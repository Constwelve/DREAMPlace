#!/usr/bin/env python3
"""Generate the adaptive RUPlace s14 layout visualization report."""

import argparse
import csv
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import TwoSlopeNorm
import numpy as np


WORKTREE = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKTREE.parents[1]
LEGACY_GENERATOR = REPO_ROOT / "reports/ruplace_s14_final/generate_s14_report.py"


def load_layout_helpers():
    spec = importlib.util.spec_from_file_location("ruplace_s14_layout_helpers", LEGACY_GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = load_layout_helpers()


@dataclass(frozen=True)
class MethodArtifact:
    method: str
    label: str
    def_path: Path
    metrics_path: Path


@dataclass(frozen=True)
class CaseArtifact:
    name: str
    label: str
    seed1001: tuple[MethodArtifact, ...]
    seed1002_metrics: tuple[tuple[str, Path], ...]
    inflation_status: Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quality_def(run_id: str, method: str, case: str, design: str) -> Path:
    return (
        WORKTREE / "results/ruplace_quality" / run_id / "dreamplace" / method / case /
        "results" / design / (design + ".gp.def")
    )


def innovus_metrics(run_id: str, method: str) -> Path:
    return WORKTREE / "results/s14_innovus" / (run_id + "_" + method) / "innovus.json"


def case_artifacts() -> tuple[CaseArtifact, ...]:
    nvdla_run1 = "s14_nvdla_s_s14_v121_adaptive_medium_s1001"
    nvdla_run2 = "s14_nvdla_s_s14_v121_adaptive_medium_s1002"
    reg_base1 = "s14_regression_s14_v121_adaptive_medium_s1001"
    reg_base2 = "s14_regression_s14_v121_adaptive_medium_s1002"
    reg_ru1 = "s14_regression_s14_v123_admmfix_s1001"
    reg_ru2 = "s14_regression_s14_v123_admmfix_s1002"
    nvdla_design = "NV_nvdla_s.fixedmacro"
    reg_design = "ct_top.fixedmacro"
    return (
        CaseArtifact(
            name="nvdla_s_s14",
            label="nvdla_s (269k instances)",
            seed1001=tuple(
                MethodArtifact(
                    method=method,
                    label=label,
                    def_path=quality_def(nvdla_run1, method, "nvdla_s_s14", nvdla_design),
                    metrics_path=innovus_metrics(nvdla_run1, method),
                )
                for method, label in (
                    ("dp_hpwl", "DREAMPlace HPWL"),
                    ("dp_rudy", "DREAMPlace RUDY"),
                    ("ruplace", "RUPlace adaptive"),
                )
            ),
            seed1002_metrics=tuple(
                (method, innovus_metrics(nvdla_run2, method))
                for method in ("dp_hpwl", "dp_rudy", "ruplace")
            ),
            inflation_status=(
                quality_def(nvdla_run1, "ruplace", "nvdla_s_s14", nvdla_design).parent /
                "ruplace_inflation_status.json"
            ),
        ),
        CaseArtifact(
            name="regression_s14",
            label="regression_s14 (735k instances)",
            seed1001=(
                MethodArtifact(
                    "dp_hpwl", "DREAMPlace HPWL",
                    quality_def(reg_base1, "dp_hpwl", "regression_s14", reg_design),
                    innovus_metrics(reg_base1, "dp_hpwl"),
                ),
                MethodArtifact(
                    "dp_rudy", "DREAMPlace RUDY",
                    quality_def(reg_base1, "dp_rudy", "regression_s14", reg_design),
                    innovus_metrics(reg_base1, "dp_rudy"),
                ),
                MethodArtifact(
                    "ruplace", "RUPlace adaptive",
                    quality_def(reg_ru1, "ruplace", "regression_s14", reg_design),
                    innovus_metrics(reg_ru1, "ruplace"),
                ),
            ),
            seed1002_metrics=(
                ("dp_hpwl", innovus_metrics(reg_base2, "dp_hpwl")),
                ("dp_rudy", innovus_metrics(reg_base2, "dp_rudy")),
                ("ruplace", innovus_metrics(reg_ru2, "ruplace")),
            ),
            inflation_status=(
                quality_def(reg_ru1, "ruplace", "regression_s14", reg_design).parent /
                "ruplace_inflation_status.json"
            ),
        ),
    )


def load_metrics(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if payload.get("status") != "ok":
        raise RuntimeError("non-ok Innovus result: %s" % path)
    return payload["metrics"]


def validate_inputs(cases: tuple[CaseArtifact, ...]) -> None:
    missing = []
    for case in cases:
        for artifact in case.seed1001:
            for path in (artifact.def_path, artifact.metrics_path):
                if not path.is_file():
                    missing.append(path)
        for _, path in case.seed1002_metrics:
            if not path.is_file():
                missing.append(path)
        if not case.inflation_status.is_file():
            missing.append(case.inflation_status)
    if missing:
        raise FileNotFoundError("missing report inputs:\n" + "\n".join(map(str, missing)))


def delta_pct(value: float, baseline: float) -> float:
    return 100.0 * (value / baseline - 1.0)


def plot_layout(case: CaseArtifact, layouts: dict, metrics: dict, output: Path):
    methods = [artifact.method for artifact in case.seed1001]
    densities = [layouts[method]["density"] for method in methods]
    baseline = densities[0]
    delta = densities[-1] - baseline
    vmax = HELPERS.positive_percentile(np.concatenate([grid.ravel() for grid in densities]), 99.5, 0.01)
    dmax = HELPERS.positive_percentile(np.abs(delta), 99.5, 0.01)
    lx, ly, hx, hy = layouts[methods[0]]["die"]
    units = layouts[methods[0]]["units"]
    extent = [lx / units, hx / units, ly / units, hy / units]

    fig, axes = plt.subplots(1, 4, figsize=(16.0, 4.45), constrained_layout=True)
    image = None
    for index, artifact in enumerate(case.seed1001):
        ax = axes[index]
        image = ax.imshow(
            layouts[artifact.method]["density"], origin="lower", extent=extent,
            cmap="viridis", vmin=0, vmax=vmax, interpolation="nearest", aspect="equal",
        )
        HELPERS.draw_macros(ax, layouts[artifact.method]["macros"], units, "white")
        current = metrics[artifact.method]
        ax.set_title(
            "%s\nrWL %.3fM | EGR %.2f%% / %.2f%%" % (
                artifact.label, current["wirelength"] / 1e6,
                current["egr_horizontal_congestion"], current["egr_vertical_congestion"],
            ),
            fontsize=9,
        )
        ax.set_xlabel("X (um)")
        if index == 0:
            ax.set_ylabel("Y (um)")

    delta_image = axes[3].imshow(
        delta, origin="lower", extent=extent, cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-dmax, vcenter=0, vmax=dmax),
        interpolation="nearest", aspect="equal",
    )
    HELPERS.draw_macros(axes[3], layouts[methods[0]]["macros"], units, "black")
    axes[3].set_title("RUPlace - HPWL\ncell-area density delta", fontsize=9)
    axes[3].set_xlabel("X (um)")
    fig.colorbar(image, ax=axes[:3], shrink=0.78, label="Cell area / bin area")
    fig.colorbar(delta_image, ax=axes[3], shrink=0.78, label="Density delta")
    fig.suptitle(
        "%s: legalized placement layout, seed 1001\n%d standard cells, %d fixed macros" % (
            case.label, layouts[methods[0]]["standard_cells"], layouts[methods[0]]["macro_count"]
        ),
        fontsize=12,
    )
    fig.savefig(output, dpi=190, bbox_inches="tight")
    return fig


def collect_rows(cases: tuple[CaseArtifact, ...]) -> list[dict]:
    rows = []
    for case in cases:
        paths_by_seed = {
            1001: tuple((artifact.method, artifact.metrics_path) for artifact in case.seed1001),
            1002: case.seed1002_metrics,
        }
        for seed, paths in paths_by_seed.items():
            loaded = {method: load_metrics(path) for method, path in paths}
            baseline = loaded["dp_hpwl"]
            for method, current in loaded.items():
                rows.append({
                    "case": case.name,
                    "seed": seed,
                    "method": method,
                    "wirelength": current["wirelength"],
                    "egr_h_pct": current["egr_horizontal_congestion"],
                    "egr_v_pct": current["egr_vertical_congestion"],
                    "h_overflow": current["horizontal_overflow"],
                    "v_overflow": current["vertical_overflow"],
                    "wl_vs_hpwl_pct": delta_pct(current["wirelength"], baseline["wirelength"]),
                    "h_vs_hpwl_pct": delta_pct(current["horizontal_overflow"], baseline["horizontal_overflow"]),
                    "v_vs_hpwl_pct": delta_pct(current["vertical_overflow"], baseline["vertical_overflow"]),
                })
    return rows


def summary_page(rows: list[dict], cases: tuple[CaseArtifact, ...]):
    fig = plt.figure(figsize=(11.69, 8.27), constrained_layout=True)
    grid = fig.add_gridspec(2, 1, height_ratios=[0.22, 0.78])
    title_ax = fig.add_subplot(grid[0])
    title_ax.axis("off")
    title_ax.text(0.0, 0.88, "RUPlace Adaptive S14 Layout and QoR Report", fontsize=21, weight="bold")
    title_ax.text(
        0.0, 0.48,
        "Legalized DEF layout density | Cadence Innovus 22 earlyGlobalRoute | seeds 1001/1002",
        fontsize=11,
    )
    title_ax.text(
        0.0, 0.12,
        "Outcome: nvdla meets the medium target; regression reduces overflow but misses the target and incurs high rWL.",
        fontsize=10,
    )

    table_ax = fig.add_subplot(grid[1])
    table_ax.axis("off")
    columns = ["Case", "Seed", "Method", "rWL (M)", "EGR H/V", "rWL vs HPWL", "H/V ovfl vs HPWL"]
    cell_rows = []
    for row in rows:
        cell_rows.append([
            row["case"].replace("_s14", ""), str(row["seed"]), row["method"],
            "%.3f" % (row["wirelength"] / 1e6),
            "%.2f%% / %.2f%%" % (row["egr_h_pct"], row["egr_v_pct"]),
            "%+.1f%%" % row["wl_vs_hpwl_pct"],
            "%+.1f%% / %+.1f%%" % (row["h_vs_hpwl_pct"], row["v_vs_hpwl_pct"]),
        ])
    table = table_ax.table(cellText=cell_rows, colLabels=columns, loc="upper center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8.4)
    table.scale(1.0, 1.55)
    for column in range(len(columns)):
        table[(0, column)].set_facecolor("#333333")
        table[(0, column)].set_text_props(color="white", weight="bold")
    for index, row in enumerate(rows, start=1):
        if row["method"] == "ruplace":
            table[(index, 2)].set_facecolor("#dcefe8")
    return fig


def inflation_page(cases: tuple[CaseArtifact, ...]):
    fig, axes = plt.subplots(1, 2, figsize=(11.69, 8.27), constrained_layout=True)
    for ax, case in zip(axes, cases):
        status = json.loads(case.inflation_status.read_text())
        history = [item for item in status["history"] if item.get("gpugr")]
        checks = np.arange(1, len(history) + 1)
        h = [item["gpugr"]["ucb_h"] for item in history]
        v = [item["gpugr"]["ucb_v"] for item in history]
        ax.plot(checks, h, marker="o", label="Calibrated H UCB")
        ax.plot(checks, v, marker="s", label="Calibrated V UCB")
        ax.axhline(status["target_pct"], color="#b33a3a", linestyle="--", label="Medium target")
        ax.set_title(
            "%s\narea growth %.1f%% | %d module + %d cell rounds" % (
                case.name, 100.0 * status["cumulative_area_growth"],
                status["module_rounds"], status["cell_rounds"],
            )
        )
        ax.set_xlabel("GPUGR confirmation")
        ax.set_ylabel("Predicted Innovus NR-eGR overflow (%)")
        ax.set_xticks(checks)
        ax.grid(color="#dddddd", linewidth=0.7)
        ax.legend(fontsize=8)
        ax.text(
            0.02, 0.02, "stop: %s" % status["stop_reason"], transform=ax.transAxes,
            fontsize=9, bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "#bbbbbb"},
        )
    fig.suptitle("Adaptive inflation controller history (seed 1001)", fontsize=16)
    return fig


def write_markdown(output: Path, rows: list[dict], cases: tuple[CaseArtifact, ...]) -> None:
    lines = [
        "# RUPlace Adaptive S14 Layout Visualization Report",
        "",
        "Protocol: legalized DEF, Cadence Innovus 22 earlyGlobalRoute, seeds 1001 and 1002.",
        "",
        "| Case | Seed | Method | rWL | NR-eGR H/V | rWL vs HPWL | H/V overflow vs HPWL |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| %s | %d | %s | %.0f | %.2f%% / %.2f%% | %+.2f%% | %+.1f%% / %+.1f%% |" % (
                row["case"], row["seed"], row["method"], row["wirelength"],
                row["egr_h_pct"], row["egr_v_pct"], row["wl_vs_hpwl_pct"],
                row["h_vs_hpwl_pct"], row["v_vs_hpwl_pct"],
            )
        )
    lines.extend(["", "## Layouts", ""])
    for case in cases:
        lines.extend([
            "### %s" % case.name,
            "",
            "![%s layout](figures/%s_layout_comparison.png)" % (case.name, case.name),
            "",
        ])
    lines.extend([
        "## Interpretation",
        "",
        "- nvdla_s meets the medium target on both seeds with a 1.82-2.34% rWL increase over dp_hpwl.",
        "- regression_s14 reduces H/V overflow by about 65%/69%, but misses the medium target and increases rWL by 24-26%.",
        "- Layout maps are 256x256 cell-area-density rasters; white or black outlines are fixed macros.",
        "",
    ])
    output.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=WORKTREE / "reports/ruplace_s14_adaptive_visual",
    )
    parser.add_argument("--layout-bins", type=int, default=256)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    figure_dir = output_dir / "figures"
    data_dir = output_dir / "data"
    figure_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    cases = case_artifacts()
    validate_inputs(cases)
    lef_paths = [
        Path("/home/yifan/data/benchmarks/s14/nvdla_s_s14/lef_lib/all_lef/scc14nsfp_90sdb_9tc16_rvt_ant.lef"),
        Path("/home/yifan/data/benchmarks/s14/nvdla_s_s14/SARM2_new.lef"),
    ]
    sizes = HELPERS.parse_lef_sizes(lef_paths)
    rows = collect_rows(cases)
    manifest = {"schema_version": 1, "layout_bins": args.layout_bins, "cases": {}}
    layout_figures = []
    for case in cases:
        layouts = {}
        metrics = {}
        for artifact in case.seed1001:
            layouts[artifact.method] = HELPERS.parse_def_layout(
                artifact.def_path, sizes, args.layout_bins
            )
            metrics[artifact.method] = load_metrics(artifact.metrics_path)
        figure_path = figure_dir / (case.name + "_layout_comparison.png")
        layout_figures.append(plot_layout(case, layouts, metrics, figure_path))
        np.savez_compressed(
            data_dir / (case.name + "_layout_density.npz"),
            **{method + "_density": layout["density"] for method, layout in layouts.items()},
            die=np.asarray(layouts["dp_hpwl"]["die"]), units=layouts["dp_hpwl"]["units"],
        )
        manifest["cases"][case.name] = {
            "methods": {
                artifact.method: {
                    "def": str(artifact.def_path), "def_sha256": sha256(artifact.def_path),
                    "metrics": str(artifact.metrics_path), "metrics_sha256": sha256(artifact.metrics_path),
                    "layout": {key: value for key, value in layouts[artifact.method].items()
                               if key not in {"density", "macros"}},
                }
                for artifact in case.seed1001
            },
            "inflation_status": str(case.inflation_status),
            "inflation_status_sha256": sha256(case.inflation_status),
        }

    summary = summary_page(rows, cases)
    inflation = inflation_page(cases)
    pdf_path = output_dir / "RUPLACE_S14_ADAPTIVE_VISUAL_REPORT.pdf"
    with PdfPages(pdf_path) as pdf:
        pdf.savefig(summary, bbox_inches="tight")
        for figure in layout_figures:
            pdf.savefig(figure, bbox_inches="tight")
        pdf.savefig(inflation, bbox_inches="tight")
    summary.savefig(figure_dir / "qor_summary.png", dpi=190, bbox_inches="tight")
    inflation.savefig(figure_dir / "inflation_history.png", dpi=190, bbox_inches="tight")
    for figure in [summary, inflation] + layout_figures:
        plt.close(figure)

    fieldnames = list(rows[0])
    with (data_dir / "metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_markdown(output_dir / "RUPLACE_S14_ADAPTIVE_VISUAL_REPORT.md", rows, cases)
    print(pdf_path)


if __name__ == "__main__":
    main()
