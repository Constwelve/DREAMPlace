#!/usr/bin/env python3
"""Audit the dynamically selected corrected routability-validation pipeline."""

import argparse
import csv
import datetime
import hashlib
import json
import math
from pathlib import Path


from tools.routability_audit_final import (
    audit_evaluator_identity,
    audit_params_identity,
    audit_plugin_identity,
)
from tools.routability_golden_replay import result_meets_resume_contract
from tools.routability_rank_golden import rank_campaigns, render_report
from tools.routability_select_survivors import (
    routability_metric_profile,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SEEDS = (1000, 2000, 3000)
EXPECTED_GOLDEN_CASES = {
    "openroad": ("data_ispd19_test3",),
    "innovus": (
        "taiwei_nangate45_bp_quad_materialized2d",
        "taiwei_nangate45_mempool_group_materialized2d",
        "taiwei_nangate45_nvdla_l_materialized2d",
        "taiwei_nangate45_openc910_materialized2d",
        "taiwei_nangate45_xscore_materialized2d",
    ),
}
EXPECTED_PROXY_COMPARISONS = {
    "contest_heldout": 3,
    "real_development": 9,
    "real_heldout": 6,
}
EXPECTED_PROXY_RESOLUTIONS = {
    "contest": (256, 256),
    "contest_heldout": (256, 256),
    "corrected_replay_development": (256, 256),
    "adaptive_v2_development": (256, 256),
    "missing_families_development": (256, 256),
    "missing_families_adaptive_v2_development": (256, 256),
    "missing_families_adaptive_v3_development": (256, 256),
    "corrected_net_weight_lifecycle_development": (256, 256),
    "real_development": (128, 128),
    "real_heldout": (128, 128),
}
EXPECTED_PROXY_STAGE_CASES = {
    "contest": (
        "data_ispd19_test1", "data_ispd19_test2", "data_ispd19_test3",
    ),
    "contest_heldout": ("data_ispd19_test3",),
    "corrected_replay_development": (
        "data_ispd19_test1", "data_ispd19_test2",
    ),
    "adaptive_v2_development": (
        "data_ispd19_test1", "data_ispd19_test2",
    ),
    "missing_families_development": (
        "data_ispd19_test1", "data_ispd19_test2",
    ),
    "missing_families_adaptive_v2_development": (
        "data_ispd19_test1", "data_ispd19_test2",
    ),
    "missing_families_adaptive_v3_development": (
        "data_ispd19_test1", "data_ispd19_test2",
    ),
    "corrected_net_weight_lifecycle_development": (
        "data_ispd19_test1", "data_ispd19_test2",
    ),
    "real_development": (
        "taiwei_nangate45_bp_quad_materialized2d",
        "taiwei_nangate45_mempool_group_materialized2d",
        "taiwei_nangate45_nvdla_l_materialized2d",
    ),
    "real_heldout": (
        "taiwei_nangate45_openc910_materialized2d",
        "taiwei_nangate45_xscore_materialized2d",
    ),
}
EXPECTED_PROXY_STAGE_SLOTS = {
    label: tuple(
        (case, seed) for case in cases for seed in EXPECTED_SEEDS
    )
    for label, cases in EXPECTED_PROXY_STAGE_CASES.items()
}
EXPECTED_PROXY_STAGE_COMPARISONS = {
    label: len(slots) for label, slots in EXPECTED_PROXY_STAGE_SLOTS.items()
}
NO_CANDIDATE_SELECTION_SETS = {
    "completed_no_contest_survivor": (
        frozenset(("contest_heldout",)),
    ),
    "completed_no_real_development_survivor": (
        frozenset(("real_development",)),
    ),
    "completed_real_heldout_proxy_validation": (
        frozenset(("real_heldout",)),
    ),
    "completed_no_integrated_contest_survivor": (
        frozenset(("contest_heldout",)),
        frozenset((
            "corrected_replay_development",
            "adaptive_v2_development",
            "missing_families_development",
            "missing_families_adaptive_v2_development",
        )),
        frozenset((
            "corrected_replay_development",
            "adaptive_v2_development",
            "missing_families_development",
            "missing_families_adaptive_v2_development",
            "missing_families_adaptive_v3_development",
            "corrected_net_weight_lifecycle_development",
        )),
    ),
    "completed_no_integrated_real_development_survivor": (
        frozenset(("real_development",)),
    ),
    "completed_integrated_real_heldout_proxy_validation": (
        frozenset(("real_heldout",)),
    ),
}
EXPECTED_EVALUATOR_MODULES = {"base.py", "innovus.py", "openroad.py"}
PROXY_METRIC_PROFILE_FILES = (
    "dreamplace/ops/gpugr/xplace_backend.py",
    "dreamplace/ops/routability_eval/base.py",
    "dreamplace/ops/routability_eval/rudy.py",
    "dreamplace/ops/routability_eval/xplace.py",
)
MISSING_FAMILY_STAGE = "missing_families_development"
POLICY_V7_STAGE = "corrected_net_weight_lifecycle_development"
POLICY_V7_CANDIDATE_COUNT = 192
POLICY_V7_METHOD_COUNT = POLICY_V7_CANDIDATE_COUNT + 1
POLICY_V7_COMPARISON_COUNT = 6
POLICY_V7_PLACEMENT_COUNT = (
    POLICY_V7_CANDIDATE_COUNT * POLICY_V7_COMPARISON_COUNT
)
POLICY_V7_EVALUATOR_RESULT_COUNT = (
    POLICY_V7_METHOD_COUNT * POLICY_V7_COMPARISON_COUNT * 2
)
REQUIRED_MISSING_FAMILIES = (
    "route_inflation",
    "momentum_inflation",
    "path_inflation",
    "pin_porosity",
    "routeforce",
)
MISSING_FAMILY_VARIANT_COUNT = 6
MISSING_FAMILY_ACTIVATION_THRESHOLDS = (0.3, 0.5, 0.8)
LOCAL_PLUGIN_TERMINAL_VERSIONS = {
    "connection_routeforce": "v35",
    "projected_connection_routeforce": "v40",
    "routed_overflow_net_contraction": "v53",
    "net_relaxation": "v59",
    "directional_net_contraction": "v63",
    "directional_path_spreading": "v67",
    "virtual_cell": "v69",
    "directional_virtual_cell": "v71",
}
MISSING_FAMILY_TUNING_KEYS = {
    "route_inflation": (
        "max_num_area_adjust", "ruplace_global_inflate_gamma",
        "ruplace_hv_inflate_mode", "ruplace_inflate_area_cap",
        "ruplace_local_inflate_max_rounds",
    ),
    "momentum_inflation": (
        "max_num_area_adjust", "ruplace_inflate_area_cap",
        "ruplace_momentum_beta", "ruplace_momentum_rounds",
        "ruplace_momentum_step",
    ),
    "path_inflation": (
        "max_num_area_adjust", "ruplace_inflate_area_cap",
        "ruplace_path_inflate_gamma", "ruplace_path_inflate_rounds",
    ),
    "pin_porosity": (
        "max_num_area_adjust", "ruplace_inflate_area_cap",
        "ruplace_pin_porosity_gamma", "ruplace_pin_porosity_rounds",
        "ruplace_porosity_radius", "ruplace_porosity_weight",
    ),
    "routeforce": (
        "ruplace_admm_apply_freq", "ruplace_admm_route_freq",
        "ruplace_admm_weight", "ruplace_admm_weight_decay",
    ),
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def valid_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def canonical_json_sha256(data):
    payload = json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def load_json(path):
    return json.loads(Path(path).read_text())


def read_status(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def audit_proxy_metric_profile(path, source_root=ROOT, install_root=None):
    source_root = Path(source_root).resolve()
    install_root = Path(install_root or (source_root / "install")).resolve()
    rows = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError("invalid proxy metric-profile hash manifest")
        digest, name = parts
        if name.startswith("*"):
            name = name[1:]
        if name in rows:
            raise ValueError("duplicate proxy metric-profile hash entry")
        rows[name] = digest

    expected = set(PROXY_METRIC_PROFILE_FILES) | {
        "install/" + name for name in PROXY_METRIC_PROFILE_FILES
    }
    if set(rows) != expected:
        raise ValueError("proxy metric-profile hash coverage mismatch")

    verified = {}
    for name in PROXY_METRIC_PROFILE_FILES:
        source = source_root / name
        installed = install_root / name
        source_hash = sha256(source)
        installed_hash = sha256(installed)
        if (
            rows[name] != source_hash
            or rows["install/" + name] != installed_hash
            or source_hash != installed_hash
        ):
            raise ValueError("proxy metric-profile source/install mismatch: %s" % name)
        verified[name] = source_hash
    return {
        "manifest_sha256": sha256(path),
        "source_install_match": True,
        "files": verified,
    }


def audit_proxy_metric_profile_record(proxy):
    record = proxy.get("metric_profile_code", {})
    files = record.get("files", {})
    expected = set(PROXY_METRIC_PROFILE_FILES)
    if (
        proxy.get("metric_profile") != "absolute_directional_v2"
        or record.get("source_install_match") is not True
        or set(files) != expected
        or any(not valid_sha256(digest) for digest in files.values())
    ):
        raise ValueError("invalid proxy metric-profile code attestation")
    manifest_hash = record.get("manifest_sha256")
    if (
        not valid_sha256(manifest_hash)
        or proxy.get("sha256", {}).get("proxy_metric_profile_manifest")
        != manifest_hash
    ):
        raise ValueError("proxy metric-profile manifest binding mismatch")
    return record


def audit_missing_family_attestation_record(record):
    expected_case_seeds = [
        {"case": case, "seed": seed}
        for case, seed in EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE]
    ]
    if (
        record.get("schema_version") != 1
        or record.get("status") != "passed"
        or record.get("stage") != MISSING_FAMILY_STAGE
        or record.get("metric_profile") != "absolute_directional_v2"
        or record.get("numeric_backend_mixing") is not False
        or record.get("heldout_or_golden_evidence_used") is not False
        or record.get("required_families") != list(REQUIRED_MISSING_FAMILIES)
        or record.get("validated_case_seeds") != expected_case_seeds
        or record.get("reported_resolution")
        != list(EXPECTED_PROXY_RESOLUTIONS[MISSING_FAMILY_STAGE])
    ):
        raise ValueError("invalid missing-family development attestation")
    coverage = record.get("family_methods")
    if set(coverage or {}) != set(REQUIRED_MISSING_FAMILIES):
        raise ValueError("missing-family attestation coverage mismatch")
    evaluated = set(record.get("evaluated_methods", []))
    if "hpwl" not in evaluated:
        raise ValueError("missing-family attestation lacks HPWL")
    family_methods = set()
    for family in REQUIRED_MISSING_FAMILIES:
        methods = coverage[family]
        if not isinstance(methods, list) or not methods:
            raise ValueError("missing-family attestation has an empty family")
        if family_methods & set(methods):
            raise ValueError("missing-family methods overlap across families")
        family_methods.update(methods)
    if evaluated != {"hpwl"} | family_methods:
        raise ValueError("missing-family attestation method coverage mismatch")
    retained_coverage = record.get("retained_family_methods")
    if set(retained_coverage or {}) != set(REQUIRED_MISSING_FAMILIES):
        raise ValueError("missing-family retained coverage mismatch")
    retained_methods = set()
    for family in REQUIRED_MISSING_FAMILIES:
        methods = retained_coverage[family]
        if (
            not isinstance(methods, list)
            or not methods
            or not set(methods) <= set(coverage[family])
            or retained_methods & set(methods)
        ):
            raise ValueError("missing-family retained methods are invalid")
        retained_methods.update(methods)
    excluded = record.get("excluded_inactive_methods")
    if not isinstance(excluded, list):
        raise ValueError("missing-family exclusions are invalid")
    excluded_names = []
    for row in excluded:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("method"), str)
            or not row.get("affected_case_seeds")
            or any(
                not affected.get("activation_error")
                for affected in row["affected_case_seeds"]
            )
        ):
            raise ValueError("missing-family exclusion evidence is invalid")
        excluded_names.append(row["method"])
    if (
        len(excluded_names) != len(set(excluded_names))
        or set(excluded_names) != family_methods - retained_methods
        or record.get("activation_contract")
        != "every retained plugin is active on every development case/seed"
    ):
        raise ValueError("missing-family activation contract mismatch")
    activation_audit = record.get("activation_audit")
    if (
        not isinstance(activation_audit, dict)
        or activation_audit.get("schema_version") != 1
        or activation_audit.get("status") not in ("passed", "inactive_methods")
        or activation_audit.get("case_seed_count")
        != len(EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE])
        or activation_audit.get("method_count") != len(evaluated)
        or activation_audit.get("inactive_method_count") != len(excluded_names)
        or {
            row.get("method")
            for row in activation_audit.get("inactive_methods", [])
        } != set(excluded_names)
    ):
        raise ValueError("missing-family activation audit is invalid")
    expected_retained_placements = (
        len(retained_methods)
        * len(EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE])
    )
    if (
        record.get("validated_retained_placements")
        != expected_retained_placements
        or record.get("validated_proxy_results")
        != len(evaluated)
        * len(EXPECTED_PROXY_STAGE_SLOTS[MISSING_FAMILY_STAGE]) * 2
    ):
        raise ValueError("missing-family validated slot counts are invalid")
    tuning = record.get("tuning_coverage")
    if set(tuning or {}) != set(REQUIRED_MISSING_FAMILIES):
        raise ValueError("missing-family tuning coverage mismatch")
    for family in REQUIRED_MISSING_FAMILIES:
        row = tuning[family]
        threshold_key = (
            "ruplace_plugin_start_overflow"
            if family == "routeforce"
            else "ruplace_inflate_start_overflow"
        )
        if (
            row.get("variant_count") != len(coverage[family])
            or row.get("variant_count") != MISSING_FAMILY_VARIANT_COUNT
            or row.get("activation_threshold_key") != threshold_key
            or row.get("activation_thresholds")
            != list(MISSING_FAMILY_ACTIVATION_THRESHOLDS)
        ):
            raise ValueError("invalid missing-family tuning coverage")
        varied = set(row.get("varied_parameter_keys", []))
        required = set(MISSING_FAMILY_TUNING_KEYS[family])
        values = row.get("parameter_values", {})
        if (
            not required <= varied
            or not required <= set(values)
            or any(len(values[key]) < 2 for key in required)
        ):
            raise ValueError("missing-family tuning dimensions are incomplete")
    selected = record.get("selected_methods")
    if (
        not isinstance(selected, list)
        or len(selected) != len(set(selected))
        or not set(selected) <= retained_methods
    ):
        raise ValueError("missing-family attestation selection mismatch")
    hashes = record.get("sha256")
    if (
        not isinstance(hashes, dict)
        or set(hashes) != {"presets", "manifest", "selection", "screening_raw"}
        or any(not valid_sha256(value) for value in hashes.values())
    ):
        raise ValueError("missing-family attestation hashes are invalid")
    return record


