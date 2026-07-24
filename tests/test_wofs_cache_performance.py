import json
import os
import subprocess
import sys

import pytest


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
