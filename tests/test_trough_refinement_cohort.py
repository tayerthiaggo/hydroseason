"""Blinded trough-refinement cohort: builder and evaluator gates.

These tests pin the gates that make the cohort evidence rather than
decoration: that the reviewer never sees an algorithm's answer, that the
sample cannot be chosen or grown after seeing results, that labels are frozen
before unblinding, and that an under-powered cohort reports *unevaluable*
rather than *passed*.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.build_trough_refinement_cohort import (
    anonymous_id,
    assert_source_eligible,
    build_review_packet,
    select_double_review_ids,
    validate_protocol,
    write_identity_mapping,
)
from scripts.evaluate_trough_refinement_cohort import (
    MIN_POINT_PREDICTIONS,
    adjudicate_labels,
    bootstrap_catchment_ids,
    classify_span,
    evaluate_cohort,
    freeze_labels_hash,
    interval_distance_months,
    summarize_spans,
    wilson_interval,
)

PROTOCOL_PATH = Path("case_studies/trough-refinement/cohort-protocol.json")


@pytest.fixture
def protocol():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


# --- builder -------------------------------------------------------------


def test_packet_allowlist_is_disjoint_from_hidden_fields(protocol):
    validated = validate_protocol(protocol)
    assert set(validated["packet_allowlist"]).isdisjoint(validated["hidden_fields"])


def test_protocol_hides_both_passes_boundaries(protocol):
    """A reviewer who can see either algorithm's answer is not blind."""
    hidden = set(validate_protocol(protocol)["hidden_fields"])
    for field in ("pass1_boundary", "pass2_boundary", "refinement_status"):
        assert field in hidden


def test_builder_rejects_any_excluded_source_token(tmp_path, protocol):
    source = tmp_path / "stress-test-full" / "fresh-copy"
    source.mkdir(parents=True)
    with pytest.raises(ValueError, match="excluded source"):
        assert_source_eligible(source, protocol["excluded_sources"])


def test_builder_rejects_protected_development_catchments(tmp_path, protocol):
    source = tmp_path / "gilbert-river-at-somewhere"
    source.mkdir(parents=True)
    with pytest.raises(ValueError, match="excluded source"):
        assert_source_eligible(source, protocol["excluded_sources"])


def test_builder_rejects_the_repeatedly_inspected_stress_bundle(tmp_path, protocol):
    """The real development bundle is named stress_test_final, not -full.

    It underpins the radius audit, the geometry work, and the recurrence
    investigation. Sampling it would make the cohort in-sample and worthless,
    and a hyphen/underscore mismatch is exactly how that slips through.
    """
    source = tmp_path / "hydroseason_tests" / "outputs" / "stress_test_final"
    source.mkdir(parents=True)
    with pytest.raises(ValueError, match="excluded source"):
        assert_source_eligible(source, protocol["excluded_sources"])


def test_review_packet_carries_observations_only(protocol):
    validated = validate_protocol(protocol)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2000-01-01", periods=3, freq="MS"),
            "extent_pct": [10.0, 2.0, 8.0],
            "invalid_pct": [0.0, 0.0, 0.0],
            "quality_state": ["usable"] * 3,
            "pass1_boundary": ["2000-02-01"] * 3,
            "pass2_boundary": ["2000-02-01"] * 3,
            "refinement_status": ["applied"] * 3,
            "station_id": ["130001a"] * 3,
        }
    )
    packet = build_review_packet(
        frame,
        anonymous_catchment_id="c-abc",
        anonymous_span_id="s-1",
        span_start=pd.Timestamp("2000-01-01"),
        span_end=pd.Timestamp("2000-03-01"),
        allowlist=validated["packet_allowlist"],
    )
    for leaked in (
        "pass1_boundary", "pass2_boundary", "refinement_status", "station_id",
    ):
        assert leaked not in packet.columns
    assert set(packet.columns) <= set(validated["packet_allowlist"])
    assert "130001a" not in json.dumps(packet.astype(str).to_dict())


def test_builder_hashes_identity_mapping_without_putting_it_in_packets(tmp_path):
    anonymous = anonymous_id(20260906, "station-a")
    mapping = {anonymous: "station-a"}
    mapping_path, hash_path = write_identity_mapping(tmp_path, mapping)
    packet = {"anonymous_catchment_id": anonymous, "anonymous_span_id": "s-1"}
    assert "station-a" not in json.dumps(packet, sort_keys=True)
    expected = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    assert hash_path.read_text(encoding="ascii").strip() == expected


def test_double_review_subset_is_deterministic_and_meets_both_minimums():
    span_ids = [f"s-{i}" for i in range(200)]
    first = select_double_review_ids(span_ids, seed=20260906, min_fraction=0.2, min_spans=30)
    second = select_double_review_ids(span_ids, seed=20260906, min_fraction=0.2, min_spans=30)
    assert first == second
    assert len(first) == 40  # 20% of 200 exceeds the floor of 30
    assert set(first) <= set(span_ids)