def audit_local_plugin_attestation_record(record):
    plugins = record.get("plugins")
    source_dir = Path(record.get("source_dir", ""))
    if (
        record.get("schema_version") != 1
        or record.get("status") != "passed"
        or record.get("stage") != "local_plugin_terminal_pilots"
        or record.get("conclusion") != "no_strict_local_plugin_survivor"
        or record.get("metric_profile") != "absolute_directional_v2"
        or record.get("validators") != ["gpugr", "rudy"]
        or record.get("numeric_backend_mixing") is not False
        or record.get("heldout_or_golden_evidence_used") is not False
        or record.get("selected_methods") != []
        or record.get("terminal_versions") != LOCAL_PLUGIN_TERMINAL_VERSIONS
        or set(plugins or {}) != set(LOCAL_PLUGIN_TERMINAL_VERSIONS)
        or not source_dir.is_dir()
        or not valid_sha256(record.get("gpugr_binary_sha256"))
    ):
        raise ValueError("invalid local-plugin terminal attestation")
    for plugin, version in LOCAL_PLUGIN_TERMINAL_VERSIONS.items():
        row = plugins[plugin]
        current_source = source_dir / (plugin + ".py")
        hashes = row.get("evidence_sha256")
        if (
            row.get("terminal_version") != version
            or not isinstance(row.get("candidate_count"), int)
            or row["candidate_count"] <= 0
            or row.get("selected_methods") != []
            or row.get("strict_recomputed_survivor_count") != 0
            or row.get("metric_profile") != "absolute_directional_v2"
            or row.get("validators") != ["gpugr", "rudy"]
            or row.get("numeric_backend_mixing") is not False
            or row.get("heldout_or_golden_evidence_used") is not False
            or row.get("current_source_snapshot_witnesses") != [plugin]
            or row.get("terminal_source_matches_current") is not True
            or not valid_sha256(row.get("terminal_evaluated_plugin_sha256"))
            or not valid_sha256(row.get("current_source_sha256"))
            or row.get("terminal_evaluated_plugin_sha256")
            != row.get("current_source_sha256")
            or not valid_sha256(row.get("selection_content_sha256"))
            or not isinstance(hashes, dict)
            or not hashes
            or any(not valid_sha256(value) for value in hashes.values())
            or not current_source.is_file()
            or sha256(current_source) != row.get("current_source_sha256")
            or row.get("gpugr_binary_sha256")
            != record.get("gpugr_binary_sha256")
        ):
            raise ValueError(
                "invalid local-plugin terminal evidence: %s" % plugin
            )
    return record


