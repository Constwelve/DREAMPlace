##
# @file   gr_metrics_test.py
# @brief  Unit test for dreamplace/ops/gpugr/gr_metrics.py (RUPlace batch 2, item A1).
#
# Pure CPU, no GPU and no design data.  Checks
#   (1) hv_maps(util_mode='legacy') against hand-computed values,
#   (2) hv_maps(util_mode='legacy') against a literal transcription of the formulas the
#       three call sites carried before they were folded into gr_metrics,
#   (3) hv_maps(util_mode='avail') against hand-computed values,
#   (4) rc_means() against a hand-computed ACE value,
#   (5) the two wirelength conversions and the two shorts estimators.
#
# Run:  python3 unittest/gr_metrics_test.py
##

import os
import sys
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamplace.ops.gpugr import gr_metrics


def _fixture():
    """A 4-layer, 2x2 synthetic GR map set.

    With m1direction=1 the strides are h_id=1, v_id=2, so layers 1 and 3 are horizontal,
    layer 2 is vertical, and layer 0 (M1) is skipped by every aggregate.
    """
    dmd = torch.tensor(
        [
            [[1.0, 1.0], [1.0, 1.0]],   # layer 0 (M1) -- must be ignored
            [[8.0, 0.0], [0.0, 12.0]],  # layer 1 (H)
            [[1.0, 1.0], [1.0, 1.0]],   # layer 2 (V)
            [[0.0, 2.0], [2.0, 0.0]],   # layer 3 (H)
        ]
    )
    cap = torch.tensor(
        [
            [[9.0, 9.0], [9.0, 9.0]],
            [[4.0, 4.0], [4.0, 4.0]],
            [[2.0, 2.0], [2.0, 2.0]],
            [[4.0, 4.0], [4.0, 4.0]],
        ]
    )
    fixed = torch.tensor(
        [
            [[0.0, 0.0], [0.0, 0.0]],
            [[1.0, 1.0], [1.0, 1.0]],
            [[0.0, 0.0], [0.0, 0.0]],
            [[1.0, 1.0], [1.0, 1.0]],
        ]
    )
    # wire/via split of dmd: keep it simple and exact.
    via_dmd = torch.full_like(dmd, 0.5)
    wire_dmd = dmd - via_dmd
    return dmd, wire_dmd, via_dmd, cap, fixed


def _legacy_hv_maps(dmd, cap, m1direction):
    """Literal copy of the pre-batch-2 inline code in xplace_backend.run_route."""
    eps = torch.finfo(dmd.dtype).eps
    h_id = 1 if m1direction else 0
    v_id = 0 if m1direction else 1
    h_id = h_id + 2 if h_id == 0 else h_id
    v_id = v_id + 2 if v_id == 0 else v_id
    all_start = 1
    util = dmd[all_start:].sum(dim=0) / cap[all_start:].sum(dim=0).clamp_min(eps)
    util = torch.nan_to_num(util, nan=0.0, posinf=0.0, neginf=0.0)
    ovfl = (util - 1).clamp_min(0)
    cg_h = dmd[h_id::2].sum(dim=0) / cap[h_id::2].sum(dim=0).clamp_min(eps)
    cg_v = dmd[v_id::2].sum(dim=0) / cap[v_id::2].sum(dim=0).clamp_min(eps)
    cg_h = torch.nan_to_num(cg_h, nan=0.0, posinf=0.0, neginf=0.0)
    cg_v = torch.nan_to_num(cg_v, nan=0.0, posinf=0.0, neginf=0.0)
    hv_util = torch.stack((cg_h, cg_v))
    return util, ovfl, hv_util, (hv_util - 1).clamp_min(0)


