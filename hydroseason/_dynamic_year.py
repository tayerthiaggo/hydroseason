from __future__ import annotations

import warnings
from dataclasses import dataclass
from numbers import Integral
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
from ._phase_scheme import (
    PHASE_SCHEME_UNSET,
    LegacyPhaseModel,
    PhaseScheme,
    UnsetPhaseScheme,
    resolve_phase_scheme,
)
from ._scientific_defaults import PHASE_DEFAULTS
from ._seasonality import SeasonalPatternResult, classify_seasonal_pattern
from ._state_input import QualityPolicy, prepare_monthly_extent

# Fallback values substituted for the deprecated recovery-window fields when a
# caller has not supplied them. These match the historical defaults (2 and 4)
# so that the legacy `last_before_confirmed_recovery` dry_plateau_rule keeps
# behaving exactly as before during the one-release deprecation window.
_DEFAULT_SUSTAINED_RISE_MONTHS = 2
_DEFAULT_PULSE_REJECTION_WINDOW_MONTHS = 4

# The released detector stays conservative by default (3-month boundary
# window, 8 usable months).  A short cycle is only allowed to use this wider
# geometry after the base pass has found it between two usable boundaries.
_ADAPTIVE_TROUGH_SEARCH_RADIUS_MONTHS = 5
_ADAPTIVE_MIN_USABLE_MONTHS_PER_CYCLE = 6


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
    min_baseline_cycles: int = 5
    low_percentile: float = 20.0
    high_percentile: float = 80.0
    measurement_tolerance_pct: float = 1.0
    detector: Literal["robust_extrema"] = "robust_extrema"
    phase_scheme: PhaseScheme | UnsetPhaseScheme = PHASE_SCHEME_UNSET
    phase_model: LegacyPhaseModel | None = None
    phase_low_fraction: float = PHASE_DEFAULTS.phase_low_fraction
    phase_high_fraction: float = PHASE_DEFAULTS.phase_high_fraction
    phase_min_duration_months: int = PHASE_DEFAULTS.phase_min_duration_months
    phase_smoothing_window: int = PHASE_DEFAULTS.phase_smoothing_window

    def __post_init__(self) -> None:
        canonical = resolve_phase_scheme(
            phase_scheme=self.phase_scheme,
            phase_model=self.phase_model,
        )
        object.__setattr__(self, "phase_scheme", canonical)
        object.__setattr__(self, "phase_model", None)

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
            raise ValueError("detector must be 'robust_extrema'.")
        fractions = (self.phase_low_fraction, self.phase_high_fraction)
        if not all(np.isfinite(value) for value in fractions) or not (
            0.0 <= self.phase_low_fraction < self.phase_high_fraction <= 1.0
        ):
            raise ValueError(
                "phase band fractions must satisfy 0 <= phase_low_fraction "
                "< phase_high_fraction <= 1"
            )
        if (
            isinstance(self.phase_min_duration_months, bool)
            or not isinstance(self.phase_min_duration_months, Integral)
            or self.phase_min_duration_months < 1
        ):
            raise ValueError("phase_min_duration_months must be at least 1")
        if (
            isinstance(self.phase_smoothing_window, bool)
            or not isinstance(self.phase_smoothing_window, Integral)
            or self.phase_smoothing_window < 1
            or self.phase_smoothing_window % 2 == 0
        ):
            raise ValueError("phase_smoothing_window must be an odd positive integer")

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
    "window_status", "selection_status", "selection_support", "selection_quality",
    "window_n_expected", "window_n_usable", "phase_shift_months",
)


