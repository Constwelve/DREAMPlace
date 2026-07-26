#!/usr/bin/env python3
"""Measure placement distribution and macro-channel patterns in placed DEFs."""

import argparse
import csv
import glob
import json
import math
from pathlib import Path
import re


CORE_PROPERTY = re.compile(
    r"DESIGN\s+FE_CORE_BOX_(LL_X|LL_Y|UR_X|UR_Y)\s+REAL\s+([0-9.eE+-]+)"
)
COMPONENT = re.compile(
    r"^\s*-\s+(\S+)\s+(\S+).*?\+\s+(FIXED|PLACED|COVER)\s+"
    r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)",
    re.IGNORECASE,
)
SWAPPED_ORIENTATIONS = {"E", "W", "FE", "FW"}


def expand_paths(values, base_dir):
    paths = []
    for value in values:
        candidate = Path(value).expanduser()
        pattern = str(candidate if candidate.is_absolute() else base_dir / candidate)
        matches = sorted(glob.glob(pattern))
        paths.extend(Path(path).resolve() for path in (matches or [pattern]))
    return paths


def parse_lef_cells(paths):
    """Return LEF master dimensions and classes without retaining file text."""
    cells = {}
    for path in paths:
        current = None
        cell_class = ""
        width = height = None
        with Path(path).open(errors="replace") as stream:
            for line in stream:
                match = re.match(r"^\s*MACRO\s+(\S+)", line, re.IGNORECASE)
                if match:
                    current = match.group(1)
                    cell_class = ""
                    width = height = None
                    continue
                if current is None:
                    continue
                match = re.match(r"^\s*CLASS\s+(\S+)", line, re.IGNORECASE)
                if match:
                    cell_class = match.group(1).upper()
                    continue
                match = re.match(
                    r"^\s*SIZE\s+([0-9.eE+-]+)\s+BY\s+([0-9.eE+-]+)",
                    line, re.IGNORECASE,
                )
                if match:
                    width, height = float(match.group(1)), float(match.group(2))
                    continue
                if re.match(r"^\s*END\s+%s\s*$" % re.escape(current), line):
                    if width is not None and height is not None:
                        cells[current] = {
                            "width_microns": width,
                            "height_microns": height,
                            "class": cell_class,
                        }
                    current = None
    return cells


def quantile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = fraction * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def grid_statistics(values):
    mean = sum(values) / len(values) if values else 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values) if values else 0.0
    return {
        "mean": mean,
        "coefficient_of_variation": math.sqrt(variance) / mean if mean else 0.0,
        "p95_over_mean": quantile(values, 0.95) / mean if mean else 0.0,
        "max_over_mean": max(values) / mean if mean else 0.0,
        "empty_bin_fraction": (
            sum(value <= 1e-12 for value in values) / len(values) if values else 0.0
        ),
    }


def add_rectangle_to_grid(grid, bins_x, bins_y, bounds, rectangle, value):
    """Distribute rectangle area exactly across overlapping grid bins."""
    xl, yl, xh, yh = bounds
    rx1, ry1, rx2, ry2 = rectangle
    rx1, rx2 = max(rx1, xl), min(rx2, xh)
    ry1, ry2 = max(ry1, yl), min(ry2, yh)
    if rx2 <= rx1 or ry2 <= ry1:
        return
    bin_w = (xh - xl) / bins_x
    bin_h = (yh - yl) / bins_y
    ix1 = max(0, min(bins_x - 1, int((rx1 - xl) / bin_w)))
    iy1 = max(0, min(bins_y - 1, int((ry1 - yl) / bin_h)))
    ix2 = max(0, min(bins_x - 1, int(((rx2 - xl) - 1e-9) / bin_w)))
    iy2 = max(0, min(bins_y - 1, int(((ry2 - yl) - 1e-9) / bin_h)))
    rectangle_area = (rx2 - rx1) * (ry2 - ry1)
    for ix in range(ix1, ix2 + 1):
        bx1, bx2 = xl + ix * bin_w, xl + (ix + 1) * bin_w
        overlap_x = max(0.0, min(rx2, bx2) - max(rx1, bx1))
        for iy in range(iy1, iy2 + 1):
            by1, by2 = yl + iy * bin_h, yl + (iy + 1) * bin_h
            overlap_y = max(0.0, min(ry2, by2) - max(ry1, by1))
            grid[iy * bins_x + ix] += value * overlap_x * overlap_y / rectangle_area


