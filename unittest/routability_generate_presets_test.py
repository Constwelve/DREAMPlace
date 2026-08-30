#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_generate_presets import generate_presets, main
from tools.routability_generate_family_presets import (
    generate_family_presets,
)


BASE = {
    "hpwl": {"ruplace_flag": 0},
    "local_gradient": {"ruplace_plugins": ["local_gradient"]},
    "net_weighting": {"ruplace_plugins": ["net_weighting"]},
    "routeforce": {"ruplace_plugins": ["routeforce"]},
}


class RoutabilityGeneratePresetsTest(unittest.TestCase):
    def test_v108_generates_atomic_aggregate_pnorm_grid(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs/routability_aggregate_pnorm_gradient_pilot_v108.json"
        ).read_text())

        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [
            presets[name] for name in manifest["generated"]
        ]

        self.assertEqual(len(generated), 6)
        self.assertEqual(manifest["required_families"], [
            "aggregate_pnorm_gradient"
        ])
        self.assertFalse(manifest["heldout_or_golden_evidence_used"])
        self.assertFalse(manifest["numeric_backend_mixing"])
        self.assertTrue(all(
            row["ruplace_plugins"] == ["aggregate_pnorm_gradient"]
            and row["ruplace_proxy"] == "gpugr"
            for row in generated
        ))
        self.assertEqual(
            {row["ruplace_aggregate_pnorm_gradient_exponent"]
             for row in generated},
            {1.0, 1.25, 1.5, 2.0, 3.0, 4.0},
        )
        control = generated[0]
        for row in generated[1:]:
            self.assertEqual(
                {key for key in set(control) | set(row)
                 if control.get(key) != row.get(key)},
                {"ruplace_aggregate_pnorm_gradient_exponent"},
            )

    def test_v106_generates_atomic_aggregate_cvar_grid(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs/routability_aggregate_cvar_gradient_pilot_v106.json"
        ).read_text())

        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = {
            metadata["variant"]: presets[name]
            for name, metadata in manifest["generated"].items()
        }

        self.assertEqual(len(generated), 6)
        self.assertEqual(manifest["required_families"], [
            "aggregate_cvar_gradient"
        ])
        self.assertFalse(manifest["heldout_or_golden_evidence_used"])
        self.assertFalse(manifest["numeric_backend_mixing"])
        self.assertTrue(all(
            row["ruplace_plugins"] == ["aggregate_cvar_gradient"]
            and row["ruplace_proxy"] == "gpugr"
            for row in generated.values()
        ))
        self.assertEqual(
            {row["ruplace_aggregate_cvar_gradient_tail_blend"]
             for row in generated.values()},
            {0.0, 0.25, 0.5, 0.75, 1.0},
        )
        self.assertEqual(
            {row["ruplace_aggregate_cvar_gradient_quantile"]
             for row in generated.values()},
            {0.975, 0.99},
        )

    def test_v107_refines_v100_balance0p90625_only(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )

        def generated_by_variant(filename):
            spec = json.loads((ROOT / "configs" / filename).read_text())
            presets, manifest = generate_family_presets(
                base, spec, max_presets=8
            )
            return {
                metadata["variant"]: presets[name]
                for name, metadata in manifest["generated"].items()
            }

        v100 = generated_by_variant(
            "routability_directional_cvar_gradient_per_axis_tail25_balance_pilot_v100.json"
        )
        v107 = generated_by_variant(
            "routability_directional_cvar_gradient_tail25_transition_pilot_v107.json"
        )

        self.assertEqual(len(v107), 6)
        self.assertEqual(
            v107["balance0p90625_control"], v100["balance0p90625"]
        )
        self.assertEqual(
            {row["ruplace_directional_cvar_gradient_axis_balance"]
             for row in v107.values()},
            {0.90625, 0.91015625, 0.9140625, 0.91796875,
             0.921875, 0.92578125},
        )
        control = v107["balance0p90625_control"]
        for name, row in v107.items():
            differing = {
                key for key in set(control) | set(row)
                if control.get(key) != row.get(key)
            }
            self.assertEqual(
                differing,
                set() if name == "balance0p90625_control" else {
                    "ruplace_directional_cvar_gradient_axis_balance"
                },
            )

    def test_v98_control_reproduces_v90_utilization_quarter(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )

        def generated_by_variant(filename):
            spec = json.loads((ROOT / "configs" / filename).read_text())
            presets, manifest = generate_family_presets(
                base, spec, max_presets=8
            )
            return {
                metadata["variant"]: presets[name]
                for name, metadata in manifest["generated"].items()
            }

        v90 = generated_by_variant(
            "routability_directional_local_gradient_matching_utilization_pilot_v90.json"
        )
        v98 = generated_by_variant(
            "routability_directional_local_gradient_utilization_refinement_pilot_v98.json"
        )

        self.assertEqual(len(v98), 6)
        self.assertEqual(
            v98["quarter_unbounded_control"],
            v90["utilization_quarter_balance1"],
        )
        self.assertEqual(
            {row["ruplace_directional_local_gradient_weight"]
             for row in v98.values()},
            {0.000046875, 0.000041015625, 0.00003515625, 0.000029296875},
        )
        self.assertEqual(
            {row.get("ruplace_force_max_applications", -1)
             for row in v98.values()},
            {-1, 8, 10},
        )

    def test_v99_control_reproduces_v95_per_axis_overflow(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )

        def generated_by_variant(filename):
            spec = json.loads((ROOT / "configs" / filename).read_text())
            presets, manifest = generate_family_presets(
                base, spec, max_presets=8
            )
            return {
                metadata["variant"]: presets[name]
                for name, metadata in manifest["generated"].items()
            }

        v95 = generated_by_variant(
            "routability_directional_cvar_gradient_per_axis_pilot_v95.json"
        )
        v99 = generated_by_variant(
            "routability_directional_cvar_gradient_per_axis_balance_pilot_v99.json"
        )

        self.assertEqual(len(v99), 6)
        self.assertEqual(
            v99["balance1_control"], v95["overflow_full_control"]
        )
        self.assertEqual(
            {row["ruplace_directional_cvar_gradient_axis_balance"]
             for row in v99.values()},
            {1.0, 0.984375, 0.96875, 0.9375, 0.90625, 0.875},
        )
        self.assertTrue(all(
            row["ruplace_directional_cvar_gradient_normalization"]
            == "per_axis"
            and row["ruplace_directional_cvar_gradient_tail_blend"] == 0.0
            and row["ruplace_force_max_applications"] == 8
            for row in v99.values()
        ))

    def test_v100_control_reproduces_v95_per_axis_q99_tail25(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )

        def generated_by_variant(filename):
            spec = json.loads((ROOT / "configs" / filename).read_text())
            presets, manifest = generate_family_presets(
                base, spec, max_presets=8
            )
            return {
                metadata["variant"]: presets[name]
                for name, metadata in manifest["generated"].items()
            }

        v95 = generated_by_variant(
            "routability_directional_cvar_gradient_per_axis_pilot_v95.json"
        )
        v100 = generated_by_variant(
            "routability_directional_cvar_gradient_per_axis_tail25_balance_pilot_v100.json"
        )

        self.assertEqual(len(v100), 6)
        self.assertEqual(
            v100["balance1_control"], v95["q99_tail25_full"]
        )
        self.assertEqual(
            {row["ruplace_directional_cvar_gradient_axis_balance"]
             for row in v100.values()},
            {1.0, 0.9921875, 0.984375, 0.96875, 0.9375, 0.90625},
        )
        self.assertTrue(all(
            row["ruplace_directional_cvar_gradient_normalization"]
            == "per_axis"
            and row["ruplace_directional_cvar_gradient_quantile"] == 0.99
            and row["ruplace_directional_cvar_gradient_tail_blend"] == 0.25
            and row["ruplace_force_max_applications"] == 8
            for row in v100.values()
        ))

    def test_v102_reverses_v97_balance_without_other_changes(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )

        def generated_by_variant(filename):
            spec = json.loads((ROOT / "configs" / filename).read_text())
            presets, manifest = generate_family_presets(
                base, spec, max_presets=8
            )
            return {
                metadata["variant"]: presets[name]
                for name, metadata in manifest["generated"].items()
            }

        v97 = generated_by_variant(
            "routability_directional_cvar_gradient_vertical_balance_pilot_v97.json"
        )
        v102 = generated_by_variant(
            "routability_directional_cvar_gradient_x_bias_pilot_v102.json"
        )

        self.assertEqual(len(v102), 6)
        self.assertEqual(v102["balance1_control"], v97["balance1_control"])
        self.assertEqual(
            {row["ruplace_directional_cvar_gradient_axis_balance"]
             for row in v102.values()},
            {1.0, 1.015625, 1.03125, 1.0625, 1.09375, 1.125},
        )
        control = v102["balance1_control"]
        for name, row in v102.items():
            differing = {
                key for key in set(control) | set(row)
                if control.get(key) != row.get(key)
            }
            if name == "balance1_control":
                self.assertEqual(differing, set())
            else:
                self.assertEqual(
                    differing,
                    {"ruplace_directional_cvar_gradient_axis_balance"},
                )

    def test_v103_interpolates_v97_balance_transition_only(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )

        def generated_by_variant(filename):
            spec = json.loads((ROOT / "configs" / filename).read_text())
            presets, manifest = generate_family_presets(
                base, spec, max_presets=8
            )
            return {
                metadata["variant"]: presets[name]
                for name, metadata in manifest["generated"].items()
            }

        v97 = generated_by_variant(
            "routability_directional_cvar_gradient_vertical_balance_pilot_v97.json"
        )
        v103 = generated_by_variant(
            "routability_directional_cvar_gradient_balance_transition_pilot_v103.json"
        )

        self.assertEqual(len(v103), 6)
        self.assertEqual(
            v103["balance0p75_control"], v97["balance0p75"]
        )
        self.assertEqual(
            {row["ruplace_directional_cvar_gradient_axis_balance"]
             for row in v103.values()},
            {0.75, 0.74609375, 0.7421875, 0.73828125,
             0.734375, 0.73046875},
        )
        control = v103["balance0p75_control"]
        for name, row in v103.items():
            differing = {
                key for key in set(control) | set(row)
                if control.get(key) != row.get(key)
            }
            if name == "balance0p75_control":
                self.assertEqual(differing, set())
            else:
                self.assertEqual(
                    differing,
                    {"ruplace_directional_cvar_gradient_axis_balance"},
                )

    def test_v101_changes_only_v96_stagnation_to_severity_gate(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )

        def generated_by_variant(filename):
            spec = json.loads((ROOT / "configs" / filename).read_text())
            presets, manifest = generate_family_presets(
                base, spec, max_presets=8
            )
            return {
                metadata["variant"]: presets[name]
                for name, metadata in manifest["generated"].items()
            }

        v96 = generated_by_variant(
            "routability_directional_excess_cvar_gradient_pilot_v96.json"
        )
        v101 = generated_by_variant(
            "routability_directional_excess_cvar_gradient_severity_pilot_v101.json"
        )

        self.assertEqual(set(v101), set(v96))
        for variant, row in v101.items():
            expected = dict(v96[variant])
            self.assertEqual(expected["ruplace_force_stagnation_window"], 3)
            expected["ruplace_force_stagnation_window"] = 1
            self.assertEqual(row, expected)
        self.assertTrue(all(
            row["ruplace_force_min_overflow_sum"] == 10.0
            and row["ruplace_force_min_overflow_bins"] == 1
            and row["ruplace_force_max_applications"] == 8
            for row in v101.values()
        ))

    def test_directional_local_gradient_v93_guards_monotonic_tails(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_monotonic_tail_guard_pilot_v93.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertEqual(
            {row["ruplace_directional_local_gradient_tail_metric"]
             for row in generated},
            {"max", "p99", "max_p99"},
        )
        self.assertEqual(
            {row["ruplace_directional_local_gradient_tail_tolerance"]
             for row in generated},
            {0.0, 0.0025},
        )
        self.assertTrue(all(
            row["ruplace_directional_local_gradient_tail_guard"] == 1
            and row["ruplace_directional_local_gradient_axis_mapping"]
            == "cross_track"
            and row["ruplace_directional_local_gradient_normalization"]
            == "joint"
            and row["ruplace_directional_local_gradient_axis_balance"] == 1.75
            and row["ruplace_directional_local_gradient_weight"] == 0.000046875
            and row["ruplace_proxy"] == "gpugr"
            for row in generated
        ))

    def test_directional_local_gradient_v92_targets_per_axis_tails(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_per_axis_tail_control_pilot_v92.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertEqual(
            {row["ruplace_directional_local_gradient_smooth"]
             for row in generated},
            {1, 2, 4, 8},
        )
        self.assertEqual(
            {row.get("ruplace_force_max_applications", -1)
             for row in generated},
            {-1, 6, 8},
        )
        self.assertTrue(all(
            row["ruplace_directional_local_gradient_axis_mapping"]
            == "cross_track"
            and row["ruplace_directional_local_gradient_normalization"]
            == "per_axis"
            and row["ruplace_directional_local_gradient_axis_balance"] == 1.5
            and row["ruplace_directional_local_gradient_weight"] == 0.00009375
            and row["ruplace_directional_local_gradient_polarity"] == "repel"
            and row["ruplace_proxy"] == "gpugr"
            for row in generated
        ))

    def test_directional_local_gradient_v91_targets_cross_axis_tails(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_cross_tail_control_pilot_v91.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertEqual(
            {row["ruplace_directional_local_gradient_smooth"]
             for row in generated},
            {1, 2, 4, 8},
        )
        self.assertEqual(
            {row.get("ruplace_force_max_applications", -1)
             for row in generated},
            {-1, 6, 8},
        )
        self.assertTrue(all(
            row["ruplace_directional_local_gradient_axis_mapping"]
            == "cross_track"
            and row["ruplace_directional_local_gradient_axis_balance"] == 1.75
            and row["ruplace_directional_local_gradient_weight"] == 0.000046875
            and row["ruplace_directional_local_gradient_polarity"] == "repel"
            and row["ruplace_proxy"] == "gpugr"
            for row in generated
        ))

    def test_directional_local_gradient_v89_matches_axis_and_normalization(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_matching_normalization_pilot_v89.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertEqual(sum(
            row["ruplace_directional_local_gradient_normalization"] == "joint"
            for row in generated
        ), 1)
        self.assertEqual(
            {row["ruplace_directional_local_gradient_axis_balance"]
             for row in generated},
            {0.75, 0.875, 1.0},
        )
        self.assertEqual(
            {row["ruplace_directional_local_gradient_weight"]
             for row in generated},
            {0.0001875, 0.00009375, 0.000046875},
        )
        self.assertTrue(all(
            row["ruplace_directional_local_gradient_axis_mapping"]
            == "matching_axis"
            and row["ruplace_directional_local_gradient_polarity"] == "repel"
            and row["ruplace_proxy"] == "gpugr"
            and row["ruplace_force_stagnation_window"] == 3
            for row in generated
        ))

    def test_directional_local_gradient_v86_normalizes_axes_independently(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_axis_normalization_pilot_v86.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertEqual(sum(
            row["ruplace_directional_local_gradient_normalization"] == "joint"
            for row in generated
        ), 1)
        self.assertEqual(
            {row["ruplace_directional_local_gradient_axis_balance"]
             for row in generated},
            {0.75, 1.0, 1.25, 1.5},
        )
        self.assertEqual(
            {row["ruplace_directional_local_gradient_weight"]
             for row in generated},
            {0.00009375, 0.000046875},
        )
        self.assertTrue(all(
            row["ruplace_directional_local_gradient_axis_mapping"]
            == "cross_track"
            and row["ruplace_directional_local_gradient_polarity"] == "repel"
            and row["ruplace_proxy"] == "gpugr"
            for row in generated
        ))

    def test_directional_local_gradient_v85_targets_half_strength_crossover(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_half_strength_pilot_v85.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertEqual(
            {row["ruplace_directional_local_gradient_axis_balance"]
             for row in generated},
            {1.25, 1.5, 1.75, 2.0},
        )
        self.assertEqual(
            {row["ruplace_directional_local_gradient_weight"]
             for row in generated},
            {0.00009375, 0.000046875},
        )
        self.assertTrue(all(
            row["ruplace_directional_local_gradient_axis_mapping"]
            == "cross_track"
            and row["ruplace_directional_local_gradient_polarity"] == "repel"
            and row["ruplace_proxy"] == "gpugr"
            and row["ruplace_force_stagnation_window"] == 3
            for row in generated
        ))

    def test_directional_local_gradient_v84_is_bounded_ablation(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_mapping_pilot_v84.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertEqual(
            {row["ruplace_directional_local_gradient_axis_mapping"]
             for row in generated},
            {"cross_track", "matching_axis"},
        )
        self.assertEqual(
            {row["ruplace_directional_local_gradient_polarity"]
             for row in generated},
            {"repel", "attract"},
        )
        self.assertEqual(sum(
            row["ruplace_directional_local_gradient_axis_mapping"]
            == "cross_track" for row in generated
        ), 1)
        self.assertTrue(all(
            row["ruplace_proxy"] == "gpugr"
            and row["ruplace_force_stagnation_window"] == 3
            and row["ruplace_force_min_overflow_sum"] == 10.0
            for row in generated
        ))

    def test_directional_local_gradient_v82_is_bounded(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs"
            / "routability_directional_local_gradient_stagnation_pilot_v82.json"
        ).read_text())
        presets, manifest = generate_family_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest["generated"]]

        self.assertEqual(len(generated), 6)
        self.assertTrue(all(
            row["ruplace_plugins"] == ["directional_local_gradient"]
            and row["ruplace_proxy"] == "gpugr"
            and row["ruplace_force_stagnation_window"] == 3
            and row["ruplace_force_min_overflow_sum"] == 10.0
            for row in generated
        ))
        self.assertEqual(
            {row["ruplace_directional_local_gradient_axis_balance"]
             for row in generated},
            {1.0, 1.25, 1.5, 2.0},
        )
        self.assertEqual(
            {row["ruplace_directional_local_gradient_feedback"]
             for row in generated},
            {"overflow", "utilization"},
        )

    def test_directional_path_spreading_start_grid_contains_v64_control(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs"
            / "routability_directional_path_spreading_start_pilot_v67.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=5)
        generated = [presets[name] for name in manifest]
        self.assertEqual(len(generated), 5)
        self.assertEqual(
            {row["ruplace_plugin_start_overflow"] for row in generated},
            {0.2, 0.3, 0.4, 0.5, 0.6},
        )
        controls = [
            row for row in generated
            if row["ruplace_plugin_start_overflow"] == 0.4
        ]
        self.assertEqual(len(controls), 1)
        self.assertTrue(all(
            row["ruplace_directional_path_spreading_apply_interval"] == 20
            and row["ruplace_directional_path_spreading_decay"] == 0.8
            and row["ruplace_directional_path_spreading_threshold"] == 0.6
            and row["ruplace_directional_path_spreading_weight"] == 0.0009375
            and row["ruplace_proxy_refresh_interval"] == 20
            for row in generated
        ))

    def test_directional_path_spreading_lifecycle_grid_contains_v64_control(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs"
            / "routability_directional_path_spreading_lifecycle_pilot_v66.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=27)
        generated = [presets[name] for name in manifest]
        self.assertEqual(len(generated), 27)
        self.assertEqual(
            {row["ruplace_proxy_refresh_interval"] for row in generated},
            {10, 20, 40},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_apply_interval"]
             for row in generated},
            {10, 20, 40},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_decay"]
             for row in generated},
            {0.5, 0.8, 1.0},
        )
        controls = [
            row for row in generated
            if row["ruplace_proxy_refresh_interval"] == 20
            and row["ruplace_directional_path_spreading_apply_interval"] == 20
            and row["ruplace_directional_path_spreading_decay"] == 0.8
        ]
        self.assertEqual(len(controls), 1)
        self.assertTrue(all(
            row["ruplace_directional_path_spreading_mode"] == "both"
            and row["ruplace_directional_path_spreading_threshold"] == 0.6
            and row["ruplace_directional_path_spreading_weight"] == 0.0009375
            for row in generated
        ))

    def test_directional_path_spreading_fine_grid_contains_v64_control(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs"
            / "routability_directional_path_spreading_fine_pilot_v65.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=25)
        generated = [presets[name] for name in manifest]
        self.assertEqual(len(generated), 25)
        self.assertEqual(
            {row["ruplace_directional_path_spreading_threshold"]
             for row in generated},
            {0.5, 0.55, 0.6, 0.65, 0.7},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_weight"]
             for row in generated},
            {0.00075, 0.000875, 0.0009375, 0.001, 0.001125},
        )
        controls = [
            row for row in generated
            if row["ruplace_directional_path_spreading_threshold"] == 0.6
            and row["ruplace_directional_path_spreading_weight"] == 0.0009375
        ]
        self.assertEqual(len(controls), 1)
        self.assertTrue(all(
            row["ruplace_directional_path_spreading_mode"] == "both"
            and row["ruplace_directional_path_spreading_smooth"] == 2
            and row["ruplace_plugin_start_overflow"] == 0.4
            for row in generated
        ))

    def test_directional_path_spreading_axis_grid_is_bounded(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs"
            / "routability_directional_path_spreading_axis_pilot_v64.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=18)
        generated = [presets[name] for name in manifest]
        self.assertEqual(len(generated), 18)
        self.assertEqual(
            {row["ruplace_directional_path_spreading_mode"]
             for row in generated},
            {"both", "horizontal", "vertical"},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_threshold"]
             for row in generated},
            {0.4, 0.6, 0.8},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_weight"]
             for row in generated},
            {0.0003125, 0.0009375},
        )
        self.assertTrue(all(
            row["ruplace_directional_path_spreading_smooth"] == 2
            and row["ruplace_directional_path_spreading_power"] == 2.0
            and row["ruplace_plugin_start_overflow"] == 0.4
            for row in generated
        ))

    def test_directional_net_contraction_boundary_grid_is_bounded(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs"
            / "routability_directional_net_contraction_boundary_pilot_v63.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=8)
        generated = [presets[name] for name in manifest]
        self.assertEqual(len(generated), 8)
        self.assertEqual(
            {row["ruplace_directional_net_contraction_weight"]
             for row in generated},
            {0.001875, 0.00195, 0.00205, 0.00215,
             0.00225, 0.00235, 0.00245, 0.0025},
        )
        self.assertTrue(all(
            row["ruplace_directional_net_contraction_mode"] == "vertical"
            and row["ruplace_directional_net_contraction_normalization"]
            == "design_mean"
            and row["ruplace_directional_net_contraction_smooth"] == 1
            and row["ruplace_plugin_start_overflow"] == 0.4
            for row in generated
        ))

    def test_directional_net_contraction_weak_grid_repeats_v60_control(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs"
            / "routability_directional_net_contraction_weak_pilot_v62.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=6)
        generated = [presets[name] for name in manifest]
        self.assertEqual(len(generated), 6)
        self.assertEqual(
            {row["ruplace_directional_net_contraction_weight"]
             for row in generated},
            {0.00015625, 0.0003125, 0.000625, 0.00125, 0.001875, 0.0025},
        )
        self.assertTrue(all(
            row["ruplace_directional_net_contraction_mode"] == "vertical"
            and row["ruplace_directional_net_contraction_normalization"]
            == "design_mean"
            and row["ruplace_directional_net_contraction_smooth"] == 1
            and row["ruplace_plugin_start_overflow"] == 0.4
            for row in generated
        ))

    def test_directional_net_contraction_axis_mean_grid_is_matched(self):
        spec = json.loads((
            ROOT
            / "configs"
            / "routability_directional_net_contraction_axis_mean_pilot_v61.json"
        ).read_text())
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        presets, manifest = generate_presets(base, spec, max_presets=24)
        generated = [presets[name] for name in manifest]
        self.assertEqual(len(generated), 24)
        self.assertEqual(
            {row["ruplace_directional_net_contraction_normalization"]
             for row in generated},
            {"axis_mean"},
        )
        self.assertEqual(
            {row["ruplace_directional_net_contraction_mode"]
             for row in generated},
            {"max_hv", "vertical"},
        )
        self.assertEqual(
            {row["ruplace_directional_net_contraction_smooth"]
             for row in generated},
            {0, 1},
        )
        self.assertEqual(
            {row["ruplace_directional_net_contraction_weight"]
             for row in generated},
            {0.0025, 0.005, 0.01},
        )
        self.assertEqual(
            {row["ruplace_plugin_start_overflow"] for row in generated},
            {0.3, 0.4},
        )

    def test_net_relaxation_is_a_separately_generatable_plugin(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = {
            "name_prefix": "relax",
            "copy_presets": ["hpwl"],
            "plugins": ["net_relaxation"],
            "combination_sizes": [1],
            "proxies": ["rudy"],
            "plugin_grids": {
                "net_relaxation": {
                    "ruplace_net_relaxation_gamma": [0.1, 0.5],
                },
            },
        }

        presets, manifest = generate_presets(base, spec, max_presets=2)

        self.assertEqual(len(manifest), 2)
        self.assertEqual(set(presets), {"hpwl"} | set(manifest))
        self.assertEqual({
            tuple(row["plugins"]) for row in manifest.values()
        }, {("net_relaxation",)})

    def test_connection_routeforce_strength_pilot_is_bounded_and_causal(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_connection_routeforce_strength_pilot_v2.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=16)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(manifest), 12)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual({row["proxy"] for row in manifest.values()}, {"gpugr"})
        self.assertEqual(
            {row["ruplace_connection_routeforce_field_mode"] for row in configs},
            {"max_hv", "max_layer"},
        )
        self.assertEqual(
            {row["ruplace_connection_routeforce_max_wire_span"] for row in configs},
            {9, 19},
        )
        self.assertEqual(
            {row["ruplace_connection_routeforce_weight"] for row in configs},
            {0.000125, 0.00025, 0.0005},
        )
        self.assertEqual(
            {row["ruplace_connection_routeforce_distance_weighting"] for row in configs},
            {"uniform"},
        )
        self.assertEqual(len({json.dumps(row, sort_keys=True) for row in configs}), 12)

    def test_connection_routeforce_pilot_is_bounded_and_structural(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT / "configs/routability_connection_routeforce_pilot_v1.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=8)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(manifest), 6)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertTrue(all(config["ruplace_external_route_eval"] == 0 for config in configs))
        self.assertEqual(
            {config["ruplace_connection_routeforce_max_wire_span"] for config in configs},
            {19},
        )
        self.assertEqual(
            {
                config["ruplace_connection_routeforce_distance_weighting"]
                for config in configs
            },
            {"uniform", "inverse_sqrt"},
        )
        self.assertEqual(
            {
                config["ruplace_connection_routeforce_field_mode"]
                for config in configs
            },
            {"max_hv", "directional_hv", "max_layer"},
        )

    def test_directional_path_weak_pilot_only_varies_force_weight(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_directional_path_spreading_weak_pilot_v1.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=8)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(manifest), 3)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual({row["proxy"] for row in manifest.values()}, {"gpugr"})
        self.assertEqual(
            {row["ruplace_directional_path_spreading_weight"] for row in configs},
            {0.0003125, 0.000625, 0.0009375},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_threshold"] for row in configs},
            {0.6},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_smooth"] for row in configs},
            {2},
        )

    def test_directional_path_pilot_is_bounded_and_development_only(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_directional_path_spreading_pilot_v1.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=32)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(manifest), 12)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual({row["proxy"] for row in manifest.values()}, {"gpugr"})
        self.assertTrue(all(
            row["ruplace_plugins"] == ["directional_path_spreading"]
            for row in configs
        ))
        self.assertEqual(
            {row["ruplace_directional_path_spreading_smooth"] for row in configs},
            {1, 2},
        )
        self.assertEqual(
            {
                row["ruplace_directional_path_spreading_threshold"]
                for row in configs
            },
            {0.6, 0.8},
        )
        self.assertEqual(
            {row["ruplace_directional_path_spreading_weight"] for row in configs},
            {0.00125, 0.0025, 0.005},
        )

    def test_production_net_weight_lifecycle_grid_has_full_bounded_coverage(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (ROOT / "configs/routability_net_weight_corridor_v2.json").read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=192)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(manifest), 192)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual({row["ruplace_proxy"] for row in configs}, {
            "rudy", "gpugr",
        })
        self.assertEqual({row["ruplace_net_weight_phase"] for row in configs}, {
            "post_gradient", "pre_objective",
        })
        self.assertEqual(
            {row["ruplace_net_weight_normalization"] for row in configs},
            {"absolute", "design_mean"},
        )
        self.assertEqual(
            {row["ruplace_net_weight_gamma"] for row in configs},
            {0.005, 0.025},
        )
        self.assertEqual(
            {row["ruplace_net_weight_freq"] for row in configs}, {10, 40}
        )
        self.assertEqual(
            {row["ruplace_net_weight_score_mode"] for row in configs},
            {"pin_mean", "bbox_mean", "bbox_pmean"},
        )
        self.assertTrue(all(
            row["ruplace_net_weight_bbox_power"] == 4.0 for row in configs
        ))
        self.assertEqual(
            {row["ruplace_plugin_start_overflow"] for row in configs},
            {0.4, 0.8},
        )
        self.assertTrue(all(
            row["ruplace_net_weight_max"] == 1.25 for row in configs
        ))
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 192
        )

    def test_generates_atomic_plugin_specific_grids(self):
        presets, manifest = generate_presets(BASE, {
            "plugins": ["local_gradient", "net_weighting"],
            "combination_sizes": [1],
            "proxies": ["rudy"],
            "grid": {"ruplace_plugin_start_overflow": [0.6, 0.8]},
            "plugin_grids": {
                "local_gradient": {"ruplace_local_gradient_weight": [0.005, 0.01]},
                "net_weighting": {"ruplace_net_weight_gamma": [0.025, 0.05]},
            },
        })

        self.assertEqual(len(manifest), 8)
        local = [
            presets[name] for name, row in manifest.items()
            if row["plugins"] == ["local_gradient"]
        ]
        weighting = [
            presets[name] for name, row in manifest.items()
            if row["plugins"] == ["net_weighting"]
        ]
        self.assertTrue(all("ruplace_net_weight_gamma" not in row for row in local))
        self.assertTrue(all("ruplace_local_gradient_weight" not in row for row in weighting))
        self.assertEqual(
            {row["ruplace_local_gradient_weight"] for row in local}, {0.005, 0.01}
        )
        self.assertEqual(
            {row["ruplace_net_weight_gamma"] for row in weighting}, {0.025, 0.05}
        )

    def test_generates_pair_grid_and_skips_invalid_routeforce_proxy(self):
        presets, manifest = generate_presets(BASE, {
            "plugins": ["local_gradient", "net_weighting", "routeforce"],
            "combination_sizes": [2],
            "proxies": ["rudy", "gpugr"],
            "grid": {"ruplace_plugin_start_overflow": [0.6, 0.8]},
        })

        self.assertEqual(len(manifest), 8)
        self.assertIn("hpwl", presets)
        self.assertTrue(all(
            row["proxy"] in ("gpugr", "xplace")
            for row in manifest.values() if "routeforce" in row["plugins"]
        ))
        self.assertEqual(
            {row["grid"]["ruplace_plugin_start_overflow"] for row in manifest.values()},
            {0.6, 0.8},
        )

    def test_all_in_process_route_plugins_skip_rudy_proxy(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        for plugin in (
            "routeforce",
            "connection_routeforce",
            "projected_connection_routeforce",
            "routed_overflow_net_contraction",
        ):
            _, manifest = generate_presets(base, {
                "plugins": [plugin],
                "combination_sizes": [1],
                "proxies": ["rudy", "gpugr"],
            })
            self.assertEqual(
                {row["proxy"] for row in manifest.values()}, {"gpugr"}
            )

    def test_projected_connection_routeforce_v36_is_bounded_factorial(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_projected_connection_routeforce_pilot_v36.json"
            ).read_text()
        )
        presets, manifest = generate_presets(base, spec, max_presets=8)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 8)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {row["ruplace_connection_routeforce_x_scale"] for row in configs},
            {4.0, 7.5},
        )
        self.assertEqual(
            {
                row["ruplace_projected_connection_routeforce_mode"]
                for row in configs
            },
            {
                "global_nonopposing",
                "node_nonopposing",
                "global_orthogonal",
                "node_orthogonal",
            },
        )
        self.assertEqual(
            {tuple(row["ruplace_plugins"]) for row in configs},
            {("projected_connection_routeforce",)},
        )

    def test_projected_connection_routeforce_v37_is_bounded_factorial(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_projected_connection_routeforce_strength_xratio_pilot_v37.json"
            ).read_text()
        )
        presets, manifest = generate_presets(base, spec, max_presets=16)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 16)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {row["ruplace_connection_routeforce_x_scale"] for row in configs},
            {1.0, 2.0, 3.0, 4.0},
        )
        self.assertEqual(
            {
                row["ruplace_projected_connection_routeforce_strength"]
                for row in configs
            },
            {0.25, 0.5, 0.75, 1.0},
        )
        self.assertEqual(
            {row["ruplace_projected_connection_routeforce_mode"] for row in configs},
            {"node_orthogonal"},
        )

    def test_routed_overflow_contraction_v42_is_bounded_factorial(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_threshold_exponent_pilot_v42.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=8)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 8)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {row["ruplace_routed_overflow_net_contraction_weight"] for row in configs},
            {0.002},
        )
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_threshold"]
                for row in configs
            },
            {0.0, 0.02, 0.04, 0.06},
        )
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_exponent"]
                for row in configs
            },
            {1.0, 2.0},
        )
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 8
        )

    def test_routed_overflow_contraction_v43_is_bounded_factorial(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_span_distance_pilot_v43.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=8)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 8)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {row["ruplace_routed_overflow_net_contraction_weight"] for row in configs},
            {0.002},
        )
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_max_wire_span"]
                for row in configs
            },
            {3, 5, 9, 19},
        )
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_distance_weighting"]
                for row in configs
            },
            {"uniform", "inverse_sqrt"},
        )
        controls = [
            row for row in configs
            if row["ruplace_routed_overflow_net_contraction_max_wire_span"] == 19
            and row["ruplace_routed_overflow_net_contraction_distance_weighting"]
            == "uniform"
        ]
        self.assertEqual(len(controls), 1)
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 8
        )

    def test_routed_overflow_contraction_v44_is_bounded_factorial(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_span_weight_pilot_v44.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=12)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 12)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_max_wire_span"]
                for row in configs
            },
            {3, 4, 5},
        )
        self.assertEqual(
            {row["ruplace_routed_overflow_net_contraction_weight"] for row in configs},
            {0.0005, 0.001, 0.0015, 0.002},
        )
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_distance_weighting"]
                for row in configs
            },
            {"uniform"},
        )
        controls = [
            row for row in configs
            if row["ruplace_routed_overflow_net_contraction_max_wire_span"] == 5
            and row["ruplace_routed_overflow_net_contraction_weight"] == 0.002
        ]
        self.assertEqual(len(controls), 1)
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 12
        )

    def test_routed_overflow_contraction_v45_is_bounded_sweep(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_orthogonal_spread_pilot_v45.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=7)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 7)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {
                row[
                    "ruplace_routed_overflow_net_contraction_orthogonal_spread_scale"
                ]
                for row in configs
            },
            {0.0, 0.03125, 0.0625, 0.125, 0.25, 0.5, 1.0},
        )
        self.assertTrue(all(
            row["ruplace_routed_overflow_net_contraction_max_wire_span"] == 4
            and row["ruplace_routed_overflow_net_contraction_weight"] == 0.002
            for row in configs
        ))
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 7
        )

    def test_routed_overflow_contraction_v46_is_bounded_sweep(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_objective_projection_pilot_v46.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=7)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 7)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_projection_strength"]
                for row in configs
            },
            {0.0, 0.0625, 0.125, 0.25, 0.5, 0.75, 1.0},
        )
        self.assertTrue(all(
            row["ruplace_routed_overflow_net_contraction_projection_mode"]
            == "node_nonopposing"
            and row[
                "ruplace_routed_overflow_net_contraction_orthogonal_spread_scale"
            ] == 0.0
            for row in configs
        ))
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 7
        )

    def test_routed_overflow_contraction_v47_is_bounded_sweep(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_apply_interval_pilot_v47.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=6)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 6)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_apply_interval"]
                for row in configs
            },
            {20, 40, 60, 80, 100, 120},
        )
        self.assertTrue(all(
            row["ruplace_routed_overflow_net_contraction_route_freq"] == 20
            and row["ruplace_routed_overflow_net_contraction_projection_mode"]
            == "none"
            for row in configs
        ))
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 6
        )

    def test_routed_overflow_contraction_v51_is_bounded_smoothing_sweep(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_smoothing_radius_pilot_v51.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=7)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 7)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {
                row[
                    "ruplace_routed_overflow_net_contraction_smoothing_radius"
                ]
                for row in configs
            },
            {0, 1, 2, 3, 4, 6, 8},
        )
        self.assertTrue(all(
            row["ruplace_routed_overflow_net_contraction_smoothing_padding"]
            == "replicate"
            and row["ruplace_routed_overflow_net_contraction_max_applications"]
            == 1
            and row["ruplace_routed_overflow_net_contraction_apply_offset"] == 0
            for row in configs
        ))
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 7
        )

    def test_routed_overflow_contraction_v52_covers_pure_orthogonal_response(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_response_orientation_pilot_v52.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=6)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 6)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {
                row["ruplace_routed_overflow_net_contraction_matching_scale"]
                for row in configs
            },
            {0.0, 0.125, 0.25, 0.5, 0.75, 1.0},
        )
        self.assertTrue(all(
            row[
                "ruplace_routed_overflow_net_contraction_orthogonal_spread_scale"
            ] == 1.0
            and row[
                "ruplace_routed_overflow_net_contraction_smoothing_radius"
            ] == 0
            for row in configs
        ))
        pure = [
            row for row in configs
            if row["ruplace_routed_overflow_net_contraction_matching_scale"] == 0.0
        ]
        self.assertEqual(len(pure), 1)
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 6
        )

    def test_routed_overflow_contraction_v53_blends_utilization_pressure(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads(
            (
                ROOT
                / "configs/routability_routed_overflow_net_contraction_utilization_pressure_pilot_v53.json"
            ).read_text()
        )

        presets, manifest = generate_presets(base, spec, max_presets=7)
        configs = [presets[name] for name in manifest]

        self.assertEqual(len(configs), 7)
        self.assertTrue(all(row["development_only"] for row in manifest.values()))
        self.assertEqual(
            {
                row[
                    "ruplace_routed_overflow_net_contraction_utilization_pressure_scale"
                ]
                for row in configs
            },
            {0.0, 0.03125, 0.0625, 0.125, 0.25, 0.5, 1.0},
        )
        self.assertTrue(all(
            row[
                "ruplace_routed_overflow_net_contraction_utilization_threshold"
            ] == 0.85
            and row[
                "ruplace_routed_overflow_net_contraction_utilization_exponent"
            ] == 1.0
            and row["ruplace_routed_overflow_net_contraction_matching_scale"]
            == 1.0
            for row in configs
        ))
        self.assertEqual(
            len({json.dumps(row, sort_keys=True) for row in configs}), 7
        )

    def test_rejects_unbounded_generation(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            generate_presets(BASE, {
                "plugins": ["local_gradient", "net_weighting", "routeforce"],
                "combination_sizes": [2],
                "proxies": ["gpugr"],
                "grid": {"ruplace_plugin_start_overflow": [0.5, 0.6]},
            }, max_presets=2)

    def test_directional_virtual_cell_v70_grid_is_bounded_and_structural(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT / "configs/routability_directional_virtual_cell_pilot_v70.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=12)
        rows = [presets[name] for name in manifest]

        self.assertEqual(len(rows), 12)
        self.assertEqual({row["ruplace_proxy"] for row in rows}, {"rudy", "gpugr"})
        self.assertEqual({
            row["ruplace_directional_virtual_cell_reduction"] for row in rows
        }, {"mean", "sum"})
        self.assertEqual({
            row["ruplace_directional_virtual_cell_weight"] for row in rows
        }, {0.001, 0.0025, 0.005})
        self.assertTrue(all(
            row["ruplace_plugins"] == ["directional_virtual_cell"]
            and row["ruplace_directional_virtual_cell_threshold"] == 0.8
            for row in rows
        ))

    def test_directional_virtual_cell_v71_grid_contains_v70_control(self):
        base = json.loads(
            (ROOT / "configs/routability_plugins/presets.json").read_text()
        )
        spec = json.loads((
            ROOT
            / "configs/routability_directional_virtual_cell_balance_pilot_v71.json"
        ).read_text())
        presets, manifest = generate_presets(base, spec, max_presets=18)
        rows = [presets[name] for name in manifest]

        self.assertEqual(len(rows), 18)
        self.assertEqual({
            row["ruplace_directional_virtual_cell_axis_balance"] for row in rows
        }, {0.5, 1.0, 2.0})
        self.assertEqual({
            row["ruplace_directional_virtual_cell_smooth"] for row in rows
        }, {1, 2, 3})
        controls = [
            row for row in rows
            if row["ruplace_proxy"] == "gpugr"
            and row["ruplace_directional_virtual_cell_axis_balance"] == 1.0
            and row["ruplace_directional_virtual_cell_smooth"] == 2
        ]
        self.assertEqual(len(controls), 1)
        self.assertEqual(
            controls[0]["ruplace_directional_virtual_cell_weight"], 0.0025
        )
        self.assertEqual(
            controls[0]["ruplace_directional_virtual_cell_reduction"], "mean"
        )

    def test_rejects_provenance_overrides(self):
        with self.assertRaisesRegex(ValueError, "identity keys"):
            generate_presets(BASE, {
                "plugins": ["local_gradient", "net_weighting"],
                "combination_sizes": [2],
                "proxies": ["rudy"],
                "shared_overrides": {"ruplace_proxy": "gpugr"},
            })

    def test_rejects_unknown_plugin_grid(self):
        with self.assertRaisesRegex(ValueError, "unknown plugins"):
            generate_presets(BASE, {
                "plugins": ["local_gradient", "net_weighting"],
                "combination_sizes": [1],
                "proxies": ["rudy"],
                "plugin_grids": {"poisson_force": {"ruplace_poisson_weight": [0.01]}},
            })

    def test_cli_writes_presets_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            spec = root / "spec.json"
            output = root / "generated.json"
            base.write_text(json.dumps(BASE))
            spec.write_text(json.dumps({
                "plugins": ["local_gradient", "net_weighting"],
                "combination_sizes": [2],
                "proxies": ["rudy"],
            }))
            status = main([
                "--base-presets", str(base), "--spec", str(spec),
                "--output", str(output),
            ])
            generated = json.loads(output.read_text())
            provenance = json.loads(
                output.with_suffix(".json.manifest.json").read_text()
            )

        self.assertEqual(status, 0)
        self.assertEqual(len(generated), 2)
        self.assertEqual(len(provenance["generated"]), 1)
        self.assertEqual(provenance["metadata"], {
            "development_only": True,
            "heldout_or_golden_evidence_used": False,
            "numeric_backend_mixing": False,
            "generated_count": 1,
        })


if __name__ == "__main__":
    unittest.main()
