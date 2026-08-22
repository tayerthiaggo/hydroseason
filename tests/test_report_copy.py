import numpy as np
import pandas as pd
import pytest

from hydroseason._boundary_recoverability import RecoverabilityThresholds
from hydroseason._catchment import analyze_catchment
from hydroseason._evidence import EvidenceThresholds
from hydroseason._regime_compare import compare_extent_and_rainfall_regimes
from hydroseason._report_copy import (
    build_rainfall_context,
    low_spell_explainer,
    select_kpis,
    verdict_sentence,
    wet_event_explainer,
)

EVIDENCE = EvidenceThresholds(
    seasonal_cv_skill=0.3,
    periodicity_alpha=0.05,
    amplitude_noise_ratio=1.0,
    mode_min_frequency=0.60,
    mode_min_separation_months=2,
    strong_timing_concentration=0.70,
    weak_timing_concentration=0.40,
    min_timing_years=5,
)
RECOVERABILITY = RecoverabilityThresholds(
    min_years=5,
    min_coverage=0.80,
    min_within_1_month=0.80,
    within_1_month_wilson_floor=0.50,
    max_p90_error_months=2.0,
    admit_insufficient_drift=False,
)


@pytest.fixture
def seasonal_analysis():
    dates = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (dates.month - 2) / 12)
    df = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    return analyze_catchment(
        df,
        phase_model="rule_based",
        n_bootstrap=40,
        evidence_thresholds=EVIDENCE,
        recoverability_thresholds=RECOVERABILITY,
    )


@pytest.fixture
def aseasonal_analysis():
    years = 10
    rng = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=12 * years, freq="MS")
    values = np.abs(rng.normal(0.15, 0.12, 12 * years))
    df = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    return analyze_catchment(df, phase_model="rule_based", n_bootstrap=40)


_KPI_LABELS = [
    "hydrological regime",
    "amplitude signal-to-noise ratio",
    "peak timing concentration",
    "trough timing concentration",
    "analytical route",
    "hydrological years",
    "mean annual amplitude",
    "mean cycle length",
    "Typical peak month",
    "Typical trough month",
    "lower water extent at end of dry season",
    "higher water extent in wet season",
    "average water extent at end of dry season",
    "high confidence years",
    "wet events",
    "longest low-extent spell",
    "years without a wet event",
    "average invalid/cloud cover",
]


def test_aseasonal_copy_never_mentions_hydrological_year(aseasonal_analysis):
    sentence = verdict_sentence(aseasonal_analysis).casefold()
    assert "no stable annual cycle" in sentence
    assert "use wet events" in sentence
    assert "hydrological-year boundaries" not in sentence
    assert len(select_kpis(aseasonal_analysis)) == len(_KPI_LABELS)


def test_seasonal_kpis_include_complete_year_count(seasonal_analysis):
    kpis = select_kpis(seasonal_analysis)
    assert [item["label"] for item in kpis] == _KPI_LABELS


def test_kpi_deck_is_identical_across_regimes(seasonal_analysis, aseasonal_analysis):
    """Cards stay in the same order and count so reports compare side by side."""
    seasonal = [item["label"] for item in select_kpis(seasonal_analysis)]
    aseasonal = [item["label"] for item in select_kpis(aseasonal_analysis)]
    assert seasonal == aseasonal == _KPI_LABELS


def test_aseasonal_cycle_kpis_state_why_they_are_absent(aseasonal_analysis):
    """A withheld number explains itself instead of rendering a bare N/A."""
    cards = {item["label"]: item for item in select_kpis(aseasonal_analysis)}
    withheld = cards["Typical peak month"]
    assert withheld["value"] == "Not defined"
    assert "no reproducible annual cycle" in withheld["detail"]
    assert "N/A" not in withheld["value"]


def test_event_kpis_are_populated_without_a_cycle(aseasonal_analysis):
    """Event descriptors presume no annual cycle, so they survive the aseasonal route."""
    cards = {item["label"]: item for item in select_kpis(aseasonal_analysis)}
    assert cards["wet events"]["value"] != "Not defined"
    assert cards["longest low-extent spell"]["value"].endswith("mo")


