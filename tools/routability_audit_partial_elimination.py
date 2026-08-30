#!/usr/bin/env python3
"""Audit irreversible proxy-gate failures in a partial development campaign."""

import argparse
from collections import Counter
import json
from pathlib import Path

try:
    from tools.routability_select_survivors import (
        load_placement_effects,
        load_plugin_states,
        objective_delta,
        routability_metric_profile,
        worst_objective_delta,
    )
except ModuleNotFoundError:
    from routability_select_survivors import (
        load_placement_effects,
        load_plugin_states,
        objective_delta,
        routability_metric_profile,
        worst_objective_delta,
    )


def partial_activation_reasons(state, completed, configured_plugins,
                               placement_effects=None, method=None):
    """Validate completed slots while permitting hash-proven gated no-ops."""
    if not configured_plugins and not state["plugins"]:
        return "valid", [], 0
    if state["rows"] != completed:
        return "indeterminate", [
            "plugin lacks completed placement provenance"
        ], 0
    if configured_plugins and state["plugins"] != configured_plugins:
        return "invalid", [
            "selected plugins do not match preset provenance"
        ], 0

    statuses = state["statuses"]
    allowed = {"active", "selected_no_activation"}
    if any(status not in allowed for status in statuses):
        return "invalid", ["plugin has invalid activation status"], 0
    inactive_count = sum(
        status == "selected_no_activation" for status in statuses
    )
    if not inactive_count and placement_effects is None:
        return "valid", [], 0
    if placement_effects is None:
        return "indeterminate", [
            "gated inactive comparisons lack placement-effect identity evidence"
        ], 0
    if placement_effects.get("expected_comparisons") != completed:
        return "indeterminate", [
            "placement-effect audit comparison coverage mismatch"
        ], 0

    observations = state.get("observations", [])
    observation_index = {
        (str(row.get("case", "")), str(row.get("seed", ""))): row.get("status")
        for row in observations
    }
    method_effects = placement_effects.get("methods", {}).get(method, {})
    if (
        len(observations) != completed
        or len(observation_index) != completed
        or len(method_effects) != completed
    ):
        return "indeterminate", [
            "placement-effect audit method coverage mismatch"
        ], 0

    for key, status in observation_index.items():
        effect = method_effects.get(key)
        if effect is None:
            return "indeterminate", [
                "placement-effect audit slot coverage mismatch"
            ], 0
        active = bool(effect.get("active"))
        changed = bool(effect.get("changed_from_baseline"))
        if status == "active" and (not active or not changed):
            return "invalid", [
                "active placement lacks changed-DEF evidence"
            ], 0
        if status == "selected_no_activation" and (active or changed):
            return "invalid", [
                "inactive placement is not a hash-proven no-op"
            ], 0
    return "valid", [], inactive_count


