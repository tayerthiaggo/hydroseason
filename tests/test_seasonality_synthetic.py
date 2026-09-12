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


def test_records_are_deterministic():
    first = generate_seasonality_record(family="sinusoid", n_years=15, replicate=3)
    second = generate_seasonality_record(family="sinusoid", n_years=15, replicate=3)

    assert first.frame.equals(second.frame)
    assert first.truth == second.truth


def test_replicates_differ():
    first = generate_seasonality_record(family="white_noise", n_years=15, replicate=0)
    second = generate_seasonality_record(family="white_noise", n_years=15, replicate=1)

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


def test_unknown_family_is_rejected():
    with pytest.raises(ValueError, match="unknown family"):
        generate_seasonality_record(family="nonsense", n_years=15, replicate=0)
