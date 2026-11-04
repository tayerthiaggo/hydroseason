# G1: checking the identifiability gates on water across Australia (pre-registration)

Status: **agreed design, 2026-11-02.** The project lead answered the review questions:
- 2 km blocks;
- a target relative to the water-rich ceiling;
- the 1988–2025 period;
- looser gates tested as well as tighter ones.

The SHA-256 of this file goes into the run receipt before any outcome is computed. Later edits are reported as deviations. The confirmation windows stay unopened until the calibration choice is written to the receipt.

Background: decision G1 in [2026-11-02-decisions-units-dates-hydropools.md](2026-11-02-decisions-units-dates-hydropools.md). The gates under review live in `hydroseason/_scientific_defaults.py`:
- `min_amplitude_to_floor_ratio = 3.0`;
- `min_peak_water_pixels = 5`.

They decide whether a cycle's timing counts. They also feed the regime test, so they affect routing. Their only real-data check so far is CAMELS-AUS, mostly upper catchments with little water.

## Principles

- **Data driven.** Any change must earn its place on data the choice never saw.
- **No overfitting to familiar places.** The five case-study catchments and the CAMELS windows are never used to choose a value. They appear only in impact tables.
- **Not referenced to gauges.** The yardstick is how reproducible HydroSeason's own dates are, measured from the water extent.
- **Default is no change.** Unless confirmation passes, the recommendation is to keep the current gates.
- **Library untouched.** The harness sets the gates inside its own worker processes by overriding the frozen defaults object; for the swing alternative it wraps the detectability check. Every run records the gate values read back in its worker. The method fingerprint does not change with runtime gate values, so it is not the evidence.

## Data

