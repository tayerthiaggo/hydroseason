"""Guards for the L2 (two-sided trough label) and R1 (rise against trough) known-truth tests."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-03-l2-r1-plan.md"
RECEIPT = HANDOFF / "2026-11-03-l2-r1-receipt.json"
RESULTS = HANDOFF / "2026-11-03-l2-r1-results.json"
RESULTS_DOC = HANDOFF / "2026-11-03-l2-r1-results.md"
SCRIPT = Path("scripts/known_truth_l2_r1.py")
L1_SCRIPT = Path("scripts/known_truth_labels.py")
G2_SCRIPT = Path("scripts/known_truth_gates.py")
G1_SCRIPT = Path("scripts/gate_calibration.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _scripts():
    sys.path.insert(0, str(Path("scripts").resolve()))
    import known_truth_gates as g2
    import known_truth_l2_r1 as l2r1
    import known_truth_labels as l1

    return g2, l1, l2r1


def test_receipt_froze_the_plan_and_the_scripts():
    receipt = _load(RECEIPT)
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert receipt["l1_script_sha256_lf"] == _lf_sha256(L1_SCRIPT)
    assert receipt["g2_script_sha256_lf"] == _lf_sha256(G2_SCRIPT)
    assert receipt["g1_script_sha256_lf"] == _lf_sha256(G1_SCRIPT)


def test_receipt_records_the_checks_made_before_the_freeze():
    receipt = _load(RECEIPT)
    check = receipt["check"]
    for setting, wrapped in (("current", False), ("two_sided", True)):
        assert check[setting]["selftests"] == [
            json.dumps({"clear_after": "point", "tie_after": "interval", "wrapped": wrapped}, sort_keys=True)]
        for shape in ("sine", "pulse"):
            entry = check[setting]["by_shape"][shape]
            assert entry["at_truth"] == entry["cycles"] == 216
            assert entry["rise_at_truth"] == entry["rise_cycles"] == 216
    assert check["pulse_labels_unchanged"] is True
    assert receipt["r1_kept"] is True
    assert receipt["rise_fraction"] == 0.2
    assert receipt["corpus_records"] == 600 + 200 + 574
    assert receipt["library_gates"] == {"ratio": 3.0, "peak_pixels": 5}
    plan = " ".join(PLAN.read_text(encoding="utf-8").split())
    assert "**Construction check outcome (recorded before the freeze).**" in plan
    assert "**Pilot outcome (recorded before the freeze).**" in plan


def test_seeds_are_fresh():
    g2, l1, l2r1 = _scripts()
    new = {*l2r1.SEASONAL_SEEDS, *l2r1.NULL_SEEDS, *l2r1.INJECTION_SEEDS, *l2r1.PILOT_S_SEEDS, *l2r1.PILOT_I_SEEDS}
    old = {*g2.SEASONAL_SEEDS, *g2.NULL_SEEDS, *g2.INJECTION_SEEDS, *g2.PILOT_SEEDS, *g2.PILOT_I_SEEDS,
           *l1.SEASONAL_SEEDS, *l1.NULL_SEEDS, *l1.INJECTION_SEEDS, *l1.PILOT_S_SEEDS, *l1.PILOT_I_SEEDS}
    assert not new & old


def test_two_sided_rule_widens_only_when_a_later_month_ties():
    _, _, l2r1 = _scripts()
    assert l2r1.selftest() == l2r1.SELFTEST_EXPECTED


def test_results_cite_the_receipt_and_record_both_fails():
    results = _load(RESULTS)
    assert results["receipt_sha256_lf"] == _lf_sha256(RECEIPT)
    assert results["errors"] == {"current": 0, "two_sided": 0}
    for setting, wrapped in (("current", False), ("two_sided", True)):
        assert results["selftests_read_back"][setting] == [
            json.dumps({"clear_after": "point", "tie_after": "interval", "wrapped": wrapped}, sort_keys=True)]
    assert results["fingerprints"]["current"] == results["fingerprints"]["two_sided"]
    l2, r1 = results["l2"], results["r1"]
    assert l2["passes"] is False and r1["passes"] is False
    for arm in ("S", "I"):
        rules = l2["arms"][arm]
        assert (rules["rule_1"]["holds"], rules["rule_2"]["holds"]) == (False, False)
        assert (rules["rule_3"]["holds"], rules["rule_4"]["holds"]) == (True, True)
        assert rules["rule_4"]["records_with_changed_dates"] == 0
        assert r1["arms"][arm]["rule_2"]["holds"] is False
        assert r1["arms"][arm]["rule_3"]["holds"] is True
    assert r1["arms"]["S"]["rule_1"]["holds"] is True
    assert r1["arms"]["I"]["rule_1"]["holds"] is False


def test_results_doc_matches_the_scorer():
    l2, r1 = _load(RESULTS)["l2"], _load(RESULTS)["r1"]
    s1, i1 = l2["arms"]["S"]["rule_1"], l2["arms"]["I"]["rule_1"]
    assert (s1["current"]["not_correct"], s1["current"]["point_dates"]) == (899, 2981)
    assert (s1["two_sided"]["not_correct"], s1["two_sided"]["point_dates"]) == (529, 1908)
    assert (i1["current"]["not_correct"], i1["current"]["point_dates"]) == (1148, 4724)
    assert (i1["two_sided"]["not_correct"], i1["two_sided"]["point_dates"]) == (787, 3440)
    assert r1["arms"]["S"]["rule_1"]["pairs"] == 3503 and r1["arms"]["I"]["rule_2"]["pairs"] == 5329
    doc = " ".join(RESULTS_DOC.read_text(encoding="utf-8").split())
    assert _lf_sha256(RECEIPT) in doc
    for text in ("899 of 2,981 (30.2%)", "529 of 1,908 (27.7%)", "1,148 of 4,724 (24.3%)", "787 of 3,440 (22.9%)",
                 "−0.024 [−0.036, −0.012]", "−0.014 [−0.025, −0.004]",
                 "27.7% against 21.6%", "22.9% against 15.9%",
                 "0.799 against 0.542 (3,503 pairs)", "0.682 against 0.634 (5,200 pairs)",
                 "+0.257 [+0.235, +0.281]", "+0.047 [+0.012, +0.084]",
                 "0.752 against 0.872 (3,813 pairs)", "0.686 against 0.884 (5,329 pairs)",
                 "−0.120 [−0.141, −0.100]", "−0.198 [−0.225, −0.170]",
                 "617 of 4,724", "64 of 2,981"):
        assert text in doc, text
