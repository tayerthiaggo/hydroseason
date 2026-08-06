from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("dask")
pytest.importorskip("geopandas")
pytest.importorskip("xarray")
pytest.importorskip("affine")
pytest.importorskip("shapely")
pytest.importorskip("rioxarray")

import dask
import dask.array as da
import geopandas as gpd
import xarray as xr
from affine import Affine
from shapely.geometry import box

import hydroseason._io_geo as geo
from hydroseason._io_wofs_acquire import acquire_wofs_cache, load_or_build_cached_wet_aoi


def _planning_footprint(*, factor=4, safety_cells=1, covered_years=(2015,), digest="f" * 64):
    """A minimal, hand-built stand-in for build_wet_planning_footprint's output.

    Only the fields _io_wofs_acquire actually needs to thread through
    (native_mask for the vectorised wet_aoi pixel-clip, digest/factor/
    safety_cells/covered_years for cache identity) are populated with real,
    properly georeferenced values -- native_mask is a 4x4, all-wet, 30 m
    EPSG:3577 grid covering the same box(0, 0, 120, 120) footprint _aoi()
    uses, so tests can exercise the real wet_aoi_polygon()/plan_storage_
    aligned_slices() path rather than mocking it away.
    """
    from hydroseason._io_dea_stats import WetPlanningFootprint
    from hydroseason._spatial_plan import GridWindow

    transform = Affine(30.0, 0.0, 0.0, 0.0, -30.0, 120.0)
    native_mask = xr.DataArray(
        np.ones((4, 4), dtype=bool), dims=("y", "x"),
        coords={
            "y": transform.f + (np.arange(4) + 0.5) * transform.e,
            "x": transform.c + (np.arange(4) + 0.5) * transform.a,
        },
    ).rio.write_crs("EPSG:3577").rio.write_transform(transform)
    coarse_mask = xr.DataArray(np.ones((1, 1), dtype=bool), dims=("y", "x"))
    return WetPlanningFootprint(
        native_mask=native_mask,
        coarse_mask=coarse_mask,
        active_windows=(GridWindow("r0c0", 0, 4, 0, 4),),
        factor=factor,
        safety_cells=safety_cells,
        digest=digest,
        covered_years=tuple(covered_years),
        source_collection="ga_ls_wo_fq_myear_3",
        source_version="3",
        source_lineage="ga_ls_wo_fq_myear_3:item-1",
        geometry=None,
    )


def _item(date: str, item_id: str):
    return SimpleNamespace(id=item_id, properties={"datetime": date})


def _aoi():
    return gpd.GeoDataFrame(geometry=[box(0, 0, 120, 120)], crs="EPSG:3577")


def _cube(year: int):
    return xr.DataArray(
        np.zeros((12, 4, 4), dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": pd.date_range(f"{year}-01-01", periods=12, freq="MS")},
    ).chunk({"time": 1, "y": 4, "x": 4})


def _stats():
    return SimpleNamespace(
        year=2015, task_count=1, chunks_considered=12,
        chunks_written=12, loaded_pixels=192, item_digest="abc",
    )


def test_stac_query_results_are_stably_ordered(monkeypatch):
    import pystac_client

    items = [
        _item("2015-01-15T00:00:00Z", "same-day-b"),
        _item("2015-01-15T00:00:00Z", "same-day-a"),
        _item("2015-01-01T00:00:00Z", "earlier"),
    ]
    query_kwargs = {}
    monkeypatch.setattr(pystac_client.Client, "open", lambda _url: object())

    def collect(*_args, **kwargs):
        query_kwargs.update(kwargs)
        return items

    monkeypatch.setattr(geo, "_collect_stac_items", collect)

    result, _aoi_gdf = geo._query_wofs_items(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31",
    )

    assert [item.id for item in result] == ["earlier", "same-day-a", "same-day-b"]
    assert query_kwargs["fields"] == {
        "include": [
            "assets.water",
            "properties.datetime",
            "properties.start_datetime",
            "properties.end_datetime",
        ]
    }


def test_multi_year_acquisition_queries_once_and_builds_one_graph_per_year(monkeypatch, tmp_path):
    items = [_item("2015-01-15", "a"), _item("2015-07-15", "b"), _item("2016-02-15", "c")]
    query = Mock(return_value=(items, _aoi()))
    graph = Mock(side_effect=[_cube(2015), _cube(2016)])
    writer = Mock(return_value=_stats())
    monkeypatch.setattr("hydroseason._io_wofs_acquire._query_wofs_items", query)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", graph)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
    )

    query.assert_called_once()
    assert graph.call_count == 2
    assert writer.call_count == 2
    assert [tuple(item.id for item in call.args[0]) for call in graph.call_args_list] == [("a", "b"), ("c",)]


def test_failed_year_is_deferred_until_other_years_finish(monkeypatch, tmp_path):
    items = [_item("2015-01-15", "a"), _item("2016-01-15", "b")]
    call_order = []
    attempts = {2015: 0, 2016: 0}

    def build(_items, _aoi_gdf, start_date, _end_date, **_kwargs):
        return _cube(pd.Timestamp(start_date).year)

    def write(_handle, year, _mask, **_kwargs):
        call_order.append(year)
        attempts[year] += 1
        if year == 2015 and attempts[year] == 1:
            raise RuntimeError("transient remote read")
        stats = _stats()
        stats.year = year
        return stats

    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", build)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", write)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.time.sleep", lambda _seconds: None)

    acquire_wofs_cache(
        "https://example.invalid/stac",
        "ga_ls_wo_3",
        _aoi(),
        "2015-01-01",
        "2016-12-31",
        cache_root=tmp_path,
        resolution=30,
    )

    assert call_order == [2015, 2016, 2015]


def test_acquisition_reports_query_and_graph_counts_to_diagnostics_callback(monkeypatch, tmp_path):
    items = [_item("2015-01-15", "a"), _item("2016-02-15", "b")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(side_effect=[_cube(2015), _cube(2016)]),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))
    diagnostics = []

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
        diagnostics_callback=diagnostics.append,
    )

    assert len(diagnostics) == 1
    payload = diagnostics[0]
    assert payload["query_count"] == 1
    assert payload["graph_count"] == 2
    assert payload["task_count"] == 2
    assert payload["chunks_considered"] == 24
    assert payload["chunks_written"] == 24
    assert payload["loaded_pixels"] == 384
    # Task 5 additive diagnostics -- new keys, existing keys unchanged above.
    for new_key in (
        "statistics_prepare_seconds", "stac_read_seconds", "active_window_count",
        "planned_native_pixels", "local_reduction_seconds",
    ):
        assert new_key in payload


def test_completed_year_is_not_rebuilt(monkeypatch, tmp_path):
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    monkeypatch.setattr("hydroseason._io_wofs_acquire.resolve_cached_request", Mock(return_value=handle))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.completed_years", Mock(return_value={2015}))
    graph = Mock()
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", graph)
    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
    )
    graph.assert_not_called()


