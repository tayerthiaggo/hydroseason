from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._regime_compare import compare_extent_and_rainfall_regimes
from hydroseason._report_copy import (
    build_rainfall_context,
    low_spell_explainer,
    select_kpis,
    verdict_sentence,
    wet_event_explainer,
)


@pytest.fixture
def seasonal_analysis():
    dates = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (dates.month - 2) / 12)
    df = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    return analyze_catchment(
        df,
        phase_scheme="two_phase",
        n_bootstrap=40,
    )


@pytest.fixture
def aseasonal_analysis():
    years = 10
    rng = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=12 * years, freq="MS")
    values = np.abs(rng.normal(0.15, 0.12, 12 * years))
    df = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    return analyze_catchment(df, phase_scheme="two_phase", n_bootstrap=40)


@pytest.fixture
def truly_aseasonal_analysis():
    """A record with no calendar-month structure at all (genuine SNR < 0.7 gate)."""
    years = 12
    rng = np.random.default_rng(8)
    dates = pd.date_range("2010-01-01", periods=12 * years, freq="MS")
    values = np.abs(rng.normal(10.0, 3.0, 12 * years))
    rng.shuffle(values)
    df = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    return analyze_catchment(df, phase_scheme="two_phase", n_bootstrap=40)


_KPI_LABELS = [
    "hydrological regime",
    "seasonality evidence",
    "analytical route",
    "observability",
    "hydrological years",
    "mean cycle length",
    "Typical peak month",
    "Typical trough month",
    "well-observed years",
    "point-identifiable boundary years",
    "wet events",
    "longest low-extent spell",
    "years without a wet event",
    "average invalid/cloud cover",
]


def test_truly_aseasonal_copy_never_mentions_hydrological_year(truly_aseasonal_analysis):
    assert truly_aseasonal_analysis.regime.regime == "aseasonal"
    sentence = verdict_sentence(truly_aseasonal_analysis).casefold()
    assert "calendar recurrence of annual peak and trough timing was not established" in sentence
    assert "exact hydrological-year boundaries are withheld" in sentence
    assert len(select_kpis(truly_aseasonal_analysis)) == len(_KPI_LABELS)


def test_aseasonal_copy_never_mentions_hydrological_year(aseasonal_analysis):
    assert aseasonal_analysis.regime.regime == "aseasonal"
    assert aseasonal_analysis.route == "event_characterisation"
    sentence = verdict_sentence(aseasonal_analysis).casefold()
    assert "calendar recurrence of annual peak and trough timing was not established" in sentence
    assert "exact hydrological-year boundaries are withheld" in sentence
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
    assert "withheld: no reproducible annual cycle" in withheld["detail"]
    assert "N/A" not in withheld["value"]


def test_event_kpis_are_populated_without_a_cycle(aseasonal_analysis):
    """Event descriptors presume no annual cycle, so they survive the aseasonal route."""
    cards = {item["label"]: item for item in select_kpis(aseasonal_analysis)}
    assert cards["wet events"]["value"] != "Not defined"
    assert cards["longest low-extent spell"]["value"].endswith("mo")


def test_seasonality_card_states_the_tests_used(seasonal_analysis):
    cards = {item["label"]: item for item in select_kpis(seasonal_analysis)}
    evidence = cards["seasonality evidence"]
    assert evidence["value"] == "Peak and trough recur"
    assert "Kuiper p-values: peak=" in evidence["detail"]
    assert "trough=0.001" in evidence["detail"]
    assert "alpha = 0.05" in evidence["detail"]
    assert "SNR" not in " ".join(item["detail"] for item in cards.values())
    assert "R >= 0.70" not in evidence["detail"]


def test_kpi_deck_omits_retired_signal_metrics(seasonal_analysis):
    labels = [item["label"] for item in select_kpis(seasonal_analysis)]
    rendered = " ".join(
        f"{item['label']} {item['value']} {item['detail']}"
        for item in select_kpis(seasonal_analysis)
    )
    assert "amplitude signal-to-noise ratio" not in labels
    assert "peak timing concentration" not in labels
    assert "trough timing concentration" not in labels
    assert "SNR" not in rendered
    assert "R >= 0.70" not in rendered


def test_observability_card_states_zero_fraction_and_timing_support(seasonal_analysis):
    cards = {item["label"]: item for item in select_kpis(seasonal_analysis)}
    observability = cards["observability"]
    assert observability["value"].endswith("% zero-water months")
    assert "whole-zero years" in observability["detail"]
    assert "years support both peak and trough timing" in observability["detail"]


