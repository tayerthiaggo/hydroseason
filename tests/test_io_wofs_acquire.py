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


def test_annual_writer_mask_and_local_counts_share_one_delayed_source(tmp_path):
    import zarr

    from hydroseason._io_wofs_zarr import (
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
        return np.array([[[1, 0], [-1, -2]]], dtype=np.int8)

    transform = Affine(30, 0, 1000, 0, -30, 2000)
    arr = da.from_delayed(source(), shape=(1, 2, 2), dtype=np.int8)
    mask = xr.DataArray(
        arr,
        dims=("time", "y", "x"),
        coords={
            "time": pd.DatetimeIndex(["2015-01-01"]),
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
        schema_version=1,
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
    np.testing.assert_array_equal(group["water_mask"][:], np.array([[[1, 0], [-1, -2]]], dtype=np.int8))
    np.testing.assert_array_equal(group["wet_count"][:], np.array([[1, 0], [0, 0]], dtype=np.uint16))
    np.testing.assert_array_equal(group["clear_count"][:], np.array([[1, 1], [0, 0]], dtype=np.uint16))


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
        schema_version=1,
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
