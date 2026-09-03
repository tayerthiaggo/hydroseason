import pandas as pd
import pytest

from hydroseason._recurrence_calibration import (
    RecurrenceEvaluation,
    evaluate_recurrence_records,
    recurrence_fingerprint,
    score_recurrence_policy,
    select_recurrence_policy,
)
from hydroseason._recurrence_identifiability import (
    ELIGIBLE_RECURRENCE_POLICIES,
    narrow_most_recent_recurrence,
)
from hydroseason._recurrence_synthetic import (
    RECURRENCE_CALIBRATION_SEEDS,
    RECURRENCE_FAMILIES,
    RECURRENCE_VALIDATION_SEEDS,
    generate_recurrence_record,
)
from hydroseason._synthetic import (
    CALIBRATION_SEEDS,
    GEOMETRY_CALIBRATION_SEEDS,
    GEOMETRY_VALIDATION_SEEDS,
    VALIDATION_SEEDS,
)
from hydroseason._timing_identifiability import (
    TimingIdentifiabilityThresholds,
    assess_window_timing,
)


def _dates(*values: str) -> tuple[pd.Timestamp, ...]:
    return tuple(pd.Timestamp(value) for value in values)


def _narrow(dates, *, policy, start="1990-01-01", end="1991-06-01", limit=2):
    return narrow_most_recent_recurrence(
        dates,
        window_start=pd.Timestamp(start),
        window_end=pd.Timestamp(end),
        max_boundary_interval_months=limit,
        policy=policy,
    )


def test_eligible_policy_order_is_frozen():
    assert ELIGIBLE_RECURRENCE_POLICIES == (
        "no_narrowing",
        "annual_shape_match",
        "long_window_last_cluster",
    )


def test_no_narrowing_returns_original_tuple_verbatim():
    dates = _dates("1991-04-01", "1990-04-01")
    assert _narrow(dates, policy="no_narrowing") is dates


def test_short_window_never_narrows():
    dates = _dates("1990-01-01", "1990-11-01")
    assert _narrow(dates, policy="long_window_last_cluster", end="1990-12-01") == dates


def test_long_window_legacy_ablation_keeps_last_resolved_cluster():
    dates = _dates("1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="long_window_last_cluster") == _dates("1991-03-01")


def test_annual_shape_match_accepts_one_month_phase_drift():
    dates = _dates("1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="annual_shape_match") == _dates("1991-03-01")


def test_annual_shape_match_rejects_large_cluster_plus_singleton():
    dates = _dates(
        "1992-05-01",
        "1992-06-01",
        "1992-07-01",
        "1992-08-01",
        "1992-09-01",
        "1993-01-01",
        "1993-04-01",
    )
    assert (
        _narrow(
            dates,
            policy="annual_shape_match",
            start="1992-05-01",
            end="1993-10-01",
        )
        == dates
    )


def test_annual_shape_match_is_symmetric_for_interval_shapes():
    # An interval in the earlier year and a point in the later one is not the
    # same annual shape: the later year's remaining equivalent months may just
    # be missing.  Symmetric nearest-date distance alone accepts this pair
    # (every distance is <= 1); the equal-span requirement is what rejects it.
    dates = _dates("1990-03-01", "1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="annual_shape_match") == dates


def test_annual_shape_match_declines_the_annual_aligned_fragment_trap():
    # Corpus family ``annual_aligned_fragment_trap`` (offsets 1, 2, 3, 13),
    # truth unresolved.  Candidate C must decline it while the legacy ablation
    # narrows it; that separation is the family's entire purpose.
    dates = _dates("1990-02-01", "1990-03-01", "1990-04-01", "1991-02-01")
    assert _narrow(dates, policy="annual_shape_match") == dates
    assert _narrow(dates, policy="long_window_last_cluster") == _dates("1991-02-01")


@pytest.mark.parametrize("dates", [(), _dates("1990-04-01")])
def test_empty_and_singleton_sets_are_unchanged(dates):
    assert _narrow(dates, policy="annual_shape_match") == dates


def test_one_cluster_is_unchanged():
    dates = _dates("1990-03-01", "1990-04-01", "1990-05-01")
    assert _narrow(dates, policy="annual_shape_match") == dates


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("1990-01-02", "1991-01-01", "month-start"),
        ("1991-01-01", "1990-01-01", "not precede"),
    ],
)
def test_invalid_caller_bounds_are_rejected(start, end, message):
    with pytest.raises(ValueError, match=message):
        _narrow(
            _dates("1990-04-01", "1991-04-01"),
            policy="annual_shape_match",
            start=start,
            end=end,
        )


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match="recurrence policy"):
        _narrow(_dates("1990-04-01", "1991-04-01"), policy="legacy_last_cluster")


