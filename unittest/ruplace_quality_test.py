#!/usr/bin/env python3

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ruplace_quality", ROOT / "tools" / "ruplace_quality.py"
)
ruplace_quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ruplace_quality)
COMPOSITE_SPEC = importlib.util.spec_from_file_location(
    "ruplace_composite", ROOT / "tools" / "ruplace_composite.py"
)
ruplace_composite = importlib.util.module_from_spec(COMPOSITE_SPEC)
COMPOSITE_SPEC.loader.exec_module(ruplace_composite)
AUTO_SPEC = importlib.util.spec_from_file_location(
    "ruplace_auto_composite", ROOT / "tools" / "ruplace_auto_composite.py"
)
ruplace_auto_composite = importlib.util.module_from_spec(AUTO_SPEC)
AUTO_SPEC.loader.exec_module(ruplace_auto_composite)


class RUPlaceQualityTest(unittest.TestCase):
    def test_expand_designs(self):
        self.assertEqual(
            ruplace_quality.expand_designs("pilot", ""),
            ["ispd18_test1", "ispd18_test2", "ispd18_test3"],
        )
        self.assertEqual(len(ruplace_quality.expand_designs("full", "")), 10)
        self.assertEqual(
            ruplace_quality.expand_designs("pilot", "ispd18_test1, ispd18_test7"),
            ["ispd18_test1", "ispd18_test7"],
        )

    def test_gate_summary_passes_on_fake_metrics(self):
        rows = []
        for design in ["ispd18_test1", "ispd18_test2", "ispd18_test3"]:
            rows.extend(
                [
                    self._row(design, "dp_hpwl", 120, 1200),
                    self._row(design, "dp_rudy", 100, 1000),
                    self._row(design, "ruplace", 80, 850),
                    self._row(design, "xplace_inflate", 75, 780),
                ]
            )
        gate = ruplace_quality.gate_summary(rows)
        self.assertTrue(gate["pass"])
        self.assertEqual(gate["dp_rudy_improved"], 3)
        self.assertLessEqual(gate["xplace_median_ratios"]["route_ovfl_nets"], 1.20)

    def test_gate_summary_fails_when_not_competitive_with_xplace(self):
        rows = []
        for design in ["ispd18_test1", "ispd18_test2", "ispd18_test3"]:
            rows.extend(
                [
                    self._row(design, "dp_hpwl", 200, 2000),
                    self._row(design, "dp_rudy", 180, 1800),
                    self._row(design, "ruplace", 100, 1000),
                    self._row(design, "xplace_inflate", 50, 500),
                ]
            )
        gate = ruplace_quality.gate_summary(rows)
        self.assertFalse(gate["pass"])
        self.assertGreater(gate["xplace_median_ratios"]["route_est_shorts"], 1.20)

    def test_zero_xplace_metric_reports_infinite_ratio(self):
        rows = [
            self._row("ispd18_test1", "dp_hpwl", 200, 2000),
            self._row("ispd18_test1", "dp_rudy", 180, 1800),
            self._row("ispd18_test1", "ruplace", 100, 1000),
            self._row("ispd18_test1", "xplace_inflate", 0, 0),
        ]
        gate = ruplace_quality.gate_summary(rows)
        self.assertEqual(gate["xplace_median_ratios"]["route_ovfl_nets"], float("inf"))
        self.assertFalse(gate["pass"])

    def test_dreamplace_config_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            xplace_root = Path(tmp) / "Xplace"
            data = xplace_root / "data"
            data.mkdir(parents=True)
            (data / "ispd18_test1.input.lef").write_text("VERSION 5.8 ;\n")
            (data / "ispd18_test1.input.def").write_text("VERSION 5.8 ;\n")
            args = SimpleNamespace(
                xplace_root=xplace_root,
                num_bins=512,
                iterations=50,
                learning_rate=0.02,
                density_weight=1.6e-4,
                gp_gamma=6.0,
                gp_noise_ratio=0.01,
                target_density=1.0,
                ruplace_target_density_overrides="",
                stop_overflow=0.15,
                random_seed=7,
                num_threads=4,
                route_rrr_iters=1,
                ruplace_external_route_eval=1,
                ruplace_inflate_start_overflow=1.0,
                ruplace_max_inflate_ratio=2.0,
                ruplace_min_inflate_ratio=1.0,
                ruplace_global_inflate_gamma=0.35,
                ruplace_local_inflate_gamma=0.35,
                ruplace_inflate_area_cap=0.03,
                ruplace_inflate_extra_capacity=0.0,
                ruplace_congested_uniform_inflate_ratio=1.0,
                ruplace_local_inflate_max_rounds=8,
                ruplace_allow_shrink=1,
                ruplace_local_ovfl_nets_stop=0.0,
                ruplace_local_est_shorts_stop=0.0,
                ruplace_admm_start_overflow=0.6,
                ruplace_admm_route_freq=20,
                ruplace_admm_weight=0.5,
                ruplace_admm_anchor_weight=0.1,
            )
            hpwl = ruplace_quality.build_dreamplace_config(
                args, "ispd18_test1", "dp_hpwl", Path(tmp) / "hpwl"
            )
            rudy = ruplace_quality.build_dreamplace_config(
                args, "ispd18_test1", "dp_rudy", Path(tmp) / "rudy"
            )
            ru = ruplace_quality.build_dreamplace_config(
                args, "ispd18_test1", "ruplace", Path(tmp) / "ruplace"
            )
        self.assertEqual(hpwl["routability_opt_flag"], 0)
        self.assertEqual(rudy["routability_opt_flag"], 1)
        self.assertEqual(rudy["adjust_rudy_area_flag"], 1)
        self.assertEqual(ru["ruplace_flag"], 1)
        self.assertEqual(ru["ruplace_global_inflate_gamma"], 0.35)
        self.assertEqual(ru["ruplace_global_cluster_mode"], "mean")
        self.assertEqual(ru["ruplace_global_util_exponent"], 1.0)
        self.assertEqual(ru["ruplace_hv_inflate_gamma"], 0.0)
        self.assertEqual(ru["ruplace_hv_inflate_mode"], "max")
        self.assertEqual(ru["ruplace_inflate_area_cap"], 0.03)
        self.assertEqual(ru["ruplace_admm_weight_decay"], 1.0)
        self.assertEqual(ru["ruplace_admm_min_weight"], 0.0)
        self.assertEqual(ru["ruplace_admm_grad_clip_norm"], 0.0)
        self.assertEqual(ru["ruplace_admm_anchor_update"], "refresh")
        self.assertEqual(ru["ruplace_admm_anchor_decay"], 0.9)
        self.assertEqual(ru["global_place_stages"][0]["learning_rate"], 0.02)
        self.assertEqual(ru["density_weight"], 1.6e-4)
        self.assertEqual(ru["gamma"], 6.0)
        self.assertEqual(ru["gp_noise_ratio"], 0.01)
        self.assertIn("ruplace_xplace_root", ru)

    def test_ruplace_target_density_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            xplace_root = Path(tmp) / "Xplace"
            data = xplace_root / "data"
            data.mkdir(parents=True)
            (data / "ispd18_test8.input.lef").write_text("VERSION 5.8 ;\n")
            (data / "ispd18_test8.input.def").write_text("VERSION 5.8 ;\n")
            args = SimpleNamespace(
                xplace_root=xplace_root,
                num_bins=512,
                iterations=50,
                target_density=1.0,
                ruplace_target_density_overrides="ispd18_test8:1.1",
                stop_overflow=0.15,
                random_seed=7,
                num_threads=4,
                route_rrr_iters=1,
                ruplace_external_route_eval=1,
                ruplace_inflate_start_overflow=1.0,
                ruplace_max_inflate_ratio=2.0,
                ruplace_min_inflate_ratio=1.0,
                ruplace_global_inflate_gamma=0.35,
                ruplace_local_inflate_gamma=0.35,
                ruplace_inflate_area_cap=0.03,
                ruplace_inflate_extra_capacity=0.0,
                ruplace_congested_uniform_inflate_ratio=1.0,
                ruplace_local_inflate_max_rounds=8,
                ruplace_allow_shrink=1,
                ruplace_local_ovfl_nets_stop=0.0,
                ruplace_local_est_shorts_stop=0.0,
                ruplace_admm_start_overflow=0.6,
                ruplace_admm_route_freq=20,
                ruplace_admm_weight=0.5,
                ruplace_admm_anchor_weight=0.1,
            )
            ru = ruplace_quality.build_dreamplace_config(
                args, "ispd18_test8", "ruplace", Path(tmp) / "ruplace"
            )
            dp = ruplace_quality.build_dreamplace_config(
                args, "ispd18_test8", "dp_hpwl", Path(tmp) / "dp"
            )
        self.assertEqual(ru["target_density"], 1.1)
        self.assertEqual(dp["target_density"], 1.0)

    def test_ruplace_param_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            xplace_root = Path(tmp) / "Xplace"
            data = xplace_root / "data"
            data.mkdir(parents=True)
            (data / "ispd18_test4.input.lef").write_text("VERSION 5.8 ;\n")
            (data / "ispd18_test4.input.def").write_text("VERSION 5.8 ;\n")
            args = SimpleNamespace(
                xplace_root=xplace_root,
                num_bins=512,
                iterations=50,
                target_density=1.0,
                ruplace_target_density_overrides="",
                ruplace_param_overrides=(
                    "ispd18_test4.target_density:1.05,"
                    "ispd18_test4.ruplace_local_inflate_max_rounds:1,"
                    "ispd18_test4.ruplace_allow_shrink:true,"
                    "ispd18_test4.ruplace_global_cluster_mode:none,"
                    "ispd18_test4.ruplace_global_util_exponent:2.0"
                ),
                stop_overflow=0.15,
                random_seed=7,
                num_threads=4,
                route_rrr_iters=1,
                ruplace_external_route_eval=1,
                ruplace_inflate_start_overflow=1.0,
                ruplace_max_inflate_ratio=2.0,
                ruplace_min_inflate_ratio=1.0,
                ruplace_global_inflate_gamma=0.35,
                ruplace_local_inflate_gamma=0.35,
                ruplace_inflate_area_cap=0.03,
                ruplace_inflate_extra_capacity=0.0,
                ruplace_congested_uniform_inflate_ratio=1.0,
                ruplace_local_inflate_max_rounds=8,
                ruplace_allow_shrink=0,
                ruplace_local_ovfl_nets_stop=0.0,
                ruplace_local_est_shorts_stop=0.0,
                ruplace_admm_start_overflow=0.6,
                ruplace_admm_route_freq=20,
                ruplace_admm_weight=0.5,
                ruplace_admm_anchor_weight=0.1,
            )
            ru = ruplace_quality.build_dreamplace_config(
                args, "ispd18_test4", "ruplace", Path(tmp) / "ruplace"
            )
            dp = ruplace_quality.build_dreamplace_config(
                args, "ispd18_test4", "dp_hpwl", Path(tmp) / "dp"
            )
        self.assertEqual(ru["target_density"], 1.05)
        self.assertEqual(ru["ruplace_local_inflate_max_rounds"], 1)
        self.assertEqual(ru["ruplace_allow_shrink"], 1)
        self.assertEqual(ru["ruplace_global_cluster_mode"], "none")
        self.assertEqual(ru["ruplace_global_util_exponent"], 2.0)
        self.assertEqual(dp["target_density"], 1.0)

    def test_report_writer_outputs_verdict_and_table(self):
        rows = [
            self._row("ispd18_test1", "dp_hpwl", 120, 1200),
            self._row("ispd18_test1", "dp_rudy", 100, 1000),
            self._row("ispd18_test1", "ruplace", 80, 850),
            self._row("ispd18_test1", "xplace_inflate", 75, 780),
        ]
        gate = ruplace_quality.gate_summary(rows)
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.md"
            args = SimpleNamespace(iterations=50)
            ruplace_quality.write_report(report, args, Path(tmp), rows, gate)
            text = report.read_text()
        self.assertIn("# RUPlace Quality Report", text)
        self.assertIn("Per-Design Results", text)
        self.assertIn("Wirelength Comparison", text)
        self.assertIn("Per-Design Wirelength Comparison", text)
        self.assertIn("Lowest GPUGR-reference WL", text)
        self.assertIn("vs dp_hpwl GR WL", text)
        self.assertIn("ispd18_test1", text)

    def test_comparison_csv_includes_wirelength_baselines(self):
        rows = [
            self._row("ispd18_test1", "dp_hpwl", 120, 1200, hpwl=12, route_wl=20),
            self._row("ispd18_test1", "dp_rudy", 100, 1000, hpwl=11, route_wl=18),
            self._row("ispd18_test1", "ruplace", 80, 850, hpwl=10, route_wl=15),
            self._row("ispd18_test1", "xplace_inflate", 75, 780, hpwl=9, route_wl=14),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comparison_summary.csv"
            ruplace_quality.write_comparison_csv(path, rows)
            text = path.read_text()
        self.assertIn("ru_vs_dp_hpwl_route_wl", text)
        self.assertIn("ru_vs_xplace_route_wl_delta_pct", text)
        self.assertIn("ru_vs_dp_rudy_place_hpwl", text)
        self.assertIn("ru_better_dp_hpwl_route_wl", text)
        self.assertIn("route_wl_best_method", text)

    def test_auto_composite_congestion_objective(self):
        incumbent = self._row("ispd18_test1", "ruplace", 100, 1000, route_wl=1000)
        lower_wl = self._row("ispd18_test1", "ruplace", 110, 1100, route_wl=900)
        lower_congestion = self._row("ispd18_test1", "ruplace", 80, 800, route_wl=1050)
        self.assertTrue(
            ruplace_auto_composite.better_candidate(
                lower_wl, incumbent, allow_equal=False, objective="wl"
            )
        )
        self.assertTrue(
            ruplace_auto_composite.better_candidate(
                lower_congestion, incumbent, allow_equal=False, objective="congestion"
            )
        )
        self.assertFalse(
            ruplace_auto_composite.wl_ok(lower_congestion, incumbent, slack=1.04)
        )

    def test_composite_method_specific_override_parser(self):
        overrides = ruplace_composite.parse_overrides(
            ["ispd18_test9.ruplace:tune_td120", "ispd18_test4:tune_lowfix"]
        )
        self.assertEqual(
            overrides,
            [
                ("ispd18_test9", "ruplace", "tune_td120"),
                ("ispd18_test4", "", "tune_lowfix"),
            ],
        )

    @staticmethod
    def _row(design, method, ovfl, shorts, hpwl=10, route_wl=10):
        return {
            "design": design,
            "method": method,
            "status": "ok",
            "route_ovfl_nets": str(ovfl),
            "route_wl": str(route_wl),
            "route_vias": "2",
            "route_est_shorts": str(shorts),
            "place_hpwl": str(hpwl),
            "rc_hor": "1.0",
            "rc_ver": "1.0",
            "metric_source": "fake",
        }


if __name__ == "__main__":
    unittest.main()
