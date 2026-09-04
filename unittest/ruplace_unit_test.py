##
# @file   ruplace_unit_test.py
# @brief  CPU-only checks for RUPlace helper logic.
#

import fcntl
import logging
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

try:
    import torch
except ImportError:
    torch = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if torch is not None:
    from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter
    from dreamplace.ops.routability_opt.pipeline import RoutabilityOptimizationPipeline
    from dreamplace.ops.routability_opt.ruplace_op import RUPlaceController, RUPlaceInflation

import dreamplace.Params as Params
from dreamplace.ops.gpugr.base import GPUGRRequest
from dreamplace.ops.gpugr.gpu_lock import (
    acquire_gpu_lock, maybe_serialized_gpu, release_gpu_lock, resolve_lock_mode,
)
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
        # No bin is over capacity: with an explicit threshold of 1.0 (the legacy
        # value, no longer the params.json default) inflation must be a no-op.
        route.utilization_map = torch.full((2, 2), float(bin_util))
        route.overflow_map = torch.clamp(route.utilization_map - 1.0, min=0.0)
        route.metrics = {}

        pos = torch.tensor([0.0, 2.0, 1.0, 0.0, 0.0, 0.0])
        return params, placedb, data, route, pos

    def test_inflate_util_threshold_one_leaves_underfull_bins_untouched(self):
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
        placedb.num_movable_nodes = 2
        placedb.num_physical_nodes = 3
        placedb.node_names = [b"u0", b"u1", b"fixed"]

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
        adapter.x_movable_ids = torch.tensor([1, 2], dtype=torch.long)
        adapter.gpdb = Obj()
        adapter.gpdb.dieInfo = lambda: (0.0, 1000.0, 0.0, 1000.0)

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


