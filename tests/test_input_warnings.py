"""Warnings that tell a caller their input is being read differently than they may expect."""
from __future__ import annotations

import inspect
import warnings

import numpy as np
import pandas as pd
import pytest

from hydroseason import analyze_catchment
from hydroseason._state_input import prepare_monthly_extent


def _counts(extent_pct=None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {"n_water": [20, 30], "n_valid": [80, 60], "n_invalid": [20, 40], "n_aoi": [100, 100]},
        index=pd.to_datetime(["2020-01-01", "2020-02-01"]),
    )
    if extent_pct is not None:
        frame["extent_pct"] = extent_pct
    return frame


def test_counts_replace_a_whole_aoi_percentage_with_a_warning():
    # 20 and 30 are wet shares of the whole AOI; the observed shares are 25 and 50.
    with pytest.warns(UserWarning, match=r"recomputed as 100 \* n_water / n_valid") as caught:
        result = prepare_monthly_extent(_counts([20.0, 30.0]))
    assert "differs in 2 of 2 months" in str(caught[0].message)
    assert "largest difference 20 percentage points" in str(caught[0].message)
    assert result["extent_pct"].tolist() == pytest.approx([25.0, 50.0])


def test_counts_with_a_matching_or_absent_percentage_do_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        prepare_monthly_extent(_counts([25.0, 50.0 + 1e-12]))
        prepare_monthly_extent(_counts())


def _pulse_extent() -> pd.Series:
    """Twelve dry years with a tiny three-month pulse: no month-to-month noise."""
    dates = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    pulse = {1: 0.002, 2: 0.004, 3: 0.002}
    return pd.Series([pulse.get(d.month, 0.0) for d in dates], index=dates, dtype=float)


def _floor_warnings(caught) -> list[str]:
    return [str(w.message) for w in caught if "detectability floor" in str(w.message)]


def test_a_floor_collapsed_by_missing_counts_warns():
    extent = _pulse_extent()
    frame = pd.DataFrame({"extent_pct": extent, "invalid_pct": 0.0})
    with pytest.warns(UserWarning, match="detectability floor of effectively zero") as caught:
        analysis = analyze_catchment(frame, n_bootstrap=20)
    years = len(analysis.hydro_years)
    floors = analysis.hydro_years["detectability_floor_pp"].dropna()
    assert analysis.route == "per_year_detection" and len(floors) > 0
    assert (floors < 1e-9).all()
    assert f"{len(floors)} of {years} hydrological years" in _floor_warnings(caught)[0]


def test_counts_or_a_tolerance_keep_the_floor_and_stay_quiet():
    extent = _pulse_extent()
    n_aoi = 1_000_000
    counts = pd.DataFrame({
        "n_water": np.round(extent.to_numpy() / 100 * n_aoi).astype(int),
        "n_valid": n_aoi, "n_invalid": 0, "n_aoi": n_aoi,
    }, index=extent.index)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with_counts = analyze_catchment(counts, n_bootstrap=20)
        with_tolerance = analyze_catchment(
            pd.DataFrame({"extent_pct": extent, "invalid_pct": 0.0}),
            n_bootstrap=20,
            measurement_tolerance_pct=0.001,
        )
    assert _floor_warnings(caught) == []
    assert (with_counts.hydro_years["detectability_floor_pp"].dropna() >= 1e-4 - 1e-12).all()
    assert (with_tolerance.hydro_years["detectability_floor_pp"].dropna() >= 0.001 - 1e-12).all()


def test_analyze_catchment_keeps_its_public_signature():
    params = inspect.signature(analyze_catchment).parameters
    assert list(params)[:3] == ["extent", "value_col", "date_col"]
    assert params["measurement_tolerance_pct"].default == 0.0
    assert analyze_catchment.__name__ == "analyze_catchment"
    assert "Assess regime" in (analyze_catchment.__doc__ or "")
