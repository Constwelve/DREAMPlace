#!/usr/bin/env python3
"""Generate RUPlace report figures from retained compact evidence.

The input can be either the extracted cleanup evidence tree or the local
``compact_evidence.tar.gz`` archive.  All plotted values are paired against
the HPWL placement from the same design and seed.  Router backends are kept
in separate panels and are never combined into a score.
"""

import argparse
import json
import tarfile
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np


DEFAULT_EXTRACTED = Path(
    "/mnt/nvme2n1/yifan/ruplace-report-evidence-20260801-3583ba6"
)
DEFAULT_ARCHIVE = Path(
    "/mnt/nvme2n1/yifan/ruplace-local-cleanup-archive/"
    "20260801_stop_cleanup_3583ba6/compact_evidence.tar.gz"
)


class EvidenceStore:
    """Read named evidence files from a directory tree or tar archive."""

    def __init__(self, root=None, archive=None):
        self.root = Path(root) if root else None
        self.archive_path = Path(archive) if archive else None
        self.archive = None
        self.paths = {}
        if self.root:
            self.paths = {
                path.relative_to(self.root).as_posix(): path
                for path in self.root.rglob("*")
                if path.is_file()
            }
        else:
            self.archive = tarfile.open(self.archive_path, "r:gz")
            self.paths = {
                member.name: member
                for member in self.archive.getmembers()
                if member.isfile()
            }

    def close(self):
        if self.archive:
            self.archive.close()

    def read_text(self, name):
        entry = self.paths[name]
        if self.root:
            return entry.read_text(encoding="utf-8", errors="replace")
        stream = self.archive.extractfile(entry)
        if stream is None:
            raise OSError("cannot read archive member %s" % name)
        return stream.read().decode("utf-8", errors="replace")

    def find_all(self, marker, basename):
        suffix = "/" + basename
        return sorted(
            name for name in self.paths
            if marker in name and (name == basename or name.endswith(suffix))
        )

    def find_one(self, marker, basename):
        matches = self.find_all(marker, basename)
        if not matches:
            raise FileNotFoundError("missing %s below %s" % (basename, marker))
        if len(matches) == 1:
            return matches[0]
        local = [name for name in matches if name.startswith("local/")]
        if len(local) == 1:
            return local[0]
        raise RuntimeError("ambiguous evidence match: %s" % matches)

    def load_json(self, marker, basename):
        return json.loads(self.read_text(self.find_one(marker, basename)))


def percent_delta(value, baseline):
    if baseline == 0:
        return None
    return 100.0 * (value / baseline - 1.0)


def parse_key_value(text):
    result = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def selection_candidate(store, marker, filename, method_marker):
    selection = store.load_json(marker, filename)
    candidates = selection.get("excluded", []) + selection.get("qualified", [])
    matches = [item for item in candidates if method_marker in item["method"]]
    if len(matches) != 1:
        raise RuntimeError(
            "expected one %s candidate in %s, found %d"
            % (method_marker, marker, len(matches))
        )
    return matches[0]


def metric_value(candidate, key, statistic="mean_delta_pct"):
    return float(candidate["metrics"][key][statistic])


def annotate_heatmap(ax, data, fontsize=7):
    for row in range(data.shape[0]):
        for col in range(data.shape[1]):
            value = data[row, col]
            ax.text(
                col,
                row,
                "%+.2f" % value,
                ha="center",
                va="center",
                fontsize=fontsize,
                color="black",
            )


