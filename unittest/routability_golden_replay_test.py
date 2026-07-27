#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval import EvaluationResult
from tools.routability_golden_replay import enforce_golden_metric_contract, main


class RoutabilityGoldenReplayTest(unittest.TestCase):
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
                }))
                placements.append({
                    "method": method, "status": "ok", "placement_hpwl": 100.0,
                })
            (methods / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [{"design_name": "input"}],
            }))

            def evaluate(request, backend):
                return EvaluationResult(
                    backend=backend, design_name=request.design_name,
                    metrics={"wirelength": 10.0},
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
                }))
                placements.append({"method": method, "status": "ok"})
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
                    metrics={"wirelength": 10.0},
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
                }))
                placements.append({"method": method, "status": "ok"})
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
                    metrics={"wirelength": 10.0},
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
            active = 0
            peak_active = 0

            def replay(source_path, source_root, output_root, methods, evaluators,
                       path_maps, num_threads, timeout_sec,
                       snap_manufacturing_grid=False):
                nonlocal active, peak_active
                with lock:
                    active += 1
                    peak_active = max(peak_active, active)
                time.sleep(0.05)
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
