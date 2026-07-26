# Routability Lab Validation Status

Validated through 2026-07-27 in the isolated worktree
`.worktrees/ruplace-routability` on branch `feat/routability-lab`. The main
DREAMPlace checkout was not modified.

## Delivered surface

- Independent plugins: `route_inflation`, `momentum_inflation`,
  `path_inflation`, `local_gradient`, `poisson_force`, `net_weighting`,
  `net_overlap`, `pin_porosity`, `whitespace`, and `routeforce`.
- An `adaptive_composite` preset and the retained monolithic DREAMPlace/RUPlace
  baselines.
- Evaluators for RUDY, pin-RUDY, Xplace GGR, bundled GPUGR, CUGR, NCTUgr,
  OpenROAD/FastRoute, and Innovus v22 EGR.
- Explicit evaluator roles: OpenROAD/Innovus are golden, RUDY/bundled GPUGR
  are fallback references, and the remaining adapters are diagnostic-only.
- Comparison rows require one identical backend across all methods, identify the
  selected validation tier/backend, and cannot mark cross-router or diagnostic
  metrics authoritative.
- An early placement stop leaves every unattempted method in the comparison and
  forces `unvalidated`; golden rows require positive routed wirelength.
- Manifest-driven comparison and campaign runners with normalized JSON/CSV,
  timeout, unsupported-input, and failed-input states.
- Each native evaluator now runs in its own child process, so a router or
  `PlaceDB` crash becomes one failed row instead of aborting the method/campaign.
- Placement rows record per-plugin attempts and activations and flag selected
  methods that never reached their activation schedule.
- Composite area plugins share cumulative inflation state instead of overwriting
  one another's node-size transformations.

These are mechanism implementations unless the literature document explicitly
calls out released-code lineage. A paper-inspired name is not an exact paper
reproduction.

## Regression evidence

After reinstalling with `cmake --install build`:

| Suite | Result |
|---|---:|
| Routability evaluator tests | 21/21 pass |
| Runner policy tests | 12/12 pass |
| Plugin math tests | 6/6 pass |
| DEF distribution tests | 1/1 pass |
| Legacy RUPlace unit tests | 14/14 pass |
| RUPlace quality/source tests | 11/11 pass |
| Python compile and `git diff --check` | pass |

The installed `ruplace_quality_test.py` cannot locate `install/tools/ruplace_quality.py`
because legacy tools are not installed by CMake; the same suite passes from the
source tree with `PYTHONPATH=install`.

A final audited rebuild and local install completed with CUDA enabled. A fresh
GPU integration smoke (`final_audit_gpu_smoke`) ran HPWL and `local_gradient`
for 200 iterations; the plugin recorded 91 nonzero activations and both methods
completed the same RUDY fallback evaluation. This smoke checks wiring only and
is not promoted to golden QoR evidence.

## Runtime validation

### Plugin state changes

The 50-iteration ISPD2019 test1 smoke showed that every gradient/net plugin
changes the placement. A forced one-round area smoke at activation threshold
`1.0` showed a 1% movable-area increment for every inflation plugin. Under that
tight cap, `route_inflation`, `path_inflation`, and `pin_porosity` produced the
same DEF; this is small-test mechanism collapse, not evidence that the methods
are equivalent.

At the normal `0.2` threshold, area plugins did not activate within 200
iterations and matched HPWL exactly. This means the current default schedule
has not validated their intended effect.

The comparison runner now records attempts and activations directly. A fresh
200-iteration threshold sweep at `0.8` confirms that every selected plugin
actually ran; the area plugins each changed node areas once, and the gradient
plugins report their exact application counts. This removes configured-but-no-op
runs from the evidence set.

### 200-iteration ISPD2019 test1 comparison

All 13 methods completed RUDY, pin-RUDY, OpenROAD, CUGR, and bundled GPUGR: 65
of 65 evaluator rows were `ok`. This is a reduced smoke, not a publication-scale
QoR conclusion.

