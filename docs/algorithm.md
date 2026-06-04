# Algorithm

HydroSeason implements a monthly, rainfall-driven workflow for dynamic wet/dry season and hydrological-year delineation. The current package generalises the workflow described in the Tayer et al. (2026) supplementary methodology and adds validation, regime detection, diagnostics, Plotly reporting, and a reusable API.

> [!NOTE]
> See [Methods & Workflow](methods.md) for conceptual background and a high-level overview of the pipeline logic.

## Pipeline Stages

1. Validate monthly input.
   Dates, years, months, duplicate records, missing values, and short gaps are normalised before analysis. Consecutive zero-value months are preserved so dry periods are not smoothed away.

2. Detect the seasonal regime.
   STL decomposition estimates seasonal strength, `F_S`. The Walsh-Lawler Seasonality Index can promote borderline rainfall records to `seasonal` when the monthly climatology is strongly concentrated.
   The previous KMeans silhouette report is retained only as an opt-in legacy diagnostic (`report_kmeans_silhouette=True`).

3. Build a fixed seasonal baseline.
   The default method is circular climatology, which labels a 12-month climatology as Wet/Dry and identifies the fixed hydrological-year start month. The earlier k-means baseline is still available with `method="kmeans"`.

4. Delineate dynamic Wet/Dry seasons.
   For seasonal records, HydroSeason smooths the monthly series while preserving zero months, finds the main wet-season core in each fixed hydrological year, and refines wet-season tails with raw-rainfall, site-scaled, and month-aware eligibility gates. Shoulder months can be absorbed when they are contiguous with a real wet core, exceed the rainfall/climatology gates, are unusually wet for their calendar month, and are not extreme positive STL-residual anomalies.

5. Assign hydrological years and metrics.
   Wet-season onsets define dynamic hydrological-year boundaries. The result uses the ending-year convention, so a hydrological year spanning November 1986 to October 1987 is labelled `1987`.


## Regime Thresholds

| STL strength `F_S` | Walsh-Lawler SI | Final regime |
| --- | --- | --- |
| `>= 0.60` | any | `seasonal` |
| `0.30` to `< 0.60` | `>= 0.80` | `seasonal` when `rainfall_si_override=True` |
| `0.30` to `< 0.60` | `< 0.80` | `borderline` |
| `< 0.30` | any | `non_seasonal` |

The `regime_source` diagnostic records whether the final regime came from STL alone (`stl`) or from the Walsh-Lawler promotion (`rainfall_si_override`).

## Hydrological Year Boundaries

Dynamic hydrological years are anchored to accepted dry-to-wet transitions. The `onset_window_months` parameter prevents mid-year wet pulses from creating spurious new hydrological years by only accepting onsets close to the climatological start month.

By default, `smooth_window`, `min_core_length`, and `onset_window_months` are adaptive. HydroSeason resolves them from the circular concentration `R` and the bimodality flag: sharp unimodal regimes keep the conservative 3-month smoothing and +/-1-month onset filter, diffuse regimes get a wider smoothing/core gate, and bimodal or uniform regimes disable the single-anchor onset filter. The fixed circular Wet/Dry baseline also adapts its unimodal Wet width from `R`: sharp regimes use 3 Wet months, moderate regimes use 5, and diffuse regimes use 7.

By default, tail guardrails use a rolling recent-normal climatology
(`climatology_window="rolling"`, 10 trailing fixed hydrological years). For each
fixed hydrological year, HydroSeason recomputes local wet months, local tail
floors, and local month-aware shoulder floors from the recent window. This lets
the workflow follow medium-term climate shifts without letting the oldest part
of a long record dominate current conditions.

The 10-year window is protected by a persistence guard. A locally labelled Wet
month is only treated as a stable recent Wet month when at least 60% of observed
years in the rolling window exceed the local tail floor
(`climatology_min_wet_year_fraction=0.60`). Months that fail this persistence
check use a stricter global tail floor for trimming smoothed Wet cores, while
month-aware quantile gates remain available for true shoulder extension. This
prevents one-off wet months, drought-cluster artefacts, or decadal noise from
becoming a new wet season.

If the local window has fewer than five observed values per calendar month, it
falls back to the full-record climatology and records the fallback count in
diagnostics. Records shorter than two rolling windows use global guardrails to
avoid overfitting short datasets.
When rolling guardrails are active and `onset_window_months="auto"`, the onset
window is widened to 3 months so newly shifted Wet onsets are not rejected for
being slightly far from the old whole-record start month, while still protecting
against out-of-season noise.

Before extension, positive raw-rainfall floors are applied inside smoothed Wet
runs. Below-floor months become Dry breaks, and tiny fragments shorter than the
resolved core-length gate are dissolved only when they touch an interior low-floor
break by default. This prevents a centred smoother from carrying low-rainfall
months into the Wet season without deleting genuinely weak baseline Wet months.
Set `require_low_floor_break_for_pruning=False` to prune all short out-of-season
fragments.

Tail refinement uses four independent shoulder-eligibility checks:

| Gate | Purpose |
| --- | --- |
| Rainfall threshold | Candidate shoulder rainfall must meet the stricter of the second-pass non-zero rainfall quantile and the first-pass tail floor. |
| Climatology floor | Candidate rainfall must exceed a fraction of the site's own wet-month climatological median. This prevents arid records from absorbing trivial mm-scale events. |
| Month-aware floor | Candidate rainfall must also meet the configured calendar-month quantile for that site (`shoulder_month_quantile`, default `0.60`). This keeps ordinary dry-season pulses out while allowing above-normal build-up or recession shoulders. Imputed months are excluded when there are enough observed values for that calendar month; for low-confidence records with missing/imputed data, the month-aware floor is disabled and the diagnostics record `disabled_low_confidence`. |
| STL-residual threshold | Candidate rainfall must not be an extreme positive STL residual. This keeps isolated storm anomalies from being treated as seasonal shoulders. |

When an accepted onset is absent for too long, `long_period_threshold` and
`fallback_month` can recover a real Wet onset that was filtered out by the
onset window. HydroSeason does not insert hydrological-year boundaries inside
an ongoing Dry season.

## Non-Seasonal and Borderline Records

For `non_seasonal` records, HydroSeason returns `SeasonType="Unclassified"` and uses calendar-year hydrological labels.

For `borderline` records that are not promoted by the Walsh-Lawler SI, HydroSeason uses the fixed monthly climatology as a conservative Wet/Dry fallback instead of applying the full dynamic segmentation.
