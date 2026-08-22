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


def _sustained(mask: np.ndarray, start: int, months: int) -> bool:
    """Whether ``mask`` holds for ``months`` consecutive positions from ``start``."""
    end = start + months
    if end > len(mask):
        return False
    return bool(mask[start:end].all())


def label_cycle(
    normalised: NormalisedCycle,
    *,
    low_fraction: float,
    high_fraction: float,
    min_duration_months: int,
) -> pd.Series:
    """Walk dry -> recovery -> wet -> recession -> dry over band crossings.

    Every transition must be evidenced. Where one cannot be established the
    interval stays ``unspecified``: a forced label is worse than an absent one,
    because a downstream duration metric cannot distinguish an invented phase
    from an observed one.
    """
    if not 0.0 <= low_fraction < high_fraction <= 1.0:
        raise ValueError("require 0 <= low_fraction < high_fraction <= 1")
    if min_duration_months < 1:
        raise ValueError("min_duration_months must be at least 1")

    index = normalised.z.index
    labels = pd.Series(UNSPECIFIED, index=index, dtype=object)
    if not normalised.sufficient or len(index) == 0:
        return labels

    signal = normalised.smoothed_z.to_numpy(dtype=float)
    n = len(signal)
    finite = np.isfinite(signal)
    if not finite.any():
        return labels

    rising = np.zeros(n, dtype=bool)
    rising[1:] = np.diff(np.where(finite, signal, np.nan)) > 0.0
    above_high = finite & (signal >= high_fraction)
    below_low = finite & (signal <= low_fraction)

    peak_position = normalised.observed_peak_position
    if peak_position is None or not finite[peak_position]:
        return labels

    # Recovery: first sustained rise out of the lower band, before the peak.
    recovery_start: int | None = None
    for position in range(1, peak_position + 1):
        if not below_low[position] and _sustained(rising, position, int(min_duration_months)):
            recovery_start = position
            break

    # Wet: first upper-band upcrossing at or before the peak.
    wet_start: int | None = None
    for position in range(0, peak_position + 1):
        if above_high[position] and _sustained(above_high, position, int(min_duration_months)):
            wet_start = position
            break

    # Recession: first sustained upper-band downcrossing after the peak.
    recession_start: int | None = None
    if wet_start is not None:
        for position in range(peak_position + 1, n):
            if not above_high[position] and _sustained(~above_high, position, int(min_duration_months)):
                recession_start = position
                break

    # Closing dry: first sustained lower-band entry after recession begins.
    closing_dry_start: int | None = None
    if recession_start is not None:
        for position in range(recession_start, n):
            if below_low[position] and _sustained(below_low, position, int(min_duration_months)):
                closing_dry_start = position
                break

    if recovery_start is not None:
        opening = np.arange(n) < recovery_start
        labels.iloc[np.flatnonzero(opening & below_low)] = "dry"
        end = wet_start if wet_start is not None else (peak_position + 1)
        labels.iloc[recovery_start:end] = "recovery"
    elif wet_start is not None:
        opening = np.arange(n) < wet_start
        labels.iloc[np.flatnonzero(opening & below_low)] = "dry"

    if wet_start is not None:
        end = recession_start if recession_start is not None else n
        labels.iloc[wet_start:end] = "wet"

    if recession_start is not None:
        below_low_indices = np.flatnonzero((np.arange(n) >= recession_start) & below_low)
        first_below = int(below_low_indices[0]) if len(below_low_indices) > 0 else n
        end = closing_dry_start if closing_dry_start is not None else first_below
        labels.iloc[recession_start:end] = "recession"

    if closing_dry_start is not None:
        closing = np.arange(n) >= closing_dry_start
        labels.iloc[np.flatnonzero(closing & below_low)] = "dry"

    labels.loc[~finite] = UNSPECIFIED
    return labels


# Matches the periodicity null. Structural, not tuned; not in the grid.
_DEFAULT_REPLICATES = 999
_THRESHOLD_JITTER = 0.05


def phase_stability(
    cycle: pd.DataFrame,
    *,
    start_extent_candidates: tuple[float, ...],
    end_extent_candidates: tuple[float, ...],
    low_fraction: float,
    high_fraction: float,
    min_duration_months: int,
    window: int,
    resolution_floor_pp: float,
    noise_pp: float,
    noise_residuals: np.ndarray,
    n_replicates: int = _DEFAULT_REPLICATES,
    random_state: int = 0,
) -> pd.DataFrame:
    """Empirical label stability under threshold and observation perturbation.

    Observations are perturbed inside the bootstrap rather than conditioned
    out. Holding them fixed would measure only threshold sensitivity, which is
    not the dominant error source: satellite extent error is largest and most
    one-sided at the low-water end of the cycle. Naming the smaller uncertainty
    and omitting the larger would make this number read as more reassuring than
    the evidence supports.
    """
    index = cycle.index
    counts = pd.DataFrame(0.0, index=index, columns=[f"p_{name}" for name in PHASES])
    if len(index) == 0:
        counts["phase_stability"] = []
        return counts

    extent = pd.to_numeric(cycle["extent_pct"], errors="coerce").astype(float)
    if "observed_fraction" in cycle.columns:
        observed = pd.to_numeric(cycle["observed_fraction"], errors="coerce").fillna(1.0).clip(0.05, 1.0)
    else:
        observed = pd.Series(1.0, index=index, dtype=float)
    residuals = np.asarray(noise_residuals, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    starts = np.asarray(start_extent_candidates, dtype=float)
    ends = np.asarray(end_extent_candidates, dtype=float)
    if not len(residuals) or not np.isfinite(starts).all() or not np.isfinite(ends).all():
        raise ValueError("noise residuals and boundary candidates must be finite and non-empty")

    rng = np.random.default_rng(np.random.SeedSequence(int(random_state)))
    valid = 0
    for _ in range(int(n_replicates)):
        residual_draw = rng.choice(residuals, size=len(residuals), replace=True)
        residual_centre = float(np.median(residual_draw))
        replicate_noise_pp = 1.4826 * float(
            np.median(np.abs(residual_draw - residual_centre))
        )
        if replicate_noise_pp <= np.finfo(float).eps:
            replicate_noise_pp = float(max(noise_pp, np.finfo(float).eps))
        # A poorly observed month carries more uncertainty, so it moves more.
        scale = replicate_noise_pp / np.sqrt(observed.to_numpy(dtype=float))
        jitter = rng.normal(0.0, 1.0, size=len(index)) * scale
        perturbed = cycle.copy()
        perturbed["extent_pct"] = (extent.to_numpy(dtype=float) + jitter).clip(0.0, 100.0)

        low = float(np.clip(low_fraction + rng.normal(0.0, _THRESHOLD_JITTER), 0.0, 0.98))
        high = float(np.clip(high_fraction + rng.normal(0.0, _THRESHOLD_JITTER), low + 0.01, 1.0))

        normalised = normalise_cycle(
            perturbed,
            start_extent=float(rng.choice(starts)) + float(jitter[0]),
            end_extent=float(rng.choice(ends)) + float(jitter[-1]),
            window=window,
            resolution_floor_pp=resolution_floor_pp,
        )
        if not normalised.sufficient:
            continue
        labels = label_cycle(
            normalised, low_fraction=low, high_fraction=high, min_duration_months=min_duration_months
        )
        valid += 1
        for name in PHASES:
            counts[f"p_{name}"] += (labels == name).to_numpy(dtype=float)

    if valid:
        counts = counts / valid
    counts["phase_stability"] = counts[[f"p_{name}" for name in PHASES]].max(axis=1)
    return counts




