import tempfile
from pathlib import Path
import unittest


from tools.routability_materialize_def import (
    UPDATED_COMPONENTS_RE,
    build_tcl,
    def_counts,
    infer_top_module,
    tcl_quote,
)


class RoutabilityMaterializeDefTest(unittest.TestCase):
    def test_counts_and_top_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verilog = root / "design.v"
            verilog.write_text("// module ignored\nmodule top(input clk);\nendmodule\n")
            design = root / "design.def"
            design.write_text(
                "COMPONENTS 12 ;\nEND COMPONENTS\n"
                "PINS 3 ;\nEND PINS\nNETS 9 ;\nEND NETS\nEND DESIGN\n"
            )
            self.assertEqual(infer_top_module(verilog), "top")
            self.assertEqual(def_counts(design), {
                "components": 12, "pins": 3, "nets": 9, "complete": True,
            })

    def test_tcl_quotes_metacharacters(self):
        self.assertEqual(tcl_quote('a b$[c]"d'), '"a b\\$\\[c\\]\\"d"')
        with self.assertRaises(ValueError):
            tcl_quote("bad\npath")

    def test_build_tcl_uses_floorplan_overlay(self):
        script = build_tcl(
            [Path("tech.lef"), Path("cells.lef")], Path("design.v"),
            "top", Path("placed.def"), Path("connected.def"),
        )
        self.assertIn('read_lef "tech.lef"', script)
        self.assertIn('link_design "top"', script)
        self.assertIn(
            'read_def -floorplan_initialize "placed.def"', script
        )
        self.assertIn('write_def "connected.def"', script)

    def test_updated_component_count(self):
        log = "[INFO ODB-0253]     Updated 938955 components.\n"
        self.assertEqual(
            [int(match.group(1)) for match in UPDATED_COMPONENTS_RE.finditer(log)],
            [938955],
        )


if __name__ == "__main__":
    unittest.main()
