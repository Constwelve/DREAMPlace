#!/usr/bin/env python3

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_summarize import (
    enrich_golden_metrics, flatten_per_design, main,
    placement_plugin_activation_error, summarize, write_report,
)


def result(method, backend, metrics):
    return {
        "method": method,
        "backend": backend,
        "status": "ok",
        "authoritative_for_comparison": True,
        "metrics": metrics,
    }


def add_openroad_congestion_artifact(evaluation, artifacts):
    report = evaluation / "openroad_congestion.rpt"
    report.write_text(
        "violation type: Horizontal congestion\n"
        "  comment: capacity:1 usage:1 overflow:0\n"
        "violation type: Vertical congestion\n"
        "  comment: capacity:1 usage:1 overflow:0\n"
    )
    artifacts["congestion"] = str(report)


def placement_provenance(method, plugins=None):
    plugins = ([] if method == "hpwl" else [method]) if plugins is None else plugins
    return {
        "method": method,
        "status": "ok",
        "routability_plugin_status": "active" if plugins else "not_selected",
        "routability_plugin_selected": ",".join(sorted(plugins)),
        "routability_plugin_summary": {
            "plugins": {
                plugin: {"status": "active", "activations": 1}
                for plugin in plugins
            },
        },
    }


def golden_placement_provenance(methods_dir, methods):
    placements = []
    for method in methods:
        plugins = [] if method == "hpwl" else [method]
        method_dir = methods_dir / method
        method_dir.mkdir(exist_ok=True)
        (method_dir / "config.json").write_text(json.dumps({
            "ruplace_plugins": plugins,
        }))
        placements.append(placement_provenance(method, plugins))
    return placements


