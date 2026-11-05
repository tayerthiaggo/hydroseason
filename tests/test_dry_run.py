"""Where the dry season ends (DE1 rule, hydroseason-v0.3.0): the dry run and the moved boundary."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import hydroseason._dynamic_year as dynamic_year
from hydroseason import analyze_catchment
from hydroseason._dry_run import DryRun, find_dry_run

DATED = ("point", "interval", "broad")


def _frame(values, *, cloudy=()):
    """A prepared monthly frame: tolerance is min(0.1 * 10, max(100 / 1000, 0.5)) = 0.5 pp."""
    dates = pd.date_range("2010-01-01", periods=len(values), freq="MS")
    quality = ["usable"] * len(values)
    for i in cloudy:
        quality[i] = "invalid"
    return pd.DataFrame(
        {"extent_pct": np.asarray(values, dtype=float), "quality_state": quality, "n_valid": 1000.0},
        index=dates,
    )


def _run(values, boundary, *, cloudy=(), **limits) -> DryRun:
    frame = _frame(values, cloudy=cloudy)
    return find_dry_run(frame, frame.index[boundary], noise_pp=0.5, amplitude_pp=10.0, **limits)


def _month(i: int) -> pd.Timestamp:
    return pd.date_range("2010-01-01", periods=i + 1, freq="MS")[-1]


def test_flat_run_ends_the_month_before_water_returns():
    run = _run([9, 0, 0, 0.3, 0, 0, 8, 9], boundary=1)
    assert (run.start, run.end, run.rewetting) == (_month(1), _month(5), _month(6))
    assert run.end_status == "interval"
    assert run.months == 5


def test_run_extends_backwards_and_never_reports_point():
    run = _run([9, 0, 0, 0, 7], boundary=3)
    assert (run.start, run.end) == (_month(1), _month(3))
    assert run.end_status == "interval"


def test_cloudy_month_neither_extends_nor_ends_the_run():
    run = _run([9, 0, 0, 30, 0, 8], boundary=1, cloudy=(3,))
    assert (run.end, run.rewetting) == (_month(4), _month(5))


def test_cloud_hidden_rewetting_leaves_a_gap():
    run = _run([9, 0, 0, 30, 8], boundary=1, cloudy=(3,))
    assert (run.end, run.rewetting) == (_month(2), _month(4))
    assert run.end_status == "interval"


def test_mid_dry_pulse_ends_the_run():
    run = _run([9, 0, 0, 2, 0, 0, 8], boundary=1)
    assert (run.end, run.rewetting) == (_month(2), _month(3))


def test_record_that_ends_dry_is_censored():
    run = _run([9, 0, 0, 0], boundary=1)
    assert (run.end, run.rewetting, run.end_status) == (_month(3), None, "censored")


def test_cloudy_next_peak_stops_the_run():
    values = [9, 0, 0, 0, 0, 0, 0]
    run = _run(values, boundary=1, cloudy=(4,), next_peak=_month(4))
    assert (run.end, run.rewetting, run.end_status) == (_month(3), _month(4), "interval")
    # An observed month is judged on its extent, peak or not.
    run = _run(values, boundary=1, next_peak=_month(4))
    assert run.end == _month(6)


def test_missing_boundary_is_unavailable():
    frame = _frame([1, 0, 0])
    assert find_dry_run(frame, None, noise_pp=0.5, amplitude_pp=10.0).end_status == "unavailable"
    assert find_dry_run(frame, pd.NaT, noise_pp=0.5, amplitude_pp=10.0) == DryRun.unavailable()


ONSET_SHIFT = [0, 2, -1, 1, -2, 2, 0, -1, 2, 1, -2, 0, 2, -1, 1]


def _ephemeral_record(years: int = 15, seed: int = 0) -> pd.DataFrame:
    """Dry all year except a short wet season whose onset moves between years.

    Onset (0.6 of the peak) in February shifted by up to two months, then the
    peak (1.0), 0.5 and a 0.2 tail. Dry months are exactly zero, as in DE1's
    construction check; noise on a flat bottom ends the run early (DE1's main
    remaining error) and is not tested here.
    """
    dates = pd.date_range("2005-01-01", periods=years * 12, freq="MS")
    rng = np.random.default_rng(seed)
    wet = np.zeros(len(dates))
    for year in range(years):
        onset = year * 12 + 1 + ONSET_SHIFT[year % len(ONSET_SHIFT)]
        for offset, level in enumerate((0.6, 1.0, 0.5, 0.2)):
            if 0 <= onset + offset < len(dates):
                wet[onset + offset] = level
    values = 40.0 * wet * np.exp(rng.normal(0, 0.1, len(dates)))
    return pd.DataFrame({"extent_pct": values, "invalid_pct": np.full(len(dates), 2.0)}, index=dates)


def _onsets(years: int = 15) -> list[pd.Timestamp]:
    dates = pd.date_range("2005-01-01", periods=years * 12, freq="MS")
    return [dates[year * 12 + 1 + ONSET_SHIFT[year]] for year in range(years) if year * 12 + 1 + ONSET_SHIFT[year] >= 0]


def _analyse(record: pd.DataFrame):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return analyze_catchment(record, phase_scheme="two_phase", quality_policy="flag")


def test_ephemeral_dry_season_ends_the_month_before_the_onset():
    years = _analyse(_ephemeral_record()).hydro_years
    onsets = _onsets()
    checked = 0
    for _, row in years.iterrows():
        if pd.isna(row["peak_month"]) or pd.isna(row["dry_run_end_month"]):
            continue
        following = [o for o in onsets if o > row["trough_month"] - pd.DateOffset(months=1)]
        if not following:
            continue
        onset = following[0]
        assert row["dry_run_end_month"] == onset - pd.DateOffset(months=1)
        assert row["rewetting_month"] == onset
        checked += 1
    assert checked >= 10
    moved = years[years["dry_run_boundary_status"] == "moved"]
    assert len(moved) >= 3
    assert (moved["trough_month"] == moved["dry_run_end_month"]).all()
    assert (moved["boundary_shift_months"] > 0).all()
    expected = moved["dry_end_status"].map({"interval": "interval", "censored": "unresolved"})
    assert (moved["trough_timing_status"] == expected).all()
    assert (moved["dry_end_status"] == "interval").sum() >= 3


def test_dry_end_status_is_never_point_and_dated_labels_cover_the_boundary():
    years = _analyse(_ephemeral_record(seed=3)).hydro_years
    assert set(years["dry_end_status"]) <= {"interval", "censored", "unavailable"}
    dated = years[years["trough_timing_status"].isin(DATED)]
    assert (dated["trough_interval_start"] <= dated["trough_month"]).all()
    assert (dated["trough_month"] <= dated["trough_interval_end"]).all()


def test_moving_boundaries_moves_no_peak(monkeypatch):
    record = _ephemeral_record(seed=5)
    after = _analyse(record).hydro_years
    monkeypatch.setattr(dynamic_year, "_apply_dry_run_end", lambda frame, rows, *args: rows)
    before = _analyse(record).hydro_years
    assert after["hy_year"].tolist() == before["hy_year"].tolist()
    pd.testing.assert_series_equal(after["peak_month"], before["peak_month"])
    shifted = after["trough_month"] != before["trough_month"]
    assert shifted.any()
    assert (after.loc[shifted, "dry_run_boundary_status"] == "moved").all()
    assert (after.loc[shifted, "trough_month"] > before.loc[shifted, "trough_month"]).all()


def test_every_boundary_outcome_is_documented():
    outcomes = set()
    for seed in (0, 3, 5):
        outcomes |= set(_analyse(_ephemeral_record(seed=seed)).hydro_years["dry_run_boundary_status"])
    assert outcomes <= set(dynamic_year.DRY_RUN_BOUNDARY_OUTCOMES)
    assert "moved" in outcomes