def plot_proxy_near_misses(store, output_dir, figure_data):
    specs = [
        (
            "V98 cap 8",
            "ruplace-terminal-audits/v98_20260801T0405Z",
            "strict_selection_v3.json",
            "quarter_cap8",
        ),
        (
            "V100 bal. 0.90625",
            "ruplace-terminal-audits/v100_terminal_20260801T0605Z",
            "strict_selection_absolute_directional_v3_regenerated.json",
            "balance0p90625",
        ),
        (
            "V102 bal. 1.015625",
            "ruplace-partial-audits/v102_two_candidate_20260801T0641Z",
            "strict_selection_absolute_directional_v3.json",
            "balance1p015625",
        ),
        (
            "V103 bal. 0.75",
            "ruplace-terminal-audits/v103_terminal_20260801T0615Z",
            "strict_selection_absolute_directional_v3_regenerated.json",
            "balance0p75_control",
        ),
    ]
    metrics = [
        ("gpugr:gr_wirelength", "GR WL"),
        ("gpugr:est_shorts", "Est. shorts"),
        ("gpugr:num_ovfl_nets", "Ovfl nets"),
        ("gpugr:overflow_sum", "Ovfl sum"),
        ("gpugr:utilization_p99", "Util. p99"),
        ("gpugr:utilization_max", "Util. max"),
        ("gpugr:horizontal_overflow_sum", "H ovfl"),
        ("gpugr:vertical_overflow_sum", "V ovfl"),
        ("gpugr:horizontal_utilization_max", "H max"),
        ("gpugr:vertical_utilization_max", "V max"),
        ("rudy:overflow_sum", "RUDY ovfl"),
        ("rudy:utilization_p99", "RUDY p99"),
    ]
    candidates = [
        selection_candidate(store, marker, filename, method_marker)
        for _, marker, filename, method_marker in specs
    ]
    means = np.asarray([
        [metric_value(candidate, key) for key, _ in metrics]
        for candidate in candidates
    ])
    worst = np.asarray([
        [metric_value(candidate, key, "worst_delta_pct") for key, _ in metrics]
        for candidate in candidates
    ])

    fig, axes = plt.subplots(2, 1, figsize=(12.5, 5.8), constrained_layout=True)
    labels = [label for label, _, _, _ in specs]
    metric_labels = [label for _, label in metrics]
    for ax, values, title, limit in [
        (axes[0], means, "Mean paired delta", 10.0),
        (axes[1], worst, "Worst paired delta used by strict veto", 5.0),
    ]:
        shown = np.clip(values, -limit, limit)
        image = ax.imshow(
            shown,
            aspect="auto",
            cmap="RdYlGn_r",
            norm=TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit),
        )
        annotate_heatmap(ax, values)
        ax.set_yticks(range(len(labels)), labels)
        ax.set_xticks(range(len(metric_labels)), metric_labels, rotation=35, ha="right")
        ax.set_title("%s (%%, lower is better; color clipped at +/-%.0f%%)" % (title, limit))
        fig.colorbar(image, ax=ax, shrink=0.82, label="Delta vs same-case HPWL (%)")
    path = output_dir / "proxy_near_miss_heatmaps.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    figure_data["proxy_near_misses"] = {
        label: {
            "method": candidate["method"],
            "mean_delta_pct": {
                metric_label: float(value)
                for (_, metric_label), value in zip(metrics, row_mean)
            },
            "worst_delta_pct": {
                metric_label: float(value)
                for (_, metric_label), value in zip(metrics, row_worst)
            },
        }
        for (label, _, _, _), candidate, row_mean, row_worst
        in zip(specs, candidates, means, worst)
    }


