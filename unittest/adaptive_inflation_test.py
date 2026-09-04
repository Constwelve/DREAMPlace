#!/usr/bin/env python3
"""CPU-only tests for adaptive RUPlace inflation policy helpers."""

import json
import os
import sys
import tempfile
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamplace.ops.routability_opt.inflation_calibration import (
    EFFORT_PROFILES,
    InflationCalibration,
    MonotoneCurve,
    adaptive_budget,
    normalize_effort,
    overflow_coverage_pct,
)
from dreamplace.ops.routability_opt.ruplace_op import RUPlaceInflation
from dreamplace.ops.routability_opt.ruplace_op import RUPlaceController
from dreamplace.ops.gpugr.gpu_lock import acquire_gpu_lock, release_gpu_lock
import dreamplace.Params as Params


class Obj(object):
    pass


class CalibrationTest(unittest.TestCase):
    def test_effort_profiles_and_budget(self):
        self.assertEqual(normalize_effort("HIGH"), "high")
        self.assertEqual(normalize_effort(None), "medium")
        with self.assertRaises(ValueError):
            normalize_effort("turbo")
        self.assertLess(EFFORT_PROFILES["low"]["max_ratio"], EFFORT_PROFILES["high"]["max_ratio"])
        profile = EFFORT_PROFILES["medium"]
        self.assertEqual(adaptive_budget(profile, 0.0, 0.5), profile["budget_min"])
        self.assertEqual(adaptive_budget(profile, 100.0, 10.0), profile["budget_max"])

    def test_monotone_curve_and_ucb(self):
        curve = MonotoneCurve([0, 1, 2], [0, 2, 3], underprediction_q95=0.5)
        self.assertAlmostEqual(curve.predict(0.5), 1.0)
        self.assertAlmostEqual(curve.predict_ucb(0.5), 1.5)
        with self.assertRaises(ValueError):
            MonotoneCurve([0, 1], [2, 1])

    def test_default_profile_loads(self):
        profile = InflationCalibration.load_default()
        self.assertTrue(profile.valid)
        h, v = profile.predict("gpugr", 0.0, 0.0, upper=True)
        self.assertGreaterEqual(h, 0.0)
        self.assertGreaterEqual(v, 0.0)

    def test_params_default_to_legacy(self):
        # The shipped default is the published legacy inflation flow: it is the only
        # setting whose s14 Innovus numbers are gate-tested, so a fresh clone enabling
        # only routability_opt_flag + ruplace_flag reproduces the recorded result.
        params = Params.Params()
        params.fromJson({"routability_opt_flag": 1, "ruplace_flag": 1})
        self.assertEqual(params.ruplace_inflation_effort, "legacy")

    def test_adaptive_medium_is_opt_in(self):
        params = Params.Params()
        params.fromJson({"routability_opt_flag": 1, "ruplace_flag": 1,
                         "ruplace_inflation_effort": "medium"})
        self.assertEqual(params.ruplace_inflation_effort, "medium")

    def test_directional_coverage(self):
        maps = torch.tensor([[[0.0, 1.0], [0.0, 2.0]], [[0.0, 0.0], [3.0, 0.0]]])
        self.assertEqual(overflow_coverage_pct(maps), (50.0, 25.0))

    def test_gpu_process_lock_uses_configured_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "gpu0.lock")
            previous = os.environ.get("RUPLACE_GPU_LOCK")
            os.environ["RUPLACE_GPU_LOCK"] = path
            handle = None
            try:
                handle = acquire_gpu_lock(0, "unit-test")
                with open(path) as stream:
                    metadata = stream.read()
                self.assertIn("label=unit-test", metadata)
                self.assertIn("pid=", metadata)
            finally:
                release_gpu_lock(handle)
                if previous is None:
                    os.environ.pop("RUPLACE_GPU_LOCK", None)
                else:
                    os.environ["RUPLACE_GPU_LOCK"] = previous


