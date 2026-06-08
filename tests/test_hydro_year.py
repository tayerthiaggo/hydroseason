import pandas as pd

from hydroseason.dynamic_season import (
    harmonize_with_zero_preservation,
    segment_main_wet_season_fixed_threshold,
)
from hydroseason.hydro_year import (
    assign_fixed_hydro_year,
    assign_hydro_year,
    assign_hydro_years,
)


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


def test_assign_hydro_years_deduplicates_unimodal_january_cycle_onsets():
    dates = pd.date_range("2018-01-01", "2020-12-01", freq="MS")
    wet_onsets = {
        pd.Timestamp("2018-03-01"),
        pd.Timestamp("2018-11-01"),
        pd.Timestamp("2019-10-01"),
        pd.Timestamp("2020-03-01"),
        pd.Timestamp("2020-10-01"),
    }
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": ["Wet" if d in wet_onsets else "Dry" for d in dates],
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=1,
        fallback_month=1,
        onset_window_months=3,
    )

    fixed_hy = out["Date"].map(lambda d: assign_hydro_year(pd.Timestamp(d), 1))
    assert (out["Hydro_Year"] <= fixed_hy + 1).all()
    assert out.loc[out["Date"] == pd.Timestamp("2018-11-01"), "Hydro_Year"].iloc[0] == 2019
    assert out.loc[out["Date"] == pd.Timestamp("2020-03-01"), "Hydro_Year"].iloc[0] == 2020


def test_assign_hydro_years_deduplicates_unimodal_may_cycle_onsets():
    dates = pd.date_range("2013-01-01", "2016-12-01", freq="MS")
    wet_onsets = {
        pd.Timestamp("2013-05-01"),
        pd.Timestamp("2013-07-01"),
        pd.Timestamp("2014-04-01"),
        pd.Timestamp("2014-07-01"),
        pd.Timestamp("2015-04-01"),
        pd.Timestamp("2015-07-01"),
        pd.Timestamp("2016-04-01"),
    }
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": ["Wet" if d in wet_onsets else "Dry" for d in dates],
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=5,
        fallback_month=5,
        onset_window_months=3,
    )

    fixed_hy = out["Date"].map(lambda d: assign_hydro_year(pd.Timestamp(d), 5))
    assert (out["Hydro_Year"] <= fixed_hy + 1).all()
    assert out.loc[out["Date"] == pd.Timestamp("2013-07-01"), "Hydro_Year"].iloc[0] == 2014
    assert out.loc[out["Date"] == pd.Timestamp("2016-04-01"), "Hydro_Year"].iloc[0] == 2017


def test_assign_hydro_years_does_not_insert_fallback_inside_dry_season():
    dates = pd.date_range("2020-01-01", periods=24, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": ["Wet", "Wet", "Wet"] + ["Dry"] * 21,
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=11,
        fallback_month=8,
        long_period_threshold=12,
        onset_window_months=1,
    )

    assert out["Hydro_Year"].nunique() == 1
    assert not out["Hydro_Year_Boundary_Source"].astype(str).eq("no_dry_minimum").any()


def test_assign_hydro_years_splits_no_dry_year_at_local_minimum():
    dates = pd.date_range("2020-01-01", periods=20, freq="MS")
    rainfall = [
        120, 110, 100, 95, 90, 85, 70, 60, 40, 5,
        55, 80, 120, 130, 125, 90, 70, 55, 45, 35,
    ]
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "Rainfall_mm": rainfall,
        "SeasonType": ["Wet"] * len(dates),
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=1,
        fallback_month=1,
        onset_window_months=1,
        max_hydro_year_months=15,
    )

    boundary = out.loc[
        out["Hydro_Year_Boundary_Source"].eq("no_dry_minimum"),
        "Date",
    ]
    assert boundary.tolist() == [pd.Timestamp("2020-10-01")]
    assert out.groupby("Hydro_Year").size().max() <= 15
    assert out["Hydro_Year_No_Dry_Season"].all()


def test_assign_hydro_years_no_dry_split_ignores_real_dry_season():
    dates = pd.date_range("2020-01-01", periods=20, freq="MS")
    season = ["Wet"] * 6 + ["Dry"] * 3 + ["Wet"] * 11
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "Rainfall_mm": [100.0] * 6 + [0.0] * 3 + [100.0] * 11,
        "SeasonType": season,
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=1,
        fallback_month=1,
        onset_window_months=1,
        max_hydro_year_months=15,
    )

    assert not out["Hydro_Year_Boundary_Source"].astype(str).eq("no_dry_minimum").any()
    assert not out["Hydro_Year_No_Dry_Season"].all()


