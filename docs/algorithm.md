# Algorithm

HydroSeason implements monthly, rainfall-driven workflow for dynamic wet/dry season and hydrological-year delineation. Generalises Tayer et al. (2026) supplementary methodology; adds validation, regime detection, diagnostics, Plotly reporting, reusable API.

> [!NOTE]
> See [Methods & Workflow](methods.md) for conceptual background and high-level pipeline overview.

## Pipeline Stages

1. Validate monthly input.
   Dates, years, months, duplicates, missing values, short gaps normalised. Consecutive zero-value months preserved so dry periods not smoothed away.

2. Detect seasonal regime.
   STL decomposition estimates seasonal strength `F_S`. Walsh-Lawler Seasonality Index can promote borderline records to `seasonal` when monthly climatology strongly concentrated.
   KMeans silhouette report retained as opt-in legacy diagnostic (`report_kmeans_silhouette=True`).

3. Build fixed seasonal baseline.
   Default: circular climatology — labels 12-month climatology as Wet/Dry, identifies fixed hydrological-year start month. k-means baseline available via `method="kmeans"`.

4. Delineate dynamic Wet/Dry seasons.
   For seasonal records: smooth monthly series while preserving zero months, find main wet-season core per fixed hydrological year, refine wet-season tails with raw-rainfall, site-scaled, month-aware eligibility gates. Shoulder months absorbed when contiguous with real wet core, exceed rainfall/climatology gates, unusually wet for calendar month, not extreme positive STL-residual anomalies.

5. Assign hydrological years and metrics.
   Wet-season onsets define dynamic hydrological-year boundaries. Ending-year convention: hydrological year spanning November 1986–October 1987 labelled `1987`.


## Regime Thresholds

| STL strength `F_S` | Walsh-Lawler SI | Final regime |
| --- | --- | --- |
| `>= 0.60` | any | `seasonal` |
| `0.30` to `< 0.60` | `>= 0.80` | `seasonal` when `rainfall_si_override=True` |
| `0.30` to `< 0.60` | `< 0.80` | `borderline` |
| `< 0.30` | any | `non_seasonal` |

`regime_source` records whether final regime came from STL alone (`stl`) or Walsh-Lawler promotion (`rainfall_si_override`).

## Hydrological Year Boundaries

Dynamic hydrological years anchored to accepted dry-to-wet transitions. `onset_window_months` prevents mid-year wet pulses from creating spurious new hydrological years by only accepting onsets near climatological start month.

By default, `smooth_window`, `min_core_length`, and `onset_window_months` are adaptive — resolved from circular concentration `R` and bimodality flag: sharp unimodal regimes keep 3-month smoothing and ±1-month onset filter, diffuse regimes get wider smoothing/core gate, bimodal/uniform regimes disable single-anchor onset filter. Fixed circular Wet/Dry baseline also adapts unimodal Wet width from `R`: sharp regimes use 3 Wet months, moderate use 5, diffuse use 7.

By default, tail guardrails use rolling recent-normal climatology
(`climatology_window="rolling"`, 10 trailing fixed hydrological years). Per fixed hydrological year, HydroSeason recomputes local wet months, local tail floors, local month-aware shoulder floors. Lets workflow follow medium-term climate shifts without oldest record dominating.

10-year window protected by persistence guard. Locally labelled Wet month treated as stable recent Wet only when ≥60% of observed years in rolling window exceed local tail floor
(`climatology_min_wet_year_fraction=0.60`). Months failing this check use stricter global tail floor for trimming smoothed Wet cores; month-aware quantile gates remain for true shoulder extension. Prevents one-off wet months, drought-cluster artefacts, decadal noise from becoming new wet season.

If local window has fewer than five observed values per calendar month, falls back to full-record climatology and records fallback count in diagnostics. Records shorter than two rolling windows use global guardrails to avoid overfitting.
When rolling guardrails active and `onset_window_months="auto"`, onset window widened to 3 months so newly shifted Wet onsets not rejected for being slightly far from old whole-record start month, while still protecting against out-of-season noise.

HydroSeason is intentionally date-range sensitive — guardrails, fixed baseline months, adaptive onset settings recomputed from supplied record. Trimming long series to shorter subset can preserve same labels across overlapping middle years, but can also change edge-year Wet onsets or switch from rolling guardrails to `global_short_record`.
When subset begins inside already-active Wet season, first visible Wet month is not proof that true onset occurred inside subset.

Before extension, positive raw-rainfall floors applied inside smoothed Wet runs. Below-floor months become Dry breaks; tiny fragments shorter than resolved core-length gate dissolved only when touching interior low-floor break by default. Prevents centred smoother from carrying low-rainfall months into Wet season without deleting genuinely weak baseline Wet months.
Set `require_low_floor_break_for_pruning=False` to prune all short out-of-season fragments.

Tail refinement uses four independent shoulder-eligibility checks:

| Gate | Purpose |
| --- | --- |
| Rainfall threshold | Candidate shoulder rainfall must meet stricter of second-pass non-zero rainfall quantile and first-pass tail floor. |
| Climatology floor | Candidate rainfall must exceed fraction of site's own wet-month climatological median. Prevents arid records from absorbing trivial mm-scale events. |
| Month-aware floor | Candidate rainfall must meet configured calendar-month quantile for site (`shoulder_month_quantile`, default `0.60`). Keeps ordinary dry-season pulses out while allowing above-normal build-up/recession shoulders. Imputed months excluded when enough observed values; for low-confidence records, month-aware floor disabled and diagnostics record `disabled_low_confidence`. |
| STL-residual threshold | Candidate rainfall must not be extreme positive STL residual. Keeps isolated storm anomalies from being treated as seasonal shoulders. |

When accepted onset absent too long, `long_period_threshold` and `fallback_month` can recover real Wet onset filtered by onset window. HydroSeason does not insert hydrological-year boundaries inside ongoing Dry season.

## Non-Seasonal and Borderline Records

For `non_seasonal` records, returns `SeasonType="Unclassified"` and calendar-year hydrological labels.

For `borderline` records not promoted by Walsh-Lawler SI, uses fixed monthly climatology as conservative Wet/Dry fallback instead of full dynamic segmentation.