def test_double_review_floor_applies_to_small_cohorts():
    span_ids = [f"s-{i}" for i in range(50)]
    chosen = select_double_review_ids(span_ids, seed=20260906, min_fraction=0.2, min_spans=30)
    assert len(chosen) == 30  # 20% would be 10; the 30-span floor wins


# --- distance rule -------------------------------------------------------


def test_prediction_inside_reviewer_interval_scores_zero_distance():
    assert interval_distance_months(
        predicted=pd.Timestamp("2000-03-01"),
        interval_start=pd.Timestamp("2000-02-01"),
        interval_end=pd.Timestamp("2000-04-01"),
    ) == 0


def test_prediction_outside_interval_scores_distance_to_nearest_edge():
    assert interval_distance_months(
        predicted=pd.Timestamp("2000-06-01"),
        interval_start=pd.Timestamp("2000-02-01"),
        interval_end=pd.Timestamp("2000-04-01"),
    ) == 2
    assert interval_distance_months(
        predicted=pd.Timestamp("1999-12-01"),
        interval_start=pd.Timestamp("2000-02-01"),
        interval_end=pd.Timestamp("2000-04-01"),
    ) == 2


# --- classification ------------------------------------------------------


def test_point_prediction_on_unsupported_boundary_is_a_direct_contradiction():
    row = classify_span("no_boundary_supported", "point")
    assert row["direct_contradiction"] is True
    assert row["false_precise"] is True


def test_point_prediction_on_interval_truth_is_false_precise_not_contradiction():
    row = classify_span("interval_supported", "point")
    assert row["direct_contradiction"] is False
    assert row["false_precise"] is True


def test_interval_prediction_on_interval_truth_is_neither():
    row = classify_span("interval_supported", "interval")
    assert row["direct_contradiction"] is False
    assert row["false_precise"] is False


def test_abstention_is_never_false_precise():
    row = classify_span("no_boundary_supported", "unresolved")
    assert row["false_precise"] is False
    assert row["abstained"] is True


# --- summary and denominators -------------------------------------------


def test_uncertain_labels_are_reported_but_excluded_from_rate_denominators():
    rows = pd.DataFrame(
        [
            {"reviewer_label": "uncertain", "predicted_status": "point",
             "false_precise": True, "direct_contradiction": False,
             "abstained": False, "distance_months": 3.0},
            {"reviewer_label": "point_supported", "predicted_status": "point",
             "false_precise": False, "direct_contradiction": False,
             "abstained": False, "distance_months": 0.0},
        ]
    )
    summary = summarize_spans(rows)
    assert summary["reviewed_n"] == 2
    assert summary["uncertain_n"] == 1
    assert summary["rate_denominator_n"] == 1
    assert summary["false_precise_k"] == 0


def test_abstention_reported_separately_from_resolved_accuracy():
    """A method cannot hide abstention behind accuracy on what it did answer."""
    rows = pd.DataFrame(
        [
            {"reviewer_label": "point_supported", "predicted_status": "unresolved",
             "false_precise": False, "direct_contradiction": False,
             "abstained": True, "distance_months": np.nan},
            {"reviewer_label": "point_supported", "predicted_status": "point",
             "false_precise": False, "direct_contradiction": False,
             "abstained": False, "distance_months": 0.0},
        ]
    )
    summary = summarize_spans(rows)
    assert summary["abstained_n"] == 1
    assert summary["abstention_rate"] == pytest.approx(0.5)
    assert summary["resolved_n"] == 1
    assert summary["median_distance_months"] == 0.0


# --- statistics ----------------------------------------------------------


def test_wilson_upper_bound_on_zero_errors_needs_the_frozen_denominator():
    """73 point predictions is what makes a zero-error gate evaluable at 0.05."""
    _, high = wilson_interval(0, MIN_POINT_PREDICTIONS)
    assert high <= 0.05
    _, high_short = wilson_interval(0, MIN_POINT_PREDICTIONS - 20)
    assert high_short > 0.05


def test_bootstrap_resamples_catchments_not_spans():
    class RecordingRng:
        def choice(self, values, *, size, replace):
            assert list(values) == ["catchment-a", "catchment-b"]
            assert size == 2
            assert replace is True
            return np.array(["catchment-b", "catchment-b"])

    rows = pd.DataFrame(
        {
            "anonymous_catchment_id": ["catchment-a"] + ["catchment-b"] * 5,
            "anonymous_span_id": ["a-1"] + [f"b-{i}" for i in range(5)],
        }
    )
    assert bootstrap_catchment_ids(rows, rng=RecordingRng()) == [
        "catchment-b", "catchment-b",
    ]


# --- adjudication and freezing ------------------------------------------


