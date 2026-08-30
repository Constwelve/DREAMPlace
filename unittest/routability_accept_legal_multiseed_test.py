#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_accept_legal_multiseed import audit_multiseed


def acceptance(path, accepted):
    rows = [
        {"name": "a", "accepted": "a" in accepted},
        {"name": "b", "accepted": "b" in accepted},
    ]
    path.write_text(json.dumps({
        "status": "complete",
        "decision": "accepted" if accepted else "rollback_to_baseline",
        "metric_profile": "absolute_directional_v2",
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "strict_gate": {
            "gpugr_positive_worst_regression_allowed": False,
        },
        "candidates": rows,
    }))


class RoutabilityAcceptLegalMultiseedTest(unittest.TestCase):
    def test_intersects_only_strict_per_seed_survivors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "1000.json"
            second = root / "2000.json"
            acceptance(first, {"a", "b"})
            acceptance(second, {"b"})
            result = audit_multiseed([(1000, first), (2000, second)])

        self.assertEqual(result["decision"], "accepted")
        self.assertEqual(result["common_strict_survivors"], ["b"])
        self.assertEqual(result["selected_candidate"], "b")

    def test_rejects_candidate_order_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "1000.json"
            second = root / "2000.json"
            acceptance(first, {"a"})
            acceptance(second, {"a"})
            data = json.loads(second.read_text())
            data["candidates"].reverse()
            second.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "coverage or policy"):
                audit_multiseed([(1000, first), (2000, second)])


if __name__ == "__main__":
    unittest.main()
