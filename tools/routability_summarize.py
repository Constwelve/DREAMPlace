#!/usr/bin/env python3
"""Aggregate routability campaigns without mixing evaluator backends."""

import argparse
import csv
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


PRIMARY_METRICS = {
    "placement": ("placement_hpwl", "density_overflow", "runtime_sec"),
    "rudy": ("overflow_sum", "congestion_score", "utilization_max"),
    "gpugr": ("gr_wirelength", "gr_vias", "congestion_score"),
    "openroad": ("wirelength", "vias", "overflow"),
    "innovus": (
        "wirelength", "vias", "overflow", "horizontal_congestion",
        "vertical_congestion",
    ),
}


def finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def campaign_identity(path, root):
    parts = path.relative_to(root).parts
    seed_index = next(
        (index for index, part in enumerate(parts) if part.startswith("seed_")),
        None,
    )
    if seed_index is None or seed_index == 0:
        raise ValueError("cannot infer case and seed from %s" % path)
    return parts[seed_index - 1], int(parts[seed_index][len("seed_"):])


def flatten_result(case, seed, method, backend, metrics, result):
    row = {
        "case": case,
        "seed": seed,
        "method": method,
        "backend": backend,
        "status": result.get("status", ""),
        "runtime_sec": result.get("runtime_sec", ""),
    }
    for key, value in metrics.items():
        if finite_number(value):
            row[key] = value
    return row


def load_comparison(path, root):
    case, seed = campaign_identity(path, root)
    data = json.loads(path.read_text())
    validation = data.get("validation", {})
    if validation.get("status") != "validated":
        return [], {
            "case": case,
            "seed": seed,
            "path": str(path),
            "status": validation.get("status", "missing"),
        }

    rows = []
    for placement in data.get("placements", []):
        if placement.get("status") != "ok":
            continue
        metrics = {
            key: placement.get(key)
            for key in PRIMARY_METRICS["placement"]
            if finite_number(placement.get(key))
        }
        row = flatten_result(
            case, seed, placement.get("method", ""), "placement", metrics,
            placement,
        )
        row["plugin_status"] = placement.get("routability_plugin_status", "")
        row["plugin_selected"] = placement.get("routability_plugin_selected", "")
        rows.append(row)

    for result in data.get("results", []):
        if result.get("status") != "ok" or not result.get(
            "authoritative_for_comparison", False
        ):
            continue
        rows.append(flatten_result(
            case,
            seed,
            result.get("method", ""),
            result.get("backend", ""),
            result.get("metrics", {}),
            result,
        ))
    return rows, None


def add_baseline_deltas(rows, baseline):
    baselines = {
        (row["case"], row["seed"], row["backend"]): row
        for row in rows if row["method"] == baseline
    }
    for row in rows:
        base = baselines.get((row["case"], row["seed"], row["backend"]))
        if not base:
            continue
        for metric in PRIMARY_METRICS.get(row["backend"], ()):
            value = row.get(metric)
            base_value = base.get(metric)
            if finite_number(value) and finite_number(base_value) and base_value != 0:
                row[metric + "_delta_pct"] = (value / base_value - 1.0) * 100.0
    return baselines


def summarize(rows, baselines):
    groups = defaultdict(list)
    for row in rows:
        for metric in PRIMARY_METRICS.get(row["backend"], ()):
            delta = row.get(metric + "_delta_pct")
            if finite_number(delta):
                groups[(row["backend"], metric, row["method"])].append(delta)

    expected = defaultdict(int)
    for _, _, backend in baselines:
        expected[backend] += 1

    summary = []
    for (backend, metric, method), values in sorted(groups.items()):
        wins = sum(value < 0 for value in values)
        ties = sum(abs(value) <= 1e-12 for value in values)
        summary.append({
            "backend": backend,
            "metric": metric,
            "method": method,
            "valid_count": len(values),
            "expected_count": expected[backend],
            "mean_delta_pct": statistics.fmean(values),
            "median_delta_pct": statistics.median(values),
            "best_delta_pct": min(values),
            "worst_delta_pct": max(values),
            "wins": wins,
            "ties": ties,
            "losses": len(values) - wins - ties,
        })
    return summary


