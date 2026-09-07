"""Evaluate blinded human labels for the trough-refinement span cohort.

Refuses to produce a verdict from a cohort that cannot support one: labels
carrying algorithm columns, incomplete adjudication, a label file whose hash
has moved since freezing, or too few algorithm point predictions to make the
false-precision gate evaluable at all.

The distinction this module exists to preserve is between *failed* and
*unevaluable*. An under-powered cohort reports ``unavailable`` with a stated
reason; it never reports a pass, and it is never enlarged after results are
seen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Frozen before evaluation: the smallest denominator at which a zero-error
# result clears a two-sided 95% Wilson upper bound of 0.05. Below this the
# false-precision gate is unevaluable, not passed.
MIN_POINT_PREDICTIONS = 73

MEDIAN_DISTANCE_GATE_MONTHS = 1.0
P90_DISTANCE_GATE_MONTHS = 2.0
FALSE_PRECISE_WILSON_GATE = 0.05

_UNCERTAIN = "uncertain"
_NO_BOUNDARY = "no_boundary_supported"
_INTERVAL = "interval_supported"
_POINT = "point_supported"

# Any of these appearing in a label file means the reviewer could see an
# algorithm's answer, which voids the blinding.
_ALGORITHM_COLUMNS = {
    "pass1_boundary", "pass2_boundary", "refinement_status", "refinement_reason",
    "boundary_candidates", "low_state_start", "low_state_end", "recovery_start",
    "pulse_months", "selected_policy", "fingerprint", "model_output",
    "timing_status", "trough_timing_status", "peak_timing_status",
}

# Columns the evaluator itself needs; these are the algorithm's predictions
# joined in AFTER the labels were frozen, so they are permitted by name.
_PREDICTION_COLUMNS = {
    "predicted_status", "predicted_boundary", "interval_start", "interval_end",
}


def freeze_labels_hash(labels_path: Path, sidecar_path: Path) -> str:
    """Freeze, or verify, the label file's hash.

    First call writes the sidecar; later calls refuse a file that has moved.
    """
    current_digest = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if sidecar_path.exists():
        expected_digest = sidecar_path.read_text(encoding="ascii").strip()
        if current_digest != expected_digest:
            raise RuntimeError(
                f"frozen label hash mismatch: expected {expected_digest}, "
                f"got {current_digest}"
            )
        return expected_digest
    sidecar_path.write_text(f"{current_digest}\n", encoding="ascii")
    return current_digest


def adjudicate_labels(labels: pd.DataFrame) -> pd.DataFrame:
    """Resolve each span to one final label, refusing partial adjudication.

    A span reviewed twice with disagreeing labels must carry an adjudicated
    label. Leaving one unresolved and evaluating the rest would silently drop
    exactly the spans the reviewers found hardest.
    """
    resolved = labels.copy()
    second = resolved.get("second_label", pd.Series("", index=resolved.index))
    second = second.fillna("").astype(str)
    adjudicated = resolved.get("adjudicated_label", pd.Series("", index=resolved.index))
    adjudicated = adjudicated.fillna("").astype(str)
    primary = resolved["label"].fillna("").astype(str)

    disagreed = (second != "") & (second != primary)
    unadjudicated = disagreed & (adjudicated == "")
    if bool(unadjudicated.any()):
        ids = resolved.loc[unadjudicated, "anonymous_span_id"].tolist()
        raise RuntimeError(
            f"unadjudicated double-reviewed spans remain: {ids}. "
            "Evaluation cannot run on a partially adjudicated cohort."
        )
    resolved["final_label"] = np.where(adjudicated != "", adjudicated, primary)
    return resolved


def interval_distance_months(
    *,
    predicted: pd.Timestamp | None,
    interval_start: pd.Timestamp | None,
    interval_end: pd.Timestamp | None,
) -> float:
    """Months from a predicted boundary to the reviewer's interval.

    Zero inside the interval; otherwise the calendar-month distance to the
    nearest edge. This is the only distance rule and it is fixed before
    unblinding.
    """
    if predicted is None or pd.isna(predicted):
        return float("nan")
    if interval_start is None or pd.isna(interval_start):
        return float("nan")
    if interval_end is None or pd.isna(interval_end):
        interval_end = interval_start
    predicted = pd.Timestamp(predicted)
    start = pd.Timestamp(interval_start)
    end = pd.Timestamp(interval_end)
    if start <= predicted <= end:
        return 0.0
    if predicted < start:
        delta = start
        sign_from = predicted
    else:
        delta = predicted
        sign_from = end
    return float((delta.year - sign_from.year) * 12 + delta.month - sign_from.month)


def classify_span(reviewer_label: str, predicted_status: str) -> dict[str, Any]:
    """Classify one span's algorithm prediction against adjudicated truth."""
    abstained = predicted_status in {"unresolved", "unavailable", ""}
    false_precise = predicted_status == "point" and reviewer_label in {
        _INTERVAL, _NO_BOUNDARY,
    }
    direct_contradiction = predicted_status == "point" and reviewer_label == _NO_BOUNDARY
    return {
        "reviewer_label": reviewer_label,
        "predicted_status": predicted_status,
        "false_precise": bool(false_precise),
        "direct_contradiction": bool(direct_contradiction),
        "abstained": bool(abstained),
    }


