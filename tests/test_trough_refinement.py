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


def _mark_low_quality(
    frame: pd.DataFrame,
    date: str,
    *,
    observed_fraction: float = 0.5,
) -> pd.DataFrame:
    changed = frame.copy()
    timestamp = pd.Timestamp(date)
    changed.loc[timestamp, "observed_fraction"] = observed_fraction
    changed.loc[timestamp, "invalid_pct"] = 100.0 * (1.0 - observed_fraction)
    changed.loc[timestamp, "quality_state"] = "low"
    changed.loc[timestamp, "candidate_usable"] = True
    return changed


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


def test_continuous_fitzroy_recovery_assigns_january_to_next_cycle():
    result = refine_trough_span(
        _prepared(
            [
                34.863511,
                1.885925,
                1.515238,
                1.287817,
                1.221751,
                1.038752,
                0.794876,
                0.743982,
                0.699226,
                0.540206,
                0.568017,
                35.0,
            ],
            start="2021-03-01",
        ),
        left_peak=_point_peak("2021-03-01"),
        right_peak=_point_peak("2022-02-01"),
        policy=_policy(profile_loss_cutoff=0.05),
    )

    assert result.boundary == pd.Timestamp("2021-12-01")
    assert result.boundary_candidates[-1] == pd.Timestamp("2021-12-01")
    assert result.recovery_start == pd.Timestamp("2022-01-01")


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


def test_large_early_pulse_returns_to_low_state_before_recovery():
    result = refine_trough_span(
        _prepared([90.0, 60.0, 20.0, 55.0, 10.0, 18.0, 35.0, 60.0, 85.0]),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-09-01"),
        policy=_policy(profile_loss_cutoff=0.0, pulse_z=1.0),
    )

    assert result.status == "confirmed"
    assert result.boundary == pd.Timestamp("2020-05-01")
    assert result.recovery_start == pd.Timestamp("2020-06-01")
    assert result.pulse_months == (pd.Timestamp("2020-04-01"),)


def test_two_rewetting_pulses_stay_inside_one_cycle():
    result = refine_trough_span(
        _prepared(
            [90.0, 60.0, 20.0, 55.0, 15.0, 45.0, 10.0, 18.0, 40.0, 70.0, 90.0]
        ),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-11-01"),
        policy=_policy(profile_loss_cutoff=0.0, pulse_z=1.0),
    )

    assert result.status == "confirmed"
    assert result.boundary == pd.Timestamp("2020-07-01")
    assert result.recovery_start == pd.Timestamp("2020-08-01")
    assert result.pulse_months == (
        pd.Timestamp("2020-04-01"),
        pd.Timestamp("2020-06-01"),
    )


def test_separated_endpoint_clusters_choose_later_after_observed_return():
    result = refine_trough_span(
        _prepared([90.0, 50.0, 10.0, 50.0, 10.0, 30.0, 80.0]),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0, pulse_z=1.0),
    )

    assert result.status == "confirmed"
    assert result.boundary_candidates == (pd.Timestamp("2020-05-01"),)
    assert result.boundary == pd.Timestamp("2020-05-01")
    assert result.pulse_months == (pd.Timestamp("2020-04-01"),)


def test_separated_endpoint_clusters_are_never_bridged_without_clear_pulse():
    result = refine_trough_span(
        _prepared([90.0, 50.0, 10.0, 50.0, 10.0, 30.0, 80.0]),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0, pulse_z=4.0),
    )

    assert result.status == "unresolved"
    assert result.reason == "disjoint_modes"
    assert result.boundary is None
    assert result.boundary_candidates == (
        pd.Timestamp("2020-03-01"),
        pd.Timestamp("2020-05-01"),
    )


def test_gap_after_observed_low_state_keeps_provisional_boundary():
    frame = _prepared([90.0, 50.0, 20.0, 10.0, 0.0, 40.0, 80.0])
    frame.loc["2020-05-01", ["extent_pct", "observed_fraction"]] = float("nan")
    frame.loc["2020-05-01", "quality_state"] = "missing"
    frame.loc["2020-05-01", "candidate_usable"] = False

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "provisional"
    assert result.reason == "recovery_crosses_gap"
    assert result.boundary == pd.Timestamp("2020-04-01")
    assert result.recovery_start is None


