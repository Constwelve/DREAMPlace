#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_parallel import baseline_first_methods, main


class ImmediateProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class RoutabilityParallelTest(unittest.TestCase):
    def test_hpwl_baseline_is_scheduled_first_without_changing_method_set(self):
        self.assertEqual(
            baseline_first_methods("candidate_a,hpwl,candidate_b"),
            "hpwl,candidate_a,candidate_b",
        )
        self.assertEqual(
            baseline_first_methods("candidate_a,candidate_b"),
            "candidate_a,candidate_b",
        )

    def test_parallel_runner_assigns_gpu_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "input.lef"
            deffile = root / "input.def"
            lef.write_text("END LIBRARY\n")
            deffile.write_text("END DESIGN\n")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"cases": [{
                "name": "tiny", "lef_input": str(lef),
                "def_input": str(deffile),
            }]}))
            template = root / "template.json"
            template.write_text("{}\n")
            presets = root / "presets.json"
            presets.write_text('{"hpwl": {}}\n')
            placer = root / "Placer.py"
            placer.write_text("# placeholder\n")
            output = root / "out"

            with mock.patch(
                "tools.routability_parallel.subprocess.Popen",
                return_value=ImmediateProcess(),
            ) as popen:
                status = main([
                    "--manifest", str(manifest), "--template", str(template),
                    "--presets", str(presets),
                    "--cases", "tiny", "--seeds", "7", "--gpus", "3",
                    "--methods", "candidate,hpwl", "--evaluators", "rudy",
                    "--output-dir", str(output),
                    "--dreamplace-entry", str(placer),
                    "--resume",
                ])

            report = json.loads((output / "parallel_status.json").read_text())
        self.assertEqual(status, 0)
        self.assertEqual(report["jobs"][0]["status"], "completed")
        self.assertEqual(report["jobs"][0]["gpu"], 3)
        self.assertEqual(popen.call_args.kwargs["env"]["CUDA_VISIBLE_DEVICES"], "3")
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--random-seed") + 1], "7")
        self.assertEqual(command[command.index("--presets") + 1], str(presets))
        self.assertEqual(
            command[command.index("--methods") + 1], "hpwl,candidate"
        )
        self.assertIn("--resume", command)


if __name__ == "__main__":
    unittest.main()
