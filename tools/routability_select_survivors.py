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
    ("gpugr", "gr_wirelength"),
    ("gpugr", "est_shorts"),
    ("gpugr", "num_ovfl_nets"),
    ("gpugr", "rc_hor"),
    ("gpugr", "rc_ver"),
    ("gpugr", "congestion_score"),
    ("rudy", "overflow_sum"),
    ("rudy", "congestion_score"),
)

ROUTABILITY_SECONDARY_METRICS = (
    ("gpugr", "gr_vias"),
)

ROUTABILITY_DIAGNOSTIC_METRICS = (("placement", "placement_hpwl"),)

ROUTABILITY_BACKEND_CONSTRAINTS = {
    "gpugr": {
        "metrics": (
            "gr_wirelength", "est_shorts", "num_ovfl_nets", "rc_hor",
            "rc_ver", "congestion_score",
        ),
        "minimum_improvements": 1,
    },
    "rudy": {
        "metrics": ("overflow_sum", "congestion_score"),
        "minimum_improvements": 1,
    },
}

ABSOLUTE_DIRECTIONAL_PRIMARY_METRICS = (
    ("gpugr", "gr_wirelength"),
    ("gpugr", "est_shorts"),
    ("gpugr", "num_ovfl_nets"),
    ("gpugr", "overflow_sum"),
    ("gpugr", "overflow_bins"),
    ("gpugr", "utilization_p99"),
    ("gpugr", "utilization_max"),
    ("gpugr", "horizontal_overflow_sum"),
    ("gpugr", "vertical_overflow_sum"),
    ("gpugr", "horizontal_overflow_bins"),
    ("gpugr", "vertical_overflow_bins"),
    ("gpugr", "rc_hor"),
    ("gpugr", "rc_ver"),
    ("gpugr", "horizontal_utilization_p99"),
    ("gpugr", "vertical_utilization_p99"),
    ("gpugr", "horizontal_utilization_max"),
    ("gpugr", "vertical_utilization_max"),
    ("gpugr", "horizontal_congestion_score"),
    ("gpugr", "vertical_congestion_score"),
    ("gpugr", "horizontal_congestion_score_p95"),
    ("gpugr", "vertical_congestion_score_p95"),
    ("gpugr", "horizontal_congestion_score_p99"),
    ("gpugr", "vertical_congestion_score_p99"),
    ("gpugr", "horizontal_ace"),
    ("gpugr", "vertical_ace"),
    ("rudy", "overflow_sum"),
    ("rudy", "overflow_bins"),
    ("rudy", "utilization_p99"),
    ("rudy", "utilization_max"),
)

ABSOLUTE_DIRECTIONAL_DIAGNOSTIC_METRICS = (
    ("placement", "placement_hpwl"),
    ("gpugr", "congestion_score"),
    ("rudy", "congestion_score"),
)

# V2 retained p99/mean and p95/mean concentration ratios as primary metrics.
# They can regress when every absolute congestion metric improves because the
# map mean falls faster than its tail. V3 keeps the versioned V2 contract
# intact while gating on capacity-relevant absolute metrics instead.
NORMALIZED_DIRECTIONAL_CONCENTRATION_METRICS = (
    ("gpugr", "horizontal_congestion_score"),
    ("gpugr", "vertical_congestion_score"),
    ("gpugr", "horizontal_congestion_score_p95"),
    ("gpugr", "vertical_congestion_score_p95"),
    ("gpugr", "horizontal_congestion_score_p99"),
    ("gpugr", "vertical_congestion_score_p99"),
)

ABSOLUTE_DIRECTIONAL_V3_PRIMARY_METRICS = tuple(
    item for item in ABSOLUTE_DIRECTIONAL_PRIMARY_METRICS
    if item not in NORMALIZED_DIRECTIONAL_CONCENTRATION_METRICS
)

ABSOLUTE_DIRECTIONAL_V3_DIAGNOSTIC_METRICS = (
    ABSOLUTE_DIRECTIONAL_DIAGNOSTIC_METRICS
    + NORMALIZED_DIRECTIONAL_CONCENTRATION_METRICS
)

