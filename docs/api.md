# API Reference

The reference below is generated from the package docstrings with `mkdocstrings`.

## Pipeline

::: hydroseason.pipeline
    options:
      members:
        - PipelineArtifacts
        - DiagnosticsReport
        - delineate_monthly_dataframe
        - delineate_rainfall
        - run_pipeline_from_csv
        - run_rainfall
        - classify

## Rainfall IO

::: hydroseason.io
    options:
      members:
        - read_rainfall
        - read_silo
        - read_bom_monthly

## Metrics

::: hydroseason.metrics
    options:
      members:
        - compute_season_metrics
        - compute_end_dry_metrics
        - compute_zero_flow_months
        - compute_annual_spi_categories
        - classify_drought
        - classify_year_spi

## Plotting

::: hydroseason.plot
    options:
      members:
        - plot_season_timeline
        - plot_monthly_climatology
        - plot_stl_decomposition
        - plot_annual_metrics
        - plot_dashboard
        - plot_diagnostics_table
        - plot_imputation_overview
        - show

## Reports

::: hydroseason.report
    options:
      members:
        - display_summary
        - generate_html_report
        - export_bundle

## Fetch

::: hydroseason.fetch
    options:
      members:
        - load_vector
        - get_monthly_variable
        - get_monthly_silo_rainfall
        - get_monthly_total_precip