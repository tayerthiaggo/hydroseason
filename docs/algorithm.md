# Algorithm

HydroSeason implements a monthly, rainfall-driven workflow for dynamic wet/dry season and hydrological-year delineation. The current package generalises the workflow described in the Tayer et al. (2026) supplementary methodology and adds validation, regime detection, diagnostics, Plotly reporting, and a reusable API.

## Pipeline Stages

1. Validate monthly input.
   Dates, years, months, duplicate records, missing values, and short gaps are normalised before analysis. Consecutive zero-value months are preserved so dry periods are not smoothed away.

2. Detect the seasonal regime.
   STL decomposition estimates seasonal strength, `F_S`. The Walsh-Lawler Seasonality Index can promote borderline rainfall records to `seasonal` when the monthly climatology is strongly concentrated.

3. Build a fixed seasonal baseline.
   The default method is circular climatology, which labels a 12-month climatology as Wet/Dry and identifies the fixed hydrological-year start month. The earlier k-means baseline is still available with `method="kmeans"`.

4. Delineate dynamic Wet/Dry seasons.
   For seasonal records, HydroSeason smooths the monthly series while preserving zero months, finds the main wet-season core in each fixed hydrological year, and refines wet-season tails with lower, site-scaled eligibility gates. Shoulder months can be absorbed when they are contiguous with a real wet core, exceed the rainfall/climatology gates, and are not extreme positive STL-residual anomalies.

5. Assign hydrological years and metrics.
   Wet-season onsets define dynamic hydrological-year boundaries. The result uses the ending-year convention, so a hydrological year spanning December 1986 to November 1987 is labelled `1987`.

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

By default, `smooth_window`, `min_core_length`, and `onset_window_months` are adaptive. HydroSeason resolves them from the circular concentration `R` and the bimodality flag: sharp unimodal regimes keep the conservative 3-month smoothing and +/-1-month onset filter, diffuse regimes get a wider smoothing/core gate, and bimodal or uniform regimes disable the single-anchor onset filter.

Tail refinement uses three independent shoulder-eligibility checks:

| Gate | Purpose |
| --- | --- |
| Rainfall threshold | Candidate shoulder rainfall must exceed the second-pass non-zero rainfall quantile. |
| Climatology floor | Candidate rainfall must exceed a fraction of the site's own wet-month climatological median. This prevents arid records from absorbing trivial mm-scale events. |
| STL-residual threshold | Candidate rainfall must not be an extreme positive STL residual. This keeps isolated storm anomalies from being treated as seasonal shoulders. |

When a clear onset is absent for too long, `long_period_threshold` and `fallback_month` preserve a continuous hydrological-year sequence.

## Non-Seasonal and Borderline Records

For `non_seasonal` records, HydroSeason returns `SeasonType="Unclassified"` and uses calendar-year hydrological labels.

For `borderline` records that are not promoted by the Walsh-Lawler SI, HydroSeason uses the fixed monthly climatology as a conservative Wet/Dry fallback instead of applying the full dynamic segmentation.