#!/usr/bin/env python3

import unittest
from unittest import mock
from pathlib import Path
import tempfile

from tools.routability_audit_final import audit_ranking, audit_ranking_report
import tools.routability_audit_final as audit_final
from tools.routability_rank_golden import rank_campaigns, render_report, write_report


def metric(backend, name, method, mean, worst=None, percent=True):
    worst = mean if worst is None else worst
    baseline = 100.0
    return {
        "backend": backend,
        "metric": name,
        "method": method,
        "valid_count": 3,
        "percent_valid_count": 3 if percent else 0,
        "expected_count": 3,
        "mean_delta": mean,
        "worst_delta": worst,
        "mean_delta_pct": mean if percent else None,
        "worst_delta_pct": worst if percent else None,
        "mean_value": baseline + mean,
        "mean_baseline": baseline,
        "wins": int(mean < 0),
        "ties": int(mean == 0),
        "losses": int(mean > 0),
        "case_wins": int(mean < 0),
        "case_ties": int(mean == 0),
        "case_losses": int(mean > 0),
        "case_results": [{
            "case": "case_a", "valid_count": 3,
            "percent_valid_count": 3 if percent else 0,
            "mean_value": baseline + mean,
            "mean_baseline": baseline,
            "mean_delta": mean,
            "mean_delta_pct": mean if percent else None,
        }],
        "worst_case": "case_a",
        "worst_case_mean_delta": worst,
        "worst_case_mean_delta_pct": worst if percent else None,
        "worst_pair_case": "case_a",
        "worst_pair_seed": 3,
        "worst_pair_value": baseline + worst,
        "worst_pair_baseline": baseline,
        "worst_pair_delta": worst,
        "worst_pair_delta_pct": worst if percent else None,
        "statistically_supported": mean < 0,
        "consistent_improvement": mean < 0,
    }


def summary(backend, alternatives):
    directional = (
        ("horizontal_overflow", "vertical_overflow")
        if backend == "openroad" else
        ("horizontal_congestion", "vertical_congestion")
    )
    rows = []
    values = {"hpwl": (0.0, 0.0, 0.0, 0.0), **alternatives}
    for method, deltas in values.items():
        metric_values = {
            "drc_violations": deltas[0],
            directional[0]: deltas[1],
            directional[1]: deltas[2],
            "unrouted_nets": 0.0,
            "short_violations": 0.0,
            "wirelength": deltas[3],
            "vias": deltas[4] if len(deltas) > 4 else deltas[3],
        }
        if backend == "innovus":
            metric_values["connectivity_violations"] = 0.0
            metric_values["open_violations"] = 0.0
        for name, value in metric_values.items():
            rows.append(metric(
                backend, name, method, value,
                percent=name not in (
                    "drc_violations", "unrouted_nets", "short_violations",
                    "connectivity_violations", "open_violations",
                ),
            ))
        rows.append(metric("placement", "placement_hpwl", method, 0.0))
    return {
        "plugin_activation_contract": "validated",
        "expected_comparisons": 3,
        "validated_comparisons": 3,
        "expected_case_seeds": [
            {"case": "case_a", "seed": seed} for seed in (1, 2, 3)
        ],
        "validated_case_seeds": [
            {"case": "case_a", "seed": seed} for seed in (1, 2, 3)
        ],
        "incomplete_jobs": [],
        "missing_comparisons": [],
        "excluded": [],
        "baseline_gaps": [],
        "rows": rows,
    }


def add_innovus_overflow(data, alternatives):
    values = {"hpwl": (0.0, 0.0), **alternatives}
    for method, deltas in values.items():
        for name, value in zip(
            ("horizontal_overflow", "vertical_overflow"), deltas
        ):
            data["rows"].append(metric(
                "innovus", name, method, value, percent=False
            ))


