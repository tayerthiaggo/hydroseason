from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest


def _fake_monthly_cube(start: str, end: str):
    xr = pytest.importorskip("xarray")
    dates = pd.date_range(start, end, freq="MS")
    values = np.ones((len(dates), 2, 2), dtype=np.int8)
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": dates, "y": [0, 1], "x": [0, 1]},
    )


def test_cached_extent_reuses_completed_calendar_years(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    def fake_load(_url, _collection, _aoi, start, end, **kwargs):
        return _fake_monthly_cube(start, end)

    load = Mock(side_effect=fake_load)
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-11-01",
        end_date="2021-02-28",
        cache_dir=tmp_path / "cache",
        resolution=100,
    )
    first = load_wofs_monthly_extent(**kwargs)
    second = load_wofs_monthly_extent(**kwargs)
    forced = load_wofs_monthly_extent(**kwargs, force=True)

    assert load.call_count == 4
    assert list(first.index) == list(pd.date_range("2020-11-01", "2021-02-01", freq="MS"))
    pd.testing.assert_frame_equal(first, second, check_freq=False)
    pd.testing.assert_frame_equal(first, forced, check_freq=False)


def test_cached_extent_is_invalidated_when_resolution_changes(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    load = Mock(side_effect=lambda _u, _c, _a, start, end, **kw: _fake_monthly_cube(start, end))
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    common = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
    )
    load_wofs_monthly_extent(**common, resolution=100)
    load_wofs_monthly_extent(**common, resolution=30)

    assert load.call_count == 2


def test_year_without_stac_items_becomes_unusable_months(monkeypatch):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    def fake_load(_url, _collection, _aoi, start, end, **kwargs):
        if start.startswith("2020"):
            raise ValueError("No STAC items found for requested AOI and date range.")
        return _fake_monthly_cube(start, end)

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load)

    extent = load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", object(),
        "2020-01-01", "2021-12-31", resolution=100,
    )

    assert len(extent) == 24
    assert (extent.loc["2020", "n_valid"] == 0).all()
    assert extent.loc["2020", "extent_pct"].isna().all()
    assert (extent.loc["2021", "n_valid"] == 4).all()
