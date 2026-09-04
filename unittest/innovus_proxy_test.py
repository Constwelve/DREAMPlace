##
# @file   innovus_proxy_test.py
# @brief  Unit tests for the Innovus eGR congestion proxy (Phase 2 lever 1).
#
# Covered:
#   * dumpCongestArea parsing, including negative `remain` on overflowed gcells
#   * the 72 dbu x-origin offset and centre-based gcell assignment
#   * the commensurate case (Innovus 576 dbu -> router 2880 dbu, exactly 5x5)
#   * the *incommensurate* case (regression_s14-style: the die span is not an
#     integer multiple of the Innovus gcell, so no k x k reshape exists)
#   * util / overflow definitions and the clamp that matches
#     gr_metrics.hv_maps(util_mode='avail')
#   * that the default ruplace_inflate_proxy=gpugr leaves the loop untouched
#

import os
import sys
import types
import unittest

import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamplace.ops.routability_opt import innovus_proxy as ip


def write_dump(path, nx, ny, x0=72, y0=0, step=576, value_fn=None):
    """Synthesize a `dumpCongestArea -all` file on an nx x ny grid.

    ``value_fn(i, j) -> (v_remain, v_total, h_remain, h_total)``; the default
    makes every field a distinct function of (i, j) so a mis-transposed or
    mis-offset index cannot pass by accident.
    """
    if value_fn is None:
        def value_fn(i, j):
            return (i - j, 10, j - i, 20)
    lines = ["Total congestion area report:"]
    for i in range(nx):
        for j in range(ny):
            vr, vt, hr, ht = value_fn(i, j)
            lines.append("(%d, %d) (%d, %d) V: %d/%d H: %d/%d"
                         % (x0 + step * i, y0 + step * j,
                            x0 + step * (i + 1), y0 + step * (j + 1), vr, vt, hr, ht))
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


class ParseTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="innovus_proxy_test_")

    def test_parse_grid_and_offset(self):
        path = write_dump(os.path.join(self.tmp, "d.txt"), 10, 10)
        dump = ip.parse_congest_dump(path)
        self.assertEqual((dump["nx"], dump["ny"]), (10, 10))
        self.assertEqual((dump["step_x"], dump["step_y"]), (576, 576))
        self.assertEqual((dump["x0"], dump["y0"]), (72, 0))
        self.assertEqual(dump["n_rows"], 100)
        # x-major indexing: entry [i, j] is the gcell at (x0+576i, y0+576j)
        self.assertEqual(int(dump["v_remain"][3, 7]), 3 - 7)
        self.assertEqual(int(dump["h_remain"][3, 7]), 7 - 3)
        self.assertEqual(int(dump["v_total"][3, 7]), 10)
        self.assertEqual(int(dump["h_total"][3, 7]), 20)
        # negative remain survives (an overflowed gcell must not be dropped)
        self.assertLess(int(dump["v_remain"][0, 9]), 0)

    def test_parse_rejects_ragged(self):
        path = os.path.join(self.tmp, "bad.txt")
        with open(path, "w") as fh:
            fh.write("(72, 0) (648, 576) V: 1/2 H: 3/4\n"
                     "(648, 0) (1224, 576) V: 1/2 H: 3/4\n"
                     "(72, 576) (648, 1152) V: 1/2 H: 3/4\n")
        with self.assertRaises(ip.InnovusDumpError):
            ip.parse_congest_dump(path)


class GridMappingTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="innovus_proxy_test_")

    def test_commensurate_5x5_matches_block_sum(self):
        """10x10 Innovus gcells (576 dbu, x0=72) -> 2x2 router gcells (2880 dbu).

        This is the nvdla_s geometry scaled down: the 72 dbu offset is a
        one-eighth-gcell snap, so centre-based assignment must still give the
        exact 5x5 block sum the calibration harness computes by reshape.
        """
        rng = np.random.RandomState(0)
        vals = rng.randint(-5, 30, size=(10, 10, 4))

        def value_fn(i, j):
            return tuple(int(v) for v in vals[i, j])

        path = write_dump(os.path.join(self.tmp, "d.txt"), 10, 10, value_fn=value_fn)
        dump = ip.parse_congest_dump(path)
        die = (0.0, 10 * 576.0, 0.0, 10 * 576.0)  # router tiles [0, 5760] into 2x2
        tracks = ip.dump_to_router_grid(dump, 2, 2, die[0], die[2], die[1], die[3])
        self.assertEqual(tracks["n_empty_bins"], 0)
        self.assertEqual(tracks["src_per_bin_min"], 25)
        self.assertEqual(tracks["src_per_bin_max"], 25)
        for name in ("h_remain", "h_total", "v_remain", "v_total"):
            expect = dump[name].reshape(2, 5, 2, 5).sum(axis=(1, 3))
            np.testing.assert_array_equal(tracks[name], expect)

    def test_incommensurate_span(self):
        """7 Innovus gcells -> 2 router gcells: no k x k reshape exists.

        Router pitch is 3.5 Innovus gcells, so columns 0..2 fall in bin 0 and
        3..6 in bin 1 by centre.  Nothing may be dropped or double-counted.
        """
        path = write_dump(os.path.join(self.tmp, "d7.txt"), 7, 7)
        dump = ip.parse_congest_dump(path)
        span = 7 * 576.0
        tracks = ip.dump_to_router_grid(dump, 2, 2, 0.0, 0.0, span, span)
        self.assertEqual(tracks["n_empty_bins"], 0)
        self.assertEqual(int(tracks["src_per_bin_min"]), 9)   # 3x3
        self.assertEqual(int(tracks["src_per_bin_max"]), 16)  # 4x4
        # every source gcell lands exactly once
        self.assertEqual(int(tracks["h_total"].sum()), int(dump["h_total"].sum()))
        self.assertEqual(int(tracks["v_total"].sum()), int(dump["v_total"].sum()))
        np.testing.assert_array_equal(
            tracks["h_total"], np.array([[9 * 20, 12 * 20], [12 * 20, 16 * 20]]))

    def test_util_and_overflow_definitions(self):
        """util = 1 - remain/total; overflow = (util-1)+; clamp matches 'avail'."""
        tracks = {
            "h_remain": np.array([[5, 0], [-10, 20]], dtype=np.int64),
            "h_total": np.array([[20, 20], [20, 0]], dtype=np.int64),
            "v_remain": np.array([[10, -4], [0, 0]], dtype=np.int64),
            "v_total": np.array([[20, 20], [20, 0]], dtype=np.int64),
        }
        f = ip.hv_fields(tracks, clamp=True)
        np.testing.assert_allclose(f["h_util"], [[0.75, 1.0], [1.5, 0.0]])
        np.testing.assert_allclose(f["h_overflow"], [[0.0, 0.0], [0.5, 0.0]])
        np.testing.assert_allclose(f["h_ovfl_tracks"], [[0.0, 0.0], [10.0, 0.0]])
        np.testing.assert_allclose(f["v_util"], [[0.5, 1.2], [1.0, 0.0]])
        # 2D map: both directions pooled, i.e. 1 - sum(remain)/sum(total)
        np.testing.assert_allclose(f["util"], [[1 - 15 / 40.0, 1 - (-4) / 40.0],
                                               [1 - (-10) / 40.0, 0.0]])
        np.testing.assert_array_equal(f["mask"], [[True, True], [True, False]])
        # clamp=False keeps remain>total (negative utilization) for rank-based checks
        neg = {"h_remain": np.array([[25]], dtype=np.int64),
               "h_total": np.array([[20]], dtype=np.int64),
               "v_remain": np.array([[0]], dtype=np.int64),
               "v_total": np.array([[20]], dtype=np.int64)}
        self.assertAlmostEqual(float(ip.hv_fields(neg, clamp=False)["h_util"][0, 0]), -0.25)
        self.assertAlmostEqual(float(ip.hv_fields(neg, clamp=True)["h_util"][0, 0]), 0.0)

    def test_maps_from_dump_end_to_end(self):
        path = write_dump(os.path.join(self.tmp, "e.txt"), 10, 10)
        dump = ip.parse_congest_dump(path)
        fields, tracks = ip.maps_from_dump(dump, 2, 2, (0.0, 5760.0, 0.0, 5760.0))
        self.assertEqual(fields["h_util"].shape, (2, 2))
        # block (0,0): h_remain = sum_{i,j<5}(j-i) = 0, h_total = 25*20 = 500
        self.assertAlmostEqual(float(fields["h_util"][0, 0]), 1.0 - 0.0 / 500.0)
        self.assertEqual(int(tracks["h_total"][0, 0]), 500)


