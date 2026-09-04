#!/usr/bin/env python3
"""
Run RUPlace routability-quality validation against DREAMPlace and Xplace.

The runner creates comparable ISPD18 LEF/DEF configs, runs DREAMPlace
variants, evaluates their GP DEFs with Xplace GGR, runs an Xplace inflation
baseline, and writes CSV/Markdown reports plus a quality-gate verdict.
"""

import argparse
import csv
import datetime
import json
import math
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
PARAMS_JSON = REPO_ROOT / "dreamplace" / "params.json"


def _load_params_defaults(path=PARAMS_JSON):
    """Read the DREAMPlace parameter defaults out of ``dreamplace/params.json``."""
    with open(path) as stream:
        raw = json.load(stream)
    return {key: entry.get("default") for key, entry in raw.items()}


PARAMS_DEFAULTS = _load_params_defaults()


def params_default(key):
    """Return the ``dreamplace/params.json`` default for ``key``.

    Every RUPlace argparse default and every RUPlace ``getattr`` fallback in this
    driver goes through here, so the driver and params.json cannot drift apart.
    Explicit command-line flags still override the value.
    """
    if key not in PARAMS_DEFAULTS:
        raise KeyError("unknown DREAMPlace parameter %r (not in %s)" % (key, PARAMS_JSON))
    return PARAMS_DEFAULTS[key]


