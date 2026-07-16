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


from hydroseason._dynamic_year import _find_semi_markov_trough_opportunities


def _semi_markov_seasonal_frame(years=6):
    # Same shape family as tests/test_semi_markov.py's own fixture (a clean
    # annual cycle repeated), so the HSMM reliably localizes one trough per
    # year with high transition-posterior support.
    index = pd.date_range("2019-01-01", periods=years * 12, freq="MS")
    annual = np.array([80, 75, 60, 40, 25, 15, 8, 4, 3, 5, 20, 55], dtype=float)
    values = np.tile(annual, years)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_semi_markov_adapter_resolves_every_year_in_a_clean_cycle():
    raw = _semi_markov_seasonal_frame(6)
    config = DynamicHydroYearConfig(expected_trough_month=9, trough_search_radius_months=3)
    rows = _find_semi_markov_trough_opportunities(prepare_monthly_extent(raw), config)
    assert rows["trough_month"].notna().all()
    assert (rows["status"] == "complete").all()
    assert (rows["boundary_status"] == "confirmed").all()
    assert (rows["selection_support"] >= 0.80).all()
    # Engine-specific placeholder columns per the adapter's documented contract.
    assert (rows["raw_trough_month"] == rows["trough_month"]).all()
    assert (rows["window_status"] == "full").all()
    assert (rows["selection_status"] == "raw").all()
    assert rows["low_run_start_month"].isna().all()
    assert rows["low_run_end_month"].isna().all()
    assert rows["window_n_expected"].isna().all()
    assert rows["window_n_usable"].isna().all()


def test_semi_markov_adapter_reports_provisional_below_support_threshold():
    # Making the months adjacent to 2021's trough unusable lowers the summed
    # +/-1 month transition-posterior support for that year below the shared
    # 0.80 confirmation threshold, while neighbouring years stay confirmed --
    # exercising both branches of the confirmed/provisional split in one
    # cheap synthetic fixture (no need to lean on the experimental promotion
    # -gate test for this).
    raw = _semi_markov_seasonal_frame(6)
    raw.loc["2021-10-01":"2021-11-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, trough_search_radius_months=3)
    rows = _find_semi_markov_trough_opportunities(prepare_monthly_extent(raw), config)
    provisional = rows.loc[rows["hy_year"] == 2021].iloc[0]
    assert provisional["status"] == "partial"
    assert provisional["status_reason"] == "boundary_provisional"
    assert provisional["boundary_status"] == "provisional"
    assert pd.notna(provisional["trough_month"])
    assert provisional["selection_support"] < 0.80
    confirmed_years = rows.loc[rows["hy_year"] != 2021]
    assert (confirmed_years["boundary_status"] == "confirmed").all()


def test_semi_markov_adapter_reports_unresolved_when_no_candidate_in_radius():
    # Truncate the series so the final nominal year's expected trough window
    # never opens (the HSMM has no data there at all), leaving that year with
    # no in-radius candidate in result.trough_months.
    raw = _semi_markov_seasonal_frame(6).iloc[:61]
    config = DynamicHydroYearConfig(expected_trough_month=9, trough_search_radius_months=3)
    rows = _find_semi_markov_trough_opportunities(prepare_monthly_extent(raw), config)
    last_year = rows.loc[rows["hy_year"] == 2024].iloc[0]
    assert last_year["status"] == "unresolved"
    assert pd.isna(last_year["trough_month"])
    assert last_year["status_reason"] == "insufficient_trough_candidates"
    # Earlier, fully-covered years are unaffected by the truncation.
    assert (rows.loc[rows["hy_year"] != 2024, "trough_month"].notna()).all()


# The "already-used trough_months entry" defensive dedup branch (see the
# docstring of `_find_semi_markov_trough_opportunities`) is unreachable
# through this adapter for any valid `DynamicHydroYearConfig`: consecutive
# nominal years' expected trough dates are always exactly 12 months apart,
# while `trough_search_radius_months` is capped at 5 by
# `DynamicHydroYearConfig.__post_init__`. Two windows of radius <=5 centred
# 12 months apart can jointly reach at most 5+5=10 months towards each
# other's centre, which is less than the 12-month gap -- so no single
# `result.trough_months` entry can ever fall within radius of two different
# nominal years' expected dates, and the dedup guard can never trigger via
# the public adapter. It is retained as defensive belt-and-suspenders code
# (mirroring `_select_troughs`'s own "already used" guard) rather than
# covered by a contrived/invalid-config test.


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


def test_additive_diagnostic_columns_present_and_populated_for_both_detectors():
    # test_both_detectors_return_identical_columns above only checks column-name
    # parity between the two detectors; it never checks the additive robust-
    # extrema diagnostic columns against the full ANNUAL_COLUMNS contract, nor
    # that they are actually populated (not all-NaN) for a resolved cycle under
    # either detector choice. This closes that gap.
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

    # The semi-Markov engine has no raw-vs-selected window/run concept (see
    # _find_semi_markov_trough_opportunities's docstring): it always fills
    # these trough-window diagnostics with placeholders rather than real
    # per-window measurements, so they are excluded from the "must be
    # populated" check for that detector only.
    always_populated = [c for c in additive_columns if c not in {"low_run_start_month", "low_run_end_month", "window_n_expected", "window_n_usable"}]

    for detector in ("robust_extrema", "semi_markov"):
        result = detect_dynamic_hydrological_years(
            raw, config=DynamicHydroYearConfig(expected_trough_month=9, detector=detector)
        )
        assert list(result.columns) == ANNUAL_COLUMNS
        complete = result.loc[result["status"] == "complete"]
        assert not complete.empty, f"no resolved cycle for detector={detector}"
        row = complete.iloc[0]
        for column in always_populated:
            assert pd.notna(row[column]), f"{column} is NaN for detector={detector}"
        assert row["window_status"] in {"full", "left_truncated", "right_truncated", "internal_gap"}
        assert row["selection_status"] in {"raw", "ambiguous", "quality_adjusted", "unresolved"}
        assert 0.0 <= row["selection_support"] <= 1.0
        assert row["boundary_status"] in {"confirmed", "provisional"}

    # The robust_extrema detector, by contrast, does populate every additive
    # column, including the window/run diagnostics the semi-Markov engine
    # cannot provide.
    robust_row = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, detector="robust_extrema")
    ).pipe(lambda df: df.loc[df["status"] == "complete"]).iloc[0]
    for column in additive_columns:
        assert pd.notna(robust_row[column]), f"{column} is NaN for robust_extrema"


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