class CaseResolutionTest(unittest.TestCase):
    def setUp(self):
        import json
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="innovus_proxy_meta_")
        self.meta = os.path.join(self.tmp, "data", "s14")
        os.makedirs(self.meta)
        with open(os.path.join(self.meta, "nvdla_s_s14.meta.json"), "w") as fh:
            json.dump({"case": "nvdla_s_s14", "top_cell": "NV_nvdla",
                       "def_raw": "/x/nvdla_s_s14/NV_nvdla_s.def",
                       "def_fixed_macro": "/x/nvdla_s_s14/NV_nvdla_s.fixedmacro.def"}, fh)
        with open(os.path.join(self.meta, "regression_s14.meta.json"), "w") as fh:
            json.dump({"case": "regression_s14", "top_cell": "ct_top",
                       "def_raw": "/x/regression_s14/ct_top.def",
                       "def_fixed_macro": "/x/regression_s14/ct_top.fixedmacro.def"}, fh)

    def test_explicit_case_wins(self):
        params = types.SimpleNamespace(ruplace_innovus_case="regression_s14", def_input="/junk.def")
        self.assertEqual(ip.resolve_case(params, self.meta), "regression_s14")

    def test_gp_output_resolves_by_stem(self):
        params = types.SimpleNamespace(
            ruplace_innovus_case="",
            def_input="/results/nvdla_s_gp_baseline/NV_nvdla_s.fixedmacro/NV_nvdla_s.fixedmacro.gp.def")
        self.assertEqual(ip.resolve_case(params, self.meta), "nvdla_s_s14")

    def test_unresolvable_fails_fast(self):
        params = types.SimpleNamespace(ruplace_innovus_case="", def_input="/x/other/thing.def")
        with self.assertRaises(RuntimeError):
            ip.resolve_case(params, self.meta)


class FactoryTest(unittest.TestCase):
    """The feature must be strictly opt-in."""

    def test_default_is_a_no_op(self):
        for value in ("gpugr", "", "xplace", "GPUGR", None):
            params = types.SimpleNamespace(ruplace_inflate_proxy=value)
            self.assertEqual(ip.resolve_inflate_proxy(params), "gpugr")
            # None means "controller keeps calling adapter.run_route", i.e. no change
            self.assertIsNone(ip.build_inflation_proxy(params, None, object()))

    def test_missing_param_is_gpugr(self):
        self.assertEqual(ip.resolve_inflate_proxy(types.SimpleNamespace()), "gpugr")
        self.assertIsNone(ip.build_inflation_proxy(types.SimpleNamespace(), None, object()))

    def test_bad_value_rejected(self):
        with self.assertRaises(ValueError):
            ip.resolve_inflate_proxy(types.SimpleNamespace(ruplace_inflate_proxy="rudy"))

    def test_adaptive_effort_rejected(self):
        for mode in ("innovus", "both"):
            params = types.SimpleNamespace(ruplace_inflate_proxy=mode)
            with self.assertRaises(RuntimeError):
                ip.build_inflation_proxy(params, None, object(), adaptive_profile={"target_pct": 1.0})

    def test_controller_uses_the_factory(self):
        """Guard against the wiring drifting away from the factory."""
        import inspect

        from dreamplace.ops.routability_opt import ruplace_op
        src = inspect.getsource(ruplace_op.RUPlaceController)
        self.assertIn("build_inflation_proxy", src)
        self.assertIn("_inflation_route", src)
        # the legacy path must route its inflation map through the dispatcher
        legacy = inspect.getsource(ruplace_op.RUPlaceController._maybe_inflate_legacy)
        self.assertIn("self._inflation_route(pos, model)", legacy)
        self.assertNotIn("self.adapter.run_route(pos)", legacy)
        # ADMM must keep using GPUGR
        admm = inspect.getsource(ruplace_op.RUPlaceController.apply_admm_gradient)
        self.assertNotIn("_inflation_route", admm)


class _StubGpdb(object):
    def __init__(self, die):
        self.die = die
        self.written = []

    def apply_node_lpos(self, lpos):
        self.applied = lpos

    def write_placement(self, prefix):
        with open(prefix + ".def", "w") as fh:
            fh.write("DESIGN stub ;\nEND DESIGN\n")
        self.written.append(prefix)

    def dieInfo(self):
        return self.die


class _StubAdapter(object):
    """Stands in for XplaceGGRAdapter: only the DEF-write path and the grid are used."""

    def __init__(self, die, grid):
        self.gpdb = _StubGpdb(die)
        self.grid = grid
        self.route_calls = 0

    def _scaled_to_raw_lpos(self, pos):
        return pos

    def _gr_grid_size(self):
        return self.grid

    def run_route(self, pos):
        self.route_calls += 1
        return "gpugr-fallback"


