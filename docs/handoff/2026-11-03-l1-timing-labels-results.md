# L1: trough timing labels against known truth, results

Run 2026-11-03 under the frozen plan ([plan](2026-11-03-l1-timing-labels-plan.md), [receipt](2026-11-03-l1-timing-labels-receipt.json)). The scorer output is [2026-11-03-l1-timing-labels-results.json](2026-11-03-l1-timing-labels-results.json). It cites receipt SHA-256 `1a1e23f075e4e61ef33e58da0f94d41228eaa619157adf32aa124d27aa4c816f`.

## Summary

**The G2 finding is confirmed on fresh records. No tolerance setting passes, so there is no candidate: changing the pass-1 trough tolerance alone does not make `point` trustworthy.** That is the answer the plan fixed in advance for this outcome. Nothing changes in the library.

- **Confirmation (rule C).** Under today's rule, 784 of 2,779 `point` trough dates (28.2%) in arm S and 1,192 of 4,837 (24.6%) in arm I are more than a month from the true month. The Wilson lower bounds, 0.266 and 0.234, are far above 0.05.
- **All three wider tolerances fail rule 1 in both arms.** Even the widest (k3, 2.77 floors) leaves 24.5% (arm S) and 22.8% (arm I) of `point` dates wrong.
- **They pass rules 2 and 3.** Dates are no worse and records are not lost. The tolerance changes which cycles are called `point`, not the dates.
- **Cost of widening.** k3 removes 43% (arm S) and 34% (arm I) of `point` dates and 44% and 32% of baseline-eligible cycles, for a 3.7 and 1.8 percentage-point drop in the `point` miss share.
- **Null records.** No null record, under any setting, gave a dated trough or was routed to per-year detection.

Exploratory checks on the same runs (not pre-registered) point to why. Details are under "Exploratory findings":
- most `point` dates that miss are months that really were lower than the true month in the data;
- the trough label compares the boundary only with the months before it, back to the wet-season peak, and never with the months after it;
- the noise floor is not too small.

## Decision rules

**C. Confirmation (current setting)**

| | Arm S | Arm I | Bound | Outcome |
| --- | --- | --- | --- | --- |
| `point` trough dates that are not correct | 784 of 2,779 (28.2%); Wilson [0.266, 0.299] | 1,192 of 4,837 (24.6%); Wilson [0.234, 0.259] | lower bound > 0.05 | **Holds in both: confirmed** |

**Rules 1 to 3, by setting.** Rule 1 is the share of `point` dates that are not correct. Rule 2 is the accuracy of all trough boundaries in seasonal cycles, setting minus current, with its 95% bootstrap interval. Rule 3 is the share of seasonal records routed to per-year detection, setting minus current.

| Setting | Factor | Rule 1, arm S | Rule 1, arm I | Rule 2, arm S | Rule 2, arm I | Rule 3, arm S | Rule 3, arm I | Passes |
| --- | ---: | --- | --- | --- | --- | ---: | ---: | --- |
| k1 | 1.414 | 644 of 2,305 (27.9%); Wilson upper 0.298 | 1,041 of 4,227 (24.6%); Wilson upper 0.259 | +0.0002 [0.0000, +0.0006] | 0.0000 [0.0000, 0.0000] | −0.0017 | 0.0000 | No (rule 1) |
| k2 | 2.326 | 452 of 1,737 (26.0%); Wilson upper 0.281 | 804 of 3,411 (23.6%); Wilson upper 0.250 | +0.0029 [+0.0002, +0.0072] | −0.0014 [−0.0036, 0.0000] | −0.0067 | −0.0035 | No (rule 1) |
| k3 | 2.772 | 387 of 1,578 (24.5%); Wilson upper 0.267 | 726 of 3,178 (22.8%); Wilson upper 0.243 | +0.0033 [+0.0004, +0.0078] | −0.0014 [−0.0036, 0.0000] | −0.0083 | −0.0035 | No (rule 1) |

Bounds: rule 1 Wilson upper ≤ 0.05; rule 2 ≥ −0.02 with lower end ≥ −0.05; rule 3 ≥ −0.02. Every rule could be evaluated; the fewest cases were 1,578 `point` dates (k3, arm S).

