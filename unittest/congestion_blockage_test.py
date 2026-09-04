##
# @file   congestion_blockage_test.py
# @brief  CPU-only checks for RUPlace congestion-driven soft blockage.
#
# Covers the router-grid -> density-grid resample (extents and x/y orientation),
# the threshold / cap / smoothing / decay pipeline, the fixed-occupancy headroom
# cap, the controller refresh, and the default-off no-op guarantee.
#

import os
import sys
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dreamplace.ops.electric_potential.congestion_blockage as cb
from dreamplace.ops.routability_opt.ruplace_op import RUPlaceController, RUPlaceInflation

try:
    from dreamplace.ops.electric_potential.electric_overflow import ElectricOverflow
except ImportError:  # compiled extension only exists in the install tree
    ElectricOverflow = None


class Obj(object):
    pass


# Router grid: 4 x 8 bins (deliberately asymmetric) over (10, 20) - (50, 100).
# Placement region: (0, 0) - (60, 120), 6 x 12 density bins of 10 x 10.
ROUTE_XL, ROUTE_YL, ROUTE_XH, ROUTE_YH = 10.0, 20.0, 50.0, 100.0
PLACE_XL, PLACE_YL, PLACE_XH, PLACE_YH = 0.0, 0.0, 60.0, 120.0
NBX, NBY = 6, 12


def resample(util, mode="nearest"):
    return cb.resample_router_map(
        util,
        ROUTE_XL, ROUTE_YL, ROUTE_XH, ROUTE_YH,
        NBX, NBY,
        PLACE_XL, PLACE_YL, PLACE_XH, PLACE_YH,
        mode=mode,
    )


class ResampleTest(unittest.TestCase):
    def test_hot_router_column_lands_in_the_same_x_range(self):
        # one hot column at router x index 2 -> placement x in [30, 40)
        util = torch.zeros(4, 8)
        util[2, :] = 1.0
        out = resample(util)
        self.assertEqual(tuple(out.shape), (NBX, NBY))
        # only the density column whose center (35) falls in [30, 40) is hot
        self.assertTrue(torch.equal(out[3], torch.ones(NBY)))
        for i in (0, 1, 2, 4, 5):
            self.assertTrue(torch.equal(out[i], torch.zeros(NBY)), "row %d" % i)

    def test_hot_router_row_lands_in_the_same_y_range(self):
        # transposing the resample would move this into x; assert it does not
        util = torch.zeros(4, 8)
        util[:, 1] = 1.0
        out = resample(util)
        self.assertTrue(torch.equal(out[:, 3], torch.ones(NBX)))
        for j in range(NBY):
            if j == 3:
                continue
            self.assertTrue(torch.equal(out[:, j], torch.zeros(NBX)), "col %d" % j)

    def test_bins_outside_the_routing_grid_clamp_to_the_edge(self):
        # density bins at x centers 5 and 15 both sit at/below the routing grid
        # left edge (10), so both take router column 0
        util = torch.zeros(4, 8)
        util[0, :] = 0.9
        out = resample(util)
        self.assertAlmostEqual(float(out[0, 5]), 0.9, places=6)
        self.assertAlmostEqual(float(out[1, 5]), 0.9, places=6)
        self.assertAlmostEqual(float(out[2, 5]), 0.0, places=6)
        # and the top-right corner clamps to the last router bin
        util2 = torch.zeros(4, 8)
        util2[3, 7] = 0.7
        out2 = resample(util2)
        self.assertAlmostEqual(float(out2[5, 11]), 0.7, places=6)

    def test_bilinear_is_monotone_along_x_and_flat_along_y(self):
        util = torch.arange(4, dtype=torch.float32).view(4, 1).expand(4, 8).contiguous()
        out = resample(util, mode="bilinear")
        for j in range(NBY):
            self.assertTrue(torch.equal(out[:, j], out[:, 0]))
        diffs = out[1:, 0] - out[:-1, 0]
        self.assertTrue(bool((diffs >= -1e-6).all()))
        self.assertGreater(float(out[-1, 0]), float(out[0, 0]))

    def test_uniform_map_is_preserved(self):
        util = torch.full((4, 8), 0.42)
        out = resample(util, mode="bilinear")
        self.assertTrue(torch.allclose(out, torch.full((NBX, NBY), 0.42)))


