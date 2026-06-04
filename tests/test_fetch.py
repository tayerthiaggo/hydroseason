import importlib.util

import numpy as np
import pandas as pd
import pytest

from hydroseason.fetch import (
    _SystemProfile,
    _cache_key,
    _resolve_temporal_batch_years,
    _resolve_spatial_chunk,
    _resolve_time_chunk,
    get_monthly_aoi_rainfall,
    get_monthly_chirps_rainfall,
    get_monthly_silo_rainfall,
    get_monthly_era5_rainfall,
    infer_default_fetch_source,
    rasterize_to_xarray_grid,
)


class _DummyGeoDataFrame:
    total_bounds = np.array([120.0, -1.0, 121.0, 0.0])

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


def test_rasterize_to_xarray_grid_falls_back_for_tiny_polygon():
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    ds = xr.Dataset(
        coords={
            "latitude": np.array([0.0]),
            "longitude": np.array([10.0]),
        }
    )
    gdf = gpd.GeoDataFrame(
        geometry=[box(9.90, -0.10, 10.05, -0.01)],
        crs="EPSG:4326",
    )

    mask = rasterize_to_xarray_grid(
        gdf,
        ds,
        lon_step=0.25,
        lat_step=0.25,
    )

    assert mask.shape == (1, 1)
    assert bool(mask.values[0, 0])


