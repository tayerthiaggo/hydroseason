import json
from dataclasses import asdict, replace
from pathlib import Path

from hydroseason import _scientific_defaults as defaults
from hydroseason._calibration import fingerprint

REPORT = Path("docs/calibration/2026-08-21-calibration-report.json")


def test_constants_exist_and_are_typed():
    assert isinstance(defaults.CALIBRATION_VERSION, str)
    assert 0.0 <= defaults.EVIDENCE_DEFAULTS.seasonal_cv_skill <= 1.0
    assert 0.0 < defaults.EVIDENCE_DEFAULTS.periodicity_alpha < 1.0


def test_report_exists_and_parses():
    assert REPORT.exists(), "calibration report must be committed"
    json.loads(REPORT.read_text())


def test_report_matches_the_generated_constants():
    payload = json.loads(REPORT.read_text())

    assert payload["calibration_version"] == defaults.CALIBRATION_VERSION
    assert payload["evidence"] == asdict(defaults.EVIDENCE_DEFAULTS)
    assert payload["recoverability"] == asdict(defaults.RECOVERABILITY_DEFAULTS)


def test_fingerprint_is_current():
    """A changed generator, grid or objective invalidates the constants."""
    payload = json.loads(REPORT.read_text())

    assert payload["fingerprint"] == fingerprint() == defaults.CALIBRATION_FINGERPRINT


def test_fingerprint_ignores_the_interpreter_and_dependency_versions(monkeypatch):
    """The staleness check must hold across the whole supported CI matrix.

    Hashing sys.version/numpy/pandas made the fingerprint environment-specific,
    so equality could hold on at most one row of a matrix spanning Python
    3.10-3.13 plus a pinned minimum-dependency floor.
    """
    import numpy as np
    import pandas as pd

    from hydroseason import _calibration

    current = fingerprint()
    monkeypatch.setattr(_calibration.sys, "version", "3.10.0 (fake) [fake]")
    monkeypatch.setattr(np, "__version__", "1.24.4")
    monkeypatch.setattr(pd, "__version__", "2.0.3")

    assert fingerprint() == current


def test_generated_defaults_record_the_calibration_environment():
    """Version provenance is recorded rather than hashed."""
    assert set(defaults.CALIBRATION_ENVIRONMENT) == {"python", "numpy", "pandas"}
    payload = json.loads(REPORT.read_text())
    assert payload["environment"] == defaults.CALIBRATION_ENVIRONMENT
    # The report filename carries a fixed vintage label, so the run's real
    # instant has to be legible from the payload.
    assert payload["generated"].endswith("+00:00")


def test_fingerprint_changes_when_selected_constants_change(monkeypatch):
    current = fingerprint()
    monkeypatch.setattr(
        defaults,
        "EVIDENCE_DEFAULTS",
        replace(
            defaults.EVIDENCE_DEFAULTS,
            seasonal_cv_skill=defaults.EVIDENCE_DEFAULTS.seasonal_cv_skill + 0.05,
        ),
    )

    assert fingerprint() != current


def test_report_records_the_negative_control_rate_by_record_length():
    payload = json.loads(REPORT.read_text())

    by_length = payload["false_annualisation_by_length"]
    assert {"5", "7", "10", "20", "30"}.issubset(by_length)


def test_report_records_both_drift_axis_settings():
    payload = json.loads(REPORT.read_text())

    assert set(payload["drift_axis"]) == {"admit", "reject"}


def test_report_states_the_rotation_null_bias_direction():
    payload = json.loads(REPORT.read_text())

    note = payload["periodicity_null"]["bias_note"].lower()
    assert "anti-conservative" in note
    assert payload["periodicity_null"]["selected_alpha"] in (0.01, 0.025, 0.05, 0.10)


def test_defaults_module_is_generated_not_hand_edited():
    header = Path("hydroseason/_scientific_defaults.py").read_text()[:400]

    assert "generated" in header.lower()
    assert "do not edit" in header.lower()


def test_generated_default_module_declares_scientific_scope():
    """Nothing in the calibration claims authority over released behaviour.

    The four-phase labeller that PHASE_DEFAULTS governed was unreachable and
    has been removed, so `authoritative_for_four_phase_labels_only` no longer
    describes a product. Both remaining groups are challengers.
    """
    assert defaults.EVIDENCE_AUTHORITY_SCOPE == "experimental_challenger"
    assert defaults.RECOVERABILITY_AUTHORITY_SCOPE == "experimental_challenger"
    assert not hasattr(defaults, "PHASE_DEFAULTS")
    assert not hasattr(defaults, "PHASE_AUTHORITY_SCOPE")