PILOT_DESIGNS = ["ispd18_test1", "ispd18_test2", "ispd18_test3"]
FULL_DESIGNS = ["ispd18_test%d" % i for i in range(1, 11)]
DEFAULT_METHODS = ["input_ggr", "dp_hpwl", "dp_rudy", "ruplace", "xplace_inflate"]
RUPLACE_METHODS = {
    "ruplace",
    "ruplace_no_route_opt",
    "ruplace_inflation",
    "ruplace_inflation_admm",
}
DREAMPLACE_METHODS = {"dp_hpwl", "dp_rudy", *RUPLACE_METHODS}
REFERENCE_DEF_METHODS = {"innovus_2d_place", "innovus_2d_route"}
VALID_METHODS = set(DEFAULT_METHODS) | RUPLACE_METHODS | REFERENCE_DEF_METHODS
COMPARISON_BASELINES = [
    "innovus_2d_place",
    "innovus_2d_route",
    "xplace_inflate",
    "dp_hpwl",
    "dp_rudy",
]
METRIC_KEYS = [
    "route_ovfl_nets",
    "route_wl",
    "route_vias",
    "route_est_shorts",
    "rc_hor",
    "rc_ver",
]
PLACE_KEYS = ["place_hpwl"]
SUMMARY_KEYS = METRIC_KEYS + PLACE_KEYS
FIELDNAMES = [
    "design",
    "method",
    "status",
    *METRIC_KEYS,
    *PLACE_KEYS,
    "metric_source",
    "placed_def",
    "config_path",
    "log_path",
    "exp_dir",
    "elapsed_sec",
    "error",
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate RUPlace routability quality on ISPD18 designs."
    )
    design_group = parser.add_mutually_exclusive_group()
    design_group.add_argument(
        "--suite",
        choices=["pilot", "full"],
        default="pilot",
        help="pilot=test1-3, full=test1-10",
    )
    design_group.add_argument(
        "--designs",
        default="",
        help="Comma-separated design list, e.g. ispd18_test1,ispd18_test2.",
    )
    parser.add_argument(
        "--methods",
        default=",".join(DEFAULT_METHODS),
        help=(
            "Comma-separated methods: input_ggr,dp_hpwl,dp_rudy,ruplace,"
            "xplace_inflate,innovus_2d_place,innovus_2d_route,"
            "ruplace_no_route_opt,ruplace_inflation,ruplace_inflation_admm."
        ),
    )
    parser.add_argument(
        "--case-manifest",
        type=Path,
        default=None,
        help=(
            "JSON manifest for custom LEF/DEF/Verilog cases. If provided without "
            "--designs, all manifest cases are run."
        ),
    )
    parser.add_argument(
        "--manifest-path-map",
        action="append",
        default=[],
        help=(
            "Rewrite manifest path prefixes as OLD=NEW. May be repeated for "
            "remote runs where local absolute benchmark paths are mirrored elsewhere."
        ),
    )
    parser.add_argument("--xplace-root", type=Path, default=REPO_ROOT / "../Xplace")
    parser.add_argument("--result-root", type=Path, default=REPO_ROOT / "results" / "ruplace_quality")
    parser.add_argument("--run-id", default="", help="Stable run id. Default: timestamp.")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--random-seed", type=int, default=1000)
    parser.add_argument("--num-bins", type=int, default=512)
    parser.add_argument(
        "--eval-timeout-sec",
        type=int,
        default=0,
        help="Optional timeout for each embedded Xplace GGR evaluator subprocess.",
    )
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--density-weight", type=float, default=8e-5)
    parser.add_argument("--gp-gamma", type=float, default=4.0)
    parser.add_argument("--gp-noise-ratio", type=float, default=0.025)
    parser.add_argument("--target-density", type=float, default=1.0)
    parser.add_argument(
        "--ruplace-target-density-overrides",
        default="",
        help="Comma-separated RUPlace-only target-density overrides, e.g. ispd18_test8:1.10,ispd18_test9:1.10.",
    )
    parser.add_argument(
        "--ruplace-param-overrides",
        default="",
        help=(
            "Comma-separated RUPlace config overrides in design.param:value form, "
            "e.g. ispd18_test4.ruplace_local_inflate_max_rounds:1. "
            "Values are parsed as bool/int/float when possible."
        ),
    )
    parser.add_argument(
        "--ruplace-router-backend",
        choices=["xplace", "gpugr"],
        default=params_default("ruplace_router_backend"),
        help="Router backend used inside RUPlace optimization; final metrics still use the shared Xplace GGR evaluator.",
    )
    parser.add_argument(
        "--ruplace-gpugr-root",
        type=Path,
        default=None,
        help="Optional bundled GPUGR root for --ruplace-router-backend=gpugr.",
    )
    parser.add_argument("--stop-overflow", type=float, default=0.15)
    parser.add_argument(
        "--node-area-adjust-overflow",
        type=float,
        default=0.15,
        help=(
            "DREAMPlace node_area_adjust_overflow for the dp_rudy method: RUDY/pin "
            "area adjustment rounds run only while the density overflow is above this "
            "value. The DREAMPlace default (0.15) equals the default --stop-overflow, "
            "so on designs that stop right at the threshold dp_rudy performs a single "
            "adjustment round whose inflation is never exploited. Raise it (e.g. 0.25) "
            "to start adjusting earlier."
        ),
    )
    parser.add_argument(
        "--max-num-area-adjust",
        type=int,
        default=3,
        help=(
            "DREAMPlace max_num_area_adjust for the dp_rudy method: maximum number "
            "of RUDY/pin area adjustment rounds. 3 is the legacy hard-coded value."
        ),
    )
    parser.add_argument(
        "--legalize-flag",
        type=int,
        default=0,
        help=(
            "DREAMPlace legalize_flag for every DREAMPlace method (dp_hpwl/dp_rudy/ruplace*). "
            "0 = legacy GP-only DEF; 1 = run legalization before the solution DEF is written. "
            "abacus_legalize_flag is left at its params.json default."
        ),
    )
    parser.add_argument(
        "--detailed-place-flag",
        type=int,
        default=0,
        help=(
            "DREAMPlace detailed_place_flag for every DREAMPlace method (dp_hpwl/dp_rudy/ruplace*). "
            "0 = legacy, no detailed placement; 1 = run the internal ABCDPlace detailed placer "
            "(global_swap / k_reorder / independent_set_matching) after legalization and before the "
            "solution DEF is written. Default is hard-coded 0 (deliberately not read from "
            "params.json) so legacy behavior is stable regardless of params.json edits."
        ),
    )
    parser.add_argument("--route-rrr-iters", type=int, default=1)
    parser.add_argument(
        "--eval-route-rrr-iters",
        type=int,
        default=None,
        help=(
            "RRR iterations for final shared Xplace GGR evaluation. "
            "Defaults to --route-rrr-iters; set to 1 when using a stronger "
            "router only inside RUPlace optimization but keeping paper metrics comparable."
        ),
    )
    # Every --ruplace-* default below is read from dreamplace/params.json via
    # params_default() so the driver and params.json cannot drift apart.  Since
    # params.json ships the s14-calibrated congestion preset, running with no
    # --ruplace-* flag reproduces that preset; explicit flags still override.
    parser.add_argument(
        "--ruplace-inflation-effort",
        choices=["high", "medium", "low", "legacy"],
        default=params_default("ruplace_inflation_effort"),
        help="Adaptive inflation target level; legacy preserves fixed threshold/gamma behavior.",
    )
    parser.add_argument(
        "--ruplace-inflate-start-overflow",
        type=float,
        default=float(params_default("ruplace_inflate_start_overflow")),
        help="Density overflow threshold to start RUPlace route-driven inflation.",
    )
    parser.add_argument("--ruplace-max-inflate-ratio", type=float, default=float(params_default("ruplace_max_inflate_ratio")))
    parser.add_argument("--ruplace-min-inflate-ratio", type=float, default=float(params_default("ruplace_min_inflate_ratio")))
    parser.add_argument("--ruplace-global-inflate-gamma", type=float, default=float(params_default("ruplace_global_inflate_gamma")))
    parser.add_argument(
        "--ruplace-global-cluster-mode",
        default=params_default("ruplace_global_cluster_mode"),
        choices=["mean", "max", "none"],
        help="Cluster aggregation for global RUPlace inflation.",
    )
    parser.add_argument(
        "--ruplace-global-util-exponent",
        type=float,
        default=float(params_default("ruplace_global_util_exponent")),
        help="Exponent applied to route utilization excess before global inflation.",
    )
    parser.add_argument("--ruplace-local-inflate-gamma", type=float, default=float(params_default("ruplace_local_inflate_gamma")))
    parser.add_argument("--ruplace-inflate-area-cap", type=float, default=float(params_default("ruplace_inflate_area_cap")))
    parser.add_argument(
        "--ruplace-inflate-util-threshold",
        type=float,
        default=float(params_default("ruplace_inflate_util_threshold")),
        help=(
            "Route utilization fraction treated as congested by RUPlace inflation. "
            "Node utilization is divided by this before clamping at 1.0; 1.0 is legacy."
        ),
    )
    parser.add_argument("--ruplace-inflate-extra-capacity", type=float, default=float(params_default("ruplace_inflate_extra_capacity")))
    parser.add_argument("--ruplace-congested-uniform-inflate-ratio", type=float, default=float(params_default("ruplace_congested_uniform_inflate_ratio")))
    parser.add_argument(
        "--ruplace-hv-inflate-gamma",
        type=float,
        default=float(params_default("ruplace_hv_inflate_gamma")),
        help="Extra inflation pressure from H/V route overflow maps; 0 disables directional H/V-aware inflation.",
    )
    parser.add_argument(
        "--ruplace-hv-inflate-mode",
        default=params_default("ruplace_hv_inflate_mode"),
        choices=["max", "mean", "sum", "h", "v"],
        help="How to combine horizontal and vertical overflow for H/V-aware inflation.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage",
        type=float,
        default=float(params_default("ruplace_congestion_blockage")),
        help=(
            "Congestion-driven soft blockage: fraction of a bin's density capacity "
            "removed at full congestion, pushing cells out of congested bins with the "
            "electrostatic density force instead of inflating them. 0 disables."
        ),
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-threshold",
        type=float,
        default=float(params_default("ruplace_congestion_blockage_threshold")),
        help="Route utilization above which soft blockage starts ramping in.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-max",
        type=float,
        default=float(params_default("ruplace_congestion_blockage_max")),
        help="Per-bin cap on fixed occupancy + soft blockage, as a bin-capacity fraction.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-smooth",
        type=int,
        default=int(params_default("ruplace_congestion_blockage_smooth")),
        help="Box-blur radius, in density bins, applied to the soft-blockage map.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-decay",
        type=float,
        default=float(params_default("ruplace_congestion_blockage_decay")),
        help="Multiplier applied to the standing blockage map on each refresh.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-start-overflow",
        type=float,
        default=float(params_default("ruplace_congestion_blockage_start_overflow")),
        help="Only apply soft blockage once GP density overflow drops below this.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-refresh-interval",
        type=int,
        default=int(params_default("ruplace_congestion_blockage_refresh_interval")),
        help=(
            "Refresh the soft blockage every N area-adjust calls, independently of "
            "the cell-inflation schedule (forces a router / Innovus-proxy call when "
            "inflation produced no map). 0 keeps the legacy inflation-coupled refresh."
        ),
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-max-refreshes",
        type=int,
        default=int(params_default("ruplace_congestion_blockage_max_refreshes")),
        help="Cap on material soft-blockage map updates; 0 is unlimited.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-stop-overflow",
        type=float,
        default=float(params_default("ruplace_congestion_blockage_stop_overflow")),
        help="Stop refreshing the soft blockage once GP overflow falls below this; 0 never stops.",
    )
    parser.add_argument(
        "--ruplace-congestion-blockage-budget-mode",
        default=params_default("ruplace_congestion_blockage_budget_mode"),
        choices=["shared", "independent"],
        help=(
            "Charge the blocked area against the filler budget and the inflation "
            "whitespace budget (shared, default) or against the filler budget only "
            "(independent)."
        ),
    )
    # ---- plugin pipeline (dreamplace/ops/routability_opt/pipeline.py) -----------------
    # A non-empty --ruplace-plugins makes build_routability_opt_op() return
    # RoutabilityOptimizationPipeline INSTEAD OF RUPlaceController, so the legacy
    # inflation / soft-blockage / ADMM flags above are inert on such a run.
    parser.add_argument(
        "--ruplace-plugins",
        default="",
        help=(
            "Comma-separated routability plugin names (e.g. net_weighting). Empty "
            "(default) keeps the legacy RUPlace controller; non-empty REPLACES it "
            "with the plugin pipeline, which has no inflation, no soft blockage and "
            "no ADMM."
        ),
    )
    parser.add_argument(
        "--ruplace-proxy",
        default=params_default("ruplace_proxy"),
        help="Congestion proxy for the plugin pipeline: gpugr, xplace, innovus, rudy, pin_density, nctugr, rudy_pin.",
    )
    parser.add_argument(
        "--ruplace-proxy-refresh-interval",
        type=int,
        default=int(params_default("ruplace_proxy_refresh_interval")),
        help="Objective evaluations between congestion-proxy refreshes (each refresh is one router call).",
    )
    parser.add_argument(
        "--ruplace-plugin-start-overflow",
        type=float,
        default=float(params_default("ruplace_plugin_start_overflow")),
        help="Density overflow at or below which pipeline plugins become active; 1.0 = always on.",
    )
    parser.add_argument("--ruplace-net-weight-freq", type=int, default=int(params_default("ruplace_net_weight_freq")))
    parser.add_argument("--ruplace-net-weight-gamma", type=float, default=float(params_default("ruplace_net_weight_gamma")))
    parser.add_argument("--ruplace-net-weight-decay", type=float, default=float(params_default("ruplace_net_weight_decay")))
    parser.add_argument("--ruplace-net-weight-min-ratio", type=float, default=float(params_default("ruplace_net_weight_min_ratio")))
    parser.add_argument("--ruplace-net-weight-max", type=float, default=float(params_default("ruplace_net_weight_max")))
    parser.add_argument(
        "--ruplace-net-weight-normalization",
        default=params_default("ruplace_net_weight_normalization"),
        choices=["absolute", "design_mean"],
    )
    parser.add_argument(
        "--ruplace-net-weight-phase",
        default=params_default("ruplace_net_weight_phase"),
        choices=["post_gradient", "pre_objective"],
    )
    parser.add_argument(
        "--ruplace-net-weight-score-mode",
        default=params_default("ruplace_net_weight_score_mode"),
        choices=["pin_mean", "bbox_mean", "bbox_pmean"],
    )
    parser.add_argument("--ruplace-net-weight-bbox-power", type=float, default=float(params_default("ruplace_net_weight_bbox_power")))
    parser.add_argument(
        "--ruplace-net-weight-direction-mode",
        default=params_default("ruplace_net_weight_direction_mode"),
        choices=["aggregate", "max_hv", "mean_hv", "horizontal", "vertical"],
    )
    parser.add_argument("--ruplace-net-weight-smooth", type=int, default=int(params_default("ruplace_net_weight_smooth")))
    parser.add_argument("--ruplace-local-inflate-max-rounds", type=int, default=int(params_default("ruplace_local_inflate_max_rounds")))
    parser.add_argument(
        "--ruplace-allow-shrink",
        type=int,
        choices=[0, 1],
        default=int(params_default("ruplace_allow_shrink")),
        help="Allow local adjustment to shrink over-inflated cells toward original size.",
    )
    # ---- RUPlace GR map + grid knobs. ----
    parser.add_argument(
        "--ruplace-gr-util-mode",
        choices=["legacy", "avail"],
        default=params_default("ruplace_gr_util_mode"),
        help="Congestion definition for the RUPlace GR maps: legacy (dmd/cap) or avail "
             "((dmd-fixed)/(cap-fixed)).  Also forwarded to the DEF eval path.",
    )
    parser.add_argument(
        "--ruplace-gr-grid",
        default=params_default("ruplace_gr_grid"),
        help="GR gcell grid for RUPlace methods: 'bins', 'def' (use the DEF "
             "GCELLGRID) or an explicit 'NxM' such as 625x650.  'def'/'NxM' are also "
             "honoured by the DEF eval path.",
    )
    parser.add_argument(
        "--ruplace-write-guides",
        type=int,
        choices=[0, 1],
        default=int(params_default("ruplace_write_guides")),
        help="1 = the router writes a route guide file each evaluation; 0 = skip it.",
    )
    parser.add_argument(
        "--ruplace-gr-wire-cost-sat",
        type=int,
        choices=[0, 1],
        default=int(params_default("ruplace_gr_wire_cost_sat")),
        help="1 = saturate the pattern-router int64->int wire-cost difference at INF instead "
             "of letting it overflow (recovers long nets that otherwise report `failed`).",
    )
    parser.add_argument(
        "--ruplace-gr-via-usage-scale",
        type=float,
        default=float(params_default("ruplace_gr_via_usage_scale")),
        help="GGR viaUsageScale for RUPlace methods (1.5 = ISPD18 calibration, 0 = no extra via demand).",
    )
    parser.add_argument(
        "--ruplace-gr-m1-routable",
        type=int,
        choices=[0, 1],
        default=int(params_default("ruplace_gr_m1_routable")),
        help="1 = GGR may route on M1; 0 = M1 unroutable (the SMIC14 setting).",
    )
    parser.add_argument(
        "--ruplace-gr-max-route-len-per-pin",
        type=int,
        default=int(params_default("ruplace_gr_max_route_len_per_pin")),
        help="GGR maxRouteLenPerPin in gcells (130 = ISPD18 calibration, 256 for the coarse s14 grid).",
    )
    # ---- Innovus early-global-route in-loop proxy (Phase 2 lever 1). ----
    parser.add_argument(
        "--ruplace-inflate-proxy",
        choices=["gpugr", "innovus", "both"],
        default=params_default("ruplace_inflate_proxy"),
        help="Congestion map RUPlace inflation optimizes against: gpugr (default), "
             "innovus (Innovus early global route -- the signal that scores the run), or "
             "both (Innovus for inflation, GPUGR still for ADMM).  innovus/both need "
             "--ruplace-inflation-effort legacy and add one ~60-100 s Innovus call per "
             "inflation round.",
    )
    parser.add_argument(
        "--ruplace-innovus-proxy-min-interval",
        type=int,
        default=int(params_default("ruplace_innovus_proxy_min_interval")),
        help="Minimum placement iterations between two Innovus eGR calls; an inflation "
             "round asking sooner reuses the cached map.",
    )
    parser.add_argument(
        "--ruplace-innovus-case",
        default=params_default("ruplace_innovus_case"),
        help="s14 case for the Innovus proxy scorer; empty derives it from the input DEF "
             "via data/s14/*.meta.json.",
    )
    parser.add_argument(
        "--ruplace-innovus-proxy-workdir",
        default=params_default("ruplace_innovus_proxy_workdir"),
        help="Directory for Innovus proxy call artifacts; empty uses "
             "<result_dir>/<design>/ruplace/innovus.",
    )
    parser.add_argument("--ruplace-local-ovfl-nets-stop", type=float, default=float(params_default("ruplace_local_ovfl_nets_stop")))
    parser.add_argument("--ruplace-local-est-shorts-stop", type=float, default=float(params_default("ruplace_local_est_shorts_stop")))
    parser.add_argument(
        "--ruplace-gpu-lock-mode",
        choices=["call", "run", "none"],
        default=str(params_default("ruplace_gpu_lock_mode")),
        help="Granularity of the exclusive GPU lock: call = per GPU router call "
             "(default, lets concurrent workers share the GPU), run = hold it for "
             "the whole global placement, none = never lock.",
    )
    parser.add_argument(
        "--ruplace-external-route-eval",
        type=int,
        choices=[0, 1],
        default=int(params_default("ruplace_external_route_eval")),
        help="1 = subprocess Xplace GGR eval; 0 = in-process ADMM route gradients.",
    )
    parser.add_argument(
        "--ruplace-admm-start-overflow",
        type=float,
        default=float(params_default("ruplace_admm_start_overflow")),
        help="Density overflow threshold to start RUPlace routed-wire ADMM refinement.",
    )
    parser.add_argument("--ruplace-admm-route-freq", type=int, default=int(params_default("ruplace_admm_route_freq")))
    parser.add_argument(
        "--ruplace-admm-apply-freq",
        type=int,
        default=int(params_default("ruplace_admm_apply_freq")),
        help="Placement-iteration interval for applying RUPlace ADMM gradients.",
    )
    parser.add_argument("--ruplace-admm-weight", type=float, default=float(params_default("ruplace_admm_weight")))
    parser.add_argument(
        "--ruplace-admm-weight-decay",
        type=float,
        default=float(params_default("ruplace_admm_weight_decay")),
        help="Multiplicative decay of the RUPlace ADMM gradient weight after each application.",
    )
    parser.add_argument(
        "--ruplace-admm-min-weight",
        type=float,
        default=float(params_default("ruplace_admm_min_weight")),
        help="Minimum decayed RUPlace ADMM gradient weight; 0 disables the floor.",
    )
    parser.add_argument(
        "--ruplace-admm-grad-clip-norm",
        type=float,
        default=float(params_default("ruplace_admm_grad_clip_norm")),
        help="Global norm for clipping RUPlace ADMM gradients before weighting; 0 disables clipping.",
    )
    parser.add_argument("--ruplace-admm-anchor-weight", type=float, default=float(params_default("ruplace_admm_anchor_weight")))
    parser.add_argument(
        "--ruplace-admm-anchor-update",
        choices=["refresh", "static", "ema"],
        default=params_default("ruplace_admm_anchor_update"),
        help="Anchor update policy for RUPlace ADMM route gradients.",
    )
    parser.add_argument(
        "--ruplace-admm-anchor-decay",
        type=float,
        default=float(params_default("ruplace_admm_anchor_decay")),
        help="EMA decay for ADMM anchor update when --ruplace-admm-anchor-update=ema.",
    )
    parser.add_argument(
        "--dreamplace-entry",
        type=Path,
        default=REPO_ROOT / "install" / "dreamplace" / "Placer.py",
        help="DREAMPlace Placer.py to execute after install/build.",
    )
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Do not launch placements; refresh CSV/report from an existing raw_metrics.csv.",
    )
    parser.add_argument("--fail-on-gate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def parse_eval_args(argv):
    parser = argparse.ArgumentParser(description="Internal Xplace GGR DEF evaluator.")
    parser.add_argument("--_eval-def", type=Path, required=True)
    parser.add_argument("--_eval-lef", type=Path, action="append", required=True)
    parser.add_argument("--_eval-verilog", type=Path, default=None)
    parser.add_argument("--_eval-design", required=True)
    parser.add_argument("--_eval-xplace-root", type=Path, required=True)
    parser.add_argument("--_eval-gpu", type=int, default=0)
    parser.add_argument("--_eval-num-threads", type=int, default=8)
    parser.add_argument("--_eval-num-bins", type=int, default=512)
    parser.add_argument("--_eval-route-rrr-iters", type=int, default=1)
    # RUPlace batch 2: A1/A2 knobs.  Defaults reproduce the legacy eval path exactly.
    parser.add_argument("--_eval-util-mode", dest="_eval_util_mode",
                        choices=["legacy", "avail"], default="legacy")
    parser.add_argument("--_eval-gr-grid", dest="_eval_gr_grid", default="")
    # When set, the bundled GPUGR root is used instead of --_eval-xplace-root for
    # the native extensions, the flute tables and the IOParser.  Empty keeps the
    # legacy external-Xplace behaviour byte for byte.
    parser.add_argument("--_eval-gpugr-root", dest="_eval_gpugr_root", default="")
    return parser.parse_args(argv)


def expand_designs(suite, designs):
    if designs:
        return [name.strip() for name in designs.split(",") if name.strip()]
    return list(PILOT_DESIGNS if suite == "pilot" else FULL_DESIGNS)


def _apply_path_maps(value, path_maps):
    text = os.path.expandvars(os.path.expanduser(str(value)))
    for old, new in path_maps or []:
        if text == old or text.startswith(old.rstrip("/") + "/"):
            return new.rstrip("/") + text[len(old.rstrip("/")) :]
    return text


def parse_path_maps(specs):
    maps = []
    for spec in specs or []:
        if "=" not in spec:
            raise ValueError("--manifest-path-map must use OLD=NEW form, got %s" % spec)
        old, new = spec.split("=", 1)
        maps.append(
            (
                os.path.expandvars(os.path.expanduser(old.rstrip("/"))),
                os.path.expandvars(os.path.expanduser(new.rstrip("/"))),
            )
        )
    return maps


def _resolve_manifest_path(value, base_dir, path_maps=None):
    path = Path(_apply_path_maps(value, path_maps))
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _resolve_manifest_globs(patterns, base_dir, path_maps=None):
    paths = []
    for pattern in _as_list(patterns):
        raw = Path(_apply_path_maps(pattern, path_maps))
        if raw.is_absolute():
            matches = sorted(raw.parent.glob(raw.name))
        else:
            matches = sorted(base_dir.glob(str(raw)))
        if not matches:
            raise FileNotFoundError("Manifest glob matched no files: %s" % pattern)
        paths.extend(p.resolve() for p in matches)
    return paths


def _dedup_paths(paths):
    result = []
    seen = set()
    for path in paths:
        resolved = Path(path).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _validate_taiwei_2d_case(name, case):
    """Keep TaiWei expansion on 2D handoff artifacts, not pseudo-3D outputs."""
    source = str(case.get("source", ""))
    if not source.startswith("taiwei"):
        return

    def_path = Path(case["def_input"])
    if def_path.name != "2_2_floorplan_io.def":
        raise ValueError(
            "TaiWei case %s must use 2D floorplan DEF 2_2_floorplan_io.def, got %s"
            % (name, def_path)
        )

    forbidden = {
        "3_place.def",
        "4_cts.def",
        "5_route.def",
        "3_place.v",
        "4_cts.v",
        "5_route.v",
    }
    paths = [def_path]
    paths.extend(Path(p) for p in case.get("lef_input", []))
    for key in ("verilog_input", "eval_verilog_input", "reference_route_def"):
        value = case.get(key)
        if value:
            paths.append(Path(value))
    paths.extend(Path(p) for p in (case.get("reference_defs") or {}).values())

    for artifact in paths:
        text = str(artifact)
        lowered = text.lower()
        if artifact.name in forbidden or "_3d.fp.def" in lowered or "_3d.tmp.def" in lowered:
            raise ValueError(
                "TaiWei case %s uses generated 3D/final artifact %s; use only "
                "LEF + 2_2_floorplan_io.def + 1_synth.v/sanitized netlist"
                % (name, artifact)
            )
        if artifact.suffix == ".lef" and any(token in lowered for token in ("cover", "_upper", "_bottom")):
            raise ValueError(
                "TaiWei case %s uses tier/cover LEF %s; use 2D technology/cell LEFs only"
                % (name, artifact)
            )


def load_case_manifest(path, path_maps=None):
    if path is None:
        return {}
    path = path.resolve()
    base_dir = path.parent
    data = json.loads(path.read_text())
    cases = data.get("cases", data if isinstance(data, list) else [])
    if not isinstance(cases, list):
        raise ValueError("Case manifest must contain a 'cases' list: %s" % path)

    case_map = {}
    for raw_case in cases:
        case = dict(raw_case)
        if case.get("enabled", True) is False:
            continue
        name = case.get("name") or case.get("design")
        if not name:
            raise ValueError("Manifest case missing 'name' or 'design': %s" % raw_case)
        lefs = case.get("lef_input", case.get("lefs"))
        if not lefs:
            raise ValueError("Manifest case %s missing lef_input/lefs" % name)
        lef_paths = [_resolve_manifest_path(p, base_dir, path_maps) for p in _as_list(lefs)]
        lef_paths.extend(_resolve_manifest_globs(case.get("lef_globs", []), base_dir, path_maps))
        def_input = case.get("def_input", case.get("def"))
        if not def_input:
            raise ValueError("Manifest case %s missing def_input/def" % name)

        normalized = {
            "name": name,
            "design_name": case.get("design_name", name),
            "benchmark": case.get("benchmark", "dreamplace"),
            "lef_input": _dedup_paths(lef_paths),
            "def_input": _resolve_manifest_path(def_input, base_dir, path_maps),
            "verilog_input": "",
            "eval_verilog_input": "",
            "dreamplace_verilog_input": case.get("dreamplace_verilog_input", True),
            "placement_enabled": case.get("placement_enabled", True),
            "source": case.get("source", "manifest"),
            "notes": case.get("notes", ""),
            "reference_defs": {},
        }
        if case.get("verilog_input", case.get("verilog")):
            normalized["verilog_input"] = str(
                _resolve_manifest_path(
                    case.get("verilog_input", case.get("verilog")), base_dir, path_maps
                )
            )
        eval_verilog = case.get("eval_verilog_input") or case.get("original_verilog_input")
        if eval_verilog:
            normalized["eval_verilog_input"] = str(
                _resolve_manifest_path(eval_verilog, base_dir, path_maps)
            )
        for key in ("tech", "stage", "reference_route_def"):
            if key in case:
                normalized[key] = case[key]
        if "reference_route_def" in normalized:
            normalized["reference_route_def"] = str(
                _resolve_manifest_path(normalized["reference_route_def"], base_dir, path_maps)
            )
        for ref_name, ref_path in dict(case.get("reference_defs", {})).items():
            normalized["reference_defs"][ref_name] = str(
                _resolve_manifest_path(ref_path, base_dir, path_maps)
            )
        _validate_taiwei_2d_case(name, normalized)
        missing = [str(p) for p in normalized["lef_input"] + [normalized["def_input"]] if not p.exists()]
        if normalized["verilog_input"] and not Path(normalized["verilog_input"]).exists():
            missing.append(normalized["verilog_input"])
        if normalized["eval_verilog_input"] and not Path(normalized["eval_verilog_input"]).exists():
            missing.append(normalized["eval_verilog_input"])
        for ref_path in normalized.get("reference_defs", {}).values():
            if not Path(ref_path).exists():
                missing.append(ref_path)
        if missing:
            raise FileNotFoundError("Manifest case %s has missing files: %s" % (name, ", ".join(missing)))
        case_map[name] = normalized
    return case_map


def get_case(args, design):
    case_map = getattr(args, "case_map", {})
    if design in case_map:
        return case_map[design]
    lef, deffile = xplace_design_paths(args.xplace_root, design)
    return {
        "name": design,
        "design_name": design,
        "benchmark": "ispd2018",
        "lef_input": [lef],
        "def_input": deffile,
        "verilog_input": "",
        "source": "xplace_data",
    }


def parse_methods(methods):
    parsed = [name.strip() for name in methods.split(",") if name.strip()]
    unknown = sorted(set(parsed) - VALID_METHODS)
    if unknown:
        raise ValueError("Unknown methods: %s" % ", ".join(unknown))
    return parsed


def parse_density_overrides(text):
    overrides = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError("Bad density override '%s'; expected design:value" % item)
        design, value = item.split(":", 1)
        overrides[design.strip()] = float(value)
    return overrides


def parse_override_value(value):
    value = value.strip()
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return int(lowered == "true")
    try:
        if re.fullmatch(r"[-+]?\d+", value):
            return int(value)
        return float(value)
    except ValueError:
        return value


def parse_ruplace_plugin_list(value):
    """Normalize --ruplace-plugins into the JSON list dreamplace expects.

    dreamplace/ops/routability_opt/plugins.parse_plugin_names() also accepts a
    comma-separated string, but writing a real list keeps the emitted config
    self-describing and keeps an empty selection falsy (legacy controller).
    """
    if isinstance(value, (list, tuple)):
        items = [str(name).strip() for name in value]
    else:
        items = [name.strip() for name in str(value or "").split(",")]
    names = [name.lower() for name in items if name]
    if len(names) != len(set(names)):
        raise ValueError("--ruplace-plugins contains duplicate names: %s" % value)
    return names


def parse_ruplace_param_overrides(text):
    overrides = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                "Bad RUPlace override '%s'; expected design.param:value" % item
            )
        lhs, value = item.split(":", 1)
        if "." not in lhs:
            raise ValueError(
                "Bad RUPlace override '%s'; expected design.param:value" % item
            )
        design, key = lhs.split(".", 1)
        design = design.strip()
        key = key.strip()
        if not design or not key:
            raise ValueError(
                "Bad RUPlace override '%s'; expected design.param:value" % item
            )
        if key != "target_density" and not key.startswith("ruplace_"):
            raise ValueError(
                "RUPlace override key '%s' must be target_density or start with ruplace_" % key
            )
        overrides.setdefault(design, {})[key] = parse_override_value(value)
    return overrides


