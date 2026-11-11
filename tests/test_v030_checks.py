"""Guards for the hydroseason-v0.3.0 implementation checks (case studies, real records, rescore)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
DOC = HANDOFF / "2026-11-04-v0.3.0-implementation-checks.md"
CASES = HANDOFF / "2026-11-04-v0.3.0-case-study-comparison.json"
REAL = HANDOFF / "2026-11-04-v0.3.0-real-record-check.json"
OLD_REAL = HANDOFF / "2026-11-03-real-record-impact-results.json"
SIMULATION = HANDOFF / "2026-11-04-v0.3.0-label-fix-impact.json"
RESCORE = HANDOFF / "2026-11-04-v0.3.0-known-truth-rescore.json"
FINGERPRINT_BEFORE_DRY_RUN = "4d11d348a745e980d25b933c3f51fe90e7b5931e856223b597c9d5e3566db578"


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _doc() -> str:
    return " ".join(DOC.read_text(encoding="utf-8").split())


def test_case_studies_change_only_the_baseline():
    result = _load(CASES)
    assert result["unexpected_differences"] == []
    eligible = {key: (s.get("eligible_before"), s.get("eligible_after"), s.get("labelled_after"))
                for key, s in result["series"].items()}
    assert len(eligible) == 20
    assert eligible["daly_river_nt_30m"] == (2, 4, 0)
    assert eligible["fitzroy_river_wa_30m"] == (1, 7, 21)
    assert eligible["gilbert_river_qld_30m"] == (3, 9, 21)
    assert eligible["fitzroy_river_wa_300m"] == (1, 8, 20)
    for key, series in result["series"].items():
        assert series["summary_unexpected"] == [], key
        if key.startswith(("lachlan", "moonie")):
            assert series["route"] == "event_characterisation", key
        else:
            assert series["hydro_years"]["unexpected"] == {}, key
            assert series["monthly_phase"]["changed"] == {}, key
            assert series["labelled_before"] == 0, key


def test_real_record_rerun_meets_the_proposal_criteria():
    result = _load(REAL)
    assert result["script_sha256_lf"] == _lf_sha256(Path("scripts/v030_real_record_check.py"))
    # The rerun predates the reported dry run (DE1 change A), which later joined the manifest.
    assert result["policies"] == [["hydroseason-v0.3.0", FINGERPRINT_BEFORE_DRY_RUN, 4468]]
    assert result["records"] == 4468 and result["errors"] == []
    assert result["route_changes"] == [] and result["cycle_count_changes"] == []
    assert result["unexpected_changed_fields"] == {}
    assert result["dated_troughs_not_covering_boundary"] == {}
    assert sum(result["dated_troughs"].values()) == 64746
    assert result["e0_mismatches_new"] == 0
    assert "trough_interval_start" not in result["changed_fields"]
    assert all(v["differs"]["k"] == 0 for v in result["m2_mismatch_new"].values())
    assert sum(v["point_troughs"] for v in result["m2_mismatch_new"].values()) == 17912


def test_point_trough_changes_match_the_simulation():
    result = _load(REAL)
    simulation = _load(SIMULATION)["simulation"]
    assert result["simulation"] == simulation
    for family in ("g1", "su"):
        moved = {}
        for key, n in result["trough_label_transitions"].items():
            source, _scale, transition = key.split("|")
            before, after = transition.split("->")
            if source == family and before == "point":
                moved[after] = moved.get(after, 0) + n
        assert moved == simulation[family]["new_trough_status"], family
        assert sum(moved.values()) == simulation[family]["changed_troughs"], family


def test_coverage_numbers_in_the_doc():
    old = _load(OLD_REAL)["m1"]["coverage"]
    new = _load(REAL)["coverage_new"]
    sources = sorted({key.rsplit("|", 1)[0] for key in new})
    units = sum(new[f"{s}|E0"]["units"] for s in sources)
    before = sum(old[f"{s}|E0"]["units_with_baseline"]["k"] for s in sources)
    c_alone = sum(old[f"{s}|E1"]["units_with_baseline"]["k"] for s in sources)
    after = sum(new[f"{s}|E0"]["units_with_baseline"]["k"] for s in sources)
    refuge = (sum(old[f"{s}|E0"]["refuge_labelled"]["k"] for s in sources),
              sum(new[f"{s}|E0"]["refuge_labelled"]["k"] for s in sources),
              sum(new[f"{s}|E0"]["cycles"] for s in sources))
    assert (units, before, c_alone, after) == (3010, 123, 1340, 1318)
    assert refuge == (4232, 44052, 97227)
    assert sum(_load(REAL)["units_losing_e1_baseline"].values()) == c_alone - after == 22
    doc = _doc()
    for text in ("**123 (4.1%)**", "**1,340**", "**1,318 (43.8%)**", "| 274 (61.4%) |", "| 690 (44.4%) |",
                 "4,232 to 44,052 of 97,227", "0 of 64,746", "1,637 of 19,549", "0 of 17,912",
                 "22 units", "607 of 3,648", "94 of 546", "3 h 3 min (10,968 s)"):
        assert text in doc, text


def test_rescore_numbers_in_the_doc():
    rescore = _load(RESCORE)
    doc = _doc()
    for test, arm in (("l1", "S"), ("l1", "I"), ("l2", "S"), ("l2", "I")):
        for side in ("before", "after"):
            point = rescore[test]["arms"][arm][side]["point"]
            text = f"{100 * point['share']:.1f}% ({point['not_correct']:,} of {point['point_dates']:,})"
            assert text in doc, text


def test_validation_receipt_evidence_is_current():
    receipt = _load(Path("docs/method-policy-v0.3.0-validation.json"))
    evidence = receipt["evidence_sha256_lf"]
    for name in ("case_study_comparison", "real_record_check", "implementation_checks"):
        assert name in evidence, name
    for name, entry in evidence.items():
        assert entry["sha256_lf"] == _lf_sha256(Path(entry["path"])), name


def test_fitzroy_tile_results_match_the_note():
    result = _load(HANDOFF / "2026-11-05-v0.3.0-fitzroy-tiles.json")
    identity = _load(HANDOFF / "2026-11-05-v0.3.0-fitzroy-tiles-identity.json")
    assert result["unexpected"] == {}
    assert all(v == {} for k, v in identity.items() if not k.startswith("_"))
    assert sum(1 for k in identity if not k.startswith("_")) == 40
    production, counts = result["summary"]["production"], result["summary"]["counts"]
    assert (production["tiles"], production["tile_years"], counts["tiles"], counts["tile_years"]) == (40, 1600, 41, 1640)
    doc = " ".join((HANDOFF / "2026-11-05-v0.3.0-fitzroy-tiles.md").read_text(encoding="utf-8").split())
    rows = {
        "Failing tile-years": ("fails_before", "fails_after"),
        "Cycles anchoring the condition baseline": ("baseline_eligible_before", "baseline_eligible_after"),
        "Tiles with condition labels": ("tiles_with_labels_before", "tiles_with_labels_after"),
        "Labelled tile-years": ("labelled_years_before", "labelled_years_after"),
    }
    for label, (before, after) in rows.items():
        text = (f"| {label} | {production[before]:,} → {production[after]:,} | "
                f"{counts[before]:,} → {counts[after]:,} |")
        assert text in doc, text
    assert (f"| Earlier labels that change | {production['label_changed_where_both']} of "
            f"{production['labelled_both']} | {counts['label_changed_where_both']} of {counts['labelled_both']} |") in doc
    assert (f"| hydropools end-dry clock moves | {production['clock_changes']} | {counts['clock_changes']} |") in doc
