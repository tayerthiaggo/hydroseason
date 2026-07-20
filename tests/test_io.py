import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _aoi():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import box

    return geopandas.GeoDataFrame(geometry=[box(0, 0, 2, 2)], crs="EPSG:4326")


def _write_binary_tif(path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    proj_data = Path(rasterio.__file__).parent / "proj_data"
    os.environ["PROJ_DATA"] = str(proj_data)
    os.environ["PROJ_LIB"] = str(proj_data)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 2, 1, 1),
    ) as dst:
        dst.write(np.array([[0, 1], [1, 0]], dtype=np.uint8), 1)


def test_csv_loader_imports_without_raster_dependencies(monkeypatch, tmp_path):
    for name in ("xarray", "dask", "rasterio", "geopandas", "zarr"):
        monkeypatch.setitem(sys.modules, name, None)
    sys.modules.pop("hydroseason.io", None)

    path = tmp_path / "extent.csv"
    path.write_text("date,extent_pct\n2020-01-01,25.0\n", encoding="utf-8")
    io = importlib.import_module("hydroseason.io")

    result = io.load_extent_csv(path)

    assert result.loc[pd.Timestamp("2020-01-01"), "extent_pct"] == 25.0


def test_load_aoi_validates_geometry_and_reprojects():
    from hydroseason.io import load_aoi

    loaded = load_aoi(_aoi(), to_crs=3857)

    assert not loaded.empty
    assert loaded.crs.to_epsg() == 3857


