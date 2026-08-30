#!/usr/bin/env python3

import hashlib
import json
from pathlib import Path
import tempfile
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_audit_corrected import (
    POLICY_V7_CANDIDATE_COUNT,
    audit_policy_v7_attestation_record,
)
from tools.routability_audit_policy_v7 import (
    FACTORIAL_DIMENSIONS,
    OPTIMIZATION_SOURCE_FILES,
    audit_active_net_mask,
    audit_factorial,
    audit_gpugr_runtime,
    audit_optimization_source_install,
)
from tools.routability_generate_presets import generate_presets


class RoutabilityAuditPolicyV7Test(unittest.TestCase):
    def generated_grid(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (ROOT / "configs/routability_net_weight_corridor_v2.json").read_text()
        )
        presets, generated = generate_presets(base, spec, max_presets=192)
        manifest = {
            "metadata": {
                "development_only": True,
                "heldout_or_golden_evidence_used": False,
                "numeric_backend_mixing": False,
                "generated_count": len(generated),
            },
            "generated": generated,
        }
        return presets, manifest

    def attestation(self):
        return {
            "schema_version": 1,
            "status": "passed",
            "stage": "corrected_net_weight_lifecycle_development",
            "proposal_policy_version": 7,
            "metric_profile": "absolute_directional_v2",
            "numeric_backend_mixing": False,
            "heldout_or_golden_evidence_used": False,
            "candidate_count": 192,
            "method_count": 193,
            "comparison_count": 6,
            "candidate_placement_count": 1152,
            "evaluator_result_count": 2316,
            "placement_hpwl_count": 1158,
            "primary_metric_value_count": 33582,
            "factorial_dimensions": FACTORIAL_DIMENSIONS,
            "factorial_unique_point_count": 192,
            "optimization_source_install_match": True,
            "optimization_source_sha256": {
                name: "9" * 64 for name in OPTIMIZATION_SOURCE_FILES
            },
            "active_net_mask_audit_status": "passed",
            "gpugr_runtime_sha256": {
                "gpugr_extension": "a" * 64,
                "io_parser_extension": "b" * 64,
                "xplace_common": "c" * 64,
                "xplace_flute": "d" * 64,
            },
            "selected_methods": [],
            "selection_recomputed": True,
            "placement_effect_recomputed": True,
            "active_changed_count": 990,
            "active_identical_count": 2,
            "inactive_identical_count": 112,
            "inactive_changed_count": 48,
            "placement_effect_excluded_methods": [
                "inactive_method", "active_identical_method",
            ],
            "sha256": {
                name: character * 64
                for name, character in zip((
                    "presets", "manifest", "summary", "screening_raw",
                    "selection", "placement_effect_audit",
                    "selection_audit", "terminal_status",
                    "optimization_source_install", "active_net_mask_audit",
                ), "abcdef1234")
            },
        }

    def test_source_install_manifest_binds_both_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "source_install.sha256"
            rows = []
            for name in OPTIMIZATION_SOURCE_FILES:
                payload = (name + "\n").encode()
                source = root / name
                installed = root / ("install/" + name)
                source.parent.mkdir(parents=True, exist_ok=True)
                installed.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(payload)
                installed.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                rows.extend((
                    "%s  %s" % (digest, name),
                    "%s  install/%s" % (digest, name),
                ))
            manifest.write_text("\n".join(rows) + "\n")
            verified = audit_optimization_source_install(manifest, root)
            self.assertEqual(set(verified), set(OPTIMIZATION_SOURCE_FILES))
            (root / ("install/" + OPTIMIZATION_SOURCE_FILES[0])).write_text(
                "changed\n"
            )
            with self.assertRaisesRegex(ValueError, "identity"):
                audit_optimization_source_install(manifest, root)

    def test_active_net_mask_audit_rejects_mutation(self):
        record = {
            "status": "passed",
            "active_net_mask": "net_mask_ignore_large_degrees",
            "active_nets": [True, True, False],
            "masked_net_affects_scale": False,
            "masked_net_ratio": 1.0,
            "ratios": [1.0, 1.25, 1.0],
            "score_scale": 2.0,
            "rudy_feedback_net_weights": "frozen_input",
            "rudy_feedback_after_objective_weight_change": 2.0,
            "net_weight_score_modes": ["pin_mean", "bbox_mean", "bbox_pmean"],
            "pin_mean_corridor_example": 1.0,
            "bbox_mean_corridor_example": 12.0,
            "bbox_pmean_corridor_example": 57.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active_mask.json"
            path.write_text(json.dumps(record))
            self.assertEqual(audit_active_net_mask(path), record)
            record["masked_net_ratio"] = 1.1
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "active-net-mask"):
                audit_active_net_mask(path)

    def test_gpugr_runtime_requires_exact_binary_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specs = []
            for label in (
                "gpugr_extension", "io_parser_extension",
                "xplace_common", "xplace_flute",
            ):
                path = root / label
                path.write_text(label)
                specs.append("%s=%s" % (label, path))
            hashes = audit_gpugr_runtime(specs)
            self.assertEqual(set(hashes), {
                "gpugr_extension", "io_parser_extension",
                "xplace_common", "xplace_flute",
            })
            with self.assertRaisesRegex(ValueError, "coverage"):
                audit_gpugr_runtime(specs[:-1])

    def test_real_spec_is_exact_complete_factorial(self):
        presets, manifest = self.generated_grid()
        points = audit_factorial(presets, manifest)
        self.assertEqual(len(points), POLICY_V7_CANDIDATE_COUNT)

    def test_factorial_rejects_duplicate_point(self):
        presets, manifest = self.generated_grid()
        methods = sorted(manifest["generated"])
        source, target = methods[:2]
        manifest["generated"][target]["grid"] = dict(
            manifest["generated"][source]["grid"]
        )
        manifest["generated"][target]["proxy"] = (
            manifest["generated"][source]["proxy"]
        )
        presets[target].update(presets[source])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_factorial(presets, manifest)

    def test_attestation_rejects_missing_primary_metric_coverage(self):
        record = self.attestation()
        self.assertIs(audit_policy_v7_attestation_record(record), record)
        record["primary_metric_value_count"] -= 1
        with self.assertRaisesRegex(ValueError, "Policy V7"):
            audit_policy_v7_attestation_record(record)

    def test_attestation_rejects_invalid_placement_effect_partition(self):
        record = self.attestation()
        record["inactive_changed_count"] -= 1
        with self.assertRaisesRegex(ValueError, "Policy V7"):
            audit_policy_v7_attestation_record(record)

    def test_attestation_rejects_selected_excluded_method(self):
        record = self.attestation()
        record["selected_methods"] = ["inactive_method"]
        with self.assertRaisesRegex(ValueError, "Policy V7"):
            audit_policy_v7_attestation_record(record)


if __name__ == "__main__":
    unittest.main()
