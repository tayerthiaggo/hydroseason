"""Tests for wet-AOI precompute: reducer, vectorizer, and tile intersection."""
import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("rioxarray")

from hydroseason._wet_aoi import compute_ever_wet


def _cube(values):
    """values: list of 2D int8 arrays, one per time step."""
    arr = np.stack(values).astype(np.int8)
    da = xr.DataArray(arr, dims=("time", "y", "x"),
                      coords={"time": range(len(values)),
                              "y": [0, 1], "x": [0, 1]})
    return da.rio.write_crs("EPSG:3577")


def test_ever_wet_default_includes_pixel_wet_once():
    # pixel (0,0) wet exactly once across 3 steps; rest always dry
    dry = np.zeros((2, 2), np.int8)
    wet_once = dry.copy()
    wet_once[0, 0] = 1
    cube = _cube([dry, wet_once, dry])

    result = compute_ever_wet(cube)  # persistence_min defaults to 0.0

    assert result.dims == ("y", "x")
    assert bool(result.sel(y=0, x=0)) is True
    assert bool(result.sel(y=1, x=1)) is False


def test_persistence_threshold_excludes_rare_pixel():
    dry = np.zeros((2, 2), np.int8)
    wet_once = dry.copy()
    wet_once[0, 0] = 1
    cube = _cube([dry, wet_once, dry])  # (0,0) wet 1 of 3 clear = 0.333

    included = compute_ever_wet(cube, persistence_min=0.3)
    excluded = compute_ever_wet(cube, persistence_min=0.5)

    assert bool(included.sel(y=0, x=0)) is True
    assert bool(excluded.sel(y=0, x=0)) is False


def test_persistence_denominator_is_clear_not_scene_count():
    # (0,0): wet once, invalid once, no dry -> clear_count=1, wet/clear=1.0
    dry = np.zeros((2, 2), np.int8)
    wet = dry.copy(); wet[0, 0] = 1
    invalid = dry.copy(); invalid[0, 0] = -1
    cube = _cube([wet, invalid, dry])
    # If denominator were scene_count (3): 1/3=0.33 -> excluded at 0.5
    # With clear denominator (wet+dry at that pixel = 1+1=2): 1/2=0.5 -> included at 0.5
    result = compute_ever_wet(cube, persistence_min=0.5)
    assert bool(result.sel(y=0, x=0)) is True


def _wet_grid(bool_2d, *, res=30.0):
    """Build a georeferenced boolean DataArray on a res-meter grid at origin."""
    h, w = bool_2d.shape
    da = xr.DataArray(
        np.asarray(bool_2d, dtype=bool),
        dims=("y", "x"),
        coords={"y": np.arange(h) * -res, "x": np.arange(w) * res},
    )
    return da.rio.write_crs("EPSG:3577").rio.write_transform()


def test_wet_aoi_polygon_buffers_outward_in_meters():
    from hydroseason._wet_aoi import wet_aoi_polygon
    grid = np.zeros((5, 5), bool)
    grid[2, 2] = True  # single wet pixel
    gdf = wet_aoi_polygon(_wet_grid(grid), close_m=0.0, buffer_m=300.0)
    assert len(gdf) == 1
    assert str(gdf.crs).endswith("3577")
    # one 30m pixel (~900 m2) buffered by 300m must be far larger than raw pixel
    assert gdf.geometry.area.iloc[0] > 300.0 ** 2


def test_wet_aoi_closing_connects_gap():
    from hydroseason._wet_aoi import wet_aoi_polygon
    # two wet pixels separated by one dry pixel horizontally, 30m apart
    grid = np.zeros((3, 5), bool)
    grid[1, 1] = True
    grid[1, 3] = True
    # closing radius >= the 30m gap should merge into ONE polygon; buffer 0
    gdf = wet_aoi_polygon(_wet_grid(grid), close_m=60.0, buffer_m=0.0)
    assert len(gdf) == 1
    assert gdf.geometry.iloc[0].geom_type in ("Polygon", "MultiPolygon")
    # merged extent spans both pixels: bounds width > 2 pixels
    minx, _, maxx, _ = gdf.total_bounds
    assert maxx - minx >= 60.0


def test_wet_aoi_polygon_empty_when_no_wet():
    from hydroseason._wet_aoi import wet_aoi_polygon
    grid = np.zeros((4, 4), bool)
    gdf = wet_aoi_polygon(_wet_grid(grid), buffer_m=300.0)
    assert gdf.empty or gdf.geometry.is_empty.all()