def test_narrowed_dates_are_always_a_subset_of_input():
    base = pd.date_range("1990-01-01", periods=24, freq="MS")
    for mask in range(1, 1 << 8):
        dates = tuple(base[i] for i in range(8) if mask & (1 << i)) + (base[19],)
        for policy in ELIGIBLE_RECURRENCE_POLICIES:
            result = _narrow(dates, policy=policy, end="1991-12-01")
            assert set(result).issubset(dates)


WINDOW_THRESHOLDS = TimingIdentifiabilityThresholds(1.5, 1, 0, 2, 2)


def _window_result(values, index, *, policy, window_start=None, window_end=None):
    series = pd.Series(values, index=pd.to_datetime(index), dtype=float)
    rows = pd.DataFrame({"n_valid": 100}, index=series.index)
    return assess_window_timing(
        series,
        rows,
        thresholds=WINDOW_THRESHOLDS,
        measurement_tolerance_pct=1.0,
        noise_pp=0.0,
        pixel_support_status="unavailable",
        recurrence_policy=policy,
        window_start=window_start,
        window_end=window_end,
    )


def test_window_assessor_drives_explicit_candidate_policy():
    index = pd.date_range("1990-02-01", periods=18, freq="MS")
    values = [5.0] * 2 + [10.0] + [5.0] * 10 + [10.0] + [5.0] * 3 + [0.0]
    result = _window_result(values, index, policy="annual_shape_match")
    assert result.peak_status == "point"
    assert result.peak_dates == (pd.Timestamp("1991-03-01"),)


# Both bound tests need a window whose peak set is genuinely ``unresolved``,
# because that is the only branch that calls ``narrow_most_recent_recurrence()``
# at all.  ``[10, 5, 10]`` spans 2 months, which is within
# ``max_boundary_interval_months=2``, so it resolves to ``interval`` and the
# narrowing code is never reached; ``[10, 5, 5, 5, 10]`` spans 4 and is.


def test_derived_bounds_normalise_non_month_start_value_index():
    index = ["1990-01-15", "1990-02-15", "1990-03-15", "1990-04-15", "1990-05-15"]
    result = _window_result(
        [10.0, 5.0, 5.0, 5.0, 10.0], index, policy="no_narrowing"
    )
    assert result.detectable is True
    assert result.peak_status == "unresolved"
    assert result.peak_dates == (
        pd.Timestamp("1990-01-15"),
        pd.Timestamp("1990-05-15"),
    )


def test_explicit_non_month_start_bound_is_rejected():
    with pytest.raises(ValueError, match="month-start"):
        _window_result(
            [10.0, 5.0, 5.0, 5.0, 10.0],
            pd.date_range("1990-01-01", periods=5, freq="MS"),
            policy="no_narrowing",
            window_start=pd.Timestamp("1990-01-02"),
            window_end=pd.Timestamp("1990-05-01"),
        )


def test_recurrence_seed_partitions_are_disjoint_from_every_existing_corpus():
    groups = [
        set(CALIBRATION_SEEDS), set(VALIDATION_SEEDS),
        set(GEOMETRY_CALIBRATION_SEEDS), set(GEOMETRY_VALIDATION_SEEDS),
        set(RECURRENCE_CALIBRATION_SEEDS), set(RECURRENCE_VALIDATION_SEEDS),
    ]
    assert all(left.isdisjoint(right) for i, left in enumerate(groups) for right in groups[i + 1 :])


def test_first_960_seeds_balance_eight_families_exactly():
    records = [generate_recurrence_record(seed, partition="calibration") for seed in range(50000, 50960)]
    counts = pd.Series([record.family for record in records]).value_counts().to_dict()
    assert set(counts) == set(RECURRENCE_FAMILIES)
    assert set(counts.values()) == {120}


def test_recurrence_truth_is_generator_owned_and_reachable():
    for offset, family in enumerate(RECURRENCE_FAMILIES):
        record = generate_recurrence_record(50000 + offset, partition="calibration")
        assert record.family == family
        assert record.window_start <= record.values.index.min()
        assert record.values.index.max() <= record.window_end
        if family.startswith("annual_") and family != "annual_aligned_fragment_trap":
            assert record.truth.status in {"point", "interval"}
            assert record.truth.latest_dates
        else:
            assert record.truth.status == "unresolved"
            assert record.truth.latest_dates == ()


def test_corpus_is_deterministic_and_partitions_differ():
    first = generate_recurrence_record(50007, partition="calibration")
    again = generate_recurrence_record(50007, partition="calibration")
    validation = generate_recurrence_record(60007, partition="validation")
    pd.testing.assert_series_equal(first.values, again.values)
    pd.testing.assert_frame_equal(first.rows, again.rows)
    assert first.truth == again.truth
    assert not first.values.equals(validation.values) or first.window_end != validation.window_end