class RoutabilitySummarizeTest(unittest.TestCase):
    def test_plugin_activation_contract_rejects_partial_or_noop_plugins(self):
        placement = placement_provenance("pair", ["left", "right"])
        config = {"ruplace_plugins": ["right", "left"]}
        self.assertEqual(placement_plugin_activation_error(placement, config), "")

        placement["routability_plugin_status"] = "partially_active"
        self.assertIn(
            "expected active", placement_plugin_activation_error(placement, config)
        )
        placement["routability_plugin_status"] = "active"
        placement["routability_plugin_summary"]["plugins"]["right"][
            "activations"
        ] = 0
        self.assertIn(
            "lacks positive active evidence",
            placement_plugin_activation_error(placement, config),
        )

    def test_strict_enrichment_rejects_summary_wrapper(self):
        with self.assertRaisesRegex(ValueError, "golden backend: missing"):
            enrich_golden_metrics({"results": []}, require_complete=True)

    def test_strict_enrichment_does_not_invent_missing_openroad_congestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "openroad.log"
            log.write_text(
                "Number of nets: 1\n"
                "[INFO DRT-0199] Number of violations = 0.\n"
                "Viol/Layer Metal2\n"
                "[INFO DRT-0267] done\n"
            )
            metrics = root / "openroad_metrics.json"
            metrics.write_text(json.dumps({
                "route__wirelength": 10, "route__vias": 1,
                "route__drc_errors": 0, "route__net": 1,
            }))
            with self.assertRaisesRegex(
                ValueError, "horizontal_overflow, vertical_overflow"
            ):
                enrich_golden_metrics({
                    "backend": "openroad",
                    "metrics": {},
                    "artifacts": {"log": str(log), "metrics": str(metrics)},
                }, require_complete=True)

    def test_streams_innovus_drc_artifact_when_backfilling_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "innovus_drc.rpt"
            report.write_text(
                "SHORT: first\nSPACING: one\n  short: second\n"
                "  Total Violations : 3 Viols.\n"
            )
            metrics = enrich_golden_metrics({
                "backend": "innovus",
                "metrics": {"wirelength": 10.0},
                "artifacts": {"drc": str(report)},
            })

        self.assertEqual(metrics["short_violations"], 2.0)
        self.assertEqual(metrics["drc_violations"], 3.0)

    def test_rejects_persisted_drc_that_disagrees_with_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "innovus_drc.rpt"
            report.write_text("  Total Violations : 3 Viols.\n")
            with self.assertRaisesRegex(ValueError, "drc_violations"):
                enrich_golden_metrics({
                    "backend": "innovus",
                    "metrics": {"drc_violations": 2.0},
                    "artifacts": {"drc": str(report)},
                })

    def test_rejects_innovus_log_drc_that_disagrees_with_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "innovus.log"
            log.write_text(
                "Verification Complete : 2 Viols.\n"
                "Violation Summary By Layer and Type:\n"
                "Short MetSpc Totals\n"
                "Totals 1 1 2\n"
                "*** End Verify DRC\n"
            )
            report = root / "innovus_drc.rpt"
            report.write_text("Total Violations : 3 Viols.\n")
            with self.assertRaisesRegex(
                ValueError, "log drc_violations.*disagrees with DRC report"
            ):
                enrich_golden_metrics({
                    "backend": "innovus",
                    "metrics": {"drc_violations": 3.0},
                    "artifacts": {"log": str(log), "drc": str(report)},
                })

    def test_rejects_persisted_metric_that_disagrees_with_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_1" / "methods"
            evaluation = comparison / "evaluation"
            evaluation.mkdir(parents=True)
            drc = evaluation / "innovus_drc.rpt"
            drc.write_text("SHORT: first\nSHORT: second\n")
            artifacts = {"drc": str(drc)}
            for name in ("log", "metrics", "connectivity", "script"):
                artifact = evaluation / ("innovus_%s.txt" % name)
                artifact.write_text("0 total info(s) created.\n" if name == "connectivity" else "")
                artifacts[name] = str(artifact)
            baseline = result("hpwl", "innovus", {
                "wirelength": 100.0, "short_violations": 1.0,
            })
            baseline["artifacts"] = artifacts
            placements = golden_placement_provenance(comparison, ["hpwl"])
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [baseline],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["validated_comparisons"], 0)
        self.assertEqual(
            data["excluded"][0]["status"], "artifact_metric_mismatch"
        )
        self.assertIn("short_violations", data["excluded"][0]["error"])

    def test_rejects_openroad_metrics_artifact_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_1" / "methods"
            evaluation = comparison / "evaluation"
            evaluation.mkdir(parents=True)
            artifacts = {}
            for name in ("log", "drc", "guide", "script"):
                artifact = evaluation / ("openroad_%s.txt" % name)
                artifact.write_text("")
                artifacts[name] = str(artifact)
            metrics_artifact = evaluation / "openroad_metrics.json"
            metrics_artifact.write_text(json.dumps({"route__drc_errors": 3}))
            artifacts["metrics"] = str(metrics_artifact)
            add_openroad_congestion_artifact(evaluation, artifacts)
            baseline = result("hpwl", "openroad", {
                "wirelength": 100.0,
                "openroad_metrics": {"route__drc_errors": 2},
            })
            baseline["artifacts"] = artifacts
            placements = golden_placement_provenance(comparison, ["hpwl"])
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [baseline],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["validated_comparisons"], 0)
        self.assertEqual(
            data["excluded"][0]["status"], "artifact_metric_mismatch"
        )
        self.assertIn("raw metrics", data["excluded"][0]["error"])

    def test_missing_golden_artifact_excludes_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            baseline = result("hpwl", "openroad", {
                "wirelength": 100.0, "drc_violations": 0.0,
            })
            baseline["artifacts"] = {}
            placements = golden_placement_provenance(comparison, ["hpwl"])
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [baseline],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["validated_comparisons"], 0)
        self.assertEqual(data["excluded"][0]["status"], "missing_artifact")
        self.assertIn("guide", data["excluded"][0]["error"])

    def test_significance_uses_percent_deltas_across_design_scales(self):
        rows = []
        baselines = {}
        for index, baseline in enumerate((1.0, 1000.0, 1000000.0)):
            case = "case_%d" % index
            base_row = {
                "case": case, "seed": 1, "method": "hpwl",
                "backend": "innovus", "drc_violations": baseline,
                "drc_violations_baseline": baseline,
                "drc_violations_delta": 0.0,
                "drc_violations_delta_pct": 0.0,
            }
            plugin_row = {
                "case": case, "seed": 1, "method": "plugin",
                "backend": "innovus", "drc_violations": baseline * 0.9,
                "drc_violations_baseline": baseline,
                "drc_violations_delta": -baseline * 0.1,
                "drc_violations_delta_pct": -10.0,
            }
            rows.extend((base_row, plugin_row))
            baselines[(case, 1, "innovus")] = base_row

        result = summarize(rows, baselines)
        plugin = next(
            row for row in result
            if row["backend"] == "innovus"
            and row["metric"] == "drc_violations"
            and row["method"] == "plugin"
        )

        self.assertEqual(plugin["statistical_evidence_unit"], "percent")
        self.assertLess(plugin["case_ci95_high_pct"], 0)
        self.assertGreater(plugin["case_ci95_high"], 0)
        self.assertTrue(plugin["statistically_supported"])

    def test_records_per_design_means_and_worst_pair_identity(self):
        rows = []
        baselines = {}
        deltas = {
            ("case_a", 1): -10.0,
            ("case_a", 2): 5.0,
            ("case_b", 1): 20.0,
            ("case_b", 2): 30.0,
        }
        for (case, seed), delta_pct in deltas.items():
            baseline = {
                "case": case, "seed": seed, "method": "hpwl",
                "backend": "innovus", "wirelength": 100.0,
                "wirelength_baseline": 100.0,
                "wirelength_delta": 0.0,
                "wirelength_delta_pct": 0.0,
            }
            plugin = {
                "case": case, "seed": seed, "method": "plugin",
                "backend": "innovus", "wirelength": 100.0 + delta_pct,
                "wirelength_baseline": 100.0,
                "wirelength_delta": delta_pct,
                "wirelength_delta_pct": delta_pct,
            }
            rows.extend((baseline, plugin))
            baselines[(case, seed, "innovus")] = baseline

        result = summarize(rows, baselines)
        plugin = next(
            row for row in result
            if row["backend"] == "innovus"
            and row["metric"] == "wirelength"
            and row["method"] == "plugin"
        )

        self.assertEqual(plugin["case_results"], [
            {
                "case": "case_a", "valid_count": 2,
                "percent_valid_count": 2, "mean_delta": -2.5,
                "mean_delta_pct": -2.5, "mean_value": 97.5,
                "mean_baseline": 100.0,
            },
            {
                "case": "case_b", "valid_count": 2,
                "percent_valid_count": 2, "mean_delta": 25.0,
                "mean_delta_pct": 25.0, "mean_value": 125.0,
                "mean_baseline": 100.0,
            },
        ])
        self.assertEqual(plugin["worst_case"], "case_b")
        self.assertEqual(plugin["worst_case_mean_delta_pct"], 25.0)
        self.assertEqual(plugin["worst_pair_case"], "case_b")
        self.assertEqual(plugin["worst_pair_seed"], 2)
        self.assertEqual(plugin["worst_pair_value"], 130.0)
        self.assertEqual(plugin["worst_pair_baseline"], 100.0)
        self.assertEqual(plugin["worst_pair_delta_pct"], 30.0)

        flat = flatten_per_design([plugin])
        self.assertEqual(flat[0]["mean_value"], 97.5)
        self.assertEqual(flat[0]["mean_baseline"], 100.0)

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "summary.md"
            write_report(
                report, 4, rows, result, [], "hpwl",
                {"expected_comparisons": 4},
            )
            text = report.read_text()
        self.assertIn("Mean candidate / HPWL", text)
        self.assertIn("97.5 / 100 (-2.500%)", text)
        self.assertIn("case_b/2 130 / 100 (30.000%)", text)

    def test_tiny_float_delta_is_a_tie_not_a_win(self):
        baseline = {
            "case": "case_a", "seed": 1, "method": "hpwl",
            "backend": "innovus", "wirelength": 1.0,
            "wirelength_baseline": 1.0, "wirelength_delta": 0.0,
            "wirelength_delta_pct": 0.0,
        }
        plugin = {
            "case": "case_a", "seed": 1, "method": "plugin",
            "backend": "innovus", "wirelength": 1.0 - 1e-13,
            "wirelength_baseline": 1.0, "wirelength_delta": -1e-13,
            "wirelength_delta_pct": -1e-11,
        }

        result = summarize(
            [baseline, plugin], {("case_a", 1, "innovus"): baseline}
        )
        plugin_summary = next(
            row for row in result
            if row["backend"] == "innovus"
            and row["metric"] == "wirelength"
            and row["method"] == "plugin"
        )

        self.assertEqual(plugin_summary["wins"], 0)
        self.assertEqual(plugin_summary["ties"], 1)
        self.assertEqual(plugin_summary["losses"], 0)
        self.assertFalse(plugin_summary["consistent_improvement"])

    def test_backfills_openroad_connectivity_from_retained_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_1" / "methods"
            evaluation = comparison / "evaluation"
            evaluation.mkdir(parents=True)
            log = evaluation / "openroad.log"
            log.write_text("""
Number of nets: 12
[INFO DRT-0199] Number of violations = 3.
Viol/Layer Metal2 Metal3
Short 2 1
[INFO DRT-0267] done
""")
            raw_metrics = {
                "route__net": 11, "route__drc_errors": 3,
                "route__wirelength": 100, "route__vias": 10,
            }
            metrics_artifact = evaluation / "openroad_metrics.json"
            metrics_artifact.write_text(json.dumps(raw_metrics))
            artifacts = {
                "log": str(log),
                "metrics": str(metrics_artifact),
            }
            for name in ("drc", "guide", "script"):
                artifact = evaluation / ("openroad_%s.txt" % name)
                artifact.write_text("")
                artifacts[name] = str(artifact)
            add_openroad_congestion_artifact(evaluation, artifacts)
            baseline = result("hpwl", "openroad", {
                "wirelength": 100.0,
                "openroad_metrics": raw_metrics,
            })
            baseline["artifacts"] = artifacts
            plugin = result("plugin", "openroad", {
                "wirelength": 100.0,
                "openroad_metrics": raw_metrics,
            })
            plugin["artifacts"] = artifacts
            placements = golden_placement_provenance(
                comparison, ["hpwl", "plugin"]
            )
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [baseline, plugin],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        indexed = {
            (row["backend"], row["metric"], row["method"]): row
            for row in data["rows"]
        }
        self.assertEqual(status, 0)
        self.assertEqual(
            indexed[("openroad", "unrouted_nets", "plugin")]["mean_value"], 1.0
        )
        self.assertEqual(
            indexed[("openroad", "short_violations", "plugin")]["mean_value"], 3.0
        )

    def test_backend_deltas_are_paired_with_same_case_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_7" / "case_a" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": "hpwl", "status": "ok", "placement_hpwl": 100.0},
                    {"method": "plugin", "status": "ok", "placement_hpwl": 90.0,
                     "routability_plugin_status": "active"},
                ],
                "results": [
                    result("hpwl", "rudy", {"overflow_sum": 10.0}),
                    result("plugin", "rudy", {"overflow_sum": 8.0}),
                    result("hpwl", "gpugr", {
                        "gr_wirelength": 200.0, "est_shorts": 10.0,
                        "num_ovfl_nets": 4, "rc_hor": 0.5, "rc_ver": 0.25,
                        "horizontal_congestion_score": 10.0,
                        "vertical_congestion_score": 20.0,
                        "horizontal_congestion_score_p95": 11.0,
                        "vertical_congestion_score_p95": 21.0,
                        "horizontal_congestion_score_p99": 12.0,
                        "vertical_congestion_score_p99": 22.0,
                    }),
                    result("plugin", "gpugr", {
                        "gr_wirelength": 220.0, "est_shorts": 5.0,
                        "num_ovfl_nets": 2, "rc_hor": 0.4, "rc_ver": 0.125,
                        "horizontal_congestion_score": 9.0,
                        "vertical_congestion_score": 19.0,
                        "horizontal_congestion_score_p95": 10.0,
                        "vertical_congestion_score_p95": 20.0,
                        "horizontal_congestion_score_p99": 11.0,
                        "vertical_congestion_score_p99": 21.0,
                    }),
                ],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            with (output / "screening_summary.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            with (output / "screening_per_design.csv").open() as stream:
                per_design = list(csv.DictReader(stream))

        self.assertEqual(status, 0)
        indexed = {(row["backend"], row["metric"], row["method"]): row for row in rows}
        self.assertAlmostEqual(
            float(indexed[("rudy", "overflow_sum", "plugin")]["mean_delta_pct"]),
            -20.0,
        )
        self.assertAlmostEqual(
            float(indexed[("gpugr", "gr_wirelength", "plugin")]["mean_delta_pct"]),
            10.0,
        )
        self.assertAlmostEqual(
            float(indexed[("gpugr", "est_shorts", "plugin")]["mean_delta_pct"]),
            -50.0,
        )
        self.assertAlmostEqual(
            float(indexed[("gpugr", "rc_hor", "plugin")]["mean_delta_pct"]),
            -20.0,
        )
        self.assertAlmostEqual(
            float(indexed[("gpugr", "rc_ver", "plugin")]["mean_delta_pct"]),
            -50.0,
        )
        for name in (
            "horizontal_congestion_score", "vertical_congestion_score",
            "horizontal_congestion_score_p95", "vertical_congestion_score_p95",
            "horizontal_congestion_score_p99", "vertical_congestion_score_p99",
        ):
            self.assertIn(("gpugr", name, "plugin"), indexed)
        self.assertEqual(indexed[("rudy", "overflow_sum", "plugin")]["wins"], "1")
        self.assertEqual(indexed[("gpugr", "gr_wirelength", "plugin")]["losses"], "1")
        self.assertAlmostEqual(
            float(indexed[("rudy", "overflow_sum", "plugin")]["mean_delta"]),
            -2.0,
        )
        self.assertEqual(
            indexed[("rudy", "overflow_sum", "plugin")]["case_count"], "1"
        )
        self.assertEqual(
            indexed[("rudy", "overflow_sum", "plugin")]["case_ci95_low_pct"], ""
        )
        self.assertEqual(
            json.loads(
                indexed[("rudy", "overflow_sum", "plugin")]["case_results"]
            )[0]["case"],
            "case_a",
        )
        per_design_index = {
            (row["backend"], row["metric"], row["method"], row["case"]): row
            for row in per_design
        }
        self.assertAlmostEqual(
            float(per_design_index[
                ("rudy", "overflow_sum", "plugin", "case_a")
            ]["mean_delta_pct"]),
            -20.0,
        )
        self.assertEqual(
            per_design_index[("rudy", "overflow_sum", "plugin", "case_a")][
                "is_worst_case"
            ],
            "True",
        )

    def test_unvalidated_comparison_is_excluded_and_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "campaign" / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "unvalidated"},
                "placements": [],
                "results": [],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(root / "campaign"),
                "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["validated_comparisons"], 0)
        self.assertEqual(len(data["excluded"]), 1)

    def test_negative_golden_metric_is_excluded_and_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "campaign" / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            evaluation = comparison / "evaluation"
            evaluation.mkdir()
            artifacts = {}
            for name in ("log", "drc", "guide", "script"):
                artifact = evaluation / ("openroad_%s.txt" % name)
                artifact.write_text("Number of nets: 1\n" if name == "log" else "")
                artifacts[name] = str(artifact)
            metrics_artifact = evaluation / "openroad_metrics.json"
            metrics_artifact.write_text(json.dumps({
                "route__wirelength": 100,
                "route__vias": 10,
                "route__drc_errors": 0,
                "route__net": 1,
            }))
            artifacts["metrics"] = str(metrics_artifact)
            add_openroad_congestion_artifact(evaluation, artifacts)
            baseline = result("hpwl", "openroad", {
                "wirelength": 100.0, "drc_violations": 0.0,
            })
            baseline["artifacts"] = artifacts
            plugin = result("plugin", "openroad", {
                "wirelength": 90.0, "drc_violations": -1.0,
            })
            plugin["artifacts"] = artifacts
            placements = golden_placement_provenance(
                comparison, ["hpwl", "plugin"]
            )
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": placements,
                "results": [baseline, plugin],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(root / "campaign"),
                "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["validated_comparisons"], 0)
        self.assertEqual(data["excluded"][0]["status"], "invalid_metric")
        self.assertIn("openroad:drc_violations", data["excluded"][0]["error"])

    def test_zero_baseline_count_keeps_full_coverage_with_absolute_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "campaign" / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": "hpwl", "status": "ok", "placement_hpwl": 100.0},
                    {"method": "plugin", "status": "ok", "placement_hpwl": 110.0},
                ],
                "results": [
                    result("hpwl", "gpugr", {"est_shorts": 0.0}),
                    result("plugin", "gpugr", {"est_shorts": 3.0}),
                ],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(root / "campaign"),
                "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        row = next(
            item for item in data["rows"]
            if item["backend"] == "gpugr"
            and item["metric"] == "est_shorts"
            and item["method"] == "plugin"
        )
        self.assertEqual(status, 0)
        self.assertEqual(row["valid_count"], 1)
        self.assertEqual(row["percent_valid_count"], 0)
        self.assertEqual(row["mean_delta"], 3.0)
        self.assertEqual(row["losses"], 1)
        self.assertEqual(row["case_wins"], 0)
        self.assertEqual(row["case_ties"], 0)
        self.assertEqual(row["case_losses"], 1)
        self.assertEqual(row["worst_case"], "case_a")
        self.assertEqual(row["worst_pair_case"], "case_a")
        self.assertEqual(row["worst_pair_seed"], 1)
        self.assertIsNone(row["worst_pair_delta_pct"])
        self.assertEqual(row["worst_pair_delta"], 3.0)

    def test_raw_summary_preserves_reported_proxy_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "campaign" / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            methods = ("hpwl", "plugin")
            results = []
            for backend in ("rudy", "gpugr"):
                for method in methods:
                    results.append(result(method, backend, {
                        "route_x_size": 256,
                        "route_y_size": 256,
                        "overflow_sum": 0.0,
                    }))
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": method, "status": "ok", "placement_hpwl": 100.0}
                    for method in methods
                ],
                "results": results,
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(root / "campaign"),
                "--output-dir", str(output),
            ])
            with (output / "screening_raw.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))

        proxy_rows = [row for row in rows if row["backend"] in ("rudy", "gpugr")]
        self.assertEqual(status, 0)
        self.assertEqual(len(proxy_rows), 4)
        self.assertEqual(
            {(row["route_x_size"], row["route_y_size"]) for row in proxy_rows},
            {("256", "256")},
        )

    def test_validated_comparison_without_hpwl_baseline_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "campaign" / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": "plugin", "status": "ok", "placement_hpwl": 90.0},
                ],
                "results": [
                    result("plugin", "rudy", {"overflow_sum": 8.0}),
                ],
            }))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(root / "campaign"),
                "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(len(data["baseline_gaps"]), 2)

    def test_partial_parallel_campaign_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            comparison = campaign / "case_a" / "seed_1" / "methods"
            comparison.mkdir(parents=True)
            (comparison / "comparison.json").write_text(json.dumps({
                "validation": {"status": "validated"},
                "placements": [
                    {"method": "hpwl", "status": "ok", "placement_hpwl": 100.0},
                ],
                "results": [result("hpwl", "rudy", {"overflow_sum": 8.0})],
            }))
            (campaign / "parallel_status.json").write_text(json.dumps({"jobs": [
                {"case": "case_a", "seed": 1, "status": "completed", "returncode": 0},
                {"case": "case_b", "seed": 2, "status": "running", "returncode": ""},
            ]}))
            output = root / "summary"
            status = main([
                "--campaign-dir", str(campaign), "--output-dir", str(output),
            ])
            data = json.loads((output / "screening_summary.json").read_text())

        self.assertEqual(status, 1)
        self.assertEqual(data["expected_comparisons"], 2)
        self.assertEqual(data["expected_case_seeds"], [
            {"case": "case_a", "seed": 1},
            {"case": "case_b", "seed": 2},
        ])
        self.assertEqual(data["validated_case_seeds"], [
            {"case": "case_a", "seed": 1},
        ])
        self.assertEqual(data["incomplete_jobs"][0]["status"], "running")
        self.assertEqual(data["missing_comparisons"], [{"case": "case_b", "seed": 2}])
        plugin = next(
            row for row in data["rows"]
            if row["backend"] == "rudy" and row["method"] == "hpwl"
        )
        self.assertEqual(plugin["valid_count"], 1)
        self.assertEqual(plugin["expected_count"], 2)
        self.assertFalse(plugin["statistically_supported"])


if __name__ == "__main__":
    unittest.main()
