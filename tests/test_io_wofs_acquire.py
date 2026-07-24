from types import SimpleNamespace
from unittest.mock import Mock

import dask
import dask.array as da
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import box

from hydroseason._io_wofs_acquire import acquire_wofs_cache


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


def test_shared_graph_consumers_execute_delayed_source_once():
    calls = {"source": 0}

    @dask.delayed
    def source():
        calls["source"] += 1
        return np.arange(16, dtype=np.int8).reshape(4, 4)

    parent = da.from_delayed(source(), shape=(4, 4), dtype=np.int8)
    left, right = dask.compute(parent[:, :2], parent[:, 2:])
    assert calls["source"] == 1
    assert left.shape == right.shape == (4, 2)


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