class BlockageMapTest(unittest.TestCase):
    def test_threshold_ramp_and_cap(self):
        util = torch.tensor([[0.5, 0.7, 0.85, 1.0, 2.0]])
        extra = cb.compute_blockage_map(
            util, blockage=0.4, threshold=0.7, blockage_max=0.5, smooth=0
        )
        # below/at the threshold nothing is blocked
        self.assertAlmostEqual(float(extra[0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(extra[0, 1]), 0.0, places=6)
        # halfway up the ramp: 0.4 * (0.85 - 0.7) / 0.3 = 0.2
        self.assertAlmostEqual(float(extra[0, 2]), 0.2, places=6)
        # at and beyond capacity the ramp saturates at `blockage`
        self.assertAlmostEqual(float(extra[0, 3]), 0.4, places=6)
        self.assertAlmostEqual(float(extra[0, 4]), 0.4, places=6)

    def test_blockage_max_caps_the_ramp(self):
        util = torch.tensor([[1.5]])
        extra = cb.compute_blockage_map(
            util, blockage=0.8, threshold=0.7, blockage_max=0.25, smooth=0
        )
        self.assertAlmostEqual(float(extra[0, 0]), 0.25, places=6)

    def test_zero_blockage_returns_none(self):
        util = torch.full((3, 3), 2.0)
        self.assertIsNone(
            cb.compute_blockage_map(util, 0.0, 0.7, 0.5, 1)
        )

    def test_smoothing_spreads_and_conserves(self):
        util = torch.zeros(5, 5)
        util[2, 2] = 2.0
        sharp = cb.compute_blockage_map(util, 0.3, 0.7, 0.5, smooth=0)
        blurred = cb.compute_blockage_map(util, 0.3, 0.7, 0.5, smooth=1)
        self.assertAlmostEqual(float(sharp[2, 2]), 0.3, places=6)
        # blur lowers the peak and lights up the 3x3 neighbourhood
        self.assertAlmostEqual(float(blurred[2, 2]), 0.3 / 9.0, places=6)
        self.assertGreater(float(blurred[1, 2]), 0.0)
        self.assertGreater(float(blurred[1, 1]), 0.0)
        self.assertAlmostEqual(float(blurred[0, 0]), 0.0, places=6)
        # interior blur is mass conserving
        self.assertAlmostEqual(float(blurred.sum()), float(sharp.sum()), places=5)
        # blur can only lower the peak, so the cap stays meaningful
        self.assertLessEqual(float(blurred.max()), float(sharp.max()) + 1e-9)

    def test_smooth_zero_is_identity(self):
        m = torch.rand(4, 4)
        self.assertIs(cb.box_blur(m, 0), m)


class DecayTest(unittest.TestCase):
    def test_first_refresh_takes_the_fresh_map(self):
        cur = torch.tensor([[0.3]])
        self.assertIs(cb.blend_decay(None, cur, 0.5), cur)

    def test_stale_blockage_fades_when_congestion_clears(self):
        prev = torch.tensor([[0.4, 0.4]])
        cur = torch.tensor([[0.0, 0.4]])
        out = cb.blend_decay(prev, cur, 0.5)
        # bin 0 is clean now -> halves; bin 1 still congested -> holds
        self.assertAlmostEqual(float(out[0, 0]), 0.2, places=6)
        self.assertAlmostEqual(float(out[0, 1]), 0.4, places=6)

    def test_fresh_congestion_wins_over_the_decayed_map(self):
        prev = torch.tensor([[0.1]])
        cur = torch.tensor([[0.35]])
        out = cb.blend_decay(prev, cur, 0.5)
        self.assertAlmostEqual(float(out[0, 0]), 0.35, places=6)

    def test_decay_never_exceeds_the_cap(self):
        prev = torch.full((3, 3), 0.5)
        cur = torch.full((3, 3), 0.5)
        out = cb.blend_decay(prev, cur, 0.9)
        self.assertLessEqual(float(out.max()), 0.5 + 1e-9)


class HeadroomTest(unittest.TestCase):
    def test_fixed_occupied_bins_get_no_blockage(self):
        capacity = 100.0  # target_density * bin_area
        extra = torch.tensor([[0.4, 0.4, 0.4]])
        # fixed occupancy fractions 0.0, 0.3, 0.6 of bin capacity
        fixed = torch.tensor([[0.0, 30.0, 60.0]])
        out = cb.cap_by_fixed_headroom(extra, fixed, capacity, blockage_max=0.5)
        self.assertAlmostEqual(float(out[0, 0]), 0.4, places=6)   # headroom 0.5
        self.assertAlmostEqual(float(out[0, 1]), 0.2, places=6)   # headroom 0.2
        self.assertAlmostEqual(float(out[0, 2]), 0.0, places=6)   # already over cap

    def test_no_fixed_map_only_applies_the_cap(self):
        extra = torch.tensor([[0.9]])
        out = cb.cap_by_fixed_headroom(extra, None, 100.0, blockage_max=0.5)
        self.assertAlmostEqual(float(out[0, 0]), 0.5, places=6)


class ApplyToDensityMapTest(unittest.TestCase):
    def test_extra_is_added_in_area_units_scaled_by_capacity(self):
        capacity = 200.0
        initial = torch.tensor([[0.0, 40.0]])
        blockage = torch.tensor([[0.25, 0.25]])
        applied = cb.apply_blockage_to_density_map(
            initial, blockage, capacity, blockage_max=0.5
        )
        # bin 0: full 0.25 of capacity; bin 1: 0.2 fixed + 0.25 <= 0.5, so full too
        self.assertAlmostEqual(float(applied[0, 0]), 50.0, places=5)
        self.assertAlmostEqual(float(applied[0, 1]), 50.0, places=5)
        self.assertAlmostEqual(float(initial[0, 0]), 50.0, places=5)
        self.assertAlmostEqual(float(initial[0, 1]), 90.0, places=5)

    def test_none_blockage_leaves_the_map_bitwise_untouched(self):
        initial = torch.rand(8, 8, dtype=torch.float64)
        reference = initial.clone()
        applied = cb.apply_blockage_to_density_map(initial, None, 3.5, 0.5)
        self.assertIsNone(applied)
        self.assertTrue(torch.equal(initial, reference))

    def test_the_stored_blockage_map_is_not_mutated(self):
        blockage = torch.tensor([[0.25, 0.25]])
        reference = blockage.clone()
        initial = torch.zeros(1, 2)
        cb.apply_blockage_to_density_map(initial, blockage, 200.0, 0.5)
        self.assertTrue(torch.equal(blockage, reference))
        # a second application must reproduce the first exactly
        initial2 = torch.zeros(1, 2)
        cb.apply_blockage_to_density_map(initial2, blockage, 200.0, 0.5)
        self.assertTrue(torch.equal(initial, initial2))


class FakeDensityOp(object):
    """Just enough of ElectricOverflow for the controller path."""

    def __init__(self, num_bins_x, num_bins_y, target_density=1.0, bin_size=10.0):
        self.num_bins_x = num_bins_x
        self.num_bins_y = num_bins_y
        self.bin_size_x = bin_size
        self.bin_size_y = bin_size
        self.target_density = target_density
        self.bin_center_x = torch.zeros(num_bins_x)
        self.fixed_density_map = torch.zeros(num_bins_x, num_bins_y)
        self.congestion_blockage_map = None
        self.congestion_blockage_max = 1.0
        self.initial_density_map = torch.zeros(num_bins_x, num_bins_y)

    def capacity_per_bin(self):
        return self.target_density * self.bin_size_x * self.bin_size_y

    def set_congestion_blockage_map(self, blockage_map, blockage_max=1.0):
        self.congestion_blockage_map = blockage_map
        self.congestion_blockage_max = float(blockage_max)
        self.initial_density_map = None


class FakeInflation(object):
    def __init__(self):
        self.blocked_area = None
        self.rescaled = 0

    def set_blocked_area(self, blocked_area):
        self.blocked_area = blocked_area

    def rescale_fillers(self, pos):
        self.rescaled += 1
        return False


class StubAdapter(object):
    """Counts router calls and hands back an alternating hot column."""

    def __init__(self, hot_columns=(2, 1)):
        self.calls = 0
        self.hot_columns = list(hot_columns)

    def run_route(self, pos):
        route = make_route(self.hot_columns[self.calls % len(self.hot_columns)])
        self.calls += 1
        return route


def make_controller(**overrides):
    ctrl = RUPlaceController.__new__(RUPlaceController)
    params = Obj()
    params.ruplace_congestion_blockage = 0.3
    params.ruplace_congestion_blockage_threshold = 0.7
    params.ruplace_congestion_blockage_max = 0.5
    params.ruplace_congestion_blockage_smooth = 0
    params.ruplace_congestion_blockage_decay = 0.5
    params.ruplace_congestion_blockage_start_overflow = 0.5
    # standalone refresh schedule / budget mode: defaults are the legacy no-ops
    params.ruplace_congestion_blockage_refresh_interval = 0
    params.ruplace_congestion_blockage_max_refreshes = 0
    params.ruplace_congestion_blockage_stop_overflow = 0.0
    params.ruplace_congestion_blockage_budget_mode = "shared"
    params.ruplace_local_inflate_max_rounds = 3
    params.ruplace_hv_inflate_mode = "max"
    for key, value in overrides.items():
        setattr(params, key, value)
    ctrl.params = params

    placedb = Obj()
    placedb.routing_grid_xl = ROUTE_XL
    placedb.routing_grid_yl = ROUTE_YL
    placedb.routing_grid_xh = ROUTE_XH
    placedb.routing_grid_yh = ROUTE_YH
    placedb.xl = PLACE_XL
    placedb.yl = PLACE_YL
    placedb.xh = PLACE_XH
    placedb.yh = PLACE_YH
    ctrl.placedb = placedb

    ctrl.blockage_map = None
    ctrl.blockage_refreshes = 0
    ctrl.blockage_calls = 0
    ctrl.last_blockage_refresh_call = None
    ctrl._last_route_for_blockage = None
    ctrl.inflation = FakeInflation()
    ctrl.adapter = StubAdapter()
    ctrl.innovus_proxy = None
    # legacy (non-adaptive) inflation, already exhausted: maybe_inflate() then
    # returns False without routing, which is the state that used to freeze the
    # blockage map for the rest of global placement.
    ctrl.adaptive_profile = None
    ctrl.global_inflation_done = True
    ctrl.inflation_rounds = 3
    return ctrl


def make_model(density_op, overflow=0.2):
    model = Obj()
    model.overflow = overflow
    collections = Obj()
    collections.density_op = density_op
    collections.density_overflow_op = None
    model.op_collections = collections
    return model


def make_route(hot_x=2):
    route = Obj()
    hv = torch.zeros(2, 4, 8)
    hv[0, hot_x, :] = 2.0   # horizontal at 2x capacity
    hv[1, hot_x, :] = 0.1
    route.hv_utilization_map = hv
    route.utilization_map = hv.max(dim=0).values
    return route


class ControllerBlockageTest(unittest.TestCase):
    def test_refresh_installs_a_map_on_the_density_ops(self):
        ctrl = make_controller()
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op)
        ctrl._last_route_for_blockage = make_route()
        self.assertTrue(ctrl._maybe_update_blockage(torch.zeros(4), model))
        self.assertIsNotNone(op.congestion_blockage_map)
        self.assertEqual(op.congestion_blockage_max, 0.5)
        self.assertIsNone(op.initial_density_map)  # invalidated for rebuild
        # H utilization 2.0 saturates the ramp -> the full 0.3
        self.assertAlmostEqual(float(op.congestion_blockage_map[3, 0]), 0.3, places=6)
        self.assertAlmostEqual(float(op.congestion_blockage_map[0, 0]), 0.0, places=6)
        # blocked area = sum(extra) * bin_area = 12 bins * 0.3 * 100
        self.assertAlmostEqual(ctrl.inflation.blocked_area, 12 * 0.3 * 100.0, places=4)
        self.assertEqual(ctrl.inflation.rescaled, 1)
        self.assertEqual(ctrl.blockage_refreshes, 1)

    def test_disabled_by_default_param(self):
        ctrl = make_controller(ruplace_congestion_blockage=0.0)
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op)
        ctrl._last_route_for_blockage = make_route()
        self.assertFalse(ctrl._maybe_update_blockage(torch.zeros(4), model))
        self.assertIsNone(op.congestion_blockage_map)
        self.assertIsNotNone(op.initial_density_map)
        self.assertIsNone(ctrl.inflation.blocked_area)

    def test_gated_by_start_overflow(self):
        ctrl = make_controller()
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op, overflow=0.8)
        ctrl._last_route_for_blockage = make_route()
        self.assertFalse(ctrl._maybe_update_blockage(torch.zeros(4), model))
        self.assertIsNone(op.congestion_blockage_map)

    def test_no_route_means_no_refresh(self):
        ctrl = make_controller()
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op)
        self.assertFalse(ctrl._maybe_update_blockage(torch.zeros(4), model))

    def test_second_refresh_decays_a_cleared_hotspot(self):
        ctrl = make_controller()
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op)
        ctrl._last_route_for_blockage = make_route()
        ctrl._maybe_update_blockage(torch.zeros(4), model)
        clean = Obj()
        clean.hv_utilization_map = torch.zeros(2, 4, 8)
        clean.utilization_map = torch.zeros(4, 8)
        ctrl._last_route_for_blockage = clean
        self.assertTrue(ctrl._maybe_update_blockage(torch.zeros(4), model))
        self.assertAlmostEqual(float(ctrl.blockage_map[3, 0]), 0.15, places=6)

    def test_repeated_identical_refresh_is_not_reported_as_a_change(self):
        ctrl = make_controller(ruplace_congestion_blockage_decay=1.0)
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op)
        ctrl._last_route_for_blockage = make_route()
        self.assertTrue(ctrl._maybe_update_blockage(torch.zeros(4), model))
        ctrl._last_route_for_blockage = make_route()
        self.assertFalse(ctrl._maybe_update_blockage(torch.zeros(4), model))
        self.assertEqual(ctrl.blockage_refreshes, 1)

    def test_fixed_occupancy_limits_the_installed_map(self):
        ctrl = make_controller()
        op = FakeDensityOp(NBX, NBY)
        # bin (3, 0) is 40% occupied by fixed cells -> only 0.1 headroom left
        op.fixed_density_map[3, 0] = 0.4 * op.capacity_per_bin()
        model = make_model(op)
        ctrl._last_route_for_blockage = make_route()
        ctrl._maybe_update_blockage(torch.zeros(4), model)
        self.assertAlmostEqual(float(op.congestion_blockage_map[3, 0]), 0.1, places=6)
        self.assertAlmostEqual(float(op.congestion_blockage_map[3, 1]), 0.3, places=6)


