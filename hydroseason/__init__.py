"""HydroSeason: remote-sensing-first hydro-year and season detection from monthly surface-water extent."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .hydro_year import (
    HydroYearConfig,
    detect_hydrological_years,
    label_hydrological_months,
    monthly_water_extent,
)
from .io import (
    complete_monthly_axis,
    load_aoi,
    load_extent_csv,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_wofs_from_stac,
)
from .report import generate_html_report

try:
    __version__ = _pkg_version("hydroseason")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.1.0"

__all__ = [
    "__version__",
    "HydroYearConfig",
    "detect_hydrological_years",
    "label_hydrological_months",
    "monthly_water_extent",
    "load_aoi",
    "load_wofs_from_stac",
    "load_monthly_masks",
    "load_monthly_masks_zarr",
    "load_extent_csv",
    "complete_monthly_axis",
    "generate_html_report",
]
