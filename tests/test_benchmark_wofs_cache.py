"""Offline contracts for the opt-in bounded WOfS benchmark."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


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
    primary_masks = np.array(
        [
            [[1, 0], [1, 1]],
            [[0, 1], [1, -2]],
        ],
        dtype=np.int8,
    )
    historical_mask = np.array([[True, True], [False, True]])

    assert benchmark_module._containment_mismatch_count(primary_masks, historical_mask) == 2


def test_containment_audit_rejects_incompatible_grids(benchmark_module):
    with pytest.raises(ValueError, match="same spatial shape"):
        benchmark_module._containment_mismatch_count(
            np.ones((2, 2, 2), dtype=np.int8), np.ones((3, 2), dtype=bool)
        )
