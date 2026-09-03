"""Scoring, lexicographic selection, and parameter fingerprinting for recurrence policies."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from . import (
    _recurrence_identifiability as recurrence_metrics,
    _recurrence_synthetic as recurrence_synthetic,
)
from ._calibration import wilson_interval
from ._recurrence_identifiability import (
    ELIGIBLE_RECURRENCE_POLICIES,
    RecurrencePolicy,
)
from ._recurrence_synthetic import (
    RecurrenceSyntheticRecord,
)
from ._timing_identifiability import (
    PixelSupportStatus,
    TimingStatus,
    _window_status,
    assess_window_timing,
)

RECURRENCE_AUTHORITY_SCOPE: str = "candidate_for_established_0_2_0"


@dataclass(frozen=True)
class RecurrenceEvaluation:
    policy: RecurrencePolicy
    family: str
    kind: Literal["peak", "trough"]
    pixel_support_status: PixelSupportStatus
    truth_status: TimingStatus
    predicted_status: TimingStatus
    exact_latest_dates: bool


@dataclass(frozen=True)
class RecurrencePolicyScore:
    policy: RecurrencePolicy
    false_point_k: int
    false_point_n: int
    false_point_rate: float
    false_point_wilson: tuple[float, float]
    false_resolution_k: int
    false_resolution_n: int
    false_resolution_rate: float
    false_resolution_wilson: tuple[float, float]
    genuine_recurrence_status_accuracy: float
    exact_latest_date_accuracy: float
    conservative_abstention_rate: float
    by_family: dict[str, dict[str, int | float]]
    by_kind: dict[str, dict[str, int | float]]
    by_pixel_support: dict[str, dict[str, int | float]]


def evaluate_recurrence_records(
    records: Iterable[RecurrenceSyntheticRecord],
    policies: Sequence[RecurrencePolicy] = ELIGIBLE_RECURRENCE_POLICIES,
) -> list[RecurrenceEvaluation]:
    """Evaluate synthetic recurrence records against candidate policies via assess_window_timing."""
    evaluations: list[RecurrenceEvaluation] = []
    for record in records:
        for policy in policies:
            result = assess_window_timing(
                record.values,
                record.rows,
                thresholds=record.thresholds,
                measurement_tolerance_pct=record.measurement_tolerance_pct,
                noise_pp=record.noise_pp,
                pixel_support_status=record.pixel_support_status,
                recurrence_policy=policy,
                window_start=record.window_start,
                window_end=record.window_end,
            )
            if record.truth.kind == "peak":
                predicted_status = result.peak_status
                predicted_dates = result.peak_dates
            else:
                predicted_status = result.trough_status
                predicted_dates = result.trough_dates

            exact_latest_dates = bool(
                record.truth.status in {"point", "interval"}
                and tuple(predicted_dates) == tuple(record.truth.latest_dates)
            )
            evaluations.append(
                RecurrenceEvaluation(
                    policy=policy,
                    family=record.family,
                    kind=record.truth.kind,
                    pixel_support_status=record.pixel_support_status,
                    truth_status=record.truth.status,
                    predicted_status=predicted_status,
                    exact_latest_dates=exact_latest_dates,
                )
            )
    return evaluations


def _subgroup_metrics(sub_rows: Sequence[RecurrenceEvaluation]) -> dict[str, int | float]:
    """Calculate recurrence metrics for a subset of evaluation rows."""
    fp_rows = [e for e in sub_rows if e.truth_status in ("interval", "unresolved")]
    fp_n = len(fp_rows)
    fp_k = sum(1 for e in fp_rows if e.predicted_status == "point")
    fp_rate = float(fp_k / fp_n) if fp_n > 0 else 0.0

    fr_rows = [e for e in sub_rows if e.truth_status == "unresolved"]
    fr_n = len(fr_rows)
    fr_k = sum(1 for e in fr_rows if e.predicted_status in ("point", "interval"))
    fr_rate = float(fr_k / fr_n) if fr_n > 0 else 0.0

    gen_rows = [e for e in sub_rows if e.truth_status in ("point", "interval")]
    gen_n = len(gen_rows)
    gen_acc = (
        float(sum(1 for e in gen_rows if e.predicted_status == e.truth_status) / gen_n)
        if gen_n > 0
        else 0.0
    )
    exact_acc = (
        float(
            sum(
                1
                for e in gen_rows
                if e.predicted_status == e.truth_status and e.exact_latest_dates
            )
            / gen_n
        )
        if gen_n > 0
        else 0.0
    )
    abstention = (
        float(sum(1 for e in fr_rows if e.predicted_status == "unresolved") / fr_n)
        if fr_n > 0
        else 0.0
    )

    return {
        "n": len(sub_rows),
        "false_point_k": fp_k,
        "false_point_n": fp_n,
        "false_point_rate": fp_rate,
        "false_resolution_k": fr_k,
        "false_resolution_n": fr_n,
        "false_resolution_rate": fr_rate,
        "genuine_recurrence_status_accuracy": gen_acc,
        "exact_latest_date_accuracy": exact_acc,
        "conservative_abstention_rate": abstention,
    }


def score_recurrence_policy(
    evaluations: Sequence[RecurrenceEvaluation],
    policy: RecurrencePolicy,
) -> RecurrencePolicyScore:
    """Score a candidate recurrence policy across evaluations."""
    rows = [e for e in evaluations if e.policy == policy]

    fp_rows = [e for e in rows if e.truth_status in ("interval", "unresolved")]
    false_point_n = len(fp_rows)
    false_point_k = sum(1 for e in fp_rows if e.predicted_status == "point")
    false_point_rate = float(false_point_k / false_point_n) if false_point_n > 0 else 0.0
    false_point_wilson = wilson_interval(false_point_k, false_point_n)

    fr_rows = [e for e in rows if e.truth_status == "unresolved"]
    false_resolution_n = len(fr_rows)
    false_resolution_k = sum(1 for e in fr_rows if e.predicted_status in ("point", "interval"))
    false_resolution_rate = (
        float(false_resolution_k / false_resolution_n) if false_resolution_n > 0 else 0.0
    )
    false_resolution_wilson = wilson_interval(false_resolution_k, false_resolution_n)

    gen_rows = [e for e in rows if e.truth_status in ("point", "interval")]
    gen_n = len(gen_rows)
    genuine_recurrence_status_accuracy = (
        float(sum(1 for e in gen_rows if e.predicted_status == e.truth_status) / gen_n)
        if gen_n > 0
        else 0.0
    )
    exact_latest_date_accuracy = (
        float(
            sum(
                1
                for e in gen_rows
                if e.predicted_status == e.truth_status and e.exact_latest_dates
            )
            / gen_n
        )
        if gen_n > 0
        else 0.0
    )
    conservative_abstention_rate = (
        float(sum(1 for e in fr_rows if e.predicted_status == "unresolved") / false_resolution_n)
        if false_resolution_n > 0
        else 0.0
    )

    by_family = {
        family: _subgroup_metrics([e for e in rows if e.family == family])
        for family in sorted({e.family for e in rows})
    }
    by_kind = {
        kind: _subgroup_metrics([e for e in rows if e.kind == kind])
        for kind in sorted({e.kind for e in rows})
    }
    by_pixel_support = {
        status: _subgroup_metrics([e for e in rows if e.pixel_support_status == status])
        for status in sorted({e.pixel_support_status for e in rows})
    }

    return RecurrencePolicyScore(
        policy=policy,
        false_point_k=false_point_k,
        false_point_n=false_point_n,
        false_point_rate=false_point_rate,
        false_point_wilson=false_point_wilson,
        false_resolution_k=false_resolution_k,
        false_resolution_n=false_resolution_n,
        false_resolution_rate=false_resolution_rate,
        false_resolution_wilson=false_resolution_wilson,
        genuine_recurrence_status_accuracy=genuine_recurrence_status_accuracy,
        exact_latest_date_accuracy=exact_latest_date_accuracy,
        conservative_abstention_rate=conservative_abstention_rate,
        by_family=by_family,
        by_kind=by_kind,
        by_pixel_support=by_pixel_support,
    )


def select_recurrence_policy(
    evaluations: Sequence[RecurrenceEvaluation],
) -> tuple[RecurrencePolicy, RecurrencePolicyScore, dict[str, int]]:
    """Select the best recurrence policy using two-stage Wilson safety gates and lexicographic ranking."""
    scores = [
        score_recurrence_policy(evaluations, policy) for policy in ELIGIBLE_RECURRENCE_POLICIES
    ]
    survivors = [score for score in scores if score.false_point_wilson[1] <= 0.05]
    counts = {"candidates": len(scores), "false_point_wilson": len(survivors)}
    survivors = [score for score in survivors if score.false_resolution_wilson[1] <= 0.05]
    counts["false_resolution_wilson"] = len(survivors)
    if not survivors:
        raise RuntimeError("no recurrence policy satisfies both false-precision safety gates")
    for name in (
        "exact_latest_date_accuracy",
        "genuine_recurrence_status_accuracy",
        "conservative_abstention_rate",
    ):
        best = max(getattr(score, name) for score in survivors)
        survivors = [score for score in survivors if np.isclose(getattr(score, name), best)]
        counts[name] = len(survivors)
    rank = {policy: index for index, policy in enumerate(ELIGIBLE_RECURRENCE_POLICIES)}
    selected = min(survivors, key=lambda score: rank[score.policy])
    counts["conservative_policy_order"] = 1
    return selected.policy, selected, counts


def recurrence_fingerprint(
    policy: RecurrencePolicy | str,
    *,
    seeds: Iterable[int],
    metrics: Mapping[str, Any] | RecurrencePolicyScore,
    authority_scope: str = "candidate_for_established_0_2_0",
) -> str:
    """Hash code, seeds, metrics, policy, and authority scope into a 64-char hex SHA-256 fingerprint."""
    hasher = hashlib.sha256()
    for item in (
        recurrence_synthetic.RecurrenceTruth,
        recurrence_synthetic.RecurrenceSyntheticRecord,
        recurrence_synthetic.generate_recurrence_record,
        recurrence_metrics.narrow_most_recent_recurrence,
        recurrence_metrics._clusters,
        recurrence_metrics._covers,
        RecurrenceEvaluation,
        RecurrencePolicyScore,
        evaluate_recurrence_records,
        score_recurrence_policy,
        select_recurrence_policy,
    ):
        hasher.update(inspect.getsource(item).encode("utf-8"))
    hasher.update(json.dumps(list(seeds)).encode("utf-8"))
    metrics_payload = asdict(metrics) if is_dataclass(metrics) else metrics
    hasher.update(json.dumps(metrics_payload, sort_keys=True).encode("utf-8"))
    hasher.update(policy.encode("utf-8"))
    hasher.update(authority_scope.encode("utf-8"))
    return hasher.hexdigest()


def legacy_last_cluster(
    dates: Sequence[pd.Timestamp], *, max_boundary_interval_months: int
) -> tuple[pd.Timestamp, ...]:
    ordered = tuple(sorted(pd.Timestamp(value) for value in dates))
    if len(ordered) <= 1:
        return ordered
    clusters = recurrence_metrics._clusters(
        ordered, max_gap=max_boundary_interval_months
    )
    latest = clusters[-1]
    return latest if recurrence_metrics._resolved(
        latest, limit=max_boundary_interval_months
    ) else ordered


def evaluate_legacy_records(
    records: Iterable[RecurrenceSyntheticRecord],
    *,
    policy: str = "legacy_last_cluster_report_only",
) -> list[RecurrenceEvaluation]:
    """Evaluate synthetic records against the legacy last-cluster policy for reporting."""
    evaluations: list[RecurrenceEvaluation] = []
    for record in records:
        result = assess_window_timing(
            record.values,
            record.rows,
            thresholds=record.thresholds,
            measurement_tolerance_pct=record.measurement_tolerance_pct,
            noise_pp=record.noise_pp,
            pixel_support_status=record.pixel_support_status,
            recurrence_policy="no_narrowing",
            window_start=record.window_start,
            window_end=record.window_end,
        )
        peak_dates = result.peak_dates
        peak_status = result.peak_status
        if peak_status == "unresolved" and len(peak_dates) > 0:
            narrowed = legacy_last_cluster(
                peak_dates,
                max_boundary_interval_months=record.thresholds.max_boundary_interval_months,
            )
            if narrowed != peak_dates:
                narrowed_status = _window_status(narrowed, record.thresholds)
                if narrowed_status != "unresolved":
                    peak_dates, peak_status = narrowed, narrowed_status

        trough_dates = result.trough_dates
        trough_status = result.trough_status
        if trough_status == "unresolved" and len(trough_dates) > 0:
            narrowed = legacy_last_cluster(
                trough_dates,
                max_boundary_interval_months=record.thresholds.max_boundary_interval_months,
            )
            if narrowed != trough_dates:
                narrowed_status = _window_status(narrowed, record.thresholds)
                if narrowed_status != "unresolved":
                    trough_dates, trough_status = narrowed, narrowed_status

        if record.truth.kind == "peak":
            predicted_status = peak_status
            predicted_dates = peak_dates
        else:
            predicted_status = trough_status
            predicted_dates = trough_dates

        exact_latest_dates = bool(
            record.truth.status in {"point", "interval"}
            and tuple(predicted_dates) == tuple(record.truth.latest_dates)
        )
        evaluations.append(
            RecurrenceEvaluation(
                policy=policy,  # type: ignore[arg-type]
                family=record.family,
                kind=record.truth.kind,
                pixel_support_status=record.pixel_support_status,
                truth_status=record.truth.status,
                predicted_status=predicted_status,
                exact_latest_dates=exact_latest_dates,
            )
        )
    return evaluations


__all__ = [
    "RECURRENCE_AUTHORITY_SCOPE",
    "RecurrenceEvaluation",
    "RecurrencePolicyScore",
    "evaluate_legacy_records",
    "evaluate_recurrence_records",
    "legacy_last_cluster",
    "recurrence_fingerprint",
    "score_recurrence_policy",
    "select_recurrence_policy",
]
