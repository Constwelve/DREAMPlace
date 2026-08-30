#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_generate_report_figures import EvidenceStore, innovus_rows
from tools.routability_plot_spatial import parse_def_locations


class RoutabilityReportFiguresTest(unittest.TestCase):
    def test_innovus_rows_uses_full_successful_summary_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = "campaign/golden_innovus"
            eval_dir = (
                root / marker / "case_a" / "seed_1000" / "case_a" /
                "methods" / "hpwl" / "evaluation"
            )
            eval_dir.mkdir(parents=True)
            metrics = {
                "wirelength": 12.5,
                "horizontal_congestion": 0.2,
                "vertical_congestion": 0.3,
                "drc_violations": 4.0,
                "short_violations": 3.0,
                "vias": 8.0,
            }
            (eval_dir / "summary.json").write_text(json.dumps({
                "results": [{
                    "backend": "innovus", "status": "ok", "metrics": metrics,
                }],
            }))
            failed_dir = (
                root / marker / "case_a" / "seed_2000" / "case_a" /
                "methods" / "hpwl" / "evaluation"
            )
            failed_dir.mkdir(parents=True)
            (failed_dir / "summary.json").write_text(json.dumps({
                "results": [{
                    "backend": "innovus", "status": "timeout", "metrics": {},
                }],
            }))

            store = EvidenceStore(root=root)
            try:
                rows = innovus_rows(store, marker)
            finally:
                store.close()
            self.assertEqual(rows, {("case_a", "seed_1000", "hpwl"): metrics})

    def test_parse_def_locations_accepts_multiline_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "placed.def"
            path.write_text(
                "VERSION 5.8 ;\n"
                "DIEAREA ( 10 20 ) ( 110 220 ) ;\n"
                "COMPONENTS 2 ;\n"
                "- u0 NAND2_X1\n"
                "  + PLACED ( 30 40 ) N ;\n"
                "- u1 NOR2_X1 + FIXED ( 50 60 ) FN ;\n"
                "END COMPONENTS\n"
                "END DESIGN\n"
            )
            diearea, locations = parse_def_locations(path)
            self.assertEqual(diearea, (10, 20, 110, 220))
            self.assertEqual(locations.tolist(), [[30.0, 40.0], [50.0, 60.0]])


if __name__ == "__main__":
    unittest.main()
