#!/usr/bin/env python3
"""Audit exact golden matrices and bind final routability outputs by SHA-256."""

import argparse
import ast
import csv
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_golden_replay import result_meets_resume_contract
from tools.routability_import_openroad_recovery import verify_hashes
from tools.routability_rank_golden import (
    OBJECTIVE_TOLERANCE, rank_campaigns, render_report,
)


EVALUATOR_MODULES = ("base.py", "innovus.py", "openroad.py")
EXPECTED_PLUGIN_REGISTRY = {
    "connection_routeforce": (
        "connection_routeforce", "ConnectionRouteForcePlugin",
    ),
    "multisegment_connection_routeforce": (
        "multisegment_connection_routeforce",
        "MultiSegmentConnectionRouteForcePlugin",
    ),
    "projected_connection_routeforce": (
        "projected_connection_routeforce", "ProjectedConnectionRouteForcePlugin",
    ),
    "directional_cvar_gradient": (
        "directional_cvar_gradient", "DirectionalCVaRGradientPlugin",
    ),
    "directional_excess_cvar_gradient": (
        "directional_excess_cvar_gradient",
        "DirectionalExcessCVaRGradientPlugin",
    ),
    "directional_net_contraction": (
        "directional_net_contraction", "DirectionalNetContractionPlugin",
    ),
    "directional_local_gradient": (
        "directional_local_gradient", "DirectionalLocalCongestionGradientPlugin",
    ),
    "directional_path_spreading": (
        "directional_path_spreading", "DirectionalPathSpreadingPlugin",
    ),
    "directional_virtual_cell": (
        "directional_virtual_cell", "DirectionalVirtualCellNetMovingPlugin",
    ),
    "route_inflation": ("route_inflation", "RouteInflationPlugin"),
    "momentum_inflation": ("momentum_inflation", "MomentumInflationPlugin"),
    "path_inflation": ("path_inflation", "RoutingPathInflationPlugin"),
    "local_gradient": ("local_gradient", "LocalCongestionGradientPlugin"),
    "poisson_force": ("poisson_force", "PoissonCongestionForcePlugin"),
    "net_weighting": ("net_weighting", "CongestionNetWeightingPlugin"),
    "net_relaxation": ("net_relaxation", "CongestionNetRelaxationPlugin"),
    "net_overlap": ("net_overlap", "NetOverlapRemovalPlugin"),
    "pin_porosity": ("pin_porosity", "PinDensityPorosityPlugin"),
    "whitespace": ("whitespace", "WhitespaceAllocationPlugin"),
    "routeforce": ("routeforce", "RouteForcePlugin"),
    "routed_overflow_net_contraction": (
        "routed_overflow_net_contraction", "RoutedOverflowNetContractionPlugin",
    ),
    "virtual_cell": ("virtual_cell", "VirtualCellNetMovingPlugin"),
}
PLUGIN_MODULES = (
    "__init__.py",
    *("%s.py" % module for module, _class_name in EXPECTED_PLUGIN_REGISTRY.values()),
    "utils.py",
)
EXPECTED_GOLDEN_CASES = {
    "openroad": (
        "data_ispd19_test1", "data_ispd19_test2", "data_ispd19_test3",
    ),
    "innovus": (
        "taiwei_nangate45_bp_quad_materialized2d",
        "taiwei_nangate45_mempool_group_materialized2d",
        "taiwei_nangate45_nvdla_l_materialized2d",
        "taiwei_nangate45_openc910_materialized2d",
        "taiwei_nangate45_xscore_materialized2d",
    ),
}
EXPECTED_GOLDEN_SEEDS = (1000, 2000, 3000)
EXPECTED_GOLDEN_METHODS = (
    "hpwl",
    "survivor_pair_0003_rudy_net_weighting__local_gradient",
    "weak_atomic_dev_0002_rudy_local_gradient",
    "weak_atomic_dev_0006_rudy_net_overlap",
    "weak_atomic_dev_0013_rudy_net_weighting",
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_json_sha256(data):
    payload = json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def contract_results(root, name, backend):
    paths = sorted(Path(root).glob("**/%s" % name))
    valid = []
    invalid = []
    for path in paths:
        result = json.loads(path.read_text())
        if result_meets_resume_contract(
            {**result, "authoritative_for_comparison": True}, backend
        ):
            valid.append(path)
        else:
            invalid.append(path)
    return paths, valid, invalid


def compact_innovus_reports(root):
    compact = []
    for path in Path(root).glob("**/innovus_drc.rpt"):
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 4096))
            tail = stream.read()
        if b"Total Short Violations" in tail:
            compact.append(path)
    return sorted(compact)