def _find_robust_trough_opportunities(
    frame: pd.DataFrame,
    config: DynamicHydroYearConfig,
    *,
    radius_by_year: dict[int, int] | None = None,
    fixed_trough_months: dict[int, pd.Timestamp] | None = None,
    not_later_than: dict[int, pd.Timestamp] | None = None,
    fallback_trough_months: dict[int, pd.Timestamp] | None = None,
) -> pd.DataFrame:
    amplitude_pp, noise_pp = robust_scale(frame)
    boundary_config = RobustBoundaryConfig(min_usable_candidates=config.min_usable_trough_candidates)
    radius_by_year = radius_by_year or {}
    fixed_trough_months = fixed_trough_months or {}
    not_later_than = not_later_than or {}
    fallback_trough_months = fallback_trough_months or {}

    years = list(range(int(frame.index.min().year), int(frame.index.max().year) + 1))
    selections = []
    expecteds = []
    sequence_input: list[dict] = []
    for year in years:
        radius = radius_by_year.get(year, config.trough_search_radius_months)
        expected_count = 2 * radius + 1
        expected = pd.Timestamp(year, config.expected_trough_month, 1)
        start = expected - pd.DateOffset(months=radius)
        end = expected + pd.DateOffset(months=radius)
        window = frame.loc[start:end]
        selection = select_window_minimum(
            window, expected=expected, expected_count=expected_count,
            noise_pp=noise_pp, amplitude_pp=amplitude_pp, config=boundary_config,
        )
        selections.append(selection)
        expecteds.append(expected)
        if selection.run_start is not None and selection.run_end is not None:
            run = frame.loc[selection.run_start:selection.run_end]
            if selection.selection_status == "quality_adjusted":
                if "quality_state" in run.columns:
                    run = run.loc[run["quality_state"].isin(["usable", "unknown"]) & run["extent_pct"].notna()]
                elif "candidate_usable" in run.columns:
                    run = run.loc[run["candidate_usable"] & run["extent_pct"].notna()]
                elif "invalid_pct" in run.columns:
                    run = run.loc[run["invalid_pct"].le(20.0) & run["extent_pct"].notna()]
                else:
                    run = run.loc[run["extent_pct"].notna()]
                if run.empty and selection.selected_month is not None:
                    candidates = [(pd.Timestamp(selection.selected_month), float(selection.selected_extent_pct))]
                else:
                    candidates = [(pd.Timestamp(month), float(value)) for month, value in run["extent_pct"].items()]
            else:
                candidates = [(pd.Timestamp(month), float(value)) for month, value in run["extent_pct"].dropna().items()]
        else:
            candidates = []
        upper_bound = not_later_than.get(year)
        if upper_bound is not None:
            upper_bound = pd.Timestamp(upper_bound)
            candidates = [candidate for candidate in candidates if candidate[0] <= upper_bound]
            if not candidates:
                fallback = fallback_trough_months.get(year)
                if fallback is not None and pd.Timestamp(fallback) in frame.index:
                    value = frame.loc[pd.Timestamp(fallback), "extent_pct"]
                    if pd.notna(value):
                        candidates = [(pd.Timestamp(fallback), float(value))]
        # The adaptive pass must not let a newly widened target year pull a
        # neighbouring, already classified year onto another candidate.
        fixed = fixed_trough_months.get(year)
        if fixed is not None:
            fixed = pd.Timestamp(fixed)
            fixed_candidates = [candidate for candidate in candidates if candidate[0] == fixed]
            if fixed_candidates:
                candidates = fixed_candidates
        sequence_input.append({"year": year, "expected": expected, "candidates": candidates})

    selected_dates = select_boundary_sequence(
        sequence_input, raw_minimum_rel_tolerance=0.0
    )

    rows = []
    for year, expected, selection, selected in zip(years, expecteds, selections, selected_dates):
        selection_status = selection.selection_status
        if (
            selected is not None
            and selection.selected_month is not None
            and pd.Timestamp(selected) != pd.Timestamp(selection.selected_month)
            and selection_status not in ("low_quality", "quality_adjusted")
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
            "selection_quality": selection.support,
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
            and selection_status in ("raw", "quality_adjusted")
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
    "temporal_mid_dry_invalid_pct", "mid_dry_invalid_pct",
    "half_loss_month", "half_loss_extent_pct", "half_loss_target_pct",
    "trough_month", "trough_extent_pct", "trough_invalid_pct", "boundary_status",
    "drawdown_pct", "persistence_ratio", "recession_months", "half_loss_months",
    "n_rewetting_pulses", "n_usable_months", "confidence",
    "secondary_peak_month", "secondary_peak_extent_pct",
    "secondary_trough_month", "secondary_trough_extent_pct",
    "raw_trough_month", "raw_trough_extent_pct",
    "low_run_start_month", "low_run_end_month",
    "window_status", "selection_status", "selection_support", "selection_quality",
    "window_n_expected", "window_n_usable", "phase_shift_months",
    "raw_peak_month", "raw_peak_extent_pct",
    "peak_selection_status", "peak_selection_support",
]


