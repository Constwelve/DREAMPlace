#!/usr/bin/env python3

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_audit_partial_elimination import audit_partial_elimination
from tools.routability_select_survivors import routability_metric_profile


def summary(worst_by_method=None):
    worst_by_method = worst_by_method or {}
    rows = []
    for method in ("hpwl", "regresses", "possible"):
        rows.append({
            "backend": "placement",
            "metric": "placement_hpwl",
            "method": method,
            "valid_count": 3,
            "mean_delta": 0.0,
            "mean_delta_pct": 0.0,
            "median_delta": 0.0,
            "median_delta_pct": 0.0,
            "worst_delta": 0.0,
            "worst_delta_pct": 0.0,
        })
        if method == "hpwl":
            continue
        for backend, metric in routability_metric_profile(
            "absolute_directional_v2"
        )["primary"]:
            worst = worst_by_method.get((method, backend, metric), 0.0)
            mean = -1.0 if metric in ("gr_wirelength", "overflow_sum") else 0.0
            rows.append({
                "backend": backend,
                "metric": metric,
                "method": method,
                "valid_count": 3,
                "percent_valid_count": 3,
                "mean_delta": mean,
                "mean_delta_pct": mean,
                "median_delta": mean,
                "median_delta_pct": mean,
                "worst_delta": worst,
                "worst_delta_pct": worst,
            })
    return {
        "baseline": "hpwl",
        "expected_comparisons": 6,
        "validated_comparisons": 3,
        "excluded": [],
        "baseline_gaps": [],
        "rows": rows,
    }


def state(statuses, plugin="net_weighting"):
    return {
        "statuses": list(statuses),
        "plugins": {plugin},
        "rows": len(statuses),
        "observations": [
            {"case": "case_%d" % index, "seed": "1000", "status": status}
            for index, status in enumerate(statuses)
        ],
    }


def placement_effects(method, statuses, changed_inactive=False,
                      malformed_active=False):
    rows = {}
    for index, status in enumerate(statuses):
        active = status == "active"
        rows[("case_%d" % index, "1000")] = {
            "active": False if malformed_active and active else active,
            "changed_from_baseline": (
                True if active else bool(changed_inactive)
            ),
        }
    return {
        "expected_comparisons": len(statuses),
        "methods": {method: rows},
    }