def test_load_aoi_rejects_empty_geometry_frame():
    geopandas = pytest.importorskip("geopandas")
    from hydroseason.io import load_aoi

    with pytest.raises(ValueError, match="empty"):
        load_aoi(geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326"))


def test_load_aoi_rejects_self_intersecting_geometry():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon
    from hydroseason.io import load_aoi

    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
    gdf = geopandas.GeoDataFrame(geometry=[bowtie], crs="EPSG:4326")

    with pytest.raises(ValueError, match="valid"):
        load_aoi(gdf)


def test_complete_monthly_axis_preserves_lazy_data_and_marks_missing_months():
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    from hydroseason.io import complete_monthly_axis

    masks = xr.DataArray(
        np.ones((2, 2, 2), dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(["2020-01-01", "2020-03-01"]), "y": [0, 1], "x": [0, 1]},
    ).chunk({"time": 1, "y": 1, "x": 1})

    completed = complete_monthly_axis(masks, "2020-01-01", "2020-03-01")

    assert completed.shape == (3, 2, 2)
    assert completed.chunks is not None
    assert completed.attrs["inserted_months"] == ["2020-02"]
    assert (completed.sel(time="2020-02-01").compute().values == -1).all()


def test_generic_raster_loader_requires_aoi(tmp_path):
    from hydroseason.io import load_monthly_masks

    _write_binary_tif(tmp_path / "water_scene_2020_01_01.tif")

    with pytest.raises(ValueError, match="AOI"):
        load_monthly_masks(tmp_path, "2020-01-01", "2020-01-01", encoding="binary")


def test_generic_raster_loader_requires_explicit_encoding_or_classifier(tmp_path):
    from hydroseason.io import load_monthly_masks

    _write_binary_tif(tmp_path / "water_scene_2020_01_01.tif")

    with pytest.raises(ValueError, match="encoding"):
        load_monthly_masks(tmp_path, "2020-01-01", "2020-01-01", aoi=_aoi())


def test_uint8_binary_masks_are_not_misclassified_as_wofs(tmp_path):
    from hydroseason.io import load_monthly_masks

    _write_binary_tif(tmp_path / "water_scene_2020_01_01.tif")

    masks = load_monthly_masks(
        tmp_path,
        "2020-01-01",
        "2020-01-01",
        aoi=_aoi(),
        encoding="binary",
        chunk_x=1,
        chunk_y=1,
    )

    assert masks.chunks is not None
    assert set(np.unique(masks.compute().values)) == {0, 1}


def test_clip_to_aoi_excludes_outside_pixels_from_water_denominator():
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("rioxarray")
    geopandas = pytest.importorskip("geopandas")
    import rioxarray  # noqa: F401
    from shapely.geometry import box
    from hydroseason.io import _clip_to_aoi
    from hydroseason.hydro_year import monthly_water_extent

    ny = nx = 16
    arr = xr.DataArray(
        np.ones((ny, nx), dtype=np.int8),
        dims=("y", "x"),
        coords={"y": np.arange(ny, 0, -1) - 0.5, "x": np.arange(nx) + 0.5},
    )
    arr = arr.rio.set_spatial_dims(x_dim="x", y_dim="y").rio.write_crs("EPSG:3577")

    aoi = geopandas.GeoDataFrame(geometry=[box(0, 0, 8, ny)], crs="EPSG:3577")

    clipped = _clip_to_aoi(arr, aoi)
    values = np.asarray(clipped.values)

    assert not (values == 0).any()
    assert set(np.unique(values)).issubset({-2, 1})

    cube = clipped.expand_dims(time=[np.datetime64("2020-01-01")]).chunk({"time": 1, "y": 1, "x": 1})
    summary = monthly_water_extent(cube)
    row = summary.iloc[0]

    assert row["n_aoi"] == ny * 8
    assert row["extent_pct"] == pytest.approx(100.0)


def test_raster_loader_fails_closed_when_aoi_cannot_reproject(tmp_path):
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import box
    from hydroseason.io import AOIRasterizationError, load_monthly_masks

    _write_binary_tif(tmp_path / "water_scene_2020_01_01.tif")
    no_crs_aoi = geopandas.GeoDataFrame(geometry=[box(0, 0, 2, 2)])

    with pytest.raises(AOIRasterizationError, match="AOI"):
        load_monthly_masks(
            tmp_path,
            "2020-01-01",
            "2020-01-01",
            aoi=no_crs_aoi,
            encoding="binary",
        )


def test_stac_loader_requires_aoi_before_optional_stac_imports():
    from hydroseason.io import load_wofs_from_stac

    with pytest.raises(ValueError, match="AOI"):
        load_wofs_from_stac("https://example.invalid/stac", "wofs", None, "2020-01-01", "2020-01-01")


def test_stac_loader_passes_resolution_to_stac_load(monkeypatch):
    """Test that resolution parameter is passed to odc.stac.stac_load when provided."""
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("rioxarray")
    from unittest.mock import Mock
    from hydroseason.io import load_wofs_from_stac

    # Mock the STAC client and items
    mock_item = Mock()
    mock_item.properties = {"datetime": "2020-01-01T00:00:00Z"}

    # Create a minimal mock Dataset to be returned by stac_load
    # (must have a "water" variable as a DataArray)
    mock_ds = xr.Dataset(
        {"water": (("time", "y", "x"), np.ones((1, 2, 2), dtype=np.int8))},
        coords={"time": pd.to_datetime(["2020-01-01"]), "y": [0, 1], "x": [0, 1]},
    )

    # Track calls to stac_load
    mock_stac_load = Mock(return_value=mock_ds)
    monkeypatch.setattr("odc.stac.stac_load", mock_stac_load)

    # Mock pystac_client.Client.open
    mock_client_instance = Mock()
    mock_search_result = Mock()
    mock_search_result.items.return_value = [mock_item]
    mock_client_instance.search.return_value = mock_search_result
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=mock_client_instance))

    # Mock _clip_to_aoi to avoid additional complications
    monkeypatch.setattr(
        "hydroseason.io._clip_to_aoi",
        Mock(return_value=mock_ds["water"]),
    )

    # Test with resolution=100
    load_wofs_from_stac(
        "https://example.invalid/stac",
        "wofs",
        _aoi(),
        "2020-01-01",
        "2020-01-01",
        resolution=100,
    )

    # Assert that stac_load was called with resolution and resampling kwargs
    assert mock_stac_load.called
    call_kwargs = mock_stac_load.call_args[1]
    assert call_kwargs.get("resolution") == 100
    assert call_kwargs.get("resampling") == "mode"


