##
# @file   ruplace_unit_test.py
# @brief  CPU-only checks for RUPlace helper logic.
#

import os
import sys
import unittest

try:
    import torch
except ImportError:
    torch = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if torch is not None:
    from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter
    from dreamplace.ops.routability_opt.ruplace_op import RUPlaceController, RUPlaceInflation

from dreamplace.ops.gpugr.base import GPUGRRequest
from dreamplace.ops.gpugr.gpugr import build_gpugr_backend
from dreamplace.ops.gpugr.instantgr_backend import InstantGRBackend


class Obj(object):
    pass


class InstantGRBackendTest(unittest.TestCase):
    def test_parse_for_stat(self):
        metrics = InstantGRBackend._parse_for_stat("FOR_STAT 1.5 2 3.25 4")
        self.assertEqual(metrics["wirelength_cost"], 1.5)
        self.assertEqual(metrics["via_cost"], 2.0)
        self.assertEqual(metrics["overflow_cost"], 3.25)
        self.assertEqual(metrics["total_cost"], 4.0)

    def test_missing_native_inputs_explain_lef_def_gap(self):
        backend = InstantGRBackend()
        request = GPUGRRequest(design_name="dummy")
        with self.assertRaisesRegex(RuntimeError, "cap/.net inputs"):
            backend.route(request)

    def test_factory_builds_instantgr_without_xplace_state(self):
        params = Obj()
        params.ruplace_router_backend = "instantgr"
        backend = build_gpugr_backend(params)
        self.assertIsInstance(backend, InstantGRBackend)


