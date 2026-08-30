#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest


from tools.routability_audit_local_plugins import (
    EXPECTED_TERMINAL_PILOTS,
    audit_local_plugins,
    main,
)
from tools.routability_select_survivors import routability_metric_profile


def metric(value=0.0, worst=0.0):
    return {
        "mean_delta": value,
        "mean_delta_pct": value,
        "median_delta": value,
        "median_delta_pct": value,
        "worst_delta": worst,
        "worst_delta_pct": worst,
        "valid_count": 1,
        "percent_valid_count": 1,
    }


class RoutabilityAuditLocalPluginsTest(unittest.TestCase):
    def fixture(self, root):
        profile = routability_metric_profile("absolute_directional_v2")
        primary = ["%s:%s" % item for item in profile["primary"]]
        source = root / "source"
        source.mkdir()
        specs = []
        roots = {}
        for plugin, (version, count) in EXPECTED_TERMINAL_PILOTS.items():
            pilot = root / plugin
            summary = pilot / "summary"
            campaign = pilot / "campaign"
            install_plugins = (
                pilot / "python_install/dreamplace/ops/routability_opt/plugins"
            )
            summary.mkdir(parents=True)
            campaign.mkdir()
            install_plugins.mkdir(parents=True)
            content = "# %s\n" % plugin
            (source / (plugin + ".py")).write_text(content)
            (install_plugins / (plugin + ".py")).write_text(content)
            methods = ["%s_%02d" % (plugin, index) for index in range(count)]
            generated = {
                method: {
                    "plugins": [plugin],
                    "proxy": "gpugr",
                    "development_only": True,
                }
                for method in methods
            }
            presets = {"hpwl": {}}
            presets.update({
                method: {
                    "ruplace_plugins": [plugin],
                    "ruplace_proxy": "gpugr",
                }
                for method in methods
            })
            (pilot / "presets.json").write_text(json.dumps(presets))
            (pilot / "presets.json.manifest.json").write_text(json.dumps({
                "generated": generated,
                "metadata": {
                    "generated_count": count,
                    "development_only": True,
                    "heldout_or_golden_evidence_used": False,
                    "numeric_backend_mixing": False,
                },
            }))
            rows = []
            for method in methods:
                metrics = {name: metric() for name in primary}
                metrics["gpugr:gr_wirelength"] = metric(-1.0)
                metrics["rudy:overflow_sum"] = metric(-1.0)
                metrics["gpugr:est_shorts"] = metric(0.0, 1.0)
                rows.append({
                    "method": method,
                    "is_atomic_plugin": True,
                    "metrics": metrics,
                })
            (summary / "pilot_survivors.json").write_text(json.dumps({
                "baseline": "hpwl",
                "expected_comparisons": 1,
                "selection_policy": {
                    "name": "routability_first",
                    "metric_profile": "absolute_directional_v2",
                    "numeric_backend_mixing": False,
                    "max_primary_worst_regression": 0.0,
                    "worst_regression_backends": list(
                        profile["worst_regression_backends"]
                    ),
                    "primary_objectives": primary,
                    "backend_improvement_constraints": profile["constraints"],
                },
                "qualified": [],
                "pareto_frontier": [],
                "selected_methods": [],
                "excluded": rows,
            }))
            (pilot / "pilot_audit.json").write_text(json.dumps({
                "status": "passed",
                "candidate_count": count,
                "scope": "development_only_test1_seed1000",
                "heldout_or_golden_evidence_used": False,
                "numeric_backend_mixing": False,
                "selection_or_final_admission_decision": False,
                "selected_in_pilot_only": [],
                "gpugr_binary_sha256": "a" * 64,
            }))
            (summary / "placement_effect_audit.json").write_text(json.dumps({
                "status": "passed",
                "expected_comparisons": 1,
                "validated_comparisons": 1,
                "placement_count": count,
                "active_changed_count": count,
                "active_identical_count": 0,
                "inactive_changed_count": 0,
                "inactive_identical_count": 0,
            }))
            (summary / "near_misses.json").write_text(json.dumps({
                "expected_comparisons": 1,
                "policy": {
                    "complete_campaign_required": True,
                    "metric_profile": "absolute_directional_v2",
                    "numeric_backend_mixing": False,
                    "selection_or_admission_decision": False,
                },
            }))
            (summary / "screening_summary.json").write_text(json.dumps({
                "expected_comparisons": 1,
                "validated_comparisons": 1,
                "missing_comparisons": [],
                "incomplete_jobs": [],
            }))
            (summary / "screening_raw.csv").write_text("backend,method\n")
            (campaign / "parallel_status.json").write_text(json.dumps({
                "jobs": [{
                    "case": "data_ispd19_test1",
                    "seed": 1000,
                    "status": "completed",
                    "returncode": 0,
                }],
            }))
            (pilot / "HANDOFF_STATUS.md").write_text(
                "phase=completed_development_pilot\n"
                "scope=data_ispd19_test1_seed_1000_development_only\n"
                "evaluators=rudy,gpugr\n"
                "metric_profile=absolute_directional_v2\n"
            )
            specs.append("%s=%s=%s" % (plugin, version, pilot))
            roots[plugin] = pilot
        return specs, source, roots

    def test_audits_all_terminal_pilots_and_current_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs, source, _roots = self.fixture(Path(tmp))
            result = audit_local_plugins(specs, source)
        self.assertEqual(result["selected_methods"], [])
        self.assertEqual(set(result["plugins"]), set(EXPECTED_TERMINAL_PILOTS))
        self.assertTrue(all(
            row["strict_recomputed_survivor_count"] == 0
            for row in result["plugins"].values()
        ))

    def test_rejects_candidate_that_actually_passes_strict_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs, source, roots = self.fixture(Path(tmp))
            path = roots["virtual_cell"] / "summary/pilot_survivors.json"
            selection = json.loads(path.read_text())
            selection["excluded"][0]["metrics"]["gpugr:est_shorts"].update({
                "worst_delta": 0.0,
                "worst_delta_pct": 0.0,
            })
            selection["excluded"][0]["metrics"]["rudy:utilization_max"].update({
                "worst_delta": 1.0,
                "worst_delta_pct": 1.0,
            })
            path.write_text(json.dumps(selection))
            with self.assertRaisesRegex(ValueError, "satisfies the strict"):
                audit_local_plugins(specs, source)

    def test_main_writes_attestation_and_rejects_source_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs, source, _roots = self.fixture(root)
            output = root / "attestation.json"
            argv = []
            for spec in specs:
                argv.extend(("--pilot", spec))
            argv.extend(("--source-dir", str(source), "--output", str(output)))
            self.assertEqual(main(argv), 0)
            self.assertTrue(output.is_file())
            (source / "connection_routeforce.py").write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "did not evaluate current source"):
                audit_local_plugins(specs, source)

    def test_cross_pilot_snapshot_cannot_replace_terminal_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs, source, roots = self.fixture(Path(tmp))
            plugin = "connection_routeforce"
            changed = "changed after terminal pilot\n"
            (source / (plugin + ".py")).write_text(changed)
            witness = (
                roots["virtual_cell"]
                / "python_install/dreamplace/ops/routability_opt/plugins"
                / (plugin + ".py")
            )
            witness.write_text(changed)
            with self.assertRaisesRegex(ValueError, "did not evaluate current source"):
                audit_local_plugins(specs, source)


if __name__ == "__main__":
    unittest.main()
