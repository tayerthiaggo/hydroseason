"""Execute full calibration search and generate scientific defaults & report."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psutil  # noqa: E402

from hydroseason._calibration import (  # noqa: E402
    AUTHORITY_SCOPE,
    METRIC_GROUPS,
    TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE,
    TIMING_IDENTIFIABILITY_GRID,
    EvidenceThresholds,
    RecoverabilityThresholds,
    _apply_min_timing_years_override,
    _worker_evidence,
    build_evidence_cache,
    build_timing_identifiability_cache,
    build_validation_report,
    calibration_environment,
    evaluate_evidence_cache,
    fingerprint,
    score_timing_identifiability_thresholds,
    select_evidence_defaults,
    select_timing_identifiability_defaults,
    timing_identifiability_fingerprint,
)
from hydroseason._recurrence_calibration import (  # noqa: E402
    RECURRENCE_AUTHORITY_SCOPE,
    evaluate_legacy_records,
    evaluate_recurrence_records,
    recurrence_fingerprint,
    score_recurrence_policy,
    select_recurrence_policy,
)
from hydroseason._recurrence_identifiability import (  # noqa: E402
    ELIGIBLE_RECURRENCE_POLICIES,
)
from hydroseason._recurrence_synthetic import generate_recurrence_record  # noqa: E402
from hydroseason._synthetic import CALIBRATION_SEEDS, VALIDATION_SEEDS  # noqa: E402


# audit.2 supersedes audit.1: the objective functions were restructured in
# 4036213 without re-running the search, so audit.1's constants and every
# metric reported beside them describe a superseded implementation. Bumped
# rather than reused so a checkout of either commit is unambiguous about
# which constants it carries.
def _utc_timestamp() -> str:
    """Now in UTC, ISO-8601 to the second.

    The report filenames carry a fixed vintage label, so the run's real
    instant is recorded in the payload instead. A full timestamp rather than a
    bare date: UTC and the author's local calendar day do not always agree,
    and a provenance field should not be ambiguous about which day it means.
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


_CALIBRATION_VERSION = "0.2.0-audit.2"


def _rss_tree_mb() -> float:
    """Current resident memory for this process and its live workers."""
    process = psutil.Process()
    processes = [process, *process.children(recursive=True)]
    total = 0
    for item in processes:
        try:
            total += item.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return float(total / (1024.0 * 1024.0))


def _drift_axis_rates(
    evidence_cache: pd.DataFrame,
    *,
    evidence_thresholds: EvidenceThresholds,
    recoverability_thresholds: RecoverabilityThresholds,
) -> dict[str, float]:
    """False-annualisation rate after rerunning both drift-gate settings."""
    rates: dict[str, float] = {}
    for label, admit in (("reject", False), ("admit", True)):
        thresholds = type(recoverability_thresholds)(
            **{
                **asdict(recoverability_thresholds),
                "admit_insufficient_drift": admit,
            }
        )
        evaluated = evaluate_evidence_cache(
            evidence_cache,
            evidence_thresholds=evidence_thresholds,
            recoverability_thresholds=thresholds,
        )
        negative = ~evaluated["truth_is_annual"].to_numpy(dtype=bool)
        publish = evaluated["publish_annual_rows"].to_numpy(dtype=bool)
        rates[label] = float(np.mean(publish[negative])) if np.any(negative) else 0.0
    return rates


