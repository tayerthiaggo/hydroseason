from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Iterable, Literal

import numpy as np
import pandas as pd

_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class AnnualTimingSummary:
    """Circular summary of annual extremum timing, resampled by year."""

    concentration: float | None
    ci_low: float | None
    ci_high: float | None
    iqr_months: float | None
    uniformity_p: float | None
    n_years: int
    dominant_month: int | None


@dataclass(frozen=True)
class CircularTimingSummary:
    concentration: float | None
    ci_low: float | None
    ci_high: float | None
    iqr_months: float | None
    uniformity_p: float | None
    n: int


def _expand_year_weights(
    month_sets: Sequence[tuple[int, ...]],
) -> tuple[np.ndarray, np.ndarray]:
    """Flatten per-year month sets to angles and weights totalling 1 per year."""
    angles: list[float] = []
    weights: list[float] = []
    for months in month_sets:
        if not months:
            continue
        share = 1.0 / len(months)
        for month in months:
            angles.append(2.0 * np.pi * (month - 1) / _MONTHS_PER_YEAR)
            weights.append(share)
    return np.asarray(angles, dtype=float), np.asarray(weights, dtype=float)


def _weighted_resultant(angles: np.ndarray, weights: np.ndarray) -> complex:
    total = float(weights.sum())
    if total <= 0.0:
        return 0j
    return complex(np.sum(weights * np.exp(1j * angles)) / total)


def _weighted_kuiper(angles: np.ndarray, weights: np.ndarray) -> float:
    """Kuiper statistic on a weighted sample of circular phases."""
    if len(angles) == 0:
        return 0.0
    phases = np.mod(angles / (2.0 * np.pi), 1.0)
    order = np.argsort(phases)
    ordered_phases = phases[order]
    ordered_weights = weights[order]
    total = float(ordered_weights.sum())
    if total <= 0.0:
        return 0.0
    upper = np.cumsum(ordered_weights) / total
    lower = upper - ordered_weights / total
    return float(np.max(upper - ordered_phases) + np.max(ordered_phases - lower))


def _rotate_month_set(months: tuple[int, ...], offset: int) -> tuple[int, ...]:
    """Shift a month set around the calendar circle, preserving its spacing."""
    return tuple(((month - 1 + offset) % _MONTHS_PER_YEAR) + 1 for month in months)


def _circular_offsets(angles: np.ndarray, centre: float) -> np.ndarray:
    return np.angle(np.exp(1j * (angles - centre))) * _MONTHS_PER_YEAR / (2.0 * np.pi)


def summarise_annual_timing(
    month_sets: Mapping[int, Sequence[int]],
    *,
    n_resamples: int = 200,
    random_state: int = 0,
    confidence: float = 0.95,
) -> AnnualTimingSummary:
    """Summarise annual extremum timing, resampling years rather than entries.

    Each year carries total weight 1 spread equally over its equivalent months,
    so an ambiguous year contributes a diffuse vote of the same total size as a
    sharp year's single vote. The bootstrap draws years with replacement and the
    uniformity null rotates each year's month set by a uniform offset, which
    preserves tie structure while destroying calendar alignment.
    """
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, Integral):
        raise TypeError("n_resamples must be an integer")
    if n_resamples < 20:
        raise ValueError("n_resamples must be at least 20")
    if isinstance(random_state, bool) or not isinstance(random_state, Integral):
        raise TypeError("random_state must be an integer")
    if not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be between 0 and 1")

    cleaned: list[tuple[int, ...]] = []
    for year in sorted(month_sets):
        months = tuple(int(month) for month in month_sets[year])
        if any(month < 1 or month > _MONTHS_PER_YEAR for month in months):
            raise ValueError("months must be integers from 1 to 12")
        if months:
            cleaned.append(months)

    n_years = len(cleaned)
    if n_years == 0:
        return AnnualTimingSummary(None, None, None, None, None, 0, None)

    angles, weights = _expand_year_weights(cleaned)
    resultant = _weighted_resultant(angles, weights)
    concentration = float(abs(resultant))

    seed_sequence = np.random.SeedSequence(int(random_state))
    bootstrap_seed, null_seed = seed_sequence.spawn(2)
    bootstrap_rng = np.random.default_rng(bootstrap_seed)
    null_rng = np.random.default_rng(null_seed)

    # Resample YEARS, not expanded entries.
    draws = bootstrap_rng.integers(0, n_years, size=(int(n_resamples), n_years))
    bootstrap_lengths = np.empty(int(n_resamples), dtype=float)
    for position, row in enumerate(draws):
        drawn_angles, drawn_weights = _expand_year_weights([cleaned[index] for index in row])
        bootstrap_lengths[position] = abs(_weighted_resultant(drawn_angles, drawn_weights))
    alpha = (1.0 - float(confidence)) / 2.0
    ci_low, ci_high = np.percentile(bootstrap_lengths, [100.0 * alpha, 100.0 * (1.0 - alpha)])

    observed_stat = _weighted_kuiper(angles, weights)
    n_null = max(int(n_resamples), 999)
    offsets = null_rng.integers(0, _MONTHS_PER_YEAR, size=(n_null, n_years))
    null_stats = np.empty(n_null, dtype=float)
    for position, row in enumerate(offsets):
        rotated = [_rotate_month_set(months, int(offset)) for months, offset in zip(cleaned, row)]
        null_angles, null_weights = _expand_year_weights(rotated)
        null_stats[position] = _weighted_kuiper(null_angles, null_weights)
    uniformity_p = (1.0 + np.count_nonzero(null_stats >= observed_stat)) / (n_null + 1.0)

    if concentration <= np.finfo(float).eps:
        dominant_month: int | None = None
        iqr_months: float | None = None
    else:
        centre = float(np.angle(resultant))
        dominant_month = int(round(centre * _MONTHS_PER_YEAR / (2.0 * np.pi))) % _MONTHS_PER_YEAR + 1
        offsets_months = _circular_offsets(angles, centre)
        iqr_months = float(np.percentile(offsets_months, 75) - np.percentile(offsets_months, 25))

    return AnnualTimingSummary(
        concentration=concentration,
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        iqr_months=iqr_months,
        uniformity_p=float(uniformity_p),
        n_years=n_years,
        dominant_month=dominant_month,
    )



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


def equivalent_extremum_months(
    values: pd.Series,
    *,
    kind: Literal["min", "max"],
    tolerance: float,
) -> tuple[int, ...]:
    """Calendar months tied with a year's extremum, within measurement tolerance.

    A flat or near-flat year has no single argmin. ``idxmin``/``idxmax`` answer
    anyway by returning the first row, which silently reports January. This
    returns the full equivalent set so a tied year contributes a diffuse timing
    distribution instead of a fabricated one.
    """
    if kind not in {"min", "max"}:
        raise ValueError("kind must be 'min' or 'max'.")
    if not np.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("tolerance must be a non-negative finite number.")
    finite = values.dropna()
    if finite.empty:
        return ()
    extremum = float(finite.min() if kind == "min" else finite.max())
    if kind == "min":
        selected = finite.loc[finite <= extremum + tolerance]
    else:
        selected = finite.loc[finite >= extremum - tolerance]
    return tuple(sorted({int(stamp.month) for stamp in selected.index}))


__all__ = [
    "AnnualTimingSummary",
    "CircularTimingSummary",
    "equivalent_extremum_months",
    "summarise_annual_timing",
    "summarise_circular_months",
]