def test_acquisition_year_workers_parameter(monkeypatch, tmp_path):
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    handle.path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.resolve_cached_request", Mock(return_value=handle))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.create_cache_handle", Mock(return_value=handle))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.completed_years", Mock(return_value=set()))
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=([_item("2015-01-15", "a"), _item("2016-01-15", "b")], _aoi())),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", Mock(side_effect=[_cube(2015), _cube(2016)]))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    res = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
        year_workers=2,
    )
    assert res == handle


def test_corrupt_final_year_directory_is_rebuilt_with_overwrite(monkeypatch, tmp_path):
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    (handle.path / "years" / "2015").mkdir(parents=True)
    writer = Mock(return_value=_stats())
    monkeypatch.setattr("hydroseason._io_wofs_acquire.resolve_cached_request", Mock(return_value=handle))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.create_cache_handle", Mock(return_value=handle))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.completed_years", Mock(return_value=set()))
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=([_item("2015-01-15", "a")], _aoi())),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", Mock(return_value=_cube(2015)))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", writer)

    acquire_wofs_cache(
        "https://example.invalid/stac",
        "ga_ls_wo_3",
        _aoi(),
        "2015-01-01",
        "2015-12-31",
        cache_root=tmp_path,
        resolution=30,
    )

    assert writer.call_args.kwargs["overwrite"] is True


def test_annual_writer_mask_and_local_counts_share_one_delayed_source(tmp_path):
    import zarr

    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOfSCacheIdentity,
        WOfSCacheRequest,
        create_cache_handle,
        write_annual_group,
    )
    from hydroseason._spatial_plan import GridWindow

    calls = {"source": 0}

    @dask.delayed
    def source():
        calls["source"] += 1
        return np.repeat(np.array([[[1, 0], [-1, -2]]], dtype=np.int8), 12, axis=0)

    transform = Affine(30, 0, 1000, 0, -30, 2000)
    arr = da.from_delayed(source(), shape=(12, 2, 2), dtype=np.int8)
    mask = xr.DataArray(
        arr,
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2015-01-01", periods=12, freq="MS"),
            "y": transform.f + (np.arange(2) + 0.5) * transform.e,
            "x": transform.c + (np.arange(2) + 0.5) * transform.a,
        },
        name="water_mask",
    ).rio.write_crs(3577).rio.write_transform(transform)
    request = WOfSCacheRequest(
        stac_url="https://example.invalid/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="2015-01-01",
        end_date="2015-01-31",
        crs="EPSG:3577",
        resolution=30.0,
        classifier_version=1,
        groupby="solar_day",
        majority=True,
        planner_version=1,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    identity = WOfSCacheIdentity.from_request(
        request,
        shape=(mask.sizes["y"], mask.sizes["x"]),
        transform=tuple(mask.rio.transform())[:6],
    )
    handle = create_cache_handle(tmp_path, identity)

    write_annual_group(
        handle,
        2015,
        mask,
        windows=(GridWindow("parent", 0, 2, 0, 2),),
        item_ids=("a",),
    )

    group = zarr.open_group(handle.path / "years" / "2015", mode="r")
    assert calls["source"] == 1
    expected_mask = np.repeat(np.array([[[1, 0], [-1, -2]]], dtype=np.int8), 12, axis=0)
    np.testing.assert_array_equal(group["water_mask"][:], expected_mask)
    np.testing.assert_array_equal(group["wet_count"][:], np.array([[12, 0], [0, 0]], dtype=np.uint16))
    np.testing.assert_array_equal(group["clear_count"][:], np.array([[12, 12], [0, 0]], dtype=np.uint16))


def test_empty_year_mask_is_invalid_inside_and_outside_aoi_elsewhere():
    from hydroseason._io_wofs_acquire import _empty_year_mask

    transform = Affine(30, 0, 0, 0, -30, 120)

    class _Coord:
        def __init__(self, values):
            self.values = values

    class _Coords:
        def values(self):
            return (
                _Coord(transform.f + (np.arange(4) + 0.5) * transform.e),
                _Coord(transform.c + (np.arange(4) + 0.5) * transform.a),
            )

    geobox = SimpleNamespace(
        shape=(4, 4),
        coordinates=_Coords(),
        crs="EPSG:3577",
        affine=transform,
    )
    aoi = gpd.GeoDataFrame(geometry=[box(30, 30, 90, 90)], crs="EPSG:3577")

    values = _empty_year_mask(geobox, "2015-01-01", "2015-01-31", aoi).compute().values

    assert values[0, 0, 0] == -2
    assert values[0, 1, 1] == -1
    assert set(np.unique(values)) == {-2, -1}


def test_empty_year_mask_uses_bounded_spatial_chunks(monkeypatch):
    from hydroseason._io_wofs_acquire import _empty_year_mask

    transform = Affine(30, 0, 0, 0, -30, 18000)

    class _Coord:
        def __init__(self, values):
            self.values = values

    class _Coords:
        def values(self):
            return (
                _Coord(transform.f + (np.arange(600) + 0.5) * transform.e),
                _Coord(transform.c + (np.arange(600) + 0.5) * transform.a),
            )

    geobox = SimpleNamespace(
        shape=(600, 600), coordinates=_Coords(), crs="EPSG:3577", affine=transform
    )
    monkeypatch.setattr(
        "hydroseason._io_geo._clip_to_aoi",
        lambda mask, _aoi, **_kwargs: mask,
    )

    mask = _empty_year_mask(geobox, "2015-01-01", "2015-01-31", _aoi())

    assert max(mask.data.chunksize[1:]) <= 512


def _historical_mask_for_empty_year_grid(*, transform, shape, exclude_cells=()):
    """A real HistoricalWaterMask matching the 4x4 EPSG:3577/30m grid
    test_empty_year_mask_is_invalid_inside_and_outside_aoi_elsewhere builds,
    with every cell True except ``exclude_cells`` (row, col) pairs."""
    from hydroseason._historical_water_mask import HistoricalWaterMask

    values = np.ones(shape, dtype=bool)
    for row, col in exclude_cells:
        values[row, col] = False
    return HistoricalWaterMask(
        mask=values,
        crs="EPSG:3577",
        transform=tuple(transform)[:6],
        shape=tuple(shape),
        resolution=(abs(transform.a), abs(transform.e)),
        pixel_count=int(values.sum()),
        source_product="ga_ls_wo_fq_myear_3",
        source_version="3",
        source_item_ids=("item-1",),
        source_lineage=("ga_ls_wo_fq_myear_3",),
        coverage_start="1987-01-01",
        coverage_end="2024-12-31",
        aoi_sha256="a" * 64,
        mask_sha256="b" * 64,
    )


def test_empty_year_mask_applies_historical_water_mask_as_constant_denominator():
    """A year with zero STAC items must still report the SAME n_aoi as a
    normal year: every historical-mask cell reads -1 (invalid, no source
    data), every other cell (including inside the AOI polygon but outside
    the exact historical mask) reads -2, so n_aoi == pixel_count and
    n_invalid == n_aoi -- never the full user-AOI pixel count."""
    from hydroseason._io_wofs_acquire import _empty_year_mask
    from hydroseason.hydro_year import monthly_water_extent

    transform = Affine(30, 0, 0, 0, -30, 120)

    class _Coord:
        def __init__(self, values):
            self.values = values

    class _Coords:
        def values(self):
            return (
                _Coord(transform.f + (np.arange(4) + 0.5) * transform.e),
                _Coord(transform.c + (np.arange(4) + 0.5) * transform.a),
            )

    geobox = SimpleNamespace(
        shape=(4, 4),
        coordinates=_Coords(),
        crs="EPSG:3577",
        affine=transform,
    )
    # AOI covers the whole 4x4 grid, so without a historical mask every
    # cell would be -1 (n_aoi == 16). The historical mask excludes exactly
    # one cell -- that cell must read -2, not -1, and the reduction's n_aoi
    # must equal the mask's pixel_count (15), not the full AOI (16).
    aoi = gpd.GeoDataFrame(geometry=[box(0, 0, 120, 120)], crs="EPSG:3577")
    historical_mask = _historical_mask_for_empty_year_grid(
        transform=transform, shape=(4, 4), exclude_cells=[(0, 0)]
    )

    mask = _empty_year_mask(
        geobox, "2015-01-01", "2015-01-31", aoi, historical_water_mask=historical_mask
    )
    values = mask.compute().values

    assert values[0, 0, 0] == -2
    assert set(np.unique(values)) == {-2, -1}
    assert int((values[0] == -1).sum()) == historical_mask.pixel_count

    summary = monthly_water_extent(mask.chunk({"time": 1, "y": 4, "x": 4}))
    row = summary.iloc[0]
    assert row["n_aoi"] == historical_mask.pixel_count
    assert row["n_invalid"] == row["n_aoi"]


def _canonical_year_cube(*, shape: tuple[int, int, int], fill: int, year: int) -> xr.DataArray:
    time, height, width = shape
    transform = Affine(30, 0, 1000, 0, -30, 2000)
    values = np.full(shape, fill, dtype=np.int8)
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range(f"{year}-01-01", periods=time, freq="MS"),
            "y": transform.f + (np.arange(height) + 0.5) * transform.e,
            "x": transform.c + (np.arange(width) + 0.5) * transform.a,
        },
        name="water_mask",
    ).rio.write_crs(3577).rio.write_transform(transform)