def audit_result_matrix(root, paths, backend, result_name):
    """Require one routed result for every frozen case/seed/method slot."""
    actual = []
    for path in paths:
        try:
            parts = Path(path).relative_to(root).parts
        except ValueError:
            raise ValueError("%s result is outside its campaign" % backend)
        if (
            len(parts) != 7
            or not parts[1].startswith("seed_")
            or parts[2] != parts[0]
            or parts[3] != "methods"
            or parts[5] != "evaluation"
            or parts[6] != result_name
        ):
            raise ValueError("%s result path does not match matrix layout" % backend)
        try:
            seed = int(parts[1][5:])
        except ValueError:
            raise ValueError("%s result path has invalid seed" % backend)
        actual.append((parts[0], seed, parts[4]))
    expected = {
        (case, seed, method)
        for case in EXPECTED_GOLDEN_CASES[backend]
        for seed in EXPECTED_GOLDEN_SEEDS
        for method in EXPECTED_GOLDEN_METHODS
    }
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("%s routed result matrix coverage mismatch" % backend)


def audit_evaluator_identity(source_dir, installed_dir):
    hashes = {}
    for name in EVALUATOR_MODULES:
        source = Path(source_dir) / name
        installed = Path(installed_dir) / name
        if not source.is_file() or not installed.is_file():
            raise ValueError("missing source or installed evaluator module: %s" % name)
        source_hash = sha256(source)
        installed_hash = sha256(installed)
        if source_hash != installed_hash:
            raise ValueError("source/install evaluator mismatch: %s" % name)
        hashes[name] = source_hash
    return hashes


def parse_plugin_registry(path):
    """Statically verify the exact plugin names, classes, and relative imports."""
    path = Path(path)
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (OSError, SyntaxError) as error:
        raise ValueError("cannot parse plugin registry: %s" % error)

    imports = {}
    registries = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = (node.module, alias.name)
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PLUGIN_REGISTRY"
            for target in node.targets
        ):
            registries.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PLUGIN_REGISTRY"
        ):
            registries.append(node.value)

    if len(registries) != 1 or not isinstance(registries[0], ast.Dict):
        raise ValueError("plugin registry must be one static dictionary")
    registry = {}
    for key_node, value_node in zip(registries[0].keys, registries[0].values):
        if (
            not isinstance(key_node, ast.Constant)
            or not isinstance(key_node.value, str)
            or not isinstance(value_node, ast.Name)
        ):
            raise ValueError("plugin registry must contain literal name/class entries")
        if key_node.value in registry:
            raise ValueError("plugin registry contains duplicate names")
        registry[key_node.value] = imports.get(value_node.id)

    if registry != EXPECTED_PLUGIN_REGISTRY:
        raise ValueError("plugin registry name/class/import set mismatch")
    return registry


def audit_plugin_identity(source_dir, installed_dir):
    hashes = {}
    for name in PLUGIN_MODULES:
        source = Path(source_dir) / name
        installed = Path(installed_dir) / name
        if not source.is_file() or not installed.is_file():
            raise ValueError("missing source or installed plugin module: %s" % name)
        source_hash = sha256(source)
        installed_hash = sha256(installed)
        if source_hash != installed_hash:
            raise ValueError("source/install plugin mismatch: %s" % name)
        hashes[name] = source_hash
    parse_plugin_registry(Path(source_dir) / "__init__.py")
    parse_plugin_registry(Path(installed_dir) / "__init__.py")
    return hashes


def audit_params_identity(source_path, installed_path):
    source = Path(source_path)
    installed = Path(installed_path)
    if not source.is_file() or not installed.is_file():
        raise ValueError("missing source or installed parameter schema")
    source_hash = sha256(source)
    installed_hash = sha256(installed)
    if source_hash != installed_hash:
        raise ValueError("source/install parameter schema mismatch")
    return source_hash


def audit_parallel_status(path, expected_jobs, split):
    with Path(path).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != expected_jobs:
        raise ValueError(
            "%s triple status has %d jobs, expected %d" % (
                split, len(rows), expected_jobs
            )
        )
    job_ids = [row.get("job_id") for row in rows]
    if any(not job_id for job_id in job_ids) or len(set(job_ids)) != len(job_ids):
        raise ValueError("%s triple status has invalid job ids" % split)
    incomplete = [
        row.get("job_id") for row in rows
        if row.get("status") != "completed" or row.get("returncode") != "0"
    ]
    if incomplete:
        raise ValueError(
            "%s triple status has incomplete jobs: %s" % (
                split, ", ".join(incomplete)
            )
        )
    return rows


