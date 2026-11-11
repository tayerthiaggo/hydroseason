"""Guards for the G2 known-truth gate test record."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-02-g2-known-truth-gates-plan.md"
RECEIPT = HANDOFF / "2026-11-02-g2-known-truth-gates-receipt.json"
RESULTS = HANDOFF / "2026-11-02-g2-known-truth-gates-results.json"
RESULTS_DOC = HANDOFF / "2026-11-02-g2-known-truth-gates-results.md"
SCRIPT = Path("scripts/known_truth_gates.py")
G1_SCRIPT = Path("scripts/gate_calibration.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_receipt_froze_the_plan_and_the_scripts():
    receipt = _load(RECEIPT)
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert receipt["g1_script_sha256_lf"] == _lf_sha256(G1_SCRIPT)


def test_receipt_records_the_checks_made_before_the_freeze():
    receipt = _load(RECEIPT)
    for shape in ("sine", "pulse"):
        rows = [v for v in receipt["check"].values() if v["shape"] == shape]
        assert sum(v["at_truth"] for v in rows) == sum(v["cycles"] for v in rows) > 0
    assert receipt["corpus_records"] == 1000 + 400 + 287 * 4
    plan = " ".join(PLAN.read_text(encoding="utf-8").split())
    assert "**Construction check outcome (recorded before the freeze).**" in plan
    assert "**Pilot outcome (recorded before the freeze).**" in plan


def test_results_cite_the_receipt_and_record_the_failure():
    results = _load(RESULTS)
    assert results["receipt_sha256_lf"] == _lf_sha256(RECEIPT)
    assert results["errors"] == 0
    assert results["gates_read_back"] == [[1.5, 2, 0], [3.0, 5, 0]]
    assert results["checks"] == {
        "1_precise_safe_S": False,
        "2_band_vs_margin_S": False,
        "1_precise_safe_I": False,
        "2_band_vs_margin_I": True,
        "3_null_records": True,
    }
    assert results["passes"] is False


def test_results_doc_matches_the_scorer():
    results = _load(RESULTS)
    doc = " ".join(RESULTS_DOC.read_text(encoding="utf-8").split())
    assert results["receipt_sha256_lf"] in doc
    assert "**G2 does not pass. The current gates (ratio 3.0, 5 peak water pixels) stay.**" in doc
    for arm in ("S", "I"):
        rule_1 = results["arms"][arm]["rule_1"]
        margin = results["arms"][arm]["rule_1_current_margin"]
        assert f"{rule_1['not_correct']} of {rule_1['point_in_band']}" in doc
        assert f"{margin['not_correct']:,} of {margin['point_in_margin']:,}" in doc
        diff = results["arms"][arm]["rule_2"]["difference"]
        assert f"{'+' if diff > 0 else '−'}{abs(diff):.3f}" in doc


def test_library_gates_unchanged_after_g2():
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as gates

    assert (gates.min_amplitude_to_floor_ratio, gates.min_peak_water_pixels) == (3.0, 5)
