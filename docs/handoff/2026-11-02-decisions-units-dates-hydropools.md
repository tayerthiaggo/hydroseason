# Decisions: spatial units, dates and HydroSeason in hydropools

Date: 2026-11-02. Library decisions change documentation and add warnings only; none changes method policy `hydroseason-v0.2.0`, its thresholds or its outputs.

## Principle

HydroSeason describes what the water extent does. It is not referenced to stream gauges. Extent and discharge measure different things and do not always agree, and the library has to work anywhere, with or without a gauge. The method is the same whatever area it is given; the results depend on the area. What the library tells users is therefore advice about choosing and reading areas, and that advice rests only on evidence from the extent itself. Gauges stay ancillary context, as `docs/methods.md` already says of streamflow and rainfall.

## Status (2026-11-03)

| Item | Status |
| --- | --- |
| U1–U4 | Approved and implemented on branch `spatial-unit-study`. U2 was revised after review (see below). |
| X1, cross-scale agreement | Done ([results](2026-11-02-x1-cross-scale-agreement-results.md)). Peaks transfer more readily than trough boundaries, and the nearest containing subbasin is a better source than the whole catchment. A whole catchment's trough boundary should not be borrowed. The guide carries this. |
| G1, gate calibration | Run ([results](2026-11-02-g1-gate-calibration-results.md)). The pre-registered rule supports looser gates (ratio 1.5, 2 peak pixels) as a candidate. Closed by G2: the candidate is not adopted. |
| G2, known-truth gate test | Run 2026-11-03 ([results](2026-11-02-g2-known-truth-gates-results.md)). **Did not pass: the current gates (3.0, 5 pixels) stay.** It also found that `point` trough dates miss by more than a month far more often than the 0.2.0 safety bound allows, under the current gates too, and that troughs on long recessions are dated early. The project lead approved the next steps on 2026-11-03. The docs now say `point` means "distinct", not "exact". |
| L1, timing labels against known truth | Run 2026-11-03 ([results](2026-11-03-l1-timing-labels-results.md)). **G2's finding is confirmed on fresh seeds: 28% (synthetic) and 25% (injected) of `point` trough dates miss by more than a month. No tolerance setting passes, so there is no candidate and the library is unchanged.** Exploratory checks found that the trough label compares the boundary only with the months before it, back to the peak. The docs now say so. Proposals await the lead. |
| L1 follow-ups (B1 baseline, D1 boundary) | Measured 2026-11-03 ([results](2026-11-03-l1-followups-results.md)); not pre-registered. A misdated trough boundary reads the dry level as well as a correct one. The baseline's `point` requirement leaves most records without a baseline and buys no accuracy. The boundary passes over a lower month for designed reasons (the cloud screen and the search window), and neither costs accuracy overall. |
| L2, two-sided trough label | Run 2026-11-03 ([results](2026-11-03-l2-r1-results.md)). **Did not pass.** Also comparing the months after the boundary cuts the `point` miss share by only 2.4 points (synthetic) and 1.4 points (injected), and `point` stays less reliable than `interval`. No candidate; the library is unchanged. An exploratory check found that the `point` label can belong to an earlier, cloudy month rather than the reported `trough_date`. |
| R1, rise against trough | Run 2026-11-03 (same results). **Did not pass.** A standard 20% amplitude rise dates the dry-to-wet transition better than the trough boundary on sharp-rise seasons (+26 points, synthetic) but worse on smooth ones (−12 and −20 points). No support for a rise anchor. |
| Real-record impact (baseline rule, label/date mismatch) | Measured 2026-11-03 ([results](2026-11-03-real-record-impact-results.md)); a measurement, not a test. Allowing any dated status gives about ten times as many units a condition baseline. Recharge labels repeat between pixel halves as well as today's; for refuge labels the pre-registered comparison is inconclusive, and an exploratory measure hints they repeat less in the newly labelled units. The `point` label belongs to a month other than `trough_date` in 9–12% of `point` troughs on small G1 windows, usually several months earlier. |
| B2, refuge condition labels | Run 2026-11-04 ([results](2026-11-04-b2-refuge-labels-results.md)). **Passed.** On known truth, letting any dated cycle anchor the baseline does not make refuge labels worse where both rules give them, and the refuge labels it adds beat chance (kappa 0.35 synthetic, 0.38 injected; fair, not good). Recharge labels, reported only, also passed. |
| Next method policy (`hydroseason-v0.3.0`) | Approved 2026-11-04: A (gates in the manifest), B (widen the trough label to cover the boundary) and C (any dated cycle anchors the baseline). Built on branch `method-v0.3.0` ([proposal](2026-11-04-v0.3.0-proposal.md)). |
| H1 | Not a library decision; handed to hydropools as their own validation |
| H2–H5 | Hydropools decisions; proposed |

