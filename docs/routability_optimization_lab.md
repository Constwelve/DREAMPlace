# Routability Optimization Lab

## Scope and claims

This branch separates three concerns that were previously coupled:

1. **Optimization plugins** change a placement.
2. **Congestion proxies** supply feedback during placement.
3. **Evaluators** score completed DEFs independently.

An implementation is called a **reproduction** only when the published method and released code can be matched. The current analytical plugins are paper-inspired implementations of mechanisms, not exact reproductions of proprietary or incompletely specified placers.

The literature search was refreshed on 2026-07-26 using DBLP, OpenAlex, DOI metadata, and public source repositories. It covered DAC, ICCAD, ISPD, ASP-DAC, DATE, TCAD, TCAS-II, and adjacent physical-design venues. No canonical standard-cell routability-driven global-placement method was found in TCAS-II that adds a distinct mechanism beyond the rows below; the relevant journal extensions are primarily in TCAD.

## What existed before this branch

DREAMPlace already contained four disconnected mechanisms:

- RUDY route-utilization maps.
- Pin-density and pin-RUDY maps.
- NCTUgr congestion maps for Bookshelf cases.
- Route/pin-driven `AdjustNodeArea` inflation.

RUPlace added Xplace/bundled GPUGR route maps, clustered and local cell inflation, directional H/V blending, shrinkage and area caps, and Xplace `routeforce.admm_route_grad`. The optimization controller was monolithic, only Xplace GGR was integrated as a final evaluator, and the older RUDY/NCTUgr/pin paths were mutually exclusive with RUPlace.

The retained validation evidence also shows that implementation success was not yet a broad QoR result: the congestion criterion passed 1/3 ISPD2019 and 1/5 TaiWei-2D cases, while median routed wirelength was about 1.83x and 1.82x the Xplace baseline respectively. Data-large NVDLA was the positive exception at 0.745x Xplace routed wirelength. Those numbers motivate independent plugins and routers rather than further tuning one coupled policy.

## Literature-to-plugin matrix

