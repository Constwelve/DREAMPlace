# Routability Lab Validation Status

Validated through 2026-07-29 in the isolated worktree
`.worktrees/ruplace-routability` on branch `feat/routability-lab`. The main
DREAMPlace checkout was not modified.

## Routability-first revalidation in progress

The earlier conclusion in this document preserved HPWL because the finalist
did not improve common-router wirelength robustly. A stricter rerun is now in
progress and does not treat placement HPWL as a routability objective.

- Primary golden routability metrics are horizontal and vertical
  congestion/overflow, detailed-route DRC violations, routed wirelength,
  unrouted nets, shorts, and backend-specific connectivity violations. Vias are
  a required secondary routed cost. Placement HPWL is diagnostic only.
- OpenROAD and Innovus are ranked separately. RUDY and bundled GPUGR are used
  only for screening/fallback, and no numeric score mixes router backends.
- A default candidate is eligible only if it is no worse than HPWL in both
  mean and worst case for every primary metric and remains on the primary
  Pareto frontier for every golden backend, while Pareto-dominating the
  baseline in primary routability on at least one backend with either a
  design-level 95% confidence interval below zero or consistent improvement
  across every case-seed. A backend where every method ties cannot veto an
  improvement elsewhere, but an H/V congestion, DRC, unrouted, short,
  connectivity, or routed-wirelength regression does veto default selection.
- Vias do not independently veto a primary routability win. They refine the
  full backend-local Pareto comparison, and a robust
  candidate is removed only when the same robust alternative is no worse on
  every full objective in every backend and strictly better somewhere.
  The default secondary-cost budgets are at most `+5%` mean and `+10%`
  worst-case regression for vias; a zero baseline permits no absolute
  increase. This exposes bounded cost tradeoffs without scalarizing unlike
  metrics. The final ranking reports the minimum mean/worst percentage budget
  each alternative actually requires, plus any zero-baseline absolute increase.
- Confidence intervals use per-design means of paired percentage deltas when
  every baseline value is nonzero. Metrics containing a zero baseline use
  absolute deltas instead, and numerical changes within `1e-12` are ties rather
  than wins or losses.

The active contest replay is
`results/routability_remote/ispd2019_routability_first_unified_3583ba6/golden_openroad_detailed_3583ba6`.
The original 7,200-second limit was insufficient for ISPD2019 test2: the HPWL
seed-1000 route timed out with about 284,050 violations while 10% through its
second TritonRoute optimization iteration. That replay was stopped without
removing artifacts and resumed on 2026-07-27 with a 21,600-second per-route
limit. The refreshed test1 HPWL routes for all three seeds already satisfy the
complete contract: zero H/V overflow, DRC, unrouted nets, and shorts, with
positive detailed-route wirelength and vias. The older test1 comparison rows
are rerun rather than skipped because their persisted schema predates the
unrouted-net and short fields.

The 20-iteration test2 routes were still CPU-active after roughly five hours,
and the retained first attempt showed that the initial route, one complete
optimization iteration, and 10% of the second took about 1 hour 40 minutes.
Continuing to a six-hour timeout would not emit a usable final metric report.
On 2026-07-28 the OpenROAD-only replay was therefore restarted with
`openroad_droute_end_iteration=2` for every test2 method and seed. Test1 and
test3 retain the 20-iteration setting. The first completed capped log confirms
that this value runs optimization iterations 0, 1, and 2 inclusively. This is a
documented, size-specific runtime cap, never a method-specific setting.
Contract-checked
per-method resume reuses a route only when its config is unchanged, all routed
metrics are finite and nonnegative, routed wirelength is positive, and the log,
DRC, metrics, route script, and backend-specific guide/connectivity artifacts
still exist. This preserved the completed test1 and test3 HPWL evidence while
forcing every prior test2 timeout to rerun.

At the 2026-07-28 03:26 SGT checkpoint, this campaign was `3/9`
case-seeds complete, `4` running, `2` pending, and `0` failed under supervisor
PID `574618`. All 15 completed test1 method routes satisfy the detailed-route
contract. Every violation metric ties at zero on test1, so that easy case
distinguishes candidates only through routed-wirelength and via outcomes;
test2/test3 remain necessary.

The test3 seed-1000 HPWL detailed route then completed in 14,620 seconds and
passed the current contract with zero H/V global overflow, 2,207 detailed-route
DRC violations, 1,962 short-class violations, zero unrouted nets, 82,543 um
routed wirelength, and 62,977 vias. The DRC marker report contains 1,961
`Short` entries plus one `Cut Short`, matching the final TritonRoute short-row
total. Unlike test1, test3 therefore provides nonzero detailed-route violation
outcomes even though its global overflow is zero. The same case-seed is now
routing the plugin methods sequentially.

The first test3 plugin route, the `net_weighting` + `local_gradient` pair,
subsequently passed direct artifact re-parsing with zero H/V overflow and zero
unrouted nets, but regressed every nonzero detailed-route outcome against its
same-seed HPWL baseline: 2,496 DRC violations (`+13.094%`), 2,269 shorts
(`+15.647%`), 82,760 um routed wirelength (`+0.263%`), and 63,233 vias
(`+0.407%`). This is routability evidence against the pair; placement HPWL is not
used to soften that conclusion.

Atomic `local_gradient` then completed the same test3 seed and passed
identity-checked H/V backfill plus detailed-route artifact re-parsing. It tied
HPWL at zero H/V overflow and zero unrouted nets, but increased DRC from 2,207
to 2,488 (`+12.732%`), shorts from 1,962 to 2,207 (`+12.487%`), routed
wirelength from 82,543 to 82,695 um (`+0.184%`), and vias from 62,977 to
63,110 (`+0.211%`). This held-out regression makes `local_gradient`
ineligible as a robust OpenROAD default even though it was strong on test2
seeds 1000 and 2000.

At the 2026-07-28 04:55 SGT checkpoint, the OpenROAD campaign retained 20/45
individual detailed routes and the Innovus campaign retained 19/75. Direct
`require_complete=True` artifact re-parsing passed all 39 routes with no
missing required metric or persisted/raw disagreement. Each backend still had
three complete five-method case-seed comparisons: all test1 seeds for OpenROAD
and all BP_quad seeds for Innovus. Refreshed partial summaries contained zero
excluded comparisons and zero HPWL-baseline gaps, but correctly exited nonzero
because the full campaign completeness gates remain 3/9 and 3/15. No partial
row is eligible for a final winner decision.

The test2 seed-3000 HPWL capped detailed route completed in 10,435 seconds and
passed the contract with zero H/V global overflow, 220,665 total DRC
violations, 162,280 shorts, zero unrouted nets, 5,442,615 um routed wirelength,
and 1,241,333 vias. The final TritonRoute short-row values sum exactly to the
parsed short count, and the final log values agree with `openroad_metrics.json`.
This OpenROAD build exposes no unlimited marker-report option: the standalone
`-output_drc` report caps common violation categories at 10,000 entries, so its
line count is not an alternate total-DRC counter on highly violating designs.
The uncapped final iteration table and metrics JSON are authoritative and are
both reparsed by the consistency gate. The supervisor advanced this case-seed
to the pair candidate.

The test2 seed-1000 HPWL route passed the same capped contract in 11,527
seconds with zero H/V global overflow, 268,532 total DRC violations, 197,625
shorts, zero unrouted nets, 5,460,141 um routed wirelength, and 1,277,111 vias.
The final TritonRoute table and `openroad_metrics.json` agree on total DRC,
routed wirelength, and vias, and the short row sums exactly to the persisted
short count.

The test2 seed-2000 HPWL route then completed in 15,368 seconds with zero H/V
global overflow, 617,428 total DRC violations, 461,375 shorts, zero unrouted
nets, 7,225,233 um routed wirelength, and 1,444,629 vias. The retained route
script confirms the same `droute_end_iter=2` setting used by every test2 method
and seed, and direct artifact re-parsing reproduced every persisted metric.
This seed's source placement HPWL is 59,926,280, versus about 45.1 million for
seeds 1000 and 3000, so its larger routed wirelength is a placement-seed effect
rather than a backend configuration mismatch. Placement HPWL remains
diagnostic and does not replace the routed-QoR objectives.

Across the three completed test2 HPWL baselines, total DRC spans 220,665 to
617,428 (`2.80x`), shorts span 162,280 to 461,375 (`2.84x`), routed wirelength
spans 5,442,615 to 7,225,233 um (`1.33x`), and vias span 1,241,333 to 1,444,629
(`1.16x`). All method conclusions therefore use paired method-minus-HPWL
deltas within each case-seed. Confidence intervals aggregate the three seeds
to one mean per design rather than treating repeated seeds as independent
design evidence.

The first test2 plugin result then completed for seed 1000. The
`net_weighting` + `local_gradient` pair passed strict raw-artifact re-parsing
with zero H/V overflow and zero unrouted nets. Against the same-seed HPWL
route, it reduced DRC from 268,532 to 151,639 (`-43.530%`), shorts from 197,625
to 115,414 (`-41.599%`), routed wirelength from 5,460,141 to 4,904,112 um
(`-10.183%`), and vias from 1,277,111 to 1,111,734 (`-12.949%`). This improves
every routed metric on one difficult case-seed, but it is not a
method-level conclusion until the other test2 seeds, test3 methods, and both
complete backend campaigns close.

The pair then completed test2 seed 2000 with artifact-backed DRC, short,
routed-wirelength, and via values of 155,944, 117,717, 4,996,713 um, and
1,144,124, respectively. Relative to the same-seed HPWL route, these are
improvements of `-74.743%`, `-74.486%`, `-30.844%`, and `-20.802%`. The worker
was launched before the OpenROAD congestion-retention fix and therefore did
not retain its FastRoute report. Its persisted 0/0 H/V values are not accepted
as golden evidence yet; the finalizer must reproduce the original global-route
wirelength and via counts exactly before attaching backfilled directional
overflow. This strong single-backend result does not override the pair's
large NVDLA-L Innovus regressions or establish a cross-backend winner.

The same pair then completed test2 seed 3000 in 20,190 seconds, before its
21,600-second timeout, and passed strict raw-artifact re-parsing. Its retained
FastRoute report contains 514 horizontal and 1,772 vertical overflow, while
the detailed route contains 655,259 DRC violations, 498,891 shorts, zero
unrouted nets, 7,685,084 um routed wirelength, and 1,558,946 vias. A targeted
global-route replay exactly reproduced the HPWL route's original wirelength
and via counts of 5,936,236 and 1,012,603, respectively, and established a
valid H/V baseline of 0/0. The pair therefore regressed directional congestion
by an absolute 514/1,772 overflow, DRC by `+196.947%`, shorts by `+207.426%`,
routed wirelength by `+41.202%`, and vias by `+25.586%`. These regressions make
the pair ineligible as a robust OpenROAD default, independently confirming its
Innovus NVDLA-L failure.

Atomic `local_gradient` subsequently completed test2 seed 1000 with
artifact-backed DRC, short, routed-wirelength, and via values of 154,201,
117,531, 5,008,277 um, and 1,141,151. Against the same-seed HPWL route these
improve by `-42.576%`, `-40.528%`, `-8.276%`, and `-10.646%`. This pre-install
worker also lacks a retained FastRoute congestion report, so its persisted H/V
values remain excluded until identity-checked global-route backfill succeeds.
The result is promising single-case evidence, not a method-level conclusion.

Atomic `local_gradient` then completed test2 seed 3000 and passed the resume
contract plus direct raw-artifact re-parsing. It tied the same-seed HPWL route
at zero H/V overflow and zero unrouted nets, but regressed DRC from 220,665 to
258,549 (`+17.168%`), shorts from 162,280 to 198,985 (`+22.618%`), and routed
wirelength from 5,442,615 to 5,895,674 um (`+8.324%`). Vias decreased from
1,241,333 to 1,238,680 (`-0.214%`). Both zero-byte FastRoute congestion reports
reparse to zero overflow edges; the HPWL baseline also has an identity-checked
global-route backfill, so 0/0 is a valid tied outcome rather than a missing
metric. The DRC and short regressions independently confirm that
`local_gradient` is not a robust OpenROAD default. Its routed-wirelength
regression is an additional primary veto; vias remain secondary-cost evidence.

Atomic `net_overlap` subsequently completed OpenROAD test2 seed 1000 and
passed the resume contract plus direct raw-artifact re-parsing. It tied the
same-seed HPWL route at zero H/V overflow and zero unrouted nets, but increased
DRC from 268,532 to 1,178,982 (`+339.047%`), shorts from 197,625 to 889,594
(`+350.142%`), routed wirelength from 5,460,141 to 8,681,483 um (`+58.997%`),
and vias from 1,277,111 to 1,529,196 (`+19.739%`). The DRC and short
regressions independently disqualify `net_overlap` as a robust OpenROAD
default and agree with its Innovus BP_quad and NVDLA-L failures.

The held-out test3 seed-1000 `net_overlap` route later completed after
19,512 seconds and passed the same strict candidate/baseline artifact reparse.
It tied HPWL at zero H/V overflow and zero unrouted nets and slightly improved
routed wirelength from 82,543 to 82,492 um (`-0.062%`). That wirelength-only
gain came with DRC increasing from 2,207 to 3,115 (`+41.142%`), shorts from
1,962 to 2,685 (`+36.850%`), and vias from 62,977 to 63,381 (`+0.642%`). This is
additional held-out evidence that `net_overlap` is not routability-safe and
demonstrates why routed wirelength cannot override violation regressions.

OpenROAD test2 seed-2000 `net_overlap` then produced a strongly positive but
seed-sensitive result and passed the strict artifact contract. It tied HPWL at
zero H/V overflow and zero unrouted nets while reducing DRC from 617,428 to
171,514 (`-72.221%`), shorts from 461,375 to 128,798 (`-72.084%`), routed
wirelength from 7,225,233 to 5,078,536 um (`-29.711%`), and vias from 1,444,629
to 1,121,658 (`-22.357%`). This route remains important positive Pareto and
statistical evidence, but it cannot erase the same method's `+339.047%` DRC
regression on test2 seed 1000 or its held-out test3 and Innovus regressions.
The incomplete test2 three-seed slice therefore must not be summarized by this
single favorable seed.

OpenROAD test2 seed-1000 `net_weighting` subsequently completed the fifth
method for that case-seed and passed the strict candidate/baseline reparse. It
tied HPWL at zero H/V overflow and zero unrouted nets, reduced DRC from 268,532
to 264,338 (`-1.562%`), shorts from 197,625 to 194,286 (`-1.690%`), and vias
from 1,277,111 to 1,264,762 (`-0.967%`). Routed wirelength increased from
5,460,141 to 5,508,702 um (`+0.889%`). Under the current metric policy this is
a primary routed-wirelength regression, so the result is not primary-safe on
this slice. It advanced OpenROAD to
`4/9` completed case-seeds, but it cannot erase the method's Innovus BP_quad
seed-3000 H/V regression.

OpenROAD test2 seed-2000 `net_weighting` later passed the same strict artifact
contract and produced a strongly positive result. It tied HPWL at zero H/V
overflow and zero unrouted nets while reducing DRC from 617,428 to 370,799
(`-39.945%`), shorts from 461,375 to 278,258 (`-39.689%`), routed wirelength
from 7,225,233 to 6,178,487 um (`-14.487%`), and vias from 1,444,629 to
1,323,409 (`-8.391%`). This adds important positive Pareto evidence and again
shows large seed sensitivity. Test2 seed 3000 remains necessary for the full
design slice, and the existing Innovus BP_quad H/V regression still prevents a
robust cross-backend recommendation.

The five-design, three-seed placement campaign
`results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/campaign`
completed `15/15` case-seeds with no failures on `ceca2080x4`. Its complete
proxy summary is in the sibling `proxy_summary_15of15_3583ba6` directory.
The 75 placements were transferred locally and are being manufacturing-grid
snapped and replayed with Innovus 22 detailed routing. Golden replay supports
contract-aware `--resume`: only already-validated case-seeds with the complete
current detailed-route schema can be skipped.

The Innovus replay is active in tmux session `ruplace_innovus_3583ba6` with
supervisor PID `3258438`. Four case-seeds run in parallel. At the 2026-07-28
06:12 SGT checkpoint, all three BP_quad seeds had completed all five methods,
with the three mempool seeds and NVDLA seed 1000 active. The queue was `3/15`
case-seeds complete, `4` running, `8` pending, and `0` failed, with `20`
individual detailed routes persisted.

The first persisted real-design row, BP_quad seed 1000 HPWL, passed the full
contract with 25,880,086.7106 um routed wirelength, 8,212,255 vias, 0.11%/0.16%
H/V congestion, 14,259 total DRC violations, 11,005 shorts, zero unrouted nets,
and zero regular-net connectivity violations. Direct artifact checks found all
912,665 routable nets had routed wires and counted exactly 11,005 `SHORT:`
records in the 14,259-violation DRC report. Its manufacturing-grid snap changed
coordinates by at most one DEF unit. This establishes that the active real
campaign reports nonzero violations rather than silently reducing the
comparison to wirelength.

The first three-seed plugin comparison is also complete for BP_quad. The
`net_weighting` + `local_gradient` pair improved mean H/V congestion by
9.091%/8.333% and shorts by 0.532%; vertical congestion and shorts improved on
all three seeds, while horizontal congestion improved on two and tied on one.
It increased routed wirelength by 0.856% on average and lost all three seeds.
More importantly, total DRC improved on two seeds but regressed by 105
violations (0.751%) on seed 3000. This is interim single-design evidence, not a
campaign conclusion, but that nonzero worst DRC regression already makes
the pair ineligible under the frozen robust-default rule. It remains in the
full Pareto report as a routability/cost tradeoff candidate.

The atomic `local_gradient` routes then completed all three BP_quad seeds and
passed the same metric contract. Relative to HPWL, mean H/V congestion changed
by -6.061%/-4.167%, total DRC by -2.198%, and shorts by -1.122%. DRC and shorts
improved on all three seeds; each directional congestion metric improved on two
and tied on one. Unrouted nets and regular-net connectivity violations stayed
at zero. Routed wirelength regressed by +1.052% on average, with all three
seeds losing, and vias regressed by +0.037%. The routed-wirelength regression
makes this BP_quad slice primary-unsafe, although it remains visible as a
Pareto tradeoff. It also cannot become the robust default because its
OpenROAD test3 and Innovus NVDLA-L results regress primary DRC and directional
congestion metrics.

All three BP_quad `net_overlap` routes passed the artifact contract but
regressed every requested nonzero routed-QoR objective. Mean H/V congestion
increased by 137.576%/106.250%, total DRC by 12.191%, shorts by 15.493%, routed
wirelength by 11.681%, and vias by 10.856%. The worst seed changes were
140.000%/112.500% H/V congestion, 16.501% DRC, 20.891% shorts, 12.066% routed
wirelength, and 11.305% vias. Unrouted nets and regular-net connectivity
violations remained zero, and each parsed short count exactly matched its DRC
report. `net_overlap` is therefore ineligible as a robust default.

The three BP_quad `net_weighting` routes also completed with exact DRC
short-count agreement. Mean total DRC and shorts improved by 1.245% and 1.007%,
respectively, but mean H/V congestion regressed by 3.333%/2.083%. Seeds 1000
and 2000 tied the HPWL baseline in both directions, while seed 3000 regressed
H/V congestion by 10.000%/6.250%. Routed wirelength increased by 0.149% on
average and vias by 0.100%; unrouted nets and regular-net connectivity
violations remained zero. The directional seed-3000 regression makes
`net_weighting` ineligible under the frozen routability-safe rule despite its DRC
improvement.

The mempool seed-1000 HPWL detailed route then completed in 18,004 seconds and
passed the full contract with 2.32%/2.97% H/V congestion, 9,579,257 total DRC
violations, 8,565,140 shorts, zero unrouted nets, zero regular-net connectivity
violations, 156,103,162.128 um routed wirelength, and 38,989,687 vias. The
1.99-GB unlimited DRC report contains exactly 8,565,140 `SHORT:` records, and
its final `Total Violations` line exactly matches the parsed DRC count. This
large nonzero baseline finished within the 21,600-second per-route limit and
establishes that the real-design campaign is exercising severe congestion and
detailed-route failures rather than only easy zero-violation cases.

The same-seed `net_weighting` + `local_gradient` pair subsequently passed a
direct strict reparse of its retained Innovus log, 1.86-GB DRC report,
connectivity report, and metric file. It reported 2.31%/2.92% H/V congestion,
8,963,992 total DRC violations, 8,004,432 shorts, zero unrouted nets, zero
regular-net connectivity violations, 159,471,808.719 um routed wirelength, and
39,423,315 vias. Relative to the HPWL route, H/V congestion improved by
0.431%/1.684%, total DRC by 6.423%, and shorts by 6.546%, while routed
wirelength worsened by 2.158% and vias by 1.112%. This is a violation-count
improvement with a primary routed-wirelength regression and a secondary via
regression on one case-seed, not a campaign winner; the pair remains ineligible as a robust default because BP_quad seed
3000 already showed a nonzero worst-case DRC regression.

The mempool seed-2000 HPWL route subsequently completed in 16,669 seconds with
2.32%/2.98% H/V congestion, 9,694,160 total DRC violations, 8,669,435 shorts,
zero unrouted nets, zero regular-net connectivity violations,
156,005,914.153 um routed wirelength, and 38,994,387 vias. Its approximately
2.02-GB DRC report ends with the same 9,694,160 total, while both an independent
`rg` count and the streaming parser found exactly 8,669,435 `SHORT:` records;
the parser used about 10.8 MB peak RSS. The supervisor preserved this baseline
and advanced seed 2000 to the pair candidate, bringing the real-design replay
to 18 persisted detailed routes with no failed case-seeds.

The corresponding seed-2000 `net_weighting` + `local_gradient` pair then
passed the strict retained-artifact contract on its 1.916-GB unlimited DRC
report, connectivity report, Innovus log, and metrics file. It reported
2.33%/2.94% H/V congestion, 9,219,948 total DRC violations, 8,228,934
short-class violations, zero unrouted nets, zero regular-net connectivity
violations, 158,908,132.270 um routed wirelength, and 39,460,240 vias. The
short-class value includes both `Short` and `Cut Short` records and exactly
matches the streaming parser. Relative to HPWL, vertical congestion, DRC, and
short-class violations improved by `-1.342%`, `-4.892%`, and `-5.081%`, while
horizontal congestion, routed wirelength, and vias regressed by `+0.431%`,
`+1.860%`, and `+1.195%`. This is a Pareto tradeoff, not a robust winner.

The mempool seed-3000 HPWL route completed next with 2.31%/2.96% H/V
congestion, 9,496,495 total DRC violations, 8,490,003 shorts, zero unrouted
nets, zero regular-net connectivity violations, 156,274,973.928 um routed
wirelength, and 38,942,654 vias. Re-parsing the retained Innovus log,
approximately 1.98-GB unlimited DRC report, connectivity report, and metrics
file reproduced every persisted value. The supervisor then advanced seed 3000
to the pair candidate, bringing the replay to 19 persisted detailed routes
with no failed case-seeds.

The corresponding seed-3000 pair route subsequently passed the same strict
artifact contract. It reported 2.39%/3.01% H/V congestion, 9,404,447 DRC
violations, 8,390,241 shorts, zero unrouted nets, zero regular-net connectivity
violations, 160,695,888.828 um routed wirelength, and 39,800,125 vias. Relative
to HPWL, DRC and shorts improved by `-0.969%` and `-1.175%`, but H/V congestion
regressed by `+3.463%`/`+1.689%`, routed wirelength by `+2.829%`, and vias by
`+2.202%`. The pair is therefore a Pareto tradeoff on this seed and is not
routability-safe.

Across all three Mempool seeds, the pair improves DRC by `-4.095%` on average
and shorts by `-4.268%`, winning every seed on both metrics. Those improvements
come with mean horizontal congestion `+1.154%`, routed wirelength `+2.282%`,
and vias `+1.503%`; routed wirelength and vias lose all three seeds, horizontal
congestion loses two, and vertical congestion has a `-0.446%` mean but a
`+1.689%` worst-seed regression. This complete design-level slice is useful
Pareto evidence but fails primary routability safety because H/V congestion
and routed wirelength have nonzero worst-seed regressions; vias are a
secondary cost.

Atomic `local_gradient` subsequently completed Mempool seed 1000 and passed
the per-method raw-artifact contract. Relative to HPWL, it improved H/V
congestion by `-0.862%`/`-1.347%`, DRC by `-7.035%`, and shorts by `-7.178%`,
with both unrouted nets and regular-net connectivity violations tied at zero.
However, routed wirelength increased from 156,103,162.128 to 160,722,553.959 um
(`+2.959%`) and vias increased from 38,989,687 to 39,473,038 (`+1.240%`). This
is a violation-metric improvement with a primary routed-wirelength regression
and a secondary via-cost tradeoff on this slice. It also cannot be the robust
default because primary metrics regress on OpenROAD
test3 and Innovus NVDLA-L seed 1000.

Mempool seed-2000 `local_gradient` then passed the same strict streaming
artifact reparse. Relative to HPWL, DRC improved from 9,694,160 to 9,543,080
(`-1.558%`), shorts from 8,669,435 to 8,520,647 (`-1.716%`), and vertical
congestion from 2.98% to 2.97% (`-0.336%`). Horizontal congestion increased
from 2.32% to 2.33% (`+0.431%`), routed wirelength increased from
156,005,914.153 to 160,064,446.519 um (`+2.602%`), and vias increased from
38,994,387 to 39,583,802 (`+1.512%`). Unrouted nets and regular-net
connectivity violations remained zero. The nonzero horizontal-congestion
regression violates primary safety despite the DRC and short improvements.

Mempool seed-3000 `local_gradient` subsequently completed and passed both the
resume contract and a fresh streaming reparse of the candidate and same-seed
HPWL artifacts. Horizontal congestion tied at 2.31%, while vertical congestion
improved from 2.96% to 2.95% (`-0.338%`), DRC from 9,496,495 to 8,808,042
(`-7.250%`), and shorts from 8,490,003 to 7,847,290 (`-7.570%`). Unrouted nets
and regular-net connectivity violations remained zero. Routed wirelength
increased from 156,274,973.928 to 160,173,113.634 um (`+2.494%`) and vias from
38,942,654 to 39,464,781 (`+1.341%`). The former is a primary regression; only
the via increase is evaluated under the secondary-cost budget.

Across all three Mempool seeds, `local_gradient` improves mean vertical
congestion by `-0.673%`, DRC by `-5.281%`, and shorts by `-5.488%`; it improves
DRC and shorts on every seed. Mean horizontal congestion also improves slightly
by `-0.144%`, but seed 2000 has a `+0.431%` worst regression, so the complete
design slice remains primary-unsafe. Routed wirelength and vias regress on all
three seeds by `+2.685%` and `+1.364%` on average, with worst regressions of
`+2.959%` and `+1.512%`. These routed costs remain inside the default budgets
but do not erase the directional-congestion veto.

Mempool seed-1000 `net_overlap` then completed and passed a strict streaming
reparse of both its own and the same-seed HPWL artifacts. It is a genuine
all-metric win on this slice: H/V congestion improved from 2.32%/2.97% to
2.25%/2.87% (`-3.017%`/`-3.367%`), DRC from 9,579,257 to 8,645,906
(`-9.743%`), shorts from 8,565,140 to 7,710,387 (`-9.979%`), routed wirelength
from 156,103,162.128 to 155,547,504.248 um (`-0.356%`), and vias from
38,989,687 to 38,807,233 (`-0.468%`). Unrouted nets and regular-net
connectivity violations remained zero. This favorable case-seed remains in the
Pareto evidence, but it cannot override `net_overlap`'s severe BP_quad,
NVDLA-L, and OpenROAD primary regressions.

Mempool seed-2000 `net_overlap` subsequently passed the same strict
candidate/HPWL artifact contract. H/V congestion improved from 2.32%/2.98% to
2.28%/2.91% (`-1.724%`/`-2.349%`), DRC from 9,694,160 to 9,136,319
(`-5.754%`), shorts from 8,669,435 to 8,158,303 (`-5.896%`), and vias from
38,994,387 to 38,957,500 (`-0.095%`). Routed wirelength increased from
156,005,914.153 to 156,682,559.533 um (`+0.434%`), which is a primary
routed-wirelength regression, while unrouted nets and regular-net connectivity
violations remained zero. Both completed Mempool seeds improve every violation
metric, but seed 2000 is not primary-safe and
seed 3000 is still required before forming a design-level conclusion.

Mempool seed-3000 `net_overlap` then completed and passed strict artifact
reparsing, closing the three-seed method slice. It improved H/V congestion by
`-1.299%`/`-2.365%`, DRC by `-4.918%`, shorts by `-5.077%`, and routed
wirelength by `-0.208%`; vias regressed slightly by `+0.119%`, while unrouted
nets and regular-net connectivity violations remained zero. Across all three
Mempool seeds, `net_overlap` improves mean H/V congestion by
`-2.013%`/`-2.694%`, DRC by `-6.805%`, and shorts by `-6.984%`, winning every
seed on every violation metric. Routed wirelength improves by `-0.043%` on
average with a `+0.434%` worst seed, and vias improve by `-0.148%` on average
with a `+0.119%` worst seed. The routed-wirelength tail prevents primary safety;
the method is also not robust
cross-design method: BP_quad, NVDLA-L, and OpenROAD retain severe primary
regressions.

The NVDLA-L seed-1000 HPWL detailed route then completed in 10,762 seconds and
passed the same contract with 1.29%/1.54% H/V congestion, 3,494,657 total DRC
violations, 3,071,302 shorts, zero unrouted nets, zero regular-net connectivity
violations, 139,250,170.069 um routed wirelength, and 30,492,812 vias. Its
approximately 904-MB DRC report contains exactly 3,071,302 `SHORT:` records,
and its final `Total Violations` line exactly matches the parsed DRC count. The
supervisor advanced this case-seed to the pair candidate without an evaluator
or artifact failure.

The corresponding NVDLA-L seed-1000 pair route also completed and passed a
direct strict reparse of its retained log, approximately 1.86-GB DRC report,
connectivity report, and metric file. It reported 1.51%/1.89% H/V congestion,
7,110,851 total DRC violations, 6,313,995 shorts, zero unrouted nets, zero
regular-net connectivity violations, 166,826,028.268 um routed wirelength, and
33,116,931 vias. Relative to HPWL, the pair regressed H/V congestion by
17.054%/22.727%, total DRC by 103.478%, shorts by 105.580%, routed wirelength by
19.803%, and vias by 8.606%. This independently confirms that the pair is not a
robust routability winner; its mempool seed-1000 improvement does not generalize.

Atomic `local_gradient` then completed NVDLA-L seed 1000 and passed streaming
re-parsing of its retained Innovus log, DRC report, connectivity report, and
metrics file. It reported 1.37%/1.68% H/V congestion, 4,958,419 DRC
violations, 4,375,543 shorts, zero unrouted nets, zero regular-net connectivity
violations, 160,455,534.356 um routed wirelength, and 32,109,304 vias. Relative
to HPWL, H/V congestion regressed by `+6.202%`/`+9.091%`, DRC by `+41.886%`,
shorts by `+42.465%`, routed wirelength by `+15.228%`, and vias by `+5.301%`.
This independently disqualifies `local_gradient` as a robust Innovus default
and agrees with its held-out OpenROAD test3 regression.

Atomic `net_overlap` subsequently completed NVDLA-L seed 1000 and passed the
resume contract plus a fresh streaming reparse of its retained Innovus log,
DRC report, connectivity report, and metrics file. It reported 1.34%/1.61%
H/V congestion, 4,082,989 total DRC violations, 3,601,472 shorts, zero
unrouted nets, zero regular-net connectivity violations, 143,235,632.483 um
routed wirelength, and 31,209,243 vias. Relative to the same-seed HPWL route,
H/V congestion regressed by `+3.876%`/`+4.545%`, DRC by `+16.835%`, shorts by
`+17.262%`, routed wirelength by `+2.862%`, and vias by `+2.350%`. This
independently disqualifies `net_overlap` on NVDLA-L and agrees with its severe
three-seed BP_quad regression.

Atomic `net_weighting` completed the final NVDLA-L seed-1000 route and passed a
strict candidate/baseline artifact reparse. It improved every nonzero requested
metric: H/V congestion fell from 1.29%/1.54% to 1.24%/1.50%
(`-3.876%`/`-2.597%`), DRC from 3,494,657 to 3,097,890 (`-11.354%`), shorts
from 3,071,302 to 2,725,058 (`-11.274%`), routed wirelength from
139,250,170.069 to 137,162,304.976 um (`-1.499%`), and vias from 30,492,812 to
30,064,102 (`-1.406%`). Unrouted nets and regular-net connectivity violations
remained zero. This is a genuine all-metric win and completed all five methods
for the case-seed, advancing Innovus to `4/15` completed case-seeds. It remains
candidate-level positive evidence rather than a robust recommendation because
the same method already has a primary H/V regression on BP_quad seed 3000.

The NVDLA-L seed-2000 HPWL baseline then completed and passed a strict retained
artifact reparse with 1.33%/1.58% H/V congestion, 3,821,328 DRC violations,
3,360,453 shorts, zero unrouted nets, zero regular-net connectivity violations,
140,164,845.788 um routed wirelength, and 30,697,751 vias. This advances
Innovus to `33/75` valid routes and establishes the same-seed comparator; no
plugin conclusion is drawn until its paired candidate routes complete.

Because unlimited Innovus DRC reports already reached 1.99 GB on mempool, the
DRC parser now extracts both the total violation count and short count in one
streaming pass instead of loading the entire file into memory. A direct check
on that report reproduced all 8,565,140 shorts with approximately 12 MB peak
process RSS. The evaluator no longer makes Innovus reread the same multi-GB
report in Tcl merely to recover the total count; future routes rely on the
single artifact-derived Python pass. The text parser remains available for unit
tests and compatibility, and the final campaign summarizer uses the same
streaming file parser.

A combination-coverage audit confirmed that the routability-first development
campaign tested all three pairs of `local_gradient`, `net_overlap`, and
`net_weighting` at activation thresholds 0.6, 0.8, and 1.0. Only
`net_weighting` + `local_gradient` at 0.6 survived that proxy screen. The
previous campaign did not cover the three-plugin combination, so a bounded
triple screen was launched in remote tmux session `ruplace_triple_3583ba6` at
`results/routability_remote/ispd2019_routability_first_triples_3583ba6` on
`ceca2080x4`. It waited for five continuous GPU-idle minutes before running
test1/test2 development and test3 held-out screens at the same three activation
thresholds. The local finalizer was configured to refuse a final five-method
recommendation if a triple survived both screens; such a survivor would first
have needed to be added to the common golden-router campaigns.

The remote triple launch passed its five-minute idle gate at 22:50 SGT, but a
recurring shared four-GPU job reclaimed the devices during detailed placement.
All six development case-seeds reached detailed placement and then failed
`curandCreateGenerator` in independent-set matching; these are infrastructure
failures, not QoR results. The identical frozen triple specification was rerun
sequentially on the local TITAN RTX and completed all nine development and
held-out case-seeds without execution failures. The development selector
rejected all three activation thresholds because each improved fewer than two
of five GPUGR primary metrics; the 0.8-threshold variant also improved fewer
than one of two RUDY primary metrics. Held-out test3 selected only the
0.8-threshold variant, so the frozen development/held-out intersection is
empty. No triple is eligible for golden replay. The compact summaries and
status files were synced to the remote path watched by the finalizer.

Tmux session `ruplace_finalize_3583ba6` runs the persistent completion watcher
`results/routability_remote/finalize_golden_3583ba6.sh`. It waits until both
status files contain only completed jobs, then produces backend-local summaries
and invokes the Pareto ranker. Before summarization it deterministically
backfills any OpenROAD directional-congestion artifact that was not retained
through detailed routing. It cannot commit code or alter the final
recommendation. Its log is
`results/routability_remote/golden_finalizer_3583ba6.log`.

At the 2026-07-28 08:52 SGT checkpoint, OpenROAD remained at `3/9`
case-seeds and `23/45` retained method routes, while Innovus remained at `3/15`
case-seeds and `22/75` retained method routes. Each backend had four active
workers and zero failed case-seeds. OpenROAD test2 seed 3000's pair route was
still CPU-active at 5 hours 28 minutes against its six-hour per-route timeout;
the supervisor and other workers were left undisturbed. An interim ranker
revision treated routed wirelength as a hard routability-safety constraint and
vias as a final tie-breaker. A later intermediate audit temporarily demoted
routed wirelength, but the current policy restored it as an independent primary
metric; only vias are secondary. The full `139/139` local regression set passed
at this historical checkpoint.

At the 2026-07-28 10:20 SGT checkpoint, OpenROAD had advanced to `25/45`
retained method routes and Innovus to `24/75`; both still had three fully
completed case-seeds, four active workers, and zero failed case-seeds. A
low-priority summary replay accepted every fully completed comparison with
zero artifact exclusions. A separate per-method resume-contract audit then
strictly reparsed all retained raw artifacts and accepted `25/25` OpenROAD and
`24/24` Innovus routes, including methods from incomplete case-seeds. The
active workers continued to produce routed artifacts, including an Innovus
NVDLA-L route completed at 09:49 SGT, so the unchanged case-seed totals are not
evidence of a scheduler stall. The remote triple summaries are also complete:
the development survivor set is empty, while held-out test3 selects one triple,
leaving an empty frozen intersection and therefore no triple-plugin golden
extension.

At the 2026-07-28 11:05 SGT checkpoint, the newly retained Mempool seed-1000
`local_gradient` route brought Innovus to `25/75` retained routes. A fresh
streaming reparse of every retained artifact accepted `25/25` OpenROAD and
`25/25` Innovus routes with zero invalid results. Campaign scheduling remained
at three completed case-seeds per backend, four active workers per backend,
zero failed case-seeds, and 2/8 pending OpenROAD/Innovus case-seeds. All four
OpenROAD workers were CPU-active; the oldest active method still had about two
hours before its 21,600-second limit. All four Innovus workers were still in
routed jobs. No restart or timeout extension was warranted.

At the 2026-07-28 11:16 SGT checkpoint, an intermediate objective audit changed
the final ranker so routed wirelength was no longer embedded in the primary routability
vector. The primary vector now contains H/V congestion or overflow, DRC,
unrouted nets, shorts, and backend-specific connectivity violations. Routed
wirelength and vias remain mandatory evidence but are secondary costs. A robust
candidate must be primary-safe and primary-Pareto on every golden backend,
show supported primary improvement on at least one backend, survive consensus
full-Pareto dominance by the other robust candidates, and stay within explicit
`+5%` mean and `+10%` worst-case budgets for each secondary cost. No metrics or router
backends are scalarized. Regression tests cover bounded cost tradeoffs, primary
regression vetoes, backend-local cost disagreement, zero-baseline routed costs,
and the fact that wirelength-only improvements are not routability wins. The
machine-readable and Markdown rankings also expose each alternative's minimum
required secondary-cost budget; the full local suite passed `145/145`. This
intermediate policy is superseded by the later routed-wirelength-primary update.

At the 2026-07-28 11:29 SGT checkpoint, both campaigns still retained `25`
method routes with four active workers and zero failed case-seeds. Every active
OpenROAD worker had completed global routing and retained its guide,
directional-congestion evidence, and global-route wirelength before entering
detailed routing. The oldest worker remained CPU-active after about 4.5 hours
with roughly 90 minutes before its six-hour limit. The four Innovus route
containers had been active for approximately 51 minutes to three hours. No
worker had reached its timeout or lost its supervisor, so preserving the active
runs remained preferable to a speculative restart.

At the 2026-07-28 11:35 SGT checkpoint, the completed test2 seed-3000
`local_gradient` route advanced OpenROAD to `26/45` retained routes. Innovus
remained at `25/75`; each backend still had three complete case-seeds, four
active workers, and zero failed case-seeds. The OpenROAD worker immediately
advanced to `net_overlap`, so the unchanged complete-case count reflects
sequential progress within active case-seeds rather than a stall.

A follow-up audit of that intermediate policy found no hidden wirelength-only path
to recommendation: the ranker requires backend-local mean and worst-case
nonregression for H/V congestion, DRC, unrouted nets, shorts, and available
connectivity violations before applying routed wirelength and via budgets.
The focused ranker, summarizer, and congestion-backfill suites passed `36/36`.
All 26 retained OpenROAD rows have directional-congestion evidence: 24 use
deterministic global-route identity-checked backfills, one uses the installed
immediate FastRoute snapshot, and the remaining pre-snapshot pair route retains
a nonempty 624,721-byte native congestion report. Every active OpenROAD script
uses the immediate-snapshot implementation, so no future clean-route empty
report is ambiguous with a deleted legacy artifact.

The timeout/resume audit also hardened the common native-evaluator runner.
Router commands now run in isolated process groups, and a timeout terminates
the wrapper plus all descendants before returning a resumable timeout result.
This prevents a timed-out OpenROAD child or Innovus container from continuing
unaccounted in the background. A regression probe spawns a descendant and
verifies that it is terminated. The complete suite then passed `146/146`, and
Python compilation plus `git diff --check` passed. The existing CMake install
step made the source and installed runner byte-identical, and the evaluator
suite independently passed `28/28` through the installed package. This change
applies only to future evaluator launches; it did not signal or restart any
active golden run.

The idle `ceca2080x4` GPUs cannot safely accelerate the frozen golden OpenROAD
queue. That host has no OpenROAD executable installed, while the local replay
uses `/usr/bin/openroad` version `26Q1-951-g6975124cf2`; substituting or
installing a different build mid-campaign would break the common-router
contract. The remote remains suitable for GPU placement and proxy screening,
including the completed triple screen, while the golden OpenROAD routes stay
on the validated local binary.

The final Pareto ranker was also exercised end to end on temporary
three-comparison fixtures derived from the strict-valid OpenROAD test1 and
Innovus BP_quad slices. This integration check required OpenROAD H/V overflow
and Innovus H/V congestion separately, preserved all five common methods, and
recommended HPWL with no robust routability or all-metric winner. The pair
remained visible as a consensus Pareto alternative but was not promoted because
it was unsafe on primary metrics. The fixture override was used only to test
the final summary schema before campaign completion; it is not final QoR
evidence and no partial ranking is used for the ultimate recommendation.
The corrected primary/secondary ranker was rerun on the same real-schema slice
and again recommended HPWL: one completed design cannot provide the required
design-level statistical support, even when all three seeds improve. This
confirms that the new tradeoff policy does not promote partial evidence.
Its secondary-cost sensitivity output required mean/worst budgets of
`0.856%/1.102%` for the pair, `1.052%/1.241%` for `local_gradient`,
`11.681%/12.066%` for `net_overlap`, and `0.249%/0.555%` for `net_weighting`.
Only `net_overlap` exceeded the default `5%/10%` cost bounds on this partial
slice. These are schema and policy checks, not final campaign conclusions.

At the 2026-07-28 12:52 SGT checkpoint, the NVDLA-L seed-1000 `net_overlap`
route advanced Innovus to `26/75` retained method routes. OpenROAD remained at
`26/45`; both campaigns still had three complete case-seeds, four active
workers, and zero failed case-seeds. The remote triple screen was also
rechecked: development selected no triple, held-out test3 selected one, and
their frozen intersection remained empty, so no triple requires golden replay.
The focused ranker, summarizer, and OpenROAD congestion-backfill suites passed
`36/36` during this checkpoint.

At 12:58 SGT, OpenROAD test2 seed-2000 `local_gradient` reached its 21,600-second
limit while 60% through the second detailed-route optimization iteration. Its
summary correctly records `status=timeout` with no authoritative metrics, so it
does not increase the `26/45` reusable-route count. The process-group timeout
cleanup removed the router child before the case worker advanced to
`net_overlap`; no orphan OpenROAD process remained. Tmux session
`ruplace_recovery_3583ba6` now runs
`results/routability_remote/recover_openroad_golden_3583ba6.sh`. It waits for
the OpenROAD supervisor and descendants, backfills retained H/V congestion,
and starts the longer OpenROAD resume immediately, allowing its recovery to
overlap the remaining Innovus campaign. It then waits for Innovus and invokes
the same five-method Innovus campaign with `--resume`. Both recovery passes use
a justified 28,800-second limit; a remaining timeout gets one
contract-preserving 36,000-second retry. The resume contract preserves every
valid sibling and reruns only invalid or missing methods. Finalization still
starts only after both exact campaigns finish, preventing concurrent status
writers or partial ranking.
An explicit partial-resume regression test seeds one valid sibling and one
timeout summary, then verifies that replay invokes the evaluator only for the
timed-out method. With that test added, the complete current suite passes
`161/161`: 136 routability tests, 14 legacy RUPlace unit tests, and 11
quality/source tests.

At 17:35 SGT, OpenROAD test2 seed-3000 `net_overlap` also reached the
21,600-second limit. Its summary records `status=timeout`, an empty metric map,
and only non-authoritative partial artifacts, so the valid-route count remains
unchanged. Process-group cleanup removed the old router descendant, and the
same case worker immediately advanced to `net_weighting`. The isolated recovery
watcher therefore has two invalid methods to rerun at 28,800 seconds:
test2 seed-2000 `local_gradient` and test2 seed-3000 `net_overlap`. Its
contract-aware resume will preserve every valid sibling and cannot promote
either timeout as QoR evidence.

At the 2026-07-28 20:18 SGT checkpoint, the remote triple prerequisite was
audited beyond its survivor filenames. Development completed all six
case-seeds, held-out completed all three, and their selected-set intersection
remains empty. All 18 retained development triple placement logs report exact
configured plugin sets with positive activation: minimum activation counts are
3 for `net_weighting` and 120 each for `net_overlap` and `local_gradient`.
Development selected no triple, so the missing heavy held-out placement tree
cannot hide a candidate eligible in both splits. No triple extension of the
golden matrix is required.

At the 2026-07-28 13:18 SGT checkpoint, OpenROAD had advanced to `27/45`
valid routes and Innovus to `27/75`. The newly retained OpenROAD test2
seed-1000 `net_overlap` route and Innovus Mempool seed-2000 `local_gradient`
route both passed strict same-seed HPWL artifact comparisons and both regressed
at least one primary routability metric. Each original supervisor still had
four active workers and no completed case-seed failure; the recovery watcher
remained isolated and waiting.

The summarizer and golden ranker were then extended to make the final
per-design and worst-case audit explicit. Every metric summary now retains each
design's mean paired delta, the worst design, and the exact worst case-seed;
zero-baseline violation metrics retain absolute rather than undefined percent
deltas. Both backend summary reports and the final ranking report render this
evidence alongside the existing design-level confidence intervals. The
machine-readable outputs include nested `case_results` in
`screening_summary.json`, JSON-encoded nested cells in `screening_summary.csv`,
and a flat `screening_per_design.csv` for direct external analysis. A
live-schema integration on the strict-valid test1 and BP_quad slices confirmed
that the final report names both designs and their worst seeds while preserving
the HPWL recommendation. The focused summarizer and ranker suites pass `29/29`,
Python compilation passes, and `git diff --check` remains clean.

A subsequent router-configuration audit covered all 25 retained OpenROAD and
23 retained Innovus method routes available at 09:30 SGT and found zero
configuration errors. Every OpenROAD script performs global routing with a
retained congestion report followed by detailed routing and reports both
global- and detailed-route wirelength; test2 alone uses the documented
`droute_end_iter=2` cap while test1/test3 use 20. Every Innovus script disables
timing/SI-driven routing, uses `drouteEndIteration 20`, runs
`globalDetailRoute`, reports congestion, DRC, regular-net connectivity, and
routed wirelength, and has a manufacturing-grid snap report with at most one
DBU coordinate movement. This rules out method-specific router settings as an
explanation for the observed QoR deltas.

### Current golden-candidate veto ledger

Every non-HPWL finalist already has at least one strict artifact-backed
regression in a primary routability metric:

| Candidate | Golden veto evidence |
|---|---|
| `net_weighting` + `local_gradient` | OpenROAD test2 seed 3000: H/V overflow 514/1,772 versus 0/0, DRC `+196.947%`, routed wirelength `+41.202%`; Innovus NVDLA-L seed 1000 also regresses every nonzero metric |
| `local_gradient` | OpenROAD test2 seed 3000: DRC `+17.168%`, shorts `+22.618%`, routed wirelength `+8.324%`; OpenROAD test3 seed 1000: DRC `+12.732%`; Innovus NVDLA-L seed 1000: H/V `+6.202%`/`+9.091%`, DRC `+41.886%`, routed wirelength `+15.228%` |
| `net_overlap` | Innovus BP_quad three-seed means: H/V `+137.576%`/`+106.250%`, DRC `+12.191%`, routed wirelength `+11.681%` |
| `net_weighting` | Innovus BP_quad seed 3000: H/V `+10.000%`/`+6.250%`; three-seed routed wirelength mean `+0.149%` |

These primary-metric vetoes are monotone under the robust default rule: later
improvements cannot remove an already observed worst-case regression. The
routed-wirelength values are also primary veto evidence under the current rule.
All remaining routes still run to completion because the final report requires
complete backend-local Pareto frontiers, per-design results, and confidence
intervals; the ledger is not a substitute for the final campaign audit.

At the five-complete-case-seed Innovus checkpoint (BP_quad seeds 1000/2000/3000,
Mempool seed 1000, and NVDLA-L seed 1000), a direct same-backend recomputation
found primary regressions for every alternative. The pair regressed primary
metrics on 2/5 case-seeds and lost routed wirelength on all five (mean
`+4.906%`, worst `+19.803%`). `local_gradient` regressed primary metrics on
NVDLA-L and also lost wirelength on all five (mean `+4.269%`, worst `+15.228%`).
`net_overlap` regressed primary metrics on 4/5 and increased both routed costs
on average (`+7.510%` wirelength, `+6.890%` vias). `net_weighting` had the only
negative mean deltas (`-0.152%` wirelength, `-0.212%` vias), but lost
wirelength on 4/5 and regressed primary metrics on BP_quad seed 3000 and
Mempool seed 1000. These partial values are a consistency/veto audit only; the
final decision still requires all 15 Innovus case-seeds and all nine OpenROAD
case-seeds.

### Routability-first completion gate audit

The following audit is the acceptance checklist for the active objective, not
a reinterpretation of the older Poisson campaign. Status is current at the
2026-07-29 05:01 SGT checkpoint.

| Requirement | Authoritative evidence | Status |
|---|---|---|
| Literature and mechanism coverage | `docs/routability_optimization_lab.md`; ten independent plugins with explicit reproduction-fidelity limits; live 2022-2026 DOI/source refresh | Complete for the implementable atomic GP mechanism families; learned selectors, explicit group constraints, and post-GP detailed-placement policies remain documented gaps rather than claimed reproductions |
| Independent plugin operations and combinations | `dreamplace/ops/routability_opt/plugins`; frozen atomic, pair, and triple screens | Complete; all three finalist pairs and the one three-plugin family were covered, and the development/held-out triple intersection is empty |
| Comparable golden metrics | OpenROAD and Innovus evaluator adapters, retained route scripts/reports, and artifact-reparsing tests | Complete in code: H/V congestion or overflow, DRC, shorts, unrouted/connectivity violations, routed wirelength, and vias are mandatory; backends are never numerically mixed |
| Routability-first selection | `tools/routability_rank_golden.py` and its regression tests | Complete in code: H/V congestion or overflow, DRC/connectivity, unrouted nets, shorts, and routed WL form the primary backend-local Pareto vector; only vias use explicit secondary-cost budgets; complete placement-HPWL coverage is required and reported separately, but cannot affect Pareto, safety, evidence, or winner decisions |
| Contest multi-seed golden evidence | ISPD2019 test1/test2/test3, three seeds, five methods, common OpenROAD detailed routing | In progress: 37/45 strict-valid routes and 5/9 complete case-seeds; two invalid timeout rows are isolated for exact-container recovery on `ceca2080x4` |
| Real-design multi-seed golden evidence | BP_quad, Mempool, NVDLA-L, OpenC910, and XScore, three seeds, five methods, common Innovus detailed routing | In progress: 48/75 strict-valid routes and 7/15 complete case-seeds, with no invalid result; four case-seeds are running and four are queued |
| Robust best-method or no-winner decision | Complete backend-local summaries plus `golden_routability_ranking_3583ba6.json` and `.md` | Pending; every current alternative already has a primary-metric veto, but final recommendation requires zero missing/excluded/mismatched comparisons and complete per-design confidence evidence |
| Final decision report | `docs/routability_validation_final.md` | Pending replacement; the existing report is now explicitly marked as the superseded `bb24016` historical campaign |
| Regression and source integrity | Full unit suite, Python compilation, `git diff --check`, installed/source evaluator, plugin, and parameter-schema identity | Current checks pass 211/211 with compilation and diff checks clean; the finalizer reruns these gates after ranking |

At the 2026-07-29 00:00 SGT checkpoint, the final audit was tightened from an
exact-count check to an exact production-matrix check. It now requires the
cartesian product of the three ISPD2019 cases or five real designs, seeds 1000,
2000, and 3000, and the frozen five-method finalist set directly in the routed
artifact paths. Duplicate, substituted, misplaced, or incorrectly named route
slots cannot satisfy the `45/45` OpenROAD or `75/75` Innovus gate even when the
raw file count matches. The finalizer enables this production-only contract.

At the 2026-07-28 19:20 SGT checkpoint, the replay provenance audit was
tightened so a method label cannot enter golden routing or ranking unless the
frozen placement proves that every configured plugin actually activated.
Candidates must have top-level status `active`, exact equality among the
configured, selected, and summarized plugin sets, and positive per-plugin
activation counts. The baseline must have `not_selected` and an empty plugin
summary; `partially_active` is invalid for golden evidence. The same contract
is applied during staging, resume, and summary loading, and the ranker requires
the summary's validated contract marker. All 120 placement records in the 24
current contest and real-design source comparisons pass this contract. Focused
replay, summarization, and ranking tests pass 13/13, 18/18, and 25/25.

At the 2026-07-28 19:26 SGT checkpoint, strict resume exposed a recovery-order
hazard: an interrupted congestion backfill had left valid zero-overflow reports
on disk without committing their paths into several OpenROAD result JSON files.
The recovery watcher would therefore have repeated already successful detailed
routes before the finalizer reached its backfill step. The backfill tool now has
an incomplete-campaign mode that skips failed/timeout rows, updates successful
siblings with deterministic global-route identity checks, and runs before the
longer OpenROAD resume. The watcher was restarted as PID 2651283 without
touching either active router supervisor. A new regression covers the skipped
timeout-row behavior; the full suite passes 158/158.

At the 2026-07-28 20:07 SGT checkpoint, the detailed Innovus evaluator was
changed to retain a compact DRC artifact by default instead of multi-gigabyte
per-violation reports. It runs PG-excluded `verify_drc -limit 0`, parses the
verifier's stdout total plus `Short` and `CShort` columns, and writes only those
totals to `innovus_drc.rpt`; it does not use `dbGet top.markers`. A frozen
BP_quad seed-1000 HPWL probe reproduced the original golden route exactly:
25,880,086.7106 routed wirelength, 8,212,255 vias, 0.11/0.16 H/V congestion,
14,259 DRC violations, and 11,005 shorts. The rejected marker count was 30,398.
The equality record is retained as `compact_validation.json` under
`results/routability_remote/innovus_compact_drc_probe_3583ba6/` and its
`bp_quad_seed1000_hpwl_snapped` subdirectory; its compact totals also reparse to
14,259/11,005 through the normal artifact parser. Focused
evaluator tests pass 31/31 and the complete suite passes 161/161. The compact
parser also accepts Innovus's table-free clean-route form: the retained GCD log
reparses as exactly zero DRC and zero shorts, while a nonzero total without a
typed violation table remains incomplete and fails closed.

At the 2026-07-28 20:33 SGT checkpoint, the current worktree was reinstalled
and the source and installed Innovus evaluators were byte-identical. A fresh
Innovus 22 end-to-end GCD smoke at
`results/routability_lab/innovus_gcd_compact_e2e_3583ba6` reported 0.00/0.08
H/V congestion, zero DRC, shorts, unrouted nets, and connectivity violations,
3,924.675 routed wirelength, and 2,806 vias. Production artifact parsers
reproduced every serialized value exactly. The generated detailed-route TCL
contains neither `reportWire -summary` nor `dbGet top.markers`, and its compact
DRC report is 62 bytes. The live golden campaigns retained 33/45 OpenROAD and
34/75 Innovus routes. All four active Innovus children were launched before
the reinstall and therefore legitimately retain the older verbose scripts;
the first subsequently launched method remains the campaign-level compact-code
pickup gate. The complete source suite passed 161/161 after this smoke.

At the 2026-07-28 20:46 SGT checkpoint, strict interim summarization exposed a
finalization performance problem in the 34 legacy Innovus artifacts: their DRC
reports total 29.760 GiB, and the original streaming parser remained busy after
roughly six minutes. Every retained Innovus log already contains the complete
typed `verify_drc` total and `Short + CShort` matrix. The artifact parser now
reads the bounded report tail to independently confirm total DRC and uses the
typed log short total; reports lacking typed log evidence retain the original
full-record scan. The summarizer also rejects any log/report total mismatch.
All 34 current routes agree exactly across persisted JSON, log, and report.
The same strict five-case-seed interim summary now completes in 2.02 seconds,
with zero exclusions or baseline gaps; it exits nonzero only because the
Innovus matrix remains intentionally incomplete at 5/15 comparisons. Two new
regressions bring the complete suite to 163/163.

At the 2026-07-28 20:54 SGT checkpoint, finalization gained a separate
machine-readable completion audit. After strict summaries and Pareto ranking,
the inactive finalizer now requires exactly 45/45 successful OpenROAD results
and 75/75 successful Innovus results, at least one post-install compact Innovus
DRC artifact, matching source/install evaluator modules, successful Python
compilation, the complete regression suite, and a clean `git diff --check`.
Only then can `tools/routability_audit_final.py` emit
`golden_finalization_audit_3583ba6.json`, which records the recommendation and
SHA-256 hashes of both summaries, ranking JSON/report, and regression log. Its
success, missing-compact-artifact, and empty-recommendation fixtures pass; a
live partial-matrix probe fails before producing an audit file. The finalizer's
remote triple-screen dependency was also rechecked: development selects none,
held-out selects one, and their intersection is empty. The complete suite now
passes 166/166.

At the 2026-07-28 20:59 SGT checkpoint, the final audit was tightened from
hash binding to semantic ranking validation. It independently requires
complete backend-local summaries, exact canonical summary hashes in the
OpenROAD and Innovus campaign records, disabled numeric backend mixing and
metric scalarization, the full primary metric set including routed wirelength,
vias as the secondary metric with the frozen +5% mean/+10% worst guardrails, and exact
agreement between `recommended_methods` and the bounded winner set or HPWL
fallback. Tampered-summary and backend-mixing fixtures fail closed. A
timing-sensitive bounded-parallelism test discovered during the full run now
uses a two-worker barrier rather than a scheduler-dependent sleep; it passed
five focused repetitions. The complete suite passes 168/168.

At the 2026-07-28 21:09 SGT checkpoint, the final audit gained an independent
per-route metric and artifact contract. It no longer counts a result merely
because its JSON says `status: ok`: every OpenROAD and Innovus result must pass
the same strict resume check used by golden replay, including retained-artifact
reparsing and finite nonnegative H/V congestion, DRC, unrouted/shorted-net,
routed-wirelength, and via evidence. A status-OK result with routed wirelength
removed now fails closed. The live partial-matrix probe was intentionally asked
to accept all 35 existing OpenROAD JSON files and correctly rejected them as
`paths=35 valid=33 invalid=2`; both invalid rows are known six-hour timeouts.
All 33 valid OpenROAD and all 34 Innovus results independently pass the strict
contract. The standalone audit CLI, Python compilation, `git diff --check`,
and the expanded suites pass. A follow-up removed the final manifest's reliance
on an external shell assertion for evaluator installation: the audit now
independently compares and SHA-binds source and installed `base.py`,
`innovus.py`, and `openroad.py`; a deliberately changed installed module fails
closed. The current total is 144 routability, one DEF-distribution, 14 RUPlace
unit, and 11 quality/source tests, for `170/170`.

At the 2026-07-28 21:21 SGT checkpoint, the requested routed-QoR policy was
tightened again: routed wirelength now belongs to the primary backend-local
routability vector with H/V congestion, DRC, unrouted nets, shorts, and
available connectivity violations. A mean or worst-case routed-wirelength
regression therefore vetoes robust-default selection. Vias alone retain the
explicit `+5%` mean and `+10%` worst secondary-cost budget. A
routed-wirelength-only improvement is still insufficient for promotion; a
candidate must show supported improvement in congestion, DRC, unrouted nets,
shorts, or connectivity. Focused and complete regression gates pass `170/170`
under this policy, with compilation, evaluator source/install identity, and
`git diff --check` clean. The live campaigns contain `34/45` strict-valid
OpenROAD routes and `34/75` strict-valid Innovus routes. The two invalid
OpenROAD rows are the known six-hour timeouts; both supervisors and the
OpenROAD recovery watcher remain alive. No compact Innovus DRC report exists
yet because all four current child jobs predate the compact-report evaluator;
the exact final audit requires at least one compact artifact from a later job.

At 21:23 SGT, Innovus advanced to `35/75` strict-valid routes and immediately
launched NVDLA-L seed-2000 `local_gradient` from the updated installation. Its
retained production Tcl uses unlimited `verify_drc` without the multi-gigabyte
`-report` option, confirming that this child is on the compact path. The route
must still finish successfully and retain a two-line total/short DRC artifact
before it satisfies the final audit's compact-evidence requirement. OpenROAD
remained at `34/45` strict-valid plus the two recoverable timeout rows. Disk
headroom was 221 GB, and all active OpenROAD and Innovus router children were
CPU-active.

At 22:19 SGT, Mempool seed-2000 `net_weighting` completed the sixth Innovus
case-seed job and advanced the matrix to `36/75` strict-valid routes with zero
invalid rows. Against the same-seed HPWL route it regressed H/V congestion by
`+2.586%`/`+1.678%`, total DRC by `+3.910%`, shorts by `+3.969%`, routed
wirelength by `+0.470%`, and vias by `+0.429%`; unrouted nets and regular-net
connectivity violations remained zero. These artifact-reparsed primary
regressions independently veto `net_weighting` on this slice. The freed worker
immediately launched OpenC910 seed-1000 HPWL, whose retained production Tcl
uses compact unlimited `verify_drc` without the legacy multi-gigabyte report
option. The compact-artifact audit remains pending until one such route
finishes.

At 22:29 SGT, the NVDLA-L seed-3000 HPWL baseline advanced Innovus to `37/75`
strict-valid routes. It reports 1.34%/1.60% H/V congestion, 4,010,042 total DRC
violations, 3,526,903 shorts, zero unrouted nets, zero regular-net connectivity
violations, 139,865,297.578 um routed wirelength, and 30,726,515 vias. Direct
artifact reparsing reproduced the complete vector. The supervisor immediately
advanced the same case-seed to the `net_weighting` + `local_gradient` pair;
that retained Tcl uses the compact unlimited-DRC path. The case-seed comparison
remains incomplete until all four plugin routes close.

At 22:33 SGT, Mempool seed-3000 `net_weighting` closed the seventh Innovus
case-seed job and advanced the matrix to `38/75` strict-valid routes with zero
invalid rows. It improved routed wirelength by `-0.368%`, but regressed H/V
congestion by `+1.299%`/`+0.676%`, total DRC by `+2.072%`, shorts by
`+2.131%`, and vias by `+0.045%`; unrouted nets and regular-net connectivity
violations remained zero. This is artifact-backed evidence that a small routed
wirelength improvement cannot override primary congestion and DRC regressions.
The freed worker launched compact-enabled OpenC910 seed-2000. All four active
Innovus workers now use the compact evaluator path, although no compact route
has finished yet.

At 00:33 SGT on 2026-07-29, OpenC910 seed-1000 HPWL became the first completed
production route using the installed compact evaluator and advanced Innovus to
`39/75` strict-valid routes with zero invalid rows. The retained
`innovus_drc.rpt` is exactly two lines (74 bytes) and records 4,083,470 total
violations and 3,770,245 short violations. Direct contract reparsing also
reproduced 3.08%/3.96% H/V congestion, zero unrouted nets, zero regular-net
connectivity violations, 33,298,778.7173 um routed wirelength, and 11,791,286
vias. The retained Tcl invokes `globalDetailRoute`, and the result passes the
detailed-route resume contract. The compact-evidence gate is therefore closed;
the remaining finalization blockers are exact OpenROAD `45/45` and Innovus
`75/75` matrix completion. OpenROAD remains at `35/45` strict-valid routes plus
the two isolated six-hour timeout rows queued for longer recovery.

At 01:48 SGT, Innovus had advanced to `42/75` strict-valid routes, including
four compact DRC artifacts, with zero invalid rows. An artifact-strict interim
summary was retained separately under
`golden_innovus_detailed_3583ba6_interim_42`; it intentionally returns nonzero
because only 7/15 case-seed comparisons are complete, with zero artifact
exclusions and zero HPWL-baseline gaps. That completed slice already vetoes all
four alternatives under the primary no-regression policy. The closest method,
`net_weighting`, has worst observed regressions of +0.470% routed wirelength,
+10.0%/+6.25% H/V congestion, +3.910% DRC, and +3.969% shorts. This is an
early irrevocable veto, not a substitute for the complete matrix, final
confidence evidence, or backend-local Pareto ranking.

At 01:52 SGT, OpenROAD test3 seed-2000 pair completed after approximately
4.5 hours and advanced the backend to `36/45` strict-valid routes, with the two
known test2 timeout artifacts still isolated for recovery. It tied the HPWL
baseline at zero H/V overflow and zero unrouted nets, improved DRC by 4.280%,
shorts by 3.662%, and vias by 0.250%, but regressed routed wirelength by 0.284%
(83,362 versus 83,126). Because routed wirelength is part of the primary
backend-local safety vector, this otherwise favorable row cannot promote the
pair. Strict retained-artifact reparsing accepted its detailed-route metrics,
guide, congestion snapshot, DRC report, route log, script, and wirelength
report. The supervisor immediately advanced test3 seed-2000 to
`local_gradient`.

At 02:55 SGT, OpenC910 seed-1000 pair advanced Innovus to `43/75`
strict-valid routes, including five compact DRC artifacts, with zero invalid
rows. Against the same-seed HPWL route it regressed every nonzero primary
metric: routed wirelength by 4.274%, H/V congestion by 2.922%/5.303%, total DRC
by 9.013%, and shorts by 8.978%; unrouted nets and regular-net connectivity
violations tied at zero. Vias also regressed by 1.969%. Strict retained-artifact
reparsing accepted the complete vector. This route independently reinforces the
pair veto on a large real design rather than relying on the earlier worst-case
ledger alone.

At 22:54 SGT, the completed remote three-plugin development and held-out
survivor summaries were synchronized locally. Development selects no triple,
held-out test3 selects one, and their frozen intersection is empty. The final
machine-readable audit now requires both summaries, rejects any nonempty
intersection as requiring golden replay, and SHA-binds both files. It also
requires and hashes the exact `6/6` development and `3/3` held-out status
matrices with every job completed at return code zero. Both summaries must
partition the same complete three-preset family into qualified and excluded
rows, and `selected_methods` must exactly equal the qualified set. This makes
the bounded combination conclusion an audited prerequisite rather than only a
shell-side finalizer check.

The added audit rejection fixtures cover both a surviving triple and an
incomplete triple status matrix, plus mismatched method coverage between
development and held-out splits. The complete current gate passes 148
routability tests, one DEF-distribution test, 14 RUPlace unit tests, and 11
quality/source tests, for `174/174`; compilation, finalizer shell syntax, and
`git diff --check` also pass.

An artifact-strict interim summary over the seven completed Innovus case-seeds
still cannot select a final method, but every candidate already violates at
least one robust-default primary gate. `net_weighting` is closest: mean H/V
congestion regresses `+1.615%`/`+0.906%`, while its worst case regresses H/V by
`+10.000%`/`+6.250%`, DRC by `+3.910%`, shorts by `+3.969%`, and routed
wirelength by `+0.470%`. `local_gradient`, `net_overlap`, and the
`net_weighting` + `local_gradient` pair have larger DRC, congestion, or routed
wirelength worst-case regressions. This is preliminary evidence only; the
exact five-design, three-seed Innovus matrix and complete OpenROAD matrix remain
mandatory for the final backend-local Pareto decision.

A live targeted congestion backfill then exposed an incomplete-campaign edge
case: successful method siblings can exist under a still-running case-seed
before its aggregate `comparison.json` has been written. `--skip-non-ok` now
allows that missing aggregate only in incomplete-campaign mode; it still
updates the method-level retained artifacts, while normal final backfill keeps
the strict missing-comparison error. A regression reproduces the live layout.
The repaired backfill reused 34 valid routes, skipped exactly the two timeout
rows, and raised artifact-strict OpenROAD comparison coverage from `3/9` to
`5/9` with no artifact exclusions among the completed case-seeds.

The resulting five-case-seed OpenROAD summary is still not rankable. All
methods tie at zero H/V overflow and zero unrouted nets. The pair and
`local_gradient` have favorable aggregate DRC means of `-15.218%` and
`-14.922%`, respectively, but their worst cases regress DRC by `+13.095%` and
`+12.732%`, shorts by `+15.647%` and `+12.487%`, and routed wirelength by
`+0.679%` and `+0.324%`. `net_overlap` regresses mean DRC by `+190.094%` and
worst routed wirelength by `+58.997%`; `net_weighting` regresses mean DRC by
`+9.369%` and mean routed wirelength by `+0.484%`. Every candidate therefore
already has a primary worst-case veto on the completed contest slice, but all
nine case-seeds remain mandatory for the final backend-wide decision.

These are monotonic eliminations under the frozen no-primary-regression gate:
adding case-seeds cannot reduce an already observed positive worst-case delta.
The pair's current largest OpenROAD/Innovus vetoes are `+15.647%` shorts on
test3 seed-1000 and `+105.580%` shorts on NVDLA-L seed-1000. For
`local_gradient` they are `+12.732%` OpenROAD DRC and `+42.465%` Innovus
shorts; for `net_overlap`, `+350.142%` OpenROAD shorts and `+140.000%` Innovus
horizontal congestion; for `net_weighting`, `+20.299%` OpenROAD DRC and
`+10.000%` Innovus horizontal congestion. Therefore none can become the robust
default if the validated routes remain authoritative. The complete matrices
are still required to quantify all tradeoffs, produce confidence evidence,
and satisfy the final audit; this early proof does not replace them.

At the 2026-07-28 18:52 SGT checkpoint, a final-output schema audit found that
the summarizer retained overall absolute candidate and HPWL values but exposed
only deltas in its per-design and worst-seed evidence. The summary schema now
retains per-design mean candidate and baseline values plus worst-pair candidate
and baseline values. The backend-local Markdown summaries,
`screening_per_design.csv`, the machine-readable golden ranking, and the final
Markdown ranking propagate those absolute values for
every required H/V, DRC, connectivity, routed-wirelength, and via metric. The
ranker rejects a required metric if overall, per-design, or worst-pair absolute
evidence is missing or non-finite. Two new regressions cover missing overall and
empty per-design evidence; the complete suite passes `150/150`.

The same final-ranker audit now rejects duplicate
`backend`/`metric`/`method` rows instead of silently allowing the later row to
overwrite earlier evidence. This preserves row-order independence for every
backend-local decision. The added regression brings the complete suite to
`151/151`.

Each accepted backend campaign in the final ranking now also records a
canonical-JSON SHA-256 of its complete `screening_summary.json` content. The
Markdown report prints the same digest next to the resolved source path, tying
the recommendation to exact OpenROAD and Innovus metric evidence rather than a
mutable filename alone.

An explicit policy regression now adds a deliberately severe placement-HPWL
loss to a candidate that improves golden H/V routability within routed-cost
budgets. The candidate remains eligible and `placement_hpwl` is absent from the
golden required-metric vector, proving that HPWL is diagnostic rather than a
hidden veto. The complete suite passes `152/152`.

The final ranker now also requires identical per-design coverage for every
method and metric. The production finalizer supplies the exact three-case
OpenROAD set and five-case Innovus set; both were checked directly against the
live `parallel_status.json` files. A current-schema integration regenerated the
retained one-design OpenROAD test1 and Innovus BP_quad fixtures from compact raw
rows. The production gate rejected that partial fixture before ranking, proving
that all-seed consistency on one design cannot be promoted as the robust final
result. Two coverage regressions bring the complete suite to `154/154`.

Backend summaries now preserve both declared and validated case-seed lists, and
summary completeness requires exact equality with no duplicate pair. The final
ranker independently checks the Cartesian product of every required design and
seeds 1000, 2000, and 3000. This rules out a scalar comparison count masking
missing or uneven seed coverage. Two additional regressions bring the complete
suite to `156/156`.

After reinstalling the current evaluator, an Innovus 22 detailed-route smoke at
`results/routability_lab/innovus_gcd_detailed_connectivity_installed_v3_3583ba6`
reported 0.00%/0.08% H/V congestion, zero DRC, unrouted nets, shorts, and
connectivity violations, 3,924.675 um routed wirelength, and 2,806 vias. The
short parser also exactly counted 251, 692, and 299 `SHORT:` records in three
independent nonzero Innovus DRC reports.

The remote checkout prefix cannot be mapped wholesale. For local Innovus
replay, map
`/home/yifanchen/proj/ruplace-routability-e0e3fe4/install/benchmarks` to
`/mnt/nvme0n1/yifan/projs/DREAMPlace/install/benchmarks`, and map
`/home/yifanchen/proj/ruplace-routability-e0e3fe4/results/routability_lab/real_design_inputs`
to this worktree's corresponding result directory. The first location contains
the gathered Nangate45/fakeram LEFs; the second contains the materialized 2D
DEFs. The final metadata preflight checked all 75 configs and placement DEFs,
15 comparison files, and 58 unique LEF/DEF/Verilog inputs with zero missing
files before Innovus launch.

The final transfer intentionally retains only status, comparison provenance,
method configs, and frozen placement DEFs:

```bash
rsync -a --prune-empty-dirs \
  --include='*/' --include='parallel_status.*' \
  --include='comparison.json' --include='config.json' --include='*.gp.def' \
  --exclude='*' \
  ceca2080x4:~/proj/ruplace-routability-e0e3fe4/results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/campaign/ \
  results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/campaign/
```

After the install and Innovus smoke gates pass, launch the detailed replay with:

```bash
python tools/routability_golden_replay.py \
  --source-campaign results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/campaign \
  --output-dir results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/golden_innovus_detailed_3583ba6 \
  --methods hpwl,survivor_pair_0003_rudy_net_weighting__local_gradient,weak_atomic_dev_0002_rudy_local_gradient,weak_atomic_dev_0006_rudy_net_overlap,weak_atomic_dev_0013_rudy_net_weighting \
  --evaluators innovus --max-parallel 4 --num-threads 8 \
  --timeout-sec 21600 --snap-manufacturing-grid --hardlink-placements --resume \
  --path-map /home/yifanchen/proj/ruplace-routability-e0e3fe4/install/benchmarks=/mnt/nvme0n1/yifan/projs/DREAMPlace/install/benchmarks \
  --path-map /home/yifanchen/proj/ruplace-routability-e0e3fe4/results/routability_lab/real_design_inputs=/mnt/nvme0n1/yifan/projs/DREAMPlace/.worktrees/ruplace-routability/results/routability_lab/real_design_inputs
```

Summarize each router campaign independently, then pass the two complete
summary JSON files to the backend-local Pareto ranker:

```bash
python tools/routability_summarize.py \
  --campaign-dir results/routability_remote/ispd2019_routability_first_unified_3583ba6/golden_openroad_detailed_3583ba6 \
  --output-dir results/routability_remote/ispd2019_routability_first_unified_3583ba6/golden_openroad_detailed_3583ba6_summary

python tools/routability_summarize.py \
  --campaign-dir results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/golden_innovus_detailed_3583ba6 \
  --output-dir results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/golden_innovus_detailed_3583ba6_summary

python tools/routability_rank_golden.py \
  --summary results/routability_remote/ispd2019_routability_first_unified_3583ba6/golden_openroad_detailed_3583ba6_summary/screening_summary.json \
  --summary results/routability_remote/real_5designs_3seeds_routability_first_3583ba6/golden_innovus_detailed_3583ba6_summary/screening_summary.json \
  --require-cases data_ispd19_test1,data_ispd19_test2,data_ispd19_test3 \
  --require-cases taiwei_nangate45_bp_quad_materialized2d,taiwei_nangate45_mempool_group_materialized2d,taiwei_nangate45_nvdla_l_materialized2d,taiwei_nangate45_openc910_materialized2d,taiwei_nangate45_xscore_materialized2d \
  --require-seeds 1000,2000,3000 \
  --require-seeds 1000,2000,3000 \
  --output results/routability_remote/golden_routability_ranking_3583ba6.json \
  --report results/routability_remote/golden_routability_ranking_3583ba6.md
```

The ranker discovers candidates from all golden metric rows, then rejects any
candidate without complete routed-wirelength coverage. It also rejects
incomplete summaries, inconsistent or incomplete required design/seed sets,
summaries containing more than one golden backend, and cross-backend summaries
with different method sets. It never adds OpenROAD and
Innovus values into one score. Golden replay applies the same finite,
nonnegative mandatory-metric contract when a route first completes and when a
persisted result is considered for `--resume`, so malformed routed wirelength,
H/V congestion/overflow, or DRC values cannot become authoritative.
The final summarizer requires the retained router log, DRC report, metrics,
route script, and backend-specific guide/connectivity artifacts. It reparses
Innovus reports and OpenROAD logs, congestion evidence, and metrics JSON, then
excludes an entire case-seed as `missing_artifact` or
`artifact_metric_mismatch` when evidence is absent or disagrees with a
persisted metric. Case-level and method-level resume apply the same artifact
contract. This consistency gate passes all currently completed BP_quad Innovus
and test1 OpenROAD comparisons. A direct `validated_replay_matches` audit also
accepted all six completed comparison files under the strict source identity,
method-set, preprocessing, mandatory-metric, and retained-artifact resume
contract, so a supervisor restart can reuse them without weakening evidence.

A subsequent artifact audit found that OpenROAD removes FastRoute's congestion
report before the detailed-route evaluator serializes its result. The old parser
therefore synthesized false 0/0 directional overflow from missing text. The
evaluator now snapshots the report immediately after global routing and creates
an empty retained report only when a successful clean route emits no violation
file. Strict enrichment no longer invents directional metrics when the artifact
is absent. For routes completed before that fix,
`tools/routability_backfill_openroad_congestion.py` reruns only global routing
on the frozen placed DEF and accepts the report only when global-route
wirelength and via counts exactly reproduce the original metric JSON. A live
backfill repaired all 15 test1 method routes; all three five-method comparisons
then passed both the case-level resume contract and strict artifact summarizer
with 0/0 H/V overflow backed by retained reports and per-route identity checks.

At 03:00 SGT on 2026-07-29, a fresh strict-contract checkpoint still found
`36/45` valid OpenROAD routes plus the two isolated test2 timeout artifacts,
and `43/75` valid Innovus routes with zero invalid artifacts. Five post-install
compact Innovus DRC reports are retained. Both OpenROAD workers remain
CPU-active, all four Innovus logs continue to advance through routing
iterations, and the recovery watcher is still waiting for the original
OpenROAD supervisor as designed. The routed-WL-primary ranking and independent
final-audit policy tests pass `39/39`; evaluator source and installed copies
remain byte-identical and `git diff --check` is clean.

`ceca2080x4` was checked as a possible OpenROAD accelerator. Its only located
binary, `/home/yifanchen/usr/bin/openroad`, is non-launchable because of
missing libraries and incompatible GLIBC/GLIBCXX requirements, and its binary
SHA-256 differs from the local golden validator. The local executable reports
OpenROAD `26Q1-951-g6975124cf2`. An Ubuntu 22.04 container was therefore built
around the exact local executable and OR-Tools runtime. The executable SHA-256
inside the image is the local value
`45f608244297fc77e5c9ce03f30525719f1427b81ed559355dacb94c5a9c7b7d`.
The image reproduced the retained Nangate45 GCD route both locally and on
`ceca2080x4`: global WL/vias `6432/2688`, detailed WL/vias `4012/2793`, and
DRC `0`.

After separately verifying the exact local test2 LEF, both frozen placed DEFs,
and current evaluator-source hashes on the remote, two isolated recovery jobs
were launched for the known six-hour timeout rows: seed-2000 `local_gradient`
as PID `17072` and seed-3000 `net_overlap` as PID `17073`. Each uses eight
threads and a 36,000-second cap. Fetching now runs in tmux session
`ruplace-openroad-fetch-3583ba6` (pane PID `180587`) and copies completed
outputs only into
`results/routability_remote/openroad_timeout_recovery_ceca2080x4_3583ba6`.
It does not modify the golden campaign. Remote outputs must pass local retained-
artifact reparsing and race resolution before they can replace timeout rows.
`tools/routability_import_openroad_recovery.py` and the frozen
`openroad_timeout_recovery_import_3583ba6.json` manifest enforce that import:
all inputs and evaluator modules are SHA-checked, artifacts are rebased and
reparsed in staging, the timeout directory is archived outside the campaign,
and a competing valid local result is accepted only when its complete metric
dictionary is identical. Six focused import/rollback tests pass.

At 03:18 SGT, Innovus advanced to `45/75` strict-valid routes, with seven
compact DRC artifacts and zero invalid rows. OpenC910 seed-2000 pair regressed
routed WL by `+3.697%`, H/V congestion by `+3.595%/+5.330%`, DRC by
`+9.255%`, shorts by `+9.524%`, and vias by `+1.484%`; unrouted nets and
regular-net connectivity remained zero. NVDLA-L seed-2000 `net_overlap`
improved H/V congestion by `-3.759%/-2.532%`, DRC by `-11.637%`, and shorts
by `-11.434%`, with zero unrouted/connectivity violations, but regressed routed
WL by `+1.141%` and vias by `+0.346%`. Both rows pass strict retained-artifact
reparsing. The first loses broadly; the second is a clear example of why a
routed-WL regression remains a primary veto even when congestion and DRC
improve.

At the 03:35 SGT checkpoint, the final audit conditionally binds any imported
OpenROAD timeout recovery to its frozen import spec, applied import report,
quarantine source, exact campaign target, and archived timeout evidence. It
independently re-hashes every fetched provenance file and compares the archived
timeout result against the digest captured by the importer. Focused rejection
fixtures cover missing evidence and tampering of input/hash manifests, route
coverage, source/target paths, and archived timeout content. The production
finalizer passes these recovery-audit inputs only after the applied import
report exists; campaigns with no imported recovery retain the ordinary audit
path. Routed wirelength, horizontal and vertical congestion or overflow, and
detailed-route DRC are co-primary veto dimensions; shorts, unrouted nets, and
available connectivity violations are primary as well. No improvement in one
of these dimensions can compensate for regression in another.

At 04:00 SGT, NVDLA-L seed-3000 `local_gradient` advanced Innovus to `46/75`
strict-valid routes, with eight compact DRC artifacts and zero invalid rows.
Relative to the same-seed HPWL route it improved H/V congestion by
`-11.940%/-11.875%`, total DRC by `-27.350%`, and shorts by `-26.818%`;
unrouted nets and regular-net connectivity violations remained zero, and vias
improved by `-0.053%`. Routed wirelength, however, increased from
139,865,297.578 to 155,985,606.246 um (`+11.526%`). This is a strong
congestion/DRC result but remains ineligible for a robust default because routed
wirelength is an independent co-primary veto rather than a compensable cost.

At 04:05 SGT, the production final audit gained independent ranking
recomputation. It now regenerates the complete backend-local constrained/Pareto
result directly from the two SHA-bound summaries, frozen case/seed matrices,
HPWL baseline, and `+5%` mean/`+10%` worst via budgets, then requires canonical
equality with the supplied ranking JSON. This closes the possibility that a
stale or tampered bounded-winner list could pass merely by making its declared
recommendation internally self-consistent. A regression accepts an authentic
recomputation and rejects a tampered HPWL fallback. The full gate passes 167
routability tests, one DEF-distribution test, 14 RUPlace unit tests, and 11
quality/source tests, for `193/193`; compilation and `git diff --check` pass.

At 04:09 SGT, production finalization also bound the human-readable ranking
report to the independently verified ranking object. `render_report` now
provides the deterministic representation used by both the ranker and final
audit, and the audit requires the retained Markdown to match it byte-for-byte.
A focused regression accepts the authentic report and rejects a one-line
semantic alteration. The complete suite now passes 168 routability tests, one
DEF-distribution test, 14 RUPlace unit tests, and 11 quality/source tests, for
`194/194`; compilation and `git diff --check` remain clean.

At 04:12 SGT, the final audit output gained an explicit objective-requirement
status map for the golden artifact contract, exact contest and real-design
matrices, independent Pareto recomputation, human-report binding, bounded
combination search, evaluator installation identity, and regression/source
integrity. Generic fixture mode labels production-only gates `not_required`;
the real finalizer's mandatory `--require-production-matrix` mode labels them
`validated` only after their checks pass. A direct production/nonproduction
regression covers this distinction. The complete suite passes 169 routability
tests plus the unchanged 1/14/11 supporting suites, for `195/195`.

At 04:19 SGT, finalization replaced its implicit regression-success claim with
a structured regression manifest emitted only after Python compilation, the
four test suites, and `git diff --check` succeed under `set -euo pipefail`.
The final audit reparses all four unittest summaries and `OK` markers, requires
the named 171/1/14/11 suite coverage and at least 197 total tests, rejects
failure markers or false pass booleans, and verifies the regression-log
SHA-256. Tampered-log and false-diff-pass regressions fail closed. The complete
suite passes `197/197`.

At 04:29 SGT, finalization also bound the complete routability-plugin package
to the reviewed source. An AST audit requires the exact ten-entry
`PLUGIN_REGISTRY`, including each plugin name, class, and relative import, while
SHA-256 identity checks cover `__init__.py`, all ten independently selectable
plugin modules, and `utils.py` in both the source and installed trees. The final
audit records the verified registry and per-file hashes and exposes this as a
separate objective gate. Regressions reject both a changed installed module and
an identically changed source/install registry with a missing plugin. The full
gate now passes 173 routability tests plus the unchanged 1/14/11 supporting
suites, for `199/199`; Python compilation, finalizer shell syntax, and
`git diff --check` pass.

At 04:36 SGT, the ranking gate was aligned with the summarizer's `1e-12`
floating-point tie tolerance. Mean, worst-case, Pareto-dominance, and
zero-baseline secondary-cost comparisons now use the same tolerance, which
prevents a reported numerical tie from becoming an inconsistent default veto.
The tolerance is explicit in the ranking policy and independently checked by
the final audit. A regression proves that `5e-13` worst-case primary residue is
a tie while `2e-12` remains a hard primary regression. The full gate passes 174
routability tests plus the unchanged 1/14/11 suites, for `200/200`.

At 04:43 SGT, Innovus `open_violations` was promoted from optional reporting to
an independently gated connectivity metric. The evaluator already derives both
total connectivity violations and opens from the retained connectivity report,
and all 46 current strict-valid Innovus routes contain finite values for both.
Golden resume and artifact contracts now require opens, and the backend-local
Pareto vector can no longer hide an open regression behind an unchanged total
connectivity count. A regression holds total connectivity neutral while
increasing opens and confirms HPWL fallback. The full gate passes 175
routability tests plus the unchanged 1/14/11 suites, for `201/201`.

At 04:59 SGT, the OpenROAD test3 seed-3000 route for the `net_weighting` plus
`local_gradient` pair completed before its six-hour timeout and passed the full
artifact contract. This advances OpenROAD to `37/45` strict-valid routes, with
two isolated timeout rows and six results not yet produced. Against its
same-seed HPWL route, the pair improved detailed-route wirelength by `-0.394%`
and vias by `-0.584%`, but increased DRC by `+0.095%` and shorts by `+3.587%`;
H/V overflow and unrouted nets tied at zero. The DRC and short regressions are
independent primary vetoes and cannot be offset by the routed-wirelength gain.

At 05:17 SGT, Innovus completed and strictly validated OpenC910 seed-1000
`local_gradient`, advancing the real-design matrix to `47/75` with no invalid
result. Against same-seed HPWL it regressed H/V congestion by
`+2.922%`/`+4.798%`, DRC by `+8.018%`, shorts by `+8.094%`, and routed
wirelength by `+3.781%`; unrouted nets, total connectivity violations, and open
violations tied at zero. Vias also increased `+1.411%`. Every nonzero primary
metric therefore vetoes this candidate on this case-seed independently.

At 05:32 SGT, OpenC910 seed-2000 `local_gradient` also passed the strict
Innovus artifact contract, bringing that matrix to `48/75`. It repeated the
same failure pattern: H/V congestion regressed `+3.595%`/`+5.076%`, DRC
`+7.694%`, shorts `+7.894%`, and routed wirelength `+3.751%`; unrouted nets,
total connectivity violations, and opens tied at zero, while vias increased
`+1.469%`. The independent seed confirms that the OpenC910 routability loss is
not a one-seed anomaly.

A live bibliography refresh added nine omitted mechanism-level works to the
literature matrix. The older set covers ICCAD 2009 clustering/estimation, CROP
module shifting and detailed-placement refinement, ASP-DAC 2014 group
pin-density constraints, and 2019 hierarchy/pin-aware mixed-size placement.
The recent set covers DATE 2022 pin-access optimization, VLSI-SoC 2022 RL
detailed placement, ISQED 2023 GNN placement guidance, ICCAD 2023 explainable-
AI routability optimization, and the 2025 Integration paper on explainable
routability-wirelength co-guided inflation. The public BSD `XAI_RoutOpt` source
was audited directly: it provides training, preprocessing, and DeepSHAP scripts
but lacks its referenced checkpoint/data, ClipGraphExtract feature flow, and
placement-remedy engine. A venue-specific TCAS-II search found no distinct
standard-cell routability-driven GP mechanism. The refresh exposed no new
runnable atomic GP force: clustering, inflation, regional movement, pin
porosity, and net weighting are already isolated, while the remaining distinct
mechanisms require learned assets, explicit group/hierarchy constraints, or a
separate post-GP detailed-placement stage. They are recorded as gaps rather
than being misrepresented as exact reproductions.

## Delivered surface

- Independent plugins: `route_inflation`, `momentum_inflation`,
  `path_inflation`, `local_gradient`, `poisson_force`, `net_weighting`,
  `net_overlap`, `pin_porosity`, `whitespace`, and `routeforce`.
- An `adaptive_composite` preset and the retained monolithic DREAMPlace/RUPlace
  baselines.
- Evaluators for RUDY, pin-RUDY, Xplace GGR, bundled GPUGR, CUGR, NCTUgr,
  OpenROAD global/detailed routing, and Innovus v22 EGR/detailed routing.
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
| All routability evaluator, plugin, orchestration, replay, summary, ranking, and audit tests | 175/175 pass |
| DEF distribution test | 1/1 pass |
| Legacy RUPlace unit tests | 14/14 pass |
| RUPlace quality/source tests | 11/11 pass |
| Total | 201/201 pass |
| Python compile and `git diff --check` | pass |

The installed `ruplace_quality_test.py` cannot locate `install/tools/ruplace_quality.py`
because legacy tools are not installed by CMake; the same suite passes from the
source tree with `PYTHONPATH=install`.

The `pin_porosity` fixed-macro map now rasterizes exact clipped rectangle-to-grid
overlap instead of assigning each macro's full area to its center bin. Unit tests
cover overlap values, boundary clipping, area conservation, and the plugin-level
porosity map. A CUDA smoke reproduced the expected map exactly, and a
1,000-macro, 256-by-256 CPU stress completed in approximately 1.91 seconds
including interpreter startup. The source was reinstalled with
`cmake --install build`; the installed plugin and helper modules are byte-identical
to their source copies. This plugin is outside the frozen five-method golden
finalist set, so the change did not alter any active placement or route.

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

## Historical validation conclusion and remaining research gaps

The earlier Poisson-focused plugin and bounded-combination campaign is complete.
No method or pair passed that frozen protocol, so its historical decision was
to enable no routability plugin by default. That decision is documented in
`docs/routability_validation_final.md`, but it does not complete the active
corrected proxy-first revalidation described above.

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

## Effective adaptive reopening

The first corrected adaptive manifest contains 80 atomic variants derived only
from test1/test2 near-miss evidence. A generation audit found that its
16-variant per-parent truncation removed both intended joint schedules. It also
emitted several trust caps larger than the relative force weight and refresh
cadences at or below the force-application interval; these settings can be
mathematically non-binding and produced byte-identical placements in completed
test1 runs. The frozen campaign remains unchanged and must still complete so
its result is reproducible.

Proposal policy version 2 corrects the tuning experiment rather than changing
the active result. It balances tuning dimensions inside the bound, guarantees
joint variants, derives binding trust caps, excludes ineffective refresh
cadences, and adds weaker force strengths, later activation, longer application
intervals, and stronger annealing. The gated runner is
`results/routability_remote/corrected_adaptive_v2_dev_3583ba6/run_remote.sh`.
It activates only if adaptive v1 has zero strict development survivor and uses
no test3, real-design, OpenROAD, or Innovus evidence to construct candidates.

The pair, real-design proxy, OpenROAD, Innovus, and final-audit waiters now treat
adaptive v2 as part of the mandatory funnel. Therefore no-candidate finalization
cannot occur after the known-defective v1 proposal grid alone.

## Absolute-directional proxy correction

A live audit of the completed adaptive-v1 test1 results found two additional
limitations in the legacy GPUGR screen. First, `rc_hor` and `rc_ver` were the
means of overflow-only maps, so an under-capacity direction collapsed to zero
and could not expose pre-overflow routing pressure. Second, placement feedback
used a 256-by-256 grid while the standalone evaluator silently used its default
128-by-128 grid because the evaluator-specific resolution keys were absent.
The active v1 matrix remains frozen on those legacy semantics.

Adaptive v2 now uses the versioned `absolute_directional_v2` metric profile.
GPUGR artifacts retain raw H/V utilization maps and report directional
utilization p99/max, overflow sums, and ACE hotspot scores. The selector gates
these absolute metrics, routed wirelength, overflow nets, and estimated shorts;
the normalized p99/mean hotspot ratio and legacy overflow means are diagnostic.
RUDY uses absolute overflow sum and utilization p99/max. Each backend must
improve independently and every primary worst-case delta must remain nonpositive.

The v2 contest template explicitly matches GPUGR feedback and validation at
256-by-256; the real-design template similarly matches its configured
128-by-128 feedback grid. A six-baseline development audit at 256-by-256 found
that test1 averaged 56 overflow nets and 440.7 estimated shorts, whereas the
legacy 128-grid evaluation averaged 0 and 2. Test2 exposed stronger horizontal
than vertical pressure: mean H/V ACE was 1.071/1.009 and mean H/V maximum
utilization was 1.326/1.185. These are resolution diagnostics, not candidate
wins, because raw GPUGR route statistics are resolution-dependent. The v2 smoke
gate must verify all enhanced metrics and resolution equality before its
development matrix starts. Patched source is staged remotely, but the installed
modules used by running v1 jobs are intentionally unchanged until v2 activation.

Compact per-seed evidence is retained in
`results/routability_remote/corrected_absolute_directional_baseline_dev_3583ba6`;
the larger route tensors and logs remain on `ceca2080x4` under the same relative
path.

## Matched-resolution adaptive-v1 replay

The legacy adaptive-v1 placements will no longer feed adaptive-v2 or any
held-out stage directly. `tools/routability_proxy_replay.py` now stages each
frozen DEF by hardlink (with copy fallback), hashes the source config and source
and staged DEF, preserves the full plugin-activation record, and reruns exactly
RUDY and GPUGR without rerunning placement. It rejects a source config unless
its feedback grid matches the requested validator grid, requires the complete
`absolute_directional_v2` metric contract, and rejects a nonpositive GPUGR
routed wirelength. An exclusive GPU queue prevents two replay jobs from being
assigned the same GPU concurrently. Its outputs use ordinary
`comparison.json`, `comparison.csv`, `parallel_status.json`, and
`HANDOFF_STATUS.md` contracts so the existing summarizer and strict selector
consume them without a special result path.

The remote transition runner is
`results/routability_remote/corrected_proxy_replay_v1_3583ba6/run_remote.sh`.
After adaptive-v1 reaches a terminal phase it will activate the already staged
v2 evaluator source, replay all six test1/test2 case-seeds at 256-by-256,
summarize, select with a zero worst-primary-regression gate, analyze near
misses, and audit all source hashes and resolution records. If the replay has a
survivor, only its frozen preset manifest can enter pair/test3 handling. If it
has no survivor, adaptive-v2 proposals are derived from the replay's corrected
near-miss file rather than the legacy 128-grid summary.

A second live audit found that this first matched-resolution implementation was
still incomplete. Bundled GPUGR honored the requested 256-by-256 grid, but the
standalone `RudyEvaluator` ignored `route_size`, `route_x_size`, and
`route_y_size`; its retained map was actually 512-by-512. The evaluator now
constructs RUDY and pin-RUDY on the requested grid and both RUDY and Xplace
adapters report the dimensions they actually used. Proxy replay schema version
4 requires positive reported dimensions and rejects either backend when its
reported dimensions differ from the requested grid, so schema-3 results cannot
be resumed as corrected evidence.

The activation and final proxy-code attestations now bind four source/install
pairs: `xplace_backend.py`, evaluator `base.py`, evaluator `rudy.py`, and
evaluator `xplace.py`. Adaptive-v2 independently installs, compiles,
byte-compares, and hashes the same four files. Its smoke and full-development
audits, plus every pair, held-out test3, and real-design campaign, inspect every
evaluator summary and require both backends' reported dimensions to equal that
campaign's feedback grid. Contest campaigns remain 256-by-256; real-design
campaigns remain 128-by-128 rather than being incorrectly forced to the contest
resolution.

An isolated frozen-test1 smoke completed on `ceca2080x4` at
2026-07-29 16:03 UTC. RUDY reported and produced a 256-by-256 map; GPUGR
reported 256-by-256 and produced a 256-by-256 utilization map plus a
2-by-256-by-256 directional tensor. All four isolated installed files were
byte-identical to their staged sources. Evidence is retained under
`results/routability_remote/corrected_resolution_smoke_3583ba6`.

The pair, real-design, and final-attestation runners no longer contain paths
that can promote the scheduled or adaptive-v1 legacy selections. Final proxy
attestation derives primary metrics and independent backend constraints from
the declared metric profile and explicitly requires
`absolute_directional_v2` for this corrected chain. The obsolete sleeping
downstream shells were cleanly replaced; their logs and artifacts were kept,
and adaptive-v1 placement/evaluation processes were not interrupted.

At the 2026-07-29 14:16 UTC snapshot, adaptive-v1 had produced 270 of 486
method configs and 268 of 486 evaluator summaries. All 243 test1 method configs
were present; three test2 seed jobs remained active on GPUs 3, 2, and 0. The
corrected replay, adaptive-v2, pair, real proxy, OpenROAD, and final-attestation
runners were detached and waiting on their immediate predecessor. The remote
installed evaluator still differed from the patched source, as required until
adaptive-v1 exits.

At the 2026-07-29 16:04 UTC snapshot, all three test1 seeds had 81 evaluator
summaries and no failed backend result. Test2 had 69, 37, and 17 completed
method summaries for seeds 1000, 2000, and 3000, again with no failed backend
result. Adaptive-v1 remained the only active placement dependency; the
corrected replay and hardened downstream runners were detached and waiting.

Validation for this correction passed 99 focused local tests across proxy
replay, runner, evaluator, summarizer, selector, near-miss, and corrected-audit
suites. The PyTorch-dependent evaluator suite ran in the placement environment.
The new replay/runner/audit subset passed 31 tests remotely. Python compilation,
shell syntax checks, and `git diff --check` also passed.

## Local golden handoff hardening

The corrected Innovus golden campaign no longer stores its routed databases
under the nearly full `/mnt/nvme0n1` repository filesystem. Its default artifact
root is now
`/mnt/nvme2n1/yifan/ruplace-routability-corrected-3583ba6/corrected_golden_innovus_3583ba6`,
where about 3.1 TiB was free at the 2026-07-29 live check. The repository retains
the status, protocol, activation evidence, and absolute symlinks to
`source_campaign`, `campaign`, and `summary`. Storage setup refuses to replace
any existing non-symlink path, so retained evidence is never deleted or moved.
The disk admission gate now measures the artifact filesystem rather than the
repository filesystem.

The local installed `base.py` intentionally remains on the legacy version while
the old Innovus replay is active. After strict real-design proxy admission, the
new runner copies the 79 MiB installed DREAMPlace package into the alternate
artifact root, atomically activates corrected `base.py`, `innovus.py`, and
`openroad.py` only in that isolated package, and records pre/post SHA-256 plus
byte-for-byte comparison evidence. Its explicit `PYTHONPATH` makes evaluator
subprocesses import the isolated package while leaving the shared install and
historical replay unchanged. The corrected final audit resolves campaign,
summary, and installed-evaluator paths from the Innovus status artifact root and
binds the activation manifest hash into both the source audit and router
attestation. Therefore corrected golden routing does not wait on or modify the
historical Innovus replay.

The local handoff, runner ordering, no-deletion, corrected-provenance, evaluator
activation, and corrected-audit checks are covered by the routability test
suite. At this revision, all 243 discovered routability tests passed; Python
compilation, shell syntax checks, and `git diff --check` also passed.

Adaptive-v2 now closes a previously uncovered tuning dimension. The scheduled
net-weighting parents all used `pre_objective`, and the original v2 proposal
generator varied strength, cadence, cap, and normalization without changing
the lifecycle phase. The corrected generator requires the six-comparison
`absolute_directional_v2` near-miss artifact, gives each available atomic plugin
one parent before adding extra backend-local Pareto parents, and emits both an
isolated phase toggle and a gentle joint alternate-phase net-weighting variant.
The parent ordering uses only frontier set membership and never scalarizes
RUDY with GPUGR. Proposal metadata and the remote runner audit now prove the
net-weight lifecycle key was tuned whenever net weighting is represented.
Plugin coverage is also based on plugin-local backend Pareto sets: each atomic
mechanism first uses a cross-backend intersection when one exists and otherwise
uses the union of its RUDY-local and GPUGR-local mean/worst frontiers. This
avoids selecting a lexicographically convenient but dominated parent merely to
claim mechanism coverage.

## Raw proxy-resolution attestation hardening

The corrected final audit now derives the complete method set from each strict
selection and binds its sibling `screening_raw.csv`. It requires exactly one
successful RUDY and GPUGR row for every method and common case/seed slot, rejects
duplicate or shifted slots, and requires every reported route dimension to
equal the campaign feedback grid. The resulting proxy attestation records the
raw-file SHA-256, exact comparison slots, method list, comparison count, result
count, and reported grid for every selection stage. Router and final audits
independently revalidate those record counts and hashes before accepting the
proxy admission set.

Stage labels are also bound to exact design identities, not only row counts.
Development replay/adaptive evidence must be the full `test1`/`test2` by
three-seed matrix, contest held-out evidence must be `test3` by three seeds,
real development must be BP_quad/Mempool/NVDLA by three seeds, and real held-out
must be OpenC910/XScore by three seeds. Substituting another design while
preserving the same number of rows now fails both the raw proxy audit and later
attestation validation.

Regression coverage includes mismatched dimensions, duplicate result slots,
missing resolution columns, incomplete matrices, same-count shifted case/seed
matrices, inconsistent attested counts, and an integration check that the
summarizer retains RUDY/GPUGR dimensions in `screening_raw.csv`. All 278
discovered `routability_*test.py` tests passed, along with Python compilation
and `git diff --check`. The corrected audit deployed to `ceca2080x4` is
byte-identical to the tested local file with SHA-256
`a830a3ff5293525657509d4a128029f642a225b14b8538e6722efbc882f631ae`.

At the 2026-07-29 16:24 UTC snapshot, adaptive-v1 retained complete 81-method
RUDY/GPUGR results for all three test1 seeds. The three active test2 seeds had
at least 71, 49, and 30 paired method results, respectively, with no failed
backend result. GPUs 3, 2, and 0 were active and GPU 1 was idle because only
three case/seed jobs remained. These adaptive-v1 evaluations still use the
legacy installed evaluator and are not admissible corrected proxy evidence.
After adaptive-v1 exits, the waiting replay installs and byte-compares all four
corrected source files, freezes the exact 120-method development union, and
re-evaluates its six case/seeds at 256-by-256 before any adaptive-v2, pair,
held-out, real-design, or golden stage can advance.

A golden-policy re-audit removed one last optionality gap. The ranker previously
included Innovus `connectivity_violations` and `open_violations` when present,
but could silently omit either metric if all rows were missing, and its rendered
report incorrectly described opens as an optional breakdown. Both metrics are
now unconditional Innovus primary requirements: missing coverage fails ranking,
and any mean or worst-case regression remains an independent default veto.
`tools/routability_audit_final.py` independently requires the same explicit
policy entries. Missing-open and missing-policy regressions pass locally, and
the full 278-test gate remains green. The byte-identical remote deployments have
SHA-256 `cc19e315f55a0b679b6105e68884a09e11da64798399d91dae0037979bf42da2`
for `routability_rank_golden.py` and
`b2b1d398ba63b1714801cf1ff109d08a77f790fc0f19b51f1ecd3aca285a96dc`
for `routability_audit_final.py`.

The successful proxy-chain audit now proves exact method admission as well as
case/seed admission. The real-development raw matrix must contain exactly HPWL
plus the frozen contest-heldout survivors; evaluating any additional method is
a failure even if that method is later excluded. The OpenC910/XScore raw matrix
must similarly contain exactly HPWL plus the real-development survivors. This
closes a gap where selected sets were required to shrink but an unadmitted
method could still be evaluated after a stage boundary. Passing, extra-real-
development, and extra-real-heldout regressions are included in the 278-test
gate.

The golden ranker now also treats placement HPWL as a mandatory diagnostic
artifact rather than silently dropping its `placement` backend rows. Every
method must have complete case/seed placement-HPWL coverage consistent with the
routed metrics. The JSON and Markdown retain those values in a separate
diagnostic section, while the objective vector and every Pareto, safety,
evidence, and winner gate exclude them. The final auditor independently checks
the diagnostic policy, frozen-method coverage, and objective isolation.

## Corrected evidence for the five omitted plugin families

A scope audit found that the corrected 120-method replay covered only
`local_gradient`, `net_overlap`, `net_weighting`, `poisson_force`, and
`whitespace`. The earlier results for `route_inflation`,
`momentum_inflation`, `path_inflation`, `pin_porosity`, and `routeforce` used
legacy validator resolution or policy and therefore cannot eliminate those
families under `absolute_directional_v2`.

The new development-only campaign at
`results/routability_remote/corrected_missing_families_dev_3583ba6` closes that
gap with 30 explicit coupled parameter variants, six per family. It uses only
ISPD2019 `test1` and `test2`, seeds 1000/2000/3000, separate RUDY and GPUGR
evaluation, and matched 256-by-256 feedback/evaluator grids. Area-transform
variants jointly tune the per-round area cap and `max_num_area_adjust`, avoiding
the earlier ineffective case where a nominal multi-round setting was limited
to one placement area adjustment. The route-inflation sweep includes global,
local, H/V-directional, windowed, and shrink-enabled variants. Momentum, path,
and pin-porosity sweeps cover weak through multi-round settings and macro/pin
balance. Routeforce covers route/apply cadence, annealing, anchor policy, and
objective-relative force ratios.

Routeforce itself was corrected before tuning. It previously added the full
router gradient, including non-movable coordinates, and exposed only an
absolute raw coefficient whose default value `1.0` was destructive in prior
runs. It now slices the router field to movable x/y coordinates and uses the
common placement-gradient RMS scaling contract. Absolute mode remains the
compatibility default; the corrected campaign uses bounded relative ratios from
0.005 through 0.05. Unit coverage proves fixed/non-movable gradient entries are
unchanged and the applied RMS ratio matches the requested value.

`tools/routability_audit_family_campaign.py` requires positive activation for
every configured plugin placement, exact six-comparison development scope,
successful independent RUDY/GPUGR results, and exact 256-by-256 reported
dimensions. Its hash-bound attestation is now mandatory for both the successful
proxy-chain audit and the no-candidate audit, so the previous five-family
pipeline cannot produce a final conclusion. Strict survivors are merged with
the earlier corrected atomic survivors by
`tools/routability_merge_atomic_survivors.py` before pair or held-out testing;
held-out `test3` and real designs are not used to select these parameters.

The expanded local regression gate passes all 286 discovered
`routability_*test.py` tests. Python compilation, JSON parsing, shell syntax,
and `git diff --check` pass. The campaign controls and source changes deployed
to `ceca2080x4` are byte-identical to the local tested files. At the 2026-07-29
16:55 UTC snapshot, adaptive-v1 was still active, so the new one-shot detached
runner correctly wrote `phase=waiting_for_adaptive_capacity`, exited with its
capacity-deferred status, and did not modify the installed package or start a
competing GPU job.

Two additional one-shot stages are deployed behind that gate. The integrated
contest stage unions strict atomic survivors from both corrected five-family
sources, evaluates only compatible same-proxy pairs on development cases, and
then runs the admitted atomic/pair set on held-out `test3`. The integrated real
stage consumes only that held-out contest selection, screens on
BP_quad/Mempool/NVDLA, and reserves OpenC910/XScore for held-out proxy
validation. Their current phases are respectively
`waiting_for_missing_family_terminal` and
`waiting_for_integrated_contest_terminal`; neither process remains running or
polling after writing its deferred status.

## Missing-family smoke and effective-control audit

The isolated GPU-1 smoke-v2 completed all six placements and both requested
proxy evaluations per method, but failed its artifact audit. Each evaluator
invocation wrote evaluation/summary.json, so GPUGR overwrote the earlier RUDY
entry even though comparison.json, rudy.json, and gpugr.json retained both
successful results. tools/routability_compare.py now replaces that transient
single-backend file with an aggregate per-method summary after all evaluators
finish. A regression reproduces the overwrite and requires the final summary
to retain RUDY and GPUGR in request order.

An implementation-to-preset audit then found two effective-control defects.
First, the local route-inflation pass could reduce a ratio established by the
global pass even when ruplace_allow_shrink=0; its cumulative target is now
bounded below by the current inflation ratio. Second, routeforce interpreted
ruplace_admm_route_freq in successful force applications rather than placement
iterations. For example, apply_freq=20 and route_freq=100 could reuse one route
for about 2,000 iterations. Route refresh now follows placement iterations and
also refreshes whenever no cached route exists.

Smoke-v3 was launched with the aggregate-summary repair before the two
effective-control fixes were made. It is retained as infrastructure evidence
but cannot attest the final parameter sweep. The staged smoke-v4 uses a fresh
artifact root and keeps the isolated Python install on GPU 1. Its explicit
source manifest copies, compiles, byte-compares, and hashes the placement hooks,
GPUGR adapter, evaluator adapters, pipeline/proxy, shared inflation engine, and
all five family implementations instead of inheriting unproved files from the
shared install. The full missing-family runner activates the same source set
and now defers with exit 75 if any parallel GPU campaign or the corrected replay
runner is active.

The final six-point matrices also cover activation timing rather than holding it
constant: every missing family includes density-overflow thresholds 0.8, 0.5,
and 0.3. Routeforce retains independent apply and route-refresh cadence,
gradient-relative strength, decay, and anchor-policy points; the four area
families retain their area-cap, round-count, smoothing/directional, and
family-specific strength points. A generator regression requires all three
thresholds for every family. The complete local gate passes all 291 discovered
routability_*test.py tests; Python compilation, JSON parsing, shell syntax, and
git diff --check also pass.

The strict proxy profile now treats aggregate overflow-bin count and horizontal
and vertical overflow-bin counts as independent primary metrics. These values
were already emitted by RUDY/GPUGR but were previously absent from the
summarizer and survivor veto set. A candidate must now provide complete
case/seed coverage and zero positive worst-case regression for these counts in
addition to routed wirelength, estimated shorts, overflow nets, overflow sums,
H/V utilization, H/V ACE, and H/V route-congestion means. Backend improvement
requirements remain separate: at least one RUDY primary and at least one GPUGR
primary must improve, with no numeric aggregation across the two backends.

Smoke-v4 completed successfully on GPU 1. All five plugin placements activated
(route_inflation, momentum_inflation, path_inflation, and pin_porosity once
each; routeforce 16 times), HPWL and every plugin produced successful RUDY and
GPUGR results at 256-by-256, and all 22 source/install hash pairs matched. The
comparison therefore contains six successful placements and 12 successful
proxy results. Its first audit reported ten proxy results because it counted
only plugin methods, although the validated comparison and HPWL aggregate
summary retained both baseline results.

Inspection of those activation diagnostics found that skipped calls repeatedly
recorded the preceding successful call's metric dictionary. This did not alter
placement or proxy QoR, and activation counters were correct, but it inflated
diagnostic sample counts (for example, one route-inflation application appeared
in 237 metric samples). The pipeline now clears each plugin's per-call metrics
before objective, gradient, or area invocation. Smoke-v5 is the required exact
final-source attestation: its audit requires six placements, all 12
method/backend slots, per-method aggregate summaries, exact 256-by-256
dimensions, five-family activation, and 22 equal source/install hash pairs.
The complete local regression gate passes all 292 discovered routability tests.

Smoke-v5 completed successfully on `ceca2080x4` at 2026-07-29 17:46 UTC and
passed that exact final-source contract. Its `smoke_audit.json` records six
placements (HPWL plus one representative from each omitted family), all five
families activated, 12 successful RUDY/GPUGR result slots at 256-by-256, and 22
equal source/install SHA-256 pairs. The parallel job returned zero, and the
runner's terminal `SMOKE_STATUS.md` phase is `completed_isolated_smoke_v5`.
Adaptive-v1 still had two active test2 case/seed jobs at the same live check,
while the corrected proxy replay remained in
`waiting_for_adaptive_v1_terminal`. The full 30-variant missing-family runner
therefore remains correctly deferred until both processes release exclusive
GPU capacity; it has not modified the shared remote install.

To avoid requiring an interactive restart after those prerequisites finish,
`launch_after_corrected_chain_remote.sh` is deployed byte-identically and
detached on `ceca2080x4`. Its supervisor PID is 10799, its launcher PID is
10800, and `DEFERRED_LAUNCH_STATUS.md` records
`phase=waiting_for_corrected_chain` with replay PID 50600 and adaptive-v2 PID
60249. The launcher validates both command lines, waits for those exact
processes without a shell polling loop, and then calls the independently gated
missing-family runner. A residual capacity conflict remains a deferred exit 75
rather than an unsafe concurrent install or GPU launch.

The remaining remote stages are also connected without bypassing their
individual admission gates. The byte-identical
`corrected_integrated_contest_3583ba6/launch_after_missing_remote.sh` runs as
detached PID 14060 with wait helper PID 14063 and records
`phase=waiting_for_missing_family_launcher` in `DEFERRED_CHAIN_STATUS.md`.
After missing-family PID 10800 terminates successfully, it sequentially invokes
the integrated contest development/pair and held-out test3 runner, the
BP_quad/Mempool/NVDLA development plus OpenC910/XScore held-out real-design
runner, the final-survivor OpenROAD detailed router, and the independent remote
attestation. Any prerequisite deferral or failed stage stops the chain and is
preserved as a terminal status instead of silently continuing.

The corrected integrated Innovus runner remains staged locally. It uses an
isolated Python install and alternate `/mnt/nvme2n1` artifact storage, but does
not itself exclude other active router campaigns. It will therefore not be
started while the retained historical OpenROAD/Innovus supervisors are still
active. This resource-scheduling delay does not change the frozen proxy
admission set or allow OpenROAD evidence to tune the candidate.

The staged integrated Innovus runner now enforces that scheduling boundary
itself. Before alternate-storage setup or evaluator activation, it records and
checks only RUPlace processes tied to the retained
`golden_openroad_detailed_3583ba6`, `golden_innovus_detailed_3583ba6`, and
older corrected-Innovus runner. A live invocation exited with the designated
deferred code 75 and `phase=waiting_for_legacy_router_capacity`, listing the
three relevant supervisors while ignoring unrelated Innovus processes from
other repositories. Regression coverage fixes this ordering and scope; the
full local discovery remains 292/292 passing, with Python compilation, shell
syntax, and `git diff --check` also passing.

A later structured adaptive-v1 checkpoint confirms forward progress rather than
a stale supervisor. Each of the four completed case/seed jobs contains all 81
placements and 162 successful RUDY/GPUGR rows. The active test2 seed-2000 and
seed-3000 jobs have materialized 75 and 70 of 81 methods, respectively, up from
49 and 30 at the earlier checkpoint. The deferred launchers now also have a
regression that requires process-based waiting without `sleep`, launches the
missing-family runner only after the corrected replay/adaptive prerequisites,
and preserves the downstream order contest, real proxy, OpenROAD, then remote
audit. The targeted runner suite passes 21/21.

The absolute-directional metric audit also confirms the deliberate backend
asymmetry. DREAMPlace's RUDY evaluator receives a single capacity-normalized
utilization map from the RUDY operator, so its defensible primary metrics are
aggregate overflow sum/bin count and utilization p99/max. It does not claim a
synthetic H/V decomposition. GPUGR independently supplies mandatory horizontal
and vertical overflow, bin, utilization, ACE, and route-congestion metrics for
proxy admission, while OpenROAD/Innovus supply the backend-native H/V golden
metrics. Thus every stage retains directional evidence without inventing or
numerically mixing RUDY and GPUGR quantities.

Research provenance is now executable regression evidence rather than only a
documentation convention. The plugin test enumerates the live registry and
requires every one of its ten independently selectable mechanisms to appear in
the literature-to-plugin matrix. This preserves the distinction between
paper-inspired mechanism implementations and the explicitly unimplemented
learned-model, post-route ILP, or timing-aware methods. The expanded full local
routability suite passes 293/293, with Python compilation and
`git diff --check` also passing.

The missing-family attestation now proves parameter-space coverage as well as
family presence. Each of the five omitted mechanisms must have exactly six
development variants and activation thresholds 0.3, 0.5, and 0.8. The
attestation also requires variation of each family's effective controls:
inflation strength/cap/rounds and H/V mode, momentum beta/step/rounds,
path-inflation strength/rounds, pin-porosity strength/radius/balance/rounds,
and routeforce strength, apply cadence, route-refresh cadence, and decay. The
derived values are embedded in `tuning_coverage` and bound by the preset and
manifest hashes used by the final proxy audit. A regression rejects a matrix
whose route-refresh cadence is held constant.

The expanded local suite passes 294/294 with Python compilation and
`git diff --check`. The two future-stage audit modules were deployed only after
confirming neither was executing on `ceca2080x4`; the remote files compile and
match local SHA-256 values `cb84d19c10a3a62b2d26a0a652fe16711b45f9abcd304a5851c0db4cdd3dc7a7`
and `c64a4f7d777cde5f5c2bc45709be0903b1ea9e550f145bc7cd2fbfb599de53ba`.

An all-ten tuning audit found and closed a DAG error before corrected replay
started. Adaptive-v2 contains the net-weight lifecycle toggle and additional
directional-feedback variants, but its old watcher exited early whenever the
corrected replay found any survivor. That outcome would have skipped tuning
dimensions required by the protocol. Adaptive-v2 now runs after either replay
terminal outcome, using only the same six development comparisons and
backend-local near-miss frontiers. Integrated contest admission now unions the
strict corrected-replay, adaptive-v2, and missing-family selections instead of
choosing replay survivors in preference to adaptive-v2.

The corrected runner gate passes all 294 local routability tests plus shell
syntax and `git diff --check`. Remote runner hashes are
`ebc30af5949aaab31ce2036719fa9f42a67dcaf39631e405e4f770a978ad8bdc`
for adaptive-v2 and
`b2434f8a263cd31373ae180c9bb0fcd9d434c0d42355d046ecf3a4d0cd047e64`
for integrated contest. Only idle watcher processes were replaced: the active
placements and replay were untouched. New adaptive-v2 PID 29105 waits for
replay PID 50600; missing-family PID 29221 waits for both; downstream PID 29465
waits for PID 29221. Their status files bind those exact dependencies, and all
four superseded waiter/wrapper PIDs are stopped.

The future three-source survivor merge was audited before the missing-family
campaign launched. `tools/routability_generate_family_presets.py` had applied
`shared_overrides` to copied presets as well as generated family variants,
which added activation and refresh fields to the missing-family HPWL baseline.
That baseline then differed from the corrected-replay and adaptive-v2 HPWL
presets, so `tools/routability_merge_atomic_survivors.py` would have rejected
the otherwise valid replay/adaptive/missing union. Copied presets now remain
exact identities and shared tuning fields apply only to generated variants.
The shared base HPWL preset now also explicitly sets `detailed_place_flag` to
zero, matching the scheduled/adaptive development identity rather than
inheriting the campaign template's detailed-placement setting. The regression
suite proves the base HPWL object is unchanged by family generation, matches
the production scheduled identity, and allows three independently generated
replay, adaptive, and missing-family survivor bundles to merge. The expanded
routability gate passes all 296 tests under the local `placement` PyTorch
environment, with Python compilation, JSON parsing, shell syntax, and
`git diff --check` also clean.

The corrected generator was deployed before the waiting missing-family
launcher could activate. Its local and `ceca2080x4` SHA-256 is
`2d607aa039e3676fa4d7ee2fccb1e434788eaa57d5de2eceed9b6e389d5b14af`.
The canonical base preset file is also deployed with SHA-256
`9259ad5b67c5e258c39c8d8a8dcd3024abdb10ceb48b9cf7c82a8f5897c954d1`.
An isolated invocation on the remote using the production
`routability_missing_families_absolute_directional_v2.json` spec generated all
30 variants and confirmed that its HPWL preset exactly equals both the base
preset and the live scheduled/adaptive preset. Active placement PID 48635 and
the replay/downstream dependency chain were not interrupted.

The staged integrated merge had a second deterministic incompatibility. All
three source selectors use the same strict backend-local admission metrics,
one-improvement-per-backend requirement, and zero worst-case primary
regression gate, but their intentional source-local survivor caps are 32 for
corrected replay, 5 for adaptive-v2, and 12 for the missing families. The old
merger compared the complete serialized selection policies, so those cap
differences alone would have stopped the integrated contest stage. It also
would have mislabeled a successful union with replay's cap even when the union
contained survivors from all three sources.

`tools/routability_merge_atomic_survivors.py` now compares every strict
admission-policy field except the source-local cap, validates each positive
integer cap and its selected count, and records both `[32, 5, 12]` and their
49-method union bound in the merged provenance. It still rejects any change to
the actual objectives, backend constraints, metric profile, numeric-separation
policy, or zero-regression gate. Regression coverage exercises the production
three-source cap pattern and a mismatched admission policy. The expanded suite
passes all 297 routability tests with compilation, JSON, shell syntax, and
`git diff --check` clean. The corrected merger was deployed before any source
selection existed and matches local SHA-256
`08397f69b4ccb2cda8f81a1ae82e1eda105951d37e1e36f175a4c5960d3dcc6f`.

The integrated no-candidate path was also incomplete for the likely all-empty
development outcome. When corrected replay, adaptive-v2, and the missing-family
campaign all selected zero methods, the previous runner supplied only the
adaptive-v2 and missing-family empty selections to the final attestation. That
did not bind the corrected-replay result and therefore could not prove that the
full scheduled/adaptive-v1 search space was exhausted before recommending
HPWL.

The final remote runner now requires the terminal phases for all three source
campaigns and supplies all three strict empty selections. The corrected audit
tool maps every terminal phase to its exact acceptable empty-selection set and
exact comparison count. Integrated atomic exhaustion requires
`corrected_replay_development`, `adaptive_v2_development`, and
`missing_families_development`; contest, real-development, and real-heldout
exhaustion each require their corresponding terminal selection. A regression
accepts the complete three-source proof and rejects it when corrected replay is
omitted. The expanded suite passes all 298 tests with compilation, JSON, shell
syntax, and `git diff --check` clean. The deployed SHA-256 values are
`fd5bf8e0ec6ff80058a6e7baa2eeb6ec16f8c3361ca2ec9bd53bda9ffa88eaff`
for `tools/routability_audit_corrected.py` and
`d5302b300a0df9feeba630d71cb5603ce4a066603903f636dfd6d1c601b0527a`
for the integrated final remote runner.

The golden backend scope remains deliberate rather than incomplete: OpenROAD
routes held-out ISPD2019 test3 for seeds 1000, 2000, and 3000, while Innovus 22
routes BP_quad, Mempool, NVDLA-L, OpenC910, and XScore for the same three seeds.
The router attestations bind each exact matrix, and the final ranker requires
identical methods across both complementary backend summaries before making a
recommendation.

A preflight of the future 120-method corrected-replay union compared every
available duplicate HPWL source pair. ISPD2019 test1 seeds 1000/2000/3000 and
test2 seeds 1000/2000 have identical canonical configs, byte-identical placed
DEFs, and identical placement evidence after excluding runtime, exactly
matching the contract enforced by
`tools/routability_merge_source_campaigns.py`. Test2 seed 2000 completed all
81 methods successfully at 2026-07-29 18:44 UTC; its canonical config and
placed-DEF SHA-256 values are
`321426e12ed907837f0a5b0778741a7628f252229bbe0feaebcbab38fe1520ee` and
`a273cb4bd686b6d2fefae66a59d4c090ac7df0d832438a510a6580da229b1116`.
Test2 seed 3000 is the sole remaining adaptive-v1 job and the sole pending
duplicate-HPWL identity check. At the same checkpoint it had materialized
76/81 methods and evaluated 75/81; GPU 0 was active on
`adaptive_dev_0075_local_gradient_minimum_0`. The corrected replay and its
adaptive-v2, missing-family, and downstream dependents remain correctly gated
on terminal adaptive-v1 evidence.

A bounded-grid audit found one more adaptive-v2 coverage defect before the
corrected replay became terminal. Policy v4 placed all directional modes in a
single round-robin category. With the production limit of 16 variants per
parent, that guaranteed only `utilization_hv_max`; it could omit
`utilization_hv_mean`, `utilization_horizontal`, and `utilization_vertical`
while the manifest still reported absolute directional feedback as tuned.
Policy v5 treats each of the four absolute-utilization modes as an independent
required dimension. The 16-variant regression now requires all four modes,
and the manifest records the exact ordered mode list and reports complete
coverage only when the list is exhaustive.

Policy v5 passes all 300 local routability tests and the focused remote suites
(`8/8` adaptive proposal, `21/21` runner, and `27/27` plugin), plus Python
compilation, shell syntax, and `git diff --check`. Local and remote SHA-256
values are `e1e8e2f16e577b8dc8fba6e9b367222d951199e0152758a88d11b11522b1691e`
for `tools/routability_propose_adaptive.py` and
`1defe91343a78e22286efa2737b61f2cacea054c8bae362dc2a11f9c5d6e21c1`
for the adaptive-v2 runner. Only the three idle v4 waiters were stopped.
Adaptive-v1 PID 48635 and replay PID 50600 were untouched. The replacement
adaptive-v2 PID 70053 waits for replay 50600; missing-family PID 70136 waits
for both; downstream PID 70218 waits for PID 70136. Their generated status
files bind those exact dependencies.

## Activation-clean replay repair and GPUGR coverage source (2026-07-30)

Adaptive-v1 completed all six development case/seeds with zero placement-job
failures, but the replay source merge correctly rejected one method that was
selected without activating. A complete reparse of every source comparison
and `placement.log` found zero genuinely inactive placements among the 240
scheduled rows after recovering 48 stale net-weighting summaries from their
logs. Among the 486 adaptive-v1 rows, exactly one is genuinely inactive:
`adaptive_dev_0003_local_gradient_start_0.6` on ISPD2019 test1 seed 2000.
It reached the gradient hook 241 times and scheduled 12 force evaluations with
nonzero reference gradients, but every congestion-field norm and applied scale
was zero; its final density overflow was `0.09844418`. The same method was
active on the other five development slots. This is a real per-slot no-op, not
a comparison-parser defect, so it is excluded rather than relabeled active.

`tools/routability_merge_source_campaigns.py` now provides a complete
activation audit with per-case/seed method, plugin, proxy, start thresholds,
attempts, activations, final density overflow, evidence source, pipeline
counters, metric histories, and a classified failure reason. Its default
contract still rejects any inactive source placement. The new opt-in frozen
union mode excludes a method if it is inactive on any development slot and
records every excluded row and reason in both a standalone audit and the union
manifest. Replay method counts are derived from that manifest rather than the
obsolete fixed `120/119` assumptions.

The same audit exposed a separate source-coverage defect: the scheduled plus
adaptive-v1 union had GPUGR provenance for local-gradient, net-overlap, and
whitespace methods, but net-weighting and Poisson-force had only RUDY
provenance. The merger now requires both RUDY and GPUGR provenance independently
for every required plugin. A third development-only source campaign was added
under `corrected_proxy_coverage_dev_3583ba6`: four GPUGR net-weight variants
cover pre-objective and post-gradient lifecycles with design-mean
normalization, and eight GPUGR Poisson variants cover weak/medium strengths for
`utilization_hv_max`, `utilization_hv_mean`, `utilization_horizontal`, and
`utilization_vertical`. Its activation audit permits candidate-level
exclusions but requires at least one method for each missing plugin/proxy pair
to be active across all six development slots before replay can proceed.

The expanded local routability suite passes `304/304` under the `placement`
PyTorch environment. Remote focused suites pass `15/15` source-merge tests,
`5/5` family-generator tests, and `21/21` runner tests, with Python compilation,
JSON parsing, and shell syntax clean. Remote `git diff --check` is unavailable
because the campaign mirror intentionally has no `.git` directory; the local
worktree check is clean.

The prematurely released missing-family campaign remains useful independent
development evidence and is currently healthy at 3/6 completed case/seeds,
with all three test2 seeds running on the four GPUs. Launcher PID `70136`
remains active. A replacement one-shot chain is detached as PID `35830` with
durable status
`corrected_proxy_coverage_dev_3583ba6/CHAIN_STATUS.md`; it is currently
`waiting_for_missing_family_terminal`. After capacity is released it runs the
new GPUGR coverage campaign, the activation-clean three-source replay,
adaptive-v2, and then the existing integrated held-out/OpenROAD chain in that
order. The older downstream waiter PID `70218` is retained but cannot promote
the failed replay because the integrated runner checks terminal phases.

## Local Innovus successor staged (2026-07-30)

The corrected remote chain does not itself launch the local Innovus golden
campaign. A one-shot local successor is now provided at
`corrected_integrated_golden_innovus_3583ba6/launch_after_remote_chain_local.sh`.
It validates the identity of remote chain PID `35830`, waits with a single
`tail --pid` operation, requires `CHAIN_STATUS.md` to report `completed`, then
runs the existing Innovus-22 golden runner and the combined OpenROAD/Innovus
final audit in order. Both candidate and no-candidate terminal paths require
explicit accepted status phases; no proxy-only result can be presented as a
golden winner.

Local Innovus 22.10 was launch-checked through the validated `cadence-local`
Rocky 8 wrapper, and `/mnt/nvme2n1` has about 3.1 TiB free for retained route
artifacts. The successor is detached as local PID `854955`, with durable state
in `corrected_integrated_golden_innovus_3583ba6/LOCAL_CHAIN_STATUS.md` and log
in `launch_after_remote_chain_local.log`. Its current phase is
`waiting_for_remote_chain_terminal`. Shell syntax, `git diff --check`, and the
focused runner suite (`21/21`) pass.

## Net-weight lifecycle behavioral gate (2026-07-30)

The net-weight lifecycle audit now includes a real-tensor behavioral regression
instead of relying only on hook ordering and a mocked update. With a shared net
weight tensor and a real congestion map, `pre_objective` changes the current
objective and gradient from `(4, 4)` to `(5, 5)`, while `post_gradient` leaves
the current objective and gradient at `(4, 4)` and changes the next evaluation
to `(5, 5)`. This proves the opt-in corrected lifecycle and the preserved legacy
lifecycle at their actual objective boundary. All `306/306` discovered
`routability_*_test.py` tests pass under PyTorch 2.4.0; Python compilation and
`git diff --check` are clean.

At the live remote checkpoint, the missing-family campaign retained three
complete test1 case/seeds and advanced test2 to `55/93` methods with complete,
separate RUDY and GPUGR results. One additional test2 method had completed RUDY
and was running GPUGR. No proxy result was non-OK. Remote PIDs `70136` and
`35830` and local Innovus-successor PID `854955` remained alive with the two
successors correctly waiting for terminal upstream evidence.

## Policy-v6 missing-family adaptive chain resumed (2026-07-30)

The five mechanism families that were screened but not adaptively retuned are
now covered by proposal policy v6: route inflation, momentum inflation, path
inflation, pin porosity, and RouteForce. The development-only stage selects one
near-miss parent per family and generates at most 16 variants per parent. Its
bounded grids include joint gentle and early-gentle variants and tune the
family-specific strengths, activation thresholds, caps, round counts,
momentum, porosity, RouteForce trust/cadence/refresh, and decay controls. The
stage uses only the six ISPD2019 test1/test2 development comparisons and keeps
RUDY and GPUGR numerically separate.

At the live one-shot checkpoint, missing-family launcher PID `70136` remained
healthy. All three test1 case/seeds were terminal, and test2 had advanced to
`77/93` methods with complete separate RUDY and GPUGR results; no persisted
proxy result was non-OK. The corrected downstream remote chain was relaunched
as detached PID `1871`. Its `CHAIN_STATUS.md` now records both
`chain_pid=1871` and `missing_launcher_pid=70136`, and reports
`waiting_for_missing_family_terminal`. It will run missing-family adaptive-v2,
GPUGR coverage, activation-clean corrected replay, regular adaptive-v2, and
the integrated held-out/OpenROAD chain in order.

The matching local Innovus/final-audit successor is detached in a new session
as PID `903940`. `LOCAL_CHAIN_STATUS.md` binds it to remote chain PID `1871`
and reports `waiting_for_remote_chain_terminal`. It cannot start Innovus until
the remote proxy and OpenROAD evidence is terminal. The authoritative local
routability suite passes `307/307`; the focused policy-v6 proposer,
corrected-audit, and atomic-merge suites pass `9/9`, `31/31`, and `5/5`.
Shell syntax and `git diff --check` are clean.

The 689 MiB remote `.test1-analysis.IOO7wK` diagnostic copy was removed after
its exact resolved path was checked. It contained only reproducible test1
summary/near-miss scratch data; canonical campaign evidence and all durable
status, selection, summary, and log artifacts were retained.

## Explicit GPUGR H/V congestion veto closure (2026-07-30)

A source-level check against the goal found that GPUGR already emitted six
explicit directional congestion-score metrics, but the absolute-directional
summary and selector did not retain them. The existing primary set covered H/V
overflow sums/bins, utilization p99/max, ACE, and router H/V congestion, but it
could not veto regressions in `horizontal_congestion_score`,
`vertical_congestion_score`, or their p95/p99 variants.

`tools/routability_summarize.py` now aggregates all six explicit H/V
congestion-score fields. `tools/routability_select_survivors.py` classifies
them as `absolute_directional_v2` primary objectives, so each must have full
case/seed coverage and a nonpositive worst-case delta. They also participate
in the independent GPUGR improvement constraint and Pareto objectives; RUDY
and GPUGR remain numerically separate. A regression injects an improved mean
with a `+0.1` worst-case horizontal congestion-score delta and proves that the
candidate is rejected.

The correction was deployed while the active missing-family runner was still
in `running_development`, before summarization or selection. Local hashes
`dfad7677ef14e3ba14a9f7085b725bb55dd70edf38defc5c09a9d633e9fa58ee`
for the summarizer and
`aca71ba1f9c6fa50562870742aa8cae9da51a6a64ef19b8a6526f5ff4b1358ca`
for the selector match `ceca2080x4`. The full local suite passes `307/307`;
local and remote selector, summarizer, and corrected-audit suites pass
`10/10`, `20/20`, and `31/31`, with compilation and `git diff --check` clean.

The same audit found that `tools/routability_analyze_near_misses.py` computed
frontiers with the selected profile's full vectors but serialized each
backend's `metrics` metadata from the legacy profile. Policy-v6 proposals did
not numerically mix those mislabeled vectors, but their provenance understated
the actual tuning objectives. The metadata now comes from the active profile's
constraints. An `absolute_directional_v2` regression requires the complete
directional metric list, including the six explicit H/V congestion scores.
The corrected analyzer hash is
`03c6ae5f5303f6183fff55b93334c30a97069cf9085cdb4d984de8cb77a518e9`
locally and remotely; its focused suite passes `6/6`, and the expanded full
local suite passes `308/308`.

The frozen-placement replay resume contract also lagged the selector profile.
It required only a hand-maintained subset of the absolute-directional metrics,
so a stale result without H/V congestion scores, overflow-bin counts, GPUGR
vias, or backend congestion score could be accepted as reusable and fail only
later during selection. `tools/routability_proxy_replay.py` now derives each
backend's required result metrics directly from the active profile's primary,
secondary, and backend diagnostic sets. Placement HPWL remains outside the
evaluator-result contract because it is verified through frozen placement
provenance. Missing any required metric now invalidates the cached result and
forces reevaluation rather than permitting partial evidence.

The corrected replay hash is
`bfe052b2de0f0cb3c2a8239a5edc4f3fe02d99dfe4db788af1ee5fab1c315624`
locally and on `ceca2080x4`. Its local and remote focused suite passes `6/6`;
the full local suite remains `308/308`, and the change was deployed before the
corrected replay stage started.

## Missing-family terminal result and policy-v6 retune (2026-07-30)

The original five-family development sweep completed all six test1/test2
case-seeds and all 30 variants with separate RUDY and GPUGR evaluation. The
family attestation passed, including exact case/seed, resolution, family, and
parameter-coverage evidence. The corrected strict selector retained `0/30`
methods. Sixteen variants were inactive in at least one comparison. Among the
remaining active methods, exclusions came from missing a RUDY primary
improvement and, for three pin-porosity/RouteForce rows, a positive worst-case
primary regression. All six explicit GPUGR H/V congestion-score metrics were
present in the primary objective set and audited with full six-comparison
coverage.

The development-only near-miss analysis selected exactly one policy-v6 parent
per family:

- `corrected_missing_00_00_route_inflation_global_weak`
- `corrected_missing_01_00_momentum_inflation_one_weak`
- `corrected_missing_02_00_path_inflation_one_very_weak`
- `corrected_missing_03_03_pin_porosity_two_balanced`
- `corrected_missing_04_04_routeforce_relative_03_static_anchor`

The resulting proposal audit passed with `80` variants, exactly `16` per
family, no held-out/golden evidence, and no numeric backend mixing. Every
family includes joint-gentle and joint-early-gentle variants plus its bounded
family-specific strength, schedule, cap/round, smoothing/momentum, or
RouteForce cadence/trust/decay changes. The first momentum joint-gentle smoke
placement completed but was `selected_no_activation`: its reduced step/cap
made no effective area change even though its parent was active. This is a
deliberately weak grid point, not accepted evidence; the full development
stage independently requires active placement provenance and will exclude it.

Remote chain PID `1871` advanced to
`running_missing_family_adaptive_v2`, and the adaptive runner entered
`running_development_atomic` on all four GPUs after a complete smoke campaign.
The original sweep ended with `completed_no_missing_family_survivor`; it is
not being promoted as a routability win.

## Policy-v6 live placement-effect audit (2026-07-30)

A live one-shot audit of the active policy-v6 development campaign separated
plugin execution from actual placement effect. Every completed momentum- or
path-inflation row whose machine-readable plugin summary reported a positive
activation produced a DEF with a different SHA-256 from the deterministic HPWL
placement for the same case and seed. Rows with a completed no-activation
summary were byte-identical to HPWL. One apparent inactive-but-changed row was
observed while its placement log was still being written; its terminal summary
subsequently reported a positive activation. Thus the completed active rows are
changing the emitted placement, while true no-ops remain excluded.

The adaptive and source campaign base configurations were compared as parsed
JSON and have zero differences after excluding only `result_dir`. Early proxy
comparisons against the source HPWL placements are therefore configuration-
matched. At the checkpoint with 31 policy-v6 methods complete on all three
test1 seeds, 25 were active in every test1 placement, one improved at least one
primary metric in both RUDY and GPUGR, and none satisfied the zero-positive-
worst-case primary gate. This is provisional test1-only evidence, not a
terminal selection: pin porosity, route inflation, RouteForce, all test2 seeds,
and the campaign-owned HPWL replay were still incomplete.

The one provisional dual-backend improver,
`adaptive_dev_0030_path_inflation_start_1`, reduced test1 seed-1000 RUDY p99
utilization by 6.30%, RUDY maximum utilization by 10.04%, GPUGR estimated
shorts by 18.47%, and both GPUGR directional congestion scores. It nevertheless
regressed GPUGR routed wirelength by 2.65%, overflow nets by 1.79%, and vertical
overflow by 43.78% on that seed; across the three test1 seeds it had 16 positive
worst-case primary regressions. It cannot pass the frozen selector in its
current form.

The area-inflation log audit also explains some inactive or redundant proposal
points. Caps below the implementation's `1e-4` relative-area effect threshold
produce no activation, while several one-at-a-time momentum changes remain
cap-limited and emit identical placements. A follow-up proposal policy should,
if policy v6 has no strict survivor, jointly tune the dependent area cap,
strength, round count, and `max_num_area_adjust` controls and sample active caps
immediately above the effect threshold. This follow-up must remain development-
only and retain the same separate-backend and zero-worst-regression gates.

## Coordinated policy-v7 follow-up prepared (2026-07-30)

The policy-v6 placement logs confirmed that the original one-at-a-time area
grid contains both sub-threshold no-ops and cap-limited variants whose changed
parameters do not change the emitted placement. An opt-in proposal policy v7
now addresses that specific tuning defect without changing the live v6 default.
For route inflation, momentum inflation, path inflation, and pin porosity, every
v7 proposal jointly sets strength, area cap, activation threshold, plugin round
count, and `max_num_area_adjust`. The smallest proposed cap is `1.25e-4`, above
the `RUPlaceInflation.apply_node_ratios` relative-effect floor of `1e-4`.
RouteForce retains its bounded joint strength, cadence, refresh, trust, and
decay grid.

A remote preview generated exactly 80 development-only variants from five
parents, 16 per family. Its audit reports policy version 7, no held-out or
golden evidence, no numeric backend mixing, coordinated area controls enabled,
and zero area rows at or below the effect floor. Policy v6 remains the proposer
default; v7 requires explicit `--proposal-policy-version 7`.

`tools/routability_audit_placement_effect.py` now independently hashes each
emitted plugin DEF against same-case, same-seed HPWL and rejects any placement
that reports a positive plugin activation but is byte-identical to HPWL. The
completed original five-family campaign passes this contract: 114 active rows
changed their DEF. It also records 36 inactive-identical and 30
inactive-changed rows; all inactive rows remain ineligible under the existing
every-case activation contract.

The separate policy-v7 runner is in
`corrected_missing_adaptive_v3_dev_3583ba6`. It consumes only the terminal v6
test1/test2 near-miss evidence, reruns all six development comparisons with
separate RUDY and GPUGR evaluation, applies the placement-effect audit, and
uses the unchanged `absolute_directional_v2` zero-positive-worst-case selector.
It contains no test3, real-design, OpenROAD, or Innovus input. Remote successor
PID `11034` is detached with phase `waiting_for_existing_chain_terminal` and
waits without polling for chain PID `1871`, preventing GPU contention with the
active policy-v6/downstream chain. The expanded local routability suite passes
`312/312`; remote focused proposer, placement-effect, and runner tests pass.

At the later policy-v6 checkpoint with 70 methods complete on all three test1
seeds, 61 were active on every test1 seed, nine improved at least one primary
metric in each backend, nine had no positive primary worst-case regression,
but those sets did not intersect: there were still zero strict test1 survivors.
The nine dual-backend improvers included path inflation, pin porosity, and
RouteForce, but each regressed 16-21 primary worst-case metrics. This remains
partial test1 evidence; the six-comparison selector is authoritative only after
the full development campaign terminates.

## Policy-v7 integrated contest successor (2026-07-30)

Policy-v7 survivors now have an automatic contest-validation path instead of
ending at development selection. The separate
`corrected_integrated_contest_v7_3583ba6` stage waits for terminal policy-v7
evidence, merges five independently audited atomic bundles (corrected replay,
regular adaptive-v2, original missing families, missing-family policy v6, and
missing-family policy v7), and builds compatible pairs only from strict
development survivors. Every pair is rerun on all six test1/test2 slots with
separate RUDY and GPUGR evaluation and the zero-positive-worst-case primary
gate before any held-out use.

After parameters are frozen, atomic and strict-pair survivors run on all three
test3 seeds. Development-pair and test3 campaigns also run the emitted-DEF
placement-effect audit. This stage contains no real-design, OpenROAD, or
Innovus metric, so test3 remains the first held-out contest evidence and cannot
influence tuning. Remote successor PID `31112` is detached with phase
`waiting_for_policy_v7_terminal` and waits without polling on policy-v7 PID
`11034`. Shell validation, the focused remote runner test, `git diff --check`,
and the expanded local routability suite (`313/313`) pass.

## Complete policy-v6 test1 diagnostic (2026-07-30)

All 80 policy-v6 variants and HPWL completed on each of the three test1 seeds.
Seventy-one variants activated on every test1 seed, 17 improved at least one
primary metric in both RUDY and GPUGR, and nine had no positive primary
worst-case regression, but the latter two sets did not intersect. There are
zero strict test1 survivors.

The mutually exclusive first-failure classification is:

- momentum inflation: 3 inactive, 13 without a RUDY primary improvement;
- path inflation: 3 inactive, 12 without a RUDY improvement, 1 with positive
  worst-case regressions;
- pin porosity: 13 without a RUDY improvement, 3 with positive worst-case
  regressions;
- route inflation: 3 inactive, 13 without a RUDY improvement;
- RouteForce: 3 without a RUDY improvement, 13 with positive worst-case
  regressions.

The closest dual-backend row by violation count was
`adaptive_dev_0078_routeforce_strength_x0.125`, but it still regressed 13
primary worst-case metrics; its largest regressions included GPUGR overflow
nets `+36.54%`, RUDY maximum utilization `+13.64%`, and GPUGR estimated shorts
`+11.31%`. The path-inflation `start_1` row regressed 16 primaries, including
GPUGR overflow nets `+63.46%` and routed wirelength `+5.09%`.

The frozen test1 placement-effect audit passes: all 213 active plugin
placements differ from HPWL, while all 27 inactive placements are
byte-identical to HPWL. Therefore the test1 failures are QoR failures rather
than hidden no-op or configuration-mismatch artifacts. Test2 remains required
for the authoritative six-comparison decision.

## Policy-v7 real-design and golden continuation (2026-07-30)

The policy-v7 chain no longer stops after contest test3. The shared real-proxy,
OpenROAD, Innovus, and final-audit runners now accept explicit campaign roots
while retaining their pre-v7 roots as defaults. A separate
`corrected_integrated_v7_continuation_3583ba6` chain consumes only terminal
`corrected_integrated_contest_v7_3583ba6` survivors, freezes them, screens them
on BP_quad/Mempool/NVDLA-L across seeds 1000/2000/3000, and reserves
OpenC910/XScore across the same seeds as real-design held-outs. RUDY and GPUGR
remain separate mandatory validators under `absolute_directional_v2` with zero
positive primary worst-case regression.

The real-design development and held-out campaigns now each run the emitted-DEF
placement-effect audit before selection, with expected comparison counts 9 and
6 respectively. Contest survivors that pass both real proxy gates proceed to
the existing common-backend OpenROAD test3 route and a new isolated Innovus 22
campaign over all five real designs and three seeds. The final audit preserves
routed wirelength, H/V congestion or overflow, DRC, shorts, unrouted nets,
connectivity violations, and opens as independent golden primary metrics.

The focused runner-contract suite passes `24/24`, and the full local
routability suite passes `314/314`; all modified and new shell scripts pass
`bash -n`, and `git diff --check` is clean. The parameterized
remote scripts were deployed to `ceca2080x4`. Remote continuation PID `42326`
is detached with phase `waiting_for_integrated_contest_v7_terminal` behind PID
`31112`. Local Innovus-v7 successor PID `1036360` is detached in a new session
with phase `waiting_for_remote_v7_chain_terminal`; after the remote chain it
also waits for legacy local Innovus chain PID `903940`, preventing concurrent
Innovus routing. These are orchestration results only. Policy-v6 test2,
policy-v7 development, real proxy selection, and both golden routes remain
unfinished, so no candidate has been promoted.

## Policy-v7 directional-area tuning correction (2026-07-30)

A tuning-space audit against the requested strength, cadence, annealing,
lifecycle, smoothing, and H/V controls found that the regular force-family
policy already covers proxy refresh, force application, annealing, smoothing,
net-weight phase, and absolute directional feedback. The queued policy-v7
route-inflation grid, however, inherited
`corrected_missing_00_00_route_inflation_global_weak`, whose actual preset has
only `ruplace_global_inflate_gamma=0.1` and no H/V inflation strength or mode.
Scaling only nonzero parent keys therefore left every proposed route-inflation
variant aggregate-only.

Before policy v7 started, its bounded route-inflation generator was corrected
to reserve four of the 16 family slots for explicit `max`, `mean`, horizontal,
and vertical H/V inflation. Each row injects a nonzero
`ruplace_hv_inflate_gamma` even when the parent omits that key. The proposal
manifest now attests `directional_area_feedback_tuned=true` and the exact four
modes, and the remote runner rejects a proposal set that does not satisfy this
contract. The candidate total remains 80, with 16 variants per missing family;
the held-out boundary and separate RUDY/GPUGR gates are unchanged.

The corrected proposer and policy-v7 runner were deployed while PID `11034`
was still in `waiting_for_existing_chain_terminal`, so no policy-v7 placement
used the older aggregate-only grid. The remote proposer suite passes `9/9`, the
local full routability suite remains `314/314`, shell syntax checks pass, and
`git diff --check` is clean. This establishes tuning coverage only; proxy and
golden QoR remain pending.

## Policy-v7 area-budget activation correction (2026-07-30)

The implementation audit also found that `max_num_area_adjust` was checked only
by DREAMPlace's legacy `routability_opt_flag` area-adjustment branch. The
RUPlace plugin branch calls `RoutabilityOptimizationPipeline.maybe_adjust_area`
directly and did not enforce that limit. Consequently, policy-v6/v7 proposal
manifests described `max_num_area_adjust` as a coordinated control even though
it was dormant on the executed plugin path.

The pipeline now supports an explicit total successful area-adjustment budget.
It is gated by the new `ruplace_enforce_area_adjust_budget` parameter, whose
default is zero to preserve every earlier candidate's audited semantics. All
policy-v7 coordinated area proposals set the flag to one. Momentum, path, and
pin-porosity proposal rounds equal the total pipeline budget. Route inflation's
round knob counts local passes after its mandatory global pass, so its total
budget is explicitly `ruplace_local_inflate_max_rounds + 1`. Pipeline summaries
now record whether the budget is active, the successful adjustment count, and
the effective maximum.

The policy-v7 runner activates the corrected pipeline and parameter schema only
after the existing chain terminates, and records source/install hashes. The
remote source was deployed while policy v7 remained `prepared_not_launched`;
byte comparisons confirm that the active policy-v6 installed pipeline and
schema were not changed. Remote plugin tests pass `29/29`, remote proposer tests
pass `9/9`, the local full routability suite passes `315/315`, shell syntax
checks pass, and `git diff --check` is clean. No proxy or golden conclusion is
drawn from this implementation correction.

The placement-effect audit was subsequently strengthened from configuration
intent to runtime proof. For every placement whose config enables
`ruplace_enforce_area_adjust_budget`, it now requires the parsed
`ROUTABILITY_PLUGIN_SUMMARY` to report `area_budget_enabled=1`, an effective
maximum equal to `max_num_area_adjust`, and a nonnegative successful-adjustment
count no larger than that maximum. Policy v7 requires this evidence for all
`384` area-family placements across its four 16-variant families and six
development slots before selection. The audit remains backward compatible for
older configs that do not opt into the new budget. The expanded local suite
passes `317/317`, the remote placement-effect suite passes `5/5`, and the
active policy-v6 installed sources remain unchanged.

The comparison parser was also updated to preserve this runtime evidence.
Previously it aggregated only the original objective, gradient, and area call
counters and would have discarded the new budget fields before the audit saw
them. It now retains every placement-stage budget observation and exposes
aggregate values only when the observations agree. The placement-effect audit
checks each observation independently, preventing multiple placement stages
from hiding a per-stage budget violation through summation. Local routability
tests pass `318/318`; remote placement-effect tests pass `5/5`, and the focused
remote parser-provenance test passes `1/1`. The remote full runner file still
has its known two environment-only errors because that host intentionally lacks
the local Innovus launcher files; no functional runner assertion failed.

## RouteForce gradient-convention audit (2026-07-30)

The remaining RouteForce sign question was resolved by tracing the complete
executed path rather than inferring direction from the plugin name. In Xplace's
`compGcellAdmmRouteForce`, a congested horizontal segment contributes a
negative x derivative to its left endpoint and a positive x derivative to its
right endpoint. Gradient descent therefore moves both endpoints inward and
reduces demand on that segment. The CUDA anchor term is
`anchor_weight * (position - anchor)`, so descent pulls a displaced node back
toward its anchor. Xplace adds this ADMM tensor positively to its placement
gradient before preconditioning, and DREAMPlace likewise adds it positively
before its own preconditioner and optimizer step.

Consequently, the plugin's sign is correct and was not changed. The backend and
plugin now document that the returned tensor is an objective gradient rather
than a displacement force. A focused regression supplies the analytical
two-endpoint kernel signs, passes them through the actual plugin scaling path,
performs one gradient-descent step, and requires the congested segment to
contract. This is source-level and optimizer-contract validation; proxy and
golden QoR remain governed by the running policy-v6/v7 campaigns.

At the 2026-07-30 06:20 SGT one-shot checkpoint, policy-v6 remained healthy
and active on `ceca2080x4`. All three test1 case-seeds had completed with return
code zero. Test2 retained 42, 19, and 24 complete method summaries for seeds
1000, 2000, and 3000 respectively, up from 38, 15, and 20 at the preceding
checkpoint; the campaign status contained zero failed jobs. Across the full
test1/test2 tree, all 328 summaries containing a GPUGR result also contained
`directional_metric_schema_version=2`, horizontal overflow metrics, and
vertical overflow metrics. Two additional files were active RUDY-only partial
summaries, not completed GPUGR rows with missing directional evidence.

The queued policy-v7 isolation contract also still held at this checkpoint.
Its proposal file had not yet been generated, and the remote source and
installed hashes for both `pipeline.py` and `params.json` remained different.
Thus the corrected area-budget implementation had not been activated early in
the policy-v6 process. Policy-v7, contest, real-proxy, OpenROAD, and final-audit
waiters were alive; both local Innovus successors were also alive and waiting.
The complete local routability regression suite, including the new RouteForce
direction test, passes `319/319`; Python compilation and `git diff --check`
pass. These facts establish implementation integrity and live progress only,
not a QoR winner.

## Policy-v7 effective refresh-cadence correction (2026-07-30)

A parameter-to-execution audit found one remaining alias in RouteForce cadence
tuning. The route refresh predicate is evaluated only when RouteForce itself is
applied, so the observable refresh cadence is the least common multiple of the
configured route and application intervals. With the policy-v6 parent values
`apply_freq=10` and `route_freq=50`, the nominal `route_freq=25` variant also
refreshes every 50 placement iterations and is behaviorally identical to its
parent along that dimension. Thus policy v6 contains 15 rather than 16
behaviorally distinct RouteForce configurations; this does not create a false
survivor, but it means that row is not independent tuning evidence.

The adaptive proposer now converts candidate refresh values to their effective
least-common-multiple cadence, rejects values equal to the parent's effective
cadence, removes duplicates, and observes the configured maximum. RouteForce
uses the same helper as the other force and net-weight families. Proposal
metadata records the exact
`lcm(refresh_interval,application_interval)` definition, and the queued
policy-v7 runner fails closed unless that attestation is present. A regression
reproduces the 25-versus-50 alias and requires every emitted RouteForce route
variant to have a different effective cadence.

The corrected proposer, test, and queued policy-v7 runner were deployed to
`ceca2080x4` with matching local/remote SHA-256 values while policy v7 remained
waiting behind policy v6. No installed placement source or active policy-v6
file was changed. The focused remote cadence and 80-row five-family proposal
tests pass `2/2`; the complete local routability suite passes `320/320`, shell
syntax and Python compilation pass, and `git diff --check` is clean. This is a
tuning-fidelity correction, not proxy or golden QoR evidence.

## Net-weight objective/preconditioner lifecycle correction (2026-07-30)

An optimizer-order audit found that legacy post-gradient net weighting changed
`data_collections.net_weights` after wirelength backward but before gradient
preconditioning. The current wirelength gradient was therefore computed with
the old net weights while the preconditioner divided it using the new weights.
That mixed two objective states in one optimizer step and could weaken or
distort net-weight tuning independently of the selected gamma.

The net-weight plugin now queues post-gradient targets. `PlaceObj` commits them
only after current-gradient preconditioning, so they affect the next objective
and its matching preconditioner. An explicit `pre_objective` mode remains
available when current-objective weighting is desired; it updates weights
before objective graph construction. Pipeline counters distinguish objective
and gradient phases, skipped refreshes clear queued targets, and a regression
proves the old/current versus next-objective behavior through actual autograd
values. The complete local routability suite passes `321/321`; Python
compilation, JSON parsing, shell syntax, and `git diff --check` pass.

Policy v7 now activates and hashes a single six-file lifecycle set only after
policy v6 terminates: `PlaceObj.py`, `plugin_base.py`, `pipeline.py`,
`proxy.py`, `net_weighting.py`, and `params.json`. The local Innovus runner applies the
same set only after its legacy-router capacity gate and before creating its
isolated Python package, preventing final source/install audits from mixing
optimizer semantics. Matching source, runner, and test hashes were deployed to
`ceca2080x4`; focused remote lifecycle tests pass `4/4` and both relevant
runner-contract tests pass. All six remote installed files remain different
from source while policy v6 is active, proving that the new implementation was
not activated early.

At the 2026-07-30 06:43 SGT one-shot checkpoint, policy v6 remained at `3/6`
complete case-seeds with all three Test2 jobs active. Complete Test2 method
summaries reached `53/81`, `32/81`, and `38/81` for seeds 1000, 2000, and 3000;
all `123` completed summaries had `ok` results for both RUDY and GPUGR. GPUs 0
and 3 were actively routing, and the policy-v7, contest, remote continuation,
and both local Innovus waiters remained alive. No proxy or golden winner is
claimed from this implementation correction or progress checkpoint.

The lifecycle defect also invalidates the admission evidence for net-weight
survivors produced before this correction. Policy v7 therefore now includes a
separate 64-point atomic `net_weighting` development sweep under the corrected
implementation. It crosses RUDY and GPUGR feedback, `post_gradient` and
`pre_objective` semantics, absolute and design-mean normalization, gamma
`0.005/0.025`, update intervals `10/40`, and activation thresholds `0.4/0.8`,
with a bounded maximum ratio of `1.25`. Every placement is evaluated by RUDY
and GPUGR separately on the six Test1/Test2 case-seeds and must pass the same
zero-worst-primary-regression gate. Test3, real designs, and golden routers are
not inputs to generation or selection.

Before integrated pair construction, a hash-bound filter removes only
pre-correction `net_weighting` survivors from the older replay and adaptive
development bundles. Other valid atomic survivors are preserved, and the new
corrected-lifecycle net-weight selection is merged as a sixth bundle. This
also prevents pairs from inheriting invalid old net-weight evidence. The
expanded local suite passes `326/326`; remote filter tests pass `4/4`, the
production-grid test passes `1/1`, policy-v7/contest/final-audit runner tests
pass `3/3`, and queued shell syntax checks pass. These files remain source-only
on `ceca2080x4` until policy v6 reaches an accepted terminal state.

After syncing the two inert local Innovus launcher files needed only by the
repository-wide orchestration inventory, the complete remote-discoverable
routability suite passes `320/320` under the remote Python environment. The
local suite remains `326/326` because the local worktree has six additional
test cases not discovered by the remote mirror. The count difference is test
availability, not a remote failure; all lifecycle, grid, filter, and runner
tests added for this correction are present and passing on both hosts.

## Net-weight active-mask normalization correction (2026-07-30)

A follow-up mathematical audit found that design-mean net-weight normalization
used every nonempty net, including one-pin and large-degree nets masked out of
DREAMPlace's wirelength objective. Congestion on an irrelevant masked net could
therefore change the scale and effective gamma applied to valid nets. Masked
nets could also receive unused weight updates, which made runtime ratio
statistics describe a larger population than the actual objective.

`net_weighting` now uses `net_mask_ignore_large_degrees` as the exact active
population for design-mean normalization, forces every inactive net's ratio to
one, and reports ratio/saturation statistics over active nets only. A regression
uses an extreme score on a masked net and proves that it neither changes the
valid-net scale nor receives a weight increase. The complete local routability
suite passes `327/327`; the remote plugin suite passes `32/32`.

The corrected source and test were deployed while policy v6 remained in
`running_development_atomic` and policy v7 remained `prepared_not_launched`.
Remote source SHA-256 is
`9efb96ac8c383ca3b95b4e979698008a91c6a8da70850f96cd6522b2b25bb1fc`, while
the active remote installed copy retains the earlier
`d2cfd683fb8778d04e638ef131e2c673377946b35442f708e52079b359f8779d` hash.
This proves the running policy-v6 placements were not modified. Policy v7 will
install and hash the active-mask-corrected source before the separate 64-point
net-weight lifecycle sweep begins.

The policy-v7 runner also performs the masked-net numerical example against
the newly installed package before generating any placement. It fails closed
unless the scale is exactly `2.0`, the valid-net ratios are `1.0/1.25`, and the
extreme masked net retains ratio `1.0`; successful evidence is retained in
`net_weight_active_mask_audit.json`. The updated runner passes local and remote
contract tests `25/25` and remained queued throughout deployment.

## Net-weight RUDY feedback isolation correction (2026-07-30)

The RUDY placement proxy previously retained the same mutable
`data_collections.net_weights` tensor used by the wirelength objective. After a
net-weight update, subsequent RUDY refreshes therefore amplified demand using
the weights that RUDY itself had caused. GPUGR does not consume those objective
weights, and the standalone final RUDY evaluator reconstructs original input
weights from the placed design. The RUDY-feedback variants consequently had a
backend-specific positive-feedback loop that was absent from both validators.

RUDY plugin feedback now owns an immutable clone of the input net weights.
Objective updates remain visible to wirelength and its matching preconditioner,
but cannot alter later congestion measurements. A direct regression changes
the live objective weights by `10x` after proxy construction and proves that
the RUDY signal remains at its original weighted demand. The policy-v7
installed-code audit repeats this example and records
`rudy_feedback_net_weights=frozen_input` before permitting any placement.

`proxy.py` was added to both remote policy-v7 and local Innovus lifecycle
activation/hash sets. The local routability suite passes `328/328`; remote
plugin and runner suites pass `33/33` and `25/25`. Remote proxy source SHA-256
is `c5fcc184244a7843ce1cfef0068903fbd06f6682d1a368e5af23efbeaaba8ade`,
while its installed copy remains different and policy v7 remains
`prepared_not_launched`. Policy v6 therefore stayed frozen, and only the new
64-point corrected net-weight sweep will provide admission evidence for this
feedback behavior.

## Corridor-aware net-weight scoring (2026-07-30)

The corrected lifecycle audit exposed a remaining mechanism weakness: a net's
congestion score was the mean utilization at its pin bins, so a hotspot inside
the routing corridor between otherwise uncongested endpoints was invisible.
`net_weighting` now supports an explicit `ruplace_net_weight_score_mode` with
the original `pin_mean` control and an exact `bbox_mean` alternative. The new
mode obtains per-net bounding boxes with GPU `scatter_reduce_` operations and
queries a 2D summed-area table, giving O(pins + routing bins + nets) work and no
per-net Python loop. A third `bbox_pmean` mode applies a numerically stable
fourth-power mean over the same box. It preserves a score of one on a uniform
utilization-one box while emphasizing localized hotspots that `bbox_mean` can
dilute. The default remains `pin_mean`; no prior preset changes semantics
implicitly.

A direct behavioral example places two pins in utilization-1 endpoint bins
around a 3-by-3 box containing a utilization-100 interior bin. `pin_mean`
returns `1.0`, while `bbox_mean` returns the exact box average `12.0`. The
implementation matches a naive random-rectangle reference within `7.15e-07`,
runs on both CPU and CUDA, and remained finite on a synthetic 300,000-net,
1,050,166-pin CUDA check. The complete local routability suite passes
`330/330`; remote plugin, preset-generator, and runner suites pass `35/35`,
`7/7`, and `25/25` respectively.

Policy v7 now uses `configs/routability_net_weight_corridor_v2.json` and expands
the corrected net-weight development matrix from 64 to 192 unique variants.
This is a paired factorial comparison of `pin_mean`, `bbox_mean`, and
`bbox_pmean` across both RUDY and GPUGR, both lifecycle phases, both
normalizations, both strengths, both update frequencies, and both activation
thresholds. Its installed-code audit fails closed unless the corridor example
produces `1.0`, `12.0`, and a larger peak-sensitive score, and records those
results in `net_weight_active_mask_audit.json` before placement.

The source-only deployment occurred while policy v6 remained
`running_development_atomic`, policy v7 remained `prepared_not_launched`, and
both gate PIDs 1871 and 11034 were alive. Remote `net_weighting.py` source now
has SHA-256 `cfe6134fd1d8e3e0a00a495123e3ab0b4f80bab2ad9e13398010711f0ecb8c23`
while its installed copy remains
`d2cfd683fb8778d04e638ef131e2c673377946b35442f708e52079b359f8779d`.
Remote `params.json` source/install hashes are respectively
`362711580578649bb36a5b6025ab89de5c6564cc02c1300f89c86638ce535114` and
`b5c515d3dbf3e248be8f87809d964526a7f2975e2299469bef230474ba6c49eb`.
All six lifecycle source/install pairs remain different, proving that the
active policy-v6 campaign was not modified; the queued policy-v7 runner will
install and attest the new source only after policy v6 reaches a terminal
state.

## Baseline-first campaign execution correction (2026-07-30)

A one-shot partial audit of policy v6 found no failed placement or evaluator
JSON, but also found that its sorted proposal JSON placed `hpwl` at method index
80. Candidate artifacts therefore accumulated without a same-seed baseline and
could not support valid partial deltas until the final method completed. The
same serialization behavior would have placed `hpwl` at index 192 in the new
net-weight sweep even though both Python generators construct it first.

The queued policy-v7 development and real-design runners now explicitly build
their method list as `hpwl` followed by every non-baseline method, independent
of JSON key order. Both fail closed unless the resulting execution string
matches `hpwl,*`. A production-spec check proves the serialized corridor file
has `hpwl` at index 192 while the execution list moves it to index 0 without
dropping or duplicating any of the 193 methods. Shell syntax and the remote
runner contract suite `25/25` pass. Only queued runner source changed; policy
v6 and the shared installed package remain untouched.

## Policy-v6 partial irreversible-elimination audit (2026-07-30)

The three complete Test1 development comparisons were summarized while the
three Test2 jobs continued. `tools/routability_audit_partial_elimination.py`
uses only completed development rows and cannot select or admit a method. It
classifies a candidate as irreversibly eliminated only when an already
observed primary worst-case delta is positive, or when the plugin was already
inactive in a completed comparison; both conditions make the frozen six-row
zero-regression/always-active gate impossible to recover. Missing baseline,
metric, or activation evidence remains indeterminate instead.

The retained artifact is
`corrected_missing_adaptive_v2_dev_3583ba6/development_atomic/partial_test1_snapshot/partial_elimination_audit.json`.
It proves that all 80 policy-v6 candidates are already ineligible: 71 have a
positive primary worst-case regression, nine were inactive in at least one
completed Test1 comparison, zero remain possible under the strict gate, and
zero are evidence-indeterminate. Family counts are momentum inflation 13/3,
path inflation 13/3, route inflation 13/3, pin porosity 16/0, and routeforce
16/0 for metric-regression/inactivation elimination.

All 71 active candidates regress GPUGR routed wirelength, estimated shorts,
overflow-net count, and RUDY maximum utilization on at least one Test1 seed.
The least broadly regressive candidate is
`adaptive_dev_0071_routeforce_joint_early_gentle`: it improves 17 GPUGR
congestion metrics on average but still has nine positive worst-case primaries,
including routed wirelength `+1.472%`, estimated shorts `+1.204%`, overflow
nets `+63.462%`, RUDY maximum utilization `+19.176%`, and RUDY p99 utilization
`+2.540%`. Its force is already capped at only `0.001875` of raw placement
gradient RMS, so blindly shrinking the coefficient is not supported as a
sufficient repair. The result instead supports the corrected lifecycle,
corridor-scoring, and coordinated-control investigation queued in policy v7.

This is not a final campaign selection and uses no Test3, real-design,
OpenROAD, or Innovus evidence. Policy v6 remains running because its Test2 rows
are still required for full six-comparison near-miss analysis and policy-v7
proposal generation. The partial auditor passes `4/4` focused tests, and the
complete local routability suite passes `334/334`.

## Directional routed-overflow contraction V41 (2026-07-30)

The independent `routed_overflow_net_contraction` mechanism reuses the pinned
GPUGR routed-segment contraction kernel without its ADMM anchor. Horizontal
overflow retains only x contraction, vertical overflow retains only y
contraction, and the cross-direction kernel responses are discarded. V41
swept relative force weights from zero through `0.004` on development-only
ISPD19 Test1 seed 1000. RUDY and GPUGR were evaluated and gated separately
under `absolute_directional_v2`; no Test3, real-design, OpenROAD, or Innovus
evidence was used.

The attested attempt-2 artifact is
`results/routability_local/routed_overflow_net_contraction_weight_pilot_v41_attempt2_3583ba6`.
The zero-weight control exactly reproduced HPWL, all eight nonzero candidates
activated and emitted distinct changed placements, the directional map schema
was `[2, 256, 256]`, and the pinned GPUGR binary SHA-256 was
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.
No candidate passed the strict proxy gate.

Weights `0.001` and `0.002` were the cross-backend near misses. Weight `0.002`
improved RUDY p99 utilization by `3.598%` and maximum utilization by `8.221%`
without a RUDY primary regression. It also improved GPUGR estimated shorts by
`4.386%`, vertical overflow sum by `56.032%`, vertical overflow-bin count by
`33.333%`, and maximum utilization by `3.180%`. It nevertheless regressed
GPUGR routed wirelength by `0.397%`, overflow-net count by `3.571%`, horizontal
p95 congestion by `0.208%`, horizontal maximum utilization by `0.225%`,
vertical ACE by `0.197%`, and vertical p95 congestion by `0.401%`.

Every V41 runtime had zero active horizontal overflow bins and at most four
active vertical bins. The HPWL evaluator map contained three positive vertical
overflow values near `0.023`, `0.047`, and `0.075`. Axis scaling is therefore
not an informative next variable, while threshold and exponent directly alter
which scarce vertical resources drive contraction. V42 holds weight `0.002`
and sweeps thresholds `0`, `0.02`, `0.04`, and `0.06` with exponents `1` and
`2`; the threshold-zero/exponent-one row must exactly reproduce the V41
near-miss placement before the new evidence is accepted.

## Directional routed-overflow contraction V42 (2026-07-30)

V42 completed all eight development-only Test1 seed-1000 placements and both
RUDY and pinned-GPUGR evaluations. Its original `failed_rc_1` terminal marker
was an overstrict audit failure, not a placement, evaluator, or provenance
failure: threshold `0.06` intentionally suppressed every active overflow bin
for both exponents. Reapplying the corrected audit to the preserved campaign
recorded six active changed placements and two inactive HPWL-identical rows,
with no inactive changed row. The threshold-zero/exponent-one control exactly
matched the V41 weight-`0.002` placement, and the GPUGR binary SHA-256 remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.
No placement or evaluation was rerun during recovery.

No V42 candidate passed the strict proxy gate. The V41 control remained the
only method on both the mean and worst-case cross-backend frontier, with 13
GPUGR mean improvements, six GPUGR worst-case primary regressions, two RUDY
improvements, and no RUDY regression. Threshold `0.02` with exponent `1`
worsened that balance to 12/7 GPUGR improvements/regressions; every other
active row introduced at least one RUDY regression or at least eight GPUGR
regressions. Threshold/exponent focusing therefore did not improve the V41
near miss and is closed without held-out or golden evaluation.

V43 keeps the V41 control settings and sweeps maximum routed-wire spans
`3`, `5`, `9`, and `19` against `uniform` and `inverse_sqrt` distance
weighting. The span-`19`/uniform row must exactly reproduce V41 weight `0.002`.
This tests whether limiting contraction to local routed segments avoids the
routed-wirelength and overflow-net regressions while retaining the proxy
congestion improvements.

## Directional routed-overflow contraction V43 (2026-07-30)

V43 completed all eight active, changed candidates on development-only Test1
seed 1000. The span-`19`/uniform control exactly reproduced the V41
weight-`0.002` placement, all RUDY and GPUGR evaluations passed provenance and
directional-schema checks, and the pinned GPUGR binary hash was unchanged. No
candidate passed the strict proxy gate, and no Test3, real-design, OpenROAD, or
Innovus evidence was used.

Uniform span `5` and span `9` produced the same placement and were the clear
near misses. They improved RUDY p99 utilization by `1.013%` and maximum
utilization by `2.567%` with no RUDY primary regression. They also improved 17
GPUGR primaries, including routed wirelength `0.033%`, estimated shorts
`4.100%`, overall p99 utilization `1.200%`, overall maximum utilization
`5.738%`, vertical overflow sum `97.546%`, and vertical overflow-bin count
`66.667%`. Three GPUGR primaries still regressed: overflow-net count by
`44.643%`, vertical peak congestion score by `0.473%`, and its identical p99
score by `0.473%`.

Uniform span `3` repaired routed wirelength, shorts, and overflow-net count but
introduced ten horizontal and peak-congestion regressions. Inverse-sqrt
weighting never improved the strict balance: span `5`/`9` added a RUDY maximum
utilization regression and span `19` had 12 GPUGR regressions. V44 therefore
closes inverse-sqrt weighting and sweeps weights `0.0005`, `0.001`, `0.0015`,
and `0.002` across the discrete span transition `3`, `4`, and `5`. The
span-`5`, weight-`0.002` row must exactly reproduce the V43 near miss.

## Directional routed-overflow contraction V44 (2026-07-30)

V44 completed all 12 active, changed Test1 seed-1000 candidates with a passing
control/provenance audit and no strict proxy survivor. Span `4` and span `5`
produced identical placements at every tested weight. Weight `0.002` exactly
reproduced the V43 three-regression near miss; lower weights were not a smooth
repair and produced between six and 14 GPUGR regressions. At weight `0.0005`,
overflow-net count was non-regressive and routed wirelength improved `0.660%`,
but estimated shorts regressed `6.494%` and ten congestion primaries regressed.
Strength-only tuning is therefore closed for this formulation.

The remaining V43/V44 near-miss failures are overflow-net count and the
vertical peak/p99 congestion score. The current directional implementation
contracts vertical routed segments along y but discards the native x response
from those same vertical-overflow resources. V45 adds a default-zero,
nonnegative orthogonal-spread scale that reverses this cross-direction response:
vertical hotspots retain y contraction while spreading affected nets in x,
and horizontal hotspots analogously spread in y. Scale zero must exactly
reproduce V44 span `4`, weight `0.002`; scales through `1.0` are screened only
on development Test1 before any held-out or golden use.

## Directional routed-overflow contraction V45 (2026-07-30)

V45 completed all seven active, unique Test1 seed-1000 placements with a
passing zero-scale control and provenance audit, but produced no strict proxy
survivor. Scale `0.03125` reduced the overflow-net regression from `44.643%`
to `5.357%`, but added routed-wirelength (`0.330%`), estimated-short (`3.105%`),
and vertical-ACE (`0.608%`) regressions. Scale `1.0` made overflow-net count
non-regressive and improved routed wirelength `0.351%` and shorts `6.090%`, but
introduced seven GPUGR regressions and a `4.464%` RUDY maximum-utilization
regression. Reversing cross-direction response is therefore closed.

V46 instead projects routed contraction node by node against DREAMPlace's
current placement-objective gradient. `node_nonopposing` projection removes
only a configurable fraction of a contraction component whose dot product
with the density/wirelength gradient is negative; aligned components remain
unchanged. Strength zero must exactly reproduce V45/V44. This directly tests
whether the three-regression near miss is caused by locally conflicting
placement and routing descent directions, without adding a second force or
mixing evaluator metrics.

## Directional routed-overflow contraction V46 (2026-07-30)

V46 completed all seven active, unique Test1 seed-1000 placements with a
passing zero-strength control and pinned-backend audit, but no strict proxy
survivor. Projection strength `0.125` retained routed-wirelength and short
improvements yet had five GPUGR regressions, while strength `0.75` repaired
overflow-net count but had seven GPUGR regressions. Strengths `0.25`, `0.5`,
and `1.0` also introduced a RUDY maximum-utilization regression. Node-wise
nonopposing objective projection is therefore closed.

The control runtime applies routed contraction only once, so V47 tests force
timing before changing the formulation again. It refreshes the route on every
20-iteration application opportunity and sweeps application intervals `20`,
`40`, `60`, `80`, `100`, and `120`. Because the legacy interval-`80` calls
occur only at multiples of both route frequencies, that row must exactly
reproduce V46 despite reducing the configured route-frequency modulus from
`80` to `20`.

## Directional routed-overflow contraction V47 (2026-07-30)

V47 completed all six Test1 seed-1000 placements and both proxy evaluations,
but its launcher intentionally failed closed during the final runtime audit.
The interval-`120` row reached one schedule opportunity after the useful
routed field had disappeared, so it remained inactive and exactly matched
HPWL. This violated the launcher's no-inactive-candidate contract; it was not
a placement, RUDY, GPUGR, provenance, or summarization failure. Five nonzero
rows were active and changed, and the pinned GPUGR binary remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.

No V47 candidate passed the strict proxy gate. Intervals `80` and `100` each
made one effective application and produced the same placement. The
interval-`80` row exactly reproduced V46. Both retained the V43/V44 result:
two RUDY improvements with no RUDY regression and 17 GPUGR improvements, but
overflow-net count regressed `44.643%` and vertical peak and p99 congestion
each regressed `0.473%`. Interval `60` applied once at a later iteration and
had nine GPUGR regressions plus one RUDY regression. Intervals `20` and `40`
made five and two effective applications and added routed-wirelength or wider
congestion regressions. Cadence and repeated application are therefore closed.

V48 adds default-preserving application-offset and maximum-application
controls to isolate a single fresh-route force at global placement iterations
`380`, `400`, `420`, `440`, and `460`. Every candidate uses interval `100`,
route frequency `20`, and a one-successful-application budget. Offset zero,
which applies at iteration `400`, must exactly reproduce the V47/V46 control;
offset `20`, which applies at iteration `420`, should reproduce V47 interval
`60`. Runtime telemetry records the configured phase, scheduled iteration,
and exhausted budget so timing is verified directly. This remains a
development-only Test1 screen; Test3, real designs, OpenROAD, and Innovus stay
held out unless a candidate passes both proxy gates without a GPUGR primary
regression.

## Directional routed-overflow contraction V48 (2026-07-30)

V48 completed all five placements and both proxy evaluations. Its original
launcher ended `failed_rc_1` because the final audit required every activated
candidate to produce a non-HPWL final DEF. The iteration-`460` row did apply a
nonzero force but legalization returned the byte-identical HPWL placement. The
placement-effect audit already recorded this as active-identical and the strict
selector excluded it for improving no primary metric. The campaign audit was
corrected to accept this case only when it is explicitly recorded and excluded;
the preserved campaign then passed without rerunning placement or evaluation.

Runtime telemetry proves exactly one application per candidate at iterations
`380`, `400`, `420`, `440`, and `460`. The iteration-`400` row exactly matched
V47 interval `80`, and iteration `420` exactly matched V47 interval `60`.
No candidate passed the strict proxy gate. Iteration `400` remained best with
two RUDY improvements and no RUDY regression, 17 GPUGR improvements, and the
same three vetoes: overflow-net count `+44.643%` and vertical peak/p99
congestion `+0.473%`. All other changed timings had at least one RUDY
regression and four to nine GPUGR regressions. Late single-application timing
is therefore closed.

V49 retains the iteration-`400` control and a one-application budget while
sweeping density-overflow activation thresholds `0.4`, `0.5`, `0.6`, `0.7`,
`0.8`, and `1.0`. This tests earlier route feedback without conflating timing
with repeated forces. The threshold-`0.4` row must reproduce V48 iteration
`400`. Runtime telemetry and the active-identical exclusion contract remain
mandatory. V49 is development-only Test1 screening; held-out and golden
validation remain prohibited without a strict RUDY and GPUGR survivor.

## Directional routed-overflow contraction V49 (2026-07-30)

V49 completed all six active, changed Test1 seed-1000 candidates with a
passing control, runtime, provenance, and pinned-backend audit. Thresholds
`0.4` and `0.5` both applied at iteration `400` and produced the same
placement; the `0.4` control exactly reproduced V48. Thresholds `0.6/0.7`
applied at iteration `300`, threshold `0.8` at `200`, and threshold `1.0` at
`100`. No candidate passed the strict proxy gate.

Earlier activation was uniformly worse. Iteration `300` had ten GPUGR
regressions, iteration `200` had eleven GPUGR and one RUDY regression, and
iteration `100` had nine GPUGR and one RUDY regression. The iteration-`400`
control remained the three-veto near miss. Activation timing is therefore
closed.

V50 isolates annealing of a second application. Every row applies the full
force at iteration `400`, then schedules a second fresh-route force at
iteration `440` with multipliers `0`, `0.025`, `0.05`, `0.1`, `0.15`, or
`0.2`. Decay zero is newly accepted as a default-preserving exact one-shot
schedule and must reproduce V48. The `0.2` row should reproduce V47 interval
`40`. A maximum of two successful applications and zero minimum ratio prevent
later force contributions. This remains a development-only Test1 screen.

## Directional routed-overflow contraction V50 (2026-07-30)

V50 completed all six active, changed Test1 seed-1000 placements and both
proxy evaluations with a passing runtime, provenance, control, and pinned
backend audit. No candidate passed the strict proxy gate. The decay-`0` row
made exactly one successful application and reproduced the V48 iteration-`400`
placement with DEF SHA-256
`950aa316be6329ebb2ae56aa5363ebb03aa672d795590d2cb6d676494a6cdc14`.
The decay-`0.2` row made two successful applications and reproduced the V47
interval-`40` placement with DEF SHA-256
`40aa1efa97da3edd53468083b904e293734e0a26a0e2f3131891046328cbe30a`.
The pinned GPUGR binary remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.

The one-shot control remained the best candidate: two RUDY improvements with
no RUDY regression and 17 GPUGR improvements, but overflow-net count regressed
`44.643%` and vertical peak and p99 congestion each regressed `0.473%`.
Decay `0.05` retained the same three veto classes and worsened vertical peak
and p99 congestion to `0.500%`; decay `0.1` reduced the overflow-net regression
to `23.214%` but introduced six GPUGR primary regressions. Decays `0.025`,
`0.15`, and `0.2` had 13, seven, and four GPUGR primary regressions,
respectively. Second-force annealing is therefore closed. The preserved
artifact is
`results/routability_local/routed_overflow_net_contraction_second_application_decay_pilot_v50_3583ba6`.

V51 returns to the one-shot iteration-`400` control and tests an independent
formulation change: replicate-padded box smoothing of each directional routed
overflow map before the native contraction gradient. Radius `0` must exactly
reproduce V48/V50. This remains development-only Test1 screening; held-out and
golden validation remain prohibited without a strict RUDY and GPUGR survivor.

## Directional routed-overflow contraction V51 (2026-07-30)

V51 completed all seven active, changed, unique Test1 seed-1000 placements and
both proxy evaluations with a passing runtime, provenance, control, and pinned
backend audit. Every radius made exactly one successful application at
iteration `400`. Radius `0` reproduced V48/V50 with DEF SHA-256
`950aa316be6329ebb2ae56aa5363ebb03aa672d795590d2cb6d676494a6cdc14`,
and the pinned GPUGR binary remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.
No radius passed the strict proxy gate.

Radius `0` remained the best valid RUDY/GPUGR balance with the original three
GPUGR vetoes. Radius `6` also had only three GPUGR veto classes, but reduced
the overflow-net regression only to `21.429%`, worsened vertical peak/p99
congestion to `0.781%`, and added a `2.362%` RUDY maximum-utilization
regression. Radius `3` removed the overflow-net veto but introduced six GPUGR
primary regressions plus a `16.890%` RUDY maximum-utilization regression.
Radius `8` removed the original overflow-net and vertical peak/p99 veto set but
replaced it with nine GPUGR regressions, including estimated shorts `7.544%`
and horizontal congestion score `0.949%`. Radii `1`, `2`, and `4` had nine to
11 GPUGR primary regressions. Replicate-padded spatial smoothing is therefore
closed. The preserved artifact is
`results/routability_local/routed_overflow_net_contraction_smoothing_radius_pilot_v51_3583ba6`.

V52 completes the untested directional-response range left by V45. V45 held
matching-axis contraction at `1.0` while increasing reversed cross-axis
spreading only through `1.0`, covering response ratios from pure contraction
to an equal 45-degree mix. V52 fixes orthogonal spreading at `1.0` and sweeps
matching-axis contraction through `1.0`, `0.75`, `0.5`, `0.25`, `0.125`, and
`0.0`; the last row is pure orthogonal relief. Matching scale `1.0` must
exactly reproduce V45 orthogonal scale `1.0`. This remains development-only
Test1 screening with no held-out or golden admission unless a strict proxy
survivor emerges.

## Directional routed-overflow contraction V52 (2026-07-30)

V52 completed all six active, changed, unique Test1 seed-1000 placements and
both proxy evaluations with a passing runtime, provenance, control, and pinned
backend audit. Matching scale `1.0` exactly reproduced V45 orthogonal-spread
scale `1.0` with DEF SHA-256
`8639682822cbdc12e88f12a69d44d35598dd1da96d454552376408a593144025`,
and the pinned GPUGR binary remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.
No response orientation passed the strict proxy gate.

Pure orthogonal relief at matching scale `0.0` improved 13 GPUGR primaries but
still had six GPUGR vetoes: routed wirelength `0.430%`, estimated shorts
`8.934%`, overflow-net count `69.643%`, vertical peak/p99 congestion `0.560%`,
and horizontal p95 congestion `0.238%`; it also had one RUDY primary
regression. Matching scale `0.75` was the only cross-backend mean/worst Pareto
intersection and had no RUDY primary regression, but still regressed nine
GPUGR primaries. The other intermediate orientations had 11 or 15 GPUGR
regressions. The 45-to-90-degree response range is therefore closed. The
preserved artifact is
`results/routability_local/routed_overflow_net_contraction_response_orientation_pilot_v52_3583ba6`.

V53 tests a structurally different routed-segment field. The sparse overflow
map is retained, while a default-zero blend adds continuous H/V utilization
pressure above `0.85` before invoking the same native routed-segment
contraction kernel. Scales `0`, `0.03125`, `0.0625`, `0.125`, `0.25`, `0.5`,
and `1.0` are screened. Scale `0` must exactly reproduce V48/V50/V51 radius
`0`. Unlike the earlier connection-routeforce pressure campaigns, this field
does not use the global DCT route-gradient kernel, via term, or repeated
application schedule. V53 remains development-only Test1 screening and cannot
admit held-out or golden work without a strict RUDY and GPUGR survivor.

## Directional routed-overflow contraction V53 (2026-07-30)

V53 completed all seven active, changed Test1 seed-1000 placements and both
proxy evaluations with passing placement-effect, runtime, provenance, control,
and pinned-backend audits. Scale `0` reproduced the V48/V50/V51 radius-`0`
control with DEF SHA-256
`950aa316be6329ebb2ae56aa5363ebb03aa672d795590d2cb6d676494a6cdc14`.
The pinned GPUGR binary remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.
No utilization-pressure scale passed the strict proxy gate.

The scale-`0` control remained the closest candidate, with the same three
GPUGR vetoes as V48: overflow-net count `+44.643%` and vertical peak/p99
congestion `+0.473%`. Scale `0.03125` reduced the overflow-net regression to
`+19.643%`, but introduced routed wirelength, estimated-short, horizontal-p95,
vertical-ACE, and larger vertical peak/p99 regressions. Scale `0.125` avoided
routed-wirelength, estimated-short, and overflow-net regressions but still
regressed five GPUGR utilization and congestion primaries. Larger scales
`0.5` and `1.0` again regressed routed wirelength and overflow-net count.
Near-capacity utilization-pressure blending is therefore closed. The preserved
artifact is
`results/routability_local/routed_overflow_net_contraction_utilization_pressure_pilot_v53_3583ba6`.

## Policy-v7 coordinated-area development result (2026-07-30)

The corrected policy-v7 coordinated-area campaign completed all six Test1/Test2
development comparisons with zero failed jobs. Its placement-effect audit
covered all `480` candidate placements: `472` were active and changed, one
RouteForce variant was active but byte-identical to HPWL, and seven emitted a
changed placement without satisfying the every-case activation contract. The
active-identical method
`adaptive_dev_0064_routeforce_joint_gentle` was explicitly recorded and proved
disjoint from the selected-method set; it was not silently admitted or treated
as an implementation failure.

No candidate among the 80 coordinated route-inflation, momentum-inflation,
path-inflation, pin-porosity, and RouteForce variants passed the unchanged
`absolute_directional_v2` selection contract. The selection used separate RUDY
and pinned-GPUGR decisions, required an improvement in each backend, and
allowed no positive worst-case regression across GPUGR routed wirelength,
estimated shorts, overflow nets, aggregate and directional overflow,
utilization, congestion scores, or ACE. The selected set is empty, so this
branch cannot advance to Test3, plugin-pair, real-design, OpenROAD, or Innovus
validation. The corrected net-weight lifecycle branch remains a separate
running policy-v7 development campaign and is not covered by this conclusion.

## Policy-v7 successor-chain recovery (2026-07-30)

The first recovery covered PID identity but missed a prerequisite-state
failure. The corrected replay root was `failed_rc_1` after its original source
union rejected inactive method
`adaptive_dev_0003_local_gradient_start_0.6`; its subsequently patched
inactive-method filter had never been rerun. The GPUGR proxy-coverage root was
still `waiting_for_exclusive_gpu_capacity` with no development campaign, and
adaptive-v2 consequently remained `waiting_for_corrected_replay_terminal`.
The first recovered contest waiter would therefore have failed immediately
after policy v7 despite being attached to the correct PID.

The contest launcher now serializes the missing breadth-validation prerequisites
after policy v7 releases the four GPUs: GPUGR proxy coverage, activation-clean
corrected replay, adaptive-v2 development, then integrated contest/pair/Test3.
Each prerequisite is skipped only with an accepted terminal phase, otherwise
it is run and its terminal phase is checked before advancing. Proxy coverage
and adaptive-v2 now use content-checked `--resume`; corrected replay already
did. Replay's legacy minute polling loop was replaced by a one-shot deferred
terminal check. Replay now also independently requires a terminal GPUGR
proxy-coverage phase before constructing its frozen source union, rather than
trusting only the caller's ordering. Adaptive-v2 accepts `REPLAY_PID=none` only
for a caller that has already verified replay terminal evidence.

The obsolete waiter process groups `11392/11394`, `12664/12666`, and
`2748956/2748958` were terminated without touching policy-v7 PID `66351` or
legacy Innovus PID `1005556`. The replacement detached, fail-closed chain is:

- remote contest/prerequisite launcher PID `5201`, waiting on policy-v7 PID
  `66351`;
- remote continuation launcher PID `5563`, waiting on contest PID `5201`
  before real proxy, OpenROAD, and remote audit;
- local Innovus launcher PID `2793003`, waiting on remote continuation PID
  `5563` and then legacy Innovus PID `1005556`.

The deployed remote scripts are SHA-256 identical to the locally tested
copies. Shell syntax, `git diff --check`, the runner suite (`28/28`), and the
source-union suite (`15/15`) pass. Immediate status and PID-command checks show
all three replacement waiters attached to the intended predecessors with
empty recovery logs. These are orchestration results only: the corrected
net-weight lifecycle development sweep remains active, and no held-out or
golden candidate has been promoted.

An explicit survivor-bundle audit also confirmed that the completed missing
families, missing-families adaptive-v2, and policy-v7 coordinated-area
selections each contain zero selected methods. They therefore contain no
superseded `net_weighting` survivor that could bypass the replay/adaptive
filters during the eventual six-bundle merge.

## Corrected net-weight partial development diagnostic (2026-07-30)

A read-only snapshot of the still-running corrected net-weight lifecycle
campaign examined the common completed Test1 prefix across seeds `1000`,
`2000`, and `3000`. At 109 completed candidate methods plus the same-seed HPWL
baseline, all rows had both RUDY and pinned-GPUGR results and none was evidence
indeterminate. Zero candidates could still satisfy the proxy contract. This
was diagnostic-only: it used no Test2, Test3, real-design, OpenROAD, or Innovus
evidence and made no selection or admission decision.

The earlier apparent near miss
`corrected_net_weight_corridor_0030_rudy_net_weighting` has five GPUGR veto
metrics, but its plugin was inactive on Test1 seed `3000`, so it is already
ineligible. The best always-active candidate in that snapshot was
`corrected_net_weight_corridor_0008_rudy_net_weighting`; it improved one RUDY
and 16 GPUGR primaries on average but retained nine GPUGR worst-case vetoes,
including estimated shorts, overflow-net count, utilization, horizontal p95,
vertical ACE, and vertical peak/p99 congestion.

A subsequent grouping snapshot at 111 common candidates identified the best
completed region as RUDY feedback, `pre_objective`, `bbox_mean`, absolute
normalization, gamma `0.005`, update frequency `10`, and activation threshold
`0.4`. The installed active-mask audit passed: it recorded `pin_mean=1.0`,
`bbox_mean=12.0`, a larger `bbox_pmean`, correct active-net masking, a bounded
`1.25` ratio, and frozen RUDY feedback input. This rules out the corrected
active-mask/lifecycle implementation defect, but does not establish QoR. The
remote six-comparison campaign and its successor chain remain active.

## Net-weight low-strength pilots V54-V56 (2026-07-30)

V54-V56 performed 15 additional development-only Test1 seed-`1000` placements
around the best partial net-weight region. Every candidate activated, every
DEF differed from HPWL, both RUDY and GPUGR evaluations completed, and each
pilot's placement-effect, source/install, snapshot, and pinned-backend audits
passed. The GPUGR binary SHA-256 remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.
No held-out or golden evidence was used, and all three strict survivor sets are
empty.

V54 swept gamma from `0.0005` through `0.005`. Gamma `0.001` was the closest
cross-backend point, with 13 GPUGR mean improvements and one RUDY improvement,
but six GPUGR primary regressions remained. Gamma `0.002` had 14 GPUGR
improvements and the same six-regression count but failed to improve any RUDY
primary.

V55 swept `0.00001` through `0.00025`. Gamma `0.000025` improved GPUGR routed
wirelength by `0.170%`, estimated shorts by `7.356%`, vertical overflow amount
by `57.214%`, and 11 GPUGR primaries in total while improving RUDY p99 by
`0.745%`. It still regressed overflow-net count by `7.143%`, horizontal
peak/p95/p99 congestion by about `0.149%`, vertical peak/p99 congestion by
`0.260%`, and vertical p95 congestion by `1.605%`; RUDY maximum utilization
also regressed `1.688%`.

V56 refined `0.000015` through `0.00004` around that point. Its best rows still
had seven GPUGR veto metrics, and no row improved on V55's gate balance. Scalar
gamma refinement below `0.005` is therefore closed for this fixed
RUDY/`pre_objective`/`bbox_mean`/absolute/frequency-`10` region. No V54-V56
candidate may enter multi-seed, held-out, pair, OpenROAD, or Innovus validation.
The next decision must use the terminal six-comparison corrected net-weight
campaign; if that selection is empty, further work must change the mechanism
or feedback formulation rather than continue nearby gamma mining.

## Congestion net-relaxation plugin and V57-V59 (2026-07-30)

`net_relaxation` is a separate, default-off objective plugin that reduces
wirelength weights only for active nets whose congestion score exceeds the
selected normalization reference. It reuses the corrected net-score and
pre-/post-objective lifecycle machinery, but owns an independent parameter
namespace and a positive weight floor. The registry rejects selecting it with
`net_weighting` because both mutate the same objective tensor. The operation
is documented as an inverse-response ablation rather than a reproduction of a
published method.

Unit coverage proves active-net masking, exact ratio/floor behavior,
independent parameters, lifecycle execution, registry generation, and mutual
exclusion. The plugin and preset-generator suites pass `74/74` and `24/24`.
All three pilots used isolated source/install snapshots, separate RUDY and
GPUGR evaluators, and pinned GPUGR SHA-256
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.
No Test3, real-design, OpenROAD, or Innovus evidence was used.

V57 swept gamma `0.005`, `0.025`, `0.1`, and `0.5` with minimum weight floors
`0.5/0.75` under RUDY `bbox_mean` absolute feedback. All eight placements
activated and changed, but the floor pairs were byte-identical, their
saturated fraction was zero, and mean ratios remained near one. Gamma `0.005`
was best with two RUDY improvements, no RUDY regression, and 12 GPUGR
improvements, but six GPUGR primary regressions remained. The floor dimension
is therefore non-causal over this range, not eight independent observations.

V58 fixed the floor at `0.5` and crossed gamma `0.5/2.0`, absolute/design-mean
normalization, and `bbox_mean/bbox_pmean`. All eight candidates activated and
changed. Observed minimum ratios reached `0.648` under absolute normalization
and the `0.5` floor under design-mean normalization, proving that the inverse
response was materially exercised. The best row, gamma `2.0`, absolute
`bbox_mean`, improved 13 GPUGR primaries but retained six GPUGR vetoes and one
RUDY regression. V58 selected zero of eight candidates.

V59 used pinned-GPUGR feedback and crossed gamma `0.5/2.0` with `max_hv`,
horizontal-only, and vertical-only scoring. Four candidates were active and
changed. Both horizontal-only rows were inactive and HPWL-identical because
the absolute horizontal field did not exceed the relaxation threshold. The
best active row, `max_hv` at gamma `0.5`, improved 12 GPUGR primaries but still
regressed routed wirelength, estimated shorts, horizontal p95 congestion,
vertical overflow amount/route congestion, and vertical ACE. V59 selected zero
of six candidates.

The V57-V59 survivor sets are all empty. `net_relaxation` therefore remains a
tested, default-off plugin but is closed for promotion: it cannot enter
multi-seed, held-out, pair, OpenROAD, or Innovus validation. These negative
results do not alter the still-running corrected net-weight policy-v7 campaign
or its serialized successor chain.

## Directional path-spreading development result (2026-07-30)

The development-only directional path-spreading work completed its strong and
weak scalar-force sweeps on Test1 seed `1000`.  The final weak sweep evaluated
weights `0.0003125`, `0.000625`, and `0.0009375`; every plugin activated, every
candidate DEF differed from HPWL, and all four RUDY and four pinned-GPUGR
records were valid.  The directional schema-v2 map audit passed with shape
`[2, 256, 256]`, and no held-out or golden evidence was used.

All three weak candidates improved at least one primary metric in each proxy,
but none passed the no-regression contract.  Weight `0.0003125` regressed
GPUGR estimated shorts by `4.099%`, overflow-net count by `10.714%`, and
maximum utilization by `8.034%`, while RUDY maximum utilization regressed
`12.771%`.  Weight `0.000625` regressed GPUGR estimated shorts by `11.560%`,
overflow-net count by `8.929%`, and maximum utilization by `2.553%`, with
additional directional regressions.  Weight `0.0009375` regressed GPUGR routed
wirelength by `0.371%` and vertical congestion by `0.355%`, while RUDY maximum
utilization regressed `18.178%`.  The strict survivor set is empty, so nearby
scalar-strength tuning for `directional_path_spreading` is closed and the
plugin cannot enter multi-seed, held-out, pair, OpenROAD, or Innovus stages.
The preserved artifact is
`results/routability_local/directional_path_spreading_weak_pilot_3583ba6`.

## Directional net-contraction V60 (2026-07-30)

V60 completed all 24 Test1 seed-`1000` candidates spanning shared
`design_mean` normalization, `max_hv`/vertical response, smoothing radii `0/1`,
weights `0.0025/0.005/0.01`, and start-overflow thresholds `0.3/0.4`.  All 24
plugins activated, all 24 candidate DEFs changed from HPWL, and all 25 DEFs
including HPWL had distinct SHA-256 hashes.  Both proxy evaluations, the
placement-effect audit, isolated source/install audit, and pinned-GPUGR check
passed.  The GPUGR SHA-256 remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.

No V60 candidate passed the strict proxy gate.  The two closest rows each had
three GPUGR primary vetoes.  The smoothed `max_hv`, weight-`0.0025`,
start-`0.4` row improved 17 GPUGR primaries and two RUDY primaries with no
RUDY regression, but regressed estimated shorts by `4.514%`, overflow-net count by
`26.786%`, and vertical p95 congestion by `2.285%`.  The matched vertical-only
row improved 16 GPUGR primaries, including routed wirelength by `0.184%`,
estimated shorts by `6.324%`, overflow-net count by `3.571%`, and vertical
overflow by `100%`; it still regressed vertical peak/p99 congestion by
`0.464%` and vertical p95 congestion by `2.189%`.  V60 therefore selects zero
of 24 candidates and cannot advance.  Its preserved artifact is
`results/routability_local/directional_net_contraction_pilot_v60_3583ba6`.

## Directional net-contraction per-axis normalization V61 (2026-07-30)

V61 tested a matched implementation change rather than another scalar sweep.
The new `axis_mean` mode normalizes horizontal and vertical net scores by their
own active-net means before applying `max_hv` selection or a single-axis
response.  This avoids using one shared threshold on routing stacks whose H/V
score distributions differ.  Telemetry proved the mechanism was active: the
horizontal-to-vertical score-scale ratio ranged from `1.274` to `1.294`, and
the 12 `max_hv` rows averaged approximately `915` active horizontal nets and
`1096` active vertical nets, compared with roughly `1592/650` in the first
matched V60 shared-scale row.

All 24 V61 candidates activated, changed placement, produced unique DEFs, and
completed both proxy evaluations.  The source/install, placement-effect, JSON,
and pinned-GPUGR audits passed, and no held-out or golden evidence was used.
No candidate passed the strict gate.  The closest two vertical-only rows each
retained five GPUGR vetoes.  At weight `0.0025`, start `0.4`, and smoothing `0`,
the regressions were routed wirelength `0.266%`, estimated shorts `12.506%`,
overflow-net count `51.786%`, horizontal maximum utilization `5.274%`, and
vertical p95 congestion `2.343%`.  Weight `0.005` retained routed-wirelength,
short, overflow-net, and vertical peak/p99 regressions.  V61 is therefore worse
than the three-veto V60 near misses and selects zero of 24 candidates.
Per-axis normalization remains available as a default-off control, but this
matched region is closed for multi-seed, held-out, pair, OpenROAD, and Innovus
promotion.  The preserved artifact is
`results/routability_local/directional_net_contraction_axis_mean_pilot_v61_3583ba6`.

## Directional net-contraction weak and boundary sweeps V62-V63 (2026-07-30)

V62 swept six vertical-only shared-mean weights from `0.00015625` through
`0.0025` with smoothing `1` and start overflow `0.4`.  V63 then tested six
interior weights between `0.001875` and `0.0025` plus both endpoints.  All 14
candidate runs activated and changed placement, both proxy evaluations
completed, and the `0.001875` and `0.0025` V63 controls exactly reproduced the
corresponding V62 DEF SHA-256 values.  The pinned GPUGR hash remained
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.

Neither sweep produced a strict survivor.  The original selector correctly
excluded every row but reported only the first failed gate, which initially
hid GPUGR vetoes when a row also lacked a RUDY improvement.  The selector now
evaluates all metric gates independently after coverage and activation pass;
its decisions are unchanged, while each exclusion lists both backend-
improvement and GPUGR-regression failures.  Comprehensive selections and tool
hashes are preserved beside the original pilot selections.

With complete diagnostics, weight `0.001875` fails the RUDY improvement gate
and has eight GPUGR vetoes, including routed wirelength `0.472%`, estimated
shorts `8.188%`, overflow-net count `23.214%`, and vertical maximum utilization
`2.278%`.  Every V63 interior point has at least six GPUGR vetoes.  The best
V62/V63 row remains the exact `0.0025` V60 control with three vertical-
congestion vetoes.  Scalar tuning below `0.0025` is therefore closed for this
fixed vertical/shared-mean/smoothing-`1`/apply-`20` lifecycle.  No V62/V63 row
may advance to multi-seed, held-out, pair, OpenROAD, or Innovus validation.
The preserved artifacts are
`results/routability_local/directional_net_contraction_weak_pilot_v62_3583ba6`
and
`results/routability_local/directional_net_contraction_boundary_pilot_v63_3583ba6`.

## Directional path-spreading axis sweep V64 (2026-07-30)

V64 reopened this mechanism only for a bounded structural check after the
scalar sweep had closed.  It crossed `both`, horizontal-route-only, and
vertical-route-only response modes with utilization thresholds `0.4/0.6/0.8`
and relative force weights `0.0003125/0.0009375`, while fixing smoothing `2`,
power `2`, apply/refresh interval `20`, decay `0.8`, start overflow `0.4`, and
maximum relative force ratio `0.02`.  All 18 candidates activated, all 18 DEFs
changed from HPWL, and all 19 DEFs including HPWL had distinct SHA-256 hashes.
Both proxy evaluations and the placement-effect audit passed with pinned GPUGR
SHA-256
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`.

The plugin now reports separate x/y field norms.  A complete replay proved the
mode wiring in the live placement path: all six `both` rows had nonzero x and
y norms, all six horizontal-route rows had exactly zero x norm and nonzero y
norm, and all six vertical-route rows had nonzero x norm and exactly zero y
norm.  The replay reproduced all 19 DEF hashes, all 136 non-runtime fields in
the 57 placement/RUDY/GPUGR records, and the selection JSON exactly; only wall-
clock runtime columns differed.

V64 selected zero of 18 candidates.  The closest row was the exact scalar-
sweep control at mode `both`, threshold `0.6`, and weight `0.0009375`.  It
improved 17 GPUGR primary metrics but retained three vetoes: routed wirelength
`+0.371%`, vertical peak congestion `+0.355%`, and the identical vertical p99
congestion ratio `+0.355%`.  It also retained a RUDY primary improvement, so
the exclusion is specifically the GPUGR no-regression gate.  Horizontal-only
and vertical-only response did not reduce the veto count below this control.
No V64 row may advance to multi-seed, held-out, pair, OpenROAD, or Innovus
validation.  The original and telemetry-replay artifacts are
`results/routability_local/directional_path_spreading_axis_pilot_v64_3583ba6`
and
`results/routability_local/directional_path_spreading_axis_pilot_v64_telemetry_3583ba6`.

V65 completed a bounded interpolation around the three-veto V64 control.  It
crossed thresholds `0.5/0.55/0.6/0.65/0.7` with weights
`0.00075/0.000875/0.0009375/0.001/0.001125`, includes the exact V64 control,
and kept every other lifecycle parameter fixed.  All 25 candidates activated,
changed placement, produced unique candidate DEF hashes, and completed both
proxy evaluations.  The exact control reproduced the V64 DEF hash
`4cdcf4e519fa38aca272cb4e84c9823d64dbe164519797e34b41c8fefc7e9d4e`.

V65 selected zero of 25 candidates.  The exact V64 control remained the only
three-veto row; every interpolated point retained at least four GPUGR primary
regressions.  The next closest row, threshold `0.65` and weight `0.001125`,
regressed overflow-net count by `5.357%`, vertical peak/p99 congestion by
`0.248%`, and vertical p95 congestion by `1.114%`.  Threshold/weight
interpolation is therefore closed.  The preserved artifact is
`results/routability_local/directional_path_spreading_fine_pilot_v65_3583ba6`.

V66 completed the bounded lifecycle check for this plugin.  At the fixed V64
control response it crossed proxy refresh and force-application intervals
`10/20/40` with decay `0.5/0.8/1.0`, including the exact V64 lifecycle.  All 27
candidates activated and changed from HPWL.  Apply intervals `10/20/40`
produced `13/6/3` force applications, and decay `0.5` reached the configured
`0.2` floor while decay `1.0` remained at full strength.

The 27 configurations produced 18 distinct candidate DEF hashes for an
expected causal reason.  Refresh `10` and `20` are equivalent at apply interval
`20`, and all three refresh values are equivalent at apply interval `40`,
because the plugin requests a route only on a scheduled force iteration.  At
apply interval `10`, refresh `10/20/40` produced `13/7/4` route snapshots and
distinct placements.  The exact control again reproduced hash
`4cdcf4e519fa38aca272cb4e84c9823d64dbe164519797e34b41c8fefc7e9d4e`.

V66 selected zero of 27 candidates.  The exact control retained its routed-WL
and vertical peak/p99 congestion vetoes.  A distinct refresh-`40`, apply-`10`,
decay-`0.8` row also had three vetoes, but regressed aggregate maximum
utilization by `2.897%`, horizontal maximum utilization by `6.312%`, and
horizontal p95 congestion by `0.184%`.  No lifecycle row may advance.  The
preserved artifact is
`results/routability_local/directional_path_spreading_lifecycle_pilot_v66_3583ba6`.

V67 completed the final activation-timing check, sweeping global placement-
overflow start thresholds `0.2/0.3/0.4/0.5/0.6` around the unchanged V64
response and lifecycle.  All five candidates activated, changed placement,
produced unique candidate DEF hashes, and completed both proxy evaluations.
The start threshold materially changed the lifecycle: the five rows applied
the force `3/5/6/9/12` times respectively, and the `0.4` control again
reproduced hash
`4cdcf4e519fa38aca272cb4e84c9823d64dbe164519797e34b41c8fefc7e9d4e`.

V67 selected zero of five candidates.  The `0.4` control remained best with
three GPUGR vetoes; every other start point retained at least six.  Start
`0.2` had 13 vetoes, `0.3` had 16, `0.5` had eight, and `0.6` had six.  The
artifact is
`results/routability_local/directional_path_spreading_start_pilot_v67_3583ba6`.

Directional path spreading is therefore closed for promotion.  Across the
strong/weak scalar sweeps and V64-V67, the investigation exercised force
strength, smoothing, directional and global activation thresholds, H/V
response mode, proxy refresh, force-application interval, decay, and start
timing.  No row satisfied the separate RUDY-improvement and zero-GPUGR-
regression contract, so none may enter development multi-seed, held-out,
combination, OpenROAD, or Innovus validation.

## GPUGR per-ABI identity contract (2026-07-30)

The remote corrected net-weight campaign was initially described using the
local frozen GPUGR SHA-256 even though `ceca2080x4` cannot load that CPython
3.8 extension.  Live import-resolution checks proved the actual identities:

- local CPython 3.8 uses
  `6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`;
- `ceca2080x4` CPython 3.9 uses
  `8994ac6f1ff2086d149205b0e7f9d2876c4d91e2c4bbd81d39a495449b8b0dc1`.

The source trees are not byte-identical.  Their two differing files comprise
an old-GCC filesystem compatibility shim and the local native route-gradient
API/negative-span changes.  Therefore the two binaries are not claimed to be
generally interchangeable for native route-gradient optimization.

A controlled evaluator replay used byte-identical ISPD19 Test1 seed-`2000`
placement and LEF inputs, routing grid `256x256`, one RRR pass, and directional
schema v2.  The complete serialized GPUGR tensor files were byte-identical.
Aggregate utilization/overflow and H/V utilization/overflow maps had zero
mismatches, and every non-runtime metric was exactly equal, including routed
wirelength, estimated shorts, overflow-net count, horizontal/vertical
congestion, and vias.  This proves evaluator and proxy-map equivalence for the
replayed contract used by net weighting; it does not prove arbitrary native
route-gradient equivalence.

`tools/routability_evaluate.py` now records the native extension selected for
the active Python ABI plus content hashes for every evaluator input.  The
separate `tools/routability_audit_gpugr_identity.py` operation enforces equal
request content, all four exact maps, and exact non-runtime metrics while
retaining the narrower equivalence scope.  Its durable passing report is
`results/routability_local/gpugr_abi_identity_replay_20260730/gpugr_abi_identity_audit.json`.
The remote corrected campaign is henceforth attributed to the CPython 3.9
`8994ac6f...` backend, not the local `6d543649...` binary.

## Net-weight trust-region diagnostic V68 (2026-07-30)

V68 tested whether the seed-`2000` Test1 net-weight candidate's displacement
direction was useful at a smaller step than the optimizer emitted.  The
baseline-anchored DEF operation evaluated alpha values `0.03125`, `0.0625`,
`0.125`, `0.25`, `0.5`, `0.75`, and `0.875` with separate RUDY and GPUGR
evaluations.  A terminal `absolute_directional_v2` audit covers all seven
placements and selects zero proxy or promotion survivors.

Alpha `0.0625` was closest: GPUGR routed wirelength improved by `385` database
units and overflow-net count by `15`, while estimated shorts regressed by
`78.817` and horizontal p95 congestion by `0.002034`.  RUDY maximum utilization
improved by `0.003923`, but RUDY p99 utilization regressed by `0.004186`.
Every other alpha retained between three and eleven GPUGR primary vetoes.

All seven blends also recorded `3365` candidate/baseline orientation
mismatches among `8879` components.  V68 deliberately preserved baseline
orientations to isolate displacement response; it is therefore a diagnostic,
not a legal placement method, even independent of the failed proxy gate.  The
operation remains default-off and cannot enter held-out, pair, OpenROAD, or
Innovus validation.  The compact artifact is
`results/routability_remote/trust_region_blend_v68_3583ba6/seed_2000/trust_region_audit.json`.

At the latest live refresh, the corrected net-weight Test2 workers remained
healthy and had completed `126/193`, `98/193`, and `100/193` evaluations for
seeds `1000`, `2000`, and `3000`, respectively.  Test1 remains terminal at
`3/3` seeds and eliminates all `192` candidates under the strict gate.  The
six-comparison campaign is still allowed to finish for terminal mechanism
diagnostics and does not authorize held-out or golden promotion.

## Virtual-cell and directional virtual-cell pilots V69-V71 (2026-07-30)

V69 added a separate default-off `virtual_cell` mechanism approximation for
the 2025 DAC differentiable net-moving work.  It samples a Poisson congestion
field at conceptual two-pin-net midpoints and transfers the same translation
force to both movable endpoints.  The development-only Test1 seed-`1000`
pilot crossed RUDY/GPUGR feedback, weights `0.001/0.0025/0.005`, and absolute
utilization thresholds `0.8/1.0`.  Nine of 12 rows activated and changed DEF;
the three GPUGR threshold-`1.0` rows correctly reported no activation and were
byte-identical to HPWL.  No row passed the strict gate.  The closest RUDY
rows remained Pareto diagnostics only and retained GPUGR horizontal-p95,
short, overflow-net, or directional-tail vetoes.  The preserved artifact is
`results/routability_local/virtual_cell_pilot_v69_3583ba6`.

The V69 audit exposed two formulation limits: aggregate feedback discarded
GPUGR's H/V maps, and incident virtual-net forces were averaged at each cell.
V70 therefore added a distinct default-off `directional_virtual_cell` plugin,
not a mutation of the V69 operation.  It derives x motion from the vertical
Poisson field and y motion from the horizontal Poisson field, uses an explicit
aggregate fallback for RUDY, and compares mean versus summed incident-net
force transfer.  All 12 V70 rows activated, changed placement, completed both
evaluators, and passed the placement-effect audit.  The RUDY/mean controls
exactly reproduced the corresponding V69 metrics, while GPUGR runtime
telemetry reported directional feedback on every directional row.

V70 selected zero of 12 candidates.  Its closest row used GPUGR feedback,
mean reduction, weight `0.0025`, threshold `0.8`, smoothing `2`, and six force
applications.  It improved GPUGR routed wirelength by `0.051%`, estimated
shorts by `4.824%`, overflow-net count by `17.857%`, vertical p95 congestion
by `1.994%`, and vertical overflow by `100%`, but regressed vertical peak/p99
congestion by `0.663%` and horizontal p95 congestion by `0.175%`.  It also
improved one RUDY primary metric while regressing the other.  No held-out or
golden evidence was used.  The artifact is
`results/routability_local/directional_virtual_cell_pilot_v70_3583ba6`.

V71 completed one bounded structural calibration around that near miss.  It
held weight, threshold, reduction, lifecycle, and proxy cadence fixed while
crossing H/V axis balance `0.5/1.0/2.0` with smoothing radius `1/2/3` for both
feedback backends.  All 18 rows activated, all 18 DEFs changed, and the exact
balance-`1.0`/smooth-`2` control reproduced V70's three vetoes.  No other row
reduced the veto set: horizontal-priority rows kept vertical-tail plus routed-
WL or overflow-net regressions, and vertical-priority rows introduced larger
wirelength, short, overflow-net, utilization, or directional-tail losses.
V71 selected zero of 18 candidates.

The V69-V71 artifacts use local pinned GPUGR SHA-256
`6d543649143c7415ca0d92a62271725792f00c9b25f10a38941b8fedd67c1681`,
keep RUDY and GPUGR metrics separate, and use no Test3, real-design, held-out,
OpenROAD, or Innovus evidence.  Virtual-cell tuning is therefore closed for
promotion; none of these 42 development candidates may enter multi-seed,
combination, held-out, or golden routing.  The V71 artifact is
`results/routability_local/directional_virtual_cell_balance_pilot_v71_3583ba6`.

## Expanded plugin-registry final-audit closure (2026-07-30)

A full current-worktree routability test discovered that the historical golden
finalizer's static production registry still listed 16 operations after the
separate `virtual_cell` and `directional_virtual_cell` plugins increased the
live registry to 18.  `tools/routability_audit_final.py` now includes both
module/class identities, so its derived source/install hash set covers every
registered plugin.  The live-registry regression passes `28/28`, the complete
routability suite passes `424/424`, RUPlace unit tests pass `14/14`, quality
tests pass `11/11`, Python compilation passes, and `git diff --check` passes.

The active `ceca2080x4` repository is a frozen policy-v7 campaign deployment
whose runtime registry predates the local-only V69-V71 mechanisms.  Its
historical finalizer and `27/27` fixture suite were restored to their prior
deployment versions rather than changing source or installed DREAMPlace while
Test2 was active.  The policy-v7 continuation uses
`tools/routability_audit_corrected.py` for its no-candidate/proxy/router
attestations; it does not invoke the historical full-registry finalizer.  The
eventual local final report must therefore bind the expanded 18-plugin source
audit separately from the frozen remote campaign provenance instead of
claiming that V69-V71 ran inside policy v7.

## Local-only terminal-pilot attestation (2026-07-30)

`tools/routability_audit_local_plugins.py` now closes that provenance gap
without changing the frozen remote runtime.  It audits the terminal pilots for
connection RouteForce V35, projected connection RouteForce V40, routed-
overflow net contraction V53, net relaxation V59, directional net contraction
V63, directional path spreading V67, virtual cell V69, and directional virtual
cell V71.  The operation requires exact plugin/config/manifest coverage,
development-only status, completed Test1 seed-`1000` jobs, placement-effect
coverage, separate RUDY and GPUGR evaluators, the
`absolute_directional_v2` policy, and the pinned local GPUGR binary identity.

The audit does not trust an empty `selected_methods` list alone.  It recomputes
the strict gate for every excluded candidate from the backend-local primary
metrics and rejects an attestation if any excluded row actually satisfies the
zero-worst-regression plus per-backend-improvement contract.  The current
artifact covers all 72 terminal candidates and recomputes zero strict
survivors:

`results/routability_remote/local_plugin_terminal_attestation_3583ba6/attestation.json`.

Evaluated-source identity is explicit.  Six plugin files are byte-identical to
their own terminal pilot installs.  The current `connection_routeforce` source
differs from V35 but is byte-identical to later evaluated V40-and-newer pilot
snapshots; the current `virtual_cell` source differs from V69 but is byte-
identical to the evaluated V71 snapshot.  The attestation records both hashes,
the matching snapshot witnesses, and whether the terminal snapshot itself is
current.  It therefore does not falsely claim all eight terminal installs are
identical to the final worktree.

The local policy-V7 final wrapper now generates this attestation before
combining remote and Innovus evidence.  Both `final` and
`no-candidate-final` modes of `tools/routability_audit_corrected.py` require
the attestation, revalidate the current source hashes, and bind its SHA-256 in
the final result.  This leaves the active remote ten-plugin deployment frozen
while making the expanded local evidence mandatory in the eventual combined
decision.  Focused tests pass `36/36`; the full suite is rerun after this
integration and passes `429/429` in the placement environment.  Legacy
RUPlace unit and source-quality results remain `14/14` and `11/11`.

The candidate path also preserves the same identity split.  A local Innovus
router attestation no longer compares the intentionally frozen main install
against the expanded source tree.  Instead it validates and SHA-256-binds the
same proxy-linked plugin identity already attested by the remote OpenROAD
route, while the local terminal-pilot attestation covers the expanded source.
The two records cannot be substituted for one another: the OpenROAD record
must reference the identical proxy attestation and method set, and the local
record must match every current local-only plugin source hash.

## Policy-V7 guarded-backend and diagnostic-HPWL audit (2026-07-30)

The partial and final selection audit implementations now express the proxy
policy without a redundant ambiguity.  RUDY and GPUGR remain independent gates:
each must show at least one primary improvement, but the zero-worst-regression
guard applies only to the configured `worst_regression_backends`, currently
`["gpugr"]`.  RUDY and GPUGR values are never combined.  Legacy selections that
do not serialize the redundant guarded-backend field derive it from the bound
metric profile, while an explicitly inconsistent declaration is rejected.

A fresh local recomputation of the terminal three-seed Test1 prefix used the
corrected `tools/routability_audit_partial_elimination.py` against the frozen
remote summary, raw rows, and preset manifest.  It reports exactly 192
eliminated alternatives: 40 inactive and 152 with GPUGR worst-case primary
regressions, with zero still possible and zero indeterminate.  Its regression
counts contain only the `gpugr` backend.  Every active candidate has at least
nine GPUGR veto metrics.  Candidate
`corrected_net_weight_corridor_0002_rudy_net_weighting`, the closest under the
near-miss magnitude ordering, retains eleven vetoes including `+0.252%` routed
wirelength and `+32.143%` overflow nets.  This partial audit is diagnostic and
uses no held-out or golden evidence; the complete six-comparison terminal audit
is still required.

At the `2026-07-30T23:48:30+08:00` live checkpoint, Test2 had complete method
rows `146/193`, `114/193`, and `118/193` for seeds 1000, 2000, and 3000, with
`147/193`, `115/193`, and `119/193` materialized.  Remote Policy-V7 PID `66351`,
contest waiter PID `5201`, continuation waiter PID `5563`, and local final
watcher PID `2793003` were all alive.  Recent GPUGR route artifacts were still
being written and the active GPUs were utilized, so no job was restarted or
duplicated.

Golden ranking now requires complete `placement:placement_hpwl` coverage for
every method and preserves its aggregate, per-design, and worst-pair evidence
in both JSON and Markdown.  Placement HPWL is stored only under
`diagnostic_metrics`: it is absent from objective components and cannot affect
Pareto, safety, evidence, secondary-cost, or recommendation logic.  The final
auditor independently verifies the diagnostic policy, exact frozen-method
coverage, and objective isolation.  A generated regression with a deliberately
large `+1000` placement-HPWL delta retained the same routing winner while
reporting `objective_has_hpwl=false`.  The complete routability suite passes
`436/436` in the `placement` environment; Python compilation and
`git diff --check` also pass.

The corrected eight-plugin terminal-pilot attestation was regenerated in a
temporary output before waiting for the long chain.  It passes with all eight
plugins covered, zero selected methods, `absolute_directional_v2`, no numeric
backend mixing, and no held-out or golden evidence.  The final local watcher
will regenerate the timestamped artifact again and bind it to the remote
no-candidate or routed-candidate attestation.

## Policy-V7 tuning-adequacy and live Test2 integrity (2026-07-30)

The corrected lifecycle campaign is a complete 192-point factorial rather than
a sparse parameter sample.  It contains 96 RUDY-feedback and 96 GPUGR-feedback
methods and crosses strengths `0.005/0.025`, update intervals `10/40`,
activation thresholds `0.4/0.8`, normalizations `absolute/design_mean`,
lifecycle phases `post_gradient/pre_objective`, and scoring modes
`pin_mean/bbox_mean/bbox_pmean`.  All 192 serialized combinations are unique.
Independent V54-V56 development pilots additionally searched scalar strengths
from `0.00001` through `0.005`, so the terminal result cannot be attributed to
omitting a nearby weaker gamma.

Test1 placement telemetry covers all 576 candidate placements.  It reports 462
active changed rows, two active rows identical to HPWL and explicitly excluded,
112 inactive rows identical to HPWL, and no inactive changed row.  Runtime
telemetry for the near-miss methods records real weight refreshes, bounded
ratios, and the configured score modes.  Together with the direct autograd,
active-mask, frozen-RUDY-input, and corridor-scoring regressions, this rules out
the previously fixed lifecycle, normalization, feedback, and pin-only scoring
defects as explanations for the current no-survivor result.

A read-only live audit at `2026-07-30T23:53:25+08:00` checked every then-complete
Test2 artifact: 385 method rows and 770 evaluator results.  All configs matched
the frozen method manifest and seed, all evaluation grids were 256 by 256, all
RUDY and GPUGR statuses were `ok`, all 29 required primary metrics were finite,
and every GPUGR routed wirelength was positive.  No malformed, missing,
nonfinite, failed, or identity-mismatched row was found.  Complete Test2 rows
had advanced to `150/193`, `116/193`, and `120/193` for seeds 1000, 2000, and
3000.

The early near-miss methods already have all six Test1/Test2 comparisons, which
provides diagnostic-only robustness evidence while the complete matrix runs.
`corrected_net_weight_corridor_0002_rudy_net_weighting` improves all four RUDY
metrics and 19 of 25 GPUGR primaries on average, but retains 15 GPUGR
worst-case vetoes, including routed wirelength, estimated shorts, overflow-net
count, utilization, and both horizontal and vertical congestion tails.  The
earlier Test1-best method `0008` retains 18 GPUGR vetoes over the six
comparisons.  Stronger nearby methods `0001` and `0020` retain 24 and 22 vetoes.
These rows demonstrate a real congestion response but no cross-seed,
cross-design safe operating point.  They remain diagnostic and cannot be
promoted before the terminal selector runs.

A later strict-prefix refresh required all three files
`evaluation/summary.json`, `evaluation/rudy.json`, and `evaluation/gpugr.json`
with both evaluator statuses `ok`.  This matters during a live write because
`summary.json` can become visible briefly before the second evaluator JSON is
committed; the campaign controller itself still waits for the complete result.
Under the three-file rule, the six slots contained `193/193/193` Test1 methods
and `150/117/120` Test2 methods, including HPWL.  Their intersection contained
116 alternatives, of which 82 were active in every slot and zero passed the
strict gate.

The best active six-comparison prefix point remains RUDY feedback, gamma
`0.005`, update frequency `10`, threshold `0.4`, absolute normalization,
`post_gradient`, and `bbox_mean`.  It is method `0002`: four RUDY and 19 GPUGR
mean improvements, but 15 GPUGR worst-case veto metrics.  The next-best point
has 16 vetoes, and every other active common-prefix method has at least 18.
Both RUDY- and GPUGR-feedback regions are already represented in the common
prefix.  This diagnostic therefore identifies no safe parameter basin or new
local scalar refinement justified before terminal completion.

## Policy-V7 terminal-attestation hardening (2026-07-31)

The deferred final wrapper initially supplied the two Policy-V7 selection
labels `missing_families_adaptive_v3_development` and
`corrected_net_weight_lifecycle_development`, while the corrected final auditor
recognized only the historical four-stage exhaustion set.  A valid terminal
no-survivor campaign would therefore have failed before producing its proxy
attestation.  The auditor now registers both 256-by-256 Test1/Test2 stages and
accepts either the historical four-stage proof or the exact six-stage
Policy-V7 proof.  A regression requires both new selections in the latter
case.

An empty selection is not sufficient proof that the 192-point campaign is
complete or trustworthy.  The separate
`tools/routability_audit_policy_v7.py` operation is now mandatory for the V7
no-candidate path.  It independently verifies the exact 192-point factorial,
193 methods including HPWL, six case/seed comparisons, 1,152 candidate
placements, 2,316 RUDY/GPUGR evaluator results, 1,158 finite diagnostic HPWL
values, and 33,582 finite primary metric values.  It also checks every
serialized config against the frozen preset and seed, requires positive GPUGR
routed wirelength and 256-by-256 maps, recomputes the placement-effect audit,
recomputes the strict selector from the summary and raw evidence, and binds the
presets, manifest, summary, raw CSV, selection, placement-effect audit,
selection audit, and terminal status by SHA-256.

The remote final wrapper generates this attestation before accepting V7 proxy
exhaustion.  The corrected proxy attestation embeds and hashes it, and the
local final audit revalidates the embedded record before accepting OpenROAD and
Innovus no-admission statuses.  Local routability tests pass `440/440`; the
focused remote tests pass `3/3` for the V7 operation and `37/37` for the
corrected final auditor.  Local/remote source hashes match, shell syntax and
Python compilation pass, and the active placement campaign was not modified.

## Route-directed legal refinement pilot (2026-07-31)

A separate closed-loop post-placement operation now uses a routed placement
only as a direction oracle and projects the requested x displacements onto
actual row whitespace. Movable standard cells change by whole sites while
y-coordinate and orientation remain fixed. Fixed, unplaced, and multirow
instances are excluded, and the operation verifies that both input and output
have zero overlap pairs. The occupancy-indexed implementation processes the
8,879-cell Test1 seed-1000 oracle in about 1.4 seconds.

The operation is wired into `tools/routability_compare.py` through declarative
`ruplace_post_placement` presets. Source methods must precede the derived
method. Each derived method retains a versioned report binding the baseline,
oracle, LEFs, output DEF, movement parameters, and SHA-256 identities. Resume
reuses it only when all of those inputs still match. Candidates in one
acceptance group are evaluated by RUDY and GPUGR separately, then
`tools/routability_accept_legal_refinement.py` materializes a survivor only if
both backends improve at least one primary metric and no GPUGR primary metric
regresses. Otherwise it materializes the HPWL baseline. This operation is
opt-in and does not change the default policy.

The first formal Test1 seed-1000 audit evaluated 14 legal variants under
`results/routability_local/openroad_refine_test1_seed1000_v1`. None passed;
`legal_refinement_acceptance.json` records `rollback_to_baseline`, and the
materialized DEF has the baseline SHA-256
`c61fd85e34f4ef899a7f8b7ec086df7a467c768d130848ece131b799f0636b8c`.
No held-out or golden evidence was used. The 10% one-site prefix is the closest
metric-wise point: it improves GPUGR routed wirelength and eight H/V or tail
metrics, has only a `+0.00715%` horizontal-ACE regression, but produces no RUDY
improvement and therefore still fails both required conditions.

The subsequent 11%-24% fine-prefix sweep found no survivor: 11%-16% retained
the same one-metric ACE veto and no RUDY response, while 17% and above added
multiple GPUGR vetoes. Rank-window support was therefore added to attribute
disjoint move batches and compose noncontiguous batches without mixing backend
metrics. Seven broad batches, five tail sub-batches, and fourteen composed
variants were evaluated. Two composed seed-1000 candidates passed the exact
gate:

- `prefix_drop_a`, windows `[0.00,0.10]` and `[0.88,1.00]`, moved 156 cells,
  improved two RUDY and eleven GPUGR primaries, and had zero GPUGR regression.
- `tail_drop_ae`, window `[0.88,0.97]`, moved 65 cells, improved two RUDY and
  nine GPUGR primaries, and had zero GPUGR regression.

The route oracle was then formalized as the independent
`openroad_routability_direction_oracle` operation. Its frozen incremental-GPL
and GRT-feedback options, detailed placement, placement check, executable
identity, inputs, log, and output are hash-bound. Replaying seed 1000 with
OpenROAD `26Q1-951-g6975124cf2` reproduced the retained oracle exactly at SHA-256
`4530c7b1c4826a3983029a2d60a8be58aec82c3489aa82def4b719eedc359674`.

The two seed-1000 candidates were then applied unchanged to Test1 seeds 2000
and 3000 under
`results/routability_local/legal_refine_multiseed_test1_v6`. Neither survived:
seed 2000 retained three GPUGR vetoes for each candidate, and seed 3000 retained
four for `prefix_drop_a` and seven for `tail_drop_ae`. The formal
`multiseed_acceptance.json` therefore records zero common strict survivors and
`rollback_to_baseline`. No Test3, real-design, OpenROAD golden route, or Innovus
golden result was used for this tuning decision.

The broader fourteen-composition search completed under
`results/routability_local/legal_refine_multiseed_composed_test1_v7`. Seed 1000
again accepted `tail_drop_ae` and `prefix_drop_a`, but seeds 2000 and 3000
accepted no candidate. Its hash-bound three-seed acceptance therefore records
zero common survivors and `rollback_to_baseline`. The nine-candidate
direction/sweep decomposition in `legal_refine_directional_test1_v8` also had
no common survivor: reversing the two-direction sweep retained two seed-1000
passes, while every seed-2000 and seed-3000 candidate failed.

Five atomic 3% tail windows (`legal_refine_atomic_tail_test1_v9`) and five
atomic 2% prefix windows (`legal_refine_atomic_prefix_test1_v10`) were then
evaluated on all three development seeds. None passed a single complete seed
gate. The attribution showed that the only tail atom improving RUDY on seed
3000 regressed GPUGR routed wirelength, while atoms that recovered routed
wirelength introduced H/V congestion vetoes. Some prefix atoms moved legal
cells but had zero routing-map effect, so further blind fraction composition
was stopped.

A separate `legal_whitespace_net_bbox` objective was implemented to retain the
OpenROAD route-feedback direction while ranking/filtering one-site moves by
their connected-net x-bounding-box delta. The guard is checked before every
move, and all Test1 outputs reported non-increasing aggregate proxy x-span.
Six coarse strengths in `legal_refine_net_bbox_test1_v11` and four interpolated
strengths in `legal_refine_net_bbox_fine_test1_v12` were evaluated across all
three seeds. All ten failed: seed 1000 obtained no RUDY improvement at any
strength, while strengths that improved RUDY on seeds 2000 or 3000 retained
GPUGR routed-wirelength, shorts, overflow-net, or directional-congestion
vetoes. Both formal multi-seed artifacts record zero common survivors and
`rollback_to_baseline`. No held-out or golden evidence was consumed, so no
legal-refinement method is authorized to advance.

After adding the bbox-guided operation and its regression coverage, the full
routability suite passes `466/466` in the placement environment. All
routability Python sources compile, both relevant JSON preset files validate,
and `git diff --check` is clean.

## Nonperiodic Poisson and continuous-RUDY closure (2026-07-31)

The Poisson force plugin now has an opt-in `neumann_dct` solver backed by
DREAMPlace's compiled DCT/Neumann operators. The historical periodic solver
remains the default. The implementation scales the x and y derivatives by the
physical bin dimensions and emits `poisson_solver_neumann_dct` telemetry, so
solver use is directly auditable. Adaptive proposal policy V8 adds both this
periodic-versus-Neumann choice and continuous RUDY utilization feedback;
policies V6 and V7 remain frozen.

Three Test1 seed-1000 development-only pilots initially exercised the new
branch. V13 compared periodic/Neumann solvers and GPUGR/RUDY feedback modes,
V14 swept lower Neumann strengths, and V15 micro-swept six strengths from
`0.00009` through `0.000175`. Every nonbaseline V15 placement was active with
six plugin applications and positive Neumann telemetry.

A post-run semantic audit invalidated the Neumann rows in all three pilots.
DREAMPlace's `IDXST_IDCT` and `IDCT_IDXST` transforms return electric field
`E=-grad(phi)`, as confirmed by the native density operator's explicit minus
sign and a CPU/GPU numerical comparison with finite differences (cosine
`-0.9927`). The plugin had added that electric field as an objective gradient,
reversing the intended descent direction. The helper now negates the mixed
inverse-transform outputs and returns `grad(phi)`. Periodic rows are unaffected.
V13-V15 Neumann metrics are retained as defect evidence only and cannot close
or qualify this branch; a corrected development-only rerun is required before
any multi-seed or held-out decision.

Before the sign correction, the full routability suite passed `469/469` in the
placement environment. The correction adds an explicit objective-gradient
sign regression; corrected-run verification is recorded with the successor
pilot rather than attributed to the invalid V13-V15 evidence.

### Corrected Neumann Poisson V16-V27

The corrected-sign development sequence is complete. V16-V21 and V23-V27
each completed six Test1 seed-`1000` candidates, and four active V22 timing
rows were recovered from its completed placement/evaluation data. V22 stopped
only because offsets `460` and `480` occurred after placement termination and
the placement-effect audit correctly rejected their HPWL-identical DEFs. The
active offsets `380`, `400`, `420`, and `440` all independently failed the
strict GPUGR gate. In total, 70 active corrected-sign candidates covered
feedback backend, scalar versus cross-track directionality, strength,
application count and timing, smoothing, H/V axis balance, and fine axis-aware
strength. No candidate survived separate RUDY and GPUGR screening.

The closest terminal point was the V27 scalar Neumann row with axis balance
`1.25`, one application at iteration `440`, smoothing radius `1`, and strength
`0.00009`. It improved GPUGR routed wirelength by `0.366%`, estimated shorts by
`3.776%`, utilization p99 by `1.516%`, maximum utilization by `7.769%`, and
vertical congestion score by `0.052%`. It also improved RUDY congestion score
by `3.034%` and p99 utilization by `2.994%`. It was rejected because overflow
nets regressed `8.929%`, horizontal congestion score and p99 regressed
`0.193%`, horizontal p95 regressed `0.237%`, and RUDY maximum utilization
regressed `10.289%`. The first four are GPUGR primary vetoes. Corrected
Neumann Poisson is therefore closed without held-out or golden admission; its
code remains available as an independent research plugin but is not a default
or combination candidate.

## Connection RouteForce semantic audit and V79 (2026-07-31)

The Xplace connection RouteForce path was audited from the Python invocation
through `compGcellRouteForce` and the Nesterov update. Xplace's DCT maps are
electric-force fields, its native kernel multiplies them by `-1.0`, and Xplace
adds the returned tensor to the objective gradient before optimizer descent.
The DREAMPlace adapter preserves that exact sign. Its directional mapping is
also intentional: vertical routing pressure drives x motion and horizontal
routing pressure drives y motion. A behavioral regression now proves that a
descent step moves representative pins away from congestion on those
cross-track axes.

The audit found a separate released-kernel limitation: a global pin with more
than one routed branch on the same axis keeps only the last branch contribution.
The original `route_grad` API and `connection_routeforce` plugin remain the
reference. A new native `route_grad_reduce` API and independent
`multisegment_connection_routeforce` plugin expose `sum` and `mean` reductions
without changing that reference. The bundled patch remains reproducible from
the pinned Xplace source, the CUDA extension builds successfully, and both APIs
are present in the installed module. The local regression totals are `476/476`
routability tests, `14/14` RUPlace unit tests, and `11/11` source-quality tests.

V79 screens only the two reduction modes on development Test1 seed `1000`, at
the best V75-V78 directional short-via settings. It runs in detached tmux
`ruplace-v79-3583ba6`; its durable state is
`results/routability_local/multisegment_connection_routeforce_pilot_v79_3583ba6/HANDOFF_STATUS.md`.
The campaign records separate RUDY and GPUGR evaluators and explicitly excludes
Test3, real designs, OpenROAD, and Innovus from tuning. No V79 row may advance
unless it satisfies the unchanged strict proxy gate.

V79 completed with zero strict survivors. `sum` was the only useful reduction:
it improved GPUGR routed wirelength by `0.506%`, estimated shorts by `8.686%`,
overflow-net count by `5.357%`, maximum utilization by `6.368%`, and vertical
overflow by `47.206%`; it also improved all three nonzero RUDY metrics. It was
nevertheless rejected by nine positive GPUGR primary regressions: aggregate
utilization p99; horizontal utilization p99, congestion score, congestion p95,
congestion p99, and ACE; and vertical congestion score, congestion p99, and
ACE. `mean` regressed 13 GPUGR primary metrics and one RUDY metric and is
closed. The placement-effect audit passed and all candidate DEF hashes differ.

V80 is the single bounded structural calibration allowed by the V79 result. It
adds a `blend` reduction that interpolates the exact reference last-branch
gradient and summed-branch gradient from the same route. Coefficients `0` and
`1` are explicitly dispatched to the original kernels, preserving both
endpoints; the development pilot tests only interior coefficients `0.25`,
`0.5`, and `0.75`, with every other V79 control frozen. Test3, real designs,
OpenROAD, and Innovus remain excluded. If V80 has no strict RUDY+GPUGR survivor,
the multisegment family is closed without another scalar sweep.

V80 completed with zero strict survivors. All three placements were active,
used reduction telemetry ID `3`, applied their requested blend coefficient
twice with finite gradients, and produced distinct DEF hashes. Coefficient
`0.25` regressed GPUGR routed wirelength by `0.747%`, estimated shorts by
`18.826%`, overflow nets by `75.000%`, and maximum utilization by `7.503%`;
it also regressed RUDY maximum utilization by `1.787%`. Coefficient `0.5`
improved routed wirelength by `0.530%`, but regressed estimated shorts by
`5.971%`, overflow nets by `33.929%`, maximum utilization by `4.152%`, and
RUDY maximum utilization by `3.221%`. Coefficient `0.75` improved routed
wirelength by `0.369%` and all three RUDY metrics, but regressed estimated
shorts by `14.270%`, overflow nets by `21.429%`, aggregate utilization p99 by
`2.045%`, and multiple H/V congestion-tail metrics. The strict result is
recorded at
`results/routability_local/multisegment_connection_routeforce_blend_pilot_v80_3583ba6/HANDOFF_STATUS.md`.

Therefore `multisegment_connection_routeforce` is closed: neither `sum`,
`mean`, nor an interior last-to-sum interpolation satisfies the separate RUDY
and zero-regression GPUGR gate on the development case. No V79/V80 row is sent
to multi-seed, held-out, OpenROAD, or Innovus validation. The implementation is
retained as an independently selectable research plugin, but it is not enabled
by default or eligible for a combination. Post-change verification passes
`477/477` routability tests, `14/14` RUPlace unit tests, `11/11`
source-quality tests, the DEF-distribution test, JSON and Python compilation,
shell syntax, and `git diff --check`.

## Corrected adaptive-v2 Test1 closure and Test2 continuation (2026-07-31)

The corrected adaptive-v2 Test1 development campaign completed all 160
candidates on seeds 1000, 2000, and 3000 with separate RUDY and GPUGR
evaluation. The unchanged `absolute_directional_v2` selector retained zero
strict survivors. The placement-effect audit passed all 480 candidate slots:
462 active placements changed their emitted DEF, zero active placements were
identical to HPWL, and all 18 inactive placements were byte-identical to HPWL.
Seven methods were inactive on at least one seed. This closes the concern that
the broad Test1 failure came from a generally disconnected implementation;
the result is a QoR and tuning failure under the strict proxy contract.

An immutable six-comparison snapshot at
`development_atomic/partial_six_20260731T1355Z` freezes HPWL plus the first ten
candidates common to Test1 and Test2 across all three seeds. Its strict selector
retained `0/10` candidates. This is a complete six-comparison evaluation of the
frozen prefix, but not a terminal result for the 160-candidate Test2 campaign.
It cannot authorize held-out or golden promotion and does not race the live
per-seed `comparison.json` outputs.

At the verified checkpoint, Test2 had 47, 11, and 12 completed methods
including HPWL for seeds 1000, 2000, and 3000 respectively. Every completed
evaluation summary contained exactly one successful RUDY result and one
successful GPUGR result; no persisted result was invalid or non-OK. The common
completed set remained HPWL plus ten candidates, so another partial snapshot
would duplicate the existing gate. The controller and all three campaign and
comparison workers remained alive on `ceca2080x4`; no duplicate worker was
started in any seed output.

The detached storage pruner had removed 1,013 intermediate `route_*.def`
refresh snapshots from 49 completed methods and reclaimed 17.52 GB while
retaining final DEFs, configurations, placement logs, evaluator summaries,
metrics, and hashes. Remote `/home` had approximately 80 GB free. The full
local routability suite passes `483/483` under the placement PyTorch
environment, and `git diff --check` is clean. Test3, real designs, OpenROAD,
and Innovus remain excluded until a strict full-development survivor exists.

## Proxy-stagnation activation gate and V81 pilot (2026-07-31)

A semantic audit of the first ten immutable six-comparison candidates found a
specific schedule limitation rather than a force-sign or hook-order defect.
The generic local-gradient path normalizes its congestion field and applies a
configured ratio of the placement-gradient RMS. Consequently, a small
transient overflow can receive the same global ratio as persistent severe
congestion. The retained seed-1000 GPUGR refresh sequence made the distinction
observable: Test1 `hv_max` overflow sum fell from 1,508 to 0.79 and then below
0.5, while Test2 remained in the hundreds for most refreshes. Blind periodic
application therefore perturbed the lightly routed case even while its routing
pressure was already resolving under ordinary placement.

`RoutabilityPlugin.congestion_stagnation_gate` is a new opt-in schedule control.
It observes only distinct proxy maps, converts utilization feedback to excess
above a configured threshold, enforces minimum overflow sum and bin count, and
requires a bounded window in which overflow does not improve beyond a tolerance.
The local-gradient plugin applies this gate before smoothing or force
construction and emits complete gate telemetry. Defaults use a one-observation
window and zero severity minima, preserving all prior placements and campaigns.

V81 is a six-point, development-only calibration derived from the completed
Test1 and partial Test2 proxy evidence. It tests three- and four-observation
windows, overflow-sum minima 10/50/100, 0%/5% improvement tolerances, and two
weak force ratios. It uses only ISPD2019 Test1/Test2 seed 1000 with separate
RUDY and GPUGR evaluation and the unchanged `absolute_directional_v2`
zero-positive-worst-case selector. Test3, real designs, OpenROAD, and Innovus
are absent from the pilot.

The pilot runs on idle GPU 1 in tmux
`ruplace-v81-stagnation-3583ba6` using the isolated 75 MB overlay
`/home/yifanchen/proj/ruplace-v81-stagnation-overlay-3583ba6`. Its source and
installed Python hashes match, and it does not modify the installation or
outputs used by the active 160-candidate Test2 campaign. Five focused gate
tests, 91 existing plugin tests, JSON/schema and preset-generation checks, and
the full `488/488` routability suite pass; Python compilation and
`git diff --check` are clean.

## V81 first hard-case result and directional local-gradient V82 (2026-07-31)

All six V81 candidates remained inactive on Test1 seed 1000 and reproduced the
HPWL placement and proxy metrics exactly. Snapshot-level replay independently
confirmed that none of the configured three- or four-observation gates could
simultaneously satisfy severity and stagnation on Test1. Its `hv_max` overflow
sum fell from `1508.39` through `15.86` and below one instead of remaining
stagnant.

The first Test2 candidate, window three with minimum overflow sum ten, was
active for 11 of 26 distinct GPUGR observations. Its gate responded in two
bounded intervention periods rather than applying continuously. The final
placement improved every RUDY metric, including overflow sum by `12.288%` and
maximum utilization by `7.703%`. It also improved GPUGR routed wirelength by
`0.543%`, estimated shorts by `11.809%`, aggregate overflow sum by `20.981%`,
horizontal overflow sum by `32.890%`, and vertical overflow sum by `6.753%`.
It is nevertheless not a strict survivor: overflow-net count regressed
`0.063%`, horizontal mean utilization regressed `0.119%`, vertical p90
utilization regressed `0.205%`, and vertical congestion score/p95/p99 regressed
`0.390%` to `0.447%`. At that checkpoint five schedules remained; this single
near miss did not authorize multi-seed or held-out promotion.

The directional regressions expose a mechanism absent from the node-level
plugin set. Existing `local_gradient` differentiates one aggregate or selected
scalar map along both axes, while `directional_path_spreading` uses cross-track
H/V fields only after averaging them by connected net neighborhood. The new
independent `directional_local_gradient` plugin applies vertical-map x
gradients and horizontal-map y gradients directly to sampled movable nodes. It
supports overflow or utilization feedback, both/single route directions,
positive x/y axis balance, smoothing, and the same opt-in stagnation gate. It
does not alter `local_gradient` or any historical preset.

V82 is a bounded six-row development pilot with the V81 gate and schedule
frozen. It varies only cross-track axis balance `1.0/1.25/1.5/2.0`, one
half-strength point, and one utilization-feedback point. Test3, real designs,
OpenROAD, and Innovus remain excluded. The plugin math and activation tests,
preset-generation test, source-identity audit, JSON/shell checks, and full
`491/491` routability suite pass locally. V82 is not eligible to run or advance
until its isolated remote source/install hashes are verified; V81 remains the
current proxy decision.

The isolated V82 overlay was subsequently prepared at
`/home/yifanchen/proj/ruplace-v82-directional-overlay-3583ba6` without changing
the active V81 overlay or main adaptive-v2 installation. Source/install hashes
match for `plugin_base.py`, the plugin registry, the new directional plugin,
and `params.json`. Remote import reports 20 registered plugins and resolves
`directional_local_gradient` to
`DirectionalLocalCongestionGradientPlugin`. Remote preset preflight generates
exactly HPWL plus six V82 candidates, shell syntax passes, and a PyTorch
cross-track field smoke produces equal positive x/y response.

V81 minimum-overflow-sum 100 subsequently reproduced the sum-10 and sum-50
Test2 placement byte-for-byte (`0c3ddaf3023970514ac921a05b7b805ad246a265308a17643ebd66d6a038f6ba`),
confirming that all 11 active observations exceeded all three thresholds. The
5%-tolerance point was genuinely different from refresh 13 onward, but the
extra interventions were destructive: Test2 RUDY overflow sum/bins/p99/max
regressed `+142.484%/+65.842%/+28.880%/+32.016%`, while GPUGR routed
wirelength, estimated shorts, overflow nets, and H/V overflow regressed
`+41.487%/+92.571%/+7.437%/+78.730%/+143.343%`. Its lower aggregate
congestion-score values are therefore diagnostic artifacts and cannot override
the absolute and directional vetoes.

V81 then completed all 14 case/method evaluations. The four-observation,
5%-tolerance point improved every RUDY metric and GPUGR routed wirelength,
shorts, overflow nets, and horizontal overflow by `-1.260%`, `-12.760%`,
`-6.861%`, and `-27.634%`; it was rejected by seven vertical GPUGR regressions,
including vertical overflow `+1.309%` and vertical maximum utilization
`+1.545%`. The doubled-weak-weight point was the closest V81 result: all RUDY
metrics improved, as did GPUGR routed wirelength `-1.721%`, shorts `-17.482%`,
overflow nets `-3.518%`, and H/V overflow `-41.275%/-20.174%`. It still
regressed horizontal maximum utilization `+0.401%` and vertical congestion
score/p95/p99 `+1.108%/+1.211%/+1.108%`.

The placement-effect-aware terminal selector therefore retained `0/6`. Its
audit proves six active-and-changed Test2 placements, six inactive-and-identical
Test1 placements, and zero inactive-changed placements. The compact terminal
evidence is archived under
`results/routability_lab/local_gradient_stagnation_pilot_v81_3583ba6_terminal`;
the strict selection and placement-effect audit SHA-256 values are
`a319dbeb100fe3ba5dd8647154d8b82c5dc6dcdc8d061ff509f903cb2253dc55`
and `08d64b7231d21b774df398ee3680289902c318f45efbc210d271ab94f23f9efa`.
No V81 method advanced to multi-seed, held-out, OpenROAD, or Innovus work.

The V81 review also exposed a selector contract that predated congestion-gated
plugins. `routability_select_survivors.py` required a plugin to report active
in every comparison, which made a schedule designed to leave an easy case
untouched ineligible even when another development case improved. The selector
now permits `selected_no_activation` only with the corresponding
`placement_effect_audit.json`: at least one comparison must be active with a
DEF different from HPWL, every inactive comparison must be byte-identical to
HPWL, and inactive-changed or active-identical placements remain rejected.
All-active historical campaigns retain the old contract. V81/V82 pass the
placement-effect audit path explicitly to the selector; the focused selector
suite and complete local routability suite pass `16/16` and `495/495`.

`run_ruplace_proxy_multiseed_remote.sh` is the frozen continuation for any
future one-seed survivor. It reruns only HPWL plus selector-approved methods
from scratch on Test1/Test2 seeds `1000/2000/3000`, then repeats the separate
RUDY/GPUGR, placement-effect, and zero-positive-worst-case gates. This avoids
reusing a one-seed result as independent multiseed evidence.

After V81 closed, V82 was launched in tmux
`ruplace-v82-directional-3583ba6` on GPU 1. Its first initialization attempt
stopped before placement because the isolated overlay lacked the referenced
`configs/routability_plugins/presets.json`; the failed log is preserved as
`launcher.initial_missing_presets.log`. The exact source preset file (SHA-256
`510370a9d7f66baa843ae035150fd2d2e165f4b1d6708875a73683c706571d42`)
was restored, a seven-method generation preflight passed, and the clean relaunch
entered `running_proxy_pilot`. Test3, real designs, OpenROAD, and Innovus remain
excluded.

## Immutable six-comparison snapshot and geometry identity repair (2026-07-31)

The active adaptive-v2 campaign now has an immutable snapshot at
`development_atomic/partial_six_20260731T1629Z`. It freezes the first 38
candidates common to Test1/Test2 seeds 1000, 2000, and 3000, for 228 placement
comparison slots. The strict proxy selector retained `0/38`. The placement
audit classified 214 slots as active-and-changed, zero as active-and-identical,
eight as inactive-and-identical, and six as inactive-and-changed. The compact
snapshot is also archived locally under
`results/routability_lab/corrected_adaptive_v2_partial_six_20260731T1629Z`.
The snapshot-manifest, placement-audit, strict-selection, and near-miss hashes
are respectively
`84941e0b97c63ef884fe1bf8309a5c1f7d064717da59ca6bee62a7726758ef3f`,
`bb01f66e5c873cf9a149881f7a3b3173833308a1ab02ca9cb3e67d6f97f55eb8`,
`5d43f2e72ac2a24035e6d9db64931ccadd87381ed496d2e9d657e96aa340f65c`,
and `8acae80aeba5313cd6e13cc210008b37661e1a1768cb101bbbe5c1952fb26417`.

All six inactive-and-changed rows are Test2 seed 2000 placements. Their global
placement metrics match HPWL through iteration 499, but legalization diverges.
The cause was an unconditional lower-left-to-center-to-lower-left floating-point
round trip in `NonLinearPlace.py` whenever `routability_opt_flag` was enabled,
even when no plugin changed node sizes or pin offsets. That perturbation changed
legalization tie ordering. `restore_original_node_geometry` now returns without
touching positions when geometry is unchanged; real area inflation still keeps
cell centers fixed while restoring original sizes and pin offsets. Four focused
geometry tests and the complete `501/501` routability suite pass. V83 is queued
on `ceca2080x4` to rerun the affected inactive Test2 seed-2000 candidate and
requires one inactive-and-identical row, zero inactive-and-changed rows, and an
exact HPWL DEF hash before the repair is accepted as runtime evidence.

## V82 axis response and V84 mapping/polarity ablation (2026-07-31)

V82 completed both proxy backends for its first two Test2 candidates while its
own HPWL baseline and remaining candidates were still running. Against the
same-seed V81 HPWL reference, the balance-1.0 cross-track point is destructive:
RUDY overflow sum rises from `19158.10` to `28830.86`, while GPUGR aggregate,
horizontal, and vertical overflow rise from `63.88/276.00/87.16` to
`108.43/684.44/103.21`. It activated ten times and cannot advance.

The balance-1.25 point is less destructive but still fails the independent
proxy guardrails. Its RUDY overflow sum is `19329.82` (`+0.896%`), with p90 and
p95 utilization also worse. GPUGR horizontal overflow improves to `223.22`
(`-19.12%`), but vertical overflow worsens to `107.07` (`+22.83%`), aggregate
overflow worsens to `65.60` (`+2.69%`), and horizontal maximum utilization
worsens from `1.300` to `1.492`. Routed wirelength and overflow-net count also
worsen by `+0.516%` and `+0.569%`; the `-0.809%` estimated-short improvement
cannot override those independent vetoes. These are diagnostic comparisons
until V82's own HPWL result and terminal selector exist; they do not authorize
multi-seed, held-out, OpenROAD, or Innovus work.

The subsequent balance-1.5 point confirms that this is not a monotonic tuning
interval: RUDY overflow regresses `+45.83%`, while GPUGR routed wirelength,
estimated shorts, overflow-net count, horizontal overflow, and vertical
overflow regress `+3.31%`, `+85.30%`, `+3.25%`, `+132.73%`, and `+18.97%`.
It activated ten times and is eliminated without further seed expansion.

Balance 2.0 also fails despite improving GPUGR vertical overflow and vertical
congestion score by `-39.14%` and `-6.08%`. RUDY overflow regresses `+44.87%`,
while GPUGR routed wirelength, estimated shorts, overflow-net count, and
horizontal overflow regress `+8.89%`, `+73.17%`, `+1.94%`, and `+118.20%`.
It activated 13 times. This rules out further interpolation on the current
cross-track axis-balance sweep; V84 tests the mapping itself instead.

The balance-1.5 half-strength point is the first useful V82 near miss. Against
the same-seed HPWL reference, RUDY overflow sum/bins/max/mean/p99 improve by
`-3.62%/-4.42%/-1.20%/-0.72%/-3.68%`; GPUGR routed wirelength, estimated
shorts, overflow-net count, aggregate overflow, and horizontal overflow improve
by `-0.70%`, `-2.77%`, `-0.35%`, `-1.11%`, and `-19.73%`. It is not a strict
survivor: RUDY p90/p95 regress `+1.44%/+1.25%`, GPUGR vertical overflow and
horizontal maximum utilization regress `+13.35%/+1.12%`, and vertical
congestion score/p95 regress `+0.53%/+0.91%`. It activated ten times. These
vetoes forbid direct multi-seed or held-out promotion.

V85 targets that exact crossover with independent half-strength balances
`1.25/1.5/1.75/2.0` and quarter-strength balances `1.5/1.75`. It retains the
V82 gate and schedule, cross-track mapping, overflow feedback, separate RUDY
and GPUGR evaluation, Test1/Test2 seed 1000 scope, and zero-positive-worst-case
selector. The isolated corrected overlay is
`/home/yifanchen/proj/ruplace-v85-cross-half-overlay-3583ba6`. Local and remote
source/config hashes match, remote generation produces exactly HPWL plus six
candidates, shell/JSON checks pass, and the complete routability suite passes
`502/502`. Tmux `ruplace-v85-cross-half-3583ba6` waits for V84 on GPU 1. No
held-out or golden evidence is used.

The opposite H/V response indicates that the assumed cross-track mapping needs
an explicit ablation rather than another blind weight sweep. The
`directional_local_gradient` plugin therefore has backward-compatible opt-in
`cross_track` versus `matching_axis` mapping and `repel` versus `attract`
polarity. Historical presets retain `cross_track` and `repel`. V84 contains six
development-only rows: one corrected cross-track control, three matching-axis
balance points, one half-strength matching-axis point, and one half-strength
polarity control. The isolated overlay is
`/home/yifanchen/proj/ruplace-v84-directional-mapping-overlay-3583ba6`; source
and install hashes match, the remote registry exposes 20 plugins, the mapping
and polarity tensor smoke passes, preset generation produces exactly HPWL plus
six candidates, and the full local routability suite passes `501/501`. Tmux
`ruplace-v84-directional-3583ba6` waits for the V83 geometry regression on GPU
1. Test3, real designs, OpenROAD, and Innovus remain excluded.

## V82 terminal decision, V83 identity proof, and diagnostic repair (2026-08-01)

V82 completed all `14/14` Test1/Test2 seed-1000 evaluations. The strict
placement-effect-aware selector retained `0/6`: six Test2 placements were
active and different from HPWL, six Test1 placements were inactive and
byte-identical to HPWL, and there were no active-identical or inactive-changed
rows. The utilization-feedback row is eliminated rather than retuned: on Test2
it regressed RUDY overflow sum by `+37.23%`, GPUGR routed wirelength by
`+8.95%`, estimated shorts by `+43.51%`, overflow-net count by `+9.75%`,
aggregate overflow by `+117.72%`, and horizontal/vertical overflow by
`+46.34%/+118.96%`. No V82 method advances to multiseed, held-out, OpenROAD,
or Innovus validation.

The compact terminal evidence is archived at
`results/routability_lab/directional_local_gradient_stagnation_pilot_v82_3583ba6_terminal`.
The screening summary, strict selection, and placement-effect audit SHA-256
values are respectively
`391d8b0035ec1a543dac88de58be6a58124b30c2075f96fc9d1c5979a376813f`,
`bd835624b9228357c3a8675ab25fa15edf231350b44b6de453a32790a9077984`,
and `080f470122acb224d4128b0c813f84016bd25ed6f9f2117dca9e9ec05756c5fc`.

V83 then proved the geometry repair at runtime on the affected Test2 seed-2000
no-op case. The candidate remained `selected_no_activation`; its DEF and HPWL's
DEF both hash to
`a273cb4bd686b6d2fefae66a59d4c090ac7df0d832438a510a6580da229b1116`.
The audit reports one inactive-identical row and zero inactive-changed,
active-changed, or active-identical rows. Its compact record is archived at
`results/routability_lab/geometry_noop_regression_v83_3583ba6_terminal`; the
placement audit hashes to
`5220120b7096d0686356678c11447233833245aa5e6099c2472c622fdf59323a`.
This closes the no-op identity regression and released V84, which is now
running; V85 remains sequenced after it.

The V82 near-miss artifact had a diagnostic-only inconsistency: it required
every plugin comparison to be active even though strict selection already
accepted a mixed active plus hash-proven inactive schedule. The analyzer now
reuses the selector's exact activation and placement-effect checks, discovers a
sibling `placement_effect_audit.json` for already-running legacy launchers, and
the V81/V82/V84/V85 and multiseed runners pass the audit explicitly. The
original V82 near-miss artifact is preserved with SHA-256
`aca7a7fa42f6937427650fca93d3305506ddbe97edc201793cfb744b4b47f3ac`;
the corrected artifact hashes to
`e4f3ab2e3c88a73d3f5666495e48b78cc2d5c9c965e83c043e5a749a47795e72`.
All six rows are now structurally eligible for diagnostic Pareto analysis, and
the half-strength balance-1.5 point is the sole cross-backend worst-frontier
intersection. This does not alter the strict `0/6` decision or waive its
positive vertical and utilization vetoes. The complete local routability suite
passes `504/504`; the two postprocessing tools were deployed to the remote
corrected tree with source-identical hashes before V84 summarization.

## Direction-independent force normalization V86 (2026-08-01)

The V82 half-strength near miss also exposes a scale-coupling limitation in the
directional field itself. Joint normalization preserves the raw RMS ratio of
the horizontal- and vertical-derived map gradients, so a large gradient in one
route direction can consume most of the fixed relative-gradient budget before
`axis_balance` is applied. The new opt-in
`ruplace_directional_local_gradient_normalization=per_axis` first normalizes
the two nonzero axis fields independently, then applies axis balance and a final
joint normalization. This makes the configured X/Y balance equal the actual
pre-sampling field RMS ratio instead of multiplying an unknown map-scale ratio.
The historical `joint` behavior remains the default and all V82/V84/V85
placements are unchanged.

V86 is a bounded development-only six-row ablation: one joint half-strength
control, per-axis half-strength balances `0.75/1.0/1.25/1.5`, and one per-axis
quarter-strength balance-1.25 point. It retains the V82 stagnation schedule,
cross-track repel mapping, GPUGR feedback, separate RUDY/GPUGR evaluation, and
Test1/Test2 seed-1000 scope. The full routability suite passes `506/506`. The
isolated 75 MB overlay is prepared but not launched at
`/home/yifanchen/proj/ruplace-v86-axis-normalization-overlay-3583ba6` so that a
V85 strict survivor, if any, can take priority for mandatory multiseed replay.
Source and installed plugin hashes match
`93e92d7a8f68a581f839a6ce83761f1eca71c8ecc89ba38364e557718291518c`;
remote preset generation produces exactly HPWL plus six candidates, and a
tensor smoke confirms that per-axis balance 4.0 produces an X/Y RMS ratio of
exactly 4.0. No held-out or golden evidence was used.

V86 was subsequently launched in parallel on the otherwise idle local Titan
RTX, without changing or duplicating the remote queue. The remote overlay's
compiled extensions target Python 3.9, so the local runtime was reconstructed
non-destructively at
`/mnt/nvme2n1/yifan/ruplace-v86-local-py38-overlay-3583ba6` from the validated
local Python-3.8/CUDA-11.8 DREAMPlace install plus only V86's Python/config
overlay. Imports of the compiled placement ops, bundled GPUGR, and the V86
plugin pass. Source and installed plugin hashes both remain
`93e92d7a8f68a581f839a6ce83761f1eca71c8ecc89ba38364e557718291518c`.

`run_ruplace_v86_remote.sh` now accepts an explicitly empty
`RUPLACE_PATH_MAP`, allowing a local launch to retain native benchmark paths;
the historical remote mapping remains the default. The updated runner hashes
to `88f1541120156f8a291497052123eec8218b49f2331c955803740b159d0bfc16`.
Tmux `ruplace-v86-axis-normalization-local-3583ba6` entered
`running_proxy_pilot` on local GPU 0 with Test1 running and Test2 queued. The
scope remains Test1/Test2 seed 1000 with separate RUDY/GPUGR evaluation and no
held-out or golden evidence.

The first V86 Test1 candidate subsequently completed both RUDY and GPUGR with
`ok` status. Its stagnation gate reported zero force applications and
`attempted_no_change`, as expected for the easy development case. This proves
the reconstructed local Python-3.8 overlay through placement, bundled GPUGR,
and both external evaluators; placement identity remains subject to the
terminal campaign audit.

All six V86 Test1 candidates have now completed. Each plugin summary reports
`attempted_no_change`, zero activations, and zero force applications, and each
RUDY/GPUGR summary is metric-identical to same-campaign HPWL. Test1 therefore
satisfies the intended inactive-control behavior. Test2 started automatically
on the local Titan RTX; its first joint-normalization control has completed,
while the per-axis rows and terminal selector remain in progress.

The original local V86 campaign was stopped after an input-provenance audit
found that its Test2 benchmark was not semantically identical to the canonical
remote campaign input. The local Test2 LEF declared `MEM1` and `MEM2` as
`CLASS BLOCK` and its DEF marked the four memory instances `FIXED`; the
canonical remote files declare the macros `CLASS CORE` and mark those same
instances `PLACED`. This explains the anomalously low local Test2 congestion
and makes its cross-campaign Test2 deltas invalid. The untouched invalid run is
preserved at
`/mnt/nvme2n1/yifan/ruplace-v86-local-py38-overlay-3583ba6/results/directional_local_gradient_axis_normalization_pilot_v86_3583ba6.invalid-input-fixed-macro-20260801T0340`.
Test1 happened to be byte-identical, but the archived campaign is not used for
selection.

Byte-identical copies of the canonical remote inputs now live under the local
V86 overlay's `benchmarks/ispd2019` directory. Their SHA-256 values are Test1
DEF `b8c8d4af0d3ee2fc775e5653a398d6836dd378df713302aa6187260cd3819afb`,
Test1 LEF `e28d313dc139fe65165b9e756f7b12ae053434a5e62d3a7e24d7507ac6006c44`,
Test2 DEF `f88564964b86f5e7124445b9551d95bfcb1015dd073d0c50f2ac03d3385e60dd`,
and Test2 LEF `74860500a13e66eea5b6d9b4c389057b5987fa497e19c871e2d392034a00fb3a`.
Fresh tmux `ruplace-v86-axis-normalization-local-3583ba6` was relaunched with
an explicit path map to that isolated canonical copy. The corrected campaign
reruns Test1 and Test2 from scratch and remains development-only.

`tools/routability_compare.py` now hashes every resolved LEF, DEF, netlist,
evaluation netlist, and AUX input, stores the result as
`placement_input_provenance` in `comparison.json`, and permits placement or
evaluation resume only when those content hashes match. Missing inputs are
represented explicitly, and large files are hashed incrementally. This closes
the same-path/content-changed resume hole that allowed the V86 mismatch to go
undetected. The runner, campaign, and parallel tests pass `32/32`, and both
modified Python files compile. The validated runner hash
`67e0e083aa4d5395957cf466a8d88cac2c8d319ba2b3fdb667952f09d031229f`
was installed atomically in the remote corrected tree; the previous remote
copy is retained as `routability_compare.py.pre-provenance-20260801` with hash
`5c5b3bcf54deafa711975cc341c1bbccd2b43cf8d1494386cd0768d9ecc6926c`.
The already-running V85 process retains its loaded module, while V87-V89 will
load the guarded runner when their queued launches begin.

The corrected local V86 process began at 03:39, three minutes before the guard
was installed in the worktree at 03:42. Its completed Test1 comparison is
therefore byte-verified against the canonical hashes above but does not yet
contain the new `placement_input_provenance` record. Test2 began after the
guard installation and uses the guarded runner. Tmux
`ruplace-v86-provenance-recheck-local-3583ba6` waits for the active V86 campaign
to finish, then reruns the same resumable runner. The missing Test1 provenance
will force all seven Test1 placements and evaluations to rerun; hash-matching
Test2 work will be reused. The terminal V86 selector is regenerated only after
that pass, so no pre-guard Test1 result can be promoted.

The broad adaptive-v2 campaign reached 58 candidates with complete `ok` RUDY
and GPUGR results in all six Test1/Test2 seed comparisons. Tmux
`ruplace-snapshot64-3583ba6` now watches that exact completion predicate and
will freeze a compact immutable snapshot once at least 64 candidates are
common, then run the placement-effect audit, separate-backend near-miss
diagnostic, and zero-positive-GPUGR-worst-regression selector. It does not pause
or modify the active placement workers and does not access held-out or golden
data.

## Adaptive-v2 immutable 64-candidate decision (2026-08-01)

The snapshot watcher reached its exact target and froze 64 candidates common
to Test1/Test2 seeds `1000/2000/3000`, for 384 candidate placement comparison
slots with complete RUDY and GPUGR evaluation. The immutable remote snapshot is
`development_atomic/partial_six_64_20260731T182023Z`; its 19 MB compact record
is archived locally at
`results/routability_lab/corrected_adaptive_v2_partial_six_64_20260731T182023Z`.
The snapshot-manifest, screening-summary, placement-audit, strict-selection,
and near-miss SHA-256 values are respectively
`cc8fbebbf468914fe7daecd4ed5986e9aef6422bdeaa7c906a8df7551650babc`,
`055da1831eef08227411d82299ab3e6c4392d33bea3c850f74b5d337d19a5598`,
`b38b1a995d08edba4cca9ac416309591ea336a896eb91cdf5396641b19236411`,
`f65348d177f1c9c03b6e9df998165676306064ade73afbfaf01e548dc25be1c1`,
and `6e502964fba9653705d334b3b171acf778e424aa12d1c66172db1f8002cbe332`.

The strict selector retained `0/64`. Of the 64 candidates, 56 are structurally
eligible and 40 improve at least one primary metric independently in both RUDY
and GPUGR, but none has zero positive GPUGR worst-case regressions. Even the
eligible both-backend candidates with the fewest violated GPUGR guardrails
regress 17 or more primary metrics across the six comparisons. The
cross-backend worst-frontier intersection contains six local-gradient or
net-overlap variants, but they still regress 19 to 24 GPUGR guardrails and are
diagnostic near misses only.

The placement audit reports 366 active-and-changed, zero
active-and-identical, ten inactive-and-identical, and eight
inactive-and-changed rows. The eight inactive-changed rows are explicit
selector vetoes from the pre-V83 geometry path, but they do not explain the
terminal result: all structurally eligible rows also fail at least one proxy
metric gate. No adaptive-v2 snapshot candidate advances to corrected
multiseed, held-out, OpenROAD, or Innovus validation. The active adaptive
workers remain screening-only; V84/V85/V86 corrected directional experiments
retain promotion priority.

That broad campaign was launched before the V83 geometry no-op repair was
installed in its main DREAMPlace tree. Its snapshot is therefore a screening
source, not corrected promotion evidence: inactive-changed rows remain explicit
selector vetoes, and any strict candidate must be rerun from scratch with
`run_ruplace_proxy_multiseed_remote.sh` in an immutable overlay containing the
V83 repair before it can advance to Test3, real designs, OpenROAD, or Innovus.

## V84 first matching-axis result and targeted V87 follow-up (2026-08-01)

The first active V84 matching-axis point, full strength with axis balance 1.0,
completed Test2 RUDY and GPUGR evaluation. Against the same-seed HPWL reference,
it improves every reported RUDY congestion metric, including overflow sum/bins
by `-17.50%/-4.97%` and p90/p95/p99/max utilization by
`-4.60%/-7.91%/-9.67%/-10.30%`. GPUGR routed wirelength, estimated shorts,
overflow nets, aggregate overflow, and horizontal/vertical overflow improve by
`-1.96%`, `-18.38%`, `-8.57%`, `-28.18%`, and `-36.48%/-9.20%`.

This is not a strict survivor. GPUGR aggregate maximum utilization regresses
`+0.74%`, horizontal maximum utilization regresses `+1.24%`, and vertical
congestion score/p95/p99 regress about `+1.35%`. The result does show that
matching-axis response fixes the much larger cross-track overflow tradeoff and
narrows the remaining problem to directional tail metrics. V84 continues with
its balance and strength ablations; no held-out or golden evidence was used.

The next full-strength matching-axis point at balance 1.25 proves that this is
a sharp trajectory boundary rather than a smooth improvement interval. Against
HPWL, RUDY overflow regresses `+41.18%`, while GPUGR routed wirelength,
estimated shorts, overflow nets, aggregate overflow, and horizontal/vertical
overflow regress `+4.51%`, `+81.87%`, `+6.54%`, `+61.52%`, and
`+104.05%/+32.42%`. Its `-1.42%` vertical-congestion-score improvement cannot
override these independent vetoes. It is eliminated without seed expansion.

Balance 1.5 is more destructive still: RUDY overflow sum/bins regress
`+64.18%/+19.96%`; GPUGR routed wirelength, estimated shorts, overflow nets,
aggregate overflow, and horizontal/vertical overflow regress `+25.92%`,
`+95.05%`, `+14.89%`, `+121.05%`, and `+118.14%/+59.01%`. Its lower
horizontal and vertical congestion-score values are proxy-shape artifacts and
cannot override the absolute overflow and violation metrics. V84 therefore
rules out matching-axis balances above 1.0 at full strength and proceeds to its
half-strength mapping/polarity controls.

Because matching-axis balances above 1.0 amplify X response while weakening Y
response to the still-regressed vertical congestion, V87 adds the missing
lower-balance interval. Its six independent rows test balances `0.75/0.875` at
full, half, and quarter strength under the same corrected geometry, stagnation
schedule, RUDY/GPUGR split, and strict zero-positive-GPUGR-worst gate. Local
JSON/shell/preset checks and 67 focused generator/selector/near-miss tests pass.
The isolated 75 MB overlay is
`/home/yifanchen/proj/ruplace-v87-matching-vertical-overlay-3583ba6`; config,
runner, source-plugin, and installed-plugin SHA-256 values are respectively
`827dccbab70974c23b60b531ae258800f2e63cf421f1e6e342a173975b766c9d`,
`3d84a47ffc95461d3b066dcb6009ef9486c68cddfb06341078d2b3a83a994638`,
and matching plugin hashes
`d7ffc0254ad245259823d04b6127a5b610ed2af8d7249b6d63b5afcbb2e1f2b8`.
Remote generation produces exactly HPWL plus six candidates. Tmux
`ruplace-v87-matching-vertical-3583ba6` waits behind V85 on GPU 1 and remains
development-only.

## Matching-axis application-budget ablation V88 (2026-08-01)

V84 also exposes a schedule-lifetime distinction: the useful full-strength
balance-1.0 matching-axis trajectory applied eight congestion-gated forces,
whereas the destructive balance-1.25 trajectory applied ten. V88 isolates this
control from axis balance by fixing matching-axis balance 1.0 and testing
maximum application counts `4/6/7` independently at full and half strength.
The existing `ruplace_force_max_applications` budget is used directly; no
plugin behavior or selector policy changes.

Local and remote generation produce exactly HPWL plus six candidates, with
separate RUDY/GPUGR evaluation, Test1/Test2 seed-1000 scope, placement-effect
audit, and zero-positive-GPUGR-worst selection. The isolated 75 MB overlay is
`/home/yifanchen/proj/ruplace-v88-application-budget-overlay-3583ba6`.
Config, runner, source-plugin, and installed-plugin SHA-256 values are
respectively
`f801d8432c6297f7f96011b49d2bb6fd6de1c0316afe9e5a5ef0ac6ee3a7dcbd`,
`06eccea3b849ff352d3a12a529177539185af301b646d2c52625060e38e319c7`,
and matching plugin hashes
`d7ffc0254ad245259823d04b6127a5b610ed2af8d7249b6d63b5afcbb2e1f2b8`.
Tmux `ruplace-v88-application-budget-3583ba6` waits behind V87 on GPU 1 and
does not access held-out or golden evidence.

## Matching-axis per-axis normalization ablation V89 (2026-08-01)

The V84 matching-axis balance-1.0 point is the strongest corrected near miss,
but its joint field normalization leaves small GPUGR tail-utilization
regressions after large improvements in routed wirelength, shorts, and H/V
overflow. V86 tests per-axis normalization only with the older cross-track
mapping. V89 fills that missing interaction without changing plugin behavior:
it fixes matching-axis, repel polarity, overflow feedback, and the corrected
stagnation schedule, then compares one joint-normalization control against
per-axis normalization at full, half, and quarter strength with balances in
the bounded `0.75` to `1.0` interval.

The campaign contains exactly HPWL plus six candidates and is restricted to
Test1/Test2 seed `1000` with RUDY and GPUGR evaluated and gated separately.
It does not access Test3, real designs, OpenROAD, or Innovus. The isolated
remote overlay is
`/home/yifanchen/proj/ruplace-v89-matching-normalization-overlay-3583ba6`.
Config, runner, source-plugin, and installed-plugin SHA-256 values are
respectively
`5af6dcdde4abdc4d8335ea6f2629ff1074fed0b19cc04f68c0d545832d0bf829`,
`ccefd9b12d6839c26107c828edce596ffa6147ed1269623f196d8b721ce7d795`,
and matching plugin hashes
`93e92d7a8f68a581f839a6ce83761f1eca71c8ecc89ba38364e557718291518c`.
Remote preset generation produces exactly seven methods. Tmux
`ruplace-v89-matching-normalization-3583ba6` waits behind V88 on GPU 1 and
remains development-only.

A pre-execution source audit found that the initially staged V89 overlay had
incorrectly retained plugin hash
`d7ffc0254ad245259823d04b6127a5b610ed2af8d7249b6d63b5afcbb2e1f2b8`,
which predates the `normalization` argument. Its nominal per-axis variants
would therefore have silently executed joint normalization. V89 had not left
`waiting_for_gpu`, so no placement or evaluation artifact was produced by the
stale implementation. The waiting tmux was stopped, both isolated source and
installed plugin copies were replaced with the correct hash above, and the
session was relaunched behind V88. The runner now fails before preset
generation unless source/install hashes match and a tensor smoke produces the
requested X/Y RMS ratio of exactly `4.0` under per-axis normalization. The
remote preflight passes.

## Matching-axis utilization-feedback ablation V90 (2026-08-01)

V84's strongest matching-axis point improves absolute overflow, violations,
and routed wirelength but leaves small GPUGR tail-utilization regressions. All
V84 and V87-V89 matching-axis variants use overflow feedback. The only earlier
utilization-feedback row was V82's rejected cross-track balance-1.5 point, so
it does not answer whether absolute utilization gradients complement the
corrected matching-axis mapping.

V90 isolates this missing control with one overflow full-strength balance-1.0
reference and five utilization-feedback rows: full, half, and quarter strength
at balance 1.0 plus half and quarter strength at balance 0.875. Utilization
gating uses threshold `1.0`; all schedule, smoothing, polarity, and proxy
settings otherwise match V84. The campaign contains exactly HPWL plus six
candidates on Test1/Test2 seed `1000`, evaluates RUDY and GPUGR separately,
and uses the same placement-effect and zero-positive-GPUGR-worst gates. It
does not access held-out or golden evidence.

The isolated overlay is
`/home/yifanchen/proj/ruplace-v90-matching-utilization-overlay-3583ba6`.
Config, runner, source-plugin, and installed-plugin SHA-256 values are
respectively
`0ab7609cd937f53202ac46c2c439b88cd1b07f73f0e15a0052f5e2384697f913`,
`628e0003a2092fde756b6da7f3ba504c9b33a5ff9f03582c22c5259ab0065c37`,
and matching plugin hashes
`93e92d7a8f68a581f839a6ce83761f1eca71c8ecc89ba38364e557718291518c`.
Local and remote preset generation both produce exactly seven methods, the
full plugin regression passes `98/98`, and tmux
`ruplace-v90-matching-utilization-3583ba6` waits behind corrected V89 on remote
GPU 1.

## V84 terminal proxy decision (2026-08-01)

V84 completed both development cases with all six candidate placements and
both proxy evaluators valid. The placement-effect audit passes with six
active-and-changed Test2 rows, six inactive-and-identical Test1 rows, and no
identity-contract failures. The strict selector retained `0/6` candidates.
Every candidate is structurally eligible, but none satisfies the zero-positive
GPUGR worst-regression gate.

Full-strength matching-axis repel at balance 1.0 remains the strongest V84
near miss, with five GPUGR guardrail regressions: aggregate and horizontal
maximum utilization plus vertical congestion score, p95, and p99. Reducing
the same force to half strength does not fix that frontier. It applies eleven
forces rather than eight and improves Test2 RUDY overflow sum/bins by
`-7.63%/-5.12%`, GPUGR routed wirelength by `-0.73%`, estimated shorts by
`-5.36%`, overflow nets by `-1.88%`, and horizontal overflow by `-25.26%`.
However, GPUGR aggregate overflow sum/bins regress `+3.37%/+1.17%`, vertical
overflow sum/bins regress `+21.53%/+23.21%`, horizontal maximum utilization
regresses `+1.42%`, and several vertical tail metrics also regress. The
half-strength candidate therefore violates twelve GPUGR guardrails. Reversing
the half-strength polarity still violates nine GPUGR guardrails, including
`+0.52%` routed wirelength, and is also eliminated.

The compact terminal record is archived locally at
`results/routability_lab/directional_local_gradient_mapping_pilot_v84_3583ba6_20260801T032652`.
The screening-summary, strict-selection, placement-audit, and near-miss
SHA-256 values are respectively
`5a16720a7c60037eacd4213a63aa591532101d8c6185cb080ef9b6aee3f864a1`,
`6936c7c00d607fd548a614fb7b74b3dbd313f98373b73cc00c81027d95f0e70e`,
`8c63076134cdb58401282b2cae512f3cc8c35ed86376b6d6a99edc3e3f4dccd3`,
and `665f4c3d2873d612ea569a4006c6060ac176efb0c4943ca0e60e34103a2b70d8`.
No V84 method advances to multi-seed, held-out, OpenROAD, or Innovus
validation. V85 has started automatically on remote GPU 1; V87, V88, and V89
remain ordered behind it.

## Placement resume provenance hardening (2026-08-01)

`tools/routability_compare.py` now makes placement reuse conditional on three
independent exact matches: resolved input-content provenance, the executed
DREAMPlace placement package, and the numerical runtime. The placement-package
record hashes all Python, JSON, and native shared objects below the package used
by `--dreamplace-entry`, excluding evaluator-only RUDY/GPUGR code that is
already covered by evaluator provenance. Isolated overlays also record their
retained `source/` snapshot; a missing installed counterpart or any byte
mismatch is a hard pre-placement error. The runtime record includes hostname,
kernel/machine, Python and NumPy versions, Torch/CUDA/cuDNN/C++ ABI, NVIDIA
driver, visible GPU name/compute capability/memory/SM count, and environment
variables that can change numerical execution. A legacy `comparison.json`
missing either new record is deliberately non-reusable.

The campaign Python 3.8 environment passes the plugin and runner suites
`98/98` and `35/35`; campaign/parallel control tests pass `2/2`, Python
compilation passes, and `git diff --check` is clean. The local V86 probe hashes
167 installed placement files and four retained source files with zero
mismatches, and resolves the runtime as TITAN RTX, Python `3.8.18`, Torch
`2.0.1`, and CUDA `11.8`.

The corrected comparison driver was deployed atomically to remote shared repo
`/home/yifanchen/proj/ruplace-routability-corrected-3583ba6` with SHA-256
`bee9cd696ca78085e41d713c164ce3354836950536498d50bc81fadd75b29343`.
Its closed post-placement helper dependency set was also deployed and the
driver import/compile smoke passes. Remote V85 and queued V87-V90 overlays each
hash 167 installed placement files, retain one to four relevant source files,
and have zero source/install mismatches. The remote runtime resolves as RTX
2080 Ti compute capability `7.5`, Python `3.9.18`, Torch `2.0.1`, and CUDA
`11.8`. V87 remained in `waiting_for_gpu` behind V85 throughout deployment, so
V87-V90 will start with the new guard.

At `2026-08-01 04:27 +08`, local V86 has Test1 `7/7` and Test2 `2/7`
placement-plus-RUDY-plus-GPUGR results, with the third Test2 candidate active.
Its completed Test1 `comparison.json` predates input, placement-package, and
runtime provenance. The already-staged V86 watcher will therefore rerun both
development cases after the first pass finishes. Remote V85 has Test1 `7/7`
and Test2 `3/7`, with the fourth Test2 candidate active; its completed Test1
comparison also lacks all three placement provenance records. V85 may be used
only as same-host legacy rejection evidence and cannot promote a method. No
metric is compared numerically between local V86 and remote V85, and neither
campaign accesses held-out or golden validation.

The resume record also stores and verifies the SHA-256 of every emitted placed
DEF. Output mutation therefore invalidates placement and evaluator reuse even
when inputs, config, implementation, and runtime are unchanged. Before proxy
evaluation, an independent LEF/DEF geometry parser records component, row,
overlap-pair, unplaced-component, and row-uncovered-component counts. The
placement-effect audit now requires all top-level placement provenance, a
hash-matching placed DEF, successful geometry provenance, and zero counts for
all three geometry violations before any selector can promote a method. The
new runner, placement-effect, geometry/refinement, and selector tests pass
`35/35`, `12/12`, `9/9`, and `16/16`, respectively. Current remote helper
hashes are
`6a4422b7d18e7ce497ad304b7fae5f7190d2eb867dd86588b24899463d7e9ef9`
for `routability_legal_refine_def.py` and
`2bfd5055d41f73f8459bb09f6a0c6b94238422bff03bc959fb383e291da41431`
for `routability_audit_placement_effect.py`.

An independent local audit of the V86 input and both completed Test2 outputs
found zero overlap pairs. A remote smoke on the completed first V85 Test2
candidate parsed all `72,094` components and found zero overlap pairs, zero
unplaced components, and zero row-uncovered components. The repeated
`gap 0.149902` messages are buffered diagnostics from an Abacus trial that
DREAMPlace rejects before returning the greedy-legal placement; they are not
the exported DEF. Promotion is nevertheless based on the exported geometry
record above, never this log interpretation.

## V85 terminal diagnostic and cross-axis tail-control pilot V91 (2026-08-01)

V85 completed all seven methods on Test1 and Test2 with both RUDY and GPUGR.
It is diagnostic-only: a manual run of the strengthened placement-effect audit
rejects the Test1 comparison because it predates
`placement_input_provenance`, `placement_implementation_provenance`, and
`placement_runtime_provenance`. The screening summary and explicit rejection
log remain at the remote V85 overlay with SHA-256 values
`8706a3cee2661e6a81396208044fb341f233363c1c52c6b47a06ab5465c4cb96`
and
`563dd59b18b8d8775f408d4114d3520e4eba8a7e10973a8337e27645af5bff0f`.
No V85 row can advance from this campaign.

The closest V85 numeric row is cross-axis, quarter-strength balance `1.75`.
Test1 is a congestion-gated byte-identical no-op; on congested Test2 the row
improves RUDY overflow sum by `-15.21%`, GPUGR routed wirelength by `-0.73%`,
estimated shorts by `-15.75%`, overflow nets by `-3.79%`, horizontal overflow
sum by `-34.27%`, and vertical overflow sum by `-7.30%`. It still fails five
absolute GPUGR guardrails: aggregate maximum utilization `+2.62%`, vertical
overflow bins `+0.20%`, and vertical congestion score/p95/p99
`+0.44%/+0.66%/+0.44%`. This is a tail-concentration failure rather than a
bulk-overflow or routed-wirelength failure.

V91 is a bounded follow-up that reruns that exact V85 control with current
provenance and independently changes one tail-control knob. Its six rows are
smoothing radii `1/2/4/8` with unbounded applications plus the smoothing-1
control capped at `6` or `8` applications. Axis mapping, balance, quarter
strength, overflow feedback, polarity, stagnation gate, and proxy resolution
remain fixed. All 39 preset-generation tests pass, and local and remote
generation each produce exactly HPWL plus six candidates.

The isolated 75 MB overlay is
`/home/yifanchen/proj/ruplace-v91-cross-tail-control-overlay-3583ba6`.
Config and runner SHA-256 values are
`3b73c9281c29c768c4e44b656cd2758049750181b4a2e7dee19ebf8f7da3f488`
and
`38b982776d57b89d37ebf3952835b981abc8ae98ebfedf1de298304758bd00bb`;
the retained and installed `NonLinearPlace.py` hashes both equal
`e39f2578e4f3315f948e4cb4b3b75f178ca8b462a147e4d6af2f59a9e3252bde`.
Tmux `ruplace-v91-cross-tail-control-3583ba6` is queued after V90 on remote
GPU 1. V87 started automatically after V85 exited. V87-V91 remain restricted
to Test1/Test2 seed `1000`; none accesses Test3, real designs, OpenROAD, or
Innovus.

V87's Test1 comparison is the first fresh remote artifact under the hardened
resume contract. It records hashed DEF/LEF inputs, 167 installed placement
files, four retained source files, zero source/install missing files or
mismatches, and the exact RTX 2080 Ti/Python 3.9.18/Torch 2.0.1/CUDA 11.8
runtime. Every one of its seven placements has a matching placed-DEF digest
and independent geometry provenance with zero overlaps, zero unplaced
components, and zero row-uncovered components. The one-slot placement-effect
audit passes with six congestion-gated inactive-and-identical candidates and
has SHA-256
`7054526ecc09a4090ec05c61a23ced5d7f35cff34437a385fb61f9e092d86453`.
Both RUDY and GPUGR are complete for every method. V87 then advanced to
congested Test2; terminal selection still requires that second comparison and
the full two-slot audit.

## V86 terminal diagnostic and per-axis tail-control pilot V92 (2026-08-01)

At `2026-08-01 05:29 +08`, the first local V86 pass completed both development
cases and immediately handed the same isolated overlay to the staged
provenance recheck. The first-pass Test2 comparison records input provenance
but lacks `placement_implementation_provenance` and
`placement_runtime_provenance`; its numbers are therefore diagnostic only and
cannot enter survivor selection. The recheck invalidated that resume state as
intended and restarted Test1 placement under the hardened contract.

The diagnostic V86 Test2 result rejects per-axis normalization as a general
replacement: balances `0.75`, `1.0`, and the quarter-strength `1.25` row all
regress multiple RUDY/GPUGR metrics. The per-axis half-strength balance `1.5`
row is nevertheless a useful bounded tail-control lead. Relative to its
same-comparison HPWL baseline it changes RUDY overflow sum by `-9.98%`, GPUGR
routed wirelength by `-0.23%`, estimated shorts by `-12.78%`, overflow nets by
`-7.91%`, horizontal overflow sum by `-9.69%`, and vertical overflow sum by
`-51.47%`. It still fails the strict gate because aggregate maximum utilization
regresses `+5.69%`; no V86 row is promoted from this pass.

An independent runtime wiring audit of the active V87 Test2 control confirms
that the directional plugin is not a silent no-op: `matching_axis` is recorded
in the emitted configuration and plugin metrics, the three-observation
stagnation gate passes ten times, all ten scheduled force applications have a
nonzero applied scale, and the placement exporter writes the resulting legal
DEF. The objective path captures the base placement gradient before adding the
congestion gradient, so relative scaling is computed against the intended
wirelength-plus-density reference. This supports tuning the tail response
rather than changing force sign or pipeline order.

V92 isolates that V86 lead and varies only tail-control knobs. Its six rows
hold cross-track mapping, per-axis normalization, balance `1.5`, half strength
`0.00009375`, overflow feedback, polarity, stagnation gate, and proxy settings
fixed. Four rows use smoothing radii `1/2/4/8` without an application cap; two
more retain smoothing `1` and cap force applications at `6` or `8`. The local
generator produces exactly HPWL plus six candidates, all 40 preset-generation
tests pass, JSON/shell validation passes, and `git diff --check` is clean.

The isolated remote overlay is
`/home/yifanchen/proj/ruplace-v92-per-axis-tail-control-overlay-3583ba6`.
Config and runner SHA-256 values are
`715cd759310131894516804057fa1817877fa6e95a5549fc44a889b455a4c862`
and
`dff8e280faa1bccaa4ab83498131b98900940cd6d21decd1493362d28ba11ca1`.
Retained and installed plugin hashes match, the overlay is 75 MB, and tmux
`ruplace-v92-per-axis-tail-control-3583ba6` is waiting behind V91 on remote
GPU 1. V92 is development-only Test1/Test2 seed `1000`; it cannot access
Test3, real designs, OpenROAD, or Innovus.

## Monotonic directional tail guard V93 (2026-08-01)

V91/V92 use static smoothing and application budgets to limit the utilization
tails seen in the V85/V86 near misses. V93 adds a separate default-off dynamic
operation: before a directional local-gradient force is applied, it records
the best observed horizontal and vertical utilization max and/or p99 from the
GPUGR feedback map. A later force is allowed only when every selected tail is
within a configured fractional tolerance of that best observation. A blocked
force does not consume the application budget or advance force decay, so the
ordinary wirelength-plus-density optimizer can recover before the plugin is
considered again. Every guarded application also requires a fresh proxy
observation; one cached observation cannot authorize multiple unseen forces
when application and refresh intervals differ.

The option is plugin-scoped through
`ruplace_directional_local_gradient_tail_guard`,
`ruplace_directional_local_gradient_tail_metric`, and
`ruplace_directional_local_gradient_tail_tolerance`. It is disabled by default,
so prior plugins and campaigns retain their existing behavior. Runtime summary
metrics expose current/reference H/V max and p99, observation freshness, metric
mode, tolerance, initialization, and pass/fail state for auditability.

V93 holds the V85 cross-track quarter-strength balance-`1.75` near miss fixed.
Its six rows independently guard max, p99, or both, each with zero or `0.0025`
fractional tolerance. It remains a Test1/Test2 seed-`1000` development-only
campaign with separate RUDY and GPUGR evaluation and the full provenance,
geometry, summary, strict-selection, and near-miss terminal sequence.

The implementation passes 100 plugin tests and 41 preset-generation tests;
Python compilation, JSON/shell validation, `git diff --check`, local matrix
generation, and a remote installed-overlay tail regression smoke also pass.
The isolated 75 MB overlay is
`/home/yifanchen/proj/ruplace-v93-monotonic-tail-guard-overlay-3583ba6`.
Config, runner, plugin base, directional plugin, and parameter SHA-256 values
are respectively
`6501776a576cd1702a4e3eb1a7dfd5f2b431769b6aa2f23776f1606ee20b741f`,
`7f2b498f701da2965914b870a72a22b3d1e486720a12621c01436ab0a1fd131c`,
`078511c700bfbd8ec2c261e8206369c33a7e05cdd9d5dc46e66357479415a67d`,
`ec71df9a6915438ee7b11425b88f1b6eb2de1cd0993d3e27af421aef1395b7b8`,
and
`247a545df3905063c6b8262e33c2778d8a29931f393ebb3375301e0172f6abd6`.
Each retained/installed source pair matches. Tmux
`ruplace-v93-monotonic-tail-guard-3583ba6` is waiting behind V92 on remote
GPU 1 and cannot access held-out or golden data.

## Directional CVaR-gradient pilot V94 (2026-08-01)

The corrected V84 frontier and the first second-pass V86 Test2 control
show the same useful-but-incomplete structure: routed wirelength, estimated
shorts, overflow nets, and several H/V overflow measures can improve while a
small set of utilization-tail or directional-congestion metrics still vetoes
promotion. The V86 control is rationale only until its active driver writes
the terminal implementation/runtime provenance and placement audit. V91-V93
limit the established overflow force through smoothing,
budgets, or a pre-force tail gate. V94 instead adds a separate default-off
objective mechanism, `directional_cvar_gradient`, which concentrates the
directional force on the excess above a detached per-axis utilization
quantile. This is a CVaR risk-objective adaptation, not a claimed reproduction
of an EDA paper.

The plugin blends the existing routed H/V overflow pressure with q95 or q99
utilization-tail excess. Tail pressure is RMS-matched to overflow pressure
before blending, so the sweep changes spatial concentration without silently
changing the established force scale. The quantile threshold is clamped to
utilization `1.0`; an easy design with no capacity excess therefore remains a
no-op. Route-direction mapping, polarity, axis balance, smoothing, field
normalization, stagnation gating, relative trust scaling, decay, and force
application budget remain independently parameterized.

V94 contains exactly HPWL plus six candidates: one overflow-only full-strength
control, q95 blends `0.25/0.5`, q99 blends `0.25/0.5`, and a q99 blend-`0.5`
half-strength row. All use matching-axis balance `1.0` and at most eight force
applications, so this experiment does not duplicate the V88 budget sweep. It
is restricted to Test1/Test2 seed `1000`, evaluates RUDY and GPUGR separately,
and uses the unchanged zero-positive-GPUGR-worst-regression selector. It cannot
access Test3, real designs, OpenROAD, or Innovus.

Local verification passes 102 plugin tests and 41 preset-generation tests,
plus Python compilation, JSON and shell validation, matrix generation, and
`git diff --check`. The isolated remote overlay is
`/home/yifanchen/proj/ruplace-v94-directional-cvar-overlay-3583ba6` and records
168 installed placement files plus six retained source files with zero missing
or mismatched source/install pairs. Plugin, registry, parameter schema, base
preset, V94 config, and runner SHA-256 values are respectively
`132458a2bbc52f3314726bec1a7e2d657c6623b2557ef049f6dcd79063ae5fa8`,
`23e793883891bc1c0585932d02732a6cb02e05420fe66004aa931a9931736bf8`,
`7eb6a3bcc7c17d5cecf83d60f50108d990b2090442a5cecec1d994f8dbe6a9de`,
`07fc4eb503bfd17e19ef4259eb76c67ba563901dfeed1adf39384bf2e821bf50`,
`b296105c22efb3a1382cccaf6ef5f6816d894a89bfc4fc65ef9381822b713146`,
and
`059d5bc5be3a21ecda1eda79b83c6629480d205c3799b3d6aefa70239cbb006d`.
Remote import, easy-case no-op, preset-generation, compilation, and provenance
smokes pass. Tmux `ruplace-v94-directional-cvar-3583ba6` is waiting behind V93
on remote GPU 1.

At 06:12, the active V86 provenance rerun had rewritten its Test2 joint
control and per-axis balance-`0.75` evaluator rows but had not yet atomically
rewritten the terminal comparison or HPWL baseline. Deltas against the retained
same-directory HPWL row are therefore tuning diagnostics only. The joint
control improves all four RUDY primaries and 14 GPUGR primaries, including
routed wirelength `-6.15%` and estimated shorts `-47.47%`, but retains eleven
GPUGR vetoes led by vertical overflow `+22.47%`, vertical congestion score
`+4.15%`, and aggregate utilization max `+0.45%`. Per-axis normalization at
balance `0.75` is decisively worse: all four RUDY primaries and 21 GPUGR
guardrails regress, including routed wirelength `+2.78%`, estimated shorts
`+12.48%`, and aggregate overflow `+93.45%`. These rows do not advance; the
formal decision still waits for the terminal provenance and placement audit.

V87 had four Test2 candidates with complete absolute RUDY/GPUGR outputs at the
same checkpoint. Full-strength balance `0.875` remains the best internal row
for routed wirelength, shorts, aggregate overflow, and RUDY overflow; lowering
full strength to balance `0.75`, or using half strength at balances
`0.875/0.75`, worsens at least one of those absolute fronts. V87 has not yet
written its same-campaign HPWL comparison, so these observations are not
baseline deltas and cannot authorize promotion.

## V86/V87 nonterminal audit checkpoint (2026-08-01 06:32 +0800)

Live process and artifact checks confirm that the hardened V86 rerun and V87
remote campaign remain active rather than stalled or terminal. V86 advanced
from its per-axis balance-`1.0` row to balance `1.25`; V87 advanced from
quarter-strength balance `0.875` to its last plugin row, quarter-strength
balance `0.75`. Both active placements continued producing external GPUGR
route artifacts every tens of seconds. V88-V94 remain serialized by explicit
tmux dependencies, and every runner was rechecked for Test1/Test2-only seed
`1000`, separate `rudy,gpugr` evaluation, the
`absolute_directional_v2` metric profile, and zero allowed positive GPUGR
worst-case regression.

The terminal Test1 comparison for each campaign passes the independent
placement-effect audit. All six candidates are intentional easy-case no-ops:
their plugin status is `selected_no_activation`, their legal DEF hash is
identical to HPWL, and none is treated as an active tuning result. The first
two freshly rewritten V86 Test2 candidates also pass an independent geometry
parse over all `72,094` components with zero overlaps, zero unplaced
components, and zero components outside placement rows. Their DEF SHA-256
values are respectively
`d3180cbf8bc3169668ea0260fc232538646b7ea2a4ef90a6646234f7e0371399`
and
`bd129d5ca1c64c6c6651a43fade580c892676dd1684fc774c80dba13838b0966`.
These hashes remain nonterminal evidence until the campaign writes matching
comparison provenance.

Runtime summaries prove that the completed Test2 rows activate the intended
plugin rather than merely selecting it. They record the configured mapping,
normalization, balance, and objective-relative strength, with approximately
10-11 congestion-gated force applications per completed row. A source review
also found no sign or H/V-order inversion: GPUGR constructs its directional
payload as `[horizontal, vertical]`, a positive congestion-map gradient is
added to the placement objective gradient, and gradient descent therefore
moves cells down the congestion gradient. V94's detached per-axis quantile,
capacity-`1.0` lower bound, easy-case no-op, and RMS-matched mixed-tail scaling
are internally consistent. This is implementation evidence, not QoR
promotion evidence.

Fresh focused verification passes `102/102` plugin tests and `41/41`
preset-generation tests. No V86 or V87 strict selector output exists yet, so
neither campaign has a survivor and no held-out or golden access is
authorized at this checkpoint.

### Immutable partial-snapshot provenance repair

The nonterminal audit exposed a validation-tool mismatch: the partial-campaign
snapshot generator reconstructed placement rows without the input,
implementation, runtime, placed-DEF, and geometry provenance now required by
the placement-effect audit. Its common-completion counter could therefore
announce a snapshot target that the stricter audit could not validate.

`tools/routability_compare.py` now atomically publishes a hash-bound
`placement_provenance.json` beside each completed method. The sidecar records
the config and placed-DEF paths and hashes, independent geometry result, input
hashes, executed placement-package hashes, and numerical runtime ABI. The
partial-snapshot generator counts only methods with this sidecar, verifies all
source hashes and method identity, requires consistent global provenance
within each comparison, and embeds the verified provenance and geometry into
the immutable comparison. Missing or tampered sidecars fail closed.

Focused verification passes snapshot `4/4`, runner `35/35`, placement-effect
audit `12/12`, summarizer `20/20`, and selector `16/16` tests, plus Python
compilation and `git diff --check`. The two updated runtime tools were deployed
to `/home/yifanchen/proj/ruplace-routability-corrected-3583ba6` before V88
started. Local and remote SHA-256 values match:
`d2c0b1533be7047a9ac2dcfab2c94cdb866a9e0257126bcf6e12f6d0a351f987`
for `routability_compare.py` and
`0b96c447228cf22796b4d4f0388a405b8a282719bd7efa32f82a616ccd53888b`
for `routability_snapshot_partial_campaign.py`. V87's already-running driver
retains its original loaded comparison code and remains valid because it will
produce a full terminal comparison rather than a partial snapshot.

## V87 terminal rejection and V88 provenance start (2026-08-01 06:49 +0800)

V87 completed both development comparisons and the strict terminal sequence.
The mandatory RUDY and GPUGR gate is validated for all seven methods in both
Test1 and Test2, all placements and evaluations were freshly rerun, and the
executed placement package reports 167 hashed files plus four retained source
files with no missing or mismatched source/install pair. The placement-effect
audit passes all 12 candidate slots: Test1 is an intentional legal no-op for
all six candidates, while every Test2 candidate is active, differs from HPWL,
and has legal geometry over 72,094 components with zero overlap, unplaced, or
uncovered components.

The strict result is `0/6` survivors. Full-strength balance `0.875` is the
clearest cross-backend near miss: it improves all four RUDY primaries and 20
GPUGR primaries, but violates the zero-positive-worst-regression contract on
GPUGR routed wirelength `+0.514913%`, overflow nets `+3.91664%`, aggregate
utilization max `+0.158234%`, vertical overflow bins `+7.74527%`, and vertical
p95 congestion score `+0.122160%`. Quarter-strength balance `0.875` also
improves all four RUDY primaries and 13 GPUGR primaries, but retains 12 GPUGR
vetoes, dominated by vertical overflow and congestion tails. The remaining
four variants are no closer: three fail the RUDY-improvement requirement and
all retain positive GPUGR worst-case regressions. V87 is therefore rejected
for held-out or golden promotion; its Pareto data may only guide subsequent
development tuning.

V88 started immediately after V87 on remote GPU 1. Its first completed Test1
method atomically published `placement_provenance.json` before evaluation,
confirming that the repaired per-method provenance contract is active in the
serialized queue. Independent readback confirms that the recorded config and
DEF hashes match their files, the geometry hash matches the DEF, all 8,879
Test1 components are legal with zero overlap, unplaced, or uncovered cells,
and the 167-file implementation fingerprint has no source/install mismatch.
V89-V94 remain waiting behind V88. The independent local V86 provenance rerun
is still active on Test2 and has reached its per-axis half-strength
balance-`1.5` row; its terminal comparison and strict selector remain pending.

## V88 Test1 audit and V86 stale-comparison guard (2026-08-01 07:01 +0800)

V88 completed its atomic Test1 comparison and started Test2. An independent
placement-effect audit over the completed comparison passes: all six capped
variants report `selected_no_activation`, are byte-identical to HPWL, and
retain legal geometry. The audit is preserved as
`summary/test1_provenance_audit.json` in the V88 overlay. All seven Test1
placements published provenance sidecars before evaluation, so V88 confirms
the repaired sidecar path across candidates and HPWL rather than for only the
first method. The active Test2 row is full strength with an application cap of
four; no Test2 placement is complete yet.

V86 remains nonterminal. Its existing Test2 `comparison.json` and top-level
summary have timestamps around 05:29 and belong to the earlier partial run;
their mere presence is not a fresh atomic boundary. The live provenance rerun
is evaluating the per-axis half-strength balance-`1.5` placement and still
must process the quarter-strength row and HPWL before it can replace that
comparison and run the strict selector. Until the comparison timestamp and
provenance change and `strict_selection.json` appears, V86 rows remain
development diagnostics only.

The first V88 Test2 placement subsequently completed and independently passes
the application-budget contract. The full-strength cap-`4` row records exactly
four plugin activations, `force_max_applications=4`, a terminal exhausted
budget, eight scheduled proxy observations, and four congestion-gate passes.
Its sidecar config and DEF hashes match the files on disk, and its fresh DEF
contains all 72,094 components with zero overlap, unplaced, or uncovered
components. This proves the cap changes runtime behavior and preserves legal
geometry; its RUDY/GPUGR QoR remains nonterminal until evaluation and the
comparison rewrite complete.

A focused regression now proves that an exhausted directional-local-gradient
application budget returns before `context.signal()` and therefore cannot
trigger another proxy evaluation. The focused test and the full plugin suite
pass (`103/103`), together with Python compilation and `git diff --check`.

The second V88 Test2 placement independently confirms the generalized budget
behavior. Full-strength cap `6` records exactly six activations, ten proxy
observations, six congestion-gate passes, and terminal budget exhaustion. Its
config and DEF hashes match the sidecar, and the 72,094-component placement is
legal with zero overlap, unplaced, or uncovered cells. Cap `4` and cap `6`
therefore both stop before later proxy evaluations once their successful-force
budgets are consumed; their comparative QoR still waits for the atomic V88
comparison and same-campaign HPWL baseline.

The next two completed V88 placements also pass. Full-strength cap `7`
records exactly seven activations from eleven observations, while half-strength
cap `4` records exactly four activations from six observations. Both report
the configured cap and terminal budget exhaustion; all config and DEF hashes
match their sidecars, and both 72,094-component placements have zero overlap,
unplaced, or uncovered cells. V88 has therefore validated four distinct
strength/budget rows without an activation-count or geometry defect and is
currently running half-strength cap `6`.

## V86 terminal rejection (2026-08-01 07:20 +0800)

V86 completed its fresh terminal sequence and has `0/6` strict survivors.
Both Test1 and Test2 mandatory RUDY/GPUGR comparisons validate, all seven
Test2 placements and fourteen proxy evaluations were rerun, and the executed
placement package records 167 files plus four retained sources with no missing
or mismatched source/install pair. The placement-effect audit passes all 12
candidate slots: every Test1 candidate is an intentional legal no-op, and
every Test2 candidate is active, differs from the fresh HPWL baseline, and is
legal.

Per-axis normalization does not solve the directional guardrails. Its best
row by GPUGR veto count, half strength with balance `1.5`, improves 18 GPUGR
primaries and two RUDY primaries. It improves GPUGR routed wirelength
`-0.114531%`, estimated shorts `-6.38947%`, overflow nets `-3.95398%`,
aggregate overflow sum `-23.4657%`, and overflow bins `-36.1661%`. It is still
rejected by seven positive GPUGR worst-case regressions: aggregate utilization
max `+5.69037%`, horizontal utilization p99 `+0.612047%`, horizontal
utilization max `+1.67548%`, vertical utilization max `+6.67578%`, horizontal
congestion score and p99 `+0.388813%`, and horizontal ACE `+0.164245%`.

The joint-normalized control remains the cross-backend Pareto intersection and
improves all four RUDY primaries plus 14 GPUGR primaries, including routed
wirelength `-3.07741%`, estimated shorts `-23.7337%`, and aggregate overflow
`-7.67315%`. It retains eleven GPUGR vetoes, led by vertical overflow
`+22.4646%` and vertical congestion score `+4.14577%`. All other per-axis rows
are weaker on either the RUDY gate or the GPUGR veto set. V86 therefore cannot
advance to held-out or golden validation; the V86 balance-`1.5` tail pattern
remains development-only evidence for the queued tail-control pilots.

## Parallel local V94 launch (2026-08-01 07:26 +0800)

The completed V86 run released the local Titan RTX, so V94 was duplicated
locally to shorten the serialized remote queue without disturbing V88-V93.
The isolated overlay is
`/mnt/nvme2n1/yifan/ruplace-v94-local-py38-overlay-3583ba6`; it reuses the
validated CPython-3.8/CUDA-11.8 binary ABI from the V86 overlay and replaces
only V94's six provenance-tracked Python/schema files. All six source/install
hash pairs match the retained remote V94 overlay, including CVaR plugin
`132458a2bbc52f3314726bec1a7e2d657c6623b2557ef049f6dcd79063ae5fa8`,
registry
`23e793883891bc1c0585932d02732a6cb02e05420fe66004aa931a9931736bf8`,
and parameter schema
`7eb6a3bcc7c17d5cecf83d60f50108d990b2090442a5cecec1d994f8dbe6a9de`.

The local overlay passes shell validation, exact source/install hashing,
overlay-precedence import, finite CVaR-pressure evaluation, both focused CVaR
unit tests, and generation of HPWL plus six V94 candidates. Its local runner
differs only by accepting an environment-controlled benchmark path map, as the
validated V86 local runner does. Tmux `ruplace-v94-local-py38-3583ba6` is
active on local GPU 0 with Test1/Test2 seed `1000`, separate RUDY and GPUGR
evaluation, and no held-out or golden access. The remote V94 tmux remains an
idle waiter behind V93; it will be removed only after the local V94 result is
terminal and independently audited, so no evidence is lost if the local run
fails.

## Force-budget provenance hardening and live V88/V94 checkpoint (2026-08-01 07:38 +0800)

The placement-effect audit now validates every effective nonnegative
force-application budget. Plugin-specific
`ruplace_<plugin>_max_applications` values take precedence over the global
`ruplace_force_max_applications` value. Each capped plugin must have a runtime
plugin summary whose final `force_max_applications` matches the effective cap
and whose `force_applications` is nonnegative and no larger than that cap.
Per-row output records the checked plugin set, count, configuration status, and
runtime error; the top-level `force_budget_checked_count` counts all checked
plugin caps. Missing, mismatched, and exceeded runtime evidence fail closed.
The audit schema remains version 2.

Four focused valid/missing/mismatched/exceeded regression cases were added.
The placement-effect suite passes `16/16`, all routability audit suites pass
`106/106`, and the plugin suite passes `103/103`; Python compilation and
`git diff --check` also pass. The broad audit run exposed and repaired a
separate production-identity omission: the final audit's exact plugin registry
now includes `directional_cvar_gradient`, so its source/install module cannot
be omitted from final golden attestation.

Both strengthened tools were deployed to
`/home/yifanchen/proj/ruplace-routability-corrected-3583ba6/tools` and compile
remotely. Local and remote SHA-256 values match:
`a5aa00449cf0a601955bfc81a3545d1045117a490facc413f3397bedd242da86`
for `routability_audit_placement_effect.py` and
`feee1e93bc44aaf976a8442a09d1b850559a962b12aefbbfc5bfabfb40376aba`
for `routability_audit_final.py`.

An independent preterminal rerun of the strengthened auditor over V88 Test1
passes all six capped rows and checks six force budgets. Remote V88 is still
running Test2 and has completed provenance sidecars for five candidates; the
sixth, half-strength cap `7`, is active. Local V94 completed its atomic Test1
comparison and independently passes: all six candidates are legal intentional
no-ops, while all six configured force caps match runtime evidence. V94 has
started Test2 with its full-strength overflow-control row. Neither campaign
has used held-out or golden evidence.

## V88 terminal rejection and V89 runner repair (2026-08-01 07:48 +0800)

V88 completed with `0/6` strict survivors. The terminal placement-effect audit
passes both comparisons and all twelve candidate slots: Test1 contains six
legal intentional no-ops, Test2 contains six active legal placements distinct
from HPWL, and all twelve configured force budgets match runtime evidence.
Every Test2 candidate has 72,094 covered components with zero overlap or
unplaced components. The six runtime application counts are exactly their
configured caps: full-strength `4/4`, `6/6`, and `7/7`, plus half-strength
`4/4`, `6/6`, and `7/7`.

An independent terminal audit and strict-selector replay are byte-identical to
the runner outputs. The placement-effect audit SHA-256 is
`c7859e883c4ebdea2295a0f5cb2974b5c61d3d0b49cce4ceccae04c7a0456ae4`;
the strict selection SHA-256 is
`0d35c368e239cf6caee962d381e38a3948783eea570387371aa01f72836207f2`.

Full-strength cap `6` is the best V88 row by GPUGR veto count. It improves all
four RUDY metrics and 19 GPUGR metrics, but retains six positive GPUGR
worst-case regressions: routed wirelength `+0.475338%`, overflow nets
`+0.879609%`, aggregate utilization max `+0.633873%`, horizontal utilization
max `+0.184854%`, vertical utilization max `+2.86153%`, and vertical overflow
bins `+2.18015%`. Full-strength cap `7` removes the routed-wirelength,
estimated-short, overflow-net, and aggregate-overflow vetoes, but retains seven
vertical-tail vetoes led by vertical overflow bins `+11.3597%`, vertical
overflow sum/RC `+2.40734%`, vertical utilization max `+3.69131%`, and
vertical congestion p95 `+0.814365%`. Application count alone therefore
cannot satisfy both routed and directional tail guardrails, and V88 is not
eligible for held-out or golden promotion.

The serialized V89 runner initially failed before placement because its inline
normalization preflight imported from the corrected repository's current
working directory ahead of the overlay `PYTHONPATH`; that older source package
does not contain the overlay-only directional module. The overlay files were
present and an interactive import succeeded, isolating the failure to stdin
Python's leading empty-path entry. `run_ruplace_v89_remote.sh` now inserts
`<overlay>/install` at `sys.path[0]` before importing. Shell validation,
an exact corrected-repository-cwd import, and `git diff --check` pass. The
first failed launcher log is preserved as `launcher.first_failed.log`.

V89 was relaunched independently on remote GPU 2 rather than delaying V90,
which had already advanced on GPU 1. Its fixed preflight reports
`V89_NORMALIZATION_OK` with directional-plugin hash
`93e92d7a8f68a581f839a6ce83761f1eca71c8ecc89ba38364e557718291518c`,
and V89 is now running Test1. V90 remains active on GPU 1, while local V94
continues Test2. All three remain development-only RUDY/GPUGR campaigns.

## V90 Test1 audit and V94 canonical-input relaunch (2026-08-01 08:00 +0800)

V90 completed its atomic Test1 comparison and moved to Test2. An independent
placement-effect audit passes all six candidates: every row is a legal
`selected_no_activation` placement byte-identical to HPWL. V90 does not
configure a finite force-application cap, so its zero force-budget check count
is expected. Test2 is now running the same-campaign overflow-feedback control
before the utilization-feedback variants.

A live plausibility check caught a second local benchmark-path error before
V94 could finish. Its first Test2 CVaR row reported implausibly zero RUDY and
GPUGR overflow and a routed-wirelength scale far below the canonical Test2
baseline. Hash inspection proved that the empty local path map resolved to the
old fixed-macro local inputs: DEF
`0a67fedcc6d197cb990aedba99c936e454e302cfbec14157219aa9c0b2b7d60f`
and LEF
`88e17b56280c37d766f47ed0a51a8fd984cdebaa1511f03cfe33819834309fb3`,
not canonical Test2 DEF
`f88564964b86f5e7124445b9551d95bfcb1015dd073d0c50f2ac03d3385e60dd`
and LEF
`74860500a13e66eea5b6d9b4c389057b5987fa497e19c871e2d392034a00fb3a`.
The affected Test2 result is invalid and has never been used for tuning,
selection, held-out, or golden evidence.

The local V94 tmux was stopped without deleting evidence. Its complete output
and launcher log are preserved at
`/mnt/nvme2n1/yifan/ruplace-v94-local-py38-overlay-3583ba6/results/directional_cvar_gradient_pilot_v94_3583ba6.invalid-input-fixed-macro-20260801T000000Z`.
V94 was relaunched from scratch with an explicit mapping from the manifest's
benchmark root to the V86 overlay's byte-identical canonical copy. The new
Test1 base config resolves to canonical DEF
`b8c8d4af0d3ee2fc775e5653a398d6836dd378df713302aa6187260cd3819afb`
and LEF
`e28d313dc139fe65165b9e756f7b12ae053434a5e62d3a7e24d7507ac6006c44`;
the mapped Test2 files independently match the canonical hashes above. The
fresh V94 run is again in Test1 and remains development-only.

A proposed adaptive-v2 96-candidate watcher was also cancelled before it
froze anything. The long-running adaptive workers predate per-method
`placement_provenance.json`, so the strengthened snapshot helper correctly
reports zero verified common candidates even though the older 64-candidate
snapshot exists. The remote `SNAPSHOT_96_STATUS.md` records
`cancelled_missing_per_method_provenance`. The adaptive workers themselves
were not stopped or modified; their eventual full comparisons remain
screening-only because the campaign also predates the V83 no-op repair.

## V89 Test1 provenance audit and live proxy checkpoint (2026-08-01 08:11 +0800)

Corrected V89 completed its atomic Test1 comparison and moved to canonical
Test2. An independent one-comparison placement-effect audit using the
strengthened remote auditor passes all six candidates. Every candidate is a
legal `selected_no_activation` placement byte-identical to HPWL; there are no
active-identical or inactive-changed rows. V89 does not configure a finite
force-application cap, so `force_budget_checked_count=0` is expected. The
independent audit SHA-256 is
`6644f5b5434bf2b95f4f61536d50866e1cb0fb622325b87e3cdee29cfa1956a5`.

V89 and V90 are concurrently running their first canonical Test2 candidates
on remote GPUs 2 and 1. V90's first Test2 placement sidecar resolves to
canonical DEF
`f88564964b86f5e7124445b9551d95bfcb1015dd073d0c50f2ac03d3385e60dd`
and LEF
`74860500a13e66eea5b6d9b4c389057b5987fa497e19c871e2d392034a00fb3a`;
its independently parsed geometry contains 72,094 covered components with
zero overlap or unplaced components. This sidecar is nonterminal provenance,
not comparative QoR evidence. The corrected local V94 campaign has advanced
through five canonical Test1 placement sidecars and remains development-only.

Corrected local V94 subsequently completed its atomic Test1 comparison. An
independent placement-effect audit passes all six candidates as legal
intentional no-ops and validates all six configured force-application caps;
the audit SHA-256 is
`994987081d8ba488626aa0297b38d483478d272d626e0e8311434704fc8dca35`.
V94 then created its fresh Test2 base config. Direct hashing confirms canonical
DEF
`f88564964b86f5e7124445b9551d95bfcb1015dd073d0c50f2ac03d3385e60dd`
and LEF
`74860500a13e66eea5b6d9b4c389057b5987fa497e19c871e2d392034a00fb3a`.
Its first Test2 overflow-control placement subsequently published a canonical
sidecar. The plugin is active with exactly `8/8` force applications; the
independent geometry record contains 72,094 covered components with zero
overlap or unplaced components. RUDY evaluation is complete but GPUGR and the
same-campaign HPWL baseline are not, so no V94 Test2 comparative QoR is yet
eligible for interpretation and the serialized remote V94 waiter remains
intact.

V89's first canonical Test2 row subsequently completed. It is the joint-
normalization control shared with V90: both campaigns emit byte-identical
placed DEF SHA-256
`fc46be0a63f5d0f8077d597c049178f49a352e632bf772245f4bbb8ddc1a46c0`,
record eight active force applications, and independently parse as 72,094
covered components with zero overlap or unplaced components. This proves the
control is reproducible across the two overlays before V89 changes
normalization or V90 changes feedback.

V90's full-strength raw-utilization row is also active, legal, and distinct
from that control, but the direct backend-local ablation is decisively worse.
Relative to the control it regresses RUDY overflow sum/bins by
`+64.1928%/+8.4674%` and RUDY utilization max/p99 by
`+33.7842%/+32.1742%`. GPUGR routed wirelength regresses `+10.5597%`,
estimated shorts `+73.9500%`, overflow nets `+13.1658%`, aggregate overflow
sum/bins `+191.423%/+178.619%`, and H/V overflow sums
`+105.369%/+124.065%`. Although H/V congestion-score tails improve, raw
utilization feedback spreads pressure outside the capacity-excess tail and is
not a viable full-strength replacement. V90 remains nonterminal while its
half- and quarter-strength rows run; no same-campaign HPWL or selector result
is inferred from this pairwise diagnostic.

The completed half- and quarter-strength balance-1.0 rows rule out simple
overpowering as the explanation. Half strength still regresses RUDY overflow
sum/p99/max by `+8.0436%/+6.6435%/+9.2741%`; GPUGR routed wirelength, shorts,
overflow nets, and aggregate overflow regress
`+4.4105%/+22.2770%/+9.9762%/+54.3870%`. Quarter strength regresses all four
RUDY primary metrics, including overflow sum `+9.7907%`, and regresses GPUGR
routed wirelength, shorts, overflow nets, and aggregate overflow by
`+0.6954%/+8.4560%/+7.1484%/+14.2368%`. Thus raw-utilization feedback is
misdirected across the tested full-to-quarter interval, not merely too strong.
V90 remains nonterminal while the balance-0.875 controls and HPWL run; they are
retained to complete the bounded interaction audit, not because any completed
utilization row is promotion-eligible.

## Per-axis CVaR interaction pilot V95 (2026-08-01 08:30 +0800)

V90's raw-utilization failure and the still-open V89/V94 normalization-tail
interaction motivate a bounded factorial follow-up rather than another broad
strength sweep. V95 changes
`ruplace_directional_cvar_gradient_normalization` from `joint` to `per_axis`
and tests overflow, q99, and q99.5 pressure at fixed tail blends/strengths. It
therefore tests whether axis normalization can retain targeted tail relief
without the broad RUDY/GPUGR regressions caused by raw utilization feedback.
The separate family spec is
`configs/routability_directional_cvar_gradient_per_axis_pilot_v95.json` and
the local runner is `run_ruplace_v95_local.sh`.

JSON parsing, shell syntax, family-preset generation, and `git diff --check`
pass. The generated preset contains HPWL plus exactly six
`directional_cvar_gradient` candidates, all with `per_axis` normalization.
V95 reuses the corrected V94 Python-3.8 install and canonical benchmark map;
the retained CVaR source/install SHA-256 matches
`132458a2bbc52f3314726bec1a7e2d657c6623b2557ef049f6dcd79063ae5fa8`.
Tmux `ruplace-v95-local-py38-3583ba6` is in phase `waiting_for_gpu` behind
`ruplace-v94-local-py38-3583ba6`. It is restricted to development Test1/Test2
seed `1000` with separate RUDY and GPUGR evaluation and cannot access held-out
or golden cases.

The first completed V94 q95/tail-25 row exposed a duplicate-control flaw in
the initial quantile grid: on all ten overflow-control route refreshes, each
per-axis q95 threshold clamps to `1.0`, so the q95 tail is exactly the existing
`(utilization-1)+` overflow pressure. RMS matching therefore produces
identical field metrics, placed DEF SHA-256, RUDY, and GPUGR results. V94's
q95 rows are retained only as diagnosed duplicate controls. Before V95 left
`waiting_for_gpu`, its two q95 rows were replaced with q99.5 tail-25/tail-50
rows. Direct route-map inspection proves q99 and q99.5 are distinct on both
axes; no V95 presets or placements existed before this correction. The
corrected preset smoke passes with four q99 metadata rows (including the
overflow control) and two q99.5 rows; preset-generator tests pass `41/41`,
plugin tests pass `103/103`, and `git diff --check` is clean.

## Capacity-conditioned directional CVaR pilot V96 (2026-08-01 08:45 +0800)

V94 proves that a quantile over every route bin can collapse to ordinary
overflow when most bins are below capacity. V96 therefore adds the separate,
default-off `directional_excess_cvar_gradient` plugin. It computes each H/V
quantile only over bins whose utilization exceeds `1.0`, clamps the resulting
threshold at capacity, and blends that tail with ordinary directional
overflow. A zero tail blend exactly reproduces the overflow control. This is
an objective-family change rather than an undocumented mode of V94/V95, so it
has an independent parameter prefix, registry entry, preset family, and test
contract.

The development Test2 route-map calibration keeps q90 and q95 materially
distinct: q90 activates `187/106` H/V bins and q95 activates `94/53` H/V bins.
The q99 tail (`19/11` H/V bins) was excluded from V96 because it is too sparse
for this first capacity-conditioned pilot. The spec
`configs/routability_directional_excess_cvar_gradient_pilot_v96.json` contains
HPWL plus six candidates: the exact overflow control, q90 and q95 tail blends
of `0.25` and `0.5`, and a half-strength q95/tail-50 row. All use the same
eight-application development budget as V94 so the objective change is the
controlled variable.

Plugin tests pass `105/105`, final-audit tests pass `28/28`, and the six-preset
overlay import smoke passes. JSON parsing, Python compilation, shell syntax,
and the relevant `git diff --check` are clean. The retained source/install
SHA-256 for `directional_excess_cvar_gradient.py` is
`4a53d3bf2edac8297c14db3c40a19d4d027da44f7698eea76c07a7611efcf409`;
the V96 spec and runner SHA-256 values are respectively
`4dce3220a6586c98d7b6f982516647eb034e605c92c8b55cda1184740be27fb8`
and `132da83748193603e7bb1e83987660cd136f513274b253cabd9a989c715ee197`.
The 132 MiB byte-matched overlay is
`/mnt/nvme2n1/yifan/ruplace-v96-local-py38-overlay-3583ba6`.

Tmux `ruplace-v96-local-py38-3583ba6` is in phase `waiting_for_gpu` behind
V95, which is itself waiting behind corrected local V94. V96 is restricted to
development Test1/Test2 seed `1000` with RUDY and GPUGR evaluated separately.
It cannot access Test3, real designs, OpenROAD, or Innovus; no promotion claim
is possible until its terminal placements pass the independent effect audit
and strict proxy selector.

## V94 first distinct q99 diagnostic (2026-08-01 08:49 +0800)

Corrected local V94 has completed four of seven Test2 methods. The q95 rows
remain the diagnosed overflow-control duplicates, while q99/tail-25 is the
first distinct CVaR placement with both backend evaluations. Its DEF SHA-256
is `8131521d5f9323dec5982addfbd0b9017efd192691ff294d112152075a070849`,
all 72,094 components are covered with zero overlap or unplaced components,
and runtime provenance records eight active force applications.

Against V94's byte-reproducible overflow control, q99/tail-25 improves RUDY
overflow sum/bins/p99 by `-28.1183%/-26.7488%/-8.9483%`, but RUDY maximum
utilization regresses `+1.4843%`. GPUGR routed wirelength improves
`-21.0389%`, overflow nets `-7.0711%`, aggregate overflow sum/bins
`-15.1471%/-23.2299%`, and vertical overflow sum/bins
`-16.0672%/-26.4248%`. Those gains do not pass the independent guardrails:
estimated shorts regress `+28.0131%`, horizontal overflow sum/bins regress
`+17.8065%/+1.2270%`, horizontal RC regresses `+17.8065%`, and both H/V
congestion-score tails regress by roughly `+11.85%` to `+15.00%`. In total,
13 of 25 primary GPUGR metrics regress. This row is therefore vetoed as a
promotion candidate even though it is informative for objective tuning.

V94 remains nonterminal while q99/tail-50, the half-strength row, and HPWL
run. The result supports the already queued V95 per-axis normalization test;
it does not authorize Test3, multi-seed, real-design, OpenROAD, or Innovus
execution.

Q99/tail-50 subsequently completed as a distinct legal placement with DEF
SHA-256
`5f298062c6f91610b65365dec2a3e87b662074c0af4ab3f05698ffd5ad011725`.
Relative to the same overflow control, all four RUDY primary metrics improve:
overflow sum/bins/p99/max change by
`-25.5860%/-29.4430%/-4.2104%/-0.6830%`. GPUGR improves 17 of 25 primary
metrics, including routed wirelength `-19.3071%`, overflow nets `-5.3136%`,
aggregate overflow sum/bins `-30.3956%/-33.9476%`, horizontal overflow
sum/bins `-0.0889%/-10.9021%`, and vertical overflow sum/bins
`-28.2836%/-36.1972%`. Increasing the tail blend from `0.25` to `0.50`
therefore reduces the GPUGR regression count from 13 to eight. It still fails
the zero-regression gate: estimated shorts regress `+18.3567%`, horizontal
maximum utilization `+1.8672%`, and the six H/V congestion score, p95, and p99
metrics regress by `+9.4477%` to `+13.7376%`. The half-strength row remains
necessary to separate blend concentration from total force magnitude.

## V94 terminal audit and capacity-absolute proxy policy V3 (2026-08-01 09:11 +0800)

Corrected local V94 completed both development cases and all seven methods.
The runner's placement-effect audit passes all two expected comparisons and
its frozen `absolute_directional_v2` selector retains `0/6`. An independent
replay under
`/mnt/nvme2n1/yifan/ruplace-v94-local-py38-overlay-3583ba6/results/directional_cvar_gradient_pilot_v94_3583ba6/summary_independent_capacity_policy_20260801T0104Z`
also passes all two placement comparisons. The independent placement-audit,
V2 selection, and screening-summary SHA-256 values are respectively
`fea3168cbb1762ee66c0f76ad48674ca9ca640c4ffbfb6793d23c9ca40ce4e1e`,
`ef77d19e7c069d7534e8f56f9cd643b5cb0b9556e5827c5224ebe4d3f1a27085`,
and `8dab641902e83dbace5bfbcc4f68829b5459a9b72d3adec81bc08c70e650875d`.
The idle remote V94 waiter was then removed to prevent duplicate execution;
its overlay and `waiting_for_gpu` status artifact remain retained.

The terminal comparison exposes a metric-policy defect rather than a hidden
survivor. `horizontal_congestion_score*` and `vertical_congestion_score*` are
implemented as p99/mean or p95/mean. V94's q99/tail-50 half-strength row lowers
absolute H/V p99, max, overflow, ACE, and RC relative to the overflow control,
but the ratios rise because mean utilization falls faster. These ratios measure
spatial concentration, not routing-capacity demand. The existing
`absolute_directional_v2` profile is frozen for reproducibility, and the new
versioned `absolute_directional_v3` profile keeps routed wirelength, shorts,
overflow nets, aggregate and H/V overflow, absolute utilization p99/max, ACE,
and RC as independent primary metrics while moving the six normalized ratios
to diagnostics. Selector and near-miss tests pass `17/17` and `10/10`; both
CLIs expose V3. The independent V3 selection SHA-256 is
`7b6cc7ea4138eaf52e53a6cb19bc160be34e049d1d42c80b5d9eed8e2e7958d6`.

V3 still retains `0/6`, so it does not relax away real congestion failures.
Against HPWL, q99/tail-50 half improves every RUDY primary metric and GPUGR
routed wirelength, shorts, overflow nets, horizontal overflow, both ACE values,
and most absolute utilization tails. It nevertheless regresses GPUGR aggregate
p99/max by `+0.0916%/+1.4808%` and vertical overflow sum/bins, RC, and p99 by
`+17.6021%/+2.4702%/+17.6021%/+0.5159%`. It therefore remains a near miss, not
a proxy survivor or golden candidate.

## Directional CVaR vertical-balance pilot V97 (2026-08-01 09:11 +0800)

V97 targets those remaining vertical regressions while preserving the strong
q99/tail-50 half-strength response. It fixes every V94 objective and schedule
parameter except matching-axis balance, which is swept over
`1.0/0.9375/0.875/0.75/0.625/0.5`. Lower balance weakens X response and
strengthens Y response, matching the observed excess horizontal improvement
and residual vertical regression. The spec and runner are
`configs/routability_directional_cvar_gradient_vertical_balance_pilot_v97.json`
and `run_ruplace_v97_local.sh`; their SHA-256 values are
`7fee7d02ad276b76e9e16720d011c5073db5dcd7291292f73a78ed6e47b79ab8`
and `8f34635297c3312f07bcc48074bc5ab72fceb9f39e60958f6ceb08d8872c5d2a`.

Shell/JSON/whitespace checks pass, generation produces exactly HPWL plus six
balance candidates, and generator/selector/near-miss tests pass
`41/41`, `17/17`, and `10/10`. Tmux
`ruplace-v97-local-py38-3583ba6` is in phase `waiting_for_gpu` behind V96 and
uses the capacity-absolute V3 gate. V95 is now running the corrected per-axis
q99/q99.5 grid with all six rows carrying `per_axis` normalization and the
byte-matched V94 plugin SHA-256
`132458a2bbc52f3314726bec1a7e2d657c6623b2557ef049f6dcd79063ae5fa8`;
V96 remains behind V95. All three are development-only and cannot access
Test3, real designs, OpenROAD, or Innovus.

## V90 terminal V3 audit and utilization refinement V98 (2026-08-01 09:34 +0800)

V90 completed both development cases and all seven methods. An independent
replay under
`/home/yifanchen/proj/ruplace-v90-matching-utilization-overlay-3583ba6/results/directional_local_gradient_matching_utilization_pilot_v90_3583ba6/summary_independent_v2_v3_20260801T0123Z`
passes the two-comparison placement-effect contract and selects `0/6` under
both frozen V2 and capacity-absolute V3. The placement-effect, V2 selection,
V3 selection, and V3 near-miss SHA-256 values are respectively
`b687b1d031d45ab41a0938ea3c8e1b36b296c2755aaa18d3f050a36109331b48`,
`c2e92d2de3a4baaa29583ed9165746afc29ddccdce6bbffc6b5526d113b267bd`,
`2f97df06c3b23b4136a9e9630483b167ec05f9ab45cf0a12fafe549b73ea833a`,
and
`b7cd432033dba230721dde5ea7d6786fb70e2c92cd07250d63194e1e6e1e1555`.

The final HPWL-referenced result changes the earlier control-relative
interpretation of V90's quarter-strength balance-1.0 row. On active Test2 it
improves all four RUDY primaries: overflow sum/bins and utilization p99/max
change by `-9.4168%/-2.6469%/-5.6483%/-5.6224%`. It improves 18 of 19 V3
GPUGR primaries, including routed wirelength `-1.2764%`, estimated shorts
`-11.4747%`, overflow nets `-2.0366%`, aggregate overflow sum/bins
`-17.9508%/-13.4828%`, horizontal overflow sum/bins
`-31.3494%/-26.2963%`, vertical overflow sum/bins `-8.0270%/-4.6472%`, both
RC values by the corresponding `-31.3494%/-8.0270%`, and both p99 and ACE
directions. Its only primary veto is vertical absolute utilization max
`+1.19097%`; normalized concentration scores are diagnostics under V3. The
row applied 11 congestion-gated forces and remains a near miss, not a proxy
survivor.

V98 isolates the two plausible fixes without changing plugin implementation:
it retains V90's utilization feedback, joint normalization, matching-axis
mapping, balance `1.0`, smoothing, gate, refresh, and seed/case scope. It
compares the unlimited quarter-strength control against `7/8`, `3/4`, and
`5/8` of that strength plus quarter-strength application caps `8` and `10`.
The spec and runner are
`configs/routability_directional_local_gradient_utilization_refinement_pilot_v98.json`
and `run_ruplace_v98_remote.sh`, with SHA-256 values
`2ddef2be3a1a92f0b1b51bf3a5e729576a8ff67200f04e81be5cdb579433fafb`
and `a5689a70591916ea90eae0b63e5ba8aa5a542e05f4d251acca840881e2caa5d4`.
JSON, shell, and whitespace checks pass; generation produces exactly HPWL plus
six candidates, and generator/selector/near-miss tests pass `41/41`, `17/17`,
and `10/10`. Remote tmux
`ruplace-v98-utilization-refinement-3583ba6` waits behind V89 on GPU 2 in
isolated root
`/home/yifanchen/proj/ruplace-v98-utilization-refinement-3583ba6`. It uses V3
and cannot access Test3, real designs, OpenROAD, or Innovus.

Before V98 left `waiting_for_gpu`, an effective-control audit found two preset
representation differences from V90: V98 explicitly selected the existing
default joint normalization, while it relied on the existing default `1.0`
utilization gate instead of carrying V90's explicit value. Both were runtime-
equivalent, but exact experimental reproduction requires identical effective
presets. The spec now omits the redundant normalization key and explicitly
sets `ruplace_force_gate_utilization_threshold=1.0`. Its new config SHA-256 is
the value above; the runner hash is unchanged. The corrected remote preset
SHA-256 is
`4c4620b0e4ab3606290c997ecd00773d44dec1d0afaab64253b965be57a2a9ca`,
and a full key/value comparison against V90's quarter-strength balance-1.0 row
has an empty diff. V98 remained waiting throughout the correction, so no
placement artifact used the superseded spec.

## V95 first per-axis Test2 ablation (2026-08-01 09:37 +0800)

V95's per-axis overflow control completed canonical Test2 placement and both
proxy evaluations. Its DEF SHA-256 is
`82d729b0fddbd7c6d272f88e26bd9cf872c46c95764393c949f1d002463a9061`;
the geometry sidecar covers all 72,094 components with zero overlap, unplaced,
or uncovered components. Runtime summary data confirms per-axis normalization
and exactly `8/8` congestion-gated applications. Relative to V94's joint-
normalization overflow control on the same canonical input, per-axis
normalization improves all four absolute RUDY primaries, GPUGR routed
wirelength `-24.7702%`, shorts `-39.1806%`, overflow nets `-12.2180%`,
aggregate overflow sum/bins `-56.9602%/-58.1798%`, horizontal overflow
sum/bins `-59.6550%/-56.5256%`, and vertical overflow sum/bins
`-40.4384%/-46.8253%`. Both RC values, absolute p99/max values, and ACE values
also improve. The six normalized concentration ratios worsen because mean
demand falls faster and remain V3 diagnostics.

Against V94's byte-stable HPWL reference, the same row improves all four RUDY
primaries and 16 of 19 V3 GPUGR primaries, including routed wirelength
`-7.4218%`, shorts `-50.0950%`, overflow nets `-12.2049%`, aggregate overflow
sum/bins `-17.0326%/-28.8504%`, and horizontal overflow sum/bins
`-58.5406%/-53.5958%`. It is still vetoed provisionally by vertical overflow
sum and RC `+9.1655%` and vertical utilization p99 `+0.4743%`; no own-campaign
HPWL, terminal placement audit, or V3 selection exists yet. The q99.5/tail-25
row is already broadly destructive versus the same reference, with three of
four RUDY and 18 of 19 GPUGR primaries regressing. V95 continues unchanged so
the remaining tail blends and same-campaign HPWL can decide the family.

V95's q99/tail-25 row is closer than the overflow-only control. Against the
same canonical HPWL reference it improves all four RUDY primaries and 16 of 19
V3 GPUGR primaries, including routed wirelength `-6.9165%`, shorts
`-53.4197%`, overflow nets `-11.2941%`, aggregate overflow sum/bins
`-26.3491%/-33.3883%`, and horizontal overflow sum/bins
`-66.9988%/-60.0968%`. The only provisional vetoes are vertical overflow sum
and RC `+3.6368%` and vertical p99 `+0.3608%`; vertical overflow bins, max,
and ACE all improve. The legal placed DEF SHA-256 is
`d196bb5f5116fc75fef35f5ae49c1248b393a91a956aedbbd201372f83818467`.
This row is not selected because V95 still lacks its own Test2 HPWL and
terminal audits. Q99/tail-50 and its half-strength variant remain necessary
before deciding whether a separate tail-aware balance refinement is warranted.

The q99.5/tail-50 row subsequently completed and confirms that increasing tail
blend does not repair the directional tradeoff. It improves all four RUDY
primaries, GPUGR routed wirelength `-5.8979%`, shorts `-48.0277%`, overflow
nets `-12.4072%`, and horizontal overflow sum/bins
`-60.2350%/-52.3575%` against V94's HPWL reference. It nevertheless regresses
seven of 19 V3 GPUGR primaries: aggregate overflow sum `+0.3692%`, aggregate
p99/max `+0.3024%/+0.8475%`, vertical overflow sum/bins and RC
`+35.2810%/+11.1905%/+35.2810%`, and vertical p99 `+0.8115%`. The per-axis
overflow-only control remains V95's best completed point.

## Per-axis CVaR balance refinement V99 (2026-08-01 09:47 +0800)

V99 targets only the three remaining V95 overflow-control vetoes. It preserves
per-axis normalization, matching-axis mapping, overflow-only pressure, full
strength, smoothing, stagnation gate, refresh interval, and the validated
eight-application cap, while sweeping axis balance over the bounded interval
`1.0/0.984375/0.96875/0.9375/0.90625/0.875`. Lower balance weakens the already
over-improved horizontal response and strengthens the residual vertical
response. No objective, schedule, benchmark, seed, or selection-policy
parameter changes within the six-row comparison.

The spec and runner are
`configs/routability_directional_cvar_gradient_per_axis_balance_pilot_v99.json`
and `run_ruplace_v99_remote.sh`, with SHA-256 values
`536a57e7369f9a9cb2924d669af0cf8fde3eb776c3d52d20fb81de07c8e33ee8`
and `4418a7f425700597d098dd726fd07b54f65d914c0e6ef7630848ee7a4ad67347`.
JSON, shell, whitespace, preset, and remote import checks pass; generation
produces exactly HPWL plus six candidates, and generator/selector/near-miss
tests pass `41/41`, `17/17`, and `10/10`. The remote overlay at
`/home/yifanchen/proj/ruplace-v99-per-axis-cvar-overlay-3583ba6` copies only
V94's retained install/source/config snapshot. All five required source and
installed files match byte-for-byte, including CVaR plugin SHA-256
`132458a2bbc52f3314726bec1a7e2d657c6623b2557ef049f6dcd79063ae5fa8`.
Tmux `ruplace-v99-per-axis-cvar-3583ba6` waits behind V98 on remote GPU 2,
uses V3, and cannot access Test3, real designs, OpenROAD, or Innovus.

## V95 q99/tail-50 full result (2026-08-01 09:58 +0800)

V95's per-axis q99/tail-50 full-strength row completed legal Test2 placement
and both proxy evaluations. Against the byte-stable V94 HPWL reference, only
three of four RUDY primaries improve: overflow sum, p99, and maximum change by
`-1.0466%/-3.0538%/-6.7862%`, while overflow bins regress `+3.0114%`.
Only eight of 19 capacity-absolute V3 GPUGR primaries improve. Routed
wirelength, shorts, overflow nets, and horizontal overflow sum/bins change by
`-1.2725%/-2.9151%/-2.2056%/-3.7253%/-5.0960%`, but aggregate overflow
sum/bins regress `+38.6899%/+8.0308%` and vertical overflow sum/bins and RC
regress `+47.9245%/+9.8214%/+47.9245%`. Vertical p99/max and both ACE
directions also regress. This row is decisively worse than q99/tail-25 and
cannot be promoted.

## V89 terminal replay and q99/tail-25 balance pilot V100 (2026-08-01 10:01 +0800)

V89 completed both development cases and all seven methods. Its runner
selected `0/6` under the frozen V2 policy. An independent current-analysis
replay at
`/home/yifanchen/proj/ruplace-v89-matching-normalization-overlay-3583ba6/results/directional_local_gradient_matching_normalization_pilot_v89_3583ba6/summary_independent_v2_v3_20260801T020028Z`
passes the two-comparison placement-effect audit and selects `0/6` under both
V2 and V3. SHA-256 values for the placement-effect audit, screening summary,
V2 selection, V3 selection, and V3 near-miss analysis are respectively
`e9388aef2c41887aaef2d7f3c37317381b168212a8d7fdfe7b3c1ecb8d990ea6`,
`0096b32be03f540952e355a872497d4a13e331c6b7385c4fe588c364ad49c6cd`,
`028fb4f72a3a2af034ddd77ecf79db1808d046447890e51971ed25c674ebe26e`,
`c01976f942391a8319e82b59695baef00b25d7c416725875309f2af1531f36d9`,
and `5d008994364356e6119fe2a8cef440f365260630292b1b30d1e5e1d4b2cf4d96`.

V89's joint-normalized full-strength control is its closest V3 point. It
improves all four RUDY primaries and 17 of 19 GPUGR primaries; its only V3
vetoes are aggregate utilization maximum `+0.7398%` and horizontal
utilization maximum `+1.2350%`. This remains a near miss, not a proxy
survivor. V98 started automatically after V89 and is now testing the still
closer V90 utilization-feedback point, which had only one V3 veto.

V95's q99/tail-25 row remains the justified tail-aware branch because its
three provisional vetoes are much smaller than q99/tail-50's broad
regressions. V100 preserves every q99/tail-25 objective and schedule control
while sweeping matching-axis balance over
`1.0/0.9921875/0.984375/0.96875/0.9375/0.90625`. Its config and runner are
`configs/routability_directional_cvar_gradient_per_axis_tail25_balance_pilot_v100.json`
and `run_ruplace_v100_remote.sh`, with SHA-256 values
`6f950a849ab7be528ccc15c8480fcd19a08c670ab8b6c9127323d2364d157b76`
and `4a2c2bbeaea2a8f41154ae9d980d65589229a935a4c4ae492e3ef6df68a660f7`.
The V100 balance-1 control is exactly equal to V95 q99/tail-25 locally and in
the isolated remote overlay; all five retained source/install pairs match.
Generator tests pass `44/44`, including exact V98/V90, V99/V95, and V100/V95
control invariants. Tmux `ruplace-v100-per-axis-tail25-3583ba6` is in phase
`waiting_for_gpu` behind V99 on remote GPU 2. V100 is development-only and
cannot access Test3, real designs, OpenROAD, or Innovus.

## V95 terminal V2/V3 audit (2026-08-01 10:04 +0800)

V95 completed both development cases and all seven methods. The runner's
placement-effect audit passes and its frozen V2 selector retains `0/6`. An
independent replay at
`/mnt/nvme2n1/yifan/ruplace-v95-local-py38-3583ba6/results/directional_cvar_gradient_per_axis_pilot_v95_3583ba6/summary_independent_v2_v3_20260801T020356Z`
also passes both expected placement comparisons and selects `0/6` under V2
and V3. SHA-256 values for its placement audit, screening summary, V2
selection, V3 selection, and V3 near-miss analysis are respectively
`469e2e148f8bfe42d20275efb8083a8748918e8df8f8d90bc70d7b9cc26d28a8`,
`81ee5680a574de99a5f93bfe511a8baa507cf4c59a123e2ac15d637675ef77fc`,
`2fea02264c0db078331d1d396672eab9eb63f6149cd2ba77a9da221a8ddf65c9`,
`66efee1dca32d26bc2931779a0dfd2aaf73644a482225ed2de666cf6eaec88bb`,
and `e17bf8faaa0aeb74514ea5f7d80c46fb6396ae8a8a46bda26fa6e7026bb08dd6`.

The same-campaign terminal comparison confirms q99/tail-25 as V95's unique
cross-backend worst-case Pareto point. It improves all four RUDY primaries and
16 of 19 V3 GPUGR primaries. Its only vetoes remain vertical overflow sum and
RC `+3.63675%` and vertical utilization p99 `+0.360792%`. The overflow-only
control also improves `4/4` RUDY and `16/19` GPUGR metrics but has larger
vetoes: vertical overflow/RC `+9.16549%` and vertical p99 `+0.474258%`.
Q99/tail-50 half strength improves only `3/4` RUDY and `9/19` GPUGR metrics,
so it does not displace either balance-refinement branch. V99 and V100 remain
the evidence-driven next experiments; no V95 row is admitted to held-out or
golden validation. V96 started automatically after V95, and V97 remains
queued behind V96 on local GPU 0.
## V96 Test1 inactivity and severity-gated comparator V101 (2026-08-01 10:19 +0800)

The partial V96 run established that its stagnation gate is inactive on the
easy Test1 case; it did not establish a campaign-wide no-op. The control and
first three completed non-control Test1 methods
all emitted the same final DEF SHA-256
`c61fd85e34f4ef899a7f8b7ec086df7a467c768d130848ece131b799f0636b8c`.
Their RUDY and GPUGR metric payloads are identical. Each placement log reports
`491` gradient attempts, `24` scheduled force opportunities, zero gate passes,
zero gradient activations, and zero successful force applications. The common
cause is the V96 setting `ruplace_force_stagnation_window=3`: the selected
pressure improved between most GPUGR refreshes, so the monotonically
non-improving gate vetoed every scheduled application. The contemporaneous
V91 and V98 Test1 snapshots show the same inactive, byte-identical behavior,
and the placement-effect audit correctly accepts inactive methods on this
uncongested case. V96 was paused before finishing Test1, its partial artifacts
were retained, and it is queued to resume after V101 so congested Test2 can
determine whether the stagnation-gated policy activates. Its partial Test1
tree alone is not admissible selection evidence.

V101 is the isolated severity-gated comparator. It retains V96's
capacity-conditioned CVaR
implementation, quantile/tail grid, weights, matching-axis response, joint
normalization, relative scaling, refresh/application interval, severity
thresholds, and eight-successful-application budget. Its only generated-preset
change is `ruplace_force_stagnation_window: 3 -> 1`, which disables the
monotonic-stagnation requirement while retaining the minimum overflow-sum and
overflow-bin severity gates. The spec and runner are
`configs/routability_directional_excess_cvar_gradient_severity_pilot_v101.json`
and `run_ruplace_v101_local.sh`; their SHA-256 values are
`097daff363bbda4e8578d663c62f413911342d13a28a5b50dd6eea5e6a69896d`
and
`1a776ebc8d77c45755ae37f253f0e7d03f71d46ffe4b70eea3d703ba9f67a9e4`.
Generation produces HPWL plus exactly six development-only candidates, the
exact V96-to-V101 delta invariant passes, the complete generator suite passes
`45/45`, plugin tests pass `105/105`, gate tests pass `5/5`, and JSON, shell,
whitespace, and generated-manifest checks pass. Tmux
`ruplace-v101-local-py38-3583ba6` is waiting behind the now-running V97 on
local GPU 0 and will select under `absolute_directional_v3`.

The accompanying implementation audit found the H/V payload order preserved
as `[horizontal, vertical]` from GPUGR through `CongestionSignal`; map axes,
physical bin scaling, per-axis normalization, balance scaling, repulsive
descent sign, successful-application accounting, and CVaR/excess-CVaR
parameter dispatch agree with the focused tests and runtime provenance. No
source defect in those paths is established. The proven defect is that V96's
stagnation-gate tuning prevented the new objective from being exercised on
Test1; V96 Test2 and V101 remain necessary to distinguish selective gating
from a campaign-wide no-op.

V98 Test1 also completed during this audit. Its
`quarter_unbounded_control` final DEF is byte-identical to V90's
`utilization_quarter_balance1` control, with the same SHA-256 above, and the
structured RUDY and GPUGR metric dictionaries compare equal. This validates
runtime control reproduction; raw evaluator JSON is not compared bytewise
because it contains run-specific paths and runtimes. V98 is now running Test2.
V97 is running Test1, V91 is running Test2 remotely, and V99/V100 remain
serialized behind V98. No Test3, real-design, OpenROAD, or Innovus promotion
is authorized by this evidence.

## V99/V100 remote ABI repair and relaunch (2026-08-01 10:39 +0800)

The first V99 and V100 remote attempts were invalid launch failures rather
than routability results. Both isolated output overlays contained 61 compiled
DREAMPlace extensions copied from the local CPython 3.8 installation, while
`ceca2080x4` runs CPython 3.9. Every one of the 14 attempted method/case rows
in each campaign failed before placement with
`ModuleNotFoundError: No module named
'dreamplace.ops.place_io.place_io_cpp'`; neither campaign produced an
evaluation `summary.json`. The old launch logs and status snapshots are
preserved as `launcher.failed_py38_20260801T0231Z.log` and
`RUN_STATUS.failed_py38_20260801T0231Z.md` under their respective V99/V100
roots.

The corrected runners now separate the executable install from the output
root. Both use the complete CPython 3.9 install at
`/home/yifanchen/proj/ruplace-v94-directional-cvar-overlay-3583ba6` and retain
their own specs, current-analysis tools, and campaign outputs under the V99
and V100 roots. All five required V99/V100 source files are byte-identical to
that V94 install, including the directional CVaR plugin SHA-256
`132458a2bbc52f3314726bec1a7e2d657c6623b2557ef049f6dcd79063ae5fa8`.
The launch preflight now derives the active interpreter's extension suffix,
requires and imports eight essential placement extensions, and rejects any
extension loaded outside the selected install overlay. Remote validation
passes as `V99_SNAPSHOT_OK 5 files 8 extensions`.

The corrected V99 and V100 runner SHA-256 values are respectively
`63a287282ee19d01e646e46bb6ab724475dca8514e5b53c7a414c56e285e7358`
and
`06e9e175fc60cddaa4ea8f2b81341f2a0b15daa9da28f19ca3bbda20d86e46a3`.
V99 was relaunched in tmux `ruplace-v99-per-axis-cvar-3583ba6` on remote GPU
0 and is executing its first Test1 placement through the V94 install. V100 is
in tmux `ruplace-v100-per-axis-tail25-3583ba6`, phase `waiting_for_gpu`, and
will start on GPU 0 only after V99 exits. The original failed artifacts remain
for audit, but `--resume` is actively retrying the incomplete rows. Neither
campaign is eligible for held-out or golden promotion until both cases finish,
the placement-effect audit passes, and the independent V3 selector admits a
candidate.

## V91 terminal V2/V3 audit (2026-08-01 10:50 +0800)

V91 completed both development cases and all seven methods with successful
RUDY and GPUGR results. The runner's frozen V2 policy selected `0/6`. An
independent replay using the retained current-analysis bundle at
`/home/yifanchen/proj/ruplace-v91-cross-tail-control-overlay-3583ba6/results/directional_local_gradient_cross_tail_control_pilot_v91_3583ba6/summary_independent_v2_v3_20260801T0247Z`
also selects `0/6` under V2 and V3. Its placement-effect audit passes both
expected comparisons: all six Test2 candidate placements changed, all six
inactive Test1 placements remained identical, and no active candidate was a
no-op.

The smooth-1 unbounded control is V91's closest V3 point. On active Test2 it
improves all four RUDY primaries: overflow sum/bins and utilization p99/max
change by `-15.2085%/-4.4101%/-9.9802%/-8.8208%`. It improves 17 of 19 V3
GPUGR primaries, including routed wirelength `-0.7334%`, estimated shorts
`-15.7457%`, overflow nets `-3.7898%`, aggregate overflow sum/bins
`-22.6711%/-18.5980%`, horizontal overflow sum/bins
`-34.2666%/-31.9012%`, and vertical overflow sum and RC `-7.2998%`. Its two
vetoes are aggregate utilization maximum `+2.6186%` and vertical overflow
bins `+0.2008%`. Smoothing radii 2, 4, and 8 have broader vertical and/or
routed-wirelength regressions; application caps 6 and 8 introduce RUDY or
additional GPUGR vetoes. Therefore neither smoothing nor the tested
application caps repair the directional tradeoff, and V91 is not eligible for
Test3, real-design, OpenROAD, or Innovus promotion.

SHA-256 values for the independent placement audit, screening summary, V2
selection, V3 selection, and V3 near-miss analysis are respectively
`c468009046e63b821314d787592642108e253b3988dfc6dd93b71fd80c57ba99`,
`129063a1ea34388ba72efd98f1af06ba260c8561f7f1687f02adbd06c6a3beb7`,
`bd4fb42f068e0e3d358bcfc2214a56c4d34d2644debf652d1280302f327120d7`,
`361f818352014dc6b00f71cbc150572562bc68ddbd97529ef1e026caec959ea8`,
and `0fee3953756bf0a526f685d6db6283ac85c8165b33c3b6b7bb53231c64359e98`.

At `2026-08-01 10:51 +0800`, counting a row as complete only when its
evaluation summary contains successful results from both RUDY and GPUGR, the
active queue is: V92 `1/14` complete after starting behind terminal V91; V98
`8/14` complete with one current partial evaluation; repaired V99 `5/14`
complete; and V100 waiting behind V99. Locally, V97 is `10/14` complete, V101
waits behind V97, and retained V96 (`7/14`, Test1 only) waits behind V101. No
row from these partial campaigns is promotion evidence.

## V97 partial response and complementary-balance pilot V102 (2026-08-01 11:00 +0800)

The first four complete V97 Test2 rows establish a nonmonotonic balance
response; V97 must still finish before any terminal decision. Against the
byte-stable V94 HPWL reference, the balance-1 control improves all four RUDY
primaries and 13/19 V3 GPUGR primaries, including routed wirelength `-5.6161%`,
estimated shorts `-46.8351%`, overflow nets `-6.1577%`, aggregate overflow sum
`-9.4570%`, and horizontal overflow sum `-58.8890%`. Its main directional veto
is vertical overflow sum and RC `+17.6021%`, with vertical overflow bins
`+2.4702%` and aggregate utilization maximum `+1.4808%`.

Reducing matching-axis balance from `1.0` to `0.9375` and `0.875` does not
repair those vetoes. Vertical overflow sum/RC worsen to `+44.5586%` and
`+27.8238%`, respectively; both rows also regress aggregate overflow sum.
The completed balance-`0.75` row then crosses that local regression interval.
It improves all four RUDY primaries and 18/19 V3 GPUGR primaries, including
routed wirelength `-9.4242%`, estimated shorts `-47.2650%`, overflow nets
`-11.1367%`, aggregate overflow sum/bins `-18.1804%/-25.0550%`, horizontal
overflow sum/bins `-53.5895%/-52.0638%`, and vertical overflow sum/bins and RC
`-1.6921%/-12.7381%/-1.6921%`. Its sole provisional veto is vertical
utilization p99 `+0.1529%`; vertical maximum and ACE both improve. Source
inspection confirms that the implementation is not inverted:
`directional_local_gradient_field` multiplies X by `sqrt(axis_balance)` and
divides Y by the same factor before final joint normalization. These partial
rows remain tuning evidence only; they cannot be selected before V97's own
HPWL, placement-effect audit, and terminal V3 analysis exist.

V102 retains a complementary fine X-biased response without changing the
plugin implementation. It reproduces V97 balance 1.0 exactly and sweeps only
`ruplace_directional_cvar_gradient_axis_balance` over
`1.0/1.015625/1.03125/1.0625/1.09375/1.125`; every objective, schedule,
normalization, mapping, gate, benchmark, seed, and evaluator remains fixed. The
spec and
runner are
`configs/routability_directional_cvar_gradient_x_bias_pilot_v102.json` and
`run_ruplace_v102_local.sh`, with SHA-256 values
`cc56dbb226330b35a58dee6a28937177bbe01f588db5465360350b631cf98dcc`
and
`12985a89adce360aa11b63d7036418024661d3be1e148bcb56a5669c0a3db2e3`.
Generation produces exactly HPWL plus six candidates, the exact-control and
axis-balance-only invariants pass, the generator suite passes `46/46`, and all
eight required local compiled extensions import successfully. Tmux
`ruplace-v102-local-py38-3583ba6` is in phase `waiting_for_gpu` behind V96,
which itself remains behind V101 and V97. V102 is development-only and cannot
access Test3, real designs, OpenROAD, or Innovus. If terminal V97 admits a
strict survivor, V102 must be canceled before it leaves the wait state so the
survivor receives mandatory multiseed proxy validation instead.

The subsequent V97 balance-`0.625` row confirms that the transition is narrow.
It improves 18/19 V3 GPUGR primaries, including vertical utilization p99
`-1.3611%`, vertical overflow sum/bins and RC
`-48.5407%/-35.5952%/-48.5407%`, but regresses horizontal utilization maximum
`+0.5732%`. More importantly, it fails the independent RUDY gate: overflow
bins and utilization p99/max regress `+2.0727%/+4.1567%/+4.1900%`. Balance
`0.75` and `0.625` therefore bracket the observed tradeoff. Linear
interpolation of the sole `0.75` GPUGR veto places its zero crossing near
balance `0.737`, while the three RUDY crossings remain below about `0.674`;
the interval is promising but only a measured fine sweep can establish a
zero-veto point.

V103 reproduces the V97 balance-`0.75` row exactly and changes only
`ruplace_directional_cvar_gradient_axis_balance` over the binary-exact grid
`0.75/0.74609375/0.7421875/0.73828125/0.734375/0.73046875`. Its spec and runner
are
`configs/routability_directional_cvar_gradient_balance_transition_pilot_v103.json`
and `run_ruplace_v103_local.sh`, with SHA-256 values
`ae28e11ef09ab623a7508d5b24c3b3a8401fe596227e263087288fda1c9bdae2`
and
`5ca871cc9e054c8d3b233bf2ec14db27a6c0bd87c0e1b00a37ec307bb6f77ff9`.
Generation produces exactly HPWL plus six candidates, the exact-control and
axis-balance-only invariants pass, and the generator suite passes `47/47`.
Tmux `ruplace-v103-local-py38-3583ba6` waits behind V96; V102 was moved behind
V103. If terminal V97 admits a strict survivor, both refinements must remain
paused while that survivor receives mandatory multiseed proxy validation.

## V97 terminal V2/V3 audit and queue continuation (2026-08-01 11:17 +0800)

V97 completed all 14 method/case rows with successful, separate RUDY and
GPUGR results. The runner's frozen `absolute_directional_v3` selector admits
`0/6` candidates. A fresh replay under
`/mnt/nvme2n1/yifan/ruplace-v97-local-py38-3583ba6/results/directional_cvar_gradient_vertical_balance_pilot_v97_3583ba6/summary_independent_v2_v3_20260801T0316Z`
independently regenerated the screening summary and placement-effect audit and
also selects `0/6` under both `absolute_directional_v2` and
`absolute_directional_v3`.

The same-campaign V97 Test2 HPWL DEF is byte-identical to the frozen V94 HPWL
control, with SHA-256
`8c34f39dda925842233b3adc62fc8bf48bae3f94d7c26b582f907ec16f65371a`.
After excluding run-path and runtime metadata, all 42 GPUGR metrics and all 15
RUDY metrics are also exactly equal. The V97 deltas therefore do not depend on
baseline drift between campaigns.

The placement-effect audit passes: all six active Test2 placements differ
from same-campaign HPWL, all six intentionally inactive Test1 placements are
byte-identical to same-campaign HPWL, all 12 force-budget checks pass, and all
12 audited placement geometries are legal. Balance `0.75` remains the closest
V3 near miss. It improves all four RUDY primaries and 18/19 guarded GPUGR
primaries, but vertical utilization p99 regresses `+0.152917%`. Balance
`0.625` repairs that metric but regresses GPUGR horizontal utilization maximum
`+0.573217%` and fails three RUDY primaries. Balance `0.5` moves farther from
the gate: it improves none of the four RUDY primaries and regresses 13/19 V3
GPUGR primaries, including routed wirelength `+7.66241%`, overflow nets
`+8.20028%`, and vertical overflow sum/RC `+157.119%`.

SHA-256 values for the independently generated screening summary, raw table,
placement audit, V2 selection, V3 selection, and V3 near-miss analysis are
respectively
`2363999203055c8bac88f4feb502ae82c6996c7da6baaeafa082e7f338e8590f`,
`806be2cc71f0627f7b477d55572cc985272b966eb7b309d8635c3ba099e89887`,
`21b612140a3be1de5e1b9399b85acc893ea3554e18e5d15ed85225e4b6d8a7fc`,
`4e16953c27702a1d330b6148c8e7035b1f6239c2d5b49722301b069451f2163f`,
`ad517de962c59e7baec2079ac97787907c8f7b275478d64eb25273a1e6b16e26`,
and `4ed0fdc773fe5870ba54b51b220a568cce6a7def5665317a55a843fe344737f4`.

Because V97 has no strict survivor, it cannot advance to multiseed, Test3,
real-design, OpenROAD, or Innovus validation. The existing local queue
therefore continues with V101, then retained V96, V103, and V102. V101 began
on local GPU 0 immediately after V97 exited. At the last live remote check,
V92/V98/V99 had `7/14`, `10/14`, and `8/14` complete rows respectively;
V93 waits behind V92 and V100 waits behind V99. Remote GPU 3 is not idle: the
older corrected adaptive-development campaign is using it. No held-out or
golden promotion is authorized by any of these partial campaigns.

## Baseline-first proxy scheduler correction (2026-08-01 11:27 +0800)

V101 completed all seven Test1 method rows before starting Test2. All six
candidate DEFs differ from HPWL and pass placement-geometry provenance, so the
campaign is not a no-op. A direct one-case diagnostic finds at least one
positive `absolute_directional_v3` GPUGR primary delta for every candidate;
under the frozen zero-worst-regression policy those observations cannot be
repaired by later Test2 improvements. This is elimination evidence only, not a
selection or admission decision, and V101 continues because complete Test2
evidence is still required for terminal near-miss analysis.

The attempted formal Test1 partial audit exposed that the V96/V97/V101-V103
runners serialized their generated preset dictionaries with `hpwl` last. This
does not invalidate terminal comparisons, but it prevents the partial snapshot
tool from establishing a same-seed baseline while the second case is active.
`tools/routability_campaign.py` now owns the canonicalization of any supplied
method list that contains `hpwl` to `hpwl,<candidates>`, and
`tools/routability_parallel.py` imports and applies the same helper before
spawning per-case campaigns. Direct and parallel entry points therefore share
one policy. It preserves the complete method set and original candidate order;
method lists without `hpwl` are unchanged. The already-running V101 process
retains its original order, while waiting V96, V103, and V102 will import the
corrected scheduler when they start.

SHA-256 values for the campaign entry point, parallel entry point, and their
focused tests are respectively
`a9fbb5d66e82b1b322b5316f1730d03a4f475caf839a757d6408e29db9cecd45`,
`74bacf524506793fade7731fb4b26d204de73d9a10488b1400aa0d55ed785105`,
`f54519920cd4a5aebdf6f32f454fd396318f1810b68a8a79a08e0487500d0b06`,
and `161ac3afe5f4262564833778dc3a13eb9edafbb90efa50c8a79e242645f67864`.
Campaign, parallel-runner, partial-snapshot, and partial-elimination tests pass
`13/13`; the complete routability suite passes `548/548`. Python compilation,
the method-set/order invariant, and `git diff --check` also pass.

## V92/V98/V99 Test1 inactivity audit (2026-08-01 11:35 +0800)

A live read-only audit of the complete remote Test1 slices confirms that all
six candidates in each of V92, V98, and V99 are byte-identical to their
same-campaign HPWL placement. All 21 DEFs share SHA-256
`c61fd85e34f4ef899a7f8b7ec086df7a467c768d130848ece131b799f0636b8c`.
Consequently every one of the four RUDY and 19 V3 GPUGR primary deltas is
exactly zero for all 18 candidate/Test1 rows. A sampled V98 provenance parse
reports `selected_no_activation`, 491 gradient attempts, zero activations, and
plugin status `attempted_no_change`, consistent with the intended congestion
gate rather than an evaluator discrepancy.

These rows neither qualify nor eliminate a candidate: the methods are designed
to activate on Test2, and the terminal placement-effect audit must prove that
activation and changed geometry there. At this checkpoint V92, V98, and V99
have `9/14`, `11/14`, and `9/14` complete dual-evaluator rows respectively.
No Test3, real-design, OpenROAD, or Innovus evidence was accessed.

## Completed-comparison snapshot and formal V101 elimination (2026-08-01 11:42 +0800)

`tools/routability_snapshot_partial_campaign.py` now has an explicit
`--completed-comparisons-only` mode for older baseline-last campaigns. It
freezes only comparisons that already contain a successful HPWL row and at
least one successful candidate, while retaining every expected case/seed in
the generated `parallel_status.json`; omitted comparisons remain `running`.
The downstream summarizer therefore reports partial coverage and cannot
mistake the snapshot for a terminal campaign. The default common-prefix mode
is unchanged.

The new mode froze V101 Test1 under
`partial_test1_snapshot_v2_20260801T0340Z`. Its independent summary reports
exactly `1/2` validated comparisons, zero excluded rows, zero baseline gaps,
and Test2 as missing/running. The V3 partial-elimination audit classifies all
six active candidates as irreversibly eliminated by an already positive
GPUGR worst-case primary delta; zero are inactive, still possible, or
evidence-indeterminate. The closest Test1 candidate is q95/tail50/full with
two vetoes: vertical ACE `+0.099563%` and aggregate utilization maximum
`+0.734225%`. V101 continues because complete Test2 data remains necessary for
terminal near-miss analysis and future tuning, not because Test2 can reverse
the frozen zero-worst-regression veto.

SHA-256 values for the snapshot manifest, partial screening summary, raw rows,
and V3 elimination audit are respectively
`140c97b4fa3c0a0d73906a12c86b538c91644f9857999a4bca108b23cb5a98f8`,
`e74792a4cc401be336f2267befa8b7ac76a6df384523cbd7b67052214ebc719f`,
`86b5b492c427e99aa0ac652628d69f933a9053e70be4f3c9fbdfeeb685c1f03c`,
and `ee24744c14cb1f6b63f18df904aa93671a42827727291bd69f71518660cec2fa`.
The snapshot tool and focused test hashes are
`351122fdc748020f3605763a6e03c54ce91cb2966d9610e63075d061ba43582a`
and `8e6d083884699e35c35a5d329868ad6e92f9f9da2b1d3f84448557ed088988f6`.
Focused snapshot and elimination tests pass `10/10`; the complete routability
suite passes `549/549`. Compilation and `git diff --check` pass. This partial
audit is not a selection or admission decision and uses no held-out or golden
evidence.

## Placement-effect-aware partial activation gate (2026-08-01 11:49 +0800)

`tools/routability_audit_partial_elimination.py` now accepts the optional
`--placement-effect-audit` evidence already consumed by the terminal selector.
The partial gate distinguishes four activation states without weakening the
numeric proxy rules:

- active placements remain valid, with supplied placement-effect evidence
  required to show an active status and a changed DEF;
- `selected_no_activation` slots remain possible only when every completed
  case/seed is hash-proven byte-identical to its same-slot HPWL DEF, and are
  reported as `still_possible_pending_activation`;
- missing or incomplete placement-effect evidence is structural
  indeterminacy, not an irreversible elimination;
- contradictory or malformed activation evidence remains fail-closed, while
  any positive guarded GPUGR worst-case primary delta still irreversibly
  eliminates the candidate.

This does not relax terminal admission. The terminal selector still requires
at least one real activation and changed placement, so a candidate that never
activates cannot survive a complete campaign.

Real-data applications now cover frozen Test1 summaries from V92, V98, and
V99. Each placement-effect audit passes, all six methods in each campaign have
zero inactive-placement changes, and each corrected partial audit reports `0`
eliminated, `6` still possible, `6` pending activation, and `0` indeterminate.
The copied compact evidence and new audits are under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v92_test1_20260801T0355Z`,
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v98_test1_20260801T0220Z`, and
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v99_test1_20260801T0355Z`.
The three new partial-audit SHA-256 values are respectively
`5e9562ff80cfc711e622a5466937c995a5b2f083ae610cc9e0339b796b4cdbe2`,
`957a1f2876d2260c95aff395dcfe20816b8e1ea2a9f71f0299e2bf312ba36cc5`,
and `7acc9fdfee49c0340a930657b1e50aa255a7c10da2b046c6975affe81d4ade1e`.

Focused partial-elimination tests pass `11/11`; the complete routability suite
passes `555/555`. Python compilation and `git diff --check` pass. The tool and
focused-test hashes are
`5ab51f56f3240a00e122e98ed18c654b6ccf0d1a6e02a1c1ae33ff8c2d471195`
and `2f8aa73bb0803e3940768a0e9732ecf0bb1f8ed24937b217d8b730d0021cd236`.

Live dual-evaluator counts at this checkpoint are local V101 `10/14`, local
V96 `7/14`, remote V92 `10/14`, remote V98 `12/14`, and remote V99 `10/14`.
V103, V102, V93, and V100 remain queued. No campaign is terminal, no strict
survivor exists, and no Test3, real-design, OpenROAD, or Innovus evidence was
accessed.

## Terminal V98 audit and cap-budget follow-up V104 (2026-08-01 12:05 +0800)

V98 reached `14/14` complete dual-evaluator rows. An independent terminal
regeneration under remote directory `summary_independent_20260801T0405Z`
matches the launcher-generated screening summary and placement-effect audit
byte-for-byte. The summary has `2/2` validated comparisons, zero exclusions,
and zero same-seed baseline gaps. The placement audit passes with six active,
changed Test2 placements, six inactive HPWL-identical Test1 placements, and
zero inactive changed placements.

Independent strict selectors using both `absolute_directional_v2` and
`absolute_directional_v3` select `0/6`. Every candidate improves at least one
primary metric in RUDY and GPUGR, but every candidate has a positive guarded
GPUGR worst-case regression. The closest V3 point is
`directional_local_gradient_utilization_refinement_v98_00_04_...quarter_cap8`:
all four RUDY primaries and 18 of 19 V3 GPUGR primaries improve. Its sole veto
is aggregate GPUGR utilization maximum `+0.274506%`. This is not a strict
survivor and does not authorize held-out or golden evaluation.

The independently regenerated compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v98_20260801T0405Z`. SHA-256 values
for its summary, placement audit, V2 selection, V3 selection, and V3 near-miss
analysis are respectively
`ac593b9510cb4653f918b700afbded288b4d898f63d6f1ad3265ebc83de0201e`,
`347959a469ce8449e4186f25607d963358993967ce26e3e079bc0ffff074999b`,
`68d3245692f97fee0302cd4decb3c1223b78fd29b6abe9b8e92a0445cb3f7814`,
`884247c504800035fb5ef7bac9336a82b5b7495dc886e00c1b817dcb69a374ba`,
and `2358b1985562f2e2174f35926ca778048f55af48c79265637ce35524217f15b2`.

V104 is a controlled refinement of this near miss. It keeps V98's utilization
feedback, matching-axis mapping, quarter weight, smoothing, refresh interval,
force interval, decay, and activation gates fixed, and varies only
`ruplace_force_max_applications` over `3,4,5,6,7,8`. The cap-8 point is an
exact configuration control. Its config and runner are
`configs/routability_directional_local_gradient_utilization_budget_refinement_pilot_v104.json`
and `run_ruplace_v104_remote.sh`, with SHA-256 values
`94522e9f34b8f968148c60c0a5c408884cb87c0a79790f4443fca2bdca9f58b8`
and `23844d327fd3062ddd5e796ae5407fbdc7488825e1f997e912f1a5dc441dc9a2`.
Generated-preset validation proves one HPWL baseline plus the six intended
caps. An independent generation using the actual remote V90 base presets
proves that V104's cap-8 control and V98's cap-8 candidate have the same 26
effective keys with zero differences. The runner repeats this comparison
fail-closed before starting the campaign. JSON parsing, shell syntax,
`git diff --check`, and the complete routability suite (`555/555`) pass.

Remote tmux `ruplace-v104-utilization-budget-refinement-3583ba6` is detached
in durable phase `waiting_for_gpu`, queued on GPU 0 behind
`ruplace-v100-per-axis-tail25-3583ba6`. At the launch checkpoint, V101 is
`11/14`, V96 `7/14`, V92 `11/14`, V98 `14/14`, V99 `11/14`, and V100 `0/14`.
No Test3, real-design, OpenROAD, or Innovus evidence was accessed.

## Terminal V101 audit and queue handoff (2026-08-01 12:11 +0800)

V101 reached `14/14`. An independent terminal regeneration under
`summary_independent_20260801T0415Z` is byte-identical to the launcher summary
and placement-effect audit. It has `2/2` validated comparisons, zero
exclusions, zero baseline gaps, and a passing placement audit with all 12
candidate slots active and changed. Independent V2 and V3 selectors both
select `0/6`, confirming the earlier Test1 partial-elimination result.

The closest complete V3 point is q95/tail50/full. It improves 18 GPUGR
primaries and three RUDY primaries, but has three GPUGR worst-case vetoes:
horizontal utilization maximum `+1.80925%`, aggregate utilization maximum
`+5.03654%`, and vertical ACE `+0.0995627%`. This is materially farther from
the gate than V98 cap-8's single `+0.274506%` veto, so V98 remains the stronger
tuning anchor.

The compact independent V101 evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v101_20260801T0415Z`. SHA-256
values for its summary, placement audit, V2 selection, V3 selection, and V3
near-miss analysis are respectively
`95f00c27369470b9ecab232d6f35c530db8901eca1915b2c3909ca6ea8687c15`,
`a56902ac0885a5569dc79afd8f54e8f21a5f9ac279ad65de35fa62058ec810b4`,
`2f4f5fc316575f111077a0ff88c019396d35912c99b0bbe57862cc4e551044c9`,
`705d74bf54fea91624c628f3c53fe083e03e599ffec315288b34da15eb0d34e0`,
and `f04cc43d169803df34e85b1d148e8afee82d8f39a3d28be18bea875dc97d1132`.

V101's tmux ended normally and released local GPU 0. V96 then left its wait
state and resumed Test2 with HPWL first, proving the corrected baseline-first
scheduler is active in the successor queue. V103 and V102 remain behind V96.
V92 and V99 remain active remotely; V93, V100, and V104 remain queued. No
strict survivor exists, and no held-out or golden evidence was accessed.

## Terminal V92 audit and V93 handoff (2026-08-01 12:15 +0800)

V92 reached `14/14`. Its independent terminal summary under
`summary_independent_20260801T0420Z` is byte-identical to the launcher summary
and placement-effect audit. The summary has `2/2` validated comparisons, zero
exclusions, and zero baseline gaps. The placement audit passes with six
active, changed Test2 slots, six inactive HPWL-identical Test1 slots, and zero
inactive changed placements.

Independent V2 and V3 selectors both select `0/6`. The closest V3 point is the
smooth-1 unbounded control, but it improves only nine GPUGR primaries and has
10 GPUGR worst-case vetoes. Its largest are overflow bins `+34` raw, vertical
overflow bins `+17.3264%`, and vertical overflow/RC `+11.803%`. V92 is
therefore not competitive with V98 cap-8 and does not justify another tuning
branch.

The compact independent V92 evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v92_20260801T0420Z`. SHA-256
values for its summary, placement audit, V2 selection, V3 selection, and V3
near-miss analysis are respectively
`b97aac16823c98938f34ba5dd775d25002b0b5dc00ee951a75e194009aac6613`,
`750dd7509de0d73cc66a3973d1c10f9109c59da02642f555e4a26b5cc68b4b8b`,
`cb6956b7a8ec06589a84958fb5201f6282c47ff6a94d9f7fb3c812dcd9123cad`,
`72b815790588a32d1497dccc55a967578555c61c85a155c73d07b59801baf796`,
and `ed60c1a6c7056f321d865f8345eaee1228606d98cc370dd2301686813c41e84e`.

V92's tmux ended normally and V93 entered `running_proxy_pilot` on remote GPU
1. V99 remains active on GPU 0; V100 and V104 remain queued behind it. V96 is
active locally, with V103 and V102 queued behind it. No strict survivor exists
and no held-out or golden evidence was accessed.

## Remote baseline-first scheduler repair (2026-08-01 12:19 +0800)

The first completed V93 Test1 rows exposed deployment drift: two candidates,
not HPWL, completed first. A byte-level local/remote comparison proved the
remote scheduler files differed from the validated local versions only by the
missing `baseline_first_methods()` helper and its two entry-point calls; no
unrelated remote edits were present. The validated local
`tools/routability_campaign.py` and `tools/routability_parallel.py` were
therefore deployed to the shared remote corrected tree.

Remote hashes now match local exactly:

- `routability_campaign.py`:
  `a9fbb5d66e82b1b322b5316f1730d03a4f475caf839a757d6408e29db9cecd45`;
- `routability_parallel.py`:
  `74bacf524506793fade7731fb4b26d204de73d9a10488b1400aa0d55ed785105`.

Remote Python compilation passes, and a direct import check maps
`candidate_a,hpwl,candidate_b` to `hpwl,candidate_a,candidate_b`. Active V99
and the already-started V93 Test1 process retain their frozen legacy order.
The updated campaign entry point will reorder V93 Test2 when that child starts,
and queued V100 and V104 will load baseline-first behavior from their first
comparison. No running process was stopped or restarted for this repair.

## Terminal V99 audit and V100 handoff (2026-08-01 12:21 +0800)

V99 reached `14/14`. Its independent terminal summary under
`summary_independent_20260801T0425Z` is byte-identical to the launcher summary
and placement-effect audit. It has `2/2` validated comparisons, zero
exclusions, zero baseline gaps, and a passing placement audit with six active,
changed Test2 slots, six inactive HPWL-identical Test1 slots, and zero inactive
changed placements.

Independent V2 and V3 selectors both select `0/6`. The closest V3 point is the
balance-1 control. It improves all four RUDY primaries and 16 GPUGR primaries,
but has three GPUGR worst-case vetoes: routed wirelength `+0.0100514%`,
horizontal utilization maximum `+2.47079%`, and aggregate utilization maximum
`+2.47024%`. This is weaker than V98 cap-8 and does not justify another tuning
branch.

The compact independent V99 evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v99_20260801T0425Z`. SHA-256
values for its summary, placement audit, V2 selection, V3 selection, and V3
near-miss analysis are respectively
`7324a701ae8824fd0d6264a6325ec257a334b825b751a18a083b6ce5853df3f0`,
`a9026af575b7df01ac7a8d1d231360c186ad8d22c86c505056d885d428529cfd`,
`ddca8f702a086cbfa042a6edc0709515cecc8e2f49d302cc302e61e5a16b3b6f`,
`a22697104f85d1f86ab1333d7fe89a06fdedbf35ca67246ebe516095d0ca303c`,
and `02a9e185f7f846a2737d4a71d602b2cabaf3ffd789be9d5d99dce159a310a805`.

V99's tmux ended normally and V100 entered `running_proxy_pilot` on remote GPU
0. Its first completed row is HPWL, and the live child command orders HPWL
before all six candidates, directly validating the repaired scheduler in a
real campaign. V104 remains queued behind V100. No strict survivor exists and
no held-out or golden evidence was accessed.

## V93/V96/V100 live-prefix audits (2026-08-01 12:35 +0800)

Fresh process, tmux, status-file, and evaluation-artifact checks confirmed that
V96 was active locally, V93 and V100 were active on `ceca2080x4`, V103 and V102
were queued locally, and V104 was queued remotely behind V100. V93 transitioned
to Test2 with `hpwl` first, so the repaired scheduler is now proven on both a
new campaign and the successor comparison of the legacy-started V93 campaign.

The validated local completed-comparison snapshot and placement-aware partial
elimination tools were deployed to the remote corrected tree after byte-level
diff review. The only remote drift was the missing
`--completed-comparisons-only` snapshot mode and the missing hash-proven gated
no-op handling. Remote hashes now match local at
`351122fdc748020f3605763a6e03c54ce91cb2966d9610e63075d061ba43582a`
for `routability_snapshot_partial_campaign.py` and
`5ab51f56f3240a00e122e98ed18c654b6ccf0d1a6e02a1c1ae33ff8c2d471195`
for `routability_audit_partial_elimination.py`. Focused tests pass `16/16`, and
remote Python compilation passes.

V93's completed Test1 slice has one validated comparison, a passing placement
audit, six inactive HPWL-identical candidates, and zero contradictory changed
placements. Both V2 and V3 partial audits therefore classify all six as
`still_possible_pending_activation`; none is eliminated or indeterminate.
The compact local copy is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v93_test1_20260801T0431Z`.
SHA-256 values for its snapshot manifest, summary, placement audit, V2 audit,
and V3 audit are respectively
`1364e8a3f979320226b208f00c62016968e38adabe569183940098068bebaf15`,
`58b1ab56eb76bbfaad4c26683eefed9d95c1e59f8da23f85c3c4e1a43b3694a2`,
`dfd36bf629293e1070add9332e3d4b4462dd103b982601c03a9147d759239084`,
`ee2945639fb987e88e2e34971c126fe4e48b71366edc248539cd8e177cfcf06b`,
and `1453003ec89deabe981098a5e18d99829b8feed8e658fc07268d2af6ca160faf`.

V100's first five completed Test1 candidates show the same valid gated-no-op
pattern. Both partial profiles report zero eliminations, five pending
activation, and zero indeterminate candidates. The compact local copy is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v100_test1_20260801T0435Z`.
Its corresponding five hashes are
`3540f5a25fec9979fdd7771a79f1ed5f1c1e7bd96337ea2d224cd996fd6aadc5`,
`efd4d62e95c8b65e8963dad0da3ed64934b4742b9899479b2743b26f2f445bcc`,
`76c53eb0df51c55dc026ded952c6f316bd58a06fbcddd3d45ac318b679cc982b`,
`c131449c9a965daa2f7e30debf681805a8c7659c095dbe1a48589d5f344ff01f`,
and `0960cd6fd6bcc08d2d37c2421e42e5c7eea4e30f8880b1c550642283d1c02bc6`.

V96 already had two candidates with complete Test1 and Test2 evidence. A
common-prefix snapshot therefore supports full strict decisions for those two
methods, even though the remaining four V96 settings are still running. The
placement audit passes with two active changed Test2 slots, two inactive
HPWL-identical Test1 slots, and zero contradictions. Both V2 and V3 select
`0/2`. The overflow-control point has many large GPUGR regressions. The milder
q90/tail25 point still has four V3 vetoes: aggregate utilization maximum
`+1.49923%`, vertical overflow sum and vertical RC both `+13.2623%`, and
vertical utilization p99 `+0.634519%`. Compact evidence is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v96_two_candidate_20260801T0431Z`.
Its snapshot, summary, placement-audit, V2-selection, and V3-selection hashes
are respectively
`b1f03a5e266c7c3ea05f3450578a78e122f8cf5cbfa3e0529e72d513a14ed88f`,
`5331d3c4e9aef54191e38e2cbe4e42c71dd530fff260b3c9ccf062f99be375c7`,
`f28d58aa677d5594e8f4fd88b77298806830a8543ab70df616b47c78bf9a442c`,
`7d805af851cd84bdaf0ac05cf8685af18de334264cbed9598ae283773ff0ceb5`,
and `e2d24111551394e53d93ce44f48d5c2feb7b632d1e8b83ce338ca7861cafb95c`.

An implementation-level review of V98 cap-8 found no metric inconsistency.
GPUGR's aggregate utilization map is total demand divided by total capacity
across routing layers, while the H/V maps separately aggregate directional
layer groups; their maxima need not move monotonically together. The cap-8
Test2 placement used exactly eight early force applications and improved all
four RUDY primaries plus 18 of 19 V3 GPUGR primaries, including routed
wirelength, estimated shorts, total overflow, and both directional utilization
maxima. Its sole aggregate utilization maximum veto remains `+0.274506%`.
V104's cap-3 through cap-8 sweep therefore remains the highest-priority next
evidence. No held-out or new golden evidence was accessed.

## V93/V96 candidate-level terminal extensions (2026-08-01 12:39 +0800)

As later Test2 rows completed, new common-prefix snapshots produced full
two-comparison decisions without waiting for unrelated candidates. V96's
q90/tail50/full point is rejected by both strict profiles. Its V3 result
regresses GPUGR routed wirelength `+7.50817%`, estimated shorts `+23.5922%`,
overflow sum `+74.3096%`, aggregate utilization maximum `+2.57556%`, and many
directional metrics. The three-candidate compact snapshot is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v96_three_candidate_20260801T0438Z`.
SHA-256 values for its manifest, summary, placement audit, and V3 selection are
`3f40094a633d24e681a804ee1b71b7f35bc22cd6d0e73588707d31e9baaca291`,
`94b6927a4aa53e05144475fc3b4e4debe01f62bc44091a2b15dde75937109836`,
`a4e6b52ba2f0a8baafb4682a0598752ebfc2f6cfc77b48d262b245822e039693`,
and `71db2cbd187e0d671ba19257539f7d143fe9eefb77040f32763674da93834e9f`.

V93's max/zero-tolerance point is likewise rejected by both profiles. Under
V3 it improves no primary metric and regresses GPUGR routed wirelength
`+10.5498%`, estimated shorts `+45.627%`, aggregate utilization maximum
`+11.4606%`, and every reported directional congestion family. Its compact
snapshot is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v93_one_candidate_20260801T0439Z`.
The corresponding four hashes are
`7d09d6c0124b84afbfebc712b16cc0b5911cc8842a0df1b722f7e4c5cbe5efa9`,
`f10050bc90f57c72e0b18edc6e767c982d23f868ac11cdd903db623201b109c2`,
`13b9f7ae5c41884f4322e619b6a4ae4a53af79ce848e320b4f25db803c88cb82`,
and `7c2bcc4c602c282a1e5b32578d5cedcc70ab8c40cf6910197983f7c2e18694c2`.

These are terminal decisions for the named methods only, not declarations that
V93 or V96 as whole campaigns are terminal. Their remaining settings continue
to run for near-miss characterization. No candidate has passed the strict
proxy gate, and no held-out or golden admission occurred.

V96's next completed cross-case point, q95/tail25/full, is also rejected by
both profiles. It is materially closer than the other V96 settings but still
has three V3 GPUGR vetoes: vertical overflow sum `+7.67991%`, vertical RC
`+7.67991%`, and vertical utilization p99 `+0.256411%`. This remains weaker
than V98 cap-8's sole aggregate-utilization-maximum veto of `+0.274506%`, so it
does not replace V98 as the tuning anchor. Its four-candidate compact snapshot
is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v96_four_candidate_20260801T0442Z`.
SHA-256 values for the manifest, summary, placement audit, and V3 selection are
`68ae414194523b9301d7f3fb54c0ce2f8d6217ce23bac21d7a9117dc7425731f`,
`a9e1d4c6297c639293f60c9e467a770396d6f0da1d4929165eac7b5a45340989`,
`9e7a005fac53a91eadda11f05ce30ed47e304e79b268f68750db7e0be1a6fff0`,
and `9aa8ee68757e596fe6037e5958e1d5cd3f548da09bb2d729c412c35f5e87f391`.

## Remote V3 analysis deployment repair (2026-08-01 12:59 +0800)

An independent V100 common-prefix audit exposed analysis-only deployment
drift before the terminal runner reached it: the shared corrected remote tree
accepted `absolute_directional_v2` but not the V3 profile requested by
`run_ruplace_v100_remote.sh`. Byte-level local/remote diffs proved that the
selector differed only by the missing V3 profile definition, while the
near-miss tool differed only by the missing dynamic V3 CLI choice. Placement,
evaluation, summary, snapshot, and placement-effect tools were already
identical and were not changed.

Focused selector, near-miss, partial-elimination, and placement-effect tests
pass `54/54`. The two validated analysis files were deployed without stopping
or restarting any active campaign. Remote compilation passes, both CLIs now
advertise V3, and remote hashes match local exactly:

- `tools/routability_select_survivors.py`:
  `621d87dfa0d87ab3daff140d2e2bd02a2df501a3c191690dc324d4669103d923`;
- `tools/routability_analyze_near_misses.py`:
  `03a803d99dfb5c911423b211c9e3c51e052b1313dd5b3983ffa86eb8e9c45a64`.

This repair changes no placement or evaluator result. It prevents V93, V100,
and V104 from failing when their post-campaign analysis requests V3.

## V100 first cross-case candidate rejection (2026-08-01 12:59 +0800)

V100 reached `9/14` complete dual-evaluator rows, making its balance-1 control
the first candidate with complete Test1 and Test2 evidence. An independent
two-comparison snapshot has zero exclusions and zero baseline gaps, and its
placement-effect audit passes with an inactive, HPWL-identical Test1 placement
and an active, changed Test2 placement. Both V2 and V3 select `0/1`.

The candidate improves no primary metric in either RUDY or GPUGR. Its V3
Test2 regressions include routed wirelength `+11.3015%`, estimated shorts
`+112.827%`, aggregate utilization maximum `+2.63084%`, horizontal utilization
maximum `+13.0004%`, vertical utilization maximum `+8.57033%`, horizontal
overflow sum `+584.135` raw, and vertical overflow sum and RC `+57.7836%`.
It is terminally rejected and is not a tuning anchor.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v100_one_candidate_20260801T0451Z`.
SHA-256 values for its snapshot manifest, summary, placement audit, V2
selection, V3 selection, and V3 near-miss analysis are respectively
`67531be78bfa14588b1a648447fa66836cb95f30f9908d5071b11e02402f44da`,
`dc911e564c941d724348ed1c1d066080c1098b558f23f47d39a5908a071b7a70`,
`0f0042295ef6bc50bdd26ff2ae859de614f3d4e2d3153a6b2807138ccd8ac82c`,
`91fc841553eb6c58b1a4deea182b749b4df91525924e9d7d5812b80aed163044`,
`ae969baac4d9917c6200e0ddf9c638e28b0eff089579c87fdc64fb75c14f8017`,
and `098d6e2096b86059348b7edfc5897659886c321ad18dedf70eb5bf4063325c76`.
Independent local V3 regeneration is byte-identical to the remote result.
This is a terminal decision for the named method only. V100 continues for the
remaining balance settings, V104 stays queued behind it, and no held-out or
golden evidence was accessed.

## V93/V96 next candidate-level decisions (2026-08-01 13:02 +0800)

V96 reached `13/14`, so its q95/tail50/full point now has complete Test1 and
Test2 evidence. Both V2 and V3 reject it. It improves no primary metric in
either RUDY or GPUGR; V3 regressions include routed wirelength `+3.78126%`,
estimated shorts `+10.9958%`, aggregate utilization maximum `+2.82106%`,
horizontal overflow sum `+164.643` raw, and vertical overflow sum and RC
`+54.5362%`. The five-candidate compact snapshot is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v96_five_candidate_20260801T0500Z`.
Its snapshot, summary, placement-audit, V2-selection, V3-selection, and V3
near-miss hashes are respectively
`194dab626145d7e04181f66a53ed299bbe5c4231c1f7fb5aa4507bbf8cc95f83`,
`cfd4c2606e7feb082d32510daa3f87b32154ecec7dd7d884ee69bd40234dc7b5`,
`fb5732d09e3203f0df233b54664e67eb76a72493165e12f81900bd5867103955`,
`d244d64b531aefb5dd05384cc7bde412b00b52a73d15c4a403ed35215a378aaa`,
`07c5f6967f38228df6a07fee1eaebdb914740b4f3f041aced9a0c1647baf0f45`,
and `a837a7a8ee25934376ef0f255e185c53849f493d836704d1d3bf29c06101e739`.

V93 reached `10/14`, making its max/tolerance-0.0025 point independently
decidable. Both profiles reject it with no primary improvement in either
backend. Its Test1 placement is HPWL-identical and its active Test2 placement
is byte-identical to the already rejected max/zero-tolerance point, so the
tolerance change did not alter the placement trajectory or metrics. Repeated
V3 regressions include routed wirelength `+10.5498%`, estimated shorts
`+45.627%`, aggregate utilization maximum `+11.4606%`, horizontal overflow
sum `+128.672` raw, and vertical overflow sum and RC `+127.645%`.

The two-candidate V93 evidence is under
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v93_two_candidate_20260801T0500Z`.
Its corresponding six hashes are
`f50d15ae21d533a82cf09e38aca1337268dcb4c1101527a0d11b20fa4472ff59`,
`9bb9a1443c399ce124177b2ba7a4dde242f062e0b92d235021f53ae1a9b98691`,
`b2fc49d05173f91acd2afb10c31885e6bba03768f474bbc01f8630fbe632b808`,
`77a1bf101556a6364e832675f42457e5de91613c39ded23fbf635217728806fe`,
`9e0e7620da5b64dd5a97905dfc05f86c0754999037cf5fccdfb5fc0b0a23815e`,
and `7f6792c909d355b923100547706d3d3bb8f91bfb6c4eeabe1481eeaeb1216cda`.
Independent local V3 regeneration is byte-identical to the remote result.
These are terminal decisions only for the newly completed methods. No strict
survivor exists, and no held-out or golden evidence was accessed.

## Terminal V96 audit and V103 handoff (2026-08-01 13:13 +0800)

V96 reached `14/14`. Its independent terminal summary and placement-effect
audit are byte-identical to the launcher artifacts, with `2/2` validated
comparisons, zero exclusions, zero baseline gaps, and a passing audit over 12
candidate placements. Independent V2 and V3 selectors both select `0/6`.

The final q95/tail50/half point improves all four RUDY primaries and 16 V3
GPUGR primaries, but it has three GPUGR vetoes: vertical overflow sum
`+6.48782%`, vertical RC `+6.48782%`, and vertical utilization p99
`+0.377578%`. It is slightly better than q95/tail25/full on vertical overflow
but worse on vertical p99, and remains materially weaker than V98 cap-8's
single aggregate-utilization-maximum veto. V96 therefore does not advance or
replace the tuning anchor.

Compact independent evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v96_20260801T0512Z`. SHA-256
values for its summary, placement audit, V2 selection, V3 selection, and V3
near-miss analysis are respectively
`cc314156a06782a15869bf7470ee794a5452b127905a144d18a56b60f84b94f9`,
`14297b0a9626ba7de62bc696a07b3f84cafd0c4738a76e8b245bd78d385c4185`,
`9852b7f5d61d68a8f290f6992b91e10a51e68a727961d882f45a6cf43a65a18c`,
`30c2b347813a1ad9e87e93ce9f6751347e7bf36a270d9e7669d46d8ea47d0b16`,
and `82d5e927dd85d557698ec8e77c3a263072f7e2176fa85d1643b5c75109f65e80`.
V96's tmux ended normally, V103 entered its proxy pilot on local GPU 0, and
V102 remains queued behind V103.

## Aggregate-utilization gradient blend and V105 queue (2026-08-01 13:13 +0800)

Implementation review confirmed that V98 cap-8's H/V utilization-gradient
plugin did not consume GPUGR's aggregate utilization map, even though its sole
strict veto is aggregate utilization maximum `+0.274506%`. The
`directional_local_gradient` plugin now has an opt-in aggregate-gradient blend.
The bounded parameter
`ruplace_directional_local_gradient_aggregate_blend` defaults to `0.0`; that
branch follows the pre-existing field calculation byte-for-byte. Positive
values blend a shape-checked, equally smoothed aggregate feedback gradient
into the separate H/V field before the existing normalization and axis
balance. Runtime provenance records the selected blend.

Focused helper and end-to-end tests cover zero-blend identity, aggregate-only
motion, missing/mismatched maps, nonfinite and out-of-range controls, and the
plugin signal path. Locally, all `107` plugin tests and `47` preset-generation
tests pass. The complete routability suite passes `557/557`; JSON parsing,
Python compilation, shell syntax, and `git diff --check` pass. The relevant
hashes are:

- plugin: `e92f4f9086257695794fd4b200824f8c943a54f48d4af8d24738bf18b759ba34`;
- parameter schema: `1f803441021674534e420eef73505e9819b900e69e41829af4dca5a97734c853`;
- focused test file: `c5948e03fed5c16c4071abba85a82bfd4544aebd2e31e6b52b9425f2406e5506`;
- V105 spec: `7b05dfbae6b3dc8965c9c39668f12fb25a44bf018462afd2e4dd2b2a99faaf4a`;
- V105 runner: `1d5a8c7ce70383c7b82d65935ce14a677eb9572bf3ff5cc7dbb7cd0e6d67af30`.

V105 is an independent six-point development sweep over blend values `0`,
`1/128`, `1/64`, `1/32`, `1/16`, and `1/8`, with every other V98 cap-8
control fixed. A hardlink-based remote overlay retains only 75 MiB of unique
data. Modified source/install files have independent inodes and matching
hashes, so the frozen V90/V104 install is unchanged. Dependency review found
that the current plugin additionally needs the default-disabled tail-gate API;
the V105 snapshot therefore carries `plugin_base.py` hash
`078511c700bfbd8ec2c261e8206369c33a7e05cdd9d5dc46e66357479415a67d`.
The base-to-current diff contains only that API and its state.

Ten targeted tests pass remotely. Actual remote preset generation produces
one HPWL baseline and six candidates; its zero-blend control matches V98 cap-8
on all 26 effective keys. Preflight preset and manifest hashes are
`a74fa17f11907433d3d86eb295ba20f6fae098d383b4cec99fa3d276eddd14d0`
and `8c79dea18d3db4aa93eaae1cbead7e29acab6e09d135075f713b15a755c6387a`.
Remote tmux `ruplace-v105-aggregate-blend-3583ba6` is in `waiting_for_gpu` on
GPU 0 behind V104. Its runner checks V104's terminal V3 selection and exits
without running if V104 already has a strict survivor. Otherwise it preserves
the Test1/Test2-only, separate RUDY/GPUGR, zero-worst-regression protocol.

## V100 second cross-case candidate rejection (2026-08-01 13:13 +0800)

V100 reached `10/14`, making balance `0.9921875` independently decidable.
Both V2 and V3 reject it. It is materially better than the balance-1 control,
but still has 13 V3 GPUGR vetoes, including routed wirelength `+1.49864%`,
estimated shorts `+3.59737%`, aggregate utilization maximum `+0.0973814%`,
horizontal utilization maximum `+3.66915%`, and vertical overflow sum and RC
`+20.3848%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v100_two_candidate_20260801T0513Z`.
SHA-256 values for its snapshot, summary, placement audit, V2 selection, V3
selection, and V3 near-miss analysis are respectively
`a56e2590948de83b45616cad75e8802f595f68bfc0910712fe0333251e4f1264`,
`78d3f143258bb4178456aabdb4b8979ff753c1d46e8d8f0a92319e60a8995029`,
`d40058177cd6319a98f04468c6c25e0e5764b98934f4c2812fd3cd009b4f1273`,
`14086688332af501697ed0353f9947611e99e53c9ae9258bc5ce99c269e82750`,
`df3e535121777fe1b51f3376f27ec681ba79bf00829ab083b4d1767fb798f441`,
and `4a16df7f55036276274e296a5d1804a0d0ee5e685eae6a43ea3d9d7f3de118c0`.
Independent local V3 regeneration is byte-identical to the remote result.
This is a terminal decision only for the named method; V100 continues. No
strict survivor exists, and no held-out or golden evidence was accessed.

## V93 p99/zero-tolerance rejection (2026-08-01 13:18 +0800)

V93 reached `11/14`, making its p99/zero-tolerance method independently
decidable. Both V2 and V3 reject it, and it improves no RUDY primary. Its V3
GPUGR vetoes include routed wirelength `+11.9471%`, estimated shorts
`+55.3661%`, horizontal overflow sum `+196.589` raw, vertical overflow sum and
RC `+99.5102%`, horizontal utilization maximum `+6.51819%`, and vertical
utilization maximum `+2.69119%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v93_three_candidate_20260801T0517Z`.
SHA-256 values for its snapshot, summary, placement audit, V2 selection, V3
selection, and V3 near-miss analysis are respectively
`a0e0a38f4302ba69c65666601073c408532510bcaefa9abdb95aade59d20b65c`,
`bc3b1f9ba25c72233d3de4a1aed49e795d54906f5604ae67625623896bc03c3a`,
`b96aed89f5ad54e32a44b19fc42a3441c111d4e268c9636782a40949a90c9ef0`,
`76002436a764956bb62df106c146ae5219e9bfcdce20ccfd3d6fda0df61d60ff`,
`df4153d4499dc9b76378d17fdd9599cea2b82bc4e3899c2b20dd149c0e6205f5`,
and `d739abd3797662bf10a2afad92666e49434c83e51511328c832fa0338d44e422`.
Independent local V3 regeneration is byte-identical to the remote result.
This is a terminal decision only for the named method; V93 continues. No
strict survivor exists, and no held-out or golden evidence was accessed.

## V100 balance-0.984375 rejection (2026-08-01 13:23 +0800)

V100 reached `11/14`, making balance `0.984375` independently decidable. It is
the strongest point in V100 so far, but both V2 and V3 reject it. Its six V3
GPUGR vetoes are routed wirelength `+0.139918%`, aggregate utilization maximum
`+0.267252%`, vertical overflow sum `+3.97489%`, vertical overflow bins
`+3.70052%`, vertical RC `+3.97489%`, and vertical utilization p99
`+0.119177%`. This is weaker than V98 cap-8, whose only veto is aggregate
utilization maximum `+0.274506%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v100_three_candidate_20260801T0522Z`.
SHA-256 values for its snapshot, summary, placement audit, V2 selection, V3
selection, and V3 near-miss analysis are respectively
`b5ce937ac4be07ad79306eb7936b61404ce7bdb7532e3b5ed32f21df5566c1f8`,
`dfd54cdbe304a9af75552aa95c19066322aca621f6afe51aa2ffcef446cb137a`,
`91bdbd0704f7850c1e677c47ca41c3deb09dc047d2a60629f7408baa2c522337`,
`a7a127f5b1935e9ec3fd59089e7c6fb9efa714390acc7c69ca39513dceda671a`,
`bff73ace605207b4fdb5b1eca31a434fd3ec31c9158c7734d3c45aee00846556`,
and `a3a587c19c1947514f0e91db2424221747fa08e46d669f476817c5ebaf11d869`.
Independent local V3 regeneration is byte-identical to the remote result.
This is a terminal decision only for the named method; V100 continues. No
strict survivor exists, and no held-out or golden evidence was accessed.

## V103 first cross-case candidate rejection (2026-08-01 13:32 +0800)

V103 reached `9/14`, making the balance-`0.75` control independently
decidable. The common-prefix snapshot contains both Test1 and Test2, the
placement-effect audit passes with one inactive HPWL-identical Test1 slot and
one active changed Test2 slot, and both V2 and V3 select `0/1`. The candidate
improves all four RUDY primaries and 18 of 19 V3 GPUGR primaries. Its sole
strict veto is vertical utilization p99 `+0.152917%`.

This is a strong but non-surviving point. The following V103 settings decrease
the X/Y balance below `0.75`, increasing the relative Y response that targets
this vertical-tail veto, so the already-running fine transition sweep remains
justified. Compact independent evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v103_one_candidate_20260801T0530Z`.
SHA-256 values for its snapshot, summary, placement audit, V2 selection, V3
selection, and V3 near-miss analysis are respectively
`7961f0823f771190625fd972064c9a608d596de40cdc8afea9cd40fef09450b4`,
`0a2cc6dc91dd1224d50292c5bc062a020a7c6390e12b78625102701c9ca2559d`,
`d924d3ec59fbe5955b9be5f6fda666403d99594d955878cb774e41246142b0ad`,
`edd25a4aa4253258ad1cd6826029a76c1372b14423db2b407eaee5a836e641d2`,
`6bfe3b5275f6788e2c3015945f437ac4796d250bf84bff5bc747c1abf574a4b1`,
and `675510b4f868b37949dd0c29dbbed54506315bb214820b53c059b986588147f9`.

## V100 balance-0.96875 rejection (2026-08-01 13:32 +0800)

V100 reached `12/14`, making balance `0.96875` independently decidable. Both
V2 and V3 reject it. It improves all four RUDY primaries but has eight V3
GPUGR vetoes: routed wirelength `+0.0932405%`, aggregate overflow sum
`+2.29614%`, aggregate utilization p99 `+0.114157%`, vertical overflow sum and
vertical RC `+12.3273%`, vertical overflow bins `+15.7487%`, vertical
utilization p99 `+0.101158%`, and vertical ACE `+0.0234852%`. This is worse
than both V100 balance `0.984375` and the single-veto V103/V98 near misses, so
it does not justify another refinement branch.

The remote audit was copied locally to
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v100_four_candidate_20260801T0532Z`.
SHA-256 values for its snapshot, summary, placement audit, V2 selection, V3
selection, and V3 near-miss analysis are respectively
`002860ea6064412a7c1189d25f540f4dc7a4b711120c9e039f6fa297a4f92a72`,
`2f1cb40c1d40ea797bf973d26128a4ab609d2407d339ba17113eaa88e845b7b8`,
`29e9325ce80baf97c061767c8ee19034a4f7d4f65a9c234270e69f3d31a7bdb1`,
`76dfae600aba95023c399903f62b4782bf90fb3290d379461b459d2d12d27c77`,
`52df790ac6df57e224896e1bf6ba54350ad6a957401e253cb0f08009e6721f11`,
and `206604cf24a7d9dd00b3a885f3b18d2dc69c3b3d1941275bef26c80d3b0081af`.
V100 continues for completeness; V103 continues as the stronger CVaR branch.
No strict survivor exists, and no Test3, real-design, OpenROAD, or Innovus
evidence was accessed.

## V93 p99/tolerance-0.0025 rejection (2026-08-01 13:37 +0800)

V93 reached `12/14`, making its p99/tolerance-`0.0025` point independently
decidable. Both strict profiles select `0/4`, and the placement-effect audit
passes. The new point improves no RUDY primary and only one GPUGR primary; its
18 GPUGR vetoes are identical to the p99/zero-tolerance predecessor, including
routed wirelength `+11.9471%`, estimated shorts `+55.3661%`, aggregate
overflow `+70.9933%`, horizontal overflow sum `+196.589` raw, and vertical
overflow sum and RC `+99.5102%`.

The zero- and nonzero-tolerance Test2 DEFs are byte-identical at SHA-256
`08865ac76005848d8b4dd65823d6e8c6a562b3b51df1dd9efecf54930fc37590`.
Thus the `0.0025` tolerance did not change an application decision or the
placement, and this tolerance branch is terminally unproductive. Compact
remote evidence was copied locally to
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v93_four_candidate_20260801T0537Z`.
SHA-256 values for its snapshot, summary, placement audit, V2 selection, V3
selection, and V3 near-miss analysis are respectively
`2e25b0319f10a0d6ee300bfb1e80339582d6f8a8c80d133546922aebe00303f6`,
`2120a000d653bdba72fdf3a2902997ed8561c2b79b10c339b27a7bdcab3e2528`,
`72c3bc1ca7dbc522d6d3750ad33a17c9a9bfb9a5e4dc0acd54dbd95bb6684f7d`,
`448c01a7053e9f1cdba47b4c64f536b5cfc7f94263ef4de16008d2b72ec4bef9`,
`0875e4faf245e0f17b43625dd7ad5aeb7fedbcf138b380f6991218334aab9116`,
and `a28dff4ba0cee56bc17c4b58bfbcf9aef2613825dbc3a0f9552e0e0ca496c993`.
V93 continues only to complete its two remaining max-p99 variants. No strict
survivor exists, and no held-out or golden evidence was accessed.

## V103 balance-0.74609375 rejection (2026-08-01 13:38 +0800)

V103 reached `10/14`, making balance `0.74609375` independently decidable.
The placement-effect audit passes with two active changed Test2 slots, two
inactive HPWL-identical Test1 slots, and no contradictory placement. Both V2
and V3 select `0/2`. The new point improves all four RUDY primaries, but only
14 of 19 V3 GPUGR primaries. Its five strict vetoes are aggregate utilization
maximum `+1.66328%`, vertical overflow sum and vertical RC `+25.4905%`,
vertical overflow bins `+14.1964%`, and vertical utilization p99
`+0.528858%`.

This small balance step is materially worse than the balance-`0.75` control's
single vertical-p99 veto, demonstrating a non-monotonic router response rather
than the expected smooth vertical-tail tradeoff. V103 continues to measure the
remaining transition points, but balance `0.75` remains its strongest point.
Compact independent evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v103_two_candidate_20260801T0540Z`.
SHA-256 values for its snapshot, summary, placement audit, V2 selection, V3
selection, and V3 near-miss analysis are respectively
`7d91028d08d91e3aa0d3b6317886dff73b81bdc0bdc1da4634858f9d243c2ff5`,
`2aefa02791360360fda8fd988e482b037b482726a54677efc7bb0348ab438093`,
`af7c04e43a989e6e82406f99c6de6806f6ecbbc8bd7d0574eb1d665ea16706bb`,
`34d80eb52c2e05867e8858cf605e66670980a23fd0bfa90b4e1d6806ada27dbd`,
`fae3a2ad5deb9aae8b6b205bfe25f9712c6745f04babb57774cfa4be95ccc154`,
and `fb6a8e3ec1add70b2a1cc652ca2f8b4188b853042dcb8782b2a54d14a78753d7`.
No strict survivor exists, and no held-out or golden evidence was accessed.

## V103 balance-0.7421875 rejection (2026-08-01 13:46 +0800)

V103 reached `11/14`, making balance `0.7421875` independently decidable.
The placement-effect audit passes, but both V2 and V3 select `0/3`. The new
point improves only one of four RUDY primaries and 13 of 19 V3 GPUGR
primaries. Its six GPUGR vetoes are routed wirelength `+3.22714%`, aggregate
utilization maximum `+3.39272%`, horizontal utilization p99 `+0.795575%`,
horizontal utilization maximum `+5.41509%`, vertical utilization maximum
`+3.1347%`, and horizontal ACE `+0.760198%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v103_three_candidate_20260801T0546Z`.
This point is worse than both preceding transition points and confirms that
the balance response is not locally monotonic. V103 continues only to close
the remaining points. No strict survivor exists, and no held-out or golden
evidence was accessed.

## V93 independent terminal rejection (2026-08-01 13:58 +0800)

V93 reached `14/14` complete dual-evaluator rows. The remote terminal V2
selector and an independent local V2 regeneration are byte-identical at
SHA-256
`522e94e37e3bb7fb4dc7505bf154bf293598c9c2ed2adcfb7b037c9334bd1770`;
both select `0/6`. An independent V3 regeneration also selects `0/6`, with
SHA-256
`a855f879019ce68c2fb0a641883f58d57031d7ed78bec5596ef80693de206336`.
All six variants improve zero RUDY primaries, and each improves at most one
GPUGR primary while violating at least 18 GPUGR guards. The placement-effect
audit passes with six active changed Test2 slots and six inactive
HPWL-identical Test1 slots.

Compact terminal evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v93_terminal_20260801T0558Z`;
its summary SHA-256 is
`95da612d39674b0b84dc653eaeb6627bd44732338903fcf8a5deb8e457689c87`.
The monotonic tail-guard family is terminally rejected. No held-out or golden
evidence was accessed.

## V100 balance-0.9375 rejection (2026-08-01 14:00 +0800)

V100 reached `13/14`, making balance `0.9375` independently decidable. Both
strict profiles select `0/5`, and the placement-effect audit passes. Under V3
the new point improves no primary metric in either backend and regresses all
19 guarded GPUGR primaries. Representative vetoes are routed wirelength
`+7.56362%`, estimated shorts `+80.3329%`, overflow-net count `+7.69261%`,
aggregate overflow `+32.9683%`, horizontal overflow sum `+331.739%`,
horizontal utilization maximum `+12.2999%`, and vertical utilization maximum
`+7.88919%`.

Compact remote evidence was copied locally to
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v100_five_candidate_20260801T0600Z`.
The summary and V3 selection SHA-256 values are
`3799f3a7ed4b8643dfa50bb047d8b0af141d68746cd5e78a5776dc6cf5f8960a`
and
`09e2dffa44451e30fdb1d71d4dfd48ed7b9ab6209ab4078853252a8bc9da6e52`.
V100 continues only to close its final balance point. No strict survivor
exists, and no held-out or golden evidence was accessed.

## V103 balance-0.73828125 rejection (2026-08-01 14:01 +0800)

V103 reached `12/14`, making balance `0.73828125` independently decidable.
Both strict profiles select `0/4`, and the placement-effect audit passes. The
point improves two of four RUDY primaries and 11 of 19 V3 GPUGR primaries,
including routed wirelength, shorts, overflow-net count, aggregate overflow,
and aggregate utilization maximum. It nevertheless has seven V3 GPUGR vetoes:
aggregate utilization p99 `+0.190235%`, horizontal overflow sum `+23.5446%`,
horizontal overflow bins `+227` raw, horizontal RC `+0.000359261` raw,
horizontal utilization p99 `+0.473583%`, horizontal utilization maximum
`+2.30156%`, and horizontal ACE `+0.298142%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v103_four_candidate_20260801T0600Z`.
The summary and V3 selection SHA-256 values are
`0e4aa6e3db26207aa94b8686459bbde8ecb860bf250ca8569e82a8bed841e769`
and
`e8c6e99991a4dd81447478244560bf60c18471b635b29c16e6505bd4f9023f4a`.
The branch remains non-monotonic and has no strict survivor.

## Atomic aggregate-CVaR plugin and V106 launch (2026-08-01 14:03 +0800)

The missing independently selectable aggregate utilization-tail objective is
implemented as `aggregate_cvar_gradient`. It uses the aggregate GPUGR
utilization and overflow maps, clamps the quantile threshold to routing
capacity, RMS-matches tail excess to overflow before blending, smooths and
differentiates with physical routing-bin dimensions, normalizes the vector
field, and applies it through the existing scheduled relative-force contract.
Its independent parameters are weight, smoothing radius, quantile, and tail
blend. It is registered separately, has an atomic preset, and is included in
the mechanism-lineage table. Plugin source SHA-256 is
`dbab0650841d214913c552d99c8d8994046cfdd74722b5dc7f67f96eec91e35d`.

All `109` plugin tests and all `48` preset-generator tests pass under the
placement Python environment. V106 is a six-point Test1/Test2, seed-1000,
RUDY-plus-GPUGR atomic pilot over tail blend and aggregate quantile; it does
not combine the plugin with V98 or access Test3, real designs, OpenROAD, or
Innovus. Its specification and generated preset SHA-256 values are
`f35a88675a5fcfc1508ee2a86deebd949f61ad1c5f07837f65ff459dc1873465`
and
`5d93fe4050ea78431d4fc39b4bdf8997831fb8d1fde68faeb3521e21d3a310ee`.

The isolated remote overlay passed source/install hash validation, eight
compiled-extension ABI imports, plugin-registry validation, parameter-schema
validation, and deterministic preset generation. Remote tmux
`ruplace-v106-aggregate-cvar-3583ba6` is running on `ceca2080x4` GPU 1. It
preserves separate RUDY/GPUGR metrics and evaluates both V2 and V3 zero-worst-
regression gates before any later stage can open.

## V100 independent terminal rejection (2026-08-01 14:05 +0800)

V100 reached `14/14` complete dual-evaluator rows and its remote terminal V3
selector reports `0/6` strict survivors. An independent local V3 regeneration
is byte-identical to the remote selection at SHA-256
`09e2dffa44451e30fdb1d71d4dfd48ed7b9ab6209ab4078853252a8bc9da6e52`;
an independent V2 regeneration also selects `0/6`. The placement-effect audit
passes with all six Test2 placements changed and all six inactive Test1
placements HPWL-identical.

The final balance `0.90625` point is V100's strongest near miss: 15 of 19
GPUGR primaries and two of four RUDY primaries improve. It is still rejected
by routed wirelength `+0.474822%`, overflow-net count `+1.25998%`, horizontal
utilization maximum `+0.387227%`, and vertical utilization maximum
`+3.20088%`. Compact terminal evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v100_terminal_20260801T0605Z`;
its summary SHA-256 is
`c2325456592b839e4de0e0e763f8cdc9d10dfe5671b1cf5c253087945b32b139`.
No held-out or golden evidence was accessed.

## V103 balance-0.734375 rejection (2026-08-01 14:08 +0800)

V103 reached `13/14`, making balance `0.734375` independently decidable.
Both V2 and V3 select `0/5`, and the placement-effect audit passes. This point
improves no RUDY primary and only six GPUGR primaries; it has 20 GPUGR vetoes,
including routed wirelength `+0.876222%`, estimated shorts `+2.06925%`,
aggregate overflow `+20.3189%`, horizontal overflow `+37.8364%`, vertical
overflow and RC `+27.2334%`, horizontal utilization maximum `+5.19896%`, and
vertical utilization maximum `+1.33624%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v103_five_candidate_20260801T0608Z`.
Its summary and V3 selection SHA-256 values are
`7b49bc385762726399bf6230d82c576c707ee05baa73ad34c8c58a0f6dc63aae`
and
`1d209a55f4a62f60355ae70d27e596bf62dbbd7ed38512ec7c09939e57af85c4`.
V103 continues only to close its final point; balance `0.75` remains the
branch's single-veto best result.

## V107 bounded transition refinement queued (2026-08-01 14:12 +0800)

V100's isolated balance-`0.90625` near miss justifies one bounded atomic
transition sweep before closing the per-axis q99/tail-25 branch. V107 keeps
every V100 control parameter fixed and varies only axis balance over
`0.90625`, `0.91015625`, `0.9140625`, `0.91796875`, `0.921875`, and
`0.92578125`. A generator regression test proves that its control is exactly
V100 balance `0.90625` and that every other variant differs only in axis
balance. All `49` preset-generator tests pass.

The V107 specification, generated presets, and runner SHA-256 values are
`18ad46aefbf672e3ec705f0c7d93f41eac10bbe9aca499235a326273e758c2dd`,
`d1e57f150f0db8cf846a9afd0bb3ca3a67149df3367e97d6ce2fbdb7733d3f4a`,
and
`57272071228996498ef651eadeac5d223ced035d64a7b3c9b8f7ad876348b38b`.
The remote preflight passed five source/install hash checks and eight compiled
extension ABI imports. Tmux `ruplace-v107-tail25-transition-3583ba6` is
waiting on GPU 1 behind V106 and will skip without running if V106's terminal
V3 selector already contains a strict survivor. It remains Test1/Test2-only,
uses separate RUDY and GPUGR evaluation, and cannot open held-out or golden
validation.

## V103 independent terminal rejection (2026-08-01 14:15 +0800)

V103 reached `14/14` complete dual-evaluator rows. Its campaign V3 selector
and independent local V3 regeneration are byte-identical at SHA-256
`7e10eb0d6ee3580f6d5ded6db3bb7d2b0a292416f6f6aa05024ffa458ed7489b`;
both select `0/6`, and an independent V2 regeneration also selects `0/6`.
The placement-effect audit passes with all six Test2 placements changed and
all six inactive Test1 placements HPWL-identical.

The final balance `0.73046875` point improves no RUDY primary and has 17
GPUGR vetoes, including routed wirelength `+17.9824%`, overflow-net count
`+12.7333%`, aggregate overflow `+69.2738%`, horizontal overflow
`+104.154%`, vertical overflow and RC `+150.31%`, aggregate utilization
maximum `+4.91989%`, and vertical utilization p99 `+2.24612%`. Compact
terminal evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-terminal-audits/v103_terminal_20260801T0615Z`;
its summary SHA-256 is
`97f672915eb4da7bd31d54e2dd7bd7ba87e1d9a102efcf69b54b93e0201febb3`.

V103 is terminally rejected. Balance `0.75` remains the branch's best point,
with all four RUDY primaries and 18 of 19 GPUGR primaries improved but a
vertical utilization-p99 veto of `+0.152917%`. V102 has started on local GPU
0. No held-out or golden evidence was accessed.

## V106 activation audit and aggregate-overflow rejection (2026-08-01 14:24 +0800)

V106's completed Test1 half passed an independent placement-effect audit.
All six variants have valid force-budget provenance: the pure q99-tail point
activates and changes its DEF, while the other five variants are correctly
gated inactive and byte-identical to HPWL on this easier case. Compact
diagnostic evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v106_test1_20260801T0618Z`.
This proves that the new plugin is registered and executes; it also shows that
tail blend affects activation severity as well as pressure shape under the
current pressure-based gate.

V106 then reached `9/14`, making its q99/tail-0 aggregate-overflow control
independently decidable across Test1 and Test2. The placement-effect audit
passes with one active changed Test2 slot and one inactive HPWL-identical
Test1 slot. Both V2 and V3 select `0/1`. All four RUDY primaries improve, but
only nine of 19 GPUGR primaries improve. Its ten V3 GPUGR vetoes include
routed wirelength `+0.346273%`, overflow-net count `+0.645839%`, aggregate
overflow bins `+4` raw, vertical overflow and RC `+20.3977%`, vertical
overflow bins `+27.3953%`, vertical utilization p99 `+0.180312%`, horizontal
utilization maximum `+3.13281%`, vertical utilization maximum `+3.34788%`,
and vertical ACE `+0.264141%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v106_one_candidate_20260801T0621Z`.
The summary, placement-effect audit, and V3 selection SHA-256 values are
`115cdf9ba6df92b241b64638dd77879026edb635f79790d23114f1e42e12dc27`,
`0b4f9ce33ce1d0ea7cb8677da5ce27e17ae79a413aa91d70a6e6339d42fe941f`,
and
`1beb05e229f8381c311d81dfb5292419ab587216d0e270556befa04533b7e97b`.
V106 continues through the utilization-tail blends; no held-out or golden
evidence was accessed.

## V104 cap-3 rejection (2026-08-01 14:28 +0800)

V104 reached `9/14`, making the quarter-strength cap-3 application budget
independently decidable. The placement-effect audit passes with one active
changed Test2 slot and one inactive HPWL-identical Test1 slot. Both V2 and V3
select `0/1`. All four RUDY primaries and 12 of 19 GPUGR primaries improve,
but seven V3 GPUGR vetoes remain: aggregate utilization maximum `+0.263048%`,
vertical overflow and RC `+14.676%`, vertical overflow bins `+15.0029%`,
vertical utilization p99 `+0.219087%`, vertical utilization maximum
`+0.292423%`, and vertical ACE `+0.165655%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v104_one_candidate_20260801T0628Z`.
The summary, placement-effect audit, and V3 selection SHA-256 values are
`d1888f07fc2415f3aea874a58f8f1bc296feba93f192b15fcf72447a09aa485b`,
`c73ca0ff40cd4d7cc1cee7b03e1b2810697a94d80ce36d14489f02c80742ae6d`,
and
`0206fe5789e5d712e9fbd238e55189a5fb27495219f10714fa8aabb4e623632a`.
Cap 3 reduces V98 cap 8's aggregate-maximum veto only from `+0.274506%` to
`+0.263048%` while introducing six additional vetoes, so application-budget
response is not monotonic. V104 continues through caps 4--8.

## Atomic aggregate-Lp plugin and V108 queue (2026-08-01 14:33 +0800)

A second independent aggregate-tail objective is implemented as
`aggregate_pnorm_gradient`. It raises utilization excess above routing
capacity to a selectable Lp exponent before smoothing and physical-bin
differentiation. Exponent 1 is ordinary aggregate overflow; larger exponents
increasingly emphasize maximum-utilization bins without a quantile boundary.
Unlike V106, every exponent uses the same aggregate-overflow activation gate,
so the pilot isolates objective shape from activation severity. The plugin is
registered separately, has its own parameters and atomic preset, and is
included in the mechanism-lineage table. Source SHA-256 is
`df9436e427e73b4dc21c122ba1fb2340186f252aec3039d863437e9d19c638fc`.

All `111` plugin tests and all `50` preset-generator tests pass. V108 sweeps
only exponent `1`, `1.25`, `1.5`, `2`, `3`, and `4`; its specification and
generated-preset SHA-256 values are
`d27b03e231fa6e4d10d7ead64000f177f41b2eb630e43386fbcce2b97536a0d7`
and
`41f4365bf5b859f817840dd5edf56ef883fac53b88cf703d999dd867a7d6580c`.
The isolated remote overlay passed three source/install hash checks, plugin
registry and parameter-schema checks, and eight compiled-extension ABI
imports. Tmux `ruplace-v108-aggregate-pnorm-3583ba6` is waiting on GPU 1
behind V107. It checks both V106 and V107 terminal V3 selections and skips if
either has a strict survivor. It is Test1/Test2-only and cannot open held-out
or golden validation.

## V102 balance-1 control rejection (2026-08-01 14:36 +0800)

V102 reached `9/14`, making its balance-1 control independently decidable.
The placement-effect audit passes with one active changed Test2 slot and one
inactive HPWL-identical Test1 slot. Both V2 and V3 select `0/1`. All four RUDY
primaries and 13 of 19 GPUGR primaries improve, but six V3 GPUGR vetoes
remain: aggregate utilization p99 `+0.0916258%`, aggregate utilization maximum
`+1.48082%`, vertical overflow and RC `+17.6021%`, vertical overflow bins
`+2.47024%`, and vertical utilization p99 `+0.515911%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v102_one_candidate_20260801T0634Z`.
The summary and V3 selection SHA-256 values are
`322858b44f451c34a5b456b3221bf12865a30ddf56679edb84c4151a171c309a`
and
`32f2d55e3a0af70719bd2e42d1b1deb666631ffbbcdf330343fe628bd679fb79`.
V102 continues through the positive X-bias points; no held-out or golden
evidence was accessed.

## V106 q99/tail-0.25 rejection (2026-08-01 14:36 +0800)

V106 reached `10/14`, making q99/tail `0.25` independently decidable. The
placement-effect audit passes with both methods active and changed on Test2
and inactive/HPWL-identical on Test1. Both V2 and V3 select `0/2`. The new
point improves no primary metric in either backend and regresses all 19 V3
GPUGR primaries. Representative vetoes are routed wirelength `+16.3027%`,
estimated shorts `+54.6184%`, overflow-net count `+14.6047%`, aggregate
overflow `+83.6904%`, horizontal overflow `+155.551%`, vertical overflow and
RC `+136.901%`, horizontal utilization p99 `+1.19141%`, and vertical
utilization maximum `+3.91561%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v106_two_candidate_20260801T0634Z`.
The summary and V3 selection SHA-256 values are
`3595f00e9321791cc2c86dd2ae4c868642aed29abf272b9b377ea977b485c690`
and
`b0a4bb9408596a4fe89f92ea652d5e6fdd5b0c673adea9c22dde41266f949d05`.
The discontinuity between tail blend 0 and 0.25 reinforces the need for V108's
common-gated Lp sweep. V106 continues for completeness; no held-out or golden
evidence was accessed.

## V106 q99/tail-0.5 rejection (2026-08-01 14:38 +0800)

V106 reached `11/14`, making q99/tail `0.5` independently decidable. Both V2
and V3 select `0/3`, and the placement-effect audit passes with three active
changed Test2 slots and three inactive HPWL-identical Test1 slots. The new
point improves all four RUDY primaries and 11 of 19 GPUGR primaries, but has
eight V3 GPUGR vetoes: aggregate overflow bins `+95` raw, aggregate
utilization maximum `+0.342212%`, vertical overflow and RC `+18.3245%`,
vertical overflow bins `+19.5353%`, vertical utilization p99 `+0.279133%`,
vertical utilization maximum `+2.42316%`, and vertical ACE `+0.120725%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v106_three_candidate_20260801T0637Z`.
The summary and V3 selection SHA-256 values are
`0efe9d47020a9ca86a434ae610a2f984890d280cf2b69886e0b6843275292a9a`
and
`d0680b44b440438e91cf12f5d734ae9aa24c609ee7dc29c072373d567924e271`.
Tail `0.5` recovers from tail `0.25` but remains worse than the strongest prior
atomic near misses. V106 continues; no held-out or golden evidence was
accessed.

## V104 cap-4 rejection (2026-08-01 14:40 +0800)

V104 reached `10/14`, making the quarter-strength cap-4 application budget
independently decidable. Both V2 and V3 select `0/2`, and the placement-effect
audit passes. The new point improves no primary metric in either backend and
regresses all 19 V3 GPUGR primaries. Representative vetoes are routed
wirelength `+4.28382%`, estimated shorts `+89.6404%`, overflow-net count
`+3.90673%`, aggregate overflow `+65.9302%`, horizontal overflow
`+368.597%`, vertical overflow and RC `+61.1498%`, aggregate utilization
maximum `+6.06868%`, horizontal utilization maximum `+8.25776%`, and
vertical utilization maximum `+7.55213%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v104_two_candidate_20260801T0638Z`.
The summary and V3 selection SHA-256 values are
`b3a3af0ba18df3432969032b69f4aad19dd737462765e1fc94a6fcf4d9283182`
and
`bb062ca6bc282e433b09a1a3dc4163ff74b922ced5dadff60af1a4c31af7717e`.
The cap-3 to cap-4 collapse rules out monotonic application-budget response;
V104 continues through caps 5--8.

## V102 balance-1.015625 rejection (2026-08-01 14:42 +0800)

V102 reached `10/14`, making balance `1.015625` independently decidable.
Both V2 and V3 select `0/2`, and the placement-effect audit passes with two
active changed Test2 slots and two inactive HPWL-identical Test1 slots. The
new point improves all four RUDY primaries and 15 of 19 GPUGR primaries. Four
V3 GPUGR vetoes remain: aggregate utilization maximum `+1.65916%`, vertical
overflow and RC `+4.82776%`, and vertical utilization p99 `+0.309235%`.

Compact evidence is retained at
`/mnt/nvme2n1/yifan/ruplace-partial-audits/v102_two_candidate_20260801T0641Z`.
The summary and V3 selection SHA-256 values are
`f591089b0dc7d250b11ac5f60f844d965a7135e3a141d74fd10caf95542e519c`
and
`605b80f33899305f76fc2f2258d7a6f5c551b1835670a6bd55732d7ae5134864`.
The small positive X bias removes two control vetoes but increases aggregate
maximum utilization; V102 continues through larger biases. No held-out or
golden evidence was accessed.
