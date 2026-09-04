import numpy as np
import pandas as pd
import pytest

from hydroseason._boundary import robust_scale
from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS
from hydroseason._state_input import prepare_monthly_extent
from hydroseason._timing_identifiability import (
    TimingIdentifiabilityThresholds,
    assess_timing_identifiability,
    assess_window_timing,
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


def _window(values, *, start="2019-10-01", n_valid=100, n_water=None):
    index = pd.date_range(start, periods=len(values), freq="MS")
    valid = np.broadcast_to(n_valid, len(values)).astype(int)
    water = np.asarray(values if n_water is None else n_water, dtype=int)
    return pd.DataFrame(
        {
            "extent_pct": np.asarray(values, dtype=float),
            "n_water": water,
            "n_valid": valid,
        },
        index=index,
    )


def test_window_timing_detects_a_point_peak_across_a_cycle_spanning_two_years():
    # Cycle Oct-2019..Sep-2020: a single sharp peak in Nov identifies a point,
    # even though the window crosses a calendar-year boundary.
    values = [5.0, 40.0, 8.0, 6.0, 5.0, 4.0, 3.0, 3.0, 2.0, 2.0, 1.0, 1.0]
    rows = _window(values)
    result = assess_window_timing(
        rows["extent_pct"], rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.5,
        pixel_support_status="unavailable",
    )
    assert result.detectable is True
    assert result.peak_status == "point"
    assert result.peak_dates == (pd.Timestamp("2019-11-01"),)


def test_window_timing_reports_interval_for_a_broad_plateau():
    values = [30.0, 25.0, 20.0, 1.0, 1.1, 1.0, 15.0, 20.0, 25.0, 28.0, 29.0, 30.0]
    rows = _window(values)
    result = assess_window_timing(
        rows["extent_pct"], rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.5,
        pixel_support_status="unavailable",
    )
    assert result.trough_status == "interval"
    assert result.trough_dates == (
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01"), pd.Timestamp("2020-03-01"),
    )


def test_window_timing_flat_cycle_is_unresolved_and_at_or_below_floor():
    rows = _window([5.0] * 12)
    result = assess_window_timing(
        rows["extent_pct"], rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.5,
        pixel_support_status="unavailable",
    )
    assert result.detectable is False
    assert result.at_or_below_floor is True
    assert result.peak_status == result.trough_status == "unresolved"
    assert result.peak_dates == result.trough_dates == ()


def test_window_timing_empty_window_is_unresolved():
    rows = _window([])
    result = assess_window_timing(
        rows["extent_pct"], rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.5,
        pixel_support_status="unavailable",
    )
    assert result.n_usable_months == 0
    assert result.detectable is False
    assert result.peak_status == result.trough_status == "unresolved"


def test_window_timing_pixel_available_gates_on_peak_water_pixels():
    values = [1.0, 40.0, 1.0, 1.0]
    rows = _window(values, n_water=[1, 0, 1, 1])
    result = assess_window_timing(
        rows["extent_pct"], rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.1,
        pixel_support_status="available",
    )
    assert result.peak_n_water == 0
    assert result.detectable is False
    assert result.peak_status == "unresolved"


def test_window_timing_uses_same_floor_formula_as_calendar_year_assessment():
    # A single calendar year and an identical HY cycle spanning the same
    # months must agree exactly: same values, same formula.
    values = [5.0, 40.0, 8.0, 6.0, 5.0, 4.0, 3.0, 3.0, 2.0, 2.0, 1.0, 1.0]
    calendar_counts = _counts(values, year=2020)
    prepared = prepare_monthly_extent(calendar_counts)
    year_evidence = assess_timing_identifiability(
        calendar_counts, thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0
    ).years[2020]

    _amplitude_pp, noise_pp = robust_scale(prepared)
    window_rows = prepared.loc[prepared["candidate_usable"]]
    window_evidence = assess_window_timing(
        window_rows["extent_pct"], window_rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0,
        noise_pp=noise_pp,
        pixel_support_status="available",
    )
    assert window_evidence.detectability_floor_pp == pytest.approx(
        year_evidence.detectability_floor_pp
    )
    assert window_evidence.amplitude_to_floor_ratio == pytest.approx(
        year_evidence.amplitude_to_floor_ratio
    )
    assert window_evidence.detectable == year_evidence.detectable
    assert window_evidence.peak_status == year_evidence.peak_status


def _oversized_window(start="1990-02-01", periods=18, n_valid=100):
    index = pd.date_range(start, periods=periods, freq="MS")
    valid = np.broadcast_to(n_valid, periods).astype(int)
    return pd.DataFrame({"n_valid": valid}, index=index)


def test_window_timing_recovers_a_recurring_peak_in_an_oversized_cycle():
    # An 18-month window whose boundary detector could not close a clean
    # 12-month cycle (e.g. an alternating trough) can genuinely contain the
    # SAME annual peak twice, a year apart -- not one diffuse extremum. The
    # most recent occurrence is the defensible read, not "unresolved".
    values = pd.Series(
        [5.0] * 2 + [10.0] + [5.0] * 10 + [10.0] + [5.0] * 3 + [0.0],
        index=pd.date_range("1990-02-01", periods=18, freq="MS"),
    )
    rows = _oversized_window()
    result = assess_window_timing(
        values, rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.0,
        pixel_support_status="unavailable",
        recurrence_policy="annual_shape_match",
    )
    assert result.peak_status == "point"
    assert result.peak_dates == (pd.Timestamp("1991-03-01"),)


def test_window_timing_genuinely_diffuse_extremum_stays_unresolved():
    # A true diffuse spread (many distinct near-tied months, no recurrence
    # structure) must not be rescued by the recurrence-cluster narrowing.
    index = pd.date_range("1990-02-01", periods=18, freq="MS")
    values = pd.Series([10.0] * 12 + [5.0] * 6, index=index)
    rows = _oversized_window()
    result = assess_window_timing(
        values, rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.0,
        pixel_support_status="unavailable",
    )
    assert result.peak_status == "unresolved"
    assert len(result.peak_dates) == 12


def test_window_timing_recurrence_cluster_does_not_touch_a_span_within_tolerance():
    # A span already within the boundary-interval threshold must be reported
    # as-is, not silently narrowed to a sub-cluster.
    index = pd.date_range("1990-02-01", periods=6, freq="MS")
    values = pd.Series([5.0, 10.0, 10.0, 5.0, 4.0, 0.0], index=index)
    rows = _oversized_window(start="1990-02-01", periods=6)
    result = assess_window_timing(
        values, rows,
        thresholds=TEST_THRESHOLDS, measurement_tolerance_pct=1.0, noise_pp=0.0,
        pixel_support_status="unavailable",
    )
    assert result.peak_status == "interval"
    assert result.peak_dates == (pd.Timestamp("1990-03-01"), pd.Timestamp("1990-04-01"))


def test_gap_fragmented_equivalent_trough_does_not_become_a_false_point():
    index = pd.to_datetime([
        "1992-05-01", "1992-06-01", "1992-07-01", "1992-08-01",
        "1992-09-01", "1992-10-01", "1993-01-01", "1993-04-01",
    ])
    extent = np.array([40, 40, 40, 40, 40, 70, 40, 40], dtype=float)
    rows = pd.DataFrame(
        {
            "extent_pct": extent,
            "n_water": extent.astype(int),
            "n_valid": 100,
            "n_invalid": 0,
            "n_aoi": 100,
        },
        index=index,
    )
    result = assess_window_timing(
        rows["extent_pct"],
        rows,
        thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
        measurement_tolerance_pct=1.0,
        noise_pp=0.0,
        pixel_support_status="available",
        window_start=pd.Timestamp("1992-05-01"),
        window_end=pd.Timestamp("1993-04-01"),
    )
    assert result.detectable is True
    assert result.trough_status == "unresolved"
    assert result.trough_dates == tuple(index.delete(5))


def test_gap_fragmented_equivalent_peak_does_not_become_a_false_point():
    index = pd.to_datetime([
        "1992-05-01", "1992-06-01", "1992-07-01", "1992-08-01",
        "1992-09-01", "1992-10-01", "1993-01-01", "1993-04-01",
    ])
    extent = np.array([70, 70, 70, 70, 70, 40, 70, 70], dtype=float)
    rows = pd.DataFrame(
        {
            "extent_pct": extent,
            "n_water": extent.astype(int),
            "n_valid": 100,
            "n_invalid": 0,
            "n_aoi": 100,
        },
        index=index,
    )
    result = assess_window_timing(
        rows["extent_pct"],
        rows,
        thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
        measurement_tolerance_pct=1.0,
        noise_pp=0.0,
        pixel_support_status="available",
        window_start=pd.Timestamp("1992-05-01"),
        window_end=pd.Timestamp("1993-04-01"),
    )
    assert result.detectable is True
    assert result.peak_status == "unresolved"
    assert result.peak_dates == tuple(index.delete(5))


def _thresholds(**overrides):
    from hydroseason._timing_identifiability import TimingIdentifiabilityThresholds

    base = {
        "min_amplitude_to_floor_ratio": 3.0,
        "min_peak_water_pixels": 5,
        "max_point_span_months": 0,
        "max_boundary_interval_months": 2,
        "min_informative_years": 7,
    }
    base.update(overrides)
    return TimingIdentifiabilityThresholds(**base)


def _months(n):
    import pandas as pd

    return tuple(pd.Timestamp("2020-01-01") + pd.DateOffset(months=i) for i in range(n))


def test_max_broad_interval_months_defaults_to_five():
    assert _thresholds().max_broad_interval_months == 5


def test_broad_tier_is_off_by_default_preserving_current_behaviour():
    from hydroseason._timing_identifiability import _window_status

    th = _thresholds()
    # span 0 -> point, span 2 -> interval, span 3 -> unresolved (today's ladder)
    assert _window_status(_months(1), th) == "point"
    assert _window_status(_months(3), th) == "interval"
    assert _window_status(_months(4), th) == "unresolved"
    assert _window_status(_months(6), th) == "unresolved"


def test_broad_tier_when_enabled_covers_four_to_six_months():
    from hydroseason._timing_identifiability import _window_status

    th = _thresholds()
    assert _window_status(_months(1), th, allow_broad=True) == "point"
    assert _window_status(_months(3), th, allow_broad=True) == "interval"
    assert _window_status(_months(4), th, allow_broad=True) == "broad"
    assert _window_status(_months(6), th, allow_broad=True) == "broad"
    assert _window_status(_months(7), th, allow_broad=True) == "unresolved"


def test_empty_dates_are_unresolved_under_both_modes():
    from hydroseason._timing_identifiability import _window_status

    th = _thresholds()
    assert _window_status((), th) == "unresolved"
    assert _window_status((), th, allow_broad=True) == "unresolved"


def test_broad_cap_must_not_be_below_the_interval_cap():
    import pytest

    with pytest.raises(ValueError, match="max_broad_interval_months"):
        _thresholds(max_broad_interval_months=1)


def test_status_rank_orders_broad_between_interval_and_unresolved():
    from hydroseason._dynamic_year import _TIMING_STATUS_RANK

    assert (
        _TIMING_STATUS_RANK["unresolved"]
        < _TIMING_STATUS_RANK["broad"]
        < _TIMING_STATUS_RANK["interval"]
        < _TIMING_STATUS_RANK["point"]
    )


def _two_dry_seasons():
    """A trough-to-trough cycle: dry tail, wet peak, then this cycle's dry season."""
    import pandas as pd

    index = pd.date_range("2005-11-01", periods=12, freq="MS")
    values = [0.028, 0.083, 0.703, 0.276, 0.610, 0.132, 0.089, 0.068, 0.055, 0.046, 0.033, 0.019]
    return pd.Series(values, index=index, dtype=float)


def test_window_search_includes_the_previous_dry_season_tail():
    import pandas as pd
    from hydroseason._timing_identifiability import assess_window_timing

    values = _two_dry_seasons()
    rows = pd.DataFrame(index=values.index)
    ev = assess_window_timing(
        values, rows, thresholds=_thresholds(), measurement_tolerance_pct=0.0,
        noise_pp=0.0148, pixel_support_status="unavailable",
    )
    # Spans from 2005-11 across the January peak to 2006-10.
    assert ev.trough_dates[0] == pd.Timestamp("2005-11-01")
    assert ev.trough_dates[-1] == pd.Timestamp("2006-10-01")
    assert ev.trough_status == "unresolved"


def test_post_peak_search_excludes_the_previous_dry_season_tail():
    import pandas as pd
    from hydroseason._timing_identifiability import assess_window_timing

    values = _two_dry_seasons()
    rows = pd.DataFrame(index=values.index)
    ev = assess_window_timing(
        values, rows, thresholds=_thresholds(), measurement_tolerance_pct=0.0,
        noise_pp=0.0148, pixel_support_status="unavailable",
        trough_search="post_peak",
    )
    # Peak is 2006-01; no candidate may precede it.
    assert all(d >= pd.Timestamp("2006-01-01") for d in ev.trough_dates)
    assert ev.trough_dates[-1] == pd.Timestamp("2006-10-01")


def test_post_peak_search_leaves_the_peak_branch_untouched():
    import pandas as pd
    from hydroseason._timing_identifiability import assess_window_timing

    values = _two_dry_seasons()
    rows = pd.DataFrame(index=values.index)
    kw = dict(
        thresholds=_thresholds(), measurement_tolerance_pct=0.0,
        noise_pp=0.0148, pixel_support_status="unavailable",
    )
    base = assess_window_timing(values, rows, **kw)
    limb = assess_window_timing(values, rows, trough_search="post_peak", **kw)
    assert limb.peak_dates == base.peak_dates
    assert limb.peak_status == base.peak_status


def test_post_peak_search_handles_a_peak_in_the_final_month():
    import pandas as pd
    from hydroseason._timing_identifiability import assess_window_timing

    index = pd.date_range("2020-01-01", periods=4, freq="MS")
    values = pd.Series([0.05, 0.04, 0.03, 0.90], index=index, dtype=float)
    rows = pd.DataFrame(index=index)
    ev = assess_window_timing(
        values, rows, thresholds=_thresholds(), measurement_tolerance_pct=0.0,
        noise_pp=0.001, pixel_support_status="unavailable",
        trough_search="post_peak",
    )
    assert ev.trough_dates == (pd.Timestamp("2020-04-01"),)
    assert ev.trough_status == "point"


def test_cycle_trough_reports_broad_for_a_sustained_minimum():
    import pandas as pd
    from hydroseason._timing_identifiability import assess_window_timing

    index = pd.date_range("2020-01-01", periods=10, freq="MS")
    # Peak in Feb, then a five-month flat minimum Jun-Oct.
    values = pd.Series(
        [0.40, 0.90, 0.50, 0.30, 0.12, 0.050, 0.048, 0.047, 0.046, 0.045],
        index=index, dtype=float,
    )
    rows = pd.DataFrame(index=index)
    ev = assess_window_timing(
        values, rows, thresholds=_thresholds(), measurement_tolerance_pct=0.0,
        noise_pp=0.01, pixel_support_status="unavailable",
        trough_search="post_peak",
    )
    assert ev.trough_status == "broad"
    assert ev.trough_dates[0] == pd.Timestamp("2020-06-01")
    assert ev.trough_dates[-1] == pd.Timestamp("2020-10-01")


def test_calendar_window_never_reports_broad():
    import pandas as pd
    from hydroseason._timing_identifiability import assess_window_timing

    index = pd.date_range("2020-01-01", periods=10, freq="MS")
    values = pd.Series(
        [0.40, 0.90, 0.50, 0.30, 0.12, 0.050, 0.048, 0.047, 0.046, 0.045],
        index=index, dtype=float,
    )
    rows = pd.DataFrame(index=index)
    ev = assess_window_timing(
        values, rows, thresholds=_thresholds(), measurement_tolerance_pct=0.0,
        noise_pp=0.01, pixel_support_status="unavailable",
    )
    assert ev.trough_status != "broad"


def test_peak_status_is_never_broad_even_on_a_flat_peak():
    import pandas as pd
    from hydroseason._timing_identifiability import assess_window_timing

    index = pd.date_range("2020-01-01", periods=8, freq="MS")
    # Five-month flat maximum, sharp minimum at the end.
    values = pd.Series([0.90, 0.899, 0.898, 0.897, 0.896, 0.50, 0.20, 0.02], index=index, dtype=float)
    rows = pd.DataFrame(index=index)
    ev = assess_window_timing(
        values, rows, thresholds=_thresholds(), measurement_tolerance_pct=0.0,
        noise_pp=0.01, pixel_support_status="unavailable",
        trough_search="post_peak",
    )
    assert ev.peak_status != "broad"
