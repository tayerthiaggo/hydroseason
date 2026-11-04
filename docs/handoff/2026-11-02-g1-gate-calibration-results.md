# G1: identifiability gates on water across Australia — results

Date: 2026-11-02. Plan: [2026-11-02-g1-gate-calibration-plan.md](2026-11-02-g1-gate-calibration-plan.md), frozen before any outcome was computed. The plan's SHA-256 of LF bytes, `0c9f5deaeb00…`, is recorded in the [receipt](2026-11-02-g1-gate-calibration-receipt.json), whose own SHA-256 is `3673cacbcf5fb5e403075ec72ce7b7f8446c64e1dcd2f13b044f088d7b716c8f`. Numbers come from [2026-11-02-g1-gate-calibration-results.json](2026-11-02-g1-gate-calibration-results.json) and the receipt. Only the water extent was used; no gauge entered.

> **Update 2026-11-03: closed by G2.** The known-truth test did not pass, so the current gates stay and the candidate below is not adopted. On synthetic records, the dates the looser gates add are less accurate than the current margin. See [2026-11-02-g2-known-truth-gates-results.md](2026-11-02-g2-known-truth-gates-results.md).

## Summary

The pre-registered rule returns **adopt** for looser gates: an amplitude-to-floor ratio of **1.5** (now 3.0) and a peak minimum of **2 water pixels** (now 5). All four confirmation checks pass on the 141 locked windows, through the loosening branch:
- 12.3% more half-cycles get a dated trough boundary;
- reproducibility drops by 0.010;
- route agreement drops by 0.011.

This is **not a library change**. The plan requires further checks before any release. The first, rerunning the existing synthetic suite, passes the chosen gates but cannot tell them apart from the current ones (see below). Accuracy against a known truth in the range that matters is therefore still untested. Method policy `hydroseason-v0.2.0` and its gates are unchanged.

What the evidence says about the gates themselves:
1. **The ratio gate does not buy reproducibility on real water.** On the calibration windows, every step up the ratio grid lowers trough reproducibility, from 0.604 at 1.5 to 0.548 at 20. With the gates fully open, reproducibility is 0.603, level with the chosen gates. The chosen 1.5 is the loosest value in the grid, so the rule picked the edge of what was tested, not an interior optimum.
2. **A larger peak in water pixels does help, slightly.** Raising the peak minimum from 5 to 200 pixels lifts reproducibility from 0.601 to 0.610 while removing a quarter of the cycles. No grid point reached the water-rich ceiling of 0.618.
3. **The confirmation agrees with the calibration**, but it shows a price. The cycles the looser gates add reproduce about half the time (0.51, exploratory), against 0.61 for the cycles today's gates already pass.
4. **No evidence ever favoured the current values over lower ones.** The 0.2.0 synthetic calibration tied every ratio in {1, 1.5, 2, 3} and every peak minimum in {1, 2, 3, 5}. Its final rule takes the stricter value on a tie, so it picked the top of each grid. No synthetic record had a ratio between 0 and 3.

## Calibration (Phase A, 178 windows, gates applied after the run)

1,780 runs, no errors, all with gates open (read back as ratio 0, 0 pixels). 45,524 half-cycles; 32,172 have a dated trough boundary.

Target: 0.95 × 0.618 = **0.588**. The ceiling, 0.618, is the reproducibility of half-cycles whose ratio (≥ 34.8) and peak pixels (≥ 3,640) are both in the top quartile.

Ratio gate, at the current 5-pixel peak minimum:

| Ratio | 1.5 | 2 | 2.5 | 3 (now) | 4 | 5 | 6 | 8 | 10 | 15 | 20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Reproducibility | 0.604 | 0.603 | 0.601 | 0.601 | 0.599 | 0.594 | 0.586 | 0.578 | 0.569 | 0.553 | 0.548 |
| Passing half-cycles | 30,975 | 30,361 | 29,662 | 28,895 | 26,969 | 24,936 | 22,906 | 19,719 | 17,323 | 13,471 | 11,252 |

Peak gate, at the current 3.0 ratio:

| Peak pixels | 1–3 | 5 (now) | 10 | 20 | 50 | 100 | 200 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Reproducibility | 0.600 | 0.601 | 0.603 | 0.605 | 0.606 | 0.607 | 0.610 |
| Passing half-cycles | 29,062 | 28,895 | 28,331 | 27,504 | 25,974 | 24,252 | 21,963 |

The swing gate (shape 2) behaves like the peak gate, from 0.600 at 0 pixels to 0.609 at 200. It never kept 5% more cycles than shape 1, so shape 1 was kept.

