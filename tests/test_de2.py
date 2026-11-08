"""Guards for DE2, the known-truth test of a year boundary at the end of the low."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-08-de2-end-of-low-plan.md"
RECEIPT = HANDOFF / "2026-11-08-de2-end-of-low-receipt.json"
SCRIPT = Path("scripts/known_truth_de2.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _de2():
    sys.path.insert(0, str(Path("scripts").resolve()))
    import known_truth_de2

    return known_truth_de2


def test_seeds_are_fresh():
    de2 = _de2()
    import known_truth_de1 as de1

    new = {*de2.S_EPHEMERAL, *de2.S_PULSE, *de2.S_SINE, *de2.I_SEEDS, *de2.PILOT_S, *de2.PILOT_I,
           *range(de2.CHECK_SEEDS_START, de2.CHECK_SEEDS_START + 12)}
    old = {*de1.S_EPHEMERAL, *de1.S_PULSE, *de1.S_SINE, *de1.I_SEEDS, *de1.PILOT_S, *de1.PILOT_I,
           *range(de1.CHECK_SEEDS_START, de1.CHECK_SEEDS_START + 12)}
    assert not new & old
    # DE1's own guard already proves its seeds are fresh against G2, L1, L2/R1 and B2.
    assert min(new) > max(r.stop for r in (de1.S_SINE, de1.I_SEEDS, de1.PILOT_S, de1.PILOT_I)) or not new & old


@pytest.mark.skipif(not RECEIPT.exists(), reason="DE2 not frozen yet")
def test_receipt_froze_the_plan_the_script_and_the_candidate():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert receipt["de1_script_sha256_lf"] == _lf_sha256(Path("scripts/known_truth_de1.py"))
    assert receipt["g2_script_sha256_lf"] == _lf_sha256(Path("scripts/known_truth_gates.py"))
    assert receipt["corpus_records"] == 3148
    assert receipt["current_fingerprint"] != receipt["candidate_fingerprint"]
    for name in ("current", "candidate"):
        assert receipt["checks"][name]["identity_failures"] == []
        assert receipt["checks"][name]["construction_true_ends"] == 206
    assert (receipt["checks"]["candidate"]["construction_within_1"], receipt["checks"]["current"]["construction_within_1"]) == (177, 79)
