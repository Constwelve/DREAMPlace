#!/usr/bin/env python3
"""Project route-directed DEF displacements onto legal row whitespace."""

import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re

try:
    from tools.routability_blend_def import (
        COMPONENTS_RE,
        COMPONENT_RE,
        LOCATION_RE,
        file_sha256,
    )
except ModuleNotFoundError:
    from routability_blend_def import (
        COMPONENTS_RE,
        COMPONENT_RE,
        LOCATION_RE,
        file_sha256,
    )


UNITS_RE = re.compile(
    r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;",
    re.IGNORECASE | re.MULTILINE,
)
ROW_RE = re.compile(
    r"^\s*ROW\s+\S+\s+\S+\s+([-+]?\d+)\s+([-+]?\d+)\s+\S+\s+"
    r"DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+([-+]?\d+)\s+([-+]?\d+)",
    re.IGNORECASE | re.MULTILINE,
)
COMPONENT_HEADER_RE = re.compile(r"^\s*-\s+(\S+)\s+(\S+)", re.MULTILINE)
NETS_RE = re.compile(
    r"^\s*NETS\s+\d+\s*;(.*?)^\s*END\s+NETS\s*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
NET_RE = re.compile(r"^\s*-\s+\S+(.*?);", re.MULTILINE | re.DOTALL)
NET_CONNECTION_RE = re.compile(r"\(\s*(\S+)\s+\S+[^)]*\)")
LEF_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)", re.IGNORECASE)
LEF_SIZE_RE = re.compile(
    r"^\s*SIZE\s+([0-9.eE+-]+)\s+BY\s+([0-9.eE+-]+)\s*;",
    re.IGNORECASE,
)
LEF_END_RE = re.compile(r"^\s*END\s+(\S+)", re.IGNORECASE)


def _microns_to_dbu(value, dbu):
    return int(
        (Decimal(value) * Decimal(dbu)).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )


def parse_macro_sizes(lef_inputs, dbu):
    sizes = {}
    for lef in lef_inputs:
        current = None
        current_size = None
        for line in Path(lef).read_text(errors="strict").splitlines():
            macro = LEF_MACRO_RE.match(line)
            if macro:
                current = macro.group(1)
                current_size = None
                continue
            if current is None:
                continue
            size = LEF_SIZE_RE.match(line)
            if size:
                current_size = (
                    _microns_to_dbu(size.group(1), dbu),
                    _microns_to_dbu(size.group(2), dbu),
                )
                continue
            end = LEF_END_RE.match(line)
            if end and end.group(1) == current:
                if current_size is None:
                    raise ValueError("LEF macro %s lacks SIZE" % current)
                if current in sizes and sizes[current] != current_size:
                    raise ValueError("conflicting LEF sizes for macro %s" % current)
                sizes[current] = current_size
                current = None
                current_size = None
    if not sizes:
        raise ValueError("LEF inputs contain no sized macros")
    return sizes


def parse_rows(def_text):
    rows = []
    for match in ROW_RE.finditer(def_text):
        x, y, count_x, count_y, step_x, step_y = map(int, match.groups())
        if count_y != 1 or step_y != 0 or count_x <= 0 or step_x <= 0:
            continue
        rows.append({
            "x": x,
            "y": y,
            "site_count": count_x,
            "site_width": step_x,
            "xh": x + count_x * step_x,
        })
    if not rows:
        raise ValueError("DEF contains no horizontal placement rows")
    by_y = {}
    for row in rows:
        if row["y"] in by_y:
            raise ValueError("multiple DEF rows share y=%d" % row["y"])
        by_y[row["y"]] = row
    return by_y


def parse_geometry_row_levels(def_text):
    """Return unique horizontal row levels, accepting split row segments."""
    levels = {}
    for match in ROW_RE.finditer(def_text):
        x, y, count_x, count_y, step_x, step_y = map(int, match.groups())
        if count_y != 1 or step_y != 0 or count_x <= 0 or step_x <= 0:
            continue
        xh = x + count_x * step_x
        if y not in levels:
            levels[y] = {
                "x": x,
                "y": y,
                "site_count": count_x,
                "site_width": step_x,
                "xh": xh,
            }
        else:
            levels[y]["x"] = min(levels[y]["x"], x)
            levels[y]["xh"] = max(levels[y]["xh"], xh)
            levels[y]["site_count"] += count_x
    if not levels:
        raise ValueError("DEF contains no horizontal placement rows")
    return levels


