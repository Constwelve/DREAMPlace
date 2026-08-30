#!/usr/bin/env python3
"""Rank complete golden-router campaigns without scalarizing QoR metrics."""

import argparse
import hashlib
import json
import math
from pathlib import Path


GOLDEN_BACKENDS = ("openroad", "innovus")
DIRECTIONAL_METRIC_PAIRS = (
    ("horizontal_overflow", "vertical_overflow"),
    ("horizontal_congestion", "vertical_congestion"),
)
OPTIONAL_METRICS = (
    "horizontal_overflow_edges", "vertical_overflow_edges",
)
CONNECTIVITY_METRICS = ("unrouted_nets", "short_violations")
BACKEND_PRIMARY_METRICS = {
    "innovus": ("connectivity_violations", "open_violations"),
}
CORE_ROUTABILITY_METRICS = ("wirelength",)
ROUTED_COST_METRICS = ("vias",)
DIAGNOSTIC_METRICS = (("placement", "placement_hpwl"),)
OBJECTIVE_TOLERANCE = 1e-12


def finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def summary_content_sha256(data):
    payload = json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def case_seed_pairs(data, field):
    rows = data.get(field)
    if not isinstance(rows, list):
        return None
    try:
        pairs = [(str(row["case"]), int(row["seed"])) for row in rows]
    except (KeyError, TypeError, ValueError):
        return None
    if len(set(pairs)) != len(pairs):
        return None
    return sorted(pairs)


def complete_summary(data):
    expected = data.get("expected_comparisons")
    expected_pairs = case_seed_pairs(data, "expected_case_seeds")
    validated_pairs = case_seed_pairs(data, "validated_case_seeds")
    return bool(
        expected
        and data.get("validated_comparisons") == expected
        and expected_pairs
        and len(expected_pairs) == expected
        and validated_pairs == expected_pairs
        and not data.get("incomplete_jobs")
        and not data.get("missing_comparisons")
        and not data.get("excluded")
        and not data.get("baseline_gaps")
        and data.get("plugin_activation_contract") == "validated"
    )


def delta_value(row, field):
    percent_field = field + "_pct"
    percent_value = row.get(percent_field)
    if (
        row.get("percent_valid_count", row.get("valid_count"))
        == row.get("valid_count")
        and finite_number(percent_value)
    ):
        return percent_value, "percent"
    value = row.get(field)
    if not finite_number(value):
        raise ValueError(
            "metric %s:%s:%s lacks finite %s" % (
                row.get("backend"), row.get("metric"), row.get("method"), field
            )
        )
    return value, "absolute"


def metric_evidence(row, backend, method, metric):
    mean, mean_unit = delta_value(row, "mean_delta")
    worst, worst_unit = delta_value(row, "worst_delta")
    if mean_unit != worst_unit:
        raise ValueError("inconsistent delta units for %s:%s" % (method, metric))
    absolute_fields = (
        "mean_value", "mean_baseline", "worst_pair_value",
        "worst_pair_baseline",
    )
    missing_absolute = [
        field for field in absolute_fields if not finite_number(row.get(field))
    ]
    if missing_absolute:
        raise ValueError(
            "%s:%s:%s lacks finite absolute evidence: %s" % (
                backend, method, metric, ", ".join(missing_absolute)
            )
        )
    case_results = row.get("case_results", [])
    if not case_results or any(
        not finite_number(case.get(field))
        for case in case_results
        for field in ("mean_value", "mean_baseline")
    ):
        raise ValueError(
            "%s:%s:%s lacks per-design absolute evidence" % (
                backend, method, metric
            )
        )
    metric_cases = {str(case.get("case", "")) for case in case_results}
    if "" in metric_cases:
        raise ValueError(
            "%s:%s:%s has a missing per-design case name" % (
                backend, method, metric
            )
        )
    return {
        "mean_value": row["mean_value"],
        "mean_baseline": row["mean_baseline"],
        "mean_delta": mean,
        "worst_delta": worst,
        "delta_unit": mean_unit,
        "wins": row.get("wins"),
        "ties": row.get("ties"),
        "losses": row.get("losses"),
        "case_wins": row.get("case_wins"),
        "case_ties": row.get("case_ties"),
        "case_losses": row.get("case_losses"),
        "case_ci95_low_pct": row.get("case_ci95_low_pct"),
        "case_ci95_high_pct": row.get("case_ci95_high_pct"),
        "case_ci95_low": row.get("case_ci95_low"),
        "case_ci95_high": row.get("case_ci95_high"),
        "statistical_evidence_unit": row.get("statistical_evidence_unit"),
        "case_results": case_results,
        "worst_case": row.get("worst_case"),
        "worst_case_mean_delta": row.get("worst_case_mean_delta"),
        "worst_case_mean_delta_pct": row.get("worst_case_mean_delta_pct"),
        "worst_pair_case": row.get("worst_pair_case"),
        "worst_pair_seed": row.get("worst_pair_seed"),
        "worst_pair_value": row["worst_pair_value"],
        "worst_pair_baseline": row["worst_pair_baseline"],
        "worst_pair_delta": row.get("worst_pair_delta"),
        "worst_pair_delta_pct": row.get("worst_pair_delta_pct"),
        "statistically_supported": bool(row.get("statistically_supported", False)),
        "consistent_improvement": bool(row.get("consistent_improvement", False)),
    }, metric_cases


