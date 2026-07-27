#!/usr/bin/env python3
"""Select screening survivors without numerically mixing evaluator backends."""

import argparse
import csv
import json
import math
from pathlib import Path


WIRELENGTH_GUARDED_METRICS = (
    ("placement", "placement_hpwl"),
    ("gpugr", "gr_wirelength"),
    ("gpugr", "gr_vias"),
    ("gpugr", "congestion_score"),
    ("rudy", "overflow_sum"),
    ("rudy", "congestion_score"),
)

ROUTABILITY_PRIMARY_METRICS = (
    ("gpugr", "est_shorts"),
    ("gpugr", "num_ovfl_nets"),
    ("gpugr", "congestion_score"),
    ("rudy", "overflow_sum"),
    ("rudy", "congestion_score"),
)

ROUTABILITY_SECONDARY_METRICS = (
    ("gpugr", "gr_wirelength"),
    ("gpugr", "gr_vias"),
)

ROUTABILITY_DIAGNOSTIC_METRICS = (("placement", "placement_hpwl"),)

ROUTABILITY_BACKEND_CONSTRAINTS = {
    "gpugr": {
        "metrics": ("est_shorts", "num_ovfl_nets", "congestion_score"),
        "minimum_improvements": 2,
    },
    "rudy": {
        "metrics": ("overflow_sum", "congestion_score"),
        "minimum_improvements": 1,
    },
}


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


def objective_delta(row, use_median=False):
    percent_key = "median_delta_pct" if use_median else "mean_delta_pct"
    percent_value = row.get(percent_key)
    if (
        row.get("percent_valid_count", row.get("valid_count"))
        == row.get("valid_count")
        and isinstance(percent_value, (int, float))
        and math.isfinite(percent_value)
    ):
        return percent_value
    raw_key = "median_delta" if use_median else "mean_delta"
    return row[raw_key]


def select_survivors(data, plugin_states, baseline="hpwl", max_survivors=5,
                     max_hpwl_mean=5.0, max_hpwl_worst=10.0,
                     max_gpugr_wl_mean=5.0, max_gpugr_wl_worst=10.0,
                     preset_provenance=None,
                     selection_policy="routability_first"):
    if selection_policy not in ("routability_first", "wirelength_guarded"):
        raise ValueError("unknown selection policy: %s" % selection_policy)
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
    if selection_policy == "routability_first":
        required_metrics = (
            ROUTABILITY_PRIMARY_METRICS
            + ROUTABILITY_SECONDARY_METRICS
            + ROUTABILITY_DIAGNOSTIC_METRICS
        )
        objective_metrics = ROUTABILITY_PRIMARY_METRICS + ROUTABILITY_SECONDARY_METRICS
    else:
        required_metrics = WIRELENGTH_GUARDED_METRICS
        objective_metrics = WIRELENGTH_GUARDED_METRICS
    objective_names = ["%s:%s" % item for item in objective_metrics]
    primary_names = ["%s:%s" % item for item in ROUTABILITY_PRIMARY_METRICS]

    for method in methods:
        metrics = {}
        reasons = []
        for backend, metric in required_metrics:
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

        if not reasons and selection_policy == "wirelength_guarded":
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
            improvement_names = (
                primary_names if selection_policy == "routability_first" else [
                    "gpugr:gr_wirelength", "gpugr:gr_vias",
                    "gpugr:congestion_score", "rudy:overflow_sum",
                    "rudy:congestion_score",
                ]
            )
            improved = any(
                objective_delta(
                    metrics[name], use_median=name == "rudy:overflow_sum"
                ) < 0
                for name in improvement_names
            )
            if not improved:
                reasons.append("no primary routability metric improved")

        if not reasons and selection_policy == "routability_first":
            for backend, constraint in ROUTABILITY_BACKEND_CONSTRAINTS.items():
                backend_metrics = [
                    "%s:%s" % (backend, metric)
                    for metric in constraint["metrics"]
                ]
                improvement_count = sum(
                    objective_delta(
                        metrics[name], use_median=name == "rudy:overflow_sum"
                    ) < 0
                    for name in backend_metrics
                )
                minimum = constraint["minimum_improvements"]
                if improvement_count < minimum:
                    reasons.append(
                        "fewer than %d/%d %s primary metrics improved" % (
                            minimum, len(backend_metrics), backend.upper()
                        )
                    )

        record = {
            "method": method,
            "plugins": sorted(state["plugins"]),
            "is_atomic_plugin": len(state["plugins"]) == 1,
            "metrics": {
                key: {
                    "mean_delta_pct": row["mean_delta_pct"],
                    "median_delta_pct": row["median_delta_pct"],
                    "worst_delta_pct": row["worst_delta_pct"],
                    "mean_delta": row.get("mean_delta", row["mean_delta_pct"]),
                    "median_delta": row.get(
                        "median_delta", row["median_delta_pct"]
                    ),
                    "worst_delta": row.get("worst_delta", row["worst_delta_pct"]),
                    "valid_count": row["valid_count"],
                    "percent_valid_count": row.get(
                        "percent_valid_count", row["valid_count"]
                    ),
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
                    objective_delta(
                        metrics[name], use_median=name == "rudy:overflow_sum"
                    )
                )
                for name in objective_names
            }
            record["primary_objectives"] = {
                name: record["objectives"][name]
                for name in primary_names if name in record["objectives"]
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
    if selection_policy == "routability_first":
        frontier.sort(key=lambda row: (
            sum(value >= 0 for value in row["primary_objectives"].values()),
            max(row["primary_objectives"].values()),
            row["objectives"]["gpugr:est_shorts"],
            row["objectives"]["gpugr:num_ovfl_nets"],
            row["objectives"]["gpugr:gr_wirelength"],
            row["method"],
        ))
    else:
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
            "name": selection_policy,
            "method": (
                "routability-first Pareto frontier with routed wirelength and vias secondary"
                if selection_policy == "routability_first" else
                "hard wirelength guardrails followed by multiobjective Pareto frontier"
            ),
            "numeric_backend_mixing": False,
            "max_survivors": max_survivors,
            "primary_objectives": primary_names if selection_policy == "routability_first" else [],
            "backend_improvement_constraints": (
                ROUTABILITY_BACKEND_CONSTRAINTS
                if selection_policy == "routability_first" else {}
            ),
            "secondary_objectives": (
                ["%s:%s" % item for item in ROUTABILITY_SECONDARY_METRICS]
                if selection_policy == "routability_first" else []
            ),
            "diagnostic_metrics": (
                ["%s:%s" % item for item in ROUTABILITY_DIAGNOSTIC_METRICS]
                if selection_policy == "routability_first" else []
            ),
            **({
                "max_hpwl_mean_delta_pct": max_hpwl_mean,
                "max_hpwl_worst_delta_pct": max_hpwl_worst,
                "max_gpugr_wirelength_mean_delta_pct": max_gpugr_wl_mean,
                "max_gpugr_wirelength_worst_delta_pct": max_gpugr_wl_worst,
            } if selection_policy == "wirelength_guarded" else {}),
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
    parser.add_argument(
        "--selection-policy",
        choices=("routability_first", "wirelength_guarded"),
        default="routability_first",
    )
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
        selection_policy=args.selection_policy,
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
