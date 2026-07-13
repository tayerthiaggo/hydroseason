# HydroSeason Refactor Brief: Hydrological Stress First

## Core Reframe

HydroSeason should no longer be framed primarily as a wet/dry season classifier.

The main scientific goal is:

> Identify, for every year and region, the timing of maximum hydrological stress — the period when surface water is expected to be at or near its annual minimum.

This is especially important for studying:

- persistent river pools;
- wetlands;
- floodplain waterbodies;
- dry-season refugia;
- seasonal surface-water contraction;
- interannual variability in minimum water availability.

Wet-season detection remains important, but it becomes a secondary product that supports:

- identifying the recharge/flood/connectivity period;
- identifying the period of highest cloud/gap risk in remote-sensing time series;
- developing seasonal gap-filling strategies.

---

## Package Purpose Statement

HydroSeason identifies annual wet-season, dry-down, and maximum hydrological-stress windows from rainfall time series.

Its primary use is to support ecological and remote-sensing analyses of persistent pools, wetlands, and seasonal water availability by identifying the best annual period to assess minimum surface-water extent.

A secondary use is identifying wet-season periods where remote-sensing gaps are likely to be highest.

---

## Primary User Question

HydroSeason should answer:

```text
When, each year, is the landscape likely to experience maximum hydrological stress?
```

Not only:

```text
When does the wet season start and end?
```

---

## Primary Outputs

The primary output should be an annual hydrological stress table.

Suggested fields:

```text
hydro_year
stress_date
stress_window_start
stress_window_end
stress_confidence
dry_season_length_days
days_since_wet_season_end
days_until_next_wet_season
antecedent_rainfall_deficit
rainfall_since_wet_season_end
method_selected
diagnostic_flags
```

Definitions:

```text
stress_date:
    Estimated annual date of maximum hydrological stress.

stress_window:
    Period around the stress date when water availability is expected to be lowest.

stress_confidence:
    Confidence score based on rainfall seasonality, onset uncertainty, missing data, and late dry-season rainfall events.

antecedent_rainfall_deficit:
    Rainfall deficit accumulated during the dry-down period.
```

---

## Secondary Outputs

Wet-season outputs should still be returned.

Suggested fields:

```text
hydro_year
wet_season_onset
wet_season_cessation
wet_season_length_days
wet_season_total_rainfall
wet_season_confidence
dry_down_start
dry_down_end
season_type
```

These are useful for:

- rainfall seasonality analysis;
- hydrological-year assignment;
- remote-sensing gap-filling;
- identifying wet-season cloud/gap risk;
- estimating recharge and flood-connectivity timing.

---

## Remote-Sensing Helper Outputs

HydroSeason should explicitly support remote-sensing workflows.

Suggested outputs:

```text
best_pool_mapping_window
late_dry_candidate_dates
avoid_gap_window
wet_season_gap_risk_window
dry_season_clear_sky_window
```

Definitions:

```text
best_pool_mapping_window:
    Recommended annual window for mapping persistent pools or wetlands at minimum extent.

wet_season_gap_risk_window:
    Period when rainfall/clouds are likely to cause remote-sensing gaps.

dry_season_clear_sky_window:
    Period likely to have fewer cloud-related gaps, useful for optical imagery.
```

---

## Conceptual Annual Cycle

HydroSeason should model each hydrological year as three linked phases:

```text
1. Wet season
   Rainfall accumulation, recharge, flooding, lateral connectivity, and high cloud/gap risk.

2. Dry-down period
   Period after wet-season cessation when waterbodies contract and hydrological stress increases.

3. Maximum hydrological-stress window
   Late dry season, before reliable hydrological recovery or wet-season onset.
```

In simple terms:

```text
Wet season tells us when water comes in.
Dry-down tells us when water is being lost.
Stress window tells us when persistent pools matter most.
```

---

## Important Scientific Distinction

Rainfall-only detection estimates:

```text
climatic hydrological stress
```

not necessarily the exact observed surface-water minimum.

Actual water persistence also depends on:

- groundwater inputs;
- local geomorphology;
- soil and sediment storage;
- river flow;
- floodplain connectivity;
- evapotranspiration;
- upstream rainfall;
- regulation, dam releases, or water extraction.

Therefore, rainfall-derived outputs should be named carefully.

Recommended terminology:

```text
climatic_hydrological_stress_window
```

When combined with satellite water observations, this can support estimating:

```text
observed_surface_water_minimum_window
```

---

## Recommended Algorithmic Logic

For each location, station, catchment, or gridded pixel:

```text
1. Load daily rainfall where available.
2. Run quality control and temporal-resolution inference.
3. Detect rainfall regime.
4. Detect wet-season onset and cessation.
5. Identify the dry-down period after wet-season cessation.
6. Identify the next wet-season onset or hydrological recovery period.
7. Estimate the annual maximum hydrological-stress date.
8. Expand the date into a stress window based on uncertainty.
9. Return stress outputs, wet-season outputs, diagnostics, and confidence flags.
```

---

## Stress-Date Logic

A simple default rainfall-only interpretation:

```text
stress_date ≈ latest point in the dry season before reliable wet-season recovery
```

Usually this means:

```text
stress_date ≈ day before next wet-season onset
```

However, the method should account for uncertainty.

Stress window should widen when:

```text
wet-season onset is uncertain
late dry-season storms occur
rainfall seasonality is weak
data are missing
the region is arid/intermittent
the rainfall regime is bimodal or complex
```

---

## Daily Data Priority

Daily SILO rainfall should be preferred for detection whenever available.

Reason:

```text
Daily rainfall can distinguish persistent seasonal recovery from isolated storms.
Monthly rainfall cannot reliably separate one large storm from many wet days spread across a month.
```

Monthly outputs should be derived summaries.

Recommended design:

```text
daily rainfall
    -> daily wet/dry/stress detection
    -> annual stress window
    -> monthly labels
    -> hydrological-year summaries
```

---

## Main API Target

The user-facing API should remain simple.

```python
result = hydroseason.detect(rainfall)
```

or:

```python
result = hydroseason.from_silo(
    aoi=aoi,
    start="1980-01-01",
    end="2024-12-31",
)
```

The user should not need to provide thresholds.

---

## Suggested Result Object

```python
HydroSeasonResult(
    stress=...,
    seasons=...,
    daily=...,
    monthly=...,
    hydro_year=...,
    diagnostics=...,
    warnings=...,
    config_used=...,
)
```

### `result.stress`

Main output.

```text
hydro_year
stress_date
stress_window_start
stress_window_end
stress_confidence
antecedent_rainfall_deficit
dry_season_length_days
diagnostic_flags
```

### `result.seasons`

Wet-season and dry-down outputs.

```text
hydro_year
wet_season_onset
wet_season_cessation
dry_down_start
dry_down_end
wet_season_total_rainfall
wet_season_length_days
```

### `result.monthly`

Monthly labels derived from daily detection.

```text
month
rainfall_total
monthly_label
hydro_year
days_inside_wet_season
days_inside_stress_window
```

### `result.diagnostics`

Transparency and uncertainty.

```text
method_selected
temporal_resolution
rainfall_regime
seasonality_strength
bimodality_score
driest_period_anchor
baseline_selected
adaptive_thresholds
missing_data_fraction
false_onset_candidates_rejected
late_dry_storm_flags
stress_confidence
wet_season_confidence
```

---

## Method Selection

Default automatic method selection should follow:

```text
If daily rainfall is available:
    use daily cumulative anomaly + persistence filters

If daily rainfall is unavailable but monthly rainfall exists:
    use monthly cumulative anomaly fallback

If rainfall is weakly seasonal:
    return low-confidence stress window or fixed climatological window

If rainfall is non-seasonal:
    do not force dynamic wet/dry season boundaries

If rainfall is bimodal:
    allow multiple wet seasons and define stress windows between or after seasonal rainfall periods
```

---

## Adaptive Parameters

