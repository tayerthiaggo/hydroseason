import numpy as np
import pandas as pd
import pytest
from hydroseason.config import DailyDetectionConfig
from hydroseason.daily_detection import (
    compute_daily_baseline,
    compute_daily_cumulative_anomaly,
    detect_wet_seasons_daily,
    detect_dry_down,
    find_stress_date,
    compute_stress_window,
)


def test_daily_baseline_and_anomaly():
    # Construct 2 years of daily data
    dates = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    # Wet DOYs (say DOY 100 to 200) have 10mm, others have 1mm
    rain = []
    for d in dates:
        if 100 <= d.dayofyear <= 200:
            rain.append(10.0)
        else:
            rain.append(1.0)

    df = pd.DataFrame({"Date": dates, "Rainfall_mm": rain})
    baseline = compute_daily_baseline(df, roll_window=30)

    assert len(baseline) == len(df)
    assert baseline.iloc[0] < baseline.iloc[150]  # wet DOY has higher baseline

    cum_anom = compute_daily_cumulative_anomaly(df, baseline)
    assert len(cum_anom) == len(df)


def test_detect_wet_seasons_daily_unimodal():
    # 2.7 years of daily data to cover 2 full seasons
    dates = pd.date_range("2020-01-01", "2022-08-31", freq="D")
    # Wet period: Nov (month 11) to Feb (month 2)
    # So we use a hydro year starting in September (month 9)
    rain = []
    for d in dates:
        if d.month in [11, 12, 1, 2]:
            rain.append(15.0)
        else:
            rain.append(1.0)

    df = pd.DataFrame({"Date": dates, "Rainfall_mm": rain})
    # Set hydro year: starting month 9
    from hydroseason.hydro_year import assign_hydro_year
    df["Hydro_Year"] = df["Date"].map(lambda dt: assign_hydro_year(pd.Timestamp(dt), 9))

    baseline = compute_daily_baseline(df, roll_window=30)
    df["Baseline"] = baseline
    cum_anom = compute_daily_cumulative_anomaly(df, baseline)

    config = DailyDetectionConfig(onset_persistence_days=21, cessation_persistence_days=21)
    wet_bounds = detect_wet_seasons_daily(df, cum_anom, config)

    assert not wet_bounds.empty
    # We should have Hydro_Year 2020 and 2021
    assert len(wet_bounds) >= 2
    # Verify that we delineated wet seasons in both years
    for _, row in wet_bounds.iterrows():
        # The third year (2022) is incomplete so it won't have onset/cessation, but 2020 and 2021 will
        if row["Hydro_Year"] in [2020, 2021]:
            assert row["WetStart"] is not None
            assert row["WetEnd"] is not None
            assert row["WetStart"] < row["WetEnd"]


def test_detect_dry_down_and_stress():
    # Mock wet boundaries
    wet_bounds = pd.DataFrame([
        {"Hydro_Year": 2020, "WetStart": pd.Timestamp("2020-11-01").date(), "WetEnd": pd.Timestamp("2021-02-28").date()},
        {"Hydro_Year": 2021, "WetStart": pd.Timestamp("2021-11-01").date(), "WetEnd": pd.Timestamp("2022-02-28").date()},
    ])

    dry_downs = detect_dry_down(wet_bounds, max_date="2022-12-31")
    assert len(dry_downs) == 2
    assert dry_downs.iloc[0]["DryStart"] == pd.Timestamp("2021-03-01").date()
    assert dry_downs.iloc[0]["DryEnd"] == pd.Timestamp("2021-10-31").date()

    # Create dummy cumulative anomaly with minimum in August
    dates = pd.date_range("2020-01-01", "2022-12-31", freq="D")
    # Anomaly decreases until August 15, then increases
    cum_anom_vals = []
    val = 0.0
    for d in dates:
        if d.year == 2021 and d.month == 8 and d.day == 15:
            val = -100.0  # absolute minimum
        elif d.year == 2021 and d.month < 8:
            val -= 0.5
        else:
            val += 0.5
        cum_anom_vals.append(val)

    df = pd.DataFrame({"Date": dates})
    cum_anom = pd.Series(cum_anom_vals)

    stress_date = find_stress_date(cum_anom, dry_downs.iloc[0]["DryStart"], dry_downs.iloc[0]["DryEnd"], df)
    assert stress_date.date() == pd.Timestamp("2021-08-15").date()

    # Stress window: stress_date to day before next wet season start (2021-10-31)
    w_start, w_end = compute_stress_window(stress_date, wet_bounds.iloc[1]["WetStart"])
    assert w_start == pd.Timestamp("2021-08-15").date()
    assert w_end == pd.Timestamp("2021-10-31").date()
