"""OpenROAD FastRoute evaluator adapter."""

import json
from pathlib import Path
import re
import time

from .base import EvaluationResult, RoutabilityEvaluator


def tcl_quote(value):
    return "{" + str(value).replace("}", "\\}") + "}"


def parse_openroad_log(text):
    metrics = {}
    patterns = {
        "wirelength": [
            r"Total\s+(?:Global Route\s+)?Wirelength\s*[:=]\s*([0-9.eE+-]+)",
            r"Total wire length\s*=\s*([0-9.eE+-]+)",
        ],
        "overflow": [
            r"Total\s+(?:routing\s+)?overflow\s*[:=]\s*([0-9.eE+-]+)",
            r"overflow\s*=\s*([0-9.eE+-]+)",
        ],
        "vias": [r"Total\s+vias\s*[:=]\s*([0-9.eE+-]+)"],
        "drc_violations": [
            r"RLEVAL_DRC_COUNT\s+([0-9.eE+-]+)",
            r"Number of violations\s*[=:]\s*([0-9.eE+-]+)",
            r"Total violations\s*[=:]\s*([0-9.eE+-]+)",
        ],
    }
    for key, candidates in patterns.items():
        for pattern in candidates:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metrics[key] = float(match.group(1))
                break
    return metrics


def parse_openroad_congestion_report(text):
    """Aggregate FastRoute overflow separately by routing direction."""
    metrics = {
        "horizontal_overflow": 0.0,
        "vertical_overflow": 0.0,
        "horizontal_overflow_edges": 0,
        "vertical_overflow_edges": 0,
    }
    entries = re.findall(
        r"violation type:\s*(Horizontal|Vertical) congestion.*?"
        r"comment:\s*capacity:\s*([0-9.eE+-]+)\s+"
        r"usage:\s*([0-9.eE+-]+)\s+overflow:\s*([0-9.eE+-]+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    for direction, _capacity, _usage, overflow in entries:
        prefix = direction.lower()
        metrics[prefix + "_overflow"] += float(overflow)
        metrics[prefix + "_overflow_edges"] += 1
    metrics["total_overflow"] = (
        metrics["horizontal_overflow"] + metrics["vertical_overflow"]
    )
    metrics["overflow"] = metrics["total_overflow"]
    return metrics


class OpenROADEvaluator(RoutabilityEvaluator):
    name = "openroad"

    def evaluate(self, request):
        start = time.time()
        route_mode = str(request.options.get("openroad_route_mode", "global")).lower()
        if route_mode not in ("global", "detailed"):
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="unsupported",
                error="openroad_route_mode must be global or detailed",
            )
        guide = request.artifact("openroad.guide")
        congestion = request.artifact("openroad_congestion.rpt")
        metrics_json = request.artifact("openroad_metrics.json")
        wire_report = request.artifact("openroad_wirelength.rpt")
        script = request.artifact("openroad_eval.tcl")
        drc_report = request.artifact("openroad_drc.rpt")
        lines = ["read_lef %s" % tcl_quote(Path(lef).resolve()) for lef in request.lef_input]
        lines.extend([
            "read_def %s" % tcl_quote(Path(request.def_input).resolve()),
            "global_route -allow_congestion -guide_file %s -congestion_report_file %s" %
            (tcl_quote(guide), tcl_quote(congestion)),
            "report_wire_length -global_route -summary -file %s" % tcl_quote(wire_report),
        ])
        if route_mode == "detailed":
            lines.extend([
                "detailed_route -output_drc %s -droute_end_iter %d" % (
                    tcl_quote(drc_report), int(
                        request.options.get("openroad_droute_end_iteration", 20)
                    )
                ),
                "report_wire_length -detailed_route -summary -file %s" %
                tcl_quote(wire_report),
            ])
        script.write_text("\n".join(lines) + "\n")
        command = [
            request.options.get("openroad_binary", "openroad"),
            "-no_init", "-no_splash", "-exit",
            "-threads", str(request.num_threads),
            "-metrics", str(metrics_json), str(script),
        ]
        output, failure = self.run(request, command)
        if failure:
            failure.artifacts.update({"script": str(script), "congestion": str(congestion)})
            return failure
        report_text = wire_report.read_text() if wire_report.exists() else ""
        congestion_text = congestion.read_text() if congestion.exists() else ""
        drc_text = drc_report.read_text() if drc_report.exists() else ""
        metrics = parse_openroad_log(
            output + "\n" + report_text + "\n" + congestion_text + "\n" + drc_text
        )
        metrics.update(parse_openroad_congestion_report(congestion_text))
        if metrics_json.exists():
            try:
                raw = json.loads(metrics_json.read_text())
                metrics["openroad_metrics"] = raw
                for source, target in (
                    ("global_route__wirelength", "wirelength"),
                    ("global_route__vias", "vias"),
                    ("global_route__overflow", "overflow"),
                ):
                    if source in raw and (
                        route_mode == "global" or target not in ("wirelength", "vias")
                    ):
                        metrics[target] = raw[source]
                if route_mode == "detailed":
                    for source, target in (
                        ("route__wirelength", "wirelength"),
                        ("route__vias", "vias"),
                        ("route__drc_errors", "drc_violations"),
                    ):
                        if source in raw:
                            metrics[target] = raw[source]
            except json.JSONDecodeError:
                pass
        artifacts = {
            "guide": guide, "congestion": congestion, "metrics": metrics_json,
            "wirelength": wire_report, "script": script,
            "log": request.artifact("openroad.log"),
            "drc": drc_report,
        }
        serialized_artifacts = {
            key: str(path) for key, path in artifacts.items() if path.exists()
        }
        missing_drc = route_mode == "detailed" and "drc_violations" not in metrics
        missing_directional = route_mode == "detailed" and not all(
            key in metrics for key in ("horizontal_overflow", "vertical_overflow")
        )
        if (
            float(metrics.get("wirelength", 0.0)) <= 0.0
            or missing_drc
            or missing_directional
        ):
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                metrics=metrics,
                artifacts=serialized_artifacts,
                error=(
                    "OpenROAD detailed routing completed without a DRC count"
                    if missing_drc else
                    "OpenROAD detailed routing completed without directional congestion"
                    if missing_directional else
                    "OpenROAD completed without positive routed wirelength"
                ),
            )
        return EvaluationResult(
            backend=self.name,
            design_name=request.design_name,
            runtime_sec=time.time() - start,
            metrics=metrics,
            artifacts=serialized_artifacts,
        )
