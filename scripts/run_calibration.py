"""Execute full calibration search and generate scientific defaults & report."""
from __future__ import annotations

import argparse
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

from hydroseason._boundary_recoverability import RecoverabilityThresholds  # noqa: E402
from hydroseason._calibration import (  # noqa: E402
    _worker_evidence,
    _worker_phase,
    build_evidence_cache,
    build_phase_cache,
    build_validation_report,
    evaluate_evidence_cache,
    fingerprint,
    select_evidence_defaults,
    select_phase_defaults,
)
from hydroseason._evidence import EvidenceThresholds  # noqa: E402
from hydroseason._synthetic import CALIBRATION_SEEDS  # noqa: E402

_CALIBRATION_VERSION = "0.2.0-audit.1"


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

    print(f"Building phase cache using {worker_count} workers...", flush=True)
    if worker_count == 1:
        phase_cache = build_phase_cache(seeds, partition=partition)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            phase_results = list(executor.map(_worker_phase, arg_list, chunksize=25))
            peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
        phase_cache = tuple(cycle for result in phase_results for cycle in result)
    peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
    print(f"Phase cache ready ({len(phase_cache)} annual cycles).", flush=True)

    print("Selecting optimal evidence defaults across 190,080 grid points...", flush=True)
    ev_defaults, rec_defaults, ev_scores = select_evidence_defaults(evidence_cache)
    best_ev_score = ev_scores[0]
    print(f"Selected evidence: {ev_defaults}", flush=True)
    print(f"Selected recoverability: {rec_defaults}", flush=True)

    print("Selecting optimal phase defaults across 144 grid points...", flush=True)
    phase_defaults, phase_scores = select_phase_defaults(phase_cache)
    best_phase_score = phase_scores[0]
    print(f"Selected phase: {phase_defaults}", flush=True)

    fp = fingerprint(
        evidence_defaults=ev_defaults,
        recoverability_defaults=rec_defaults,
        phase_defaults=phase_defaults,
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
        "evidence": asdict(ev_defaults),
        "recoverability": asdict(rec_defaults),
        "phase": asdict(phase_defaults),
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
            "phase_macro_accuracy": best_phase_score.macro_accuracy,
            "phase_transition_mae": best_phase_score.transition_mae,
            "phase_forced_complete_rate": best_phase_score.forced_complete_rate,
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

from hydroseason._boundary_recoverability import RecoverabilityThresholds
from hydroseason._cycle_phase import PhaseThresholds
from hydroseason._evidence import EvidenceThresholds

CALIBRATION_VERSION = "{_CALIBRATION_VERSION}"
CALIBRATION_FINGERPRINT = "{fp}"

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

PHASE_DEFAULTS = PhaseThresholds(
    phase_low_fraction={phase_defaults.phase_low_fraction},
    phase_high_fraction={phase_defaults.phase_high_fraction},
    phase_min_duration_months={phase_defaults.phase_min_duration_months},
    phase_smoothing_window={phase_defaults.phase_smoothing_window},
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
    phase_stability_replicates: int = 50,
    phase_stability_max_cycles: int = 200,
) -> None:
    """Run evaluation over the untouched validation partition under frozen defaults."""
    from hydroseason._scientific_defaults import (
        CALIBRATION_FINGERPRINT,
        CALIBRATION_VERSION,
        EVIDENCE_DEFAULTS,
        PHASE_DEFAULTS,
        RECOVERABILITY_DEFAULTS,
    )

    worker_count = workers if workers is not None else min(os.cpu_count() or 4, 16)
    started = time.perf_counter()
    peak_rss_mb = _rss_tree_mb()
    arg_list = [(seed, "validation") for seed in seeds]
    if worker_count == 1:
        evidence_cache = build_evidence_cache(seeds, partition="validation")
        phase_cache = build_phase_cache(seeds, partition="validation")
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            evidence_rows = list(
                executor.map(_worker_evidence, arg_list, chunksize=25)
            )
            peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
        evidence_cache = pd.DataFrame(evidence_rows)
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            phase_results = list(executor.map(_worker_phase, arg_list, chunksize=25))
            peak_rss_mb = max(peak_rss_mb, _rss_tree_mb())
        phase_cache = tuple(cycle for result in phase_results for cycle in result)

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
            evidence_thresholds=EVIDENCE_DEFAULTS,
            recoverability_thresholds=RECOVERABILITY_DEFAULTS,
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
        phase_cache=phase_cache,
        seeds=seeds,
        calibration_version=CALIBRATION_VERSION,
        calibration_fingerprint=CALIBRATION_FINGERPRINT,
        evidence_thresholds=EVIDENCE_DEFAULTS,
        recoverability_thresholds=RECOVERABILITY_DEFAULTS,
        phase_thresholds=PHASE_DEFAULTS,
        runtime_metrics=runtime_metrics,
        quality_policy_sensitivity=policy_metrics,
        phase_stability_replicates=phase_stability_replicates,
        phase_stability_max_cycles=phase_stability_max_cycles,
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


if __name__ == "__main__":
    from hydroseason._synthetic import VALIDATION_SEEDS

    parser = argparse.ArgumentParser(description="Run calibration/validation workflow")
    parser.add_argument("--partition", default="calibration", choices=["calibration", "validation"])
    parser.add_argument("--out-report", default=None)
    parser.add_argument("--out-module", default="hydroseason/_scientific_defaults.py")
    parser.add_argument("--num-seeds", type=int, default=None)
    args = parser.parse_args()

    if args.partition == "validation":
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
