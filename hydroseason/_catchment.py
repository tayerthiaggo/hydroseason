"""Regime-routed catchment analysis: one entry point, no operator decisions.

``analyze_catchment`` assesses the regime first, then dispatches to the
analysis that regime actually supports, and records which route it took and
why. Nothing prompts and nothing raises on a difficult record: a catchment
with no detectable annual cycle returns event descriptors and an empty
hydrological-year table rather than an exception or -- worse -- a full set of
confidently-labelled boundaries fitted to noise.

The three routes:

``per_year_detection``
    Seasonal record. Per-year peak and trough are reproducible, so the full
    dynamic pipeline runs and its boundaries are marked ``detected_per_year``.

``fixed_climatological_window``
    Marginal record. Individual years disagree on timing, but the pooled
    climatology has a stable phase, so one fixed window derived from that
    climatology is applied to every year. Those boundaries are marked
    ``imposed_fixed_window`` because they are an assumption the workflow
    made, not a feature it found.

``event_characterisation``
    Aseasonal record. No hydrological year is defined at all. Wet episodes
    and low-extent spells carry the description instead.

Event descriptors are computed on every route, since they are the one view
that never presumes a cycle exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ._events import WaterEventResult, extract_water_events
from ._regime import WaterRegimeAssessment, assess_water_regime
from ._state_input import QualityPolicy
from .hydro_year import HydroYearConfig, detect_hydrological_years


Route = str


@dataclass(frozen=True)
class CatchmentAnalysis:
    """Everything the record supports, plus how that was decided."""

    regime: WaterRegimeAssessment
    route: Route
    route_reason: str
    hydro_years: pd.DataFrame
    events: WaterEventResult
    monthly: pd.DataFrame
    climatological_peak_month: int | None = None
    climatological_trough_month: int | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def summary_row(self, *, name: str) -> dict:
        """Flat one-row-per-catchment record for a cross-catchment table."""
        return {
            "catchment": name,
            "regime": self.regime.regime,
            "route": self.route,
            "amplitude_snr": round(self.regime.amplitude_snr, 3),
            "peak_phase_iqr_months": (
                round(self.regime.peak_phase_iqr_months, 2)
                if self.regime.peak_phase_iqr_months is not None
                else None
            ),
            "n_usable_years": self.regime.n_usable_years,
            "n_usable_months": self.regime.n_usable_months,
            "n_hydro_years": int(len(self.hydro_years)),
            "boundary_basis": (
                str(self.hydro_years["boundary_basis"].iloc[0])
                if not self.hydro_years.empty
                else "none"
            ),
            "climatological_peak_month": self.climatological_peak_month,
            "climatological_trough_month": self.climatological_trough_month,
            "n_wet_events": self.events.summary["n_events"],
            "median_event_duration_months": self.events.summary["median_event_duration_months"],
            "longest_low_spell_months": self.events.summary["longest_low_spell_months"],
            "median_recurrence_months": self.events.summary["median_recurrence_months"],
            "years_without_wet_event": self.regime.years_without_wet_event,
        }


def _wrap_month(month: int) -> int:
    """Map any integer onto a 1-based calendar month."""
    return ((month - 1) % 12) + 1


def _fixed_config_from_climatology(peak_month: int) -> HydroYearConfig | None:
    """Build a fixed wet/dry window spanning an observed climatological peak.

    The wet window is centred so the peak sits inside it, not at its edge: a
    window ending at the peak leaves too few months for the dry window and the
    detector rejects every year.

    ``HydroYearConfig`` hard-requires the wet window to cross the calendar-year
    boundary and the dry window to sit within one year after it. That geometry
    describes a tropical wet season (wet spanning the turn of the year, dry
    mid-year) and genuinely cannot express the reverse phase -- a catchment
    peaking around mid-year has no valid representation. Return ``None`` in
    that case rather than fitting a window with the wrong phase, and let the
    caller fall back to a view that makes no phase assumption.
    """
    wet_start = _wrap_month(peak_month - 2)
    wet_end = _wrap_month(peak_month + 3)
    if wet_start <= wet_end:
        return None  # wet window would not cross the year boundary
    dry_start = _wrap_month(wet_end + 1)
    dry_end = min(12, dry_start + 5)
    if dry_start <= wet_end or dry_end < dry_start:
        return None
    return HydroYearConfig(
        wet_start_month=wet_start,
        wet_end_month=wet_end,
        dry_start_month=dry_start,
        dry_end_month=dry_end,
    )


def analyze_catchment(
    extent,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    min_months_per_year: int = 9,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "exclude",
) -> CatchmentAnalysis:
    """Assess regime, then run the analysis that regime supports.

    Fully automatic: the recommended action for the detected regime is taken,
    not offered. Callers wanting a different route should call the underlying
    detectors directly, which makes the override explicit in their own code
    rather than hidden in a flag here.
    """
    regime = assess_water_regime(
        extent,
        value_col=value_col,
        date_col=date_col,
        min_months_per_year=min_months_per_year,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    )
    events = extract_water_events(
        extent,
        value_col=value_col,
        date_col=date_col,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    )
    warnings: list[str] = list(regime.caveats)
    empty_years = pd.DataFrame()

    if regime.regime == "insufficient_record":
        return CatchmentAnalysis(
            regime=regime,
            route="insufficient_record",
            route_reason=(
                f"only {regime.n_usable_years} usable years "
                f"(min {min_months_per_year} months each); regime undetermined, "
                "no hydrological year defined"
            ),
            hydro_years=empty_years,
            events=events,
            monthly=pd.DataFrame(),
            warnings=tuple(warnings),
        )

    if regime.regime == "aseasonal":
        return CatchmentAnalysis(
            regime=regime,
            route="event_characterisation",
            route_reason=(
                f"aseasonal record (SNR {regime.amplitude_snr:.2f}, per-year peak "
                f"spread {regime.peak_phase_iqr_months:.1f} months): no reproducible "
                "annual cycle, so no hydrological year is defined"
            ),
            hydro_years=empty_years,
            events=events,
            monthly=pd.DataFrame(),
            climatological_peak_month=None,
            climatological_trough_month=None,
            warnings=tuple(warnings),
        )

    config = _fixed_config_from_climatology(int(regime.climatological_peak_month))
    if config is None:
        warnings.append(
            "climatological peak falls mid-year, a phase the fixed wet/dry "
            "window geometry cannot represent; reported as events only rather "
            "than fitted with a wrong-phase window"
        )
        return CatchmentAnalysis(
            regime=regime,
            route="event_characterisation",
            route_reason=(
                f"{regime.regime} record peaking in month "
                f"{regime.climatological_peak_month}: the supported window "
                "geometry requires a wet season spanning the turn of the year, "
                "so no hydrological year is defined"
            ),
            hydro_years=empty_years,
            events=events,
            monthly=pd.DataFrame(),
            climatological_peak_month=regime.climatological_peak_month,
            climatological_trough_month=regime.climatological_trough_month,
            warnings=tuple(warnings),
        )
    try:
        years = detect_hydrological_years(
            extent,
            value_col=value_col,
            date_col=date_col,
            config=config,
            quality_policy="flag",
            missing_month_policy="ignore",
        )
    except ValueError as exc:  # pragma: no cover - defensive; routing should prevent
        warnings.append(f"boundary detection failed, falling back to events: {exc}")
        return CatchmentAnalysis(
            regime=regime,
            route="event_characterisation",
            route_reason=f"detection failed on a {regime.regime} record: {exc}",
            hydro_years=empty_years,
            events=events,
            monthly=pd.DataFrame(),
            warnings=tuple(warnings),
        )

    if regime.regime == "seasonal":
        route = "per_year_detection"
        basis = "detected_per_year"
        reason = (
            f"seasonal record (SNR {regime.amplitude_snr:.2f}, per-year peak spread "
            f"{regime.peak_phase_iqr_months:.1f} months): per-year boundaries are "
            "reproducible"
        )
    else:
        route = "fixed_climatological_window"
        basis = "imposed_fixed_window"
        reason = (
            f"marginal record (SNR {regime.amplitude_snr:.2f}, per-year peak spread "
            f"{regime.peak_phase_iqr_months:.1f} months): per-year timing is not "
            "reproducible, so one fixed climatological window is imposed on every year"
        )
    if not years.empty:
        years = years.copy()
        years["boundary_basis"] = basis

    return CatchmentAnalysis(
        regime=regime,
        route=route,
        route_reason=reason,
        hydro_years=years,
        events=events,
        monthly=pd.DataFrame(),
        climatological_peak_month=regime.climatological_peak_month,
        climatological_trough_month=regime.climatological_trough_month,
        warnings=tuple(warnings),
    )


__all__ = ["CatchmentAnalysis", "Route", "analyze_catchment"]