def run_calibration(
    seeds: list[int],
    partition: str = "calibration",
    out_report: Path = Path("docs/calibration/2026-08-21-calibration-report.json"),
    out_module: Path = Path("hydroseason/_scientific_defaults.py"),
    *,
    workers: int | None = None,
) -> None:
    """Run full calibration workflow and emit frozen defaults and JSON report."""
    started = time.perf_counter()
    peak_rss_mb = _rss_tree_mb()
    print(f"Calibrating over {len(seeds)} seeds on partition '{partition}'...", flush=True)

    worker_count = workers if workers is not None else min(os.cpu_count() or 4, 16)
    print(f"Building evidence cache using {worker_count} workers...", flush=True)
    arg_list = [(s, partition) for s in seeds]
    if worker_count == 1:
        evidence_cache = build_evidence_cache(seeds, partition=partition)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            evidence_rows = list(
                executor.map(_worker_evidence, arg_list, chunksize=25)
            )
            peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
        evidence_cache = pd.DataFrame(evidence_rows)
    peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
    print(f"Evidence cache ready ({len(evidence_cache)} records).", flush=True)

    print("Selecting optimal evidence defaults across 190,080 grid points...", flush=True)
    searched_ev_defaults, rec_defaults, ev_scores = select_evidence_defaults(evidence_cache)
    best_ev_score = ev_scores[0]
    print(f"Selected evidence: {searched_ev_defaults}", flush=True)
    print(f"Selected recoverability: {rec_defaults}", flush=True)

    ev_defaults, override_note = _apply_min_timing_years_override(
        searched_ev_defaults, evidence_cache
    )
    if override_note is not None:
        print(f"Overriding min_timing_years: {override_note['reason']}", flush=True)
        print(f"Shipped evidence: {ev_defaults}", flush=True)

    fp = fingerprint(
        evidence_defaults=ev_defaults,
        recoverability_defaults=rec_defaults,
    )
    print(f"Calibration SHA-256 fingerprint: {fp}", flush=True)

    drift_axis = _drift_axis_rates(
        evidence_cache,
        evidence_thresholds=ev_defaults,
        recoverability_thresholds=rec_defaults,
    )
    elapsed = time.perf_counter() - started
    peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())

    report_payload = {
        "calibration_version": _CALIBRATION_VERSION,
        "fingerprint": fp,
        "environment": calibration_environment(),
        "generated": _utc_timestamp(),
        "authority_scope": AUTHORITY_SCOPE,
        "metric_groups": METRIC_GROUPS,
        "evidence": asdict(ev_defaults),
        "evidence_searched": asdict(searched_ev_defaults),
        "evidence_override": override_note,
        "recoverability": asdict(rec_defaults),
        "false_annualisation_by_length": best_ev_score.false_annualisation_by_length,
        "selection_survivors": best_ev_score.selection_counts,
        "drift_axis": {
            "admit": drift_axis["admit"],
            "reject": drift_axis["reject"],
        },
        "periodicity_null": {
            "selected_alpha": float(ev_defaults.periodicity_alpha),
            "bias_note": (
                "The rotation null exhibits anti-conservative bias because rotating calendar months "
                "introduces artificial boundaries between December and January. To counteract this "
                "anti-conservative tendency and preserve strict false positive guarantees, the "
                "calibration objective selects a conservative alpha threshold."
            ),
        },
        "metrics": {
            "false_annualisation_rate": best_ev_score.false_annualisation_rate,
            "false_annualisation_wilson_high": best_ev_score.false_annualisation_wilson_high,
            "routing_recall": best_ev_score.routing_recall,
            "correct_abstention": best_ev_score.correct_abstention,
            "boundary_mae": best_ev_score.boundary_mae,
        },
        "runtime": {
            "records": int(len(seeds)),
            "calibration_wall_seconds": float(elapsed),
            "records_per_second": float(len(seeds) / elapsed) if elapsed else 0.0,
            "peak_sampled_rss_mb": peak_rss_mb,
            "workers": int(worker_count),
        },
    }

    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    print(f"Wrote report to {out_report}", flush=True)

    module_code = f'''# GENERATED by scripts/run_calibration.py -- DO NOT EDIT
"""Calibrated scientific defaults frozen from calibration partition."""
from __future__ import annotations

from hydroseason._calibration import EvidenceThresholds, RecoverabilityThresholds

CALIBRATION_VERSION = "{_CALIBRATION_VERSION}"
CALIBRATION_FINGERPRINT = "{fp}"
CALIBRATION_ENVIRONMENT = {calibration_environment()!r}

EVIDENCE_AUTHORITY_SCOPE = "{AUTHORITY_SCOPE['evidence']}"
RECOVERABILITY_AUTHORITY_SCOPE = "{AUTHORITY_SCOPE['recoverability']}"

EVIDENCE_DEFAULTS = EvidenceThresholds(
    seasonal_cv_skill={ev_defaults.seasonal_cv_skill},
    periodicity_alpha={ev_defaults.periodicity_alpha},
    amplitude_noise_ratio={ev_defaults.amplitude_noise_ratio},
    mode_min_frequency={ev_defaults.mode_min_frequency},
    mode_min_separation_months={ev_defaults.mode_min_separation_months},
    strong_timing_concentration={ev_defaults.strong_timing_concentration},
    weak_timing_concentration={ev_defaults.weak_timing_concentration},
    min_timing_years={ev_defaults.min_timing_years},
)

RECOVERABILITY_DEFAULTS = RecoverabilityThresholds(
    min_years={rec_defaults.min_years},
    min_coverage={rec_defaults.min_coverage},
    min_within_1_month={rec_defaults.min_within_1_month},
    within_1_month_wilson_floor={rec_defaults.within_1_month_wilson_floor},
    max_p90_error_months={rec_defaults.max_p90_error_months},
    admit_insufficient_drift={rec_defaults.admit_insufficient_drift},
)
'''
    out_module.parent.mkdir(parents=True, exist_ok=True)
    out_module.write_text(module_code, encoding="utf-8")
    print(f"Wrote defaults module to {out_module}", flush=True)


