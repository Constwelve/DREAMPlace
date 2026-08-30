#!/usr/bin/env python3
"""Run plugin ablations and evaluate every placed DEF with independent backends."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
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
from tools.routability_accept_legal_refinement import accept_legal_refinement
from tools.routability_legal_refine_def import placement_geometry_provenance
from tools.routability_post_placement import (
    materialize_post_placement,
    placement_record as post_placement_record,
    post_placement_spec,
    reusable_post_placement,
    validate_post_placement_order,
)


DEFAULT_EVALUATORS = ",".join(DEFAULT_VALIDATION_EVALUATORS)
PLACEMENT_INPUT_KEYS = (
    "lef_input",
    "def_input",
    "verilog_input",
    "ruplace_eval_verilog_input",
    "aux_input",
)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path, payload):
    """Publish provenance only after its complete JSON payload is durable."""
    path = Path(path)
    temporary = path.with_name(
        ".%s.tmp-%d" % (path.name, os.getpid())
    )
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(str(temporary), str(path))


def placement_input_provenance(config):
    """Hash resolved design inputs so resume cannot cross in-place changes."""
    result = {}
    for key in PLACEMENT_INPUT_KEYS:
        values = config.get(key, [])
        if not isinstance(values, list):
            values = [values]
        records = []
        for value in values:
            if not value:
                continue
            path = Path(value).expanduser().resolve()
            record = {"path": str(path), "exists": path.is_file()}
            if path.is_file():
                record["sha256"] = file_sha256(path)
                record["size"] = path.stat().st_size
            records.append(record)
        if records:
            result[key] = records
    return {"files": result}


def evaluator_python_root(dreamplace_entry):
    """Return the package root paired with a dreamplace/Placer.py entry."""
    entry = Path(dreamplace_entry).resolve()
    if entry.name == "Placer.py" and entry.parent.name == "dreamplace":
        root = entry.parent.parent
        if (root / "dreamplace").is_dir():
            return root
    return PYTHON_ROOT.resolve()


def evaluator_package_provenance(python_root):
    """Hash evaluator sources so resume never crosses implementation changes."""
    root = Path(python_root).resolve()
    patterns = (
        "dreamplace/ops/routability_eval/*.py",
        "dreamplace/ops/gpugr/xplace_backend.py",
        "dreamplace/ops/gpugr/run_gpugr.py",
    )
    files = sorted({path for pattern in patterns for path in root.glob(pattern)})
    return {
        "python_root": str(root),
        "files": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files if path.is_file()
        },
    }


def placement_package_files(root):
    """Return hashes for placement-relevant files below a Python root."""
    root = Path(root).resolve()
    package = root / "dreamplace"
    excluded = (
        "dreamplace/ops/routability_eval/",
        "dreamplace/ops/gpugr/",
    )
    files = []
    if package.is_dir():
        for path in package.rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".so", ".json"):
                continue
            relative = str(path.relative_to(root))
            if any(relative.startswith(prefix) for prefix in excluded):
                continue
            files.append((relative, path))
    return {
        relative: file_sha256(path)
        for relative, path in sorted(files)
    }


def placement_package_provenance(dreamplace_entry):
    """Hash the installed package and any retained placement source snapshot."""
    root = evaluator_python_root(dreamplace_entry)
    installed_files = placement_package_files(root)
    entry = Path(dreamplace_entry).expanduser().resolve()
    entry_record = {"path": str(entry), "exists": entry.is_file()}
    if entry.is_file():
        entry_record.update({
            "sha256": file_sha256(entry),
            "size": entry.stat().st_size,
        })
    source_root = root.parent / "source" if root.name == "install" else None
    source_files = (
        placement_package_files(source_root)
        if source_root is not None and (source_root / "dreamplace").is_dir()
        else {}
    )
    missing = sorted(
        relative for relative in source_files if relative not in installed_files
    )
    mismatches = sorted(
        relative for relative, digest in source_files.items()
        if relative in installed_files and installed_files[relative] != digest
    )
    return {
        "python_root": str(root),
        "dreamplace_entry": entry_record,
        "files": installed_files,
        "source_python_root": str(source_root) if source_files else None,
        "source_files": source_files,
        "source_install_missing": missing,
        "source_install_mismatches": mismatches,
    }


def validate_placement_package_provenance(provenance):
    """Refuse a retained source snapshot that differs from executed code."""
    missing = provenance.get("source_install_missing", [])
    mismatches = provenance.get("source_install_mismatches", [])
    if not missing and not mismatches:
        return
    details = []
    if missing:
        details.append("missing installed files: %s" % ", ".join(missing))
    if mismatches:
        details.append("source/install mismatches: %s" % ", ".join(mismatches))
    raise RuntimeError("placement package provenance failed; " + "; ".join(details))


def placement_runtime_provenance():
    """Record the host and numerical ABI that can change placement results."""
    result = {
        "host": {
            "hostname": platform.node(),
            "machine": platform.machine(),
            "system": platform.system(),
            "release": platform.release(),
        },
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "environment": {
            key: os.environ.get(key)
            for key in (
                "CUDA_VISIBLE_DEVICES",
                "CUBLAS_WORKSPACE_CONFIG",
                "LD_LIBRARY_PATH",
                "MKL_NUM_THREADS",
                "OMP_NUM_THREADS",
                "PYTHONHASHSEED",
                "PYTHONPATH",
            )
        },
    }
    try:
        import numpy
        result["numpy_version"] = numpy.__version__
    except (ImportError, AttributeError, OSError):
        result["numpy_version"] = None

    try:
        import torch
    except (ImportError, OSError):
        result["torch"] = {"available": False}
    else:
        torch_record = {
            "available": True,
            "version": torch.__version__,
            "compiled_cuda": getattr(torch.version, "cuda", None),
            "cxx11_abi": getattr(torch._C, "_GLIBCXX_USE_CXX11_ABI", None),
        }
        try:
            torch_record["cudnn_version"] = torch.backends.cudnn.version()
        except (AttributeError, RuntimeError):
            torch_record["cudnn_version"] = None
        try:
            cuda_available = bool(torch.cuda.is_available())
            torch_record["cuda_available"] = cuda_available
            torch_record["visible_device_count"] = (
                torch.cuda.device_count() if cuda_available else 0
            )
            devices = []
            for index in range(torch_record["visible_device_count"]):
                properties = torch.cuda.get_device_properties(index)
                devices.append({
                    "index": index,
                    "name": properties.name,
                    "compute_capability": [properties.major, properties.minor],
                    "total_memory": properties.total_memory,
                    "multi_processor_count": properties.multi_processor_count,
                })
            torch_record["visible_devices"] = devices
        except Exception as error:
            torch_record.update({
                "cuda_available": False,
                "visible_device_count": 0,
                "visible_devices": [],
                "cuda_probe_error_type": type(error).__name__,
            })
        result["torch"] = torch_record

    driver = Path("/proc/driver/nvidia/version")
    try:
        result["nvidia_driver"] = (
            driver.read_text(errors="replace").splitlines()[0]
            if driver.is_file() else None
        )
    except OSError:
        result["nvidia_driver"] = None
    return result


def reusable_evaluation_result(result, backend, options):
    if result.status != "ok":
        return False
    required = options.get("required_directional_metric_schema_version")
    if required and backend in ("gpugr", "xplace"):
        return result.metrics.get("directional_metric_schema_version") == int(required)
    return True


def placement_output_name(config):
    """Match Params.design_name(), which controls DREAMPlace's result path."""
    for key, suffix in (("aux_input", ".aux"), ("verilog_input", ".v"),
                        ("def_input", ".def")):
        value = config.get(key)
        if value:
            name = Path(value).name
            return name[:-len(suffix)] if name.lower().endswith(suffix) else Path(name).stem
    raise ValueError("base config requires aux_input, verilog_input, or def_input")


