# Plan: HydroSeason Refactor — Daily-First Stress Window Detector

## TL;DR
Reframe package from monthly onset mapper → daily-first climatic hydrological stress window detector. Daily SILO is primary; monthly kept as fallback. Stress date = minimum of daily cumulative anomaly in dry-down; stress window = anomaly minimum → next wet onset. Breaking v2 API: `detect()` replaces `classify_rainfall()`. Remote-sensing helpers excluded from this plan.

## Decisions
- Daily SILO available for all AU sites → primary data path
- Stress date = minimum of cumulative anomaly curve in dry-down period
- Stress window = anomaly minimum → next wet-season onset
- Monthly path kept as fallback (cruder stress estimate from wet_boundaries)
- RS helper windows (best_pool_mapping_window etc.) deferred — NOT in scope
- Breaking API OK (major version)

## What stays (reuse as-is or minimal edit)
- `seasonality.py` — regime detection (eta², R, Walsh-Lawler SI, bimodality) — UNTOUCHED
- `fixed_season.py` — circular_climatology(), hydro_year_start_* — UNTOUCHED
- `hydro_year.py` — assign_hydro_years() works on event dates — MINOR ADAPT
- `metrics.py` — season aggregates — PARTIAL reuse
- `config.py` — AlgorithmConfig dataclass — EXTEND (add DailyDetectionConfig)
- `io.py` / `fetch.py` — EXTEND (add daily fetch + daily reader)
- `plot.py` — EXTEND (add plot_stress_timeline)
- `report.py` — EXTEND (add stress section)

## What is new / rewritten
- `fetch.py`: add get_daily_silo_rainfall()
- `validate.py`: add daily validation mode (no aggregation path)
- NEW `daily_detection.py`: daily cumulative anomaly engine
- NEW `stress.py`: stress window + confidence computation
- `pipeline.py`: new detect_daily() path + HydroSeasonResult
- `__init__.py`: add detect() as primary API

## Phases

### Phase 1: Daily Data Foundation
1. `fetch.py`: add `get_daily_silo_rainfall(aoi, start, end, cache_dir)` — same AWS pattern as monthly_rain but `daily_rain` variable; returns tidy df (Date, Rainfall_mm)
2. `validate.py`: add `validate_daily(df)` + `DailyValidationConfig` — no aggregation; validates DatetimeIndex continuity, flags gaps as NaN, computes missing_fraction
3. `io.py`: extend `read_rainfall()` to detect daily resolution and route to validate_daily

### Phase 2: Daily Detection Engine (new module daily_detection.py)
4. `compute_daily_baseline(daily_df)` — DOY climatology (rolling 30-day window mean/median) from full record
5. `compute_daily_cumulative_anomaly(daily_df, baseline)` — running sum of (rain - baseline); returns daily Series
6. `detect_wet_seasons_daily(daily_df, cum_anom, config)` — sign changes with persistence filter (min 21 days sustained positive → onset; min 21 days sustained negative → cessation); returns wet_boundaries matching current schema {hydro_year, wet_start, wet_end}
7. `detect_dry_down(wet_boundaries)` — dry_down_start = cessation + 1, dry_down_end = next onset - 1
8. `find_stress_date(cum_anom, dry_down_start, dry_down_end)` — argmin of cum_anom in dry-down window per year
9. `compute_stress_window(stress_date, next_onset, cum_anom)` — window from stress_date to day before next onset; clip to hydro year

### Phase 3: Stress Outputs (new module stress.py)
10. `build_stress_table(wet_boundaries, stress_dates, dry_downs, daily_df)` — assemble annual stress DataFrame with fields: hydro_year, stress_date, stress_window_start, stress_window_end, dry_season_length_days, antecedent_rainfall_deficit, rainfall_since_wet_season_end
11. `compute_stress_confidence(stress_row, seasonality, daily_df)` — scalar 0-1; lower for: weak seasonality, large missing fraction near stress period, isolated dry-season storms, wide onset uncertainty
12. `stress_from_monthly_seasons(wet_boundaries, monthly_df)` — monthly fallback: stress_date = last month before next onset; cruder confidence

