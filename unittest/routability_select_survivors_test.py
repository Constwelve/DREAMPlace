#!/usr/bin/env python3

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_select_survivors import main, select_survivors


def metric(backend, name, method, mean, worst=None, median=None):
    return {
        "backend": backend, "metric": name, "method": method,
        "valid_count": 3, "expected_count": 3,
        "mean_delta_pct": mean,
        "median_delta_pct": mean if median is None else median,
        "worst_delta_pct": mean if worst is None else worst,
        "case_wins": int(mean < 0), "case_losses": int(mean >= 0),
    }


def summary():
    rows = []
    values = {
        "good_a": (-1.0, -0.5, -1.0, -4.0, -3.0, -2.0, -3.0, -1.0),
        "good_b": (-0.5, 0.5, -2.0, -2.0, -4.0, -1.0, -1.0, -2.0),
        "bad_wl": (1.0, 20.0, -5.0, -8.0, -7.0, -8.0, -9.0, -4.0),
    }
    for method, value in values.items():
        for (backend, name), mean in zip((
            ("placement", "placement_hpwl"), ("gpugr", "gr_wirelength"),
            ("gpugr", "gr_vias"), ("gpugr", "est_shorts"),
            ("gpugr", "num_ovfl_nets"), ("gpugr", "congestion_score"),
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
    def test_routability_first_does_not_reject_congestion_for_wirelength(self):
        result = select_survivors(summary(), STATES)

        self.assertIn("bad_wl", result["selected_methods"])
        self.assertEqual(result["selection_policy"]["name"], "routability_first")
        self.assertIn(
            "placement:placement_hpwl",
            result["selection_policy"]["diagnostic_metrics"],
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
