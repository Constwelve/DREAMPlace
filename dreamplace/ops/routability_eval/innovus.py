"""Cadence Innovus early-global-route evaluator adapter."""

from pathlib import Path
import re
import shutil
import tempfile
import time

from .base import EvaluationResult, RoutabilityEvaluator
from .openroad import tcl_quote


INNOVUS_SHORT_RE = re.compile(r"^\s*SHORT\s*:", re.IGNORECASE)
INNOVUS_TOTAL_DRC_RE = re.compile(
    r"Total\s+Violations\s*:\s*([0-9]+)\s+Viols\.", re.IGNORECASE
)
INNOVUS_TOTAL_SHORT_RE = re.compile(
    r"Total\s+Short\s+Violations\s*:\s*([0-9]+)\s+Viols\.", re.IGNORECASE
)
INNOVUS_DRC_REPORT_TAIL_BYTES = 1024 * 1024


class RetainableTemporaryDirectory(tempfile.TemporaryDirectory):
    """Clean successful evaluator staging while retaining failed route evidence."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._retained = False

    def retain(self):
        self._retained = True
        self._finalizer.detach()

    def cleanup(self):
        if not self._retained:
            super().cleanup()


def parse_innovus_route_violation_summary(text):
    """Extract the final NanoRoute DRC/short totals from its typed matrix."""
    final_types = None
    header = None
    awaiting_header = False
    for line in text.splitlines():
        if "By Layer and Type" in line:
            awaiting_header = True
            header = None
            continue
        fields = line.lstrip("#").split()
        if awaiting_header and fields:
            header = fields
            awaiting_header = False
            continue
        if header and fields and fields[0].lower() == "totals":
            try:
                values = [int(value) for value in fields[1:]]
            except ValueError:
                continue
            if len(values) == len(header):
                final_types = dict(zip(header, values))
    drc_totals = re.findall(
        r"#Total number of DRC violations\s*=\s*([0-9]+)",
        text,
        re.IGNORECASE,
    )
    metrics = {}
    if drc_totals:
        metrics["router_drc_violations"] = float(drc_totals[-1])
    if final_types is not None:
        metrics["router_short_violations"] = float(
            final_types.get("Short", 0) + final_types.get("CShort", 0)
        )
    return metrics


def parse_innovus_verify_drc_summary(text):
    """Extract PG-excluded DRC and short totals from verify_drc stdout."""
    blocks = re.findall(
        r"(Verification Complete\s*:\s*([0-9]+)\s+Viols\..*?"
        r"\*\*\* End Verify DRC.*?)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not blocks:
        return {}
    block, total = blocks[-1]
    header = None
    final_types = None
    awaiting_header = False
    for line in block.splitlines():
        if "Violation Summary By Layer and Type" in line:
            awaiting_header = True
            continue
        fields = line.split()
        if awaiting_header and fields:
            header = fields
            awaiting_header = False
            continue
        if header and fields and fields[0].lower() == "totals":
            try:
                values = [int(value) for value in fields[1:]]
            except ValueError:
                continue
            if len(values) == len(header):
                final_types = dict(zip(header, values))
    metrics = {"verify_drc_violations": float(total)}
    if final_types is not None:
        metrics["verify_short_violations"] = float(
            final_types.get("Short", 0) + final_types.get("CShort", 0)
        )
    elif int(total) == 0:
        metrics["verify_short_violations"] = 0.0
    return metrics


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
    egr_overflows = re.findall(
        r"Overflow\s+after\s+(?:Early\s+Global\s+Route\s+|GR:\s*)"
        r"([0-9.eE+-]+)%\s+H\s*\+\s*([0-9.eE+-]+)%\s+V",
        text,
        re.IGNORECASE,
    )
    if egr_overflows:
        horizontal, vertical = (float(value) for value in egr_overflows[-1])
        metrics["egr_horizontal_congestion"] = horizontal
        metrics["egr_vertical_congestion"] = vertical
        metrics.setdefault("horizontal_congestion", horizontal)
        metrics.setdefault("vertical_congestion", vertical)
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
    total_routable = re.findall(
        r"Total number of routable nets\s*=\s*([0-9]+)",
        text,
        re.IGNORECASE,
    )
    routed = re.findall(
        r"([0-9]+)\s+routable nets have routed wires",
        text,
        re.IGNORECASE,
    )
    if total_routable and routed:
        metrics["unrouted_nets"] = float(max(
            int(total_routable[-1]) - int(routed[-1]), 0
        ))
    metrics.update(parse_innovus_route_violation_summary(text))
    verify_metrics = parse_innovus_verify_drc_summary(text)
    metrics.update(verify_metrics)
    if "verify_drc_violations" in verify_metrics:
        metrics.setdefault("drc_violations", verify_metrics["verify_drc_violations"])
    if "verify_short_violations" in verify_metrics:
        metrics.setdefault("short_violations", verify_metrics["verify_short_violations"])
    return metrics


def parse_innovus_drc_report(text):
    """Extract total DRC and short counts from an Innovus verify_drc report."""
    metrics = {"short_violations": 0.0}
    reported_short_total = None
    for line in text.splitlines():
        if INNOVUS_SHORT_RE.match(line):
            metrics["short_violations"] += 1.0
        match = INNOVUS_TOTAL_DRC_RE.search(line)
        if match:
            metrics["drc_violations"] = float(match.group(1))
        short_match = INNOVUS_TOTAL_SHORT_RE.search(line)
        if short_match:
            reported_short_total = float(short_match.group(1))
    if reported_short_total is not None:
        metrics["short_violations"] = reported_short_total
    return metrics


def parse_innovus_drc_report_file(path, known_short_violations=None):
    """Extract report totals, scanning legacy violation records only if needed."""
    path = Path(path)
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        start = max(0, size - INNOVUS_DRC_REPORT_TAIL_BYTES)
        stream.seek(start)
        tail = stream.read().decode(errors="replace")
    if start:
        tail = tail.split("\n", 1)[-1]
    drc_totals = INNOVUS_TOTAL_DRC_RE.findall(tail)
    short_totals = INNOVUS_TOTAL_SHORT_RE.findall(tail)
    if drc_totals and (short_totals or known_short_violations is not None):
        return {
            "drc_violations": float(drc_totals[-1]),
            "short_violations": (
                float(short_totals[-1]) if short_totals
                else float(known_short_violations)
            ),
        }

    metrics = {"short_violations": 0.0}
    reported_short_total = None
    with path.open(errors="replace") as stream:
        for line in stream:
            if INNOVUS_SHORT_RE.match(line):
                metrics["short_violations"] += 1.0
            match = INNOVUS_TOTAL_DRC_RE.search(line)
            if match:
                metrics["drc_violations"] = float(match.group(1))
            short_match = INNOVUS_TOTAL_SHORT_RE.search(line)
            if short_match:
                reported_short_total = float(short_match.group(1))
    if reported_short_total is not None:
        metrics["short_violations"] = reported_short_total
    return metrics


def parse_innovus_connectivity_report(text):
    """Extract regular-net open/connectivity violations from verifyConnectivity."""
    summary = re.findall(
        r"^\s*([0-9]+)\s+Problem\(s\)\s+\(IMPVFC-[0-9]+\):\s*(.*?)\s*$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    total_match = re.findall(
        r"^\s*([0-9]+)\s+total\s+info\(s\)\s+created\.",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    open_violations = sum(
        int(count) for count, description in summary
        if re.search(r"not connected|open|dangling", description, re.IGNORECASE)
    )
    total = int(total_match[-1]) if total_match else sum(
        int(count) for count, _description in summary
    )
    return {
        "connectivity_violations": float(total),
        "open_violations": float(open_violations),
    }


def innovus_fatal_error(text):
    """Return a fatal Innovus line when its launcher masks the exit status."""
    match = re.search(r"^\*\*(?:ERROR|FATAL):.*$", text, re.MULTILINE)
    return match.group(0).strip() if match else ""


class InnovusEvaluator(RoutabilityEvaluator):
    name = "innovus"

    def evaluate(self, request):
        start = time.time()
        route_mode = str(request.options.get("innovus_route_mode", "global")).lower()
        compact_setting = request.options.get("innovus_compact_drc")
        compact_drc = (
            route_mode == "detailed" if compact_setting is None
            else bool(compact_setting)
        )
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
        connectivity_artifact = request.artifact("innovus_connectivity.rpt")
        congest_artifact = request.artifact("innovus_congest_area.txt")
        temporary = RetainableTemporaryDirectory(
            prefix="routability_eval_", dir=mounted_root
        )
        with temporary as tmp:
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
            connectivity_file = work / "innovus_connectivity.rpt"
            congest_file = work / "innovus_congest_area.txt"
            dump_congest = bool(int(request.options.get("innovus_dump_congest_area", 0) or 0))
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
            if dump_congest:
                # Per-gcell overflow/track dump; the calibration harness aligns it to the GPUGR grid.
                lines.append("catch {dumpCongestArea -all %s}" % tcl_quote(congest_file))
            if route_mode == "global":
                lines.append("catch {reportWire -summary}")
            lines.append("catch {reportCongestion -overflow}")
            lines.extend([
                "set rleval_wl 0",
                "catch {set rleval_wl [expr [join [dbget top.nets.wires.length] +]]}",
                "puts \"RLEVAL_ROUTED_WIRELENGTH $rleval_wl\"",
            ])
            if route_mode == "detailed":
                if compact_drc:
                    lines.append("verify_drc -exclude_pg_net -limit 0")
                else:
                    lines.append(
                        "verify_drc -exclude_pg_net -limit 0 -report %s" %
                        tcl_quote(drc_file)
                    )
                lines.append(
                    "verifyConnectivity -type regular -error 2147483646 "
                    "-warning 2147483646 -report %s" % tcl_quote(connectivity_file)
                )
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
            if compact_drc and not failure:
                compact_metrics = parse_innovus_log(output)
                if all(key in compact_metrics for key in (
                    "verify_drc_violations", "verify_short_violations"
                )):
                    drc_file.write_text(
                        "Total Violations : %d Viols.\n"
                        "Total Short Violations : %d Viols.\n" % (
                            int(compact_metrics["verify_drc_violations"]),
                            int(compact_metrics["verify_short_violations"]),
                        )
                    )
            if metric_file.exists():
                shutil.copy2(metric_file, metric_artifact)
            if drc_file.exists():
                shutil.copy2(drc_file, drc_artifact)
            if connectivity_file.exists():
                shutil.copy2(connectivity_file, connectivity_artifact)
            if congest_file.exists():
                shutil.copy2(congest_file, congest_artifact)
            if failure:
                temporary.retain()
                failure.artifacts["script"] = str(script_artifact)
                failure.artifacts["work_dir"] = str(work)
                for name in ("innovus.log", "innovus.logv"):
                    native_log = work / name
                    if native_log.exists():
                        failure.artifacts["native_" + name.replace(".", "_")] = str(
                            native_log
                        )
                return failure
        metrics = parse_innovus_log(output)
        if drc_artifact.exists():
            metrics.update(parse_innovus_drc_report_file(drc_artifact))
        elif metrics.get("drc_violations") == 0:
            metrics["short_violations"] = 0.0
        if connectivity_artifact.exists():
            metrics.update(parse_innovus_connectivity_report(
                connectivity_artifact.read_text()
            ))
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
        missing_connectivity = route_mode == "detailed" and not all(
            key in metrics for key in (
                "unrouted_nets", "short_violations", "connectivity_violations",
            )
        )
        if (
            fatal_error
            or float(metrics.get("wirelength", 0.0)) <= 0.0
            or missing_drc
            or missing_directional
            or missing_connectivity
        ):
            failure_artifacts = {
                "script": str(script_artifact),
                "metrics": str(metric_artifact),
                "log": str(request.artifact("innovus.log")),
            }
            if drc_artifact.exists():
                failure_artifacts["drc"] = str(drc_artifact)
            if connectivity_artifact.exists():
                failure_artifacts["connectivity"] = str(connectivity_artifact)
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                artifacts=failure_artifacts,
                error=fatal_error or (
                    "Innovus detailed routing completed without a DRC count"
                    if missing_drc else
                    "Innovus detailed routing completed without directional congestion"
                    if missing_directional else
                    "Innovus detailed routing completed without connectivity metrics"
                    if missing_connectivity else
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
                **({"connectivity": str(connectivity_artifact)}
                   if connectivity_artifact.exists() else {}),
                **({"congest_area": str(congest_artifact)}
                   if congest_artifact.exists() else {}),
            },
        )
