# Methods Reference

This document provides the authoritative scientific and algorithmic reference for `hydroseason-v0.2.0`, the sole frozen runtime method shipped with HydroSeason.

## Method Identity & Cryptographic Fingerprints

HydroSeason v0.2.0 freezes a single authoritative method policy. There are no competing, alternate, or unversioned runtime method policies.

- **Method Identifier**: `hydroseason-v0.2.0`
- **Method Payload SHA-256 Fingerprint**: `ac32ad6bcce4c30f6406bb5b4f2e205a02d56a045448706fe7d9e5f086aa4080`
- **Method Manifest SHA-256 Digest**: `b0f294c644409d5acbf03f268696d1c684bdaec3b5147213c91dfd853f009384`
- **Run Manifest Schema**: `hydroseason-run-manifest-v1`

Every execution writes a cryptographic run manifest (`<stem>_manifest.json`) capturing the exact method payload fingerprint, software versions, input data digests, configuration parameters, and output artifacts.

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
- **Pass 1 (Search)**: Searches 7-month windows (expandable to 9 months) centred on the climatic low month, resolving approximately 12-month cycle sequences via dynamic programming.
- **Pass 2 (Direct-Profile Refinement)**: Refines boundaries using weighted Huber loss ($k = 1.345$) across candidate reference levels within 2 noise scales of the preliminary valley at quarter-scale increments.
- **Relative Margin**: $\delta_{\mathrm{rel}} = 0.05$. Candidate low-state months maintaining profile loss within this margin define the supported plateau.
- **Profile Support Interval**: The interval of candidate boundary locations maintaining profile Huber loss within the 5% relative margin. This is a **robust-loss support interval**, not a nominal confidence interval or Gaussian probability.
- **Sensitivity Scenarios**: Perturbs uncertain observations across dry-bound, wet-bound, and joint missingness scenarios, as well as bracketed peak shifts. Overlapping scenarios within a contiguous 5-month window are required for point boundaries.
- **Reason-Coded Abstention**: Where sensitivity scenarios disagree or evidence is insufficient, refinement abstains with typed reason codes (`BoundaryNotSupported`), preserving the robust Pass 1 boundary rather than guessing.

### 5. Event & Low-Extent Spell Routing
Catchments routed away from per-year boundaries (aseasonal or insufficient cycles) undergo event characterisation:
- **Wet Events**: Open when extent exceeds the record median plus 3 robust AR(1)-corrected noise scales, remaining open above median plus 1 scale.
- **Low-Extent Spells**: Continuous runs of at least 2 months at or below the record median minus 1 scale.

---

## Validation Stages & Denominators

HydroSeason v0.2.0 was verified across three formal validation stages whose exact denominators match the frozen evidence receipts (`docs/evidence-receipts.json`):

| Validation Stage | Benchmark Denominator | Status | Verdict SHA-256 Digest |
| :--- | :--- | :--- | :--- |
| `multiscale_synthetic` | 1000 cases | Passed | `b467c6c26eadbee60dc38d1117b24ab49f65c3d095c5c0ed817952512794a7e9` |
| `full_pipeline_synthetic` | 12000 cases | Passed | `18bf46bb42187cb50a92f787a62191b588fca36b214073901666176a6513c5df` |
| `camels_aus_validation` | 561 catchments | Passed | `9e4f669a8f3250475c9167689b661d8d860db922514ac4c0ae2cd8156ff93f35` |

### Validation Details
1. **Development Evidence**:
   - The initial 84-cycle manual expert review of boundary placements and candidate behaviors served strictly as exploratory development evidence.
   - Five protected benchmark catchments were verified: Daly, Fitzroy, and Gilbert remain seasonal/per-year; Lachlan and Moonie remain aseasonal/event-routed.
2. **Synthetic Held-Out Matrix (`multiscale_synthetic`)**:
   - 1,000 synthetic matrix cases evaluating boundary stability, multi-frequency components, and scale transitions.
3. **Full Pipeline Synthetic Suite (`full_pipeline_synthetic`)**:
   - 12,000 end-to-end synthetic cases testing the complete pipeline across 18 synthetic families (series lengths: 7, 15, and 30 years).
   - Note: The 54,000-record synthetic experiment validates the seasonality gate (omnibus Kuiper recurrence under noise and distortion), not trough boundary accuracy.
4. **CAMELS-AUS Blinded Holdout (`camels_aus_validation`)**:
   - 561 total Australian catchments spanning tropical, temperate, arid, and Mediterranean climates.
   - 370 open catchments used for empirical distribution baseline review.
   - 191 sealed holdout catchments evaluated under blinded pre-registration (digest: `0761d4ca9eab0265c53c947ed0b0563e98a10bf0ec3b13aa95049b5e3366d77d`).