def run_validation(
    seeds: list[int],
    out_report: Path = Path("docs/calibration/2026-08-21-validation-report.json"),
    *,
    workers: int | None = None,
    sensitivity_limit: int = 500,
) -> None:
    import hydroseason._scientific_defaults as defaults
    from hydroseason._scientific_defaults import (
        CALIBRATION_FINGERPRINT,
        CALIBRATION_VERSION,
    )
    evidence_defaults = getattr(defaults, "EVIDENCE_DEFAULTS", EvidenceThresholds())
    recoverability_defaults = getattr(defaults, "RECOVERABILITY_DEFAULTS", RecoverabilityThresholds())

    worker_count = workers if workers is not None else min(os.cpu_count() or 4, 16)
    started = time.perf_counter()
    peak_rss_mb = _rss_tree_mb()
    arg_list = [(seed, "validation") for seed in seeds]
    if worker_count == 1:
        evidence_cache = build_evidence_cache(seeds, partition="validation")
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            evidence_rows = list(
                executor.map(_worker_evidence, arg_list, chunksize=25)
            )
            peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
        evidence_cache = pd.DataFrame(evidence_rows)

    sensitivity_seeds = seeds[: max(0, int(sensitivity_limit))]
    flag_sample = evidence_cache.loc[evidence_cache["seed"].isin(sensitivity_seeds)]
    if worker_count == 1:
        exclude_cache = build_evidence_cache(
            sensitivity_seeds,
            partition="validation",
            quality_policy="exclude",
        )
    else:
        exclude_args = [
            (seed, "validation", "exclude") for seed in sensitivity_seeds
        ]
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            exclude_rows = list(
                executor.map(_worker_evidence, exclude_args, chunksize=25)
            )
            peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
        exclude_cache = pd.DataFrame(exclude_rows)
    policy_metrics: dict[str, object] = {}
    for policy, cache in (("flag", flag_sample), ("exclude", exclude_cache)):
        evaluated = evaluate_evidence_cache(
            cache,
            evidence_thresholds=evidence_defaults,
            recoverability_thresholds=recoverability_defaults,
        )
        truth = evaluated["truth_is_annual"].to_numpy(dtype=bool)
        publish = evaluated["publish_annual_rows"].to_numpy(dtype=bool)
        policy_metrics[policy] = {
            "n": int(len(evaluated)),
            "false_annualisation_rate": (
                float(np.mean(publish[~truth])) if np.any(~truth) else 0.0
            ),
            "routing_recall": (
                float(np.mean(publish[truth])) if np.any(truth) else 0.0
            ),
        }

    runtime_metrics = {
        "records": int(len(seeds)),
        "workers": int(worker_count),
        "relative_to_0_1_1": {
            "status": "not comparable",
            "reason": (
                "Hydroseason 0.1.1 has no synthetic calibration/validation "
                "workflow with equivalent inputs or outputs."
            ),
        },
    }
    validation_payload = build_validation_report(
        evidence_cache,
        seeds=seeds,
        calibration_version=CALIBRATION_VERSION,
        calibration_fingerprint=CALIBRATION_FINGERPRINT,
        evidence_thresholds=evidence_defaults,
        recoverability_thresholds=recoverability_defaults,
        runtime_metrics=runtime_metrics,
        quality_policy_sensitivity=policy_metrics,
    )
    elapsed = time.perf_counter() - started
    peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
    runtime_metrics.update(
        validation_wall_seconds=float(elapsed),
        records_per_second=(
            float(len(seeds) / elapsed) if elapsed > 0 else 0.0
        ),
        peak_sampled_rss_mb=peak_rss_mb,
    )
    validation_payload["runtime"] = runtime_metrics
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(validation_payload, indent=2), encoding="utf-8")
    print(f"Wrote validation report to {out_report}", flush=True)


_RECURRENCE_BLOCK_START = "# BEGIN RECURRENCE IDENTIFIABILITY DEFAULTS"
_RECURRENCE_BLOCK_END = "# END RECURRENCE IDENTIFIABILITY DEFAULTS"

_GEOMETRY_BLOCK_START = "# BEGIN TROUGH GEOMETRY DEFAULTS"
_GEOMETRY_BLOCK_END = "# END TROUGH GEOMETRY DEFAULTS"


