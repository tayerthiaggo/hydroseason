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
    rainfall_col: str = "Rainfall_mm",
    max_hydro_year_months: int | None = 15,
    no_dry_split_min_months: int = 9,
    no_dry_split_max_months: int = 15,
    min_dry_season_length: int = 2,
    date_col: str = "Date",
    year_col: str = "Year",
    month_col: str = "Month",
) -> pd.DataFrame:
    """Dynamic hydro years from successive wet-season onsets.

    ``Hydro_Year`` advances **only** at real Wet onsets (``SeasonType``
    transitions to Wet).  Normal onsets are filtered by ``onset_window_months``
    (circular distance from the anchor month); this prevents off-cycle wet
    fragments from incrementing the label.  Filtered unimodal runs also allow
    at most one advancing onset per seasonal cycle, so a widened onset window
    cannot count multiple shoulder onsets in the same year.  When a gap between
    accepted onsets reaches ``long_period_threshold``, the nearest excluded
    real Wet onset to the *next* expected occurrence of ``fallback_month`` is
    recovered as a boundary.  This step iterates until all remaining gaps are
    below the threshold or no further Wet onsets are available to recover.  If
    no real Wet onset exists in a gap, no boundary is inserted — ``Hydro_Year`` never
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
        accepted: set[pd.Timestamp] = set()
        accepted_sources: dict[pd.Timestamp, str] = {}
        for d in all_wet_shift_dates:
            if _month_distance(int(d.month), anchor_month) <= int(onset_window_months):
                accepted.add(d)
                accepted_sources[d] = "wet_onset"
    else:
        # Bimodal / no filtering: every real Wet onset advances the hydro year.
        accepted = set(all_wet_shift_dates)
        accepted_sources = {d: "wet_onset" for d in all_wet_shift_dates}

    all_wet_set = set(all_wet_shift_dates)
    last_date = df[date_col].iloc[-1]

    def _unimodal_onset_cycle(d: pd.Timestamp) -> int:
        """Ending-year label of the seasonal cycle an onset is closest to."""
        fixed_label = assign_hydro_year(d, anchor_month)
        months_since_anchor = (int(d.month) - anchor_month) % 12
        if months_since_anchor > 6:
            return fixed_label + 1
        return fixed_label

    def _effective_hy_starts(starts: set[pd.Timestamp]) -> list[pd.Timestamp]:
        """Drop duplicate unimodal onsets that target an already-counted cycle."""
        ordered = sorted(starts)
        if onset_window_months is None:
            return ordered

        effective: list[pd.Timestamp] = []
        last_cycle = initial_hydro_year
        for d in ordered:
            cycle = _unimodal_onset_cycle(d)
            if cycle <= last_cycle:
                continue
            effective.append(d)
            last_cycle = cycle
        return effective

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
        current = _effective_hy_starts(accepted)
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
        for d in new:
            accepted.add(d)
            accepted_sources[d] = "recovered_onset"

    all_hy_starts = _effective_hy_starts(accepted)
    source_by_date = {
        d: accepted_sources.get(d, "wet_onset")
        for d in all_hy_starts
    }

    def _has_real_dry_run(seasons: pd.Series) -> bool:
        run = 0
        for label in seasons.astype(str):
            if label == "Dry":
                run += 1
                if run >= int(min_dry_season_length):
                    return True
            else:
                run = 0
        return False

    def _candidate_allowed_for_label(
        candidate: pd.Timestamp,
        proposed_label: int | None,
    ) -> bool:
        if proposed_label is None or onset_window_months is None:
            return True
        max_allowed = assign_hydro_year(candidate, anchor_month) + 1
        return int(proposed_label) <= int(max_allowed)

    def _label_at_span_start(
        start: pd.Timestamp,
        starts: list[pd.Timestamp],
    ) -> int:
        if start == first_date:
            return int(initial_hydro_year)
        return int(initial_hydro_year + np.searchsorted(starts, start, side="right"))

    def _no_dry_minimum_candidate(
        span_start: pd.Timestamp,
        span_end_exclusive: pd.Timestamp,
        proposed_label: int | None = None,
    ) -> pd.Timestamp | None:
        if rainfall_col not in df.columns:
            return None
        window_start = span_start + pd.DateOffset(months=int(no_dry_split_min_months))
        window_end = span_start + pd.DateOffset(months=int(no_dry_split_max_months))
        latest = span_end_exclusive - pd.DateOffset(months=1)
        if window_end > latest:
            window_end = latest
        if window_start > window_end:
            return None

        prefix = df[
            (df[date_col] >= span_start)
            & (df[date_col] <= window_end)
        ]
        if prefix.empty or _has_real_dry_run(prefix["SeasonType"]):
            return None
        if not bool(prefix["SeasonType"].astype(str).eq("Wet").any()):
            return None

        candidates = df[
            (df[date_col] >= window_start)
            & (df[date_col] <= window_end)
        ].copy()
        if candidates.empty:
            return None
        values = pd.to_numeric(candidates[rainfall_col], errors="coerce")
        if values.isna().all():
            return None
        idx = values.idxmin()
        candidate = pd.Timestamp(df.loc[idx, date_col])
        if candidate <= span_start or candidate >= span_end_exclusive:
            return None
        if not _candidate_allowed_for_label(candidate, proposed_label):
            return None
        return candidate

    if (
        max_hydro_year_months is not None
        and int(max_hydro_year_months) > 0
        and rainfall_col in df.columns
    ):
        end_exclusive = last_date + pd.DateOffset(months=1)
        starts = sorted(all_hy_starts)
        for _ in range(len(df) + 1):
            boundaries = [first_date] + starts + [end_exclusive]
            new_starts: list[pd.Timestamp] = []
            for start, end in zip(boundaries, boundaries[1:]):
                span_rows = df[
                    (df[date_col] >= start)
                    & (df[date_col] < end)
                ]
                if len(span_rows) <= int(max_hydro_year_months):
                    continue
                proposed_label = _label_at_span_start(start, starts) + 1
                candidate = _no_dry_minimum_candidate(
                    start,
                    end,
                    proposed_label,
                )
                if candidate is not None and candidate not in starts:
                    new_starts.append(candidate)
                    source_by_date[candidate] = "no_dry_minimum"
            if not new_starts:
                break
            starts = sorted(set(starts).union(new_starts))
        all_hy_starts = starts

    def _dedupe_unimodal_starts(starts: list[pd.Timestamp]) -> list[pd.Timestamp]:
        if onset_window_months is None:
            return sorted(starts)
        final_starts: list[pd.Timestamp] = []
        last_cycle = initial_hydro_year
        for start in sorted(starts):
            cycle = _unimodal_onset_cycle(start)
            source = source_by_date.get(start, "wet_onset")
            if cycle <= last_cycle:
                if source not in {"no_dry_minimum", "recovered_onset", "dry_anchor"}:
                    continue
                proposed_cycle = last_cycle + 1
                max_allowed = assign_hydro_year(start, anchor_month) + 1
                if proposed_cycle > max_allowed:
                    continue
                last_cycle = proposed_cycle
            else:
                last_cycle = cycle
            final_starts.append(start)
        return final_starts

    all_hy_starts = _dedupe_unimodal_starts(all_hy_starts)

    def _first_wet_onset_after_real_dry(
        span_start: pd.Timestamp,
        span_end_exclusive: pd.Timestamp,
        proposed_label: int | None = None,
    ) -> pd.Timestamp | None:
        rows = df[
            (df[date_col] >= span_start)
            & (df[date_col] < span_end_exclusive)
        ].sort_values(date_col)
        dry_run = 0
        seen_real_dry = False
        previous = None
        recovering_wet_run = False
        for _, row in rows.iterrows():
            label = str(row["SeasonType"])
            if label == "Dry":
                dry_run += 1
                if dry_run >= int(min_dry_season_length):
                    seen_real_dry = True
                recovering_wet_run = False
            else:
                if label == "Wet" and seen_real_dry and (
                    previous == "Dry" or recovering_wet_run
                ):
                    recovering_wet_run = True
                    candidate = pd.Timestamp(row[date_col])
                    if _candidate_allowed_for_label(candidate, proposed_label):
                        return candidate
                else:
                    recovering_wet_run = False
                dry_run = 0
            previous = label
        return None

    def _dry_anchor_candidate(
        span_start: pd.Timestamp,
        span_end_exclusive: pd.Timestamp,
        proposed_label: int | None = None,
    ) -> pd.Timestamp | None:
        window_start = span_start + pd.DateOffset(months=int(no_dry_split_min_months))
        window_end = span_start + pd.DateOffset(months=int(no_dry_split_max_months))
        latest = span_end_exclusive - pd.DateOffset(months=1)
        if window_end > latest:
            window_end = latest
        candidates = df[
            (df[date_col] >= window_start)
            & (df[date_col] <= window_end)
            & (df[month_col].astype(int) == anchor_month)
        ]
        if candidates.empty:
            fallback = span_start + pd.DateOffset(months=12)
            candidates = df[df[date_col] == fallback]
        if candidates.empty:
            return None
        candidate = pd.Timestamp(candidates.iloc[0][date_col])
        if candidate <= span_start or candidate >= span_end_exclusive:
            return None
        if not _candidate_allowed_for_label(candidate, proposed_label):
            return None
        return candidate

    if (
        max_hydro_year_months is not None
        and int(max_hydro_year_months) > 0
        and rainfall_col in df.columns
    ):
        end_exclusive = last_date + pd.DateOffset(months=1)
        starts = sorted(all_hy_starts)
        for _ in range(len(df) + 1):
            boundaries = [first_date] + starts + [end_exclusive]
            new_starts: list[pd.Timestamp] = []
            for start, end in zip(boundaries, boundaries[1:]):
                span_rows = df[
                    (df[date_col] >= start)
                    & (df[date_col] < end)
                ]
                if len(span_rows) <= int(max_hydro_year_months):
                    continue

                proposed_label = _label_at_span_start(start, starts) + 1
                candidate = _first_wet_onset_after_real_dry(
                    start,
                    end,
                    proposed_label,
                )
                source = "recovered_onset"
                if candidate is None:
                    candidate = _no_dry_minimum_candidate(
                        start,
                        end,
                        proposed_label,
                    )
                    source = "no_dry_minimum"
                if candidate is None:
                    candidate = _dry_anchor_candidate(start, end, proposed_label)
                    source = "dry_anchor"
                if candidate is not None and candidate not in starts:
                    new_starts.append(candidate)
                    source_by_date[candidate] = source
            if not new_starts:
                break
            starts = _dedupe_unimodal_starts(sorted(set(starts).union(new_starts)))
        all_hy_starts = starts

    counts = np.searchsorted(all_hy_starts, df[date_col], side="right")
    df["Hydro_Year"] = initial_hydro_year + counts
    df["Hydro_Year_Boundary_Source"] = pd.NA
    df.loc[df.index[0], "Hydro_Year_Boundary_Source"] = "initial"
    for start in all_hy_starts:
        matches = df.index[df[date_col] == start]
        if len(matches):
            df.loc[matches[0], "Hydro_Year_Boundary_Source"] = (
                source_by_date.get(start, "wet_onset")
            )

    no_dry_by_hy: dict[int, bool] = {}
    for hy, group in df.groupby("Hydro_Year", sort=False):
        has_wet = bool(group["SeasonType"].astype(str).eq("Wet").any())
        no_real_dry = not _has_real_dry_run(group["SeasonType"])
        no_dry_by_hy[int(hy)] = bool(has_wet and no_real_dry)
    df["Hydro_Year_No_Dry_Season"] = (
        df["Hydro_Year"].astype(int).map(no_dry_by_hy).fillna(False).astype(bool)
    )
    return df