## What the tolerance changes

| | current | k1 | k2 | k3 |
| --- | ---: | ---: | ---: | ---: |
| Arm S `point` trough dates | 2,779 | 2,305 | 1,737 | 1,578 |
| Arm S share not correct | 28.2% | 27.9% | 26.0% | 24.5% |
| Arm S share at exactly the true month | 42.6% | 43.1% | 45.0% | 46.7% |
| Arm S baseline-eligible cycles (accuracy) | 545 (0.763) | 463 (0.765) | 359 (0.777) | 303 (0.789) |
| Arm S accuracy of all trough boundaries | 0.711 | 0.711 | 0.714 | 0.715 |
| Arm I `point` trough dates | 4,837 | 4,227 | 3,411 | 3,178 |
| Arm I share not correct | 24.6% | 24.6% | 23.6% | 22.8% |
| Arm I share at exactly the true month | 50.5% | 50.7% | 52.8% | 54.1% |
| Arm I baseline-eligible cycles (accuracy) | 811 (0.797) | 736 (0.796) | 605 (0.803) | 555 (0.809) |
| Arm I accuracy of all trough boundaries | 0.766 | 0.766 | 0.765 | 0.765 |

Widening the tolerance moves cycles out of `point` into `interval`, `broad` and `unresolved`. Under k3, the `point` dates removed (net of current minus k3) were wrong more often than the ones that stay: 33.1% against 24.5% in arm S, and 28.1% against 22.8% in arm I. The difference is not large enough to bring the rest near 5%.

## Reported, not used to decide (current setting)

**Accuracy by label.** Share of trough boundaries within a month of the truth (number of boundaries in brackets).

| Label | Arm S, `sine` | Arm S, `pulse` | Arm I, `sine` | Arm I, `pulse` |
| --- | --- | --- | --- | --- |
| `point` | 0.837 (1,493) | 0.580 (1,286) | 0.875 (2,580) | 0.615 (2,257) |
| `interval` | 0.931 (1,239) | 0.567 (920) | 0.950 (2,009) | 0.674 (1,431) |
| `broad` | 0.901 (436) | 0.579 (765) | 0.880 (317) | 0.695 (996) |
| `unresolved` | 0.728 (415) | 0.507 (531) | 0.890 (616) | 0.649 (738) |
| All boundaries | 0.859 (3,720) | 0.561 (3,660) | 0.893 (5,737) | 0.637 (5,658) |

On smooth seasons, `point` dates are right less often than `interval` dates. On recession-shaped seasons, the labels hardly separate good dates from bad ones.

**`point` dates that miss by more than a month, by ratio band** (number of `point` dates in brackets):

| Ratio | Arm S, `sine` | Arm S, `pulse` | Arm I, `sine` | Arm I, `pulse` |
| --- | --- | --- | --- | --- |
| 3–4 | 38.9% (185) | 63.2% (125) | 31.2% (64) | 45.3% (64) |
| 4–6 | 25.5% (482) | 54.4% (351) | 20.9% (254) | 44.2% (231) |
| 6–10 | 8.3% (527) | 41.3% (433) | 14.0% (609) | 42.5% (548) |
| 10 and up | 1.7% (299) | 24.1% (377) | 10.0% (1,653) | 35.7% (1,414) |

This replicates G2's finding 2. Across ratios 3–6, 41% (arm S) and 33% (arm I) of `point` dates miss.

**Other reported items**
- **Intervals.** An `interval` or `broad` trough interval, widened by a month on each side, contains the true month for 94.7% (arm S) and 96.3% (arm I) of `sine` cycles, but only 56.5% and 67.8% of `pulse` cycles.
- **Baseline-eligible cycles.** Their trough boundary is within a month of the truth for 76.3% (arm S) and 79.7% (arm I). The plan's rule was the library's: complete, boundary `confirmed`, peak not `anomalous`, aggregate timing `point`.
- **Recession-shaped seasons are dated early.** `pulse` trough boundaries, months from the truth (negative is early):

  | | −5 | −4 | −3 | −2 | −1 | 0 | +1 | +2 to +6 |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | Arm S | 122 | 249 | 485 | 651 | 867 | 1,157 | 31 | 98 |
  | Arm I | 232 | 295 | 529 | 744 | 1,263 | 2,251 | 90 | 254 |

  Of the `pulse` `point` dates that miss, 92.6% (arm S) and 84.6% (arm I) are early. The interval end shows the same pattern. This replicates G2's finding 1.