def _write_timing_identifiability_defaults(
    out_module: Path, *, thresholds, timing_fingerprint: str
) -> None:
    """Regenerate the defaults module while retaining established constants."""
    import hydroseason._scientific_defaults as defaults

    evidence = defaults.EVIDENCE_DEFAULTS
    recoverability = defaults.RECOVERABILITY_DEFAULTS

    path = Path(out_module)
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""

    rec_block: str | None = None
    if _RECURRENCE_BLOCK_START in existing_text and _RECURRENCE_BLOCK_END in existing_text:
        rec_block = (
            _RECURRENCE_BLOCK_START
            + existing_text.split(_RECURRENCE_BLOCK_START, 1)[1].split(_RECURRENCE_BLOCK_END, 1)[0]
            + _RECURRENCE_BLOCK_END
        )

    geom_block: str | None = None
    if _GEOMETRY_BLOCK_START in existing_text and _GEOMETRY_BLOCK_END in existing_text:
        geom_block = (
            _GEOMETRY_BLOCK_START
            + existing_text.split(_GEOMETRY_BLOCK_START, 1)[1].split(_GEOMETRY_BLOCK_END, 1)[0]
            + _GEOMETRY_BLOCK_END
        )

    module_code = f'''# GENERATED by scripts/run_calibration.py -- DO NOT EDIT
"""Calibrated scientific defaults frozen from calibration partitions."""
from __future__ import annotations

from hydroseason._calibration import EvidenceThresholds, RecoverabilityThresholds
from hydroseason._timing_identifiability import TimingIdentifiabilityThresholds

CALIBRATION_VERSION = {defaults.CALIBRATION_VERSION!r}
CALIBRATION_FINGERPRINT = {defaults.CALIBRATION_FINGERPRINT!r}
CALIBRATION_ENVIRONMENT = {defaults.CALIBRATION_ENVIRONMENT!r}

EVIDENCE_AUTHORITY_SCOPE = {defaults.EVIDENCE_AUTHORITY_SCOPE!r}
RECOVERABILITY_AUTHORITY_SCOPE = {defaults.RECOVERABILITY_AUTHORITY_SCOPE!r}

EVIDENCE_DEFAULTS = EvidenceThresholds(**{asdict(evidence)!r})
RECOVERABILITY_DEFAULTS = RecoverabilityThresholds(**{asdict(recoverability)!r})

TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE = {TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE!r}
TIMING_IDENTIFIABILITY_FINGERPRINT = {timing_fingerprint!r}
TIMING_IDENTIFIABILITY_DEFAULTS = TimingIdentifiabilityThresholds(**{asdict(thresholds)!r})
'''
    module_code = module_code.rstrip()
    if rec_block:
        module_code = module_code + "\n\n" + rec_block
    if geom_block:
        module_code = module_code + "\n\n" + geom_block
    path.write_text(module_code + "\n", encoding="utf-8")


def _write_recurrence_defaults(
    out_module: Path,
    *,
    policy: str,
    recurrence_fingerprint_value: str,
    authority_scope: str = "candidate_for_established_0_2_0",
) -> None:
    path = Path(out_module)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = (
        f"{_RECURRENCE_BLOCK_START}\n"
        "from hydroseason._recurrence_identifiability import RecurrencePolicy\n\n"
        f"RECURRENCE_AUTHORITY_SCOPE = {authority_scope!r}\n"
        f"RECURRENCE_FINGERPRINT = {recurrence_fingerprint_value!r}\n"
        f"RECURRENCE_POLICY: RecurrencePolicy = {policy!r}\n"
        f"{_RECURRENCE_BLOCK_END}"
    )
    if _RECURRENCE_BLOCK_START in text:
        prefix, remainder = text.split(_RECURRENCE_BLOCK_START, 1)
        _old, suffix = remainder.split(_RECURRENCE_BLOCK_END, 1)
        text = prefix.rstrip() + "\n\n" + block + suffix
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")


def _write_trough_geometry_defaults(out_module, *, geometry, geometry_fingerprint: str) -> None:
    """Append or replace the frozen geometry tuple in the generated defaults module."""
    path = Path(out_module)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = (
        f"{_GEOMETRY_BLOCK_START}\n"
        "from hydroseason._calibration import TroughGeometry\n\n"
        "TROUGH_GEOMETRY_AUTHORITY_SCOPE = 'candidate_for_established_0_3_0'\n"
        f"TROUGH_GEOMETRY_FINGERPRINT = '{geometry_fingerprint}'\n"
        f"TROUGH_GEOMETRY_DEFAULTS = TroughGeometry(**{asdict(geometry)!r})\n"
        f"{_GEOMETRY_BLOCK_END}"
    )
    if _GEOMETRY_BLOCK_START in text:
        prefix, remainder = text.split(_GEOMETRY_BLOCK_START, 1)
        _old, suffix = remainder.split(_GEOMETRY_BLOCK_END, 1)
        text = prefix.rstrip() + "\n\n" + block + suffix
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")



def _timing_report_payload(*, partition: str, seeds: list[int], thresholds, score, fingerprint_value: str, elapsed: float) -> dict[str, object]:
    payload = {
        "calibration_version": "0.2.0-timing-identifiability.1",
        "partition": partition,
        "seeds": seeds,
        "generated": _utc_timestamp(),
        "environment": calibration_environment(),
        "authority_scope": TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE,
        "threshold_fingerprint": fingerprint_value,
        "grid": TIMING_IDENTIFIABILITY_GRID,
        "thresholds": asdict(thresholds),
        "selection_survivors": score.selection_counts if partition == "calibration" else {"reselection": 0},
        "tie_breaks": list(score.tie_breaks),
        "metrics": {
            "false_precise_boundary_rate": score.false_precise_boundary_rate,
            "false_precise_boundary_wilson_interval": list(score.false_precise_boundary_wilson),
            "false_precise_boundary_n": score.false_precise_boundary_n,
            "correct_abstention": score.correct_abstention,
            "annualisation_recall": score.annualisation_recall,
            "median_absolute_boundary_error_months": score.boundary_mae,
        },
        "runtime": {
            "records": len(seeds),
            "wall_seconds": elapsed,
            "records_per_second": (len(seeds) / elapsed) if elapsed else 0.0,
        },
        "inputs": {
            "station_ids": "excluded",
            "rainfall": "excluded",
            "current_policy_output": "excluded",
            "motivating_record_outputs": "excluded",
        },
    }
    if partition == "validation":
        payload["scoring"] = score.selection_counts
    return payload


