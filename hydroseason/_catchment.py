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

import pandas as pd

from ._decision_policy import DECISION_POLICY, DecisionPolicy, Route
from ._dynamic_year import DynamicHydroYearConfig
from ._events import WaterEventResult, extract_water_events
from ._method_policy import CURRENT_METHOD_POLICY, method_policy_fingerprint
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

_CYCLE_TIMING_INFORMATIVE_STATUSES: frozenset[str] = frozenset({"point", "interval", "broad"})


@dataclass(frozen=True)
class CatchmentAnalysis:
    """Everything the record supports, plus how that was decided."""

    regime: WaterRegimeAssessment
    route: Route
    route_reason: str
    hydro_years: pd.DataFrame
    events: WaterEventResult
    monthly: pd.DataFrame
    mean_monthly_peak_month: int | None = None
    mean_monthly_trough_month: int | None = None
    monthly_phase: pd.DataFrame | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    state: HydrologicalStateResult | None = None
    quality_policy: QualityPolicy = "flag"
    max_invalid_pct: float = 20.0
    decision_policy: DecisionPolicy = DECISION_POLICY
    method_policy_id: str = CURRENT_METHOD_POLICY.policy_id
    method_policy_fingerprint: str = field(
        default_factory=method_policy_fingerprint
    )
    random_state: int = 0

    @property
    def public_route(self) -> Route:
        return self.route

    def summary_row(self, *, name: str) -> dict:
        """Flat one-row-per-catchment record for a cross-catchment table."""
        return {
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
            "n_peak_timing_years": self.regime.n_peak_timing_years,
            "n_trough_timing_years": self.regime.n_trough_timing_years,
            "n_zero_months": self.regime.n_zero_months,
            "zero_month_fraction": _rounded(self.regime.zero_month_fraction, 4),
            "n_whole_zero_years": self.regime.n_whole_zero_years,
            "pixel_support_status": self.regime.pixel_support_status,
            "timing_evidence": self.regime.timing_evidence,
            "n_usable_years": self.regime.n_usable_years,
            "n_usable_months": self.regime.n_usable_months,
            "n_hydro_years": int(len(self.hydro_years)),
            "boundary_basis": (
                str(self.hydro_years["boundary_basis"].iloc[0])
                if not self.hydro_years.empty
                else "none"
            ),
            "mean_monthly_peak_month": self.mean_monthly_peak_month,
            "mean_monthly_trough_month": self.mean_monthly_trough_month,
            "n_wet_events": self.events.summary["n_events"],
            "median_event_duration_months": self.events.summary["median_event_duration_months"],
            "longest_low_spell_months": self.events.summary["longest_low_spell_months"],
            "median_recurrence_months": self.events.summary["median_recurrence_months"],
            "years_without_wet_event": self.regime.years_without_wet_event,
        }


def _rounded(value: float | None, decimals: int) -> float | None:
    """Round optional scalar diagnostics without introducing non-serialisable values."""
    return round(value, decimals) if value is not None else None


def _policy_evidence(regime: WaterRegimeAssessment) -> str:
    """Name the evidence the active policy actually decided on."""
    test = regime.seasonality_test
    if test is None:
        return f"SNR {regime.amplitude_snr:.2f}"
    peak_p = "n/a" if test.peak.uniformity_p is None else f"{test.peak.uniformity_p:.3f}"
    trough_p = "n/a" if test.trough.uniformity_p is None else f"{test.trough.uniformity_p:.3f}"
    return f"peak p={peak_p}, trough p={trough_p}"