def audit_triple_search(
        development_path, heldout_path, development_status_path,
        heldout_status_path, development_expected, heldout_expected,
        expected_methods):
    summaries = {
        "development": json.loads(Path(development_path).read_text()),
        "heldout": json.loads(Path(heldout_path).read_text()),
    }
    expected_by_split = {
        "development": development_expected,
        "heldout": heldout_expected,
    }
    status_paths = {
        "development": development_status_path,
        "heldout": heldout_status_path,
    }
    selected = {}
    covered = {}
    status_rows = {}
    for split, summary in summaries.items():
        methods = summary.get("selected_methods")
        if not isinstance(methods, list) or any(
            not isinstance(method, str) or not method for method in methods
        ):
            raise ValueError("%s triple summary lacks selected_methods" % split)
        if len(set(methods)) != len(methods):
            raise ValueError("%s triple summary has duplicate selected methods" % split)
        qualified = summary.get("qualified")
        excluded = summary.get("excluded")
        if not isinstance(qualified, list) or not isinstance(excluded, list):
            raise ValueError("%s triple summary lacks coverage rows" % split)
        qualified_methods = [
            row.get("method") for row in qualified if isinstance(row, dict)
        ]
        excluded_methods = [
            row.get("method") for row in excluded if isinstance(row, dict)
        ]
        all_methods = qualified_methods + excluded_methods
        if (
            any(not isinstance(method, str) or not method for method in all_methods)
            or len(all_methods) != expected_methods
            or len(set(all_methods)) != expected_methods
        ):
            raise ValueError("%s triple summary method coverage mismatch" % split)
        if set(methods) != set(qualified_methods):
            raise ValueError("%s triple selected/qualified mismatch" % split)
        policy = summary.get("selection_policy")
        if not isinstance(policy, dict) or policy.get("numeric_backend_mixing") is not False:
            raise ValueError("%s triple summary permits backend mixing" % split)
        if summary.get("expected_comparisons") != expected_by_split[split]:
            raise ValueError(
                "%s triple summary expected-comparison mismatch" % split
            )
        selected[split] = set(methods)
        covered[split] = set(all_methods)
        status_rows[split] = audit_parallel_status(
            status_paths[split], expected_by_split[split], split
        )

    common = sorted(selected["development"] & selected["heldout"])
    if covered["development"] != covered["heldout"]:
        raise ValueError("triple split method sets do not match")
    if common:
        raise ValueError(
            "triple search has golden-replay candidates: %s" % ", ".join(common)
        )
    return summaries, status_rows


def complete_summary(data):
    expected = data.get("expected_comparisons")
    return bool(
        expected
        and data.get("validated_comparisons") == expected
        and not data.get("incomplete_jobs")
        and not data.get("missing_comparisons")
        and not data.get("excluded")
        and not data.get("baseline_gaps")
        and data.get("plugin_activation_contract") == "validated"
    )