class AdaptiveWaterFillingTest(unittest.TestCase):
    def fixture(self):
        params = Obj()
        params.ruplace_max_inflate_ratio = 2.0
        params.ruplace_min_inflate_ratio = 1.0
        params.ruplace_inflate_extra_capacity = 0.0
        params.ruplace_hv_inflate_gamma = 0.0
        params.ruplace_node_util_window = 0

        placedb = Obj()
        placedb.num_nodes = 5
        placedb.num_movable_nodes = 4
        placedb.num_filler_nodes = 1
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 8.0
        placedb.routing_grid_yh = 2.0
        placedb.row_height = 1.0
        placedb.node_names = [b"a/u0", b"a/u1", b"b/u0", b"b/u1", b"filler"]

        data = Obj()
        data.node_size_x = torch.ones(5)
        data.node_size_y = torch.ones(5)
        data.pin_offset_x = torch.zeros(4)
        data.pin_offset_y = torch.zeros(4)
        data.flat_node2pin_start_map = torch.tensor([0, 1, 2, 3, 4, 4], dtype=torch.long)
        data.flat_node2pin_map = torch.tensor([0, 1, 2, 3], dtype=torch.long)
        data.target_density = torch.tensor([1.0])
        data.node_areas = data.node_size_x * data.node_size_y

        route = Obj()
        route.utilization_map = torch.tensor([[2.0, 1.8], [2.0, 1.8], [1.1, 1.0], [1.1, 1.0]])
        route.hv_overflow_map = torch.zeros((2, 4, 2))
        pos = torch.tensor([0.0, 1.0, 4.0, 5.0, 7.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        return params, placedb, data, route, pos

    def test_module_water_filling_is_bounded(self):
        params, placedb, data, route, pos = self.fixture()
        inflation = RUPlaceInflation(params, placedb, data)
        profile = dict(EFFORT_PROFILES["medium"])
        profile["max_ratio"] = 3.0
        self.assertTrue(inflation.adaptive_node_ratios(pos, route, "module", 0.20, profile))
        ratios = inflation.current_inflate_ratio
        self.assertAlmostEqual(ratios[0].item(), ratios[1].item(), places=5)
        self.assertGreater(ratios[0].item(), ratios[2].item())
        self.assertLessEqual(ratios.max().item(), 3.0)
        growth = float((ratios.mean() - 1.0).item())
        self.assertLessEqual(growth, 0.20 + 1e-5)

    def test_oversized_spatial_module_has_hard_cell_cap(self):
        placedb = Obj()
        placedb.num_nodes = 4100
        placedb.num_movable_nodes = 4100
        placedb.routing_grid_xl = 0.0
        placedb.routing_grid_yl = 0.0
        placedb.routing_grid_xh = 8.0
        placedb.routing_grid_yh = 8.0
        placedb.node_names = [b"flat_cell"] * placedb.num_nodes
        inflation = object.__new__(RUPlaceInflation)
        inflation.placedb = placedb
        pos = torch.zeros(2 * placedb.num_nodes)
        cluster_ids = inflation._build_adaptive_cluster_ids(pos)
        self.assertLessEqual(int(torch.bincount(cluster_ids).max().item()), 4096)
        self.assertEqual(int(torch.unique(cluster_ids).numel()), 2)


class AdaptiveControllerTest(unittest.TestCase):
    def controller_fixture(self, prediction=(10.0, 10.0), area_ratio=1.0):
        controller = object.__new__(RUPlaceController)
        controller.params = Obj()
        controller.params.result_dir = ""
        controller.params.ruplace_inflate_start_overflow = 1.0
        controller.inflation_effort = "medium"
        controller.adaptive_profile = EFFORT_PROFILES["medium"]
        controller.calibration = Obj()
        controller.calibration.name = "test"
        controller.calibration.predict = lambda proxy, h, v, upper=True: prediction
        controller.inflation_phase = "module"
        controller.module_rounds = 0
        controller.cell_rounds = 0
        controller.inflation_stopped = False
        controller.inflation_stop_reason = ""
        controller.proxy_target_met = False
        controller.target_confirmations = 0
        controller.stagnation_rounds = 0
        controller.error_integral = 0.0
        controller.last_controller_score = None
        controller.last_prediction = None
        controller.last_rudy_prediction = None
        controller.rudy_deferred_checks = 0
        controller.gpugr_checks = 0
        controller.inflation_history = []
        controller.grad_iteration = 0
        controller.admm_applications = 0
        controller.admm_active = False
        controller.adapter = Obj()
        route = Obj()
        route.hv_overflow_map = torch.zeros((2, 2, 2))
        route.utilization_map = torch.ones((2, 2))
        controller.adapter.run_route = lambda pos: route
        controller.adapter.anchor_pos = None
        controller.adapter.last_route = None
        controller.adapter.external_route_eval = False
        controller.inflation = Obj()
        controller.inflation.original_node_size_x = torch.ones(2)
        controller.inflation.original_node_size_y = torch.ones(2)
        controller.inflation.current_inflate_ratio = torch.full((2,), area_ratio)
        controller.inflation.last_adaptive_stats = {"top_module_fraction": 1.0}
        controller.inflation.adaptive_node_ratios = lambda pos, route, phase, budget, profile: True

        model = Obj()
        model.overflow = torch.tensor(0.1)
        model.op_collections = Obj()
        model.op_collections.route_utilization_map_op = None
        pos = torch.zeros(4)
        return controller, model, pos

    def test_two_proxy_confirmations_stop_only_inflation(self):
        controller, model, pos = self.controller_fixture(prediction=(0.5, 0.5))
        self.assertFalse(controller._maybe_inflate_adaptive(pos, model))
        self.assertFalse(controller.inflation_stopped)
        self.assertFalse(controller._maybe_inflate_adaptive(pos, model))
        self.assertTrue(controller.inflation_stopped)
        self.assertTrue(controller.proxy_target_met)

    def test_module_transitions_to_cell(self):
        controller, model, pos = self.controller_fixture()
        phases = []
        controller.inflation.adaptive_node_ratios = (
            lambda pos, route, phase, budget, profile: phases.append(phase) or True
        )
        self.assertTrue(controller._maybe_inflate_adaptive(pos, model))
        self.assertTrue(controller._maybe_inflate_adaptive(pos, model))
        self.assertEqual(phases, ["module", "cell"])
        self.assertEqual(controller.module_rounds, 1)
        self.assertEqual(controller.cell_rounds, 1)

    def test_stagnation_stops_inflation(self):
        controller, model, pos = self.controller_fixture(area_ratio=1.10)
        self.assertTrue(controller._maybe_inflate_adaptive(pos, model))
        self.assertTrue(controller._maybe_inflate_adaptive(pos, model))
        self.assertFalse(controller._maybe_inflate_adaptive(pos, model))
        self.assertTrue(controller.inflation_stopped)
        self.assertEqual(controller.inflation_stop_reason, "stagnated")

    def test_capacity_exhaustion_is_explicit(self):
        controller, model, pos = self.controller_fixture(area_ratio=1.60)
        self.assertFalse(controller._maybe_inflate_adaptive(pos, model))
        self.assertEqual(controller.inflation_stop_reason, "capacity_exhausted")
        self.assertFalse(controller.proxy_target_met)

    def test_status_json_records_history_and_schema(self):
        controller, model, pos = self.controller_fixture(area_ratio=1.60)
        with tempfile.TemporaryDirectory() as result_dir:
            controller.params.result_dir = result_dir
            controller.params.design_name = lambda: "case"
            self.assertFalse(controller._maybe_inflate_adaptive(pos, model))
            path = os.path.join(result_dir, "case", "ruplace_inflation_status.json")
            with open(path) as stream:
                payload = json.load(stream)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["stop_reason"], "capacity_exhausted")
        self.assertEqual(payload["gpugr_checks"], 1)
        self.assertEqual(len(payload["history"]), 1)

    def test_rudy_defers_only_one_gpugr_check(self):
        controller, model, pos = self.controller_fixture()
        route_calls = []
        route = Obj()
        route.hv_overflow_map = torch.zeros((2, 2, 2))
        route.utilization_map = torch.ones((2, 2))
        controller.adapter.run_route = lambda pos: route_calls.append(1) or route
        rudy = {"coverage_h": 1.0, "coverage_v": 1.0, "route_overflow": 0.1,
                "ucb_h": 10.0, "ucb_v": 10.0}
        controller._rudy_prediction = lambda pos, model: dict(rudy)

        self.assertTrue(controller._maybe_inflate_adaptive(pos, model))
        self.assertFalse(controller._maybe_inflate_adaptive(pos, model))
        self.assertTrue(controller._maybe_inflate_adaptive(pos, model))
        self.assertEqual(len(route_calls), 2)
        self.assertEqual(controller.gpugr_checks, 2)
        self.assertEqual(controller.inflation_history[1]["route_decision"], "deferred_by_rudy")

    def test_stopped_inflation_does_not_disable_admm(self):
        controller, model, _ = self.controller_fixture()
        controller.params.ruplace_admm_start_overflow = 1.0
        controller.params.ruplace_admm_apply_freq = 1
        controller.params.ruplace_admm_route_freq = 1
        controller.params.ruplace_admm_grad_clip_norm = 0.0
        controller.params.ruplace_admm_weight = 0.5
        controller.params.ruplace_admm_weight_decay = 1.0
        controller.params.ruplace_admm_min_weight = 0.0
        controller.adapter.admm_gradient = lambda pos, refresh: torch.ones_like(pos)
        controller._stop_adaptive_inflation("stagnated")
        pos = torch.zeros(4, requires_grad=True)
        controller.apply_admm_gradient(pos, model)
        self.assertEqual(controller.admm_applications, 1)
        self.assertTrue(controller.admm_active)
        self.assertTrue(torch.equal(pos.grad, torch.full_like(pos, 0.5)))


if __name__ == "__main__":
    unittest.main()
