import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


def test_benchmark_exactness_uses_pickled_dataframe(tmp_path):
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_wofs_cache.py"
    spec = importlib.util.spec_from_file_location("benchmark_wofs_cache_under_test", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    try:
        left_csv = tmp_path / "left.csv"
        right_csv = tmp_path / "right.csv"
        left_pickle = left_csv.with_suffix(".pkl")
        right_pickle = right_csv.with_suffix(".pkl")
        pd.DataFrame({"n_water": pd.Series([1], dtype="int64")}).to_pickle(left_pickle)
        pd.DataFrame({"n_water": pd.Series([1.0], dtype="float64")}).to_pickle(right_pickle)
        digest = "same-serialized-projection"
        assert mod._assert_exact(
            {"output_digest": digest, "frame_path": str(left_csv)},
            {"output_digest": digest, "frame_path": str(right_csv)},
        ) is False
    finally:
        sys.modules.pop(spec.name, None)


def test_benchmark_source_count_gate_rejects_extra_cold_queries():
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_wofs_cache.py"
    spec = importlib.util.spec_from_file_location("benchmark_wofs_cache_under_test_counts", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    try:
        result = {
            "gilbert": {
                "legacy_stac_calls": 6,
                "cold_stac_calls": 4,
                "cold_graph_builds": 3,
                "cached_stac_calls": 0,
                "cached_graph_builds": 0,
            },
            "fitzroy": {
                "legacy_stac_calls": 6,
                "cold_stac_calls": 3,
                "cold_graph_builds": 3,
            },
        }
        assert mod._source_counts_ok(result, runs=3) is False
        result["gilbert"]["cold_stac_calls"] = 3
        assert mod._source_counts_ok(result, runs=3) is True
    finally:
        sys.modules.pop(spec.name, None)


def test_benchmark_parser_accepts_selected_cases():
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_wofs_cache.py"
    spec = importlib.util.spec_from_file_location("benchmark_wofs_cache_parser", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    try:
        args = mod._parser().parse_args(["--cases", "gilbert,fitzroy,moonie"])
        assert args.cases == ["gilbert", "fitzroy", "moonie"]
    finally:
        sys.modules.pop(spec.name, None)


@pytest.mark.network
@pytest.mark.performance
def test_real_wofs_cache_performance_gates(tmp_path):
    if os.environ.get("HYDROSEASON_RUN_WOFS_PERF") != "1":
        pytest.skip("set HYDROSEASON_RUN_WOFS_PERF=1")
    output = tmp_path / "benchmark.json"
    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_wofs_cache.py", "--output", str(output), "--runs", "3"],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["gilbert"]["cold_median_improvement"] >= 0.20
    assert result["fitzroy"]["cold_median_regression"] <= 0.10
    assert result["gilbert"]["cached_median_improvement"] >= 0.80
    assert result["gilbert"]["cached_stac_calls"] == 0
    assert result["exact_output_equality"] is True
