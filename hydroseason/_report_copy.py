from __future__ import annotations

import calendar
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydroseason._catchment import CatchmentAnalysis

from ._regime_compare import RegimeComparison

_DIVERGENCE_LABELS = {
    "agree": "Agree",
    "extent_damped": "Extent damped versus rainfall",
    "extent_more_seasonal": "Extent more seasonal than rainfall",
    "rainfall_insufficient": "Rainfall record too short",
    "extent_insufficient": "Extent record too short",
    "partial": "Partial comparison",
    "no_rainfall": "No rainfall data",
}


def _month_name(month_idx: int | float | None) -> str:
    if month_idx is None:
        return "N/A"
    try:
        idx = int(month_idx)
        if 1 <= idx <= 12:
            return calendar.month_name[idx]
    except (ValueError, TypeError):
        pass
    return "N/A"


def verdict_sentence(analysis: CatchmentAnalysis) -> str:
    """Generate regime-aware verdict copy for manager summary."""
    assessment = analysis.regime
    regime = assessment.regime
    snr = assessment.amplitude_snr

    if regime == "seasonal":
        route_desc = (
            "Dynamic hydrological-year boundaries are detected per year."
            if analysis.route == "per_year_detection"
            else "Hydrological year boundaries are applied."
        )
        return (
            f"Exhibits a seasonal regime with reproducible annual cycles "
            f"(SNR = {snr:.2f}). {route_desc}"
        )
    elif regime == "marginal":
        return (
            f"Exhibits marginal seasonality (SNR = {snr:.2f}); "
            f"analysis uses an imposed fixed annual climatological window as an analytical assumption."
        )
    elif regime == "aseasonal":
        return (
            f"Exhibits an aseasonal regime (SNR = {snr:.2f}) with no stable annual cycle; "
            f"use wet events and low-extent spells for surface water tracking."
        )
    else:  # insufficient_record or fallback
        return (
            "Data record is insufficient to establish hydrological regime or seasonal boundaries."
        )


