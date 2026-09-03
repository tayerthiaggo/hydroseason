"""Calibration search space, statistics caches, and lexicographic objective.

Pre-computes threshold-independent evidence and phase statistics once per record,
allowing the 190,080-point grid to be scored vectorially without re-running
harmonic regression or circular timing models.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from itertools import product
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import (
    RobustBoundaryConfig,
    robust_scale,
    select_window_minimum,
)
from ._circular_timing import (
    AnnualTimingSummary,
    equivalent_extremum_months,
    shortest_circular_span,
    summarise_annual_timing,
    timing_drift,
)
from ._harmonic import (
    _curve_extrema,
    _design,
    _year_matrices,
    amplitude_evidence,
    periodicity_p_value,
    select_harmonic_order,
)
from ._state_input import QualityPolicy, candidate_weights, prepare_monthly_extent
from ._synthetic import SyntheticRecord, generate_record, generate_timing_identifiability_record
from ._timing_identifiability import (
    TimingIdentifiabilityThresholds,
    assess_timing_identifiability,
)


@dataclass(frozen=True)
class EvidenceThresholds:
    seasonal_cv_skill: float = 0.8
    periodicity_alpha: float = 0.1
    amplitude_noise_ratio: float = 2.0
    mode_min_frequency: float = 0.5
    mode_min_separation_months: int = 2
    strong_timing_concentration: float = 0.8
    weak_timing_concentration: float = 0.5
    min_timing_years: int = 10


@dataclass(frozen=True)
class RecoverabilityThresholds:
    min_years: int = 5
    min_coverage: float = 0.8
    min_within_1_month: float = 0.8
    within_1_month_wilson_floor: float = 0.3
    max_p90_error_months: float = 2.0
    admit_insufficient_drift: bool = True


MODE_FREQUENCY_GRID = (0.50, 0.60, 0.70, 0.80)

AUTHORITY_SCOPE = {
    "evidence": "experimental_challenger",
    "recoverability": "experimental_challenger",
}


def wilson_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Score interval for binomial proportion."""
    if n <= 0:
        return (0.0, 1.0)
    z = 1.959963984540054
    p = float(k) / float(n)
    denom = 1.0 + (z**2) / float(n)
    centre = (p + (z**2) / (2.0 * float(n))) / denom
    spread = (z / denom) * np.sqrt((p * (1.0 - p) / float(n)) + (z**2) / (4.0 * (float(n) ** 2)))
    return (float(max(0.0, centre - spread)), float(min(1.0, centre + spread)))


def annual_extremum_month_sets(
    frame: pd.DataFrame,
    *,
    kind: Literal["min", "max"],
    tolerance_pct: float = 0.5,
    min_months_per_year: int = 9,
) -> dict[int, tuple[int, ...]]:
    """Equivalent extremum month sets grouped by year."""
    out: dict[int, tuple[int, ...]] = {}
    for year, group in frame.groupby(frame.index.year):
        usable = (
            group.loc[group["candidate_usable"], "extent_pct"]
            if "candidate_usable" in group.columns
            else group["extent_pct"]
        )
        if len(usable) >= min_months_per_year:
            months = equivalent_extremum_months(usable, kind=kind, tolerance=tolerance_pct)
            if months:
                out[int(year)] = months
    return out


@dataclass(frozen=True)
class _YearEvaluation:
    year: int
    evaluable: bool
    resolved: bool
    selected_month: int | None
    error_months: float | None


def evaluate_year(
    extent: pd.DataFrame,
    *,
    year: int,
    month_sets: Mapping[int, Sequence[int]],
    config: RobustBoundaryConfig,
    search_radius_months: int = 3,
    min_usable_months: int = 9,
) -> _YearEvaluation:
    """Leave-one-out cross-validation of boundary placement in one year."""
    train_sets = {k: v for k, v in month_sets.items() if k != year}
    if len(train_sets) < 2:
        return _YearEvaluation(year=year, evaluable=False, resolved=False, selected_month=None, error_months=None)
    summary = summarise_annual_timing(train_sets)
    if summary.dominant_month is None or summary.concentration is None:
        return _YearEvaluation(year=year, evaluable=False, resolved=False, selected_month=None, error_months=None)

    expected_month = int(summary.dominant_month)
    expected_stamp = pd.Timestamp(year=year, month=expected_month, day=1)
    expected_count = 2 * search_radius_months + 1
    window_start = expected_stamp - pd.DateOffset(months=search_radius_months)
    window_end = expected_stamp + pd.DateOffset(months=search_radius_months)
    window = extent.loc[(extent.index >= window_start) & (extent.index <= window_end)]

    usable_count = int(window["candidate_usable"].sum()) if "candidate_usable" in window.columns else len(window)
    if usable_count < config.min_usable_candidates:
        return _YearEvaluation(year=year, evaluable=False, resolved=False, selected_month=None, error_months=None)

    amplitude_pp, noise_pp = robust_scale(extent)
    selection = select_window_minimum(
        window,
        expected=expected_stamp,
        expected_count=expected_count,
        noise_pp=noise_pp,
        amplitude_pp=amplitude_pp,
        config=config,
    )
    if selection.selected_month is None:
        return _YearEvaluation(year=year, evaluable=True, resolved=False, selected_month=None, error_months=None)

    obs_months = month_sets.get(year, ())
    if not obs_months:
        return _YearEvaluation(year=year, evaluable=True, resolved=False, selected_month=None, error_months=None)

    det_month = int(selection.selected_month.month)
    min_err = min(
        min(abs(det_month - m), 12 - abs(det_month - m))
        for m in obs_months
    )
    return _YearEvaluation(year=year, evaluable=True, resolved=True, selected_month=det_month, error_months=float(min_err))


def annual_cycle_evidence(
    *,
    seasonal_cv_skill: float,
    periodicity_p: float,
    amplitude_noise_ratio: float,
    peak_n_modes: int,
    trough_n_modes: int,
    n_evaluable_years: int,
    at_or_below_floor: bool,
    timing: AnnualTimingSummary,
    drift_status: str,
    thresholds: EvidenceThresholds,
) -> str:
    """Classify annual cycle evidence state."""
    if n_evaluable_years < thresholds.min_timing_years:
        return "insufficient"
    if at_or_below_floor:
        return "unsupported"
    if (
        seasonal_cv_skill >= thresholds.seasonal_cv_skill
        and periodicity_p <= thresholds.periodicity_alpha
        and amplitude_noise_ratio >= thresholds.amplitude_noise_ratio
        and peak_n_modes <= 1
        and trough_n_modes <= 1
    ):
        if (
            timing.concentration is not None
            and timing.concentration >= thresholds.strong_timing_concentration
        ):
            return "strong"
        if (
            timing.concentration is not None
            and timing.concentration >= thresholds.weak_timing_concentration
        ):
            return "weak"
    return "unsupported"


@dataclass(frozen=True)
class _RecoverabilityResult:
    state: str
    reason: str
    within_1_month_wilson_low: float


def _classify_boundary_recoverability(
    *,
    n: int,
    resolved_count: int,
    within_1_count: int,
    p90_error_months: float,
    evidence: str,
    thresholds: RecoverabilityThresholds,
    drift_status: str,
    n_trough_modes: int,
) -> _RecoverabilityResult:
    """Classify boundary recoverability."""
    if n < thresholds.min_years:
        return _RecoverabilityResult("insufficient", f"fewer than {thresholds.min_years} evaluable years", 0.0)
    low, _ = wilson_interval(within_1_count, n) if n else (0.0, 1.0)
    coverage = resolved_count / n if n else 0.0
    within_rate = within_1_count / n if n else 0.0
    if (
        evidence in {"strong", "weak"}
        and coverage >= thresholds.min_coverage
        and within_rate >= thresholds.min_within_1_month
        and low >= thresholds.within_1_month_wilson_floor
        and p90_error_months <= thresholds.max_p90_error_months
        and n_trough_modes <= 1
    ):
        if not thresholds.admit_insufficient_drift and drift_status == "insufficient_for_drift":
            return _RecoverabilityResult("provisional", "insufficient record for drift check", low)
        return _RecoverabilityResult("supported", "boundary timing is cross-validated", low)
    return _RecoverabilityResult("unsupported", "recoverability criteria not met", low)

METRIC_GROUPS = {
    "challenger_decision": ["evidence", "recoverability"],
}

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
    boundary_within_1_count: int
    boundary_p90_error_months: float
    boundary_truth_errors: tuple[float, ...]
    truth_is_annual: bool
    truth_trough_month: int | None
    missingness: str
    quality_loss: str
    noise_pp: float
    timing_jitter_months: int
    bias_strength_pp: float




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
    selection_counts: dict[str, int] | None = None




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


