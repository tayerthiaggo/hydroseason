from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from hydroseason._synthetic import (
    _TROUGH_REFINEMENT_FAMILIES,
    TROUGH_REFINEMENT_CALIBRATION_SEEDS,
    TROUGH_REFINEMENT_VALIDATION_SEEDS,
    generate_trough_refinement_record,
)
from hydroseason._trough_refinement_calibration import (
    build_trough_refinement_cache,
    distance_to_truth_interval,
    iter_trough_refinement_policies,
    score_trough_refinement_policy,
    select_trough_refinement_policy,
    trough_refinement_fingerprint,
)
from scripts import run_calibration as calibration_cli


def test_trough_refinement_partitions_are_disjoint_and_enforced():
    assert set(TROUGH_REFINEMENT_CALIBRATION_SEEDS).isdisjoint(
        TROUGH_REFINEMENT_VALIDATION_SEEDS
    )
    with pytest.raises(ValueError, match="outside the calibration partition"):
        generate_trough_refinement_record(
            TROUGH_REFINEMENT_VALIDATION_SEEDS.start,
            partition="calibration",
        )


def test_trough_refinement_generator_is_deterministic_and_covers_frozen_families():
    seeds = range(
        TROUGH_REFINEMENT_CALIBRATION_SEEDS.start,
        TROUGH_REFINEMENT_CALIBRATION_SEEDS.start
        + len(_TROUGH_REFINEMENT_FAMILIES),
    )
    records = [
        generate_trough_refinement_record(seed, partition="calibration")
        for seed in seeds
    ]
    repeat = generate_trough_refinement_record(seeds.start, partition="calibration")

    assert {record.family for record in records} == set(_TROUGH_REFINEMENT_FAMILIES)
    pd.testing.assert_frame_equal(records[0].frame, repeat.frame)
    assert records[0].truth == repeat.truth
    assert any(record.truth.boundary_start is None for record in records)
    assert any(
        record.truth.boundary_start is not None
        and record.truth.boundary_start != record.truth.boundary_end
        for record in records
    )
    assert any(
        record.truth.boundary_start == record.truth.boundary_end
        for record in records
        if record.truth.boundary_start is not None
    )


def test_policy_grid_is_the_frozen_128_global_tuples():
    policies = list(iter_trough_refinement_policies())
    assert len(policies) == 128
    assert {policy.huber_k for policy in policies} == {1.0, 1.345, 1.5, 2.0}
    assert {policy.profile_loss_cutoff for policy in policies} == {
        0.0,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
    }
    assert {policy.pulse_z for policy in policies} == {1.5, 2.0, 2.5, 3.0}


def test_distance_scores_against_truth_interval_not_forced_point():
    assert distance_to_truth_interval(
        pd.Timestamp("2020-05-01"),
        pd.Timestamp("2020-04-01"),
        pd.Timestamp("2020-06-01"),
    ) == 0
    assert distance_to_truth_interval(
        pd.Timestamp("2020-08-01"),
        pd.Timestamp("2020-04-01"),
        pd.Timestamp("2020-06-01"),
    ) == 2


def _literal_cache(*, false_points: int = 0, structural: int = 0) -> pd.DataFrame:
    policies = list(iter_trough_refinement_policies())[:2]
    rows = []
    for policy_index, _policy in enumerate(policies):
        for seed in range(160):
            truth_resolvable = seed < 80
            truth_start = pd.Timestamp("2020-06-01") if truth_resolvable else pd.NaT
            truth_end = pd.Timestamp("2020-07-01") if truth_resolvable else pd.NaT
            predicted = pd.Timestamp("2020-07-01") if truth_resolvable else pd.NaT
            timing = "point" if truth_resolvable else "unresolved"
            if not truth_resolvable and seed - 80 < false_points:
                predicted = pd.Timestamp("2020-07-01")
                timing = "point"
            rows.append(
                {
                    "seed": seed,
                    "family": "literal",
                    "policy_index": policy_index,
                    "truth_resolvable": truth_resolvable,
                    "truth_start": truth_start,
                    "truth_end": truth_end,
                    "pass1_boundary": pd.Timestamp("2020-05-01"),
                    "predicted_boundary": predicted,
                    "predicted_start": predicted,
                    "predicted_end": predicted,
                    "predicted_timing_status": timing,
                    "refinement_status": (
                        "confirmed" if pd.notna(predicted) else "unresolved"
                    ),
                    "peak_changed": False,
                    "duplicate_or_nonmonotonic": (
                        policy_index == 1 and seed < structural
                    ),
                    "wrong_cycle": False,
                    "new_uncomputable": False,
                    "applied": pd.notna(predicted),
                }
            )
    return pd.DataFrame(rows)


