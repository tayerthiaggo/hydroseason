from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.prepare_case_study_data import (
    CASE_DATA_DIR,
    CATCHMENTS,
    RESOLUTIONS,
    normalize_extent_csv,
)


@pytest.fixture
def raw_extent_csv(tmp_path: Path) -> Path:
    dates = pd.date_range("2004-01-01", "2026-06-01", freq="MS")
    df = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "extent_pct": [0.123456 + i * 0.001 for i in range(len(dates))],
            "invalid_pct": [5.0 for _ in range(len(dates))],
            "n_water": [100 + i for i in range(len(dates))],
            "n_valid": [1000 for _ in range(len(dates))],
            "n_aoi": [1050 for _ in range(len(dates))],
            "extra_col": ["ignore" for _ in range(len(dates))],
        }
    )
    src = tmp_path / "raw_extent.csv"
    df.to_csv(src, index=False)
    return src


def test_normalizer_writes_stable_columns_dates_and_hash(
    tmp_path: Path, raw_extent_csv: Path
):
    dst = tmp_path / "normalized.csv"
    entry = normalize_extent_csv(
        raw_extent_csv,
        dst,
        start="2005-01-01",
        end="2025-12-01",
        catchment="fitzroy_river_wa",
        resolution=30,
    )

    out = pd.read_csv(dst)
    assert out.columns.tolist() == [
        "date",
        "extent_pct",
        "invalid_pct",
        "n_water",
        "n_valid",
        "n_aoi",
    ]
    assert len(out) == 252  # 21 years * 12 months
    assert out["date"].iloc[0] == "2005-01-01"
    assert out["date"].iloc[-1] == "2025-12-01"
    assert entry["sha256"] == hashlib.sha256(dst.read_bytes()).hexdigest()
    assert entry["rows"] == 252
    assert entry["start"] == "2005-01-01"
    assert entry["end"] == "2025-12-01"
    assert entry["resolution_m"] == 30
    assert entry["catchment"] == "fitzroy_river_wa"


def test_normalizer_rejects_missing_months(tmp_path: Path):
    dates = pd.date_range("2005-01-01", "2025-12-01", freq="MS").drop(
        pd.Timestamp("2010-05-01")
    )
    df = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "extent_pct": 1.0,
            "invalid_pct": 0.0,
            "n_water": 10,
            "n_valid": 100,
            "n_aoi": 100,
        }
    )
    src = tmp_path / "incomplete.csv"
    df.to_csv(src, index=False)
    dst = tmp_path / "out.csv"

    with pytest.raises(ValueError, match="Missing 1 expected month"):
        normalize_extent_csv(
            src,
            dst,
            start="2005-01-01",
            end="2025-12-01",
            catchment="test",
            resolution=30,
        )


def test_normalizer_rejects_duplicate_months(tmp_path: Path):
    dates = list(pd.date_range("2005-01-01", "2025-12-01", freq="MS"))
    dates.append(pd.Timestamp("2010-05-01"))
    df = pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "extent_pct": 1.0,
            "invalid_pct": 0.0,
            "n_water": 10,
            "n_valid": 100,
            "n_aoi": 100,
        }
    )
    src = tmp_path / "dup.csv"
    df.to_csv(src, index=False)
    dst = tmp_path / "out.csv"

    with pytest.raises(ValueError, match="Duplicate month"):
        normalize_extent_csv(
            src,
            dst,
            start="2005-01-01",
            end="2025-12-01",
            catchment="test",
            resolution=30,
        )


def test_committed_case_study_data_matrix_is_complete():
    manifest_path = CASE_DATA_DIR / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_product"] == "ga_ls_wo_3"
    assert manifest["analysis_start"] == "2005-01-01"
    assert manifest["analysis_end"] == "2025-12-01"
    assert manifest["output_crs"] == "EPSG:3577"

    inputs = manifest["inputs"]
    assert len(inputs) == 20
    for catchment in CATCHMENTS:
        for res in RESOLUTIONS:
            key = f"{catchment}_{res}m"
            assert key in inputs
            entry = inputs[key]
            file_path = CASE_DATA_DIR / "extent" / f"{key}.csv"
            assert file_path.exists()
            content = file_path.read_bytes()
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]
            assert entry["rows"] == 252
