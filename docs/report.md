# Example Report

HydroSeason exports self-contained interactive HTML report with season timeline, data-quality overview, aggregated monthly rainfall, annual Wet/Dry totals, STL diagnostics, algorithm diagnostics, and per-hydrological-year metrics.

[Open the full interactive example report](examples/hydroseason_report.html){ .md-button .md-button--primary }

![HydroSeason example report preview](assets/images/hydroseason-report-preview.png)

## Embedded Preview

Embedded report below is same standalone HTML produced by `generate_html_report(...)` from bundled example rainfall dataset.

<iframe
  src="../examples/hydroseason_report.html"
  title="HydroSeason example report"
  style="width: 100%; min-height: 760px; border: 1px solid #CFD8DC; border-radius: 6px; background: white;"
  loading="lazy">
</iframe>

## Understanding the Report Structure

Generated HTML report contains several interactive sections:

### 1. Interactive Season Timeline
Raw monthly rainfall time-series with color-coded markers:
- **Wet (Blue)**: Peak wet months and valid absorbed shoulders.
- **Dry (Orange)**: Baseline dry months and non-absorbing shoulder breaks.
- **Unclassified (Gray)**: Only for non-seasonal records without seasonal baseline.
- **Hydrological Year Boundaries (Vertical Dashed Lines)**: Mark start of each dynamic hydrological year.

### 2. Climatology & Fixed Season Dashboard
Long-term 12-month calendar climatology defining fixed seasonal baseline: core wet months, fixed hydrological start month, thresholds for dynamic season passes.

### 3. Seasonality Strength & Regime Classification
Mathematical seasonality indicators:
- **Walsh-Lawler Seasonality Index (SI)**: Distribution of monthly means. Near 0 = uniform; near 1 = extremely seasonal.
- **STL Strength ($F_S$)**: How much variation explained by seasonal patterns vs. residual noise.
- **Regime Classification**:
  - `seasonal`: Strong seasonal pattern (dynamic pipeline executes).
  - `borderline`: Moderate seasonality (fixed climatology defaults used).
  - `non_seasonal`: Uniform rainfall (all months labelled unclassified).

### 4. Data Quality & Imputation Report
Validation statistics:
- **Missing months**: Count of missing months in input.
- **Imputed months**: Months filled using calendar-month climatological mean.
- **Confidence Rating**:
  - **High confidence**: No missing data or minimal imputations (missing fraction ≤ 2%).
  - **Medium confidence**: Up to 5% missing data successfully imputed.
  - **Low confidence**: Over 5% missing data, large consecutive gaps, or near-constant/degenerate input series.
