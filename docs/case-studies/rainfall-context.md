# Rainfall Context Case Study

This study re-runs [Case Study 1's](main-workflow.md) five catchments with
monthly SILO gridded rainfall attached as ancillary context
(`run_hydroseason`'s rainfall path), using the same
`compare_rainfall_to_extent_regime` comparison exposed by the public API.

Same analysis window and extent inputs as the main workflow study
(2005-01-01 through 2025-12-01, 252 monthly observations); rainfall inputs
are monthly SILO rainfall (`silo-open-data`, Official archive), pre-fetched
and trimmed to the same range.

## Rainfall is strictly additive

Rainfall is resolved *after* the water-only `analyze_catchment` call and can
never influence regime, route, or hydrological-year boundaries. Every
water-only column in `case_studies/results/main_rainfall/summary.csv`
(`regime`, `route`, `amplitude_snr`, `peak_phase_iqr_months`, `n_hydro_years`,
`n_events`, `longest_low_spell_months`, `water_extent_peak_month`,
`climatological_trough_month`, ...) is identical to
[Case Study 1's](main-workflow.md) `summary.csv`. Only four rainfall-
comparison columns are new: `rainfall_regime`, `rainfall_amplitude_snr`,
`rainfall_divergence`, and `rainfall_peak_lag_months`.

## Results

<!-- BEGIN GENERATED RAINFALL RESULTS -->
| Catchment | Water Regime | Rainfall Regime | Water SNR | Rainfall SNR | Divergence | Peak Lag (months) |
|---|---|---|---|---|---|---|
| Daly River (NT) | marginal | seasonal | 2.46 | 5.81 | extent_damped | 2 |
| Fitzroy River (WA) | seasonal | seasonal | 2.65 | 5.71 | agree | 1 |
| Gilbert River (QLD) | seasonal | seasonal | 3.62 | 4.79 | agree | 1 |
| Lachlan River (NSW) | aseasonal | aseasonal | 0.67 | 0.86 | agree | N/A |
| Moonie River (QLD/NSW) | aseasonal | marginal | 0.62 | 1.34 | extent_damped | N/A |
<!-- END GENERATED RAINFALL RESULTS -->

`rainfall_divergence` describes how the rainfall-only regime compares to the
water-extent regime: `agree` means both series indicate the same regime
strength; `extent_damped` means rainfall shows a stronger seasonal signal
than the observed surface-water extent (expected — a river's inundation
footprint smooths and lags rainfall's raw seasonal swing).

## Findings

1. **Rainfall consistently shows a stronger seasonal signal than extent.**
   Every catchment's rainfall SNR exceeds its water-extent SNR — rainfall
   arrives and recedes more sharply than the surface water it drives, which
   integrates, lags, and drains more slowly.
2. **Peak lag is short and consistent for seasonal catchments.** Fitzroy and
   Gilbert both show extent peaking 1 month after rainfall; Daly (routed to
   `fixed_climatological_window` under flagged quality) shows a 2-month lag.
   Daly's rainfall classification does not override its water regime: the
   water record misses the <=1.5-month peak-timing gate, and rainfall is
   ancillary by design.
3. **Aseasonal catchments stay aseasonal in both series.** Lachlan's
   rainfall SNR (0.86) remains well below the seasonal threshold, agreeing
   with its `event_characterisation` water route. Moonie's rainfall is
   `marginal` (SNR 1.34) while its water extent is `aseasonal` (SNR 0.62) —
   still an `extent_damped` divergence, not a regime disagreement that would
   call the water-only routing into question.
4. **None of this changes routing.** As designed, the water-only columns
   above are byte-identical to Case Study 1 regardless of what rainfall
   shows — rainfall is context for interpretation, never an input to
   detection.

## Reproduction

```bash
python scripts/_build_study_case_rainfall.py --check
python -m pytest tests/test_prepare_case_study_data.py -q
```

See [case_studies/README.md](https://github.com/tayerthiaggo/hydroseason/blob/main/case_studies/README.md)
for full data provenance and licensing.
