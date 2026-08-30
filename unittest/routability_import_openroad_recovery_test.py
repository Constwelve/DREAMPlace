#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


from tools.routability_golden_replay import result_meets_resume_contract
import tools.routability_import_openroad_recovery as importer
from tools.routability_import_openroad_recovery import run_import, sha256


def write_valid_result(directory, wirelength=80, remote_paths=True):
    directory.mkdir(parents=True, exist_ok=True)
    raw = {
        "global_route__wirelength": 100,
        "global_route__vias": 10,
        "route__wirelength": wirelength,
        "route__vias": 12,
        "route__drc_errors": 0,
        "route__net": 1,
    }
    contents = {
        "openroad.log": (
            "Number of nets: 1\n"
            "[INFO DRT-0199] Number of violations = 0.\n"
            "[INFO DRT-0267] done\n"
        ),
        "openroad_drc.rpt": "",
        "openroad_metrics.json": json.dumps(raw),
        "openroad_congestion.rpt": "",
        "openroad.guide": "",
        "openroad_eval.tcl": (
            "detailed_route -output_drc openroad_drc.rpt\n"
            "report_wire_length -detailed_route -summary\n"
        ),
    }
    for filename, text in contents.items():
        (directory / filename).write_text(text)
    artifact_names = {
        "log": "openroad.log",
        "drc": "openroad_drc.rpt",
        "metrics": "openroad_metrics.json",
        "congestion": "openroad_congestion.rpt",
        "guide": "openroad.guide",
        "script": "openroad_eval.tcl",
    }
    artifacts = {
        name: (
            "/remote/recovery/%s" % filename
            if remote_paths else str((directory / filename).resolve())
        )
        for name, filename in artifact_names.items()
    }
    result = {
        "backend": "openroad",
        "design_name": "case_a",
        "status": "ok",
        "runtime_sec": 1.0,
        "schema_version": 1,
        "error": "",
        "metrics": {
            "wirelength": wirelength,
            "vias": 12,
            "drc_violations": 0,
            "unrouted_nets": 0.0,
            "short_violations": 0.0,
            "horizontal_overflow": 0.0,
            "vertical_overflow": 0.0,
            "openroad_metrics": raw,
        },
        "artifacts": artifacts,
    }
    (directory / "openroad.json").write_text(json.dumps(result))
    (directory / "summary.json").write_text(json.dumps({"results": [result]}))
    return result


class RoutabilityImportOpenROADRecoveryTest(unittest.TestCase):
    def fixture(self, root):
        recovery = root / "recovery"
        campaign = root / "campaign"
        archive = root / "archive"
        source = recovery / "outputs/route_a"
        target = campaign / "case_a/seed_1/case_a/methods/plugin/evaluation"
        write_valid_result(source)
        (recovery / "input.def").write_text("END DESIGN\n")
        target.mkdir(parents=True)
        (target / "old.txt").write_text("timeout evidence\n")
        (target / "openroad.json").write_text(json.dumps({
            "backend": "openroad", "status": "timeout",
        }))
        spec = {
            "required_hashes": {"input.def": sha256(recovery / "input.def")},
            "routes": [{
                "name": "route_a",
                "source_dir": "outputs/route_a",
                "target_dir": "case_a/seed_1/case_a/methods/plugin/evaluation",
            }],
        }
        return recovery, campaign, archive, target, spec

    def test_imports_valid_recovery_and_archives_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            recovery, campaign, archive, target, spec = self.fixture(Path(tmp))
            report = run_import(spec, recovery, campaign, archive)
            result = json.loads((target / "openroad.json").read_text())
            summary = json.loads((target / "summary.json").read_text())
            archived = archive / "route_a/evaluation/old.txt"

            self.assertEqual(report["routes"][0]["status"], "imported")
            self.assertEqual(
                report["routes"][0]["archived_previous_sha256"],
                sha256(archive / "route_a/evaluation/openroad.json"),
            )
            self.assertTrue(archived.is_file())
            self.assertEqual(summary["results"], [result])
            self.assertEqual(result["metrics"]["wirelength"], 80)
            self.assertEqual(
                Path(result["artifacts"]["log"]), target / "openroad.log"
            )
            self.assertTrue(result_meets_resume_contract(
                {**result, "authoritative_for_comparison": True}, "openroad"
            ))

    def test_dry_run_validates_without_modifying_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            recovery, campaign, archive, target, spec = self.fixture(Path(tmp))
            report = run_import(
                spec, recovery, campaign, archive, dry_run=True
            )

            self.assertEqual(
                report["routes"][0]["status"], "validated_pending_import"
            )
            self.assertTrue((target / "old.txt").is_file())
            self.assertFalse(archive.exists())

    def test_rejects_provenance_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            recovery, campaign, archive, _target, spec = self.fixture(Path(tmp))
            spec["required_hashes"]["input.def"] = "0" * 64

            with self.assertRaisesRegex(ValueError, "provenance hash mismatch"):
                run_import(spec, recovery, campaign, archive)

    def test_rejects_competing_valid_target_with_different_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            recovery, campaign, archive, target, spec = self.fixture(Path(tmp))
            write_valid_result(target, wirelength=81, remote_paths=False)

            with self.assertRaisesRegex(ValueError, "different metrics"):
                run_import(spec, recovery, campaign, archive)

            self.assertFalse(archive.exists())

    def test_rejects_archive_inside_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            recovery, campaign, _archive, _target, spec = self.fixture(Path(tmp))

            with self.assertRaisesRegex(ValueError, "outside the golden campaign"):
                run_import(spec, recovery, campaign, campaign / "archive")

    def test_staging_failure_leaves_timeout_target_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            recovery, campaign, archive, target, spec = self.fixture(Path(tmp))
            with mock.patch.object(
                importer, "write_rebased_result",
                side_effect=ValueError("staging failure"),
            ):
                with self.assertRaisesRegex(ValueError, "staging failure"):
                    run_import(spec, recovery, campaign, archive)

            self.assertTrue((target / "old.txt").is_file())
            self.assertFalse((target.parent / "evaluation.failed_import").exists())
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
