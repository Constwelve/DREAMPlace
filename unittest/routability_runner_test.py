#!/usr/bin/env python3

import hashlib
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.routability_campaign import (
    apply_path_maps,
    parse_path_maps,
    resolve_template_paths,
)
from dreamplace.ops.routability_eval import EvaluationResult
from tools.routability_compare import (
    DEFAULT_EVALUATORS,
    apply_validation_policy,
    evaluator_design_name,
    evaluator_options,
    find_placed_def,
    parse_placement_metrics,
    parse_plugin_summaries,
    placement_package_provenance,
    placement_input_provenance,
    placement_output_name,
    placement_runtime_provenance,
    run_evaluator_subprocess,
    validate_placement_package_provenance,
    main as compare_main,
)


class RoutabilityRunnerTest(unittest.TestCase):
    def test_corrected_integrated_orchestration_is_one_shot_and_chained(self):
        remote_root = ROOT / "results/routability_remote"
        paths = {
            "missing": remote_root / (
                "corrected_missing_families_dev_3583ba6/run_remote.sh"
            ),
            "missing_launcher": remote_root / (
                "corrected_missing_families_dev_3583ba6/"
                "launch_after_corrected_chain_remote.sh"
            ),
            "missing_adaptive": remote_root / (
                "corrected_missing_adaptive_v2_dev_3583ba6/run_remote.sh"
            ),
            "smoke": remote_root / (
                "corrected_missing_families_dev_3583ba6/"
                "run_isolated_smoke_remote.sh"
            ),
            "contest": remote_root / (
                "corrected_integrated_contest_3583ba6/run_remote.sh"
            ),
            "downstream_launcher": remote_root / (
                "corrected_integrated_contest_3583ba6/"
                "launch_after_missing_remote.sh"
            ),
            "real": remote_root / (
                "corrected_integrated_real_proxy_3583ba6/run_remote.sh"
            ),
            "openroad": remote_root / (
                "corrected_integrated_golden_openroad_3583ba6/run_remote.sh"
            ),
            "innovus": remote_root / (
                "corrected_integrated_golden_innovus_3583ba6/run_local.sh"
            ),
            "innovus_launcher": remote_root / (
                "corrected_integrated_golden_innovus_3583ba6/"
                "launch_after_remote_chain_local.sh"
            ),
            "final_remote": remote_root / (
                "corrected_integrated_final_audit_3583ba6/run_remote.sh"
            ),
            "final_local": remote_root / (
                "corrected_integrated_final_audit_3583ba6/run_local.sh"
            ),
        }
        scripts = {name: path.read_text() for name, path in paths.items()}
        for script in scripts.values():
            self.assertNotIn("while true", script)

        self.assertIn("corrected_missing_families_dev_3583ba6", scripts["contest"])
        self.assertIn("corrected_integrated_contest_3583ba6", scripts["real"])
        self.assertNotIn("corrected_pair_dev_3583ba6", scripts["real"])
        self.assertNotIn("corrected_real_proxy_3583ba6", scripts["real"])
        for name in ("openroad", "innovus"):
            self.assertIn(
                "corrected_integrated_real_proxy_3583ba6", scripts[name]
            )
            self.assertNotIn("corrected_real_proxy_3583ba6", scripts[name])
        self.assertIn(
            "corrected_integrated_golden_openroad_3583ba6",
            scripts["final_local"],
        )
        self.assertIn(
            "corrected_integrated_golden_innovus_3583ba6",
            scripts["final_local"],
        )

        innovus_launcher = scripts["innovus_launcher"]
        self.assertIn(
            'ssh "$remote" "tail --pid=\'$remote_chain_pid\' -f /dev/null"',
            innovus_launcher,
        )
        self.assertNotIn("sleep ", innovus_launcher)
        self.assertIn(
            "remote PID $remote_chain_pid is not the corrected chain",
            innovus_launcher,
        )
        launcher_stages = (
            "waiting_for_remote_chain_terminal",
            "running_innovus_golden",
            "running_combined_final_audit",
            "write_status completed 0",
        )
        launcher_offsets = [
            innovus_launcher.index(stage) for stage in launcher_stages
        ]
        self.assertEqual(launcher_offsets, sorted(launcher_offsets))

        innovus = scripts["innovus"]
        admission_gate = innovus.index(
            "checking_remote_integrated_real_proxy"
        )
        capacity_gate = innovus.index("waiting_for_legacy_router_capacity")
        storage_setup = innovus.index(
            "tools/routability_local_handoff.py prepare-storage"
        )
        evaluator_activation = innovus.index(
            "tools/routability_local_handoff.py activate-evaluators"
        )
        self.assertLess(admission_gate, capacity_gate)
        self.assertLess(capacity_gate, storage_setup)
        self.assertLess(capacity_gate, evaluator_activation)
        self.assertIn("legacy_router_processes.txt", innovus)
        self.assertIn("golden_openroad_detailed_3583ba6", innovus)
        self.assertIn("golden_innovus_detailed_3583ba6", innovus)
        self.assertNotIn("pgrep -af '/innovus", innovus)

        missing_launcher = scripts["missing_launcher"]
        self.assertIn('tail "${wait_args[@]}" -f /dev/null', missing_launcher)
        self.assertNotIn("sleep ", missing_launcher)
        self.assertLess(
            missing_launcher.index("waiting_for_corrected_chain"),
            missing_launcher.index('bash "$runner"'),
        )

        downstream = scripts["downstream_launcher"]
        self.assertIn('tail --pid="$missing_launcher_pid" -f /dev/null', downstream)
        self.assertNotIn("sleep ", downstream)
        stages = (
            "run_stage integrated_contest",
            "run_stage integrated_real_proxy",
            "run_stage integrated_openroad",
            "run_stage integrated_remote_audit",
        )
        offsets = [downstream.index(stage) for stage in stages]
        self.assertEqual(offsets, sorted(offsets))

        final_remote = scripts["final_remote"]
        for label in (
            "corrected_replay_without_invalidated_net_weight=6=",
            "adaptive_v2_without_invalidated_net_weight=6=",
            "missing_families_development=6=",
            "missing_families_adaptive_v2_development=6=",
        ):
            self.assertIn(label, final_remote)
        self.assertIn(
            "completed_no_integrated_atomic_survivor", final_remote
        )

        smoke = scripts["smoke"]
        self.assertIn("smoke_python_install", smoke)
        self.assertIn("smoke_run=isolated_smoke_v5", smoke)
        self.assertIn('"proxy_result_count": len(result_slots)', smoke)
        self.assertIn('"source_install_hash_pairs": len(hash_rows) // 2', smoke)
        self.assertIn(
            'install -m 0644 "$path" "$python_install/$path"', smoke
        )
        required_family_sources = (
            "dreamplace/PlaceObj.py",
            "dreamplace/NonLinearPlace.py",
            "dreamplace/ops/routability_opt/pipeline.py",
            "dreamplace/ops/routability_opt/proxy.py",
            "dreamplace/ops/routability_opt/plugins/route_inflation.py",
            "dreamplace/ops/routability_opt/plugins/momentum_inflation.py",
            "dreamplace/ops/routability_opt/plugins/path_inflation.py",
            "dreamplace/ops/routability_opt/plugins/pin_porosity.py",
            "dreamplace/ops/routability_opt/plugins/routeforce.py",
        )
        for source in required_family_sources:
            self.assertIn(source, smoke)
            self.assertIn(source, scripts["missing"])
        self.assertIn("--gpus 1", smoke)
        self.assertIn(
            "routability_parallel.py.*corrected_missing_families_dev_3583ba6/"
            "isolated_smoke",
            smoke,
        )
        self.assertIn(
            '--dreamplace-entry "$python_install/dreamplace/Placer.py"', smoke
        )
        self.assertIn('PYTHONPATH="$python_install":install', smoke)

        missing = scripts["missing"]
        self.assertIn("pgrep -f 'routability_parallel.py'", missing)
        self.assertIn("corrected_proxy_replay_v1_3583ba6/run_remote.sh", missing)
        self.assertIn("waiting_for_exclusive_gpu_capacity", missing)

    def test_corrected_local_golden_uses_alternate_store_and_gated_activation(self):
        innovus = (
            ROOT / "results/routability_remote/"
            "corrected_golden_innovus_3583ba6/run_local.sh"
        ).read_text()
        final = (
            ROOT / "results/routability_remote/"
            "corrected_final_audit_3583ba6/run_local.sh"
        ).read_text()

        alternate = "/mnt/nvme2n1/yifan/ruplace-routability-corrected-3583ba6"
        self.assertIn(alternate, innovus)
        self.assertIn("tools/routability_local_handoff.py prepare-storage", innovus)
        self.assertIn("refusing to replace retained artifact path", (
            ROOT / "tools/routability_local_handoff.py"
        ).read_text())
        admission = innovus.index(
            "completed_real_heldout_proxy_validation"
        )
        activation = innovus.index(
            "tools/routability_local_handoff.py activate-evaluators"
        )
        routing = innovus.index("tools/routability_golden_replay.py")
        self.assertLess(admission, activation)
        self.assertLess(activation, routing)
        self.assertIn("prepare-python-install", innovus)
        self.assertIn('PYTHONPATH="$python_install:$repo/install"', innovus)
        self.assertIn("evaluator_import_identity.txt", innovus)
        self.assertNotIn("waiting_for_existing_innovus_replays", innovus)
        self.assertNotIn(
            "--installed-dir install/dreamplace/ops/routability_eval", innovus
        )
        self.assertIn("evaluator_activation_sha256", innovus)
        self.assertIn("innovus_artifact=$(sed", final)
        self.assertIn('--campaign "$innovus_campaign"', final)
        self.assertIn('--summary "$innovus_summary"', final)
        self.assertIn('--activation-manifest "$innovus/evaluator_activation.json"', final)
        self.assertIn(
            '"$innovus_artifact/python_install/dreamplace/ops/routability_eval"',
            final,
        )
        self.assertNotIn("corrected_scheduled_dev", innovus)
        self.assertNotIn("corrected_adaptive_dev", innovus)

    def test_corrected_pipeline_cannot_promote_legacy_proxy_evidence(self):
        replay = (
            ROOT / "results/routability_remote/"
            "corrected_proxy_replay_v1_3583ba6/run_remote.sh"
        ).read_text()
        adaptive_v2 = (
            ROOT / "results/routability_remote/"
            "corrected_adaptive_v2_dev_3583ba6/run_remote.sh"
        ).read_text()
        missing_adaptive_v2 = (
            ROOT / "results/routability_remote/"
            "corrected_missing_adaptive_v2_dev_3583ba6/run_remote.sh"
        ).read_text()
        proxy_coverage = (
            ROOT / "results/routability_remote/"
            "corrected_proxy_coverage_dev_3583ba6/run_remote.sh"
        ).read_text()
        integrated_contest = (
            ROOT / "results/routability_remote/"
            "corrected_integrated_contest_3583ba6/run_remote.sh"
        ).read_text()
        pair = (
            ROOT / "results/routability_remote/"
            "corrected_pair_dev_3583ba6/run_remote.sh"
        ).read_text()
        real = (
            ROOT / "results/routability_remote/"
            "corrected_real_proxy_3583ba6/run_remote.sh"
        ).read_text()
        final_audit = (
            ROOT / "results/routability_remote/"
            "corrected_final_audit_3583ba6/run_remote.sh"
        ).read_text()
        integrated_final_audit = (
            ROOT / "results/routability_remote/"
            "corrected_integrated_final_audit_3583ba6/run_remote.sh"
        ).read_text()

        self.assertIn("tools/routability_proxy_replay.py", replay)
        self.assertIn("tools/routability_merge_source_campaigns.py", replay)
        self.assertIn("--method-union", replay)
        self.assertIn("--exclude-inactive-methods", replay)
        self.assertIn("--activation-audit-output", replay)
        self.assertNotIn("--expected-method-count 120", replay)
        self.assertIn(
            'source_union["source_method_count"] == method_count + excluded_count',
            replay,
        )
        self.assertIn(
            '--source-campaign "$scheduled_campaign"', replay
        )
        self.assertIn(
            '--source-campaign "$adaptive_campaign"', replay
        )
        self.assertIn(
            '--source-campaign "$proxy_coverage_campaign"', replay
        )
        self.assertIn(
            '--source-presets "$proxy_coverage_presets"', replay
        )
        self.assertIn("audit_method_campaign_activation", proxy_coverage)
        self.assertIn("net_weighting:gpugr,poisson_force:gpugr", proxy_coverage)
        self.assertIn("ruplace_data_ispd2019_cases.json", proxy_coverage)
        self.assertIn('> "$root/source_install.sha256"', proxy_coverage)
        for source in (
            "dreamplace/Placer.py",
            "dreamplace/NonLinearPlace.py",
            "dreamplace/ops/gpugr/gpugr.py",
            "dreamplace/ops/routability_opt/ruplace_op.py",
            "dreamplace/ops/routability_opt/plugins/net_weighting.py",
            "dreamplace/ops/routability_opt/plugins/poisson_force.py",
        ):
            self.assertIn(source, proxy_coverage)
        self.assertIn(
            "dreamplace/ops/routability_opt/plugins/net_weighting.py",
            adaptive_v2,
        )
        for source in (
            "dreamplace/Placer.py",
            "dreamplace/NonLinearPlace.py",
            "dreamplace/PlaceObj.py",
            "dreamplace/params.json",
            "dreamplace/ops/routability_opt/pipeline.py",
            "dreamplace/ops/routability_opt/ruplace_op.py",
            "dreamplace/ops/routability_opt/plugins/__init__.py",
            "dreamplace/ops/routability_opt/plugins/connection_routeforce.py",
            "dreamplace/ops/routability_opt/plugins/directional_net_contraction.py",
            "dreamplace/ops/routability_opt/plugins/directional_path_spreading.py",
            "dreamplace/ops/routability_opt/plugins/directional_virtual_cell.py",
            "dreamplace/ops/routability_opt/plugins/momentum_inflation.py",
            "dreamplace/ops/routability_opt/plugins/net_relaxation.py",
            "dreamplace/ops/routability_opt/plugins/path_inflation.py",
            "dreamplace/ops/routability_opt/plugins/pin_porosity.py",
            "dreamplace/ops/routability_opt/plugins/projected_connection_routeforce.py",
            "dreamplace/ops/routability_opt/plugins/route_inflation.py",
            "dreamplace/ops/routability_opt/plugins/routed_overflow_net_contraction.py",
            "dreamplace/ops/routability_opt/plugins/routeforce.py",
            "dreamplace/ops/routability_opt/plugins/virtual_cell.py",
            "dreamplace/ops/gpugr/gpugr_backend.py",
            "dreamplace/ops/gpugr/run_gpugr.py",
            "dreamplace/ops/routability_eval/registry.py",
            "dreamplace/ops/routability_eval/openroad.py",
            "dreamplace/ops/routability_eval/innovus.py",
            "tools/routability_compare.py",
            "configs/routability_campaign_ispd2019_absolute_directional_v2.json",
            "cmake/xplace_gpugr_negative_span.patch",
            "thirdparty/XplaceGPUGR/cpp_to_py/gpugr/gr/GPURouterTorch.cu",
        ):
            self.assertIn(source, adaptive_v2)
        self.assertIn("runtime_source_install.sha256", adaptive_v2)
        self.assertIn("campaign_source.sha256", adaptive_v2)
        self.assertIn("gpugr_build_identity.sha256", adaptive_v2)
        self.assertIn("plugin_registry_activation.json", adaptive_v2)
        self.assertIn("assert len(plugin_names) == 18", adaptive_v2)
        self.assertIn('RUPLACE_ACTIVATE_ONLY:-0', adaptive_v2)
        self.assertIn("activation_only_complete", adaptive_v2)
        self.assertIn(
            "Maze routing can encode a segment with a negative signed span",
            adaptive_v2,
        )
        self.assertIn("--max-parents 10", adaptive_v2)
        self.assertIn(
            '["hpwl"] + [name for name in methods if name != "hpwl"]',
            adaptive_v2,
        )
        self.assertIn("assert len(generated) == 160", adaptive_v2)
        self.assertIn('"poisson_force", "whitespace"', adaptive_v2)
        self.assertIn(
            'set(metadata["used_plugin_feedback_groups"]) '
            "== expected_feedback_groups",
            adaptive_v2,
        )
        self.assertIn("plugin: 32 for plugin in expected_plugins", adaptive_v2)
        self.assertIn(
            'source_campaign=$source_union/campaign', replay
        )
        self.assertIn(
            'source_presets=$source_union/presets.json', replay
        )
        self.assertIn('legacy_proxy_results_imported', replay)
        self.assertIn("--route-x-size \"$route_size\"", replay)
        self.assertIn("--route-y-size \"$route_size\"", replay)
        self.assertIn("--metric-profile \"$metric_profile\"", replay)
        self.assertIn("$proxy_replay/summary/near_misses.json", adaptive_v2)
        self.assertIn('--presets "$union_presets"', adaptive_v2)
        self.assertIn('--preset-manifest "$union_manifest"', adaptive_v2)
        self.assertNotIn(
            "$adaptive_v1/development_atomic/summary/near_misses.json",
            adaptive_v2,
        )
        self.assertNotIn(
            '--presets "$scheduled/development_atomic/summary/adaptive_proposals.json"',
            adaptive_v2,
        )
        self.assertIn(
            "dreamplace/ops/routability_eval/rudy.py", adaptive_v2
        )
        self.assertIn(
            "dreamplace/ops/routability_opt/proxy.py", adaptive_v2
        )
        self.assertIn(
            "dreamplace/ops/routability_opt/plugin_base.py", adaptive_v2
        )
        self.assertIn(
            "dreamplace/ops/routability_opt/plugins/utils.py", adaptive_v2
        )
        self.assertIn("optimization_source_install.sha256", adaptive_v2)
        self.assertIn('proposal_policy_version"] == 6', adaptive_v2)
        self.assertIn("absolute_directional_feedback_tuned", adaptive_v2)
        self.assertIn("absolute_directional_feedback_modes", adaptive_v2)
        self.assertIn('replay_pid=${REPLAY_PID:-50600}', adaptive_v2)
        self.assertIn('tail --pid="$replay_pid" -f /dev/null', adaptive_v2)
        self.assertNotIn("sleep 60", adaptive_v2)
        self.assertIn("cmp -s", adaptive_v2)
        self.assertIn("audit_metric_profile development_atomic", adaptive_v2)
        self.assertIn(
            "completed_no_atomic_survivor|completed_atomic_survivors",
            adaptive_v2,
        )
        self.assertNotIn(
            "not_required_corrected_replay_survivor", adaptive_v2
        )
        self.assertIn(
            '--bundle "$replay/summary/survivors.json,',
            integrated_contest,
        )
        self.assertIn(
            '--bundle "$adaptive/development_atomic/summary/survivors.json,',
            integrated_contest,
        )
        self.assertIn(
            '--bundle "$missing/development/summary/survivors.json,',
            integrated_contest,
        )
        self.assertIn(
            '--bundle "$missing_adaptive/development_atomic/summary/survivors.json,',
            integrated_contest,
        )
        self.assertIn("--max-parents 5", missing_adaptive_v2)
        self.assertIn("--max-variants-per-parent 16", missing_adaptive_v2)
        self.assertIn("proposal_policy_version\"] == 6", missing_adaptive_v2)
        self.assertIn("data_ispd19_test1,data_ispd19_test2", missing_adaptive_v2)
        self.assertIn("--evaluators rudy,gpugr", missing_adaptive_v2)
        self.assertIn("--max-primary-worst-regression 0.0", missing_adaptive_v2)
        self.assertIn(
            "source_selection=$proxy_replay/summary/survivors.json", pair
        )
        for runner in (pair, real):
            self.assertIn("audit_proxy_resolution", runner)
            self.assertIn('metrics["route_x_size"]', runner)
            self.assertIn('metrics["route_y_size"]', runner)
            self.assertIn('config["route_num_bins_x"]', runner)
            self.assertIn('config["route_num_bins_y"]', runner)
        self.assertNotIn("metric_profile=legacy", pair)
        self.assertNotIn("source_selection=$scheduled/", pair)
        self.assertNotIn("source_selection=$adaptive/", pair)
        self.assertIn(
            "contest_selection=$pair/heldout_test3/summary/survivors.json", real
        )
        self.assertNotIn("corrected_scheduled_dev", real)
        self.assertNotIn("corrected_adaptive_dev", real)
        self.assertIn(
            "corrected_replay_development=6=$proxy_replay/summary/survivors.json",
            final_audit,
        )
        self.assertIn(
            "missing_families_adaptive_v2_development=6=",
            integrated_final_audit,
        )
        self.assertNotIn("scheduled_development=", final_audit)
        self.assertNotIn("adaptive_development=", final_audit)

    def test_absolute_directional_templates_match_feedback_resolution(self):
        for name in (
            "routability_campaign_ispd2019_absolute_directional_v2.json",
            "routability_real_design_absolute_directional_v2.json",
        ):
            config = json.loads((ROOT / "configs" / name).read_text())
            options = evaluator_options(config, Path("placed.def"))
            self.assertEqual(options["route_x_size"], config["route_num_bins_x"])
            self.assertEqual(options["route_y_size"], config["route_num_bins_y"])

    def test_policy_v7_runner_is_development_only_and_effect_audited(self):
        root = (
            ROOT / "results/routability_remote/"
            "corrected_missing_adaptive_v3_dev_3583ba6"
        )
        runner = (root / "run_remote.sh").read_text()
        launcher = (root / "launch_after_existing_chain_remote.sh").read_text()

        self.assertIn("--proposal-policy-version 7", runner)
        self.assertIn("activating_corrected_optimization_lifecycle", runner)
        self.assertIn("optimization_source_install.sha256", runner)
        for path in (
            "dreamplace/PlaceObj.py",
            "dreamplace/ops/routability_opt/plugin_base.py",
            "dreamplace/ops/routability_opt/pipeline.py",
            "dreamplace/ops/routability_opt/proxy.py",
            "dreamplace/ops/routability_opt/plugins/net_weighting.py",
            "dreamplace/params.json",
        ):
            self.assertIn(path, runner)
        self.assertIn('metadata["proposal_policy_version"] == 7', runner)
        self.assertIn('metadata["effective_refresh_cadences_only"] is True', runner)
        self.assertIn(
            '"lcm(refresh_interval,application_interval)"', runner
        )
        self.assertIn('metadata["area_effect_floor"] == 1e-4', runner)
        self.assertIn('metadata["directional_area_feedback_tuned"] is True', runner)
        self.assertIn('metadata["directional_area_feedback_modes"] == ["max", "mean", "h", "v"]', runner)
        self.assertIn("tools/routability_audit_placement_effect.py", runner)
        self.assertIn("--expected-comparisons 6", runner)
        self.assertIn("data_ispd19_test1,data_ispd19_test2", runner)
        self.assertIn("--evaluators rudy,gpugr", runner)
        self.assertIn("routability_net_weight_corridor_v2.json", runner)
        self.assertIn("generating_corrected_net_weight_lifecycle", runner)
        self.assertIn("net_weight_lifecycle/development_atomic", runner)
        self.assertIn("net_weight_lifecycle_corrected", runner)
        self.assertIn("len(generated) == 192", runner)
        self.assertIn('"pin_mean", "bbox_mean", "bbox_pmean",', runner)
        self.assertIn("pin_mean_corridor_example", runner)
        self.assertIn("bbox_mean_corridor_example", runner)
        self.assertIn("bbox_pmean_corridor_example", runner)
        self.assertGreaterEqual(
            runner.count('print(",".join(["hpwl"] + ['), 1
        )
        self.assertIn('[[ "$all_methods" == hpwl,* ]]', runner)
        self.assertIn('[[ "$net_weight_methods" == hpwl,* ]]', runner)
        self.assertIn('{"rudy", "gpugr"}', runner)
        self.assertIn('"post_gradient", "pre_objective",', runner)
        self.assertIn("net_weight_active_mask_audit.json", runner)
        self.assertIn("net_mask_ignore_large_degrees", runner)
        self.assertIn("masked_net_affects_scale", runner)
        self.assertIn("rudy_feedback_net_weights", runner)
        self.assertIn("--max-primary-worst-regression 0.0", runner)
        self.assertNotIn("data_ispd19_test3", runner)
        self.assertNotIn("openroad", runner.lower())
        self.assertNotIn("innovus", runner.lower())
        self.assertIn('existing_chain_pid=${EXISTING_CHAIN_PID:-1871}', launcher)
        self.assertIn('tail --pid="$existing_chain_pid" -f /dev/null', launcher)
        self.assertIn("waiting_for_existing_chain_terminal", launcher)
        self.assertIn("running_coordinated_adaptive_v3", launcher)
        self.assertNotIn("sleep ", launcher)

    def test_local_corridor_pilot_is_isolated_and_development_only(self):
        runner = (
            ROOT / "results/routability_local/"
            "net_weight_corridor_pilot_3583ba6/run_local.sh"
        ).read_text()

        self.assertIn("routability_net_weight_corridor_pilot_v1.json", runner)
        self.assertIn("cp -a install", runner)
        self.assertIn("python_install", runner)
        self.assertIn("len(generated) == 12", runner)
        self.assertIn('"pin_mean", "bbox_mean", "bbox_pmean",', runner)
        self.assertIn('[[ "$methods" == hpwl,* ]]', runner)
        self.assertIn("data_ispd19_test1", runner)
        self.assertIn("--seeds 1000", runner)
        self.assertIn("--evaluators rudy,gpugr", runner)
        self.assertIn("--max-primary-worst-regression 0.0", runner)
        self.assertIn("selection_or_final_admission_decision", runner)
        self.assertNotIn("data_ispd19_test3", runner)
        self.assertNotIn("openroad", runner.lower())
        self.assertNotIn("innovus", runner.lower())

    def test_policy_v7_contest_chain_merges_then_uses_heldout_test3(self):
        root = (
            ROOT / "results/routability_remote/"
            "corrected_integrated_contest_v7_3583ba6"
        )
        runner = (root / "run_remote.sh").read_text()
        launcher = (root / "launch_after_policy_v7_remote.sh").read_text()

        self.assertIn("corrected_missing_adaptive_v3_dev_3583ba6", runner)
        self.assertEqual(runner.count("--bundle "), 6)
        self.assertIn("net_weight_lifecycle", runner)
        self.assertEqual(
            runner.count("tools/routability_filter_atomic_selection.py"), 2
        )
        self.assertEqual(runner.count("--exclude-plugin net_weighting"), 2)
        self.assertIn("replay_survivors_without_invalidated_net_weight", runner)
        self.assertIn("adaptive_survivors_without_invalidated_net_weight", runner)
        self.assertLess(
            runner.index("building_integrated_pairs"),
            runner.index("heldout_test3"),
        )
        self.assertIn("development_pairs", runner)
        self.assertIn("--expected-comparisons 6", runner)
        self.assertIn("data_ispd19_test3", runner)
        self.assertIn("--expected-comparisons 3", runner)
        self.assertIn("tools/routability_audit_placement_effect.py", runner)
        self.assertIn("--max-primary-worst-regression 0.0", runner)
        self.assertNotIn("openroad", runner.lower())
        self.assertNotIn("innovus", runner.lower())
        self.assertIn('policy_v7_launcher_pid=${POLICY_V7_LAUNCHER_PID:-11034}', launcher)
        self.assertIn(
            'corrected_missing_adaptive_v3_dev_3583ba6/run_remote.sh',
            launcher,
        )
        self.assertIn('tail --pid="$policy_v7_launcher_pid" -f /dev/null', launcher)
        for prerequisite in (
            "corrected_proxy_coverage_dev_3583ba6",
            "corrected_proxy_replay_v1_3583ba6",
            "corrected_adaptive_v2_dev_3583ba6",
        ):
            self.assertIn(prerequisite, launcher)
        prerequisite_stages = (
            "run_stage corrected_proxy_coverage",
            "run_stage corrected_proxy_replay",
            "run_stage corrected_adaptive_v2",
            "running_integrated_contest_v7",
        )
        prerequisite_offsets = [
            launcher.index(stage) for stage in prerequisite_stages
        ]
        self.assertEqual(prerequisite_offsets, sorted(prerequisite_offsets))
        self.assertIn("REPLAY_PID=none", launcher)
        self.assertNotIn("sleep ", launcher)

        coverage = (
            ROOT / "results/routability_remote/"
            "corrected_proxy_coverage_dev_3583ba6/run_remote.sh"
        ).read_text()
        replay = (
            ROOT / "results/routability_remote/"
            "corrected_proxy_replay_v1_3583ba6/run_remote.sh"
        ).read_text()
        adaptive = (
            ROOT / "results/routability_remote/"
            "corrected_adaptive_v2_dev_3583ba6/run_remote.sh"
        ).read_text()
        self.assertIn("--resume", coverage)
        self.assertIn("--resume", adaptive)
        self.assertNotIn("sleep 60", replay)
        self.assertIn("waiting_for_adaptive_v1_terminal", replay)
        self.assertIn("waiting_for_proxy_coverage_terminal", replay)
        self.assertIn(
            "completed_proxy_coverage_no_strict_survivor|"
            "completed_proxy_coverage_survivors",
            replay,
        )
        self.assertIn('[[ "$replay_pid" != none ]]', adaptive)

    def test_policy_v7_continues_through_real_proxies_and_golden_routers(self):
        remote_root = ROOT / "results/routability_remote"
        real = (
            remote_root
            / "corrected_integrated_real_proxy_3583ba6/run_remote.sh"
        ).read_text()
        openroad = (
            remote_root
            / "corrected_integrated_golden_openroad_3583ba6/run_remote.sh"
        ).read_text()
        innovus = (
            remote_root
            / "corrected_integrated_golden_innovus_3583ba6/run_local.sh"
        ).read_text()
        remote_audit = (
            remote_root
            / "corrected_integrated_final_audit_3583ba6/run_remote.sh"
        ).read_text()
        local_audit = (
            remote_root
            / "corrected_integrated_final_audit_3583ba6/run_local.sh"
        ).read_text()
        remote_launcher = (
            remote_root
            / "corrected_integrated_v7_continuation_3583ba6/"
            "launch_after_contest_v7_remote.sh"
        ).read_text()
        local_launcher = (
            remote_root
            / "corrected_integrated_golden_innovus_v7_3583ba6/"
            "launch_after_remote_chain_local.sh"
        ).read_text()

        self.assertIn("${RUPLACE_CONTEST_ROOT:-", real)
        self.assertIn("${RUPLACE_REAL_PROXY_ROOT:-", real)
        self.assertIn("--expected-comparisons 9", real)
        self.assertIn("--expected-comparisons 6", real)
        self.assertEqual(real.count("routability_audit_placement_effect.py"), 2)
        self.assertLess(
            real.index("development_bp_mempool_nvdla"),
            real.index("heldout_openc910_xscore"),
        )
        self.assertIn("--evaluators rudy,gpugr", real)
        self.assertIn("--max-primary-worst-regression 0.0", real)
        self.assertIn('print(",".join(["hpwl"] + [', real)
        self.assertIn('[[ "$all_methods" == hpwl,* ]]', real)

        self.assertIn("${RUPLACE_REAL_PROXY_ROOT:-", openroad)
        self.assertIn("${RUPLACE_OPENROAD_ROOT:-", openroad)
        self.assertIn("${RUPLACE_REAL_PROXY_ROOT:-", innovus)
        self.assertIn("${RUPLACE_INNOVUS_ROOT:-", innovus)
        self.assertIn("activating_corrected_optimization_lifecycle", innovus)
        self.assertIn("optimization_source_install.sha256", innovus)
        for path in (
            "dreamplace/PlaceObj.py",
            "dreamplace/ops/routability_opt/plugin_base.py",
            "dreamplace/ops/routability_opt/pipeline.py",
            "dreamplace/ops/routability_opt/proxy.py",
            "dreamplace/ops/routability_opt/plugins/net_weighting.py",
            "dreamplace/params.json",
        ):
            self.assertIn(path, innovus)
        self.assertIn("${RUPLACE_POLICY_V7_ROOT:-}", remote_audit)
        self.assertIn("missing_families_adaptive_v3_development=6=", remote_audit)
        self.assertIn("corrected_net_weight_lifecycle_development=6=", remote_audit)
        self.assertIn(
            "corrected_replay_without_invalidated_net_weight=6=", remote_audit
        )
        self.assertIn("${RUPLACE_FINAL_AUDIT_ROOT:-", local_audit)

        self.assertIn('contest_launcher_pid=${CONTEST_V7_LAUNCHER_PID:-31112}', remote_launcher)
        self.assertIn('tail --pid="$contest_launcher_pid" -f /dev/null', remote_launcher)
        self.assertNotIn("sleep ", remote_launcher)
        remote_stages = (
            "run_stage integrated_real_proxy_v7",
            "run_stage integrated_openroad_v7",
            "run_stage integrated_remote_audit_v7",
        )
        remote_offsets = [remote_launcher.index(stage) for stage in remote_stages]
        self.assertEqual(remote_offsets, sorted(remote_offsets))
        for root in (
            "corrected_integrated_contest_v7_3583ba6",
            "corrected_integrated_real_proxy_v7_3583ba6",
            "corrected_integrated_golden_openroad_v7_3583ba6",
            "corrected_integrated_final_audit_v7_3583ba6",
        ):
            self.assertIn(root, remote_launcher)

        self.assertIn("REMOTE_CHAIN_PID is required", local_launcher)
        self.assertIn("handoff_innovus_to_10h_3583ba6.sh", local_launcher)
        self.assertIn('while [[ "$remote_phase" != completed ]]', local_launcher)
        self.assertIn("exited without completed evidence", local_launcher)
        self.assertIn('ssh "$remote" "tail --pid=\'$remote_chain_pid\' -f /dev/null" || true', local_launcher)
        self.assertIn("sleep 5", local_launcher)
        self.assertIn('tail --pid="$legacy_local_chain_pid" -f /dev/null', local_launcher)
        self.assertIn('[[ "$golden_candidate" -eq 1 ]]', local_launcher)
        self.assertLess(
            local_launcher.index("remote_real_phase="),
            local_launcher.index('kill -0 "$legacy_local_chain_pid"'),
        )
        self.assertIn("corrected_integrated_golden_innovus_v7_3583ba6", local_launcher)
        local_stages = (
            "waiting_for_remote_v7_chain_terminal",
            "waiting_for_legacy_local_chain_terminal",
            "running_innovus_v7_golden",
            "running_combined_final_audit_v7",
        )
        local_offsets = [local_launcher.index(stage) for stage in local_stages]
        self.assertEqual(local_offsets, sorted(local_offsets))

    def test_default_evaluators_follow_golden_then_fallback_policy(self):
        self.assertEqual(DEFAULT_EVALUATORS, "openroad,innovus,rudy,gpugr")

    def test_plugin_summary_preserves_runtime_area_budget_observations(self):
        summaries = [
            {
                "pipeline": {
                    "area_calls": 3,
                    "area_gate_skips": 1,
                    "area_budget_enabled": 1,
                    "area_adjustments": 2,
                    "max_area_adjustments": 2,
                },
                "plugins": {},
            },
            {
                "pipeline": {
                    "area_calls": 2,
                    "area_gate_skips": 0,
                    "area_budget_enabled": 1,
                    "area_adjustments": 1,
                    "max_area_adjustments": 2,
                },
                "plugins": {},
            },
        ]
        text = "\n".join(
            "INFO ROUTABILITY_PLUGIN_SUMMARY " + json.dumps(summary)
            for summary in summaries
        )

        result = parse_plugin_summaries(text)["routability_plugin_summary"]
        pipeline = result["pipeline"]
        self.assertEqual(pipeline["area_calls"], 5)
        self.assertEqual(pipeline["area_gate_skips"], 1)
        self.assertEqual(pipeline["area_budget_enabled"], 1)
        self.assertEqual(pipeline["area_adjustments"], 2)
        self.assertEqual(pipeline["max_area_adjustments"], 2)
        self.assertEqual(pipeline["area_budget_observations"], [
            {
                "area_budget_enabled": 1,
                "area_adjustments": 2,
                "max_area_adjustments": 2,
            },
            {
                "area_budget_enabled": 1,
                "area_adjustments": 1,
                "max_area_adjustments": 2,
            },
        ])

    def test_comparison_marks_only_common_selected_role_authoritative(self):
        method_results = {
            "a": [EvaluationResult("openroad", "d"), EvaluationResult("gpugr", "d")],
            "b": [
                EvaluationResult("innovus", "d", status="failed"),
                EvaluationResult("gpugr", "d"),
            ],
        }
        serialized = [
            {"method": method, **result.to_dict()}
            for method, results in method_results.items() for result in results
        ]
        rows = [
            {"method": item["method"], "evaluator": item["backend"],
             "validation_role": "golden" if item["backend"] in ("openroad", "innovus")
             else "fallback_reference", "status": item["status"]}
            for item in serialized
        ]
        summary = apply_validation_policy(method_results, rows, serialized)
        self.assertEqual(summary["selected_role"], "fallback_reference")
        self.assertEqual(summary["selected_backends"], ["gpugr"])
        self.assertTrue(summary["fallback_used"])
        self.assertFalse(rows[0]["authoritative_for_comparison"])
        self.assertTrue(rows[1]["authoritative_for_comparison"])
        self.assertTrue(rows[3]["authoritative_for_comparison"])

    def test_failed_method_prevents_subset_from_being_validated(self):
        method_results = {
            "completed": [EvaluationResult("openroad", "d")],
            "placement_failed": [],
        }
        serialized = [
            {"method": "completed", **method_results["completed"][0].to_dict()}
        ]
        rows = [{
            "method": "completed", "evaluator": "openroad",
            "validation_role": "golden", "status": "ok",
        }]
        summary = apply_validation_policy(method_results, rows, serialized)
        self.assertEqual(summary["status"], "unvalidated")
        self.assertEqual(summary["selected_backends"], [])
        self.assertFalse(rows[0]["authoritative_for_comparison"])

    def test_paired_proxy_gate_rejects_rudy_only_success(self):
        from tools.routability_compare import mandatory_requested_evaluator_gate

        results = {
            "hpwl": [
                EvaluationResult("rudy", "d"),
                EvaluationResult("gpugr", "d", status="failed"),
            ],
        }
        gate = mandatory_requested_evaluator_gate(
            results, ["hpwl"], ["rudy", "gpugr"]
        )
        self.assertEqual(gate["status"], "failed")
        self.assertEqual(gate["failures"], ["hpwl:gpugr"])

    def test_early_stop_cannot_validate_only_completed_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(root / "input.def")}))
            presets.write_text(json.dumps({"hpwl": {}, "fails": {}}))

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult("openroad", "d", metrics={"wirelength": 1}).write_json(
                        eval_dir / "openroad.json"
                    )
                    return mock.Mock(returncode=0, stdout="")
                config = json.loads(Path(command[-1]).read_text())
                if Path(command[-1]).parent.name == "fails":
                    return mock.Mock(returncode=1, stdout="placement failed")
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(returncode=0, stdout="")

            with mock.patch("tools.routability_compare.subprocess.run", side_effect=run):
                status = compare_main([
                    "--base-config", str(base), "--presets", str(presets),
                    "--methods", "hpwl,fails", "--evaluators", "openroad",
                    "--output-dir", str(output), "--dreamplace-entry", "placer.py",
                ])

            comparison = json.loads((output / "comparison.json").read_text())
        self.assertEqual(status, 1)
        self.assertEqual(comparison["validation"]["status"], "unvalidated")
        self.assertEqual(comparison["validation"]["selected_backends"], [])

    def test_resume_reuses_only_complete_config_identical_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(root / "input.def")}))
            presets.write_text(json.dumps({"hpwl": {}, "plugin": {"alpha": 1}}))

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult(
                        "rudy", "d", metrics={"congestion_score": 1.0}
                    ).write_json(eval_dir / "rudy.json")
                    return mock.Mock(returncode=0, stdout="")
                config = json.loads(Path(command[-1]).read_text())
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(
                    returncode=0,
                    stdout="iteration 1, wHPWL 1.0, Overflow 0.1\n",
                )

            arguments = [
                "--base-config", str(base), "--presets", str(presets),
                "--methods", "hpwl,plugin", "--evaluators", "rudy",
                "--output-dir", str(output), "--dreamplace-entry", "placer.py",
            ]
            with mock.patch(
                "tools.routability_compare.subprocess.run", side_effect=run
            ):
                self.assertEqual(compare_main(arguments), 0)
            with mock.patch(
                "tools.routability_compare.subprocess.run",
                side_effect=AssertionError("resume reran completed work"),
            ):
                self.assertEqual(compare_main(arguments + ["--resume"]), 0)
            comparison = json.loads((output / "comparison.json").read_text())
            placement_provenance = [
                json.loads((output / method / "placement_provenance.json").read_text())
                for method in ("hpwl", "plugin")
            ]

        self.assertEqual(
            comparison["resume"]["reused_placements"], ["hpwl", "plugin"]
        )
        self.assertEqual(len(comparison["resume"]["reused_evaluations"]), 2)
        self.assertEqual(comparison["resume"]["rerun_placements"], [])
        self.assertEqual(comparison["validation"]["status"], "validated")
        self.assertEqual(
            [row["method"] for row in placement_provenance],
            ["hpwl", "plugin"],
        )
        self.assertTrue(all(
            row["schema_version"] == 1
            and row["placed_def_sha256"]
            == row["placement_geometry_provenance"]["def_sha256"]
            and isinstance(row["placement_runtime_provenance"], dict)
            for row in placement_provenance
        ))

    def test_resume_rejects_placement_after_input_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_def = root / "input.def"
            input_def.write_text("VERSION 5.8 ;\nEND DESIGN\n")
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(input_def)}))
            presets.write_text(json.dumps({"hpwl": {}}))
            placement_calls = []

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult(
                        "rudy", "d", metrics={"congestion_score": 1.0}
                    ).write_json(eval_dir / "rudy.json")
                    return mock.Mock(returncode=0, stdout="")
                placement_calls.append(command)
                config = json.loads(Path(command[-1]).read_text())
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True, exist_ok=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(
                    returncode=0,
                    stdout="iteration 1, wHPWL 1.0, Overflow 0.1\n",
                )

            arguments = [
                "--base-config", str(base), "--presets", str(presets),
                "--methods", "hpwl", "--evaluators", "rudy",
                "--output-dir", str(output), "--dreamplace-entry", "placer.py",
            ]
            with mock.patch(
                "tools.routability_compare.subprocess.run", side_effect=run
            ):
                self.assertEqual(compare_main(arguments), 0)
                input_def.write_text("VERSION 5.8 ;\n# changed\nEND DESIGN\n")
                self.assertEqual(compare_main(arguments + ["--resume"]), 0)
            comparison = json.loads((output / "comparison.json").read_text())

        self.assertEqual(len(placement_calls), 2)
        self.assertEqual(comparison["resume"]["reused_placements"], [])
        self.assertEqual(comparison["resume"]["rerun_placements"], ["hpwl"])
        self.assertFalse(comparison["resume"]["input_provenance_matches"])

    def test_resume_rejects_modified_placed_def(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(root / "input.def")}))
            presets.write_text(json.dumps({"hpwl": {}}))
            placement_calls = []

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult(
                        "rudy", "d", metrics={"congestion_score": 1.0}
                    ).write_json(eval_dir / "rudy.json")
                    return mock.Mock(returncode=0, stdout="")
                placement_calls.append(command)
                config = json.loads(Path(command[-1]).read_text())
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True, exist_ok=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(returncode=0, stdout="")

            arguments = [
                "--base-config", str(base), "--presets", str(presets),
                "--methods", "hpwl", "--evaluators", "rudy",
                "--output-dir", str(output), "--dreamplace-entry", "placer.py",
            ]
            with mock.patch(
                "tools.routability_compare.subprocess.run", side_effect=run
            ):
                self.assertEqual(compare_main(arguments), 0)
                placed = output / "hpwl/placement/input/input.gp.def"
                placed.write_text("tampered\n")
                self.assertEqual(compare_main(arguments + ["--resume"]), 0)
            comparison = json.loads((output / "comparison.json").read_text())

        self.assertEqual(len(placement_calls), 2)
        self.assertEqual(comparison["resume"]["reused_placements"], [])
        self.assertEqual(comparison["resume"]["rerun_placements"], ["hpwl"])

    def test_placement_input_provenance_hashes_lists_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lef = root / "input.lef"
            deffile = root / "input.def"
            lef.write_text("END LIBRARY\n")
            deffile.write_text("END DESIGN\n")
            provenance = placement_input_provenance({
                "lef_input": [str(lef)],
                "def_input": str(deffile),
                "verilog_input": str(root / "missing.v"),
            })

        self.assertEqual(
            provenance["files"]["lef_input"][0]["sha256"],
            hashlib.sha256(b"END LIBRARY\n").hexdigest(),
        )
        self.assertEqual(
            provenance["files"]["def_input"][0]["size"], 11
        )
        self.assertFalse(
            provenance["files"]["verilog_input"][0]["exists"]
        )

    def test_placement_package_provenance_hashes_loaded_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay = Path(tmp)
            root = overlay / "install"
            package = root / "dreamplace"
            plugin = package / "ops/routability_opt/plugins/example.py"
            evaluator = package / "ops/routability_eval/example.py"
            plugin.parent.mkdir(parents=True)
            evaluator.parent.mkdir(parents=True)
            entry = package / "Placer.py"
            entry.write_text("print('placer')\n")
            plugin.write_text("STRENGTH = 1\n")
            evaluator.write_text("SCHEMA = 1\n")
            source_plugin = (
                overlay / "source/dreamplace/ops/routability_opt/plugins/example.py"
            )
            source_plugin.parent.mkdir(parents=True)
            source_plugin.write_text("STRENGTH = 2\n")

            provenance = placement_package_provenance(entry)

        self.assertEqual(provenance["python_root"], str(root.resolve()))
        self.assertEqual(
            provenance["files"][
                "dreamplace/ops/routability_opt/plugins/example.py"
            ],
            hashlib.sha256(b"STRENGTH = 1\n").hexdigest(),
        )
        self.assertNotIn(
            "dreamplace/ops/routability_eval/example.py", provenance["files"]
        )
        self.assertEqual(
            provenance["source_files"][
                "dreamplace/ops/routability_opt/plugins/example.py"
            ],
            hashlib.sha256(b"STRENGTH = 2\n").hexdigest(),
        )
        self.assertEqual(provenance["source_install_mismatches"], [
            "dreamplace/ops/routability_opt/plugins/example.py"
        ])
        with self.assertRaisesRegex(RuntimeError, "source/install mismatches"):
            validate_placement_package_provenance(provenance)

    def test_placement_runtime_provenance_has_numerical_abi(self):
        provenance = placement_runtime_provenance()
        self.assertIn("hostname", provenance["host"])
        self.assertIn("executable", provenance["python"])
        self.assertIn("torch", provenance)
        self.assertIn("CUDA_VISIBLE_DEVICES", provenance["environment"])

    def test_resume_rejects_placement_after_implementation_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "dreamplace"
            package.mkdir()
            entry = package / "Placer.py"
            entry.write_text("VERSION = 1\n")
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(root / "input.def")}))
            presets.write_text(json.dumps({"hpwl": {}}))
            placement_calls = []

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult(
                        "rudy", "d", metrics={"congestion_score": 1.0}
                    ).write_json(eval_dir / "rudy.json")
                    return mock.Mock(returncode=0, stdout="")
                placement_calls.append(command)
                config = json.loads(Path(command[-1]).read_text())
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True, exist_ok=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(returncode=0, stdout="")

            arguments = [
                "--base-config", str(base), "--presets", str(presets),
                "--methods", "hpwl", "--evaluators", "rudy",
                "--output-dir", str(output), "--dreamplace-entry", str(entry),
            ]
            with mock.patch(
                "tools.routability_compare.subprocess.run", side_effect=run
            ):
                self.assertEqual(compare_main(arguments), 0)
                entry.write_text("VERSION = 2\n")
                self.assertEqual(compare_main(arguments + ["--resume"]), 0)
            comparison = json.loads((output / "comparison.json").read_text())

        self.assertEqual(len(placement_calls), 2)
        self.assertFalse(comparison["resume"][
            "placement_implementation_provenance_matches"
        ])
        self.assertEqual(comparison["resume"]["rerun_placements"], ["hpwl"])

    def test_resume_rejects_placement_after_runtime_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(root / "input.def")}))
            presets.write_text(json.dumps({"hpwl": {}}))
            placement_calls = []

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult(
                        "rudy", "d", metrics={"congestion_score": 1.0}
                    ).write_json(eval_dir / "rudy.json")
                    return mock.Mock(returncode=0, stdout="")
                placement_calls.append(command)
                config = json.loads(Path(command[-1]).read_text())
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True, exist_ok=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(returncode=0, stdout="")

            arguments = [
                "--base-config", str(base), "--presets", str(presets),
                "--methods", "hpwl", "--evaluators", "rudy",
                "--output-dir", str(output), "--dreamplace-entry", "placer.py",
            ]
            with mock.patch(
                "tools.routability_compare.placement_runtime_provenance",
                side_effect=[{"host": "gpu-a"}, {"host": "gpu-b"}],
            ), mock.patch(
                "tools.routability_compare.subprocess.run", side_effect=run
            ):
                self.assertEqual(compare_main(arguments), 0)
                self.assertEqual(compare_main(arguments + ["--resume"]), 0)
            comparison = json.loads((output / "comparison.json").read_text())

        self.assertEqual(len(placement_calls), 2)
        self.assertFalse(comparison["resume"][
            "placement_runtime_provenance_matches"
        ])
        self.assertEqual(comparison["resume"]["rerun_placements"], ["hpwl"])

    def test_method_summary_retains_every_requested_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            presets = root / "presets.json"
            output = root / "out"
            base.write_text(json.dumps({"def_input": str(root / "input.def")}))
            presets.write_text(json.dumps({"hpwl": {}}))

            def run(command, **kwargs):
                if "routability_evaluate.py" in str(command[1]):
                    backend = command[command.index("--backend") + 1]
                    eval_dir = Path(command[command.index("--output-dir") + 1])
                    EvaluationResult(
                        backend, "d", metrics={"route_x_size": 256,
                                               "route_y_size": 256},
                    ).write_json(eval_dir / (backend + ".json"))
                    # The evaluator CLI writes a single-backend summary. The
                    # comparison runner must replace it with the aggregate.
                    (eval_dir / "summary.json").write_text(json.dumps({
                        "results": [{"backend": backend}],
                    }))
                    return mock.Mock(returncode=0, stdout="")
                config = json.loads(Path(command[-1]).read_text())
                placed = Path(config["result_dir"]) / "input" / "input.gp.def"
                placed.parent.mkdir(parents=True)
                placed.write_text("END DESIGN\n")
                return mock.Mock(returncode=0, stdout="")

            with mock.patch(
                "tools.routability_compare.subprocess.run", side_effect=run
            ):
                status = compare_main([
                    "--base-config", str(base), "--presets", str(presets),
                    "--methods", "hpwl", "--evaluators", "rudy,gpugr",
                    "--output-dir", str(output),
                    "--dreamplace-entry", "placer.py",
                ])
            summary = json.loads(
                (output / "hpwl/evaluation/summary.json").read_text()
            )

        self.assertEqual(status, 0)
        self.assertEqual(
            [result["backend"] for result in summary["results"]],
            ["rudy", "gpugr"],
        )

    def test_output_name_matches_dreamplace_precedence(self):
        config = {"def_input": "/d/chip.floorplan.def", "verilog_input": "/n/chip.v"}
        self.assertEqual(placement_output_name(config), "chip")
        self.assertEqual(placement_output_name({"def_input": "/d/chip.floorplan.def"}),
                         "chip.floorplan")

    def test_evaluator_design_name_accepts_explicit_top(self):
        config = {
            "def_input": "/d/2_2_floorplan_io.def",
            "ruplace_eval_design_name": "gcd",
        }
        self.assertEqual(evaluator_design_name(config), "gcd")
        self.assertEqual(
            evaluator_design_name({"def_input": "/d/chip.floorplan.def"}),
            "chip.floorplan",
        )

    def test_find_placed_def_recurses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "nested" / "chip.floorplan" / "chip.floorplan.gp.def"
            expected.parent.mkdir(parents=True)
            expected.write_text("END DESIGN\n")
            self.assertEqual(find_placed_def(root, "chip.floorplan"), expected)

    def test_template_paths_resolve_from_template(self):
        result = resolve_template_paths(
            {"ruplace_xplace_root": "../../Xplace", "routability_eval_openroad_binary": "openroad"},
            Path("/repo/configs"),
        )
        self.assertEqual(result["ruplace_xplace_root"], "/Xplace")
        self.assertEqual(result["routability_eval_openroad_binary"], "openroad")

    def test_campaign_path_maps_replace_only_path_prefix(self):
        mappings = parse_path_maps(["/source/data=/remote/data"])
        self.assertEqual(
            apply_path_maps("/source/data/case/input.def", mappings),
            "/remote/data/case/input.def",
        )
        self.assertEqual(
            apply_path_maps("/source/database/input.def", mappings),
            "/source/database/input.def",
        )

    def test_parse_placement_metrics_uses_final_iteration(self):
        metrics = parse_placement_metrics(
            "iteration 0, wHPWL 1.2E+03, Overflow 9.0E-01\n"
            "iteration 1, wHPWL 8.5E+02, Overflow 2.5E-01\n"
        )
        self.assertEqual(metrics["placement_hpwl"], 850.0)
        self.assertEqual(metrics["density_overflow"], 0.25)

    def test_parse_plugin_summaries_flags_active_and_noop_plugins(self):
        logs = "\n".join([
            'INFO ROUTABILITY_PLUGIN_SUMMARY {"pipeline":{"gradient_calls":3,'
            '"gradient_gate_skips":1,"area_calls":2,"area_gate_skips":0},'
            '"plugins":{"local_gradient":{"gradient_attempts":2,'
            '"gradient_activations":2,"area_attempts":0,"area_activations":0,'
            '"metrics":{"field_norm":0.0},"metric_stats":{"field_norm":'
            '{"count":2,"nonzero_count":1,"min":0.0,"max":2.0,'
            '"mean":1.0,"last":0.0}}},"pin_porosity":{"gradient_attempts":0,'
            '"gradient_activations":0,"area_attempts":2,"area_activations":0,'
            '"metrics":{"changed":false}}}}',
            'INFO ROUTABILITY_PLUGIN_SUMMARY {"pipeline":{"gradient_calls":1,'
            '"gradient_gate_skips":0,"area_calls":0,"area_gate_skips":0},'
            '"plugins":{"local_gradient":{"gradient_attempts":1,'
            '"gradient_activations":1,"area_attempts":0,"area_activations":0,'
            '"metrics":{"field_norm":4.0},"metric_stats":{"field_norm":'
            '{"count":1,"nonzero_count":1,"min":4.0,"max":4.0,'
            '"mean":4.0,"last":4.0}}}}}',
        ])
        result = parse_plugin_summaries(logs)
        self.assertEqual(result["routability_plugin_status"], "partially_active")
        self.assertEqual(result["routability_plugin_attempts"], 5)
        self.assertEqual(result["routability_plugin_activations"], 3)
        self.assertEqual(
            result["routability_plugin_summary"]["plugins"]["pin_porosity"]["status"],
            "attempted_no_change",
        )
        metric = result["routability_plugin_summary"]["plugins"][
            "local_gradient"
        ]["metric_stats"]["field_norm"]
        self.assertEqual(metric["count"], 3)
        self.assertEqual(metric["nonzero_count"], 2)
        self.assertEqual(metric["min"], 0.0)
        self.assertEqual(metric["max"], 4.0)
        self.assertEqual(metric["mean"], 2.0)
        self.assertEqual(metric["last"], 4.0)

    def test_parse_plugin_summaries_marks_baseline_not_selected(self):
        result = parse_plugin_summaries("ordinary placement log")
        self.assertEqual(result["routability_plugin_status"], "not_selected")
        self.assertEqual(result["routability_plugin_activations"], 0)

    def test_parse_plugin_summaries_counts_objective_phase_activation(self):
        result = parse_plugin_summaries(
            'INFO ROUTABILITY_PLUGIN_SUMMARY {"pipeline":{'
            '"objective_calls":12,"objective_gate_skips":2,'
            '"gradient_calls":12,"gradient_gate_skips":2,'
            '"area_calls":0,"area_gate_skips":0},"plugins":{'
            '"net_weighting":{"objective_attempts":10,'
            '"objective_activations":3,"gradient_attempts":0,'
            '"gradient_activations":0,"area_attempts":0,'
            '"area_activations":0,"metrics":{"mean_ratio":1.1},'
            '"metric_stats":{}}}}'
        )
        self.assertEqual(result["routability_plugin_status"], "active")
        self.assertEqual(result["routability_plugin_attempts"], 10)
        self.assertEqual(result["routability_plugin_activations"], 3)
        summary = result["routability_plugin_summary"]
        self.assertEqual(summary["pipeline"]["objective_calls"], 12)
        self.assertEqual(
            summary["plugins"]["net_weighting"]["objective_activations"], 3
        )

    def test_evaluator_process_result_is_reconstructed(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        with tempfile.TemporaryDirectory() as tmp:
            request = EvaluationRequest(
                design_name="d", lef_input=["a.lef"], def_input="a.def",
                output_dir=tmp, options={"route_size": 64},
            )

            def completed(command, **kwargs):
                Path(tmp, "rudy.json").write_text(
                    '{"backend":"rudy","design_name":"d","status":"ok",'
                    '"runtime_sec":1.0,"metrics":{"wirelength":2},'
                    '"artifacts":{},"error":"","schema_version":1}'
                )
                return mock.Mock(returncode=0, stdout="done")

            with mock.patch("tools.routability_compare.subprocess.run", side_effect=completed) as run:
                result = run_evaluator_subprocess(
                    request, "rudy", entry="evaluate.py", python_root=ROOT
                )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metrics["wirelength"], 2)
        command = run.call_args.args[0]
        self.assertIn("route_size=64", command)
        self.assertEqual(
            run.call_args.kwargs["env"]["DREAMPLACE_EVALUATOR_PYTHON_ROOT"],
            str(ROOT.resolve()),
        )

    def test_resume_rejects_result_from_changed_evaluator_package(self):
        from tools.routability_compare import reusable_evaluation_result

        result = EvaluationResult(
            "gpugr", "d", metrics={"directional_metric_schema_version": 1}
        )
        self.assertFalse(reusable_evaluation_result(
            result, "gpugr",
            {"required_directional_metric_schema_version": 2},
        ))
        result.metrics["directional_metric_schema_version"] = 2
        self.assertTrue(reusable_evaluation_result(
            result, "gpugr",
            {"required_directional_metric_schema_version": 2},
        ))

    def test_evaluator_process_crash_becomes_failed_result(self):
        from dreamplace.ops.routability_eval import EvaluationRequest

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "tools.routability_compare.subprocess.run",
            return_value=mock.Mock(returncode=-11, stdout="native crash"),
        ):
            result = run_evaluator_subprocess(
                EvaluationRequest(design_name="d", output_dir=tmp),
                "pin_rudy", entry="evaluate.py",
            )
        self.assertEqual(result.status, "failed")
        self.assertIn("status -11", result.error)


if __name__ == "__main__":
    unittest.main()
