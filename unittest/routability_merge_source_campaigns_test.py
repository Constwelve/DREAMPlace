#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest

from tools.routability_merge_source_campaigns import (
    audit_method_campaign_activation,
    merge_campaigns,
    union_method_campaigns,
)


def make_campaign(root, case, seed, status="completed"):
    methods = root / case / ("seed_%d" % seed) / case / "methods"
    methods.mkdir(parents=True)
    for method in ("hpwl", "plugin", "rejected"):
        directory = methods / method
        directory.mkdir()
        (directory / "config.json").write_text(json.dumps({"method": method}))
    comparison = methods / "comparison.json"
    comparison.write_text(json.dumps({
        "validation": {"status": "validated"},
        "placements": [
            {"method": "hpwl", "status": "ok"},
            {"method": "plugin", "status": "ok"},
            {"method": "rejected", "status": "ok"},
        ],
        "results": [
            {"method": "hpwl", "backend": "gpugr"},
            {"method": "plugin", "backend": "gpugr"},
            {"method": "rejected", "backend": "gpugr"},
        ],
    }))
    (root / "parallel_status.json").write_text(json.dumps({
        "jobs": [{
            "case": case,
            "seed": seed,
            "status": status,
            "returncode": 0 if status == "completed" else "",
        }]
    }))
    return comparison


def make_union_bundle(root, label, case_seeds, methods):
    campaign = root / label / "campaign"
    presets = {"hpwl": {
        "detailed_place_flag": 0,
        "routability_opt_flag": 0,
        "ruplace_flag": 0,
    }}
    generated = {}
    for method, (plugin, proxy) in methods.items():
        presets[method] = {
            "ruplace_flag": 1,
            "ruplace_plugins": plugin,
            "ruplace_proxy": proxy,
        }
        generated[method] = {"plugins": [plugin], "proxy": proxy}
    jobs = []
    for case, seed in case_seeds:
        methods_dir = campaign / case / ("seed_%d" % seed) / case / "methods"
        placements = []
        for method, preset in presets.items():
            method_dir = methods_dir / method
            placement_dir = method_dir / "placement" / "input"
            placement_dir.mkdir(parents=True)
            config = {
                "def_input": "/bench/input.def",
                "random_seed": seed,
                "result_dir": str(method_dir / "placement"),
                "route_num_bins_x": 256,
                "route_num_bins_y": 256,
                **preset,
            }
            (method_dir / "config.json").write_text(json.dumps(config))
            (placement_dir / "input.gp.def").write_text(
                "VERSION 5.8 ;\nDESIGN input ;\n# %s %d\nEND DESIGN\n"
                % (case, seed)
            )
            if method == "hpwl":
                placements.append({
                    "method": method,
                    "status": "ok",
                    "runtime_sec": 1.0 if label == "left" else 2.0,
                    "routability_plugin_selected": "",
                    "routability_plugin_status": "not_selected",
                    "routability_plugin_summary": {"plugins": {}},
                })
            else:
                plugin = methods[method][0]
                placements.append({
                    "method": method,
                    "status": "ok",
                    "routability_plugin_selected": plugin,
                    "routability_plugin_status": "active",
                    "routability_plugin_summary": {"plugins": {
                        plugin: {"status": "active", "activations": 3},
                    }},
                })
        comparison = methods_dir / "comparison.json"
        comparison.write_text(json.dumps({
            "validation": {"status": "validated"},
            "placements": placements,
            "results": [{
                "method": method,
                "backend": "rudy",
                "status": "ok",
                "metrics": {"legacy": 1},
            } for method in presets],
        }))
        jobs.append({
            "case": case,
            "seed": seed,
            "status": "completed",
            "returncode": 0,
        })
    (campaign / "parallel_status.json").write_text(json.dumps({"jobs": jobs}))
    preset_path = root / label / "presets.json"
    preset_path.write_text(json.dumps(presets))
    manifest_path = root / label / "presets.json.manifest.json"
    manifest_path.write_text(json.dumps({"generated": generated}))
    return campaign, preset_path, manifest_path


