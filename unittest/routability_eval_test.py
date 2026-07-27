#!/usr/bin/env python3

import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval.base import EvaluationResult, map_statistics
from dreamplace.ops.routability_eval.cugr import (
    DEFAULT_RRR_ITERS,
    add_gcell_grid,
    filter_duplicate_special_nets,
    merge_lefs,
    parse_cugr_log,
)
from dreamplace.ops.routability_eval.innovus import innovus_fatal_error, parse_innovus_log
from dreamplace.ops.routability_eval.openroad import (
    parse_openroad_congestion_report,
    parse_openroad_log,
)
from dreamplace.ops.routability_eval.registry import (
    DEFAULT_VALIDATION_EVALUATORS,
    build_evaluator,
    common_validation_backends,
    select_common_validation_role,
    validation_role,
)


class RoutabilityEvaluatorTest(unittest.TestCase):
    def test_normalized_result_schema(self):
        result = EvaluationResult(
            backend="fake", design_name="d", metrics={"wirelength": 10.0}
        ).to_dict()
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"]["wirelength"], 10.0)

    def test_sparse_map_score_does_not_hide_hotspot(self):
        import torch

        value = torch.zeros(10, 10)
        value[-1, -1] = 10.0
        metrics = map_statistics(value)
        self.assertEqual(metrics["congestion_score_p95"], 0.0)
        self.assertGreater(metrics["congestion_score"], 0.0)
        self.assertEqual(metrics["congestion_score"], metrics["congestion_score_p99"])

    def test_zero_rudy_map_is_invalid_for_nonempty_design(self):
        import torch
        from dreamplace.ops.routability_eval.rudy import (
            routing_pin_coverage,
            zero_map_for_nonempty_design,
            zero_map_error,
        )

        self.assertTrue(zero_map_for_nonempty_design(torch.zeros(2, 2), 3))
        self.assertFalse(zero_map_for_nonempty_design(torch.zeros(2, 2), 0))
        self.assertFalse(zero_map_for_nonempty_design(torch.eye(2), 3))
        coverage = routing_pin_coverage(
            torch.tensor([-2.0, -1.0]), torch.tensor([5.0, 6.0]), 0, 0, 10, 10
        )
        self.assertEqual(coverage["pins_in_routing_region"], 0)
        self.assertIn("unplaced/collapsed", zero_map_error(coverage))

    def test_registry_keeps_backends_independent(self):
        self.assertEqual(build_evaluator("cugr").name, "cugr")
        self.assertEqual(build_evaluator("openroad").name, "openroad")
        self.assertEqual(build_evaluator("innovus").name, "innovus")
        with self.assertRaisesRegex(ValueError, "Unknown evaluator"):
            build_evaluator("missing")

    def test_evaluator_validation_roles_match_policy(self):
        self.assertEqual(validation_role("openroad"), "golden")
        self.assertEqual(validation_role("innovus"), "golden")
        self.assertEqual(validation_role("rudy"), "fallback_reference")
        self.assertEqual(validation_role("gpugr"), "fallback_reference")
        self.assertEqual(validation_role("pin_rudy"), "diagnostic_only")
        self.assertEqual(validation_role("cugr"), "diagnostic_only")
        self.assertEqual(
            DEFAULT_VALIDATION_EVALUATORS,
            ("openroad", "innovus", "rudy", "gpugr"),
        )

    def test_different_golden_backends_are_not_a_common_comparison(self):
        results = {
            "a": [EvaluationResult("openroad", "d"), EvaluationResult("rudy", "d")],
            "b": [EvaluationResult("innovus", "d"), EvaluationResult("gpugr", "d")],
        }
        self.assertIsNone(select_common_validation_role(results))

    def test_common_validation_role_prefers_shared_golden_backend(self):
        results = {
            "a": [EvaluationResult("openroad", "d"), EvaluationResult("rudy", "d")],
            "b": [EvaluationResult("openroad", "d"), EvaluationResult("gpugr", "d")],
        }
        self.assertEqual(select_common_validation_role(results), "golden")
        self.assertEqual(common_validation_backends(results, "golden"), ("openroad",))

    def test_common_validation_role_falls_back_without_common_golden(self):
        results = {
            "a": [EvaluationResult("openroad", "d"), EvaluationResult("rudy", "d")],
            "b": [
                EvaluationResult("innovus", "d", status="unsupported"),
                EvaluationResult("rudy", "d"),
            ],
        }
        self.assertEqual(select_common_validation_role(results), "fallback_reference")

    def test_diagnostic_only_results_cannot_validate(self):
        results = {
            "a": [EvaluationResult("xplace", "d")],
            "b": [EvaluationResult("cugr", "d")],
        }
        self.assertIsNone(select_common_validation_role(results))

    def test_cugr_rejects_empty_route_mode(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        result = build_evaluator("cugr").evaluate(EvaluationRequest(
            design_name="d", lef_input=["unused.lef"], def_input="unused.def",
            options={"rrr_iters": 0},
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertIn("rrr_iters >= 1", result.error)

    def test_cugr_uses_one_validated_rrr_pass_by_default(self):
        self.assertEqual(DEFAULT_RRR_ITERS, 1)

    def test_cugr_filter_diagnostic_does_not_mask_empty_router_metrics(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("cugr")
        with tempfile.TemporaryDirectory() as tmp:
            lef = Path(tmp) / "input.lef"
            deffile = Path(tmp) / "input.def"
            lef.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
            deffile.write_text(
                "VERSION 5.8 ;\nDIEAREA ( 0 0 ) ( 100 100 ) ;\n"
                "SPECIALNETS 1 ;\n- VDD ( * VDD ) ;\nEND SPECIALNETS\n"
                "NETS 1 ;\n- VDD ( U1 VDD ) ;\nEND NETS\nEND DESIGN\n"
            )
            with mock.patch.object(evaluator, "run", return_value=("", None)):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=[str(lef)], def_input=str(deffile),
                    output_dir=tmp, options={"cugr_root": tmp},
                ))
        self.assertEqual(result.status, "failed")
        self.assertIn("no score block", result.error)

    def test_gpugr_child_uses_loaded_package_root(self):
        from dreamplace.ops.routability_eval import EvaluationRequest
        from dreamplace.ops.routability_eval import xplace as xplace_module

        evaluator = build_evaluator("gpugr")
        failure = EvaluationResult(
            backend="gpugr", design_name="d", status="failed", error="stop"
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            evaluator, "run", return_value=(None, failure)
        ) as run:
            evaluator.evaluate(EvaluationRequest(
                design_name="d", lef_input=["input.lef"], def_input="input.def",
                output_dir=tmp,
            ))
        self.assertEqual(
            run.call_args.kwargs["cwd"],
            Path(xplace_module.__file__).resolve().parents[3],
        )
        command = run.call_args.args[1]
        self.assertEqual(command[command.index("--route-x-size") + 1], "128")
        self.assertEqual(command[command.index("--route-y-size") + 1], "128")

    def test_gpugr_invalid_artifact_is_a_failed_result(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("gpugr")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            evaluator, "run", return_value=("", None)
        ):
            result = evaluator.evaluate(EvaluationRequest(
                design_name="d", lef_input=["input.lef"], def_input="input.def",
                output_dir=tmp,
            ))
        self.assertEqual(result.status, "failed")
        self.assertIn("invalid gpugr result artifact", result.error)

    def test_openroad_empty_metrics_are_a_failed_result(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("openroad")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            evaluator, "run", return_value=("Total routing overflow: 3\n", None)
        ):
            result = evaluator.evaluate(EvaluationRequest(
                design_name="d", lef_input=["input.lef"], def_input="input.def",
                output_dir=tmp,
            ))
        self.assertEqual(result.status, "failed")
        self.assertIn("without positive routed wirelength", result.error)

    def test_nctugr_missing_overflow_artifact_is_a_failed_result(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("nctugr")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            evaluator, "run", return_value=("", None)
        ):
            result = evaluator.evaluate(EvaluationRequest(
                design_name="d", aux_input="input.aux", output_dir=tmp,
                options={"pl_input": "input.pl", "nctugr_root": tmp},
            ))
        self.assertEqual(result.status, "failed")
        self.assertIn("without an overflow-info artifact", result.error)

    def test_add_gcell_grid_preserves_design(self):
        source_text = """VERSION 5.8 ;
DESIGN tiny ;
DIEAREA ( 0 0 ) ( 1000 2000 ) ;
END DESIGN
"""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "in.def"
            output = Path(tmp) / "out.def"
            source.write_text(source_text)
            add_gcell_grid(source, output, route_size=100)
            result = output.read_text()
        self.assertIn("GCELLGRID X", result)
        self.assertIn("GCELLGRID Y", result)
        self.assertEqual(result.count("END DESIGN"), 1)

    def test_cugr_filters_only_regular_nets_duplicated_in_specialnets(self):
        source_text = """VERSION 5.8 ;
SPECIALNETS 2 ;
- VDD ( * VDD ) + USE POWER ;
- VSS ( * VSS ) + USE GROUND ;
END SPECIALNETS
NETS 3 ;
- signal ( U1 A ) ( U2 Z ) ;
- VDD
  ( U1 VDD )
  + USE POWER
 ;
- escaped\\[0\\] ( U1 A ) ( U2 Z ) ;
END NETS
END DESIGN
"""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "in.def"
            output = Path(tmp) / "out.def"
            source.write_text(source_text)
            removed = filter_duplicate_special_nets(source, output)
            text = output.read_text()
        self.assertEqual(removed, ["VDD"])
        self.assertIn("NETS 2 ;", text)
        self.assertEqual(text.count("- VDD"), 1)
        self.assertIn("- signal", text)
        self.assertIn(r"- escaped\[0\]", text)

    def test_router_log_parsers(self):
        cugr = parse_cugr_log(
            "wirelength | 123\n# vias | 4\nshort | 5.5\ntotal score = 99\n"
        )
        self.assertEqual(cugr["wirelength"], 123.0)
        self.assertEqual(cugr["estimated_shorts"], 5.5)
        openroad = parse_openroad_log(
            "Total Global Route Wirelength: 88\nTotal routing overflow: 3\n"
        )
        self.assertEqual(openroad["wirelength"], 88.0)
        self.assertEqual(openroad["overflow"], 3.0)
        innovus = parse_innovus_log(
            "RLEVAL_WIRELENGTH 77\nHorizontal congestion: 4.5%\n"
        )
        self.assertEqual(innovus["wirelength"], 77.0)
        self.assertEqual(innovus["horizontal_congestion"], 4.5)
        egr = parse_innovus_log(
            "Overflow after Early Global Route 1.25% H + 2.5% V\n"
            "Total length: 2464um, number of vias: 2706\n"
        )
        self.assertEqual(egr["wirelength"], 2464.0)
        self.assertEqual(egr["horizontal_congestion"], 1.25)
        self.assertEqual(egr["vertical_congestion"], 2.5)
        self.assertEqual(egr["vias"], 2706.0)
        report = parse_innovus_log(
            "Overflow after Early Global Route 1.25% H + 2.5% V\n"
            "Overflow: 4186671 = 2067272 (21.66% H) + 2119399 (22.21% V)\n"
            "RLEVAL_ROUTED_WIRELENGTH 77\nRLEVAL_DRC_COUNT 13\n"
        )
        self.assertEqual(report["total_overflow"], 4186671.0)
        self.assertEqual(report["horizontal_overflow"], 2067272.0)
        self.assertEqual(report["vertical_overflow"], 2119399.0)
        self.assertEqual(report["horizontal_congestion"], 21.66)
        self.assertEqual(report["vertical_congestion"], 22.21)
        self.assertEqual(report["egr_horizontal_congestion"], 1.25)
        self.assertEqual(report["drc_violations"], 13.0)
        global_detail = parse_innovus_log(
            "Overflow after GR: 0.00% H + 0.08% V\n"
            "Total number of vias = 2663\n"
            "Total number of vias = 2806\n"
        )
        self.assertEqual(global_detail["horizontal_congestion"], 0.0)
        self.assertEqual(global_detail["vertical_congestion"], 0.08)
        self.assertEqual(global_detail["vias"], 2806.0)

    def test_openroad_congestion_report_keeps_directions_separate(self):
        report = parse_openroad_congestion_report("""
violation type: Horizontal congestion
\tcomment: capacity:45 usage:52 overflow:7
violation type: Vertical congestion
\tcomment: capacity:47 usage:52 overflow:5
violation type: Horizontal congestion
\tcomment: capacity:42 usage:47 overflow:5
""")
        self.assertEqual(report["horizontal_overflow"], 12.0)
        self.assertEqual(report["vertical_overflow"], 5.0)
        self.assertEqual(report["total_overflow"], 17.0)
        self.assertEqual(report["horizontal_overflow_edges"], 2)
        self.assertEqual(report["vertical_overflow_edges"], 1)

    def test_innovus_detailed_mode_requires_and_emits_drc(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("innovus")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "input.lef"
            deffile = root / "input.def"
            verilog = root / "input.v"
            lef.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
            deffile.write_text("VERSION 5.8 ;\nEND DESIGN\n")
            verilog.write_text("module d; endmodule\n")
            with mock.patch.object(
                evaluator, "run",
                return_value=(
                    "Overflow: 0 = 0 (0.00% H) + 0 (0.00% V)\n"
                    "RLEVAL_ROUTED_WIRELENGTH 10\nRLEVAL_DRC_COUNT 0\n",
                    None,
                ),
            ):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=[str(lef)], def_input=str(deffile),
                    verilog_input=str(verilog), output_dir=tmp,
                    options={"cadence_mounted_root": tmp, "innovus_route_mode": "detailed"},
                ))
            script = (root / "innovus_eval.tcl").read_text()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metrics["drc_violations"], 0.0)
        self.assertIn("globalDetailRoute", script)
        self.assertIn("-routeWithTimingDriven false", script)
        self.assertIn("verify_drc", script)

    def test_openroad_detailed_mode_requires_drc_metric(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("openroad")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            evaluator, "run", return_value=("Total Global Route Wirelength: 10\n", None)
        ):
            result = evaluator.evaluate(EvaluationRequest(
                design_name="d", lef_input=["input.lef"], def_input="input.def",
                output_dir=tmp, options={"openroad_route_mode": "detailed"},
            ))
            script = (Path(tmp) / "openroad_eval.tcl").read_text()
        self.assertEqual(result.status, "failed")
        self.assertIn("without a DRC count", result.error)
        self.assertIn("detailed_route", script)
        self.assertIn("-detailed_route -summary", script)

    def test_openroad_detailed_mode_uses_final_route_metrics(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("openroad")
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "openroad_metrics.json"

            def run_with_metrics(*args, **kwargs):
                metrics_path.write_text(json.dumps({
                    "global_route__wirelength": 6432,
                    "global_route__vias": 2688,
                    "route__wirelength": 4012,
                    "route__vias": 2793,
                    "route__drc_errors": 0,
                    "route__drc_errors__iter:0": 267,
                }))
                return "Number of violations = 267\n", None

            with mock.patch.object(evaluator, "run", side_effect=run_with_metrics):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=["input.lef"], def_input="input.def",
                    output_dir=tmp, options={"openroad_route_mode": "detailed"},
                ))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metrics["wirelength"], 4012)
        self.assertEqual(result.metrics["vias"], 2793)
        self.assertEqual(result.metrics["drc_violations"], 0)

    def test_innovus_fatal_error_detects_hidden_wrapper_failure(self):
        text = "launcher returned zero\n**ERROR: (IMPTCM-48): bad option\n"
        self.assertIn("IMPTCM-48", innovus_fatal_error(text))
        self.assertEqual(innovus_fatal_error("**WARN: harmless\n"), "")

    def test_merge_lefs_keeps_one_library_terminator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tech = root / "tech.lef"
            cells = root / "cells.lef"
            merged = root / "merged.lef"
            tech.write_text("VERSION 5.8 ;\nLAYER M1\nEND M1\nEND LIBRARY\n")
            cells.write_text("VERSION 5.8 ;\nMACRO INV\nEND INV\nEND LIBRARY\n")
            merge_lefs([tech, cells], merged)
            text = merged.read_text()
        self.assertEqual(text.upper().count("END LIBRARY"), 1)
        self.assertEqual(text.upper().count("VERSION 5.8"), 1)
        self.assertIn("MACRO INV", text)


if __name__ == "__main__":
    unittest.main()
