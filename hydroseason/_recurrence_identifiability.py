"""Pure policy for identifying annual recurrence in equivalent-extremum dates."""

from __future__ import annotations

from numbers import Integral
from typing import Literal, cast

import pandas as pd

from ._circular_timing import linear_span_months

RecurrencePolicy = Literal[
    "no_narrowing",
    "long_window_last_cluster",
    "annual_shape_match",
]

ELIGIBLE_RECURRENCE_POLICIES: tuple[RecurrencePolicy, ...] = (
    "no_narrowing",
    "annual_shape_match",
    "long_window_last_cluster",
)


def _month_start(value: pd.Timestamp, *, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp != stamp.to_period("M").to_timestamp():
        raise ValueError(f"{name} must be a month-start timestamp.")
    return stamp


def _clusters(dates: tuple[pd.Timestamp, ...], *, max_gap: int) -> list[tuple[pd.Timestamp, ...]]:
    ordered = sorted(pd.Timestamp(date) for date in dates)
    if not ordered:
        return []
    result: list[list[pd.Timestamp]] = [[ordered[0]]]
    for date in ordered[1:]:
        gap = linear_span_months((result[-1][-1], date))
        if gap is not None and gap <= max_gap:
            result[-1].append(date)
        else:
            result.append([date])
    return [tuple(cluster) for cluster in result]


def _resolved(cluster: tuple[pd.Timestamp, ...], *, limit: int) -> bool:
    span = linear_span_months(cluster)
    return span is not None and span <= limit


def _covers(left: tuple[pd.Timestamp, ...], right: tuple[pd.Timestamp, ...], *, limit: int) -> bool:
    return all(
        any(linear_span_months((item, candidate)) <= limit for candidate in right) for item in left
    )


def narrow_most_recent_recurrence(
    dates: tuple[pd.Timestamp, ...],
    *,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    max_boundary_interval_months: int,
    policy: RecurrencePolicy,
) -> tuple[pd.Timestamp, ...]:
    """Return dates unchanged unless ``policy`` proves an annual recurrence."""
    if policy not in ELIGIBLE_RECURRENCE_POLICIES:
        raise ValueError(f"unknown recurrence policy: {policy!r}")
    if (
        isinstance(max_boundary_interval_months, bool)
        or not isinstance(max_boundary_interval_months, Integral)
        or max_boundary_interval_months < 0
    ):
        raise ValueError("max_boundary_interval_months must be a non-negative integer.")
    start = _month_start(window_start, name="window_start")
    end = _month_start(window_end, name="window_end")
    if end < start:
        raise ValueError("window_end must not precede window_start.")
    if policy == "no_narrowing" or len(dates) < 2:
        return dates
    window_span = linear_span_months((start, end))
    if window_span is None or window_span < 12:
        return dates
    clusters = _clusters(dates, max_gap=int(max_boundary_interval_months))
    if len(clusters) < 2:
        return dates
    previous, latest = clusters[-2], clusters[-1]
    if not _resolved(latest, limit=int(max_boundary_interval_months)):
        return dates
    if policy == "long_window_last_cluster":
        return latest
    if not _resolved(previous, limit=int(max_boundary_interval_months)):
        return dates
    shifted = tuple(date + pd.DateOffset(months=12) for date in previous)
    limit = int(max_boundary_interval_months)
    if linear_span_months(shifted) != linear_span_months(latest):
        return dates
    if not (_covers(shifted, latest, limit=limit) and _covers(latest, shifted, limit=limit)):
        return dates
    return cast(tuple[pd.Timestamp, ...], latest)