def audit_ranking(ranking, summaries, recompute=False):
    for backend, summary in summaries.items():
        if not complete_summary(summary):
            raise ValueError("%s golden summary is incomplete" % backend)
        row_backends = {
            row.get("backend") for row in summary.get("rows", [])
            if row.get("backend") in ("openroad", "innovus")
        }
        if row_backends != {backend}:
            raise ValueError(
                "%s summary does not contain exactly its backend rows" % backend
            )

    campaigns = ranking.get("campaigns", [])
    by_backend = {
        campaign.get("backend"): campaign for campaign in campaigns
        if campaign.get("backend") in summaries
    }
    if len(campaigns) != 2 or set(by_backend) != set(summaries):
        raise ValueError("ranking does not contain exactly OpenROAD and Innovus")
    for backend, summary in summaries.items():
        expected_cases = sorted(EXPECTED_GOLDEN_CASES[backend])
        if by_backend[backend].get("cases") != expected_cases:
            raise ValueError("%s ranking case coverage mismatch" % backend)
        expected_case_seeds = [
            {"case": case, "seed": seed}
            for case in expected_cases for seed in EXPECTED_GOLDEN_SEEDS
        ]
        if by_backend[backend].get("case_seeds") != expected_case_seeds:
            raise ValueError("%s ranking seed coverage mismatch" % backend)
        expected_hash = canonical_json_sha256(summary)
        if by_backend[backend].get("summary_content_sha256") != expected_hash:
            raise ValueError("%s ranking summary hash mismatch" % backend)

    policy = ranking.get("policy", {})
    if policy.get("name") != "golden_routability_lexicographic_pareto":
        raise ValueError("ranking policy name mismatch")
    if policy.get("numeric_backend_mixing") is not False:
        raise ValueError("ranking policy permits numeric backend mixing")
    if policy.get("numeric_metric_scalarization") is not False:
        raise ValueError("ranking policy permits numeric metric scalarization")
    if policy.get("objective_comparison_tolerance") != OBJECTIVE_TOLERANCE:
        raise ValueError("ranking objective comparison tolerance mismatch")
    required_primary = {
        "drc_violations", "horizontal congestion or overflow",
        "vertical congestion or overflow", "unrouted_nets",
        "short_violations", "Innovus connectivity_violations",
        "Innovus open_violations", "routed wirelength",
    }
    if set(policy.get("primary_metrics", [])) != required_primary:
        raise ValueError("ranking primary metric policy mismatch")
    if policy.get("secondary_metrics") != ["vias"]:
        raise ValueError("ranking secondary metric policy mismatch")
    if (
        policy.get("diagnostic_metrics") != ["placement_hpwl"]
        or policy.get("diagnostic_metrics_affect_decision") is not False
    ):
        raise ValueError("ranking diagnostic metric policy mismatch")
    if policy.get("secondary_cost_guardrails") != {
        "max_mean_regression_pct": 5.0,
        "max_worst_regression_pct": 10.0,
        "zero_baseline_absolute_increase_allowed": False,
    }:
        raise ValueError("ranking secondary cost guardrail mismatch")
    for campaign in campaigns:
        if campaign.get("diagnostic_metrics") != ["placement_hpwl"]:
            raise ValueError("ranking campaign diagnostic metric mismatch")
        candidates = campaign.get("candidates", [])
        if sorted(
            candidate.get("method") for candidate in candidates
            if isinstance(candidate, dict)
        ) != sorted(EXPECTED_GOLDEN_METHODS):
            raise ValueError("ranking candidate diagnostic method coverage mismatch")
        for candidate in candidates:
            diagnostics = candidate.get("diagnostic_metrics")
            objectives = candidate.get("objectives", {})
            if (
                not isinstance(diagnostics, dict)
                or set(diagnostics) != {"placement_hpwl"}
                or any("placement_hpwl" in name for name in objectives)
            ):
                raise ValueError("ranking candidate diagnostic isolation mismatch")

    recommended = ranking.get("recommended_methods")
    bounded = ranking.get("bounded_cost_routability_winners")
    baseline = ranking.get("baseline")
    if not isinstance(bounded, list) or not isinstance(baseline, str) or not baseline:
        raise ValueError("ranking lacks bounded winners or baseline")
    expected_recommendation = bounded or [baseline]
    if recommended != expected_recommendation:
        raise ValueError("ranking recommendation does not match bounded policy winners")
    common_methods = ranking.get("common_methods", [])
    if common_methods != sorted(EXPECTED_GOLDEN_METHODS):
        raise ValueError("ranking finalist method coverage mismatch")
    if not all(method in common_methods for method in recommended):
        raise ValueError("ranking recommendation is absent from common methods")

    if recompute:
        ordered_backends = ("openroad", "innovus")
        sources = [by_backend[backend].get("source") for backend in ordered_backends]
        if any(not isinstance(source, str) or not source for source in sources):
            raise ValueError("ranking campaigns lack source paths for recomputation")
        recomputed = rank_campaigns(
            [summaries[backend] for backend in ordered_backends],
            sources,
            baseline=baseline,
            max_secondary_mean_pct=5.0,
            max_secondary_worst_pct=10.0,
            required_case_sets=[
                EXPECTED_GOLDEN_CASES[backend] for backend in ordered_backends
            ],
            required_seed_sets=[
                EXPECTED_GOLDEN_SEEDS for _backend in ordered_backends
            ],
        )
        if canonical_json_sha256(recomputed) != canonical_json_sha256(ranking):
            raise ValueError(
                "ranking does not match independent summary recomputation"
            )
        return recomputed
    return ranking


def audit_ranking_report(path, ranking):
    if Path(path).read_text() != render_report(ranking):
        raise ValueError("ranking report does not match verified ranking JSON")