### Phase 4: New Result Object + Pipeline
13. New `HydroSeasonResult` dataclass in `pipeline.py` (or new `results.py`):
    - `.stress` — annual stress DataFrame (PRIMARY)
    - `.seasons` — wet_boundaries + dry_down DataFrame (SECONDARY)
    - `.daily` — daily df with cum_anom + labels (if daily input)
    - `.monthly` — monthly labels derived from daily detection
    - `.hydro_year` — hydro year assignments
    - `.diagnostics` — DiagnosticsReport (extend existing)
    - `.config_used` — all resolved parameters
14. New `detect_daily(df, config)` orchestration in `pipeline.py`:
    - validate_daily → regime detect (existing seasonality.py) → circular climatology (fixed_season.py) → daily detection engine → stress module → HydroSeasonResult
15. Update `pipeline.py`'s existing `classify_rainfall()` to also return monthly stress estimate (Phase 3 fallback)
16. `__init__.py`: add `detect(rainfall, source='auto', **kwargs)` — routes daily or monthly; deprecation warning on classify_rainfall()

### Phase 5: Monthly Fallback Integration
17. Ensure `detect()` with monthly input returns HydroSeasonResult (not PipelineArtifacts) using stress_from_monthly_seasons for .stress; wet_boundaries for .seasons
18. Keep `classify_rainfall()` as deprecated alias pointing to detect(); same PipelineArtifacts output for backwards compat

### Phase 6: Tests
19. `tests/test_daily_detection.py`:
    - unimodal clear case
    - wet season crosses calendar year
    - isolated dry-season storm (should not move stress date)
    - false onset rejected
    - bimodal
    - arid/intermittent
    - missing data near stress period
20. `tests/test_stress.py`:
    - stress_date in late dry season
    - stress_window includes anomaly minimum
    - confidence lower when storm in dry season
    - monthly fallback path

### Phase 7: Plots + Reports
21. `plot.py`: add `plot_stress_timeline(result)` — annual chart: cum_anom curve + stress window shading + onset/cessation markers
22. `report.py`: extend `generate_html_report()` to include stress section

## Relevant files
- `hydroseason/fetch.py` — add get_daily_silo_rainfall()
- `hydroseason/validate.py` — add validate_daily()
- `hydroseason/io.py` — extend read_rainfall() resolution detection
- NEW `hydroseason/daily_detection.py` — daily cumulative anomaly engine
- NEW `hydroseason/stress.py` — stress window + confidence
- `hydroseason/pipeline.py` — new detect_daily() path + HydroSeasonResult
- `hydroseason/__init__.py` — add detect() API
- `hydroseason/config.py` — add DailyDetectionConfig
- `hydroseason/plot.py` — add plot_stress_timeline()
- `hydroseason/report.py` — extend for stress outputs
- `tests/test_daily_detection.py` (new)
- `tests/test_stress.py` (new)

## Verification
1. `python -m pytest -q` — all 119 existing tests still pass (monthly path unchanged)
2. Synthetic daily test: known unimodal — stress_date lands in correct late-dry-season window
3. Synthetic isolated storm test: single dry-season event doesn't shift stress_date
4. Fitzroy catchment daily SILO smoke test: stress window aligns with expected late dry season (Aug-Oct for tropical AU)
5. Monthly fallback: `detect(monthly_df)` returns HydroSeasonResult with valid .stress table
6. API smoke: `hydroseason.detect(df)` runs without args, `result.stress` is a non-empty DataFrame

## Excluded
- Remote-sensing helper windows (best_pool_mapping_window, wet_season_gap_risk_window, dry_season_clear_sky_window)
- Probabilistic HSMM mode (Phase 6 from refactor doc)
- Grid/pixel-level batch processing (future)
