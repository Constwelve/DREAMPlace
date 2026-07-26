"""Cadence Innovus early-global-route evaluator adapter."""

from pathlib import Path
import re
import shutil
import tempfile
import time

from .base import EvaluationResult, RoutabilityEvaluator
from .openroad import tcl_quote


def parse_innovus_log(text):
    metrics = {}
    patterns = {
        "wirelength": [r"RLEVAL_WIRELENGTH\s+([0-9.eE+-]+)",
                       r"Total\s+wire\s+length\s*[:=]\s*([0-9.eE+-]+)",
                       r"Total\s+length\s*:\s*([0-9.eE+-]+)\s*(?:um)?"],
        "horizontal_congestion": [r"(?:Horizontal|H)\s+congestion\s*[:=]\s*([0-9.eE+%+-]+)"],
        "vertical_congestion": [r"(?:Vertical|V)\s+congestion\s*[:=]\s*([0-9.eE+%+-]+)"],
        "overflow": [r"total\s+overflow\s*[:=]\s*([0-9.eE+-]+)"],
        "vias": [r"Total\s+length:.*?number\s+of\s+vias:\s*([0-9.eE+-]+)"],
    }
    for key, candidates in patterns.items():
        for pattern in candidates:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metrics[key] = float(match.group(1).rstrip("%"))
                break
    overflow = re.search(
        r"Overflow\s+after\s+Early\s+Global\s+Route\s+"
        r"([0-9.eE+-]+)%\s+H\s*\+\s*([0-9.eE+-]+)%\s+V",
        text,
        re.IGNORECASE,
    )
    if overflow:
        metrics["horizontal_congestion"] = float(overflow.group(1))
        metrics["vertical_congestion"] = float(overflow.group(2))
    return metrics


def innovus_fatal_error(text):
    """Return a fatal Innovus line when its launcher masks the exit status."""
    match = re.search(r"^\*\*(?:ERROR|FATAL):.*$", text, re.MULTILINE)
    return match.group(0).strip() if match else ""


class InnovusEvaluator(RoutabilityEvaluator):
    name = "innovus"

    def evaluate(self, request):
        start = time.time()
        if not request.verilog_input:
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="unsupported",
                error="Innovus evaluation requires a Verilog netlist in addition to LEF/DEF",
            )
        mounted_root = Path(request.options.get(
            "cadence_mounted_root", "/mnt/nvme0n1/yifan/projs/TaiWei-Pin-3D"
        )).resolve()
        if not mounted_root.is_dir():
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="unsupported",
                error="Cadence staging root does not exist: %s" % mounted_root,
            )
        wrapper = request.options.get(
            "cadence_wrapper", "/home/yifan/.codex/skills/cadence-local/cadence"
        )
        script_artifact = request.artifact("innovus_eval.tcl")
        metric_artifact = request.artifact("innovus_metrics.txt")
        with tempfile.TemporaryDirectory(prefix="routability_eval_", dir=mounted_root) as tmp:
            work = Path(tmp)
            staged_lefs = []
            for index, lef in enumerate(request.lef_input):
                staged = work / ("lef_%d_%s" % (index, Path(lef).name))
                shutil.copy2(lef, staged)
                staged_lefs.append(staged)
            staged_def = work / ("input_" + Path(request.def_input).name)
            staged_verilog = work / ("input_" + Path(request.verilog_input).name)
            shutil.copy2(request.def_input, staged_def)
            shutil.copy2(request.verilog_input, staged_verilog)
            script = work / "innovus_eval.tcl"
            metric_file = work / "innovus_metrics.txt"
            lef_list = " ".join(tcl_quote(path) for path in staged_lefs)
            script.write_text("\n".join([
                "set init_lef_file [list %s]" % lef_list,
                "set init_verilog %s" % tcl_quote(staged_verilog),
                "set init_design_netlisttype Verilog",
                "set init_design_settop 1",
                "set init_top_cell %s" % tcl_quote(request.design_name),
                "set init_mmmc_file {}",
                "init_design",
                "defIn %s" % tcl_quote(staged_def),
                "setMultiCpuUsage -localCpu %d" % request.num_threads,
                "setNanoRouteMode -grouteExpWithTimingDriven false",
                "earlyGlobalRoute",
                "set rleval_wl 0",
                "catch {set rleval_wl [expr [join [dbget top.nets.wires.length] +]]}",
                "puts \"RLEVAL_WIRELENGTH $rleval_wl\"",
                "catch {reportWire -summary}",
                "catch {reportCongestion -overflow}",
                "set rleval_fh [open %s w]" % tcl_quote(metric_file),
                "puts $rleval_fh \"wirelength=$rleval_wl\"",
                "close $rleval_fh",
                "exit",
            ]) + "\n")
            shutil.copy2(script, script_artifact)
            command = [
                wrapper, "-v", str(request.options.get("innovus_version", 22)),
                "innovus", "-no_gui", "-batch", "-files", str(script),
            ]
            output, failure = self.run(request, command, cwd=work)
            if metric_file.exists():
                shutil.copy2(metric_file, metric_artifact)
            if failure:
                failure.artifacts["script"] = str(script_artifact)
                return failure
        metrics = parse_innovus_log(output)
        fatal_error = innovus_fatal_error(output)
        if fatal_error or float(metrics.get("wirelength", 0.0)) <= 0.0:
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                artifacts={"script": str(script_artifact),
                           "metrics": str(metric_artifact),
                           "log": str(request.artifact("innovus.log"))},
                error=fatal_error or "Innovus completed without positive EGR wirelength",
            )
        return EvaluationResult(
            backend=self.name,
            design_name=request.design_name,
            runtime_sec=time.time() - start,
            metrics=metrics,
            artifacts={"script": str(script_artifact), "metrics": str(metric_artifact),
                       "log": str(request.artifact("innovus.log"))},
        )