def _assess_record(record, policy):
    result = assess_window_timing(
        record.values,
        record.rows,
        thresholds=record.thresholds,
        measurement_tolerance_pct=record.measurement_tolerance_pct,
        noise_pp=record.noise_pp,
        pixel_support_status=record.pixel_support_status,
        recurrence_policy=policy,
        window_start=record.window_start,
        window_end=record.window_end,
    )
    return (
        (result.peak_status, result.peak_dates)
        if record.truth.kind == "peak"
        else (result.trough_status, result.trough_dates)
    )


def test_legacy_ablation_fails_fragmented_negative_control():
    record = generate_recurrence_record(50003, partition="calibration")
    status, _dates = _assess_record(record, "long_window_last_cluster")
    assert record.family == "ordinary_gap_fragmented_plateau"
    assert status == "unresolved"  # short-window gate must defeat legacy narrowing


def test_annual_shape_candidate_recovers_positive_families():
    for offset in range(3):
        record = generate_recurrence_record(50000 + offset, partition="calibration")
        status, dates = _assess_record(record, "annual_shape_match")
        assert status == record.truth.status
        assert dates == record.truth.latest_dates


def _evaluation(policy, truth, predicted, exact=False, family="fixture"):
    return RecurrenceEvaluation(
        policy=policy,
        family=family,
        kind="trough",
        pixel_support_status="unavailable",
        truth_status=truth,
        predicted_status=predicted,
        exact_latest_dates=exact,
    )


def test_false_point_and_false_resolution_denominators_are_distinct():
    rows = [
        _evaluation("annual_shape_match", "interval", "point"),
        _evaluation("annual_shape_match", "unresolved", "interval"),
        _evaluation("annual_shape_match", "point", "point", exact=True),
    ]
    score = score_recurrence_policy(rows, "annual_shape_match")
    assert (score.false_point_k, score.false_point_n) == (1, 2)
    assert (score.false_resolution_k, score.false_resolution_n) == (1, 1)
    # Denominator is every genuine-recurrence row, not just the ones the policy
    # got right: the interval row predicted as a point counts against it.
    assert score.exact_latest_date_accuracy == 0.5


def test_selector_rejects_unsafe_accuracy_winner():
    safe = [_evaluation("no_narrowing", "unresolved", "unresolved") for _ in range(120)]
    unsafe = [_evaluation("annual_shape_match", "unresolved", "point") for _ in range(120)]
    policy, score, counts = select_recurrence_policy(safe + unsafe)
    assert policy == "no_narrowing"
    assert score.false_point_k == 0
    assert counts["false_point_wilson"] == 1


def test_selector_prefers_exact_recovery_after_safety_gates():
    rows = []
    for policy, exact in (("no_narrowing", False), ("annual_shape_match", True)):
        rows.extend(_evaluation(policy, "unresolved", "unresolved") for _ in range(120))
        rows.extend(
            _evaluation(policy, "point", "point" if exact else "unresolved", exact=exact)
            for _ in range(120)
        )
    policy, _score, counts = select_recurrence_policy(rows)
    assert policy == "annual_shape_match"
    assert counts["exact_latest_date_accuracy"] == 1


def test_fingerprint_changes_with_metrics_seed_or_policy():
    metrics = {"false_point_k": 0, "false_point_n": 120}
    base = recurrence_fingerprint(
        "annual_shape_match", seeds=list(range(50000, 50960)), metrics=metrics
    )
    assert base != recurrence_fingerprint(
        "no_narrowing", seeds=list(range(50000, 50960)), metrics=metrics
    )
    assert base != recurrence_fingerprint(
        "annual_shape_match", seeds=list(range(50000, 50959)), metrics=metrics
    )
    assert base != recurrence_fingerprint(
        "annual_shape_match",
        seeds=list(range(50000, 50960)),
        metrics={"false_point_k": 1, "false_point_n": 120},
    )


def test_selector_raises_when_no_policy_satisfies_safety_gates():
    unsafe = [
        _evaluation(policy, "unresolved", "point")
        for policy in ELIGIBLE_RECURRENCE_POLICIES
        for _ in range(120)
    ]
    with pytest.raises(
        RuntimeError,
        match="no recurrence policy satisfies both false-precision safety gates",
    ):
        select_recurrence_policy(unsafe)


def test_evaluate_recurrence_records_runs_production_assessor():
    records = [generate_recurrence_record(50000 + i, partition="calibration") for i in range(8)]
    evals = evaluate_recurrence_records(records, policies=ELIGIBLE_RECURRENCE_POLICIES)
    assert len(evals) == 8 * len(ELIGIBLE_RECURRENCE_POLICIES)
    pos_eval = next(
        e
        for e in evals
        if e.policy == "annual_shape_match" and e.family == "annual_point_recurrence"
    )
    assert pos_eval.truth_status == "point"
    assert pos_eval.predicted_status == "point"
    assert pos_eval.exact_latest_dates is True
