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
    }
    for key, candidates in patterns.items():
        for pattern in candidates:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metrics[key] = float(match.group(1))
                break
    return metrics


class OpenROADEvaluator(RoutabilityEvaluator):
    name = "openroad"

    def evaluate(self, request):
        start = time.time()
        guide = request.artifact("openroad.guide")
        congestion = request.artifact("openroad_congestion.rpt")
        metrics_json = request.artifact("openroad_metrics.json")
        wire_report = request.artifact("openroad_wirelength.rpt")
        script = request.artifact("openroad_eval.tcl")
        lines = ["read_lef %s" % tcl_quote(Path(lef).resolve()) for lef in request.lef_input]
        lines.extend([
            "read_def %s" % tcl_quote(Path(request.def_input).resolve()),
            "global_route -allow_congestion -guide_file %s -congestion_report_file %s" %
            (tcl_quote(guide), tcl_quote(congestion)),
            "report_wire_length -global_route -summary -file %s" % tcl_quote(wire_report),
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
        metrics = parse_openroad_log(output + "\n" + report_text + "\n" + congestion_text)
        if metrics_json.exists():
            try:
                raw = json.loads(metrics_json.read_text())
                metrics["openroad_metrics"] = raw
                for source, target in (
                    ("global_route__wirelength", "wirelength"),
                    ("global_route__vias", "vias"),
                    ("global_route__overflow", "overflow"),
                ):
                    if source in raw:
                        metrics[target] = raw[source]
            except json.JSONDecodeError:
                pass
        artifacts = {
            "guide": guide, "congestion": congestion, "metrics": metrics_json,
            "wirelength": wire_report, "script": script,
            "log": request.artifact("openroad.log"),
        }
        serialized_artifacts = {
            key: str(path) for key, path in artifacts.items() if path.exists()
        }
        if float(metrics.get("wirelength", 0.0)) <= 0.0:
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                metrics=metrics,
                artifacts=serialized_artifacts,
                error="OpenROAD completed without positive global-route wirelength",
            )
        return EvaluationResult(
            backend=self.name,
            design_name=request.design_name,
            runtime_sec=time.time() - start,
            metrics=metrics,
            artifacts=serialized_artifacts,
        )
