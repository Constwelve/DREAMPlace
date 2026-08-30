#!/usr/bin/env python3
"""Blend a candidate DEF displacement with its same-seed HPWL baseline."""

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re


COMPONENTS_RE = re.compile(
    r"(^\s*COMPONENTS\s+\d+\s*;\s*$)(.*?)(^\s*END\s+COMPONENTS\s*$)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
COMPONENT_RE = re.compile(
    r"(^\s*-\s+(\S+)\b.*?;)",
    re.MULTILINE | re.DOTALL,
)
LOCATION_RE = re.compile(
    r"(\+\s*(PLACED|FIXED|COVER)\s*\(\s*)"
    r"([-+]?\d+)(\s+)([-+]?\d+)(\s*\)\s+)(\S+)",
    re.IGNORECASE,
)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _component_index(text):
    section = COMPONENTS_RE.search(text)
    if not section:
        raise ValueError("DEF lacks a COMPONENTS section")
    result = {}
    for match in COMPONENT_RE.finditer(section.group(2)):
        name = match.group(2)
        if name in result:
            raise ValueError("duplicate DEF component %s" % name)
        location = LOCATION_RE.search(match.group(1))
        if location:
            placement = {
                "kind": location.group(2).upper(),
                "x": int(location.group(3)),
                "y": int(location.group(5)),
                "orientation": location.group(7).upper(),
            }
        else:
            placement = None
        result[name] = placement
    if not result:
        raise ValueError("DEF COMPONENTS section is empty")
    return section, result


def _rounded_coordinate(value):
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _snap_coordinate(value, grid):
    if grid <= 0:
        raise ValueError("grid_dbu must be positive")
    sign = -1 if value < 0 else 1
    magnitude = abs(value)
    return sign * (((magnitude + grid // 2) // grid) * grid)


def blend_components(baseline_text, candidate_text, alpha, grid_dbu=1,
                     orientation_policy="require_same", axis="xy"):
    alpha = Decimal(str(alpha))
    if alpha < 0 or alpha > 1:
        raise ValueError("alpha must be in [0, 1]")
    if orientation_policy not in ("require_same", "baseline"):
        raise ValueError("unsupported orientation policy: %s" % orientation_policy)
    if axis not in ("x", "y", "xy"):
        raise ValueError("axis must be x, y, or xy")
    baseline_section, baseline = _component_index(baseline_text)
    _, candidate = _component_index(candidate_text)
    if set(baseline) != set(candidate):
        missing = sorted(set(baseline) - set(candidate))
        extra = sorted(set(candidate) - set(baseline))
        raise ValueError(
            "DEF component mismatch: missing=%s extra=%s" % (missing, extra)
        )

    moved_components = 0
    changed_coordinates = 0
    max_candidate_displacement = 0
    max_applied_displacement = 0
    orientation_mismatches = set()

    def replace_component(match):
        nonlocal moved_components, changed_coordinates
        nonlocal max_candidate_displacement, max_applied_displacement
        name = match.group(2)
        base = baseline[name]
        cand = candidate[name]
        if (base is None) != (cand is None):
            raise ValueError("component %s placement presence differs" % name)
        if base is None:
            return match.group(1)
        if base["kind"] != cand["kind"]:
            raise ValueError(
                "component %s kind differs: %s != %s"
                % (name, base["kind"], cand["kind"])
            )
        if base["orientation"] != cand["orientation"]:
            orientation_mismatches.add(name)
            if orientation_policy == "require_same":
                raise ValueError(
                    "component %s orientation differs: %s != %s"
                    % (name, base["orientation"], cand["orientation"])
                )
        if base["kind"] != "PLACED":
            if (base["x"], base["y"]) != (cand["x"], cand["y"]):
                raise ValueError("fixed component %s location differs" % name)
            return match.group(1)

        x = base["x"]
        y = base["y"]
        if "x" in axis:
            x = _rounded_coordinate(
                Decimal(base["x"])
                + alpha * Decimal(cand["x"] - base["x"])
            )
        if "y" in axis:
            y = _rounded_coordinate(
                Decimal(base["y"])
                + alpha * Decimal(cand["y"] - base["y"])
            )
        x = _snap_coordinate(x, int(grid_dbu))
        y = _snap_coordinate(y, int(grid_dbu))
        candidate_displacement = max(
            abs(cand["x"] - base["x"]), abs(cand["y"] - base["y"])
        )
        applied_displacement = max(abs(x - base["x"]), abs(y - base["y"]))
        max_candidate_displacement = max(
            max_candidate_displacement, candidate_displacement
        )
        max_applied_displacement = max(
            max_applied_displacement, applied_displacement
        )
        if x != base["x"] or y != base["y"]:
            moved_components += 1
            changed_coordinates += int(x != base["x"]) + int(y != base["y"])

        def replace_location(location):
            return "%s%d%s%d%s%s" % (
                location.group(1), x, location.group(4), y,
                location.group(6), location.group(7),
            )

        return LOCATION_RE.sub(replace_location, match.group(1), count=1)

    body = COMPONENT_RE.sub(replace_component, baseline_section.group(2))
    output = (
        baseline_text[:baseline_section.start(2)]
        + body
        + baseline_text[baseline_section.end(2):]
    )
    return output, {
        "alpha": float(alpha),
        "component_count": len(baseline),
        "moved_components": moved_components,
        "changed_coordinates": changed_coordinates,
        "max_candidate_displacement_dbu": max_candidate_displacement,
        "max_applied_displacement_dbu": max_applied_displacement,
        "grid_dbu": int(grid_dbu),
        "axis": axis,
        "orientation_policy": orientation_policy,
        "orientation_mismatch_count": len(orientation_mismatches),
        "orientation_mismatch_examples": sorted(orientation_mismatches)[:20],
    }


def blend_def(baseline_def, candidate_def, output, alpha, grid_dbu=1,
              report_path=None, orientation_policy="require_same", axis="xy"):
    baseline_def = Path(baseline_def).resolve()
    candidate_def = Path(candidate_def).resolve()
    output = Path(output).resolve()
    if output in (baseline_def, candidate_def):
        raise ValueError("blend output must differ from both input DEFs")
    baseline_text = baseline_def.read_text(errors="strict")
    candidate_text = candidate_def.read_text(errors="strict")
    blended, stats = blend_components(
        baseline_text, candidate_text, alpha, grid_dbu, orientation_policy, axis
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(blended)
    report = {
        "schema_version": 1,
        "operation": "baseline_anchored_component_displacement_blend",
        "baseline_def": str(baseline_def),
        "candidate_def": str(candidate_def),
        "output_def": str(output),
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
    parser.add_argument("--alpha", type=Decimal, required=True)
    parser.add_argument("--grid-dbu", type=int, default=1)
    parser.add_argument(
        "--orientation-policy", choices=("require_same", "baseline"),
        default="require_same",
        help="fail on orientation changes or preserve baseline orientations",
    )
    parser.add_argument(
        "--axis", choices=("x", "y", "xy"), default="xy",
        help="blend x, y, or both movable-component coordinates",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    blend_def(
        args.baseline_def, args.candidate_def, args.output, args.alpha,
        args.grid_dbu, args.report, args.orientation_policy, args.axis,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
