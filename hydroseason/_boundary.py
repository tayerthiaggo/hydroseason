from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

WindowStatus = Literal["full", "left_truncated", "right_truncated", "internal_gap"]
SelectionStatus = Literal["raw", "ambiguous", "quality_adjusted", "unresolved"]


@dataclass(frozen=True)
class RobustBoundaryConfig:
    min_usable_candidates: int = 2
    min_window_coverage: float = 0.70
    support_threshold: float = 0.80
    anomaly_noise_scales: float = 3.0

    def __post_init__(self) -> None:
        if self.min_usable_candidates < 1:
            raise ValueError("min_usable_candidates must be positive")
        if not 0 < self.min_window_coverage <= 1:
            raise ValueError("min_window_coverage must be in (0, 1]")
        if not 0 <= self.support_threshold <= 1:
            raise ValueError("support_threshold must be in [0, 1]")
        if self.anomaly_noise_scales <= 0:
            raise ValueError("anomaly_noise_scales must be positive")


@dataclass(frozen=True)
class BoundarySelection:
    raw_month: pd.Timestamp | None
    raw_extent_pct: float
    selected_month: pd.Timestamp | None
    selected_extent_pct: float
    run_start: pd.Timestamp | None
    run_end: pd.Timestamp | None
    window_status: WindowStatus
    selection_status: SelectionStatus
    support: float
    n_expected: int
    n_usable: int
    phase_shift_months: int | None
