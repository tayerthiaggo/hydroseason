from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import (
    _RAW_MINIMUM_REL_TOLERANCE,
    RobustBoundaryConfig,
    robust_scale,
    select_boundary_sequence,
    select_cycle_peak,
    select_window_minimum,
)
from ._seasonality import SeasonalPatternResult, classify_seasonal_pattern
from ._state_input import prepare_monthly_extent

# Fallback values substituted for the deprecated recovery-window fields when a
# caller has not supplied them. These match the historical defaults (2 and 4)
# so that the legacy `last_before_confirmed_recovery` dry_plateau_rule keeps
# behaving exactly as before during the one-release deprecation window.
_DEFAULT_SUSTAINED_RISE_MONTHS = 2
_DEFAULT_PULSE_REJECTION_WINDOW_MONTHS = 4


@dataclass(frozen=True)
class DynamicHydroYearConfig:
    expected_trough_month: int
    expected_peak_month: int | None = None
    trough_search_radius_months: int = 3
    dry_plateau_rule: Literal["raw_minimum", "last_before_confirmed_recovery", "middle", "first"] = "raw_minimum"
    sustained_rise_months: int | None = None
    pulse_rejection_window_months: int | None = None
    max_invalid_pct: float = 20.0
    allow_unknown_quality: bool = False
    min_usable_months_per_cycle: int = 8
    min_usable_trough_candidates: int = 2
    min_baseline_cycles: int = 10
    low_percentile: float = 20.0
    high_percentile: float = 80.0
    measurement_tolerance_pct: float = 1.0
    detector: Literal["robust_extrema", "semi_markov"] = "robust_extrema"

    def __post_init__(self) -> None:
        if self.expected_trough_month not in range(1, 13):
            raise ValueError("expected_trough_month must be in 1..12.")
        if self.expected_peak_month is not None and self.expected_peak_month not in range(1, 13):
            raise ValueError("expected_peak_month must be in 1..12.")
        if not 0 <= self.trough_search_radius_months <= 5:
            raise ValueError("trough_search_radius_months must be in 0..5.")
        if self.sustained_rise_months is not None and self.sustained_rise_months < 1:
            raise ValueError("recovery windows must be positive.")
        if self.pulse_rejection_window_months is not None and self.pulse_rejection_window_months < 1:
            raise ValueError("recovery windows must be positive.")
        if not 0 <= self.max_invalid_pct <= 100:
            raise ValueError("max_invalid_pct must be between 0 and 100.")
        if not 0 <= self.low_percentile < self.high_percentile <= 100:
            raise ValueError("condition percentiles must satisfy 0 <= low < high <= 100.")
        if self.measurement_tolerance_pct < 0:
            raise ValueError("measurement_tolerance_pct must be non-negative.")
        if self.detector not in {"robust_extrema", "semi_markov"}:
            raise ValueError("detector must be 'robust_extrema' or 'semi_markov'")
        if self.sustained_rise_months is not None or self.pulse_rejection_window_months is not None:
            warnings.warn(
                "recovery-window fields (sustained_rise_months, pulse_rejection_window_months) "
                "are deprecated and ignored by robust_extrema; they are retained only for "
                "backward compatibility with dry_plateau_rule='last_before_confirmed_recovery'.",
                DeprecationWarning,
                stacklevel=2,
            )
        if self.dry_plateau_rule == "last_before_confirmed_recovery":
            warnings.warn(
                "dry_plateau_rule='last_before_confirmed_recovery' is deprecated; use 'raw_minimum'.",
                DeprecationWarning,
                stacklevel=2,
            )

    @property
    def _effective_sustained_rise_months(self) -> int:
        return self.sustained_rise_months if self.sustained_rise_months is not None else _DEFAULT_SUSTAINED_RISE_MONTHS

    @property
    def _effective_pulse_rejection_window_months(self) -> int:
        return (
            self.pulse_rejection_window_months
            if self.pulse_rejection_window_months is not None
            else _DEFAULT_PULSE_REJECTION_WINDOW_MONTHS
        )


def suggest_dynamic_hydro_year_config(extent, *, pattern: SeasonalPatternResult | None = None, **overrides) -> DynamicHydroYearConfig:
    result = pattern or classify_seasonal_pattern(extent)
    user_supplied_trough = "expected_trough_month" in overrides
    expected_trough = overrides.pop("expected_trough_month", result.expected_trough_month)
    if expected_trough is None or result.pattern in {"weak_or_irregular", "low_variability", "insufficient_record"} and not user_supplied_trough:
        raise ValueError("No stable trough phase; supply expected_trough_month explicitly.")
    fields = {
        "expected_trough_month": expected_trough,
        "expected_peak_month": result.expected_peak_month,
    }
    fields.update(overrides)
    return DynamicHydroYearConfig(**fields)


