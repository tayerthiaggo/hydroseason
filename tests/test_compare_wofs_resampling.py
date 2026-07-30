import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("xarray")

import xarray as xr


def _module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "compare_wofs_resampling.py"
    spec = importlib.util.spec_from_file_location("compare_wofs_resampling_under_test", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_windowed_comparison_avoids_full_cube_materialization():
    module = _module()
    safe = xr.DataArray(
        np.array([[[1, 0], [0, 1]], [[0, 1], [1, 0]]], dtype=np.int8),
        dims=("time", "y", "x"),
    ).chunk({"time": 1, "y": 1, "x": 1})
    aligned = safe.copy()
    from hydroseason._spatial_plan import GridWindow

    windows = (
        GridWindow("r0c0", 0, 1, 0, 1),
        GridWindow("r0c1", 0, 1, 1, 2),
        GridWindow("r1c0", 1, 2, 0, 1),
        GridWindow("r1c1", 1, 2, 1, 2),
    )

    result = module._compare_windowed(safe, aligned, windows, compute_batch_size=2)

    assert result["differing_pixels_total"] == 0
    assert result["differing_pixels_per_month"] == [0, 0]
    assert result["blocks_compared"] == 4


def test_windowed_digest_computes_one_policy_once():
    module = _module()
    cube = xr.DataArray(
        np.ones((2, 2, 2), dtype=np.int8), dims=("time", "y", "x")
    ).chunk({"time": 1, "y": 1, "x": 1})
    from hydroseason._spatial_plan import GridWindow

    digest = module._digest_windowed(
        cube,
        (GridWindow("r0c0", 0, 1, 0, 1), GridWindow("r0c1", 0, 1, 1, 2)),
        compute_batch_size=2,
    )

    assert digest["blocks_compared"] == 2
    assert digest["compute_seconds"] >= 0