def parse_components(def_text, macro_sizes, rows):
    section = COMPONENTS_RE.search(def_text)
    if not section:
        raise ValueError("DEF lacks a COMPONENTS section")
    row_values = sorted(rows.values(), key=lambda row: row["y"])
    records = {}
    for match in COMPONENT_RE.finditer(section.group(2)):
        statement = match.group(1)
        header = COMPONENT_HEADER_RE.search(statement)
        if not header:
            raise ValueError("malformed DEF component statement")
        name, macro = header.groups()
        if name in records:
            raise ValueError("duplicate DEF component %s" % name)
        location = LOCATION_RE.search(statement)
        if not location:
            records[name] = {
                "name": name, "macro": macro, "kind": "UNPLACED",
                "x": None, "y": None, "orientation": "",
                "width": None, "height": None, "rows": [],
            }
            continue
        if macro not in macro_sizes:
            raise ValueError("missing LEF size for component macro %s" % macro)
        width, height = macro_sizes[macro]
        x = int(location.group(3))
        y = int(location.group(5))
        orientation = location.group(7).upper()
        if orientation in ("E", "W", "FE", "FW"):
            width, height = height, width
        covered = [
            row["y"] for row in row_values
            if row["y"] >= y and row["y"] < y + height
        ]
        records[name] = {
            "name": name,
            "macro": macro,
            "kind": location.group(2).upper(),
            "x": x,
            "y": y,
            "orientation": orientation,
            "width": width,
            "height": height,
            "rows": covered,
        }
    if not records:
        raise ValueError("DEF COMPONENTS section is empty")
    return section, records


def parse_component_nets(def_text, records):
    """Return signal-net memberships using component origins as pin proxies."""
    section = NETS_RE.search(def_text)
    if not section:
        raise ValueError("baseline DEF lacks a NETS section for net-bbox ranking")
    nets = []
    incident = {name: [] for name in records}
    for statement in NET_RE.finditer(section.group(1)):
        names = []
        seen = set()
        for connection in NET_CONNECTION_RE.finditer(statement.group(1)):
            name = connection.group(1)
            if (
                name.upper() == "PIN"
                or name not in records
                or records[name]["x"] is None
                or name in seen
            ):
                continue
            seen.add(name)
            names.append(name)
        if len(names) < 2:
            continue
        net_index = len(nets)
        nets.append(tuple(names))
        for name in names:
            incident[name].append(net_index)
    if not nets:
        raise ValueError("baseline DEF has no multi-component signal nets")
    return nets, incident


def net_bbox_x_sum(records, nets):
    return sum(
        max(records[name]["x"] for name in net)
        - min(records[name]["x"] for name in net)
        for net in nets
    )


def component_net_bbox_delta(record, new_x, records, nets, incident):
    delta = 0
    for net_index in incident[record["name"]]:
        net = nets[net_index]
        before = [records[name]["x"] for name in net]
        after = [new_x if name == record["name"] else records[name]["x"]
                 for name in net]
        delta += max(after) - min(after) - (max(before) - min(before))
    return delta


def _overlap_pairs(records, rows):
    pairs = set()
    for row_y in rows:
        occupied = sorted(
            (record["x"], record["x"] + record["width"], record["name"])
            for record in records.values()
            if record["x"] is not None and row_y in record["rows"]
        )
        active = []
        for xl, xh, name in occupied:
            active = [item for item in active if item[1] > xl]
            for _, _, other in active:
                pairs.add(tuple(sorted((name, other))))
            active.append((xl, xh, name))
    return pairs


def placement_geometry_provenance(def_path, lef_inputs):
    """Return independently parsed geometry evidence for an exported DEF."""
    def_path = Path(def_path).resolve()
    if isinstance(lef_inputs, (str, Path)):
        lef_inputs = [lef_inputs]
    lef_inputs = [Path(path).resolve() for path in lef_inputs if path]
    result = {
        "schema_version": 1,
        "def_path": str(def_path),
        "def_sha256": file_sha256(def_path),
        "lef_sha256": {
            str(path): file_sha256(path) for path in lef_inputs
        },
    }
    if not lef_inputs:
        result.update({
            "status": "not_checked",
            "reason": "no LEF input was configured",
        })
        return result

    text = def_path.read_text(errors="strict")
    units = UNITS_RE.search(text)
    if not units:
        raise ValueError("exported DEF lacks distance units")
    dbu = int(units.group(1))
    rows = parse_geometry_row_levels(text)
    _, records = parse_components(
        text, parse_macro_sizes(lef_inputs, dbu), rows
    )
    overlap_pairs = _overlap_pairs(records, rows)
    unplaced = sorted(
        record["name"] for record in records.values()
        if record["x"] is None
    )
    uncovered = sorted(
        record["name"] for record in records.values()
        if (
            record["kind"] == "PLACED"
            and record["x"] is not None
            and not record["rows"]
        )
    )
    result.update({
        "status": "ok",
        "dbu_per_micron": dbu,
        "component_count": len(records),
        "row_count": len(rows),
        "overlap_pair_count": len(overlap_pairs),
        "unplaced_component_count": len(unplaced),
        "uncovered_component_count": len(uncovered),
        "overlap_pair_sample": [list(pair) for pair in sorted(overlap_pairs)[:10]],
        "unplaced_component_sample": unplaced[:10],
        "uncovered_component_sample": uncovered[:10],
    })
    return result


