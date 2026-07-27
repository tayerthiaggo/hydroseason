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


def test_combine_observations_flat_selection():
    pytest.importorskip("xarray")
    import xarray as xr
    from hydroseason._io_geo import _combine_observations

    obs = xr.DataArray(
        np.array([
            [[1, 0], [-1, -2]],
            [[1, 0], [0, -2]],
            [[0, -1], [0, -2]],
        ], dtype=np.int8),
        dims=["time", "y", "x"],
    )

    combined = _combine_observations(obs, majority=True)
    expected = np.array([[1, 0], [0, -2]], dtype=np.int8)
    np.testing.assert_array_equal(combined.values, expected)


def test_combine_observations_exhaustive_parity():
    pytest.importorskip("xarray")
    import itertools
    import xarray as xr
    from hydroseason._io_geo import _combine_observations

    values = [1, 0, -1, -2]
    # Test all permutations of length 4
    all_combos = list(itertools.product(values, repeat=4))
    obs_arr = np.array(all_combos, dtype=np.int8).T  # shape (4, 256)
    obs = xr.DataArray(obs_arr, dims=["time", "x"])

    for maj in (True, False):
        res = _combine_observations(obs, majority=maj)
        # Verify result manually for each column
        for col_idx, col_vals in enumerate(all_combos):
            w = sum(1 for v in col_vals if v == 1)
            d = sum(1 for v in col_vals if v == 0)
            inv = sum(1 for v in col_vals if v == -1)

            w_wins = (w > 0) and ((w > d) if maj else True)
            if w_wins:
                expected_val = 1
            elif d > 0:
                expected_val = 0
            elif inv > 0:
                expected_val = -1
            else:
                expected_val = -2

            assert res.values[col_idx] == expected_val, f"Mismatch for combo {col_vals} with majority={maj}"


@pytest.mark.parametrize(
    "transform, expected",
    [
        pytest.param((30, 0, 0, 0, -30, 300), True, id="north-up"),
        pytest.param((30, 1, 0, 0, -30, 300), False, id="sheared"),
        pytest.param((30, 0, 0, 1, -30, 300), False, id="rotated"),
        pytest.param((-30, 0, 0, 0, 30, 300), False, id="flipped"),
    ],
)
def test_native_grid_alignment_rejects_rotated_or_flipped_source(transform, expected):
    pytest.importorskip("odc.geo")
    from affine import Affine
    from odc.geo.crs import CRS
    from odc.geo.geobox import GeoBox

    from hydroseason._io_geo import _geobox_native_aligned

    destination = GeoBox((10, 10), Affine(30, 0, 0, 0, -30, 300), CRS("EPSG:3577"))
    source = GeoBox((10, 10), Affine(*transform), CRS("EPSG:3577"))
    assert _geobox_native_aligned(source, destination) is expected


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


def test_csv_import_does_not_import_raster_stack(monkeypatch, tmp_path):
    csv_path = tmp_path / "extent.csv"
    csv_path.write_text("date,extent_pct\n2020-01-01,10\n", encoding="utf-8")
    for name in ("xarray", "dask", "zarr", "pystac_client", "odc.stac"):
        monkeypatch.setitem(sys.modules, name, None)

    from hydroseason.io import load_extent_csv

    assert load_extent_csv(csv_path).iloc[0]["extent_pct"] == 10


def test_load_aoi_validates_geometry_and_reprojects():
    from hydroseason.io import load_aoi

    loaded = load_aoi(_aoi(), to_crs=3857)

    assert not loaded.empty
    assert loaded.crs.to_epsg() == 3857


def test_query_wofs_items_uses_polygon_intersects(monkeypatch):
    from unittest.mock import Mock
    import pystac_client
    import hydroseason._io_geo as geo

    mock_client = Mock()
    mock_search = Mock(return_value=Mock(items=Mock(return_value=[])))
    mock_client.search = mock_search
    monkeypatch.setattr(pystac_client.Client, "open", lambda _url: mock_client)

    with pytest.raises(ValueError, match="No STAC items found"):
        geo._query_wofs_items(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2015-01-01", "2015-12-31",
        )

    mock_search.assert_called_once()
    kwargs = mock_search.call_args.kwargs
    assert "intersects" in kwargs
    assert "bbox" not in kwargs
    assert kwargs["limit"] == 1000