def _completed_cache_handle(tmp_path: Path):
    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOfSCacheIdentity,
        WOfSCacheRequest,
        create_cache_handle,
        write_annual_group,
    )
    from hydroseason._spatial_plan import GridWindow

    request = WOfSCacheRequest(
        stac_url="https://example.invalid/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="2015-01-01",
        end_date="2016-12-31",
        crs="EPSG:3577",
        resolution=30.0,
        classifier_version=1,
        groupby="solar_day",
        majority=True,
        planner_version=1,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    cube_2015 = _canonical_year_cube(shape=(12, 4, 4), fill=1, year=2015)
    identity = WOfSCacheIdentity.from_request(
        request,
        shape=(cube_2015.sizes["y"], cube_2015.sizes["x"]),
        transform=tuple(cube_2015.rio.transform())[:6],
    )
    handle = create_cache_handle(tmp_path, identity)
    window = (GridWindow("parent", 0, 4, 0, 4),)
    write_annual_group(
        handle, 2015, cube_2015.chunk({"time": 1, "y": 4, "x": 4}),
        windows=window, item_ids=("a",),
    )
    cube_2016 = _canonical_year_cube(shape=(12, 4, 4), fill=0, year=2016)
    write_annual_group(
        handle, 2016, cube_2016.chunk({"time": 1, "y": 4, "x": 4}),
        windows=window, item_ids=("b",),
    )
    return handle


def test_load_or_build_cached_wet_aoi_never_touches_stac(monkeypatch, tmp_path):
    handle = _completed_cache_handle(tmp_path)

    def _raise(*args, **kwargs):
        raise AssertionError("STAC function must not be called")

    monkeypatch.setattr("hydroseason._io_wofs_acquire._query_wofs_items", _raise)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", _raise)

    wet_aoi = load_or_build_cached_wet_aoi(
        handle, persistence_min=0.0, close_m=0.0, buffer_m=0.0
    )

    assert isinstance(wet_aoi, gpd.GeoDataFrame)
    assert len(wet_aoi) > 0
    assert not wet_aoi.geometry.is_empty.all()


def test_force_rewrite_with_changed_pixels_does_not_reuse_wet_aoi_sidecar(tmp_path):
    from hydroseason._io_wofs_zarr import write_annual_group
    from hydroseason._spatial_plan import GridWindow

    handle = _completed_cache_handle(tmp_path)
    first = load_or_build_cached_wet_aoi(
        handle, persistence_min=0.0, close_m=0.0, buffer_m=0.0
    )
    rewritten = _canonical_year_cube(shape=(12, 4, 4), fill=0, year=2015)
    rewritten.values[:, 0, 0] = 1
    write_annual_group(
        handle,
        2015,
        rewritten.chunk({"time": 1, "y": 4, "x": 4}),
        windows=(GridWindow("parent", 0, 4, 0, 4),),
        item_ids=("a",),
        overwrite=True,
    )

    second = load_or_build_cached_wet_aoi(
        handle, persistence_min=0.0, close_m=0.0, buffer_m=0.0
    )

    assert len(list((handle.path / "wet_aoi").glob("*.geojson"))) == 2
    assert not first.geometry.equals(second.geometry)


def test_storage_preflight_fails_before_stac_query(monkeypatch, tmp_path):
    query = Mock()
    monkeypatch.setattr("hydroseason._io_wofs_acquire._query_wofs_items", query)
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.preflight_request_space",
        Mock(side_effect=OSError("insufficient cache space")),
    )
    with pytest.raises(OSError, match="insufficient cache space"):
        acquire_wofs_cache(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        )
    query.assert_not_called()


def test_manifest_contains_year_diagnostics(monkeypatch, tmp_path):
    import json

    items = [_item("2015-01-15", "a"), _item("2016-02-15", "b")]
    stats2015 = SimpleNamespace(
        year=2015, task_count=10, chunks_considered=12, chunks_written=8,
        loaded_pixels=1000, item_digest="dig2015", compute_seconds=1.2,
        encode_write_seconds=0.3, validation_seconds=0.1,
    )
    stats2016 = SimpleNamespace(
        year=2016, task_count=15, chunks_considered=12, chunks_written=10,
        loaded_pixels=1200, item_digest="dig2016", compute_seconds=1.5,
        encode_write_seconds=0.4, validation_seconds=0.2,
    )

    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(side_effect=[_cube(2015), _cube(2016)]),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.write_annual_group",
        Mock(side_effect=[stats2015, stats2016]),
    )

    handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
    )

    manifest_path = handle.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    year_diags = manifest["acquisition"]["year_diagnostics"]
    assert len(year_diags) == 2
    assert year_diags[0]["year"] == 2015
    assert year_diags[0]["compute_seconds"] == 1.2
    assert year_diags[1]["year"] == 2016
    assert year_diags[1]["validation_seconds"] == 0.2