def dominates(left, right, objective_names):
    return all(
        left[name] <= right[name] + OBJECTIVE_TOLERANCE
        for name in objective_names
    ) and any(
        left[name] < right[name] - OBJECTIVE_TOLERANCE
        for name in objective_names
    )


def within_secondary_cost_budget(candidate, metrics, max_mean_pct, max_worst_pct):
    for metric in metrics:
        evidence = candidate["metrics"][metric]
        if evidence["delta_unit"] == "percent":
            mean_limit = max_mean_pct
            worst_limit = max_worst_pct
        else:
            # A zero baseline has no meaningful percent budget. Do not allow an
            # absolute routed-cost increase in that case.
            mean_limit = 0.0
            worst_limit = 0.0
        if (
            evidence["mean_delta"] > mean_limit + OBJECTIVE_TOLERANCE
            or evidence["worst_delta"] > worst_limit + OBJECTIVE_TOLERANCE
        ):
            return False
    return True


def choose_directional_metrics(index, backend, methods):
    selected = [
        pair for pair in DIRECTIONAL_METRIC_PAIRS
        if all((backend, metric, method) in index for metric in pair for method in methods)
    ]
    if selected:
        return tuple(metric for pair in selected for metric in pair)
    raise ValueError(
        "%s summary lacks complete horizontal and vertical congestion coverage" % backend
    )


