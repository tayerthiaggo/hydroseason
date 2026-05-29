"""Tests for hydroseason.io — SILO and BoM monthly readers."""

from pathlib import Path

import pandas as pd
import pytest

from hydroseason.io import read_bom_monthly, read_rainfall, read_silo

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# read_silo — fixed formats
# ---------------------------------------------------------------------------


class TestReadSiloFixed:
    def test_daily_rainonly_returns_monthly_totals(self):
        """Daily SILO Rain Only → 3 monthly rows with correct sums."""
        df = read_silo(FIXTURES / "silo_rainonly_daily.txt")

        assert list(df.columns) == ["Date", "Year", "Month", "Rainfall_mm"]
        assert len(df) == 3

        jan = df[df["Month"] == 1]["Rainfall_mm"].iloc[0]
        feb = df[df["Month"] == 2]["Rainfall_mm"].iloc[0]
        mar = df[df["Month"] == 3]["Rainfall_mm"].iloc[0]

        assert jan == pytest.approx(15.0)
        assert feb == pytest.approx(10.0)
        assert mar == pytest.approx(6.5)

    def test_daily_output_dtypes(self):
        df = read_silo(FIXTURES / "silo_rainonly_daily.txt")

        assert pd.api.types.is_datetime64_any_dtype(df["Date"])
        assert pd.api.types.is_integer_dtype(df["Year"])
        assert pd.api.types.is_integer_dtype(df["Month"])
        assert pd.api.types.is_float_dtype(df["Rainfall_mm"])

    def test_daily_date_is_first_of_month(self):
        df = read_silo(FIXTURES / "silo_rainonly_daily.txt")
        assert (df["Date"].dt.day == 1).all()

    def test_monthly_format_no_aggregation(self):
        """SILO monthly-summary fixture: 3 rows, values unchanged."""
        df = read_silo(FIXTURES / "silo_monthly.txt")

        assert len(df) == 3
        assert df.loc[df["Month"] == 1, "Rainfall_mm"].iloc[0] == pytest.approx(120.5)
        assert df.loc[df["Month"] == 2, "Rainfall_mm"].iloc[0] == pytest.approx(230.8)
        assert df.loc[df["Month"] == 3, "Rainfall_mm"].iloc[0] == pytest.approx(50.0)

    def test_monthly_year_and_month_columns(self):
        df = read_silo(FIXTURES / "silo_monthly.txt")
        assert list(df["Year"].unique()) == [2010]
        assert sorted(df["Month"].tolist()) == [1, 2, 3]

    def test_custom_output_col_name(self):
        df = read_silo(FIXTURES / "silo_monthly.txt", output_col="Rain_mm")
        assert "Rain_mm" in df.columns
        assert "Rainfall_mm" not in df.columns

    def test_sorted_ascending(self):
        df = read_silo(FIXTURES / "silo_rainonly_daily.txt")
        assert list(df["Month"]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# read_silo — custom CSV (no header block)
# ---------------------------------------------------------------------------


class TestReadSiloCustomCSV:
    def test_basic_read(self):
        df = read_silo(FIXTURES / "silo_custom.csv")

        assert list(df.columns) == ["Date", "Year", "Month", "Rainfall_mm"]
        assert len(df) == 3

    def test_values_correct(self):
        df = read_silo(FIXTURES / "silo_custom.csv")

        assert df.loc[df["Month"] == 1, "Rainfall_mm"].iloc[0] == pytest.approx(120.5)
        assert df.loc[df["Month"] == 2, "Rainfall_mm"].iloc[0] == pytest.approx(230.8)
        assert df.loc[df["Month"] == 3, "Rainfall_mm"].iloc[0] == pytest.approx(50.0)

    def test_extra_columns_ignored(self):
        df = read_silo(FIXTURES / "silo_custom.csv")
        assert "MaxT" not in df.columns
        assert "MinT" not in df.columns

    def test_unknown_variable_raises(self):
        with pytest.raises(ValueError, match="not found"):
            read_silo(FIXTURES / "silo_custom.csv", variable="Evap")


# ---------------------------------------------------------------------------
# read_bom_monthly
# ---------------------------------------------------------------------------


class TestReadBomMonthly:
    def test_basic_read_quality_filtered(self):
        """Quality='N' row (April) is dropped by default."""
        df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv")

        assert list(df.columns) == ["Date", "Year", "Month", "Rainfall_mm"]
        # April has Quality=N, so only 4 rows remain
        assert len(df) == 4
        assert 4 not in df["Month"].tolist()

    def test_quality_filter_disabled(self):
        df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv", quality_filter=False)
        assert len(df) == 5
        assert 4 in df["Month"].tolist()

    def test_values_correct(self):
        df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv")

        assert df.loc[df["Month"] == 1, "Rainfall_mm"].iloc[0] == pytest.approx(120.5)
        assert df.loc[df["Month"] == 2, "Rainfall_mm"].iloc[0] == pytest.approx(230.8)
        assert df.loc[df["Month"] == 5, "Rainfall_mm"].iloc[0] == pytest.approx(1.5)

    def test_output_dtypes(self):
        df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv")

        assert pd.api.types.is_datetime64_any_dtype(df["Date"])
        assert pd.api.types.is_integer_dtype(df["Year"])
        assert pd.api.types.is_integer_dtype(df["Month"])
        assert pd.api.types.is_float_dtype(df["Rainfall_mm"])

    def test_date_is_first_of_month(self):
        df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv")
        assert (df["Date"].dt.day == 1).all()

    def test_custom_output_col(self):
        df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv", output_col="Rain_mm")
        assert "Rain_mm" in df.columns

    def test_custom_value_col_override(self):
        df = read_bom_monthly(
            FIXTURES / "bom_idcjac0001.csv",
            value_col="Monthly Precipitation Total (millimetres)",
        )
        assert len(df) == 4

    def test_bad_value_col_raises(self):
        with pytest.raises(ValueError, match="not found"):
            read_bom_monthly(FIXTURES / "bom_idcjac0001.csv", value_col="NoSuchCol")

    def test_sorted_ascending(self):
        df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv")
        assert list(df["Month"]) == [1, 2, 3, 5]


class TestReadRainfall:
    def test_auto_detects_bom(self):
        df = read_rainfall(FIXTURES / "bom_idcjac0001.csv")
        assert list(df.columns) == ["Date", "Year", "Month", "Rainfall_mm"]
        assert len(df) == 4

    def test_auto_detects_silo(self):
        df = read_rainfall(FIXTURES / "silo_monthly.txt")
        assert list(df.columns) == ["Date", "Year", "Month", "Rainfall_mm"]
        assert len(df) == 3

    def test_csv_mode_falls_back_to_pandas(self):
        df = read_rainfall(FIXTURES / "silo_custom.csv", source="csv")
        assert "Date" in df.columns
        assert "Rain" in df.columns


# ---------------------------------------------------------------------------
# Integration: readers → validate_monthly_input
# ---------------------------------------------------------------------------


def test_silo_output_passes_validation():
    """read_silo output has the columns validate_monthly_input expects."""
    from hydroseason.validate import validate_monthly_input

    df = read_silo(FIXTURES / "silo_monthly.txt")
    # Use a loose missing-data threshold so the tiny fixture doesn't trip
    # the >=24-month check (that's a pipeline concern, not a reader concern).
    _, report = validate_monthly_input(df, max_fraction_missing=1.0)

    # No format errors (wrong columns, non-numeric values, etc.)
    format_errors = [e for e in report.errors if "months" not in e.lower()]
    assert format_errors == []


def test_bom_output_passes_validation():
    """read_bom_monthly output has the columns validate_monthly_input expects."""
    from hydroseason.validate import validate_monthly_input

    df = read_bom_monthly(FIXTURES / "bom_idcjac0001.csv")
    # Relax thresholds so the tiny fixture (4 rows, 1 gap) doesn't trigger
    # data-sufficiency errors — those are pipeline concerns, not reader concerns.
    _, report = validate_monthly_input(df, max_fraction_missing=1.0)

    format_errors = [e for e in report.errors if "months" not in e.lower()]
    assert format_errors == []
