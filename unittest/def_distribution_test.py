#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.analyze_def_distribution import analyze_def, parse_lef_cells


class DefDistributionTest(unittest.TestCase):
    def test_analyzer_separates_macro_and_standard_cell_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "cells.lef"
            deffile = root / "placed.def"
            lef.write_text(
                "MACRO STD\n  CLASS CORE ;\n  SIZE 1 BY 1 ;\nEND STD\n"
                "MACRO RAM\n  CLASS BLOCK ;\n  SIZE 2 BY 2 ;\nEND RAM\n"
            )
            deffile.write_text(
                "UNITS DISTANCE MICRONS 10 ;\n"
                "DIEAREA ( 0 0 ) ( 100 100 ) ;\n"
                "COMPONENTS 3 ;\n"
                "- m0 RAM + FIXED ( 10 10 ) N ;\n"
                "- u0 STD + PLACED ( 70 70 ) N ;\n"
                "- u1 STD_upper + PLACED ( 80 80 ) N ;\n"
                "END COMPONENTS\nEND DESIGN\n"
            )
            result = analyze_def(deffile, parse_lef_cells([lef]), 4, 4)
        self.assertEqual(result["counts"]["components"], 3)
        self.assertEqual(result["counts"]["fixed_macros"], 1)
        self.assertEqual(result["counts"]["standard_cells"], 2)
        self.assertEqual(result["counts"]["unknown_masters"], 0)
        self.assertGreater(result["macro_pattern"]["macro_covered_bin_fraction"], 0)
        self.assertGreater(result["component_count_grid"]["empty_bin_fraction"], 0)


if __name__ == "__main__":
    unittest.main()