def rank_summary(data, source, baseline="hpwl"):
    if not complete_summary(data):
        raise ValueError("golden summary is not a complete validated campaign: %s" % source)
    expected = int(data["expected_comparisons"])
    case_seeds = case_seed_pairs(data, "expected_case_seeds")
    rows = data.get("rows", [])
    backends = sorted({
        row.get("backend") for row in rows if row.get("backend") in GOLDEN_BACKENDS
    })
    if len(backends) != 1:
        raise ValueError(
            "each golden summary must contain exactly one golden backend, found %s in %s"
            % (backends, source)
        )
    backend = backends[0]
    backend_rows = [row for row in rows if row.get("backend") == backend]
    diagnostic_keys = set(DIAGNOSTIC_METRICS)
    diagnostic_rows = [
        row for row in rows
        if (row.get("backend"), row.get("metric")) in diagnostic_keys
    ]
    relevant_rows = backend_rows + diagnostic_rows
    keys = [
        (row.get("backend"), row.get("metric"), row.get("method"))
        for row in relevant_rows
    ]
    duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
    if duplicate_keys:
        raise ValueError(
            "duplicate golden metric rows in %s: %s" % (source, duplicate_keys)
        )
    index = {
        (row["backend"], row["metric"], row["method"]): row
        for row in relevant_rows
    }
    methods = sorted({
        method for row_backend, _metric, method in index
        if row_backend == backend and method
    })
    if baseline not in methods:
        raise ValueError("missing %s baseline for %s" % (baseline, source))
    diagnostic_methods = {
        method for row_backend, metric, method in index
        if (row_backend, metric) in diagnostic_keys and method
    }
    if diagnostic_methods != set(methods):
        raise ValueError(
            "%s summary lacks exact placement_hpwl method coverage" % source
        )
    directional = choose_directional_metrics(index, backend, methods)
    violation_metrics = (
        ("drc_violations",) + directional + CONNECTIVITY_METRICS
        + BACKEND_PRIMARY_METRICS.get(backend, ())
    )
    primary_routability = violation_metrics + CORE_ROUTABILITY_METRICS
    # A shorter route alone is useful QoR, but it is not evidence that a
    # routability mechanism improved congestion or route correctness.
    routability_improvement_metrics = violation_metrics
    routed_cost = ROUTED_COST_METRICS
    routability = primary_routability + routed_cost
    required = routability

    candidates = []
    covered_cases = None
    for method in methods:
        metric_rows = {}
        for metric in required:
            row = index.get((backend, metric, method))
            if row is None or int(row.get("valid_count", 0)) != expected:
                raise ValueError(
                    "%s:%s lacks complete %s coverage in %s" % (
                        backend, method, metric, source
                    )
                )
            metric_rows[metric] = row
        objectives = {}
        metrics = {}
        for metric, row in metric_rows.items():
            evidence, metric_cases = metric_evidence(
                row, backend, method, metric
            )
            if covered_cases is None:
                covered_cases = metric_cases
            elif metric_cases != covered_cases:
                raise ValueError(
                    "%s summary has inconsistent per-design coverage: %s:%s "
                    "covers %s, expected %s" % (
                        backend, method, metric, sorted(metric_cases),
                        sorted(covered_cases),
                    )
                )
            objectives[metric + ":mean"] = evidence["mean_delta"]
            objectives[metric + ":worst"] = evidence["worst_delta"]
            metrics[metric] = evidence
        diagnostics = {}
        for diagnostic_backend, metric in DIAGNOSTIC_METRICS:
            row = index.get((diagnostic_backend, metric, method))
            if row is None or int(row.get("valid_count", 0)) != expected:
                raise ValueError(
                    "%s:%s lacks complete %s coverage in %s" % (
                        diagnostic_backend, method, metric, source
                    )
                )
            evidence, metric_cases = metric_evidence(
                row, diagnostic_backend, method, metric
            )
            if metric_cases != covered_cases:
                raise ValueError(
                    "%s summary has inconsistent per-design coverage: %s:%s "
                    "covers %s, expected %s" % (
                        backend, method, metric, sorted(metric_cases),
                        sorted(covered_cases),
                    )
                )
            diagnostics[metric] = evidence
        optional = {}
        for metric in OPTIONAL_METRICS:
            row = index.get((backend, metric, method))
            if row is None or int(row.get("valid_count", 0)) != expected:
                continue
            mean, unit = delta_value(row, "mean_delta")
            worst, worst_unit = delta_value(row, "worst_delta")
            if unit == worst_unit:
                optional[metric] = {
                    "mean_delta": mean, "worst_delta": worst, "delta_unit": unit,
                }
        candidates.append({
            "method": method,
            "metrics": metrics,
            "diagnostic_metrics": diagnostics,
            "optional_metrics": optional,
            "objectives": objectives,
        })

    objective_names = [
        metric + suffix for metric in required for suffix in (":mean", ":worst")
    ]
    by_method = {row["method"]: row for row in candidates}
    baseline_objectives = by_method[baseline]["objectives"]
    routability_objective_names = [
        metric + suffix
        for metric in primary_routability for suffix in (":mean", ":worst")
    ]
    routed_cost_objective_names = [
        metric + suffix
        for metric in routed_cost for suffix in (":mean", ":worst")
    ]
    for candidate in candidates:
        objectives = candidate["objectives"]
        candidate["dominates_baseline"] = (
            candidate["method"] != baseline
            and dominates(objectives, baseline_objectives, objective_names)
        )
        candidate["dominated_by_baseline"] = (
            candidate["method"] != baseline
            and dominates(baseline_objectives, objectives, objective_names)
        )
        candidate["routability_dominates_baseline"] = (
            candidate["method"] != baseline
            and dominates(
                objectives, baseline_objectives, routability_objective_names
            )
        )
        candidate["routability_safe"] = all(
            objectives[name] <= baseline_objectives[name] + OBJECTIVE_TOLERANCE
            for name in routability_objective_names
        )
        candidate["routed_cost_safe"] = all(
            objectives[name] <= baseline_objectives[name] + OBJECTIVE_TOLERANCE
            for name in routed_cost_objective_names
        )
        candidate["decision_safe"] = all(
            objectives[name] <= baseline_objectives[name] + OBJECTIVE_TOLERANCE
            for name in objective_names
        )
        candidate["drc_worst_regression"] = (
            objectives["drc_violations:worst"] > OBJECTIVE_TOLERANCE
        )
        candidate["routability_evidence_supported"] = any(
            candidate["metrics"][metric]["statistically_supported"]
            or candidate["metrics"][metric]["consistent_improvement"]
            for metric in routability_improvement_metrics
        )
        candidate["decision_evidence_supported"] = any(
            candidate["metrics"][metric]["statistically_supported"]
            or candidate["metrics"][metric]["consistent_improvement"]
            for metric in required
        )
    frontier = sorted(
        candidate["method"] for candidate in candidates
        if not any(
            other["method"] != candidate["method"]
            and dominates(other["objectives"], candidate["objectives"], objective_names)
            for other in candidates
        )
    )
    routability_frontier = sorted(
        candidate["method"] for candidate in candidates
        if not any(
            other["method"] != candidate["method"]
            and dominates(
                other["objectives"], candidate["objectives"],
                routability_objective_names,
            )
            for other in candidates
        )
    )
    return {
        "source": str(source),
        "summary_content_sha256": summary_content_sha256(data),
        "backend": backend,
        "cases": sorted(covered_cases or ()),
        "case_count": len(covered_cases or ()),
        "case_seeds": [
            {"case": case, "seed": seed} for case, seed in case_seeds
        ],
        "expected_comparisons": expected,
        "directional_metrics": list(directional),
        "violation_metrics": list(violation_metrics),
        "routability_metrics": list(routability),
        "primary_routability_metrics": list(primary_routability),
        "routability_improvement_metrics": list(
            routability_improvement_metrics
        ),
        "secondary_routability_metrics": list(routed_cost),
        "routed_cost_metrics": list(routed_cost),
        "diagnostic_metrics": [metric for _backend, metric in DIAGNOSTIC_METRICS],
        "required_metrics": list(required),
        "objective_components": objective_names,
        "pareto_frontier": frontier,
        "full_routability_pareto_frontier": frontier,
        "routability_pareto_frontier": routability_frontier,
        "primary_routability_pareto_frontier": routability_frontier,
        "candidates": candidates,
    }