def audit_policy_v7_attestation_record(record):
    expected_dimensions = {
        "feedback_proxies": ["gpugr", "rudy"],
        "gammas": [0.005, 0.025],
        "frequencies": [10, 40],
        "activation_thresholds": [0.4, 0.8],
        "normalizations": ["absolute", "design_mean"],
        "lifecycle_phases": ["post_gradient", "pre_objective"],
        "score_modes": ["bbox_mean", "bbox_pmean", "pin_mean"],
    }
    required_hashes = {
        "presets", "manifest", "summary", "screening_raw", "selection",
        "placement_effect_audit", "selection_audit", "terminal_status",
        "optimization_source_install", "active_net_mask_audit",
    }
    hashes = record.get("sha256")
    selected = record.get("selected_methods")
    placement_class_counts = [
        record.get(key) for key in (
            "active_changed_count",
            "active_identical_count",
            "inactive_identical_count",
            "inactive_changed_count",
        )
    ]
    excluded_methods = record.get("placement_effect_excluded_methods")
    if (
        record.get("schema_version") != 1
        or record.get("status") != "passed"
        or record.get("stage") != POLICY_V7_STAGE
        or record.get("proposal_policy_version") != 7
        or record.get("metric_profile") != "absolute_directional_v2"
        or record.get("numeric_backend_mixing") is not False
        or record.get("heldout_or_golden_evidence_used") is not False
        or record.get("candidate_count") != POLICY_V7_CANDIDATE_COUNT
        or record.get("method_count") != POLICY_V7_METHOD_COUNT
        or record.get("comparison_count") != POLICY_V7_COMPARISON_COUNT
        or record.get("candidate_placement_count")
        != POLICY_V7_PLACEMENT_COUNT
        or record.get("evaluator_result_count")
        != POLICY_V7_EVALUATOR_RESULT_COUNT
        or record.get("placement_hpwl_count")
        != POLICY_V7_METHOD_COUNT * POLICY_V7_COMPARISON_COUNT
        or record.get("primary_metric_value_count") != (
            POLICY_V7_METHOD_COUNT * POLICY_V7_COMPARISON_COUNT * 29
        )
        or record.get("factorial_dimensions") != expected_dimensions
        or record.get("factorial_unique_point_count")
        != POLICY_V7_CANDIDATE_COUNT
        or record.get("optimization_source_install_match") is not True
        or set(record.get("optimization_source_sha256", {})) != {
            "dreamplace/PlaceObj.py",
            "dreamplace/ops/routability_opt/plugin_base.py",
            "dreamplace/ops/routability_opt/pipeline.py",
            "dreamplace/ops/routability_opt/proxy.py",
            "dreamplace/ops/routability_opt/plugins/net_weighting.py",
            "dreamplace/params.json",
        }
        or any(
            not valid_sha256(value)
            for value in record.get("optimization_source_sha256", {}).values()
        )
        or record.get("active_net_mask_audit_status") != "passed"
        or set(record.get("gpugr_runtime_sha256", {})) != {
            "gpugr_extension",
            "io_parser_extension",
            "xplace_common",
            "xplace_flute",
        }
        or any(
            not valid_sha256(value)
            for value in record.get("gpugr_runtime_sha256", {}).values()
        )
        or not isinstance(selected, list)
        or len(selected) != len(set(selected))
        or record.get("selection_recomputed") is not True
        or record.get("placement_effect_recomputed") is not True
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in placement_class_counts
        )
        or sum(placement_class_counts) != POLICY_V7_PLACEMENT_COUNT
        or not isinstance(excluded_methods, list)
        or len(excluded_methods) != len(set(excluded_methods))
        or any(not isinstance(method, str) or not method for method in excluded_methods)
        or set(excluded_methods) & set(selected)
        or not isinstance(hashes, dict)
        or set(hashes) != required_hashes
        or any(not valid_sha256(value) for value in hashes.values())
    ):
        raise ValueError("invalid Policy V7 campaign attestation")
    return record


def selection_methods(selection):
    methods = {selection.get("baseline")}
    for group in ("qualified", "excluded"):
        methods.update(
            row.get("method") for row in selection.get(group, [])
            if isinstance(row, dict) and row.get("method")
        )
    methods.discard(None)
    return methods


