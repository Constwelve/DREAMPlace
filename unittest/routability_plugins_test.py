#!/usr/bin/env python3

import unittest
from unittest import mock
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import torch
except ImportError:
    torch = None


class Obj:
    pass


@unittest.skipIf(torch is None, "torch is not installed")
class RoutabilityPluginMathTest(unittest.TestCase):
    def test_duplicate_plugins_are_rejected(self):
        from dreamplace.ops.routability_opt.plugins import build_plugins

        params = Obj()
        params.ruplace_plugins = ["local_gradient", "local_gradient"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_plugins(params, Obj(), Obj())

    def test_zero_congestion_field_is_not_reported_as_activation(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.local_gradient import (
            LocalCongestionGradientPlugin,
        )

        params = Obj()
        params.ruplace_local_gradient_smooth = 0
        params.ruplace_local_gradient_weight = 0.05
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        context = Obj()
        context.signal = lambda pos: CongestionSignal(torch.zeros(2, 2))
        context.sample_vector_field = lambda pos, gx, gy: (torch.zeros(1), torch.zeros(1))
        context.add_movable_gradient = mock.Mock()
        plugin = LocalCongestionGradientPlugin(params, db, Obj())

        changed = plugin.apply_gradient(torch.zeros(2), Obj(), context)

        self.assertFalse(changed)
        context.add_movable_gradient.assert_not_called()

    def test_composite_area_plugins_share_cumulative_inflation_state(self):
        from dreamplace.ops.routability_opt.pipeline import RoutabilityOptimizationPipeline

        params = Obj()
        params.ruplace_plugins = ["momentum_inflation", "pin_porosity"]
        params.ruplace_proxy = "rudy_pin"
        params.ruplace_proxy_refresh_interval = 1
        db = Obj()
        db.num_movable_nodes = 2
        db.num_filler_nodes = 0
        data = Obj()
        data.node_size_x = torch.ones(2)
        data.node_size_y = torch.ones(2)
        data.target_density = torch.tensor(1.0)
        with mock.patch(
            "dreamplace.ops.routability_opt.pipeline.build_congestion_proxy",
            return_value=Obj(),
        ):
            pipeline = RoutabilityOptimizationPipeline(params, db, data, Obj())
        self.assertIs(pipeline.plugins[0].engine, pipeline.plugins[1].engine)

    def test_poisson_solver_is_finite_and_zero_mean(self):
        from dreamplace.ops.routability_opt.plugin_base import poisson_potential

        charge = torch.zeros(8, 8)
        charge[4, 4] = 1.0
        potential = poisson_potential(charge)
        self.assertTrue(torch.isfinite(potential).all())
        self.assertAlmostEqual(potential.mean().item(), 0.0, places=6)
        self.assertGreater(potential[4, 4].item(), potential[0, 0].item())

    def test_map_gradient_points_toward_hotspot(self):
        from dreamplace.ops.routability_opt.plugin_base import map_gradient

        value = torch.tensor([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]])
        gx, gy = map_gradient(value)
        self.assertGreater(gx[1, 1].item(), 0.0)
        self.assertEqual(gy[1, 1].item(), 0.0)

    def test_footprint_average_uses_more_than_center_bin(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.utils import node_footprint_average

        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 4.0
        data = Obj()
        data.node_size_x = torch.tensor([2.0])
        data.node_size_y = torch.tensor([2.0])
        context = PluginContext(Obj(), db, data, Obj(), Obj())
        pos = torch.tensor([0.0, 0.0])
        value = torch.tensor(
            [[4.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0],
             [0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]]
        )
        exposure = node_footprint_average(context, pos, value)
        self.assertEqual(exposure.item(), 1.0)


if __name__ == "__main__":
    unittest.main()
