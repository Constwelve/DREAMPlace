#!/usr/bin/env python3
"""Rebuild a strict OpenROAD result after an evaluator timeout orphaned Docker."""

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval.openroad import (
    parse_openroad_congestion_report,
    parse_openroad_detailed_route_metrics,
    parse_openroad_log,
)
from tools.routability_golden_replay import result_meets_resume_contract


REQUIRED_FILES = {
    "container_log": "openroad.container.log",
    "drc": "openroad_drc.rpt",
    "metrics": "openroad_metrics.json",
    "congestion": "openroad_congestion.rpt",
    "guide": "openroad.guide",
    "wirelength": "openroad_wirelength.rpt",
    "script": "openroad_eval.tcl",
}

NONEMPTY_FILES = {
    "container_log", "metrics", "guide", "wirelength", "script",
}

REQUIRED_RAW_METRICS = (
    "route__wirelength", "route__vias", "route__drc_errors", "route__net",
)


def required_artifacts(directory):
    directory = Path(directory).resolve()
    artifacts = {}
    for name, filename in REQUIRED_FILES.items():
        path = directory / filename
        if not path.is_file():
            raise ValueError("missing completed OpenROAD artifact: %s" % path)
        if name in NONEMPTY_FILES and path.stat().st_size <= 0:
            raise ValueError("empty completed OpenROAD artifact: %s" % path)
        artifacts[name] = path
    return artifacts


def load_timeout_result(directory):
    directory = Path(directory)
    path = directory / "openroad.json"
    if not path.is_file():
        raise ValueError("missing original timeout result: %s" % path)
    try:
        result = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError("invalid original timeout result: %s" % error)
    if result.get("backend") == "openroad" and result.get("status") == "timeout":
        return result, True
    archived = directory / "openroad.timeout.json"
    if result.get("backend") == "openroad" and result.get("status") == "ok" \
            and archived.is_file():
        try:
            timeout = json.loads(archived.read_text())
        except json.JSONDecodeError as error:
            raise ValueError("invalid archived timeout result: %s" % error)
        if timeout.get("backend") == "openroad" and timeout.get("status") == "timeout":
            return timeout, False
    raise ValueError("original recovery result is not an OpenROAD timeout")


def preserve_timeout_file(source, target):
    source = Path(source)
    target = Path(target)
    if not source.is_file():
        raise ValueError("missing timeout evidence: %s" % source)
    if target.exists():
        if not target.is_file() or source.read_bytes() != target.read_bytes():
            raise ValueError("competing timeout evidence: %s" % target)
        return
    shutil.copy2(source, target)


def derive_metrics(artifacts):
    log_text = artifacts["container_log"].read_text(errors="replace")
    if "[INFO DRT-0198] Complete detail routing." not in log_text:
        raise ValueError("OpenROAD container log lacks detail-route completion")

    try:
        raw = json.loads(artifacts["metrics"].read_text())
    except json.JSONDecodeError as error:
        raise ValueError("invalid completed OpenROAD metrics: %s" % error)
    if not isinstance(raw, dict):
        raise ValueError("completed OpenROAD metrics must be an object")
    missing = [name for name in REQUIRED_RAW_METRICS if name not in raw]
    if missing:
        raise ValueError("completed OpenROAD metrics lack %s" % ", ".join(missing))
    if raw.get("flow__errors__count") != 0:
        raise ValueError("completed OpenROAD metrics report flow errors")

    congestion_text = artifacts["congestion"].read_text(errors="replace")
    wire_text = artifacts["wirelength"].read_text(errors="replace")
    drc_text = artifacts["drc"].read_text(errors="replace")
    metrics = parse_openroad_log(
        log_text + "\n" + wire_text + "\n" + congestion_text + "\n" + drc_text
    )
    metrics.update(parse_openroad_congestion_report(congestion_text))
    metrics["openroad_metrics"] = raw
    metrics["wirelength"] = raw["route__wirelength"]
    metrics["vias"] = raw["route__vias"]
    metrics["drc_violations"] = raw["route__drc_errors"]
    metrics.update(parse_openroad_detailed_route_metrics(log_text, raw))

    if metrics.get("drc_violations") != raw["route__drc_errors"]:
        raise ValueError("final log DRC count disagrees with OpenROAD metrics")
    return metrics


def postprocess(directory, design_name=None):
    directory = Path(directory).resolve()
    artifacts = required_artifacts(directory)
    timeout, preserve_timeout = load_timeout_result(directory)
    if design_name and timeout.get("design_name") != design_name:
        raise ValueError("timeout result design does not match %s" % design_name)

    metrics = derive_metrics(artifacts)
    runtime_sec = max(
        float(timeout.get("runtime_sec", 0.0)),
        max(path.stat().st_mtime for path in artifacts.values())
        - artifacts["script"].stat().st_mtime,
    )
    result_artifacts = {
        "log": str(artifacts["container_log"]),
        "drc": str(artifacts["drc"]),
        "metrics": str(artifacts["metrics"]),
        "congestion": str(artifacts["congestion"]),
        "guide": str(artifacts["guide"]),
        "wirelength": str(artifacts["wirelength"]),
        "script": str(artifacts["script"]),
    }
    result = {
        "backend": "openroad",
        "design_name": timeout.get("design_name", design_name or "unknown"),
        "status": "ok",
        "runtime_sec": runtime_sec,
        "schema_version": timeout.get("schema_version", 1),
        "error": "",
        "metrics": metrics,
        "artifacts": result_artifacts,
        "recovery_postprocess": {
            "source_status": "timeout",
            "full_log": str(artifacts["container_log"]),
            "metric_derivation": [
                "parse_openroad_log",
                "parse_openroad_congestion_report",
                "parse_openroad_detailed_route_metrics",
            ],
        },
    }
    if not result_meets_resume_contract(
        {**result, "authoritative_for_comparison": True}, "openroad"
    ):
        raise ValueError("postprocessed result fails strict OpenROAD contract")

    if preserve_timeout:
        preserve_timeout_file(
            directory / "openroad.json", directory / "openroad.timeout.json"
        )
        preserve_timeout_file(
            directory / "summary.json", directory / "summary.timeout.json"
        )
        preserve_timeout_file(
            directory / "openroad.log", directory / "openroad.timeout.log"
        )
    (directory / "openroad.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    (directory / "summary.json").write_text(
        json.dumps({"results": [result]}, indent=2, sort_keys=True) + "\n"
    )
    if not result_meets_resume_contract(
        {**result, "authoritative_for_comparison": True}, "openroad"
    ):
        raise ValueError("written result fails strict OpenROAD contract")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, action="append", required=True)
    parser.add_argument("--design-name")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    rows = [
        {
            "evaluation_dir": str(directory.resolve()),
            "result": postprocess(directory, design_name=args.design_name),
        }
        for directory in args.evaluation_dir
    ]
    report = {"schema_version": 1, "routes": rows}
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
        print(args.report)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
