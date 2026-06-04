import pandas as pd

from hydroseason.dynamic_season import (
    harmonize_with_zero_preservation,
    segment_main_wet_season_fixed_threshold,
)
from hydroseason.hydro_year import assign_fixed_hydro_year, assign_hydro_years
from hydroseason.metrics import compute_annual_spi_categories, compute_season_metrics


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


def test_compute_annual_spi_categories_non_default_value_col(monthly_df: pd.DataFrame):
    """Verify compute_annual_spi_categories handles non-default value_col and falls back to dry_month_count."""
    monthly_df = monthly_df.rename(columns={"Rainfall_mm": "Q_mm"})
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    work = assign_fixed_hydro_year(monthly_df, start_month=11)
    work["SeasonType"] = ["Wet"] * 6 + ["Dry"] * 6 + ["Wet"] * 6 + ["Dry"] * 6 + ["Wet"] * 6 + ["Dry"] * 6
    work["Hydro_Year"] = work["Hydro_Year_fixed"]
    
    # This creates dry_month_count (lowercase) but NOT Dry_month_count (capitalised)
    out = compute_season_metrics(work, value_col="Q_mm")
    assert "dry_month_count" in out.columns
    assert "Dry_month_count" not in out.columns

    # Call compute_annual_spi_categories with Q_mm
    out = compute_annual_spi_categories(out, value_col="Q_mm")
    
    # Drought_Category should correctly evaluate based on dry_month_count, not silently default to "Regular"
    assert "Drought_Category" in out.columns
    # dry_month_count = 6 -> "Regular"
    # dry_month_count = 2 -> "Minimal"
    assert (out.loc[out["dry_month_count"] == 6, "Drought_Category"] == "Regular").all()
    assert (out.loc[out["dry_month_count"] == 2, "Drought_Category"] == "Minimal").all()

    # If we artificially set dry_month_count to 9, it should change to "Prolonged"
    out["dry_month_count"] = 9
    out = compute_annual_spi_categories(out, value_col="Q_mm")
    assert (out["Drought_Category"] == "Prolonged").all()


def test_annual_spi_uses_sample_standard_deviation():
    df = pd.DataFrame(
        {
            "Hydro_Year": [2001, 2002, 2003],
            "Rainfall_mm": [100.0, 200.0, 400.0],
            "Dry_month_count": [3, 3, 3],
        }
    )

    out = compute_annual_spi_categories(df)
    annual = out.drop_duplicates("Hydro_Year").set_index("Hydro_Year")["Annual_SPI"]

    assert annual.loc[2001] == -0.873
    assert annual.loc[2002] == -0.218
    assert annual.loc[2003] == 1.091

