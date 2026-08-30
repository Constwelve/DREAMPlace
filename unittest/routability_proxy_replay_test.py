#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


from dreamplace.ops.routability_eval import EvaluationResult
from tools.routability_proxy_replay import (
    PROXY_REQUIRED_METRICS,
    expected_sources,
    main,
    mandatory_proxy_gate,
    matched_resolution_config,
    proxy_metric_contract_error,
    validated_replay_matches,
)


def placement_provenance(method):
    plugins = [] if method == "hpwl" else ["local_gradient"]
    return {
        "method": method,
        "status": "ok",
        "routability_plugin_status": "active" if plugins else "not_selected",
        "routability_plugin_selected": ",".join(plugins),
        "routability_plugin_summary": {
            "plugins": {
                plugin: {"status": "active", "activations": 2}
                for plugin in plugins
            },
        },
    }


def proxy_metrics(backend):
    metrics = {name: 1.0 for name in PROXY_REQUIRED_METRICS[backend]}
    metrics.update({
        "route_x_size": 256,
        "route_y_size": 256,
    })
    if backend == "gpugr":
        metrics.update({
            "gr_wirelength": 10.0,
            "directional_metric_schema_version": 2,
        })
    return metrics


def make_source(root, case="case_a", seed=1000):
    methods = root / case / ("seed_%d" % seed) / case / "methods"
    methods.mkdir(parents=True)
    placements = []
    for method in ("hpwl", "plugin"):
        method_dir = methods / method
        placement = method_dir / "placement" / case / (case + ".dp.def")
        placement.parent.mkdir(parents=True)
        placement.write_text("VERSION 5.8 ;\nDESIGN case_a ;\nEND DESIGN\n")
        config = {
            "def_input": "/source/input/%s.def" % case,
            "lef_input": [],
            "route_num_bins_x": 256,
            "route_num_bins_y": 256,
            "ruplace_plugins": [] if method == "hpwl" else ["local_gradient"],
        }
        (method_dir / "config.json").write_text(json.dumps(config))
        placements.append(placement_provenance(method))
    comparison = methods / "comparison.json"
    comparison.write_text(json.dumps({
        "validation": {"status": "validated"},
        "placements": placements,
        "results": [{"design_name": case}],
    }))
    return comparison