class EndToEndPlumbingTest(unittest.TestCase):
    """Whole run_route() path with a stub adapter and a stub scorer.

    Exercises DEF write -> subprocess under the licence flock -> dump parse ->
    router-grid maps -> RUPlaceRouteResult, without a GPU or an Innovus licence.
    """

    def setUp(self):
        import json
        import stat
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="innovus_proxy_e2e_")
        self.dump = write_dump(os.path.join(self.tmp, "fixture.txt"), 10, 10)
        with open(os.path.join(self.tmp, "fixture.json"), "w") as fh:
            json.dump({"status": "ok", "metrics": {
                "egr_horizontal_congestion": 1.5, "egr_vertical_congestion": 0.68,
                "horizontal_overflow": 40482.0, "vertical_overflow": 16950.0,
                "vias": 3225754.0, "wirelength": 4375359.36899}}, fh)
        self.script = os.path.join(self.tmp, "fake_eval.sh")
        with open(self.script, "w") as fh:
            fh.write("#!/usr/bin/env bash\nset -e\n"
                     "test -f \"$2\"\n"                       # the DEF must exist
                     "test \"$DUMP_CONGEST\" = 1\n"           # and the dump must be requested
                     "echo \"case=$1 def=$2 out=$3 mode=$4\"\n"
                     "cp %s \"$3/innovus_congest_area.txt\"\n"
                     "cp %s \"$3/innovus.json\"\n"
                     % (self.dump, os.path.join(self.tmp, "fixture.json")))
        os.chmod(self.script, os.stat(self.script).st_mode | stat.S_IEXEC)

    def _proxy(self, **over):
        params = types.SimpleNamespace(
            ruplace_inflate_proxy="innovus",
            ruplace_innovus_case="nvdla_s_s14",
            ruplace_innovus_eval_script=self.script,
            ruplace_innovus_repo=self.tmp,
            ruplace_innovus_proxy_workdir=os.path.join(self.tmp, "work"),
            ruplace_innovus_proxy_min_interval=100,
            ruplace_innovus_proxy_lock=os.path.join(self.tmp, "lock"),
            result_dir=self.tmp,
        )
        for k, v in over.items():
            setattr(params, k, v)
        # die spans the 10x10 Innovus grid; router grid is 2x2, i.e. 5x5 blocks
        adapter = _StubAdapter((0.0, 5760.0, 0.0, 5760.0), (2, 2))
        return ip.InnovusEGRProxy(params, None, adapter), adapter

    def test_full_call(self):
        proxy, adapter = self._proxy()
        route = proxy.run_route("POS", iteration=300)
        self.assertEqual(adapter.route_calls, 0)          # GPUGR was not used
        self.assertEqual(len(adapter.gpdb.written), 1)
        self.assertEqual(tuple(route.utilization_map.shape), (2, 2))
        self.assertEqual(tuple(route.hv_utilization_map.shape), (2, 2, 2))
        self.assertEqual(tuple(route.hv_overflow_map.shape), (2, 2, 2))
        self.assertIsNone(route.routeforce)
        m = route.metrics
        self.assertEqual(m["innovus_egr_h"], 1.5)
        self.assertEqual(m["innovus_egr_v"], 0.68)
        self.assertAlmostEqual(m["innovus_wl"], 4375359.36899)
        # the two GPUGR-scale stop thresholds have no eGR analogue and must not
        # make ruplace_local_*_stop unreachable
        self.assertEqual(m["num_ovfl_nets"], 0)
        self.assertEqual(m["est_shorts"], 0.0)
        self.assertGreater(m["time"], 0.0)
        self.assertTrue(os.path.isfile(os.path.join(proxy.workdir, "calls.json")))
        self.assertTrue(os.path.isfile(
            os.path.join(proxy.workdir, "call_0001", "innovus_congest_area.txt")))

        # second call inside the min interval reuses the map, no new DEF
        again = proxy.run_route("POS", iteration=350)
        self.assertIs(again, route)
        self.assertEqual(len(adapter.gpdb.written), 1)
        # past the interval it runs again
        proxy.run_route("POS", iteration=500)
        self.assertEqual(len(adapter.gpdb.written), 2)
        self.assertEqual(proxy.call_count, 2)

    def test_failure_falls_back_without_raising(self):
        proxy, adapter = self._proxy(ruplace_innovus_eval_script="/bin/false")
        proxy.script = "/bin/false"
        route = proxy.run_route("POS", iteration=1)
        self.assertEqual(route, "gpugr-fallback")   # no cache yet -> GPUGR
        self.assertEqual(adapter.route_calls, 1)

    def test_failure_prefers_the_cached_map(self):
        proxy, adapter = self._proxy()
        good = proxy.run_route("POS", iteration=0)
        proxy.script = "/bin/false"
        stale = proxy.run_route("POS", iteration=1000)
        self.assertIs(stale, good)
        self.assertEqual(adapter.route_calls, 0)


class RateLimitTest(unittest.TestCase):
    def test_min_interval(self):
        proxy = ip.InnovusEGRProxy.__new__(ip.InnovusEGRProxy)
        proxy.min_interval = 100
        proxy.last_route = None
        proxy.last_iteration = None
        self.assertTrue(proxy.should_run(0))       # no cache -> always run
        proxy.last_route = object()
        proxy.last_iteration = 500
        self.assertFalse(proxy.should_run(501))
        self.assertFalse(proxy.should_run(599))
        self.assertTrue(proxy.should_run(600))
        self.assertTrue(proxy.should_run(None))    # unknown iteration -> run
        proxy.min_interval = 0
        self.assertTrue(proxy.should_run(500))


if __name__ == "__main__":
    unittest.main()
