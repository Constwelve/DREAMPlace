#!/usr/bin/env python3
"""Collect RUPlace tuning leaders across benchmark result directories."""

import argparse
import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan RUPlace result folders and report best route-WL/congestion runs."
    )
    parser.add_argument(
        "--result-root",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality",
    )
    parser.add_argument("--designs", default="", help="Comma-separated design filter.")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--baseline-run",
        default="paper_full_bestwl_t8seed1001_composite",
        help="Run whose comparison_summary.csv provides Xplace/DREAMPlace baselines.",
    )
    parser.add_argument(
        "--congestion-slack",
        type=float,
        default=1.05,
        help="Congestion-qualified WL leaders must be within this factor of baseline RUPlace congestion.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality" / "tuning_leaderboard.md",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality" / "tuning_leaderboard.csv",
    )
    return parser.parse_args()


def numeric(row, key):
    value = row.get(key, "")
    if value in ("", "NA", None):
        return None
    return float(value)


def load_baseline(result_root, run_id):
    path = result_root / run_id / "comparison_summary.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {row["design"]: row for row in csv.DictReader(f)}


def load_baseline_ruplace_congestion(result_root, run_id):
    path = result_root / run_id / "raw_metrics.csv"
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("method") != "ruplace" or row.get("status") != "ok":
                continue
            out[row["design"]] = {
                "route_ovfl_nets": int(numeric(row, "route_ovfl_nets") or 0),
                "route_est_shorts": int(numeric(row, "route_est_shorts") or 0),
            }
    return out


def load_ruplace_rows(result_root, designs):
    rows = []
    for raw_path in sorted(result_root.glob("*/raw_metrics.csv")):
        run_id = raw_path.parent.name
        if (
            ("rrr2" in run_id and "eval1" not in run_id)
            or run_id in {"paper_full_auto_qualified_v38", "paper_full_congestion_balanced_v29"}
        ):
            continue
        with raw_path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("method") != "ruplace" or row.get("status") != "ok":
                    continue
                if designs and row.get("design") not in designs:
                    continue
                route_wl = numeric(row, "route_wl")
                if route_wl is None:
                    continue
                rows.append(
                    {
                        "run": run_id,
                        "design": row["design"],
                        "route_wl": int(route_wl),
                        "route_ovfl_nets": int(numeric(row, "route_ovfl_nets") or 0),
                        "route_est_shorts": int(numeric(row, "route_est_shorts") or 0),
                        "place_hpwl": numeric(row, "place_hpwl"),
                    }
                )
    return rows


def fmt(value, digits=3):
    if value is None:
        return "NA"
    if isinstance(value, int):
        return str(value)
    return ("%.*f" % (digits, value)).rstrip("0").rstrip(".")


def ratio(value, baseline):
    if value is None or baseline in (None, 0):
        return None
    return float(value) / float(baseline)


def enrich(rows, baseline):
    for row in rows:
        base = baseline.get(row["design"], {})
        x_wl = numeric(base, "xplace_route_wl")
        dp_wl = numeric(base, "dp_rudy_route_wl")
        row["ru_vs_xplace_route_wl"] = ratio(row["route_wl"], x_wl)
        row["ru_vs_dp_rudy_route_wl"] = ratio(row["route_wl"], dp_wl)
        row["congestion_score"] = row["route_ovfl_nets"] + row["route_est_shorts"]
    return rows


