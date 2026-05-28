import numpy as np
import pandas as pd

from hydroseason.seasonality import (
    classify_regime_from_stl,
    classify_regime_with_rainfall_si,
    detect_seasonality_regime,
    stl_seasonality_strength,
    walsh_lawler_seasonality_index,
)


def test_walsh_lawler_uniform_is_zero():
    assert walsh_lawler_seasonality_index(np.ones(12)) == 0.0


def test_walsh_lawler_strong_seasonality(monthly_df: pd.DataFrame):
    clim = monthly_df.groupby("Month")["Rainfall_mm"].mean().reindex(range(1, 13), fill_value=0.0)
    assert walsh_lawler_seasonality_index(clim.values) > 0.6


def test_classify_regime_from_stl_thresholds():
    assert classify_regime_from_stl(0.1) == "non_seasonal"
    assert classify_regime_from_stl(0.45) == "borderline"
    assert classify_regime_from_stl(0.8) == "seasonal"


def test_rainfall_si_override_promotes_borderline_series():
    regime, source = classify_regime_with_rainfall_si(0.56, 1.0)
    assert regime == "seasonal"
    assert source == "rainfall_si_override"

    regime, source = classify_regime_with_rainfall_si(0.2, 1.0)
    assert regime == "non_seasonal"
    assert source == "stl"


def test_stl_strength_in_unit_interval(monthly_df: pd.DataFrame):
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    s = stl_seasonality_strength(monthly_df)
    assert 0.0 <= s <= 1.0


def test_detect_regime_returns_all_fields(monthly_df: pd.DataFrame):
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    r = detect_seasonality_regime(monthly_df, rainfall_si_override=True)
    assert r.regime in {"non_seasonal", "borderline", "seasonal"}
    assert 0.0 <= r.stl_strength <= 1.0
    assert isinstance(r.si, float)
    assert r.regime_source in {"stl", "rainfall_si_override"}
