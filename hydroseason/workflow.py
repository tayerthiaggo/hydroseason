"""Public orchestrator: resolve water input, analyze, then add rainfall context.

``run_hydroseason`` ties together the modules that were designed to stay
decoupled from each other: it resolves whatever water source the caller
supplied (:mod:`hydroseason._workflow_input`), runs :func:`analyze_catchment`
exactly once -- the sole routing authority, rainfall-blind -- and only then
looks at rainfall at all. Rainfall is a strictly separate, best-effort branch:
loading a supplied CSV, fetching from SILO, and comparing against the
already-computed regime can each fail independently without taking the water
analysis or the report down with them. Every rainfall failure is recorded on
the result and surfaced as a ``UserWarning``; only water input, analysis, and
report-writing failures are fatal and propagate as exceptions.

Rainfall is off by default (``fetch_rainfall=False``). A supplied
``rainfall_csv_path`` always takes precedence over ``fetch_rainfall=True``: if
both are given, SILO is never called.

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

from ._catchment import CatchmentAnalysis, analyze_catchment
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
    artifacts: CatchmentReportPaths


def _warn(messages: list[str], message: str) -> None:
    messages.append(message)
    py_warnings.warn(message, UserWarning, stacklevel=3)


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
    tracker = WorkflowProgress(resolve_progress_reporter(progress))

    tracker.start(
        1,
        "fetching DEA WOfS"
        if water_source is None
        else "reading the supplied water source",
    )
    resolved = resolve_water_input(
        water_source,
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        water_mask_variable=water_mask_variable,
        stac_url=stac_url,
        stac_collection=stac_collection,
        statistics_stac_url=statistics_stac_url,
        cache_dir=cache_dir,
        progress=tracker.renders_subprogress,
        progress_desc=tracker.subprogress_desc(1),
    )
    tracker.finish(1, f"{len(resolved.extent)} months, {resolved.source_kind}")

    tracker.start(2)
    options = dict(analysis_options or {})
    analysis = analyze_catchment(resolved.extent, **options)
    tracker.finish(2, f"{analysis.route} route")
    messages = list(analysis.warnings)

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
            if aoi is None:
                raise ValueError("SILO rainfall fetching requires aoi.")
            aoi_gdf = load_aoi(aoi)
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
        artifacts=artifacts,
    )


__all__ = [
    "HydroSeasonRunResult",
    "RainfallSource",
    "RainfallStatus",
    "run_hydroseason",
]
