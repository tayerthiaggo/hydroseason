"""Canonical extent fingerprinting for HydroSeason."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["canonical_extent_payload", "extent_fingerprint"]

_SCIENTIFIC_COLUMNS = (
    "extent_pct",
    "invalid_pct",
    "n_water",
    "n_valid",
    "n_invalid",
    "n_aoi",
)
_SCHEMA_PREFIX = "hydroseason-extent-v1\n"
_COUNT_COLUMNS = frozenset({"n_water", "n_valid", "n_invalid", "n_aoi"})


def _format_canonical_value(val: Any, *, is_count: bool) -> str:
    if val is None or pd.isna(val):
        return "null"
    if isinstance(val, (bool, np.bool_)):
        return "true" if val else "false"
    if isinstance(val, (int, np.integer)):
        return str(int(val))
    if isinstance(val, (float, np.floating)):
        f = float(val)
        if math.isnan(f):
            return "null"
        if math.isinf(f):
            return "Infinity" if f > 0 else "-Infinity"
        if f == 0.0:
            f = 0.0
        if is_count and f.is_integer():
            return str(int(f))
        return repr(f)
    try:
        f = float(val)
        if math.isnan(f):
            return "null"
        if f == 0.0:
            f = 0.0
        if is_count and f.is_integer():
            return str(int(f))
        return repr(f)
    except (ValueError, TypeError):
        return str(val)


def canonical_extent_payload(
    extent: pd.DataFrame | pd.Series,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
) -> str:
    """Build the normalized, deterministic string payload for an extent table."""
    if isinstance(extent, pd.Series):
        frame = extent.to_frame(name=value_col)
    elif isinstance(extent, pd.DataFrame):
        frame = extent.copy()
    else:
        frame = pd.DataFrame(extent)

    if date_col is not None:
        if date_col not in frame.columns:
            raise ValueError(f"date_col {date_col!r} not found in columns.")
        raw_dates = frame.pop(date_col)
    elif not isinstance(frame.index, pd.DatetimeIndex) and "date" in frame.columns:
        raw_dates = frame.pop("date")
    else:
        raw_dates = frame.index

    # Parse and normalize to UTC-naive month-start timestamps
    parsed = pd.to_datetime(raw_dates)
    if getattr(parsed, "tz", None) is not None:
        parsed = parsed.tz_convert("UTC").tz_localize(None)
    elif getattr(getattr(parsed, "dt", None), "tz", None) is not None:
        parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)

    month_starts = pd.DatetimeIndex([
        pd.Timestamp(dt).replace(day=1, hour=0, minute=0, second=0, microsecond=0, nanosecond=0)
        for dt in parsed
    ])

    if month_starts.isna().any():
        raise ValueError("extent dates contain null or invalid timestamps.")

    if month_starts.has_duplicates:
        dups = sorted(month_starts[month_starts.duplicated(keep=False)].strftime("%Y-%m").unique())
        raise ValueError(f"extent contains duplicate month timestamps: {dups}.")

    # Map/rename value_col to extent_pct if different
    if value_col != "extent_pct" and value_col in frame.columns:
        frame["extent_pct"] = frame.pop(value_col)

    # Filter to included scientific columns in canonical order
    included_cols = [col for col in _SCIENTIFIC_COLUMNS if col in frame.columns]

    # Set normalized dates and sort by timestamp
    frame = frame[included_cols].copy()
    frame.index = month_starts
    frame = frame.sort_index()

    # Build lines
    lines = [_SCHEMA_PREFIX.rstrip("\n")]
    header = ["date"] + included_cols
    lines.append(",".join(header))

    for dt, row in zip(frame.index, frame.itertuples(index=False), strict=False):
        date_str = dt.strftime("%Y-%m-%d")
        row_vals = [date_str]
        for col_name, val in zip(included_cols, row, strict=False):
            is_count = col_name in _COUNT_COLUMNS
            row_vals.append(_format_canonical_value(val, is_count=is_count))
        lines.append(",".join(row_vals))

    return "\n".join(lines) + "\n"


def extent_fingerprint(
    extent: pd.DataFrame | pd.Series,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
) -> str:
    """Compute the SHA-256 fingerprint of the canonically normalized extent table."""
    payload = canonical_extent_payload(extent, value_col=value_col, date_col=date_col)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()