import numpy as np
import pandas as pd

from hydroseason.hydrological_state import (
    DynamicHydroYearConfig,
    HydrologicalStateResult,
    analyze_hydrological_state,
)


def _extent(years=15):
    index = pd.date_range("2000-01-01", periods=years * 12, freq="MS")
    values = 30.0 + 25.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_orchestrator_returns_all_public_products():
    result = analyze_hydrological_state(_extent(), n_bootstrap=40)
    assert isinstance(result, HydrologicalStateResult)
    assert not result.hydro_years.empty
    assert len(result.monthly_condition) == 15 * 12
    assert result.data_quality["n_usable"] == 15 * 12


def test_user_configuration_is_authoritative_over_advisory_pattern():
    config = DynamicHydroYearConfig(expected_trough_month=7, dry_plateau_rule="middle")
    result = analyze_hydrological_state(_extent(), config=config, n_bootstrap=40)
    assert result.config is config
    assert result.config.expected_trough_month == 7