@unittest.skipIf(torch is None, "torch is not installed")
class RUPlaceInflationTest(unittest.TestCase):
    def test_scale_preserves_centers_and_pin_locations(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1

        data = Obj()
        data.node_size_x = torch.tensor([1.0, 1.0, 1.0])
        data.node_size_y = torch.tensor([1.0, 1.0, 1.0])
        data.pin_offset_x = torch.tensor([0.2, 0.3])
        data.pin_offset_y = torch.tensor([0.4, 0.5])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        pos = torch.tensor([0.0, 2.0, 4.0, 0.0, 0.0, 0.0])
        old_centers = torch.stack((pos[:3] + 0.5, pos[3:] + 0.5), dim=1)
        old_pin_abs = torch.tensor([pos[0] + data.pin_offset_x[0], pos[3] + data.pin_offset_y[0]])

        inflation = RUPlaceInflation(params, placedb, data)
        inflation._scale_movable_nodes(pos, torch.tensor([1.21, 1.0]))

        new_centers = torch.stack(
            (pos[:3] + data.node_size_x * 0.5, pos[3:] + data.node_size_y * 0.5), dim=1
        )
        new_pin_abs = torch.tensor([pos[0] + data.pin_offset_x[0], pos[3] + data.pin_offset_y[0]])

        self.assertTrue(torch.allclose(old_centers[:2], new_centers[:2], atol=1e-6))
        self.assertTrue(torch.allclose(old_pin_abs, new_pin_abs, atol=1e-6))
        self.assertLess(data.node_size_x[2].item(), 1.0)

    def test_apply_uses_route_bins_and_bounded_area(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_local_inflate_gamma = 0.2

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 4.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"cluster_a/u1", b"cluster_b/u2", b"filler"]

        data = Obj()
        data.node_size_x = torch.tensor([1.0, 1.0, 2.0])
        data.node_size_y = torch.tensor([1.0, 1.0, 1.0])
        data.pin_offset_x = torch.tensor([0.0, 0.0])
        data.pin_offset_y = torch.tensor([0.0, 0.0])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        route.utilization_map = torch.tensor([[2.0, 1.0], [1.0, 1.0]])
        route.overflow_map = torch.clamp(route.utilization_map - 1.0, min=0.0)
        route.metrics = {}

        pos = torch.tensor([0.0, 2.0, 1.0, 0.0, 0.0, 0.0])
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertTrue(inflation.apply(pos, route, global_pass=True))
        self.assertGreater(data.node_size_x[0].item(), data.node_size_x[1].item())
        self.assertLessEqual((data.node_size_x * data.node_size_y).sum().item(), inflation.total_place_area.item() + 1e-6)

    def _threshold_fixture(self, util_threshold, gamma=0.35, exponent=1.0, bin_util=0.8):
        """Two 1x1 movable cells, one filler, in bins whose utilization is `bin_util`."""
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_min_inflate_ratio = 1.0
        params.ruplace_local_inflate_gamma = 0.2
        params.ruplace_global_cluster_mode = "none"
        params.ruplace_global_util_exponent = exponent
        params.ruplace_global_inflate_gamma = gamma
        params.ruplace_inflate_area_cap = 0.1
        params.ruplace_hv_inflate_gamma = 0.0
        params.ruplace_node_util_window = 0
        params.ruplace_inflate_util_threshold = util_threshold

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 4.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"same/u1", b"same/u2", b"filler"]

        data = Obj()
        data.node_size_x = torch.tensor([1.0, 1.0, 2.0])
        data.node_size_y = torch.tensor([1.0, 1.0, 1.0])
        data.pin_offset_x = torch.tensor([0.0, 0.0])
        data.pin_offset_y = torch.tensor([0.0, 0.0])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        # No bin is over capacity: legacy inflation (threshold 1.0) must be a no-op.
        route.utilization_map = torch.full((2, 2), float(bin_util))
        route.overflow_map = torch.clamp(route.utilization_map - 1.0, min=0.0)
        route.metrics = {}

        pos = torch.tensor([0.0, 2.0, 1.0, 0.0, 0.0, 0.0])
        return params, placedb, data, route, pos

    def test_inflate_util_threshold_default_leaves_underfull_bins_untouched(self):
        params, placedb, data, route, pos = self._threshold_fixture(1.0)
        before_x = data.node_size_x.clone()
        before_y = data.node_size_y.clone()
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertFalse(inflation.apply(pos, route, global_pass=True))
        self.assertTrue(torch.allclose(data.node_size_x, before_x))
        self.assertTrue(torch.allclose(data.node_size_y, before_y))
        self.assertTrue(
            torch.allclose(inflation.current_inflate_ratio, torch.ones(2), atol=1e-6)
        )

    def test_inflate_util_threshold_inflates_cells_below_capacity(self):
        gamma, exponent, bin_util, thr = 0.35, 1.0, 0.8, 0.7
        params, placedb, data, route, pos = self._threshold_fixture(
            thr, gamma=gamma, exponent=exponent, bin_util=bin_util
        )
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertTrue(inflation.apply(pos, route, global_pass=True))
        expected = 1.0 + gamma * ((bin_util / thr) - 1.0) ** exponent
        self.assertAlmostEqual(
            inflation.current_inflate_ratio[0].item(), expected, places=5
        )
        self.assertAlmostEqual(
            inflation.current_inflate_ratio[1].item(), expected, places=5
        )
        # areas scale by the ratio, edges by its square root
        self.assertAlmostEqual(
            data.node_size_x[0].item(), expected ** 0.5, places=5
        )
        self.assertLessEqual(
            (data.node_size_x * data.node_size_y).sum().item(),
            inflation.total_place_area.item() + 1e-6,
        )

    def test_inflate_util_threshold_applies_to_local_shrink_path(self):
        thr = 0.7
        params, placedb, data, route, pos = self._threshold_fixture(thr)
        params.ruplace_allow_shrink = 1
        params.ruplace_local_inflate_gamma = 1.0
        # room for the full 0.8/0.7 target so the budget does not clip the ratio
        params.ruplace_inflate_area_cap = 0.2
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertTrue(inflation.apply(pos, route, global_pass=False))
        # local allow_shrink path targets the (util / thr) ratio directly
        self.assertAlmostEqual(
            inflation.current_inflate_ratio[0].item(), 0.8 / thr, places=5
        )

    def test_global_inflation_is_uniform_within_hierarchy_cluster(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_local_inflate_gamma = 0.2
        params.ruplace_global_cluster_mode = "mean"

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 4.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"same/u1", b"same/u2", b"filler"]

        data = Obj()
        data.node_size_x = torch.tensor([1.0, 1.0, 2.0])
        data.node_size_y = torch.tensor([1.0, 1.0, 1.0])
        data.pin_offset_x = torch.tensor([0.0, 0.0])
        data.pin_offset_y = torch.tensor([0.0, 0.0])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        route.utilization_map = torch.tensor([[2.0, 1.0], [1.0, 1.0]])
        route.overflow_map = torch.clamp(route.utilization_map - 1.0, min=0.0)
        route.metrics = {}

        pos = torch.tensor([0.0, 2.0, 1.0, 0.0, 0.0, 0.0])
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertTrue(inflation.apply(pos, route, global_pass=True))
        self.assertTrue(torch.allclose(data.node_size_x[0], data.node_size_x[1], atol=1e-6))

    def test_global_inflation_can_use_per_cell_utilization(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_local_inflate_gamma = 0.2
        params.ruplace_global_cluster_mode = "none"

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 4.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"same/u1", b"same/u2", b"filler"]

        data = Obj()
        data.node_size_x = torch.tensor([1.0, 1.0, 2.0])
        data.node_size_y = torch.tensor([1.0, 1.0, 1.0])
        data.pin_offset_x = torch.tensor([0.0, 0.0])
        data.pin_offset_y = torch.tensor([0.0, 0.0])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        route.utilization_map = torch.tensor([[2.0, 1.0], [1.0, 1.0]])
        route.overflow_map = torch.clamp(route.utilization_map - 1.0, min=0.0)
        route.metrics = {}

        pos = torch.tensor([0.0, 2.0, 1.0, 0.0, 0.0, 0.0])
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertTrue(inflation.apply(pos, route, global_pass=True))
        self.assertGreater(data.node_size_x[0].item(), data.node_size_x[1].item())

    def test_global_inflation_can_use_directional_hv_overflow(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_global_cluster_mode = "none"
        params.ruplace_hv_inflate_gamma = 2.0
        params.ruplace_hv_inflate_mode = "max"

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 4.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"same/u1", b"same/u2", b"filler"]

        data = Obj()
        data.node_size_x = torch.tensor([1.0, 1.0, 2.0])
        data.node_size_y = torch.tensor([1.0, 1.0, 1.0])
        data.pin_offset_x = torch.tensor([0.0, 0.0])
        data.pin_offset_y = torch.tensor([0.0, 0.0])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        route.utilization_map = torch.ones(2, 2)
        route.overflow_map = torch.zeros(2, 2)
        route.hv_overflow_map = torch.tensor([
            [[0.5, 0.0], [0.0, 0.0]],
            [[0.0, 0.0], [0.0, 0.0]],
        ])
        route.metrics = {}

        pos = torch.tensor([0.0, 2.0, 1.0, 0.0, 0.0, 0.0])
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertTrue(inflation.apply(pos, route, global_pass=True))
        self.assertGreater(data.node_size_x[0].item(), data.node_size_x[1].item())

    def test_inflation_sanitizes_nonfinite_route_utilization(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_min_inflate_ratio = 1.0
        params.ruplace_local_inflate_gamma = 0.2
        params.ruplace_global_inflate_gamma = 0.35
        params.ruplace_global_cluster_mode = "none"
        params.ruplace_global_util_exponent = 1.0
        params.ruplace_inflate_area_cap = 1.0

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 4.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"a/u1", b"b/u2", b"filler"]

        data = Obj()
        data.node_size_x = torch.tensor([1.0, 1.0, 2.0])
        data.node_size_y = torch.tensor([1.0, 1.0, 1.0])
        data.pin_offset_x = torch.tensor([0.0, 0.0])
        data.pin_offset_y = torch.tensor([0.0, 0.0])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        route.utilization_map = torch.tensor([[float("nan"), 1.0], [2.0, float("inf")]])
        route.overflow_map = torch.clamp(torch.nan_to_num(route.utilization_map, nan=1.0) - 1.0, min=0.0)
        route.metrics = {}

        pos = torch.tensor([0.0, 2.0, 1.0, 0.0, 0.0, 0.0])
        inflation = RUPlaceInflation(params, placedb, data)
        self.assertTrue(inflation.apply(pos, route, global_pass=True))
        self.assertTrue(torch.isfinite(data.node_size_x).all())
        self.assertTrue(torch.isfinite(data.node_size_y).all())
        self.assertTrue(torch.isfinite(pos).all())

    def test_local_adjustment_can_shrink_overinflated_cells(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_min_inflate_ratio = 1.0
        params.ruplace_local_inflate_gamma = 0.5
        params.ruplace_inflate_area_cap = 1.0
        params.ruplace_allow_shrink = 1

        placedb = Obj()
        placedb.num_nodes = 3
        placedb.num_movable_nodes = 2
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 4.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"a/u1", b"b/u2", b"filler"]

        data = Obj()
        data.node_size_x = torch.tensor([1.2, 1.2, 0.56])
        data.node_size_y = torch.tensor([1.2, 1.2, 1.0])
        data.pin_offset_x = torch.tensor([0.1, 0.1])
        data.pin_offset_y = torch.tensor([0.1, 0.1])
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 2], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        route.utilization_map = torch.ones(2, 2)
        route.overflow_map = torch.zeros(2, 2)
        route.metrics = {}

        pos = torch.tensor([-0.1, 1.9, 4.22, -0.1, -0.1, 0.0])
        inflation = RUPlaceInflation(params, placedb, data)
        inflation.original_node_size_x = torch.tensor([1.0, 1.0])
        inflation.original_node_size_y = torch.tensor([1.0, 1.0])
        inflation.current_inflate_ratio = torch.tensor([1.44, 1.44])
        inflation.total_place_area = torch.tensor(3.0)

        self.assertTrue(inflation.apply(pos, route, global_pass=False))
        self.assertLess(data.node_size_x[0].item(), 1.2)
        self.assertGreaterEqual(data.node_size_x[0].item(), 1.0)
        self.assertAlmostEqual((data.node_size_x * data.node_size_y).sum().item(), 3.0, places=5)


