#!/usr/bin/env python3
"""Replay frozen placements with matched-resolution RUDY and GPUGR proxies."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PYTHON_ROOT = ROOT / "install" if (ROOT / "install/dreamplace").is_dir() else ROOT
if str(PYTHON_ROOT) in sys.path:
    sys.path.remove(str(PYTHON_ROOT))
sys.path.insert(0, str(PYTHON_ROOT))

from dreamplace.ops.routability_eval import EvaluationRequest, EvaluationResult
from tools.routability_campaign import apply_path_maps, parse_path_maps
from tools.routability_compare import (
    apply_validation_policy,
    evaluator_options,
    find_placed_def,
    flatten_result,
    placement_output_name,
    run_evaluator_subprocess,
)
from tools.routability_parallel import parse_int_list, utc_now, write_status
from tools.routability_summarize import (
    campaign_identity,
    placement_plugin_activation_error,
)
from tools.routability_select_survivors import routability_metric_profile


PROXY_BACKENDS = ("rudy", "gpugr")
METRIC_PROFILE = "absolute_directional_v2"
_PROFILE = routability_metric_profile(METRIC_PROFILE)
PROXY_REQUIRED_METRICS = {
    backend: tuple(
        metric
        for category in ("primary", "secondary", "diagnostic")
        for metric_backend, metric in _PROFILE[category]
        if metric_backend == backend
    )
    for backend in PROXY_BACKENDS
}
PROXY_REQUIRED_ARTIFACTS = {
    "rudy": ("map",),
    "gpugr": ("result", "log"),
}
REPLAY_SCHEMA_VERSION = 4


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_nonnegative(metrics, name):
    value = metrics.get(name)
    return (
        isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def proxy_metric_contract_error(metrics, backend, route_x_size=None,
                                route_y_size=None):
    required = PROXY_REQUIRED_METRICS.get(backend)
    if required is None:
        return "unsupported proxy backend %s" % backend
    missing = [name for name in required if not finite_nonnegative(metrics, name)]
    if missing:
        return "missing, non-finite, or negative %s" % ", ".join(missing)
    if backend == "gpugr" and metrics["gr_wirelength"] <= 0:
        return "gr_wirelength is not positive"
    if backend == "gpugr" and metrics.get("directional_metric_schema_version") != 2:
        return "directional_metric_schema_version is not 2"
    if (
        not finite_nonnegative(metrics, "route_x_size")
        or not finite_nonnegative(metrics, "route_y_size")
        or metrics["route_x_size"] <= 0
        or metrics["route_y_size"] <= 0
    ):
        return "missing or invalid route resolution"
    if (
        route_x_size is not None
        and metrics.get("route_x_size") != route_x_size
    ):
        return "route_x_size does not match requested resolution"
    if (
        route_y_size is not None
        and metrics.get("route_y_size") != route_y_size
    ):
        return "route_y_size does not match requested resolution"
    return ""


def result_meets_proxy_contract(result, backend, route_x_size=None,
                                route_y_size=None):
    if (
        result.get("status") != "ok"
        or result.get("backend") != backend
        or proxy_metric_contract_error(
            result.get("metrics", {}), backend, route_x_size, route_y_size
        )
    ):
        return False
    artifacts = result.get("artifacts", {})
    return all(
        artifacts.get(name) and Path(artifacts[name]).is_file()
        for name in PROXY_REQUIRED_ARTIFACTS[backend]
    )


def mandatory_proxy_gate(method_results, methods, backends, route_x_size,
                         route_y_size):
    """Require every method to pass both proxy contracts independently."""
    failures = []
    for method in methods:
        results = method_results.get(method, [])
        by_backend = {}
        for result in results:
            by_backend.setdefault(result.backend, []).append(result)
        for backend in backends:
            matches = by_backend.get(backend, [])
            if len(matches) != 1 or not result_meets_proxy_contract(
                matches[0].to_dict(), backend, route_x_size, route_y_size
            ):
                failures.append("%s:%s" % (method, backend))
    return {
        "status": "passed" if not failures else "failed",
        "required_backends": list(backends),
        "failures": failures,
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


def source_design_name(data, config):
    for result in data.get("results", []):
        if result.get("design_name"):
            return result["design_name"]
    return config.get("ruplace_eval_design_name") or placement_output_name(config)


def matched_resolution_config(config, route_x_size, route_y_size):
    result = dict(config)
    feedback_x = result.get("route_num_bins_x")
    feedback_y = result.get("route_num_bins_y")
    if feedback_x != route_x_size or feedback_y != route_y_size:
        raise ValueError(
            "source feedback resolution %sx%s does not match replay %dx%d"
            % (feedback_x, feedback_y, route_x_size, route_y_size)
        )
    result["routability_eval_route_x_size"] = route_x_size
    result["routability_eval_route_y_size"] = route_y_size
    return result


def failed_result(backend, design_name, error):
    return EvaluationResult(
        backend=backend, design_name=design_name, status="failed", error=error
    )


def proxy_evaluation_identity(request, backends):
    """Identify evaluator-equivalent frozen placements independent of method."""
    options = dict(request.options)
    pl_input = options.pop("pl_input", "")
    pl_path = Path(pl_input) if pl_input else None
    payload = {
        "placement_sha256": sha256(request.def_input),
        "pl_input_sha256": sha256(pl_path) if pl_path and pl_path.is_file() else None,
        "design_name": request.design_name,
        "lef_input": list(request.lef_input),
        "verilog_input": request.verilog_input,
        "aux_input": request.aux_input,
        "num_threads": request.num_threads,
        "timeout_sec": request.timeout_sec,
        "options": options,
        "backends": list(backends),
        "metric_profile": METRIC_PROFILE,
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def write_comparison(path, payload, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    fields = sorted({key for row in rows for key in row})
    with path.with_suffix(".csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def stage_placement(source_method, output_method, config, hardlink):
    source_def = find_placed_def(
        source_method / "placement", placement_output_name(config)
    )
    placement_dir = output_method / "placement"
    placement_dir.mkdir(parents=True, exist_ok=True)
    placed_def = placement_dir / source_def.name
    if placed_def.exists():
        placed_def.unlink()
    transfer = "copy"
    if hardlink:
        try:
            os.link(source_def, placed_def)
            transfer = "hardlink"
        except OSError:
            shutil.copy2(source_def, placed_def)
            transfer = "copy_fallback"
    else:
        shutil.copy2(source_def, placed_def)
    return source_def, placed_def, transfer


def reusable_results(summary_path, backends, route_x_size, route_y_size):
    if not summary_path.is_file():
        return None
    try:
        data = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    indexed = {row.get("backend"): row for row in data.get("results", [])}
    if not all(
        result_meets_proxy_contract(
            indexed.get(name, {}), name, route_x_size, route_y_size
        )
        for name in backends
    ):
        return None
    return [EvaluationResult(**indexed[name]) for name in backends]


def validated_replay_matches(path, source, methods, backends, route_x_size, route_y_size):
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text())
        source_data = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    replay = data.get("proxy_replay", {})
    if (
        data.get("validation", {}).get("status") != "validated"
        or data.get("validation", {}).get(
            "mandatory_proxy_gate", {}
        ).get("status") != "passed"
        or replay.get("schema_version") != REPLAY_SCHEMA_VERSION
        or replay.get("metric_profile") != METRIC_PROFILE
        or replay.get("route_x_size") != route_x_size
        or replay.get("route_y_size") != route_y_size
        or set(replay.get("evaluators", [])) != set(backends)
    ):
        return False
    try:
        if Path(data.get("source_comparison", "")).resolve() != source.resolve():
            return False
    except (OSError, RuntimeError):
        return False
    placements = {row.get("method"): row for row in data.get("placements", [])}
    source_placements = {
        row.get("method"): row for row in source_data.get("placements", [])
    }
    if set(placements) != set(methods) or set(source_placements) < set(methods):
        return False
    results = data.get("results", [])
    provenance = {row.get("method"): row for row in replay.get("provenance", [])}
    reuse = replay.get("identical_placement_evaluation_reuse", [])
    if (
        replay.get("deduplicated_method_count") != len(reuse)
        or replay.get("unique_evaluation_count") != len(methods) - len(reuse)
    ):
        return False
    for row in reuse:
        method = row.get("method")
        source_method = row.get("source_method")
        if (
            method not in methods
            or source_method not in methods
            or method == source_method
            or not row.get("evaluation_identity")
            or provenance.get(method, {}).get("evaluation_reused_from_method")
            != source_method
            or provenance.get(method, {}).get("source_placement_sha256")
            != provenance.get(source_method, {}).get("source_placement_sha256")
        ):
            return False
    for method in methods:
        config_path = source.parent / method / "config.json"
        try:
            config = json.loads(config_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        if (
            placement_plugin_activation_error(source_placements[method], config)
            or placement_plugin_activation_error(placements[method], config)
            or provenance.get(method, {}).get("source_config_sha256") != sha256(config_path)
        ):
            return False
        output_config = path.parent / method / "config.json"
        try:
            current = json.loads(output_config.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        if (
            current.get("routability_eval_route_x_size") != route_x_size
            or current.get("routability_eval_route_y_size") != route_y_size
        ):
            return False
        for backend in backends:
            matches = [
                row for row in results
                if row.get("method") == method and row.get("backend") == backend
            ]
            if len(matches) != 1 or not result_meets_proxy_contract(
                matches[0], backend, route_x_size, route_y_size
            ):
                return False
    return True


def replay_comparison(source, source_root, output_root, methods, backends,
                      path_maps, num_threads, timeout_sec, route_x_size,
                      route_y_size, gpu, evaluator_python_root=None,
                      hardlink_placements=False,
                      resume_methods=False):
    case, seed = campaign_identity(source, source_root)
    data = json.loads(source.read_text())
    source_methods = source.parent
    output_methods = output_root / case / ("seed_%d" % seed) / case / "methods"
    source_placements = {
        row.get("method"): row for row in data.get("placements", [])
    }
    placements = []
    serialized_results = []
    method_results = {method: [] for method in methods}
    provenance = []
    evaluation_cache = {}
    evaluation_reuse = []
    rows = []

    source_validation_error = ""
    if data.get("validation", {}).get("status") != "validated":
        source_validation_error = "source comparison is not validated"

    for method in methods:
        source_method = source_methods / method
        output_method = output_methods / method
        eval_dir = output_method / "evaluation"
        eval_dir.mkdir(parents=True, exist_ok=True)
        placement = dict(source_placements.get(method, {
            "method": method, "status": "failed",
            "error": "method is absent from source comparison",
        }))
        placements.append(placement)
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
        previous_config = None
        if resume_methods and output_config_path.is_file():
            try:
                previous_config = json.loads(output_config_path.read_text())
            except (OSError, json.JSONDecodeError):
                previous_config = None
        design_name = "unknown"
        config = {}
        error = source_validation_error
        try:
            if error:
                raise ValueError(error)
            source_config = json.loads(config_path.read_text())
            activation_error = placement_plugin_activation_error(placement, source_config)
            if activation_error:
                raise ValueError("plugin activation contract: %s" % activation_error)
            config = matched_resolution_config(
                remap_config(source_config, path_maps), route_x_size, route_y_size
            )
            config["ruplace_route_gpu"] = gpu
            design_name = source_design_name(data, config)
            source_def, placed_def, transfer = stage_placement(
                source_method, output_method, config, hardlink_placements
            )
            config["result_dir"] = str((output_method / "placement").resolve())
            output_config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
            provenance_row = {
                "method": method,
                "source_config": str(config_path.resolve()),
                "source_config_sha256": sha256(config_path),
                "source_placement": str(source_def.resolve()),
                "source_placement_sha256": sha256(source_def),
                "staged_placement": str(placed_def.resolve()),
                "staged_placement_sha256": sha256(placed_def),
                "transfer": transfer,
                "plugin_activation": placement,
                "evaluation_reused_from_method": None,
            }
            provenance.append(provenance_row)
        except (FileNotFoundError, KeyError, OSError, RuntimeError, ValueError) as exc:
            error = "cannot stage frozen placement: %s" % exc
            placed_def = None

        results = None
        if not error and resume_methods and previous_config == config:
            results = reusable_results(
                eval_dir / "summary.json", backends, route_x_size, route_y_size
            )
        if error:
            results = [failed_result(name, design_name, error) for name in backends]
        elif results is None:
            request = EvaluationRequest(
                design_name=design_name,
                lef_input=config.get("lef_input", []),
                def_input=str(placed_def),
                verilog_input=(
                    config.get("ruplace_eval_verilog_input")
                    or config.get("verilog_input", "")
                ),
                aux_input=config.get("aux_input", ""),
                output_dir=str(eval_dir),
                num_threads=num_threads,
                timeout_sec=timeout_sec,
                options=evaluator_options(config, placed_def),
            )
            identity = proxy_evaluation_identity(request, backends)
            cached = evaluation_cache.get(identity)
            if cached is not None:
                source_method, cached_results = cached
                results = [
                    EvaluationResult(**result.to_dict()) for result in cached_results
                ]
                provenance_row["evaluation_reused_from_method"] = source_method
                evaluation_reuse.append({
                    "method": method,
                    "source_method": source_method,
                    "evaluation_identity": identity,
                })
            else:
                results = [
                    run_evaluator_subprocess(
                        request, name,
                        **(
                            {"python_root": evaluator_python_root}
                            if evaluator_python_root is not None else {}
                        )
                    ) for name in backends
                ]
                if all(
                    result_meets_proxy_contract(
                        result.to_dict(), result.backend,
                        route_x_size, route_y_size,
                    )
                    for result in results
                ):
                    evaluation_cache[identity] = (method, results)
        for result in results:
            contract_error = (
                proxy_metric_contract_error(
                    result.metrics, result.backend, route_x_size, route_y_size
                )
                if result.status == "ok" else ""
            )
            if contract_error:
                result.status = "failed"
                result.error = "proxy metric contract: %s" % contract_error
            method_results[method].append(result)
            serialized_results.append({"method": method, **result.to_dict()})
            rows.append(flatten_result(method, result))
        (eval_dir / "summary.json").write_text(json.dumps({
            "metric_profile": METRIC_PROFILE,
            "route_x_size": route_x_size,
            "route_y_size": route_y_size,
            "results": [result.to_dict() for result in results],
        }, indent=2, sort_keys=True) + "\n")

    validation = apply_validation_policy(method_results, rows, serialized_results)
    proxy_gate = mandatory_proxy_gate(
        method_results, methods, backends, route_x_size, route_y_size
    )
    validation["mandatory_proxy_gate"] = proxy_gate
    if proxy_gate["status"] != "passed":
        validation["status"] = "unvalidated"
    comparison = output_methods / "comparison.json"
    write_comparison(comparison, {
        "source_comparison": str(source.resolve()),
        "proxy_replay": {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "metric_profile": METRIC_PROFILE,
            "evaluators": list(backends),
            "route_x_size": route_x_size,
            "route_y_size": route_y_size,
            "feedback_validator_resolution_matched": True,
            "placement_rerun": False,
            "proposal_evidence_scope": "development_only",
            "numeric_backend_mixing": False,
            "gpu": gpu,
            "identical_placement_evaluation_reuse": evaluation_reuse,
            "deduplicated_method_count": len(evaluation_reuse),
            "unique_evaluation_count": len(methods) - len(evaluation_reuse),
            "provenance": provenance,
        },
        "validation": validation,
        "placements": placements,
        "results": serialized_results,
    }, rows)
    return case, seed, (
        validation["status"] == "validated"
        and proxy_gate["status"] == "passed"
    ), comparison


def expected_sources(source_root, cases, seeds):
    paths = sorted(source_root.rglob("comparison.json"))
    indexed = {}
    for path in paths:
        key = campaign_identity(path, source_root)
        if key in indexed:
            raise ValueError("duplicate source comparison for %s seed %d" % key)
        indexed[key] = path
    expected = {(case, seed) for case in cases for seed in seeds}
    missing = sorted(expected - set(indexed))
    if missing:
        raise ValueError("source campaign is incomplete: missing %s" % ", ".join(
            "%s/seed_%d" % key for key in missing
        ))
    unexpected = sorted(set(indexed) - expected)
    if unexpected:
        raise ValueError("source campaign contains out-of-scope comparisons: %s" % ", ".join(
            "%s/seed_%d" % key for key in unexpected
        ))
    return [indexed[key] for key in sorted(expected)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-campaign", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--methods", required=True)
    parser.add_argument("--evaluators", default="rudy,gpugr")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--seeds", default="1000,2000,3000")
    parser.add_argument("--gpus", default="0,1,2,3")
    parser.add_argument("--route-x-size", type=int, required=True)
    parser.add_argument("--route-y-size", type=int, required=True)
    parser.add_argument("--path-map", action="append", default=[])
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument(
        "--evaluator-python-root", type=Path,
        help="package root containing the dreamplace evaluator implementation",
    )
    parser.add_argument("--max-parallel", type=int, default=0)
    parser.add_argument("--hardlink-placements", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    source_root = args.source_campaign.resolve()
    methods = [value.strip() for value in args.methods.split(",") if value.strip()]
    backends = [value.strip() for value in args.evaluators.split(",") if value.strip()]
    cases = [value.strip() for value in args.cases.split(",") if value.strip()]
    seeds = parse_int_list(args.seeds)
    gpus = parse_int_list(args.gpus)
    if not methods or not cases or not seeds or not gpus:
        raise ValueError("methods, cases, seeds, and GPUs must be nonempty")
    if len(methods) != len(set(methods)) or len(cases) != len(set(cases)):
        raise ValueError("methods and cases must not contain duplicates")
    if set(backends) != set(PROXY_BACKENDS) or len(backends) != len(PROXY_BACKENDS):
        raise ValueError("proxy replay requires exactly rudy and gpugr")
    if args.route_x_size <= 0 or args.route_y_size <= 0:
        raise ValueError("route resolution must be positive")
    evaluator_root = (
        args.evaluator_python_root.resolve()
        if args.evaluator_python_root is not None else None
    )
    if evaluator_root is not None and not (evaluator_root / "dreamplace").is_dir():
        raise ValueError(
            "evaluator Python root has no dreamplace package: %s"
            % evaluator_root
        )
    paths = expected_sources(source_root, cases, seeds)
    path_maps = parse_path_maps(args.path_map)
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
    pending = []
    for source in paths:
        case, seed = campaign_identity(source, source_root)
        result_dir = args.output_dir / case / ("seed_%d" % seed)
        comparison = result_dir / case / "methods" / "comparison.json"
        reusable = args.resume and validated_replay_matches(
            comparison, source, methods, backends,
            args.route_x_size, args.route_y_size,
        )
        job_id = "%s__seed_%d" % (case, seed)
        prior = prior_jobs.get(job_id, {})
        job = {
            "job_id": job_id, "case": case, "seed": seed,
            "gpu": prior.get("gpu", "") if reusable else "",
            "status": "completed" if reusable else "pending",
            "returncode": 0 if reusable else "",
            "started_at": prior.get("started_at", "") if reusable else "",
            "finished_at": prior.get("finished_at", "") if reusable else "",
            "result_dir": str(result_dir.resolve()),
            "log": str(comparison.resolve()) if reusable else str(
                (result_dir / "proxy_replay.log").resolve()
            ),
        }
        jobs.append(job)
        if not reusable:
            pending.append((source, job))
    write_status(args.output_dir, jobs)
    if not pending:
        return 0

    gpu_pool = queue.Queue()
    for gpu in gpus:
        gpu_pool.put(gpu)
    status_lock = threading.Lock()

    def run_job(source, job):
        gpu = gpu_pool.get()
        try:
            with status_lock:
                job.update({"gpu": gpu, "status": "running", "started_at": utc_now()})
                write_status(args.output_dir, jobs)
            try:
                _, _, ok, comparison = replay_comparison(
                    source, source_root, args.output_dir, methods, backends,
                    path_maps, args.num_threads, args.timeout_sec,
                    args.route_x_size, args.route_y_size, gpu,
                    evaluator_root,
                    args.hardlink_placements, args.resume,
                )
                log = str(comparison.resolve())
            except Exception as exc:
                ok = False
                error_log = Path(job["result_dir"]) / "proxy_replay.error.log"
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
        finally:
            gpu_pool.put(gpu)

    workers = min(
        len(pending), len(gpus),
        args.max_parallel if args.max_parallel > 0 else len(gpus),
    )
    all_ok = True
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_job, source, job) for source, job in pending]
        for future in as_completed(futures):
            all_ok = future.result() and all_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