def test_era5_fetch_handles_subgrid_aoi(monkeypatch):
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    time = pd.to_datetime(["2000-01-01T00:00:00", "2000-01-01T01:00:00"])
    lat = np.array([0.0, -0.25])
    lon = np.array([10.0, 10.25])
    rain = np.ones((2, 2, 2), dtype=float)
    ds = xr.Dataset(
        data_vars={
            "tp": (("time", "latitude", "longitude"), rain),
        },
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    gdf = gpd.GeoDataFrame(
        geometry=[box(9.90, -0.10, 10.05, -0.01)],
        crs="EPSG:4326",
    )

    monkeypatch.setattr("xarray.open_zarr", lambda *args, **kwargs: ds)

    out = get_monthly_era5_rainfall(
        "era5-test.zarr",
        gdf,
        2000,
        2000,
        show_progress=False,
    )

    assert len(out) == 1
    assert list(out.columns) == ["Date", "Year", "Month", "Rainfall_mm"]
    assert out.loc[0, "Rainfall_mm"] == 2000.0


def test_era5_fetch_uses_configurable_time_chunks(monkeypatch):
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    time = pd.to_datetime(["2000-01-01T00:00:00", "2000-01-01T01:00:00"])
    lat = np.array([0.0, -0.25])
    lon = np.array([10.0, 10.25])
    rain = np.ones((2, 2, 2), dtype=np.float32)
    ds = xr.Dataset(
        data_vars={"tp": (("time", "latitude", "longitude"), rain)},
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    gdf = gpd.GeoDataFrame(
        geometry=[box(9.90, -0.10, 10.05, 0.10)],
        crs="EPSG:4326",
    )
    calls: list[dict] = []

    def fake_open_zarr(*_args, **kwargs):
        calls.append(kwargs)
        return ds

    monkeypatch.setattr("xarray.open_zarr", fake_open_zarr)

    get_monthly_era5_rainfall(
        "era5-test.zarr",
        gdf,
        2000,
        2000,
        time_chunk=6,
        show_progress=False,
    )

    assert calls[0]["chunks"]["time"] == 6
    assert "storage_options" not in calls[0]


def test_era5_fetch_preserves_light_monthly_accumulations(monkeypatch):
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    time = pd.to_datetime(["2000-01-01T00:00:00"])
    lat = np.array([0.0, -0.25])
    lon = np.array([10.0, 10.25])
    # ERA5 rainfall is metres; 0.0005 m is 0.5 mm after unit conversion.
    rain = np.full((1, 2, 2), 0.0005, dtype=np.float32)
    ds = xr.Dataset(
        data_vars={"tp": (("time", "latitude", "longitude"), rain)},
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    gdf = gpd.GeoDataFrame(
        geometry=[box(9.90, -0.10, 10.05, 0.10)],
        crs="EPSG:4326",
    )

    monkeypatch.setattr("xarray.open_zarr", lambda *args, **kwargs: ds)

    out = get_monthly_era5_rainfall(
        "era5-test.zarr",
        gdf,
        2000,
        2000,
        show_progress=False,
    )

    assert out.loc[0, "Rainfall_mm"] == 0.5


def test_era5_fetch_auto_chunks_open_zarr_time(monkeypatch):
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    time = pd.date_range("2000-01-01", periods=48, freq="h")
    lat = np.linspace(-3.0, 3.0, 60)
    lon = np.linspace(100.0, 106.0, 80)
    rain = np.ones((48, 60, 80), dtype=np.float32)
    ds = xr.Dataset(
        data_vars={"tp": (("time", "latitude", "longitude"), rain)},
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    gdf = gpd.GeoDataFrame(
        geometry=[box(100.1, -2.9, 105.9, 2.9)],
        crs="EPSG:4326",
    )

    calls: list[dict] = []

    def fake_open_zarr(*_args, **kwargs):
        calls.append(kwargs)
        return ds

    monkeypatch.setattr("xarray.open_zarr", fake_open_zarr)
    monkeypatch.setattr(
        "hydroseason.fetch._detect_system_profile",
        lambda: _SystemProfile(cpu_count=32, memory_gib=64.0),
    )

    out = get_monthly_era5_rainfall(
        "era5-test.zarr",
        gdf,
        2000,
        2000,
        spatial_chunk="auto",
        time_chunk="auto",
        show_progress=False,
    )

    assert len(out) == 1
    assert calls
    assert calls[0]["chunks"]["time"] == 120


def test_chunk_resolvers_validate_positive_ints():
    profile = _SystemProfile(cpu_count=8, memory_gib=16.0)

    with pytest.raises(ValueError, match="spatial_chunk"):
        _resolve_spatial_chunk(0, profile=profile)
    with pytest.raises(ValueError, match="time_chunk"):
        _resolve_time_chunk(-1, profile=profile)
    with pytest.raises(ValueError, match="temporal_batch_years"):
        _resolve_temporal_batch_years(
            0,
            start_year=2000,
            end_year=2005,
            profile=profile,
        )


def test_era5_fetch_temporal_batching_matches_single_batch(monkeypatch):
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    time = pd.to_datetime(
        [
            "2000-12-31T22:00:00",
            "2000-12-31T23:00:00",
            "2001-01-01T00:00:00",
            "2001-01-01T01:00:00",
        ]
    )
    lat = np.array([0.0, -0.25])
    lon = np.array([10.0, 10.25])
    rain = np.ones((4, 2, 2), dtype=np.float32)
    ds = xr.Dataset(
        data_vars={"tp": (("time", "latitude", "longitude"), rain)},
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    gdf = gpd.GeoDataFrame(
        geometry=[box(9.90, -0.10, 10.25, 0.10)],
        crs="EPSG:4326",
    )

    monkeypatch.setattr("xarray.open_zarr", lambda *args, **kwargs: ds)

    out_single = get_monthly_era5_rainfall(
        "era5-test.zarr",
        gdf,
        2000,
        2001,
        temporal_batch_years=5,
        show_progress=False,
    )
    out_yearly = get_monthly_era5_rainfall(
        "era5-test.zarr",
        gdf,
        2000,
        2001,
        temporal_batch_years=1,
        show_progress=False,
    )

    pd.testing.assert_frame_equal(out_single, out_yearly)


def test_era5_fetch_uses_single_overall_progress_bar(monkeypatch, capsys):
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    time = pd.to_datetime(
        [
            "2000-01-01T00:00:00",
            "2001-01-01T00:00:00",
        ]
    )
    lat = np.array([0.0, -0.25])
    lon = np.array([10.0, 10.25])
    rain = np.ones((2, 2, 2), dtype=np.float32)
    ds = xr.Dataset(
        data_vars={"tp": (("time", "latitude", "longitude"), rain)},
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    gdf = gpd.GeoDataFrame(
        geometry=[box(9.90, -0.10, 10.25, 0.10)],
        crs="EPSG:4326",
    )

    monkeypatch.setattr("xarray.open_zarr", lambda *args, **kwargs: ds)

    get_monthly_era5_rainfall(
        "era5-test.zarr",
        gdf,
        2000,
        2001,
        temporal_batch_years=1,
        show_progress=True,
    )

    err = capsys.readouterr().err
    assert "ERA5" in err
    assert "2/2 years" in err
    assert "processing 2000" in err
    assert "processing 2001" in err


def test_chirps_fetch_monthly_shape(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        geometry=[box(10.0, -5.0, 11.0, -4.0)],
        crs="EPSG:4326",
    )

    def fake_read_chirps_month(_gdf, url):
        month = int(str(url).split(".")[-2])
        return float(month)

    monkeypatch.setattr(
        "hydroseason.fetch._read_chirps_month",
        fake_read_chirps_month,
    )

    out = get_monthly_chirps_rainfall(
        gdf,
        2000,
        2000,
        base_url="https://example.test/chirps/cogs",
        show_progress=False,
    )

    assert len(out) == 12
    assert out.loc[0, "Rainfall_mm"] == 1.0
    assert set(["Data_Source", "Data_Product", "Fetch_Note"]).issubset(out.columns)
    assert out["Data_Source"].unique().tolist() == ["CHIRPS"]


def test_auto_fetch_routes_australian_aoi_to_silo(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        geometry=[box(120.0, -20.0, 121.0, -19.0)],
        crs="EPSG:4326",
    )
    calls: dict[str, object] = {}

    def fake_silo(**kwargs):
        calls["silo"] = kwargs
        return pd.DataFrame(
            {
                "Date": ["2000-01-01"],
                "Year": [2000],
                "Month": [1],
                "Rainfall_mm": [10.0],
            }
        )

    monkeypatch.setattr("hydroseason.fetch.get_monthly_silo_rainfall", fake_silo)

    out = get_monthly_aoi_rainfall(
        gdf,
        2000,
        2000,
        source="auto",
        show_progress=False,
    )

    assert infer_default_fetch_source(gdf) == "silo"
    assert "silo" in calls
    assert out["Data_Source"].unique().tolist() == ["SILO"]


def test_chirps_auto_uses_era5_for_pre_chirps_years(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        geometry=[box(10.0, -5.0, 11.0, -4.0)],
        crs="EPSG:4326",
    )

    def fake_era5(**kwargs):
        year = kwargs["start_year"]
        dates = pd.date_range(f"{year}-01-01", periods=12, freq="MS")
        return pd.DataFrame(
            {
                "Date": dates.strftime("%Y-%m-%d"),
                "Year": dates.year,
                "Month": dates.month,
                "Rainfall_mm": 5.0,
            }
        )

    def fake_chirps(_gdf, start_year, end_year, **_kwargs):
        dates = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-01", freq="MS")
        return pd.DataFrame(
            {
                "Date": dates.strftime("%Y-%m-%d"),
                "Year": dates.year,
                "Month": dates.month,
                "Rainfall_mm": 10.0,
                "Data_Source": "CHIRPS",
                "Data_Product": "CHIRPS v3 monthly COG",
                "Fetch_Note": "CHIRPS v3 monthly rainfall; land-only; 60S-60N",
            }
        )

    monkeypatch.setattr("hydroseason.fetch.get_monthly_era5_rainfall", fake_era5)
    monkeypatch.setattr(
        "hydroseason.fetch.get_monthly_chirps_rainfall",
        fake_chirps,
    )

    out = get_monthly_aoi_rainfall(
        gdf,
        1980,
        1981,
        source="chirps",
        era5_zarr_path="gs://example/era5.zarr",
        show_progress=False,
    )

    assert len(out) == 24
    assert out["Data_Source"].tolist()[:12] == ["ERA5"] * 12
    assert out["Data_Source"].tolist()[12:] == ["CHIRPS"] * 12
    assert out["Fetch_Note"].str.contains("mixed-source").all()


def test_chirps_auto_uses_era5_for_unavailable_chirps_months(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        geometry=[box(10.0, -5.0, 11.0, -4.0)],
        crs="EPSG:4326",
    )

    def fake_chirps(_gdf, start_year, end_year, **_kwargs):
        assert start_year == 1981
        assert end_year == 1981
        return pd.DataFrame(
            {
                "Date": ["1981-01-01"],
                "Year": [1981],
                "Month": [1],
                "Rainfall_mm": [10.0],
                "Data_Source": ["CHIRPS"],
                "Data_Product": ["CHIRPS v3 monthly COG"],
                "Fetch_Note": ["CHIRPS partial"],
            }
        )

    def fake_era5(**kwargs):
        dates = pd.date_range(
            f"{kwargs['start_year']}-01-01",
            f"{kwargs['end_year']}-12-01",
            freq="MS",
        )
        return pd.DataFrame(
            {
                "Date": dates.strftime("%Y-%m-%d"),
                "Year": dates.year,
                "Month": dates.month,
                "Rainfall_mm": 5.0,
            }
        )

    monkeypatch.setattr(
        "hydroseason.fetch.get_monthly_chirps_rainfall",
        fake_chirps,
    )
    monkeypatch.setattr("hydroseason.fetch.get_monthly_era5_rainfall", fake_era5)

    out = get_monthly_aoi_rainfall(
        gdf,
        1981,
        1981,
        source="chirps",
        era5_zarr_path="gs://example/era5.zarr",
        show_progress=False,
    )

    assert len(out) == 12
    assert out.loc[0, "Data_Source"] == "CHIRPS"
    assert out["Data_Source"].tolist()[1:] == ["ERA5"] * 11
    assert out["Fetch_Note"].str.contains("mixed-source").all()


def test_chirps_raster_not_found_uses_era5_fallback(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        geometry=[box(10.0, -5.0, 11.0, -4.0)],
        crs="EPSG:4326",
    )
    calls = []

    def fake_chirps(*_args, **_kwargs):
        raise FileNotFoundError("CHIRPS raster unavailable")

    def fake_era5(**kwargs):
        calls.append(kwargs)
        dates = pd.date_range("1981-01-01", periods=12, freq="MS")
        return pd.DataFrame(
            {
                "Date": dates.strftime("%Y-%m-%d"),
                "Year": dates.year,
                "Month": dates.month,
                "Rainfall_mm": 5.0,
            }
        )

    monkeypatch.setattr(
        "hydroseason.fetch.get_monthly_chirps_rainfall",
        fake_chirps,
    )
    monkeypatch.setattr("hydroseason.fetch.get_monthly_era5_rainfall", fake_era5)

    out = get_monthly_aoi_rainfall(
        gdf,
        1981,
        1981,
        source="chirps",
        era5_zarr_path="gs://example/era5.zarr",
        show_progress=False,
    )

    assert len(calls) == 1
    assert out["Data_Source"].unique().tolist() == ["ERA5"]


def test_cache_key_distinguishes_same_bbox_different_geometry():
    import geopandas as gpd
    from shapely.geometry import Polygon, box

    full_box = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
    triangle = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs="EPSG:4326",
    )

    assert _cache_key("same", full_box, 2000, 2000, "rain") != _cache_key(
        "same",
        triangle,
        2000,
        2000,
        "rain",
    )


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


def test_silo_fetch_uses_single_overall_progress_bar(monkeypatch, capsys):
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

    get_monthly_silo_rainfall(
        _DummyGeoDataFrame(),
        2000,
        2001,
        show_progress=True,
    )

    err = capsys.readouterr().err
    assert "SILO" in err
    assert "2/2 years" in err
    assert "processing 2000" in err
    assert "processing 2001" in err


def test_chirps_auto_uses_era5_only_for_missing_years(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        geometry=[box(10.0, -5.0, 11.0, -4.0)],
        crs="EPSG:4326",
    )

    def fake_chirps(_gdf, start_year, end_year, **_kwargs):
        # Return incomplete CHIRPS data: missing months in 1981 and 1983, but not 1982
        return pd.DataFrame({
            "Date": ["1981-01-01", "1982-01-01", "1982-02-01"],
            "Year": [1981, 1982, 1982],
            "Month": [1, 1, 2],
            "Rainfall_mm": [10.0, 10.0, 10.0],
            "Data_Source": ["CHIRPS"] * 3,
            "Data_Product": ["CHIRPS v3 monthly COG"] * 3,
            "Fetch_Note": ["CHIRPS partial"] * 3,
        })

    era5_calls = []

    def fake_era5(**kwargs):
        era5_calls.append((kwargs.get("start_year"), kwargs.get("end_year")))
        dates = pd.date_range(
            f"{kwargs['start_year']}-01-01",
            f"{kwargs['end_year']}-12-01",
            freq="MS",
        )
        return pd.DataFrame({
            "Date": dates.strftime("%Y-%m-%d"),
            "Year": dates.year,
            "Month": dates.month,
            "Rainfall_mm": 5.0,
        })

    monkeypatch.setattr(
        "hydroseason.fetch.get_monthly_chirps_rainfall",
        fake_chirps,
    )
    monkeypatch.setattr("hydroseason.fetch.get_monthly_era5_rainfall", fake_era5)

    # We ask for years 1981 to 1982
    out = get_monthly_aoi_rainfall(
        gdf,
        1981,
        1982,
        source="chirps",
        era5_zarr_path="gs://example/era5.zarr",
        show_progress=False,
    )

    # 1981 is missing months, 1982 is missing months.
    # It should call fake_era5 individually for year 1981 and year 1982.
    assert (1981, 1981) in era5_calls
    assert (1982, 1982) in era5_calls
    # Should not call (1981, 1982) as a single multi-year range
    assert (1981, 1982) not in era5_calls