| Method | Main evidence |
|---|---|
| HPWL | OpenROAD WL 55,123; CUGR WL 350,180 with 0 shorts; GPUGR WL 38,722 and estimated shorts 1,880.5 |
| `net_weighting` | OpenROAD WL 54,882 and CUGR WL 346,030, but CUGR shorts increased to 27 and GPUGR estimated shorts to 2,016.2 |
| `poisson_force` | Best RUDY overflow sum 3.856 and best GPUGR estimated shorts 918.1; OpenROAD/CUGR WL degraded to 70,404/478,130 |
| `adaptive_composite` | RUDY overflow sum 18.35 and GPUGR estimated shorts 1,688.1; OpenROAD/CUGR wirelength degraded |
| `routeforce` | Harmful in this setup: placement 219.4 s, OpenROAD WL 393,090, CUGR shorts 313,316, GPUGR WL 246,403 |

No default plugin beat HPWL across all routers. Router disagreement is large
enough that RUDY-only tuning would be misleading.

### Activation-schedule development result

At activation overflow `0.8`, all 13 methods completed a common OpenROAD golden
evaluation on ISPD2019 test1. `net_weighting` was the only method below HPWL:
55,047 versus 55,123 global-route wirelength (-0.14%). This is too small to call
a robust improvement. `local_gradient` was +0.65%, `whitespace` +2.45%,
`net_overlap` +2.63%, and `poisson_force` +28.09%. The one-round inflation
methods were roughly +97% to +99%, `adaptive_composite` was +101.02%, and
`routeforce` was +492.78%. All figures are same-backend OpenROAD comparisons.

The apparent `net_weighting` improvement did not generalize to legal Nangate45
`gcd`. It activated 14 times, but OpenROAD wirelength increased from 6,432 to
6,543 (+1.73%) and Innovus EGR wirelength increased from 3,316.145 um to
3,415.195 um (+2.99%). Both backends were common golden validators for both
methods and Innovus reported 0%/0% H/V overflow. Therefore no implemented
plugin is currently supported as a winner.

### Multi-seed default-strength screening

The full ISPD2019 test1/test2/test3 screen completed 9 of 9 case-seed
comparisons at seeds 1000, 2000, and 3000. All comparisons were validated on
the common RUDY and bundled-GPUGR fallback tier, every selected plugin activated
in every run, and the summary reported no exclusions, incomplete jobs, missing
comparisons, or HPWL-baseline gaps. The strict selector qualified zero methods
under the predeclared 5% mean/10% worst placement-HPWL and GPUGR-wirelength
guardrails.

The failure is concentrated on ISPD2019 test2: among the five least damaging
gradient/net methods, the worst observed seed regressed placement HPWL by 61%
to 129% and GPUGR wirelength by 62% to 94%. Test1/test3 changes were generally
within a few percent. Therefore no default-strength plugin is eligible for pair
search.
A bounded 30-point weak-strength atomic sweep used test1/test2 as development
cases and reserved test3 for held-out confirmation before any pair was formed.

The saved full-comparison CSV predates placement-row reporting, the p99
headline score, and the hardened evaluator failure semantics. It must not be
used as evidence for those newer reporting contracts. A fresh
50-iteration runner smoke at
`results/routability_lab/ispd19_test1_runner_reporting_smoke` proves the new
row: HPWL `88,079.48`, overflow `0.9502155`, and placement runtime `5.25 s`.

### Frozen weak-strength and combination search

The bounded weak-strength development sweep completed all six test1/test2
case-seeds for 30 atomic presets. The predeclared 5% mean/10% worst placement
HPWL and GPUGR-wirelength guardrails selected one preset each for
`net_weighting`, `poisson_force`, and `net_overlap`. All three remained
eligible on the separately held-out test3 seeds; this held-out result was not
used to retune their parameters.

The resulting bounded pair search evaluated nine combinations across the six
development case-seeds: the three plugin pairs at activation thresholds 0.6,
0.8, and 1.0. None passed the same hard guardrails, so no combination advanced
to golden validation. In particular, an improved GPUGR congestion score was
not accepted when placement HPWL or GPUGR routed wirelength regressed.