## Evidence used

1. **Spatial unit study** (pre-registered), [2026-11-02-spatial-unit-study-results.md](2026-11-02-spatial-unit-study-results.md). 1,278 areas over the five case-study catchments.
   - Grid tiles and HydroBASINS subbasins give equivalent results at matched size.
   - Small areas detect the season, but their troughs agree with the catchment's in only 38–45% of cases (exploratory).
   - 24.7% of level-7 subbasins in seasonal catchments have a trough more than one month from the catchment's.
   - The Lachlan is aseasonal as a whole, yet 16 of its 36 level-7 subbasins are seasonal.
2. **Hydropools U1/U2 handoff**, `hydropools/docs/handoff/2026-11-02-hydroseason-handoff-u1-u2.md`. Findings about the library, independent of gauges:
   - Passing counts removes the machine-epsilon floor.
   - Identifiability improves with unit size: the peak becomes a point and the trough stops being unresolved.
   - The clock fields did not move between 0.2.0 and `d32dd47`.
   - Reach-scale floodplain series carry little timing of their own.

## Advising library users

**U1. Spatial unit guidance: implemented.** Guide section "Choosing the area to analyse":
- Any polygon works.
- Small areas date the season less consistently.
- Run subbasins before concluding a large catchment has no season.
- Analyse a reach or refuge directly when its own timing matters.

**U2. The dates around the dry-season low: implemented, revised.** Guide section "Dates around the dry-season low":
- `trough_boundary_date` is the boundary the trough method places at the end of the dry-season low; the guide points to the method rather than paraphrasing it.
- The following year's `start_date` is that boundary plus one month by construction.
- Because both come from one boundary, they vary across a catchment in the same way.

The first draft called the trough "the driest month", presented `start_date` as more widely shared than the trough, and quoted gauge agreement. All three were removed:
- The trough method is more than finding a minimum.
- A date that is the boundary plus one month cannot be more or less synchronous than the boundary.
- The library is not referenced to gauges.

**U3. Pixel counts: implemented (docs and two warnings).**
- *Docs:* recommend passing `n_water`, `n_valid`, `n_invalid` and `n_aoi`, and say that with counts `extent_pct` is recomputed as `100 * n_water / n_valid`.
- *Warning 1:* fires when a supplied `extent_pct` disagrees with the counts.
- *Warning 2:* fires when a record without counts has a cycle whose detectability floor is effectively zero.
- Outputs are unchanged.

**U4. Parallel runs: implemented (docs).** Set `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` to 1 per worker in your own process pools.

**U5. Series with no hydrological years: deferred** until hydropools supplies examples.

**U6. Slow series: deferred** until hydropools logs per-series wall time and identifiers.

**Not changing:**
- The identifiability gates (frozen policy).
- The meaning of `start_date`.
- No new rise estimator.

## X1. Cross-scale agreement (next evidence step)

**Question:** how well do a larger area's dates stand in for the dates of the areas inside it, year by year, and how does that change with the inner area's size? This rests only on the extent. It reuses the spatial unit study series: catchments and HydroBASINS levels 6–8, nested by construction.

**Outcomes:** the share of inner-area years whose peak month, and whose trough boundary, falls within one month of the containing area's in the same hydrological year. Each is reported by the inner area's size in water pixels, for the immediate parent and for the whole catchment. A plan with fixed thresholds is written before the run.

**What it would support:**
- A rule of thumb for when one large-area run can serve the places inside it, and when places need their own run.
- Whether peaks and trough boundaries differ in how widely they are shared.

## G1. Gate calibration (run 2026-11-02)

