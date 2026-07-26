#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_parallel import main


class ImmediateProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class RoutabilityParallelTest(unittest.TestCase):
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
            placer = root / "Placer.py"
            placer.write_text("# placeholder\n")
            output = root / "out"

            with mock.patch(
                "tools.routability_parallel.subprocess.Popen",
                return_value=ImmediateProcess(),
            ) as popen:
                status = main([
                    "--manifest", str(manifest), "--template", str(template),
                    "--cases", "tiny", "--seeds", "7", "--gpus", "3",
                    "--methods", "hpwl", "--evaluators", "rudy",
                    "--output-dir", str(output),
                    "--dreamplace-entry", str(placer),
                ])

            report = json.loads((output / "parallel_status.json").read_text())
        self.assertEqual(status, 0)
        self.assertEqual(report["jobs"][0]["status"], "completed")
        self.assertEqual(report["jobs"][0]["gpu"], 3)
        self.assertEqual(popen.call_args.kwargs["env"]["CUDA_VISIBLE_DEVICES"], "3")
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--random-seed") + 1], "7")


if __name__ == "__main__":
    unittest.main()