def audit_proxy_resolution_evidence(selection_path, selection, stage_label,
                                    expected_comparisons,
                                    expected_resolution):
    expected_stage_slots = set(EXPECTED_PROXY_STAGE_SLOTS.get(stage_label, ()))
    if (
        not expected_stage_slots
        or len(expected_stage_slots) != expected_comparisons
    ):
        raise ValueError("unknown or inconsistent proxy evidence stage")
    raw_path = Path(selection_path).parent / "screening_raw.csv"
    if not raw_path.is_file():
        raise ValueError("proxy selection lacks raw resolution evidence")
    with raw_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "backend", "case", "seed", "method", "status",
            "route_x_size", "route_y_size",
        }
        if not required <= set(reader.fieldnames or ()):
            raise ValueError("proxy raw evidence lacks reported resolution columns")
        rows = list(reader)

    expected_methods = selection_methods(selection)
    if "hpwl" not in expected_methods:
        raise ValueError("proxy resolution evidence has no HPWL baseline")
    expected_backends = {"rudy", "gpugr"}
    slots = set()
    comparison_slots = {}
    observed_methods = set()
    for row in rows:
        backend = row["backend"]
        if backend not in expected_backends:
            continue
        method = row["method"]
        observed_methods.add(method)
        try:
            seed = int(row["seed"])
            route_x = float(row["route_x_size"])
            route_y = float(row["route_y_size"])
        except (TypeError, ValueError):
            raise ValueError("proxy raw evidence has invalid reported resolution")
        if (
            row["status"] != "ok"
            or (route_x, route_y) != tuple(expected_resolution)
        ):
            raise ValueError(
                "proxy raw evidence has mismatched reported resolution"
            )
        slot = (row["case"], seed, method, backend)
        if slot in slots:
            raise ValueError("proxy raw evidence has duplicate result slot")
        slots.add(slot)
        key = (method, backend)
        comparison_slots.setdefault(key, set()).add((row["case"], seed))

    if observed_methods != expected_methods:
        raise ValueError("proxy raw evidence method coverage mismatch")
    expected_keys = {
        (method, backend)
        for method in expected_methods for backend in expected_backends
    }
    if set(comparison_slots) != expected_keys:
        raise ValueError("proxy raw evidence result matrix mismatch")
    reference_slots = comparison_slots[("hpwl", "rudy")]
    if len(reference_slots) != expected_comparisons:
        raise ValueError("proxy raw evidence comparison count mismatch")
    if reference_slots != expected_stage_slots:
        raise ValueError("proxy raw evidence case-seed coverage mismatch")
    if any(
        method_slots != reference_slots
        for method_slots in comparison_slots.values()
    ):
        raise ValueError("proxy raw evidence comparison-slot matrix mismatch")
    return {
        "raw_path": str(raw_path.resolve()),
        "raw_sha256": sha256(raw_path),
        "reported_resolution": list(expected_resolution),
        "methods": sorted(expected_methods),
        "validated_comparisons": expected_comparisons,
        "validated_results": len(slots),
        "comparison_slots": [
            {"case": case, "seed": seed}
            for case, seed in sorted(reference_slots)
        ],
    }


def audit_proxy_resolution_record(proxy, expected_labels=None):
    records = proxy.get("proxy_resolution_evidence")
    if not isinstance(records, dict) or not records:
        raise ValueError("proxy attestation lacks resolution evidence")
    if expected_labels is not None and set(records) != set(expected_labels):
        raise ValueError("proxy attestation resolution-stage coverage mismatch")
    hashes = proxy.get("sha256", {})
    for label, record in records.items():
        resolution = record.get("reported_resolution")
        digest = record.get("raw_sha256")
        raw_path = record.get("raw_path")
        methods = record.get("methods")
        expected_comparisons = EXPECTED_PROXY_STAGE_COMPARISONS.get(label)
        expected_slots = set(EXPECTED_PROXY_STAGE_SLOTS.get(label, ()))
        comparison_slots = record.get("comparison_slots")
        normalized_slots = {
            (row.get("case"), row.get("seed"))
            for row in comparison_slots or () if isinstance(row, dict)
        }
        if (
            label not in EXPECTED_PROXY_RESOLUTIONS
            or resolution != list(EXPECTED_PROXY_RESOLUTIONS[label])
            or not isinstance(methods, list)
            or len(methods) != len(set(methods))
            or "hpwl" not in methods
            or any(not isinstance(method, str) or not method for method in methods)
            or record.get("validated_comparisons") != expected_comparisons
            or not isinstance(record.get("validated_results"), int)
            or record["validated_results"]
                != 2 * len(methods) * expected_comparisons
            or not isinstance(comparison_slots, list)
            or len(comparison_slots) != expected_comparisons
            or len(normalized_slots) != expected_comparisons
            or normalized_slots != expected_slots
            or any(
                not isinstance(case, str)
                or not case
                or not isinstance(seed, int)
                for case, seed in normalized_slots
            )
            or not isinstance(raw_path, str)
            or not raw_path
            or not valid_sha256(digest)
            or hashes.get("proxy_resolution_raw:%s" % label) != digest
        ):
            raise ValueError("invalid proxy resolution evidence record")
    return records


def selected_record(selection, method):
    matches = [
        row for row in selection.get("qualified", [])
        if row.get("method") == method
    ]
    if len(matches) != 1:
        raise ValueError("selected method lacks one qualified record: %s" % method)
    return matches[0]


def metric_delta(metric, prefix):
    percent = metric.get(prefix + "_delta_pct")
    if (
        metric.get("percent_valid_count", metric.get("valid_count"))
        == metric.get("valid_count")
        and finite_number(percent)
    ):
        return percent, "percent"
    raw = metric.get(prefix + "_delta")
    if not finite_number(raw):
        raise ValueError("proxy metric lacks finite %s delta" % prefix)
    return raw, "absolute"