class RoutabilityProxyReplayTest(unittest.TestCase):
    def test_mandatory_proxy_gate_rejects_single_backend_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rudy_map = root / "rudy.pt"
            gpugr_result = root / "gpugr.pt"
            gpugr_log = root / "gpugr.log"
            for path in (rudy_map, gpugr_result, gpugr_log):
                path.write_text("artifact")
            results = {
                "candidate": [
                    EvaluationResult(
                        "rudy", "d", metrics=proxy_metrics("rudy"),
                        artifacts={"map": str(rudy_map)},
                    ),
                    EvaluationResult(
                        "gpugr", "d", status="failed",
                        artifacts={
                            "result": str(gpugr_result),
                            "log": str(gpugr_log),
                        },
                    ),
                ],
            }
            failed = mandatory_proxy_gate(
                results, ["candidate"], ["rudy", "gpugr"], 256, 256
            )
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["failures"], ["candidate:gpugr"])
            results["candidate"][1].status = "ok"
            results["candidate"][1].metrics = proxy_metrics("gpugr")
            passed = mandatory_proxy_gate(
                results, ["candidate"], ["rudy", "gpugr"], 256, 256
            )
            self.assertEqual(passed["status"], "passed")

    def test_metric_contract_requires_v2_directional_metrics(self):
        metrics = proxy_metrics("gpugr")
        self.assertEqual(proxy_metric_contract_error(metrics, "gpugr"), "")
        del metrics["vertical_ace"]
        self.assertIn("vertical_ace", proxy_metric_contract_error(metrics, "gpugr"))
        metrics["vertical_ace"] = 1.0
        del metrics["horizontal_congestion_score_p99"]
        self.assertIn(
            "horizontal_congestion_score_p99",
            proxy_metric_contract_error(metrics, "gpugr"),
        )
        metrics["horizontal_congestion_score_p99"] = 1.0
        del metrics["gr_vias"]
        self.assertIn("gr_vias", proxy_metric_contract_error(metrics, "gpugr"))
        metrics["gr_vias"] = 1.0
        del metrics["rc_hor"]
        self.assertIn("rc_hor", proxy_metric_contract_error(metrics, "gpugr"))
        metrics["rc_hor"] = 0.1
        metrics["directional_metric_schema_version"] = 1
        self.assertIn("schema_version", proxy_metric_contract_error(metrics, "gpugr"))
        metrics["directional_metric_schema_version"] = 2
        metrics["gr_wirelength"] = 0.0
        self.assertIn("not positive", proxy_metric_contract_error(metrics, "gpugr"))

        rudy = proxy_metrics("rudy")
        del rudy["congestion_score"]
        self.assertIn(
            "congestion_score", proxy_metric_contract_error(rudy, "rudy")
        )

    def test_metric_contract_rejects_mismatched_actual_resolution(self):
        metrics = proxy_metrics("rudy")
        self.assertIn(
            "route_x_size",
            proxy_metric_contract_error(metrics, "rudy", 128, 256),
        )

    def test_resolution_must_match_source_feedback(self):
        config = {"route_num_bins_x": 256, "route_num_bins_y": 256}
        matched = matched_resolution_config(config, 256, 256)
        self.assertEqual(matched["routability_eval_route_x_size"], 256)
        with self.assertRaisesRegex(ValueError, "does not match"):
            matched_resolution_config(config, 128, 128)

    def test_expected_sources_rejects_heldout_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_source(root, "development")
            make_source(root, "heldout")
            with self.assertRaisesRegex(ValueError, "out-of-scope"):
                expected_sources(root, ["development"], [1000])

    def test_replays_frozen_placements_and_resumes_complete_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            source = make_source(source_root)
            output = root / "replay"
            calls = []

            def evaluate(request, backend):
                calls.append((request.def_input, backend, request.options["gpu"]))
                eval_dir = Path(request.output_dir)
                if backend == "rudy":
                    artifact = eval_dir / "rudy_map.pt"
                    artifact.write_text("map")
                    artifacts = {"map": str(artifact)}
                else:
                    result = eval_dir / "gpugr.pt"
                    log = eval_dir / "gpugr.log"
                    result.write_text("result")
                    log.write_text("log")
                    artifacts = {"result": str(result), "log": str(log)}
                return EvaluationResult(
                    backend=backend,
                    design_name=request.design_name,
                    metrics=proxy_metrics(backend),
                    artifacts=artifacts,
                )

            argv = [
                "--source-campaign", str(source_root),
                "--output-dir", str(output),
                "--methods", "hpwl,plugin",
                "--cases", "case_a",
                "--seeds", "1000",
                "--gpus", "2",
                "--route-x-size", "256",
                "--route-y-size", "256",
                "--hardlink-placements",
            ]
            with mock.patch(
                "tools.routability_proxy_replay.run_evaluator_subprocess",
                side_effect=evaluate,
            ):
                self.assertEqual(main(argv), 0)
            self.assertEqual(len(calls), 2)
            self.assertEqual({gpu for _, _, gpu in calls}, {2})

            comparison = (
                output / "case_a/seed_1000/case_a/methods/comparison.json"
            )
            self.assertTrue(validated_replay_matches(
                comparison, source, ["hpwl", "plugin"], ["rudy", "gpugr"],
                256, 256,
            ))
            data = json.loads(comparison.read_text())
            self.assertFalse(data["proxy_replay"]["placement_rerun"])
            self.assertFalse(data["proxy_replay"]["numeric_backend_mixing"])
            self.assertEqual(data["proxy_replay"]["deduplicated_method_count"], 1)
            self.assertEqual(data["proxy_replay"]["unique_evaluation_count"], 1)
            self.assertEqual(
                data["proxy_replay"]["identical_placement_evaluation_reuse"],
                [{
                    "method": "plugin",
                    "source_method": "hpwl",
                    "evaluation_identity": data["proxy_replay"]
                    ["identical_placement_evaluation_reuse"][0]
                    ["evaluation_identity"],
                }],
            )
            self.assertEqual(len(data["proxy_replay"]["provenance"]), 2)
            provenance = {
                row["method"]: row for row in data["proxy_replay"]["provenance"]
            }
            self.assertIsNone(provenance["hpwl"]["evaluation_reused_from_method"])
            self.assertEqual(
                provenance["plugin"]["evaluation_reused_from_method"], "hpwl"
            )
            for row in data["proxy_replay"]["provenance"]:
                self.assertEqual(
                    row["source_placement_sha256"],
                    row["staged_placement_sha256"],
                )

            with mock.patch(
                "tools.routability_proxy_replay.run_evaluator_subprocess"
            ) as rerun:
                self.assertEqual(main(argv + ["--resume"]), 0)
                rerun.assert_not_called()

    def test_rejects_any_backend_set_other_than_rudy_and_gpugr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            make_source(source_root)
            with self.assertRaisesRegex(ValueError, "exactly rudy and gpugr"):
                main([
                    "--source-campaign", str(source_root),
                    "--output-dir", str(root / "output"),
                    "--methods", "hpwl,plugin",
                    "--evaluators", "gpugr",
                    "--cases", "case_a",
                    "--seeds", "1000",
                    "--gpus", "0",
                    "--route-x-size", "256",
                    "--route-y-size", "256",
                ])


if __name__ == "__main__":
    unittest.main()
