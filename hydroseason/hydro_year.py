"""Step 4 — Dynamic hydrological year assignment."""

from __future__ import annotations

import numpy as np
import pandas as pd


def assign_hydro_year(date: pd.Timestamp, start_month: int) -> int:
    """Calendar-style hydro year for a single date given a fixed start month."""
    return date.year + 1 if date.month >= start_month else date.year


def assign_fixed_hydro_year(
    df: pd.DataFrame,
    *,
    start_month: int,
    year_col: str = "Year",
    month_col: str = "Month",
    date_col: str = "Date",
    out_col: str = "Hydro_Year_fixed",
) -> pd.DataFrame:
    out = df.copy()
    if date_col not in out.columns:
        out[date_col] = pd.to_datetime(out[[year_col, month_col]].assign(day=1))
    else:
        out[date_col] = pd.to_datetime(out[date_col])
    out[out_col] = out[date_col].map(lambda d: assign_hydro_year(d, start_month))
    return out


def assign_hydro_years(
    df: pd.DataFrame,
    *,
    long_period_threshold: int = 16,
    fallback_month: int = 10,
    hydro_year_start_month: int | None = None,
    onset_window_months: int | None = 1,
    date_col: str = "Date",
    year_col: str = "Year",
    month_col: str = "Month",
) -> pd.DataFrame:
    """Dynamic hydro years from successive wet-season onsets.

    Parameters
    ----------
    long_period_threshold : int
        Maximum allowable gap (months) between wet onsets before a fallback insertion.
    fallback_month : int
        Climatological fallback month used when no onset exists in a long gap.
    hydro_year_start_month : int, optional
        Established start month from the fixed-season step. Used to compute the
        initial hydro year correctly (defaults to ``fallback_month`` only if not given).
    onset_window_months : int | None
        Only Wet shifts within this circular month distance from the climatological
        start month are allowed to start a new hydro year. This prevents short
        mid-year Wet fragments from incrementing the hydro-year label.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)
    df["SeasonShift"] = df["SeasonShift"].astype(bool)

    anchor_month = int(hydro_year_start_month) if hydro_year_start_month is not None else int(fallback_month)

    first_date = pd.Timestamp(df.iloc[0][date_col])
    # Use the same ending-year convention as assign_fixed_hydro_year:
    # e.g. Dec 1986 with a November start belongs to Hydro_Year 1987.
    initial_hydro_year = assign_hydro_year(first_date, anchor_month)

    wet_shifts = df.loc[df["SeasonShift"] & (df["SeasonType"] == "Wet"), date_col]
    wet_shift_dates: list[pd.Timestamp] = list(wet_shifts.tolist())

    # The first row is always flagged as a SeasonShift (no prior row to compare to).
    # That flag is an artefact, not a real Dry→Wet onset, so drop it.
    if wet_shift_dates and wet_shift_dates[0] == df[date_col].iloc[0]:
        wet_shift_dates = wet_shift_dates[1:]

    if onset_window_months is not None:
        def _month_distance(a: int, b: int) -> int:
            diff = abs(a - b)
            return min(diff, 12 - diff)

        wet_shift_dates = [
            d for d in wet_shift_dates
            if _month_distance(int(d.month), anchor_month) <= int(onset_window_months)
        ]

    fallback_dates: list[pd.Timestamp] = []

    def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
        return (b.year - a.year) * 12 + (b.month - a.month)

    if len(wet_shift_dates) > 1:
        for start, end in zip(wet_shift_dates, wet_shift_dates[1:]):
            if _months_between(start, end) >= long_period_threshold:
                fb = pd.Timestamp(year=start.year + 1, month=int(fallback_month), day=1)
                if start < fb < end:
                    fallback_dates.append(fb)

    last_date = df[date_col].iloc[-1]
    if not wet_shift_dates:
        anchor = df[date_col].iloc[0]
    else:
        anchor = wet_shift_dates[-1]
    if _months_between(anchor, last_date) >= long_period_threshold:
        fb = pd.Timestamp(year=anchor.year + 1, month=int(fallback_month), day=1)
        if anchor < fb <= last_date:
            fallback_dates.append(fb)

    all_hy_starts = sorted(set(wet_shift_dates + fallback_dates))
    counts = np.searchsorted(all_hy_starts, df[date_col], side="right")
    df["Hydro_Year"] = initial_hydro_year + counts
    return df
