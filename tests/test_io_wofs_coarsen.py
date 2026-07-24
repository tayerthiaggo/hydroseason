"""Unit tests for spatial coarsening of WOfS categorical data."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr
from affine import Affine

from hydroseason._io_wofs_coarsen import (
    coarsen_canonical_mask,
    validate_resolution_factor,
)


def test_validate_resolution_factor_accepts_integers():
    assert validate_resolution_factor(30.0, 90.0) == 3
    assert validate_resolution_factor(30.0, 60.0) == 2
    assert validate_resolution_factor(30.0, 30.0) == 1
    assert validate_resolution_factor(30.0, 300.0) == 10


def test_validate_resolution_factor_rejects_non_integers_and_upscaling():
    with pytest.raises(ValueError, match="must be an integer multiple"):
        validate_resolution_factor(30.0, 45.0)
    with pytest.raises(ValueError, match="must be an integer multiple"):
        validate_resolution_factor(30.0, 10.0)


def _make_mask(data, transform: Affine = None) -> xr.DataArray:
    data = np.asarray(data, dtype=np.int8)
    da = xr.DataArray(
        data,
        dims=["y", "x"],
        coords={"y": np.arange(data.shape[0]), "x": np.arange(data.shape[1])},
    )
    if transform:
        da = da.assign_coords(spatial_ref=0)
        da.coords["spatial_ref"].attrs["GeoTransform"] = (
            f"{transform.c} {transform.a} {transform.b} "
            f"{transform.f} {transform.d} {transform.e}"
        )
    return da


def test_coarsen_categorical_rules():
    # 2x2 blocks
    # Block 1: all outside (-2)
    # Block 2: more water (1) than dry (0)
    # Block 3: more dry (0) than water (1)
    # Block 4: tie between water (1) and dry (0)
    # Block 5: no valid (-1)
    # Block 6: tie with invalid
    
    data = [
        # B1         B2         B3         B4         B5         B6
        [-2, -2,     1, 1,      0, 0,      1, 0,     -1, -1,      1, -1],
        [-2, -2,     1, 0,      0, 1,      0, 1,     -1, -2,      0, -1],
    ]
    
    da = _make_mask(data)
    result = coarsen_canonical_mask(da, factor=2)
    
    # B1: inside == 0 -> -2
    # B2: water (3) > dry (1) -> 1
    # B3: dry (3) > water (1) -> 0
    # B4: water (2) == dry (2) -> -1
    # B5: inside = 3, water = 0, dry = 0 -> tie/no valid -> -1
    # B6: inside = 3, water = 1, dry = 1 -> tie -> -1
    
    expected = [[-2, 1, 0, -1, -1, -1]]
    np.testing.assert_array_equal(result.values, expected)


def test_coarsen_padding_preserves_origin():
    # 3x3 data, factor 2 => needs 1 row/col padding
    data = [
        [ 1,  1,   0],
        [ 1,  0,   0],
        
        [ 0,  1,  -1],
    ]
    # Padded data conceptually:
    # 1  1 |  0 -2
    # 1  0 |  0 -2
    # -------------
    # 0  1 | -1 -2
    # -2 -2| -2 -2
    
    da = _make_mask(data)
    result = coarsen_canonical_mask(da, factor=2)
    
    assert result.shape == (2, 2)
    
    # B1 (top-left): water (3) > dry (1) -> 1
    # B2 (top-right): dry (2) > water (0) -> 0
    # B3 (bottom-left): tie water (1) == dry (1) -> -1
    # B4 (bottom-right): no valid -> -1
    
    expected = [
        [ 1,  0],
        [-1, -1]
    ]
    np.testing.assert_array_equal(result.values, expected)


def test_coarsen_updates_transform_and_coords():
    transform = Affine.translation(100.0, 500.0) * Affine.scale(30.0, -30.0)
    da = _make_mask([[1, 1], [1, 1]], transform=transform)
    
    result = coarsen_canonical_mask(da, factor=2)
    
    assert "spatial_ref" in result.coords
    new_transform_str = result.coords["spatial_ref"].attrs["GeoTransform"]
    parts = [float(p) for p in new_transform_str.split(" ")]
    new_transform = Affine.from_gdal(*parts)
    
    # Origin should be unchanged
    assert new_transform.c == 100.0
    assert new_transform.f == 500.0
    # Scale should be multiplied by 2
    assert new_transform.a == 60.0
    assert new_transform.e == -60.0
    
    # Check coordinates: center of first 60x60 pixel
    assert result.x[0].item() == 130.0
    assert result.y[0].item() == 470.0


def test_derived_cache_identity():
    from hydroseason._io_wofs_zarr import WOfSCacheIdentity, WOfSCacheRequest, WOFS_CACHE_SCHEMA_VERSION
    from hydroseason._io_wofs_coarsen import DerivedCacheIdentity

    req = WOfSCacheRequest(
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
    source = WOfSCacheIdentity.from_request(
        req,
        shape=(10, 10),
        transform=(0.0, 30.0, 0.0, 0.0, 0.0, -30.0),
    )
    derived = DerivedCacheIdentity(source_identity=source, factor=3)

    assert derived.start_date == "2020-01-01"
    assert derived.end_date == "2020-12-31"

    # The request_digest should match a request made with resolution 90.0
    expected_req = WOfSCacheRequest(
        stac_url="test",
        collection="test",
        aoi_sha256="123",
        start_date="2020-01-01",
        end_date="2020-12-31",
        crs="EPSG:3577",
        resolution=90.0,
        classifier_version=1,
        groupby="solar_day",
        majority=True,
        planner_version=1,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    assert derived.request_digest == expected_req.request_digest()

    assert derived.digest is not None
    assert derived.as_dict()["factor"] == 3


def test_derive_resolution_cache_lifecycle(tmp_path):
    import zarr
    import json
    from hydroseason._io_wofs_zarr import WOfSCacheRequest, WOfSCacheIdentity, create_cache_handle, WOFS_CACHE_SCHEMA_VERSION
    from hydroseason._io_wofs_coarsen import derive_resolution_cache

    source_root = tmp_path / "source"
    target_root = tmp_path / "target"

    source_req = WOfSCacheRequest(
        stac_url="test",
        collection="test",
        aoi_sha256="123",
        start_date="2020-01-01",
        end_date="2021-12-31",
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

    # Write dummy source data for 2020 and 2021
    da_2020 = _make_mask([[1, 1], [0, 0]])
    ds_2020 = xr.Dataset({"water": da_2020})
    ds_2020.to_zarr(source_handle.path, group="2020", mode="a")

    da_2021 = _make_mask([[1, 1], [1, 1]])
    ds_2021 = xr.Dataset({"water": da_2021})
    ds_2021.to_zarr(source_handle.path, group="2021", mode="a")

    # 1. Derive cache
    target_handle = derive_resolution_cache(
        source_handle, target_root, factor=2
    )

    # Check that both years were processed
    tg = zarr.open_group(target_handle.path, mode="r")
    assert "2020" in tg
    assert "2021" in tg

    ds_target_2020 = xr.open_zarr(target_handle.path, group="2020")
    # 2x2 with factor 2 => 1x1 block
    # 2020: 2 water, 2 dry => tie => -1
    assert ds_target_2020["water"].values[0, 0] == -1
    ds_target_2020.close()

    ds_target_2021 = xr.open_zarr(target_handle.path, group="2021")
    # 2021: 4 water => 1
    assert ds_target_2021["water"].values[0, 0] == 1
    ds_target_2021.close()

    # 2. Test completion resume (overwrite=False)
    # Delete 2021 from source to verify it skips instead of failing
    import shutil
    shutil.rmtree(source_handle.path / "2021")
    derive_resolution_cache(source_handle, target_root, factor=2, overwrite=False)
    
    # 2021 should still be in target, because it skipped
    tg = zarr.open_group(target_handle.path, mode="r")
    assert "2021" in tg

    # 3. Test corruption recovery
    # Corrupt 2020 in target
    (target_handle.path / "2020" / ".zgroup").unlink()
    
    # Run again
    derive_resolution_cache(source_handle, target_root, factor=2, overwrite=False)
    
    # It should have rebuilt 2020 (source still has it)
    ds_target_2020 = xr.open_zarr(target_handle.path, group="2020")
    assert ds_target_2020["water"].values[0, 0] == -1
    ds_target_2020.close()
