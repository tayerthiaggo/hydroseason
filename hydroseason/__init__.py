"""HydroSeason: rainfall-based hydrological wet/dry season delineation."""

# Register the pandas DataFrame accessor (df.hydroseason.classify() etc.)
from . import accessor as _accessor  # noqa: F401

from .config import (
    AlgorithmConfig,
    FetchConfig,
    InputConfig,
    OutputConfig,
    RunConfig,
    ValidationConfig,
    load_config,
)
from .dynamic_season import (
    harmonize_with_zero_preservation,
    refine_season_tails,
    segment_main_wet_season_fixed_threshold,
)
from .fixed_season import (
    CircularStats,
    circular_climatology,
    circular_stats,
    hydro_year_start_after_min_month,
    hydro_year_start_driest_6_months,
    identify_fixed_hydro_year,
)
from .hydro_year import (
    assign_fixed_hydro_year,
    assign_hydro_year,
    assign_hydro_years,
)
from .metrics import (
    classify_drought,
    classify_year_spi,
    compute_annual_spi_categories,
    compute_end_dry_metrics,
    compute_season_metrics,
    compute_zero_flow_months,
)
from .pipeline import (
    DiagnosticsReport,
    PipelineArtifacts,
    classify,
    delineate_rainfall,
    delineate_monthly_dataframe,
    run_rainfall,
    run_pipeline,
    run_pipeline_from_csv,
)
from .seasonality import (
    SeasonalityResult,
    classify_regime_from_stl,
    classify_regime_with_rainfall_si,
    detect_seasonality_regime,
    monthly_climatology,
    stl_seasonality_strength,
    walsh_lawler_seasonality_index,
)
from .validate import ValidationReport, validate_monthly_input
from .fetch import (
    get_monthly_silo_rainfall,
    get_monthly_total_precip,
    get_monthly_variable,
    load_vector,
)
from .io import read_bom_monthly, read_rainfall, read_silo

__all__ = [
    # config
    "RunConfig", "InputConfig", "OutputConfig", "AlgorithmConfig",
    "ValidationConfig", "FetchConfig", "load_config",
    # validation
    "validate_monthly_input", "ValidationReport",
    # seasonality
    "detect_seasonality_regime", "SeasonalityResult",
    "stl_seasonality_strength", "walsh_lawler_seasonality_index",
    "classify_regime_from_stl", "classify_regime_with_rainfall_si",
    "monthly_climatology",
    # fixed season
    "circular_climatology", "circular_stats", "CircularStats",
    "identify_fixed_hydro_year",
    "hydro_year_start_after_min_month", "hydro_year_start_driest_6_months",
    # dynamic season
    "harmonize_with_zero_preservation",
    "segment_main_wet_season_fixed_threshold",
    "refine_season_tails",
    # hydro year
    "assign_hydro_year", "assign_fixed_hydro_year", "assign_hydro_years",
    # metrics
    "compute_season_metrics", "compute_end_dry_metrics",
    "compute_zero_flow_months",
    "compute_annual_spi_categories", "classify_drought", "classify_year_spi",
    # pipeline
    "classify", "delineate_monthly_dataframe", "delineate_rainfall",
    "run_rainfall",
    "run_pipeline_from_csv", "run_pipeline",
    "PipelineArtifacts", "DiagnosticsReport",
    # fetch / io
    "get_monthly_variable", "get_monthly_total_precip",
    "get_monthly_silo_rainfall",
    "load_vector",
    "read_silo", "read_bom_monthly", "read_rainfall",
]

# Plot helpers (optional dep: plotly)
try:
    from .plot import (
        plot_annual_metrics,
        plot_dashboard,
        plot_diagnostics_table,
        plot_imputation_overview,
        plot_monthly_climatology,
        plot_season_timeline,
        plot_stl_decomposition,
        PLOTLY_CONFIG,
        show,
    )
    __all__ += [
        "plot_season_timeline",
        "plot_monthly_climatology",
        "plot_stl_decomposition",
        "plot_annual_metrics",
        "plot_dashboard",
        "plot_diagnostics_table",
        "plot_imputation_overview",
        "PLOTLY_CONFIG",
        "show",
    ]
except ImportError:
    pass  # plotly not installed

# Report helpers (optional dep: plotly + ipython)
try:
    from .report import display_summary, export_bundle, generate_html_report
    __all__ += ["display_summary", "generate_html_report", "export_bundle"]
except ImportError:
    pass  # plotly not installed
