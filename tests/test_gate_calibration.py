"""Guards for the G1 gate calibration record and the results document built on it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-02-g1-gate-calibration-plan.md"
RECEIPT = HANDOFF / "2026-11-02-g1-gate-calibration-receipt.json"
RESULTS_JSON = HANDOFF / "2026-11-02-g1-gate-calibration-results.json"
RESULTS_MD = HANDOFF / "2026-11-02-g1-gate-calibration-results.md"
SYNTHETIC = HANDOFF / "2026-11-02-g1-synthetic-suite-rerun.json"
SCRIPT = Path("scripts/gate_calibration.py")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _doc() -> str:
    return " ".join(RESULTS_MD.read_text(encoding="utf-8").split())


def test_receipt_froze_the_plan_and_the_script():
    receipt = _load(RECEIPT)
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)
    assert receipt["phase_b"]["holds"] is True


def test_results_cite_the_receipt():
    receipt_hash = _lf_sha256(RECEIPT)
    assert _load(RESULTS_JSON)["receipt_sha256_lf"] == receipt_hash
    assert receipt_hash in RESULTS_MD.read_text(encoding="utf-8")


def test_results_doc_matches_the_confirmation():
    results = _load(RESULTS_JSON)
    doc = _doc()
    current, chosen = results["current"], results["chosen"]
    assert (
        f"| Current (3.0, 5 pixels) | {current['reproducibility']:.3f} | {current['passes']:,.0f} | "
        f"{current['route_agreement']:.3f} |"
    ) in doc
    assert (
        f"| Chosen (1.5, 2 pixels) | {chosen['reproducibility']:.3f} | {chosen['passes']:,.0f} | "
        f"{chosen['route_agreement']:.3f} |"
    ) in doc
    growth = chosen["passes"] / current["passes"] - 1
    assert f"{100 * growth:.1f}% more half-cycles" in doc
    assert results["gates_chosen"] == [1.5, 2, 0]
    assert results["adopt"] is True and results["loosening_rule"] is True
    assert all(results["checks"].values())


def test_library_gates_are_unchanged_by_the_study():
    assert TIMING_IDENTIFIABILITY_DEFAULTS.min_amplitude_to_floor_ratio == 3.0
    assert TIMING_IDENTIFIABILITY_DEFAULTS.min_peak_water_pixels == 5
    assert "This is **not a library change**." in _doc()


def test_synthetic_suite_cannot_separate_the_gates():
    record = _load(SYNTHETIC)
    assert record["source_commit_resolved"].startswith("a6e5a41")
    for partition in record["partitions"].values():
        bands = partition["rows_by_ratio"]
        assert bands["[0,1)"] == bands["[1,1.5)"] == bands["[1.5,3)"] == 0
        assert partition["rows_with_ratio_above_0_and_peak_pixels_below_5"] == 0
        scores = [
            {k: v for k, v in gate.items() if k not in ("ratio", "peak_pixels")}
            for gate in partition["gates"].values()
        ]
        assert all(score == scores[0] for score in scores)
    reselection = record["partitions"]["calibration"]["reselection"]
    assert (reselection["ratio"], reselection["peak_pixels"]) == (3.0, 5)
    assert "None lies between 0 and 3." in _doc()
