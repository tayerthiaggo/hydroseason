# Report CSV columns

`generate_catchment_report` writes four CSVs beside the HTML report. These
files are the default user interface: dates are named explicitly, the
monthly table contains the flags needed to filter a timeline, and the
hydrological-year table contains the three boundary markers and their quality
signals. Internal condition-model and detector diagnostics are deliberately
not repeated in every row of the default CSVs.

The HTML report still receives the complete internal frames. The
`build_monthly_export`, `build_hydro_years_export`, `build_events_export`, and
`build_summary_export` helpers remain available when a diagnostic table is
needed programmatically.

For monthly WOfS acquired through the default high-level workflow, the fixed
scientific footprint is `(DEA Multi-Year count_wet > 0) AND user AOI`.
`n_aoi` is that historical mask's constant pixel count,
`invalid_pct = 100 * n_invalid / n_aoi`, and pixels outside the mask do not
affect quality percentages. `extent_pct = 100 * n_water / n_valid` uses valid
observations inside the same mask. The separate planning superset affects only
remote reads. Date and event selection remains percentage-based, and no area,
pixel-area, or km2 columns are added.

## Monthly timeline (`<stem>_monthly.csv`)

One row is retained for every input month. `date` is the first day of the
month; percentages are 0--100.

| Column | Meaning |
|---|---|
| `date` | Month represented by the row. |
| `extent_pct` | Observed surface-water extent percentage. |
| `invalid_pct` | Percentage of the fixed historical-mask pixels that were invalid in that month; invalid pixels outside the mask are excluded. |
| `max_invalid_pct` | User-configurable per-month invalid-pixel limit over the historical-mask denominator, used when determining `usable_month`. |
| `baseline_extent_pct` | Record baseline extent used by both wet-event and low-spell detection. |
| `usable_month` | Whether the month is admitted by the configured quality policy. In the review-oriented `flag` workflow, finite partial-invalid months remain usable and are flagged by `quality_state`. |
| `quality_state` | Quality label for the month (`usable`, `low`, `missing`, or `unknown`). |
| `hy_year` | Hydrological-year identifier, blank when the selected route does not define years. |
| `confidence` | Hydrological-year confidence level (`high`, `medium`, `low`), blank when outside a resolved hydrological year. |
| `phase` | Phase label according to the selected `phase_scheme` (`two_phase` [default]: `rising`/`receding`, split at the observed peak; deprecated `four_phase` is an alias for the same labels; `none`: `unspecified`). |
| `phase_status` | Phase provenance (`ok`, `provisional`, `unresolved_cycle`, `outside_cycle`, `unusable`, or `disabled`). |
| `is_hy_peak` | `True` for the detected annual maximum month. |
| `is_hy_mid_dry` | `True` for the temporal mid-dry marker. |
| `is_hy_trough` | `True` for the detected annual minimum/trough month. |
| `in_wet_event` / `wet_event_id` | Whether the month belongs to a wet event and its identifier. |
| `in_low_spell` / `low_spell_id` | Whether the month belongs to a low-extent spell and its identifier. |
| `regime` / `route` | The regime decision and analysis route applied to the record. |
| `decision_policy` | Decision policy identifier controlling public routing (`established_0_2_0`). |
| `rainfall_mm` / `rain_anomaly_mm` | Optional supplied-CSV or SILO rainfall context, written only when rainfall loads successfully. The anomaly is rainfall minus the median for the same calendar month. These fields never drive regime routing, boundaries, phases, events, or low spells. |

## Hydrological years (`<stem>_hydro_years.csv`)

This file is header-only for `event_characterisation` and other routes that do
not define hydrological years. Date columns are month starts.

| Column | Meaning |
|---|---|
| `catchment` | User-supplied AOI name, or `HydroSeason results` when the name is blank. |
| `hy_year` | Hydrological-year identifier. |
| `start_date` / `end_date` | Closed interval used for that hydrological year. |
| `peak_date` / `mid_dry_date` / `trough_date` | Wet maximum, mid-dry, and dry minimum markers. |
| `peak_extent_pct` / `mid_dry_extent_pct` / `trough_extent_pct` | Extent observed at each marker. |
| `peak_invalid_pct` / `mid_dry_invalid_pct` / `trough_invalid_pct` | Invalid-pixel percentage at each marker. High values make the marker provisional/low confidence. |
| `drawdown_pct` | Peak-to-trough extent range when available. |
| `confidence` | Overall confidence assigned to the row. |
| `status` / `boundary_status` | Result status and whether boundaries are exact, provisional, or otherwise constrained. |
| `boundary_basis` | Whether the boundary was detected per year or imposed from a fixed climatological window. |
| `regime` / `route` | Record-level routing metadata. |
| `timing_status` | Aggregate timing identifiability for the row (`point`, `interval`, or `unresolved`): the weaker of `peak_timing_status` and `trough_timing_status`. `boundary_status` describes selection/data admissibility; `timing_status` describes temporal identifiability -- the two are independent. |
| `peak_timing_status` / `trough_timing_status` | Whether the peak/trough resolves to an exact month (`point`), a bounded interval (`interval`), or cannot be resolved (`unresolved`). |
| `peak_date` / `trough_date` | Populated only when the corresponding `*_timing_status` is `point`; blank for `interval` or `unresolved` so a broad plateau or diffuse peak is never presented as a fabricated exact date. |
| `peak_interval_start_date` / `peak_interval_end_date` / `trough_interval_start_date` / `trough_interval_end_date` | Populated whenever the corresponding `*_timing_status` is `interval` (bounds of the defensible interval), also populated for `point` (a single-month interval). Blank for `unresolved`. |
| `detectability_floor_pp` | The record's detectability floor for that cycle, in percentage points: `max(measurement_tolerance_pct, robust_noise_pp, peak_resolution_pp, trough_resolution_pp, machine epsilon)`. |
| `amplitude_to_floor_ratio` | That cycle's amplitude divided by `detectability_floor_pp`; `0.0` when the amplitude is at or below the floor. |

