import numpy as np
import pandas as pd
import pytest

from hydroseason._dynamic_year import DynamicHydroYearConfig, suggest_dynamic_hydro_year_config
from hydroseason._seasonality import classify_seasonal_pattern


def _monsoonal(years=12):
    index = pd.date_range("2000-01-01", periods=years * 12, freq="MS")
    values = 30.0 + 25.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_suggestion_uses_advisory_phase_and_user_overrides_win():
    extent = _monsoonal()
    pattern = classify_seasonal_pattern(extent, n_bootstrap=40)
    config = suggest_dynamic_hydro_year_config(extent, pattern=pattern, trough_search_radius_months=2)
    assert config.expected_trough_month == pattern.expected_trough_month
    assert config.expected_peak_month == pattern.expected_peak_month
    assert config.trough_search_radius_months == 2


def test_unstable_pattern_requires_explicit_trough():
    extent = _monsoonal(years=4)
    with pytest.raises(ValueError, match="expected_trough_month"):
        suggest_dynamic_hydro_year_config(extent)


def test_dynamic_config_rejects_invalid_recovery_geometry():
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=13)
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=9, pulse_rejection_window_months=0)
