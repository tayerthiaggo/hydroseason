"""Definitional contract for wet events and dry spells.

The first cut used bare p75/p50 quantiles of the record: arbitrary, with no
minimum duration (one noisy month counted as a flood), no minimum separation,
and dry spells defined only as the gap *between* events -- so a catchment that
never crossed the threshold reported no dry spells at all, which inverts the
meaning. These tests pin the replacement.
"""
import numpy as np
import pandas as pd
import pytest

from hydroseason._events import extract_water_events


def _frame(values, start="1990-01-01"):
    index = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.asarray(values, dtype=float), "invalid_pct": 0.0}, index=index
    )


def _noisy_baseline(n=120, level=0.5, noise=0.03, seed=1):
    rng = np.random.default_rng(seed)
    return list(np.abs(rng.normal(level, noise, n)))


# --- minimum duration ------------------------------------------------------

def test_single_month_spike_excluded_when_minimum_duration_is_two():
    values = _noisy_baseline(60)
    values[30] = 5.0
    result = extract_water_events(_frame(values), min_event_months=2)
    assert result.summary["n_events"] == 0


def test_single_month_spike_counted_when_minimum_duration_is_one():
    values = _noisy_baseline(60)
    values[30] = 5.0
    lenient = extract_water_events(_frame(values), min_event_months=1)
    strict = extract_water_events(_frame(values), min_event_months=2)
    assert lenient.summary["n_events"] > strict.summary["n_events"]
    spike = pd.Timestamp("1990-01-01") + pd.DateOffset(months=30)
    assert (lenient.events["start"] <= spike).any() and (lenient.events["end"] >= spike).any()


def test_sustained_event_survives_a_minimum_duration_filter():
    values = _noisy_baseline(60)
    values[30:35] = [5.0] * 5
    result = extract_water_events(_frame(values), min_event_months=3)
    assert result.summary["n_events"] == 1
    assert result.events.iloc[0]["duration_months"] == 5


# --- minimum separation ----------------------------------------------------

def test_events_closer_than_minimum_separation_are_merged():
    values = _noisy_baseline(60)
    values[30:32] = [5.0, 5.0]
    values[33:35] = [5.0, 5.0]  # one quiet month between
    merged = extract_water_events(_frame(values), min_separation_months=3)
    assert merged.summary["n_events"] == 1


def test_events_further_apart_than_minimum_separation_stay_separate():
    values = _noisy_baseline(80)
    values[20:22] = [5.0, 5.0]
    values[50:52] = [5.0, 5.0]
    result = extract_water_events(_frame(values), min_separation_months=3)
    assert result.summary["n_events"] == 2


# --- dry spells are independent of events ----------------------------------

def test_low_spells_are_found_even_when_no_wet_event_occurs():
    """A record that never floods still has dry spells. Defining a spell as
    the gap between events made this case report none, which is backwards."""
    values = [0.5] * 40 + [0.01] * 20 + [0.5] * 40
    result = extract_water_events(_frame(values))
    assert result.summary["n_events"] == 0
    assert result.summary["n_low_spells"] >= 1
    assert result.summary["longest_low_spell_months"] >= 15


def test_dry_spell_requires_minimum_duration():
    values = [0.5] * 40 + [0.01] * 2 + [0.5] * 40
    strict = extract_water_events(_frame(values), min_low_months=6)
    assert strict.summary["n_low_spells"] == 0


def test_dry_spell_duration_is_measured_below_the_low_threshold():
    values = [0.5] * 30 + [0.01] * 12 + [0.5] * 30
    result = extract_water_events(_frame(values), min_low_months=3)
    assert result.summary["longest_low_spell_months"] == 12


# --- threshold provenance --------------------------------------------------

def test_resolved_definition_is_reported_for_audit():
    result = extract_water_events(_frame(_noisy_baseline(120)))
    for key in (
        "threshold_mode", "enter_threshold_pct", "exit_threshold_pct",
        "low_threshold_pct", "baseline_pct", "min_event_months",
        "min_separation_months", "min_low_months",
    ):
        assert key in result.summary, f"missing {key}"


def test_noise_relative_mode_scales_with_the_records_own_noise():
    """Two records with the same baseline but different noise must not get the
    same absolute threshold -- that is the point of grounding it in noise."""
    quiet = extract_water_events(_frame(_noisy_baseline(120, noise=0.01, seed=2)))
    loud = extract_water_events(_frame(_noisy_baseline(120, noise=0.20, seed=2)))
    assert loud.summary["enter_threshold_pct"] > quiet.summary["enter_threshold_pct"]


def test_degenerate_noise_falls_back_to_quantiles_and_says_so():
    """A synthetic record with zero month-to-month variation has no noise
    scale; the definition must degrade to quantiles rather than divide by zero.
    """
    result = extract_water_events(_frame([0.1] * 24 + [3.0] * 3 + [0.1] * 24))
    assert result.summary["threshold_mode"] == "quantile_fallback"
    assert result.summary["n_events"] == 1


def test_explicit_quantile_mode_is_honoured():
    result = extract_water_events(_frame(_noisy_baseline(120)), threshold_mode="quantile")
    assert result.summary["threshold_mode"] == "quantile"


def test_invalid_threshold_mode_rejected():
    with pytest.raises(ValueError, match="threshold_mode"):
        extract_water_events(_frame(_noisy_baseline(60)), threshold_mode="nonsense")
