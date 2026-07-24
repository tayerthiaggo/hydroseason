from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest


def _aoi():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import box

    return geopandas.GeoDataFrame(geometry=[box(0, 0, 2, 2)], crs="EPSG:4326")


def _mixed_canonical_cube():
    xr = pytest.importorskip("xarray")
    values = np.resize(np.array([-2, -1, 0, 1], dtype=np.int8), (12, 4, 4))
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": pd.date_range("2020-01-01", periods=12, freq="MS")},
    ).chunk({"time": 1, "y": 2, "x": 2})


def _fake_monthly_cube(start: str, end: str):
    xr = pytest.importorskip("xarray")
    dates = pd.date_range(start, end, freq="MS")
    values = np.ones((len(dates), 2, 2), dtype=np.int8)
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": dates, "y": [0, 1], "x": [0, 1]},
    )


def _fake_wet_aoi():
    # A minimal real GeoDataFrame (not a bare sentinel) so it can pass through
    # monthly_water_extent's wet_aoi rasterisation unchanged, while identity
    # ("is this the same object that came out of compute_wet_aoi/was passed
    # in explicitly?") is still trackable via `is`/`==` through the pipeline.
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    return gpd.GeoDataFrame({"geometry": [box(-10, -10, 10, 10)]}, geometry="geometry", crs=None)


def test_offline_cache_hit_performs_zero_stac_calls(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio

    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    cube = _mixed_canonical_cube()
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=handle))
    monkeypatch.setattr(hio, "open_completed_mask_cache", Mock(return_value=cube))
    monkeypatch.setattr(hio, "_query_wofs_items", Mock(side_effect=AssertionError("network")), raising=False)

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2020-01-01", "2020-12-31", resolution=30,
        mask_cache_dir=tmp_path, offline=True,
    )

    assert len(result) == 12


def test_offline_cache_miss_is_explicit(tmp_path):
    import hydroseason.io as hio

    with pytest.raises(FileNotFoundError, match="offline WOfS cache miss"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2020-01-01", "2020-12-31", resolution=30,
            mask_cache_dir=tmp_path, offline=True,
        )


def test_offline_without_mask_cache_dir_is_explicit():
    import hydroseason.io as hio

    with pytest.raises(FileNotFoundError, match="offline WOfS cache miss"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2020-01-01", "2020-12-31", resolution=30, offline=True,
        )


def test_offline_without_mask_cache_dir_still_uses_complete_csv_cache(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    load = Mock(return_value=_fake_monthly_cube("2020-01-01", "2020-12-01"))
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-01-01",
        end_date="2020-12-31",
        resolution=30,
        cache_dir=tmp_path / "extent_cache",
    )
    expected = hio.load_wofs_monthly_extent(**kwargs)

    monkeypatch.setattr(
        hio,
        "acquire_wofs_cache",
        Mock(side_effect=AssertionError("canonical acquisition must not run")),
    )
    actual = hio.load_wofs_monthly_extent(**kwargs, offline=True)

    assert load.call_count == 1
    pd.testing.assert_frame_equal(actual, expected, check_freq=False)


def test_canonical_cache_extent_is_exactly_equal_to_legacy(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.hydro_year import monthly_water_extent

    cube = _mixed_canonical_cube()
    expected = monthly_water_extent(cube, time_block=3)
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=handle))
    monkeypatch.setattr(hio, "open_completed_mask_cache", Mock(return_value=cube))

    actual = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2020-01-01", "2020-12-31", resolution=30,
        mask_cache_dir=tmp_path,
    )

    pd.testing.assert_frame_equal(actual, expected)


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


def test_tile_extent_aggregation_sums_counts_then_recomputes_percentages():
    from hydroseason._io_extent_cache import _aggregate_extent_parts

    index = pd.DatetimeIndex(["2020-01-01"])
    left = pd.DataFrame({
        "n_water": [3], "n_aoi": [8], "n_valid": [6], "n_invalid": [2],
        "n_wet_aoi": [8], "extent_pct": [50.0], "invalid_pct": [25.0],
        "wet_fill_pct": [37.5],
    }, index=index)
    right = pd.DataFrame({
        "n_water": [1], "n_aoi": [2], "n_valid": [2], "n_invalid": [0],
        "n_wet_aoi": [2], "extent_pct": [50.0], "invalid_pct": [0.0],
        "wet_fill_pct": [50.0],
    }, index=index)

    result = _aggregate_extent_parts([left, right], index)

    assert result.loc[index[0], "n_water"] == 4
    assert result.loc[index[0], "n_valid"] == 8
    assert result.loc[index[0], "n_invalid"] == 2
    assert result.loc[index[0], "n_aoi"] == 10
    assert result.loc[index[0], "n_wet_aoi"] == 10
    assert result.loc[index[0], "extent_pct"] == 50.0
    assert result.loc[index[0], "invalid_pct"] == 20.0
    assert result.loc[index[0], "wet_fill_pct"] == 40.0
    assert result.loc[index[0], "n_aoi"] == (
        result.loc[index[0], "n_valid"] + result.loc[index[0], "n_invalid"]
    )