class RoutabilityAuditPartialEliminationTest(unittest.TestCase):
    def test_eliminates_only_observed_positive_worst_regression(self):
        data = summary({("regresses", "gpugr", "gr_wirelength"): 0.01})
        states = {
            method: {
                "statuses": ["active"] * 3,
                "plugins": {"local_gradient"},
                "rows": 3,
            }
            for method in ("regresses", "possible")
        }
        provenance = {
            method: {"plugins": ["local_gradient"], "proxy": "gpugr"}
            for method in states
        }

        result = audit_partial_elimination(data, states, provenance)

        self.assertEqual(result["eliminated_count"], 1)
        self.assertEqual(result["eliminated_metric_regression_count"], 1)
        self.assertEqual(result["eliminated_inactive_count"], 0)
        self.assertEqual(result["still_possible_count"], 1)
        self.assertEqual(result["indeterminate_count"], 0)
        self.assertEqual(result["eliminated"][0]["method"], "regresses")
        self.assertEqual(
            result["eliminated"][0]["positive_worst_primary_regressions"],
            {"gpugr:gr_wirelength": 0.01},
        )
        self.assertEqual(
            result["positive_regression_metric_counts"],
            {"gpugr:gr_wirelength": 1},
        )
        self.assertEqual(
            result["classification_by_plugin"]["local_gradient"],
            {
                "metric_regression": 1,
                "inactive": 0,
                "still_possible": 1,
                "indeterminate": 0,
            },
        )
        self.assertFalse(result["selection_or_admission_decision"])
        self.assertFalse(result["numeric_backend_mixing"])

    def test_observed_inactivation_is_irreversible(self):
        data = summary()
        states = {
            "possible": {
                "statuses": ["active", "inactive", "active"],
                "plugins": {"net_weighting"},
                "rows": 3,
            }
        }
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(data, states, provenance)

        self.assertEqual(result["eliminated_inactive_count"], 1)
        row = result["eliminated_inactive"][0]
        self.assertEqual(row["method"], "possible")
        self.assertEqual(row["classification"], "irreversibly_eliminated_inactive")
        self.assertEqual(
            result["classification_by_plugin"]["net_weighting"]["inactive"], 1
        )

    def test_hash_proven_gated_noop_remains_pending_activation(self):
        data = summary()
        statuses = ["selected_no_activation"] * 3
        states = {"possible": state(statuses)}
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(
            data,
            states,
            provenance,
            placement_effects=placement_effects("possible", statuses),
        )

        self.assertEqual(result["eliminated_inactive_count"], 0)
        self.assertEqual(result["still_possible_count"], 2)
        self.assertEqual(result["pending_activation_count"], 1)
        row = result["pending_activation"][0]
        self.assertEqual(row["method"], "possible")
        self.assertEqual(
            row["classification"], "still_possible_pending_activation"
        )
        self.assertEqual(row["activation"]["inactive_noop_comparisons"], 3)

    def test_inactive_changed_placement_remains_fail_closed(self):
        data = summary()
        statuses = ["active", "selected_no_activation", "active"]
        states = {"possible": state(statuses)}
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(
            data,
            states,
            provenance,
            placement_effects=placement_effects(
                "possible", statuses, changed_inactive=True
            ),
        )

        self.assertEqual(result["eliminated_inactive_count"], 1)
        self.assertIn(
            "inactive placement is not a hash-proven no-op",
            result["eliminated_inactive"][0]["reasons"],
        )

    def test_active_candidate_accepts_matching_effect_evidence(self):
        data = summary()
        statuses = ["active"] * 3
        states = {"possible": state(statuses)}
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(
            data,
            states,
            provenance,
            placement_effects=placement_effects("possible", statuses),
        )

        self.assertEqual(result["eliminated_count"], 0)
        self.assertEqual(result["still_possible_count"], 2)
        self.assertEqual(
            next(
                row for row in result["still_possible"]
                if row["method"] == "possible"
            )["classification"],
            "still_possible_zero_regression",
        )

    def test_gated_noop_without_effect_evidence_is_indeterminate(self):
        data = summary()
        statuses = ["selected_no_activation"] * 3
        states = {"possible": state(statuses)}
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(data, states, provenance)

        self.assertEqual(result["eliminated_inactive_count"], 0)
        self.assertEqual(result["indeterminate_count"], 1)
        self.assertIn(
            "gated inactive comparisons lack placement-effect identity evidence",
            result["indeterminate"][0]["reasons"],
        )

    def test_gpugr_regression_precedes_missing_activation_evidence(self):
        data = summary({("possible", "gpugr", "gr_wirelength"): 0.01})
        statuses = ["selected_no_activation"] * 3
        states = {"possible": state(statuses)}
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(data, states, provenance)

        self.assertEqual(result["eliminated_metric_regression_count"], 1)
        self.assertEqual(result["indeterminate_count"], 0)
        self.assertEqual(
            result["eliminated_metric_regression"][0]["method"], "possible"
        )

    def test_malformed_active_effect_evidence_is_eliminated(self):
        data = summary()
        statuses = ["active"] * 3
        states = {"possible": state(statuses)}
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(
            data,
            states,
            provenance,
            placement_effects=placement_effects(
                "possible", statuses, malformed_active=True
            ),
        )

        self.assertEqual(result["eliminated_inactive_count"], 1)
        self.assertIn(
            "active placement lacks changed-DEF evidence",
            result["eliminated_inactive"][0]["reasons"],
        )

    def test_rudy_worst_regression_is_not_an_irreversible_gate(self):
        data = summary({("regresses", "rudy", "utilization_max"): 0.01})
        states = {
            method: {
                "statuses": ["active"] * 3,
                "plugins": {"local_gradient"},
                "rows": 3,
            }
            for method in ("regresses", "possible")
        }
        provenance = {
            method: {"plugins": ["local_gradient"], "proxy": "rudy"}
            for method in states
        }

        result = audit_partial_elimination(data, states, provenance)

        self.assertEqual(result["eliminated_metric_regression_count"], 0)
        self.assertEqual(result["still_possible_count"], 2)
        self.assertEqual(result["worst_regression_backends"], ["gpugr"])
        regresses = next(
            row for row in result["still_possible"]
            if row["method"] == "regresses"
        )
        self.assertEqual(regresses["positive_worst_primary_regressions"], {})

    def test_marks_missing_completed_coverage_indeterminate(self):
        data = summary()
        data["rows"] = [
            row for row in data["rows"]
            if not (
                row["method"] == "possible"
                and row["backend"] == "rudy"
                and row["metric"] == "overflow_sum"
            )
        ]
        states = {
            "possible": {
                "statuses": ["active"] * 3,
                "plugins": {"net_weighting"},
                "rows": 3,
            }
        }
        provenance = {
            "possible": {"plugins": ["net_weighting"], "proxy": "rudy"}
        }

        result = audit_partial_elimination(data, states, provenance)

        self.assertEqual(result["indeterminate_count"], 1)
        possible = next(
            row for row in result["indeterminate"] if row["method"] == "possible"
        )
        self.assertIn(
            "missing completed coverage for rudy:overflow_sum",
            possible["reasons"],
        )

    def test_rejects_empty_or_complete_campaign(self):
        data = summary()
        data["validated_comparisons"] = 0
        with self.assertRaisesRegex(ValueError, "partial"):
            audit_partial_elimination(data, {})
        data["validated_comparisons"] = 6
        with self.assertRaisesRegex(ValueError, "partial"):
            audit_partial_elimination(data, {})


if __name__ == "__main__":
    unittest.main()
