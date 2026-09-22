"""The trough-geometry corpus.

Existing partitions cannot calibrate search geometry: legacy timing jitter and
phase drift reach only about +/-2 months, and the timing-identifiability corpus
uses fixed extrema.  Neither contains a year whose true trough lies outside a
radius-3 window, so neither can distinguish radius 3 from radius 5.
"""
import pandas as pd
import pytest

from hydroseason._synthetic import (
    _TROUGH_GEOMETRY_FAMILIES,
    CALIBRATION_SEEDS,
    GEOMETRY_CALIBRATION_SEEDS,
    GEOMETRY_VALIDATION_SEEDS,
    VALIDATION_SEEDS,
    TroughGeometryTruthLabels,
    generate_trough_geometry_record,
)


def test_geometry_seed_ranges_are_disjoint_from_every_frozen_partition():
    geometry = set(GEOMETRY_CALIBRATION_SEEDS) | set(GEOMETRY_VALIDATION_SEEDS)
    frozen = set(CALIBRATION_SEEDS) | set(VALIDATION_SEEDS)
    assert not (geometry & frozen)
    assert not (set(GEOMETRY_CALIBRATION_SEEDS) & set(GEOMETRY_VALIDATION_SEEDS))


def test_record_is_deterministic_for_a_seed():
    first = generate_trough_geometry_record(30000, partition="calibration")
    second = generate_trough_geometry_record(30000, partition="calibration")
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.truth == second.truth
    assert first.family == second.family


def test_partition_rejects_a_seed_from_the_other_range():
    with pytest.raises(ValueError, match="outside the calibration partition"):
        generate_trough_geometry_record(40000, partition="calibration")
    with pytest.raises(ValueError, match="outside the validation partition"):
        generate_trough_geometry_record(30000, partition="validation")


def test_every_family_is_reachable_and_labelled():
    seen = {
        generate_trough_geometry_record(seed, partition="calibration").family
        for seed in range(30000, 30000 + 4 * len(_TROUGH_GEOMETRY_FAMILIES))
    }
    assert seen == set(_TROUGH_GEOMETRY_FAMILIES)


def test_frame_carries_counts_and_derived_percentages():
    record = generate_trough_geometry_record(30000, partition="calibration")
    for column in ("n_water", "n_valid", "n_invalid", "n_aoi", "extent_pct", "invalid_pct"):
        assert column in record.frame.columns
    assert isinstance(record.frame.index, pd.DatetimeIndex)
    assert len(record.frame) == 12 * record.truth.n_years


def test_wide_excursion_family_places_troughs_beyond_a_radius_three_window():
    """The corpus must contain what no existing partition contains."""
    index = _TROUGH_GEOMETRY_FAMILIES.index("wide_phase_excursion")
    record = generate_trough_geometry_record(30000 + index, partition="calibration")
    assert record.family == "wide_phase_excursion"
    truth = record.truth
    assert isinstance(truth, TroughGeometryTruthLabels)
    anchor = truth.climatological_trough_month
    shifts = [
        _circular_shift(date.month, anchor)
        for date in truth.trough_date_by_year
        if date is not None
    ]
    assert max(abs(shift) for shift in shifts) >= 4
    assert truth.max_abs_excursion_months >= 4


def _circular_shift(month: int, anchor: int) -> int:
    raw = (month - anchor) % 12
    return raw - 12 if raw > 6 else raw


def test_plateau_family_declares_no_identifiable_point_truth():
    index = _TROUGH_GEOMETRY_FAMILIES.index("tied_low_plateau_wide")
    record = generate_trough_geometry_record(30000 + index, partition="calibration")
    assert record.family == "tied_low_plateau_wide"
    assert not any(record.truth.identifiable_by_year)
    assert all(date is None for date in record.truth.trough_date_by_year)


