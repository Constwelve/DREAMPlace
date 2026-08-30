#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval import EvaluationResult
from tools.routability_golden_replay import (
    RESUME_REQUIRED_ARTIFACTS,
    enforce_golden_metric_contract,
    main,
    replay_comparison,
    reusable_method_results,
    validated_replay_matches,
)


def golden_metrics(backend, **overrides):
    metrics = {
        "wirelength": 10.0, "vias": 1.0, "drc_violations": 0.0,
        "unrouted_nets": 0.0, "short_violations": 0.0,
    }
    if backend == "openroad":
        metrics.update({"horizontal_overflow": 0.0, "vertical_overflow": 0.0})
    else:
        metrics.update({
            "horizontal_congestion": 0.0, "vertical_congestion": 0.0,
            "connectivity_violations": 0.0,
            "open_violations": 0.0,
        })
    metrics.update(overrides)
    return metrics


def golden_artifacts(root, backend, stem="artifact"):
    artifacts = {}
    for name in RESUME_REQUIRED_ARTIFACTS[backend]:
        path = root / ("%s_%s.txt" % (stem, name))
        if backend == "openroad" and name == "metrics":
            path.write_text(json.dumps({
                "route__wirelength": 10.0,
                "route__vias": 1.0,
                "route__drc_errors": 0.0,
                "route__net": 1,
            }))
        elif backend == "openroad" and name == "log":
            path.write_text(
                "Number of nets: 1\n"
                "[INFO DRT-0199] Number of violations = 0.\n"
                "Viol/Layer Metal2\n"
                "[INFO DRT-0267] done\n"
            )
        elif backend == "openroad" and name == "congestion":
            path.write_text(
                "violation type: Horizontal congestion\n"
                "  comment: capacity:1 usage:1 overflow:0\n"
                "violation type: Vertical congestion\n"
                "  comment: capacity:1 usage:1 overflow:0\n"
            )
        elif backend == "openroad" and name == "script":
            path.write_text(
                "global_route -allow_congestion\n"
                "detailed_route -output_drc openroad_drc.rpt\n"
                "report_wire_length -detailed_route -summary\n"
            )
        elif backend == "innovus" and name == "log":
            path.write_text(
                "RLEVAL_ROUTED_WIRELENGTH 10\n"
                "Total number of vias = 1\n"
                "Overflow after Early Global Route 0.0% H + 0.0% V\n"
                "#Total number of routable nets = 1.\n"
                "#1 routable nets have routed wires.\n"
            )
        elif backend == "innovus" and name == "drc":
            path.write_text("Total Violations : 0 Viols.\n")
        elif backend == "innovus" and name == "connectivity":
            path.write_text("Begin Summary\n0 total info(s) created.\nEnd Summary\n")
        elif backend == "innovus" and name == "metrics":
            path.write_text("wirelength=10\nroute_mode=detailed\n")
        elif backend == "innovus" and name == "script":
            path.write_text("globalDetailRoute\n")
        else:
            path.write_text(name + "\n")
        artifacts[name] = str(path)
    return artifacts


def plugin_names(method):
    return [] if method == "hpwl" else [method]


def placement_provenance(method, plugins=None):
    plugins = plugin_names(method) if plugins is None else list(plugins)
    return {
        "method": method,
        "status": "ok",
        "routability_plugin_status": "active" if plugins else "not_selected",
        "routability_plugin_selected": ",".join(sorted(plugins)),
        "routability_plugin_summary": {
            "plugins": {
                plugin: {"status": "active", "activations": 1}
                for plugin in plugins
            },
        },
    }