def test_snr_card_states_the_thresholds_it_is_judged_against(seasonal_analysis):
    """The number alone cannot tell a reader whether it passed."""
    cards = {item["label"]: item for item in select_kpis(seasonal_analysis)}
    assert "2.0" in cards["amplitude signal-to-noise ratio"]["detail"]
    peak = cards["peak timing concentration"]
    trough = cards["trough timing concentration"]
    assert peak["value"].startswith("R ")
    assert "95% bootstrap CI" in peak["detail"]
    assert "R >= 0.70" in peak["detail"]
    assert "R ranges from 0 (diffuse or cancelling timing) to 1 (same month every year)." in peak["detail"]
    assert "A low R can also arise from symmetric multi-modal timing; the Kuiper p-value tests the discrete 12-month uniform null." in peak["detail"]
    assert trough["value"].startswith("R ")
    assert "boundary eligibility" in trough["detail"]


def test_route_labels_are_short_enough_for_a_card(seasonal_analysis):
    value = {item["label"]: item for item in select_kpis(seasonal_analysis)}["analytical route"]["value"]
    assert value == "Per-Year Detection"
    assert "Characterisation" not in value


def test_seasonal_copy_has_regime_verdict(seasonal_analysis):
    sentence = verdict_sentence(seasonal_analysis)
    assert isinstance(sentence, str)
    assert len(sentence) > 0


def test_wet_event_explainer_states_this_catchments_own_thresholds(aseasonal_analysis):
    """The explanation is grounded in resolved numbers, not generic boilerplate."""
    summary = aseasonal_analysis.events.summary
    text = wet_event_explainer(aseasonal_analysis)
    assert str(round(summary["enter_threshold_pct"], 1)) in text or "%" in text
    assert "hysteresis" in text
    assert f"{summary['min_event_months']} month" in text
    assert f"{summary['min_separation_months']} month" in text


def test_wet_event_explainer_handles_no_events(seasonal_analysis):
    assert seasonal_analysis.events.summary["n_events"] == 0
    text = wet_event_explainer(seasonal_analysis)
    assert "no wet event" in text.casefold()


def test_low_spell_explainer_states_this_catchments_own_thresholds(aseasonal_analysis):
    summary = aseasonal_analysis.events.summary
    text = low_spell_explainer(aseasonal_analysis)
    assert f"{summary['min_low_months']} consecutive month" in text
    assert "independently of wet events" in text
    assert "%" in text


def test_low_spell_explainer_handles_no_spells(seasonal_analysis):
    from dataclasses import replace
    no_spells_events = replace(
        seasonal_analysis.events,
        summary={**seasonal_analysis.events.summary, "n_low_spells": 0},
        low_spells=pd.DataFrame(),
    )
    no_spells_analysis = replace(seasonal_analysis, events=no_spells_events)
    assert no_spells_analysis.events.summary["n_low_spells"] == 0
    text = low_spell_explainer(no_spells_analysis)
    assert "no run of low extent" in text.casefold()


def test_explainers_differ_by_catchment():
    """Two catchments with different thresholds must not get the same prose."""
    rng_a = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=120, freq="MS")
    low = analyze_catchment(
        pd.DataFrame(
            {"extent_pct": np.abs(rng_a.normal(0.15, 0.12, 120)), "invalid_pct": 0.0},
            index=dates,
        ),
        phase_model="rule_based",
        n_bootstrap=20,
    )
    rng_b = np.random.default_rng(7)
    high = analyze_catchment(
        pd.DataFrame(
            {"extent_pct": np.abs(rng_b.normal(15.0, 12.0, 120)), "invalid_pct": 0.0},
            index=dates,
        ),
        phase_model="rule_based",
        n_bootstrap=20,
    )
    assert wet_event_explainer(low) != wet_event_explainer(high)


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
