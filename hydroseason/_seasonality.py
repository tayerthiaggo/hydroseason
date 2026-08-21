from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._state_input import prepare_monthly_extent

Pattern = Literal["unimodal_annual", "bimodal_or_complex", "weak_or_irregular", "low_variability", "insufficient_record"]


@dataclass(frozen=True)
class SeasonalPatternResult:
    pattern: Pattern
    expected_peak_month: int | None
    expected_trough_month: int | None
    secondary_peak_month: int | None
    secondary_trough_month: int | None
    seasonal_strength: float
    bootstrap_support: float
    peak_phase_iqr_months: float | None
    trough_phase_iqr_months: float | None
    n_complete_years: int


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


def _fit(month: np.ndarray, values: np.ndarray, order: int) -> tuple[np.ndarray, float]:
    matrix = _design_for_months(month, order)
    beta = np.linalg.lstsq(matrix, values, rcond=None)[0]
    residual = values - matrix @ beta
    rss = max(float(residual @ residual), np.finfo(float).tiny)
    n, k = len(values), matrix.shape[1]
    aic = n * np.log(rss / n) + 2 * k
    aicc = aic + (2 * k * (k + 1) / (n - k - 1)) if n > k + 1 else np.inf
    return beta, float(aicc)



def _local_extrema(curve: np.ndarray, kind: str) -> list[int]:
    sign = 1.0 if kind == "max" else -1.0
    scaled = sign * curve
    return [i + 1 for i in range(12) if scaled[i] > scaled[(i - 1) % 12] and scaled[i] >= scaled[(i + 1) % 12]]


def _phase_iqr(months: list[int]) -> float | None:
    if not months:
        return None
    radians = 2.0 * np.pi * (np.asarray(months) - 1) / 12.0
    centre = np.angle(np.mean(np.exp(1j * radians)))
    offsets = np.angle(np.exp(1j * (radians - centre))) * 12.0 / (2.0 * np.pi)
    return float(np.percentile(offsets, 75) - np.percentile(offsets, 25))


def _classify_values(month: np.ndarray, values: np.ndarray, tolerance: float) -> tuple[Pattern, np.ndarray, int, float]:
    fits = [_fit(month, values, order) for order in (0, 1, 2)]
    order = int(np.argmin([item[1] for item in fits]))
    beta = fits[order][0]
    curve = _design(order) @ beta
    intercept_rss = max(float(np.sum((values - values.mean()) ** 2)), np.finfo(float).tiny)
    selected_rss = max(float(np.sum((values - _design_for_months(month, order) @ beta) ** 2)), np.finfo(float).tiny)
    strength = float(np.clip(1.0 - selected_rss / intercept_rss, 0.0, 1.0))

    if float(curve.max() - curve.min()) <= tolerance:
        return "low_variability", curve, order, strength
    if order == 0:
        return "weak_or_irregular", curve, order, strength
    maxima = _local_extrema(curve, "max")
    return ("unimodal_annual" if len(maxima) == 1 else "bimodal_or_complex"), curve, order, strength


def classify_seasonal_pattern(
    extent,
    *,
    n_bootstrap: int = 200,
    random_state: int = 0,
    measurement_tolerance_pct: float = 1.0,
    quality_policy: Literal["exclude", "flag"] = "flag",
) -> SeasonalPatternResult:
    frame = prepare_monthly_extent(extent, quality_policy=quality_policy)
    usable = frame.loc[frame["candidate_usable"]]
    complete_years = [year for year, group in usable.groupby(usable.index.year) if set(group.index.month) == set(range(1, 13))]
    if len(complete_years) < 5:
        return SeasonalPatternResult("insufficient_record", None, None, None, None, 0.0, 0.0, None, None, len(complete_years))
    sample = usable.loc[usable.index.year.isin(complete_years)]
    pattern, curve, _, strength = _classify_values(sample.index.month.to_numpy(), sample["extent_pct"].to_numpy(float), measurement_tolerance_pct)
    maxima, minima = _local_extrema(curve, "max"), _local_extrema(curve, "min")
    peaks = sorted(maxima, key=lambda month: curve[month - 1], reverse=True)
    troughs = sorted(minima, key=lambda month: curve[month - 1])
    peak = peaks[0] if peaks else int(np.argmax(curve) + 1)
    trough = troughs[0] if troughs else int(np.argmin(curve) + 1)

    rng = np.random.default_rng(random_state)
    support, boot_peaks, boot_troughs = 0, [], []
    by_year = {year: sample.loc[sample.index.year == year] for year in complete_years}
    for _ in range(n_bootstrap):
        draw = [by_year[int(year)] for year in rng.choice(complete_years, len(complete_years), replace=True)]
        boot = pd.concat(draw, ignore_index=True)
        boot_month = np.tile(np.arange(1, 13), len(draw))
        boot_pattern, boot_curve, _, _ = _classify_values(boot_month, boot["extent_pct"].to_numpy(float), measurement_tolerance_pct)
        support += int(boot_pattern == pattern)
        boot_peaks.append(int(np.argmax(boot_curve) + 1))
        boot_troughs.append(int(np.argmin(boot_curve) + 1))
    bootstrap_support = support / n_bootstrap if n_bootstrap else 0.0
    if pattern not in ("low_variability", "insufficient_record") and bootstrap_support < 0.80:
        pattern = "weak_or_irregular"
    stable_peak = None if pattern == "low_variability" else peak
    stable_trough = None if pattern == "low_variability" else trough
    return SeasonalPatternResult(
        pattern, stable_peak, stable_trough,
        peaks[1] if len(peaks) > 1 else None,
        troughs[1] if len(troughs) > 1 else None,
        strength, bootstrap_support, _phase_iqr(boot_peaks), _phase_iqr(boot_troughs), len(complete_years),
    )
