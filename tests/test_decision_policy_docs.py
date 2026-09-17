from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_decision_policy_document_contains_complete_promotion_gate():
    text = (ROOT / "docs" / "decision-policy.md").read_text(encoding="utf-8").casefold()
    required = (
        "new versioned decision-policy design",
        "predeclared metrics and acceptance thresholds",
        "synthetic calibration",
        "untouched synthetic validation partition",
        "independent real-catchment cohort",
        "empirical results or published scientific evidence",
        "comparison report",
        "migration notes",
        "regenerating expected fixtures",
    )
    assert all(phrase in text for phrase in required)
    # Promotion is complete (Task 8): the document now records the promoted
    # identifier and the historical baseline it was measured against, not a
    # pending-promotion state.
    normalized = " ".join(text.split())
    assert "promoted to public policy identifier `established_0_2_0`" in normalized
    assert "established_0_1_1` remains the historical baseline" in normalized


def test_v020_policy_design_freezes_public_decision_contract():
    text = (ROOT / "docs" / "decision-policy-0.2.0.md").read_text(encoding="utf-8")
    required = {
        "established_0_2_0",
        "zero frequency is descriptive only",
        "n_peak_timing_years",
        "n_trough_timing_years",
        "point",
        "interval",
        "unresolved",
        "false precise-boundary Wilson upper bound <= 0.05",
        "validation cannot trigger threshold reselection",
    }
    assert all(phrase in text for phrase in required)
    grid = {
        '"min_amplitude_to_floor_ratio": [1.0, 1.5, 2.0, 3.0],',
        '"min_peak_water_pixels": [1, 2, 3, 5],',
        '"max_point_span_months": [0, 1, 2],',
        '"max_boundary_interval_months": [2, 3, 4],',
        '"min_informative_years": [5, 7, 10],',
    }
    assert all(line in text for line in grid)
    assert "motivating records" in text.lower()
    assert "excluded from calibration fitting, threshold selection" in text
    assert "dry-duration and event summaries" in text


def test_v030_geometry_design_freezes_grid_and_selector():
    text = (ROOT / "docs" / "decision-policy-0.3.0.md").read_text(encoding="utf-8")
    required = {
        "TROUGH_GEOMETRY_GRID",
        "trough_search_radius_months",
        "adaptive_trough_search_radius_months",
        "adaptive_min_usable_months_per_cycle",
        "duplicate_or_nonmonotonic_rate",
        "boundary_signed_bias",
        "Status-quo tie-break",
        "GEOMETRY_CALIBRATION_SEEDS = range(30000, 35000)",
        "GEOMETRY_VALIDATION_SEEDS  = range(40000, 45000)",
    }
    missing = sorted(phrase for phrase in required if phrase not in text)
    assert not missing, f"frozen geometry design is missing: {missing}"


def test_v030_geometry_design_excludes_challenge_count_from_selection():
    """The outside-window challenge count must never become a selection metric.

    Selecting on it would reward any tuple that widens the window regardless of
    whether the wider choice is correct.
    """
    text = (ROOT / "docs" / "decision-policy-0.3.0.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "Report-only. **Excluded from selection.**" in normalized
    assert "`established_0_2_0` must **not** be silently retained across a geometry change." in normalized


def test_v030_geometry_design_records_null_result_as_publishable():
    text = (ROOT / "docs" / "decision-policy-0.3.0.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "Null result — shipped tuple `(3, 5, 6)` wins" in normalized
    assert "This is a real result and is reported as such, not as \"no change\"." in normalized




def test_recurrence_identifiability_promotion_docs():
    text_020 = (ROOT / "docs" / "decision-policy-0.2.0.md").read_text(encoding="utf-8")
    text_main = (ROOT / "docs" / "decision-policy.md").read_text(encoding="utf-8")
    text_mig = (ROOT / "docs" / "migrations" / "0.2.0-timing-identifiability.md").read_text(encoding="utf-8")

    # Selected policy
    assert "annual_shape_match" in text_020
    # Recurrence fingerprint at the scope actually shipped (promotion withheld)
    assert "4b08cd352ce67a6be999e28734963b0ce6b989163923a21d76da8762c5314b00" in text_020
    assert "candidate_for_established_0_2_0" in text_020
    assert "promotion is therefore withheld" in text_020
    # Timing fingerprint
    assert "e6cdf3ce960aa011711dc90e3ef4fb0135513eadaf471f4ac9e0656f80884735" in text_020
    # Both Wilson gates
    assert "false-point Wilson upper bound <= 0.05" in text_020
    assert "false-resolution Wilson upper bound <= 0.05" in text_020
    # Validation report path
    assert "2026-09-03-recurrence-identifiability-validation.json" in text_020
    # Cohort status statement
    assert "case_studies/recurrence-identifiability/cohort-protocol.json" in text_020
    # Unchanged policy ID
    assert "established_0_2_0" in text_020
    assert "established_0_2_0" in text_main
    # Unchanged package version
    assert "0.2.0" in text_020
    # Recurrence promotion in decision-policy.md
    assert "2026-09-03-recurrence-identifiability-promotion.json" in text_main
    # Bounds of equivalent evidence in migration notes
    assert "bounds of equivalent evidence" in text_mig


def test_docs_name_the_only_method_and_manifest():
    combined = "\n".join(
        (Path(path) if Path(path).is_file() else ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/methods.md", "docs/cli-recipes.md")
    )
    assert "hydroseason-v0.2.0" in combined
    assert "run manifest" in combined.lower()
    assert "--method-policy" not in combined
    assert "candidate_timing_recurrence" not in combined
    assert "established_0_2_0" not in combined


def test_library_docs_do_not_claim_completed_evidence_absent_from_receipts():
    methods_path = Path("docs/methods.md") if Path("docs/methods.md").is_file() else ROOT / "docs/methods.md"
    receipts_path = Path("docs/evidence-receipts.json") if Path("docs/evidence-receipts.json").is_file() else ROOT / "docs/evidence-receipts.json"
    methods = methods_path.read_text(encoding="utf-8")
    receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
    for item in receipts["evidence"]:
        assert item["stage"] in methods
        assert str(item["denominator"]) in methods