def objective_requirement_status(require_production_matrix):
    production_status = (
        "validated" if require_production_matrix else "not_required"
    )
    return {
        "golden_metric_and_artifact_contract": "validated",
        "contest_openroad_matrix": production_status,
        "real_design_innovus_matrix": production_status,
        "backend_local_pareto_recomputation": production_status,
        "human_ranking_report_binding": production_status,
        "bounded_combination_search": "validated",
        "evaluator_source_install_identity": "validated",
        "plugin_registry_and_source_install_identity": "validated",
        "parameter_schema_source_install_identity": "validated",
        "regression_and_source_integrity": "validated",
    }


def audit_regression_manifest(path, log_path, minimum_tests):
    manifest = json.loads(Path(path).read_text())
    log_path = Path(log_path)
    text = log_path.read_text(errors="replace")
    expected_names = (
        "routability", "def_distribution", "ruplace_unit", "ruplace_quality",
    )
    suites = manifest.get("suites")
    if (
        manifest.get("schema_version") != 1
        or not isinstance(suites, list)
        or [row.get("name") for row in suites] != list(expected_names)
    ):
        raise ValueError("regression manifest suite coverage mismatch")
    try:
        manifest_counts = [int(row["tests"]) for row in suites]
    except (KeyError, TypeError, ValueError):
        raise ValueError("regression manifest has invalid test counts")
    log_counts = [
        int(value) for value in re.findall(
            r"^Ran (\d+) tests? in ", text, flags=re.MULTILINE
        )
    ]
    if manifest_counts != log_counts or len(log_counts) != len(expected_names):
        raise ValueError("regression manifest/log test counts mismatch")
    total = sum(log_counts)
    if manifest.get("total_tests") != total or total < minimum_tests:
        raise ValueError("regression manifest total test count mismatch")
    if len(re.findall(r"^OK$", text, flags=re.MULTILINE)) != len(expected_names):
        raise ValueError("regression log lacks complete OK markers")
    if re.search(r"^(?:FAILED|ERROR)(?:\s|$)", text, flags=re.MULTILINE):
        raise ValueError("regression log contains a failure marker")
    if not all(manifest.get(field) is True for field in (
        "all_passed", "python_compilation_passed", "git_diff_check_passed",
    )):
        raise ValueError("regression manifest does not declare every gate passed")
    if manifest.get("regression_log_sha256") != sha256(log_path):
        raise ValueError("regression manifest/log hash mismatch")
    return {row["name"]: row["tests"] for row in suites}, total


