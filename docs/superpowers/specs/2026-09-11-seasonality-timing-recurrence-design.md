# Seasonality test by annual timing recurrence: design

Date: 11 September 2026. Status: approved design, not implemented. Repository baseline: `a4592e2` (HydroSeason 0.2.0, policy `established_0_2_0`). Supersedes [the seasonality gate comparison experiment](2026-09-11-seasonality-gate-comparison-design.md).

## 1. Purpose and decision

Replace the amplitude/SNR seasonality gate with a test whose every decision rule is established or cited. The test ships as an opt-in candidate decision policy, `candidate_timing_recurrence`, beside `established_0_2_0`. The default does not change until the repository promotion gate in [`docs/decision-policy.md`](../../decision-policy.md) passes.

The candidate answers one question: **does the timing of the annual high and the annual low recur at the same time of year across years?** It classifies a record as `seasonal` or `aseasonal`. There is no `marginal` class. Boundary detection, anchor months, trough refinement and boundary-support checks are unchanged.

The only numerical choice the test introduces is the significance level, α = 0.05, fixed before any result is seen.

## 2. Scientific basis

### 2.1 What is tested

A seasonal pattern has a fixed and known period tied to the calendar ([Hyndman and Athanasopoulos, 2021](https://otexts.com/fpp3/tspatterns.html)). A single year holds one realisation of the annual cycle, so seasonality cannot be established within one year; it is established by recurrence across years.

Two properties are routinely called seasonality and must not be conflated (Colwell, 1974; Tonkin et al., 2017):

- **Magnitude**: how much a variable changes within a year.
- **Recurrence (predictability)**: whether that change happens at the same time each year.

Annual boundaries presuppose a low state that recurs at a similar time each year. The gate therefore tests recurrence. Magnitude remains a descriptor, and its observability is already handled by the calibrated per-year detectability rule.

Timing of annual events on the calendar circle is the established hydrological approach to seasonality (Burn, 1997; Villarini, 2016). Hall and Blöschl (2018) test uniformity of flood timing with the Kuiper test. `established_0_2_0` already uses a weighted Kuiper test with a rotation null.

### 2.2 Why the current gate is replaced

The current rule labels a record seasonal when SNR ≥ 2 and the lower bound of peak R ≥ 0.70, and aseasonal when SNR < 0.70. Neither the SNR formula nor any of the cutoffs has a literature source. The SNR denominator absorbs trend and interannual variability, so a perfect annual cycle plus a linear trend is labelled aseasonal ([counterexample](../../paper/seasonality_gate_counterexample.json)).

### 2.3 Alternatives considered and rejected

| Alternative | Reason rejected |
|---|---|
| Lake seasonality contribution, C = σ̄ / (σ̄ + δ) (Li et al., 2025) | Measures within-year versus between-year variability and is explicitly not calendar-locked. In a pilot it called white noise seasonal in 100% of records and annual cycles with trend aseasonal in 100%. |
| Normalised seasonal index (harmonic amplitude / RMSE; Gaudaré et al., 2026) | Built for InSAR coherence, used inversely for flood mapping, thresholds fitted to one delta; not a statistical test. |
| X-13 combined seasonality test; Webel–Ollech test | Established, but designed and calibrated for economic series, needs gap-free input, and adds ARIMA/X-11 machinery. Not needed once timing recurrence is the estimand. |
| Harmonic predictive skill, STL seasonal strength with calibrated cutoffs | Both end in study-calibrated thresholds with no literature source. |

### 2.4 Development evidence (not validation)

A scratchpad pilot (200 records per cell, noise SD 2.5, trend +40 points, strong trend +72 with SD 1, α = 0.05 on both peak and trough) motivated the design. It does not validate it. The pilot's detrended variant used only informative years and no widened tolerance, so it is a simpler version of the rule in Section 3.

| Series (30 / 15 years) | Current label seasonal or marginal | Timing test, raw extent | Timing test, detrended |
|---|---|---|---|
| white noise | 0.22 / 0.82 | 0 / 0 | 0 / 0 |
| AR(1) 0.8 | 0 / 0.13 | 0.03 / 0.02 | 0.01 / 0 |
| strong trend | 0 / 0 | 0.68 / 0.82 | 0 / 0 |
| annual | 1 / 1 | 1 / 1 | 1 / 1 |
| annual + strong trend | 0 / 0 | 1 / 1 | 1 / 1 |

Raw-extent timing fails on a strong trend because the annual maximum lands in December and the minimum in January. Detrending removes that failure.

### 2.5 Terminology

`extent_pct` measures observed surface water, not a climate variable, so this design does not call a mean-by-calendar-month profile a climatology. The 12-value profile is the **mean monthly extent**; its extremes are the **peak month of mean monthly extent** and the **trough month of mean monthly extent**. The same wording replaces "climatology" in the manuscript and in the public field names (Section 6.1). Frozen policy records, plans and handoffs keep their original wording.

## 3. Decision rule

### 3.1 Inputs and record sufficiency

1. Prepare the record with `prepare_monthly_extent`, using the caller's `max_invalid_pct`, `quality_policy` and `measurement_tolerance_pct`. This step is unchanged.
2. A calendar year qualifies when it has at least `min_months_per_year` (default 9) candidate-usable months. This rule is unchanged.
3. Fewer than 5 qualifying years (the existing `_MIN_USABLE_YEARS`) gives status `insufficient_record`, reason `too_few_qualifying_years`. This rule is unchanged.

### 3.2 Classical trend and detrended series

1. Build a complete monthly grid from the first to the last month of the prepared record. Set y_t to `extent_pct` where the month is candidate-usable and finite; otherwise y_t is missing.
2. Fill internal missing months by linear interpolation in time, **for trend estimation only**. Do not extrapolate before the first or after the last observation. Li et al. (2025) interpolate cloud-affected months linearly in the same way.
3. Trend: T_t = Σ w_k y_{t+k} for k = −6…6, with w = 1/24 at k = ±6 and 1/12 otherwise. This is the centred 2×12 moving average of classical additive decomposition (Hyndman and Athanasopoulos, 2021). T_t is undefined if any of its 13 inputs is undefined, which leaves the first and last six months without a trend.
4. Detrended series: SI_t = y_t − T_t, defined only where the month is candidate-usable and T_t is defined. Interpolated values never enter SI.
5. A calendar year is **timing-eligible** when at least `min_months_per_year` of its months have SI defined. Fewer than 5 timing-eligible years gives status `insufficient_record`, reason `trend_unavailable`. A missing trend is never converted to `aseasonal`.

### 3.3 Per-year detectability

For each timing-eligible year, detectability is computed on **raw** extent over the months with SI defined. It uses the calibrated `established_0_2_0` rule and `TIMING_IDENTIFIABILITY_DEFAULTS` without change:

- floor = max(measurement tolerance, record-wide robust noise from `robust_scale`, pixel resolution at the raw peak rows, pixel resolution at the raw trough rows, machine epsilon);
- detectable when the raw amplitude exceeds the floor, amplitude/floor ≥ 3.0, and, where pixel counts exist, the peak has at least 5 water pixels.

Non-detectable years contribute no timing evidence, as in `established_0_2_0`.

### 3.4 Peak and trough month sets

For each detectable year y:

- tolerance_y = floor_y + (max T − min T over that year's SI-defined months);
- peak months = months with SI ≥ max SI − tolerance_y;
- trough months = months with SI ≤ min SI + tolerance_y.

These sets use the existing `equivalent_extremum_months`.

**Invariant: detrending never creates timing precision the raw data lack.** For months a and b in the same year, SI_a − SI_b = (y_a − y_b) − (T_a − T_b). Let r be the raw minimum month and s the SI minimum month. Any month a within the floor of the raw minimum satisfies SI_a − SI_s ≤ (y_a − y_r) + (y_r − y_s) + range(T) ≤ floor + 0 + range(T). Every raw-equivalent trough month is therefore in the SI trough set, and the same argument holds for peaks.

This protects zero-dominated records. In a pilot with an exact-zero nine-month dry plateau, plain detrending selected a single trough month (Aug, Sep or Oct); with the widened tolerance the set equalled the raw nine-month tie.

### 3.5 Test

- Pass all detectable years' peak sets to `summarise_annual_timing`, and separately all trough sets, with `n_resamples = n_bootstrap` and the caller's `random_state`. Years are not filtered by timing status: broad but consistently placed sets are evidence of recurrence.
- Each year carries total weight 1 spread equally over its months.
- The uniformity p-value is the existing weighted Kuiper statistic against a null that rotates each year's month set by an independent uniform calendar offset. There are max(n_resamples, 999) null draws, so the minimum p-value is 1/1000.
- The bootstrap interval of R is reported but plays no part in the decision.

### 3.6 Classification, reasons and route

| Condition | Class | Reason | Route |
|---|---|---|---|
| Section 3.1 or 3.2 insufficiency | none (`insufficient_record`) | `too_few_qualifying_years` or `trend_unavailable` | `insufficient_record` |
| No detectable year | `aseasonal` | `no_detectable_years` | `event_characterisation` |
| peak p < 0.05 and trough p < 0.05 | `seasonal` | `peak_and_trough_recur` | `per_year_detection` |
| only trough p < 0.05 | `aseasonal` | `peak_uniformity_not_rejected` | `event_characterisation` |
| only peak p < 0.05 | `aseasonal` | `trough_uniformity_not_rejected` | `event_characterisation` |
| neither p < 0.05 | `aseasonal` | `peak_and_trough_uniformity_not_rejected` | `event_characterisation` |

`aseasonal` means annual timing recurrence was not established. It is not a claim that timing is uniform.

A `seasonal` record still passes through the unchanged downstream check that requires at least `min_informative_years` resolved peak and trough cycles, and it falls back to event characterisation with an explicit reason if it fails.

### 3.7 Removed under the candidate

The SNR as a decision input, the SNR cutoffs 2.0 and 0.70, the R lower bound ≥ 0.70, the ≥10-year condition for accepting uniformity, the calendar-year informative-year condition in the gate, and the `marginal` class.

`amplitude_snr` is still computed and reported as a descriptor.

## 4. Architecture

### 4.1 New module `hydroseason/_seasonality_test.py`

```python
@dataclass(frozen=True)
class TrendEstimate:
    trend: pd.Series            # T on the monthly grid; NaN where undefined
    detrended: pd.Series        # SI at candidate-usable months with T defined
    interpolated: pd.Series     # bool; months filled for trend estimation only
    n_interpolated_months: int
    n_months_without_trend: int


@dataclass(frozen=True)
class TimingRecurrenceResult:
    classification: Literal["seasonal", "aseasonal"] | None
    status: Literal["ok", "insufficient_record"]
    reason: str
    alpha: float
    peak: AnnualTimingSummary
    trough: AnnualTimingSummary
    peak_month_sets: Mapping[int, tuple[int, ...]]
    trough_month_sets: Mapping[int, tuple[int, ...]]
    n_qualifying_years: int
    n_timing_eligible_years: int
    n_detectable_years: int
    trend: TrendEstimate


def classical_trend(prepared: pd.DataFrame) -> TrendEstimate: ...


def assess_timing_recurrence(
    prepared: pd.DataFrame,
    *,
    thresholds: TimingIdentifiabilityThresholds,
    measurement_tolerance_pct: float,
    min_months_per_year: int = 9,
    alpha: float = TIMING_RECURRENCE_ALPHA,
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> TimingRecurrenceResult: ...
```

No public name starts with `test_`, because pytest collects imported `test_*` callables.

### 4.2 Shared detectability helper

Extract the per-year detectability computation, which is currently duplicated in the calendar-year and cycle-window loops of `_timing_identifiability.py`, into one helper:

```python
@dataclass(frozen=True)
class AnnualDetectability:
    floor_pp: float
    amplitude_pp: float
    amplitude_to_floor_ratio: float
    peak_n_water: int | None
    at_or_below_floor: bool
    detectable: bool


def annual_detectability(
    rows: pd.DataFrame,
    *,
    noise_pp: float,
    measurement_tolerance_pp: float,
    thresholds: TimingIdentifiabilityThresholds,
    pixel_support_status: PixelSupportStatus,
) -> AnnualDetectability: ...
```

Both existing loops and the candidate call it. `TIMING_IDENTIFIABILITY_DEFAULTS` and `TIMING_IDENTIFIABILITY_FINGERPRINT` are unchanged. A regression test pins `established_0_2_0` outputs as identical before and after the extraction.

### 4.3 Decision policy and entry points

In `_decision_policy.py`:

- `SeasonalityPolicy = Literal["timing_recurrence"]`.
- `DecisionPolicy` gains `"candidate_timing_recurrence"`. A promoted identifier is assigned only at promotion, which avoids the `established_0_3_0` identifier reserved by the trough-geometry design.
- `TIMING_RECURRENCE_ALPHA = 0.05`.
- `decide_timing_recurrence(result: TimingRecurrenceResult) -> EstablishedDecision` implements Section 3.6. It emits only `seasonal`, `aseasonal` or `insufficient_record`, and sets `timing_evidence` to `supported`, `unsupported` or `insufficient` respectively.

`assess_water_regime(..., seasonality_policy: SeasonalityPolicy | None = None)`:

- `None` runs the current code path unchanged.
- `"timing_recurrence"` computes the candidate result and decision.
- `WaterRegimeAssessment` gains `seasonality_test: TimingRecurrenceResult | None = None`.
- The peak and trough months of **mean monthly extent** (today's `climatological_peak_month` and `climatological_trough_month`, renamed at implementation per Section 6.1) keep today's computation: the mean of raw observed extent per calendar month over qualifying years. Under the candidate they are populated whenever the class is `seasonal`, without the `established_0_2_0` dominant-month condition, because the candidate test has already established recurrence. For records that both policies route to per-year detection, the anchor is therefore identical.
- The SNR and marginal caveats are replaced by one candidate caveat that names the policy and states that `aseasonal` means recurrence was not established.

`analyze_catchment(..., seasonality_policy: SeasonalityPolicy | None = None)` passes the keyword through. Under the candidate, route-reason strings report peak and trough p-values instead of the SNR. Nothing else in `analyze_catchment` changes.

### 4.4 Data flow

```
extent → prepare_monthly_extent → qualifying years                     (unchanged)
       → [candidate] classical_trend → SI, timing-eligible years
       → annual_detectability on raw rows (shared helper)
       → SI peak/trough month sets, tolerance = floor + range(T)
       → summarise_annual_timing (peak), summarise_annual_timing (trough)
       → decide_timing_recurrence → regime, route
       → anchor, detector, trough refinement, resolved-cycle check    (unchanged)
```

### 4.5 Boundaries of the change

These are unchanged:

- the anchor months that centre the trough and peak search windows (the peak and trough of mean monthly extent, computed on raw observed values);
- `_dynamic_year`, `analyze_hydrological_state`, the trough-refinement candidates, and the downstream resolved-cycle check;
- report columns, report copy, CLI and batch interfaces;
- CAMELS-AUS partitions, which are neither loaded nor split.

Mean monthly extent computed on the detrended series was rejected as the anchor because, on the zero-plateau pilot, it moved the trough anchor from January to August. The anchor belongs to the [0.3.0 trough-geometry design](../../decision-policy-0.3.0.md).

**Rule:** timing statistics of detected hydrological-year cycles never feed the seasonality decision. The search window constrains where those boundaries can fall, so their concentration is partly produced by the method.

## 5. Validation

### 5.1 No calibration partition

The candidate fits nothing. The rule, α and all inherited thresholds are fixed before any result is seen, so the promotion gate's calibration step has no parameter to select. Validation uses one untouched synthetic set and checks on real records after the design is frozen.

### 5.2 Synthetic known-truth set

New module `hydroseason/_seasonality_synthetic.py`:

- Seeds: `SEASONALITY_VALIDATION_SEEDS = range(90000, 95000)`.
- Each record's stream is `SeedSequence([90000, family_id, n_years, replicate, attempt])`.
- Records start in January 1990 and carry `invalid_pct`.
- Unless stated otherwise: centre 50%, annual cosine amplitude 5, Gaussian noise SD 2.5, integer calendar phase uniform on 0–11 per record.
- Lengths are 7, 15 and 30 years, with 200 records per family and length.
- A record falling outside 0–100% is redrawn with the next `attempt`; redraw counts are logged. Records are never clipped.

| ID | Family | Construction | Truth |
|---|---|---|---|
| 1 | white noise | centre + noise | not seasonal |
| 2 | AR(1) 0.5 | stationary AR(1), marginal SD 2.5, stationary initial value | not seasonal |
| 3 | AR(1) 0.8 | as ID 2 with coefficient 0.8 | not seasonal |
| 4 | trend | centred linear change of +40 points over the record + noise | not seasonal |
| 5 | strong trend | centred linear change of +72 points + noise SD 1 | not seasonal |
| 6 | step | +20 points from the record midpoint + noise | not seasonal |
| 7 | non-calendar events | monthly start probability 0.08, amplitude U[5, 10], exponential decay 1.5 months, 120-month burn-in, centred by generating expectation, + noise | not seasonal |
| 8 | all-zero | exact zeros | not seasonal |
| 21 | sinusoid | annual cosine + noise | seasonal |
| 22 | narrow pulse | circular triangular pulse, half-width 2 months, range 10 + noise | seasonal |
| 23 | asymmetric | 3-month rise, 9-month decline, range 10 + noise | seasonal |
| 24 | annual + trend | ID 21 + ID 4 trend | seasonal |
| 25 | annual + strong trend | annual cosine + ID 5 trend + noise SD 1 | seasonal |
| 26 | zero-dominated pulse | 3 consecutive wet months at 30 + noise SD 2; exact 0 in the other 9 months | seasonal |
| 27 | timing jitter | ID 21 with an independent yearly phase offset ~ N(0, 1 month) | seasonal |
| 41 | two cycles per year | 6-month cosine + noise | reported only |
| 42 | phase drift | ID 21 with the phase shifting linearly by 6 months over the record | reported only |
| 43 | amplitude curve | ID 21 with amplitude/noise ratio ∈ {0.25, 0.5, 1, 2, 4} | reported only |

Observation-stress variants keep truth unchanged. They apply to IDs 1, 3, 5 and 7 (negatives) and IDs 21 and 26 (positives):

- 10% and 25% of months missing at random (`invalid_pct = 100`);
- a 3-month gap centred on the truth trough month in every third year (positives only; ID 21 cosine minimum, ID 26 middle month of the dry plateau);
- low-extent pixel rounding: extent scaled by 0.02, `n_aoi = n_valid = 1000`, `n_invalid = 0`, `n_water = round(extent/100 × 1000)`.

Each record is scored with `assess_water_regime(..., seasonality_policy=None)` and with `seasonality_policy="timing_recurrence"`. Both regime and route are saved for every policy.

### 5.3 Acceptance criteria

The candidate is eligible for promotion only if all of these hold. One-sided Wilson bounds use z = 1.6448536269514722. Denominators are all records of the stated truth, including `insufficient_record`.

1. **False seasonal.** For each non-seasonal family (IDs 1–8), pooled over the three lengths (600 records), the one-sided 95% Wilson upper bound of the seasonal rate is ≤ 0.05.
2. **Detection.** For each seasonal family (IDs 21–27), at 15 years and at 30 years separately (200 records each), the seasonal rate is ≥ 0.80, the conventional power level. 7-year rates are reported but not used for acceptance.
3. **Missing data.** Criterion 1 holds for each stressed negative family (IDs 1, 3, 5, 7) with 25% of months missing at random.
4. **Status accounting.** Every `insufficient_record` result is reported with its reason and is never counted as `aseasonal`. Tables show both the all-records and the evaluable-records denominators.

A failed criterion is a documented finding. The candidate is not tuned; any redesign becomes a new candidate version with a new synthetic seed range.

### 5.4 Tests

- `seasonality_policy=None` reproduces current `WaterRegimeAssessment` and `CatchmentAnalysis` outputs for the existing fixtures, including the protected catchments and the trend counterexample.
- Extracting `annual_detectability` leaves `established_0_2_0` timing evidence unchanged.
- The 2×12 weights sum to 1; a linear trend is removed exactly; a pure period-12 pattern is annihilated from T.
- The first and last six months have no trend, and interpolated months never appear in SI.
- Raw-equivalent months are a subset of SI-equivalent months (property test), and the zero-plateau fixture keeps its full tie set.
- All 12 calendar rotations of one record give the same class.
- The trend counterexample (annual cosine + 0.2 per month) is `seasonal` under the candidate.
- White noise, all-zero and constant records are not `seasonal`.
- Short records return `insufficient_record` with the correct reason.
- Fixed seeds reproduce identical p-values.

### 5.5 Real records, after freeze

The records are those listed in the superseded comparison spec: Daly, Fitzroy, Gilbert, Lachlan and Moonie from `case_studies/data/extent/`, plus Kakadu and Roper, with the same input selection. They are run only after this design and the implementation are frozen.

- **Daly, Fitzroy, Gilbert** (protected seasonal, per-year) must be `seasonal` with route `per_year_detection`. A different outcome blocks promotion unless reviewed evidence shows the protected label is wrong (promotion gate item 5).
- **Lachlan, Moonie** (protected aseasonal, event): any change is reported with raw series, SI, month sets and both p-values for review. No parameter changes in response.
- **Kakadu, Roper:** descriptive only.

### 5.6 Deferred: independent real cohort

The CAMELS-AUS cohort required for promotion gets its own protocol, written and committed before any CAMELS result is opened, when the extraction pass runs. That pass records both `established_0_2_0` and `candidate_timing_recurrence` regime and route for every catchment, so the single-use sealed partition is never re-run for this purpose.

### 5.7 Outputs

The entry point `scripts/evaluate_timing_recurrence.py` writes an immutable run directory `case_studies/results/seasonality-timing-recurrence/<run_id>/` containing:

- `protocol.json`: commit, package and dependency versions, seeds, α, configuration, source hashes;
- `synthetic_records.csv`: one row per record × policy, with family, length, variant, truth, regime, route, status, reason, p-values, R, detectable-year counts, redraw count;
- `synthetic_metrics.csv`: rates with Wilson intervals by family × length × variant × policy;
- `acceptance.json`: criteria 1–4, pass or fail, with numerators and denominators;
- `real_records.csv` and `real_records.md`;
- `sensitivity_alpha_0_10.csv`: all synthetic metrics recomputed at α = 0.10;
- `findings.md`: failure modes and disagreements with `established_0_2_0`.

Nothing existing under `case_studies/results/` is overwritten.

## 6. Documentation, paper and migration

### 6.1 At implementation

- `docs/decision-policy.md`: add a paragraph naming `candidate_timing_recurrence` as an opt-in, unpromoted candidate, like the trough-refinement paragraph.
- `docs/decision-policy-timing-recurrence.md`: the frozen design record, condensed from this spec.
- `docs/superpowers/plans/2026-09-11-camels-aus-validation-handoff.md`, step 2: record candidate regime and route in the same pass.
- Terminology rename, shipped with the candidate (Section 2.5): `climatological_peak_month` → `mean_monthly_peak_month` and `climatological_trough_month` → `mean_monthly_trough_month` on `WaterRegimeAssessment` and `CatchmentAnalysis`, with the old names retained as deprecated read-only aliases; the report strings "climatological maximum" and "climatological minimum" become "maximum of mean monthly extent" and "minimum of mean monthly extent"; internal identifiers and comments in `_regime.py`, `_catchment.py` and `hydro_year.py` follow; `docs/report-columns.md` is updated. The unreachable `fixed_climatological_window` route literal is left as it is: renaming or removing it is a separate public-schema decision. The deprecated aliases are removed only at promotion, with migration notes.

### 6.2 At promotion only

Migration notes, `docs/report-columns.md` additions, CLI and batch flags, the default switch, a promoted policy identifier, and the manuscript Methods update.

### 6.3 Draft Methods paragraph

Apply only after promotion.

> Seasonality was assessed as recurrence of annual timing rather than magnitude of within-year variation (Colwell, 1974; Tonkin et al., 2017). The trend-cycle of monthly extent was estimated with a centred 2×12 moving average (classical additive decomposition; Hyndman and Athanasopoulos, 2021) after linear interpolation of internal missing months, which were used for trend estimation only (cf. Li et al., 2025), and was subtracted from observed extent. In each calendar year with at least nine detrended months and a detectable annual range, months equivalent to the detrended maximum and minimum were identified. The equivalence tolerance was widened by the within-year range of the trend estimate, so that detrending could not create timing precision absent from the observations. Each year contributed equal weight across its equivalent months. Uniformity of peak and trough timing on the calendar circle was assessed with a Kuiper test (Hall and Blöschl, 2018) against a null distribution rotating each year's month set, following circular approaches to hydrological seasonality (Burn, 1997; Villarini, 2016). Records were classified as seasonal when both tests rejected uniformity at α = 0.05, and aseasonal otherwise; aseasonal denotes that annual timing recurrence was not established, not that timing is uniform.

## 7. Known limitations and scope

- **Fixed calendar.** Phase drift and large timing jitter reduce power; strongly drifting records may be `aseasonal`. This is consistent with search windows anchored on a fixed month and must be stated as scope.
- **Twice-yearly regimes** are mostly `aseasonal` (5–22% seasonal in the pilot). This fits a one-cycle-per-year boundary model.

  > **Correction, 14 September 2026.** The validation run measured the opposite: `two_cycles` is classified seasonal 98.5% of the time at 15 years and 100% at 30 years, and six-month phase drift 96% and 100%. The 5-22% figures came from a weaker pilot variant that used informative years only with no widened tolerance. The rule approved in Section 1 uses every detectable year with tie-aware month sets and is materially more powerful. See `case_studies/results/seasonality-timing-recurrence/2026-09-12/findings.md` section 6. The original sentence above is left intact as the record of what was believed at approval.
- **Calendar-year windows.** Persistent noise can favour extremes near window edges. The AR(1) families measure this.
- **Moving average.** The first and last six months are lost, so 5 timing-eligible years need about 7 calendar years. Abrupt steps are over-smoothed (Hyndman and Athanasopoulos, 2021); the step family measures this.
- **Interpolation.** Long internal gaps bias T near the gap. Interpolated values never enter SI.
- **Null assumption.** The rotation null treats years as exchangeable under no seasonality; interannual dependence is not modelled. The Monte Carlo p-value resolution is 1/1000.
- **Inherited thresholds.** The calibrated `established_0_2_0` detectability thresholds (3.0 amplitude-to-floor ratio, 5 peak water pixels) and the downstream resolved-cycle requirement are retained, not re-derived.
- **Anchor bias.** The anchor from mean monthly extent on raw values is unchanged. In a pilot, a strong trend shifted it by a mean of up to 0.43 months, within the ±3-month search radius.
- **Out of scope:** the CAMELS cohort protocol, report and CLI changes, the default switch, manuscript edits before promotion, and any boundary-method change.

## 8. References

- Burn, D. H. (1997). Catchment similarity for regional flood frequency analysis using seasonality measures. *Journal of Hydrology*. https://doi.org/10.1016/S0022-1694(97)00068-1
- Colwell, R. K. (1974). Predictability, constancy, and contingency of periodic phenomena. *Ecology*, 55. https://doi.org/10.2307/1940366
- Gaudaré, L., Corgne, S., Jolivet, M., et al. (2026). Flood pulse monitoring in wetlands with multi-temporal Sentinel-1 interferometric coherence data: application to the Okavango Delta (Botswana). *Remote Sensing of Environment*, 334, 115173. https://doi.org/10.1016/j.rse.2025.115173
- Hall, J., and Blöschl, G. (2018). Spatial patterns and characteristics of flood seasonality in Europe. *Hydrology and Earth System Sciences*, 22, 3883–3901. https://doi.org/10.5194/hess-22-3883-2018
- Hyndman, R. J., and Athanasopoulos, G. (2021). *Forecasting: Principles and Practice* (3rd ed.). OTexts. Sections 2.3 and 3.4. https://otexts.com/fpp3/
- Li, L., Long, D., Wang, Y., et al. (2025). Global dominance of seasonality in shaping lake-surface-extent dynamics. *Nature*, 642, 361–368. https://doi.org/10.1038/s41586-025-09046-3
- Tonkin, J. D., Bogan, M. T., Bonada, N., et al. (2017). Seasonality and predictability shape temporal species diversity. *Ecology*, 98(5), 1201–1216. https://doi.org/10.1002/ecy.1761
- Villarini, G. (2016). On the seasonality of flooding across the continental United States. *Advances in Water Resources*. https://doi.org/10.1016/j.advwatres.2015.11.009

Source checks: Li et al. (2025) Methods equations 8–10 were read in the open-access full text. Gaudaré et al. (2026) was read at abstract and full-text-excerpt level only; its normalised seasonal index equation was not verified. The original Kuiper (1960) reference is to be added to the manuscript after checking.
