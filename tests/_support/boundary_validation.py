from __future__ import annotations

import numpy as np
import pandas as pd


def month_delta(left: pd.Series, right: pd.Series) -> pd.Series:
    left = pd.to_datetime(left)
    right = pd.to_datetime(right)
    return (left.dt.year - right.dt.year) * 12 + left.dt.month - right.dt.month


def align_events_by_interval(truth: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    """Match each truth event to the nearest actual date inside its cycle interval.

    Intervals are half-open ``(interval_start, interval_end]``: the previous
    cycle's own boundary month (``interval_start``) is excluded so it is never
    double-counted against two consecutive events, but ``interval_end`` is
    included because it IS this event's target boundary month -- an exact
    match there must count as resolved, not be excluded by its own target date.
    """
    rows = []
    actual_dates = pd.to_datetime(actual["actual_month"]).dropna()
    for row in truth.itertuples(index=False):
        candidates = actual_dates.loc[actual_dates.gt(row.interval_start) & actual_dates.le(row.interval_end)]
        chosen = pd.NaT
        if len(candidates):
            delta = (candidates - row.truth_month).abs()
            chosen = pd.Timestamp(candidates.loc[delta.idxmin()])
        rows.append({"event_id": row.event_id, "truth_month": row.truth_month, "actual_month": chosen})
    return pd.DataFrame(rows)


def summarize_timing(aligned: pd.DataFrame) -> dict[str, float | int]:
    required = {"truth_month", "actual_month"}
    if not required.issubset(aligned.columns):
        raise ValueError(f"aligned events require columns {sorted(required)}")
    eligible = aligned["truth_month"].notna()
    resolved = eligible & aligned["actual_month"].notna()
    signed = month_delta(
        aligned.loc[resolved, "actual_month"],
        aligned.loc[resolved, "truth_month"],
    ).astype(float)
    absolute = signed.abs()
    n_eligible = int(eligible.sum())
    n_resolved = int(resolved.sum())
    within = int((absolute <= 1).sum())
    penalized = pd.Series(12.0, index=aligned.index[eligible], dtype=float)
    penalized.loc[resolved] = absolute
    return {
        "n_eligible": n_eligible,
        "n_resolved": n_resolved,
        "coverage": n_resolved / n_eligible if n_eligible else np.nan,
        "within_1_month": within / n_eligible if n_eligible else np.nan,
        "signed_bias_months": float(signed.mean()) if len(signed) else np.nan,
        "resolved_mae_months": float(absolute.mean()) if len(absolute) else np.nan,
        "total_mae_months": float(penalized.mean()) if n_eligible else np.nan,
        "median_abs_error_months": float(penalized.median()) if n_eligible else np.nan,
        "p90_abs_error_months": float(penalized.quantile(0.90)) if n_eligible else np.nan,
        "max_abs_error_months": float(penalized.max()) if n_eligible else np.nan,
    }