ABSOLUTE_DIRECTIONAL_BACKEND_CONSTRAINTS = {
    "gpugr": {
        "metrics": tuple(
            metric for backend, metric in ABSOLUTE_DIRECTIONAL_PRIMARY_METRICS
            if backend == "gpugr"
        ),
        "minimum_improvements": 1,
    },
    "rudy": {
        "metrics": tuple(
            metric for backend, metric in ABSOLUTE_DIRECTIONAL_PRIMARY_METRICS
            if backend == "rudy"
        ),
        "minimum_improvements": 1,
    },
}

ABSOLUTE_DIRECTIONAL_V3_BACKEND_CONSTRAINTS = {
    backend: {
        "metrics": tuple(
            metric
            for metric_backend, metric in ABSOLUTE_DIRECTIONAL_V3_PRIMARY_METRICS
            if metric_backend == backend
        ),
        "minimum_improvements": 1,
    }
    for backend in ("gpugr", "rudy")
}

ROUTABILITY_METRIC_PROFILES = {
    "legacy": {
        "primary": ROUTABILITY_PRIMARY_METRICS,
        "secondary": ROUTABILITY_SECONDARY_METRICS,
        "diagnostic": ROUTABILITY_DIAGNOSTIC_METRICS,
        "constraints": ROUTABILITY_BACKEND_CONSTRAINTS,
        "worst_regression_backends": ("gpugr",),
    },
    "absolute_directional_v2": {
        "primary": ABSOLUTE_DIRECTIONAL_PRIMARY_METRICS,
        "secondary": ROUTABILITY_SECONDARY_METRICS,
        "diagnostic": ABSOLUTE_DIRECTIONAL_DIAGNOSTIC_METRICS,
        "constraints": ABSOLUTE_DIRECTIONAL_BACKEND_CONSTRAINTS,
        "worst_regression_backends": ("gpugr",),
    },
    "absolute_directional_v3": {
        "primary": ABSOLUTE_DIRECTIONAL_V3_PRIMARY_METRICS,
        "secondary": ROUTABILITY_SECONDARY_METRICS,
        "diagnostic": ABSOLUTE_DIRECTIONAL_V3_DIAGNOSTIC_METRICS,
        "constraints": ABSOLUTE_DIRECTIONAL_V3_BACKEND_CONSTRAINTS,
        "worst_regression_backends": ("gpugr",),
    },
}


def routability_metric_profile(name):
    try:
        return ROUTABILITY_METRIC_PROFILES[name]
    except KeyError:
        raise ValueError("unknown routability metric profile: %s" % name)


def load_plugin_states(path):
    states = {}
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("backend") != "placement":
                continue
            method = row["method"]
            state = states.setdefault(method, {
                "statuses": [], "plugins": set(), "rows": 0,
                "observations": [],
            })
            state["rows"] += 1
            status = row.get("plugin_status", "")
            state["statuses"].append(status)
            state["observations"].append({
                "case": row.get("case", ""),
                "seed": row.get("seed", ""),
                "status": status,
            })
            state["plugins"].update(
                value for value in row.get("plugin_selected", "").split(",") if value
            )
    return states


def load_placement_effects(path):
    """Load byte-identity evidence used to validate intentionally gated no-ops."""
    data = json.loads(Path(path).read_text())
    if data.get("status") not in (
        "passed", "passed_with_active_identical_candidates_excluded",
    ):
        raise ValueError("placement-effect audit did not pass")
    effects = {}
    for row in data.get("rows", []):
        method = row.get("method")
        if not isinstance(method, str) or not method:
            raise ValueError("placement-effect audit has an invalid method")
        key = (str(row.get("case", "")), str(row.get("seed", "")))
        method_effects = effects.setdefault(method, {})
        if key in method_effects:
            raise ValueError(
                "placement-effect audit has duplicate %s/%s/%s" % (
                    key[0], key[1], method,
                )
            )
        method_effects[key] = row
    return {
        "expected_comparisons": int(data.get("expected_comparisons", 0)),
        "methods": effects,
    }


