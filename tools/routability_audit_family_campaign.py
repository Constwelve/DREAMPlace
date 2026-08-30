#!/usr/bin/env python3
"""Audit corrected development evidence for previously missing plugin families."""

import argparse
import datetime
import json
from pathlib import Path


from tools.routability_audit_corrected import (
    EXPECTED_PROXY_RESOLUTIONS,
    MISSING_FAMILY_ACTIVATION_THRESHOLDS,
    MISSING_FAMILY_STAGE,
    MISSING_FAMILY_TUNING_KEYS,
    MISSING_FAMILY_VARIANT_COUNT,
    REQUIRED_MISSING_FAMILIES,
    audit_missing_family_attestation_record,
    audit_proxy_resolution_evidence,
    audit_strict_selection,
    canonical_json_sha256,
    sha256,
)
from tools.routability_summarize import (
    campaign_identity,
)
from tools.routability_merge_source_campaigns import (
    audit_method_campaign_activation,
    resolve_activation_evidence,
)


STAGE_LABEL = MISSING_FAMILY_STAGE
REQUIRED_FAMILIES = REQUIRED_MISSING_FAMILIES
EXPECTED_CASE_SEEDS = tuple(
    (case, seed)
    for case in ("data_ispd19_test1", "data_ispd19_test2")
    for seed in (1000, 2000, 3000)
)


def load_json(path):
    return json.loads(Path(path).read_text())


def audit_family_manifest(presets, manifest,
                          required_families=REQUIRED_FAMILIES):
    if manifest.get("schema_version") != 1:
        raise ValueError("family manifest schema is not 1")
    if manifest.get("heldout_or_golden_evidence_used") is not False:
        raise ValueError("family tuning is not development-only")
    if manifest.get("numeric_backend_mixing") is not False:
        raise ValueError("family tuning mixes backend metrics")
    required = list(required_families)
    if manifest.get("required_families") != required:
        raise ValueError("family manifest required-family coverage mismatch")
    generated = manifest.get("generated")
    if not isinstance(generated, dict) or not generated:
        raise ValueError("family manifest has no generated variants")
    if set(presets) != {"hpwl"} | set(generated):
        raise ValueError("family presets and manifest method sets differ")

    coverage = {family: [] for family in required}
    for method, provenance in generated.items():
        family = provenance.get("family")
        config = presets[method]
        if (
            family not in coverage
            or provenance.get("plugins") != [family]
            or config.get("ruplace_plugins") != [family]
            or config.get("ruplace_proxy") != provenance.get("proxy")
            or provenance.get("development_only") is not True
        ):
            raise ValueError("invalid family provenance for %s" % method)
        if family == "routeforce" and (
            config.get("ruplace_proxy") not in ("gpugr", "xplace")
            or int(config.get("ruplace_external_route_eval", 1)) != 0
        ):
            raise ValueError("routeforce is not configured for in-process routing")
        coverage[family].append(method)
    if any(not methods for methods in coverage.values()):
        raise ValueError("one or more required families have no variants")
    return {family: sorted(methods) for family, methods in coverage.items()}


audit_family_attestation_record = audit_missing_family_attestation_record


def distinct_parameter_values(configs, key):
    values = {}
    for config in configs:
        value = config.get(key)
        values[json.dumps(value, sort_keys=True)] = value
    return [values[name] for name in sorted(values)]


def audit_family_tuning_coverage(presets, coverage):
    result = {}
    for family in REQUIRED_FAMILIES:
        methods = coverage[family]
        configs = [presets[method] for method in methods]
        if len(configs) != MISSING_FAMILY_VARIANT_COUNT:
            raise ValueError(
                "%s requires exactly %d tuning variants" % (
                    family, MISSING_FAMILY_VARIANT_COUNT
                )
            )
        threshold_key = (
            "ruplace_plugin_start_overflow"
            if family == "routeforce"
            else "ruplace_inflate_start_overflow"
        )
        thresholds = distinct_parameter_values(configs, threshold_key)
        if thresholds != list(MISSING_FAMILY_ACTIVATION_THRESHOLDS):
            raise ValueError("%s activation-threshold coverage mismatch" % family)
        parameter_values = {
            key: distinct_parameter_values(configs, key)
            for key in sorted({key for config in configs for key in config})
        }
        varied = sorted(
            key for key, values in parameter_values.items() if len(values) > 1
        )
        missing = set(MISSING_FAMILY_TUNING_KEYS[family]) - set(varied)
        if missing:
            raise ValueError(
                "%s does not vary required tuning keys: %s" % (
                    family, ", ".join(sorted(missing))
                )
            )
        result[family] = {
            "variant_count": len(configs),
            "activation_threshold_key": threshold_key,
            "activation_thresholds": thresholds,
            "varied_parameter_keys": varied,
            "parameter_values": {
                key: parameter_values[key] for key in varied
            },
        }
    return result


