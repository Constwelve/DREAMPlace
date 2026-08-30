#!/usr/bin/env python3

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_legal_refine_def import (
    placement_geometry_provenance,
    refine_def,
)


LEF = """UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MACRO CELL
  SIZE 0.01 BY 0.01 ;
END CELL
"""


def placed_def(a=0, b=20, c=50, nets=False):
    return """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
ROW R0 SITE 0 0 N DO 10 BY 1 STEP 10 0 ;
COMPONENTS 3 ;
- A CELL + PLACED ( %d 0 ) N ;
- B CELL + PLACED ( %d 0 ) N ;
- C CELL + FIXED ( %d 0 ) N ;
END COMPONENTS
%s
END DESIGN
""" % (
        a,
        b,
        c,
        """NETS 1 ;
- net0 ( A Y ) ( B A ) ;
END NETS""" if nets else "",
    )


class RoutabilityLegalRefineDefTest(unittest.TestCase):
    def test_exported_geometry_provenance_detects_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            legal = root / "legal.def"
            overlap = root / "overlap.def"
            lef.write_text(LEF)
            legal.write_text(placed_def())
            overlap.write_text(placed_def(a=0, b=0))

            legal_result = placement_geometry_provenance(legal, [lef])
            overlap_result = placement_geometry_provenance(overlap, [lef])

        self.assertEqual(legal_result["overlap_pair_count"], 0)
        self.assertEqual(legal_result["unplaced_component_count"], 0)
        self.assertEqual(overlap_result["overlap_pair_count"], 1)
        self.assertEqual(overlap_result["overlap_pair_sample"], [["A", "B"]])

    def test_exported_geometry_uses_orientation_and_allows_fixed_off_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            deffile = root / "oriented.def"
            lef.write_text(LEF + """MACRO TALL
  SIZE 0.01 BY 0.02 ;
END TALL
""")
            deffile.write_text("""VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
ROW R0 SITE 0 0 N DO 10 BY 1 STEP 10 0 ;
ROW R0B SITE 200 0 N DO 5 BY 1 STEP 10 0 ;
ROW R1 SITE 0 10 N DO 10 BY 1 STEP 10 0 ;
COMPONENTS 3 ;
- A TALL + PLACED ( 0 0 ) E ;
- B CELL + PLACED ( 10 0 ) N ;
- C CELL + FIXED ( 50 100 ) N ;
END COMPONENTS
END DESIGN
""")

            result = placement_geometry_provenance(deffile, [lef])

        self.assertEqual(result["overlap_pair_count"], 1)
        self.assertEqual(result["overlap_pair_sample"], [["A", "B"]])
        self.assertEqual(result["uncovered_component_count"], 0)
        self.assertEqual(result["row_count"], 2)

    def test_slides_by_sites_without_overlap_or_row_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "refined.def"
            lef.write_text(LEF)
            baseline.write_text(placed_def())
            candidate.write_text(placed_def(a=40, b=40))

            report = refine_def(
                baseline, candidate, [lef], output, max_steps=1
            )
            text = output.read_text()

        self.assertIn("- A CELL + PLACED ( 10 0 ) N", text)
        self.assertIn("- B CELL + PLACED ( 30 0 ) N", text)
        self.assertIn("- C CELL + FIXED ( 50 0 ) N", text)
        self.assertEqual(report["moved_components"], 2)
        self.assertEqual(report["baseline_overlap_pairs"], 0)
        self.assertEqual(report["output_overlap_pairs"], 0)

    def test_blocks_moves_without_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "refined.def"
            lef.write_text(LEF)
            baseline.write_text(placed_def(a=0, b=10, c=20))
            candidate.write_text(placed_def(a=20, b=20, c=20))

            report = refine_def(baseline, candidate, [lef], output)

        self.assertEqual(report["moved_components"], 0)
        self.assertGreater(report["blocked_attempts"], 0)

    def test_direction_filter_keeps_operations_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "refined.def"
            lef.write_text(LEF)
            baseline.write_text(placed_def(a=10, b=30, c=50))
            candidate.write_text(placed_def(a=0, b=40, c=50))

            report = refine_def(
                baseline, candidate, [lef], output, direction="left"
            )
            text = output.read_text()

        self.assertIn("- A CELL + PLACED ( 0 0 ) N", text)
        self.assertIn("- B CELL + PLACED ( 30 0 ) N", text)
        self.assertEqual(report["direction"], "left")
        self.assertEqual(report["moved_components"], 1)

    def test_fraction_window_selects_a_disjoint_rank_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "refined.def"
            lef.write_text(LEF)
            baseline.write_text(placed_def(a=0, b=20, c=50))
            candidate.write_text(placed_def(a=40, b=30, c=50))

            report = refine_def(
                baseline,
                candidate,
                [lef],
                output,
                min_moved_fraction=0.5,
                max_moved_fraction=1.0,
            )
            text = output.read_text()

        self.assertIn("- A CELL + PLACED ( 0 0 ) N", text)
        self.assertIn("- B CELL + PLACED ( 30 0 ) N", text)
        self.assertEqual(report["selected_components"], 1)
        self.assertEqual(report["min_moved_fraction"], 0.5)

    def test_rejects_overlapping_fraction_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "refined.def"
            lef.write_text(LEF)
            baseline.write_text(placed_def())
            candidate.write_text(placed_def(a=40, b=40))

            with self.assertRaisesRegex(ValueError, "ordered and disjoint"):
                refine_def(
                    baseline,
                    candidate,
                    [lef],
                    output,
                    moved_fraction_windows=[(0.0, 0.6), (0.5, 1.0)],
                )

    def test_net_bbox_guard_rejects_predicted_wirelength_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "refined.def"
            lef.write_text(LEF)
            baseline.write_text(placed_def(a=0, b=30, c=50, nets=True))
            candidate.write_text(placed_def(a=20, b=50, c=50, nets=True))

            report = refine_def(
                baseline,
                candidate,
                [lef],
                output,
                rank_mode="net_bbox_delta",
                max_net_bbox_delta_dbu=-1,
            )
            text = output.read_text()

        self.assertIn("- A CELL + PLACED ( 10 0 ) N", text)
        self.assertIn("- B CELL + PLACED ( 30 0 ) N", text)
        self.assertEqual(report["rank_mode"], "net_bbox_delta")
        self.assertEqual(report["skipped"]["net_bbox_guard"], 1)
        self.assertEqual(report["net_bbox_x_delta_dbu"], -10)

    def test_net_bbox_limit_requires_net_bbox_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            output = root / "refined.def"
            lef.write_text(LEF)
            baseline.write_text(placed_def())
            candidate.write_text(placed_def(a=20))

            with self.assertRaisesRegex(ValueError, "requires rank_mode"):
                refine_def(
                    baseline,
                    candidate,
                    [lef],
                    output,
                    max_net_bbox_delta_dbu=0,
                )


if __name__ == "__main__":
    unittest.main()
