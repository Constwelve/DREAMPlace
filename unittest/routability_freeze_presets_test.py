#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_freeze_presets import freeze_presets, main


class RoutabilityFreezePresetsTest(unittest.TestCase):
    def test_freezes_union_with_one_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atomic = root / "atomic.json"
            pairs = root / "pairs.json"
            atomic_selection = root / "atomic_selection.json"
            pair_selection = root / "pair_selection.json"
            atomic.write_text(json.dumps({
                "hpwl": {"ruplace_flag": 0},
                "atomic_a": {"ruplace_plugins": ["local_gradient"]},
            }))
            pairs.write_text(json.dumps({
                "hpwl": {"ruplace_flag": 0},
                "pair_ab": {"ruplace_plugins": ["local_gradient", "net_weighting"]},
            }))
            atomic_selection.write_text(json.dumps({"selected_methods": ["atomic_a"]}))
            pair_selection.write_text(json.dumps({"selected_methods": ["pair_ab"]}))

            frozen, provenance = freeze_presets(
                [atomic, pairs], [atomic_selection, pair_selection]
            )

        self.assertEqual(list(frozen), ["hpwl", "atomic_a", "pair_ab"])
        self.assertEqual([row["method"] for row in provenance["methods"]], list(frozen))

    def test_rejects_conflicting_duplicate_presets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.json"
            right = root / "right.json"
            selection = root / "selection.json"
            left.write_text(json.dumps({"hpwl": {"ruplace_flag": 0}}))
            right.write_text(json.dumps({"hpwl": {"ruplace_flag": 1}}))
            selection.write_text(json.dumps({"selected_methods": []}))
            with self.assertRaisesRegex(ValueError, "conflicting preset"):
                freeze_presets([left, right], [selection])

    def test_cli_writes_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            presets = root / "presets.json"
            selection = root / "selection.json"
            output = root / "frozen.json"
            presets.write_text(json.dumps({
                "hpwl": {"ruplace_flag": 0},
                "atomic": {"ruplace_plugins": ["net_overlap"]},
            }))
            selection.write_text(json.dumps({"selected_methods": ["atomic"]}))

            status = main([
                "--preset-source", str(presets),
                "--selection", str(selection),
                "--output", str(output),
            ])

            frozen = json.loads(output.read_text())
            provenance = json.loads(
                output.with_suffix(".json.provenance.json").read_text()
            )

        self.assertEqual(status, 0)
        self.assertEqual(set(frozen), {"hpwl", "atomic"})
        self.assertEqual(provenance["baseline"], "hpwl")


if __name__ == "__main__":
    unittest.main()