def write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path, comparisons, rows, summary, excluded, baseline):
    lines = [
        "# Routability Screening Summary",
        "",
        "- Baseline: `%s`" % baseline,
        "- Validated comparisons: `%d`" % comparisons,
        "- Raw backend rows: `%d`" % len(rows),
        "- Excluded comparisons: `%d`" % len(excluded),
        "- Negative deltas are improvements; backends are ranked separately.",
        "",
    ]
    for backend, metrics in PRIMARY_METRICS.items():
        for metric in metrics:
            ranking = [
                row for row in summary
                if row["backend"] == backend and row["metric"] == metric
            ]
            if not ranking:
                continue
            ranking.sort(key=lambda row: (row["mean_delta_pct"], row["method"]))
            lines.extend([
                "## %s: %s" % (backend, metric),
                "",
                "| Method | Mean delta | Median | Worst | W/T/L | Coverage |",
                "|---|---:|---:|---:|---:|---:|",
            ])
            for row in ranking:
                lines.append(
                    "| %s | %.3f%% | %.3f%% | %.3f%% | %d/%d/%d | %d/%d |" % (
                        row["method"], row["mean_delta_pct"],
                        row["median_delta_pct"], row["worst_delta_pct"],
                        row["wins"], row["ties"], row["losses"],
                        row["valid_count"], row["expected_count"],
                    )
                )
            lines.append("")
    path.write_text("\n".join(lines) + "\n")


def campaign_gate(root, comparison_keys):
    status_path = root / "parallel_status.json"
    if not status_path.exists():
        return {
            "parallel_status": "not_present",
            "expected_comparisons": None,
            "incomplete_jobs": [],
            "missing_comparisons": [],
        }
    jobs = json.loads(status_path.read_text()).get("jobs", [])
    expected = {(str(job["case"]), int(job["seed"])) for job in jobs}
    incomplete = [
        {
            "case": str(job["case"]),
            "seed": int(job["seed"]),
            "status": str(job.get("status", "missing")),
            "returncode": job.get("returncode", ""),
        }
        for job in jobs if job.get("status") != "completed"
    ]
    missing = [
        {"case": case, "seed": seed}
        for case, seed in sorted(expected - comparison_keys)
    ]
    return {
        "parallel_status": str(status_path),
        "expected_comparisons": len(expected),
        "incomplete_jobs": incomplete,
        "missing_comparisons": missing,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", default="hpwl")
    args = parser.parse_args(argv)

    root = args.campaign_dir.resolve()
    paths = sorted(root.rglob("comparison.json"))
    rows = []
    excluded = []
    valid_comparisons = 0
    for path in paths:
        loaded, exclusion = load_comparison(path, root)
        if exclusion:
            excluded.append(exclusion)
        else:
            rows.extend(loaded)
            valid_comparisons += 1

    baselines = add_baseline_deltas(rows, args.baseline)
    comparison_keys = {(row["case"], row["seed"]) for row in rows}
    gate = campaign_gate(root, comparison_keys)
    backends_by_comparison = defaultdict(set)
    for row in rows:
        backends_by_comparison[(row["case"], row["seed"])].add(row["backend"])
    baseline_gaps = []
    for case, seed in sorted(comparison_keys):
        for backend in sorted(backends_by_comparison[(case, seed)]):
            if (case, seed, backend) not in baselines:
                baseline_gaps.append({
                    "case": case, "seed": seed, "backend": backend,
                    "baseline": args.baseline,
                })
    summary = summarize(rows, baselines)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "screening_raw.csv", rows)
    write_csv(args.output_dir / "screening_summary.csv", summary)
    (args.output_dir / "screening_summary.json").write_text(json.dumps({
        "baseline": args.baseline,
        "comparison_files": len(paths),
        "validated_comparisons": valid_comparisons,
        "excluded": excluded,
        "baseline_gaps": baseline_gaps,
        **gate,
        "rows": summary,
    }, indent=2, sort_keys=True) + "\n")
    write_report(
        args.output_dir / "report.md", valid_comparisons, rows, summary,
        excluded, args.baseline,
    )
    return 0 if (
        paths
        and valid_comparisons == len(paths)
        and not baseline_gaps
        and not gate["incomplete_jobs"]
        and not gate["missing_comparisons"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
