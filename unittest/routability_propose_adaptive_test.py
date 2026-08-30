#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest

from tools.routability_propose_adaptive import main, propose_adaptive


ANALYSIS = {
    "expected_comparisons": 6,
    "policy": {
        "numeric_backend_mixing": False,
        "selection_or_admission_decision": False,
        "metric_profile": "absolute_directional_v2",
    },
    "backends": {
        "gpugr": {
            "mean_pareto_frontier": ["force_parent", "weight_parent"],
            "worst_pareto_frontier": ["force_parent"],
        },
        "rudy": {
            "mean_pareto_frontier": ["force_parent"],
            "worst_pareto_frontier": ["weight_parent"],
        },
    },
    "cross_backend_frontier_intersection": {
        "mean": ["force_parent"],
        "worst": ["weight_parent"],
    },
    "methods": [
        {"method": "force_parent", "plugins": ["local_gradient"],
         "feedback_proxy": "gpugr", "eligible": True},
        {"method": "weight_parent", "plugins": ["net_weighting"],
         "feedback_proxy": "rudy", "eligible": True},
    ],
    "plugin_frontiers": {
        "local_gradient": {
            "backends": {
                "gpugr": {
                    "mean_pareto_frontier": ["force_parent"],
                    "worst_pareto_frontier": ["force_parent"],
                },
                "rudy": {
                    "mean_pareto_frontier": ["force_parent"],
                    "worst_pareto_frontier": ["force_parent"],
                },
            },
            "cross_backend_frontier_intersection": {
                "mean": ["force_parent"], "worst": ["force_parent"],
            },
        },
        "net_weighting": {
            "backends": {
                "gpugr": {
                    "mean_pareto_frontier": ["weight_parent"],
                    "worst_pareto_frontier": ["weight_parent"],
                },
                "rudy": {
                    "mean_pareto_frontier": ["weight_parent"],
                    "worst_pareto_frontier": ["weight_parent"],
                },
            },
            "cross_backend_frontier_intersection": {
                "mean": ["weight_parent"], "worst": ["weight_parent"],
            },
        },
    },
    "plugin_proxy_frontiers": {
        "local_gradient": {
            "gpugr": {
                "backends": {
                    "gpugr": {"mean_pareto_frontier": ["force_parent"],
                              "worst_pareto_frontier": ["force_parent"]},
                    "rudy": {"mean_pareto_frontier": ["force_parent"],
                             "worst_pareto_frontier": ["force_parent"]},
                },
                "cross_backend_frontier_intersection": {
                    "mean": ["force_parent"], "worst": ["force_parent"],
                },
            },
        },
        "net_weighting": {
            "rudy": {
                "backends": {
                    "gpugr": {"mean_pareto_frontier": ["weight_parent"],
                              "worst_pareto_frontier": ["weight_parent"]},
                    "rudy": {"mean_pareto_frontier": ["weight_parent"],
                             "worst_pareto_frontier": ["weight_parent"]},
                },
                "cross_backend_frontier_intersection": {
                    "mean": ["weight_parent"], "worst": ["weight_parent"],
                },
            },
        },
    },
}

PRESETS = {
    "hpwl": {"ruplace_flag": 0},
    "force_parent": {
        "ruplace_flag": 1,
        "routability_opt_flag": 1,
        "ruplace_plugins": ["local_gradient"],
        "ruplace_proxy": "gpugr",
        "ruplace_local_gradient_weight": 0.003,
        "ruplace_plugin_start_overflow": 0.8,
        "ruplace_force_apply_interval": 20,
        "ruplace_proxy_refresh_interval": 20,
        "ruplace_force_decay": 0.995,
        "ruplace_force_min_ratio": 0.1,
        "ruplace_force_max_ratio": 0.05,
        "ruplace_force_scale_mode": "relative",
    },
    "weight_parent": {
        "ruplace_flag": 1,
        "routability_opt_flag": 1,
        "ruplace_plugins": ["net_weighting"],
        "ruplace_proxy": "rudy",
        "ruplace_net_weight_gamma": 0.01,
        "ruplace_net_weight_freq": 20,
        "ruplace_proxy_refresh_interval": 20,
        "ruplace_net_weight_normalization": "absolute",
        "ruplace_net_weight_phase": "pre_objective",
        "ruplace_plugin_start_overflow": 0.8,
    },
}

