import warnings

import numpy as np
import pandas as pd
import pytest

from hydroseason._dynamic_year import (
    DynamicHydroYearConfig,
    _find_robust_trough_opportunities,
    detect_dynamic_hydrological_years,
    suggest_dynamic_hydro_year_config,
)
from hydroseason._seasonality import classify_seasonal_pattern
from hydroseason._state_input import prepare_monthly_extent

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
    records ``peak_low_quality`` for exactly that case) and takes ``trough``
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



def test_two_phase_is_the_default_phase_scheme():
    config = DynamicHydroYearConfig(expected_trough_month=9)
    assert config.phase_scheme == "two_phase"
    assert config.phase_model is None


def test_explicit_phase_schemes_are_stored():
    two = DynamicHydroYearConfig(expected_trough_month=9, phase_scheme="two_phase")
    assert two.phase_scheme == "two_phase"


@pytest.mark.parametrize(
    "low, high",
    [(0.5, 0.5), (0.8, 0.2), (-0.1, 0.7), (0.2, 1.1)],
)
def test_invalid_band_fractions_are_rejected(low, high):
    with pytest.raises(ValueError, match="fraction"):
        DynamicHydroYearConfig(expected_trough_month=9, phase_low_fraction=low, phase_high_fraction=high)


def test_valid_band_fractions_are_accepted():
    config = DynamicHydroYearConfig(expected_trough_month=9, phase_low_fraction=0.0, phase_high_fraction=1.0)

    assert config.phase_low_fraction == 0.0
    assert config.phase_high_fraction == 1.0


def test_minimum_duration_must_be_at_least_one_month():
    with pytest.raises(ValueError, match="phase_min_duration_months"):
        DynamicHydroYearConfig(expected_trough_month=9, phase_min_duration_months=0)


@pytest.mark.parametrize("window", [0, -1, 2, 4])
def test_smoothing_window_must_be_odd_and_positive(window):
    with pytest.raises(ValueError, match="phase_smoothing_window"):
        DynamicHydroYearConfig(expected_trough_month=9, phase_smoothing_window=window)


def test_smoothing_window_may_exceed_cycle_length():
    """Oversized windows are resolved at use time, not rejected up front."""
    assert DynamicHydroYearConfig(expected_trough_month=9, phase_smoothing_window=25).phase_smoothing_window == 25


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_phase_fractions_must_be_finite(value):
    with pytest.raises(ValueError, match="fraction"):
        DynamicHydroYearConfig(expected_trough_month=9, phase_low_fraction=value)


@pytest.mark.parametrize("field,value", [
    ("phase_min_duration_months", True),
    ("phase_min_duration_months", 1.5),
    ("phase_smoothing_window", True),
    ("phase_smoothing_window", 3.5),
])
def test_phase_integer_fields_reject_bools_and_floats(field, value):
    with pytest.raises(ValueError, match=field):
        DynamicHydroYearConfig(expected_trough_month=9, **{field: value})
