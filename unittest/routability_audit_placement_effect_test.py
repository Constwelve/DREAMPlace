#!/usr/bin/env python3

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.routability_audit_placement_effect import audit_placement_effect, main


def plugin_summary(active):
    return {
        "pipeline": {},
        "plugins": {
            "path_inflation": {
                "status": "active" if active else "attempted_no_change",
                "activations": 1 if active else 0,
            },
        },
    }


class RoutabilityAuditPlacementEffectTest(unittest.TestCase):
    def make_campaign(self, root, active_def="changed"):
        methods = root / "case_a" / "seed_1000" / "case_a" / "methods"
        placements = [
            {
                "method": "hpwl", "status": "ok",
                "routability_plugin_status": "not_selected",
                "routability_plugin_selected": "",
                "routability_plugin_summary": {"pipeline": {}, "plugins": {}},
            },
            {
                "method": "active", "status": "ok",
                "routability_plugin_status": "active",
                "routability_plugin_selected": "path_inflation",
                "routability_plugin_summary": plugin_summary(True),
            },
            {
                "method": "inactive", "status": "ok",
                "routability_plugin_status": "selected_no_activation",
                "routability_plugin_selected": "path_inflation",
                "routability_plugin_summary": plugin_summary(False),
            },
        ]
        methods.mkdir(parents=True)
        (methods / "comparison.json").write_text(json.dumps({
            "validation": {"status": "validated"},
            "placement_input_provenance": {"files": {}},
            "placement_implementation_provenance": {"files": {}},
            "placement_runtime_provenance": {"host": {}},
            "placements": placements,
        }))
        for method in ("hpwl", "active", "inactive"):
            method_dir = methods / method
            method_dir.mkdir()
            config = (
                {"ruplace_plugins": []}
                if method == "hpwl" else
                {"ruplace_plugins": ["path_inflation"]}
            )
            (method_dir / "config.json").write_text(json.dumps(config))
            output = method_dir / "placement" / "design.input"
            output.mkdir(parents=True)
            value = "baseline"
            if method == "active":
                value = active_def
            (output / "design.input.gp.def").write_text(value)
        comparison_path = methods / "comparison.json"
        comparison = json.loads(comparison_path.read_text())
        for placement in comparison["placements"]:
            placed = next(
                (methods / placement["method"] / "placement").glob("**/*.gp.def")
            )
            digest = hashlib.sha256(placed.read_bytes()).hexdigest()
            placement.update({
                "placed_def": str(placed.resolve()),
                "placed_def_sha256": digest,
                "placement_geometry_provenance": {
                    "status": "ok",
                    "def_sha256": digest,
                    "overlap_pair_count": 0,
                    "unplaced_component_count": 0,
                    "uncovered_component_count": 0,
                },
            })
        comparison_path.write_text(json.dumps(comparison))
        return methods

    def make_snapshot(self, root):
        source_root = root / "source"
        source_methods = self.make_campaign(source_root)
        snapshot_root = root / "snapshot"
        snapshot_methods = (
            snapshot_root / "case_a" / "seed_1000" / "case_a" / "methods"
        )
        snapshot_methods.mkdir(parents=True)
        source_comparison = source_methods / "comparison.json"
        snapshot_comparison = snapshot_methods / "comparison.json"
        snapshot_comparison.write_bytes(source_comparison.read_bytes())

        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        sources = []
        for method in ("hpwl", "active", "inactive"):
            method_dir = source_methods / method
            config = method_dir / "config.json"
            placed = next((method_dir / "placement").glob("**/*.gp.def"))
            sources.append({
                "method": method,
                "config": str(config.resolve()),
                "config_sha256": digest(config),
                "placed_def": str(placed.resolve()),
                "placed_def_sha256": digest(placed),
            })
        (snapshot_root / "snapshot_manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "comparisons": [{
                "case": "case_a",
                "seed": 1000,
                "comparison": str(snapshot_comparison.resolve()),
                "comparison_sha256": digest(snapshot_comparison),
                "sources": sources,
            }],
        }))
        return snapshot_root, source_methods

    def test_accepts_active_change_and_records_inactive_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_campaign(root)
            result = audit_placement_effect(root, 1)
            output = root / "audit.json"
            status = main([
                "--campaign-dir", str(root),
                "--expected-comparisons", "1",
                "--output", str(output),
            ])
            persisted = json.loads(output.read_text())

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["active_changed_count"], 1)
        self.assertEqual(result["active_changed_methods"], ["active"])
        self.assertEqual(result["inactive_identical_count"], 1)
        self.assertEqual(result["inactive_identical_methods"], ["inactive"])
        self.assertEqual(result["inactive_changed_count"], 0)
        self.assertEqual(result["inactive_changed_methods"], [])
        self.assertEqual(result["inactive_methods"], ["inactive"])
        self.assertEqual(status, 0)
        self.assertEqual(persisted["contract"], result["contract"])

    def test_rejects_active_plugin_with_identical_def(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_campaign(root, active_def="baseline")
            with self.assertRaisesRegex(
                ValueError, "active plugin emitted the baseline placement"
            ):
                audit_placement_effect(root, 1)

    def test_opt_in_records_active_identical_for_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_campaign(root, active_def="baseline")
            result = audit_placement_effect(
                root, 1, allow_active_identical=True
            )
            output = root / "audit.json"
            status = main([
                "--campaign-dir", str(root),
                "--expected-comparisons", "1",
                "--allow-active-identical",
                "--output", str(output),
            ])
            persisted = json.loads(output.read_text())

        self.assertEqual(
            result["status"],
            "passed_with_active_identical_candidates_excluded",
        )
        self.assertEqual(result["active_identical_count"], 1)
        self.assertEqual(result["active_identical_methods"], ["active"])
        self.assertEqual(status, 0)
        self.assertEqual(persisted["active_identical_count"], 1)

    def test_records_inactive_changed_placement_for_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            inactive_def = next(
                (methods / "inactive" / "placement").glob("**/*.gp.def")
            )
            inactive_def.write_text("changed by enabled routability path")
            digest = hashlib.sha256(inactive_def.read_bytes()).hexdigest()
            comparison_path = methods / "comparison.json"
            comparison = json.loads(comparison_path.read_text())
            inactive = next(
                row for row in comparison["placements"]
                if row["method"] == "inactive"
            )
            inactive["placed_def_sha256"] = digest
            inactive["placement_geometry_provenance"]["def_sha256"] = digest
            comparison_path.write_text(json.dumps(comparison))
            result = audit_placement_effect(root, 1)

        self.assertEqual(result["inactive_changed_count"], 1)
        self.assertEqual(result["inactive_changed_methods"], ["inactive"])
        self.assertEqual(result["inactive_identical_count"], 0)
        self.assertEqual(result["inactive_methods"], ["inactive"])

    def test_rejects_incomplete_comparison_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_campaign(root)
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                audit_placement_effect(root, 2)

    def test_rejects_missing_placement_runtime_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            comparison_path = methods / "comparison.json"
            comparison = json.loads(comparison_path.read_text())
            del comparison["placement_runtime_provenance"]
            comparison_path.write_text(json.dumps(comparison))
            with self.assertRaisesRegex(
                ValueError, "lacks placement provenance"
            ):
                audit_placement_effect(root, 1)

    def test_rejects_illegal_exported_placement_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            comparison_path = methods / "comparison.json"
            comparison = json.loads(comparison_path.read_text())
            active = next(
                row for row in comparison["placements"]
                if row["method"] == "active"
            )
            active["placement_geometry_provenance"]["overlap_pair_count"] = 1
            comparison_path.write_text(json.dumps(comparison))
            with self.assertRaisesRegex(
                ValueError, "nonzero overlap_pair_count"
            ):
                audit_placement_effect(root, 1)

    def test_rejects_modified_placed_def(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            active_def = next(
                (methods / "active" / "placement").glob("**/*.gp.def")
            )
            active_def.write_text("modified after comparison")
            with self.assertRaisesRegex(ValueError, "placed DEF hash"):
                audit_placement_effect(root, 1)

    def test_accepts_hash_verified_partial_snapshot_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, _ = self.make_snapshot(Path(tmp))
            result = audit_placement_effect(snapshot, 1)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["source_provenance"], "snapshot_manifest")
        self.assertEqual(result["active_changed_count"], 1)
        self.assertEqual(result["inactive_identical_count"], 1)
        self.assertRegex(result["snapshot_manifest_sha256"], r"^[0-9a-f]{64}$")

    def test_rejects_tampered_partial_snapshot_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, source_methods = self.make_snapshot(Path(tmp))
            active_def = next(
                (source_methods / "active" / "placement").glob("**/*.gp.def")
            )
            active_def.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "snapshot active DEF hash mismatch"):
                audit_placement_effect(snapshot, 1)

    def test_requires_configured_area_budget_in_runtime_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            active_dir = methods / "active"
            config_path = active_dir / "config.json"
            config = json.loads(config_path.read_text())
            config.update({
                "ruplace_enforce_area_adjust_budget": 1,
                "max_num_area_adjust": 2,
            })
            config_path.write_text(json.dumps(config))
            comparison_path = methods / "comparison.json"
            comparison = json.loads(comparison_path.read_text())
            active = next(
                row for row in comparison["placements"]
                if row["method"] == "active"
            )
            active["routability_plugin_summary"]["pipeline"] = {
                "area_budget_enabled": 1,
                "area_adjustments": 2,
                "max_area_adjustments": 2,
                "area_budget_observations": [{
                    "area_budget_enabled": 1,
                    "area_adjustments": 2,
                    "max_area_adjustments": 2,
                }],
            }
            comparison_path.write_text(json.dumps(comparison))

            result = audit_placement_effect(root, 1)
            self.assertEqual(result["area_budget_checked_count"], 1)
            self.assertEqual(result["schema_version"], 2)

            active["routability_plugin_summary"]["pipeline"][
                "area_budget_observations"
            ][0]["area_budget_enabled"] = 0
            comparison_path.write_text(json.dumps(comparison))
            with self.assertRaisesRegex(
                ValueError, "configured area budget was not enabled"
            ):
                audit_placement_effect(root, 1)

    def test_rejects_runtime_area_adjustments_above_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            active_dir = methods / "active"
            config = json.loads((active_dir / "config.json").read_text())
            config.update({
                "ruplace_enforce_area_adjust_budget": 1,
                "max_num_area_adjust": 1,
            })
            (active_dir / "config.json").write_text(json.dumps(config))
            comparison_path = methods / "comparison.json"
            comparison = json.loads(comparison_path.read_text())
            active = next(
                row for row in comparison["placements"]
                if row["method"] == "active"
            )
            active["routability_plugin_summary"]["pipeline"] = {
                "area_budget_enabled": 1,
                "area_adjustments": 2,
                "max_area_adjustments": 1,
            }
            comparison_path.write_text(json.dumps(comparison))

            with self.assertRaisesRegex(
                ValueError, "area adjustments exceed configured maximum"
            ):
                audit_placement_effect(root, 1)

    def configure_force_budget(self, methods, maximum=2, runtime_maximum=2,
                               applications=2, include_metrics=True,
                               plugin_specific=False):
        active_dir = methods / "active"
        config_path = active_dir / "config.json"
        config = json.loads(config_path.read_text())
        config["ruplace_force_max_applications"] = maximum + 5
        if plugin_specific:
            config["ruplace_path_inflation_max_applications"] = maximum
        elif maximum is not None:
            config["ruplace_force_max_applications"] = maximum
        config_path.write_text(json.dumps(config))

        comparison_path = methods / "comparison.json"
        comparison = json.loads(comparison_path.read_text())
        active = next(
            row for row in comparison["placements"]
            if row["method"] == "active"
        )
        if include_metrics:
            active["routability_plugin_summary"]["plugins"][
                "path_inflation"
            ]["metrics"] = {
                "force_max_applications": runtime_maximum,
                "force_applications": applications,
            }
        comparison_path.write_text(json.dumps(comparison))

    def test_accepts_force_budget_with_plugin_specific_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            self.configure_force_budget(methods, plugin_specific=True)
            result = audit_placement_effect(root, 1)

        self.assertEqual(result["force_budget_checked_count"], 1)
        active = next(row for row in result["rows"] if row["method"] == "active")
        self.assertTrue(active["force_budget_configured"])
        self.assertEqual(active["force_budget_checked_count"], 1)
        self.assertEqual(active["force_budget_checked_plugins"], ["path_inflation"])
        self.assertIsNone(active["force_budget_runtime_error"])

    def test_rejects_missing_runtime_force_budget_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            self.configure_force_budget(methods, include_metrics=False)
            with self.assertRaisesRegex(
                ValueError, "missing runtime force budget summary"
            ):
                audit_placement_effect(root, 1)

    def test_rejects_mismatched_runtime_force_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            self.configure_force_budget(methods, runtime_maximum=3)
            with self.assertRaisesRegex(
                ValueError, "does not match configured maximum"
            ):
                audit_placement_effect(root, 1)

    def test_rejects_runtime_force_applications_above_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            methods = self.make_campaign(root)
            self.configure_force_budget(methods, applications=3)
            with self.assertRaisesRegex(
                ValueError, "force applications.*exceed configured maximum"
            ):
                audit_placement_effect(root, 1)


if __name__ == "__main__":
    unittest.main()
