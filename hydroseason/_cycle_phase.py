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


@dataclass(frozen=True)
class NormalisedCycle:
    """One cycle expressed against its own low-water envelope."""

    z: pd.Series
    smoothed_z: pd.Series
    denominator_pp: float
    smoothed_peak_position: int | None
    observed_peak_position: int | None
    sufficient: bool


def normalise_cycle(
    cycle: pd.DataFrame,
    *,
    start_extent: float,
    end_extent: float,
    window: int,
    resolution_floor_pp: float,
) -> NormalisedCycle:
    """Express a cycle as z in [0, 1] between its low envelope and its peak.

    The denominator uses the SMOOTHED peak. A raw peak is a single observation
    setting the scale for every month in the cycle: one anomalously high month
    deflates all of z, the upper band is never reached, and the cycle loses its
    wet phase to ``unspecified``. The trough side is already protected by the
    equivalent-low run, so this makes both ends of the normalisation symmetric.
    """
    if not np.isfinite(resolution_floor_pp) or resolution_floor_pp <= 0.0:
        raise ValueError("resolution_floor_pp must be a positive finite number.")

    extent = pd.to_numeric(cycle["extent_pct"], errors="coerce").astype(float)
    n = len(extent)
    if n == 0:
        empty = pd.Series(dtype=float)
        return NormalisedCycle(empty, empty, 0.0, None, None, False)

    positions = np.arange(n, dtype=float)
    span = max(float(n - 1), 1.0)
    envelope = pd.Series(
        float(start_extent) + (float(end_extent) - float(start_extent)) * positions / span,
        index=extent.index,
        dtype=float,
    )

    effective = effective_window(int(window), n)
    smoothed_extent = smooth_for_geometry(extent, effective)
    above = smoothed_extent - envelope
    if not above.notna().any():
        empty = pd.Series(np.nan, index=extent.index, dtype=float)
        return NormalisedCycle(empty, empty, 0.0, None, None, False)

    smoothed_peak_position = int(np.nanargmax(above.to_numpy(dtype=float)))
    observed_above = extent - envelope
    observed_peak_position = int(np.nanargmax(observed_above.to_numpy(dtype=float)))
    denominator = float(above.iloc[smoothed_peak_position])

    if not np.isfinite(denominator) or denominator <= float(resolution_floor_pp):
        unspecified = pd.Series(np.nan, index=extent.index, dtype=float)
        return NormalisedCycle(
            unspecified,
            unspecified,
            max(denominator, 0.0) if np.isfinite(denominator) else 0.0,
            smoothed_peak_position,
            observed_peak_position,
            False,
        )

    z = ((extent - envelope) / denominator).clip(lower=0.0, upper=1.0)
    smoothed_z = ((smoothed_extent - envelope) / denominator).clip(lower=0.0, upper=1.0)
    return NormalisedCycle(
        z.astype(float),
        smoothed_z.astype(float),
        denominator,
        smoothed_peak_position,
        observed_peak_position,
        True,
    )

