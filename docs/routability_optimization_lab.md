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
| Experimental control | Inverse congestion-aware wirelength response | Reduce wirelength pressure on nets crossing congested regions so density spreading can dominate | `net_relaxation` | Counter-response ablation to published congestion-aware net weighting; not claimed as a literature reproduction |
| Experimental control | Aggregate Lp overflow objective | Raise utilization above capacity to a selectable exponent so larger values increasingly emphasize peak bins | `aggregate_pnorm_gradient` | Independent smooth-tail objective with a common overflow activation gate; not claimed as a literature reproduction |
| 2000 Journal of Risk | *Optimization of Conditional Value-at-Risk* | Optimize the expected loss in a selected distribution tail | `aggregate_cvar_gradient`, `directional_cvar_gradient`, `directional_excess_cvar_gradient` | Risk-objective adaptations to aggregate or spatial H/V utilization tails; the excess variant conditions its quantile on bins above routing capacity so sparse congestion cannot collapse a requested tail into ordinary overflow; not an EDA-paper reproduction |
| 2001 DAC | *A New Congestion-Driven Placement Algorithm Based on Cell Inflation* ([DOI](https://doi.org/10.1145/370155.370560)) | Congestion-based cell inflation | `route_inflation` | Mechanism implementation |
| 2002 ISPD / 2003 TCAD | *An Effective Congestion-Driven Placement Framework* ([DOI](https://doi.org/10.1145/505388.505391), [journal DOI](https://doi.org/10.1109/TCAD.2003.809662)) | Estimation, inflation, repeated placement | `route_inflation`; legacy `AdjustNodeArea` baseline | Mechanism implementation |
| 2002 DAC / 2003, 2007 TCAD | Routability-driven white-space allocation ([DOI](https://doi.org/10.1145/505388.505400), [journal DOI](https://doi.org/10.1109/TCAD.2003.809660)) | Move whitespace toward congestion | `whitespace` | Low-frequency force approximation |
| 2007 DATE | *Fast and Accurate Routing Demand Estimation for Efficient Routability-Driven Placement* ([DOI](https://doi.org/10.1109/DATE.2007.364463)) | RUDY rectangular demand and force-directed optimization | `rudy` proxy/evaluator plus field plugins | RUDY estimator is existing native op; force is an approximation |
| 2008 DAC | *Routability-Driven Analytical Placement by Net Overlapping Removal* ([DOI](https://doi.org/10.1145/1391469.1391513)) | Move overlapping net boxes; Gaussian macro porosity | `net_overlap`, `pin_porosity` | Mechanism approximations |
| 2009 ICCAD | *A Study of Routability Estimation and Clustering in Placement* ([DOI](https://doi.org/10.1145/1687399.1687468)) | Routability estimation plus clustering before placement | Router proxies and legacy clustered inflation | Mechanism coverage; no separate objective beyond the clustered-inflation baseline |
| 2010 ICCAD | *New Placement Prediction and Mitigation Techniques for Local Routing Congestion* ([DOI](https://doi.org/10.1109/ICCAD.2010.5654225)) | Local congestion prediction and mitigation | `local_gradient`, `directional_local_gradient` | Aggregate and cross-track H/V map-gradient approximations |
| 2011 ICCAD | *A SimPLR Method for Routability-Driven Placement* ([DOI](https://doi.org/10.1109/ICCAD.2011.6105307)) | Layer/via-aware look-ahead routing; spreading and contraction | `path_inflation`, `whitespace`, `directional_net_contraction`, `directional_path_spreading`; router proxies | Partial mechanism coverage, not SimPLR reproduction; the directional plugins approximate H/V span contraction and cross-track route spreading |
| 2011 ICCAD | *Routability-Driven Analytical Placement for Mixed-Size Circuit Designs* ([DOI](https://doi.org/10.1109/ICCAD.2011.6105309)) | Pin density, sigmoid overflow, macro porosity, legalization | `pin_porosity`; legacy legalizer | Partial mechanism coverage |
| 2011 ICCAD / 2013 TCAD | *Ripple* ([DOI](https://doi.org/10.1109/ICCAD.2011.6105308), [journal DOI](https://doi.org/10.1109/TCAD.2013.2265371)) | Iterative movement of cells in congested routing paths | `path_inflation`, `local_gradient`, `directional_path_spreading` | Mechanism approximation; the directional plugin translates connected net neighborhoods across congested track directions |
| 2013 DAC / 2016 TODAES | *Ripple 2.0* ([DOI](https://doi.org/10.1145/2463209.2488922), [journal DOI](https://doi.org/10.1145/2925989)) | Routing-path inflation and congested-cluster optimization | `path_inflation`, legacy clustered inflation | Mechanism approximation |
| 2013 DAC | *Routability-Driven Placement for Hierarchical Mixed-Size Circuit Designs* ([DOI](https://doi.org/10.1145/2463209.2488921)) | Hierarchy-aware mixed-size placement | `net_weighting`, clustered inflation | Partial mechanism coverage; hierarchy is not preserved as an explicit constraint |
| 2013 ASP-DAC | *Optimizing Routability in Large-Scale Mixed-Size Placement* ([DOI](https://doi.org/10.1109/ASPDAC.2013.6509636)) | Mixed-size congestion control and spreading | `pin_porosity`, `whitespace` | Partial mechanism coverage |
| 2013 TVLSI | *Fast and Effective Placement Refinement for Routability* (CROP, [DOI](https://doi.org/10.1109/TVLSI.2012.2214408)) | LP/longest-path G-cell module shifting plus congestion-driven detailed placement and net weighting | `whitespace`, `local_gradient`, `net_weighting`, `legal_whitespace_slide` | GP force approximations plus a separate legal whole-site post-GP move operation; not the published LP/longest-path solver |
| 2014 TCAD | *NTUplace4h* ([DOI](https://doi.org/10.1109/TCAD.2014.2360453)) | Narrow channels, pin density, net congestion, hierarchy | `pin_porosity`, `net_weighting`, clustered inflation | Partial mechanism coverage |
| 2014 ASP-DAC | *Analytical Placement of Mixed-size Circuits for Better Detailed-routability* ([DOI](https://doi.org/10.1109/ASPDAC.2014.6742864)) | Group pin-density constraints and fixed-macro-aware smoothing | `pin_porosity`, `whitespace` | Constraint approximation; no explicit group pin-density constraint |
| 2014 DAC | *Routability-Driven Blockage-Aware Macro Placement* ([DOI](https://doi.org/10.1145/2593069.2593206)) | Routing blockages and macro-channel awareness | `pin_porosity`, `whitespace`; macro-aware evaluator inputs | Partial mechanism coverage; no dedicated macro legalizer objective |
| 2015 ASP-DAC | *Detailed-Routing-Driven Analytical Standard-Cell Placement* ([DOI](https://doi.org/10.1109/ASPDAC.2015.7059034)) | Routability wirelength, whitespace allocation, multistage spreading | `net_weighting`, `whitespace`, composite schedule | Global-route approximation, not detailed-route reproduction |
| 2015 ICCAD | *Detailed-Routability-Driven Analytical Placement...* ([DOI](https://doi.org/10.1109/ICCAD.2015.7372612)) | Technology/region-aware detailed-routability feedback | Evaluator interface and regional map plugins | Interface coverage only |
| 2017 ASP-DAC | *Regularity-Aware Routability-Driven Placement Prototyping...* ([DOI](https://doi.org/10.1109/ASPDAC.2017.7858362)) | Hierarchy and regular macro structure | `net_weighting`, `pin_porosity` | Feature approximation; no explicit regularity constraint |
| 2019 DATE | *Routability-Driven Macro Placement with Embedded CNN-Based Prediction Model* ([DOI](https://doi.org/10.23919/DATE.2019.8715126)) | Learned congestion prediction for macro placement | Not implemented | Needs released model/data or retraining |
| 2019 DAC | *Routability-Driven Mixed-Size Placement Prototyping...* ([DOI](https://doi.org/10.1145/3316781.3317901)) | Design hierarchy and indirect macro connectivity | `net_weighting`, `net_overlap` | Partial mechanism coverage; indirect-connectivity graph is not explicit |
| 2019 TVLSI | *Regularity-Aware Routability-Driven Macro Placement...* ([DOI](https://doi.org/10.1109/TVLSI.2018.2867833)) | Regular macro patterns under obstacles | Not implemented as a separate operation | Requires a macro-pattern constraint and macro legalization loop |
| 2019 TCAD | *RePlAce: Advancing Solution Quality and Routability Validation in Global Placement* ([DOI](https://doi.org/10.1109/TCAD.2018.2859220)) | Electrostatic placement plus independent routability validation | DREAMPlace baseline and evaluator protocol | Baseline lineage, not a new plugin |
| 2019 ICACTM | *Routability-driven Placement for Mixed-size Designs using Design-hierarchy and Pin Information* ([DOI](https://doi.org/10.1109/ICACTM.2019.8776791)) | Hierarchy/pin-aware clustering, quadratic placement, congestion spreading, and swapping | `net_weighting`, `pin_porosity`, clustered inflation | Partial mechanism coverage; no explicit hierarchy or swapping stage |
| 2020 NeurIPS | *Gradient Surgery for Multi-Task Learning* ([arXiv](https://arxiv.org/abs/2001.06782)) | Project conflicting objective gradients onto nonconflicting directions | `projected_connection_routeforce` | Gradient-conditioning adaptation, not an EDA reproduction; global/node and nonopposing/orthogonal modes are independently screened |
| 2020 ELEX | *A Local Congestion Elimination Technique Driven by Overflow* ([DOI](https://doi.org/10.1587/elex.17.20200232)) | Search keepout margins around high-pin cells in congested regions | `pin_porosity` | Padding mechanism approximation; SA/ACO parameter search is not reproduced |
| 2021 DATE | *Global Placement with Deep Learning-Enabled Explicit Routability Optimization* | Learned congestion prediction in the placement loop | Not implemented | Needs a pinned model, features, and training data |
| 2021 JCST | *DrPlace: A Deep Learning Based Routability-Driven VLSI Placement Algorithm* ([DOI](https://doi.org/10.3724/SP.J.1089.2021.18566)) | Learned routability prediction and placement guidance | Not implemented | No validated model/checkpoint is present in this tree |
| 2021 ICCAD | *Routability-driven Global Placer Target on Removing Global and Local Congestion for VLSI Designs* ([DOI](https://doi.org/10.1109/ICCAD51958.2021.9643544)) | Congestion-aware movable-net penalty and connectivity/congestion-aware cluster inflation | `net_overlap`, `net_weighting`, clustered inflation | Mechanism approximation; nets are not explicit soft modules |
| 2022 DATE | *Pin Accessibility-driven Placement Optimization with Accurate and Comprehensive Prediction Model* ([DOI](https://doi.org/10.23919/DATE54114.2022.9774753)) | Empirical pin-access difficulty prediction followed by local cell perturbation | `pin_porosity` | Predictor approximation only; no shift/flip/swap detailed-placement stage |
| 2022 VLSI-SoC | *Routability-Driven Detailed Placement Using Reinforcement Learning* ([DOI](https://doi.org/10.1109/VLSI-SoC54400.2022.9939602)) | Learned detailed-placement refinement | Not implemented | Separate post-GP detailed-placement policy; no public checkpoint or training set found |
| 2022 TVLSI | *PPOM: An Effective Post-Global Placement Optimization Methodology for Better Wirelength and Routability* | Post-GP local refinement | `local_gradient`, `net_overlap`, `legal_whitespace_slide` | Mechanism approximation with an independently gated post-GP move operation, not PPOM reproduction |
| 2023 ISQED | *Routability-aware Placement Guidance Generation for Mixed-size Designs* ([DOI](https://doi.org/10.1109/ISQED57927.2023.10129328)) | GNN cell embeddings, clustering, and commercial-placer group guidance | `net_weighting`, clustered inflation | Feature approximation; no learned embedding or explicit group-region constraint |
| 2023 ICCAD | *Routability Prediction and Optimization Using Explainable AI* ([DOI](https://doi.org/10.1109/ICCAD57390.2023.10323630)) | 49 placement/EGR features, DRV prediction, DeepSHAP attribution, and feature-selected remedies | Not integrated | Public BSD code contains training/preprocessing/SHAP analysis but no data, checkpoint, feature extractor, or optimization engine |
| 2023 TODAES | *CRP2.0* ([DOI](https://doi.org/10.1145/3590962)) | Post-global-route ILP detailed placement, net classification, and router cost/net caching | `legal_whitespace_slide` | Only the separate legal post-route-feedback stage is represented; no ILP, net classifier, or router-cost cache is reproduced |
| 2023 DAC | *PUFFER* ([DOI](https://doi.org/10.1109/DAC56929.2023.10247681)) | Multi-feature cell padding and Bayesian strategy exploration | `path_inflation`, `pin_porosity`, preset comparisons | Feature approximations; Bayesian search remains open |
| 2024 KDD | *RoutePlacer* ([DOI](https://doi.org/10.1145/3637528.3671895)) | Differentiable RouteGNN congestion surrogate | Not integrated | Public source exists, but no checkpoint or license was present in the audited tree |
| 2024 DAC LBR | *Coulomb Force-Based Routability-Driven Placement* ([DOI](https://doi.org/10.1145/3649329.3663501)) | Routing-path padding plus global virtual Coulomb forces | `path_inflation`, `poisson_force` | Mechanism approximation |
| 2025 Integration | *Routability-wirelength co-guided cell inflation with explainable multi-task learning for global placement optimization* ([DOI](https://doi.org/10.1016/j.vlsi.2025.102624)) | Explainable multi-task prediction co-guiding cell inflation and wirelength control | `route_inflation`, `adaptive_composite` | Inflation mechanism coverage only; article is closed and no public model/code was found |
| 2025 DAC | *RUPlace: Optimizing Routability via Unified Placement and Routing Formulation* | Xplace GGR feedback, clustered/local inflation, route force | Legacy RUPlace controller, `routeforce`, `connection_routeforce`, `multisegment_connection_routeforce`, `routed_overflow_net_contraction`, inflation plugins | Released implementation lineage retained; the connection plugin exposes Xplace's routed-segment demand/capacity force separately from its ADMM force, with optional aggregate-via and layer-short-conditioned via fields. The independent multisegment ablation sums or averages all same-axis route branches at a global pin instead of inheriting the released kernel's last-branch overwrite; the original entry point remains the reference. The short-conditioned field uses full-layer maps because the pinned evaluator includes M1, and includes via demand where total wire-plus-via utilization exceeds one, exactly matching the evaluator's via-short mask. `routed_overflow_net_contraction` reuses the pinned routed-segment contraction kernel without its anchor, evaluates horizontal and vertical routed overflow separately, and retains only the matching along-route contraction axis. Legacy aggregate and max-layer fields retain their M1-excluded behavior. |
| 2025 DAC | *Differentiable Net-Moving and Local Congestion Mitigation...* ([DOI](https://doi.org/10.1109/DAC63849.2025.11133117)) | Momentum inflation, Poisson congestion, virtual cells on two-pin nets, rail-aware density | `momentum_inflation`, `poisson_force`, `virtual_cell`, `directional_virtual_cell` | Mechanism approximations; the virtual midpoint forces translate movable two-pin endpoints together, and the separate directional variant uses cross-track H/V Poisson feedback with aggregate fallback for RUDY, while the undisclosed rail-density formulation is not reproduced |
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
| Library pin-layout selection | *Placement-guided Pin Layout Substitution for Routability Optimization* (Microelectronics Journal 2021) | Chooses alternate characterized-cell pin layouts; the current benchmarks and placement database expose no interchangeable library-cell pin views |
| Macro-only learned methods | DATE 2019 CNN macro placement; DATE 2026 LBR RL macro placement | No validated public model/checkpoint and the objective acts on macro floorplanning, not the mixed-size GP loop implemented here |

The live source audit on 2026-07-26 found Xplace under BSD-3-Clause. The public
RoutePlacer repository existed but GitHub reported no repository license; it is
therefore a research reference, not a dependency that can be copied into this
tree. A 2026-07-29 refresh through OpenAlex, Crossref, DOI metadata, and GitHub
also audited the BSD-3-Clause `XAI_RoutOpt` release. That repository calls a
missing `MODEL/.../step_*` checkpoint and `TORCH` data tree, relies on the
separate ClipGraphExtract flow, and releases no placement-remedy engine. The
newly found learned cell-inflation article is closed and has no public model or
code. Consequently, neither learned selector is a runnable independent plugin
in this branch; their underlying inflation and regional-force mechanisms remain
covered by the existing atomic operations. Search hits alone are not evidence
of reproducibility.

## Post-placement operation contract

`legal_whitespace_slide` is deliberately separate from the analytical
`ruplace_plugins` lifecycle. A preset declares its dependencies under
`ruplace_post_placement`: an already completed HPWL baseline, an already
completed route-feedback oracle, a strict acceptance group, and the movement
limits. The comparison runner requires both source methods to precede the
derived method, projects only standard cells into real row whitespace by whole
sites, preserves row, y-coordinate, and orientation, and rejects any output
with an overlap.

The oracle supplies direction only; its placement is never accepted directly.
Every derived DEF is evaluated independently by RUDY and GPUGR. After both
backends finish, the acceptance operation requires at least one RUDY
improvement, at least one GPUGR improvement, and zero positive GPUGR primary
delta. It verifies the baseline, oracle, LEF, output, report, and evaluator
hashes before materializing either the first declared strict survivor or a
byte-identical baseline rollback. Backend values are not combined, and this
development gate cannot consume held-out or golden evidence.

The opt-in base preset uses `hpwl` as the baseline and `routeforce` as the
oracle, so a valid invocation orders methods as
`hpwl,routeforce,legal_whitespace_slide`. Campaign-specific preset files may
name another route-feedback oracle while retaining the same operation and
acceptance contracts.

`openroad_routability_oracle` is a second independent post-placement operation.
It freezes the OpenROAD incremental-GPL/GRT-feedback command, performs detailed
placement and `check_placement`, and records the resolved OpenROAD executable
hash, version, options, TCL, log, input hashes, and output hash. The oracle is
never an acceptance candidate; legal refinement may consume only its movement
direction. A seed-1000 replay with OpenROAD `26Q1-951-g6975124cf2` reproduced
the original oracle byte-for-byte.

`legal_whitespace_net_bbox` is a separate objective variant of the legal
projection. It retains the OpenROAD direction but ranks a one-site move by the
change in the x-span of its connected signal nets, using component origins as
an intentionally simple pin-location proxy. `max_net_bbox_delta_dbu` can reject
predicted expansion. The limit is rechecked against the current placement
immediately before every move, and the report records the baseline/output
aggregate x-span and blocked-move counts. This quantity is only a move filter;
it is not routed wirelength and cannot satisfy either proxy gate by itself.
The default displacement-ranked operation is unchanged.

## Plugin contract

`ruplace_plugins` accepts a list or comma-separated string. Every plugin is a separate module under `dreamplace/ops/routability_opt/plugins/` and implements one or more lifecycle hooks:

```python
prepare_objective(pos, model, context)
apply_gradient(pos, model, context)
commit_post_gradient(pos, model, context)
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
| `net_relaxation` | Wirelength net weights | Does reducing wirelength pressure on congested nets let density spreading remove hotspots? |
| `directional_net_contraction` | Placement gradient through per-axis net spans, with shared or per-axis congestion normalization | Does contracting only the congested H/V span reduce routed demand without bias from an asymmetric routing stack? |
| `directional_path_spreading` | Placement gradient through cross-track net fields | Does shifting horizontal routes across y and vertical routes across x reduce routed hotspots? |
| `virtual_cell` | Placement gradient through two-pin virtual midpoints | Does translating both endpoints from a shared Poisson-field sample move a net out of congestion without directly stretching its span? |
| `directional_virtual_cell` | Placement gradient through two-pin virtual midpoints and cross-track H/V Poisson fields | Does directional midpoint translation avoid the peak/tail regressions of aggregate virtual-cell feedback? |
| `connection_routeforce` | Placement gradient through routed GGR segments | Do aggregate, H/V-directional, or layer-maximum per-edge demand/capacity fields outperform aggregate maps and ADMM feedback? |
| `multisegment_connection_routeforce` | Sum or average every same-axis routed branch incident to a global pin | Does retaining branch contributions discarded by Xplace's last-branch overwrite improve proxy and golden routability without destabilizing placement? |
| `projected_connection_routeforce` | Conflict-conditioned routed GGR gradient | Does partially or fully removing routeforce components that oppose or duplicate the placement gradient reduce routed-QoR regressions? |
| `routed_overflow_net_contraction` | Placement gradient through direction-matched routed-overflow net contraction | Does contracting only the routed span responsible for H/V overflow reduce demand without an opposing anchor force? |
| `net_overlap` | Placement gradient through net-level fields | Does moving whole net neighborhoods help? |
| `pin_porosity` | Cell/filler area | Do pin density and macro porosity explain residual failures? |
| `whitespace` | Placement gradient | Does regional whitespace transfer help? |
| `routeforce` | Placement gradient | Does Xplace routed-wire feedback help independently? |

`connection_routeforce` and `projected_connection_routeforce` also expose
`ruplace_connection_routeforce_pressure_exponent`. The default `1.0` preserves
the linear directional-utilization pressure field. Values below one spread
attention across more bins above the utilization floor, while values above one
emphasize the hottest horizontal and vertical bins before DCT force
construction. The separately weighted short-aware via-pressure term remains
linear. This is a development-only tuning control for overflow-net and
peak/tail congestion regressions; it does not relax any RUDY, GPUGR, held-out,
or golden-routing gate.

`net_weighting` computes design-mean normalization and weight updates only for
nets enabled by DREAMPlace's wirelength net mask. One-pin and ignored
large-degree nets therefore cannot change the normalization applied to the
objective's active nets.

`net_relaxation` is an explicit inverse-response ablation, not a claimed
reproduction of published net weighting. It uses a separate parameter
namespace and a positive minimum-weight floor. It is mutually exclusive with
`net_weighting` because both operations mutate the same objective weights.

`configs/routability_plugins/presets.json` contains one-method presets and an `adaptive_composite` preset. An empty `ruplace_plugins` retains the old RUPlace controller.

## Proxy providers

| Proxy | Input class | Differentiable | Cost | Notes |
|---|---|---:|---:|---|
| `rudy` | LEF/DEF or Bookshelf | No native backward | Low | Native DREAMPlace RUDY map; plugin feedback freezes input net weights so objective reweighting cannot amplify its own signal |
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
- `openroad`: FastRoute guide and directional overflow, plus optional
  TritonRoute detailed routing with final DRC, unrouted-net, short, routed
  wirelength, and via metrics.
- `innovus`: v22 `earlyGlobalRoute` or `globalDetailRoute` through the
  `cadence-local` container. Detailed mode reports H/V congestion or overflow,
  final DRC, routed versus routable nets, shorts, regular-net connectivity,
  routed wirelength, and vias. It requires topology-matched Verilog and an
  output directory mounted by the wrapper.

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
Numeric plugin telemetry includes `count`, `nonzero_count`, `min`, `max`,
`mean`, and `last`. The unsuffixed `metrics` object remains the final sample for
compatibility; it must not be interpreted as the history of a run. For example,
a final zero congestion-gradient norm can coexist with earlier nonzero plugin
activations.

Generate bounded atomic, pair/triple, and hyperparameter sweeps from a JSON specification
with `tools/routability_generate_presets.py`. The generator writes both the
presets and a provenance manifest, requires an explicit congestion proxy, skips
non-GPUGR `routeforce` combinations, and rejects identity-key overrides. Pass the
result through either campaign layer with `--presets`; both
`routability_campaign.py` and `routability_parallel.py` forward the exact file to
the comparison runner. A `plugin_grids` mapping scopes strength controls to the
plugins that consume them, avoiding duplicate configurations from irrelevant
Cartesian dimensions. Survivor selection should precede pair/triple generation;
a bounded atomic strength sweep is the fallback when no default-strength method
passes the predeclared wirelength guardrails.

After freezing survivors, use `tools/routability_golden_replay.py` to copy their
placed DEFs and mapped configs into a separate artifact tree and evaluate only
OpenROAD and/or Innovus. The replay rejects incomplete source campaigns,
unvalidated source comparisons, failed placements, fallback evaluators, and
missing DEFs. Its output uses the same comparison and parallel-status schemas,
so `tools/routability_summarize.py` applies the identical completion, baseline,
coverage, and case-level confidence gates to golden results.

Golden replay also enforces an activation-provenance contract before routing.
For every candidate, `routability_plugin_status` must be `active`, the selected
and per-plugin summary names must exactly match the frozen config's
`ruplace_plugins`, and every selected plugin must report a positive activation
count. The HPWL baseline must instead report `not_selected` with an empty
plugin summary. `partially_active`, selected-but-no-change, missing summaries,
and config/name mismatches are invalid. Resume rechecks both source and replayed
placement records, the summarizer excludes invalid comparisons, and the final
ranker refuses summaries without a validated activation contract.

`tools/routability_select_survivors.py` freezes the methods eligible for the
first pair sweep. It requires a complete validated screening campaign and full
plugin activation, rejects candidates outside explicit placement-HPWL and
GPUGR-wirelength guardrails, and computes a multiobjective Pareto frontier over
the separately retained placement, RUDY, and GPUGR metrics. It does not add
cross-backend values into a synthetic score. The emitted JSON records every
qualified/excluded method and reason. For a generated tuning campaign, pass its
provenance file with `--preset-manifest`; selection then retains at most one
tuned preset per atomic plugin and carries each mechanism-specific strength into
the optional combination specification. Shared activation thresholds remain an
explicit pair-level grid instead of being inherited from either atomic preset.

After atomic and pair settings pass their held-out checks, use
`tools/routability_freeze_presets.py` to combine their selector outputs with the
corresponding preset files. The freezer rejects conflicting duplicate method
definitions, retains one HPWL baseline, and writes exact source/selection
provenance for the unified finalist placement and golden-routing campaign.

Required controls for a defensible table:

1. Same input revision, LEFs, DEF topology, netlist, target density, bins, seed, optimizer, and placement iteration budget.
2. Require complete placement-HPWL coverage for every routed method and report it
   beside the routed metrics. Keep it in a separate diagnostic field: placement
   HPWL must not enter Pareto frontiers, safety gates, evidence gates, or winner
   selection. Draw final routability conclusions only from OpenROAD and/or
   Innovus.
3. Attempt both golden validators. Use RUDY and bundled GPUGR only as the common fallback when golden evaluation cannot run on the case. Keep pin-RUDY, external Xplace, CUGR, and NCTUgr diagnostic-only.
4. For golden detailed routes, report H/V congestion or overflow separately,
   total DRC, unrouted nets, shorts/connectivity violations, routed wirelength,
   vias, and runtime. For fallback routes, report the available routed
   wirelength, vias, overflow, overflow nets, and estimated shorts. Do not
   collapse metrics or router backends into one score.
5. Rank H/V congestion/overflow, DRC, routed wirelength, unrouted nets, shorts,
   and connectivity failures as primary routability objectives. Treat vias as
   a required secondary routed cost and placement HPWL as diagnostic only. The
   complete routability vector therefore includes H/V congestion,
   DRC/connectivity failures, routed wirelength, and vias. A robust
   default must be primary-safe and primary-Pareto across every golden backend.
   Among robust candidates, remove one only when the same alternative is no
   worse on every full objective in every backend and strictly better
   somewhere. Routed-wirelength-only improvement is not sufficient: at least
   one congestion, DRC, unrouted, short, or connectivity metric must show
   supported improvement. Bound the via tradeoff to at most `+5%` mean and
   `+10%` worst-case regression, with no absolute increase from a zero
   baseline. Report the minimum
   mean/worst percentage budget required by every alternative and identify any
   zero-baseline absolute increase so the default budget can be sensitivity
   checked without rerunning placement or routing.
6. Separate router failure, unsupported input, timeout, and clean zero overflow.
7. Use the TaiWei **2D phase** inputs only: technology/cell LEFs,
   `2_2_floorplan_io.def`, and its topology-matched
   `2_2_floorplan_io.v`. Use `1_synth.v` only when component matching proves
   that placement did not change topology. Exclude `*_3D.fp.def`, later
   placed/CTS/routed DEFs, and mixed-tier processed LEFs.
7. Start with one small smoke design and confirm each plugin changes its intended state before launching a suite.

For Cadence 2D handoffs whose DEF contains components but no regular `NETS`,
`tools/routability_materialize_def.py` can use OpenROAD to link the original
synthesized Verilog, overlay `2_2_floorplan_io.def`, and emit a
connectivity-complete DEF for DREAMPlace. The operation records input/output
component, pin, and net counts; rejects zero-net or incomplete output; and
enforces physical-name matching and unplaced-linked-instance gates. DEF-only
placement is not a valid substitute because it produces a zero-net objective.
Any physical-only cells or stale netlist-only cells are reported rather than
silently treated as topology-compatible.

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
- Differentiable net-moving: the two-pin midpoint and directional cross-track
  virtual-cell mechanisms are implemented as separate approximations; reproduce
  rail-aware density only when the undisclosed formulation becomes available.
- CRP2.0 and related post-route methods: add a separate legal detailed-placement
  stage with router cost caching; the global-placement gradient hook is the wrong
  lifecycle for these operations.
- C3PO and timing-aware methods: extend the plugin context with timing paths,
  criticality, and a reproducible timer before claiming a joint objective.
- Deep-learning methods: pin datasets, feature extraction, model checkpoints,
  licenses, and inference calibration; a plugin name without those artifacts is
  not a reproduction.
- Macro porosity now uses exact fixed-macro rectangle-to-grid overlap rather
  than center-scattered area. Layer-specific routing-blockage capacity remains
  open because the placement database exposes only aggregate macro geometry to
  this plugin.
- Diagnostic-router calibration: OpenROAD and Innovus golden detailed-route
  units, zero/nonzero congestion, and zero/nonzero DRC behavior are covered by
  retained ISPD/Nangate45 smokes and artifact-reparsing tests. CUGR, NCTUgr,
  external Xplace, and other diagnostic-only routers still need equivalent
  per-version unit and zero-overflow calibration before any future promotion.

These gaps should stay visible in reports; hiding them behind plugin names would overstate reproduction fidelity.
