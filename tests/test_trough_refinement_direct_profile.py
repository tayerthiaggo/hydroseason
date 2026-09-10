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
        "delta_rel": 0.05, "l_uncertainty_k": 2.0, "scale_mode": "combined",
    }
    values.update(overrides)
    return TroughRefinementPolicy(**values)


def test_frozen_direct_profile_defaults_are_valid():
    from hydroseason._trough_refinement_direct_profile_defaults import (
        TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY,
    )

    policy = TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY
    assert policy.candidate == "direct_profile_combined"
    assert policy.delta_rel == 0.05
    assert policy.version == "direct_profile_combined_v1"


class TestPolicyValidation:
    def test_default_candidate_is_shape_fit(self):
        policy = _shape_fit_policy()
        assert policy.candidate == "shape_fit"

    def test_direct_profile_candidate_requires_delta_rel(self):
        with pytest.raises(ValueError, match="delta_rel"):
            TroughRefinementPolicy(
                huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5,
                candidate="direct_profile_combined",
            )

    def test_direct_profile_candidate_rejects_non_positive_delta_rel(self):
        with pytest.raises(ValueError, match="delta_rel"):
            _direct_profile_policy(delta_rel=0.0)

    def test_direct_profile_candidate_rejects_a_margin_of_one_or_more(self):
        # delta_rel is a fraction of the low-state level; at 1.0 the
        # equivalence ceiling reaches twice the low state, which is a
        # doubling, not a tie.
        with pytest.raises(ValueError, match="delta_rel"):
            _direct_profile_policy(delta_rel=1.0)

    def test_unknown_candidate_rejected(self):
        with pytest.raises(ValueError, match="candidate"):
            _shape_fit_policy(candidate="not_a_real_candidate")

    def test_shape_fit_candidate_ignores_delta_rel_requirement(self):
        # delta_rel stays None (its default) for the existing candidate -- it
        # must not become a silently-required field for shape_fit callers.
        policy = _shape_fit_policy()
        assert policy.delta_rel is None


