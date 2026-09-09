import warnings

import numpy as np
import pandas as pd
import pytest

from hydroseason import _dynamic_year as dynamic_year
from hydroseason._dynamic_year import (
    _DIAGNOSTIC_AUDIT_RADIUS_MONTHS,
    ANNUAL_COLUMNS,
    DynamicHydroYearConfig,
    _find_robust_trough_opportunities,
    detect_dynamic_hydrological_years,
    suggest_dynamic_hydro_year_config,
)
from hydroseason._seasonality import classify_seasonal_pattern
from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import (
    TroughRefinementPolicy,
    TroughRefinementResult,
)

_EVIDENCE_KWARGS = {
    "resolution_floor_pp": 0.5,
    "mode_min_frequency": 0.60,
    "mode_min_separation_months": 2,
    "n_null": 99,
}


def _monsoonal(years=12):
    index = pd.date_range("2000-01-01", periods=years * 12, freq="MS")
    values = 30.0 + 25.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_suggestion_uses_advisory_phase_and_user_overrides_win():
    extent = _monsoonal()
    pattern = classify_seasonal_pattern(extent, n_bootstrap=40, **_EVIDENCE_KWARGS)
    config = suggest_dynamic_hydro_year_config(extent, pattern=pattern, trough_search_radius_months=2)
    assert config.expected_trough_month == pattern.expected_trough_month
    assert config.expected_peak_month == pattern.expected_peak_month
    assert config.trough_search_radius_months == 2


def test_dynamic_config_keeps_historical_detection_defaults():
    config = DynamicHydroYearConfig(expected_trough_month=10)
    assert config.trough_search_radius_months == 3
    assert config.min_usable_months_per_cycle == 8


def test_unstable_pattern_requires_explicit_trough():
    extent = _monsoonal(years=4)
    pattern = classify_seasonal_pattern(extent, n_bootstrap=40, **_EVIDENCE_KWARGS)
    with pytest.raises(ValueError, match="expected_trough_month"):
        suggest_dynamic_hydro_year_config(extent, pattern=pattern)


def test_dynamic_config_rejects_invalid_recovery_geometry():
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=13)
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=9, pulse_rejection_window_months=0)


def _candidate_frame(start="2018-01-01", periods=60):
    index = pd.date_range(start, periods=periods, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_default_detection_does_not_apply_unvalidated_trough_refinement():
    """Removing candidate authority must leave the established pass-1 boundary."""
    raw = _candidate_frame()
    raw.loc["2020-06-01":"2020-12-01", "extent_pct"] = [
        30.0,
        20.0,
        10.0,
        1.0,
        1.0,
        1.0,
        15.0,
    ]

    result = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(expected_trough_month=9),
    )

    row = result.loc[result["hy_year"] == 2020].iloc[0]
    assert row["raw_trough_month"] == pd.Timestamp("2020-09-01")
    assert row["trough_month"] == pd.Timestamp("2020-09-01")
    assert row["pass1_trough_month"] == row["trough_month"]
    assert row["trough_refinement_status"] == "unavailable"
    assert row["trough_refinement_reason"] == "not_requested"
    assert not bool(row["trough_refinement_applied"])


def test_opted_in_trough_refinement_applies_boundary_without_changing_peaks():
    raw = _candidate_frame()
    raw.loc["2020-06-01":"2020-12-01", "extent_pct"] = [
        30.0,
        20.0,
        10.0,
        1.0,
        1.0,
        1.0,
        15.0,
    ]
    baseline = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(expected_trough_month=9),
    )
    refined = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(
            expected_trough_month=9,
            trough_refinement_policy=TroughRefinementPolicy(
                huber_k=1.345,
                profile_loss_cutoff=0.05,
                pulse_z=2.0,
            ),
        ),
    )

    baseline_peaks = tuple(baseline["peak_month"])
    refined_peaks = tuple(refined["peak_month"])
    assert refined_peaks == baseline_peaks

    row = refined.loc[refined["hy_year"] == 2020].iloc[0]
    following = refined.loc[refined["hy_year"] == 2021].iloc[0]
    assert row["pass1_trough_month"] == pd.Timestamp("2020-09-01")
    assert row["trough_challenger_month"] == pd.Timestamp("2020-11-01")
    assert row["trough_month"] == pd.Timestamp("2020-11-01")
    assert row["trough_interval_start"] == pd.Timestamp("2020-09-01")
    assert row["trough_interval_end"] == pd.Timestamp("2020-11-01")
    assert row["trough_refinement_status"] == "confirmed"
    assert bool(row["trough_refinement_applied"])
    assert following["hy_start"] == pd.Timestamp("2020-12-01")


def test_direct_profile_combined_candidate_applies_boundary_without_changing_peaks():
    """The opt-in direct_profile_combined candidate must plug into the same
    pass-1/pass-2 wiring as shape_fit: unchanged peaks, atomic acceptance,
    generic trough_refinement_* export columns populated the same way."""
    raw = _candidate_frame()
    raw.loc["2020-06-01":"2020-12-01", "extent_pct"] = [
        30.0, 20.0, 10.0, 1.0, 1.0, 1.0, 15.0,
    ]
    baseline = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9),
    )
    refined = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(
            expected_trough_month=9,
            trough_refinement_policy=TroughRefinementPolicy(
                huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=2.0,
                version="direct_profile_combined_v1",
                candidate="direct_profile_combined", delta_pp=0.5,
            ),
        ),
    )

    assert tuple(refined["peak_month"]) == tuple(baseline["peak_month"])
    row = refined.loc[refined["hy_year"] == 2020].iloc[0]
    assert row["pass1_trough_month"] == pd.Timestamp("2020-09-01")
    assert row["trough_refinement_policy_version"] == "direct_profile_combined_v1"
    assert row["trough_refinement_status"] in {"confirmed", "provisional"}
    assert bool(row["trough_refinement_applied"])


def test_open_peak_span_retains_pass1_as_provisional_fallback():
    raw = _candidate_frame()
    result = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(
            expected_trough_month=9,
            trough_refinement_policy=TroughRefinementPolicy(
                huber_k=1.345,
                profile_loss_cutoff=0.05,
                pulse_z=2.0,
            ),
        ),
    )

    row = result.iloc[-1]
    assert row["trough_refinement_status"] == "awaiting_next_peak"
    assert row["trough_refinement_reason"] == "open_span"
    assert not bool(row["trough_refinement_applied"])
    assert row["trough_month"] == row["pass1_trough_month"]
    assert row["boundary_status"] == "provisional"


