"""HydroSeason: remote-sensing-first hydro-year and season detection from monthly surface-water extent."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from ._catchment import CatchmentAnalysis, analyze_catchment
from ._events import WaterEventResult, extract_water_events
from ._regime import Regime, WaterRegimeAssessment, assess_water_regime
from .hydro_year import (
    HydroYearConfig,
    detect_hydrological_years,
    label_hydrological_months,
    monthly_water_extent,
    suggest_hydro_year_config,
)
from .hydrological_state import (
    DynamicHydroYearConfig,
    HydrologicalStateResult,
    SeasonalPatternResult,
    aggregate_basin_monthly_extent,
    analyze_hydrological_state,
    classify_annual_surface_water_condition,
    classify_seasonal_pattern,
    compute_monthly_surface_water_condition,
    detect_dynamic_hydrological_years,
    suggest_dynamic_hydro_year_config,
)
from .io import (
    WetPlanningFootprint,
    WOfSCacheHandle,
    acquire_wofs_cache,
    build_wet_planning_footprint,
    complete_monthly_axis,
    load_aoi,
    load_extent_csv,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_wofs_from_stac,
    load_wofs_monthly_extent,
    open_completed_dual_extent_counts,
    open_completed_mask_cache,
    open_wo_statistics,
    verify_cache_footprints,
)
from .report import CatchmentReportPaths, generate_catchment_report, generate_html_report
from .workflow import HydroSeasonRunResult, run_hydroseason

try:
    __version__ = _pkg_version("hydroseason")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.1.0"

__all__ = [
    "__version__", "HydroYearConfig", "detect_hydrological_years",
    "label_hydrological_months", "monthly_water_extent", "suggest_hydro_year_config",
    "load_aoi", "load_wofs_from_stac", "load_wofs_monthly_extent", "load_monthly_masks",
    "load_monthly_masks_zarr", "load_extent_csv", "complete_monthly_axis",
    "acquire_wofs_cache", "WOfSCacheHandle", "open_wo_statistics", "open_completed_mask_cache",
    "verify_cache_footprints", "open_completed_dual_extent_counts",
    "build_wet_planning_footprint", "WetPlanningFootprint",
    "generate_html_report", "CatchmentReportPaths", "generate_catchment_report",
    "DynamicHydroYearConfig", "HydrologicalStateResult",
    "SeasonalPatternResult", "aggregate_basin_monthly_extent",
    "analyze_hydrological_state", "classify_annual_surface_water_condition",
    "classify_seasonal_pattern", "compute_monthly_surface_water_condition",
    "detect_dynamic_hydrological_years", "suggest_dynamic_hydro_year_config",
    "Regime", "WaterRegimeAssessment", "assess_water_regime",
    "WaterEventResult", "extract_water_events",
    "CatchmentAnalysis", "analyze_catchment",
    "HydroSeasonRunResult", "run_hydroseason",
]
