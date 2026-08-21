import numpy as np
import pandas as pd
import pytest

from hydroseason._state_input import candidate_weights, prepare_monthly_extent


def _frame(extent, invalid_pct=None):
    index = pd.date_range("2000-01-01", periods=len(extent), freq="MS")
    data = {"extent_pct": extent}
    if invalid_pct is not None:
        data["invalid_pct"] = invalid_pct
    return pd.DataFrame(data, index=index)


def test_candidate_weights_track_observed_fraction():
    prepared = prepare_monthly_extent(_frame([10.0, 20.0, 30.0], [0.0, 50.0, 90.0]))

    weights = candidate_weights(prepared)

    assert weights.tolist() == pytest.approx([1.0, 0.5, 0.1])


def test_candidate_weights_clip_to_floor_and_ceiling():
    prepared = prepare_monthly_extent(_frame([10.0, 20.0], [99.5, 0.0]))

    weights = candidate_weights(prepared)

    # 0.5% observed would be 0.005; the floor keeps it informative but small.
    assert weights.iloc[0] == pytest.approx(0.05)
    assert weights.iloc[1] == pytest.approx(1.0)


def test_candidate_weights_are_zero_for_unusable_months():
    prepared = prepare_monthly_extent(_frame([10.0, np.nan, 30.0], [0.0, 0.0, 0.0]))

    weights = candidate_weights(prepared)

    assert weights.iloc[1] == 0.0
    assert (weights.iloc[[0, 2]] > 0).all()


def test_candidate_weights_treat_unknown_quality_as_fully_observed():
    prepared = prepare_monthly_extent(_frame([10.0, 20.0]))

    weights = candidate_weights(prepared)

    assert weights.tolist() == pytest.approx([1.0, 1.0])
