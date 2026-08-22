"""Cycle-relative phase labelling for one accepted trough-to-trough cycle.

Phases are defined against the cycle's own low-water envelope rather than
against month-specific climatological baselines. That is what lets an ideal
sinusoid produce recovery, wet, recession and dry in order: the question asked
of each month is "where is this cycle now", not "is this month unusual for a
March".
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral

import numpy as np
import pandas as pd

PHASES = ("dry", "recovery", "wet", "recession")
UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class PhaseThresholds:
    """Calibrated phase tuple. Required fields; generated defaults live elsewhere."""

    phase_low_fraction: float
    phase_high_fraction: float
    phase_min_duration_months: int
    phase_smoothing_window: int

    def __post_init__(self) -> None:
        if not (
            np.isfinite(self.phase_low_fraction)
            and np.isfinite(self.phase_high_fraction)
            and 0.0 <= self.phase_low_fraction < self.phase_high_fraction <= 1.0
        ):
            raise ValueError("phase fractions must satisfy 0 <= low < high <= 1")
        for name in ("phase_min_duration_months", "phase_smoothing_window"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.phase_smoothing_window % 2 == 0:
            raise ValueError("phase_smoothing_window must be odd")


def effective_window(requested: int, cycle_length: int) -> int:
    """Largest valid odd smoothing window that fits the cycle.

    A short cycle cannot support a wide window, and refusing to label it would
    be a worse answer than labelling it with less smoothing.
    """
    if requested < 1 or requested % 2 == 0:
        raise ValueError("requested window must be an odd positive integer")
    if cycle_length < 1:
        raise ValueError("cycle_length must be positive")
    window = min(int(requested), int(cycle_length))
    if window % 2 == 0:
        window -= 1
    return max(1, window)


def smooth_for_geometry(values: pd.Series, window: int) -> pd.Series:
    """Centred rolling median, for slopes and crossings only.

    Median, not mean: one spike must not drag a band-crossing month. Published
    peaks, troughs and extent metrics continue to come from raw observations.
    """
    if window == 1:
        return values.astype(float).copy()
    smoothed = values.astype(float).rolling(window=window, center=True, min_periods=1).median()
    return smoothed.astype(float)
