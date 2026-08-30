#!/usr/bin/env python3
"""Replay frozen campaign placements with common golden routing backends."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import threading


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
from tools.routability_summarize import (
    campaign_gate,
    campaign_identity,
    enrich_golden_metrics,
    placement_plugin_activation_error,
)


RESUME_REQUIRED_METRICS = {
    "openroad": (
        "wirelength", "vias", "horizontal_overflow", "vertical_overflow",
        "drc_violations", "unrouted_nets", "short_violations",
    ),
    "innovus": (
        "wirelength", "vias", "drc_violations", "unrouted_nets",
        "short_violations", "connectivity_violations", "open_violations",
    ),
}

RESUME_REQUIRED_ARTIFACTS = {
    "openroad": (
        "log", "drc", "metrics", "congestion", "guide", "script",
    ),
    "innovus": ("log", "drc", "metrics", "connectivity", "script"),
}


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


def enforce_golden_metric_contract(config):
    """Golden replay always includes detailed-route wirelength and DRC."""
    result = dict(config)
    result["routability_eval_openroad_route_mode"] = "detailed"
    result["routability_eval_innovus_route_mode"] = "detailed"
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


def finite_metric(metrics, name):
    value = metrics.get(name)
    return isinstance(value, (int, float)) and math.isfinite(value)


def golden_metric_contract_error(metrics, backend):
    """Return an error when a golden result cannot support routed-QoR ranking."""
    required = RESUME_REQUIRED_METRICS.get(backend)
    if required is None:
        return "unsupported golden backend %s" % backend
    for metric in required:
        if not finite_metric(metrics, metric):
            return "missing or non-finite %s" % metric
        if metrics[metric] < 0:
            return "negative %s" % metric
    if metrics["wirelength"] <= 0:
        return "nonpositive wirelength"
    if backend == "innovus" and not (
        all(
            finite_metric(metrics, metric) and metrics[metric] >= 0
            for metric in ("horizontal_overflow", "vertical_overflow")
        )
        or all(
            finite_metric(metrics, metric) and metrics[metric] >= 0
            for metric in ("horizontal_congestion", "vertical_congestion")
        )
    ):
        return "missing or invalid horizontal/vertical congestion"
    return ""


def detailed_route_contract_error(result, backend):
    """Prove retained golden metrics came from a detailed-route invocation."""
    artifacts = result.get("artifacts", {})
    try:
        script = Path(artifacts.get("script", "")).read_text(errors="replace")
    except (OSError, ValueError):
        return "missing or unreadable route script"
    active_lines = [
        line.strip() for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if backend == "openroad":
        if not any(re.match(r"^detailed_route(?:\s|$)", line) for line in active_lines):
            return "OpenROAD script does not invoke detailed_route"
        if not any(
            re.match(r"^report_wire_length(?:\s|$)", line)
            and re.search(r"(?:^|\s)-detailed_route(?:\s|$)", line)
            for line in active_lines
        ):
            return "OpenROAD script does not report detailed-route wirelength"
    elif backend == "innovus":
        if not any(re.match(r"^globalDetailRoute(?:\s|$)", line) for line in active_lines):
            return "Innovus script does not invoke globalDetailRoute"
        try:
            metric_text = Path(artifacts.get("metrics", "")).read_text(
                errors="replace"
            )
        except (OSError, ValueError):
            return "missing or unreadable Innovus metrics artifact"
        route_modes = [
            line.split("=", 1)[1].strip().lower()
            for line in metric_text.splitlines()
            if line.strip().lower().startswith("route_mode=")
        ]
        if route_modes != ["detailed"]:
            return "Innovus metrics do not declare route_mode=detailed"
    else:
        return "unsupported golden backend %s" % backend
    return ""


def result_meets_resume_contract(result, backend):
    """Reject stale golden results that predate the current metric contract."""
    if (
        result.get("status") != "ok"
        or not result.get("authoritative_for_comparison", False)
        or result.get("backend") != backend
    ):
        return False
    if golden_metric_contract_error(result.get("metrics", {}), backend):
        return False
    artifacts = result.get("artifacts", {})
    if not all(
        artifacts.get(name) and Path(artifacts[name]).is_file()
        for name in RESUME_REQUIRED_ARTIFACTS[backend]
    ):
        return False
    if detailed_route_contract_error(result, backend):
        return False
    try:
        enrich_golden_metrics(result, require_complete=True)
    except ValueError:
        return False
    return True


def reusable_method_results(path, evaluators):
    """Load one method's routed results only when metrics and artifacts survive."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    indexed = {
        row.get("backend"): row for row in data.get("results", [])
        if row.get("backend") in evaluators
    }
    results = []
    for backend in evaluators:
        row = indexed.get(backend)
        if row is None or row.get("status") != "ok" or golden_metric_contract_error(
            row.get("metrics", {}), backend
        ):
            return None
        if not result_meets_resume_contract(
            {**row, "authoritative_for_comparison": True}, backend
        ):
            return None
        artifacts = row.get("artifacts", {})
        results.append(EvaluationResult(
            backend=backend,
            design_name=row.get("design_name", "unknown"),
            status=row.get("status", "ok"),
            runtime_sec=row.get("runtime_sec", 0.0),
            metrics=row.get("metrics", {}),
            artifacts=artifacts,
            error=row.get("error", ""),
            schema_version=row.get("schema_version", 1),
        ))
    return results