@pytest.mark.parametrize(
    "source_epsg, source_resolution, x_shift, y_shift, expected",
    [
        (3577, 30, 0, 0, True),
        (3577, 30, 30, -60, True),
        (3577, 30, 15, 0, False),
        (3577, 60, 0, 0, False),
        (4326, 30, 0, 0, False),
    ],
)
def test_native_grid_alignment(
    source_epsg, source_resolution, x_shift, y_shift, expected
):
    from affine import Affine
    from odc.geo.geobox import GeoBox
    from odc.geo.crs import CRS
    from hydroseason._io_geo import _geobox_native_aligned

    destination = GeoBox(
        (10, 10), Affine(30, 0, 0, 0, -30, 300), CRS(3577)
    )
    source = GeoBox(
        (10, 10),
        Affine(
            source_resolution,
            0,
            x_shift,
            0,
            -source_resolution,
            300 + y_shift,
        ),
        CRS(source_epsg),
    )
    assert _geobox_native_aligned(source, destination) is expected


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

    from hydroseason.hydro_year import monthly_water_extent
    from hydroseason.io import _clip_to_aoi

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


def test_clip_once_on_cube_matches_per_slice_clip():
    """Clipping a whole (time, y, x) cube once is byte-identical to clipping
    each time slice separately -- the invariant the once-per-cube optimisation
    in _load_wofs_items relies on."""
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("rioxarray")
    geopandas = pytest.importorskip("geopandas")
    import rioxarray  # noqa: F401
    from shapely.geometry import box

    from hydroseason.io import _clip_to_aoi

    ny = nx = 12
    # Three canonical slices with different water/dry/invalid/outside patterns
    # so the clip + invalid-marking path is exercised, not just all-ones.
    rng = np.random.default_rng(0)
    values = rng.choice(
        np.array([-1, 0, 1], dtype=np.int8), size=(3, ny, nx)
    ).astype(np.int8)
    cube = xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={
            "time": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"]),
            "y": np.arange(ny, 0, -1) - 0.5,
            "x": np.arange(nx) + 0.5,
        },
    ).rio.set_spatial_dims(x_dim="x", y_dim="y").rio.write_crs("EPSG:3577")

    # AOI covers the left half only, so right-half pixels become outside (-2).
    aoi = geopandas.GeoDataFrame(geometry=[box(0, 0, nx / 2, ny)], crs="EPSG:3577")

    once = _clip_to_aoi(cube, aoi)
    per_slice = xr.concat(
        [
            _clip_to_aoi(cube.isel(time=t), aoi).expand_dims(time=[cube.time.values[t]])
            for t in range(cube.sizes["time"])
        ],
        dim="time",
    )

    np.testing.assert_array_equal(
        np.asarray(once.values), np.asarray(per_slice.values)
    )


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


def test_stac_loader_defaults_to_solar_day_grouping(monkeypatch):
    """WOfS loads default to groupby='solar_day' so same-day tile-edge scenes
    are nodata-mosaicked into one plane before compositing."""
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("rioxarray")
    from unittest.mock import Mock

    from hydroseason.io import load_wofs_from_stac

    mock_item = Mock()
    mock_item.properties = {"datetime": "2020-01-01T00:00:00Z"}
    mock_ds = xr.Dataset(
        {"water": (("time", "y", "x"), np.ones((1, 2, 2), dtype=np.int8))},
        coords={"time": pd.to_datetime(["2020-01-01"]), "y": [0, 1], "x": [0, 1]},
    )
    mock_stac_load = Mock(return_value=mock_ds)
    monkeypatch.setattr("odc.stac.stac_load", mock_stac_load)

    mock_client_instance = Mock()
    mock_search_result = Mock()
    mock_search_result.items.return_value = [mock_item]
    mock_client_instance.search.return_value = mock_search_result
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=mock_client_instance))
    monkeypatch.setattr(
        "hydroseason.io._clip_to_aoi", Mock(return_value=mock_ds["water"])
    )

    load_wofs_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-01-01",
    )

    assert mock_stac_load.called
    assert mock_stac_load.call_args[1].get("groupby") == "solar_day"


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
    """Long direct ranges should pay one STAC search and one odc.stac load per year."""
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

    def fake_search(*, datetime, **kwargs):
        start, end = [pd.Timestamp(part) for part in datetime.split("/")]
        matched_items = [
            item for item in items
            if start <= pd.Timestamp(item.properties["datetime"]).tz_localize(None) <= end
        ]
        result = Mock()
        result.items.return_value = matched_items
        return result

    client.search.side_effect = fake_search
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=client))
    monkeypatch.setattr("hydroseason.io._clip_to_aoi", lambda mask, target: mask)

    result = load_wofs_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2021-01-31", resolution=100,
    )

    assert client.search.call_count == 1
    assert stac_load.call_count == 2
    assert result.sizes["time"] == 13


