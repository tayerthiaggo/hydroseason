import json
from dataclasses import asdict, replace
from pathlib import Path

from hydroseason import _scientific_defaults as defaults
from hydroseason._calibration import fingerprint

REPORT = Path("docs/calibration/2026-08-21-calibration-report.json")


def test_constants_exist_and_are_typed():
    assert isinstance(defaults.CALIBRATION_VERSION, str)
    assert defaults.EVIDENCE_DEFAULTS.weak_timing_concentration < defaults.EVIDENCE_DEFAULTS.strong_timing_concentration
    assert 0.0 <= defaults.PHASE_DEFAULTS.phase_low_fraction < defaults.PHASE_DEFAULTS.phase_high_fraction <= 1.0


def test_report_exists_and_parses():
    assert REPORT.exists(), "calibration report must be committed"
    json.loads(REPORT.read_text())


def test_report_matches_the_generated_constants():
    payload = json.loads(REPORT.read_text())

    assert payload["calibration_version"] == defaults.CALIBRATION_VERSION
    assert payload["evidence"] == asdict(defaults.EVIDENCE_DEFAULTS)
    assert payload["recoverability"] == asdict(defaults.RECOVERABILITY_DEFAULTS)
    assert payload["phase"] == asdict(defaults.PHASE_DEFAULTS)


def test_fingerprint_is_current():
    """A changed generator, grid or objective invalidates the constants."""
    payload = json.loads(REPORT.read_text())

    assert payload["fingerprint"] == fingerprint() == defaults.CALIBRATION_FINGERPRINT


def test_fingerprint_changes_when_selected_constants_change(monkeypatch):
    current = fingerprint()
    monkeypatch.setattr(
        defaults,
        "EVIDENCE_DEFAULTS",
        replace(
            defaults.EVIDENCE_DEFAULTS,
            seasonal_cv_skill=defaults.EVIDENCE_DEFAULTS.seasonal_cv_skill - 0.1,
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
