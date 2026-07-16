from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
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


def robust_scale(frame: pd.DataFrame) -> tuple[float, float]:
    """Estimate amplitude and noise scale (percentage points) from usable candidates.

    Amplitude is the 10th-90th percentile spread of extent_pct among usable rows.
    Noise is a robust (MAD-based) estimate of month-to-month variability after
    removing each observation's month-of-year median (a crude seasonal baseline).
    """
    usable = frame.loc[frame["candidate_usable"], "extent_pct"].astype(float)
    if not len(usable):
        return 0.0, 0.0
    amplitude = float(usable.quantile(0.90) - usable.quantile(0.10))
    month_median = usable.groupby(usable.index.month).transform("median")
    delta = (usable - month_median).diff().dropna().to_numpy(float)
    if not len(delta):
        return amplitude, 0.0
    centre = float(np.median(delta))
    noise = 1.4826 * float(np.median(np.abs(delta - centre))) / np.sqrt(2.0)
    return amplitude, noise


def _epsilon_pp(row: pd.Series, *, noise_pp: float, amplitude_pp: float) -> float:
    """Tolerance band (percentage points) for treating nearby values as equivalent minima.

    Bounded above by 10% of the amplitude so the tolerance never swallows the
    whole seasonal range; bounded below by measurement resolution (100 / n_valid)
    when available, otherwise by the noise estimate.
    """
    resolution = 100.0 / float(row["n_valid"]) if "n_valid" in row and row["n_valid"] > 0 else 0.0
    return min(0.10 * amplitude_pp, max(resolution, noise_pp)) if amplitude_pp > 0 else 0.0


def select_window_minimum(
    window: pd.DataFrame,
    *,
    expected: pd.Timestamp,
    expected_count: int,
    noise_pp: float,
    amplitude_pp: float,
    config: RobustBoundaryConfig = RobustBoundaryConfig(),
) -> BoundarySelection:
    """Select the boundary month within a window around an expected date.

    Always reports the true observed minimum (``raw_month``/``raw_extent_pct``)
    even when the selection is flagged ambiguous or the window is truncated —
    the raw extremum is never silently replaced or dropped.
    """
    usable = window.loc[window["candidate_usable"]].copy()
    n_usable = len(usable)
    if n_usable < config.min_usable_candidates:
        return BoundarySelection(None, np.nan, None, np.nan, None, None,
                                 "internal_gap", "unresolved", 0.0,
                                 expected_count, n_usable, None)
    raw_month = pd.Timestamp(usable["extent_pct"].idxmin())
    raw_extent = float(usable.loc[raw_month, "extent_pct"])
    epsilon = _epsilon_pp(usable.loc[raw_month], noise_pp=noise_pp, amplitude_pp=amplitude_pp)
    equivalent = (
        window["candidate_usable"]
        & window["extent_pct"].le(raw_extent + epsilon)
    )
    groups = equivalent.ne(equivalent.shift(fill_value=False)).cumsum()
    raw_group = groups.loc[raw_month]
    run = window.loc[equivalent & groups.eq(raw_group)]
    local = usable["extent_pct"].rolling(3, center=True, min_periods=2).median()
    residual = float(local.loc[raw_month] - raw_extent)
    ambiguous = noise_pp > 0 and residual > config.anomaly_noise_scales * noise_pp
    full_start = expected - pd.DateOffset(months=(expected_count - 1) // 2)
    full_end = expected + pd.DateOffset(months=(expected_count - 1) // 2)
    if window.index.min() > full_start:
        window_status = "left_truncated"
    elif window.index.max() < full_end:
        window_status = "right_truncated"
    elif n_usable / expected_count < config.min_window_coverage:
        window_status = "internal_gap"
    else:
        window_status = "full"
    support = min(1.0, n_usable / expected_count)
    if ambiguous:
        support *= 0.60
    if window_status != "full":
        support *= 0.75
    return BoundarySelection(
        raw_month, raw_extent, raw_month, raw_extent,
        pd.Timestamp(run.index[0]), pd.Timestamp(run.index[-1]),
        window_status, "ambiguous" if ambiguous else "raw", support,
        expected_count, n_usable,
        (raw_month.year - expected.year) * 12 + raw_month.month - expected.month,
    )
