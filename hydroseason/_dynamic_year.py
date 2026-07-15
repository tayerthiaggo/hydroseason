from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._seasonality import SeasonalPatternResult, classify_seasonal_pattern
from ._state_input import prepare_monthly_extent


@dataclass(frozen=True)
class DynamicHydroYearConfig:
    expected_trough_month: int
    expected_peak_month: int | None = None
    trough_search_radius_months: int = 3
    dry_plateau_rule: Literal["last_before_confirmed_recovery", "middle", "first"] = "last_before_confirmed_recovery"
    sustained_rise_months: int = 2
    pulse_rejection_window_months: int = 4
    max_invalid_pct: float = 20.0
    allow_unknown_quality: bool = False
    min_usable_months_per_cycle: int = 8
    min_usable_trough_candidates: int = 2
    min_baseline_cycles: int = 10
    low_percentile: float = 20.0
    high_percentile: float = 80.0
    measurement_tolerance_pct: float = 1.0

    def __post_init__(self) -> None:
        if self.expected_trough_month not in range(1, 13):
            raise ValueError("expected_trough_month must be in 1..12.")
        if self.expected_peak_month is not None and self.expected_peak_month not in range(1, 13):
            raise ValueError("expected_peak_month must be in 1..12.")
        if not 0 <= self.trough_search_radius_months <= 5:
            raise ValueError("trough_search_radius_months must be in 0..5.")
        if self.sustained_rise_months < 1 or self.pulse_rejection_window_months < 1:
            raise ValueError("recovery windows must be positive.")
        if not 0 <= self.max_invalid_pct <= 100:
            raise ValueError("max_invalid_pct must be between 0 and 100.")
        if not 0 <= self.low_percentile < self.high_percentile <= 100:
            raise ValueError("condition percentiles must satisfy 0 <= low < high <= 100.")
        if self.measurement_tolerance_pct < 0:
            raise ValueError("measurement_tolerance_pct must be non-negative.")


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


def _recovery_status(frame: pd.DataFrame, low_date: pd.Timestamp, plateau_ceiling: float, config: DynamicHydroYearConfig) -> str:
    threshold = plateau_ceiling
    tail = frame.loc[frame.index > low_date]
    consecutive = 0
    for position, (_, row) in enumerate(tail.iterrows()):
        if not bool(row["candidate_usable"]):
            consecutive = 0
            continue
        consecutive = consecutive + 1 if float(row["extent_pct"]) > threshold else 0
        if consecutive < config.sustained_rise_months:
            continue
        end_position = position + config.pulse_rejection_window_months
        if end_position >= len(tail):
            return "provisional"
        rejection = tail.iloc[position + 1 : end_position + 1]
        if (~rejection["candidate_usable"]).any():
            return "partial"
        if (rejection["extent_pct"] <= plateau_ceiling).any():
            consecutive = 0
            continue
        return "confirmed"
    return "provisional" if len(tail) < config.sustained_rise_months + config.pulse_rejection_window_months else "unconfirmed"


def _select_low_candidate(window: pd.DataFrame, full: pd.DataFrame, config: DynamicHydroYearConfig) -> tuple[pd.Timestamp | None, str]:
    minimum = float(window["extent_pct"].min())
    plateau = window.loc[window["extent_pct"] <= minimum + config.measurement_tolerance_pct]
    if config.dry_plateau_rule == "first":
        return pd.Timestamp(plateau.index[0]), "confirmed"
    if config.dry_plateau_rule == "middle":
        return pd.Timestamp(plateau.index[len(plateau) // 2]), "confirmed"
    provisional = None
    for candidate in reversed(plateau.index.tolist()):
        status = _recovery_status(full, pd.Timestamp(candidate), minimum + config.measurement_tolerance_pct, config)
        if status == "confirmed":
            return pd.Timestamp(candidate), status
        if status in {"provisional", "partial"} and provisional is None:
            provisional = (pd.Timestamp(candidate), status)
    return provisional if provisional is not None else (None, "unconfirmed")


def _find_trough_opportunities(frame: pd.DataFrame, config: DynamicHydroYearConfig) -> pd.DataFrame:
    rows = []
    for year in range(int(frame.index.min().year), int(frame.index.max().year) + 1):
        expected = pd.Timestamp(year, config.expected_trough_month, 1)
        start = expected - pd.DateOffset(months=config.trough_search_radius_months)
        end = expected + pd.DateOffset(months=config.trough_search_radius_months)
        usable = frame.loc[(frame.index >= start) & (frame.index <= end) & frame["candidate_usable"]]
        base = {
            "hy_year": year,
            "status": "unresolved",
            "status_reason": "insufficient_trough_candidates",
            "trough_month": pd.NaT,
            "trough_extent_pct": np.nan,
            "trough_invalid_pct": np.nan,
            "boundary_status": "provisional",
            "phase_shift_months": np.nan,
        }
        if len(usable) < config.min_usable_trough_candidates:
            rows.append(base)
            continue
        candidate, recovery = _select_low_candidate(usable, frame, config)
        if candidate is None:
            base["status_reason"] = "recovery_not_confirmed"
            rows.append(base)
            continue
        row = frame.loc[candidate]
        base.update(
            status="complete" if recovery == "confirmed" else "partial",
            status_reason="ok" if recovery == "confirmed" else f"boundary_{recovery}",
            trough_month=candidate,
            trough_extent_pct=float(row["extent_pct"]),
            trough_invalid_pct=float(row["invalid_pct"]) if pd.notna(row["invalid_pct"]) else np.nan,
            boundary_status="confirmed" if recovery == "confirmed" else "provisional",
            phase_shift_months=_month_delta(candidate, expected),
        )
        rows.append(base)
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
]


def _middle_tie(series: pd.Series, kind: str) -> pd.Timestamp:
    target = series.max() if kind == "max" else series.min()
    candidates = series.loc[series == target]
    return pd.Timestamp(candidates.index[len(candidates) // 2])


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
    return row


def detect_dynamic_hydrological_years(extent, *, config: DynamicHydroYearConfig, value_col: str = "extent_pct", date_col: str | None = None, pattern: SeasonalPatternResult | None = None) -> pd.DataFrame:
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=config.max_invalid_pct,
        allow_unknown_quality=config.allow_unknown_quality,
    )
    opportunities = _find_trough_opportunities(frame, config)
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
        peak = _middle_tie(usable, "max")
        post_peak = usable.loc[peak:end]
        trough = end
        peak_value, trough_value = float(usable.loc[peak]), float(frame.loc[trough, "extent_pct"])
        target = (peak_value + trough_value) / 2.0
        half_candidates = post_peak.loc[post_peak <= target]
        half = pd.Timestamp(half_candidates.index[0]) if len(half_candidates) else pd.NaT
        midpoint = _nearest_month(post_peak.index, peak, trough)
        after_half = post_peak.loc[half:] if pd.notna(half) else post_peak.iloc[0:0]
        pulses = int((after_half.diff() > config.measurement_tolerance_pct).sum())
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
        )
        previous = opportunity
        rows.append(row)
    return pd.DataFrame(rows, columns=ANNUAL_COLUMNS)
