"""Independent calibration and untouched validation for Pass-2 troughs."""
from __future__ import annotations

import hashlib
import inspect
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from typing import Iterable, Literal, Sequence

import numpy as np
import pandas as pd

from ._calibration import wilson_interval
from ._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS
from ._synthetic import generate_trough_refinement_record
from ._trough_refinement import TroughRefinementPolicy, refine_trough_span

TROUGH_REFINEMENT_AUTHORITY_SCOPE = "trough_refinement_candidate_0_1"
TROUGH_REFINEMENT_GRID = {
    "huber_k": (1.0, 1.345, 1.5, 2.0),
    "profile_loss_cutoff": (0.0, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    "pulse_z": (1.5, 2.0, 2.5, 3.0),
}


@dataclass(frozen=True)
class TroughRefinementScore:
    policy: TroughRefinementPolicy
    boundary_set_inclusion: float
    false_precise_boundary_rate: float
    false_precise_boundary_wilson: tuple[float, float]
    false_precise_boundary_n: int
    median_distance_months: float
    p90_distance_months: float
    pass1_median_distance_months: float
    pass1_p90_distance_months: float
    coverage: float
    abstention_rate: float
    peak_changes: int
    duplicate_or_nonmonotonic: int
    wrong_cycle: int
    new_uncomputable: int
    mean_interval_width_months: float
    mean_boundary_change_months: float
    selection_counts: dict[str, int]


def iter_trough_refinement_policies() -> Iterable[TroughRefinementPolicy]:
    for huber_k in TROUGH_REFINEMENT_GRID["huber_k"]:
        for profile_loss_cutoff in TROUGH_REFINEMENT_GRID["profile_loss_cutoff"]:
            for pulse_z in TROUGH_REFINEMENT_GRID["pulse_z"]:
                yield TroughRefinementPolicy(
                    huber_k=huber_k,
                    profile_loss_cutoff=profile_loss_cutoff,
                    pulse_z=pulse_z,
                    version=TROUGH_REFINEMENT_AUTHORITY_SCOPE,
                )


def _month_delta(left: pd.Timestamp, right: pd.Timestamp) -> int:
    return (left.year - right.year) * 12 + left.month - right.month


def distance_to_truth_interval(
    predicted: pd.Timestamp,
    truth_start: pd.Timestamp,
    truth_end: pd.Timestamp,
) -> int:
    predicted = pd.Timestamp(predicted)
    truth_start = pd.Timestamp(truth_start)
    truth_end = pd.Timestamp(truth_end)
    if truth_start <= predicted <= truth_end:
        return 0
    return min(
        abs(_month_delta(predicted, truth_start)),
        abs(_month_delta(predicted, truth_end)),
    )


def _timing_status(candidates: tuple[pd.Timestamp, ...]) -> str:
    if not candidates:
        return "unresolved"
    span = abs(_month_delta(candidates[-1], candidates[0]))
    thresholds = TIMING_IDENTIFIABILITY_DEFAULTS
    if span <= thresholds.max_point_span_months:
        return "point"
    if span <= thresholds.max_boundary_interval_months:
        return "interval"
    if span <= thresholds.max_broad_interval_months:
        return "broad"
    return "unresolved"


def _cache_row(record, policy_index: int, policy: TroughRefinementPolicy) -> dict:
    result = refine_trough_span(
        record.frame,
        left_peak=record.left_peak,
        right_peak=record.right_peak,
        policy=policy,
    )
    applied = result.status in {"confirmed", "provisional"} and result.boundary is not None
    candidates = result.boundary_candidates if applied else ()
    predicted = pd.Timestamp(result.boundary) if applied else pd.NaT
    left = record.left_peak.selected
    right = record.right_peak.selected if record.right_peak is not None else None
    wrong_cycle = bool(
        applied
        and (
            left is None
            or right is None
            or not pd.Timestamp(left) < predicted < pd.Timestamp(right)
        )
    )
    return {
        "seed": int(record.seed),
        "family": record.family,
        "policy_index": policy_index,
        "truth_resolvable": record.truth.resolvable,
        "truth_start": record.truth.boundary_start or pd.NaT,
        "truth_end": record.truth.boundary_end or pd.NaT,
        "pass1_boundary": record.pass1_boundary or pd.NaT,
        "predicted_boundary": predicted,
        "predicted_start": candidates[0] if candidates else pd.NaT,
        "predicted_end": candidates[-1] if candidates else pd.NaT,
        "predicted_timing_status": _timing_status(candidates),
        "refinement_status": result.status,
        "refinement_reason": result.reason,
        "peak_changed": False,
        "duplicate_or_nonmonotonic": False,
        "wrong_cycle": wrong_cycle,
        "new_uncomputable": False,
        "applied": applied,
    }


def build_trough_refinement_cache(
    seeds: Iterable[int],
    *,
    partition: Literal["calibration", "validation"],
    policies: Sequence[TroughRefinementPolicy] | None = None,
    workers: int = 1,
) -> pd.DataFrame:
    """Evaluate the frozen policy tuples; validation callers pass one frozen tuple."""
    all_policies = list(iter_trough_refinement_policies())
    selected = list(policies) if policies is not None else all_policies
    if workers < 1:
        raise ValueError("workers must be positive.")
    for policy in selected:
        if policy not in all_policies:
            raise ValueError(f"{policy} is not a frozen trough-refinement policy.")
    args = [
        (int(seed), partition, tuple(selected), tuple(all_policies)) for seed in seeds
    ]
    if workers == 1:
        batches = map(_build_seed_rows, args)
    else:
        executor = ProcessPoolExecutor(max_workers=workers)
        batches = executor.map(_build_seed_rows, args, chunksize=1)
    try:
        rows = [row for batch in batches for row in batch]
    finally:
        if workers != 1:
            executor.shutdown()
    return pd.DataFrame(rows)


def _build_seed_rows(args: tuple) -> list[dict]:
    seed, partition, selected, all_policies = args
    record = generate_trough_refinement_record(int(seed), partition=partition)
    return [
        _cache_row(record, all_policies.index(policy), policy)
        for policy in selected
    ]


def _percentile(values: np.ndarray, percentile: float, fallback: float) -> float:
    return float(np.percentile(values, percentile)) if values.size else fallback


def score_trough_refinement_policy(
    cache: pd.DataFrame,
    policy: TroughRefinementPolicy,
) -> TroughRefinementScore:
    policies = list(iter_trough_refinement_policies())
    if policy not in policies:
        raise ValueError(f"{policy} is not a point of TROUGH_REFINEMENT_GRID.")
    subset = cache.loc[cache["policy_index"] == policies.index(policy)].copy()
    if subset.empty:
        raise ValueError("cache has no rows for the requested trough-refinement policy.")

    resolvable = subset.loc[subset["truth_resolvable"]]
    applied = resolvable.loc[resolvable["applied"]]
    inclusions = (
        (applied["predicted_end"] >= applied["truth_start"])
        & (applied["predicted_start"] <= applied["truth_end"])
    )
    inclusion = float(inclusions.sum() / len(resolvable)) if len(resolvable) else 0.0
    distances = np.asarray(
        [
            distance_to_truth_interval(row.predicted_boundary, row.truth_start, row.truth_end)
            for row in applied.itertuples(index=False)
        ],
        dtype=float,
    )
    pass1_distances = np.asarray(
        [
            distance_to_truth_interval(row.pass1_boundary, row.truth_start, row.truth_end)
            for row in resolvable.itertuples(index=False)
            if pd.notna(row.pass1_boundary)
        ],
        dtype=float,
    )

    unresolvable = subset.loc[~subset["truth_resolvable"]]
    false_precise = unresolvable[
        unresolvable["applied"]
        & unresolvable["predicted_timing_status"].eq("point")
    ]
    n_false = int(len(false_precise))
    n_unresolvable = int(len(unresolvable))
    resolved_count = int(len(applied))
    coverage = float(resolved_count / len(resolvable)) if len(resolvable) else 0.0
    interval_widths = np.asarray(
        [
            abs(_month_delta(row.predicted_end, row.predicted_start))
            for row in applied.itertuples(index=False)
        ],
        dtype=float,
    )
    changes = np.asarray(
        [
            abs(_month_delta(row.predicted_boundary, row.pass1_boundary))
            for row in applied.itertuples(index=False)
            if pd.notna(row.pass1_boundary)
        ],
        dtype=float,
    )
    return TroughRefinementScore(
        policy=policy,
        boundary_set_inclusion=inclusion,
        false_precise_boundary_rate=(
            float(n_false / n_unresolvable) if n_unresolvable else 0.0
        ),
        false_precise_boundary_wilson=wilson_interval(n_false, n_unresolvable),
        false_precise_boundary_n=n_unresolvable,
        median_distance_months=_percentile(distances, 50.0, 12.0),
        p90_distance_months=_percentile(distances, 90.0, 12.0),
        pass1_median_distance_months=_percentile(pass1_distances, 50.0, 12.0),
        pass1_p90_distance_months=_percentile(pass1_distances, 90.0, 12.0),
        coverage=coverage,
        abstention_rate=1.0 - coverage,
        peak_changes=int(subset["peak_changed"].sum()),
        duplicate_or_nonmonotonic=int(subset["duplicate_or_nonmonotonic"].sum()),
        wrong_cycle=int(subset["wrong_cycle"].sum()),
        new_uncomputable=int(subset["new_uncomputable"].sum()),
        mean_interval_width_months=(
            float(np.mean(interval_widths)) if interval_widths.size else 0.0
        ),
        mean_boundary_change_months=(
            float(np.mean(changes)) if changes.size else 0.0
        ),
        selection_counts={"evaluated_candidates": 1},
    )


def _admissible(score: TroughRefinementScore) -> bool:
    return bool(
        score.boundary_set_inclusion >= 0.95
        and score.false_precise_boundary_wilson[1] <= 0.05
        and score.peak_changes == 0
        and score.duplicate_or_nonmonotonic == 0
        and score.wrong_cycle == 0
        and score.new_uncomputable == 0
        and score.median_distance_months <= 1.0
        and score.p90_distance_months <= 2.0
        and score.median_distance_months <= score.pass1_median_distance_months
        and score.p90_distance_months <= score.pass1_p90_distance_months
    )


def select_trough_refinement_policy(
    cache: pd.DataFrame,
) -> tuple[TroughRefinementPolicy, TroughRefinementScore]:
    policies = list(iter_trough_refinement_policies())
    indexes = sorted(int(index) for index in cache["policy_index"].unique())
    scores = [score_trough_refinement_policy(cache, policies[index]) for index in indexes]
    survivors = [score for score in scores if _admissible(score)]
    if not survivors:
        raise RuntimeError(
            "no trough-refinement candidate satisfies the frozen calibration gates."
        )
    survivors.sort(
        key=lambda score: (
            score.median_distance_months,
            score.p90_distance_months,
            score.abstention_rate,
            score.mean_boundary_change_months,
            -score.mean_interval_width_months,
            abs(score.policy.huber_k - 1.345),
            score.policy.profile_loss_cutoff,
            score.policy.pulse_z,
        )
    )
    selected = survivors[0]
    return selected.policy, TroughRefinementScore(
        **{
            **asdict(selected),
            "policy": selected.policy,
            "false_precise_boundary_wilson": selected.false_precise_boundary_wilson,
            "selection_counts": {
                "grid": len(scores),
                "admissible": len(survivors),
                "selected": 1,
            },
        }
    )


def trough_refinement_fingerprint(policy: TroughRefinementPolicy) -> str:
    """Hash calibration inputs only; untouched validation truth is excluded."""
    from . import _state_input, _synthetic, _trough_refinement

    hasher = hashlib.sha256()
    hasher.update(inspect.getsource(_trough_refinement).encode("utf-8"))
    for item in (
        _synthetic.TroughRefinementTruth,
        _synthetic.TroughRefinementSyntheticRecord,
        _synthetic._trough_refinement_values,
        _synthetic.generate_trough_refinement_record,
        _state_input.prepare_monthly_extent,
        _cache_row,
        build_trough_refinement_cache,
        distance_to_truth_interval,
        score_trough_refinement_policy,
        _admissible,
        select_trough_refinement_policy,
    ):
        hasher.update(inspect.getsource(item).encode("utf-8"))
    hasher.update(json.dumps(_synthetic._TROUGH_REFINEMENT_FAMILIES).encode("utf-8"))
    hasher.update(json.dumps(TROUGH_REFINEMENT_GRID, sort_keys=True).encode("utf-8"))
    hasher.update(
        json.dumps(list(_synthetic.TROUGH_REFINEMENT_CALIBRATION_SEEDS)).encode("utf-8")
    )
    hasher.update(json.dumps(asdict(policy), sort_keys=True).encode("utf-8"))
    hasher.update(TROUGH_REFINEMENT_AUTHORITY_SCOPE.encode("utf-8"))
    return hasher.hexdigest()


__all__ = [
    "TROUGH_REFINEMENT_AUTHORITY_SCOPE",
    "TROUGH_REFINEMENT_GRID",
    "TroughRefinementScore",
    "build_trough_refinement_cache",
    "distance_to_truth_interval",
    "iter_trough_refinement_policies",
    "score_trough_refinement_policy",
    "select_trough_refinement_policy",
    "trough_refinement_fingerprint",
]
