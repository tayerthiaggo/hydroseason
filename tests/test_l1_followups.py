"""Guards for the L1 follow-up measurements (B1 baseline impact, D1 boundary diagnostic)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
RESULTS = HANDOFF / "2026-11-03-l1-followups-results.json"
DOC = HANDOFF / "2026-11-03-l1-followups-results.md"
L1_RECEIPT = HANDOFF / "2026-11-03-l1-timing-labels-receipt.json"
SCRIPT = Path("scripts/l1_followups.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _results() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_results_come_from_this_script_on_the_l1_corpus():
    results = _results()
    assert results["l1_receipt_sha256_lf"] == _lf_sha256(L1_RECEIPT)
    assert results["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert results["records"] == 1174
    assert results["errors"] == 0
    assert results["e0_reproduces_library_labels"] is True


def test_doc_matches_the_results():
    results = _results()
    recharge = results["b1"]["recharge"]
    assert recharge["S|E0"]["labelled"]["k"] == 343
    assert recharge["S|E1"]["labelled"]["k"] == 2566
    assert recharge["I|E0"]["labelled"]["k"] == 2374
    assert recharge["I|E1"]["labelled"]["k"] == 7216
    assert recharge["S|E1"]["agree_on_cycles_labelled_under_e0_and_e1"]["k"] == 248
    assert recharge["I|E1"]["agree_on_cycles_labelled_under_e0_and_e1"]["k"] == 1194
    screen = results["d1_quality_screen"]
    assert (screen["S|quality_adjusted"]["selected_correct"], screen["S|quality_adjusted"]["raw_correct"]) == (398, 394)
    assert (screen["I|quality_adjusted"]["selected_correct"], screen["I|quality_adjusted"]["raw_correct"]) == (1393, 1245)
    doc = " ".join(DOC.read_text(encoding="utf-8").split())
    for text in ("0.723 against 0.682", "0.503 against 0.479", "18 of 369", "65 of 300",
                 "63.1% against 62.4%", "65.3% against 58.3%", "0.48 floors against 0.52 floors"):
        assert text in doc, text
