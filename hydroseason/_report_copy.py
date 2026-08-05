from __future__ import annotations

import calendar
from typing import TYPE_CHECKING, Any

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


def select_kpis(analysis: CatchmentAnalysis) -> list[dict[str, str]]:
    """Select at most 6 key performance indicators tailored to catchment regime."""
    assessment = analysis.regime
    kpis: list[dict[str, str]] = []

    # 1. Regime
    regime_display = assessment.regime.replace("_", " ").title()
    kpis.append({"label": "Regime", "value": regime_display, "detail": "Assessed seasonal strength"})

    # 2. SNR
    kpis.append({"label": "Signal-to-Noise Ratio", "value": f"{assessment.amplitude_snr:.2f}", "detail": "SNR metric"})

    # 3. Route
    route_display = analysis.route.replace("_", " ").title()
    kpis.append({"label": "Hydrological route", "value": route_display, "detail": "Analytical workflow path"})

    if analysis.route in ("per_year_detection", "climatological_fixed"):
        hy_df = analysis.hydro_years
        complete_cnt = 0
        if not hy_df.empty and "status" in hy_df.columns:
            complete_cnt = int((hy_df["status"] == "complete").sum())

        kpis.append({
            "label": "Complete hydrological years",
            "value": str(complete_cnt),
            "detail": "Robust dynamic annual cycles" if analysis.route == "per_year_detection" else "Imposed annual cycles",
        })

        trough_m = _month_name(analysis.climatological_trough_month)
        peak_m = _month_name(analysis.climatological_peak_month)

        kpis.append({"label": "Typical peak month", "value": peak_m, "detail": "Climatological max"})
        kpis.append({"label": "Typical trough month", "value": trough_m, "detail": "Climatological min"})

    else:
        # Event characterisation / insufficient
        n_events = len(analysis.events.events) if hasattr(analysis.events, "events") else 0
        n_spells = len(analysis.events.low_spells) if hasattr(analysis.events, "low_spells") else 0

        kpis.append({"label": "Wet events detected", "value": str(n_events), "detail": "Distinct high-water events"})
        kpis.append({"label": "Low-extent spells", "value": str(n_spells), "detail": "Prolonged dry/low periods"})

    # Ensure at most 6 items
    return kpis[:6]


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