def _nearest_month(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp:
    target = start + (end - start) / 2
    return pd.Timestamp(index[int(np.argmin(np.abs(index - target)))])


def _position_of(index: pd.DatetimeIndex, month: pd.Timestamp) -> int:
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
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=config.max_invalid_pct,
        allow_unknown_quality=config.allow_unknown_quality,
        quality_policy=config.quality_policy,
    )
    opportunities = _find_robust_trough_opportunities(frame, config)
    base_opportunities = opportunities.copy()
    result = _assemble_dynamic_years(frame, opportunities, config, pattern)

    # Iterate only over short, interior cycles.  A missing/poor boundary is
    # not enough evidence to invent one across a data gap; the base boundary
    # must already exist and have classified neighbours on both sides.
    relaxed_years: set[int] = set()
    base_boundaries = {
        int(row["hy_year"]): pd.Timestamp(row["trough_month"])
        for _, row in result.iterrows()
        if pd.notna(row["trough_month"])
    }
    max_passes = max(1, len(result))
    for _ in range(max_passes):
        candidates = _adaptive_retry_years(result) | _adaptive_edge_retry_years(
            frame, result, config
        )
        new_years = candidates - relaxed_years
        if not new_years:
            break
        relaxed_years.update(new_years)
        radius = min(
            5,
            max(config.trough_search_radius_months, _ADAPTIVE_TROUGH_SEARCH_RADIUS_MONTHS),
        )
        relaxed_radius = {year: radius for year in relaxed_years}
        fixed = {
            year: month for year, month in base_boundaries.items()
            if year not in relaxed_years
        }
        not_later_than = {
            year: base_boundaries[year] for year in relaxed_years
            if year in base_boundaries
        }
        opportunities = _find_robust_trough_opportunities(
            frame,
            config,
            radius_by_year=relaxed_radius,
            fixed_trough_months=fixed,
            not_later_than=not_later_than,
            fallback_trough_months=base_boundaries,
        )
        effective_relaxed_years = {
            int(row["hy_year"])
            for _, row in opportunities.iterrows()
            if int(row["hy_year"]) in relaxed_years
            and int(row["hy_year"]) in base_boundaries
            and pd.notna(row["trough_month"])
            and pd.Timestamp(row["trough_month"]) < base_boundaries[int(row["hy_year"])]
        }
        for year in relaxed_years - effective_relaxed_years:
            base_rows = base_opportunities.loc[base_opportunities["hy_year"] == year]
            if not base_rows.empty:
                row_index = opportunities.index[opportunities["hy_year"] == year]
                opportunities.loc[row_index, base_opportunities.columns] = base_rows.iloc[0].to_numpy()
        result = _assemble_dynamic_years(
            frame,
            opportunities,
            config,
            pattern,
            min_usable_months_by_year={
                year: min(config.min_usable_months_per_cycle, _ADAPTIVE_MIN_USABLE_MONTHS_PER_CYCLE)
                for year in effective_relaxed_years
            },
        )
        successful_relaxed_years = {
            int(row["hy_year"])
            for _, row in result.iterrows()
            if int(row["hy_year"]) in effective_relaxed_years
            and pd.notna(row["peak_month"])
            and row["status_reason"] != "insufficient_cycle_coverage"
        }
        failed_relaxed_years = effective_relaxed_years - successful_relaxed_years
        if failed_relaxed_years:
            for year in failed_relaxed_years:
                base_rows = base_opportunities.loc[base_opportunities["hy_year"] == year]
                if not base_rows.empty:
                    row_index = opportunities.index[opportunities["hy_year"] == year]
                    opportunities.loc[row_index, base_opportunities.columns] = base_rows.iloc[0].to_numpy()
            result = _assemble_dynamic_years(
                frame,
                opportunities,
                config,
                pattern,
                min_usable_months_by_year={
                    year: min(config.min_usable_months_per_cycle, _ADAPTIVE_MIN_USABLE_MONTHS_PER_CYCLE)
                    for year in successful_relaxed_years
                },
            )
    return result