- **Label source.** `point` labels set by trough refinement are right more often than pass-1 labels: 0.780 against 0.659 in arm S, and 0.834 against 0.692 in arm I.

## Exploratory findings (not pre-registered)

These come from the same runs and the corpus, recomputed by scripts that do not import the frozen scorer. They did not decide anything and need their own pre-registered test before they change anything.

**1. Wider tolerance mostly leaves refinement labels, which it does not touch.**

Under k3, 1,327 of 1,578 `point` dates in arm S and 2,040 of 3,178 in arm I come from refinement. The tolerance only acts on pass 1. Refinement `point` dates on `pulse` seasons miss 31% (arm S) and 24% (arm I) of the time. The few pass-1 `point` dates left under k3 still miss often: 34% (`sine`) and 59% (`pulse`) in arm S.

**2. The trough label is one-sided.**

A cycle runs from the month after the previous trough boundary to its own trough boundary (`_dynamic_year._assemble_dynamic_cycle`). The trough label searches from the last equivalent peak to the end of that window (`assess_window_timing`, `trough_search="post_peak"`). So the boundary is always the last month the label sees. The label asks whether the boundary is lower than every month since the peak, not whether it is lower than the months after it. Refinement's candidates are also clipped to months at or before the boundary.

The boundary step itself does look both ways: it reports an "equivalent low run" of adjacent months on either side of the minimum (`low_run_start_month` / `low_run_end_month`).

In the data, a `point` trough that misses usually had a month just after it that was as low, within the record's floor:

| Share with a month within one floor in the next 3 months | Arm S, `sine` | Arm S, `pulse` | Arm I, `sine` | Arm I, `pulse` |
| --- | ---: | ---: | ---: | ---: |
| `point` dates that miss | 74% | 75% | 60% | 56% |
| `point` dates that are correct | 51% | 22% | 48% | 20% |

A crude two-sided check, which drops `point` whenever such a month exists, would cut the miss share from 28.2% to 14.1% in arm S and from 24.6% to 18.4% in arm I. That is better, but still far from 5%. The floor here is approximated as the record's robust noise estimate or the trough month's resolution, whichever is larger.

**3. The noise floor is not too small.**

The timing floor's noise term is `_boundary.robust_scale`: the MAD of month-to-month differences after removing month-of-year medians. In arm S, where the generator's noise is known, it reads a median of 1.17 times the generator's σ. Only 11.5% of records read below 0.8 σ. So the label is not overconfident because the floor underestimates noise.

**4. Most misses are the lowest month in the data.**

For `point` dates that miss, the dated month's observed extent is below the true month's in 83% (`sine`) and 87% (`pulse`) of arm S cases, and in 72% and 79% of arm I cases. Missing valid pixels do not explain this: in arm S the median valid coverage of the dated month is 100% for misses as well as hits.

So on seasons with a flat bottom, noise moves the observed minimum by two months or more. No rule that only reads the observed values can then tell the dated month from the true one. A two-sided label would make `point` rarer and more honest, but a 5% bound on single-month errors looks out of reach on such seasons.

**5. In arm I, a quarter of the missed `point` dates were not the lowest month looking forward.**

Of the missed `point` dates in arm I, 32% (`sine`) and 24% (`pulse`) had a strictly lower month among the next three months. In arm S the figures are 6% and 8%. Real gaps and partly observed months in arm I may stop the boundary step from choosing those months. This was not investigated further.

## Audit

