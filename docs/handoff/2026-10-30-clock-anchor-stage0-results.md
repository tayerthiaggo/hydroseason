# Clock anchor stage 0: frozen rise rule versus end-dry as run

Date: 2026-10-30. Branch `clock-anchor-stage0`. Plan: [2026-10-30-clock-anchor-stage0.md](../superpowers/plans/2026-10-30-clock-anchor-stage0.md). Question: does a frozen rise rule agree across Fitzroy tiles better than the end-dry hydropools uses today?

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

(filled in Task 8)
