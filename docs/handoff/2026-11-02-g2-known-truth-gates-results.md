# G2: known-truth gate test, results

Run 2026-11-02 to 2026-11-03 under the frozen plan ([plan](2026-11-02-g2-known-truth-gates-plan.md), [receipt](2026-11-02-g2-known-truth-gates-receipt.json)). The scorer output is [2026-11-02-g2-known-truth-gates-results.json](2026-11-02-g2-known-truth-gates-results.json). It cites receipt SHA-256 `3f86c44bb1ce59389461697a68c95ef8a252e8819ad46b6b28f19180a59becc9`.

## Summary

**G2 does not pass. The current gates (ratio 3.0, 5 peak water pixels) stay.** The G1 candidate (ratio 1.5, 2 pixels) is not adopted, and no `hydroseason-v0.3.0` gate change follows. That is the outcome the plan fixed in advance for a failure.

Three of the five rules fail:
- **Arm S, synthetic records:** the dates the looser gates add are clearly less accurate than the weakest dates the current gates already accept.
- **Both arms:** their `point` dates are wrong far more often than the 5% safety bound allows.
- **Arm I, real flat records with an injected season:** the added dates are as accurate as the current margin.
- **Null records:** the looser gates do not make them look seasonal.

Two further findings matter more than the gate question. Neither was what G2 set out to decide:
- **The current gates fail the precise-date safety rule too.** The plan reported this rule for the current margin as well, so that both settings are held to the same standard. In that margin, 42% (arm S) and 39% (arm I) of `point` trough dates are more than one month from the truth.
  - The 0.2.0 calibration found no false precise boundaries, but its corpus had no noise.
  - Its count is not the same as G2's. 0.2.0 counted a `point` label as false when the true trough was not a single month. G2 counts a `point` date as false when it is more than a month from the truth. Both ask whether `point` can be trusted.
- **On recession-shaped seasons, dated troughs fall early, in the slow recession before the true end of the low.** This happens at every ratio. It is exploratory and is set out below.

## Decision rules

| Rule | Arm S | Arm I | Bound | Outcome |
| --- | --- | --- | --- | --- |
| 1. `point` dates in the admitted band that are not correct | 252 of 433 (58%); Wilson upper 0.628 | 94 of 322 (29%); Wilson upper 0.344 | ≤ 0.05 | **Fails in both** |
| 2. Accuracy, admitted band minus current margin | 0.497 − 0.632 = **−0.135**, 95% interval [−0.179, −0.090] | 0.683 − 0.663 = **+0.020**, 95% interval [−0.038, 0.075] | ≥ −0.05, and lower end ≥ −0.10 | **Fails in S**, passes in I |
| 3. Null records routed to per-year detection, chosen minus current | −0.005, 95% interval [−0.0125, 0.0] | — | upper end ≤ 0.02 | Passes |

Every rule could be evaluated: each band held at least 100 cases (fewest: 322 `point` dates in arm I).

**Held to the same standard: rule 1 for the current margin** (reported only, as pre-registered):

| | Arm S | Arm I |
| --- | --- | --- |
| `point` dates in the current margin (ratio 3–6) that are not correct | 831 of 1,990 (42%); Wilson upper 0.439 | 424 of 1,076 (39%); Wilson upper 0.424 |

The failure does not hinge on how the truth for `pulse` seasons is defined. With `sine` records alone, arm S still fails both rules. The admitted band's accuracy is 0.698, against 0.811 for the margin, and 44% of the band's `point` dates are wrong.

## What the looser gates add

| | Arm S, current | Arm S, chosen | Arm I, current | Arm I, chosen |
| --- | ---: | ---: | ---: | ---: |
| Dated trough boundaries | 10,181 | 11,946 (+17.3%) | 18,500 | 21,064 (+13.9%) |
| Correct (within 1 month) | 7,389 | 8,306 (+917) | 14,062 | 15,772 (+1,710) |
| Not correct | 2,792 | 3,640 (+848) | 4,438 | 5,292 (+854) |
| Accuracy of all dated boundaries | 0.726 | 0.695 | 0.760 | 0.749 |
| Seasonal records routed to per-year detection | 61.2% | 67.5% | 50.3% | 55.1% |

In arm S, nearly one in two added dates is wrong. In arm I, about one in three is.

### Accuracy by ratio band (reported only)

Accuracy, with the number of dated boundaries in brackets.