def test_trough_refinement_rolls_back_both_cycles_when_coverage_would_fail(
    monkeypatch,
):
    raw = _candidate_frame()
    baseline = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(expected_trough_month=9),
    )

    def challenge(_frame, *, left_peak, right_peak, policy, measurement_tolerance_pp=0.0):
        if left_peak.selected == pd.Timestamp("2019-02-01"):
            boundary = pd.Timestamp("2020-01-01")
            return TroughRefinementResult(
                status="confirmed",
                reason="accepted",
                boundary=boundary,
                boundary_candidates=(boundary,),
                low_state_start=boundary,
                low_state_end=boundary,
                recovery_start=pd.Timestamp("2020-02-01"),
                pulse_months=(),
                local_scale_pp=0.2,
                best_loss=0.1,
                effective_support=12.0,
                policy_version=policy.version,
            )
        status = "awaiting_next_peak" if right_peak is None else "unavailable"
        reason = "open_span" if right_peak is None else "missing_or_unresolved_peak"
        return TroughRefinementResult(
            status=status,
            reason=reason,
            boundary=None,
            boundary_candidates=(),
            low_state_start=None,
            low_state_end=None,
            recovery_start=None,
            pulse_months=(),
            local_scale_pp=np.nan,
            best_loss=np.nan,
            effective_support=0.0,
            policy_version=policy.version,
        )

    monkeypatch.setattr(dynamic_year, "refine_trough_span", challenge)
    refined = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(
            expected_trough_month=9,
            trough_refinement_policy=TroughRefinementPolicy(1.345, 0.05, 2.0),
        ),
    )

    for year in (2019, 2020):
        before = baseline.loc[baseline["hy_year"] == year].iloc[0]
        after = refined.loc[refined["hy_year"] == year].iloc[0]
        assert after["trough_month"] == before["trough_month"]
        assert after["hy_start"] == before["hy_start"]
        assert after["hy_end"] == before["hy_end"]
        assert after["peak_month"] == before["peak_month"]
    challenged = refined.loc[refined["hy_year"] == 2019].iloc[0]
    assert challenged["trough_refinement_reason"] == "atomic_rollback_cycle"
    assert not bool(challenged["trough_refinement_applied"])


def _post_trough_peak_frame(start="2017-01-01", periods=84):
    """Monotonic decline from an October peak to the following September trough.

    The annual maximum therefore falls in October -- the month immediately after
    the previous September trough (i.e. the very first month of the cycle). This
    exposes an off-by-one that over-excludes the first cycle month from peak
    candidacy and would otherwise report the second-highest month instead.
    """
    index = pd.date_range(start, periods=periods, freq="MS")
    by_month = {10: 60.0, 11: 52.0, 12: 44.0, 1: 38.0, 2: 32.0, 3: 27.0,
                4: 22.0, 5: 18.0, 6: 13.0, 7: 9.0, 8: 5.0, 9: 2.0}
    values = [by_month[month] for month in index.month]
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_mid_dry_rise_does_not_replace_later_lower_trough():
    raw = _candidate_frame()
    raw.loc["2020-07-01":"2021-02-01", "extent_pct"] = [5, 8, 9, 4, 8, 12, 20, 25]
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    row = result.loc[result["hy_year"] == 2020].iloc[0]
    assert row["raw_trough_month"] == pd.Timestamp("2020-10-01")
    assert row["trough_month"] == pd.Timestamp("2020-10-01")


def test_final_incomplete_search_window_is_provisional():
    raw = _candidate_frame(periods=34)
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    row = result.loc[result["hy_year"] == 2020].iloc[0]
    assert row["window_status"] == "right_truncated"
    assert row["boundary_status"] == "provisional"


def test_materially_higher_month_outside_equivalent_run_is_never_selected():
    # Raw minimum sits at Oct (2 pp); Sep (15 pp) is materially higher and inside
    # the same search window. The equivalent low run is Oct alone, so neither the
    # sequence optimizer (which would otherwise prefer the expected Sep phase) nor
    # any tolerance band may promote the higher Sep value over the raw minimum.
    raw = _candidate_frame()
    raw.loc["2020-06-01":"2020-12-01", "extent_pct"] = [30, 25, 20, 15, 2, 18, 22]
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    row = result.loc[result["hy_year"] == 2020].iloc[0]
    assert row["raw_trough_month"] == pd.Timestamp("2020-10-01")
    assert row["trough_month"] == pd.Timestamp("2020-10-01")
    assert row["low_run_start_month"] == pd.Timestamp("2020-10-01")
    assert row["low_run_end_month"] == pd.Timestamp("2020-10-01")


def test_insufficient_candidate_coverage_is_an_explicit_row():
    raw = _candidate_frame()
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    rows = _find_robust_trough_opportunities(prepare_monthly_extent(raw), DynamicHydroYearConfig(expected_trough_month=9))
    row = rows.loc[rows["hy_year"] == 2020].iloc[0]
    assert row["status"] == "unresolved"
    assert row["status_reason"] == "insufficient_trough_candidates"


def test_dynamic_cycle_reports_observed_peak_two_mid_dry_metrics_and_trough():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    config = DynamicHydroYearConfig(expected_trough_month=8, dry_plateau_rule="middle")
    result = detect_dynamic_hydrological_years(raw, config=config)
    complete = result.loc[result["status"] == "complete"].iloc[0]
    assert complete["peak_extent_pct"] == raw.loc[complete["peak_month"], "extent_pct"]
    assert complete["trough_extent_pct"] == raw.loc[complete["trough_month"], "extent_pct"]
    assert complete["half_loss_target_pct"] == pytest.approx((complete["peak_extent_pct"] + complete["trough_extent_pct"]) / 2)
    assert complete["peak_month"] <= complete["temporal_mid_dry_month"] <= complete["trough_month"]
    assert complete["peak_month"] <= complete["half_loss_month"] <= complete["trough_month"]


def test_short_six_month_cycle_keeps_observed_peak_and_local_trough():
    dates = pd.date_range("2019-01-01", "2021-12-01", freq="MS")
    values = (
        [8.0, 18.0, 14.0, 12.0, 10.0, 8.0, 7.0, 6.0, 5.0, 4.8, 4.5, 4.0]
        + [6.9, 9.8, 6.5, 5.7, 4.7, 3.8, 4.0, 5.3, 5.4, 5.5, 5.4, 5.2]
        + [7.0, 15.0, 12.0, 9.0, 7.0, 6.0, 5.5, 5.0, 4.5, 4.0, 4.5, 6.0]
    )
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)

    result = detect_dynamic_hydrological_years(
        raw,
        config=DynamicHydroYearConfig(expected_trough_month=10),
    )

    short = result.loc[result["hy_year"] == 2020].iloc[0]
    assert short["trough_month"] == pd.Timestamp("2020-06-01")
    assert short["peak_month"] == pd.Timestamp("2020-02-01")
    assert short["cycle_months"] == 6


