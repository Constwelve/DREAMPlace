#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_generate_presets import generate_presets, main


BASE = {
    "hpwl": {"ruplace_flag": 0},
    "local_gradient": {"ruplace_plugins": ["local_gradient"]},
    "net_weighting": {"ruplace_plugins": ["net_weighting"]},
    "routeforce": {"ruplace_plugins": ["routeforce"]},
}


class RoutabilityGeneratePresetsTest(unittest.TestCase):
    def test_generates_pair_grid_and_skips_invalid_routeforce_proxy(self):
        presets, manifest = generate_presets(BASE, {
            "plugins": ["local_gradient", "net_weighting", "routeforce"],
            "combination_sizes": [2],
            "proxies": ["rudy", "gpugr"],
            "grid": {"ruplace_plugin_start_overflow": [0.6, 0.8]},
        })

        self.assertEqual(len(manifest), 8)
        self.assertIn("hpwl", presets)
        self.assertTrue(all(
            row["proxy"] in ("gpugr", "xplace")
            for row in manifest.values() if "routeforce" in row["plugins"]
        ))
        self.assertEqual(
            {row["grid"]["ruplace_plugin_start_overflow"] for row in manifest.values()},
            {0.6, 0.8},
        )

    def test_rejects_unbounded_generation(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            generate_presets(BASE, {
                "plugins": ["local_gradient", "net_weighting", "routeforce"],
                "combination_sizes": [2],
                "proxies": ["gpugr"],
                "grid": {"ruplace_plugin_start_overflow": [0.5, 0.6]},
            }, max_presets=2)

    def test_rejects_provenance_overrides(self):
        with self.assertRaisesRegex(ValueError, "identity keys"):
            generate_presets(BASE, {
                "plugins": ["local_gradient", "net_weighting"],
                "combination_sizes": [2],
                "proxies": ["rudy"],
                "shared_overrides": {"ruplace_proxy": "gpugr"},
            })

    def test_cli_writes_presets_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            spec = root / "spec.json"
            output = root / "generated.json"
            base.write_text(json.dumps(BASE))
            spec.write_text(json.dumps({
                "plugins": ["local_gradient", "net_weighting"],
                "combination_sizes": [2],
                "proxies": ["rudy"],
            }))
            status = main([
                "--base-presets", str(base), "--spec", str(spec),
                "--output", str(output),
            ])
            generated = json.loads(output.read_text())
            provenance = json.loads(
                output.with_suffix(".json.manifest.json").read_text()
            )

        self.assertEqual(status, 0)
        self.assertEqual(len(generated), 2)
        self.assertEqual(len(provenance["generated"]), 1)


if __name__ == "__main__":
    unittest.main()