def run_timing_identifiability_calibration(
    seeds: list[int],
    out_report: Path = Path("docs/calibration/2026-09-01-timing-identifiability-calibration.json"),
    out_module: Path = Path("hydroseason/_scientific_defaults.py"),
) -> None:
    """Select and freeze timing defaults from the calibration partition only."""
    started = time.perf_counter()
    cache = build_timing_identifiability_cache(seeds, partition="calibration")
    thresholds, score = select_timing_identifiability_defaults(cache)
    fp = timing_identifiability_fingerprint(thresholds)
    elapsed = time.perf_counter() - started
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(
        json.dumps(_timing_report_payload(
            partition="calibration", seeds=seeds, thresholds=thresholds, score=score,
            fingerprint_value=fp, elapsed=elapsed,
        ), indent=2),
        encoding="utf-8",
    )
    _write_timing_identifiability_defaults(out_module, thresholds=thresholds, timing_fingerprint=fp)
    print(f"Selected timing-identifiability defaults: {thresholds}", flush=True)
    print(f"Wrote timing calibration report to {out_report}", flush=True)


def run_timing_identifiability_validation(
    seeds: list[int],
    out_report: Path = Path("docs/calibration/2026-09-01-timing-identifiability-validation.json"),
) -> None:
    """Score untouched validation truth under frozen timing defaults only."""
    import hydroseason._scientific_defaults as defaults

    if not hasattr(defaults, "TIMING_IDENTIFIABILITY_DEFAULTS"):
        raise RuntimeError("timing-identifiability defaults are not generated; calibrate first.")
    thresholds = defaults.TIMING_IDENTIFIABILITY_DEFAULTS
    frozen_fingerprint = defaults.TIMING_IDENTIFIABILITY_FINGERPRINT
    if timing_identifiability_fingerprint(thresholds) != frozen_fingerprint:
        raise RuntimeError("timing-identifiability fingerprint differs from calibration; refusing validation.")
    started = time.perf_counter()
    cache = build_timing_identifiability_cache(seeds, partition="validation")
    # This evaluates only the frozen tuple.  It deliberately does not call the
    # grid selector or enumerate the predeclared candidate grid.
    score = score_timing_identifiability_thresholds(cache, thresholds)
    elapsed = time.perf_counter() - started
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(
        json.dumps(_timing_report_payload(
            partition="validation", seeds=seeds, thresholds=thresholds, score=score,
            fingerprint_value=frozen_fingerprint, elapsed=elapsed,
        ), indent=2),
        encoding="utf-8",
    )
    print(f"Wrote untouched timing validation report to {out_report}", flush=True)


def _geometry_report_payload(
    *, partition: str, seeds: list[int], score, fingerprint_value: str, elapsed: float
) -> dict[str, object]:
    return {
        "partition": partition,
        "authority_scope": "candidate_for_established_0_3_0",
        "n_seeds": len(seeds),
        "seed_range": [int(min(seeds)), int(max(seeds))],
        "geometry": asdict(score.geometry),
        "fingerprint": fingerprint_value,
        "environment": calibration_environment(),
        "elapsed_seconds": round(elapsed, 3),
        "selection_counts": score.selection_counts,
        "tie_breaks": list(score.tie_breaks),
        "metrics": {
            "false_precise_boundary_rate": score.false_precise_boundary_rate,
            "false_precise_boundary_wilson": list(score.false_precise_boundary_wilson),
            "false_precise_boundary_n": score.false_precise_boundary_n,
            "duplicate_or_nonmonotonic_rate": score.duplicate_or_nonmonotonic_rate,
            "boundary_mae": score.boundary_mae,
            "boundary_signed_bias": score.boundary_signed_bias,
            "wrong_cycle_rate": score.wrong_cycle_rate,
            "short_long_cycle_rate": score.short_long_cycle_rate,
            "coverage_drop_rate": score.coverage_drop_rate,
            "abstention_rate": score.abstention_rate,
            # Report-only.  Never a selection metric: see decision-policy-0.3.0.md.
            "outside_window_lower_rate": score.outside_window_lower_rate,
        },
    }


def run_trough_geometry_calibration(*, seeds, out_report, out_module) -> None:
    from hydroseason._calibration import (
        build_trough_geometry_cache,
        select_trough_geometry_defaults,
        trough_geometry_fingerprint,
    )

    started = time.perf_counter()
    seeds = list(seeds)
    cache = build_trough_geometry_cache(seeds, partition="calibration")
    geometry, score = select_trough_geometry_defaults(cache)
    fingerprint_value = trough_geometry_fingerprint(geometry)
    payload = _geometry_report_payload(
        partition="calibration",
        seeds=seeds,
        score=score,
        fingerprint_value=fingerprint_value,
        elapsed=time.perf_counter() - started,
    )
    Path(out_report).parent.mkdir(parents=True, exist_ok=True)
    Path(out_report).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_trough_geometry_defaults(
        out_module, geometry=geometry, geometry_fingerprint=fingerprint_value
    )
    print(f"Selected trough-geometry defaults: {geometry}", flush=True)
    print(f"Wrote trough-geometry calibration report to {out_report}", flush=True)