def test_adjudication_must_be_complete_before_evaluation():
    labels = pd.DataFrame(
        [
            {"anonymous_span_id": "s-1", "label": "point_supported",
             "second_label": "interval_supported", "adjudicated_label": ""},
        ]
    )
    with pytest.raises(RuntimeError, match="unadjudicated"):
        adjudicate_labels(labels)


def test_adjudicated_label_wins_over_both_reviewers():
    labels = pd.DataFrame(
        [
            {"anonymous_span_id": "s-1", "label": "point_supported",
             "second_label": "interval_supported",
             "adjudicated_label": "interval_supported"},
            {"anonymous_span_id": "s-2", "label": "point_supported",
             "second_label": "", "adjudicated_label": ""},
        ]
    )
    resolved = adjudicate_labels(labels)
    assert resolved.loc[resolved["anonymous_span_id"] == "s-1", "final_label"].iloc[0] == (
        "interval_supported"
    )
    assert resolved.loc[resolved["anonymous_span_id"] == "s-2", "final_label"].iloc[0] == (
        "point_supported"
    )


def test_labels_hash_cannot_change_after_first_evaluation(tmp_path):
    labels = tmp_path / "labels.csv"
    sidecar = tmp_path / "labels.sha256"
    labels.write_text("anonymous_span_id,label\ns-1,point_supported\n", encoding="utf-8")
    frozen = freeze_labels_hash(labels, sidecar)
    assert frozen == hashlib.sha256(labels.read_bytes()).hexdigest()
    labels.write_text("anonymous_span_id,label\ns-1,interval_supported\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frozen label hash"):
        freeze_labels_hash(labels, sidecar)


def test_labels_carrying_algorithm_columns_are_rejected(tmp_path):
    labels = tmp_path / "labels.csv"
    labels.write_text(
        "anonymous_span_id,label,pass2_boundary\ns-1,point_supported,2000-02-01\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="algorithm"):
        evaluate_cohort(
            labels_path=labels,
            sidecar_path=tmp_path / "labels.sha256",
            output_path=tmp_path / "out.json",
        )


# --- promotion eligibility ----------------------------------------------


def _labels_csv(tmp_path, n_points: int):
    rows = ["anonymous_catchment_id,anonymous_span_id,label,adjudicated_label,"
            "predicted_status,predicted_boundary,interval_start,interval_end"]
    for index in range(n_points):
        rows.append(
            f"c{index % 9},s-{index},point_supported,,point,"
            f"2000-02-01,2000-02-01,2000-02-01"
        )
    path = tmp_path / "labels.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_underpowered_cohort_reports_unavailable_not_passed(tmp_path):
    labels = _labels_csv(tmp_path, MIN_POINT_PREDICTIONS - 1)
    report = evaluate_cohort(
        labels_path=labels,
        sidecar_path=tmp_path / "labels.sha256",
        output_path=tmp_path / "out.json",
    )
    assert report["promotion_eligibility"] == "unavailable"
    assert report["gates"]["min_point_predictions"] is False
    assert "point predictions" in report["unavailable_reason"]


def test_sufficient_clean_cohort_is_eligible(tmp_path):
    labels = _labels_csv(tmp_path, MIN_POINT_PREDICTIONS)
    report = evaluate_cohort(
        labels_path=labels,
        sidecar_path=tmp_path / "labels.sha256",
        output_path=tmp_path / "out.json",
    )
    assert report["gates"]["min_point_predictions"] is True
    assert report["gates"]["false_precise_wilson_upper_at_most_0_05"] is True
    assert report["gates"]["zero_direct_contradictions"] is True
    assert report["promotion_eligibility"] == "eligible"


def test_one_direct_contradiction_blocks_promotion_regardless_of_rates(tmp_path):
    labels = _labels_csv(tmp_path, MIN_POINT_PREDICTIONS)
    text = labels.read_text(encoding="utf-8").rstrip().split("\n")
    text.append("c9,s-contra,no_boundary_supported,,point,2000-02-01,,")
    labels.write_text("\n".join(text) + "\n", encoding="utf-8")
    report = evaluate_cohort(
        labels_path=labels,
        sidecar_path=tmp_path / "labels.sha256",
        output_path=tmp_path / "out.json",
    )
    assert report["metrics"]["direct_contradiction_k"] == 1
    assert report["gates"]["zero_direct_contradictions"] is False
    assert report["promotion_eligibility"] == "unavailable"


def test_report_is_written_with_both_interval_families(tmp_path):
    labels = _labels_csv(tmp_path, MIN_POINT_PREDICTIONS)
    out = tmp_path / "out.json"
    report = evaluate_cohort(
        labels_path=labels,
        sidecar_path=tmp_path / "labels.sha256",
        output_path=out,
    )
    assert out.exists()
    assert "false_precise_rate" in report["bootstrap_intervals"]
    assert "false_precise_wilson" in report["cycle_level_intervals"]
    assert report["cycle_level_intervals"]["note"].startswith("potentially optimistic")