def plot_tuning_instability(store, output_dir, figure_data):
    v104 = store.load_json(
        "ruplace-partial-audits/v104_two_candidate_20260801T0638Z",
        "strict_selection_absolute_directional_v3.json",
    )["excluded"]
    v106 = store.load_json(
        "ruplace-partial-audits/v106_three_candidate_20260801T0637Z",
        "strict_selection_absolute_directional_v3.json",
    )["excluded"]
    series = [
        ("V104 cap 3", next(x for x in v104 if "quarter_cap3" in x["method"])),
        ("V104 cap 4", next(x for x in v104 if "quarter_cap4" in x["method"])),
        ("V106 tail 0", next(x for x in v106 if x["method"].endswith("q99_tail0"))),
        ("V106 tail 0.25", next(x for x in v106 if "q99_tail0p25" in x["method"])),
        ("V106 tail 0.5", next(x for x in v106 if "q99_tail0p5" in x["method"])),
    ]
    metrics = [
        ("gpugr:gr_wirelength", "GR WL"),
        ("gpugr:est_shorts", "Est. shorts"),
        ("gpugr:overflow_sum", "Ovfl sum"),
        ("gpugr:horizontal_overflow_sum", "H ovfl"),
        ("gpugr:vertical_overflow_sum", "V ovfl"),
        ("gpugr:utilization_max", "Util. max"),
    ]
    values = np.asarray([
        [metric_value(candidate, key) for key, _ in metrics]
        for _, candidate in series
    ])
    fig, ax = plt.subplots(figsize=(10.5, 4.5), constrained_layout=True)
    x = np.arange(len(series))
    for index, (_, label) in enumerate(metrics):
        ax.plot(x, values[:, index], marker="o", linewidth=1.5, label=label)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_xticks(x, [label for label, _ in series], rotation=20, ha="right")
    ax.set_ylabel("Mean paired delta vs HPWL (%)")
    ax.set_title("Adjacent parameter settings produce non-monotonic router response")
    ax.set_yscale("symlog", linthresh=1.0)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(ncol=3, fontsize=8)
    path = output_dir / "proxy_tuning_instability.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    figure_data["tuning_instability"] = {
        label: {metric_label: float(value) for (_, metric_label), value in zip(metrics, row)}
        for (label, _), row in zip(series, values)
    }


METHOD_LABELS = {
    "weak_atomic_dev_0002_rudy_local_gradient": "Local gradient",
    "weak_atomic_dev_0006_rudy_net_overlap": "Net overlap",
    "weak_atomic_dev_0013_rudy_net_weighting": "Net weighting",
    "survivor_pair_0003_rudy_net_weighting__local_gradient": "Weighting + local",
    "weak_atomic_dev_0022_rudy_poisson_force": "Weak Poisson",
}


def method_label(name):
    return METHOD_LABELS.get(name, name)


def openroad_rows(store):
    marker = "ispd2019_routability_first_unified_3583ba6/golden_openroad_detailed_3583ba6"
    rows = {}
    for name in store.find_all(marker, "openroad_metrics.json"):
        if "/congestion_backfill/" in name:
            continue
        parts = name.split("/")
        marker_index = next(i for i, part in enumerate(parts) if part == "golden_openroad_detailed_3583ba6")
        case = parts[marker_index + 1]
        seed = next(part for part in parts[marker_index + 2:] if part.startswith("seed_"))
        method = parts[parts.index("methods", marker_index) + 1]
        rows[(case, seed, method)] = json.loads(store.read_text(name))
    return rows


def innovus_rows(store, marker):
    """Load authoritative Innovus metrics from evaluator summaries.

    The compact ``innovus_metrics.txt`` artifact contains only the values
    emitted directly by Tcl.  ``summary.json`` also retains metrics derived
    from the DRC and connectivity reports, so it is the complete structured
    source for comparisons.
    """
    rows = {}
    for name in store.find_all(marker, "summary.json"):
        parts = name.split("/")
        marker_part = marker.rstrip("/").split("/")[-1]
        marker_index = parts.index(marker_part)
        case = parts[marker_index + 1]
        seed = next(part for part in parts[marker_index + 2:] if part.startswith("seed_"))
        method = parts[parts.index("methods", marker_index) + 1]
        summary = json.loads(store.read_text(name))
        results = [
            result for result in summary.get("results", [])
            if result.get("backend") == "innovus" and result.get("status") == "ok"
        ]
        if not results:
            continue
        if len(results) != 1:
            raise RuntimeError(
                "expected one successful Innovus result in %s, found %d"
                % (name, len(results))
            )
        rows[(case, seed, method)] = results[0]["metrics"]
    return rows


