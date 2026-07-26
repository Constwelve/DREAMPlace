#!/usr/bin/env python3

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_summarize import main


def result(method, backend, metrics):
    return {
        "method": method,
        "backend": backend,
        "status": "ok",
        "authoritative_for_comparison": True,
        "metrics": metrics,
    }


class RoutabilitySummarizeTest(unittest.TestCase):
    def test_backend_deltas_are_paired_with_same_case_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_7" / "case_a" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": "hpwl", "status": "ok", "placement_hpwl": 100.0},
                    {"method": "plugin", "status": "ok", "placement_hpwl": 90.0,
                     "routability_plugin_status": "active"},
                ],
                "results": [
                    result("hpwl", "rudy", {"overflow_sum": 10.0}),
                    result("plugin", "rudy", {"overflow_sum": 8.0}),
                    result("hpwl", "gpugr", {"gr_wirelength": 200.0}),
                    result("plugin", "gpugr", {"gr_wirelength": 220.0}),
                ],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            with (output / "screening_summary.csv").open() as stream:
                rows = list(csv.DictReader(stream))

        self.assertEqual(status, 0)
        indexed = {(row["backend"], row["metric"], row["method"]): row for row in rows}
        self.assertAlmostEqual(
            float(indexed[("rudy", "overflow_sum", "plugin")]["mean_delta_pct"]),
            -20.0,
        )
        self.assertAlmostEqual(
            float(indexed[("gpugr", "gr_wirelength", "plugin")]["mean_delta_pct"]),
            10.0,
        )
        self.assertEqual(indexed[("rudy", "overflow_sum", "plugin")]["wins"], "1")
        self.assertEqual(indexed[("gpugr", "gr_wirelength", "plugin")]["losses"], "1")
        self.assertAlmostEqual(
            float(indexed[("rudy", "overflow_sum", "plugin")]["mean_delta"]),
            -2.0,
        )
        self.assertEqual(
            indexed[("rudy", "overflow_sum", "plugin")]["case_count"], "1"
        )
        self.assertEqual(
            indexed[("rudy", "overflow_sum", "plugin")]["case_ci95_low_pct"], ""
        )

    def test_unvalidated_comparison_is_excluded_and_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "campaign" / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "unvalidated"},
                "placements": [],
                "results": [],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(root / "campaign"),
                "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["validated_comparisons"], 0)
        self.assertEqual(len(data["excluded"]), 1)

    def test_validated_comparison_without_hpwl_baseline_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "campaign" / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": "plugin", "status": "ok", "placement_hpwl": 90.0},
                ],
                "results": [
                    result("plugin", "rudy", {"overflow_sum": 8.0}),
                ],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(root / "campaign"),
                "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(len(data["baseline_gaps"]), 2)

    def test_partial_parallel_campaign_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": "hpwl", "status": "ok", "placement_hpwl": 100.0},
                ],
                "results": [result("hpwl", "rudy", {"overflow_sum": 8.0})],
            }))
            (campaign / "parallel_status.json").write_text(json.dumps({"jobs": [
                {"case": "case_a", "seed": 1, "status": "completed", "returncode": 0},
                {"case": "case_b", "seed": 2, "status": "running", "returncode": ""},
            ]}))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["expected_comparisons"], 2)
        self.assertEqual(data["incomplete_jobs"][0]["status"], "running")
        self.assertEqual(data["missing_comparisons"], [{"case": "case_b", "seed": 2}])
        plugin = next(
            row for row in data["rows"]
            if row["backend"] == "rudy" and row["method"] == "hpwl"
        )
        self.assertEqual(plugin["valid_count"], 1)
        self.assertEqual(plugin["expected_count"], 2)
        self.assertFalse(plugin["statistically_supported"])


if __name__ == "__main__":
    unittest.main()
