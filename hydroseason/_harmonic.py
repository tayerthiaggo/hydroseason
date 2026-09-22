from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Literal

import numpy as np
import pandas as pd

_MONTHS_PER_YEAR = 12
_MAX_HARMONIC_ORDER = 3
_ALL_MONTHS = np.arange(1, _MONTHS_PER_YEAR + 1)


def _design_for_months(month: np.ndarray, order: int) -> np.ndarray:
    """Harmonic design matrix evaluated at arbitrary calendar months."""
    theta = 2.0 * np.pi * (month - 1) / _MONTHS_PER_YEAR
    columns = [np.ones(len(month))]
    for harmonic in range(1, order + 1):
        columns.extend([np.sin(harmonic * theta), np.cos(harmonic * theta)])
    return np.column_stack(columns)


def _design(order: int) -> np.ndarray:
    """Fixed 12-row harmonic design over January..December."""
    return _design_for_months(_ALL_MONTHS, order)


def _year_matrices(prepared: pd.DataFrame, weights: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reshape a prepared monthly frame into (years, values, weights) matrices.

    Months are placed by their true calendar month, never by position, so a
    partial year keeps its real phase. Absent or unusable months carry NaN
    value and zero weight, which removes them from every weighted sum without
    removing the year.
    """
    index = pd.DatetimeIndex(prepared.index)
    year_values = index.year.to_numpy()
    month_values = index.month.to_numpy()
    years = np.unique(year_values)
    row_of_year = {int(year): position for position, year in enumerate(years)}

    values = np.full((len(years), _MONTHS_PER_YEAR), np.nan, dtype=float)
    weight_matrix = np.zeros((len(years), _MONTHS_PER_YEAR), dtype=float)

    extent = pd.to_numeric(prepared["extent_pct"], errors="coerce").to_numpy(dtype=float)
    weight_array = weights.to_numpy(dtype=float)
    for position in range(len(index)):
        row = row_of_year[int(year_values[position])]
        column = int(month_values[position]) - 1
        values[row, column] = extent[position]
        weight_matrix[row, column] = weight_array[position]

    # A NaN value can never carry weight; guard rather than trusting callers.
    weight_matrix = np.where(np.isfinite(values), weight_matrix, 0.0)
    return years, values, weight_matrix


def _year_gram(
    values_row: np.ndarray,
    weights_row: np.ndarray,
    design: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Weighted normal-equation contributions from one year.

    Returning per-year Gram pieces is what makes leave-one-year-out cheap:
    training on all-but-one year is a subtraction, not a refit.
    """
    safe_values = np.where(np.isfinite(values_row), values_row, 0.0)
    weighted = design * weights_row[:, None]
    gram = weighted.T @ design
    moment = weighted.T @ safe_values
    return gram, moment, float(weights_row.sum()), float(np.sum(weights_row * safe_values**2))


def _solve_gram(gram: np.ndarray, moment: np.ndarray) -> np.ndarray | None:
    """Solve normal equations, returning None rather than raising when singular."""
    try:
        return np.linalg.solve(gram, moment)
    except np.linalg.LinAlgError:
        return None


@dataclass(frozen=True)
class HarmonicSelection:
    """Result of leave-one-year-out harmonic order selection."""

    order: int
    fold_skills: tuple[float, ...]
    mean_skill: float
    standard_error: float
    pooled_skill: float
    eligible_orders: tuple[int, ...]
    coefficients: np.ndarray


def _fold_scores(values: np.ndarray, weights: np.ndarray, order: int) -> tuple[list[float], float, float] | None:
    """Per-fold skills plus pooled candidate and null SSE for one order.

    Returns None when any fold's training sample cannot support the candidate,
    which makes eligibility a property of the whole cross-validation rather
    than of the full record only.
    """
    design = _design(order)
    n_coefficients = design.shape[1]
    n_years = values.shape[0]
    if n_years < 2:
        return None

    grams, moments, weight_sums = [], [], []
    for row in range(n_years):
        gram, moment, weight_sum, _ = _year_gram(values[row], weights[row], design)
        grams.append(gram)
        moments.append(moment)
        weight_sums.append(weight_sum)
    total_gram = np.sum(grams, axis=0)
    total_moment = np.sum(moments, axis=0)
    total_weight = float(np.sum(weight_sums))

    fold_skills: list[float] = []
    pooled_candidate = 0.0
    pooled_null = 0.0
    for row in range(n_years):
        test_weights = weights[row]
        if test_weights.sum() <= 0.0:
            continue
        n_train_observations = int(np.count_nonzero(weights) - np.count_nonzero(test_weights))
        if n_train_observations <= n_coefficients + 1:
            return None

        beta = _solve_gram(total_gram - grams[row], total_moment - moments[row])
        if beta is None:
            return None

        train_weight_total = total_weight - weight_sums[row]
        if train_weight_total <= 0.0:
            return None
        # The intercept moment divided by total weight IS the weighted mean,
        # so the order-0 null costs no extra fit.
        null_prediction = (total_moment[0] - moments[row][0]) / train_weight_total

        observed = np.where(np.isfinite(values[row]), values[row], 0.0)
        predicted = design @ beta
        candidate_sse = float(np.sum(test_weights * (observed - predicted) ** 2))
        null_sse = float(np.sum(test_weights * (observed - null_prediction) ** 2))
        pooled_candidate += candidate_sse
        pooled_null += null_sse
        fold_skills.append(1.0 - candidate_sse / null_sse if null_sse > 0.0 else 0.0)

    if not fold_skills:
        return None
    return fold_skills, pooled_candidate, pooled_null


def select_harmonic_order(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    max_order: int = _MAX_HARMONIC_ORDER,
) -> HarmonicSelection | None:
    """Choose harmonic order by leave-one-year-out skill under the 1-SE rule.

    The one-standard-error rule selects the lowest order whose mean fold skill
    is within one standard error of the best candidate's mean. It replaces a
    fixed absolute tolerance, which is scale-dependent: the same margin is
    loose on a short noisy record and tight on a long clean one.
    """
    if max_order < 0 or max_order > _MAX_HARMONIC_ORDER:
        raise ValueError(f"max_order must be between 0 and {_MAX_HARMONIC_ORDER}.")

    scored: dict[int, tuple[list[float], float, float]] = {}
    for order in range(max_order + 1):
        result = _fold_scores(values, weights, order)
        if result is not None:
            scored[order] = result
    if not scored:
        return None

    means = {order: float(np.mean(skills)) for order, (skills, _, _) in scored.items()}
    best_order = max(means, key=lambda order: (means[order], -order))
    best_skills = scored[best_order][0]
    best_error = (
        float(np.std(best_skills, ddof=1) / np.sqrt(len(best_skills))) if len(best_skills) > 1 else 0.0
    )
    threshold = means[best_order] - best_error
    chosen = min(order for order in scored if means[order] >= threshold)

    skills, pooled_candidate, pooled_null = scored[chosen]
    pooled_skill = 1.0 - pooled_candidate / pooled_null if pooled_null > 0.0 else 0.0

    design = _design(chosen)
    gram = np.zeros((design.shape[1], design.shape[1]))
    moment = np.zeros(design.shape[1])
    for row in range(values.shape[0]):
        year_gram, year_moment, _, _ = _year_gram(values[row], weights[row], design)
        gram += year_gram
        moment += year_moment
    coefficients = _solve_gram(gram, moment)
    if coefficients is None:
        return None

    standard_error = float(np.std(skills, ddof=1) / np.sqrt(len(skills))) if len(skills) > 1 else 0.0

    return HarmonicSelection(
        order=chosen,
        fold_skills=tuple(float(value) for value in skills),
        mean_skill=float(np.mean(skills)),
        standard_error=standard_error,
        pooled_skill=float(pooled_skill),
        eligible_orders=tuple(sorted(scored)),
        coefficients=coefficients,
    )


# Scaling that makes the median absolute deviation a consistent estimator of
# the standard deviation for normally distributed residuals.
_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class AmplitudeEvidence:
    """Seasonal amplitude against a robust, floored noise scale."""

    seasonal_amplitude_pp: float
    robust_noise_pp: float
    amplitude_noise_ratio: float
    at_or_below_floor: bool


def amplitude_evidence(
    values: np.ndarray,
    weights: np.ndarray,
    selection: HarmonicSelection,
    *,
    resolution_floor_pp: float,
) -> AmplitudeEvidence:
    """Seasonal amplitude and its ratio to a noise scale that cannot be zero.

    The denominator is the larger of the robust residual scale and the
    observation-resolution floor, so a noiseless or constant record yields a
    finite ratio rather than infinity. When the amplitude itself is at or below
    the floor the record has no resolvable seasonal signal at all, and the ratio
    is reported as zero rather than as a large number divided by a small one.
    """
    if not np.isfinite(resolution_floor_pp) or resolution_floor_pp <= 0.0:
        raise ValueError("resolution_floor_pp must be a positive finite number.")

    design = _design(selection.order)
    curve = design @ selection.coefficients
    amplitude = float(curve.max() - curve.min())

    residuals = []
    for row in range(values.shape[0]):
        observed = values[row]
        mask = (weights[row] > 0.0) & np.isfinite(observed)
        if mask.any():
            residuals.append(observed[mask] - curve[mask])
    if residuals:
        stacked = np.concatenate(residuals)
        mad = float(np.median(np.abs(stacked - np.median(stacked))))
        robust_noise = _MAD_TO_SIGMA * mad
    else:
        robust_noise = 0.0

    at_or_below_floor = amplitude <= resolution_floor_pp
    if at_or_below_floor:
        ratio = 0.0
    else:
        ratio = amplitude / max(robust_noise, float(resolution_floor_pp))

    return AmplitudeEvidence(
        seasonal_amplitude_pp=amplitude,
        robust_noise_pp=float(robust_noise),
        amplitude_noise_ratio=float(ratio),
        at_or_below_floor=bool(at_or_below_floor),
    )


_DEFAULT_N_NULL = 999


def _rotate_years(
    values: np.ndarray,
    weights: np.ndarray,
    offsets: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Roll each year around the calendar circle by its own offset.

    Values and weights roll together so a poorly observed month stays poorly
    observed. Gaps roll with them, so each year keeps its own shape, spacing and
    missingness; only its alignment with the calendar is destroyed.
    """
    rotated_values = np.empty_like(values)
    rotated_weights = np.empty_like(weights)
    for row in range(values.shape[0]):
        shift = int(offsets[row])
        rotated_values[row] = np.roll(values[row], shift)
        rotated_weights[row] = np.roll(weights[row], shift)
    return rotated_values, rotated_weights


def _null_skills(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    n_null: int,
    random_state: int,
    max_order: int,
    reselect_order: bool = True,
) -> np.ndarray:
    """Pooled skills under the rotation null.

    ``reselect_order=False`` exists only so tests can demonstrate why
    re-selection is required; production callers must leave it True.
    """
    fixed_order = None
    if not reselect_order:
        observed_selection = select_harmonic_order(values, weights, max_order=max_order)
        fixed_order = observed_selection.order if observed_selection is not None else 0

    rng = np.random.default_rng(np.random.SeedSequence(int(random_state)))
    offsets = rng.integers(0, _MONTHS_PER_YEAR, size=(int(n_null), values.shape[0]))
    skills = np.zeros(int(n_null), dtype=float)
    for position in range(int(n_null)):
        rotated_values, rotated_weights = _rotate_years(values, weights, offsets[position])
        order_cap = max_order if fixed_order is None else fixed_order
        selection = select_harmonic_order(rotated_values, rotated_weights, max_order=order_cap)
        if selection is None:
            continue
        if fixed_order is not None and selection.order != fixed_order:
            continue
        skills[position] = selection.pooled_skill
    return skills


def periodicity_p_value(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    n_null: int = _DEFAULT_N_NULL,
    random_state: int = 0,
    max_order: int = _MAX_HARMONIC_ORDER,
) -> float:
    """Probability of the observed seasonal skill under calendar-phase rotation.

    The complete leave-one-year-out procedure, order re-selection included, is
    re-run for every resample. Because the observed statistic is post-selection
    and therefore optimistically biased, the null must carry the same bias for
    the p-value to be calibrated.
    """
    if isinstance(n_null, bool) or not isinstance(n_null, Integral) or n_null < 1:
        raise ValueError("n_null must be a positive integer.")

    observed_selection = select_harmonic_order(values, weights, max_order=max_order)
    if observed_selection is None:
        return 1.0
    observed = observed_selection.pooled_skill

    null_skills = _null_skills(
        values, weights, n_null=int(n_null), random_state=random_state, max_order=max_order
    )
    return float((1.0 + np.count_nonzero(null_skills >= observed)) / (int(n_null) + 1.0))


def _curve_extrema(curve: np.ndarray, kind: str) -> list[int]:
    """Local extremum months of a closed 12-month curve."""
    sign = 1.0 if kind == "peak" else -1.0
    scaled = sign * curve
    span = float(scaled.max() - scaled.min())
    if span <= np.finfo(float).eps:
        return []
    return [
        index + 1
        for index in range(_MONTHS_PER_YEAR)
        if scaled[index] > scaled[(index - 1) % _MONTHS_PER_YEAR]
        and scaled[index] >= scaled[(index + 1) % _MONTHS_PER_YEAR]
    ]


def _circular_month_distance(left: int, right: int) -> int:
    raw = abs(left - right)
    return min(raw, _MONTHS_PER_YEAR - raw)


def retained_modes(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    kind: Literal["peak", "trough"],
    min_frequency: float,
    min_separation_months: int,
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> tuple[int, ...]:
    """Modes surviving year-bootstrap refits, thinned by circular separation.

    A single full-record fit reports whatever shape it happened to land on. A
    mode is only reported here if it reappears across resampled refits, so
    ``*_timing_n_modes`` reflects reproducible structure rather than one fit.
    """
    if kind not in {"peak", "trough"}:
        raise ValueError("kind must be 'peak' or 'trough'.")
    if not 0.0 < float(min_frequency) <= 1.0:
        raise ValueError("min_frequency must be in (0, 1].")
    if min_separation_months < 1:
        raise ValueError("min_separation_months must be at least 1.")

    n_years = values.shape[0]
    if n_years < 2:
        return ()

    rng = np.random.default_rng(np.random.SeedSequence(int(random_state)))
    draws = rng.integers(0, n_years, size=(int(n_bootstrap), n_years))
    counts = np.zeros(_MONTHS_PER_YEAR + 1, dtype=float)
    valid = 0
    for row in draws:
        selection = select_harmonic_order(values[row], weights[row])
        if selection is None:
            continue
        valid += 1
        curve = _design(selection.order) @ selection.coefficients
        for month in _curve_extrema(curve, kind):
            counts[month] += 1.0
    if valid == 0:
        return ()

    frequencies = counts / valid
    candidates = sorted(
        (month for month in range(1, _MONTHS_PER_YEAR + 1) if frequencies[month] >= float(min_frequency)),
        key=lambda month: (-frequencies[month], month),
    )

    kept: list[int] = []
    for month in candidates:
        if all(_circular_month_distance(month, other) >= min_separation_months for other in kept):
            kept.append(month)
    return tuple(sorted(kept))
