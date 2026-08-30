#!/usr/bin/env python3

import ast
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


class BundledGPUGRSourceTest(unittest.TestCase):
    def test_connection_gradient_normalizes_signed_spans_and_guards_division(self):
        patch_path = ROOT / "cmake/xplace_gpugr_negative_span.patch"
        source_path = (
            ROOT / "thirdparty/XplaceGPUGR/cpp_to_py/gpugr/gr/GPURouterTorch.cu"
        )
        cmake = (ROOT / "CMakeLists.txt").read_text()
        patch = patch_path.read_text()
        source = source_path.read_text()
        required = (
            "if (hx < lx)",
            "cudaSwapInt(lx, hx)",
            "if (hy < ly)",
            "cudaSwapInt(ly, hy)",
            "if (total_weight > 0)",
        )

        self.assertIn(patch_path.name, cmake)
        self.assertIn("apply --directory=thirdparty/XplaceGPUGR", cmake)
        for fragment in required:
            self.assertIn(fragment, patch)
        self.assertEqual(patch.count("reverseRoute = !reverseRoute;"), 2)
        self.assertEqual(patch.count("+                if (total_weight > 0)"), 2)

        if "if (hx < lx)" in source:
            start = source.index("__global__ void compGcellRouteForce(")
            end = source.index("__global__ void assignRouteForceToPlPin(", start)
            kernel = source[start:end]
            for fragment in required:
                self.assertIn(fragment, kernel)
            self.assertEqual(kernel.count("reverseRoute = !reverseRoute;"), 2)
            self.assertEqual(kernel.count("if (total_weight > 0)"), 2)

    def test_multisegment_routeforce_is_separate_and_reference_preserving(self):
        patch = (ROOT / "cmake/xplace_gpugr_negative_span.patch").read_text()
        source_root = ROOT / "thirdparty/XplaceGPUGR/cpp_to_py/gpugr"
        cuda = (source_root / "gr/GPURouterTorch.cu").read_text()
        binding = (source_root / "PyBindCppMain.cpp").read_text()

        for fragment in (
            "calcRouteGradReduce",
            "segment_reduce_mode == 0",
            "segment_reduce_mode == 2",
            "gbpin_grad[idx][0] += contribution",
            "gbpin_grad[idx][1] += contribution",
        ):
            self.assertIn(fragment, patch)
            self.assertIn(fragment, cuda)
        self.assertIn('def("route_grad_reduce"', patch)
        self.assertIn('def("route_grad_reduce"', binding)
        # The original route_grad entry point delegates to mode zero, which
        # retains Xplace's last-segment assignment behavior.
        start = cuda.index("torch::Tensor GPURouter::calcRouteGrad(")
        end = cuda.index("torch::Tensor GPURouter::calcRouteGradReduce(", start)
        self.assertIn("num_nodes,\n                               0);", cuda[start:end])


