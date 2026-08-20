from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import (
    RobustBoundaryConfig,
    robust_scale,
    select_boundary_sequence,
    select_cycle_peak,
    select_window_minimum,
)
from ._seasonality import SeasonalPatternResult, classify_seasonal_pattern
from ._semi_markov import SemiMarkovConfig, fit_semi_markov_boundaries
from ._state_input import QualityPolicy, prepare_monthly_extent

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
    quality_policy: QualityPolicy = "flag"
    min_usable_months_per_cycle: int = 8
    min_usable_trough_candidates: int = 2
    min_baseline_cycles: int = 10
    low_percentile: float = 20.0
    high_percentile: float = 80.0
    measurement_tolerance_pct: float = 1.0
    detector: Literal["robust_extrema"] = "robust_extrema"
    phase_model: Literal["none", "rule_based"] = "rule_based"

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
        if self.quality_policy not in {"exclude", "flag"}:
            raise ValueError("quality_policy must be 'exclude' or 'flag'.")
        if not 0 <= self.low_percentile < self.high_percentile <= 100:
            raise ValueError("condition percentiles must satisfy 0 <= low < high <= 100.")
        if self.measurement_tolerance_pct < 0:
            raise ValueError("measurement_tolerance_pct must be non-negative.")
        if self.detector != "robust_extrema":
            raise ValueError(
                "detector must be 'robust_extrema'; it is the only publicly "
                "supported boundary detector for released dynamic hydrological "
                "years (the semi-Markov challenger is internal-only, see "
                "hydroseason._dynamic_year._find_semi_markov_trough_opportunities)"
            )
        if self.phase_model not in {"none", "rule_based"}:
            raise ValueError("phase_model must be 'none' or 'rule_based'")
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
    and coverage evidence come from ``select_window_minimum``. The public
    detector keeps that observed minimum authoritative; sequence coherence is
    allowed to break only exact-value ties, and any resulting date change is
    labelled ``coherence_adjusted`` rather than reported as a raw selection.
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
            run = run.loc[run["extent_pct"].notna() & run["invalid_pct"].lt(100.0)]
            candidates = [(pd.Timestamp(month), float(value)) for month, value in run["extent_pct"].items()]
        else:
            candidates = []
        sequence_input.append({"year": year, "expected": expected, "candidates": candidates})

    selected_dates = select_boundary_sequence(
        sequence_input, raw_minimum_rel_tolerance=0.0
    )

    rows = []
    for year, expected, selection, selected in zip(years, expecteds, selections, selected_dates):
        selection_status = selection.selection_status
        if (
            selected is not None
            and selection.raw_month is not None
            and pd.Timestamp(selected) != pd.Timestamp(selection.raw_month)
            and selection_status != "low_quality"
        ):
            selection_status = "coherence_adjusted"
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
            "selection_status": selection_status,
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
            and selection_status == "raw"
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


