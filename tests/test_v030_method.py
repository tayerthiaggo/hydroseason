"""hydroseason-v0.3.0 method rules: the trough timing label covers the trough boundary."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from hydroseason import analyze_catchment
from hydroseason._dynamic_year import _reconcile_trough_labels
from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS

DATED = ("point", "interval", "broad")
BOUNDARY_COLUMNS = ["trough_month", "hy_start", "hy_end", "peak_month", "trough_extent_pct", "peak_extent_pct",
                    "status", "boundary_status", "status_reason"]


def _row(label_start: str, label_end: str, status: str, boundary: str = "2010-09-01", peak_status: str = "point"):
    return {
        "hy_year": 2010, "hy_start": pd.Timestamp("2009-10-01"), "hy_end": pd.Timestamp(boundary),
        "trough_month": pd.Timestamp(boundary), "peak_month": pd.Timestamp("2010-03-01"),
        "trough_extent_pct": 4.0, "peak_extent_pct": 30.0, "status": "complete", "boundary_status": "confirmed",
        "status_reason": "ok", "peak_timing_status": peak_status,
        "trough_timing_status": status, "trough_interval_start": pd.Timestamp(label_start),
        "trough_interval_end": pd.Timestamp(label_end), "timing_status": status,
    }


@pytest.mark.parametrize(
    ("label", "expected"),
    [("2010-08-01", "interval"), ("2010-07-01", "interval"), ("2010-06-01", "broad"),
     ("2010-04-01", "broad"), ("2010-03-01", "unresolved")],
)
def test_point_label_on_another_month_is_widened_and_regraded(label, expected):
    rows = pd.DataFrame([_row(label, label, "point")])
    out = _reconcile_trough_labels(rows, TIMING_IDENTIFIABILITY_DEFAULTS)
    assert out.loc[0, "trough_timing_status"] == expected
    assert out.loc[0, "trough_interval_start"] == pd.Timestamp(label)
    assert out.loc[0, "trough_interval_end"] == pd.Timestamp("2010-09-01")
    assert out.loc[0, "timing_status"] == expected
    pd.testing.assert_frame_equal(out[BOUNDARY_COLUMNS], rows[BOUNDARY_COLUMNS])


def test_labels_that_cover_the_boundary_and_unresolved_labels_are_untouched():
    rows = pd.DataFrame([
        _row("2010-09-01", "2010-09-01", "point"),
        _row("2010-08-01", "2010-09-01", "interval"),
        _row("2010-05-01", "2010-09-01", "broad"),
        {**_row("2010-03-01", "2010-03-01", "unresolved"), "trough_interval_start": pd.NaT,
         "trough_interval_end": pd.NaT},
    ])
    out = _reconcile_trough_labels(rows, TIMING_IDENTIFIABILITY_DEFAULTS)
    pd.testing.assert_frame_equal(out, rows)


def test_widened_interval_label_keeps_the_weaker_peak_in_the_aggregate():
    rows = pd.DataFrame([_row("2010-07-01", "2010-08-01", "interval", peak_status="broad")])
    out = _reconcile_trough_labels(rows, TIMING_IDENTIFIABILITY_DEFAULTS)
    assert out.loc[0, "trough_timing_status"] == "interval"  # July to September: 2 months apart
    assert out.loc[0, "trough_interval_end"] == pd.Timestamp("2010-09-01")
    assert out.loc[0, "timing_status"] == "broad"


def _cloudy_trough_record() -> pd.DataFrame:
    """Seasonal record whose lowest dry-season month is cloudy in two years.

    The boundary skips the cloudy month (more than 20% invalid) and lands on the
    clear month after it; the label, which counts cloudy months, singles out the
    cloudy one. Before hydroseason-v0.3.0 the row read ``point`` for a month the
    label did not single out.
    """
    dates = pd.date_range("2005-01-01", periods=15 * 12, freq="MS")
    rng = np.random.default_rng(0)
    values = np.asarray(20.0 + 15.0 * np.cos(2 * np.pi * (dates.month - 3) / 12) + rng.normal(0, 0.3, len(dates)),
                        dtype=float)
    invalid = np.full(len(dates), 5.0)
    for year in (2008, 2012):
        values[dates == f"{year}-09-01"] = 1.0
        invalid[dates == f"{year}-09-01"] = 60.0
        values[dates == f"{year}-10-01"] = 5.5
        values[dates == f"{year}-08-01"] = 8.5
    return pd.DataFrame({"extent_pct": values, "invalid_pct": invalid}, index=dates)


def test_cloud_screened_trough_no_longer_reads_point_for_another_month():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        analysis = analyze_catchment(_cloudy_trough_record(), phase_scheme="two_phase", quality_policy="flag")
    years = analysis.hydro_years.set_index("hy_year")
    for year in (2008, 2012):
        row = years.loc[year]
        assert row["trough_month"] == pd.Timestamp(f"{year}-10-01")
        assert row["trough_timing_status"] == "interval"
        assert (row["trough_interval_start"], row["trough_interval_end"]) == (
            pd.Timestamp(f"{year}-09-01"), pd.Timestamp(f"{year}-10-01"))


def test_every_dated_trough_label_covers_its_boundary():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        analysis = analyze_catchment(_cloudy_trough_record(), phase_scheme="two_phase", quality_policy="flag")
    years = analysis.hydro_years
    dated = years[years["trough_timing_status"].isin(DATED)]
    assert len(dated)
    assert (dated["trough_interval_start"] <= dated["trough_month"]).all()
    assert (dated["trough_month"] <= dated["trough_interval_end"]).all()