def paired_router_values(rows, value_key, cast=float):
    result = defaultdict(list)
    for (case, seed, method), data in rows.items():
        if method == "hpwl" or (case, seed, "hpwl") not in rows:
            continue
        baseline = rows[(case, seed, "hpwl")]
        value = cast(data[value_key])
        base_value = cast(baseline[value_key])
        result[method].append({
            "case": case,
            "seed": seed,
            "value": value,
            "baseline": base_value,
            "delta": value - base_value,
            "delta_pct": percent_delta(value, base_value),
        })
    return result


def distribution_summary(entries):
    percentages = [entry["delta_pct"] for entry in entries if entry["delta_pct"] is not None]
    deltas = [entry["delta"] for entry in entries]
    return {
        "comparisons": len(entries),
        "mean_delta_pct": float(np.mean(percentages)) if percentages else None,
        "median_delta_pct": float(np.median(percentages)) if percentages else None,
        "best_delta_pct": float(np.min(percentages)) if percentages else None,
        "worst_delta_pct": float(np.max(percentages)) if percentages else None,
        "wins": sum(delta < 0 for delta in deltas),
        "ties": sum(delta == 0 for delta in deltas),
        "losses": sum(delta > 0 for delta in deltas),
        "mean_absolute_delta": float(np.mean(deltas)) if deltas else None,
    }


def add_boxplot(ax, values, labels, title, ylabel):
    positions = np.arange(1, len(values) + 1)
    ax.boxplot(values, positions=positions, widths=0.55, showfliers=False)
    for index, points in enumerate(values, start=1):
        offsets = np.linspace(-0.12, 0.12, len(points)) if len(points) > 1 else [0.0]
        ax.scatter(index + offsets, points, s=18, alpha=0.75, zorder=3)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_xticks(positions, labels, rotation=25, ha="right")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.22)


