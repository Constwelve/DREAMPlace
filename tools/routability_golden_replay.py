#!/usr/bin/env python3
"""Replay frozen campaign placements with common golden routing backends."""

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval import EvaluationRequest, EvaluationResult, validation_role
from tools.routability_campaign import apply_path_maps, parse_path_maps
from tools.routability_compare import (
    apply_validation_policy,
    evaluator_options,
    find_placed_def,
    flatten_result,
    placement_output_name,
    run_evaluator_subprocess,
)
from tools.routability_parallel import utc_now, write_status
from tools.routability_snap_def import snap_def
from tools.routability_summarize import campaign_gate, campaign_identity


def remap_config(config, path_maps):
    result = dict(config)
    lef_input = result.get("lef_input", [])
    if isinstance(lef_input, str):
        lef_input = [lef_input]
    result["lef_input"] = [apply_path_maps(value, path_maps) for value in lef_input]
    for key in ("def_input", "verilog_input", "ruplace_eval_verilog_input", "aux_input"):
        if result.get(key):
            result[key] = apply_path_maps(result[key], path_maps)
    return result


def source_design_name(data, config):
    for result in data.get("results", []):
        if result.get("design_name"):
            return result["design_name"]
    return placement_output_name(config)


def failed_result(backend, design_name, error):
    return EvaluationResult(
        backend=backend, design_name=design_name, status="failed", error=error
    )


