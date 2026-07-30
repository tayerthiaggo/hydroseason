"""Tests for native Zarr extraction script."""

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xarray")
pytest.importorskip("affine")

import xarray as xr
from affine import Affine


def test_extract_native_zarr_lifecycle(tmp_path):
    # We must insert scripts into sys.path to import it if it's not a package
    script_dir = Path(__file__).parent.parent / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
        
    from extract_native_zarr import extract_native_zarr

    aoi_file = tmp_path / "aoi.geojson"
    aoi_file.write_text('{"type": "FeatureCollection", "features": []}')

    cache_dir = tmp_path / "cache"

    # Mock load_wofs_from_stac to return a valid DataArray
    times = pd.date_range("2020-01-01", "2021-12-31", freq="MS")
    da = xr.DataArray(
        np.zeros((len(times), 2, 2), dtype=np.int8),
        dims=["time", "y", "x"],
        coords={
            "time": times,
            "y": [10.0, -10.0],
            "x": [10.0, 30.0],
        },
    )
    da = da.assign_coords(spatial_ref=0)
    transform = Affine(20.0, 0.0, 0.0, 0.0, -20.0, 20.0)
    da.coords["spatial_ref"].attrs["GeoTransform"] = (
        f"{transform.c} {transform.a} {transform.b} "
        f"{transform.f} {transform.d} {transform.e}"
    )
    da.coords["spatial_ref"].attrs["spatial_ref"] = "EPSG:3577"
    # rioxarray requires the rio accessor to be initialized, we can mock _resolve_raster_transform
    
    with patch("extract_native_zarr.load_wofs_from_stac", return_value=da), \
         patch("extract_native_zarr._resolve_raster_transform", return_value=transform):
         
        path = extract_native_zarr(
            aoi_path=aoi_file,
            start_date="2020-01-01",
            end_date="2021-12-31",
            cache_dir=cache_dir,
        )

    # verify years 2020 and 2021 were written
    import zarr
    tg = zarr.open_group(path, mode="r")
    assert "2020" in tg
    assert "2021" in tg

    ds_2020 = xr.open_zarr(path, group="2020")
    assert len(ds_2020["water"].time) == 12
    ds_2020.close()
