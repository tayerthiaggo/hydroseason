"""Tests for canonical extent table fingerprinting."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from hydroseason import extent_fingerprint
from hydroseason._fingerprint import canonical_extent_payload


@pytest.fixture
def sample_extent() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    return pd.DataFrame(
        {
            "extent_pct": [10.0, 12.5, 25.0, 45.0, 60.0, 75.0, 50.0, 30.0, 20.0, 15.0, 12.0, 10.5],
            "invalid_pct": [0.0, 2.5, 0.0, 5.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 3.0, 0.0],
        },
        index=dates,
    )


def test_fingerprint_determinism(sample_extent):
    fp1 = extent_fingerprint(sample_extent)
    fp2 = extent_fingerprint(sample_extent)
    assert fp1 == fp2
    assert len(fp1) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", fp1) is not None


def test_fingerprint_sorting_invariance(sample_extent):
    shuffled = sample_extent.sample(frac=1.0, random_state=42)
    assert not shuffled.index.equals(sample_extent.index)
    assert extent_fingerprint(shuffled) == extent_fingerprint(sample_extent)


def test_fingerprint_duplicate_month_rejection():
    dates = [
        pd.Timestamp("2020-01-05"),
        pd.Timestamp("2020-01-20"),
        pd.Timestamp("2020-02-01"),
    ]
    df = pd.DataFrame({"extent_pct": [10.0, 12.0, 15.0]}, index=dates)
    with pytest.raises(ValueError, match="duplicate month timestamps"):
        extent_fingerprint(df)


def test_fingerprint_column_filtering(sample_extent):
    with_extras = sample_extent.copy()
    with_extras["extra_comment"] = "station_alpha"
    with_extras["operator_flag"] = 42
    with_extras["quality_note"] = "verified"

    assert extent_fingerprint(with_extras) == extent_fingerprint(sample_extent)


def test_fingerprint_column_order_invariance(sample_extent):
    reordered = sample_extent[["invalid_pct", "extent_pct"]]
    assert extent_fingerprint(reordered) == extent_fingerprint(sample_extent)


def test_fingerprint_value_col_mapping():
    dates = pd.date_range("2020-01-01", periods=6, freq="MS")
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    standard = pd.DataFrame({"extent_pct": values}, index=dates)
    custom = pd.DataFrame({"water_fraction_pct": values}, index=dates)

    assert extent_fingerprint(custom, value_col="water_fraction_pct") == extent_fingerprint(standard)


def test_fingerprint_date_col_support():
    dates = pd.date_range("2020-01-01", periods=6, freq="MS")
    indexed = pd.DataFrame({"extent_pct": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=dates)
    columnar = pd.DataFrame(
        {
            "obs_date": dates,
            "extent_pct": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )

    assert extent_fingerprint(columnar, date_col="obs_date") == extent_fingerprint(indexed)


def test_fingerprint_float_representation_and_zero_sign():
    dates = pd.date_range("2020-01-01", periods=3, freq="MS")
    pos_zero = pd.DataFrame({"extent_pct": [0.0, 10.0, 20.0]}, index=dates)
    neg_zero = pd.DataFrame({"extent_pct": [-0.0, 10.0, 20.0]}, index=dates)

    assert extent_fingerprint(pos_zero) == extent_fingerprint(neg_zero)


def test_fingerprint_null_handling():
    dates = pd.date_range("2020-01-01", periods=3, freq="MS")
    with_nan = pd.DataFrame({"extent_pct": [10.0, np.nan, 20.0]}, index=dates)
    with_zero = pd.DataFrame({"extent_pct": [10.0, 0.0, 20.0]}, index=dates)

    assert extent_fingerprint(with_nan) != extent_fingerprint(with_zero)

    payload = canonical_extent_payload(with_nan)
    assert "2020-02-01,null" in payload


def test_fingerprint_count_columns_included():
    dates = pd.date_range("2020-01-01", periods=3, freq="MS")
    df = pd.DataFrame(
        {
            "extent_pct": [10.0, 20.0, 30.0],
            "invalid_pct": [0.0, 0.0, 0.0],
            "n_water": [100, 200, 300],
            "n_valid": [1000, 1000, 1000],
            "n_invalid": [0, 0, 0],
            "n_aoi": [1000, 1000, 1000],
        },
        index=dates,
    )
    payload = canonical_extent_payload(df)
    assert payload.splitlines()[1] == "date,extent_pct,invalid_pct,n_water,n_valid,n_invalid,n_aoi"
    assert "2020-01-01,10.0,0.0,100,1000,0,1000" in payload


def test_canonical_payload_schema_prefix(sample_extent):
    payload = canonical_extent_payload(sample_extent)
    assert payload.startswith("hydroseason-extent-v1\n")
    lines = payload.splitlines()
    assert lines[0] == "hydroseason-extent-v1"
    assert lines[1] == "date,extent_pct,invalid_pct"


def test_fingerprint_series_input():
    dates = pd.date_range("2020-01-01", periods=4, freq="MS")
    series = pd.Series([10.0, 20.0, 30.0, 40.0], index=dates, name="extent_pct")
    frame = series.to_frame()
    assert extent_fingerprint(series) == extent_fingerprint(frame)