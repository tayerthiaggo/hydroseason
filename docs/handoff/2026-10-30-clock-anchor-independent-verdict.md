# Clock anchor: independent verdict (trough, rise, audit corrections, next experiment)

Date: 2026-10-30, Australia/Perth. Status: independent review of the [original proposal](D:/RLH/5.6/repos/hydropools/docs/handoff/2026-10-30-clock-anchor-analysis.md) and the [audit](2026-10-30-clock-anchor-audit.md), per the [review brief](2026-10-30-clock-anchor-independent-review.md). Read-only. No detector, default, threshold, test, output contract or external file was changed. Nothing here is a method decision; the lead decides the target.

Every claim below carries one of five evidence classes: **[source]** inspection of code at the pinned hashes; **[rerun]** behaviour reproduced in this session; **[artifact]** recalculated from historical outputs (not re-generated); **[inference]** scientific reasoning; **[policy]** proposed rule or workflow choice. Verdict words: agree / partly agree / disagree / not verifiable.

## 1. Verdict in brief

1. **The audit's numerical corrections all reproduce exactly** [artifact]: ratio table (913/92/1,005; 59/86/145; 33/80/113), endpoint cohort (26,633 / 523 / 26,110 / 10,914 / 9,876 / 1,038; 534 unobserved and 11 absent in `pool_years`), input statistics (19,434 / 18,610 / 11,388; median invalid 0.093 %, p95 34.5 %, p99 87.9 %), tolerance default 0.0 on the catchment path, `start_date` = previous boundary + 1 month. Section 4.
2. **The proposal's central empirical premise is unmeasured and, on its own series, not supported** [artifact, exploratory]. The proposal reports 93 % peak agreement and infers rise agreement. Three crude rise rules applied to the same channel series give 0.83 (first departure > 1 pp), 0.87 to 0.88 (doubling), and 0.93 only for a half-amplitude crossing, which lands in the peak month itself in at least half of tile-years (median gap to the next peak 0 months). The current end-dry as run scores 0.83. The 93 % figure is the peak's, not a rise's. Section 6.1.
3. **Neither document notices that hydropools already reads y at the end of the trough band in 1,057 of 1,544 windows, and that HydroSeason's operational boundary equals that band end in 1,389 of 1,410 cycles with an interval** [artifact, source]. HydroSeason also already defines its boundary as the "final interior month of the supported low state before sustained hydrological recovery" (`docs/methods.md` §4) and computes an internal `recovery_start_month`, which is boundary + 1 month and is not exported. As written, "end-dry = month before `rise_date` = band end" changes nothing for most tile-years. The real content of the proposal is (a) the floor on four tiles, (b) a departure-size status for the band end, (c) what to do with the 135 windows that fall to `hy_boundary` and the 264 `unresolved` troughs, and (d) censoring policy for years without a sustained rise. Section 3, finding 2.
4. **Observation-density bias is visible in the data** [artifact]: the wet-at-endpoint but dry-somewhere-in-window flip rate rises monotonically with observed months per window (0.8 %, 3.7 %, 4.1 %, 5.2 % for ≤2, 3–4, 5–6, 7–8 months). The proposal's era argument does not exclude it. The audit's objection stands with evidence.
5. **The falsification results support the trough as a recurring, identifiable calendar event on synthetic records and say nothing about any single year's endpoint date, about spatial synchrony, about onset, or about the Fitzroy.** They neither motivate nor refute a rise anchor. No current test adjudicates the rise proposal. Section 7.
6. **Recommendation:** do not change `start_date`, the basis chain, the re-wet guard or D8 on this evidence. Run the zero-cost stage 0 (frozen rise rule on existing series, leave-target-out synchrony) and stage A (input repair attribution) before any HydroSeason contract change. Freeze margins in section 10 before touching gauges or 2026 imagery.

## 2. Checkout and provenance differences (stated before judging)

