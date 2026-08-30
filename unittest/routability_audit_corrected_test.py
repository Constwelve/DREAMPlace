#!/usr/bin/env python3

import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


from tools.routability_audit_corrected import (
    EXPECTED_GOLDEN_CASES,
    EXPECTED_SEEDS,
    EXPECTED_PROXY_COMPARISONS,
    EXPECTED_PROXY_RESOLUTIONS,
    EXPECTED_PROXY_STAGE_SLOTS,
    LOCAL_PLUGIN_TERMINAL_VERSIONS,
    MISSING_FAMILY_TUNING_KEYS,
    MISSING_FAMILY_STAGE,
    POLICY_V7_STAGE,
    PROXY_METRIC_PROFILE_FILES,
    REQUIRED_MISSING_FAMILIES,
    audit_final,
    audit_evaluator_activation,
    audit_no_candidate_final,
    audit_no_candidate_proxy,
    audit_missing_family_attestation_record,
    audit_local_plugin_attestation_record,
    audit_proxy_chain,
    audit_proxy_bound_plugin_identity,
    audit_proxy_metric_profile,
    audit_proxy_resolution_evidence,
    audit_proxy_resolution_record,
    audit_strict_selection,
    canonical_json_sha256,
    result_slot,
    sha256,
)
from tools.routability_select_survivors import (
    routability_metric_profile,
)


def strict_selection(method="plugin", worst=0.0, metric_profile="legacy",
                     expected=3, worst_backend="gpugr"):
    profile = routability_metric_profile(metric_profile)
    primary = ["%s:%s" % item for item in profile["primary"]]
    metrics = {}
    for name in primary:
        mean = -1.0 if name in ("gpugr:gr_wirelength", "rudy:overflow_sum") else 0.0
        metrics[name] = {
            "mean_delta": mean,
            "mean_delta_pct": mean,
            "median_delta": mean,
            "median_delta_pct": mean,
            "worst_delta": worst if name.startswith(worst_backend + ":") else 0.0,
            "worst_delta_pct": (
                worst if name.startswith(worst_backend + ":") else 0.0
            ),
            "valid_count": expected,
            "percent_valid_count": expected,
        }
    return {
        "baseline": "hpwl",
        "expected_comparisons": expected,
        "selection_policy": {
            "name": "routability_first",
            "metric_profile": metric_profile,
            "numeric_backend_mixing": False,
            "max_primary_worst_regression": 0.0,
            "worst_regression_backends": list(
                profile["worst_regression_backends"]
            ),
            "primary_objectives": primary,
            "backend_improvement_constraints": json.loads(json.dumps(
                profile["constraints"]
            )),
        },
        "qualified": [{"method": method, "metrics": metrics}],
        "pareto_frontier": [method],
        "selected_methods": [method],
    }


