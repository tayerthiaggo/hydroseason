import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.build_recurrence_identifiability_cohort import (
    anonymous_id,
    assert_source_eligible,
    validate_protocol,
    write_identity_mapping,
)
from scripts.evaluate_recurrence_identifiability_cohort import (
    bootstrap_catchment_ids,
    classify_comparison,
    evaluate_cohort,
    freeze_labels_hash,
    summarize_comparisons,
)

PROTOCOL_PATH = Path("case_studies/recurrence-identifiability/cohort-protocol.json")


@pytest.fixture
def protocol():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def test_packet_allowlist_is_disjoint_from_hidden_fields(protocol):
    validated = validate_protocol(protocol)
    assert set(validated["packet_allowlist"]).isdisjoint(validated["hidden_fields"])


def test_builder_rejects_any_excluded_source_token(tmp_path, protocol):
    source = tmp_path / "stress-test-full" / "fresh-copy"
    source.mkdir(parents=True)
    with pytest.raises(ValueError, match="excluded source"):
        assert_source_eligible(source, protocol["excluded_sources"])


def test_builder_hashes_identity_mapping_without_putting_it_in_packets(tmp_path):
    anonymous = anonymous_id(20260903, "station-a")
    mapping = {anonymous: "station-a"}
    mapping_path, hash_path = write_identity_mapping(tmp_path, mapping)
    packet = {"anonymous_catchment_id": anonymous, "anonymous_cycle_id": "cycle-1"}
    assert "station-a" not in json.dumps(packet, sort_keys=True)
    expected = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    assert hash_path.read_text(encoding="ascii").strip() == expected


def test_labels_hash_cannot_change_after_first_evaluation(tmp_path):
    labels = tmp_path / "labels.csv"
    sidecar = tmp_path / "labels.sha256"
    labels.write_text("anonymous_cycle_id,label\ncycle-1,unresolved\n", encoding="utf-8")
    frozen = freeze_labels_hash(labels, sidecar)
    assert frozen == hashlib.sha256(labels.read_bytes()).hexdigest()
    labels.write_text("anonymous_cycle_id,label\ncycle-1,point_supported\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frozen label hash"):
        freeze_labels_hash(labels, sidecar)


def test_unresolved_label_plus_predicted_point_is_direct_contradiction():
    row = classify_comparison("unresolved", "point", exact_endpoints=False)
    assert row["direct_contradiction"] is True
    assert row["false_point"] is True
    assert row["false_resolution"] is True


def test_unresolved_label_plus_predicted_interval_is_false_resolution_not_direct():
    row = classify_comparison("unresolved", "interval", exact_endpoints=False)
    assert row["direct_contradiction"] is False
    assert row["false_point"] is False
    assert row["false_resolution"] is True


def test_interval_label_plus_predicted_point_counts_as_false_point():
    row = classify_comparison("interval_supported", "point", exact_endpoints=False)
    assert row["direct_contradiction"] is False
    assert row["false_point"] is True
    assert row["false_resolution"] is False


def test_bootstrap_resamples_catchments_not_cycles():
    class RecordingRng:
        def choice(self, values, *, size, replace):
            assert list(values) == ["catchment-a", "catchment-b"]
            assert size == 2
            assert replace is True
            return np.array(["catchment-b", "catchment-b"])

    rows = pd.DataFrame(
        {
            "anonymous_catchment_id": ["catchment-a"] + ["catchment-b"] * 5,
            "anonymous_cycle_id": ["a-1"] + [f"b-{index}" for index in range(5)],
        }
    )
    sampled = bootstrap_catchment_ids(rows, rng=RecordingRng())
    assert sampled == ["catchment-b", "catchment-b"]


def test_uncertain_labels_are_reported_but_excluded_from_rates():
    rows = pd.DataFrame(
        [
            {
                "reviewer_label": "uncertain",
                "false_point": True,
                "false_resolution": True,
                "status_match": False,
                "exact_endpoints": False,
                "direct_contradiction": False,
            },
            {
                "reviewer_label": "unresolved",
                "false_point": False,
                "false_resolution": False,
                "status_match": True,
                "exact_endpoints": False,
                "direct_contradiction": False,
            },
        ]
    )
    summary = summarize_comparisons(rows)
    assert summary["reviewed_n"] == 2
    assert summary["uncertain_n"] == 1
    assert summary["rate_denominator_n"] == 1
    assert summary["false_point_k"] == 0
    assert summary["false_resolution_k"] == 0
    assert summary["status_match_k"] == 1
    assert summary["status_match_rate"] == 1.0


def test_evaluate_cohort_produces_complete_report_with_bootstrap_intervals(tmp_path):
    labels_csv = tmp_path / "labels.csv"
    labels_csv.write_text(
        "anonymous_catchment_id,anonymous_cycle_id,label,predicted_status\n"
        "c1,cy1,point_supported,point\n"
        "c1,cy2,interval_supported,interval\n"
        "c2,cy3,unresolved,unresolved\n"
        "c2,cy4,uncertain,point\n",
        encoding="utf-8",
    )
    sidecar = tmp_path / "labels.sha256"
    out_json = tmp_path / "cohort-evaluation.json"

    report = evaluate_cohort(
        labels_path=labels_csv,
        sidecar_path=sidecar,
        output_path=out_json,
    )

    assert out_json.exists()
    assert report["metrics"]["reviewed_n"] == 4
    assert report["metrics"]["uncertain_n"] == 1
    assert report["metrics"]["rate_denominator_n"] == 3
    assert "false_point_rate" in report["bootstrap_intervals"]
    assert "false_resolution_rate" in report["bootstrap_intervals"]
    assert "status_match_rate" in report["bootstrap_intervals"]
    assert "exact_endpoints_rate" in report["bootstrap_intervals"]