def test_adaptive_pass_relaxes_only_unresolved_interior_year():
    dates = pd.date_range("2019-01-01", "2021-12-01", freq="MS")
    values = (
        [8.0, 18.0, 14.0, 12.0, 10.0, 8.0, 7.0, 6.0, 5.0, 4.8, 4.5, 4.0]
        + [6.9, 9.8, 6.5, 5.7, 4.7, 3.8, 4.0, 5.3, 5.4, 5.5, 5.4, 5.2]
        + [7.0, 15.0, 12.0, 9.0, 7.0, 6.0, 5.5, 5.0, 4.5, 4.0, 4.5, 6.0]
    )
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)

    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=10)
    )

    middle = result.loc[result["hy_year"] == 2020].iloc[0]
    assert middle["trough_month"] == pd.Timestamp("2020-06-01")
    assert middle["peak_month"] == pd.Timestamp("2020-02-01")
    assert middle["cycle_months"] == 6
    assert result.loc[result["hy_year"] == 2019, "trough_month"].item() == pd.Timestamp("2019-12-01")
    assert result.loc[result["hy_year"] == 2021, "trough_month"].item() == pd.Timestamp("2021-10-01")


def test_adaptive_edge_retry_finds_earlier_observed_trough():
    dates = pd.date_range("2015-01-01", "2017-12-01", freq="MS")
    values = (
        [10.0, 20.0, 16.0, 12.0, 9.0, 7.0, 6.0, 5.0, 4.0, 3.0, 4.0, 6.0]
        + [10.0, 20.0, 16.0, 12.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        + [10.0, 20.0, 16.0, 12.0, 9.0, 7.0, 6.0, 5.0, 4.0, 3.0, 4.0, 6.0]
    )
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)

    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=10)
    )

    assert result.loc[result["hy_year"] == 2015, "trough_month"].item() == pd.Timestamp("2015-10-01")
    assert result.loc[result["hy_year"] == 2016, "trough_month"].item() == pd.Timestamp("2016-05-01")
    assert result.loc[result["hy_year"] == 2017, "trough_month"].item() == pd.Timestamp("2017-10-01")


def test_unresolved_nominal_year_breaks_cycles_instead_of_merging():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle")
    result = detect_dynamic_hydrological_years(raw, config=config)
    assert result.loc[result["hy_year"] == 2020, "status"].item() == "unresolved"
    assert result.loc[result["hy_year"] == 2021, "status_reason"].item() == "no_previous_boundary"
    resolved_lengths = result.loc[result["status"] == "complete", "cycle_months"]
    assert (resolved_lengths <= 18).all()


def test_first_opportunity_uses_record_start_as_opening_boundary():
    """The record's own first observed month anchors the opening cycle.

    The very first hydrological-year opportunity has no preceding trough,
    but when enough real data precedes its trough there is a genuine
    partial cycle to report. Before this fix that row was a blank stub
    (status_reason="no_previous_boundary", no hy_start/hy_end/peak at
    all), which rendered as an unbounded "no data" card and left the
    start of the timeline unshaded.
    """
    index = pd.date_range("2005-01-01", periods=36, freq="MS")
    # Descending Jan..Oct 2005 -- the record opens mid-cycle, so its peak
    # is its first month -- then two clean cycles troughing in October.
    # The +30/-20 offset keeps every later month above the opening trough
    # of 8.0, so Oct 2005 stays the first resolved trough.
    opening = [90.0, 78.0, 66.0, 54.0, 42.0, 30.0, 22.0, 16.0, 11.0, 8.0]
    following = list(
        30.0 + 20.0 * np.cos(2 * np.pi * (index[10:].month - 4) / 12)
    )
    raw = pd.DataFrame(
        {"extent_pct": opening + following, "invalid_pct": 0.0}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=10)

    result = detect_dynamic_hydrological_years(raw, config=config)

    first_row = result.iloc[0]
    assert first_row["status_reason"] == "record_start_boundary"
    assert first_row["hy_start"] == pd.Timestamp("2005-01-01")
    assert first_row["hy_end"] == pd.Timestamp("2005-10-01")
    # The record's own first month must be peak-eligible: select_cycle_peak
    # is given the synthetic pre-record trough, not hy_start, precisely so
    # that January is not excluded as a boundary month.
    assert first_row["peak_month"] == pd.Timestamp("2005-01-01")
    assert pd.notna(first_row["drawdown_pct"])
    assert first_row["boundary_status"] == "provisional"


def test_first_opportunity_too_short_still_falls_back_to_insufficient_coverage():
    """A record starting only 3 months before its first trough has no
    cycle to report, even with the record-start boundary. It must fail
    the same min_usable_months_per_cycle check as any other cycle rather
    than being waved through on a synthetic boundary.
    """
    index = pd.date_range("2005-08-01", periods=24, freq="MS")
    opening = [30.0, 20.0, 10.0]  # Aug, Sep, Oct 2005 -- 3 months only
    following = list(
        20.0 + 15.0 * np.cos(2 * np.pi * (index[3:].month - 12) / 12)
    )
    raw = pd.DataFrame(
        {"extent_pct": opening + following, "invalid_pct": 0.0}, index=index
    )
    config = DynamicHydroYearConfig(
        expected_trough_month=10, min_usable_months_per_cycle=8
    )

    result = detect_dynamic_hydrological_years(raw, config=config)

    first_row = result.iloc[0]
    assert first_row["status_reason"] == "insufficient_cycle_coverage"
    assert first_row["hy_start"] == pd.Timestamp("2005-08-01")
    assert pd.isna(first_row["peak_month"])


def test_mid_record_reset_after_gap_still_reports_no_previous_boundary():
    """Only the record's first opportunity may synthesize a boundary.

    A year that resets the chain mid-record (because an earlier year's
    trough was unresolvable) must keep reporting no_previous_boundary --
    synthesizing a start there would invent cycle data spanning a real
    data gap.
    """
    raw = _candidate_frame(start="2017-01-01", periods=84)
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle")

    result = detect_dynamic_hydrological_years(raw, config=config)

    assert result.loc[result["hy_year"] == 2020, "status"].item() == "unresolved"
    assert result.loc[result["hy_year"] == 2021, "status_reason"].item() == "no_previous_boundary"
    assert pd.isna(result.loc[result["hy_year"] == 2021, "hy_start"].item())


