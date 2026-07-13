"""Daily cumulative anomaly and season transition detector."""

from __future__ import annotations

import pandas as pd
import numpy as np


def compute_daily_baseline(
    daily_df: pd.DataFrame,
    value_col: str = "Rainfall_mm",
    roll_window: int = 30,
) -> pd.Series:
    """Compute Day-of-Year (DOY) climatology with circular rolling window smoothing."""
    dates = pd.to_datetime(daily_df["Date"])
    doy = dates.dt.dayofyear

    # Calculate DOY mean across the entire record
    doy_mean = daily_df.groupby(doy)[value_col].mean()

    # Smooth circularly by replicating the DOY series 3 times
    extended = pd.concat([doy_mean] * 3)
    rolled = extended.rolling(window=roll_window, center=True, min_periods=1).mean()

    # Extract the middle segment (original DOY range)
    n = len(doy_mean)
    doy_baseline = rolled.iloc[n:2*n]
    doy_baseline.index = doy_mean.index

    # Map back to matching daily row shape
    return doy.map(doy_baseline).rename("Baseline")


def compute_daily_cumulative_anomaly(
    daily_df: pd.DataFrame,
    baseline: pd.Series,
    value_col: str = "Rainfall_mm",
) -> pd.Series:
    """Compute the running cumulative sum of rainfall daily anomaly."""
    anom = daily_df[value_col] - baseline
    return anom.cumsum().rename("Cumulative_Anomaly")


def detect_wet_seasons_daily(
    daily_df: pd.DataFrame,
    cum_anom: pd.Series,
    config,
) -> pd.DataFrame:
    """Detect daily wet-season onset and cessation with persistence filters."""
    onset_days = config.onset_persistence_days
    cess_days = config.cessation_persistence_days

    work = daily_df.sort_values("Date").reset_index(drop=True)
    n_global = len(work)
    daily_anoms = work["Rainfall_mm"] - work["Baseline"]

    records = []

    # Hydro_Year should be present in work
    if "Hydro_Year" not in work.columns:
        # Fallback to fixed calendar assignment if missing
        work["Hydro_Year"] = work["Date"].dt.year

    for hy, group in work.groupby("Hydro_Year"):
        group_indices = group.index.tolist()
        if not group_indices:
            continue
        start_pos = group_indices[0]
        end_pos = group_indices[-1]

        wet_start = None
        wet_end = None
        onset_pos = None

        # 1. Find onset (first day with positive anomaly sustained for onset_days)
        for pos in range(start_pos, end_pos + 1):
            if daily_anoms.iloc[pos] <= 0:
                continue

            if pos + onset_days > n_global:
                continue

            # Reference anomaly value is the day before onset starts
            start_val = (
                cum_anom.iloc[pos - 1]
                if pos > 0
                else (cum_anom.iloc[pos] - daily_anoms.iloc[pos])
            )

            persistent = True
            for d in range(onset_days):
                if cum_anom.iloc[pos + d] < start_val:
                    persistent = False
                    break

            if persistent:
                wet_start = pd.to_datetime(work.iloc[pos]["Date"]).date()
                onset_pos = pos
                break

        # 2. Find cessation (first day after onset with negative anomaly sustained for cess_days)
        if wet_start is not None and onset_pos is not None:
            for pos in range(onset_pos + 1, end_pos + 1):
                if daily_anoms.iloc[pos] >= 0:
                    continue

                if pos + cess_days > n_global:
                    continue

                start_val = cum_anom.iloc[pos - 1]

                persistent = True
                for d in range(cess_days):
                    if cum_anom.iloc[pos + d] > start_val:
                        persistent = False
                        break

                if persistent:
                    wet_end = pd.to_datetime(work.iloc[pos]["Date"]).date()
                    break

        records.append({
            "Hydro_Year": int(hy),
            "WetStart": wet_start,
            "WetEnd": wet_end,
        })

    return pd.DataFrame(records)


def detect_dry_down(
    wet_boundaries: pd.DataFrame,
    max_date=None,
) -> pd.DataFrame:
    """Identify the dry-down window as cessation to next onset."""
    records = []
    n = len(wet_boundaries)

    for i in range(n):
        row = wet_boundaries.iloc[i]
        hy = row["Hydro_Year"]
        wet_end = row["WetEnd"]

        dry_start = None
        dry_end = None

        if wet_end is not None and not pd.isna(wet_end):
            # Dry down starts the day after wet season ends
            dry_start = wet_end + pd.Timedelta(days=1)

            if i < n - 1:
                next_row = wet_boundaries.iloc[i + 1]
                next_start = next_row["WetStart"]
                if next_start is not None and not pd.isna(next_start):
                    # Dry down ends the day before next wet season starts
                    dry_end = next_start - pd.Timedelta(days=1)
            else:
                if max_date is not None:
                    dry_end = pd.to_datetime(max_date).date()

            # Ensure dry_start is a date and dry_end is a date
            if dry_start is not None:
                dry_start = pd.to_datetime(dry_start).date()
            if dry_end is not None:
                dry_end = pd.to_datetime(dry_end).date()

        records.append({
            "Hydro_Year": int(hy),
            "DryStart": dry_start,
            "DryEnd": dry_end,
        })

    return pd.DataFrame(records)


def find_stress_date(
    cum_anom: pd.Series,
    dry_start,
    dry_end,
    daily_df: pd.DataFrame,
) -> pd.Timestamp | None:
    """Find the stress date as the argmin of cumulative anomaly in dry-down window."""
    if (
        dry_start is None
        or pd.isna(dry_start)
        or dry_end is None
        or pd.isna(dry_end)
    ):
        return None

    dates = pd.to_datetime(daily_df["Date"])
    mask = (dates.dt.date >= dry_start) & (dates.dt.date <= dry_end)
    sub_cum = cum_anom[mask]
    if sub_cum.empty:
        return None

    min_idx = sub_cum.idxmin()
    return pd.to_datetime(daily_df.loc[min_idx, "Date"])


def compute_stress_window(
    stress_date,
    next_onset,
) -> tuple[object, object] | tuple[None, None]:
    """Return stress window as (stress_start, stress_end)."""
    if (
        stress_date is None
        or pd.isna(stress_date)
        or next_onset is None
        or pd.isna(next_onset)
    ):
        return None, None
    stress_start = pd.to_datetime(stress_date).date()
    stress_end = (pd.to_datetime(next_onset) - pd.Timedelta(days=1)).date()
    return stress_start, stress_end