def test_tile_extent_aggregation_keeps_empty_month_percentages_nan():
    from hydroseason._io_extent_cache import _aggregate_extent_parts

    index = pd.DatetimeIndex(["2020-01-01"])
    result = _aggregate_extent_parts([], index)

    assert (result[["n_water", "n_aoi", "n_valid", "n_invalid", "n_wet_aoi"]] == 0).all().all()
    assert result[["extent_pct", "invalid_pct", "wet_fill_pct"]].isna().all().all()


def test_tiled_extent_resume_skips_completed_tiles(monkeypatch, tmp_path):
    import hydroseason.io as hio

    calls = []
    fail_once = {"value": True}

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        calls.append(set(skip_tile_ids))
        for tile_id in ["r0000_c0000", "r0000_c0001", "r0001_c0000"]:
            if tile_id in skip_tile_ids:
                continue
            if tile_id == "r0001_c0000" and fail_once["value"]:
                fail_once["value"] = False
                raise RuntimeError("interrupted")
            yield tile_id, _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        hio.load_wofs_monthly_extent(**kwargs)
    result = hio.load_wofs_monthly_extent(**kwargs)

    assert calls[0] == set()
    assert calls[1] == {"r0000_c0000", "r0000_c0001"}
    assert (result["n_water"] == 12).all()