def plugin_activation_reasons(state, expected, placement_effects=None,
                              method=None):
    """Require real activation while permitting hash-proven gated no-op slots."""
    if state["rows"] != expected:
        return ["plugin lacks full placement provenance"]
    statuses = state["statuses"]
    allowed = {"active", "selected_no_activation"}
    if any(status not in allowed for status in statuses):
        return ["plugin has invalid activation status"]
    if all(status == "active" for status in statuses):
        return []
    if not any(status == "active" for status in statuses):
        return ["plugin was not active in any comparison"]
    if placement_effects is None:
        return [
            "gated inactive comparisons lack placement-effect identity evidence"
        ]
    if placement_effects.get("expected_comparisons") != expected:
        return ["placement-effect audit comparison coverage mismatch"]
    method_effects = placement_effects["methods"].get(method, {})
    observations = {
        (str(row["case"]), str(row["seed"])): row["status"]
        for row in state.get("observations", [])
    }
    if len(observations) != expected or len(method_effects) != expected:
        return ["placement-effect audit method coverage mismatch"]
    for key, status in observations.items():
        effect = method_effects.get(key)
        if effect is None:
            return ["placement-effect audit slot coverage mismatch"]
        active = bool(effect.get("active"))
        changed = bool(effect.get("changed_from_baseline"))
        if status == "active" and (not active or not changed):
            return ["active placement lacks changed-DEF evidence"]
        if status == "selected_no_activation" and (active or changed):
            return ["inactive placement is not a hash-proven no-op"]
    return []


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


def worst_objective_delta(row):
    """Use percent deltas only when every pair has a nonzero baseline."""
    percent_value = row.get("worst_delta_pct")
    if (
        row.get("percent_valid_count", row.get("valid_count"))
        == row.get("valid_count")
        and isinstance(percent_value, (int, float))
        and math.isfinite(percent_value)
    ):
        return percent_value
    return row["worst_delta"]


