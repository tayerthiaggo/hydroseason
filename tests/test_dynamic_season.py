import pandas as pd

from hydroseason.dynamic_season import (
    harmonize_with_zero_preservation,
    refine_season_tails,
    segment_main_wet_season_fixed_threshold,
)
from hydroseason.hydro_year import assign_fixed_hydro_year


def test_harmonize_preserves_zeros():
    df = pd.DataFrame({"Rainfall_mm": [0.0, 0.0, 5.0, 10.0, 20.0, 5.0, 0.0, 0.0]})
    out = harmonize_with_zero_preservation(df, window=3)
    # Zeros adjacent to zero must stay zero
    assert out.loc[0, "Smoothed"] == 0
    assert out.loc[1, "Smoothed"] == 0
    assert out.loc[6, "Smoothed"] == 0
    assert out.loc[7, "Smoothed"] == 0


def test_segment_picks_dominant_block(monthly_df: pd.DataFrame):
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    work = assign_fixed_hydro_year(monthly_df, start_month=11)
    work = harmonize_with_zero_preservation(work, window=3)
    seg, boundaries = segment_main_wet_season_fixed_threshold(
        work, threshold=float(work[work["Rainfall_mm"] > 0]["Rainfall_mm"].quantile(0.2))
    )
    assert "SeasonType" in seg.columns
    # at least one wet block per year
    assert (boundaries["WetStart"].notna()).any()


def test_refine_hysteresis_extends_wet_tails():
    """Regression for the dead-elif bug: Wet→Dry tail refinement must actually fire."""
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [100, 50, 0, 0, 0, 0, 0, 0, 0, 50, 100, 100],
        "SeasonType": ["Wet", "Wet", "Dry", "Dry", "Dry", "Dry",
                       "Dry", "Dry", "Dry", "Dry", "Wet", "Wet"],
    })
    refined = refine_season_tails(df, threshold_high=40.0, threshold_low=0.0)
    # The Oct=50 month preceding the Nov-Dec Wet block must now be Wet.
    assert refined.loc[refined["Date"] == pd.Timestamp("2020-10-01"), "SeasonType"].iloc[0] == "Wet"


def test_refine_legacy_threshold_argument():
    dates = pd.date_range("2020-01-01", periods=6, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [10, 50, 100, 100, 50, 10],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Dry", "Dry"],
    })
    out = refine_season_tails(df, threshold=40.0)
    assert "SeasonType" in out.columns
