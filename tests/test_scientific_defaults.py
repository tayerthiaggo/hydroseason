import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

from hydroseason import _scientific_defaults as defaults
from hydroseason._calibration import fingerprint, timing_identifiability_fingerprint

REPORT = Path("docs/calibration/2026-08-21-calibration-report.json")
TIMING_CALIBRATION_REPORT = Path("docs/calibration/2026-09-01-timing-identifiability-calibration.json")
TIMING_VALIDATION_REPORT = Path("docs/calibration/2026-09-01-timing-identifiability-validation.json")


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


def test_generated_timing_identifiability_defaults_are_a_candidate():
    assert defaults.TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE == "candidate_for_established_0_2_0"
    assert defaults.TIMING_IDENTIFIABILITY_DEFAULTS.min_informative_years in {5, 7, 10}


def test_timing_calibration_and_untouched_validation_artifacts_are_fresh():
    calibration = json.loads(TIMING_CALIBRATION_REPORT.read_text(encoding="utf-8"))
    validation = json.loads(TIMING_VALIDATION_REPORT.read_text(encoding="utf-8"))

    assert calibration["thresholds"] == asdict(defaults.TIMING_IDENTIFIABILITY_DEFAULTS)
    assert calibration["threshold_fingerprint"] == defaults.TIMING_IDENTIFIABILITY_FINGERPRINT
    assert timing_identifiability_fingerprint() == defaults.TIMING_IDENTIFIABILITY_FINGERPRINT
    assert validation["threshold_fingerprint"] == defaults.TIMING_IDENTIFIABILITY_FINGERPRINT
    assert validation["partition"] == "validation"
    assert validation["selection_survivors"] == {"reselection": 0}
    assert validation["scoring"] == {"evaluated_candidates": 1}
    for payload in (calibration, validation):
        assert tuple(map(int, payload["environment"]["python"].split(".")[:2])) < (3, 14)


RECURRENCE_CALIBRATION_REPORT = Path(
    "docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"
)

RECURRENCE_PROMOTION_REPORT = Path(
    "docs/calibration/2026-09-03-recurrence-identifiability-promotion.json"
)


def test_recurrence_calibration_artifact_matches_generated_defaults():
    from hydroseason._recurrence_calibration import recurrence_fingerprint

    payload = json.loads(RECURRENCE_CALIBRATION_REPORT.read_text(encoding="utf-8"))
    promotion = json.loads(RECURRENCE_PROMOTION_REPORT.read_text(encoding="utf-8"))
    assert payload["selected_policy"] == defaults.RECURRENCE_POLICY
    assert payload["authority_scope"] == "candidate_for_established_0_2_0"
    assert payload["seeds"] == list(range(50000, 50960))
    assert promotion["candidate_fingerprint"] == payload["fingerprint"]
    # The blinded real-cohort gate was never evaluated, so the shipped scope is
    # the candidate one and the promotion record says promotion was withheld.
    assert promotion["promotion_status"] == "withheld"
    assert promotion["authority_scope"] == defaults.RECURRENCE_AUTHORITY_SCOPE
    assert defaults.RECURRENCE_AUTHORITY_SCOPE == "candidate_for_established_0_2_0"
    assert defaults.RECURRENCE_FINGERPRINT == payload["fingerprint"]
    assert recurrence_fingerprint(
        defaults.RECURRENCE_POLICY,
        seeds=payload["seeds"],
        metrics=payload["metrics"],
        authority_scope=defaults.RECURRENCE_AUTHORITY_SCOPE,
    ) == defaults.RECURRENCE_FINGERPRINT


RECURRENCE_VALIDATION_REPORT = Path(
    "docs/calibration/2026-09-03-recurrence-identifiability-validation.json"
)


def test_recurrence_untouched_validation_uses_frozen_policy_once():
    calibration = json.loads(RECURRENCE_CALIBRATION_REPORT.read_text(encoding="utf-8"))
    validation = json.loads(RECURRENCE_VALIDATION_REPORT.read_text(encoding="utf-8"))
    assert validation["partition"] == "validation"
    assert validation["selected_policy"] == calibration["selected_policy"]
    assert validation["fingerprint"] == calibration["fingerprint"]
    assert validation["seeds"] == list(range(60000, 60960))
    assert validation["selection_counts"] == {"reselection": 0}
    assert set(validation["candidate_metrics"]) == {calibration["selected_policy"]}
    assert validation["metrics"]["false_point_wilson"][1] <= 0.05
    assert validation["metrics"]["false_resolution_wilson"][1] <= 0.05


