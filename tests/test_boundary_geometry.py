"""Record- and cohort-level geometry diagnostics.

These summarise where boundaries were found.  They never choose one, so no
test here may assert a boundary date.
"""
import numpy as np
import pandas as pd
import pytest

from hydroseason._boundary_geometry import (
    BoundaryGeometrySummary,
    bootstrap_catchment_rate,
    summarise_boundary_geometry,
)


def _annual(edge_flags, *, observed=None, lower=None, radius=3, retry="not_attempted"):
    n = len(edge_flags)
    observed = [False] * n if observed is None else observed
    lower = [False] * n if lower is None else lower
    return pd.DataFrame(
        {
            "hy_year": range(2000, 2000 + n),
            "trough_month": pd.date_range("2000-07-01", periods=n, freq="12MS"),
            "trough_search_radius_used": [radius] * n,
            "boundary_at_search_edge": edge_flags,
            "boundary_search_edge_side": ["right" if f else "none" for f in edge_flags],
            "outside_window_observed": observed,
            "outside_window_lower": lower,
            "retry_outcome": [retry] * n,
        }
    )


def test_edge_rate_publishes_numerator_and_denominator():
    summary = summarise_boundary_geometry(_annual([True, False, False, True]))
    assert isinstance(summary, BoundaryGeometrySummary)
    assert summary.n_boundaries == 4
    assert summary.n_at_search_edge == 2
    assert summary.boundary_search_edge_rate == pytest.approx(0.5)


def test_within_catchment_interval_is_labelled_an_understatement():
    summary = summarise_boundary_geometry(_annual([True, False, False, True]))
    assert summary.interval_method == "wilson_within_catchment"
    low, high = summary.boundary_search_edge_interval
    assert 0.0 <= low <= summary.boundary_search_edge_rate <= high <= 1.0


def test_challenge_rate_uses_the_observed_span_denominator_not_all_boundaries():
    """The two rates have different denominators and must not be compared."""
    annual = _annual(
        [False] * 4,
        observed=[True, True, False, False],
        lower=[True, False, False, False],
    )
    summary = summarise_boundary_geometry(annual)
    assert summary.n_boundaries == 4
    assert summary.n_outside_window_observed == 2
    assert summary.n_outside_window_lower == 1
    assert summary.outside_window_lower_rate == pytest.approx(0.5)


def test_unresolved_rows_are_excluded_from_every_denominator():
    annual = _annual([True, False])
    annual.loc[1, "trough_month"] = pd.NaT
    summary = summarise_boundary_geometry(annual)
    assert summary.n_boundaries == 1
    assert summary.boundary_search_edge_rate == pytest.approx(1.0)


def test_empty_frame_reports_zero_not_nan():
    summary = summarise_boundary_geometry(_annual([]).iloc[0:0])
    assert summary.n_boundaries == 0
    assert summary.boundary_search_edge_rate == 0.0
    assert summary.boundary_search_edge_interval == (0.0, 0.0)


def test_radius_and_retry_counts_are_reported():
    summary = summarise_boundary_geometry(_annual([False] * 3, radius=5, retry="applied"))
    assert summary.radius_used_counts == {5: 3}
    assert summary.retry_outcome_counts == {"applied": 3}


def test_cohort_bootstrap_resamples_catchments_not_cycles():
    """Twenty catchments of twenty identical cycles must not look like 400 draws."""
    clustered = [(20, 20)] * 10 + [(0, 20)] * 10
    low, high = bootstrap_catchment_rate(clustered, seed=0, n_resamples=500)
    assert 0.0 <= low < 0.5 < high <= 1.0
    # A cycle-level interval on 200/400 successes would be roughly +/-0.05.
    assert (high - low) > 0.2


def test_cohort_bootstrap_is_deterministic_for_a_fixed_seed():
    data = [(3, 10), (1, 12), (7, 9), (0, 15)]
    assert bootstrap_catchment_rate(data, seed=7, n_resamples=200) == bootstrap_catchment_rate(
        data, seed=7, n_resamples=200
    )


def test_cohort_bootstrap_rejects_an_empty_cohort():
    with pytest.raises(ValueError, match="at least one catchment"):
        bootstrap_catchment_rate([], seed=0)
