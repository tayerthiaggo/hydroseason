import numpy as np
import pytest

from hydroseason._seasonality_synthetic import (
    SEASONALITY_FAMILIES,
    generate_seasonality_record,
    iter_seasonality_records,
)

_TRUTH_BY_FAMILY = {family.name: family.truth_seasonal for family in SEASONALITY_FAMILIES}


def test_every_record_stays_inside_the_extent_domain():
    for family in SEASONALITY_FAMILIES:
        record = generate_seasonality_record(family=family.name, n_years=15, replicate=0)
        values = record.frame["extent_pct"].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0


# One or two families per truth category (False/True/None), so determinism
# and replicate-independence are not proven by a single family alone.
_FAMILIES_ACROSS_TRUTH_CATEGORIES = (
    "white_noise",  # truth_seasonal=False
    "ar1_0_8",  # truth_seasonal=False
    "sinusoid",  # truth_seasonal=True
    "narrow_pulse",  # truth_seasonal=True
    "two_cycles",  # truth_seasonal=None
    "phase_drift",  # truth_seasonal=None
)


@pytest.mark.parametrize("family", _FAMILIES_ACROSS_TRUTH_CATEGORIES)
def test_records_are_deterministic(family):
    first = generate_seasonality_record(family=family, n_years=15, replicate=3)
    second = generate_seasonality_record(family=family, n_years=15, replicate=3)

    assert first.frame.equals(second.frame)
    assert first.truth == second.truth


@pytest.mark.parametrize("family", _FAMILIES_ACROSS_TRUTH_CATEGORIES)
def test_replicates_differ(family):
    first = generate_seasonality_record(family=family, n_years=15, replicate=0)
    second = generate_seasonality_record(family=family, n_years=15, replicate=1)

    assert not first.frame.equals(second.frame)


def test_truth_labels_match_the_family_table():
    for name, truth in _TRUTH_BY_FAMILY.items():
        record = generate_seasonality_record(family=name, n_years=7, replicate=0)
        assert record.truth.truth_seasonal is truth


def test_zero_dominated_pulse_has_exact_zero_dry_months():
    record = generate_seasonality_record(family="zero_dominated_pulse", n_years=15, replicate=0)
    values = record.frame["extent_pct"].to_numpy(dtype=float)

    assert (values == 0.0).sum() >= 9 * 15 - 1


def test_missing_variant_blanks_the_requested_fraction():
    record = generate_seasonality_record(
        family="white_noise", n_years=30, replicate=0, variant="missing_25"
    )
    invalid = record.frame["invalid_pct"].to_numpy(dtype=float)

    assert 0.2 <= float((invalid == 100.0).mean()) <= 0.3


def test_iteration_covers_families_lengths_and_replicates():
    records = list(
        iter_seasonality_records(lengths=(7,), replicates=2, variants=("base",))
    )

    assert len(records) == len(SEASONALITY_FAMILIES) * 2

    # A count alone would pass even if some combination were yielded twice
    # while another was skipped; every (family, n_years, replicate, variant)
    # combination must be distinct.
    combinations = [
        (
            record.truth.family,
            record.truth.n_years,
            record.truth.replicate,
            record.truth.variant,
        )
        for record in records
    ]
    assert len(set(combinations)) == len(combinations)


def test_unknown_family_is_rejected():
    with pytest.raises(ValueError, match="unknown family"):
        generate_seasonality_record(family="nonsense", n_years=15, replicate=0)


def test_missing_10_variant_blanks_roughly_one_tenth():
    record = generate_seasonality_record(
        family="white_noise", n_years=30, replicate=0, variant="missing_10"
    )
    extent = record.frame["extent_pct"].to_numpy(dtype=float)
    invalid = record.frame["invalid_pct"].to_numpy(dtype=float)

    blanked = np.isnan(extent)
    blanked_fraction = float(blanked.mean())

    # Expect roughly 10% blanked with tolerance band (0.05 to 0.15)
    assert 0.05 <= blanked_fraction <= 0.15
    # Every blanked month must have invalid_pct == 100.0
    assert (invalid[blanked] == 100.0).all()
    # Every unblanked month must have finite extent
    unblanked = ~blanked
    assert np.isfinite(extent[unblanked]).all()


def test_low_state_gap_blanks_around_trough_month():
    # Test with positive family (has trough_month)
    record = generate_seasonality_record(
        family="sinusoid", n_years=15, replicate=0, variant="low_state_gap"
    )
    extent = record.frame["extent_pct"].to_numpy(dtype=float)
    invalid = record.frame["invalid_pct"].to_numpy(dtype=float)

    blanked = np.isnan(extent)
    # Assert some months are blanked (every third year gets 3-month gap)
    assert blanked.sum() > 0
    # Every blanked month has invalid_pct == 100.0
    assert (invalid[blanked] == 100.0).all()

    # Check that blanked months cluster around trough_month
    blanked_months = record.frame.index[blanked].month.values
    trough = record.truth.trough_month
    # Expected window is trough-1, trough, trough+1 (handling month wrapping)
    expected_months = {
        (trough - 2) % 12 + 1,
        (trough - 1) % 12 + 1,
        trough % 12 + 1,
    }
    # All blanked months should be in or near the expected window
    assert all(m in expected_months for m in blanked_months)

    # Test with non-positive family (no trough_month): should be unchanged
    base_record = generate_seasonality_record(
        family="white_noise", n_years=15, replicate=0, variant="base"
    )
    gap_record = generate_seasonality_record(
        family="white_noise", n_years=15, replicate=0, variant="low_state_gap"
    )
    assert base_record.frame.equals(gap_record.frame)


def test_pixel_rounded_scales_extent_correctly():
    base_record = generate_seasonality_record(
        family="sinusoid", n_years=15, replicate=0, variant="base"
    )
    rounded_record = generate_seasonality_record(
        family="sinusoid", n_years=15, replicate=0, variant="pixel_rounded"
    )

    frame = rounded_record.frame
    # Check new columns exist and have expected values
    assert "n_water" in frame.columns
    assert "n_valid" in frame.columns
    assert "n_invalid" in frame.columns
    assert "n_aoi" in frame.columns

    # All n_valid, n_invalid, n_aoi must be constant
    assert (frame["n_valid"] == 1000).all()
    assert (frame["n_invalid"] == 0).all()
    assert (frame["n_aoi"] == 1000).all()

    # extent_pct must be consistent with n_water / n_valid * 100
    extent = frame["extent_pct"].to_numpy(dtype=float)
    n_water = frame["n_water"].to_numpy(dtype=float)
    expected_extent = n_water / 1000.0 * 100.0
    assert np.allclose(extent, expected_extent, rtol=1e-10)

    # Pixel-rounded extents should be scaled down relative to base
    base_extent = base_record.frame["extent_pct"].to_numpy(dtype=float)
    finite_base = base_extent[np.isfinite(base_extent)]
    finite_rounded = extent[np.isfinite(extent)]
    # With scale factor 0.02, max should be ~2% instead of ~55%
    assert finite_rounded.max() < finite_base.max()