def test_generated_defaults_module_keeps_its_imports_in_the_header(tmp_path):
    """Block writers must not leave a module-level import after assignments.

    A block-local ``RecurrencePolicy`` import lands mid-module and the generated
    file then fails ``ruff`` E402, so the writers hoist it into the header and
    must stay idempotent when a block is rewritten or carried forward.
    """
    from scripts.run_calibration import _write_recurrence_defaults

    header = Path("hydroseason/_scientific_defaults.py").read_text(encoding="utf-8")
    assert "\nfrom hydroseason._recurrence_identifiability import RecurrencePolicy\n" in header.split(
        "# BEGIN RECURRENCE IDENTIFIABILITY DEFAULTS"
    )[0]

    out_mod = tmp_path / "_scientific_defaults.py"
    out_mod.write_text(header, encoding="utf-8")
    for _ in range(2):
        _write_recurrence_defaults(
            out_mod,
            policy="annual_shape_match",
            recurrence_fingerprint_value="0" * 64,
            authority_scope="candidate_for_established_0_2_0",
        )
    written = out_mod.read_text(encoding="utf-8")
    assert written.count("from hydroseason._recurrence_identifiability import RecurrencePolicy") == 1

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "E402,F401,F821,I001", str(out_mod)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def _promotion_module_copy(tmp_path):
    out_mod = tmp_path / "_scientific_defaults.py"
    out_mod.write_text(Path("hydroseason/_scientific_defaults.py").read_text(encoding="utf-8"), encoding="utf-8")
    return out_mod


def test_promote_recurrence_defaults_withholds_promotion_without_a_blinded_cohort(tmp_path):
    """A narrowing policy may not reach established scope on an unevaluated gate.

    ``annual_shape_match`` is not ``no_narrowing``, so the blinded real-cohort
    gate applies. With no cohort report there is nothing to evaluate, and an
    unevaluated gate must stop promotion at candidate scope rather than pass.
    """
    from scripts.run_calibration import promote_recurrence_defaults

    cal_bytes = RECURRENCE_CALIBRATION_REPORT.read_bytes()
    val_bytes = RECURRENCE_VALIDATION_REPORT.read_bytes()
    out_mod = _promotion_module_copy(tmp_path)

    promotion = promote_recurrence_defaults(
        calibration_report=RECURRENCE_CALIBRATION_REPORT,
        validation_report=RECURRENCE_VALIDATION_REPORT,
        out_report=tmp_path / "promotion.json",
        out_module=out_mod,
    )

    assert RECURRENCE_CALIBRATION_REPORT.read_bytes() == cal_bytes
    assert RECURRENCE_VALIDATION_REPORT.read_bytes() == val_bytes

    assert promotion["promotion_status"] == "withheld"
    assert promotion["authority_scope"] == "candidate_for_established_0_2_0"
    assert promotion["blinded_cohort_gate"]["satisfied"] is False
    assert "established_fingerprint" not in promotion

    written = out_mod.read_text(encoding="utf-8")
    assert "RECURRENCE_AUTHORITY_SCOPE = 'candidate_for_established_0_2_0'" in written
    cal_payload = json.loads(cal_bytes.decode("utf-8"))
    assert f"RECURRENCE_FINGERPRINT = {cal_payload['fingerprint']!r}" in written


def test_promote_recurrence_defaults_preserves_source_reports_and_computes_fingerprint(tmp_path):
    from hydroseason._recurrence_calibration import recurrence_fingerprint
    from scripts.run_calibration import promote_recurrence_defaults

    cal_bytes = RECURRENCE_CALIBRATION_REPORT.read_bytes()
    val_bytes = RECURRENCE_VALIDATION_REPORT.read_bytes()

    cohort_report = tmp_path / "cohort.json"
    cohort_report.write_text(json.dumps({"metrics": {"direct_contradictions_k": 0}}), encoding="utf-8")

    out_rep = tmp_path / "promotion.json"
    out_mod = _promotion_module_copy(tmp_path)

    promotion = promote_recurrence_defaults(
        calibration_report=RECURRENCE_CALIBRATION_REPORT,
        validation_report=RECURRENCE_VALIDATION_REPORT,
        out_report=out_rep,
        out_module=out_mod,
        cohort_report=cohort_report,
    )

    assert RECURRENCE_CALIBRATION_REPORT.read_bytes() == cal_bytes
    assert RECURRENCE_VALIDATION_REPORT.read_bytes() == val_bytes

    cal_payload = json.loads(cal_bytes.decode("utf-8"))
    expected_fp = recurrence_fingerprint(
        cal_payload["selected_policy"],
        seeds=cal_payload["seeds"],
        metrics=cal_payload["metrics"],
        authority_scope="established_0_2_0",
    )
    assert promotion["promotion_status"] == "promoted"
    assert promotion["established_fingerprint"] == expected_fp


def test_promote_recurrence_defaults_withholds_on_a_contradicting_cohort(tmp_path):
    from scripts.run_calibration import promote_recurrence_defaults

    cohort_report = tmp_path / "cohort.json"
    cohort_report.write_text(json.dumps({"metrics": {"direct_contradictions_k": 1}}), encoding="utf-8")

    promotion = promote_recurrence_defaults(
        calibration_report=RECURRENCE_CALIBRATION_REPORT,
        validation_report=RECURRENCE_VALIDATION_REPORT,
        out_report=tmp_path / "promotion.json",
        out_module=_promotion_module_copy(tmp_path),
        cohort_report=cohort_report,
    )

    assert promotion["promotion_status"] == "withheld"
    assert promotion["blinded_cohort_gate"]["direct_contradictions_k"] == 1
