"""Stage 0 of the clock-anchor thread: does a frozen rise rule agree across tiles?

Reads hydropools' historical HydroSeason outputs read-only (per tile:
``channel_monthly_extent.csv`` and ``*_hydro_years.csv``) and the hydropools
output manifest (channel pixel counts). For every tile-year it locates the
first sustained departure from the trough band under ``RULE`` and scores how
well tiles agree on that month, against the end-dry hydropools uses today.

``RULE``, ``MARGIN`` and ``VARIANTS`` are frozen before any real data is read
(see docs/superpowers/plans/2026-10-30-clock-anchor-stage0.md, Task 7). They
are not method thresholds and nothing in ``hydroseason/`` uses them.

Example:

    .venv/Scripts/python.exe scripts/clock_anchor_stage0.py \
        --hydroseason-dir D:/RLH/5.6/repos/hydropools/work/rerun/fitzroy/hydroseason \
        --manifest D:/RLH/5.6/repos/hydropools/outputs/rerun/fitzroy/manifest.json \
        --out dev/reports/2026-10-30-clock-anchor-stage0.csv \
        --summary dev/reports/2026-10-30-clock-anchor-stage0.md \
        --receipt dev/reports/2026-10-30-clock-anchor-stage0.json
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RULE = {
    "version": "stage0_rise_v1",
    "extent": "valid_denominator: extent_pct / (1 - invalid_pct / 100)",
    "level": "median of the valid-denominator extent over the trough band "
    "(trough_interval_start_date..trough_interval_end_date, else the boundary month)",
    "floor_pp_min": 1.0,
    "threshold": "level + max(detectability_floor_pp, floor_pp_min)",
    "search": "months after trough_boundary_date up to and including the window end",
    "window_end": "next cycle's peak_date, else its peak_interval_start_date, "
    "else its trough_boundary_date",
    "confirm_max_gap_months": 2,
    "confirmation": "the next observed month, at most confirm_max_gap_months later and "
    "inside the window, must also exceed the threshold; a single exceedance followed by a "
    "return below it is a pulse and the search continues",
    "status": {
        "point": "confirmed, and the calendar month before the rise month was observed below "
        "the threshold",
        "interval": "confirmed, but the last observed low month is more than one month "
        "earlier (or the boundary month itself was unobserved); interval = "
        "[last low month + 1, rise month]",
        "unconfirmed": "an exceedance with no following observation inside the window within "
        "confirm_max_gap_months",
        "no_rise": "nothing exceeds the threshold before the window end",
        "no_observed_months": "no observed month between the boundary and the window end",
        "no_band_level": "no observed month inside the trough band",
        "no_window": "no boundary, no following cycle, or a window end at or before the boundary",
    },
    "scored_month": "the rise month (first observed exceedance; the interval's end)",
    "scored_statuses": ["point", "interval"],
}

MARGIN = {
    "min_within_1": 0.90,
    "min_gain_over_end_dry": 0.05,
    "min_coverage": 0.90,
    "big_tile_min_px": 3000,
    "min_other_tiles": 3,
    "min_scored_tile_years": 500,
    "hy_first": 1988,
    "hy_last": 2025,
    "primary_metric": "pooled share of big-tile tile-years within +-1 month of the "
    "leave-target-out channel-pixel-weighted median of the same year",
    "coverage": "point + interval over all statuses except no_window, big tiles",
}

HY_DATE_COLUMNS = [
    "trough_boundary_date",
    "trough_interval_start_date",
    "trough_interval_end_date",
    "trough_date",
    "peak_date",
    "peak_interval_start_date",
    "mid_dry_date",
]


def _month_axis(monthly: pd.DataFrame) -> pd.DatetimeIndex:
    stamps = pd.to_datetime(monthly["date"]).dt.to_period("M").dt.to_timestamp()
    return pd.DatetimeIndex(stamps)


def valid_denominator_extent(monthly: pd.DataFrame) -> pd.Series:
    """Hydropools exports 100*wet/n_aoi and 100*(n_aoi-obs)/n_aoi; their quotient is the valid-pixel extent."""
    extent = pd.to_numeric(monthly["extent_pct"], errors="coerce").to_numpy(dtype=float)
    invalid = pd.to_numeric(monthly["invalid_pct"], errors="coerce").to_numpy(dtype=float)
    observed = 1.0 - invalid / 100.0
    with np.errstate(divide="ignore", invalid="ignore"):
        values = np.where(
            np.isfinite(extent) & np.isfinite(observed) & (observed > 0.0),
            extent / observed,
            np.nan,
        )
    return pd.Series(values, index=_month_axis(monthly), name="valid_denominator_extent").sort_index()


def exported_extent(monthly: pd.DataFrame) -> pd.Series:
    """The exported ``extent_pct`` as is (denominator = all footprint pixels)."""
    extent = pd.to_numeric(monthly["extent_pct"], errors="coerce").to_numpy(dtype=float)
    return pd.Series(extent, index=_month_axis(monthly), name="exported_extent").sort_index()


def month_index(stamp) -> int:
    ts = pd.Timestamp(stamp)
    return ts.year * 12 + ts.month - 1


def month_from_index(k: int) -> pd.Timestamp:
    return pd.Timestamp(year=k // 12, month=k % 12 + 1, day=1)


def end_dry_as_run(row: pd.Series) -> pd.Timestamp | None:
    """hydropools ``seasons.dry_windows`` chain: point -> interval end -> boundary. No re-wet guard."""
    if row.get("trough_timing_status") == "point" and pd.notna(row.get("trough_date")):
        return pd.Timestamp(row["trough_date"])
    if pd.notna(row.get("trough_interval_end_date")):
        return pd.Timestamp(row["trough_interval_end_date"])
    if pd.notna(row.get("trough_boundary_date")):
        return pd.Timestamp(row["trough_boundary_date"])
    return None


def weighted_median(values, weights) -> float:
    """First value whose cumulative weight reaches half the total (the proposal's ``sync.py`` rule)."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cumulative, cumulative[-1] / 2.0)])


def leave_one_out_deviations(values, weights, *, min_other: int) -> np.ndarray:
    """Absolute distance of each value from the weighted median of the others; NaN if too few others."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) - 1 < min_other:
        return out
    for i in range(len(values)):
        out[i] = abs(values[i] - weighted_median(np.delete(values, i), np.delete(weights, i)))
    return out
