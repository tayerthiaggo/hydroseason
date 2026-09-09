from __future__ import annotations

import pandas as pd

from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import (
    PeakBoundary,
    TroughRefinementPolicy,
    TroughRefinementResult,
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


def test_gap_before_the_true_low_state_does_not_answer_from_the_recession_limb():
    """Opus checkpoint-1 finding F1: `_refine_gap_after_low_state` only ever
    fits the pre-gap segment. A single cloud-obscured month early in the
    recession, with the true (lower) minimum fully observed afterwards, must
    not be answered from the pre-gap segment alone -- the pre-gap segment
    is still descending, so its fitted "low level" is not the actual low
    state, and every month after the gap is fully observed and available.
    """
    values = [
        90.0, 76.33, 62.62, 49.0, 35.33, 21.66, 8.0,
        20.03, 33.56, 47.18, 60.85, 74.41, 88.0,
    ]
    frame = _prepared(values, start="2000-01-01")
    frame.loc["2000-04-01", ["extent_pct", "observed_fraction"]] = float("nan")
    frame.loc["2000-04-01", "quality_state"] = "missing"
    frame.loc["2000-04-01", "candidate_usable"] = False

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2000-01-01"),
        right_peak=_point_peak("2001-01-01"),
        policy=_policy(profile_loss_cutoff=0.05),
    )

    assert result.status != "confirmed"
    assert result.status != "provisional"
    assert result.boundary is None


def test_gap_with_exact_later_return_to_low_abstains_instead_of_pre_gap_only_support():
    """Codex final review C1: a post-gap value materially above the fitted
    low (recovery-looking) followed by a *later* post-gap value that exactly
    equals the pre-gap low is real evidence the low state is not confined to
    the pre-gap segment. The old code only inspected the first post-gap
    value, so it committed to `recovery_crosses_gap` with pre-gap-only
    support and silently dropped the later equivalent low. It must abstain
    instead.
    """
    frame = _prepared([90.0, 60.0, 30.0, 10.0, 10.0, 11.0, 10.0, 30.0, 80.0])
    frame.loc["2020-05-01", ["extent_pct", "observed_fraction"]] = float("nan")
    frame.loc["2020-05-01", "quality_state"] = "missing"
    frame.loc["2020-05-01", "candidate_usable"] = False

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-09-01"),
        policy=_policy(profile_loss_cutoff=0.05),
        measurement_tolerance_pp=0.0,
    )

    assert result.status == "unresolved"
    assert result.reason == "post_gap_return_to_low_state"
    assert result.boundary is None


def test_gap_with_within_tolerance_later_return_to_low_abstains():
    """Same defect as above, but the later post-gap value (9.8%) is only
    within the measurement-tolerance equivalence band of the pre-gap low
    (10%), not exactly equal. A near-miss return must be treated the same
    as an exact one -- it is still evidence the low state continues past
    the gap.
    """
    frame = _prepared([90.0, 60.0, 30.0, 10.0, 10.0, 15.0, 9.8, 30.0, 80.0])
    frame.loc["2020-05-01", ["extent_pct", "observed_fraction"]] = float("nan")
    frame.loc["2020-05-01", "quality_state"] = "missing"
    frame.loc["2020-05-01", "candidate_usable"] = False

    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-09-01"),
        policy=_policy(profile_loss_cutoff=0.05),
        measurement_tolerance_pp=1.0,
    )

    assert result.status == "unresolved"
    assert result.reason == "post_gap_return_to_low_state"
    assert result.boundary is None


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


def test_low_quality_recession_month_adjacent_to_peak_abstains():
    """A low-quality month right next to the peak degrades to abstention
    once its removal-sensitivity scenario is checked honestly.

    Before the calendar-gap fix, `_quality_sensitivity` modelled "what if
    this month were entirely missing" by dropping its row from the frame,
    which silently closed the resulting calendar gap (the neighbouring
    months became falsely consecutive) and let this case reach "confirmed".
    With the row correctly retained as an explicit unobserved month, that
    scenario re-enters `_refine_selected_span` as a genuine one-month gap at
    the very start of the span (position 1 of 7). `_refine_gap_after_low_state`
    refuses any gap that close to a peak (`gap_start <= 1`) before it ever
    attempts a fit, returning `reason="gap_overlaps_low_state"` -- so the
    combined result abstains instead of quietly ignoring the uncertainty.
    This is the corrected, intentionally more conservative behaviour, not a
    regression.
    """
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

    assert result.status == "unresolved"
    assert result.reason == "unstable_quality_sensitivity"
    assert result.boundary is None


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


def test_absent_recovery_month_cannot_be_confirmed():
    """Audit reproduction (6.4): a row missing from the source frame must be
    treated as an unobserved calendar month, not silently compressed away.
    """
    frame = _prepared([90, 60, 30, 10, 20, 45, 80])
    frame = frame.drop(index=pd.Timestamp("2020-05-01"))
    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"), policy=_policy(),
    )
    assert result.status != "confirmed"
    assert result.recovery_start is None


