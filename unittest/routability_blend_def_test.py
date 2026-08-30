#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_blend_def import blend_components, blend_def


def placed_def(u1=(100, 200), u2=(50, 50), orientation="N"):
    return (
        "VERSION 5.8 ;\n"
        "COMPONENTS 3 ;\n"
        "- U1 CELL\n  + PLACED ( %d %d ) %s ;\n"
        "- U2 CELL + PLACED ( %d %d ) N ;\n"
        "- MACRO BLOCK + FIXED ( 900 800 ) FN ;\n"
        "END COMPONENTS\n"
        "PINS 1 ;\n"
        "- IN + NET IN + FIXED ( 3 4 ) N ;\n"
        "END PINS\nEND DESIGN\n"
    ) % (u1[0], u1[1], orientation, u2[0], u2[1])


class RoutabilityBlendDefTest(unittest.TestCase):
    def test_blends_only_movable_component_coordinates(self):
        baseline = placed_def()
        candidate = placed_def(u1=(140, 120), u2=(42, 62))
        blended, stats = blend_components(baseline, candidate, "0.25", 2)

        self.assertIn("+ PLACED ( 110 180 ) N", blended)
        self.assertIn("+ PLACED ( 48 54 ) N", blended)
        self.assertIn("+ FIXED ( 900 800 ) FN", blended)
        self.assertIn("+ FIXED ( 3 4 ) N", blended)
        self.assertEqual(stats["moved_components"], 2)
        self.assertEqual(stats["changed_coordinates"], 4)
        self.assertEqual(stats["max_candidate_displacement_dbu"], 80)
        self.assertEqual(stats["max_applied_displacement_dbu"], 20)

    def test_zero_alpha_preserves_baseline_bytes_and_report_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "blend.def"
            report_path = root / "blend.json"
            baseline.write_text(placed_def())
            candidate.write_text(placed_def(u1=(140, 120)))

            report = blend_def(
                baseline, candidate, output, 0, report_path=report_path
            )
            persisted = json.loads(report_path.read_text())
            output_text = output.read_text()
            baseline_text = baseline.read_text()

        self.assertEqual(output_text, baseline_text)
        self.assertEqual(report["baseline_sha256"], report["output_sha256"])
        self.assertEqual(persisted["operation"], report["operation"])
        self.assertEqual(report["moved_components"], 0)

    def test_rejects_incompatible_components_and_fixed_locations(self):
        baseline = placed_def()
        with self.assertRaisesRegex(ValueError, "orientation differs"):
            blend_components(baseline, placed_def(orientation="S"), 0.5)
        blended, stats = blend_components(
            baseline, placed_def(u1=(140, 120), orientation="S"), 0.5,
            orientation_policy="baseline",
        )
        self.assertIn("+ PLACED ( 120 160 ) N", blended)
        self.assertEqual(stats["orientation_mismatch_count"], 1)
        self.assertEqual(stats["orientation_mismatch_examples"], ["U1"])
        changed_fixed = placed_def().replace(
            "+ FIXED ( 900 800 )", "+ FIXED ( 901 800 )"
        )
        with self.assertRaisesRegex(ValueError, "fixed component"):
            blend_components(baseline, changed_fixed, 0.5)
        missing = placed_def().replace("- U2 CELL + PLACED ( 50 50 ) N ;\n", "")
        with self.assertRaisesRegex(ValueError, "component mismatch"):
            blend_components(baseline, missing, 0.5)

    def test_axis_constrained_blend_preserves_other_coordinate(self):
        baseline = placed_def()
        candidate = placed_def(u1=(140, 120), u2=(42, 62))

        x_blended, x_stats = blend_components(
            baseline, candidate, "0.25", 2, axis="x"
        )
        y_blended, y_stats = blend_components(
            baseline, candidate, "0.25", 2, axis="y"
        )

        self.assertIn("+ PLACED ( 110 200 ) N", x_blended)
        self.assertIn("+ PLACED ( 48 50 ) N", x_blended)
        self.assertEqual(x_stats["axis"], "x")
        self.assertEqual(x_stats["changed_coordinates"], 2)
        self.assertIn("+ PLACED ( 100 180 ) N", y_blended)
        self.assertIn("+ PLACED ( 50 54 ) N", y_blended)
        self.assertEqual(y_stats["axis"], "y")
        self.assertEqual(y_stats["changed_coordinates"], 2)

    def test_rejects_invalid_alpha_and_output_alias(self):
        with self.assertRaisesRegex(ValueError, "alpha"):
            blend_components(placed_def(), placed_def(), 1.1)
        with self.assertRaisesRegex(ValueError, "axis"):
            blend_components(placed_def(), placed_def(), 0.5, axis="z")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            baseline.write_text(placed_def())
            candidate.write_text(placed_def(u1=(140, 120)))
            with self.assertRaisesRegex(ValueError, "must differ"):
                blend_def(baseline, candidate, baseline, 0.5)


if __name__ == "__main__":
    unittest.main()