def test_stac_loader_omits_resolution_when_none(monkeypatch):
    """Test that resolution and resampling are NOT passed when resolution=None."""
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("rioxarray")
    from unittest.mock import Mock
    from hydroseason.io import load_wofs_from_stac

    # Mock the STAC client and items
    mock_item = Mock()
    mock_item.properties = {"datetime": "2020-01-01T00:00:00Z"}

    # Create a minimal mock Dataset to be returned by stac_load
    mock_ds = xr.Dataset(
        {"water": (("time", "y", "x"), np.ones((1, 2, 2), dtype=np.int8))},
        coords={"time": pd.to_datetime(["2020-01-01"]), "y": [0, 1], "x": [0, 1]},
    )

    # Track calls to stac_load
    mock_stac_load = Mock(return_value=mock_ds)
    monkeypatch.setattr("odc.stac.stac_load", mock_stac_load)

    # Mock pystac_client.Client.open
    mock_client_instance = Mock()
    mock_search_result = Mock()
    mock_search_result.items.return_value = [mock_item]
    mock_client_instance.search.return_value = mock_search_result
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=mock_client_instance))

    # Mock _clip_to_aoi to avoid additional complications
    monkeypatch.setattr(
        "hydroseason.io._clip_to_aoi",
        Mock(return_value=mock_ds["water"]),
    )

    # Test with resolution=None (default)
    load_wofs_from_stac(
        "https://example.invalid/stac",
        "wofs",
        _aoi(),
        "2020-01-01",
        "2020-01-01",
    )

    # Assert that stac_load was called WITHOUT resolution and resampling kwargs
    assert mock_stac_load.called
    call_kwargs = mock_stac_load.call_args[1]
    assert "resolution" not in call_kwargs
    assert "resampling" not in call_kwargs


def test_stac_loader_batches_months_into_annual_loads(monkeypatch):
    """Long ranges should pay one odc.stac load per year, not per month."""
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("rioxarray")
    from unittest.mock import Mock

    from hydroseason.io import load_wofs_from_stac

    dates = pd.to_datetime(["2020-01-05", "2020-02-05", "2020-03-05", "2021-01-05"])
    items = []
    for date in dates:
        item = Mock()
        item.properties = {"datetime": date.isoformat()}
        items.append(item)

    def fake_stac_load(batch_items, **kwargs):
        batch_dates = pd.to_datetime([item.properties["datetime"] for item in batch_items])
        return xr.Dataset(
            {"water": (("time", "y", "x"), np.full((len(batch_dates), 2, 2), 128, dtype=np.uint16))},
            coords={"time": batch_dates, "y": [0, 1], "x": [0, 1]},
        )

    stac_load = Mock(side_effect=fake_stac_load)
    monkeypatch.setattr("odc.stac.stac_load", stac_load)
    client = Mock()
    client.search.return_value.items.return_value = items
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=client))
    monkeypatch.setattr("hydroseason.io._clip_to_aoi", lambda mask, target: mask)

    result = load_wofs_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2021-01-31", resolution=100,
    )

    assert stac_load.call_count == 2
    assert result.sizes["time"] == 13


def test_classify_canonical_rejects_out_of_domain_codes():
    xr = pytest.importorskip("xarray")
    from hydroseason.io import _classify

    arr = xr.DataArray(
        np.array([[7, 200], [1, -1]], dtype=np.int16),
        dims=("y", "x"),
        coords={"y": [0, 1], "x": [0, 1]},
    )

    result = _classify(arr, "canonical", None)
    values = np.asarray(result.values)

    assert set(np.unique(values)).issubset({-2, -1, 0, 1})
    assert values[0, 0] == -1  # out-of-domain code 7
    assert values[0, 1] == -1  # would int8-wrap to -56 without the guard
    assert values[1, 0] == 1
    assert values[1, 1] == -1


def test_classify_canonical_nan_is_invalid_not_dry():
    xr = pytest.importorskip("xarray")
    from hydroseason.io import _classify

    arr = xr.DataArray(
        np.array([[np.nan, 1.0], [0.0, np.nan]]),
        dims=("y", "x"),
        coords={"y": [0, 1], "x": [0, 1]},
    )

    result = _classify(arr, "canonical", None)
    values = np.asarray(result.values)

    assert values[0, 0] == -1
    assert values[1, 1] == -1
    assert values[0, 1] == 1
    assert values[1, 0] == 0