319 windows of per-pixel monthly DEA WOfS counts. Each is 532 × 532 pixels at 30 m with a 10-pixel halo, about 15 km a side, in `D:\RLH\5.6\data_local\raw\WaterMask-TSFill\`. They come from the stratified national draws made for WaterMask-TSFill:
- strata are drainage division (13) × water type (`channel`, `broad` floodplain or wetland, `coastal`, `permanent` lake or reservoir);
- sites are random within each stratum, and each later draw is at least 30–50 km from all earlier windows.

Site lists with strata are in `WaterMask-TSFill/experiments/gapfill/national_*sites*.json`.

| Role | Draws | Windows |
| --- | --- | ---: |
| **Calibration** (values chosen here) | `national_train` (114), draw A `national` (64) | 178 |
| **Confirmation** (opened once, after the choice) | draws B (56), C (46), D (23), E (16) | 141 |
| **Report only** | CAMELS windows (110); the five case-study catchments | — |

Same composite rule as the library: per scene, flag 0 is dry and 128 is water; monthly majority, ties dry. Period 1988-01 to 2025-12.

## Units and the block split

- **Units:** each window's 512 × 512 core, and its four 256 × 256 quadrants. That gives about 236 km² and 59 km² of land and a wide range of water-pixel counts.
- **Block split:** each unit's pixels are split into halves A and B by a checkerboard of 67 × 67-pixel blocks (about 2 km), aligned to the core's corner. The 2 km block keeps long river corridors from being split into near-identical halves.
- **Series:** one count series per half. Each series is analysed with `analyze_catchment(extent, phase_scheme="two_phase", quality_policy="flag")` on count input, library defaults apart from the gate values, at the commit in the receipt.

## What is measured

**Per half-cycle.** For every cycle found in a half:
- its gate statistics: amplitude-to-floor ratio, peak water pixels, and swing in water pixels (peak minus trough);
- whether it is **reproduced**: the other half has a cycle matched by nearest peak within 6 months, whose `trough_month` is within 1 month (primary) and whose `peak_month` is within 1 month (secondary).

**Per unit:** whether both halves take the same route.

Gate statistics are measured on the series being judged, so a threshold learned on a half applies to any series with those statistics.

## Phase A: screening on the calibration windows, gates open

Every calibration half is run once with the gates opened (ratio 0, peak pixels 0), so that cycles today's gates reject still carry dates and statistics. A cycle at or below its floor stays undetectable, as in the library. Any candidate gate is then applied after the run:
- a half-cycle passes when its statistics clear the thresholds;
- it counts as reproduced only if its matched cycle in the other half also passes the same gate, because a real gate applies to both series.

**Candidate grid, looser and tighter than today:**
- ratio ∈ {1.5, 2, 2.5, 3 (current), 4, 5, 6, 8, 10, 15, 20};
- peak pixels ∈ {1, 2, 3, 5 (current), 10, 20, 50, 100, 200};
- as the alternative second gate (shape 2), swing pixels ∈ {0, 5, 10, 20, 50, 100, 200}.

**Target:** 0.95 × the trough reproducibility of half-cycles whose ratio and peak pixels are both in the top quartile of the calibration set.

**Choice:** among grid points whose passing half-cycles reach the target, take the one that keeps the most cycles; ties go to the larger thresholds.
- Shape 1, the current two gates with new values, is preferred.
- Shape 2 replaces the peak gate with the swing gate only if it keeps at least 5% more cycles at the same target.
- If no grid point reaches the target, no value is chosen.

The choice, the target and the reproducibility curves are written to the receipt before Phase B.

## Phase B: exact runs

Applying a gate after the run cannot show its effect on routing or on the refinement steps that read timing status. Phase B therefore reruns with the gates actually set.

1. **Check:** 40 calibration windows, chosen at random with seed 0 and stratified by water type, run with the chosen gates. The cycle-level choice must hold within 0.03 of Phase A's reproducibility; if not, the Phase A choice is reported as unreliable and no change is recommended.
2. **Confirmation:** the 141 confirmation windows, run once with the current gates and once with the chosen gates.

## Confirmation rules (held-out draws B–E)

The chosen gates are adopted only if all of the following hold:
1. Trough reproducibility of passing half-cycles is at least target − 0.03.
2. Against the current gates, either:
   - *(tightening)* reproducibility improves by at least 0.05, or
   - *(loosening)* passing half-cycles increase by at least 10% while reproducibility drops by no more than 0.02.

   In both cases a 95% bootstrap interval over windows must exclude 0 for the gain claimed.
3. No water type, and no group of drainage divisions with at least 30 passing cycles, falls below target − 0.10. The groups are:
   - **North:** Carpentaria Coast, Tanami-Timor Sea Coast, North Western Plateau, North East Coast.
   - **Arid interior:** Lake Eyre Basin, Pilbara-Gascoyne, South Western Plateau.
   - **South-east:** Murray-Darling Basin, South East Coast (NSW), South East Coast (Victoria), Tasmania.
   - **South and west:** South Australian Gulf, South West Coast.

   A half-cycle "has a date" when its `trough_timing_status` is `point`, `interval` or `broad` and, in Phase A, its statistics clear the gate. In the exact runs the library applies the gate itself.
4. Route agreement between halves is no worse than under the current gates by more than 0.02.

If any check fails, the recommendation is no change, with the curves published.

## Impact tables (report only)

At the chosen gates and at the current ones:
- cycles changing timing status, units changing route, and units losing baseline eligibility;
- shown for the confirmation windows, the CAMELS windows, the five case-study catchments and their subbasins (spatial unit study), and hydropools series if supplied.

These tables inform the decision but never choose the values.

## Further checks before any release

- **Known-truth accuracy:** rerun the existing synthetic validation suites with the chosen gates; reproducibility is not accuracy.
- **Cross-scale agreement:** rerun X1 under the chosen gates.
- **Policy:** a change ships as a new method policy version (`hydroseason-v0.3.0`) through the calibration pipeline that generates `_scientific_defaults.py`, with a new fingerprint and a changelog entry marked as a method change.

## Limits stated in advance

- **Shared conditions:** halves share clouds, sensors and the composite rule. Errors they share are invisible, so reproducibility measures precision only.
- **Unit size:** windows and quadrants are at most about 236 km². Gates matter most for small units, and large catchments appear only in impact tables.
- **Coverage:** some strata are thin, for example permanent lakes in draws B–E. Thin strata are reported, not used to decide.
- **Approximation:** Phase A applies gates after the run; Phase B measures how far that approximation holds.
- **Compute:**
  - Phase A: 178 windows × 5 units × 2 halves = 1,780 runs.
  - Phase B check: 400 runs.
  - Confirmation: 141 × 5 × 2 × 2 = 2,820 runs.
  - Impact runs on top.

  A pilot on 10 calibration windows estimates time before the full run.