def xplace_design_paths(xplace_root, design):
    data_dir = Path(xplace_root).resolve() / "data"
    lef = data_dir / ("%s.input.lef" % design)
    deffile = data_dir / ("%s.input.def" % design)
    if not lef.exists() or not deffile.exists():
        raise FileNotFoundError("Missing ISPD18 inputs for %s under %s" % (design, data_dir))
    return lef, deffile


def build_dreamplace_config(args, design, method, result_dir):
    case = get_case(args, design)
    lefs = case["lef_input"]
    deffile = case["def_input"]
    stage = {
        "num_bins_x": args.num_bins,
        "num_bins_y": args.num_bins,
        "iteration": args.iterations,
        "learning_rate": getattr(args, "learning_rate", 0.01),
        "wirelength": "weighted_average",
        "optimizer": "nesterov",
    }
    target_density = args.target_density
    if method in RUPLACE_METHODS:
        target_density = parse_density_overrides(args.ruplace_target_density_overrides).get(
            design, target_density
        )
        target_density = parse_ruplace_param_overrides(
            getattr(args, "ruplace_param_overrides", "")
        ).get(design, {}).get("target_density", target_density)
    cfg = {
        "lef_input": [str(lef) for lef in lefs],
        "def_input": str(deffile),
        "gpu": 1,
        "num_bins_x": args.num_bins,
        "num_bins_y": args.num_bins,
        "global_place_stages": [stage],
        "target_density": target_density,
        "density_weight": getattr(args, "density_weight", 8e-5),
        "gamma": getattr(args, "gp_gamma", 4.0),
        "random_seed": args.random_seed,
        "ignore_net_degree": 100,
        "enable_fillers": 1,
        "gp_noise_ratio": getattr(args, "gp_noise_ratio", 0.025),
        "global_place_flag": 1,
        "legalize_flag": int(getattr(args, "legalize_flag", 0)),
        "detailed_place_flag": int(getattr(args, "detailed_place_flag", 0)),
        "stop_overflow": args.stop_overflow,
        "dtype": "float32",
        "plot_flag": 0,
        "random_center_init_flag": 1,
        "sort_nets_by_degree": 0,
        "num_threads": args.num_threads,
        "deterministic_flag": 0,
        "routability_opt_flag": 0,
        "ruplace_flag": 0,
        "result_dir": str(result_dir),
    }
    if case.get("verilog_input") and case.get("dreamplace_verilog_input", True):
        cfg["verilog_input"] = str(case["verilog_input"])
    if case.get("eval_verilog_input"):
        cfg["ruplace_eval_verilog_input"] = str(case["eval_verilog_input"])
    if method == "dp_rudy":
        cfg.update(
            {
                "routability_opt_flag": 1,
                "adjust_nctugr_area_flag": 0,
                "adjust_rudy_area_flag": 1,
                "adjust_pin_area_flag": 1,
                "max_num_area_adjust": int(getattr(args, "max_num_area_adjust", 3)),
                "node_area_adjust_overflow": float(
                    getattr(args, "node_area_adjust_overflow", 0.15)
                ),
                "route_num_bins_x": args.num_bins,
                "route_num_bins_y": args.num_bins,
            }
        )
    elif method in {"ruplace", "ruplace_inflation", "ruplace_inflation_admm"}:
        external_route_eval = args.ruplace_external_route_eval
        if method == "ruplace_inflation":
            external_route_eval = 1
        elif method == "ruplace_inflation_admm":
            external_route_eval = 0
        cfg.update(
            {
                "routability_opt_flag": 1,
                "ruplace_flag": 1,
                "ruplace_xplace_root": str(Path(args.xplace_root).resolve()),
                "ruplace_router_backend": getattr(args, "ruplace_router_backend", params_default("ruplace_router_backend")),
                "ruplace_route_gpu": getattr(args, "gpu", 0),
                "ruplace_gpu_lock_mode": getattr(
                    args, "ruplace_gpu_lock_mode", params_default("ruplace_gpu_lock_mode")
                ),
                "ruplace_gr_rrr_iters": args.route_rrr_iters,
                "ruplace_gr_util_mode": getattr(args, "ruplace_gr_util_mode", params_default("ruplace_gr_util_mode")),
                "ruplace_gr_grid": getattr(args, "ruplace_gr_grid", params_default("ruplace_gr_grid")),
                "ruplace_write_guides": int(getattr(args, "ruplace_write_guides", params_default("ruplace_write_guides"))),
                "ruplace_gr_wire_cost_sat": int(getattr(args, "ruplace_gr_wire_cost_sat", params_default("ruplace_gr_wire_cost_sat"))),
                "ruplace_gr_via_usage_scale": float(getattr(args, "ruplace_gr_via_usage_scale", params_default("ruplace_gr_via_usage_scale"))),
                "ruplace_gr_m1_routable": int(getattr(args, "ruplace_gr_m1_routable", params_default("ruplace_gr_m1_routable"))),
                "ruplace_gr_max_route_len_per_pin": int(
                    getattr(args, "ruplace_gr_max_route_len_per_pin", params_default("ruplace_gr_max_route_len_per_pin"))
                ),
                "ruplace_inflate_proxy": getattr(args, "ruplace_inflate_proxy", params_default("ruplace_inflate_proxy")),
                "ruplace_innovus_proxy_min_interval": int(
                    getattr(args, "ruplace_innovus_proxy_min_interval",
                            params_default("ruplace_innovus_proxy_min_interval"))
                ),
                "ruplace_innovus_case": getattr(args, "ruplace_innovus_case", params_default("ruplace_innovus_case")),
                "ruplace_innovus_proxy_workdir": getattr(
                    args, "ruplace_innovus_proxy_workdir", params_default("ruplace_innovus_proxy_workdir")
                ),
                "ruplace_external_route_eval": external_route_eval,
                "ruplace_inflate_start_overflow": args.ruplace_inflate_start_overflow,
                "ruplace_inflation_effort": getattr(
                    args, "ruplace_inflation_effort", params_default("ruplace_inflation_effort")
                ),
                "ruplace_max_inflate_ratio": args.ruplace_max_inflate_ratio,
                "ruplace_min_inflate_ratio": args.ruplace_min_inflate_ratio,
                "ruplace_global_inflate_gamma": args.ruplace_global_inflate_gamma,
                "ruplace_global_cluster_mode": getattr(args, "ruplace_global_cluster_mode", params_default("ruplace_global_cluster_mode")),
                "ruplace_global_util_exponent": getattr(args, "ruplace_global_util_exponent", params_default("ruplace_global_util_exponent")),
                "ruplace_local_inflate_gamma": args.ruplace_local_inflate_gamma,
                "ruplace_inflate_area_cap": args.ruplace_inflate_area_cap,
                "ruplace_inflate_util_threshold": getattr(
                    args, "ruplace_inflate_util_threshold", 1.0
                ),
                "ruplace_inflate_extra_capacity": args.ruplace_inflate_extra_capacity,
                "ruplace_congested_uniform_inflate_ratio": args.ruplace_congested_uniform_inflate_ratio,
                "ruplace_hv_inflate_gamma": getattr(args, "ruplace_hv_inflate_gamma", params_default("ruplace_hv_inflate_gamma")),
                "ruplace_hv_inflate_mode": getattr(args, "ruplace_hv_inflate_mode", params_default("ruplace_hv_inflate_mode")),
                "ruplace_congestion_blockage": getattr(
                    args, "ruplace_congestion_blockage", params_default("ruplace_congestion_blockage")
                ),
                "ruplace_congestion_blockage_threshold": getattr(
                    args,
                    "ruplace_congestion_blockage_threshold",
                    params_default("ruplace_congestion_blockage_threshold"),
                ),
                "ruplace_congestion_blockage_max": getattr(
                    args,
                    "ruplace_congestion_blockage_max",
                    params_default("ruplace_congestion_blockage_max"),
                ),
                "ruplace_congestion_blockage_smooth": getattr(
                    args,
                    "ruplace_congestion_blockage_smooth",
                    params_default("ruplace_congestion_blockage_smooth"),
                ),
                "ruplace_congestion_blockage_decay": getattr(
                    args,
                    "ruplace_congestion_blockage_decay",
                    params_default("ruplace_congestion_blockage_decay"),
                ),
                "ruplace_congestion_blockage_start_overflow": getattr(
                    args,
                    "ruplace_congestion_blockage_start_overflow",
                    params_default("ruplace_congestion_blockage_start_overflow"),
                ),
                "ruplace_congestion_blockage_refresh_interval": getattr(
                    args,
                    "ruplace_congestion_blockage_refresh_interval",
                    params_default("ruplace_congestion_blockage_refresh_interval"),
                ),
                "ruplace_congestion_blockage_max_refreshes": getattr(
                    args,
                    "ruplace_congestion_blockage_max_refreshes",
                    params_default("ruplace_congestion_blockage_max_refreshes"),
                ),
                "ruplace_congestion_blockage_stop_overflow": getattr(
                    args,
                    "ruplace_congestion_blockage_stop_overflow",
                    params_default("ruplace_congestion_blockage_stop_overflow"),
                ),
                "ruplace_congestion_blockage_budget_mode": getattr(
                    args,
                    "ruplace_congestion_blockage_budget_mode",
                    params_default("ruplace_congestion_blockage_budget_mode"),
                ),
                "ruplace_local_inflate_max_rounds": args.ruplace_local_inflate_max_rounds,
                "ruplace_allow_shrink": args.ruplace_allow_shrink,
                "ruplace_local_ovfl_nets_stop": args.ruplace_local_ovfl_nets_stop,
                "ruplace_local_est_shorts_stop": args.ruplace_local_est_shorts_stop,
                "ruplace_admm_start_overflow": args.ruplace_admm_start_overflow,
                "ruplace_admm_route_freq": args.ruplace_admm_route_freq,
                "ruplace_admm_apply_freq": getattr(args, "ruplace_admm_apply_freq", params_default("ruplace_admm_apply_freq")),
                "ruplace_admm_weight": args.ruplace_admm_weight,
                "ruplace_admm_weight_decay": getattr(args, "ruplace_admm_weight_decay", params_default("ruplace_admm_weight_decay")),
                "ruplace_admm_min_weight": getattr(args, "ruplace_admm_min_weight", params_default("ruplace_admm_min_weight")),
                "ruplace_admm_grad_clip_norm": getattr(args, "ruplace_admm_grad_clip_norm", params_default("ruplace_admm_grad_clip_norm")),
                "ruplace_admm_anchor_weight": args.ruplace_admm_anchor_weight,
                "ruplace_admm_anchor_update": getattr(args, "ruplace_admm_anchor_update", params_default("ruplace_admm_anchor_update")),
                "ruplace_admm_anchor_decay": getattr(args, "ruplace_admm_anchor_decay", params_default("ruplace_admm_anchor_decay")),
                # ---- plugin pipeline ------------------------------------------------
                # A non-empty list selects RoutabilityOptimizationPipeline instead of
                # RUPlaceController (dreamplace/ops/routability_opt/__init__.py), which
                # drops legacy inflation, soft blockage and ADMM for this run.
                "ruplace_plugins": parse_ruplace_plugin_list(
                    getattr(args, "ruplace_plugins", "")
                ),
                "ruplace_proxy": getattr(args, "ruplace_proxy", params_default("ruplace_proxy")),
                "ruplace_proxy_refresh_interval": int(getattr(
                    args, "ruplace_proxy_refresh_interval",
                    params_default("ruplace_proxy_refresh_interval"),
                )),
                "ruplace_plugin_start_overflow": float(getattr(
                    args, "ruplace_plugin_start_overflow",
                    params_default("ruplace_plugin_start_overflow"),
                )),
                "ruplace_net_weight_freq": int(getattr(
                    args, "ruplace_net_weight_freq", params_default("ruplace_net_weight_freq")
                )),
                "ruplace_net_weight_gamma": float(getattr(
                    args, "ruplace_net_weight_gamma", params_default("ruplace_net_weight_gamma")
                )),
                "ruplace_net_weight_decay": float(getattr(
                    args, "ruplace_net_weight_decay", params_default("ruplace_net_weight_decay")
                )),
                "ruplace_net_weight_min_ratio": float(getattr(
                    args, "ruplace_net_weight_min_ratio",
                    params_default("ruplace_net_weight_min_ratio"),
                )),
                "ruplace_net_weight_max": float(getattr(
                    args, "ruplace_net_weight_max", params_default("ruplace_net_weight_max")
                )),
                "ruplace_net_weight_normalization": getattr(
                    args, "ruplace_net_weight_normalization",
                    params_default("ruplace_net_weight_normalization"),
                ),
                "ruplace_net_weight_phase": getattr(
                    args, "ruplace_net_weight_phase", params_default("ruplace_net_weight_phase")
                ),
                "ruplace_net_weight_score_mode": getattr(
                    args, "ruplace_net_weight_score_mode",
                    params_default("ruplace_net_weight_score_mode"),
                ),
                "ruplace_net_weight_bbox_power": float(getattr(
                    args, "ruplace_net_weight_bbox_power",
                    params_default("ruplace_net_weight_bbox_power"),
                )),
                "ruplace_net_weight_direction_mode": getattr(
                    args, "ruplace_net_weight_direction_mode",
                    params_default("ruplace_net_weight_direction_mode"),
                ),
                "ruplace_net_weight_smooth": int(getattr(
                    args, "ruplace_net_weight_smooth", params_default("ruplace_net_weight_smooth")
                )),
            }
        )
        gpugr_root = getattr(args, "ruplace_gpugr_root", None)
        if gpugr_root:
            cfg["ruplace_gpugr_root"] = str(Path(gpugr_root).resolve())
        cfg.update(
            parse_ruplace_param_overrides(getattr(args, "ruplace_param_overrides", "")).get(
                design, {}
            )
        )
    return cfg