def test_acquisition_passes_512_aligned_windows_to_writer(monkeypatch, tmp_path):
    items = [_item("2015-01-15", "a")]
    writer = Mock(return_value=_stats())
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
    )

    writer.assert_called_once()
    windows = writer.call_args.kwargs["windows"]
    for w in windows:
        assert w.y_start % 512 == 0
        assert w.x_start % 512 == 0
        assert (w.y_stop - w.y_start) <= 512
        assert (w.x_stop - w.x_start) <= 512


def test_resolve_wet_aoi_prefers_explicit_mask_over_dea_stats(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire

    explicit = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("DEA stats must not be queried when wet_aoi is explicit")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _must_not_be_called)

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", explicit, [2015],
        wet_aoi=explicit, wet_mask="dea_stats",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
    )
    assert resolved is explicit
    assert digest is not None and len(digest) == 64


def test_resolve_wet_aoi_falls_open_when_dea_stats_unavailable(monkeypatch):
    """A failed stats fetch must yield NO pruning, never partial pruning:
    pruning on a bad mask silently deletes real water."""
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    def _unavailable(*args, **kwargs):
        raise DEAStatsUnavailable("collection unreachable")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _unavailable)

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", aoi, [2015],
        wet_aoi=None, wet_mask="dea_stats",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
    )
    assert resolved is None
    assert digest is None


def test_resolve_wet_aoi_off_never_queries_stats(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire

    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("wet_mask='off' must not query DEA stats")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _must_not_be_called)

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", aoi, [2015],
        wet_aoi=None, wet_mask="off",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
    )
    assert resolved is None
    assert digest is None


def test_pruned_and_unpruned_requests_use_distinct_stores(tmp_path):
    """The whole point of wet_mask_sha256: a pruned store must not be mistaken
    for a full-coverage one."""
    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOFS_CLASSIFIER_VERSION,
        WOFS_PLANNER_VERSION,
        WOfSCacheRequest,
    )

    common = {
        "stac_url": "https://example.test/stac",
        "collection": "ga_ls_wo_3",
        "aoi_sha256": "a" * 64,
        "start_date": "2015-01-01",
        "end_date": "2015-12-31",
        "crs": "3577",
        "resolution": 30.0,
        "classifier_version": WOFS_CLASSIFIER_VERSION,
        "groupby": "solar_day",
        "majority": True,
        "planner_version": WOFS_PLANNER_VERSION,
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
    }
    full = WOfSCacheRequest(**common)
    pruned = WOfSCacheRequest(**common, wet_mask_sha256="d" * 64)
    assert full.request_digest() != pruned.request_digest()


def test_resolve_wet_aoi_prefers_local_cached_counts_over_dea_stats(monkeypatch, tmp_path):
    """Local cached wet counts (free, exact for completed years) must win
    over a DEA-stats fetch when both are available."""
    import hydroseason._io_wofs_acquire as acquire

    handle = _completed_cache_handle(tmp_path)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("DEA stats must not be queried when local counts cover the request")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _must_not_be_called)

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", _aoi(), [2015, 2016],
        wet_aoi=None, wet_mask="dea_stats",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
        local_wet_aoi_handle=handle,
    )
    assert resolved is not None
    assert digest is not None and len(digest) == 64


def test_resolve_wet_aoi_falls_through_to_dea_stats_when_local_years_incomplete(monkeypatch, tmp_path):
    """A local store exists but doesn't cover every requested year: the
    local-cached-counts level must not apply, and dea_stats must still run."""
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire

    handle = _completed_cache_handle(tmp_path)  # only covers 2015, 2016
    dea_result = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", Mock(return_value=dea_result))

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", _aoi(), [2015, 2016, 2017],
        wet_aoi=None, wet_mask="dea_stats",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
        local_wet_aoi_handle=handle,
    )
    assert resolved is dea_result
    assert digest is not None and len(digest) == 64


def test_resolve_wet_aoi_falls_through_to_dea_stats_when_local_handle_has_no_completed_years(monkeypatch, tmp_path):
    """A freshly created (empty) handle must not raise out of _resolve_wet_aoi;
    it must fall through to dea_stats instead."""
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire
    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOFS_CLASSIFIER_VERSION,
        WOFS_PLANNER_VERSION,
        WOfSCacheIdentity,
        WOfSCacheRequest,
        create_cache_handle,
    )

    request = WOfSCacheRequest(
        stac_url="https://example.test/stac", collection="ga_ls_wo_3",
        aoi_sha256="a" * 64, start_date="2015-01-01", end_date="2015-12-31",
        crs="3577", resolution=30.0, classifier_version=WOFS_CLASSIFIER_VERSION,
        groupby="solar_day", majority=True, planner_version=WOFS_PLANNER_VERSION,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    identity = WOfSCacheIdentity.from_request(
        request, shape=(4, 4), transform=(1.0, 0.0, 0.0, 0.0, -1.0, 0.0)
    )
    empty_handle = create_cache_handle(tmp_path, identity)
    dea_result = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", Mock(return_value=dea_result))

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", _aoi(), [2015],
        wet_aoi=None, wet_mask="dea_stats",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
        local_wet_aoi_handle=empty_handle,
    )
    assert resolved is dea_result
    assert digest is not None and len(digest) == 64


def test_default_wet_mask_off_reuses_existing_full_coverage_store(monkeypatch, tmp_path):
    """A completed full-coverage store must be reused as-is on a later call
    with the default wet_mask="off" and no explicit wet_aoi -- it must never
    resolve to a *different* (pruned) store just because a local wet mask
    happens to be derivable from that same store."""
    import hydroseason._io_wofs_acquire as acquire

    items = [_item("2015-01-15", "a"), _item("2016-02-15", "b")]
    stats2015 = SimpleNamespace(
        year=2015, task_count=1, chunks_considered=1, chunks_written=1,
        loaded_pixels=16, item_digest="dig2015",
    )
    stats2016 = SimpleNamespace(
        year=2016, task_count=1, chunks_considered=1, chunks_written=1,
        loaded_pixels=16, item_digest="dig2016",
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(side_effect=[_cube(2015), _cube(2016)]),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.write_annual_group",
        Mock(side_effect=[stats2015, stats2016]),
    )

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("wet_mask='off' must never derive or query a wet mask")

    monkeypatch.setattr(acquire, "load_or_build_cached_wet_aoi", _must_not_be_called)
    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _must_not_be_called)

    first = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
    )

    # Pre-existing behaviour (unrelated to this task): a repeat call still
    # re-queries STAC even on a full cache hit, but must resolve to the SAME
    # store. The property under test here is that this call resolves to the
    # same store/identity as before, never a different (pruned) one, even
    # though a locally-derivable wet mask now exists for that same store.
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=([], _aoi())),
    )

    second = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
    )

    assert second.path == first.path
    assert second.identity == first.identity