def analyze_catchment(
    extent,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    min_months_per_year: int = 9,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "flag",
    measurement_tolerance_pct: float = 0.0,
    phase_scheme: PhaseScheme | UnsetPhaseScheme = PHASE_SCHEME_UNSET,
    phase_model: LegacyPhaseModel | None = None,
    n_bootstrap: int = 200,
    random_state: int = 0,
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
        measurement_tolerance_pct=measurement_tolerance_pct,
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
            decision_policy=regime.decision_policy,
            random_state=random_state,
        )

    if regime.regime == "seasonal":
        try:
            state_extent = prepare_monthly_extent(
                extent,
                value_col=value_col,
                date_col=date_col,
                max_invalid_pct=max_invalid_pct,
                quality_policy=quality_policy,
            )
            operational_climatology = state_extent.loc[
                state_extent["candidate_usable"]
            ].groupby(state_extent.loc[state_extent["candidate_usable"]].index.month)[
                "extent_pct"
            ].mean()
            operational_peak_month = (
                regime.mean_monthly_peak_month
                if regime.mean_monthly_peak_month is not None
                else int(operational_climatology.idxmax())
            )
            operational_trough_month = (
                regime.mean_monthly_trough_month
                if regime.mean_monthly_trough_month is not None
                else int(operational_climatology.idxmin())
            )
            if (
                regime.mean_monthly_peak_month is None
                or regime.mean_monthly_trough_month is None
            ):
                warnings.append(
                    "a diffuse annual timing summary has no dominant month; "
                    "the dynamic detector uses a private mean-monthly-extent anchor"
                )
            config = DynamicHydroYearConfig(
                expected_trough_month=operational_trough_month,
                expected_peak_month=operational_peak_month,
                max_invalid_pct=max_invalid_pct,
                quality_policy=quality_policy,
                measurement_tolerance_pct=measurement_tolerance_pct,
                detector="robust_extrema",
                phase_scheme=canonical_scheme,
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
                random_state=random_state,
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
                random_state=random_state,
            )
        years["boundary_basis"] = "detected_per_year"
        state = replace(state, hydro_years=years)

        min_informative = config.timing_identifiability_thresholds.min_informative_years
        n_peak_cycles = (
            int(years["peak_timing_status"].isin(_CYCLE_TIMING_INFORMATIVE_STATUSES).sum())
            if "peak_timing_status" in years.columns
            else 0
        )
        n_trough_cycles = (
            int(years["trough_timing_status"].isin(_CYCLE_TIMING_INFORMATIVE_STATUSES).sum())
            if "trough_timing_status" in years.columns
            else 0
        )
        cycles_support_timing = min(n_peak_cycles, n_trough_cycles) >= min_informative

        if not cycles_support_timing:
            reason = (
                f"{regime.regime} record ({_policy_evidence(regime)}): calendar-year "
                "timing evidence appeared sufficient, but the detected hydrological-year "
                f"cycles do not support it (peak cycles resolved={n_peak_cycles}, "
                f"trough cycles resolved={n_trough_cycles}, need >={min_informative} on "
                "each); using event characterisation"
            )
            warnings.append(reason)
            return CatchmentAnalysis(
                regime=regime,
                route="event_characterisation",
                route_reason=reason,
                hydro_years=empty_years,
                events=events,
                monthly=pd.DataFrame(),
                state=None,
                warnings=tuple(warnings),
                quality_policy=quality_policy,
                max_invalid_pct=max_invalid_pct,
                decision_policy=regime.decision_policy,
                random_state=random_state,
            )

        route_reason = (
            f"seasonal record ({_policy_evidence(regime)}): "
            "per-year dynamic boundaries are reproducible"
        )
        return CatchmentAnalysis(
            regime=regime,
            route="per_year_detection",
            route_reason=route_reason,
            hydro_years=years,
            events=events,
            monthly=pd.DataFrame(),
            state=state,
            mean_monthly_peak_month=regime.mean_monthly_peak_month,
            mean_monthly_trough_month=regime.mean_monthly_trough_month,
            monthly_phase=state.monthly_phase,
            warnings=tuple(warnings),
            quality_policy=quality_policy,
            max_invalid_pct=max_invalid_pct,
            decision_policy=regime.decision_policy,
            random_state=random_state,
        )

    route_reason = (
        f"{regime.regime} record ({_policy_evidence(regime)}): recurrence was not "
        "established, so no hydrological year is defined"
    )
    return CatchmentAnalysis(
        regime=regime,
        route="event_characterisation",
        route_reason=route_reason,
        hydro_years=empty_years,
        events=events,
        monthly=pd.DataFrame(),
        state=None,
        mean_monthly_peak_month=None,
        mean_monthly_trough_month=None,
        warnings=tuple(warnings),
        quality_policy=quality_policy,
        max_invalid_pct=max_invalid_pct,
        decision_policy=regime.decision_policy,
        random_state=random_state,
    )
