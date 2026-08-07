import numpy as np
import pandas as pd
import pytest

from hydroseason._dynamic_year import (
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
)
from hydroseason._phase import (
    PHASES,
    assign_monthly_phases,
    assign_rule_based_phases,
    empty_monthly_phase,
)
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


def test_phase_model_defaults_to_rule_based():
    assert DynamicHydroYearConfig(expected_trough_month=9).phase_model == "rule_based"


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


def test_rule_based_phases_use_baseline_and_half_peak_anomaly():
    dates = pd.date_range("2018-01-01", "2020-12-01", freq="MS")
    baseline_year = [10, 10, 11, 12, 12, 11, 10, 9, 8, 7, 6, 5]
    target_year = [5, 8, 15, 30, 25, 20, 15, 10, 8, 6, 5, 4]
    values = baseline_year + baseline_year + target_year
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    prepared = prepare_monthly_extent(raw)
    config = DynamicHydroYearConfig(expected_trough_month=12, phase_model="rule_based")
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2020,
                "status": "complete",
                "hy_start": pd.Timestamp("2020-01-01"),
                "hy_end": pd.Timestamp("2020-12-01"),
                "peak_month": pd.Timestamp("2020-04-01"),
                "peak_extent_pct": 30.0,
                "trough_month": pd.Timestamp("2020-12-01"),
                "trough_extent_pct": 4.0,
                "boundary_status": "confirmed",
            }
        ]
    )

    labels = assign_monthly_phases(prepared, hydro_years, config, noise_pp=0.0)
    actual = labels.loc["2020", "phase"].tolist()

    assert actual == [
        "recovery", "recovery", "wet", "wet", "wet", "recession",
        "recession", "recession", "dry", "dry", "dry", "dry",
    ]


def test_record_start_boundary_cycle_receives_monthly_phases():
    """An opening cycle bounded from the record start must be phaseable.

    assign_rule_based_phases skips rows whose hy_start/hy_end/peak_month
    is None, so before the opening-boundary fix the record's first months
    stayed "unspecified"/"outside_cycle" and left the timeline unshaded
    there. Once those fields are populated the months must get real
    phases like any other partial cycle.
    """
    index = pd.date_range("2005-01-01", periods=10, freq="MS")
    raw = pd.DataFrame(
        {
            "extent_pct": [90.0, 78.0, 66.0, 54.0, 42.0, 30.0, 22.0, 16.0, 11.0, 8.0],
            "invalid_pct": 0.0,
        },
        index=index,
    )
    prepared = prepare_monthly_extent(raw)
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2005,
                "status": "partial",
                "status_reason": "record_start_boundary",
                "hy_start": pd.Timestamp("2005-01-01"),
                "hy_end": pd.Timestamp("2005-10-01"),
                "peak_month": pd.Timestamp("2005-01-01"),
                "peak_extent_pct": 90.0,
                "trough_extent_pct": 8.0,
            }
        ]
    )

    out = assign_rule_based_phases(prepared, hydro_years, noise_pp=1.0)

    assert (out["phase_status"] != "outside_cycle").any()
    assert (out["hy_year"] == 2005).any()
    assert set(out["phase"].unique()) - {"unspecified"}


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