def audit_openroad_recovery(campaign_root, result_paths, spec_path=None,
                            report_path=None, archive_root=None,
                            postprocess_report_path=None):
    recovered = {}
    for path in result_paths:
        result = json.loads(Path(path).read_text())
        provenance = result.get("recovery_provenance")
        if provenance is None:
            continue
        name = provenance.get("route_name") if isinstance(provenance, dict) else None
        if not isinstance(name, str) or not name or name in recovered:
            raise ValueError("invalid or duplicate OpenROAD recovery provenance")
        recovered[name] = (Path(path).resolve(), provenance)

    supplied = (
        spec_path is not None, report_path is not None, archive_root is not None,
        postprocess_report_path is not None,
    )
    if any(supplied) and not all(supplied):
        raise ValueError("OpenROAD recovery evidence arguments must be supplied together")
    if recovered and not all(supplied):
        raise ValueError("OpenROAD recovery provenance lacks final audit evidence")
    if not all(supplied):
        return {"used": False, "route_names": [], "sha256": {}}

    spec_path = Path(spec_path).resolve()
    report_path = Path(report_path).resolve()
    archive_root = Path(archive_root).resolve()
    postprocess_report_path = Path(postprocess_report_path).resolve()
    spec = json.loads(spec_path.read_text())
    report = json.loads(report_path.read_text())
    postprocess_report = json.loads(postprocess_report_path.read_text())
    if report.get("dry_run") is not False:
        raise ValueError("OpenROAD recovery import report is not an applied import")
    if report.get("verified_hashes") != spec.get("required_hashes"):
        raise ValueError("OpenROAD recovery report/hash manifest mismatch")
    if Path(report.get("campaign_root", "")).resolve() != Path(campaign_root).resolve():
        raise ValueError("OpenROAD recovery campaign root mismatch")
    if Path(report.get("archive_root", "")).resolve() != archive_root:
        raise ValueError("OpenROAD recovery archive root mismatch")
    recovery_root = Path(report.get("recovery_root", "")).resolve()
    if verify_hashes(recovery_root, spec.get("required_hashes", {})) != report.get(
            "verified_hashes"):
        raise ValueError("OpenROAD recovery source/hash verification mismatch")

    spec_routes = spec.get("routes")
    report_routes = report.get("routes")
    postprocess_routes = postprocess_report.get("routes")
    if (
        postprocess_report.get("schema_version") != 1
        or not isinstance(spec_routes, list)
        or not isinstance(report_routes, list)
        or not isinstance(postprocess_routes, list)
    ):
        raise ValueError("OpenROAD recovery evidence lacks route rows")
    spec_by_name = {row.get("name"): row for row in spec_routes}
    report_by_name = {row.get("name"): row for row in report_routes}
    postprocess_by_source = {
        str(Path(row.get("evaluation_dir", "")).resolve()): row
        for row in postprocess_routes
    }
    if (
        None in spec_by_name or None in report_by_name
        or len(spec_by_name) != len(spec_routes)
        or set(report_by_name) != set(spec_by_name)
        or len(postprocess_by_source) != len(postprocess_routes)
        or len(postprocess_routes) != len(spec_routes)
    ):
        raise ValueError("OpenROAD recovery route coverage mismatch")
    allowed_statuses = {"imported", "already_valid_identical"}
    if any(row.get("status") not in allowed_statuses for row in report_routes):
        raise ValueError("OpenROAD recovery report contains an invalid route status")
    imported_names = {
        name for name, row in report_by_name.items() if row.get("status") == "imported"
    }
    if set(recovered) != imported_names:
        raise ValueError("OpenROAD imported result/provenance coverage mismatch")

    archive_hashes = {}
    timeout_source_hashes = {}
    campaign_root = Path(campaign_root).resolve()
    for name, (result_path, provenance) in recovered.items():
        route = spec_by_name[name]
        report_route = report_by_name[name]
        expected_target = (campaign_root / route.get("target_dir", "")).resolve()
        if result_path.parent != expected_target:
            raise ValueError("OpenROAD recovered result target mismatch: %s" % name)
        if Path(report_route.get("target", "")).resolve() != expected_target:
            raise ValueError("OpenROAD recovery report target mismatch: %s" % name)
        expected_source = (recovery_root / route.get("source_dir", "")).resolve()
        if Path(provenance.get("quarantine_source", "")).resolve() != expected_source:
            raise ValueError("OpenROAD recovery quarantine source mismatch: %s" % name)
        postprocess_row = postprocess_by_source.get(str(expected_source))
        if postprocess_row is None:
            raise ValueError("OpenROAD postprocess source coverage mismatch: %s" % name)
        source_result_path = expected_source / "openroad.json"
        source_result = json.loads(source_result_path.read_text())
        if postprocess_row.get("result") != source_result:
            raise ValueError("OpenROAD postprocess report/result mismatch: %s" % name)
        imported_result = json.loads(result_path.read_text())
        for field in (
            "backend", "design_name", "status", "schema_version", "metrics",
            "recovery_postprocess",
        ):
            if imported_result.get(field) != source_result.get(field):
                raise ValueError(
                    "OpenROAD postprocess/import field mismatch for %s: %s"
                    % (name, field)
                )
        source_artifacts = source_result.get("artifacts", {})
        imported_artifacts = imported_result.get("artifacts", {})
        if {
            key: Path(value).name for key, value in source_artifacts.items()
        } != {
            key: Path(value).name for key, value in imported_artifacts.items()
        }:
            raise ValueError("OpenROAD postprocess/import artifact mismatch: %s" % name)
        timeout_paths = {
            key: expected_source / filename for key, filename in (
                ("result", "openroad.timeout.json"),
                ("summary", "summary.timeout.json"),
                ("log", "openroad.timeout.log"),
            )
        }
        if not all(path.is_file() for path in timeout_paths.values()):
            raise ValueError("missing preserved OpenROAD timeout evidence: %s" % name)
        timeout_result = json.loads(timeout_paths["result"].read_text())
        if (
            timeout_result.get("status") != "timeout"
            or "timeout" not in str(timeout_result.get("error", "")).lower()
        ):
            raise ValueError("preserved OpenROAD source is not timeout evidence: %s" % name)
        timeout_summary = json.loads(timeout_paths["summary"].read_text())
        if timeout_summary.get("results") != [timeout_result]:
            raise ValueError("preserved OpenROAD timeout summary mismatch: %s" % name)
        if timeout_paths["log"].stat().st_size <= 0:
            raise ValueError("preserved OpenROAD timeout log is empty: %s" % name)
        timeout_source_hashes[name] = {
            key: sha256(path) for key, path in timeout_paths.items()
        }
        archived = archive_root / name / "evaluation/openroad.json"
        if not archived.is_file():
            raise ValueError("missing archived OpenROAD timeout result: %s" % name)
        if Path(report_route.get("archived_previous", "")).resolve() != archived.parent:
            raise ValueError("OpenROAD recovery archive path mismatch: %s" % name)
        archived_hash = sha256(archived)
        if report_route.get("archived_previous_sha256") != archived_hash:
            raise ValueError("OpenROAD recovery archive hash mismatch: %s" % name)
        old = json.loads(archived.read_text())
        if (
            old.get("status") != "timeout"
            or "timeout" not in str(old.get("error", "")).lower()
        ):
            raise ValueError("archived OpenROAD result is not timeout evidence: %s" % name)
        archive_hashes[name] = archived_hash
    return {
        "used": bool(recovered),
        "route_names": sorted(recovered),
        "archived_timeout_sha256": archive_hashes,
        "preserved_source_timeout_sha256": timeout_source_hashes,
        "sha256": {
            "import_spec": sha256(spec_path),
            "import_report": sha256(report_path),
            "postprocess_report": sha256(postprocess_report_path),
        },
    }