class BlockageScheduleTest(unittest.TestCase):
    """The refresh schedule decoupled from the cell-inflation schedule."""

    def drive(self, ctrl, model, routes):
        """Run one _maybe_update_blockage per entry; None == inflation routed nothing."""
        fired = []
        for index, route in enumerate(routes, start=1):
            ctrl._last_route_for_blockage = route
            if ctrl._maybe_update_blockage(torch.zeros(4), model):
                fired.append(index)
        return fired

    def test_default_off_only_refreshes_when_inflation_routed(self):
        ctrl = make_controller()
        model = make_model(FakeDensityOp(NBX, NBY))
        routes = [make_route(2), None, make_route(1), None, None, make_route(1)]
        self.assertEqual(self.drive(ctrl, model, routes), [1, 3, 6])
        # legacy path never routes on its own
        self.assertEqual(ctrl.adapter.calls, 0)
        self.assertEqual(ctrl.blockage_refreshes, 3)

    def test_interval_keeps_refreshing_after_inflation_is_exhausted(self):
        ctrl = make_controller(ruplace_congestion_blockage_refresh_interval=2)
        model = make_model(FakeDensityOp(NBX, NBY))
        # inflation is done, so it hands the blockage no congestion map at all
        self.assertEqual(self.drive(ctrl, model, [None] * 6), [1, 3, 5])
        self.assertEqual(ctrl.adapter.calls, 3)
        self.assertEqual(ctrl.blockage_refreshes, 3)

    def test_interval_reuses_a_route_inflation_already_produced(self):
        ctrl = make_controller(ruplace_congestion_blockage_refresh_interval=2)
        model = make_model(FakeDensityOp(NBX, NBY))
        routes = [make_route(2), None, make_route(1), None, None, make_route(1)]
        self.assertEqual(self.drive(ctrl, model, routes), [1, 3, 5])
        # only call 5 had no route of its own
        self.assertEqual(ctrl.adapter.calls, 1)

    def test_interval_of_one_refreshes_every_call(self):
        ctrl = make_controller(ruplace_congestion_blockage_refresh_interval=1)
        model = make_model(FakeDensityOp(NBX, NBY))
        self.assertEqual(self.drive(ctrl, model, [None] * 4), [1, 2, 3, 4])
        self.assertEqual(ctrl.adapter.calls, 4)

    def test_a_no_op_refresh_does_not_re_fire_before_the_interval(self):
        # identical maps + decay 1.0 -> no material change, so the attempt must
        # still consume the interval slot
        ctrl = make_controller(
            ruplace_congestion_blockage_refresh_interval=2,
            ruplace_congestion_blockage_decay=1.0,
        )
        ctrl.adapter = StubAdapter(hot_columns=(2,))
        model = make_model(FakeDensityOp(NBX, NBY))
        self.assertEqual(self.drive(ctrl, model, [None] * 6), [1])
        self.assertEqual(ctrl.adapter.calls, 3)   # calls 1, 3, 5
        self.assertEqual(ctrl.blockage_refreshes, 1)

    def test_max_refreshes_caps_material_updates_and_router_calls(self):
        ctrl = make_controller(
            ruplace_congestion_blockage_refresh_interval=1,
            ruplace_congestion_blockage_max_refreshes=2,
        )
        model = make_model(FakeDensityOp(NBX, NBY))
        self.assertEqual(self.drive(ctrl, model, [None] * 6), [1, 2])
        self.assertEqual(ctrl.blockage_refreshes, 2)
        # the cap is checked before the route is obtained
        self.assertEqual(ctrl.adapter.calls, 2)

    def test_max_refreshes_default_zero_is_unlimited(self):
        ctrl = make_controller(
            ruplace_congestion_blockage_refresh_interval=1,
            ruplace_congestion_blockage_max_refreshes=0,
        )
        model = make_model(FakeDensityOp(NBX, NBY))
        self.assertEqual(len(self.drive(ctrl, model, [None] * 5)), 5)

    def test_stop_overflow_halts_refreshes_late_in_gp(self):
        ctrl = make_controller(
            ruplace_congestion_blockage_refresh_interval=1,
            ruplace_congestion_blockage_stop_overflow=0.15,
        )
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op, overflow=0.2)
        self.assertTrue(self._call(ctrl, model))
        model.overflow = 0.1   # below stop_overflow
        self.assertFalse(self._call(ctrl, model))
        self.assertEqual(ctrl.adapter.calls, 1)
        model.overflow = 0.2   # back above it -> refreshing resumes
        self.assertTrue(self._call(ctrl, model))

    def test_stop_overflow_default_never_stops(self):
        ctrl = make_controller(ruplace_congestion_blockage_refresh_interval=1)
        model = make_model(FakeDensityOp(NBX, NBY), overflow=0.0)
        self.assertTrue(self._call(ctrl, model))

    def test_start_overflow_gate_precedes_any_router_call(self):
        ctrl = make_controller(ruplace_congestion_blockage_refresh_interval=1)
        model = make_model(FakeDensityOp(NBX, NBY), overflow=0.8)
        self.assertFalse(self._call(ctrl, model))
        self.assertEqual(ctrl.adapter.calls, 0)
        self.assertIsNone(ctrl.last_blockage_refresh_call)

    def test_disabled_lever_never_routes(self):
        ctrl = make_controller(
            ruplace_congestion_blockage=0.0,
            ruplace_congestion_blockage_refresh_interval=1,
        )
        model = make_model(FakeDensityOp(NBX, NBY))
        self.assertFalse(self._call(ctrl, model))
        self.assertEqual(ctrl.adapter.calls, 0)

    def test_maybe_adjust_area_drives_the_schedule_with_inflation_exhausted(self):
        ctrl = make_controller(ruplace_congestion_blockage_refresh_interval=1)
        op = FakeDensityOp(NBX, NBY)
        model = make_model(op)
        pos = torch.zeros(4)
        # _maybe_inflate_legacy early-returns (rounds exhausted) without routing
        self.assertTrue(ctrl.maybe_adjust_area(pos, model))
        self.assertTrue(ctrl.maybe_adjust_area(pos, model))
        self.assertEqual(ctrl.blockage_refreshes, 2)
        self.assertEqual(ctrl.adapter.calls, 2)
        self.assertIsNotNone(op.congestion_blockage_map)

    def _call(self, ctrl, model):
        ctrl._last_route_for_blockage = None
        return ctrl._maybe_update_blockage(torch.zeros(4), model)


