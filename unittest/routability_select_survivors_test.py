#!/usr/bin/env python3

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_select_survivors import (
    main,
    routability_metric_profile,
    select_survivors,
)


def metric(backend, name, method, mean, worst=None, median=None):
    return {
        "backend": backend, "metric": name, "method": method,
        "valid_count": 3, "expected_count": 3,
        "mean_delta_pct": mean,
        "median_delta_pct": mean if median is None else median,
        "worst_delta_pct": mean if worst is None else worst,
        "mean_delta": mean,
        "median_delta": mean if median is None else median,
        "worst_delta": mean if worst is None else worst,
        "percent_valid_count": 3,
        "case_wins": int(mean < 0), "case_losses": int(mean >= 0),
    }


def summary():
    rows = []
    values = {
        "good_a": (
            -1.0, -0.5, -1.0, -4.0, -3.0, -2.0, -1.0, -2.0,
            -3.0, -1.0,
        ),
        "good_b": (
            -0.5, 0.5, -2.0, -2.0, -4.0, -1.0, -2.0, -1.0,
            -1.0, -2.0,
        ),
        "bad_wl": (
            1.0, 20.0, -5.0, -8.0, -7.0, -8.0, -7.0, -8.0,
            -9.0, -4.0,
        ),
    }
    for method, value in values.items():
        for (backend, name), mean in zip((
            ("placement", "placement_hpwl"), ("gpugr", "gr_wirelength"),
            ("gpugr", "gr_vias"), ("gpugr", "est_shorts"),
            ("gpugr", "num_ovfl_nets"), ("gpugr", "rc_hor"),
            ("gpugr", "rc_ver"), ("gpugr", "congestion_score"),
            ("rudy", "overflow_sum"), ("rudy", "congestion_score"),
        ), value):
            rows.append(metric(backend, name, method, mean, worst=mean))
    return {
        "expected_comparisons": 3, "validated_comparisons": 3,
        "incomplete_jobs": [], "missing_comparisons": [], "excluded": [],
        "baseline_gaps": [], "rows": rows,
    }


STATES = {
    "good_a": {"statuses": ["active"] * 3, "plugins": {"local_gradient"}, "rows": 3},
    "good_b": {"statuses": ["active"] * 3, "plugins": {"net_weighting"}, "rows": 3},
    "bad_wl": {"statuses": ["active"] * 3, "plugins": {"routeforce"}, "rows": 3},
}


