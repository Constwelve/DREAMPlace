#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest

from tools.routability_build_survivor_pairs import build_survivor_pairs, main


SELECTION = {
    "selected_methods": ["a", "b", "c", "d"],
    "selection_policy": {
        "name": "routability_first",
        "numeric_backend_mixing": False,
        "max_primary_worst_regression": 0.0,
        "backend_improvement_constraints": {
            "gpugr": {"minimum_improvements": 1},
            "rudy": {"minimum_improvements": 1},
        },
    },
}

COMMON = {
    "ruplace_flag": 1,
    "routability_opt_flag": 1,
    "ruplace_proxy": "rudy",
    "ruplace_plugin_start_overflow": 0.8,
    "ruplace_proxy_refresh_interval": 20,
}

PRESETS = {
    "hpwl": {"ruplace_flag": 0},
    "a": {
        **COMMON,
        "ruplace_plugins": ["local_gradient"],
        "ruplace_local_gradient_weight": 0.001,
    },
    "b": {
        **COMMON,
        "ruplace_plugins": ["net_weighting"],
        "ruplace_net_weight_gamma": 0.005,
    },
    "c": {
        **COMMON,
        "ruplace_proxy": "gpugr",
        "ruplace_plugins": ["whitespace"],
        "ruplace_whitespace_weight": 0.001,
    },
    "d": {
        **COMMON,
        "ruplace_proxy_refresh_interval": 10,
        "ruplace_plugins": ["net_overlap"],
        "ruplace_net_overlap_weight": 0.001,
    },
}

MANIFEST = {
    "generated": {
        name: {
            "plugins": PRESETS[name]["ruplace_plugins"],
            "proxy": PRESETS[name]["ruplace_proxy"],
        }
        for name in ("a", "b", "c", "d")
    }
}


class RoutabilityBuildSurvivorPairsTest(unittest.TestCase):
    def test_builds_only_same_proxy_conflict_free_pairs(self):
        presets, generated, metadata = build_survivor_pairs(
            SELECTION, PRESETS, MANIFEST
        )

        self.assertEqual(metadata["pair_count"], 1)
        pair = metadata["pair_methods"][0]
        self.assertEqual(
            presets[pair]["ruplace_plugins"],
            ["local_gradient", "net_weighting"],
        )
        self.assertEqual(presets[pair]["ruplace_proxy"], "rudy")
        self.assertEqual(set(presets), {"hpwl", "a", "b", "c", "d", pair})
        self.assertTrue(generated[pair]["compatible_shared_configuration"])
        self.assertEqual(len(metadata["incompatible_pairs"]), 5)
        reasons = [
            reason
            for row in metadata["incompatible_pairs"]
            for reason in row["reasons"]
        ]
        self.assertIn("parents use different proxies", reasons)
        self.assertIn("ruplace_proxy_refresh_interval differs", reasons)
        self.assertFalse(metadata["numeric_backend_mixing"])
        self.assertFalse(metadata["heldout_or_golden_evidence_used"])

    def test_rejects_non_strict_selection(self):
        selection = json.loads(json.dumps(SELECTION))
        selection["selection_policy"]["max_primary_worst_regression"] = None

        with self.assertRaisesRegex(ValueError, "strict proxy policy"):
            build_survivor_pairs(selection, PRESETS, MANIFEST)

    def test_rejects_single_survivor(self):
        selection = json.loads(json.dumps(SELECTION))
        selection["selected_methods"] = ["a"]

        with self.assertRaisesRegex(ValueError, "fewer than two"):
            build_survivor_pairs(selection, PRESETS, MANIFEST)

    def test_cli_writes_pair_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            presets = root / "presets.json"
            manifest = root / "manifest.json"
            output = root / "pairs.json"
            selection.write_text(json.dumps(SELECTION))
            presets.write_text(json.dumps(PRESETS))
            manifest.write_text(json.dumps(MANIFEST))

            status = main([
                "--selection", str(selection),
                "--presets", str(presets),
                "--preset-manifest", str(manifest),
                "--output", str(output),
            ])
            result = json.loads(output.read_text())
            provenance = json.loads(
                output.with_suffix(".json.manifest.json").read_text()
            )

        self.assertEqual(status, 0)
        self.assertEqual(provenance["metadata"]["pair_count"], 1)
        self.assertEqual(len(result), 6)


if __name__ == "__main__":
    unittest.main()