def test_zero_scale_candidate_set_is_invariant_to_data_scaling():
    """Audit reproduction (6.1): scaling data by 0.01 must not change which
    dates are exact-L1-optimal, now that the zero-scale plausibility rule no
    longer applies the dimensionless pp cutoff to a raw L1 loss.
    """
    left = _point_peak("2020-01-01")
    right = _point_peak("2020-07-01")
    policy = _policy(profile_loss_cutoff=0.05, pulse_z=1.5)

    results = []
    for factor in (1.0, 0.01):
        frame = _prepared(list(factor * pd.array([90, 60, 30, 10, 10.2, 45, 80])))
        results.append(
            refine_trough_span(frame, left_peak=left, right_peak=right, policy=policy)
        )

    assert results[0].local_scale_pp == 0.0
    assert results[1].local_scale_pp == 0.0
    assert results[0].loss_basis == "exact_l1"
    assert results[1].loss_basis == "exact_l1"
    assert results[0].boundary_candidates == results[1].boundary_candidates
    assert results[0].boundary_candidates == (pd.Timestamp("2020-04-01"),)


def test_positive_measurement_tolerance_reaches_nominal_and_sensitivity_fits():
    """`measurement_tolerance_pp` must thread through the nominal fit and the
    quality-sensitivity scenarios, not just the top-level call.
    """
    frame = _mark_low_quality(
        _prepared([90.0, 60.0, 30.0, 10.0, 20.0, 45.0, 80.0]),
        "2020-05-01",
    )
    result = refine_trough_span(
        frame,
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
        measurement_tolerance_pp=5.0,
    )
    assert result.local_scale_pp >= 5.0
    assert result.loss_basis == "standardized_huber"


def test_measurement_tolerance_must_be_finite_and_nonnegative():
    import pytest

    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="measurement_tolerance_pp"):
            refine_trough_span(
                _simple_span(),
                left_peak=_point_peak("2020-01-01"),
                right_peak=_point_peak("2020-07-01"),
                policy=_policy(),
                measurement_tolerance_pp=bad,
            )


def test_tiny_residual_noise_cannot_drive_scale_below_pixel_floor():
    """A residual/difference estimator below one-pixel resolution must be
    floored, not returned as-is (the audit's "only if both vanish" bug).
    """
    import numpy as np

    from hydroseason._trough_refinement import _CandidateFit, _local_scale

    values = np.array([90.0, 60.0, 30.0, 10.0001, 10.0, 45.0, 80.0])
    fitted = np.array([90.0, 60.0, 30.0, 10.0, 10.0, 45.0, 80.0])
    preliminary = _CandidateFit(
        start_position=3, end_position=4, fitted=fitted, loss=0.0, converged=True
    )
    frame = pd.DataFrame({"n_valid": [100] * 7})  # pixel floor = 100/100 = 1.0 pp
    scale = _local_scale(values, preliminary, frame, measurement_tolerance_pp=0.0)
    assert scale >= 1.0


def test_positive_scale_equivariance_when_data_and_tolerance_scale_together():
    """When scale > 0, scaling both the data and the explicit measurement
    tolerance by the same positive factor must not change which endpoint
    candidates are selected -- the standardized Huber comparison is
    dimensionless once scale itself is derived consistently.
    """
    left = _point_peak("2020-01-01")
    right = _point_peak("2020-07-01")
    policy = _policy(profile_loss_cutoff=0.1, pulse_z=1.5)

    base_values = [90.0, 60.0, 20.0, 12.0, 18.0, 45.0, 85.0]
    results = []
    for factor in (0.1, 1.0):
        frame = _prepared([factor * v for v in base_values])
        results.append(
            refine_trough_span(
                frame, left_peak=left, right_peak=right, policy=policy,
                measurement_tolerance_pp=factor * 2.0,
            )
        )
    assert results[0].loss_basis == "standardized_huber"
    assert results[1].loss_basis == "standardized_huber"
    assert results[0].boundary_candidates == results[1].boundary_candidates


def test_combine_sensitivity_results_uses_a_real_scenario_boundary_not_union_end():
    """`_combine_sensitivity_results` must report a scenario's own selected
    operational boundary, not the union support set's last date -- those
    differ once a single scenario's own support set legitimately extends
    past its own operational boundary (the Task 2 untruncated-cluster fix).
    """
    from hydroseason._trough_refinement import _combine_sensitivity_results

    def _result(boundary: str, candidates: list[str]) -> TroughRefinementResult:
        return TroughRefinementResult(
            status="confirmed",
            reason="accepted",
            boundary=pd.Timestamp(boundary),
            boundary_candidates=tuple(pd.Timestamp(c) for c in candidates),
            low_state_start=pd.Timestamp(candidates[0]),
            low_state_end=pd.Timestamp(boundary),
            recovery_start=pd.Timestamp(boundary) + pd.DateOffset(months=1),
            pulse_months=(),
            local_scale_pp=0.0,
            best_loss=0.0,
            effective_support=3.0,
            policy_version="test",
        )

    nominal = _result("2020-04-01", ["2020-03-01", "2020-04-01"])
    scenario_a = _result("2020-04-01", ["2020-03-01", "2020-04-01"])
    # This scenario's own support set extends one month past its own chosen
    # operational boundary -- exactly the untruncated shape Task 2 produces.
    scenario_b = _result("2020-04-01", ["2020-03-01", "2020-04-01", "2020-05-01"])

    combined = _combine_sensitivity_results(
        nominal, [scenario_a, scenario_b], unstable_reason="unstable"
    )
    assert combined.boundary == pd.Timestamp("2020-04-01")
    assert combined.boundary_candidates == (
        pd.Timestamp("2020-03-01"),
        pd.Timestamp("2020-04-01"),
        pd.Timestamp("2020-05-01"),
    )


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