def def_header(path):
    units = 1.0
    die = None
    core_properties = {}
    with Path(path).open(errors="replace") as stream:
        for line in stream:
            match = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", line)
            if match:
                units = float(match.group(1))
            match = re.search(
                r"DIEAREA\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+"
                r"\(\s*(-?\d+)\s+(-?\d+)\s*\)", line,
            )
            if match:
                die = tuple(float(value) for value in match.groups())
            match = CORE_PROPERTY.search(line)
            if match:
                core_properties[match.group(1)] = float(match.group(2)) * units
            if line.lstrip().startswith("COMPONENTS "):
                break
    if len(core_properties) == 4:
        bounds = tuple(core_properties[key] for key in ("LL_X", "LL_Y", "UR_X", "UR_Y"))
        source = "FE_CORE_BOX"
    elif die:
        bounds = die
        source = "DIEAREA"
    else:
        raise ValueError("DEF has no parseable DIEAREA: %s" % path)
    return units, bounds, source


def analyze_def(path, lef_cells, bins_x=32, bins_y=32, edge_fraction=0.1):
    path = Path(path).resolve()
    units, bounds, bounds_source = def_header(path)
    xl, yl, xh, yh = bounds
    width, height = xh - xl, yh - yl
    bin_area = width * height / (bins_x * bins_y)
    count_grid = [0.0] * (bins_x * bins_y)
    stdcell_area_grid = [0.0] * (bins_x * bins_y)
    macro_area_grid = [0.0] * (bins_x * bins_y)
    x_hist = [0] * 1000
    y_hist = [0] * 1000
    counts = {
        "components": 0, "placed": 0, "fixed": 0, "cover": 0,
        "fixed_macros": 0, "movable_macros": 0, "standard_cells": 0,
        "unknown_masters": 0, "outside_core": 0,
    }
    edge_count = center_count = 0
    macro_rectangles = []

    in_components = False
    with path.open(errors="replace") as stream:
        for line in stream:
            if line.lstrip().startswith("COMPONENTS "):
                in_components = True
                continue
            if not in_components:
                continue
            if line.lstrip().startswith("END COMPONENTS"):
                break
            match = COMPONENT.match(line)
            if not match:
                continue
            _, master, status, raw_x, raw_y, orientation = match.groups()
            status = status.lower()
            counts["components"] += 1
            counts[status] += 1
            cell = lef_cells.get(master)
            if cell is None:
                for suffix in ("_upper", "_bottom"):
                    if master.endswith(suffix):
                        cell = lef_cells.get(master[:-len(suffix)])
                        if cell is not None:
                            break
            if cell is None:
                counts["unknown_masters"] += 1
                cell = {"width_microns": 0.0, "height_microns": 0.0, "class": ""}
            cell_w = cell["width_microns"] * units
            cell_h = cell["height_microns"] * units
            if orientation.upper() in SWAPPED_ORIENTATIONS:
                cell_w, cell_h = cell_h, cell_w
            x, y = float(raw_x), float(raw_y)
            cx, cy = x + cell_w / 2.0, y + cell_h / 2.0
            nx = (cx - xl) / width
            ny = (cy - yl) / height
            if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
                counts["outside_core"] += 1
                continue
            ix = min(bins_x - 1, max(0, int(nx * bins_x)))
            iy = min(bins_y - 1, max(0, int(ny * bins_y)))
            count_grid[iy * bins_x + ix] += 1.0
            x_hist[min(999, int(nx * 1000))] += 1
            y_hist[min(999, int(ny * 1000))] += 1
            if nx < edge_fraction or nx > 1.0 - edge_fraction or ny < edge_fraction or ny > 1.0 - edge_fraction:
                edge_count += 1
            if 0.25 <= nx <= 0.75 and 0.25 <= ny <= 0.75:
                center_count += 1

            is_macro = cell["class"] in ("BLOCK", "PAD", "RING")
            area = cell_w * cell_h
            if is_macro:
                key = "fixed_macros" if status in ("fixed", "cover") else "movable_macros"
                counts[key] += 1
                rectangle = (x, y, x + cell_w, y + cell_h)
                macro_rectangles.append(rectangle)
                add_rectangle_to_grid(
                    macro_area_grid, bins_x, bins_y, bounds, rectangle, area
                )
            else:
                counts["standard_cells"] += 1
                stdcell_area_grid[iy * bins_x + ix] += area

    inside = counts["components"] - counts["outside_core"]
    occupancy = [value / bin_area for value in stdcell_area_grid]
    macro_coverage = [min(1.0, value / bin_area) for value in macro_area_grid]
    near_macro = []
    far_from_macro = []
    for iy in range(bins_y):
        for ix in range(bins_x):
            index = iy * bins_x + ix
            neighboring_macro = any(
                macro_coverage[ny * bins_x + nx] > 0.01
                for ny in range(max(0, iy - 1), min(bins_y, iy + 2))
                for nx in range(max(0, ix - 1), min(bins_x, ix + 2))
            )
            if macro_coverage[index] < 0.5:
                (near_macro if neighboring_macro else far_from_macro).append(occupancy[index])

    def histogram_quantile(histogram, fraction):
        target = fraction * max(0, sum(histogram) - 1)
        cumulative = 0
        for index, count in enumerate(histogram):
            cumulative += count
            if cumulative > target:
                return (index + 0.5) / len(histogram)
        return 0.0

    result = {
        "def_input": str(path),
        "bounds_source": bounds_source,
        "core_bounds_dbu": list(bounds),
        "dbu_per_micron": units,
        "grid": {"bins_x": bins_x, "bins_y": bins_y},
        "counts": counts,
        "normalized_position": {
            "x_p10": histogram_quantile(x_hist, 0.10),
            "x_p50": histogram_quantile(x_hist, 0.50),
            "x_p90": histogram_quantile(x_hist, 0.90),
            "y_p10": histogram_quantile(y_hist, 0.10),
            "y_p50": histogram_quantile(y_hist, 0.50),
            "y_p90": histogram_quantile(y_hist, 0.90),
            "edge_fraction": edge_count / inside if inside else 0.0,
            "center_fraction": center_count / inside if inside else 0.0,
        },
        "component_count_grid": grid_statistics(count_grid),
        "standard_cell_area_grid": grid_statistics(occupancy),
        "macro_pattern": {
            "macro_count": len(macro_rectangles),
            "macro_covered_bin_fraction": sum(value > 0.01 for value in macro_coverage) / len(macro_coverage),
            "macro_blocked_bin_fraction": sum(value >= 0.5 for value in macro_coverage) / len(macro_coverage),
            "mean_standard_cell_utilization_near_macro": sum(near_macro) / len(near_macro) if near_macro else 0.0,
            "mean_standard_cell_utilization_far_from_macro": sum(far_from_macro) / len(far_from_macro) if far_from_macro else 0.0,
        },
    }
    near = result["macro_pattern"]["mean_standard_cell_utilization_near_macro"]
    far = result["macro_pattern"]["mean_standard_cell_utilization_far_from_macro"]
    result["macro_pattern"]["near_to_far_stdcell_utilization_ratio"] = near / far if far else 0.0
    return result


