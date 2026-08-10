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
    assert len(result.monthly_phase) == 15 * 12
    # phase_model defaults to "rule_based": months inside complete cycles get
    # a real phase label, not the "unspecified"/"disabled" placeholder.
    assert result.monthly_phase["phase_method"].eq("rule_based").all()
    assert not result.monthly_phase["phase_status"].eq("disabled").any()
    assert set(result.monthly_phase["phase"]) <= {"recovery", "wet", "recession", "dry", "unspecified"}
    assert result.data_quality["n_usable"] == 15 * 12


def test_user_configuration_is_authoritative_over_advisory_pattern():
    config = DynamicHydroYearConfig(expected_trough_month=7, dry_plateau_rule="middle")
    result = analyze_hydrological_state(_extent(), config=config, n_bootstrap=40)
    assert result.config is config
    assert result.config.expected_trough_month == 7


def test_analyze_threads_noise_pp_and_rolling_columns():
    import numpy as np
    import pandas as pd

    from hydroseason import analyze_hydrological_state

    # 15 years of monthly monsoonal extent so the detector yields several HYs.
    idx = pd.date_range("2000-01-01", periods=12 * 15, freq="MS")
    month = idx.month.to_numpy()
    # Simple annual cycle: high around Feb, low around Sep.
    extent = 40 + 30 * np.cos(2 * np.pi * (month - 2) / 12)
    frame = pd.DataFrame({"extent_pct": extent, "invalid_pct": 0.0}, index=idx)

    result = analyze_hydrological_state(frame, reference="rolling")
    annual = result.hydro_years
    assert "noise_floor_pp" in annual.columns
    assert "timing_confidence" in annual.columns
    assert "baseline_mode" in annual.columns
    assert "annual_condition_qualified" in annual.columns
    # noise_floor_pp is the same record-level value on every row (not NaN).
    assert annual["noise_floor_pp"].notna().all()
    assert annual["noise_floor_pp"].nunique() == 1