def _find_semi_markov_trough_opportunities(frame: pd.DataFrame, config: DynamicHydroYearConfig) -> pd.DataFrame:
    """One trough opportunity per nominal year from the semi-Markov challenger.

    ``fit_semi_markov_boundaries`` is fit exactly once over the whole record
    (it is a global fit, unlike the robust engine's per-year window scan).
    Each nominal calendar year then claims the nearest entry in
    ``result.trough_months`` to its own expected phase, but only within
    ``config.trough_search_radius_months`` -- the same phase-window
    discipline the robust engine enforces via its own search window. A year
    that finds no in-window match, or whose nearest candidate has already
    been claimed by an earlier year (a defensive dedup that mirrors
    ``_select_troughs``'s own "already used" guard; the window discipline
    above means it should not normally trigger), reports ``"unresolved"``
    with ``trough_month = pd.NaT``.

    This engine has no raw-vs-selected distinction (the transition-posterior
    argmax IS the only candidate) and no window/run diagnostics (no
    expected-window truncation concept), so several of the shared opportunity
    columns are filled with engine-appropriate placeholders documented on
    each field below rather than left to mean something they do not here.
    """
    result = fit_semi_markov_boundaries(
        frame, expected_trough_month=config.expected_trough_month, config=SemiMarkovConfig()
    )
    trough_months = list(result.trough_months)
    trough_support = list(result.trough_support)
    used = [False] * len(trough_months)

    years = list(range(int(frame.index.min().year), int(frame.index.max().year) + 1))
    rows = []
    for year in years:
        expected = pd.Timestamp(year, config.expected_trough_month, 1)
        best_index, best_distance = None, None
        for index, month in enumerate(trough_months):
            if used[index]:
                continue
            distance = abs(_month_delta(pd.Timestamp(month), expected))
            if distance > config.trough_search_radius_months:
                continue
            if best_distance is None or distance < best_distance:
                best_index, best_distance = index, distance

        row = {
            "hy_year": year,
            "status": "unresolved",
            "status_reason": "insufficient_trough_candidates",
            "trough_month": pd.NaT,
            "trough_extent_pct": np.nan,
            "trough_invalid_pct": np.nan,
            "boundary_status": "provisional",
            "phase_shift_months": np.nan,
            "raw_trough_month": pd.NaT,
            "raw_trough_extent_pct": np.nan,
            "low_run_start_month": pd.NaT,
            "low_run_end_month": pd.NaT,
            "window_status": "full",
            "selection_status": "raw",
            "selection_support": np.nan,
            "window_n_expected": np.nan,
            "window_n_usable": np.nan,
        }
        if best_index is None:
            rows.append(row)
            continue

        used[best_index] = True
        selected = pd.Timestamp(trough_months[best_index])
        support = float(np.clip(trough_support[best_index], 0.0, 1.0))
        observed = frame.loc[selected]
        confirmed = support >= RobustBoundaryConfig().support_threshold
        row.update(
            status="complete" if confirmed else "partial",
            status_reason="ok" if confirmed else "boundary_provisional",
            trough_month=selected,
            trough_extent_pct=float(observed["extent_pct"]),
            trough_invalid_pct=float(observed["invalid_pct"]) if pd.notna(observed["invalid_pct"]) else np.nan,
            boundary_status="confirmed" if confirmed else "provisional",
            phase_shift_months=_month_delta(selected, expected),
            raw_trough_month=selected,
            raw_trough_extent_pct=float(observed["extent_pct"]),
            selection_support=support,
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


def _position_of(index: pd.DatetimeIndex, month: pd.Timestamp) -> int:
    """``month``'s position in ``index``, or where it would be inserted.

    ``_secondary_extrema`` is handed the cycle's USABLE months, but its
    ``peak``/``trough`` arguments come from the unfiltered cycle -- a peak may
    be a ``low_quality`` month, and the trough is the cycle's end month, so
    neither is guaranteed to have survived the usability filter. An exact
    ``Index.get_loc`` raises ``KeyError`` in that case and takes the whole
    analysis down with it. The distance test this feeds ("keep secondary
    extrema at least 2 months clear of the primary one") stays meaningful
    when the primary month is missing: measure from the position it would
    occupy, which is what ``searchsorted`` returns.
    """
    position = int(index.searchsorted(month))
    return min(position, len(index) - 1) if len(index) else 0


def _secondary_extrema(series: pd.Series, peak: pd.Timestamp, trough: pd.Timestamp) -> tuple[pd.Timestamp | None, float, pd.Timestamp | None, float]:
    values = series.to_numpy(float)
    peak_position = _position_of(series.index, peak)
    trough_position = _position_of(series.index, trough)
    peaks = [i for i in range(1, len(values) - 1) if values[i] > values[i - 1] and values[i] >= values[i + 1] and abs(i - peak_position) >= 2]
    troughs = [i for i in range(1, len(values) - 1) if values[i] < values[i - 1] and values[i] <= values[i + 1] and abs(i - trough_position) >= 2]
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
    """Public, released entry point: robust-extrema is the sole boundary authority.

    ``config.detector`` only ever accepts ``"robust_extrema"`` (enforced by
    ``DynamicHydroYearConfig.__post_init__``), so this always dispatches to
    ``_find_robust_trough_opportunities``. The semi-Markov challenger stays
    reachable only through the internal
    ``_detect_dynamic_hydrological_years_experimental`` dispatcher used by
    experimental/internal tests (see tests/test_detector_comparison.py).
    """
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=config.max_invalid_pct,
        allow_unknown_quality=config.allow_unknown_quality,
        quality_policy=config.quality_policy,
    )
    opportunities = _find_robust_trough_opportunities(frame, config)
    return _assemble_dynamic_years(frame, opportunities, config, pattern)


