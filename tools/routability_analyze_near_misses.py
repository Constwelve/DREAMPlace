#!/usr/bin/env python3
"""Analyze proxy-screen near misses without scalarizing evaluator backends."""

import argparse
import json
from pathlib import Path

try:
    from tools.routability_select_survivors import (
        complete_summary,
        dominates,
        load_placement_effects,
        load_plugin_states,
        objective_delta,
        plugin_activation_reasons,
        ROUTABILITY_METRIC_PROFILES,
        routability_metric_profile,
        worst_objective_delta,
    )
except ModuleNotFoundError:
    from routability_select_survivors import (
        complete_summary,
        dominates,
        load_placement_effects,
        load_plugin_states,
        objective_delta,
        plugin_activation_reasons,
        ROUTABILITY_METRIC_PROFILES,
        routability_metric_profile,
        worst_objective_delta,
    )


def _metric_key(backend, metric):
    return "%s:%s" % (backend, metric)


def _frontier(records, vector_key):
    eligible = [row for row in records if row["eligible"]]
    if not eligible:
        return []
    objectives = list(eligible[0][vector_key])
    return sorted(
        row["method"] for row in eligible
        if not any(
            other is not row
            and dominates(other[vector_key], row[vector_key], objectives)
            for other in eligible
        )
    )


