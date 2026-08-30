#!/usr/bin/env python3
"""Recover retained OpenROAD H/V congestion reports without rerunning detail route."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import math
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval import EvaluationRequest, build_evaluator
from tools.routability_compare import evaluator_options, find_placed_def, placement_output_name
from tools.routability_summarize import enrich_golden_metrics


DIRECTIONAL_METRICS = (
    "horizontal_overflow", "vertical_overflow", "total_overflow", "overflow",
    "horizontal_overflow_edges", "vertical_overflow_edges",
)


def write_json(path, data):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def result_row(path):
    data = json.loads(path.read_text())
    rows = data.get("results", [])
    if len(rows) != 1 or rows[0].get("backend") != "openroad":
        raise ValueError("%s does not contain exactly one OpenROAD result" % path)
    return data, rows[0]


def finite_equal(left, right):
    return (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and math.isfinite(left)
        and math.isfinite(right)
        and math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    )


def global_route_identity(original, replay):
    original_raw = original.get("openroad_metrics", {})
    replay_raw = replay.get("openroad_metrics", {})
    checks = {}
    for metric in ("global_route__wirelength", "global_route__vias"):
        checks[metric] = {
            "original": original_raw.get(metric),
            "backfill": replay_raw.get(metric),
        }
        if not finite_equal(checks[metric]["original"], checks[metric]["backfill"]):
            raise ValueError(
                "%s mismatch: original=%r backfill=%r" % (
                    metric, checks[metric]["original"], checks[metric]["backfill"]
                )
            )
    return checks


def merge_backfill(row, metrics, artifacts, check_path):
    merged = dict(row)
    merged_metrics = dict(row.get("metrics", {}))
    for metric in DIRECTIONAL_METRICS:
        if metric in metrics:
            merged_metrics[metric] = metrics[metric]
    merged_artifacts = dict(row.get("artifacts", {}))
    merged_artifacts.update(artifacts)
    merged["metrics"] = merged_metrics
    merged["artifacts"] = merged_artifacts
    provenance = dict(row.get("metric_provenance", {}))
    provenance["directional_congestion"] = {
        "backend": "openroad",
        "operation": "deterministic_global_route_backfill",
        "identity_check": str(check_path),
    }
    merged["metric_provenance"] = provenance
    enrich_golden_metrics(merged, require_complete=True)
    return merged


def update_single_result(path, merged):
    if not path.is_file():
        return
    data = json.loads(path.read_text())
    if "results" in data:
        rows = data.get("results", [])
        if len(rows) != 1 or rows[0].get("backend") != "openroad":
            raise ValueError("cannot update non-OpenROAD result wrapper %s" % path)
        data["results"][0] = {
            **rows[0],
            "metrics": merged["metrics"],
            "artifacts": merged["artifacts"],
            "metric_provenance": merged["metric_provenance"],
        }
    else:
        data.update({
            "metrics": merged["metrics"],
            "artifacts": merged["artifacts"],
            "metric_provenance": merged["metric_provenance"],
        })
    write_json(path, data)


def existing_record(summary_path, row):
    congestion = row.get("artifacts", {}).get("congestion")
    if not congestion or not Path(congestion).is_file():
        return None
    enrich_golden_metrics(row, require_complete=True)
    method = summary_path.parents[1].name
    return {
        "method": method,
        "methods_dir": summary_path.parents[2],
        "metrics": {key: row["metrics"][key] for key in DIRECTIONAL_METRICS},
        "artifacts": row["artifacts"],
        "metric_provenance": row.get("metric_provenance", {}),
        "status": "retained",
    }


def backfill_one(
    summary_path, num_threads, timeout_sec, evaluator=None, skip_non_ok=False
):
    data, row = result_row(summary_path)
    if row.get("status") != "ok":
        if skip_non_ok:
            return {
                "method": summary_path.parents[1].name,
                "methods_dir": summary_path.parents[2],
                "status": "skipped_non_ok",
            }
        raise ValueError("OpenROAD result is not ok: %s" % summary_path)
    retained = existing_record(summary_path, row)
    if retained:
        return retained

    evaluation_dir = summary_path.parent
    method_dir = evaluation_dir.parent
    config = json.loads((method_dir / "config.json").read_text())
    placement_dir = Path(config.get("result_dir", method_dir / "placement"))
    placed_def = find_placed_def(placement_dir, placement_output_name(config))
    lef_input = config.get("lef_input", [])
    if isinstance(lef_input, str):
        lef_input = [lef_input]
    backfill_dir = evaluation_dir / "congestion_backfill"
    options = evaluator_options(config, placed_def)
    options["openroad_route_mode"] = "global"
    request = EvaluationRequest(
        design_name=row.get("design_name", placement_output_name(config)),
        lef_input=lef_input,
        def_input=str(placed_def),
        output_dir=str(backfill_dir),
        num_threads=num_threads,
        timeout_sec=timeout_sec,
        options=options,
    )
    evaluator = evaluator or build_evaluator("openroad")
    replay = evaluator.evaluate(request)
    if replay.status != "ok":
        raise RuntimeError("OpenROAD congestion backfill failed: %s" % replay.error)
    checks = global_route_identity(row.get("metrics", {}), replay.metrics)
    source_congestion = Path(replay.artifacts.get("congestion", ""))
    if not source_congestion.is_file():
        raise RuntimeError("OpenROAD backfill did not retain a congestion report")

    congestion = evaluation_dir / "openroad_congestion.rpt"
    shutil.copy2(source_congestion, congestion)
    check_path = evaluation_dir / "openroad_congestion_backfill.json"
    write_json(check_path, {
        "backend": "openroad",
        "design_name": row.get("design_name"),
        "placed_def": str(placed_def.resolve()),
        "global_route_identity": checks,
        "directional_metrics": {
            key: replay.metrics[key] for key in DIRECTIONAL_METRICS
            if key in replay.metrics
        },
    })
    extra_artifacts = {
        "congestion": str(congestion.resolve()),
        "congestion_backfill_check": str(check_path.resolve()),
    }
    for name in ("log", "script", "metrics", "guide"):
        if replay.artifacts.get(name):
            extra_artifacts["congestion_backfill_" + name] = replay.artifacts[name]
    merged = merge_backfill(row, replay.metrics, extra_artifacts, check_path.resolve())
    data["results"][0] = merged
    write_json(summary_path, data)
    update_single_result(evaluation_dir / "openroad.json", merged)
    return {
        "method": method_dir.name,
        "methods_dir": method_dir.parent,
        "metrics": {key: merged["metrics"][key] for key in DIRECTIONAL_METRICS},
        "artifacts": merged["artifacts"],
        "metric_provenance": merged["metric_provenance"],
        "status": "backfilled",
    }


def update_comparison(record, skip_missing=False):
    comparison = record["methods_dir"] / "comparison.json"
    if not comparison.is_file():
        if skip_missing:
            return False
        raise FileNotFoundError("missing completed comparison %s" % comparison)
    data = json.loads(comparison.read_text())
    matches = [
        row for row in data.get("results", [])
        if row.get("method") == record["method"] and row.get("backend") == "openroad"
    ]
    if len(matches) != 1:
        raise ValueError(
            "expected one %s OpenROAD row in %s" % (record["method"], comparison)
        )
    row = matches[0]
    row["metrics"].update(record["metrics"])
    row["artifacts"] = record["artifacts"]
    row["metric_provenance"] = record["metric_provenance"]
    write_json(comparison, data)

    csv_path = comparison.with_suffix(".csv")
    if csv_path.is_file():
        with csv_path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for csv_row in rows:
            if (
                csv_row.get("method") == record["method"]
                and csv_row.get("evaluator") == "openroad"
            ):
                csv_row.update({key: value for key, value in record["metrics"].items()})
        fields = sorted({key for csv_row in rows for key in csv_row})
        with csv_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=7200)
    parser.add_argument(
        "--skip-non-ok", action="store_true",
        help=(
            "skip failed/timeout result rows so successful siblings can be "
            "backfilled before a contract-aware resume"
        ),
    )
    args = parser.parse_args(argv)
    summaries = sorted(args.campaign_dir.resolve().rglob("summary.json"))
    if not summaries:
        raise ValueError("no evaluator summaries found")
    records = []
    failures = []
    with ThreadPoolExecutor(max_workers=min(args.max_parallel, len(summaries))) as pool:
        futures = {
            pool.submit(
                backfill_one, path, args.num_threads, args.timeout_sec,
                skip_non_ok=args.skip_non_ok,
            ): path for path in summaries
        }
        for future in as_completed(futures):
            try:
                records.append(future.result())
            except Exception as error:
                failures.append({"summary": str(futures[future]), "error": str(error)})
    if failures:
        for failure in failures:
            print("FAILED %s: %s" % (failure["summary"], failure["error"]), file=sys.stderr)
        return 1
    for record in sorted((
        record for record in records if record["status"] != "skipped_non_ok"
    ), key=lambda item: (
        str(item["methods_dir"]), item["method"]
    )):
        update_comparison(record, skip_missing=args.skip_non_ok)
    counts = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    print(json.dumps({"results": len(records), "status_counts": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
