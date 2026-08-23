import numpy as np
import pandas as pd
import pytest

from hydroseason._challenger import ChallengerAssessment, assess_challenger, failed_challenger
from hydroseason._scientific_defaults import EVIDENCE_DEFAULTS, RECOVERABILITY_DEFAULTS
from hydroseason._state_input import prepare_monthly_extent


def test_failed_challenger_is_complete_non_proposal():
    result = failed_challenger(RuntimeError("harmonic fit exploded"))
    assert result.status == "failed"
    assert result.proposed_regime is None
    assert result.proposed_route is None
    assert result.agreement is None
    assert result.disagreement_reason is None
    assert result.error == "RuntimeError: harmonic fit exploded"
    assert result.annual_cycle_evidence == "insufficient"
    assert result.boundary_recoverability == "insufficient"


def test_challenger_is_frozen():
    result = failed_challenger(ValueError("bad input"))
    with pytest.raises(Exception):
        result.status = "ok"


def test_direct_challenger_error_is_not_swallowed(monkeypatch):
    index = pd.date_range("2000-01-01", periods=15 * 12, freq="MS")
    raw = pd.DataFrame(
        {
            "extent_pct": 30.0 + 20.0 * np.cos(2.0 * np.pi * (index.month - 2) / 12.0),
            "invalid_pct": 0.0,
        },
        index=index,
    )
    prepared = prepare_monthly_extent(raw)

    def explode(*args, **kwargs):
        raise RuntimeError("direct challenger failure")

    monkeypatch.setattr("hydroseason._challenger.classify_seasonal_pattern", explode)
    with pytest.raises(RuntimeError, match="direct challenger failure"):
        assess_challenger(
            prepared,
            value_col="extent_pct",
            qualifying_years=sorted(set(prepared.index.year)),
            min_months_per_year=9,
            measurement_tolerance_pct=1.0,
            n_bootstrap=40,
            random_state=0,
            evidence_thresholds=EVIDENCE_DEFAULTS,
            recoverability_thresholds=RECOVERABILITY_DEFAULTS,
            robust_boundary_config=None,
            trough_search_radius_months=3,
            established_regime="seasonal",
            established_route="per_year_detection",
        )
