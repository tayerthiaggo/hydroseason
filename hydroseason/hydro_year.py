"""Step 4 — Dynamic hydrological year assignment."""

from __future__ import annotations

import numpy as np
import pandas as pd


def assign_hydro_year(date: pd.Timestamp, start_month: int) -> int:
    """Calendar-style hydro year for a single date given a fixed start month."""
    if start_month == 1:
        return date.year
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

    ``Hydro_Year`` advances **only** at real Wet onsets (``SeasonType``
    transitions to Wet).  Normal onsets are filtered by ``onset_window_months``
    (circular distance from the anchor month); this prevents off-cycle wet
    fragments from incrementing the label.  When a gap between accepted onsets
    reaches ``long_period_threshold``, the nearest excluded real Wet onset to
    the *next* expected occurrence of ``fallback_month`` is recovered as a
    boundary.  This step iterates until all remaining gaps are below the
    threshold or no further Wet onsets are available to recover.  If no real
    Wet onset exists in a gap, no boundary is inserted — ``Hydro_Year`` never
    changes inside an ongoing Dry season.

    **Bimodal / two-wet-season regimes** (e.g. East Africa long rains + short
    rains): set ``onset_window_months=None`` so that *every* Wet onset starts a
    new ``Hydro_Year``.  In that case ``Hydro_Year`` increments at each wet
    onset — possibly twice per calendar year — and is a sequential counter, not
    a calendar-year label.

    **Arid regimes** where dry periods exceed ``long_period_threshold`` are
    handled correctly: if no wet season occurs during a drought, no boundary is
    inserted and ``Hydro_Year`` stays constant until the next real Wet onset.

    Parameters
    ----------
    long_period_threshold : int
        Maximum allowable gap (months) between accepted wet onsets before
        attempting to recover a filtered Wet onset.
    fallback_month : int
        Target month when choosing the best fallback Wet onset inside a long
        gap.  The target date is the **first** occurrence of this month strictly
        after the gap's opening onset: same calendar year when the onset precedes
        ``fallback_month``, next year otherwise.
    hydro_year_start_month : int, optional
        Anchor month from the fixed-season step. Used to compute the initial
        ``Hydro_Year`` (defaults to ``fallback_month`` when omitted).
    onset_window_months : int | None
        Circular distance (months) from the anchor month within which a Wet
        shift is accepted in the normal pass.  ``None`` accepts all Wet shifts
        (required for bimodal regimes so that both wet seasons advance the
        hydro year).
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
    all_wet_shift_dates: list[pd.Timestamp] = sorted(wet_shifts.tolist())

    # The first row is always flagged as a SeasonShift (no prior row to compare
    # to).  That flag is an artefact, not a real Dry→Wet onset, so drop it.
    if all_wet_shift_dates and all_wet_shift_dates[0] == df[date_col].iloc[0]:
        all_wet_shift_dates = all_wet_shift_dates[1:]

    def _month_distance(a: int, b: int) -> int:
        diff = abs(a - b)
        return min(diff, 12 - diff)

    def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
        return (b.year - a.year) * 12 + (b.month - a.month)

    def _fallback_target(start: pd.Timestamp) -> pd.Timestamp:
        """First occurrence of fallback_month strictly after *start*."""
        fb = int(fallback_month)
        yr = start.year if start.month < fb else start.year + 1
        return pd.Timestamp(year=yr, month=fb, day=1)

    if onset_window_months is not None:
        accepted: set[pd.Timestamp] = {
            d for d in all_wet_shift_dates
            if _month_distance(int(d.month), anchor_month) <= int(onset_window_months)
        }
    else:
        # Bimodal / no filtering: every real Wet onset advances the hydro year.
        accepted = set(all_wet_shift_dates)

    all_wet_set = set(all_wet_shift_dates)
    last_date = df[date_col].iloc[-1]

    def _nearest_candidate(
        start: pd.Timestamp,
        end: pd.Timestamp,
        *,
        include_end: bool = False,
    ) -> pd.Timestamp | None:
        """Unaccepted real Wet onset in (start, end] nearest to the fallback target."""
        target = _fallback_target(start)
        candidates = [
            d for d in all_wet_set
            if d not in accepted
            and start < d
            and (d <= end if include_end else d < end)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda d: abs(_months_between(target, d)))

    # Iteratively recover filtered Wet onsets from long gaps until no gaps
    # remain above the threshold or no further candidates exist.
    # Bounded by the number of available real Wet onsets.
    for _ in range(len(all_wet_shift_dates) + 1):
        current = sorted(accepted)
        new: list[pd.Timestamp] = []

        for s, e in zip(current, current[1:]):
            if _months_between(s, e) >= long_period_threshold:
                r = _nearest_candidate(s, e)
                if r is not None:
                    new.append(r)

        tail_anchor = current[-1] if current else first_date
        if _months_between(tail_anchor, last_date) >= long_period_threshold:
            r = _nearest_candidate(tail_anchor, last_date, include_end=True)
            if r is not None:
                new.append(r)

        if not new:
            break
        accepted.update(new)

    all_hy_starts = sorted(accepted)
    counts = np.searchsorted(all_hy_starts, df[date_col], side="right")
    df["Hydro_Year"] = initial_hydro_year + counts
    return df