class RoutabilityAuditCorrectedTest(unittest.TestCase):
    def write_policy_v7_attestation(self, root, selection_path):
        raw_path = selection_path.parent / "screening_raw.csv"
        path = root / "policy_v7_attestation.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "status": "passed",
            "stage": POLICY_V7_STAGE,
            "proposal_policy_version": 7,
            "metric_profile": "absolute_directional_v2",
            "numeric_backend_mixing": False,
            "heldout_or_golden_evidence_used": False,
            "candidate_count": 192,
            "method_count": 193,
            "comparison_count": 6,
            "candidate_placement_count": 1152,
            "evaluator_result_count": 2316,
            "placement_hpwl_count": 1158,
            "primary_metric_value_count": 33582,
            "factorial_dimensions": {
                "feedback_proxies": ["gpugr", "rudy"],
                "gammas": [0.005, 0.025],
                "frequencies": [10, 40],
                "activation_thresholds": [0.4, 0.8],
                "normalizations": ["absolute", "design_mean"],
                "lifecycle_phases": ["post_gradient", "pre_objective"],
                "score_modes": ["bbox_mean", "bbox_pmean", "pin_mean"],
            },
            "factorial_unique_point_count": 192,
            "optimization_source_install_match": True,
            "optimization_source_sha256": {
                "dreamplace/PlaceObj.py": "1" * 64,
                "dreamplace/ops/routability_opt/plugin_base.py": "2" * 64,
                "dreamplace/ops/routability_opt/pipeline.py": "3" * 64,
                "dreamplace/ops/routability_opt/proxy.py": "4" * 64,
                "dreamplace/ops/routability_opt/plugins/net_weighting.py": (
                    "5" * 64
                ),
                "dreamplace/params.json": "6" * 64,
            },
            "active_net_mask_audit_status": "passed",
            "gpugr_runtime_sha256": {
                "gpugr_extension": "9" * 64,
                "io_parser_extension": "a" * 64,
                "xplace_common": "b" * 64,
                "xplace_flute": "c" * 64,
            },
            "selected_methods": [],
            "selection_recomputed": True,
            "placement_effect_recomputed": True,
            "active_changed_count": 990,
            "active_identical_count": 2,
            "inactive_identical_count": 112,
            "inactive_changed_count": 48,
            "placement_effect_excluded_methods": [
                "inactive_method", "active_identical_method",
            ],
            "sha256": {
                "presets": "a" * 64,
                "manifest": "b" * 64,
                "summary": "c" * 64,
                "screening_raw": sha256(raw_path),
                "selection": sha256(selection_path),
                "placement_effect_audit": "d" * 64,
                "selection_audit": "e" * 64,
                "terminal_status": "f" * 64,
                "optimization_source_install": "7" * 64,
                "active_net_mask_audit": "8" * 64,
            },
        }))
        return path

    def family_attestation(self):
        coverage = {
            family: [
                "%s_method_%d" % (family, index) for index in range(6)
            ]
            for family in REQUIRED_MISSING_FAMILIES
        }
        tuning = {}
        for family in REQUIRED_MISSING_FAMILIES:
            threshold_key = (
                "ruplace_plugin_start_overflow"
                if family == "routeforce"
                else "ruplace_inflate_start_overflow"
            )
            keys = MISSING_FAMILY_TUNING_KEYS[family]
            tuning[family] = {
                "variant_count": 6,
                "activation_threshold_key": threshold_key,
                "activation_thresholds": [0.3, 0.5, 0.8],
                "varied_parameter_keys": list(keys),
                "parameter_values": {key: [0, 1] for key in keys},
            }
        return {
            "schema_version": 1,
            "status": "passed",
            "stage": MISSING_FAMILY_STAGE,
            "metric_profile": "absolute_directional_v2",
            "numeric_backend_mixing": False,
            "heldout_or_golden_evidence_used": False,
            "required_families": list(REQUIRED_MISSING_FAMILIES),
            "family_methods": coverage,
            "retained_family_methods": {
                family: list(methods) for family, methods in coverage.items()
            },
            "activation_contract": (
                "every retained plugin is active on every development case/seed"
            ),
            "activation_audit": {
                "schema_version": 1,
                "status": "passed",
                "case_seed_count": len(
                    EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE]
                ),
                "method_count": 1 + sum(len(row) for row in coverage.values()),
                "inactive_method_count": 0,
                "inactive_methods": [],
            },
            "excluded_inactive_methods": [],
            "tuning_coverage": tuning,
            "evaluated_methods": ["hpwl"] + [
                method for methods in coverage.values() for method in methods
            ],
            "selected_methods": [],
            "validated_case_seeds": [
                {"case": case, "seed": seed}
                for case, seed in EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE]
            ],
            "reported_resolution": [256, 256],
            "validated_retained_placements": (
                len(EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE])
                * sum(len(row) for row in coverage.values())
            ),
            "validated_proxy_results": (
                len(EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE])
                * (1 + sum(len(row) for row in coverage.values())) * 2
            ),
            "sha256": {
                "presets": "a" * 64,
                "manifest": "b" * 64,
                "selection": "c" * 64,
                "screening_raw": "d" * 64,
            },
        }

    def write_family_attestation(self, root):
        path = root / "family_attestation.json"
        path.write_text(json.dumps(self.family_attestation()))
        return path

    def write_local_plugin_attestation(self, root):
        source = root / "local_plugin_source"
        source.mkdir(exist_ok=True)
        plugins = {}
        for plugin, version in LOCAL_PLUGIN_TERMINAL_VERSIONS.items():
            path = source / (plugin + ".py")
            path.write_text("# %s\n" % plugin)
            digest = sha256(path)
            plugins[plugin] = {
                "terminal_version": version,
                "candidate_count": 1,
                "selected_methods": [],
                "strict_recomputed_survivor_count": 0,
                "metric_profile": "absolute_directional_v2",
                "validators": ["gpugr", "rudy"],
                "numeric_backend_mixing": False,
                "heldout_or_golden_evidence_used": False,
                "current_source_snapshot_witnesses": [plugin],
                "terminal_source_matches_current": True,
                "terminal_evaluated_plugin_sha256": digest,
                "current_source_sha256": digest,
                "selection_content_sha256": "b" * 64,
                "gpugr_binary_sha256": "a" * 64,
                "evidence_sha256": {"selection": "c" * 64},
            }
        path = root / "local_plugin_attestation.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "status": "passed",
            "stage": "local_plugin_terminal_pilots",
            "conclusion": "no_strict_local_plugin_survivor",
            "metric_profile": "absolute_directional_v2",
            "validators": ["gpugr", "rudy"],
            "numeric_backend_mixing": False,
            "heldout_or_golden_evidence_used": False,
            "selected_methods": [],
            "terminal_versions": LOCAL_PLUGIN_TERMINAL_VERSIONS,
            "source_dir": str(source),
            "gpugr_binary_sha256": "a" * 64,
            "plugins": plugins,
        }))
        return path

    def write_resolution_evidence(self, selection_path, selection,
                                  comparisons, resolution,
                                  stage_label="contest_heldout",
                                  missing_columns=(), mutate=None):
        methods = {selection["baseline"]}
        for group in ("qualified", "excluded"):
            methods.update(
                row["method"] for row in selection.get(group, [])
            )
        fieldnames = [
            "backend", "case", "seed", "method", "status",
            "route_x_size", "route_y_size",
        ]
        fieldnames = [
            name for name in fieldnames if name not in set(missing_columns)
        ]
        rows = []
        slots = list(EXPECTED_PROXY_STAGE_SLOTS[stage_label])
        self.assertEqual(len(slots), comparisons)
        for backend in ("rudy", "gpugr"):
            for method in sorted(methods):
                for case, seed in slots:
                    rows.append({
                        "backend": backend,
                        "case": case,
                        "seed": seed,
                        "method": method,
                        "status": "ok",
                        "route_x_size": resolution[0],
                        "route_y_size": resolution[1],
                    })
        if mutate is not None:
            mutate(rows)
        raw_path = selection_path.parent / "screening_raw.csv"
        with raw_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return raw_path

    def resolution_record(self, label, methods=("hpwl", "plugin")):
        comparisons = EXPECTED_PROXY_COMPARISONS[label]
        return {
            "raw_path": "/evidence/%s/screening_raw.csv" % label,
            "raw_sha256": "d" * 64,
            "reported_resolution": list(EXPECTED_PROXY_RESOLUTIONS[label]),
            "methods": list(methods),
            "validated_comparisons": comparisons,
            "validated_results": 2 * len(methods) * comparisons,
            "comparison_slots": [
                {"case": case, "seed": seed}
                for case, seed in EXPECTED_PROXY_STAGE_SLOTS[label]
            ],
        }

    def metric_profile_fixture(self, root):
        source = root / "source"
        installed = root / "install"
        rows = []
        for name in PROXY_METRIC_PROFILE_FILES:
            source_path = source / name
            installed_path = installed / name
            source_path.parent.mkdir(parents=True, exist_ok=True)
            installed_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(name + "\n")
            installed_path.write_text(name + "\n")
            digest = sha256(source_path)
            rows.extend((
                "%s  %s" % (digest, name),
                "%s  install/%s" % (digest, name),
            ))
        manifest = root / "metric_profile.sha256"
        manifest.write_text("\n".join(rows) + "\n")
        return manifest, source, installed

    def proxy_chain_fixture(self, root, extra_real_development=False,
                            extra_real_heldout=False):
        selections = {}
        paths = {}
        for label, comparisons in EXPECTED_PROXY_COMPARISONS.items():
            path = root / label / "survivors.json"
            path.parent.mkdir(parents=True)
            selection = strict_selection(
                method="plugin", metric_profile="absolute_directional_v2",
                expected=comparisons,
            )
            if label == "contest_heldout":
                selection["excluded"] = [{"method": "discarded_contest"}]
            elif label == "real_development" and extra_real_development:
                selection["excluded"] = [{"method": "extra_real_development"}]
            elif label == "real_heldout" and extra_real_heldout:
                selection["excluded"] = [{"method": "extra_real_heldout"}]
            path.write_text(json.dumps(selection))
            self.write_resolution_evidence(
                path, selection, comparisons,
                EXPECTED_PROXY_RESOLUTIONS[label], stage_label=label,
            )
            selections[label] = selection
            paths[label] = path
        frozen = root / "frozen.json"
        frozen.write_text(json.dumps({"hpwl": {}, "plugin": {}}))
        status = root / "real_status.md"
        status.write_text("phase=completed_real_heldout_proxy_validation\n")
        manifest, source, installed = self.metric_profile_fixture(
            root / "metric_profile"
        )
        family_attestation = self.write_family_attestation(root)
        return SimpleNamespace(
            contest_selection=paths["contest_heldout"],
            real_development_selection=paths["real_development"],
            real_heldout_selection=paths["real_heldout"],
            frozen_presets=frozen,
            real_status=status,
            proxy_metric_profile_manifest=manifest,
            development_family_attestation=family_attestation,
            proxy_source_root=source,
            proxy_install_root=installed,
        )

    def test_proxy_metric_profile_binds_source_and_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, source, installed = self.metric_profile_fixture(Path(tmp))
            result = audit_proxy_metric_profile(manifest, source, installed)
        self.assertTrue(result["source_install_match"])
        self.assertEqual(len(result["files"]), 4)

    def test_missing_family_attestation_excludes_inactive_method(self):
        record = self.family_attestation()
        family = REQUIRED_MISSING_FAMILIES[0]
        method = record["retained_family_methods"][family].pop()
        exclusion = {
            "method": method,
            "plugins": [family],
            "proxy": "rudy",
            "affected_case_seeds": [{
                "case": "data_ispd19_test1",
                "seed": 1000,
                "activation_error": "%s did not activate" % method,
            }],
        }
        record["excluded_inactive_methods"] = [exclusion]
        record["activation_audit"].update({
            "status": "inactive_methods",
            "inactive_method_count": 1,
            "inactive_methods": [exclusion],
        })
        record["validated_retained_placements"] -= len(
            EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE]
        )

        self.assertIs(audit_missing_family_attestation_record(record), record)

        record["selected_methods"] = [method]
        with self.assertRaisesRegex(ValueError, "selection mismatch"):
            audit_missing_family_attestation_record(record)

    def test_proxy_metric_profile_rejects_changed_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, source, installed = self.metric_profile_fixture(Path(tmp))
            target = installed / "dreamplace/ops/routability_eval/xplace.py"
            target.write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "source/install mismatch"):
                audit_proxy_metric_profile(manifest, source, installed)

    def test_local_plugin_attestation_rejects_current_source_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_local_plugin_attestation(root)
            record = json.loads(path.read_text())
            self.assertIs(audit_local_plugin_attestation_record(record), record)
            source = Path(record["source_dir"])
            (source / "virtual_cell.py").write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "virtual_cell"):
                audit_local_plugin_attestation_record(record)

    def test_proxy_bound_plugin_identity_requires_same_proxy_and_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proxy = root / "proxy.json"
            proxy.write_text("{}\n")
            attestation = root / "openroad.json"
            record = {
                "status": "passed",
                "stage": "golden_router",
                "backend": "openroad",
                "methods": ["hpwl", "plugin"],
                "source_install_plugins_match": True,
                "plugin_sha256": {"plugin.py": "a" * 64},
                "sha256": {"proxy_attestation": sha256(proxy)},
            }
            attestation.write_text(json.dumps(record))
            hashes, digest = audit_proxy_bound_plugin_identity(
                attestation, proxy, ["hpwl", "plugin"]
            )
            self.assertEqual(hashes, record["plugin_sha256"])
            self.assertEqual(digest, sha256(attestation))
            record["methods"] = ["hpwl", "other"]
            attestation.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "proxy-bound"):
                audit_proxy_bound_plugin_identity(
                    attestation, proxy, ["hpwl", "plugin"]
                )

    def final_fixture(self, root):
        proxy_path = root / "proxy.json"
        proxy = {
            "status": "passed",
            "stage": "proxy_chain",
            "metric_profile": "absolute_directional_v2",
            "metric_profile_code": {
                "manifest_sha256": "a" * 64,
                "source_install_match": True,
                "files": {
                    name: "b" * 64 for name in PROXY_METRIC_PROFILE_FILES
                },
            },
            "final_methods": ["hpwl", "plugin"],
            "selection_content_sha256": {"real_heldout": "selection-hash"},
            "proxy_resolution_evidence": {
                label: self.resolution_record(label)
                for label in EXPECTED_PROXY_COMPARISONS
            },
            "development_family_evidence": self.family_attestation(),
            "sha256": {
                "proxy_metric_profile_manifest": "a" * 64,
                **{
                    "proxy_resolution_raw:%s" % label: "d" * 64
                    for label in EXPECTED_PROXY_COMPARISONS
                },
            },
        }
        proxy_path.write_text(json.dumps(proxy))
        summaries = {}
        attestations = {}
        for backend in ("openroad", "innovus"):
            summary_path = root / (backend + "_summary.json")
            summary_path.write_text(json.dumps({"backend": backend}))
            summaries[backend] = summary_path
            cases = list(EXPECTED_GOLDEN_CASES[backend])
            seeds = list(EXPECTED_SEEDS)
            comparisons = len(cases) * len(seeds)
            results = comparisons * len(proxy["final_methods"])
            attestation_path = root / (backend + "_attestation.json")
            attestation_path.write_text(json.dumps({
                "status": "passed",
                "stage": "golden_router",
                "backend": backend,
                "cases": cases,
                "seeds": seeds,
                "methods": proxy["final_methods"],
                "validated_comparisons": comparisons,
                "validated_results": results,
                "result_evidence": {
                    "result_%d" % index: {} for index in range(results)
                },
                "summary_content_sha256": canonical_json_sha256(
                    {"backend": backend}
                ),
                "proxy_final_selection_sha256": "selection-hash",
                "sha256": {
                    "proxy_attestation": sha256(proxy_path),
                    "summary": sha256(summary_path),
                },
            }))
            attestations[backend] = attestation_path
        ranking = {"recommended_methods": ["hpwl"], "robust_routability_winners": []}
        ranking_path = root / "ranking.json"
        ranking_path.write_text(json.dumps(ranking))
        report_path = root / "ranking.md"
        report_path.write_text("ranking report\n")
        local_plugin_attestation = self.write_local_plugin_attestation(root)
        return SimpleNamespace(
            proxy_attestation=proxy_path,
            openroad_attestation=attestations["openroad"],
            innovus_attestation=attestations["innovus"],
            openroad_summary=summaries["openroad"],
            innovus_summary=summaries["innovus"],
            ranking=ranking_path,
            report=report_path,
            local_plugin_attestation=local_plugin_attestation,
        ), ranking

    def test_final_audit_binds_proxy_router_matrices_and_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, ranking = self.final_fixture(Path(tmp))
            with mock.patch(
                "tools.routability_audit_corrected.rank_campaigns",
                return_value=ranking,
            ), mock.patch(
                "tools.routability_audit_corrected.render_report",
                return_value="ranking report\n",
            ):
                result = audit_final(args)
        self.assertEqual(result["conclusion"], "no_safe_golden_candidate")

    def test_final_audit_rejects_router_bound_to_different_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, ranking = self.final_fixture(Path(tmp))
            attestation = json.loads(args.openroad_attestation.read_text())
            attestation["sha256"]["proxy_attestation"] = "stale"
            args.openroad_attestation.write_text(json.dumps(attestation))
            with mock.patch(
                "tools.routability_audit_corrected.rank_campaigns",
                return_value=ranking,
            ), mock.patch(
                "tools.routability_audit_corrected.render_report",
                return_value="ranking report\n",
            ), self.assertRaisesRegex(ValueError, "different proxy"):
                audit_final(args)

    def test_final_audit_rejects_incomplete_router_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, ranking = self.final_fixture(Path(tmp))
            attestation = json.loads(args.innovus_attestation.read_text())
            attestation["validated_results"] -= 1
            args.innovus_attestation.write_text(json.dumps(attestation))
            with mock.patch(
                "tools.routability_audit_corrected.rank_campaigns",
                return_value=ranking,
            ), mock.patch(
                "tools.routability_audit_corrected.render_report",
                return_value="ranking report\n",
            ), self.assertRaisesRegex(ValueError, "matrix mismatch"):
                audit_final(args)

    def test_innovus_activation_evidence_is_bound_to_source_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            installed = root / "installed"
            source.mkdir()
            installed.mkdir()
            hashes = {}
            modules = {}
            for name in ("base.py", "innovus.py", "openroad.py"):
                (source / name).write_text(name + "\n")
                (installed / name).write_text(name + "\n")
                hashes[name] = sha256(source / name)
                modules[name] = {
                    "source_sha256": hashes[name],
                    "installed_after_sha256": hashes[name],
                    "byte_identical": True,
                }
            manifest = root / "activation.json"
            manifest.write_text(json.dumps({
                "status": "passed",
                "source_dir": str(source.resolve()),
                "installed_dir": str(installed.resolve()),
                "modules": modules,
            }))
            source_audit = {"evaluator_activation_sha256": sha256(manifest)}

            self.assertEqual(
                audit_evaluator_activation(
                    manifest, source, installed, hashes, source_audit
                ),
                sha256(manifest),
            )
            modules["base.py"]["source_sha256"] = "stale"
            manifest.write_text(json.dumps({
                "status": "passed",
                "source_dir": str(source.resolve()),
                "installed_dir": str(installed.resolve()),
                "modules": modules,
            }))
            with self.assertRaisesRegex(ValueError, "stale evaluator"):
                audit_evaluator_activation(
                    manifest, source, installed, hashes,
                    {"evaluator_activation_sha256": sha256(manifest)},
                )

    def test_accepts_strict_separate_backend_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            path.write_text(json.dumps(strict_selection()))
            result = audit_strict_selection(
                path, EXPECTED_PROXY_COMPARISONS["contest_heldout"]
            )
        self.assertEqual(result["selected_methods"], ["plugin"])

    def test_rejects_positive_primary_worst_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            path.write_text(json.dumps(strict_selection(worst=0.01)))
            with self.assertRaisesRegex(ValueError, "regresses worst-case"):
                audit_strict_selection(path, 3)

    def test_accepts_rudy_only_worst_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            path.write_text(json.dumps(strict_selection(
                worst=0.01, worst_backend="rudy"
            )))
            result = audit_strict_selection(path, 3)
        self.assertEqual(result["selected_methods"], ["plugin"])

    def test_rejects_changed_worst_regression_backend_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            data = strict_selection()
            data["selection_policy"]["worst_regression_backends"] = ["rudy"]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "backend set changed"):
                audit_strict_selection(path, 3)

    def test_accepts_legacy_implicit_profile_worst_regression_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            data = strict_selection()
            del data["selection_policy"]["worst_regression_backends"]
            path.write_text(json.dumps(data))
            result = audit_strict_selection(path, 3)
        self.assertEqual(result["selected_methods"], ["plugin"])

    def test_rejects_two_improvement_gpugr_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            data = strict_selection()
            data["selection_policy"]["backend_improvement_constraints"][
                "gpugr"
            ]["minimum_improvements"] = 2
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "constraints changed"):
                audit_strict_selection(path, 3)

    def test_rejects_selected_metric_with_partial_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            data = strict_selection()
            data["qualified"][0]["metrics"]["gpugr:gr_wirelength"][
                "valid_count"
            ] = 2
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "full primary metric coverage"):
                audit_strict_selection(path, 3)

    def test_corrected_pipeline_rejects_legacy_metric_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            path.write_text(json.dumps(strict_selection()))
            with self.assertRaisesRegex(ValueError, "metric profile"):
                audit_strict_selection(
                    path, 3,
                    required_metric_profile="absolute_directional_v2",
                )

    def test_accepts_terminal_empty_strict_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            data = strict_selection()
            data["qualified"] = []
            data["pareto_frontier"] = []
            data["selected_methods"] = []
            path.write_text(json.dumps(data))
            result = audit_strict_selection(path, 3, allow_empty=True)
        self.assertEqual(result["selected_methods"], [])

    def test_proxy_chain_binds_exact_stage_admission_method_sets(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_proxy_chain(
                self.proxy_chain_fixture(Path(tmp))
            )
        self.assertEqual(result["final_methods"], ["hpwl", "plugin"])
        self.assertEqual(
            result["proxy_resolution_evidence"]["real_development"][
                "methods"
            ],
            ["hpwl", "plugin"],
        )

    def test_proxy_chain_accepts_explicit_integrated_real_terminal_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.proxy_chain_fixture(Path(tmp))
            args.real_status.write_text(
                "phase=completed_integrated_real_heldout_proxy_validation\n"
            )
            args.expected_real_phase = (
                "completed_integrated_real_heldout_proxy_validation"
            )
            result = audit_proxy_chain(args)
        self.assertEqual(result["final_methods"], ["hpwl", "plugin"])

    def test_proxy_chain_rejects_extra_real_development_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.proxy_chain_fixture(
                Path(tmp), extra_real_development=True
            )
            with self.assertRaisesRegex(
                ValueError, "outside contest admission"
            ):
                audit_proxy_chain(args)

    def test_proxy_chain_rejects_extra_real_heldout_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.proxy_chain_fixture(
                Path(tmp), extra_real_heldout=True
            )
            with self.assertRaisesRegex(
                ValueError, "outside development admission"
            ):
                audit_proxy_chain(args)

    def test_rejects_empty_selection_with_hidden_qualified_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            data = strict_selection()
            data["selected_methods"] = []
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "still contains qualified"):
                audit_strict_selection(path, 3, allow_empty=True)

    def test_no_candidate_audits_bind_both_golden_admission_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection_path = root / "selection.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            selection["qualified"] = []
            selection["pareto_frontier"] = []
            selection["selected_methods"] = []
            selection_path.write_text(json.dumps(selection))
            self.write_resolution_evidence(
                selection_path, selection, 3,
                EXPECTED_PROXY_RESOLUTIONS["contest_heldout"],
            )
            terminal_status = root / "real_status.md"
            terminal_status.write_text(
                "phase=completed_no_contest_survivor\n"
            )
            openroad_status = root / "openroad_status.md"
            openroad_status.write_text(
                "phase=completed_no_golden_candidate\n"
            )
            metric_manifest, metric_source, metric_install = (
                self.metric_profile_fixture(root / "metric_profile")
            )
            family_attestation = self.write_family_attestation(root)
            proxy = audit_no_candidate_proxy(SimpleNamespace(
                terminal_status=terminal_status,
                terminal_phase="completed_no_contest_survivor",
                empty_selection=["contest_heldout=3=%s" % selection_path],
                openroad_status=openroad_status,
                proxy_metric_profile_manifest=metric_manifest,
                development_family_attestation=family_attestation,
                proxy_source_root=metric_source,
                proxy_install_root=metric_install,
            ))
            proxy_path = root / "proxy.json"
            proxy_path.write_text(json.dumps(proxy))
            innovus_status = root / "innovus_status.md"
            innovus_status.write_text(
                "phase=completed_no_golden_candidate\n"
            )
            local_plugin_attestation = self.write_local_plugin_attestation(root)
            final = audit_no_candidate_final(SimpleNamespace(
                proxy_attestation=proxy_path,
                innovus_status=innovus_status,
                local_plugin_attestation=local_plugin_attestation,
            ))
        self.assertEqual(proxy["conclusion"], "no_safe_proxy_candidate")
        self.assertEqual(final["recommended_methods"], ["hpwl"])
        self.assertEqual(final["golden_admission"], "not_run_no_proxy_survivor")
        self.assertIn("local_plugin_attestation", final["sha256"])

    def test_integrated_atomic_exhaustion_requires_all_source_selections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = []
            for label in (
                "corrected_replay_development",
                "adaptive_v2_development",
                "missing_families_development",
                "missing_families_adaptive_v2_development",
            ):
                path = root / (label + ".json")
                selection = strict_selection(
                    metric_profile="absolute_directional_v2", expected=6
                )
                selection["qualified"] = []
                selection["pareto_frontier"] = []
                selection["selected_methods"] = []
                path.write_text(json.dumps(selection))
                self.write_resolution_evidence(
                    path, selection, 6,
                    EXPECTED_PROXY_RESOLUTIONS[label],
                    stage_label=label,
                )
                specs.append("%s=6=%s" % (label, path))
            terminal_status = root / "real_status.md"
            terminal_status.write_text(
                "phase=completed_no_integrated_contest_survivor\n"
            )
            openroad_status = root / "openroad_status.md"
            openroad_status.write_text(
                "phase=completed_no_golden_candidate\n"
            )
            metric_manifest, metric_source, metric_install = (
                self.metric_profile_fixture(root / "metric_profile")
            )
            family_attestation = self.write_family_attestation(root)
            args = SimpleNamespace(
                terminal_status=terminal_status,
                terminal_phase="completed_no_integrated_contest_survivor",
                empty_selection=specs,
                openroad_status=openroad_status,
                proxy_metric_profile_manifest=metric_manifest,
                development_family_attestation=family_attestation,
                proxy_source_root=metric_source,
                proxy_install_root=metric_install,
            )
            result = audit_no_candidate_proxy(args)
            args.empty_selection = specs[1:]
            with self.assertRaisesRegex(
                ValueError, "do not prove terminal phase"
            ):
                audit_no_candidate_proxy(args)

        self.assertEqual(
            result["terminal_empty_selections"],
            [
                "adaptive_v2_development",
                "corrected_replay_development",
                "missing_families_adaptive_v2_development",
                "missing_families_development",
            ],
        )

    def test_policy_v7_atomic_exhaustion_requires_both_new_selections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            labels = (
                "corrected_replay_development",
                "adaptive_v2_development",
                "missing_families_development",
                "missing_families_adaptive_v2_development",
                "missing_families_adaptive_v3_development",
                "corrected_net_weight_lifecycle_development",
            )
            specs = []
            for label in labels:
                path = root / (label + ".json")
                selection = strict_selection(
                    metric_profile="absolute_directional_v2", expected=6
                )
                selection["qualified"] = []
                selection["pareto_frontier"] = []
                selection["selected_methods"] = []
                path.write_text(json.dumps(selection))
                self.write_resolution_evidence(
                    path, selection, 6,
                    EXPECTED_PROXY_RESOLUTIONS[label],
                    stage_label=label,
                )
                specs.append("%s=6=%s" % (label, path))
            terminal_status = root / "real_status.md"
            terminal_status.write_text(
                "phase=completed_no_integrated_contest_survivor\n"
            )
            openroad_status = root / "openroad_status.md"
            openroad_status.write_text(
                "phase=completed_no_golden_candidate\n"
            )
            metric_manifest, metric_source, metric_install = (
                self.metric_profile_fixture(root / "metric_profile")
            )
            args = SimpleNamespace(
                terminal_status=terminal_status,
                terminal_phase="completed_no_integrated_contest_survivor",
                empty_selection=specs,
                openroad_status=openroad_status,
                proxy_metric_profile_manifest=metric_manifest,
                development_family_attestation=(
                    self.write_family_attestation(root)
                ),
                proxy_source_root=metric_source,
                proxy_install_root=metric_install,
                policy_v7_attestation=self.write_policy_v7_attestation(
                    root,
                    root / (
                        "corrected_net_weight_lifecycle_development.json"
                    ),
                ),
            )
            result = audit_no_candidate_proxy(args)
            args.empty_selection = specs[1:]
            with self.assertRaisesRegex(
                ValueError, "do not prove terminal phase"
            ):
                audit_no_candidate_proxy(args)

        self.assertEqual(
            result["terminal_empty_selections"], sorted(labels)
        )

    def test_proxy_resolution_evidence_accepts_complete_exact_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "survivors.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            path.write_text(json.dumps(selection))
            self.write_resolution_evidence(path, selection, 3, (256, 256))
            record = audit_proxy_resolution_evidence(
                path, selection, "contest_heldout", 3, (256, 256)
            )
        self.assertEqual(record["validated_comparisons"], 3)
        self.assertEqual(record["validated_results"], 12)
        self.assertEqual(len(record["comparison_slots"]), 3)

    def test_proxy_resolution_evidence_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "survivors.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            path.write_text(json.dumps(selection))
            self.write_resolution_evidence(
                path, selection, 3, (256, 256),
                mutate=lambda rows: rows[0].update(route_x_size=255),
            )
            with self.assertRaisesRegex(ValueError, "mismatched reported"):
                audit_proxy_resolution_evidence(
                    path, selection, "contest_heldout", 3, (256, 256)
                )

    def test_proxy_resolution_evidence_rejects_duplicate_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "survivors.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            path.write_text(json.dumps(selection))
            self.write_resolution_evidence(
                path, selection, 3, (256, 256),
                mutate=lambda rows: rows.append(dict(rows[0])),
            )
            with self.assertRaisesRegex(ValueError, "duplicate result slot"):
                audit_proxy_resolution_evidence(
                    path, selection, "contest_heldout", 3, (256, 256)
                )

    def test_proxy_resolution_evidence_rejects_missing_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "survivors.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            path.write_text(json.dumps(selection))
            self.write_resolution_evidence(
                path, selection, 3, (256, 256),
                missing_columns={"route_y_size"},
            )
            with self.assertRaisesRegex(ValueError, "reported resolution columns"):
                audit_proxy_resolution_evidence(
                    path, selection, "contest_heldout", 3, (256, 256)
                )

    def test_proxy_resolution_evidence_rejects_incomplete_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "survivors.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            path.write_text(json.dumps(selection))
            self.write_resolution_evidence(
                path, selection, 3, (256, 256),
                mutate=lambda rows: rows.pop(),
            )
            with self.assertRaisesRegex(ValueError, "comparison-slot matrix"):
                audit_proxy_resolution_evidence(
                    path, selection, "contest_heldout", 3, (256, 256)
                )

    def test_proxy_resolution_evidence_rejects_shifted_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "survivors.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            path.write_text(json.dumps(selection))

            def shift_slot(rows):
                rows[-1]["case"] = "different_case"
                rows[-1]["seed"] = 9999

            self.write_resolution_evidence(
                path, selection, 3, (256, 256), mutate=shift_slot
            )
            with self.assertRaisesRegex(ValueError, "comparison-slot matrix"):
                audit_proxy_resolution_evidence(
                    path, selection, "contest_heldout", 3, (256, 256)
                )

    def test_proxy_resolution_evidence_rejects_wrong_stage_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "survivors.json"
            selection = strict_selection(metric_profile="absolute_directional_v2")
            path.write_text(json.dumps(selection))

            def replace_heldout_case(rows):
                for row in rows:
                    row["case"] = "data_ispd19_test1"

            self.write_resolution_evidence(
                path, selection, 3, (256, 256), mutate=replace_heldout_case
            )
            with self.assertRaisesRegex(ValueError, "case-seed coverage"):
                audit_proxy_resolution_evidence(
                    path, selection, "contest_heldout", 3, (256, 256)
                )

    def test_proxy_resolution_record_rejects_inconsistent_result_count(self):
        records = {
            label: self.resolution_record(label)
            for label in EXPECTED_PROXY_COMPARISONS
        }
        hashes = {
            "proxy_resolution_raw:%s" % label: row["raw_sha256"]
            for label, row in records.items()
        }
        proxy = {
            "proxy_resolution_evidence": records,
            "sha256": hashes,
        }
        audit_proxy_resolution_record(proxy, EXPECTED_PROXY_COMPARISONS)
        records["real_heldout"]["validated_results"] -= 1
        with self.assertRaisesRegex(ValueError, "invalid proxy resolution"):
            audit_proxy_resolution_record(proxy, EXPECTED_PROXY_COMPARISONS)

    def test_proxy_resolution_record_rejects_wrong_stage_slot(self):
        records = {
            label: self.resolution_record(label)
            for label in EXPECTED_PROXY_COMPARISONS
        }
        hashes = {
            "proxy_resolution_raw:%s" % label: row["raw_sha256"]
            for label, row in records.items()
        }
        proxy = {"proxy_resolution_evidence": records, "sha256": hashes}
        records["real_heldout"]["comparison_slots"][0]["case"] = (
            "taiwei_nangate45_bp_quad_materialized2d"
        )
        with self.assertRaisesRegex(ValueError, "invalid proxy resolution"):
            audit_proxy_resolution_record(proxy, EXPECTED_PROXY_COMPARISONS)

    def test_no_candidate_final_rejects_missing_metric_profile_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proxy_path = root / "proxy.json"
            proxy_path.write_text(json.dumps({
                "status": "passed",
                "stage": "no_candidate_proxy",
                "final_methods": ["hpwl"],
            }))
            innovus_status = root / "innovus_status.md"
            innovus_status.write_text("phase=completed_no_golden_candidate\n")
            with self.assertRaisesRegex(ValueError, "metric-profile"):
                audit_no_candidate_final(SimpleNamespace(
                    proxy_attestation=proxy_path,
                    innovus_status=innovus_status,
                ))

    def test_result_slot_requires_exact_campaign_layout(self):
        root = Path("/campaign")
        good = root / "case/seed_1000/case/methods/plugin/evaluation/openroad.json"
        self.assertEqual(
            result_slot(root, good, "openroad.json"),
            ("case", 1000, "plugin"),
        )
        bad = root / "case/seed_1000/methods/plugin/evaluation/openroad.json"
        with self.assertRaisesRegex(ValueError, "layout"):
            result_slot(root, bad, "openroad.json")


if __name__ == "__main__":
    unittest.main()
