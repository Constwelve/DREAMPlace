#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval import EvaluationResult
from tools.routability_compare import main as compare_main
from tools.routability_post_placement import validate_post_placement_order
from tools.routability_select_survivors import routability_metric_profile


LEF = """UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MACRO CELL
  SIZE 0.01 BY 0.01 ;
END CELL
"""


def placed_def(a=0, b=20, c=50):
    return """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
ROW R0 SITE 0 0 N DO 10 BY 1 STEP 10 0 ;
COMPONENTS 3 ;
- A CELL + PLACED ( %d 0 ) N ;
- B CELL + PLACED ( %d 0 ) N ;
- C CELL + FIXED ( %d 0 ) N ;
END COMPONENTS
END DESIGN
""" % (a, b, c)


class RoutabilityPostPlacementTest(unittest.TestCase):
    def test_requires_sources_to_precede_derived_method(self):
        presets = {
            "hpwl": {},
            "legal": {"ruplace_post_placement": {
                "operation": "legal_whitespace_slide",
                "baseline_method": "hpwl",
                "oracle_method": "oracle",
                "acceptance_group": "legal",
            }},
            "oracle": {},
        }
        with self.assertRaisesRegex(ValueError, "must precede"):
            validate_post_placement_order(
                ["hpwl", "legal", "oracle"], presets
            )

    def test_compare_materializes_evaluates_and_accepts_legal_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_def = root / "input.def"
            lef = root / "cells.lef"
            base = root / "base.json"
            presets_path = root / "presets.json"
            output = root / "out"
            input_def.write_text(placed_def())
            lef.write_text(LEF)
            base.write_text(json.dumps({
                "def_input": str(input_def),
                "lef_input": [str(lef)],
            }))
            presets_path.write_text(json.dumps({
                "hpwl": {},
                "oracle": {},
                "legal": {
                    "ruplace_post_placement": {
                        "operation": "legal_whitespace_slide",
                        "baseline_method": "hpwl",
                        "oracle_method": "oracle",
                        "acceptance_group": "legal_slide",
                        "max_steps": 1,
                    }
                },
            }))

            def place(command, **kwargs):
                config_path = Path(command[-1])
                config = json.loads(config_path.read_text())
                method = config_path.parent.name
                placed = (
                    Path(config["result_dir"]) / "input" / "input.gp.def"
                )
                placed.parent.mkdir(parents=True)
                placed.write_text(
                    placed_def(a=40, b=40) if method == "oracle"
                    else placed_def()
                )
                return mock.Mock(returncode=0, stdout="")

            profile = routability_metric_profile("absolute_directional_v2")

            def evaluate(request, backend, **kwargs):
                method = Path(request.output_dir).parent.name
                value = 9.0 if method == "legal" else 10.0
                metrics = {
                    metric: value
                    for item_backend, metric in profile["primary"]
                    if item_backend == backend
                }
                result = EvaluationResult(
                    backend, "input", metrics=metrics, status="ok"
                )
                result.write_json(Path(request.output_dir) / (backend + ".json"))
                return result

            with mock.patch(
                "tools.routability_compare.subprocess.run", side_effect=place
            ), mock.patch(
                "tools.routability_compare.run_evaluator_subprocess",
                side_effect=evaluate,
            ):
                status = compare_main([
                    "--base-config", str(base),
                    "--presets", str(presets_path),
                    "--methods", "hpwl,oracle,legal",
                    "--evaluators", "rudy,gpugr",
                    "--output-dir", str(output),
                    "--dreamplace-entry", "placer.py",
                ])

            comparison = json.loads((output / "comparison.json").read_text())
            acceptance = json.loads(
                (output / "post_placement_acceptance/legal_slide.json").read_text()
            )
            derived = output / "legal/placement/input/input.gp.def"
            materialized = output / "post_placement_acceptance/legal_slide.def"

            self.assertEqual(status, 0)
            self.assertEqual(acceptance["decision"], "accepted")
            self.assertEqual(acceptance["selected_candidate"], "legal")
            self.assertEqual(derived.read_bytes(), materialized.read_bytes())
            self.assertEqual(
                comparison["post_placement_acceptance"]["legal_slide"][
                    "decision"
                ],
                "accepted",
            )


if __name__ == "__main__":
    unittest.main()