def rank_campaigns(summaries, sources, baseline="hpwl",
                   max_secondary_mean_pct=5.0,
                   max_secondary_worst_pct=10.0,
                   required_case_sets=None,
                   required_seed_sets=None):
    if len(summaries) != len(sources):
        raise ValueError("summary/source count mismatch")
    if max_secondary_mean_pct < 0 or max_secondary_worst_pct < 0:
        raise ValueError("secondary-cost guardrails must be nonnegative")
    campaigns = [
        rank_summary(data, source, baseline=baseline)
        for data, source in zip(summaries, sources)
    ]
    if required_case_sets is not None:
        if len(required_case_sets) != len(campaigns):
            raise ValueError("required case-set count does not match summaries")
        for campaign, required_cases in zip(campaigns, required_case_sets):
            required = sorted({str(case) for case in required_cases})
            if not required:
                raise ValueError("required case sets must be nonempty")
            if campaign["cases"] != required:
                raise ValueError(
                    "%s case coverage %s does not match required cases %s" % (
                        campaign["backend"], campaign["cases"], required,
                    )
                )
    if required_seed_sets is not None:
        if len(required_seed_sets) != len(campaigns):
            raise ValueError("required seed-set count does not match summaries")
        for campaign, required_seeds in zip(campaigns, required_seed_sets):
            seeds = sorted({int(seed) for seed in required_seeds})
            if not seeds:
                raise ValueError("required seed sets must be nonempty")
            required_pairs = [
                {"case": case, "seed": seed}
                for case in campaign["cases"] for seed in seeds
            ]
            if campaign["case_seeds"] != required_pairs:
                raise ValueError(
                    "%s case-seed coverage %s does not match required matrix %s" % (
                        campaign["backend"], campaign["case_seeds"],
                        required_pairs,
                    )
                )
    method_sets = [
        {row["method"] for row in campaign["candidates"]}
        for campaign in campaigns
    ]
    if any(methods != method_sets[0] for methods in method_sets[1:]):
        raise ValueError(
            "golden summaries do not cover identical method sets: %s" % (
                [sorted(methods) for methods in method_sets]
            )
        )
    common_methods = method_sets[0]
    alternatives = sorted(common_methods - {baseline})
    per_campaign = {
        campaign["source"]: {
            row["method"]: row for row in campaign["candidates"]
        }
        for campaign in campaigns
    }
    for campaign in campaigns:
        for candidate in campaign["candidates"]:
            candidate["secondary_cost_within_budget"] = (
                within_secondary_cost_budget(
                    candidate,
                    campaign["routed_cost_metrics"],
                    max_secondary_mean_pct,
                    max_secondary_worst_pct,
                )
            )
    consensus_frontier = [
        method for method in alternatives
        if all(method in campaign["pareto_frontier"] for campaign in campaigns)
    ]
    strict_winners = [
        method for method in alternatives
        if method in consensus_frontier
        and all(per_campaign[campaign["source"]][method]["dominates_baseline"]
                for campaign in campaigns)
    ]
    drc_safe_consensus = [
        method for method in consensus_frontier
        if all(not per_campaign[campaign["source"]][method]["drc_worst_regression"]
               for campaign in campaigns)
    ]
    routability_safe_consensus = [
        method for method in alternatives
        if all(per_campaign[campaign["source"]][method]["routability_safe"]
               for campaign in campaigns)
    ]
    decision_safe_consensus = [
        method for method in consensus_frontier
        if all(per_campaign[campaign["source"]][method]["decision_safe"]
               for campaign in campaigns)
    ]
    robust_routability_winners = [
        method for method in alternatives
        if all(
            method in campaign["routability_pareto_frontier"]
            and per_campaign[campaign["source"]][method]["routability_safe"]
            for campaign in campaigns
        )
        and any(
            per_campaign[campaign["source"]][method][
                "routability_dominates_baseline"
            ]
            and per_campaign[campaign["source"]][method][
                "routability_evidence_supported"
            ]
            for campaign in campaigns
        )
    ]

    def consensus_full_dominates(left_method, right_method):
        strict = False
        for campaign in campaigns:
            source = campaign["source"]
            left = per_campaign[source][left_method]["objectives"]
            right = per_campaign[source][right_method]["objectives"]
            names = campaign["objective_components"]
            if any(
                left[name] > right[name] + OBJECTIVE_TOLERANCE
                for name in names
            ):
                return False
            strict = strict or any(
                left[name] < right[name] - OBJECTIVE_TOLERANCE
                for name in names
            )
        return strict

    cost_efficient_winners = [
        method for method in robust_routability_winners
        if not any(
            other != method
            and consensus_full_dominates(other, method)
            for other in robust_routability_winners
        )
    ]
    secondary_cost_requirements = {}
    for method in alternatives:
        requirement = {
            "minimum_mean_budget_pct": 0.0,
            "minimum_worst_budget_pct": 0.0,
            "zero_baseline_absolute_increase": False,
            "campaigns": [],
        }
        for campaign in campaigns:
            candidate = per_campaign[campaign["source"]][method]
            campaign_requirement = {
                "source": campaign["source"],
                "backend": campaign["backend"],
                "metrics": {},
            }
            for metric in campaign["routed_cost_metrics"]:
                evidence = candidate["metrics"][metric]
                metric_requirement = {
                    "delta_unit": evidence["delta_unit"],
                    "mean_regression": max(0.0, evidence["mean_delta"]),
                    "worst_regression": max(0.0, evidence["worst_delta"]),
                }
                campaign_requirement["metrics"][metric] = metric_requirement
                if evidence["delta_unit"] == "percent":
                    requirement["minimum_mean_budget_pct"] = max(
                        requirement["minimum_mean_budget_pct"],
                        metric_requirement["mean_regression"],
                    )
                    requirement["minimum_worst_budget_pct"] = max(
                        requirement["minimum_worst_budget_pct"],
                        metric_requirement["worst_regression"],
                    )
                elif (
                    metric_requirement["mean_regression"] > OBJECTIVE_TOLERANCE
                    or metric_requirement["worst_regression"] > OBJECTIVE_TOLERANCE
                ):
                    requirement["zero_baseline_absolute_increase"] = True
            requirement["campaigns"].append(campaign_requirement)
        requirement["eligible_under_policy_budget"] = (
            not requirement["zero_baseline_absolute_increase"]
            and requirement["minimum_mean_budget_pct"]
            <= max_secondary_mean_pct
            and requirement["minimum_worst_budget_pct"]
            <= max_secondary_worst_pct
        )
        secondary_cost_requirements[method] = requirement
    bounded_cost_winners = [
        method for method in cost_efficient_winners
        if secondary_cost_requirements[method]["eligible_under_policy_budget"]
    ]
    robust_decision_winners = [
        method for method in decision_safe_consensus
        if any(
            per_campaign[campaign["source"]][method]["dominates_baseline"]
            and per_campaign[campaign["source"]][method][
                "decision_evidence_supported"
            ]
            for campaign in campaigns
        )
    ]
    recommended = bounded_cost_winners or [baseline]
    return {
        "baseline": baseline,
        "policy": {
            "name": "golden_routability_lexicographic_pareto",
            "numeric_backend_mixing": False,
            "numeric_metric_scalarization": False,
            "objective_comparison_tolerance": OBJECTIVE_TOLERANCE,
            "required_metrics": [
                "drc_violations", "horizontal congestion or overflow",
                "vertical congestion or overflow", "unrouted_nets",
                "short_violations", "Innovus connectivity_violations",
                "Innovus open_violations", "routed wirelength", "vias",
            ],
            "primary_metrics": [
                "drc_violations", "horizontal congestion or overflow",
                "vertical congestion or overflow", "unrouted_nets",
                "short_violations", "Innovus connectivity_violations",
                "Innovus open_violations", "routed wirelength",
            ],
            "secondary_metrics": ["vias"],
            "diagnostic_metrics": ["placement_hpwl"],
            "diagnostic_metrics_affect_decision": False,
            "secondary_cost_guardrails": {
                "max_mean_regression_pct": max_secondary_mean_pct,
                "max_worst_regression_pct": max_secondary_worst_pct,
                "zero_baseline_absolute_increase_allowed": False,
            },
            "decision_metrics": (
                "DRC, horizontal and vertical congestion/overflow, unrouted "
                "nets, short and backend-specific connectivity violations, "
                "routed wirelength, and vias"
            ),
            "routability_metrics": (
                "DRC, directional congestion, unrouted nets, short violations, "
                "backend-specific connectivity failures, routed wirelength, and "
                "vias"
            ),
            "routed_cost_metrics": "vias",
            "acceptance": (
                "A default alternative must not regress the mean or worst case of "
                "any primary routability metric, must remain on every backend-local "
                "primary-routability Pareto frontier, and must Pareto-dominate the "
                "baseline in primary routability for at least one golden backend "
                "with supported improvement in congestion, DRC, unrouted nets, "
                "shorts, or connectivity; routed-wirelength-only improvement is "
                "insufficient. The recommendation retains only robust "
                "routability winners that are not full-Pareto-dominated by the same "
                "robust alternative across every backend, "
                "subject to explicit mean and worst-case via-cost budgets, "
                "without numerically scalarizing metrics or mixing backends."
            ),
        },
        "campaigns": campaigns,
        "common_methods": sorted(common_methods),
        "consensus_pareto_alternatives": consensus_frontier,
        "drc_safe_consensus_alternatives": drc_safe_consensus,
        "routability_safe_consensus_alternatives": routability_safe_consensus,
        "decision_safe_consensus_alternatives": decision_safe_consensus,
        "robust_routability_winners": robust_routability_winners,
        "cost_efficient_routability_winners": cost_efficient_winners,
        "bounded_cost_routability_winners": bounded_cost_winners,
        "secondary_cost_requirements": secondary_cost_requirements,
        "robust_decision_winners": robust_decision_winners,
        "strict_winners": strict_winners,
        "recommended_methods": recommended,
    }


