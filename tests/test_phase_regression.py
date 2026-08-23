import dataclasses
from pathlib import Path

import pandas as pd

from hydroseason._dynamic_year import (
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
    suggest_dynamic_hydro_year_config,
)
from hydroseason._phase import PHASES, assign_rule_based_phases
from hydroseason._state_input import prepare_monthly_extent

FIXTURES = Path(__file__).parent / "fixtures"


def _assert_rule_based_fixture(monthly: pd.DataFrame, config: DynamicHydroYearConfig) -> None:
    base = dataclasses.replace(config, phase_scheme="none")
    phased = dataclasses.replace(config, phase_scheme="four_phase")
    annual_base = detect_dynamic_hydrological_years(monthly, config=base)
    annual_phased = detect_dynamic_hydrological_years(monthly, config=phased)
    pd.testing.assert_frame_equal(annual_base, annual_phased)

    prepared = prepare_monthly_extent(
        monthly,
        max_invalid_pct=phased.max_invalid_pct,
        allow_unknown_quality=phased.allow_unknown_quality,
        quality_policy=phased.quality_policy,
    )
    labels = assign_rule_based_phases(prepared, annual_phased, noise_pp=0.0)

    assert labels.index.equals(prepared.index)
    assert labels["phase"].notna().all()
    assert set(labels["phase"]).issubset(set(PHASES) | {"unspecified"})

    complete = annual_phased.loc[annual_phased["status"].eq("complete")]
    assert not complete.empty
    for row in complete.itertuples():
        # phase_status reports data quality at that month, not whether it is a
        # valid anchor: peak/trough selection can land on a high-invalid_pct
        # month when it is still the genuine seasonal extreme (see
        # _boundary.py's candidacy rule), so phase_status may legitimately be
        # "unusable" at the anchor itself.
        assert labels.loc[row.peak_month, "phase"] == "wet"
        assert labels.loc[row.trough_month, "phase"] == "dry"

    partial = annual_phased.loc[
        annual_phased["status"].eq("partial")
        & annual_phased["hy_start"].notna()
        & annual_phased["hy_end"].notna()
        & annual_phased["peak_month"].notna()
    ]
    if not partial.empty:
        partial_years = set(partial["hy_year"].astype(int))
        partial_labels = labels.loc[labels["hy_year"].isin(partial_years)]
        assert partial_labels["phase"].isin(PHASES).any()
        assert partial_labels["phase_status"].eq("provisional").any()


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
