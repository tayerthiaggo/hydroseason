import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._method_policy import (
    CURRENT_METHOD_POLICY,
    canonical_method_policy_json,
    main,
    method_policy_fingerprint,
    method_policy_manifest,
)
from hydroseason._regime import assess_water_regime
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY


@pytest.fixture
def seasonal_extent():
    dates = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (dates.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)


def test_v020_has_one_non_selectable_method():
    analyze_parameters = inspect.signature(analyze_catchment).parameters
    regime_parameters = inspect.signature(assess_water_regime).parameters
    assert "method_policy" not in analyze_parameters
    assert "seasonality_policy" not in analyze_parameters
    assert "trough_refinement_policy" not in analyze_parameters
    assert "seasonality_policy" not in regime_parameters
    assert CURRENT_METHOD_POLICY.policy_id == "hydroseason-v0.2.0"


def test_v020_manifest_pins_every_scientific_constant():
    manifest = method_policy_manifest()
    assert manifest["policy_id"] == "hydroseason-v0.2.0"
    assert manifest["seasonality"] == {
        "method": "timing_recurrence",
        "alpha": 0.05,
        "min_detectable_years": 5,
    }
    assert manifest["trough_refinement"]["method"] == "direct_profile_combined"
    assert manifest["trough_refinement"]["huber_k"] == 1.345
    assert manifest["trough_refinement"]["profile_loss_cutoff"] == 0.05
    assert manifest["trough_refinement"]["delta_rel"] == 0.05
    assert manifest["event_thresholds"] == {
        "enter_sigma": 3.0,
        "exit_sigma": 1.0,
        "low_sigma": 1.0,
    }


@pytest.mark.parametrize(
    "removed",
    [
        {"seasonality_policy": "timing_recurrence"},
        {"trough_refinement_policy": TROUGH_REFINEMENT_POLICY},
        {"method_policy": "established-0.2.0"},
    ],
)
def test_removed_method_options_are_not_accepted(seasonal_extent, removed):
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        analyze_catchment(seasonal_extent, **removed)


def test_canonical_json_and_fingerprint():
    json_str = canonical_method_policy_json()
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["policy_id"] == "hydroseason-v0.2.0"
    fp = method_policy_fingerprint()
    assert isinstance(fp, str)
    assert len(fp) == 64


def test_catchment_analysis_records_provenance(seasonal_extent):
    analysis = analyze_catchment(seasonal_extent, n_bootstrap=40)
    assert analysis.method_policy_id == CURRENT_METHOD_POLICY.policy_id
    assert analysis.method_policy_fingerprint == method_policy_fingerprint()
    assert analysis.random_state == 0


def test_checked_in_method_policy_manifest_matches_runtime():
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "docs" / "method-policy-v0.2.0.json"
    sidecar_path = repo_root / "docs" / "method-policy-v0.2.0.sha256"

    assert manifest_path.is_file(), f"Missing manifest: {manifest_path}"
    assert sidecar_path.is_file(), f"Missing sidecar: {sidecar_path}"

    payload = manifest_path.read_bytes()
    sidecar_digest = sidecar_path.read_text(encoding="ascii").strip()

    manifest_digest = hashlib.sha256(payload).hexdigest()
    assert manifest_digest == sidecar_digest

    parsed = json.loads(payload.decode("utf-8"))
    assert parsed == method_policy_manifest()

    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == method_policy_fingerprint()


def test_method_policy_cli_generator(tmp_path):
    out_json = tmp_path / "custom-policy.json"
    ret = main(["--output", str(out_json)])
    assert ret == 0
    assert out_json.is_file()
    out_sha = tmp_path / "custom-policy.sha256"
    assert out_sha.is_file()
    digest = hashlib.sha256(out_json.read_bytes()).hexdigest()
    assert out_sha.read_text(encoding="ascii").strip() == digest


def test_validation_receipt_authorizes_the_frozen_method():
    receipt = json.loads(
        Path("docs/method-policy-v0.2.0-validation.json").read_text(encoding="utf-8")
    )
    assert receipt["release_decision"] == "pass"
    assert receipt["method_policy_id"] == "hydroseason-v0.2.0"
    assert receipt["method_fingerprint"] == method_policy_fingerprint()
    method_bytes = Path("docs/method-policy-v0.2.0.json").read_bytes()
    assert hashlib.sha256(method_bytes).hexdigest() == receipt["method_manifest_sha256"]