def flatten_result(name, result):
    row = {"case": name, "def_input": result["def_input"]}
    for prefix, section in (
        ("count", result["counts"]),
        ("position", result["normalized_position"]),
        ("component_grid", result["component_count_grid"]),
        ("stdcell_grid", result["standard_cell_area_grid"]),
        ("macro", result["macro_pattern"]),
    ):
        row.update({"%s_%s" % (prefix, key): value for key, value in section.items()})
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bins-x", type=int, default=32)
    parser.add_argument("--bins-y", type=int, default=32)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    base_dir = args.manifest.resolve().parent
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    rows = []
    for case in manifest.get("cases", []):
        lef_paths = expand_paths(case.get("lef_input", []), base_dir)
        cells = parse_lef_cells(lef_paths)
        def_path = expand_paths([case["def_input"]], base_dir)[0]
        result = analyze_def(def_path, cells, args.bins_x, args.bins_y)
        result.update({"name": case["name"], "lef_inputs": [str(path) for path in lef_paths]})
        results.append(result)
        rows.append(flatten_result(case["name"], result))
        print("%s: %d components, %d macros" % (
            case["name"], result["counts"]["components"],
            result["macro_pattern"]["macro_count"],
        ))
    (args.output_dir / "placement_distribution.json").write_text(
        json.dumps({"results": results}, indent=2, sort_keys=True) + "\n"
    )
    fields = sorted({key for row in rows for key in row})
    with (args.output_dir / "placement_distribution.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
