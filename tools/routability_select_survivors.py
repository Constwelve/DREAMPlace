#!/usr/bin/env python3
"""Select screening survivors without numerically mixing evaluator backends."""

import argparse
import csv
import json
from pathlib import Path


REQUIRED_METRICS = (
    ("placement", "placement_hpwl"),
    ("gpugr", "gr_wirelength"),
    ("gpugr", "gr_vias"),
    ("gpugr", "congestion_score"),
    ("rudy", "overflow_sum"),
    ("rudy", "congestion_score"),
)


def load_plugin_states(path):
    states = {}
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("backend") != "placement":
                continue
            method = row["method"]
            state = states.setdefault(method, {
                "statuses": [], "plugins": set(), "rows": 0,
            })
            state["rows"] += 1
            state["statuses"].append(row.get("plugin_status", ""))
            state["plugins"].update(
                value for value in row.get("plugin_selected", "").split(",") if value
            )
    return states


def complete_summary(data):
    expected = data.get("expected_comparisons")
    return bool(
        expected
        and data.get("validated_comparisons") == expected
        and not data.get("incomplete_jobs")
        and not data.get("missing_comparisons")
        and not data.get("excluded")
        and not data.get("baseline_gaps")
    )


def dominates(left, right, objectives):
    left_values = [left[objective] for objective in objectives]
    right_values = [right[objective] for objective in objectives]
    return all(a <= b for a, b in zip(left_values, right_values)) and any(
        a < b for a, b in zip(left_values, right_values)
    )


