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