def legal_whitespace_slide(baseline_text, candidate_text, macro_sizes,
                           max_steps=1, max_moved_fraction=1.0,
                           min_moved_fraction=0.0,
                           moved_fraction_windows=None,
                           direction="both", sweep_order="right_left",
                           rank_mode="displacement",
                           max_net_bbox_delta_dbu=None):
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    if moved_fraction_windows is None:
        moved_fraction_windows = [
            (min_moved_fraction, max_moved_fraction)
        ]
    else:
        moved_fraction_windows = [
            (float(start), float(stop))
            for start, stop in moved_fraction_windows
        ]
    if not moved_fraction_windows:
        raise ValueError("moved_fraction_windows must not be empty")
    previous_stop = 0.0
    for start, stop in moved_fraction_windows:
        if not 0.0 <= start < stop <= 1.0:
            raise ValueError("moved fraction windows must be within [0, 1]")
        if start < previous_stop:
            raise ValueError("moved fraction windows must be ordered and disjoint")
        previous_stop = stop
    if direction not in ("both", "left", "right"):
        raise ValueError("direction must be both, left, or right")
    if sweep_order not in ("right_left", "left_right"):
        raise ValueError("sweep_order must be right_left or left_right")
    if rank_mode not in ("displacement", "net_bbox_delta"):
        raise ValueError("rank_mode must be displacement or net_bbox_delta")
    if max_net_bbox_delta_dbu is not None and rank_mode != "net_bbox_delta":
        raise ValueError(
            "max_net_bbox_delta_dbu requires rank_mode=net_bbox_delta"
        )
    rows = parse_rows(baseline_text)
    baseline_section, records = parse_components(
        baseline_text, macro_sizes, rows
    )
    _, candidate = parse_components(candidate_text, macro_sizes, rows)
    if set(records) != set(candidate):
        raise ValueError("baseline and candidate component sets differ")

    baseline_overlap_pairs = _overlap_pairs(records, rows)
    occupancy = {row_y: {} for row_y in rows}

    def covered_sites(record, x=None):
        x = record["x"] if x is None else x
        result = {}
        for row_y in record["rows"]:
            row = rows[row_y]
            start = (x - row["x"]) // row["site_width"]
            stop = (
                x + record["width"] - row["x"] + row["site_width"] - 1
            ) // row["site_width"]
            result[row_y] = range(start, stop)
        return result

    for record in records.values():
        if record["x"] is None:
            continue
        for row_y, sites in covered_sites(record).items():
            for site in sites:
                occupancy[row_y].setdefault(site, set()).add(record["name"])

    nets = None
    incident = None
    baseline_net_bbox_x_sum = None
    if rank_mode == "net_bbox_delta":
        nets, incident = parse_component_nets(baseline_text, records)
        baseline_net_bbox_x_sum = net_bbox_x_sum(records, nets)

    eligible = []
    skipped = {
        "fixed": 0,
        "unplaced": 0,
        "multirow": 0,
        "unchanged": 0,
        "net_bbox_guard": 0,
    }
    for name, record in records.items():
        target = candidate[name]
        if record["kind"] != "PLACED":
            skipped["fixed" if record["x"] is not None else "unplaced"] += 1
            continue
        if len(record["rows"]) != 1:
            skipped["multirow"] += 1
            continue
        delta = target["x"] - record["x"]
        if delta == 0:
            skipped["unchanged"] += 1
            continue
        if direction == "left" and delta > 0:
            continue
        if direction == "right" and delta < 0:
            continue
        record["target_x"] = target["x"]
        record["target_delta"] = delta
        if rank_mode == "net_bbox_delta":
            row = rows[record["rows"][0]]
            one_site_x = record["x"] + (
                row["site_width"] if delta > 0 else -row["site_width"]
            )
            record["net_bbox_delta_dbu"] = component_net_bbox_delta(
                record, one_site_x, records, nets, incident
            )
            if (
                max_net_bbox_delta_dbu is not None
                and record["net_bbox_delta_dbu"] > max_net_bbox_delta_dbu
            ):
                skipped["net_bbox_guard"] += 1
                continue
        eligible.append(record)

    if rank_mode == "net_bbox_delta":
        eligible.sort(key=lambda record: (
            record["net_bbox_delta_dbu"],
            -abs(record["target_delta"]),
            record["name"],
        ))
    else:
        eligible.sort(
            key=lambda record: (-abs(record["target_delta"]), record["name"])
        )
    selected = set()
    for start_fraction, stop_fraction in moved_fraction_windows:
        start = int(len(eligible) * start_fraction)
        limit = max(start + 1, int(len(eligible) * stop_fraction)) \
            if eligible else 0
        selected.update(record["name"] for record in eligible[start:limit])
    attempts = 0
    blocked = 0
    net_bbox_blocked = 0
    applied_moves = 0
    moved = set()

    def can_move(record, new_x):
        for row_y in record["rows"]:
            row = rows[row_y]
            if new_x < row["x"] or new_x + record["width"] > row["xh"]:
                return False
            if (new_x - row["x"]) % row["site_width"]:
                return False
            for site in covered_sites(record, new_x)[row_y]:
                if occupancy[row_y].get(site, set()) - {record["name"]}:
                    return False
        return True

    def apply_move(record, new_x):
        for row_y, sites in covered_sites(record).items():
            for site in sites:
                occupants = occupancy[row_y][site]
                occupants.discard(record["name"])
                if not occupants:
                    del occupancy[row_y][site]
        record["x"] = new_x
        for row_y, sites in covered_sites(record).items():
            for site in sites:
                occupancy[row_y].setdefault(site, set()).add(record["name"])

    for _ in range(max_steps):
        step_moves = 0
        move_directions = (
            (1, -1) if sweep_order == "right_left" else (-1, 1)
        )
        for move_direction in move_directions:
            candidates = [
                record for record in eligible
                if record["name"] in selected
                and (record["target_x"] - record["x"]) * move_direction > 0
            ]
            candidates.sort(
                key=lambda record: (record["x"], record["name"]),
                reverse=(move_direction > 0),
            )
            for record in candidates:
                row = rows[record["rows"][0]]
                new_x = record["x"] + move_direction * row["site_width"]
                if (new_x - record["target_x"]) * move_direction > 0:
                    continue
                attempts += 1
                if (
                    max_net_bbox_delta_dbu is not None
                    and component_net_bbox_delta(
                        record, new_x, records, nets, incident
                    ) > max_net_bbox_delta_dbu
                ):
                    blocked += 1
                    net_bbox_blocked += 1
                    continue
                if not can_move(record, new_x):
                    blocked += 1
                    continue
                apply_move(record, new_x)
                applied_moves += 1
                moved.add(record["name"])
                step_moves += 1
        if not step_moves:
            break

    output_overlap_pairs = _overlap_pairs(records, rows)
    if output_overlap_pairs - baseline_overlap_pairs:
        raise RuntimeError("whitespace projection introduced component overlaps")

    def replace_component(match):
        statement = match.group(1)
        header = COMPONENT_HEADER_RE.search(statement)
        record = records[header.group(1)]
        if record["x"] is None:
            return statement

        def replace_location(location):
            return "%s%d%s%d%s%s" % (
                location.group(1), record["x"], location.group(4),
                record["y"], location.group(6), record["orientation"],
            )

        return LOCATION_RE.sub(replace_location, statement, count=1)

    body = COMPONENT_RE.sub(replace_component, baseline_section.group(2))
    output = (
        baseline_text[:baseline_section.start(2)]
        + body
        + baseline_text[baseline_section.end(2):]
    )
    output_net_bbox_x_sum = (
        net_bbox_x_sum(records, nets) if nets is not None else None
    )
    if (
        max_net_bbox_delta_dbu is not None
        and output_net_bbox_x_sum - baseline_net_bbox_x_sum
        > applied_moves * max_net_bbox_delta_dbu
    ):
        raise RuntimeError("net-bbox guard failed to bound aggregate expansion")
    return output, {
        "operation": "route_directed_legal_whitespace_slide",
        "max_steps": int(max_steps),
        "min_moved_fraction": float(min_moved_fraction),
        "max_moved_fraction": float(max_moved_fraction),
        "moved_fraction_windows": [
            [float(start), float(stop)]
            for start, stop in moved_fraction_windows
        ],
        "direction": direction,
        "sweep_order": sweep_order,
        "rank_mode": rank_mode,
        "max_net_bbox_delta_dbu": max_net_bbox_delta_dbu,
        "net_count": len(nets) if nets is not None else None,
        "baseline_net_bbox_x_sum_dbu": baseline_net_bbox_x_sum,
        "output_net_bbox_x_sum_dbu": output_net_bbox_x_sum,
        "net_bbox_x_delta_dbu": (
            output_net_bbox_x_sum - baseline_net_bbox_x_sum
            if nets is not None else None
        ),
        "component_count": len(records),
        "eligible_components": len(eligible),
        "selected_components": len(selected),
        "moved_components": len(moved),
        "move_attempts": attempts,
        "applied_moves": applied_moves,
        "blocked_attempts": blocked,
        "net_bbox_blocked_attempts": net_bbox_blocked,
        "baseline_overlap_pairs": len(baseline_overlap_pairs),
        "output_overlap_pairs": len(output_overlap_pairs),
        "skipped": skipped,
    }


