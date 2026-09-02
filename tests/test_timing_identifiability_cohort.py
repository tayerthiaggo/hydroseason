from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.build_timing_identifiability_cohort import (
    KNOWN_DECISION_COLUMNS,
    PACKET_COLUMNS,
    UnrecognisedColumnError,
    _selection_hash,
    _station_id,
    build_cohort,
    discover_bundles,
    strip_decision_columns,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = REPO_ROOT / "case_studies" / "timing-identifiability" / "cohort-protocol.json"


@pytest.fixture
def protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _decision_output_frame(*, n_months=24, seed=0, station="999999x"):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2005-01-01", periods=n_months, freq="MS")
    return pd.DataFrame({
        "date": dates,
        "extent_pct": np.abs(rng.normal(5.0, 3.0, n_months)),
        "invalid_pct": 0.0,
        "max_invalid_pct": 20.0,
        "baseline_extent_pct": 4.5,
        "usable_month": True,
        "quality_state": "usable",
        "hy_year": 2005,
        "confidence": "medium",
        "phase": "rising",
        "phase_status": "ok",
        "is_hy_peak": False,
        "is_hy_mid_dry": False,
        "is_hy_trough": False,
        "in_wet_event": False,
        "wet_event_id": pd.NA,
        "in_low_spell": False,
        "low_spell_id": pd.NA,
        "regime": "marginal",
        "route": "per_year_detection",
    })


def _write_bundle(root: Path, station_dir: str, *, frame: pd.DataFrame | None = None) -> Path:
    bundle = root / station_dir
    bundle.mkdir(parents=True, exist_ok=True)
    data = frame if frame is not None else _decision_output_frame()
    data.to_csv(bundle / f"{station_dir}_monthly.csv", index=False)
    return bundle


def test_station_id_is_the_lowercase_slug_prefix():
    assert _station_id(Path("130413A-Denison-Creek-at-Braeside")) == "130413a"
    assert _station_id(Path("130413a-denison-creek-at-braeside")) == "130413a"


def test_strip_decision_columns_keeps_only_the_observation_allowlist():
    frame = _decision_output_frame()
    stripped = strip_decision_columns(frame, source="test")
    assert list(stripped.columns) == [c for c in PACKET_COLUMNS if c in frame.columns]
    assert set(stripped.columns) <= set(PACKET_COLUMNS)
    for column in KNOWN_DECISION_COLUMNS:
        assert column not in stripped.columns


def test_strip_decision_columns_raises_on_an_unrecognised_column():
    frame = _decision_output_frame()
    frame["some_new_undocumented_field"] = 1
    with pytest.raises(UnrecognisedColumnError, match="some_new_undocumented_field"):
        strip_decision_columns(frame, source="test")


def test_selection_hash_is_deterministic_sha256_of_seed_and_station():
    expected = hashlib.sha256(b"20260901:130003b").hexdigest()
    assert _selection_hash(20260901, "130003b") == expected


def test_protocol_declares_the_frozen_seed_and_exclusions(protocol):
    assert protocol["seed"] == 20260901
    assert set(protocol["exclude_station_ids"]) == {"130413a", "130407a", "130302a"}


@pytest.fixture
def synthetic_stress_root(tmp_path):
    root = tmp_path / "stress"
    root.mkdir()
    # Three motivating stations to be excluded, case-insensitively.
    _write_bundle(root, "130413A-Denison-Creek-at-Braeside", frame=_decision_output_frame(seed=1))
    _write_bundle(root, "130407a-nebo-creek-at-nebo", frame=_decision_output_frame(seed=2))
    _write_bundle(root, "130302a-dawson-river-at-taroom", frame=_decision_output_frame(seed=3))
    # A handful of eligible candidates.
    for i in range(5):
        _write_bundle(root, f"9990{i}a-synthetic-station-{i}", frame=_decision_output_frame(seed=10 + i))
    return root


def test_discover_bundles_finds_every_directory(synthetic_stress_root):
    bundles = discover_bundles(synthetic_stress_root)
    assert len(bundles) == 8


def test_build_cohort_excludes_motivating_stations_case_insensitively(synthetic_stress_root, protocol, tmp_path):
    summary = build_cohort(
        stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out",
    )
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    assert set(manifest["station_id"]) & {"130413a", "130407a", "130302a"} == set()
    assert summary["excluded_station_ids"] == ["130302a", "130407a", "130413a"]


def test_build_cohort_manifest_has_no_duplicate_station_ids(synthetic_stress_root, protocol, tmp_path):
    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    assert manifest["station_id"].is_unique


def test_build_cohort_quota_is_min_8_or_available_and_shortfall_is_reported(synthetic_stress_root, protocol, tmp_path):
    summary = build_cohort(
        stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out",
    )
    for stratum_name, report in summary["per_stratum"].items():
        assert report["selected"] == min(8, report["available"])
        assert report["shortfall"] == max(0, 8 - report["available"])
    # This tiny synthetic pool cannot possibly reach 8 in every stratum;
    # a shortfall must be reported, not raised.
    assert any(report["shortfall"] > 0 for report in summary["per_stratum"].values())


def test_build_cohort_packets_contain_no_decision_columns(synthetic_stress_root, protocol, tmp_path):
    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    packet_dir = tmp_path / "out" / "packets"
    packet_files = sorted(packet_dir.glob("*_packet.csv"))
    assert packet_files
    for packet_file in packet_files:
        packet = pd.read_csv(packet_file)
        assert set(packet.columns) <= set(PACKET_COLUMNS)
        for column in KNOWN_DECISION_COLUMNS:
            assert column not in packet.columns


def test_build_cohort_manifest_records_pixel_support_status(synthetic_stress_root, protocol, tmp_path):
    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    assert not manifest.empty
    assert (manifest["pixel_support_status"] == "unavailable").all()


def test_build_cohort_selection_is_deterministic_across_runs(synthetic_stress_root, protocol, tmp_path):
    first = build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "run1")
    second = build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "run2")
    manifest_1 = pd.read_csv(tmp_path / "run1" / "cohort-manifest.csv")
    manifest_2 = pd.read_csv(tmp_path / "run2" / "cohort-manifest.csv")
    assert sorted(manifest_1["station_id"]) == sorted(manifest_2["station_id"])
    assert first["threshold_fingerprint"] == second["threshold_fingerprint"]


