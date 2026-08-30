#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_merge_atomic_survivors import merge_atomic_survivors
from tools.routability_generate_family_presets import generate_family_presets
from tools.routability_select_survivors import routability_metric_profile


def selection(method, max_survivors=5,
              metric_profile="absolute_directional_v2"):
    profile = routability_metric_profile(metric_profile)
    metrics = {}
    for backend, metric in profile["primary"]:
        metrics["%s:%s" % (backend, metric)] = {
            "mean_delta": -1.0,
            "mean_delta_pct": -1.0,
            "median_delta": -1.0,
            "median_delta_pct": -1.0,
            "worst_delta": 0.0,
            "worst_delta_pct": 0.0,
            "valid_count": 6,
            "percent_valid_count": 6,
        }
    return {
        "baseline": "hpwl",
        "expected_comparisons": 6,
        "selection_policy": {
            "name": "routability_first",
            "metric_profile": metric_profile,
            "numeric_backend_mixing": False,
            "max_survivors": max_survivors,
            "max_primary_worst_regression": 0.0,
            "worst_regression_backends": list(
                profile["worst_regression_backends"]
            ),
            "primary_objectives": [
                "%s:%s" % item for item in profile["primary"]
            ],
            "backend_improvement_constraints": json.loads(json.dumps(
                profile["constraints"]
            )),
        },
        "qualified": [{"method": method, "metrics": metrics}],
        "pareto_frontier": [method],
        "selected_methods": [method],
    }


class RoutabilityMergeAtomicSurvivorsTest(unittest.TestCase):
    def write_bundle(self, root, index, method, plugin, proxy,
                     max_survivors=5,
                     metric_profile="absolute_directional_v2"):
        bundle = root / str(index)
        bundle.mkdir()
        selection_path = bundle / "selection.json"
        presets_path = bundle / "presets.json"
        manifest_path = bundle / "manifest.json"
        selection_path.write_text(json.dumps(selection(
            method, max_survivors, metric_profile
        )))
        presets_path.write_text(json.dumps({
            "hpwl": {"ruplace_flag": 0},
            method: {
                "ruplace_plugins": [plugin],
                "ruplace_proxy": proxy,
            },
        }))
        manifest_path.write_text(json.dumps({
            "generated": {method: {
                "plugins": [plugin], "proxy": proxy,
            }},
        }))
        return selection_path, presets_path, manifest_path

    def write_generated_bundle(self, root, index, base, spec,
                               max_survivors=5):
        presets, manifest = generate_family_presets(base, spec)
        method = next(iter(manifest["generated"]))
        bundle = root / str(index)
        bundle.mkdir()
        selection_path = bundle / "selection.json"
        presets_path = bundle / "presets.json"
        manifest_path = bundle / "manifest.json"
        selection_path.write_text(json.dumps(selection(method, max_survivors)))
        presets_path.write_text(json.dumps(presets))
        manifest_path.write_text(json.dumps(manifest))
        return selection_path, presets_path, manifest_path

    def test_merges_independent_strict_atomic_survivors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = [
                self.write_bundle(root, 0, "old", "poisson_force", "rudy"),
                self.write_bundle(root, 1, "new", "routeforce", "gpugr"),
            ]
            presets, manifest, merged = merge_atomic_survivors(bundles)
        self.assertEqual(set(presets), {"hpwl", "old", "new"})
        self.assertEqual(merged["selected_methods"], ["old", "new"])
        self.assertEqual(manifest["metadata"]["source_count"], 2)

    def test_rejects_method_name_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = [
                self.write_bundle(root, 0, "same", "poisson_force", "rudy"),
                self.write_bundle(root, 1, "same", "routeforce", "gpugr"),
            ]
            with self.assertRaisesRegex(ValueError, "collision"):
                merge_atomic_survivors(bundles)

    def test_merges_capacity_absolute_v3_survivors_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = [
                self.write_bundle(
                    root, 0, "a", "directional_cvar_gradient", "gpugr",
                    metric_profile="absolute_directional_v3",
                ),
                self.write_bundle(
                    root, 1, "b", "directional_excess_cvar_gradient", "gpugr",
                    metric_profile="absolute_directional_v3",
                ),
            ]
            presets, manifest, merged = merge_atomic_survivors(
                bundles, metric_profile="absolute_directional_v3"
            )

        self.assertEqual(set(presets), {"hpwl", "a", "b"})
        self.assertEqual(merged["selected_methods"], ["a", "b"])
        self.assertEqual(
            merged["selection_policy"]["metric_profile"],
            "absolute_directional_v3",
        )
        self.assertEqual(manifest["metadata"]["source_count"], 2)

    def test_replay_adaptive_and_missing_bundles_keep_mergeable_hpwl(self):
        base = {
            "hpwl": {
                "detailed_place_flag": 1,
                "routability_opt_flag": 0,
                "ruplace_flag": 0,
            },
        }
        sources = [
            ("replay", "local_gradient", 0.3, 32),
            ("adaptive", "poisson_force", 0.5, 5),
            ("missing", "route_inflation", 0.8, 12),
            ("missing_adaptive", "routeforce", 0.8, 5),
        ]
        for _, plugin, _, _ in sources:
            base[plugin] = {
                "ruplace_flag": 1,
                "routability_opt_flag": 1,
                "ruplace_proxy": "gpugr",
                "ruplace_plugins": [plugin],
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = []
            for index, (source, plugin, threshold, max_survivors) in enumerate(
                sources
            ):
                bundles.append(self.write_generated_bundle(
                    root,
                    index,
                    base,
                    {
                        "name_prefix": source,
                        "shared_overrides": {
                            "ruplace_plugin_start_overflow": threshold,
                        },
                        "families": [{
                            "plugin": plugin,
                            "variants": [{
                                "name": "candidate",
                                "overrides": {"ruplace_plugin_strength": index + 1},
                            }],
                        }],
                    },
                    max_survivors,
                ))
            presets, manifest, merged = merge_atomic_survivors(bundles)

        self.assertEqual(presets["hpwl"], base["hpwl"])
        self.assertEqual(manifest["metadata"]["source_count"], 4)
        self.assertEqual(len(merged["selected_methods"]), 4)
        self.assertEqual(merged["selection_policy"]["max_survivors"], 54)
        self.assertEqual(
            merged["admission_union"]["source_max_survivors"], [32, 5, 12, 5]
        )

    def test_rejects_different_strict_admission_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundles = [
                self.write_bundle(root, 0, "a", "poisson_force", "rudy", 32),
                self.write_bundle(root, 1, "b", "routeforce", "gpugr", 5),
            ]
            path = bundles[1][0]
            data = json.loads(path.read_text())
            data["selection_policy"]["secondary_objectives"] = ["changed"]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "admission policies differ"):
                merge_atomic_survivors(bundles)

    def test_production_missing_family_hpwl_matches_scheduled_identity(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_missing_families_absolute_directional_v2.json"
            ).read_text()
        )
        presets, _ = generate_family_presets(base, spec)
        scheduled_hpwl = {
            "detailed_place_flag": 0,
            "routability_opt_flag": 0,
            "ruplace_flag": 0,
        }
        self.assertEqual(presets["hpwl"], scheduled_hpwl)


if __name__ == "__main__":
    unittest.main()
