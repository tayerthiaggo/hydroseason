"""Regime-routed catchment analysis: one entry point, no operator decisions.

``analyze_catchment`` assesses the regime first, then dispatches to the
analysis that regime actually supports, and records which route it took and
why. Nothing prompts and nothing raises on a difficult record: a catchment
with no detectable annual cycle returns event descriptors and an empty
hydrological-year table rather than an exception or -- worse -- a full set of
confidently-labelled boundaries fitted to noise.

The three routes:

``per_year_detection``
    Seasonal or marginal record with supported boundary recoverability.
    Per-year peak and trough are reproducible, so the full dynamic pipeline
    runs and its boundaries are marked ``detected_per_year``.

``event_characterisation``
    Aseasonal record, or seasonal/marginal record without supported boundary
    recoverability. No hydrological year is defined. Wet episodes and
    low-extent spells carry the description instead.

``insufficient_record``
    Too few usable years to determine regime.

Event descriptors are computed on every route, since they are the one view
that never presumes a cycle exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

import pandas as pd

from ._boundary import RobustBoundaryConfig
from ._boundary_recoverability import RecoverabilityThresholds
from ._dynamic_year import DynamicHydroYearConfig
from ._events import WaterEventResult, extract_water_events
from ._evidence import EvidenceThresholds
from ._regime import PublicRoute, WaterRegimeAssessment, assess_water_regime, public_route
from ._state_input import QualityPolicy, prepare_monthly_extent
from .hydrological_state import HydrologicalStateResult, analyze_hydrological_state

Route = PublicRoute


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
    # Retain the quality policy used to construct this analysis so report
    # exports validate and label months against the same candidate set.
    quality_policy: QualityPolicy = "flag"
    max_invalid_pct: float = 20.0

    def summary_row(self, *, name: str) -> dict:
        """Flat one-row-per-catchment record for a cross-catchment table."""
        return {
            "catchment": name,
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


def _rounded(value: float | None, decimals: int) -> float | None:
    """Round optional scalar diagnostics without introducing non-serialisable values."""
    return round(value, decimals) if value is not None else None


def _is_publicly_confirmed(
    row: pd.Series,
    *,
    recoverability_state: str,
    min_selection_quality: float,
    min_cycle_coverage: float,
) -> bool:
    """Global and local evidence both constrain confirmation.

    A row can be locally immaculate and still not confirmable, because the
    record's trough phase does not reproduce out of sample. Confirmation is a
    claim about the boundary being right, not about the window being tidy.
    """
    return (
        recoverability_state == "supported"
        and row.get("window_status") == "full"
        and row.get("selection_status") == "raw"
        and float(row.get("selection_quality", 0.0)) >= min_selection_quality
        and row.get("peak_selection_status") not in {"unresolved", "low_quality"}
        and float(row.get("n_usable_months", 0.0)) >= min_cycle_coverage
    )


def analyze_catchment(
    extent,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    min_months_per_year: int = 9,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "flag",
    phase_model: Literal["none", "rule_based", "cycle_relative"] = "rule_based",
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
    if phase_model not in {"none", "rule_based", "cycle_relative"}:
        raise ValueError("phase_model must be 'none', 'rule_based', or 'cycle_relative'")

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

    route = public_route(regime.regime, regime.boundary_recoverability)

    if route == "insufficient_record":
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

    if route == "per_year_detection":
        try:
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
        except ValueError as exc:
            warnings.append(f"per-year boundary detection failed; using events: {exc}")
            return CatchmentAnalysis(
                regime=regime,
                route="event_characterisation",
                route_reason=(
                    f"per-year boundary detection failed despite supported recoverability: {exc}; "
                    "using event characterisation"
                ),
                hydro_years=empty_years,
                events=events,
                monthly=pd.DataFrame(),
                state=None,
                warnings=tuple(warnings),
                quality_policy=quality_policy,
                max_invalid_pct=max_invalid_pct,
            )
        years = state.hydro_years.copy()
        if not years.empty:
            years["boundary_basis"] = "detected_per_year"
            years["annual_cycle_evidence"] = regime.annual_cycle_evidence
            years["boundary_recoverability"] = regime.boundary_recoverability
            years["seasonal_cv_skill"] = regime.seasonal_cv_skill
            years["boundary_cv_coverage"] = regime.boundary_cv_coverage
            years["boundary_cv_within_1_month"] = regime.boundary_cv_within_1_month
            years["boundary_cv_p90_error_months"] = regime.boundary_cv_p90_error_months

            boundary_cfg = robust_boundary_config or RobustBoundaryConfig()
            min_qual = boundary_cfg.support_threshold
            min_cov = float(config.min_usable_months_per_cycle)

            for idx, row in years.iterrows():
                is_conf = _is_publicly_confirmed(
                    row,
                    recoverability_state=regime.boundary_recoverability,
                    min_selection_quality=min_qual,
                    min_cycle_coverage=min_cov,
                )
                if not is_conf and row.get("boundary_status") == "confirmed":
                    years.at[idx, "boundary_status"] = "provisional"
                    years.at[idx, "status"] = "partial"
                    if years.at[idx, "status_reason"] == "ok":
                        years.at[idx, "status_reason"] = "boundary_provisional"

        state = replace(state, hydro_years=years)
        return CatchmentAnalysis(
            regime=regime,
            route="per_year_detection",
            route_reason=(
                f"{regime.regime} record with supported boundary recoverability "
                f"({regime.boundary_recoverability_reason}): per-year boundaries are reproducible"
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

    # route == "event_characterisation"
    return CatchmentAnalysis(
        regime=regime,
        route="event_characterisation",
        route_reason=(
            f"{regime.regime} record with {regime.boundary_recoverability} boundary recoverability "
            f"({regime.boundary_recoverability_reason}): no hydrological year defined; "
            "using event characterisation"
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


__all__ = ["CatchmentAnalysis", "Route", "analyze_catchment"]
