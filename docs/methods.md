# Methods Reference

This document provides the authoritative scientific and algorithmic reference for `hydroseason-v0.3.0`, the sole frozen runtime method shipped with HydroSeason. It replaces `hydroseason-v0.2.0`; [Changes from hydroseason-v0.2.0](#changes-from-hydroseason-v020) lists what differs.

## Method Identity & Cryptographic Fingerprints

HydroSeason freezes a single authoritative method policy. There are no competing, alternate, or unversioned runtime method policies.

- **Method Identifier**: `hydroseason-v0.3.0`
- **Method Payload SHA-256 Fingerprint**: `07f1eaa173372e2544c46f794426917539a774756a64ccdac400ea0a747171cb`
- **Method Manifest SHA-256 Digest**: `93a60215a83a2f5ba88a54316157346e4da7c7ccdcd980d14ce4be34bd60f7af`
- **Run Manifest Schema**: `hydroseason-run-manifest-v1`

Every execution writes a cryptographic run manifest (`<stem>_manifest.json`) capturing the exact method payload fingerprint, software versions, input data digests, configuration parameters, and output artifacts.

The manifest (`docs/method-policy-v0.3.0.json`) pins the event thresholds, the seasonality test, the recurrence policy, trough refinement and, since `hydroseason-v0.3.0`, the timing-identifiability gates, the condition-baseline rule, the trough-label rule, the dry-run rule, the trough-search anchor and the end-of-dry label rule, and the trough-search, boundary-selection and peak-quality settings. A change to any of them changes the fingerprint.

---

## Architectural Principles & Process Independence

### Surface-Water Focus
HydroSeason detects hydrological regimes and hydrological-year boundaries from satellite-derived surface-water extent (Digital Earth Australia Water Observations, 30-m resolution). It quantifies the percentage of historically wet support that is wet in each month, without imposing artificial calendar boundaries or presuming periodicity where none exists.

### Rainfall and Streamflow Independence
Rainfall (e.g., SILO gridded climate data) and streamflow (e.g., CAMELS-AUS gauge discharge) are strictly ancillary contextual series. They are **completely independent** from:
- Catchment surface-water mask definition,
- Monthly extent and quality compositing,
- Seasonality classification and regime routing,
- Peak selection and annual boundary placement.

Hydrometeorological variables provide process context in reporting; they never serve as training targets, gating criteria, or boundary constraints.

---

## Pipeline Components

### 1. Preflight Screening & Observation Quality
- **Screening**: Pixels with multi-year recurrent water frequency $\ge 0.10$ must form a 4-connected cluster covering at least $3,600\,\text{m}^2$ (four 30-m pixels) to warrant analysis.
- **Quality Annotation**: Months with invalid observation coverage $I_t > 20\%$ are flagged. Partially observed finite months remain candidate-usable for first-pass analysis, but their quality flags propagate into downstream decisions.
- **Record Sufficiency**: A calendar year requires at least 9 candidate-usable monthly observations to qualify. A record must contain at least 5 qualifying years to proceed.

### 2. Recurrence Conjunction & Five-Detectable-Year Guard
Seasonality is defined strictly as the recurrence of annual timing, not merely large within-year amplitude:
- **Detrending**: A centred $2 \times 12$ moving average estimates the long-term trend-cycle. Internal missing months are linearly interpolated for trend estimation only; interpolated months contribute no timing evidence.
- **Detectability Floor**: Evaluated on raw extent. A year is detectable when its peak-to-trough range is at least $3 \times$ the floor (the maximum of measurement tolerance, robust scatter, extrema pixel resolution, and machine precision). If wet pixel counts are present, the annual peak requires at least 5 wet pixels; if counts are absent, extent thresholds alone govern detectability.
- **Five-Detectable-Year Guard**: The record must contain at least **5 detectable years**. If a record has fewer than 5 detectable years, timing recurrence cannot be tested, and the record is routed to aseasonal.
- **Equivalent-Month Sets**: For detectable years with at least 9 detrended months, peak and trough timing are represented as complete sets of equivalent calendar months (within tolerance $\delta = \text{floor} + \text{trend\_range}$). Broad equivalent-month sets remain eligible evidence, sharing unit annual weight equally.
- **Circular Kuiper Tests**: Timing angles $\theta = 2\pi(m-1)/12$ are evaluated independently for peaks and troughs using weighted circular Kuiper uniformity tests (Monte Carlo null with 999 rotations, reproducible seed 0).
- **Conjunction Rule**: A record is classified as seasonal if and only if **both** peak ($p < 0.05$) and trough ($p < 0.05$) tests reject the discrete-uniform null. Failure of either test classifies the record as aseasonal.

### 3. Seven-Cycle Annualization Guard
Records classified as seasonal enter annual boundary detection. However, before per-year dynamic boundaries can be published, the assembled cycles must satisfy a strict **seven-cycle annualization guard**:
- At least 7 informative peak cycles and at least 7 informative trough cycles must be resolved.
- If fewer than 7 cycles are resolved, dynamic annual boundaries are withheld, and the catchment is routed to event and spell analysis. This prevents short or fragmented seasonal signals from producing unrepresentative annual boundaries.

### 4. Direct-Profile Trough Refinement
Annual boundaries mark the final interior month of the supported low state before sustained hydrological recovery:
- **Pass 1 (Search)**: Searches 7-month windows (expandable to 9 months) centred on the anchor month (the end of the typical low, below), resolving approximately 12-month cycle sequences via dynamic programming.
- **Pass 2 (Direct-Profile Refinement)**: Refines boundaries using weighted Huber loss ($k = 1.345$) across candidate reference levels within 2 noise scales of the preliminary valley at quarter-scale increments.
- **Relative Margin**: $\delta_{\mathrm{rel}} = 0.05$. Candidate low-state months maintaining profile loss within this margin define the supported plateau.
- **Profile Support Interval**: The interval of candidate boundary locations maintaining profile Huber loss within the 5% relative margin. This is a **robust-loss support interval**, not a nominal confidence interval or Gaussian probability.
- **Sensitivity Scenarios**: Perturbs uncertain observations across dry-bound, wet-bound, and joint missingness scenarios, as well as bracketed peak shifts. Refinement stands only when every evaluable scenario returns a boundary, the scenarios share at least one candidate month, and their combined candidate months are contiguous and at most five months apart from first to last (up to six calendar months); otherwise it abstains as `unresolved`.
- **Reason-Coded Abstention**: Where sensitivity scenarios disagree or evidence is insufficient, refinement abstains with typed reason codes (`BoundaryNotSupported`), preserving the robust Pass 1 boundary rather than guessing.

### 5. Timing Labels
- Each cycle's peak and trough carry a timing label, judged against the cycle's detectability floor: `point` when one month stands out, `interval` for up to 3 months (at most 2 apart), `broad` (troughs) for up to 6 (at most 5 apart), and `unresolved` otherwise. The aggregate `timing_status` is the weaker of the two. A label says how distinct the extremum is, not how close its month is to the true one.
- **The trough label covers the boundary** (rule `covers_trough_boundary`, version 1, new in `hydroseason-v0.3.0`). The boundary is the lowest clear month in its search window, while the label compares every usable month from the peak to the boundary, cloudy months included. When a dated label's interval misses the boundary month, it is widened to cover both and graded by its width. This runs after every boundary is final, so boundaries, dates, peaks and cycle status do not change.

### 5a. Where the Dry Season Ends
- Each cycle reports the **dry run** of its trough boundary (rule `report_dry_run`, version 1, new in `hydroseason-v0.3.0`): `dry_run_start_month`, `dry_run_end_month`, `rewetting_month`, `dry_run_months` and `dry_end_status`. Starting at the boundary, with level L its extent and tolerance ε its own boundary tolerance (at most a tenth of the amplitude), the run takes in the observed months on either side whose extent is at most L + ε, continuing past the search window and over unobserved months, until the first observed month above L + ε. A month is observed when its `quality_state` is `usable`; cloudier months neither extend nor end the run. The run cannot pass a cloudy reported peak of the next cycle. A mid-dry pulse of water above the tolerance ends it. This borrows, by analogy, the streamflow convention that a zero-flow period ends when flow resumes (Snelder et al., 2013, https://doi.org/10.5194/hess-17-2685-2013; Tramblay et al., 2021, https://doi.org/10.1080/02626667.2020.1849708); HydroSeason measures surface-water extent, not flow, and the dry run is a period of low extent, not of zero flow.
- `dry_run_end_month` is the end of the dry season; `rewetting_month` is the first month above it. `dry_end_status` is `interval` when a re-wetting month was observed (the end lies between the run end and the month before re-wetting) and `censored` when the record ends dry (`unavailable` when the cycle has no boundary). It is never `point`: in a test on records with known answers ("known truth": synthetic records with real observation gaps, and seasons injected into real flat records), a run end followed at once by re-wetting was more than a month from the true end in 24–43% of cases, far above the 5% allowed for `point` labels.
- **The year boundary is the end of the dry season** (section 4's definition). Two rules, new in `hydroseason-v0.3.0`, make the boundary reach it on flat-bottomed records, where every dry month ties near zero:
  - **The search anchor is the end of the typical low** (rule `end_of_climatological_low`, version 1). Every year's search is centred on one month. It starts from the month of lowest mean monthly extent and follows the next months while their mean stays within a tenth of the climatological range of the minimum; the anchor is the last of them. On a V-shaped season that is the lowest month or the one after; on an ephemeral channel it is the end of the dry season rather than its first dry month. `analyze_catchment` and `run_hydroseason` apply this anchor; a month passed to `DynamicHydroYearConfig(expected_trough_month=...)` for a direct `analyze_hydrological_state` call is used as given.
  - **A boundary at the end of a dry low is dated by where the low ends** (rule `zero_low_end_status`, version 2). When the boundary is the last month of its dry run, the run is longer than a month and sits at zero extent (at or below the larger of the measurement tolerance and one pixel), water was seen to return, and the trough label is `broad` or `unresolved` because every dry month ties, the label runs from the run end to the month before the next peak and is graded by that width (`interval` or `broad`, never `point`; wider leaves the label as it was). Those rows read `trough_label_basis` = `end_of_dry_run`.
- In a known-truth test of the boundary at the end of the low, the anchor raised the share of ephemeral dry-season ends dated within a month by a boundary from 0.070 to 0.109 (synthetic records) and 0.085 to 0.103 (real backgrounds), or from 0.18 to 0.27 and 0.26 to 0.32 among records with per-year results, with smooth and pulse seasons no worse. In a post-hoc check on the same records (the label rule was revised after that test), the end-of-dry labels held the true end within a month about three times in four. The level stays low: most ephemeral records are routed to event characterisation, and a noisy dry month just above the tolerance can end a run early. On 40 grid tiles over the Fitzroy catchment (WA), the year boundary ends three or more months before the dry season in 104, of about 1,600 tile-years, against 251 under `hydroseason-v0.2.0`.
- When the boundary and `dry_run_end_month` still differ, the refinement did not reach the end of the low (for example a cloudy or noisy year); `dry_run_end_month` is then the better date for the end of the dry season.

### 6. Annual Condition Baseline
- A cycle anchors the annual condition baseline when it is `complete`, its boundary is `confirmed`, its peak is not `anomalous`, and its aggregate timing is dated: `point`, `interval` or `broad`. Under `hydroseason-v0.2.0` only `point` cycles could.
- A record needs at least 5 anchoring cycles. Each cycle's peak extent (recharge) and trough extent (refuge) are ranked against them by empirical percentile: `low` at or below the 20th, `high` at or above the 80th.

### 7. Event & Low-Extent Spell Routing
Catchments routed away from per-year boundaries (aseasonal or insufficient cycles) undergo event characterisation:
- **Wet Events**: Open when extent exceeds the record median plus 3 robust AR(1)-corrected noise scales, remaining open above median plus 1 scale.
- **Low-Extent Spells**: Continuous runs of at least 2 months at or below the record median minus 1 scale.

---

## Validation Stages & Denominators

`hydroseason-v0.2.0` was verified across three formal validation stages whose exact denominators match the frozen evidence receipts (`docs/evidence-receipts.json`). They cover every part of the method that `hydroseason-v0.3.0` keeps unchanged:

| Validation Stage | Benchmark Denominator | Status | Verdict SHA-256 Digest |
| :--- | :--- | :--- | :--- |
| `multiscale_synthetic` | 1056 cases | Passed | `b467c6c26eadbee60dc38d1117b24ab49f65c3d095c5c0ed817952512794a7e9` |
| `full_pipeline_synthetic` | 12000 cases | Passed | `18bf46bb42187cb50a92f787a62191b588fca36b214073901666176a6513c5df` |
| `camels_aus_validation` | 561 catchments | Passed | `9e4f669a8f3250475c9167689b661d8d860db922514ac4c0ae2cd8156ff93f35` |

### Validation Details
1. **Development Evidence**:
   - The initial 84-cycle manual expert review of boundary placements and candidate behaviors served strictly as exploratory development evidence.
   - Five protected benchmark catchments were verified: Daly, Fitzroy, and Gilbert remain seasonal/per-year; Lachlan and Moonie remain aseasonal/event-routed.
2. **Synthetic Held-Out Matrix (`multiscale_synthetic`)**:
   - 1,056 synthetic matrix cases evaluating boundary stability, multi-frequency components, and scale transitions.
3. **Full Pipeline Synthetic Suite (`full_pipeline_synthetic`)**:
   - 12,000 end-to-end synthetic cases testing the complete pipeline across 18 synthetic families (series lengths: 7, 15, and 30 years).
   - Note: The 54,000-record synthetic experiment validates the seasonality gate (omnibus Kuiper recurrence under noise and distortion), not trough boundary accuracy.
4. **CAMELS-AUS Blinded Holdout (`camels_aus_validation`)**:
   - 561 total Australian catchments spanning tropical, temperate, arid, and Mediterranean climates.
   - 370 open catchments used for empirical distribution baseline review.
   - 191 sealed holdout catchments evaluated under blinded pre-registration (digest: `0761d4ca9eab0265c53c947ed0b0563e98a10bf0ec3b13aa95049b5e3366d77d`).
   - Limit: CAMELS-AUS catchments are mostly upper catchments with little surface water, so they say little about lowland channels and wetlands. The `hydroseason-v0.3.0` changes were tested instead on known-truth records (synthetic records with real observation gaps, and seasons injected into real flat records) and on real records: 319 national DEA WOfS windows (about 15 km a side), 1,278 subbasins and grid tiles, 40 grid tiles over the Fitzroy catchment (WA) and the five case-study catchments.

## Changes from hydroseason-v0.2.0

`hydroseason-v0.3.0` makes five changes. Changes 1 to 4 compute every boundary, date, peak, route and cycle status as in `hydroseason-v0.2.0`; change 5 moves boundaries on records with a flat low.

1. **The fingerprint covers the timing, baseline and dry-season label rules.** The timing-identifiability gates, the condition-baseline rule and the trough-label rule are now in the manifest, so changing any of them changes the fingerprint. Under `hydroseason-v0.2.0` they were fixed in code but missing from the manifest. Nothing computed changes. The new rules of changes 4 and 5 are in the manifest too.
2. **The trough timing label covers the trough boundary** (section 5). A trough label could single out a cloudy month before the boundary and read `point` for a month other than the reported `trough_date`. The label is now widened to cover the boundary and graded by its width. This changes `trough_timing_status`, `trough_interval_start`, `trough_interval_end` and `timing_status` on the cycles affected; a trough that loses `point` also loses its single-month `trough_date` in the report. Monthly phases follow the cycle's aggregate timing as before, so in a year whose `timing_status` changes the monthly `phase_status` changes with it (for example `provisional` becomes `interval_boundary`), and a year whose timing becomes `unresolved` has no rising or receding months (`phase` is `unspecified`, `phase_status` is `unresolved_cycle`). The report draws that year's trough marker as an interval. Measured on real records under `hydroseason-v0.2.0`, about 10% of `point` troughs on small areas (about 59–236 km²) and about 3% on subbasins and tiles were affected, and none on whole catchments. This is a consistency fix, not an accuracy fix: on records with known answers, `point` troughs are more than a month from the true month about as often as before (23–30%).
3. **Any dated cycle anchors the condition baseline** (section 6). Only `point` cycles could before, which left most areas without a baseline. This changes `baseline_eligible`, `baseline_n`, the peak and trough percentiles and the condition labels. On real records about ten times as many areas get a baseline. On records with known answers the larger baseline does not make labels worse on the cycles both rules label, and the labels it adds beat chance, though only fairly (kappa about 0.35 for refuge, 0.16 to 0.28 for recharge). On real records, refuge labels in the newly labelled areas repeat less well between pixel halves (kappa 0.41 against 0.51).

4. **Each cycle reports where its dry season ends** (section 5a). Five columns are added: `dry_run_start_month`, `dry_run_end_month`, `rewetting_month`, `dry_run_months` and `dry_end_status` (in the hydro-years CSV, `dry_run_start_date`, `dry_run_end_date`, `rewetting_date`, `dry_run_months` and `dry_end_status`). No existing column changes.
5. **The year boundary reaches the end of the dry season on flat lows** (section 5a): the search anchor is the end of the typical low, and a boundary at the end of a dry low is dated by where the low ends (`analysis.hydro_years` gains `trough_label_basis`). Boundaries move later where the typical low is flat, and with them year start and end, peaks where a cycle's window changes, trough labels, monthly phases and baselines. On real records 69% (quarters, about 59 km² each, of the national DEA WOfS test windows) to 100% (whole catchments) of boundaries are unchanged; the share of boundaries on which two halves of a test window's pixels agree within a month rises from 0.734 to 0.767, and 38 of 4,468 areas change route. On the five case studies only Fitzroy at 300 m changes (4 of 21 boundaries).
6. **The fingerprint also covers the trough search, boundary selection, peak quality and the trough-refinement grid.** The search radii, minimum usable months and candidates, the boundary-selection thresholds, the peak-quality rule and the refinement level grid are now in the manifest. Their values are unchanged, so nothing computed changes; the fingerprint moved from `59756dfe…` to `07f1eaa1…`, and the evidence below ran under `59756dfe…`.

**Comparing outputs across versions.** Compare `hydroseason-v0.2.0` and `hydroseason-v0.3.0` outputs only on the columns that did not change, and tell them apart by `method_policy_id` or the fingerprint.

**Evidence** (archived in the repository at the v0.3.0 tag, [`docs/handoff/`](https://github.com/tayerthiaggo/hydroseason/tree/v0.3.0/docs/handoff), not part of the published docs): the proposal and decisions, `2026-11-04-v0.3.0-proposal.md`; the known-truth test of condition labels, `2026-11-04-b2-refuge-labels-results.md`; the real-record measurement, `2026-11-03-real-record-impact-results.md`; the baseline follow-up, `2026-11-03-l1-followups-results.md`; the second known-truth test of timing labels, whose exploratory findings found the label/date mismatch, `2026-11-03-l2-r1-results.md`; and, for the dry run, the known-truth test of where the dry season ends, `2026-11-05-de1-dry-run-end-results.md`, and its implementation checks, `2026-11-06-dry-run-end-implementation.md`; for the boundary at the end of the low, its known-truth test and the post-hoc check of the revised label, `2026-11-08-de2-end-of-low-results.md`, and its implementation checks, `2026-11-08-de2-implementation-checks.md`.
