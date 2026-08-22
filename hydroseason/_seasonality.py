from __future__ import annotations

from dataclasses import dataclass, replace
from numbers import Integral
from typing import Literal

import numpy as np
import pandas as pd

from ._harmonic import (
    _DEFAULT_N_NULL,
    _curve_extrema,
    _design,
    _year_matrices,
    amplitude_evidence,
    periodicity_p_value,
    retained_modes,
    select_harmonic_order,
)
from ._state_input import candidate_weights, prepare_monthly_extent

Pattern = Literal[
    "unimodal_annual",
    "bimodal_or_complex",
    "weak_or_irregular",
    "low_variability",
    "insufficient_record",
]

_MIN_EVALUABLE_YEARS = 5


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
    seasonal_cv_skill: float
    periodicity_p: float
    selected_harmonic_order: int
    seasonal_amplitude_pp: float
    amplitude_noise_ratio: float
    peak_timing_n_modes: int
    trough_timing_n_modes: int
    n_evaluable_years: int


def _insufficient(n_complete: int, n_evaluable: int) -> SeasonalPatternResult:
    return SeasonalPatternResult(
        "insufficient_record",
        None,
        None,
        None,
        None,
        0.0,
        0.0,
        None,
        None,
        n_complete,
        0.0,
        1.0,
        0,
        0.0,
        0.0,
        0,
        0,
        n_evaluable,
    )