The amplitude-to-floor ratio (3.0) and the 5-pixel peak minimum gate every cycle's timing. Their only real-data check is CAMELS-AUS. The project lead notes that this is a poor set for these gates, because most of its catchments are upper catchments with little or no surface water. The gates are therefore untested where HydroSeason is mostly used: lowland channels, floodplains and wetlands.

Open choices:
- **Reference standard, without gauges.** Candidates:
  - split-half reliability, which asks whether two random halves of a unit's pixels give the same dates;
  - cross-scale agreement (X1);
  - realistic synthetic records with a known answer.
- **Data:** water-bearing units with pixel counts, such as the spatial unit study units and the hydropools reach and tile series.
- **Rule:** fix the rule for choosing the thresholds, and the held-out split, before looking.

Any change to the gates is a new method policy version, not a patch. Meanwhile the docs say what the gates were checked on and no longer call them calibrated.

**Outcome.** The agreed plan used 319 national windows: 178 for calibration and 141 locked for confirmation. The yardstick was 2 km block split-half reproducibility, and the grid ran both looser and tighter than today. Results: [2026-11-02-g1-gate-calibration-results.md](2026-11-02-g1-gate-calibration-results.md).
- On water-bearing windows, tightening the ratio gate lowers reproducibility at every step. Open gates do as well as any tested value.
- The rule chose ratio 1.5 and 2 peak pixels, the loosest grid point. Confirmation passed all four checks: 12.3% more dated trough boundaries, reproducibility −0.010, route agreement −0.011.
- The added cycles reproduce about half the time (exploratory).
- Rerunning the 0.2.0 synthetic suite shows that its records never fall between ratio 0 and 3, so every gate value tied. The current 3.0 and 5 were the stricter tie-break, not values the evidence chose.

**G2 (run 2026-11-02 to 2026-11-03). A known-truth test in the gates' range.** The project lead chose synthetic truth, so the test used both arms: synthetic records that borrow real observation gaps (S), and known seasons injected into 287 real flat records (I). The plan was frozen before any outcome. Results: [2026-11-02-g2-known-truth-gates-results.md](2026-11-02-g2-known-truth-gates-results.md).
- **G2 did not pass, so the current gates stay.** Three of five rules failed.
  - In arm S, the added dates are less accurate than the current margin: 0.497 against 0.632, 95% interval of the difference [−0.179, −0.090].
  - In both arms, the added `point` dates are often wrong: 58% in arm S and 29% in arm I, against a 5% bound.
  - In arm I, the added dates are as accurate as the margin. Null records do not turn seasonal.
- **The current gates fail the same precise-date rule in their own margin:** 42% and 39% of `point` dates are wrong. The 0.2.0 calibration found none wrong, but its corpus had no noise.
- **Exploratory: on long recessions, the dated trough falls early, at every ratio.** For smooth seasons, `interval` dates are right more often than `point` dates.
- **Proposed, for the project lead to decide:**
  - a pre-registered known-truth test of the timing labels on fresh seeds;
  - rewording `point` in the docs, as advice;
  - a known-truth test of a rise-based anchor (the clock-anchor thread);
  - making the method policy fingerprint cover the timing gates at the next policy version.

**What happened to each step (2026-11-03).**
- **Timing labels.** This became L1 ([plan](2026-11-03-l1-timing-labels-plan.md)).
  - Rerunning 140 G2 records showed that about 65% of dated cycles keep the pass-1 label. That label counts the months within one floor of the cycle minimum. The other 35% are relabelled by trough refinement, and `point` dates were wrong less often after refinement.
  - L1 therefore varies only the pass-1 trough tolerance, using three standard values: √2, 1.645 × √2 and 1.96 × √2 floors.
  - Trough refinement is not tuned, to avoid fitting a complex estimator to synthetic records.
- **Docs.**
  - `docs/report-columns.md`, `docs/hydrological-state.md` and the guide now say `point` means the extremum is distinct, not that its month is exact. They list the `broad` trough status.
  - The guide gives G2's numbers for how far to trust a single trough month.
  - `docs/hydrological-state.md` says the gates held up in G2.
  - `tests/test_guide_advice.py` guards the wording.