def write_csv(path, rows):
    fields = [
        "design",
        "run",
        "route_wl",
        "route_ovfl_nets",
        "route_est_shorts",
        "congestion_score",
        "place_hpwl",
        "ru_vs_xplace_route_wl",
        "ru_vs_dp_rudy_route_wl",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["place_hpwl"] = fmt(out.get("place_hpwl"), 0)
            out["ru_vs_xplace_route_wl"] = fmt(out.get("ru_vs_xplace_route_wl"), 6)
            out["ru_vs_dp_rudy_route_wl"] = fmt(out.get("ru_vs_dp_rudy_route_wl"), 6)
            writer.writerow({field: out.get(field, "") for field in fields})


def write_markdown(path, rows, top, baseline_congestion, congestion_slack):
    by_design = {}
    for row in rows:
        by_design.setdefault(row["design"], []).append(row)
    lines = [
        "# RUPlace Tuning Leaderboard",
        "",
        "Scans `raw_metrics.csv` files under `results/ruplace_quality`. Lower values are better.",
    ]
    for design in sorted(by_design):
        design_rows = by_design[design]
        best_wl = sorted(design_rows, key=lambda r: (r["route_wl"], r["congestion_score"], r["run"]))[:top]
        best_cong = sorted(design_rows, key=lambda r: (r["congestion_score"], r["route_wl"], r["run"]))[:top]
        base_cong = baseline_congestion.get(design, {})
        max_ovfl = int(base_cong.get("route_ovfl_nets", 0) * congestion_slack)
        max_shorts = int(base_cong.get("route_est_shorts", 0) * congestion_slack)
        qualified = []
        if base_cong:
            qualified = [
                row
                for row in design_rows
                if row["route_ovfl_nets"] <= max_ovfl
                and row["route_est_shorts"] <= max_shorts
            ]
            qualified = sorted(qualified, key=lambda r: (r["route_wl"], r["congestion_score"], r["run"]))[:top]
        lines.extend(
            [
                "",
                "## %s" % design,
                "",
                "### Best Routed Wirelength",
                "",
                "| Rank | Run | GR WL | OvflNets | EstShorts | RU/Xplace WL | RU/RUDY WL |",
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for rank, row in enumerate(best_wl, 1):
            lines.append(
                "| %d | `%s` | %d | %d | %d | %s | %s |"
                % (
                    rank,
                    row["run"],
                    row["route_wl"],
                    row["route_ovfl_nets"],
                    row["route_est_shorts"],
                    fmt(row.get("ru_vs_xplace_route_wl"), 6),
                    fmt(row.get("ru_vs_dp_rudy_route_wl"), 6),
                )
            )
        if qualified:
            lines.extend(
                [
                    "",
                    "### Best Routed Wirelength Within Baseline Congestion",
                    "",
                    "Baseline limits: OvflNets <= %d, EstShorts <= %d." % (max_ovfl, max_shorts),
                    "",
                    "| Rank | Run | GR WL | OvflNets | EstShorts | RU/Xplace WL | RU/RUDY WL |",
                    "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for rank, row in enumerate(qualified, 1):
                lines.append(
                    "| %d | `%s` | %d | %d | %d | %s | %s |"
                    % (
                        rank,
                        row["run"],
                        row["route_wl"],
                        row["route_ovfl_nets"],
                        row["route_est_shorts"],
                        fmt(row.get("ru_vs_xplace_route_wl"), 6),
                        fmt(row.get("ru_vs_dp_rudy_route_wl"), 6),
                    )
                )
        lines.extend(
            [
                "",
                "### Best Congestion",
                "",
                "| Rank | Run | Score | OvflNets | EstShorts | GR WL | RU/Xplace WL |",
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for rank, row in enumerate(best_cong, 1):
            lines.append(
                "| %d | `%s` | %d | %d | %d | %d | %s |"
                % (
                    rank,
                    row["run"],
                    row["congestion_score"],
                    row["route_ovfl_nets"],
                    row["route_est_shorts"],
                    row["route_wl"],
                    fmt(row.get("ru_vs_xplace_route_wl"), 6),
                )
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main():
    args = parse_args()
    result_root = args.result_root.resolve()
    designs = {item.strip() for item in args.designs.split(",") if item.strip()}
    rows = enrich(load_ruplace_rows(result_root, designs), load_baseline(result_root, args.baseline_run))
    rows = sorted(rows, key=lambda r: (r["design"], r["route_wl"], r["run"]))
    write_csv(args.csv_output, rows)
    write_markdown(
        args.output,
        rows,
        args.top,
        load_baseline_ruplace_congestion(result_root, args.baseline_run),
        args.congestion_slack,
    )
    print("Wrote %s and %s from %d RUPlace rows" % (args.output, args.csv_output, len(rows)))


if __name__ == "__main__":
    main()
