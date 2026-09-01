from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


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
    assert "identifier remains `established_0_1_1`" in text
    assert "until promotion passes" in text
    assert "its public policy identifier is `established_0_2_0`" not in text


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
        {"name": "high_ratio", "lower": 3, "upper": "inf", "upper_inclusive": False},
    ]
    assert protocol["quota_policy"] == "min_8_or_available"
    assert protocol["shortfall_is_reported_not_fatal"] is True
    assert isinstance(protocol["source_bundles"], list)
    assert protocol["source_bundles"] == ["stress_test_final"]
    assert protocol["pixel_support_expected"] == "unavailable"
    assert protocol["exclude_motivating_records_from_calibration_and_validation"] is True
    assert protocol["reproducibility_metadata"] == {
        "package_version": "0.2.0",
        "input_fingerprint": "required in generated manifest",
        "threshold_fingerprint": "required from calibrated defaults",
        "seed": 20260901,
    }


def test_review_rubric_freezes_blinded_labels_and_adjudication():
    text = (
        ROOT / "case_studies" / "timing-identifiability" / "review-rubric.md"
    ).read_text(encoding="utf-8")
    labels = [
        "point_supported",
        "interval_supported",
        "event_only",
        "unobservable",
        "uncertain",
    ]
    label_block = re.search(r"```json\n(\[.*?\])\n```", text, re.DOTALL)
    assert label_block is not None
    assert json.loads(label_block.group(1)) == labels
    assert "one reviewer" in text
    assert "adjudication" in text
    assert "excluded from rate denominators" in text
    for hidden in ("regime", "route", "timing status", "confidence", "selected thresholds"):
        assert hidden in text
    blinding_block = re.search(
        r"The machine-readable packet-blinding contract is:\n\n```json\n(\{.*?\})\n```",
        text,
        re.DOTALL,
    )
    assert blinding_block is not None
    blinding = json.loads(blinding_block.group(1))
    allowlist = set(blinding["packet_allowlist"])
    hidden = set(blinding["hidden_decision_fields"])
    assert allowlist == {
        "date",
        "extent_pct",
        "pixel_counts",
        "invalid_coverage",
        "quality_flags",
        "source_imagery_references",
    }
    assert hidden == {
        "regime",
        "route",
        "timing_status",
        "confidence",
        "selected_thresholds",
        "policy_id",
        "threshold_fingerprint",
        "model_output",
    }
    assert allowlist.isdisjoint(hidden)

    def validate_packet_fields(fields: set[str]) -> None:
        unexpected = fields - allowlist
        assert not unexpected, f"prohibited packet fields: {sorted(unexpected)}"

    validate_packet_fields(allowlist)
    for prohibited in hidden:
        with pytest.raises(AssertionError, match="prohibited packet fields"):
            validate_packet_fields(allowlist | {prohibited})