## Wet events (`<stem>_wet_event.csv`)

Wet events are contiguous runs above a robust, record-specific wet threshold.
The default detector uses a noise-based threshold with hysteresis: an event
opens above `baseline + 3 × noise` and remains open while above
`baseline + 1 × noise`. Unusable months close an event. The event table is
descriptive and is produced for every route, including aseasonal records.

| Column | Meaning |
|---|---|
| `event_id` | One-based event identifier. |
| `start_date` / `end_date` | First and last month in the event. |
| `duration_months` | Number of contiguous event months. |
| `baseline_extent_pct` | Record baseline extent used by the wet-event detector. |
| `peak_date` / `peak_extent_pct` | Month and extent of the event maximum. |
| `mean_extent_pct` | Mean extent during the event. |
| `magnitude_pp_months` | Sum of `(extent_pct - event_exit_threshold)` for event months, clipped at zero. It measures event size and persistence in percentage-points × months; it is not a volume or discharge estimate. |

## Low-extent spells (`<stem>_low_spells.csv`)

Low spells are independent of wet events. They are contiguous runs at or below
`baseline - 1 × noise` (or the configured quantile fallback), with a default
minimum duration of two months. They describe unusually low extent in this
record; they are not automatically a drought declaration.

| Column | Meaning |
|---|---|
| `low_spell_id` | One-based low-spell identifier. |
| `start_date` / `end_date` | First and last month in the spell. |
| `duration_months` | Number of contiguous low-extent months. |
| `baseline_extent_pct` | Record baseline extent used by the low-spell detector. |
| `min_extent_pct` | Minimum extent observed during the spell. |

## Summary information

The HTML report's internal one-row summary (also returned by
`CatchmentAnalysis.summary_row()`) includes the timing fields below. They are
not repeated in the compact four-CSV bundle, so downstream code that needs
them should use the analysis result or a full summary export.

| Field | Units / range | Null / zero semantics |
|---|---|---|
| `amplitude_snr` | Unitless, >=0 (possibly `inf`) | `0.0` for insufficient records. |
| `peak_timing_concentration`, `trough_timing_concentration` | Mean resultant length, 0–1 | `null` for insufficient records. |
| `peak_timing_concentration_ci_low`, `peak_timing_concentration_ci_high`, `trough_timing_concentration_ci_low`, `trough_timing_concentration_ci_high` | Unitless 0–1, 95% bootstrap bounds | `null` for insufficient records. |
| `peak_timing_uniformity_p`, `trough_timing_uniformity_p` | Kuiper probability 0–1 | `null` for insufficient records. |
| `peak_phase_iqr_months`, `trough_phase_iqr_months` | Circular months | `null` with fewer than four timing observations or an insufficient record; IQR is descriptive only. |
| `n_timing_years` | Non-negative integer **years** | `0` for insufficient records; it is not a count of months. Equals `n_peak_timing_years` -- it keeps its historical peak-derived meaning and is never silently redefined as a minimum. |
| `n_peak_timing_years`, `n_trough_timing_years` | Non-negative integer **years** | Count of calendar years whose peak/trough extremum is independently identifiable (not `unresolved`). The conservative `min()` of the two is used only in the route gate, and is not itself a published field. |
| `n_zero_months` | Non-negative integer **months** | Total months with exact-zero observed extent among usable months. Descriptive only; it never enters a route or timing decision. |
| `zero_month_fraction` | Unitless, 0–1 | Fraction of usable months that are exact zero. |
| `n_whole_zero_years` | Non-negative integer **years** | Count of years whose usable months are all exact zero. A whole-zero year still contributes to dry-duration and event summaries; it contributes no peak or trough timing observation. |
| `pixel_support_status` | `"available"` or `"unavailable"` | Whether the record carries pixel counts (`n_water`/`n_valid`/`n_invalid`/`n_aoi`). Percentage-only inputs always report `"unavailable"`, and their `min_peak_water_pixels` threshold is not consulted. |
| `timing_evidence` | `"supported"`, `"insufficient"`, or `"unsupported"` | Record-level timing verdict: `insufficient` when `min(n_peak_timing_years, n_trough_timing_years) < min_informative_years`; `unsupported` when the established seasonality/uniformity evidence rejects an annual cycle (today this is reachable only when `regime == "aseasonal"`); otherwise `supported`. |

`R` and confidence intervals are rounded to three decimal places in the
summary; IQR is rounded to two decimal places. The report uses peak `R` for
regime evidence and trough `R` for per-year boundary support. It does not use
IQR as a hidden decision threshold.

Per-AOI summary CSVs are not part of the current bundle. Routing, counts,
quality settings, and interpretation belong in the HTML report. The checked
multi-catchment case study keeps its aggregate
`case_studies/results/main/summary.csv` for documentation tables; its extent
marker is named `water_extent_peak_month`.

`max_invalid_pct` is always a configurable per-month invalid-pixel threshold
over the historical-mask denominator, not a percentage of invalid months.

## AOI naming

The `name` argument is optional. Use it for a catchment name, station name, or
any label that identifies a custom AOI. It does not have to be a whole
catchment. If it is omitted or blank, reports and metadata use
`HydroSeason results`, and files use the safe stem `hydroseason-results`.
