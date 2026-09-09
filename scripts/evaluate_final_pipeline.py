"""Measured detector-off/detector-on comparison on complete synthetic records.

This is a *pipeline* comparison, distinct from
``hydroseason._trough_refinement_calibration``'s per-span component harness:
it runs the real ``detect_dynamic_hydrological_years`` detector twice --
refinement off, then the candidate policy on -- across a complete 12-year
record, using no supplied truth peaks (the detector must find its own peaks,
same as production). See
``docs/superpowers/plans/2026-09-08-final-scientific-hardening.md`` Task 3.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason import (  # noqa: E402
    _boundary,
    _calibration,
    _circular_timing,
    _dynamic_year,
    _harmonic,
    _phase_scheme,
    _recurrence_identifiability,
    _scientific_defaults,
    _seasonality,
    _state_input,
    _synthetic,
    _timing_identifiability,
)
from hydroseason._calibration import _GEOMETRY_MAX_MATCH_MONTHS  # noqa: E402
from hydroseason._dynamic_year import (  # noqa: E402
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
)
from hydroseason._synthetic import generate_trough_geometry_record  # noqa: E402
from hydroseason._trough_refinement import TroughRefinementPolicy  # noqa: E402

# Frozen regression partitions for this pipeline evaluation: ten seeds per
# each of the ten geometry families in each partition (family = seed % 10).
# These are regression subsets of the existing geometry corpus, not a new
# real-world validation claim.
PIPELINE_CALIBRATION_SEEDS = range(30000, 30100)
PIPELINE_VALIDATION_SEEDS = range(40000, 40100)

_STATUS_COLUMNS = ("status", "status_reason", "boundary_status")

# Fields the plan's Task 5 per-cycle diff names explicitly: operational date
# (added separately via boundary_col), raw minimum, support start/end,
# recovery date, peak date/value, quality, status/reason, cycle length,
# usable months, refinement applied/rollback reason, and condition/phase.
# Only columns actually present in both joined tables are ever emitted.
_DIFF_VALUE_COLUMNS = (
    "peak_month", "peak_extent_pct", "peak_quality",
    "raw_trough_month", "raw_trough_extent_pct",
    "trough_interval_start", "trough_interval_end", "trough_timing_status",
    "recovery_start_month",
    "status", "status_reason", "boundary_status",
    "cycle_months", "n_usable_months",
    "trough_refinement_applied", "trough_refinement_reason",
    "annual_condition", "confidence",
)
_UNCOMPUTABLE_REASONS = {"insufficient_cycle_coverage", "no_previous_boundary"}


def _month_delta(left: pd.Timestamp, right: pd.Timestamp) -> int:
    left, right = pd.Timestamp(left), pd.Timestamp(right)
    return (left.year - right.year) * 12 + left.month - right.month


def _nan_eq(left: object, right: object) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    return bool(left == right)


def _boundary_column(frame: pd.DataFrame) -> str | None:
    for name in ("trough_boundary_date", "trough_month"):
        if name in frame.columns:
            return name
    return None


def _is_computable(row: pd.Series, *, boundary_col: str | None) -> bool:
    peak = row.get("peak_month", pd.NaT)
    boundary = row.get(boundary_col, pd.NaT) if boundary_col else pd.NaT
    reason = row.get("status_reason")
    return bool(
        pd.notna(peak) and pd.notna(boundary) and reason not in _UNCOMPUTABLE_REASONS
    )


def _interval_width_months(row: pd.Series) -> float | None:
    start = row.get("trough_interval_start")
    end = row.get("trough_interval_end")
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    return float(_month_delta(end, start))


def _duplicate_or_nonmonotonic_boundaries(frame: pd.DataFrame, *, boundary_col: str) -> int:
    """Count rows with a non-null boundary, in chronological hy_year order,
    whose boundary repeats or does not strictly increase relative to the
    previous one.
    """
    if boundary_col not in frame.columns or "hy_year" not in frame.columns:
        return 0
    ordered = frame.sort_values("hy_year")
    dates = [
        pd.Timestamp(value)
        for value in ordered[boundary_col]
        if pd.notna(value)
    ]
    violations = 0
    for previous, current in zip(dates, dates[1:]):
        if current <= previous:
            violations += 1
    return violations


def _looks_datetime(series: pd.Series) -> bool:
    """True only for columns actually holding dates -- never matched by
    column name alone, so an integer duration column like ``cycle_months``
    (name contains "month") is never miscoerced into nanosecond epoch dates.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if series.dtype != object:
        return False
    sample = series.dropna()
    if sample.empty:
        return False
    return all(isinstance(value, pd.Timestamp) for value in sample)


