"""Calibration search space, statistics caches, and lexicographic objective.

Pre-computes threshold-independent evidence and phase statistics once per record,
allowing the 190,080-point grid to be scored vectorially without re-running
harmonic regression or circular timing models.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import RobustBoundaryConfig
from ._boundary_recoverability import evaluate_year
from ._circular_timing import equivalent_extremum_months, summarise_annual_timing, timing_drift
from ._cycle_phase import normalise_cycle
from ._harmonic import (
    _design,
    _year_matrices,
    amplitude_evidence,
    periodicity_p_value,
    retained_modes,
    select_harmonic_order,
)
from ._state_input import candidate_weights, prepare_monthly_extent
from ._synthetic import SyntheticRecord, generate_record

MODE_FREQUENCY_GRID = (0.50, 0.60, 0.70, 0.80)


@dataclass(frozen=True)
class RecordStatistics:
    """Threshold-independent statistics extracted from one synthetic record."""

    seed: int
    family: str
    n_years: int
    n_evaluable_years: int
    seasonal_cv_skill: float
    periodicity_p: float
    amplitude_noise_ratio: float
    at_or_below_floor: bool
    peak_n_modes_by_frequency: dict[float, int]
    trough_n_modes_by_frequency: dict[float, int]
    timing_concentration: float
    timing_uniformity_p: float
    drift_status: str
    boundary_errors: tuple[float, ...]
    boundary_n: int
    boundary_coverage: float
    truth_is_annual: bool
    truth_trough_month: int | None


@dataclass(frozen=True)
class PhaseCycleStatistics:
    """Threshold-independent geometry, residuals, and truth for one annual cycle."""

    seed: int
    year: int
    cycle_frame: pd.DataFrame
    normalised_z: pd.Series
    smoothed_z: pd.Series
    denominator_pp: float
    smoothed_peak_position: int | None
    observed_peak_position: int | None
    sufficient: bool
    start_extent_candidates: tuple[float, ...]
    end_extent_candidates: tuple[float, ...]
    noise_residuals: np.ndarray
    true_phase: pd.Series


def compute_statistics(record: SyntheticRecord) -> RecordStatistics:
    """Compute threshold-independent evidence and boundary statistics for one record."""
    prepared = prepare_monthly_extent(record.frame)
    weights = candidate_weights(prepared)
    years, values, weight_matrix = _year_matrices(prepared, weights)

    selection = select_harmonic_order(values, weight_matrix)
    if selection is None:
        seasonal_cv_skill = 0.0
        periodicity_p = 1.0
        amplitude_noise_ratio = 0.0
        at_or_below_floor = True
    else:
        seasonal_cv_skill = float(selection.pooled_skill)
        periodicity_p = float(
            periodicity_p_value(values, weight_matrix, n_null=99, random_state=record.seed)
        )
        amp = amplitude_evidence(values, weight_matrix, selection, resolution_floor_pp=0.5)
        amplitude_noise_ratio = float(amp.amplitude_noise_ratio)
        at_or_below_floor = bool(amp.at_or_below_floor)

    peak_n_modes_by_frequency = {}
    trough_n_modes_by_frequency = {}
    for freq in MODE_FREQUENCY_GRID:
        pk_modes = retained_modes(
            values,
            weight_matrix,
            kind="peak",
            min_frequency=freq,
            min_separation_months=2,
            random_state=record.seed,
        )
        tr_modes = retained_modes(
            values,
            weight_matrix,
            kind="trough",
            min_frequency=freq,
            min_separation_months=2,
            random_state=record.seed,
        )
        peak_n_modes_by_frequency[freq] = len(pk_modes)
        trough_n_modes_by_frequency[freq] = len(tr_modes)

    month_sets = {}
    for y in years:
        month_sets[int(y)] = equivalent_extremum_months(
            prepared.loc[str(y), "extent_pct"], kind="min", tolerance=0.5
        )

    timing_summary = summarise_annual_timing(month_sets, random_state=record.seed)
    timing_concentration = (
        float(timing_summary.concentration) if timing_summary.concentration is not None else 0.0
    )
    timing_uniformity_p = (
        float(timing_summary.uniformity_p) if timing_summary.uniformity_p is not None else 1.0
    )

    drift = timing_drift(month_sets, min_timing_years=5, random_state=record.seed)
    drift_status = str(drift.status)

    boundary_config = RobustBoundaryConfig()
    evaluations = [
        evaluate_year(
            prepared,
            year=int(y),
            month_sets=month_sets,
            config=boundary_config,
            search_radius_months=3,
            min_usable_months=3,
        )
        for y in sorted(month_sets)
    ]
    evaluable = [item for item in evaluations if item.evaluable]
    resolved = [item for item in evaluable if item.resolved and item.error_months is not None]
    boundary_errors = tuple(float(item.error_months) for item in resolved)
    boundary_n = len(evaluable)
    boundary_coverage = float(len(resolved) / boundary_n) if boundary_n > 0 else 0.0

    return RecordStatistics(
        seed=record.seed,
        family=record.family,
        n_years=record.truth.n_years,
        n_evaluable_years=boundary_n,
        seasonal_cv_skill=seasonal_cv_skill,
        periodicity_p=periodicity_p,
        amplitude_noise_ratio=amplitude_noise_ratio,
        at_or_below_floor=at_or_below_floor,
        peak_n_modes_by_frequency=peak_n_modes_by_frequency,
        trough_n_modes_by_frequency=trough_n_modes_by_frequency,
        timing_concentration=timing_concentration,
        timing_uniformity_p=timing_uniformity_p,
        drift_status=drift_status,
        boundary_errors=boundary_errors,
        boundary_n=boundary_n,
        boundary_coverage=boundary_coverage,
        truth_is_annual=record.truth.is_annual,
        truth_trough_month=record.truth.trough_month,
    )


def compute_phase_statistics(record: SyntheticRecord) -> tuple[PhaseCycleStatistics, ...]:
    """Compute threshold-independent cycle geometry and truth for all annual cycles."""
    prepared = prepare_monthly_extent(record.frame)
    weights = candidate_weights(prepared)
    years, values, weight_matrix = _year_matrices(prepared, weights)

    selection = select_harmonic_order(values, weight_matrix)
    if selection is not None:
        design = _design(selection.order)
        curve = design @ selection.coefficients
        residuals = []
        for r in range(values.shape[0]):
            obs = values[r]
            m = (weight_matrix[r] > 0.0) & np.isfinite(obs)
            if m.any():
                residuals.append(obs[m] - curve[m])
        noise_residuals = np.concatenate(residuals) if residuals else np.zeros(1, dtype=float)
    else:
        noise_residuals = np.zeros(1, dtype=float)

    cycle_stats: list[PhaseCycleStatistics] = []
    for y in years:
        cycle_months = prepared.loc[str(y)].index
        if len(cycle_months) == 0:
            continue
        cycle_df = prepared.loc[cycle_months]
        if record.truth.phase_by_month is not None:
            true_phase_slice = record.truth.phase_by_month.loc[cycle_months]
        else:
            true_phase_slice = pd.Series("unspecified", index=cycle_months, dtype=object)

        cand_vals = cycle_df["extent_pct"].dropna()
        start_extent = float(cand_vals.iloc[0]) if len(cand_vals) else 0.0
        end_extent = float(cand_vals.iloc[-1]) if len(cand_vals) else 0.0

        normalised = normalise_cycle(
            cycle_df,
            start_extent=start_extent,
            end_extent=end_extent,
            window=1,
            resolution_floor_pp=0.5,
        )

        cycle_stats.append(
            PhaseCycleStatistics(
                seed=record.seed,
                year=int(y),
                cycle_frame=cycle_df,
                normalised_z=normalised.z,
                smoothed_z=normalised.smoothed_z,
                denominator_pp=normalised.denominator_pp,
                smoothed_peak_position=normalised.smoothed_peak_position,
                observed_peak_position=normalised.observed_peak_position,
                sufficient=normalised.sufficient,
                start_extent_candidates=(start_extent,),
                end_extent_candidates=(end_extent,),
                noise_residuals=noise_residuals,
                true_phase=true_phase_slice,
            )
        )

    return tuple(cycle_stats)


def build_evidence_cache(
    seeds: Iterable[int], *, partition: Literal["calibration", "validation"]
) -> pd.DataFrame:
    """Build threshold-independent evidence dataframe over a set of record seeds."""
    rows = []
    for seed in seeds:
        record = generate_record(seed, partition=partition)
        stats = compute_statistics(record)
        row = {
            "seed": stats.seed,
            "family": stats.family,
            "n_years": stats.n_years,
            "n_evaluable_years": stats.n_evaluable_years,
            "seasonal_cv_skill": stats.seasonal_cv_skill,
            "periodicity_p": stats.periodicity_p,
            "amplitude_noise_ratio": stats.amplitude_noise_ratio,
            "at_or_below_floor": stats.at_or_below_floor,
            "timing_concentration": stats.timing_concentration,
            "timing_uniformity_p": stats.timing_uniformity_p,
            "drift_status": stats.drift_status,
            "boundary_n": stats.boundary_n,
            "boundary_coverage": stats.boundary_coverage,
            "truth_is_annual": stats.truth_is_annual,
            "truth_trough_month": stats.truth_trough_month if stats.truth_trough_month is not None else -1,
        }
        for freq in MODE_FREQUENCY_GRID:
            row[f"peak_n_modes_{freq:.2f}"] = stats.peak_n_modes_by_frequency[freq]
            row[f"trough_n_modes_{freq:.2f}"] = stats.trough_n_modes_by_frequency[freq]
        rows.append(row)

    return pd.DataFrame(rows)


def build_phase_cache(
    seeds: Iterable[int], *, partition: Literal["calibration", "validation"]
) -> tuple[PhaseCycleStatistics, ...]:
    """Build cycle statistics tuple over a set of record seeds."""
    all_cycles: list[PhaseCycleStatistics] = []
    for seed in seeds:
        record = generate_record(seed, partition=partition)
        cycles = compute_phase_statistics(record)
        all_cycles.extend(cycles)
    return tuple(all_cycles)