def test_stac_loader_retries_transient_search_failure(monkeypatch):
    """Transient STAC listing failures should retry before failing the AOI query."""
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("rioxarray")
    from unittest.mock import Mock

    from hydroseason.io import load_wofs_from_stac

    item = Mock()
    item.properties = {"datetime": "2020-01-05T00:00:00Z"}
    ds = xr.Dataset(
        {"water": (("time", "y", "x"), np.full((1, 2, 2), 128, dtype=np.uint16))},
        coords={"time": pd.to_datetime(["2020-01-05"]), "y": [0, 1], "x": [0, 1]},
    )

    attempts = {"n": 0}
    client = Mock()

    def fake_search(**kwargs):
        attempts["n"] += 1
        result = Mock()
        if attempts["n"] == 1:
            result.items.side_effect = RuntimeError("504 Gateway Time-out")
        else:
            result.items.return_value = [item]
        return result

    client.search.side_effect = fake_search
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=client))
    monkeypatch.setattr("odc.stac.stac_load", Mock(return_value=ds))
    monkeypatch.setattr("hydroseason.io._clip_to_aoi", lambda mask, target: mask)
    monkeypatch.setattr("hydroseason._io_geo.time.sleep", Mock())

    result = load_wofs_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-01-31", resolution=100,
    )

    assert attempts["n"] == 2
    assert result.sizes["time"] == 1


def test_stac_wrapper_queries_once_and_loads_the_returned_items(monkeypatch):
    from unittest.mock import Mock

    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("rioxarray")
    import hydroseason._io_geo as geo

    items = [object(), object()]
    query = Mock(return_value=(items, _aoi()))
    loaded = object()
    load_items = Mock(return_value=loaded)
    monkeypatch.setattr(geo, "_query_wofs_items", query)
    monkeypatch.setattr(geo, "_load_wofs_items", load_items)

    result = geo.load_wofs_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-02-29", crs=3577, resolution=30,
    )

    query.assert_called_once()
    assert load_items.call_args.args[0] is items
    assert load_items.call_args.kwargs["geobox"] is None
    assert result is loaded


def test_tile_slices_cover_parent_once_without_overlap():
    from hydroseason.io import _tile_slices

    coverage = np.zeros((2050, 1030), dtype=np.uint8)
    tiles = list(_tile_slices(coverage.shape, 1024))
    for _tile_id, ys, xs in tiles:
        coverage[ys, xs] += 1

    assert len(tiles) == 6
    assert coverage.min() == 1
    assert coverage.max() == 1
    assert tiles[-1] == ("r0002_c0001", slice(2048, 2050), slice(1024, 1030))


@pytest.mark.parametrize("tile_pixels", [0, -1])
def test_tile_slices_reject_non_positive_edge(tile_pixels):
    from hydroseason.io import _tile_slices

    with pytest.raises(ValueError, match="tile_pixels"):
        list(_tile_slices((100, 100), tile_pixels))


