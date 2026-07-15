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