- **Rise anchor.** No separate test is needed for the library's own rise.
  - HydroSeason's rise (`recovery_start_month`, internal) is always the trough boundary plus one month. On a known-truth record, its error against the true rise equals the boundary's error against the true trough, which G2 and L1 already measure.
  - A rise detected independently of the trough would be a new estimator. The clock-anchor thread left that to the project lead's choice of target and its own pre-registration, so nothing was built.
- **Fingerprint.** `method_policy_manifest()` does not include `TIMING_IDENTIFIABILITY_FINGERPRINT` or the gate values. Two outputs made with different gates therefore carry the same fingerprint.
  - Adding the gates changes every fingerprint, so the change belongs with `hydroseason-v0.3.0`.
  - `tests/test_method_policy.py::test_manifest_covers_timing_identifiability_gates` is a strict expected failure. It will start passing, and so fail the suite, when the manifest gains the gates, which forces the marker to be removed with that change.

- **L1 outcome (2026-11-03).** Confirmed G2 on fresh seeds; no tolerance setting passed ([results](2026-11-03-l1-timing-labels-results.md)).
  - Widening the tolerance to 2.77 floors removed 32% to 44% of `point` dates and of baseline-eligible cycles, but the miss share only fell from 28% to 25% (synthetic) and from 25% to 23% (injected).
  - Exploratory: most misses are months that really were lowest in the data, and the trough label never compares the boundary with the months after it. The noise floor is not too small.
  - Baseline-eligible trough boundaries were within a month of the truth 76% (synthetic) and 80% (injected) of the time.

- **L1 follow-ups, L2 and R1 (2026-11-03).**
  - **B1** ([results](2026-11-03-l1-followups-results.md)). A misdated boundary reads the dry level as closely as a correct one (median 0.48 against 0.52 floors). Requiring `point` labels only 4.9% (synthetic) and 21.7% (injected) of cycles; any dated status labels 36.3% and 66.1%, with at least the same agreement with the truth on the cycles both label. The labels it adds are weak: 0.520 against 0.440 by chance (synthetic), and 0.417 against 0.423 by chance (injected). (Qualifier added 2026-11-04.)
  - **D1** (same results). Where the boundary passed over a lower month, that month was cloudy or beyond the search window. The cloud screen is neutral (synthetic) or helps (injected). No change.
  - **L2** ([results](2026-11-03-l2-r1-results.md)). Did not pass. The `point` dates that still miss are single months that read more than a floor below the true month, so no label tolerance or direction fixes them. With L1, three tests now agree that `point` is not a reliable exact-date tier on weak or flat-bottomed seasons.
  - **L2, exploratory.** In 13% of injected `point` trough cycles (2% synthetic), the label's single month is an earlier, cloudy month that the trough selection screened out. The row still reports `point` for the later boundary month. None of the 85 `point` cycles in the three routed case-study catchments showed this.
  - **R1** (same results). Did not pass. The rise rule wins on sharp-rise seasons in arm S only, and loses on smooth seasons in both arms. The rise question in the clock-anchor thread can close for now; the trough-band end stays the anchor.
  - **Real-record impact** ([results](2026-11-03-real-record-impact-results.md)). Measured on the G1 windows (both pixel halves) and the spatial-unit-study units.
    - Any dated status gives a baseline to 62% of G1 core units and 45% of quadrants, against about 5% today. Dropping the timing requirement altogether adds almost nothing more.
    - Agreement between halves on the labels relaxing adds, minus today's: recharge −0.025 [−0.104, +0.052], refuge −0.014 [−0.096, +0.069]. Both are inconclusive, because today's rule labels only 16 of 256 windows.
    - Exploratory: refuge labels in the added units agree less beyond chance (kappa 0.41 against 0.51). Recharge labels do not.
    - Of the case-study catchments, only the Gilbert gains a baseline.
    - The label/date mismatch affects 12.3% of `point` troughs on G1 core units, 9.2% on quadrants, 3–5% on subbasins and tiles, and none on whole catchments. The median gap is 3 months.