def test_daly_gap_keeps_full_pre_gap_low_state_and_uses_november_boundary():
    frame = _prepared(
        [10.0, 5.0, 1.0, 0.1188, 0.1194, 0.1218, 0.0, 0.8, 8.0, 40.0, 90.0],
        start="2005-06-01",
    )
    frame.loc["2005-11-01", "extent_pct"] = 0.1218
    frame.loc["2005-12-01", ["extent_pct", "observed_fraction"]] = float("nan")
    frame.loc["2005-12-01", "quality_state"] = "missing"
    frame.loc["2005-12-01", "candidate_usable"] = False

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2005-06-01"),
        right_peak=_point_peak("2006-04-01"),
        policy=_policy(profile_loss_cutoff=0.05),
    )

    assert result.status == "provisional"
    assert result.reason == "recovery_crosses_gap"
    assert result.boundary_candidates == tuple(
        pd.date_range("2005-09-01", "2005-11-01", freq="MS")
    )
    assert result.boundary == pd.Timestamp("2005-11-01")
    assert result.recovery_start is None


def test_gap_overlapping_possible_low_state_is_unresolved():
    frame = _prepared([90.0, 50.0, 10.0, 0.0, 10.0, 35.0, 80.0])
    frame.loc["2020-04-01", ["extent_pct", "observed_fraction"]] = float("nan")
    frame.loc["2020-04-01", "quality_state"] = "missing"
    frame.loc["2020-04-01", "candidate_usable"] = False

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.1),
    )

    assert result.status == "unresolved"
    assert result.reason == "gap_overlaps_low_state"
    assert result.boundary is None


def test_low_quality_month_essential_to_recovery_is_provisional():
    frame = _mark_low_quality(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        "2020-05-01",
    )

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.boundary_candidates == (
        pd.Timestamp("2020-04-01"),
        pd.Timestamp("2020-05-01"),
    )
    assert result.boundary == pd.Timestamp("2020-05-01")
    assert result.status == "provisional"
    assert result.reason == "essential_low_quality_recovery"


def test_low_quality_recession_month_does_not_prevent_confirmation():
    frame = _mark_low_quality(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        "2020-02-01",
    )

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "confirmed"
    assert result.boundary == pd.Timestamp("2020-04-01")


def test_low_quality_trough_that_changes_under_support_bounds_is_unresolved():
    frame = _mark_low_quality(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        "2020-04-01",
    )

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "unresolved"
    assert result.reason == "unstable_quality_sensitivity"
    assert result.boundary is None


def test_interval_peak_propagation_is_explicitly_provisional():
    left = PeakBoundary(
        selected=pd.Timestamp("2020-01-01"),
        candidates=(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")),
        timing_status="interval",
        quality="normal",
    )

    result = refine_trough_span(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        left_peak=left,
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "provisional"
    assert result.reason == "interval_peak"
    assert result.boundary == pd.Timestamp("2020-04-01")


def test_interval_peak_with_unstable_trough_does_not_replace_pass_one():
    frame = _prepared(
        [90.0, 64.068, 21.097, 72.208, 74.673, 26.379, 62.498, 38.963, 88.0]
    )
    left = PeakBoundary(
        selected=pd.Timestamp("2020-01-01"),
        candidates=(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")),
        timing_status="interval",
        quality="normal",
    )

    result = refine_trough_span(
        frame,
        left_peak=left,
        right_peak=_point_peak("2020-09-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "unresolved"
    assert result.reason == "unstable_peak_sensitivity"
    assert result.boundary is None


def test_low_quality_identifiable_peak_is_explicitly_provisional():
    result = refine_trough_span(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        left_peak=_point_peak("2020-01-01", quality="low"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )

    assert result.status == "provisional"
    assert result.reason == "low_quality_peak"
    assert result.boundary == pd.Timestamp("2020-04-01")


def test_selected_but_timing_unresolved_peak_disables_refinement():
    right = PeakBoundary(
        selected=pd.Timestamp("2020-07-01"),
        candidates=(),
        timing_status="unresolved",
        quality="normal",
    )

    result = refine_trough_span(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        left_peak=_point_peak("2020-01-01"),
        right_peak=right,
        policy=_policy(),
    )

    assert result.status == "unavailable"
    assert result.reason == "missing_or_unresolved_peak"