def test_monthly_water_extent_raw_canonical_nan_is_invalid_not_dry():
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pd_module = pytest.importorskip("pandas")
    from hydroseason.hydro_year import monthly_water_extent

    masks = xr.DataArray(
        np.full((1, 2, 2), np.nan, dtype=float),
        dims=("time", "y", "x"),
        coords={"time": pd_module.to_datetime(["2020-01-01"])},
    ).chunk({"time": 1, "y": 1, "x": 1})

    summary = monthly_water_extent(masks)
    row = summary.iloc[0]

    assert row["invalid_pct"] == pytest.approx(100.0)
    assert not (row["extent_pct"] == 0.0 and row["invalid_pct"] == 0.0)


def test_classify_rejects_out_of_domain_classifier_output():
    xr = pytest.importorskip("xarray")
    from hydroseason.io import _classify

    arr = xr.DataArray(
        np.array([[5, 5], [5, 5]], dtype=np.int16),
        dims=("y", "x"),
        coords={"y": [0, 1], "x": [0, 1]},
    )

    def bad_classifier(a):
        return xr.full_like(a, 256)

    result = _classify(arr, None, bad_classifier)
    values = np.asarray(result.values)

    assert set(np.unique(values)).issubset({-2, -1, 0, 1})
    assert not (values == 0).any()


def test_zarr_loader_returns_lazy_canonical_cube(tmp_path):
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("zarr")
    from hydroseason.io import load_monthly_masks_zarr

    source = xr.Dataset(
        {"water_mask": (("time", "y", "x"), np.array([[[0, 1], [1, 0]]], dtype=np.int8))},
        coords={"time": pd.to_datetime(["2020-01-01"]), "y": [0, 1], "x": [0, 1]},
    )
    path = tmp_path / "masks.zarr"
    source.chunk({"time": 1, "y": 1, "x": 1}).to_zarr(path)

    masks = load_monthly_masks_zarr(path, "2020-01-01", "2020-01-01", chunk_x=1, chunk_y=1)

    assert masks.shape == (1, 2, 2)
    assert masks.chunks is not None


def _known_bbox_area_m2():
    """Independently reproject the test bbox with pyproj and return its area.

    Cross-checks ``plan_resolution``'s internal reprojection against a direct
    call to the same industry-standard library, rather than hard-coding a
    number derived from the implementation itself.
    """
    pyproj = pytest.importorskip("pyproj")
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32750", always_xy=True)
    lons, lats = [150.0, 150.1, 150.0, 150.1], [-32.0, -32.0, -31.9, -31.9]
    xs, ys = transformer.transform(lons, lats)
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


_BBOX_WGS84 = (150.0, -32.0, 150.1, -31.9)
_TARGET_CRS = "EPSG:32750"


def test_plan_resolution_picks_finest_resolution_that_fits_memory_budget():
    pytest.importorskip("pyproj")
    from hydroseason.io import plan_resolution

    area = _known_bbox_area_m2()
    bytes_per_scratch = 5
    time_chunk = 24
    # Hand-calculated: finest candidate (30 m) peak_gb from the same formula
    # the function must use; budget is set comfortably above it so 30 m must
    # be picked (it is the smallest candidate, i.e. the finest available).
    expected_peak_gb_30m = (area / 30**2) * time_chunk * bytes_per_scratch / 1e9
    assert expected_peak_gb_30m < 1.0  # sanity: budget below is a real discriminator

    resolution_m, peak_gb, floor_pp, reason = plan_resolution(
        _BBOX_WGS84, _TARGET_CRS, memory_budget_gb=1.0,
        bytes_per_scratch=bytes_per_scratch, time_chunk=time_chunk,
    )

    assert resolution_m == 30
    assert peak_gb == pytest.approx(expected_peak_gb_30m, rel=1e-6)
    assert reason == "ok"
    assert floor_pp == pytest.approx(100.0 / (area / 30**2), rel=1e-6)