def audit_partial_elimination(data, plugin_states, preset_provenance=None,
                              metric_profile="absolute_directional_v2",
                              placement_effects=None):
    expected = int(data.get("expected_comparisons") or 0)
    completed = int(data.get("validated_comparisons") or 0)
    if expected <= 0 or completed <= 0 or completed >= expected:
        raise ValueError("summary must contain a nonempty partial campaign")
    if data.get("excluded"):
        raise ValueError("partial campaign contains excluded comparisons")
    if data.get("baseline_gaps"):
        raise ValueError("partial campaign lacks same-seed baselines")

    profile = routability_metric_profile(metric_profile)
    primary = profile["primary"]
    constraints = profile["constraints"]
    guarded_backends = set(profile["worst_regression_backends"])
    index = {
        (row["backend"], row["metric"], row["method"]): row
        for row in data.get("rows", [])
    }
    methods = sorted({
        method for backend, metric, method in index
        if backend == "placement" and metric == "placement_hpwl"
        and method != data.get("baseline", "hpwl")
    })
    eliminated = []
    eliminated_metric = []
    eliminated_inactive = []
    possible = []
    pending_activation = []
    indeterminate = []
    for method in methods:
        provenance = (preset_provenance or {}).get(method, {})
        state = plugin_states.get(method, {
            "statuses": [], "plugins": set(), "rows": 0,
        })
        coverage_reasons = []
        configured_plugins = set(provenance.get("plugins", []))
        (
            activation_evidence_status,
            activation_reasons,
            inactive_noop_count,
        ) = partial_activation_reasons(
            state, completed, configured_plugins,
            placement_effects=placement_effects, method=method,
        )

        metrics = {}
        for backend, metric in primary:
            row = index.get((backend, metric, method))
            if not row or int(row.get("valid_count", 0)) != completed:
                coverage_reasons.append(
                    "missing completed coverage for %s:%s" % (backend, metric)
                )
            else:
                metrics["%s:%s" % (backend, metric)] = row

        record = {
            "method": method,
            "plugins": sorted(configured_plugins or state["plugins"]),
            "feedback_proxy": provenance.get("proxy"),
            "completed_comparisons": completed,
            "activation": {
                "active_comparisons": sum(
                    status == "active" for status in state["statuses"]
                ),
                "inactive_noop_comparisons": inactive_noop_count,
                "placement_effect_audit_used": placement_effects is not None,
                "evidence_status": activation_evidence_status,
            },
        }
        if coverage_reasons:
            record["classification"] = "indeterminate_structural"
            record["reasons"] = sorted(set(coverage_reasons))
            indeterminate.append(record)
            continue

        violations = {
            name: worst_objective_delta(row)
            for name, row in metrics.items()
            if (
                name.split(":", 1)[0] in guarded_backends
                and worst_objective_delta(row) > 0.0
            )
        }
        improvements = {}
        for backend, constraint in constraints.items():
            improvements[backend] = sorted(
                metric for metric in constraint["metrics"]
                if objective_delta(
                    metrics["%s:%s" % (backend, metric)],
                    use_median=(backend == "rudy" and metric == "overflow_sum"),
                ) < 0.0
            )
        record["current_backend_improvements"] = improvements
        record["positive_worst_primary_regressions"] = violations
        if activation_evidence_status == "invalid":
            record["classification"] = "irreversibly_eliminated_inactive"
            record["reasons"] = activation_reasons
            eliminated.append(record)
            eliminated_inactive.append(record)
        elif violations:
            record["classification"] = "irreversibly_eliminated"
            eliminated.append(record)
            eliminated_metric.append(record)
        elif activation_evidence_status == "indeterminate":
            record["classification"] = "indeterminate_structural"
            record["reasons"] = activation_reasons
            indeterminate.append(record)
        elif inactive_noop_count:
            record["classification"] = "still_possible_pending_activation"
            record["reasons"] = [
                "completed inactive slots are hash-proven baseline no-ops; "
                "a remaining comparison may activate the plugin"
            ]
            possible.append(record)
            pending_activation.append(record)
        else:
            record["classification"] = "still_possible_zero_regression"
            possible.append(record)

    violation_metric_counts = Counter(
        metric for row in eliminated_metric
        for metric in row["positive_worst_primary_regressions"]
    )
    classification_by_plugin = {}
    for label, records in (
        ("metric_regression", eliminated_metric),
        ("inactive", eliminated_inactive),
        ("still_possible", possible),
        ("indeterminate", indeterminate),
    ):
        for row in records:
            for plugin in row["plugins"] or ["unknown"]:
                counts = classification_by_plugin.setdefault(plugin, {
                    "metric_regression": 0,
                    "inactive": 0,
                    "still_possible": 0,
                    "indeterminate": 0,
                })
                counts[label] += 1

    return {
        "schema_version": 2,
        "status": "partial_elimination_audit",
        "metric_profile": metric_profile,
        "expected_comparisons": expected,
        "completed_comparisons": completed,
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "selection_or_admission_decision": False,
        "worst_regression_backends": sorted(guarded_backends),
        "irreversible_elimination_rule": (
            "any positive worst-case primary delta in a guarded backend "
            "during completed development comparisons, or contradictory "
            "plugin activation and placement-effect evidence"
        ),
        "eliminated_count": len(eliminated),
        "eliminated_metric_regression_count": len(eliminated_metric),
        "eliminated_inactive_count": len(eliminated_inactive),
        "still_possible_count": len(possible),
        "pending_activation_count": len(pending_activation),
        "indeterminate_count": len(indeterminate),
        "positive_regression_metric_counts": dict(sorted(
            violation_metric_counts.items()
        )),
        "classification_by_plugin": dict(sorted(
            classification_by_plugin.items()
        )),
        "eliminated": eliminated,
        "eliminated_metric_regression": eliminated_metric,
        "eliminated_inactive": eliminated_inactive,
        "still_possible": possible,
        "pending_activation": pending_activation,
        "indeterminate": indeterminate,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--preset-manifest", type=Path)
    parser.add_argument("--placement-effect-audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metric-profile", default="absolute_directional_v2")
    args = parser.parse_args(argv)

    data = json.loads(args.summary.read_text())
    states = load_plugin_states(args.raw)
    provenance = None
    if args.preset_manifest:
        provenance = json.loads(args.preset_manifest.read_text()).get("generated", {})
    placement_effects = (
        load_placement_effects(args.placement_effect_audit)
        if args.placement_effect_audit else None
    )
    result = audit_partial_elimination(
        data, states, provenance, args.metric_profile, placement_effects
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
