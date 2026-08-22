"""Calibration search space, statistics caches, and lexicographic objective.

Pre-computes threshold-independent evidence and phase statistics once per record,
allowing the 190,080-point grid to be scored vectorially without re-running
harmonic regression or circular timing models.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import RobustBoundaryConfig
from ._boundary_recoverability import (
    RecoverabilityThresholds,
    evaluate_year,
)
from ._circular_timing import (
    equivalent_extremum_months,
    summarise_annual_timing,
    timing_drift,
)
from ._cycle_phase import PhaseThresholds, label_cycle, normalise_cycle
from ._evidence import (
    EvidenceThresholds,
    wilson_interval,
)
from ._harmonic import (
    _curve_extrema,
    _design,
    _year_matrices,
    amplitude_evidence,
    periodicity_p_value,
    select_harmonic_order,
)
from ._state_input import candidate_weights, prepare_monthly_extent
from ._synthetic import SyntheticRecord, generate_record

MODE_FREQUENCY_GRID = (0.50, 0.60, 0.70, 0.80)

EVIDENCE_GRID = {
    "seasonal_cv_skill": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    "periodicity_alpha": [0.01, 0.025, 0.05, 0.10],
    "amplitude_noise_ratio": [0.5, 0.7, 1.0, 1.5, 2.0],
    "mode_min_frequency": [0.50, 0.60, 0.70, 0.80],
    "strong_timing_concentration": [0.50, 0.60, 0.70, 0.80],
    "weak_timing_concentration": [0.30, 0.40, 0.50],
    "min_timing_years": [5, 7, 10],
    "within_1_month_wilson_floor": [0.30, 0.40, 0.50, 0.60],
    "admit_insufficient_drift": [False, True],
}

PHASE_GRID = {
    "phase_low_fraction": [0.10, 0.20, 0.25, 0.30],
    "phase_high_fraction": [0.60, 0.70, 0.75, 0.80],
    "phase_min_duration_months": [1, 2, 3],
    "phase_smoothing_window": [1, 3, 5],
}


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


@dataclass(frozen=True)
class GridScore:
    """Score summary for one evaluated evidence + recoverability point."""

    evidence: EvidenceThresholds
    recoverability: RecoverabilityThresholds
    false_annualisation_wilson_high: float
    false_annualisation_rate: float
    false_annualisation_by_length: dict[str, float]
    routing_recall: float
    correct_abstention: float
    boundary_mae: float


@dataclass(frozen=True)
class PhaseGridScore:
    """Score summary for one evaluated phase point."""

    thresholds: PhaseThresholds
    macro_accuracy: float
    transition_mae: float
    forced_complete_rate: float


def iter_evidence_points() -> Iterator[tuple]:
    """Iterate all 190,080 valid points of the evidence search grid."""
    for s_skill in EVIDENCE_GRID["seasonal_cv_skill"]:
        for p_alpha in EVIDENCE_GRID["periodicity_alpha"]:
            for anr in EVIDENCE_GRID["amplitude_noise_ratio"]:
                for m_freq in EVIDENCE_GRID["mode_min_frequency"]:
                    for s_conc in EVIDENCE_GRID["strong_timing_concentration"]:
                        for w_conc in EVIDENCE_GRID["weak_timing_concentration"]:
                            if w_conc >= s_conc:
                                continue
                            for min_y in EVIDENCE_GRID["min_timing_years"]:
                                for w_floor in EVIDENCE_GRID["within_1_month_wilson_floor"]:
                                    for admit_drift in EVIDENCE_GRID["admit_insufficient_drift"]:
                                        yield (
                                            float(s_skill),
                                            float(p_alpha),
                                            float(anr),
                                            float(m_freq),
                                            float(s_conc),
                                            float(w_conc),
                                            int(min_y),
                                            float(w_floor),
                                            bool(admit_drift),
                                        )


def iter_phase_points() -> Iterator[PhaseThresholds]:
    """Iterate all 144 points of the phase search grid."""
    for low in PHASE_GRID["phase_low_fraction"]:
        for high in PHASE_GRID["phase_high_fraction"]:
            if low >= high:
                continue
            for dur in PHASE_GRID["phase_min_duration_months"]:
                for win in PHASE_GRID["phase_smoothing_window"]:
                    yield PhaseThresholds(
                        phase_low_fraction=float(low),
                        phase_high_fraction=float(high),
                        phase_min_duration_months=int(dur),
                        phase_smoothing_window=int(win),
                    )


def _circular_month_distance(left: int, right: int) -> int:
    raw = abs(left - right)
    return min(raw, 12 - raw)


def _mode_counts_by_frequency(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    kind: Literal["peak", "trough"],
    frequency_grid: tuple[float, ...] = MODE_FREQUENCY_GRID,
    min_separation_months: int = 2,
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> dict[float, int]:
    """Compute mode counts for all candidate frequencies sharing one bootstrap sample."""
    n_years = values.shape[0]
    if n_years < 2:
        return {freq: 0 for freq in frequency_grid}

    rng = np.random.default_rng(np.random.SeedSequence(int(random_state)))
    draws = rng.integers(0, n_years, size=(int(n_bootstrap), n_years))
    counts = np.zeros(13, dtype=float)
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
        return {freq: 0 for freq in frequency_grid}

    frequencies = counts / valid
    result = {}
    for freq in frequency_grid:
        candidates = sorted(
            (m for m in range(1, 13) if frequencies[m] >= float(freq)),
            key=lambda m: (-frequencies[m], m),
        )
        kept: list[int] = []
        for m in candidates:
            if all(_circular_month_distance(m, o) >= min_separation_months for o in kept):
                kept.append(m)
        result[freq] = len(kept)
    return result


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

    peak_n_modes_by_frequency = _mode_counts_by_frequency(
        values, weight_matrix, kind="peak", random_state=record.seed
    )
    trough_n_modes_by_frequency = _mode_counts_by_frequency(
        values, weight_matrix, kind="trough", random_state=record.seed
    )

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

    # Fast order-1 fit for noise residuals
    design = _design(1)
    m = (weight_matrix > 0.0) & np.isfinite(values)
    if m.any():
        v_flat = values[m]
        w_flat = weight_matrix[m]
        d_flat = np.repeat(design[None, :, :], values.shape[0], axis=0)[m]
        sqrt_w = np.sqrt(w_flat)[:, None]
        d_w = d_flat * sqrt_w
        v_w = v_flat * sqrt_w.squeeze()
        coef, _, _, _ = np.linalg.lstsq(d_w, v_w, rcond=None)
        curve = design @ coef
        residuals = []
        for r in range(values.shape[0]):
            obs = values[r]
            row_m = (weight_matrix[r] > 0.0) & np.isfinite(obs)
            if row_m.any():
                residuals.append(obs[row_m] - curve[row_m])
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


_RECORD_STATS_CACHE: dict[tuple[int, str], RecordStatistics] = {}
_PHASE_STATS_CACHE: dict[tuple[int, str], tuple[PhaseCycleStatistics, ...]] = {}


def build_evidence_cache(
    seeds: Iterable[int], *, partition: Literal["calibration", "validation"]
) -> pd.DataFrame:
    """Build threshold-independent evidence dataframe over a set of record seeds."""
    rows = []
    for seed in seeds:
        key = (int(seed), str(partition))
        if key not in _RECORD_STATS_CACHE:
            record = generate_record(seed, partition=partition)
            _RECORD_STATS_CACHE[key] = compute_statistics(record)
        stats = _RECORD_STATS_CACHE[key]
        mean_b_error = float(np.mean(stats.boundary_errors)) if stats.boundary_errors else 0.0
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
            "boundary_mae": mean_b_error,
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
        key = (int(seed), str(partition))
        if key not in _PHASE_STATS_CACHE:
            record = generate_record(seed, partition=partition)
            _PHASE_STATS_CACHE[key] = compute_phase_statistics(record)
        cycles = _PHASE_STATS_CACHE[key]
        all_cycles.extend(cycles)
    return tuple(all_cycles)


def score_evidence_grid_point(evidence_cache: pd.DataFrame, point: tuple) -> GridScore:
    """Score one evidence + recoverability tuple over the evidence cache."""
    (
        s_skill,
        p_alpha,
        anr,
        m_freq,
        s_conc,
        w_conc,
        min_y,
        w_floor,
        admit_drift,
    ) = point

    ev_thresholds = EvidenceThresholds(
        seasonal_cv_skill=s_skill,
        periodicity_alpha=p_alpha,
        amplitude_noise_ratio=anr,
        mode_min_frequency=m_freq,
        mode_min_separation_months=2,
        strong_timing_concentration=s_conc,
        weak_timing_concentration=w_conc,
        min_timing_years=min_y,
    )
    rec_thresholds = RecoverabilityThresholds(
        min_years=5,
        min_coverage=0.80,
        min_within_1_month=0.80,
        within_1_month_wilson_floor=w_floor,
        max_p90_error_months=2.0,
        admit_insufficient_drift=admit_drift,
    )

    skill = evidence_cache["seasonal_cv_skill"].to_numpy(dtype=float)
    p_val = evidence_cache["periodicity_p"].to_numpy(dtype=float)
    ratio = evidence_cache["amplitude_noise_ratio"].to_numpy(dtype=float)
    at_floor = evidence_cache["at_or_below_floor"].to_numpy(dtype=bool)
    conc = evidence_cache["timing_concentration"].to_numpy(dtype=float)
    n_eval_years = evidence_cache["n_evaluable_years"].to_numpy(dtype=int)
    drift = evidence_cache["drift_status"].to_numpy(dtype=object)
    is_annual_truth = evidence_cache["truth_is_annual"].to_numpy(dtype=bool)
    family = evidence_cache["family"].to_numpy(dtype=object)
    n_years = evidence_cache["n_years"].to_numpy(dtype=int)
    b_mae = evidence_cache["boundary_mae"].to_numpy(dtype=float)

    pk_modes = evidence_cache[f"peak_n_modes_{m_freq:.2f}"].to_numpy(dtype=int)
    tr_modes = evidence_cache[f"trough_n_modes_{m_freq:.2f}"].to_numpy(dtype=int)
    unimodal = (pk_modes == 1) & (tr_modes == 1)

    significant = p_val < p_alpha
    skilful = skill >= s_skill
    loud = ratio >= anr
    concentrated = conc >= s_conc
    weakly_conc = conc >= w_conc
    drifting = drift == "detected"
    not_absent = (~at_floor) & (ratio > 0.0)
    sufficient_years = n_eval_years >= 5

    strong_ev = sufficient_years & not_absent & significant & skilful & loud & concentrated & unimodal & (~drifting)
    moderate_ev = sufficient_years & not_absent & significant & (skilful | loud) & weakly_conc & (~strong_ev)
    is_annual_pred = strong_ev | moderate_ev

    # Negative controls
    neg_mask = ~is_annual_truth
    n_neg = int(np.sum(neg_mask))
    k_neg = int(np.sum(neg_mask & is_annual_pred))
    _, wilson_high = wilson_interval(k_neg, n_neg) if n_neg > 0 else (0.0, 1.0)
    false_ann_rate = float(k_neg / n_neg) if n_neg > 0 else 0.0

    by_length = {}
    for length in (5, 7, 10, 20, 30):
        mask_l = neg_mask & (n_years == length)
        n_l = int(np.sum(mask_l))
        k_l = int(np.sum(mask_l & is_annual_pred))
        by_length[str(length)] = float(k_l / n_l) if n_l > 0 else 0.0

    # Positive controls
    pos_mask = np.isin(family, ["unimodal_symmetric", "monsoonal_sharp"])
    n_pos = int(np.sum(pos_mask))
    k_pos = int(np.sum(pos_mask & is_annual_pred))
    recall = float(k_pos / n_pos) if n_pos > 0 else 0.0

    # Abstention controls
    abs_mask = np.isin(family, ["bimodal", "switching_modes", "multi_year_regimes", "phase_drift"])
    n_abs = int(np.sum(abs_mask))
    k_abs = int(np.sum(abs_mask & (~is_annual_pred)))
    correct_abstention = float(k_abs / n_abs) if n_abs > 0 else 0.0

    # Boundary timing error on positive controls
    pos_res_mae = float(np.mean(b_mae[pos_mask])) if np.any(pos_mask) else 0.0

    return GridScore(
        evidence=ev_thresholds,
        recoverability=rec_thresholds,
        false_annualisation_wilson_high=float(wilson_high),
        false_annualisation_rate=false_ann_rate,
        false_annualisation_by_length=by_length,
        routing_recall=recall,
        correct_abstention=correct_abstention,
        boundary_mae=pos_res_mae,
    )


def select_evidence_defaults(
    evidence_cache: pd.DataFrame,
) -> tuple[EvidenceThresholds, RecoverabilityThresholds, list[GridScore]]:
    """Select optimal evidence and recoverability thresholds through multi-stage lexicographic pruning."""
    skill = evidence_cache["seasonal_cv_skill"].to_numpy(dtype=float)
    p_val = evidence_cache["periodicity_p"].to_numpy(dtype=float)
    ratio = evidence_cache["amplitude_noise_ratio"].to_numpy(dtype=float)
    at_floor = evidence_cache["at_or_below_floor"].to_numpy(dtype=bool)
    conc = evidence_cache["timing_concentration"].to_numpy(dtype=float)
    n_eval_years = evidence_cache["n_evaluable_years"].to_numpy(dtype=int)
    drift = evidence_cache["drift_status"].to_numpy(dtype=object)
    is_annual_truth = evidence_cache["truth_is_annual"].to_numpy(dtype=bool)
    family = evidence_cache["family"].to_numpy(dtype=object)
    n_years = evidence_cache["n_years"].to_numpy(dtype=int)
    b_mae = evidence_cache["boundary_mae"].to_numpy(dtype=float)

    unimodal_by_freq = {}
    for freq in MODE_FREQUENCY_GRID:
        pk = evidence_cache[f"peak_n_modes_{freq:.2f}"].to_numpy(dtype=int)
        tr = evidence_cache[f"trough_n_modes_{freq:.2f}"].to_numpy(dtype=int)
        unimodal_by_freq[freq] = (pk == 1) & (tr == 1)

    neg_mask = ~is_annual_truth
    n_neg = int(np.sum(neg_mask))
    pos_mask = np.isin(family, ["unimodal_symmetric", "monsoonal_sharp"])
    n_pos = int(np.sum(pos_mask))
    abs_mask = np.isin(family, ["bimodal", "switching_modes", "multi_year_regimes", "phase_drift"])
    n_abs = int(np.sum(abs_mask))
    pos_res_mae = float(np.mean(b_mae[pos_mask])) if np.any(pos_mask) else 0.0

    len_masks = {
        str(L): (neg_mask & (n_years == L), int(np.sum(neg_mask & (n_years == L))))
        for L in (5, 7, 10, 20, 30)
    }

    # Precalculate Wilson lookup
    wilson_lookup = np.array([wilson_interval(k, n_neg)[1] for k in range(n_neg + 1)]) if n_neg > 0 else np.ones(1)

    not_absent = (~at_floor) & (ratio > 0.0)
    sufficient_years = n_eval_years >= 5
    drifting = drift == "detected"

    all_points = list(iter_evidence_points())
    n_pts = len(all_points)
    chunk_size = 15000

    wilson_high_all = np.empty(n_pts, dtype=np.float32)
    k_neg_all = np.empty(n_pts, dtype=np.int32)
    recall_all = np.empty(n_pts, dtype=np.float32)
    abstention_all = np.empty(n_pts, dtype=np.float32)

    for i in range(0, n_pts, chunk_size):
        chunk = all_points[i : i + chunk_size]
        s_skill_c = np.array([pt[0] for pt in chunk], dtype=np.float32)
        p_alpha_c = np.array([pt[1] for pt in chunk], dtype=np.float32)
        anr_c = np.array([pt[2] for pt in chunk], dtype=np.float32)
        m_freq_c = np.array([pt[3] for pt in chunk], dtype=np.float32)
        s_conc_c = np.array([pt[4] for pt in chunk], dtype=np.float32)
        w_conc_c = np.array([pt[5] for pt in chunk], dtype=np.float32)

        sig_m = p_val[None, :] < p_alpha_c[:, None]
        skil_m = skill[None, :] >= s_skill_c[:, None]
        loud_m = ratio[None, :] >= anr_c[:, None]
        conc_m = conc[None, :] >= s_conc_c[:, None]
        w_conc_m = conc[None, :] >= w_conc_c[:, None]

        unimodal_m = np.empty((len(chunk), len(skill)), dtype=bool)
        for f_val in MODE_FREQUENCY_GRID:
            idx = np.where(np.isclose(m_freq_c, f_val))[0]
            if len(idx):
                unimodal_m[idx] = unimodal_by_freq[f_val]

        strong_ev = (
            sufficient_years[None, :]
            & not_absent[None, :]
            & sig_m
            & skil_m
            & loud_m
            & conc_m
            & unimodal_m
            & (~drifting[None, :])
        )
        moderate_ev = (
            sufficient_years[None, :]
            & not_absent[None, :]
            & sig_m
            & (skil_m | loud_m)
            & w_conc_m
            & (~strong_ev)
        )
        is_annual_pred = strong_ev | moderate_ev

        k_n = np.sum(is_annual_pred & neg_mask[None, :], axis=1)
        k_p = np.sum(is_annual_pred & pos_mask[None, :], axis=1)
        k_a = np.sum((~is_annual_pred) & abs_mask[None, :], axis=1)

        wilson_high_all[i : i + len(chunk)] = wilson_lookup[k_n]
        k_neg_all[i : i + len(chunk)] = k_n
        recall_all[i : i + len(chunk)] = k_p / n_pos if n_pos > 0 else 0.0
        abstention_all[i : i + len(chunk)] = k_a / n_abs if n_abs > 0 else 0.0

    # Stage 1 pruning: Wilson bound <= 0.05
    pass_stage1 = wilson_high_all <= 0.05
    if np.any(pass_stage1):
        candidate_indices = np.flatnonzero(pass_stage1)
    else:
        min_w = np.min(wilson_high_all)
        candidate_indices = np.flatnonzero(np.isclose(wilson_high_all, min_w))

    # Sort surviving candidates lexicographically
    def _cand_key(idx: int) -> tuple:
        pt = all_points[idx]
        return (
            wilson_high_all[idx],
            -recall_all[idx],
            -abstention_all[idx],
            -pt[0],  # -seasonal_cv_skill
            pt[1],   # periodicity_alpha
            -pt[2],  # -amplitude_noise_ratio
            -pt[4],  # -strong_timing_concentration
            -pt[7],  # -within_1_month_wilson_floor
        )

    candidate_indices = sorted(candidate_indices, key=_cand_key)

    # Build GridScores for candidate indices
    scores: list[GridScore] = []
    for idx in candidate_indices:
        pt = all_points[idx]
        k_n = int(k_neg_all[idx])
        w_high = float(wilson_high_all[idx])
        false_ann_rate = float(k_n / n_neg) if n_neg > 0 else 0.0
        rec = float(recall_all[idx])
        abs_corr = float(abstention_all[idx])

        # Stratified by length (computed for surviving points)
        ev_th = EvidenceThresholds(
            seasonal_cv_skill=pt[0],
            periodicity_alpha=pt[1],
            amplitude_noise_ratio=pt[2],
            mode_min_frequency=pt[3],
            mode_min_separation_months=2,
            strong_timing_concentration=pt[4],
            weak_timing_concentration=pt[5],
            min_timing_years=pt[6],
        )
        rec_th = RecoverabilityThresholds(
            min_years=5,
            min_coverage=0.80,
            min_within_1_month=0.80,
            within_1_month_wilson_floor=pt[7],
            max_p90_error_months=2.0,
            admit_insufficient_drift=pt[8],
        )

        # Vectorised single point prediction for length stratification
        sig_1 = p_val < pt[1]
        skil_1 = skill >= pt[0]
        loud_1 = ratio >= pt[2]
        conc_1 = conc >= pt[4]
        w_conc_1 = conc >= pt[5]
        unimodal_1 = unimodal_by_freq[pt[3]]
        strong_1 = sufficient_years & not_absent & sig_1 & skil_1 & loud_1 & conc_1 & unimodal_1 & (~drifting)
        moderate_1 = sufficient_years & not_absent & sig_1 & (skil_1 | loud_1) & w_conc_1 & (~strong_1)
        pred_1 = strong_1 | moderate_1

        by_len = {}
        for l_str, (l_mask, n_l) in len_masks.items():
            k_l = int(np.sum(pred_1 & l_mask))
            by_len[l_str] = float(k_l / n_l) if n_l > 0 else 0.0

        scores.append(
            GridScore(
                evidence=ev_th,
                recoverability=rec_th,
                false_annualisation_wilson_high=w_high,
                false_annualisation_rate=false_ann_rate,
                false_annualisation_by_length=by_len,
                routing_recall=rec,
                correct_abstention=abs_corr,
                boundary_mae=pos_res_mae,
            )
        )

    best = scores[0]
    return best.evidence, best.recoverability, scores


def _score_phase_with_norm_cache(
    phase_cache: tuple[PhaseCycleStatistics, ...],
    norm_list: list,
    point: PhaseThresholds,
) -> PhaseGridScore:
    phases = ("dry", "recovery", "wet", "recession")
    correct_counts = {p: 0 for p in phases}
    total_counts = {p: 0 for p in phases}
    transition_errors = []
    complete_count = 0
    total_cycles = len(phase_cache)

    if total_cycles == 0:
        return PhaseGridScore(
            thresholds=point,
            macro_accuracy=0.0,
            transition_mae=12.0,
            forced_complete_rate=0.0,
        )

    for idx, cycle in enumerate(phase_cache):
        normalised = norm_list[idx]
        if not normalised.sufficient:
            continue

        labels = label_cycle(
            normalised,
            low_fraction=point.phase_low_fraction,
            high_fraction=point.phase_high_fraction,
            min_duration_months=point.phase_min_duration_months,
        )

        pred = labels.to_numpy()
        true = cycle.true_phase.to_numpy()

        for p in phases:
            mask = true == p
            n_true = int(np.sum(mask))
            if n_true > 0:
                total_counts[p] += n_true
                correct_counts[p] += int(np.sum(mask & (pred == p)))

        # Transition MAE
        for p in phases:
            true_idx = np.where(true == p)[0]
            pred_idx = np.where(pred == p)[0]
            if len(true_idx) > 0 and len(pred_idx) > 0:
                transition_errors.append(abs(float(pred_idx[0] - true_idx[0])))

        # Check if all 4 phases are resolved
        if set(phases).issubset(set(pred)):
            complete_count += 1

    accuracies = [
        correct_counts[p] / total_counts[p] for p in phases if total_counts[p] > 0
    ]
    macro_acc = float(np.mean(accuracies)) if accuracies else 0.0
    t_mae = float(np.mean(transition_errors)) if transition_errors else 12.0
    forced_rate = float(complete_count / total_cycles) if total_cycles > 0 else 0.0

    return PhaseGridScore(
        thresholds=point,
        macro_accuracy=macro_acc,
        transition_mae=t_mae,
        forced_complete_rate=forced_rate,
    )


def score_phase_grid_point(
    phase_cache: tuple[PhaseCycleStatistics, ...], point: PhaseThresholds
) -> PhaseGridScore:
    """Score one phase threshold point over the phase cache."""
    norm_list = [
        normalise_cycle(
            cycle.cycle_frame,
            start_extent=cycle.start_extent_candidates[0],
            end_extent=cycle.end_extent_candidates[0],
            window=point.phase_smoothing_window,
            resolution_floor_pp=0.5,
        )
        for cycle in phase_cache
    ]
    return _score_phase_with_norm_cache(phase_cache, norm_list, point)


def select_phase_defaults(
    phase_cache: tuple[PhaseCycleStatistics, ...],
) -> tuple[PhaseThresholds, list[PhaseGridScore]]:
    """Select optimal phase thresholds through lexicographic sorting."""
    norm_cache = {
        win: [
            normalise_cycle(
                cycle.cycle_frame,
                start_extent=cycle.start_extent_candidates[0],
                end_extent=cycle.end_extent_candidates[0],
                window=win,
                resolution_floor_pp=0.5,
            )
            for cycle in phase_cache
        ]
        for win in (1, 3, 5)
    }

    scores = [
        _score_phase_with_norm_cache(phase_cache, norm_cache[pt.phase_smoothing_window], pt)
        for pt in iter_phase_points()
    ]
    scores.sort(
        key=lambda item: (
            -item.macro_accuracy,
            item.transition_mae,
            item.forced_complete_rate,
            item.thresholds.phase_smoothing_window,
            item.thresholds.phase_min_duration_months,
        )
    )
    best = scores[0]
    return best.thresholds, scores


def fingerprint() -> str:
    """Canonical SHA-256 fingerprint over generator, grid, objective, seed manifest, and dependency versions."""
    from . import _synthetic

    hasher = hashlib.sha256()

    # Generator source code
    import inspect

    hasher.update(inspect.getsource(_synthetic).encode("utf-8"))

    # Grid constants
    hasher.update(json.dumps(EVIDENCE_GRID, sort_keys=True).encode("utf-8"))
    hasher.update(json.dumps(PHASE_GRID, sort_keys=True).encode("utf-8"))

    # Seed manifest
    hasher.update(
        json.dumps(list(_synthetic.CALIBRATION_SEEDS)).encode("utf-8")
    )

    # Dependency versions
    deps = {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }
    hasher.update(json.dumps(deps, sort_keys=True).encode("utf-8"))

    return hasher.hexdigest()