**Choice:** ratio 1.5, peak 2 pixels; reproducibility 0.603 on 31,511 passing half-cycles (current gates: 0.601 on 28,895, so +9.1%). Peak minimums of 1 and 2 give identical results, because no dated cycle peaks below 2 pixels.

**Phase B check (40 calibration windows, gates set in the library):** 0.668 exact against 0.666 applied after the run. The difference, 0.001, is within the 0.03 allowed, so the Phase A choice holds.

## Confirmation (141 locked windows, draws B–E)

2,820 runs, no errors; every run read back the gates it was given.

| Gates | Trough reproducibility | Passing half-cycles | Route agreement between halves |
| --- | ---: | ---: | ---: |
| Current (3.0, 5 pixels) | 0.609 | 20,183 | 0.884 |
| Chosen (1.5, 2 pixels) | 0.598 | 22,660 | 0.872 |
| Change | −0.010 (95% interval −0.020 to −0.001) | +12.3% (95% interval +10.0% to +15.0%) | −0.011 |

| Check (plan) | Rule | Result |
| --- | --- | --- |
| 1. Reproducibility at target | ≥ 0.588 − 0.03 = 0.558 | 0.598, pass |
| 2. Gain over current | Loosening: ≥ 10% more passes, interval excludes 0, drop ≤ 0.02 | +12.3%, interval from +10.0%, drop 0.010, pass |
| 3. No stratum fails | No water type or group with ≥ 30 passes below 0.488 | lowest 0.522 (South-east), pass |
| 4. Route agreement | No worse than current by more than 0.02 | −0.011, pass |

Two readings of check 2 matter. The drop in reproducibility is small but real: its interval excludes zero. And the lower end of the interval for pass growth sits right at the 10% the rule asks of the point estimate.

By stratum (chosen gates; change from current in brackets):

| Stratum | Reproducibility | Passing half-cycles |
| --- | ---: | ---: |
| Broad floodplain or wetland | 0.662 (−0.013) | 8,895 (+9.2%) |
| Channel | 0.554 (−0.012) | 11,860 (+13.3%) |
| Coastal | 0.525 (+0.029) | 1,340 (+33.6%) |
| Permanent lake or reservoir | 0.676 (+0.047) | 565 (+0.4%) |
| North | 0.586 (−0.014) | 8,075 (+11.5%) |
| Arid interior | 0.600 (−0.024) | 5,470 (+15.7%) |
| South and west | 0.662 (+0.004) | 5,619 (+6.8%) |
| South-east | 0.522 (+0.005) | 3,496 (+18.4%) |

Permanent lakes are thin in draws B–E (3 windows) and are reported, not used to decide.

## Impact on the confirmation windows (report only)

- **Routes:** 66 of 1,410 half-unit series change route. 53 move from event characterisation to per-year detection, and 13 move back.
- **Trough status, series whose route is unchanged:** dated trough boundaries rise from 19,953 to 21,682 (+8.7%). Unresolved boundaries fall by 1,729, which become broad (+734), interval (+525) or point (+470).
- **Peaks:** dated peaks rise from 21,994 to 24,206.

## Exploratory findings (after the outcome; not part of the decision)

- **Robustness of the gain.** 117 of the 126 confirmation windows that have any dated cycle gain passes. Dropping any one window leaves growth at 11.9% or more.
- **The cycles the looser gates add.** Across windows, the extra 2,477 passing half-cycles add 1,272 reproduced ones, a marginal reproducibility of 0.51. This is a window-level difference, because routing changes too, so it is approximate.
- **What predicts reproducibility.** In Phase A, by quartile of each statistic:

  | Quartile, low to high | Peak pixels | Swing pixels | Amplitude | Ratio |
  | --- | --- | --- | --- | --- |
  | Trough reproduced | 0.48, 0.59, 0.65, 0.69 | 0.48, 0.59, 0.64, 0.71 | 0.49, 0.60, 0.66, 0.66 | 0.50, 0.63, 0.65, 0.63 |

  The amount of water in a cycle predicts reproducibility steadily. The ratio does not, beyond its lowest quartile. Ratio correlates with floor at −0.35 and with amplitude at +0.35 (Spearman), so a high ratio often means a tiny floor, not a large cycle.
- **Why a hard gate gains so little.** A cycle counts as reproduced only if its twin in the other half also passes. Two near-identical halves often fall on opposite sides of a sharp threshold. Each gain from tightening is offset by these flips. That is a property of any hard cut-off on noisy statistics, not a fault of the harness.
- **The 2 km halves see different water.** Units whose halves are larger (core, 0.695) reproduce better than quadrants (0.575). Some of what the split measures is how different two sets of 2 km blocks are, not only measurement noise.

