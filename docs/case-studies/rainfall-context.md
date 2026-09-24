# Rainfall Context Case Study

This study re-runs the [main workflow's](main-workflow.md) five catchments
with monthly SILO rainfall attached as context (`run_hydroseason`'s rainfall
path). The window and extent inputs are the same (2005-01-01 to 2025-12-01,
252 months); rainfall is monthly SILO (`silo-open-data`), pre-fetched and
trimmed to that range.

## Rainfall is strictly additive

Rainfall is resolved *after* the water-only `analyze_catchment` call and
cannot change regime, route, or hydrological-year boundaries. Every
water-only column of this study's summary (`regime`, `route`, `route_reason`,
timing statistics, `n_hydro_years`, `n_events`, `longest_low_spell_months`,
...) is identical to the main workflow's. Only the rainfall-comparison
columns are new: `rainfall_regime`, `rainfall_amplitude_snr`,
`rainfall_peak_timing_concentration`, `rainfall_trough_timing_concentration`,
`rainfall_divergence`, and `rainfall_peak_lag_months`.

## Results

<!-- BEGIN GENERATED RAINFALL RESULTS -->
| Catchment | Water Regime | Rainfall Regime | Water Peak R | Rainfall Peak R | Divergence | Peak Lag (months) |
|---|---|---|---|---|---|---|
| Daly River (NT) | seasonal | seasonal | 0.878 | 0.874 | agree | 2 |
| Fitzroy River (WA) | seasonal | seasonal | 0.900 | 0.908 | agree | 1 |
| Gilbert River (QLD) | seasonal | seasonal | 0.934 | 0.914 | agree | 1 |
| Lachlan River (NSW) | aseasonal | aseasonal | 0.393 | 0.416 | agree | N/A |
| Moonie River (QLD/NSW) | aseasonal | seasonal | 0.444 | 0.594 | extent_damped | N/A |
<!-- END GENERATED RAINFALL RESULTS -->

`rainfall_divergence` compares the rainfall-only regime with the water
regime: `agree` means both give the same regime; `extent_damped` means
rainfall shows a seasonal signal that surface-water extent does not.

## Findings

1. **Seasonal catchments agree.** Daly, Fitzroy, and Gilbert are seasonal in
   both series, with similar peak timing concentration (R within 0.03).
2. **Extent lags rainfall by one to two months.** Fitzroy and Gilbert peak
   1 month after rainfall, Daly 2 months.
3. **Lachlan is aseasonal in both series.** Neither rainfall nor water shows
   a recurring annual cycle.
4. **Moonie shows `extent_damped`.** Its rainfall is seasonal, but its
   surface water is not: peak water timing does not recur (p = 0.232), so no
   hydrological year is defined. Rainfall does not override that:
   rainfall is ancillary by design.
5. **None of this changes routing.** The water-only columns are identical to
   the main workflow whatever rainfall shows.

## Reproduction

```bash
python scripts/_build_study_case_rainfall.py --check
```

See [case_studies/README.md](https://github.com/tayerthiaggo/hydroseason/blob/main/case_studies/README.md)
for data provenance and licensing.
