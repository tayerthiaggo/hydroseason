"""Regression tests: first-party code must not emit RuntimeWarning/SerializationWarning."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xarray")
pytest.importorskip("zarr")


def test_noise_floor_pp_handles_zero_variance_residual_without_warning():
    from hydroseason.hydro_year import _noise_floor_pp

    index = pd.date_range("2020-01-01", periods=6, freq="MS")
    flat = pd.Series(5.0, index=index)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = _noise_floor_pp(flat)

    assert result == 0.0


def test_derive_resolution_cache_writes_integer_zarr_without_serialization_warning(tmp_path):
    import xarray as xr

    from hydroseason._io_wofs_coarsen import derive_resolution_cache
    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOfSCacheIdentity,
        WOfSCacheRequest,
        create_cache_handle,
    )

    source_root = tmp_path / "source"
    target_root = tmp_path / "target"

    source_req = WOfSCacheRequest(
        stac_url="test",
        collection="test",
        aoi_sha256="123",
        start_date="2020-01-01",
        end_date="2020-12-31",
        crs="EPSG:3577",
        resolution=30.0,
        classifier_version=1,
        groupby="solar_day",
        majority=True,
        planner_version=1,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    source_identity = WOfSCacheIdentity.from_request(
        source_req,
        shape=(2, 2),
        transform=(0.0, 30.0, 0.0, 0.0, 0.0, -30.0),
    )
    source_handle = create_cache_handle(source_root, source_identity)

    data = np.array([[1, 1], [0, 0]], dtype=np.int8)
    da = xr.DataArray(
        data,
        dims=["y", "x"],
        coords={"y": np.arange(2), "x": np.arange(2), "spatial_ref": 0},
    )
    da.coords["spatial_ref"].attrs["GeoTransform"] = "0.0 30.0 0.0 0.0 0.0 -30.0"
    ds = xr.Dataset({"water": da})
    ds.to_zarr(source_handle.path, group="2020", mode="a")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        derive_resolution_cache(source_handle, target_root, factor=2)