def _month_delta(actual: pd.Timestamp, expected: pd.Timestamp) -> int:
    return (actual.year - expected.year) * 12 + actual.month - expected.month


# Diagnostic columns carried straight from each robust trough opportunity into
# the annual output for every year (resolved or unresolved), so the raw observed
# minimum and the evidence behind the selected boundary are always auditable.
_TROUGH_DIAGNOSTIC_COLUMNS = (
    "raw_trough_month", "raw_trough_extent_pct",
    "low_run_start_month", "low_run_end_month",
    "window_status", "selection_status", "selection_support",
    "window_n_expected", "window_n_usable", "phase_shift_months",
)


def _find_robust_trough_opportunities(frame: pd.DataFrame, config: DynamicHydroYearConfig) -> pd.DataFrame:
    """One trough opportunity per nominal year from the robust boundary engine.

    Robust scale is estimated once over the whole record. For each expected
    trough window the raw observed minimum, its contiguous equivalent low run,
    and coverage evidence come from ``select_window_minimum`` (the raw extremum
    is never silently replaced).     A globally consistent boundary date is then
    chosen per year by ``select_boundary_sequence`` over each year's equivalent
    low run only. That run is built from ``select_window_minimum``'s *absolute*
    noise-band epsilon, which two independent real rivers showed is too loose
    relative to near-zero troughs (a sub-noise 0.01pp gap can still be a 50%
    jump above a 0.02pp minimum). We therefore hand the sequence optimizer a
    *relative* fidelity tolerance so a cycle-coherent shift can only move onto
    months that are within measurement noise of the year's raw minimum, never
    onto a materially higher month.
    """
    amplitude_pp, noise_pp = robust_scale(frame)
    boundary_config = RobustBoundaryConfig(min_usable_candidates=config.min_usable_trough_candidates)
    expected_count = 2 * config.trough_search_radius_months + 1

    years = list(range(int(frame.index.min().year), int(frame.index.max().year) + 1))
    selections = []
    expecteds = []
    sequence_input: list[dict] = []
    for year in years:
        expected = pd.Timestamp(year, config.expected_trough_month, 1)
        start = expected - pd.DateOffset(months=config.trough_search_radius_months)
        end = expected + pd.DateOffset(months=config.trough_search_radius_months)
        window = frame.loc[start:end]
        selection = select_window_minimum(
            window, expected=expected, expected_count=expected_count,
            noise_pp=noise_pp, amplitude_pp=amplitude_pp, config=boundary_config,
        )
        selections.append(selection)
        expecteds.append(expected)
        if selection.run_start is not None and selection.run_end is not None:
            run = frame.loc[selection.run_start:selection.run_end]
            run = run.loc[run["candidate_usable"]]
            candidates = [(pd.Timestamp(month), float(value)) for month, value in run["extent_pct"].items()]
        else:
            candidates = []
        sequence_input.append({"year": year, "expected": expected, "candidates": candidates})

    selected_dates = select_boundary_sequence(
        sequence_input, raw_minimum_rel_tolerance=_RAW_MINIMUM_REL_TOLERANCE
    )

    rows = []
    for year, expected, selection, selected in zip(years, expecteds, selections, selected_dates):
        row = {
            "hy_year": year,
            "status": "unresolved",
            "status_reason": "insufficient_trough_candidates",
            "trough_month": pd.NaT,
            "trough_extent_pct": np.nan,
            "trough_invalid_pct": np.nan,
            "boundary_status": "provisional",
            "phase_shift_months": np.nan,
            "raw_trough_month": selection.raw_month if selection.raw_month is not None else pd.NaT,
            "raw_trough_extent_pct": selection.raw_extent_pct,
            "low_run_start_month": selection.run_start if selection.run_start is not None else pd.NaT,
            "low_run_end_month": selection.run_end if selection.run_end is not None else pd.NaT,
            "window_status": selection.window_status,
            "selection_status": selection.selection_status,
            "selection_support": selection.support,
            "window_n_expected": selection.n_expected,
            "window_n_usable": selection.n_usable,
        }
        if selected is None:
            rows.append(row)
            continue
        selected = pd.Timestamp(selected)
        observed = frame.loc[selected]
        confirmed = (
            selection.window_status == "full"
            and selection.selection_status == "raw"
            and selection.support >= boundary_config.support_threshold
        )
        row.update(
            status="complete" if confirmed else "partial",
            status_reason="ok" if confirmed else "boundary_provisional",
            trough_month=selected,
            trough_extent_pct=float(observed["extent_pct"]),
            trough_invalid_pct=float(observed["invalid_pct"]) if pd.notna(observed["invalid_pct"]) else np.nan,
            boundary_status="confirmed" if confirmed else "provisional",
            phase_shift_months=_month_delta(selected, expected),
        )
        rows.append(row)
    return pd.DataFrame(rows)