def select_survivors(data, plugin_states, baseline="hpwl", max_survivors=5,
                     max_hpwl_mean=5.0, max_hpwl_worst=10.0,
                     max_gpugr_wl_mean=5.0, max_gpugr_wl_worst=10.0,
                     max_primary_worst_regression=None,
                     preset_provenance=None, metric_profile="legacy",
                     selection_policy="routability_first",
                     placement_effects=None):
    if selection_policy not in ("routability_first", "wirelength_guarded"):
        raise ValueError("unknown selection policy: %s" % selection_policy)
    if not complete_summary(data):
        raise ValueError("screening summary is not a complete validated campaign")
    profile = routability_metric_profile(metric_profile)
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
        required_metrics = profile["primary"] + profile["secondary"] + profile["diagnostic"]
        objective_metrics = profile["primary"] + profile["secondary"]
    else:
        required_metrics = WIRELENGTH_GUARDED_METRICS
        objective_metrics = WIRELENGTH_GUARDED_METRICS
    objective_names = ["%s:%s" % item for item in objective_metrics]
    primary_names = ["%s:%s" % item for item in profile["primary"]]

    for method in methods:
        metrics = {}
        reasons = []
        for backend, metric in required_metrics:
            row = index.get((backend, metric, method))
            if not row or int(row.get("valid_count", 0)) != expected:
                reasons.append("missing full %s:%s coverage" % (backend, metric))
                continue
            metrics["%s:%s" % (backend, metric)] = row
        state = plugin_states.get(method, {
            "statuses": [], "plugins": set(), "rows": 0,
            "observations": [],
        })
        is_plugin_method = bool(state["plugins"])
        if is_plugin_method:
            activation_reasons = plugin_activation_reasons(
                state, expected, placement_effects=placement_effects,
                method=method,
            )
            reasons.extend(activation_reasons)
        metrics_complete = not reasons

        if metrics_complete and selection_policy == "wirelength_guarded":
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

        if metrics_complete:
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

        if metrics_complete and selection_policy == "routability_first":
            for backend, constraint in profile["constraints"].items():
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

        if (
            metrics_complete
            and selection_policy == "routability_first"
            and max_primary_worst_regression is not None
        ):
            violations = []
            guarded_backends = set(profile["worst_regression_backends"])
            for name in primary_names:
                if name.split(":", 1)[0] not in guarded_backends:
                    continue
                value = worst_objective_delta(metrics[name])
                if value > max_primary_worst_regression:
                    violations.append("%s=%g" % (name, value))
            if violations:
                reasons.append(
                    "worst-case primary regression exceeds %g: %s" % (
                        max_primary_worst_regression, ", ".join(violations)
                    )
                )

        record = {
            "method": method,
            "plugins": sorted(state["plugins"]),
            "is_atomic_plugin": len(state["plugins"]) == 1,
            "activation": {
                "active_comparisons": sum(
                    status == "active" for status in state["statuses"]
                ),
                "inactive_noop_comparisons": sum(
                    status == "selected_no_activation"
                    for status in state["statuses"]
                ),
                "placement_effect_audit_used": placement_effects is not None,
            },
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
            "metric_profile": metric_profile,
            "method": (
                "proxy-screen Pareto frontier with GPUGR routed wirelength, "
                "congestion, and violations primary and vias secondary; "
                "golden metrics are ranked separately"
                if selection_policy == "routability_first" else
                "hard wirelength guardrails followed by multiobjective Pareto frontier"
            ),
            "numeric_backend_mixing": False,
            "max_survivors": max_survivors,
            "primary_objectives": primary_names if selection_policy == "routability_first" else [],
            "backend_improvement_constraints": (
                profile["constraints"]
                if selection_policy == "routability_first" else {}
            ),
            "max_primary_worst_regression": (
                max_primary_worst_regression
                if selection_policy == "routability_first" else None
            ),
            "worst_regression_backends": (
                list(profile["worst_regression_backends"])
                if selection_policy == "routability_first" else []
            ),
            "secondary_objectives": (
                ["%s:%s" % item for item in profile["secondary"]]
                if selection_policy == "routability_first" else []
            ),
            "diagnostic_metrics": (
                ["%s:%s" % item for item in profile["diagnostic"]]
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
    parser.add_argument(
        "--placement-effect-audit", type=Path,
        help=(
            "byte-identity audit required when a gated plugin is intentionally "
            "inactive in some comparisons"
        ),
    )
    parser.add_argument("--baseline", default="hpwl")
    parser.add_argument(
        "--selection-policy",
        choices=("routability_first", "wirelength_guarded"),
        default="routability_first",
    )
    parser.add_argument(
        "--metric-profile",
        choices=tuple(sorted(ROUTABILITY_METRIC_PROFILES)),
        default="legacy",
    )
    parser.add_argument("--max-survivors", type=int, default=5)
    parser.add_argument("--max-hpwl-mean-pct", type=float, default=5.0)
    parser.add_argument("--max-hpwl-worst-pct", type=float, default=10.0)
    parser.add_argument("--max-gpugr-wl-mean-pct", type=float, default=5.0)
    parser.add_argument("--max-gpugr-wl-worst-pct", type=float, default=10.0)
    parser.add_argument(
        "--max-primary-worst-regression", type=float,
        help=(
            "reject a routability-first candidate when any primary worst-case "
            "delta for a profile-guarded backend exceeds this value; percentages "
            "are used only with complete nonzero-baseline coverage, otherwise raw "
            "deltas are used"
        ),
    )
    parser.add_argument("--combination-proxy", default="rudy")
    args = parser.parse_args(argv)

    raw = args.raw or args.summary.parent / "screening_raw.csv"
    preset_provenance = None
    if args.preset_manifest:
        preset_provenance = json.loads(args.preset_manifest.read_text()).get(
            "generated", {}
        )
    placement_effects = (
        load_placement_effects(args.placement_effect_audit)
        if args.placement_effect_audit else None
    )
    result = select_survivors(
        json.loads(args.summary.read_text()), load_plugin_states(raw),
        baseline=args.baseline, max_survivors=args.max_survivors,
        max_hpwl_mean=args.max_hpwl_mean_pct,
        max_hpwl_worst=args.max_hpwl_worst_pct,
        max_gpugr_wl_mean=args.max_gpugr_wl_mean_pct,
        max_gpugr_wl_worst=args.max_gpugr_wl_worst_pct,
        max_primary_worst_regression=args.max_primary_worst_regression,
        preset_provenance=preset_provenance,
        metric_profile=args.metric_profile,
        selection_policy=args.selection_policy,
        placement_effects=placement_effects,
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