class GRMetricsTest(unittest.TestCase):
    def test_hv_layer_ids(self):
        self.assertEqual(gr_metrics.hv_layer_ids(1), (1, 2))
        self.assertEqual(gr_metrics.hv_layer_ids(0), (2, 1))

    def test_hv_maps_legacy_hand_computed(self):
        dmd, wire_dmd, via_dmd, cap, fixed = _fixture()
        util, ovfl, hv_util, hv_ovfl = gr_metrics.hv_maps(
            dmd, wire_dmd, via_dmd, cap, fixed=fixed, m1direction=1, util_mode="legacy")

        # layers 1..3 summed: dmd = [[9, 3], [3, 13]], cap = [[10, 10], [10, 10]]
        torch.testing.assert_close(util, torch.tensor([[0.9, 0.3], [0.3, 1.3]]))
        torch.testing.assert_close(ovfl, torch.tensor([[0.0, 0.0], [0.0, 0.3]]))
        # H = layers 1,3: dmd [[8, 2], [2, 12]] / cap 8
        torch.testing.assert_close(hv_util[0], torch.tensor([[1.0, 0.25], [0.25, 1.5]]))
        # V = layer 2 only: dmd 1 / cap 2
        torch.testing.assert_close(hv_util[1], torch.tensor([[0.5, 0.5], [0.5, 0.5]]))
        torch.testing.assert_close(hv_ovfl[0], torch.tensor([[0.0, 0.0], [0.0, 0.5]]))
        torch.testing.assert_close(hv_ovfl[1], torch.zeros(2, 2))

    def test_hv_maps_legacy_matches_pre_refactor_code(self):
        dmd, wire_dmd, via_dmd, cap, fixed = _fixture()
        for m1direction in (0, 1):
            got = gr_metrics.hv_maps(dmd, wire_dmd, via_dmd, cap, fixed=fixed,
                                     m1direction=m1direction, util_mode="legacy")
            want = _legacy_hv_maps(dmd, cap, m1direction)
            for g, w in zip(got, want):
                torch.testing.assert_close(g, w)

    def test_hv_maps_avail_hand_computed(self):
        dmd, wire_dmd, via_dmd, cap, fixed = _fixture()
        util, ovfl, hv_util, hv_ovfl = gr_metrics.hv_maps(
            dmd, wire_dmd, via_dmd, cap, fixed=fixed, m1direction=1, util_mode="avail")
        # layers 1..3: (dmd - fixed) = [[7, 1], [1, 11]], (cap - fixed) = 8
        torch.testing.assert_close(util, torch.tensor([[0.875, 0.125], [0.125, 1.375]]))
        # H layers 1,3: (dmd - fixed) = [[6, 0], [0, 10]], (cap - fixed) = 6
        torch.testing.assert_close(hv_util[0], torch.tensor([[1.0, 0.0], [0.0, 10.0 / 6.0]]))
        # V layer 2: fixed is 0 there, so avail == legacy
        torch.testing.assert_close(hv_util[1], torch.tensor([[0.5, 0.5], [0.5, 0.5]]))
        torch.testing.assert_close(ovfl, torch.tensor([[0.0, 0.0], [0.0, 0.375]]))

    def test_avail_requires_fixed(self):
        dmd, wire_dmd, via_dmd, cap, _ = _fixture()
        with self.assertRaises(ValueError):
            gr_metrics.hv_maps(dmd, wire_dmd, via_dmd, cap, fixed=None,
                               m1direction=1, util_mode="avail")
        with self.assertRaises(ValueError):
            gr_metrics.hv_maps(dmd, wire_dmd, via_dmd, cap, fixed=None,
                               m1direction=1, util_mode="nonsense")

    def test_rc_means_hand_computed(self):
        # hv_overflow[0] = [[0, 0], [0, 0.5]], hv_overflow[1] = 0.
        # ACE fractions [.005 .01 .02 .05 .1 .2 .5] x 4 gcells -> indices [0,0,0,0,0,0,2].
        # Row 0 sorted desc of (ovfl + 1) = [1.5, 1, 1, 1]; running means
        #   [1.5, 1.25, 7/6, 1.125]; selected [1.5]*6 + [7/6]; mean = (9 + 7/6) / 7.
        hv_overflow = torch.tensor([[[0.0, 0.0], [0.0, 0.5]], [[0.0, 0.0], [0.0, 0.0]]])
        rc_hor, rc_ver = gr_metrics.rc_means(hv_overflow)
        self.assertAlmostEqual(rc_hor, (9.0 + 7.0 / 6.0) / 7.0, places=6)
        self.assertAlmostEqual(rc_ver, 1.0, places=6)

    def test_wirelength_conversions(self):
        # 1000 gcell steps, 576 dbu gcells, 2000 dbu/um -> 288 um.
        self.assertAlmostEqual(gr_metrics.gr_wirelength_um(1000, 576, 576, 2000), 288.0)
        # max(step) is used, matching the router's own convention.
        self.assertAlmostEqual(gr_metrics.gr_wirelength_um(1000, 400, 576, 2000), 288.0)
        # M2-pitch units (the ISPD18 route_wl unit).
        self.assertAlmostEqual(
            gr_metrics.gr_wirelength_m2pitch(1000, 576, 576, [100.0, 200.0]), 2880.0)

    def test_shorts_estimators(self):
        dmd, wire_dmd, via_dmd, cap, _ = _fixture()
        # simple: sum((wire_dmd - cap)+) over ALL layers + via_dmd where dmd/cap > 1.
        # wire_dmd - cap is positive only at layer1 [1][1]: 11.5 - 4 = 7.5, and
        # layer1 [0][0]: 7.5 - 4 = 3.5  -> 11.0
        # dmd/cap > 1 at layer1 [0][0] (8/4) and [1][1] (12/4) -> 2 x 0.5 = 1.0
        self.assertAlmostEqual(
            gr_metrics.estimate_num_shorts_simple(dmd, cap, wire_dmd, via_dmd), 12.0, places=5)
        # area-weighted: with unit widths/pitches it reduces to the wire overflow area
        # plus the vias in gcells whose wire demand exceeds capacity.
        got = gr_metrics.estimate_num_shorts(
            cap, wire_dmd, via_dmd, layer_width=[1.0, 1.0, 1.0, 1.0],
            layer_pitch=[1.0, 1.0], step_x=1.0, step_y=1.0, microns=1.0, m1direction=1)
        self.assertAlmostEqual(got, 12.0, places=5)

    def test_route_metrics_modes(self):
        dmd, wire_dmd, via_dmd, cap, _ = _fixture()
        hv_overflow = torch.tensor([[[0.0, 0.0], [0.0, 0.5]], [[0.0, 0.0], [0.0, 0.0]]])
        m = gr_metrics.route_metrics(
            num_ovfl_nets=7, hv_overflow=hv_overflow, dmd_map=dmd, wire_dmd_map=wire_dmd,
            via_dmd_map=via_dmd, cap_map=cap, wl_steps=1000, gr_vias=42,
            step_x=576, step_y=576, microns=2000)
        self.assertEqual(m["num_ovfl_nets"], 7)
        self.assertAlmostEqual(m["gr_wirelength"], 1000.0)
        self.assertAlmostEqual(m["gr_wirelength_um"], 288.0)
        self.assertAlmostEqual(m["gr_vias"], 42.0)
        self.assertAlmostEqual(m["rc_hor"], 0.125, places=6)   # mean of [[0,0],[0,.5]]
        self.assertAlmostEqual(m["rc_ver"], 0.0, places=6)
        m_ace = gr_metrics.route_metrics(
            num_ovfl_nets=7, hv_overflow=hv_overflow, dmd_map=dmd, wire_dmd_map=wire_dmd,
            via_dmd_map=via_dmd, cap_map=cap, wl_steps=1000, gr_vias=42, rc_mode="ace")
        self.assertAlmostEqual(m_ace["rc_hor"], (9.0 + 7.0 / 6.0) / 7.0, places=6)


if __name__ == "__main__":
    unittest.main()
