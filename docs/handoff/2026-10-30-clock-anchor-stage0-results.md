# Clock anchor stage 0: frozen rise rule versus end-dry as run

Date: 2026-10-30. Branch `clock-anchor-stage0`. Plan: `docs/superpowers/plans/2026-10-30-clock-anchor-stage0.md` (local working file, not tracked; the version used is in commit `4ab73da`). Question: does a frozen rise rule agree across Fitzroy tiles better than the end-dry hydropools uses today?

## Freeze

- Script `scripts/clock_anchor_stage0.py`, SHA-256 `e935821cab8632e0335c03e14907a00b9cc10d0e3ff9e0f5d6573346ea3df729`, committed at `da81ded7caeb17a5f17099811733e94713c47d3d` before any real file was read by it.
- `RULE["version"] = "stage0_rise_v1"`; `MARGIN`: within ±1 ≥ 0.90, gain over end-dry ≥ 0.05, big-tile coverage ≥ 0.90; only the `primary` variant decides. At least 500 scored tile-years for each of rise and end-dry, and finite pooled scores for both, are data-sufficiency conditions for a conclusive decision.
- The rule abstains when the first post-band month is unobserved, as required by the independent verdict. Coverage is point plus interval outcomes over all eligible big tile-years, including `no_window` in the denominator.
- Disclosure: before this rule was written, exploratory rise proxies were computed on the same series (independent verdict §6.1: first departure > 1 pp 0.82, doubling 0.88, half-amplitude 0.93 which coincides with the peak month). This test is pre-specified, not blind. The rule differs from those proxies (band-median level, two-observation confirmation, pulse rejection, interval statuses) and was fixed with its margin before this run.

## Reading rules (written before the run)

- **PASS**: the rise premise survives on this data; stage B (gauge referee) becomes worth its cost if the lead chooses target T2.
- **FAIL with rise within ±1 below end-dry + 0.05**: the proposal's synchrony motivation is falsified on its own data. The thread reduces to the floor on four tiles, departure-size status semantics, handling of `hy_boundary` and `unresolved` cases, and the censoring policy. No HydroSeason contract change is motivated by synchrony.
- **FAIL on coverage alone** (rise synchronous but covers < 0.90): report where the abstentions sit (cloud months, `no_rise` years, four epsilon tiles); a rise anchor would trade coverage for agreement, which is the lead's call under target T2.
- **INCONCLUSIVE**: diagnose the data-sufficiency or data problem; if the loader is at fault, fix the loader, do not touch the rule.
- Sensitivity variants are reported, never used to decide. If any variant passes while the primary fails, say so and say that it would be post hoc to adopt it.

## Results

Decision: **FAIL**. Receipt: [2026-10-30-clock-anchor-stage0-receipt.json](2026-10-30-clock-anchor-stage0-receipt.json), moved unchanged from `dev/reports/` on 2026-10-31 (run `git_head` `bf2ae59cc24ec2414b26cd3977d8ab1f18c3a845`, 82 input files hashed, manifest `1f1500ee7d7bb97d01cb690e3ec6f21067cfe4ca7c8213bf7ad7407ae9f7de00`). The frozen script commit is recorded above.

| Method | within ±1 (pooled) | within ±1 (mean of years) | ≥ 3 off | scored tile-years | coverage, big tiles |
| --- | ---: | ---: | ---: | ---: | ---: |
| End-dry as run (chain, no re-wet guard) | 0.815 | 0.815 | 0.048 | 1,147 | n/a |
| Rise, primary | 0.901 | 0.895 | 0.049 | 635 | 0.539 |
| Rise, floor_2pp | 0.890 | 0.861 | 0.051 | 508 | 0.431 |
| Rise, floor_only | 0.877 | 0.869 | 0.051 | 822 | 0.698 |
| Rise, exported_extent | 0.878 | 0.844 | 0.056 | 592 | 0.505 |
| Rise, confirm_1 | 0.894 | 0.883 | 0.051 | 613 | 0.523 |

Primary status counts (all tiles, 1988–2025): point 692, interval 21, unconfirmed 562, no_rise 187, no_observed_months 0, missing_first_post_band_month 59, no_band_level 0, no_window 37. Median interval width 0 months; median months from boundary to rise month 2.

Margin check (primary): within ±1 0.901 against 0.90 (pass); gain over end-dry 0.086 against 0.05 (pass); coverage 0.539 against 0.90 (fail). Separately, the additional data-sufficiency condition of at least 500 scored tile-years is met by rise (635) and end-dry (1,147), and both pooled scores are finite; this condition was added by the plan and is not a verdict-specified margin.

Sensitivity checks apply the same three margins and sufficiency conditions; none passes all margins. `floor_2pp`, `floor_only`, `exported_extent`, and `confirm_1` each fail within ±1 and coverage, but pass gain (respectively 0.075, 0.062, 0.063, 0.079 against 0.05); all have finite pooled scores and at least 500 scored rise tile-years, as does the common end-dry comparator.

Preflight resolved two rule and coverage conflicts before the freeze: the first unobserved post-band month causes abstention, and coverage includes `no_window` in the eligible big-tile denominator. The receipt uses the actual run HEAD and reports every status, including the added missing-month status.

## Interpretation

**FAIL on coverage alone** (rise synchronous but covers < 0.90): report where the abstentions sit (cloud months, `no_rise` years, four epsilon tiles); a rise anchor would trade coverage for agreement, which is the lead's call under target T2.

The largest abstention category is `unconfirmed` (562), followed by `no_rise` (187) and `missing_first_post_band_month` (59). There are no `no_band_level` or `no_observed_months` rows; `unconfirmed` is most frequent on tile09 (25), then tiles 31, 42, 48 and 49 (23 each), tile56 (22), tile02 (21), and tile05 (20). The four epsilon tiles 05, 13, 18 and 46 account for 69 `no_rise` and 57 `unconfirmed` rows; missing first post-band observations account for 16 more rows on those tiles.

## Limits

- Inputs are the unrepaired hydropools exports: the valid-denominator correction is exact for percentages but restores no pixel counts, so the detectability floor is still machine epsilon on tiles 05, 13, 18 and 46; those tiles fall under `floor_pp_min = 1.0` in every variant except `floor_only`.
- The band level is the median of the exported trough band, which the proposal itself calls the trough estimator. A rise rule that does not depend on the trough band at all was not tested.
- Agreement with a pixel-weighted median of other tiles is a synchrony measurement, not a timing accuracy measurement. Stage B is the only place accuracy against an independent referee is assessed.
- Rows for 2025 use the 2026 cycle row as the following cycle; HydroSeason inputs end 2026-06, so those windows can be truncated and are more likely `unconfirmed`.
- The end-dry comparator omits the re-wet guard, which moved 8 of 1,544 windows.

## What this does not decide

The target (T1/T2/T3), the censoring policy, the donor policy and whether hydropools honours HydroSeason's gates remain the lead's decisions in [2026-10-30-clock-anchor-target-decision.md](2026-10-30-clock-anchor-target-decision.md). Stage A (input repair attribution) is motivated independently of this result and is the next step whatever the decision here.
