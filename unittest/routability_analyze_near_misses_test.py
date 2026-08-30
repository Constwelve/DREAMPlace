#!/usr/bin/env python3

import unittest

from tools.routability_analyze_near_misses import (
    analyze_near_misses,
    render_markdown,
)
from tools.routability_select_survivors import (
    ROUTABILITY_BACKEND_CONSTRAINTS,
    routability_metric_profile,
)


def metric(backend, name, method, value):
    return {
        "backend": backend,
        "metric": name,
        "method": method,
        "valid_count": 2,
        "mean_delta_pct": value,
        "median_delta_pct": value,
        "worst_delta_pct": value,
        "mean_delta": value,
        "median_delta": value,
        "worst_delta": value,
        "percent_valid_count": 2,
        "worst_pair_case": "test1",
        "worst_pair_seed": 2000,
        "worst_pair_delta": value,
        "worst_pair_delta_pct": value,
        "worst_case": "test1",
        "case_results": [{"case": "test1", "mean_delta_pct": value}],
    }


def summary():
    rows = []
    values = {
        "a": {
            "gpugr": [-2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "rudy": [0.0, 0.0],
        },
        "b": {
            "gpugr": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "rudy": [-2.0, 0.0],
        },
        "c": {
            "gpugr": [-1.0, -2.0, 0.0, 0.0, 0.0, 0.0],
            "rudy": [-1.0, -2.0],
        },
    }
    for method, backends in values.items():
        rows.append(metric("placement", "placement_hpwl", method, 0.0))
        for backend, metric_values in backends.items():
            for name, value in zip(
                ROUTABILITY_BACKEND_CONSTRAINTS[backend]["metrics"],
                metric_values,
            ):
                rows.append(metric(backend, name, method, value))
    raw_fallback = next(
        row for row in rows
        if row["method"] == "c" and row["backend"] == "gpugr"
        and row["metric"] == "rc_hor"
    )
    raw_fallback["percent_valid_count"] = 1
    raw_fallback["worst_delta_pct"] = -50.0
    raw_fallback["worst_delta"] = 0.25
    return {
        "expected_comparisons": 2,
        "validated_comparisons": 2,
        "incomplete_jobs": [],
        "missing_comparisons": [],
        "excluded": [],
        "baseline_gaps": [],
        "rows": rows,
    }


STATES = {
    method: {
        "statuses": ["active", "active"],
        "plugins": {"plugin_%s" % method},
        "rows": 2,
    }
    for method in ("a", "b", "c")
}


class RoutabilityAnalyzeNearMissesTest(unittest.TestCase):
    def mixed_activation_state(self):
        return {
            "statuses": ["selected_no_activation", "active"],
            "plugins": {"plugin_a"},
            "rows": 2,
            "observations": [
                {"case": "test1", "seed": "1000",
                 "status": "selected_no_activation"},
                {"case": "test2", "seed": "1000", "status": "active"},
            ],
        }

    def mixed_activation_effects(self):
        return {
            "expected_comparisons": 2,
            "methods": {"a": {
                ("test1", "1000"): {
                    "active": False, "changed_from_baseline": False,
                },
                ("test2", "1000"): {
                    "active": True, "changed_from_baseline": True,
                },
            }},
        }

    def test_hash_proven_gated_noop_remains_diagnostically_eligible(self):
        states = dict(STATES)
        states["a"] = self.mixed_activation_state()

        result = analyze_near_misses(
            summary(), states,
            placement_effects=self.mixed_activation_effects(),
        )
        method = next(row for row in result["methods"] if row["method"] == "a")

        self.assertTrue(method["eligible"])
        self.assertEqual(method["structural_reasons"], [])
        self.assertTrue(result["policy"]["placement_effect_audit_used"])

    def test_gated_noop_without_identity_audit_remains_ineligible(self):
        states = dict(STATES)
        states["a"] = self.mixed_activation_state()

        result = analyze_near_misses(summary(), states)
        method = next(row for row in result["methods"] if row["method"] == "a")

        self.assertFalse(method["eligible"])
        self.assertIn(
            "gated inactive comparisons lack placement-effect identity evidence",
            method["structural_reasons"],
        )

    def test_backend_local_frontiers_and_set_intersection(self):
        result = analyze_near_misses(summary(), STATES)

        self.assertEqual(
            result["backends"]["gpugr"]["mean_pareto_frontier"],
            ["a", "c"],
        )
        self.assertEqual(
            result["backends"]["rudy"]["mean_pareto_frontier"],
            ["b", "c"],
        )
        self.assertEqual(
            result["cross_backend_frontier_intersection"]["mean"], ["c"]
        )
        self.assertFalse(result["policy"]["numeric_backend_mixing"])
        self.assertFalse(result["policy"]["selection_or_admission_decision"])
        self.assertEqual(
            result["plugin_frontiers"]["plugin_c"]
            ["cross_backend_frontier_intersection"]["mean"],
            ["c"],
        )
        self.assertEqual(
            result["plugin_frontiers"]["plugin_a"]["backends"]["gpugr"]
            ["mean_pareto_frontier"],
            ["a"],
        )

    def test_plugin_feedback_proxy_frontiers_remain_separate(self):
        states = {
            method: {"statuses": ["active", "active"],
                     "plugins": {"shared"}, "rows": 2}
            for method in ("a", "b", "c")
        }
        provenance = {
            "a": {"plugins": ["shared"], "proxy": "rudy"},
            "b": {"plugins": ["shared"], "proxy": "gpugr"},
            "c": {"plugins": ["shared"], "proxy": "gpugr"},
        }
        result = analyze_near_misses(
            summary(), states, preset_provenance=provenance
        )

        groups = result["plugin_proxy_frontiers"]["shared"]
        self.assertEqual(set(groups), {"rudy", "gpugr"})
        self.assertEqual(
            groups["rudy"]["backends"]["gpugr"]["mean_pareto_frontier"],
            ["a"],
        )
        self.assertEqual(
            {row["method"]: row["feedback_proxy"] for row in result["methods"]},
            {"a": "rudy", "b": "gpugr", "c": "gpugr"},
        )

    def test_zero_baseline_worst_regression_uses_raw_delta(self):
        result = analyze_near_misses(summary(), STATES)
        method = next(row for row in result["methods"] if row["method"] == "c")

        self.assertIn(
            "gpugr:rc_hor", method["backends"]["gpugr"]["worst_regressions"]
        )
        self.assertFalse(
            method["backends"]["gpugr"]["meets_zero_worst_regression_gate"]
        )
        evidence = method["backends"]["gpugr"]["metric_evidence"][
            "gpugr:rc_hor"
        ]
        self.assertEqual(evidence["objective_basis"], "raw")
        self.assertEqual(evidence["worst_pair_case"], "test1")
        self.assertEqual(evidence["worst_pair_seed"], 2000)

    def test_absolute_directional_metadata_uses_full_profile_metrics(self):
        data = summary()
        profile = routability_metric_profile("absolute_directional_v2")
        existing = {
            (row["backend"], row["metric"], row["method"])
            for row in data["rows"]
        }
        for method in STATES:
            for backend, constraint in profile["constraints"].items():
                for name in constraint["metrics"]:
                    key = (backend, name, method)
                    if key not in existing:
                        data["rows"].append(metric(backend, name, method, 0.0))

        result = analyze_near_misses(
            data, STATES, metric_profile="absolute_directional_v2"
        )

        for backend, constraint in profile["constraints"].items():
            self.assertEqual(
                result["backends"][backend]["metrics"],
                ["%s:%s" % (backend, name) for name in constraint["metrics"]],
            )

    def test_absolute_directional_v3_frontier_excludes_normalized_scores(self):
        data = summary()
        profile = routability_metric_profile("absolute_directional_v3")
        existing = {
            (row["backend"], row["metric"], row["method"])
            for row in data["rows"]
        }
        for method in STATES:
            for backend, constraint in profile["constraints"].items():
                for name in constraint["metrics"]:
                    key = (backend, name, method)
                    if key not in existing:
                        data["rows"].append(metric(backend, name, method, 0.0))

        result = analyze_near_misses(
            data, STATES, metric_profile="absolute_directional_v3"
        )

        gpugr_metrics = result["backends"]["gpugr"]["metrics"]
        self.assertIn("gpugr:horizontal_utilization_p99", gpugr_metrics)
        self.assertIn("gpugr:vertical_ace", gpugr_metrics)
        self.assertNotIn("gpugr:horizontal_congestion_score", gpugr_metrics)
        self.assertNotIn("gpugr:vertical_congestion_score_p99", gpugr_metrics)

    def test_rudy_worst_regression_is_diagnostic_not_a_zero_regression_gate(self):
        data = summary()
        row = next(
            row for row in data["rows"]
            if row["method"] == "c" and row["backend"] == "rudy"
            and row["metric"] == "congestion_score"
        )
        row["worst_delta"] = 1.0
        row["worst_delta_pct"] = 1.0

        result = analyze_near_misses(data, STATES)
        method = next(row for row in result["methods"] if row["method"] == "c")
        rudy = method["backends"]["rudy"]

        self.assertIn("rudy:congestion_score", rudy["worst_regressions"])
        self.assertEqual(rudy["guarded_worst_regressions"], [])
        self.assertTrue(rudy["meets_zero_worst_regression_gate"])
        self.assertEqual(result["policy"]["worst_regression_backends"], ["gpugr"])

    def test_rejects_incomplete_campaign(self):
        data = summary()
        data["validated_comparisons"] = 1

        with self.assertRaisesRegex(ValueError, "complete validated campaign"):
            analyze_near_misses(data, STATES)

    def test_report_labels_output_as_diagnostic(self):
        text = render_markdown(analyze_near_misses(summary(), STATES))

        self.assertIn("development-only diagnostic", text)
        self.assertIn("No metric values are combined across backends", text)


if __name__ == "__main__":
    unittest.main()
