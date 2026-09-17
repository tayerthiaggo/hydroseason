import numpy as np
import pandas as pd
import pytest

from hydroseason._seasonality import classify_seasonal_pattern

_EVIDENCE_KWARGS = {
    "resolution_floor_pp": 0.5,
    "mode_min_frequency": 0.60,
    "mode_min_separation_months": 2,
    "n_null": 99,
}


def _signal(values, years=12):
    index = pd.date_range("2000-01-01", periods=12 * years, freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.tile(values, years), "invalid_pct": 0.0},
        index=index,
    )


def test_unimodal_bimodal_low_variability_and_short_records():
    unimodal = 30.0 + 20.0 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    bimodal = 30.0 + 15.0 * np.cos(4 * np.pi * (np.arange(12) - 1) / 12)
    assert (
        classify_seasonal_pattern(
            _signal(unimodal), n_bootstrap=40, **_EVIDENCE_KWARGS
        ).pattern
        == "unimodal_annual"
    )
    assert (
        classify_seasonal_pattern(
            _signal(bimodal), n_bootstrap=40, **_EVIDENCE_KWARGS
        ).pattern
        == "bimodal_or_complex"
    )
    assert (
        classify_seasonal_pattern(
            _signal(np.repeat(20.0, 12)), n_bootstrap=40, **_EVIDENCE_KWARGS
        ).pattern
        == "low_variability"
    )
    assert (
        classify_seasonal_pattern(
            _signal(unimodal, years=4), n_bootstrap=40, **_EVIDENCE_KWARGS
        ).pattern
        == "insufficient_record"
    )


def test_existing_call_shape_uses_measurement_tolerance_as_resolution_floor():
    barely_variable = 60.0 + 0.3 * np.cos(2 * np.pi * np.arange(12) / 12)

    result = classify_seasonal_pattern(
        _signal(barely_variable),
        n_bootstrap=40,
        n_null=39,
        measurement_tolerance_pct=1.0,
    )

    assert result.pattern == "low_variability"
    assert result.seasonal_amplitude_pp == pytest.approx(0.6)


def test_zero_measurement_tolerance_remains_valid_and_finite():
    seasonal = 30.0 + 20.0 * np.cos(2 * np.pi * np.arange(12) / 12)

    result = classify_seasonal_pattern(
        _signal(seasonal),
        n_bootstrap=40,
        n_null=39,
        measurement_tolerance_pct=0.0,
    )

    assert result.pattern == "unimodal_annual"
    assert np.isfinite(result.amplitude_noise_ratio)


def test_zero_tolerance_does_not_hide_sub_epsilon_nonzero_amplitude():
    tiny = np.finfo(float).eps / 4.0
    nonconstant = tiny * (1.0 + np.cos(2 * np.pi * np.arange(12) / 12))

    result = classify_seasonal_pattern(
        _signal(nonconstant),
        n_bootstrap=0,
        n_null=39,
        measurement_tolerance_pct=0.0,
    )

    assert 0.0 < result.seasonal_amplitude_pp < np.finfo(float).eps
    assert result.pattern != "low_variability"
    assert np.isfinite(result.amplitude_noise_ratio)
    assert result.amplitude_noise_ratio > 0.0