def compute_statistics(
    record: SyntheticRecord, *, quality_policy: QualityPolicy = "flag"
) -> RecordStatistics:
    """Compute threshold-independent evidence and boundary statistics for one record."""
    prepared = prepare_monthly_extent(record.frame, quality_policy=quality_policy)
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

    month_sets = annual_extremum_month_sets(
        prepared, kind="min", tolerance_pct=0.5
    )

    timing_summary = summarise_annual_timing(month_sets, random_state=record.seed)
    timing_concentration = (
        float(timing_summary.concentration) if timing_summary.concentration is not None else 0.0
    )
    timing_uniformity_p = (
        float(timing_summary.uniformity_p) if timing_summary.uniformity_p is not None else 1.0
    )

    drift = timing_drift(month_sets, min_timing_years=10, random_state=record.seed)
    drift_status = str(drift.status)

    boundary_config = RobustBoundaryConfig()
    evaluations = [
        evaluate_year(
            prepared,
            year=int(y),
            month_sets=month_sets,
            config=boundary_config,
            search_radius_months=3,
            min_usable_months=9,
        )
        for y in sorted(month_sets)
    ]
    evaluable = [item for item in evaluations if item.evaluable]
    resolved = [item for item in evaluable if item.resolved and item.error_months is not None]
    boundary_errors = tuple(float(item.error_months) for item in resolved)
    boundary_n = len(evaluable)
    boundary_coverage = float(len(resolved) / boundary_n) if boundary_n > 0 else 0.0
    boundary_within_1_count = sum(error <= 1.0 for error in boundary_errors)
    boundary_p90_error_months = (
        float(np.percentile(boundary_errors, 90)) if boundary_errors else 12.0
    )
    truth_by_year = dict(
        zip(
            sorted(set(prepared.index.year)),
            record.truth.trough_month_by_year,
            strict=True,
        )
    )
    boundary_truth_errors = tuple(
        float(((int(item.selected_month) - int(truth_by_year[item.year]) + 6) % 12) - 6)
        for item in resolved
        if record.truth.is_annual
        and item.selected_month is not None
        and item.year in truth_by_year
    )
    n_evaluable_years = int(np.count_nonzero(weight_matrix.sum(axis=1) > 0.0))

    return RecordStatistics(
        seed=record.seed,
        family=record.family,
        n_years=record.truth.n_years,
        n_evaluable_years=n_evaluable_years,
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
        boundary_within_1_count=boundary_within_1_count,
        boundary_p90_error_months=boundary_p90_error_months,
        boundary_truth_errors=boundary_truth_errors,
        truth_is_annual=record.truth.is_annual,
        truth_trough_month=record.truth.trough_month,
        missingness=record.scenario.missingness,
        quality_loss=record.scenario.quality_loss,
        noise_pp=record.scenario.noise_pp,
        timing_jitter_months=record.scenario.timing_jitter_months,
        bias_strength_pp=record.scenario.bias_strength_pp,
    )




_RECORD_STATS_CACHE: dict[tuple[int, str, str], RecordStatistics] = {}


def _worker_evidence(args: tuple[int, str] | tuple[int, str, QualityPolicy]) -> dict:
    seed, partition, *policy_arg = args
    quality_policy: QualityPolicy = policy_arg[0] if policy_arg else "flag"
    record = generate_record(seed, partition=partition)
    stats = compute_statistics(record, quality_policy=quality_policy)
    mean_b_error = float(np.mean(stats.boundary_errors)) if stats.boundary_errors else 0.0
    truth_errors = np.asarray(stats.boundary_truth_errors, dtype=float)
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
        "boundary_within_1_count": stats.boundary_within_1_count,
        "boundary_p90_error_months": stats.boundary_p90_error_months,
        "boundary_truth_n": int(len(truth_errors)),
        "boundary_truth_within_1_count": int(np.count_nonzero(np.abs(truth_errors) <= 1.0)),
        "boundary_truth_bias_months": float(np.mean(truth_errors)) if len(truth_errors) else 0.0,
        "boundary_truth_mae_months": float(np.mean(np.abs(truth_errors))) if len(truth_errors) else 0.0,
        "boundary_truth_p90_error_months": float(np.percentile(np.abs(truth_errors), 90)) if len(truth_errors) else 12.0,
        "boundary_truth_errors": stats.boundary_truth_errors,
        "boundary_mae": mean_b_error,
        "truth_is_annual": stats.truth_is_annual,
        "truth_trough_month": stats.truth_trough_month if stats.truth_trough_month is not None else -1,
        "missingness": stats.missingness,
        "quality_loss": stats.quality_loss,
        "noise_pp": stats.noise_pp,
        "timing_jitter_months": stats.timing_jitter_months,
        "bias_strength_pp": stats.bias_strength_pp,
    }
    for freq in MODE_FREQUENCY_GRID:
        row[f"peak_n_modes_{freq:.2f}"] = stats.peak_n_modes_by_frequency[freq]
        row[f"trough_n_modes_{freq:.2f}"] = stats.trough_n_modes_by_frequency[freq]
    return row




def build_evidence_cache(
    seeds: Iterable[int],
    *,
    partition: Literal["calibration", "validation"],
    quality_policy: QualityPolicy = "flag",
) -> pd.DataFrame:
    """Build threshold-independent evidence dataframe over a set of record seeds."""
    rows = []
    for seed in seeds:
        key = (int(seed), str(partition), str(quality_policy))
        if key not in _RECORD_STATS_CACHE:
            record = generate_record(seed, partition=partition)
            _RECORD_STATS_CACHE[key] = compute_statistics(
                record, quality_policy=quality_policy
            )
        stats = _RECORD_STATS_CACHE[key]
        mean_b_error = float(np.mean(stats.boundary_errors)) if stats.boundary_errors else 0.0
        truth_errors = np.asarray(stats.boundary_truth_errors, dtype=float)
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
            "boundary_within_1_count": stats.boundary_within_1_count,
            "boundary_p90_error_months": stats.boundary_p90_error_months,
            "boundary_truth_n": int(len(truth_errors)),
            "boundary_truth_within_1_count": int(np.count_nonzero(np.abs(truth_errors) <= 1.0)),
            "boundary_truth_bias_months": float(np.mean(truth_errors)) if len(truth_errors) else 0.0,
            "boundary_truth_mae_months": float(np.mean(np.abs(truth_errors))) if len(truth_errors) else 0.0,
            "boundary_truth_p90_error_months": float(np.percentile(np.abs(truth_errors), 90)) if len(truth_errors) else 12.0,
            "boundary_truth_errors": stats.boundary_truth_errors,
            "boundary_mae": mean_b_error,
            "truth_is_annual": stats.truth_is_annual,
            "truth_trough_month": stats.truth_trough_month if stats.truth_trough_month is not None else -1,
            "missingness": stats.missingness,
            "quality_loss": stats.quality_loss,
            "noise_pp": stats.noise_pp,
            "timing_jitter_months": stats.timing_jitter_months,
            "bias_strength_pp": stats.bias_strength_pp,
        }
        for freq in MODE_FREQUENCY_GRID:
            row[f"peak_n_modes_{freq:.2f}"] = stats.peak_n_modes_by_frequency[freq]
            row[f"trough_n_modes_{freq:.2f}"] = stats.trough_n_modes_by_frequency[freq]
        rows.append(row)

    return pd.DataFrame(rows)




def evaluate_evidence_cache(
    evidence_cache: pd.DataFrame,
    *,
    evidence_thresholds: EvidenceThresholds,
    recoverability_thresholds: RecoverabilityThresholds,
) -> pd.DataFrame:
    """Apply runtime evidence and recoverability rules to cached statistics."""
    rows: list[dict[str, object]] = []
    frequency = evidence_thresholds.mode_min_frequency
    for _, cached in evidence_cache.iterrows():
        timing_n = int(cached.get("timing_n_years", cached["n_evaluable_years"]))
        timing = AnnualTimingSummary(
            concentration=float(cached["timing_concentration"]),
            ci_low=None,
            ci_high=None,
            iqr_months=None,
            uniformity_p=float(cached.get("timing_uniformity_p", 1.0)),
            n_years=timing_n,
            dominant_month=None,
        )
        peak_modes = int(cached[f"peak_n_modes_{frequency:.2f}"])
        trough_modes = int(cached[f"trough_n_modes_{frequency:.2f}"])
        evidence = annual_cycle_evidence(
            seasonal_cv_skill=float(cached["seasonal_cv_skill"]),
            periodicity_p=float(cached["periodicity_p"]),
            amplitude_noise_ratio=float(cached["amplitude_noise_ratio"]),
            peak_n_modes=peak_modes,
            trough_n_modes=trough_modes,
            n_evaluable_years=int(cached["n_evaluable_years"]),
            at_or_below_floor=bool(cached["at_or_below_floor"]),
            timing=timing,
            drift_status=str(cached["drift_status"]),
            thresholds=evidence_thresholds,
        )
        boundary_n = int(cached["boundary_n"])
        resolved_count = int(
            cached.get(
                "boundary_resolved_count",
                round(float(cached["boundary_coverage"]) * boundary_n),
            )
        )
        recoverability = _classify_boundary_recoverability(
            n=boundary_n,
            resolved_count=resolved_count,
            within_1_count=int(cached["boundary_within_1_count"]),
            p90_error_months=float(cached["boundary_p90_error_months"]),
            evidence=evidence,
            thresholds=recoverability_thresholds,
            drift_status=str(cached["drift_status"]),
            n_trough_modes=trough_modes,
        )
        row = cached.to_dict()
        row.update(
            annual_cycle_evidence=evidence,
            boundary_recoverability=recoverability.state,
            boundary_recoverability_reason=recoverability.reason,
            boundary_cv_within_1_month_wilson_low=(
                recoverability.within_1_month_wilson_low
            ),
            publish_annual_rows=recoverability.state == "supported",
        )
        rows.append(row)
    return pd.DataFrame(rows, index=evidence_cache.index)


def _rate_interval(successes: int, trials: int) -> dict[str, float | int]:
    low, high = wilson_interval(successes, trials) if trials else (0.0, 1.0)
    return {
        "successes": int(successes),
        "trials": int(trials),
        "rate": float(successes / trials) if trials else 0.0,
        "wilson_low": float(low),
        "wilson_high": float(high),
    }




