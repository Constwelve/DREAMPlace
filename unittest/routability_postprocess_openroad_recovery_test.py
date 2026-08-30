#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest


from tools.routability_golden_replay import result_meets_resume_contract
from tools.routability_postprocess_openroad_recovery import main, postprocess


def write_recovery(directory, *, complete=True, flow_errors=0):
    directory.mkdir(parents=True)
    raw = {
        "flow__errors__count": flow_errors,
        "global_route__vias": 10,
        "global_route__wirelength": 100,
        "route__drc_errors": 3,
        "route__net": 2,
        "route__vias": 12,
        "route__wirelength": 80,
    }
    log = (
        "Number of nets: 2\n"
        "[INFO DRT-0199] Number of violations = 3.\n"
        " Short 1 2\n"
        "[INFO DRT-0267] done\n"
    )
    if complete:
        log += "[INFO DRT-0198] Complete detail routing.\n"
    files = {
        "openroad.container.log": log,
        "openroad.log": "partial timeout log\n",
        "openroad_drc.rpt": "drc report\n",
        "openroad_metrics.json": json.dumps(raw),
        "openroad_congestion.rpt": (
            "violation type: Horizontal congestion\n"
            "comment: capacity: 2 usage: 4 overflow: 2\n"
            "violation type: Vertical congestion\n"
            "comment: capacity: 3 usage: 4 overflow: 1\n"
        ),
        "openroad.guide": "guide\n",
        "openroad_wirelength.rpt": "Total wire length = 80\n",
        "openroad_eval.tcl": (
            "detailed_route -output_drc openroad_drc.rpt\n"
            "report_wire_length -detailed_route -summary\n"
        ),
    }
    for name, text in files.items():
        (directory / name).write_text(text)
    timeout = {
        "backend": "openroad",
        "design_name": "case_a",
        "status": "timeout",
        "runtime_sec": 10.0,
        "schema_version": 1,
        "metrics": {},
        "artifacts": {"log": "/remote/openroad.log"},
        "error": "timeout after 10 seconds",
    }
    (directory / "openroad.json").write_text(json.dumps(timeout))
    (directory / "summary.json").write_text(json.dumps({"results": [timeout]}))
    return timeout


class RoutabilityPostprocessOpenROADRecoveryTest(unittest.TestCase):
    def test_rebuilds_strict_result_and_preserves_timeout_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "evaluation"
            timeout = write_recovery(directory)

            result = postprocess(directory, design_name="case_a")

            self.assertEqual(result["metrics"]["wirelength"], 80)
            self.assertEqual(result["metrics"]["horizontal_overflow"], 2)
            self.assertEqual(result["metrics"]["vertical_overflow"], 1)
            self.assertEqual(result["metrics"]["drc_violations"], 3)
            self.assertEqual(result["metrics"]["short_violations"], 3)
            self.assertEqual(result["metrics"]["unrouted_nets"], 0)
            self.assertEqual(
                json.loads((directory / "openroad.timeout.json").read_text()),
                timeout,
            )
            self.assertEqual(
                (directory / "openroad.timeout.log").read_text(),
                "partial timeout log\n",
            )
            self.assertTrue(result_meets_resume_contract(
                {**result, "authoritative_for_comparison": True}, "openroad"
            ))

            rerun = postprocess(directory, design_name="case_a")
            self.assertEqual(rerun["metrics"], result["metrics"])
            self.assertEqual(
                json.loads((directory / "openroad.timeout.json").read_text()),
                timeout,
            )

    def test_rejects_log_without_detail_route_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "evaluation"
            write_recovery(directory, complete=False)

            with self.assertRaisesRegex(ValueError, "lacks detail-route completion"):
                postprocess(directory)

            self.assertFalse((directory / "openroad.timeout.json").exists())

    def test_rejects_nonzero_flow_error_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "evaluation"
            write_recovery(directory, flow_errors=1)

            with self.assertRaisesRegex(ValueError, "report flow errors"):
                postprocess(directory)

    def test_rejects_missing_retained_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "evaluation"
            write_recovery(directory)
            (directory / "openroad_drc.rpt").unlink()

            with self.assertRaisesRegex(ValueError, "missing completed"):
                postprocess(directory)

    def test_cli_report_binds_evaluation_directory_and_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "evaluation"
            report = root / "report.json"
            write_recovery(directory)

            self.assertEqual(main([
                "--evaluation-dir", str(directory),
                "--design-name", "case_a",
                "--report", str(report),
            ]), 0)

            data = json.loads(report.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["routes"][0]["evaluation_dir"], str(directory))
            self.assertEqual(data["routes"][0]["result"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