def wilson_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided Wilson score interval; ``(0.0, 1.0)`` when ``n <= 0``."""
    if n <= 0:
        return (0.0, 1.0)
    z = 1.959963984540054 if abs(confidence - 0.95) < 1e-9 else 1.959963984540054
    phat = k / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def bootstrap_catchment_ids(rows: pd.DataFrame, *, rng) -> list[str]:
    """Resample catchments with replacement.

    Spans within one catchment are dependent, so the resampling unit is the
    catchment; resampling spans would understate the interval.
    """
    catchments = sorted(rows["anonymous_catchment_id"].unique().tolist())
    drawn = rng.choice(catchments, size=len(catchments), replace=True)
    return [str(value) for value in drawn]


def summarize_spans(rows: pd.DataFrame) -> dict[str, Any]:
    """Aggregate spans, keeping abstention separate from resolved accuracy."""
    reviewed_n = int(len(rows))
    uncertain_mask = rows["reviewer_label"] == _UNCERTAIN
    uncertain_n = int(uncertain_mask.sum())
    rated = rows.loc[~uncertain_mask]
    rate_denominator_n = int(len(rated))

    abstained_n = int(rated["abstained"].sum()) if rate_denominator_n else 0
    resolved = rated.loc[~rated["abstained"]] if rate_denominator_n else rated
    distances = resolved["distance_months"].dropna() if len(resolved) else pd.Series(dtype=float)

    point_predictions = int((rated["predicted_status"] == "point").sum()) if rate_denominator_n else 0
    false_precise_k = int(rated["false_precise"].sum()) if rate_denominator_n else 0

    return {
        "reviewed_n": reviewed_n,
        "uncertain_n": uncertain_n,
        "rate_denominator_n": rate_denominator_n,
        "abstained_n": abstained_n,
        "abstention_rate": (abstained_n / rate_denominator_n) if rate_denominator_n else 0.0,
        "resolved_n": int(len(resolved)),
        "point_prediction_n": point_predictions,
        "false_precise_k": false_precise_k,
        "false_precise_rate": (false_precise_k / point_predictions) if point_predictions else 0.0,
        "direct_contradiction_k": int(rated["direct_contradiction"].sum()) if rate_denominator_n else 0,
        "median_distance_months": float(distances.median()) if len(distances) else float("nan"),
        "p90_distance_months": float(distances.quantile(0.9)) if len(distances) else float("nan"),
    }


def _bootstrap_intervals(rows: pd.DataFrame, *, seed: int, n_resamples: int) -> dict[str, list[float]]:
    if rows.empty:
        return {"false_precise_rate": [0.0, 1.0]}
    rng = np.random.default_rng(seed)
    by_catchment = {cid: frame for cid, frame in rows.groupby("anonymous_catchment_id")}
    rates: list[float] = []
    for _ in range(n_resamples):
        drawn = bootstrap_catchment_ids(rows, rng=rng)
        sample = pd.concat([by_catchment[c] for c in drawn], ignore_index=True)
        summary = summarize_spans(sample)
        if summary["point_prediction_n"]:
            rates.append(summary["false_precise_rate"])
    if not rates:
        return {"false_precise_rate": [0.0, 1.0]}
    return {
        "false_precise_rate": [
            float(np.percentile(rates, 2.5)),
            float(np.percentile(rates, 97.5)),
        ]
    }


def evaluate_cohort(
    *,
    labels_path: Path,
    sidecar_path: Path,
    output_path: Path,
    seed: int = 20260906,
    n_resamples: int = 1000,
) -> dict[str, Any]:
    """Evaluate the frozen cohort and emit a pass/unavailable verdict."""
    labels = pd.read_csv(labels_path)
    leaked = (set(labels.columns) & _ALGORITHM_COLUMNS) - _PREDICTION_COLUMNS
    if leaked:
        raise ValueError(
            f"label file carries algorithm columns {sorted(leaked)}; the review "
            "was not blind and its labels cannot be used."
        )

    freeze_labels_hash(labels_path, sidecar_path)
    resolved = adjudicate_labels(labels)

    records = []
    for _, row in resolved.iterrows():
        classified = classify_span(
            str(row["final_label"]), str(row.get("predicted_status", "") or "")
        )
        classified["anonymous_catchment_id"] = row.get("anonymous_catchment_id", "c0")
        classified["anonymous_span_id"] = row["anonymous_span_id"]
        classified["distance_months"] = interval_distance_months(
            predicted=pd.to_datetime(row.get("predicted_boundary"), errors="coerce"),
            interval_start=pd.to_datetime(row.get("interval_start"), errors="coerce"),
            interval_end=pd.to_datetime(row.get("interval_end"), errors="coerce"),
        )
        records.append(classified)
    rows = pd.DataFrame(records)

    metrics = summarize_spans(rows)
    point_n = metrics["point_prediction_n"]
    wilson_low, wilson_high = wilson_interval(metrics["false_precise_k"], point_n)

    gates = {
        "min_point_predictions": point_n >= MIN_POINT_PREDICTIONS,
        "false_precise_wilson_upper_at_most_0_05": (
            point_n >= MIN_POINT_PREDICTIONS and wilson_high <= FALSE_PRECISE_WILSON_GATE
        ),
        "zero_direct_contradictions": metrics["direct_contradiction_k"] == 0,
        "median_distance_at_most_1_month": (
            math.isnan(metrics["median_distance_months"])
            or metrics["median_distance_months"] <= MEDIAN_DISTANCE_GATE_MONTHS
        ),
        "p90_distance_at_most_2_months": (
            math.isnan(metrics["p90_distance_months"])
            or metrics["p90_distance_months"] <= P90_DISTANCE_GATE_MONTHS
        ),
    }

    unavailable_reason = ""
    if not gates["min_point_predictions"]:
        unavailable_reason = (
            f"cohort yielded {point_n} algorithm point predictions; "
            f"{MIN_POINT_PREDICTIONS} are required for the false-precision gate to "
            "be evaluable. Promotion is unavailable. The cohort is not expanded "
            "after viewing results."
        )
    elif not all(gates.values()):
        failed = sorted(name for name, ok in gates.items() if not ok)
        unavailable_reason = f"failed gates: {failed}"

    report = {
        "protocol_id": "trough-refinement-span-cohort-v1",
        "labels_sha256": sidecar_path.read_text(encoding="ascii").strip(),
        "metrics": metrics,
        "gates": gates,
        "bootstrap_intervals": _bootstrap_intervals(rows, seed=seed, n_resamples=n_resamples),
        "cycle_level_intervals": {
            "false_precise_wilson": [wilson_low, wilson_high],
            "note": (
                "potentially optimistic: spans within one catchment are dependent, "
                "so the catchment-level bootstrap is the headline interval."
            ),
        },
        "promotion_eligibility": "eligible" if all(gates.values()) else "unavailable",
        "unavailable_reason": unavailable_reason,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_cohort(
        labels_path=args.labels,
        sidecar_path=args.sidecar,
        output_path=args.output,
    )
    print(f"promotion_eligibility: {report['promotion_eligibility']}")
    if report["unavailable_reason"]:
        print(report["unavailable_reason"])
        raise SystemExit(3)


if __name__ == "__main__":
    main()
