"""Public orchestrator: preview an AOI, resolve water input, then add rainfall.

``run_hydroseason`` ties together the modules that were designed to stay
decoupled from each other: it resolves whatever water source the caller
supplied (:mod:`hydroseason._workflow_input`), runs :func:`analyze_catchment`
exactly once -- the sole routing authority, rainfall-blind -- and only then
looks at rainfall at all. Rainfall is a strictly separate, best-effort branch:
loading a supplied CSV, fetching from SILO, and comparing against the
already-computed regime can each fail independently without taking the water
analysis or the report down with them. Every rainfall failure is recorded on
the result and surfaced as a ``UserWarning``; only water input, analysis, and
report-writing failures are fatal and propagate as exceptions. A supplied AOI
is loaded once before acquisition so its optional display context can be
previewed and reused for rainfall; context and preview failures only warn, but
an unloadable supplied AOI is fatal.

Rainfall is off by default (``fetch_rainfall=False``). A supplied
``rainfall_csv_path`` always takes precedence over ``fetch_rainfall=True``: if
both are given, SILO is never called.

A ``fetch_rainfall=True`` run whose environment cannot import the SILO
dependencies warns before the water step rather than after it, giving the
caller a chance to abort before spending hours on water acquisition. The
warning does not make ancillary rainfall fatal and does not change the water
analysis.

``progress`` is off by default. ``progress=True`` writes five numbered step
lines to standard error and switches on the per-calendar-year bar that
``load_wofs_monthly_extent`` already provides; passing a callable instead
delivers :class:`hydroseason._progress.ProgressEvent` objects and leaves the
nested bar off. Progress reporting never changes what a run computes.
"""
from __future__ import annotations

import warnings as py_warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

import pandas as pd

from ._aoi_context import AOIContext, build_aoi_context
from ._aoi_map import display_aoi_map
from ._catchment import CatchmentAnalysis, analyze_catchment
from ._diagnostics import missing_rainfall_dependencies
from ._progress import ProgressEvent, WorkflowProgress, resolve_progress_reporter
from ._rainfall import (
    align_monthly_rainfall,
    get_monthly_silo_rainfall,
    load_monthly_rainfall_csv,
    normalise_monthly_rainfall,
)
from ._regime_compare import RegimeComparison, compare_rainfall_to_extent_regime
from ._workflow_input import (
    DEFAULT_STAC_COLLECTION,
    DEFAULT_STAC_URL,
    WaterSourceKind,
    resolve_water_input,
)
from .io import load_aoi
from .report import CatchmentReportPaths, generate_catchment_report

RainfallStatus = Literal[
    "disabled", "provided", "fetched", "provided_failed", "fetch_failed"
]
RainfallSource = Literal["none", "csv", "silo"]


@dataclass(frozen=True)
class HydroSeasonRunResult:
    """Everything a single ``run_hydroseason`` call produced.

    ``analysis`` is always rainfall-blind, regardless of whether rainfall was
    requested or how it fared: the invariant this dataclass exists to make
    checkable is that ``analysis`` is identical whether or not rainfall was
    supplied at all.
    """

    extent: pd.DataFrame
    analysis: CatchmentAnalysis
    rainfall: pd.DataFrame | None
    rainfall_comparison: RegimeComparison | None
    rainfall_status: RainfallStatus
    rainfall_source: RainfallSource
    rainfall_error: str | None
    rainfall_comparison_error: str | None
    source_kind: WaterSourceKind
    warnings: tuple[str, ...]
    aoi_context: AOIContext | None
    artifacts: CatchmentReportPaths


def _warn(messages: list[str], message: str) -> None:
    messages.append(message)
    py_warnings.warn(message, UserWarning, stacklevel=3)


def _in_notebook_kernel() -> bool:
    """Return whether this process is running in a Jupyter kernel."""
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    shell = get_ipython()
    return shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell"


def _resolve_show_map(show_map: Literal["auto"] | bool) -> bool:
    if show_map == "auto":
        return _in_notebook_kernel()
    if type(show_map) is bool:
        return show_map
    raise ValueError("show_map must be 'auto', True, or False.")