def _adaptive_retry_years(result: pd.DataFrame) -> set[int]:
    """Return short-cycle years safe to retry between existing boundaries."""
    retryable: set[int] = set()
    for position, (_, row) in enumerate(result.iterrows()):
        if row["status"] == "complete" or pd.isna(row["trough_month"]):
            continue
        if row["status_reason"] != "insufficient_cycle_coverage":
            continue
        if position == 0 or position == len(result) - 1:
            continue
        previous = result.iloc[position - 1]["trough_month"]
        following = result.iloc[position + 1]["trough_month"]
        if pd.notna(previous) and pd.notna(following):
            retryable.add(int(row["hy_year"]))
    return retryable


def _adaptive_edge_retry_years(
    frame: pd.DataFrame, result: pd.DataFrame, config: DynamicHydroYearConfig
) -> set[int]:
    """Return interior years whose base window clipped a lower trough.

    The released radius remains the default.  This retry is deliberately
    evidence-gated: the base trough must be exactly at the left edge of its
    window, both neighbouring years must have boundaries, and every month in
    the extra look-back span must be observed.  The comparison uses the raw
    observed extent, preserving the existing rule that partially invalid
    observations can still identify a trough.
    """
    expanded_radius = min(
        5,
        max(config.trough_search_radius_months, _ADAPTIVE_TROUGH_SEARCH_RADIUS_MONTHS),
    )
    if expanded_radius <= config.trough_search_radius_months:
        return set()

    retryable: set[int] = set()
    for position, (_, row) in enumerate(result.iterrows()):
        if position == 0 or position == len(result) - 1:
            continue
        if pd.isna(row["trough_month"]):
            continue
        previous = result.iloc[position - 1]["trough_month"]
        following = result.iloc[position + 1]["trough_month"]
        if pd.isna(previous) or pd.isna(following):
            continue

        year = int(row["hy_year"])
        expected = pd.Timestamp(year, config.expected_trough_month, 1)
        base_start = expected - pd.DateOffset(months=config.trough_search_radius_months)
        if pd.Timestamp(row["trough_month"]) != base_start:
            continue

        expanded_start = expected - pd.DateOffset(months=expanded_radius)
        extra_index = pd.date_range(
            expanded_start,
            base_start - pd.DateOffset(months=1),
            freq="MS",
        )
        extra = frame.reindex(extra_index)
        observed = extra["extent_pct"].notna() & extra["invalid_pct"].lt(100.0)
        if not observed.all():
            continue
        selected_value = frame.loc[base_start, "extent_pct"]
        if pd.notna(selected_value) and (extra.loc[observed, "extent_pct"] < selected_value).any():
            retryable.add(year)
    return retryable


def _assemble_dynamic_years(
    frame: pd.DataFrame, opportunities: pd.DataFrame, config: DynamicHydroYearConfig,
    pattern: SeasonalPatternResult | None,
    *,
    min_usable_months_by_year: dict[int, int] | None = None,
) -> pd.DataFrame:
    amplitude_pp, noise_pp = robust_scale(frame)
    rows = []
    previous = None
    for position, (_, opportunity) in enumerate(opportunities.iterrows()):
        row = _blank_cycle(opportunity)
        min_usable_months = (min_usable_months_by_year or {}).get(
            int(opportunity["hy_year"]), config.min_usable_months_per_cycle
        )
        used_record_start = False
        if pd.isna(opportunity["trough_month"]):
            previous = None
            rows.append(row)
            continue
        if previous is None:
            if position == 0:
                synthetic_previous = opportunity.copy()
                synthetic_previous["trough_month"] = (
                    frame.index.min() - pd.DateOffset(months=1)
                )
                previous = synthetic_previous
                used_record_start = True
            else:
                row.update(status="partial", status_reason="no_previous_boundary")
                previous = opportunity
                rows.append(row)
                continue
        start = pd.Timestamp(previous["trough_month"]) + pd.DateOffset(months=1)
        end = pd.Timestamp(opportunity["trough_month"])
        cycle = frame.loc[start:end]
        usable = cycle.loc[cycle["candidate_usable"], "extent_pct"]
        if len(usable) < min_usable_months:
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
            temporal_mid_dry_invalid_pct=float(frame.loc[midpoint, "invalid_pct"]) if midpoint in frame.index and "invalid_pct" in frame.columns and pd.notna(frame.loc[midpoint, "invalid_pct"]) else np.nan,
            mid_dry_invalid_pct=float(frame.loc[midpoint, "invalid_pct"]) if midpoint in frame.index and "invalid_pct" in frame.columns and pd.notna(frame.loc[midpoint, "invalid_pct"]) else np.nan,
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
