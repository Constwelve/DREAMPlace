#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_snap_def import (
    grid_in_def_units,
    manufacturing_grid_microns,
    snap_def,
)


class RoutabilitySnapDefTest(unittest.TestCase):
    def test_snaps_only_component_placement_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "tech.lef"
            source = root / "placed.def"
            output = root / "snapped.def"
            report_path = root / "snap.json"
            lef.write_text("MANUFACTURINGGRID 0.005 ;\nEND LIBRARY\n")
            source.write_text(
                "VERSION 5.8 ;\n"
                "UNITS DISTANCE MICRONS 2000 ;\n"
                "COMPONENTS 3 ;\n"
                "- U1 CELL + PLACED ( 4401541 2591680 ) N ;\n"
                "- U2 CELL + FIXED ( 15 -15 ) N ;\n"
                "- U3 CELL ;\n"
                "END COMPONENTS\n"
                "PINS 1 ;\n"
                "- IN + NET IN + FIXED ( 4401541 2591681 ) N ;\n"
                "END PINS\nEND DESIGN\n"
            )

            report = snap_def(source, [lef], output, report_path)
            text = output.read_text()
            persisted = json.loads(report_path.read_text())

        self.assertIn("+ PLACED ( 4401540 2591680 )", text)
        self.assertIn("+ FIXED ( 20 -20 )", text)
        self.assertIn("+ FIXED ( 4401541 2591681 )", text)
        self.assertEqual(report["manufacturing_grid_dbu"], 10)
        self.assertEqual(report["placement_count"], 2)
        self.assertEqual(report["changed_components"], 2)
        self.assertEqual(report["changed_coordinates"], 3)
        self.assertEqual(report["max_delta_x_dbu"], 5)
        self.assertEqual(report["max_delta_y_dbu"], 5)
        self.assertEqual(persisted["output_sha256"], report["output_sha256"])
        self.assertNotEqual(report["input_sha256"], report["output_sha256"])

    def test_rejects_conflicting_or_nonintegral_grids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.lef"
            second = root / "second.lef"
            first.write_text("MANUFACTURINGGRID 0.005 ;\n")
            second.write_text("MANUFACTURINGGRID 0.0025 ;\n")

            with self.assertRaisesRegex(ValueError, "conflicting"):
                manufacturing_grid_microns([first, second])
            with self.assertRaisesRegex(ValueError, "not integral"):
                grid_in_def_units(manufacturing_grid_microns([second]), 200)

    def test_rejects_in_place_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "tech.lef"
            source = root / "placed.def"
            lef.write_text("MANUFACTURINGGRID 0.005 ;\n")
            source.write_text(
                "UNITS DISTANCE MICRONS 2000 ;\n"
                "COMPONENTS 1 ;\n- U1 CELL + PLACED ( 1 2 ) N ;\n"
                "END COMPONENTS\nEND DESIGN\n"
            )
            with self.assertRaisesRegex(ValueError, "must differ"):
                snap_def(source, [lef], source)


if __name__ == "__main__":
    unittest.main()