def audit_strict_selection(path, expected_comparisons, allow_empty=False,
                           required_metric_profile=None):
    selection = load_json(path)
    if selection.get("baseline") != "hpwl":
        raise ValueError("proxy selection baseline is not hpwl")
    if selection.get("expected_comparisons") != expected_comparisons:
        raise ValueError("proxy selection comparison count mismatch")
    policy = selection.get("selection_policy", {})
    if policy.get("name") != "routability_first":
        raise ValueError("proxy selection is not routability-first")
    metric_profile = policy.get("metric_profile", "legacy")
    if (
        required_metric_profile is not None
        and metric_profile != required_metric_profile
    ):
        raise ValueError(
            "proxy metric profile is %s, expected %s" % (
                metric_profile, required_metric_profile
            )
        )
    profile = routability_metric_profile(metric_profile)
    if policy.get("numeric_backend_mixing") is not False:
        raise ValueError("proxy selection mixes backend metrics")
    if policy.get("max_primary_worst_regression") != 0.0:
        raise ValueError("proxy selection lacks the zero worst-regression gate")
    guarded_backends = list(profile["worst_regression_backends"])
    declared_guarded_backends = policy.get("worst_regression_backends")
    if (
        declared_guarded_backends is not None
        and declared_guarded_backends != guarded_backends
    ):
        raise ValueError("proxy worst-regression backend set changed")
    constraints = policy.get("backend_improvement_constraints")
    expected_constraints = json.loads(json.dumps(profile["constraints"]))
    if constraints != expected_constraints:
        raise ValueError("proxy backend improvement constraints changed")
    expected_primary = ["%s:%s" % item for item in profile["primary"]]
    if policy.get("primary_objectives") != expected_primary:
        raise ValueError("proxy primary objective set changed")

    methods = selection.get("selected_methods")
    if not isinstance(methods, list) or len(methods) != len(set(methods)):
        raise ValueError("proxy selection has invalid selected methods")
    if not methods and not allow_empty:
        raise ValueError("proxy selection has no surviving method")
    if not methods and (
        selection.get("qualified") or selection.get("pareto_frontier")
    ):
        raise ValueError("empty proxy selection still contains qualified methods")
    frontier = selection.get("pareto_frontier", [])
    for method in methods:
        if method == "hpwl" or method not in frontier:
            raise ValueError("selected method is not a nonbaseline Pareto member")
        record = selected_record(selection, method)
        metrics = record.get("metrics", {})
        for name in expected_primary:
            metric = metrics.get(name)
            if not isinstance(metric, dict):
                raise ValueError("selected method lacks primary metric %s" % name)
            if metric.get("valid_count") != expected_comparisons:
                raise ValueError(
                    "selected method lacks full primary metric coverage: %s" % name
                )
            backend = name.split(":", 1)[0]
            worst, _unit = metric_delta(metric, "worst")
            if backend in guarded_backends and worst > 0.0:
                raise ValueError(
                    "selected method regresses worst-case primary metric %s" % name
                )
        for backend, constraint in profile["constraints"].items():
            improvements = 0
            for metric_name in constraint["metrics"]:
                name = "%s:%s" % (backend, metric_name)
                prefix = "median" if name == "rudy:overflow_sum" else "mean"
                value, _unit = metric_delta(metrics[name], prefix)
                improvements += value < 0.0
            if improvements < constraint["minimum_improvements"]:
                raise ValueError(
                    "selected method lacks a %s primary improvement" % backend
                )
    return selection


def audit_proxy_chain(args):
    metric_profile = audit_proxy_metric_profile(
        args.proxy_metric_profile_manifest,
        getattr(args, "proxy_source_root", ROOT),
        getattr(args, "proxy_install_root", ROOT / "install"),
    )
    family_evidence = audit_missing_family_attestation_record(
        load_json(args.development_family_attestation)
    )
    real_status = read_status(args.real_status)
    expected_real_phase = getattr(
        args,
        "expected_real_phase",
        "completed_real_heldout_proxy_validation",
    )
    if real_status.get("phase") != expected_real_phase:
        raise ValueError("real proxy validation is not complete")
    selections = {
        "contest_heldout": audit_strict_selection(
            args.contest_selection,
            EXPECTED_PROXY_COMPARISONS["contest_heldout"],
            required_metric_profile="absolute_directional_v2",
        ),
        "real_development": audit_strict_selection(
            args.real_development_selection,
            EXPECTED_PROXY_COMPARISONS["real_development"],
            required_metric_profile="absolute_directional_v2",
        ),
        "real_heldout": audit_strict_selection(
            args.real_heldout_selection,
            EXPECTED_PROXY_COMPARISONS["real_heldout"],
            required_metric_profile="absolute_directional_v2",
        ),
    }
    selection_paths = {
        "contest_heldout": args.contest_selection,
        "real_development": args.real_development_selection,
        "real_heldout": args.real_heldout_selection,
    }
    resolution_evidence = {
        name: audit_proxy_resolution_evidence(
            selection_paths[name], selection, name,
            EXPECTED_PROXY_COMPARISONS[name],
            EXPECTED_PROXY_RESOLUTIONS[name],
        )
        for name, selection in selections.items()
    }
    method_sets = {
        name: set(selection["selected_methods"])
        for name, selection in selections.items()
    }
    if not method_sets["real_development"] <= method_sets["contest_heldout"]:
        raise ValueError("real development introduced a new contest method")
    if not method_sets["real_heldout"] <= method_sets["real_development"]:
        raise ValueError("real heldout introduced a new development method")

    frozen = load_json(args.frozen_presets)
    if not isinstance(frozen, dict):
        raise ValueError("frozen contest presets are not a dictionary")
    expected_frozen = {"hpwl"} | method_sets["contest_heldout"]
    if set(frozen) != expected_frozen:
        raise ValueError("frozen contest preset methods do not match selection")
    evaluated_method_sets = {
        name: set(record["methods"])
        for name, record in resolution_evidence.items()
    }
    if evaluated_method_sets["real_development"] != expected_frozen:
        raise ValueError(
            "real development evaluated methods outside contest admission"
        )
    expected_real_heldout = {"hpwl"} | method_sets["real_development"]
    if evaluated_method_sets["real_heldout"] != expected_real_heldout:
        raise ValueError(
            "real heldout evaluated methods outside development admission"
        )

    paths = {
        "contest_heldout": args.contest_selection,
        "real_development": args.real_development_selection,
        "real_heldout": args.real_heldout_selection,
        "frozen_presets": args.frozen_presets,
        "real_status": args.real_status,
        "proxy_metric_profile_manifest": args.proxy_metric_profile_manifest,
    }
    final_methods = ["hpwl"] + selections["real_heldout"]["selected_methods"]
    return {
        "schema_version": 1,
        "status": "passed",
        "stage": "proxy_chain",
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "numeric_backend_mixing": False,
        "max_primary_worst_regression": 0.0,
        "metric_profile": "absolute_directional_v2",
        "metric_profile_code": metric_profile,
        "proxy_resolution_evidence": resolution_evidence,
        "development_family_evidence": family_evidence,
        "final_methods": final_methods,
        "selection_methods": {
            name: selection["selected_methods"]
            for name, selection in selections.items()
        },
        "selection_content_sha256": {
            name: canonical_json_sha256(selection)
            for name, selection in selections.items()
        },
        "sha256": {
            **{name: sha256(path) for name, path in paths.items()},
            "development_family_attestation": sha256(
                args.development_family_attestation
            ),
            **{
                "proxy_resolution_raw:%s" % name: row["raw_sha256"]
                for name, row in resolution_evidence.items()
            },
        },
    }


