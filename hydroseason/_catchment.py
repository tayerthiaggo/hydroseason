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

from dataclasses import dataclass, field, replace
from typing import Literal

import pandas as pd

from ._boundary import robust_scale
from ._dynamic_year import DynamicHydroYearConfig
from ._events import WaterEventResult, extract_water_events
from ._phase import assign_rule_based_phases
from ._regime import WaterRegimeAssessment, assess_water_regime
from ._state_input import QualityPolicy, prepare_monthly_extent
from .hydro_year import HydroYearConfig, detect_hydrological_years
from .hydrological_state import HydrologicalStateResult, analyze_hydrological_state

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
    # Phase labels for routes that carry annual cycles but no
    # ``HydrologicalStateResult`` to hang them off. The seasonal route reaches
    # its phases through ``state.monthly_phase``; the imposed-window route has
    # no state object, so without this field its phases had nowhere to live and
    # the report fell back to a fully ``unspecified`` monthly frame.
    monthly_phase: pd.DataFrame | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    state: HydrologicalStateResult | None = None
    # Retain the quality policy used to construct this analysis so report
    # exports validate and label months against the same candidate set.
    quality_policy: QualityPolicy = "exclude"
    max_invalid_pct: float = 20.0

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


def _fixed_config_from_climatology(peak_month: int) -> HydroYearConfig:
    """Build a fixed wet/dry window spanning an observed climatological peak.

    The wet window is centred so the peak sits inside it, not at its edge: a
    window ending at the peak leaves too few months for the dry window and the
    detector rejects every year.

    Windows are cyclic month ranges (see ``HydroYearConfig``), so any
    climatological peak phase is representable -- tropical year-boundary wet
    seasons and mid-year / winter-rainfall phases alike. The six-month wet
    window is ``peak-2 .. peak+3``; the dry window is the six months that
    follow. Callers must still mark every emitted row
    ``boundary_basis="imposed_fixed_window"``: this is average behaviour
    imposed from climatology, not a per-year detection.
    """
    if peak_month < 1 or peak_month > 12:
        raise ValueError(f"peak_month must be in 1..12, got {peak_month}")
    wet_start = _wrap_month(peak_month - 2)
    wet_end = _wrap_month(peak_month + 3)
    dry_start = _wrap_month(wet_end + 1)
    dry_end = _wrap_month(dry_start + 5)
    return HydroYearConfig(
        wet_start_month=wet_start,
        wet_end_month=wet_end,
        dry_start_month=dry_start,
        dry_end_month=dry_end,
    )


def _annotate_fixed_window_quality(
    years: pd.DataFrame,
    extent,
    *,
    value_col: str,
    date_col: str | None,
    max_invalid_pct: float,
    quality_policy: QualityPolicy,
) -> pd.DataFrame:
    """Carry invalid-coverage diagnostics into imposed-window HY rows.

    The fixed-window route predates the robust dynamic schema.  It still needs
    the same trust signal: observed boundary months are retained, but any
    boundary touching a low-quality month is explicitly provisional/low.
    ``quality_policy`` controls which finite months are exported as usable;
    the invalid percentage itself remains the evidence used for the flag.
    """
    if years.empty:
        return years
    prepared = prepare_monthly_extent(
        extent,
        value_col=value_col,
        date_col=date_col,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    )
    out = years.copy()

    def _invalid(month) -> float:
        if pd.isna(month) or pd.Timestamp(month) not in prepared.index:
            return float("nan")
        value = prepared.loc[pd.Timestamp(month), "invalid_pct"]
        return float(value) if pd.notna(value) else float("nan")

    def _support(value: float) -> float:
        return max(0.0, min(1.0, 1.0 - value / 100.0)) if pd.notna(value) else 0.0

    peak_invalid = [_invalid(value) for value in out["peak_month"]]
    mid_invalid = [_invalid(value) for value in out["mid_dry_month"]]
    trough_invalid = [_invalid(value) for value in out["end_dry_month"]]
    out["peak_invalid_pct"] = peak_invalid
    out["mid_dry_invalid_pct"] = mid_invalid
    out["trough_invalid_pct"] = trough_invalid
    out["temporal_mid_dry_month"] = out["mid_dry_month"]
    out["temporal_mid_dry_extent_pct"] = out["mid_extent_pct"]
    # The fixed-window detector names the cycle's closing boundary
    # ``end_dry_month``; the dynamic schema every consumer downstream reads
    # calls it ``trough_month``. Without the alias the report silently drops
    # the End Dry marker, phase labelling cannot resolve an amplitude, and
    # ``is_hy_trough`` stays False for every row -- all three failing quietly
    # because a missing column reads as "no such boundary" rather than an error.
    out["trough_month"] = out["end_dry_month"]
    out["trough_extent_pct"] = out["end_extent_pct"]
    bad = [
        any(pd.isna(value) or float(value) > max_invalid_pct for value in values)
        for values in zip(peak_invalid, mid_invalid, trough_invalid)
    ]
    out["peak_selection_status"] = ["low_quality" if value else "raw" for value in bad]
    out["peak_selection_support"] = [_support(value) for value in peak_invalid]
    out["boundary_status"] = ["provisional" if value else "confirmed" for value in bad]
    out["status"] = ["partial" if value else "complete" for value in bad]
    out["status_reason"] = ["boundary_low_quality" if value else "ok" for value in bad]
    out.loc[out["status"] == "partial", "confidence"] = "low"
    return out


