import json
import tempfile
import unittest
from pathlib import Path

from tools.routability_prune_proxy_snapshots import manifest_totals, process_once


class RoutabilityPruneProxySnapshotsTest(unittest.TestCase):
    def make_method(self, root, name="method", final_def=True, complete=True):
        method = root / "case" / "seed_1000" / "methods" / name
        external = method / "placement" / "design" / "ruplace" / "external"
        external.mkdir(parents=True)
        (external / "route_0001.def").write_text("snapshot one\n")
        (external / "route_0002.def").write_text("snapshot two\n")
        if final_def:
            (method / "placement" / "design" / "design.gp.def").write_text(
                "final placement\n"
            )
        if complete:
            evaluation = method / "evaluation"
            evaluation.mkdir(parents=True)
            (evaluation / "summary.json").write_text('{"results": []}\n')
        return method

    def test_dry_run_preserves_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            method = self.make_method(root)
            manifest = root / "manifest.jsonl"
            records = process_once(root, manifest, execute=False)
            self.assertEqual(records[0]["status"], "dry_run")
            self.assertEqual(records[0]["snapshot_count"], 2)
            self.assertEqual(len(list(method.glob("placement/**/route_*.def"))), 2)

    def test_execute_prunes_only_completed_method_with_final_def(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete = self.make_method(root, "complete")
            missing_final = self.make_method(root, "missing_final", final_def=False)
            incomplete = self.make_method(root, "incomplete", complete=False)
            manifest = root / "manifest.jsonl"
            records = process_once(root, manifest, execute=True)
            statuses = {
                Path(record["method_dir"]).name: record["status"]
                for record in records
            }
            self.assertEqual(statuses["complete"], "pruned")
            self.assertEqual(
                statuses["missing_final"], "refused_missing_final_def"
            )
            self.assertFalse(list(complete.glob("placement/**/route_*.def")))
            self.assertEqual(
                len(list(missing_final.glob("placement/**/route_*.def"))), 2
            )
            self.assertEqual(len(list(incomplete.glob("placement/**/route_*.def"))), 2)
            lines = [json.loads(line) for line in manifest.read_text().splitlines()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(len(lines[0]["final_defs"]), 1)
            self.assertIn("sha256", lines[0]["final_defs"][0])

    def test_execute_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_method(root)
            manifest = root / "manifest.jsonl"
            first = process_once(root, manifest, execute=True)
            second = process_once(root, manifest, execute=True)
            self.assertEqual(first[0]["status"], "pruned")
            self.assertEqual(second, [])

    def test_manifest_totals_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_method(root)
            manifest = root / "manifest.jsonl"
            records = process_once(root, manifest, execute=True)
            total = manifest_totals(manifest)
            self.assertEqual(total["methods"], 1)
            self.assertEqual(total["snapshots"], 2)
            self.assertEqual(total["bytes"], records[0]["snapshot_bytes"])


if __name__ == "__main__":
    unittest.main()