ANNUAL_COLUMNS = [
    "hy_year", "status", "status_reason", "hy_start", "hy_end", "cycle_months",
    "peak_month", "peak_extent_pct", "peak_invalid_pct",
    "temporal_mid_dry_month", "temporal_mid_dry_extent_pct",
    "half_loss_month", "half_loss_extent_pct", "half_loss_target_pct",
    "trough_month", "trough_extent_pct", "trough_invalid_pct", "boundary_status",
    "drawdown_pct", "persistence_ratio", "recession_months", "half_loss_months",
    "n_rewetting_pulses", "n_usable_months", "confidence",
    "secondary_peak_month", "secondary_peak_extent_pct",
    "secondary_trough_month", "secondary_trough_extent_pct",
    "raw_trough_month", "raw_trough_extent_pct",
    "low_run_start_month", "low_run_end_month",
    "window_status", "selection_status", "selection_support",
    "window_n_expected", "window_n_usable", "phase_shift_months",
    "raw_peak_month", "raw_peak_extent_pct",
    "peak_selection_status", "peak_selection_support",
]


def _nearest_month(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp:
    target = start + (end - start) / 2
    return pd.Timestamp(index[int(np.argmin(np.abs(index - target)))])


def _secondary_extrema(series: pd.Series, peak: pd.Timestamp, trough: pd.Timestamp) -> tuple[pd.Timestamp | None, float, pd.Timestamp | None, float]:
    values = series.to_numpy(float)
    peaks = [i for i in range(1, len(values) - 1) if values[i] > values[i - 1] and values[i] >= values[i + 1] and abs(i - series.index.get_loc(peak)) >= 2]
    troughs = [i for i in range(1, len(values) - 1) if values[i] < values[i - 1] and values[i] <= values[i + 1] and abs(i - series.index.get_loc(trough)) >= 2]
    secondary_peak = max(peaks, key=lambda i: values[i]) if peaks else None
    secondary_trough = min(troughs, key=lambda i: values[i]) if troughs else None
    return (
        pd.Timestamp(series.index[secondary_peak]) if secondary_peak is not None else None,
        float(values[secondary_peak]) if secondary_peak is not None else np.nan,
        pd.Timestamp(series.index[secondary_trough]) if secondary_trough is not None else None,
        float(values[secondary_trough]) if secondary_trough is not None else np.nan,
    )


def _confidence(cycle: pd.DataFrame, boundary_status: str) -> str:
    usable_fraction = float(cycle["candidate_usable"].mean())
    observed = cycle.loc[cycle["candidate_usable"], "observed_fraction"]
    quality = float(observed.mean()) if observed.notna().any() else 0.5
    score = usable_fraction * quality * (0.75 if boundary_status == "provisional" else 1.0)
    if (cycle["quality_state"] == "unknown").any():
        score = min(score, 0.59)
    return "high" if score >= 0.80 else "medium" if score >= 0.60 else "low"


def _blank_cycle(opportunity: pd.Series) -> dict:
    row = {column: np.nan for column in ANNUAL_COLUMNS}
    row.update(
        hy_year=int(opportunity["hy_year"]), status=opportunity["status"],
        status_reason=opportunity["status_reason"], trough_month=opportunity["trough_month"],
        trough_extent_pct=opportunity["trough_extent_pct"], trough_invalid_pct=opportunity["trough_invalid_pct"],
        boundary_status=opportunity["boundary_status"], confidence="low",
    )
    for column in _TROUGH_DIAGNOSTIC_COLUMNS:
        row[column] = opportunity[column]
    return row


def detect_dynamic_hydrological_years(extent, *, config: DynamicHydroYearConfig, value_col: str = "extent_pct", date_col: str | None = None, pattern: SeasonalPatternResult | None = None) -> pd.DataFrame:
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=config.max_invalid_pct,
        allow_unknown_quality=config.allow_unknown_quality,
    )
    opportunities = _find_robust_trough_opportunities(frame, config)
    amplitude_pp, noise_pp = robust_scale(frame)
    rows = []
    previous = None
    for _, opportunity in opportunities.iterrows():
        row = _blank_cycle(opportunity)
        if pd.isna(opportunity["trough_month"]):
            previous = None
            rows.append(row)
            continue
        if previous is None:
            row.update(status="partial", status_reason="no_previous_boundary")
            previous = opportunity
            rows.append(row)
            continue
        start = pd.Timestamp(previous["trough_month"]) + pd.DateOffset(months=1)
        end = pd.Timestamp(opportunity["trough_month"])
        cycle = frame.loc[start:end]
        usable = cycle.loc[cycle["candidate_usable"], "extent_pct"]
        if len(usable) < config.min_usable_months_per_cycle:
            row.update(status="partial", status_reason="insufficient_cycle_coverage", hy_start=start, hy_end=end, cycle_months=len(cycle), n_usable_months=len(usable))
            previous = opportunity
            rows.append(row)
            continue
        previous_trough = pd.Timestamp(previous["trough_month"])
        peak_selection = select_cycle_peak(
            cycle, start=previous_trough, end=end, noise_pp=noise_pp, amplitude_pp=amplitude_pp,
        )
        if peak_selection.selected_month is None:
            row.update(status="partial", status_reason="insufficient_cycle_coverage", hy_start=start, hy_end=end, cycle_months=len(cycle), n_usable_months=len(usable))
            previous = opportunity
            rows.append(row)
            continue
        peak = pd.Timestamp(peak_selection.selected_month)
        post_peak = usable.loc[peak:end]
        trough = end
        peak_value, trough_value = float(usable.loc[peak]), float(frame.loc[trough, "extent_pct"])
        target = (peak_value + trough_value) / 2.0
        half_candidates = post_peak.loc[post_peak <= target]
        half = pd.Timestamp(half_candidates.index[0]) if len(half_candidates) else pd.NaT
        midpoint = _nearest_month(post_peak.index, peak, trough)
        post = cycle.loc[peak:end, ["extent_pct", "candidate_usable"]]
        delta = post["extent_pct"].diff()
        month_number = post.index.year * 12 + post.index.month
        adjacent = pd.Series(
            np.diff(month_number, prepend=month_number[0] - 1) == 1,
            index=post.index,
        )
        rise = post["candidate_usable"] & post["candidate_usable"].shift(fill_value=False) & adjacent & delta.gt(noise_pp)
        pulses = int((rise & ~rise.shift(fill_value=False)).sum())
        secondary = _secondary_extrema(usable, peak, trough) if pattern is not None and pattern.pattern == "bimodal_or_complex" else (None, np.nan, None, np.nan)
        peak_invalid = frame.loc[peak, "invalid_pct"]
        row.update(
            status="complete" if opportunity["boundary_status"] == "confirmed" else "partial",
            status_reason="ok" if opportunity["boundary_status"] == "confirmed" else "boundary_provisional",
            hy_start=start, hy_end=end, cycle_months=len(cycle),
            peak_month=peak, peak_extent_pct=peak_value,
            peak_invalid_pct=float(peak_invalid) if pd.notna(peak_invalid) else np.nan,
            temporal_mid_dry_month=midpoint, temporal_mid_dry_extent_pct=float(frame.loc[midpoint, "extent_pct"]),
            half_loss_month=half, half_loss_extent_pct=float(frame.loc[half, "extent_pct"]) if pd.notna(half) else np.nan,
            half_loss_target_pct=target, trough_month=trough, trough_extent_pct=trough_value,
            trough_invalid_pct=opportunity["trough_invalid_pct"], boundary_status=opportunity["boundary_status"],
            drawdown_pct=peak_value - trough_value,
            persistence_ratio=trough_value / peak_value if peak_value > 0 else np.nan,
            recession_months=_month_delta(trough, peak),
            half_loss_months=_month_delta(half, peak) if pd.notna(half) else np.nan,
            n_rewetting_pulses=pulses, n_usable_months=len(usable), confidence=_confidence(cycle, opportunity["boundary_status"]),
            secondary_peak_month=secondary[0], secondary_peak_extent_pct=secondary[1],
            secondary_trough_month=secondary[2], secondary_trough_extent_pct=secondary[3],
            raw_peak_month=peak_selection.raw_month if peak_selection.raw_month is not None else pd.NaT,
            raw_peak_extent_pct=peak_selection.raw_extent_pct,
            peak_selection_status=peak_selection.selection_status,
            peak_selection_support=peak_selection.support,
        )
        previous = opportunity
        rows.append(row)
    return pd.DataFrame(rows, columns=ANNUAL_COLUMNS)
