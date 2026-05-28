import pandas as pd

from hydroseason.dynamic_season import (
    harmonize_with_zero_preservation,
    segment_main_wet_season_fixed_threshold,
)
from hydroseason.hydro_year import assign_fixed_hydro_year, assign_hydro_years
from hydroseason.metrics import compute_season_metrics


def test_compute_season_metrics_columns(monthly_df: pd.DataFrame):
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    work = assign_fixed_hydro_year(monthly_df, start_month=11)
    work = harmonize_with_zero_preservation(work, window=3)
    seg, _ = segment_main_wet_season_fixed_threshold(work)
    hydro = assign_hydro_years(seg, hydro_year_start_month=11)
    out = compute_season_metrics(hydro)
    for col in ["dry_event_count", "dry_total", "wet_total", "dry_month_count", "wet_month_count"]:
        assert col in out.columns
    # rainfall-aliased columns preserved
    for col in ["Rain_dry_season_mm", "Rain_wet_season_mm", "Dry_month_count"]:
        assert col in out.columns


def test_metrics_value_col_arg(monthly_df: pd.DataFrame):
    """Regression: value_col now parameterised."""
    monthly_df = monthly_df.rename(columns={"Rainfall_mm": "Q_mm"})
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    work = assign_fixed_hydro_year(monthly_df, start_month=11)
    work["SeasonType"] = ["Wet"] * 6 + ["Dry"] * 6 + ["Wet"] * 6 + ["Dry"] * 6 + ["Wet"] * 6 + ["Dry"] * 6
    work["Hydro_Year"] = work["Hydro_Year_fixed"]
    out = compute_season_metrics(work, value_col="Q_mm")
    assert "wet_total_Q_mm" in out.columns
    assert "dry_total_Q_mm" in out.columns
