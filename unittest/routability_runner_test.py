#!/usr/bin/env python3

import tempfile
import unittest
from unittest import mock
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_campaign import resolve_template_paths
from dreamplace.ops.routability_eval import EvaluationResult
from tools.routability_compare import (
    DEFAULT_EVALUATORS,
    apply_validation_policy,
    find_placed_def,
    parse_placement_metrics,
    parse_plugin_summaries,
    placement_output_name,
    run_evaluator_subprocess,
    main as compare_main,
)


class RoutabilityRunnerTest(unittest.TestCase):
    def test_default_evaluators_follow_golden_then_fallback_policy(self):
        self.assertEqual(DEFAULT_EVALUATORS, "openroad,innovus,rudy,gpugr")

    def test_comparison_marks_only_common_selected_role_authoritative(self):
        method_results = {
            "a": [EvaluationResult("openroad", "d"), EvaluationResult("gpugr", "d")],
            "b": [
                EvaluationResult("innovus", "d", status="failed"),
                EvaluationResult("gpugr", "d"),
            ],
        }
        serialized = [
            {"method": method, **result.to_dict()}
            for method, results in method_results.items() for result in results
        ]
        rows = [
            {"method": item["method"], "evaluator": item["backend"],
             "validation_role": "golden" if item["backend"] in ("openroad", "innovus")
             else "fallback_reference", "status": item["status"]}
            for item in serialized
        ]
        summary = apply_validation_policy(method_results, rows, serialized)
        self.assertEqual(summary["selected_role"], "fallback_reference")
        self.assertEqual(summary["selected_backends"], ["gpugr"])
        self.assertTrue(summary["fallback_used"])
        self.assertFalse(rows[0]["authoritative_for_comparison"])
        self.assertTrue(rows[1]["authoritative_for_comparison"])
        self.assertTrue(rows[3]["authoritative_for_comparison"])

    def test_failed_method_prevents_subset_from_being_validated(self):
        method_results = {
            "completed": [EvaluationResult("openroad", "d")],
            "placement_failed": [],
        }
        serialized = [
            {"method": "completed", **method_results["completed"][0].to_dict()}
        ]
        rows = [{
            "method": "completed", "evaluator": "openroad",
            "validation_role": "golden", "status": "ok",
        }]
        summary = apply_validation_policy(method_results, rows, serialized)
        self.assertEqual(summary["status"], "unvalidated")
        self.assertEqual(summary["selected_backends"], [])
        self.assertFalse(rows[0]["authoritative_for_comparison"])

    def test_early_stop_cannot_validate_only_completed_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(root / "input.def")}))
            presets.write_text(json.dumps({"hpwl": {}, "fails": {}}))

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult("openroad", "d", metrics={"wirelength": 1}).write_json(
                        eval_dir / "openroad.json"
                    )
                    return mock.Mock(returncode=0, stdout="")
                config = json.loads(Path(command[-1]).read_text())
                if Path(command[-1]).parent.name == "fails":
                    return mock.Mock(returncode=1, stdout="placement failed")
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(returncode=0, stdout="")

            with mock.patch("tools.routability_compare.subprocess.run", side_effect=run):
                status = compare_main([
                    "--base-config", str(base), "--presets", str(presets),
                    "--methods", "hpwl,fails", "--evaluators", "openroad",
                    "--output-dir", str(output), "--dreamplace-entry", "placer.py",
                ])

            comparison = json.loads((output / "comparison.json").read_text())
        self.assertEqual(status, 1)
        self.assertEqual(comparison["validation"]["status"], "unvalidated")
        self.assertEqual(comparison["validation"]["selected_backends"], [])

    def test_output_name_matches_dreamplace_precedence(self):
        config = {"def_input": "/d/chip.floorplan.def", "verilog_input": "/n/chip.v"}
        self.assertEqual(placement_output_name(config), "chip")
        self.assertEqual(placement_output_name({"def_input": "/d/chip.floorplan.def"}),
                         "chip.floorplan")

    def test_find_placed_def_recurses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "nested" / "chip.floorplan" / "chip.floorplan.gp.def"
            expected.parent.mkdir(parents=True)
            expected.write_text("END DESIGN\n")
            self.assertEqual(find_placed_def(root, "chip.floorplan"), expected)

    def test_template_paths_resolve_from_template(self):
        result = resolve_template_paths(
            {"ruplace_xplace_root": "../../Xplace", "routability_eval_openroad_binary": "openroad"},
            Path("/repo/configs"),
        )
        self.assertEqual(result["ruplace_xplace_root"], "/Xplace")
        self.assertEqual(result["routability_eval_openroad_binary"], "openroad")

    def test_parse_placement_metrics_uses_final_iteration(self):
        metrics = parse_placement_metrics(
            "iteration 0, wHPWL 1.2E+03, Overflow 9.0E-01\n"
            "iteration 1, wHPWL 8.5E+02, Overflow 2.5E-01\n"
        )
        self.assertEqual(metrics["placement_hpwl"], 850.0)
        self.assertEqual(metrics["density_overflow"], 0.25)

    def test_parse_plugin_summaries_flags_active_and_noop_plugins(self):
        logs = "\n".join([
            'INFO ROUTABILITY_PLUGIN_SUMMARY {"pipeline":{"gradient_calls":3,'
            '"gradient_gate_skips":1,"area_calls":2,"area_gate_skips":0},'
            '"plugins":{"local_gradient":{"gradient_attempts":2,'
            '"gradient_activations":2,"area_attempts":0,"area_activations":0,'
            '"metrics":{}},"pin_porosity":{"gradient_attempts":0,'
            '"gradient_activations":0,"area_attempts":2,"area_activations":0,'
            '"metrics":{"changed":false}}}}',
            'INFO ROUTABILITY_PLUGIN_SUMMARY {"pipeline":{"gradient_calls":1,'
            '"gradient_gate_skips":0,"area_calls":0,"area_gate_skips":0},'
            '"plugins":{"local_gradient":{"gradient_attempts":1,'
            '"gradient_activations":1,"area_attempts":0,"area_activations":0,'
            '"metrics":{}}}}',
        ])
        result = parse_plugin_summaries(logs)
        self.assertEqual(result["routability_plugin_status"], "partially_active")
        self.assertEqual(result["routability_plugin_attempts"], 5)
        self.assertEqual(result["routability_plugin_activations"], 3)
        self.assertEqual(
            result["routability_plugin_summary"]["plugins"]["pin_porosity"]["status"],
            "attempted_no_change",
        )

    def test_parse_plugin_summaries_marks_baseline_not_selected(self):
        result = parse_plugin_summaries("ordinary placement log")
        self.assertEqual(result["routability_plugin_status"], "not_selected")
        self.assertEqual(result["routability_plugin_activations"], 0)

    def test_evaluator_process_result_is_reconstructed(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        with tempfile.TemporaryDirectory() as tmp:
            request = EvaluationRequest(
                design_name="d", lef_input=["a.lef"], def_input="a.def",
                output_dir=tmp, options={"route_size": 64},
            )

            def completed(command, **kwargs):
                Path(tmp, "rudy.json").write_text(
                    '{"backend":"rudy","design_name":"d","status":"ok",'
                    '"runtime_sec":1.0,"metrics":{"wirelength":2},'
                    '"artifacts":{},"error":"","schema_version":1}'
                )
                return mock.Mock(returncode=0, stdout="done")

            with mock.patch("tools.routability_compare.subprocess.run", side_effect=completed) as run:
                result = run_evaluator_subprocess(request, "rudy", entry="evaluate.py")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metrics["wirelength"], 2)
        command = run.call_args.args[0]
        self.assertIn("route_size=64", command)

    def test_evaluator_process_crash_becomes_failed_result(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "tools.routability_compare.subprocess.run",
            return_value=mock.Mock(returncode=-11, stdout="native crash"),
        ):
            result = run_evaluator_subprocess(
                EvaluationRequest(design_name="d", output_dir=tmp),
                "pin_rudy", entry="evaluate.py",
            )
        self.assertEqual(result.status, "failed")
        self.assertIn("status -11", result.error)


if __name__ == "__main__":
    unittest.main()