def _group_route_metrics(
    evaluated: pd.DataFrame, columns: tuple[str, ...]
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, dict[str, float | int]] = {}
    grouper: str | list[str] = columns[0] if len(columns) == 1 else list(columns)
    for key, group in evaluated.groupby(grouper, dropna=False, sort=True):
        key_tuple = key if isinstance(key, tuple) else (key,)
        label = "|".join(
            f"{column}={value}" for column, value in zip(columns, key_tuple, strict=True)
        )
        publish = group["publish_annual_rows"].to_numpy(dtype=bool)
        grouped[label] = {
            "n": int(len(group)),
            "per_year_detection": float(np.mean(publish)) if len(group) else 0.0,
            "event_characterisation": float(np.mean(~publish)) if len(group) else 0.0,
        }
    return grouped




def _sensitivity_metrics(
    evaluated: pd.DataFrame, column: str
) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for value, group in evaluated.groupby(column, dropna=False, sort=True):
        truth = group["truth_is_annual"].to_numpy(dtype=bool)
        publish = group["publish_annual_rows"].to_numpy(dtype=bool)
        negative = ~truth
        result[str(value)] = {
            "n": int(len(group)),
            "false_annualisation_rate": (
                float(np.mean(publish[negative])) if np.any(negative) else 0.0
            ),
            "routing_recall": (
                float(np.mean(publish[truth])) if np.any(truth) else 0.0
            ),
        }
    return result


def build_validation_report(
    evidence_cache: pd.DataFrame,
    *,
    seeds: list[int],
    calibration_version: str,
    calibration_fingerprint: str,
    evidence_thresholds: EvidenceThresholds,
    recoverability_thresholds: RecoverabilityThresholds,
    runtime_metrics: dict[str, object],
    quality_policy_sensitivity: dict[str, object],
) -> dict[str, object]:
    """Build validation payload exclusively from measured cache outputs."""
    evaluated = evaluate_evidence_cache(
        evidence_cache,
        evidence_thresholds=evidence_thresholds,
        recoverability_thresholds=recoverability_thresholds,
    )
    truth = evaluated["truth_is_annual"].to_numpy(dtype=bool)
    evidence_present = ~evaluated["annual_cycle_evidence"].isin(
        ["absent", "insufficient"]
    ).to_numpy()
    publish = evaluated["publish_annual_rows"].to_numpy(dtype=bool)

    confusion = {
        "true_annual_pred_annual": int(np.count_nonzero(truth & evidence_present)),
        "true_annual_pred_non_annual": int(
            np.count_nonzero(truth & ~evidence_present)
        ),
        "true_non_annual_pred_annual": int(
            np.count_nonzero(~truth & evidence_present)
        ),
        "true_non_annual_pred_non_annual": int(
            np.count_nonzero(~truth & ~evidence_present)
        ),
    }

    negative = ~truth
    false_annualisation = _rate_interval(
        int(np.count_nonzero(negative & publish)), int(np.count_nonzero(negative))
    )
    abstention_families = {
        "bimodal",
        "switching_modes",
        "multi_year_regimes",
        "phase_drift",
    }
    abstention_mask = evaluated["family"].isin(abstention_families).to_numpy()
    correct_abstention = _rate_interval(
        int(np.count_nonzero(abstention_mask & ~publish)),
        int(np.count_nonzero(abstention_mask)),
    )

    false_by_length: dict[str, float] = {}
    for length in (5, 7, 10, 20, 30):
        mask = negative & (evaluated["n_years"].to_numpy(dtype=int) == length)
        false_by_length[str(length)] = (
            float(np.mean(publish[mask])) if np.any(mask) else 0.0
        )

    truth_errors = np.asarray(
        [
            error
            for errors in evaluated.loc[truth, "boundary_truth_errors"]
            for error in errors
        ],
        dtype=float,
    )
    truth_within = int(np.count_nonzero(np.abs(truth_errors) <= 1.0))
    truth_wilson_low = (
        wilson_interval(truth_within, len(truth_errors))[0]
        if len(truth_errors)
        else 0.0
    )
    boundary_metrics = {
        "n": int(len(truth_errors)),
        "coverage": float(
            evaluated.loc[truth, "boundary_truth_n"].sum()
            / max(1, evaluated.loc[truth, "boundary_n"].sum())
        ),
        "within_1_month": (
            float(truth_within / len(truth_errors)) if len(truth_errors) else 0.0
        ),
        "within_1_month_wilson_low": float(truth_wilson_low),
        "bias": float(np.mean(truth_errors)) if len(truth_errors) else 0.0,
        "mae": float(np.mean(np.abs(truth_errors))) if len(truth_errors) else 0.0,
        "p90": (
            float(np.percentile(np.abs(truth_errors), 90))
            if len(truth_errors)
            else 12.0
        ),
    }

    drift_axis: dict[str, float] = {}
    for label, admit in (("reject", False), ("admit", True)):
        drift_evaluated = evaluate_evidence_cache(
            evidence_cache,
            evidence_thresholds=evidence_thresholds,
            recoverability_thresholds=replace(
                recoverability_thresholds, admit_insufficient_drift=admit
            ),
        )
        drift_publish = drift_evaluated["publish_annual_rows"].to_numpy(dtype=bool)
        drift_axis[label] = (
            float(np.mean(drift_publish[negative])) if np.any(negative) else 0.0
        )

    sensitivity = {
        "missingness": _sensitivity_metrics(evaluated, "missingness"),
        "noise": _sensitivity_metrics(evaluated, "noise_pp"),
        "drift": _sensitivity_metrics(evaluated, "drift_status"),
        "multimodality": _sensitivity_metrics(
            evaluated.assign(
                multimodality=np.where(
                    evaluated["family"].isin(["bimodal", "switching_modes"]),
                    "multimodal",
                    "other",
                )
            ),
            "multimodality",
        ),
        "quality_loss": _sensitivity_metrics(evaluated, "quality_loss"),
        "extent_dependent_bias": _sensitivity_metrics(
            evaluated, "bias_strength_pp"
        ),
        "quality_policy": quality_policy_sensitivity,
    }

    recoverability_sensitivity: dict[str, dict[str, float]] = {}
    axes = {
        "min_years": (3, 5, 7),
        "min_coverage": (0.6, 0.8, 0.9),
        "min_within_1_month": (0.6, 0.8, 0.9),
        "max_p90_error_months": (1.5, 2.0, 3.0),
    }
    for field_name, values in axes.items():
        axis_results: dict[str, float] = {}
        for value in values:
            candidate = replace(recoverability_thresholds, **{field_name: value})
            axis_evaluated = evaluate_evidence_cache(
                evidence_cache,
                evidence_thresholds=evidence_thresholds,
                recoverability_thresholds=candidate,
            )
            axis_publish = axis_evaluated["publish_annual_rows"].to_numpy(dtype=bool)
            axis_results[str(value)] = (
                float(np.mean(axis_publish[truth])) if np.any(truth) else 0.0
            )
        recoverability_sensitivity[field_name] = axis_results

    scenario_columns = (
        "family",
        "missingness",
        "quality_loss",
        "noise_pp",
        "timing_jitter_months",
        "bias_strength_pp",
    )
    return {
        "calibration_version": calibration_version,
        "fingerprint": calibration_fingerprint,
        "authority_scope": AUTHORITY_SCOPE,
        "metric_groups": METRIC_GROUPS,
        "partition": "validation",
        "seeds": [int(seed) for seed in seeds],
        "evidence_confusion_matrix": confusion,
        "false_annualisation": false_annualisation,
        "correct_abstention": correct_abstention,
        "false_annualisation_by_length": false_by_length,
        "route_coverage": {
            "by_scenario": _group_route_metrics(evaluated, scenario_columns),
            "by_record_length": _group_route_metrics(evaluated, ("n_years",)),
        },
        "boundary_metrics": boundary_metrics,
        "drift_axis": drift_axis,
        "sensitivity": sensitivity,
        "recoverability_sensitivity": recoverability_sensitivity,
        "periodicity_null": {
            "selected_alpha": float(evidence_thresholds.periodicity_alpha),
            "bias_note": (
                "The rotation null is anti-conservative because calendar rotation "
                "splices December to a non-adjacent month and introduces a discontinuity."
            ),
        },
        "runtime": runtime_metrics,
    }


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

    evaluated = evaluate_evidence_cache(
        evidence_cache,
        evidence_thresholds=ev_thresholds,
        recoverability_thresholds=rec_thresholds,
    )
    is_annual_truth = evaluated["truth_is_annual"].to_numpy(dtype=bool)
    family = evaluated["family"].to_numpy(dtype=object)
    n_years = evaluated["n_years"].to_numpy(dtype=int)
    is_annual_pred = evaluated["publish_annual_rows"].to_numpy(dtype=bool)
    b_mae = evaluated["boundary_mae"].to_numpy(dtype=float)

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

    # Boundary timing error among positive controls the point actually routes.
    routed_pos = pos_mask & is_annual_pred
    pos_res_mae = float(np.mean(b_mae[routed_pos])) if np.any(routed_pos) else 12.0

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


# Values below MIN_TIMING_YEARS_OVERRIDE are candidates for the shipped
# override; the search's own answer is never one of them, so this constant
# alone can never silently reproduce what the search already picked.
MIN_TIMING_YEARS_OVERRIDE = 5