def audit_no_candidate_proxy(args):
    metric_profile = audit_proxy_metric_profile(
        args.proxy_metric_profile_manifest,
        getattr(args, "proxy_source_root", ROOT),
        getattr(args, "proxy_install_root", ROOT / "install"),
    )
    family_evidence = audit_missing_family_attestation_record(
        load_json(args.development_family_attestation)
    )
    terminal_status = read_status(args.terminal_status)
    if terminal_status.get("phase") != args.terminal_phase:
        raise ValueError("terminal proxy status phase mismatch")
    if args.terminal_phase not in NO_CANDIDATE_SELECTION_SETS:
        raise ValueError("terminal proxy phase cannot prove no candidate")
    if not args.empty_selection:
        raise ValueError("no terminal empty proxy selection was supplied")

    selections = {}
    selection_paths = {}
    resolution_evidence = {}
    for spec in args.empty_selection:
        parts = spec.split("=", 2)
        if len(parts) != 3:
            raise ValueError("empty selection must be label=count=path")
        label, expected_text, path_text = parts
        if not label or label in selections:
            raise ValueError("empty selection labels must be unique")
        try:
            expected = int(expected_text)
        except ValueError:
            raise ValueError("empty selection comparison count is invalid")
        if expected <= 0:
            raise ValueError("empty selection comparison count must be positive")
        path = Path(path_text)
        selection = audit_strict_selection(
            path, expected, allow_empty=True,
            required_metric_profile="absolute_directional_v2",
        )
        if selection.get("selected_methods"):
            raise ValueError("terminal selection is not empty: %s" % label)
        selections[label] = selection
        selection_paths[label] = path
        if label not in EXPECTED_PROXY_RESOLUTIONS:
            raise ValueError("unknown proxy resolution stage: %s" % label)
        if expected != EXPECTED_PROXY_STAGE_COMPARISONS.get(label):
            raise ValueError(
                "empty selection comparison count differs for %s" % label
            )
        resolution_evidence[label] = audit_proxy_resolution_evidence(
            path, selection, label, expected,
            EXPECTED_PROXY_RESOLUTIONS[label]
        )

    if frozenset(selections) not in NO_CANDIDATE_SELECTION_SETS[
        args.terminal_phase
    ]:
        raise ValueError(
            "empty selections do not prove terminal phase %s"
            % args.terminal_phase
        )

    policy_v7_evidence = None
    policy_v7_path = getattr(args, "policy_v7_attestation", None)
    has_policy_v7_selection = POLICY_V7_STAGE in selections
    if has_policy_v7_selection:
        if policy_v7_path is None:
            raise ValueError("Policy V7 exhaustion lacks campaign attestation")
        policy_v7_evidence = audit_policy_v7_attestation_record(
            load_json(policy_v7_path)
        )
        selection_path = selection_paths[POLICY_V7_STAGE]
        if (
            policy_v7_evidence["sha256"]["selection"]
            != sha256(selection_path)
            or policy_v7_evidence["sha256"]["screening_raw"]
            != resolution_evidence[POLICY_V7_STAGE]["raw_sha256"]
            or policy_v7_evidence["selected_methods"]
            != selections[POLICY_V7_STAGE]["selected_methods"]
        ):
            raise ValueError("Policy V7 attestation binding mismatch")
    elif policy_v7_path is not None:
        raise ValueError("unexpected Policy V7 campaign attestation")

    openroad_status = read_status(args.openroad_status)
    if openroad_status.get("phase") != "completed_no_golden_candidate":
        raise ValueError("OpenROAD did not reject the empty proxy admission set")
    return {
        "schema_version": 1,
        "status": "passed",
        "stage": "no_candidate_proxy",
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "conclusion": "no_safe_proxy_candidate",
        "terminal_phase": args.terminal_phase,
        "terminal_empty_selections": sorted(selections),
        "final_methods": ["hpwl"],
        "numeric_backend_mixing": False,
        "max_primary_worst_regression": 0.0,
        "metric_profile": "absolute_directional_v2",
        "metric_profile_code": metric_profile,
        "proxy_resolution_evidence": resolution_evidence,
        "development_family_evidence": family_evidence,
        "policy_v7_evidence": policy_v7_evidence,
        "selection_content_sha256": {
            label: canonical_json_sha256(selection)
            for label, selection in selections.items()
        },
        "sha256": {
            "terminal_status": sha256(args.terminal_status),
            "openroad_status": sha256(args.openroad_status),
            "proxy_metric_profile_manifest": sha256(
                args.proxy_metric_profile_manifest
            ),
            "development_family_attestation": sha256(
                args.development_family_attestation
            ),
            **({
                "policy_v7_attestation": sha256(policy_v7_path),
            } if policy_v7_path is not None else {}),
            **{
                "selection:%s" % label: sha256(path)
                for label, path in selection_paths.items()
            },
            **{
                "proxy_resolution_raw:%s" % label: row["raw_sha256"]
                for label, row in resolution_evidence.items()
            },
        },
    }


def audit_no_candidate_final(args):
    proxy = load_json(args.proxy_attestation)
    if (
        proxy.get("status") != "passed"
        or proxy.get("stage") != "no_candidate_proxy"
        or proxy.get("final_methods") != ["hpwl"]
    ):
        raise ValueError("invalid no-candidate proxy attestation")
    audit_proxy_metric_profile_record(proxy)
    audit_missing_family_attestation_record(
        proxy.get("development_family_evidence", {})
    )
    audit_proxy_resolution_record(
        proxy, proxy.get("terminal_empty_selections", [])
    )
    if POLICY_V7_STAGE in proxy.get("terminal_empty_selections", []):
        audit_policy_v7_attestation_record(
            proxy.get("policy_v7_evidence", {})
        )
        if not valid_sha256(
            proxy.get("sha256", {}).get("policy_v7_attestation")
        ):
            raise ValueError("no-candidate proxy lacks Policy V7 binding")
    elif proxy.get("policy_v7_evidence") is not None:
        raise ValueError("unexpected Policy V7 evidence in proxy attestation")
    local_plugins = audit_local_plugin_attestation_record(
        load_json(args.local_plugin_attestation)
    )
    innovus_status = read_status(args.innovus_status)
    if innovus_status.get("phase") != "completed_no_golden_candidate":
        raise ValueError("Innovus did not reject the empty proxy admission set")
    return {
        "schema_version": 1,
        "status": "passed",
        "stage": "corrected_final",
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "conclusion": "no_safe_proxy_candidate",
        "recommended_methods": ["hpwl"],
        "final_methods": ["hpwl"],
        "golden_admission": "not_run_no_proxy_survivor",
        "numeric_backend_mixing": False,
        "numeric_metric_scalarization": False,
        "local_plugin_evidence": local_plugins,
        "sha256": {
            "proxy_attestation": sha256(args.proxy_attestation),
            "innovus_status": sha256(args.innovus_status),
            "local_plugin_attestation": sha256(
                args.local_plugin_attestation
            ),
        },
    }


def result_slot(root, path, result_name):
    parts = Path(path).relative_to(root).parts
    if (
        len(parts) != 7
        or not parts[1].startswith("seed_")
        or parts[2] != parts[0]
        or parts[3] != "methods"
        or parts[5] != "evaluation"
        or parts[6] != result_name
    ):
        raise ValueError("router result path does not match campaign layout")
    try:
        seed = int(parts[1][5:])
    except ValueError:
        raise ValueError("router result path has invalid seed")
    return parts[0], seed, parts[4]


def audit_router_results(root, backend, cases, seeds, methods):
    result_name = backend + ".json"
    paths = sorted(Path(root).glob("**/%s" % result_name))
    expected = {
        (case, seed, method)
        for case in cases for seed in seeds for method in methods
    }
    actual = [result_slot(root, path, result_name) for path in paths]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("%s routed result matrix coverage mismatch" % backend)

    evidence_hashes = {}
    for path, slot in zip(paths, actual):
        result = load_json(path)
        if not result_meets_resume_contract(
            {**result, "authoritative_for_comparison": True}, backend
        ):
            raise ValueError("%s result fails routed metric contract: %s" % (backend, path))
        relative = str(path.relative_to(root))
        artifacts = {}
        for name, artifact in sorted(result.get("artifacts", {}).items()):
            artifact_path = Path(artifact)
            if not artifact_path.is_file():
                raise ValueError("missing %s route artifact: %s" % (backend, artifact))
            artifacts[name] = sha256(artifact_path)
        evidence_hashes[relative] = {
            "slot": {"case": slot[0], "seed": slot[1], "method": slot[2]},
            "result_sha256": sha256(path),
            "artifact_sha256": artifacts,
        }
    return evidence_hashes