## What it means

- **On water-bearing units, the 3.0 ratio gate removes about 10% of dated cycles and makes the rest no more reproducible.** The data give no support for tightening it, and the pre-registered rule supports loosening it.
- **Reproducibility is precision, not accuracy.** The two halves share clouds, sensors, scene dates and the composite rule. A cycle created by an error both halves share reproduces perfectly. The gates exist to stop the method from dating such cycles near the detectability floor. Whether ratio 1.5 dates them wrongly is exactly what split-half evidence cannot see.
- **The pixel count of a cycle is the better reliability signal.** The exploratory results point there. The guide already says trough boundaries are less consistent below about 100 water pixels a month. Reporting a cycle's water-pixel size, rather than tightening a gate, is a candidate for later work. It would be a separate, pre-registered question.

## The existing synthetic suite, rerun

The plan's first check before release is to rerun the existing synthetic validation suite with the chosen gates. That suite, the 0.2.0 timing-identifiability calibration, was removed from the library before 0.2.0 (commit `88b78cd`). `scripts/g1_synthetic_suite_rerun.py` runs it from the last commit that had it, `a6e5a41`, without importing the current library. Record: [2026-11-02-g1-synthetic-suite-rerun.json](2026-11-02-g1-synthetic-suite-rerun.json).

- **The 0.2.0 selection reproduces exactly:** ratio 3.0 and 5 peak pixels, with the same survivor counts as the frozen record (432 → 288 → 288 → 192 → 192, then 48 after the larger-ratio tie-break and 12 after the larger-peak tie-break).
- **The corpus has no record in the range the gates decide.** Of 100,000 annual rows per partition, 53,750 have a ratio of 0, 17,500 lie between 3 and 25, and 28,750 are at 25 or above. None lies between 0 and 3. No row with a ratio above 0 has fewer than 5 peak water pixels.
- **All gates score the same.** On both partitions, the current, chosen and fully open gates give 0 false precise boundaries in 31,250, correct abstention 1.0, annualisation recall 1.0 and a median boundary error of 0 months.

So the check passes, but it carries no information about the change. The current 3.0 and 5 were the stricter ends of a grid whose values all tied, not values the synthetic records supported over lower ones. A known-truth test in the range between ratio 1.5 and 3, and between 2 and 5 peak pixels, needs its own pre-registered design (proposed as G2).

## Before any change (from the plan)

1. **Accuracy against a known truth in the gate's range** (G2, above). The existing suite is done and uninformative.
2. **Cross-scale agreement (X1) under the chosen gates.**
3. **Impact tables** for the CAMELS windows, the five case-study catchments and their subbasins, and hydropools series if supplied.
4. **Policy.** If all of these hold, the change ships as `hydroseason-v0.3.0` through the calibration pipeline, with a new fingerprint and a changelog entry marked as a method change.

## Limits

- **Shared conditions:** reproducibility between halves measures precision only (see above).
- **Unit size:** units are at most about 236 km². Larger areas appear only in impact tables.
- **Grid edge:** the choice sits at the loosest ratio tested. The plan did not test opening the gates fully, although Phase A shows open gates score the same on reproducibility.
- **Thin strata:** permanent lakes (3 confirmation windows) and coastal windows (11).

## Provenance

- **Script:** `scripts/gate_calibration.py` (receipt hash `1b19e6055cf0…`), run at commit `d32dd47` on branch `spatial-unit-study`. The library was unchanged during the runs; no file under `hydroseason/` was modified after the freeze.
- **Synthetic suite rerun:** `scripts/g1_synthetic_suite_rerun.py`, run on the library tree at `a6e5a41` extracted with `git archive`, after the confirmation outcome was known.
- **Independent check:** the confirmation numbers were recomputed from the raw run files with a separate implementation of the matching and scoring rules. Reproducibility, passes and route agreement match to every digit.
- **Intermediate files:** in `D:\RLH\5.6\data_local\intermediate\hydroseason_gate_calibration` (`sites.csv`, `series/`, `phase_a.jsonl`, `curves.csv`, `phase_b.jsonl`, `confirm_current.jsonl`, `confirm_chosen.jsonl`, `g1.log`).
- **Deviations from the plan:** none in the decision path. The impact table above covers the confirmation windows only; baseline eligibility was not recorded in the runs, so units losing it are not counted. The exploratory findings were computed after the outcome.
