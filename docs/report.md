# Example Report

HydroSeason can export a self-contained interactive HTML report with the season
timeline, data-quality overview, aggregated monthly rainfall, annual Wet/Dry totals, STL
diagnostics, algorithm diagnostics, and per-hydrological-year metrics.

[Open the full interactive example report](examples/hydroseason_report.html){ .md-button .md-button--primary }

![HydroSeason example report preview](assets/images/hydroseason-report-preview.png)

## Embedded Preview

The embedded report below is the same standalone HTML file produced by
`generate_html_report(...)` from the bundled example rainfall dataset.

<iframe
  src="../examples/hydroseason_report.html"
  title="HydroSeason example report"
  style="width: 100%; min-height: 760px; border: 1px solid #CFD8DC; border-radius: 6px; background: white;"
  loading="lazy">
</iframe>

## Understanding the Report Structure

The generated HTML report contains several interactive sections to inspect and visualize the delineation results:

### 1. Interactive Season Timeline
Shows the raw monthly rainfall time-series with color-coded markers for each month's designation:
- **Wet (Blue)**: Peak wet months and valid absorbed shoulders.
- **Dry (Orange)**: Baseline dry months and non-absorbing shoulder breaks.
- **Unclassified (Gray)**: Only shown for non-seasonal records where no seasonal baseline exists.
- **Hydrological Year Boundaries (Vertical Dashed Lines)**: Mark the start of each dynamic hydrological year (delineated at the onset of the wet season).

### 2. Climatology & Fixed Season Dashboard
Displays the long-term 12-month calendar climatology of the station. This defines the fixed seasonal baseline: the core wet months, the fixed hydrological start month, and the thresholds used for the dynamic season passes.

### 3. Seasonality Strength & Regime Classification
Summarizes the mathematical indicators of seasonality:
- **Walsh-Lawler Seasonality Index (SI)**: Relies on the distribution of monthly means. Values close to 0 denote uniform rainfall; close to 1 denote extremely seasonal rainfall.
- **STL Strength ($F_S$)**: Measures how much of the variation is explained by seasonal patterns vs. random/residual noise.
- **Regime Classification**:
  - `seasonal`: Strong seasonal pattern (dynamic pipeline executes).
  - `borderline`: Moderate seasonality (fixed climatology defaults are used).
  - `non_seasonal`: Uniform rainfall (all months labeled unclassified).

### 4. Data Quality & Imputation Report
Provides validation statistics for transparency:
- **Missing months**: Count of missing months in the input data.
- **Imputed months**: Number of months filled using the calendar-month climatological mean.
- **Confidence Rating**:
  - **High confidence**: No missing data or minimal successful imputations (missing fraction ≤ 2%).
  - **Medium confidence**: Up to 5% missing data successfully imputed.
  - **Low confidence**: Over 5% missing data, large consecutive missing gaps, or near-constant/degenerate input series. A warning card will list specific validation warnings.
