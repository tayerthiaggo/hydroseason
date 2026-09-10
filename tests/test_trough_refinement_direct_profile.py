from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import (
    PeakBoundary,
    TroughRefinementPolicy,
    refine_trough_span,
)
from hydroseason._trough_refinement_direct_profile import refine_selected_span_direct_profile


def _prepared(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(values), freq="MS")
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
    return prepare_monthly_extent(raw)


def _point_peak(date: str, *, quality: str = "normal") -> PeakBoundary:
    timestamp = pd.Timestamp(date)
    return PeakBoundary(selected=timestamp, candidates=(timestamp,), timing_status="point", quality=quality)


def _shape_fit_policy(**overrides) -> TroughRefinementPolicy:
    values = {"huber_k": 1.345, "profile_loss_cutoff": 0.1, "pulse_z": 2.0}
    values.update(overrides)
    return TroughRefinementPolicy(**values)


def _direct_profile_policy(**overrides) -> TroughRefinementPolicy:
    values = {
        "huber_k": 1.345, "profile_loss_cutoff": 0.05, "pulse_z": 1.5,
        "version": "direct_profile_combined_v1", "candidate": "direct_profile_combined",
        "delta_pp": 0.4, "l_uncertainty_k": 2.0, "scale_mode": "combined",
    }
    values.update(overrides)
    return TroughRefinementPolicy(**values)


def test_frozen_direct_profile_defaults_are_valid():
    from hydroseason._trough_refinement_direct_profile_defaults import (
        TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY,
    )

    policy = TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY
    assert policy.candidate == "direct_profile_combined"
    assert policy.delta_pp == 0.02
    assert policy.version == "direct_profile_combined_v1"


class TestPolicyValidation:
    def test_default_candidate_is_shape_fit(self):
        policy = _shape_fit_policy()
        assert policy.candidate == "shape_fit"

    def test_direct_profile_candidate_requires_delta_pp(self):
        with pytest.raises(ValueError, match="delta_pp"):
            TroughRefinementPolicy(
                huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5,
                candidate="direct_profile_combined",
            )

    def test_direct_profile_candidate_rejects_non_positive_delta_pp(self):
        with pytest.raises(ValueError, match="delta_pp"):
            _direct_profile_policy(delta_pp=0.0)

    def test_unknown_candidate_rejected(self):
        with pytest.raises(ValueError, match="candidate"):
            _shape_fit_policy(candidate="not_a_real_candidate")

    def test_shape_fit_candidate_ignores_delta_pp_requirement(self):
        # delta_pp stays None (its default) for the existing candidate -- it
        # must not become a silently-required field for shape_fit callers.
        policy = _shape_fit_policy()
        assert policy.delta_pp is None


class TestDispatch:
    """refine_trough_span must route to the direct-profile core under the
    exact same peak/quality sensitivity ensemble used for shape_fit -- see
    hydroseason/_trough_refinement_direct_profile.py."""

    def test_direct_profile_candidate_produces_a_boundary(self):
        frame = _prepared([40.0, 20.0, 12.0, 12.1, 12.3, 20.0, 40.0])
        left = _point_peak("2020-01-01")
        right = _point_peak("2020-07-01")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(delta_pp=0.4),
        )
        assert result.boundary == pd.Timestamp("2020-05-01")
        assert result.policy_version == "direct_profile_combined_v1"

    def test_shape_fit_candidate_unaffected_by_new_fields(self):
        # Same fixture, default (shape_fit) candidate: must reproduce exactly
        # today's production behavior -- zero regression from adding the new
        # dispatch seam.
        frame = _prepared([40.0, 20.0, 12.0, 12.1, 12.3, 20.0, 40.0])
        left = _point_peak("2020-01-01")
        right = _point_peak("2020-07-01")
        result = refine_trough_span(frame, left_peak=left, right_peak=right, policy=_shape_fit_policy())
        assert result.policy_version == "trough_refinement_candidate_0_2"

    def test_direct_profile_flat_series_no_departure(self):
        frame = _prepared([12.0, 12.0, 12.0, 12.0, 12.0])
        left = _point_peak("2020-01-01")
        right = _point_peak("2020-05-01")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(delta_pp=0.4),
        )
        assert result.boundary is None

    def test_direct_profile_pulse_does_not_reset_low_state(self):
        dates = pd.date_range("2020-01-01", periods=9, freq="MS")
        values = [40.0, 20.0, 12.0, 12.1, 30.0, 12.2, 12.3, 20.0, 40.0]
        frame = _prepared(values)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(delta_pp=0.4),
        )
        assert result.boundary == dates[6]
        assert dates[4] in result.pulse_months

    def test_direct_profile_gap_adjacent_to_low_state_is_unresolved(self):
        dates = pd.date_range("2020-01-01", periods=8, freq="MS")
        values = [40.0, 20.0, 12.0, 12.1, 12.3, np.nan, np.nan, 12.2]
        frame = _prepared(values)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(delta_pp=0.4),
        )
        assert result.status == "unresolved"
        assert result.boundary is None