def analyze_catchment(
    extent,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    min_months_per_year: int = 9,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "exclude",
    phase_model: Literal["none", "rule_based"] = "rule_based",
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> CatchmentAnalysis:
    """Assess regime, then run the analysis that regime supports.

    Fully automatic: the recommended action for the detected regime is taken,
    not offered. Callers wanting a different route should call the underlying
    detectors directly, which makes the override explicit in their own code
    rather than hidden in a flag here.
    """
    if phase_model not in {"none", "rule_based"}:
        raise ValueError("phase_model must be 'none' or 'rule_based'")

    regime = assess_water_regime(
        extent,
        value_col=value_col,
        date_col=date_col,
        min_months_per_year=min_months_per_year,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
        n_bootstrap=n_bootstrap,
        random_state=random_state,
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
            state=None,
            warnings=tuple(warnings),
            quality_policy=quality_policy,
            max_invalid_pct=max_invalid_pct,
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
            state=None,
            climatological_peak_month=None,
            climatological_trough_month=None,
            warnings=tuple(warnings),
            quality_policy=quality_policy,
            max_invalid_pct=max_invalid_pct,
        )

    if regime.regime == "seasonal":
        config = DynamicHydroYearConfig(
            expected_trough_month=int(regime.climatological_trough_month),
            expected_peak_month=int(regime.climatological_peak_month),
            max_invalid_pct=max_invalid_pct,
            quality_policy=quality_policy,
            detector="robust_extrema",
            phase_model=phase_model,
        )
        state_extent = prepare_monthly_extent(
            extent,
            value_col=value_col,
            date_col=date_col,
            max_invalid_pct=max_invalid_pct,
            quality_policy=quality_policy,
        )
        state = analyze_hydrological_state(
            state_extent,
            config=config,
            n_bootstrap=n_bootstrap,
            random_state=random_state,
            quality_policy=quality_policy,
        )
        years = state.hydro_years.copy()
        if not years.empty:
            years["boundary_basis"] = "detected_per_year"
        state = replace(state, hydro_years=years)
        return CatchmentAnalysis(
            regime=regime,
            route="per_year_detection",
            route_reason=(
                f"seasonal record (SNR {regime.amplitude_snr:.2f}, per-year peak spread "
                f"{regime.peak_phase_iqr_months:.1f} months): per-year boundaries are "
                "reproducible"
            ),
            hydro_years=years,
            events=events,
            monthly=pd.DataFrame(),
            state=state,
            climatological_peak_month=regime.climatological_peak_month,
            climatological_trough_month=regime.climatological_trough_month,
            warnings=tuple(warnings),
            quality_policy=quality_policy,
            max_invalid_pct=max_invalid_pct,
        )

    # Marginal (and any remaining non-seasonal/non-aseasonal route that still
    # carries a climatological peak): impose one fixed window from that peak.
    # HydroYearConfig is cyclic, so every calendar peak phase is valid -- no
    # tropical-only geometry gate and no silent downgrade to events-only.
    config = _fixed_config_from_climatology(int(regime.climatological_peak_month))
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
            state=None,
            warnings=tuple(warnings),
            quality_policy=quality_policy,
            max_invalid_pct=max_invalid_pct,
        )

    route = "fixed_climatological_window"
    basis = "imposed_fixed_window"
    reason = (
        f"marginal record (SNR {regime.amplitude_snr:.2f}, per-year peak spread "
        f"{regime.peak_phase_iqr_months:.1f} months): per-year timing is not "
        "reproducible, so one fixed climatological window is imposed on every year"
    )
    monthly_phase: pd.DataFrame | None = None
    if not years.empty:
        years = years.copy()
        years["boundary_basis"] = basis
        years = _annotate_fixed_window_quality(
            years,
            extent,
            value_col=value_col,
            date_col=date_col,
            max_invalid_pct=max_invalid_pct,
            quality_policy=quality_policy,
        )
        # Phases describe observed within-cycle structure, so they are as
        # available here as on the seasonal route: the cycle they subdivide is
        # imposed, but recovery/wet/recession/dry are still read off the data.
        # ``boundary_basis`` carries the imposed provenance forward so a
        # consumer can tell the two apart.
        if phase_model == "rule_based":
            phase_input = prepare_monthly_extent(
                extent,
                value_col=value_col,
                date_col=date_col,
                max_invalid_pct=max_invalid_pct,
                quality_policy=quality_policy,
            )
            _, noise_pp = robust_scale(phase_input)
            monthly_phase = assign_rule_based_phases(
                phase_input,
                years,
                noise_pp=noise_pp,
                boundary_basis=basis,
            )

    return CatchmentAnalysis(
        regime=regime,
        route=route,
        route_reason=reason,
        hydro_years=years,
        events=events,
        monthly=pd.DataFrame(),
        state=None,
        climatological_peak_month=regime.climatological_peak_month,
        climatological_trough_month=regime.climatological_trough_month,
        monthly_phase=monthly_phase,
        warnings=tuple(warnings),
        quality_policy=quality_policy,
        max_invalid_pct=max_invalid_pct,
    )


__all__ = ["CatchmentAnalysis", "Route", "analyze_catchment"]
