#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest

import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_audit_gpugr_identity import audit_identity


def write_bundle(root, label, offset=0.0, request=None):
    directory = root / label
    directory.mkdir()
    result = directory / "gpugr.json"
    tensor = directory / "gpugr.pt"
    provenance = directory / "provenance.json"
    metrics = {
        "gr_wirelength": 100.0 + offset,
        "num_ovfl_nets": 2,
        "time": 3.0 + offset,
    }
    result.write_text(json.dumps({
        "backend": "gpugr", "status": "ok", "metrics": metrics,
    }))
    value = torch.tensor([[0.5 + offset]])
    torch.save({
        "utilization_map": value,
        "overflow_map": torch.zeros_like(value),
        "hv_utilization_map": torch.stack((value, value)),
        "hv_overflow_map": torch.zeros(2, 1, 1),
    }, tensor)
    provenance.write_text(json.dumps({
        "request": request or {"design_name": "d", "options": {}},
        "native_extensions": {"gpugr": {
            "status": "resolved", "path": "/%s/gpugr.so" % label,
            "sha256": label * 64, "python_cache_tag": "cpython-x",
        }},
    }))
    return result, tensor, provenance


class RoutabilityAuditGPUGRIdentityTest(unittest.TestCase):
    def test_accepts_exact_maps_metrics_and_request_across_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = write_bundle(root, "a")
            right = write_bundle(root, "b")
            output = root / "audit.json"
            report = audit_identity(*left, *right, output=output)

        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["maps_exact"])
        self.assertTrue(report["metrics_exact"])
        self.assertEqual(
            report["optimization_native_gradient_equivalence"], "not_proven"
        )

    def test_rejects_map_or_metric_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = write_bundle(root, "a")
            right = write_bundle(root, "b", offset=0.25)
            report = audit_identity(*left, *right)

        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["maps_exact"])
        self.assertFalse(report["metrics_exact"])

    def test_rejects_different_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = write_bundle(root, "a")
            right = write_bundle(
                root, "b", request={"design_name": "other", "options": {}}
            )
            report = audit_identity(*left, *right)

        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["request_exact"])


if __name__ == "__main__":
    unittest.main()
