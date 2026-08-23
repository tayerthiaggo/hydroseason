"""Regime-routed catchment analysis: one entry point, no operator decisions.

``analyze_catchment`` assesses the regime first, then dispatches to the
analysis that regime actually supports, and records which route it took and
why. Nothing prompts and nothing raises on a difficult record: a catchment
with no detectable annual cycle returns event descriptors and an empty
hydrological-year table rather than an exception or -- worse -- a full set of
confidently-labelled boundaries fitted to noise.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import RobustBoundaryConfig, robust_scale
from ._boundary_recoverability import RecoverabilityThresholds
from ._challenger import ChallengerAssessment
from ._decision_policy import DecisionPolicy, ESTABLISHED_POLICY, Route
from ._dynamic_year import DynamicHydroYearConfig
from ._events import WaterEventResult, extract_water_events
from ._evidence import EvidenceThresholds
from .hydro_year import HydroYearConfig, detect_hydrological_years
from ._phase import assign_monthly_phases
from ._phase_scheme import (
    PHASE_SCHEME_UNSET,
    LegacyPhaseModel,
    PhaseScheme,
    UnsetPhaseScheme,
    resolve_phase_scheme,
)
from ._regime import WaterRegimeAssessment, assess_water_regime
from ._state_input import QualityPolicy, prepare_monthly_extent
from .hydrological_state import HydrologicalStateResult, analyze_hydrological_state

__all__ = ["CatchmentAnalysis", "Route", "analyze_catchment"]


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
    monthly_phase: pd.DataFrame | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    state: HydrologicalStateResult | None = None
    quality_policy: QualityPolicy = "flag"
    max_invalid_pct: float = 20.0
    decision_policy: DecisionPolicy = ESTABLISHED_POLICY
    challenger: ChallengerAssessment | None = None

    @property
    def public_route(self) -> Route:
        return self.route

    def summary_row(self, *, name: str) -> dict:
        """Flat one-row-per-catchment record for a cross-catchment table."""
        row = {
            "catchment": name,
            "decision_policy": self.decision_policy,
            "regime": self.regime.regime,
            "route": self.route,
            "amplitude_snr": round(self.regime.amplitude_snr, 3),
            "peak_timing_concentration": _rounded(self.regime.peak_timing_concentration, 3),
            "peak_timing_concentration_ci_low": _rounded(
                self.regime.peak_timing_concentration_ci_low, 3
            ),
            "peak_timing_concentration_ci_high": _rounded(
                self.regime.peak_timing_concentration_ci_high, 3
            ),
            "peak_timing_uniformity_p": _rounded(self.regime.peak_timing_uniformity_p, 3),
            "peak_phase_iqr_months": (
                round(self.regime.peak_phase_iqr_months, 2)
                if self.regime.peak_phase_iqr_months is not None
                else None
            ),
            "trough_timing_concentration": _rounded(self.regime.trough_timing_concentration, 3),
            "trough_timing_concentration_ci_low": _rounded(
                self.regime.trough_timing_concentration_ci_low, 3
            ),
            "trough_timing_concentration_ci_high": _rounded(
                self.regime.trough_timing_concentration_ci_high, 3
            ),
            "trough_timing_uniformity_p": _rounded(self.regime.trough_timing_uniformity_p, 3),
            "trough_phase_iqr_months": _rounded(self.regime.trough_phase_iqr_months, 2),
            "n_timing_years": self.regime.n_timing_years,
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
        if self.challenger is not None:
            row.update({
                "challenger_route": self.challenger.proposed_route,
                "challenger_regime": self.challenger.proposed_regime,
                "challenger_annual_cycle_evidence": self.challenger.annual_cycle_evidence,
                "challenger_boundary_recoverability": self.challenger.boundary_recoverability,
                "challenger_seasonal_cv_skill": _rounded(self.challenger.seasonal_cv_skill, 3),
            })
        return row


def _rounded(value: float | None, decimals: int) -> float | None:
    """Round optional scalar diagnostics without introducing non-serialisable values."""
    return round(value, decimals) if value is not None else None


def _wrap_month(month: int) -> int:
    """Map any integer onto a 1-based calendar month."""
    return ((month - 1) % 12) + 1


def _fixed_config_from_climatology(peak_month: int) -> HydroYearConfig:
    """Build a fixed wet/dry window spanning an observed climatological peak."""
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
    """Carry invalid-coverage diagnostics into imposed-window HY rows."""
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
    quality_policy: QualityPolicy = "flag",
    phase_scheme: PhaseScheme | UnsetPhaseScheme = PHASE_SCHEME_UNSET,
    phase_model: LegacyPhaseModel | None = None,
    n_bootstrap: int = 200,
    random_state: int = 0,
    evidence_thresholds: EvidenceThresholds | None = None,
    recoverability_thresholds: RecoverabilityThresholds | None = None,
    robust_boundary_config: RobustBoundaryConfig | None = None,
    trough_search_radius_months: int = 3,
) -> CatchmentAnalysis:
    """Assess regime, then run the analysis that regime supports.

    Fully automatic: the recommended action for the detected regime is taken,
    not offered. Callers wanting a different route should call the underlying
    detectors directly, which makes the override explicit in their own code
    rather than hidden in a flag here.
    """
    canonical_scheme = resolve_phase_scheme(
        phase_scheme=phase_scheme,
        phase_model=phase_model,
    )

    regime = assess_water_regime(
        extent,
        value_col=value_col,
        date_col=date_col,
        min_months_per_year=min_months_per_year,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
        n_bootstrap=n_bootstrap,
        random_state=random_state,
        evidence_thresholds=evidence_thresholds,
        recoverability_thresholds=recoverability_thresholds,
        robust_boundary_config=robust_boundary_config,
        trough_search_radius_months=trough_search_radius_months,
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
            decision_policy=regime.decision_policy,
            challenger=regime.challenger,
        )

    if regime.supports_per_year_boundaries:
        try:
            config = DynamicHydroYearConfig(
                expected_trough_month=int(regime.climatological_trough_month),
                expected_peak_month=int(regime.climatological_peak_month),
                max_invalid_pct=max_invalid_pct,
                quality_policy=quality_policy,
                detector="robust_extrema",
                phase_scheme=canonical_scheme,
                trough_search_radius_months=trough_search_radius_months,
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
        except ValueError as exc:
            warnings.append(f"per-year boundary detection failed; using events: {exc}")
            return CatchmentAnalysis(
                regime=regime,
                route="event_characterisation",
                route_reason=(
                    f"per-year boundary detection failed despite stable trough timing: {exc}; "
                    "using event characterisation"
                ),
                hydro_years=empty_years,
                events=events,
                monthly=pd.DataFrame(),
                state=None,
                warnings=tuple(warnings),
                quality_policy=quality_policy,
                max_invalid_pct=max_invalid_pct,
                decision_policy=regime.decision_policy,
                challenger=regime.challenger,
            )
        years = state.hydro_years.copy()
        if years.empty:
            reason = "per-year boundary detection returned no hydrological years"
            warnings.append(f"{reason}; using events")
            return CatchmentAnalysis(
                regime=regime,
                route="event_characterisation",
                route_reason=f"{reason}; using event characterisation",
                hydro_years=empty_years,
                events=events,
                monthly=pd.DataFrame(),
                state=None,
                warnings=tuple(warnings),
                quality_policy=quality_policy,
                max_invalid_pct=max_invalid_pct,
                decision_policy=regime.decision_policy,
                challenger=regime.challenger,
            )
        years["boundary_basis"] = "detected_per_year"
        state = replace(state, hydro_years=years)
        return CatchmentAnalysis(
            regime=regime,
            route="per_year_detection",
            route_reason=(
                f"seasonal record (SNR {regime.amplitude_snr:.2f}, trough timing "
                f"CI lower bound {regime.trough_timing_concentration_ci_low:.2f}): "
                "per-year boundaries are reproducible"
            ),
            hydro_years=years,
            events=events,
            monthly=pd.DataFrame(),
            state=state,
            climatological_peak_month=regime.climatological_peak_month,
            climatological_trough_month=regime.climatological_trough_month,
            monthly_phase=state.monthly_phase,
            warnings=tuple(warnings),
            quality_policy=quality_policy,
            max_invalid_pct=max_invalid_pct,
            decision_policy=regime.decision_policy,
            challenger=regime.challenger,
        )

    if not regime.supports_fixed_window:
        return CatchmentAnalysis(
            regime=regime,
            route="event_characterisation",
            route_reason=(
                f"{regime.regime} record (SNR {regime.amplitude_snr:.2f}): complex or "
                "diffuse timing does not support a fixed climatological window, so no "
                "hydrological year is defined"
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
            decision_policy=regime.decision_policy,
            challenger=regime.challenger,
        )

    # Imposed fixed climatological window route
    config_fixed = _fixed_config_from_climatology(int(regime.climatological_peak_month))
    try:
        years = detect_hydrological_years(
            extent,
            value_col=value_col,
            date_col=date_col,
            config=config_fixed,
            quality_policy="flag",
            missing_month_policy="ignore",
        )
    except ValueError as exc:
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
            decision_policy=regime.decision_policy,
            challenger=regime.challenger,
        )

    route = "fixed_climatological_window"
    basis = "imposed_fixed_window"
    reason = (
        f"{regime.regime} record (SNR {regime.amplitude_snr:.2f}): timing evidence "
        "supports a fixed climatological window, so it is imposed on every year"
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
        if canonical_scheme != "none":
            phase_input = prepare_monthly_extent(
                extent,
                value_col=value_col,
                date_col=date_col,
                max_invalid_pct=max_invalid_pct,
                quality_policy=quality_policy,
            )
            _, noise_pp = robust_scale(phase_input)
            dyn_cfg = DynamicHydroYearConfig(
                expected_trough_month=int(regime.climatological_trough_month or 1),
                expected_peak_month=int(regime.climatological_peak_month or 7),
                phase_scheme=canonical_scheme,
            )
            monthly_phase = assign_monthly_phases(
                phase_input,
                years,
                dyn_cfg,
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
        decision_policy=regime.decision_policy,
        challenger=regime.challenger,
    )