**Candidates for `hydroseason-v0.3.0`.** Decided 2026-11-04: 1, 4 and 5 (widen form) are adopted; see the [0.3.0 proposal](2026-11-04-v0.3.0-proposal.md).
1. Add the timing-identifiability gates to the method policy manifest and fingerprint.
2. ~~If L1 names a candidate trough tolerance, adopt it.~~ L1 named none.
3. ~~A two-sided trough label.~~ L2 did not pass.
4. Relax the baseline's timing requirement from `point` to any dated status (B1). B1 found that a misdated boundary does not change the dry level the baseline reads, and that the `point` requirement buys no accuracy. On known truth, the recharge labels it adds were weak (at chance on injected records). Real records (measured): about ten times the coverage, and no repeatability cost for recharge labels; repeatability is not accuracy. Refuge labels have never had a known truth, and their real-record result is unresolved. B2 ([plan](2026-11-04-b2-refuge-labels-plan.md), [results](2026-11-04-b2-refuge-labels-results.md)) scored refuge labels against a known truth and passed, so this is adopted. Full proposal: [0.3.0 proposal](2026-11-04-v0.3.0-proposal.md). If adopted, update the docs that call `point` "a defensible exact date".
5. Make the trough label and `trough_date` refer to the same month (L2, exploratory finding 2): either judge the label on the cloud-screened months the boundary uses, or downgrade it when the boundary is outside its own trough interval. Measured: 9–12% of `point` troughs on small G1 windows. Judging on screened months would leave the search-window cases. Downgrading covers every case and costs those 9–12% of `point` troughs (recommended).

## Hydropools (their decisions)

The gauge comparisons below are hydropools' business. Their target, the month the river starts flowing again, is a flow concept, so their own referee is gauge first flow. The library does not adopt it.

**Context they may use.** This is an exploratory re-scoring of their referee tables (`outputs/u1/fitzroy/gauge_years.csv`, `u2_gauge_years.csv`, `outputs/u1/gilbert/gauge_years.csv`). A hit is within ±1 month of the gauge end-dry month.

| Clock | Main stem (58) | Tributaries (238) | Tributaries, Sep–Jan spells (187) | Gilbert 917001D (15) |
| --- | ---: | ---: | ---: | ---: |
| Reach trough clock (a) | 0.91 | 0.45 | 0.58 | 0.60 |
| Reach trough clock + 1 | 0.97 | 0.56 | 0.71 | 0.80 |
| Catchment median clock (d) | 0.90 | 0.66 | 0.84 | 0.67 |
| Catchment median clock + 1 | 0.98 | 0.75 | 0.95 | 0.80 |

- **The +1 shift** is the offset between the end of the extent's dry-season low and flow resuming at a gauge. It equals the next year's `start_date` and is a mapping choice for hydropools, not a property of the method.
- **The catchment-wide advantage on tributaries** is about which area best tracks their gauges. Whether a large area's dates represent its parts *in the extent* is X1's question.

**H1.** Whether to read their clock at the basin, one month after the trough, is theirs to test against their referee. The draft plan [2026-11-02-h1-wet-return-clock-plan.md](2026-11-02-h1-wet-return-clock-plan.md) is offered to them as a starting point. BoM lists unscored discharge gauges in the Daly (37), Lachlan (56), Moonie (4) and Gilbert (1).

**H2.** If they read clocks at a large area and the basin routes aseasonal, use subbasins; the Lachlan shows a basin total can hide seasonal parts. X1 will say where a basin's dates stop representing its parts.

**H3.** Retire the reach-level merge chain only if their own test supports a larger-area clock.

**H4.** Do not run HydroSeason on reach-scale floodplain series:
- 26% of pool-years have no floodplain pixels;
- 37% return no hydrological year;
- where a peak exists, it matches the channel's month in 78% of pool-years.

**H5.** Keep passing counts, set the BLAS thread variables, and pin the HydroSeason version.

## Answers to the hydropools asks (handoff section 4)

1. **Rise-side date:** the next year's `start_date` exists and is the trough boundary plus one month. Whether it matches first flow is for their referee.
2. **Where to read it:** extent-side evidence comes from X1; flow-side evidence from their own test.
3. **Count convention:** documented, and warned on (U3).
4. **Slow series:** U6.
5. **No-years reason:** U5.
6. Carried questions:
   - **`start_date`:** keeps its meaning.
   - **Calibration:** see G1.
   - **WaterMask-TSFill rank transform:** not assessed.