def test_temporary_rewetting_after_half_loss_is_counted():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    raw.loc["2020-06-01":"2020-09-01", "extent_pct"] = [8.0, 14.0, 7.0, 4.0]
    result = detect_dynamic_hydrological_years(raw, config=DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle"))
    assert result.loc[result["hy_year"] == 2020, "n_rewetting_pulses"].item() >= 1


def test_zero_peak_has_explicit_nan_persistence_ratio():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    raw["extent_pct"] = 0.0
    result = detect_dynamic_hydrological_years(raw, config=DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle"))
    assert result.loc[result["status"] == "complete", "persistence_ratio"].isna().all()


def test_unknown_quality_never_receives_high_confidence():
    raw = _candidate_frame(start="2017-01-01", periods=72).drop(columns="invalid_pct")
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle", allow_unknown_quality=True)
    result = detect_dynamic_hydrological_years(raw, config=config)
    assert "high" not in set(result["confidence"])


def test_old_recovery_fields_warn_for_one_release():
    with pytest.warns(DeprecationWarning, match="recovery-window"):
        DynamicHydroYearConfig(expected_trough_month=9, sustained_rise_months=2)


def test_old_recovery_field_pulse_rejection_window_also_warns():
    with pytest.warns(DeprecationWarning, match="recovery-window"):
        DynamicHydroYearConfig(expected_trough_month=9, pulse_rejection_window_months=4)


def test_old_dry_plateau_rule_literal_warns():
    with pytest.warns(DeprecationWarning, match="raw_minimum"):
        DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="last_before_confirmed_recovery")


def test_new_default_dry_plateau_rule_is_raw_minimum_and_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        config = DynamicHydroYearConfig(expected_trough_month=9)
    assert config.dry_plateau_rule == "raw_minimum"


def test_new_config_without_recovery_overrides_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        config = DynamicHydroYearConfig(expected_trough_month=9)
    assert config.sustained_rise_months is None
    assert config.pulse_rejection_window_months is None


def test_detector_field_defaults_to_robust_extrema():
    config = DynamicHydroYearConfig(expected_trough_month=9)
    assert config.detector == "robust_extrema"


def test_detector_field_rejects_unknown_value():
    with pytest.raises(ValueError, match="detector"):
        DynamicHydroYearConfig(expected_trough_month=9, detector="not_a_real_detector")


def test_phase_model_does_not_change_annual_hydrological_years():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    without_phases = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, phase_model="none")
    )
    with_rule_based_axis = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, phase_model="rule_based")
    )
    pd.testing.assert_frame_equal(with_rule_based_axis, without_phases)


def test_explicit_zero_pulse_rejection_window_still_rejected():
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=9, pulse_rejection_window_months=0)


def test_raw_peak_reports_maximum_in_first_month_after_previous_trough():
    # cycle 2019 spans Oct-2018 .. Sep-2019; the true observed maximum is the
    # first month, Oct-2018 (60 pp), which must be reported as the raw peak --
    # not the second-highest month (Nov-2018, 52 pp) that an off-by-one exclusion
    # of the first cycle month would leave behind.
    raw = _post_trough_peak_frame()
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    row = result.loc[result["hy_year"] == 2019].iloc[0]
    assert row["raw_peak_month"] == pd.Timestamp("2018-10-01")
    assert row["raw_peak_extent_pct"] == pytest.approx(60.0)
    assert row["peak_month"] == pd.Timestamp("2018-10-01")
    assert row["peak_extent_pct"] == pytest.approx(60.0)


def test_peak_diagnostic_columns_populated_for_resolved_cycle():
    raw = _post_trough_peak_frame()
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    complete = result.loc[result["status"] == "complete"].iloc[0]
    assert pd.notna(complete["raw_peak_month"])
    assert complete["raw_peak_month"] == complete["peak_month"]
    assert complete["raw_peak_extent_pct"] == pytest.approx(complete["peak_extent_pct"])
    assert complete["peak_selection_status"] in {"raw", "ambiguous", "quality_adjusted", "low_quality"}
    assert pd.notna(complete["peak_selection_support"])
    assert 0.0 <= complete["peak_selection_support"] <= 1.0


def test_observed_high_invalid_peak_is_reported_but_cycle_is_provisional():
    raw = _post_trough_peak_frame()
    raw.loc["2018-10-01", "invalid_pct"] = 60.0
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, max_invalid_pct=20.0)
    )
    row = result.loc[result["hy_year"] == 2019].iloc[0]
    assert row["peak_month"] == pd.Timestamp("2018-10-01")
    assert row["peak_invalid_pct"] == pytest.approx(60.0)
    assert row["peak_selection_status"] == "low_quality"
    assert row["boundary_status"] == "provisional"
    assert row["status"] == "partial"
    assert row["confidence"] != "high"


def test_additive_diagnostic_columns_are_present_and_populated():
    from hydroseason._dynamic_year import ANNUAL_COLUMNS

    raw = _candidate_frame(start="2017-01-01", periods=84)
    additive_columns = [
        "raw_trough_month", "raw_trough_extent_pct",
        "low_run_start_month", "low_run_end_month",
        "window_status", "selection_status", "selection_support",
        "window_n_expected", "window_n_usable", "phase_shift_months",
        "raw_peak_month", "raw_peak_extent_pct",
        "peak_selection_status", "peak_selection_support",
    ]
    for column in additive_columns:
        assert column in ANNUAL_COLUMNS

    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    complete = result.loc[result["status"] == "complete"]
    assert not complete.empty
    row = complete.iloc[0]
    for column in additive_columns:
        assert pd.notna(row[column]), f"{column} is NaN"
    assert row["window_status"] in {"full", "left_truncated", "right_truncated", "internal_gap"}
    assert row["selection_status"] in {
        "raw", "ambiguous", "quality_adjusted", "low_quality",
        "coherence_adjusted", "unresolved",
    }
    assert 0.0 <= row["selection_support"] <= 1.0
    assert row["boundary_status"] in {"confirmed", "provisional"}


