#!/usr/bin/env python3

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval import EvaluationResult
from tools.routability_backfill_openroad_congestion import backfill_one, update_comparison


def original_result(root):
    artifacts = {}
    for name in ("log", "drc", "metrics", "guide", "script"):
        path = root / ("openroad_%s.txt" % name)
        path.write_text("")
        artifacts[name] = str(path)
    raw = {
        "global_route__wirelength": 100,
        "global_route__vias": 10,
        "route__wirelength": 80,
        "route__vias": 12,
        "route__drc_errors": 0,
        "route__net": 1,
    }
    Path(artifacts["metrics"]).write_text(json.dumps(raw))
    Path(artifacts["log"]).write_text(
        "Number of nets: 1\n"
        "[INFO DRT-0199] Number of violations = 0.\n"
        "Viol/Layer Metal2\n"
        "[INFO DRT-0267] done\n"
    )
    return {
        "backend": "openroad", "design_name": "case_a", "status": "ok",
        "metrics": {
            "wirelength": 80, "vias": 12, "drc_violations": 0,
            "unrouted_nets": 0.0, "short_violations": 0.0,
            "horizontal_overflow": 0.0, "vertical_overflow": 0.0,
            "openroad_metrics": raw,
        },
        "artifacts": artifacts,
    }


class FakeEvaluator:
    def __init__(self, wirelength=100):
        self.wirelength = wirelength

    def evaluate(self, request):
        root = Path(request.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        for name, filename in (
            ("congestion", "openroad_congestion.rpt"),
            ("log", "openroad.log"),
            ("script", "openroad_eval.tcl"),
            ("metrics", "openroad_metrics.json"),
            ("guide", "openroad.guide"),
        ):
            path = root / filename
            path.write_text(
                "violation type: Horizontal congestion\n"
                "  comment: capacity:1 usage:4 overflow:3\n"
                "violation type: Vertical congestion\n"
                "  comment: capacity:1 usage:5 overflow:4\n"
                if name == "congestion" else ""
            )
            artifacts[name] = str(path)
        raw = {
            "global_route__wirelength": self.wirelength,
            "global_route__vias": 10,
        }
        Path(artifacts["metrics"]).write_text(json.dumps(raw))
        return EvaluationResult(
            backend="openroad", design_name="case_a",
            metrics={
                "wirelength": self.wirelength, "vias": 10,
                "horizontal_overflow": 3.0, "vertical_overflow": 4.0,
                "total_overflow": 7.0, "overflow": 7.0,
                "horizontal_overflow_edges": 1,
                "vertical_overflow_edges": 1,
                "openroad_metrics": raw,
            },
            artifacts=artifacts,
        )


class RoutabilityBackfillOpenROADCongestionTest(unittest.TestCase):
    def fixture(self, root):
        methods = root / "campaign" / "case_a" / "seed_1" / "case_a" / "methods"
        method = methods / "hpwl"
        evaluation = method / "evaluation"
        placement = method / "placement"
        evaluation.mkdir(parents=True)
        placement.mkdir()
        placed = placement / "case_a.gp.def"
        placed.write_text("END DESIGN\n")
        (method / "config.json").write_text(json.dumps({
            "lef_input": [str(root / "input.lef")],
            "def_input": str(root / "case_a.def"),
            "result_dir": str(placement),
        }))
        result = original_result(evaluation)
        (evaluation / "summary.json").write_text(json.dumps({"results": [result]}))
        (evaluation / "openroad.json").write_text(json.dumps(result))
        comparison_result = {"method": "hpwl", **result}
        (methods / "comparison.json").write_text(json.dumps({
            "validation": {"status": "validated"},
            "placements": [], "results": [comparison_result],
        }))
        with (methods / "comparison.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("method", "evaluator"))
            writer.writeheader()
            writer.writerow({"method": "hpwl", "evaluator": "openroad"})
        return evaluation / "summary.json", methods / "comparison.json"

    def test_backfill_requires_identity_and_updates_retained_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, comparison = self.fixture(Path(tmp))
            record = backfill_one(summary, 1, 10, evaluator=FakeEvaluator())
            update_comparison(record)
            summary_row = json.loads(summary.read_text())["results"][0]
            comparison_row = json.loads(comparison.read_text())["results"][0]
            congestion_exists = Path(
                summary_row["artifacts"]["congestion"]
            ).is_file()

        self.assertEqual(summary_row["metrics"]["horizontal_overflow"], 3.0)
        self.assertEqual(summary_row["metrics"]["vertical_overflow"], 4.0)
        self.assertTrue(congestion_exists)
        self.assertEqual(comparison_row["metrics"]["total_overflow"], 7.0)
        self.assertIn("directional_congestion", comparison_row["metric_provenance"])

    def test_backfill_rejects_global_route_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, _comparison = self.fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "global_route__wirelength mismatch"):
                backfill_one(summary, 1, 10, evaluator=FakeEvaluator(wirelength=101))

    def test_incomplete_campaign_mode_skips_non_ok_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, _comparison = self.fixture(Path(tmp))
            data = json.loads(summary.read_text())
            data["results"][0]["status"] = "timeout"
            summary.write_text(json.dumps(data))

            record = backfill_one(
                summary, 1, 10, evaluator=FakeEvaluator(), skip_non_ok=True
            )

        self.assertEqual(record["status"], "skipped_non_ok")
        self.assertEqual(record["method"], "hpwl")

    def test_incomplete_campaign_mode_allows_running_case_without_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, comparison = self.fixture(Path(tmp))
            record = backfill_one(
                summary, 1, 10, evaluator=FakeEvaluator(), skip_non_ok=True
            )
            comparison.unlink()

            updated = update_comparison(record, skip_missing=True)

        self.assertFalse(updated)


if __name__ == "__main__":
    unittest.main()