def classify_seasonal_pattern(
    extent,
    *,
    resolution_floor_pp: float | None = None,
    mode_min_frequency: float | None = None,
    mode_min_separation_months: int | None = None,
    n_bootstrap: int = 200,
    n_null: int = _DEFAULT_N_NULL,
    random_state: int = 0,
    measurement_tolerance_pct: float = 1.0,
    quality_policy: Literal["exclude", "flag"] = "flag",
) -> SeasonalPatternResult:
    """Classify annual-cycle shape from weighted, partial-year-tolerant evidence.

    Every month passing the observation policy contributes, weighted by its
    observed fraction. Complete calendar years remain a compatibility metric,
    but evaluable partial years now gate and inform the fit.
    """
    if not np.isfinite(measurement_tolerance_pct) or measurement_tolerance_pct < 0.0:
        raise ValueError("measurement_tolerance_pct must be a non-negative finite number.")
    if (mode_min_frequency is None) != (mode_min_separation_months is None):
        raise ValueError(
            "mode_min_frequency and mode_min_separation_months must be provided together."
        )
    if mode_min_frequency is not None and not 0.0 < float(mode_min_frequency) <= 1.0:
        raise ValueError("mode_min_frequency must be in (0, 1].")
    if mode_min_separation_months is not None and (
        isinstance(mode_min_separation_months, bool)
        or not isinstance(mode_min_separation_months, Integral)
        or mode_min_separation_months < 1
    ):
        raise ValueError("mode_min_separation_months must be an integer of at least 1.")
    if (
        isinstance(n_bootstrap, bool)
        or not isinstance(n_bootstrap, Integral)
        or n_bootstrap < (1 if mode_min_frequency is not None else 0)
    ):
        raise ValueError(
            "n_bootstrap must be positive when calibrated mode retention is enabled, "
            "otherwise non-negative."
        )
    if isinstance(n_null, bool) or not isinstance(n_null, Integral) or n_null < 1:
        raise ValueError("n_null must be a positive integer.")
    if isinstance(random_state, bool) or not isinstance(random_state, Integral):
        raise ValueError("random_state must be an integer.")
    if resolution_floor_pp is not None and (
        not np.isfinite(resolution_floor_pp) or resolution_floor_pp <= 0.0
    ):
        raise ValueError("resolution_floor_pp must be a positive finite number.")
    effective_resolution_floor = (
        max(float(measurement_tolerance_pct), np.finfo(float).eps)
        if resolution_floor_pp is None
        else float(resolution_floor_pp)
    )
    if isinstance(extent, pd.DataFrame) and "candidate_usable" in extent.columns:
        prepared = extent.copy()
        if "observed_fraction" not in prepared.columns:
            prepared["observed_fraction"] = 1.0
    else:
        prepared = prepare_monthly_extent(extent, quality_policy=quality_policy)
    weights = candidate_weights(prepared)
    usable = prepared.loc[prepared["candidate_usable"]]
    complete_years = [
        year
        for year, group in usable.groupby(usable.index.year)
        if set(group.index.month) == set(range(1, 13))
    ]
    if weights.sum() <= 0.0:
        return _insufficient(len(complete_years), 0)

    _years, values, weight_matrix = _year_matrices(prepared, weights)
    n_evaluable = int(np.count_nonzero(weight_matrix.sum(axis=1) > 0.0))
    if n_evaluable < _MIN_EVALUABLE_YEARS:
        return _insufficient(len(complete_years), n_evaluable)

    selection = select_harmonic_order(values, weight_matrix)
    if selection is None:
        return _insufficient(len(complete_years), n_evaluable)

    evidence = amplitude_evidence(
        values,
        weight_matrix,
        selection,
        resolution_floor_pp=effective_resolution_floor,
    )
    if (
        resolution_floor_pp is None
        and measurement_tolerance_pct == 0.0
        and evidence.seasonal_amplitude_pp > 0.0
        and evidence.at_or_below_floor
    ):
        numerical_denominator = max(
            evidence.robust_noise_pp,
            np.finfo(float).eps,
        )
        evidence = replace(
            evidence,
            amplitude_noise_ratio=evidence.seasonal_amplitude_pp
            / numerical_denominator,
            at_or_below_floor=False,
        )
    curve = _design(selection.order) @ selection.coefficients
    peak_seed, trough_seed, periodicity_seed = np.random.SeedSequence(
        int(random_state)
    ).spawn(3)
    peak_random_state = int(peak_seed.generate_state(1, dtype=np.uint32)[0])
    trough_random_state = int(trough_seed.generate_state(1, dtype=np.uint32)[0])
    periodicity_random_state = int(
        periodicity_seed.generate_state(1, dtype=np.uint32)[0]
    )

    if evidence.at_or_below_floor:
        return SeasonalPatternResult(
            "low_variability",
            None,
            None,
            None,
            None,
            0.0,
            0.0,
            None,
            None,
            len(complete_years),
            float(selection.pooled_skill),
            1.0,
            int(selection.order),
            float(evidence.seasonal_amplitude_pp),
            float(evidence.amplitude_noise_ratio),
            0,
            0,
            n_evaluable,
        )

    if mode_min_frequency is None:
        # Compatibility path for existing callers until generated calibration
        # defaults exist. Shape comes from the selected weighted curve, with no
        # invented mode-retention threshold.
        peak_modes = tuple(_curve_extrema(curve, "peak"))
        trough_modes = tuple(_curve_extrema(curve, "trough"))
    else:
        peak_modes = retained_modes(
            values,
            weight_matrix,
            kind="peak",
            min_frequency=mode_min_frequency,
            min_separation_months=mode_min_separation_months,
            n_bootstrap=n_bootstrap,
            random_state=peak_random_state,
        )
        trough_modes = retained_modes(
            values,
            weight_matrix,
            kind="trough",
            min_frequency=mode_min_frequency,
            min_separation_months=mode_min_separation_months,
            n_bootstrap=n_bootstrap,
            random_state=trough_random_state,
        )
    periodicity = periodicity_p_value(
        values,
        weight_matrix,
        n_null=n_null,
        random_state=periodicity_random_state,
    )

    if selection.order == 0:
        pattern: Pattern = "weak_or_irregular"
    elif len(peak_modes) > 1:
        pattern = "bimodal_or_complex"
    elif len(peak_modes) == 1:
        pattern = "unimodal_annual"
    else:
        pattern = "weak_or_irregular"

    ranked_peaks = sorted(peak_modes, key=lambda month: curve[month - 1], reverse=True)
    ranked_troughs = sorted(trough_modes, key=lambda month: curve[month - 1])
    fallback_peak = int(np.argmax(curve)) + 1
    fallback_trough = int(np.argmin(curve)) + 1

    return SeasonalPatternResult(
        pattern=pattern,
        expected_peak_month=ranked_peaks[0] if ranked_peaks else fallback_peak,
        expected_trough_month=ranked_troughs[0] if ranked_troughs else fallback_trough,
        secondary_peak_month=ranked_peaks[1] if len(ranked_peaks) > 1 else None,
        secondary_trough_month=ranked_troughs[1] if len(ranked_troughs) > 1 else None,
        seasonal_strength=float(np.clip(selection.pooled_skill, 0.0, 1.0)),
        bootstrap_support=float(bool(peak_modes)),
        peak_phase_iqr_months=None,
        trough_phase_iqr_months=None,
        n_complete_years=len(complete_years),
        seasonal_cv_skill=float(selection.pooled_skill),
        periodicity_p=float(periodicity),
        selected_harmonic_order=int(selection.order),
        seasonal_amplitude_pp=float(evidence.seasonal_amplitude_pp),
        amplitude_noise_ratio=float(evidence.amplitude_noise_ratio),
        peak_timing_n_modes=len(peak_modes),
        trough_timing_n_modes=len(trough_modes),
        n_evaluable_years=n_evaluable,
    )


__all__ = ["Pattern", "SeasonalPatternResult", "classify_seasonal_pattern"]
