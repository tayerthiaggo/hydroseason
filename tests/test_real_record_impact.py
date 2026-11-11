"""Guards for the real-record impact measurement (baseline timing requirement; trough label/date mismatch)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-03-real-record-impact-plan.md"
RESULTS = HANDOFF / "2026-11-03-real-record-impact-results.json"
EXPLORATORY = HANDOFF / "2026-11-03-real-record-impact-exploratory.json"
RESULTS_DOC = HANDOFF / "2026-11-03-real-record-impact-results.md"
SCRIPT = Path("scripts/real_record_impact.py")
EXPLORE_SCRIPT = Path("scripts/real_record_impact_explore.py")
L1_FOLLOWUPS = Path("scripts/l1_followups.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _doc() -> str:
    return " ".join(RESULTS_DOC.read_text(encoding="utf-8").split())


def test_results_cite_the_plan_and_scripts_and_pass_the_checks():
    results = _load(RESULTS)
    assert results["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert results["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert results["l1_followups_sha256_lf"] == _lf_sha256(L1_FOLLOWUPS)
    assert results["records"] == 3190 + 1278
    assert results["errors"] == []
    assert results["e0_mismatches"] == 0
    assert results["g1_series_match_receipt"] is True


def test_exploratory_cites_the_results_and_its_script():
    exploratory = _load(EXPLORATORY)
    assert exploratory["results_sha256_lf"] == _lf_sha256(RESULTS)
    assert exploratory["script_sha256_lf"] == _lf_sha256(EXPLORE_SCRIPT)


def test_primary_comparison_follows_the_plan():
    repro = _load(RESULTS)["m1"]["reproducibility"]
    for kind in ("recharge", "refuge"):
        entry = repro[kind]
        assert entry["E0"]["n"] >= 100
        assert entry["primary"] == "added_minus_e0"
        assert entry["added_minus_e0"]["reading"] == "inconclusive"
    assert repro["recharge"]["not_point_minus_point"]["reading"] == "no_evidence_of_a_cost"
    assert repro["refuge"]["not_point_minus_point"]["reading"] == "inconclusive"


def test_results_doc_matches_the_measures():
    results = _load(RESULTS)
    m1, m2 = results["m1"], results["m2"]
    assert m1["coverage"]["g1|core|E0"]["units_with_baseline"]["k"] == 24
    assert m1["coverage"]["g1|core|E1"]["units_with_baseline"]["k"] == 278
    assert m1["coverage"]["g1|quadrant|E1"]["units_with_baseline"]["k"] == 706
    assert (m2["g1|core"]["differs"]["k"], m2["g1|core"]["point_troughs"]) == (472, 3843)
    assert (m2["g1|quadrant"]["differs"]["k"], m2["g1|quadrant"]["point_troughs"]) == (1008, 10918)
    assert m2["su|catchment"]["differs"]["k"] == 0
    assert m1["stability"]["recharge"]["changed"]["k"] == 534
    assert m1["stability"]["refuge"]["changed"]["k"] == 700
    causes = _load(EXPLORATORY)["mismatch_causes"]["g1"]
    assert causes["differs"] == 472 + 1008
    assert causes["causes"] == {"cloud_screened_raw_minimum": 701, "lower_month_outside_search_window": 489,
                                "other": 290}
    assert (causes["gap_one_month"], causes["gap_median"], causes["gap_max"]) == (367, 3.0, 14)
    doc = _doc()
    assert results["plan_sha256_lf"] in doc and results["script_sha256_lf"] in doc
    assert _lf_sha256(RESULTS) in doc and _lf_sha256(EXPLORE_SCRIPT) in doc
    for text in ("24 (5.4%) | 278 (62.3%)", "73 (4.7%) | 706 (45.4%)",
                 "475 of 637 (74.6%)", "8,075 of 11,200 (72.1%)", "433 of 637 (68.0%)", "7,458 of 11,200 (66.6%)",
                 "−0.025 [−0.104, +0.052]", "−0.014 [−0.096, +0.069]",
                 "−0.001 [−0.034, +0.028]", "−0.039 [−0.073, −0.004]",
                 "0.57 [0.54, 0.59]", "0.43 [0.39, 0.46]",
                 "−0.10 [−0.22, +0.02]", "−0.12 [−0.18, −0.06]",
                 "534 of 4,103 recharge labels (13.0%)", "700 of 4,232 refuge labels (16.5%)",
                 "472 (12.3%)", "1,008 (9.2%)", "701 (47.4%)", "489 (33.0%)", "290 (19.6%)", "367 (24.8%)"):
        assert text in doc, text