def _apply_min_timing_years_override(
    searched: EvidenceThresholds, evidence_cache: pd.DataFrame
) -> tuple[EvidenceThresholds, dict[str, object] | None]:
    """Ship a deliberately relaxed `min_timing_years`, recording why.

    The 190,080-point search reproducibly selects `min_timing_years=10`:
    `correct_abstention` (which favours a higher floor) is pruned before
    `min_timing_years` is ever consulted as a tie-break, so a higher floor
    keeps winning on the search's own stated priority order. But this floor
    trades directly against `routing_recall`, which favours a *lower* floor,
    and a per-record-length breakdown shows the floor is a hard cliff at
    its own value with no effect above it -- raising it from 5 to 10 buys
    zero coverage on 7-30 year records and removes all coverage on 5-6 and
    7-9 year records. False annualisation (negative-control Wilson high) is
    identical -- 0.0 -- at 5, 7, and 10: the one metric this constant could
    plausibly protect is not moved by it at any tested value.

    `_MIN_USABLE_YEARS = 5` in `hydroseason/_regime.py` is the released
    floor for exactly the same question (is there enough annual timing to
    assess a record at all). A challenger floor of 10 makes the
    experimental second opinion refuse records the released path already
    analyses -- stricter than the tool it exists to check, for a benefit
    that measurably does not exist above the floor it would remove.

    This function does not change the search or its objective -- both are
    left free to report their own answer, which the report still records
    under `evidence_searched`. It only overrides the one field the search
    has no way to weigh against the released floor it is not shown.
    """
    if searched.min_timing_years == MIN_TIMING_YEARS_OVERRIDE:
        return searched, None

    def _false_ann_high(min_y: int) -> float:
        point = (
            searched.seasonal_cv_skill, searched.periodicity_alpha,
            searched.amplitude_noise_ratio, searched.mode_min_frequency,
            searched.strong_timing_concentration, searched.weak_timing_concentration,
            min_y, RecoverabilityThresholds().within_1_month_wilson_floor, True,
        )
        return score_evidence_grid_point(evidence_cache, point).false_annualisation_wilson_high

    shipped = replace(searched, min_timing_years=MIN_TIMING_YEARS_OVERRIDE)
    note = {
        "searched_value": searched.min_timing_years,
        "shipped_value": MIN_TIMING_YEARS_OVERRIDE,
        "false_annualisation_wilson_high_at_searched": _false_ann_high(searched.min_timing_years),
        "false_annualisation_wilson_high_at_shipped": _false_ann_high(MIN_TIMING_YEARS_OVERRIDE),
        "reason": (
            f"Search selected min_timing_years={searched.min_timing_years}; shipping "
            f"{MIN_TIMING_YEARS_OVERRIDE} to match the released _MIN_USABLE_YEARS floor "
            "(hydroseason/_regime.py). False annualisation is unaffected at every tested "
            "value; the floor only removes challenger coverage on records shorter than "
            "itself, with no measurable benefit to records above it."
        ),
    }
    return shipped, note


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
    b_mae = evidence_cache["boundary_mae"].to_numpy(dtype=float)
    boundary_n = evidence_cache["boundary_n"].to_numpy(dtype=int)
    boundary_coverage = evidence_cache["boundary_coverage"].to_numpy(dtype=float)
    boundary_within_count = evidence_cache["boundary_within_1_count"].to_numpy(
        dtype=int
    )
    boundary_p90 = evidence_cache["boundary_p90_error_months"].to_numpy(
        dtype=float
    )
    boundary_within_rate = np.divide(
        boundary_within_count,
        boundary_n,
        out=np.zeros_like(boundary_coverage),
        where=boundary_n > 0,
    )
    boundary_wilson_low = np.asarray(
        [
            wilson_interval(int(successes), int(trials))[0]
            if trials > 0
            else 0.0
            for successes, trials in zip(
                boundary_within_count, boundary_n, strict=True
            )
        ],
        dtype=float,
    )

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
    # Precalculate Wilson lookup
    wilson_lookup = np.array([wilson_interval(k, n_neg)[1] for k in range(n_neg + 1)]) if n_neg > 0 else np.ones(1)

    not_absent = (~at_floor) & (ratio > 0.0)
    sufficient_years = n_eval_years >= 5
    drifting = drift == "detected"
    drift_insufficient = drift == "insufficient_for_drift"
    boundary_base = (
        (boundary_n >= 5)
        & (boundary_coverage >= 0.80)
        & (boundary_within_rate >= 0.80)
        & (boundary_p90 <= 2.0)
    )

    all_points = list(iter_evidence_points())
    n_pts = len(all_points)
    chunk_size = 2000

    wilson_high_all = np.empty(n_pts, dtype=np.float32)
    k_neg_all = np.empty(n_pts, dtype=np.int32)
    recall_all = np.empty(n_pts, dtype=np.float32)
    abstention_all = np.empty(n_pts, dtype=np.float32)
    boundary_mae_all = np.empty(n_pts, dtype=np.float32)

    for i in range(0, n_pts, chunk_size):
        chunk = all_points[i : i + chunk_size]
        s_skill_c = np.array([pt[0] for pt in chunk], dtype=np.float32)
        p_alpha_c = np.array([pt[1] for pt in chunk], dtype=np.float32)
        anr_c = np.array([pt[2] for pt in chunk], dtype=np.float32)
        m_freq_c = np.array([pt[3] for pt in chunk], dtype=np.float32)
        s_conc_c = np.array([pt[4] for pt in chunk], dtype=np.float32)
        w_conc_c = np.array([pt[5] for pt in chunk], dtype=np.float32)
        min_years_c = np.array([pt[6] for pt in chunk], dtype=np.int16)
        wilson_floor_c = np.array([pt[7] for pt in chunk], dtype=np.float32)
        admit_drift_c = np.array([pt[8] for pt in chunk], dtype=bool)

        sig_m = p_val[None, :] <= (p_alpha_c[:, None] + 1e-6)
        skil_m = skill[None, :] >= s_skill_c[:, None]
        loud_m = ratio[None, :] >= anr_c[:, None]
        timing_adequate_m = n_eval_years[None, :] >= min_years_c[:, None]
        conc_m = timing_adequate_m & (conc[None, :] >= s_conc_c[:, None])
        w_conc_m = timing_adequate_m & (conc[None, :] >= w_conc_c[:, None])

        unimodal_m = np.empty((len(chunk), len(skill)), dtype=bool)
        trough_unimodal_m = np.empty((len(chunk), len(skill)), dtype=bool)
        for f_val in MODE_FREQUENCY_GRID:
            idx = np.where(np.isclose(m_freq_c, f_val))[0]
            if len(idx):
                unimodal_m[idx] = unimodal_by_freq[f_val]
                trough_unimodal_m[idx] = evidence_cache[
                    f"trough_n_modes_{f_val:.2f}"
                ].to_numpy(dtype=int) == 1

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
        weak_ev = (
            sufficient_years[None, :]
            & not_absent[None, :]
            & (sig_m | skil_m)
        )
        evidence_present = strong_ev | moderate_ev | weak_ev
        drift_supported_m = (~drifting[None, :]) & (
            (~drift_insufficient[None, :]) | admit_drift_c[:, None]
        )
        is_annual_pred = (
            evidence_present
            & boundary_base[None, :]
            & (boundary_wilson_low[None, :] >= wilson_floor_c[:, None])
            & trough_unimodal_m
            & drift_supported_m
        )

        k_n = np.sum(is_annual_pred & neg_mask[None, :], axis=1)
        k_p = np.sum(is_annual_pred & pos_mask[None, :], axis=1)
        k_a = np.sum((~is_annual_pred) & abs_mask[None, :], axis=1)
        routed_pos = is_annual_pred & pos_mask[None, :]
        routed_pos_n = np.sum(routed_pos, axis=1)
        routed_pos_error = np.sum(routed_pos * b_mae[None, :], axis=1)
        routed_mae = np.divide(
            routed_pos_error,
            routed_pos_n,
            out=np.full(len(chunk), 12.0, dtype=float),
            where=routed_pos_n > 0,
        )

        wilson_high_all[i : i + len(chunk)] = wilson_lookup[k_n]
        k_neg_all[i : i + len(chunk)] = k_n
        recall_all[i : i + len(chunk)] = k_p / n_pos if n_pos > 0 else 0.0
        abstention_all[i : i + len(chunk)] = k_a / n_abs if n_abs > 0 else 0.0
        boundary_mae_all[i : i + len(chunk)] = routed_mae

    # Stage 1 pruning: Wilson bound <= 0.05
    pass_stage1 = wilson_high_all <= 0.05
    if np.any(pass_stage1):
        candidate_indices = np.flatnonzero(pass_stage1)
    else:
        min_w = np.min(wilson_high_all)
        candidate_indices = np.flatnonzero(np.isclose(wilson_high_all, min_w))

    selection_counts = {
        "grid": n_pts,
        "negative_control_wilson": int(len(candidate_indices)),
    }
    survivors = np.asarray(candidate_indices, dtype=int)

    def _retain_metric(
        name: str, values: np.ndarray, *, maximise: bool
    ) -> None:
        nonlocal survivors
        best_value = (
            np.max(values[survivors]) if maximise else np.min(values[survivors])
        )
        survivors = survivors[np.isclose(values[survivors], best_value)]
        selection_counts[name] = int(len(survivors))

    def _retain_axis(name: str, position: int, *, maximise: bool) -> None:
        nonlocal survivors
        values = [all_points[index][position] for index in survivors]
        best_value = max(values) if maximise else min(values)
        survivors = np.asarray(
            [
                index
                for index in survivors
                if all_points[index][position] == best_value
            ],
            dtype=int,
        )
        selection_counts[name] = int(len(survivors))

    _retain_metric("routing_recall", recall_all, maximise=True)
    _retain_metric("correct_abstention", abstention_all, maximise=True)
    _retain_metric("boundary_mae", boundary_mae_all, maximise=False)
    for name, position, maximise in (
        ("seasonal_cv_skill_margin", 0, True),
        ("periodicity_alpha_margin", 1, False),
        ("amplitude_noise_ratio_margin", 2, True),
        ("strong_timing_concentration_margin", 4, True),
        ("wilson_floor_margin", 7, True),
        ("min_timing_years_margin", 6, True),
        ("reject_insufficient_drift_margin", 8, False),
        ("mode_frequency_margin", 3, True),
        ("weak_timing_concentration_margin", 5, True),
    ):
        _retain_axis(name, position, maximise=maximise)

    # Break any tie the staged pruning left standing, deterministically.
    #
    # The pick must come from `survivors`, not `candidate_indices`: the latter
    # is still the whole stage-1 set, so sorting it here would discard every
    # pruning stage above -- the same stages `selection_counts` reports as
    # `selection_survivors`. The two are not interchangeable. `_retain_metric`
    # keeps points within `np.isclose` of the stage optimum, so a point whose
    # recall is worse only by float noise stays eligible and can win on the
    # next metric; sorting the unpruned set applies exact ordering instead and
    # lets that noise decide the whole selection.
    def _cand_key(idx: int) -> tuple:
        pt = all_points[idx]
        return (
            -recall_all[idx],
            -abstention_all[idx],
            boundary_mae_all[idx],
            -pt[0],  # -seasonal_cv_skill
            pt[1],   # periodicity_alpha
            -pt[2],  # -amplitude_noise_ratio
            -pt[4],  # -strong_timing_concentration
            -pt[7],  # -within_1_month_wilson_floor
            -pt[6],  # more timing years is the larger-margin choice
            pt[8],   # rejecting unmeasurable drift is simpler/conservative
            -pt[3],
            -pt[5],
        )

    ordered = sorted(survivors.tolist(), key=_cand_key)
    selection_counts["final_survivors"] = int(len(ordered))
    selection_counts["selected"] = 1

    best = replace(
        score_evidence_grid_point(evidence_cache, all_points[ordered[0]]),
        selection_counts=selection_counts,
    )
    return best.evidence, best.recoverability, [best]