def test_tiled_extent_no_data_year_continues_to_next_year(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(_url, _collection, _aoi, start, _end, **kwargs):
        if start.startswith("2020"):
            raise ValueError("No STAC items found for requested AOI and date range.")
        yield "r0000_c0000", _fake_monthly_cube("2021-01-01", "2021-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac",
        "wofs",
        object(),
        "2020-01-01",
        "2021-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    assert len(result) == 24
    assert (result.loc["2020", "n_valid"] == 0).all()
    assert result.loc["2020", "extent_pct"].isna().all()
    assert (result.loc["2021", "n_valid"] == 4).all()
    assert (result.loc["2021", "n_water"] == 4).all()


def test_tiled_extent_zero_tiles_yielded_raises_and_does_not_cache(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        return
        yield  # pragma: no cover - makes this a generator function that yields nothing

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    cache_dir = tmp_path / "cache"
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=cache_dir,
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    with pytest.raises(ValueError, match="no tiles were produced"):
        hio.load_wofs_monthly_extent(**kwargs)

    assert not cache_dir.exists() or list(cache_dir.glob("*.csv")) == []


def test_tiled_extent_per_tile_value_error_propagates_uncached(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        # A tile whose reduced monthly index doesn't match the expected year
        # window -- this triggers the "unexpected monthly index" ValueError
        # inside the reduction loop, not from the generator/STAC query itself.
        yield "r0000_c0000", _fake_monthly_cube("2020-06-01", "2020-08-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    cache_dir = tmp_path / "cache"
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=cache_dir,
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    with pytest.raises(ValueError, match="unexpected monthly index"):
        hio.load_wofs_monthly_extent(**kwargs)

    assert not cache_dir.exists() or list(cache_dir.glob("*.csv")) == []


def test_tiled_extent_force_ignores_annual_and_tile_caches(monkeypatch, tmp_path):
    import hydroseason.io as hio

    calls = []

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        calls.append(set(skip_tile_ids))
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    hio.load_wofs_monthly_extent(**kwargs)
    hio.load_wofs_monthly_extent(**kwargs)
    hio.load_wofs_monthly_extent(**kwargs, force=True)

    assert len(calls) == 2
    assert calls[0] == set()
    assert calls[1] == set()


def test_cache_path_depends_on_wet_aoi_hash(tmp_path):
    from hydroseason._io_extent_cache import _cache_path

    common = dict(
        cache_dir=tmp_path, stac_url="s", collection="c", aoi_hash="a",
        start=pd.Timestamp("2020-01-01"), end=pd.Timestamp("2020-12-31"),
        crs=3577, resolution=30.0, majority=True,
    )
    p_none = _cache_path(**common, wet_aoi_hash="")
    p_wet = _cache_path(**common, wet_aoi_hash="deadbeef")
    assert p_none != p_wet  # wet AOI is data-affecting -> distinct cache file


def test_cache_path_wet_aoi_hash_defaults_to_empty(tmp_path):
    # Default (no wet_aoi_hash kwarg) must match explicitly passing "" so that
    # pre-Task-5 callers of _cache_path (no wet AOI involved) are unaffected.
    from hydroseason._io_extent_cache import _cache_path

    common = dict(
        cache_dir=tmp_path, stac_url="s", collection="c", aoi_hash="a",
        start=pd.Timestamp("2020-01-01"), end=pd.Timestamp("2020-12-31"),
        crs=3577, resolution=30.0, majority=True,
    )
    assert _cache_path(**common) == _cache_path(**common, wet_aoi_hash="")


def test_precompute_requires_tile_pixels(tmp_path):
    from hydroseason._io_extent_cache import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="precompute_wet_aoi requires tile_pixels"):
        load_wofs_monthly_extent(
            "https://example.invalid/stac", "wofs", aoi, "2020-01-01", "2020-12-31",
            cache_dir=tmp_path / "cache", resolution=30.0,
            precompute_wet_aoi=True,  # no tile_pixels -> error
        )


def test_precompute_wet_aoi_runs_full_ts_pass_and_threads_into_tiles(monkeypatch, tmp_path):
    import hydroseason.io as hio

    full_ts_calls = []
    compute_wet_aoi_calls = []
    tile_calls = []

    sentinel_wet_aoi = _fake_wet_aoi()

    def fake_load_full_ts(_url, _collection, _aoi, start, end, **kwargs):
        full_ts_calls.append((start, end))
        return _fake_monthly_cube(start, end)

    def fake_compute_wet_aoi(mask, **kwargs):
        compute_wet_aoi_calls.append(kwargs)
        return sentinel_wet_aoi

    def fake_tiles(*args, wet_aoi=None, skip_tile_ids=(), **kwargs):
        tile_calls.append(wet_aoi)
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load_full_ts)
    monkeypatch.setattr(hio, "compute_wet_aoi", fake_compute_wet_aoi)
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", object(),
        "2020-01-01", "2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        precompute_wet_aoi=True,
        persistence_min=0.25,
        close_m=100.0,
        buffer_m=200.0,
    )

    # One full-time-series pass over the whole requested window.
    assert full_ts_calls == [("2020-01-01", "2020-12-31")]
    # compute_wet_aoi received the precompute knobs.
    assert compute_wet_aoi_calls == [
        {"persistence_min": 0.25, "close_m": 100.0, "buffer_m": 200.0}
    ]
    # The computed wet AOI is threaded into the tiled per-year load.
    assert tile_calls == [sentinel_wet_aoi]
    assert (result["n_water"] == 4).all()
    assert "wet_fill_pct" in result.columns


def test_wet_aoi_passed_explicitly_skips_precompute_pass_but_does_not_prune_tiles(
    monkeypatch, tmp_path
):
    """An externally-supplied ``wet_aoi`` (no ``precompute_wet_aoi``) still
    skips the internal precompute pass (no redundant full-TS STAC call), but
    -- per Task 8's fix -- must NOT be threaded into
    ``iter_wofs_tiles_from_stac`` as a pruning gate, because there is no
    ``full_ts`` cube here to reconcile the tiled aggregate's denominator
    against if a tile were skipped. This replaces a prior version of this
    test that asserted ``tile_calls == [explicit_wet_aoi]`` -- that assertion
    was exercising exactly the denominator-shrinkage bug Task 8 fixes, not a
    correct contract worth preserving.

    ``n_wet_aoi``/``wet_fill_pct`` are a separate concern with no such
    problem (they only ever read pixels from tiles actually loaded), so the
    real ``wet_aoi`` must still reach ``monthly_water_extent`` for that
    calculation -- verified via ``monthly_water_extent_calls`` below.
    """
    import hydroseason._io_extent_cache as extent_cache
    import hydroseason.io as hio

    full_ts_calls = []
    tile_calls = []
    monthly_water_extent_calls = []
    explicit_wet_aoi = _fake_wet_aoi()

    def fake_load_full_ts(*args, **kwargs):
        full_ts_calls.append(args)
        raise AssertionError("full-TS pass must not run when wet_aoi is already given")

    def fake_tiles(*args, wet_aoi=None, skip_tile_ids=(), **kwargs):
        tile_calls.append(wet_aoi)
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    real_monthly_water_extent = extent_cache.monthly_water_extent

    def spying_monthly_water_extent(*args, **kwargs):
        monthly_water_extent_calls.append(kwargs.get("wet_aoi"))
        return real_monthly_water_extent(*args, **kwargs)

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load_full_ts)
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    monkeypatch.setattr(extent_cache, "monthly_water_extent", spying_monthly_water_extent)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", object(),
        "2020-01-01", "2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        wet_aoi=explicit_wet_aoi,
    )

    assert full_ts_calls == []
    # Pruning gate: disabled (falls back to None) since there is no full_ts.
    assert tile_calls == [None]
    # n_wet_aoi/wet_fill_pct calculation: still uses the real, caller-supplied
    # wet_aoi, since that computation has no missing-tile denominator problem.
    assert monthly_water_extent_calls == [explicit_wet_aoi]