def make_inflation(mode="shared", base=16.0, movable=8.0, filler=8.0):
    """RUPlaceInflation with only the budget fields set."""
    inf = RUPlaceInflation.__new__(RUPlaceInflation)
    params = Obj()
    params.ruplace_congestion_blockage_budget_mode = mode
    inf.params = params

    placedb = Obj()
    placedb.num_nodes = 4
    placedb.num_movable_nodes = 2
    placedb.num_filler_nodes = 2
    inf.placedb = placedb

    dc = Obj()
    # two movable + two filler cells, each square, areas movable/2 and filler/2
    m = (movable / 2.0) ** 0.5
    f = (filler / 2.0) ** 0.5
    dc.node_size_x = torch.tensor([m, m, f, f])
    dc.node_size_y = torch.tensor([m, m, f, f])
    dc.node_areas = dc.node_size_x * dc.node_size_y
    inf.data_collections = dc

    inf.original_movable_area = movable
    inf.base_total_place_area = base
    inf.total_place_area = base
    inf.filler_place_area = base
    inf.blocked_place_area = 0.0
    return inf


class BlockageBudgetModeTest(unittest.TestCase):
    def test_shared_mode_charges_both_budgets(self):
        inf = make_inflation("shared")
        inf.set_blocked_area(4.0)
        self.assertAlmostEqual(float(inf.total_place_area), 12.0, places=6)
        self.assertAlmostEqual(float(inf.filler_place_area), 12.0, places=6)

    def test_independent_mode_leaves_the_inflation_budget_pristine(self):
        inf = make_inflation("independent")
        inf.set_blocked_area(4.0)
        self.assertAlmostEqual(float(inf.total_place_area), 16.0, places=6)
        self.assertAlmostEqual(float(inf.filler_place_area), 12.0, places=6)
        # the inflation whitespace (total - movable) is untouched by blockage
        self.assertAlmostEqual(
            float(inf.total_place_area) - inf.original_movable_area, 8.0, places=6
        )

    def test_independent_mode_still_shrinks_the_fillers(self):
        shrunk = {}
        for mode in ("shared", "independent"):
            inf = make_inflation(mode)
            inf.set_blocked_area(4.0)
            pos = torch.zeros(8)
            self.assertTrue(inf.rescale_fillers(pos))
            shrunk[mode] = float(
                (inf.data_collections.node_size_x[2:] * inf.data_collections.node_size_y[2:]).sum()
            )
            # budget 12 - movable 8 = 4 of filler area left
            self.assertAlmostEqual(shrunk[mode], 4.0, places=4)
        self.assertAlmostEqual(shrunk["shared"], shrunk["independent"], places=6)

    def test_missing_param_defaults_to_shared(self):
        inf = make_inflation("shared")
        del inf.params.ruplace_congestion_blockage_budget_mode
        inf.set_blocked_area(4.0)
        self.assertAlmostEqual(float(inf.total_place_area), 12.0, places=6)

    def test_blocked_area_never_drops_below_the_movable_area(self):
        for mode in ("shared", "independent"):
            inf = make_inflation(mode)
            inf.set_blocked_area(1000.0)
            self.assertAlmostEqual(float(inf.filler_place_area), 8.0, places=6)

    def test_zero_blockage_is_a_no_op_in_both_modes(self):
        for mode in ("shared", "independent"):
            inf = make_inflation(mode)
            inf.set_blocked_area(0.0)
            self.assertAlmostEqual(float(inf.total_place_area), 16.0, places=6)
            self.assertAlmostEqual(float(inf.filler_place_area), 16.0, places=6)


