# Routability Optimization Validation Report

## Decision scope

This report ranks the ten independent routability plugins implemented on
`feat/routability-lab` against the unmodified HPWL objective. OpenROAD and
Innovus are golden validators. RUDY and bundled GPUGR are used only for
screening or fallback, and metrics from different routers are never combined
numerically. A routed comparison is valid only when every compared method uses
the same backend and produces positive routed wirelength.

The plugins reproduce mechanism families, not proprietary or incompletely
specified placers. The literature search, source links, and method-by-method
fidelity assessment are in `docs/routability_optimization_lab.md`.

## Implemented methods

| Plugin | Mechanism | Fidelity | Validation outcome |
|---|---|---|---|
| `route_inflation` | Congestion-based cell inflation | Mechanism implementation | Default strength rejected |
| `momentum_inflation` | History-smoothed inflation | Mechanism implementation | Default strength rejected |
| `path_inflation` | Routing-path-aware inflation | Mechanism approximation | Default strength rejected |
| `local_gradient` | Local congestion gradient | Mechanism approximation | Weak sweep, no finalist |
| `poisson_force` | Global Poisson potential force | Analytical objective | Only atomic golden finalist |
| `net_weighting` | Congested-net objective reweighting | Mechanism approximation | Atomic finalist, failed unified guardrails |
| `net_overlap` | Overlapping-net-box removal | Mechanism approximation | Atomic finalist, failed unified guardrails |
| `pin_porosity` | Pin-density and macro-porosity inflation | Partial mechanism coverage | Default strength rejected |
| `whitespace` | Low-frequency whitespace allocation | Mechanism approximation | Weak sweep, no finalist |
| `routeforce` | Xplace differentiable route gradient | Released-backend lineage | Default strength rejected |

The retained `adaptive_composite`, monolithic DREAMPlace RUDY inflation, and
monolithic RUPlace paths are baselines or presets, not additional independent
plugins.

## Selection funnel

| Stage | Cases | Methods | Validator role | Result |
|---|---:|---:|---|---|
| Default-strength screen | 3 designs x 3 seeds | 13 | RUDY + GPUGR fallback | 9/9 comparisons; zero survivors |
| Weak atomic development | 2 designs x 3 seeds | 30 presets | RUDY + GPUGR fallback | Selected one each of net weighting, Poisson, and net overlap |
| Held-out atomic check | 1 design x 3 seeds | 3 finalists | RUDY + GPUGR fallback | All three stayed eligible; no retuning |
| Pair development | 2 designs x 3 seeds | 9 pairs | RUDY + GPUGR fallback | Zero pairs survived hard guardrails |
| Unified atomic replay | 3 designs x 3 seeds | 3 finalists | RUDY + GPUGR fallback | Poisson alone remained eligible |
| Contest golden replay | 3 designs x 3 seeds | HPWL + Poisson | OpenROAD | 9/9 comparisons; 18 positive routes |
| Real-design screen | 5 designs x 3 seeds | HPWL + Poisson | RUDY fallback | 15/15 comparisons; 30 valid placements |
| Real-design golden replay | 5 designs x 3 seeds | HPWL + Poisson | Innovus 22 | 15/15 comparisons; 30 positive routes |

The hard gate allowed at most 5% mean and 10% worst regression for both
placement HPWL and GPUGR wirelength, followed by a multiobjective Pareto
frontier. The selection metadata records `numeric_backend_mixing: false`.

## Contest evidence

The default-strength run rejected every plugin. Several methods improved a
normalized congestion score while sharply increasing routed wirelength,
especially on ISPD2019 test2. This established that proxy-score improvement
alone is not a valid selection criterion.

The bounded weak sweep and held-out check selected three atomic mechanisms.
All nine pair configurations failed the same guardrails, including pairs with
statistically supported GPUGR congestion-score improvement, because their HPWL
or routed-wirelength tails were unacceptable.

The unified replay left weak Poisson as the only golden candidate. Its frozen
preset uses the RUDY proxy, `ruplace_poisson_weight=0.01`, and
`ruplace_plugin_start_overflow=0.8`. On the common OpenROAD backend its
wirelength delta versus HPWL was:

| Metric | Mean | Median | Worst | Pair W/L | Design 95% CI |
|---|---:|---:|---:|---:|---:|
| Routed wirelength | -1.115% | +0.603% | +3.994% | 2/7 | -8.202% to +5.972% |
| Vias | -0.889% | -0.184% | +0.917% | 6/3 | -5.027% to +3.249% |

The routed-wirelength mean is driven by one test2 seed. Seven of nine seeds
lose and the confidence interval crosses zero, so this is not a robust contest
improvement.

## Real-design screening

The real-design set contains BP_quad, OpenC910, Mempool, NVDLA-L, and XScore at
seeds 1000, 2000, and 3000. Inputs use topology-matched
`2_2_floorplan_io.def`/`.v` data only; no 3D, CTS, or routed placement is used.

