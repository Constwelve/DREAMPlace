import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.routability_audit_placement_effect import audit_placement_effect
from tools.routability_snapshot_partial_campaign import (
    snapshot_partial_campaign,
)
from tools.routability_summarize import load_comparison, main as summarize_main


class RoutabilitySnapshotPartialCampaignTest(unittest.TestCase):
    def write_method(self, methods, method, active=False):
        method_dir = methods / method
        placement = method_dir / "placement" / "design"
        placement.mkdir(parents=True)
        config = {
            "design_name": "design",
            "def_input": "design.def",
            "result_dir": str(method_dir / "placement"),
        }
        if active:
            config["ruplace_plugins"] = ["local_gradient"]
        config_path = method_dir / "config.json"
        config_path.write_text(
            json.dumps(config, sort_keys=True) + "\n"
        )
        summary = ""
        if active:
            summary = (
                'INFO ROUTABILITY_PLUGIN_SUMMARY {"pipeline":'
                '{"gradient_calls":1},"plugins":{"local_gradient":'
                '{"gradient_attempts":1,"gradient_activations":1}}}\n'
            )
        (method_dir / "placement.log").write_text(
            "iteration 1, wHPWL 100, Overflow 0.1\n" + summary
        )
        placed_def = placement / "design.gp.def"
        placed_def.write_text(
            "VERSION 5.8 ;\n# %s\n" % (method if active else "baseline")
        )
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        def_hash = digest(placed_def)
        (method_dir / "placement_provenance.json").write_text(json.dumps({
            "schema_version": 1,
            "method": method,
            "config": str(config_path.resolve()),
            "config_sha256": digest(config_path),
            "placed_def": str(placed_def.resolve()),
            "placed_def_sha256": def_hash,
            "placement_geometry_provenance": {
                "status": "ok",
                "def_sha256": def_hash,
                "overlap_pair_count": 0,
                "unplaced_component_count": 0,
                "uncovered_component_count": 0,
            },
            "placement_input_provenance": {"files": {}},
            "placement_implementation_provenance": {"files": {}},
            "placement_runtime_provenance": {"host": {"hostname": "test"}},
        }, sort_keys=True) + "\n")
        evaluation = method_dir / "evaluation"
        evaluation.mkdir()
        results = []
        for backend in ("rudy", "gpugr"):
            results.append({
                "backend": backend,
                "design_name": "design",
                "status": "ok",
                "runtime_sec": 1.0,
                "metrics": {
                    "congestion_score": 1.0,
                    "overflow_sum": 0.0,
                    "gr_wirelength": 100.0,
                    "gr_vias": 10.0,
                    "est_shorts": 0.0,
                    "num_ovfl_nets": 0.0,
                    "rc_hor": 0.0,
                    "rc_ver": 0.0,
                },
                "artifacts": {},
                "error": "",
                "validation_role": "proxy",
                "authoritative_for_comparison": True,
            })
        (evaluation / "summary.json").write_text(
            json.dumps({"results": results}, sort_keys=True) + "\n"
        )

    def test_freezes_only_methods_complete_in_every_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            for case in ("test1", "test2"):
                methods = campaign / case / "seed_1000" / case / "methods"
                self.write_method(methods, "hpwl")
                self.write_method(methods, "candidate", active=True)
                if case == "test1":
                    self.write_method(methods, "not_common", active=True)
            output = root / "snapshot"
            manifest = snapshot_partial_campaign(
                campaign,
                {"candidate": {}, "not_common": {}, "hpwl": {}},
                output,
                expected_comparisons=2,
            )
            self.assertEqual(manifest["selected_methods"], ["hpwl", "candidate"])
            self.assertEqual(len(manifest["comparisons"]), 2)
            comparison = output / "test1/seed_1000/test1/methods/comparison.json"
            rows, exclusion = load_comparison(comparison, output)
            self.assertIsNone(exclusion)
            self.assertEqual({row["method"] for row in rows}, {"hpwl", "candidate"})
            audit = audit_placement_effect(output, 2)
            self.assertEqual(audit["status"], "passed")
            self.assertEqual(audit["active_changed_count"], 2)
            status = json.loads((output / "parallel_status.json").read_text())
            self.assertEqual(len(status["jobs"]), 2)
            self.assertTrue(all(row["status"] == "completed" for row in status["jobs"]))

    def test_refuses_snapshot_without_common_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            for case in ("test1", "test2"):
                methods = campaign / case / "seed_1000" / case / "methods"
                self.write_method(methods, "hpwl")
                self.write_method(methods, "candidate_" + case, active=True)
            with self.assertRaisesRegex(ValueError, "no completed candidate"):
                snapshot_partial_campaign(
                    campaign,
                    {"hpwl": {}, "candidate_test1": {}, "candidate_test2": {}},
                    root / "snapshot",
                    expected_comparisons=2,
                )

    def test_completed_comparisons_mode_preserves_total_coverage_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            test1 = campaign / "test1/seed_1000/test1/methods"
            self.write_method(test1, "hpwl")
            self.write_method(test1, "candidate", active=True)
            test2 = campaign / "test2/seed_1000/test2/methods"
            self.write_method(test2, "candidate", active=True)

            snapshot = root / "snapshot"
            manifest = snapshot_partial_campaign(
                campaign,
                {"candidate": {}, "hpwl": {}},
                snapshot,
                expected_comparisons=2,
                completed_comparisons_only=True,
            )
            status = json.loads((snapshot / "parallel_status.json").read_text())
            summary_dir = root / "summary"
            summary_status = summarize_main([
                "--campaign-dir", str(snapshot),
                "--output-dir", str(summary_dir),
            ])
            summary = json.loads(
                (summary_dir / "screening_summary.json").read_text()
            )

        self.assertTrue(manifest["completed_comparisons_only"])
        self.assertEqual(len(manifest["comparisons"]), 1)
        self.assertEqual(
            manifest["omitted_comparisons"], [{"case": "test2", "seed": 1000}]
        )
        self.assertEqual(
            [(row["case"], row["status"]) for row in status["jobs"]],
            [("test1", "completed"), ("test2", "running")],
        )
        self.assertEqual(summary_status, 1)
        self.assertEqual(summary["expected_comparisons"], 2)
        self.assertEqual(summary["validated_comparisons"], 1)
        self.assertEqual(summary["excluded"], [])
        self.assertEqual(summary["baseline_gaps"], [])
        self.assertEqual(
            summary["missing_comparisons"], [{"case": "test2", "seed": 1000}]
        )

    def test_refuses_method_without_placement_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            for case in ("test1", "test2"):
                methods = campaign / case / "seed_1000" / case / "methods"
                self.write_method(methods, "hpwl")
                self.write_method(methods, "candidate", active=True)
            (campaign / "test1/seed_1000/test1/methods/candidate/"
             "placement_provenance.json").unlink()
            with self.assertRaisesRegex(ValueError, "no completed candidate"):
                snapshot_partial_campaign(
                    campaign,
                    {"hpwl": {}, "candidate": {}},
                    root / "snapshot",
                    expected_comparisons=2,
                )

    def test_refuses_tampered_placement_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            for case in ("test1", "test2"):
                methods = campaign / case / "seed_1000" / case / "methods"
                self.write_method(methods, "hpwl")
                self.write_method(methods, "candidate", active=True)
            provenance = (
                campaign / "test1/seed_1000/test1/methods/candidate/"
                "placement_provenance.json"
            )
            data = json.loads(provenance.read_text())
            data["config_sha256"] = "0" * 64
            provenance.write_text(json.dumps(data, sort_keys=True) + "\n")
            with self.assertRaisesRegex(
                ValueError, "placement provenance config mismatch"
            ):
                snapshot_partial_campaign(
                    campaign,
                    {"hpwl": {}, "candidate": {}},
                    root / "snapshot",
                    expected_comparisons=2,
                )


if __name__ == "__main__":
    unittest.main()
