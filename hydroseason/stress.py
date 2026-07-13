"""Stress window and confidence engine."""

from __future__ import annotations

import pandas as pd
import numpy as np


def build_stress_table(
    wet_boundaries: pd.DataFrame,
    dry_downs: pd.DataFrame,
    cum_anom: pd.Series,
    daily_df: pd.DataFrame,
    seasonality=None,
) -> pd.DataFrame:
    """Assemble the annual daily stress metrics DataFrame."""
    records = []
    n = len(wet_boundaries)
    dates = pd.to_datetime(daily_df["Date"])
    value_col = "Rainfall_mm"

    for i in range(n):
        row = wet_boundaries.iloc[i]
        hy = row["Hydro_Year"]
        wet_end = row["WetEnd"]

        # Dry down bounds
        dry_row = dry_downs[dry_downs["Hydro_Year"] == hy]
        dry_start = dry_row["DryStart"].iloc[0] if not dry_row.empty else None
        dry_end = dry_row["DryEnd"].iloc[0] if not dry_row.empty else None

        # Next onset
        next_onset = None
        if i < n - 1:
            next_onset = wet_boundaries.iloc[i + 1]["WetStart"]

        # Calculate stress date
        from .daily_detection import find_stress_date, compute_stress_window
        stress_date = find_stress_date(cum_anom, dry_start, dry_end, daily_df)

        # Compute stress window
        stress_w_start, stress_w_end = compute_stress_window(stress_date, next_onset)

        # Dry season length
        dry_season_length = None
        if wet_end is not None and not pd.isna(wet_end) and next_onset is not None and not pd.isna(next_onset):
            dry_season_length = (pd.to_datetime(next_onset) - pd.to_datetime(wet_end)).days

        # Deficit and antecedent rain
        deficit = None
        rain_since_wet_end = None
        if (
            wet_end is not None
            and not pd.isna(wet_end)
            and stress_date is not None
            and not pd.isna(stress_date)
        ):
            # Antecedent deficit: cum_anom[wet_end] - cum_anom[stress_date]
            end_mask = dates.dt.date == wet_end
            stress_mask = dates.dt.date == stress_date.date()
            if end_mask.any() and stress_mask.any():
                val_end = cum_anom[end_mask].iloc[0]
                val_stress = cum_anom[stress_mask].iloc[0]
                deficit = float(val_end - val_stress)

            # Rain since wet end
            rain_mask = (dates.dt.date > wet_end) & (dates.dt.date <= stress_date.date())
            rain_since_wet_end = float(daily_df.loc[rain_mask, value_col].sum(min_count=1))

        # Pack row
        rec = {
            "hydro_year": int(hy),
            "stress_date": stress_date.date() if stress_date is not None else None,
            "stress_window_start": stress_w_start,
            "stress_window_end": stress_w_end,
            "dry_season_length_days": dry_season_length,
            "antecedent_rainfall_deficit": deficit,
            "rainfall_since_wet_season_end": rain_since_wet_end,
            "dry_season_start": dry_start,
            "dry_season_end": dry_end,
        }

        # Calculate confidence
        confidence = compute_stress_confidence(rec, seasonality, daily_df)
        rec["stress_confidence"] = confidence

        records.append(rec)

    return pd.DataFrame(records)


def compute_stress_confidence(
    stress_row: dict,
    seasonality,
    daily_df: pd.DataFrame,
) -> float:
    """Compute 0-1 scalar confidence index for stress detection."""
    # Base confidence from seasonality strength
    sf = 0.8
    if seasonality is not None:
        sf = getattr(seasonality, "stl_strength", 0.8)
        if sf is None or pd.isna(sf):
            sf = getattr(seasonality, "si", 0.8)
            if sf is None or pd.isna(sf):
                sf = 0.8

    confidence = sf

    dry_start = stress_row.get("dry_season_start")
    dry_end = stress_row.get("dry_season_end")

    if dry_start is not None and dry_end is not None and not pd.isna(dry_start) and not pd.isna(dry_end):
        dates = pd.to_datetime(daily_df["Date"]).dt.date
        mask = (dates >= dry_start) & (dates <= dry_end)
        sub_df = daily_df[mask]

        if not sub_df.empty:
            # 1. Missing data penalty
            missing_frac = sub_df["Rainfall_mm"].isna().mean()
            confidence -= 1.0 * missing_frac

            # 2. Storm penalty (days > 10mm in dry season)
            storm_days = int((sub_df["Rainfall_mm"] > 10.0).sum())
            storm_penalty = min(0.20, 0.05 * storm_days)
            confidence -= storm_penalty

    # Wide onset uncertainty (if stress date is None)
    if stress_row.get("stress_date") is None:
        confidence = 0.0

    return float(max(0.0, min(1.0, confidence)))