def compare_cycle_tables(
    before: pd.DataFrame,
    after: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Diff two hydro-year tables on ``hy_year`` with NaN-aware equality.

    Returns the per-year diff frame and a dict of named counters: changed
    peaks (date and/or extent), boundary shift, interval width/status
    changes, newly-uncomputable and newly-computable cycles, added/dropped
    rows, and duplicate/non-monotonic boundary sequences measured
    separately in each table. Quality changes are split into upgrades and
    downgrades rather than folded into a single "failure" count -- an
    honest downgrade in reported certainty is not a computational failure.
    """
    before = before.copy()
    after = after.copy()
    for frame in (before, after):
        for column in frame.columns:
            if _looks_datetime(frame[column]):
                frame[column] = pd.to_datetime(frame[column], errors="coerce")

    boundary_col = _boundary_column(before) or _boundary_column(after)

    merged = before.merge(
        after, on="hy_year", how="outer", suffixes=("_before", "_after"), indicator=True
    )
    merged = merged.sort_values("hy_year").reset_index(drop=True)

    counts = {
        "matched_rows": 0,
        "added_rows": 0,
        "dropped_rows": 0,
        "peak_changes": 0,
        "boundary_shifted": 0,
        "interval_width_changed": 0,
        "interval_widened": 0,
        "interval_narrowed": 0,
        "status_changed": 0,
        "newly_uncomputable": 0,
        "newly_computable": 0,
        "quality_upgraded": 0,
        "quality_downgraded": 0,
    }
    diff_rows: list[dict[str, object]] = []

    for _, merged_row in merged.iterrows():
        hy_year = merged_row["hy_year"]
        presence = merged_row["_merge"]
        if presence == "left_only":
            counts["dropped_rows"] += 1
            diff_rows.append({"hy_year": hy_year, "change": "dropped_row"})
            continue
        if presence == "right_only":
            counts["added_rows"] += 1
            diff_rows.append({"hy_year": hy_year, "change": "added_row"})
            continue

        counts["matched_rows"] += 1
        before_row = before.loc[before["hy_year"] == hy_year].iloc[0]
        after_row = after.loc[after["hy_year"] == hy_year].iloc[0]
        row_changes: list[str] = []

        peak_changed = not (
            _nan_eq(before_row.get("peak_month"), after_row.get("peak_month"))
            and _nan_eq(before_row.get("peak_extent_pct"), after_row.get("peak_extent_pct"))
        )
        if peak_changed:
            counts["peak_changes"] += 1
            row_changes.append("peak_changed")

        if boundary_col:
            before_boundary = before_row.get(boundary_col)
            after_boundary = after_row.get(boundary_col)
            if not _nan_eq(before_boundary, after_boundary):
                counts["boundary_shifted"] += 1
                row_changes.append("boundary_shifted")

        before_width = _interval_width_months(before_row)
        after_width = _interval_width_months(after_row)
        if before_width != after_width:
            counts["interval_width_changed"] += 1
            row_changes.append("interval_width_changed")
            if before_width is not None and after_width is not None:
                if after_width > before_width:
                    counts["interval_widened"] += 1
                elif after_width < before_width:
                    counts["interval_narrowed"] += 1

        status_changed = any(
            not _nan_eq(before_row.get(col), after_row.get(col)) for col in _STATUS_COLUMNS
        )
        if status_changed:
            counts["status_changed"] += 1
            row_changes.append("status_changed")
            before_complete = str(before_row.get("status")) == "complete"
            after_complete = str(after_row.get("status")) == "complete"
            if after_complete and not before_complete:
                counts["quality_upgraded"] += 1
            elif before_complete and not after_complete:
                counts["quality_downgraded"] += 1

        before_computable = _is_computable(before_row, boundary_col=boundary_col)
        after_computable = _is_computable(after_row, boundary_col=boundary_col)
        if before_computable and not after_computable:
            counts["newly_uncomputable"] += 1
            row_changes.append("newly_uncomputable")
        elif after_computable and not before_computable:
            counts["newly_computable"] += 1
            row_changes.append("newly_computable")

        # The checks above only flag a subset of the fields this diff
        # promises to report (peak, boundary, width, status). A change
        # confined to a field outside that subset -- recovery_start_month
        # is the case that motivated this check -- must still surface the
        # row, or the diff silently drops a real change (C2, 2026-09-08
        # review). This does not add or alter any named counter.
        any_value_changed = any(
            not _nan_eq(before_row.get(col), after_row.get(col))
            for col in _DIFF_VALUE_COLUMNS
            if col in before.columns and col in after.columns
        )
        if any_value_changed and "value_changed" not in row_changes:
            row_changes.append("value_changed")

        if row_changes:
            diff_row: dict[str, object] = {"hy_year": hy_year, "change": ",".join(row_changes)}
            for col in _DIFF_VALUE_COLUMNS + ((boundary_col,) if boundary_col else ()):
                if col in before.columns and col in after.columns:
                    diff_row[f"{col}_before"] = before_row.get(col)
                    diff_row[f"{col}_after"] = after_row.get(col)
            diff_rows.append(diff_row)

    if boundary_col:
        counts["before_duplicate_or_nonmonotonic_boundaries"] = (
            _duplicate_or_nonmonotonic_boundaries(before, boundary_col=boundary_col)
        )
        counts["after_duplicate_or_nonmonotonic_boundaries"] = (
            _duplicate_or_nonmonotonic_boundaries(after, boundary_col=boundary_col)
        )
    else:
        counts["before_duplicate_or_nonmonotonic_boundaries"] = 0
        counts["after_duplicate_or_nonmonotonic_boundaries"] = 0

    if diff_rows:
        diff = pd.DataFrame(diff_rows)
        ordered = ["hy_year", "change"] + [
            col for col in diff.columns if col not in {"hy_year", "change"}
        ]
        diff = diff.loc[:, ordered]
    else:
        diff = pd.DataFrame(columns=["hy_year", "change"])
    return diff, counts


def _singleton_errors(
    annual: pd.DataFrame,
    *,
    base_year: int,
    truth,
) -> list[tuple[int, float]]:
    """Signed month errors for every truth-identifiable year with a
    singleton (point) prediction, matched by year. A wrong or absent
    singleton on an identifiable year counts as an error; a correctly
    non-committal (interval/broad/unresolved) row on that year does not.
    """
    by_year = {int(row["hy_year"]): row for _, row in annual.iterrows()}
    errors: list[tuple[int, float]] = []
    for offset, (identifiable, truth_date) in enumerate(
        zip(truth.identifiable_by_year, truth.trough_date_by_year)
    ):
        if not identifiable or truth_date is None:
            continue
        hy_year = base_year + offset
        row = by_year.get(hy_year)
        if row is None:
            continue
        if row.get("trough_timing_status") != "point":
            continue
        predicted = row.get("trough_month")
        if pd.isna(predicted):
            continue
        errors.append((hy_year, float(_month_delta(predicted, truth_date))))
    return errors


def _split_wrong_cycle(errors: list[tuple[int, float]]) -> tuple[list[float], int]:
    """Separate accuracy-distance errors from wrong-cycle misattributions.

    A boundary landing more than ``_GEOMETRY_MAX_MATCH_MONTHS`` months from
    its matched truth year is a year-attribution failure, not a boundary
    precision measurement -- the same convention the established geometry
    scorer (``hydroseason._calibration``) uses. Folding a handful of these
    into the same pool as month-level errors would let wrong-cycle outliers
    dominate a median/p90 that is meant to describe precision.
    """
    accuracy = [error for _, error in errors if abs(error) <= _GEOMETRY_MAX_MATCH_MONTHS]
    wrong_cycle = sum(1 for _, error in errors if abs(error) > _GEOMETRY_MAX_MATCH_MONTHS)
    return accuracy, wrong_cycle


def _error_summary(errors: list[float]) -> dict[str, float | int | None]:
    if not errors:
        return {
            "n": 0,
            "median_abs_error_months": None,
            "p90_abs_error_months": None,
            "mean_abs_error_months": None,
            "signed_bias_months": None,
        }
    values = np.asarray(errors, dtype=float)
    absolute = np.abs(values)
    return {
        "n": int(values.size),
        "median_abs_error_months": float(np.median(absolute)),
        "p90_abs_error_months": float(np.percentile(absolute, 90.0)),
        "mean_abs_error_months": float(np.mean(absolute)),
        "signed_bias_months": float(np.mean(values)),
    }


def evaluate_records(
    *,
    seeds: list[int],
    partition: str,
    policy: TroughRefinementPolicy,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Run the real detector twice (refinement off/on) per record.

    Uses ``generate_trough_geometry_record`` for complete 12-year records
    with no supplied truth peaks -- the detector finds its own peaks, same
    as production. Errors are matched to truth by year; family-level
    outcomes are reported separately since cycles within one record are
    not independent replications.
    """
    rows: list[dict[str, object]] = []
    families: dict[str, dict[str, list[float]]] = {}
    wrong_cycle_totals = {"off": 0, "on": 0}
    diff_totals: dict[str, int] = {}

    for seed in seeds:
        record = generate_trough_geometry_record(int(seed), partition=partition)
        anchor = record.truth.climatological_trough_month
        config_off = DynamicHydroYearConfig(expected_trough_month=anchor)
        config_on = DynamicHydroYearConfig(
            expected_trough_month=anchor, trough_refinement_policy=policy
        )
        annual_off = detect_dynamic_hydrological_years(record.frame, config=config_off)
        annual_on = detect_dynamic_hydrological_years(record.frame, config=config_on)

        base_year = (
            int(min(annual_off["hy_year"].min(), annual_on["hy_year"].min()))
            if not annual_off.empty and not annual_on.empty
            else None
        )
        if base_year is None:
            continue

        errors_off = _singleton_errors(annual_off, base_year=base_year, truth=record.truth)
        errors_on = _singleton_errors(annual_on, base_year=base_year, truth=record.truth)
        accuracy_off, wrong_cycle_off = _split_wrong_cycle(errors_off)
        accuracy_on, wrong_cycle_on = _split_wrong_cycle(errors_on)
        wrong_cycle_totals["off"] += wrong_cycle_off
        wrong_cycle_totals["on"] += wrong_cycle_on
        _, diff_counts = compare_cycle_tables(annual_off, annual_on)
        for key, value in diff_counts.items():
            diff_totals[key] = diff_totals.get(key, 0) + value

        rows.append(
            {
                "seed": int(seed),
                "family": record.family,
                "n_errors_off": len(errors_off),
                "n_errors_on": len(errors_on),
                "wrong_cycle_off": wrong_cycle_off,
                "wrong_cycle_on": wrong_cycle_on,
                "mean_abs_error_off": (
                    float(np.mean(np.abs(accuracy_off))) if accuracy_off else None
                ),
                "mean_abs_error_on": (
                    float(np.mean(np.abs(accuracy_on))) if accuracy_on else None
                ),
                **{f"diff_{key}": value for key, value in diff_counts.items()},
            }
        )
        bucket = families.setdefault(record.family, {"off": [], "on": []})
        bucket["off"].extend(accuracy_off)
        bucket["on"].extend(accuracy_on)

    off_pool: list[float] = [error for bucket in families.values() for error in bucket["off"]]
    on_pool: list[float] = [error for bucket in families.values() for error in bucket["on"]]

    summary: dict[str, object] = {
        "n_seeds": len(seeds),
        "n_records_with_cycles": len(rows),
        "off": {**_error_summary(off_pool), "wrong_cycle": wrong_cycle_totals["off"]},
        "on": {**_error_summary(on_pool), "wrong_cycle": wrong_cycle_totals["on"]},
        # Aggregate structural-comparison counters (audit 6.6): a reader of
        # this summary alone must be able to see peak_changes,
        # newly_uncomputable, and duplicate/non-monotonic boundaries are
        # actually measured at the integration level, not just per-record.
        "structural_diff_totals": diff_totals,
        "families": {
            family: {
                "n_seeds": sum(1 for row in rows if row["family"] == family),
                "off": _error_summary(bucket["off"]),
                "on": _error_summary(bucket["on"]),
            }
            for family, bucket in sorted(families.items())
        },
    }
    return pd.DataFrame(rows), summary


def _pipeline_manifest_hash(policy: TroughRefinementPolicy) -> str:
    """Fingerprint of the modules and grid this pipeline evaluation depends on."""
    from hydroseason._trough_refinement_calibration import trough_refinement_fingerprint

    hasher = hashlib.sha256()
    # Hash this whole module's own source, not a hand-picked function list --
    # a helper someone forgot to name (e.g. _split_wrong_cycle) previously
    # changed scoring without moving this fingerprint (C3, 2026-09-08
    # review). Reading the file directly also covers everything defined at
    # module scope, not just top-level ``def``s inspect.getsource resolves.
    hasher.update(Path(__file__).read_bytes())
    # This list is detect_dynamic_hydrological_years's actual static import
    # closure (mirrors hydroseason/_dynamic_year.py's own `from .` imports,
    # transitively) plus the corpus generator this evaluation calls directly.
    # _trough_refinement.py itself is covered separately, by
    # trough_refinement_fingerprint(policy) below, not repeated here. This is
    # still a named list, not a computed call graph: a future new import
    # inside any of these modules is not automatically covered, and modules
    # reached only through pandas/numpy/stdlib are out of scope entirely (C3,
    # 2026-09-09 review -- the prior list of _catchment/_condition/_phase was
    # not even part of this call graph, while the real transitive
    # dependencies _timing_identifiability/_circular_timing/
    # _recurrence_identifiability/_state_input/_phase_scheme/_seasonality/
    # _harmonic/_scientific_defaults were missing).
    for module in (
        _boundary,
        _calibration,
        _circular_timing,
        _dynamic_year,
        _harmonic,
        _phase_scheme,
        _recurrence_identifiability,
        _scientific_defaults,
        _seasonality,
        _state_input,
        _synthetic,
        _timing_identifiability,
    ):
        hasher.update(inspect.getsource(module).encode("utf-8"))
    # _GEOMETRY_MAX_MATCH_MONTHS is imported by name into this module's
    # namespace, so hashing _calibration's source is not enough to catch a
    # local rebind of the name actually used at scoring time -- hash the
    # runtime value this module will use.
    hasher.update(json.dumps(_GEOMETRY_MAX_MATCH_MONTHS).encode("utf-8"))
    hasher.update(
        json.dumps(list(PIPELINE_CALIBRATION_SEEDS) + list(PIPELINE_VALIDATION_SEEDS)).encode(
            "utf-8"
        )
    )
    hasher.update(trough_refinement_fingerprint(policy).encode("utf-8"))
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    policy = TroughRefinementPolicy(
        huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5,
        version="trough_refinement_candidate_0_2",
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cycles_frames = []
    payload: dict[str, object] = {
        "policy": {
            "huber_k": policy.huber_k,
            "profile_loss_cutoff": policy.profile_loss_cutoff,
            "pulse_z": policy.pulse_z,
            "version": policy.version,
        },
        "manifest_hash": _pipeline_manifest_hash(policy),
        "partitions": {},
    }
    for partition, seeds in (
        ("calibration", list(PIPELINE_CALIBRATION_SEEDS)),
        ("validation", list(PIPELINE_VALIDATION_SEEDS)),
    ):
        per_record, summary = evaluate_records(seeds=seeds, partition=partition, policy=policy)
        per_record.insert(0, "partition", partition)
        cycles_frames.append(per_record)
        payload["partitions"][partition] = summary

    (output_dir / "pipeline.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    pd.concat(cycles_frames, ignore_index=True).to_csv(
        output_dir / "pipeline-cycles.csv", index=False
    )
    print(f"Wrote pipeline evaluation to {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
