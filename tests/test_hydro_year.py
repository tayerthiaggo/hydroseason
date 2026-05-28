import pandas as pd

from hydroseason.dynamic_season import (
    harmonize_with_zero_preservation,
    segment_main_wet_season_fixed_threshold,
)
from hydroseason.hydro_year import assign_fixed_hydro_year, assign_hydro_years


def test_assign_hydro_years_accepts_renamed_date_col(monthly_df: pd.DataFrame):
    """Regression: previously hardcoded 'Date'."""
    monthly_df["Timestamp"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    work = assign_fixed_hydro_year(monthly_df, start_month=11, date_col="Timestamp")
    work = harmonize_with_zero_preservation(work, window=3)
    seg, _ = segment_main_wet_season_fixed_threshold(work, date_col="Timestamp")
    out = assign_hydro_years(seg, date_col="Timestamp")
    assert "Hydro_Year" in out.columns
    assert out["Hydro_Year"].dtype.kind in {"i", "u"}


def test_assign_hydro_years_initial_year_uses_start_month(monthly_df: pd.DataFrame):
    """Regression for inverted initial_hydro_year logic."""
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    work = assign_fixed_hydro_year(monthly_df, start_month=11)
    work = harmonize_with_zero_preservation(work, window=3)
    seg, _ = segment_main_wet_season_fixed_threshold(work)
    out = assign_hydro_years(seg, hydro_year_start_month=11, fallback_month=11)
    # Jan-Oct 2020 precede the next anchor month 11, so under the ending-year
    # convention they belong to HY 2020.
    first_year = out.loc[out["Date"] == pd.Timestamp("2020-01-01"), "Hydro_Year"].iloc[0]
    assert first_year == 2020


def test_assign_hydro_years_ignores_mid_year_wet_fragment():
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": [
            "Wet", "Wet", "Wet", "Dry", "Wet", "Dry",
            "Dry", "Dry", "Dry", "Wet", "Wet", "Wet",
        ],
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=11,
        fallback_month=11,
        onset_window_months=1,
    )

    # May is a wet fragment too far from the Oct-Dec onset window, so it stays HY2020.
    assert out.loc[out["Date"] == pd.Timestamp("2020-05-01"), "Hydro_Year"].iloc[0] == 2020
    # October is within one month of the November climatological onset, so it starts HY2021.
    assert out.loc[out["Date"] == pd.Timestamp("2020-10-01"), "Hydro_Year"].iloc[0] == 2021