| Year / venue | Work | Main mechanism | Implementation in this branch | Fidelity |
|---|---|---|---|---|
| 2001 DAC | *A New Congestion-Driven Placement Algorithm Based on Cell Inflation* ([DOI](https://doi.org/10.1145/370155.370560)) | Congestion-based cell inflation | `route_inflation` | Mechanism implementation |
| 2002 ISPD / 2003 TCAD | *An Effective Congestion-Driven Placement Framework* ([DOI](https://doi.org/10.1145/505388.505391), [journal DOI](https://doi.org/10.1109/TCAD.2003.809662)) | Estimation, inflation, repeated placement | `route_inflation`; legacy `AdjustNodeArea` baseline | Mechanism implementation |
| 2002 DAC / 2003, 2007 TCAD | Routability-driven white-space allocation ([DOI](https://doi.org/10.1145/505388.505400), [journal DOI](https://doi.org/10.1109/TCAD.2003.809660)) | Move whitespace toward congestion | `whitespace` | Low-frequency force approximation |
| 2007 DATE | *Fast and Accurate Routing Demand Estimation for Efficient Routability-Driven Placement* ([DOI](https://doi.org/10.1109/DATE.2007.364463)) | RUDY rectangular demand and force-directed optimization | `rudy` proxy/evaluator plus field plugins | RUDY estimator is existing native op; force is an approximation |
| 2008 DAC | *Routability-Driven Analytical Placement by Net Overlapping Removal* ([DOI](https://doi.org/10.1145/1391469.1391513)) | Move overlapping net boxes; Gaussian macro porosity | `net_overlap`, `pin_porosity` | Mechanism approximations |
| 2010 ICCAD | *New Placement Prediction and Mitigation Techniques for Local Routing Congestion* ([DOI](https://doi.org/10.1109/ICCAD.2010.5654225)) | Local congestion prediction and mitigation | `local_gradient` | Map-gradient approximation |
| 2011 ICCAD | *A SimPLR Method for Routability-Driven Placement* ([DOI](https://doi.org/10.1109/ICCAD.2011.6105307)) | Layer/via-aware look-ahead routing; spreading and contraction | `path_inflation`, `whitespace`; router proxies | Partial mechanism coverage, not SimPLR reproduction |
| 2011 ICCAD | *Routability-Driven Analytical Placement for Mixed-Size Circuit Designs* ([DOI](https://doi.org/10.1109/ICCAD.2011.6105309)) | Pin density, sigmoid overflow, macro porosity, legalization | `pin_porosity`; legacy legalizer | Partial mechanism coverage |
| 2011 ICCAD / 2013 TCAD | *Ripple* ([DOI](https://doi.org/10.1109/ICCAD.2011.6105308), [journal DOI](https://doi.org/10.1109/TCAD.2013.2265371)) | Iterative movement of cells in congested routing paths | `path_inflation`, `local_gradient` | Mechanism approximation |
| 2013 DAC / 2016 TODAES | *Ripple 2.0* ([DOI](https://doi.org/10.1145/2463209.2488922), [journal DOI](https://doi.org/10.1145/2925989)) | Routing-path inflation and congested-cluster optimization | `path_inflation`, legacy clustered inflation | Mechanism approximation |
| 2013 DAC | *Routability-Driven Placement for Hierarchical Mixed-Size Circuit Designs* ([DOI](https://doi.org/10.1145/2463209.2488921)) | Hierarchy-aware mixed-size placement | `net_weighting`, clustered inflation | Partial mechanism coverage; hierarchy is not preserved as an explicit constraint |
| 2013 ASP-DAC | *Optimizing Routability in Large-Scale Mixed-Size Placement* ([DOI](https://doi.org/10.1109/ASPDAC.2013.6509636)) | Mixed-size congestion control and spreading | `pin_porosity`, `whitespace` | Partial mechanism coverage |
| 2014 TCAD | *NTUplace4h* ([DOI](https://doi.org/10.1109/TCAD.2014.2360453)) | Narrow channels, pin density, net congestion, hierarchy | `pin_porosity`, `net_weighting`, clustered inflation | Partial mechanism coverage |
| 2014 DAC | *Routability-Driven Blockage-Aware Macro Placement* ([DOI](https://doi.org/10.1145/2593069.2593206)) | Routing blockages and macro-channel awareness | `pin_porosity`, `whitespace`; macro-aware evaluator inputs | Partial mechanism coverage; no dedicated macro legalizer objective |
| 2015 ASP-DAC | *Detailed-Routing-Driven Analytical Standard-Cell Placement* ([DOI](https://doi.org/10.1109/ASPDAC.2015.7059034)) | Routability wirelength, whitespace allocation, multistage spreading | `net_weighting`, `whitespace`, composite schedule | Global-route approximation, not detailed-route reproduction |
| 2015 ICCAD | *Detailed-Routability-Driven Analytical Placement...* ([DOI](https://doi.org/10.1109/ICCAD.2015.7372612)) | Technology/region-aware detailed-routability feedback | Evaluator interface and regional map plugins | Interface coverage only |
| 2017 ASP-DAC | *Regularity-Aware Routability-Driven Placement Prototyping...* ([DOI](https://doi.org/10.1109/ASPDAC.2017.7858362)) | Hierarchy and regular macro structure | `net_weighting`, `pin_porosity` | Feature approximation; no explicit regularity constraint |
| 2019 DATE | *Routability-Driven Macro Placement with Embedded CNN-Based Prediction Model* ([DOI](https://doi.org/10.23919/DATE.2019.8715126)) | Learned congestion prediction for macro placement | Not implemented | Needs released model/data or retraining |
| 2019 DAC | *Routability-Driven Mixed-Size Placement Prototyping...* ([DOI](https://doi.org/10.1145/3316781.3317901)) | Design hierarchy and indirect macro connectivity | `net_weighting`, `net_overlap` | Partial mechanism coverage; indirect-connectivity graph is not explicit |
| 2019 TVLSI | *Regularity-Aware Routability-Driven Macro Placement...* ([DOI](https://doi.org/10.1109/TVLSI.2018.2867833)) | Regular macro patterns under obstacles | Not implemented as a separate operation | Requires a macro-pattern constraint and macro legalization loop |
| 2019 TCAD | *RePlAce: Advancing Solution Quality and Routability Validation in Global Placement* ([DOI](https://doi.org/10.1109/TCAD.2018.2859220)) | Electrostatic placement plus independent routability validation | DREAMPlace baseline and evaluator protocol | Baseline lineage, not a new plugin |
| 2020 ELEX | *A Local Congestion Elimination Technique Driven by Overflow* ([DOI](https://doi.org/10.1587/elex.17.20200232)) | Search keepout margins around high-pin cells in congested regions | `pin_porosity` | Padding mechanism approximation; SA/ACO parameter search is not reproduced |
| 2021 DATE | *Global Placement with Deep Learning-Enabled Explicit Routability Optimization* | Learned congestion prediction in the placement loop | Not implemented | Needs a pinned model, features, and training data |
| 2021 JCST | *DrPlace: A Deep Learning Based Routability-Driven VLSI Placement Algorithm* ([DOI](https://doi.org/10.3724/SP.J.1089.2021.18566)) | Learned routability prediction and placement guidance | Not implemented | No validated model/checkpoint is present in this tree |
| 2021 ICCAD | *Routability-driven Global Placer Target on Removing Global and Local Congestion for VLSI Designs* ([DOI](https://doi.org/10.1109/ICCAD51958.2021.9643544)) | Congestion-aware movable-net penalty and connectivity/congestion-aware cluster inflation | `net_overlap`, `net_weighting`, clustered inflation | Mechanism approximation; nets are not explicit soft modules |
| 2022 TVLSI | *PPOM: An Effective Post-Global Placement Optimization Methodology for Better Wirelength and Routability* | Post-GP local refinement | `local_gradient`, `net_overlap` | Mechanism approximation, not PPOM reproduction |
| 2023 TODAES | *CRP2.0* ([DOI](https://doi.org/10.1145/3590962)) | Post-global-route ILP detailed placement, net classification, and router cost/net caching | Not implemented | Separate post-GR detailed-placement stage, outside the current GP plugin hook |
| 2023 DAC | *PUFFER* ([DOI](https://doi.org/10.1109/DAC56929.2023.10247681)) | Multi-feature cell padding and Bayesian strategy exploration | `path_inflation`, `pin_porosity`, preset comparisons | Feature approximations; Bayesian search remains open |
| 2024 KDD | *RoutePlacer* ([DOI](https://doi.org/10.1145/3637528.3671895)) | Differentiable RouteGNN congestion surrogate | Not integrated | Public source exists, but no checkpoint or license was present in the audited tree |
| 2024 DAC LBR | *Coulomb Force-Based Routability-Driven Placement* ([DOI](https://doi.org/10.1145/3649329.3663501)) | Routing-path padding plus global virtual Coulomb forces | `path_inflation`, `poisson_force` | Mechanism approximation |
| 2025 DAC | *RUPlace: Optimizing Routability via Unified Placement and Routing Formulation* | Xplace GGR feedback, clustered/local inflation, route force | Legacy RUPlace controller, `routeforce`, inflation plugins | Released implementation lineage retained; plugins enable ablation |
| 2025 DAC | *Differentiable Net-Moving and Local Congestion Mitigation...* ([DOI](https://doi.org/10.1109/DAC63849.2025.11133117)) | Momentum inflation, Poisson congestion, virtual cells on two-pin nets | `momentum_inflation`, `poisson_force`, `net_overlap` | Mechanism approximation; no virtual-cell/rail model yet |
| 2026 ASP-DAC | *C3PO: Commercial-Quality Global Placement via Coherent, Concurrent Timing, Routability, and Wirelength Optimization* | Concurrent timing/routability/wirelength optimization | Not implemented | Timing-aware joint objective is outside the current routability-only plugin contract |

## Screened works outside the current implementation scope

The DBLP query returned standard-cell work together with methods for materially
different placement contracts. They are kept in the survey, but not renamed as
DREAMPlace plugins:

| Domain | Representative works | Why screened out |
|---|---|---|
| FPGA | *RippleFPGA* (ICCAD 2016, TCAD 2018), ISPD 2016 FPGA placement contest, learning-based FPGA routability prediction (FPL 2019, TRETS 2021), FPGA macro placement (DAC 2024 LBR, DATE/TCAD 2025) | Packing, heterogeneous sites, cascade shapes, clock resources, and FPGA routing graphs are not LEF/DEF standard-cell placement |
| Analog/mixed signal | ISPD 2012 analog routability-driven placement, TODAES 2018 analog/mixed-signal revisit, DATE 2022 SMT-based FinFET mixed-signal placement | Symmetry, matching, device orientation, and analog topology constraints require a different database and legalizer |
| SiP/package/PCB | ICCAD 2023 orientation-aware SiP analytical placement; DAC 2025 LBR irregular PCB placement | Component rotation, package layers, escape routing, and collision models do not map to the current cell/bin operations |
| 3D IC | ICCAD 2022 precise-penalty analytical placement for large-scale 3D ICs | Tier assignment, TSVs, and inter-tier routing capacity require a 3D placement/routing contract; this branch is intentionally 2D |
| Cell/transistor synthesis | DAC 2025 CFET in-cell placement/routing; SBCCI 2025 transistor-placement prediction | These optimize internal standard-cell geometry rather than placement of characterized cells |
| Macro-only learned methods | DATE 2019 CNN macro placement; DATE 2026 LBR RL macro placement | No validated public model/checkpoint and the objective acts on macro floorplanning, not the mixed-size GP loop implemented here |

The live source audit on 2026-07-26 found Xplace under BSD-3-Clause. The public
RoutePlacer repository existed but GitHub reported no repository license; it is
therefore a research reference, not a dependency that can be copied into this
tree. Search hits alone are not evidence of reproducibility.

## Plugin contract

`ruplace_plugins` accepts a list or comma-separated string. Every plugin is a separate module under `dreamplace/ops/routability_opt/plugins/` and implements one or both lifecycle hooks:

```python
apply_gradient(pos, model, context)
maybe_adjust_area(pos, model, context)
```

The available operations are:

| Plugin | State changed | Primary ablation question |
|---|---|---|
| `route_inflation` | Cell/filler area | Does classical router-map inflation help? |
| `momentum_inflation` | Cell/filler area and momentum state | Does damping stabilize repeated inflation? |
| `path_inflation` | Cell/filler area | Does footprint exposure outperform center-bin exposure? |
| `local_gradient` | Placement gradient | Does local congestion descent remove hotspots? |
| `poisson_force` | Placement gradient | Does a global field resolve broad congestion? |
| `net_weighting` | Wirelength net weights | Does prioritizing congested nets reduce demand? |
| `net_overlap` | Placement gradient through net-level fields | Does moving whole net neighborhoods help? |
| `pin_porosity` | Cell/filler area | Do pin density and macro porosity explain residual failures? |
| `whitespace` | Placement gradient | Does regional whitespace transfer help? |
| `routeforce` | Placement gradient | Does Xplace routed-wire feedback help independently? |

`configs/routability_plugins/presets.json` contains one-method presets and an `adaptive_composite` preset. An empty `ruplace_plugins` retains the old RUPlace controller.

## Proxy providers

| Proxy | Input class | Differentiable | Cost | Notes |
|---|---|---:|---:|---|
| `rudy` | LEF/DEF or Bookshelf | No native backward | Low | Native DREAMPlace RUDY map |
| `pin_density` | Placement database | No native backward | Low | Existing DREAMPlace pin map |
| `rudy_pin` | Composite | No native backward | Low | Weighted normalized signal interface |
| `nctugr` | Bookshelf | No | High | Existing NCTUgr integration |
| `gpugr` / `xplace` | LEF/DEF | Routeforce only | High | Shared cached global-route signal |

The analytical field plugins differentiate their own grid objectives. They do not claim that the compiled RUDY or router itself has an exact backward pass.

## Evaluators

Evaluator authority is fixed by policy:

| Role | Backends | Allowed use |
|---|---|---|
| Golden | OpenROAD, Innovus | Final validation and method conclusions |
| Fallback reference | RUDY, bundled GPUGR | Validation only when no common golden result is available for every compared method |
| Diagnostic only | pin-RUDY, external Xplace, CUGR, NCTUgr | Debugging, correlation, and sensitivity analysis; never a winner criterion |

`routability_compare.py` selects one or more identical common backends for the
whole design. It uses a golden backend only when that same backend succeeds for
every method; otherwise it may use an identical common fallback backend. It
never mixes OpenROAD with Innovus, RUDY with GPUGR, or a golden row for one
method with a fallback row for another. CSV/JSON rows carry
`validation_role` and `authoritative_for_comparison`, and `comparison.json`
records the selected tier and backends. If neither golden nor fallback coverage
is complete, the comparison is `unvalidated` and the runner exits nonzero.
All requested methods are registered before placement starts, so an early
placement failure cannot validate only the completed prefix. OpenROAD and
Innovus rows also require positive routed wirelength, rather than accepting an
incidental overflow or parser metric as proof that routing completed.

`tools/routability_evaluate.py` writes one JSON file per backend and a `summary.json`. Every result has:

```text
schema_version, backend, design_name, status, runtime_sec,
metrics, artifacts, error
```

Implemented adapters:

- `rudy`, `pin_rudy`: native DREAMPlace map operators and percentile/overflow statistics.
  The headline `congestion_score` is p99/mean; p95/mean and p99/mean are also
  emitted separately so sparse pin maps cannot look congestion-free merely
  because at least 95% of their bins are zero.
- `xplace`, `gpugr`: route maps, routed wirelength, vias, overflow nets, estimated shorts.
- `cugr`: CUGR score block and guide. It requires one merged LEF. The public
  ICCAD19 binary is run with one RRR pass by default because its second pass
  raises `SIGFPE` on the validated ISPD2019 case even with one thread.
- `nctugr`: overflow edge statistics. It requires Bookshelf AUX and PL.
- `openroad`: FastRoute guide, congestion report, metrics JSON, and global-route wirelength report.
- `innovus`: v22 `earlyGlobalRoute` through the `cadence-local` container. It requires Verilog and an output directory mounted by the wrapper.

Example:

```bash
python tools/routability_evaluate.py \
  --backend openroad --backend innovus --backend rudy --backend gpugr \
  --design-name ispd18_test1 \
  --lef-input design.lef --def-input placed.def \
  --output-dir results/routability_eval/ispd18_test1
```

## Comparison protocol

Use `tools/routability_compare.py` with a fixed base configuration. The runner writes the exact merged config, placement log, placed DEF, evaluator artifacts, `comparison.csv`, and `comparison.json` for every method.

Placement rows also include per-plugin attempts and activations plus an explicit
`active`, `partially_active`, `selected_no_activation`, or `not_selected` status.
This prevents a configured-but-gated method from being reported as a QoR
comparison. Composite area plugins share one cumulative inflation engine, so a
later padding operation cannot overwrite an earlier operation's size state.

Required controls for a defensible table:

1. Same input revision, LEFs, DEF topology, netlist, target density, bins, seed, optimizer, and placement iteration budget.
2. Report placement HPWL and runtime, but draw final routability conclusions only from OpenROAD and/or Innovus.
3. Attempt both golden validators. Use RUDY and bundled GPUGR only as the common fallback when golden evaluation cannot run on the case. Keep pin-RUDY, external Xplace, CUGR, and NCTUgr diagnostic-only.
4. Report routed wirelength, vias, total/max overflow, overflow nets, estimated shorts, and runtime. Do not collapse everything into one score without also showing raw columns.
5. Separate router failure, unsupported input, timeout, and clean zero overflow.
6. Use the TaiWei **2D phase** inputs only: technology/cell LEFs, `2_2_floorplan_io.def`, and `1_synth.v` or a sanitized equivalent. Exclude `*_3D.fp.def`, later placed/CTS/routed DEFs, and mixed-tier processed LEFs.
7. Start with one small smoke design and confirm each plugin changes its intended state before launching a suite.

## Innovus 2D placement pattern study

TaiWei's `scripts_cadence/innovus_preplace.tcl` runs `floorPlan`, pin
placement, and then `place_design` before exporting
`2_2_floorplan_io.def`. These files are therefore complete Innovus 2D global
placements, not empty floorplan handoffs. The saved placements were analyzed
with `tools/analyze_def_distribution.py` on a 32x32 core grid using LEF master
sizes. Only `2_2_floorplan_io.def` is used; no 3D, CTS, or routed DEF is mixed
into this study.

| Design | Components | Fixed macros | Empty std-cell bins | Std-cell CV | P95/mean | Macro-covered bins |
|---|---:|---:|---:|---:|---:|---:|
| BP_quad | 795,816 | 220 | 49.1% | 1.492 | 4.086 | 49.0% |
| B19 | 72,652 | 0 | 0.2% | 0.195 | 1.341 | 0.0% |
| OpenC910 | 938,955 | 31 | 31.9% | 0.988 | 2.476 | 15.8% |
| Mempool | 2,579,164 | 324 | 37.8% | 1.074 | 2.738 | 26.2% |
| NVDLA-L | 2,229,371 | 174 | 41.7% | 1.632 | 4.601 | 60.4% |
| XScore | 3,617,126 | 201 | 0.7% | 0.482 | 1.732 | 23.4% |

The commercial pattern is conditional and strongly nonuniform. Macro-heavy
designs retain broad empty regions and irregular channels rather than enforcing
a globally uniform density. Standard-cell area is concentrated around macro
neighborhoods in BP_quad and Mempool, while OpenC910, NVDLA-L, and XScore have
near/far macro-bin utilization ratios close to one. B19, which has no macros and
zero initial EGR overflow, is the counterexample: it is comparatively uniform
and Innovus skips congestion repair.

The logs show the mechanism directly. `place_design` invokes early global
routing with `congEffort=auto`, then performs congestion-driven movement and
reruns EGR. Final H/V overflow changed from 0.07%/0.14% to 0.01%/0.03% for
BP_quad, from 0.13%/0.08% to 0.01%/0.02% for OpenC910, from 0.45%/0.37% to
0.03%/0.09% for the retained NVDLA-L run, and from 0.45%/0.39% to 0.19%/0.18%
for the retained XScore run. The latest NVDLA-L and XScore log attempts end
with status 137 during a later rerun, so their existing DEFs are useful layout
artifacts but those latest runs are not completion evidence.

Reproduce the table with:

```bash
python tools/analyze_def_distribution.py \
  --manifest configs/innovus_placement_analysis.json \
  --output-dir results/routability_lab/innovus_placement_patterns
```

## Remaining reproduction work

The branch now exposes the major classical and recent objective families, but “all published methods” is not a finite or scientifically sound implementation target. The remaining high-value work is:

- RoutePlacer: obtain explicit licensing, checkpoints/training data, pin the released source revision, and validate inference against its paper before adding a `routegnn` proxy.
- PUFFER: implement the exact feature vector and Bayesian strategy search after obtaining sufficient algorithm detail or released code.
- SimPLR and detailed-routing-driven placers: add per-layer/via and design-rule features rather than treating a 2D overflow map as an exact substitute.
- Differentiable net-moving: implement explicit virtual cells for two-pin nets and rail-aware density once the full formulation is available.
- CRP2.0 and related post-route methods: add a separate legal detailed-placement
  stage with router cost caching; the global-placement gradient hook is the wrong
  lifecycle for these operations.
- C3PO and timing-aware methods: extend the plugin context with timing paths,
  criticality, and a reproducible timer before claiming a joint objective.
- Deep-learning methods: pin datasets, feature extraction, model checkpoints,
  licenses, and inference calibration; a plugin name without those artifacts is
  not a reproduction.
- Macro porosity: replace center-scattered fixed-macro area with exact rectangle-to-grid convolution and layer-specific blockage capacity.
- Evaluator calibration: validate units and zero-overflow behavior on one known ISPD case for every router before comparing methods.

These gaps should stay visible in reports; hiding them behind plugin names would overstate reproduction fidelity.