def audit(args):
    openroad_paths, openroad_ok, openroad_invalid = contract_results(
        args.openroad_campaign, "openroad.json", "openroad"
    )
    innovus_paths, innovus_ok, innovus_invalid = contract_results(
        args.innovus_campaign, "innovus.json", "innovus"
    )
    if (
        len(openroad_paths) != args.require_openroad_results
        or len(openroad_ok) != args.require_openroad_results
    ):
        raise ValueError(
            "OpenROAD result matrix does not satisfy the exact routed metric "
            "contract %d/%d (paths=%d valid=%d invalid=%d)" % (
                args.require_openroad_results, args.require_openroad_results,
                len(openroad_paths), len(openroad_ok), len(openroad_invalid),
            )
        )
    if (
        len(innovus_paths) != args.require_innovus_results
        or len(innovus_ok) != args.require_innovus_results
    ):
        raise ValueError(
            "Innovus result matrix does not satisfy the exact routed metric "
            "contract %d/%d (paths=%d valid=%d invalid=%d)" % (
                args.require_innovus_results, args.require_innovus_results,
                len(innovus_paths), len(innovus_ok), len(innovus_invalid),
            )
        )
    if args.require_production_matrix:
        audit_result_matrix(
            args.openroad_campaign, openroad_paths, "openroad", "openroad.json"
        )
        audit_result_matrix(
            args.innovus_campaign, innovus_paths, "innovus", "innovus.json"
        )
    recovery_audit = audit_openroad_recovery(
        args.openroad_campaign, openroad_paths,
        args.openroad_recovery_import_spec,
        args.openroad_recovery_import_report,
        args.openroad_recovery_archive,
        args.openroad_recovery_postprocess_report,
    )

    compact = compact_innovus_reports(args.innovus_campaign)
    if args.require_compact_innovus and not compact:
        raise ValueError("no post-install compact Innovus DRC artifact was retained")
    evaluator_hashes = audit_evaluator_identity(
        args.source_evaluator_dir, args.installed_evaluator_dir
    )
    plugin_hashes = audit_plugin_identity(
        args.source_plugin_dir, args.installed_plugin_dir
    )
    params_hash = audit_params_identity(
        args.source_params, args.installed_params
    )
    triple_summaries, triple_status = audit_triple_search(
        args.triple_development_summary, args.triple_heldout_summary,
        args.triple_development_status, args.triple_heldout_status,
        args.require_triple_development_results,
        args.require_triple_heldout_results,
        args.require_triple_methods,
    )

    summaries = {
        "openroad": json.loads(args.openroad_summary.read_text()),
        "innovus": json.loads(args.innovus_summary.read_text()),
    }
    ranking = json.loads(args.ranking.read_text())
    verified_ranking = audit_ranking(
        ranking, summaries, recompute=args.require_production_matrix
    )
    if args.require_production_matrix:
        audit_ranking_report(args.report, verified_ranking)
    regression_suites, regression_total = audit_regression_manifest(
        args.regression_manifest, args.regression_log,
        args.minimum_regression_tests,
    )

    return {
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "openroad_ok_results": len(openroad_ok),
        "innovus_ok_results": len(innovus_ok),
        "routed_metric_contract": "validated",
        "production_matrix_contract": (
            "validated" if args.require_production_matrix else "not_required"
        ),
        "compact_innovus_drc_reports": len(compact),
        "recommended_methods": ranking["recommended_methods"],
        "ranking_policy": ranking["policy"]["name"],
        "objective_requirements": objective_requirement_status(
            args.require_production_matrix
        ),
        "summary_content_sha256": {
            backend: canonical_json_sha256(summary)
            for backend, summary in summaries.items()
        },
        "source_install_evaluators_match": True,
        "evaluator_sha256": evaluator_hashes,
        "plugin_registry": {
            name: class_name
            for name, (_module, class_name) in EXPECTED_PLUGIN_REGISTRY.items()
        },
        "source_install_plugins_match": True,
        "plugin_sha256": plugin_hashes,
        "source_install_params_match": True,
        "params_sha256": params_hash,
        "openroad_recovery": recovery_audit,
        "triple_search_common_survivors": [],
        "triple_search_completed_jobs": {
            split: len(rows) for split, rows in triple_status.items()
        },
        "triple_summary_content_sha256": {
            split: canonical_json_sha256(summary)
            for split, summary in triple_summaries.items()
        },
        "python_compilation_passed": True,
        "regressions_passed": True,
        "git_diff_check_passed": True,
        "regression_suite_tests": regression_suites,
        "regression_total_tests": regression_total,
        "sha256": {
            "openroad_summary": sha256(args.openroad_summary),
            "innovus_summary": sha256(args.innovus_summary),
            "ranking_json": sha256(args.ranking),
            "ranking_report": sha256(args.report),
            "regression_log": sha256(args.regression_log),
            "regression_manifest": sha256(args.regression_manifest),
            "triple_development_summary": sha256(
                args.triple_development_summary
            ),
            "triple_heldout_summary": sha256(args.triple_heldout_summary),
            "triple_development_status": sha256(
                args.triple_development_status
            ),
            "triple_heldout_status": sha256(args.triple_heldout_status),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openroad-campaign", type=Path, required=True)
    parser.add_argument("--innovus-campaign", type=Path, required=True)
    parser.add_argument("--openroad-summary", type=Path, required=True)
    parser.add_argument("--innovus-summary", type=Path, required=True)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--regression-log", type=Path, required=True)
    parser.add_argument("--regression-manifest", type=Path, required=True)
    parser.add_argument(
        "--triple-development-summary", type=Path, required=True
    )
    parser.add_argument("--triple-heldout-summary", type=Path, required=True)
    parser.add_argument("--triple-development-status", type=Path, required=True)
    parser.add_argument("--triple-heldout-status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-evaluator-dir", type=Path,
        default=Path("dreamplace/ops/routability_eval"),
    )
    parser.add_argument(
        "--installed-evaluator-dir", type=Path,
        default=Path("install/dreamplace/ops/routability_eval"),
    )
    parser.add_argument(
        "--source-plugin-dir", type=Path,
        default=Path("dreamplace/ops/routability_opt/plugins"),
    )
    parser.add_argument(
        "--installed-plugin-dir", type=Path,
        default=Path("install/dreamplace/ops/routability_opt/plugins"),
    )
    parser.add_argument(
        "--source-params", type=Path, default=Path("dreamplace/params.json"),
    )
    parser.add_argument(
        "--installed-params", type=Path,
        default=Path("install/dreamplace/params.json"),
    )
    parser.add_argument("--require-openroad-results", type=int, default=45)
    parser.add_argument("--require-innovus-results", type=int, default=75)
    parser.add_argument(
        "--require-triple-development-results", type=int, default=6
    )
    parser.add_argument("--require-triple-heldout-results", type=int, default=3)
    parser.add_argument("--require-triple-methods", type=int, default=3)
    parser.add_argument("--require-compact-innovus", action="store_true")
    parser.add_argument("--require-production-matrix", action="store_true")
    parser.add_argument("--minimum-regression-tests", type=int, default=204)
    parser.add_argument("--openroad-recovery-import-spec", type=Path)
    parser.add_argument("--openroad-recovery-import-report", type=Path)
    parser.add_argument("--openroad-recovery-archive", type=Path)
    parser.add_argument("--openroad-recovery-postprocess-report", type=Path)
    args = parser.parse_args(argv)
    if any(count <= 0 for count in (
        args.require_openroad_results, args.require_innovus_results,
        args.require_triple_development_results,
        args.require_triple_heldout_results,
        args.require_triple_methods, args.minimum_regression_tests,
    )):
        parser.error("required result counts must be positive")
    result = audit(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