def run_command(cmd, cwd, log_path, env=None, dry_run=False):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        log.write("$ %s\n\n" % " ".join(str(x) for x in cmd))
        if dry_run:
            log.write("[dry-run] command not executed\n")
            return 0, 0.0
        start = datetime.datetime.now()
        proc = subprocess.run(
            [str(x) for x in cmd],
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        elapsed = (datetime.datetime.now() - start).total_seconds()
        log.write("\n[returncode] %d\n[elapsed_sec] %.3f\n" % (proc.returncode, elapsed))
        return proc.returncode, elapsed


def xplace_env(xplace_root):
    env = os.environ.copy()
    py_paths = [str(xplace_root.resolve())]
    old = env.get("PYTHONPATH")
    if old:
        py_paths.append(old)
    env["PYTHONPATH"] = os.pathsep.join(py_paths)
    return env


def dreamplace_env():
    env = os.environ.copy()
    py_paths = [str(REPO_ROOT / "install"), str(REPO_ROOT / "install" / "dreamplace")]
    old = env.get("PYTHONPATH")
    if old:
        py_paths.append(old)
    env["PYTHONPATH"] = os.pathsep.join(py_paths)
    return env


def find_dreamplace_def(result_dir, design):
    # DREAMPlace (Placer.py) writes exactly one solution DEF, <design>.gp.def, *after*
    # NonLinearPlace has already run legalization, so with legalize_flag=1 the legalized
    # placement lands in that same .gp.def. Some flows emit an explicit .lg.def; prefer it
    # when present, fall back to .gp.def, and log which suffix was picked.
    expected_design_name = "%s.input" % design
    for suffix in ("lg", "gp"):
        expected = result_dir / expected_design_name / ("%s.%s.def" % (expected_design_name, suffix))
        if expected.exists():
            print("[def-select] %s.def (expected path): %s" % (suffix, expected))
            return expected
    for suffix in ("lg", "gp"):
        matches = sorted(
            result_dir.glob("**/*.%s.def" % suffix), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if matches:
            print("[def-select] %s.def (glob): %s" % (suffix, matches[0]))
            return matches[0]
    return None


def parse_xplace_metrics(log_path):
    metrics = {key: "" for key in METRIC_KEYS}
    if not Path(log_path).exists():
        return metrics
    pattern = re.compile(
        r"#OvflNets:\s*(\d+).*GR WL:\s*([0-9.]+),\s*GR #Vias:\s*([0-9.]+),"
        r"\s*#EstShorts:\s*([0-9.]+),\s*RC Hor:\s*([0-9.]+),\s*RC Ver:\s*([0-9.]+)"
    )
    with Path(log_path).open("r", errors="ignore") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                values = match.groups()
                for key, value in zip(METRIC_KEYS, values):
                    metrics[key] = value
    return metrics


def parse_direct_metrics(log_path):
    metrics = {key: "" for key in METRIC_KEYS}
    if not Path(log_path).exists():
        return metrics
    marker = re.compile(r"RUPLACE_GGR_METRICS_JSON\s+(\{.*\})")
    with Path(log_path).open("r", errors="ignore") as f:
        for line in f:
            match = marker.search(line)
            if not match:
                continue
            data = json.loads(match.group(1))
            for key in METRIC_KEYS:
                if key in data:
                    metrics[key] = str(data[key])
    return metrics


def parse_place_hpwl(log_path):
    hpwl = ""
    if not Path(log_path).exists():
        return hpwl
    patterns = [
        re.compile(r"After GP, best solution eval, exact HPWL:\s*([0-9.+\-Ee]+)"),
        re.compile(r"GP Stop!.*masked_hpwl:\s*([0-9.+\-Ee]+)"),
        re.compile(r"\bwHPWL\s+([0-9.+\-Ee]+)"),
    ]
    with Path(log_path).open("r", errors="ignore") as f:
        for line in f:
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    hpwl = match.group(1)
                    break
    return hpwl


def refresh_place_hpwl(row, run_dir):
    if row.get("place_hpwl"):
        return row

    candidates = []
    log_path = row.get("log_path")
    if log_path:
        candidates.append(Path(log_path))

    method = row.get("method", "")
    if method in DREAMPLACE_METHODS:
        config_path = row.get("config_path")
        if config_path:
            candidates.append(Path(config_path).parent / "dreamplace.log")
        exp_dir = row.get("exp_dir")
        if exp_dir:
            candidates.append(Path(exp_dir) / "dreamplace.log")
    elif method == "xplace_inflate":
        if log_path:
            candidates.append(Path(log_path).parent / "xplace.log")
        design = row.get("design", "")
        if design:
            candidates.append(run_dir / "xplace" / "xplace_inflate" / design / "xplace.log")

    for candidate in candidates:
        hpwl = parse_place_hpwl(candidate)
        if hpwl:
            row["place_hpwl"] = hpwl
            break
    return row


def load_existing_rows(run_dir):
    csv_path = run_dir / "raw_metrics.csv"
    if not csv_path.exists():
        raise FileNotFoundError("Missing existing metrics CSV: %s" % csv_path)
    rows = []
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            for key in FIELDNAMES:
                row.setdefault(key, "")
            rows.append(refresh_place_hpwl(row, run_dir))
    return rows


def run_command_capture(cmd, cwd, log_path, env=None, dry_run=False, timeout_sec=0):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        log.write("$ %s\n\n" % " ".join(str(x) for x in cmd))
        if dry_run:
            log.write("[dry-run] command not executed\n")
            return 0, 0.0
        start = datetime.datetime.now()
        try:
            proc = subprocess.run(
                [str(x) for x in cmd],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                timeout=timeout_sec if timeout_sec and timeout_sec > 0 else None,
            )
            elapsed = (datetime.datetime.now() - start).total_seconds()
            log.write(proc.stdout)
            log.write("\n[returncode] %d\n[elapsed_sec] %.3f\n" % (proc.returncode, elapsed))
            return proc.returncode, elapsed
        except subprocess.TimeoutExpired as exc:
            elapsed = (datetime.datetime.now() - start).total_seconds()
            if exc.stdout:
                log.write(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="ignore"))
            log.write("\n[timeout_sec] %d\n[returncode] 124\n[elapsed_sec] %.3f\n" % (timeout_sec, elapsed))
            return 124, elapsed


def parse_xplace_exp_dir(log_path, xplace_root=None):
    text = Path(log_path).read_text(errors="ignore") if Path(log_path).exists() else ""
    match = re.search(r"log file at ([^\s]+/log/test\.log)", text)
    if match:
        path = Path(match.group(1))
        if not path.is_absolute():
            # Xplace logs its experiment dir relative to its own cwd, which is
            # --xplace-root; REPO_ROOT/../Xplace is wrong from a worktree checkout.
            root = Path(xplace_root) if xplace_root else REPO_ROOT / "../Xplace"
            path = (root / path).resolve()
        return str(path.parents[1])
    return ""


def find_xplace_def(exp_dir):
    if not exp_dir:
        return ""
    output_dir = Path(exp_dir) / "output"
    matches = sorted(output_dir.glob("*.def"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(matches[0]) if matches else ""


def run_dreamplace(args, run_dir, design, method):
    case = get_case(args, design)
    if not case.get("placement_enabled", True):
        row = {
            "design": design,
            "method": method,
            "status": "skipped",
            "metric_source": "manifest",
            "config_path": "",
            "log_path": "",
            "exp_dir": "",
            "placed_def": "",
            "elapsed_sec": "",
            "error": "placement_enabled=false",
        }
        row.update({key: "" for key in METRIC_KEYS})
        row.update({key: "" for key in PLACE_KEYS})
        return row
    if not case.get("dreamplace_verilog_input", True) and not def_has_regular_nets(case["def_input"]):
        row = {
            "design": design,
            "method": method,
            "status": "skipped",
            "metric_source": "manifest",
            "config_path": "",
            "log_path": "",
            "exp_dir": "",
            "placed_def": "",
            "elapsed_sec": "",
            "error": "DREAMPlace disabled: DEF has no NETS and dreamplace_verilog_input=false",
        }
        row.update({key: "" for key in METRIC_KEYS})
        row.update({key: "" for key in PLACE_KEYS})
        return row
    method_dir = run_dir / "dreamplace" / method / design
    result_dir = method_dir / "results"
    config_path = method_dir / ("%s_%s.json" % (design, method))
    log_path = method_dir / "dreamplace.log"
    metric_path = method_dir / "xplace_ggr_metrics.json"
    if args.skip_existing and metric_path.exists():
        return json.loads(metric_path.read_text())

    method_dir.mkdir(parents=True, exist_ok=True)
    cfg = build_dreamplace_config(args, design, method, result_dir)
    config_path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")

    row = {
        "design": design,
        "method": method,
        "status": "ok",
        "metric_source": "xplace_ggr",
        "config_path": str(config_path),
        "log_path": str(log_path),
        "exp_dir": str(method_dir),
        "placed_def": "",
        "elapsed_sec": "",
        "error": "",
    }
    row.update({key: "" for key in METRIC_KEYS})
    row.update({key: "" for key in PLACE_KEYS})
    cmd = [sys.executable, str(args.dreamplace_entry), str(config_path)]
    rc, elapsed = run_command(cmd, REPO_ROOT, log_path, env=dreamplace_env(), dry_run=args.dry_run)
    row["elapsed_sec"] = "%.3f" % elapsed
    row["place_hpwl"] = parse_place_hpwl(log_path)
    if rc != 0:
        row["status"] = "failed(%d)" % rc
        row["error"] = "DREAMPlace run failed"
        metric_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        return row

    placed_def = find_dreamplace_def(result_dir, design)
    if not placed_def:
        row["status"] = "failed"
        row["error"] = "DREAMPlace GP DEF not found under %s" % result_dir
        metric_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        return row
    row["placed_def"] = str(placed_def)

    eval_log = method_dir / "xplace_ggr_eval.log"
    eval_rc, eval_elapsed = run_xplace_eval(args, design, placed_def, method_dir, eval_log)
    row["elapsed_sec"] = "%.3f" % (elapsed + eval_elapsed)
    if eval_rc != 0:
        row["status"] = "failed(%d)" % eval_rc
        row["error"] = "Xplace GGR eval failed"
    row.update(parse_direct_metrics(eval_log))
    if row["status"] == "ok" and not row.get("route_wl"):
        row["status"] = "failed(0)"
        row["error"] = "Xplace GGR eval produced no metrics"
    row["log_path"] = str(eval_log)
    metric_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    return row


def xplace_custom_path(args, design, def_path=None):
    lef, original_def = xplace_design_paths(args.xplace_root, design)
    deffile = def_path if def_path is not None else original_def
    return "lef:%s,def:%s,design_name:%s,benchmark:ispd2018" % (
        Path(lef).resolve(),
        Path(deffile).resolve(),
        design,
    )


def write_xplace_custom_json(args, design, path, def_path=None):
    case = get_case(args, design)
    data = {
        "benchmark": case.get("benchmark", "dreamplace"),
        "design_name": case.get("design_name", design),
        "lefs": [str(Path(lef).resolve()) for lef in case["lef_input"]],
        "def": str(Path(def_path if def_path is not None else case["def_input"]).resolve()),
    }
    eval_verilog = case.get("eval_verilog_input") or case.get("verilog_input")
    if eval_verilog:
        data["verilog"] = str(Path(eval_verilog).resolve())
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def def_has_regular_nets(def_path):
    try:
        with Path(def_path).open("r", errors="ignore") as f:
            for line in f:
                if line.startswith("NETS "):
                    return True
                if line.startswith("END DESIGN"):
                    return False
    except OSError:
        return False
    return False


def resolve_eval_gpugr_root(args):
    """Bundled GPUGR root to evaluate with, or "" to keep the external Xplace.

    Only used when the run itself routes with the bundled backend
    (--ruplace-router-backend gpugr) or explicitly names a root
    (--ruplace-gpugr-root); otherwise the legacy external-Xplace eval is kept.
    """
    configured = str(getattr(args, "ruplace_gpugr_root", "") or "")
    backend = str(getattr(args, "ruplace_router_backend", params_default("ruplace_router_backend")) or "xplace")
    if backend != "gpugr" and not configured:
        return ""
    install_dir = str(REPO_ROOT / "install")
    added = install_dir not in sys.path
    if added:
        sys.path.insert(0, install_dir)
    try:
        from dreamplace.ops.gpugr.gpugr_backend import BundledGPUGRBackend

        return str(BundledGPUGRBackend.resolve_bundle_root(configured))
    except Exception as e:
        print("WARN: could not resolve bundled GPUGR root for eval (%s); "
              "falling back to --xplace-root" % e)
        return str(Path(configured).resolve()) if configured else ""
    finally:
        if added and install_dir in sys.path:
            sys.path.remove(install_dir)


def run_xplace_eval(args, design, placed_def, work_dir, log_path, use_verilog=True):
    case = get_case(args, design)
    eval_rrr_iters = getattr(args, "eval_route_rrr_iters", None)
    if eval_rrr_iters is None:
        eval_rrr_iters = args.route_rrr_iters
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_eval-def",
        str(Path(placed_def).resolve()),
        "--_eval-design",
        case.get("design_name", design),
        "--_eval-xplace-root",
        str(args.xplace_root.resolve()),
        "--_eval-gpu",
        str(args.gpu),
        "--_eval-num-threads",
        str(args.num_threads),
        "--_eval-num-bins",
        str(args.num_bins),
        "--_eval-route-rrr-iters",
        str(eval_rrr_iters),
    ]
    eval_gpugr_root = resolve_eval_gpugr_root(args)
    if eval_gpugr_root:
        cmd.extend(["--_eval-gpugr-root", eval_gpugr_root])
    eval_util_mode = getattr(args, "ruplace_gr_util_mode", params_default("ruplace_gr_util_mode")) or "legacy"
    if eval_util_mode != "legacy":
        cmd.extend(["--_eval-util-mode", str(eval_util_mode)])
    eval_grid = str(getattr(args, "ruplace_gr_grid", params_default("ruplace_gr_grid")) or "bins")
    if eval_grid.strip().lower() not in ("", "bins", "legacy"):
        cmd.extend(["--_eval-gr-grid", eval_grid])
    for lef in case["lef_input"]:
        cmd.extend(["--_eval-lef", str(Path(lef).resolve())])
    eval_verilog = case.get("eval_verilog_input") or case.get("verilog_input")
    if use_verilog and eval_verilog:
        cmd.extend(["--_eval-verilog", str(Path(eval_verilog).resolve())])
    eval_env = xplace_env(args.xplace_root)
    # The evaluator subprocess has no params object; it reads this instead.
    eval_env["RUPLACE_GPU_LOCK_MODE"] = str(
        getattr(args, "ruplace_gpu_lock_mode", params_default("ruplace_gpu_lock_mode"))
    )
    return run_command_capture(
        cmd,
        REPO_ROOT,
        log_path,
        env=eval_env,
        dry_run=args.dry_run,
        timeout_sec=getattr(args, "eval_timeout_sec", 0),
    )


def run_xplace_baseline(args, run_dir, design):
    method = "xplace_inflate"
    method_dir = run_dir / "xplace" / method / design
    log_path = method_dir / "xplace.log"
    metric_path = method_dir / "xplace_metrics.json"
    if args.skip_existing and metric_path.exists():
        return json.loads(metric_path.read_text())

    method_dir.mkdir(parents=True, exist_ok=True)
    result_dir = method_dir / "results"
    custom_json = method_dir / ("%s_xplace_input.json" % design)
    row = {
        "design": design,
        "method": method,
        "status": "ok",
        "metric_source": "xplace_log",
        "config_path": "",
        "log_path": str(log_path),
        "exp_dir": "",
        "placed_def": "",
        "elapsed_sec": "",
        "error": "",
    }
    row.update({key: "" for key in METRIC_KEYS})
    row.update({key: "" for key in PLACE_KEYS})
    cmd = [
        sys.executable,
        "main.py",
        "--load_from_raw",
        "True",
        "--use_cell_inflate",
        "True",
        "--legalization",
        "False",
        "--detail_placement",
        "False",
        "--write_placement",
        "True",
        "--write_global_placement",
        "True",
        "--final_route_eval",
        "True",
        "--inner_iter",
        str(args.iterations),
        "--num_bin_x",
        str(args.num_bins),
        "--num_bin_y",
        str(args.num_bins),
        "--gpu",
        str(args.gpu),
        "--num_threads",
        str(args.num_threads),
        "--result_dir",
        str(result_dir),
        "--output_prefix",
        method,
        "--exp_id",
        "_quality_%s_%s" % (design, method),
    ]
    if getattr(args, "case_map", {}) and design in args.case_map:
        write_xplace_custom_json(args, design, custom_json)
        cmd.extend(["--custom_json", str(custom_json)])
    else:
        cmd.extend(
            [
                "--dataset",
                "ispd2018",
                "--design_name",
                design,
                "--custom_path",
                xplace_custom_path(args, design),
            ]
        )
    rc, elapsed = run_command(
        cmd,
        args.xplace_root.resolve(),
        log_path,
        env=xplace_env(args.xplace_root),
        dry_run=args.dry_run,
    )
    row["elapsed_sec"] = "%.3f" % elapsed
    row.update(parse_xplace_metrics(log_path))
    row["place_hpwl"] = parse_place_hpwl(log_path)
    exp_dir = parse_xplace_exp_dir(log_path, args.xplace_root)
    row["exp_dir"] = exp_dir
    row["placed_def"] = find_xplace_def(exp_dir)
    if row["placed_def"]:
        eval_log = method_dir / "xplace_ggr_eval.log"
        eval_rc, eval_elapsed = run_xplace_eval(args, design, row["placed_def"], method_dir, eval_log)
        row["elapsed_sec"] = "%.3f" % (elapsed + eval_elapsed)
        direct_metrics = parse_direct_metrics(eval_log)
        if direct_metrics.get("route_ovfl_nets"):
            row.update(direct_metrics)
            row["metric_source"] = "xplace_ggr_on_output"
            row["log_path"] = str(eval_log)
        elif eval_rc != 0:
            row["status"] = "failed(%d)" % eval_rc
            row["error"] = "Xplace output GGR eval failed"
    if row["status"] == "ok" and rc != 0 and row["metric_source"] == "xplace_ggr_on_output":
        row["error"] = "Xplace returned %d after placement; using output DEF eval" % rc
    elif row["status"] == "ok" and rc != 0:
        row["error"] = "Xplace returned %d after metrics were logged" % rc
    if row["status"] == "ok" and not row.get("route_ovfl_nets"):
        row["status"] = "failed(%d)" % rc
        row["error"] = "Xplace baseline metrics unavailable"
    metric_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    return row


def run_input_ggr(args, run_dir, design):
    method = "input_ggr"
    case = get_case(args, design)
    method_dir = run_dir / "input_ggr" / method / design
    log_path = method_dir / "xplace_ggr_eval.log"
    metric_path = method_dir / "input_ggr_metrics.json"
    if args.skip_existing and metric_path.exists():
        return json.loads(metric_path.read_text())

    method_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "design": design,
        "method": method,
        "status": "ok",
        "metric_source": "xplace_ggr_input",
        "config_path": "",
        "log_path": str(log_path),
        "exp_dir": str(method_dir),
        "placed_def": str(case["def_input"]),
        "elapsed_sec": "",
        "error": "",
    }
    row.update({key: "" for key in METRIC_KEYS})
    row.update({key: "" for key in PLACE_KEYS})
    rc, elapsed = run_xplace_eval(args, design, case["def_input"], method_dir, log_path)
    row["elapsed_sec"] = "%.3f" % elapsed
    if rc != 0:
        row["status"] = "failed(%d)" % rc
        row["error"] = "Xplace GGR input eval failed"
    row.update(parse_direct_metrics(log_path))
    if row["status"] == "ok" and not row.get("route_wl"):
        row["status"] = "failed(0)"
        row["error"] = "Xplace GGR input eval produced no metrics"
    metric_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    return row


def run_reference_def(args, run_dir, design, method):
    case = get_case(args, design)
    method_dir = run_dir / "reference" / method / design
    log_path = method_dir / "xplace_ggr_eval.log"
    metric_path = method_dir / ("%s_metrics.json" % method)
    if args.skip_existing and metric_path.exists():
        return json.loads(metric_path.read_text())

    row = {
        "design": design,
        "method": method,
        "status": "skipped",
        "metric_source": "manifest",
        "config_path": "",
        "log_path": str(log_path),
        "exp_dir": str(method_dir),
        "placed_def": "",
        "elapsed_sec": "",
        "error": "reference DEF not provided",
    }
    row.update({key: "" for key in METRIC_KEYS})
    row.update({key: "" for key in PLACE_KEYS})

    ref_def = case.get("reference_defs", {}).get(method, "")
    if not ref_def:
        method_dir.mkdir(parents=True, exist_ok=True)
        metric_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        return row

    method_dir.mkdir(parents=True, exist_ok=True)
    row.update(
        {
            "status": "ok",
            "metric_source": "xplace_ggr_reference",
            "placed_def": str(ref_def),
            "error": "",
        }
    )
    # Routed or post-place Innovus DEFs usually carry regular NETS; avoid
    # reparsing the large synthesized Verilog when the DEF is self-contained.
    rc, elapsed = run_xplace_eval(
        args,
        design,
        ref_def,
        method_dir,
        log_path,
        use_verilog=not def_has_regular_nets(ref_def),
    )
    row["elapsed_sec"] = "%.3f" % elapsed
    if rc != 0:
        row["status"] = "failed(%d)" % rc
        row["error"] = "Xplace GGR reference eval failed"
    row.update(parse_direct_metrics(log_path))
    if row["status"] == "ok" and not row.get("route_wl"):
        row["status"] = "failed(0)"
        row["error"] = "Xplace GGR reference eval produced no metrics"
    metric_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    return row


def numeric(row, key):
    try:
        value = row.get(key, "")
        return None if value == "" else float(value)
    except (TypeError, ValueError):
        return None


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def safe_ratio(num, den):
    if num is None or den is None:
        return None
    if den == 0:
        return 1.0 if num == 0 else float("inf")
    return num / den


def gate_summary(rows):
    ok = [r for r in rows if r.get("status") == "ok"]
    by_method = {}
    by_design_method = {}
    for row in ok:
        by_method.setdefault(row["method"], []).append(row)
        by_design_method[(row["design"], row["method"])] = row

    medians = {}
    for method, method_rows in by_method.items():
        medians[method] = {key: median(numeric(row, key) for row in method_rows) for key in SUMMARY_KEYS}

    dreamplace_baseline_pass = {}
    for baseline in ["dp_hpwl", "dp_rudy"]:
        ru = medians.get("ruplace", {})
        base = medians.get(baseline, {})
        ovfl_better = (
            ru.get("route_ovfl_nets") is not None
            and base.get("route_ovfl_nets") is not None
            and ru["route_ovfl_nets"] < base["route_ovfl_nets"]
        )
        shorts_better = (
            ru.get("route_est_shorts") is not None
            and base.get("route_est_shorts") is not None
            and ru["route_est_shorts"] < base["route_est_shorts"]
        )
        dreamplace_baseline_pass[baseline] = ovfl_better or shorts_better

    compared = 0
    improved = 0
    for design in sorted({row["design"] for row in ok}):
        ru = by_design_method.get((design, "ruplace"))
        base = by_design_method.get((design, "dp_rudy"))
        if not ru or not base:
            continue
        compared += 1
        ru_ovfl, base_ovfl = numeric(ru, "route_ovfl_nets"), numeric(base, "route_ovfl_nets")
        ru_short, base_short = numeric(ru, "route_est_shorts"), numeric(base, "route_est_shorts")
        if None in (ru_ovfl, base_ovfl, ru_short, base_short):
            continue
        strictly_better = ru_ovfl < base_ovfl or ru_short < base_short
        zero_tie = base_ovfl == 0 and base_short == 0 and ru_ovfl == 0 and ru_short == 0
        if strictly_better or zero_tie:
            improved += 1
    improve_rate = improved / compared if compared else None

    x_ratios = {}
    x_ratio_means = {}
    x_ratio_max = {}
    for key in ["route_ovfl_nets", "route_est_shorts", "route_wl", "place_hpwl"]:
        ratios = []
        for design in sorted({row["design"] for row in ok}):
            ru = by_design_method.get((design, "ruplace"))
            xp = by_design_method.get((design, "xplace_inflate"))
            if ru and xp:
                ratios.append(safe_ratio(numeric(ru, key), numeric(xp, key)))
        x_ratios[key] = median(ratios)
        finite = [r for r in ratios if r is not None and r != float("inf")]
        x_ratio_means[key] = (sum(finite) / len(finite)) if finite else None
        x_ratio_max[key] = max(ratios) if ratios else None

    gate = {
        "validation_role": "fallback_reference",
        "golden_validated": False,
        "verdict_scope": "reference_screening_only",
        "medians": medians,
        "dreamplace_baseline_pass": dreamplace_baseline_pass,
        "dp_rudy_improved": improved,
        "dp_rudy_compared": compared,
        "dp_rudy_improve_rate": improve_rate,
        "xplace_median_ratios": x_ratios,
        "xplace_mean_ratios": x_ratio_means,
        "xplace_max_ratios": x_ratio_max,
    }
    gate["pass"] = (
        all(dreamplace_baseline_pass.values())
        and improve_rate is not None
        and improve_rate >= 0.70
        and x_ratios.get("route_ovfl_nets") is not None
        and x_ratios["route_ovfl_nets"] <= 1.20
        and x_ratios.get("route_est_shorts") is not None
        and x_ratios["route_est_shorts"] <= 1.20
        and x_ratios.get("route_wl") is not None
        and x_ratios["route_wl"] <= 1.20
        and x_ratios.get("place_hpwl") is not None
        and x_ratios["place_hpwl"] <= 1.20
    )
    return gate


def ruplace_ratio_stats(rows, baselines, keys):
    ok = [r for r in rows if r.get("status") == "ok"]
    by_design_method = {(r["design"], r["method"]): r for r in ok}
    designs = sorted({row["design"] for row in ok})
    stats = {}
    for baseline in baselines:
        stats[baseline] = {}
        for key in keys:
            ratios = []
            better = 0
            tie = 0
            worse = 0
            total_ru = 0.0
            total_base = 0.0
            for design in designs:
                ru = by_design_method.get((design, "ruplace"))
                base = by_design_method.get((design, baseline))
                if ru and base:
                    ru_value = numeric(ru, key)
                    base_value = numeric(base, key)
                    ratios.append(safe_ratio(ru_value, base_value))
                    if ru_value is not None and base_value is not None:
                        total_ru += ru_value
                        total_base += base_value
                        if ru_value < base_value:
                            better += 1
                        elif ru_value == base_value:
                            tie += 1
                        else:
                            worse += 1
            finite = [r for r in ratios if r is not None and r != float("inf")]
            stats[baseline][key] = {
                "count": len(ratios),
                "median": median(ratios),
                "mean": (sum(finite) / len(finite)) if finite else None,
                "max": max(ratios) if ratios else None,
                "total_ratio": safe_ratio(total_ru, total_base) if total_base else None,
                "total_ruplace": total_ru if total_base else None,
                "total_baseline": total_base if total_base else None,
                "better": better,
                "tie": tie,
                "worse": worse,
            }
    return stats


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in FIELDNAMES})


