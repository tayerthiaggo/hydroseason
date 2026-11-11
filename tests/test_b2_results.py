"""Guards for the B2 known-truth test of refuge condition labels."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-04-b2-refuge-labels-plan.md"
RECEIPT = HANDOFF / "2026-11-04-b2-refuge-labels-receipt.json"
RESULTS = HANDOFF / "2026-11-04-b2-refuge-labels-results.json"
RESULTS_DOC = HANDOFF / "2026-11-04-b2-refuge-labels-results.md"
SCRIPT = Path("scripts/known_truth_b2.py")
B1_SCRIPT = Path("scripts/l1_followups.py")
G2_SCRIPT = Path("scripts/known_truth_gates.py")
G1_SCRIPT = Path("scripts/gate_calibration.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_receipt_froze_the_plan_and_the_scripts():
    receipt = _load(RECEIPT)
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert receipt["b1_script_sha256_lf"] == _lf_sha256(B1_SCRIPT)
    assert receipt["g2_script_sha256_lf"] == _lf_sha256(G2_SCRIPT)
    assert receipt["g1_script_sha256_lf"] == _lf_sha256(G1_SCRIPT)
    assert receipt["corpus_records"] == 2000 + 1148
    assert receipt["identity"] == {"pairs": 64, "identical": 64, "failures": []}
    assert receipt["library_gates"] == {"ratio": 3.0, "peak_pixels": 5}


def test_seeds_are_fresh():
    sys.path.insert(0, str(Path("scripts").resolve()))
    import known_truth_b2 as b2
    import known_truth_gates as g2
    import known_truth_l2_r1 as l2r1
    import known_truth_labels as l1

    new = {*b2.S_SEEDS, *b2.I_SEEDS, *b2.PILOT_S_SEEDS, *b2.PILOT_I_SEEDS}
    old = {*g2.SEASONAL_SEEDS, *g2.NULL_SEEDS, *g2.INJECTION_SEEDS, *g2.PILOT_SEEDS, *g2.PILOT_I_SEEDS,
           *l1.SEASONAL_SEEDS, *l1.NULL_SEEDS, *l1.INJECTION_SEEDS, *l1.PILOT_S_SEEDS, *l1.PILOT_I_SEEDS,
           *l2r1.SEASONAL_SEEDS, *l2r1.NULL_SEEDS, *l2r1.INJECTION_SEEDS, *l2r1.PILOT_S_SEEDS,
           *l2r1.PILOT_I_SEEDS}
    assert not new & old
    assert (len(b2.S_SEEDS), len(b2.I_SEEDS)) == (2000, 1148)


def test_results_cite_the_receipt_and_record_the_pass():
    results = _load(RESULTS)
    assert results["receipt_sha256_lf"] == _lf_sha256(RECEIPT)
    assert results["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert results["records"] == 3148 and results["errors"] == 0
    assert results["fingerprints"] == ["4bcfed63ed5f04f82417e0164d531595b349d1d8ea0dc2481ce6dc79d72a64de"]
    assert results["e0_reproduces_library_labels"] is True and results["e0_mismatched_cycles"] == 0
    assert results["decision"] == {"refuge": "pass", "recharge_reported": "pass"}
    for label in ("refuge", "recharge"):
        for arm in ("S", "I"):
            rules = results["labels"][label][arm]
            assert rules["rule_1"]["evaluable"] and rules["rule_1"]["outcome"] == "holds"
            assert rules["rule_2"]["evaluable"] and rules["rule_2"]["outcome"] == "holds"


def test_results_doc_matches_the_scorer():
    results = _load(RESULTS)
    refuge = results["labels"]["refuge"]
    assert (refuge["S"]["rule_1"]["cycles"], refuge["S"]["rule_1"]["records"]) == (940, 47)
    assert (refuge["I"]["rule_1"]["cycles"], refuge["I"]["rule_1"]["records"]) == (4023, 106)
    assert (refuge["S"]["rule_2"]["cycles"], refuge["I"]["rule_2"]["cycles"]) == (7895, 10176)
    assert refuge["S"]["coverage"]["E1"]["records_with_labels"] == 443
    assert refuge["I"]["coverage"]["E1"]["records_with_labels"] == 375
    doc = " ".join(RESULTS_DOC.read_text(encoding="utf-8").split())
    assert _lf_sha256(RECEIPT) in doc
    for arm, text in (("S", "+0.029 [+0.008, +0.050]"), ("I", "+0.067 [+0.046, +0.088]")):
        rule = refuge[arm]["rule_1"]
        assert text == f"{rule['difference']:+.3f} [{rule['ci95'][0]:+.3f}, {rule['ci95'][1]:+.3f}]"
        assert text in doc, text
    for arm, text in (("S", "0.347 [0.326, 0.368]"), ("I", "0.382 [0.353, 0.413]")):
        rule = refuge[arm]["rule_2"]
        assert text == f"{rule['kappa']:.3f} [{rule['ci95'][0]:.3f}, {rule['ci95'][1]:.3f}]"
        assert text in doc, text
    for text in ("47 → 443 of 1,254", "106 → 375 of 569", "0.690 → 0.719", "0.630 → 0.696",
                 "−0.097 [−0.141, −0.051]", "−0.014 [−0.055, +0.026]",
                 "+0.026 [−0.005, +0.058]", "+0.040 [+0.024, +0.057]",
                 "0.275 [0.254, 0.296]", "0.158 [0.134, 0.182]",
                 "97 of 940 (10.3%)", "604 of 4,023 (15.0%)", "3 h 6 min (11,151 s)"):
        assert text in doc, text