@unittest.skipIf(torch is None, "torch is not installed")
class GPULockReleaseTest(unittest.TestCase):
    """The in-process GGR lock must be dropped when global placement ends.

    ``acquire_gpu_lock`` blocks forever, so a leaked lock would hang this suite
    instead of failing it.  Every assertion therefore probes with a
    non-blocking ``flock`` on a private fd (which conflicts with the adapter's
    fd even inside one process) and only then re-acquires for real.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._previous = os.environ.get("RUPLACE_GPU_LOCK")
        self.lock_path = os.path.join(self._tmp.name, "gpu0.lock")
        os.environ["RUPLACE_GPU_LOCK"] = self.lock_path

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("RUPLACE_GPU_LOCK", None)
        else:
            os.environ["RUPLACE_GPU_LOCK"] = self._previous
        self._tmp.cleanup()

    def assertLockFree(self):
        with open(self.lock_path, "a+") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.fail("GPU lock %s is still held" % self.lock_path)
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def assertLockHeld(self):
        with open(self.lock_path, "a+") as stream:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def locked_adapter(self):
        adapter = object.__new__(XplaceGGRAdapter)
        adapter._gpu_lock_handle = acquire_gpu_lock(0, "unit-test")
        return adapter

    def test_close_releases_lock_and_is_idempotent(self):
        adapter = self.locked_adapter()
        self.assertLockHeld()
        self.assertTrue(adapter.close())
        self.assertLockFree()
        self.assertIsNone(adapter._gpu_lock_handle)
        self.assertFalse(adapter.close())
        self.assertLockFree()
        # Now that the probe proved it cannot block: a real second acquire.
        handle = acquire_gpu_lock(0, "unit-test-second")
        release_gpu_lock(handle)

    def test_close_without_lock_is_noop(self):
        adapter = object.__new__(XplaceGGRAdapter)
        adapter._gpu_lock_handle = None
        self.assertFalse(adapter.close())

    def test_controller_close_releases_adapter_lock(self):
        controller = object.__new__(RUPlaceController)
        controller.adapter = self.locked_adapter()
        controller.innovus_proxy = None
        self.assertLockHeld()
        controller.close()
        self.assertLockFree()
        controller.close()
        self.assertLockFree()

    def test_controller_close_survives_failing_proxy(self):
        class Boom(object):
            def close(self):
                raise RuntimeError("boom")

        controller = object.__new__(RUPlaceController)
        controller.adapter = self.locked_adapter()
        controller.innovus_proxy = Boom()
        controller.close()
        self.assertLockFree()

    def test_pipeline_close_releases_backend_lock(self):
        proxy = Obj()
        proxy.backend = self.locked_adapter()
        pipeline = object.__new__(RoutabilityOptimizationPipeline)
        pipeline.proxy = proxy
        self.assertLockHeld()
        pipeline.close()
        self.assertLockFree()

    def test_pipeline_close_walks_composite_proxy(self):
        class Recorder(object):
            def __init__(self):
                self.closed = 0

            def close(self):
                self.closed += 1

        backend = Recorder()
        inner = Obj()
        inner.backend = backend
        composite = Obj()
        composite.backend = None
        composite.proxies = [inner]
        pipeline = object.__new__(RoutabilityOptimizationPipeline)
        pipeline.proxy = composite
        pipeline.close()
        self.assertEqual(backend.closed, 1)


@unittest.skipIf(torch is None, "torch is not installed")
class GPULockModeTest(unittest.TestCase):
    """ruplace_gpu_lock_mode: 'call' (per router call), 'run' (whole GP), 'none'.

    Like GPULockReleaseTest every check probes with a non-blocking flock on a
    private fd, so a regression fails instead of hanging the suite.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lock_path = os.path.join(self._tmp.name, "gpu0.lock")
        self._env = {key: os.environ.get(key)
                     for key in ("RUPLACE_GPU_LOCK", "RUPLACE_GPU_LOCK_MODE")}
        os.environ["RUPLACE_GPU_LOCK"] = self.lock_path
        os.environ.pop("RUPLACE_GPU_LOCK_MODE", None)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    # ---- probes ---------------------------------------------------------
    def lock_is_held(self):
        # Opening with "a+" creates the file: only call once the test no
        # longer cares about its existence.
        with open(self.lock_path, "a+") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return False

    def assertLockHeld(self):
        self.assertTrue(self.lock_is_held(), "GPU lock %s is not held" % self.lock_path)

    def assertLockFree(self):
        self.assertFalse(self.lock_is_held(), "GPU lock %s is still held" % self.lock_path)

    def assertLockFileUntouched(self):
        self.assertFalse(os.path.exists(self.lock_path),
                         "GPU lock file %s was created" % self.lock_path)

    def make_adapter(self, mode, external=False):
        adapter = object.__new__(XplaceGGRAdapter)
        adapter.gpu_lock_mode = mode
        adapter.external_route_eval = external
        adapter._gpu_lock_device = 0
        adapter._gpu_lock_label = "unit-test in-process GPUGR"
        adapter._gpu_lock_handle = None
        return adapter

    def run_init(self, mode):
        """Drive the real __init__ up to _import_xplace, reporting lock state."""
        seen = {}

        def probe(adapter_self):
            # Record existence first: lock_is_held() opens (and creates) the file.
            seen["file_exists"] = os.path.exists(self.lock_path)
            seen["held"] = self.lock_is_held()
            seen["handle"] = adapter_self._gpu_lock_handle
            raise RuntimeError("unit test stops before the Xplace import")

        params = Obj()
        params.ruplace_xplace_root = self._tmp.name
        params.ruplace_external_route_eval = 0
        params.ruplace_route_gpu = 0
        params.ruplace_gpu_lock_mode = mode
        params.design_name = lambda: "unit_test"
        collections = Obj()
        collections.pos = [torch.zeros(1)]
        with mock.patch.object(XplaceGGRAdapter, "_import_xplace", probe):
            with self.assertRaises(RuntimeError):
                XplaceGGRAdapter(params, None, collections)
        return seen

    # ---- defaults -------------------------------------------------------
    def test_params_default_is_call(self):
        self.assertEqual(Params.Params().ruplace_gpu_lock_mode, "call")

    def test_resolve_lock_mode_env_override_and_precedence(self):
        self.assertEqual(resolve_lock_mode(), "call")
        os.environ["RUPLACE_GPU_LOCK_MODE"] = "none"
        self.assertEqual(resolve_lock_mode(), "none")
        # An explicit params/CLI value still wins over the environment.
        self.assertEqual(resolve_lock_mode("run"), "run")
        os.environ["RUPLACE_GPU_LOCK_MODE"] = "bogus"
        self.assertEqual(resolve_lock_mode(), "call")

    def test_maybe_serialized_gpu_honours_mode(self):
        with maybe_serialized_gpu("none", 0, "unit-test"):
            pass
        self.assertLockFileUntouched()
        with maybe_serialized_gpu("call", 0, "unit-test"):
            self.assertLockHeld()
        self.assertLockFree()

    # ---- __init__ -------------------------------------------------------
    def test_call_mode_takes_no_lock_in_init(self):
        seen = self.run_init("call")
        self.assertIsNone(seen["handle"])
        self.assertFalse(seen["held"])

    def test_run_mode_still_locks_for_the_whole_run(self):
        seen = self.run_init("run")
        self.assertIsNotNone(seen["handle"])
        self.assertTrue(seen["held"])
        # __init__ closes the adapter when the import fails.
        self.assertLockFree()

    def test_none_mode_never_touches_the_lock_file(self):
        seen = self.run_init("none")
        self.assertIsNone(seen["handle"])
        self.assertFalse(seen["file_exists"])
        # The probe itself opened the path; drop it before the next check.
        if os.path.exists(self.lock_path):
            os.remove(self.lock_path)
        adapter = self.make_adapter("none")
        with adapter._gpu_section("run_route"):
            pass
        self.assertLockFileUntouched()

    # ---- per-call sections ---------------------------------------------
    def test_call_mode_locks_only_inside_run_route(self):
        adapter = self.make_adapter("call")
        states = []

        def stub(pos):
            states.append(self.lock_is_held())
            return "route"

        adapter._run_route_inprocess = stub
        self.assertEqual(adapter.run_route(None), "route")
        self.assertEqual(states, [True])
        self.assertLockFree()

    def test_run_mode_section_is_a_noop(self):
        adapter = self.make_adapter("run")
        with adapter._gpu_section("run_route"):
            pass
        self.assertLockFileUntouched()

    def test_external_eval_never_locks_in_process(self):
        adapter = self.make_adapter("call", external=True)
        states = []

        def stub(pos):
            states.append(os.path.exists(self.lock_path))
            return "external"

        adapter._run_route_external = stub
        self.assertEqual(adapter.run_route(None), "external")
        self.assertEqual(states, [False])
        self.assertLockFileUntouched()

    def test_nested_wrapped_calls_do_not_deadlock(self):
        """A gradient section calling run_route must not block on its own flock."""
        adapter = self.make_adapter("call")
        calls = []

        def stub(pos):
            calls.append(self.lock_is_held())
            return "route"

        adapter._run_route_inprocess = stub
        done = threading.Event()
        errors = []

        def body():
            try:
                with adapter._gpu_section("admm gradient"):
                    adapter.run_route(None)
                    adapter.run_route(None)
                done.set()
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        worker = threading.Thread(target=body, daemon=True)
        worker.start()
        worker.join(30)
        self.assertEqual(errors, [])
        self.assertTrue(done.is_set(), "nested GPU sections deadlocked")
        self.assertEqual(calls, [True, True])
        self.assertLockFree()


