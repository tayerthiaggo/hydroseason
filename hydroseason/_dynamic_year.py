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
