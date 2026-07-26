#!/usr/bin/env python3
"""Run plugin ablations and evaluate every placed DEF with independent backends."""

import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "install" if (ROOT / "install/dreamplace").is_dir() else ROOT
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from dreamplace.ops.routability_eval import (
    DEFAULT_VALIDATION_EVALUATORS,
    EvaluationRequest,
    EvaluationResult,
    common_validation_backends,
    select_common_validation_role,
    validation_role,
)


DEFAULT_EVALUATORS = ",".join(DEFAULT_VALIDATION_EVALUATORS)


def placement_output_name(config):
    """Match Params.design_name(), which controls DREAMPlace's result path."""
    for key, suffix in (("aux_input", ".aux"), ("verilog_input", ".v"),
                        ("def_input", ".def")):
        value = config.get(key)
        if value:
            name = Path(value).name
            return name[:-len(suffix)] if name.lower().endswith(suffix) else Path(name).stem
    raise ValueError("base config requires aux_input, verilog_input, or def_input")


def find_placed_def(result_dir, output_name):
    candidates = [
        result_dir / output_name / (output_name + ".dp.def"),
        result_dir / output_name / (output_name + ".lg.def"),
        result_dir / output_name / (output_name + ".gp.def"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for suffix in ("*.dp.def", "*.lg.def", "*.gp.def", "*.def"):
        found = sorted(result_dir.rglob(suffix))
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            matching = [path for path in found if path.name == output_name + suffix[1:]]
            if len(matching) == 1:
                return matching[0]
            raise RuntimeError("ambiguous placed DEFs below %s: %s" %
                               (result_dir, ", ".join(str(path) for path in found)))
    raise FileNotFoundError("no placed DEF below %s" % result_dir)


def evaluator_options(config, placed_def):
    mapping = {
        "ruplace_xplace_root": "xplace_root",
        "ruplace_route_gpu": "gpu",
        "routability_eval_rrr_iters": "rrr_iters",
        "routability_eval_route_size": "route_size",
        "routability_eval_route_x_size": "route_x_size",
        "routability_eval_route_y_size": "route_y_size",
        "routability_eval_cugr_root": "cugr_root",
        "routability_eval_cugr_threads": "cugr_threads",
        "routability_eval_nctugr_root": "nctugr_root",
        "routability_eval_openroad_binary": "openroad_binary",
        "routability_eval_cadence_wrapper": "cadence_wrapper",
        "routability_eval_cadence_mounted_root": "cadence_mounted_root",
        "routability_eval_innovus_version": "innovus_version",
    }
    options = {target: config[source] for source, target in mapping.items()
               if config.get(source) not in (None, "")}
    if "xplace_root" not in options:
        for parent in ROOT.parents:
            candidate = parent / "Xplace"
            if candidate.is_dir():
                options["xplace_root"] = str(candidate.resolve())
                break
    options["pl_input"] = str(placed_def.with_suffix(".pl"))
    return options


def flatten_result(method, result):
    row = {
        "method": method,
        "evaluator": result.backend,
        "validation_role": validation_role(result.backend),
        "authoritative_for_comparison": False,
        "status": result.status,
        "runtime_sec": result.runtime_sec,
        "error": result.error,
    }
    for key, value in result.metrics.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            row[key] = value
    return row


def apply_validation_policy(method_results, rows, serialized_results):
    """Mark only a common golden or fallback tier as comparison-authoritative."""
    selected_role = select_common_validation_role(method_results)
    selected_backends = (
        common_validation_backends(method_results, selected_role)
        if selected_role is not None else ()
    )

    for row in rows:
        if row.get("evaluator") == "placement":
            row.setdefault("validation_role", "placement_metric")
            row.setdefault("authoritative_for_comparison", False)
            continue
        row["authoritative_for_comparison"] = bool(
            row.get("status") == "ok"
            and row.get("evaluator") in selected_backends
        )
    for item in serialized_results:
        item["validation_role"] = validation_role(item["backend"])
        item["authoritative_for_comparison"] = bool(
            item.get("status") == "ok"
            and item["backend"] in selected_backends
        )

    status = "validated" if selected_role else "unvalidated"
    return {
        "status": status,
        "selected_role": selected_role or "none",
        "selected_backends": list(selected_backends),
        "fallback_used": selected_role == "fallback_reference",
        "selected_backends_by_method": {
            method: list(selected_backends) for method in method_results
        },
        "policy": {
            "golden": ["openroad", "innovus"],
            "fallback_reference": ["rudy", "gpugr"],
            "diagnostic_only": ["pin_rudy", "xplace", "cugr", "nctugr"],
        },
    }


def run_evaluator_subprocess(request, backend, entry=None):
    """Run one native evaluator in isolation so a crash cannot abort a campaign."""
    entry = Path(entry or ROOT / "tools/routability_evaluate.py").resolve()
    result_path = request.artifact(backend + ".json")
    driver_log = request.artifact(backend + ".driver.log")
    if result_path.exists():
        result_path.unlink()
    command = [
        sys.executable, str(entry), "--backend", backend,
        "--design-name", request.design_name,
        "--output-dir", str(Path(request.output_dir).resolve()),
        "--num-threads", str(request.num_threads),
    ]
    for lef in request.lef_input:
        command.extend(["--lef-input", str(lef)])
    for flag, value in (
        ("--def-input", request.def_input),
        ("--verilog-input", request.verilog_input),
        ("--aux-input", request.aux_input),
    ):
        if value:
            command.extend([flag, str(value)])
    if request.timeout_sec:
        command.extend(["--timeout-sec", str(request.timeout_sec)])
    for key, value in sorted(request.options.items()):
        command.extend(["--option", "%s=%s" % (key, json.dumps(value))])

    start = time.time()
    try:
        completed = subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=(request.timeout_sec + 30) if request.timeout_sec else None,
            check=False,
        )
        driver_log.write_text(completed.stdout or "")
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        driver_log.write_text(output)
        return EvaluationResult(
            backend=backend, design_name=request.design_name, status="timeout",
            runtime_sec=time.time() - start,
            artifacts={"driver_log": str(driver_log)},
            error="evaluator process exceeded %d seconds" % (request.timeout_sec + 30),
        )

    if result_path.exists():
        try:
            result = EvaluationResult(**json.loads(result_path.read_text()))
            result.artifacts.setdefault("driver_log", str(driver_log))
            return result
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            return EvaluationResult(
                backend=backend, design_name=request.design_name, status="failed",
                runtime_sec=time.time() - start,
                artifacts={"driver_log": str(driver_log)},
                error="invalid evaluator result: %s" % error,
            )
    return EvaluationResult(
        backend=backend, design_name=request.design_name, status="failed",
        runtime_sec=time.time() - start,
        artifacts={"driver_log": str(driver_log)},
        error="evaluator process exited with status %d without a result" % completed.returncode,
    )


def parse_placement_metrics(text):
    """Return the final logged placement metrics from a DREAMPlace run."""
    patterns = {
        "placement_hpwl": r"\bwHPWL\s+([0-9.eE+-]+)",
        "density_overflow": r"\bOverflow\s+([0-9.eE+-]+)",
    }
    metrics = {}
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            metrics[key] = float(matches[-1])
    return metrics


def parse_plugin_summaries(text):
    """Aggregate machine-readable plugin counters logged by placement stages."""
    summaries = []
    prefix = "ROUTABILITY_PLUGIN_SUMMARY "
    for line in text.splitlines():
        if prefix not in line:
            continue
        try:
            summaries.append(json.loads(line.split(prefix, 1)[1]))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    aggregate = {
        "pipeline": {
            "gradient_calls": 0,
            "gradient_gate_skips": 0,
            "area_calls": 0,
            "area_gate_skips": 0,
        },
        "plugins": {},
    }
    for summary in summaries:
        for key in aggregate["pipeline"]:
            aggregate["pipeline"][key] += int(summary.get("pipeline", {}).get(key, 0))
        for name, raw in summary.get("plugins", {}).items():
            stats = aggregate["plugins"].setdefault(
                name,
                {
                    "gradient_attempts": 0,
                    "gradient_activations": 0,
                    "area_attempts": 0,
                    "area_activations": 0,
                    "metrics": {},
                    "metric_stats": {},
                },
            )
            for key in (
                "gradient_attempts", "gradient_activations",
                "area_attempts", "area_activations",
            ):
                stats[key] += int(raw.get(key, 0))
            stats["metrics"] = raw.get("metrics", {})
            for metric, values in raw.get("metric_stats", {}).items():
                count = int(values.get("count", 0))
                if count <= 0:
                    continue
                value_min = float(values["min"])
                value_max = float(values["max"])
                combined = stats["metric_stats"].setdefault(
                    metric,
                    {
                        "count": 0,
                        "nonzero_count": 0,
                        "sum": 0.0,
                        "min": value_min,
                        "max": value_max,
                        "last": float(values["last"]),
                    },
                )
                combined["count"] += count
                combined["nonzero_count"] += int(values.get("nonzero_count", 0))
                combined["sum"] += float(values["mean"]) * count
                combined["min"] = min(combined["min"], value_min)
                combined["max"] = max(combined["max"], value_max)
                combined["last"] = float(values["last"])

    total_attempts = 0
    total_activations = 0
    active_plugins = 0
    for stats in aggregate["plugins"].values():
        stats["metric_stats"] = {
            metric: {
                "count": values["count"],
                "nonzero_count": values["nonzero_count"],
                "min": values["min"],
                "max": values["max"],
                "mean": values["sum"] / values["count"],
                "last": values["last"],
            }
            for metric, values in stats["metric_stats"].items()
        }
        stats["attempts"] = stats["gradient_attempts"] + stats["area_attempts"]
        stats["activations"] = (
            stats["gradient_activations"] + stats["area_activations"]
        )
        stats["status"] = (
            "active" if stats["activations"]
            else "attempted_no_change" if stats["attempts"]
            else "not_reached"
        )
        total_attempts += stats["attempts"]
        total_activations += stats["activations"]
        active_plugins += int(stats["activations"] > 0)

    selected = len(aggregate["plugins"])
    if not selected:
        status = "not_selected"
    elif active_plugins == selected:
        status = "active"
    elif active_plugins:
        status = "partially_active"
    else:
        status = "selected_no_activation"
    return {
        "routability_plugin_status": status,
        "routability_plugin_selected": ",".join(sorted(aggregate["plugins"])),
        "routability_plugin_attempts": total_attempts,
        "routability_plugin_activations": total_activations,
        "routability_plugin_summary": aggregate,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--design-name", default="")
    parser.add_argument(
        "--presets", type=Path,
        default=ROOT / "configs/routability_plugins/presets.json",
    )
    parser.add_argument("--methods", default="hpwl,dreamplace_rudy_inflation,route_inflation")
    parser.add_argument("--evaluators", default=DEFAULT_EVALUATORS)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dreamplace-entry", type=Path, default=ROOT / "install/dreamplace/Placer.py")
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--skip-placement", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args(argv)

    base = json.loads(args.base_config.read_text())
    presets = json.loads(args.presets.read_text())
    methods = [name.strip() for name in args.methods.split(",") if name.strip()]
    evaluators = [name.strip() for name in args.evaluators.split(",") if name.strip()]
    design_name = args.design_name or Path(base.get("def_input") or base.get("aux_input")).stem
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    all_results = []
    placement_results = []
    # Pre-register every requested method. If placement stops early, methods
    # that were never reached must still prevent a partial comparison from
    # being reported as validated.
    method_results = {method: [] for method in methods}

    for method in methods:
        if method not in presets:
            raise KeyError("unknown method preset %s" % method)
        method_dir = (args.output_dir / method).resolve()
        placement_dir = method_dir / "placement"
        eval_dir = method_dir / "evaluation"
        method_dir.mkdir(parents=True, exist_ok=True)
        config = dict(base)
        config.update(presets[method])
        config["result_dir"] = str(placement_dir)
        config_path = method_dir / "config.json"
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

        if not args.skip_placement:
            log_path = method_dir / "placement.log"
            start = time.time()
            try:
                completed = subprocess.run(
                    [sys.executable, str(args.dreamplace_entry), str(config_path)],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=args.timeout_sec or None, check=False,
                )
                log_path.write_text(completed.stdout or "")
            except subprocess.TimeoutExpired as error:
                output = error.stdout or ""
                if isinstance(output, bytes):
                    output = output.decode(errors="replace")
                log_path.write_text(output)
                rows.append({"method": method, "evaluator": "placement", "status": "timeout",
                             "runtime_sec": time.time() - start,
                             "error": "placement exceeded %d seconds" % args.timeout_sec})
                if not args.continue_on_error:
                    break
                continue
            if completed.returncode:
                rows.append({"method": method, "evaluator": "placement", "status": "failed",
                             "runtime_sec": time.time() - start,
                             "error": "exit status %d" % completed.returncode})
                if not args.continue_on_error:
                    break
                continue
            plugin_summary = parse_plugin_summaries(completed.stdout or "")
            placement_result = {
                "method": method,
                "evaluator": "placement",
                "validation_role": "placement_metric",
                "authoritative_for_comparison": False,
                "status": "ok",
                "runtime_sec": time.time() - start,
                "error": "",
                **parse_placement_metrics(completed.stdout or ""),
                **{key: value for key, value in plugin_summary.items()
                   if key != "routability_plugin_summary"},
            }
            placement_result["routability_plugin_summary"] = json.dumps(
                plugin_summary["routability_plugin_summary"], sort_keys=True
            )
            rows.append(placement_result)
            placement_results.append({
                **placement_result,
                "routability_plugin_summary": plugin_summary[
                    "routability_plugin_summary"
                ],
            })
        placed_def = find_placed_def(placement_dir, placement_output_name(config))
        eval_dir.mkdir(parents=True, exist_ok=True)
        lef_input = config.get("lef_input", [])
        if isinstance(lef_input, str):
            lef_input = [lef_input]
        request = EvaluationRequest(
            design_name=design_name,
            lef_input=lef_input,
            def_input=str(placed_def),
            verilog_input=config.get("ruplace_eval_verilog_input") or config.get("verilog_input", ""),
            aux_input=config.get("aux_input", ""),
            output_dir=str(eval_dir),
            num_threads=args.num_threads,
            timeout_sec=args.timeout_sec,
            options=evaluator_options(config, placed_def),
        )
        for evaluator_name in evaluators:
            result = run_evaluator_subprocess(request, evaluator_name)
            method_results[method].append(result)
            all_results.append({"method": method, **result.to_dict()})
            rows.append(flatten_result(method, result))

    validation = apply_validation_policy(method_results, rows, all_results)

    fields = sorted({key for row in rows for key in row})
    with (args.output_dir / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "comparison.json").write_text(
        json.dumps(
            {
                "validation": validation,
                "placements": placement_results,
                "results": all_results,
            },
            indent=2, sort_keys=True,
        ) + "\n"
    )
    placement_ok = all(
        row["status"] == "ok" for row in rows if row["evaluator"] == "placement"
    )
    return 0 if rows and placement_ok and validation["status"] == "validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
