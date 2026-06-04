import pandas as pd
import pytest

from hydroseason.validate import validate_monthly_input


def test_validate_clean_input(monthly_df: pd.DataFrame):
    cleaned, report = validate_monthly_input(monthly_df)
    assert report.ok
    assert report.inferred_freq == "MS"
    assert report.n_rows_out == len(monthly_df)


def test_validate_missing_value_column():
    df = pd.DataFrame({"Date": pd.date_range("2020-01-01", periods=24, freq="MS")})
    _, report = validate_monthly_input(df)
    assert not report.ok
    assert any("Rainfall_mm" in e for e in report.errors)


def test_validate_missing_value_column_lists_available_columns():
    """The missing-value-column error should name the available columns and suggest value_col."""
    df = pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=24, freq="MS"),
        "precip": [1.0] * 24,
    })
    _, report = validate_monthly_input(df)
    assert not report.ok
    joined = " ".join(report.errors)
    assert "precip" in joined
    assert "value_col" in joined


def test_validate_duplicate_dates_exact_recoverable():
    """Exact duplicate rows (same date AND same value) are auto-dropped with a warning."""
    df = pd.DataFrame({
        "Date": list(pd.date_range("2020-01-01", periods=24, freq="MS")) + [pd.Timestamp("2020-01-01")],
        "Rainfall_mm": [1.0] * 25,
    })
    cleaned, report = validate_monthly_input(df)
    assert report.ok  # auto-recovered
    assert any("duplicate" in w.lower() for w in report.warnings)
    assert len(cleaned) == 24  # duplicate row removed


def test_validate_duplicate_dates_conflicting_errors():
    """Duplicate dates with different values cannot be auto-resolved — must be an error."""
    df = pd.DataFrame({
        "Date": list(pd.date_range("2020-01-01", periods=24, freq="MS")) + [pd.Timestamp("2020-01-01")],
        "Rainfall_mm": [1.0] * 24 + [999.0],  # conflicting value for Jan 2020
    })
    _, report = validate_monthly_input(df)
    assert not report.ok
    assert any("duplicate" in e.lower() for e in report.errors)


def test_validate_too_short():
    df = pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=12, freq="MS"),
        "Rainfall_mm": [1.0] * 12,
    })
    _, report = validate_monthly_input(df)
    assert not report.ok
    assert any("24 months" in e for e in report.errors)


def test_validate_fills_gap_and_warns():
    dates = list(pd.date_range("2020-01-01", periods=12, freq="MS"))
    dates += list(pd.date_range("2021-03-01", periods=24, freq="MS"))  # 2-month gap
    df = pd.DataFrame({"Date": dates, "Rainfall_mm": [10.0] * len(dates)})
    cleaned, report = validate_monthly_input(df, max_fraction_missing=0.20)
    assert report.ok
    assert report.n_imputed == 2
    assert any("climatological mean" in w for w in report.warnings)
    assert "Imputed" in cleaned.columns
    assert int(cleaned["Imputed"].sum()) == 2


def test_validate_refuses_very_long_gap_imputation():
    dates = list(pd.date_range("2000-01-01", periods=24, freq="MS"))
    dates += list(pd.date_range("2005-01-01", periods=24, freq="MS"))
    df = pd.DataFrame({"Date": dates, "Rainfall_mm": [10.0] * len(dates)})

    _, report = validate_monthly_input(
        df,
        max_fraction_missing=0.80,
        max_consecutive_imputation_gap=12,
    )

    assert not report.ok
    assert any("Refusing to impute" in e for e in report.errors)


def test_validate_daily_input_aggregated_to_monthly():
    """Daily rainfall input should be automatically summed to monthly totals."""
    dates = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    df = pd.DataFrame({"Date": dates, "Rainfall_mm": 1.0})  # 1 mm per day
    cleaned, report = validate_monthly_input(df)
    assert report.ok
    assert any("Sub-monthly" in w for w in report.warnings)
    assert len(cleaned) == 24
    # January 2020 = 31 days × 1 mm = 31 mm
    jan2020 = cleaned[(cleaned["Year"] == 2020) & (cleaned["Month"] == 1)]["Rainfall_mm"].iloc[0]
    assert abs(jan2020 - 31.0) < 0.01


def test_validate_climatology_fill_preserves_seasonal_peak():
    """Missing month should be filled with calendar-month mean, not linear interpolation.

    A missing January surrounded by dry months would receive ~0 mm from linear
    interpolation but the correct climatological mean (~100 mm) from the WMO method.
    """
    rows = []
    for year in [2020, 2021, 2022]:
        for month in range(1, 13):
            # January is the wet peak (100 mm); all other months are dry (1 mm)
            val = 100.0 if month == 1 else 1.0
            rows.append({"Date": pd.Timestamp(year=year, month=month, day=1), "Rainfall_mm": val})
    df = pd.DataFrame(rows)
    # Remove January 2021
    df = df[~((df["Date"].dt.year == 2021) & (df["Date"].dt.month == 1))].reset_index(drop=True)

    cleaned, report = validate_monthly_input(df, max_fraction_missing=0.20)
    assert report.ok
    assert report.n_imputed == 1
    jan2021 = cleaned[(cleaned["Year"] == 2021) & (cleaned["Month"] == 1)]["Rainfall_mm"].iloc[0]
    # Climatology fill gives ~100 mm (mean of other Januaries)
    # Linear interpolation would give ~1 mm (average of Dec 2020 and Feb 2021)
    assert jan2021 > 50.0, f"Expected ~100 mm from climatology fill, got {jan2021:.1f} mm"


def test_validate_year_month_input(monthly_df: pd.DataFrame):
    df = monthly_df[["Year", "Month", "Rainfall_mm"]].copy()
    cleaned, report = validate_monthly_input(df)
    assert report.ok
    assert "Date" in cleaned.columns


def test_validate_clips_negative_rainfall_with_warning():
    df = pd.DataFrame(
        {
            "Date": pd.date_range("2020-01-01", periods=24, freq="MS"),
            "Rainfall_mm": [10.0] * 23 + [-1.5],
        }
    )

    cleaned, report = validate_monthly_input(df)

    assert report.ok
    assert cleaned["Rainfall_mm"].min() == 0.0
    assert any("negative values" in warning for warning in report.warnings)


def test_validate_duplicate_dates_metadata_ignored():
    """Duplicate dates with identical rainfall should be recovered even if other columns differ."""
    df = pd.DataFrame({
        "Date": list(pd.date_range("2020-01-01", periods=24, freq="MS")) + [pd.Timestamp("2020-01-01")],
        "Rainfall_mm": [1.0] * 25,
        "Extra_Metadata": ["original"] * 24 + ["different"],
    })
    cleaned, report = validate_monthly_input(df)
    assert report.ok
    assert len(cleaned) == 24
    assert any("duplicate" in w.lower() for w in report.warnings)
