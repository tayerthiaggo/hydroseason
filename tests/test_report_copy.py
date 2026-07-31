import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._report_copy import select_kpis, verdict_sentence


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
    assert len(select_kpis(aseasonal_analysis)) <= 6


def test_seasonal_kpis_include_complete_year_count(seasonal_analysis):
    labels = {item["label"] for item in select_kpis(seasonal_analysis)}
    assert "Complete hydrological years" in labels
    assert len(select_kpis(seasonal_analysis)) <= 6


def test_seasonal_copy_has_regime_verdict(seasonal_analysis):
    sentence = verdict_sentence(seasonal_analysis)
    assert isinstance(sentence, str)
    assert len(sentence) > 0
