import numpy as np
import pandas as pd

from hydroseason._semi_markov import fit_semi_markov_boundaries


def _seasonal_frame():
    index = pd.date_range("2019-01-01", periods=36, freq="MS")
    annual = np.array([80, 75, 60, 40, 25, 15, 8, 4, 3, 5, 20, 55], dtype=float)
    return pd.DataFrame({
        "extent_pct": np.tile(annual, 3),
        "observed_fraction": 1.0,
        "candidate_usable": True,
    }, index=index)


def test_semi_markov_recovers_dry_to_recovery_boundary():
    frame = _seasonal_frame()
    result = fit_semi_markov_boundaries(frame, expected_trough_month=9)
    assert len(result.trough_months) == 3
    assert all(date.month in {9, 10, 11} for date in result.trough_months)
    assert result.state_posterior.shape == (36, 4)
    np.testing.assert_allclose(result.state_posterior.sum(axis=1), 1.0)
    # trough_support sums the dry->recovery *transition* posterior (see
    # `_transition_posterior`) over a +/-1 month window, not raw dry-state
    # occupancy. At most one dry segment ends per year, so this sum must
    # stay close to 1 (a single, sharply-localized transition) -- it must
    # never approach 3, which is what summing three near-1 occupancy
    # values across a flat dry plateau would give under the old (buggy)
    # occupancy-based scoring.
    assert all(support <= 1.5 for support in result.trough_support)


def test_semi_markov_does_not_turn_missing_month_into_transition():
    frame = _seasonal_frame()
    frame.loc[pd.Timestamp("2020-09-01"), ["candidate_usable", "observed_fraction"]] = [False, 0.0]
    result = fit_semi_markov_boundaries(frame, expected_trough_month=9)
    assert pd.Timestamp("2020-09-01") not in result.trough_months