def test_score_reports_false_precision_wilson_and_abstention_separately():
    policy = list(iter_trough_refinement_policies())[0]
    score = score_trough_refinement_policy(_literal_cache(), policy)

    assert score.false_precise_boundary_rate == 0.0
    assert score.false_precise_boundary_wilson[1] < 0.10
    assert score.boundary_set_inclusion == 1.0
    assert score.median_distance_months == 0.0
    assert score.p90_distance_months == 0.0
    assert score.coverage == 1.0
    assert score.abstention_rate == 0.0


def test_selector_rejects_structural_candidate_even_when_accuracy_ties():
    cache = _literal_cache(structural=1)
    selected, score = select_trough_refinement_policy(cache)

    assert selected == list(iter_trough_refinement_policies())[0]
    assert score.duplicate_or_nonmonotonic == 0


def test_selector_refuses_when_every_candidate_fails_false_precision_gate():
    cache = _literal_cache(false_points=4)
    with pytest.raises(RuntimeError, match="no trough-refinement candidate"):
        select_trough_refinement_policy(cache)


def test_real_small_cache_and_fingerprint_are_deterministic():
    seeds = range(
        TROUGH_REFINEMENT_CALIBRATION_SEEDS.start,
        TROUGH_REFINEMENT_CALIBRATION_SEEDS.start + 2,
    )
    policies = list(iter_trough_refinement_policies())[:2]
    first = build_trough_refinement_cache(
        seeds, partition="calibration", policies=policies
    )
    second = build_trough_refinement_cache(
        seeds, partition="calibration", policies=policies
    )
    pd.testing.assert_frame_equal(first, second)

    policy = list(iter_trough_refinement_policies())[0]
    assert trough_refinement_fingerprint(policy) == trough_refinement_fingerprint(
        replace(policy)
    )


def test_calibration_runner_writes_separate_candidate_defaults(
    tmp_path, monkeypatch
):
    cache = _literal_cache()
    monkeypatch.setattr(
        calibration_cli,
        "build_trough_refinement_cache",
        lambda *args, **kwargs: cache,
    )
    report = tmp_path / "calibration.json"
    module = tmp_path / "_trough_refinement_defaults.py"

    calibration_cli.run_trough_refinement_calibration(
        seeds=[TROUGH_REFINEMENT_CALIBRATION_SEEDS.start],
        out_report=report,
        out_module=module,
        workers=1,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["partition"] == "calibration"
    assert payload["authority_scope"] == "trough_refinement_candidate_0_1"
    assert len(payload["fingerprint"]) == 64
    text = module.read_text(encoding="utf-8")
    assert "TROUGH_REFINEMENT_POLICY" in text
    assert payload["fingerprint"] in text


def test_validation_refuses_stale_fingerprint_before_building_corpus(monkeypatch):
    policy = list(iter_trough_refinement_policies())[0]
    monkeypatch.setattr(
        calibration_cli,
        "build_trough_refinement_cache",
        lambda *args, **kwargs: pytest.fail("validation corpus must remain untouched"),
    )

    with pytest.raises(RuntimeError, match="differs from calibration"):
        calibration_cli.run_trough_refinement_validation(
            seeds=[TROUGH_REFINEMENT_VALIDATION_SEEDS.start],
            out_report="unused.json",
            frozen_policy=policy,
            frozen_fingerprint="0" * 64,
            workers=1,
        )


def test_validation_scores_frozen_policy_without_reselection(tmp_path, monkeypatch):
    policy = list(iter_trough_refinement_policies())[0]
    fingerprint = trough_refinement_fingerprint(policy)
    monkeypatch.setattr(
        calibration_cli,
        "build_trough_refinement_cache",
        lambda *args, **kwargs: _literal_cache(),
    )
    monkeypatch.setattr(
        calibration_cli,
        "select_trough_refinement_policy",
        lambda *args, **kwargs: pytest.fail("validation must not run selector"),
    )
    report = tmp_path / "validation.json"

    calibration_cli.run_trough_refinement_validation(
        seeds=[TROUGH_REFINEMENT_VALIDATION_SEEDS.start],
        out_report=report,
        frozen_policy=policy,
        frozen_fingerprint=fingerprint,
        workers=1,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["partition"] == "validation"
    assert payload["selection_counts"] == {"reselection": 0}
    assert payload["fingerprint"] == fingerprint


def test_parser_makes_trough_refinement_an_explicit_mode():
    parsed = calibration_cli._build_parser().parse_args(
        ["--trough-refinement", "--partition", "validation"]
    )
    assert parsed.trough_refinement
    assert parsed.partition == "validation"
    assert parsed.num_trough_refinement_seeds == 5000