def test_resolve_wet_aoi_off_refuses_pruning_even_with_a_working_local_handle(tmp_path):
    """wet_mask="off" must refuse to prune even when a genuinely usable local
    wet mask exists -- i.e. a handle whose completed_years(...) really is a
    superset of the requested years and whose load_or_build_cached_wet_aoi(...)
    would really succeed if called. This must hold as a property of
    _resolve_wet_aoi itself, not merely because of how acquire_wofs_cache
    happens to gate the local_wet_aoi_handle it passes in."""
    import hydroseason._io_wofs_acquire as acquire

    handle = _completed_cache_handle(tmp_path)  # real completed store: covers 2015, 2016

    # Sanity check: the handle really is usable at the local-cached-counts
    # level -- completed_years covers the request and load_or_build_cached_wet_aoi
    # genuinely succeeds. If this weren't true, a (None, None) result below
    # would prove nothing about the wet_mask="off" guard.
    assert {2015, 2016} <= acquire.completed_years(handle)
    sanity_mask = acquire.load_or_build_cached_wet_aoi(handle)
    assert isinstance(sanity_mask, gpd.GeoDataFrame)
    assert len(sanity_mask) > 0

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", _aoi(), [2015, 2016],
        wet_aoi=None, wet_mask="off",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
        local_wet_aoi_handle=handle,
    )

    assert resolved is None
    assert digest is None


# ---------------------------------------------------------------------------
# W2.1: planning_footprint threading -- query-count / pruning tests (Step 1)
# ---------------------------------------------------------------------------


def test_passing_a_prepared_planning_footprint_never_queries_dea_stats(monkeypatch, tmp_path):
    """The whole point of accepting a prepared WetPlanningFootprint: a caller
    (later, HydroFragments' orchestrator) that already built one via
    build_wet_planning_footprint must never trigger a second DEA-statistics
    STAC query when it hands the footprint to acquire_wofs_cache."""
    import hydroseason._io_wofs_acquire as acquire

    footprint = _planning_footprint()
    items = [_item("2015-01-15", "a")]

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("DEA statistics must not be queried when a prepared "
                              "planning_footprint is supplied")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _must_not_be_called)
    monkeypatch.setattr("hydroseason._io_dea_stats.open_wo_statistics", _must_not_be_called)
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint,
    )


def test_planning_footprint_and_wet_aoi_together_is_rejected(tmp_path):
    """Keep explicit legacy wet_aoi compatibility, but the two pruning
    sources must never both be supplied -- ambiguous precedence."""
    import geopandas as gpd
    from shapely.geometry import box

    footprint = _planning_footprint()
    wet_aoi = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    with pytest.raises(ValueError, match="wet_aoi.*planning_footprint|planning_footprint.*wet_aoi"):
        acquire_wofs_cache(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
            wet_aoi=wet_aoi, planning_footprint=footprint,
        )


def test_planning_footprint_queries_stac_items_exactly_once(monkeypatch, tmp_path):
    """One STAC item query per uncached request, even when a planning
    footprint is supplied -- the footprint prunes space, not the item query."""
    footprint = _planning_footprint()
    items = [_item("2015-01-15", "a")]
    query = Mock(return_value=(items, _aoi()))
    monkeypatch.setattr("hydroseason._io_wofs_acquire._query_wofs_items", query)
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint,
    )

    query.assert_called_once()


def test_planning_footprint_shares_one_graph_per_year(monkeypatch, tmp_path):
    """One shared load graph per year, same as the wet_aoi/dea_stats paths --
    a planning_footprint must not fan a year out into multiple graphs."""
    footprint = _planning_footprint(covered_years=(2015, 2016))
    items = [_item("2015-01-15", "a"), _item("2016-02-15", "b")]
    graph = Mock(side_effect=[_cube(2015), _cube(2016)])
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", graph)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint,
    )

    assert graph.call_count == 2


def test_planning_footprint_active_windows_are_the_only_windows_passed_to_writer(monkeypatch, tmp_path):
    """Only active storage windows reach the writer -- windows planned from
    the footprint's own (vectorised, native-grid) wet region, storage-aligned
    on the acquisition's own parent geobox, exactly mirroring how an explicit
    wet_aoi already prunes ``plan_storage_aligned_slices`` today. Windows are
    NOT the footprint's raw ``active_windows`` byte-for-byte -- those are
    indexed against the DEA-statistics native grid, which is not guaranteed
    pixel-aligned with the acquisition's own parent geobox."""
    # A footprint covering the whole test AOI (box(0, 0, 120, 120) at 30 m
    # native resolution, i.e. a 4x4 native pixel grid) so the resulting
    # storage-aligned plan is non-empty and covers the single 512px block.
    footprint = _planning_footprint()
    items = [_item("2015-01-15", "a")]
    writer = Mock(return_value=_stats())
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint,
    )

    writer.assert_called_once()
    windows = writer.call_args.kwargs["windows"]
    assert len(windows) >= 1
    for w in windows:
        assert w.y_start % 512 == 0
        assert w.x_start % 512 == 0


def test_planning_footprint_is_passed_through_to_year_graph(monkeypatch, tmp_path):
    """build_wofs_year_graph must receive the planning footprint's pruning
    intent (via wet_aoi/native_mask) so the fine-grain pixel clip applies it,
    matching how the existing explicit wet_aoi is threaded."""
    footprint = _planning_footprint()
    items = [_item("2015-01-15", "a")]
    graph = Mock(return_value=_cube(2015))
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", graph)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint,
    )

    graph.assert_called_once()
    assert graph.call_args.kwargs.get("wet_aoi") is not None


def test_planning_footprint_and_composite_bundle_are_recorded_in_manifest(monkeypatch, tmp_path):
    """Threading step 4 names 'manifest' explicitly: the footprint's
    provenance and the composite_bundle mode must both be recorded, purely
    for visibility -- cache identity itself is governed independently by
    WOfSCacheRequest's footprint_*/composite_bundle fields."""
    import json

    footprint = _planning_footprint(factor=4, safety_cells=1, covered_years=(2015,))
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint, composite_bundle="hydrofragments_v1",
    )

    manifest = json.loads((handle.path / "manifest.json").read_text(encoding="utf-8"))
    acq = manifest["acquisition"]
    assert acq["composite_bundle"] == "hydrofragments_v1"
    assert acq["planning_footprint"]["digest"] == footprint.digest
    assert acq["planning_footprint"]["factor"] == 4
    assert acq["planning_footprint"]["safety_cells"] == 1
    assert acq["planning_footprint"]["covered_years"] == [2015]


