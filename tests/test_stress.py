import numpy as np
import pandas as pd
import pytest
from hydroseason.stress import (
    build_stress_table,
    compute_stress_confidence,
    stress_from_monthly_seasons,
)


def test_build_stress_table():
    wet_bounds = pd.DataFrame([
        {"Hydro_Year": 2020, "WetStart": pd.Timestamp("2020-11-01").date(), "WetEnd": pd.Timestamp("2021-02-28").date()},
        {"Hydro_Year": 2021, "WetStart": pd.Timestamp("2021-11-01").date(), "WetEnd": pd.Timestamp("2022-02-28").date()},
    ])
    dry_downs = pd.DataFrame([
        {"Hydro_Year": 2020, "DryStart": pd.Timestamp("2021-03-01").date(), "DryEnd": pd.Timestamp("2021-10-31").date()},
        {"Hydro_Year": 2021, "DryStart": pd.Timestamp("2022-03-01").date(), "DryEnd": pd.Timestamp("2022-10-31").date()},
    ])

    dates = pd.date_range("2020-01-01", "2022-12-31", freq="D")
    rain = np.ones(len(dates))
    daily_df = pd.DataFrame({"Date": dates, "Rainfall_mm": rain})

    # cumulative anomaly mock
    cum_anom = pd.Series(np.zeros(len(dates)))

    stress_table = build_stress_table(wet_bounds, dry_downs, cum_anom, daily_df)

    assert len(stress_table) == 2
    assert "stress_date" in stress_table.columns
    assert "stress_confidence" in stress_table.columns
    assert "dry_season_length_days" in stress_table.columns


def test_compute_stress_confidence_penalties():
    dates = pd.date_range("2021-03-01", "2021-10-31", freq="D")
    rain = np.zeros(len(dates))
    # Add one storm day
    rain[10] = 25.0
    # Add a few NaNs to simulate missing data
    rain[20:30] = np.nan

    daily_df = pd.DataFrame({"Date": dates, "Rainfall_mm": rain})

    stress_row = {
        "dry_season_start": pd.Timestamp("2021-03-01").date(),
        "dry_season_end": pd.Timestamp("2021-10-31").date(),
        "stress_date": pd.Timestamp("2021-08-15").date(),
    }

    class SeasonalityMock:
        stl_strength = 0.9

    conf = compute_stress_confidence(stress_row, SeasonalityMock(), daily_df)

    # Base stl_strength is 0.9
    # Missing fraction: 10 / 245 = ~0.04
    # Storm days: 1 day > 10mm -> penalty 0.05
    # Total confidence should be roughly 0.9 - 0.04 - 0.05 = ~0.81
    assert 0.75 <= conf <= 0.85


def test_stress_from_monthly_seasons():
    wet_bounds = pd.DataFrame([
        {"Hydro_Year": 2020, "WetStart": pd.Timestamp("2020-11-01").date(), "WetEnd": pd.Timestamp("2021-02-28").date()},
        {"Hydro_Year": 2021, "WetStart": pd.Timestamp("2021-11-01").date(), "WetEnd": pd.Timestamp("2022-02-28").date()},
    ])
    dates = pd.date_range("2020-01-01", "2022-12-31", freq="MS")
    monthly_df = pd.DataFrame({"Date": dates, "Rainfall_mm": np.ones(len(dates))})

    class SeasonalityMock:
        stl_strength = 0.8

    monthly_stress = stress_from_monthly_seasons(wet_bounds, monthly_df, SeasonalityMock())

    assert len(monthly_stress) == 2
    # Verify monthly fallback stress date is October 1st (month before next November onset)
    assert monthly_stress.iloc[0]["stress_date"] == pd.Timestamp("2021-10-01").date()
    assert monthly_stress.iloc[0]["stress_confidence"] == 0.4  # stl_strength 0.8 * 0.5 = 0.4