class RUPlacePresetTest(unittest.TestCase):
    """Global-key half of the RUPlace congestion preset (dreamplace/Params.py)."""

    PRESET = {
        "target_density": 1.0,
        "gamma": 0.92,
        "gp_noise_ratio": 0.03,
        "stop_overflow": 0.10,
        "legalize_flag": 1,
        "num_bins_x": 512,
        "num_bins_y": 512,
    }

    @staticmethod
    def _params(data):
        params = Params.Params()
        params.fromJson(data)
        return params

    def test_preset_fills_global_keys_the_user_left_out(self):
        params = self._params({"routability_opt_flag": 1, "ruplace_flag": 1})
        for key, value in self.PRESET.items():
            self.assertEqual(getattr(params, key), value, key)
        stages = params.global_place_stages
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["iteration"], 1000)
        self.assertEqual(stages[0]["optimizer"], "nesterov")
        self.assertEqual(stages[0]["wirelength"], "weighted_average")
        self.assertEqual(stages[0]["num_bins_x"], 512)
        self.assertEqual(stages[0]["num_bins_y"], 512)
        # the ruplace_* half of the preset is carried by the params.json defaults
        self.assertEqual(params.ruplace_inflate_util_threshold, 0.6)
        self.assertEqual(params.ruplace_global_inflate_gamma, 0.7)
        self.assertEqual(params.ruplace_gr_grid, "step:2880")
        self.assertEqual(params.ruplace_gr_m1_routable, 0)
        self.assertEqual(params.ruplace_external_route_eval, 0)

    def test_explicit_user_values_win(self):
        params = self._params({
            "routability_opt_flag": 1,
            "ruplace_flag": 1,
            "target_density": 0.85,
            "stop_overflow": 0.07,
            "legalize_flag": 0,
            "num_bins_x": 1024,
            "global_place_stages": [{"iteration": 42, "optimizer": "adam"}],
        })
        self.assertEqual(params.target_density, 0.85)
        self.assertEqual(params.stop_overflow, 0.07)
        self.assertEqual(params.legalize_flag, 0)
        self.assertEqual(params.num_bins_x, 1024)
        self.assertEqual(len(params.global_place_stages), 1)
        self.assertEqual(params.global_place_stages[0]["iteration"], 42)
        # keys the user did not spell out are still filled in
        self.assertEqual(params.gamma, 0.92)
        self.assertEqual(params.gp_noise_ratio, 0.03)
        self.assertEqual(params.num_bins_y, 512)

    def test_no_preset_without_ruplace_flag(self):
        baseline = Params.Params()
        params = self._params({"routability_opt_flag": 1})
        for key in list(self.PRESET) + ["global_place_stages"]:
            self.assertEqual(getattr(params, key), getattr(baseline, key), key)
        # sanity: the untouched params.json defaults really do differ from the preset
        self.assertNotEqual(params.target_density, self.PRESET["target_density"])
        self.assertNotEqual(params.gamma, self.PRESET["gamma"])

    def test_preset_none_disables_it(self):
        baseline = Params.Params()
        params = self._params({"ruplace_flag": 1, "ruplace_preset": "none"})
        for key in list(self.PRESET) + ["global_place_stages"]:
            self.assertEqual(getattr(params, key), getattr(baseline, key), key)
        # the ruplace_* defaults are unaffected by ruplace_preset
        self.assertEqual(params.ruplace_inflate_util_threshold, 0.6)

    def test_applied_overrides_are_logged(self):
        with self.assertLogs(level="INFO") as captured:
            self._params({"routability_opt_flag": 1, "ruplace_flag": 1})
        messages = "\n".join(captured.output)
        self.assertIn("RUPlace preset 'congestion': target_density 0.8 -> 1.0", messages)
        self.assertIn("RUPlace preset 'congestion': gamma 4.0 -> 0.92", messages)

    def test_unknown_preset_warns_and_changes_nothing(self):
        baseline = Params.Params()
        with self.assertLogs(level="WARNING"):
            params = self._params({"ruplace_flag": 1, "ruplace_preset": "nope"})
        for key in list(self.PRESET) + ["global_place_stages"]:
            self.assertEqual(getattr(params, key), getattr(baseline, key), key)