class RoutabilityGoldenReplayTest(unittest.TestCase):
    def test_method_resume_requires_complete_metrics_and_retained_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = golden_artifacts(root, "openroad")
            summary = root / "summary.json"
            summary.write_text(json.dumps({
                "results": [{
                    "backend": "openroad",
                    "design_name": "case_a",
                    "status": "ok",
                    "metrics": golden_metrics("openroad"),
                    "artifacts": artifacts,
                }],
            }))

            results = reusable_method_results(summary, ["openroad"])

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].backend, "openroad")
            Path(artifacts["drc"]).unlink()
            self.assertIsNone(reusable_method_results(summary, ["openroad"]))

    def test_method_resume_rejects_global_route_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for backend in ("openroad", "innovus"):
                artifacts = golden_artifacts(root, backend, backend)
                summary = root / (backend + "_summary.json")
                summary.write_text(json.dumps({
                    "results": [{
                        "backend": backend,
                        "design_name": "case_a",
                        "status": "ok",
                        "metrics": golden_metrics(backend),
                        "artifacts": artifacts,
                    }],
                }))
                self.assertIsNotNone(reusable_method_results(summary, [backend]))
                if backend == "openroad":
                    Path(artifacts["script"]).write_text(
                        "global_route -allow_congestion\n"
                        "report_wire_length -global_route -summary\n"
                    )
                else:
                    Path(artifacts["metrics"]).write_text(
                        "wirelength=10\nroute_mode=global\n"
                    )
                self.assertIsNone(reusable_method_results(summary, [backend]))

    def test_resume_requires_complete_current_golden_metric_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source" / "comparison.json"
            source.parent.mkdir()
            for method in ("hpwl", "plugin"):
                method_dir = source.parent / method
                method_dir.mkdir()
                (method_dir / "config.json").write_text(json.dumps({
                    "ruplace_plugins": plugin_names(method),
                }))
            source.write_text(json.dumps({
                "placements": [
                    placement_provenance(method)
                    for method in ("hpwl", "plugin")
                ],
            }))
            output = root / "output.json"
            artifacts = {
                backend: golden_artifacts(root, backend, backend)
                for backend in ("openroad", "innovus")
            }
            output.write_text(json.dumps({
                "source_comparison": str(source.resolve()),
                "validation": {"status": "validated"},
                "placements": [
                    placement_provenance("hpwl"),
                    placement_provenance("plugin"),
                ],
                "preprocessing": [
                    {
                        "method": method, "operation": "snap_manufacturing_grid",
                        "status": "ok",
                    }
                    for method in ("hpwl", "plugin")
                ],
                "results": [
                    {
                        "method": method, "backend": backend, "status": "ok",
                        "authoritative_for_comparison": True,
                        "metrics": golden_metrics(backend),
                        "artifacts": artifacts[backend],
                    }
                    for method in ("hpwl", "plugin")
                    for backend in ("openroad", "innovus")
                ],
            }))

            self.assertTrue(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))
            data = json.loads(output.read_text())
            data["placements"].append(dict(data["placements"][0]))
            output.write_text(json.dumps(data))
            self.assertFalse(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))
            data["placements"].pop()
            output.write_text(json.dumps(data))
            Path(artifacts["openroad"]["guide"]).unlink()
            self.assertFalse(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))
            Path(artifacts["openroad"]["guide"]).write_text("guide\n")
            metrics_path = Path(artifacts["openroad"]["metrics"])
            valid_metrics = metrics_path.read_text()
            metrics_path.write_text(json.dumps({
                "route__wirelength": 11.0,
                "route__vias": 1.0,
                "route__drc_errors": 0.0,
                "route__net": 1,
            }))
            self.assertFalse(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))
            metrics_path.write_text(valid_metrics)
            data = json.loads(output.read_text())
            del data["results"][0]["metrics"]["drc_violations"]
            output.write_text(json.dumps(data))
            self.assertFalse(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))
            data["results"][0]["metrics"]["drc_violations"] = 0.0
            innovus_result = next(
                result for result in data["results"]
                if result["backend"] == "innovus"
            )
            del innovus_result["metrics"]["open_violations"]
            output.write_text(json.dumps(data))
            self.assertFalse(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))
            innovus_result["metrics"]["open_violations"] = 0.0
            innovus_result["metrics"]["horizontal_congestion"] = -1.0
            output.write_text(json.dumps(data))
            self.assertFalse(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))
            innovus_result["metrics"]["horizontal_congestion"] = 0.0
            data["results"][0]["metrics"]["drc_violations"] = -1.0
            output.write_text(json.dumps(data))
            self.assertFalse(validated_replay_matches(
                output, source, ["hpwl", "plugin"],
                ["openroad", "innovus"], snap_manufacturing_grid=True,
            ))

    def test_resume_skips_validated_case_seed_through_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            source = (
                source_root / "case_a" / "seed_7" / "case_a" / "methods" /
                "comparison.json"
            )
            source.parent.mkdir(parents=True)
            method_dir = source.parent / "hpwl"
            method_dir.mkdir()
            (method_dir / "config.json").write_text(json.dumps({
                "ruplace_plugins": [],
            }))
            source.write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [placement_provenance("hpwl")],
            }))
            output_root = root / "golden"
            output = (
                output_root / "case_a" / "seed_7" / "case_a" / "methods" /
                "comparison.json"
            )
            output.parent.mkdir(parents=True)
            artifacts = golden_artifacts(root, "openroad")
            output.write_text(json.dumps({
                "source_comparison": str(source.resolve()),
                "validation": {"status": "validated"},
                "placements": [placement_provenance("hpwl")],
                "preprocessing": [],
                "results": [{
                    "method": "hpwl", "backend": "openroad", "status": "ok",
                    "authoritative_for_comparison": True,
                    "metrics": golden_metrics("openroad"),
                    "artifacts": artifacts,
                }],
            }))

            with mock.patch(
                "tools.routability_golden_replay.replay_comparison"
            ) as replay:
                status = main([
                    "--source-campaign", str(source_root),
                    "--output-dir", str(output_root),
                    "--methods", "hpwl", "--evaluators", "openroad",
                    "--resume",
                ])
            jobs = json.loads(
                (output_root / "parallel_status.json").read_text()
            )["jobs"]

        self.assertEqual(status, 0)
        replay.assert_not_called()
        self.assertEqual(jobs[0]["status"], "completed")
        self.assertEqual(jobs[0]["log"], str(output.resolve()))

    def test_method_resume_reuses_valid_sibling_and_reruns_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            methods = (
                source_root / "case_a" / "seed_7" / "case_a" / "methods"
            )
            lef = root / "input.lef"
            input_def = root / "input.def"
            lef.write_text("END LIBRARY\n")
            input_def.write_text("END DESIGN\n")
            placements = []
            for method in ("hpwl", "timed_out"):
                method_dir = methods / method
                placed = method_dir / "placement" / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text("END DESIGN\n")
                (method_dir / "config.json").write_text(json.dumps({
                    "lef_input": [str(lef)], "def_input": str(input_def),
                    "ruplace_plugins": plugin_names(method),
                }))
                placements.append(placement_provenance(method))
            source = methods / "comparison.json"
            source.write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [{"design_name": "input"}],
            }))
            output_root = root / "golden"

            with mock.patch(
                "tools.routability_golden_replay.run_evaluator_subprocess",
                return_value=EvaluationResult(
                    backend="openroad", design_name="input",
                    metrics=golden_metrics("openroad"),
                ),
            ):
                replay_comparison(
                    source, source_root, output_root,
                    ["hpwl", "timed_out"], ["openroad"], [], 1, 10,
                )

            output_methods = (
                output_root / "case_a" / "seed_7" / "case_a" / "methods"
            )
            hpwl_summary = output_methods / "hpwl" / "evaluation" / "summary.json"
            hpwl_summary.parent.mkdir(parents=True, exist_ok=True)
            hpwl_summary.write_text(json.dumps({
                "results": [{
                    "backend": "openroad", "design_name": "input",
                    "status": "ok", "metrics": golden_metrics("openroad"),
                    "artifacts": golden_artifacts(root, "openroad", "hpwl"),
                }],
            }))
            timeout_summary = (
                output_methods / "timed_out" / "evaluation" / "summary.json"
            )
            timeout_summary.parent.mkdir(parents=True, exist_ok=True)
            timeout_summary.write_text(json.dumps({
                "results": [{
                    "backend": "openroad", "design_name": "input",
                    "status": "timeout", "metrics": {}, "artifacts": {},
                    "error": "timeout after 10 seconds",
                }],
            }))

            evaluated = []

            def evaluate(request, backend):
                evaluated.append(Path(request.output_dir).parents[0].name)
                return EvaluationResult(
                    backend=backend, design_name=request.design_name,
                    metrics=golden_metrics(backend),
                )

            with mock.patch(
                "tools.routability_golden_replay.run_evaluator_subprocess",
                side_effect=evaluate,
            ):
                _, _, ok, _ = replay_comparison(
                    source, source_root, output_root,
                    ["hpwl", "timed_out"], ["openroad"], [], 1, 20,
                    resume_methods=True,
                )

        self.assertTrue(ok)
        self.assertEqual(evaluated, ["timed_out"])

    def test_golden_replay_forces_detailed_route_metrics(self):
        config = enforce_golden_metric_contract({
            "routability_eval_openroad_route_mode": "global",
        })
        self.assertEqual(config["routability_eval_openroad_route_mode"], "detailed")
        self.assertEqual(config["routability_eval_innovus_route_mode"], "detailed")

    def test_replays_frozen_defs_with_common_golden_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            methods = source / "case_a" / "seed_7" / "case_a" / "methods"
            lef = root / "input.lef"
            input_def = root / "input.def"
            lef.write_text("END LIBRARY\n")
            input_def.write_text("END DESIGN\n")
            placements = []
            for method in ("hpwl", "plugin"):
                method_dir = methods / method
                placed = method_dir / "placement" / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text("END DESIGN\n")
                (method_dir / "config.json").write_text(json.dumps({
                    "lef_input": [str(lef)], "def_input": str(input_def),
                    "ruplace_plugins": plugin_names(method),
                }))
                placement = placement_provenance(method)
                placement["placement_hpwl"] = 100.0
                placements.append(placement)
            (methods / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [{"design_name": "input"}],
            }))

            def evaluate(request, backend):
                return EvaluationResult(
                    backend=backend, design_name=request.design_name,
                    metrics=golden_metrics(backend),
                )

            output = root / "golden"
            with mock.patch(
                "tools.routability_golden_replay.run_evaluator_subprocess",
                side_effect=evaluate,
            ):
                status = main([
                    "--source-campaign", str(source), "--output-dir", str(output),
                    "--methods", "hpwl,plugin", "--evaluators", "openroad",
                ])
            comparison = json.loads((
                output / "case_a" / "seed_7" / "case_a" / "methods" /
                "comparison.json"
            ).read_text())
            parallel = json.loads((output / "parallel_status.json").read_text())
            copied_def_exists = (
                output / "case_a" / "seed_7" / "case_a" / "methods" / "hpwl" /
                "placement" / "input.gp.def"
            ).exists()

        self.assertEqual(status, 0)
        self.assertEqual(comparison["validation"]["selected_role"], "golden")
        self.assertEqual(comparison["validation"]["selected_backends"], ["openroad"])
        self.assertTrue(all(
            row["authoritative_for_comparison"] for row in comparison["results"]
        ))
        self.assertEqual(parallel["jobs"][0]["status"], "completed")
        self.assertTrue(copied_def_exists)

    def test_fresh_replay_rejects_negative_mandatory_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            methods = source / "case_a" / "seed_7" / "case_a" / "methods"
            lef = root / "input.lef"
            lef.write_text("END LIBRARY\n")
            placements = []
            for method in ("hpwl", "plugin"):
                method_dir = methods / method
                placed = method_dir / "placement" / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text("END DESIGN\n")
                (method_dir / "config.json").write_text(json.dumps({
                    "lef_input": [str(lef)], "def_input": str(root / "input.def"),
                    "ruplace_plugins": plugin_names(method),
                }))
                placements.append(placement_provenance(method))
            (methods / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [{"design_name": "input"}],
            }))

            def evaluate(request, backend):
                drc = -1.0 if "plugin" in request.output_dir else 0.0
                return EvaluationResult(
                    backend=backend, design_name=request.design_name,
                    metrics=golden_metrics(backend, drc_violations=drc),
                )

            output = root / "golden"
            with mock.patch(
                "tools.routability_golden_replay.run_evaluator_subprocess",
                side_effect=evaluate,
            ):
                status = main([
                    "--source-campaign", str(source), "--output-dir", str(output),
                    "--methods", "hpwl,plugin", "--evaluators", "openroad",
                ])
            comparison = json.loads((
                output / "case_a" / "seed_7" / "case_a" / "methods" /
                "comparison.json"
            ).read_text())
            plugin = next(
                row for row in comparison["results"] if row["method"] == "plugin"
            )

        self.assertEqual(status, 1)
        self.assertEqual(comparison["validation"]["status"], "unvalidated")
        self.assertEqual(plugin["status"], "failed")
        self.assertIn("negative drc_violations", plugin["error"])

    def test_snaps_once_and_reuses_identical_def_for_all_golden_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            methods = source / "case_a" / "seed_7" / "case_a" / "methods"
            lef = root / "input.lef"
            input_def = root / "input.def"
            lef.write_text("MANUFACTURINGGRID 0.005 ;\nEND LIBRARY\n")
            input_def.write_text("END DESIGN\n")
            placements = []
            for method in ("hpwl", "plugin"):
                method_dir = methods / method
                placed = method_dir / "placement" / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text(
                    "UNITS DISTANCE MICRONS 2000 ;\n"
                    "COMPONENTS 1 ;\n"
                    "- U1 CELL + PLACED ( 4401541 2591680 ) N ;\n"
                    "END COMPONENTS\nEND DESIGN\n"
                )
                (method_dir / "config.json").write_text(json.dumps({
                    "lef_input": [str(lef)], "def_input": str(input_def),
                    "ruplace_plugins": plugin_names(method),
                }))
                placements.append(placement_provenance(method))
            (methods / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [{"design_name": "input"}],
            }))

            evaluated_defs = []

            def evaluate(request, backend):
                evaluated_defs.append((backend, Path(request.def_input)))
                return EvaluationResult(
                    backend=backend, design_name=request.design_name,
                    metrics=golden_metrics(backend),
                )

            output = root / "golden"
            with mock.patch(
                "tools.routability_golden_replay.run_evaluator_subprocess",
                side_effect=evaluate,
            ):
                status = main([
                    "--source-campaign", str(source), "--output-dir", str(output),
                    "--methods", "hpwl,plugin",
                    "--evaluators", "openroad,innovus",
                    "--snap-manufacturing-grid",
                ])
            comparison = json.loads((
                output / "case_a" / "seed_7" / "case_a" / "methods" /
                "comparison.json"
            ).read_text())

            by_method = {}
            for _, path in evaluated_defs:
                method = path.parents[1].name
                by_method.setdefault(method, set()).add(path)

            for paths in by_method.values():
                self.assertEqual(len(paths), 1)
                self.assertIn("( 4401540 2591680 )", next(iter(paths)).read_text())
            self.assertEqual(status, 0)
            self.assertEqual(set(by_method), {"hpwl", "plugin"})
            self.assertEqual(len(comparison["preprocessing"]), 2)
            for row in comparison["preprocessing"]:
                self.assertEqual(row["operation"], "snap_manufacturing_grid")
                self.assertEqual(row["status"], "ok")
                self.assertTrue(Path(row["report"]).exists())
                self.assertEqual(row["changed_coordinates"], 1)

    def test_hardlink_staging_avoids_duplicate_source_def(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            methods = source / "case_a" / "seed_7" / "case_a" / "methods"
            method = methods / "hpwl"
            placed = method / "placement" / "input" / "input.gp.def"
            placed.parent.mkdir(parents=True)
            placed.write_text("END DESIGN\n")
            lef = root / "input.lef"
            lef.write_text("END LIBRARY\n")
            (method / "config.json").write_text(json.dumps({
                "lef_input": [str(lef)], "def_input": str(root / "input.def"),
                "ruplace_plugins": [],
            }))
            (methods / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [placement_provenance("hpwl")],
                "results": [{"design_name": "input"}],
            }))
            output = root / "golden"
            with mock.patch(
                "tools.routability_golden_replay.run_evaluator_subprocess",
                return_value=EvaluationResult(
                    backend="openroad", design_name="input",
                    metrics=golden_metrics("openroad"),
                ),
            ):
                status = main([
                    "--source-campaign", str(source), "--output-dir", str(output),
                    "--methods", "hpwl", "--evaluators", "openroad",
                    "--hardlink-placements",
                ])
            staged = (
                output / "case_a" / "seed_7" / "case_a" / "methods" / "hpwl" /
                "placement" / "input.gp.def"
            )

            self.assertEqual(status, 0)
            self.assertEqual(placed.stat().st_ino, staged.stat().st_ino)
            self.assertEqual(placed.read_text(), "END DESIGN\n")

    def test_missing_frozen_def_prevents_subset_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            methods = source / "case_a" / "seed_7" / "case_a" / "methods"
            lef = root / "input.lef"
            input_def = root / "input.def"
            lef.write_text("END LIBRARY\n")
            input_def.write_text("END DESIGN\n")
            placements = []
            for method in ("hpwl", "missing"):
                method_dir = methods / method
                method_dir.mkdir(parents=True)
                (method_dir / "config.json").write_text(json.dumps({
                    "lef_input": [str(lef)], "def_input": str(input_def),
                    "ruplace_plugins": plugin_names(method),
                }))
                placements.append(placement_provenance(method))
            placed = methods / "hpwl" / "placement" / "input" / "input.gp.def"
            placed.parent.mkdir(parents=True)
            placed.write_text("END DESIGN\n")
            (methods / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [{"design_name": "input"}],
            }))

            with mock.patch(
                "tools.routability_golden_replay.run_evaluator_subprocess",
                return_value=EvaluationResult(
                    backend="openroad", design_name="input",
                    metrics=golden_metrics("openroad"),
                ),
            ):
                status = main([
                    "--source-campaign", str(source),
                    "--output-dir", str(root / "golden"),
                    "--methods", "hpwl,missing", "--evaluators", "openroad",
                ])
            comparison = json.loads((
                root / "golden" / "case_a" / "seed_7" / "case_a" / "methods" /
                "comparison.json"
            ).read_text())

        self.assertEqual(status, 1)
        self.assertEqual(comparison["validation"]["status"], "unvalidated")
        self.assertEqual(comparison["validation"]["selected_backends"], [])

    def test_rejects_fallback_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "non-golden"):
                main([
                    "--source-campaign", str(root), "--output-dir", str(root / "out"),
                    "--methods", "hpwl", "--evaluators", "gpugr",
                ])

    def test_rejects_incomplete_source_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = root / "source" / "case_a" / "seed_7" / "case_a" / "methods"
            methods.mkdir(parents=True)
            (methods / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
            }))
            (root / "source" / "parallel_status.json").write_text(json.dumps({
                "jobs": [{"case": "case_a", "seed": 7, "status": "running"}],
            }))

            with self.assertRaisesRegex(ValueError, "incomplete"):
                main([
                    "--source-campaign", str(root / "source"),
                    "--output-dir", str(root / "out"),
                    "--methods", "hpwl", "--evaluators", "openroad",
                ])

    def test_runs_case_seed_replays_with_bounded_parallelism(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            for case, seed in (("case_a", 1), ("case_b", 2)):
                methods = source / case / ("seed_%d" % seed) / case / "methods"
                methods.mkdir(parents=True)
                (methods / "comparison.json").write_text(json.dumps({
                    "validation": {"status": "validated"},
                }))

            lock = threading.Lock()
            start_barrier = threading.Barrier(2)
            active = 0
            peak_active = 0

            def replay(source_path, source_root, output_root, methods, evaluators,
                       path_maps, num_threads, timeout_sec,
                       snap_manufacturing_grid=False, hardlink_placements=False,
                       resume_methods=False):
                nonlocal active, peak_active
                with lock:
                    active += 1
                    peak_active = max(peak_active, active)
                try:
                    start_barrier.wait(timeout=2)
                finally:
                    with lock:
                        active -= 1
                case = source_path.parts[-5]
                seed = int(source_path.parts[-4][len("seed_"):])
                return case, seed, True, output_root / case / "comparison.json"

            output = root / "golden"
            with mock.patch(
                "tools.routability_golden_replay.replay_comparison",
                side_effect=replay,
            ):
                status = main([
                    "--source-campaign", str(source), "--output-dir", str(output),
                    "--methods", "hpwl,plugin", "--evaluators", "innovus",
                    "--max-parallel", "2",
                ])
            jobs = json.loads((output / "parallel_status.json").read_text())["jobs"]

        self.assertEqual(status, 0)
        self.assertEqual(peak_active, 2)
        self.assertTrue(all(job["status"] == "completed" for job in jobs))


if __name__ == "__main__":
    unittest.main()