def refine_def(baseline_def, candidate_def, lef_inputs, output, max_steps=1,
               max_moved_fraction=1.0, min_moved_fraction=0.0,
               moved_fraction_windows=None,
               direction="both",
               sweep_order="right_left", rank_mode="displacement",
               max_net_bbox_delta_dbu=None, report_path=None):
    baseline_def = Path(baseline_def).resolve()
    candidate_def = Path(candidate_def).resolve()
    output = Path(output).resolve()
    if output in (baseline_def, candidate_def):
        raise ValueError("refinement output must differ from both input DEFs")
    baseline_text = baseline_def.read_text(errors="strict")
    units = UNITS_RE.search(baseline_text)
    if not units:
        raise ValueError("baseline DEF lacks distance units")
    dbu = int(units.group(1))
    macro_sizes = parse_macro_sizes(lef_inputs, dbu)
    refined, stats = legal_whitespace_slide(
        baseline_text, candidate_def.read_text(errors="strict"), macro_sizes,
        max_steps=max_steps, max_moved_fraction=max_moved_fraction,
        min_moved_fraction=min_moved_fraction,
        moved_fraction_windows=moved_fraction_windows,
        direction=direction, sweep_order=sweep_order,
        rank_mode=rank_mode,
        max_net_bbox_delta_dbu=max_net_bbox_delta_dbu,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(refined)
    report = {
        "schema_version": 2,
        "baseline_def": str(baseline_def),
        "candidate_def": str(candidate_def),
        "lef_inputs": [str(Path(path).resolve()) for path in lef_inputs],
        "lef_sha256": {
            str(Path(path).resolve()): file_sha256(path)
            for path in lef_inputs
        },
        "output_def": str(output),
        "dbu_per_micron": dbu,
        "baseline_sha256": file_sha256(baseline_def),
        "candidate_sha256": file_sha256(candidate_def),
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
    parser.add_argument("--baseline-def", type=Path, required=True)
    parser.add_argument("--candidate-def", type=Path, required=True)
    parser.add_argument("--lef-input", type=Path, action="append", required=True)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--max-moved-fraction", type=float, default=1.0)
    parser.add_argument("--min-moved-fraction", type=float, default=0.0)
    parser.add_argument(
        "--moved-fraction-window", action="append", default=[],
        help="ordered START:STOP rank window; repeat to compose disjoint batches",
    )
    parser.add_argument(
        "--direction", choices=("both", "left", "right"), default="both"
    )
    parser.add_argument(
        "--sweep-order", choices=("right_left", "left_right"),
        default="right_left",
    )
    parser.add_argument(
        "--rank-mode", choices=("displacement", "net_bbox_delta"),
        default="displacement",
    )
    parser.add_argument("--max-net-bbox-delta-dbu", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    windows = []
    for value in args.moved_fraction_window:
        fields = value.split(":")
        if len(fields) != 2:
            parser.error("--moved-fraction-window requires START:STOP")
        windows.append((float(fields[0]), float(fields[1])))
    refine_def(
        args.baseline_def, args.candidate_def, args.lef_input, args.output,
        max_steps=args.max_steps,
        max_moved_fraction=args.max_moved_fraction,
        min_moved_fraction=args.min_moved_fraction,
        moved_fraction_windows=windows or None,
        direction=args.direction,
        sweep_order=args.sweep_order,
        rank_mode=args.rank_mode,
        max_net_bbox_delta_dbu=args.max_net_bbox_delta_dbu,
        report_path=args.report,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