def render_report(result):
    def format_delta(metric):
        suffix = "%" if metric["delta_unit"] == "percent" else ""
        return "%+.3f%s / %+.3f%s" % (
            metric["mean_delta"], suffix, metric["worst_delta"], suffix
        )

    def format_value(value, percent_value):
        if finite_number(percent_value):
            return "%+.3f%%" % percent_value
        return "n/a" if not finite_number(value) else "%+.3f" % value

    def format_absolute(value):
        return "n/a" if not finite_number(value) else "%.6g" % value

    def format_comparison(value, baseline, delta, delta_pct):
        return "%s / %s (%s)" % (
            format_absolute(value), format_absolute(baseline),
            format_value(delta, delta_pct),
        )

    lines = [
        "# Golden Routability Ranking",
        "",
        "- Baseline: `%s`" % result["baseline"],
        "- Numeric backend mixing: `false`",
        "- Numeric metric scalarization: `false`",
        "- Objective comparison tolerance: `%g`" % result["policy"][
            "objective_comparison_tolerance"
        ],
        "- Full routability vector: detailed-route DRC, horizontal and vertical "
        "congestion/overflow, unrouted nets, short and available backend-specific "
        "connectivity and open violations, routed wirelength, and vias.",
        "- Primary routability metrics: detailed-route DRC, horizontal and vertical "
        "congestion/overflow, unrouted nets, short and available backend-specific "
        "connectivity and open violations, and routed wirelength.",
        "- Secondary routed-cost metric: vias.",
        "- Diagnostic-only metric: placement HPWL; it does not affect Pareto "
        "frontiers, safety gates, evidence gates, or winner selection.",
        "- Secondary-cost guardrails: at most %g%% mean and %g%% worst-case "
        "regression for vias; a zero baseline permits "
        "no absolute increase." % (
            result["policy"]["secondary_cost_guardrails"][
                "max_mean_regression_pct"
            ],
            result["policy"]["secondary_cost_guardrails"][
                "max_worst_regression_pct"
            ],
        ),
        "- Default gate: no mean or worst-case regression on any primary "
        "routability metric, supported congestion/DRC/connectivity improvement on at least one golden "
        "backend, membership in every backend-local primary Pareto frontier, and "
        "no consensus full-Pareto domination by another robust candidate. "
        "A routed-wirelength-only improvement is not sufficient; via-cost "
        "tradeoffs remain explicit.",
        "- Optional diagnostics: overflow-edge counts.",
        "",
    ]
    for campaign in result["campaigns"]:
        lines.extend([
            "## %s" % campaign["backend"],
            "",
            "- Source: `%s`" % campaign["source"],
            "- Summary content SHA-256: `%s`" % (
                campaign["summary_content_sha256"]
            ),
            "- Coverage: `%d/%d`" % (
                campaign["expected_comparisons"], campaign["expected_comparisons"]
            ),
            "- Cases (%d): %s" % (
                campaign["case_count"], ", ".join(
                    "`%s`" % case for case in campaign["cases"]
                ),
            ),
            "- Case-seed comparisons: `%d`" % len(campaign["case_seeds"]),
            "- Directional metrics: %s" % ", ".join(
                "`%s`" % metric for metric in campaign["directional_metrics"]
            ),
            "- Diagnostic metrics: %s" % ", ".join(
                "`%s`" % metric for metric in campaign["diagnostic_metrics"]
            ),
            "- Primary-routability Pareto frontier: %s" % ", ".join(
                "`%s`" % method
                for method in campaign["primary_routability_pareto_frontier"]
            ),
            "- Full-routability Pareto frontier: %s" % ", ".join(
                "`%s`" % method
                for method in campaign["full_routability_pareto_frontier"]
            ),
            "",
        ])
        headers = ["Method"] + [
            "%s mean / worst" % metric for metric in campaign["required_metrics"]
        ] + [
            "%s diagnostic mean / worst" % metric
            for metric in campaign["diagnostic_metrics"]
        ] + [
            "Pareto", "Decision safe", "Decision evidence", "Routability safe",
            "Routability evidence", "Secondary-cost nonregression",
            "Secondary-cost budget",
            "Dominates HPWL", "HPWL dominates",
        ]
        lines.extend([
            "| " + " | ".join(headers) + " |",
            "|" + "---|" + "---:|" * (len(headers) - 1),
        ])
        for row in campaign["candidates"]:
            values = [row["method"]] + [
                format_delta(row["metrics"][metric])
                for metric in campaign["required_metrics"]
            ] + [
                format_delta(row["diagnostic_metrics"][metric])
                for metric in campaign["diagnostic_metrics"]
            ] + [
                str(row["method"] in campaign["pareto_frontier"]).lower(),
                str(row["decision_safe"]).lower(),
                str(row["decision_evidence_supported"]).lower(),
                str(row["routability_safe"]).lower(),
                str(row["routability_evidence_supported"]).lower(),
                str(row["routed_cost_safe"]).lower(),
                str(row["secondary_cost_within_budget"]).lower(),
                str(row["dominates_baseline"]).lower(),
                str(row["dominated_by_baseline"]).lower(),
            ]
            lines.append("| " + " | ".join(values) + " |")
        lines.extend([
            "",
            "### Per-design and worst-pair evidence",
            "",
            "Candidate and HPWL columns report absolute routed metrics; the value in "
            "parentheses is the paired delta.",
            "",
            "| Method | Metric | Overall candidate / HPWL | Per-design candidate / HPWL | Worst pair candidate / HPWL |",
            "|---|---|---:|---|---|",
        ])
        for row in campaign["candidates"]:
            evidence_groups = (
                (metric, row["metrics"][metric])
                for metric in campaign["required_metrics"]
            )
            diagnostic_groups = (
                (metric + " (diagnostic)", row["diagnostic_metrics"][metric])
                for metric in campaign["diagnostic_metrics"]
            )
            for metric, evidence in list(evidence_groups) + list(diagnostic_groups):
                case_results = evidence.get("case_results", [])
                per_design = "; ".join(
                    "%s %s" % (
                        item["case"], format_comparison(
                            item.get("mean_value"), item.get("mean_baseline"),
                            item.get("mean_delta"), item.get("mean_delta_pct"),
                        ),
                    )
                    for item in case_results
                ) or "n/a"
                overall = format_comparison(
                    evidence.get("mean_value"), evidence.get("mean_baseline"),
                    evidence.get("mean_delta"),
                    evidence.get("mean_delta")
                    if evidence.get("delta_unit") == "percent" else None,
                )
                worst_pair = "n/a"
                if evidence.get("worst_pair_case") is not None:
                    worst_pair = "%s/%s %s" % (
                        evidence["worst_pair_case"],
                        evidence.get("worst_pair_seed", "?"),
                        format_comparison(
                            evidence.get("worst_pair_value"),
                            evidence.get("worst_pair_baseline"),
                            evidence.get("worst_pair_delta"),
                            evidence.get("worst_pair_delta_pct"),
                        ),
                    )
                lines.append("| %s | %s | %s | %s | %s |" % (
                    row["method"], metric, overall, per_design, worst_pair,
                ))
        lines.append("")
    lines.extend([
        "## Decision",
        "",
        "- Consensus Pareto alternatives: %s" % (
            ", ".join("`%s`" % item for item in result["consensus_pareto_alternatives"])
            or "none"
        ),
        "- Strict winners: %s" % (
            ", ".join("`%s`" % item for item in result["strict_winners"])
            or "none"
        ),
        "- Robust all-metric decision winners: %s" % (
            ", ".join(
                "`%s`" % item for item in result["robust_decision_winners"]
            ) or "none"
        ),
        "- Robust routability winners: %s" % (
            ", ".join(
                "`%s`" % item for item in result["robust_routability_winners"]
            ) or "none"
        ),
        "- Cost-efficient routability winners: %s" % (
            ", ".join(
                "`%s`" % item
                for item in result["cost_efficient_routability_winners"]
            ) or "none"
        ),
        "- Routability-safe consensus alternatives: %s" % (
            ", ".join(
                "`%s`" % item
                for item in result["routability_safe_consensus_alternatives"]
            ) or "none"
        ),
        "- Secondary-cost-bounded routability winners: %s" % (
            ", ".join(
                "`%s`" % item
                for item in result["bounded_cost_routability_winners"]
            ) or "none"
        ),
        "- All-metric-safe consensus alternatives: %s" % (
            ", ".join(
                "`%s`" % item
                for item in result["decision_safe_consensus_alternatives"]
            ) or "none"
        ),
        "",
        "### Secondary-cost budget sensitivity",
        "",
        "| Method | Minimum mean budget | Minimum worst budget | "
        "Zero-baseline absolute increase | Eligible at current budget |",
        "|---|---:|---:|---:|---:|",
    ])
    for method, requirement in sorted(
        result["secondary_cost_requirements"].items()
    ):
        lines.append(
            "| %s | %.3f%% | %.3f%% | %s | %s |" % (
                method,
                requirement["minimum_mean_budget_pct"],
                requirement["minimum_worst_budget_pct"],
                str(requirement["zero_baseline_absolute_increase"]).lower(),
                str(requirement["eligible_under_policy_budget"]).lower(),
            )
        )
    lines.extend([
        "",
        "- Recommended method(s): %s" % ", ".join(
            "`%s`" % item for item in result["recommended_methods"]
        ),
        "",
    ])
    return "\n".join(lines)


