import pandas as pd
import pytest

from hydroseason._recurrence_identifiability import (
    ELIGIBLE_RECURRENCE_POLICIES,
    narrow_most_recent_recurrence,
)


def _dates(*values: str) -> tuple[pd.Timestamp, ...]:
    return tuple(pd.Timestamp(value) for value in values)


def _narrow(dates, *, policy, start="1990-01-01", end="1991-06-01", limit=2):
    return narrow_most_recent_recurrence(
        dates,
        window_start=pd.Timestamp(start),
        window_end=pd.Timestamp(end),
        max_boundary_interval_months=limit,
        policy=policy,
    )


def test_eligible_policy_order_is_frozen():
    assert ELIGIBLE_RECURRENCE_POLICIES == (
        "no_narrowing",
        "annual_shape_match",
        "long_window_last_cluster",
    )


def test_no_narrowing_returns_original_tuple_verbatim():
    dates = _dates("1991-04-01", "1990-04-01")
    assert _narrow(dates, policy="no_narrowing") is dates


def test_short_window_never_narrows():
    dates = _dates("1990-01-01", "1990-11-01")
    assert _narrow(dates, policy="long_window_last_cluster", end="1990-12-01") == dates


def test_long_window_legacy_ablation_keeps_last_resolved_cluster():
    dates = _dates("1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="long_window_last_cluster") == _dates("1991-03-01")


def test_annual_shape_match_accepts_one_month_phase_drift():
    dates = _dates("1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="annual_shape_match") == _dates("1991-03-01")


def test_annual_shape_match_rejects_large_cluster_plus_singleton():
    dates = _dates(
        "1992-05-01",
        "1992-06-01",
        "1992-07-01",
        "1992-08-01",
        "1992-09-01",
        "1993-01-01",
        "1993-04-01",
    )
    assert (
        _narrow(
            dates,
            policy="annual_shape_match",
            start="1992-05-01",
            end="1993-10-01",
        )
        == dates
    )


def test_annual_shape_match_is_symmetric_for_interval_shapes():
    # An interval in the earlier year and a point in the later one is not the
    # same annual shape: the later year's remaining equivalent months may just
    # be missing.  Symmetric nearest-date distance alone accepts this pair
    # (every distance is <= 1); the equal-span requirement is what rejects it.
    dates = _dates("1990-03-01", "1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="annual_shape_match") == dates


def test_annual_shape_match_declines_the_annual_aligned_fragment_trap():
    # Corpus family ``annual_aligned_fragment_trap`` (offsets 1, 2, 3, 13),
    # truth unresolved.  Candidate C must decline it while the legacy ablation
    # narrows it; that separation is the family's entire purpose.
    dates = _dates("1990-02-01", "1990-03-01", "1990-04-01", "1991-02-01")
    assert _narrow(dates, policy="annual_shape_match") == dates
    assert _narrow(dates, policy="long_window_last_cluster") == _dates("1991-02-01")


@pytest.mark.parametrize("dates", [(), _dates("1990-04-01")])
def test_empty_and_singleton_sets_are_unchanged(dates):
    assert _narrow(dates, policy="annual_shape_match") == dates


def test_one_cluster_is_unchanged():
    dates = _dates("1990-03-01", "1990-04-01", "1990-05-01")
    assert _narrow(dates, policy="annual_shape_match") == dates


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("1990-01-02", "1991-01-01", "month-start"),
        ("1991-01-01", "1990-01-01", "not precede"),
    ],
)
def test_invalid_caller_bounds_are_rejected(start, end, message):
    with pytest.raises(ValueError, match=message):
        _narrow(
            _dates("1990-04-01", "1991-04-01"),
            policy="annual_shape_match",
            start=start,
            end=end,
        )


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match="recurrence policy"):
        _narrow(_dates("1990-04-01", "1991-04-01"), policy="legacy_last_cluster")


def test_narrowed_dates_are_always_a_subset_of_input():
    base = pd.date_range("1990-01-01", periods=24, freq="MS")
    for mask in range(1, 1 << 8):
        dates = tuple(base[i] for i in range(8) if mask & (1 << i)) + (base[19],)
        for policy in ELIGIBLE_RECURRENCE_POLICIES:
            result = _narrow(dates, policy=policy, end="1991-12-01")
            assert set(result).issubset(dates)


import numpy as np

from hydroseason._timing_identifiability import (
    TimingIdentifiabilityThresholds,
    assess_window_timing,
)

WINDOW_THRESHOLDS = TimingIdentifiabilityThresholds(1.5, 1, 0, 2, 2)


def _window_result(values, index, *, policy, window_start=None, window_end=None):
    series = pd.Series(values, index=pd.to_datetime(index), dtype=float)
    rows = pd.DataFrame({"n_valid": 100}, index=series.index)
    return assess_window_timing(
        series,
        rows,
        thresholds=WINDOW_THRESHOLDS,
        measurement_tolerance_pct=1.0,
        noise_pp=0.0,
        pixel_support_status="unavailable",
        recurrence_policy=policy,
        window_start=window_start,
        window_end=window_end,
    )


def test_window_assessor_drives_explicit_candidate_policy():
    index = pd.date_range("1990-02-01", periods=18, freq="MS")
    values = [5.0] * 2 + [10.0] + [5.0] * 10 + [10.0] + [5.0] * 3 + [0.0]
    result = _window_result(values, index, policy="annual_shape_match")
    assert result.peak_status == "point"
    assert result.peak_dates == (pd.Timestamp("1991-03-01"),)


# Both bound tests need a window whose peak set is genuinely ``unresolved``,
# because that is the only branch that calls ``narrow_most_recent_recurrence()``
# at all.  ``[10, 5, 10]`` spans 2 months, which is within
# ``max_boundary_interval_months=2``, so it resolves to ``interval`` and the
# narrowing code is never reached; ``[10, 5, 5, 5, 10]`` spans 4 and is.


def test_derived_bounds_normalise_non_month_start_value_index():
    index = ["1990-01-15", "1990-02-15", "1990-03-15", "1990-04-15", "1990-05-15"]
    result = _window_result(
        [10.0, 5.0, 5.0, 5.0, 10.0], index, policy="no_narrowing"
    )
    assert result.detectable is True
    assert result.peak_status == "unresolved"
    assert result.peak_dates == (
        pd.Timestamp("1990-01-15"),
        pd.Timestamp("1990-05-15"),
    )


def test_explicit_non_month_start_bound_is_rejected():
    with pytest.raises(ValueError, match="month-start"):
        _window_result(
            [10.0, 5.0, 5.0, 5.0, 10.0],
            pd.date_range("1990-01-01", periods=5, freq="MS"),
            policy="no_narrowing",
            window_start=pd.Timestamp("1990-01-02"),
            window_end=pd.Timestamp("1990-05-01"),
        )