def audit_evaluator_activation(path, source_dir, installed_dir,
                               evaluator_hashes, source_audit):
    if path is None:
        raise ValueError("Innovus router audit requires evaluator activation evidence")
    activation = load_json(path)
    if (
        activation.get("status") != "passed"
        or set(activation.get("modules", {})) != EXPECTED_EVALUATOR_MODULES
        or Path(activation.get("source_dir", "")).resolve()
            != Path(source_dir).resolve()
        or Path(activation.get("installed_dir", "")).resolve()
            != Path(installed_dir).resolve()
    ):
        raise ValueError("invalid evaluator activation manifest")
    for name, expected_hash in evaluator_hashes.items():
        row = activation["modules"][name]
        if (
            row.get("source_sha256") != expected_hash
            or row.get("installed_after_sha256") != expected_hash
            or row.get("byte_identical") is not True
        ):
            raise ValueError("stale evaluator activation evidence: %s" % name)
    activation_hash = sha256(path)
    if source_audit.get("evaluator_activation_sha256") != activation_hash:
        raise ValueError("golden source audit has different activation evidence")
    return activation_hash


def audit_proxy_bound_plugin_identity(path, proxy_path, methods):
    attestation = load_json(path)
    hashes = attestation.get("plugin_sha256")
    if (
        attestation.get("status") != "passed"
        or attestation.get("stage") != "golden_router"
        or attestation.get("backend") != "openroad"
        or attestation.get("methods") != methods
        or attestation.get("source_install_plugins_match") is not True
        or attestation.get("sha256", {}).get("proxy_attestation")
        != sha256(proxy_path)
        or not isinstance(hashes, dict)
        or not hashes
        or any(not valid_sha256(value) for value in hashes.values())
    ):
        raise ValueError("invalid proxy-bound plugin identity attestation")
    return hashes, sha256(path)


def audit_router(args):
    proxy = load_json(args.proxy_attestation)
    if proxy.get("status") != "passed" or proxy.get("stage") != "proxy_chain":
        raise ValueError("invalid proxy-chain attestation")
    audit_proxy_metric_profile_record(proxy)
    audit_proxy_resolution_record(proxy, EXPECTED_PROXY_COMPARISONS)
    backend = args.backend
    cases = list(EXPECTED_GOLDEN_CASES[backend])
    seeds = list(EXPECTED_SEEDS)
    methods = proxy.get("final_methods", [])
    if len(methods) < 2 or methods[0] != "hpwl" or len(methods) != len(set(methods)):
        raise ValueError("proxy attestation has no valid golden candidate set")

    status = read_status(args.status)
    if status.get("phase") != "completed_%s_golden" % backend:
        raise ValueError("%s golden campaign is not complete" % backend)
    source_audit = load_json(args.source_audit)
    if (
        source_audit.get("status") != "passed"
        or source_audit.get("backend") != backend
        or source_audit.get("methods") != methods
        or source_audit.get("validated_comparisons") != len(cases) * len(seeds)
    ):
        raise ValueError("%s golden source audit mismatch" % backend)

    summary = load_json(args.summary)
    ranking = rank_campaigns(
        [summary], [str(Path(args.summary).resolve())],
        required_case_sets=[cases], required_seed_sets=[seeds],
    )
    if ranking.get("common_methods") != sorted(methods):
        raise ValueError("%s summary method set differs from proxy survivors" % backend)
    result_hashes = audit_router_results(
        args.campaign, backend, cases, seeds, methods
    )
    evaluator_hashes = audit_evaluator_identity(
        args.source_evaluator_dir, args.installed_evaluator_dir
    )
    activation_hash = None
    if backend == "innovus":
        activation_hash = audit_evaluator_activation(
            args.activation_manifest,
            args.source_evaluator_dir,
            args.installed_evaluator_dir,
            evaluator_hashes,
            source_audit,
        )
    plugin_identity_attestation = getattr(
        args, "proxy_plugin_identity_attestation", None
    )
    if plugin_identity_attestation is None:
        plugin_hashes = audit_plugin_identity(
            args.source_plugin_dir, args.installed_plugin_dir
        )
        plugin_identity_source = "local_source_install"
        plugin_identity_attestation_hash = None
    else:
        plugin_hashes, plugin_identity_attestation_hash = (
            audit_proxy_bound_plugin_identity(
                plugin_identity_attestation, args.proxy_attestation, methods
            )
        )
        plugin_identity_source = "proxy_bound_openroad_attestation"
    params_hash = audit_params_identity(args.source_params, args.installed_params)
    return {
        "schema_version": 1,
        "status": "passed",
        "stage": "golden_router",
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "backend": backend,
        "cases": cases,
        "seeds": seeds,
        "methods": methods,
        "validated_comparisons": len(cases) * len(seeds),
        "validated_results": len(result_hashes),
        "summary_content_sha256": canonical_json_sha256(summary),
        "proxy_final_selection_sha256": proxy["selection_content_sha256"][
            "real_heldout"
        ],
        "source_install_evaluators_match": True,
        "evaluator_sha256": evaluator_hashes,
        "evaluator_activation_sha256": activation_hash,
        "source_install_plugins_match": True,
        "plugin_identity_source": plugin_identity_source,
        "plugin_identity_attestation_sha256": (
            plugin_identity_attestation_hash
        ),
        "plugin_sha256": plugin_hashes,
        "source_install_params_match": True,
        "params_sha256": params_hash,
        "result_evidence": result_hashes,
        "sha256": {
            "proxy_attestation": sha256(args.proxy_attestation),
            "summary": sha256(args.summary),
            "source_audit": sha256(args.source_audit),
            "status": sha256(args.status),
            **({
                "proxy_plugin_identity_attestation": (
                    plugin_identity_attestation_hash
                ),
            } if plugin_identity_attestation_hash is not None else {}),
        },
    }


