from pathlib import Path

import pandas as pd

from hydroseason._dynamic_year import (
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
    suggest_dynamic_hydro_year_config,
)
from hydroseason._phase import PHASES, assign_monthly_phases
from hydroseason._state_input import prepare_monthly_extent

FIXTURES = Path(__file__).parent / "fixtures"


def _assert_rule_based_fixture(monthly: pd.DataFrame, config: DynamicHydroYearConfig) -> None:
    base = DynamicHydroYearConfig(**{**config.__dict__, "phase_model": "none"})
    phased = DynamicHydroYearConfig(**{**config.__dict__, "phase_model": "rule_based"})
    annual_base = detect_dynamic_hydrological_years(monthly, config=base)
    annual_phased = detect_dynamic_hydrological_years(monthly, config=phased)
    pd.testing.assert_frame_equal(annual_base, annual_phased)

    prepared = prepare_monthly_extent(
        monthly,
        max_invalid_pct=phased.max_invalid_pct,
        allow_unknown_quality=phased.allow_unknown_quality,
        quality_policy=phased.quality_policy,
    )
    labels = assign_monthly_phases(prepared, annual_phased, phased, noise_pp=0.0)

    assert labels.index.equals(prepared.index)
    assert labels["phase"].notna().all()
    assert set(labels["phase"]).issubset(set(PHASES) | {"unspecified"})

    complete = annual_phased.loc[annual_phased["status"].eq("complete")]
    assert not complete.empty
    for row in complete.itertuples():
        assert labels.loc[row.peak_month, "phase"] == "wet"
        assert labels.loc[row.peak_month, "phase_status"] != "unusable"
        assert labels.loc[row.trough_month, "phase"] == "dry"
        assert labels.loc[row.trough_month, "phase_status"] != "unusable"


def test_fitzroy_rule_based_phases_preserve_annual_frame_and_anchor_labels():
    monthly = pd.read_csv(
        FIXTURES / "fitzroy_kimberley_monthly.csv",
        parse_dates=["date"],
    ).set_index("date")
    config = DynamicHydroYearConfig(
        expected_trough_month=11,
        trough_search_radius_months=3,
        max_invalid_pct=95.0,
    )
    _assert_rule_based_fixture(monthly, config)


def test_gilbert_rule_based_phases_preserve_annual_frame_and_anchor_labels():
    monthly = pd.read_csv(
        FIXTURES / "gilbert_river_monthly.csv",
        parse_dates=["date"],
    ).set_index("date")
    config = suggest_dynamic_hydro_year_config(monthly, max_invalid_pct=20.0)
    _assert_rule_based_fixture(monthly, config)
