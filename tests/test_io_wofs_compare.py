"""Tests for strict categorical comparator."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr
from affine import Affine

from hydroseason._io_wofs_compare import count_categorical_mismatches
from hydroseason._io_geo import GeoreferencingError
import rioxarray


def _make_mask(data, transform: Affine = None, crs="EPSG:3577") -> xr.DataArray:
    data = np.asarray(data, dtype=np.int8)
    da = xr.DataArray(
        data,
        dims=["y", "x"],
        coords={"y": np.arange(data.shape[0]), "x": np.arange(data.shape[1])},
    )
    da = da.assign_coords(spatial_ref=0)
    transform = transform or Affine.identity()
    da.coords["spatial_ref"].attrs["GeoTransform"] = (
        f"{transform.c} {transform.a} {transform.b} "
        f"{transform.f} {transform.d} {transform.e}"
    )
    da.coords["spatial_ref"].attrs["spatial_ref"] = crs
    
    # We must also attach rio crs for _resolve_raster_crs
    da = da.rio.write_crs(crs)
    return da


def test_count_categorical_mismatches_exact_match():
    data = [[-2, 1], [0, -1]]
    baseline = _make_mask(data)
    test = _make_mask(data)
    
    total, mismatches = count_categorical_mismatches(baseline, test)
    # -2 is excluded. Valid domain has 3 pixels.
    assert total == 3
    assert mismatches == 0


def test_count_categorical_mismatches_with_differences():
    baseline = _make_mask([[-2, 1], [0, -1]])
    test = _make_mask([[-2, 0], [0, 1]])
    
    total, mismatches = count_categorical_mismatches(baseline, test)
    # 3 valid pixels.
    # [0,1] 1 vs 0 -> mismatch
    # [1,0] 0 vs 0 -> match
    # [1,1] -1 vs 1 -> mismatch
    assert total == 3
    assert mismatches == 2


def test_count_categorical_mismatches_rejects_shape():
    baseline = _make_mask([[1, 1], [1, 1]])
    test = _make_mask([[1, 1]])
    
    with pytest.raises(GeoreferencingError, match="mismatch|cannot validate"):
        count_categorical_mismatches(baseline, test)


def test_count_categorical_mismatches_rejects_transform():
    baseline = _make_mask([[1, 1]], transform=Affine.scale(30))
    test = _make_mask([[1, 1]], transform=Affine.scale(90))
    
    with pytest.raises(GeoreferencingError, match="mismatch|cannot validate"):
        count_categorical_mismatches(baseline, test)


def test_count_categorical_mismatches_rejects_crs():
    baseline = _make_mask([[1, 1]], crs="EPSG:3577")
    test = _make_mask([[1, 1]], crs="EPSG:4326")
    
    with pytest.raises(GeoreferencingError, match="mismatch|cannot validate"):
        count_categorical_mismatches(baseline, test)