def test_untiled_path_threads_caller_supplied_wet_aoi_into_wet_fill_pct(monkeypatch, tmp_path):
    """Finding 2 regression: wet_aoi given without tile_pixels must still flow
    into monthly_water_extent on the untiled branch, so wet_fill_pct reflects
    the real wet AOI instead of silently falling back to n_valid/extent_pct.
    """
    pytest.importorskip("dask")
    xr = pytest.importorskip("xarray")
    pytest.importorskip("rasterio")
    pytest.importorskip("rioxarray")
    gpd = pytest.importorskip("geopandas")
    import rioxarray  # noqa: F401  (registers the .rio accessor)
    from shapely.geometry import box

    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    # 4x4 grid, one wet pixel; wet AOI covers only the top-left quadrant, so
    # n_wet_aoi (4) differs from n_valid (16) and wet_fill_pct != extent_pct.
    def fake_load(_url, _collection, _aoi, start, end, **kwargs):
        dates = pd.date_range(start, end, freq="MS")
        cube = np.zeros((len(dates), 4, 4), dtype=np.int8)
        cube[:, 0, 0] = 1
        masks = xr.DataArray(
            cube,
            dims=("time", "y", "x"),
            coords={
                "time": dates,
                "y": np.arange(4) * -30.0,
                "x": np.arange(4) * 30.0,
            },
        ).chunk({"time": 1, "y": 4, "x": 4})
        return masks.rio.write_crs("EPSG:3577")

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load)

    wet_aoi = gpd.GeoDataFrame(
        {"geometry": [box(-15, -75, 45, 15)]}, geometry="geometry", crs="EPSG:3577"
    )

    result = load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-01-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        wet_aoi=wet_aoi,
    )

    row = result.loc[pd.Timestamp("2020-01-01")]
    assert row["n_valid"] == 16
    # The wet AOI covers only part of the grid, so n_wet_aoi must differ from
    # n_valid/n_aoi -- proving the untiled branch actually rasterised the
    # real, caller-supplied wet_aoi rather than silently aliasing n_wet_aoi
    # to n_valid (the pre-fix, no-wet-AOI fallback behaviour).
    assert 0 < row["n_wet_aoi"] < 16
    assert row["wet_fill_pct"] == pytest.approx(100.0 * row["n_water"] / row["n_wet_aoi"])
    assert row["extent_pct"] == pytest.approx(6.25)
    assert row["wet_fill_pct"] != row["extent_pct"]