def test_plan_resolution_signal_veto_when_amplitude_too_small_to_fit_both():
    pytest.importorskip("pyproj")
    from hydroseason.io import plan_resolution

    area = _known_bbox_area_m2()
    bytes_per_scratch = 5
    time_chunk = 24
    # Budget admits 100 m (peak ~0.0026 GB) but not 60 m (peak ~0.0072 GB), so
    # the memory-only pick is 100 m. Its noise floor (100 / n_pixels_at_100m)
    # is ~0.00461 pp. observed_amplitude_pp=0.02 sets the allowed floor to
    # SIGNAL_FLOOR_FRACTION * 0.02 = 0.002 pp, which the 100 m floor violates.
    # No coarser-or-equal-cost candidate can do better (floor only improves at
    # finer resolutions, which all cost more memory than the 100 m pick, the
    # finest the budget allows) -- so no candidate clears both constraints.
    budget_gb = (area / 100**2) * time_chunk * bytes_per_scratch / 1e9 * 1.5
    assert (area / 60**2) * time_chunk * bytes_per_scratch / 1e9 > budget_gb  # 60m must not fit

    resolution_m, peak_gb, floor_pp, reason = plan_resolution(
        _BBOX_WGS84, _TARGET_CRS, memory_budget_gb=budget_gb,
        observed_amplitude_pp=0.02,
        bytes_per_scratch=bytes_per_scratch, time_chunk=time_chunk,
    )

    assert reason == "signal_veto_no_fit"


def test_plan_resolution_reason_coarsened_when_budget_forces_coarser_but_signal_clears():
    pytest.importorskip("pyproj")
    from hydroseason.io import plan_resolution

    area = _known_bbox_area_m2()
    bytes_per_scratch = 5
    time_chunk = 24
    # Same budget as the signal-veto case (memory pick = 100 m), but a large
    # enough observed amplitude that 100 m's noise floor clears the bound.
    budget_gb = (area / 100**2) * time_chunk * bytes_per_scratch / 1e9 * 1.5

    resolution_m, peak_gb, floor_pp, reason = plan_resolution(
        _BBOX_WGS84, _TARGET_CRS, memory_budget_gb=budget_gb,
        observed_amplitude_pp=0.1,
        bytes_per_scratch=bytes_per_scratch, time_chunk=time_chunk,
    )

    assert resolution_m == 100
    assert reason == "coarsened"


def test_plan_resolution_flags_native_no_fit_when_even_coarsest_exceeds_budget():
    pytest.importorskip("pyproj")
    from hydroseason.io import plan_resolution

    area = _known_bbox_area_m2()
    bytes_per_scratch = 5
    time_chunk = 24
    peak_gb_300m = (area / 300**2) * time_chunk * bytes_per_scratch / 1e9
    budget_gb = peak_gb_300m / 2.0  # tighter than even the coarsest candidate

    resolution_m, peak_gb, floor_pp, reason = plan_resolution(
        _BBOX_WGS84, _TARGET_CRS, memory_budget_gb=budget_gb,
        bytes_per_scratch=bytes_per_scratch, time_chunk=time_chunk,
    )

    assert reason == "native_no_fit"


def _synthetic_monthly_mask(xr, np, pd, *, n_months, y, x, water_row_fraction):
    """Build a canonical water mask cube with a fixed fraction of wet rows.

    ``water_row_fraction`` of the ``y`` rows are set fully wet (1); the rest
    are fully dry (0). Every pixel is valid (no -1/-2 codes), so
    ``monthly_water_extent``'s ``extent_pct`` for each month equals
    ``water_row_fraction`` exactly (in percent) -- this gives full control
    over the mean water fraction the probe/guard compares, independent of
    resolution-specific resampling behaviour (which is mocked away here; the
    two passes differ only in the y/x shape supplied, standing in for what a
    coarser ``resolution=`` would have produced upstream in the real
    pipeline).
    """
    n_wet_rows = max(1, round(water_row_fraction * y))
    row = np.zeros(x, dtype=np.int8)
    wet_row = np.ones(x, dtype=np.int8)
    plane = np.stack([wet_row if i < n_wet_rows else row for i in range(y)])
    data = np.stack([plane for _ in range(n_months)])
    dates = pd.date_range("2020-01-01", periods=n_months, freq="MS")
    da = xr.DataArray(
        data,
        dims=("time", "y", "x"),
        coords={"time": dates, "y": np.arange(y), "x": np.arange(x)},
    )
    return da


