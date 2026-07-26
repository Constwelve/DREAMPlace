#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_campaign import main


class RoutabilityCampaignTest(unittest.TestCase):
    def test_custom_presets_reach_comparison_runner(self):
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
            presets = root / "generated_presets.json"
            presets.write_text('{"hpwl": {}}\n')

            with mock.patch(
                "tools.routability_campaign.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as run:
                status = main([
                    "--manifest", str(manifest), "--template", str(template),
                    "--presets", str(presets), "--methods", "hpwl",
                    "--evaluators", "rudy", "--output-dir", str(root / "out"),
                    "--dreamplace-entry", str(root / "Placer.py"),
                ])

        self.assertEqual(status, 0)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--presets") + 1], str(presets))


if __name__ == "__main__":
    unittest.main()
