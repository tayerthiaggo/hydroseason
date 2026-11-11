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


RESULTS = HANDOFF / "2026-11-05-de1-dry-run-end-results.json"
RESULTS_DOC = HANDOFF / "2026-11-05-de1-dry-run-end-results.md"
REAL = HANDOFF / "2026-11-05-de1-dry-run-end-real-records.json"
EXTRAS = HANDOFF / "2026-11-05-de1-dry-run-end-extras.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _diff(rule: dict) -> str:
    text = f"{rule['difference']:+.3f} [{rule['ci95'][0]:+.3f}, {rule['ci95'][1]:+.3f}]"
    return text.replace("-", "−")


@pytest.mark.skipif(not RESULTS.exists(), reason="DE1 not scored yet")
def test_results_cite_the_receipt_and_record_the_reading():
    results = _load(RESULTS)
    assert results["receipt_sha256_lf"] == _lf_sha256(RECEIPT)
    assert results["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert results["records"] == 3148 and results["errors"] == []
    assert results["fingerprints"] == [_load(RECEIPT)["library_fingerprint"]]
    assert results["decision"] == "A and B go to implementation"
    assert results["point_status_allowed"] is False
    for arm in ("S", "I"):
        rules = results["rules"][arm]
        assert rules["rule_1"]["outcome"] == "holds" and rules["rule_2"]["outcome"] == "holds"
        assert rules["rule_3"]["outcome"] == "fails"


@pytest.mark.skipif(not RESULTS.exists(), reason="DE1 not scored yet")
def test_results_doc_matches_the_scorer():
    results, real, extras = _load(RESULTS), _load(REAL), _load(EXTRAS)
    assert extras["results_sha256_lf"] == _lf_sha256(RESULTS)
    assert extras["frozen_script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert real["script_sha256_lf"] == _lf_sha256(SCRIPT)
    doc = " ".join(RESULTS_DOC.read_text(encoding="utf-8").split())
    assert results["receipt_sha256_lf"] in doc and results["script_sha256_lf"] in doc
    rules = results["rules"]
    for arm in ("S", "I"):
        for name in ("rule_1", "rule_2"):
            assert _diff(rules[arm][name]) in doc, (arm, name)
        assert _diff(results["reported"][arm]["pulse"]) in doc, arm
        r3 = rules[arm]["rule_3"]
        text = f"{r3['not_correct']:,} of {r3['point_ends']:,} ({r3['share']:.3f})"
        assert text in doc, text
        assert f"upper {r3['wilson_upper']:.3f}" in doc
    assert (rules["S"]["rule_1"]["pairs"], rules["S"]["rule_1"]["records"]) == (6953, 502)
    assert (rules["I"]["rule_1"]["pairs"], rules["I"]["rule_1"]["records"]) == (3617, 181)
    routing = extras["routing"]
    assert (routing["S|ephemeral|event_characterisation"], routing["I|ephemeral|event_characterisation"]) == (698, 393)
    early = extras["ephemeral_early_ends_by_rewet_month"]
    assert (early["S|dry_month_above_tolerance"], early["I|dry_month_above_tolerance"]) == (3632, 1300)
    assert sum(extras["overshoot_pairs"].values()) == 208
    assert real["g1_half_agreement_within_1"]["pairs"] == 33533
    for text in ("0.204 → 0.396", "0.255 → 0.516", "0.897 → 0.901", "0.895 → 0.892",
                 "698 of 1,200", "393 of 574", "3,632 (87.8%)", "1,300 (76.7%)",
                 "208 of 25,936", "0.732 today, 0.724", "1,251 → 2,364", "2 h 29 min (8,944 s)"):
        assert text in doc, text