def stress_from_monthly_seasons(
    wet_boundaries: pd.DataFrame | None,
    monthly_df: pd.DataFrame,
    seasonality=None,
    value_col: str = "Rainfall_mm",
) -> pd.DataFrame:
    """Monthly fallback stress calculator using monthly wet boundaries."""
    if wet_boundaries is None:
        return pd.DataFrame(columns=[
            "hydro_year", "stress_date", "stress_window_start", "stress_window_end",
            "dry_season_length_days", "antecedent_rainfall_deficit",
            "rainfall_since_wet_season_end", "dry_season_start", "dry_season_end",
            "stress_confidence"
        ])

    records = []
    n = len(wet_boundaries)
    dates = pd.to_datetime(monthly_df["Date"])

    # Compute a simple monthly anomaly to simulate cumulative anomaly argmin
    baseline = monthly_df.groupby(dates.dt.month)[value_col].mean()
    monthly_df = monthly_df.copy()
    monthly_df["Baseline"] = dates.dt.month.map(baseline)
    cum_anom = (monthly_df[value_col] - monthly_df["Baseline"]).cumsum()

    for i in range(n):
        row = wet_boundaries.iloc[i]
        hy = row["Hydro_Year"]
        wet_end = row["WetEnd"]  # date of wet end

        # Next onset
        next_onset = None
        if i < n - 1:
            next_onset = wet_boundaries.iloc[i + 1]["WetStart"]

        stress_date = None
        stress_w_start = None
        stress_w_end = None
        dry_season_length = None
        deficit = None
        rain_since_wet_end = None

        if wet_end is not None and not pd.isna(wet_end):
            wet_end_dt = pd.to_datetime(wet_end)
            dry_start_dt = wet_end_dt + pd.DateOffset(months=1)

            if next_onset is not None and not pd.isna(next_onset):
                next_onset_dt = pd.to_datetime(next_onset)
                dry_end_dt = next_onset_dt - pd.DateOffset(months=1)

                dry_season_length = (next_onset_dt - wet_end_dt).days

                # Monthly stress date = last month before next onset
                # We align stress date to the 1st day of that month
                stress_date_dt = dry_end_dt
                stress_date = stress_date_dt.date()

                stress_w_start = stress_date
                # stress window ends day before next onset
                stress_w_end = (next_onset_dt - pd.Timedelta(days=1)).date()

                # Deficit: cum_anom at wet_end - cum_anom at stress_date
                end_mask = (dates.dt.year == wet_end_dt.year) & (dates.dt.month == wet_end_dt.month)
                stress_mask = (dates.dt.year == stress_date_dt.year) & (dates.dt.month == stress_date_dt.month)

                if end_mask.any() and stress_mask.any():
                    deficit = float(cum_anom[end_mask].iloc[0] - cum_anom[stress_mask].iloc[0])

                # Rainfall since wet end
                rain_mask = (dates > wet_end_dt) & (dates <= stress_date_dt)
                rain_since_wet_end = float(monthly_df.loc[rain_mask, value_col].sum(min_count=1))

        # Pack row
        sf = 0.4  # Penalized base confidence for monthly fallback
        if seasonality is not None:
            stl = getattr(seasonality, "stl_strength", 0.8)
            if stl is not None and not pd.isna(stl):
                sf = stl * 0.5

        rec = {
            "hydro_year": int(hy),
            "stress_date": stress_date,
            "stress_window_start": stress_w_start,
            "stress_window_end": stress_w_end,
            "dry_season_length_days": dry_season_length,
            "antecedent_rainfall_deficit": deficit,
            "rainfall_since_wet_season_end": rain_since_wet_end,
            "dry_season_start": (wet_end_dt + pd.DateOffset(days=1)).date() if wet_end is not None else None,
            "dry_season_end": (pd.to_datetime(next_onset) - pd.DateOffset(days=1)).date() if next_onset is not None else None,
            "stress_confidence": float(max(0.0, min(1.0, sf))),
        }
        records.append(rec)

    return pd.DataFrame(records)
