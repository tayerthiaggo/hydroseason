"""Guards for the X1 cross-scale agreement record and the guide advice built on it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-02-x1-cross-scale-agreement-plan.md"
RECEIPT = HANDOFF / "2026-11-02-x1-cross-scale-agreement-receipt.json"
RESULTS_JSON = HANDOFF / "2026-11-02-x1-cross-scale-agreement-results.json"
RESULTS_MD = HANDOFF / "2026-11-02-x1-cross-scale-agreement-results.md"
SCRIPT = Path("scripts/cross_scale_agreement.py")
GUIDE = Path("docs/guide.md")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_receipt_froze_the_plan_and_the_script():
    receipt = _load(RECEIPT)
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)


def test_results_cite_the_receipt():
    receipt_hash = _lf_sha256(RECEIPT)
    assert _load(RESULTS_JSON)["receipt_sha256_lf"] == receipt_hash
    assert receipt_hash in RESULTS_MD.read_text(encoding="utf-8")


def test_results_doc_matches_the_recorded_agreement():
    results = _load(RESULTS_JSON)
    doc = RESULTS_MD.read_text(encoding="utf-8")
    for key in ("parent_peak", "parent_trough", "catchment_peak", "catchment_trough"):
        table = results["agreement"][key]
        low, high = table["ci95"]
        assert f"| {table['pooled']:.3f} | {low:.3f}–{high:.3f} | {table['n']:,} |" in doc
    assert results["r2_peak_vs_trough"]["decision"] == "peaks_more_widely_shared"
    assert results["r1_minimum_water_pixels"] == {
        "parent_peak": 0, "parent_trough": 100, "catchment_peak": 100, "catchment_trough": None,
    }
    assert all(v["parent_closer"] for v in results["r3_parent_vs_catchment"].values())


def test_guide_borrowing_advice_matches_the_study():
    agreement = _load(RESULTS_JSON)["agreement"]
    section = GUIDE.read_text(encoding="utf-8").split("## Choosing the area to analyse", 1)[1]
    section = " ".join(section.split("\n## ", 1)[0].split())
    pct = {k: round(100 * v["pooled"]) for k, v in agreement.items()}
    assert (
        f"agreed with the subbasin containing it in {pct['parent_peak']}% of cycles and with its "
        f"catchment in {pct['catchment_peak']}%. Its trough boundary agreed in "
        f"{pct['parent_trough']}% and {pct['catchment_trough']}%"
    ) in section
    above_100 = [
        v["share"] for k in ("parent_peak", "parent_trough")
        for label, v in agreement[k]["by_water_pixels"].items()
        if label != "[0,100)" and v["n"] >= 30
    ]
    assert f"at least {int(100 * min(above_100))}% of cycles" in section
    largest = agreement["catchment_trough"]["by_water_pixels"]["[10000,100000)"]["share"]
    assert largest < 0.80 and "fell below 80% agreement even for the largest subbasins" in section