class RoutabilitySelectSurvivorsTest(unittest.TestCase):
    def mixed_activation_state(self):
        return {
            "statuses": ["selected_no_activation", "active", "active"],
            "plugins": {"local_gradient"},
            "rows": 3,
            "observations": [
                {"case": "case_a", "seed": "1000",
                 "status": "selected_no_activation"},
                {"case": "case_b", "seed": "1000", "status": "active"},
                {"case": "case_b", "seed": "2000", "status": "active"},
            ],
        }

    def mixed_activation_effects(self):
        return {
            "expected_comparisons": 3,
            "methods": {"good_a": {
                ("case_a", "1000"): {
                    "active": False, "changed_from_baseline": False,
                },
                ("case_b", "1000"): {
                    "active": True, "changed_from_baseline": True,
                },
                ("case_b", "2000"): {
                    "active": True, "changed_from_baseline": True,
                },
            }},
        }

    def test_accepts_hash_proven_gated_noop_comparison(self):
        states = dict(STATES)
        states["good_a"] = self.mixed_activation_state()

        result = select_survivors(
            summary(), states,
            placement_effects=self.mixed_activation_effects(),
        )

        self.assertIn("good_a", result["selected_methods"])
        selected = next(
            row for row in result["qualified"] if row["method"] == "good_a"
        )
        self.assertEqual(selected["activation"]["active_comparisons"], 2)
        self.assertEqual(selected["activation"]["inactive_noop_comparisons"], 1)
        self.assertTrue(selected["activation"]["placement_effect_audit_used"])

    def test_rejects_gated_noop_without_placement_effect_evidence(self):
        states = dict(STATES)
        states["good_a"] = self.mixed_activation_state()

        result = select_survivors(summary(), states)
        rejected = next(
            row for row in result["excluded"] if row["method"] == "good_a"
        )

        self.assertTrue(any(
            "lack placement-effect identity evidence" in reason
            for reason in rejected["reasons"]
        ))

    def test_rejects_inactive_comparison_with_changed_def(self):
        states = dict(STATES)
        states["good_a"] = self.mixed_activation_state()
        effects = self.mixed_activation_effects()
        effects["methods"]["good_a"][("case_a", "1000")][
            "changed_from_baseline"
        ] = True

        result = select_survivors(
            summary(), states, placement_effects=effects,
        )
        rejected = next(
            row for row in result["excluded"] if row["method"] == "good_a"
        )

        self.assertIn(
            "inactive placement is not a hash-proven no-op",
            rejected["reasons"],
        )

    def test_rejects_candidate_never_active_in_any_comparison(self):
        states = dict(STATES)
        state = self.mixed_activation_state()
        state["statuses"] = ["selected_no_activation"] * 3
        for row in state["observations"]:
            row["status"] = "selected_no_activation"
        states["good_a"] = state

        result = select_survivors(
            summary(), states,
            placement_effects=self.mixed_activation_effects(),
        )
        rejected = next(
            row for row in result["excluded"] if row["method"] == "good_a"
        )

        self.assertIn(
            "plugin was not active in any comparison", rejected["reasons"]
        )

    def test_absolute_directional_profile_requires_enhanced_metrics(self):
        result = select_survivors(
            summary(), STATES, metric_profile="absolute_directional_v2"
        )

        self.assertEqual(result["selected_methods"], [])
        self.assertTrue(any(
            "missing full gpugr:horizontal_ace coverage" in reason
            for row in result["excluded"] for reason in row["reasons"]
        ))

    def test_absolute_directional_profile_uses_absolute_metrics(self):
        data = summary()
        existing = {
            (row["backend"], row["metric"], row["method"])
            for row in data["rows"]
        }
        required = (
            ("gpugr", "overflow_sum"),
            ("gpugr", "overflow_bins"),
            ("gpugr", "utilization_p99"),
            ("gpugr", "utilization_max"),
            ("gpugr", "horizontal_overflow_sum"),
            ("gpugr", "vertical_overflow_sum"),
            ("gpugr", "horizontal_overflow_bins"),
            ("gpugr", "vertical_overflow_bins"),
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
            ("rudy", "utilization_p99"),
            ("rudy", "utilization_max"),
            ("rudy", "overflow_bins"),
        )
        for method in STATES:
            for backend, name in required:
                if (backend, name, method) not in existing:
                    data["rows"].append(metric(
                        backend, name, method, -1.0, worst=0.0
                    ))

        result = select_survivors(
            data, STATES, metric_profile="absolute_directional_v2",
            max_primary_worst_regression=0.0,
        )

        self.assertEqual(
            result["selection_policy"]["metric_profile"],
            "absolute_directional_v2",
        )
        self.assertIn(
            "gpugr:horizontal_ace",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "gpugr:rc_hor",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "gpugr:rc_ver",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "gpugr:horizontal_overflow_bins",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "gpugr:vertical_overflow_bins",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "gpugr:horizontal_congestion_score_p99",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "gpugr:vertical_congestion_score_p99",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "rudy:overflow_bins",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertNotIn(
            "gpugr:congestion_score",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertIn(
            "gpugr:congestion_score",
            result["selection_policy"]["diagnostic_metrics"],
        )
        self.assertNotIn(
            "gpugr:rc_hor",
            result["selection_policy"]["diagnostic_metrics"],
        )

        directional = next(
            row for row in data["rows"]
            if row["method"] == "good_a"
            and row["backend"] == "gpugr"
            and row["metric"] == "horizontal_congestion_score"
        )
        directional["worst_delta_pct"] = 0.1
        directional["worst_delta"] = 0.1
        rejected = select_survivors(
            data, STATES, metric_profile="absolute_directional_v2",
            max_primary_worst_regression=0.0,
        )
        self.assertNotIn("good_a", rejected["selected_methods"])
        good_a = next(
            row for row in rejected["excluded"] if row["method"] == "good_a"
        )
        self.assertTrue(any(
            "gpugr:horizontal_congestion_score=0.1" in reason
            for reason in good_a["reasons"]
        ))

    def test_absolute_directional_v3_treats_normalized_scores_as_diagnostic(self):
        data = summary()
        profile = routability_metric_profile("absolute_directional_v3")
        existing = {
            (row["backend"], row["metric"], row["method"])
            for row in data["rows"]
        }
        required = profile["primary"] + profile["secondary"] + profile["diagnostic"]
        for method in STATES:
            for backend, name in required:
                if (backend, name, method) not in existing:
                    data["rows"].append(metric(
                        backend, name, method, -1.0, worst=0.0
                    ))

        normalized_scores = (
            "horizontal_congestion_score",
            "vertical_congestion_score",
            "horizontal_congestion_score_p95",
            "vertical_congestion_score_p95",
            "horizontal_congestion_score_p99",
            "vertical_congestion_score_p99",
        )
        for row in data["rows"]:
            if (
                row["method"] == "good_a"
                and row["backend"] == "gpugr"
                and row["metric"] in normalized_scores
            ):
                row["mean_delta_pct"] = 25.0
                row["median_delta_pct"] = 25.0
                row["worst_delta_pct"] = 25.0
                row["mean_delta"] = 25.0
                row["median_delta"] = 25.0
                row["worst_delta"] = 25.0

        result = select_survivors(
            data, STATES, metric_profile="absolute_directional_v3",
            max_primary_worst_regression=0.0,
        )

        primary = result["selection_policy"]["primary_objectives"]
        diagnostic = result["selection_policy"]["diagnostic_metrics"]
        for name in normalized_scores:
            metric_name = "gpugr:" + name
            self.assertNotIn(metric_name, primary)
            self.assertIn(metric_name, diagnostic)
        self.assertTrue(any(
            row["method"] == "good_a" for row in result["qualified"]
        ))
        self.assertFalse(any(
            row["method"] == "good_a" for row in result["excluded"]
        ))

    def test_routability_first_treats_gpugr_wirelength_as_primary(self):
        result = select_survivors(summary(), STATES)

        self.assertIn("bad_wl", result["selected_methods"])
        self.assertEqual(result["selection_policy"]["name"], "routability_first")
        self.assertIn(
            "placement:placement_hpwl",
            result["selection_policy"]["diagnostic_metrics"],
        )
        self.assertIn(
            "gpugr:rc_hor", result["selection_policy"]["primary_objectives"]
        )
        self.assertIn(
            "gpugr:rc_ver", result["selection_policy"]["primary_objectives"]
        )
        self.assertIn(
            "gpugr:gr_wirelength",
            result["selection_policy"]["primary_objectives"],
        )
        self.assertEqual(
            result["selection_policy"]["secondary_objectives"],
            ["gpugr:gr_vias"],
        )
        self.assertIn(
            "gpugr:gr_wirelength",
            result["selection_policy"]["objectives"],
        )
        self.assertIn(
            "gr_wirelength",
            result["selection_policy"]["backend_improvement_constraints"][
                "gpugr"
            ]["metrics"],
        )

    def test_legacy_wirelength_guardrails_remain_reproducible(self):
        result = select_survivors(
            summary(), STATES, selection_policy="wirelength_guarded"
        )

        self.assertEqual(set(result["selected_methods"]), {"good_a", "good_b"})
        self.assertEqual(
            set(result["combination_plugins"]), {"local_gradient", "net_weighting"}
        )
        bad = next(row for row in result["excluded"] if row["method"] == "bad_wl")
        self.assertIn("mean GPUGR wirelength guardrail", bad["reasons"])

    def test_strict_primary_gate_rejects_any_positive_worst_case(self):
        result = select_survivors(
            summary(), STATES, max_primary_worst_regression=0.0
        )

        self.assertEqual(result["selected_methods"], ["good_a"])
        self.assertEqual(
            result["selection_policy"]["max_primary_worst_regression"], 0.0
        )
        rejected = next(
            row for row in result["excluded"] if row["method"] == "good_b"
        )
        self.assertTrue(any(
            "worst-case primary regression" in reason
            for reason in rejected["reasons"]
        ))

    def test_strict_primary_gate_only_guards_gpugr(self):
        data = summary()
        rudy = next(
            row for row in data["rows"]
            if row["method"] == "good_a"
            and row["backend"] == "rudy"
            and row["metric"] == "congestion_score"
        )
        rudy["worst_delta_pct"] = 9.0
        rudy["worst_delta"] = 9.0

        result = select_survivors(
            data, STATES, max_primary_worst_regression=0.0
        )

        self.assertIn("good_a", result["selected_methods"])
        self.assertEqual(
            result["selection_policy"]["worst_regression_backends"],
            ["gpugr"],
        )

    def test_strict_primary_gate_uses_raw_delta_for_zero_baseline_pairs(self):
        data = summary()
        row = next(
            row for row in data["rows"]
            if row["method"] == "good_a"
            and row["backend"] == "gpugr" and row["metric"] == "rc_hor"
        )
        row["percent_valid_count"] = 2
        row["worst_delta_pct"] = -100.0
        row["worst_delta"] = 1.0

        result = select_survivors(
            data, STATES, max_primary_worst_regression=0.0
        )

        self.assertNotIn("good_a", result["selected_methods"])
        rejected = next(
            item for item in result["excluded"] if item["method"] == "good_a"
        )
        self.assertTrue(any(
            "gpugr:rc_hor=1" in reason for reason in rejected["reasons"]
        ))

    def test_routability_first_requires_one_improvement_per_backend(self):
        data = summary()
        source_rows = [row for row in data["rows"] if row["method"] == "good_a"]
        for row in source_rows:
            weak = dict(row)
            weak["method"] = "one_each"
            if weak["backend"] == "gpugr" and weak["metric"] == "est_shorts":
                weak["mean_delta_pct"] = -1.0
                weak["median_delta_pct"] = -1.0
            elif weak["backend"] == "rudy" and weak["metric"] == "congestion_score":
                weak["mean_delta_pct"] = -1.0
                weak["median_delta_pct"] = -1.0
            elif weak["backend"] in ("gpugr", "rudy"):
                weak["mean_delta_pct"] = 1.0
                weak["median_delta_pct"] = 1.0
            data["rows"].append(weak)
        states = dict(STATES)
        states["one_each"] = {
            "statuses": ["active"] * 3,
            "plugins": {"whitespace"},
            "rows": 3,
        }

        result = select_survivors(data, states)

        qualified = {row["method"] for row in result["qualified"]}
        self.assertIn("one_each", qualified)

        data = summary()
        source_rows = [row for row in data["rows"] if row["method"] == "good_a"]
        for row in source_rows:
            weak = dict(row)
            weak["method"] = "gpugr_only"
            if weak["backend"] == "gpugr" and weak["metric"] == "est_shorts":
                weak["mean_delta_pct"] = -1.0
                weak["median_delta_pct"] = -1.0
            elif weak["backend"] in ("gpugr", "rudy"):
                weak["mean_delta_pct"] = 1.0
                weak["median_delta_pct"] = 1.0
            data["rows"].append(weak)
        states = dict(STATES)
        states["gpugr_only"] = {
            "statuses": ["active"] * 3,
            "plugins": {"whitespace"},
            "rows": 3,
        }

        result = select_survivors(data, states)
        rejected = next(
            row for row in result["excluded"]
            if row["method"] == "gpugr_only"
        )
        self.assertNotIn(
            "fewer than 1/6 GPUGR primary metrics improved",
            rejected["reasons"],
        )
        self.assertIn(
            "fewer than 1/2 RUDY primary metrics improved",
            rejected["reasons"],
        )

    def test_reports_gpugr_veto_when_backend_improvement_gate_also_fails(self):
        data = summary()
        for row in data["rows"]:
            if row["method"] != "good_a":
                continue
            if row["backend"] == "rudy":
                row["mean_delta_pct"] = 1.0
                row["median_delta_pct"] = 1.0
                row["worst_delta_pct"] = 1.0
            if row["backend"] == "gpugr" and row["metric"] == "rc_hor":
                row["mean_delta_pct"] = 1.0
                row["median_delta_pct"] = 1.0
                row["worst_delta_pct"] = 1.0
        result = select_survivors(
            data,
            STATES,
            max_primary_worst_regression=0.0,
        )
        rejected = next(
            row for row in result["excluded"] if row["method"] == "good_a"
        )
        self.assertIn(
            "fewer than 1/2 RUDY primary metrics improved",
            rejected["reasons"],
        )
        self.assertTrue(any(
            "gpugr:rc_hor=1" in reason for reason in rejected["reasons"]
        ))

    def test_rejects_incomplete_summary(self):
        data = summary()
        data["incomplete_jobs"] = [{"status": "running"}]
        with self.assertRaisesRegex(ValueError, "not a complete"):
            select_survivors(data, STATES)

    def test_tuned_variants_keep_one_preset_per_plugin(self):
        data = summary()
        source_rows = [row for row in data["rows"] if row["method"] == "good_a"]
        for row in source_rows:
            alternative = dict(row)
            alternative["method"] = "good_a_alt"
            if alternative["backend"] == "gpugr" and alternative["metric"] == "gr_wirelength":
                alternative["mean_delta_pct"] = -2.0
                alternative["median_delta_pct"] = -2.0
                alternative["worst_delta_pct"] = -2.0
            elif alternative["backend"] == "placement":
                alternative["mean_delta_pct"] = -0.25
                alternative["median_delta_pct"] = -0.25
                alternative["worst_delta_pct"] = -0.25
            data["rows"].append(alternative)
        states = dict(STATES)
        states["good_a_alt"] = {
            "statuses": ["active"] * 3,
            "plugins": {"local_gradient"},
            "rows": 3,
        }
        provenance = {
            "good_a": {
                "grid": {
                    "ruplace_local_gradient_weight": 0.005,
                    "ruplace_plugin_start_overflow": 0.6,
                }
            },
            "good_a_alt": {
                "grid": {
                    "ruplace_local_gradient_weight": 0.01,
                    "ruplace_plugin_start_overflow": 0.8,
                }
            },
        }

        result = select_survivors(
            data, states, preset_provenance=provenance
        )

        local_methods = [
            row for row in result["selected_methods"] if row.startswith("good_a")
        ]
        self.assertEqual(local_methods, ["good_a_alt"])
        self.assertEqual(
            result["combination_plugin_grids"],
            {"local_gradient": {"ruplace_local_gradient_weight": [0.01]}},
        )

    def test_cli_writes_pair_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "screening_summary.json"
            raw = root / "screening_raw.csv"
            output = root / "survivors.json"
            spec = root / "pair_spec.json"
            preset_manifest = root / "presets.json.manifest.json"
            summary_path.write_text(json.dumps(summary()))
            with raw.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "backend", "method", "plugin_status", "plugin_selected",
                ])
                writer.writeheader()
                for method, state in STATES.items():
                    for _ in range(3):
                        writer.writerow({
                            "backend": "placement", "method": method,
                            "plugin_status": "active",
                            "plugin_selected": ",".join(state["plugins"]),
                        })
            preset_manifest.write_text(json.dumps({
                "generated": {
                    "good_a": {"grid": {"ruplace_local_gradient_weight": 0.01}},
                    "good_b": {"grid": {"ruplace_net_weight_gamma": 0.05}},
                }
            }))
            status = main([
                "--summary", str(summary_path), "--raw", str(raw),
                "--output", str(output), "--combination-spec", str(spec),
                "--preset-manifest", str(preset_manifest),
            ])
            generated = json.loads(spec.read_text())

        self.assertEqual(status, 0)
        self.assertEqual(generated["combination_sizes"], [2])
        self.assertEqual(
            set(generated["plugins"]),
            {"local_gradient", "net_weighting", "routeforce"},
        )
        self.assertEqual(
            generated["plugin_grids"]["local_gradient"],
            {"ruplace_local_gradient_weight": [0.01]},
        )


if __name__ == "__main__":
    unittest.main()