def test_hydrofragments_v1_threads_dual_counts_from_graph_to_writer(monkeypatch, tmp_path):
    """Step 3 (W2.2) wiring: build_wofs_year_graph's
    ``.attrs["hydrofragments_dual_counts"]`` side-channel must reach
    write_annual_group's ``dual_counts`` keyword unchanged, and must be
    popped off the mask (never left sitting on the object passed to
    write_annual_group as `mask`, which only expects the primary
    composite)."""
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )

    sentinel_dual_counts = object()

    def fake_graph(*_args, **_kwargs):
        cube = _cube(2015)
        cube.attrs["hydrofragments_dual_counts"] = sentinel_dual_counts
        return cube

    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", fake_graph)
    writer = Mock(return_value=_stats())
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        composite_bundle="hydrofragments_v1",
    )

    writer.assert_called_once()
    assert writer.call_args.kwargs["dual_counts"] is sentinel_dual_counts
    written_mask = writer.call_args.args[2]
    assert "hydrofragments_dual_counts" not in written_mask.attrs


def test_hydrofragments_v1_writes_zeroed_dual_counts_for_an_empty_year(monkeypatch, tmp_path):
    """An empty year (no STAC items at all) must still get
    dual_extent_counts.json when the dual bundle is requested -- both
    composites are legitimately all-zero, not simply absent, keeping the
    artifact's presence consistent across empty and non-empty years."""
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=([], _aoi())),
    )
    empty_writer = Mock(return_value=_stats())
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_empty_annual_group", empty_writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        composite_bundle="hydrofragments_v1",
    )

    empty_writer.assert_called_once()
    assert empty_writer.call_args.kwargs["dual_extent_counts"] is True


def test_default_composite_bundle_never_requests_dual_extent_counts_for_empty_year(monkeypatch, tmp_path):
    """The default 'single_mask' bundle must pass dual_extent_counts=False
    for an empty year, matching its 'no new file, ever' guarantee."""
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=([], _aoi())),
    )
    empty_writer = Mock(return_value=_stats())
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_empty_annual_group", empty_writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
    )

    empty_writer.assert_called_once()
    assert empty_writer.call_args.kwargs["dual_extent_counts"] is False


def test_default_composite_bundle_is_single_mask_with_no_footprint_recorded(monkeypatch, tmp_path):
    """A caller that never mentions composite_bundle or planning_footprint
    must get the byte-identical default manifest shape (composite_bundle
    recorded as "single_mask", planning_footprint recorded as None)."""
    import json

    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
    )

    manifest = json.loads((handle.path / "manifest.json").read_text(encoding="utf-8"))
    acq = manifest["acquisition"]
    assert acq["composite_bundle"] == "single_mask"
    assert acq["planning_footprint"] is None


def test_offline_lookup_with_planning_footprint_resolves_the_same_store_built_online(monkeypatch, tmp_path):
    """A caller that acquires online with a planning_footprint, then looks
    the same request up offline with the identical footprint, must resolve
    to the exact same store -- offline mode must never touch the network,
    but its request_digest still needs to route through the footprint's
    identity fields the same way the online path does."""
    footprint = _planning_footprint()
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    online_handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint,
    )

    offline_handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        planning_footprint=footprint, offline=True,
    )

    assert offline_handle.path == online_handle.path
    assert offline_handle.identity == online_handle.identity


def test_planning_footprint_native_mask_produces_a_valid_wet_aoi_polygon():
    """Not-mocked integration check for _wet_aoi_from_planning_footprint: a
    real (small) footprint's native_mask must vectorise into a non-empty,
    valid GeoDataFrame usable by the existing wet_aoi pixel-clip path."""
    from hydroseason._io_wofs_acquire import _wet_aoi_from_planning_footprint

    footprint = _planning_footprint()

    wet_aoi = _wet_aoi_from_planning_footprint(footprint)

    assert len(wet_aoi) > 0
    assert not bool(wet_aoi.geometry.is_empty.all())
    assert wet_aoi.crs is not None
    # native_mask is entirely wet (all-ones 4x4 grid, see _planning_footprint).
    # _wet_aoi_from_planning_footprint uses wet_aoi_polygon's default
    # close_m=150.0/buffer_m=300.0 (the same margin convention as the sibling
    # wet_aoi-producing functions), so the vectorised polygon covers the
    # whole native grid extent PLUS the 300 m outward safety buffer.
    minx, miny, maxx, maxy = wet_aoi.total_bounds
    assert (minx, miny, maxx, maxy) == pytest.approx((-300.0, -300.0, 420.0, 420.0))


def test_planning_footprint_derived_wet_aoi_clips_pixels_outside_it_via_clip_to_aoi():
    """Real (non-mocked) hydroseason._io_geo._clip_to_aoi check that the
    wet_aoi _wet_aoi_from_planning_footprint derives actually narrows the
    written mask: a footprint wet only near the left edge of a large AOI must
    leave pixels far to the right -2 (outside) after the real clip, not
    water/dry/invalid -- this is the fine-grain pixel-clip half of spatial
    pruning that build_wofs_year_graph applies via its existing wet_aoi
    parameter. The grid is deliberately much larger than the 300 m
    buffer_m/150 m close_m margin _wet_aoi_from_planning_footprint now
    applies (matching the sibling wet_aoi-producing functions' convention),
    so the buffered polygon still leaves a clearly-outside region."""
    from hydroseason._io_dea_stats import WetPlanningFootprint
    from hydroseason._io_geo import _clip_to_aoi
    from hydroseason._io_wofs_acquire import _wet_aoi_from_planning_footprint
    from hydroseason._spatial_plan import GridWindow

    # AOI is box(0, 0, 1200, 1200) in EPSG:3577 at 30 m -> a 40x40 native
    # pixel grid. A footprint wet only in columns 0-9 (0-300 m) buffers out
    # to ~600 m (300 m buffer + up to ~150 m close-related growth), so
    # columns from x=900 m (col 30) onward -- 300 m clear of the buffered
    # edge -- must still clip to -2, while the wet columns themselves must
    # not be clipped.
    size = 40
    transform = Affine(30.0, 0.0, 0.0, 0.0, -30.0, size * 30.0)
    left_wet = np.zeros((size, size), dtype=bool)
    left_wet[:, :10] = True
    native_mask = xr.DataArray(
        left_wet, dims=("y", "x"),
        coords={
            "y": transform.f + (np.arange(size) + 0.5) * transform.e,
            "x": transform.c + (np.arange(size) + 0.5) * transform.a,
        },
    ).rio.write_crs("EPSG:3577").rio.write_transform(transform)
    footprint = WetPlanningFootprint(
        native_mask=native_mask,
        coarse_mask=xr.DataArray(np.array([[True]]), dims=("y", "x")),
        active_windows=(GridWindow("r0c0", 0, size, 0, size),),
        factor=size, safety_cells=0, digest="a" * 64, covered_years=(2015,),
        source_collection="ga_ls_wo_fq_myear_3", source_version="3",
        source_lineage="ga_ls_wo_fq_myear_3:item-1", geometry=None,
    )
    footprint_wet_aoi = _wet_aoi_from_planning_footprint(footprint)

    all_water_cube = xr.DataArray(
        np.ones((1, size, size), dtype=np.int8), dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2015-06-01", periods=1, freq="MS"),
            "y": transform.f + (np.arange(size) + 0.5) * transform.e,
            "x": transform.c + (np.arange(size) + 0.5) * transform.a,
        },
    ).rio.write_crs("EPSG:3577").rio.write_transform(transform)

    aoi = gpd.GeoDataFrame(geometry=[box(0, 0, size * 30.0, size * 30.0)], crs="EPSG:3577")
    clipped = _clip_to_aoi(all_water_cube, aoi, wet_aoi=footprint_wet_aoi)
    values = clipped.isel(time=0).values

    assert np.all(values[:, :10] != -2)  # footprint-covered columns: not clipped
    assert np.all(values[:, 30:] == -2)  # far outside the buffered footprint: clipped