def test_tiled_reduction_matches_whole_cube_reduction_with_boundary_canonical_values():
    """Prove sum-then-percentage tiled aggregation is bit-exact vs. a whole-cube reduction.

    A 4x4 spatial grid with tile_pixels=2 forces exactly four non-overlapping
    2x2 tiles, cut between rows 1/2 and columns 1/2 (see
    test_tile_slices_cover_parent_once_without_overlap for the slicing
    contract). All four canonical values (1=water, 0=dry, -1=invalid inside
    the AOI, -2=outside the AOI) appear across the four months, and every
    -1/-2 pixel sits at one of (1,1), (1,2), (2,1), (2,2) -- the four corners
    of the center 2x2 block immediately flanking the tile boundary, one per
    tile -- so the equivalence is exercised exactly where a tiling bug would
    show up: values straddling the cut.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    from hydroseason._io_extent_cache import _aggregate_extent_parts
    from hydroseason.hydro_year import monthly_water_extent
    from hydroseason.io import _tile_slices

    # Month 1: water/dry only (baseline, no boundary values).
    month1 = np.array(
        [
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
        ],
        dtype=np.int8,
    )
    # Month 2: invalid (-1) at boundary corners (1,1) and (2,2).
    month2 = np.array(
        [
            [1, 0, 0, 1],
            [0, -1, 1, 0],
            [1, 0, -1, 0],
            [0, 1, 0, 1],
        ],
        dtype=np.int8,
    )
    # Month 3: outside-AOI (-2) at boundary corners (1,2) and (2,1).
    month3 = np.array(
        [
            [0, 1, 1, 0],
            [1, 0, -2, 1],
            [0, -2, 0, 1],
            [1, 0, 1, 0],
        ],
        dtype=np.int8,
    )
    # Month 4: all four canonical values, with -1 and -2 both on the
    # boundary but landing in different tiles than months 2/3 did.
    month4 = np.array(
        [
            [1, 1, -2, 0],
            [0, -1, 1, -2],
            [-1, 0, -2, 1],
            [1, -2, 0, -1],
        ],
        dtype=np.int8,
    )

    values = np.stack([month1, month2, month3, month4], axis=0)
    assert set(np.unique(values).tolist()) == {-2, -1, 0, 1}
    assert len(list(_tile_slices(values.shape[-2:], 2))) == 4

    dates = pd.date_range("2020-01-01", periods=4, freq="MS")
    cube = xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": dates, "y": np.arange(4), "x": np.arange(4)},
    ).chunk({"time": 1, "y": 2, "x": 2})

    whole = monthly_water_extent(cube, time_block=2)
    parts = [
        monthly_water_extent(cube.isel(y=ys, x=xs), time_block=2)
        for _tile_id, ys, xs in _tile_slices(cube.shape[-2:], 2)
    ]
    tiled = _aggregate_extent_parts(parts, whole.index)

    pd.testing.assert_frame_equal(tiled, whole, check_dtype=False)


def test_tiled_stac_iterator_queries_once_reuses_items_and_skips_cached_tiles(monkeypatch):
    from unittest.mock import Mock

    import hydroseason._io_geo as geo

    class FakeGeoBox:
        def __init__(self, shape, origin=(0, 0)):
            self.shape = shape
            self.origin = origin

        def __getitem__(self, roi):
            ys, xs = roi
            return FakeGeoBox(
                (ys.stop - ys.start, xs.stop - xs.start),
                (ys.start, xs.start),
            )

    items = [object(), object()]
    parent = FakeGeoBox(shape=(2048, 2048))
    query = Mock(return_value=(items, _aoi()))
    load_items = Mock(return_value="mask")
    monkeypatch.setattr(geo, "_query_wofs_items", query)
    monkeypatch.setattr(geo, "_output_geobox_for_aoi", Mock(return_value=parent))
    monkeypatch.setattr(geo, "_tile_intersects_aoi", Mock(return_value=True))
    monkeypatch.setattr(geo, "_load_wofs_items", load_items)

    result = list(geo.iter_wofs_tiles_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=1024,
        skip_tile_ids={"r0000_c0001"},
    ))

    query.assert_called_once()
    assert [tile_id for tile_id, _mask in result] == [
        "r0000_c0000", "r0001_c0000", "r0001_c0001",
    ]
    assert load_items.call_count == 3
    assert all(call.args[0] is items for call in load_items.call_args_list)
    assert all(call.kwargs["geobox"] is not None for call in load_items.call_args_list)


def test_tiled_stac_iterator_prunes_tiles_outside_wet_aoi(monkeypatch):
    """A tile that passes the user-AOI bbox test but fails the wet-AOI test
    must be skipped entirely, and the wet AOI must not otherwise influence
    which arguments reach ``_load_wofs_items`` (the user-AOI clip is untouched).
    """
    from unittest.mock import Mock

    import hydroseason._io_geo as geo

    class FakeGeoBox:
        def __init__(self, shape, origin=(0, 0)):
            self.shape = shape
            self.origin = origin

        def __getitem__(self, roi):
            ys, xs = roi
            return FakeGeoBox(
                (ys.stop - ys.start, xs.stop - xs.start),
                (ys.start, xs.start),
            )

    items = [object(), object()]
    parent = FakeGeoBox(shape=(2048, 2048))
    query = Mock(return_value=(items, _aoi()))
    load_items = Mock(return_value="mask")
    monkeypatch.setattr(geo, "_query_wofs_items", query)
    monkeypatch.setattr(geo, "_output_geobox_for_aoi", Mock(return_value=parent))
    monkeypatch.setattr(geo, "_tile_intersects_aoi", Mock(return_value=True))
    monkeypatch.setattr(geo, "_load_wofs_items", load_items)

    # Wet-AOI predicate: only the left-column tiles (c0000) are "wet"; the
    # right-column tiles (c0001) should be pruned before ever reaching
    # _load_wofs_items.
    def fake_wet_predicate(tile_geobox, wet_aoi):
        assert wet_aoi == "sentinel-wet-aoi"
        return tile_geobox.origin[1] == 0

    monkeypatch.setattr(geo, "tile_intersects_wet_aoi", fake_wet_predicate)

    result = list(geo.iter_wofs_tiles_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=1024,
        wet_aoi="sentinel-wet-aoi",
    ))

    query.assert_called_once()
    assert [tile_id for tile_id, _mask in result] == ["r0000_c0000", "r0001_c0000"]
    assert load_items.call_count == 2
    # The wet-AOI gate must not change what _load_wofs_items is called with:
    # aoi_gdf (the user AOI) is passed through unchanged for every loaded tile.
    for call in load_items.call_args_list:
        assert call.args[0] is items
        assert "wet_aoi" not in call.kwargs


def test_tiled_stac_iterator_loads_all_tiles_when_wet_aoi_is_none(monkeypatch):
    """Default ``wet_aoi=None`` must not prune anything (fail-open, unchanged
    behavior from before this parameter existed)."""
    from unittest.mock import Mock

    import hydroseason._io_geo as geo

    class FakeGeoBox:
        def __init__(self, shape, origin=(0, 0)):
            self.shape = shape
            self.origin = origin

        def __getitem__(self, roi):
            ys, xs = roi
            return FakeGeoBox(
                (ys.stop - ys.start, xs.stop - xs.start),
                (ys.start, xs.start),
            )

    items = [object(), object()]
    parent = FakeGeoBox(shape=(2048, 2048))
    query = Mock(return_value=(items, _aoi()))
    load_items = Mock(return_value="mask")
    monkeypatch.setattr(geo, "_query_wofs_items", query)
    monkeypatch.setattr(geo, "_output_geobox_for_aoi", Mock(return_value=parent))
    monkeypatch.setattr(geo, "_tile_intersects_aoi", Mock(return_value=True))
    monkeypatch.setattr(geo, "_load_wofs_items", load_items)

    result = list(geo.iter_wofs_tiles_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=1024,
    ))

    assert [tile_id for tile_id, _mask in result] == [
        "r0000_c0000", "r0000_c0001", "r0001_c0000", "r0001_c0001",
    ]
    assert load_items.call_count == 4


def test_wet_aoi_pruning_does_not_change_extent_pct(monkeypatch, tmp_path):
    """extent_pct with wet-AOI pruning == extent_pct without it (anti-drift).

    End-to-end integration test through ``load_wofs_monthly_extent`` with a
    real tiled fake-STAC scaffold: only the STAC network boundary
    (``pystac_client.Client.open``, ``odc.stac.stac_load``) and
    ``_output_geobox_for_aoi`` (which needs real ``pystac.Item`` proj
    metadata odc.stac cannot derive from bare mocks) are faked -- the same
    mocking altitude as ``test_tiled_stac_iterator_prunes_tiles_outside_wet_aoi``
    above. Every other step (``_load_wofs_items``, ``_clip_to_aoi``,
    ``_classify``, ``_tile_slices``, ``compute_wet_aoi``,
    ``tile_intersects_wet_aoi``, ``monthly_water_extent``,
    ``_aggregate_extent_parts``) runs for real.

    The parent AOI covers a 1x3 tile grid in EPSG:3577 (tile_pixels=2 over a
    2x6-pixel extent): only the leftmost 1-pixel-wide column (x in [0, 1),
    strictly inside tile ``r0000_c0000``'s [0, 2) span, leaving a real gap
    before the tile boundary at x=2 -- shapely's ``intersects`` treats
    boundary-touching polygons as intersecting, so the wet AOI must not
    reach all the way to a tile edge or every adjacent tile would trivially
    "intersect" it too) is water in every one of 12 months. Every other
    pixel, including the rest of ``r0000_c0000`` and all of tiles
    ``r0000_c0001`` and ``r0000_c0002``, is dry in every one of 12 months.
    Tiles ``c0001`` and ``c0002`` never contribute a wet pixel to the
    ever-wet union, so ``precompute_wet_aoi=True`` must prune both of them
    from the tiled load entirely. Because pruned tiles that were
    always-dry contribute zero water either way, ``extent_pct`` (measured
    against the user AOI, not the wet AOI) must be identical whether or not
    they are pruned.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("odc.geo")
    pytest.importorskip("rioxarray")
    geopandas = pytest.importorskip("geopandas")
    from unittest.mock import Mock

    from odc.geo.geobox import GeoBox
    from shapely.geometry import box

    import hydroseason._io_geo as geo
    from hydroseason._io_extent_cache import load_wofs_monthly_extent

    # Parent grid: 2 rows x 6 cols of 1m pixels in EPSG:3577, tiled 2x2 ->
    # a 1x3 tile grid (r0000_c0000 covers x in [0,2), r0000_c0001 covers x
    # in [2,4), r0000_c0002 covers x in [4,6)). See
    # test_tile_slices_cover_parent_once_without_overlap for the exact
    # tiling contract this relies on.
    parent_geobox = GeoBox.from_bbox((0, 0, 6, 2), crs="EPSG:3577", shape=(2, 6))
    aoi = geopandas.GeoDataFrame(geometry=[box(0, 0, 6, 2)], crs="EPSG:3577")

    dates = pd.date_range("2020-01-01", periods=12, freq="MS") + pd.Timedelta(days=4)

    class FakeItem:
        def __init__(self, date):
            self.properties = {"datetime": date.isoformat()}

    items = [FakeItem(d) for d in dates]

    def fake_search(*, datetime, **kwargs):
        start, end = [pd.Timestamp(part) for part in datetime.split("/")]
        matched = [
            item for item in items
            if start <= pd.Timestamp(item.properties["datetime"]).tz_localize(None) <= end
        ]
        result = Mock()
        result.items.return_value = matched
        return result

    client = Mock()
    client.search.side_effect = fake_search
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=client))
    monkeypatch.setattr(geo, "_output_geobox_for_aoi", Mock(return_value=parent_geobox))

    tile_x_origins = []

    def fake_stac_load(batch_items, *, geobox=None, geopolygon=None, **kwargs):
        batch_dates = pd.to_datetime(
            [item.properties["datetime"] for item in batch_items]
        ).tz_localize(None)
        gb = geobox if geobox is not None else parent_geobox
        ny, nx = gb.shape.y, gb.shape.x
        x0 = gb.affine.c  # x-origin of this geobox, in the parent CRS units
        if geobox is not None:
            tile_x_origins.append(x0)
        x_coords = np.asarray(gb.coordinates["x"].values)
        # Water only in the pixel column whose center falls in [0, 1) --
        # strictly inside r0000_c0000, never touching a tile boundary. Raw
        # WOfS encoding (128=water observed, 0=dry), matching
        # _load_wofs_items's encoding="wofs" classification.
        wet_column = (x_coords >= 0.0) & (x_coords < 1.0)
        row = np.where(wet_column, np.uint16(128), np.uint16(0))
        data = np.broadcast_to(row, (len(batch_dates), ny, nx)).copy()
        ds = xr.Dataset(
            {"water": (("time", "y", "x"), data)},
            coords={
                "time": batch_dates,
                "y": np.asarray(gb.coordinates["y"].values),
                "x": x_coords,
            },
        )
        return ds.rio.write_crs(gb.crs)

    stac_load_mock = Mock(side_effect=fake_stac_load)
    monkeypatch.setattr("odc.stac.stac_load", stac_load_mock)

    common = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-01-01",
        end_date="2020-12-31",
        resolution=1.0,
        crs=3577,
        tile_pixels=2,
    )

    unpruned = load_wofs_monthly_extent(**common, cache_dir=tmp_path / "a")
    tile_x_origins_unpruned = list(tile_x_origins)
    tile_x_origins.clear()

    pruned = load_wofs_monthly_extent(
        **common, cache_dir=tmp_path / "b", precompute_wet_aoi=True,
        # Tight to the wet pixels: default close_m/buffer_m are in meters
        # and would balloon far past this toy 6x2m grid, engulfing the
        # dry tiles too and defeating the point of this test.
        close_m=0.0, buffer_m=0.0,
    )
    tile_x_origins_pruned = list(tile_x_origins)

    # Sanity: pruning must actually have happened, or this test would pass
    # trivially without ever exercising the pruning path. Unpruned loads
    # all three tiles (x0=0, 2, 4); pruned loads only the tile containing
    # the wet column (x0=0) -- the two always-dry tiles are skipped
    # entirely.
    assert sorted(tile_x_origins_unpruned) == [0.0, 2.0, 4.0]
    assert tile_x_origins_pruned == [0.0]

    pd.testing.assert_series_equal(
        unpruned["extent_pct"], pruned["extent_pct"], check_names=False
    )