def test_probe_amplitude_propagates_annual_cache_settings(monkeypatch, tmp_path):
    from unittest.mock import Mock

    import hydroseason.io as hio
    from hydroseason.io import probe_amplitude

    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    extent = pd.DataFrame(
        {
            "n_water": np.arange(1, 13),
            "n_aoi": [100] * 12,
            "n_valid": [100] * 12,
            "n_invalid": [0] * 12,
            "extent_pct": np.arange(1.0, 13.0),
            "invalid_pct": [0.0] * 12,
        },
        index=dates,
    )
    cached_load = Mock(return_value=extent)
    monkeypatch.setattr(hio, "load_wofs_monthly_extent", cached_load)

    probe_amplitude(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-12-31",
        cache_dir=tmp_path, force=True, time_block=6,
    )

    assert cached_load.call_count == 2
    for call in cached_load.call_args_list:
        assert call.kwargs["cache_dir"] == tmp_path
        assert call.kwargs["force"] is True
        assert call.kwargs["time_block"] == 6


def test_probe_amplitude_guard_fires_on_disproportionate_thin_channel_collapse(monkeypatch):
    """Braided/thin-channel case: water fraction collapses going one step coarser.

    Probe-resolution pass sees 30% of rows wet; the coarser pass sees only 5%
    wet -- a collapse to ~1/6 of the probe fraction, far below the 70%
    retention floor. The guard must fire: ``refuse_coarsen_past`` pinned to
    the probe resolution, and a non-empty, human-readable ``guard_caveat``.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    from hydroseason.io import probe_amplitude

    calls = {"n": 0}

    def fake_load_wofs_from_stac(stac_url, collection, aoi, start, end, *, crs=None, resolution=None, **kwargs):
        calls["n"] += 1
        fraction = 0.30 if calls["n"] == 1 else 0.05
        return _synthetic_monthly_mask(
            xr, np, pd, n_months=12, y=20, x=5, water_row_fraction=fraction
        )

    monkeypatch.setattr("hydroseason.io.load_wofs_from_stac", fake_load_wofs_from_stac)

    result = probe_amplitude(
        "https://example.invalid/stac", "wofs", _aoi(), "2020-01-01", "2020-12-01",
        crs=3577, probe_res_m=300,
    )

    assert calls["n"] == 2
    assert result["refuse_coarsen_past"] == 300
    assert isinstance(result["guard_caveat"], str) and result["guard_caveat"]
    assert 300 in result["water_fraction_by_res"]
    probe_fraction = result["water_fraction_by_res"][300]
    coarser_res = next(k for k in result["water_fraction_by_res"] if k != 300)
    coarser_fraction = result["water_fraction_by_res"][coarser_res]
    assert coarser_fraction < 0.70 * probe_fraction
    assert result["amplitude_pp"] >= 0.0


def test_probe_amplitude_guard_silent_on_stable_water_fraction(monkeypatch):
    """Normal cube: water fraction barely moves between probe and coarser pass.

    Both passes see 30% wet rows (a tiny difference within noise, not a
    disproportionate collapse), so retention is ~100% -- well above the 70%
    floor. The guard must stay silent: ``guard_caveat`` and
    ``refuse_coarsen_past`` both ``None``.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    from hydroseason.io import probe_amplitude

    calls = {"n": 0}

    def fake_load_wofs_from_stac(stac_url, collection, aoi, start, end, *, crs=None, resolution=None, **kwargs):
        calls["n"] += 1
        fraction = 0.30 if calls["n"] == 1 else 0.29
        return _synthetic_monthly_mask(
            xr, np, pd, n_months=12, y=20, x=5, water_row_fraction=fraction
        )

    monkeypatch.setattr("hydroseason.io.load_wofs_from_stac", fake_load_wofs_from_stac)

    result = probe_amplitude(
        "https://example.invalid/stac", "wofs", _aoi(), "2020-01-01", "2020-12-01",
        crs=3577, probe_res_m=300,
    )

    assert calls["n"] == 2
    assert result["guard_caveat"] is None
    assert result["refuse_coarsen_past"] is None
