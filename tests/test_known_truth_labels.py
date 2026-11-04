"""Guards for the L1 known-truth test of the trough timing labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-03-l1-timing-labels-plan.md"
RECEIPT = HANDOFF / "2026-11-03-l1-timing-labels-receipt.json"
RESULTS = HANDOFF / "2026-11-03-l1-timing-labels-results.json"
RESULTS_DOC = HANDOFF / "2026-11-03-l1-timing-labels-results.md"
SCRIPT = Path("scripts/known_truth_labels.py")
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
    assert receipt["g2_script_sha256_lf"] == _lf_sha256(G2_SCRIPT)
    assert receipt["g1_script_sha256_lf"] == _lf_sha256(G1_SCRIPT)


def test_receipt_records_the_checks_made_before_the_freeze():
    receipt = _load(RECEIPT)
    assert receipt["settings_kept"] == ["current", "k1", "k2", "k3"]
    expected_probe = {"current": 2, "k1": 3, "k2": 4, "k3": 5}
    for setting, check in receipt["check"].items():
        assert check["selftests"] == [json.dumps({"max": 1, "min": expected_probe[setting]}, sort_keys=True)]
        for shape in ("sine", "pulse"):
            assert check["by_shape"][shape]["at_truth"] == check["by_shape"][shape]["cycles"] > 0
    assert receipt["corpus_records"] == 600 + 200 + 574
    assert receipt["library_gates"] == {"ratio": 3.0, "peak_pixels": 5}
    plan = " ".join(PLAN.read_text(encoding="utf-8").split())
    assert "**Construction check outcome (recorded before the freeze).**" in plan
    assert "**Pilot outcome (recorded before the freeze).**" in plan


def test_l1_seeds_do_not_overlap_g2():
    import sys

    sys.path.insert(0, str(Path("scripts").resolve()))
    import known_truth_gates as g2
    import known_truth_labels as l1

    l1_seeds = {*l1.SEASONAL_SEEDS, *l1.NULL_SEEDS, *l1.INJECTION_SEEDS, *l1.PILOT_S_SEEDS, *l1.PILOT_I_SEEDS}
    g2_seeds = {*g2.SEASONAL_SEEDS, *g2.NULL_SEEDS, *g2.INJECTION_SEEDS, *g2.PILOT_SEEDS, *g2.PILOT_I_SEEDS}
    assert not l1_seeds & g2_seeds


def test_results_cite_the_receipt_and_record_no_candidate():
    results = _load(RESULTS)
    assert results["receipt_sha256_lf"] == _lf_sha256(RECEIPT)
    assert results["errors"] == {"current": 0, "k1": 0, "k2": 0, "k3": 0}
    expected_probe = {"current": 2, "k1": 3, "k2": 4, "k3": 5}
    for setting, probe in expected_probe.items():
        assert results["selftests_read_back"][setting] == [json.dumps({"max": 1, "min": probe}, sort_keys=True)]
        assert len(results["factors_read_back"][setting]) == 1
    confirmation = results["confirmation"]
    assert confirmation["confirmed"] is True
    assert (confirmation["arms"]["S"]["not_correct"], confirmation["arms"]["S"]["point_dates"]) == (784, 2779)
    assert (confirmation["arms"]["I"]["not_correct"], confirmation["arms"]["I"]["point_dates"]) == (1192, 4837)
    for setting in ("k1", "k2", "k3"):
        entry = results["settings"][setting]
        assert entry["passes"] is False
        for arm in ("S", "I"):
            assert entry["arms"][arm]["rule_1"]["holds"] is False
            assert entry["arms"][arm]["rule_2"]["holds"] is True
            assert entry["arms"][arm]["rule_3"]["holds"] is True
    k3 = results["settings"]["k3"]["arms"]
    assert (k3["S"]["rule_1"]["not_correct"], k3["S"]["rule_1"]["point_dates"]) == (387, 1578)
    assert (k3["I"]["rule_1"]["not_correct"], k3["I"]["rule_1"]["point_dates"]) == (726, 3178)
    assert results["passing_settings"] == []
    assert results["candidate"] is None
    for setting in ("current", "k1", "k2", "k3"):
        assert results["null"][setting]["point_trough_dates"] == 0
        assert results["null"][setting]["routed_per_year_detection"] == 0.0


def test_results_doc_matches_the_scorer():
    doc = " ".join(RESULTS_DOC.read_text(encoding="utf-8").split())
    results = _load(RESULTS)
    assert results["receipt_sha256_lf"] in doc
    assert "**The G2 finding is confirmed on fresh records. No tolerance setting passes, so there is no candidate" in doc
    for text in ("784 of 2,779 (28.2%)", "1,192 of 4,837 (24.6%)", "387 of 1,578 (24.5%)", "726 of 3,178 (22.8%)",
                 "644 of 2,305 (27.9%)", "1,041 of 4,227 (24.6%)", "452 of 1,737 (26.0%)", "804 of 3,411 (23.6%)"):
        assert text in doc, text


def test_library_trough_tolerance_unchanged_after_l1():
    """L1 named no candidate, so the pass-1 trough tolerance stays one detectability floor."""
    import inspect

    from hydroseason import _timing_identifiability

    source = " ".join(inspect.getsource(_timing_identifiability.assess_window_timing).split())
    assert 'trough_values, kind="min", tolerance=detectability_floor_pp )' in source