| Ratio | Arm S, current | Arm S, chosen | Arm I, current | Arm I, chosen |
| --- | --- | --- | --- | --- |
| 1.5–2 | — | 0.491 (167) | — | 0.599 (317) |
| 2–2.5 | — | 0.523 (323) | — | 0.668 (400) |
| 2.5–3 | — | 0.495 (647) | — | 0.644 (399) |
| 3–4 | 0.565 (1,536) | 0.561 (1,876) | 0.649 (650) | 0.676 (996) |
| 4–6 | 0.661 (3,513) | 0.653 (3,747) | 0.667 (2,088) | 0.684 (2,443) |
| 6–10 | 0.779 (3,345) | 0.778 (3,398) | 0.728 (4,317) | 0.724 (4,450) |
| 10 and up | 0.891 (1,787) | 0.891 (1,788) | 0.796 (11,445) | 0.787 (12,059) |

| Peak water pixels | Arm S, current | Arm S, chosen | Arm I, current | Arm I, chosen |
| --- | --- | --- | --- | --- |
| 2–4 | — | 0.470 (287) | — | 0.724 (914) |
| 5–19 | 0.618 (999) | 0.581 (1,363) | 0.849 (2,088) | 0.827 (2,448) |
| 20 and up | 0.738 (9,182) | 0.717 (10,296) | 0.749 (16,412) | 0.739 (17,702) |

In arm S, accuracy rises steadily with the ratio, from about 0.5 below 3 to 0.89 at 10 and up, so the ratio carries real information about accuracy. In arm I the curve is flat between 1.5 and 6, at about 0.60 to 0.68.

### By season shape and water type (reported only)

| | Admitted band (chosen) | Current margin |
| --- | --- | --- |
| Arm S, `sine` | 0.698 (593) | 0.811 (2,513) |
| Arm S, `pulse` | 0.314 (652) | 0.454 (2,536) |
| Arm I, `sine` | 0.881 (916) | 0.818 (1,405) |
| Arm I, `pulse` | 0.414 (672) | 0.500 (1,333) |
| Arm I, broad water | 0.660 (421) | 0.700 (707) |
| Arm I, channel | 0.723 (773) | 0.711 (795) |
| Arm I, coastal | 0.556 (144) | 0.622 (662) |
| Arm I, permanent | 0.672 (250) | 0.598 (574) |

### Null records

Of 400 null records:
- 3 were routed to per-year detection under the current gates, and 1 under the chosen gates.
- They carried 34 dated trough boundaries under the current gates and 13 under the chosen gates.
- No `flat` record was routed under either gate setting; the 3 and the 1 are `random_pulse` records.

## Exploratory findings (not pre-registered)

These come from the same runs, recomputed by the audit script. They were not part of the decision and need their own pre-registered test before they change anything.

**1. On recession-shaped seasons, the trough is dated early.**

In a `pulse` record the water rises sharply after month m, then recedes slowly back to its lowest value at m. The last four months of that recession are within 12% of the amplitude of the minimum. Under the current gates, the dated pulse troughs fall as follows (months from the truth; negative means early):

| | −5 | −4 | −3 | −2 | −1 | 0 | +1 | +2 to +6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Arm S | 161 | 357 | 679 | 907 | 1,201 | 1,515 | 43 | 117 |
| Arm I | 245 | 573 | 906 | 1,281 | 1,825 | 3,825 | 139 | 379 |

Of the pulse dates that miss by more than a month, 95% (arm S) and 89% (arm I) are early. `sine` errors scatter evenly on both sides of the truth. So noise on a long, nearly flat recession pulls the dated minimum back into the recession, and this does not go away at high ratios.

Hydropools found that adding one month to their reach trough clock scores better against gauge first flow. That is consistent with this early bias, but it is not evidence for it. The library does not use gauges.

**2. `point` dates are less reliable than their name suggests, and less reliable than `interval` dates.**

Share of `point` trough dates that miss by more than a month, under the current gates (number of dates in brackets):

| Ratio | Arm S, `sine` | Arm S, `pulse` | Arm I, `sine` | Arm I, `pulse` |
| --- | --- | --- | --- | --- |
| 3–4 | 34.9% (301) | 64.6% (280) | 37.0% (100) | 52.5% (101) |
| 4–6 | 26.5% (714) | 51.2% (695) | 26.8% (433) | 49.3% (442) |
| 6–10 | 7.8% (936) | 43.2% (734) | 16.3% (1,039) | 47.7% (1,073) |
| 10 and up | 0.5% (580) | 29.2% (445) | 13.0% (3,401) | 35.9% (2,815) |

Only smooth seasons at a ratio of 10 or more stay under the 5% bound, and only in arm S.

For `sine` records, `interval` dates are right more often than `point` dates: 0.938 against 0.854 in arm S, and 0.950 against 0.846 in arm I. A likely mechanism, not yet tested: `point` means that only one month lies within one detectability floor of the minimum. The floor is about one noise standard deviation, so a single noisy low month can be labelled `point`. The floor itself does include month-to-month noise (`hydro_year._noise_floor_pp`), so the problem is not that the ratio ignores noise.