@unittest.skipIf(torch is None, "torch is not installed")
class RoutabilityPluginMathTest(unittest.TestCase):
    def test_unchanged_geometry_recovery_preserves_position_bytes(self):
        from dreamplace.ops.routability_opt.plugin_base import (
            restore_original_node_geometry,
        )

        db = Obj()
        db.num_nodes = 3
        db.num_movable_nodes = 2
        data = Obj()
        data.node_size_x = torch.tensor([1.0, 2.0, 3.0])
        data.node_size_y = torch.tensor([2.0, 4.0, 6.0])
        data.original_node_size_x = data.node_size_x.clone()
        data.original_node_size_y = data.node_size_y.clone()
        data.pin_offset_x = torch.tensor([0.25, 0.75])
        data.pin_offset_y = torch.tensor([0.5, 1.5])
        data.original_pin_offset_x = data.pin_offset_x.clone()
        data.original_pin_offset_y = data.pin_offset_y.clone()
        pos = torch.tensor([0.1, 1.3, 2.7, 3.9, 4.2, 5.8])
        before = pos.clone()

        changed = restore_original_node_geometry(pos, db, data)

        self.assertFalse(changed)
        self.assertTrue(torch.equal(pos, before))

    def test_changed_geometry_recovery_preserves_centers(self):
        from dreamplace.ops.routability_opt.plugin_base import (
            restore_original_node_geometry,
        )

        db = Obj()
        db.num_nodes = 3
        db.num_movable_nodes = 2
        data = Obj()
        data.node_size_x = torch.tensor([2.0, 4.0, 3.0])
        data.node_size_y = torch.tensor([4.0, 8.0, 6.0])
        data.original_node_size_x = torch.tensor([1.0, 2.0, 3.0])
        data.original_node_size_y = torch.tensor([2.0, 4.0, 6.0])
        data.pin_offset_x = torch.tensor([0.5, 1.5])
        data.pin_offset_y = torch.tensor([1.0, 3.0])
        data.original_pin_offset_x = torch.tensor([0.25, 0.75])
        data.original_pin_offset_y = torch.tensor([0.5, 1.5])
        pos = torch.tensor([0.0, 10.0, 20.0, 0.0, 20.0, 40.0])
        centers_x = pos[:2] + data.node_size_x[:2] * 0.5
        centers_y = pos[3:5] + data.node_size_y[:2] * 0.5

        changed = restore_original_node_geometry(pos, db, data)

        self.assertTrue(changed)
        self.assertTrue(torch.equal(
            centers_x, pos[:2] + data.node_size_x[:2] * 0.5
        ))
        self.assertTrue(torch.equal(
            centers_y, pos[3:5] + data.node_size_y[:2] * 0.5
        ))
        self.assertTrue(torch.equal(
            data.node_size_x, data.original_node_size_x
        ))
        self.assertTrue(torch.equal(
            data.node_size_y, data.original_node_size_y
        ))
        self.assertTrue(torch.equal(
            data.pin_offset_x, data.original_pin_offset_x
        ))
        self.assertTrue(torch.equal(
            data.pin_offset_y, data.original_pin_offset_y
        ))

    def test_directional_local_gradient_uses_cross_track_axes(self):
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            directional_local_gradient_field,
        )

        horizontal = torch.tensor([
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
        ])
        vertical = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0],
        ])
        field_x, field_y = directional_local_gradient_field(
            horizontal, vertical, 0, "replicate"
        )
        self.assertTrue(torch.all(field_x > 0.0))
        self.assertTrue(torch.all(field_y > 0.0))

        field_x, field_y = directional_local_gradient_field(
            horizontal, vertical, 0, "replicate", mode="horizontal"
        )
        self.assertTrue(torch.equal(field_x, torch.zeros_like(field_x)))
        self.assertTrue(torch.all(field_y > 0.0))

    def test_directional_local_gradient_mapping_and_polarity(self):
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            directional_local_gradient_field,
        )

        horizontal = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0],
        ])
        vertical = horizontal.t().contiguous()
        field_x, field_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            axis_mapping="matching_axis",
        )
        self.assertTrue(torch.all(field_x > 0.0))
        self.assertTrue(torch.all(field_y > 0.0))

        attract_x, attract_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            axis_mapping="matching_axis",
            polarity="attract",
        )
        self.assertTrue(torch.allclose(attract_x, -field_x))
        self.assertTrue(torch.allclose(attract_y, -field_y))

        horizontal_x, horizontal_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            mode="horizontal",
            axis_mapping="matching_axis",
        )
        self.assertTrue(torch.all(horizontal_x > 0.0))
        self.assertTrue(torch.equal(
            horizontal_y, torch.zeros_like(horizontal_y)
        ))

    def test_directional_local_gradient_per_axis_normalization(self):
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            directional_local_gradient_field,
        )

        horizontal = torch.tensor([
            [0.0, 10.0, 20.0],
            [0.0, 10.0, 20.0],
            [0.0, 10.0, 20.0],
        ])
        vertical = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0],
        ])
        joint_x, joint_y = directional_local_gradient_field(
            horizontal, vertical, 0, "replicate", axis_balance=4.0,
        )
        explicit_joint_x, explicit_joint_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            axis_balance=4.0,
            normalization="joint",
        )
        axis_x, axis_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            axis_balance=4.0,
            normalization="per_axis",
        )
        joint_ratio = (
            joint_x.square().mean().sqrt() / joint_y.square().mean().sqrt()
        )
        axis_ratio = axis_x.square().mean().sqrt() / axis_y.square().mean().sqrt()

        self.assertAlmostEqual(joint_ratio.item(), 0.4, places=6)
        self.assertAlmostEqual(axis_ratio.item(), 4.0, places=6)
        self.assertTrue(torch.equal(joint_x, explicit_joint_x))
        self.assertTrue(torch.equal(joint_y, explicit_joint_y))
        zero_x, zero_y = directional_local_gradient_field(
            horizontal,
            torch.zeros_like(vertical),
            0,
            "replicate",
            normalization="per_axis",
        )
        self.assertTrue(torch.equal(zero_x, torch.zeros_like(zero_x)))
        self.assertTrue(torch.isfinite(zero_y).all())
        with self.assertRaisesRegex(ValueError, "normalization"):
            directional_local_gradient_field(
                horizontal, vertical, 0, "replicate", normalization="bad"
            )

    def test_directional_local_gradient_blends_aggregate_feedback(self):
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            directional_local_gradient_field,
        )

        horizontal = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0],
        ])
        vertical = horizontal.t().contiguous()
        aggregate = torch.tensor([
            [0.0, 1.0, 2.0],
            [1.0, 2.0, 3.0],
            [2.0, 3.0, 4.0],
        ])
        default_x, default_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            axis_mapping="matching_axis",
        )
        zero_x, zero_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            axis_mapping="matching_axis",
            aggregate=aggregate,
            aggregate_blend=0.0,
        )
        aggregate_x, aggregate_y = directional_local_gradient_field(
            horizontal,
            vertical,
            0,
            "replicate",
            axis_mapping="matching_axis",
            aggregate=aggregate,
            aggregate_blend=1.0,
        )

        self.assertTrue(torch.equal(default_x, zero_x))
        self.assertTrue(torch.equal(default_y, zero_y))
        self.assertTrue(torch.all(aggregate_x > 0.0))
        self.assertTrue(torch.all(aggregate_y > 0.0))

        with self.assertRaisesRegex(ValueError, "requires an aggregate"):
            directional_local_gradient_field(
                horizontal,
                vertical,
                0,
                "replicate",
                aggregate_blend=0.25,
            )
        with self.assertRaisesRegex(ValueError, "must match"):
            directional_local_gradient_field(
                horizontal,
                vertical,
                0,
                "replicate",
                aggregate=torch.zeros(2, 2),
                aggregate_blend=0.25,
            )
        for invalid in (-0.1, 1.1, float("nan")):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "in \\[0, 1\\]"):
                    directional_local_gradient_field(
                        horizontal,
                        vertical,
                        0,
                        "replicate",
                        aggregate=aggregate,
                        aggregate_blend=invalid,
                    )

    def test_directional_local_gradient_applies_node_field(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            DirectionalLocalCongestionGradientPlugin,
        )

        params = Obj()
        params.ruplace_directional_local_gradient_weight = 0.01
        params.ruplace_directional_local_gradient_smooth = 0
        params.ruplace_directional_local_gradient_feedback = "overflow"
        params.ruplace_directional_local_gradient_mode = "both"
        params.ruplace_directional_local_gradient_axis_balance = 1.0
        params.ruplace_directional_local_gradient_axis_mapping = "cross_track"
        params.ruplace_directional_local_gradient_polarity = "repel"
        params.ruplace_directional_local_gradient_normalization = "per_axis"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 3.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        horizontal = torch.tensor([
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
        ])
        vertical = horizontal.t().contiguous()
        context.signal = lambda pos: CongestionSignal(
            torch.maximum(horizontal, vertical),
            hv_overflow_map=torch.stack((horizontal, vertical)),
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[:1], gy.reshape(-1)[:1]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = DirectionalLocalCongestionGradientPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        node_x, node_y = context.add_scaled_movable_gradient.call_args.args[1:3]
        self.assertGreater(node_x.item(), 0.0)
        self.assertGreater(node_y.item(), 0.0)
        self.assertEqual(plugin.metrics["directional_mode_id"], 0)
        self.assertEqual(plugin.metrics["directional_axis_mapping_id"], 0)
        self.assertEqual(plugin.metrics["directional_polarity_id"], 0)
        self.assertEqual(plugin.metrics["directional_normalization_id"], 1)

    def test_directional_local_gradient_applies_utilization_feedback(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            DirectionalLocalCongestionGradientPlugin,
        )

        params = Obj()
        params.ruplace_directional_local_gradient_weight = 0.01
        params.ruplace_directional_local_gradient_smooth = 0
        params.ruplace_directional_local_gradient_feedback = "utilization"
        params.ruplace_directional_local_gradient_mode = "both"
        params.ruplace_directional_local_gradient_axis_balance = 1.0
        params.ruplace_directional_local_gradient_axis_mapping = "matching_axis"
        params.ruplace_directional_local_gradient_polarity = "repel"
        params.ruplace_directional_local_gradient_normalization = "joint"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 3.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        horizontal = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0],
        ])
        vertical = horizontal.t().contiguous()
        context.signal = lambda pos: CongestionSignal(
            torch.maximum(horizontal, vertical),
            hv_utilization_map=torch.stack((horizontal, vertical)),
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[4:5], gy.reshape(-1)[4:5]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = DirectionalLocalCongestionGradientPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        node_x, node_y = context.add_scaled_movable_gradient.call_args.args[1:3]
        self.assertGreater(node_x.item(), 0.0)
        self.assertGreater(node_y.item(), 0.0)
        self.assertEqual(plugin.metrics["directional_feedback_utilization"], 1)
        self.assertEqual(plugin.metrics["directional_axis_mapping_id"], 1)

    def test_directional_local_gradient_plugin_uses_aggregate_blend(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            DirectionalLocalCongestionGradientPlugin,
        )

        params = Obj()
        params.ruplace_directional_local_gradient_weight = 0.01
        params.ruplace_directional_local_gradient_smooth = 0
        params.ruplace_directional_local_gradient_feedback = "utilization"
        params.ruplace_directional_local_gradient_mode = "both"
        params.ruplace_directional_local_gradient_axis_balance = 1.0
        params.ruplace_directional_local_gradient_axis_mapping = "matching_axis"
        params.ruplace_directional_local_gradient_polarity = "repel"
        params.ruplace_directional_local_gradient_normalization = "joint"
        params.ruplace_directional_local_gradient_aggregate_blend = 1.0
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 3.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        flat_hv = torch.zeros(2, 3, 3)
        aggregate = torch.tensor([
            [0.0, 1.0, 2.0],
            [1.0, 2.0, 3.0],
            [2.0, 3.0, 4.0],
        ])
        context.signal = lambda pos: CongestionSignal(
            aggregate,
            hv_utilization_map=flat_hv,
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[4:5], gy.reshape(-1)[4:5]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = DirectionalLocalCongestionGradientPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        node_x, node_y = context.add_scaled_movable_gradient.call_args.args[1:3]
        self.assertGreater(node_x.item(), 0.0)
        self.assertGreater(node_y.item(), 0.0)
        self.assertEqual(plugin.metrics["directional_aggregate_blend"], 1.0)

    def test_directional_cvar_pressure_preserves_endpoints(self):
        from dreamplace.ops.routability_opt.plugins.directional_cvar_gradient import (
            directional_cvar_pressure,
        )

        horizontal = torch.arange(16, dtype=torch.float32).reshape(4, 4)
        vertical = horizontal.t().contiguous()
        utilization = torch.stack((horizontal, vertical))
        overflow = (utilization - 5.0).clamp_min(0.0)

        overflow_only, thresholds, tail = directional_cvar_pressure(
            utilization, overflow, 0.75, 0.0
        )
        tail_only, _, _ = directional_cvar_pressure(
            utilization, overflow, 0.75, 1.0
        )
        blended, _, _ = directional_cvar_pressure(
            utilization, overflow, 0.75, 0.5
        )

        self.assertTrue(torch.equal(overflow_only, overflow))
        self.assertTrue(torch.equal(tail_only, tail))
        self.assertEqual(int((tail[0] > 0).sum()), 4)
        self.assertEqual(int((tail[1] > 0).sum()), 4)
        self.assertTrue(torch.allclose(
            thresholds, torch.tensor([11.25, 11.25])
        ))
        self.assertTrue(torch.isfinite(blended).all())
        self.assertGreater(blended.sum().item(), 0.0)
        easy = torch.full((2, 4, 4), 0.8)
        easy_pressure, easy_thresholds, _ = directional_cvar_pressure(
            easy, torch.zeros_like(easy), 0.75, 1.0
        )
        self.assertTrue(torch.equal(easy_pressure, torch.zeros_like(easy)))
        self.assertTrue(torch.equal(easy_thresholds, torch.ones(2)))
        with self.assertRaisesRegex(ValueError, "quantile"):
            directional_cvar_pressure(utilization, overflow, 1.0, 0.5)
        with self.assertRaisesRegex(ValueError, "tail blend"):
            directional_cvar_pressure(utilization, overflow, 0.99, 1.1)

    def test_aggregate_cvar_pressure_preserves_endpoints(self):
        from dreamplace.ops.routability_opt.plugins.aggregate_cvar_gradient import (
            aggregate_cvar_pressure,
        )

        utilization = torch.arange(16, dtype=torch.float32).reshape(4, 4)
        overflow = (utilization - 5.0).clamp_min(0.0)

        overflow_only, threshold, tail = aggregate_cvar_pressure(
            utilization, overflow, 0.75, 0.0
        )
        tail_only, _, _ = aggregate_cvar_pressure(
            utilization, overflow, 0.75, 1.0
        )
        blended, _, _ = aggregate_cvar_pressure(
            utilization, overflow, 0.75, 0.5
        )

        self.assertTrue(torch.equal(overflow_only, overflow))
        self.assertTrue(torch.equal(tail_only, tail))
        self.assertEqual(int((tail > 0).sum()), 4)
        self.assertAlmostEqual(threshold.item(), 11.25)
        self.assertTrue(torch.isfinite(blended).all())
        easy = torch.full((4, 4), 0.8)
        easy_pressure, easy_threshold, easy_tail = aggregate_cvar_pressure(
            easy, torch.zeros_like(easy), 0.75, 1.0
        )
        self.assertTrue(torch.equal(easy_pressure, torch.zeros_like(easy)))
        self.assertTrue(torch.equal(easy_tail, torch.zeros_like(easy)))
        self.assertEqual(easy_threshold.item(), 1.0)
        with self.assertRaisesRegex(ValueError, "2D tensors"):
            aggregate_cvar_pressure(
                utilization.unsqueeze(0), overflow.unsqueeze(0), 0.75, 0.5
            )
        with self.assertRaisesRegex(ValueError, "quantile"):
            aggregate_cvar_pressure(utilization, overflow, 1.0, 0.5)
        with self.assertRaisesRegex(ValueError, "tail blend"):
            aggregate_cvar_pressure(utilization, overflow, 0.99, 1.1)

    def test_aggregate_cvar_gradient_applies_tail_field(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.aggregate_cvar_gradient import (
            AggregateCVaRGradientPlugin,
        )

        params = Obj()
        params.ruplace_aggregate_cvar_gradient_weight = 0.01
        params.ruplace_aggregate_cvar_gradient_smooth = 0
        params.ruplace_aggregate_cvar_gradient_quantile = 0.75
        params.ruplace_aggregate_cvar_gradient_tail_blend = 0.75
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 4.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        utilization = torch.arange(16, dtype=torch.float32).reshape(4, 4)
        overflow = (utilization - 5.0).clamp_min(0.0)
        context.signal = lambda pos: CongestionSignal(
            utilization, overflow_map=overflow
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[-1:], gy.reshape(-1)[-1:]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = AggregateCVaRGradientPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        self.assertEqual(plugin.force_applications, 1)
        self.assertEqual(plugin.metrics["cvar_active_bins"], 4)
        self.assertAlmostEqual(plugin.metrics["cvar_threshold"], 11.25)
        self.assertGreater(plugin.metrics["field_norm"], 0.0)
        context.add_scaled_movable_gradient.assert_called_once()

    def test_aggregate_pnorm_pressure_emphasizes_peaks(self):
        from dreamplace.ops.routability_opt.plugins.aggregate_pnorm_gradient import (
            aggregate_pnorm_pressure,
        )

        utilization = torch.tensor([
            [0.5, 1.0, 1.5],
            [2.0, 3.0, float("nan")],
        ])
        linear, excess = aggregate_pnorm_pressure(utilization, 1.0)
        quadratic, _ = aggregate_pnorm_pressure(utilization, 2.0)

        self.assertTrue(torch.equal(linear, excess))
        self.assertTrue(torch.allclose(
            excess, torch.tensor([[0.0, 0.0, 0.5], [1.0, 2.0, 0.0]])
        ))
        self.assertTrue(torch.allclose(
            quadratic, torch.tensor([[0.0, 0.0, 0.25], [1.0, 4.0, 0.0]])
        ))
        self.assertGreater(
            quadratic[1, 1] / quadratic[0, 2],
            linear[1, 1] / linear[0, 2],
        )
        with self.assertRaisesRegex(ValueError, "2D tensor"):
            aggregate_pnorm_pressure(utilization.unsqueeze(0), 2.0)
        with self.assertRaisesRegex(ValueError, "exponent"):
            aggregate_pnorm_pressure(utilization, 0.5)
        with self.assertRaisesRegex(ValueError, "threshold"):
            aggregate_pnorm_pressure(utilization, 2.0, -1.0)

    def test_aggregate_pnorm_gradient_uses_common_overflow_gate(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.aggregate_pnorm_gradient import (
            AggregatePNormGradientPlugin,
        )

        params = Obj()
        params.ruplace_aggregate_pnorm_gradient_weight = 0.01
        params.ruplace_aggregate_pnorm_gradient_smooth = 0
        params.ruplace_aggregate_pnorm_gradient_exponent = 3.0
        params.ruplace_aggregate_pnorm_gradient_threshold = 1.0
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 4.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        utilization = torch.arange(16, dtype=torch.float32).reshape(4, 4)
        overflow = (utilization - 1.0).clamp_min(0.0)
        context.signal = lambda pos: CongestionSignal(
            utilization, overflow_map=overflow
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[-1:], gy.reshape(-1)[-1:]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = AggregatePNormGradientPlugin(params, db, Obj())
        plugin.congestion_stagnation_gate = mock.Mock(return_value=(True, {}))

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        gate_map = plugin.congestion_stagnation_gate.call_args.args[1]
        self.assertTrue(torch.equal(gate_map, overflow))
        self.assertEqual(plugin.metrics["pnorm_exponent"], 3.0)
        self.assertEqual(plugin.metrics["pnorm_active_bins"], 14)
        self.assertGreater(plugin.metrics["field_norm"], 0.0)
        context.add_scaled_movable_gradient.assert_called_once()

    def test_directional_cvar_gradient_applies_tail_field(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_cvar_gradient import (
            DirectionalCVaRGradientPlugin,
        )

        params = Obj()
        params.ruplace_directional_cvar_gradient_weight = 0.01
        params.ruplace_directional_cvar_gradient_smooth = 0
        params.ruplace_directional_cvar_gradient_quantile = 0.75
        params.ruplace_directional_cvar_gradient_tail_blend = 0.75
        params.ruplace_directional_cvar_gradient_mode = "both"
        params.ruplace_directional_cvar_gradient_axis_balance = 1.0
        params.ruplace_directional_cvar_gradient_axis_mapping = "matching_axis"
        params.ruplace_directional_cvar_gradient_polarity = "repel"
        params.ruplace_directional_cvar_gradient_normalization = "joint"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 4.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        horizontal = torch.arange(16, dtype=torch.float32).reshape(4, 4)
        vertical = horizontal.t().contiguous()
        utilization = torch.stack((horizontal, vertical))
        overflow = (utilization - 5.0).clamp_min(0.0)
        context.signal = lambda pos: CongestionSignal(
            utilization.max(dim=0).values,
            hv_overflow_map=overflow,
            hv_utilization_map=utilization,
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[-1:], gy.reshape(-1)[-1:]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = DirectionalCVaRGradientPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        self.assertEqual(plugin.force_applications, 1)
        self.assertEqual(plugin.metrics["cvar_horizontal_active_bins"], 4)
        self.assertEqual(plugin.metrics["cvar_vertical_active_bins"], 4)
        self.assertEqual(plugin.metrics["directional_axis_mapping_id"], 1)
        self.assertGreater(plugin.metrics["field_norm"], 0.0)
        context.add_scaled_movable_gradient.assert_called_once()

    def test_directional_excess_cvar_conditions_on_congested_bins(self):
        from dreamplace.ops.routability_opt.plugins.directional_cvar_gradient import (
            directional_cvar_pressure,
        )
        from dreamplace.ops.routability_opt.plugins.directional_excess_cvar_gradient import (
            directional_excess_cvar_pressure,
        )

        horizontal = torch.tensor([
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 1.1, 1.2, 0.0],
            [0.0, 1.3, 1.4, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ])
        utilization = torch.stack((horizontal, horizontal.t().contiguous()))
        overflow = (utilization - 1.0).clamp_min(0.0)

        overflow_only, thresholds, tail = directional_excess_cvar_pressure(
            utilization, overflow, 0.5, 0.0
        )
        tail_only, _, _ = directional_excess_cvar_pressure(
            utilization, overflow, 0.5, 1.0
        )
        _, all_bin_thresholds, all_bin_tail = directional_cvar_pressure(
            utilization, overflow, 0.5, 1.0
        )

        self.assertTrue(torch.equal(overflow_only, overflow))
        self.assertTrue(torch.equal(tail_only, tail))
        self.assertTrue(torch.allclose(thresholds, torch.tensor([1.25, 1.25])))
        self.assertEqual(int((tail[0] > 0).sum()), 2)
        self.assertEqual(int((tail[1] > 0).sum()), 2)
        self.assertTrue(torch.equal(all_bin_thresholds, torch.ones(2)))
        self.assertTrue(torch.equal(all_bin_tail, overflow))

        easy = torch.full((2, 4, 4), 0.8)
        easy_pressure, easy_thresholds, easy_tail = (
            directional_excess_cvar_pressure(
                easy, torch.zeros_like(easy), 0.95, 1.0
            )
        )
        self.assertTrue(torch.equal(easy_pressure, torch.zeros_like(easy)))
        self.assertTrue(torch.equal(easy_tail, torch.zeros_like(easy)))
        self.assertTrue(torch.equal(easy_thresholds, torch.ones(2)))

    def test_directional_excess_cvar_gradient_uses_separate_parameters(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_excess_cvar_gradient import (
            DirectionalExcessCVaRGradientPlugin,
        )

        params = Obj()
        params.ruplace_directional_excess_cvar_gradient_weight = 0.01
        params.ruplace_directional_excess_cvar_gradient_smooth = 0
        params.ruplace_directional_excess_cvar_gradient_quantile = 0.5
        params.ruplace_directional_excess_cvar_gradient_tail_blend = 0.75
        params.ruplace_directional_excess_cvar_gradient_mode = "both"
        params.ruplace_directional_excess_cvar_gradient_axis_balance = 1.0
        params.ruplace_directional_excess_cvar_gradient_axis_mapping = (
            "matching_axis"
        )
        params.ruplace_directional_excess_cvar_gradient_polarity = "repel"
        params.ruplace_directional_excess_cvar_gradient_normalization = "joint"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 4.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        horizontal = torch.tensor([
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 1.1, 1.2, 0.0],
            [0.0, 1.3, 1.4, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ])
        utilization = torch.stack((horizontal, horizontal.t().contiguous()))
        overflow = (utilization - 1.0).clamp_min(0.0)
        context.signal = lambda pos: CongestionSignal(
            utilization.max(dim=0).values,
            hv_overflow_map=overflow,
            hv_utilization_map=utilization,
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[-1:], gy.reshape(-1)[-1:]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = DirectionalExcessCVaRGradientPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        self.assertEqual(plugin.force_applications, 1)
        self.assertEqual(plugin.metrics["cvar_quantile"], 0.5)
        self.assertEqual(plugin.metrics["cvar_conditioned_on_overflow"], 1)
        self.assertEqual(plugin.metrics["cvar_horizontal_active_bins"], 2)
        self.assertEqual(plugin.metrics["cvar_vertical_active_bins"], 2)
        self.assertGreater(plugin.metrics["field_norm"], 0.0)
        context.add_scaled_movable_gradient.assert_called_once()

    def test_directional_local_gradient_tail_guard_blocks_regression(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            DirectionalLocalCongestionGradientPlugin,
        )

        params = Obj()
        params.ruplace_directional_local_gradient_weight = 0.01
        params.ruplace_directional_local_gradient_smooth = 0
        params.ruplace_directional_local_gradient_feedback = "overflow"
        params.ruplace_directional_local_gradient_mode = "both"
        params.ruplace_directional_local_gradient_axis_balance = 1.0
        params.ruplace_directional_local_gradient_axis_mapping = "cross_track"
        params.ruplace_directional_local_gradient_polarity = "repel"
        params.ruplace_directional_local_gradient_normalization = "joint"
        params.ruplace_directional_local_gradient_tail_guard = 1
        params.ruplace_directional_local_gradient_tail_metric = "max_p99"
        params.ruplace_directional_local_gradient_tail_tolerance = 0.0
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 3.0
        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        utilization = torch.ones(2, 3, 3)
        overflow = torch.stack((
            torch.tensor([
                [0.0, 1.0, 2.0],
                [0.0, 1.0, 2.0],
                [0.0, 1.0, 2.0],
            ]),
            torch.tensor([
                [0.0, 0.0, 0.0],
                [1.0, 1.0, 1.0],
                [2.0, 2.0, 2.0],
            ]),
        ))
        context.signal = lambda pos: CongestionSignal(
            utilization.max(dim=0).values,
            hv_overflow_map=overflow,
            hv_utilization_map=utilization,
        )
        context.sample_vector_field = lambda pos, gx, gy: (
            gx.reshape(-1)[:1], gy.reshape(-1)[:1]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = DirectionalLocalCongestionGradientPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        self.assertEqual(plugin.metrics["tail_guard_passed"], 1)
        context.iteration = 2
        self.assertFalse(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        self.assertEqual(plugin.metrics["tail_guard_fresh_observation"], 0)
        self.assertEqual(context.add_scaled_movable_gradient.call_count, 1)
        utilization[1, 1, 1] = 1.1
        context.iteration = 3
        context.proxy.last_iteration = 3
        self.assertFalse(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        self.assertEqual(plugin.metrics["tail_guard_passed"], 0)
        self.assertEqual(context.add_scaled_movable_gradient.call_count, 1)
        utilization[1, 1, 1] = 0.9
        context.iteration = 4
        context.proxy.last_iteration = 4
        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))
        self.assertEqual(context.add_scaled_movable_gradient.call_count, 2)

    def test_force_tail_guard_validates_contract(self):
        from dreamplace.ops.routability_opt.plugin_base import (
            CongestionSignal,
            RoutabilityPlugin,
        )

        context = Obj()
        context.iteration = 1
        context.proxy = Obj()
        context.proxy.last_iteration = 1
        params = Obj()
        params.ruplace_force_tail_guard = 1
        params.ruplace_force_tail_metric = "bad"
        plugin = RoutabilityPlugin(params, Obj(), Obj())
        signal = CongestionSignal(torch.ones(2, 2))
        with self.assertRaisesRegex(ValueError, "tail metric"):
            plugin.congestion_tail_gate(context, signal)

        params.ruplace_force_tail_metric = "max"
        params.ruplace_force_tail_tolerance = -0.1
        with self.assertRaisesRegex(ValueError, "tail tolerance"):
            plugin.congestion_tail_gate(context, signal)

        params.ruplace_force_tail_tolerance = 0.0
        with self.assertRaisesRegex(ValueError, "H/V utilization"):
            plugin.congestion_tail_gate(context, signal)

    def test_virtual_cell_midpoint_translates_both_movable_endpoints(self):
        from dreamplace.ops.routability_opt.plugins.virtual_cell import (
            virtual_net_node_gradients,
        )

        grad_x, grad_y, counts, eligible = virtual_net_node_gradients(
            torch.tensor([0.5, 1.5, 2.5, 2.5]),
            torch.tensor([0.5, 0.5, 1.5, 2.5]),
            torch.tensor([[0, 1], [2, 3]]),
            torch.tensor([0, 1, 2, 3]),
            torch.full((3, 3), 2.0),
            torch.zeros(3, 3),
            3,
            (0.0, 0.0, 3.0, 3.0),
        )

        self.assertEqual(eligible.item(), 1)
        self.assertTrue(torch.equal(grad_x, torch.tensor([1.0, 1.0, 0.0])))
        self.assertTrue(torch.equal(grad_y, torch.zeros(3)))
        self.assertTrue(torch.equal(counts, torch.tensor([1.0, 1.0, 0.0])))

    def test_virtual_cell_sum_reduction_accumulates_incident_net_forces(self):
        from dreamplace.ops.routability_opt.plugins.virtual_cell import (
            virtual_net_node_gradients,
        )

        args = (
            torch.tensor([0.5, 1.5, 0.5, 2.5]),
            torch.tensor([0.5, 0.5, 1.5, 1.5]),
            torch.tensor([[0, 1], [2, 3]]),
            torch.tensor([0, 1, 0, 2]),
            torch.full((3, 3), 2.0),
            torch.zeros(3, 3),
            3,
            (0.0, 0.0, 3.0, 3.0),
        )
        mean_x, _, counts, _ = virtual_net_node_gradients(*args, reduction="mean")
        sum_x, _, _, _ = virtual_net_node_gradients(*args, reduction="sum")

        self.assertEqual(counts[0].item(), 2.0)
        self.assertEqual(mean_x[0].item(), 1.0)
        self.assertEqual(sum_x[0].item(), 2.0)
        self.assertTrue(torch.equal(mean_x[1:], sum_x[1:]))

    def test_directional_virtual_cell_field_uses_cross_track_poisson_axes(self):
        from dreamplace.ops.routability_opt.plugins import directional_virtual_cell
        from dreamplace.ops.routability_opt.plugins.directional_virtual_cell import (
            directional_virtual_cell_field,
        )

        horizontal_potential = torch.tensor([
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
        ])
        vertical_potential = horizontal_potential.t().contiguous()
        with mock.patch.object(
            directional_virtual_cell,
            "poisson_potential",
            side_effect=[horizontal_potential, vertical_potential],
        ):
            (field_x, field_y), _, _ = directional_virtual_cell_field(
                torch.ones(3, 3),
                torch.ones(3, 3),
                threshold=0.0,
                power=1.0,
                smooth_radius=0,
                padding_mode="replicate",
            )

        self.assertTrue(torch.all(field_x > 0.0))
        self.assertTrue(torch.all(field_y > 0.0))

    def test_directional_virtual_cell_axis_balance_changes_cross_track_ratio(self):
        from dreamplace.ops.routability_opt.plugins import directional_virtual_cell
        from dreamplace.ops.routability_opt.plugins.directional_virtual_cell import (
            directional_virtual_cell_field,
        )

        horizontal_potential = torch.tensor([
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
        ])
        vertical_potential = horizontal_potential.t().contiguous()

        def field(balance):
            with mock.patch.object(
                directional_virtual_cell,
                "poisson_potential",
                side_effect=[horizontal_potential, vertical_potential],
            ):
                return directional_virtual_cell_field(
                    torch.ones(3, 3), torch.ones(3, 3),
                    threshold=0.0, power=1.0, smooth_radius=0,
                    padding_mode="replicate", axis_balance=balance,
                )[0]

        balanced_x, balanced_y = field(1.0)
        x_heavy, y_light = field(2.0)
        self.assertGreater(x_heavy.abs().mean(), balanced_x.abs().mean())
        self.assertLess(y_light.abs().mean(), balanced_y.abs().mean())

        with self.assertRaisesRegex(ValueError, "axis_balance"):
            field(0.0)

    def test_virtual_cell_plugin_uses_one_shared_midpoint_force(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins import virtual_cell
        from dreamplace.ops.routability_opt.plugins.virtual_cell import (
            VirtualCellNetMovingPlugin,
        )

        params = Obj()
        params.ruplace_virtual_cell_weight = 0.5
        params.ruplace_virtual_cell_apply_interval = 1
        params.ruplace_virtual_cell_threshold = 0.0
        params.ruplace_virtual_cell_power = 1.0
        params.ruplace_virtual_cell_smooth = 0
        params.ruplace_force_congestion_mode = "utilization"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 3.0
        data = Obj()
        data.flat_net2pin_start_map = torch.tensor([0, 2])
        data.flat_net2pin_map = torch.tensor([0, 1])
        data.net_mask_ignore_large_degrees = torch.tensor([1])
        data.pin2node_map = torch.tensor([0, 1])
        plugin = VirtualCellNetMovingPlugin(params, db, data)
        pos = torch.tensor([0.5, 1.5, 1.0, 1.0], requires_grad=True)
        context = Obj()
        context.iteration = 1
        context.signal = lambda value: CongestionSignal(
            utilization_map=torch.ones(3, 3)
        )
        context.pin_positions = lambda value: value

        def add_scaled(value, grad_x, grad_y, weight):
            value.grad = torch.cat((grad_x, grad_y)) * weight
            return {
                "reference_rms": 1.0,
                "field_rms": 1.0,
                "applied_scale": weight,
                "applied_ratio": weight,
            }

        context.add_scaled_movable_gradient = add_scaled
        potential = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0],
        ])
        with mock.patch.object(
            virtual_cell, "poisson_potential", return_value=potential
        ):
            changed = plugin.apply_gradient(pos, Obj(), context)

        self.assertTrue(changed)
        self.assertAlmostEqual(pos.grad[0].item(), pos.grad[1].item())
        self.assertGreater(pos.grad[0].item(), 0.0)
        self.assertTrue(torch.equal(pos.grad[2:], torch.zeros(2)))
        self.assertEqual(plugin.metrics["eligible_virtual_nets"], 1)
        self.assertEqual(plugin.metrics["active_nodes"], 2)

    def test_virtual_cell_validates_charge_controls(self):
        from dreamplace.ops.routability_opt.plugins.virtual_cell import (
            VirtualCellNetMovingPlugin,
        )

        params = Obj()
        params.ruplace_virtual_cell_weight = 0.5
        params.ruplace_virtual_cell_apply_interval = 1
        params.ruplace_virtual_cell_threshold = -0.1
        params.ruplace_virtual_cell_power = 1.0
        data = Obj()
        data.flat_net2pin_start_map = torch.tensor([0, 2])
        data.flat_net2pin_map = torch.tensor([0, 1])
        data.net_mask_ignore_large_degrees = torch.tensor([1])
        plugin = VirtualCellNetMovingPlugin(params, Obj(), data)
        context = Obj()
        context.iteration = 1
        with self.assertRaisesRegex(ValueError, "threshold"):
            plugin.apply_gradient(torch.zeros(4), Obj(), context)

        params.ruplace_virtual_cell_threshold = 0.8
        params.ruplace_virtual_cell_power = 0.0
        with self.assertRaisesRegex(ValueError, "power"):
            plugin.apply_gradient(torch.zeros(4), Obj(), context)

    def test_directional_path_field_uses_cross_track_axes(self):
        from dreamplace.ops.routability_opt.plugins.directional_path_spreading import (
            directional_cross_axis_field,
        )

        horizontal = torch.tensor([
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
            [0.0, 1.0, 2.0],
        ])
        vertical = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0],
        ])
        (field_x, field_y), _ = directional_cross_axis_field(
            horizontal, vertical, 0.0, 1.0, 0, "replicate"
        )
        self.assertTrue(torch.all(field_x > 0))
        self.assertTrue(torch.all(field_y > 0))

        (horizontal_x, horizontal_y), _ = directional_cross_axis_field(
            horizontal, vertical, 0.0, 1.0, 0, "replicate",
            mode="horizontal",
        )
        self.assertTrue(torch.equal(horizontal_x, torch.zeros_like(horizontal_x)))
        self.assertTrue(torch.all(horizontal_y > 0))

        (vertical_x, vertical_y), _ = directional_cross_axis_field(
            horizontal, vertical, 0.0, 1.0, 0, "replicate",
            mode="vertical",
        )
        self.assertTrue(torch.all(vertical_x > 0))
        self.assertTrue(torch.equal(vertical_y, torch.zeros_like(vertical_y)))

    def test_directional_path_spreading_translates_net_across_tracks(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_path_spreading import (
            DirectionalPathSpreadingPlugin,
        )

        params = Obj()
        params.ruplace_directional_path_spreading_weight = 0.5
        params.ruplace_directional_path_spreading_smooth = 0
        params.ruplace_directional_path_spreading_threshold = 0.0
        params.ruplace_directional_path_spreading_power = 1.0
        params.ruplace_directional_path_spreading_mode = "horizontal"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 3.0
        data = Obj()
        data.flat_net2pin_start_map = torch.tensor([0, 2])
        data.flat_net2pin_map = torch.tensor([0, 1])
        data.net_mask_ignore_large_degrees = torch.tensor([1])
        data.pin2node_map = torch.tensor([0, 1])
        plugin = DirectionalPathSpreadingPlugin(params, db, data)
        pos = torch.tensor([0.5, 1.5, 1.0, 1.0], requires_grad=True)
        context = Obj()
        context.iteration = 1
        context.signal = lambda value: CongestionSignal(
            utilization_map=torch.ones(3, 3),
            hv_utilization_map=torch.stack((
                torch.tensor([
                    [0.0, 1.0, 2.0],
                    [0.0, 1.0, 2.0],
                    [0.0, 1.0, 2.0],
                ]),
                torch.zeros(3, 3),
            )),
        )
        context.pin_positions = lambda value: value

        def add_scaled(value, grad_x, grad_y, weight):
            value.grad = torch.cat((grad_x, grad_y)) * weight
            return {
                "reference_rms": 1.0,
                "field_rms": 1.0,
                "applied_scale": weight,
                "applied_ratio": weight,
            }

        context.add_scaled_movable_gradient = add_scaled
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        self.assertTrue(torch.equal(pos.grad[:2], torch.zeros(2)))
        self.assertTrue(torch.all(pos.grad[2:] > 0))
        self.assertEqual(plugin.metrics["active_nets"], 1)
        self.assertEqual(plugin.metrics["active_nodes"], 2)
        self.assertEqual(plugin.metrics["field_x_norm"], 0.0)
        self.assertGreater(plugin.metrics["field_y_norm"], 0.0)

    def test_directional_path_field_rejects_invalid_controls(self):
        from dreamplace.ops.routability_opt.plugins.directional_path_spreading import (
            directional_cross_axis_field,
        )

        value = torch.ones(2, 2)
        with self.assertRaisesRegex(ValueError, "threshold"):
            directional_cross_axis_field(
                value, value, -0.1, 1.0, 0, "replicate"
            )
        with self.assertRaisesRegex(ValueError, "power"):
            directional_cross_axis_field(
                value, value, 0.0, 0.0, 0, "replicate"
            )
        with self.assertRaisesRegex(ValueError, "mode"):
            directional_cross_axis_field(
                value, value, 0.0, 1.0, 0, "replicate", mode="diagonal"
            )

    def test_directional_net_pressures_preserve_axis_identity(self):
        from dreamplace.ops.routability_opt.plugins.directional_net_contraction import (
            directional_net_pressures,
        )

        horizontal = torch.tensor([1.0, 3.0, 2.0, 100.0])
        vertical = torch.tensor([4.0, 2.0, 2.0, 100.0])
        active = torch.tensor([True, True, True, False])
        pressure_x, pressure_y, scale_x, scale_y = directional_net_pressures(
            horizontal, vertical, active, "max_hv", "absolute", 4.0
        )
        self.assertEqual(scale_x.item(), 1.0)
        self.assertEqual(scale_y.item(), 1.0)
        self.assertTrue(torch.equal(
            pressure_x, torch.tensor([0.0, 2.0, 1.0, 0.0])
        ))
        self.assertTrue(torch.equal(
            pressure_y, torch.tensor([3.0, 0.0, 1.0, 0.0])
        ))
        vertical_only, pressure_y, _, _ = directional_net_pressures(
            horizontal, vertical, active, "vertical", "absolute", 4.0
        )
        self.assertTrue(torch.equal(vertical_only, torch.zeros(4)))
        self.assertTrue(torch.equal(
            pressure_y, torch.tensor([3.0, 1.0, 1.0, 0.0])
        ))

    def test_directional_net_pressures_can_normalize_each_axis(self):
        from dreamplace.ops.routability_opt.plugins.directional_net_contraction import (
            directional_net_pressures,
        )

        horizontal = torch.tensor([1.0, 3.0])
        vertical = torch.tensor([10.0, 20.0])
        active = torch.ones(2, dtype=torch.bool)
        pressure_x, pressure_y, scale_x, scale_y = directional_net_pressures(
            horizontal, vertical, active, "both", "axis_mean", 4.0
        )
        self.assertEqual(scale_x.item(), 2.0)
        self.assertEqual(scale_y.item(), 15.0)
        self.assertTrue(torch.allclose(
            pressure_x, torch.tensor([0.0, 0.5])
        ))
        self.assertTrue(torch.allclose(
            pressure_y, torch.tensor([0.0, 1.0 / 3.0])
        ))
        _, _, shared_x, shared_y = directional_net_pressures(
            horizontal, vertical, active, "both", "design_mean", 4.0
        )
        self.assertEqual(shared_x.item(), 8.5)
        self.assertEqual(shared_y.item(), 8.5)

    def test_extreme_pin_subgradient_balances_each_net(self):
        from dreamplace.ops.routability_opt.plugins.directional_net_contraction import (
            extreme_pin_subgradient,
        )

        gradient = extreme_pin_subgradient(
            torch.tensor([0.0, 2.0, 2.0, 5.0, 5.0]),
            torch.tensor([0, 1, 2, 3, 4]),
            torch.tensor([0, 0, 0, 1, 1]),
            torch.tensor([3, 2]),
            torch.tensor([3.0, 4.0]),
        )
        self.assertTrue(torch.allclose(
            gradient, torch.tensor([-3.0, 1.5, 1.5, 0.0, 0.0])
        ))
        self.assertAlmostEqual(gradient[:3].sum().item(), 0.0)
        self.assertAlmostEqual(gradient[3:].sum().item(), 0.0)

    def test_directional_net_pressure_validation(self):
        from dreamplace.ops.routability_opt.plugins.directional_net_contraction import (
            directional_net_pressures,
        )

        score = torch.ones(2)
        active = torch.ones(2, dtype=torch.bool)
        with self.assertRaisesRegex(ValueError, "contraction_mode"):
            directional_net_pressures(
                score, score, active, "diagonal", "absolute", 2.0
            )
        with self.assertRaisesRegex(ValueError, "max_pressure"):
            directional_net_pressures(
                score, score, active, "both", "absolute", 0.0
            )
        with self.assertRaisesRegex(ValueError, "normalization"):
            directional_net_pressures(
                score, score, active, "both", "median", 2.0
            )

    def test_directional_net_contraction_isolates_vertical_gradient(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.directional_net_contraction import (
            DirectionalNetContractionPlugin,
        )

        params = Obj()
        params.ruplace_directional_net_contraction_weight = 0.5
        params.ruplace_directional_net_contraction_apply_interval = 1
        params.ruplace_directional_net_contraction_decay = 1.0
        params.ruplace_directional_net_contraction_min_ratio = 0.0
        params.ruplace_directional_net_contraction_mode = "vertical"
        params.ruplace_directional_net_contraction_smooth = 0
        params.ruplace_directional_net_contraction_score_mode = "pin_mean"
        params.ruplace_directional_net_contraction_bbox_power = 4.0
        params.ruplace_directional_net_contraction_normalization = "absolute"
        params.ruplace_directional_net_contraction_max_pressure = 2.0
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        data = Obj()
        data.flat_net2pin_start_map = torch.tensor([0, 2])
        data.flat_net2pin_map = torch.tensor([0, 1])
        data.net_mask_ignore_large_degrees = torch.tensor([1])
        data.net_weights = torch.ones(1)
        data.pin2node_map = torch.tensor([0, 1])
        plugin = DirectionalNetContractionPlugin(params, db, data)

        pos = torch.tensor([0.0, 2.0, 0.0, 2.0], requires_grad=True)
        context = Obj()
        context.iteration = 1
        context.signal = lambda value: CongestionSignal(
            utilization_map=torch.ones(2, 2),
            hv_utilization_map=torch.stack((
                torch.ones(2, 2), torch.full((2, 2), 3.0),
            )),
        )
        context.pin_positions = lambda value: value

        def add_scaled(value, grad_x, grad_y, weight):
            value.grad = torch.cat((grad_x, grad_y)) * weight
            field_rms = torch.sqrt((grad_x.square() + grad_y.square()).mean())
            return {
                "reference_rms": 1.0,
                "field_rms": float(field_rms.item()),
                "applied_scale": weight,
                "applied_ratio": float(weight * field_rms.item()),
            }

        context.add_scaled_movable_gradient = add_scaled
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        self.assertTrue(torch.equal(pos.grad[:2], torch.zeros(2)))
        self.assertTrue(torch.allclose(pos.grad[2:], torch.tensor([-1.0, 1.0])))
        self.assertEqual(plugin.metrics["horizontal_active_nets"], 0)
        self.assertEqual(plugin.metrics["vertical_active_nets"], 1)

    def test_net_weight_direction_selection_and_smoothing(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            select_congestion_map,
            smooth_congestion_map,
        )

        aggregate = torch.zeros(3, 3)
        horizontal = torch.tensor([
            [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0],
        ])
        vertical = torch.tensor([
            [3.0, 2.0, 1.0], [3.0, 2.0, 1.0], [3.0, 2.0, 1.0],
        ])
        hv = torch.stack((horizontal, vertical))
        self.assertTrue(torch.equal(
            select_congestion_map(aggregate, hv, "max_hv"),
            torch.maximum(horizontal, vertical),
        ))
        self.assertTrue(torch.equal(
            select_congestion_map(aggregate, hv, "horizontal"), horizontal
        ))
        with self.assertRaisesRegex(ValueError, "requires H/V"):
            select_congestion_map(aggregate, None, "max_hv")
        with self.assertRaisesRegex(ValueError, "direction_mode"):
            select_congestion_map(aggregate, hv, "diagonal")

        impulse = torch.zeros(3, 3)
        impulse[1, 1] = 9.0
        smoothed = smooth_congestion_map(impulse, 1)
        self.assertEqual(tuple(smoothed.shape), (3, 3))
        self.assertAlmostEqual(smoothed[1, 1].item(), 1.0)
        with self.assertRaisesRegex(ValueError, "nonnegative integer"):
            smooth_congestion_map(impulse, 0.5)

    def test_net_congestion_score_modes_cover_routing_corridor(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            net_congestion_scores,
        )

        utilization = torch.tensor([
            [1.0, 100.0, 1.0],
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
        ])
        pin_bx = torch.tensor([0, 2])
        pin_by = torch.tensor([0, 2])
        flat_pins = torch.tensor([0, 1])
        net_ids = torch.tensor([0, 0])
        degrees = torch.tensor([2, 0])

        pin_mean = net_congestion_scores(
            utilization, pin_bx, pin_by, flat_pins, net_ids, degrees,
            "pin_mean",
        )
        bbox_mean = net_congestion_scores(
            utilization, pin_bx, pin_by, flat_pins, net_ids, degrees,
            "bbox_mean",
        )
        bbox_pmean = net_congestion_scores(
            utilization, pin_bx, pin_by, flat_pins, net_ids, degrees,
            "bbox_pmean", bbox_power=4.0,
        )

        self.assertTrue(torch.allclose(pin_mean, torch.tensor([1.0, 0.0])))
        self.assertTrue(torch.allclose(bbox_mean, torch.tensor([12.0, 0.0])))
        expected_peak = ((100.0 ** 4 + 8.0) / 9.0) ** 0.25
        self.assertAlmostEqual(bbox_pmean[0].item(), expected_peak, places=4)
        self.assertEqual(bbox_pmean[1].item(), 0.0)

    def test_net_congestion_scores_reject_unknown_mode(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            net_congestion_scores,
        )

        with self.assertRaisesRegex(ValueError, "score_mode"):
            net_congestion_scores(
                torch.ones(1, 1), torch.zeros(1, dtype=torch.long),
                torch.zeros(1, dtype=torch.long), torch.zeros(1, dtype=torch.long),
                torch.zeros(1, dtype=torch.long), torch.ones(1, dtype=torch.long),
                "unknown",
            )
        with self.assertRaisesRegex(ValueError, "bbox_power"):
            net_congestion_scores(
                torch.ones(1, 1), torch.zeros(1, dtype=torch.long),
                torch.zeros(1, dtype=torch.long), torch.zeros(1, dtype=torch.long),
                torch.zeros(1, dtype=torch.long), torch.ones(1, dtype=torch.long),
                "bbox_pmean", bbox_power=0.0,
            )

    def test_design_mean_net_weighting_is_scale_invariant(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            net_weight_ratios,
        )

        degrees = torch.ones(3, dtype=torch.long)
        scores = torch.tensor([1.0, 2.0, 3.0])
        ratios, scale = net_weight_ratios(
            scores, degrees, gamma=0.5, max_ratio=3.0,
            normalization="design_mean",
        )
        scaled_ratios, scaled_scale = net_weight_ratios(
            scores * 100.0, degrees, gamma=0.5, max_ratio=3.0,
            normalization="design_mean",
        )

        self.assertTrue(torch.allclose(ratios, scaled_ratios))
        self.assertAlmostEqual(scale.item(), 2.0)
        self.assertAlmostEqual(scaled_scale.item(), 200.0)
        self.assertTrue(torch.allclose(
            ratios, torch.tensor([1.0, 1.0, 1.25])
        ))

    def test_net_weighting_ignores_nets_masked_from_wirelength(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            net_weight_ratios,
        )

        scores = torch.tensor([1.0, 3.0, 1000.0])
        active_nets = torch.tensor([True, True, False])
        ratios, scale = net_weight_ratios(
            scores, active_nets, gamma=0.5, max_ratio=3.0,
            normalization="design_mean",
        )

        self.assertAlmostEqual(scale.item(), 2.0)
        self.assertTrue(torch.allclose(
            ratios, torch.tensor([1.0, 1.25, 1.0])
        ))

    def test_net_relaxation_reduces_only_active_congested_nets(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            net_relaxation_ratios,
        )

        scores = torch.tensor([1.0, 3.0, 1000.0])
        active_nets = torch.tensor([True, True, False])
        ratios, scale = net_relaxation_ratios(
            scores, active_nets, gamma=0.5, min_ratio=0.4,
            normalization="absolute",
        )

        self.assertEqual(scale.item(), 1.0)
        self.assertTrue(torch.allclose(
            ratios, torch.tensor([1.0, 0.5, 1.0])
        ))

    def test_net_relaxation_uses_independent_parameters(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.net_relaxation import (
            CongestionNetRelaxationPlugin,
        )

        params = Obj()
        params.ruplace_net_relaxation_phase = "pre_objective"
        params.ruplace_net_relaxation_freq = 1
        params.ruplace_net_relaxation_gamma = 0.5
        params.ruplace_net_relaxation_min_weight = 0.4
        params.ruplace_net_relaxation_normalization = "absolute"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        data = Obj()
        data.net_weights = torch.ones(1)
        data.flat_net2pin_start_map = torch.tensor([0, 1])
        data.flat_net2pin_map = torch.tensor([0])
        data.net_mask_ignore_large_degrees = torch.tensor([1])
        context = Obj()
        context.iteration = 1
        context.signal = lambda pos: CongestionSignal(torch.full((2, 2), 3.0))
        context.pin_positions = lambda pos: torch.tensor([1.0, 1.0])
        plugin = CongestionNetRelaxationPlugin(params, db, data)

        self.assertTrue(plugin.prepare_objective(torch.zeros(2), Obj(), context))
        self.assertAlmostEqual(data.net_weights.item(), 0.5)
        self.assertEqual(plugin.metrics["ratio_limit"], 0.4)
        self.assertEqual(plugin.metrics["min_ratio"], 0.5)
        self.assertEqual(plugin.metrics["max_ratio"], 0.5)

    def test_rudy_feedback_does_not_consume_updated_objective_weights(self):
        from dreamplace.ops.routability_opt.proxy import RudyProxy

        class FakeRudy:
            def __init__(self, **kwargs):
                self.net_weights = kwargs["net_weights"]

            def __call__(self, pin_pos):
                return self.net_weights.sum().reshape(1, 1)

        params = Obj()
        params.deterministic_flag = 1
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 1.0
        db.num_routing_grids_x = db.num_routing_grids_y = 1
        db.unit_horizontal_capacity = db.unit_vertical_capacity = 1.0
        data = Obj()
        data.net_weights = torch.tensor([1.0, 1.0])
        data.flat_net2pin_start_map = torch.tensor([0, 1, 2])
        data.flat_net2pin_map = torch.tensor([0, 1])
        data.initial_horizontal_utilization_map = None
        data.initial_vertical_utilization_map = None
        ops = Obj()
        ops.pin_pos_op = lambda pos: pos
        proxy = RudyProxy(
            params, db, data, ops, refresh_interval=1,
            rudy_factory=FakeRudy,
        )

        data.net_weights.mul_(10.0)
        signal = proxy.evaluate(torch.zeros(4), iteration=1)

        self.assertEqual(signal.utilization_map.item(), 2.0)
        self.assertTrue(signal.metrics["frozen_input_net_weights"])
        self.assertTrue(torch.equal(proxy.input_net_weights, torch.ones(2)))

    def test_net_weighting_rejects_invalid_mode_and_limits(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            net_relaxation_ratios,
            net_weight_ratios,
        )

        scores = torch.ones(1)
        degrees = torch.ones(1, dtype=torch.long)
        with self.assertRaisesRegex(ValueError, "normalization"):
            net_weight_ratios(scores, degrees, 0.25, 3.0, "unknown")
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            net_weight_ratios(scores, degrees, -0.1, 3.0, "absolute")
        with self.assertRaisesRegex(ValueError, "at least 1"):
            net_weight_ratios(scores, degrees, 0.25, 0.5, "absolute")
        with self.assertRaisesRegex(ValueError, "in \(0, 1\]"):
            net_relaxation_ratios(scores, degrees, 0.25, 0.0, "absolute")

    def test_duplicate_plugins_are_rejected(self):
        from dreamplace.ops.routability_opt.plugins import build_plugins

        params = Obj()
        params.ruplace_plugins = ["local_gradient", "local_gradient"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_plugins(params, Obj(), Obj())

    def test_net_weight_mutators_are_mutually_exclusive(self):
        from dreamplace.ops.routability_opt.plugins import build_plugins

        params = Obj()
        params.ruplace_plugins = ["net_weighting", "net_relaxation"]
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            build_plugins(params, Obj(), Obj())

    def test_every_registered_plugin_has_literature_lineage(self):
        from dreamplace.ops.routability_opt.plugins import PLUGIN_REGISTRY

        document = (ROOT / "docs/routability_optimization_lab.md").read_text()
        matrix = document.split("## Literature-to-plugin matrix", 1)[1].split(
            "## Screened works outside the current implementation scope", 1
        )[0]
        for name in PLUGIN_REGISTRY:
            self.assertIn("`%s`" % name, matrix)

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
        context.iteration = 1
        context.signal = lambda pos: CongestionSignal(torch.zeros(2, 2))
        context.sample_vector_field = lambda pos, gx, gy: (torch.zeros(1), torch.zeros(1))
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 0.0,
            "applied_scale": 0.0,
            "applied_ratio": 0.0,
        })
        plugin = LocalCongestionGradientPlugin(params, db, Obj())

        changed = plugin.apply_gradient(torch.zeros(2), Obj(), context)

        self.assertFalse(changed)

    def test_placeobj_prepares_plugins_before_objective_backward(self):
        tree = ast.parse((ROOT / "dreamplace" / "PlaceObj.py").read_text())
        place_obj = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PlaceObj"
        )
        function = next(
            node for node in place_obj.body
            if isinstance(node, ast.FunctionDef) and node.name == "obj_and_grad_fn"
        )
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]

        def call_name(node):
            if isinstance(node.func, ast.Attribute):
                return node.func.attr
            if isinstance(node.func, ast.Name):
                return node.func.id
            return None

        prepare_line = next(
            node.lineno for node in calls if call_name(node) == "prepare_objective"
        )
        objective_line = next(
            node.lineno for node in calls if call_name(node) == "obj_fn"
        )
        backward_line = next(
            node.lineno for node in calls if call_name(node) == "backward"
        )
        precondition_line = next(
            node.lineno for node in calls if call_name(node) == "precondition_op"
        )
        apply_line = next(
            node.lineno for node in calls if call_name(node) == "apply_gradient"
        )
        commit_line = next(
            node.lineno for node in calls if call_name(node) == "commit_post_gradient"
        )
        self.assertLess(prepare_line, objective_line)
        self.assertLess(objective_line, backward_line)
        self.assertLess(backward_line, apply_line)
        self.assertLess(apply_line, precondition_line)
        self.assertLess(precondition_line, commit_line)

    def test_net_weight_phase_preserves_legacy_post_gradient_mode(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            CongestionNetWeightingPlugin,
        )

        plugin = CongestionNetWeightingPlugin.__new__(CongestionNetWeightingPlugin)
        plugin.params = Obj()
        plugin.params.ruplace_net_weight_phase = "post_gradient"
        plugin._update_weights = mock.Mock(return_value=True)

        self.assertFalse(plugin.objective_phase_enabled())
        self.assertTrue(plugin.gradient_phase_enabled())
        self.assertFalse(plugin.prepare_objective(Obj(), Obj(), Obj()))
        self.assertTrue(plugin.apply_gradient(Obj(), Obj(), Obj()))
        plugin._update_weights.assert_called_once_with(
            mock.ANY, mock.ANY, defer=True
        )

        plugin.params.ruplace_net_weight_phase = "pre_objective"
        plugin._update_weights.reset_mock()
        self.assertTrue(plugin.objective_phase_enabled())
        self.assertFalse(plugin.gradient_phase_enabled())
        self.assertTrue(plugin.prepare_objective(Obj(), Obj(), Obj()))
        self.assertFalse(plugin.apply_gradient(Obj(), Obj(), Obj()))
        plugin._update_weights.assert_called_once_with(mock.ANY, mock.ANY)

    def test_net_weight_phase_controls_current_or_next_objective(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            CongestionNetWeightingPlugin,
        )

        def build_plugin(phase):
            params = Obj()
            params.ruplace_net_weight_phase = phase
            params.ruplace_net_weight_freq = 1
            params.ruplace_net_weight_gamma = 0.25
            params.ruplace_net_weight_max = 3.0
            params.ruplace_net_weight_normalization = "absolute"
            db = Obj()
            db.routing_grid_xl = db.routing_grid_yl = 0.0
            db.routing_grid_xh = db.routing_grid_yh = 2.0
            data = Obj()
            data.net_weights = torch.ones(1)
            data.flat_net2pin_start_map = torch.tensor([0, 1])
            data.flat_net2pin_map = torch.tensor([0])
            data.net_mask_ignore_large_degrees = torch.tensor([1])
            context = Obj()
            context.iteration = 1
            context.signal = lambda pos: CongestionSignal(torch.full((2, 2), 2.0))
            context.pin_positions = lambda pos: torch.tensor(
                [1.0, 1.0], dtype=pos.dtype, device=pos.device
            )
            return CongestionNetWeightingPlugin(params, db, data), data, context

        def objective_and_gradient(data, pos):
            if pos.grad is not None:
                pos.grad.zero_()
            objective = data.net_weights[0] * pos[0].square()
            objective.backward()
            return objective.item(), pos.grad[0].item()

        pos = torch.tensor([2.0, 0.0], requires_grad=True)
        pre_plugin, pre_data, pre_context = build_plugin("pre_objective")
        self.assertTrue(pre_plugin.prepare_objective(pos, Obj(), pre_context))
        self.assertEqual(objective_and_gradient(pre_data, pos), (5.0, 5.0))
        self.assertFalse(pre_plugin.apply_gradient(pos, Obj(), pre_context))

        post_plugin, post_data, post_context = build_plugin("post_gradient")
        self.assertEqual(objective_and_gradient(post_data, pos), (4.0, 4.0))
        self.assertTrue(post_plugin.apply_gradient(pos, Obj(), post_context))
        self.assertEqual(objective_and_gradient(post_data, pos), (4.0, 4.0))
        self.assertTrue(post_plugin.commit_post_gradient(
            pos, Obj(), post_context
        ))
        self.assertEqual(objective_and_gradient(post_data, pos), (5.0, 5.0))

    def test_net_weight_gamma_anneals_with_floor(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            CongestionNetWeightingPlugin,
        )

        params = Obj()
        params.ruplace_net_weight_phase = "pre_objective"
        params.ruplace_net_weight_freq = 1
        params.ruplace_net_weight_gamma = 0.5
        params.ruplace_net_weight_decay = 0.5
        params.ruplace_net_weight_min_ratio = 0.4
        params.ruplace_net_weight_max = 3.0
        params.ruplace_net_weight_normalization = "absolute"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        data = Obj()
        data.net_weights = torch.ones(1)
        data.flat_net2pin_start_map = torch.tensor([0, 1])
        data.flat_net2pin_map = torch.tensor([0])
        data.net_mask_ignore_large_degrees = torch.tensor([1])
        context = Obj()
        context.iteration = 1
        context.signal = lambda pos: CongestionSignal(torch.full((2, 2), 2.0))
        context.pin_positions = lambda pos: torch.tensor([1.0, 1.0])
        plugin = CongestionNetWeightingPlugin(params, db, data)

        self.assertTrue(plugin.prepare_objective(torch.zeros(2), Obj(), context))
        self.assertAlmostEqual(data.net_weights.item(), 1.5)
        self.assertEqual(plugin.metrics["weight_update_index"], 0)
        context.iteration = 2
        self.assertTrue(plugin.prepare_objective(torch.zeros(2), Obj(), context))
        self.assertAlmostEqual(data.net_weights.item(), 1.25)
        self.assertAlmostEqual(plugin.metrics["effective_gamma"], 0.25)
        context.iteration = 3
        self.assertTrue(plugin.prepare_objective(torch.zeros(2), Obj(), context))
        self.assertAlmostEqual(data.net_weights.item(), 1.2)
        self.assertAlmostEqual(plugin.metrics["gamma_multiplier"], 0.4)

    def test_pipeline_records_objective_attempts_and_activations(self):
        from dreamplace.ops.routability_opt.pipeline import RoutabilityOptimizationPipeline
        from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin

        class PreparingPlugin(RoutabilityPlugin):
            name = "preparing"

            def prepare_objective(self, pos, model, context):
                self.metrics = {"prepared": 1}
                return True

        params = Obj()
        params.ruplace_plugins = ["preparing"]
        params.ruplace_plugin_start_overflow = 1.0
        db = Obj()
        plugin = PreparingPlugin(params, db, Obj())
        with mock.patch(
            "dreamplace.ops.routability_opt.pipeline.build_congestion_proxy",
            return_value=Obj(),
        ), mock.patch(
            "dreamplace.ops.routability_opt.pipeline.build_plugins",
            return_value=[plugin],
        ):
            pipeline = RoutabilityOptimizationPipeline(params, db, Obj(), Obj())
        model = Obj()
        model.overflow = torch.tensor([0.5])

        self.assertTrue(pipeline.prepare_objective(torch.zeros(2), model))
        metrics = pipeline.metrics()
        self.assertEqual(metrics["pipeline"]["objective_calls"], 1)
        self.assertEqual(metrics["pipeline"]["objective_gate_skips"], 0)
        self.assertEqual(metrics["plugins"]["preparing"]["objective_attempts"], 1)
        self.assertEqual(metrics["plugins"]["preparing"]["objective_activations"], 1)

    def test_relative_force_matches_raw_placement_gradient_rms_ratio(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.utils import vector_field_rms

        params = Obj()
        params.ruplace_force_scale_mode = "relative"
        params.ruplace_force_max_ratio = 0.25
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        context = PluginContext(params, db, Obj(), Obj(), Obj())
        pos = torch.zeros(4, requires_grad=True)
        pos.grad = torch.tensor([3.0, 0.0, 4.0, 0.0])
        raw = pos.grad.clone()
        context.begin_gradient(pos)

        metrics = context.add_scaled_movable_gradient(
            pos, torch.tensor([1.0, 1.0]), torch.tensor([1.0, -1.0]), 0.1
        )

        applied = pos.grad - raw
        applied_rms = vector_field_rms(applied[:2], applied[2:])
        raw_rms = vector_field_rms(raw[:2], raw[2:])
        self.assertAlmostEqual((applied_rms / raw_rms).item(), 0.1, places=6)
        self.assertAlmostEqual(metrics["applied_ratio"], 0.1, places=6)

    def test_routeforce_uses_movable_relative_scaling(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.routeforce import RouteForcePlugin

        params = Obj()
        params.ruplace_admm_apply_freq = 1
        params.ruplace_admm_route_freq = 5
        params.ruplace_admm_weight = 0.1
        params.ruplace_admm_weight_decay = 1.0
        params.ruplace_admm_min_weight = 0.0
        params.ruplace_admm_grad_clip_norm = 0.0
        params.ruplace_admm_scale_mode = "relative"
        params.ruplace_admm_max_ratio = 0.25
        db = Obj()
        db.num_nodes = 3
        db.num_movable_nodes = 2
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = None
        backend.admm_gradient = mock.Mock(return_value=torch.tensor([
            1.0, 1.0, 1000.0, 1.0, -1.0, 1000.0,
        ]))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1
        pos = torch.zeros(6, requires_grad=True)
        pos.grad = torch.tensor([3.0, 0.0, 99.0, 4.0, 0.0, 99.0])
        original = pos.grad.clone()
        context.begin_gradient(pos)
        plugin = RouteForcePlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))

        self.assertEqual(pos.grad[2].item(), original[2].item())
        self.assertEqual(pos.grad[5].item(), original[5].item())
        self.assertAlmostEqual(plugin.metrics["applied_ratio"], 0.1, places=6)
        backend.admm_gradient.assert_called_once_with(pos, refresh=True)

        backend.last_route = object()
        backend.admm_gradient.reset_mock()
        context.iteration = 2
        context.begin_gradient(pos)
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        backend.admm_gradient.assert_called_once_with(pos, refresh=False)

        backend.admm_gradient.reset_mock()
        context.iteration = 5
        context.begin_gradient(pos)
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        backend.admm_gradient.assert_called_once_with(pos, refresh=True)

    def test_routeforce_preserves_xplace_descent_direction(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.routeforce import RouteForcePlugin

        params = Obj()
        params.ruplace_admm_apply_freq = 1
        params.ruplace_admm_route_freq = 1
        params.ruplace_admm_weight = 1.0
        params.ruplace_admm_weight_decay = 1.0
        params.ruplace_admm_min_weight = 0.0
        params.ruplace_admm_grad_clip_norm = 0.0
        params.ruplace_admm_scale_mode = "absolute"
        params.ruplace_admm_max_ratio = 1.0
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = object()
        # Xplace's ADMM kernel gives a congested segment's left endpoint a
        # negative x derivative and its right endpoint a positive derivative.
        backend.admm_gradient = mock.Mock(return_value=torch.tensor([
            -2.0, 2.0, 0.0, 0.0,
        ]))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1
        pos = torch.tensor([0.0, 10.0, 0.0, 0.0], requires_grad=True)
        pos.grad = torch.zeros_like(pos)
        context.begin_gradient(pos)

        plugin = RouteForcePlugin(params, db, Obj())
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))

        self.assertEqual(pos.grad.tolist(), [-2.0, 2.0, 0.0, 0.0])
        next_pos = pos.detach() - 0.25 * pos.grad
        self.assertLess(next_pos[1] - next_pos[0], pos[1] - pos[0])

    def test_routed_overflow_contraction_separates_directional_axes(self):
        from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter

        adapter = XplaceGGRAdapter.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.device = torch.device("cpu")
        adapter.x_movable_end = adapter.x_num_nodes = 2
        adapter.node2pin_list = torch.tensor([0, 1])
        adapter.node2pin_list_end = torch.tensor([0, 1, 2])
        adapter.dp_movable_ids = torch.tensor([0, 1])
        adapter.x_movable_ids = torch.tensor([0, 1])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 2
        adapter._scaled_xplace_centers = mock.Mock(return_value=torch.tensor([
            [1.0, 2.0], [3.0, 4.0]
        ]))
        routeforce = Obj()
        routeforce.admm_route_grad = mock.Mock(side_effect=(
            torch.tensor([[1.0, 99.0], [2.0, 99.0]]),
            torch.tensor([[88.0, 3.0], [88.0, 4.0]]),
        ))
        route = Obj()
        route.routeforce = routeforce
        route.overflow_map = torch.tensor([[0.2, 0.3]])
        route.hv_overflow_map = torch.tensor([
            [[0.2, 0.0]],
            [[0.0, 0.3]],
        ])
        route.metrics = {"num_ovfl_nets": 7}
        adapter.last_route = route

        grad, metrics = adapter.routed_overflow_contraction_gradient(
            torch.zeros(4),
            mode="directional",
            overflow_threshold=0.1,
            overflow_exponent=2.0,
            max_wire_span=1,
            distance_weighting="inverse_sqrt",
        )

        self.assertTrue(torch.equal(grad, torch.tensor([1.0, 2.0, 3.0, 4.0])))
        self.assertEqual(routeforce.admm_route_grad.call_count, 2)
        horizontal_call, vertical_call = routeforce.admm_route_grad.call_args_list
        self.assertTrue(torch.allclose(
            horizontal_call.args[0], torch.tensor([[0.01, 0.0]])
        ))
        self.assertTrue(torch.allclose(
            vertical_call.args[0], torch.tensor([[0.0, 0.04]])
        ))
        self.assertTrue(torch.equal(
            horizontal_call.args[2], torch.tensor([1.0, 1.0, 0.0, 0.0])
        ))
        self.assertEqual(horizontal_call.args[8], 0.0)
        self.assertTrue(torch.equal(
            horizontal_call.args[5], horizontal_call.args[6]
        ))
        self.assertEqual(metrics["overflow_net_count"], 7)
        self.assertEqual(metrics["horizontal_active_bins"], 1)
        self.assertEqual(metrics["vertical_active_bins"], 1)
        self.assertEqual(metrics["contraction_mode"], "directional")
        self.assertEqual(metrics["matching_contraction_scale"], 1.0)
        self.assertEqual(metrics["smoothing_radius"], 0)
        self.assertEqual(metrics["smoothing_padding"], "replicate")

    def test_routed_overflow_contraction_replicate_smoothing(self):
        from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter

        adapter = XplaceGGRAdapter.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.device = torch.device("cpu")
        adapter.x_movable_end = adapter.x_num_nodes = 1
        adapter.node2pin_list = torch.tensor([0])
        adapter.node2pin_list_end = torch.tensor([0, 1])
        adapter.dp_movable_ids = torch.tensor([0])
        adapter.x_movable_ids = torch.tensor([0])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 1
        adapter._scaled_xplace_centers = mock.Mock(return_value=torch.tensor([
            [1.0, 2.0]
        ]))
        routeforce = Obj()
        routeforce.admm_route_grad = mock.Mock(side_effect=(
            torch.zeros((1, 2)),
            torch.zeros((1, 2)),
        ))
        route = Obj()
        route.routeforce = routeforce
        route.overflow_map = torch.zeros((3, 3))
        route.hv_overflow_map = torch.zeros((2, 3, 3))
        route.hv_overflow_map[0, 0, 0] = 9.0
        route.hv_overflow_map[1, 1, 1] = 9.0
        route.metrics = {"num_ovfl_nets": 1}
        adapter.last_route = route

        _, metrics = adapter.routed_overflow_contraction_gradient(
            torch.zeros(2),
            mode="directional",
            smoothing_radius=1,
            smoothing_padding="replicate",
        )

        horizontal_call, vertical_call = routeforce.admm_route_grad.call_args_list
        self.assertTrue(torch.equal(
            horizontal_call.args[0],
            torch.tensor([[4.0, 2.0, 0.0], [2.0, 1.0, 0.0], [0.0, 0.0, 0.0]]),
        ))
        self.assertTrue(torch.equal(
            vertical_call.args[0], torch.ones((3, 3))
        ))
        self.assertEqual(metrics["horizontal_active_bins"], 4)
        self.assertEqual(metrics["vertical_active_bins"], 9)
        self.assertEqual(metrics["smoothing_radius"], 1)
        self.assertEqual(metrics["smoothing_padding_id"], 1)

    def test_routed_overflow_contraction_blends_utilization_pressure(self):
        from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter

        adapter = XplaceGGRAdapter.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.device = torch.device("cpu")
        adapter.x_movable_end = adapter.x_num_nodes = 1
        adapter.node2pin_list = torch.tensor([0])
        adapter.node2pin_list_end = torch.tensor([0, 1])
        adapter.dp_movable_ids = torch.tensor([0])
        adapter.x_movable_ids = torch.tensor([0])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 1
        adapter._scaled_xplace_centers = mock.Mock(return_value=torch.tensor([
            [1.0, 2.0]
        ]))
        routeforce = Obj()
        routeforce.admm_route_grad = mock.Mock(side_effect=(
            torch.zeros((1, 2)),
            torch.zeros((1, 2)),
        ))
        route = Obj()
        route.routeforce = routeforce
        route.overflow_map = torch.zeros((1, 2))
        route.utilization_map = torch.tensor([[1.0, 0.5]])
        route.hv_overflow_map = torch.zeros((2, 1, 2))
        route.hv_utilization_map = torch.tensor([
            [[1.0, 0.5]],
            [[0.5, 1.0]],
        ])
        route.metrics = {"num_ovfl_nets": 1}
        adapter.last_route = route

        _, metrics = adapter.routed_overflow_contraction_gradient(
            torch.zeros(2),
            mode="directional",
            utilization_pressure_scale=2.0,
            utilization_threshold=0.75,
        )

        horizontal_call, vertical_call = routeforce.admm_route_grad.call_args_list
        self.assertTrue(torch.equal(
            horizontal_call.args[0], torch.tensor([[0.5, 0.0]])
        ))
        self.assertTrue(torch.equal(
            vertical_call.args[0], torch.tensor([[0.0, 0.5]])
        ))
        self.assertEqual(metrics["horizontal_pressure_active_bins"], 1)
        self.assertEqual(metrics["vertical_pressure_active_bins"], 1)
        self.assertEqual(metrics["utilization_pressure_scale"], 2.0)
        self.assertEqual(metrics["utilization_threshold"], 0.75)

    def test_routed_overflow_contraction_allows_pure_orthogonal_response(self):
        from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter

        adapter = XplaceGGRAdapter.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.device = torch.device("cpu")
        adapter.x_movable_end = adapter.x_num_nodes = 2
        adapter.node2pin_list = torch.tensor([0, 1])
        adapter.node2pin_list_end = torch.tensor([0, 1, 2])
        adapter.dp_movable_ids = torch.tensor([0, 1])
        adapter.x_movable_ids = torch.tensor([0, 1])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 2
        adapter._scaled_xplace_centers = mock.Mock(return_value=torch.tensor([
            [1.0, 2.0], [3.0, 4.0]
        ]))
        routeforce = Obj()
        routeforce.admm_route_grad = mock.Mock(side_effect=(
            torch.tensor([[1.0, 10.0], [2.0, 20.0]]),
            torch.tensor([[30.0, 3.0], [40.0, 4.0]]),
        ))
        route = Obj()
        route.routeforce = routeforce
        route.overflow_map = torch.tensor([[0.2, 0.3]])
        route.hv_overflow_map = torch.tensor([
            [[0.2, 0.0]],
            [[0.0, 0.3]],
        ])
        route.metrics = {"num_ovfl_nets": 7}
        adapter.last_route = route

        grad, metrics = adapter.routed_overflow_contraction_gradient(
            torch.zeros(4),
            mode="directional",
            matching_contraction_scale=0.0,
            orthogonal_spread_scale=1.0,
        )

        self.assertTrue(torch.equal(
            grad, torch.tensor([-30.0, -40.0, -10.0, -20.0])
        ))
        self.assertEqual(metrics["matching_contraction_scale"], 0.0)
        self.assertEqual(metrics["orthogonal_spread_scale"], 1.0)

    def test_routed_overflow_contraction_rejects_invalid_controls(self):
        from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter

        adapter = XplaceGGRAdapter.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = object()
        values = (
            ({"mode": "diagonal"}, "mode"),
            ({"overflow_threshold": -0.1}, "threshold"),
            ({"overflow_threshold": float("nan")}, "threshold"),
            ({"overflow_exponent": 0.0}, "exponent"),
            ({"overflow_exponent": float("inf")}, "exponent"),
            ({"max_wire_span": -1}, "span"),
            ({"distance_weighting": "linear"}, "distance weighting"),
            ({"matching_contraction_scale": -0.1}, "matching scale"),
            ({"matching_contraction_scale": float("inf")}, "matching scale"),
            ({"orthogonal_spread_scale": -0.1}, "orthogonal spread"),
            ({"orthogonal_spread_scale": float("inf")}, "orthogonal spread"),
            ({"smoothing_radius": -1}, "smoothing radius"),
            ({"smoothing_padding": "reflect"}, "smoothing padding"),
            ({"utilization_pressure_scale": -0.1}, "pressure scale"),
            ({"utilization_pressure_scale": float("inf")}, "pressure scale"),
            ({"utilization_threshold": -0.1}, "utilization threshold"),
            ({"utilization_threshold": float("nan")}, "utilization threshold"),
            ({"utilization_exponent": 0.0}, "utilization exponent"),
            ({"utilization_exponent": float("inf")}, "utilization exponent"),
        )
        for kwargs, message in values:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, message):
                    adapter.routed_overflow_contraction_gradient(
                        torch.zeros(2), **kwargs
                    )

    def test_routed_overflow_contraction_plugin_forwards_and_scales(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.routed_overflow_net_contraction import (
            RoutedOverflowNetContractionPlugin,
        )

        params = Obj()
        params.ruplace_routed_overflow_net_contraction_apply_interval = 2
        params.ruplace_routed_overflow_net_contraction_decay = 0.5
        params.ruplace_routed_overflow_net_contraction_min_ratio = 0.2
        params.ruplace_routed_overflow_net_contraction_weight = 0.01
        params.ruplace_routed_overflow_net_contraction_route_freq = 10
        params.ruplace_routed_overflow_net_contraction_mode = "directional"
        params.ruplace_routed_overflow_net_contraction_threshold = 0.05
        params.ruplace_routed_overflow_net_contraction_exponent = 2.0
        params.ruplace_routed_overflow_net_contraction_max_wire_span = 9
        params.ruplace_routed_overflow_net_contraction_distance_weighting = "uniform"
        params.ruplace_routed_overflow_net_contraction_matching_scale = 0.75
        params.ruplace_routed_overflow_net_contraction_orthogonal_spread_scale = 0.25
        params.ruplace_routed_overflow_net_contraction_smoothing_radius = 2
        params.ruplace_routed_overflow_net_contraction_smoothing_padding = "replicate"
        params.ruplace_routed_overflow_net_contraction_utilization_pressure_scale = 0.5
        params.ruplace_routed_overflow_net_contraction_utilization_threshold = 0.8
        params.ruplace_routed_overflow_net_contraction_utilization_exponent = 2.0
        params.ruplace_routed_overflow_net_contraction_x_scale = 2.0
        params.ruplace_routed_overflow_net_contraction_y_scale = 0.5
        params.ruplace_routed_overflow_net_contraction_scale_mode = "relative"
        params.ruplace_routed_overflow_net_contraction_max_ratio = 0.02
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = None
        backend.routed_overflow_contraction_gradient = mock.Mock(return_value=(
            torch.tensor([-1.0, 2.0, 3.0, -4.0]),
            {"overflow_net_count": 5, "horizontal_active_bins": 2},
        ))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 2
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = RoutedOverflowNetContractionPlugin(params, db, Obj())

        self.assertTrue(plugin.apply_gradient(torch.zeros(4), Obj(), context))

        backend.routed_overflow_contraction_gradient.assert_called_once_with(
            mock.ANY,
            refresh=True,
            mode="directional",
            overflow_threshold=0.05,
            overflow_exponent=2.0,
            max_wire_span=9,
            distance_weighting="uniform",
            matching_contraction_scale=0.75,
            orthogonal_spread_scale=0.25,
            smoothing_radius=2,
            smoothing_padding="replicate",
            utilization_pressure_scale=0.5,
            utilization_threshold=0.8,
            utilization_exponent=2.0,
        )
        call = context.add_scaled_movable_gradient.call_args
        self.assertTrue(torch.equal(call.args[1], torch.tensor([-2.0, 4.0])))
        self.assertTrue(torch.equal(call.args[2], torch.tensor([1.5, -2.0])))
        self.assertEqual(call.args[3], 0.01)
        self.assertEqual(call.kwargs["scale_mode"], "relative")
        self.assertEqual(call.kwargs["max_ratio"], 0.02)
        self.assertEqual(plugin.metrics["overflow_net_count"], 5)
        self.assertEqual(plugin.metrics["contraction_x_scale"], 2.0)
        self.assertEqual(plugin.metrics["contraction_y_scale"], 0.5)
        self.assertEqual(plugin.metrics["force_applications"], 1)

    def test_routed_overflow_contraction_plugin_rejects_invalid_axis_scale(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.routed_overflow_net_contraction import (
            RoutedOverflowNetContractionPlugin,
        )

        params = Obj()
        params.ruplace_routed_overflow_net_contraction_apply_interval = 1
        params.ruplace_routed_overflow_net_contraction_decay = 1.0
        params.ruplace_routed_overflow_net_contraction_min_ratio = 0.0
        params.ruplace_routed_overflow_net_contraction_weight = 0.01
        params.ruplace_routed_overflow_net_contraction_x_scale = float("nan")
        params.ruplace_routed_overflow_net_contraction_y_scale = 1.0
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        backend = Obj()
        backend.external_route_eval = False
        backend.routed_overflow_contraction_gradient = mock.Mock()
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1

        with self.assertRaisesRegex(ValueError, "axis scales"):
            RoutedOverflowNetContractionPlugin(params, db, Obj()).apply_gradient(
                torch.zeros(2), Obj(), context
            )
        backend.routed_overflow_contraction_gradient.assert_not_called()

    def test_routed_overflow_contraction_projects_opposing_objective_gradient(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.routed_overflow_net_contraction import (
            RoutedOverflowNetContractionPlugin,
        )

        params = Obj()
        params.ruplace_routed_overflow_net_contraction_apply_interval = 1
        params.ruplace_routed_overflow_net_contraction_decay = 1.0
        params.ruplace_routed_overflow_net_contraction_min_ratio = 0.0
        params.ruplace_routed_overflow_net_contraction_weight = 0.01
        params.ruplace_routed_overflow_net_contraction_x_scale = 1.0
        params.ruplace_routed_overflow_net_contraction_y_scale = 1.0
        params.ruplace_routed_overflow_net_contraction_projection_mode = (
            "node_nonopposing"
        )
        params.ruplace_routed_overflow_net_contraction_projection_strength = 1.0
        params.ruplace_routed_overflow_net_contraction_scale_mode = "relative"
        params.ruplace_routed_overflow_net_contraction_max_ratio = 0.02
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = object()
        backend.routed_overflow_contraction_gradient = mock.Mock(return_value=(
            torch.tensor([1.0, -1.0, 0.0, 0.0]),
            {"overflow_net_count": 5},
        ))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1
        context.reference_movable_gradient = mock.Mock(return_value=(
            torch.tensor([1.0, 1.0]),
            torch.tensor([0.0, 0.0]),
        ))
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })

        plugin = RoutedOverflowNetContractionPlugin(params, db, Obj())
        self.assertTrue(plugin.apply_gradient(torch.zeros(4), Obj(), context))

        call = context.add_scaled_movable_gradient.call_args
        self.assertTrue(torch.equal(call.args[1], torch.tensor([1.0, 0.0])))
        self.assertTrue(torch.equal(call.args[2], torch.tensor([0.0, 0.0])))
        self.assertEqual(plugin.metrics["objective_projection_projected_count"], 1)
        self.assertEqual(plugin.metrics["objective_projection_strength"], 1.0)

    def test_connection_routeforce_uses_routed_edge_controls(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.connection_routeforce import (
            ConnectionRouteForcePlugin,
        )

        params = Obj()
        params.ruplace_connection_routeforce_apply_interval = 1
        params.ruplace_connection_routeforce_decay = 1.0
        params.ruplace_connection_routeforce_min_ratio = 0.0
        params.ruplace_connection_routeforce_route_freq = 5
        params.ruplace_connection_routeforce_weight = 0.01
        params.ruplace_connection_routeforce_scale_mode = "relative"
        params.ruplace_connection_routeforce_max_ratio = 0.05
        params.ruplace_connection_routeforce_overflow_threshold = 0.02
        params.ruplace_connection_routeforce_max_wire_span = 19
        params.ruplace_connection_routeforce_distance_weighting = "inverse_sqrt"
        params.ruplace_connection_routeforce_field_mode = "directional_hv"
        params.ruplace_connection_routeforce_utilization_threshold = 0.75
        params.ruplace_connection_routeforce_pressure_exponent = 1.5
        params.ruplace_connection_routeforce_via_utilization_threshold = 0.15
        params.ruplace_connection_routeforce_dilation_radius = 2
        params.ruplace_connection_routeforce_wire_cost = 1.5
        params.ruplace_connection_routeforce_via_cost = 0.5
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = None
        backend.connection_route_gradient = mock.Mock(return_value=(
            torch.tensor([-2.0, 2.0, 0.0, 0.0]),
            {"overflow_active_bins": 3, "overflow_max": 0.2},
        ))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1
        pos = torch.tensor([0.0, 10.0, 0.0, 0.0], requires_grad=True)
        pos.grad = torch.tensor([1.0, -1.0, 0.0, 0.0])
        context.begin_gradient(pos)

        plugin = ConnectionRouteForcePlugin(params, db, Obj())
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        backend.connection_route_gradient.assert_called_once_with(
            pos,
            refresh=True,
            overflow_threshold=0.02,
            max_wire_span=19,
            distance_weighting="inverse_sqrt",
            field_mode="directional_hv",
            segment_reduction="last",
            segment_blend=0.0,
            utilization_threshold=0.75,
            pressure_exponent=1.5,
            via_utilization_threshold=0.15,
            dilation_radius=2,
            unit_wire_cost=1.5,
            unit_via_cost=0.5,
        )
        self.assertEqual(plugin.metrics["overflow_active_bins"], 3)
        self.assertAlmostEqual(plugin.metrics["applied_ratio"], 0.01, places=6)

        backend.last_route = object()
        backend.connection_route_gradient.reset_mock()
        context.iteration = 5
        context.begin_gradient(pos)
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        self.assertTrue(
            backend.connection_route_gradient.call_args.kwargs["refresh"]
        )

    def test_connection_routeforce_scales_cross_track_axes(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.connection_routeforce import (
            ConnectionRouteForcePlugin,
        )

        params = Obj()
        params.ruplace_connection_routeforce_apply_interval = 1
        params.ruplace_connection_routeforce_decay = 1.0
        params.ruplace_connection_routeforce_min_ratio = 0.0
        params.ruplace_connection_routeforce_route_freq = 100
        params.ruplace_connection_routeforce_weight = 0.01
        params.ruplace_connection_routeforce_x_scale = 0.25
        params.ruplace_connection_routeforce_y_scale = 2.0
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = object()
        backend.connection_route_gradient = mock.Mock(return_value=(
            torch.tensor([-2.0, 2.0, 3.0, -3.0]),
            {"overflow_active_bins": 1},
        ))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        pos = torch.zeros(4, requires_grad=True)

        plugin = ConnectionRouteForcePlugin(params, db, Obj())
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))

        call = context.add_scaled_movable_gradient.call_args
        self.assertTrue(torch.equal(
            call.args[1], torch.tensor([-0.5, 0.5])
        ))
        self.assertTrue(torch.equal(
            call.args[2], torch.tensor([6.0, -6.0])
        ))
        self.assertEqual(plugin.metrics["routeforce_x_scale"], 0.25)
        self.assertEqual(plugin.metrics["routeforce_y_scale"], 2.0)

    def test_multisegment_plugin_forwards_selected_reduction(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.multisegment_connection_routeforce import (
            MultiSegmentConnectionRouteForcePlugin,
        )

        params = Obj()
        params.ruplace_connection_routeforce_apply_interval = 1
        params.ruplace_connection_routeforce_decay = 1.0
        params.ruplace_connection_routeforce_min_ratio = 0.0
        params.ruplace_connection_routeforce_weight = 0.01
        params.ruplace_connection_routeforce_scale_mode = "absolute"
        params.ruplace_multisegment_connection_routeforce_reduction = "mean"
        params.ruplace_multisegment_connection_routeforce_blend = 0.25
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = object()
        backend.connection_route_gradient = mock.Mock(return_value=(
            torch.tensor([-1.0, 0.0]), {"overflow_active_bins": 1},
        ))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1
        pos = torch.zeros(2, requires_grad=True)
        pos.grad = torch.zeros_like(pos)
        context.begin_gradient(pos)

        plugin = MultiSegmentConnectionRouteForcePlugin(params, db, Obj())
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        self.assertEqual(
            backend.connection_route_gradient.call_args.kwargs[
                "segment_reduction"
            ],
            "mean",
        )
        self.assertEqual(
            backend.connection_route_gradient.call_args.kwargs["segment_blend"],
            0.25,
        )
        self.assertEqual(plugin.name, "multisegment_connection_routeforce")

    def test_projected_connection_routeforce_projection_modes(self):
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            project_route_gradient,
        )

        route_x = torch.tensor([-1.0, 1.0])
        route_y = torch.tensor([1.0, 1.0])
        reference_x = torch.tensor([1.0, 1.0])
        reference_y = torch.zeros(2)

        global_x, global_y, global_metrics = project_route_gradient(
            route_x, route_y, reference_x, reference_y,
            "global_nonopposing",
        )
        self.assertTrue(torch.equal(global_x, route_x))
        self.assertTrue(torch.equal(global_y, route_y))
        self.assertEqual(global_metrics["projection_projected_count"], 0)

        node_x, node_y, node_metrics = project_route_gradient(
            route_x, route_y, reference_x, reference_y,
            "node_nonopposing",
        )
        self.assertTrue(torch.allclose(node_x, torch.tensor([0.0, 1.0])))
        self.assertTrue(torch.equal(node_y, route_y))
        self.assertEqual(node_metrics["projection_projected_count"], 1)
        self.assertAlmostEqual(
            node_metrics["projection_projected_fraction"], 0.5
        )

        orthogonal_x, orthogonal_y, orthogonal_metrics = project_route_gradient(
            route_x, route_y, reference_x, reference_y,
            "node_orthogonal",
        )
        self.assertTrue(torch.equal(orthogonal_x, torch.zeros(2)))
        self.assertTrue(torch.equal(orthogonal_y, route_y))
        self.assertAlmostEqual(orthogonal_metrics["projection_dot_after"], 0.0)

    def test_projected_connection_routeforce_global_nonopposing(self):
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            project_route_gradient,
        )

        projected_x, projected_y, metrics = project_route_gradient(
            torch.tensor([-2.0, 0.0]),
            torch.tensor([0.0, 0.0]),
            torch.tensor([1.0, 1.0]),
            torch.tensor([0.0, 0.0]),
            "global_nonopposing",
        )
        self.assertTrue(torch.allclose(projected_x, torch.tensor([-1.0, 1.0])))
        self.assertTrue(torch.equal(projected_y, torch.zeros(2)))
        self.assertAlmostEqual(metrics["projection_dot_before"], -2.0)
        self.assertAlmostEqual(metrics["projection_dot_after"], 0.0)
        self.assertEqual(metrics["projection_projected_count"], 1)

        partial_x, partial_y, partial_metrics = project_route_gradient(
            torch.tensor([-2.0, 0.0]),
            torch.tensor([0.0, 0.0]),
            torch.tensor([1.0, 1.0]),
            torch.tensor([0.0, 0.0]),
            "global_nonopposing",
            strength=0.5,
        )
        self.assertTrue(torch.allclose(partial_x, torch.tensor([-1.5, 0.5])))
        self.assertTrue(torch.equal(partial_y, torch.zeros(2)))
        self.assertAlmostEqual(partial_metrics["projection_dot_after"], -1.0)
        self.assertAlmostEqual(partial_metrics["projection_strength"], 0.5)

    def test_projected_connection_routeforce_rejects_invalid_strength(self):
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            project_route_gradient,
        )

        values = torch.ones(1)
        with self.assertRaisesRegex(ValueError, "strength"):
            project_route_gradient(
                values, values, values, values, "node_orthogonal",
                strength=-0.1,
            )
        with self.assertRaisesRegex(ValueError, "strength"):
            project_route_gradient(
                values, values, values, values, "node_orthogonal",
                strength=1.1,
            )
        for kwargs in (
            {"strength": float("nan")},
            {"strength": float("inf")},
            {"strength_x": -0.1},
            {"strength_x": float("nan")},
            {"strength_y": 1.1},
            {"strength_y": float("inf")},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "strength"):
                    project_route_gradient(
                        values, values, values, values, "node_orthogonal",
                        **kwargs,
                    )

    def test_projected_connection_routeforce_axis_strengths(self):
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            project_route_gradient,
        )

        route_x = torch.tensor([3.0])
        route_y = torch.tensor([4.0])
        reference_x = torch.tensor([1.0])
        reference_y = torch.tensor([2.0])
        projected_x, projected_y, metrics = project_route_gradient(
            route_x,
            route_y,
            reference_x,
            reference_y,
            "node_orthogonal",
            strength=0.25,
            strength_x=1.0,
            strength_y=0.0,
        )

        self.assertTrue(torch.allclose(projected_x, torch.tensor([0.8])))
        self.assertTrue(torch.equal(projected_y, route_y))
        self.assertAlmostEqual(metrics["projection_strength"], 0.25)
        self.assertAlmostEqual(metrics["projection_strength_x"], 1.0)
        self.assertAlmostEqual(metrics["projection_strength_y"], 0.0)

    def test_projected_connection_routeforce_axis_fallback_matches_scalar(self):
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            project_route_gradient,
        )

        inputs = (
            torch.tensor([-2.0, 3.0]),
            torch.tensor([4.0, -5.0]),
            torch.tensor([1.0, 2.0]),
            torch.tensor([-3.0, 4.0]),
            "node_orthogonal",
        )
        scalar_x, scalar_y, scalar_metrics = project_route_gradient(
            *inputs, strength=0.375
        )
        axis_x, axis_y, axis_metrics = project_route_gradient(
            *inputs, strength=0.375, strength_x=0.375, strength_y=0.375
        )

        self.assertTrue(torch.equal(scalar_x, axis_x))
        self.assertTrue(torch.equal(scalar_y, axis_y))
        self.assertEqual(scalar_metrics, axis_metrics)

    def test_projected_connection_routeforce_forwards_axis_strengths(self):
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            ProjectedConnectionRouteForcePlugin,
        )

        params = Obj()
        params.ruplace_projected_connection_routeforce_mode = "node_orthogonal"
        params.ruplace_projected_connection_routeforce_epsilon = 1.0e-12
        params.ruplace_projected_connection_routeforce_strength = 0.5
        params.ruplace_projected_connection_routeforce_strength_x = 1.0
        params.ruplace_projected_connection_routeforce_strength_y = 0.0
        db = Obj()
        context = Obj()
        context.reference_movable_gradient = mock.Mock(return_value=(
            torch.tensor([1.0]), torch.tensor([2.0])
        ))
        plugin = ProjectedConnectionRouteForcePlugin(params, db, Obj())

        projected_x, projected_y, metrics = plugin.condition_gradient(
            torch.zeros(2), context, torch.tensor([3.0]), torch.tensor([4.0])
        )

        self.assertTrue(torch.allclose(projected_x, torch.tensor([0.8])))
        self.assertTrue(torch.equal(projected_y, torch.tensor([4.0])))
        self.assertEqual(metrics["projection_mode"], "node_orthogonal")
        self.assertEqual(metrics["projection_strength"], 0.5)
        self.assertEqual(metrics["projection_strength_x"], 1.0)
        self.assertEqual(metrics["projection_strength_y"], 0.0)

    def test_projected_connection_routeforce_uses_reference_and_shared_schedule(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            ProjectedConnectionRouteForcePlugin,
        )

        params = Obj()
        params.ruplace_connection_routeforce_apply_interval = 2
        params.ruplace_connection_routeforce_decay = 1.0
        params.ruplace_connection_routeforce_min_ratio = 0.0
        params.ruplace_connection_routeforce_weight = 0.5
        params.ruplace_connection_routeforce_scale_mode = "absolute"
        params.ruplace_projected_connection_routeforce_mode = "node_nonopposing"
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = object()
        backend.connection_route_gradient = mock.Mock(return_value=(
            torch.tensor([-1.0, 1.0, 1.0, 1.0]),
            {"overflow_active_bins": 1},
        ))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        pos = torch.zeros(4, requires_grad=True)
        pos.grad = torch.tensor([1.0, 1.0, 0.0, 0.0])
        context.begin_gradient(pos)
        plugin = ProjectedConnectionRouteForcePlugin(params, db, Obj())

        context.iteration = 1
        self.assertFalse(plugin.apply_gradient(pos, Obj(), context))
        backend.connection_route_gradient.assert_not_called()

        context.iteration = 2
        self.assertTrue(plugin.apply_gradient(pos, Obj(), context))
        self.assertTrue(torch.allclose(
            pos.grad, torch.tensor([1.0, 1.5, 0.5, 0.5])
        ))
        self.assertEqual(plugin.metrics["projection_projected_count"], 1)
        self.assertEqual(plugin.metrics["force_apply_interval"], 2)

    def test_projected_connection_routeforce_rejects_missing_reference(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.projected_connection_routeforce import (
            ProjectedConnectionRouteForcePlugin,
        )

        params = Obj()
        params.ruplace_connection_routeforce_apply_interval = 1
        params.ruplace_connection_routeforce_decay = 1.0
        params.ruplace_connection_routeforce_min_ratio = 0.0
        params.ruplace_connection_routeforce_weight = 0.5
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        backend = Obj()
        backend.external_route_eval = False
        backend.last_route = object()
        backend.connection_route_gradient = mock.Mock(return_value=(
            torch.tensor([1.0, 0.0]), {}
        ))
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1

        with self.assertRaisesRegex(RuntimeError, "placement gradient"):
            ProjectedConnectionRouteForcePlugin(params, db, Obj()).apply_gradient(
                torch.zeros(2), Obj(), context
            )

    def test_connection_routeforce_rejects_invalid_axis_scales(self):
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.connection_routeforce import (
            ConnectionRouteForcePlugin,
        )

        params = Obj()
        params.ruplace_connection_routeforce_apply_interval = 1
        params.ruplace_connection_routeforce_decay = 1.0
        params.ruplace_connection_routeforce_min_ratio = 0.0
        params.ruplace_connection_routeforce_weight = 0.01
        params.ruplace_connection_routeforce_x_scale = 0.0
        params.ruplace_connection_routeforce_y_scale = 0.0
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        backend = Obj()
        backend.external_route_eval = False
        backend.connection_route_gradient = mock.Mock()
        proxy = Obj()
        proxy.backend = backend
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1

        with self.assertRaisesRegex(ValueError, "nonzero axis scale"):
            ConnectionRouteForcePlugin(params, db, Obj()).apply_gradient(
                torch.zeros(2), Obj(), context
            )
        backend.connection_route_gradient.assert_not_called()

    def test_connection_routeforce_masks_and_clamps_zero_capacity(self):
        from dreamplace.ops.gpugr.xplace_backend import (
            RUPlaceRouteResult,
            XplaceGGRAdapter,
        )

        dct2 = mock.Mock(side_effect=lambda value: value)
        routeforce = Obj()
        routeforce.route_grad = mock.Mock(return_value=torch.zeros(2, 2))
        overflow = torch.tensor([[1.0e30, 1.0], [2.0e30, 0.0]])
        route = RUPlaceRouteResult(
            routeforce,
            overflow,
            overflow,
            torch.zeros(2, 2, 2),
            {},
            route_maps={
                "demand": torch.ones(2, 2),
                "wire_demand": torch.ones(2, 2),
                "via_demand": torch.zeros(2, 2),
                "capacity": torch.tensor([[0.0, 1.0], [0.0, 2.0]]),
            },
        )
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = route
        adapter.device = torch.device("cpu")
        adapter.connection_dct_ops = {
            ((2, 2), torch.device("cpu"), torch.float32): (
                dct2,
                lambda value: value,
                lambda value: value,
            )
        }
        adapter.node2pin_list = torch.tensor([0, 1])
        adapter.node2pin_list_end = torch.tensor([1, 2])
        adapter.x_num_nodes = 2
        adapter.dp_movable_ids = torch.tensor([0, 1])
        adapter.x_movable_ids = torch.tensor([0, 1])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 2

        _, metrics = adapter.connection_route_gradient(torch.zeros(4))

        call = routeforce.route_grad.call_args.args
        self.assertTrue(torch.equal(
            call[0], torch.tensor([[0.0, 1.0], [0.0, 0.0]])
        ))
        self.assertTrue(torch.equal(
            dct2.call_args.args[0], torch.tensor([[0.0, 1.0], [0.0, 0.0]])
        ))
        self.assertTrue(torch.all(call[3] >= 0.2))
        self.assertEqual(metrics["zero_capacity_bins"], 2)
        self.assertEqual(metrics["field_overflow_max"], 1.0)
        self.assertEqual(metrics["raw_route_gradient_nonfinite_count"], 0)

    def test_connection_routeforce_descent_moves_away_on_cross_track_axes(self):
        from dreamplace.ops.gpugr.xplace_backend import (
            RUPlaceRouteResult,
            XplaceGGRAdapter,
        )
        from dreamplace.ops.routability_opt.plugin_base import PluginContext
        from dreamplace.ops.routability_opt.plugins.connection_routeforce import (
            ConnectionRouteForcePlugin,
        )

        horizontal = torch.zeros(8, 8)
        vertical = torch.zeros(8, 8)
        horizontal[3, 3:5] = 1.0
        vertical[3:5, 3] = 1.0
        electric_x = torch.zeros(8, 8)
        electric_y = torch.zeros(8, 8)
        electric_x[4, 3] = 2.0
        electric_y[3, 4] = 3.0

        routeforce = Obj()

        def native_route_gradient(*args):
            route_field = args[6]
            grad_weight = args[9]
            self.assertEqual(grad_weight, -1.0)
            # The native kernel returns an objective gradient. A pin on the
            # right/top boundary samples the outward electric field and the
            # kernel's -1 converts it for optimizer descent.
            return torch.tensor([
                [grad_weight * route_field[0, 4, 3], 0.0],
                [0.0, grad_weight * route_field[1, 3, 4]],
            ])

        routeforce.route_grad = mock.Mock(side_effect=native_route_gradient)
        route = RUPlaceRouteResult(
            routeforce,
            torch.maximum(horizontal, vertical),
            torch.ones(8, 8),
            torch.stack((horizontal, vertical)),
            {},
            hv_utilization_map=torch.stack((horizontal, vertical)),
            route_maps={
                "demand": torch.ones(8, 8),
                "wire_demand": torch.ones(8, 8),
                "via_demand": torch.zeros(8, 8),
                "capacity": torch.ones(8, 8),
            },
        )
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = route
        adapter.device = torch.device("cpu")
        adapter.connection_dct_ops = {
            ((8, 8), torch.device("cpu"), torch.float32): (
                lambda value: value,
                lambda value: electric_x,
                lambda value: electric_y,
            )
        }
        adapter.node2pin_list = torch.tensor([0, 1])
        adapter.node2pin_list_end = torch.tensor([1, 2])
        adapter.x_num_nodes = 2
        adapter.dp_movable_ids = torch.tensor([0, 1])
        adapter.x_movable_ids = torch.tensor([0, 1])

        db = Obj()
        db.num_nodes = db.num_movable_nodes = 2
        adapter.placedb = db
        params = Obj()
        params.ruplace_connection_routeforce_apply_interval = 1
        params.ruplace_connection_routeforce_decay = 1.0
        params.ruplace_connection_routeforce_min_ratio = 0.0
        params.ruplace_connection_routeforce_weight = 1.0
        params.ruplace_connection_routeforce_scale_mode = "absolute"
        params.ruplace_connection_routeforce_field_mode = "directional_hv"
        proxy = Obj()
        proxy.backend = adapter
        context = PluginContext(params, db, Obj(), Obj(), proxy)
        context.iteration = 1
        pos = torch.zeros(4, requires_grad=True)
        pos.grad = torch.zeros_like(pos)
        context.begin_gradient(pos)

        self.assertTrue(
            ConnectionRouteForcePlugin(params, db, Obj()).apply_gradient(
                pos, Obj(), context
            )
        )
        descended = pos.detach() - pos.grad
        self.assertGreater(descended[0].item(), 0.0)
        self.assertGreater(descended[3].item(), 0.0)
        self.assertEqual(descended[1].item(), 0.0)
        self.assertEqual(descended[2].item(), 0.0)

    def test_multisegment_connection_routeforce_selects_native_reduction(self):
        from dreamplace.ops.gpugr.xplace_backend import (
            RUPlaceRouteResult,
            XplaceGGRAdapter,
        )

        routeforce = Obj()
        routeforce.route_grad = mock.Mock(return_value=torch.zeros(1, 2))
        routeforce.route_grad_reduce = mock.Mock(return_value=torch.zeros(1, 2))
        route = RUPlaceRouteResult(
            routeforce,
            torch.ones(2, 2),
            torch.ones(2, 2),
            torch.ones(2, 2, 2),
            {},
            route_maps={
                "demand": torch.ones(2, 2),
                "wire_demand": torch.ones(2, 2),
                "via_demand": torch.zeros(2, 2),
                "capacity": torch.ones(2, 2),
            },
        )
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = route
        adapter.device = torch.device("cpu")
        adapter.connection_dct_ops = {
            ((2, 2), torch.device("cpu"), torch.float32): (
                lambda value: value,
                lambda value: value,
                lambda value: value,
            )
        }
        adapter.node2pin_list = torch.tensor([0])
        adapter.node2pin_list_end = torch.tensor([1])
        adapter.x_num_nodes = 1
        adapter.dp_movable_ids = torch.tensor([0])
        adapter.x_movable_ids = torch.tensor([0])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 1

        _, sum_metrics = adapter.connection_route_gradient(
            torch.zeros(2), segment_reduction="sum"
        )
        self.assertEqual(routeforce.route_grad_reduce.call_args.args[-1], 1)
        self.assertEqual(sum_metrics["segment_reduction_id"], 1)
        routeforce.route_grad_reduce.reset_mock()

        _, mean_metrics = adapter.connection_route_gradient(
            torch.zeros(2), segment_reduction="mean"
        )
        self.assertEqual(routeforce.route_grad_reduce.call_args.args[-1], 2)
        self.assertEqual(mean_metrics["segment_reduction_id"], 2)
        routeforce.route_grad.assert_not_called()

    def test_multisegment_connection_routeforce_blends_exact_endpoints(self):
        from dreamplace.ops.gpugr.xplace_backend import (
            RUPlaceRouteResult,
            XplaceGGRAdapter,
        )

        reference = torch.tensor([[1.0, 3.0]])
        summed = torch.tensor([[5.0, -1.0]])
        routeforce = Obj()
        routeforce.route_grad = mock.Mock(return_value=reference)
        routeforce.route_grad_reduce = mock.Mock(return_value=summed)
        route = RUPlaceRouteResult(
            routeforce,
            torch.ones(1, 1),
            torch.ones(1, 1),
            torch.ones(2, 1, 1),
            {},
            route_maps={
                "demand": torch.ones(1, 1),
                "wire_demand": torch.ones(1, 1),
                "via_demand": torch.zeros(1, 1),
                "capacity": torch.ones(1, 1),
            },
        )
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = route
        adapter.device = torch.device("cpu")
        adapter.connection_dct_ops = {
            ((1, 1), torch.device("cpu"), torch.float32): (
                lambda value: value,
                lambda value: value,
                lambda value: value,
            )
        }
        adapter.node2pin_list = torch.tensor([0])
        adapter.node2pin_list_end = torch.tensor([1])
        adapter.x_num_nodes = 1
        adapter.dp_movable_ids = torch.tensor([0])
        adapter.x_movable_ids = torch.tensor([0])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 1

        grad0, metrics0 = adapter.connection_route_gradient(
            torch.zeros(2), segment_reduction="blend", segment_blend=0.0
        )
        self.assertTrue(torch.equal(grad0, torch.tensor([1.0, 3.0])))
        self.assertEqual(routeforce.route_grad.call_count, 1)
        self.assertEqual(routeforce.route_grad_reduce.call_count, 0)
        self.assertEqual(metrics0["segment_reduction_id"], 3)
        self.assertEqual(metrics0["segment_blend"], 0.0)

        routeforce.route_grad.reset_mock()
        grad1, metrics1 = adapter.connection_route_gradient(
            torch.zeros(2), segment_reduction="blend", segment_blend=1.0
        )
        self.assertTrue(torch.equal(grad1, torch.tensor([5.0, -1.0])))
        self.assertEqual(routeforce.route_grad.call_count, 0)
        self.assertEqual(routeforce.route_grad_reduce.call_count, 1)
        self.assertEqual(metrics1["segment_blend"], 1.0)

        routeforce.route_grad_reduce.reset_mock()
        grad_mid, metrics_mid = adapter.connection_route_gradient(
            torch.zeros(2), segment_reduction="blend", segment_blend=0.25
        )
        self.assertTrue(torch.equal(grad_mid, torch.tensor([2.0, 2.0])))
        self.assertEqual(routeforce.route_grad.call_count, 1)
        self.assertEqual(routeforce.route_grad_reduce.call_count, 1)
        self.assertEqual(metrics_mid["segment_blend"], 0.25)

    def test_connection_routeforce_selects_directional_and_layer_fields(self):
        from dreamplace.ops.gpugr.xplace_backend import (
            RUPlaceRouteResult,
            XplaceGGRAdapter,
        )

        horizontal = torch.tensor([[0.0, 2.0], [0.0, 0.0]])
        vertical = torch.tensor([[3.0, 0.0], [0.0, 0.0]])
        routeforce = Obj()
        routeforce.route_grad = mock.Mock(return_value=torch.zeros(2, 2))
        route = RUPlaceRouteResult(
            routeforce,
            torch.zeros(2, 2),
            torch.zeros(2, 2),
            torch.stack((horizontal, vertical)),
            {},
            route_maps={
                "demand": torch.ones(2, 2),
                "wire_demand": torch.ones(2, 2),
                "via_demand": torch.zeros(2, 2),
                "capacity": torch.ones(2, 2),
                "layer_demand": torch.tensor([
                    [[1.0, 1.0], [1.0, 1.0]],
                    [[1.0, 1.0], [4.0, 1.0]],
                ]),
                "layer_wire_demand": torch.tensor([
                    [[1.0, 2.0], [1.0, 1.0]],
                    [[1.0, 1.0], [3.0, 1.0]],
                ]),
                "layer_via_demand": torch.tensor([
                    [[0.0, 0.5], [0.0, 0.0]],
                    [[0.0, 0.0], [0.4, 0.0]],
                ]),
                "layer_capacity": torch.ones(2, 2, 2),
                "short_layer_wire_demand": torch.tensor([
                    [[0.75, 1.0], [1.0, 1.0]],
                    [[1.0, 2.0], [1.0, 1.0]],
                    [[1.0, 1.0], [3.0, 1.0]],
                ]),
                "short_layer_via_demand": torch.tensor([
                    [[0.5, 0.0], [0.0, 0.0]],
                    [[0.0, 0.5], [0.0, 0.0]],
                    [[0.0, 0.0], [0.4, 0.0]],
                ]),
                "short_layer_capacity": torch.ones(3, 2, 2),
            },
        )
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = route
        adapter.device = torch.device("cpu")
        dct2 = mock.Mock(side_effect=lambda value: value)
        adapter.connection_dct_ops = {
            ((2, 2), torch.device("cpu"), torch.float32): (
                dct2,
                lambda value: value,
                lambda value: value,
            )
        }
        adapter.node2pin_list = torch.tensor([0, 1])
        adapter.node2pin_list_end = torch.tensor([1, 2])
        adapter.x_num_nodes = 2
        adapter.dp_movable_ids = torch.tensor([0, 1])
        adapter.x_movable_ids = torch.tensor([0, 1])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 2

        _, max_hv_metrics = adapter.connection_route_gradient(
            torch.zeros(4), field_mode="max_hv"
        )
        self.assertTrue(torch.equal(
            dct2.call_args.args[0], torch.maximum(horizontal, vertical)
        ))
        self.assertEqual(max_hv_metrics["field_mode_id"], 1)

        dct2.reset_mock()
        _, directional_metrics = adapter.connection_route_gradient(
            torch.zeros(4), field_mode="directional_hv"
        )
        self.assertEqual(dct2.call_count, 2)
        self.assertTrue(torch.equal(dct2.call_args_list[0].args[0], vertical))
        self.assertTrue(torch.equal(dct2.call_args_list[1].args[0], horizontal))
        self.assertEqual(directional_metrics["field_mode_id"], 2)

        dct2.reset_mock()
        _, layer_metrics = adapter.connection_route_gradient(
            torch.zeros(4), field_mode="max_layer"
        )
        self.assertTrue(torch.equal(
            dct2.call_args.args[0],
            torch.tensor([[0.0, 0.0], [3.0, 0.0]]),
        ))
        self.assertEqual(layer_metrics["field_mode_id"], 3)

        route.hv_utilization_map = torch.stack((
            torch.tensor([[0.8, 0.6], [0.6, 0.6]]),
            torch.tensor([[0.6, 0.6], [0.6, 0.9]]),
        ))
        dct2.reset_mock()
        _, pressure_metrics = adapter.connection_route_gradient(
            torch.zeros(4),
            field_mode="directional_hv_pressure",
            utilization_threshold=0.7,
            dilation_radius=1,
        )
        self.assertEqual(dct2.call_count, 2)
        self.assertTrue(torch.allclose(
            dct2.call_args_list[0].args[0],
            torch.full((2, 2), 0.2),
        ))
        self.assertTrue(torch.allclose(
            dct2.call_args_list[1].args[0],
            torch.full((2, 2), 0.1),
        ))
        self.assertEqual(pressure_metrics["field_mode_id"], 4)
        self.assertEqual(pressure_metrics["dilation_radius"], 1)
        self.assertAlmostEqual(
            pressure_metrics["utilization_threshold"], 0.7
        )
        self.assertAlmostEqual(pressure_metrics["pressure_exponent"], 1.0)

        dct2.reset_mock()
        _, focused_pressure_metrics = adapter.connection_route_gradient(
            torch.zeros(4),
            field_mode="directional_hv_pressure",
            utilization_threshold=0.7,
            pressure_exponent=2.0,
            dilation_radius=1,
        )
        self.assertEqual(dct2.call_count, 2)
        self.assertTrue(torch.allclose(
            dct2.call_args_list[0].args[0],
            torch.full((2, 2), 0.04),
        ))
        self.assertTrue(torch.allclose(
            dct2.call_args_list[1].args[0],
            torch.full((2, 2), 0.01),
        ))
        self.assertAlmostEqual(
            focused_pressure_metrics["pressure_exponent"], 2.0
        )

        route.route_maps["via_demand"] = torch.tensor([
            [0.0, 0.0], [0.0, 0.8],
        ])
        dct2.reset_mock()
        _, via_pressure_metrics = adapter.connection_route_gradient(
            torch.zeros(4),
            field_mode="directional_hv_pressure_via",
            utilization_threshold=0.7,
            via_utilization_threshold=0.25,
            dilation_radius=0,
            unit_via_cost=2.0,
        )
        self.assertEqual(dct2.call_count, 2)
        self.assertTrue(torch.allclose(
            dct2.call_args_list[0].args[0],
            torch.tensor([[0.0, 0.0], [0.0, 1.3]]),
        ))
        self.assertTrue(torch.allclose(
            dct2.call_args_list[1].args[0],
            torch.tensor([[0.1, 0.0], [0.0, 1.1]]),
        ))
        self.assertEqual(via_pressure_metrics["field_mode_id"], 5)
        self.assertAlmostEqual(
            via_pressure_metrics["via_utilization_threshold"], 0.25
        )

        dct2.reset_mock()
        _, short_via_metrics = adapter.connection_route_gradient(
            torch.zeros(4),
            field_mode="directional_hv_pressure_via_short",
            utilization_threshold=0.7,
            via_utilization_threshold=0.25,
            dilation_radius=0,
            unit_via_cost=2.0,
        )
        self.assertEqual(dct2.call_count, 2)
        self.assertTrue(torch.allclose(
            dct2.call_args_list[0].args[0],
            torch.tensor([[0.5, 0.5], [0.3, 0.2]]),
        ))
        self.assertTrue(torch.allclose(
            dct2.call_args_list[1].args[0],
            torch.tensor([[0.6, 0.5], [0.3, 0.0]]),
        ))
        self.assertEqual(short_via_metrics["field_mode_id"], 6)
        self.assertEqual(short_via_metrics["short_via_active_layer_bins"], 3)
        self.assertAlmostEqual(
            short_via_metrics["short_via_demand_finite_max"], 0.5
        )

    def test_connection_routeforce_rejects_invalid_pressure_controls(self):
        from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter

        adapter = object.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = Obj()
        adapter.last_route.routeforce = object()
        adapter.last_route.route_maps = {"present": True}

        with self.assertRaisesRegex(ValueError, "utilization threshold"):
            adapter.connection_route_gradient(
                torch.zeros(2), utilization_threshold=-0.1
            )
        with self.assertRaisesRegex(ValueError, "dilation radius"):
            adapter.connection_route_gradient(
                torch.zeros(2), dilation_radius=-1
            )
        with self.assertRaisesRegex(ValueError, "via utilization threshold"):
            adapter.connection_route_gradient(
                torch.zeros(2), via_utilization_threshold=-0.1
            )
        with self.assertRaisesRegex(ValueError, "pressure exponent"):
            adapter.connection_route_gradient(
                torch.zeros(2), pressure_exponent=0.0
            )
        for invalid in (float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "pressure exponent"):
                adapter.connection_route_gradient(
                    torch.zeros(2), pressure_exponent=invalid
                )
        with self.assertRaisesRegex(ValueError, "segment reduction"):
            adapter.connection_route_gradient(
                torch.zeros(2), segment_reduction="median"
            )
        for invalid in (-0.1, 1.1, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "segment blend"):
                adapter.connection_route_gradient(
                    torch.zeros(2), segment_reduction="blend",
                    segment_blend=invalid,
                )

    def test_connection_routeforce_skips_xplace_kernel_for_empty_mask(self):
        from dreamplace.ops.gpugr.xplace_backend import (
            RUPlaceRouteResult,
            XplaceGGRAdapter,
        )

        routeforce = Obj()
        routeforce.route_grad = mock.Mock(
            return_value=torch.full((1, 2), float("nan"))
        )
        route = RUPlaceRouteResult(
            routeforce,
            torch.zeros(1, 1),
            torch.zeros(1, 1),
            torch.zeros(2, 1, 1),
            {},
            route_maps={
                "demand": torch.zeros(1, 1),
                "wire_demand": torch.zeros(1, 1),
                "via_demand": torch.zeros(1, 1),
                "capacity": torch.ones(1, 1),
            },
        )
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.external_route_eval = False
        adapter.last_route = route
        adapter.device = torch.device("cpu")
        adapter.connection_dct_ops = {
            ((1, 1), torch.device("cpu"), torch.float32): (
                lambda value: value,
                lambda value: value,
                lambda value: value,
            )
        }
        adapter.node2pin_list = torch.tensor([0])
        adapter.node2pin_list_end = torch.tensor([1])
        adapter.x_num_nodes = 1
        adapter.dp_movable_ids = torch.tensor([0])
        adapter.x_movable_ids = torch.tensor([0])
        adapter.placedb = Obj()
        adapter.placedb.num_nodes = 1

        grad, metrics = adapter.connection_route_gradient(torch.zeros(2))

        routeforce.route_grad.assert_not_called()
        self.assertTrue(torch.equal(grad, torch.zeros(2)))
        self.assertEqual(metrics["kernel_skipped_empty_mask"], 1)

    def test_net_overlap_uses_physical_anisotropic_bin_sizes_when_enabled(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins import net_overlap
        from dreamplace.ops.routability_opt.plugins.net_overlap import (
            NetOverlapRemovalPlugin,
        )

        params = Obj()
        params.ruplace_net_overlap_smooth = 0
        params.ruplace_net_overlap_weight = 0.05
        params.ruplace_force_physical_bins = True
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = 4.0
        db.routing_grid_yh = 2.0
        data = Obj()
        data.flat_net2pin_start_map = torch.tensor([0, 1])
        data.flat_net2pin_map = torch.tensor([0])
        data.pin2node_map = torch.tensor([0])
        context = Obj()
        context.iteration = 1
        context.signal = lambda pos: CongestionSignal(
            torch.zeros(2, 2), overflow_map=torch.tensor([[0.0, 0.0], [1.0, 0.0]])
        )
        context.pin_positions = lambda pos: torch.tensor([1.0, 1.0])
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.05,
            "applied_ratio": 0.05,
        })
        plugin = NetOverlapRemovalPlugin(params, db, data)

        with mock.patch.object(
            net_overlap, "map_gradient", wraps=net_overlap.map_gradient
        ) as gradient:
            plugin.apply_gradient(torch.tensor([0.0, 0.0]), Obj(), context)

        self.assertEqual(gradient.call_args.args[1:], (2.0, 1.0))

    def test_net_overlap_normalizes_external_map_to_placement_dtype(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.net_overlap import (
            NetOverlapRemovalPlugin,
        )

        params = Obj()
        params.ruplace_net_overlap_smooth = 0
        params.ruplace_net_overlap_weight = 0.05
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        data = Obj()
        data.flat_net2pin_start_map = torch.tensor([0, 1])
        data.flat_net2pin_map = torch.tensor([0])
        data.pin2node_map = torch.tensor([0])
        context = Obj()
        context.iteration = 1
        context.signal = lambda pos: CongestionSignal(
            torch.zeros(2, 2, dtype=torch.float32),
            overflow_map=torch.tensor(
                [[0.0, 0.0], [1.0, 0.0]], dtype=torch.float32
            ),
        )
        context.pin_positions = lambda pos: torch.tensor(
            [1.0, 1.0], dtype=pos.dtype
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.05,
            "applied_ratio": 0.05,
        })
        plugin = NetOverlapRemovalPlugin(params, db, data)

        changed = plugin.apply_gradient(
            torch.tensor([0.0, 0.0], dtype=torch.float64), Obj(), context
        )

        self.assertTrue(changed)
        gradients = context.add_scaled_movable_gradient.call_args.args[1:3]
        self.assertTrue(all(value.dtype == torch.float64 for value in gradients))

    def test_net_weighting_normalizes_external_map_to_placement_dtype(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            CongestionNetWeightingPlugin,
        )

        params = Obj()
        params.ruplace_net_weight_freq = 1
        params.ruplace_net_weight_gamma = 0.25
        params.ruplace_net_weight_max = 3.0
        params.ruplace_net_weight_normalization = "absolute"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        data = Obj()
        data.net_weights = torch.ones(1, dtype=torch.float64)
        data.flat_net2pin_start_map = torch.tensor([0, 1])
        data.flat_net2pin_map = torch.tensor([0])
        data.net_mask_ignore_large_degrees = torch.tensor([1])
        context = Obj()
        context.iteration = 1
        context.signal = lambda pos: CongestionSignal(
            torch.full((2, 2), 2.0, dtype=torch.float32)
        )
        context.pin_positions = lambda pos: torch.tensor(
            [1.0, 1.0], dtype=pos.dtype
        )
        plugin = CongestionNetWeightingPlugin(params, db, data)

        changed = plugin.apply_gradient(
            torch.tensor([0.0, 0.0], dtype=torch.float64), Obj(), context
        )

        self.assertTrue(changed)
        self.assertEqual(data.net_weights.dtype, torch.float64)
        self.assertEqual(data.net_weights.item(), 1.0)
        self.assertTrue(plugin.commit_post_gradient(
            torch.tensor([0.0, 0.0], dtype=torch.float64), Obj(), context
        ))
        self.assertGreater(data.net_weights.item(), 1.0)

    def test_skipped_post_gradient_net_weight_refresh_clears_pending_update(self):
        from dreamplace.ops.routability_opt.plugins.net_weighting import (
            CongestionNetWeightingPlugin,
        )

        plugin = CongestionNetWeightingPlugin.__new__(CongestionNetWeightingPlugin)
        plugin.params = Obj()
        plugin.params.ruplace_net_weight_freq = 2
        plugin.pending_weights = torch.tensor([2.0])
        context = Obj()
        context.iteration = 1

        self.assertFalse(plugin._update_weights(
            torch.zeros(2), context, defer=True
        ))
        self.assertIsNone(plugin.pending_weights)

    def test_force_schedule_skips_and_anneals_with_a_floor(self):
        from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin

        params = Obj()
        params.ruplace_force_apply_interval = 2
        params.ruplace_force_decay = 0.5
        params.ruplace_force_min_ratio = 0.2
        plugin = RoutabilityPlugin(params, Obj(), Obj())
        context = Obj()

        context.iteration = 1
        weight, metrics = plugin.scheduled_force_weight(context, 0.1)
        self.assertIsNone(weight)
        self.assertEqual(metrics["force_schedule_applied"], 0)

        context.iteration = 2
        weight, _ = plugin.scheduled_force_weight(context, 0.1)
        self.assertAlmostEqual(weight, 0.1)
        plugin.record_force_application()
        context.iteration = 4
        weight, _ = plugin.scheduled_force_weight(context, 0.1)
        self.assertAlmostEqual(weight, 0.05)
        plugin.record_force_application()
        plugin.record_force_application()
        context.iteration = 6
        weight, metrics = plugin.scheduled_force_weight(context, 0.1)
        self.assertAlmostEqual(weight, 0.02)
        self.assertAlmostEqual(metrics["force_weight_multiplier"], 0.2)

    def test_force_schedule_supports_phase_and_successful_application_budget(self):
        from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin

        params = Obj()
        params.ruplace_force_apply_interval = 10
        params.ruplace_force_apply_offset = 3
        params.ruplace_force_max_applications = 1
        params.ruplace_force_decay = 1.0
        params.ruplace_force_min_ratio = 0.0
        plugin = RoutabilityPlugin(params, Obj(), Obj())
        context = Obj()

        context.iteration = 10
        weight, metrics = plugin.scheduled_force_weight(context, 0.1)
        self.assertIsNone(weight)
        self.assertEqual(metrics["force_schedule_phase_hit"], 0)
        self.assertEqual(metrics["force_apply_offset"], 3)
        self.assertEqual(metrics["force_max_applications"], 1)

        context.iteration = 13
        weight, metrics = plugin.scheduled_force_weight(context, 0.1)
        self.assertAlmostEqual(weight, 0.1)
        self.assertEqual(metrics["force_schedule_applied"], 1)
        self.assertEqual(metrics["force_iteration"], 13)
        plugin.record_force_application()

        context.iteration = 23
        weight, metrics = plugin.scheduled_force_weight(context, 0.1)
        self.assertIsNone(weight)
        self.assertEqual(metrics["force_schedule_phase_hit"], 1)
        self.assertEqual(metrics["force_application_budget_exhausted"], 1)

    def test_directional_local_gradient_budget_stops_before_proxy_signal(self):
        from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
            DirectionalLocalCongestionGradientPlugin,
        )

        params = Obj()
        params.ruplace_directional_local_gradient_weight = 0.01
        params.ruplace_force_apply_interval = 1
        params.ruplace_force_max_applications = 1
        plugin = DirectionalLocalCongestionGradientPlugin(params, Obj(), Obj())
        plugin.force_applications = 1
        context = Obj()
        context.iteration = 2
        context.signal = mock.Mock(
            side_effect=AssertionError("exhausted budget evaluated the proxy")
        )

        changed = plugin.apply_gradient(torch.zeros(2), Obj(), context)

        self.assertFalse(changed)
        context.signal.assert_not_called()
        self.assertEqual(plugin.metrics["force_application_budget_exhausted"], 1)
        self.assertEqual(plugin.metrics["force_applications"], 1)

    def test_force_schedule_zero_decay_disables_later_applications(self):
        from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin

        params = Obj()
        params.ruplace_force_apply_interval = 1
        params.ruplace_force_decay = 0.0
        params.ruplace_force_min_ratio = 0.0
        plugin = RoutabilityPlugin(params, Obj(), Obj())
        context = Obj()

        context.iteration = 1
        weight, _ = plugin.scheduled_force_weight(context, 0.1)
        self.assertAlmostEqual(weight, 0.1)
        plugin.record_force_application()

        context.iteration = 2
        weight, metrics = plugin.scheduled_force_weight(context, 0.1)
        self.assertEqual(weight, 0.0)
        self.assertEqual(metrics["force_weight_multiplier"], 0.0)

    def test_force_schedule_rejects_invalid_phase_or_budget(self):
        from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin

        context = Obj()
        context.iteration = 1
        for offset, maximum, message in (
            (-1, -1, "offset"),
            (2, -1, "offset"),
            (0, -2, "maximum applications"),
        ):
            with self.subTest(offset=offset, maximum=maximum):
                params = Obj()
                params.ruplace_force_apply_interval = 2
                params.ruplace_force_apply_offset = offset
                params.ruplace_force_max_applications = maximum
                params.ruplace_force_decay = 1.0
                params.ruplace_force_min_ratio = 0.0
                plugin = RoutabilityPlugin(params, Obj(), Obj())
                with self.assertRaisesRegex(ValueError, message):
                    plugin.scheduled_force_weight(context, 0.1)

    def test_replicate_smoothing_preserves_constant_boundaries(self):
        from dreamplace.ops.routability_opt.plugins.utils import smooth_map

        value = torch.ones(3, 3)
        self.assertTrue(torch.equal(smooth_map(value, 1, "replicate"), value))
        self.assertLess(smooth_map(value, 1, "zero")[0, 0].item(), 1.0)

    def test_directional_congestion_map_selection_and_validation(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.utils import select_congestion_map

        horizontal = torch.tensor([[1.0, 3.0], [0.0, 2.0]])
        vertical = torch.tensor([[2.0, 1.0], [4.0, 0.0]])
        signal = CongestionSignal(
            torch.ones(2, 2), hv_overflow_map=torch.stack((horizontal, vertical))
        )
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "hv_max"),
            torch.maximum(horizontal, vertical),
        ))
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "hv_mean"),
            (horizontal + vertical) * 0.5,
        ))
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "horizontal"), horizontal
        ))
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "vertical"), vertical
        ))
        with self.assertRaisesRegex(ValueError, "congestion-map mode"):
            select_congestion_map(signal, "diagonal")

    def test_absolute_directional_feedback_preserves_preoverflow_pressure(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.utils import select_congestion_map

        horizontal = torch.tensor([[0.2, 0.8], [0.4, 0.6]])
        vertical = torch.tensor([[0.1, 0.3], [0.5, 0.7]])
        signal = CongestionSignal(
            utilization_map=torch.maximum(horizontal, vertical),
            hv_overflow_map=torch.zeros(2, 2, 2),
            hv_utilization_map=torch.stack((horizontal, vertical)),
        )

        self.assertEqual(select_congestion_map(signal, "hv_max").sum(), 0.0)
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "utilization_hv_max"),
            torch.maximum(horizontal, vertical),
        ))
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "utilization_hv_mean"),
            (horizontal + vertical) * 0.5,
        ))
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "utilization_horizontal"), horizontal
        ))
        self.assertTrue(torch.equal(
            select_congestion_map(signal, "utilization_vertical"), vertical
        ))

    def test_gpugr_proxy_retains_absolute_directional_utilization(self):
        from dreamplace.ops.routability_opt.proxy import GPUGRProxy

        params = Obj()
        params.ruplace_proxy_refresh_interval = 10
        route = Obj()
        route.utilization_map = torch.ones(2, 2)
        route.overflow_map = torch.zeros(2, 2)
        route.hv_overflow_map = torch.zeros(2, 2, 2)
        route.hv_utilization_map = torch.stack((
            torch.full((2, 2), 0.8), torch.full((2, 2), 0.6)
        ))
        route.metrics = {}
        backend = Obj()
        backend.run_route = mock.Mock(return_value=route)
        with mock.patch(
            "dreamplace.ops.routability_opt.proxy.build_gpugr_backend",
            return_value=backend,
        ):
            proxy = GPUGRProxy(params, Obj(), Obj())

        signal = proxy.evaluate(torch.zeros(2), iteration=1)

        self.assertTrue(torch.equal(
            signal.hv_utilization_map, route.hv_utilization_map
        ))
        backend.run_route.assert_called_once()

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

    def test_pipeline_enforces_total_successful_area_adjustment_budget(self):
        from dreamplace.ops.routability_opt.pipeline import (
            RoutabilityOptimizationPipeline,
        )
        from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin

        class AreaPlugin(RoutabilityPlugin):
            name = "area_test"

            def __init__(self):
                self.metrics = {}
                self.calls = 0

            def maybe_adjust_area(self, pos, model, context):
                self.calls += 1
                self.metrics = {"changed": 1.0}
                return True

        pipeline = RoutabilityOptimizationPipeline.__new__(
            RoutabilityOptimizationPipeline
        )
        params = Obj()
        params.max_num_area_adjust = 2
        params.ruplace_enforce_area_adjust_budget = 1
        params.ruplace_inflate_start_overflow = 1.0
        pipeline.params = params
        pipeline.iteration = 1
        pipeline.objective_calls = 0
        pipeline.objective_gate_skips = 0
        pipeline.gradient_calls = 0
        pipeline.gradient_gate_skips = 0
        pipeline.area_calls = 0
        pipeline.area_gate_skips = 0
        pipeline.area_adjustments = 0
        pipeline.context = Obj()
        pipeline.context.begin_iteration = mock.Mock()
        pipeline.proxy = Obj()
        plugin = AreaPlugin()
        pipeline.plugins = [plugin]
        pipeline.counters = {
            plugin.name: {
                "objective_attempts": 0,
                "objective_activations": 0,
                "gradient_attempts": 0,
                "gradient_activations": 0,
                "area_attempts": 0,
                "area_activations": 0,
            },
        }
        pipeline.metric_history = {plugin.name: {}}
        model = Obj()
        model.overflow = torch.tensor(0.5)

        self.assertTrue(pipeline.maybe_adjust_area(torch.zeros(2), model))
        self.assertTrue(pipeline.maybe_adjust_area(torch.zeros(2), model))
        self.assertFalse(pipeline.maybe_adjust_area(torch.zeros(2), model))

        self.assertEqual(plugin.calls, 2)
        self.assertEqual(pipeline.area_adjustments, 2)
        self.assertEqual(pipeline.area_gate_skips, 1)
        metrics = pipeline.metrics()["pipeline"]
        self.assertEqual(metrics["area_calls"], 3)
        self.assertEqual(metrics["area_adjustments"], 2)
        self.assertEqual(metrics["area_budget_enabled"], 1)
        self.assertEqual(metrics["max_area_adjustments"], 2)

        params.ruplace_enforce_area_adjust_budget = 0
        self.assertTrue(pipeline.maybe_adjust_area(torch.zeros(2), model))
        self.assertEqual(plugin.calls, 3)
        self.assertEqual(pipeline.area_adjustments, 3)
        metrics = pipeline.metrics()["pipeline"]
        self.assertEqual(metrics["area_budget_enabled"], 0)
        self.assertEqual(metrics["max_area_adjustments"], -1)

    def test_route_inflation_local_pass_does_not_shrink_when_disabled(self):
        from dreamplace.ops.routability_opt.ruplace_op import RUPlaceInflation

        engine = RUPlaceInflation.__new__(RUPlaceInflation)
        engine.params = Obj()
        engine.params.ruplace_local_inflate_gamma = 0.1
        engine.params.ruplace_allow_shrink = 0
        engine.current_inflate_ratio = torch.tensor([1.5, 1.0])
        engine._node_bin_utilization = mock.Mock(
            return_value=torch.tensor([0.0, 2.0])
        )
        engine.apply_node_ratios = mock.Mock(return_value=True)
        route = Obj()
        route.utilization_map = torch.zeros(2, 2)
        route.overflow_map = torch.zeros(2, 2)
        route.hv_overflow_map = None

        self.assertTrue(engine.apply(torch.zeros(4), route, global_pass=False))
        target = engine.apply_node_ratios.call_args.args[1]
        self.assertTrue(torch.allclose(target, torch.tensor([1.5, 1.2])))

    def test_pipeline_preserves_plugin_metric_history(self):
        from dreamplace.ops.routability_opt.pipeline import RoutabilityOptimizationPipeline

        params = Obj()
        params.ruplace_plugins = ["local_gradient"]
        params.ruplace_proxy = "rudy"
        params.ruplace_proxy_refresh_interval = 1
        db = Obj()
        with mock.patch(
            "dreamplace.ops.routability_opt.pipeline.build_congestion_proxy",
            return_value=Obj(),
        ):
            pipeline = RoutabilityOptimizationPipeline(params, db, Obj(), Obj())
        plugin = pipeline.plugins[0]
        plugin.metrics = {"field_norm": 2.0, "changed": True}
        pipeline._record_plugin_metrics(plugin)
        plugin.metrics = {"field_norm": 0.0, "changed": False}
        pipeline._record_plugin_metrics(plugin)

        stats = pipeline.metrics()["plugins"]["local_gradient"]["metric_stats"]
        self.assertEqual(stats["field_norm"]["count"], 2)
        self.assertEqual(stats["field_norm"]["nonzero_count"], 1)
        self.assertEqual(stats["field_norm"]["max"], 2.0)
        self.assertEqual(stats["field_norm"]["last"], 0.0)
        self.assertEqual(stats["field_norm"]["mean"], 1.0)
        self.assertNotIn("changed", stats)

    def test_pipeline_does_not_record_stale_metrics_on_skipped_call(self):
        from dreamplace.ops.routability_opt.pipeline import (
            RoutabilityOptimizationPipeline,
        )

        pipeline = RoutabilityOptimizationPipeline.__new__(
            RoutabilityOptimizationPipeline
        )
        params = Obj()
        params.ruplace_plugin_start_overflow = 1.0
        pipeline.params = params
        pipeline.iteration = 0
        pipeline.gradient_calls = 0
        pipeline.gradient_gate_skips = 0
        pipeline._objective_prepared = False
        pipeline.context = Obj()
        pipeline.context.begin_iteration = mock.Mock()
        pipeline.context.begin_gradient = mock.Mock()
        plugin = mock.Mock()
        plugin.name = "routeforce"
        plugin.metrics = {"stale_field_rms": 2.0}
        plugin.gradient_phase_enabled.return_value = True
        plugin.apply_gradient.return_value = False
        pipeline.plugins = [plugin]
        pipeline.counters = {
            "routeforce": {
                "gradient_attempts": 0,
                "gradient_activations": 0,
            },
        }
        pipeline.metric_history = {"routeforce": {}}
        model = Obj()
        model.overflow = torch.tensor(0.5)

        self.assertFalse(pipeline.apply_gradient(torch.zeros(2), model))

        self.assertEqual(plugin.metrics, {})
        self.assertEqual(pipeline.metric_history["routeforce"], {})

    def test_poisson_solver_is_finite_and_zero_mean(self):
        from dreamplace.ops.routability_opt.plugin_base import poisson_potential

        charge = torch.zeros(8, 8)
        charge[4, 4] = 1.0
        potential = poisson_potential(charge)
        self.assertTrue(torch.isfinite(potential).all())
        self.assertAlmostEqual(potential.mean().item(), 0.0, places=6)
        self.assertGreater(potential[4, 4].item(), potential[0, 0].item())

    def test_neumann_poisson_field_uses_physical_bins_and_zero_dc(self):
        from dreamplace.ops.routability_opt.plugin_base import (
            poisson_field_neumann,
        )

        class Echo:
            def __call__(self, value):
                return value.clone()

        charge = torch.zeros(4, 6)
        charge[1, 2] = 1.0
        potential, field_x, field_y = poisson_field_neumann(
            charge,
            bin_size_x=2.0,
            bin_size_y=1.0,
            operators=(Echo(), Echo(), Echo(), Echo()),
        )

        self.assertEqual(potential.shape, charge.shape)
        self.assertTrue(torch.isfinite(potential).all())
        self.assertTrue(torch.isfinite(field_x).all())
        self.assertTrue(torch.isfinite(field_y).all())
        self.assertEqual(potential[0, 0].item(), 0.0)
        self.assertEqual(field_x[0, 0].item(), 0.0)
        self.assertEqual(field_y[0, 0].item(), 0.0)
        self.assertGreater(field_x.abs().sum().item(), 0.0)
        self.assertGreater(field_y.abs().sum().item(), 0.0)
        # Mixed inverse transforms produce electric field E=-grad(phi); the
        # helper must negate it for objective-gradient descent semantics.
        self.assertLess(field_x[1, 2].item(), 0.0)
        self.assertLess(field_y[1, 2].item(), 0.0)

        with self.assertRaisesRegex(ValueError, "bin sizes"):
            poisson_field_neumann(
                charge, 0.0, 1.0,
                operators=(Echo(), Echo(), Echo(), Echo()),
            )

    def test_poisson_plugin_selects_neumann_dct_solver(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins import poisson_force
        from dreamplace.ops.routability_opt.plugins.poisson_force import (
            PoissonCongestionForcePlugin,
        )

        params = Obj()
        params.ruplace_poisson_weight = 0.01
        params.ruplace_poisson_smooth = 0
        params.ruplace_poisson_solver = "neumann_dct"
        params.ruplace_force_congestion_mode = "utilization"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        context = Obj()
        context.iteration = 1
        context.signal = lambda pos: CongestionSignal(torch.full((2, 2), 2.0))
        context.sample_vector_field = lambda pos, gx, gy: (
            torch.ones(1), torch.ones(1)
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = PoissonCongestionForcePlugin(params, db, Obj())
        plugin._neumann_operators = mock.Mock(return_value=())
        potential = torch.tensor([[0.0, 1.0], [1.0, 2.0]])
        with mock.patch.object(
            poisson_force,
            "poisson_field_neumann",
            return_value=(potential, torch.ones(2, 2), torch.ones(2, 2)),
        ) as solve:
            changed = plugin.apply_gradient(torch.zeros(2), Obj(), context)

        self.assertTrue(changed)
        solve.assert_called_once()
        self.assertEqual(plugin.metrics["poisson_solver_neumann_dct"], 1)

    def test_poisson_scalar_axis_balance_changes_force_ratio(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.poisson_force import (
            PoissonCongestionForcePlugin,
        )

        params = Obj()
        params.ruplace_poisson_weight = 0.01
        params.ruplace_poisson_smooth = 0
        params.ruplace_poisson_solver = "neumann_dct"
        params.ruplace_poisson_directional_mode = "scalar"
        params.ruplace_poisson_axis_balance = 4.0
        params.ruplace_force_congestion_mode = "utilization"
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        context = Obj()
        context.iteration = 0
        context.signal = lambda value: CongestionSignal(torch.ones(2, 2))
        context.sample_vector_field = lambda value, gx, gy: (
            gx.reshape(-1)[:1], gy.reshape(-1)[:1]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        plugin = PoissonCongestionForcePlugin(params, db, Obj())
        potential = torch.ones(2, 2)
        plugin._solve = mock.Mock(return_value=(
            potential, torch.ones(2, 2), torch.ones(2, 2), "neumann_dct"
        ))

        self.assertTrue(plugin.apply_gradient(torch.zeros(2), Obj(), context))

        call = context.add_scaled_movable_gradient.call_args
        self.assertAlmostEqual((call.args[1] / call.args[2]).item(), 4.0)
        self.assertEqual(plugin.metrics["poisson_directional_cross_track"], 0)
        self.assertEqual(plugin.metrics["poisson_axis_balance"], 4.0)

        params.ruplace_poisson_axis_balance = 0.0
        with self.assertRaisesRegex(ValueError, "axis_balance"):
            plugin.apply_gradient(torch.zeros(2), Obj(), context)

    def test_poisson_cross_track_neumann_preserves_axes_and_balance(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins import poisson_force
        from dreamplace.ops.routability_opt.plugins.poisson_force import (
            PoissonCongestionForcePlugin,
        )

        params = Obj()
        params.ruplace_poisson_weight = 0.01
        params.ruplace_poisson_smooth = 0
        params.ruplace_poisson_solver = "neumann_dct"
        params.ruplace_poisson_directional_mode = "cross_track"
        params.ruplace_poisson_axis_balance = 4.0
        params.ruplace_force_smoothing_padding = "replicate"
        db = Obj()
        db.num_nodes = db.num_movable_nodes = 1
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        plugin = PoissonCongestionForcePlugin(params, db, Obj())
        plugin._neumann_operators = mock.Mock(return_value=(None,) * 4)
        pos = torch.zeros(2, requires_grad=True)
        context = Obj()
        context.iteration = 0
        context.signal = lambda value: CongestionSignal(
            utilization_map=torch.ones(2, 2),
            hv_utilization_map=torch.stack((
                torch.full((2, 2), 2.0),
                torch.full((2, 2), 3.0),
            )),
        )
        context.sample_vector_field = lambda value, gx, gy: (
            gx.reshape(-1)[:1], gy.reshape(-1)[:1]
        )
        context.add_scaled_movable_gradient = mock.Mock(return_value={
            "reference_rms": 1.0,
            "field_rms": 1.0,
            "applied_scale": 0.01,
            "applied_ratio": 0.01,
        })
        horizontal = (
            torch.ones(2, 2), torch.full((2, 2), 9.0), torch.ones(2, 2)
        )
        vertical = (
            torch.ones(2, 2), torch.ones(2, 2), torch.full((2, 2), 7.0)
        )
        with mock.patch.object(
            poisson_force,
            "poisson_field_neumann",
            side_effect=[horizontal, vertical],
        ):
            self.assertTrue(plugin.apply_gradient(pos, Obj(), context))

        call = context.add_scaled_movable_gradient.call_args
        self.assertAlmostEqual((call.args[1] / call.args[2]).item(), 4.0)
        self.assertEqual(plugin.metrics["poisson_directional_cross_track"], 1)
        self.assertEqual(plugin.metrics["poisson_axis_balance"], 4.0)
        self.assertEqual(plugin.metrics["force_applications"], 1)

    def test_poisson_cross_track_rejects_missing_map_and_invalid_balance(self):
        from dreamplace.ops.routability_opt.plugin_base import CongestionSignal
        from dreamplace.ops.routability_opt.plugins.poisson_force import (
            PoissonCongestionForcePlugin,
        )

        params = Obj()
        params.ruplace_poisson_weight = 0.01
        params.ruplace_poisson_smooth = 0
        params.ruplace_poisson_solver = "periodic"
        params.ruplace_poisson_directional_mode = "cross_track"
        params.ruplace_poisson_axis_balance = 1.0
        db = Obj()
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 2.0
        context = Obj()
        context.iteration = 0
        context.signal = lambda value: CongestionSignal(
            utilization_map=torch.ones(2, 2)
        )
        plugin = PoissonCongestionForcePlugin(params, db, Obj())
        with self.assertRaisesRegex(ValueError, "requires H/V utilization"):
            plugin.apply_gradient(torch.zeros(2), Obj(), context)

        context.signal = lambda value: CongestionSignal(
            utilization_map=torch.ones(2, 2),
            hv_utilization_map=torch.ones(2, 2, 2),
        )
        params.ruplace_poisson_axis_balance = 0.0
        with self.assertRaisesRegex(ValueError, "axis_balance"):
            plugin.apply_gradient(torch.zeros(2), Obj(), context)

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

    def test_rectangle_overlap_map_preserves_clipped_macro_area(self):
        from dreamplace.ops.routability_opt.plugins.utils import rectangle_overlap_map

        value = rectangle_overlap_map(
            torch.tensor([0.5, -1.0]),
            torch.tensor([1.0, 3.5]),
            torch.tensor([2.5, 0.5]),
            torch.tensor([3.0, 5.0]),
            (4, 4),
            (0.0, 0.0, 4.0, 4.0),
        )

        expected = torch.tensor([
            [0.0, 0.5, 0.5, 0.25],
            [0.0, 1.0, 1.0, 0.0],
            [0.0, 0.5, 0.5, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ])
        self.assertTrue(torch.equal(value, expected))
        self.assertEqual(value.sum().item(), 4.25)

    def test_pin_porosity_rasterizes_fixed_macro_footprint(self):
        from dreamplace.ops.routability_opt.plugins.pin_porosity import (
            PinDensityPorosityPlugin,
        )

        params = Obj()
        params.ruplace_macro_area_threshold = 4.0
        params.ruplace_porosity_radius = 0
        params.ruplace_max_inflate_ratio = 2.0
        db = Obj()
        db.num_nodes = db.num_physical_nodes = 2
        db.num_movable_nodes = 1
        db.num_filler_nodes = 0
        db.routing_grid_xl = db.routing_grid_yl = 0.0
        db.routing_grid_xh = db.routing_grid_yh = 4.0
        data = Obj()
        data.node_size_x = torch.tensor([1.0, 2.0])
        data.node_size_y = torch.tensor([1.0, 2.0])
        data.target_density = torch.tensor(1.0)
        plugin = PinDensityPorosityPlugin(params, db, data)
        pos = torch.tensor([0.0, 0.5, 0.0, 1.0])

        porosity = plugin._macro_porosity_map(pos, (4, 4))

        expected = torch.tensor([
            [0.0, 0.5, 0.5, 0.0],
            [0.0, 1.0, 1.0, 0.0],
            [0.0, 0.5, 0.5, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ])
        expected /= expected[expected > 0].mean()
        self.assertTrue(torch.equal(porosity, expected))


if __name__ == "__main__":
    unittest.main()
