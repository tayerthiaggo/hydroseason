from __future__ import annotations

import calendar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydroseason._catchment import CatchmentAnalysis


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