A frozen unified replay then reran HPWL and the three atomic finalists on all
nine contest case-seeds. Only the Poisson preset remained eligible after the
full three-design guardrail pass. Its common OpenROAD golden replay completed
all nine comparisons with 18 positive routes. Poisson's routed-wirelength
delta was -1.115% mean, +0.603% median, and +3.994% worst, with only 2/9 pair
wins and a design-level 95% confidence interval of -8.202% to +5.972%. The
negative mean is driven by one test2 seed and is not a robust improvement.

### Router calibration

- ISPD2019 test1 input: OpenROAD WL 86,763 and 40,116 vias; CUGR one-pass WL
  603,300, 52,818 vias, 0 shorts, score 512,922; Xplace WL 60,027, 35,689 vias,
  0 overflow nets. Bundled GPUGR succeeds from the installed package root.
- CUGR defaults to one RRR pass. Its public binary raises `SIGFPE` on the second
  pass for the validated case even with one thread.
- Innovus v22 is validated on the topology-matched legal Nangate45 `gcd`
  checkpoint: EGR WL 3,554.975 um, 3,908 vias, and 0%/0% H/V overflow. The
  adapter now detects fatal Innovus log markers even when the container wrapper
  returns status zero, rejects empty metrics, and uses valid physical-only
  `init_design` semantics.
- A final strict-gate replay on the saved legal `gcd` HPWL placement reproduced
  OpenROAD WL 6,432 with 2,688 vias and Innovus EGR WL 3,316.145 um with 3,066
  vias and 0%/0% H/V overflow. Both adapters returned `ok` only after positive
  routed wirelength was observed.

## Real-design status

The manifests include BP_quad, OpenC910, Mempool, NVDLA-L, XScore, and the
TILOS NVDLA partition. TaiWei cases remain restricted to technology/cell LEFs
and the topology-matched `2_2_floorplan_io.def`/`2_2_floorplan_io.v` pair. The
older `1_synth.v` files are stale relative to Innovus placement optimization
and must not be used to reconstruct these inputs.

- The approximately 145k-cell TILOS NVDLA partition has existing paths and a
  successful campaign dry run.
- All five requested TaiWei designs now have topology-gated,
  connectivity-complete 2D DEFs. The paired `2_2_floorplan_io.v` files match
  every physical component: BP_quad materialized 795,816 components and
  1,024,037 regular nets; OpenC910 938,955/943,510; Mempool
  2,579,164/2,958,566; NVDLA-L 2,229,371/2,735,899; and XScore
  3,617,126/4,139,353. Every materializer report records component and physical
  match ratios of 1.0 and zero unplaced linked components.
- One-iteration GPU probes for all five materialized designs completed with
  positive HPWL, nonzero RUDY demand, and at least 99.89% of parsed pins inside
  the routing region. Their density overflows remain approximately 0.999, so
  these probes prove parser/evaluator/runtime readiness only. They are not
  converged placement QoR and must not be included in method rankings.
- Direct NVDLA-partition input evaluation is not a valid placed-design
  comparison. Although all components are marked `PLACED`, they are collapsed
  at `(0, 0)`, outside the parsed routing core after coordinate normalization.
  This caused the all-zero RUDY map and contributed to OpenROAD's `GRT-0228`
  capacity failure. CUGR also saw regular `VDD`/`VSS` records duplicated in
  `SPECIALNETS`; its adapter now filters only those duplicate records. The old
  Xplace input probe used a bounded `128 x 128` grid and routed only 11,811
  nets, while the newer unbounded probe constructed a `1240 x 1682` grid,
  reached 91,955 nets, and hit CUDA error 700. Standalone Xplace/GPUGR
  evaluation now defaults to the validated bounded grid. None of these raw
  floorplan probes is placement QoR evidence; the full evaluator set must run
  on a generated placed DEF.
- With the sanitizer, CUGR parsed 200,575 regular nets (exactly two fewer) and
  passed its former initialization crash before reaching the 120-second route
  timeout. Separate child-process RUDY and pin-RUDY checks on a valid placed
  ISPD2019 test1 DEF both completed successfully.
