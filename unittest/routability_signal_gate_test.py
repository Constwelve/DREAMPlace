#!/usr/bin/env python3

import unittest
from unittest import mock

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin


class Obj:
    pass


class RoutabilitySignalGateTest(unittest.TestCase):
    def make_plugin(self, **values):
        params = Obj()
        for key, value in values.items():
            setattr(params, key, value)
        return RoutabilityPlugin(params, Obj(), Obj())

    @staticmethod
    def context(iteration):
        context = Obj()
        context.iteration = iteration
        context.proxy = Obj()
        context.proxy.last_iteration = iteration
        return context

    def test_default_gate_preserves_existing_behavior(self):
        plugin = self.make_plugin()
        passed, metrics = plugin.congestion_stagnation_gate(
            self.context(1), torch.zeros(2, 2)
        )
        self.assertTrue(passed)
        self.assertEqual(metrics["congestion_gate_enabled"], 0)

    def test_gate_requires_distinct_nonimproving_observations(self):
        plugin = self.make_plugin(
            ruplace_force_stagnation_window=3,
            ruplace_force_stagnation_tolerance=0.0,
            ruplace_force_min_overflow_sum=10.0,
            ruplace_force_min_overflow_bins=1,
        )
        for iteration, value in ((1, 20.0), (2, 30.0), (3, 25.0)):
            passed, _ = plugin.congestion_stagnation_gate(
                self.context(iteration), torch.tensor([[value]])
            )
            self.assertFalse(passed)

        passed, metrics = plugin.congestion_stagnation_gate(
            self.context(4), torch.tensor([[26.0]])
        )
        self.assertFalse(passed)
        passed, metrics = plugin.congestion_stagnation_gate(
            self.context(5), torch.tensor([[27.0]])
        )
        self.assertTrue(passed)
        self.assertEqual(metrics["congestion_gate_nonimproving"], 1)

        passed, metrics = plugin.congestion_stagnation_gate(
            self.context(5), torch.tensor([[28.0]])
        )
        self.assertTrue(passed)
        self.assertEqual(metrics["congestion_gate_fresh_observation"], 0)
        self.assertEqual(metrics["congestion_gate_observations"], 3)

    def test_utilization_gate_uses_over_threshold_pressure(self):
        plugin = self.make_plugin(
            ruplace_force_stagnation_window=1,
            ruplace_force_min_overflow_sum=0.1,
            ruplace_force_gate_utilization_threshold=1.0,
        )
        passed, metrics = plugin.congestion_stagnation_gate(
            self.context(1), torch.full((2, 2), 0.9), utilization_map=True
        )
        self.assertFalse(passed)
        self.assertEqual(metrics["congestion_gate_overflow_sum"], 0.0)

        passed, metrics = plugin.congestion_stagnation_gate(
            self.context(2), torch.tensor([[1.2, 0.8], [1.0, 1.0]]),
            utilization_map=True,
        )
        self.assertTrue(passed)
        self.assertAlmostEqual(metrics["congestion_gate_overflow_sum"], 0.2)

    def test_gate_rejects_invalid_controls(self):
        cases = (
            ({"ruplace_force_stagnation_window": 0}, "window"),
            ({"ruplace_force_stagnation_tolerance": 1.1}, "tolerance"),
            ({"ruplace_force_min_overflow_sum": -1.0}, "overflow sum"),
            ({"ruplace_force_min_overflow_bins": -1}, "overflow bins"),
            ({"ruplace_force_gate_utilization_threshold": -1.0},
             "utilization threshold"),
        )
        for values, message in cases:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, message):
                    self.make_plugin(**values).congestion_stagnation_gate(
                        self.context(1), torch.ones(2, 2)
                    )

    def test_local_gradient_applies_only_after_stagnant_window(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.local_gradient import (
            LocalCongestionGradientPlugin,
        )

        params = Obj()
        params.ruplace_local_gradient_weight = 0.01
        params.ruplace_local_gradient_smooth = 0
        params.ruplace_force_congestion_mode = "aggregate"
        params.ruplace_force_stagnation_window = 3
        params.ruplace_force_stagnation_tolerance = 0.0
        params.ruplace_force_min_overflow_sum = 10.0
        params.ruplace_force_min_overflow_bins = 1
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 3.0
        plugin = LocalCongestionGradientPlugin(params, db, Obj())
        context = self.context(0)
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[:1], gy.reshape(-1)[:1]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        signal = Obj()
        context.signal = lambda pos: signal.value

        for iteration, total, expected in (
            (1, 20.0, False),
            (2, 30.0, False),
            (3, 25.0, False),
            (4, 26.0, False),
            (5, 27.0, True),
        ):
            context.iteration = iteration
            context.proxy.last_iteration = iteration
            value = torch.zeros(3, 3)
            value[1, 1] = total / 3.0
            value[2, 1] = total * 2.0 / 3.0
            signal.value = CongestionSignal(
                utilization_map=torch.ones(3, 3), overflow_map=value
            )
            self.assertEqual(
                plugin.apply_gradient(torch.zeros(2), Obj(), context), expected
            )

        context.add_scaled_movable_gradient.assert_called_once()
        self.assertEqual(plugin.force_applications, 1)


if __name__ == "__main__":
    unittest.main()