def evaluator_design_name(config):
    """Return the logical top cell, which may differ from the DEF filename."""
    return config.get("ruplace_eval_design_name") or Path(
        config.get("def_input") or config.get("aux_input")
    ).stem


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
        "routability_eval_required_directional_metric_schema_version": (
            "required_directional_metric_schema_version"
        ),
        "routability_eval_cugr_root": "cugr_root",
        "routability_eval_cugr_threads": "cugr_threads",
        "routability_eval_nctugr_root": "nctugr_root",
        "routability_eval_openroad_binary": "openroad_binary",
        "routability_eval_openroad_route_mode": "openroad_route_mode",
        "routability_eval_openroad_droute_end_iteration": "openroad_droute_end_iteration",
        "routability_eval_cadence_wrapper": "cadence_wrapper",
        "routability_eval_cadence_mounted_root": "cadence_mounted_root",
        "routability_eval_innovus_version": "innovus_version",
        "routability_eval_innovus_route_mode": "innovus_route_mode",
        "routability_eval_innovus_droute_end_iteration": "innovus_droute_end_iteration",
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


def mandatory_requested_evaluator_gate(method_results, methods, evaluators):
    """Require both proxy backends when a paired proxy campaign requests them."""
    if set(evaluators) != {"rudy", "gpugr"} or len(evaluators) != 2:
        return None
    failures = []
    for method in methods:
        results = method_results.get(method, [])
        for backend in evaluators:
            matches = [result for result in results if result.backend == backend]
            if len(matches) != 1 or matches[0].status != "ok":
                failures.append("%s:%s" % (method, backend))
    return {
        "status": "passed" if not failures else "failed",
        "required_backends": list(evaluators),
        "failures": failures,
    }


