from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral
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
    offsets = np.angle(np.exp(1j * (angles - centre))) * _MONTHS_PER_YEAR / (
        2.0 * np.pi
    )
    return (offsets + _MONTHS_PER_YEAR / 2.0) % _MONTHS_PER_YEAR - (
        _MONTHS_PER_YEAR / 2.0
    )


def _weighted_percentile(
    values: np.ndarray,
    weights: np.ndarray,
    quantiles: Sequence[float],
) -> np.ndarray:
    """Inverted-CDF percentiles for non-negative weighted observations."""
    order = np.argsort(values)
    ordered_values = values[order]
    ordered_weights = weights[order]
    total = float(ordered_weights.sum())
    if total <= 0.0:
        return np.full(len(quantiles), np.nan)
    cumulative = np.cumsum(ordered_weights) / total
    positions = np.searchsorted(cumulative, np.asarray(quantiles, dtype=float), side="left")
    return ordered_values[np.clip(positions, 0, len(ordered_values) - 1)]


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
        quartiles = _weighted_percentile(offsets_months, weights, (0.25, 0.75))
        iqr_months = float(quartiles[1] - quartiles[0])

    return AnnualTimingSummary(
        concentration=concentration,
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        iqr_months=iqr_months,
        uniformity_p=float(uniformity_p),
        n_years=n_years,
        dominant_month=dominant_month,
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
    finite = values.loc[np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))]
    if finite.empty:
        return ()
    extremum = float(finite.min() if kind == "min" else finite.max())
    if kind == "min":
        selected = finite.loc[finite <= extremum + tolerance]
    else:
        selected = finite.loc[finite >= extremum - tolerance]
    return tuple(sorted({int(stamp.month) for stamp in selected.index}))


def shortest_circular_span(months: Iterable[int]) -> int | None:
    """Return the narrowest inclusive month span covering circular month values.

    A singleton has span zero; December and January have span one.  ``None``
    represents an absent equivalent-extremum set.
    """
    values = tuple(months)
    if not values:
        return None
    if any(isinstance(month, bool) or not isinstance(month, Integral) for month in values):
        raise ValueError("months must contain integral values")
    selected = np.unique(np.asarray(values, dtype=np.int64))
    if np.any((selected < 1) | (selected > _MONTHS_PER_YEAR)):
        raise ValueError("months must be integers from 1 to 12")
    if len(selected) == 1:
        return 0
    gaps = np.diff(np.r_[selected, selected[0] + _MONTHS_PER_YEAR])
    return int(_MONTHS_PER_YEAR - gaps.max())


def equivalent_extremum_dates(
    values: pd.Series,
    *,
    kind: Literal["min", "max"],
    tolerance: float,
) -> tuple[pd.Timestamp, ...]:
    """Chronologically ordered timestamps tied with a window's extremum.

    Unlike :func:`equivalent_extremum_months`, this is not circular and does
    not fold repeated calendar months onto one label: it is meant for a single
    bounded window (one hydrological-year cycle), not a multi-year record, so
    each observation keeps its own date.
    """
    if kind not in {"min", "max"}:
        raise ValueError("kind must be 'min' or 'max'.")
    if not np.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("tolerance must be a non-negative finite number.")
    finite = values.loc[np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))]
    if finite.empty:
        return ()
    extremum = float(finite.min() if kind == "min" else finite.max())
    if kind == "min":
        selected = finite.loc[finite <= extremum + tolerance]
    else:
        selected = finite.loc[finite >= extremum - tolerance]
    return tuple(pd.Timestamp(stamp) for stamp in selected.index.sort_values())


def linear_span_months(dates: Iterable[pd.Timestamp]) -> int | None:
    """Return the inclusive month span between the earliest and latest date.

    Non-circular counterpart of :func:`shortest_circular_span`, for a
    timestamp set drawn from one bounded window rather than a multi-year
    calendar-month record. A singleton has span zero.
    """
    values = tuple(dates)
    if not values:
        return None
    stamps = sorted(pd.Timestamp(value) for value in values)
    first, last = stamps[0], stamps[-1]
    return (last.year - first.year) * _MONTHS_PER_YEAR + last.month - first.month


__all__ = [
    "AnnualTimingSummary",
    "equivalent_extremum_dates",
    "equivalent_extremum_months",
    "linear_span_months",
    "shortest_circular_span",
    "summarise_annual_timing",
]


