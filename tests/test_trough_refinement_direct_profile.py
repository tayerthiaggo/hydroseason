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