# The timing-identifiability calibration is intentionally independent from the
# established evidence/recoverability challenger calibration above.  In
# particular, its cache contains only annual timing metrics and synthetic truth.
TIMING_IDENTIFIABILITY_GRID = {
    "min_amplitude_to_floor_ratio": [1.0, 1.5, 2.0, 3.0],
    "min_peak_water_pixels": [1, 2, 3, 5],
    "max_point_span_months": [0, 1, 2],
    "max_boundary_interval_months": [2, 3, 4],
    "min_informative_years": [5, 7, 10],
}
TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE = "candidate_for_established_0_2_0"


@dataclass(frozen=True)
class TimingIdentifiabilityScore:
    thresholds: TimingIdentifiabilityThresholds
    false_precise_boundary_rate: float
    false_precise_boundary_wilson: tuple[float, float]
    false_precise_boundary_n: int
    correct_abstention: float
    annualisation_recall: float
    boundary_mae: float
    selection_counts: dict[str, int]
    tie_breaks: tuple[str, ...]


def iter_timing_identifiability_points() -> Iterator[TimingIdentifiabilityThresholds]:
    """Yield the frozen timing grid, rejecting structurally invalid tuples."""
    for values in product(
        TIMING_IDENTIFIABILITY_GRID["min_amplitude_to_floor_ratio"],
        TIMING_IDENTIFIABILITY_GRID["min_peak_water_pixels"],
        TIMING_IDENTIFIABILITY_GRID["max_point_span_months"],
        TIMING_IDENTIFIABILITY_GRID["max_boundary_interval_months"],
        TIMING_IDENTIFIABILITY_GRID["min_informative_years"],
    ):
        try:
            yield TimingIdentifiabilityThresholds(*values)
        except ValueError:
            continue


def _timing_truth_status(detectable: bool, months: tuple[int, ...]) -> str:
    if not detectable:
        return "unresolved"
    return "point" if len(months) == 1 else "interval"


def build_timing_identifiability_cache(
    seeds: Iterable[int], *, partition: Literal["calibration", "validation"]
) -> pd.DataFrame:
    """Cache threshold-independent annual metrics for the timing corpus once.

    The permissive metric pass exposes amplitude ratios, pixel support, and
    equivalent-month spans.  Candidate thresholds are only applied later by
    :func:`select_timing_identifiability_defaults`, so the grid never reruns
    observation preparation or annual extrema calculation.
    """
    rows: list[dict[str, object]] = []
    permissive = TimingIdentifiabilityThresholds(0.0, 0, 11, 11, 0)
    for seed in seeds:
        record = generate_timing_identifiability_record(int(seed), partition=partition)
        evidence = assess_timing_identifiability(record.frame, thresholds=permissive)
        first_year = min(evidence.years)
        for year, annual in evidence.years.items():
            offset = int(year - first_year)
            truth = record.truth
            for kind, observed_months, truth_detectable, truth_months in (
                (
                    "peak",
                    annual.peak_months,
                    truth.detectable_peak_by_year[offset],
                    truth.peak_months_by_year[offset],
                ),
                (
                    "trough",
                    annual.trough_months,
                    truth.detectable_trough_by_year[offset],
                    truth.trough_months_by_year[offset],
                ),
            ):
                span = shortest_circular_span(observed_months)
                rows.append(
                    {
                        "seed": int(seed),
                        "family": record.family,
                        "year": int(year),
                        "kind": kind,
                        "amplitude_to_floor_ratio": annual.amplitude_to_floor_ratio,
                        "peak_n_water": annual.peak_n_water,
                        "observed_span_months": 12 if span is None else int(span),
                        "observed_anchor_month": int(observed_months[0]) if observed_months else 0,
                        "truth_status": _timing_truth_status(bool(truth_detectable), tuple(truth_months)),
                        "truth_anchor_month": int(truth_months[0]) if truth_months else 0,
                        "truth_detectable": bool(truth_detectable),
                        "truth_is_annual": bool(truth.is_annual),
                    }
                )
    return pd.DataFrame(rows)


def _timing_threshold_arrays(
    cache: pd.DataFrame, points: Sequence[TimingIdentifiabilityThresholds]
) -> tuple[list[TimingIdentifiabilityThresholds], dict[str, np.ndarray]]:
    points = list(points)
    if not points:
        raise RuntimeError("timing-identifiability grid contains no valid candidates.")
    required = {
        "seed", "family", "kind", "amplitude_to_floor_ratio", "peak_n_water",
        "observed_span_months", "observed_anchor_month", "truth_status",
        "truth_anchor_month", "truth_is_annual",
    }
    missing = required - set(cache.columns)
    if missing:
        raise ValueError(f"timing-identifiability cache missing columns: {sorted(missing)}")
    seeds, record_index = np.unique(cache["seed"].to_numpy(dtype=int), return_inverse=True)
    ratio = cache["amplitude_to_floor_ratio"].to_numpy(dtype=float)
    pixels = cache["peak_n_water"].fillna(-1).to_numpy(dtype=int)
    span = cache["observed_span_months"].to_numpy(dtype=int)
    is_peak = cache["kind"].eq("peak").to_numpy(dtype=bool)
    truth_point = cache["truth_status"].eq("point").to_numpy(dtype=bool)
    truth_annual = cache["truth_is_annual"].to_numpy(dtype=bool)
    anchor_error = np.minimum(
        np.abs(cache["observed_anchor_month"].to_numpy(dtype=int) - cache["truth_anchor_month"].to_numpy(dtype=int)),
        12 - np.abs(cache["observed_anchor_month"].to_numpy(dtype=int) - cache["truth_anchor_month"].to_numpy(dtype=int)),
    ).astype(float)
    family = cache["family"].to_numpy(dtype=object)
    candidate = np.array(
        [
            (p.min_amplitude_to_floor_ratio, p.min_peak_water_pixels, p.max_point_span_months,
             p.max_boundary_interval_months, p.min_informative_years)
            for p in points
        ],
        dtype=float,
    )
    detectable = (ratio[:, None] >= candidate[None, :, 0]) & (pixels[:, None] >= candidate[None, :, 1])
    point = detectable & (span[:, None] <= candidate[None, :, 2])
    interval = detectable & ~point & (span[:, None] <= candidate[None, :, 3])
    status = np.where(point, 2, np.where(interval, 1, 0)).astype(np.int8)
    n_records, n_points = len(seeds), len(points)
    peak_counts = np.zeros((n_records, n_points), dtype=np.int16)
    trough_counts = np.zeros((n_records, n_points), dtype=np.int16)
    np.add.at(peak_counts, record_index[is_peak], (status[is_peak] > 0).astype(np.int16))
    np.add.at(trough_counts, record_index[~is_peak], (status[~is_peak] > 0).astype(np.int16))
    published = np.minimum(peak_counts, trough_counts) >= candidate[None, :, 4]
    record_family = np.empty(n_records, dtype=object)
    record_annual = np.zeros(n_records, dtype=bool)
    for row, idx in enumerate(record_index):
        record_family[idx] = family[row]
        record_annual[idx] = truth_annual[row]
    return points, {
        "candidate": candidate,
        "status": status,
        "record_index": record_index,
        "published": published,
        "record_family": record_family,
        "record_annual": record_annual,
        "truth_point": truth_point,
        "anchor_error": anchor_error,
    }