| Metric | Poisson mean delta | Worst | Pair W/L | Design 95% CI |
|---|---:|---:|---:|---:|
| Placement HPWL | +19.763% | +49.582% | 0/15 | +3.690% to +35.836% |
| Density overflow | -36.746% | -0.224% | 15/0 | -66.381% to -7.111% |
| Placement runtime | +12.151% | +28.676% | 1/14 | -5.430% to +29.733% |
| RUDY overflow sum | +7.872% | +87.392% | 11/4 | -25.195% to +40.940% |
| RUDY hotspot score | -19.571% | -13.051% | 15/0 | -23.322% to -15.820% |
| RUDY maximum utilization | -0.758% | +45.225% | 11/4 | -14.704% to +13.188% |

Poisson consistently flattens the proxy hotspot score and lowers density
overflow, but damages HPWL on every case-seed and does not robustly improve
actual RUDY overflow.

## Innovus golden evidence

Every evaluated DEF is snapped to the LEF `MANUFACTURINGGRID` without changing
the original. Provenance records input/output SHA256, changed components and
coordinates, and maximum displacement. The same preprocessing policy is used
for both methods.

The complete five-design, three-seed replay produced all 15 comparisons and 30
positive Innovus EGR routes. The summary found no exclusions, incomplete jobs,
missing comparisons, or baseline gaps. Every pair used Innovus for both methods
and every Poisson placement recorded nonzero plugin activation.

| Innovus metric | Poisson mean delta | Median | Worst | Pair W/T/L | Design W/T/L | Design 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| Routed wirelength | +18.663% | +13.547% | +52.558% | 0/0/15 | 0/0/5 | -1.370% to +38.696% |
| Vias | +1.090% | +0.296% | +9.363% | 6/0/9 | 2/0/3 | -2.656% to +4.836% |
| Horizontal congestion | +23.031% | -3.804% | +200.000% | 9/1/5 | 3/0/2 | -38.016% to +84.077% |
| Vertical congestion | +18.480% | -9.915% | +130.636% | 9/0/6 | 3/0/2 | -41.842% to +78.803% |

Poisson lost routed wirelength on every design and seed. Its apparently useful
median H/V congestion reductions are accompanied by extreme regressions and
wide design-level intervals; neither direction is statistically robust. It
also increased placement HPWL on all 15 runs. The golden evidence therefore
rejects Poisson even though it consistently flattened the RUDY hotspot proxy.

## Failure modes and limitations

- Strong plugin settings can improve a congestion score while destabilizing
  wirelength, particularly on ISPD2019 test2.
- Area plugins may not activate under the normal reduced-run threshold; every
  ranked run therefore records plugin attempts and activations.
- CUGR raises `SIGFPE` beyond one RRR pass on the calibrated public binary and
  is diagnostic-only.
- Raw TILOS NVDLA input is collapsed at `(0, 0)` and is not placement QoR
  evidence. Xplace/GPUGR can also exhaust CUDA resources on its unbounded grid.
- OpenROAD cannot route every real TaiWei topology. Those cases require common
  Innovus evaluation; fallback metrics are never presented as golden.
- RoutePlacer, PUFFER, SimPLR, detailed-routing, virtual-cell, timing-aware, and
  learned methods still require missing models, rules, timing context, or
  separate optimization stages. The current plugins must not be described as
  exact reproductions of those works.

## Requirement-completion audit

- All ten independent plugins were exercised and retain isolated configuration
  and implementation paths. Default-strength, weak-strength, held-out, and
  unified atomic screens completed.
- A bounded search covered all three pairs of the atomic survivors at three
  activation thresholds. None passed the frozen HPWL and routed-wirelength
  guardrails, so no pair was promoted to expensive golden routing.
- The contest finalist completed 9/9 common-OpenROAD comparisons; the
  real-design finalist completed 15/15 common-Innovus comparisons. RUDY and
  GPUGR results were kept as screening evidence and were not mixed numerically
  with either golden router.
- Contest coverage comprises ISPD2019 test1/test2/test3 at three seeds. Real
  coverage comprises BP_quad, Mempool, NVDLA-L, OpenC910, and XScore at three
  seeds using only topology-matched 2D inputs.
- The saved summary reports placement HPWL, density overflow, runtime, routed
  wirelength, vias, H/V congestion, failures, coverage, pair wins/losses, and
  design-level confidence intervals.
- Exact RoutePlacer, PUFFER, SimPLR, detailed-routing, virtual-cell,
  timing-aware, and learned reproductions are explicitly out of scope until
  their missing models, rules, timing context, or optimization stages are
  available. No mechanism approximation is presented as an exact reproduction.

## Recommendation

Keep the unmodified HPWL objective as the default robust configuration. Enable
no routability plugin or pair by default. The weak Poisson preset is useful as
an ablation showing that a smoother RUDY hotspot map and lower density overflow
do not imply better golden routed QoR, but it is not a production candidate.

This recommendation is based on the frozen selection protocol and the complete
common-backend golden replays. Future work should start from new mechanisms or
multiobjective schedules and must beat the same HPWL baseline on unseen designs
before golden validation; further tuning of these results would invalidate the
held-out interpretation.
