#!/usr/bin/env python3

import json
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_generate_family_presets import generate_family_presets


class RoutabilityGenerateFamilyPresetsTest(unittest.TestCase):
    def setUp(self):
        self.base = {
            "hpwl": {"ruplace_flag": 0},
            "route_inflation": {
                "ruplace_flag": 1,
                "routability_opt_flag": 1,
                "ruplace_proxy": "gpugr",
                "ruplace_plugins": ["route_inflation"],
            },
            "routeforce": {
                "ruplace_flag": 1,
                "routability_opt_flag": 1,
                "ruplace_proxy": "gpugr",
                "ruplace_plugins": ["routeforce"],
            },
        }

    def test_generates_explicit_bounded_family_points(self):
        spec = {
            "name_prefix": "missing",
            "shared_overrides": {"ruplace_plugin_start_overflow": 0.8},
            "families": [
                {
                    "plugin": "route_inflation",
                    "proxy": "gpugr",
                    "variants": [
                        {"name": "weak", "overrides": {
                            "ruplace_inflate_area_cap": 0.0025,
                        }},
                        {"name": "directional", "overrides": {
                            "ruplace_hv_inflate_gamma": 0.1,
                        }},
                    ],
                },
                {
                    "plugin": "routeforce",
                    "proxy": "gpugr",
                    "variants": [{"name": "relative", "overrides": {
                        "ruplace_admm_scale_mode": "relative",
                    }}],
                },
            ],
        }

        presets, manifest = generate_family_presets(self.base, spec)

        self.assertEqual(len(presets), 4)
        self.assertEqual(len(manifest["generated"]), 3)
        self.assertEqual(presets["hpwl"], self.base["hpwl"])
        self.assertNotIn("ruplace_plugin_start_overflow", presets["hpwl"])
        self.assertEqual(
            manifest["required_families"], ["route_inflation", "routeforce"]
        )
        routeforce = next(
            presets[name] for name, row in manifest["generated"].items()
            if row["family"] == "routeforce"
        )
        self.assertEqual(routeforce["ruplace_external_route_eval"], 0)
        self.assertEqual(routeforce["ruplace_plugin_start_overflow"], 0.8)

    def test_rejects_identity_overrides_and_duplicate_points(self):
        base = {
            "families": [{
                "plugin": "route_inflation",
                "variants": [{"name": "bad", "overrides": {
                    "ruplace_plugins": ["routeforce"],
                }}],
            }],
        }
        with self.assertRaisesRegex(ValueError, "identity keys"):
            generate_family_presets(self.base, base)

        base["families"][0]["variants"] = [
            {"name": "a", "overrides": {"x": 1}},
            {"name": "b", "overrides": {"x": 1}},
        ]
        with self.assertRaisesRegex(ValueError, "duplicate parameter points"):
            generate_family_presets(self.base, base)

    def test_routeforce_rejects_nonrouting_proxy(self):
        spec = {"families": [{
            "plugin": "routeforce",
            "proxy": "rudy",
            "variants": [{"name": "bad", "overrides": {"x": 1}}],
        }]}
        with self.assertRaisesRegex(ValueError, "in-process"):
            generate_family_presets(self.base, spec)

    def test_campaign_tunes_activation_thresholds_for_every_family(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_missing_families_absolute_directional_v2.json"
            ).read_text()
        )
        presets, manifest = generate_family_presets(base, spec)
        self.assertEqual(presets["hpwl"], {
            "detailed_place_flag": 0,
            "routability_opt_flag": 0,
            "ruplace_flag": 0,
        })
        thresholds = {}
        for method, provenance in manifest["generated"].items():
            family = provenance["family"]
            key = (
                "ruplace_plugin_start_overflow"
                if family == "routeforce"
                else "ruplace_inflate_start_overflow"
            )
            thresholds.setdefault(family, set()).add(presets[method][key])
        for family, values in thresholds.items():
            self.assertTrue(
                {0.3, 0.5, 0.8}.issubset(values),
                "%s does not cover early/medium/late activation" % family,
            )

    def test_proxy_coverage_campaign_spans_lifecycle_and_absolute_hv_modes(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs/routability_proxy_coverage_absolute_directional_v2.json"
        ).read_text())

        presets, manifest = generate_family_presets(base, spec)

        self.assertEqual(len(manifest["generated"]), 12)
        self.assertEqual(
            {row["proxy"] for row in manifest["generated"].values()},
            {"gpugr"},
        )
        net_methods = [
            method for method, row in manifest["generated"].items()
            if row["family"] == "net_weighting"
        ]
        poisson_methods = [
            method for method, row in manifest["generated"].items()
            if row["family"] == "poisson_force"
        ]
        self.assertEqual(
            {presets[method]["ruplace_net_weight_phase"] for method in net_methods},
            {"pre_objective", "post_gradient"},
        )
        self.assertTrue(all(
            presets[method]["ruplace_net_weight_normalization"] == "design_mean"
            for method in net_methods
        ))
        self.assertEqual(
            {
                presets[method]["ruplace_force_congestion_mode"]
                for method in poisson_methods
            },
            {
                "utilization_hv_max", "utilization_hv_mean",
                "utilization_horizontal", "utilization_vertical",
            },
        )


if __name__ == "__main__":
    unittest.main()