HydroSeason should infer parameters from the data.

Avoid requiring users to set:

```text
wet_day_threshold
minimum wet-season length
minimum dry-season length
onset window
rainfall floor
cumulative anomaly prominence
```

Instead, defaults should be:

```python
wet_day_threshold = "auto"
min_wet_season_days = "auto"
min_dry_season_days = "auto"
baseline = "auto"
stress_window_width = "auto"
method = "auto"
```

Final numeric values must be saved in:

```python
result.config_used
```

---

## Missing Data Policy

Do not create artificial rainfall by default.

Default policy:

```text
- Reindex to daily.
- Keep missing rainfall as NaN.
- Mask missing values where possible.
- Lower confidence for affected years.
- Warn or fail only when missingness prevents reliable detection.
```

Linear interpolation of rainfall should be expert-only.

---

## Hydrological Stress Confidence

Confidence should be lower when:

```text
seasonality is weak
wet-season onset is uncertain
dry-season rainfall interrupts the stress period
late dry-season storms occur
missing data affect the dry-down period
bimodality is detected but unresolved
annual rainfall regime differs strongly from climatology
```

Confidence should be higher when:

```text
seasonality is strong
wet-season onset is well defined
dry-down period is long and persistent
late dry-season rainfall is minimal
daily data are complete
stress window is consistent across neighbouring years or locations
```

---

## Validation Tests

Create synthetic tests where the true stress window is known.

Priority cases:

```text
clear unimodal wet season
wet season crossing calendar year
long dry season with clear late-dry stress
dry-season isolated storm
false onset followed by long dry spell
severe drought year
bimodal rainfall regime
weak/non-seasonal rainfall
arid intermittent rainfall
missing data near stress period
extreme rainfall event near dry-season end
```

Expected behaviour:

```text
isolated storm does not trigger hydrological recovery
false onset is rejected
stress date occurs in late dry season
stress window widens when uncertainty is high
bimodal climates are not forced into one wet season
weak/non-seasonal climates are flagged as low confidence
monthly labels are derived from daily outputs
```

---

## Implementation Phases

### Phase 1: Reframe Outputs

Implement:

```text
result.stress
result.seasons
result.diagnostics
result.config_used
```

The stress table should become the main output.

---

### Phase 2: Daily Cumulative Anomaly

Implement daily detection for:

```text
wet-season onset
wet-season cessation
dry-down period
stress date
stress window
```

---

### Phase 3: Adaptive Parameters and Regime Detection

Implement:

```text
classify_regime()
detect_bimodality()
estimate_driest_period_anchor()
estimate_adaptive_thresholds()
```

---

### Phase 4: Remote-Sensing Helper Outputs

Implement:

```text
best_pool_mapping_window
wet_season_gap_risk_window
dry_season_clear_sky_window
```

---

### Phase 5: Monthly Fallback

Keep monthly cumulative anomaly for cases where daily data are unavailable.

---

### Phase 6: Advanced Probabilistic Mode

After the deterministic daily workflow is stable, implement HSMM or another probabilistic model.

This should be optional and advanced, not the first implementation target.

---

## Acceptance Criteria

The refactor is successful when:

```text
1. A user can call hydroseason.detect(rainfall) without thresholds.
2. Daily rainfall is preferred when available.
3. The main output is annual hydrological stress timing.
4. Wet-season outputs are still returned as secondary products.
5. Stress windows are returned, not only single dates.
6. Monthly labels are derived from daily detection.
7. Weak or non-seasonal regions are flagged instead of forced.
8. Bimodal rainfall regimes are handled explicitly.
9. Remote-sensing helper windows are produced.
10. Diagnostics explain uncertainty and method choices.
11. config_used stores all estimated parameters.
```

---

## Core Principle

```text
HydroSeason should identify when water stress is highest, not only when rainfall seasonality changes.
```

The package should help answer:

```text
When should I look at satellite imagery to identify persistent waterbodies at minimum extent?
```

and secondarily:

```text
When is the wet season likely to create the most remote-sensing gaps?
```