def _score_timing_thresholds(
    cache: pd.DataFrame, points: Sequence[TimingIdentifiabilityThresholds]
) -> tuple[list[TimingIdentifiabilityThresholds], dict[str, np.ndarray], dict[str, np.ndarray]]:
    points, arrays = _timing_threshold_arrays(cache, points)
    status = arrays["status"]
    false_precise = (status == 2) & ~arrays["truth_point"][:, None]
    precise = status == 2
    n_false = false_precise.sum(axis=0)
    n_precise = precise.sum(axis=0)
    wilson_high = np.asarray(
        [wilson_interval(int(k), int(n))[1] if n else 1.0 for k, n in zip(n_false, n_precise, strict=True)],
        dtype=float,
    )
    rate = np.divide(n_false, n_precise, out=np.zeros(len(points), dtype=float), where=n_precise > 0)
    family = arrays["record_family"]
    controls = np.isin(family, ["all_zero_years", "persistent_low_amplitude_water", "broad_zero_plateaus"])
    positives = family == "intermittent_seasonal_pulses"
    published = arrays["published"]
    abstention = np.mean(~published[controls], axis=0) if np.any(controls) else np.zeros(len(points))
    recall = np.mean(published[positives], axis=0) if np.any(positives) else np.zeros(len(points))
    retained = (
        (status > 0)
        & arrays["truth_point"][:, None]
        & arrays["record_annual"][arrays["record_index"]][:, None]
        & published[arrays["record_index"]]
    )
    boundary_mae = np.empty(len(points), dtype=float)
    for col in range(len(points)):
        errors = arrays["anchor_error"][retained[:, col]]
        boundary_mae[col] = float(np.median(errors)) if len(errors) else 12.0
    return points, arrays, {
        "n_false": n_false,
        "n_precise": n_precise,
        "wilson_high": wilson_high,
        "rate": rate,
        "abstention": abstention,
        "recall": recall,
        "boundary_mae": boundary_mae,
    }


