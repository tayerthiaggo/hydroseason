"""Guards for DE1, the known-truth test of where the dry season ends."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-05-de1-dry-run-end-plan.md"
RECEIPT = HANDOFF / "2026-11-05-de1-dry-run-end-receipt.json"
SCRIPT = Path("scripts/known_truth_de1.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _de1():
    sys.path.insert(0, str(Path("scripts").resolve()))
    import known_truth_de1

    return known_truth_de1


def test_seeds_are_fresh():
    de1 = _de1()
    import known_truth_b2 as b2
    import known_truth_gates as g2
    import known_truth_l2_r1 as l2r1
    import known_truth_labels as l1

    new = {*de1.S_EPHEMERAL, *de1.S_PULSE, *de1.S_SINE, *de1.I_SEEDS, *de1.PILOT_S, *de1.PILOT_I}
    old = {*g2.SEASONAL_SEEDS, *g2.NULL_SEEDS, *g2.INJECTION_SEEDS, *g2.PILOT_SEEDS, *g2.PILOT_I_SEEDS,
           *l1.SEASONAL_SEEDS, *l1.NULL_SEEDS, *l1.INJECTION_SEEDS, *l1.PILOT_S_SEEDS, *l1.PILOT_I_SEEDS,
           *l2r1.SEASONAL_SEEDS, *l2r1.NULL_SEEDS, *l2r1.INJECTION_SEEDS, *l2r1.PILOT_S_SEEDS, *l2r1.PILOT_I_SEEDS,
           *b2.S_SEEDS, *b2.I_SEEDS, *b2.PILOT_S_SEEDS, *b2.PILOT_I_SEEDS}
    assert not new & old
    assert (len(de1.S_EPHEMERAL), len(de1.S_PULSE), len(de1.S_SINE), len(de1.I_SEEDS)) == (1200, 400, 400, 1148)


def test_run_end_unit_cases():
    assert _de1()._unit_cases() == []


@pytest.mark.skipif(not RECEIPT.exists(), reason="DE1 not frozen yet")
def test_receipt_froze_the_plan_and_the_scripts():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert receipt["g2_script_sha256_lf"] == _lf_sha256(Path("scripts/known_truth_gates.py"))
    assert receipt["g1_script_sha256_lf"] == _lf_sha256(Path("scripts/gate_calibration.py"))
    assert receipt["corpus_records"] == 2000 + 1148
    assert receipt["identity"]["failures"] == []
    assert receipt["identity"]["arm_i_shapes"] == {"ephemeral": 574, "sine": 287, "pulse": 287}
    assert receipt["check"]["unit_case_failures"] == []
    assert receipt["check"]["candidate_mismatches_without_pulse"] == []