def test_build_cohort_raises_on_partial_pixel_count_columns(synthetic_stress_root, protocol, tmp_path):
    frame = _decision_output_frame()
    frame["n_water"] = 10
    frame["n_valid"] = 100
    # n_invalid and n_aoi deliberately omitted: a partial count-column set.
    _write_bundle(synthetic_stress_root, "999099a-partial-counts", frame=frame)
    with pytest.raises(ValueError, match="partial pixel-count columns"):
        build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")


def test_label_file_rejects_unknown_labels(tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import load_labels

    labels_path = tmp_path / "labels.csv"
    pd.DataFrame([{"station_id": "999001a", "label": "definitely_a_typo", "reason": "x"}]).to_csv(
        labels_path, index=False
    )
    with pytest.raises(ValueError, match="invalid label"):
        load_labels(labels_path)


def test_label_file_rejects_duplicate_station_ids(tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import load_labels

    labels_path = tmp_path / "labels.csv"
    pd.DataFrame([
        {"station_id": "999001a", "label": "point_supported", "reason": "a"},
        {"station_id": "999001a", "label": "event_only", "reason": "b"},
    ]).to_csv(labels_path, index=False)
    with pytest.raises(ValueError, match="duplicate station_id"):
        load_labels(labels_path)


def test_evaluate_never_writes_scientific_defaults_or_threshold_files(synthetic_stress_root, protocol, tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import evaluate

    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    labels = pd.DataFrame({
        "station_id": manifest["station_id"],
        "label": "point_supported",
        "reason": "synthetic placeholder",
    })
    defaults_path = REPO_ROOT / "hydroseason" / "_scientific_defaults.py"
    before = defaults_path.read_bytes()
    evaluate(manifest=manifest, labels=labels, stress_root=synthetic_stress_root)
    after = defaults_path.read_bytes()
    assert before == after


def test_evaluate_reports_confusion_table_and_disagreements(synthetic_stress_root, protocol, tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import evaluate

    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    labels = pd.DataFrame({
        "station_id": manifest["station_id"],
        "label": "unobservable",  # deliberately wrong for most synthetic records, to force disagreements
        "reason": "synthetic placeholder",
    })
    report = evaluate(manifest=manifest, labels=labels, stress_root=synthetic_stress_root)
    assert "confusion_table" in report
    assert "disagreements" in report
    assert "overall_agreement" in report
    assert 0.0 <= report["overall_agreement"]["wilson_low"] <= report["overall_agreement"]["wilson_high"] <= 1.0
    assert report["n_rated"] + report["n_uncertain_excluded"] + report["n_missing_labels"] <= report["n_cohort_records"]


def test_evaluate_excludes_uncertain_from_rate_denominators(synthetic_stress_root, protocol, tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import evaluate

    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    labels = pd.DataFrame({
        "station_id": manifest["station_id"],
        "label": "uncertain",
        "reason": "synthetic placeholder",
    })
    report = evaluate(manifest=manifest, labels=labels, stress_root=synthetic_stress_root)
    assert report["n_uncertain_excluded"] == len(manifest)
    assert report["n_rated"] == 0
    assert report["overall_agreement"]["n"] == 0


def test_evaluate_reports_missing_labels_without_raising(synthetic_stress_root, protocol, tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import evaluate

    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    partial_labels = pd.DataFrame({
        "station_id": manifest["station_id"].iloc[:1],
        "label": "point_supported",
        "reason": "synthetic placeholder",
    })
    report = evaluate(manifest=manifest, labels=partial_labels, stress_root=synthetic_stress_root)
    assert report["n_missing_labels"] == len(manifest) - 1


def test_freeze_labels_hash_records_then_rejects_a_later_change(tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import (
        LabelFileChangedError,
        freeze_labels_hash,
    )

    labels_path = tmp_path / "review-labels.csv"
    pd.DataFrame([{"station_id": "999001a", "label": "point_supported", "reason": "x"}]).to_csv(
        labels_path, index=False
    )
    first_digest = freeze_labels_hash(labels_path)
    assert freeze_labels_hash(labels_path) == first_digest  # unchanged file re-evaluates cleanly

    labels_path.write_text(labels_path.read_text(encoding="utf-8") + "\n999002a,event_only,y\n", encoding="utf-8")
    with pytest.raises(LabelFileChangedError, match="has changed"):
        freeze_labels_hash(labels_path)


def test_evaluate_restates_known_limitations_in_the_report(synthetic_stress_root, protocol, tmp_path):
    from scripts.evaluate_timing_identifiability_cohort import evaluate

    build_cohort(stress_root=synthetic_stress_root, protocol=protocol, output_dir=tmp_path / "out")
    manifest = pd.read_csv(tmp_path / "out" / "cohort-manifest.csv")
    labels = pd.DataFrame({
        "station_id": manifest["station_id"],
        "label": "uncertain",
        "reason": "",
    })
    report = evaluate(manifest=manifest, labels=labels, stress_root=synthetic_stress_root)

    assert "known_limitations" in report
    limits = report["known_limitations"]
    assert "per_stratum_shortfall" in limits
    assert limits["pixel_support_status"] == ["unavailable"]
    assert "synthetic-only" in limits["min_peak_water_pixels_evidence_basis"]
    for stratum, report_entry in report["per_stratum"].items():
        assert "shortfall" in report_entry
        assert report_entry["shortfall"] == limits["per_stratum_shortfall"][stratum]


def test_real_stress_bundle_builds_without_raising_if_present():
    """Smoke test against the real external bundle, skipped if unavailable."""
    stress_root = Path(r"D:\RLH\5.6\hydroseason_tests\outputs\stress_test_final")
    if not stress_root.exists():
        pytest.skip("external stress-test bundle not available on this machine")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        summary = build_cohort(
            stress_root=stress_root, protocol=protocol, output_dir=Path(tmp) / "out",
        )
    assert summary["n_selected"] > 0
    assert set(summary["excluded_station_ids"]) == {"130413a", "130407a", "130302a"}
