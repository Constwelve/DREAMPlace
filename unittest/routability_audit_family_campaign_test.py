#!/usr/bin/env python3

import json
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_audit_family_campaign import (
    EXPECTED_CASE_SEEDS,
    REQUIRED_FAMILIES,
    STAGE_LABEL,
    audit_family_attestation_record,
    audit_family_manifest,
    audit_family_tuning_coverage,
)
from tools.routability_audit_corrected import MISSING_FAMILY_TUNING_KEYS
from tools.routability_generate_family_presets import generate_family_presets


class RoutabilityAuditFamilyCampaignTest(unittest.TestCase):
    def fixture(self):
        presets = {"hpwl": {"ruplace_flag": 0}}
        generated = {}
        coverage = {}
        for index, family in enumerate(REQUIRED_FAMILIES):
            method = "method_%d" % index
            proxy = "gpugr" if family == "routeforce" else "rudy"
            presets[method] = {
                "ruplace_plugins": [family],
                "ruplace_proxy": proxy,
            }
            if family == "routeforce":
                presets[method]["ruplace_external_route_eval"] = 0
            generated[method] = {
                "family": family,
                "plugins": [family],
                "proxy": proxy,
                "development_only": True,
            }
            coverage[family] = [method]
        manifest = {
            "schema_version": 1,
            "required_families": list(REQUIRED_FAMILIES),
            "heldout_or_golden_evidence_used": False,
            "numeric_backend_mixing": False,
            "generated": generated,
        }
        return presets, manifest, coverage

    def test_manifest_requires_every_missing_family(self):
        presets, manifest, coverage = self.fixture()
        self.assertEqual(audit_family_manifest(presets, manifest), coverage)
        del manifest["generated"]["method_0"]
        del presets["method_0"]
        with self.assertRaisesRegex(ValueError, "no variants"):
            audit_family_manifest(presets, manifest)

    def test_attestation_binds_development_scope_and_resolution(self):
        coverage = {
            family: ["%s_method_%d" % (family, index) for index in range(6)]
            for family in REQUIRED_FAMILIES
        }
        tuning = {}
        for family in REQUIRED_FAMILIES:
            threshold_key = (
                "ruplace_plugin_start_overflow"
                if family == "routeforce"
                else "ruplace_inflate_start_overflow"
            )
            keys = MISSING_FAMILY_TUNING_KEYS[family]
            tuning[family] = {
                "variant_count": 6,
                "activation_threshold_key": threshold_key,
                "activation_thresholds": [0.3, 0.5, 0.8],
                "varied_parameter_keys": list(keys),
                "parameter_values": {key: [0, 1] for key in keys},
            }
        record = {
            "schema_version": 1,
            "status": "passed",
            "stage": STAGE_LABEL,
            "metric_profile": "absolute_directional_v2",
            "numeric_backend_mixing": False,
            "heldout_or_golden_evidence_used": False,
            "required_families": list(REQUIRED_FAMILIES),
            "family_methods": coverage,
            "retained_family_methods": {
                family: list(methods) for family, methods in coverage.items()
            },
            "activation_contract": (
                "every retained plugin is active on every development case/seed"
            ),
            "activation_audit": {
                "schema_version": 1,
                "status": "passed",
                "case_seed_count": len(EXPECTED_CASE_SEEDS),
                "method_count": 1 + sum(len(row) for row in coverage.values()),
                "inactive_method_count": 0,
                "inactive_methods": [],
            },
            "excluded_inactive_methods": [],
            "tuning_coverage": tuning,
            "evaluated_methods": ["hpwl"] + [
                method for methods in coverage.values() for method in methods
            ],
            "selected_methods": [],
            "validated_case_seeds": [
                {"case": case, "seed": seed}
                for case, seed in EXPECTED_CASE_SEEDS
            ],
            "reported_resolution": [256, 256],
            "validated_retained_placements": (
                len(EXPECTED_CASE_SEEDS)
                * sum(len(row) for row in coverage.values())
            ),
            "validated_proxy_results": (
                len(EXPECTED_CASE_SEEDS)
                * (1 + sum(len(row) for row in coverage.values())) * 2
            ),
            "sha256": {
                "presets": "a" * 64,
                "manifest": "b" * 64,
                "selection": "c" * 64,
                "screening_raw": "d" * 64,
            },
        }
        self.assertIs(audit_family_attestation_record(record), record)
        record["validated_case_seeds"][0]["case"] = "data_ispd19_test3"
        with self.assertRaisesRegex(ValueError, "invalid"):
            audit_family_attestation_record(record)

    def test_real_campaign_covers_required_tuning_dimensions(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (ROOT / "configs/"
             "routability_missing_families_absolute_directional_v2.json").read_text()
        )
        presets, manifest = generate_family_presets(base, spec)
        coverage = audit_family_manifest(presets, manifest)

        tuning = audit_family_tuning_coverage(presets, coverage)

        self.assertEqual(set(tuning), set(REQUIRED_FAMILIES))
        self.assertTrue(all(row["variant_count"] == 6 for row in tuning.values()))
        broken = json.loads(json.dumps(presets))
        for method in coverage["routeforce"]:
            broken[method]["ruplace_admm_route_freq"] = 50
        with self.assertRaisesRegex(ValueError, "ruplace_admm_route_freq"):
            audit_family_tuning_coverage(broken, coverage)


if __name__ == "__main__":
    unittest.main()
