#!/usr/bin/env python3
"""Merge completed placement campaigns for frozen evaluator replays."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_parallel import utc_now
from tools.routability_compare import (
    find_placed_def,
    parse_plugin_summaries,
    placement_output_name,
)
from tools.routability_summarize import (
    campaign_gate,
    campaign_identity,
    normalized_plugin_names,
    placement_plugin_activation_error,
)


METHOD_UNION_SCHEMA_VERSION = 1
ACTIVATION_AUDIT_SCHEMA_VERSION = 1
ATOMIC_PLUGINS = (
    "local_gradient",
    "net_overlap",
    "net_weighting",
    "poisson_force",
    "whitespace",
)
BASELINE_EVALUATOR_GRID_FIELDS = (
    ("routability_eval_route_x_size", "route_num_bins_x"),
    ("routability_eval_route_y_size", "route_num_bins_y"),
)
BASELINE_PIPELINE_COUNTERS = (
    "area_calls",
    "area_gate_skips",
    "gradient_calls",
    "gradient_gate_skips",
    "objective_calls",
    "objective_gate_skips",
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha256(value):
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def write_frozen_json(path, value):
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_text() != text:
            raise ValueError("frozen output changed: %s" % path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def materialize_file(source, destination):
    source = source.resolve()
    if not source.is_file():
        raise ValueError("source artifact is not a file: %s" % source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(source)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError("frozen artifact is not a regular file: %s" % destination)
        if sha256(destination) != source_hash:
            raise ValueError("frozen artifact changed: %s" % destination)
        return "hardlink" if os.path.samefile(source, destination) else "copy"
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def canonical_baseline_config(config, method="hpwl"):
    result = dict(config)
    result_dir = result.get("result_dir")
    if not result_dir:
        raise ValueError("%s baseline config lacks result_dir" % method)
    path = Path(result_dir)
    if path.name != "placement" or path.parent.name != method:
        raise ValueError(
            "%s baseline result_dir does not end in %s/placement: %s"
            % (method, method, result_dir)
        )
    result["result_dir"] = "<CAMPAIGN>/%s/placement" % method
    for evaluator_field, placement_field in BASELINE_EVALUATOR_GRID_FIELDS:
        if evaluator_field not in result:
            continue
        try:
            evaluator_size = int(result[evaluator_field])
            placement_size = int(result[placement_field])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "%s baseline evaluator grid lacks matching placement grid: %s"
                % (method, evaluator_field)
            )
        if evaluator_size != placement_size:
            raise ValueError(
                "%s baseline evaluator grid differs from placement grid: %s"
                % (method, evaluator_field)
            )
        del result[evaluator_field]
    return result


def placement_without_runtime(placement):
    return {
        key: value for key, value in placement.items()
        if key != "runtime_sec"
    }


def canonical_baseline_placement(placement):
    result = placement_without_runtime(placement)
    if (
        result.get("routability_plugin_selected") not in (None, "")
        or result.get("routability_plugin_status") != "not_selected"
        or result.get("routability_plugin_attempts", 0) != 0
        or result.get("routability_plugin_activations", 0) != 0
    ):
        raise ValueError("hpwl baseline placement selected a routability plugin")
    summary = result.get("routability_plugin_summary")
    if (
        not isinstance(summary, dict)
        or not set(summary) <= {"pipeline", "plugins"}
        or summary.get("plugins") != {}
    ):
        raise ValueError("hpwl baseline has invalid plugin summary")
    pipeline = summary.get("pipeline", {})
    if (
        not isinstance(pipeline, dict)
        or not set(pipeline) <= set(BASELINE_PIPELINE_COUNTERS)
        or any(pipeline.get(name, 0) != 0 for name in BASELINE_PIPELINE_COUNTERS)
    ):
        raise ValueError("hpwl baseline has nonzero or unknown pipeline counters")
    result["routability_plugin_summary"] = {
        "pipeline": {name: 0 for name in BASELINE_PIPELINE_COUNTERS},
        "plugins": {},
    }
    return result


def resolve_activation_evidence(placement, config, method_dir):
    """Prefer complete placement-log counters when comparison evidence is stale."""
    placement = dict(placement)
    comparison_error = placement_plugin_activation_error(placement, config)
    result = {
        "placement": placement,
        "source": "comparison",
        "log": None,
        "comparison_error": comparison_error,
        "error": comparison_error,
    }
    if not comparison_error:
        return result
    log_path = method_dir / "placement.log"
    if not log_path.is_file():
        return result
    recovered = dict(placement)
    recovered.update(parse_plugin_summaries(log_path.read_text(errors="replace")))
    result.update({
        "placement": recovered,
        "source": "placement_log",
        "log": log_path.resolve(),
        "error": placement_plugin_activation_error(recovered, config),
    })
    return result


def activation_failure_reason(placement, config):
    """Classify an inactive placement without relaxing the activation contract."""
    if placement.get("status") != "ok":
        return "placement_failed"
    expected = normalized_plugin_names(config.get("ruplace_plugins"))
    if not expected:
        return "baseline_provenance_error"
    summary = placement.get("routability_plugin_summary")
    plugins = summary.get("plugins", {}) if isinstance(summary, dict) else {}
    selected = [plugins.get(name, {}) for name in expected]
    attempts = sum(int(row.get("attempts", 0)) for row in selected)
    if attempts == 0:
        return "plugin_not_reached"
    metric_stats = {
        metric: values
        for row in selected
        for metric, values in row.get("metric_stats", {}).items()
        if isinstance(values, dict)
    }
    scheduled = metric_stats.get("force_schedule_applied")
    if scheduled is not None and int(scheduled.get("nonzero_count", 0)) == 0:
        return "force_not_scheduled"
    for metric in ("field_norm", "field_rms"):
        values = metric_stats.get(metric)
        if values is not None and int(values.get("nonzero_count", 0)) == 0:
            return "zero_congestion_field"
    reference = metric_stats.get("reference_rms")
    if reference is not None and int(reference.get("nonzero_count", 0)) == 0:
        return "zero_reference_gradient"
    applied = metric_stats.get("applied_scale")
    if applied is not None and int(applied.get("nonzero_count", 0)) == 0:
        return "zero_applied_scale"
    return "attempted_no_change"


def campaign_layout(root, expected_case_seeds):
    """Validate campaign completion and return its comparisons and method order."""
    root = root.resolve()
    status_path = root / "parallel_status.json"
    if not status_path.is_file():
        raise ValueError("source campaign lacks parallel_status.json: %s" % root)
    status = json.loads(status_path.read_text())
    jobs = status.get("jobs", [])
    job_keys = [(str(row["case"]), int(row["seed"])) for row in jobs]
    if len(job_keys) != len(set(job_keys)):
        raise ValueError("source campaign has duplicate parallel jobs: %s" % root)
    if set(job_keys) != set(expected_case_seeds):
        raise ValueError("source campaign case/seed scope differs: %s" % root)
    for row in jobs:
        if row.get("status") != "completed" or row.get("returncode") != 0:
            raise ValueError(
                "source campaign has incomplete job %s seed %s"
                % (row.get("case"), row.get("seed"))
            )

    comparisons = {}
    for path in sorted(root.rglob("comparison.json")):
        key = campaign_identity(path, root)
        if key in comparisons:
            raise ValueError("source campaign duplicates %s seed %d" % key)
        comparisons[key] = path.resolve()
    if set(comparisons) != set(expected_case_seeds):
        raise ValueError("source campaign comparison scope differs: %s" % root)

    method_order = None
    for key in sorted(comparisons):
        comparison = comparisons[key]
        data = json.loads(comparison.read_text())
        if data.get("validation", {}).get("status") != "validated":
            raise ValueError("source comparison is not validated: %s" % comparison)
        placements = data.get("placements", [])
        names = [row.get("method") for row in placements]
        if not names or None in names or len(names) != len(set(names)):
            raise ValueError("source comparison has invalid placement methods: %s" % comparison)
        if method_order is None:
            method_order = names
        elif set(names) != set(method_order):
            raise ValueError("source campaign method coverage differs: %s" % comparison)
    return {
        "root": root,
        "status": status_path.resolve(),
        "comparisons": comparisons,
        "method_order": method_order,
    }


def audit_method_campaign_activation(root, expected_case_seeds):
    """Inventory activation for every method and every development case/seed."""
    layout = campaign_layout(root, expected_case_seeds)
    rows = []
    for (case, seed), comparison in sorted(layout["comparisons"].items()):
        data = json.loads(comparison.read_text())
        placements = data.get("placements", [])
        indexed = {row["method"]: row for row in placements}
        for method in layout["method_order"]:
            method_dir = comparison.parent / method
            config_path = method_dir / "config.json"
            try:
                config = json.loads(config_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("source config is unavailable: %s: %s" % (
                    config_path, error
                ))
            evidence = resolve_activation_evidence(indexed[method], config, method_dir)
            placement = evidence["placement"]
            plugins = normalized_plugin_names(config.get("ruplace_plugins"))
            summary = placement.get("routability_plugin_summary")
            plugin_stats = summary.get("plugins", {}) if isinstance(summary, dict) else {}
            row = {
                "case": case,
                "seed": seed,
                "method": method,
                "plugins": list(plugins),
                "proxy": config.get("ruplace_proxy"),
                "plugin_start_overflow": config.get("ruplace_plugin_start_overflow"),
                "inflate_start_overflow": config.get("ruplace_inflate_start_overflow"),
                "density_overflow": indexed[method].get("density_overflow"),
                "attempts": placement.get("routability_plugin_attempts", 0),
                "activations": placement.get("routability_plugin_activations", 0),
                "status": placement.get("routability_plugin_status", "missing"),
                "evidence_source": evidence["source"],
                "comparison_error": evidence["comparison_error"],
                "activation_error": evidence["error"],
                "reason": (
                    activation_failure_reason(placement, config)
                    if evidence["error"] else "active"
                ),
                "pipeline": (
                    summary.get("pipeline", {}) if isinstance(summary, dict) else {}
                ),
                "plugin_stats": plugin_stats,
            }
            rows.append(row)

    selected_rows = [row for row in rows if row["plugins"]]
    inactive_rows = [row for row in selected_rows if row["activation_error"]]
    recovered_rows = [
        row for row in selected_rows
        if row["evidence_source"] == "placement_log" and not row["activation_error"]
    ]
    inactive_methods = []
    for method in sorted({row["method"] for row in inactive_rows}):
        affected = [row for row in inactive_rows if row["method"] == method]
        inactive_methods.append({
            "method": method,
            "plugins": affected[0]["plugins"],
            "proxy": affected[0]["proxy"],
            "affected_case_seeds": [
                {key: row[key] for key in (
                    "case", "seed", "reason", "activation_error", "attempts",
                    "activations", "density_overflow", "plugin_start_overflow",
                    "inflate_start_overflow",
                )}
                for row in affected
            ],
        })
    return {
        "schema_version": ACTIVATION_AUDIT_SCHEMA_VERSION,
        "status": "passed" if not inactive_rows else "inactive_methods",
        "campaign": str(layout["root"]),
        "case_seed_count": len(layout["comparisons"]),
        "method_count": len(layout["method_order"]),
        "placement_count": len(rows),
        "selected_placement_count": len(selected_rows),
        "active_selected_placement_count": len(selected_rows) - len(inactive_rows),
        "recovered_placement_count": len(recovered_rows),
        "inactive_placement_count": len(inactive_rows),
        "inactive_method_count": len(inactive_methods),
        "inactive_methods": inactive_methods,
        "inactive_placements": inactive_rows,
        "recovered_placements": recovered_rows,
    }


def discover_strict_method_campaign(root, expected_case_seeds,
                                    excluded_methods=()):
    layout = campaign_layout(root, expected_case_seeds)
    excluded_methods = set(excluded_methods)
    unknown = excluded_methods - set(layout["method_order"])
    if unknown:
        raise ValueError("excluded methods are absent from source campaign: %s" % (
            ", ".join(sorted(unknown))
        ))
    if "hpwl" in excluded_methods:
        raise ValueError("baseline hpwl cannot be excluded")
    method_order = [
        method for method in layout["method_order"] if method not in excluded_methods
    ]
    records = {}
    for key, comparison in sorted(layout["comparisons"].items()):
        data = json.loads(comparison.read_text())
        indexed = {row["method"]: row for row in data["placements"]}
        method_records = {}
        for method in method_order:
            method_dir = comparison.parent / method
            config_path = method_dir / "config.json"
            try:
                config = json.loads(config_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("source config is unavailable: %s: %s" % (
                    config_path, error
                ))
            evidence = resolve_activation_evidence(indexed[method], config, method_dir)
            placement = evidence["placement"]
            activation_error = evidence["error"]
            if activation_error:
                raise ValueError("inactive plugin placement: %s" % activation_error)
            try:
                placed_def = find_placed_def(
                    method_dir / "placement", placement_output_name(config)
                ).resolve()
            except (FileNotFoundError, RuntimeError, ValueError) as error:
                raise ValueError("source placement is unavailable: %s: %s" % (
                    method_dir, error
                ))
            method_records[method] = {
                "placement": placement,
                "config": config,
                "config_path": config_path.resolve(),
                "placed_def": placed_def,
                "activation_source": evidence["source"],
                "activation_log": evidence["log"],
            }
        records[key] = {
            "comparison": comparison,
            "comparison_data": data,
            "methods": method_records,
        }
    return {
        "root": layout["root"],
        "status": layout["status"],
        "method_order": method_order,
        "records": records,
        "excluded_methods": sorted(excluded_methods),
    }


def load_preset_bundle(presets_path, manifest_path, campaign,
                       excluded_methods=()):
    presets_path = presets_path.resolve()
    manifest_path = manifest_path.resolve()
    presets = json.loads(presets_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    methods = set(campaign["method_order"])
    excluded_methods = set(excluded_methods)
    if set(presets) != methods | excluded_methods:
        raise ValueError("preset methods differ from source campaign: %s" % presets_path)
    if "hpwl" not in presets:
        raise ValueError("source presets lack hpwl: %s" % presets_path)
    generated = manifest.get("generated")
    if (
        not isinstance(generated, dict)
        or set(generated) != (methods | excluded_methods) - {"hpwl"}
    ):
        raise ValueError("preset manifest coverage differs: %s" % manifest_path)

    presets = {
        method: preset for method, preset in presets.items()
        if method not in excluded_methods
    }
    generated = {
        method: provenance for method, provenance in generated.items()
        if method not in excluded_methods
    }

    for record in campaign["records"].values():
        for method, preset in presets.items():
            config = record["methods"][method]["config"]
            mismatched = [
                key for key, value in preset.items() if config.get(key) != value
            ]
            if mismatched:
                raise ValueError(
                    "source config differs from preset for %s: %s"
                    % (method, ", ".join(sorted(mismatched)))
                )

    coverage = {}
    for method, provenance in generated.items():
        plugins = normalized_plugin_names(provenance.get("plugins"))
        if len(plugins) != 1:
            raise ValueError("method is not an atomic plugin: %s" % method)
        proxy = provenance.get("proxy")
        if proxy not in ("rudy", "gpugr"):
            raise ValueError("method has invalid proxy provenance: %s" % method)
        config = presets[method]
        configured_plugins = normalized_plugin_names(config.get("ruplace_plugins"))
        if configured_plugins != plugins or config.get("ruplace_proxy") != proxy:
            raise ValueError("preset and manifest provenance differ: %s" % method)
        coverage.setdefault(plugins[0], set()).add(proxy)
    return {
        "presets_path": presets_path,
        "manifest_path": manifest_path,
        "presets": presets,
        "manifest": {**manifest, "generated": generated},
        "coverage": coverage,
        "excluded_methods": sorted(excluded_methods),
    }


def union_method_campaigns(source_roots, source_preset_paths,
                           source_manifest_paths, output_root, output_presets,
                           expected_case_seeds, expected_method_count=None,
                           required_plugins=ATOMIC_PLUGINS,
                           exclude_inactive_methods=False,
                           activation_audit_output=None):
    """Union methods from complete campaigns with identical case/seed scope."""
    if not (
        len(source_roots) == len(source_preset_paths) == len(source_manifest_paths)
    ) or len(source_roots) < 2:
        raise ValueError("method union requires at least two paired source bundles")
    expected_case_seeds = tuple(sorted(set(expected_case_seeds)))
    if not expected_case_seeds:
        raise ValueError("method union case/seed scope is empty")
    activation_audits = [
        audit_method_campaign_activation(path, expected_case_seeds)
        for path in source_roots
    ]
    inactive_methods = [
        {row["method"] for row in audit["inactive_methods"]}
        for audit in activation_audits
    ]
    all_inactive = [
        (source_index, row)
        for source_index, audit in enumerate(activation_audits)
        for row in audit["inactive_methods"]
    ]
    if all_inactive and not exclude_inactive_methods:
        first = activation_audits[all_inactive[0][0]]["inactive_placements"][0]
        raise ValueError("inactive plugin placement: %s" % first["activation_error"])
    campaigns = [
        discover_strict_method_campaign(path, expected_case_seeds, excluded)
        for path, excluded in zip(source_roots, inactive_methods)
    ]
    bundles = [
        load_preset_bundle(preset, manifest, campaign, excluded)
        for preset, manifest, campaign, excluded in zip(
            source_preset_paths, source_manifest_paths, campaigns,
            inactive_methods,
        )
    ]

    baseline_preset = bundles[0]["presets"]["hpwl"]
    merged_presets = {"hpwl": baseline_preset}
    merged_generated = {}
    method_origins = {"hpwl": 0}
    coverage = {}
    for source_index, (campaign, bundle) in enumerate(zip(campaigns, bundles)):
        if bundle["presets"]["hpwl"] != baseline_preset:
            raise ValueError("duplicate hpwl presets differ")
        for plugin, proxies in bundle["coverage"].items():
            coverage.setdefault(plugin, set()).update(proxies)
        for method in campaign["method_order"]:
            if method == "hpwl":
                continue
            if method in merged_presets:
                raise ValueError("method collision across sources: %s" % method)
            merged_presets[method] = bundle["presets"][method]
            merged_generated[method] = bundle["manifest"]["generated"][method]
            method_origins[method] = source_index
    if expected_method_count is not None and len(merged_presets) != expected_method_count:
        raise ValueError(
            "method union has %d methods, expected %d"
            % (len(merged_presets), expected_method_count)
        )
    missing_plugins = sorted(set(required_plugins) - set(coverage))
    if missing_plugins:
        raise ValueError("method union lacks plugins: %s" % ", ".join(missing_plugins))
    incomplete_proxy_coverage = {
        plugin: sorted({"rudy", "gpugr"} - coverage[plugin])
        for plugin in required_plugins
        if coverage[plugin] != {"rudy", "gpugr"}
    }
    if incomplete_proxy_coverage:
        raise ValueError(
            "method union lacks per-plugin proxy provenance: %s"
            % json.dumps(incomplete_proxy_coverage, sort_keys=True)
        )

    output_root = output_root.resolve()
    output_presets = output_presets.resolve()
    activation_audit = {
        "schema_version": ACTIVATION_AUDIT_SCHEMA_VERSION,
        "status": "filtered" if all_inactive else "passed",
        "contract": "every retained plugin is active on every development case/seed",
        "exclude_inactive_methods": bool(exclude_inactive_methods),
        "source_audits": activation_audits,
        "excluded_inactive_method_count": len(all_inactive),
        "excluded_inactive_methods": [
            {
                "source_campaign": str(campaigns[source_index]["root"]),
                **row,
            }
            for source_index, row in all_inactive
        ],
    }
    if activation_audit_output is not None:
        write_frozen_json(Path(activation_audit_output).resolve(), activation_audit)
    entries = []
    jobs = []
    for case, seed in expected_case_seeds:
        source_records = [campaign["records"][(case, seed)] for campaign in campaigns]
        baseline_records = [record["methods"]["hpwl"] for record in source_records]
        canonical_configs = [
            canonical_baseline_config(record["config"])
            for record in baseline_records
        ]
        if any(value != canonical_configs[0] for value in canonical_configs[1:]):
            raise ValueError("duplicate hpwl configs differ for %s seed %d" % (case, seed))
        def_hashes = [sha256(record["placed_def"]) for record in baseline_records]
        if len(set(def_hashes)) != 1:
            raise ValueError("duplicate hpwl DEFs differ for %s seed %d" % (case, seed))
        placement_rows = [
            canonical_baseline_placement(record["placement"])
            for record in baseline_records
        ]
        if any(value != placement_rows[0] for value in placement_rows[1:]):
            raise ValueError(
                "duplicate hpwl placement evidence differs for %s seed %d"
                % (case, seed)
            )

        output_methods = output_root / case / ("seed_%d" % seed) / case / "methods"
        placements = []
        provenance = {}
        for method in merged_presets:
            source_index = method_origins[method]
            source_record = source_records[source_index]
            record = source_record["methods"][method]
            source_method = record["config_path"].parent
            output_method = output_methods / method
            config_transfer = materialize_file(
                record["config_path"], output_method / "config.json"
            )
            relative_def = record["placed_def"].relative_to(
                source_method / "placement"
            )
            def_transfer = materialize_file(
                record["placed_def"], output_method / "placement" / relative_def
            )
            placements.append(record["placement"])
            provenance[method] = {
                "source_campaign": str(campaigns[source_index]["root"]),
                "source_comparison": str(source_record["comparison"]),
                "source_comparison_sha256": sha256(source_record["comparison"]),
                "source_config": str(record["config_path"]),
                "source_config_sha256": sha256(record["config_path"]),
                "source_placement": str(record["placed_def"]),
                "source_placement_sha256": sha256(record["placed_def"]),
                "config_transfer": config_transfer,
                "placement_transfer": def_transfer,
                "activation_evidence_source": record["activation_source"],
                "activation_log": (
                    str(record["activation_log"])
                    if record["activation_log"] else None
                ),
                "activation_log_sha256": (
                    sha256(record["activation_log"])
                    if record["activation_log"] else None
                ),
            }

        comparison = output_methods / "comparison.json"
        payload = {
            "source_union": {
                "schema_version": METHOD_UNION_SCHEMA_VERSION,
                "placement_rerun": False,
                "legacy_proxy_results_imported": False,
                "numeric_backend_mixing": False,
                "method_count": len(merged_presets),
                "method_provenance": provenance,
                "baseline_identity": {
                    "config_identity": (
                        "byte-identical canonical JSON excluding result_dir and "
                        "evaluator-only route sizes verified equal to placement bins"
                    ),
                    "normalized_evaluator_grid_fields": [
                        field for field, _placement_field
                        in BASELINE_EVALUATOR_GRID_FIELDS
                    ],
                    "canonical_config_sha256": json_sha256(canonical_configs[0]),
                    "source_config_sha256": [
                        sha256(record["config_path"]) for record in baseline_records
                    ],
                    "def_identity": "byte-identical",
                    "def_sha256": def_hashes[0],
                    "placement_evidence_identity": (
                        "identical excluding runtime_sec after verifying and "
                        "normalizing zero-valued baseline pipeline counters"
                    ),
                    "normalized_pipeline_counters": list(
                        BASELINE_PIPELINE_COUNTERS
                    ),
                },
            },
            "validation": {
                "status": "validated",
                "selected_role": "frozen_placement_source",
                "selected_backends": [],
            },
            "placements": placements,
            "results": [],
        }
        write_frozen_json(comparison, payload)
        result_dir = output_root / case / ("seed_%d" % seed)
        jobs.append({
            "job_id": "%s__seed_%d" % (case, seed),
            "case": case,
            "seed": seed,
            "gpu": "source_union",
            "status": "completed",
            "returncode": 0,
            "result_dir": str(result_dir.resolve()),
            "log": str(comparison.resolve()),
        })
        entries.append({
            "case": case,
            "seed": seed,
            "comparison": str(comparison.resolve()),
            "comparison_sha256": sha256(comparison),
            "baseline_def_sha256": def_hashes[0],
            "method_count": len(merged_presets),
        })

    write_frozen_json(output_root / "parallel_status.json", {"jobs": jobs})
    source_bundles = []
    for campaign, bundle in zip(campaigns, bundles):
        source_bundles.append({
            "campaign": str(campaign["root"]),
            "parallel_status": str(campaign["status"]),
            "parallel_status_sha256": sha256(campaign["status"]),
            "presets": str(bundle["presets_path"]),
            "presets_sha256": sha256(bundle["presets_path"]),
            "preset_manifest": str(bundle["manifest_path"]),
            "preset_manifest_sha256": sha256(bundle["manifest_path"]),
            "method_count": len(campaign["method_order"]),
            "source_method_count": (
                len(campaign["method_order"]) + len(campaign["excluded_methods"])
            ),
            "excluded_inactive_methods": campaign["excluded_methods"],
        })
    source_method_count = len(merged_presets) + len(all_inactive)
    union_manifest = {
        "status": "complete",
        "schema_version": METHOD_UNION_SCHEMA_VERSION,
        "merge_mode": "frozen_method_union",
        "placement_rerun": False,
        "legacy_proxy_results_imported": False,
        "numeric_backend_mixing": False,
        "comparison_count": len(entries),
        "source_method_count": source_method_count,
        "method_count": len(merged_presets),
        "methods": list(merged_presets),
        "activation_contract": activation_audit["contract"],
        "activation_audit": activation_audit,
        "excluded_inactive_method_count": len(all_inactive),
        "excluded_inactive_methods": activation_audit[
            "excluded_inactive_methods"
        ],
        "required_plugins": list(required_plugins),
        "plugin_proxy_coverage": {
            plugin: sorted(proxies) for plugin, proxies in sorted(coverage.items())
        },
        "source_bundles": source_bundles,
        "entries": entries,
    }
    write_frozen_json(output_root / "source_union_manifest.json", union_manifest)
    write_frozen_json(output_presets, merged_presets)
    union_preset_manifest = {
        "schema_version": METHOD_UNION_SCHEMA_VERSION,
        "merge_mode": "frozen_method_union",
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "source_bundles": source_bundles,
        "hpwl": {
            "preset_sha256": json_sha256(baseline_preset),
            "verified_identical_across_sources": True,
        },
        "generated": merged_generated,
        "metadata": {
            "atomic_plugins_only": True,
            "development_only": True,
            "method_count": len(merged_presets),
            "source_method_count": source_method_count,
            "generated_count": len(merged_generated),
            "excluded_inactive_method_count": len(all_inactive),
            "excluded_inactive_methods": activation_audit[
                "excluded_inactive_methods"
            ],
            "plugin_proxy_coverage": union_manifest["plugin_proxy_coverage"],
        },
    }
    write_frozen_json(
        output_presets.with_suffix(output_presets.suffix + ".manifest.json"),
        union_preset_manifest,
    )
    return union_manifest


def discover_complete_campaign(root):
    root = root.resolve()
    paths = sorted(root.rglob("comparison.json"))
    if not paths:
        raise ValueError("source campaign has no comparisons: %s" % root)
    indexed = {}
    for path in paths:
        key = campaign_identity(path, root)
        if key in indexed:
            raise ValueError("source campaign duplicates %s seed %d" % key)
        data = json.loads(path.read_text())
        if data.get("validation", {}).get("status") != "validated":
            raise ValueError("source comparison is not validated: %s" % path)
        indexed[key] = path.resolve()
    gate = campaign_gate(root, set(indexed))
    if gate["incomplete_jobs"] or gate["missing_comparisons"]:
        raise ValueError("source campaign is incomplete: %s" % root)
    return indexed


def merge_campaigns(source_roots, output_root, methods=None):
    output_root = output_root.resolve()
    selected_methods = None if methods is None else list(dict.fromkeys(methods))
    if selected_methods is not None and not selected_methods:
        raise ValueError("selected method list is empty")
    combined = {}
    origins = {}
    for source_root in source_roots:
        for key, comparison in discover_complete_campaign(source_root).items():
            if key in combined:
                raise ValueError(
                    "duplicate case/seed across sources: %s seed %d" % key
                )
            combined[key] = comparison
            origins[key] = str(Path(source_root).resolve())
    if not combined:
        raise ValueError("no source comparisons to merge")

    jobs = []
    entries = []
    now = utc_now()
    for (case, seed), comparison in sorted(combined.items()):
        methods_dir = output_root / case / ("seed_%d" % seed) / case / "methods"
        methods_dir.mkdir(parents=True, exist_ok=True)
        comparison_link = methods_dir / "comparison.json"
        desired_comparison = comparison.resolve()
        if selected_methods is None:
            if comparison_link.is_symlink():
                if comparison_link.resolve() != desired_comparison:
                    raise ValueError(
                        "comparison link target changed: %s" % comparison_link
                    )
            elif comparison_link.exists():
                raise ValueError(
                    "comparison output already exists: %s" % comparison_link
                )
            else:
                comparison_link.symlink_to(desired_comparison)
        else:
            data = json.loads(desired_comparison.read_text())
            placements = {
                row.get("method"): row for row in data.get("placements", [])
            }
            missing = [method for method in selected_methods if method not in placements]
            if missing:
                raise ValueError(
                    "selected methods missing from %s: %s"
                    % (desired_comparison, ", ".join(missing))
                )
            filtered = dict(data)
            filtered["placements"] = [placements[method] for method in selected_methods]
            filtered["results"] = [
                row for row in data.get("results", [])
                if row.get("method") in selected_methods
            ]
            filtered["source_comparison"] = str(desired_comparison)
            filtered_text = json.dumps(filtered, indent=2, sort_keys=True) + "\n"
            if comparison_link.exists() or comparison_link.is_symlink():
                if comparison_link.is_symlink() or comparison_link.read_text() != filtered_text:
                    raise ValueError(
                        "filtered comparison output changed: %s" % comparison_link
                    )
            else:
                comparison_link.write_text(filtered_text)

        source_methods = desired_comparison.parent
        method_links = []
        for method_dir in sorted(
            path for path in source_methods.iterdir()
            if path.is_dir() and path.name != "evaluation"
        ):
            if selected_methods is not None and method_dir.name not in selected_methods:
                continue
            link = methods_dir / method_dir.name
            desired = method_dir.resolve()
            if link.is_symlink():
                if link.resolve() != desired:
                    raise ValueError("method link target changed: %s" % link)
            elif link.exists():
                raise ValueError("method output already exists: %s" % link)
            else:
                link.symlink_to(desired, target_is_directory=True)
            method_links.append({"method": method_dir.name, "target": str(desired)})

        jobs.append({
            "job_id": "%s__seed_%d" % (case, seed),
            "case": case,
            "seed": seed,
            "gpu": "source",
            "status": "completed",
            "returncode": 0,
            "started_at": now,
            "finished_at": now,
            "result_dir": str((output_root / case / ("seed_%d" % seed)).resolve()),
            "log": str(comparison_link.resolve()),
        })
        entries.append({
            "case": case,
            "seed": seed,
            "source_campaign": origins[(case, seed)],
            "source_comparison": str(desired_comparison),
            "comparison_link": str(comparison_link),
            "methods": method_links,
        })
    (output_root / "parallel_status.json").write_text(json.dumps({
        "jobs": jobs,
        "updated_at": now,
    }, indent=2, sort_keys=True) + "\n")
    manifest = {
        "status": "complete",
        "merge_mode": (
            "filtered_comparison_with_method_symlinks"
            if selected_methods is not None else "symlink"
        ),
        "selected_methods": selected_methods,
        "source_campaigns": [str(Path(path).resolve()) for path in source_roots],
        "comparison_count": len(entries),
        "entries": entries,
    }
    (output_root / "source_merge_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-campaign", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--method-union", action="store_true",
        help="union methods from campaigns with the same exact case/seed scope",
    )
    parser.add_argument("--source-presets", type=Path, action="append", default=[])
    parser.add_argument(
        "--source-preset-manifest", type=Path, action="append", default=[]
    )
    parser.add_argument("--output-presets", type=Path)
    parser.add_argument("--cases")
    parser.add_argument("--seeds")
    parser.add_argument("--expected-method-count", type=int)
    parser.add_argument(
        "--exclude-inactive-methods", action="store_true",
        help=(
            "exclude and attest methods that fail activation on any requested "
            "case/seed instead of rejecting the entire method union"
        ),
    )
    parser.add_argument(
        "--activation-audit-output", type=Path,
        help="optional frozen JSON activation audit for the source campaigns",
    )
    parser.add_argument(
        "--required-plugins", default=",".join(ATOMIC_PLUGINS)
    )
    parser.add_argument(
        "--methods",
        help="optional comma-separated method subset for a portable golden source",
    )
    args = parser.parse_args(argv)
    if args.method_union:
        if args.methods is not None:
            raise ValueError("--methods cannot be used with --method-union")
        if not args.output_presets or not args.cases or not args.seeds:
            raise ValueError(
                "method union requires --output-presets, --cases, and --seeds"
            )
        cases = [value.strip() for value in args.cases.split(",") if value.strip()]
        seeds = [int(value.strip()) for value in args.seeds.split(",") if value.strip()]
        if len(cases) != len(set(cases)) or len(seeds) != len(set(seeds)):
            raise ValueError("method union cases and seeds must not contain duplicates")
        required_plugins = tuple(
            value.strip() for value in args.required_plugins.split(",")
            if value.strip()
        )
        union_method_campaigns(
            args.source_campaign,
            args.source_presets,
            args.source_preset_manifest,
            args.output_dir,
            args.output_presets,
            [(case, seed) for case in cases for seed in seeds],
            expected_method_count=args.expected_method_count,
            required_plugins=required_plugins,
            exclude_inactive_methods=args.exclude_inactive_methods,
            activation_audit_output=args.activation_audit_output,
        )
        return 0
    methods = None
    if args.methods is not None:
        methods = [value.strip() for value in args.methods.split(",") if value.strip()]
    if (
        args.source_presets or args.source_preset_manifest or args.output_presets
        or args.exclude_inactive_methods or args.activation_audit_output
    ):
        raise ValueError("preset arguments require --method-union")
    merge_campaigns(args.source_campaign, args.output_dir, methods=methods)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
