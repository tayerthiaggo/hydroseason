import numpy as np
import pandas as pd
import pytest

from hydroseason._timing_identifiability import (
    TimingIdentifiabilityThresholds,
    assess_timing_identifiability,
)

TEST_THRESHOLDS = TimingIdentifiabilityThresholds(
    min_amplitude_to_floor_ratio=1.5,
    min_peak_water_pixels=1,
    max_point_span_months=0,
    max_boundary_interval_months=3,
    min_informative_years=2,
)


def _counts(values, *, year=2001, n_valid=100, n_water=None, invalid_pct=0.0):
    index = pd.date_range(f"{year}-01-01", periods=len(values), freq="MS")
    valid = np.broadcast_to(n_valid, len(values)).astype(int)
    water = np.asarray(values if n_water is None else n_water, dtype=int)
    invalid = np.rint(valid * invalid_pct / (100.0 - invalid_pct)).astype(int)
    return pd.DataFrame(
        {
            "extent_pct": np.asarray(values, dtype=float),
            "n_water": water,
            "n_valid": valid,
            "n_invalid": invalid,
            "n_aoi": valid + invalid,
        },
        index=index,
    )


def test_all_zero_year_is_observed_but_timing_unresolved():
    result = assess_timing_identifiability(_counts([0] * 12), thresholds=TEST_THRESHOLDS)

    year = result.years[2001]
    assert year.n_zero_months == 12
    assert year.detectable is False
    assert year.peak_months == year.trough_months == ()
    assert year.peak_status == year.trough_status == "unresolved"


def test_one_detectable_pixel_pulse_can_identify_peak_not_trough():
    result = assess_timing_identifiability(
        _counts([0, 2] + [0] * 10), thresholds=TEST_THRESHOLDS
    )

    year = result.years[2001]
    assert year.peak_status == "point"
    assert year.peak_months == (2,)
    assert year.trough_status == "unresolved"


def test_contiguous_zero_plateau_is_interval():
    result = assess_timing_identifiability(
        _counts([10] * 7 + [0] * 3 + [10] * 2), thresholds=TEST_THRESHOLDS
    )

    year = result.years[2001]
    assert year.trough_status == "interval"
    assert year.trough_months == (8, 9, 10)


def test_zero_fraction_never_changes_detectability_by_itself():
    detectable_cycle = _counts([0, 2] + [0] * 10)
    extra_years = pd.concat([_counts([0] * 12, year=2000), detectable_cycle])

    compact = assess_timing_identifiability(detectable_cycle, thresholds=TEST_THRESHOLDS)
    zero_padded = assess_timing_identifiability(extra_years, thresholds=TEST_THRESHOLDS)

    assert compact.years[2001].detectable == zero_padded.years[2001].detectable
    assert compact.years[2001].peak_status == zero_padded.years[2001].peak_status


def test_percentage_only_input_reports_pixel_support_unavailable():
    values = pd.Series(
        [0.0, 2.0] + [0.0] * 10,
        index=pd.date_range("2001-01-01", periods=12, freq="MS"),
    )

    result = assess_timing_identifiability(values, thresholds=TEST_THRESHOLDS)

    assert result.pixel_support_status == "unavailable"


def test_december_january_equivalent_months_have_a_one_month_span():
    result = assess_timing_identifiability(
        _counts([0] + [10] * 10 + [10]), thresholds=TEST_THRESHOLDS
    )

    year = result.years[2001]
    assert year.peak_months == (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
    assert year.peak_status == "unresolved"


def test_non_contiguous_equivalent_extrema_are_not_points():
    result = assess_timing_identifiability(
        _counts([10, 0, 10] + [0] * 9), thresholds=TEST_THRESHOLDS
    )

    year = result.years[2001]
    assert year.peak_months == (1, 3)
    assert year.peak_status == "interval"


def test_missing_and_fully_invalid_months_are_not_usable_or_zeroes():
    frame = _counts([0, 2] + [0] * 10)
    frame.loc["2001-03-01", ["n_water", "n_valid", "n_invalid", "n_aoi"]] = [0, 0, 100, 100]
    frame = frame.drop(pd.Timestamp("2001-04-01"))

    year = assess_timing_identifiability(frame, thresholds=TEST_THRESHOLDS).years[2001]

    assert year.n_usable_months == 10
    assert year.n_zero_months == 9


def test_count_inputs_recompute_extent_and_use_variable_valid_pixel_resolution():
    result = assess_timing_identifiability(
        _counts(
            [99.0, 99.0] + [0.0] * 10,
            n_valid=[50, 100] + [100] * 10,
            n_water=[2, 2] + [0] * 10,
        ),
        thresholds=TEST_THRESHOLDS,
        measurement_tolerance_pct=0.0,
    )

    year = result.years[2001]
    assert year.amplitude_pp == pytest.approx(4.0)
    assert year.detectability_floor_pp == pytest.approx(2.0)
    assert year.detectable is True


def test_amplitude_ratio_equal_to_threshold_is_detectable():
    thresholds = TimingIdentifiabilityThresholds(
        min_amplitude_to_floor_ratio=2.0,
        min_peak_water_pixels=1,
        max_point_span_months=0,
        max_boundary_interval_months=3,
        min_informative_years=2,
    )

    year = assess_timing_identifiability(
        _counts([0, 2] + [0] * 10),
        thresholds=thresholds,
        measurement_tolerance_pct=1.0,
    ).years[2001]

    assert year.amplitude_to_floor_ratio == pytest.approx(2.0)
    assert year.detectable is True


def test_thresholds_reject_invalid_ordering_and_non_finite_measurement_tolerance():
    with pytest.raises(ValueError, match="max_boundary_interval_months"):
        TimingIdentifiabilityThresholds(1.0, 1, 2, 1, 2)
    with pytest.raises(ValueError, match="measurement_tolerance_pct"):
        assess_timing_identifiability(
            _counts([0] * 12), thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=np.nan
        )