def plot_golden_results(store, output_dir, figure_data):
    openroad = openroad_rows(store)
    openroad_wl = paired_router_values(openroad, "route__wirelength")
    openroad_drc = paired_router_values(openroad, "route__drc_errors")

    current_innovus = innovus_rows(
        store,
        "real_5designs_3seeds_routability_first_3583ba6/golden_innovus_detailed_3583ba6",
    )
    current_innovus_wl = paired_router_values(current_innovus, "wirelength")
    current_innovus_metrics = {
        key: paired_router_values(current_innovus, key)
        for key in (
            "wirelength", "horizontal_congestion", "vertical_congestion",
            "drc_violations", "short_violations", "vias",
        )
    }

    historical_innovus = innovus_rows(
        store,
        "real_5designs_3seeds_85603d6/golden_innovus_snapped_4589107",
    )
    historical_wl = paired_router_values(historical_innovus, "wirelength")

    order = [name for name in METHOD_LABELS if name in openroad_wl]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.7), constrained_layout=True)
    add_boxplot(
        axes[0],
        [[entry["delta_pct"] for entry in openroad_wl[name]] for name in order],
        [method_label(name) for name in order],
        "OpenROAD detailed routing: 44/45 routes retained",
        "Routed wirelength delta vs HPWL (%)",
    )
    current_order = [name for name in METHOD_LABELS if name in current_innovus_wl]
    add_boxplot(
        axes[1],
        [[entry["delta_pct"] for entry in current_innovus_wl[name]] for name in current_order],
        [method_label(name) for name in current_order],
        "Innovus detailed routing: partial 4-design campaign",
        "Routed wirelength delta vs HPWL (%)",
    )
    path = output_dir / "golden_routed_wirelength.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.8, 4.7), constrained_layout=True)
    drc_order = [name for name in order if name in openroad_drc]
    add_boxplot(
        ax,
        [[entry["delta"] for entry in openroad_drc[name]] for name in drc_order],
        [method_label(name) for name in drc_order],
        "OpenROAD final DRC delta (paired by design and seed)",
        "Final DRC count delta vs HPWL",
    )
    ax.set_yscale("symlog", linthresh=100.0)
    path = output_dir / "openroad_final_drc.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)

    metric_specs = [
        ("wirelength", "Routed WL"),
        ("horizontal_congestion", "H congestion"),
        ("vertical_congestion", "V congestion"),
        ("drc_violations", "DRC"),
        ("short_violations", "Shorts"),
        ("vias", "Vias"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(14.5, 8.0), constrained_layout=True)
    for ax, (metric, label) in zip(axes.flat, metric_specs):
        values_by_method = current_innovus_metrics[metric]
        metric_order = [name for name in current_order if name in values_by_method]
        add_boxplot(
            ax,
            [
                [entry["delta_pct"] for entry in values_by_method[name]]
                for name in metric_order
            ],
            [method_label(name) for name in metric_order],
            label,
            "Delta vs same-case HPWL (%)",
        )
    fig.suptitle(
        "Innovus detailed routing: 4 designs x 3 seeds (lower is better)",
        fontsize=13,
    )
    path = output_dir / "innovus_detailed_metrics.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)

    poisson_methods = list(historical_wl)
    if len(poisson_methods) != 1:
        raise RuntimeError("expected one historical Innovus candidate")
    poisson_entries = sorted(
        historical_wl[poisson_methods[0]], key=lambda item: (item["case"], item["seed"])
    )
    case_names = []
    for entry in poisson_entries:
        short_case = entry["case"].replace("taiwei_nangate45_", "").replace("_materialized2d", "")
        case_names.append("%s\n%s" % (short_case, entry["seed"].replace("seed_", "s")))
    values = [entry["delta_pct"] for entry in poisson_entries]
    fig, ax = plt.subplots(figsize=(12.0, 4.5), constrained_layout=True)
    ax.bar(range(len(values)), values, color="#c44e52")
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_xticks(range(len(values)), case_names, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Routed wirelength delta vs HPWL (%)")
    ax.set_title("Completed Innovus replay: weak Poisson lost all 15 comparisons")
    ax.grid(axis="y", alpha=0.22)
    path = output_dir / "historical_poisson_innovus_wirelength.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)

    figure_data["openroad_detailed"] = {
        "retained_routes": len(openroad),
        "wirelength": {
            method_label(name): distribution_summary(entries)
            for name, entries in openroad_wl.items()
        },
        "final_drc": {
            method_label(name): distribution_summary(entries)
            for name, entries in openroad_drc.items()
        },
    }
    figure_data["innovus_detailed_partial"] = {
        "retained_routes": len(current_innovus),
        "designs": sorted({key[0] for key in current_innovus}),
        "metrics": {
            metric: {
                method_label(name): distribution_summary(entries)
                for name, entries in values_by_method.items()
            }
            for metric, values_by_method in current_innovus_metrics.items()
        },
    }
    figure_data["innovus_historical_poisson"] = {
        "retained_routes": len(historical_innovus),
        "wirelength": {
            method_label(name): distribution_summary(entries)
            for name, entries in historical_wl.items()
        },
        "comparisons": poisson_entries,
    }


def resolve_input(args):
    if args.evidence_root:
        return {"root": args.evidence_root}
    if args.archive:
        return {"archive": args.archive}
    if DEFAULT_EXTRACTED.exists():
        return {"root": DEFAULT_EXTRACTED}
    if DEFAULT_ARCHIVE.exists():
        return {"archive": DEFAULT_ARCHIVE}
    raise FileNotFoundError("pass --evidence-root or --archive")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, help="Extracted cleanup evidence root")
    parser.add_argument("--archive", type=Path, help="Local compact_evidence.tar.gz")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/images/routability_report"),
        help="Figure and derived-data output directory",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    input_spec = resolve_input(args)
    store = EvidenceStore(**input_spec)
    figure_data = {"input": {key: str(value) for key, value in input_spec.items()}}
    try:
        plot_proxy_near_misses(store, args.output_dir, figure_data)
        plot_tuning_instability(store, args.output_dir, figure_data)
        plot_golden_results(store, args.output_dir, figure_data)
    finally:
        store.close()

    data_path = args.output_dir / "figure_data.json"
    data_path.write_text(json.dumps(figure_data, indent=2, sort_keys=True) + "\n")
    print("Wrote %s" % data_path)


if __name__ == "__main__":
    main()
