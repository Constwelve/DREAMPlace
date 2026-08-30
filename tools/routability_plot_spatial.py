#!/usr/bin/env python3
"""Plot paired placement density and saved RUDY/GPUGR congestion maps."""

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np


DIEAREA_RE = re.compile(
    r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
    r"\(\s*(-?\d+)\s+(-?\d+)\s*\)",
    re.IGNORECASE,
)
LOCATION_RE = re.compile(
    r"\+\s+(?:PLACED|FIXED|COVER)\s*"
    r"\(\s*(-?\d+)\s+(-?\d+)\s*\)",
    re.IGNORECASE,
)
COMPONENT_NAME_RE = re.compile(r"^-\s+(\S+)")


def parse_def_components(path):
    """Return die bounds and component-name to placement-origin mapping."""
    diearea = None
    components = {}
    in_components = False
    record = ""
    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if diearea is None:
                match = DIEAREA_RE.search(line)
                if match:
                    diearea = tuple(int(value) for value in match.groups())
            stripped = line.strip()
            if not in_components:
                if stripped.upper().startswith("COMPONENTS "):
                    in_components = True
                continue
            if stripped.upper() == "END COMPONENTS":
                break
            if stripped.startswith("-"):
                record = stripped
            elif record:
                record += " " + stripped
            if record and ";" in stripped:
                name_match = COMPONENT_NAME_RE.search(record)
                location_match = LOCATION_RE.search(record)
                if name_match and location_match:
                    name = name_match.group(1)
                    if name in components:
                        raise ValueError("duplicate DEF component: %s" % name)
                    components[name] = (
                        int(location_match.group(1)), int(location_match.group(2))
                    )
                record = ""
    if diearea is None:
        raise ValueError("DEF has no DIEAREA: %s" % path)
    if not components:
        raise ValueError("DEF has no placed components: %s" % path)
    return diearea, components


def parse_def_locations(path):
    """Return die bounds and all component placement origins from a DEF."""
    diearea, components = parse_def_components(path)
    return diearea, np.asarray(list(components.values()), dtype=np.float64)


def load_proxy_maps(evaluation_dir):
    """Load the exact saved proxy arrays without rerunning an evaluator."""
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("PyTorch is required to load saved proxy tensors") from error
    root = Path(evaluation_dir)
    rudy = torch.load(root / "rudy_map.pt", map_location="cpu")
    gpugr = torch.load(root / "gpugr.pt", map_location="cpu")
    required = {"utilization_map", "hv_overflow_map"}
    if not isinstance(gpugr, dict) or not required <= set(gpugr):
        raise ValueError("GPUGR payload lacks utilization/HV overflow maps: %s" % root)
    hv = gpugr["hv_overflow_map"]
    if getattr(hv, "ndim", 0) != 3 or hv.shape[0] != 2:
        raise ValueError("GPUGR H/V overflow map must have shape (2, X, Y)")
    return {
        "RUDY utilization": rudy.detach().cpu().numpy(),
        "GPUGR utilization": gpugr["utilization_map"].detach().cpu().numpy(),
        "GPUGR H overflow": hv[0].detach().cpu().numpy(),
        "GPUGR V overflow": hv[1].detach().cpu().numpy(),
    }


def placement_density(def_path, bins):
    diearea, components = parse_def_components(def_path)
    locations = np.asarray(list(components.values()), dtype=np.float64)
    xl, yl, xh, yh = diearea
    density, _, _ = np.histogram2d(
        locations[:, 0], locations[:, 1], bins=bins,
        range=((xl, xh), (yl, yh)),
    )
    return np.log1p(density), diearea, components


def array_stats(values):
    return {
        "min": float(values.min()),
        "mean": float(values.mean()),
        "p99": float(np.percentile(values, 99)),
        "max": float(values.max()),
    }


def validate_pair(baseline, candidate, label):
    if baseline.shape != candidate.shape:
        raise ValueError(
            "%s map shape mismatch: %s vs %s"
            % (label, baseline.shape, candidate.shape)
        )


def show_map(ax, values, title, cmap, vmin=None, vmax=None, norm=None):
    image = ax.imshow(
        values.T, origin="lower", interpolation="nearest", aspect="auto",
        cmap=cmap, vmin=vmin, vmax=vmax, norm=norm,
    )
    ax.set_title(title, fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])
    return image