def _score_timing_points(
    cache: pd.DataFrame,
) -> tuple[list[TimingIdentifiabilityThresholds], dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Vectorially score the predeclared grid during calibration only."""
    return _score_timing_thresholds(cache, list(iter_timing_identifiability_points()))


def score_timing_identifiability_thresholds(
    cache: pd.DataFrame, thresholds: TimingIdentifiabilityThresholds
) -> TimingIdentifiabilityScore:
    """Score one frozen tuple without enumerating timing-grid candidates."""
    _points, _arrays, metrics = _score_timing_thresholds(cache, [thresholds])
    return TimingIdentifiabilityScore(
        thresholds=thresholds,
        false_precise_boundary_rate=float(metrics["rate"][0]),
        false_precise_boundary_wilson=wilson_interval(
            int(metrics["n_false"][0]), int(metrics["n_precise"][0])
        ),
        false_precise_boundary_n=int(metrics["n_precise"][0]),
        correct_abstention=float(metrics["abstention"][0]),
        annualisation_recall=float(metrics["recall"][0]),
        boundary_mae=float(metrics["boundary_mae"][0]),
        selection_counts={"evaluated_candidates": 1},
        tie_breaks=(),
    )


def select_timing_identifiability_defaults(
    cache: pd.DataFrame,
) -> tuple[TimingIdentifiabilityThresholds, TimingIdentifiabilityScore]:
    """Apply the frozen five-stage lexicographic timing selector."""
    points, _arrays, metrics = _score_timing_points(cache)
    survivors = np.flatnonzero(metrics["wilson_high"] <= 0.05)
    if not len(survivors):
        raise RuntimeError(
            "no timing-identifiability candidate satisfies the frozen false precise-boundary Wilson gate."
        )
    counts = {"grid": len(points), "false_precise_boundary_wilson": int(len(survivors))}
    ties = (
        "correct_abstention", "annualisation_recall", "median_absolute_boundary_error",
        "larger_min_amplitude_to_floor_ratio", "larger_min_peak_water_pixels",
        "smaller_max_point_span_months", "smaller_max_boundary_interval_months",
        "larger_min_informative_years",
    )

    def retain(name: str, values: np.ndarray, *, maximise: bool) -> None:
        nonlocal survivors
        best = values[survivors].max() if maximise else values[survivors].min()
        survivors = survivors[np.isclose(values[survivors], best)]
        counts[name] = int(len(survivors))

    retain("correct_abstention", metrics["abstention"], maximise=True)
    retain("annualisation_recall", metrics["recall"], maximise=True)
    retain("median_absolute_boundary_error", metrics["boundary_mae"], maximise=False)
    for name, position, maximise in (
        ("larger_min_amplitude_to_floor_ratio", 0, True),
        ("larger_min_peak_water_pixels", 1, True),
        ("smaller_max_point_span_months", 2, False),
        ("smaller_max_boundary_interval_months", 3, False),
        ("larger_min_informative_years", 4, True),
    ):
        values = np.asarray([getattr(point, (
            "min_amplitude_to_floor_ratio", "min_peak_water_pixels", "max_point_span_months",
            "max_boundary_interval_months", "min_informative_years",
        )[position]) for point in points], dtype=float)
        retain(name, values, maximise=maximise)
    counts["final_survivors"] = int(len(survivors))
    counts["selected"] = 1
    selected_index = int(survivors[0])
    selected = points[selected_index]
    score = TimingIdentifiabilityScore(
        thresholds=selected,
        false_precise_boundary_rate=float(metrics["rate"][selected_index]),
        false_precise_boundary_wilson=wilson_interval(
            int(metrics["n_false"][selected_index]), int(metrics["n_precise"][selected_index])
        ),
        false_precise_boundary_n=int(metrics["n_precise"][selected_index]),
        correct_abstention=float(metrics["abstention"][selected_index]),
        annualisation_recall=float(metrics["recall"][selected_index]),
        boundary_mae=float(metrics["boundary_mae"][selected_index]),
        selection_counts=counts,
        tie_breaks=ties,
    )
    return selected, score


def timing_identifiability_fingerprint(
    thresholds: TimingIdentifiabilityThresholds | None = None,
) -> str:
    """Fingerprint timing calibration inputs only; validation truth is excluded."""
    import inspect

    from . import (
        _scientific_defaults as defaults,
        _synthetic,
        _timing_identifiability as timing_metrics,
    )

    selected = thresholds or getattr(defaults, "TIMING_IDENTIFIABILITY_DEFAULTS", None)
    if selected is None:
        raise ValueError("timing-identifiability defaults have not been generated.")
    hasher = hashlib.sha256()
    for item in (
        _synthetic.TimingTruthLabels,
        _synthetic.generate_timing_identifiability_record,
        timing_metrics.assess_timing_identifiability,
        timing_metrics._validate_tolerance,
        timing_metrics._resolution_pp,
        timing_metrics._peak_water_pixels,
        timing_metrics._timing_status,
        robust_scale,
        prepare_monthly_extent,
        equivalent_extremum_months,
        shortest_circular_span,
        _timing_truth_status,
        build_timing_identifiability_cache,
        _score_timing_thresholds,
        _score_timing_points,
        select_timing_identifiability_defaults,
    ):
        hasher.update(inspect.getsource(item).encode("utf-8"))
    hasher.update(json.dumps(TIMING_IDENTIFIABILITY_GRID, sort_keys=True).encode("utf-8"))
    hasher.update(json.dumps(list(_synthetic.CALIBRATION_SEEDS)).encode("utf-8"))
    hasher.update(json.dumps(asdict(selected), sort_keys=True).encode("utf-8"))
    hasher.update(TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE.encode("utf-8"))
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Trough search geometry
#
# Unlike the timing grid, geometry is not threshold-independent: changing a
# radius changes detection itself, so the cache runs full boundary detection
# once per (record, tuple) pair rather than caching threshold-free metrics.
# ---------------------------------------------------------------------------

TROUGH_GEOMETRY_GRID = {
    "trough_search_radius_months": [3, 4, 5],
    "adaptive_trough_search_radius_months": [3, 4, 5],
    "adaptive_min_usable_months_per_cycle": [5, 6, 7, 8],
}
TROUGH_GEOMETRY_AUTHORITY_SCOPE = "candidate_for_established_0_3_0"

# Beyond half a cycle a published boundary cannot plausibly be the same trough
# as the truth date it is nearest to, so it is counted as a wrong-cycle match.
_GEOMETRY_MAX_MATCH_MONTHS = 6
_GEOMETRY_CYCLE_BOUNDS = (10, 14)


@dataclass(frozen=True)
class TroughGeometry:
    """One point of the joint geometry policy under selection."""

    trough_search_radius_months: int
    adaptive_trough_search_radius_months: int
    adaptive_min_usable_months_per_cycle: int


@dataclass(frozen=True)
class TroughGeometryScore:
    geometry: TroughGeometry
    false_precise_boundary_rate: float
    false_precise_boundary_wilson: tuple[float, float]
    false_precise_boundary_n: int
    duplicate_or_nonmonotonic_rate: float
    boundary_mae: float
    boundary_signed_bias: float
    wrong_cycle_rate: float
    short_long_cycle_rate: float
    coverage_drop_rate: float
    abstention_rate: float
    outside_window_lower_rate: float
    selection_counts: dict[str, int]
    tie_breaks: tuple[str, ...]


def iter_trough_geometry_points() -> Iterator[TroughGeometry]:
    """Enumerate the 24 valid points of the frozen geometry grid.

    A retry that narrows the base search, or a relaxation that tightens the base
    minimum coverage, is rejected before scoring rather than scored and lost.
    """
    for base, adaptive, coverage in product(
        TROUGH_GEOMETRY_GRID["trough_search_radius_months"],
        TROUGH_GEOMETRY_GRID["adaptive_trough_search_radius_months"],
        TROUGH_GEOMETRY_GRID["adaptive_min_usable_months_per_cycle"],
    ):
        if adaptive < base or coverage > 8:
            continue
        yield TroughGeometry(base, adaptive, coverage)


def _geometry_month_delta(actual: pd.Timestamp, expected: pd.Timestamp) -> int:
    return (actual.year - expected.year) * 12 + actual.month - expected.month


def _geometry_rows(
    record: SyntheticRecord, geometry_index: int, annual: pd.DataFrame
) -> list[dict[str, object]]:
    """Score one detection run against its record's truth.

    "Published" means a genuine point-timing claim -- ``trough_timing_status
    == "point"`` -- not merely a populated ``trough_month``.  ``trough_month``
    is an internal operational boundary date that is populated on essentially
    every row regardless of timing status (see ``docs/hydrological-state.md``,
    the ``peak_timing_status``/``trough_timing_status``/``timing_status``
    section): a flat or below-floor year still gets an operational trough date
    even though it contributes no identifiable peak or trough timing
    observation.  ``trough_timing_status`` is the field that actually says
    whether that date is an exact claim (``"point"``), a bounded interval
    (``"interval"``), or nothing resolvable (``"unresolved"``); it can also be
    ``NaN`` on the rare row where ``trough_month`` is set but timing was never
    computed (e.g. ``insufficient_cycle_coverage`` on the first cycle, before
    any prior boundary exists to bound a cycle against). Only ``"point"``
    counts as published here -- an ``"interval"`` row is the detector
    correctly declining to claim precision and must not be scored as a claimed
    point-truth date; a ``NaN``/``"unresolved"`` row has no timing verdict at
    all and is likewise not published.

    The record-level monotonicity/duplicate-date check below is intentionally
    kept on the *raw* operational ``trough_month`` rather than restricted to
    point-status rows: ``hy_start``/``hy_end``/``cycle_months`` (used
    elsewhere in this scoring) are built from the operational date regardless
    of timing status, so a genuinely duplicate or non-monotonic operational
    date is still a structural problem in the detector's cycle bookkeeping
    even when its timing status is ``"interval"``. Diluting this check to
    point-only rows would hide a structural defect on any record where every
    row happens to resolve to ``"interval"``.

    ``identifiable_by_year`` and ``trough_date_by_year`` are per-year: a row is
    only matched against truth when its *own* year is identifiable.  A
    published boundary on an unidentifiable year is never nearest-matched --
    no truth date is correct for it, so it counts only as a false precise
    boundary, never as a wrong-cycle or accuracy error.

    Among identifiable-year rows, a published boundary is matched to the
    nearest truth trough among *identifiable* years only -- an unidentifiable
    year contributes no candidate date, since no boundary is correct for it.
    A match further than half a cycle away is a wrong-cycle error: the
    boundary exists but names the wrong year.  When two boundaries both
    resolve to the same truth trough -- one genuinely close to it, one that
    drifted onto it from a neighbouring year -- only the *later* claimant (in
    row/iteration order) is marked wrong-cycle.  The first claimant is never
    flagged for this reason alone: it may be the boundary that is genuinely
    correct for that truth date, and flagging both would penalise a case
    where only one boundary is actually spurious.
    """
    truth = record.truth
    base_year = int(annual["hy_year"].min())
    identifiable_truth_dates = [
        date
        for year_identifiable, date in zip(
            truth.identifiable_by_year, truth.trough_date_by_year
        )
        if year_identifiable and date is not None
    ]

    # Structural check: raw operational dates, regardless of timing status.
    operational = annual.loc[annual["trough_month"].notna()]
    boundaries = [pd.Timestamp(value) for value in operational["trough_month"]]
    monotonic = all(
        earlier < later for earlier, later in zip(boundaries, boundaries[1:])
    )
    nonmonotonic = not monotonic or len(set(boundaries)) != len(boundaries)

    claimed: dict[pd.Timestamp, int] = {}
    rows: list[dict[str, object]] = []
    for _, row in annual.iterrows():
        is_published = row.get("trough_timing_status") == "point"
        offset = int(row["hy_year"]) - base_year
        row_identifiable = bool(truth.identifiable_by_year[offset])
        error = np.nan
        wrong_cycle = False
        if is_published and row_identifiable and identifiable_truth_dates:
            # This row's own year is identifiable, so it is a legitimate
            # candidate for nearest-match scoring; the pool of candidate
            # truth dates is restricted to identifiable years only, so an
            # unidentifiable year's (masked/absent) date can never be
            # nearest-matched into another row's error or wrong-cycle count.
            selected = pd.Timestamp(row["trough_month"])
            nearest = min(
                identifiable_truth_dates,
                key=lambda date: abs(_geometry_month_delta(selected, date)),
            )
            error = float(_geometry_month_delta(selected, nearest))
            claimed[nearest] = claimed.get(nearest, 0) + 1
            wrong_cycle = abs(error) > _GEOMETRY_MAX_MATCH_MONTHS or claimed[nearest] > 1
        rows.append(
            {
                "seed": int(record.seed),
                "family": record.family,
                "geometry_index": int(geometry_index),
                "hy_year": int(row["hy_year"]),
                "published": bool(is_published),
                # Per-row identifiability: this row's own year, not any
                # record-wide reduction over all years.
                "truth_identifiable": row_identifiable,
                "error_months": error,
                "wrong_cycle": bool(wrong_cycle),
                "coverage_drop": bool(row.get("status_reason") == "insufficient_cycle_coverage"),
                "record_nonmonotonic": bool(nonmonotonic),
                "outside_window_observed": bool(row.get("outside_window_observed", False)),
                "outside_window_lower": bool(row.get("outside_window_lower", False)),
                "cycle_months": float(row["cycle_months"]) if pd.notna(row.get("cycle_months")) else np.nan,
            }
        )
    return rows


def build_trough_geometry_cache(
    seeds: Iterable[int], *, partition: Literal["calibration", "validation"]
) -> pd.DataFrame:
    """Run detection once per (record, geometry tuple) and cache the outcome."""
    from ._dynamic_year import DynamicHydroYearConfig, detect_dynamic_hydrological_years
    from ._synthetic import generate_trough_geometry_record

    points = list(iter_trough_geometry_points())
    rows: list[dict[str, object]] = []
    for seed in seeds:
        record = generate_trough_geometry_record(int(seed), partition=partition)
        for index, geometry in enumerate(points):
            config = DynamicHydroYearConfig(
                expected_trough_month=record.truth.climatological_trough_month,
                trough_search_radius_months=geometry.trough_search_radius_months,
                adaptive_trough_search_radius_months=geometry.adaptive_trough_search_radius_months,
                adaptive_min_usable_months_per_cycle=geometry.adaptive_min_usable_months_per_cycle,
            )
            annual = detect_dynamic_hydrological_years(record.frame, config=config)
            rows.extend(_geometry_rows(record, index, annual))
    return pd.DataFrame(rows)


def _geometry_metrics(cache: pd.DataFrame, geometry_index: int) -> dict[str, float]:
    """Compute every predeclared metric for one tuple.

    Denominators differ by metric and are never mixed:
    ``false_precise_boundary_rate`` is over boundaries published on
    unidentifiable truth; ``boundary_mae`` is over identifiable years with a
    published, correctly-cycled boundary; ``outside_window_lower_rate`` is
    over boundaries with a fully observed audit span.

    ``boundary_mae`` and ``boundary_signed_bias`` exclude ``wrong_cycle`` rows.
    A wrong-cycle match is a large, off-by-a-year error that is already
    captured by ``wrong_cycle_rate``; leaving it in the error-distance sample
    would double-count the same failure as both a wrong-cycle error and an
    accuracy error, and a single such outlier can dominate the (undamped)
    mean that feeds ``boundary_signed_bias``.
    """
    subset = cache.loc[cache["geometry_index"] == geometry_index]
    published = subset.loc[subset["published"]]

    unidentifiable = subset.loc[~subset["truth_identifiable"]]
    n_false = int(unidentifiable["published"].sum())
    n_unidentifiable = int(len(unidentifiable))

    identifiable = subset.loc[subset["truth_identifiable"]]
    matched = identifiable.loc[
        identifiable["published"]
        & identifiable["error_months"].notna()
        & ~identifiable["wrong_cycle"]
    ]
    errors = matched["error_months"].to_numpy(dtype=float)

    records = subset.groupby("seed")["record_nonmonotonic"].any()
    cycles = published["cycle_months"].dropna()
    observed = published.loc[published["outside_window_observed"]]

    return {
        "false_precise_boundary_rate": (n_false / n_unidentifiable) if n_unidentifiable else 0.0,
        "n_false": float(n_false),
        "n_unidentifiable": float(n_unidentifiable),
        "duplicate_or_nonmonotonic_rate": float(records.mean()) if len(records) else 0.0,
        "boundary_mae": float(np.median(np.abs(errors))) if errors.size else 12.0,
        "boundary_signed_bias": float(np.mean(errors)) if errors.size else 0.0,
        "wrong_cycle_rate": float(published["wrong_cycle"].mean()) if len(published) else 0.0,
        "short_long_cycle_rate": (
            float(
                ((cycles < _GEOMETRY_CYCLE_BOUNDS[0]) | (cycles > _GEOMETRY_CYCLE_BOUNDS[1])).mean()
            )
            if len(cycles)
            else 0.0
        ),
        "coverage_drop_rate": float(subset["coverage_drop"].mean()) if len(subset) else 0.0,
        "abstention_rate": (
            float((~identifiable["published"]).mean()) if len(identifiable) else 0.0
        ),
        "outside_window_lower_rate": (
            float(observed["outside_window_lower"].mean()) if len(observed) else 0.0
        ),
    }


def _geometry_score(
    geometry: TroughGeometry,
    metrics: dict[str, float],
    *,
    selection_counts: dict[str, int],
    tie_breaks: tuple[str, ...],
) -> TroughGeometryScore:
    return TroughGeometryScore(
        geometry=geometry,
        false_precise_boundary_rate=metrics["false_precise_boundary_rate"],
        false_precise_boundary_wilson=wilson_interval(
            int(metrics["n_false"]), int(metrics["n_unidentifiable"])
        ),
        false_precise_boundary_n=int(metrics["n_unidentifiable"]),
        duplicate_or_nonmonotonic_rate=metrics["duplicate_or_nonmonotonic_rate"],
        boundary_mae=metrics["boundary_mae"],
        boundary_signed_bias=metrics["boundary_signed_bias"],
        wrong_cycle_rate=metrics["wrong_cycle_rate"],
        short_long_cycle_rate=metrics["short_long_cycle_rate"],
        coverage_drop_rate=metrics["coverage_drop_rate"],
        abstention_rate=metrics["abstention_rate"],
        outside_window_lower_rate=metrics["outside_window_lower_rate"],
        selection_counts=selection_counts,
        tie_breaks=tie_breaks,
    )


def score_trough_geometry(
    cache: pd.DataFrame, geometry: TroughGeometry
) -> TroughGeometryScore:
    """Score one frozen tuple without enumerating the grid."""
    points = list(iter_trough_geometry_points())
    if geometry not in points:
        raise ValueError(f"{geometry} is not a point of TROUGH_GEOMETRY_GRID.")
    metrics = _geometry_metrics(cache, points.index(geometry))
    return _geometry_score(
        geometry, metrics, selection_counts={"evaluated_candidates": 1}, tie_breaks=()
    )


def select_trough_geometry_defaults(
    cache: pd.DataFrame,
) -> tuple[TroughGeometry, TroughGeometryScore]:
    """Apply the frozen seven-stage lexicographic geometry selector.

    Stage 7 prefers the shipped tuple on a tie so that a geometry change must be
    earned: a tie does not justify republishing every hydrological year in every
    downstream record.

    The outside-window-challenge rate is deliberately absent from this
    function's own metrics.  It is a challenge count against an unlabelled
    alternative, so selecting on it would reward any tuple that widens the
    search window regardless of whether the wider choice is correct.
    """
    points = list(iter_trough_geometry_points())
    metrics = [_geometry_metrics(cache, index) for index in range(len(points))]
    counts = {"grid": len(points)}

    def column(name: str) -> np.ndarray:
        return np.asarray([item[name] for item in metrics], dtype=float)

    wilson_high = np.asarray(
        [
            wilson_interval(int(item["n_false"]), int(item["n_unidentifiable"]))[1]
            if item["n_unidentifiable"]
            else 0.0
            for item in metrics
        ],
        dtype=float,
    )
    survivors = np.flatnonzero(wilson_high <= 0.05)
    counts["false_precise_boundary_wilson"] = int(len(survivors))
    if not len(survivors):
        raise RuntimeError(
            "no trough-geometry candidate satisfies the frozen false precise-boundary Wilson gate."
        )

    structural = column("duplicate_or_nonmonotonic_rate")
    survivors = survivors[structural[survivors] == 0.0]
    counts["duplicate_or_nonmonotonic"] = int(len(survivors))
    if not len(survivors):
        raise RuntimeError(
            "no trough-geometry candidate satisfies the duplicate_or_nonmonotonic structural gate; "
            "a policy that can emit non-monotonic boundaries is inadmissible at any accuracy."
        )

    def retain(name: str, values: np.ndarray) -> None:
        nonlocal survivors
        best = values[survivors].min()
        survivors = survivors[np.isclose(values[survivors], best)]
        counts[name] = int(len(survivors))

    retain("boundary_mae", column("boundary_mae"))
    retain("wrong_cycle_rate", column("wrong_cycle_rate"))
    retain("abstention_rate", column("abstention_rate"))
    retain("boundary_signed_bias", np.abs(column("boundary_signed_bias")))

    shipped = TroughGeometry(3, 5, 6)
    status_quo = np.asarray(
        [
            (
                0 if points[index] == shipped else 1,
                points[index].trough_search_radius_months,
                points[index].adaptive_trough_search_radius_months,
                -points[index].adaptive_min_usable_months_per_cycle,
            )
            for index in survivors
        ],
        dtype=float,
    )
    order = np.lexsort(
        (status_quo[:, 3], status_quo[:, 2], status_quo[:, 1], status_quo[:, 0])
    )
    selected_index = int(survivors[order[0]])
    counts["status_quo_tie_break"] = int(len(survivors))
    counts["final_survivors"] = int(len(survivors))
    counts["selected"] = 1

    tie_breaks = (
        "false_precise_boundary_wilson", "duplicate_or_nonmonotonic", "boundary_mae",
        "wrong_cycle_rate", "abstention_rate", "abs_boundary_signed_bias",
        "status_quo_shipped_tuple", "smaller_trough_search_radius_months",
        "smaller_adaptive_trough_search_radius_months",
        "larger_adaptive_min_usable_months_per_cycle",
    )
    score = _geometry_score(
        points[selected_index],
        metrics[selected_index],
        selection_counts=counts,
        tie_breaks=tie_breaks,
    )
    return points[selected_index], score


def trough_geometry_fingerprint(geometry: TroughGeometry | None = None) -> str:
    """Fingerprint geometry calibration inputs only; validation truth excluded."""
    import inspect

    from . import (
        _dynamic_year as dynamic_year,
        _scientific_defaults as defaults,
        _synthetic,
    )

    selected = geometry or getattr(defaults, "TROUGH_GEOMETRY_DEFAULTS", None)
    if selected is None:
        raise ValueError("trough-geometry defaults have not been generated.")
    hasher = hashlib.sha256()
    for item in (
        _synthetic.TroughGeometryTruthLabels,
        _synthetic.generate_trough_geometry_record,
        _synthetic._geometry_frame,
        dynamic_year.DynamicHydroYearConfig,
        dynamic_year.detect_dynamic_hydrological_years,
        dynamic_year._find_robust_trough_opportunities,
        dynamic_year._adaptive_edge_retry_years,
        dynamic_year._search_edge_diagnostics,
        _geometry_rows,
        _geometry_metrics,
        build_trough_geometry_cache,
        select_trough_geometry_defaults,
    ):
        hasher.update(inspect.getsource(item).encode("utf-8"))
    hasher.update(json.dumps(TROUGH_GEOMETRY_GRID, sort_keys=True).encode("utf-8"))
    hasher.update(json.dumps(list(_synthetic.GEOMETRY_CALIBRATION_SEEDS)).encode("utf-8"))
    hasher.update(json.dumps(asdict(selected), sort_keys=True).encode("utf-8"))
    hasher.update(TROUGH_GEOMETRY_AUTHORITY_SCOPE.encode("utf-8"))
    return hasher.hexdigest()






def calibration_environment() -> dict[str, str]:
    """The interpreter and dependency versions a calibration ran under.

    Recorded alongside the constants rather than hashed into
    :func:`fingerprint`, so the generating environment is auditable without
    making the staleness check environment-specific.
    """
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


def fingerprint(
    *,
    evidence_defaults: EvidenceThresholds | None = None,
    recoverability_defaults: RecoverabilityThresholds | None = None,
) -> str:
    """Canonical SHA-256 fingerprint over generator, grid, objective, seed manifest, and selected constants.

    Changing the synthetic generator, either search grid, an objective
    function, the seed manifest, or any selected constant changes this value,
    which is what marks the shipped defaults stale. Interpreter and dependency
    versions do not -- :func:`calibration_environment` records those.
    """
    from . import _scientific_defaults as defaults, _synthetic

    hasher = hashlib.sha256()

    # Generator source code.  The timing-identifiability corpus is appended to
    # this module behind an explicit boundary and does not feed the established
    # evidence calibration, so it must not stale that independent artifact.
    import inspect

    legacy_source = inspect.getsource(_synthetic).split(
        "\n\n# TIMING_IDENTIFIABILITY_SYNTHETIC_CORPUS", 1
    )[0]
    hasher.update(legacy_source.encode("utf-8"))

    # Grid constants and the shipping objective implementations.
    hasher.update(json.dumps(EVIDENCE_GRID, sort_keys=True).encode("utf-8"))
    for objective in (
        score_evidence_grid_point,
        select_evidence_defaults,
    ):
        hasher.update(inspect.getsource(objective).encode("utf-8"))

    # Seed manifest
    hasher.update(
        json.dumps(list(_synthetic.CALIBRATION_SEEDS)).encode("utf-8")
    )

    # Interpreter and dependency versions are deliberately NOT hashed. They
    # are provenance, not a scientific input: folding them in makes the
    # fingerprint interpreter-specific, so a test asserting equality can pass
    # on at most one row of a CI matrix that spans Python 3.10-3.13 and a
    # pinned minimum-dependency floor. They are recorded instead -- see
    # calibration_environment() and CALIBRATION_ENVIRONMENT in the generated
    # defaults module -- so the generating environment stays auditable.

    selected = {
        "evidence": asdict(
            evidence_defaults
            or getattr(defaults, "EVIDENCE_DEFAULTS", EvidenceThresholds())
        ),
        "recoverability": asdict(
            recoverability_defaults
            or getattr(defaults, "RECOVERABILITY_DEFAULTS", RecoverabilityThresholds())
        ),
        "authority_scope": {
            "evidence": getattr(
                defaults, "EVIDENCE_AUTHORITY_SCOPE", AUTHORITY_SCOPE["evidence"]
            ),
            "recoverability": getattr(
                defaults,
                "RECOVERABILITY_AUTHORITY_SCOPE",
                AUTHORITY_SCOPE["recoverability"],
            ),
        },
    }
    hasher.update(json.dumps(selected, sort_keys=True).encode("utf-8"))

    return hasher.hexdigest()
