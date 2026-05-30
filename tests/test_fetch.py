import importlib.util

import numpy as np
import pandas as pd
import pytest

from hydroseason.fetch import (
    get_monthly_silo_rainfall,
    get_monthly_era5_rainfall,
    rasterize_to_xarray_grid,
)


class _DummyGeoDataFrame:
    total_bounds = np.array([0.0, 0.0, 1.0, 1.0])

    def __len__(self):
        return 1

    def to_crs(self, *_args, **_kwargs):
        return self


def test_gcs_fetch_requires_gcsfs(monkeypatch):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "gcsfs":
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    with pytest.raises(ImportError, match="gcsfs is required"):
        get_monthly_era5_rainfall(
            "gs://example/store.zarr",
            _DummyGeoDataFrame(),
            2000,
            2000,
            show_progress=False,
        )


def test_rasterize_to_xarray_grid_smoke():
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    ds = xr.Dataset(
        coords={
            "latitude": np.array([0.5, 1.5]),
            "longitude": np.array([0.5, 1.5]),
        }
    )
    gdf = gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 1.0, 1.0)], crs="EPSG:4326")

    mask = rasterize_to_xarray_grid(gdf, ds)

    assert mask.shape == (2, 2)
    assert mask.dtype == bool
    assert bool(mask.values.any())


def test_silo_fetch_monthly_shape(monkeypatch):
    from pathlib import Path

    import xarray as xr

    def fake_year_dataset_path(year, _base_url, _cache_dir):
        return Path(f"{year}.monthly_rain.nc"), False

    def fake_open_dataset(path):
        year = int(str(path).split("/")[-1].split(".")[0])
        t = pd.date_range(f"{year}-01-01", periods=12, freq="MS")
        lat = np.array([-1.0, 0.0])
        lon = np.array([120.0, 121.0])
        rain = np.ones((12, 2, 2), dtype=float) * 10.0
        return xr.Dataset(
            data_vars={"monthly_rain": (("time", "lat", "lon"), rain)},
            coords={"time": t, "lat": lat, "lon": lon},
        )

    def fake_mask(
        _gdf,
        ds,
        lon_name="longitude",
        lat_name="latitude",
        **_kwargs,
    ):
        shape = (ds[lat_name].size, ds[lon_name].size)
        return xr.DataArray(
            np.ones(shape, dtype=bool),
            coords={lat_name: ds[lat_name], lon_name: ds[lon_name]},
            dims=(lat_name, lon_name),
        )

    monkeypatch.setattr(
        "hydroseason.fetch._silo_year_dataset_path",
        fake_year_dataset_path,
    )
    monkeypatch.setattr("xarray.open_dataset", fake_open_dataset)
    monkeypatch.setattr(
        "hydroseason.fetch.rasterize_to_xarray_grid",
        fake_mask,
    )

    out = get_monthly_silo_rainfall(
        _DummyGeoDataFrame(),
        2000,
        2001,
        show_progress=False,
    )

    assert len(out) == 24
    assert list(out.columns) == ["Date", "Year", "Month", "Rainfall_mm"]
    assert out["Year"].min() == 2000
    assert out["Year"].max() == 2001
