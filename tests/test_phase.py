import numpy as np
import pandas as pd
import pytest

from hydroseason._dynamic_year import DynamicHydroYearConfig
from hydroseason._phase import empty_monthly_phase
from hydroseason._state_input import prepare_monthly_extent

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