def test_assign_hydro_years_recovers_filtered_real_wet_onset_for_long_gap():
    dates = pd.date_range("2020-01-01", periods=24, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": (
            ["Wet", "Wet", "Wet"]
            + ["Dry"] * 8
            + ["Wet", "Wet", "Wet"]
            + ["Dry"] * 10
        ),
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=11,
        fallback_month=10,
        long_period_threshold=12,
        onset_window_months=0,
    )

    recovered = out.loc[out["Date"] == pd.Timestamp("2020-12-01"), "Hydro_Year"].iloc[0]
    preceding = out.loc[out["Date"] == pd.Timestamp("2020-11-01"), "Hydro_Year"].iloc[0]

    assert recovered == preceding + 1
    assert out.loc[out["Date"] == pd.Timestamp("2020-12-01"), "SeasonType"].iloc[0] == "Wet"


def test_assign_hydro_years_bimodal_two_wet_onsets_per_year():
    """Bimodal regime: onset_window_months=None → every Wet onset advances Hydro_Year.

    A pattern with 2 wet seasons per calendar year (e.g. East Africa long rains
    + short rains) should produce 2 Hydro_Year increments per year.
    Hydro_Year is a sequential counter, not a calendar-year label.
    """
    dates = pd.date_range("2020-01-01", periods=24, freq="MS")
    # Two wet seasons per year: Mar-May and Sep-Nov
    season = (
        ["Dry", "Dry",
         "Wet", "Wet", "Wet",   # Mar-May 2020 (first wet)
         "Dry", "Dry", "Dry",
         "Wet", "Wet", "Wet",   # Sep-Nov 2020 (second wet)
         "Dry",
         "Dry", "Dry",
         "Wet", "Wet", "Wet",   # Mar-May 2021
         "Dry", "Dry", "Dry",
         "Wet", "Wet", "Wet",   # Sep-Nov 2021
         "Dry"]
    )
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": season,
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=3,
        fallback_month=3,
        onset_window_months=None,
    )

    # 4 real Wet onsets → initial HY + 4 transitions = 5 distinct Hydro_Year values
    assert out["Hydro_Year"].nunique() == 5

    # Each wet onset increments Hydro_Year relative to the preceding month
    for onset_date in [
        pd.Timestamp("2020-03-01"),
        pd.Timestamp("2020-09-01"),
        pd.Timestamp("2021-03-01"),
        pd.Timestamp("2021-09-01"),
    ]:
        prev_date = onset_date - pd.DateOffset(months=1)
        hy_before = out.loc[out["Date"] == prev_date, "Hydro_Year"].iloc[0]
        hy_at = out.loc[out["Date"] == onset_date, "Hydro_Year"].iloc[0]
        assert hy_at == hy_before + 1
        assert out.loc[out["Date"] == onset_date, "SeasonType"].iloc[0] == "Wet"


def test_assign_hydro_years_iterative_recovery_fills_multi_year_gap():
    """Long gaps recover annual Wet onsets without double-counting duplicates.

    Setup: anchor_month=10, onset_window_months=0 (only exact month 10 accepted).
    Accepted onsets: Oct 2020, Oct 2023 (36-month gap > long_period_threshold=12).
    Filtered out: Mar 2021, Mar 2022.  Mar 2021 belongs to the same unimodal
    seasonal cycle as Oct 2020, while Mar 2022 starts a later cycle.
    """
    dates = pd.date_range("2020-01-01", periods=48, freq="MS")  # Jan 2020 – Dec 2023

    # Build SeasonType: Dry everywhere except 3-month wet windows at each onset
    onset_dates = {
        pd.Timestamp("2020-10-01"),  # accepted (month 10)
        pd.Timestamp("2021-03-01"),  # filtered (month 3)
        pd.Timestamp("2022-03-01"),  # filtered (month 3)
        pd.Timestamp("2023-10-01"),  # accepted (month 10)
    }
    season = []
    for d in dates:
        if any(onset <= d < onset + pd.DateOffset(months=3) for onset in onset_dates):
            season.append("Wet")
        else:
            season.append("Dry")

    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": season,
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=10,
        fallback_month=10,
        long_period_threshold=12,
        onset_window_months=0,
    )

    # Mar 2021 is a duplicate cycle onset; Mar 2022 is recovered as a boundary.
    assert out["Hydro_Year"].nunique() == 4
    assert out.loc[out["Date"] == pd.Timestamp("2021-03-01"), "Hydro_Year"].iloc[0] == 2021
    assert out.loc[out["Date"] == pd.Timestamp("2022-03-01"), "Hydro_Year"].iloc[0] == 2022

    # Every recovered boundary is at a real Wet onset
    hy_changes = out[out["Hydro_Year"].ne(out["Hydro_Year"].shift()) & (out.index > 0)]
    for _, row in hy_changes.iterrows():
        assert row["SeasonType"] == "Wet", (
            f"Hydro_Year changed at {row['Date']} but SeasonType is {row['SeasonType']!r}"
        )


