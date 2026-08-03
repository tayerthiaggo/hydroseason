"""Offline contracts for the opt-in bounded WOfS benchmark."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rioxarray  # noqa: F401 - registers the xarray ``rio`` accessor for grid fixtures.
import xarray as xr
from affine import Affine


@pytest.fixture
def benchmark_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_wofs_cache.py"
    spec = importlib.util.spec_from_file_location("benchmark_wofs_cache_under_test", script)
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _grid_data(values, *, transform=Affine(30, 0, 0, 0, -30, 60)):
    values = np.asarray(values)
    height, width = values.shape[-2:]
    x = transform.c + transform.a * (np.arange(width) + 0.5)
    y = transform.f + transform.e * (np.arange(height) + 0.5)
    dims = ("time", "y", "x") if values.ndim == 3 else ("y", "x")
    coords = {"y": y, "x": x}
    if values.ndim == 3:
        coords["time"] = pd.date_range("2015-01-01", periods=values.shape[0], freq="MS")
    return xr.DataArray(values, dims=dims, coords=coords).rio.write_crs(
        "EPSG:3577"
    ).rio.write_transform(transform)


def test_benchmark_parser_pins_only_bounded_cases_and_canonical_grid(benchmark_module):
    assert set(benchmark_module.CASES) == {"fitzroy", "gilbert"}
    assert benchmark_module.CASES["fitzroy"] == (
        benchmark_module.REPO_ROOT / "data" / "fitzroy_kimberley_aoi.geojson"
    )
    assert benchmark_module.CASES["gilbert"] == (
        benchmark_module.REPO_ROOT / "data" / "Gilbert_river_buffer.geojson"
    )
    assert benchmark_module.YEAR_START == "2015-01-01"
    assert benchmark_module.YEAR_END == "2015-12-31"
    assert benchmark_module.CRS == "EPSG:3577"
    assert benchmark_module.RESOLUTION == 30.0

    parser = benchmark_module._parser()
    assert parser.parse_args([]).cases == ["gilbert", "fitzroy"]
    with pytest.raises(SystemExit):
        parser.parse_args(["--case", "moonie"])


def test_benchmark_child_parser_allows_only_scientific_comparison_modes(benchmark_module):
    parser = benchmark_module._parser()
    assert parser.parse_args(["--mode", "historical_mask"]).mode == "historical_mask"
    for retired_mode in ("legacy", "cold", "warm"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--mode", retired_mode])


def test_exactness_compares_only_monthly_water_counts(tmp_path, benchmark_module):
    dates = pd.date_range("2015-01-01", periods=2, freq="MS")
    reference_path = tmp_path / "reference.csv"
    candidate_path = tmp_path / "candidate.csv"
    mismatch_path = tmp_path / "mismatch.csv"
    pd.DataFrame(
        {"n_water": [4, 2], "n_aoi": [12, 12], "invalid_pct": [0.0, 20.0]}, index=dates
    ).to_pickle(reference_path.with_suffix(".pkl"))
    pd.DataFrame(
        {"n_water": [4, 2], "n_aoi": [5, 5], "invalid_pct": [0.0, 60.0]}, index=dates
    ).to_pickle(candidate_path.with_suffix(".pkl"))
    pd.DataFrame(
        {"n_water": [4, 3], "n_aoi": [5, 5], "invalid_pct": [0.0, 60.0]}, index=dates
    ).to_pickle(mismatch_path.with_suffix(".pkl"))

    assert benchmark_module._assert_exact(
        {"frame_path": str(reference_path)}, {"frame_path": str(candidate_path)}
    ) is True
    assert benchmark_module._assert_exact(
        {"frame_path": str(reference_path)}, {"frame_path": str(mismatch_path)}
    ) is False


def test_containment_audit_counts_primary_water_outside_historical_mask(benchmark_module):
    primary_masks = _grid_data(
        np.array(
            [
            [[1, 0], [1, 1]],
            [[0, 1], [1, -2]],
            ],
            dtype=np.int8,
        )
    )
    historical_mask = _grid_data([[True, True], [False, True]])

    assert benchmark_module._containment_mismatch_count(primary_masks, historical_mask) == 2


def test_containment_audit_rejects_incompatible_grids(benchmark_module):
    with pytest.raises(ValueError, match="same spatial shape"):
        benchmark_module._containment_mismatch_count(
            _grid_data(np.ones((2, 2, 2), dtype=np.int8)),
            _grid_data(np.ones((3, 2), dtype=bool)),
        )


def test_containment_audit_rejects_equal_shape_shifted_grid(benchmark_module):
    primary_masks = _grid_data(np.ones((2, 2, 2), dtype=np.int8))
    shifted_historical_mask = _grid_data(
        np.ones((2, 2), dtype=bool), transform=Affine(30, 0, 30, 0, -30, 60)
    )

    with pytest.raises(ValueError, match="affine transform"):
        benchmark_module._containment_mismatch_count(
            primary_masks, shifted_historical_mask
        )


def test_planning_only_warm_reuses_cold_identity_without_network(
    tmp_path, monkeypatch, benchmark_module
):
    import hydroseason.io as io

    historical_mask = SimpleNamespace(
        mask=np.ones((2, 2), dtype=bool),
        crs="EPSG:3577",
        transform=(30, 0, 0, 0, -30, 60),
        resolution=(30, 30),
        shape=(2, 2),
    )
    planning_footprint = SimpleNamespace(digest="historical-derived-footprint")
    statistics_offline = []
    acquire_calls = []

    def load_mask(*_args, offline, **_kwargs):
        statistics_offline.append(offline)
        return historical_mask

    def build_footprint(mask):
        assert mask is historical_mask
        return planning_footprint

    def acquire(*_args, offline, planning_footprint, historical_water_mask, **_kwargs):
        acquire_calls.append(
            (offline, planning_footprint.digest, historical_water_mask)
        )
        return object()

    frame = pd.DataFrame(
        {"n_water": [1]}, index=pd.DatetimeIndex(["2015-01-01"])
    )
    monkeypatch.setattr(io, "load_or_build_historical_water_mask", load_mask)
    monkeypatch.setattr(io, "build_planning_footprint_from_historical_mask", build_footprint)
    monkeypatch.setattr(io, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(io, "open_completed_extent_counts", lambda *_args: frame)
    monkeypatch.setattr(io, "open_completed_mask_cache", lambda *_args: None)

    def child_args(run_kind):
        run_dir = tmp_path / run_kind
        return SimpleNamespace(
            case="fitzroy",
            mode="planning_only",
            run_kind=run_kind,
            cache_root=run_dir / "cache",
            historical_mask_cache=run_dir / "historical",
            frame=run_dir / "extent.csv",
            frame_pickle=run_dir / "extent.pkl",
            result=run_dir / "result.json",
            primary_mask=None,
            historical_mask=None,
            compute_batch_size=16,
            read_workers=0,
            resampling_policy="categorical_safe",
        )

    cold_args = child_args("cold")
    warm_args = child_args("warm")
    assert benchmark_module._child_run(cold_args) == 0
    assert benchmark_module._child_run(warm_args) == 0
    cold = benchmark_module.json.loads(cold_args.result.read_text(encoding="utf-8"))
    warm = benchmark_module.json.loads(warm_args.result.read_text(encoding="utf-8"))

    assert statistics_offline == [False, True]
    assert acquire_calls == [
        (False, "historical-derived-footprint", None),
        (True, "historical-derived-footprint", None),
    ]
    assert "total_seconds" in cold
    assert "total_seconds" in warm
