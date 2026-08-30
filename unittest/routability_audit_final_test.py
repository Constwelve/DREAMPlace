#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_audit_final import (
    EXPECTED_GOLDEN_CASES,
    EXPECTED_GOLDEN_METHODS,
    EXPECTED_PLUGIN_REGISTRY,
    EXPECTED_GOLDEN_SEEDS,
    PLUGIN_MODULES,
    audit_openroad_recovery,
    audit_regression_manifest,
    audit_result_matrix,
    canonical_json_sha256,
    main,
    objective_requirement_status,
    parse_plugin_registry,
    sha256,
)
from tools.routability_golden_replay import RESUME_REQUIRED_ARTIFACTS


def golden_metrics(backend):
    metrics = {
        "wirelength": 10.0,
        "vias": 1.0,
        "drc_violations": 0.0 if backend == "openroad" else 3.0,
        "unrouted_nets": 0.0,
        "short_violations": 0.0 if backend == "openroad" else 2.0,
    }
    if backend == "openroad":
        metrics.update({"horizontal_overflow": 0.0, "vertical_overflow": 0.0})
    else:
        metrics.update({
            "horizontal_congestion": 0.0,
            "vertical_congestion": 0.0,
            "connectivity_violations": 0.0,
            "open_violations": 0.0,
        })
    return metrics


def golden_artifacts(root, backend, compact=True):
    artifacts = {}
    for name in RESUME_REQUIRED_ARTIFACTS[backend]:
        path = root / ("%s_%s.rpt" % (backend, name))
        if backend == "openroad" and name == "metrics":
            path.write_text(json.dumps({
                "route__wirelength": 10.0,
                "route__vias": 1.0,
                "route__drc_errors": 0.0,
                "route__net": 1,
            }))
        elif backend == "openroad" and name == "log":
            path.write_text(
                "Number of nets: 1\n"
                "[INFO DRT-0199] Number of violations = 0.\n"
                "Viol/Layer Metal2\n"
                "[INFO DRT-0267] done\n"
            )
        elif backend == "openroad" and name == "congestion":
            path.write_text(
                "violation type: Horizontal congestion\n"
                "  comment: capacity:1 usage:1 overflow:0\n"
                "violation type: Vertical congestion\n"
                "  comment: capacity:1 usage:1 overflow:0\n"
            )
        elif backend == "openroad" and name == "script":
            path.write_text(
                "global_route -allow_congestion\n"
                "detailed_route -output_drc openroad_drc.rpt\n"
                "report_wire_length -detailed_route -summary\n"
            )
        elif backend == "innovus" and name == "log":
            path.write_text(
                "RLEVAL_ROUTED_WIRELENGTH 10\n"
                "Total number of vias = 1\n"
                "Overflow after Early Global Route 0.0% H + 0.0% V\n"
                "#Total number of routable nets = 1.\n"
                "#1 routable nets have routed wires.\n"
            )
        elif backend == "innovus" and name == "drc":
            path.write_text(
                "Total Violations : 3 Viols.\n"
                + (
                    "Total Short Violations : 2 Viols.\n"
                    if compact else "SHORT: first\nSHORT: second\n"
                )
            )
        elif backend == "innovus" and name == "connectivity":
            path.write_text("Begin Summary\n0 total info(s) created.\nEnd Summary\n")
        elif backend == "innovus" and name == "metrics":
            path.write_text("wirelength=10\nroute_mode=detailed\n")
        elif backend == "innovus" and name == "script":
            path.write_text("globalDetailRoute\n")
        else:
            path.write_text(name + "\n")
        artifacts[name] = str(path)
    return artifacts


def plugin_registry_source(registry=EXPECTED_PLUGIN_REGISTRY):
    lines = [
        "from .%s import %s" % (module, class_name)
        for _name, (module, class_name) in registry.items()
    ]
    lines.extend(["", "PLUGIN_REGISTRY = {"])
    lines.extend(
        '    "%s": %s,' % (name, class_name)
        for name, (_module, class_name) in registry.items()
    )
    lines.extend(["}", ""])
    return "\n".join(lines)