class TestDispatch:
    """refine_trough_span must route to the direct-profile core under the
    exact same peak/quality sensitivity ensemble used for shape_fit -- see
    hydroseason/_trough_refinement_direct_profile.py."""

    def test_direct_profile_candidate_produces_a_boundary(self):
        frame = _prepared([40.0, 20.0, 12.0, 12.1, 12.3, 20.0, 40.0])
        left = _point_peak("2020-01-01")
        right = _point_peak("2020-07-01")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(),
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
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(),
        )
        assert result.boundary is None

    def test_direct_profile_pulse_does_not_reset_low_state(self):
        dates = pd.date_range("2020-01-01", periods=9, freq="MS")
        values = [40.0, 20.0, 12.0, 12.1, 30.0, 12.2, 12.3, 20.0, 40.0]
        frame = _prepared(values)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(),
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
            frame, left_peak=left, right_peak=right, policy=_direct_profile_policy(),
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
            policy=_direct_profile_policy(l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.boundary == pd.Timestamp("2020-04-01")

    def test_falls_back_through_multiple_unreliable_months(self):
        frame = self._span([0, 0, 0, 40.0, 45.0, 0, 0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.boundary == pd.Timestamp("2020-03-01")

    def test_abstains_when_the_whole_trough_is_cloud_flagged(self):
        # Every month of the low state is untrusted, so the core solves on
        # the trusted shoulders alone and finds a shallower low state. That
        # answer is not wrong for the data it was given -- it is answerable
        # only because the real trough is hidden -- and catching it is the
        # sensitivity ensemble's job, not the core's: the ensemble replaces
        # each cloud-flagged month with its plausible bounds, gets
        # incompatible answers, and abstains. Asserted through
        # `refine_trough_span` for that reason.
        frame = self._span([0, 0, 30.0, 40.0, 45.0, 0, 0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.status == "unresolved"
        assert result.reason == "unstable_quality_sensitivity"
        assert result.boundary is None

    def test_reliable_latest_month_is_unaffected(self):
        # Regression: when the naive latest month is already reliable,
        # behavior must be identical to before this change.
        frame = self._span([0, 0, 0, 0, 0, 0, 0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(l_uncertainty_k=2.0),
            measurement_tolerance_pp=0.5,
        )
        assert result.boundary == pd.Timestamp("2020-05-01")


class TestScaleRelativeEquivalenceMargin:
    """The equivalence margin is a FRACTION of the low-state level, not a
    fixed number of percentage points.

    An absolute margin cannot serve one catchment's own cycles: Fitzroy
    River's trough level varies 0.0249 (HY2008) to 0.0521 (HY2011) across
    its record, so a margin wide enough to be meaningful at one level
    swallows a real recovery at another. Reviewing both Fitzroy and Gilbert
    (42 cycles) split cleanly: every boundary that was already the cycle's
    own trough sat at a 0.0% rise, while every disputed one sat at a 10.4%
    to 56.8% rise, with nothing in between. A proportional margin separates
    those two populations at any threshold in that gap; an absolute one
    cannot separate them at all.

    The fixtures below are the real reviewed observations, so a change in
    behaviour here is a change against the record the calibration was
    bracketed on.
    """

    def test_a_real_recovery_below_the_old_absolute_margin_is_not_tied(self):
        # Fitzroy HY2008 (Jun 2008 - Feb 2009). November is the trough at
        # 0.0249; December is 0.0391 -- a +57% recovery, but only +0.014 in
        # absolute terms, so the retired delta_pp=0.02 absolute margin
        # counted it as tied and published December.
        values = [0.100487, 0.056447, 0.039419, 0.037144, 0.028395,
                  0.024948, 0.039120, 0.199723, 1.167529]
        frame = _prepared(values, start="2008-06-01")
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2008-11-01")

    def test_a_genuinely_flat_plateau_still_reports_its_last_month(self):
        # Gilbert HY2006 (Jun 2006 - Jan 2007). October/November/December
        # are 0.1177/0.1181/0.1229 -- +0.3% and +4.4%, genuinely tied. The
        # representative-date convention is unchanged, so the boundary is
        # the LAST month of the tie, not the deepest: the low state really
        # did persist through December.
        #
        # This pins the core's answer for the span in isolation. The full
        # pipeline abstains on this cycle (unstable_quality_sensitivity)
        # and publishes pass 1's October instead, which is the sensitivity
        # ensemble doing its job -- not a contradiction of this assertion.
        values = [0.242215, 0.220948, 0.172179, 0.150800,
                  0.117680, 0.118082, 0.122906, 0.965496]
        frame = _prepared(values, start="2006-06-01")
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2006-12-01")

    def test_the_same_relative_recovery_is_judged_alike_at_any_level(self):
        # The property an absolute margin cannot have: rescaling the whole
        # span leaves every verdict unchanged.
        shape = [4.0, 2.0, 1.2, 1.0, 1.4, 3.0, 6.0]
        boundaries = []
        for factor in (0.01, 1.0, 10.0):
            frame = _prepared([value * factor for value in shape])
            left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
            right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
            result = refine_selected_span_direct_profile(
                frame, left_peak=left, right_peak=right,
                policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
            )
            boundaries.append(result.boundary)
        assert boundaries[0] == boundaries[1] == boundaries[2]


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
    AND value-plausible (within the equivalence margin of the segment's own natural
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
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
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
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2020-06-01")
        assert result.reason == "recovery_crosses_gap"


class TestReferenceLevelIgnoresUnreliableMonths:
    """The low-state reference level `L` must be anchored on observations the
    pipeline is willing to trust.

    `_natural_reference_level` searches every candidate valley block for the
    best-fitting one and takes its level. Nothing stopped that block from
    being a single cloud-corrupted month: Daly River HY2005's January 2006
    reads 0.0168 at 61% invalid -- roughly a seventh of the true trough --
    and won the search outright, making 0.0168 the "low state". Every real
    month then sat far above the equivalence ceiling, so the genuine trough
    months never entered the support set at all and the cycle abstained.

    An unreliable month may still be *scored* against the reference level;
    it may not *define* it.
    """

    def _daly_2005_span(self) -> pd.DataFrame:
        # Real observations, Jan 2005 -> Apr 2006 (the peak-to-peak span
        # pass 2 actually receives for this cycle).
        values = [
            0.714490, 0.292494, 0.160265, 0.163330, 0.162717, 0.161318,
            0.147574, 0.131862, 0.118780, 0.119377, 0.121806, 0.174568,
            0.016762, 0.196351, 0.122782, 0.938340,
        ]
        invalid = [
            2.314325, 3.199080, 3.570241, 1.931157, 1.933613, 2.034552,
            1.927186, 1.926179, 2.063143, 2.333707, 3.020064, 41.032835,
            60.986964, 2.329369, 47.257731, 3.297283,
        ]
        return _prepared_with_quality(values, invalid, start="2005-01-01")

    def test_a_cloud_artifact_cannot_become_the_low_state_level(self):
        frame = self._daly_2005_span()
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        # September/October/November 2005 are within 5% of each other; the
        # latest of that genuine tie is November.
        assert result.boundary == pd.Timestamp("2005-11-01")

    def test_reliable_months_still_define_the_level_when_all_are_reliable(self):
        # Regression: with nothing cloud-flagged, the reference level is
        # chosen exactly as before.
        values = [40.0, 20.0, 12.0, 12.1, 12.3, 20.0, 40.0]
        frame = _prepared_with_quality(values, [0.0] * len(values))
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2020-05-01")


class TestUnevaluableScenariosDoNotVetoTheEnsemble:
    """A perturbation scenario that cannot be evaluated is absence of
    evidence, not evidence of instability.

    The quality-sensitivity ensemble masks each cloud-flagged month in turn.
    When the masked month sits against a span edge, the pre-gap path has no
    segment left to fit and the scenario is structurally undefined -- it
    reports nothing about where the boundary is. Treating that as a
    dissenting vote let one cloudy month far from the trough veto the whole
    refinement: Gilbert River HY2006's March 2006 (25.0% invalid, eight
    months before the trough) collapsed 2 of 7 scenarios and discarded a
    5-of-7 agreement on December.
    """

    def _gilbert_2006_span(self) -> pd.DataFrame:
        # Real observations, Feb 2006 -> Feb 2007 (peak to peak).
        values = [
            0.782102, 0.692048, 0.638315, 0.300520, 0.242215, 0.220948,
            0.172179, 0.150800, 0.117680, 0.118082, 0.122906, 0.965496,
            3.579843,
        ]
        invalid = [
            3.247203, 25.008651, 5.648274, 3.031665, 3.052006, 3.065546,
            3.764685, 3.039235, 3.041889, 3.036981, 3.039043, 10.592743,
            42.755754,
        ]
        return _prepared_with_quality(values, invalid, start="2006-02-01")

    def test_an_edge_masked_scenario_does_not_discard_an_agreed_boundary(self):
        frame = self._gilbert_2006_span()
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_trough_span(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        # Oct/Nov/Dec 2006 are 0.1177/0.1181/0.1229 -- +0.3% and +4.4%, a
        # genuine tie, so the boundary is the last month of it.
        assert result.boundary == pd.Timestamp("2006-12-01")

    def test_a_scenario_that_abstains_on_its_merits_still_vetoes(self):
        # The filter must stay narrow. A scenario that WAS evaluable and
        # concluded it could not stand behind any boundary is a real
        # dissent, and must still make the ensemble unstable.
        frame = _prepared([40.0, 20.0, 12.0, 12.1, 12.3, 20.0, 40.0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        nominal = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        from dataclasses import replace as _replace

        from hydroseason._trough_refinement import _combine_sensitivity_results

        dissenting = _replace(
            nominal,
            status="unresolved",
            reason="no_reliable_boundary_in_support",
            boundary=None,
        )
        combined = _combine_sensitivity_results(
            nominal, [nominal, dissenting], unstable_reason="unstable_quality_sensitivity",
        )
        assert combined.status == "unresolved"
        assert combined.reason == "unstable_quality_sensitivity"


class TestRecoveryWithinNoiseIsNotConfirmed:
    """Do not publish `confirmed` for a boundary the record cannot resolve.

    The equivalence margin is a hydrological statement (within `delta_rel`
    of the low-state level). The record's own noise scale is a separate,
    measurement statement. When the month after the boundary is outside the
    equivalence margin but still inside the noise scale, the claim "the low
    state ended here, not there" is finer than the observation can support.
    The boundary does not move -- the margin still decides that -- but the
    result is reported as provisional rather than confirmed.
    """

    def test_a_recovery_inside_the_noise_scale_downgrades_to_provisional(self):
        # L = 12.0, equivalence margin = 5% = 0.60 (ceiling 12.60), while the
        # record's own scale is 4.12 (ceiling 16.12). The step to 13.2 is
        # +10%: outside the margin, so the boundary stays at the trough --
        # but well inside the noise, so this is not a confirmed call.
        frame = _prepared([40.0, 20.0, 12.0, 12.0, 13.2, 30.0, 40.0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2020-04-01")
        assert result.status == "provisional"
        assert result.reason == "recovery_within_noise"

    def test_a_recovery_well_clear_of_the_noise_stays_confirmed(self):
        frame = _prepared([40.0, 20.0, 12.0, 12.0, 30.0, 35.0, 40.0])
        left = PeakBoundary(frame.index[0], (frame.index[0],), "point", "normal")
        right = PeakBoundary(frame.index[-1], (frame.index[-1],), "point", "normal")
        result = refine_selected_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=_direct_profile_policy(), measurement_tolerance_pp=0.0,
        )
        assert result.boundary == pd.Timestamp("2020-04-01")
        assert result.status == "confirmed"
        assert result.reason == "accepted"