def select_survivors(data, plugin_states, baseline="hpwl", max_survivors=5,
                     max_hpwl_mean=5.0, max_hpwl_worst=10.0,
                     max_gpugr_wl_mean=5.0, max_gpugr_wl_worst=10.0,
                     preset_provenance=None):
    if not complete_summary(data):
        raise ValueError("screening summary is not a complete validated campaign")
    expected = int(data["expected_comparisons"])
    index = {
        (row["backend"], row["metric"], row["method"]): row
        for row in data.get("rows", [])
    }
    methods = sorted({
        method for backend, metric, method in index
        if backend == "placement" and metric == "placement_hpwl"
        and method != baseline
    })
    qualified = []
    excluded = []
    objective_names = ["%s:%s" % item for item in REQUIRED_METRICS]

    for method in methods:
        metrics = {}
        reasons = []
        for backend, metric in REQUIRED_METRICS:
            row = index.get((backend, metric, method))
            if not row or int(row.get("valid_count", 0)) != expected:
                reasons.append("missing full %s:%s coverage" % (backend, metric))
                continue
            metrics["%s:%s" % (backend, metric)] = row
        state = plugin_states.get(method, {"statuses": [], "plugins": set(), "rows": 0})
        is_plugin_method = bool(state["plugins"])
        if is_plugin_method and (
            state["rows"] != expected or any(status != "active" for status in state["statuses"])
        ):
            reasons.append("plugin was not active in every comparison")

        if not reasons:
            hpwl = metrics["placement:placement_hpwl"]
            gpugr_wl = metrics["gpugr:gr_wirelength"]
            if hpwl["mean_delta_pct"] > max_hpwl_mean:
                reasons.append("mean placement HPWL guardrail")
            if hpwl["worst_delta_pct"] > max_hpwl_worst:
                reasons.append("worst placement HPWL guardrail")
            if gpugr_wl["mean_delta_pct"] > max_gpugr_wl_mean:
                reasons.append("mean GPUGR wirelength guardrail")
            if gpugr_wl["worst_delta_pct"] > max_gpugr_wl_worst:
                reasons.append("worst GPUGR wirelength guardrail")

        if not reasons:
            improved = any([
                metrics["gpugr:gr_wirelength"]["mean_delta_pct"] < 0,
                metrics["gpugr:gr_vias"]["mean_delta_pct"] < 0,
                metrics["gpugr:congestion_score"]["mean_delta_pct"] < 0,
                metrics["rudy:overflow_sum"]["median_delta_pct"] < 0,
                metrics["rudy:congestion_score"]["mean_delta_pct"] < 0,
            ])
            if not improved:
                reasons.append("no screening routability metric improved")

        record = {
            "method": method,
            "plugins": sorted(state["plugins"]),
            "is_atomic_plugin": len(state["plugins"]) == 1,
            "metrics": {
                key: {
                    "mean_delta_pct": row["mean_delta_pct"],
                    "median_delta_pct": row["median_delta_pct"],
                    "worst_delta_pct": row["worst_delta_pct"],
                    "case_wins": row["case_wins"],
                    "case_losses": row["case_losses"],
                }
                for key, row in metrics.items()
            },
        }
        if preset_provenance and method in preset_provenance:
            record["preset_provenance"] = preset_provenance[method]
        if reasons:
            record["reasons"] = reasons
            excluded.append(record)
        else:
            record["objectives"] = {
                name: (
                    metrics[name]["median_delta_pct"]
                    if name == "rudy:overflow_sum"
                    else metrics[name]["mean_delta_pct"]
                )
                for name in objective_names
            }
            qualified.append(record)

    frontier = [
        candidate for candidate in qualified
        if not any(
            other is not candidate
            and dominates(other["objectives"], candidate["objectives"], objective_names)
            for other in qualified
        )
    ]
    frontier.sort(key=lambda row: (
        row["objectives"]["gpugr:gr_wirelength"],
        row["metrics"]["gpugr:gr_wirelength"]["worst_delta_pct"],
        row["objectives"]["placement:placement_hpwl"],
        row["method"],
    ))
    selected = []
    selected_atomic_plugins = set()
    for candidate in frontier:
        if candidate["is_atomic_plugin"]:
            plugin = candidate["plugins"][0]
            if plugin in selected_atomic_plugins:
                continue
            selected_atomic_plugins.add(plugin)
        selected.append(candidate)
        if len(selected) >= max_survivors:
            break
    combination_plugin_grids = {}
    shared_schedule_keys = {
        "ruplace_plugin_start_overflow", "ruplace_inflate_start_overflow",
    }
    for candidate in selected:
        if not candidate["is_atomic_plugin"]:
            continue
        plugin = candidate["plugins"][0]
        provenance = candidate.get("preset_provenance", {})
        fixed = {
            key: [value]
            for key, value in provenance.get("grid", {}).items()
            if key not in shared_schedule_keys
        }
        if fixed:
            combination_plugin_grids[plugin] = fixed
    return {
        "baseline": baseline,
        "expected_comparisons": expected,
        "selection_policy": {
            "method": "hard guardrails followed by multiobjective Pareto frontier",
            "numeric_backend_mixing": False,
            "max_survivors": max_survivors,
            "max_hpwl_mean_delta_pct": max_hpwl_mean,
            "max_hpwl_worst_delta_pct": max_hpwl_worst,
            "max_gpugr_wirelength_mean_delta_pct": max_gpugr_wl_mean,
            "max_gpugr_wirelength_worst_delta_pct": max_gpugr_wl_worst,
            "objectives": objective_names,
        },
        "qualified": qualified,
        "pareto_frontier": [row["method"] for row in frontier],
        "selected_methods": [row["method"] for row in selected],
        "combination_plugins": [
            row["plugins"][0] for row in selected if row["is_atomic_plugin"]
        ],
        "combination_plugin_grids": combination_plugin_grids,
        "excluded": excluded,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--combination-spec", type=Path)
    parser.add_argument("--preset-manifest", type=Path)
    parser.add_argument("--baseline", default="hpwl")
    parser.add_argument("--max-survivors", type=int, default=5)
    parser.add_argument("--max-hpwl-mean-pct", type=float, default=5.0)
    parser.add_argument("--max-hpwl-worst-pct", type=float, default=10.0)
    parser.add_argument("--max-gpugr-wl-mean-pct", type=float, default=5.0)
    parser.add_argument("--max-gpugr-wl-worst-pct", type=float, default=10.0)
    parser.add_argument("--combination-proxy", default="rudy")
    args = parser.parse_args(argv)

    raw = args.raw or args.summary.parent / "screening_raw.csv"
    preset_provenance = None
    if args.preset_manifest:
        preset_provenance = json.loads(args.preset_manifest.read_text()).get(
            "generated", {}
        )
    result = select_survivors(
        json.loads(args.summary.read_text()), load_plugin_states(raw),
        baseline=args.baseline, max_survivors=args.max_survivors,
        max_hpwl_mean=args.max_hpwl_mean_pct,
        max_hpwl_worst=args.max_hpwl_worst_pct,
        max_gpugr_wl_mean=args.max_gpugr_wl_mean_pct,
        max_gpugr_wl_worst=args.max_gpugr_wl_worst_pct,
        preset_provenance=preset_provenance,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.combination_spec:
        plugins = result["combination_plugins"]
        if len(plugins) < 2:
            raise ValueError("fewer than two atomic plugin survivors")
        args.combination_spec.parent.mkdir(parents=True, exist_ok=True)
        combination = {
            "name_prefix": "survivor_pair",
            "copy_presets": [args.baseline],
            "plugins": plugins,
            "combination_sizes": [2],
            "proxies": [args.combination_proxy],
            "grid": {"ruplace_plugin_start_overflow": [0.6, 0.8, 1.0]},
        }
        if result["combination_plugin_grids"]:
            combination["plugin_grids"] = result["combination_plugin_grids"]
        args.combination_spec.write_text(
            json.dumps(combination, indent=2, sort_keys=True) + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