class RoutabilityAuditFinalTest(unittest.TestCase):
    def recovery_fixture(self, root):
        campaign = root / "campaign"
        recovery = root / "recovery"
        archive = root / "archive"
        target = campaign / "row/evaluation"
        source = recovery / "outputs/route_a"
        archived = archive / "route_a/evaluation"
        target.mkdir(parents=True)
        source.mkdir(parents=True)
        archived.mkdir(parents=True)
        provenance_input = recovery / "inputs/design.def"
        provenance_input.parent.mkdir(parents=True)
        provenance_input.write_text("frozen placement\n")

        result_path = target / "openroad.json"
        source_result = {
            "backend": "openroad",
            "design_name": "case_a",
            "status": "ok",
            "schema_version": 1,
            "metrics": {"wirelength": 80},
            "artifacts": {"log": str(source / "openroad.container.log")},
            "recovery_postprocess": {"source_status": "timeout"},
        }
        imported_result = dict(source_result)
        imported_result["artifacts"] = {"log": str(target / "openroad.container.log")}
        imported_result["recovery_provenance"] = {
            "route_name": "route_a",
            "quarantine_source": str(source.resolve()),
        }
        result_path.write_text(json.dumps(imported_result))
        (source / "openroad.json").write_text(json.dumps(source_result))
        timeout_result = {
            "status": "timeout",
            "error": "OpenROAD timeout after 21600 seconds",
        }
        (source / "openroad.timeout.json").write_text(json.dumps(timeout_result))
        (source / "summary.timeout.json").write_text(json.dumps({
            "results": [timeout_result],
        }))
        (source / "openroad.timeout.log").write_text("timeout log\n")
        (archived / "openroad.json").write_text(json.dumps({
            "status": "timeout",
            "error": "OpenROAD timeout after 21600 seconds",
        }))
        postprocess_path = root / "postprocess_report.json"
        postprocess_path.write_text(json.dumps({
            "schema_version": 1,
            "routes": [{
                "evaluation_dir": str(source.resolve()),
                "result": source_result,
            }],
        }))
        spec_path = root / "import_spec.json"
        spec = {
            "required_hashes": {"inputs/design.def": sha256(provenance_input)},
            "routes": [{
                "name": "route_a",
                "source_dir": "outputs/route_a",
                "target_dir": "row/evaluation",
            }],
        }
        spec_path.write_text(json.dumps(spec))
        archived_hash = sha256(archived / "openroad.json")
        report_path = root / "import_report.json"
        report = {
            "dry_run": False,
            "recovery_root": str(recovery.resolve()),
            "campaign_root": str(campaign.resolve()),
            "archive_root": str(archive.resolve()),
            "verified_hashes": spec["required_hashes"],
            "routes": [{
                "name": "route_a",
                "status": "imported",
                "target": str(target.resolve()),
                "archived_previous": str(archived.resolve()),
                "archived_previous_sha256": archived_hash,
            }],
        }
        report_path.write_text(json.dumps(report))
        return {
            "campaign": campaign,
            "recovery": recovery,
            "archive": archive,
            "result": result_path,
            "archived": archived / "openroad.json",
            "spec": spec_path,
            "report": report_path,
            "postprocess": postprocess_path,
            "provenance_input": provenance_input,
        }

    def test_openroad_recovery_without_recovered_rows_needs_no_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / "openroad.json"
            result.write_text(json.dumps({"status": "ok"}))
            audit = audit_openroad_recovery(root, [result])
        self.assertEqual(audit, {"used": False, "route_names": [], "sha256": {}})

    def test_openroad_recovery_requires_final_audit_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.recovery_fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "lacks final audit evidence"):
                audit_openroad_recovery(
                    fixture["campaign"], [fixture["result"]]
                )

    def test_openroad_recovery_accepts_applied_hash_bound_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.recovery_fixture(Path(tmp))
            audit = audit_openroad_recovery(
                fixture["campaign"], [fixture["result"]], fixture["spec"],
                fixture["report"], fixture["archive"],
                fixture["postprocess"],
            )
        self.assertTrue(audit["used"])
        self.assertEqual(audit["route_names"], ["route_a"])
        self.assertEqual(len(audit["archived_timeout_sha256"]["route_a"]), 64)
        self.assertEqual(
            set(audit["sha256"]),
            {"import_spec", "import_report", "postprocess_report"},
        )

    def test_openroad_recovery_rejects_tampered_evidence(self):
        mutations = {
            "hash manifest": (
                "report", lambda data: data["verified_hashes"].update(
                    {"inputs/design.def": "b" * 64}
                ), "hash manifest mismatch",
            ),
            "route coverage": (
                "report", lambda data: data["routes"].append({
                    "name": "unexpected", "status": "already_valid_identical",
                }), "route coverage mismatch",
            ),
            "target": (
                "spec", lambda data: data["routes"][0].update(
                    {"target_dir": "wrong/evaluation"}
                ), "target mismatch",
            ),
            "reported target": (
                "report", lambda data: data["routes"][0].update(
                    {"target": "/tampered/target"}
                ), "report target mismatch",
            ),
            "source": (
                "result", lambda data: data["recovery_provenance"].update(
                    {"quarantine_source": "/tampered/source"}
                ), "quarantine source mismatch",
            ),
            "archived timeout": (
                "archived", lambda data: data.update(
                    {"status": "ok", "error": ""}
                ), "archive hash mismatch",
            ),
            "postprocess report": (
                "postprocess", lambda data: data["routes"][0]["result"][
                    "metrics"
                ].update({"wirelength": 81}), "postprocess report/result mismatch",
            ),
        }
        for name, (key, mutate, message) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                fixture = self.recovery_fixture(Path(tmp))
                path = fixture[key]
                data = json.loads(path.read_text())
                mutate(data)
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, message):
                    audit_openroad_recovery(
                        fixture["campaign"], [fixture["result"]],
                        fixture["spec"], fixture["report"], fixture["archive"],
                        fixture["postprocess"],
                    )

    def test_openroad_recovery_requires_all_preserved_timeout_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.recovery_fixture(Path(tmp))
            source = fixture["recovery"] / "outputs/route_a"
            (source / "openroad.timeout.log").unlink()
            with self.assertRaisesRegex(ValueError, "missing preserved"):
                audit_openroad_recovery(
                    fixture["campaign"], [fixture["result"]], fixture["spec"],
                    fixture["report"], fixture["archive"],
                    fixture["postprocess"],
                )

    def test_openroad_recovery_rejects_tampered_fetched_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.recovery_fixture(Path(tmp))
            fixture["provenance_input"].write_text("changed placement\n")
            with self.assertRaisesRegex(ValueError, "provenance hash mismatch"):
                audit_openroad_recovery(
                    fixture["campaign"], [fixture["result"]], fixture["spec"],
                    fixture["report"], fixture["archive"],
                    fixture["postprocess"],
                )

    def test_production_result_matrix_rejects_duplicate_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / case / ("seed_%d" % seed) / case / "methods" / method
                / "evaluation" / "openroad.json"
                for case in EXPECTED_GOLDEN_CASES["openroad"]
                for seed in EXPECTED_GOLDEN_SEEDS
                for method in EXPECTED_GOLDEN_METHODS
            ]
            audit_result_matrix(root, paths, "openroad", "openroad.json")
            paths[-1] = paths[0]
            with self.assertRaisesRegex(ValueError, "matrix coverage mismatch"):
                audit_result_matrix(root, paths, "openroad", "openroad.json")

    def fixture(self, root, compact=True, recommendation=True,
                backend_mixing=False, triple_overlap=False,
                triple_incomplete=False, triple_method_mismatch=False):
        openroad = root / "openroad"
        innovus = root / "innovus"
        (openroad / "row").mkdir(parents=True)
        (innovus / "row").mkdir(parents=True)
        openroad_artifacts = golden_artifacts(openroad / "row", "openroad")
        innovus_artifacts = golden_artifacts(
            innovus / "row", "innovus", compact=compact
        )
        (openroad / "row/openroad.json").write_text(json.dumps({
            "backend": "openroad",
            "status": "ok",
            "metrics": golden_metrics("openroad"),
            "artifacts": openroad_artifacts,
        }))
        (innovus / "row/innovus.json").write_text(json.dumps({
            "backend": "innovus",
            "status": "ok",
            "metrics": golden_metrics("innovus"),
            "artifacts": innovus_artifacts,
        }))
        artifacts = {}
        summaries = {}
        for backend in ("openroad", "innovus"):
            data = {
                "expected_comparisons": 1,
                "validated_comparisons": 1,
                "incomplete_jobs": [],
                "missing_comparisons": [],
                "excluded": [],
                "baseline_gaps": [],
                "plugin_activation_contract": "validated",
                "rows": [{"backend": backend}],
            }
            path = root / (backend + "_summary.json")
            path.write_text(json.dumps(data))
            artifacts[backend + "_summary"] = path
            summaries[backend] = data
        report = root / "report.txt"
        report.write_text("report\n")
        artifacts["report"] = report
        regression_log = root / "regression_log.txt"
        regression_log.write_text("\n".join(
            "Ran 1 test in 0.001s\n\nOK" for _index in range(4)
        ) + "\n")
        artifacts["regression_log"] = regression_log
        regression_manifest = root / "regression_manifest.json"
        regression_manifest.write_text(json.dumps({
            "schema_version": 1,
            "suites": [
                {"name": name, "tests": 1} for name in (
                    "routability", "def_distribution", "ruplace_unit",
                    "ruplace_quality",
                )
            ],
            "total_tests": 4,
            "all_passed": True,
            "python_compilation_passed": True,
            "git_diff_check_passed": True,
            "regression_log_sha256": sha256(regression_log),
        }))
        artifacts["regression_manifest"] = regression_manifest
        source_evaluators = root / "source_evaluators"
        installed_evaluators = root / "installed_evaluators"
        source_evaluators.mkdir()
        installed_evaluators.mkdir()
        for name in ("base.py", "innovus.py", "openroad.py"):
            content = "# %s\n" % name
            (source_evaluators / name).write_text(content)
            (installed_evaluators / name).write_text(content)
        artifacts["source_evaluators"] = source_evaluators
        artifacts["installed_evaluators"] = installed_evaluators
        source_plugins = root / "source_plugins"
        installed_plugins = root / "installed_plugins"
        source_plugins.mkdir()
        installed_plugins.mkdir()
        for name in PLUGIN_MODULES:
            content = (
                plugin_registry_source() if name == "__init__.py"
                else "# %s\n" % name
            )
            (source_plugins / name).write_text(content)
            (installed_plugins / name).write_text(content)
        artifacts["source_plugins"] = source_plugins
        artifacts["installed_plugins"] = installed_plugins
        source_params = root / "source_params.json"
        installed_params = root / "installed_params.json"
        source_params.write_text('{"ruplace_plugins": []}\n')
        installed_params.write_text(source_params.read_text())
        artifacts["source_params"] = source_params
        artifacts["installed_params"] = installed_params
        ranking = root / "ranking.json"
        ranking.write_text(json.dumps({
            "baseline": "hpwl",
            "policy": {
                "name": "golden_routability_lexicographic_pareto",
                "numeric_backend_mixing": backend_mixing,
                "numeric_metric_scalarization": False,
                "objective_comparison_tolerance": 1e-12,
                "primary_metrics": [
                    "drc_violations", "horizontal congestion or overflow",
                    "vertical congestion or overflow", "unrouted_nets",
                    "short_violations", "Innovus connectivity_violations",
                    "Innovus open_violations", "routed wirelength",
                ],
                "secondary_metrics": ["vias"],
                "diagnostic_metrics": ["placement_hpwl"],
                "diagnostic_metrics_affect_decision": False,
                "secondary_cost_guardrails": {
                    "max_mean_regression_pct": 5.0,
                    "max_worst_regression_pct": 10.0,
                    "zero_baseline_absolute_increase_allowed": False,
                },
            },
            "campaigns": [
                {
                    "backend": backend,
                    "cases": sorted(EXPECTED_GOLDEN_CASES[backend]),
                    "case_seeds": [
                        {"case": case, "seed": seed}
                        for case in sorted(EXPECTED_GOLDEN_CASES[backend])
                        for seed in EXPECTED_GOLDEN_SEEDS
                    ],
                    "summary_content_sha256": canonical_json_sha256(data),
                    "diagnostic_metrics": ["placement_hpwl"],
                    "candidates": [
                        {
                            "method": method,
                            "diagnostic_metrics": {
                                "placement_hpwl": {"mean_delta": 0.0}
                            },
                            "objectives": {},
                        }
                        for method in EXPECTED_GOLDEN_METHODS
                    ],
                }
                for backend, data in summaries.items()
            ],
            "common_methods": sorted(EXPECTED_GOLDEN_METHODS),
            "bounded_cost_routability_winners": [],
            "recommended_methods": ["hpwl"] if recommendation else [],
        }))
        artifacts["ranking"] = ranking
        triple_method = (
            "survivor_triple_0001_rudy_net_weighting__net_overlap__local_gradient"
        )
        for split, selected in (
            ("development", [triple_method] if triple_overlap else []),
            ("heldout", [triple_method]),
        ):
            path = root / ("triple_%s.json" % split)
            path.write_text(json.dumps({
                "expected_comparisons": 1,
                "selected_methods": selected,
                "qualified": [{"method": method} for method in selected],
                "excluded": (
                    [] if selected else [{
                        "method": (
                            "different_triple" if triple_method_mismatch
                            and split == "development" else triple_method
                        )
                    }]
                ),
                "selection_policy": {"numeric_backend_mixing": False},
            }))
            artifacts["triple_" + split] = path
            status = root / ("triple_%s_status.csv" % split)
            status.write_text(
                "job_id,status,returncode\n"
                "job_1,%s,%s\n" % (
                    "running" if triple_incomplete and split == "development"
                    else "completed",
                    "" if triple_incomplete and split == "development" else "0",
                )
            )
            artifacts["triple_" + split + "_status"] = status
        return openroad, innovus, artifacts

    def run_fixture(self, root, compact=True, recommendation=True,
                    backend_mixing=False, triple_overlap=False,
                    triple_incomplete=False, triple_method_mismatch=False):
        openroad, innovus, artifacts = self.fixture(
            root, compact=compact, recommendation=recommendation,
            backend_mixing=backend_mixing, triple_overlap=triple_overlap,
            triple_incomplete=triple_incomplete,
            triple_method_mismatch=triple_method_mismatch,
        )
        output = root / "audit.json"
        argv = [
            "--openroad-campaign", str(openroad),
            "--innovus-campaign", str(innovus),
            "--openroad-summary", str(artifacts["openroad_summary"]),
            "--innovus-summary", str(artifacts["innovus_summary"]),
            "--ranking", str(artifacts["ranking"]),
            "--report", str(artifacts["report"]),
            "--regression-log", str(artifacts["regression_log"]),
            "--regression-manifest", str(artifacts["regression_manifest"]),
            "--triple-development-summary",
            str(artifacts["triple_development"]),
            "--triple-heldout-summary", str(artifacts["triple_heldout"]),
            "--triple-development-status",
            str(artifacts["triple_development_status"]),
            "--triple-heldout-status", str(artifacts["triple_heldout_status"]),
            "--output", str(output),
            "--source-evaluator-dir", str(artifacts["source_evaluators"]),
            "--installed-evaluator-dir", str(artifacts["installed_evaluators"]),
            "--source-plugin-dir", str(artifacts["source_plugins"]),
            "--installed-plugin-dir", str(artifacts["installed_plugins"]),
            "--source-params", str(artifacts["source_params"]),
            "--installed-params", str(artifacts["installed_params"]),
            "--require-openroad-results", "1",
            "--require-innovus-results", "1",
            "--require-triple-development-results", "1",
            "--require-triple-heldout-results", "1",
            "--require-triple-methods", "1",
            "--minimum-regression-tests", "4",
            "--require-compact-innovus",
        ]
        return main(argv), output

    def test_writes_hash_bound_exact_matrix_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = self.run_fixture(Path(tmp))
            data = json.loads(output.read_text())
        self.assertEqual(status, 0)
        self.assertEqual(data["openroad_ok_results"], 1)
        self.assertEqual(data["innovus_ok_results"], 1)
        self.assertEqual(data["routed_metric_contract"], "validated")
        self.assertEqual(set(data["evaluator_sha256"]), {
            "base.py", "innovus.py", "openroad.py",
        })
        self.assertEqual(set(data["plugin_sha256"]), set(PLUGIN_MODULES))
        self.assertEqual(
            set(data["plugin_registry"]), set(EXPECTED_PLUGIN_REGISTRY)
        )
        self.assertTrue(data["source_install_plugins_match"])
        self.assertTrue(data["source_install_params_match"])
        self.assertEqual(len(data["params_sha256"]), 64)
        self.assertEqual(data["compact_innovus_drc_reports"], 1)
        self.assertEqual(data["recommended_methods"], ["hpwl"])
        self.assertEqual(data["triple_search_common_survivors"], [])
        self.assertEqual(data["triple_search_completed_jobs"], {
            "development": 1, "heldout": 1,
        })
        self.assertEqual(set(data["triple_summary_content_sha256"]), {
            "development", "heldout",
        })
        self.assertEqual(
            data["ranking_policy"], "golden_routability_lexicographic_pareto"
        )
        self.assertEqual(
            data["objective_requirements"]["golden_metric_and_artifact_contract"],
            "validated",
        )
        self.assertEqual(
            data["objective_requirements"]["contest_openroad_matrix"],
            "not_required",
        )
        self.assertEqual(set(data["objective_requirements"]), {
            "golden_metric_and_artifact_contract",
            "contest_openroad_matrix",
            "real_design_innovus_matrix",
            "backend_local_pareto_recomputation",
            "human_ranking_report_binding",
            "bounded_combination_search",
            "evaluator_source_install_identity",
            "plugin_registry_and_source_install_identity",
            "parameter_schema_source_install_identity",
            "regression_and_source_integrity",
        })
        self.assertEqual(len(data["sha256"]["ranking_json"]), 64)

    def test_objective_requirement_status_distinguishes_production_mode(self):
        generic = objective_requirement_status(False)
        production = objective_requirement_status(True)

        production_only = {
            "contest_openroad_matrix",
            "real_design_innovus_matrix",
            "backend_local_pareto_recomputation",
            "human_ranking_report_binding",
        }
        self.assertTrue(all(
            generic[name] == "not_required" for name in production_only
        ))
        self.assertTrue(all(
            production[name] == "validated" for name in production_only
        ))
        self.assertTrue(all(
            status == "validated"
            for name, status in generic.items() if name not in production_only
        ))

    def test_regression_manifest_reparses_suite_counts_and_log_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            _openroad, _innovus, artifacts = self.fixture(Path(tmp))
            suites, total = audit_regression_manifest(
                artifacts["regression_manifest"], artifacts["regression_log"], 4
            )
            self.assertEqual(total, 4)
            self.assertEqual(suites, {
                "routability": 1,
                "def_distribution": 1,
                "ruplace_unit": 1,
                "ruplace_quality": 1,
            })

            artifacts["regression_log"].write_text(
                artifacts["regression_log"].read_text() + "tampered\n"
            )
            with self.assertRaisesRegex(ValueError, "log hash mismatch"):
                audit_regression_manifest(
                    artifacts["regression_manifest"],
                    artifacts["regression_log"], 4,
                )

    def test_regression_manifest_rejects_false_pass_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            _openroad, _innovus, artifacts = self.fixture(Path(tmp))
            manifest = json.loads(artifacts["regression_manifest"].read_text())
            manifest["git_diff_check_passed"] = False
            artifacts["regression_manifest"].write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "every gate passed"):
                audit_regression_manifest(
                    artifacts["regression_manifest"],
                    artifacts["regression_log"], 4,
                )

    def test_rejects_missing_compact_innovus_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "no post-install compact"):
                self.run_fixture(Path(tmp), compact=False)

    def test_rejects_status_ok_result_without_routed_wirelength(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            openroad, _innovus, _artifacts = self.fixture(root)
            result_path = openroad / "row/openroad.json"
            result = json.loads(result_path.read_text())
            result["metrics"].pop("wirelength")
            result_path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "routed metric contract"):
                self.run_fixture_from_existing(root)

    def test_rejects_source_install_evaluator_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            (artifacts["installed_evaluators"] / "innovus.py").write_text(
                "# changed\n"
            )
            with self.assertRaisesRegex(ValueError, "evaluator mismatch"):
                self.run_fixture_from_existing(root)

    def test_rejects_source_install_plugin_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            (artifacts["installed_plugins"] / "utils.py").write_text(
                "# changed\n"
            )
            with self.assertRaisesRegex(ValueError, "plugin mismatch"):
                self.run_fixture_from_existing(root)

    def test_rejects_source_install_parameter_schema_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            artifacts["installed_params"].write_text('{"changed": true}\n')
            with self.assertRaisesRegex(ValueError, "parameter schema mismatch"):
                self.run_fixture_from_existing(root)

    def test_live_plugin_registry_matches_production_identity_contract(self):
        registry = parse_plugin_registry(
            ROOT / "dreamplace/ops/routability_opt/plugins/__init__.py"
        )

        self.assertEqual(registry, EXPECTED_PLUGIN_REGISTRY)
        self.assertEqual(
            set(PLUGIN_MODULES),
            {"__init__.py", "utils.py"}
            | {"%s.py" % module for module, _class_name in registry.values()},
        )

    def test_rejects_plugin_registry_set_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            incomplete = dict(list(EXPECTED_PLUGIN_REGISTRY.items())[:-1])
            content = plugin_registry_source(incomplete)
            for key in ("source_plugins", "installed_plugins"):
                (artifacts[key] / "__init__.py").write_text(content)
            with self.assertRaisesRegex(ValueError, "registry name/class/import set"):
                self.run_fixture_from_existing(root)

    def run_fixture_from_existing(self, root):
        output = root / "audit.json"
        return main([
            "--openroad-campaign", str(root / "openroad"),
            "--innovus-campaign", str(root / "innovus"),
            "--openroad-summary", str(root / "openroad_summary.json"),
            "--innovus-summary", str(root / "innovus_summary.json"),
            "--ranking", str(root / "ranking.json"),
            "--report", str(root / "report.txt"),
            "--regression-log", str(root / "regression_log.txt"),
            "--regression-manifest", str(root / "regression_manifest.json"),
            "--triple-development-summary", str(root / "triple_development.json"),
            "--triple-heldout-summary", str(root / "triple_heldout.json"),
            "--triple-development-status",
            str(root / "triple_development_status.csv"),
            "--triple-heldout-status", str(root / "triple_heldout_status.csv"),
            "--output", str(output),
            "--source-evaluator-dir", str(root / "source_evaluators"),
            "--installed-evaluator-dir", str(root / "installed_evaluators"),
            "--source-plugin-dir", str(root / "source_plugins"),
            "--installed-plugin-dir", str(root / "installed_plugins"),
            "--source-params", str(root / "source_params.json"),
            "--installed-params", str(root / "installed_params.json"),
            "--require-openroad-results", "1",
            "--require-innovus-results", "1",
            "--require-triple-development-results", "1",
            "--require-triple-heldout-results", "1",
            "--require-triple-methods", "1",
            "--minimum-regression-tests", "4",
            "--require-compact-innovus",
        ])

    def test_rejects_empty_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "bounded policy winners"):
                self.run_fixture(Path(tmp), recommendation=False)

    def test_rejects_numeric_backend_mixing_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "backend mixing"):
                self.run_fixture(Path(tmp), backend_mixing=True)

    def test_rejects_routed_wirelength_as_secondary_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            ranking = json.loads(artifacts["ranking"].read_text())
            ranking["policy"]["primary_metrics"].remove("routed wirelength")
            ranking["policy"]["secondary_metrics"].append("routed wirelength")
            artifacts["ranking"].write_text(json.dumps(ranking))
            with self.assertRaisesRegex(ValueError, "primary metric policy"):
                self.run_fixture_from_existing(root)

    def test_rejects_missing_innovus_open_primary_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            ranking = json.loads(artifacts["ranking"].read_text())
            ranking["policy"]["primary_metrics"].remove(
                "Innovus open_violations"
            )
            artifacts["ranking"].write_text(json.dumps(ranking))
            with self.assertRaisesRegex(ValueError, "primary metric policy"):
                self.run_fixture_from_existing(root)

    def test_rejects_wrong_golden_case_seed_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            ranking = json.loads(artifacts["ranking"].read_text())
            campaign = next(
                row for row in ranking["campaigns"]
                if row["backend"] == "openroad"
            )
            campaign["case_seeds"][-1]["seed"] = 4000
            artifacts["ranking"].write_text(json.dumps(ranking))
            with self.assertRaisesRegex(ValueError, "seed coverage mismatch"):
                self.run_fixture_from_existing(root)

    def test_rejects_wrong_finalist_method_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _openroad, _innovus, artifacts = self.fixture(root)
            ranking = json.loads(artifacts["ranking"].read_text())
            ranking["common_methods"][-1] = "unfrozen_replacement"
            artifacts["ranking"].write_text(json.dumps(ranking))
            with self.assertRaisesRegex(ValueError, "finalist method coverage"):
                self.run_fixture_from_existing(root)

    def test_rejects_triple_survivor_requiring_golden_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "golden-replay candidates"):
                self.run_fixture(Path(tmp), triple_overlap=True)

    def test_rejects_incomplete_triple_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "incomplete jobs"):
                self.run_fixture(Path(tmp), triple_incomplete=True)

    def test_rejects_mismatched_triple_method_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "method sets do not match"):
                self.run_fixture(Path(tmp), triple_method_mismatch=True)

    def test_rejects_tampered_summary_after_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            openroad, innovus, artifacts = self.fixture(root)
            summary = json.loads(artifacts["openroad_summary"].read_text())
            summary["tampered"] = True
            artifacts["openroad_summary"].write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "summary hash mismatch"):
                main([
                    "--openroad-campaign", str(openroad),
                    "--innovus-campaign", str(innovus),
                    "--openroad-summary", str(artifacts["openroad_summary"]),
                    "--innovus-summary", str(artifacts["innovus_summary"]),
                    "--ranking", str(artifacts["ranking"]),
                    "--report", str(artifacts["report"]),
                    "--regression-log", str(artifacts["regression_log"]),
                    "--regression-manifest",
                    str(artifacts["regression_manifest"]),
                    "--triple-development-summary",
                    str(artifacts["triple_development"]),
                    "--triple-heldout-summary",
                    str(artifacts["triple_heldout"]),
                    "--triple-development-status",
                    str(artifacts["triple_development_status"]),
                    "--triple-heldout-status",
                    str(artifacts["triple_heldout_status"]),
                    "--output", str(root / "audit.json"),
                    "--source-evaluator-dir", str(artifacts["source_evaluators"]),
                    "--installed-evaluator-dir",
                    str(artifacts["installed_evaluators"]),
                    "--source-plugin-dir", str(artifacts["source_plugins"]),
                    "--installed-plugin-dir", str(artifacts["installed_plugins"]),
                    "--source-params", str(artifacts["source_params"]),
                    "--installed-params", str(artifacts["installed_params"]),
                    "--require-openroad-results", "1",
                    "--require-innovus-results", "1",
                    "--require-triple-development-results", "1",
                    "--require-triple-heldout-results", "1",
                    "--require-triple-methods", "1",
                    "--minimum-regression-tests", "4",
                    "--require-compact-innovus",
                ])


if __name__ == "__main__":
    unittest.main()
