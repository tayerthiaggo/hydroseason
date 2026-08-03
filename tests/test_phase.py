import numpy as np
import pandas as pd
import pytest

from hydroseason._dynamic_year import (
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
)
from hydroseason._phase import PHASES, assign_monthly_phases, empty_monthly_phase
from hydroseason._state_input import prepare_monthly_extent
from hydroseason.hydrological_state import analyze_hydrological_state

PHASE_COLUMNS = [
    "hy_year", "phase", "phase_status", "phase_confidence", "phase_method",
    "boundary_basis", "p_wet", "p_recession", "p_dry", "p_recovery",
    "extent_pct", "candidate_usable",
]


@pytest.fixture()
def prepared_extent() -> pd.DataFrame:
    index = pd.date_range("2018-01-01", periods=36, freq="MS")
    values = 30.0 + 20.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
    return prepare_monthly_extent(raw)


@pytest.fixture()
def monsonal_extent() -> pd.DataFrame:
    index = pd.date_range("2000-01-01", periods=15 * 12, freq="MS")
    values = 30.0 + 25.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_phase_model_defaults_to_none():
    assert DynamicHydroYearConfig(expected_trough_month=9).phase_model == "none"


def test_phase_model_rejects_unreleased_semi_markov_mode():
    with pytest.raises(ValueError, match="phase_model"):
        DynamicHydroYearConfig(expected_trough_month=9, phase_model="semi_markov")


def test_rule_based_phases_require_robust_extrema_detector():
    with pytest.raises(ValueError, match="robust_extrema"):
        DynamicHydroYearConfig(
            expected_trough_month=9,
            detector="semi_markov",
            phase_model="rule_based",
        )


def test_phase_helpers_stay_out_of_top_level_api():
    import hydroseason

    assert "assign_monthly_phases" not in hydroseason.__all__
    assert not hasattr(hydroseason, "assign_monthly_phases")


def test_disabled_phase_frame_has_one_row_per_month(prepared_extent):
    out = empty_monthly_phase(prepared_extent)
    assert list(out.columns) == PHASE_COLUMNS
    assert out.index.equals(prepared_extent.index)
    assert out["phase"].eq("unspecified").all()
    assert out["phase_status"].eq("disabled").all()


def test_rule_based_phases_honor_peak_and_trough(monsonal_extent):
    base = DynamicHydroYearConfig(expected_trough_month=9, phase_model="none")
    phased = DynamicHydroYearConfig(expected_trough_month=9, phase_model="rule_based")
    annual_base = detect_dynamic_hydrological_years(monsonal_extent, config=base)
    annual_phased = detect_dynamic_hydrological_years(monsonal_extent, config=phased)
    pd.testing.assert_frame_equal(annual_base, annual_phased)
    prepared = prepare_monthly_extent(monsonal_extent)
    labels = assign_monthly_phases(prepared, annual_phased, phased, noise_pp=0.0)
    assert labels.index.equals(prepared.index)
    assert labels["phase_method"].eq("rule_based").all()
    assert set(labels["phase_status"]).issubset(
        {"ok", "provisional", "unresolved_cycle", "outside_cycle", "unusable"}
    )
    assert labels.loc[labels["phase_status"].eq("outside_cycle"), "phase"].eq("unspecified").all()
    complete = annual_phased.loc[annual_phased["status"].eq("complete")]
    for row in complete.itertuples():
        assert labels.loc[row.peak_month, "phase"] == "wet"
        assert labels.loc[row.trough_month, "phase"] == "dry"


def test_rule_based_phases_follow_one_way_order(monsonal_extent):
    result = analyze_hydrological_state(
        monsonal_extent,
        config=DynamicHydroYearConfig(
            expected_trough_month=9,
            phase_model="rule_based",
        ),
        n_bootstrap=40,
    )
    rank = {"recovery": 0, "wet": 1, "recession": 2, "dry": 3}
    for _, group in result.monthly_phase.dropna(subset=["hy_year"]).groupby("hy_year"):
        usable = group.loc[group["phase_status"].ne("unusable"), "phase"]
        assert set(usable).issubset(set(PHASES))
        values = [rank[value] for value in usable]
        assert values == sorted(values)


def test_monthly_phase_boundary_basis_matches_actual_annual_boundary_detector(monsonal_extent):
    # Regression for the stage-06 review finding: monthly_phase.boundary_basis
    # must report the detector that actually produced the annual boundaries,
    # not a hard-coded "robust_extrema" string. Since the public
    # DynamicHydroYearConfig.detector is robust_extrema-only, this must hold
    # for both phase_model settings against the config actually used.
    for phase_model in ("none", "rule_based"):
        config = DynamicHydroYearConfig(expected_trough_month=9, phase_model=phase_model)
        result = analyze_hydrological_state(monsonal_extent, config=config, n_bootstrap=40)
        assert config.detector == "robust_extrema"
        assert result.monthly_phase["boundary_basis"].eq(config.detector).all()
