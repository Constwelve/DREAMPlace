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
        "good_a": (-1.0, -0.5, -1.0, -2.0, -3.0, -1.0),
        "good_b": (-0.5, 0.5, -2.0, -1.0, -1.0, -2.0),
        "bad_wl": (1.0, 20.0, -5.0, -8.0, -9.0, -4.0),
    }
    for method, value in values.items():
        for (backend, name), mean in zip((
            ("placement", "placement_hpwl"), ("gpugr", "gr_wirelength"),
            ("gpugr", "gr_vias"), ("gpugr", "congestion_score"),
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
    def test_guardrails_and_pareto_selection(self):
        result = select_survivors(summary(), STATES)

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

    def test_cli_writes_pair_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "screening_summary.json"
            raw = root / "screening_raw.csv"
            output = root / "survivors.json"
            spec = root / "pair_spec.json"
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
            status = main([
                "--summary", str(summary_path), "--raw", str(raw),
                "--output", str(output), "--combination-spec", str(spec),
            ])
            generated = json.loads(spec.read_text())

        self.assertEqual(status, 0)
        self.assertEqual(generated["combination_sizes"], [2])
        self.assertEqual(
            set(generated["plugins"]), {"local_gradient", "net_weighting"}
        )


if __name__ == "__main__":
    unittest.main()
