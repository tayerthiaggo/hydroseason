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

## Monthly timeline (`<stem>_monthly.csv`)

One row is retained for every input month. `date` is the first day of the
month; percentages are 0--100.

| Column | Meaning |
|---|---|
| `date` | Month represented by the row. |
| `extent_pct` | Observed surface-water extent percentage. |
| `invalid_pct` | Percentage of pixels that were invalid in that month. |
| `max_invalid_pct` | Configured per-month invalid-pixel limit used when determining `usable_month`. |
| `baseline_extent_pct` | Record baseline extent used by both wet-event and low-spell detection. |
| `usable_month` | Whether the month is admitted by the configured quality policy. In the review-oriented `flag` workflow, finite partial-invalid months remain usable and are flagged by `quality_state`. |
| `quality_state` | Quality label for the month (`usable`, `low`, `missing`, or `unknown`). |
| `hy_year` | Hydrological-year identifier, blank when the selected route does not define years. |
| `phase` | Phase label when a hydrological-year phase model is available. Partial cycles are labelled provisionally; `unspecified` is reserved for months outside a resolvable cycle or routes without phases. |
| `phase_status` | Phase provenance (`ok`, `provisional`, `unresolved_cycle`, `outside_cycle`, `unusable`, or `disabled`). |
| `is_hy_peak` | `True` for the detected annual maximum month. |
| `is_hy_mid_dry` | `True` for the temporal mid-dry marker. |
| `is_hy_trough` | `True` for the detected annual minimum/trough month. |
| `in_wet_event` / `wet_event_id` | Whether the month belongs to a wet event and its identifier. |
| `in_low_spell` / `low_spell_id` | Whether the month belongs to a low-extent spell and its identifier. |
| `regime` / `route` | The regime decision and analysis route applied to the record. |
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

Per-AOI summary CSVs are not part of the current bundle. Routing, counts,
quality settings, and interpretation belong in the HTML report. The checked
multi-catchment case study keeps its aggregate
`case_studies/results/main/summary.csv` for documentation tables; its extent
marker is named `water_extent_peak_month`.

`max_invalid_pct` is always a per-month invalid-pixel threshold, not a
percentage of invalid months.

## AOI naming

The `name` argument is optional. Use it for a catchment name, station name, or
any label that identifies a custom AOI. It does not have to be a whole
catchment. If it is omitted or blank, reports and metadata use
`HydroSeason results`, and files use the safe stem `hydroseason-results`.