def analyze_near_misses(data, plugin_states, baseline="hpwl",
                        preset_provenance=None, metric_profile="legacy",
                        placement_effects=None):
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
    profile = routability_metric_profile(metric_profile)
    constraints = profile["constraints"]
    guarded_backends = set(profile["worst_regression_backends"])
    records = []
    backend_records = {backend: [] for backend in constraints}

    for method in methods:
        state = plugin_states.get(method, {
            "statuses": [], "plugins": set(), "rows": 0,
            "observations": [],
        })
        structural_reasons = (
            plugin_activation_reasons(
                state,
                expected,
                placement_effects=placement_effects,
                method=method,
            )
            if state["plugins"] else []
        )
        record = {
            "method": method,
            "plugins": sorted(state["plugins"]),
            "feedback_proxy": None,
            "eligible": not structural_reasons,
            "structural_reasons": structural_reasons,
            "backends": {},
        }
        if preset_provenance and method in preset_provenance:
            record["preset_provenance"] = preset_provenance[method]
            record["feedback_proxy"] = preset_provenance[method].get("proxy")

        for backend, constraint in constraints.items():
            metric_rows = {}
            missing = []
            for metric in constraint["metrics"]:
                row = index.get((backend, metric, method))
                if not row or int(row.get("valid_count", 0)) != expected:
                    missing.append(metric)
                else:
                    metric_rows[metric] = row
            if missing:
                reason = "missing full %s coverage: %s" % (
                    backend.upper(), ", ".join(missing)
                )
                record["structural_reasons"].append(reason)
                record["eligible"] = False
                record["backends"][backend] = {"missing_metrics": missing}
                continue

            means = {
                _metric_key(backend, metric): objective_delta(
                    row,
                    use_median=(backend == "rudy" and metric == "overflow_sum"),
                )
                for metric, row in metric_rows.items()
            }
            worst = {
                _metric_key(backend, metric): worst_objective_delta(row)
                for metric, row in metric_rows.items()
            }
            metric_evidence = {}
            for metric, row in metric_rows.items():
                name = _metric_key(backend, metric)
                percent_complete = (
                    row.get("percent_valid_count", row.get("valid_count"))
                    == row.get("valid_count")
                )
                metric_evidence[name] = {
                    "mean_objective": means[name],
                    "worst_objective": worst[name],
                    "objective_basis": "percent" if percent_complete else "raw",
                    "worst_pair_case": row.get("worst_pair_case"),
                    "worst_pair_seed": row.get("worst_pair_seed"),
                    "worst_pair_delta": row.get("worst_pair_delta"),
                    "worst_pair_delta_pct": row.get("worst_pair_delta_pct"),
                    "worst_case": row.get("worst_case"),
                    "case_results": row.get("case_results", []),
                }
            diagnostics = {
                "mean_objectives": means,
                "worst_objectives": worst,
                "metric_evidence": metric_evidence,
                "mean_improvements": sorted(
                    name for name, value in means.items() if value < 0
                ),
                "worst_regressions": sorted(
                    name for name, value in worst.items() if value > 0
                ),
                "guarded_worst_regressions": sorted(
                    name for name, value in worst.items()
                    if backend in guarded_backends and value > 0
                ),
                "meets_improvement_gate": sum(
                    value < 0 for value in means.values()
                ) >= constraint["minimum_improvements"],
                "meets_zero_worst_regression_gate": (
                    backend not in guarded_backends
                    or all(value <= 0 for value in worst.values())
                ),
            }
            record["backends"][backend] = diagnostics
        for backend, diagnostics in record["backends"].items():
            if "missing_metrics" in diagnostics:
                continue
            backend_records[backend].append({
                "method": method,
                "plugins": record["plugins"],
                "feedback_proxy": record["feedback_proxy"],
                "eligible": record["eligible"],
                "mean_vector": diagnostics["mean_objectives"],
                "worst_vector": diagnostics["worst_objectives"],
            })
        records.append(record)

    backends = {}
    for backend, rows in backend_records.items():
        backends[backend] = {
            "metrics": [
                _metric_key(backend, metric)
                for metric in constraints[backend]["metrics"]
            ],
            "mean_pareto_frontier": _frontier(rows, "mean_vector"),
            "worst_pareto_frontier": _frontier(rows, "worst_vector"),
        }
    backend_names = sorted(backends)
    mean_sets = [set(backends[name]["mean_pareto_frontier"]) for name in backend_names]
    worst_sets = [set(backends[name]["worst_pareto_frontier"]) for name in backend_names]
    atomic_plugins = sorted({
        row["plugins"][0] for row in records
        if row["eligible"] and len(row["plugins"]) == 1
    })
    plugin_frontiers = {}
    for plugin in atomic_plugins:
        per_backend = {}
        for backend in backend_names:
            plugin_rows = [
                row for row in backend_records[backend]
                if row["plugins"] == [plugin]
            ]
            per_backend[backend] = {
                "mean_pareto_frontier": _frontier(plugin_rows, "mean_vector"),
                "worst_pareto_frontier": _frontier(plugin_rows, "worst_vector"),
            }
        plugin_mean_sets = [
            set(per_backend[name]["mean_pareto_frontier"])
            for name in backend_names
        ]
        plugin_worst_sets = [
            set(per_backend[name]["worst_pareto_frontier"])
            for name in backend_names
        ]
        plugin_frontiers[plugin] = {
            "backends": per_backend,
            "cross_backend_frontier_intersection": {
                "mean": sorted(set.intersection(*plugin_mean_sets))
                    if plugin_mean_sets else [],
                "worst": sorted(set.intersection(*plugin_worst_sets))
                    if plugin_worst_sets else [],
            },
        }
    plugin_proxy_frontiers = {}
    for plugin in atomic_plugins:
        feedback_proxies = sorted({
            row["feedback_proxy"] for row in records
            if row["eligible"] and row["plugins"] == [plugin]
            and row.get("feedback_proxy")
        })
        groups = {}
        for feedback_proxy in feedback_proxies:
            per_backend = {}
            for backend in backend_names:
                group_rows = [
                    row for row in backend_records[backend]
                    if row["plugins"] == [plugin]
                    and row.get("feedback_proxy") == feedback_proxy
                ]
                per_backend[backend] = {
                    "mean_pareto_frontier": _frontier(group_rows, "mean_vector"),
                    "worst_pareto_frontier": _frontier(group_rows, "worst_vector"),
                }
            group_mean_sets = [
                set(per_backend[name]["mean_pareto_frontier"])
                for name in backend_names
            ]
            group_worst_sets = [
                set(per_backend[name]["worst_pareto_frontier"])
                for name in backend_names
            ]
            groups[feedback_proxy] = {
                "backends": per_backend,
                "cross_backend_frontier_intersection": {
                    "mean": sorted(set.intersection(*group_mean_sets))
                        if group_mean_sets else [],
                    "worst": sorted(set.intersection(*group_worst_sets))
                        if group_worst_sets else [],
                },
            }
        if groups:
            plugin_proxy_frontiers[plugin] = groups
    result = {
        "baseline": baseline,
        "expected_comparisons": expected,
        "policy": {
            "complete_campaign_required": True,
            "numeric_backend_mixing": False,
            "metric_profile": metric_profile,
            "worst_regression_backends": sorted(guarded_backends),
            "placement_effect_audit_used": placement_effects is not None,
            "selection_or_admission_decision": False,
            "description": (
                "Backend-local Pareto diagnostics for constructing a new "
                "development-only tuning grid"
            ),
        },
        "backends": backends,
        "cross_backend_frontier_intersection": {
            "mean": sorted(set.intersection(*mean_sets)) if mean_sets else [],
            "worst": sorted(set.intersection(*worst_sets)) if worst_sets else [],
        },
        "plugin_frontiers": plugin_frontiers,
        "plugin_proxy_frontiers": plugin_proxy_frontiers,
        "methods": records,
    }
    return result


