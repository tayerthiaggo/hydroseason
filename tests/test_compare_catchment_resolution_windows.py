"""Offline tests for lower-reach native-vs-coarsened comparison script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "compare_catchment_resolution_windows.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "compare_catchment_resolution_windows_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod():
    m = _load_module()
    yield m
    sys.modules.pop(m.__name__, None)


def test_lower_reach_window_uses_downstream_outlet_and_builds_50km_square(mod):
    boundary = gpd.GeoDataFrame(
        {"area_km2": [200.0]},
        geometry=[box(0, -1_000, 100_000, 1_000)],
        crs="EPSG:3577",
    )
    streams = gpd.GeoDataFrame(
        {
            "hydroid": [1, 2, 3, 4],
            "nextdownid": [2, 3, 999, 999],
            "hierarchy": ["Major", "Major", "Major", "Minor"],
            "upstrdarea": [10.0, 50.0, 100.0, 1_000.0],
        },
        geometry=[
            LineString([(0, 0), (10_000, 0)]),
            LineString([(10_000, 0), (50_000, 0)]),
            LineString([(50_000, 0), (90_000, 0)]),
            LineString([(40_000, 500), (45_000, 500)]),
        ],
        crs="EPSG:3577",
    )

    window = mod.build_lower_reach_window(
        "toy", boundary, streams, side_km=50.0, output_crs=3577
    )

    assert window.lower_hydroid == 3
    assert window.lower_point.x == pytest.approx(90_000)
    assert window.lower_point.y == pytest.approx(0)
    assert window.square_aoi.total_bounds.tolist() == pytest.approx(
        [65_000, -25_000, 115_000, 25_000]
    )
    assert window.analysis_aoi.total_bounds.tolist() == pytest.approx(
        [65_000, -1_000, 100_000, 1_000]
    )


def test_compare_prepared_extent_series_reports_monthly_difference_metrics(mod):
    dates = pd.date_range("2020-01-01", periods=3, freq="MS")
    native = pd.DataFrame(
        {"extent_pct": [0.0, 10.0, 20.0], "candidate_usable": [True, True, True]},
        index=dates,
    )
    coarse = pd.DataFrame(
        {"extent_pct": [1.0, 9.0, 18.0], "candidate_usable": [True, True, True]},
        index=dates,
    )

    comparison = mod.compare_prepared_extent_series(
        native, coarse, native_res_m=30.0, coarse_res_m=100.0
    )

    assert comparison["n_months_compared"] == 3
    assert comparison["correlation"] > 0.99
    assert comparison["max_abs_diff_extent_pct"] == pytest.approx(2.0)
    assert comparison["mean_abs_diff_extent_pct"] == pytest.approx(4 / 3)
    assert comparison["same_wet_month"] is True
    assert comparison["same_dry_month"] is True
    assert comparison["native_wet_month"] == "2020-03-01"
    assert comparison["coarse_dry_month"] == "2020-01-01"


def test_extent_pipeline_uses_resumable_annual_cache(mod, monkeypatch, tmp_path):
    dates = pd.date_range("2020-01-01", periods=2, freq="MS")
    extent = pd.DataFrame(
        {
            "n_water": [1, 2],
            "n_aoi": [10, 10],
            "n_valid": [10, 10],
            "n_invalid": [0, 0],
            "extent_pct": [10.0, 20.0],
            "invalid_pct": [0.0, 0.0],
        },
        index=dates,
    )
    calls = {}

    def fake_extent(*args, **kwargs):
        calls["extent"] = kwargs
        return extent

    monkeypatch.setattr(mod, "load_wofs_monthly_extent", fake_extent)
    monkeypatch.setattr(mod, "_robust_signal", lambda prepared: (10.0, 0.0))

    mod._run_extent_pipeline(
        object(), "2020-01-01", "2020-02-29", 30.0,
        time_block=12, cache_dir=tmp_path, force=False,
    )

    assert calls["extent"]["time_block"] == 12
    assert calls["extent"]["cache_dir"] == tmp_path
    assert calls["extent"]["force"] is False


def test_parallel_catchments_overlap_and_preserve_order(mod, monkeypatch):
    import threading

    lock = threading.Lock()
    two_active = threading.Event()
    active = 0
    peak = 0

    def fake_run(spec, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                two_active.set()
        assert two_active.wait(timeout=2)
        with lock:
            active -= 1
        return {"catchment_key": spec.key}

    monkeypatch.setattr(mod, "run_one_catchment", fake_run)
    specs = [mod.CatchmentSpec(key, key, key, key) for key in ("first", "second", "third")]

    results, failures = mod._run_catchments(specs, workers=2, run_kwargs={})

    assert peak == 2
    assert [result["catchment_key"] for result in results] == ["first", "second", "third"]
    assert failures == []


def test_parallel_catchments_collect_failure_and_continue(mod, monkeypatch):
    def fake_run(spec, **kwargs):
        if spec.key == "bad":
            raise RuntimeError("boom")
        return {"catchment_key": spec.key}

    monkeypatch.setattr(mod, "run_one_catchment", fake_run)
    specs = [mod.CatchmentSpec(key, key, key, key) for key in ("good", "bad")]

    results, failures = mod._run_catchments(specs, workers=2, run_kwargs={})

    assert [result["catchment_key"] for result in results] == ["good"]
    assert failures == [{"catchment_key": "bad", "error": "RuntimeError('boom')"}]


def test_html_report_renders_na_when_no_months_are_comparable(mod, tmp_path):
    comparison = {
        "native_res_m": 30.0,
        "coarse_res_m": 100.0,
        "n_months_compared": 0,
        "correlation": None,
        "mean_abs_diff_extent_pct": None,
        "max_abs_diff_extent_pct": None,
        "amplitude_delta_pp": None,
        "same_wet_month": False,
        "same_dry_month": False,
    }
    result = {
        "catchment_key": "empty",
        "display_name": "Empty",
        "lower_hydroid": 1,
        "side_km": 50.0,
        "analysis_bounds_wgs84": [1.0, 2.0, 3.0, 4.0],
        "date_range": ["2005-01-01", "2025-12-31"],
        "comparison": comparison,
        "series": [],
    }

    report = mod.build_html_report([result], tmp_path / "report.html")

    assert "N/A" in report.read_text(encoding="utf-8")