@unittest.skipIf(
    ElectricOverflow is None,
    "electric_potential_cpp is only built in the install tree",
)
class ElectricOverflowIntegrationTest(unittest.TestCase):
    def build_op(self, target_density=1.0):
        num_bins = 4
        xl = yl = 0.0
        xh = yh = 40.0
        node_size_x = torch.tensor([2.0, 2.0])
        node_size_y = torch.tensor([2.0, 2.0])
        bin_center = torch.arange(num_bins, dtype=torch.float32) * 10.0 + 5.0
        return ElectricOverflow(
            node_size_x=node_size_x,
            node_size_y=node_size_y,
            bin_center_x=bin_center,
            bin_center_y=bin_center,
            target_density=target_density,
            xl=xl, yl=yl, xh=xh, yh=yh,
            bin_size_x=10.0, bin_size_y=10.0,
            num_movable_nodes=1,
            num_terminals=1,
            num_filler_nodes=0,
            padding=0,
            deterministic_flag=1,
            sorted_node_map=torch.zeros(1, dtype=torch.int32),
        )

    def test_default_off_leaves_the_initial_map_bitwise_untouched(self):
        op = self.build_op()
        self.assertIsNone(op.congestion_blockage_map)
        op.initial_density_map = torch.rand(4, 4, dtype=torch.float32)
        reference = op.initial_density_map.clone()
        op._apply_congestion_blockage()
        self.assertTrue(torch.equal(op.initial_density_map, reference))
        # with no blockage the fixed map is a zero-cost alias, not a copy
        self.assertIs(op.fixed_density_map, op.initial_density_map)
        self.assertIsNone(op.congestion_blockage_applied)

    def test_blockage_adds_capacity_scaled_area_and_survives_reset(self):
        op = self.build_op(target_density=0.8)
        blockage = torch.zeros(4, 4)
        blockage[1, 1] = 0.25
        op.set_congestion_blockage_map(blockage, blockage_max=0.5)
        self.assertIsNone(op.initial_density_map)
        op.initial_density_map = torch.zeros(4, 4)
        op._apply_congestion_blockage()
        capacity = 0.8 * 100.0
        self.assertAlmostEqual(
            float(op.initial_density_map[1, 1]), 0.25 * capacity, places=4
        )
        self.assertAlmostEqual(float(op.initial_density_map[0, 0]), 0.0, places=6)
        # the fixed-only snapshot stays clean
        self.assertAlmostEqual(float(op.fixed_density_map[1, 1]), 0.0, places=6)
        # reset() must not drop the standing blockage
        op.reset()
        self.assertIsNotNone(op.congestion_blockage_map)
        self.assertIsNone(op.initial_density_map)

    def test_clearing_the_map_restores_the_plain_fixed_density(self):
        op = self.build_op()
        op.set_congestion_blockage_map(torch.full((4, 4), 0.2), 0.5)
        op.set_congestion_blockage_map(None)
        op.initial_density_map = torch.zeros(4, 4)
        reference = op.initial_density_map.clone()
        op._apply_congestion_blockage()
        self.assertTrue(torch.equal(op.initial_density_map, reference))


if __name__ == "__main__":
    unittest.main()