@unittest.skipIf(torch is None, "torch is not installed")
class XplaceGGRAdapterMappingTest(unittest.TestCase):
    def test_scaled_and_raw_position_conversion(self):
        params = Obj()
        params.shift_factor = [100.0, 200.0]
        params.scale_factor = 2.0

        placedb = Obj()
        placedb.num_nodes = 3

        data = Obj()
        data.node_size_x = torch.tensor([2.0, 4.0, 6.0])
        data.node_size_y = torch.tensor([2.0, 4.0, 6.0])
        data.pos = [torch.empty(6)]

        adapter = object.__new__(XplaceGGRAdapter)
        adapter.params = params
        adapter.placedb = placedb
        adapter.data_collections = data
        adapter.device = torch.device("cpu")
        adapter.base_lpos = torch.tensor([[0.0, 0.0], [10.0, 20.0], [30.0, 40.0]])
        adapter.base_size = torch.tensor([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
        adapter.dp_to_x = {0: 1, 1: 2}

        pos = torch.tensor([2.0, 4.0, 6.0, 8.0, 10.0, 12.0])
        raw_lpos = adapter._scaled_to_raw_lpos(pos)
        self.assertTrue(torch.allclose(raw_lpos[1], torch.tensor([101.0, 204.0])))
        self.assertTrue(torch.allclose(raw_lpos[2], torch.tensor([102.0, 205.0])))

        centers = adapter._scaled_xplace_centers(pos)
        self.assertTrue(torch.allclose(centers[1], torch.tensor([3.0, 9.0])))
        self.assertTrue(torch.allclose(centers[2], torch.tensor([6.0, 12.0])))

    def test_admm_anchor_update_policies(self):
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.params = Obj()
        adapter.anchor_pos = None

        first = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
        second = torch.tensor([[2.0, 4.0], [6.0, 8.0]])

        adapter.params.ruplace_admm_anchor_update = "refresh"
        adapter._update_admm_anchor(first, refresh=True)
        adapter._update_admm_anchor(second, refresh=True)
        self.assertTrue(torch.allclose(adapter.anchor_pos, second))

        adapter.params.ruplace_admm_anchor_update = "static"
        adapter.anchor_pos = first.clone()
        adapter._update_admm_anchor(second, refresh=True)
        self.assertTrue(torch.allclose(adapter.anchor_pos, first))

        adapter.params.ruplace_admm_anchor_update = "ema"
        adapter.params.ruplace_admm_anchor_decay = 0.25
        adapter.anchor_pos = first.clone()
        adapter._update_admm_anchor(second, refresh=True)
        self.assertTrue(torch.allclose(adapter.anchor_pos, first * 0.25 + second * 0.75))


@unittest.skipIf(torch is None, "torch is not installed")
class RUPlaceControllerADMMTest(unittest.TestCase):
    def test_admm_weight_decay_and_floor(self):
        params = Obj()
        params.ruplace_admm_weight = 0.5
        params.ruplace_admm_weight_decay = 0.5
        params.ruplace_admm_min_weight = 0.2

        controller = object.__new__(RUPlaceController)
        controller.params = params
        controller.admm_applications = 0

        self.assertAlmostEqual(controller._admm_weight(), 0.5)
        controller.admm_applications = 1
        self.assertAlmostEqual(controller._admm_weight(), 0.25)
        controller.admm_applications = 4
        self.assertAlmostEqual(controller._admm_weight(), 0.2)

    def test_admm_gradient_clipping(self):
        params = Obj()
        params.ruplace_admm_grad_clip_norm = 5.0

        controller = object.__new__(RUPlaceController)
        controller.params = params

        grad = torch.tensor([3.0, 4.0, 0.0])
        self.assertTrue(torch.allclose(controller._clip_admm_gradient(grad), grad))

        grad = torch.tensor([6.0, 8.0, 0.0])
        clipped = controller._clip_admm_gradient(grad)
        self.assertAlmostEqual(clipped.norm().item(), 5.0, places=6)
        self.assertTrue(torch.allclose(clipped, torch.tensor([3.0, 4.0, 0.0]), atol=1e-6))


if __name__ == "__main__":
    unittest.main()
