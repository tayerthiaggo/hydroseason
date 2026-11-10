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


RESULTS = HANDOFF / "2026-11-08-de2-end-of-low-results.json"
RESULTS_DOC = HANDOFF / "2026-11-08-de2-end-of-low-results.md"
EXTRAS = HANDOFF / "2026-11-08-de2-end-of-low-extras.json"


@pytest.mark.skipif(not RESULTS.exists(), reason="DE2 not scored yet")
def test_results_cite_the_receipt_and_record_the_reading():
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert results["receipt_sha256_lf"] == _lf_sha256(RECEIPT)
    assert results["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert results["records"] == 3148
    assert results["errors"] == {"current": [], "candidate": []}
    assert results["fingerprints"] == {"current": [receipt["current_fingerprint"]],
                                       "candidate": [receipt["candidate_fingerprint"]]}
    assert results["decision"] == "R1 and R2 go to the implementation checks"
    assert results["rule_4_reviewed_gates"]["passed"] is True
    for arm in ("S", "I"):
        assert all(results["rules"][arm][r]["outcome"] == "holds" for r in ("rule_1", "rule_2", "rule_3"))


@pytest.mark.skipif(not RESULTS.exists(), reason="DE2 not scored yet")
def test_results_doc_matches_the_scorer():
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    extras = json.loads(EXTRAS.read_text(encoding="utf-8"))
    assert extras["results_sha256_lf"] == _lf_sha256(RESULTS)
    doc = " ".join(RESULTS_DOC.read_text(encoding="utf-8").split())
    assert results["receipt_sha256_lf"] in doc
    for arm in ("S", "I"):
        for name in ("rule_1", "rule_2", "rule_3"):
            rule = results["rules"][arm][name]
            text = (f"{rule['difference']:+.3f} [{rule['ci95'][0]:+.3f}, {rule['ci95'][1]:+.3f}]").replace("-", "−")
            assert text in doc, (arm, name, text)
        r2 = extras["r2_ephemeral_labels"][arm]
        assert f"{r2['covered']:,} of {r2['labels']:,}" in doc
    tiles = extras["fitzroy_tiles"]
    assert (tiles["late3_before"], tiles["late3_after"]) == (251, 104)
    assert tiles["tiles_routed_to_events"] == []


IMPLEMENTATION = HANDOFF / "2026-11-08-de2-implementation-checks.json"
IMPLEMENTATION_DOC = HANDOFF / "2026-11-08-de2-implementation-checks.md"


def _fingerprint_before_change_f() -> str:
    """Today's policy without the settings release change F pinned (values unchanged).

    Hashing to the fingerprint the DE2 checks recorded shows change F only added pins.
    """
    from hydroseason._method_policy import method_policy_manifest

    manifest = method_policy_manifest()
    for key in ("trough_search", "boundary_selection", "peak_quality"):
        manifest.pop(key)
    manifest["trough_refinement"].pop("l_grid_steps_per_scale")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@pytest.mark.skipif(not IMPLEMENTATION.exists(), reason="DE2 implementation checks not run yet")
def test_implementation_checks_match_the_note_and_the_library():
    result = json.loads(IMPLEMENTATION.read_text(encoding="utf-8"))
    assert result["fingerprint"] == _fingerprint_before_change_f()
    assert result["script_sha256_lf"] == _lf_sha256(Path("scripts/de2_implementation_checks.py"))
    real = result["real_records"]
    assert real["records"] == 4468 and real["errors"] == []
    assert list(real["fingerprints"]) == [_fingerprint_before_change_f()]
    assert set(result["case_studies"]["event_and_spell_tables"].values()) == {"identical"}
    assert result["fitzroy_tiles"]["late3"] == [251, 104]
    doc = " ".join(IMPLEMENTATION_DOC.read_text(encoding="utf-8").split())
    halves = real["g1_half_agreement_within_1"]
    assert f"{halves['before']['share']:.3f} → {halves['after']['share']:.3f}" in doc
    assert f"| G1 quadrants | {real['cycles']['g1|quadrant']:,} |" in doc