def write_comparison(path, placements, results, validation, source, preprocessing, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source_comparison": str(source),
        "validation": validation,
        "placements": placements,
        "preprocessing": preprocessing,
        "results": results,
    }, indent=2, sort_keys=True) + "\n")
    fields = sorted({key for row in rows for key in row})
    with path.with_suffix(".csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def replay_comparison(source, source_root, output_root, methods, evaluators,
                      path_maps, num_threads, timeout_sec,
                      snap_manufacturing_grid=False):
    case, seed = campaign_identity(source, source_root)
    data = json.loads(source.read_text())
    source_validation_error = ""
    if data.get("validation", {}).get("status") != "validated":
        source_validation_error = "source comparison is not validated"
    source_methods = source.parent
    output_methods = output_root / case / ("seed_%d" % seed) / case / "methods"
    placements_by_method = {
        row.get("method"): row for row in data.get("placements", [])
    }
    selected_placements = []
    preprocessing = []
    serialized_results = []
    rows = []
    method_results = {method: [] for method in methods}

    for method in methods:
        source_method = source_methods / method
        output_method = output_methods / method
        eval_dir = output_method / "evaluation"
        placement_dir = output_method / "placement"
        eval_dir.mkdir(parents=True, exist_ok=True)
        placement = dict(placements_by_method.get(method, {
            "method": method, "status": "failed",
            "error": "method is absent from source comparison",
        }))
        selected_placements.append(placement)
        placement_row = {
            key: value for key, value in placement.items()
            if key != "routability_plugin_summary"
        }
        placement_row.update({
            "evaluator": "placement",
            "validation_role": "placement_metric",
            "authoritative_for_comparison": False,
        })
        rows.append(placement_row)

        config_path = source_method / "config.json"
        config = {}
        design_name = "unknown"
        error = source_validation_error
        if placement.get("status") != "ok":
            error = error or "source placement status is %s" % placement.get(
                "status", "missing"
            )
        try:
            if error:
                raise ValueError(error)
            config = remap_config(json.loads(config_path.read_text()), path_maps)
            design_name = source_design_name(data, config)
            source_def = find_placed_def(
                source_method / "placement", placement_output_name(config)
            )
            placement_dir.mkdir(parents=True, exist_ok=True)
            placed_def = placement_dir / source_def.name
            shutil.copy2(source_def, placed_def)
            if snap_manufacturing_grid:
                snapped_def = placement_dir / (
                    source_def.name[:-4] + ".manufacturing_grid.def"
                    if source_def.name.lower().endswith(".def")
                    else source_def.name + ".manufacturing_grid.def"
                )
                snap_report = placement_dir / "manufacturing_grid_snap.json"
                report = snap_def(
                    placed_def, config.get("lef_input", []), snapped_def, snap_report
                )
                preprocessing.append({
                    "method": method,
                    "operation": "snap_manufacturing_grid",
                    "status": "ok",
                    "evaluated_def": str(snapped_def.resolve()),
                    "report": str(snap_report.resolve()),
                    "input_sha256": report["input_sha256"],
                    "output_sha256": report["output_sha256"],
                    "changed_components": report["changed_components"],
                    "changed_coordinates": report["changed_coordinates"],
                    "max_delta_x_dbu": report["max_delta_x_dbu"],
                    "max_delta_y_dbu": report["max_delta_y_dbu"],
                })
                placed_def = snapped_def
            config["result_dir"] = str(placement_dir.resolve())
            (output_method / "config.json").write_text(
                json.dumps(config, indent=2, sort_keys=True) + "\n"
            )
        except (FileNotFoundError, KeyError, OSError, RuntimeError, ValueError) as exc:
            error = "cannot stage frozen placement: %s" % exc
            placed_def = None

        if error:
            results = [failed_result(backend, design_name, error) for backend in evaluators]
        else:
            verilog = config.get("ruplace_eval_verilog_input") or config.get(
                "verilog_input", ""
            )
            request = EvaluationRequest(
                design_name=design_name,
                lef_input=config.get("lef_input", []),
                def_input=str(placed_def),
                verilog_input=verilog,
                aux_input=config.get("aux_input", ""),
                output_dir=str(eval_dir),
                num_threads=num_threads,
                timeout_sec=timeout_sec,
                options=evaluator_options(config, placed_def),
            )
            results = [
                run_evaluator_subprocess(request, backend) for backend in evaluators
            ]
        method_results[method].extend(results)
        for result in results:
            serialized_results.append({"method": method, **result.to_dict()})
            rows.append(flatten_result(method, result))

    validation = apply_validation_policy(method_results, rows, serialized_results)
    comparison = output_methods / "comparison.json"
    write_comparison(
        comparison, selected_placements, serialized_results, validation, source,
        preprocessing, rows
    )
    return case, seed, validation["status"] == "validated", comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-campaign", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--methods", required=True)
    parser.add_argument("--evaluators", default="openroad,innovus")
    parser.add_argument("--cases", default="")
    parser.add_argument("--path-map", action="append", default=[])
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument(
        "--snap-manufacturing-grid", action="store_true",
        help="snap component locations once before replaying all golden evaluators",
    )
    args = parser.parse_args(argv)

    source_root = args.source_campaign.resolve()
    methods = [value.strip() for value in args.methods.split(",") if value.strip()]
    evaluators = [value.strip() for value in args.evaluators.split(",") if value.strip()]
    selected_cases = {value.strip() for value in args.cases.split(",") if value.strip()}
    if not methods or not evaluators:
        raise ValueError("at least one method and evaluator are required")
    non_golden = [backend for backend in evaluators if validation_role(backend) != "golden"]
    if non_golden:
        raise ValueError(
            "golden replay rejects non-golden evaluators: %s" % ", ".join(non_golden)
        )
    all_paths = sorted(source_root.rglob("comparison.json"))
    all_keys = {campaign_identity(path, source_root) for path in all_paths}
    source_gate = campaign_gate(source_root, all_keys)
    if source_gate["incomplete_jobs"] or source_gate["missing_comparisons"]:
        raise ValueError("source campaign is incomplete")
    paths = []
    for path in all_paths:
        case, _ = campaign_identity(path, source_root)
        if not selected_cases or case in selected_cases:
            paths.append(path)
    if not paths:
        raise ValueError("no source comparisons selected")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for path in paths:
        case, seed = campaign_identity(path, source_root)
        result_dir = args.output_dir / case / ("seed_%d" % seed)
        jobs.append({
            "job_id": "%s__seed_%d" % (case, seed),
            "case": case, "seed": seed, "gpu": "local",
            "status": "pending", "returncode": "", "started_at": "",
            "finished_at": "", "result_dir": str(result_dir.resolve()),
            "log": str((result_dir / "golden_replay.log").resolve()),
        })
    write_status(args.output_dir, jobs)

    path_maps = parse_path_maps(args.path_map)
    all_ok = True
    for path, job in zip(paths, jobs):
        job.update({"status": "running", "started_at": utc_now()})
        write_status(args.output_dir, jobs)
        _, _, ok, comparison = replay_comparison(
            path, source_root, args.output_dir, methods, evaluators,
            path_maps, args.num_threads, args.timeout_sec,
            args.snap_manufacturing_grid,
        )
        job.update({
            "status": "completed" if ok else "failed",
            "returncode": 0 if ok else 1,
            "finished_at": utc_now(),
            "log": str(comparison),
        })
        all_ok = ok and all_ok
        write_status(args.output_dir, jobs)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
