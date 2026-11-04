"""Guards for the hydroseason-v0.3.0 proposal: its numbers must match their sources."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HANDOFF = Path("docs/handoff")
PROPOSAL = HANDOFF / "2026-11-04-v0.3.0-proposal.md"
SIMULATION = HANDOFF / "2026-11-04-v0.3.0-label-fix-impact.json"
SIMULATION_SCRIPT = Path("scripts/v030_label_fix_impact.py")
REAL_RECORD_RESULTS = HANDOFF / "2026-11-03-real-record-impact-results.json"
B1_RESULTS = HANDOFF / "2026-11-03-l1-followups-results.json"
B2_PLAN = HANDOFF / "2026-11-04-b2-refuge-labels-plan.md"


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _proposal() -> str:
    return " ".join(PROPOSAL.read_text(encoding="utf-8").split())


def test_simulation_cites_its_inputs():
    simulation = _load(SIMULATION)
    assert simulation["results_sha256_lf"] == _lf_sha256(REAL_RECORD_RESULTS)
    assert simulation["script_sha256_lf"] == _lf_sha256(SIMULATION_SCRIPT)
    assert simulation["gates"] == {"max_point_span_months": 0, "max_boundary_interval_months": 2,
                                   "max_broad_interval_months": 5, "min_informative_years": 7}


def test_proposal_matches_the_label_fix_simulation():
    g1, su = _load(SIMULATION)["simulation"]["g1"], _load(SIMULATION)["simulation"]["su"]
    assert (g1["point_troughs"], g1["changed_troughs"], g1["aggregate_changed"]) == (14761, 1480, 1131)
    assert g1["new_trough_status"] == {"interval": 627, "broad": 486, "unresolved": 367}
    assert (su["point_troughs"], su["changed_troughs"], su["aggregate_changed"]) == (4788, 157, 138)
    assert su["new_trough_status"] == {"interval": 56, "broad": 48, "unresolved": 53}
    assert g1["records_rerouted"] == su["records_rerouted"] == 0
    assert (g1["E0_eligible_cycles_lost"], g1["E0_eligible_cycles"]) == (247, 2549)
    assert (g1["E0_units_losing_baseline"], g1["E0_units_with_baseline"]) == (25, 97)
    assert (g1["E1_eligible_cycles_lost"], g1["E1_eligible_cycles"]) == (92, 9394)
    assert (g1["E1_units_losing_baseline"], g1["E1_units_with_baseline"]) == (15, 984)
    assert (su["E0_eligible_cycles_lost"], su["E0_eligible_cycles"], su["E0_units_losing_baseline"],
            su["E0_units_with_baseline"]) == (24, 1087, 3, 26)
    assert (su["E1_eligible_cycles_lost"], su["E1_eligible_cycles"], su["E1_units_losing_baseline"],
            su["E1_units_with_baseline"]) == (14, 3814, 1, 356)
    doc = _proposal()
    for text in ("| 14,761 | 4,788 |", "| 1,480 (10.0%) | 157 (3.3%) |", "| 627 / 486 / 367 | 56 / 48 / 53 |",
                 "| 1,131 | 138 |", "| 272 | 47 |", "| 0 | 0 |",
                 "247 of 2,549 (9.7%)", "92 of 9,394 (1.0%)", "25 of 97 (26%)", "15 of 984 (1.5%)",
                 "24 of 1,087 (2.2%)", "14 of 3,814 (0.4%)", "3 of 26", "1 of 356"):
        assert text in doc, text


def test_proposal_quotes_b1_including_the_labels_relaxing_adds():
    recharge = _load(B1_RESULTS)["b1"]["recharge"]
    doc = _proposal()
    for arm, chance in (("S", "0.440"), ("I", "0.423")):
        e1, both = recharge[f"{arm}|E1"]["agree_among_labelled"], recharge[f"{arm}|E1"]["agree_on_cycles_labelled_under_e0_and_e1"]
        added = (e1["k"] - both["k"]) / (e1["n"] - both["n"])
        assert f"{recharge[f'{arm}|chance_agreement_e1']:.3f}" == chance
        assert f"{added:.3f}" in doc
        assert f"{both['share']:.3f}" in doc
        assert f"{recharge[f'{arm}|E0']['agree_among_labelled']['share']:.3f}" in doc
    assert "| Cycles only the relaxed rule labels | 0.520 | 0.417 |" in doc


def test_proposal_links_resolve():
    text = PROPOSAL.read_text(encoding="utf-8")
    for name in ("2026-11-03-real-record-impact-results.md", "2026-11-03-l1-followups-results.md",
                 "2026-11-03-l2-r1-results.md", "2026-11-04-v0.3.0-label-fix-impact.json",
                 "2026-11-02-decisions-units-dates-hydropools.md", B2_PLAN.name):
        assert f"]({name})" in text, name
        assert (HANDOFF / name).exists(), name
