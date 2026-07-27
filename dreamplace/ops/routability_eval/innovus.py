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
        "wirelength": [r"RLEVAL_ROUTED_WIRELENGTH\s+([0-9.eE+-]+)",
                       r"RLEVAL_WIRELENGTH\s+([0-9.eE+-]+)",
                       r"Total\s+wire\s+length\s*[:=]\s*([0-9.eE+-]+)",
                       r"Total\s+length\s*:\s*([0-9.eE+-]+)\s*(?:um)?"],
        "horizontal_congestion": [r"(?:Horizontal|H)\s+congestion\s*[:=]\s*([0-9.eE+%+-]+)"],
        "vertical_congestion": [r"(?:Vertical|V)\s+congestion\s*[:=]\s*([0-9.eE+%+-]+)"],
        "overflow": [r"total\s+overflow\s*[:=]\s*([0-9.eE+-]+)"],
        "vias": [
            r"Total\s+number\s+of\s+vias\s*=\s*([0-9.eE+-]+)",
            r"Total\s+length:.*?number\s+of\s+vias:\s*([0-9.eE+-]+)",
        ],
        "drc_violations": [r"RLEVAL_DRC_COUNT\s+([0-9.eE+-]+)"],
    }
    for key, candidates in patterns.items():
        for pattern in candidates:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metrics[key] = float(match.group(1).rstrip("%"))
                break
    wire_summaries = re.findall(
        r"Total\s+length:\s*[0-9.eE+-]+\s*(?:um)?,\s*"
        r"number\s+of\s+vias:\s*([0-9.eE+-]+)",
        text,
        re.IGNORECASE,
    )
    if wire_summaries:
        metrics["vias"] = float(wire_summaries[-1])
    detailed_via_summaries = re.findall(
        r"Total\s+number\s+of\s+vias\s*=\s*([0-9.eE+-]+)",
        text,
        re.IGNORECASE,
    )
    if detailed_via_summaries:
        metrics["vias"] = float(detailed_via_summaries[-1])
    egr_overflow = re.search(
        r"Overflow\s+after\s+(?:Early\s+Global\s+Route\s+|GR:\s*)"
        r"([0-9.eE+-]+)%\s+H\s*\+\s*([0-9.eE+-]+)%\s+V",
        text,
        re.IGNORECASE,
    )
    if egr_overflow:
        metrics["egr_horizontal_congestion"] = float(egr_overflow.group(1))
        metrics["egr_vertical_congestion"] = float(egr_overflow.group(2))
        metrics.setdefault("horizontal_congestion", float(egr_overflow.group(1)))
        metrics.setdefault("vertical_congestion", float(egr_overflow.group(2)))
    congestion_reports = re.findall(
        r"^Overflow:\s*([0-9.eE+-]+)\s*=\s*"
        r"([0-9.eE+-]+)\s*\(([0-9.eE+-]+)%\s*H\)\s*\+\s*"
        r"([0-9.eE+-]+)\s*\(([0-9.eE+-]+)%\s*V\)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if congestion_reports:
        total, horizontal, horizontal_pct, vertical, vertical_pct = (
            float(value) for value in congestion_reports[-1]
        )
        metrics.update({
            "total_overflow": total,
            "horizontal_overflow": horizontal,
            "vertical_overflow": vertical,
            "horizontal_congestion": horizontal_pct,
            "vertical_congestion": vertical_pct,
        })
    return metrics


def innovus_fatal_error(text):
    """Return a fatal Innovus line when its launcher masks the exit status."""
    match = re.search(r"^\*\*(?:ERROR|FATAL):.*$", text, re.MULTILINE)
    return match.group(0).strip() if match else ""


class InnovusEvaluator(RoutabilityEvaluator):
    name = "innovus"

    def evaluate(self, request):
        start = time.time()
        route_mode = str(request.options.get("innovus_route_mode", "global")).lower()
        if route_mode not in ("global", "detailed"):
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="unsupported",
                error="innovus_route_mode must be global or detailed",
            )
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
        drc_artifact = request.artifact("innovus_drc.rpt")
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
            drc_file = work / "innovus_drc.rpt"
            lef_list = " ".join(tcl_quote(path) for path in staged_lefs)
            lines = [
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
            ]
            if route_mode == "detailed":
                lines.extend([
                    "setNanoRouteMode -routeWithTimingDriven false",
                    "setNanoRouteMode -routeWithSiDriven false",
                    "setNanoRouteMode -drouteVerboseViolationSummary 1",
                    "setNanoRouteMode -drouteEndIteration %d" % int(
                        request.options.get("innovus_droute_end_iteration", 20)
                    ),
                    "globalDetailRoute",
                ])
            else:
                lines.append("earlyGlobalRoute")
            lines.extend([
                "catch {reportWire -summary}",
                "catch {reportCongestion -overflow}",
            ])
            lines.extend([
                "set rleval_wl 0",
                "catch {set rleval_wl [expr [join [dbget top.nets.wires.length] +]]}",
                "puts \"RLEVAL_ROUTED_WIRELENGTH $rleval_wl\"",
                "catch {reportWire -summary}",
            ])
            if route_mode == "detailed":
                lines.extend([
                    "verify_drc -exclude_pg_net -limit 0 -report %s" % tcl_quote(drc_file),
                    "set rleval_drc_count 0",
                    "set rleval_drc_fh [open %s r]" % tcl_quote(drc_file),
                    "while {[gets $rleval_drc_fh rleval_line] >= 0} {",
                    "  if {[regexp {Total Violations : ([0-9]+) Viols.} $rleval_line _ rleval_count]} {",
                    "    set rleval_drc_count $rleval_count",
                    "  }",
                    "}",
                    "close $rleval_drc_fh",
                    "puts \"RLEVAL_DRC_COUNT $rleval_drc_count\"",
                ])
            lines.extend([
                "set rleval_fh [open %s w]" % tcl_quote(metric_file),
                "puts $rleval_fh \"wirelength=$rleval_wl\"",
                "puts $rleval_fh \"route_mode=%s\"" % route_mode,
                "close $rleval_fh",
                "exit",
            ])
            script.write_text("\n".join(lines) + "\n")
            shutil.copy2(script, script_artifact)
            command = [
                wrapper, "-v", str(request.options.get("innovus_version", 22)),
                "innovus", "-no_gui", "-batch", "-files", str(script),
            ]
            output, failure = self.run(request, command, cwd=work)
            if metric_file.exists():
                shutil.copy2(metric_file, metric_artifact)
            if drc_file.exists():
                shutil.copy2(drc_file, drc_artifact)
            if failure:
                failure.artifacts["script"] = str(script_artifact)
                return failure
        metrics = parse_innovus_log(output)
        fatal_error = innovus_fatal_error(output)
        missing_drc = route_mode == "detailed" and "drc_violations" not in metrics
        missing_directional = route_mode == "detailed" and not (
            all(key in metrics for key in (
                "horizontal_overflow", "vertical_overflow"
            ))
            or all(key in metrics for key in (
                "horizontal_congestion", "vertical_congestion"
            ))
        )
        if (
            fatal_error
            or float(metrics.get("wirelength", 0.0)) <= 0.0
            or missing_drc
            or missing_directional
        ):
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                artifacts={"script": str(script_artifact),
                           "metrics": str(metric_artifact),
                           "log": str(request.artifact("innovus.log"))},
                error=fatal_error or (
                    "Innovus detailed routing completed without a DRC count"
                    if missing_drc else
                    "Innovus detailed routing completed without directional congestion"
                    if missing_directional else
                    "Innovus completed without positive routed wirelength"
                ),
            )
        return EvaluationResult(
            backend=self.name,
            design_name=request.design_name,
            runtime_sec=time.time() - start,
            metrics=metrics,
            artifacts={
                "script": str(script_artifact), "metrics": str(metric_artifact),
                "log": str(request.artifact("innovus.log")),
                **({"drc": str(drc_artifact)} if drc_artifact.exists() else {}),
            },
        )