def test_acquire_wofs_cache_persists_identical_aoi_pixel_count_across_pruned_and_unpruned_runs(
    monkeypatch, tmp_path
):
    """End-to-end proof of task W2.3's central correctness property, exercised
    through the real acquire_wofs_cache entry point (not the standalone
    record_cache_footprints unit tests in test_io_cache_footprints.py): a
    pruned acquisition (explicit wet_aoi, a strict subset of the full AOI)
    and an unpruned acquisition of the SAME catchment must persist the SAME
    aoi_pixel_count, while analysis_pixel_count legitimately differs."""
    from hydroseason._io_wofs_zarr import read_cache_footprints

    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    # _aoi() is a 120x120 m box at 30 m resolution -> 4x4 = 16 pixels.
    unpruned_handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path / "unpruned", resolution=30,
    )

    # A strict half-AOI wet mask: the left half of the same 120x120 m box.
    half_wet_aoi = gpd.GeoDataFrame(geometry=[box(0, 0, 60, 120)], crs="EPSG:3577")
    pruned_handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path / "pruned", resolution=30,
        wet_aoi=half_wet_aoi,
    )

    unpruned_footprints = read_cache_footprints(unpruned_handle)
    pruned_footprints = read_cache_footprints(pruned_handle)

    assert unpruned_footprints.aoi_pixel_count == 16
    assert pruned_footprints.aoi_pixel_count == 16
    assert unpruned_footprints.aoi_pixel_count == pruned_footprints.aoi_pixel_count

    assert unpruned_footprints.analysis_pixel_count == 16
    assert pruned_footprints.analysis_pixel_count == 8
    assert pruned_footprints.analysis_pixel_count != unpruned_footprints.analysis_pixel_count


# ---------------------------------------------------------------------------
# Task 5: integrate the scientific (historical_water_mask) and planning
# (planning_footprint) masks into acquire_wofs_cache.
# ---------------------------------------------------------------------------


def _historical_mask(*, exclude_cells=(), pixel_count=None):
    """A real HistoricalWaterMask on the SAME 4x4/30m/EPSG:3577 grid as
    _aoi() (box(0, 0, 120, 120)), with every cell True except
    ``exclude_cells`` (row, col) pairs. Matches the grid
    _historical_mask_for_empty_year_grid already builds for _empty_year_mask
    tests, but exposed here (shape=(4, 4)) for the acquire_wofs_cache
    integration tests below.

    ``mask_sha256`` is computed with the REAL _mask_digest function (not a
    placeholder) -- Task 5's acquire_wofs_cache actually calls
    record_cache_analysis_mask, which re-hashes the on-disk bytes and raises
    if they disagree with the manifest, so a placeholder digest here would
    make every real acquire_wofs_cache call fail verification immediately."""
    from hydroseason._historical_water_mask import HistoricalWaterMask, _mask_digest

    transform = Affine(30.0, 0.0, 0.0, 0.0, -30.0, 120.0)
    shape = (4, 4)
    values = np.ones(shape, dtype=bool)
    for row, col in exclude_cells:
        values[row, col] = False
    resolution = (abs(transform.a), abs(transform.e))
    transform_tuple = tuple(transform)[:6]
    count = int(values.sum()) if pixel_count is None else pixel_count
    mask_sha256 = _mask_digest(
        values, crs="EPSG:3577", transform=transform_tuple, shape=shape, resolution=resolution,
    )
    return HistoricalWaterMask(
        mask=values,
        crs="EPSG:3577",
        transform=transform_tuple,
        shape=shape,
        resolution=resolution,
        pixel_count=count,
        source_product="ga_ls_wo_fq_myear_3",
        source_version="3",
        source_item_ids=("item-1",),
        source_lineage=("ga_ls_wo_fq_myear_3",),
        coverage_start="1987-01-01",
        coverage_end="2024-12-31",
        aoi_sha256="a" * 64,
        mask_sha256=mask_sha256,
    )


def _footprint_from(historical_mask, *, factor=1, safety_cells=0):
    """A real WetPlanningFootprint genuinely derived from ``historical_mask``
    via build_planning_footprint_from_historical_mask (Task 1) -- the actual
    production derivation, not a hand-rolled digest, so the tests below
    exercise the real "derives from" contract acquire_wofs_cache must check."""
    from hydroseason._io_dea_stats import build_planning_footprint_from_historical_mask

    return build_planning_footprint_from_historical_mask(
        historical_mask, factor=factor, safety_cells=safety_cells,
    )


def test_acquire_wofs_cache_accepts_historical_water_mask_and_planning_footprint_kwargs(
    monkeypatch, tmp_path,
):
    """The new lower-level signature: acquire_wofs_cache(..., historical_water_mask=,
    planning_footprint=) must be accepted together, with the planning
    footprint genuinely derived from the historical mask (real production
    derivation via build_planning_footprint_from_historical_mask)."""
    historical_mask = _historical_mask()
    footprint = _footprint_from(historical_mask)
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        historical_water_mask=historical_mask, planning_footprint=footprint,
    )

    assert handle is not None