def test_assign_hydro_years_fallback_target_same_year_when_onset_precedes_fallback_month():
    """When the gap-opening onset precedes fallback_month within the same year,
    the recovery target must be fallback_month of the *same* year, not next year.

    The previous bug used ``start.year + 1`` unconditionally, which biased
    candidate selection toward later off-window onsets.

    Setup: anchor_month=4, onset_window_months=0 (only month-4 onsets accepted),
    fallback_month=11.  Accepted: Apr 2020, Apr 2022.  Filtered: Nov 2020, Sep 2021.
    Correct target after Apr 2020: Nov 2020 (same year, since 4 < 11).
    Nov 2020 is 0 months from the target; Sep 2021 is 10 months away.
    The old (buggy) target was Nov 2021, making Sep 2021 the nearest (2 months)
    and skipping the Nov 2020 onset entirely.
    """
    dates = pd.date_range("2020-01-01", periods=36, freq="MS")  # Jan 2020 – Dec 2022

    onset_dates = {
        pd.Timestamp("2020-04-01"),  # accepted  (month 4 == anchor_month)
        pd.Timestamp("2020-11-01"),  # filtered  (month 11 != 4) - should be recovered first
        pd.Timestamp("2021-09-01"),  # filtered  (month 9 ≠ 4) — recovered in 2nd pass
        pd.Timestamp("2022-04-01"),  # accepted  (month 4)
    }
    season = []
    for d in dates:
        if any(onset <= d < onset + pd.DateOffset(months=3) for onset in onset_dates):
            season.append("Wet")
        else:
            season.append("Dry")

    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "SeasonType": season,
    })
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())

    out = assign_hydro_years(
        df,
        hydro_year_start_month=4,
        fallback_month=11,
        long_period_threshold=14,
        onset_window_months=0,
    )

    # Nov 2020 must be recovered as a Hydro_Year boundary (same-year target fix).
    # With the old code Nov 2020 was skipped because the target was Nov 2021,
    # making Sep 2021 (2 months away) win over Nov 2020 (12 months away).
    oct20_hy = out.loc[out["Date"] == pd.Timestamp("2020-10-01"), "Hydro_Year"].iloc[0]
    nov20_hy = out.loc[out["Date"] == pd.Timestamp("2020-11-01"), "Hydro_Year"].iloc[0]
    assert nov20_hy == oct20_hy + 1, "Nov 2020 onset should start a new Hydro_Year"
    assert out.loc[out["Date"] == pd.Timestamp("2020-11-01"), "SeasonType"].iloc[0] == "Wet"

    # All HY changes must fall on real Wet onsets
    hy_changes = out[out["Hydro_Year"].ne(out["Hydro_Year"].shift()) & (out.index > 0)]
    for _, row in hy_changes.iterrows():
        assert row["SeasonType"] == "Wet"


def test_assign_hydro_year_start_month_1():
    """Verify that start_month=1 maps to calendar year (no +1 offset)."""
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
    })
    
    # Test assign_fixed_hydro_year
    fixed = assign_fixed_hydro_year(df, start_month=1)
    assert (fixed["Hydro_Year_fixed"] == 2020).all()

    # Test assign_hydro_years
    df["SeasonType"] = ["Wet"] * 3 + ["Dry"] * 9
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())
    
    out = assign_hydro_years(
        df,
        hydro_year_start_month=1,
        fallback_month=1,
        onset_window_months=1,
    )
    assert (out["Hydro_Year"] == 2020).all()
