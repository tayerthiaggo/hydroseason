from __future__ import annotations

import pandas as pd

from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import (
    PeakBoundary,
    TroughRefinementPolicy,
    refine_trough_span,
)


def _prepared(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(values), freq="MS")
    raw = pd.DataFrame(
        {"extent_pct": values, "invalid_pct": 0.0},
        index=index,
    )
    return prepare_monthly_extent(raw)


def _policy(**overrides: float) -> TroughRefinementPolicy:
    values = {
        "huber_k": 1.345,
        "profile_loss_cutoff": 0.1,
        "pulse_z": 2.0,
    }
    values.update(overrides)
    return TroughRefinementPolicy(**values)


def _point_peak(date: str, *, quality: str = "normal") -> PeakBoundary:
    timestamp = pd.Timestamp(date)
    return PeakBoundary(
        selected=timestamp,
        candidates=(timestamp,),
        timing_status="point",
        quality=quality,
    )


def _simple_span() -> pd.DataFrame:
    return _prepared([90.0, 60.0, 20.0, 10.0, 30.0, 70.0, 85.0])


def test_missing_peak_makes_refinement_unavailable():
    result = refine_trough_span(
        _simple_span(),
        left_peak=PeakBoundary.missing(),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(),
    )

    assert result.status == "unavailable"
    assert result.reason == "missing_or_unresolved_peak"
    assert result.boundary is None


def test_open_span_awaits_next_peak():
    result = refine_trough_span(
        _simple_span(),
        left_peak=_point_peak("2020-01-01"),
        right_peak=None,
        policy=_policy(),
    )

    assert result.status == "awaiting_next_peak"
    assert result.reason == "open_span"
    assert result.boundary is None


def test_point_trough_is_last_low_month_before_continuous_recovery():
    result = refine_trough_span(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "confirmed"
    assert result.boundary_candidates == (pd.Timestamp("2020-04-01"),)
    assert result.boundary == pd.Timestamp("2020-04-01")
    assert result.low_state_start == pd.Timestamp("2020-04-01")
    assert result.low_state_end == pd.Timestamp("2020-04-01")
    assert result.recovery_start == pd.Timestamp("2020-05-01")


def test_boundary_interval_uses_latest_supported_endpoint():
    result = refine_trough_span(
        _prepared([90.0, 50.0, 10.0, 10.0, 10.0, 30.0, 80.0]),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "confirmed"
    assert result.boundary_candidates == tuple(
        pd.date_range("2020-03-01", "2020-05-01", freq="MS")
    )
    assert result.boundary == pd.Timestamp("2020-05-01")
    assert result.low_state_start == pd.Timestamp("2020-03-01")
    assert result.low_state_end == pd.Timestamp("2020-05-01")
    assert result.recovery_start == pd.Timestamp("2020-06-01")


def test_exact_flat_span_uses_deterministic_zero_scale_path():
    kwargs = {
        "left_peak": _point_peak("2020-01-01"),
        "right_peak": _point_peak("2020-05-01"),
        "policy": _policy(profile_loss_cutoff=0.0),
    }

    first = refine_trough_span(_prepared([10.0] * 5), **kwargs)
    second = refine_trough_span(_prepared([10.0] * 5), **kwargs)

    assert first == second
    assert first.local_scale_pp == 0.0
    assert first.best_loss == 0.0
    assert first.boundary_candidates == tuple(
        pd.date_range("2020-02-01", "2020-04-01", freq="MS")
    )