@unittest.skipIf(torch is None, "torch is not installed")
class LgammaStopCriterionTest(unittest.TestCase):
    """Regression guard: best_metric[0] is reset to None after a routability /
    RUPlace area adjustment, and the divergence heuristic in
    NonLinearPlace.Lgamma_stop_criterion used to dereference it unconditionally.

    The criterion is a closure inside NonLinearPlace.__call__, so it is extracted
    from the *source* file by AST and executed against stub collaborators. Reading
    the file by explicit path keeps the test pinned to the source tree (never the
    install/ copy) and needs no compiled extensions.
    """

    SOURCE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "dreamplace",
        "NonLinearPlace.py",
    )

    @staticmethod
    def _extract(source_path, name):
        import ast
        import textwrap

        with open(source_path) as stream:
            source = stream.read()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return textwrap.dedent(ast.get_source_segment(source, node))
        raise AssertionError("%s not found in %s" % (name, source_path))

    def _make_criterion(self, best_metric):
        scope = {
            "torch": torch,
            "logging": logging,
            "best_metric": best_metric,
            "params": self._params(),
            "placedb": self._placedb(),
            "model": self._model(),
        }
        exec(self._extract(self.SOURCE, "Lgamma_stop_criterion"), scope)
        return scope["Lgamma_stop_criterion"]

    @staticmethod
    def _params():
        params = Obj()
        params.stop_overflow = 0.1
        params.target_density = 1.0
        return params

    @staticmethod
    def _placedb():
        placedb = Obj()
        placedb.regions = []
        return placedb

    @staticmethod
    def _model():
        return Obj()

    @staticmethod
    def _metric(hpwl, overflow, max_density=2.0):
        metric = Obj()
        metric.hpwl = hpwl
        metric.overflow = [overflow]
        metric.max_density = [max_density]
        return metric

    def _metrics(self, cur_overflow, cur_hpwl):
        """51 entries shaped [[metric]]; overflow rises from metrics[-50] to metrics[-1]."""
        history = [[[self._metric(1.0e6, 0.30)]] for _ in range(50)]
        history.append([[self._metric(cur_hpwl, cur_overflow)]])
        return history

    def test_none_best_metric_skips_heuristic(self):
        # Lgamma_step below 100 so only the divergence heuristic can fire.
        criterion = self._make_criterion([None])
        self.assertFalse(criterion(0, self._metrics(cur_overflow=0.40, cur_hpwl=1.0e9)))

    def test_none_best_metric_with_falling_overflow_matches_legacy(self):
        # The only case both the pre-fix and post-fix code execute with a None
        # best_metric: the overflow comparison short-circuits before the
        # dereference, so the guard cannot change the result.
        criterion = self._make_criterion([None])
        self.assertFalse(criterion(0, self._metrics(cur_overflow=0.20, cur_hpwl=1.0e9)))

    def test_divergence_still_detected_when_best_metric_is_recorded(self):
        criterion = self._make_criterion([self._metric(1.0e6, 0.30)])
        # overflow rises and hpwl > 2 * best hpwl -> legacy True
        self.assertTrue(criterion(0, self._metrics(cur_overflow=0.40, cur_hpwl=3.0e6)))

    def test_no_divergence_when_hpwl_within_two_times_best(self):
        criterion = self._make_criterion([self._metric(1.0e6, 0.30)])
        # overflow rises but hpwl <= 2 * best hpwl -> legacy False
        self.assertFalse(criterion(0, self._metrics(cur_overflow=0.40, cur_hpwl=1.5e6)))

    def test_short_history_returns_false(self):
        criterion = self._make_criterion([None])
        self.assertFalse(criterion(0, [[[self._metric(1.0e6, 0.30)]]]))


if __name__ == "__main__":
    unittest.main()