def run_hydroseason(
    water_source=None,
    *,
    output_dir: str | Path,
    aoi=None,
    aoi_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    water_mask_variable: str | None = None,
    fetch_rainfall: bool = False,
    rainfall_csv_path: str | Path | None = None,
    stac_url: str = DEFAULT_STAC_URL,
    stac_collection: str = DEFAULT_STAC_COLLECTION,
    statistics_stac_url: str | None = None,
    cache_dir: str | Path | None = None,
    analysis_options: Mapping[str, Any] | None = None,
    report_title: str | None = None,
    report_subtitle: str | None = None,
    progress: bool | Callable[[ProgressEvent], None] = False,
    show_map: Literal["auto"] | bool = "auto",
    refresh_historical_mask: bool = True,
) -> HydroSeasonRunResult:
    """Resolve water input, analyze it once, then add rainfall as context.

    ``water_source`` follows :func:`hydroseason._workflow_input.resolve_water_input`:
    ``None`` fetches from DEA (requires ``aoi``, ``start_date``, ``end_date``),
    otherwise it may be a DataFrame, CSV path, NetCDF/Zarr path, or an
    xarray Dataset/DataArray of a canonical water mask.

    ``stac_url`` configures BOTH DEA searches the fetch path performs: the
    monthly ``ga_ls_wo_3`` search and the ``ga_ls_wo_fq_myear_3`` historical-
    statistics search that fixes this run's spatial denominator. Pass
    ``statistics_stac_url`` only to point the statistics search at a
    different service from the monthly one.

    Rainfall is entirely optional and never influences the water analysis:
    ``analyze_catchment`` runs exactly once, before any rainfall handling, on
    the resolved extent alone. If ``rainfall_csv_path`` is supplied it takes
    precedence over ``fetch_rainfall`` -- SILO is never called when a CSV is
    given. Any rainfall failure (missing/malformed CSV, SILO fetch failure,
    missing ``aoi`` for a fetch, or a comparison failure) is caught, recorded
    on the result (``rainfall_status``, ``rainfall_error``/
    ``rainfall_comparison_error``), and warned via ``UserWarning`` -- it never
    raises.
    """
    show_aoi_map = _resolve_show_map(show_map)
    messages: list[str] = []
    aoi_gdf = None
    aoi_context = None
    if aoi is not None:
        # Loading is deliberately fatal: callers that supplied an AOI expect it
        # to be valid even when their water source is already precomputed.
        aoi_gdf = load_aoi(aoi)
        try:
            aoi_context = build_aoi_context(aoi_gdf, display_name=aoi_name)
        except Exception as exc:
            _warn(messages, f"Could not build AOI context: {exc}")
        if show_aoi_map and aoi_context is not None:
            try:
                display_aoi_map(aoi_context)
            except Exception as exc:
                _warn(messages, f"Could not display AOI map: {exc}")

    tracker = WorkflowProgress(resolve_progress_reporter(progress))

    # Probed BEFORE the water step, not inside the rainfall branch: on a DEA
    # fetch the rainfall branch is hours away, and "No module named 's3fs'"
    # arriving then wastes the whole run. A supplied CSV never touches SILO,
    # so it is not probed.
    preflight: list[str] = []
    if fetch_rainfall and rainfall_csv_path is None:
        absent = missing_rainfall_dependencies()
        if absent:
            preflight.append(
                "Ancillary SILO rainfall will fail: this environment cannot "
                f"import {', '.join(absent)}. Install the raster extra "
                '(pip install "hydroseason[raster]") or drop '
                "fetch_rainfall=True. The water analysis and report are "
        "unaffected; abort now if rainfall output is required."
            )
    for message in preflight:
        py_warnings.warn(message, UserWarning, stacklevel=2)

    tracker.start(
        1,
        "fetching DEA WOfS"
        if water_source is None
        else "reading the supplied water source",
    )
    resolved = resolve_water_input(
        water_source,
        aoi=aoi_gdf if aoi_gdf is not None else aoi,
        start_date=start_date,
        end_date=end_date,
        water_mask_variable=water_mask_variable,
        stac_url=stac_url,
        stac_collection=stac_collection,
        statistics_stac_url=statistics_stac_url,
        cache_dir=cache_dir,
        progress=tracker.renders_subprogress,
        progress_desc=tracker.subprogress_desc(1),
        refresh_historical_mask=refresh_historical_mask,
    )
    tracker.finish(1, f"{len(resolved.extent)} months, {resolved.source_kind}")

    tracker.start(2)
    options = dict(analysis_options or {})
    analysis = analyze_catchment(resolved.extent, **options)
    tracker.finish(2, f"{analysis.route} route")
    messages = messages + list(analysis.warnings) + preflight + list(resolved.warnings)

    rainfall: pd.DataFrame | None = None
    comparison: RegimeComparison | None = None
    rainfall_error: str | None = None
    comparison_error: str | None = None
    status: RainfallStatus = "disabled"
    rain_source: RainfallSource = "none"

    if rainfall_csv_path is not None:
        tracker.start(3, "supplied CSV")
        rain_source = "csv"
        try:
            loaded = load_monthly_rainfall_csv(rainfall_csv_path)
            aligned = align_monthly_rainfall(loaded, resolved.extent.index)
            if not aligned["rainfall_mm"].notna().any():
                raise ValueError("no months overlapping the water record.")
            rainfall = aligned
            status = "provided"
        except Exception as exc:
            status = "provided_failed"
            rainfall_error = str(exc)
            _warn(messages, f"Ancillary rainfall CSV unavailable: {exc}")
        tracker.finish(3, status)
    elif fetch_rainfall:
        tracker.start(3, "SILO fetch")
        rain_source = "silo"
        try:
            if aoi_gdf is None:
                raise ValueError("SILO rainfall fetching requires aoi.")
            raw = get_monthly_silo_rainfall(
                aoi_gdf,
                int(resolved.extent.index.min().year),
                int(resolved.extent.index.max().year),
            )
            normalised = normalise_monthly_rainfall(raw)
            aligned = align_monthly_rainfall(normalised, resolved.extent.index)
            if not aligned["rainfall_mm"].notna().any():
                raise ValueError("no months overlapping the water record.")
            rainfall = aligned
            status = "fetched"
        except Exception as exc:
            status = "fetch_failed"
            rainfall_error = str(exc)
            _warn(messages, f"Ancillary SILO rainfall unavailable: {exc}")
        tracker.finish(3, status)
    else:
        # Reported, not renumbered: "[5/5]" always means the report, whether
        # or not rainfall was requested.
        tracker.start(3)
        tracker.finish(3, "skipped")

    if rainfall is not None:
        tracker.start(4)
        try:
            comparison = compare_rainfall_to_extent_regime(
                analysis.regime,
                rainfall,
                min_months_per_year=int(options.get("min_months_per_year", 9)),
            )
        except Exception as exc:
            comparison_error = str(exc)
            _warn(messages, f"Ancillary rainfall comparison unavailable: {exc}")
        tracker.finish(4, "failed" if comparison_error else "compared")
    else:
        tracker.start(4)
        tracker.finish(4, "skipped")

    rainfall_warning = None
    if rainfall_error is not None:
        rainfall_source_label = (
            "SILO rainfall" if rain_source == "silo" else "rainfall CSV"
        )
        rainfall_warning = (
            f"Ancillary {rainfall_source_label} unavailable: {rainfall_error}"
        )

    tracker.start(5)
    artifacts = generate_catchment_report(
        resolved.extent,
        output_dir,
        name=aoi_name,
        analysis=analysis,
        rainfall=rainfall,
        rainfall_comparison=comparison,
        rainfall_source=rain_source if rain_source != "none" else None,
        rainfall_warning=rainfall_warning,
        rainfall_comparison_warning=comparison_error,
        aoi_context=aoi_context,
        title=report_title,
        subtitle=report_subtitle,
    )
    tracker.finish(5, artifacts.html.name)
    return HydroSeasonRunResult(
        extent=resolved.extent,
        analysis=analysis,
        rainfall=rainfall,
        rainfall_comparison=comparison,
        rainfall_status=status,
        rainfall_source=rain_source,
        rainfall_error=rainfall_error,
        rainfall_comparison_error=comparison_error,
        source_kind=resolved.source_kind,
        warnings=tuple(messages),
        aoi_context=aoi_context,
        artifacts=artifacts,
    )


__all__ = [
    "HydroSeasonRunResult",
    "RainfallSource",
    "RainfallStatus",
    "run_hydroseason",
]