def format_float(value, digits=3):
    if value is None:
        return "NA"
    if value == float("inf"):
        return "inf"
    return ("%%.%df" % digits) % value


def format_delta_percent(ratio, digits=1):
    if ratio is None:
        return "NA"
    if ratio == float("inf"):
        return "inf"
    return ("%+.*f%%" % (digits, (ratio - 1.0) * 100.0))


def format_signed_value(value, digits=0):
    if value is None:
        return "NA"
    return ("%+.*f" % (digits, value))


def write_report(path, args, run_dir, rows, gate):
    wl_stats = ruplace_ratio_stats(rows, COMPARISON_BASELINES, ["route_wl", "place_hpwl"])
    lines = [
        "# RUPlace Quality Report",
        "",
        "- Run directory: `%s`" % run_dir,
        "- Designs: `%s`" % ", ".join(sorted({row["design"] for row in rows})),
        "- Methods: `%s`" % ", ".join(sorted({row["method"] for row in rows})),
        "- Iterations: `%d`" % args.iterations,
        "- GPUGR reference screening: `%s`" % ("PASS" if gate["pass"] else "FAIL"),
        "- Golden validation: `NOT RUN` (requires OpenROAD or Innovus)",
        "",
        "## Quality Gates",
        "",
        "| Gate | Result |",
        "| --- | --- |",
    ]
    for baseline, passed in gate["dreamplace_baseline_pass"].items():
        lines.append("| Median RUPlace better than `%s` on OvflNets or EstShorts | %s |" % (baseline, "PASS" if passed else "FAIL"))
    rate = gate["dp_rudy_improve_rate"]
    lines.append(
        "| Per-design RUPlace improvement or zero-congestion tie vs `dp_rudy` >= 70%% | %s (%d/%d, %s) |"
        % (
            "PASS" if rate is not None and rate >= 0.70 else "FAIL",
            gate["dp_rudy_improved"],
            gate["dp_rudy_compared"],
            format_float(rate * 100 if rate is not None else None, 1) + "%",
        )
    )
    for key, ratio in gate["xplace_median_ratios"].items():
        lines.append(
            "| Median RUPlace/Xplace `%s` <= 1.20 | %s (%s) |"
            % (key, "PASS" if ratio is not None and ratio <= 1.20 else "FAIL", format_float(ratio))
        )
    lines.append(
        "| Mean RUPlace/Xplace `route_wl` <= 1.20 | %s (%s) |"
        % (
            "PASS"
            if gate.get("xplace_mean_ratios", {}).get("route_wl") is not None
            and gate["xplace_mean_ratios"]["route_wl"] <= 1.20
            else "FAIL",
            format_float(gate.get("xplace_mean_ratios", {}).get("route_wl")),
        )
    )
    lines.append(
        "| Max RUPlace/Xplace `route_wl` <= 1.40 | %s (%s) |"
        % (
            "PASS"
            if gate.get("xplace_max_ratios", {}).get("route_wl") is not None
            and gate["xplace_max_ratios"]["route_wl"] <= 1.40
            else "FAIL",
            format_float(gate.get("xplace_max_ratios", {}).get("route_wl")),
        )
    )

    lines.extend(["", "## Median Metrics", "", "| Method | OvflNets | EstShorts | GR WL | Place HPWL | Vias | RC Hor | RC Ver |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for method in sorted(gate["medians"]):
        med = gate["medians"][method]
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s |"
            % (
                method,
                format_float(med.get("route_ovfl_nets"), 0),
                format_float(med.get("route_est_shorts"), 0),
                format_float(med.get("route_wl"), 0),
                format_float(med.get("place_hpwl"), 0),
                format_float(med.get("route_vias"), 0),
                format_float(med.get("rc_hor")),
                format_float(med.get("rc_ver")),
            )
        )

    lines.extend(
        [
            "",
            "## Wirelength Comparison",
            "",
            "Lower is better. GR WL is measured by the same Xplace GGR evaluator on each output DEF; Place HPWL is parsed from each placer log.",
            "",
            "| Baseline | Metric | Count | RU Better/Tie/Worse | Median Ratio | Mean Ratio | Total Ratio | Mean Delta | Max Ratio |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    baseline_labels = {
        "innovus_2d_place": "Innovus 2D Place",
        "innovus_2d_route": "Innovus 2D Route",
        "xplace_inflate": "Xplace",
        "dp_hpwl": "DREAMPlace HPWL",
        "dp_rudy": "DREAMPlace RUDY",
    }
    metric_labels = {"route_wl": "GR WL", "place_hpwl": "Place HPWL"}
    for baseline in COMPARISON_BASELINES:
        for key in ["route_wl", "place_hpwl"]:
            stat = wl_stats.get(baseline, {}).get(key, {})
            lines.append(
                "| %s | %s | %d | %d/%d/%d | %s | %s | %s | %s | %s |"
                % (
                    baseline_labels[baseline],
                    metric_labels[key],
                    stat.get("count", 0),
                    stat.get("better", 0),
                    stat.get("tie", 0),
                    stat.get("worse", 0),
                    format_float(stat.get("median")),
                    format_float(stat.get("mean")),
                    format_float(stat.get("total_ratio")),
                    format_delta_percent(stat.get("mean")),
                    format_float(stat.get("max")),
                )
            )
    lines.extend(
        [
            "",
            "## Absolute Wirelength Totals",
            "",
            "| Baseline | Metric | RUPlace Total | Baseline Total | RUPlace/Baseline |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for baseline in COMPARISON_BASELINES:
        for key in ["route_wl", "place_hpwl"]:
            stat = wl_stats.get(baseline, {}).get(key, {})
            lines.append(
                "| %s | %s | %s | %s | %s |"
                % (
                    baseline_labels[baseline],
                    metric_labels[key],
                    format_float(stat.get("total_ruplace"), 0),
                    format_float(stat.get("total_baseline"), 0),
                    format_float(stat.get("total_ratio")),
                )
            )

    ok_by_design_method = {
        (row["design"], row["method"]): row for row in rows if row.get("status") == "ok"
    }
    lines.extend(
        [
            "",
            "## Per-Design Wirelength Comparison",
            "",
            "Ratios and deltas use RUPlace divided by or minus the named baseline. The `Lowest GPUGR-reference WL` column is diagnostic only and does not declare a method winner.",
            "",
            "| Design | RU GR WL | vs Xplace | Delta | vs DREAMPlace RUDY | Delta | RU Place HPWL | vs Xplace HPWL | Lowest GPUGR-reference WL |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    method_labels = {
        "dp_hpwl": "DREAMPlace HPWL",
        "dp_rudy": "DREAMPlace RUDY",
        "ruplace": "RUPlace",
        "ruplace_no_route_opt": "RUPlace no route opt",
        "ruplace_inflation": "RUPlace inflation",
        "ruplace_inflation_admm": "RUPlace inflation + ADMM",
        "xplace_inflate": "Xplace",
        "innovus_2d_place": "Innovus 2D Place",
        "innovus_2d_route": "Innovus 2D Route",
    }
    for design in sorted({row["design"] for row in rows}):
        ru = ok_by_design_method.get((design, "ruplace"))
        xp = ok_by_design_method.get((design, "xplace_inflate"))
        dp = ok_by_design_method.get((design, "dp_rudy"))
        if not ru:
            continue
        wl_values = []
        for method in [
            "innovus_2d_place",
            "innovus_2d_route",
            "dp_hpwl",
            "dp_rudy",
            "ruplace",
            "ruplace_no_route_opt",
            "ruplace_inflation",
            "ruplace_inflation_admm",
            "xplace_inflate",
        ]:
            row = ok_by_design_method.get((design, method))
            value = numeric(row, "route_wl") if row else None
            if value is not None:
                wl_values.append((value, method))
        best_wl, best_method = min(wl_values) if wl_values else (None, "")
        ru_wl = numeric(ru, "route_wl")
        xp_wl = numeric(xp, "route_wl") if xp else None
        dp_wl = numeric(dp, "route_wl") if dp else None
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s%s |"
            % (
                design,
                format_float(ru_wl, 0),
                format_float(safe_ratio(ru_wl, xp_wl) if xp else None),
                format_signed_value(ru_wl - xp_wl if ru_wl is not None and xp_wl is not None else None, 0),
                format_float(safe_ratio(ru_wl, dp_wl) if dp else None),
                format_signed_value(ru_wl - dp_wl if ru_wl is not None and dp_wl is not None else None, 0),
                format_float(numeric(ru, "place_hpwl"), 0),
                format_float(safe_ratio(numeric(ru, "place_hpwl"), numeric(xp, "place_hpwl")) if xp else None),
                method_labels.get(best_method, best_method),
                " (%s)" % format_float(best_wl, 0) if best_wl is not None else "",
            )
        )

    lines.extend(["", "## Per-Design Results", "", "| Design | Method | Status | OvflNets | EstShorts | GR WL | Place HPWL | Source |", "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |"])
    for row in sorted(rows, key=lambda r: (r["design"], r["method"])):
        lines.append(
            "| `%s` | `%s` | `%s` | %s | %s | %s | %s | `%s` |"
            % (
                row["design"],
                row["method"],
                row.get("status", ""),
                row.get("route_ovfl_nets", ""),
                row.get("route_est_shorts", ""),
                row.get("route_wl", ""),
                row.get("place_hpwl", ""),
                row.get("metric_source", ""),
            )
        )

    ratio_rows = []
    for design in sorted({row["design"] for row in rows}):
        ru = ok_by_design_method.get((design, "ruplace"))
        xp = ok_by_design_method.get((design, "xplace_inflate"))
        dp = ok_by_design_method.get((design, "dp_rudy"))
        if not ru:
            continue
        ratio_rows.append((design, ru, xp, dp))
    if ratio_rows:
        lines.extend(
            [
                "",
                "## RUPlace Comparison Ratios",
                "",
                "| Design | vs Xplace OvflNets | vs Xplace EstShorts | vs Xplace RC-H | vs Xplace RC-V | vs Xplace GR WL | vs Xplace Place HPWL | vs dp_hpwl GR WL | vs dp_hpwl Place HPWL | vs dp_rudy OvflNets | vs dp_rudy EstShorts | vs dp_rudy RC-H | vs dp_rudy RC-V | vs dp_rudy GR WL | vs dp_rudy Place HPWL |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for design, ru, xp, dp in ratio_rows:
            hp = ok_by_design_method.get((design, "dp_hpwl"))
            lines.append(
                "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                % (
                    design,
                    format_float(safe_ratio(numeric(ru, "route_ovfl_nets"), numeric(xp, "route_ovfl_nets")) if xp else None),
                    format_float(safe_ratio(numeric(ru, "route_est_shorts"), numeric(xp, "route_est_shorts")) if xp else None),
                    format_float(safe_ratio(numeric(ru, "rc_hor"), numeric(xp, "rc_hor")) if xp else None),
                    format_float(safe_ratio(numeric(ru, "rc_ver"), numeric(xp, "rc_ver")) if xp else None),
                    format_float(safe_ratio(numeric(ru, "route_wl"), numeric(xp, "route_wl")) if xp else None),
                    format_float(safe_ratio(numeric(ru, "place_hpwl"), numeric(xp, "place_hpwl")) if xp else None),
                    format_float(safe_ratio(numeric(ru, "route_wl"), numeric(hp, "route_wl")) if hp else None),
                    format_float(safe_ratio(numeric(ru, "place_hpwl"), numeric(hp, "place_hpwl")) if hp else None),
                    format_float(safe_ratio(numeric(ru, "route_ovfl_nets"), numeric(dp, "route_ovfl_nets")) if dp else None),
                    format_float(safe_ratio(numeric(ru, "route_est_shorts"), numeric(dp, "route_est_shorts")) if dp else None),
                    format_float(safe_ratio(numeric(ru, "rc_hor"), numeric(dp, "rc_hor")) if dp else None),
                    format_float(safe_ratio(numeric(ru, "rc_ver"), numeric(dp, "rc_ver")) if dp else None),
                    format_float(safe_ratio(numeric(ru, "route_wl"), numeric(dp, "route_wl")) if dp else None),
                    format_float(safe_ratio(numeric(ru, "place_hpwl"), numeric(dp, "place_hpwl")) if dp else None),
                )
            )
    path.write_text("\n".join(lines) + "\n")


def write_comparison_csv(path, rows):
    ok = [r for r in rows if r.get("status") == "ok"]
    by_design_method = {(r["design"], r["method"]): r for r in ok}
    fields = [
        "design",
        "ru_route_wl",
        "innovus_2d_place_route_wl",
        "innovus_2d_route_route_wl",
        "xplace_route_wl",
        "dp_hpwl_route_wl",
        "dp_rudy_route_wl",
        "ru_place_hpwl",
        "xplace_place_hpwl",
        "dp_hpwl_place_hpwl",
        "dp_rudy_place_hpwl",
        "ru_vs_xplace_ovfl",
        "ru_vs_xplace_shorts",
        "ru_vs_xplace_rc_hor",
        "ru_vs_xplace_rc_ver",
        "ru_vs_xplace_route_wl",
        "ru_vs_xplace_route_wl_delta",
        "ru_vs_xplace_route_wl_delta_pct",
        "ru_vs_xplace_place_hpwl",
        "ru_vs_innovus_2d_place_route_wl",
        "ru_vs_innovus_2d_place_route_wl_delta",
        "ru_vs_innovus_2d_route_route_wl",
        "ru_vs_innovus_2d_route_route_wl_delta",
        "ru_vs_dp_hpwl_route_wl",
        "ru_vs_dp_hpwl_route_wl_delta",
        "ru_vs_dp_hpwl_route_wl_delta_pct",
        "ru_vs_dp_hpwl_place_hpwl",
        "ru_vs_dp_rudy_ovfl",
        "ru_vs_dp_rudy_shorts",
        "ru_vs_dp_rudy_rc_hor",
        "ru_vs_dp_rudy_rc_ver",
        "ru_vs_dp_rudy_route_wl",
        "ru_vs_dp_rudy_route_wl_delta",
        "ru_vs_dp_rudy_route_wl_delta_pct",
        "ru_vs_dp_rudy_place_hpwl",
        "ru_better_xplace_congestion",
        "ru_better_xplace_hv_congestion",
        "ru_better_xplace_route_wl",
        "ru_better_dp_hpwl_route_wl",
        "ru_better_dp_rudy_congestion",
        "ru_better_dp_rudy_hv_congestion",
        "ru_better_dp_rudy_route_wl",
        "route_wl_best_method",
        "route_wl_best_value",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for design in sorted({r["design"] for r in rows}):
            ru = by_design_method.get((design, "ruplace"))
            inv_place = by_design_method.get((design, "innovus_2d_place"))
            inv_route = by_design_method.get((design, "innovus_2d_route"))
            xp = by_design_method.get((design, "xplace_inflate"))
            hp = by_design_method.get((design, "dp_hpwl"))
            dp = by_design_method.get((design, "dp_rudy"))
            if not ru:
                continue

            def ratio_to(base, key):
                return safe_ratio(numeric(ru, key), numeric(base, key)) if base else None

            def congestion_better(base):
                if not base:
                    return ""
                ru_ovfl = numeric(ru, "route_ovfl_nets")
                ru_short = numeric(ru, "route_est_shorts")
                b_ovfl = numeric(base, "route_ovfl_nets")
                b_short = numeric(base, "route_est_shorts")
                if None in (ru_ovfl, ru_short, b_ovfl, b_short):
                    return ""
                return int((ru_ovfl <= b_ovfl and ru_short < b_short) or (ru_ovfl < b_ovfl and ru_short <= b_short))

            def hv_congestion_better(base):
                if not base:
                    return ""
                ru_h = numeric(ru, "rc_hor")
                ru_v = numeric(ru, "rc_ver")
                b_h = numeric(base, "rc_hor")
                b_v = numeric(base, "rc_ver")
                if None in (ru_h, ru_v, b_h, b_v):
                    return ""
                return int((ru_h <= b_h and ru_v < b_v) or (ru_h < b_h and ru_v <= b_v))

            def wl_better(base):
                if not base:
                    return ""
                ru_wl = numeric(ru, "route_wl")
                b_wl = numeric(base, "route_wl")
                if None in (ru_wl, b_wl):
                    return ""
                return int(ru_wl < b_wl)

            def route_wl_delta(base):
                if not base:
                    return ""
                ru_wl = numeric(ru, "route_wl")
                b_wl = numeric(base, "route_wl")
                if None in (ru_wl, b_wl):
                    return ""
                return format_signed_value(ru_wl - b_wl, 0)

            def route_wl_delta_pct(base):
                if not base:
                    return ""
                return format_delta_percent(ratio_to(base, "route_wl"))

            wl_values = []
            for method, row in [
                ("innovus_2d_place", inv_place),
                ("innovus_2d_route", inv_route),
                ("dp_hpwl", hp),
                ("dp_rudy", dp),
                ("ruplace", ru),
                ("xplace_inflate", xp),
            ]:
                value = numeric(row, "route_wl") if row else None
                if value is not None:
                    wl_values.append((value, method))
            best_wl, best_method = min(wl_values) if wl_values else (None, "")

            writer.writerow(
                {
                    "design": design,
                    "ru_route_wl": format_float(numeric(ru, "route_wl"), 0),
                    "innovus_2d_place_route_wl": format_float(numeric(inv_place, "route_wl"), 0) if inv_place else "",
                    "innovus_2d_route_route_wl": format_float(numeric(inv_route, "route_wl"), 0) if inv_route else "",
                    "xplace_route_wl": format_float(numeric(xp, "route_wl"), 0) if xp else "",
                    "dp_hpwl_route_wl": format_float(numeric(hp, "route_wl"), 0) if hp else "",
                    "dp_rudy_route_wl": format_float(numeric(dp, "route_wl"), 0) if dp else "",
                    "ru_place_hpwl": format_float(numeric(ru, "place_hpwl"), 0),
                    "xplace_place_hpwl": format_float(numeric(xp, "place_hpwl"), 0) if xp else "",
                    "dp_hpwl_place_hpwl": format_float(numeric(hp, "place_hpwl"), 0) if hp else "",
                    "dp_rudy_place_hpwl": format_float(numeric(dp, "place_hpwl"), 0) if dp else "",
                    "ru_vs_xplace_ovfl": format_float(ratio_to(xp, "route_ovfl_nets")),
                    "ru_vs_xplace_shorts": format_float(ratio_to(xp, "route_est_shorts")),
                    "ru_vs_xplace_rc_hor": format_float(ratio_to(xp, "rc_hor")),
                    "ru_vs_xplace_rc_ver": format_float(ratio_to(xp, "rc_ver")),
                    "ru_vs_xplace_route_wl": format_float(ratio_to(xp, "route_wl")),
                    "ru_vs_xplace_route_wl_delta": route_wl_delta(xp),
                    "ru_vs_xplace_route_wl_delta_pct": route_wl_delta_pct(xp),
                    "ru_vs_xplace_place_hpwl": format_float(ratio_to(xp, "place_hpwl")),
                    "ru_vs_innovus_2d_place_route_wl": format_float(ratio_to(inv_place, "route_wl")),
                    "ru_vs_innovus_2d_place_route_wl_delta": route_wl_delta(inv_place),
                    "ru_vs_innovus_2d_route_route_wl": format_float(ratio_to(inv_route, "route_wl")),
                    "ru_vs_innovus_2d_route_route_wl_delta": route_wl_delta(inv_route),
                    "ru_vs_dp_hpwl_route_wl": format_float(ratio_to(hp, "route_wl")),
                    "ru_vs_dp_hpwl_route_wl_delta": route_wl_delta(hp),
                    "ru_vs_dp_hpwl_route_wl_delta_pct": route_wl_delta_pct(hp),
                    "ru_vs_dp_hpwl_place_hpwl": format_float(ratio_to(hp, "place_hpwl")),
                    "ru_vs_dp_rudy_ovfl": format_float(ratio_to(dp, "route_ovfl_nets")),
                    "ru_vs_dp_rudy_shorts": format_float(ratio_to(dp, "route_est_shorts")),
                    "ru_vs_dp_rudy_rc_hor": format_float(ratio_to(dp, "rc_hor")),
                    "ru_vs_dp_rudy_rc_ver": format_float(ratio_to(dp, "rc_ver")),
                    "ru_vs_dp_rudy_route_wl": format_float(ratio_to(dp, "route_wl")),
                    "ru_vs_dp_rudy_route_wl_delta": route_wl_delta(dp),
                    "ru_vs_dp_rudy_route_wl_delta_pct": route_wl_delta_pct(dp),
                    "ru_vs_dp_rudy_place_hpwl": format_float(ratio_to(dp, "place_hpwl")),
                    "ru_better_xplace_congestion": congestion_better(xp),
                    "ru_better_xplace_hv_congestion": hv_congestion_better(xp),
                    "ru_better_xplace_route_wl": wl_better(xp),
                    "ru_better_dp_hpwl_route_wl": wl_better(hp),
                    "ru_better_dp_rudy_congestion": congestion_better(dp),
                    "ru_better_dp_rudy_hv_congestion": hv_congestion_better(dp),
                    "ru_better_dp_rudy_route_wl": wl_better(dp),
                    "route_wl_best_method": best_method,
                    "route_wl_best_value": format_float(best_wl, 0),
                }
            )


def eval_def_cli(argv):
    args = parse_eval_args(argv)
    xplace_root = args._eval_xplace_root.resolve()
    if getattr(args, "_eval_gpugr_root", ""):
        # Bundled GPUGR: extensions, flute tables and IOParser all come from
        # the bundle so the eval matches the in-loop router exactly.
        xplace_root = Path(args._eval_gpugr_root).resolve()
        print("eval: using bundled GPUGR root %s" % xplace_root)
    if str(xplace_root) not in sys.path:
        sys.path.insert(0, str(xplace_root))

    import torch
    from dreamplace.ops.gpugr import gr_metrics
    from dreamplace.ops.gpugr.xplace_backend import (
        _load_xplace_gpugr,
        _load_xplace_ioparser,
    )

    gpugr = _load_xplace_gpugr(xplace_root)
    IOParser = _load_xplace_ioparser(xplace_root)

    gpugr.read_flute(
        str(xplace_root / "thirdparty" / "flute" / "POWV9.dat"),
        str(xplace_root / "thirdparty" / "flute" / "POST9.dat"),
    )
    parser = IOParser()
    params = {
        "benchmark": "dreamplace",
        "lefs": [str(lef.resolve()) for lef in args._eval_lef],
        "def": str(args._eval_def.resolve()),
        "design_name": args._eval_design,
    }
    if args._eval_verilog:
        params["verilog"] = str(args._eval_verilog.resolve())
    rawdb, gpdb = parser.read(
        params,
        verbose_log=False,
        lite_mode=True,
        random_place=False,
        num_threads=args._eval_num_threads,
    )
    die_lx, die_hx, die_ly, die_hy = gpdb.coreInfo()
    bin_x = args._eval_num_bins
    bin_y = args._eval_num_bins
    num_rows = math.floor((die_hy - die_ly) / max(gpdb.siteHeight(), 1))
    if num_rows > 0 and num_rows < bin_y:
        bin_y = int(2 ** math.floor(math.log2(num_rows)))
        bin_x = int(round(args._eval_num_bins / args._eval_num_bins * bin_y))
    die_ratio = (die_hx - die_lx) / max(die_hy - die_ly, 1e-9)
    route_size = min(512, bin_y)
    route_x_size = route_size if die_ratio <= 1 else round(route_size * die_ratio)
    route_y_size = route_size if die_ratio >= 1 else round(route_size / die_ratio)

    # RUPlace batch 2 (A2): --ruplace-gr-grid overrides the derived square-ish grid.
    #   ""/"bins"  -- keep the historical derivation above (default);
    #   "def"      -- 0/0, i.e. let GRDatabase use the DEF GCELLGRID;
    #   "NxM"      -- an explicit uniform grid.
    #   "step:D"   -- a target gcell pitch in DEF dbu, resolved against the DIEAREA.
    grid = str(getattr(args, "_eval_gr_grid", "") or "").strip().lower()
    if grid == "def":
        route_x_size, route_y_size = 0, 0
    elif grid.startswith("step:"):
        try:
            _step = float(grid.split(":", 1)[1])
        except ValueError:
            _step = 0.0
        if _step > 0:
            # dieInfo() -> (dieLX, dieHX, dieLY, dieHY) in raw DEF dbu, i.e. the DIEAREA box.
            _dlx, _dhx, _dly, _dhy = gpdb.dieInfo()
            route_x_size = max(1, int(round((float(_dhx) - float(_dlx)) / _step)))
            route_y_size = max(1, int(round((float(_dhy) - float(_dly)) / _step)))
            print("GR grid: step %g dbu over die (%g, %g)-(%g, %g) -> %d x %d gcells"
                  % (_step, _dlx, _dly, _dhx, _dhy, route_x_size, route_y_size))
        else:
            print("WARNING: unrecognized --ruplace-gr-grid %r, keeping the derived grid" % grid)
    elif grid and grid not in ("bins", "legacy") and "x" in grid:
        _a, _, _b = grid.partition("x")
        try:
            route_x_size, route_y_size = int(_a), int(_b)
        except ValueError:
            print("WARNING: unrecognized --ruplace-gr-grid %r, keeping the derived grid" % grid)
    gpugr.load_gr_params(
        {
            "device_id": args._eval_gpu,
            "route_xSize": int(route_x_size),
            "route_ySize": int(route_y_size),
            "rrrIters": int(args._eval_route_rrr_iters),
        }
    )
    grdb = gpugr.create_grdatabase(rawdb, gpdb)
    routeforce = gpugr.create_routeforce(grdb)
    routeforce.run_ggr()

    dmd_map, wire_dmd_map, via_dmd_map = routeforce.dmd_map()
    cap_map = routeforce.cap_map()
    try:
        fixed_map = routeforce.fixed_map()
    except AttributeError:
        fixed_map = None

    m1direction = gpdb.m1direction()
    util_mode = str(getattr(args, "_eval_util_mode", "legacy") or "legacy")
    if util_mode == "avail" and fixed_map is None:
        print("WARNING: --ruplace-gr-util-mode avail requested but no fixed_map(); using legacy")
        util_mode = "legacy"
    _, _, _, cg_map_hv = gr_metrics.hv_maps(
        dmd_map, wire_dmd_map, via_dmd_map, cap_map,
        fixed=fixed_map, m1direction=m1direction, util_mode=util_mode,
    )

    step_x, step_y = routeforce.gcell_steps()
    layer_pitch = routeforce.layer_pitch()
    wl_steps, gr_vias = grdb.report_gr_stat()
    gr_wirelength = gr_metrics.gr_wirelength_m2pitch(wl_steps, step_x, step_y, layer_pitch)
    est_shorts = gr_metrics.estimate_num_shorts(
        cap_map, wire_dmd_map, via_dmd_map,
        layer_width=routeforce.layer_width(), layer_pitch=layer_pitch,
        step_x=step_x, step_y=step_y, microns=float(routeforce.microns()),
        m1direction=m1direction,
    )
    rc_hor, rc_ver = gr_metrics.rc_means(cg_map_hv)
    metrics = {
        "route_ovfl_nets": int(routeforce.num_ovfl_nets()),
        "route_wl": int(gr_wirelength),
        "route_vias": int(gr_vias),
        "route_est_shorts": int(est_shorts),
        "rc_hor": "%.3f" % rc_hor,
        "rc_ver": "%.3f" % rc_ver,
    }
    print("RUPLACE_GGR_METRICS_JSON %s" % json.dumps(metrics, sort_keys=True))
    return 0


def main():
    args = parse_args()
    args.xplace_root = args.xplace_root.resolve()
    args.case_map = load_case_manifest(args.case_manifest, parse_path_maps(args.manifest_path_map))
    methods = parse_methods(args.methods)
    if args.case_map and not args.designs:
        designs = list(args.case_map.keys())
    else:
        designs = expand_designs(args.suite, args.designs)
    if not args.run_id:
        args.run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.result_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.case_manifest:
        (run_dir / "case_manifest.used.json").write_text(
            json.dumps(args.case_map, indent=2, sort_keys=True, default=str) + "\n"
        )

    if args.report_only:
        rows = load_existing_rows(run_dir)
        gate = gate_summary(rows)
        (run_dir / "gate_summary.json").write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n")
        write_report(run_dir / "report.md", args, run_dir, rows, gate)
        write_csv(run_dir / "raw_metrics.csv", rows)
        write_comparison_csv(run_dir / "comparison_summary.csv", rows)
        print("Refreshed %s" % (run_dir / "report.md"))
        print("Gate verdict: %s" % ("PASS" if gate["pass"] else "FAIL"))
        if args.fail_on_gate and not gate["pass"]:
            return 2
        return 0

    rows = []
    for design in designs:
        for method in methods:
            print("=== %s / %s ===" % (design, method), flush=True)
            try:
                if method in DREAMPLACE_METHODS:
                    row = run_dreamplace(args, run_dir, design, method)
                elif method == "input_ggr":
                    row = run_input_ggr(args, run_dir, design)
                elif method in REFERENCE_DEF_METHODS:
                    row = run_reference_def(args, run_dir, design, method)
                else:
                    row = run_xplace_baseline(args, run_dir, design)
            except Exception as exc:
                row = {
                    "design": design,
                    "method": method,
                    "status": "failed",
                    "error": str(exc),
                    "metric_source": "",
                }
                row.update({key: "" for key in METRIC_KEYS})
                row.update({key: "" for key in PLACE_KEYS})
                print("ERROR: %s" % exc, file=sys.stderr)
                if not args.continue_on_error:
                    rows.append(row)
                    write_csv(run_dir / "raw_metrics.csv", rows)
                    raise
            rows.append(row)
            write_csv(run_dir / "raw_metrics.csv", rows)
            if row.get("status") != "ok" and not args.continue_on_error:
                break
        if rows and rows[-1].get("status") != "ok" and not args.continue_on_error:
            break

    gate = gate_summary(rows)
    (run_dir / "gate_summary.json").write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n")
    write_report(run_dir / "report.md", args, run_dir, rows, gate)
    write_csv(run_dir / "raw_metrics.csv", rows)
    write_comparison_csv(run_dir / "comparison_summary.csv", rows)
    print("Wrote %s" % (run_dir / "report.md"))
    print("Gate verdict: %s" % ("PASS" if gate["pass"] else "FAIL"))
    if args.fail_on_gate and not gate["pass"]:
        return 2
    return 0


if __name__ == "__main__":
    if "--_eval-def" in sys.argv:
        from dreamplace.ops.gpugr.gpu_lock import maybe_serialized_gpu, resolve_lock_mode
        gpu_index = sys.argv.index("--_eval-gpu") + 1 if "--_eval-gpu" in sys.argv else -1
        device_id = int(sys.argv[gpu_index]) if gpu_index > 0 else 0
        # No params object here: RUPLACE_GPU_LOCK_MODE from the driver decides.
        with maybe_serialized_gpu(resolve_lock_mode(), device_id,
                                  "standalone GPUGR evaluator"):
            sys.exit(eval_def_cli(sys.argv[1:]))
    sys.exit(main())
