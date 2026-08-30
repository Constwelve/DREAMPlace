#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_openroad_oracle import generate_oracle


class RoutabilityOpenroadOracleTest(unittest.TestCase):
    def test_oracle_binds_frozen_route_feedback_command_and_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.def"
            lef = root / "cells.lef"
            output = root / "oracle.def"
            report_path = root / "oracle.json"
            log = root / "oracle.log"
            baseline.write_text("baseline")
            lef.write_text("lef")

            def run(command, **kwargs):
                if "-version" in command:
                    return mock.Mock(returncode=0, stdout="OpenROAD test")
                output.write_text("oracle")
                log.write_text("placement legal")
                return mock.Mock(returncode=0, stdout="ok")

            with mock.patch(
                "tools.routability_openroad_oracle.subprocess.run",
                side_effect=run,
            ) as runner:
                report = generate_oracle(
                    baseline,
                    [lef],
                    output,
                    report_path=report_path,
                    openroad_binary="/bin/true",
                    threads=4,
                    log_path=log,
                )
            serialized = json.loads(report_path.read_text())

        tcl = runner.call_args_list[1].kwargs["input"]
        self.assertIn("-routability_target_rc_metric 1.005", tcl)
        self.assertIn("-routability_max_inflation_ratio 1.02", tcl)
        self.assertIn("check_placement -verbose", tcl)
        self.assertEqual(report["operation"], "openroad_routability_direction_oracle")
        self.assertEqual(serialized, report)


if __name__ == "__main__":
    unittest.main()