MANIFEST = {
    "generated": {
        "force_parent": {"plugins": ["local_gradient"], "proxy": "gpugr"},
        "weight_parent": {"plugins": ["net_weighting"], "proxy": "rudy"},
    }
}


class RoutabilityProposeAdaptiveTest(unittest.TestCase):
    def test_policy_v8_adds_continuous_rudy_and_neumann_poisson_dimensions(self):
        from tools.routability_propose_adaptive import _force_changes

        parent = {
            "ruplace_proxy": "rudy",
            "ruplace_force_congestion_mode": "aggregate",
            "ruplace_poisson_solver": "periodic",
            "ruplace_poisson_weight": 0.003,
            "ruplace_force_apply_interval": 5,
            "ruplace_proxy_refresh_interval": 10,
            "ruplace_plugin_start_overflow": 0.8,
            "ruplace_force_decay": 0.995,
            "ruplace_force_min_ratio": 0.1,
            "ruplace_force_max_ratio": 0.05,
            "ruplace_force_scale_mode": "relative",
            "ruplace_poisson_smooth": 1,
        }
        legacy = dict(_force_changes(
            "poisson_force", parent, proposal_policy_version=6
        ))
        expanded = dict(_force_changes(
            "poisson_force", parent, proposal_policy_version=8
        ))

        self.assertNotIn("direction_utilization", legacy)
        self.assertNotIn("solver_neumann_dct", legacy)
        self.assertEqual(
            expanded["direction_utilization"],
            {"ruplace_force_congestion_mode": "utilization"},
        )
        self.assertEqual(
            expanded["solver_neumann_dct"],
            {"ruplace_poisson_solver": "neumann_dct"},
        )

    def test_refresh_variants_change_effective_application_cadence(self):
        from tools.routability_propose_adaptive import (
            _effective_refresh_interval,
            _refresh_variants,
            _routeforce_changes,
        )

        self.assertEqual(_effective_refresh_interval(25, 10), 50)
        self.assertEqual(_effective_refresh_interval(50, 10), 50)
        variants = _refresh_variants(50, 10, maximum=320)
        self.assertNotIn(25, variants)
        self.assertTrue(variants)
        self.assertTrue(all(value % 10 == 0 for value in variants))
        self.assertTrue(all(
            _effective_refresh_interval(value, 10) != 50
            for value in variants
        ))

        changes = _routeforce_changes({
            "ruplace_admm_weight": 0.03,
            "ruplace_admm_max_ratio": 0.1,
            "ruplace_admm_apply_freq": 10,
            "ruplace_admm_route_freq": 50,
            "ruplace_admm_weight_decay": 0.999,
        })
        route_values = [
            updates["ruplace_admm_route_freq"]
            for label, updates in changes if label.startswith("route_")
        ]
        self.assertTrue(route_values)
        self.assertTrue(all(
            _effective_refresh_interval(value, 10) != 50
            for value in route_values
        ))

    def test_proposes_bounded_atomic_development_variants(self):
        presets, generated, metadata = propose_adaptive(
            ANALYSIS, PRESETS, MANIFEST,
            max_parents=2, max_variants_per_parent=30,
        )

        self.assertIn("hpwl", presets)
        self.assertEqual(
            set(metadata["used_parents"]), {"force_parent", "weight_parent"}
        )
        self.assertFalse(metadata["numeric_backend_mixing"])
        self.assertFalse(metadata["heldout_or_golden_evidence_used"])
        self.assertTrue(metadata["atomic_plugins_only"])
        self.assertEqual(metadata["proposal_policy_version"], 6)
        self.assertTrue(metadata["balanced_tuning_dimensions"])
        self.assertTrue(metadata["effective_refresh_cadences_only"])
        self.assertEqual(
            metadata["effective_refresh_cadence_definition"],
            "lcm(refresh_interval,application_interval)",
        )
        self.assertTrue(metadata["joint_variants_prioritized"])
        self.assertTrue(all(len(row["plugins"]) == 1 for row in generated.values()))
        self.assertTrue(all(row["development_only"] for row in generated.values()))
        self.assertTrue(any(
            row["change"].startswith("apply_") for row in generated.values()
        ))
        self.assertTrue(any(
            row["change"].startswith("refresh_") for row in generated.values()
        ))
        self.assertTrue(any(
            row["change"] == "joint_gentle" for row in generated.values()
        ))
        self.assertTrue(any(
            row["change"] == "joint_frequent_small"
            for row in generated.values()
        ))
        self.assertTrue(any(
            "ruplace_local_gradient_smooth" in row["updates"]
            for row in generated.values()
        ))
        self.assertTrue(metadata["net_weight_lifecycle_tuned"])
        self.assertTrue(metadata["directional_feedback_tuned"])
        self.assertTrue(metadata["absolute_directional_feedback_tuned"])
        self.assertEqual(metadata["absolute_directional_feedback_modes"], [
            "utilization_hv_max",
            "utilization_hv_mean",
            "utilization_horizontal",
            "utilization_vertical",
        ])
        self.assertIn("ruplace_net_weight_phase", metadata["tuned_parameter_keys"])
        self.assertIn(
            "ruplace_force_congestion_mode", metadata["tuned_parameter_keys"]
        )
        self.assertTrue(any(
            row["plugins"] == ["net_weighting"]
            and "ruplace_net_weight_phase" in row["updates"]
            for row in generated.values()
        ))
        self.assertTrue(any(
            row["plugins"] == ["local_gradient"]
            and row["proxy"] == "gpugr"
            and row["change"].startswith("direction_")
            for row in generated.values()
        ))
        self.assertTrue(any(
            row["plugins"] == ["local_gradient"]
            and row["proxy"] == "gpugr"
            and row["updates"].get("ruplace_force_congestion_mode")
            in {"utilization_hv_max", "utilization_hv_mean"}
            for row in generated.values()
        ))

    def test_bounded_force_grid_keeps_effective_joint_and_cadence_changes(self):
        presets, generated, _ = propose_adaptive(
            ANALYSIS, PRESETS, MANIFEST,
            max_parents=1, max_variants_per_parent=16,
        )

        rows = list(generated.values())
        changes = {row["change"] for row in rows}
        self.assertIn("joint_gentle", changes)
        self.assertIn("joint_frequent_small", changes)
        self.assertTrue(any(name.startswith("apply_") for name in changes))
        self.assertTrue(any(name.startswith("refresh_") for name in changes))
        self.assertTrue(any(name.startswith("decay_") for name in changes))
        self.assertTrue(any(name.startswith("trust_") for name in changes))
        self.assertTrue(any(name.startswith("direction_") for name in changes))
        self.assertEqual({
            row["updates"].get("ruplace_force_congestion_mode")
            for row in rows
        } & {
            "utilization_hv_max", "utilization_hv_mean",
            "utilization_horizontal", "utilization_vertical",
        }, {
            "utilization_hv_max", "utilization_hv_mean",
            "utilization_horizontal", "utilization_vertical",
        })
        for row in rows:
            updates = row["updates"]
            if "ruplace_proxy_refresh_interval" in updates and row["change"].startswith("refresh_"):
                self.assertGreater(
                    updates["ruplace_proxy_refresh_interval"],
                    PRESETS["force_parent"]["ruplace_force_apply_interval"],
                )
            if row["change"].startswith("trust_"):
                self.assertLess(
                    updates["ruplace_force_max_ratio"],
                    PRESETS["force_parent"]["ruplace_local_gradient_weight"],
                )
        joint = next(
            name for name, row in generated.items()
            if row["change"] == "joint_gentle"
        )
        self.assertLess(
            presets[joint]["ruplace_local_gradient_weight"],
            PRESETS["force_parent"]["ruplace_local_gradient_weight"],
        )

    def test_respects_parent_and_variant_bounds(self):
        _, generated, metadata = propose_adaptive(
            ANALYSIS, PRESETS, MANIFEST,
            max_parents=1, max_variants_per_parent=3,
        )

        self.assertEqual(len(metadata["used_parents"]), 1)
        self.assertEqual(len(generated), 3)

    def test_rejects_mixed_backend_analysis(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["policy"]["numeric_backend_mixing"] = True

        with self.assertRaisesRegex(ValueError, "prohibit backend mixing"):
            propose_adaptive(analysis, PRESETS, MANIFEST)

    def test_rejects_legacy_or_partial_near_miss_evidence(self):
        legacy = json.loads(json.dumps(ANALYSIS))
        legacy["policy"]["metric_profile"] = "legacy"
        with self.assertRaisesRegex(ValueError, "absolute_directional_v2"):
            propose_adaptive(legacy, PRESETS, MANIFEST)

        partial = json.loads(json.dumps(ANALYSIS))
        partial["expected_comparisons"] = 3
        with self.assertRaisesRegex(ValueError, "six development"):
            propose_adaptive(partial, PRESETS, MANIFEST)

        missing_frontiers = json.loads(json.dumps(ANALYSIS))
        del missing_frontiers["plugin_frontiers"]
        with self.assertRaisesRegex(ValueError, "plugin-local"):
            propose_adaptive(missing_frontiers, PRESETS, MANIFEST)

        missing_proxy_frontiers = json.loads(json.dumps(ANALYSIS))
        del missing_proxy_frontiers["plugin_proxy_frontiers"]
        with self.assertRaisesRegex(ValueError, "feedback-proxy"):
            propose_adaptive(missing_proxy_frontiers, PRESETS, MANIFEST)

    def test_parent_coverage_precedes_extra_frontier_parents(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["cross_backend_frontier_intersection"] = {
            "mean": ["force_parent"], "worst": ["force_parent"],
        }
        presets, generated, metadata = propose_adaptive(
            analysis, PRESETS, MANIFEST,
            max_parents=2, max_variants_per_parent=2,
        )
        self.assertEqual(set(metadata["used_plugins"]), {
            "local_gradient", "net_weighting",
        })
        self.assertEqual(len(generated), 4)
        self.assertIn("hpwl", presets)

    def test_parent_coverage_includes_available_feedback_sources(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["methods"].append({
            "method": "force_rudy_parent",
            "plugins": ["local_gradient"],
            "feedback_proxy": "rudy",
            "eligible": True,
        })
        group = json.loads(json.dumps(
            analysis["plugin_proxy_frontiers"]["local_gradient"]["gpugr"]
        ))
        for backend in group["backends"].values():
            backend["mean_pareto_frontier"] = ["force_rudy_parent"]
            backend["worst_pareto_frontier"] = ["force_rudy_parent"]
        group["cross_backend_frontier_intersection"] = {
            "mean": ["force_rudy_parent"], "worst": ["force_rudy_parent"],
        }
        analysis["plugin_proxy_frontiers"]["local_gradient"]["rudy"] = group
        presets = json.loads(json.dumps(PRESETS))
        presets["force_rudy_parent"] = dict(presets["force_parent"])
        presets["force_rudy_parent"]["ruplace_proxy"] = "rudy"
        presets["force_rudy_parent"][
            "ruplace_force_congestion_mode"
        ] = "aggregate"
        manifest = json.loads(json.dumps(MANIFEST))
        manifest["generated"]["force_rudy_parent"] = {
            "plugins": ["local_gradient"], "proxy": "rudy",
        }

        _, _, metadata = propose_adaptive(
            analysis, presets, manifest,
            max_parents=3, max_variants_per_parent=1,
        )
        self.assertEqual(set(metadata["used_plugin_feedback_groups"]), {
            "local_gradient:gpugr", "local_gradient:rudy",
            "net_weighting:rudy",
        })

    def test_missing_families_receive_bounded_adaptive_grids(self):
        configs = {
            "route_inflation": {
                "ruplace_global_inflate_gamma": 0.1,
                "ruplace_local_inflate_gamma": 0.05,
                "ruplace_inflate_area_cap": 0.005,
                "ruplace_local_inflate_max_rounds": 2,
                "max_num_area_adjust": 2,
            },
            "momentum_inflation": {
                "ruplace_momentum_step": 0.1,
                "ruplace_momentum_beta": 0.8,
                "ruplace_momentum_rounds": 2,
                "ruplace_inflate_area_cap": 0.005,
                "max_num_area_adjust": 2,
            },
            "path_inflation": {
                "ruplace_path_inflate_gamma": 0.05,
                "ruplace_path_inflate_rounds": 2,
                "ruplace_inflate_area_cap": 0.005,
                "max_num_area_adjust": 2,
            },
            "pin_porosity": {
                "ruplace_pin_porosity_gamma": 0.05,
                "ruplace_pin_porosity_rounds": 2,
                "ruplace_porosity_radius": 3,
                "ruplace_porosity_weight": 0.1,
                "ruplace_inflate_area_cap": 0.005,
                "max_num_area_adjust": 2,
            },
            "routeforce": {
                "ruplace_admm_weight": 0.005,
                "ruplace_admm_max_ratio": 0.1,
                "ruplace_admm_apply_freq": 20,
                "ruplace_admm_route_freq": 100,
                "ruplace_admm_weight_decay": 0.999,
            },
        }
        proxies = {
            "route_inflation": "gpugr",
            "momentum_inflation": "gpugr",
            "path_inflation": "rudy",
            "pin_porosity": "rudy_pin",
            "routeforce": "gpugr",
        }
        parents = ["%s_parent" % plugin for plugin in configs]
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["methods"] = []
        analysis["plugin_frontiers"] = {}
        analysis["plugin_proxy_frontiers"] = {}
        analysis["cross_backend_frontier_intersection"] = {
            "mean": parents, "worst": parents,
        }
        for backend in analysis["backends"].values():
            backend["mean_pareto_frontier"] = parents
            backend["worst_pareto_frontier"] = parents
        presets = {"hpwl": {"ruplace_flag": 0}}
        manifest = {"generated": {}}
        for plugin, values in configs.items():
            parent = "%s_parent" % plugin
            proxy = proxies[plugin]
            analysis["methods"].append({
                "method": parent,
                "plugins": [plugin],
                "feedback_proxy": proxy,
                "eligible": True,
            })
            group = {
                "backends": {
                    backend: {
                        "mean_pareto_frontier": [parent],
                        "worst_pareto_frontier": [parent],
                    }
                    for backend in ("gpugr", "rudy")
                },
                "cross_backend_frontier_intersection": {
                    "mean": [parent], "worst": [parent],
                },
            }
            analysis["plugin_frontiers"][plugin] = group
            analysis["plugin_proxy_frontiers"][plugin] = {proxy: group}
            presets[parent] = {
                "ruplace_flag": 1,
                "routability_opt_flag": 1,
                "ruplace_plugins": [plugin],
                "ruplace_proxy": proxy,
                "ruplace_inflate_start_overflow": 0.5,
                "ruplace_plugin_start_overflow": 0.5,
                **values,
            }
            manifest["generated"][parent] = {
                "plugins": [plugin], "proxy": proxy,
            }

        _, generated, metadata = propose_adaptive(
            analysis, presets, manifest,
            max_parents=5, max_variants_per_parent=16,
        )

        self.assertEqual(set(metadata["used_plugins"]), set(configs))
        self.assertEqual(
            set(metadata["missing_family_adaptive_tuning"]), set(configs)
        )
        self.assertEqual(metadata["proposal_policy_version"], 6)
        for plugin in configs:
            rows = [
                row for row in generated.values()
                if row["plugins"] == [plugin]
            ]
            self.assertEqual(len(rows), 16)
            self.assertTrue(any(
                row["change"] == "joint_gentle" for row in rows
            ))
            self.assertTrue(any(
                row["change"] == "joint_early_gentle" for row in rows
            ))
            self.assertTrue(all(row["development_only"] for row in rows))

        tuned = metadata["tuned_parameter_keys"]
        for key in (
            "ruplace_global_inflate_gamma",
            "ruplace_momentum_step",
            "ruplace_path_inflate_gamma",
            "ruplace_pin_porosity_gamma",
            "ruplace_admm_weight",
        ):
            self.assertIn(key, tuned)

        _, coordinated, coordinated_metadata = propose_adaptive(
            analysis, presets, manifest,
            max_parents=5, max_variants_per_parent=16,
            proposal_policy_version=7,
        )
        self.assertEqual(coordinated_metadata["proposal_policy_version"], 7)
        self.assertTrue(
            coordinated_metadata["coordinated_area_controls_tuned"]
        )
        self.assertEqual(coordinated_metadata["area_effect_floor"], 1e-4)
        self.assertFalse(
            coordinated_metadata["dormant_single_parameter_area_variants"]
        )
        self.assertTrue(
            coordinated_metadata["directional_area_feedback_tuned"]
        )
        self.assertEqual(
            coordinated_metadata["directional_area_feedback_modes"],
            ["max", "mean", "h", "v"],
        )
        area_contracts = {
            "route_inflation": (
                "ruplace_local_inflate_max_rounds",
                ("ruplace_global_inflate_gamma", "ruplace_local_inflate_gamma"),
            ),
            "momentum_inflation": (
                "ruplace_momentum_rounds", ("ruplace_momentum_step",),
            ),
            "path_inflation": (
                "ruplace_path_inflate_rounds",
                ("ruplace_path_inflate_gamma",),
            ),
            "pin_porosity": (
                "ruplace_pin_porosity_rounds",
                ("ruplace_pin_porosity_gamma", "ruplace_porosity_weight"),
            ),
        }
        for plugin, (rounds_key, strength_keys) in area_contracts.items():
            rows = [
                row for row in coordinated.values()
                if row["plugins"] == [plugin]
            ]
            self.assertEqual(len(rows), 16)
            for row in rows:
                updates = row["updates"]
                self.assertEqual(row["proposal_policy_version"], 7)
                self.assertEqual(
                    updates["ruplace_enforce_area_adjust_budget"], 1
                )
                self.assertGreater(
                    updates["ruplace_inflate_area_cap"], 1e-4
                )
                if plugin == "route_inflation":
                    self.assertEqual(
                        updates[rounds_key] + 1,
                        updates["max_num_area_adjust"],
                    )
                else:
                    self.assertEqual(
                        updates[rounds_key], updates["max_num_area_adjust"]
                    )
                self.assertIn("ruplace_inflate_start_overflow", updates)
                self.assertTrue(any(key in updates for key in strength_keys))
        route_rows = [
            row for row in coordinated.values()
            if row["plugins"] == ["route_inflation"]
        ]
        directional_rows = [
            row for row in route_rows
            if "ruplace_hv_inflate_mode" in row["updates"]
        ]
        self.assertEqual({
            row["updates"]["ruplace_hv_inflate_mode"]
            for row in directional_rows
        }, {"max", "mean", "h", "v"})
        self.assertTrue(all(
            row["updates"]["ruplace_hv_inflate_gamma"] > 0.0
            for row in directional_rows
        ))

    def test_cli_writes_manifest_with_evidence_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis.json"
            presets = root / "presets.json"
            manifest = root / "manifest.json"
            output = root / "adaptive.json"
            analysis.write_text(json.dumps(ANALYSIS))
            presets.write_text(json.dumps(PRESETS))
            manifest.write_text(json.dumps(MANIFEST))

            status = main([
                "--analysis", str(analysis),
                "--presets", str(presets),
                "--preset-manifest", str(manifest),
                "--output", str(output),
                "--max-parents", "2",
                "--max-variants-per-parent", "4",
            ])
            provenance = json.loads(
                output.with_suffix(".json.manifest.json").read_text()
            )

            coordinated_output = root / "adaptive_v7.json"
            coordinated_status = main([
                "--analysis", str(analysis),
                "--presets", str(presets),
                "--preset-manifest", str(manifest),
                "--output", str(coordinated_output),
                "--max-parents", "2",
                "--max-variants-per-parent", "4",
                "--proposal-policy-version", "7",
            ])
            coordinated_provenance = json.loads(
                coordinated_output.with_suffix(".json.manifest.json").read_text()
            )

        self.assertEqual(status, 0)
        self.assertFalse(
            provenance["metadata"]["heldout_or_golden_evidence_used"]
        )
        self.assertEqual(provenance["metadata"]["proposal_policy_version"], 6)
        self.assertEqual(provenance["metadata"]["generated_count"], 8)
        self.assertEqual(coordinated_status, 0)
        self.assertEqual(
            coordinated_provenance["metadata"]["proposal_policy_version"], 7
        )


if __name__ == "__main__":
    unittest.main()