def write_report(path, result):
    path.write_text(render_report(result))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", default="hpwl")
    parser.add_argument("--max-secondary-mean-pct", type=float, default=5.0)
    parser.add_argument("--max-secondary-worst-pct", type=float, default=10.0)
    parser.add_argument(
        "--require-cases", action="append", default=[],
        help="comma-separated exact case set for each --summary, in order",
    )
    parser.add_argument(
        "--require-seeds", action="append", default=[],
        help="comma-separated exact seed set for each --summary, in order",
    )
    args = parser.parse_args(argv)
    summaries = [json.loads(path.read_text()) for path in args.summary]
    result = rank_campaigns(
        summaries,
        [path.resolve() for path in args.summary],
        args.baseline,
        max_secondary_mean_pct=args.max_secondary_mean_pct,
        max_secondary_worst_pct=args.max_secondary_worst_pct,
        required_case_sets=(
            [
                {case.strip() for case in value.split(",") if case.strip()}
                for value in args.require_cases
            ]
            if args.require_cases else None
        ),
        required_seed_sets=(
            [
                {int(seed.strip()) for seed in value.split(",") if seed.strip()}
                for value in args.require_seeds
            ]
            if args.require_seeds else None
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    report = args.report or args.output.with_suffix(".md")
    report.parent.mkdir(parents=True, exist_ok=True)
    write_report(report, result)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
