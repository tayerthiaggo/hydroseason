from __future__ import annotations

import importlib.metadata
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import hydroseason
from hydroseason import analyze_catchment, generate_catchment_report
from hydroseason._method_policy import method_policy_fingerprint
from hydroseason._run_manifest import REQUIRED_SECTIONS, build_run_manifest, sha256_file


@pytest.fixture
def seasonal_extent():
    dates = pd.date_range("2010-01-01", "2015-12-01", freq="MS")
    values = [
        max(0.0, min(100.0, 40.0 + 30.0 * np.sin(2 * np.pi * (date.month - 1) / 12)))
        for date in dates
    ]
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)


@pytest.fixture
def long_seasonal_extent():
    dates = pd.date_range("2000-01-01", "2015-12-01", freq="MS")
    values = [
        max(0.0, min(100.0, 40.0 + 30.0 * np.sin(2 * np.pi * (date.month - 1) / 12)))
        for date in dates
    ]
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)


def test_report_bundle_contains_complete_manifest(tmp_path, seasonal_extent):
    analysis = analyze_catchment(
        seasonal_extent,
        random_state=17,
    )
    paths = generate_catchment_report(seasonal_extent, tmp_path, analysis=analysis)
    manifest = json.loads(paths.manifest_json.read_text(encoding="utf-8"))
    assert manifest["schema"] == "hydroseason-run-manifest-v1"
    assert manifest["method"]["policy_id"] == "hydroseason-v0.2.0"
    assert manifest["method"]["fingerprint"] == method_policy_fingerprint()
    assert manifest["input"]["extent_sha256"] == analysis.input_fingerprint
    assert manifest["analysis"]["route"] == analysis.route
    assert manifest["analysis"]["reason"] == analysis.route_reason
    assert manifest["random_state"] == 17


def test_manifest_has_all_required_sections_and_metadata(tmp_path, seasonal_extent):
    paths = generate_catchment_report(seasonal_extent, tmp_path)
    manifest = json.loads(paths.manifest_json.read_text(encoding="utf-8"))

    for section in REQUIRED_SECTIONS:
        assert section in manifest, f"Missing required section: {section}"

    assert manifest["schema"] == "hydroseason-run-manifest-v1"
    assert manifest["hydroseason_version"] == hydroseason.__version__
    assert manifest["python"] == platform.python_version()
    assert "numpy" in manifest["dependencies"]
    assert "pandas" in manifest["dependencies"]
    assert manifest["dependencies"]["numpy"] == importlib.metadata.version("numpy")
    assert manifest["dependencies"]["pandas"] == importlib.metadata.version("pandas")

    assert manifest["input"]["n_rows"] == len(seasonal_extent)
    assert manifest["input"]["date_min"] == "2010-01-01"
    assert manifest["input"]["date_max"] == "2015-12-01"

    # Default run_context when none is supplied
    assert manifest["acquisition"] == {"source_kind": "supplied_in_memory"}
    assert manifest["preflight"] == {}


def test_manifest_outputs_integrity_and_no_self_hash(tmp_path, seasonal_extent):
    paths = generate_catchment_report(seasonal_extent, tmp_path)
    manifest = json.loads(paths.manifest_json.read_text(encoding="utf-8"))

    outputs = manifest["outputs"]
    assert "html" in outputs
    assert "monthly_csv" in outputs
    assert "hydro_years_csv" in outputs
    assert "wet_event_csv" in outputs
    assert "low_spells_csv" in outputs
    assert "manifest_json" not in outputs
    assert "manifest" not in outputs

    for key, item in outputs.items():
        assert item["path"] == Path(item["path"]).name, "output paths are manifest-relative"
        p = paths.manifest_json.parent / item["path"]
        assert p.exists(), f"Output file for {key} does not exist: {p}"
        assert item["size_bytes"] == p.stat().st_size
        assert item["sha256"] == sha256_file(p)


def test_manifest_deterministic_formatting(tmp_path, seasonal_extent):
    paths = generate_catchment_report(seasonal_extent, tmp_path)
    raw_text = paths.manifest_json.read_text(encoding="utf-8")
    parsed = json.loads(raw_text)

    # Must be valid json formatted with 2 spaces and sorted keys
    expected_text = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
    assert raw_text == expected_text


def test_manifest_records_run_context_acquisition_and_preflight(tmp_path, seasonal_extent):
    run_context = {
        "acquisition": {
            "source_kind": "dea_wofs",
            "stac_url": "https://explorer.dea.ga.gov.au/stac",
            "stac_collection": "ga_ls_wo_3",
            "cache_dir": str(tmp_path / "cache"),
        },
        "preflight": {
            "feasible": True,
            "core_pixel_count": 128,
            "largest_cluster_pixels": 45,
            "minimum_cluster_pixels": 4,
            "resolution": 30.0,
            "reason": "contiguous recurrent water meets minimum threshold",
        },
    }

    paths = generate_catchment_report(
        seasonal_extent,
        tmp_path,
        run_context=run_context,
    )
    manifest = json.loads(paths.manifest_json.read_text(encoding="utf-8"))

    assert manifest["acquisition"]["source_kind"] == "dea_wofs"
    assert manifest["acquisition"]["stac_url"] == "https://explorer.dea.ga.gov.au/stac"
    assert manifest["acquisition"]["cache_dir"] == str(tmp_path / "cache")
    assert manifest["preflight"]["feasible"] is True
    assert manifest["preflight"]["core_pixel_count"] == 128


def test_manifest_scrubs_sensitive_credentials(tmp_path, seasonal_extent):
    run_context = {
        "acquisition": {
            "source_kind": "extent_csv",
            "path": "/data/test.csv",
            "api_key": "secret_api_key_123",
            "auth_token": "token_xyz",
            "password": "super_secret_password",
            "stac_url": "https://user:password123@stac.example.com/api",
        }
    }

    analysis = analyze_catchment(seasonal_extent)
    manifest = build_run_manifest(
        extent=seasonal_extent,
        analysis=analysis,
        artifacts={},
        run_context=run_context,
    )

    acq = manifest["acquisition"]
    assert "api_key" not in acq
    assert "auth_token" not in acq
    assert "password" not in acq
    assert "password123" not in acq["stac_url"]
    assert "user:password123" not in acq["stac_url"]
    assert "<redacted>" in acq["stac_url"]
    assert acq["source_kind"] == "extent_csv"
    assert acq["path"] == "/data/test.csv"


def test_manifest_pass2_refinement_counts_and_reason_codes(tmp_path, long_seasonal_extent):
    analysis = analyze_catchment(long_seasonal_extent)
    paths = generate_catchment_report(long_seasonal_extent, tmp_path, analysis=analysis)
    manifest = json.loads(paths.manifest_json.read_text(encoding="utf-8"))

    analysis_sec = manifest["analysis"]
    assert analysis_sec["n_hydro_years"] > 0
    assert "pass2_applied_count" in analysis_sec
    assert "pass2_abstained_count" in analysis_sec
    assert "reason_codes" in analysis_sec
    assert isinstance(analysis_sec["pass2_applied_count"], int)
    assert isinstance(analysis_sec["pass2_abstained_count"], int)
    assert isinstance(analysis_sec["reason_codes"], dict)