def test_externally_supplied_wet_aoi_does_not_prune_and_matches_unpruned_extent_pct(
    monkeypatch, tmp_path
):
    """A caller-supplied ``wet_aoi=`` (no ``precompute_wet_aoi``) must not prune.

    This is Task 8's fix: unlike the ``precompute_wet_aoi=True`` path (which
    keeps ``full_ts`` around to reconcile the tiled aggregate's denominator
    against), an externally-supplied ``wet_aoi`` has no such full-time-series
    cube to reconcile against here. Pruning tiles under it would silently
    shrink ``n_aoi``/``n_valid``/``n_invalid`` and corrupt ``extent_pct`` with
    no way to detect or correct it. So pruning must be automatically disabled
    (falls back to loading every tile, unpruned) whenever ``full_ts`` is
    ``None`` -- which is always true on this externally-supplied-``wet_aoi``
    path. This uses the identical tile-grid/fake-STAC scaffold as
    ``test_wet_aoi_pruning_does_not_change_extent_pct`` above: only the
    leftmost 1-pixel-wide column of tile ``r0000_c0000`` is ever wet; tiles
    ``r0000_c0001``/``r0000_c0002`` are always dry.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("odc.geo")
    pytest.importorskip("rioxarray")
    geopandas = pytest.importorskip("geopandas")
    from unittest.mock import Mock

    from odc.geo.geobox import GeoBox
    from shapely.geometry import box

    import hydroseason._io_geo as geo
    from hydroseason._io_extent_cache import load_wofs_monthly_extent

    parent_geobox = GeoBox.from_bbox((0, 0, 6, 2), crs="EPSG:3577", shape=(2, 6))
    aoi = geopandas.GeoDataFrame(geometry=[box(0, 0, 6, 2)], crs="EPSG:3577")

    # Hand-built wet AOI: covers only the wet column (x in [0, 1)), well
    # inside tile r0000_c0000's [0, 2) span and nowhere near a tile
    # boundary -- same rationale as the pruning test above (boundary-touching
    # polygons trivially "intersect" the neighboring tile too).
    externally_supplied_wet_aoi = geopandas.GeoDataFrame(
        geometry=[box(0, 0, 1, 2)], crs="EPSG:3577"
    )

    dates = pd.date_range("2020-01-01", periods=12, freq="MS") + pd.Timedelta(days=4)

    class FakeItem:
        def __init__(self, date):
            self.properties = {"datetime": date.isoformat()}

    items = [FakeItem(d) for d in dates]

    def fake_search(*, datetime, **kwargs):
        start, end = [pd.Timestamp(part) for part in datetime.split("/")]
        matched = [
            item for item in items
            if start <= pd.Timestamp(item.properties["datetime"]).tz_localize(None) <= end
        ]
        result = Mock()
        result.items.return_value = matched
        return result

    client = Mock()
    client.search.side_effect = fake_search
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=client))
    monkeypatch.setattr(geo, "_output_geobox_for_aoi", Mock(return_value=parent_geobox))

    tile_x_origins = []

    def fake_stac_load(batch_items, *, geobox=None, geopolygon=None, **kwargs):
        batch_dates = pd.to_datetime(
            [item.properties["datetime"] for item in batch_items]
        ).tz_localize(None)
        gb = geobox if geobox is not None else parent_geobox
        ny, nx = gb.shape.y, gb.shape.x
        x0 = gb.affine.c
        if geobox is not None:
            tile_x_origins.append(x0)
        x_coords = np.asarray(gb.coordinates["x"].values)
        wet_column = (x_coords >= 0.0) & (x_coords < 1.0)
        row = np.where(wet_column, np.uint16(128), np.uint16(0))
        data = np.broadcast_to(row, (len(batch_dates), ny, nx)).copy()
        ds = xr.Dataset(
            {"water": (("time", "y", "x"), data)},
            coords={
                "time": batch_dates,
                "y": np.asarray(gb.coordinates["y"].values),
                "x": x_coords,
            },
        )
        return ds.rio.write_crs(gb.crs)

    stac_load_mock = Mock(side_effect=fake_stac_load)
    monkeypatch.setattr("odc.stac.stac_load", stac_load_mock)

    common = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-01-01",
        end_date="2020-12-31",
        resolution=1.0,
        crs=3577,
        tile_pixels=2,
    )

    unpruned = load_wofs_monthly_extent(**common, cache_dir=tmp_path / "a")
    tile_x_origins.clear()

    with_external_wet_aoi = load_wofs_monthly_extent(
        **common, cache_dir=tmp_path / "b", wet_aoi=externally_supplied_wet_aoi,
    )
    tile_x_origins_external = list(tile_x_origins)

    # The fix: an externally-supplied wet_aoi (no precompute_wet_aoi, hence
    # no full_ts to reconcile against) must NOT prune -- every tile is still
    # loaded, proving the fallback-to-unpruned behavior is what actually
    # happened here, not an accidental no-op.
    assert sorted(tile_x_origins_external) == [0.0, 2.0, 4.0]

    pd.testing.assert_series_equal(
        unpruned["extent_pct"], with_external_wet_aoi["extent_pct"], check_names=False
    )


def test_tile_intersects_aoi_true_for_overlapping_tile():
    pytest.importorskip("odc.geo")
    from odc.geo.geobox import GeoBox

    from hydroseason._io_geo import _tile_intersects_aoi

    aoi = _aoi()  # box(0, 0, 2, 2) in EPSG:4326
    tile_geobox = GeoBox.from_bbox((1, 1, 3, 3), crs="EPSG:4326", shape=(10, 10))

    assert _tile_intersects_aoi(tile_geobox, aoi) is True


def test_tile_intersects_aoi_false_for_disjoint_tile():
    pytest.importorskip("odc.geo")
    from odc.geo.geobox import GeoBox

    from hydroseason._io_geo import _tile_intersects_aoi

    aoi = _aoi()  # box(0, 0, 2, 2) in EPSG:4326
    tile_geobox = GeoBox.from_bbox((100, 100, 110, 110), crs="EPSG:4326", shape=(10, 10))

    assert _tile_intersects_aoi(tile_geobox, aoi) is False


def test_output_geobox_for_aoi_raises_when_odc_returns_none(monkeypatch):
    pytest.importorskip("odc.stac")
    import odc.stac

    from hydroseason._io_geo import AOIRasterizationError, _output_geobox_for_aoi

    monkeypatch.setattr(odc.stac, "parse_items", lambda items: list(items))
    monkeypatch.setattr(odc.stac, "output_geobox", lambda *args, **kwargs: None)

    with pytest.raises(AOIRasterizationError, match="output GeoBox"):
        _output_geobox_for_aoi([object()], _aoi(), crs=3577, resolution=30)


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
        cache_dir=tmp_path,
        mask_cache_dir=tmp_path / "masks",
        force=True,
        time_block=6,
    )

    assert cached_load.call_count == 2
    for call in cached_load.call_args_list:
        assert call.kwargs["cache_dir"] == tmp_path
        assert call.kwargs["mask_cache_dir"] == tmp_path / "masks"
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


def test_canonical_masks_outside_aoi_pixels_excluded_from_counts():
    """Raster-level regression: outside-AOI -2 pixels never enter any count.

    This test proves that the canonical mask encoding (outside=-2, invalid=-1,
    dry=0, water=1) is correctly interpreted by monthly_water_extent such that
    only inside-AOI pixels contribute to the counts.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("dask")
    from hydroseason.hydro_year import monthly_water_extent

    # Create a canonical mask with:
    # - 2 outside-AOI pixels (-2): should not enter any count
    # - 1 invalid inside-AOI pixel (-1)
    # - 1 dry pixel (0)
    # - 2 water pixels (1)
    # Expected counts:
    # - n_water=2 (only the water pixels)
    # - n_aoi=4 (only inside-AOI: -1, 0, 1, 1)
    # - n_valid=3 (0 and two 1s)
    # - n_invalid=1 (one -1)
    # - extent_pct = 2/3 * 100 = 66.666...
    # - invalid_pct = 1/4 * 100 = 25.0
    values = np.array([[[-2, -2, -1], [0, 1, 1]]], dtype=np.int8)
    masks = xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(["2020-01-01"]), "y": [0, 1], "x": [0, 1, 2]},
    ).chunk({"time": 1, "y": 1, "x": 1})

    summary = monthly_water_extent(masks)
    row = summary.iloc[0]

    assert row["n_water"] == 2, f"expected n_water=2, got {row['n_water']}"
    assert row["n_valid"] == 3, f"expected n_valid=3, got {row['n_valid']}"
    assert row["n_invalid"] == 1, f"expected n_invalid=1, got {row['n_invalid']}"
    assert row["n_aoi"] == 4, f"expected n_aoi=4, got {row['n_aoi']}"
    assert row["extent_pct"] == pytest.approx(200.0 / 3.0), f"expected extent_pct≈66.67, got {row['extent_pct']}"
    assert row["invalid_pct"] == pytest.approx(25.0), f"expected invalid_pct=25.0, got {row['invalid_pct']}"