def audit_final(args):
    proxy = load_json(args.proxy_attestation)
    final_methods = proxy.get("final_methods")
    selection_hash = proxy.get("selection_content_sha256", {}).get("real_heldout")
    if (
        proxy.get("status") != "passed"
        or proxy.get("stage") != "proxy_chain"
        or not isinstance(final_methods, list)
        or len(final_methods) < 2
        or final_methods[0] != "hpwl"
        or len(final_methods) != len(set(final_methods))
        or not isinstance(selection_hash, str)
        or not selection_hash
    ):
        raise ValueError("invalid proxy-chain attestation")
    audit_proxy_metric_profile_record(proxy)
    audit_missing_family_attestation_record(
        proxy.get("development_family_evidence", {})
    )
    audit_proxy_resolution_record(proxy, EXPECTED_PROXY_COMPARISONS)
    local_plugins = audit_local_plugin_attestation_record(
        load_json(args.local_plugin_attestation)
    )

    router_attestations = [
        load_json(args.openroad_attestation),
        load_json(args.innovus_attestation),
    ]
    by_backend = {row.get("backend"): row for row in router_attestations}
    if (
        len(by_backend) != len(router_attestations)
        or set(by_backend) != {"openroad", "innovus"}
    ):
        raise ValueError("final audit requires one attestation per golden backend")
    proxy_hash = sha256(args.proxy_attestation)
    for backend, attestation in by_backend.items():
        expected_cases = list(EXPECTED_GOLDEN_CASES[backend])
        expected_seeds = list(EXPECTED_SEEDS)
        expected_comparisons = len(expected_cases) * len(expected_seeds)
        expected_results = expected_comparisons * len(final_methods)
        if (
            attestation.get("status") != "passed"
            or attestation.get("stage") != "golden_router"
            or attestation.get("backend") != backend
        ):
            raise ValueError("%s router attestation did not pass" % backend)
        if attestation.get("methods") != final_methods:
            raise ValueError("golden router method sets differ")
        if (
            attestation.get("cases") != expected_cases
            or attestation.get("seeds") != expected_seeds
            or attestation.get("validated_comparisons") != expected_comparisons
            or attestation.get("validated_results") != expected_results
            or len(attestation.get("result_evidence", {})) != expected_results
        ):
            raise ValueError("%s router attestation matrix mismatch" % backend)
        if attestation.get("proxy_final_selection_sha256") != selection_hash:
            raise ValueError("golden router used a different proxy selection")
        if attestation.get("sha256", {}).get("proxy_attestation") != proxy_hash:
            raise ValueError("%s router attestation is bound to a different proxy" % backend)

    summary_paths = [args.openroad_summary, args.innovus_summary]
    summaries = [load_json(path) for path in summary_paths]
    for backend, path, summary in zip(
        ("openroad", "innovus"), summary_paths, summaries
    ):
        attestation = by_backend[backend]
        if (
            canonical_json_sha256(summary)
            != attestation.get("summary_content_sha256")
            or sha256(path) != attestation.get("sha256", {}).get("summary")
        ):
            raise ValueError("%s summary changed after router attestation" % backend)
    ranking = rank_campaigns(
        summaries,
        [str(Path(path).resolve()) for path in summary_paths],
        required_case_sets=[
            by_backend["openroad"]["cases"], by_backend["innovus"]["cases"]
        ],
        required_seed_sets=[
            by_backend["openroad"]["seeds"], by_backend["innovus"]["seeds"]
        ],
    )
    stored_ranking = load_json(args.ranking)
    if stored_ranking != ranking:
        raise ValueError("stored golden ranking does not match recomputation")
    if Path(args.report).read_text() != render_report(ranking):
        raise ValueError("stored golden ranking report does not match recomputation")
    alternatives = [
        method for method in ranking["recommended_methods"] if method != "hpwl"
    ]
    conclusion = (
        "robust_golden_winner" if alternatives else "no_safe_golden_candidate"
    )
    return {
        "schema_version": 1,
        "status": "passed",
        "stage": "corrected_final",
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "conclusion": conclusion,
        "recommended_methods": ranking["recommended_methods"],
        "robust_routability_winners": ranking["robust_routability_winners"],
        "numeric_backend_mixing": False,
        "numeric_metric_scalarization": False,
        "golden_backends": ["openroad", "innovus"],
        "final_methods": final_methods,
        "local_plugin_evidence": local_plugins,
        "sha256": {
            "proxy_attestation": sha256(args.proxy_attestation),
            "openroad_attestation": sha256(args.openroad_attestation),
            "innovus_attestation": sha256(args.innovus_attestation),
            "openroad_summary": sha256(args.openroad_summary),
            "innovus_summary": sha256(args.innovus_summary),
            "ranking": sha256(args.ranking),
            "report": sha256(args.report),
            "local_plugin_attestation": sha256(
                args.local_plugin_attestation
            ),
        },
    }


def add_code_identity_arguments(parser):
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
        "--source-params", type=Path, default=Path("dreamplace/params.json")
    )
    parser.add_argument(
        "--installed-params", type=Path, default=Path("install/dreamplace/params.json")
    )


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    proxy = subparsers.add_parser("proxy", help="audit the strict proxy chain")
    proxy.add_argument("--contest-selection", type=Path, required=True)
    proxy.add_argument("--real-development-selection", type=Path, required=True)
    proxy.add_argument("--real-heldout-selection", type=Path, required=True)
    proxy.add_argument("--frozen-presets", type=Path, required=True)
    proxy.add_argument("--real-status", type=Path, required=True)
    proxy.add_argument(
        "--expected-real-phase",
        default="completed_real_heldout_proxy_validation",
    )
    proxy.add_argument(
        "--proxy-metric-profile-manifest", type=Path, required=True
    )
    proxy.add_argument(
        "--development-family-attestation", type=Path, required=True
    )
    proxy.add_argument("--output", type=Path, required=True)

    no_candidate_proxy = subparsers.add_parser(
        "no-candidate-proxy", help="audit terminal strict proxy exhaustion"
    )
    no_candidate_proxy.add_argument(
        "--empty-selection", action="append", required=True,
        help="label=expected_comparisons=survivors.json",
    )
    no_candidate_proxy.add_argument("--terminal-status", type=Path, required=True)
    no_candidate_proxy.add_argument("--terminal-phase", required=True)
    no_candidate_proxy.add_argument("--openroad-status", type=Path, required=True)
    no_candidate_proxy.add_argument(
        "--proxy-metric-profile-manifest", type=Path, required=True
    )
    no_candidate_proxy.add_argument(
        "--development-family-attestation", type=Path, required=True
    )
    no_candidate_proxy.add_argument("--policy-v7-attestation", type=Path)
    no_candidate_proxy.add_argument("--output", type=Path, required=True)

    router = subparsers.add_parser("router", help="audit one golden router")
    router.add_argument("--backend", choices=("openroad", "innovus"), required=True)
    router.add_argument("--proxy-attestation", type=Path, required=True)
    router.add_argument("--campaign", type=Path, required=True)
    router.add_argument("--summary", type=Path, required=True)
    router.add_argument("--source-audit", type=Path, required=True)
    router.add_argument("--activation-manifest", type=Path)
    router.add_argument(
        "--proxy-plugin-identity-attestation", type=Path,
        help="reuse the proxy-bound OpenROAD plugin identity for Innovus",
    )
    router.add_argument("--status", type=Path, required=True)
    router.add_argument("--output", type=Path, required=True)
    add_code_identity_arguments(router)

    final = subparsers.add_parser("final", help="combine golden attestations")
    final.add_argument("--proxy-attestation", type=Path, required=True)
    final.add_argument("--openroad-attestation", type=Path, required=True)
    final.add_argument("--innovus-attestation", type=Path, required=True)
    final.add_argument("--openroad-summary", type=Path, required=True)
    final.add_argument("--innovus-summary", type=Path, required=True)
    final.add_argument("--ranking", type=Path, required=True)
    final.add_argument("--report", type=Path, required=True)
    final.add_argument(
        "--local-plugin-attestation", type=Path, required=True
    )
    final.add_argument("--output", type=Path, required=True)

    no_candidate_final = subparsers.add_parser(
        "no-candidate-final", help="bind both golden admission refusals"
    )
    no_candidate_final.add_argument(
        "--proxy-attestation", type=Path, required=True
    )
    no_candidate_final.add_argument("--innovus-status", type=Path, required=True)
    no_candidate_final.add_argument(
        "--local-plugin-attestation", type=Path, required=True
    )
    no_candidate_final.add_argument("--output", type=Path, required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "proxy":
        result = audit_proxy_chain(args)
    elif args.command == "no-candidate-proxy":
        result = audit_no_candidate_proxy(args)
    elif args.command == "router":
        result = audit_router(args)
    elif args.command == "final":
        result = audit_final(args)
    else:
        result = audit_no_candidate_final(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
