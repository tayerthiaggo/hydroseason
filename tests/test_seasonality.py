import numpy as np
import pandas as pd

import hydroseason.seasonality as seasonality
from hydroseason.seasonality import (
    classify_regime_from_stl,
    classify_regime_with_rainfall_si,
    detect_seasonality_regime,
    stl_residuals,
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
    monthly_df["Date"] = pd.to_datetime(
        monthly_df[["Year", "Month"]].assign(day=1)
    )
    s = stl_seasonality_strength(monthly_df)
    assert 0.0 <= s <= 1.0


def test_stl_residuals_align_to_input_rows(monthly_df: pd.DataFrame):
    monthly_df["Date"] = pd.to_datetime(
        monthly_df[["Year", "Month"]].assign(day=1)
    )
    residuals = stl_residuals(monthly_df)
    assert residuals.index.equals(monthly_df.index)
    assert len(residuals) == len(monthly_df)
    assert residuals.notna().all()


def test_detect_regime_returns_all_fields(monthly_df: pd.DataFrame, monkeypatch):
    monthly_df["Date"] = pd.to_datetime(
        monthly_df[["Year", "Month"]].assign(day=1)
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("KMeans diagnostic should be opt-in")

    monkeypatch.setattr(seasonality, "kmeans_silhouette_diagnostic", fail_if_called)
    r = detect_seasonality_regime(monthly_df, rainfall_si_override=True)
    assert r.regime in {"non_seasonal", "borderline", "seasonal"}
    assert 0.0 <= r.stl_strength <= 1.0
    assert isinstance(r.si, float)
    assert r.silhouette is None
    assert r.regime_source in {"eta_squared", "eta_squared_confirmed", "concentration", "all_weak"}


def test_detect_regime_can_report_legacy_kmeans_silhouette(
    monthly_df: pd.DataFrame, monkeypatch
):
    monthly_df["Date"] = pd.to_datetime(
        monthly_df[["Year", "Month"]].assign(day=1)
    )
    monkeypatch.setattr(
        seasonality,
        "kmeans_silhouette_diagnostic",
        lambda *args, **kwargs: 0.42,
    )

    r = detect_seasonality_regime(
        monthly_df,
        rainfall_si_override=True,
        report_silhouette=True,
    )

    assert r.silhouette == 0.42


def test_eta_squared_seasonality_score():
    # Uniform profile (low eta squared)
    months = np.tile(np.arange(1, 13), 10)
    rainfall = np.ones(120) * 50.0
    # Add minor noise so ss_total > 0
    rainfall[0] += 1.0
    rainfall[1] -= 1.0
    df = pd.DataFrame({"Month": months, "Rainfall_mm": rainfall})
    eta_sq = seasonality.eta_squared_seasonality_score(df)
    assert eta_sq <= 0.11

    # Highly seasonal profile (high eta squared)
    rainfall_seasonal = np.array([10.0, 10.0, 10.0, 100.0, 100.0, 100.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    rainfall = np.tile(rainfall_seasonal, 10)
    df_seasonal = pd.DataFrame({"Month": months, "Rainfall_mm": rainfall})
    eta_sq_seasonal = seasonality.eta_squared_seasonality_score(df_seasonal)
    assert eta_sq_seasonal > 0.6


def test_circular_concentration_R():
    months = np.tile(np.arange(1, 13), 5)
    # Uniform
    rainfall_uniform = np.ones(60) * 30.0
    df_uniform = pd.DataFrame({"Month": months, "Rainfall_mm": rainfall_uniform})
    r_val = seasonality.circular_concentration_R(df_uniform)
    assert np.isclose(r_val, 0.0)

    # All rainfall in one month
    rainfall_one_month = np.zeros(12)
    rainfall_one_month[0] = 100.0
    df_one = pd.DataFrame({"Month": np.arange(1, 13), "Rainfall_mm": rainfall_one_month})
    r_val_one = seasonality.circular_concentration_R(df_one)
    assert np.isclose(r_val_one, 1.0)


def test_classify_regime_composite():
    # Strong eta_squared
    regime, source = seasonality.classify_regime_composite(eta_sq=0.40, circular_R=0.10, si=0.10)
    assert regime == "seasonal"
    assert source == "eta_squared"

    # Moderate eta_squared confirmed by circular_R
    regime, source = seasonality.classify_regime_composite(eta_sq=0.25, circular_R=0.45, si=0.10)
    assert regime == "seasonal"
    assert source == "eta_squared_confirmed"

    # Borderline concentration
    regime, source = seasonality.classify_regime_composite(eta_sq=0.12, circular_R=0.20, si=0.20)
    assert regime == "borderline"
    assert source == "concentration"

    # All weak
    regime, source = seasonality.classify_regime_composite(eta_sq=0.05, circular_R=0.15, si=0.15)
    assert regime == "non_seasonal"
    assert source == "all_weak"