**3. Why G1 and G2 disagree.**

G1 found that tightening never improved reproducibility on real water. G2 finds that, in arm S, lower ratios are less accurate. Split-half reproducibility asks whether two halves of the pixels agree. A trough that both halves place early in the same recession agrees with itself. G1 could not see that error; G2 can.

**4. Edge cycles are not the cause.**

Accuracy of the first and last cycle in each record:
- Arm S: 0.715 for edge cycles, 0.727 for interior cycles.
- Arm I: 0.774 for edge cycles, 0.760 for interior cycles.

## Audit

- **Independent recompute.** A separate script recomputed rules 1 to 3, the bands and the shape splits from the raw run files and the corpus. It does not import the frozen scorer. Every count and accuracy matches exactly. Its own bootstrap (4,000 draws, a different seed) gives [−0.178, −0.091] for arm S and [−0.040, 0.079] for arm I.
- **Hashes.** The plan, script and G1 script hashes match the receipt. The results cite the receipt hash. The corpus digest `9f0fbc97…` matches the 2,548 records.
- **Gates read back.** All 2,548 current-gate runs read back (3.0, 5, 0). All 2,548 chosen-gate runs read back (1.5, 2, 0).
- **Errors and fingerprint.** No run raised an error. All 5,096 runs carry the same method policy fingerprint, `4bcfed63…`, under both gate settings. That is because the fingerprint does not cover the timing gates: `method_policy_manifest()` includes `RECURRENCE_FINGERPRINT` but not `TIMING_IDENTIFIABILITY_FINGERPRINT` or the threshold values. Overriding the gates leaves it at `4bcfed63…` (checked). The gates read back are therefore the record of what ran. See proposal 4.
- **Library state.** Git head was `d32dd47`, with uncommitted edits to `hydroseason/_catchment.py` and `hydroseason/_state_input.py`: the U2–U4 input warnings, also present for G1. No library file changed after 14:39 on 2026-11-02, before the freeze at 20:54.
- **Deviations.** There were no deviations from the frozen plan.

## What follows

**Fixed by the plan**
- The current gates stay.
- The G1 candidate is closed, and these results are published.

**Proposed. Each needs the project lead's decision.**
1. **Test whether the timing labels match known truth.** Decide with a pre-registered test whether `point`, `interval` and `broad` mean what the documentation says. The tolerance that defines `point` is the obvious variable.
   - Use fresh seeds. The G2 corpus found the problem, so it cannot also be the test.
   - `baseline_eligible` requires `timing_status == "point"`, so any change reaches the condition baseline too.
   - Any change is a new method policy (`hydroseason-v0.3.0`).
2. **Reword `point` in the docs now, as advice.** This changes no method.
   - `docs/report-columns.md` and `docs/hydrological-state.md` say a `point` status "resolves to an exact month".
   - The evidence supports this instead: one month stood out as lowest by more than the noise floor. That is not a guarantee that the date is within a month of the truth, and on long, flat recessions the date tends to fall early.
3. **Feed finding 1 into the clock-anchor thread (trough or rise).** The G2 corpus already has a known rise in every `pulse` record, at m to m + 1. A known-truth test of a rise-based anchor could reuse it. G2 did not record rise timing, and the frozen `scripts/clock_anchor_stage0.py` is untouched.
4. **Make the method policy fingerprint cover the timing gates.** Today, two outputs made with different gates or `point` spans can carry the same fingerprint.
   - The fix is to add `TIMING_IDENTIFIABILITY_FINGERPRINT`, or the threshold values, to `method_policy_manifest()`.
   - That changes every fingerprint, so it belongs with the next policy version, not a patch.

## Limits

- **Modelled noise and seasons.** Arm S noise is modelled. Arm I seasons are modelled.
- **The `pulse` shape is one choice.** Its long, flat recession is what makes its trough hard to date. Real recessions vary.
- **A fixed trough month.** Each record keeps one trough month every year.
- **Not accuracy for real places.** The results describe accuracy on records like these, not at any real place.

## Provenance

- **Code:** `scripts/known_truth_gates.py` (stages `check`, `pilot`, `pilot-i`, `freeze`, `run`, `evaluate`), run with `./.venv/Scripts/python.exe`. It reuses `scripts/gate_calibration.py` unchanged.
- **Runs:** `D:\RLH\5.6\data_local\intermediate\hydroseason_known_truth_gates\`: `corpus.jsonl.gz`, `main_current.jsonl`, `main_chosen.jsonl` and `g2.log`.
  - Current gates: 2026-11-02 20:54 to 22:33.
  - Chosen gates: 22:33 to 00:31 the next day.
  - Evaluation: 2026-11-03 00:31.
- **Guards:** `tests/test_known_truth_gates.py`.