def render_markdown(result):
    lines = [
        "# Routability Proxy Near-Miss Analysis",
        "",
        "This is a development-only diagnostic. It does not select methods or "
        "admit them to held-out or golden routing.",
        "",
    ]
    for backend, evidence in sorted(result["backends"].items()):
        lines.extend([
            "## %s" % backend.upper(),
            "",
            "- Mean Pareto frontier: %s" % (
                ", ".join("`%s`" % item for item in evidence["mean_pareto_frontier"])
                or "none"
            ),
            "- Worst-case Pareto frontier: %s" % (
                ", ".join("`%s`" % item for item in evidence["worst_pareto_frontier"])
                or "none"
            ),
            "",
        ])
    lines.extend([
        "## Cross-Backend Set Intersection",
        "",
        "No metric values are combined across backends.",
        "",
        "- Mean-frontier intersection: %s" % (
            ", ".join(
                "`%s`" % item
                for item in result["cross_backend_frontier_intersection"]["mean"]
            ) or "none"
        ),
        "- Worst-frontier intersection: %s" % (
            ", ".join(
                "`%s`" % item
                for item in result["cross_backend_frontier_intersection"]["worst"]
            ) or "none"
        ),
        "",
        "## Gate Diagnostics",
        "",
        "| Method | Backend | Mean improvements | Worst regressions |",
        "|---|---|---:|---:|",
    ])
    for method in result["methods"]:
        for backend, evidence in sorted(method["backends"].items()):
            if "missing_metrics" in evidence:
                lines.append("| `%s` | %s | missing | missing |" % (
                    method["method"], backend,
                ))
                continue
            lines.append("| `%s` | %s | %d | %d |" % (
                method["method"], backend,
                len(evidence["mean_improvements"]),
                len(evidence["worst_regressions"]),
            ))
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--preset-manifest", type=Path)
    parser.add_argument("--placement-effect-audit", type=Path)
    parser.add_argument("--baseline", default="hpwl")
    parser.add_argument(
        "--metric-profile", choices=tuple(sorted(ROUTABILITY_METRIC_PROFILES)),
        default="legacy",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    raw = args.raw or args.summary.parent / "screening_raw.csv"
    provenance = None
    if args.preset_manifest:
        provenance = json.loads(args.preset_manifest.read_text()).get("generated", {})
    placement_effect_audit = args.placement_effect_audit
    if placement_effect_audit is None:
        sibling_audit = args.summary.parent / "placement_effect_audit.json"
        if sibling_audit.is_file():
            placement_effect_audit = sibling_audit
    result = analyze_near_misses(
        json.loads(args.summary.read_text()),
        load_plugin_states(raw),
        baseline=args.baseline,
        preset_provenance=provenance,
        metric_profile=args.metric_profile,
        placement_effects=(
            load_placement_effects(placement_effect_audit)
            if placement_effect_audit else None
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