def _metric_column(frame: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce")
    return pd.Series(dtype=float)


def _number(value: float | int | None, *, decimals: int = 1, suffix: str = "") -> str:
    if value is None or not np.isfinite(float(value)):
        return "N/A"
    return f"{float(value):.{decimals}f}{suffix}"


def _extent_number(value: float | int | None) -> str:
    """Format a water-extent percentage without collapsing small values to zero.

    Catchment extents are often a small fraction of a percent, where a fixed
    one-decimal format renders a real, non-zero extent as ``0.0%``.  Add
    decimals until the value is distinguishable from zero.
    """
    if value is None or not np.isfinite(float(value)):
        return "N/A"
    magnitude = abs(float(value))
    if magnitude == 0:
        return "0.0%"
    for decimals in (1, 2, 3):
        if round(magnitude, decimals) != 0:
            return f"{float(value):.{decimals}f}%"
    return "<0.001%" if value > 0 else ">-0.001%"


def _date_range_label(extent: pd.DataFrame | None) -> str:
    if extent is None or extent.empty:
        return "Source record"
    source = extent["date"] if "date" in extent.columns else extent.index
    dates = pd.to_datetime(source, errors="coerce" ).dropna()
    if dates.empty:
        return "Source record"
    return f"{dates.min():%b %Y} to {dates.max():%b %Y}"


def select_kpis(
    analysis: CatchmentAnalysis,
    extent: pd.DataFrame | None = None,
) -> list[dict[str, str]]:
    """Build the manager-facing summary cards in display order.

    Regime, signal-to-noise ratio and analytical route lead the deck: they
    frame how much weight the remaining per-year numbers can carry.
    """
    hy_df = analysis.hydro_years.copy()
    n_years = len(hy_df)
    amplitude = _metric_column(hy_df, "drawdown_pct", "amplitude_pct")
    cycle_length = _metric_column(hy_df, "cycle_months", "n_months_cycle")
    peak = _metric_column(hy_df, "peak_extent_pct")
    trough = _metric_column(hy_df, "trough_extent_pct", "end_extent_pct")
    confidence = hy_df.get("confidence", pd.Series(dtype=object)).astype(str).str.lower()
    high_confidence = int(confidence.eq("high").sum())
    average_invalid = (
        pd.to_numeric(extent["invalid_pct"], errors="coerce").mean()
        if extent is not None and "invalid_pct" in extent.columns
        else np.nan
    )

    assessment = analysis.regime

    return [
        {
            "label": "hydrological regime",
            "value": str(assessment.regime).replace("_", " ").title(),
            "detail": "assessed seasonal strength",
        },
        {
            "label": "amplitude signal-to-noise ratio",
            "value": _number(assessment.amplitude_snr, decimals=2),
            "detail": "higher means a more reproducible annual cycle",
        },
        {
            "label": "analytical route",
            "value": str(analysis.route).replace("_", " ").title(),
            "detail": "how hydro-year boundaries were derived",
        },
        {
            "label": "hydrological years",
            "value": str(n_years),
            "detail": _date_range_label(extent),
        },
        {
            "label": "mean annual amplitude",
            "value": _number(amplitude.mean(), suffix="%"),
            "detail": "difference between peak and end dry",
        },
        {
            "label": "mean cycle length",
            "value": _number(cycle_length.mean()),
            "detail": "months per hydro-year",
        },
        {
            "label": "Typical peak month",
            "value": _month_name(analysis.climatological_peak_month),
            "detail": "climatological maximum",
        },
        {
            "label": "Typical trough month",
            "value": _month_name(analysis.climatological_trough_month),
            "detail": "climatological minimum",
        },
        {
            "label": "lower water extent at end of dry season",
            "value": _extent_number(trough.min()),
            "detail": "minimum across all hydro-years",
        },
        {
            "label": "higher water extent in wet season",
            "value": _extent_number(peak.max()),
            "detail": "maximum across all hydro-years",
        },
        {
            "label": "average water extent at end of dry season",
            "value": _extent_number(trough.mean()),
            "detail": "mean across all hydro-years",
        },
        {
            "label": "high confidence years",
            "value": str(high_confidence),
            "detail": f"out of {n_years} total years",
        },
        {
            "label": "average invalid/cloud cover",
            "value": _number(average_invalid, suffix="%"),
            "detail": f"mean across {len(extent) if extent is not None else 0} months of observations",
        },
    ]


def build_rainfall_context(
    *,
    source: str,
    comparison: RegimeComparison | None,
    comparison_warning: str | None,
) -> dict[str, Any]:
    """Build rainfall context labels and metrics for display.

    Consumes an already-computed RegimeComparison (Task 2 output) and returns
    presentation-ready metadata: source title, divergence label, comparison status,
    and derived monthly climatology metrics for a paired figure.
    """
    title = (
        "Rainfall context (SILO)"
        if source == "silo"
        else "Rainfall context (supplied CSV)"
    )
    if comparison is None or comparison.rainfall is None:
        return {
            "title": title,
            "divergence": "unavailable",
            "comparison_label": "Unavailable",
            "interpretation": "Rainfall values are shown, but regime comparison is unavailable.",
            "extent_regime": None,
            "rainfall_regime": None,
            "extent_snr": None,
            "rainfall_snr": None,
            "extent_peak_month": "N/A",
            "extent_trough_month": "N/A",
            "rainfall_peak_month": "N/A",
            "rainfall_trough_month": "N/A",
            "peak_lag_months": None,
            "warning": comparison_warning,
        }
    return {
        "title": title,
        "divergence": comparison.divergence,
        "comparison_label": _DIVERGENCE_LABELS.get(
            comparison.divergence, comparison.divergence.replace("_", " ").title()
        ),
        "interpretation": comparison.interpretation,
        "extent_regime": comparison.extent.regime,
        "rainfall_regime": comparison.rainfall.regime,
        "extent_snr": comparison.extent.amplitude_snr,
        "rainfall_snr": comparison.rainfall.amplitude_snr,
        "extent_peak_month": _month_name(comparison.extent.climatological_peak_month),
        "extent_trough_month": _month_name(comparison.extent.climatological_trough_month),
        "rainfall_peak_month": _month_name(comparison.rainfall.climatological_peak_month),
        "rainfall_trough_month": _month_name(comparison.rainfall.climatological_trough_month),
        "peak_lag_months": comparison.peak_lag_months,
        "warning": comparison_warning,
    }