def test_well_observed_and_point_identifiable_cards_are_independent(seasonal_analysis):
    """Data/window quality and timing identifiability are reported separately."""
    cards = {item["label"]: item for item in select_kpis(seasonal_analysis)}
    well_observed = cards["well-observed years"]
    point_identifiable = cards["point-identifiable boundary years"]
    assert "selection_support" in well_observed["detail"]
    assert "interval or unresolved" in point_identifiable["detail"]


def test_route_labels_are_short_enough_for_a_card(seasonal_analysis):
    value = {item["label"]: item for item in select_kpis(seasonal_analysis)}["analytical route"]["value"]
    assert value == "Per-Year Detection"
    assert "Characterisation" not in value


def test_seasonal_copy_has_regime_verdict(seasonal_analysis):
    sentence = verdict_sentence(seasonal_analysis)
    assert isinstance(sentence, str)
    assert len(sentence) > 0


def test_seasonal_regime_routed_to_event_characterisation_explains_why(seasonal_analysis):
    """A seasonal-looking record whose per-cycle timing didn't hold up (Roper
    River NT: SNR 2.14, but only 3 of 11 cycles resolved a usable trough)
    must not claim "Hydrological year boundaries are applied" -- none were.
    The verdict must surface analysis.route_reason and be honest that
    boundaries are withheld."""
    reason = (
        "seasonal record (SNR 2.14) has insufficient identifiable annual "
        "timing (peak cycles resolved=9, trough cycles resolved=3, need "
        ">=3 on each); using event characterisation"
    )
    analysis = replace(
        seasonal_analysis, route="event_characterisation", route_reason=reason,
        hydro_years=pd.DataFrame(),
    )
    sentence = verdict_sentence(analysis)
    assert "applied" not in sentence.casefold()
    assert "trough cycles resolved=3" in sentence
    assert "withheld" in sentence.casefold()


def _candidate_record(*, years=30, trend=0.0, amplitude=5.0, centre=10.0, seed=0):
    months = np.arange(12 * years)
    values = centre + trend * months + amplitude * np.cos(2 * np.pi * months / 12)
    if seed:
        values = values + np.random.default_rng(seed).normal(0.0, 2.5, len(values))
    values = np.clip(values, 0.0, 100.0)
    return pd.DataFrame(
        {"extent_pct": values, "invalid_pct": 0.0},
        index=pd.date_range("1990-01-01", periods=len(values), freq="MS"),
    )


def test_candidate_report_copy_uses_calendar_recurrence_evidence():
    analysis = analyze_catchment(
        _candidate_record(trend=0.2),
        n_bootstrap=40,
    )
    test = analysis.regime.seasonality_test
    sentence = verdict_sentence(analysis)
    cards = {item["label"]: item for item in select_kpis(analysis)}
    detail = " ".join(item["detail"] for item in cards.values())

    assert analysis.regime.regime == "seasonal"
    assert "Calendar recurrence" in sentence
    assert "was established" in sentence
    assert f"peak Kuiper p = {test.peak.uniformity_p:.3f}" in sentence
    assert f"trough Kuiper p = {test.trough.uniformity_p:.3f}" in sentence
    assert "alpha = 0.05" in detail
    assert f"{test.n_detectable_years} detectable years" in detail
    assert "R >= 0.70" not in detail
    assert "seasonal >= 2.0" not in detail


def test_candidate_aseasonal_copy_does_not_claim_uniform_timing():
    analysis = analyze_catchment(
        _candidate_record(amplitude=0.0, centre=50.0, seed=3),
        n_bootstrap=40,
    )
    sentence = verdict_sentence(analysis)

    assert analysis.regime.regime == "aseasonal"
    assert "calendar recurrence" in sentence.casefold()
    assert "was not established" in sentence
    assert "aseasonal means recurrence was not established" in sentence.casefold()
    assert "proven uniform" in sentence.casefold()


def test_candidate_insufficient_copy_is_not_aseasonal():
    analysis = analyze_catchment(
        _candidate_record(years=4),
        n_bootstrap=40,
    )
    sentence = verdict_sentence(analysis)

    assert analysis.regime.regime == "insufficient_record"
    assert "could not be assessed" in sentence
    assert "insufficient" in sentence.casefold()
    assert "aseasonal means" not in sentence.casefold()


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
        phase_scheme="two_phase",
        n_bootstrap=20,
    )
    rng_b = np.random.default_rng(7)
    high = analyze_catchment(
        pd.DataFrame(
            {"extent_pct": np.abs(rng_b.normal(15.0, 12.0, 120)), "invalid_pct": 0.0},
            index=dates,
        ),
        phase_scheme="two_phase",
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
    assert "extent_snr" not in context
    assert "rainfall_snr" not in context
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