- The converged five-design, three-seed screen completed all 15 comparisons
  with 30 valid placements. Poisson reduced density overflow by 36.746% and
  the RUDY hotspot score by 19.571% on average, but increased placement HPWL by
  19.763% with losses on every case-seed. RUDY overflow sum increased 7.872%
  on average and its maximum-utilization change was inconclusive. These are
  fallback screening results, not golden evidence.
- A manufacturing-grid-safe BP_quad seed-1000 Innovus pilot produced two
  positive EGR routes. Relative to HPWL, Poisson increased routed wirelength
  15.143%, vias 0.296%, horizontal congestion 20%, and vertical congestion
  12%. The original DEFs remain preserved and each snapped DEF records input
  and output hashes, changed coordinates, and maximum displacement.
- The full common-Innovus replay completed all 15 five-design, three-seed
  comparisons with 30 positive routes and 30 successful manufacturing-grid
  snap reports. The summary has zero exclusions, incomplete jobs, missing
  comparisons, or baseline gaps. Poisson lost routed wirelength on all 15
  pairs: +18.663% mean, +13.547% median, +52.558% worst, with a design-level
  95% confidence interval of -1.370% to +38.696%. Vias increased 1.090% on
  average (6 wins, 9 losses); H/V congestion was mixed with wide confidence
  intervals. This rejects Poisson and leaves HPWL as the robust default.

## Validation conclusion and remaining research gaps

The implemented plugin and bounded-combination campaign is complete. No method
or pair passed the full frozen protocol, so no routability plugin should be
enabled by default. The final cross-stage decision report is
`docs/routability_validation_final.md`.

Future work may reproduce RoutePlacer, PUFFER, SimPLR, detailed-routing,
virtual-cell, and timing-aware methods only after their missing
licenses/models/features are resolved. Until then the corresponding plugins
remain approximations and are not evidence gaps in the completed
mechanism-comparison campaign.

## Evidence roots

- `results/routability_lab/ispd19_test1_200iter_full_eval`
- `results/routability_lab/ispd19_test1_plugin_smoke_stage1`
- `results/routability_lab/ispd19_test1_plugin_smoke_stage2`
- `results/routability_lab/ispd19_test1_area_activation_smoke`
- `results/routability_lab/ispd19_test1_forced_activation_200iter`
- `results/routability_lab/ispd19_test1_all_plugins_overflow080`
- `results/routability_lab/nangate45_gcd_hpwl_vs_net_weighting_golden`
- `results/routability_lab/ispd19_test1_runner_reporting_smoke`
- `results/routability_lab/innovus_nangate45_gcd_base_routed`
- `results/routability_lab/innovus_placement_patterns`
- `results/routability_lab/nvdla_partition_input_full_eval`
- `results/routability_lab/nvdla_partition_contract_recheck`
- `results/routability_lab/evaluator_process_isolation_smoke`
- `results/routability_lab/final_audit_gpu_smoke`
- `results/routability_lab/final_audit_golden_replay`
- `results/routability_lab/real_design_inputs`
- `results/routability_lab/openc910_materialized_probe`
- `results/routability_lab/bp_quad_materialized_probe`
- `results/routability_lab/remaining_materialized_real_probes`
- `results/routability_lab/remote_screening_ispd2019_e040310`
- `results/routability_remote/ispd2019_weak_atomic_dev_test1_test2_3seeds_de60953`
- `results/routability_remote/ispd2019_weak_atomic_heldout_test3_3seeds_6cad06c`
- `results/routability_remote/ispd2019_pair_dev_test1_test2_3seeds_d8fab3c`
- `results/routability_remote/ispd2019_unified_finalists_3cases_3seeds_d8fab3c`
- `results/routability_remote/real_5designs_3seeds_85603d6`
- `results/routability_remote/real_bp_quad_pilot_seed1000_85603d6`
- `results/routability_remote/real_5designs_3seeds_85603d6/golden_innovus_snapped_4589107`
- `results/routability_remote/real_5designs_3seeds_85603d6/golden_innovus_snapped_4589107_summary`
