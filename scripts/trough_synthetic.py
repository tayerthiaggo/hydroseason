"""Known-truth monthly extent records for trough-recurrence checks.

Every construction has 12 calendar months per year. Values are percent of a
fixed footprint. Nothing here is a hydrological model; the constructions exist
so that the true trough timing is known before any method sees the record.

The ``stable`` construction at ``seed=0`` with ``flood_rate=0.3`` reproduces the
record in section 4 of docs/provisional-trough-judgement-2026-10-30.md exactly:
the random draws happen in the same order.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CONSTRUCTIONS = ("stable", "stable_sharp", "drift", "plateau", "flat", "uniform")
GAP_MODES = (None, "random20", "dry20", "wet20")

_BASE_LOW = 15.0
_BASE_SPREAD = 5.0
_TROUGH_VALUE = 10.0
_PEAK_VALUE = 25.0
_FLOOD_LOW = 40.0
_FLOOD_HIGH = 70.0
_SEPTEMBER = 8  # zero-based month index
_PLATEAU = slice(6, 10)  # July to October, zero-based
_DRY_MONTHS = (7, 8, 9, 10)  # calendar months
_WET_MONTHS = (12, 1, 2, 3)  # calendar months
_N_AOI = 1000


def build_record(
    kind: str,
    *,
    seed: int = 0,
    years: int = 12,
    flood_rate: float = 0.3,
    gap: str | None = None,
    counts: bool = False,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Return ``(values, frame)``: the gap-free truth and the record to analyse.

    ``stable``: September is the unique minimum every year; other months are
    noise, so the annual peak is a broad set of near-tied months.
    ``stable_sharp``: as ``stable`` plus one sharp peak in a random non-September
    month each year, so the peak set is a single month.
    ``drift``: one random month per year is the minimum.
    ``plateau``: July to October are all near the minimum.
    ``flat``: noise only, range 0.5 pp.
    ``uniform``: one random trough month and one random peak month per year.

    ``flood_rate`` is the per-year probability of one large flood in a month
    other than September. ``gap`` drops 20 percent of months at random
    (``random20``), 20 percent of July to October months (``dry20``) or 20
    percent of December to March months (``wet20``) by setting ``extent_pct`` to
    NaN and ``invalid_pct`` to 100. ``counts=True`` attaches
    pixel counts consistent with the extent on a 1000-pixel footprint.
    """
    if kind not in CONSTRUCTIONS:
        raise ValueError(f"kind must be one of {CONSTRUCTIONS}, got {kind!r}.")
    if gap not in GAP_MODES:
        raise ValueError(f"gap must be one of {GAP_MODES}, got {gap!r}.")

    rng = np.random.default_rng(seed)
    values = _BASE_LOW + rng.uniform(0.0, _BASE_SPREAD, size=(years, 12))
    if kind == "stable":
        values[:, _SEPTEMBER] = _TROUGH_VALUE
    elif kind == "stable_sharp":
        values[:, _SEPTEMBER] = _TROUGH_VALUE
        for year in range(years):
            month = int(rng.choice([m for m in range(12) if m != _SEPTEMBER]))
            values[year, month] = _PEAK_VALUE
    elif kind == "drift":
        for year in range(years):
            values[year, int(rng.integers(0, 12))] = _TROUGH_VALUE
    elif kind == "plateau":
        values[:, _PLATEAU] = _TROUGH_VALUE + rng.uniform(0.0, 0.3, size=(years, 4))
    elif kind == "flat":
        values[:] = _BASE_LOW + rng.uniform(0.0, 0.5, size=(years, 12))
    elif kind == "uniform":
        for year in range(years):
            trough, peak = rng.choice(12, size=2, replace=False)
            values[year, trough] = _TROUGH_VALUE
            values[year, peak] = _PEAK_VALUE

    if flood_rate > 0.0:
        other = [month for month in range(12) if month != _SEPTEMBER]
        for year in range(years):
            if rng.random() < flood_rate:
                month = int(rng.choice(other))
                values[year, month] += rng.uniform(_FLOOD_LOW, _FLOOD_HIGH)

    index = pd.date_range("2000-01-01", periods=12 * years, freq="MS")
    frame = pd.DataFrame({"extent_pct": values.ravel(), "invalid_pct": 0.0}, index=index)

    if gap == "random20":
        dropped = rng.random(len(frame)) < 0.2
    elif gap == "dry20":
        dropped = frame.index.month.isin(_DRY_MONTHS) & (rng.random(len(frame)) < 0.2)
    elif gap == "wet20":
        dropped = frame.index.month.isin(_WET_MONTHS) & (rng.random(len(frame)) < 0.2)
    else:
        dropped = np.zeros(len(frame), dtype=bool)
    frame.loc[dropped, "extent_pct"] = np.nan
    frame.loc[dropped, "invalid_pct"] = 100.0

    if counts:
        n_valid = np.where(dropped, 0, _N_AOI)
        frame["n_aoi"] = _N_AOI
        frame["n_valid"] = n_valid
        frame["n_invalid"] = _N_AOI - n_valid
        water = frame["extent_pct"].fillna(0.0).to_numpy() / 100.0 * n_valid
        frame["n_water"] = np.round(water).astype(int)

    return values, frame


def truth_trough_months(values: np.ndarray) -> list[int]:
    """One-based calendar month of each year's minimum in the gap-free truth."""
    return (np.argmin(values, axis=1) + 1).tolist()
