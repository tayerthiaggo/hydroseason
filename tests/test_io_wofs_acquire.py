from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import dask
import dask.array as da
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from affine import Affine
from shapely.geometry import box

from hydroseason._io_wofs_acquire import acquire_wofs_cache, load_or_build_cached_wet_aoi
import hydroseason._io_geo as geo

pytest.importorskip("rioxarray")


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
    monkeypatch.setattr(pystac_client.Client, "open", lambda _url: object())
    monkeypatch.setattr(geo, "_collect_stac_items", lambda *_args, **_kwargs: items)

    result, _aoi_gdf = geo._query_wofs_items(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31",
    )

    assert [item.id for item in result] == ["earlier", "same-day-a", "same-day-b"]


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

    assert diagnostics == [{
        "query_count": 1,
        "graph_count": 2,
        "task_count": 2,
        "chunks_considered": 24,
        "chunks_written": 24,
        "loaded_pixels": 384,
    }]


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
    monkeypatch.setattr("hydroseason._io_geo._clip_to_aoi", lambda mask, _aoi: mask)

    mask = _empty_year_mask(geobox, "2015-01-01", "2015-01-31", _aoi())

    assert max(mask.data.chunksize[1:]) <= 512


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