def validated_replay_matches(path, source, methods, evaluators,
                             snap_manufacturing_grid=False):
    """Return true only for a complete replay produced under this contract."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text())
        source_data = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("validation", {}).get("status") != "validated":
        return False
    try:
        if Path(data.get("source_comparison", "")).resolve() != source.resolve():
            return False
    except (OSError, RuntimeError):
        return False
    placement_rows = data.get("placements", [])
    source_placement_rows = source_data.get("placements", [])
    placements = {row.get("method"): row for row in placement_rows}
    source_placements = {row.get("method"): row for row in source_placement_rows}
    if (
        len(placements) != len(placement_rows)
        or len(source_placements) != len(source_placement_rows)
        or set(placements) != set(methods)
        or set(source_placements) < set(methods)
    ):
        return False
    for method in methods:
        try:
            config = json.loads((source.parent / method / "config.json").read_text())
        except (OSError, json.JSONDecodeError):
            return False
        if (
            placement_plugin_activation_error(source_placements[method], config)
            or placement_plugin_activation_error(placements[method], config)
        ):
            return False
    if snap_manufacturing_grid:
        snapped = {
            row.get("method") for row in data.get("preprocessing", [])
            if row.get("operation") == "snap_manufacturing_grid"
            and row.get("status") == "ok"
        }
        if snapped != set(methods):
            return False
    results = data.get("results", [])
    return all(any(
        row.get("method") == method
        and result_meets_resume_contract(row, backend)
        for row in results
    ) for method in methods for backend in evaluators)


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
                      snap_manufacturing_grid=False, hardlink_placements=False,
                      resume_methods=False, evaluator_python_root=None):
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
        output_config_path = output_method / "config.json"
        prior_config = None
        if resume_methods and output_config_path.is_file():
            try:
                prior_config = json.loads(output_config_path.read_text())
            except (OSError, json.JSONDecodeError):
                prior_config = None
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
            source_config = json.loads(config_path.read_text())
            activation_error = placement_plugin_activation_error(
                placement, source_config
            )
            if activation_error:
                raise ValueError("plugin activation contract: %s" % activation_error)
            config = enforce_golden_metric_contract(remap_config(
                source_config, path_maps
            ))
            design_name = source_design_name(data, config)
            source_def = find_placed_def(
                source_method / "placement", placement_output_name(config)
            )
            placement_dir.mkdir(parents=True, exist_ok=True)
            placed_def = placement_dir / source_def.name
            if hardlink_placements:
                if placed_def.exists():
                    placed_def.unlink()
                os.link(source_def, placed_def)
            else:
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
            output_config_path.write_text(
                json.dumps(config, indent=2, sort_keys=True) + "\n"
            )
        except (FileNotFoundError, KeyError, OSError, RuntimeError, ValueError) as exc:
            error = "cannot stage frozen placement: %s" % exc
            placed_def = None

        if error:
            results = [failed_result(backend, design_name, error) for backend in evaluators]
        else:
            results = (
                reusable_method_results(eval_dir / "summary.json", evaluators)
                if resume_methods and prior_config == config else None
            )
            if results is None:
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
                    run_evaluator_subprocess(
                        request, backend,
                        **(
                            {"python_root": evaluator_python_root}
                            if evaluator_python_root is not None else {}
                        )
                    )
                    for backend in evaluators
                ]
            for result in results:
                contract_error = golden_metric_contract_error(
                    result.metrics, result.backend
                ) if result.status == "ok" else ""
                if contract_error:
                    result.status = "failed"
                    result.error = "golden metric contract: %s" % contract_error
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
        "--evaluator-python-root", type=Path,
        help="package root containing the dreamplace evaluator implementation",
    )
    parser.add_argument(
        "--max-parallel", type=int, default=1,
        help="maximum number of case-seed golden replays to run concurrently",
    )
    parser.add_argument(
        "--snap-manufacturing-grid", action="store_true",
        help="snap component locations once before replaying all golden evaluators",
    )
    parser.add_argument(
        "--hardlink-placements", action="store_true",
        help=(
            "hardlink immutable source DEFs into the output tree; source and output "
            "must be on the same filesystem"
        ),
    )
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "skip existing validated case-seeds only when every selected method "
            "and golden backend satisfies the current detailed-route metric contract"
        ),
    )
    args = parser.parse_args(argv)
    evaluator_root = (
        args.evaluator_python_root.resolve()
        if args.evaluator_python_root is not None else None
    )
    if evaluator_root is not None and not (evaluator_root / "dreamplace").is_dir():
        raise ValueError(
            "evaluator Python root has no dreamplace package: %s"
            % evaluator_root
        )

    source_root = args.source_campaign.resolve()
    methods = [value.strip() for value in args.methods.split(",") if value.strip()]
    evaluators = [value.strip() for value in args.evaluators.split(",") if value.strip()]
    selected_cases = {value.strip() for value in args.cases.split(",") if value.strip()}
    if not methods or not evaluators:
        raise ValueError("at least one method and evaluator are required")
    if args.max_parallel < 1:
        raise ValueError("max-parallel must be at least one")
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
    prior_jobs = {}
    prior_status = args.output_dir / "parallel_status.json"
    if args.resume and prior_status.is_file():
        try:
            prior_jobs = {
                row.get("job_id"): row
                for row in json.loads(prior_status.read_text()).get("jobs", [])
            }
        except (OSError, json.JSONDecodeError):
            prior_jobs = {}
    jobs = []
    pending_paths = []
    for path in paths:
        case, seed = campaign_identity(path, source_root)
        result_dir = args.output_dir / case / ("seed_%d" % seed)
        comparison = result_dir / case / "methods" / "comparison.json"
        reusable = args.resume and validated_replay_matches(
            comparison, path, methods, evaluators,
            snap_manufacturing_grid=args.snap_manufacturing_grid,
        )
        prior = prior_jobs.get("%s__seed_%d" % (case, seed), {})
        job = {
            "job_id": "%s__seed_%d" % (case, seed),
            "case": case, "seed": seed, "gpu": "local",
            "status": "completed" if reusable else "pending",
            "returncode": 0 if reusable else "",
            "started_at": prior.get("started_at", "") if reusable else "",
            "finished_at": prior.get("finished_at", "") if reusable else "",
            "result_dir": str(result_dir.resolve()),
            "log": str(comparison.resolve()) if reusable else str(
                (result_dir / "golden_replay.log").resolve()
            ),
        }
        jobs.append(job)
        if not reusable:
            pending_paths.append((path, job))
    write_status(args.output_dir, jobs)

    path_maps = parse_path_maps(args.path_map)
    status_lock = threading.Lock()

    def run_job(path, job):
        with status_lock:
            job.update({"status": "running", "started_at": utc_now()})
            write_status(args.output_dir, jobs)
        try:
            _, _, ok, comparison = replay_comparison(
                path, source_root, args.output_dir, methods, evaluators,
                path_maps, args.num_threads, args.timeout_sec,
                args.snap_manufacturing_grid, args.hardlink_placements,
                args.resume,
                **(
                    {"evaluator_python_root": evaluator_root}
                    if evaluator_root is not None else {}
                )
            )
            log = str(comparison)
        except Exception as exc:
            ok = False
            error_log = Path(job["result_dir"]) / "golden_replay.error.log"
            error_log.parent.mkdir(parents=True, exist_ok=True)
            error_log.write_text("%s: %s\n" % (type(exc).__name__, exc))
            log = str(error_log.resolve())
        with status_lock:
            job.update({
                "status": "completed" if ok else "failed",
                "returncode": 0 if ok else 1,
                "finished_at": utc_now(),
                "log": log,
            })
            write_status(args.output_dir, jobs)
        return ok

    all_ok = True
    if not pending_paths:
        return 0
    with ThreadPoolExecutor(
        max_workers=min(args.max_parallel, len(pending_paths))
    ) as executor:
        futures = [
            executor.submit(run_job, path, job)
            for path, job in pending_paths
        ]
        for future in as_completed(futures):
            all_ok = future.result() and all_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
