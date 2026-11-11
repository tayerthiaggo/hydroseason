"""Behaviour pins for trough recurrence on known-truth records.

These tests record what the released method (policy hydroseason-v0.2.0) does on
records whose trough recurs while peaks do not, and on the mirror case. They are
not claims that the recorded behaviour is scientifically correct. Background:
docs/provisional-trough-verdict-2026-10-30.md, sections 2 and 4.
"""

import numpy as np
import pandas as pd
import pytest

from hydroseason import (
    analyze_catchment,
    assess_water_regime,
    classify_seasonal_pattern,
    suggest_dynamic_hydro_year_config,
)
from hydroseason._seasonality_test import TIMING_RECURRENCE_ALPHA
from scripts.trough_synthetic import build_record


def _stable_peak_irregular_trough(seed=0, years=12):
    """April is the peak every year; the minimum lands in a random other month."""
    rng = np.random.default_rng(seed)
    values = 15.0 + rng.uniform(0.0, 5.0, size=(years, 12))
    values[:, 3] = 25.0
    for year in range(years):
        month = int(rng.choice([m for m in range(12) if m != 3]))
        values[year, month] = 5.0
    index = pd.date_range("2000-01-01", periods=12 * years, freq="MS")
    return pd.DataFrame({"extent_pct": values.ravel(), "invalid_pct": 0.0}, index=index)


def _sinusoid(half_amplitude, years=12):
    months = np.arange(12 * years)
    index = pd.date_range("2000-01-01", periods=12 * years, freq="MS")
    return pd.DataFrame(
        {
            "extent_pct": 20.0 + half_amplitude * np.cos(2 * np.pi * months / 12),
            "invalid_pct": 0.0,
        },
        index=index,
    )


def test_recurrent_trough_with_irregular_peaks_is_aseasonal_by_conjunction():
    _, frame = build_record("stable", seed=0)

    assessment = assess_water_regime(frame)
    test = assessment.seasonality_test

    assert assessment.regime == "aseasonal"
    assert assessment.public_route == "event_characterisation"
    assert test.status == "ok"
    assert test.reason == "peak_uniformity_not_rejected"
    assert test.trough.uniformity_p < TIMING_RECURRENCE_ALPHA
    assert test.peak.uniformity_p >= TIMING_RECURRENCE_ALPHA
    assert test.trough.dominant_month == 9
    # Public surface: the trough p-value is exposed, the month is not.
    assert assessment.trough_timing_uniformity_p < TIMING_RECURRENCE_ALPHA
    assert assessment.mean_monthly_trough_month is None


def test_recurrent_peak_with_irregular_troughs_is_aseasonal_by_conjunction():
    test = assess_water_regime(_stable_peak_irregular_trough()).seasonality_test

    assert test.reason == "trough_uniformity_not_rejected"
    assert test.peak.uniformity_p < TIMING_RECURRENCE_ALPHA
    assert test.trough.uniformity_p >= TIMING_RECURRENCE_ALPHA
    assert test.peak.dominant_month == 4


def test_catchment_routes_recurrent_trough_with_irregular_peaks_to_events():
    _, frame = build_record("stable", seed=0)

    analysis = analyze_catchment(frame)

    assert analysis.route == "event_characterisation"
    assert analysis.state is None


def test_harmonic_refuses_the_judgement_counterexample():
    _, frame = build_record("stable", seed=0)

    result = classify_seasonal_pattern(frame, n_null=99)

    assert result.pattern == "low_variability"
    assert result.selected_harmonic_order == 0
    assert result.seasonal_amplitude_pp == 0.0
    assert result.expected_trough_month is None
    # Sentinel written by the floor branch; no periodicity test ran.
    assert result.periodicity_p == 1.0
    with pytest.raises(ValueError, match="No stable trough phase"):
        suggest_dynamic_hydro_year_config(frame, pattern=result)


def test_harmonic_accepts_the_same_trough_without_floods():
    _, frame = build_record("stable", seed=0, flood_rate=0.0)

    result = classify_seasonal_pattern(frame, n_null=99)

    assert result.pattern != "low_variability"
    assert result.expected_trough_month == 9


def test_low_variability_floor_is_the_measurement_tolerance():
    # Fitted range 0.8 pp is at or below a 1.0 pp tolerance.
    at_floor = classify_seasonal_pattern(_sinusoid(0.4), n_null=49, measurement_tolerance_pct=1.0)
    # Fitted range 2.0 pp clears it.
    above = classify_seasonal_pattern(_sinusoid(1.0), n_null=49, measurement_tolerance_pct=1.0)
    # The default tolerance is 0, so the floor is machine epsilon and any positive amplitude passes.
    zero_tolerance = classify_seasonal_pattern(_sinusoid(0.4), n_null=49)

    assert at_floor.pattern == "low_variability"
    assert at_floor.selected_harmonic_order == 1
    assert above.pattern == "unimodal_annual"
    assert zero_tolerance.pattern == "unimodal_annual"
    assert zero_tolerance.amplitude_noise_ratio > 1e6
