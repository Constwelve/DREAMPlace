#!/usr/bin/env python3
"""Materialize Verilog connectivity into a physical DEF with OpenROAD."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time


COUNT_RE = re.compile(r"^\s*(COMPONENTS|PINS|NETS)\s+(\d+)\s*;", re.IGNORECASE)
MODULE_RE = re.compile(r"^\s*module\s+([^\s(#;]+)")
UPDATED_COMPONENTS_RE = re.compile(r"Updated\s+(\d+)\s+components", re.IGNORECASE)


def def_counts(path):
    counts = {}
    complete = False
    with path.open(errors="ignore") as stream:
        for line in stream:
            match = COUNT_RE.match(line)
            if match:
                counts[match.group(1).lower()] = int(match.group(2))
            elif line.strip().upper() == "END DESIGN":
                complete = True
    counts["complete"] = complete
    return counts


def infer_top_module(path):
    with path.open(errors="ignore") as stream:
        for line in stream:
            match = MODULE_RE.match(line)
            if match:
                return match.group(1)
    raise ValueError("cannot infer a top module from %s" % path)


def tcl_quote(value):
    value = str(value)
    if "\n" in value or "\r" in value:
        raise ValueError("Tcl path/value contains a newline")
    escaped = value.replace("\\", "\\\\")
    for char in ('$', '[', ']', '"'):
        escaped = escaped.replace(char, "\\" + char)
    return '"%s"' % escaped


def build_tcl(lefs, verilog, top_module, floorplan_def, output_def):
    lines = ["read_lef %s" % tcl_quote(path) for path in lefs]
    lines.extend([
        "read_verilog %s" % tcl_quote(verilog),
        "link_design %s" % tcl_quote(top_module),
        "read_def -floorplan_initialize %s" % tcl_quote(floorplan_def),
        "write_def %s" % tcl_quote(output_def),
    ])
    return "\n".join(lines) + "\n"


def materialize(openroad, lefs, verilog, top_module, floorplan_def, output_def,
                log_path, timeout_sec, min_component_retention,
                min_physical_match_retention, max_unplaced_component_fraction):
    for path in [*lefs, verilog, floorplan_def]:
        if not path.is_file():
            raise FileNotFoundError(path)
    if output_def.exists():
        raise FileExistsError(output_def)
    output_def.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    input_counts = def_counts(floorplan_def)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ruplace-materialize-") as directory:
        script = Path(directory) / "materialize.tcl"
        script.write_text(build_tcl(
            lefs, verilog, top_module, floorplan_def, output_def
        ))
        result = subprocess.run(
            [str(openroad), "-no_init", "-exit", str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=None if timeout_sec <= 0 else timeout_sec,
        )
    elapsed = time.monotonic() - started
    log_path.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(
            "OpenROAD failed with return code %d; see %s"
            % (result.returncode, log_path)
        )
    if not output_def.is_file():
        raise RuntimeError("OpenROAD did not create %s" % output_def)

    output_counts = def_counts(output_def)
    input_components = input_counts.get("components", 0)
    output_components = output_counts.get("components", 0)
    component_ratio = (
        float(output_components) / input_components if input_components else 0.0
    )
    updated_matches = [
        int(match.group(1))
        for match in UPDATED_COMPONENTS_RE.finditer(result.stdout)
    ]
    matched_components = updated_matches[-1] if updated_matches else 0
    physical_match_retention = (
        float(matched_components) / input_components if input_components else 0.0
    )
    unplaced_linked_components = max(0, output_components - matched_components)
    unplaced_component_fraction = (
        float(unplaced_linked_components) / output_components
        if output_components else 1.0
    )
    errors = []
    if not output_counts["complete"]:
        errors.append("output DEF is incomplete")
    if output_components <= 0:
        errors.append("output DEF has no components")
    if output_counts.get("nets", 0) <= 0:
        errors.append("output DEF has no regular nets")
    if component_ratio < min_component_retention:
        errors.append(
            "component retention %.6f is below %.6f"
            % (component_ratio, min_component_retention)
        )
    if physical_match_retention < min_physical_match_retention:
        errors.append(
            "physical component match retention %.6f is below %.6f"
            % (physical_match_retention, min_physical_match_retention)
        )
    if unplaced_component_fraction > max_unplaced_component_fraction:
        errors.append(
            "unplaced linked component fraction %.6f exceeds %.6f"
            % (unplaced_component_fraction, max_unplaced_component_fraction)
        )
    metrics = {
        "status": "failed" if errors else "ok",
        "openroad": str(openroad),
        "lef_input": [str(path) for path in lefs],
        "verilog_input": str(verilog),
        "top_module": top_module,
        "floorplan_def": str(floorplan_def),
        "output_def": str(output_def),
        "log": str(log_path),
        "runtime_sec": elapsed,
        "input_counts": input_counts,
        "output_counts": output_counts,
        "component_ratio": component_ratio,
        "matched_physical_components": matched_components,
        "physical_match_retention": physical_match_retention,
        "dropped_physical_components": max(0, input_components - matched_components),
        "unplaced_linked_components": unplaced_linked_components,
        "unplaced_component_fraction": unplaced_component_fraction,
        "errors": errors,
    }
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lef", action="append", type=Path, required=True)
    parser.add_argument("--verilog", type=Path, required=True)
    parser.add_argument("--top-module", default="")
    parser.add_argument("--floorplan-def", type=Path, required=True)
    parser.add_argument("--output-def", type=Path, required=True)
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--openroad", type=Path, default=Path("/usr/bin/openroad"))
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--min-component-retention", type=float, default=0.95)
    parser.add_argument("--min-physical-match-retention", type=float, default=0.99)
    parser.add_argument("--max-unplaced-component-fraction", type=float, default=0.01)
    args = parser.parse_args(argv)

    if not 0.0 < args.min_component_retention <= 1.0:
        raise ValueError("--min-component-retention must be in (0, 1]")
    if not 0.0 < args.min_physical_match_retention <= 1.0:
        raise ValueError("--min-physical-match-retention must be in (0, 1]")
    if not 0.0 <= args.max_unplaced_component_fraction < 1.0:
        raise ValueError("--max-unplaced-component-fraction must be in [0, 1)")
    top_module = args.top_module or infer_top_module(args.verilog)
    metrics_path = args.metrics or args.output_def.with_suffix(
        args.output_def.suffix + ".materialize.json"
    )
    log_path = args.log or args.output_def.with_suffix(
        args.output_def.suffix + ".materialize.log"
    )
    metrics = materialize(
        args.openroad, args.lef, args.verilog, top_module,
        args.floorplan_def, args.output_def, log_path,
        args.timeout_sec, args.min_component_retention,
        args.min_physical_match_retention,
        args.max_unplaced_component_fraction,
    )
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0 if metrics["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