- **Independent recompute.** A separate script recomputed rule C and rules 1 to 3 for every setting from the raw run files and the corpus. It does not import the frozen scorer. Every count, share, Wilson bound and difference matches exactly. Its own bootstrap (2,000 draws, a different seed) gives [0.0004, 0.0074] for k3 in arm S and [−0.0036, 0.0000] in arm I.
- **Hashes.** The plan, L1 script, G2 script and G1 script hashes match the receipt. The results cite the receipt hash. The corpus digest `9ed2879d…` matches the 1,374 records.
- **Fresh seeds.** None of the 1,374 seeds appears in the G2 corpus.
- **Settings read back.** For each setting, all 1,374 runs read back the planned factor and the expected wrapper self-test (trough probe counts 2, 3, 4 and 5; peak probe 1).
- **Errors and fingerprint.** No run raised an error. All runs carry one method policy fingerprint, as expected: the fingerprint does not cover the timing settings (see the G2 audit).
- **Library state.** Git head was `d32dd47`, with the same uncommitted U2–U4 input-warning edits as in G1 and G2. No library file changed after 14:39 on 2026-11-02, before the freeze at 06:42 on 2026-11-03.
- **Deviations.** There were no deviations from the frozen plan.

## What follows

**Fixed by the plan**
- No setting passes, so there is no candidate tolerance. The library is unchanged.

**Done with these results (documentation only)**
- The docs now say that the trough label compares the boundary only with the months back to the wet-season peak, and the guide cites L1 alongside G2.

**Proposed. Each needs the project lead's decision.**
1. **Decide what `point` is for.** Baseline eligibility requires an aggregate `point` status, so that the boundary is "a defensible exact date". In these tests, baseline-eligible trough boundaries are within a month of the truth only 76% (arm S) and 80% (arm I) of the time. Before any label change, measure whether that error matters for what the baseline uses, on known-truth records. If it does not, the docs are enough. If it does, the baseline rule belongs in `hydroseason-v0.3.0`.
2. **Test a two-sided trough label (L2).** Compare the boundary with the months after it as well, for example through the boundary step's own equivalent low run. This corrects a one-sided comparison rather than adding an estimator.
   - Fresh seeds and a frozen plan, as for L1.
   - The pass bound must be decided before the run. Finding 4 suggests 5% is out of reach on flat-bottomed seasons, so "no worse than `interval`" may be the useful bound.
3. **Bring the recession result to the clock-anchor thread.** On `pulse` seasons the minimum sits at the end of a long, flat low, and its month is poorly identified. The rise that follows is sharp. The library's rise date is the boundary plus one month, so it inherits the early bias. A separate rise estimate would be a new estimator, which needs the lead's choice of target first.
4. **Check finding 5 (arm I).** Find why the boundary step passed over a lower month just after it. This is a diagnostic, not a method change.
5. **Fingerprint.** Unchanged: it is still planned for the next method policy (G2 proposal 4).

## Limits

- **Modelled noise and seasons.** Arm S noise is modelled, and arm I seasons are modelled. Arm I keeps real noise.
- **The `pulse` shape is one choice.** Its long, flat low is what makes its trough hard to date. Real recessions vary.
- **A fixed trough month.** Each record keeps one trough month every year.
- **Only the pass-1 trough tolerance was varied.** Three standard values were tested, not a fitted optimum.
- **The exploratory checks are rough.** The three-month look-ahead and the floor approximation stand in for a real two-sided label.
- **Not accuracy for real places.** The results describe accuracy on records like these, not at any real place.

## Provenance

- **Code:** `scripts/known_truth_labels.py` (stages `check`, `pilot`, `freeze`, `run`, `evaluate`), run with `./.venv/Scripts/python.exe`. It reuses the G2 generators in `scripts/known_truth_gates.py` unchanged.
- **Runs:** `D:\RLH\5.6\data_local\intermediate\hydroseason_known_truth_labels\`: `corpus.jsonl.gz`, `main_current.jsonl`, `main_k1.jsonl`, `main_k2.jsonl`, `main_k3.jsonl` and `l1.log`.
  - Freeze: 2026-11-03 06:42.
  - Current: 06:43 to 07:29. k1: 07:29 to 08:15. k2: 08:15 to 09:08. k3: 09:08 to 10:10.
  - Evaluation: 10:10.
- **Guards:** `tests/test_known_truth_labels.py`.
