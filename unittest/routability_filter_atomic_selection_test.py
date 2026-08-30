#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_filter_atomic_selection import filter_atomic_selection, main
from tools.routability_audit_corrected import audit_strict_selection
from tools.routability_select_survivors import routability_metric_profile


def strict_selection(methods, metric_profile="absolute_directional_v2"):
    profile = routability_metric_profile(metric_profile)
    qualified = []
    for method in methods:
        metrics = {}
        for backend, metric in profile["primary"]:
            metrics["%s:%s" % (backend, metric)] = {
                "mean_delta": -1.0,
                "mean_delta_pct": -1.0,
                "median_delta": -1.0,
                "median_delta_pct": -1.0,
                "worst_delta": 0.0,
                "worst_delta_pct": 0.0,
                "valid_count": 6,
                "percent_valid_count": 6,
            }
        qualified.append({"method": method, "metrics": metrics})
    return {
        "baseline": "hpwl",
        "expected_comparisons": 6,
        "selection_policy": {
            "name": "routability_first",
            "metric_profile": metric_profile,
            "numeric_backend_mixing": False,
            "max_survivors": 5,
            "max_primary_worst_regression": 0.0,
            "worst_regression_backends": list(
                profile["worst_regression_backends"]
            ),
            "primary_objectives": [
                "%s:%s" % item for item in profile["primary"]
            ],
            "backend_improvement_constraints": json.loads(json.dumps(
                profile["constraints"]
            )),
        },
        "qualified": qualified,
        "excluded": [],
        "pareto_frontier": list(methods),
        "selected_methods": list(methods),
    }


class RoutabilityFilterAtomicSelectionTest(unittest.TestCase):
    def test_removes_only_invalidated_plugin_survivors(self):
        selection = strict_selection(["weight", "force"])
        presets = {
            "weight": {"ruplace_plugins": ["net_weighting"]},
            "force": {"ruplace_plugins": ["local_gradient"]},
        }
        generated = {
            name: {"plugins": config["ruplace_plugins"]}
            for name, config in presets.items()
        }

        result = filter_atomic_selection(
            selection, presets, generated, ["net_weighting"]
        )

        self.assertEqual(result["selected_methods"], ["force"])
        self.assertEqual(result["pareto_frontier"], ["force"])
        self.assertEqual(
            [row["method"] for row in result["qualified"]], ["force"]
        )
        self.assertEqual(result["filter_policy"]["removed_methods"], ["weight"])
        self.assertFalse(result["filter_policy"]["heldout_or_golden_evidence_used"])

    def test_only_invalidated_survivor_becomes_auditable_empty_selection(self):
        selection = strict_selection(["weight"])
        presets = {"weight": {"ruplace_plugins": ["net_weighting"]}}
        generated = {"weight": {"plugins": ["net_weighting"]}}

        result = filter_atomic_selection(
            selection, presets, generated, ["net_weighting"]
        )

        self.assertEqual(result["selected_methods"], [])
        self.assertEqual(result["pareto_frontier"], [])
        self.assertEqual(result["qualified"], [])

    def test_rejects_plugin_provenance_mismatch(self):
        selection = strict_selection(["weight"])
        presets = {"weight": {"ruplace_plugins": ["net_weighting"]}}
        generated = {"weight": {"plugins": ["local_gradient"]}}

        with self.assertRaisesRegex(ValueError, "provenance differs"):
            filter_atomic_selection(
                selection, presets, generated, ["net_weighting"]
            )

    def test_cli_writes_hash_bound_auditable_filter_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            presets = root / "presets.json"
            manifest = root / "manifest.json"
            output = root / "filtered.json"
            selection.write_text(json.dumps(strict_selection(["weight", "force"])))
            presets.write_text(json.dumps({
                "weight": {"ruplace_plugins": ["net_weighting"]},
                "force": {"ruplace_plugins": ["local_gradient"]},
            }))
            manifest.write_text(json.dumps({"generated": {
                "weight": {"plugins": ["net_weighting"]},
                "force": {"plugins": ["local_gradient"]},
            }}))

            status = main([
                "--selection", str(selection),
                "--presets", str(presets),
                "--preset-manifest", str(manifest),
                "--exclude-plugin", "net_weighting",
                "--output", str(output),
            ])
            result = audit_strict_selection(
                output, 6, allow_empty=True,
                required_metric_profile="absolute_directional_v2",
            )

        self.assertEqual(status, 0)
        self.assertEqual(result["selected_methods"], ["force"])
        self.assertIn("source_selection_sha256", result["filter_policy"])

    def test_cli_accepts_explicit_capacity_absolute_v3_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            presets = root / "presets.json"
            manifest = root / "manifest.json"
            output = root / "filtered.json"
            selection.write_text(json.dumps(strict_selection(
                ["weight", "force"], "absolute_directional_v3"
            )))
            presets.write_text(json.dumps({
                "weight": {"ruplace_plugins": ["net_weighting"]},
                "force": {"ruplace_plugins": ["local_gradient"]},
            }))
            manifest.write_text(json.dumps({"generated": {
                "weight": {"plugins": ["net_weighting"]},
                "force": {"plugins": ["local_gradient"]},
            }}))

            status = main([
                "--selection", str(selection),
                "--presets", str(presets),
                "--preset-manifest", str(manifest),
                "--exclude-plugin", "net_weighting",
                "--metric-profile", "absolute_directional_v3",
                "--output", str(output),
            ])
            result = audit_strict_selection(
                output, 6, allow_empty=True,
                required_metric_profile="absolute_directional_v3",
            )

        self.assertEqual(status, 0)
        self.assertEqual(result["selected_methods"], ["force"])


if __name__ == "__main__":
    unittest.main()
