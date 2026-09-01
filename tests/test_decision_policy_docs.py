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


def test_cohort_protocol_declares_amplitude_strata_and_safe_quota():
    protocol = json.loads(
        (ROOT / "case_studies" / "timing-identifiability" / "cohort-protocol.json")
        .read_text(encoding="utf-8")
    )

    assert protocol["seed"] == 20260901
    assert protocol["exclude_station_ids"] == ["130413a", "130407a", "130302a"]
    assert protocol["stratification"]["variable"] == "amplitude_to_floor_ratio"
    assert protocol["stratification"]["reported_covariate"] == "zero_fraction"
    assert protocol["stratification"]["strata"] == [
        {"name": "below_floor", "lower": 0, "upper": 1, "upper_inclusive": False},
        {"name": "mid_ratio", "lower": 1, "upper": 3, "upper_inclusive": False},
        {"name": "high_ratio", "lower": 3, "upper": "inf", "upper_inclusive": True},
    ]
    assert protocol["quota_policy"] == "min_8_or_available"
    assert protocol["shortfall_is_reported_not_fatal"] is True
    assert isinstance(protocol["source_bundles"], list)
    assert protocol["pixel_support_expected"] == "unavailable"


def test_review_rubric_freezes_blinded_labels_and_adjudication():
    text = (
        ROOT / "case_studies" / "timing-identifiability" / "review-rubric.md"
    ).read_text(encoding="utf-8")
    labels = {
        "point_supported",
        "interval_supported",
        "event_only",
        "unobservable",
        "uncertain",
    }
    assert all(label in text for label in labels)
    assert "one reviewer" in text
    assert "adjudication" in text
    assert "excluded from rate denominators" in text
    for hidden in ("regime", "route", "timing status", "confidence", "selected thresholds"):
        assert hidden in text