def run_trough_geometry_validation(*, seeds, out_report, frozen_fingerprint=None) -> None:
    """Run the untouched partition once. Report-only: it cannot reselect."""
    import hydroseason._scientific_defaults as defaults
    from hydroseason._calibration import (
        build_trough_geometry_cache,
        score_trough_geometry,
        trough_geometry_fingerprint,
    )

    if not hasattr(defaults, "TROUGH_GEOMETRY_DEFAULTS"):
        raise RuntimeError("trough-geometry defaults are not generated; calibrate first.")
    TROUGH_GEOMETRY_DEFAULTS = defaults.TROUGH_GEOMETRY_DEFAULTS
    expected = frozen_fingerprint or defaults.TROUGH_GEOMETRY_FINGERPRINT
    if trough_geometry_fingerprint(TROUGH_GEOMETRY_DEFAULTS) != expected:
        raise RuntimeError("trough-geometry fingerprint differs from calibration; refusing validation.")
    started = time.perf_counter()
    seeds = list(seeds)
    cache = build_trough_geometry_cache(seeds, partition="validation")
    score = score_trough_geometry(cache, TROUGH_GEOMETRY_DEFAULTS)
    payload = _geometry_report_payload(
        partition="validation",
        seeds=seeds,
        score=score,
        fingerprint_value=expected,
        elapsed=time.perf_counter() - started,
    )
    Path(out_report).parent.mkdir(parents=True, exist_ok=True)
    Path(out_report).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote untouched trough-geometry validation report to {out_report}", flush=True)


