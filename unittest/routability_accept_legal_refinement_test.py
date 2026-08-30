#!/usr/bin/env python3

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_accept_legal_refinement import accept_legal_refinement
from tools.routability_select_survivors import routability_metric_profile


class RoutabilityAcceptLegalRefinementTest(unittest.TestCase):
    def write_evaluation(self, root, value, regression=None):
        root.mkdir(parents=True)
        profile = routability_metric_profile("absolute_directional_v2")
        for backend in ("rudy", "gpugr"):
            metrics = {
                metric: float(value)
                for item_backend, metric in profile["primary"]
                if item_backend == backend
            }
            if regression and regression[0] == backend:
                metrics[regression[1]] = float(regression[2])
            (root / (backend + ".json")).write_text(json.dumps({
                "backend": backend,
                "design_name": "test",
                "status": "ok",
                "metrics": metrics,
            }))

    def write_proposal(self, path, baseline, oracle, placement, lef):
        path.write_text(json.dumps({
            "schema_version": 2,
            "operation": "route_directed_legal_whitespace_slide",
            "baseline_def": str(baseline.resolve()),
            "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
            "candidate_def": str(oracle.resolve()),
            "candidate_sha256": hashlib.sha256(oracle.read_bytes()).hexdigest(),
            "lef_sha256": {
                str(lef.resolve()): hashlib.sha256(lef.read_bytes()).hexdigest(),
            },
            "output_def": str(placement.resolve()),
            "output_sha256": hashlib.sha256(placement.read_bytes()).hexdigest(),
            "baseline_overlap_pairs": 0,
            "output_overlap_pairs": 0,
        }))

    def test_accepts_first_strict_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            materialized = root / "selected.def"
            baseline.write_text("baseline")
            oracle = root / "oracle.def"
            oracle.write_text("oracle")
            lef = root / "cells.lef"
            lef.write_text("lef")
            candidate.write_text("candidate")
            self.write_evaluation(root / "baseline_eval", 10)
            self.write_evaluation(root / "candidate_eval", 9)
            proposal = root / "proposal.json"
            self.write_proposal(proposal, baseline, oracle, candidate, lef)

            result = accept_legal_refinement(
                baseline,
                root / "baseline_eval",
                [("candidate", candidate, root / "candidate_eval", proposal)],
                output=materialized,
            )
            materialized_text = materialized.read_text()

        self.assertEqual(result["decision"], "accepted")
        self.assertEqual(result["selected_candidate"], "candidate")
        self.assertEqual(materialized_text, "candidate")

    def test_rolls_back_on_any_gpugr_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.def"
            candidate = root / "candidate.def"
            materialized = root / "selected.def"
            baseline.write_text("baseline")
            oracle = root / "oracle.def"
            oracle.write_text("oracle")
            lef = root / "cells.lef"
            lef.write_text("lef")
            candidate.write_text("candidate")
            self.write_evaluation(root / "baseline_eval", 10)
            self.write_evaluation(
                root / "candidate_eval", 9,
                regression=("gpugr", "gr_wirelength", 11),
            )
            proposal = root / "proposal.json"
            self.write_proposal(proposal, baseline, oracle, candidate, lef)

            result = accept_legal_refinement(
                baseline,
                root / "baseline_eval",
                [("candidate", candidate, root / "candidate_eval", proposal)],
                output=materialized,
            )
            materialized_text = materialized.read_text()

        self.assertEqual(result["decision"], "rollback_to_baseline")
        self.assertEqual(result["selected_candidate"], "baseline")
        self.assertEqual(materialized_text, "baseline")
        self.assertEqual(
            result["candidates"][0]["gpugr_regressions"], ["gr_wirelength"]
        )


if __name__ == "__main__":
    unittest.main()
