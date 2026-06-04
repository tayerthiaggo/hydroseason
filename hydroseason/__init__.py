"""HydroSeason: rainfall-based hydrological wet/dry season delineation."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

# Register the pandas DataFrame accessor (df.hydroseason.classify_rainfall() etc.)
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
from .fixed_season import (
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
)
from .pipeline import (
    DiagnosticsReport,
    PipelineArtifacts,
    classify_rainfall,
    classify_rainfall_df,
    classify_rainfall_from_file,
    run_pipeline,
)
from .seasonality import (
    SeasonalityResult,
    classify_regime_from_stl,
    classify_regime_with_rainfall_si,
    detect_seasonality_regime,
    mean_monthly_rainfall,
    stl_seasonality_strength,
    walsh_lawler_seasonality_index,
)
from .validate import ValidationReport, validate_monthly_input
from .fetch import (
    get_monthly_aoi_rainfall,
    get_monthly_chirps_rainfall,
    get_monthly_silo_rainfall,
    get_monthly_era5_rainfall,
    infer_default_fetch_source,
    load_vector,
)
from .io import read_rainfall

try:
    __version__ = _pkg_version("hydroseason")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.1.0"

# NOTE: algorithm building blocks (circular_climatology, circular_stats,
# CircularStats, segment_main_wet_season_fixed_threshold,
# harmonize_with_zero_preservation, refine_season_tails) are intentionally NOT
# re-exported here. Import them from their submodules
# (hydroseason.fixed_season, hydroseason.dynamic_season) if you need them.

__all__ = [
    "__version__",
    # --- Core entry points ---
    "classify_rainfall", "classify_rainfall_df", "classify_rainfall_from_file",
    "run_pipeline",
    "load_config",
    # --- Output types & config ---
    "PipelineArtifacts", "DiagnosticsReport",
    "SeasonalityResult", "ValidationReport",
    "RunConfig", "InputConfig", "OutputConfig", "AlgorithmConfig",
    "ValidationConfig", "FetchConfig",
    # --- Advanced: validation & seasonality diagnostics ---
    "validate_monthly_input",
    "detect_seasonality_regime",
    "stl_seasonality_strength", "walsh_lawler_seasonality_index",
    "classify_regime_from_stl", "classify_regime_with_rainfall_si",
    "mean_monthly_rainfall",
    # --- Advanced: hydrological year ---
    "identify_fixed_hydro_year",
    "hydro_year_start_after_min_month", "hydro_year_start_driest_6_months",
    "assign_hydro_year", "assign_fixed_hydro_year", "assign_hydro_years",
    # --- Advanced: metrics ---
    "compute_season_metrics", "compute_end_dry_metrics",
    "compute_annual_spi_categories", "classify_drought", "classify_year_spi",
    # --- Advanced: rainfall IO & AOI fetch ---
    "get_monthly_aoi_rainfall",
    "get_monthly_chirps_rainfall",
    "get_monthly_era5_rainfall",
    "get_monthly_silo_rainfall", "infer_default_fetch_source", "load_vector",
    "read_rainfall",
]

# --- Plotting & reporting (plotly in core) ---
try:
    from .plot import (
        plot_agg_monthly_rainfall,
        plot_annual_metrics,
        plot_dashboard,
        plot_diagnostics_table,
        plot_imputation_overview,
        plot_season_timeline,
        plot_stl_decomposition,
        show,
    )
    __all__ += [
        "plot_agg_monthly_rainfall",
        "plot_season_timeline",
        "plot_stl_decomposition",
        "plot_annual_metrics",
        "plot_dashboard",
        "plot_diagnostics_table",
        "plot_imputation_overview",
        "show",
    ]
except ImportError:
    pass  # plotly not installed

# Report helpers (plotly in core; IPython display support is optional at runtime)
try:
    from .report import display_summary, export_bundle, generate_html_report
    __all__ += ["display_summary", "generate_html_report", "export_bundle"]
except ImportError:
    pass  # plotly not installed