- **The proposal file exists in three versions, none matching the audit's text.** The audit body cites SHA-256 `5cbe392f…`; the audit's own receipt pins `a5779286…` (17,256 bytes, 14:07 local); the file on disk at review time is `6619c823…` (19,223 bytes, modified 14:55, after the audit at 14:14) [artifact]. The file is untracked in hydropools, so no history exists. The current version revised section 1, section 5 and question 1 of section 6 to frame the ask as "the rise edge of the trough band with a departure-size status" rather than "first post-trough month exceeding the trough by the floor, staying above until peak". **Effect:** parts of audit §5 target superseded wording; its substantive points (reference low state, persistence, gaps, threshold scale, peak dependence, composites, latency) survive the rewording (section 5). This verdict judges the current version.
- HydroSeason HEAD is `505d42a` (one commit after the receipt's `6b3a58e`; it touches docs, scripts and tests only, nothing under `hydroseason/`). Every file pinned in the receipt hashes identically on disk, including the four `dev/reports` artifacts and the scratch `clock_quality.csv` [artifact].
- Hydropools checkout `ccc4ab0` matches the receipt. `outputs/rerun/fitzroy/manifest.json` records producer commit `3f54c6c`, hydropools 0.1.0; all 41 tile manifests record HydroSeason 0.2.0 with method fingerprint `4bcfed63…` (equal to `docs/method-policy-v0.2.0.json`) and inputs 1987-01 to 2026-06 (tile05 created 2026-10-25) [artifact]. `git diff 3f54c6c HEAD -- src/hydropools/seasons.py src/hydropools/pipeline.py` is empty, so the inspected `extent_series` is the one that produced the historical outputs. Not re-generated.
- Targeted tests the audit cited: `7 passed in 14.12s` [rerun].

## 3. Ranked findings

| # | Severity | Finding | Class | Effect on decision |
| --- | --- | --- | --- | --- |
| 1 | High | Rise synchrony was never measured; crude rise proxies on the same series are no more synchronous than the end-dry as run (0.83 vs 0.83; best non-peak rule 0.88). The 93 % is peak agreement. | artifact | Removes the stated reason to switch anchors. A frozen rise rule must be measured before any contract change (stage 0). |
| 2 | High | Band end is already the end-dry in 1,057/1,544 windows (`interval_end(*)` bases) plus 352 point windows where the band is one month; operational boundary = band end in 1,389/1,410 cycles; `recovery_start_month` = boundary + 1. | artifact, source | The proposal as written is a relabelling for most tile-years. Reframe the ask as floor, status semantics, `hy_boundary`/`unresolved` handling and censoring. |
| 3 | High | `pd.cut` upper edge dropped the 92 largest ratios (all floor = 2.2e-16; tiles 46/05/13/18). Corrected `ratio > 10` group: 14.4 % Jan–Aug ends, 11.2 % ≥ 3 months off median. | artifact | Ratio stratification does not isolate "real early troughs"; input repair comes first. Audit correct. |
| 4 | High | Input semantics: `extent_pct = 100·wet/n_aoi` vs HydroSeason's `100·n_water/n_valid`. Invalid share > 20 % occurs in 14–21 % of Dec–Mar rows but only 2–5 % of Apr–Oct rows. Valid-denominator correction moves the post-peak minimum month in 47/1,206 cycles (3.9 %). | artifact, source | The defect bites the rise side (cloudy months) far more than the trough side. Weakens the rise anchor's robustness claim; strengthens repair-first. |
| 5 | Medium | Density bias: flip rate rises with observed months (0.8 → 5.2 %). Era means (4.0/4.6/3.3 %) hide it. | artifact | "Exact trough month barely matters" is not established; survival needs an interval-censored statement. |
| 6 | Medium | Hydropools applies none of HydroSeason's own gates: `boundary_status` provisional in 1,257/1,558 tile-years, `status` partial 1,269, `confidence` low 840. Only `trough_timing_status` and date presence are consulted. | artifact, source | Any clock change should first decide whether to honour existing gates; otherwise quality is discarded before the anchor question arises. |
| 7 | Medium | Fitzroy is one of the five HydroSeason case-study catchments (2005–2025, 30/60/90/300 m). Calibration partition behind the frozen defaults is maintained outside the repository; its membership is not recorded here. | source | Transfer validation cannot be claimed; "no constant tuned to the Fitzroy" is unverifiable without the partition manifest. |
| 8 | Medium | `start_date` is boundary + 1 month, not the previous trough; in 18 point cycles the refined boundary sits after the equivalent-minimum band, so `trough_date` (used as end-dry) and the next year's `start_date` − 1 differ. | source, artifact | Exposure span and end-dry are not keyed to one event; re-key cycles explicitly before any anchor change. |
| 9 | Medium | Audit provenance: text hash ≠ receipt hash; proposal moved under the audit. | artifact | Audit §5 partly targets superseded text; no numeric effect. |
| 10 | Low | Input repair will most likely remove the four epsilon-floor tiles from per-year detection rather than fix them: with counts, tile05's 0.1 pp amplitude has floor 100/971 = 0.103 pp, ratio 0, peak pixels 1 < 5. | rerun | Rule (c) borrowing is needed for 151 tile-years whatever the anchor; plan it in stage A, not after. |
| 11 | Low | `narrow_most_recent_recurrence` trimming the band end is plausible by code but unquantified; it applies only to `unresolved` spans in windows ≥ 12 months with two matching clusters. | source | Not verifiable from exports; request a diagnostic column before relying on it. |
| 12 | Low | Re-wet guard fired in 8 of 1,544 windows; `hy_boundary` basis in 135. | artifact | Confirms proposal; the 135 non-detectable windows are the real "no signal" set. |

## 4. The audit's five new findings: falsification attempts

**4.1 Denominator mismatch** — **agree** [source, rerun, artifact]. `extent_series` (seasons.py:24–30) divides by `n = states.shape[1]`; `prepare_monthly_extent` (_state_input.py:50–51) recomputes `100·n_water/n_valid` when counts exist, and `docs/report-columns.md:18` documents that denominator. Probe: `n_valid 50, n_water 10` → 20.0 % (not 10 %). Adding counts therefore changes values, not only guards. Distinction the audit draws is right: the exported value is a lower bound on footprint wetness under arbitrary missing pixels; the valid-denominator value is the compatible semantics, not truth under cloud. **Added quantification:** the mismatch is seasonal (Dec–Mar) and changes the post-peak minimum month in 3.9 % of cycles; so for the trough it is a second-order effect, for any rise rule it is first-order. Historical producer source: `seasons.py` and `pipeline.py` are byte-identical between producer commit `3f54c6c` and the checkout; no difference [artifact].

**4.2 Tolerance 0.0 overrides dataclass 1.0** — **agree** [source]. `analyze_catchment(measurement_tolerance_pct=0.0)` (_catchment.py:146) forwards to `assess_water_regime` (:176; that function's own default is also 0.0, _regime.py:146) and to `DynamicHydroYearConfig(measurement_tolerance_pct=…)` (:248), which `_cycle_timing_evidence` (_dynamic_year.py:698) and `refine_trough_span(measurement_tolerance_pp=…)` (:1213) consume. `run_hydroseason` passes `analysis_options` through unchanged (workflow.py:313–317); hydropools passes none (seasons.py:36–38). Probe: amplitude 0.1 pp, no counts, tolerance 0, noise 0 → floor 2.220446e-16, ratio 4.5e14, detectable. The harmonic classifier's floor (`_seasonality.py:87`, default 1.0) is a different quantity, as the audit says. Floor = epsilon in 151 tile-years across exactly four tiles (05, 13, 18, 46); 145 of the 270 Jan–Aug ends sit there.

**4.3 `pd.cut` drops 92 records** — **agree** [artifact]. Recalculated from the pinned `clock_quality.csv`: 1,545 rows, 0 NaN ratios, 80 zero ratios (all `unresolved`), 0 ratios in (0, 1). Groups: 10 < r ≤ 1e9: 913 / 59 / 33; r > 1e9: 92 / 86 / 80; all r > 10: 1,005 / 145 / 113. Excluded by tile: 46: 32, 05: 28, 13: 17, 18: 15. All 92 have floor 2.2e-16; their trough statuses are interval 37, broad 26, point 17, unresolved 12. The proposal's "no amplitude (ratio NaN)" row is 80 zeros, as the audit says.

**4.4 Endpoint cohort** — **agree** [artifact]. 132,815 rows, 26,633 groups; 523 last-observed rows with `pos_to_end ≠ 0` (1: 461, 2: 61, 4: 1). Source-style reproduction: wet share 0.42177, no-dry 0.382157, 1,055 flips. Observed-endpoint cohort: 26,110; 10,914 wet (0.418001); 9,876 no observed dry (0.378246); 1,038 flips (3.98 %). `pool_years`: 26,644 rows, 534 unobserved endpoints, 11 groups absent from `pool_months`; all 26,110 known endpoints agree. **Added:** flip rate by observed months per window (0, 2]: 0.84 %, (2, 4]: 3.67 %, (4, 6]: 4.09 %, (6, 8]: 5.20 %.

**4.5 `start_date` mapping** — **agree** [source, artifact]. `hy_start = previous["trough_month"] + 1 month` (_dynamic_year.py:732); exported as `start_date` (_report_export.py:390). Tile05 rows confirm (boundary 1988-06-01, next `start_date` 1988-07-01). First cycle uses record start − 1 month as the previous trough (:925, :1249). Partial cycles still carry `hy_start`.

## 5. The original proposal, claim by claim (current version)

| Claim | Verdict | Evidence |
| --- | --- | --- |
| hydropools exports no `n_valid`/`n_water`; HydroSeason accepts them | agree | seasons.py:24–30; `COUNT_COLUMNS` [source] |
| Floor collapses to machine epsilon without counts | agree, but confined to 4 tiles / 151 tile-years | probe; `clock_quality.csv` [rerun, artifact] |
| "Why is tolerance 0 when the dataclass says 1.0?" | answered: `analyze_catchment` default 0.0 | §4.2 [source] |
| D8 is mostly this input gap | partly agree | 145 of 270 Jan–Aug ends have epsilon floor; 152 of 270 are in tiles < 2,000 px; 84 are in tiles ≥ 3,000 px (tile 11 alone 33 %) [artifact]. Repair removes rather than fixes the four tiles (finding 10). |
| Ratio table | disagree as published | §4.3 |
| Stakes table (pool-years touched) | not verified; cohort method shares the §4.4 endpoint defect | — |
| Peak point 1,213 (78 %), 93.1 % within ±1; trough point 352, 84.8 %; end-dry 83.2 % | agree on numbers; leave-target-out median lowers trough to 81.4 %, peak unchanged (26 tiles/yr) | recomputed [artifact] |
| "Anchor on the rise and tiles agree within a month in 93 %" | disagree: unmeasured; proxies 0.83–0.88 | §6.1 [artifact] |
| y changes 4 % under no-dry rule; "exact trough month barely matters" | numbers agree; interpretation disagree | §4.4; finding 5 |
| "Within-window minimum is not observation-density biased at these window lengths" | disagree | finding 5 |
| Month after end-dry flips 33 %, nearly all dry→wet; "that is the rise" | numbers agree (23,056 compared; 6,764 dry→wet); interpretation partly agree: rewetting next month is evidence that the endpoint is near a low state, not an onset estimate | `clock_check.json` [artifact] |
| `trough_interval_end` is the last band month = month before the rise | agree as a definition; it is already used as end-dry in 1,057 windows | finding 2 |
| Two things stop hydropools using it: epsilon floor; `narrow_most_recent_recurrence` | partly agree: floor yes (4 tiles); narrowing not verifiable from exports | finding 11 |
| `start_date` is the previous trough | off by one month | §4.5 |
| Re-wet guard fired 8/1,544 | agree | `windows_all.csv` [artifact] |
| Floodplain: trough point 13 %, unresolved 19 %, trough extent 0 in 46 %, peak point 79 % | agree (13.1 / 18.8 / 46.3 / 78.5 %) | [artifact] |
| Fitzroy calibration membership unknown | agree; Fitzroy is a HydroSeason case study | finding 7 |
| Gauge first-flow referee, 70 % ±1 month, baseline end-dry + 1 | design acceptable only with the audit's conditions (§6.6) | [policy] |
| 2026 wet season clean if frozen before Jul–Dec imagery | local cache ends 2026-06 (479 months from 1986-08); non-use elsewhere not provable | §11 |

## 6. Scientific challenge

### 6.1 Peak synchrony does not establish onset synchrony

Logical point (audit): agreed. Identical March peaks are compatible with November onset in one reach and February in another. Empirical check [artifact, exploratory, unrepaired inputs, 31 tiles ≥ 3,000 px, 1,166 tile-years, pixel-weighted median per year, including and excluding the target tile]:

| Event | within ±1, incl. | within ±1, leave-target-out | ≥ 3 off | tiles/yr |
| --- | ---: | ---: | ---: | ---: |
| Peak (point only) | 0.931 | 0.931 | 0.014 | 26 |
| Trough (point only) | 0.854 | 0.814 | 0.062–0.072 | 8 |
| Cycle boundary (all) | 0.832 | 0.826 | 0.032–0.039 | 31 |
| End-dry as run | 0.832 | 0.826 | 0.033–0.039 | 31 |
| Rise: first month after boundary exceeding band level + 1 pp (valid denominator) | 0.822 | 0.815 | 0.033–0.042 | 25 |
| Rise: first month ≥ max(2× band level, +1 pp) | 0.880 | 0.880 | 0.025 | 25 |
| Rise: half-amplitude crossing | 0.926 | 0.921 | 0.013 | 25 |

The half-amplitude crossing is the next peak in disguise: its gap to the next peak has quantiles (5, 50, 95 %) of 0, 0, 2 months. The departure rules, which are what the proposal describes, are no more synchronous than the end-dry as run, and the first-departure rule starts 1–5 months after the boundary (quantiles 1, 1, 2, 3, 5). These are crude rules on uncorrected series and prove nothing about a well-designed rise estimator; they do show that synchrony is a property of the rule, not of "the rise", and that the proposal's number cannot be assumed.

Point-only selection and target inclusion: peak statistics use 26 tiles per year, trough 8; leave-target-out lowers trough agreement by 4 points and peak by none. Coverage must be reported with accuracy, as the audit says.

### 6.2 Which target, and whether a shared aggregate clock fits it

Three defensible targets, as the audit lists: minimum availability; state immediately before replenishment; continuous survival through recession. The lead's own framing (2026-10-29 handoff §3.3) asks exactly this: "driest local month … or a common date". A shared aggregate clock is a convention for comparability and exposure accounting; it is appropriate for the second target and for X, not for the first (circular at the pool) and not sufficient for the third (needs a trajectory). Dependence: the same pixels choose the aggregate endpoint, define cores (era-dry years via X at that endpoint), and score y. That dependence exists under any anchor; the rise anchor does not remove it and adds dependence on the following wet season's observations.

### 6.3 The 4 % versus 19.4 %

Four percent is the wet-at-endpoint share that has an observed dry month somewhere in the window; 19.4 % is the share of pool-years whose state differs one month earlier (mostly dry→wet, 4,301 of 4,889). They measure different things and the second already shows that the endpoint month matters. The density gradient (finding 5) shows the 4 % is a floor set by sampling, not a ceiling on hydrological change. Era comparisons cannot separate density from sensors, clouds, interval length and pool selection; the audit's thinning design is the right test.

### 6.4 Can a sustained rise be defined without the trough

Not without a reference low level. HydroSeason's own refinement needs both adjacent peaks resolved (`refine_trough_span` returns `missing_or_unresolved_peak` otherwise; 389 of 1,640 cycles in the manifests) and sets `recovery_start = boundary + 1`. So the existing "sustained recovery" is defined from the low state and confirmed by the next peak, with the latency the proposal lists as a cost. The proposal's current wording ("judged by the size of the departure against the floor") still needs: which low level when the band is broad (median span 4 months for `broad`, 7 for `unresolved`); persistence horizon (one month above the band is a pulse; `n_rewetting_pulses` exists for this); gaps (interval, not a date); scale (the floor is an annual-extrema quantity, not a local change tolerance; and it is epsilon on four tiles); years with no rise or two wet seasons; composite month stamps; confirmation lag. Frozen annual-extrema calibration (3.0×, 5 pixels) does not transfer to a local onset step without its own calibration.

### 6.5 "Refuges fall" is not guaranteed

On a fixed, fully observed cohort a within-window minimum lowers y by construction. A pre-rise endpoint has no such property: moving the endpoint later samples a wetter-or-drier month depending on dry-season storms (9.2 % of pool-years show dry then wet inside the window), cloud censoring (more missing endpoints in the wet-season tail), and rebuilt cores and era-dry years. Counterexample: a pool dry at the current band end that rewets in a dry-season pulse the month before the rise scores wet under the new endpoint. Direction is a hypothesis.

### 6.6 First flow as referee

Fair for one target only: reconnection at a gauge-connected reach. Not a referee for tile-wide extent rise or pool survival. The local files are BOM semicolon-delimited daily series with `+10:00` stamps, empty values for missing and a quality-code column [artifact]; any protocol must define day boundary, quality eligibility, zero-spell rule (the proposal's Q ≤ 0.01 m³/s for ≥ 14 days is not in hydropools source; it lives elsewhere), multiple spells, allowable lag, gauge-to-tile mapping, and must never read missing discharge as zero. A ±1-month symmetric score hides late estimates, which are the costly error (the pre-rise month then already contains rewetting). Baseline to beat: current end-dry + 1 month on the same gauge-years, with abstention and coverage reported, blocks by hydrological year across connected gauges, and margins frozen first (section 10).

### 6.7 Safeguards and product boundary

The recommendation can preserve the seasonal conjunction and annual-condition gates: a consumer field (band end, departure status) need not touch regime, baselines or `start_date`. The proposal's hydropools list (delete basis chain, re-wet guard, D8; start drying and extents walks from the pre-rise month) is too broad: the drying and extents walks run backward from end-dry to the peak and must keep the peak as origin; the guard and chain can only be retired after the replacement is measured.

### 6.8 What transfers across channel, floodplain and TSFill

Transfer event semantics, provenance fields, interval representation and abstention rules. Do not transfer dates: the floodplain's trough extent is 0 in 46 % of tile-years, so a zero-floor low state is a legitimate dry interval there; TSFill's climatological bins are strata, not per-year events. Trough recurrence results (section 7) transfer as a method property; the Fitzroy numbers do not.

## 7. What the falsification results establish, undermine, and leave open

Inspected artifacts, counts reproduced from the pinned CSVs [artifact]: drift 4/100; power 99/100; uniform null 7/200 trough, 17/200 peak; 1,000-seed null 51 trough, 62 peak, 2 seasonal; stable/30 y/no floods/no gaps: trough 30/30, peak 21/30, seasonal 21; stable_sharp variant peak 1/30; stable/12 y/floods: harmonic accepted 12/30, wrong month 5, trough 29/30; stable/7 y/floods/dry20: trough 15/30.

**Establish** (synthetic, fully observed, no classification error, no counts): the released trough Kuiper test is calibrated near alpha (4 %, 3.5 %, 5.1 %) and powerful on a recurring trough even under episodic floods; the harmonic route both refuses and mis-accepts the same records; the conjunction can classify "seasonal" for the wrong reason on long records with broad near-tied peaks; dry-season gaps on short records cost trough power. These are properties of the regime test, and they contradict the proposal's blanket characterisation of the trough as "the weakest, least synchronous event": as a recurring calendar event, the trough is the better-identified of the two in these constructions.

**Undermine**: nothing about the rise, because no construction contains a rise rule or a sustained onset; and nothing about per-year endpoint accuracy, which the tests do not measure. They also do not touch the proposal's actual problem cases (zero-heavy tiny channels, epsilon floor, cloud-structured missingness).

**Leave open**: whether Fitzroy windows have recurrent troughs (step 2, frozen windows, not run; `dev/fixtures/frozen_windows` does not exist); whether the 21/30 broad-peak mechanism operates on 38-year Fitzroy records, which matters because all 41 tiles were classified seasonal, including tile05 (peak p = 0.001, trough p = 0.001) whose series is zero in most months and is "detectable" only because of the epsilon floor; whether counts change regime decisions on real data (the counts variant changed 6 of 360 synthetic classifications, but it rounds pixels on a 1,000-pixel footprint and models no cloud); and the 6.2 % peak null rate (1.7 standard errors above 5 %; not a finding, worth one more pre-registered run if the peak test is to gate anything).

**No current test adjudicates the rise proposal.** Keep both workstreams. Rank recovery is a unit change and must not be compared with percentage-point floors.

## 8. Judgement on the two recommendations

**Original proposal** — partly agree on diagnosis, disagree on the move. Agree: counts must be exported; an unresolved local clock must not become a confident date through a silent chain; end-dry errors propagate into identity, X, y, refuges, drying and floodplain lags; the trough point and the band end are different quantities worth separate status. Disagree: the switch to "the rise" is unmeasured and, on its own data, the band end already is the end-dry; the synchrony claim is the peak's; the proposed deletions (basis chain, re-wet guard, D8) and walk changes precede any measurement; "refuges fall" is asserted; re-validation would be post hoc and the proposal says so. The censoring choice for failed wet seasons is a legitimate target decision for the lead, not an inference from data.

**Audit** — agree on every numerical correction, on the four non-sequiturs it names, on target-before-clock, and on the staged sequence. Partly agree on §5: some critique targets superseded wording, though each point still applies. Disagree with two omissions: it did not report that the band end is already the operational end-dry for 68 % of windows and that `recovery_start_month`/`low_state_end` exist internally, which changes what the HydroSeason ask is; and its stage A should say up front that repair will most likely route the four epsilon tiles out of per-year detection, so rule (c) is needed regardless of anchor. Its Cavallo et al. citation supports the observable distinction only and was not independently checked here.

## 9. Target definition and minimum contract (no implementation)

Define, in the ledger, one of:

- **T1 minimum availability**: lowest supported extent in the post-peak window; may be an interval; per pool it is circular, so it is an aggregate quantity only.
- **T2 pre-replenishment state**: occupancy in the last month of the supported low state, i.e. the month before `rise_date`; carries interval uncertainty `[L−1, U−1]` when the rise is an interval `[L, U]`.
- **T3 continuous survival**: no supported drying between recession start and replenishment; interval-censored; separate rewetting events.

If T2 is chosen, the minimum HydroSeason contract is additive and versioned: `low_state_end` (date; equals today's band end), `rise_date` (first month after it), `rise_timing_status ∈ {point, interval, unresolved, no_rise, censored_by_gap}`, `rise_departure_pp` with the floor it was judged against, `rise_confirmation ∈ {next_peak_resolved, provisional}` with confirmation month, observation support at both months (`n_valid`, `invalid_pct`), the cycle key, and method identity. `start_date` keeps its meaning. The hydropools contract: one explicit endpoint policy with `endpoint_source ∈ {local, donor_median, catchment}`, donor IDs and spread when borrowed, `endpoint_status`, and no silent replacement of an unknown local date by a neighbour's. Statistical products refit with the new endpoint and report both cohorts (common observable and full).

## 10. Smallest staged experiment, margins frozen before any new reference inspection

**Stage 0 — measure the premise (read-only, days).** Freeze one rise rule R on existing channel series (valid-denominator percentages recomputed from the exported CSVs, which is exact: `extent/(1 − invalid/100)`), with abstention when the month after the band end is unobserved. Compute per year, over tiles ≥ 3,000 px, the share within ±1 month of the leave-target-out pixel-weighted median, and the same for end-dry as run. **Frozen margin:** R is worth carrying forward only if its agreement is ≥ 0.90 and exceeds end-dry as run by ≥ 0.05 at coverage ≥ 0.90 of tile-years. Otherwise the synchrony motivation is falsified for this data and the thread reduces to stages A and C. The crude variants above give 0.82–0.88; this stage is likely decisive against.

**Stage A — input repair attribution (same tile-years, three versions).** Existing export; valid-denominator percentages; the same with counts. Report regime, route, detectable years, floor, trough status, band end and `hy_boundary` count per tile, and the pool-years that lose a local clock. **Expected and to be recorded:** tiles 05, 13, 18 and probably 46 leave per-year detection (finding 10). **Decision:** if Jan–Aug ends outside those tiles fall below 8 % of remaining tile-years, the anchor is an optional target change; if tile 11 and similar big-tile early troughs persist, they need a gauge or imagery referee, not a threshold.

**Stage B — independent timing comparison (only if stage 0 passes or the lead chooses T2 regardless).** Gauge protocol per §6.6, written and hashed before any discharge file is opened for this purpose. Compare corrected end-dry + 1, fixed climatological onset, and R on paired gauge-years. **Frozen margins:** R must beat the baseline's ±1-month agreement by ≥ 10 points with a late-estimate rate (R after first-flow month) no higher than the baseline's, pooled over gauges and reported per gauge, with hydrological-year blocks. Report all-year-flow and no-rise years separately. The 70 % bar is reported, not used to decide.

**Stage C — consequences.** First on the fixed 709 cores and the common observable cohort: y, X, refuge flips, drying intervals under current endpoint, corrected-input endpoint, pre-rise endpoint and trajectory survival. Then rebuild cores and era-dry years and compare births, losses, splits, inherited IDs. Treat all 2019 Planet and prior leave-year-out results as development evidence once used to choose a policy.

## 11. Evidence and provenance gaps

- Calibration partition membership: `_scientific_defaults.py` says values are frozen from partitions maintained outside the repository; `docs/method-policy-v0.2.0-validation.json` gives denominators (1,056 synthetic cases, 12,000 pipeline cases, 561 CAMELS-AUS catchments, 191 sealed) but names no catchments. Fitzroy is a HydroSeason case study (2005–2025). Request the partition manifest; until then "no constant tuned to the Fitzroy" is unverified.
- 2026 imagery: the local WOfS cache holds 479 months from 1986-08 to 2026-06; hydropools inputs end 2026-06-30; HydroSeason inputs end 2026-06-01 [artifact]. This is consistent with Jul–Oct 2026 being unexamined locally. It does not prove non-use through other channels (DEA services, the TSFill repository). Treat Jul–Dec 2026 as a holdout only with an access statement and a hashed, frozen rule.
- The proposal's scratch scripts and CSV are the only record of its tables; the proposal file itself has no version history. Archive the three versions with hashes.
- `windows_all.csv` (1,544 windows) lives in a session scratchpad; the re-wet guard count and basis distribution depend on it.
- Frozen external windows (`dev/fixtures/frozen_windows`) do not exist; verdict step 2 remains unrun.
- Hydropools' `zero_flow_days` rule is not in its source tree; the referee rule must be written into the protocol, not cited.

## 12. Reproduction

Run from the HydroSeason root with `.venv/Scripts/python.exe`; external paths read-only. Scratch copies used here are in the session scratchpad; the decisive fragments:

```python
import pandas as pd, numpy as np
cq = pd.read_csv(r"<clock_quality.csv>")               # receipt-pinned scratch CSV
r = cq.amplitude_to_floor_ratio
for m in [(r > 10) & (r <= 1e9), r > 1e9, r > 10]:
    print(m.sum(), cq.jan_aug[m].sum(), (cq.absdev[m] >= 3).sum())   # 913 59 33 / 92 86 80 / 1005 145 113

pm = pd.read_csv("D:/RLH/5.6/repos/hydropools/outputs/rerun/fitzroy/pool_months.csv").sort_values(["core", "hy", "t"])
g = pm.groupby(["core", "hy"]); anyd = g.state.apply(lambda s: s.eq("dry").any())
a = pm[pm.pos_to_end.eq(0)].join(anyd.rename("any_dry"), on=["core", "hy"]).join(g.size().rename("n"), on=["core", "hy"])
print(len(a), a.state.eq("wet").sum(), (~a.any_dry).sum(), (a.state.eq("wet") & a.any_dry).sum())   # 26110 10914 9876 1038
print(a.groupby(pd.cut(a.n, [0, 2, 4, 6, 8, 20]), observed=True).apply(lambda s: (s.state.eq("wet") & s.any_dry).mean()))

w = pd.read_csv(r"<windows_all.csv>"); print(w.end_basis.value_counts())   # interval_end(*) 1057, point 344, hy_boundary 135, point+rewet_guard 8
```

Synchrony and onset proxies: glob `work/rerun/fitzroy/hydroseason/*/*_hydro_years.csv` and the matching `channel_monthly_extent.csv`; month index `(year − 1987)·12 + month − 1`; big tiles `px ≥ 3000` from `clock_quality.csv`; for each tile-year with a boundary and a next-cycle point peak, R(+1 pp) = first month after the boundary with `extent/(1 − invalid/100)` > boundary value + 1; half-amplitude = first month above boundary value + 0.5·(segment max − boundary value); pixel-weighted median per year with and without the target tile. Manifest aggregation: `pass2_applied_count` 728 of 1,640, reason codes as listed in finding 2.

Floor probe: `annual_detectability` with `measurement_tolerance_pp=0.0, noise_pp=0.0`, no counts, amplitude 0.1 → floor `2.220446049250313e-16`; with `n_valid=971` → floor 0.10299, ratio 0, `peak_n_water` 1.
