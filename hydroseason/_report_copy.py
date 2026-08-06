from __future__ import annotations

import calendar
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydroseason._catchment import CatchmentAnalysis

from ._regime import REGIME_THRESHOLDS
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


# Display names for analytical routes. The raw identifiers title-cased into
# strings like "Event Characterisation" that overflowed their card; these are
# also plainer language for a reader who has not read the routing docstring.
_ROUTE_LABELS = {
    "per_year_detection": "Per-Year Detection",
    "fixed_climatological_window": "Fixed Window",
    "event_characterisation": "Event-Based",
    "insufficient_record": "Insufficient Record",
}

_WITHHELD_VALUE = "Not defined"
_WITHHELD_REASONS = {
    "aseasonal": "no reproducible annual cycle",
    "insufficient_record": "too few usable years to assess",
}


def _route_label(route: Any) -> str:
    return _ROUTE_LABELS.get(str(route), str(route).replace("_", " ").title())


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
    event_summary = analysis.events.summary if analysis.events is not None else {}

    # Every catchment keeps the same cards in the same order so two reports can
    # be read side by side. Where a regime cannot support a number, the card
    # says why it is absent rather than showing a bare "N/A": a deck of blanks
    # reads as a broken run, when it is in fact the finding.
    withheld_reason = _WITHHELD_REASONS.get(str(assessment.regime))
    if withheld_reason is None and n_years == 0:
        withheld_reason = "no hydrological years were resolved"

    def cycle_metric(value: str, detail: str) -> dict[str, str]:
        """A card whose number only exists if an annual cycle was defined."""
        if n_years == 0 and withheld_reason is not None:
            return {"value": _WITHHELD_VALUE, "detail": f"withheld: {withheld_reason}"}
        return {"value": value, "detail": detail}

    def card(label: str, value: str, detail: str) -> dict[str, str]:
        return {"label": label, "value": value, "detail": detail}

    snr_detail = (
        f"seasonal >= {REGIME_THRESHOLDS['seasonal_min_snr']:.1f}, "
        f"aseasonal < {REGIME_THRESHOLDS['aseasonal_max_snr']:.1f}"
    )
    iqr_detail = (
        f"spread of per-year peak timing; seasonal <= "
        f"{REGIME_THRESHOLDS['seasonal_max_phase_iqr_months']:.1f} months"
    )

    return [
        card(
            "hydrological regime",
            str(assessment.regime).replace("_", " ").title(),
            "assessed seasonal strength",
        ),
        card(
            "amplitude signal-to-noise ratio",
            _number(assessment.amplitude_snr, decimals=2),
            snr_detail,
        ),
        # Both gates are shown because either one alone is misleading: a
        # catchment can clear the amplitude threshold comfortably and still be
        # denied per-year boundaries on timing spread, which is exactly the
        # case a reader shown only the SNR would mistake for a bug.
        card(
            "peak timing spread",
            _number(assessment.peak_phase_iqr_months, decimals=1, suffix=" mo"),
            iqr_detail,
        ),
        card(
            "analytical route",
            _route_label(analysis.route),
            "how hydro-year boundaries were derived",
        ),
        card("hydrological years", str(n_years), _date_range_label(extent)),
        card(
            "mean annual amplitude",
            **cycle_metric(
                _number(amplitude.mean(), suffix="%"),
                "difference between peak and end dry",
            ),
        ),
        card(
            "mean cycle length",
            **cycle_metric(_number(cycle_length.mean()), "months per hydro-year"),
        ),
        card(
            "Typical peak month",
            **cycle_metric(
                _month_name(analysis.climatological_peak_month),
                "climatological maximum",
            ),
        ),
        card(
            "Typical trough month",
            **cycle_metric(
                _month_name(analysis.climatological_trough_month),
                "climatological minimum",
            ),
        ),
        card(
            "lower water extent at end of dry season",
            **cycle_metric(_extent_number(trough.min()), "minimum across all hydro-years"),
        ),
        card(
            "higher water extent in wet season",
            **cycle_metric(_extent_number(peak.max()), "maximum across all hydro-years"),
        ),
        card(
            "average water extent at end of dry season",
            **cycle_metric(_extent_number(trough.mean()), "mean across all hydro-years"),
        ),
        card(
            "high confidence years",
            **cycle_metric(str(high_confidence), f"out of {n_years} total years"),
        ),
        # Event descriptors presume no cycle, so they are populated on every
        # route. They carry the description for aseasonal catchments, where the
        # cycle cards above are deliberately empty.
        card(
            "wet events",
            str(event_summary.get("n_events", 0)),
            "episodes above the record's 75th percentile",
        ),
        card(
            "longest low-extent spell",
            _number(event_summary.get("longest_low_spell_months"), decimals=0, suffix=" mo"),
            "longest continuous run below baseline",
        ),
        card(
            "years without a wet event",
            str(assessment.years_without_wet_event),
            f"out of {assessment.n_usable_years} usable years",
        ),
        card(
            "average invalid/cloud cover",
            _number(average_invalid, suffix="%"),
            f"mean across {len(extent) if extent is not None else 0} months of observations",
        ),
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