class RoutabilityRankGoldenTest(unittest.TestCase):
    def test_placement_hpwl_is_diagnostic_only(self):
        data = summary("openroad", {
            "plugin": (0.0, -2.0, -3.0, 0.0, 1.0),
        })
        placement = next(
            row for row in data["rows"]
            if row["backend"] == "placement"
            and row["metric"] == "placement_hpwl"
            and row["method"] == "plugin"
        )
        placement.update(metric(
            "placement", "placement_hpwl", "plugin", 1000.0
        ))

        result = rank_campaigns([data], ["contest"])

        self.assertEqual(result["recommended_methods"], ["plugin"])
        self.assertNotIn(
            "placement_hpwl", result["campaigns"][0]["required_metrics"]
        )
        campaign = result["campaigns"][0]
        candidate = next(
            row for row in campaign["candidates"] if row["method"] == "plugin"
        )
        self.assertEqual(campaign["diagnostic_metrics"], ["placement_hpwl"])
        self.assertEqual(
            candidate["diagnostic_metrics"]["placement_hpwl"]["mean_delta"],
            1000.0,
        )
        self.assertNotIn("placement_hpwl:mean", candidate["objectives"])
        self.assertEqual(result["policy"]["diagnostic_metrics"], ["placement_hpwl"])
        self.assertFalse(
            result["policy"]["diagnostic_metrics_affect_decision"]
        )
        self.assertIn("placement_hpwl diagnostic mean / worst", render_report(result))

    def test_missing_placement_hpwl_is_rejected(self):
        data = summary("openroad", {
            "plugin": (0.0, -2.0, -3.0, 0.0, 1.0),
        })
        data["rows"] = [
            row for row in data["rows"]
            if not (
                row["backend"] == "placement"
                and row["metric"] == "placement_hpwl"
                and row["method"] == "plugin"
            )
        ]

        with self.assertRaisesRegex(
            ValueError, "lacks exact placement_hpwl method coverage"
        ):
            rank_campaigns([data], ["contest"])

    def test_incomplete_placement_hpwl_is_rejected(self):
        data = summary("openroad", {
            "plugin": (0.0, -2.0, -3.0, 0.0, 1.0),
        })
        placement = next(
            row for row in data["rows"]
            if row["backend"] == "placement"
            and row["metric"] == "placement_hpwl"
            and row["method"] == "plugin"
        )
        placement["valid_count"] = 2

        with self.assertRaisesRegex(
            ValueError, "lacks complete placement_hpwl coverage"
        ):
            rank_campaigns([data], ["contest"])

    def test_neutral_backend_does_not_veto_other_backend_routability_win(self):
        openroad = summary("openroad", {
            "plugin": (0.0, 0.0, 0.0, 0.0),
        })
        innovus = summary("innovus", {
            "plugin": (0.0, -2.0, -3.0, -1.0),
        })

        result = rank_campaigns(
            [openroad, innovus], ["contest", "real_designs"]
        )

        self.assertEqual(result["robust_routability_winners"], ["plugin"])
        self.assertEqual(
            result["cost_efficient_routability_winners"], ["plugin"]
        )
        self.assertEqual(result["recommended_methods"], ["plugin"])

    def test_unsupported_negative_mean_is_not_a_robust_winner(self):
        data = summary("innovus", {
            "plugin": (0.0, -2.0, -3.0, 1.0),
        })
        for row in data["rows"]:
            if row["method"] == "plugin":
                row["statistically_supported"] = False
                row["consistent_improvement"] = False

        result = rank_campaigns([data], ["real_designs"])

        self.assertEqual(result["robust_routability_winners"], [])
        self.assertEqual(result["recommended_methods"], ["hpwl"])

    def test_routed_wirelength_regression_is_a_primary_routability_veto(self):
        data = summary("openroad", {"plugin": (0.0, -2.0, -3.0, 1.0)})

        result = rank_campaigns([data], ["contest"])

        campaign = result["campaigns"][0]
        self.assertEqual(
            campaign["required_metrics"],
            [
                "drc_violations", "horizontal_overflow", "vertical_overflow",
                "unrouted_nets", "short_violations", "wirelength", "vias",
            ],
        )
        self.assertEqual(set(campaign["pareto_frontier"]), {"hpwl", "plugin"})
        self.assertEqual(
            campaign["full_routability_pareto_frontier"],
            campaign["pareto_frontier"],
        )
        self.assertEqual(
            campaign["primary_routability_pareto_frontier"],
            campaign["routability_pareto_frontier"],
        )
        self.assertEqual(result["strict_winners"], [])
        self.assertEqual(
            campaign["routability_metrics"],
            [
                "drc_violations", "horizontal_overflow", "vertical_overflow",
                "unrouted_nets", "short_violations", "wirelength", "vias",
            ],
        )
        self.assertEqual(
            campaign["primary_routability_metrics"],
            [
                "drc_violations", "horizontal_overflow", "vertical_overflow",
                "unrouted_nets", "short_violations", "wirelength",
            ],
        )
        self.assertEqual(
            campaign["secondary_routability_metrics"], ["vias"]
        )
        self.assertEqual(campaign["routed_cost_metrics"], ["vias"])
        self.assertEqual(
            result["policy"]["secondary_metrics"],
            ["vias"],
        )
        self.assertIn(
            "routed wirelength", result["policy"]["routability_metrics"]
        )
        self.assertEqual(result["robust_routability_winners"], [])
        self.assertEqual(result["cost_efficient_routability_winners"], [])
        self.assertEqual(result["robust_decision_winners"], [])
        self.assertEqual(result["recommended_methods"], ["hpwl"])

    def test_primary_regression_vetoes_even_when_routed_costs_improve(self):
        data = summary("openroad", {
            "plugin": (1.0, -2.0, -3.0, -5.0, -5.0),
        })

        result = rank_campaigns([data], ["contest"])

        self.assertEqual(result["robust_routability_winners"], [])
        self.assertEqual(result["cost_efficient_routability_winners"], [])
        self.assertEqual(result["recommended_methods"], ["hpwl"])

    def test_innovus_open_regression_is_an_independent_primary_veto(self):
        data = summary("innovus", {
            "plugin": (0.0, -2.0, -3.0, -1.0, 0.0),
        })
        open_row = next(
            row for row in data["rows"]
            if row["method"] == "plugin" and row["metric"] == "open_violations"
        )
        open_row.update({
            "mean_delta": 1.0,
            "worst_delta": 1.0,
            "mean_value": 1.0,
            "mean_baseline": 0.0,
            "worst_pair_value": 1.0,
            "worst_pair_baseline": 0.0,
            "statistically_supported": False,
            "consistent_improvement": False,
        })

        result = rank_campaigns([data], ["real_designs"])
        candidate = next(
            row for row in result["campaigns"][0]["candidates"]
            if row["method"] == "plugin"
        )

        self.assertIn(
            "open_violations",
            result["campaigns"][0]["primary_routability_metrics"],
        )
        self.assertFalse(candidate["routability_safe"])
        self.assertEqual(result["recommended_methods"], ["hpwl"])

    def test_innovus_missing_open_metric_is_rejected(self):
        data = summary("innovus", {
            "plugin": (0.0, -2.0, -3.0, -1.0, 0.0),
        })
        data["rows"] = [
            row for row in data["rows"]
            if row["metric"] != "open_violations"
        ]

        with self.assertRaisesRegex(
            ValueError, "lacks complete open_violations coverage"
        ):
            rank_campaigns([data], ["real_designs"])

    def test_worst_case_primary_gate_uses_only_numerical_tie_tolerance(self):
        data = summary("openroad", {
            "plugin": (0.0, -2.0, -3.0, -1.0, 0.0),
        })
        horizontal = next(
            row for row in data["rows"]
            if row["method"] == "plugin"
            and row["metric"] == "horizontal_overflow"
        )
        horizontal.update({
            "worst_delta": 5e-13,
            "worst_delta_pct": 5e-13,
            "worst_pair_delta": 5e-13,
            "worst_pair_delta_pct": 5e-13,
        })

        numerical_tie = rank_campaigns([data], ["contest"])

        self.assertEqual(numerical_tie["recommended_methods"], ["plugin"])
        self.assertTrue(
            next(
                row for row in numerical_tie["campaigns"][0]["candidates"]
                if row["method"] == "plugin"
            )["routability_safe"]
        )

        horizontal["worst_delta"] = 2e-12
        horizontal["worst_delta_pct"] = 2e-12
        material_regression = rank_campaigns([data], ["contest"])

        self.assertEqual(material_regression["recommended_methods"], ["hpwl"])

    def test_routed_wirelength_improvement_alone_is_not_a_routability_winner(self):
        data = summary("openroad", {
            "wirelength_only": (0.0, 0.0, 0.0, -5.0, -5.0),
        })

        result = rank_campaigns([data], ["contest"])

        self.assertEqual(result["robust_routability_winners"], [])
        self.assertEqual(result["recommended_methods"], ["hpwl"])

    def test_final_audit_independently_recomputes_ranking(self):
        openroad = summary("openroad", {
            "plugin": (0.0, -2.0, -3.0, -1.0, 0.0),
        })
        innovus = summary("innovus", {
            "plugin": (0.0, -1.0, -2.0, -0.5, 0.0),
        })
        summaries = {"openroad": openroad, "innovus": innovus}
        sources = ["contest", "real_designs"]
        ranking = rank_campaigns(
            [openroad, innovus], sources,
            required_case_sets=[{"case_a"}, {"case_a"}],
            required_seed_sets=[{1, 2, 3}, {1, 2, 3}],
        )
        expected_cases = {"openroad": ("case_a",), "innovus": ("case_a",)}
        with mock.patch.dict(
            audit_final.EXPECTED_GOLDEN_CASES, expected_cases, clear=True
        ), mock.patch.object(
            audit_final, "EXPECTED_GOLDEN_SEEDS", (1, 2, 3)
        ), mock.patch.object(
            audit_final, "EXPECTED_GOLDEN_METHODS", ("hpwl", "plugin")
        ):
            audit_ranking(ranking, summaries, recompute=True)
            ranking["bounded_cost_routability_winners"] = []
            ranking["recommended_methods"] = ["hpwl"]
            with self.assertRaisesRegex(
                ValueError, "independent summary recomputation"
            ):
                audit_ranking(ranking, summaries, recompute=True)

    def test_final_audit_binds_human_report_to_verified_ranking(self):
        data = summary("openroad", {
            "plugin": (0.0, -2.0, -3.0, -1.0, 0.0),
        })
        ranking = rank_campaigns([data], ["contest"])
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "ranking.md"
            report.write_text(render_report(ranking))
            audit_ranking_report(report, ranking)
            report.write_text(report.read_text().replace(
                "Recommended method(s)", "Unverified method(s)", 1
            ))
            with self.assertRaisesRegex(
                ValueError, "report does not match verified ranking JSON"
            ):
                audit_ranking_report(report, ranking)

    def test_via_cost_budget_rejects_pathological_routability_tradeoff(self):
        data = summary("openroad", {
            "expensive_plugin": (0.0, -2.0, -3.0, -1.0, 6.0),
        })

        result = rank_campaigns([data], ["contest"])

        self.assertEqual(
            result["robust_routability_winners"], ["expensive_plugin"]
        )
        self.assertEqual(
            result["cost_efficient_routability_winners"], ["expensive_plugin"]
        )
        self.assertEqual(result["bounded_cost_routability_winners"], [])
        self.assertEqual(result["recommended_methods"], ["hpwl"])
        requirement = result["secondary_cost_requirements"]["expensive_plugin"]
        self.assertEqual(requirement["minimum_mean_budget_pct"], 6.0)
        self.assertEqual(requirement["minimum_worst_budget_pct"], 6.0)
        self.assertFalse(requirement["eligible_under_policy_budget"])

        relaxed = rank_campaigns(
            [data], ["contest"], max_secondary_mean_pct=7.0
        )
        self.assertEqual(relaxed["recommended_methods"], ["expensive_plugin"])
        self.assertTrue(
            relaxed["secondary_cost_requirements"]["expensive_plugin"][
                "eligible_under_policy_budget"
            ]
        )

    def test_zero_baseline_secondary_cost_increase_cannot_use_percent_budget(self):
        data = summary("openroad", {
            "plugin": (0.0, -2.0, -3.0, -1.0, 1.0),
        })
        via = next(
            row for row in data["rows"]
            if row["method"] == "plugin" and row["metric"] == "vias"
        )
        via.update({
            "percent_valid_count": 0,
            "mean_delta": 2.0,
            "worst_delta": 3.0,
            "mean_delta_pct": None,
            "worst_delta_pct": None,
        })

        result = rank_campaigns([data], ["contest"])
        requirement = result["secondary_cost_requirements"]["plugin"]

        self.assertTrue(requirement["zero_baseline_absolute_increase"])
        self.assertFalse(requirement["eligible_under_policy_budget"])
        self.assertEqual(result["recommended_methods"], ["hpwl"])

    def test_via_cost_selects_between_equal_routability_winners(self):
        data = summary("openroad", {
            "higher_route_cost": (0.0, -2.0, -3.0, -1.0, -1.0),
            "lower_route_cost": (0.0, -2.0, -3.0, -1.0, -2.0),
        })

        result = rank_campaigns([data], ["contest"])

        self.assertEqual(
            result["robust_routability_winners"],
            ["higher_route_cost", "lower_route_cost"],
        )
        self.assertEqual(
            result["cost_efficient_routability_winners"],
            ["lower_route_cost"],
        )
        self.assertEqual(result["robust_decision_winners"], ["lower_route_cost"])
        self.assertEqual(result["recommended_methods"], ["lower_route_cost"])

    def test_backend_local_cost_disagreement_keeps_both_robust_candidates(self):
        openroad = summary("openroad", {
            "better_in_innovus": (0.0, -2.0, -3.0, 0.0, 1.0),
            "better_in_openroad": (0.0, -2.0, -3.0, 0.0, 0.0),
        })
        innovus = summary("innovus", {
            "better_in_innovus": (0.0, -2.0, -3.0, 0.0, 0.0),
            "better_in_openroad": (0.0, -2.0, -3.0, 0.0, 1.0),
        })

        result = rank_campaigns(
            [openroad, innovus], ["contest", "real_designs"]
        )

        expected = ["better_in_innovus", "better_in_openroad"]
        self.assertEqual(result["robust_routability_winners"], expected)
        self.assertEqual(result["cost_efficient_routability_winners"], expected)
        self.assertEqual(result["recommended_methods"], expected)

    def test_accepts_only_cross_backend_pareto_dominator(self):
        openroad = summary("openroad", {
            "winner": (0.0, -2.0, -3.0, -1.0),
            "tradeoff": (0.0, -4.0, 1.0, -2.0),
        })
        innovus = summary("innovus", {
            "winner": (-1.0, -1.0, -2.0, -0.5),
            "tradeoff": (1.0, -5.0, -5.0, -5.0),
        })

        result = rank_campaigns(
            [openroad, innovus], ["contest_openroad", "real_innovus"]
        )

        self.assertFalse(result["policy"]["numeric_backend_mixing"])
        self.assertFalse(result["policy"]["numeric_metric_scalarization"])
        self.assertIn("routed wirelength", result["policy"]["decision_metrics"])
        self.assertEqual(result["strict_winners"], ["winner"])
        self.assertEqual(result["recommended_methods"], ["winner"])
        self.assertNotIn("tradeoff", result["drc_safe_consensus_alternatives"])

    def test_uses_overflow_and_congestion_when_innovus_reports_both(self):
        data = summary("innovus", {"plugin": (0.0, -1.0, -2.0, -0.5)})
        add_innovus_overflow(data, {"plugin": (-3.0, -4.0)})

        result = rank_campaigns([data], ["real_innovus"])

        self.assertEqual(
            result["campaigns"][0]["directional_metrics"],
            [
                "horizontal_overflow", "vertical_overflow",
                "horizontal_congestion", "vertical_congestion",
            ],
        )
        self.assertEqual(result["recommended_methods"], ["plugin"])

    def test_zero_baseline_drc_uses_absolute_delta(self):
        data = summary("openroad", {"plugin": (2.0, -1.0, -1.0, -1.0)})

        result = rank_campaigns([data], ["contest"])
        plugin = next(
            row for row in result["campaigns"][0]["candidates"]
            if row["method"] == "plugin"
        )

        self.assertEqual(plugin["metrics"]["drc_violations"]["delta_unit"], "absolute")
        self.assertTrue(plugin["drc_worst_regression"])
        self.assertEqual(result["recommended_methods"], ["hpwl"])

    def test_dominated_baseline_dominator_is_not_recommended(self):
        data = summary("openroad", {
            "best": (0.0, -2.0, -2.0, -2.0),
            "also_beats_hpwl": (0.0, -1.0, -1.0, -1.0),
        })

        result = rank_campaigns([data], ["contest"])

        self.assertEqual(result["strict_winners"], ["best"])
        self.assertEqual(result["recommended_methods"], ["best"])

    def test_rejects_incomplete_golden_campaign(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -1.0, -1.0)})
        data["incomplete_jobs"] = [{"status": "running"}]

        with self.assertRaisesRegex(ValueError, "not a complete"):
            rank_campaigns([data], ["contest"])

    def test_rejects_duplicate_backend_metric_method_rows(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -1.0, -1.0)})
        duplicate = next(
            row for row in data["rows"]
            if row["method"] == "plugin" and row["metric"] == "wirelength"
        )
        data["rows"].append(dict(duplicate))

        with self.assertRaisesRegex(ValueError, "duplicate golden metric rows"):
            rank_campaigns([data], ["contest"])

    def test_rejects_mismatched_cross_backend_method_sets(self):
        openroad = summary("openroad", {
            "plugin": (0.0, -1.0, -1.0, -1.0),
        })
        innovus = summary("innovus", {
            "plugin": (0.0, -1.0, -1.0, -1.0),
            "omitted_from_openroad": (0.0, -2.0, -2.0, -2.0),
        })

        with self.assertRaisesRegex(ValueError, "identical method sets"):
            rank_campaigns([openroad, innovus], ["contest", "real_designs"])

    def test_rejects_incomplete_required_design_set(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -1.0, -1.0)})

        with self.assertRaisesRegex(ValueError, "does not match required cases"):
            rank_campaigns(
                [data], ["contest"],
                required_case_sets=[{"case_a", "case_b"}],
            )

    def test_rejects_inconsistent_metric_case_coverage(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -1.0, -1.0)})
        row = next(
            item for item in data["rows"]
            if item["method"] == "plugin" and item["metric"] == "wirelength"
        )
        row["case_results"][0]["case"] = "case_b"

        with self.assertRaisesRegex(ValueError, "inconsistent per-design coverage"):
            rank_campaigns([data], ["contest"])

    def test_rejects_incomplete_required_seed_matrix(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -1.0, -1.0)})

        with self.assertRaisesRegex(ValueError, "does not match required matrix"):
            rank_campaigns(
                [data], ["contest"], required_case_sets=[{"case_a"}],
                required_seed_sets=[{1, 2, 3, 4}],
            )

    def test_rejects_summary_with_duplicate_case_seed_rows(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -1.0, -1.0)})
        data["validated_case_seeds"].append({"case": "case_a", "seed": 3})

        with self.assertRaisesRegex(ValueError, "not a complete"):
            rank_campaigns([data], ["contest"])

    def test_rejects_candidate_without_routed_wirelength(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -1.0, -1.0)})
        data["rows"] = [
            row for row in data["rows"]
            if not (
                row["method"] == "plugin" and row["metric"] == "wirelength"
            )
        ]

        with self.assertRaisesRegex(
            ValueError, "plugin lacks complete wirelength coverage"
        ):
            rank_campaigns([data], ["contest"])

    def test_report_includes_every_required_metric_delta(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -2.0, 0.5)})
        result = rank_campaigns([data], ["contest"])
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "ranking.md"
            write_report(report, result)
            text = report.read_text()

        self.assertIn("drc_violations mean / worst", text)
        self.assertIn("horizontal_overflow mean / worst", text)
        self.assertIn("vertical_overflow mean / worst", text)
        self.assertIn("unrouted_nets mean / worst", text)
        self.assertIn("short_violations mean / worst", text)
        self.assertIn("wirelength mean / worst", text)
        self.assertIn("vias mean / worst", text)
        self.assertIn(
            "Full routability vector: detailed-route DRC", text
        )
        self.assertIn(
            "Primary routability metrics: detailed-route DRC", text
        )
        self.assertIn("Secondary routed-cost metric: vias", text)
        self.assertIn("Primary-routability Pareto frontier", text)
        self.assertIn("Full-routability Pareto frontier", text)
        self.assertIn("-1.000% / -1.000%", text)
        self.assertIn("Per-design and worst-pair evidence", text)
        self.assertIn("Secondary-cost budget sensitivity", text)
        self.assertIn("case_a/3", text)
        self.assertIn("Overall candidate / HPWL", text)
        self.assertIn("99 / 100 (-1.000%)", text)
        digest = result["campaigns"][0]["summary_content_sha256"]
        self.assertEqual(len(digest), 64)
        self.assertIn("Summary content SHA-256: `%s`" % digest, text)

    def test_rejects_missing_absolute_metric_evidence(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -2.0, 0.5)})
        row = next(
            item for item in data["rows"]
            if item["method"] == "plugin" and item["metric"] == "wirelength"
        )
        del row["mean_value"]

        with self.assertRaisesRegex(ValueError, "absolute evidence"):
            rank_campaigns([data], ["contest"])

    def test_rejects_missing_per_design_absolute_evidence(self):
        data = summary("openroad", {"plugin": (0.0, -1.0, -2.0, 0.5)})
        row = next(
            item for item in data["rows"]
            if item["method"] == "plugin" and item["metric"] == "wirelength"
        )
        row["case_results"] = []

        with self.assertRaisesRegex(ValueError, "per-design absolute evidence"):
            rank_campaigns([data], ["contest"])


if __name__ == "__main__":
    unittest.main()