def test_planned_windows_limit_reads_while_exact_historical_mask_sets_stored_pixels_and_counts(
    monkeypatch, tmp_path,
):
    """Planned windows (from the coarse/dilated planning_footprint) may be a
    SUPERSET of the exact historical mask -- they only gate which storage
    windows are read. What actually lands in stored -2 pixels and counts
    must come from the EXACT historical_water_mask, not the planning
    superset: one cell excluded from the historical mask (but still inside
    the planning footprint's coarse/native mask) must read -2 and must be
    excluded from n_aoi, even though the planning-driven windows still cover
    it (nothing to prune away at the coarse level for a single excluded
    native cell)."""

    historical_mask = _historical_mask(exclude_cells=[(0, 0)])
    footprint = _footprint_from(historical_mask)
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )

    graph_calls = []

    def _fake_graph(*args, **kwargs):
        graph_calls.append(kwargs)
        return _cube(2015)

    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", _fake_graph)
    writer = Mock(return_value=_stats())
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        historical_water_mask=historical_mask, planning_footprint=footprint,
    )

    assert graph_calls, "build_wofs_year_graph must be called"
    assert graph_calls[0].get("historical_water_mask") is historical_mask
    # Planning-derived wet_aoi (windows/diagnostics only) must still be
    # threaded too, but it is NOT what determines the exact -2/count
    # denominator -- that is historical_water_mask, asserted above.
    assert graph_calls[0].get("wet_aoi") is not None


def test_no_source_months_preserve_constant_n_aoi(monkeypatch, tmp_path):
    """A year with zero STAC items (no source observations at all) must
    still report n_aoi == historical_water_mask.pixel_count -- the SAME
    fixed denominator a normal (item-bearing) year would report -- not the
    larger, unpruned full-AOI pixel count. Exercised through the real
    write_empty_annual_group (not mocked away), so the n_aoi invariant is
    checked by production code, not by this test re-deriving it."""
    from hydroseason._io_wofs_zarr import open_completed_extent_counts

    historical_mask = _historical_mask(exclude_cells=[(0, 0)])
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=([], _aoi())),
    )

    handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        historical_water_mask=historical_mask,
    )

    df = open_completed_extent_counts(handle, "2015-01-01", "2015-12-31")
    assert df is not None
    assert (df["n_aoi"] == historical_mask.pixel_count).all()
    assert (df["n_aoi"] == 15).all()


def test_planning_dilation_does_not_increase_n_aoi(monkeypatch, tmp_path):
    """A planning_footprint built with a wide safety-cell dilation (a much
    larger coarse/native pruning superset than the exact historical mask)
    must never leak into the stored n_aoi denominator -- n_aoi must still
    equal historical_water_mask.pixel_count exactly, proving the planning
    mask never supplies n_aoi/counts, only active-window selection."""

    historical_mask = _historical_mask(exclude_cells=[(0, 0), (0, 1)])
    # A wide dilation halo: the planning footprint's coarse/native mask
    # covers far more than the exact historical mask, but n_aoi must not move.
    footprint = _footprint_from(historical_mask, factor=1, safety_cells=3)
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        historical_water_mask=historical_mask, planning_footprint=footprint,
    )

    from hydroseason._io_wofs_zarr import _handle_request_dict

    request_dict = _handle_request_dict(handle)
    assert request_dict.get("historical_mask_pixel_count") == 14
    assert request_dict.get("historical_mask_sha256") == historical_mask.mask_sha256


def test_mask_source_coverage_mismatch_errors_before_any_monthly_wofs_call(monkeypatch, tmp_path):
    """A planning_footprint that does NOT derive from the supplied
    historical_water_mask (independently supplied, mismatched artifacts)
    must be rejected before any STAC access / monthly WOfS call -- neither
    _query_wofs_items nor build_wofs_year_graph may ever be invoked."""
    historical_mask = _historical_mask()
    other_mask = _historical_mask(exclude_cells=[(1, 1)])
    mismatched_footprint = _footprint_from(other_mask)

    query = Mock(side_effect=AssertionError("must not query STAC on a mask mismatch"))
    graph = Mock(side_effect=AssertionError("must not build a graph on a mask mismatch"))
    monkeypatch.setattr("hydroseason._io_wofs_acquire._query_wofs_items", query)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", graph)

    with pytest.raises(ValueError, match="(?i)does not derive from|mismatch"):
        acquire_wofs_cache(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
            historical_water_mask=historical_mask, planning_footprint=mismatched_footprint,
        )

    query.assert_not_called()
    graph.assert_not_called()


def test_record_cache_analysis_mask_is_called_before_annual_writes(monkeypatch, tmp_path):
    """record_cache_analysis_mask() (Task 4) must actually be invoked by
    acquire_wofs_cache -- nothing called it before this task. Verified via
    the real on-disk sidecar it creates (verify_cache_analysis_mask), not a
    mock of record_cache_analysis_mask itself, so this proves the sidecar is
    genuinely persisted and independently verifiable, not merely that some
    function was called."""
    from hydroseason._io_wofs_zarr import verify_cache_analysis_mask

    historical_mask = _historical_mask()
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    handle = acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        historical_water_mask=historical_mask,
    )

    analysis_mask = verify_cache_analysis_mask(handle)
    assert analysis_mask.mask_sha256 == historical_mask.mask_sha256
    assert analysis_mask.pixel_count == historical_mask.pixel_count


def test_resume_path_verifies_cache_analysis_mask_before_accepting_completed_years(
    monkeypatch, tmp_path,
):
    """On a resumed (already-completed) request, acquire_wofs_cache must
    call verify_cache_analysis_mask() before accepting the completed years /
    count sidecars -- a store whose on-disk analysis-mask sidecar has been
    tampered with must not be silently trusted just because completed_years
    reports every requested year done."""
    import hydroseason._io_wofs_acquire as acquire_mod

    historical_mask = _historical_mask()
    items = [_item("2015-01-15", "a")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(return_value=_cube(2015)),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        historical_water_mask=historical_mask,
    )

    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.completed_years", Mock(return_value={2015})
    )
    verify_mock = Mock(wraps=acquire_mod.verify_cache_analysis_mask)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.verify_cache_analysis_mask", verify_mock)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        historical_water_mask=historical_mask,
    )

    verify_mock.assert_called()


def test_diagnostics_callback_gains_five_new_fields_without_changing_existing_keys(
    monkeypatch, tmp_path,
):
    """New diagnostic fields (statistics_prepare_seconds, stac_read_seconds,
    active_window_count, planned_native_pixels, local_reduction_seconds) must
    be added additively -- every existing callback key/value stays exactly
    as before."""
    items = [_item("2015-01-15", "a"), _item("2016-02-15", "b")]
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire._query_wofs_items",
        Mock(return_value=(items, _aoi())),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.build_wofs_year_graph",
        Mock(side_effect=[_cube(2015), _cube(2016)]),
    )
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", Mock(return_value=_stats()))
    diagnostics = []

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
        diagnostics_callback=diagnostics.append,
    )

    assert len(diagnostics) == 1
    payload = diagnostics[0]
    existing = {
        "query_count": 1,
        "graph_count": 2,
        "task_count": 2,
        "chunks_considered": 24,
        "chunks_written": 24,
        "loaded_pixels": 384,
    }
    for key, value in existing.items():
        assert payload[key] == value
    for new_key in (
        "statistics_prepare_seconds", "stac_read_seconds", "active_window_count",
        "planned_native_pixels", "local_reduction_seconds",
    ):
        assert new_key in payload