def run_evaluator_subprocess(request, backend, entry=None, python_root=None):
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
    env = dict(os.environ)
    if python_root is not None:
        python_root = Path(python_root).resolve()
        if not (python_root / "dreamplace").is_dir():
            raise ValueError(
                "evaluator Python root has no dreamplace package: %s" % python_root
            )
        env["DREAMPLACE_EVALUATOR_PYTHON_ROOT"] = str(python_root)
    try:
        completed = subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=(request.timeout_sec + 30) if request.timeout_sec else None,
            check=False, env=env,
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
            "objective_calls": 0,
            "objective_gate_skips": 0,
            "gradient_calls": 0,
            "gradient_gate_skips": 0,
            "area_calls": 0,
            "area_gate_skips": 0,
        },
        "plugins": {},
    }
    area_budget_observations = []
    for summary in summaries:
        pipeline = summary.get("pipeline", {})
        for key in aggregate["pipeline"]:
            aggregate["pipeline"][key] += int(pipeline.get(key, 0))
        if "area_budget_enabled" in pipeline:
            area_budget_observations.append({
                "area_budget_enabled": int(pipeline["area_budget_enabled"]),
                "area_adjustments": int(pipeline.get("area_adjustments", -1)),
                "max_area_adjustments": int(pipeline.get(
                    "max_area_adjustments", -1
                )),
            })
        for name, raw in summary.get("plugins", {}).items():
            stats = aggregate["plugins"].setdefault(
                name,
                {
                    "objective_attempts": 0,
                    "objective_activations": 0,
                    "gradient_attempts": 0,
                    "gradient_activations": 0,
                    "area_attempts": 0,
                    "area_activations": 0,
                    "metrics": {},
                    "metric_stats": {},
                },
            )
            for key in (
                "objective_attempts", "objective_activations",
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

    if area_budget_observations:
        maxima = {
            row["max_area_adjustments"] for row in area_budget_observations
        }
        aggregate["pipeline"].update({
            "area_budget_enabled": int(all(
                row["area_budget_enabled"] == 1
                for row in area_budget_observations
            )),
            "area_adjustments": max(
                row["area_adjustments"] for row in area_budget_observations
            ),
            "max_area_adjustments": (
                next(iter(maxima)) if len(maxima) == 1 else -1
            ),
            "area_budget_observations": area_budget_observations,
        })

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
        stats["attempts"] = (
            stats["objective_attempts"]
            + stats["gradient_attempts"]
            + stats["area_attempts"]
        )
        stats["activations"] = (
            stats["objective_activations"]
            + stats["gradient_activations"]
            + stats["area_activations"]
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
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "reuse only config-identical successful placements and evaluator "
            "results from the existing comparison"
        ),
    )
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args(argv)
    if args.resume and args.skip_placement:
        parser.error("--resume and --skip-placement are mutually exclusive")

    base = json.loads(args.base_config.read_text())
    input_provenance = placement_input_provenance(base)
    placement_implementation = placement_package_provenance(args.dreamplace_entry)
    validate_placement_package_provenance(placement_implementation)
    placement_runtime = placement_runtime_provenance()
    presets = json.loads(args.presets.read_text())
    methods = [name.strip() for name in args.methods.split(",") if name.strip()]
    evaluators = [name.strip() for name in args.evaluators.split(",") if name.strip()]
    validate_post_placement_order(methods, presets)
    design_name = args.design_name or evaluator_design_name(base)
    evaluation_python_root = evaluator_python_root(args.dreamplace_entry)
    evaluation_provenance = evaluator_package_provenance(evaluation_python_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    previous_path = args.output_dir / "comparison.json"
    previous = (
        json.loads(previous_path.read_text())
        if args.resume and previous_path.is_file() else {}
    )
    previous_placements = {
        row.get("method"): row
        for row in previous.get("placements", [])
        if row.get("method")
    }
    previous_results = {
        (row.get("method"), row.get("backend")): row
        for row in previous.get("results", [])
        if row.get("method") and row.get("backend")
    }
    previous_evaluator_matches = (
        previous.get("evaluator_package_provenance") == evaluation_provenance
    )
    previous_input_matches = (
        previous.get("placement_input_provenance") == input_provenance
    )
    previous_implementation_matches = (
        previous.get("placement_implementation_provenance")
        == placement_implementation
    )
    previous_runtime_matches = (
        previous.get("placement_runtime_provenance") == placement_runtime
    )
    resume_stats = {
        "enabled": bool(args.resume),
        "reused_placements": [],
        "reused_evaluations": [],
        "rerun_placements": [],
        "rerun_evaluations": [],
        "input_provenance_matches": previous_input_matches,
        "placement_implementation_provenance_matches": (
            previous_implementation_matches
        ),
        "placement_runtime_provenance_matches": previous_runtime_matches,
    }
    rows = []
    all_results = []
    placement_results = []
    # Pre-register every requested method. If placement stops early, methods
    # that were never reached must still prevent a partial comparison from
    # being reported as validated.
    method_results = {method: [] for method in methods}
    placed_defs = {}
    method_configs = {}
    post_placement_reports = {}

    for method in methods:
        if method not in presets:
            raise KeyError("unknown method preset %s" % method)
        method_dir = (args.output_dir / method).resolve()
        placement_dir = method_dir / "placement"
        eval_dir = method_dir / "evaluation"
        method_dir.mkdir(parents=True, exist_ok=True)
        config = dict(base)
        config.update(presets[method])
        method_configs[method] = config
        config["result_dir"] = str(placement_dir)
        config_path = method_dir / "config.json"
        previous_config = None
        if config_path.is_file():
            try:
                previous_config = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                previous_config = None
        config_matches = previous_config == config
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

        log_path = method_dir / "placement.log"
        placed_def = None
        placement_reused = False
        post_spec = post_placement_spec(config)
        previous_placement = previous_placements.get(method)
        if (
            args.resume and config_matches and previous_input_matches
            and previous_implementation_matches and previous_runtime_matches
            and previous_placement
            and previous_placement.get("status") == "ok" and log_path.is_file()
        ):
            try:
                placed_def = find_placed_def(
                    placement_dir, placement_output_name(config)
                )
            except (FileNotFoundError, RuntimeError):
                placed_def = None
            if (
                placed_def is not None
                and post_spec is not None
                and not reusable_post_placement(
                    method_dir / "post_placement_operation.json",
                    placed_def,
                    method,
                    post_spec,
                    placed_defs,
                    config.get("lef_input", []),
                )
            ):
                placed_def = None
            if (
                placed_def is not None
                and previous_placement.get("placed_def_sha256")
                != file_sha256(placed_def)
            ):
                placed_def = None
            if placed_def is not None:
                placement_record = dict(previous_placement)
                placement_row = dict(placement_record)
                summary = placement_row.get("routability_plugin_summary")
                if isinstance(summary, dict):
                    placement_row["routability_plugin_summary"] = json.dumps(
                        summary, sort_keys=True
                    )
                rows.append(placement_row)
                placement_results.append(placement_record)
                placement_reused = True
                resume_stats["reused_placements"].append(method)

        if not args.skip_placement and not placement_reused and post_spec is not None:
            resume_stats["rerun_placements"].append(method)
            start = time.time()
            report_path = method_dir / "post_placement_operation.json"
            try:
                placed_def, report = materialize_post_placement(
                    method,
                    config,
                    placed_defs,
                    placement_dir,
                    placement_output_name(config),
                    config.get("lef_input", []),
                    report_path,
                )
            except (OSError, RuntimeError, ValueError) as error:
                log_path.write_text(str(error) + "\n")
                failed = {
                    "method": method,
                    "evaluator": "placement",
                    "validation_role": "placement_metric",
                    "authoritative_for_comparison": False,
                    "status": "failed",
                    "runtime_sec": time.time() - start,
                    "error": str(error),
                }
                rows.append(failed)
                placement_results.append(failed)
                if not args.continue_on_error:
                    break
                continue
            log_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            placement_result = post_placement_record(
                method, report, time.time() - start
            )
            placement_result["post_placement_report"] = str(report_path.resolve())
            rows.append({
                **placement_result,
                "routability_plugin_summary": json.dumps(
                    placement_result["routability_plugin_summary"], sort_keys=True
                ),
            })
            placement_results.append(placement_result)
            post_placement_reports[method] = report_path.resolve()
        elif not args.skip_placement and not placement_reused:
            resume_stats["rerun_placements"].append(method)
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
        if placed_def is None:
            placed_def = find_placed_def(placement_dir, placement_output_name(config))
        placed_def = placed_def.resolve()
        geometry = placement_geometry_provenance(
            placed_def, config.get("lef_input", [])
        )
        placed_def_hash = file_sha256(placed_def)
        for placement_record in reversed(placement_results):
            if placement_record.get("method") == method:
                placement_record.update({
                    "placed_def": str(placed_def),
                    "placed_def_sha256": placed_def_hash,
                    "placement_geometry_provenance": geometry,
                })
                break
        for placement_row in reversed(rows):
            if (
                placement_row.get("method") == method
                and placement_row.get("evaluator") == "placement"
            ):
                placement_row.update({
                    "placed_def": str(placed_def),
                    "placed_def_sha256": placed_def_hash,
                    "placement_geometry_provenance": json.dumps(
                        geometry, sort_keys=True
                    ),
                })
                break
        placed_defs[method] = placed_def
        atomic_write_json(method_dir / "placement_provenance.json", {
            "schema_version": 1,
            "method": method,
            "config": str(config_path.resolve()),
            "config_sha256": file_sha256(config_path),
            "placed_def": str(placed_def),
            "placed_def_sha256": placed_def_hash,
            "placement_geometry_provenance": geometry,
            "placement_input_provenance": input_provenance,
            "placement_implementation_provenance": placement_implementation,
            "placement_runtime_provenance": placement_runtime,
        })
        if post_spec is not None and method not in post_placement_reports:
            report_path = method_dir / "post_placement_operation.json"
            if not report_path.is_file():
                raise FileNotFoundError(
                    "post-placement report is missing for %s" % method
                )
            post_placement_reports[method] = report_path.resolve()
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
            result = None
            previous_result = previous_results.get((method, evaluator_name))
            result_path = eval_dir / (evaluator_name + ".json")
            if (
                args.resume and placement_reused and previous_result
                and previous_result.get("status") == "ok" and result_path.is_file()
            ):
                try:
                    loaded = EvaluationResult(**json.loads(result_path.read_text()))
                except (TypeError, ValueError, json.JSONDecodeError):
                    loaded = None
                if (
                    previous_evaluator_matches
                    and loaded is not None
                    and reusable_evaluation_result(
                        loaded, evaluator_name, request.options
                    )
                ):
                    result = loaded
                    resume_stats["reused_evaluations"].append(
                        "%s:%s" % (method, evaluator_name)
                    )
            if result is None:
                result = run_evaluator_subprocess(
                    request, evaluator_name,
                    python_root=evaluation_python_root,
                )
                resume_stats["rerun_evaluations"].append(
                    "%s:%s" % (method, evaluator_name)
                )
            method_results[method].append(result)
            all_results.append({"method": method, **result.to_dict()})
            rows.append(flatten_result(method, result))
        (eval_dir / "summary.json").write_text(
            json.dumps(
                {
                    "results": [
                        result.to_dict() for result in method_results[method]
                    ],
                },
                indent=2,
                sort_keys=True,
            ) + "\n"
        )

    validation = apply_validation_policy(method_results, rows, all_results)
    proxy_gate = mandatory_requested_evaluator_gate(
        method_results, methods, evaluators
    )
    if proxy_gate is not None:
        validation["mandatory_proxy_gate"] = proxy_gate
        if proxy_gate["status"] != "passed":
            validation["status"] = "unvalidated"

    post_acceptance = {}
    acceptance_root = args.output_dir / "post_placement_acceptance"
    for method in methods:
        spec = post_placement_spec(method_configs[method])
        if spec is None or spec["operation"] != "legal_whitespace_slide":
            continue
        group = spec["acceptance_group"]
        entry = post_acceptance.setdefault(group, {
            "baseline_method": spec["baseline_method"],
            "metric_profile": spec.get(
                "metric_profile", "absolute_directional_v2"
            ),
            "candidates": [],
            "unavailable_methods": [],
        })
        if (
            entry["baseline_method"] != spec["baseline_method"]
            or entry["metric_profile"] != spec.get(
                "metric_profile", "absolute_directional_v2"
            )
        ):
            raise ValueError("inconsistent post-placement acceptance group %s" % group)
        if method not in placed_defs or method not in post_placement_reports:
            entry["unavailable_methods"].append(method)
            continue
        entry["candidates"].append((
            method,
            str(placed_defs[method]),
            str((args.output_dir / method / "evaluation").resolve()),
            str(post_placement_reports[method]),
        ))
    for group, entry in post_acceptance.items():
        if not {"rudy", "gpugr"}.issubset(evaluators):
            raise ValueError(
                "post-placement acceptance requires rudy and gpugr evaluators"
            )
        baseline_method = entry["baseline_method"]
        required_methods = [baseline_method] + [
            candidate[0] for candidate in entry["candidates"]
        ]
        proxy_complete = all(
            len([
                result for result in method_results.get(method, [])
                if result.backend in ("rudy", "gpugr") and result.status == "ok"
            ]) == 2
            for method in required_methods
        )
        if (
            entry["unavailable_methods"]
            or baseline_method not in placed_defs
            or not entry["candidates"]
            or not proxy_complete
        ):
            entry.clear()
            entry.update({
                "decision": "unavailable",
                "selected_candidate": None,
                "materialized_def": None,
                "reason": "source placement or mandatory proxy evidence is incomplete",
            })
            continue
        acceptance_root.mkdir(parents=True, exist_ok=True)
        result = accept_legal_refinement(
            placed_defs[baseline_method],
            args.output_dir / baseline_method / "evaluation",
            entry["candidates"],
            output=acceptance_root / (group + ".def"),
            metric_profile=entry["metric_profile"],
        )
        report_path = acceptance_root / (group + ".json")
        report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        entry.clear()
        entry.update({
            "report": str(report_path.resolve()),
            "materialized_def": result["materialized_def"],
            "decision": result["decision"],
            "selected_candidate": result["selected_candidate"],
        })

    fields = sorted({key for row in rows for key in row})
    with (args.output_dir / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "comparison.json").write_text(
        json.dumps(
            {
                "validation": validation,
                "evaluator_package_provenance": evaluation_provenance,
                "placement_input_provenance": input_provenance,
                "placement_implementation_provenance": placement_implementation,
                "placement_runtime_provenance": placement_runtime,
                "resume": resume_stats,
                "post_placement_acceptance": post_acceptance,
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