def test_peak_diagnostic_columns_are_nan_for_unresolved_cycles():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle")
    result = detect_dynamic_hydrological_years(raw, config=config)
    # The unresolved boundary must not be widened across a fully invalid gap;
    # neither affected row reaches peak selection.
    for year in (2020, 2021):
        row = result.loc[result["hy_year"] == year].iloc[0]
        assert pd.isna(row["raw_peak_month"])
        assert pd.isna(row["raw_peak_extent_pct"])
        assert pd.isna(row["peak_selection_status"])
        assert pd.isna(row["peak_selection_support"])


def test_record_start_boundary_cycle_is_never_high_confidence():
    """A cycle opened at the record's edge is an assumption, not a
    detection, and must never be scored "high". Task 1 forces
    boundary_status="provisional" for these, which caps _confidence's
    score at 0.75 -- below the 0.80 "high" threshold.
    """
    index = pd.date_range("2005-01-01", periods=36, freq="MS")
    opening = [90.0, 78.0, 66.0, 54.0, 42.0, 30.0, 22.0, 16.0, 11.0, 8.0]
    following = list(
        30.0 + 20.0 * np.cos(2 * np.pi * (index[10:].month - 4) / 12)
    )
    raw = pd.DataFrame(
        {"extent_pct": opening + following, "invalid_pct": 0.0}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=10)

    result = detect_dynamic_hydrological_years(raw, config=config)

    first_row = result.iloc[0]
    assert first_row["status_reason"] == "record_start_boundary"
    assert first_row["confidence"] in {"medium", "low"}


def test_secondary_extrema_survives_extrema_filtered_out_of_the_usable_series():
    """The primary peak/trough need not be present in the usable-months series.

    ``_assemble_dynamic_years`` builds ``usable`` by filtering the cycle down
    to ``candidate_usable`` months, but selects ``peak`` from the unfiltered
    cycle (it may legitimately be a ``low_quality`` month -- the caller even
    records ``peak_quality`` for exactly that case) and takes ``trough``
    as the cycle's end month. Neither is guaranteed to survive the usability
    filter, so looking them up with an exact ``Index.get_loc`` raises
    ``KeyError`` and takes down the whole analysis.

    Reachable only for ``pattern == "bimodal_or_complex"`` catchments, which
    is why no existing fixture covers it; observed on a real DEA WOfS fetch
    of the Fitzroy/Kimberley AOI (``KeyError: Timestamp('2017-02-01')``).

    The exclusion rule -- "a secondary extremum must sit at least 2 months
    away from the primary one" -- still has a well-defined meaning when the
    primary month is absent: measure from where it would fall in the series.
    """
    from hydroseason._dynamic_year import _secondary_extrema

    index = pd.date_range("2020-01-01", periods=12, freq="MS")
    series = pd.Series(
        [5.0, 40.0, 8.0, 6.0, 30.0, 7.0, 5.0, 4.0, 25.0, 6.0, 5.0, 4.0],
        index=index,
    )
    absent_peak = pd.Timestamp("2020-02-01")
    absent_trough = pd.Timestamp("2020-12-01")
    without_extrema = series.drop([absent_peak, absent_trough])

    peak_month, peak_value, trough_month, trough_value = _secondary_extrema(
        without_extrema, absent_peak, absent_trough
    )

    assert peak_month is None or peak_month in without_extrema.index
    assert trough_month is None or trough_month in without_extrema.index
    assert peak_value != peak_value or isinstance(peak_value, float)
    assert trough_value != trough_value or isinstance(trough_value, float)


def test_selection_quality_mirrors_selection_support():
    frame = _candidate_frame()
    result = detect_dynamic_hydrological_years(
        frame, config=DynamicHydroYearConfig(expected_trough_month=7)
    )

    assert "selection_quality" in result.columns
    assert (result["selection_quality"] == result["selection_support"]).all()


def test_existing_columns_keep_their_order():
    frame = _candidate_frame()
    result = detect_dynamic_hydrological_years(
        frame, config=DynamicHydroYearConfig(expected_trough_month=7)
    )
    existing = ["hy_year", "status", "status_reason"]

    assert list(result.columns)[: len(existing)] == existing



def test_flat_cycle_reports_unresolved_timing_but_selection_support_stands():
    # A flat cycle can still have good data/window coverage (selection_support)
    # while contributing no timing observation -- the two must be independent.
    dates = pd.date_range("2018-01-01", "2021-12-01", freq="MS")
    values = (
        [8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.5, 2.0, 1.8, 1.5, 1.2, 1.0]
        + [1.0] * 12
        + [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0, 16.0, 14.0, 10.0, 6.0, 3.0]
        + [2.0, 1.8, 1.5, 1.2, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
    )
    raw = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=12, measurement_tolerance_pct=0.5)
    )
    flat = result.loc[result["hy_year"] == 2019].iloc[0]
    assert flat["timing_status"] == "unresolved"
    assert flat["boundary_status"] == "provisional"
    assert flat["status"] == "partial"
    assert flat["confidence"] == "low"
    assert flat["selection_support"] >= 0.8


def test_detectable_cycle_reports_point_or_interval_timing_status():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    complete = result.loc[result["status"] == "complete"]
    assert not complete.empty
    row = complete.iloc[0]
    assert row["timing_status"] in {"point", "interval"}
    assert row["peak_timing_status"] in {"point", "interval"}
    assert row["trough_timing_status"] in {"point", "interval"}
    assert pd.notna(row["detectability_floor_pp"])
    assert pd.notna(row["amplitude_to_floor_ratio"])


def test_timing_status_columns_present_for_every_row():
    from hydroseason._dynamic_year import ANNUAL_COLUMNS

    timing_columns = [
        "detectability_floor_pp", "amplitude_to_floor_ratio", "peak_n_water",
        "peak_timing_status", "peak_interval_start", "peak_interval_end",
        "trough_timing_status", "trough_interval_start", "trough_interval_end",
        "timing_status",
    ]
    for column in timing_columns:
        assert column in ANNUAL_COLUMNS

    raw = _candidate_frame(start="2017-01-01", periods=72)
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    for column in timing_columns:
        assert column in result.columns


def test_aggregate_timing_status_is_the_weaker_of_peak_and_trough():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    raw.loc["2020-08-01":"2020-10-01", "extent_pct"] = [1.0, 1.02, 1.04]
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, measurement_tolerance_pct=0.1)
    )
    row = result.loc[result["hy_year"] == 2020].iloc[0]
    order = {"unresolved": 0, "interval": 1, "point": 2}
    weakest = min(row["peak_timing_status"], row["trough_timing_status"], key=order.get)
    assert row["timing_status"] == weakest