def plot_pair(args):
    baseline_density, baseline_die, baseline_components = placement_density(
        args.baseline_def, args.placement_bins
    )
    candidate_density, candidate_die, candidate_components = placement_density(
        args.candidate_def, args.placement_bins
    )
    if baseline_die != candidate_die:
        raise ValueError("baseline and candidate DEF DIEAREA values differ")
    if set(baseline_components) != set(candidate_components):
        raise ValueError("baseline and candidate DEF component sets differ")
    validate_pair(baseline_density, candidate_density, "placement density")
    names = sorted(baseline_components)
    baseline_xy = np.asarray([baseline_components[name] for name in names])
    candidate_xy = np.asarray([candidate_components[name] for name in names])
    displacement = np.linalg.norm(candidate_xy - baseline_xy, axis=1)

    baseline_maps = load_proxy_maps(args.baseline_eval)
    candidate_maps = load_proxy_maps(args.candidate_eval)
    rows = [("Placement density (log1p count)", baseline_density, candidate_density)]
    for label in (
        "RUDY utilization", "GPUGR utilization",
        "GPUGR H overflow", "GPUGR V overflow",
    ):
        validate_pair(baseline_maps[label], candidate_maps[label], label)
        rows.append((label, baseline_maps[label], candidate_maps[label]))

    fig, axes = plt.subplots(
        len(rows), 3, figsize=(11.8, 15.0), constrained_layout=True,
    )
    for row_index, (label, baseline, candidate) in enumerate(rows):
        low = float(min(baseline.min(), candidate.min()))
        high = float(max(baseline.max(), candidate.max()))
        if high == low:
            high = low + 1.0
        baseline_image = show_map(
            axes[row_index, 0], baseline, "%s: %s" % (args.baseline_label, label),
            "viridis", vmin=low, vmax=high,
        )
        show_map(
            axes[row_index, 1], candidate, "%s: %s" % (args.candidate_label, label),
            "viridis", vmin=low, vmax=high,
        )
        delta = candidate - baseline
        extent = float(np.max(np.abs(delta)))
        if extent > 0:
            delta_norm = TwoSlopeNorm(vmin=-extent, vcenter=0.0, vmax=extent)
            delta_image = show_map(
                axes[row_index, 2], delta, "Candidate - baseline", "RdBu_r",
                norm=delta_norm,
            )
        else:
            delta_image = show_map(
                axes[row_index, 2], delta, "Candidate - baseline", "RdBu_r",
                vmin=-1.0, vmax=1.0,
            )
        fig.colorbar(baseline_image, ax=axes[row_index, :2], shrink=0.82)
        fig.colorbar(delta_image, ax=axes[row_index, 2], shrink=0.82)
    fig.suptitle(
        "%s vs %s | %d matched components | displacement p95 %.1f DBU"
        % (
            args.candidate_label, args.baseline_label, len(names),
            float(np.percentile(displacement, 95)),
        ),
        fontsize=13,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=180)
    plt.close(fig)
    sidecar = args.output.with_suffix(".json")
    sidecar.write_text(json.dumps({
        "baseline_def": str(args.baseline_def.resolve()),
        "candidate_def": str(args.candidate_def.resolve()),
        "baseline_evaluation": str(args.baseline_eval.resolve()),
        "candidate_evaluation": str(args.candidate_eval.resolve()),
        "diearea_dbu": list(baseline_die),
        "matched_components": len(names),
        "displacement_dbu": {
            "mean": float(displacement.mean()),
            "median": float(np.median(displacement)),
            "p95": float(np.percentile(displacement, 95)),
            "p99": float(np.percentile(displacement, 99)),
            "max": float(displacement.max()),
            "moved_components": int(np.count_nonzero(displacement)),
        },
        "maps": {
            label: {
                "baseline": array_stats(baseline),
                "candidate": array_stats(candidate),
                "delta": array_stats(candidate - baseline),
            }
            for label, baseline, candidate in rows
        },
    }, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-def", type=Path, required=True)
    parser.add_argument("--candidate-def", type=Path, required=True)
    parser.add_argument("--baseline-eval", type=Path, required=True)
    parser.add_argument("--candidate-eval", type=Path, required=True)
    parser.add_argument("--baseline-label", default="HPWL")
    parser.add_argument("--candidate-label", required=True)
    parser.add_argument("--placement-bins", type=int, default=256)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.placement_bins < 2:
        raise ValueError("placement-bins must be at least 2")
    plot_pair(args)
    print("Wrote %s" % args.output)


if __name__ == "__main__":
    main()
