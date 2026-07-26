#!/usr/bin/env python3
"""Snap DEF component locations to the LEF manufacturing grid."""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


MANUFACTURING_GRID_RE = re.compile(
    r"\bMANUFACTURINGGRID\s+([0-9]+(?:\.[0-9]+)?)\s*;", re.IGNORECASE
)
DEF_UNITS_RE = re.compile(
    r"\bUNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", re.IGNORECASE
)
COMPONENTS_RE = re.compile(
    r"(^\s*COMPONENTS\s+\d+\s*;\s*$)(.*?)(^\s*END\s+COMPONENTS\s*$)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
LOCATION_RE = re.compile(
    r"(\+\s*(?:PLACED|FIXED|COVER)\s*\(\s*)([-+]?\d+)(\s+)([-+]?\d+)(\s*\))",
    re.IGNORECASE,
)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manufacturing_grid_microns(lef_paths):
    values = set()
    for path in lef_paths:
        values.update(Decimal(value) for value in MANUFACTURING_GRID_RE.findall(
            path.read_text(errors="replace")
        ))
    if not values:
        raise ValueError("LEF inputs do not declare MANUFACTURINGGRID")
    if len(values) != 1:
        raise ValueError(
            "conflicting LEF manufacturing grids: %s"
            % ", ".join(str(value) for value in sorted(values))
        )
    value = values.pop()
    if value <= 0:
        raise ValueError("manufacturing grid must be positive")
    return value


def def_units_per_micron(text):
    matches = {int(value) for value in DEF_UNITS_RE.findall(text)}
    if len(matches) != 1:
        raise ValueError("DEF must declare exactly one UNITS DISTANCE MICRONS")
    return matches.pop()


def grid_in_def_units(grid_microns, units_per_micron):
    scaled = grid_microns * units_per_micron
    integral = scaled.to_integral_value()
    if scaled != integral or integral <= 0:
        raise ValueError(
            "manufacturing grid %s is not integral at %d DEF units per micron"
            % (grid_microns, units_per_micron)
        )
    return int(integral)


def snap_coordinate(value, grid):
    sign = -1 if value < 0 else 1
    magnitude = abs(value)
    return sign * (((magnitude + grid // 2) // grid) * grid)


def snap_components(text, grid):
    section = COMPONENTS_RE.search(text)
    if not section:
        raise ValueError("DEF lacks a COMPONENTS section")
    placement_count = 0
    changed_components = 0
    changed_coordinates = 0
    max_delta_x = 0
    max_delta_y = 0

    def replace_location(match):
        nonlocal placement_count, changed_components, changed_coordinates
        nonlocal max_delta_x, max_delta_y
        placement_count += 1
        x = int(match.group(2))
        y = int(match.group(4))
        snapped_x = snap_coordinate(x, grid)
        snapped_y = snap_coordinate(y, grid)
        delta_x = abs(snapped_x - x)
        delta_y = abs(snapped_y - y)
        if delta_x or delta_y:
            changed_components += 1
            changed_coordinates += int(bool(delta_x)) + int(bool(delta_y))
            max_delta_x = max(max_delta_x, delta_x)
            max_delta_y = max(max_delta_y, delta_y)
        return "%s%d%s%d%s" % (
            match.group(1), snapped_x, match.group(3), snapped_y, match.group(5)
        )

    body = LOCATION_RE.sub(replace_location, section.group(2))
    if not placement_count:
        raise ValueError("DEF COMPONENTS section has no placed locations")
    result = text[:section.start(2)] + body + text[section.end(2):]
    return result, {
        "placement_count": placement_count,
        "changed_components": changed_components,
        "changed_coordinates": changed_coordinates,
        "max_delta_x_dbu": max_delta_x,
        "max_delta_y_dbu": max_delta_y,
    }


def snap_def(def_input, lef_inputs, output, report_path=None):
    def_input = Path(def_input).resolve()
    lef_inputs = [Path(path).resolve() for path in lef_inputs]
    output = Path(output).resolve()
    if output == def_input:
        raise ValueError("snap output must differ from input DEF")
    text = def_input.read_text(errors="strict")
    grid_microns = manufacturing_grid_microns(lef_inputs)
    units_per_micron = def_units_per_micron(text)
    grid_dbu = grid_in_def_units(grid_microns, units_per_micron)
    snapped, stats = snap_components(text, grid_dbu)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(snapped)
    report = {
        "input_def": str(def_input),
        "output_def": str(output),
        "lef_inputs": [str(path) for path in lef_inputs],
        "manufacturing_grid_microns": str(grid_microns),
        "def_units_per_micron": units_per_micron,
        "manufacturing_grid_dbu": grid_dbu,
        "input_sha256": file_sha256(def_input),
        "output_sha256": file_sha256(output),
        **stats,
    }
    if report_path:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lef-input", type=Path, action="append", required=True)
    parser.add_argument("--def-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    snap_def(args.def_input, args.lef_input, args.output, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
