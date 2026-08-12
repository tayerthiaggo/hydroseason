"""Deterministic circular statistics for calendar-month timing."""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class CircularTimingSummary:
    concentration: float | None
    ci_low: float | None
    ci_high: float | None
    iqr_months: float | None
    uniformity_p: float | None
    n: int


def _validate_months(months: Iterable[object]) -> np.ndarray:
    try:
        values = list(months)
    except TypeError as exc:
        raise TypeError("months must be an iterable of integers") from exc
    if not values:
        raise ValueError("months must not be empty")
    if any(isinstance(value, bool) or not isinstance(value, Integral) for value in values):
        raise ValueError("months must contain integral values")
    result = np.asarray(values, dtype=np.int64)
    if np.any((result < 1) | (result > 12)):
        raise ValueError("months must be integers from 1 to 12")
    return result


def _month_angles(months: np.ndarray) -> np.ndarray:
    return 2.0 * np.pi * (months - 1) / 12.0


def _circular_iqr_months(months: Iterable[int]) -> float | None:
    values = np.asarray(list(months), dtype=np.int64)
    if len(values) < 4:
        return None
    radians = _month_angles(values)
    centre = np.angle(np.mean(np.exp(1j * radians)))
    offsets = np.angle(np.exp(1j * (radians - centre))) * 12.0 / (2.0 * np.pi)
    return float(np.percentile(offsets, 75) - np.percentile(offsets, 25))


def _resultant_length(angles: np.ndarray) -> float:
    return float(abs(np.mean(np.exp(1j * angles))))


def _kuiper_statistic(phases: np.ndarray) -> float:
    ordered = np.sort(np.mod(phases, 1.0))
    n = len(ordered)
    ranks = np.arange(1, n + 1, dtype=float) / n
    lower_ranks = np.arange(n, dtype=float) / n
    return float(np.max(ranks - ordered) + np.max(ordered - lower_ranks))


def summarise_circular_months(
    months,
    *,
    n_resamples: int = 200,
    random_state: int = 0,
    confidence: float = 0.95,
) -> CircularTimingSummary:
    """Summarise month observations as points on a twelve-month circle."""
    values = _validate_months(months)
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, Integral):
        raise TypeError("n_resamples must be an integer")
    if n_resamples < 20:
        raise ValueError("n_resamples must be at least 20")
    if isinstance(random_state, bool) or not isinstance(random_state, Integral):
        raise TypeError("random_state must be an integer")
    if isinstance(confidence, bool) or not isinstance(confidence, Real):
        raise ValueError("confidence must be a number between 0 and 1")
    confidence_value = float(confidence)
    if not 0.0 < confidence_value < 1.0:
        raise ValueError("confidence must be between 0 and 1")

    angles = _month_angles(values)
    concentration = _resultant_length(angles)
    seed_sequence = np.random.SeedSequence(int(random_state))
    bootstrap_seed, null_seed = seed_sequence.spawn(2)
    bootstrap_rng = np.random.default_rng(bootstrap_seed)
    null_rng = np.random.default_rng(null_seed)

    bootstrap_indices = bootstrap_rng.integers(0, len(values), size=(n_resamples, len(values)))
    bootstrap_angles = angles[bootstrap_indices]
    bootstrap_lengths = np.abs(np.mean(np.exp(1j * bootstrap_angles), axis=1))
    alpha = (1.0 - confidence_value) / 2.0
    ci_low, ci_high = np.percentile(bootstrap_lengths, [100.0 * alpha, 100.0 * (1.0 - alpha)])

    observed_stat = _kuiper_statistic(angles / (2.0 * np.pi))
    n_null = max(int(n_resamples), 999)
    # The observed statistic is computed from month angles, which only take
    # 12 discrete values ((m - 1) / 12 for month m in 1..12). The null must be
    # drawn from that same discrete 12-point support -- not continuous U(0,1)
    # -- otherwise the discrete-support observed statistic looks artificially
    # extreme against a continuous null, biasing p-values toward false
    # rejection of uniformity.
    null_phases = null_rng.integers(0, 12, size=(n_null, len(values))) / 12.0
    null_stats = np.array([_kuiper_statistic(sample) for sample in null_phases])
    uniformity_p = (1.0 + np.count_nonzero(null_stats >= observed_stat)) / (n_null + 1.0)

    return CircularTimingSummary(
        concentration=concentration,
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        iqr_months=_circular_iqr_months(values),
        uniformity_p=float(uniformity_p),
        n=len(values),
    )


__all__ = ["CircularTimingSummary", "summarise_circular_months"]
