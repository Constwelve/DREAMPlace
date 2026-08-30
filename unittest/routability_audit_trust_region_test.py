#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_audit_trust_region import audit_trust_region
from tools.routability_select_survivors import routability_metric_profile


def metrics(backend, value):
    names = [
        metric for item_backend, metric in
        routability_metric_profile("absolute_directional_v2")["primary"]
        if item_backend == backend
    ]
    return {name: value for name in names}


def write_result(path, backend, value):
    path.write_text(json.dumps({
        "backend": backend, "status": "ok", "metrics": metrics(backend, value),
    }))


class RoutabilityAuditTrustRegionTest(unittest.TestCase):
    def test_accepts_only_proxy_clean_orientation_preserving_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            baseline.mkdir()
            write_result(baseline / "rudy.json", "rudy", 10.0)
            write_result(baseline / "gpugr.json", "gpugr", 10.0)
            alpha = root / "experiment/alpha_0p5"
            (alpha / "evaluation").mkdir(parents=True)
            (alpha / "blend.json").write_text(json.dumps({
                "alpha": 0.5, "orientation_mismatch_count": 0,
            }))
            (alpha / "placement.def").write_text("END DESIGN\n")
            write_result(alpha / "evaluation/rudy.json", "rudy", 9.0)
            write_result(alpha / "evaluation/gpugr.json", "gpugr", 9.0)
            report = audit_trust_region(baseline, root / "experiment")

        self.assertEqual(report["decision"], "survivor")
        self.assertEqual(report["proxy_survivors"], [0.5])
        self.assertEqual(report["promotion_survivors"], [0.5])

    def test_rejects_gpugr_regression_and_orientation_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            baseline.mkdir()
            write_result(baseline / "rudy.json", "rudy", 10.0)
            write_result(baseline / "gpugr.json", "gpugr", 10.0)
            alpha = root / "experiment/alpha_0p5"
            (alpha / "evaluation").mkdir(parents=True)
            (alpha / "blend.json").write_text(json.dumps({
                "alpha": 0.5, "orientation_mismatch_count": 3,
            }))
            (alpha / "placement.def").write_text("END DESIGN\n")
            write_result(alpha / "evaluation/rudy.json", "rudy", 9.0)
            gpugr = metrics("gpugr", 9.0)
            gpugr["gr_wirelength"] = 11.0
            (alpha / "evaluation/gpugr.json").write_text(json.dumps({
                "backend": "gpugr", "status": "ok", "metrics": gpugr,
            }))
            report = audit_trust_region(baseline, root / "experiment")

        self.assertEqual(report["decision"], "rejected")
        self.assertFalse(report["rows"][0]["proxy_pass"])
        self.assertIn(
            "gpugr:gr_wirelength", report["rows"][0]["gpugr_regressions"]
        )
        self.assertFalse(report["rows"][0]["promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
