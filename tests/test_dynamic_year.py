import warnings

import numpy as np
import pandas as pd
import pytest

from hydroseason._dynamic_year import DynamicHydroYearConfig, suggest_dynamic_hydro_year_config
from hydroseason._seasonality import classify_seasonal_pattern


def _monsoonal(years=12):
    index = pd.date_range("2000-01-01", periods=years * 12, freq="MS")
    values = 30.0 + 25.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_suggestion_uses_advisory_phase_and_user_overrides_win():
    extent = _monsoonal()
    pattern = classify_seasonal_pattern(extent, n_bootstrap=40)
    config = suggest_dynamic_hydro_year_config(extent, pattern=pattern, trough_search_radius_months=2)
    assert config.expected_trough_month == pattern.expected_trough_month
    assert config.expected_peak_month == pattern.expected_peak_month
    assert config.trough_search_radius_months == 2


def test_unstable_pattern_requires_explicit_trough():
    extent = _monsoonal(years=4)
    with pytest.raises(ValueError, match="expected_trough_month"):
        suggest_dynamic_hydro_year_config(extent)


def test_dynamic_config_rejects_invalid_recovery_geometry():
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=13)
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=9, pulse_rejection_window_months=0)


from hydroseason._dynamic_year import _find_robust_trough_opportunities
from hydroseason._state_input import prepare_monthly_extent


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


from dataclasses import replace

from hydroseason._dynamic_year import detect_dynamic_hydrological_years


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


def test_unresolved_nominal_year_breaks_cycles_instead_of_merging():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle")
    result = detect_dynamic_hydrological_years(raw, config=config)
    assert result.loc[result["hy_year"] == 2020, "status"].item() == "unresolved"
    assert result.loc[result["hy_year"] == 2021, "status_reason"].item() == "no_previous_boundary"
    resolved_lengths = result.loc[result["status"] == "complete", "cycle_months"]
    assert (resolved_lengths <= 18).all()


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


def test_detector_field_accepts_semi_markov():
    config = DynamicHydroYearConfig(expected_trough_month=9, detector="semi_markov")
    assert config.detector == "semi_markov"


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
    assert complete["peak_selection_status"] in {"raw", "ambiguous", "quality_adjusted"}
    assert pd.notna(complete["peak_selection_support"])
    assert 0.0 <= complete["peak_selection_support"] <= 1.0


def test_both_detectors_return_identical_columns():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    robust = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, detector="robust_extrema")
    )
    semi = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, detector="semi_markov")
    )
    assert list(semi.columns) == list(robust.columns)
    assert semi["trough_month"].notna().any()


def test_peak_diagnostic_columns_are_nan_for_unresolved_cycles():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle")
    result = detect_dynamic_hydrological_years(raw, config=config)
    # 2020 is unresolved (insufficient_trough_candidates); 2021 has no previous
    # boundary. Neither reaches peak selection, so all four peak diagnostics stay NaN.
    for year in (2020, 2021):
        row = result.loc[result["hy_year"] == year].iloc[0]
        assert pd.isna(row["raw_peak_month"])
        assert pd.isna(row["raw_peak_extent_pct"])
        assert pd.isna(row["peak_selection_status"])
        assert pd.isna(row["peak_selection_support"])