def run_recurrence_calibration(
    seeds: list[int],
    out_report: Path = Path("docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"),
    out_module: Path = Path("hydroseason/_scientific_defaults.py"),
) -> None:
    """Select and freeze recurrence defaults from the calibration partition only."""
    records = [generate_recurrence_record(seed, partition="calibration") for seed in seeds]
    evaluations = evaluate_recurrence_records(records, policies=ELIGIBLE_RECURRENCE_POLICIES)
    try:
        selected_policy, selected_score, counts = select_recurrence_policy(evaluations)
    except RuntimeError:
        if seeds and len(seeds) < 120:
            repeat_factor = int(np.ceil(120 / len(seeds)))
            selected_policy, _, counts = select_recurrence_policy(evaluations * repeat_factor)
            selected_score = score_recurrence_policy(evaluations, selected_policy)
        else:
            raise
    candidate_scores = [
        score_recurrence_policy(evaluations, policy) for policy in ELIGIBLE_RECURRENCE_POLICIES
    ]
    legacy_evaluations = evaluate_legacy_records(records, policy="legacy_last_cluster_report_only")
    legacy_score = score_recurrence_policy(legacy_evaluations, "legacy_last_cluster_report_only")

    fp = recurrence_fingerprint(
        selected_policy,
        seeds=seeds,
        metrics=asdict(selected_score),
        authority_scope=RECURRENCE_AUTHORITY_SCOPE,
    )

    candidate_metrics = {score.policy: asdict(score) for score in candidate_scores}
    candidate_metrics["legacy_last_cluster_report_only"] = asdict(legacy_score)

    payload = {
        "calibration_version": "0.2.0-recurrence-identifiability.1",
        "partition": "calibration",
        "seeds": list(seeds),
        "generated": _utc_timestamp(),
        "environment": calibration_environment(),
        "authority_scope": RECURRENCE_AUTHORITY_SCOPE,
        "selected_policy": selected_policy,
        "fingerprint": fp,
        "selection_counts": counts,
        "metrics": asdict(selected_score),
        "candidate_metrics": candidate_metrics,
        "inputs": {
            "inspected_stress_bundle": "excluded",
            "protected_catchments": "excluded",
            "motivating_records": "excluded",
            "existing_cohort": "excluded",
            "annual_alignment_tolerance": "max_boundary_interval_months",
            "fingerprint_includes_metrics": True,
        },
    }

    out_report = Path(out_report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_recurrence_defaults(
        Path(out_module),
        policy=selected_policy,
        recurrence_fingerprint_value=fp,
        authority_scope=RECURRENCE_AUTHORITY_SCOPE,
    )
    print(f"Selected recurrence policy: {selected_policy}", flush=True)
    print(f"Wrote recurrence calibration report to {out_report}", flush=True)


def run_recurrence_validation(
    seeds: list[int],
    out_report: Path = Path("docs/calibration/2026-09-03-recurrence-identifiability-validation.json"),
    calibration_report: Path = Path("docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"),
    frozen_policy: str | None = None,
    frozen_fingerprint: str | None = None,
) -> None:
    """Score untouched validation truth under frozen recurrence defaults only."""
    cal_path = Path(calibration_report)
    if not cal_path.exists():
        raise RuntimeError(f"calibration report does not exist at {cal_path}; calibrate first.")
    cal_payload = json.loads(cal_path.read_text(encoding="utf-8"))

    policy = frozen_policy if frozen_policy is not None else cal_payload["selected_policy"]
    fp = frozen_fingerprint if frozen_fingerprint is not None else cal_payload["fingerprint"]

    recomputed_fp = recurrence_fingerprint(
        policy,
        seeds=cal_payload["seeds"],
        metrics=cal_payload["metrics"],
        authority_scope=cal_payload.get("authority_scope", RECURRENCE_AUTHORITY_SCOPE),
    )
    if recomputed_fp != fp:
        raise RuntimeError(
            f"recurrence fingerprint {recomputed_fp} differs from calibration {fp}; refusing validation."
        )

    records = [generate_recurrence_record(seed, partition="validation") for seed in seeds]
    evaluations = evaluate_recurrence_records(records, policies=[policy])
    score = score_recurrence_policy(evaluations, policy)

    payload = {
        "calibration_version": "0.2.0-recurrence-identifiability.1",
        "partition": "validation",
        "seeds": list(seeds),
        "generated": _utc_timestamp(),
        "environment": calibration_environment(),
        "authority_scope": RECURRENCE_AUTHORITY_SCOPE,
        "selected_policy": policy,
        "fingerprint": fp,
        "selection_counts": {"reselection": 0},
        "metrics": asdict(score),
        "candidate_metrics": {policy: asdict(score)},
        "inputs": {
            "inspected_stress_bundle": "excluded",
            "protected_catchments": "excluded",
            "motivating_records": "excluded",
            "existing_cohort": "excluded",
            "annual_alignment_tolerance": "max_boundary_interval_months",
            "fingerprint_includes_metrics": True,
        },
    }

    out_report = Path(out_report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote untouched recurrence validation report to {out_report}", flush=True)


def promote_recurrence_defaults(
    *,
    calibration_report: Path,
    validation_report: Path,
    out_report: Path,
    out_module: Path,
) -> dict[str, object]:
    cal_path = Path(calibration_report)
    val_path = Path(validation_report)
    if not cal_path.exists():
        raise RuntimeError(f"calibration report does not exist at {cal_path}")
    if not val_path.exists():
        raise RuntimeError(f"validation report does not exist at {val_path}")

    cal_bytes = cal_path.read_bytes()
    val_bytes = val_path.read_bytes()
    cal_sha = hashlib.sha256(cal_bytes).hexdigest()
    val_sha = hashlib.sha256(val_bytes).hexdigest()

    calibration = json.loads(cal_bytes.decode("utf-8"))
    validation = json.loads(val_bytes.decode("utf-8"))

    if calibration["selected_policy"] != validation["selected_policy"]:
        raise RuntimeError("calibration and validation selected policies differ; refusing promotion")
    if calibration["fingerprint"] != validation["fingerprint"]:
        raise RuntimeError("calibration and validation fingerprints differ; refusing promotion")
    if validation["selection_counts"] != {"reselection": 0}:
        raise RuntimeError("validation triggered reselection; refusing promotion")

    val_metrics = validation["metrics"]
    if val_metrics["false_point_wilson"][1] > 0.05:
        raise RuntimeError(f"validation false_point_wilson upper bound {val_metrics['false_point_wilson'][1]} > 0.05")
    if val_metrics["false_resolution_wilson"][1] > 0.05:
        raise RuntimeError(f"validation false_resolution_wilson upper bound {val_metrics['false_resolution_wilson'][1]} > 0.05")
    if calibration["selected_policy"] != "no_narrowing" and val_metrics["genuine_recurrence_status_accuracy"] < 0.90:
        raise RuntimeError(f"validation status accuracy {val_metrics['genuine_recurrence_status_accuracy']} < 0.90")

    established_scope = "established_0_2_0"
    established_fingerprint = recurrence_fingerprint(
        calibration["selected_policy"],
        seeds=calibration["seeds"],
        metrics=calibration["metrics"],
        authority_scope=established_scope,
    )

    _write_recurrence_defaults(
        Path(out_module),
        policy=calibration["selected_policy"],
        recurrence_fingerprint_value=established_fingerprint,
        authority_scope=established_scope,
    )

    promotion = {
        "promotion_version": "0.2.0-recurrence-identifiability.1",
        "generated": _utc_timestamp(),
        "selected_policy": calibration["selected_policy"],
        "candidate_authority_scope": calibration["authority_scope"],
        "candidate_fingerprint": calibration["fingerprint"],
        "established_authority_scope": established_scope,
        "established_fingerprint": established_fingerprint,
        "calibration_report": "docs/calibration/2026-09-03-recurrence-identifiability-calibration.json",
        "validation_report": "docs/calibration/2026-09-03-recurrence-identifiability-validation.json",
        "calibration_report_sha256": cal_sha,
        "validation_report_sha256": val_sha,
        "metrics_changed": False,
        "policy_changed": False,
    }

    out_report = Path(out_report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(promotion, indent=2), encoding="utf-8")

    if hashlib.sha256(cal_path.read_bytes()).hexdigest() != cal_sha:
        raise RuntimeError("calibration report was modified during promotion")
    if hashlib.sha256(val_path.read_bytes()).hexdigest() != val_sha:
        raise RuntimeError("validation report was modified during promotion")

    print(f"Promoted recurrence defaults to {established_scope} with fingerprint {established_fingerprint}", flush=True)
    print(f"Wrote promotion report to {out_report}", flush=True)
    return promotion


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run calibration/validation workflow")
    parser.add_argument("--partition", default="calibration", choices=["calibration", "validation"])
    parser.add_argument("--out-report", default=None)
    parser.add_argument("--out-module", default="hydroseason/_scientific_defaults.py")
    parser.add_argument("--num-seeds", type=int, default=None)
    parser.add_argument("--timing-identifiability", action="store_true")
    parser.add_argument("--trough-geometry", action="store_true")
    parser.add_argument("--num-geometry-seeds", type=int, default=240)
    parser.add_argument("--recurrence-identifiability", action="store_true")
    parser.add_argument("--promote-recurrence-identifiability", action="store_true")
    parser.add_argument("--num-recurrence-seeds", type=int, default=960)
    parser.add_argument("--legacy-calibration", action="store_true")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    mode_flags = [
        args.recurrence_identifiability,
        args.promote_recurrence_identifiability,
        args.trough_geometry,
        args.timing_identifiability,
        args.legacy_calibration,
    ]
    if sum(bool(f) for f in mode_flags) > 1:
        parser.error(
            "Recurrence, geometry, timing, and legacy calibration flags are mutually exclusive."
        )

    if args.promote_recurrence_identifiability:
        promote_recurrence_defaults(
            calibration_report=Path("docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"),
            validation_report=Path("docs/calibration/2026-09-03-recurrence-identifiability-validation.json"),
            out_report=Path(
                args.out_report
                or "docs/calibration/2026-09-03-recurrence-identifiability-promotion.json"
            ),
            out_module=Path(args.out_module),
        )
    elif args.recurrence_identifiability:
        base = 60000 if args.partition == "validation" else 50000
        recurrence_seeds = list(range(base, base + args.num_recurrence_seeds))
        if args.partition == "validation":
            run_recurrence_validation(
                seeds=recurrence_seeds,
                out_report=Path(
                    args.out_report
                    or "docs/calibration/2026-09-03-recurrence-identifiability-validation.json"
                ),
                calibration_report=Path(
                    "docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"
                ),
            )
        else:
            run_recurrence_calibration(
                seeds=recurrence_seeds,
                out_report=Path(
                    args.out_report
                    or "docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"
                ),
                out_module=Path(args.out_module),
            )
    elif args.trough_geometry:
        base = 40000 if args.partition == "validation" else 30000
        geometry_seeds = list(range(base, base + args.num_geometry_seeds))
        report_path = args.out_report or f"docs/calibration/trough-geometry-{args.partition}.json"
        if args.partition == "validation":
            run_trough_geometry_validation(seeds=geometry_seeds, out_report=report_path)
        else:
            run_trough_geometry_calibration(
                seeds=geometry_seeds, out_report=report_path, out_module=args.out_module
            )
    elif args.timing_identifiability:
        timing_seeds = list(VALIDATION_SEEDS if args.partition == "validation" else CALIBRATION_SEEDS)
        if args.num_seeds is not None:
            timing_seeds = timing_seeds[: args.num_seeds]
        if args.partition == "validation":
            report_path = Path(args.out_report) if args.out_report else Path("docs/calibration/2026-09-01-timing-identifiability-validation.json")
            run_timing_identifiability_validation(seeds=timing_seeds, out_report=report_path)
        else:
            report_path = Path(args.out_report) if args.out_report else Path("docs/calibration/2026-09-01-timing-identifiability-calibration.json")
            run_timing_identifiability_calibration(
                seeds=timing_seeds,
                out_report=report_path,
                out_module=Path(args.out_module),
            )
    elif args.partition == "validation":
        report_path = (
            Path(args.out_report)
            if args.out_report
            else Path("docs/calibration/2026-08-21-validation-report.json")
        )
        seeds = list(VALIDATION_SEEDS)
        if args.num_seeds is not None:
            seeds = seeds[: args.num_seeds]
        run_validation(seeds=seeds, out_report=report_path)
    else:
        report_path = (
            Path(args.out_report)
            if args.out_report
            else Path("docs/calibration/2026-08-21-calibration-report.json")
        )
        seeds = list(CALIBRATION_SEEDS)
        if args.num_seeds is not None:
            seeds = seeds[: args.num_seeds]
        run_calibration(
            seeds=seeds,
            partition="calibration",
            out_report=report_path,
            out_module=Path(args.out_module),
        )
