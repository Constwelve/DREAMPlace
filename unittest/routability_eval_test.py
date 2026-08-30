#!/usr/bin/env python3

import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock
from pathlib import Path
import shutil
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval.base import (
    ace_congestion,
    directional_map_statistics,
    EvaluationRequest,
    EvaluationResult,
    RoutabilityEvaluator,
    map_statistics,
)
from dreamplace.ops.routability_eval.cugr import (
    DEFAULT_RRR_ITERS,
    add_gcell_grid,
    filter_duplicate_special_nets,
    merge_lefs,
    parse_cugr_log,
)
from dreamplace.ops.routability_eval.innovus import (
    innovus_fatal_error,
    parse_innovus_connectivity_report,
    parse_innovus_drc_report,
    parse_innovus_drc_report_file,
    parse_innovus_log,
    parse_innovus_route_violation_summary,
    parse_innovus_verify_drc_summary,
)
from dreamplace.ops.routability_eval.openroad import (
    parse_openroad_congestion_report,
    parse_openroad_detailed_route_metrics,
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

    def test_timeout_terminates_router_process_group(self):
        evaluator = RoutabilityEvaluator()
        evaluator.name = "timeout_probe"
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_path = Path(tmp) / "child.pid"
            script = Path(tmp) / "spawn_child.py"
            script.write_text(
                "import pathlib, subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(60)'])\n"
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
                "print('ready', flush=True)\n"
                "time.sleep(60)\n"
            )
            output, result = evaluator.run(
                EvaluationRequest(
                    design_name="d", output_dir=tmp, timeout_sec=1
                ),
                [sys.executable, str(script), str(child_pid_path)],
            )
            self.assertIsNone(output)
            self.assertEqual(result.status, "timeout")
            self.assertIn("ready", Path(result.artifacts["log"]).read_text())
            child_pid = int(child_pid_path.read_text())
            deadline = time.time() + 2
            while Path("/proc/%d/stat" % child_pid).exists() and time.time() < deadline:
                state = Path("/proc/%d/stat" % child_pid).read_text().split()[2]
                if state == "Z":
                    break
                time.sleep(0.05)
            if Path("/proc/%d/stat" % child_pid).exists():
                self.assertEqual(
                    Path("/proc/%d/stat" % child_pid).read_text().split()[2], "Z"
                )

    def test_sparse_map_score_does_not_hide_hotspot(self):
        import torch

        value = torch.zeros(10, 10)
        value[-1, -1] = 10.0
        metrics = map_statistics(value)
        self.assertEqual(metrics["congestion_score_p95"], 0.0)
        self.assertGreater(metrics["congestion_score"], 0.0)
        self.assertEqual(metrics["congestion_score"], metrics["congestion_score_p99"])

    def test_directional_statistics_preserve_preoverflow_pressure(self):
        import torch

        horizontal = torch.tensor([[0.2, 0.8], [0.4, 0.6]])
        vertical = torch.tensor([[0.1, 0.3], [0.5, 0.7]])
        metrics = directional_map_statistics(
            torch.stack((horizontal, vertical))
        )

        self.assertEqual(metrics["horizontal_overflow_sum"], 0.0)
        self.assertEqual(metrics["vertical_overflow_sum"], 0.0)
        self.assertAlmostEqual(metrics["horizontal_utilization_max"], 0.8)
        self.assertAlmostEqual(metrics["vertical_utilization_max"], 0.7)
        self.assertGreater(metrics["horizontal_ace"], metrics["vertical_ace"])
        self.assertGreater(ace_congestion(horizontal), 0.0)

    def test_directional_statistics_reject_malformed_map(self):
        import torch

        with self.assertRaisesRegex(ValueError, "shape"):
            directional_map_statistics(torch.ones(4, 4))

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

    def test_rudy_honors_requested_routing_grid(self):
        from dreamplace.ops.routability_eval.rudy import requested_routing_grid

        placedb = SimpleNamespace(
            num_routing_grids_x=512, num_routing_grids_y=384
        )
        self.assertEqual(requested_routing_grid(placedb, {}), (512, 384))
        self.assertEqual(
            requested_routing_grid(placedb, {"route_size": 256}),
            (256, 256),
        )
        self.assertEqual(
            requested_routing_grid(
                placedb, {"route_x_size": 128, "route_y_size": 192}
            ),
            (128, 192),
        )
        with self.assertRaisesRegex(ValueError, "must be positive"):
            requested_routing_grid(placedb, {"route_x_size": 0})

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
        self.assertEqual(
            command[command.index("--def-input") + 1],
            str(Path("input.def").resolve()),
        )
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

    def test_gpugr_requires_directional_v2_artifact_when_requested(self):
        import torch
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("gpugr")
        with tempfile.TemporaryDirectory() as tmp:
            torch.save({
                "utilization_map": torch.ones(2, 2),
                "metrics": {"gr_wirelength": 1.0},
            }, Path(tmp) / "gpugr.pt")
            with mock.patch.object(evaluator, "run", return_value=("", None)):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=["input.lef"],
                    def_input="input.def", output_dir=tmp,
                    options={"required_directional_metric_schema_version": 2},
                ))
        self.assertEqual(result.status, "failed")
        self.assertIn("hv_utilization_map required", result.error)

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
        repeated_global_detail = parse_innovus_log(
            "Overflow after GR: 5.00% H + 6.00% V\n"
            "Overflow after GR: 1.00% H + 2.00% V\n"
        )
        self.assertEqual(repeated_global_detail["horizontal_congestion"], 1.0)
        self.assertEqual(repeated_global_detail["vertical_congestion"], 2.0)
        routed = parse_innovus_log(
            "#Total number of routable nets = 468.\n"
            "#467 routable nets have routed wires.\n"
        )
        self.assertEqual(routed["unrouted_nets"], 1.0)

    def test_innovus_connectivity_and_short_parsers(self):
        connectivity = parse_innovus_connectivity_report("""
Begin Summary
    2 Problem(s) (IMPVFC-92): Pieces of the net are not connected together.
    3 Problem(s) (IMPVFC-94): The net has dangling wire(s).
    5 total info(s) created.
End Summary
""")
        self.assertEqual(connectivity["connectivity_violations"], 5.0)
        self.assertEqual(connectivity["open_violations"], 5.0)
        self.assertEqual(parse_innovus_drc_report(
            "SHORT: first\nMETAL: one\n  SHORT: second\n"
            "  Total Violations : 7 Viols.\n"
        )["short_violations"], 2.0)
        self.assertEqual(parse_innovus_drc_report(
            "SHORT: first\n  Total Violations : 7 Viols.\n"
        )["drc_violations"], 7.0)
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "innovus_drc.rpt"
            report.write_text(
                "SHORT: first\nMETAL: one\n  short: second\nCUTSPACING: one\n"
                "  Total Violations : 4 Viols.\n"
            )
            metrics = parse_innovus_drc_report_file(report)
            self.assertEqual(metrics["short_violations"], 2.0)
            self.assertEqual(metrics["drc_violations"], 4.0)
        clean = parse_innovus_connectivity_report("""
Begin Summary
    Found no problems or warnings.
End Summary
""")
        self.assertEqual(clean["connectivity_violations"], 0.0)
        self.assertEqual(clean["open_violations"], 0.0)

    def test_innovus_drc_report_file_uses_known_short_tail_fast_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "innovus_drc.rpt"
            report.write_text(
                "SHORT: outside tail\n"
                + "x" * (1024 * 1024 + 1)
                + "\n  Total Violations : 9 Viols.\n"
            )
            fast = parse_innovus_drc_report_file(
                report, known_short_violations=7
            )
            fallback = parse_innovus_drc_report_file(report)
        self.assertEqual(fast["drc_violations"], 9.0)
        self.assertEqual(fast["short_violations"], 7.0)
        self.assertEqual(fallback["drc_violations"], 9.0)
        self.assertEqual(fallback["short_violations"], 1.0)

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

    def test_innovus_final_route_matrix_keeps_pg_inclusive_drc_separate(self):
        metrics = parse_innovus_route_violation_summary("""
#    By Layer and Type :
#             MetSpc    Short   CShort   Totals
#    M1            2        3        4        9
#    Totals        2        3        4        9
#Total number of DRC violations = 9
""")
        self.assertEqual(metrics["router_drc_violations"], 9.0)
        self.assertEqual(metrics["router_short_violations"], 7.0)

    def test_innovus_verify_drc_summary_extracts_pg_excluded_counts(self):
        metrics = parse_innovus_verify_drc_summary("""
  Verification Complete : 12 Viols.

 Violation Summary By Layer and Type:

              Short   MetSpc   CShort   Totals
    M3            6        3        2       11
    via3          0        0        1        1
    Totals        6        3        3       12

 *** End Verify DRC (CPU TIME: 0:00:01)
""")
        self.assertEqual(metrics["verify_drc_violations"], 12.0)
        self.assertEqual(metrics["verify_short_violations"], 9.0)

        clean = parse_innovus_verify_drc_summary("""
  Verification Complete : 0 Viols.
 *** End Verify DRC (CPU TIME: 0:00:00.0)
******** End: VERIFY CONNECTIVITY ********
  Verification Complete : 0 Viols.  0 Wrngs.
""")
        self.assertEqual(clean["verify_drc_violations"], 0.0)
        self.assertEqual(clean["verify_short_violations"], 0.0)

        incomplete = parse_innovus_verify_drc_summary("""
  Verification Complete : 7 Viols.
 *** End Verify DRC (CPU TIME: 0:00:00.0)
""")
        self.assertEqual(incomplete["verify_drc_violations"], 7.0)
        self.assertNotIn("verify_short_violations", incomplete)

    def test_openroad_detailed_route_parser_uses_final_short_table(self):
        report = parse_openroad_detailed_route_metrics("""
Number of nets: 12
[INFO DRT-0199] Number of violations = 4.
Viol/Layer Metal2 Metal3
Short 2 1
[INFO DRT-0267] done
[INFO DRT-0199] Number of violations = 1.
Viol/Layer Metal2
Metal Spacing 1
[INFO DRT-0267] done
""", {"route__net": 11})
        self.assertEqual(report["unrouted_nets"], 1.0)
        self.assertEqual(report["short_violations"], 0.0)

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
            def run_with_reports(*args, **kwargs):
                work = Path(kwargs["cwd"])
                (work / "innovus_drc.rpt").write_text(
                    "  Total Violations : 0 Viols.\n"
                )
                (work / "innovus_connectivity.rpt").write_text(
                    "Begin Summary\n    0 total info(s) created.\nEnd Summary\n"
                )
                return (
                    "Overflow: 0 = 0 (0.00% H) + 0 (0.00% V)\n"
                    "#Total number of routable nets = 2.\n"
                    "#2 routable nets have routed wires.\n"
                    "RLEVAL_ROUTED_WIRELENGTH 10\n",
                    None,
                )

            with mock.patch.object(evaluator, "run", side_effect=run_with_reports):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=[str(lef)], def_input=str(deffile),
                    verilog_input=str(verilog), output_dir=tmp,
                    options={"cadence_mounted_root": tmp, "innovus_route_mode": "detailed"},
                ))
            script = (root / "innovus_eval.tcl").read_text()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metrics["drc_violations"], 0.0)
        self.assertEqual(result.metrics["unrouted_nets"], 0.0)
        self.assertEqual(result.metrics["short_violations"], 0.0)
        self.assertEqual(result.metrics["connectivity_violations"], 0.0)
        self.assertIn("globalDetailRoute", script)
        self.assertIn("-routeWithTimingDriven false", script)
        self.assertIn("dbget top.nets.wires.length", script)
        self.assertNotIn("reportWire -summary", script)
        self.assertIn("verify_drc", script)
        self.assertIn("verifyConnectivity -type regular", script)
        self.assertNotIn("rleval_drc_fh", script)

    def test_innovus_compact_drc_uses_verifier_stdout_and_typed_short_total(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        evaluator = build_evaluator("innovus")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in (
                ("input.lef", "VERSION 5.8 ;\nEND LIBRARY\n"),
                ("input.def", "VERSION 5.8 ;\nEND DESIGN\n"),
                ("input.v", "module d; endmodule\n"),
            ):
                (root / name).write_text(content)

            def run_with_compact_reports(*args, **kwargs):
                work = Path(kwargs["cwd"])
                (work / "innovus_connectivity.rpt").write_text(
                    "Begin Summary\n0 total info(s) created.\nEnd Summary\n"
                )
                return (
                    "Overflow: 0 = 0 (0.00% H) + 0 (0.00% V)\n"
                    "#Total number of routable nets = 2.\n"
                    "#2 routable nets have routed wires.\n"
                    "# By Layer and Type :\n"
                    "# MetSpc Short CShort Totals\n"
                    "# Totals 5 6 2 13\n"
                    "#Total number of DRC violations = 13\n"
                    "RLEVAL_ROUTED_WIRELENGTH 10\n"
                    "Verification Complete : 12 Viols.\n\n"
                    "Violation Summary By Layer and Type:\n"
                    "Short MetSpc CShort Totals\n"
                    "Totals 6 4 2 12\n"
                    "*** End Verify DRC\n",
                    None,
                )

            with mock.patch.object(evaluator, "run", side_effect=run_with_compact_reports):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=[str(root / "input.lef")],
                    def_input=str(root / "input.def"),
                    verilog_input=str(root / "input.v"), output_dir=tmp,
                    options={
                        "cadence_mounted_root": tmp,
                        "innovus_route_mode": "detailed",
                        "innovus_compact_drc": True,
                    },
                ))
            script = (root / "innovus_eval.tcl").read_text()
            drc_text = (root / "innovus_drc.rpt").read_text()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metrics["drc_violations"], 12.0)
        self.assertEqual(result.metrics["short_violations"], 8.0)
        self.assertNotIn("dbGet top.markers", script)
        self.assertNotIn("-report", script.split("verify_drc", 1)[1].splitlines()[0])
        self.assertIn("Total Violations : 12 Viols.", drc_text)
        self.assertIn("Total Short Violations : 8 Viols.", drc_text)

    def test_innovus_failure_retains_native_work_directory(self):
        from dreamplace.ops.routability_eval import (
            EvaluationRequest, EvaluationResult,
        )

        evaluator = build_evaluator("innovus")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            for name, content in (
                ("input.lef", "VERSION 5.8 ;\nEND LIBRARY\n"),
                ("input.def", "VERSION 5.8 ;\nEND DESIGN\n"),
                ("input.v", "module d; endmodule\n"),
            ):
                (root / name).write_text(content)

            def fail_with_native_log(request, command, cwd=None, env=None):
                work = Path(cwd)
                (work / "innovus.log").write_text("partial native log\n")
                return None, EvaluationResult(
                    backend="innovus", design_name=request.design_name,
                    status="timeout", error="timeout after 10 seconds",
                )

            with mock.patch.object(evaluator, "run", side_effect=fail_with_native_log):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=[str(root / "input.lef")],
                    def_input=str(root / "input.def"),
                    verilog_input=str(root / "input.v"), output_dir=str(output),
                    options={
                        "cadence_mounted_root": str(root),
                        "innovus_route_mode": "detailed",
                    },
                ))

            retained = Path(result.artifacts["work_dir"])
            self.assertEqual(result.status, "timeout")
            self.assertTrue(retained.is_dir())
            self.assertEqual(
                Path(result.artifacts["native_innovus_log"]).read_text(),
                "partial native log\n",
            )
            shutil.rmtree(retained)

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
                    "route__net": 12,
                }))
                (Path(tmp) / "openroad_congestion.rpt").write_text("")
                return "Number of nets: 12\nNumber of violations = 267\n", None

            with mock.patch.object(evaluator, "run", side_effect=run_with_metrics):
                result = evaluator.evaluate(EvaluationRequest(
                    design_name="d", lef_input=["input.lef"], def_input="input.def",
                    output_dir=tmp, options={"openroad_route_mode": "detailed"},
                ))
                script = (Path(tmp) / "openroad_eval.tcl").read_text()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metrics["wirelength"], 4012)
        self.assertEqual(result.metrics["vias"], 2793)
        self.assertEqual(result.metrics["drc_violations"], 0)
        self.assertEqual(result.metrics["unrouted_nets"], 0.0)
        self.assertEqual(result.metrics["short_violations"], 0.0)
        self.assertIn("openroad_congestion.raw.rpt", script)
        self.assertIn("file copy -force", script)

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
