import numpy as np
import pandas as pd
import pytest

from hydroseason._state_input import prepare_monthly_extent


def test_invalid_percentage_is_converted_to_fraction_once():
    frame = pd.DataFrame(
        {"extent_pct": [40.0], "invalid_pct": [5.0]},
        index=pd.to_datetime(["2020-01-01"]),
    )
    result = prepare_monthly_extent(frame)
    assert result.iloc[0]["observed_fraction"] == pytest.approx(0.95)
    assert result.iloc[0]["quality_state"] == "usable"
    assert bool(result.iloc[0]["candidate_usable"])


def test_quality_states_are_explicit_and_unknown_is_fail_closed():
    index = pd.date_range("2020-01-01", periods=4, freq="MS")
    frame = pd.DataFrame(
        {"extent_pct": [10.0, 20.0, np.nan, 40.0], "invalid_pct": [0.0, 21.0, 100.0, np.nan]},
        index=index,
    )
    result = prepare_monthly_extent(frame)
    assert result["quality_state"].tolist() == ["usable", "low", "missing", "unknown"]
    assert result["candidate_usable"].tolist() == [True, False, False, False]


def test_counts_are_authoritative_and_gap_month_is_missing():
    frame = pd.DataFrame(
        {
            "n_water": [20, 30], "n_valid": [80, 60],
            "n_invalid": [20, 40], "n_aoi": [100, 100],
            "extent_pct": [99.0, 99.0],
        },
        index=pd.to_datetime(["2020-01-01", "2020-03-01"]),
    )
    result = prepare_monthly_extent(frame)
    assert result.loc["2020-01-01", "extent_pct"] == pytest.approx(25.0)
    assert result.loc["2020-03-01", "invalid_pct"] == pytest.approx(40.0)
    assert result.loc["2020-02-01", "quality_state"] == "missing"


def test_unknown_quality_can_be_explicitly_enabled():
    series = pd.Series([12.0], index=pd.to_datetime(["2020-01-01"]))
    assert prepare_monthly_extent(series)["candidate_usable"].tolist() == [False]
    assert prepare_monthly_extent(series, allow_unknown_quality=True)["candidate_usable"].tolist() == [True]


def test_flag_quality_policy_keeps_high_invalid_observed_values_usable():
    frame = pd.DataFrame(
        {"extent_pct": [10.0, 20.0], "invalid_pct": [0.0, 90.0]},
        index=pd.date_range("2020-01-01", periods=2, freq="MS"),
    )

    prepared = prepare_monthly_extent(frame, max_invalid_pct=10.0, quality_policy="flag")

    assert prepared["quality_state"].tolist() == ["usable", "low"]
    assert prepared["candidate_usable"].tolist() == [True, True]
