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


def test_html_report_renders_na_when_resolution_missing(mod, tmp_path):
    result1 = {
        "catchment_key": "first",
        "display_name": "First",
        "lower_hydroid": 1,
        "side_km": 50.0,
        "analysis_bounds_wgs84": [1.0, 2.0, 3.0, 4.0],
        "date_range": ["2005-01-01", "2025-12-31"],
        "matrix": {
            "60.0": {"fidelity": 0.9},
            "90.0": {"fidelity": 0.8},
        },
    }
    result2 = {
        "catchment_key": "empty",
        "display_name": "Empty",
        "lower_hydroid": 2,
        "side_km": 50.0,
        "analysis_bounds_wgs84": [1.0, 2.0, 3.0, 4.0],
        "date_range": ["2005-01-01", "2025-12-31"],
        "matrix": {
            "60.0": {"fidelity": 0.9},
            # Missing 90.0
        },
    }

    report = mod.build_html_report([result1, result2], tmp_path / "report.html")

    assert "N/A" in report.read_text(encoding="utf-8")
