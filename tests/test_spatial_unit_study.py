"""Guards for the spatial unit study record and the guide advice built on it.

The study ran on local data (scripts/spatial_unit_study.py); these tests only
read the committed record, so they run anywhere. They fail if the plan or the
study script changes after the receipt froze them, or if the results doc or
the guide quote a number the recorded results do not support.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
PLAN = HANDOFF / "2026-11-02-spatial-unit-study-plan.md"
RECEIPT = HANDOFF / "2026-11-02-spatial-unit-study-receipt.json"
RESULTS_JSON = HANDOFF / "2026-11-02-spatial-unit-study-results.json"
EXPLORATORY_JSON = HANDOFF / "2026-11-02-spatial-unit-study-exploratory.json"
RESULTS_MD = HANDOFF / "2026-11-02-spatial-unit-study-results.md"
SCRIPT = Path("scripts/spatial_unit_study.py")
GUIDE = Path("docs/guide.md")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _signed(value: float, digits: int = 3) -> str:
    return f"{value:+.{digits}f}".replace("-", "−")


def _plain(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace("-", "−")


def _guide_section() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    return text.split("## Choosing the area to analyse", 1)[1].split("\n## ", 1)[0]


def test_receipt_froze_the_plan_and_the_study_script():
    receipt = _load(RECEIPT)
    assert receipt["plan_sha256_lf"] == _lf_sha256(PLAN)
    assert receipt["script_sha256_lf"] == _lf_sha256(SCRIPT)


def test_results_cite_the_receipt_and_the_plan():
    receipt_hash = _lf_sha256(RECEIPT)
    assert _load(RESULTS_JSON)["receipt_sha256_lf"] == receipt_hash
    doc = RESULTS_MD.read_text(encoding="utf-8")
    assert receipt_hash in doc
    assert _load(RECEIPT)["plan_sha256_lf"] in doc


def test_results_doc_reports_the_recorded_decisions():
    results = _load(RESULTS_JSON)
    doc = RESULTS_MD.read_text(encoding="utf-8")

    c1 = results["c1_unit_type"]
    assert c1["decision"] == "equivalent"
    assert "the decision is **Equivalent**" in doc
    for outcome in c1["outcomes"].values():
        low, high = outcome["ci95"]
        assert f"| {_signed(outcome['difference'])} | {_plain(low)} to {_plain(high)} |" in doc

    for unit_type in ("subbasin", "tile"):
        assert results["c2_size"][unit_type]["by_water_pixels"]["minimum_lower_edge"] == 0
        for item in results["c2_size"][unit_type]["by_water_pixels"]["bins"].values():
            if item["n"]:
                assert f"{item['seasonal_share']:.3f}" in doc

    c3 = results["c3_asynchrony"]
    assert c3["material"] is False
    assert f"{100 * c3['trough']['share_more_than_1_month']:.1f}%" in doc

    c4 = results["c4_hidden_seasonality"]
    assert c4["material"] is True
    lachlan = c4["per_catchment"]["lachlan_river_nsw"]
    assert f"Lachlan {round(lachlan['size'] * lachlan['mean'])} of {lachlan['size']}" in doc
    assert f"{100 * c4['share_routed_seasonal']:.1f}%" in doc


def test_guide_advice_matches_the_study():
    section = _guide_section()
    results = _load(RESULTS_JSON)
    exploratory = _load(EXPLORATORY_JSON)

    assert f"{results['n_units']:,} areas" in section
    assert "10.1002/hyp.9740" in section

    routed = results["c1_unit_type"]["outcomes"]["routed_seasonal"]
    low, high = (100 * v for v in routed["ci95"])
    assert (
        f"{_plain(100 * routed['difference'], 1)} percentage points, 95% interval "
        f"{_plain(low, 1)} to {_signed(high, 1)}"
    ) in section
    confirmed = results["c1_unit_type"]["outcomes"]["confirmed_share"]
    low, high = (100 * v for v in confirmed["ci95"])
    assert f"{_signed(100 * confirmed['difference'], 1)} points, {_plain(low, 1)} to {_signed(high, 1)}" in section

    small = [
        bins["[0,100)"]["trough_within_1_month_of_catchment"]
        for bins in exploratory["quality_and_timing_by_water_pixels"].values()
    ]
    assert f"{round(100 * min(small))}–{round(100 * max(small))}%" in section
    larger = [
        item["trough_within_1_month_of_catchment"]
        for bins in exploratory["quality_and_timing_by_water_pixels"].values()
        for label, item in bins.items()
        if label != "[0,100)"
    ]
    assert f"against {int(100 * min(larger))}% or more" in section

    lachlan = results["c4_hidden_seasonality"]["per_catchment"]["lachlan_river_nsw"]
    assert f"{round(lachlan['size'] * lachlan['mean'])} of its {lachlan['size']}" in section
    assert f"{100 * results['c3_asynchrony']['trough']['share_more_than_1_month']:.1f}%" in section
    assert "run its subbasins before concluding it has no season" in section
