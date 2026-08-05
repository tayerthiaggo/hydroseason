import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._regime_compare import compare_extent_and_rainfall_regimes
from hydroseason._report_copy import build_rainfall_context, select_kpis, verdict_sentence


@pytest.fixture
def seasonal_analysis():
    dates = pd.date_range("2010-01-01", "2015-12-01", freq="MS")
    records = []
    for date in dates:
        month = date.month
        val = 10.0 + 30.0 * np.sin(2 * np.pi * (month - 1) / 12) + np.random.normal(0, 0.5)
        records.append({"extent_pct": max(0.0, min(100.0, val)), "invalid_pct": 0.0})
    df = pd.DataFrame(records, index=dates)
    return analyze_catchment(df, phase_model="rule_based", n_bootstrap=40)


@pytest.fixture
def aseasonal_analysis():
    years = 10
    rng = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=12 * years, freq="MS")
    values = np.abs(rng.normal(0.15, 0.12, 12 * years))
    df = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    return analyze_catchment(df, phase_model="rule_based", n_bootstrap=40)


def test_aseasonal_copy_never_mentions_hydrological_year(aseasonal_analysis):
    sentence = verdict_sentence(aseasonal_analysis).casefold()
    assert "no stable annual cycle" in sentence
    assert "use wet events" in sentence
    assert "hydrological-year boundaries" not in sentence
    assert len(select_kpis(aseasonal_analysis)) == 10


def test_seasonal_kpis_include_complete_year_count(seasonal_analysis):
    kpis = select_kpis(seasonal_analysis)
    labels = [item["label"] for item in kpis]
    assert labels == [
        "hydrological years",
        "mean annual amplitude",
        "mean cycle length",
        "Typical peak month",
        "Typical trough month",
        "lower water extent at end of dry season",
        "higher water extent in wet season",
        "average water extent at end of dry season",
        "high confidence years",
        "average invalid/cloud cover",
    ]
    assert len(kpis) == 10


def test_seasonal_copy_has_regime_verdict(seasonal_analysis):
    sentence = verdict_sentence(seasonal_analysis)
    assert isinstance(sentence, str)
    assert len(sentence) > 0


def _seasonal_extent_for_context(years=30, peak_month=2, seed=2, noise=0.02):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    phase = 2 * np.pi * (dates.month - peak_month) / 12.0
    return pd.DataFrame(
        {
            "extent_pct": np.clip(
                1.0 + 0.8 * np.cos(phase) + rng.normal(0, noise, len(dates)),
                0.01,
                None,
            ),
            "invalid_pct": 0.0,
        },
        index=dates,
    )


def test_rainfall_context_exposes_comparison_metrics():
    dates = pd.date_range("1990-01-01", periods=360, freq="MS")
    rain = pd.DataFrame(
        {"rainfall_mm": 100 + 80 * np.cos(2 * np.pi * (dates.month - 1) / 12)},
        index=dates,
    )
    comparison = compare_extent_and_rainfall_regimes(
        _seasonal_extent_for_context(),
        rain,
    )
    context = build_rainfall_context(
        source="silo",
        comparison=comparison,
        comparison_warning=None,
    )

    assert context["title"] == "Rainfall context (SILO)"
    assert context["extent_snr"] == pytest.approx(comparison.extent.amplitude_snr)
    assert context["rainfall_snr"] == pytest.approx(comparison.rainfall.amplitude_snr)
    assert context["peak_lag_months"] == comparison.peak_lag_months
    assert context["interpretation"] == comparison.interpretation


def test_rainfall_context_handles_comparison_failure():
    context = build_rainfall_context(
        source="csv",
        comparison=None,
        comparison_warning="comparison unavailable",
    )
    assert context["title"] == "Rainfall context (supplied CSV)"
    assert context["comparison_label"] == "Unavailable"
    assert context["warning"] == "comparison unavailable"