def test_two_phase_is_the_default_phase_scheme():
    config = DynamicHydroYearConfig(expected_trough_month=9)
    assert config.phase_scheme == "two_phase"
    assert config.phase_model is None


def test_explicit_phase_schemes_are_stored():
    two = DynamicHydroYearConfig(expected_trough_month=9, phase_scheme="two_phase")
    assert two.phase_scheme == "two_phase"


def _anchored_frame(trough_by_year, *, anchor_month=7, n_years=6, base=40.0, low=2.0):
    """Monthly frame whose annual minimum sits at the requested calendar month.

    ``trough_by_year`` is one calendar month per year, so a caller can place a
    true trough outside a given search radius on purpose.
    """
    index = pd.date_range("2000-01-01", periods=12 * n_years, freq="MS")
    values = np.full(len(index), base, dtype=float)
    for offset, month in enumerate(trough_by_year):
        rows = np.arange(offset * 12, (offset + 1) * 12)
        values[rows[index.month.to_numpy()[rows] == month]] = low
    return pd.DataFrame(
        {"extent_pct": values, "invalid_pct": np.zeros(len(index))}, index=index
    ), anchor_month


def _anchored_frame_with_missing_cycle_edges() -> pd.DataFrame:
    index = pd.date_range("2000-01-01", periods=36, freq="MS")
    by_month = {
        1: 40.0, 2: 30.0, 3: 20.0, 4: 15.0, 5: 10.0, 6: 7.0,
        7: 5.0,
        8: 10.0, 9: 18.0, 10: 25.0, 11: 35.0,
        12: 50.0,
    }
    values = [by_month[dt.month] for dt in index]
    frame = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
    frame.loc["2000-08-01", "invalid_pct"] = 100.0
    frame.loc["2001-07-01", "invalid_pct"] = 100.0
    return frame



def test_annual_columns_carry_geometry_diagnostics():
    for column in (
        "trough_search_radius_used",
        "boundary_at_search_edge",
        "boundary_search_edge_side",
        "outside_window_observed",
        "outside_window_lower",
        "retry_outcome",
    ):
        assert column in ANNUAL_COLUMNS