def _detect_dynamic_hydrological_years_experimental(
    extent, *, config: DynamicHydroYearConfig, detector: Literal["robust_extrema", "semi_markov"],
    value_col: str = "extent_pct", date_col: str | None = None, pattern: SeasonalPatternResult | None = None,
) -> pd.DataFrame:
    """Internal-only dispatcher that allows the semi-Markov challenger.

    Not part of the public API and not reachable through
    ``DynamicHydroYearConfig``/``detect_dynamic_hydrological_years`` (which are
    robust-extrema only per the release contract). Exists solely for the
    experimental promotion-gate comparison harness
    (tests/test_detector_comparison.py) and must never be imported from
    released, public code paths.
    """
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=config.max_invalid_pct,
        allow_unknown_quality=config.allow_unknown_quality,
        quality_policy=config.quality_policy,
    )
    if detector == "robust_extrema":
        opportunities = _find_robust_trough_opportunities(frame, config)
    elif detector == "semi_markov":
        opportunities = _find_semi_markov_trough_opportunities(frame, config)
    else:
        raise ValueError(f"unknown detector {detector!r}")
    return _assemble_dynamic_years(frame, opportunities, config, pattern)


def _assemble_dynamic_years(
    frame: pd.DataFrame, opportunities: pd.DataFrame, config: DynamicHydroYearConfig,
    pattern: SeasonalPatternResult | None,
) -> pd.DataFrame:
    """Shared, detector-agnostic annual-cycle assembly from trough opportunities."""
    amplitude_pp, noise_pp = robust_scale(frame)
    rows = []
    previous = None
    for position, (_, opportunity) in enumerate(opportunities.iterrows()):
        row = _blank_cycle(opportunity)
        used_record_start = False
        if pd.isna(opportunity["trough_month"]):
            previous = None
            rows.append(row)
            continue
        if previous is None:
            if position == 0:
                # Nothing precedes this opportunity at all, so the record's
                # own first observed month is a legitimate stand-in for the
                # previous trough. A mid-record reset (position > 0) is a
                # different situation: a gap broke the chain there, and
                # synthesizing a boundary would invent data across it.
                synthetic_previous = opportunity.copy()
                synthetic_previous["trough_month"] = (
                    frame.index.min() - pd.DateOffset(months=1)
                )
                previous = synthetic_previous
                used_record_start = True
                # Fall through into the normal assembly branch below.
            else:
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
        peak_value, trough_value = float(frame.loc[peak, "extent_pct"]), float(frame.loc[trough, "extent_pct"])
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
        peak_low_quality = peak_selection.selection_status == "low_quality"
        boundary_status = (
            "provisional"
            if peak_low_quality
            or used_record_start
            or opportunity["boundary_status"] != "confirmed"
            else "confirmed"
        )
        status_reason = (
            "record_start_boundary"
            if used_record_start
            else "peak_low_quality"
            if peak_low_quality
            else "ok"
            if boundary_status == "confirmed"
            else "boundary_provisional"
        )
        row.update(
            status="complete" if boundary_status == "confirmed" else "partial",
            status_reason=status_reason,
            hy_start=start, hy_end=end, cycle_months=len(cycle),
            peak_month=peak, peak_extent_pct=peak_value,
            peak_invalid_pct=float(peak_invalid) if pd.notna(peak_invalid) else np.nan,
            temporal_mid_dry_month=midpoint, temporal_mid_dry_extent_pct=float(frame.loc[midpoint, "extent_pct"]),
            half_loss_month=half, half_loss_extent_pct=float(frame.loc[half, "extent_pct"]) if pd.notna(half) else np.nan,
            half_loss_target_pct=target, trough_month=trough, trough_extent_pct=trough_value,
            trough_invalid_pct=opportunity["trough_invalid_pct"], boundary_status=boundary_status,
            drawdown_pct=peak_value - trough_value,
            persistence_ratio=trough_value / peak_value if peak_value > 0 else np.nan,
            recession_months=_month_delta(trough, peak),
            half_loss_months=_month_delta(half, peak) if pd.notna(half) else np.nan,
            n_rewetting_pulses=pulses, n_usable_months=len(usable), confidence=_confidence(cycle, boundary_status),
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
