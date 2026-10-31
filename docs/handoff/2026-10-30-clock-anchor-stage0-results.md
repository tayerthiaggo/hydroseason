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


## Post-hoc audit (2026-10-31)

Written after the decision. Nothing here changes it: the decision stays **FAIL** on coverage. The numbers come from [2026-10-30-clock-anchor-stage0-diagnostics.json](2026-10-30-clock-anchor-stage0-diagnostics.json), written by `scripts/clock_anchor_stage0_diagnostics.py` from the run's own row table and receipt and from the 82 input files, whose hashes it re-checked against the receipt. Earlier figures quoted in conversation used looser definitions; where they differ, this section supersedes them.

### Corrections to the interpretation

1. **The `unconfirmed` abstentions come from the rule, not from cloud.** 555 of 562 have their first exceedance in the window's last month, which is the next cycle's peak month. Confirmation needs a later observation inside the window, so it cannot happen there. Only 0.151 of `unconfirmed` rows have any unobserved month between band end and peak. 357 are fully observed and stay below the threshold until the peak month, and 71 more have no month between band end and peak. On big tiles, the month before the exceedance sits a median 0.14 pp above the band level, and the exceedance month a median 5.36 pp above it; 0.535 of them jump by 5 pp or more. At monthly cadence the rise and the peak usually fall in the same month for these rows. They are 404 of 1,178 big tile-years.
2. **Synchrony clears its margin by one tile-year.** 572 of 635 agree (0.901); one fewer gives 0.899. A year-block bootstrap (4,000 draws, seed 0) gives a 95% interval of 0.863–0.933, with 0.470 of draws below 0.90. The mean-of-years score, 0.895, is already below the margin. "Rise synchronous" in the interpretation overstates this: the data do not separate the rise rule from a 0.90 agreement rate.
3. **The gain compared different rows.** End-dry was scored on 1,147 tile-years and rise on 635. On the same 635 rows end-dry scores 0.836, a gain of 0.065 (bootstrap 95% interval 0.011–0.120). It still clears 0.05.
4. **End-dry coverage was not reported.** On big tiles it is 0.974, against 0.539 for the rise rule.
5. **The four epsilon tiles do not touch the failing margin.** Their channel pixel counts are 73–2,764, all below the 3,000-pixel big-tile cut, so they enter neither coverage nor synchrony. Big-tile statuses are point 620, interval 15, unconfirmed 404, no_rise 76, missing_first_post_band_month 32 and no_window 31.

### What a longer window would buy

Extending the window past the peak by the confirmation gap, so the frozen rule can see the following month, would confirm 304 `unconfirmed` rows (252 on big tiles). Big-tile coverage would rise to 0.753, still below 0.90. This is post hoc and is not adopted.

### Provenance

- **Script hash.** The receipt's `script_sha256` (`e935821cab8632e0335c03e14907a00b9cc10d0e3ff9e0f5d6573346ea3df729`) hashes the Windows working-tree file, which has CRLF line endings under `core.autocrlf=true`. Git stores the script with LF line endings, SHA-256 `aebebc8a7e22a6246615f67d68926c5c94d4cd8bfbdb1aea98beeb0799e3b899`. Both identify the same committed script; a checkout on Linux or macOS reproduces the LF hash.
- **Freeze timing.** The strict-JSON fix (`da81ded`, 20:08:58) was committed one minute before the freeze commit (`bf2ae59`, 20:09:58). The run was recorded at 20:10:25 with `git_head` `bf2ae59`. The fix shows the receipt writer had produced a non-finite value before the freeze; the data it ran on then was not recorded. The disclosure under "Freeze" covers only the exploratory proxies.
- **Files.** The receipt and summary moved unchanged from `dev/reports/`, which the repository ignores, to this folder: [receipt](2026-10-30-clock-anchor-stage0-receipt.json) (SHA-256 of its LF-normalised bytes `5bbf372fff9b479fbd20dda84a12271d614f5975c344b61bde41a9a6078e78bc`) and [summary](2026-10-30-clock-anchor-stage0-summary.md). The 7,790-row table is `2026-10-30-clock-anchor-stage0-rows.csv.gz`; its uncompressed bytes are the run's CSV, SHA-256 `ef13e8114383167256e5c9257b221eb7e3f4023b1bf1827ecbc30c3eea10b143`. The frozen script's usage text still names the old `dev/reports/` paths and is left unchanged to keep its hash. The plan is a local working file under `docs/superpowers/`, which the release repository does not track; the version used is in commit `4ab73da`.
- **Guards.** `tests/test_clock_anchor_stage0.py` checks the Results table against the receipt, the receipt against the row table, the diagnostics against the row table, the numbers in this section against the diagnostics, and the frozen script against both hashes.

### What this changes downstream

- At monthly cadence a rise rule mostly finds the peak. Locating a rise edge needs per-scene observations, or a confirmation window that extends past the peak. Either is a new pre-registered test, not a rerun of this one.
- The hydropools monthly composite reads a pixel wet only when clear-wet scenes outnumber clear-dry ones, and ties read dry. That vote can push an onset into the following month. Rerunning the hydropools extents with ties read wet is the cheapest structural check before any per-scene work.