def test_boundary_at_window_centre_is_not_an_edge():
    frame, anchor = _anchored_frame([7] * 6)
    config = DynamicHydroYearConfig(expected_trough_month=anchor, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    resolved = result.loc[result["trough_month"].notna()]
    assert not resolved["boundary_at_search_edge"].any()
    assert (resolved["boundary_search_edge_side"] == "none").all()
    assert (resolved["trough_search_radius_used"] == 3).all()


def test_boundary_pinned_to_right_edge_is_reported_with_its_side():
    # True trough three months after the anchor: exactly the right edge of a
    # radius-3 window.
    frame, anchor = _anchored_frame([10] * 6)
    config = DynamicHydroYearConfig(expected_trough_month=anchor, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    resolved = result.loc[result["trough_month"].notna()]
    edge = resolved.loc[resolved["boundary_at_search_edge"]]
    assert not edge.empty
    assert (edge["boundary_search_edge_side"] == "right").all()
    assert (edge["phase_shift_months"].abs() == edge["trough_search_radius_used"]).all()


def test_outside_window_lower_reports_a_strictly_lower_observed_outer_month():
    # Anchor July, radius 3 -> window Apr..Oct. Place a deeper low in December,
    # five months out: inside the audit span, outside the search window.
    index = pd.date_range("2000-01-01", periods=12 * 6, freq="MS")
    values = np.full(len(index), 40.0)
    values[index.month == 10] = 5.0
    values[index.month == 12] = 1.0
    frame = pd.DataFrame(
        {"extent_pct": values, "invalid_pct": np.zeros(len(index))}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=7, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    resolved = result.loc[result["trough_month"].notna()]
    interior = resolved.iloc[1:-1]
    assert interior["outside_window_observed"].any()
    assert interior["outside_window_lower"].any()


def test_audit_span_is_empty_at_the_widest_radius():
    """A diagnostic must never name a month the detector could not reach."""
    frame, anchor = _anchored_frame([7] * 6)
    config = DynamicHydroYearConfig(
        expected_trough_month=anchor,
        trough_search_radius_months=_DIAGNOSTIC_AUDIT_RADIUS_MONTHS,
    )
    result = detect_dynamic_hydrological_years(frame, config=config)
    assert not result["outside_window_observed"].any()
    assert not result["outside_window_lower"].any()


def test_retry_outcome_defaults_to_not_attempted():
    frame, anchor = _anchored_frame([7] * 6)
    config = DynamicHydroYearConfig(expected_trough_month=anchor, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    assert set(result["retry_outcome"]) <= {"not_attempted", "applied", "rolled_back"}
    assert (result["retry_outcome"] == "not_attempted").all()


def test_audit_span_never_reaches_a_month_the_search_radius_could_not_touch():
    # Anchor July, radius 3 -> window Apr..Oct, audit span reaches at most
    # +-5 months (Feb, Mar, Nov, Dec). January sits at offset +6/-6 from
    # every year's anchor: inside neither the search window nor the widest
    # possible audit span. Its much deeper low must never be reported as a
    # challenge, however far the audit span is (mis)computed to reach.
    index = pd.date_range("2000-01-01", periods=12 * 6, freq="MS")
    values = np.full(len(index), 40.0)
    values[index.month == 7] = 2.0
    values[index.month == 1] = 1.0
    frame = pd.DataFrame(
        {"extent_pct": values, "invalid_pct": np.zeros(len(index))}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=7, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    resolved = result.loc[result["trough_month"].notna()]
    interior = resolved.iloc[1:-1]
    assert interior["outside_window_observed"].all()
    assert not interior["outside_window_lower"].any()


def test_outside_window_lower_uses_raw_extent_not_quality_filtered():
    # November carries invalid_pct=60 -- well above the default
    # max_invalid_pct=20 threshold, so quality screening (quality_state ==
    # "low", candidate_usable False under quality_policy="exclude") would
    # drop it as a candidate entirely -- yet it is still a real observation
    # (invalid_pct < 100, so valid pixels back the value) and its raw
    # extent_pct is genuinely lower than the selected July trough.
    # outside_window_lower compares raw observed extents, matching the rule
    # the adaptive retry itself uses, so it must still report True; a
    # quality-filtered comparison would drop November and report False.
    index = pd.date_range("2000-01-01", periods=12 * 6, freq="MS")
    values = np.full(len(index), 40.0)
    invalid = np.zeros(len(index))
    values[index.month == 7] = 5.0
    values[index.month == 11] = 1.0
    invalid[index.month == 11] = 60.0
    frame = pd.DataFrame({"extent_pct": values, "invalid_pct": invalid}, index=index)
    config = DynamicHydroYearConfig(expected_trough_month=7, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    resolved = result.loc[result["trough_month"].notna()]
    interior = resolved.iloc[1:-1]
    assert interior["outside_window_observed"].all()
    assert interior["outside_window_lower"].all()


def test_outside_window_lower_excludes_a_fully_invalid_outer_month():
    # November carries invalid_pct=100 -- no valid pixels back its
    # extent_pct, so it is not an observation at all, even though its raw
    # extent_pct value is lower than the selected July trough. Unlike the
    # partially invalid case above, outside_window_lower must not treat a
    # fully invalid month as a challenge, matching the rule
    # _adaptive_edge_retry_years uses.
    index = pd.date_range("2000-01-01", periods=12 * 6, freq="MS")
    values = np.full(len(index), 40.0)
    invalid = np.zeros(len(index))
    values[index.month == 7] = 5.0
    values[index.month == 11] = 1.0
    invalid[index.month == 11] = 100.0
    frame = pd.DataFrame({"extent_pct": values, "invalid_pct": invalid}, index=index)
    config = DynamicHydroYearConfig(expected_trough_month=7, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    resolved = result.loc[result["trough_month"].notna()]
    interior = resolved.iloc[1:-1]
    assert interior["outside_window_observed"].all()
    assert not interior["outside_window_lower"].any()


def test_retry_outcome_reports_applied_when_the_widened_boundary_survives():
    years = list(range(2000, 2006))
    index = pd.date_range("2000-01-01", periods=12 * 6, freq="MS")
    values = np.full(len(index), 40.0)

    def set_month(year, month, value):
        values[index.get_loc(pd.Timestamp(year, month, 1))] = value

    for year in years:
        set_month(year, 7, 5.0)

    target = 2002
    # Base window (radius 3) puts the trough at April: exactly the window's
    # left edge. February -- two months further back, inside the adaptive
    # retry's 5-month reach but outside the base window -- carries a
    # genuinely lower, fully observed extent, so `_adaptive_edge_retry_years`
    # is expected to fire and the widened search should pull the boundary
    # back to February. The surrounding months stay rich enough that the
    # resulting (shorter) cycle still clears the retry's relaxed
    # usable-month floor, so the widened boundary should survive.
    set_month(target, 4, 3.0)
    set_month(target, 7, 20.0)
    set_month(target, 2, 1.0)
    set_month(target, 3, 40.0)

    frame = pd.DataFrame(
        {"extent_pct": values, "invalid_pct": np.zeros(len(index))}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=7, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    row = result.loc[result["hy_year"] == target].iloc[0]
    assert row["trough_month"] == pd.Timestamp(target, 2, 1)
    assert row["retry_outcome"] == "applied"


def test_retry_outcome_reports_rolled_back_when_the_widened_boundary_fails_coverage():
    years = list(range(2000, 2006))
    index = pd.date_range("2000-01-01", periods=12 * 6, freq="MS")
    values = np.full(len(index), 40.0)

    def set_month(year, month, value):
        values[index.get_loc(pd.Timestamp(year, month, 1))] = value

    for year in years:
        set_month(year, 7, 5.0)

    previous_year, target = 2001, 2002
    # Radius-2 windows. The previous year's trough sits at its own window's
    # right edge (September), so the cycle feeding into `target` starts
    # late. `target`'s base trough sits at its own window's left edge (May);
    # two months further back -- inside the adaptive retry's 5-month reach
    # but outside the base window -- is a genuinely lower, fully observed
    # extent in February, so `_adaptive_edge_retry_years` is expected to
    # fire. Pulling the boundary back to February shrinks the already-short
    # cycle below even the retry's relaxed usable-month floor, so the
    # widened attempt must be rolled back to the original (April) boundary.
    set_month(previous_year, 9, 5.0)
    set_month(previous_year, 7, 40.0)
    set_month(target, 5, 3.0)
    set_month(target, 7, 40.0)
    set_month(target, 2, 1.0)
    set_month(target, 3, 40.0)
    set_month(target, 4, 40.0)

    frame = pd.DataFrame(
        {"extent_pct": values, "invalid_pct": np.zeros(len(index))}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=7, trough_search_radius_months=2)
    result = detect_dynamic_hydrological_years(frame, config=config)
    row = result.loc[result["hy_year"] == target].iloc[0]
    # The widened attempt is rolled back: the boundary stays at its base
    # (pre-retry) month, not the lower one the retry found.
    assert row["trough_month"] == pd.Timestamp(target, 5, 1)
    assert row["retry_outcome"] == "rolled_back"


def test_boundary_pinned_to_left_edge_is_reported_with_its_side():
    # True trough three months before the anchor: exactly the left edge of a
    # radius-3 window.
    frame, anchor = _anchored_frame([4] * 6)
    config = DynamicHydroYearConfig(expected_trough_month=anchor, trough_search_radius_months=3)
    result = detect_dynamic_hydrological_years(frame, config=config)
    resolved = result.loc[result["trough_month"].notna()]
    edge = resolved.loc[resolved["boundary_search_edge_side"] == "left"]
    assert not edge.empty
    assert edge["boundary_at_search_edge"].all()
    assert (edge["phase_shift_months"] == -edge["trough_search_radius_used"]).all()


def test_adaptive_geometry_defaults_match_the_shipped_constants():
    from hydroseason._dynamic_year import (
        _ADAPTIVE_MIN_USABLE_MONTHS_PER_CYCLE,
        _ADAPTIVE_TROUGH_SEARCH_RADIUS_MONTHS,
    )

    config = DynamicHydroYearConfig(expected_trough_month=7)
    assert config.trough_search_radius_months == 3
    assert config.adaptive_trough_search_radius_months == _ADAPTIVE_TROUGH_SEARCH_RADIUS_MONTHS
    assert config.adaptive_min_usable_months_per_cycle == _ADAPTIVE_MIN_USABLE_MONTHS_PER_CYCLE


def test_adaptive_radius_may_not_narrow_the_base_search():
    with pytest.raises(ValueError, match="must not be smaller than trough_search_radius_months"):
        DynamicHydroYearConfig(
            expected_trough_month=7,
            trough_search_radius_months=5,
            adaptive_trough_search_radius_months=3,
        )


def test_adaptive_radius_respects_the_derived_upper_bound():
    """A symmetric radius 6 spans 13 months, so adjacent windows would overlap."""
    with pytest.raises(ValueError, match="adaptive_trough_search_radius_months must be in 0..5"):
        DynamicHydroYearConfig(
            expected_trough_month=7, adaptive_trough_search_radius_months=6
        )


def test_relaxed_coverage_may_not_tighten_the_base_minimum():
    with pytest.raises(ValueError, match="adaptive_min_usable_months_per_cycle"):
        DynamicHydroYearConfig(
            expected_trough_month=7,
            min_usable_months_per_cycle=8,
            adaptive_min_usable_months_per_cycle=9,
        )


def test_unset_adaptive_minimum_derives_from_a_below_default_base():
    # A caller who sets only min_usable_months_per_cycle=5 (below the shipped
    # adaptive default of 6) must not see a ValueError naming a field they
    # never touched, for a default value they never supplied. The old
    # runtime clamp absorbed this case silently; the derived default must
    # keep doing so.
    config = DynamicHydroYearConfig(expected_trough_month=7, min_usable_months_per_cycle=5)
    assert config.adaptive_min_usable_months_per_cycle == 5


def test_unset_adaptive_minimum_derives_from_a_far_below_default_base():
    config = DynamicHydroYearConfig(expected_trough_month=7, min_usable_months_per_cycle=3)
    assert config.adaptive_min_usable_months_per_cycle == 3


def test_unset_adaptive_minimum_matches_shipped_default_for_the_common_base():
    # min_usable_months_per_cycle=8 is the only value used anywhere in this
    # repo; the resolved adaptive default here must be byte-identical to the
    # value shipped before this fix (min(6, 8) == 6).
    config = DynamicHydroYearConfig(expected_trough_month=7, min_usable_months_per_cycle=8)
    assert config.adaptive_min_usable_months_per_cycle == 6


def test_explicit_inconsistent_adaptive_minimum_still_raises():
    # An explicitly-supplied value that is inconsistent with the base must
    # still be rejected strictly; only the unset case gets a derived default.
    with pytest.raises(ValueError, match="adaptive_min_usable_months_per_cycle"):
        DynamicHydroYearConfig(
            expected_trough_month=7,
            min_usable_months_per_cycle=5,
            adaptive_min_usable_months_per_cycle=6,
        )


def test_configured_geometry_reaches_detection():
    frame, anchor = _anchored_frame([7] * 6)
    wide = DynamicHydroYearConfig(
        expected_trough_month=anchor,
        trough_search_radius_months=5,
        adaptive_trough_search_radius_months=5,
        adaptive_min_usable_months_per_cycle=5,
    )
    result = detect_dynamic_hydrological_years(frame, config=wide)
    resolved = result.loc[result["trough_month"].notna()]
    assert (resolved["trough_search_radius_used"] == 5).all()


def test_cycle_timing_passes_full_bounds_when_edge_months_are_unusable(monkeypatch):
    seen = []
    real = dynamic_year.assess_window_timing

    def capture(*args, **kwargs):
        seen.append((kwargs["window_start"], kwargs["window_end"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(dynamic_year, "assess_window_timing", capture)
    frame = _anchored_frame_with_missing_cycle_edges()
    detect_dynamic_hydrological_years(
        frame,
        config=DynamicHydroYearConfig(
            expected_trough_month=7,
            recurrence_policy="no_narrowing",
        ),
    )
    assert seen
    assert all(start.day == end.day == 1 for start, end in seen)
    assert any((end.year - start.year) * 12 + end.month - start.month >= 12 for start, end in seen)


def _monsoon_frame(peak_invalid, *, years=6):
    """Annual cycles peaking in February, with a chosen invalid% on every peak.

    Every February carries the same invalid fraction, so heavy-but-consistent
    wet-season cloud is normal for the month by construction.
    """
    idx = pd.date_range("2015-01-01", periods=years * 12, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (idx.month - 2) / 12)
    invalid = np.where(idx.month == 2, peak_invalid, 2.0).astype(float)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": invalid}, index=idx)


def test_routine_wet_season_cloud_does_not_downgrade_the_cycle():
    """35% every February is normal for a February and must not mark cycles partial."""
    result = detect_dynamic_hydrological_years(
        _monsoon_frame(35.0), config=DynamicHydroYearConfig(expected_trough_month=8)
    )
    interior = result.iloc[1:-1]

    assert (interior["status"] == "complete").all()
    assert (interior["boundary_status"] == "confirmed").all()
    assert (interior["peak_quality"] == "normal").all()


def test_a_peak_far_above_its_month_norm_still_downgrades_the_cycle():
    """One February at 85% against a 20% norm is anomalous, not seasonal."""
    frame = _monsoon_frame(20.0)
    frame.loc["2018-02-01", "invalid_pct"] = 85.0
    result = detect_dynamic_hydrological_years(
        frame, config=DynamicHydroYearConfig(expected_trough_month=8)
    ).set_index("hy_year")

    assert result.loc[2018, "peak_quality"] == "anomalous"
    assert result.loc[2018, "status"] == "partial"
    assert result.loc[2018, "status_reason"] == "peak_quality_anomalous"


def test_peak_selection_status_is_unchanged_by_the_new_verdict():
    """The raw selector verdict keeps its own meaning and is still reported."""
    frame = _monsoon_frame(35.0)
    result = detect_dynamic_hydrological_years(
        frame, config=DynamicHydroYearConfig(expected_trough_month=8)
    )
    interior = result.iloc[1:-1]

    assert (interior["peak_selection_status"] == "low_quality").all()
    assert (interior["peak_quality"] == "normal").all()


def test_a_record_with_no_quality_problem_flags_no_anomalous_peaks():
    """A p90 has a tenth of its samples above it, whatever the units.

    Before the floor, this record -- every month between 1% and 5% invalid,
    which is flawless data -- had 10% of its months flagged anomalous purely
    for being that calendar month's cloudiest. Nothing here is anomalous.
    """
    rng = np.random.default_rng(0)
    idx = pd.date_range("2005-01-01", periods=240, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (idx.month - 2) / 12)
    frame = pd.DataFrame(
        {"extent_pct": values, "invalid_pct": rng.uniform(1.0, 5.0, len(idx))},
        index=idx,
    )

    result = detect_dynamic_hydrological_years(
        frame, config=DynamicHydroYearConfig(expected_trough_month=8)
    )

    assert (result["peak_quality"] == "normal").all()
    assert not result["status_reason"].eq("peak_quality_anomalous").any()