def audit_campaign(args):
    campaign = args.campaign.resolve()
    presets = load_json(args.presets)
    manifest = load_json(args.manifest)
    coverage = audit_family_manifest(presets, manifest)
    tuning_coverage = audit_family_tuning_coverage(presets, coverage)
    selection = audit_strict_selection(
        args.selection,
        expected_comparisons=len(EXPECTED_CASE_SEEDS),
        allow_empty=True,
        required_metric_profile="absolute_directional_v2",
    )
    resolution = audit_proxy_resolution_evidence(
        args.selection,
        selection,
        STAGE_LABEL,
        len(EXPECTED_CASE_SEEDS),
        EXPECTED_PROXY_RESOLUTIONS[STAGE_LABEL],
    )
    evaluated_methods = set(resolution["methods"])
    if evaluated_methods != set(presets):
        raise ValueError("family campaign did not evaluate the frozen preset set")
    selected = set(selection["selected_methods"])
    if not selected <= set(manifest["generated"]):
        raise ValueError("family selection contains an unknown method")

    activation_audit = audit_method_campaign_activation(
        campaign, EXPECTED_CASE_SEEDS
    )
    excluded_methods = {
        row["method"] for row in activation_audit["inactive_methods"]
    }
    if "hpwl" in excluded_methods:
        raise ValueError("family campaign baseline failed activation provenance")
    retained_methods = set(manifest["generated"]) - excluded_methods
    retained_coverage = {
        family: sorted(set(methods) & retained_methods)
        for family, methods in coverage.items()
    }
    empty_families = [
        family for family, methods in retained_coverage.items() if not methods
    ]
    if empty_families:
        raise ValueError(
            "inactive variants removed every method for families: %s"
            % ", ".join(empty_families)
        )
    if selected & excluded_methods:
        raise ValueError("family selection contains an inactive method")

    comparisons = {}
    for path in sorted(campaign.rglob("comparison.json")):
        key = campaign_identity(path, campaign)
        if key in comparisons:
            raise ValueError("family campaign has a duplicate comparison")
        comparisons[key] = path
    if set(comparisons) != set(EXPECTED_CASE_SEEDS):
        raise ValueError("family campaign case/seed coverage mismatch")

    retained_activation_slots = set()
    evaluation_slots = set()
    expected_resolution = tuple(EXPECTED_PROXY_RESOLUTIONS[STAGE_LABEL])
    for (case, seed), comparison_path in sorted(comparisons.items()):
        comparison = load_json(comparison_path)
        if comparison.get("validation", {}).get("status") != "validated":
            raise ValueError("family comparison is not validated")
        placements = comparison.get("placements", [])
        by_method = {row.get("method"): row for row in placements}
        if None in by_method or len(by_method) != len(placements):
            raise ValueError("family comparison has invalid placement methods")
        if set(by_method) != set(presets):
            raise ValueError("family comparison method coverage mismatch")
        for method in presets:
            method_dir = comparison_path.parent / method
            config = load_json(method_dir / "config.json")
            if any(config.get(key) != value for key, value in presets[method].items()):
                raise ValueError("family config differs from preset: %s" % method)
            if (
                config.get("route_num_bins_x"), config.get("route_num_bins_y")
            ) != expected_resolution or (
                config.get("routability_eval_route_x_size"),
                config.get("routability_eval_route_y_size"),
            ) != expected_resolution:
                raise ValueError("family config resolution mismatch: %s" % method)
            evidence = resolve_activation_evidence(
                by_method[method], config, method_dir
            )
            if method in retained_methods:
                if evidence["error"]:
                    raise ValueError(
                        "retained plugin activation contract: %s"
                        % evidence["error"]
                    )
                retained_activation_slots.add((case, seed, method))

            results = load_json(method_dir / "evaluation" / "summary.json").get(
                "results", []
            )
            by_backend = {row.get("backend"): row for row in results}
            if set(by_backend) != {"rudy", "gpugr"}:
                raise ValueError("family evaluator backend coverage mismatch")
            for backend, result in by_backend.items():
                metrics = result.get("metrics", {})
                if (
                    result.get("status") != "ok"
                    or (metrics.get("route_x_size"), metrics.get("route_y_size"))
                    != expected_resolution
                ):
                    raise ValueError("family evaluator result contract mismatch")
                evaluation_slots.add((case, seed, method, backend))

    expected_retained_activations = (
        len(EXPECTED_CASE_SEEDS) * len(retained_methods)
    )
    if len(retained_activation_slots) != expected_retained_activations:
        raise ValueError("retained family activation slot count mismatch")
    expected_evaluations = len(EXPECTED_CASE_SEEDS) * len(presets) * 2
    if len(evaluation_slots) != expected_evaluations:
        raise ValueError("family evaluation slot count mismatch")

    result = {
        "schema_version": 1,
        "status": "passed",
        "stage": STAGE_LABEL,
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "metric_profile": "absolute_directional_v2",
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "required_families": list(REQUIRED_FAMILIES),
        "family_methods": coverage,
        "retained_family_methods": retained_coverage,
        "activation_contract": (
            "every retained plugin is active on every development case/seed"
        ),
        "activation_audit": activation_audit,
        "excluded_inactive_methods": activation_audit["inactive_methods"],
        "tuning_coverage": tuning_coverage,
        "evaluated_methods": sorted(presets),
        "selected_methods": selection["selected_methods"],
        "validated_case_seeds": [
            {"case": case, "seed": seed} for case, seed in EXPECTED_CASE_SEEDS
        ],
        "reported_resolution": list(expected_resolution),
        "validated_retained_placements": len(retained_activation_slots),
        "validated_proxy_results": len(evaluation_slots),
        "selection_content_sha256": canonical_json_sha256(selection),
        "sha256": {
            "presets": sha256(args.presets),
            "manifest": sha256(args.manifest),
            "selection": sha256(args.selection),
            "screening_raw": resolution["raw_sha256"],
        },
    }
    return audit_family_attestation_record(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--presets", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_campaign(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