def _prepared_with_quality(values: list[float], invalid_pct: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(values), freq="MS")
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": invalid_pct}, index=index)
    return prepare_monthly_extent(raw)


class TestQualityAwareBoundarySelection:
    """direct_profile_combined only (shape_fit is frozen -- see the migration
    doc). The statistically-plausible support cluster can legitimately
    include a month whose own observation is heavily cloud-contaminated
    (high invalid_pct): the profile only sees its value, not its
    reliability. Publishing that month as the operational boundary is
    risky for any downstream step that pulls the raster/extent layer at
    the reported date (a near-half-invalid layer has little valid data to
    work with). The adopted boundary must be the latest month in the
    support cluster that is ALSO reliable (quality_state != "low"),
    falling back through the cluster, and abstaining (unresolved) if no
    month in it is reliable -- never publishing a boundary the pipeline
    cannot itself trust enough to use.
    """

    def _span(self, invalid_pct):
        values = [40.0, 20.0, 12.0, 12.1, 12.3, 20.0, 40.0]
        return _prepared_with_quality(values, invalid_pct)

    def test_low_quality_latest_month_defers_to_the_last_reliable_one(self):
        # support cluster is {2020-03, 2020-04, 2020-05} at this scale/k;
        # 2020-05 (the naive latest) is heavily cloud-contaminated.
        frame = self._span([0, 0, 0, 0, 45.0, 0, 0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(delta_pp=0.4, l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.boundary == pd.Timestamp("2020-04-01")

    def test_falls_back_through_multiple_unreliable_months(self):
        frame = self._span([0, 0, 0, 40.0, 45.0, 0, 0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(delta_pp=0.4, l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.boundary == pd.Timestamp("2020-03-01")

    def test_abstains_when_no_month_in_the_cluster_is_reliable(self):
        frame = self._span([0, 0, 30.0, 40.0, 45.0, 0, 0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(delta_pp=0.4, l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.status == "unresolved"
        assert result.boundary is None

    def test_reliable_latest_month_is_unaffected(self):
        # Regression: when the naive latest month is already reliable,
        # behavior must be identical to before this change.
        frame = self._span([0, 0, 0, 0, 0, 0, 0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(delta_pp=0.4, l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.boundary == pd.Timestamp("2020-05-01")


class TestGapPathValuePlausibility:
    """direct_profile_combined only. ``_refine_gap_direct_profile`` always
    treats the last OBSERVED pre-gap month as the low state's own endpoint,
    fitting a block that forces it in and only checking its quality -- never
    whether its raw value is actually a plausible low-state member. A real
    month (e.g. Daly River HY2016/HY2024's December: a real, fully-usable
    but sharply elevated observation immediately before a low-quality
    January) can pass that quality check while still being far outside the
    equivalence band any other low-state month sits in. The published
    boundary must defer to the latest month that is BOTH quality-reliable
    AND value-plausible (within delta_pp of the segment's own natural
    reference level), not just quality-reliable.
    """

    def _gap_frame(self, before_tail: float) -> pd.DataFrame:
        # Sep/Oct/Nov analogue at ~12, then a spike immediately before a
        # real data gap (Jan masked), then a clear post-gap recovery.
        values = [40.0, 20.0, 12.0, 12.1, 12.3, before_tail, np.nan, 50.0]
        return _prepared(values)

    def test_implausible_naive_endpoint_defers_to_the_last_plausible_month(self):
        frame = self._gap_frame(before_tail=24.0)
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(delta_pp=0.4), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2020-05-01")
        assert result.reason == "boundary_deferred_to_implausible_month"

    def test_plausible_naive_endpoint_is_unaffected(self):
        # Regression: when the naive last pre-gap month genuinely belongs to
        # the low state, behavior is unchanged from before this fix.
        frame = self._gap_frame(before_tail=12.2)
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(delta_pp=0.4), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2020-06-01")
        assert result.reason == "recovery_crosses_gap"