def test_missing_outer_months_family_removes_the_months_a_wider_window_would_need():
    index = _TROUGH_GEOMETRY_FAMILIES.index("missing_outer_months")
    record = generate_trough_geometry_record(30000 + index, partition="calibration")
    assert record.family == "missing_outer_months"
    assert (record.frame["n_valid"] == 0).any()


def test_truth_lengths_agree_with_the_declared_year_count():
    for offset in range(len(_TROUGH_GEOMETRY_FAMILIES)):
        truth = generate_trough_geometry_record(30000 + offset, partition="calibration").truth
        assert len(truth.trough_date_by_year) == truth.n_years
        assert len(truth.identifiable_by_year) == truth.n_years


def test_every_truth_date_lies_inside_its_own_frame():
    """A truth date on the wrong base year makes every error metric meaningless.

    ``_monthly_index`` starts at 1990, so a truth date built on any other base
    year falls silently outside the frame instead of raising.
    """
    for offset in range(len(_TROUGH_GEOMETRY_FAMILIES)):
        record = generate_trough_geometry_record(30000 + offset, partition="calibration")
        for date in record.truth.trough_date_by_year:
            if date is not None:
                assert date in record.frame.index, f"{record.family}: {date} outside frame"


def test_identifiable_truth_dates_sit_at_the_annual_minimum():
    """Truth must describe the record, not merely accompany it."""
    for offset in range(len(_TROUGH_GEOMETRY_FAMILIES)):
        record = generate_trough_geometry_record(30000 + offset, partition="calibration")
        for year_offset, date in enumerate(record.truth.trough_date_by_year):
            if date is None or not record.truth.identifiable_by_year[year_offset]:
                continue
            window = record.frame.iloc[year_offset * 12 : (year_offset + 1) * 12]
            observed = window["extent_pct"].dropna()
            if observed.empty:
                continue
            assert float(record.frame.loc[date, "extent_pct"]) == pytest.approx(
                float(observed.min())
            ), f"{record.family} year {year_offset}: truth is not the annual minimum"


def test_identifiable_truth_dates_are_the_unique_annual_minimum():
    """A tied annual minimum is not an identifiable point truth.

    ``test_identifiable_truth_dates_sit_at_the_annual_minimum`` only checks
    that the truth date's value equals the observed minimum -- a tie between
    the truth month and a competing month satisfies that trivially. A family
    that claims ``identifiable=True`` with a specific truth date must have
    exactly one month attaining the annual minimum; otherwise the label is
    unresolvable and any detector choosing the tied competitor is penalised
    for a genuinely ambiguous record.
    """
    for offset in range(len(_TROUGH_GEOMETRY_FAMILIES)):
        record = generate_trough_geometry_record(30000 + offset, partition="calibration")
        for year_offset, date in enumerate(record.truth.trough_date_by_year):
            if date is None or not record.truth.identifiable_by_year[year_offset]:
                continue
            window = record.frame.iloc[year_offset * 12 : (year_offset + 1) * 12]
            observed = window["extent_pct"].dropna()
            if observed.empty:
                continue
            tied_count = int((observed == observed.min()).sum())
            assert tied_count == 1, (
                f"{record.family} year {year_offset}: annual minimum "
                f"{observed.min()!r} is attained by {tied_count} months, not 1 "
                "-- truth date is not a resolvable point trough"
            )


def test_generating_the_geometry_corpus_does_not_perturb_the_frozen_corpora():
    from hydroseason._synthetic import generate_record, generate_timing_identifiability_record

    before_legacy = generate_record(10000, partition="calibration")
    before_timing = generate_timing_identifiability_record(10000, partition="calibration")
    generate_trough_geometry_record(30000, partition="calibration")
    after_legacy = generate_record(10000, partition="calibration")
    after_timing = generate_timing_identifiability_record(10000, partition="calibration")
    pd.testing.assert_frame_equal(before_legacy.frame, after_legacy.frame)
    pd.testing.assert_frame_equal(before_timing.frame, after_timing.frame)
    assert before_legacy.family == after_legacy.family
    assert before_timing.family == after_timing.family
