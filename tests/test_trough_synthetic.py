import pytest

from scripts.trough_synthetic import build_record, truth_trough_months


def test_stable_record_reproduces_the_judgement_counterexample():
    values, frame = build_record("stable", seed=0)

    assert values.shape == (12, 12)
    assert len(frame) == 144
    assert truth_trough_months(values) == [9] * 12
    # Flood years from the judgement package at seed 0, one-based.
    flood_years = [year + 1 for year in range(12) if values[year].max() > 30.0]
    assert flood_years == [3, 5, 6, 9, 10]
    assert frame["invalid_pct"].eq(0.0).all()
    assert list(frame.columns) == ["extent_pct", "invalid_pct"]


def test_drift_troughs_are_not_all_the_same_month():
    values, _ = build_record("drift", seed=0)

    assert len(set(truth_trough_months(values))) > 1


def test_uniform_record_moves_both_extrema():
    values, _ = build_record("uniform", seed=0, flood_rate=0.0)

    peaks = (values.argmax(axis=1) + 1).tolist()
    assert len(set(truth_trough_months(values))) > 1
    assert len(set(peaks)) > 1


def test_gap_modes_mark_dropped_months_fully_invalid():
    _, frame = build_record("stable", seed=0, gap="dry20")

    dropped = frame["extent_pct"].isna()
    assert dropped.any()
    assert frame.loc[dropped, "invalid_pct"].eq(100.0).all()
    assert set(frame.index[dropped].month) <= {7, 8, 9, 10}


def test_counts_are_consistent_with_extent():
    _, frame = build_record("stable", seed=0, gap="random20", counts=True)

    assert (frame["n_valid"] + frame["n_invalid"]).eq(frame["n_aoi"]).all()
    assert (frame["n_water"] <= frame["n_valid"]).all()
    assert frame.loc[frame["extent_pct"].isna(), "n_valid"].eq(0).all()


def test_stable_sharp_has_a_fixed_trough_and_one_sharp_peak_per_year():
    values, _ = build_record("stable_sharp", seed=0, years=30, flood_rate=0.0)

    assert truth_trough_months(values) == [9] * 30
    assert (values.max(axis=1) == 25.0).all()
    assert len(set((values.argmax(axis=1) + 1).tolist())) > 1


def test_wet_gap_mode_drops_only_wet_season_months():
    _, frame = build_record("stable", seed=0, gap="wet20")

    dropped = frame["extent_pct"].isna()
    assert dropped.any()
    assert set(frame.index[dropped].month) <= {12, 1, 2, 3}


def test_unknown_construction_and_gap_are_rejected():
    with pytest.raises(ValueError):
        build_record("tidal", seed=0)
    with pytest.raises(ValueError):
        build_record("stable", seed=0, gap="fog20")