def test_different_wet_aoi_produces_different_cache_file(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(*args, wet_aoi=None, skip_tile_ids=(), **kwargs):
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    cache_dir = tmp_path / "cache"
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=cache_dir,
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    hio.load_wofs_monthly_extent(**kwargs, wet_aoi=None)
    files_without_wet_aoi = set(cache_dir.glob("extent_*.csv"))

    hio.load_wofs_monthly_extent(**kwargs, wet_aoi=_fake_wet_aoi())
    files_with_wet_aoi = set(cache_dir.glob("extent_*.csv")) - files_without_wet_aoi

    assert files_with_wet_aoi  # a new, distinct annual cache file was written


def _write_box_aoi(tmp_path, name, *, crs, span_m):
    """Write a square AOI GeoJSON `span_m` metres per side in the given CRS."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        {"geometry": [box(0, 0, span_m, span_m)]}, geometry="geometry", crs=crs
    )
    path = tmp_path / name
    gdf.to_file(path, driver="GeoJSON")
    return path


def test_auto_tiling_degrades_single_tile_aoi_to_untiled_path(monkeypatch, tmp_path):
    """An AOI smaller than one tile skips precompute and the tiled iterator,
    taking the plain untiled read instead (bit-identical, no double-read)."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    # 5 km AOI at 30 m with tile_pixels=2048 => one tile spans ~61 km >> 5 km.
    aoi = _write_box_aoi(tmp_path, "small.geojson", crs="EPSG:3577", span_m=5_000)

    untiled = Mock(side_effect=lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end))
    tiles = Mock(side_effect=lambda *a, **k: iter(()))
    monkeypatch.setattr(hio, "load_wofs_from_stac", untiled)
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", tiles)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
    )

    assert untiled.called  # took the untiled whole-AOI read
    assert not tiles.called  # never touched the tiled iterator


def test_auto_tiling_keeps_tiled_path_for_multi_tile_aoi(monkeypatch, tmp_path):
    """An AOI larger than one tile keeps the tiled+precompute path."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    # 200 km AOI at 30 m with tile_pixels=2048 => spans many ~61 km tiles.
    aoi = _write_box_aoi(tmp_path, "big.geojson", crs="EPSG:3577", span_m=200_000)

    monkeypatch.setattr(
        hio, "load_wofs_from_stac",
        lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end),
    )
    monkeypatch.setattr(hio, "compute_wet_aoi", lambda mask, **k: _fake_wet_aoi())
    tiles = Mock(side_effect=lambda *a, **k: iter(
        [("r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01"))]
    ))
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", tiles)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
    )

    assert tiles.called  # kept the tiled path for a genuinely multi-tile AOI


def test_auto_tiling_false_forces_tiled_path_even_for_small_aoi(monkeypatch, tmp_path):
    """auto_tiling=False keeps the requested tiled path regardless of AOI size."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    aoi = _write_box_aoi(tmp_path, "small2.geojson", crs="EPSG:3577", span_m=5_000)

    monkeypatch.setattr(
        hio, "load_wofs_from_stac",
        lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end),
    )
    monkeypatch.setattr(hio, "compute_wet_aoi", lambda mask, **k: _fake_wet_aoi())
    tiles = Mock(side_effect=lambda *a, **k: iter(
        [("r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01"))]
    ))
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", tiles)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
        auto_tiling=False,
    )

    assert tiles.called  # opt-out respected: tiled path forced


def test_read_workers_threads_into_reduction_and_leaves_result_unchanged(monkeypatch, tmp_path):
    """read_workers reaches monthly_water_extent and does not alter output."""
    pytest.importorskip("dask")
    import hydroseason.hydro_year as hy
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    monkeypatch.setattr(
        hio, "load_wofs_from_stac",
        lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end),
    )

    seen_workers = []
    real_reduce = hy.monthly_water_extent

    def spy_reduce(*args, read_workers=None, **kwargs):
        seen_workers.append(read_workers)
        return real_reduce(*args, read_workers=read_workers, **kwargs)

    # The cache module imported the name directly, so patch it there.
    monkeypatch.setattr("hydroseason._io_extent_cache.monthly_water_extent", spy_reduce)

    kwargs = dict(
        stac_url="https://example.invalid/stac", collection="wofs", aoi=aoi,
        start_date="2020-11-01", end_date="2021-02-28", resolution=100,
    )
    default_run = load_wofs_monthly_extent(**kwargs)
    tuned_run = load_wofs_monthly_extent(**kwargs, read_workers=8)

    # Default is None (profiling found forcing a worker count hurts this
    # workload -- see load_wofs_monthly_extent's read_workers docstring);
    # an explicit override still threads through when the caller opts in.
    assert None in seen_workers
    assert 8 in seen_workers
    # Concurrency is a scheduler detail only: identical numbers out.
    pd.testing.assert_frame_equal(default_run, tuned_run, check_freq=False)