class RoutabilityMergeSourceCampaignsTest(unittest.TestCase):
    @staticmethod
    def mark_inactive(comparison, method, reason="zero_congestion_field"):
        data = json.loads(comparison.read_text())
        placement = next(
            row for row in data["placements"] if row["method"] == method
        )
        plugin = placement["routability_plugin_selected"]
        stats = placement["routability_plugin_summary"]["plugins"][plugin]
        stats.update({
            "status": "attempted_no_change",
            "attempts": 12,
            "activations": 0,
            "gradient_attempts": 12,
            "gradient_activations": 0,
            "metric_stats": {
                "force_schedule_applied": {
                    "count": 3, "nonzero_count": 3, "min": 1.0,
                    "max": 1.0, "mean": 1.0, "last": 1.0,
                },
                "field_norm": {
                    "count": 3, "nonzero_count": 0, "min": 0.0,
                    "max": 0.0, "mean": 0.0, "last": 0.0,
                },
            },
        })
        placement.update({
            "routability_plugin_status": "selected_no_activation",
            "routability_plugin_attempts": 12,
            "routability_plugin_activations": 0,
            "density_overflow": 0.42,
        })
        comparison.write_text(json.dumps(data))

    def test_merges_complete_campaigns_with_provenance_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            output = root / "merged"
            left_comparison = make_campaign(left, "case_a", 1000)
            right_comparison = make_campaign(right, "case_b", 2000)

            manifest = merge_campaigns([left, right], output)

            left_link = (
                output / "case_a" / "seed_1000" / "case_a" / "methods"
                / "comparison.json"
            )
            right_method = (
                output / "case_b" / "seed_2000" / "case_b" / "methods"
                / "plugin"
            )
            status = json.loads((output / "parallel_status.json").read_text())
            self.assertEqual(manifest["comparison_count"], 2)
            self.assertTrue(left_link.is_symlink())
            self.assertEqual(left_link.resolve(), left_comparison.resolve())
            self.assertTrue(right_method.is_symlink())
            self.assertEqual(
                right_method.resolve(),
                right_comparison.parent.joinpath("plugin").resolve(),
            )
            self.assertEqual(
                {row["status"] for row in status["jobs"]}, {"completed"}
            )

    def test_merge_is_idempotent_for_unchanged_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            output = root / "merged"
            make_campaign(source, "case_a", 1000)

            first = merge_campaigns([source], output)
            second = merge_campaigns([source], output)

        self.assertEqual(first["entries"], second["entries"])

    def test_exports_only_selected_methods_with_filtered_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            output = root / "merged"
            make_campaign(source, "case_a", 1000)

            manifest = merge_campaigns(
                [source], output, methods=["hpwl", "plugin"]
            )
            methods = output / "case_a" / "seed_1000" / "case_a" / "methods"
            comparison = methods / "comparison.json"
            data = json.loads(comparison.read_text())

            self.assertFalse(comparison.is_symlink())
            self.assertTrue((methods / "hpwl").is_symlink())
            self.assertTrue((methods / "plugin").is_symlink())
            self.assertFalse((methods / "rejected").exists())
            self.assertEqual(
                [row["method"] for row in data["placements"]],
                ["hpwl", "plugin"],
            )
            self.assertEqual(
                {row["method"] for row in data["results"]},
                {"hpwl", "plugin"},
            )
            self.assertEqual(
                manifest["merge_mode"],
                "filtered_comparison_with_method_symlinks",
            )
            self.assertEqual(manifest["selected_methods"], ["hpwl", "plugin"])

    def test_rejects_duplicate_case_seed_across_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            make_campaign(left, "case_a", 1000)
            make_campaign(right, "case_a", 1000)

            with self.assertRaisesRegex(ValueError, "duplicate case/seed"):
                merge_campaigns([left, right], root / "merged")

    def test_rejects_incomplete_source_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            make_campaign(source, "case_a", 1000, status="running")

            with self.assertRaisesRegex(ValueError, "incomplete"):
                merge_campaigns([source], root / "merged")

    def test_strict_method_union_freezes_all_plugin_methods_without_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_seeds = [("case_a", 1000), ("case_b", 2000)]
            left = make_union_bundle(root, "left", case_seeds, {
                "scheduled_local": ("local_gradient", "rudy"),
                "scheduled_overlap": ("net_overlap", "rudy"),
                "scheduled_weight": ("net_weighting", "rudy"),
                "scheduled_poisson": ("poisson_force", "rudy"),
                "scheduled_space": ("whitespace", "rudy"),
            })
            right = make_union_bundle(root, "right", case_seeds, {
                "adaptive_local": ("local_gradient", "gpugr"),
                "adaptive_overlap": ("net_overlap", "gpugr"),
                "adaptive_weight": ("net_weighting", "gpugr"),
                "adaptive_poisson": ("poisson_force", "gpugr"),
                "adaptive_space": ("whitespace", "gpugr"),
            })
            output = root / "union" / "campaign"
            output_presets = root / "union" / "presets.json"

            manifest = union_method_campaigns(
                [left[0], right[0]],
                [left[1], right[1]],
                [left[2], right[2]],
                output,
                output_presets,
                case_seeds,
                expected_method_count=11,
            )
            comparison = json.loads(next(output.rglob("comparison.json")).read_text())
            preset_manifest = json.loads(
                output_presets.with_suffix(".json.manifest.json").read_text()
            )
            methods_dir = (
                output / "case_a" / "seed_1000" / "case_a" / "methods"
            )

            self.assertEqual(manifest["method_count"], 11)
            self.assertEqual(manifest["comparison_count"], 2)
            self.assertEqual(set(manifest["plugin_proxy_coverage"]), {
                "local_gradient", "net_overlap", "net_weighting",
                "poisson_force", "whitespace",
            })
            self.assertEqual(
                manifest["plugin_proxy_coverage"]["local_gradient"],
                ["gpugr", "rudy"],
            )
            self.assertFalse(manifest["legacy_proxy_results_imported"])
            self.assertEqual(comparison["results"], [])
            self.assertEqual(len(comparison["placements"]), 11)
            self.assertFalse((methods_dir / "scheduled_weight").is_symlink())
            self.assertTrue((
                methods_dir / "scheduled_weight" / "placement" / "input"
                / "input.gp.def"
            ).is_file())
            self.assertEqual(
                set(preset_manifest["generated"]),
                set(json.loads(output_presets.read_text())) - {"hpwl"},
            )
            self.assertFalse(preset_manifest["numeric_backend_mixing"])

            repeated = union_method_campaigns(
                [left[0], right[0]], [left[1], right[1]], [left[2], right[2]],
                output, output_presets, case_seeds, expected_method_count=11,
            )
            self.assertEqual(manifest, repeated)

    def test_strict_method_union_requires_both_proxies_for_each_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(root, "left", scope, {
                "left_local": ("local_gradient", "rudy"),
                "left_overlap": ("net_overlap", "rudy"),
            })
            right = make_union_bundle(root, "right", scope, {
                "right_local": ("local_gradient", "gpugr"),
            })
            with self.assertRaisesRegex(
                ValueError, "lacks per-plugin proxy provenance"
            ):
                union_method_campaigns(
                    [left[0], right[0]], [left[1], right[1]],
                    [left[2], right[2]], root / "out", root / "presets.json",
                    scope, required_plugins=("local_gradient", "net_overlap"),
                )

    def test_strict_method_union_rejects_missing_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000), ("case_b", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope[:1], {"right_local": ("local_gradient", "gpugr")}
            )
            with self.assertRaisesRegex(ValueError, "case/seed scope"):
                union_method_campaigns(
                    [left[0], right[0]], [left[1], right[1]],
                    [left[2], right[2]], root / "out", root / "presets.json",
                    scope, required_plugins=("local_gradient",),
                )

    def test_strict_method_union_rejects_method_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"duplicate": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope, {"duplicate": ("local_gradient", "gpugr")}
            )
            with self.assertRaisesRegex(ValueError, "method collision"):
                union_method_campaigns(
                    [left[0], right[0]], [left[1], right[1]],
                    [left[2], right[2]], root / "out", root / "presets.json",
                    scope, required_plugins=("local_gradient",),
                )

    def test_strict_method_union_rejects_hpwl_config_or_def_mismatch(self):
        for mismatch in ("config", "def"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                scope = [("case_a", 1000)]
                left = make_union_bundle(
                    root, "left", scope, {"left_local": ("local_gradient", "rudy")}
                )
                right = make_union_bundle(
                    root, "right", scope, {"right_local": ("local_gradient", "gpugr")}
                )
                hpwl = (
                    right[0] / "case_a" / "seed_1000" / "case_a" / "methods"
                    / "hpwl"
                )
                if mismatch == "config":
                    config = json.loads((hpwl / "config.json").read_text())
                    config["random_seed"] = 999
                    (hpwl / "config.json").write_text(json.dumps(config))
                else:
                    (hpwl / "placement" / "input" / "input.gp.def").write_text(
                        "DESIGN changed ;\nEND DESIGN\n"
                    )

    def test_strict_method_union_accepts_evaluator_only_hpwl_grid_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope, {"right_local": ("local_gradient", "gpugr")}
            )
            hpwl = (
                right[0] / "case_a" / "seed_1000" / "case_a" / "methods"
                / "hpwl" / "config.json"
            )
            config = json.loads(hpwl.read_text())
            config.update({
                "routability_eval_route_x_size": 256,
                "routability_eval_route_y_size": 256,
            })
            hpwl.write_text(json.dumps(config))

            output = root / "out"
            union_method_campaigns(
                [left[0], right[0]], [left[1], right[1]],
                [left[2], right[2]], output, root / "presets.json", scope,
                required_plugins=("local_gradient",),
            )
            identity = json.loads(
                next(output.rglob("comparison.json")).read_text()
            )["source_union"]["baseline_identity"]
            self.assertEqual(identity["normalized_evaluator_grid_fields"], [
                "routability_eval_route_x_size",
                "routability_eval_route_y_size",
            ])

    def test_strict_method_union_accepts_zero_counter_schema_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope, {"right_local": ("local_gradient", "gpugr")}
            )
            comparison = next(right[0].rglob("comparison.json"))
            data = json.loads(comparison.read_text())
            baseline = next(
                row for row in data["placements"] if row["method"] == "hpwl"
            )
            baseline["routability_plugin_summary"]["pipeline"] = {
                "area_calls": 0,
                "area_gate_skips": 0,
                "gradient_calls": 0,
                "gradient_gate_skips": 0,
                "objective_calls": 0,
                "objective_gate_skips": 0,
            }
            comparison.write_text(json.dumps(data))

            output = root / "out"
            union_method_campaigns(
                [left[0], right[0]], [left[1], right[1]],
                [left[2], right[2]], output, root / "presets.json", scope,
                required_plugins=("local_gradient",),
            )
            identity = json.loads(
                next(output.rglob("comparison.json")).read_text()
            )["source_union"]["baseline_identity"]
            self.assertIn("objective_calls", identity["normalized_pipeline_counters"])

    def test_strict_method_union_rejects_nonzero_baseline_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope, {"right_local": ("local_gradient", "gpugr")}
            )
            comparison = next(right[0].rglob("comparison.json"))
            data = json.loads(comparison.read_text())
            baseline = next(
                row for row in data["placements"] if row["method"] == "hpwl"
            )
            baseline["routability_plugin_summary"]["pipeline"] = {
                "objective_calls": 1,
            }
            comparison.write_text(json.dumps(data))

            with self.assertRaisesRegex(ValueError, "nonzero or unknown"):
                union_method_campaigns(
                    [left[0], right[0]], [left[1], right[1]],
                    [left[2], right[2]], root / "out",
                    root / "presets.json", scope,
                    required_plugins=("local_gradient",),
                )

    def test_strict_method_union_rejects_mismatched_evaluator_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope, {"right_local": ("local_gradient", "gpugr")}
            )
            hpwl = (
                right[0] / "case_a" / "seed_1000" / "case_a" / "methods"
                / "hpwl" / "config.json"
            )
            config = json.loads(hpwl.read_text())
            config["routability_eval_route_x_size"] = 128
            hpwl.write_text(json.dumps(config))

            with self.assertRaisesRegex(ValueError, "evaluator grid differs"):
                union_method_campaigns(
                    [left[0], right[0]], [left[1], right[1]],
                    [left[2], right[2]], root / "out",
                    root / "presets.json", scope,
                    required_plugins=("local_gradient",),
                )
                with self.assertRaisesRegex(ValueError, "hpwl .* differ"):
                    union_method_campaigns(
                        [left[0], right[0]], [left[1], right[1]],
                        [left[2], right[2]], root / "out", root / "presets.json",
                        scope, required_plugins=("local_gradient",),
                    )

    def test_strict_method_union_rejects_inactive_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope, {"right_local": ("local_gradient", "gpugr")}
            )
            comparison = next(right[0].rglob("comparison.json"))
            data = json.loads(comparison.read_text())
            plugin = next(row for row in data["placements"] if row["method"] != "hpwl")
            plugin["routability_plugin_summary"]["plugins"]["local_gradient"][
                "activations"
            ] = 0
            comparison.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "inactive plugin placement"):
                union_method_campaigns(
                    [left[0], right[0]], [left[1], right[1]],
                    [left[2], right[2]], root / "out", root / "presets.json",
                    scope, required_plugins=("local_gradient",),
                )

    def test_activation_audit_reports_every_inactive_case_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000), ("case_b", 2000)]
            campaign, _, _ = make_union_bundle(
                root, "source", scope,
                {"local": ("local_gradient", "gpugr")},
            )
            comparisons = sorted(campaign.rglob("comparison.json"))
            self.mark_inactive(comparisons[0], "local")
            self.mark_inactive(comparisons[1], "local")

            audit = audit_method_campaign_activation(campaign, scope)

            self.assertEqual(audit["status"], "inactive_methods")
            self.assertEqual(audit["inactive_method_count"], 1)
            self.assertEqual(audit["inactive_placement_count"], 2)
            self.assertEqual(audit["selected_placement_count"], 2)
            self.assertEqual(
                {row["reason"] for row in audit["inactive_placements"]},
                {"zero_congestion_field"},
            )
            self.assertEqual(
                audit["inactive_methods"][0]["method"], "local"
            )
            self.assertEqual(
                len(audit["inactive_methods"][0]["affected_case_seeds"]), 2
            )

    def test_method_union_can_exclude_and_attest_inactive_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000), ("case_b", 2000)]
            left = make_union_bundle(root, "left", scope, {
                "left_inactive": ("local_gradient", "rudy"),
                "left_active": ("local_gradient", "rudy"),
            })
            right = make_union_bundle(root, "right", scope, {
                "right_active": ("local_gradient", "gpugr"),
            })
            self.mark_inactive(
                sorted(left[0].rglob("comparison.json"))[0], "left_inactive"
            )
            output = root / "union" / "campaign"
            output_presets = root / "union" / "presets.json"
            audit_path = root / "union" / "activation_audit.json"

            manifest = union_method_campaigns(
                [left[0], right[0]], [left[1], right[1]], [left[2], right[2]],
                output, output_presets, scope, expected_method_count=3,
                required_plugins=("local_gradient",),
                exclude_inactive_methods=True,
                activation_audit_output=audit_path,
            )

            presets = json.loads(output_presets.read_text())
            audit = json.loads(audit_path.read_text())
            self.assertEqual(manifest["source_method_count"], 4)
            self.assertEqual(manifest["method_count"], 3)
            self.assertEqual(manifest["excluded_inactive_method_count"], 1)
            self.assertNotIn("left_inactive", presets)
            self.assertEqual(audit["status"], "filtered")
            self.assertEqual(
                audit["excluded_inactive_methods"][0]["method"],
                "left_inactive",
            )
            for comparison in output.rglob("comparison.json"):
                methods = {
                    row["method"]
                    for row in json.loads(comparison.read_text())["placements"]
                }
                self.assertEqual(
                    methods, {"hpwl", "left_active", "right_active"}
                )

    def test_strict_method_union_recovers_objective_activation_from_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope,
                {"right_weight": ("net_weighting", "gpugr")},
            )
            comparison = next(right[0].rglob("comparison.json"))
            data = json.loads(comparison.read_text())
            plugin = next(row for row in data["placements"] if row["method"] != "hpwl")
            plugin.update({
                "routability_plugin_status": "selected_no_activation",
                "routability_plugin_activations": 0,
                "routability_plugin_attempts": 0,
                "routability_plugin_summary": {"plugins": {
                    "net_weighting": {"status": "not_reached", "activations": 0},
                }},
            })
            comparison.write_text(json.dumps(data))
            log_path = comparison.parent / "right_weight" / "placement.log"
            log_path.write_text(
                'INFO ROUTABILITY_PLUGIN_SUMMARY {"pipeline":{'
                '"objective_calls":12,"objective_gate_skips":2,'
                '"gradient_calls":12,"gradient_gate_skips":2,'
                '"area_calls":0,"area_gate_skips":0},"plugins":{'
                '"net_weighting":{"objective_attempts":10,'
                '"objective_activations":3,"gradient_attempts":0,'
                '"gradient_activations":0,"area_attempts":0,'
                '"area_activations":0,"metrics":{"mean_ratio":1.1},'
                '"metric_stats":{}}}}\n'
            )
            output = root / "out"
            union_method_campaigns(
                [left[0], right[0]], [left[1], right[1]], [left[2], right[2]],
                output, root / "presets.json", scope,
                required_plugins=(),
            )
            union = json.loads(next(output.rglob("comparison.json")).read_text())
            recovered = next(
                row for row in union["placements"] if row["method"] == "right_weight"
            )
            provenance = union["source_union"]["method_provenance"]["right_weight"]
            self.assertEqual(recovered["routability_plugin_status"], "active")
            self.assertEqual(recovered["routability_plugin_activations"], 3)
            self.assertEqual(provenance["activation_evidence_source"], "placement_log")
            self.assertTrue(provenance["activation_log_sha256"])

    def test_strict_method_union_rejects_preset_config_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = [("case_a", 1000)]
            left = make_union_bundle(
                root, "left", scope, {"left_local": ("local_gradient", "rudy")}
            )
            right = make_union_bundle(
                root, "right", scope, {"right_local": ("local_gradient", "gpugr")}
            )
            config_path = next(right[0].rglob("right_local/config.json"))
            config = json.loads(config_path.read_text())
            config["ruplace_proxy"] = "rudy"
            config_path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "source config differs from preset"):
                union_method_campaigns(
                    [left[0], right[0]], [left[1], right[1]],
                    [left[2], right[2]], root / "out", root / "presets.json",
                    scope, required_plugins=("local_gradient",),
                )


if __name__ == "__main__":
    unittest.main()
