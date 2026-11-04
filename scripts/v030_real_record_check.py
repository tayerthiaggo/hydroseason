"""Real-record check of hydroseason-v0.3.0 against the stored 0.2.0 runs.

Step 4 of the 0.3.0 implementation checks (docs/handoff/2026-11-04-v0.3.0-proposal.md):
rerun the real-record impact records with the new library, confirm the label/date
mismatch is gone, and confirm that only the columns changes B and C may touch differ.
The frozen scripts/real_record_impact.py and its results are read, never rewritten.

Stages:
  run      rerun every real-record impact record (G1 windows, spatial-unit-study units)
           with the importable HydroSeason, which must be hydroseason-v0.3.0
  analyse  compare with the stored 0.2.0 runs; writes
           docs/handoff/2026-11-04-v0.3.0-real-record-check.json

    PYTHONPATH=<0.3.0 checkout> python scripts/v030_real_record_check.py run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402
import l1_followups as fu  # noqa: E402
import real_record_impact as rri  # noqa: E402

OUT = g1.DATA / "intermediate" / "hydroseason_v030_real_record_check"
OLD_RUNS = rri.OUT / "runs.jsonl"
SIMULATION = g1.HANDOFF / "2026-11-04-v0.3.0-label-fix-impact.json"
RESULTS = g1.HANDOFF / "2026-11-04-v0.3.0-real-record-check.json"
DATED = {"point", "interval", "broad"}
# Cycle fields that changes B (trough label) and C (baseline) may alter.
CHANGEABLE = {"trough_timing_status", "timing_status", "trough_interval_start", "trough_interval_end",
              "baseline_eligible", "recharge", "refuge"}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "check.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _run(payload):
    from hydroseason._method_policy import CURRENT_METHOD_POLICY, method_policy_fingerprint

    record = fu._run(payload)
    record["policy_id"] = CURRENT_METHOD_POLICY.policy_id
    record["fingerprint"] = method_policy_fingerprint()
    return record


def stage_run(workers: int) -> None:
    from hydroseason._method_policy import CURRENT_METHOD_POLICY

    if CURRENT_METHOD_POLICY.policy_id != "hydroseason-v0.3.0":
        raise SystemExit(f"run with hydroseason-v0.3.0, not {CURRENT_METHOD_POLICY.policy_id}")
    sink = OUT / "runs.jsonl"
    done = set()
    if sink.exists():
        done = {json.loads(x)["key"] for x in sink.read_text(encoding="utf-8").splitlines() if x}
    frames = rri.series_frames()
    payloads = [(key, frame.to_dict(orient="list")) for key, frame in frames.items() if key not in done]
    log(f"run: {len(payloads)} of {len(frames)} records, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 200 == 0 or n == len(futures):
                log(f"run: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


def _load(path: Path) -> dict[str, dict]:
    return {r["key"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x)}


def _source(key: str, units: pd.DataFrame) -> str:
    source, scale = rri.scale_of(key, units)
    return f"{source}|{scale}"


def stage_analyse() -> None:
    old, new = _load(OLD_RUNS), _load(OUT / "runs.jsonl")
    if set(old) != set(new):
        raise SystemExit(f"run keys differ: {len(set(old) ^ set(new))}")
    units = pd.read_csv(rri.SU / "units.csv").set_index("unit_id")
    changed_fields: Counter = Counter()
    unexpected: Counter = Counter()
    transitions: Counter = Counter()
    status_kept = Counter()
    not_covering, dated = Counter(), Counter()
    route_changes, cycle_count_changes = [], []
    lost_baseline = Counter()
    for key in sorted(old):
        a, b = old[key], new[key]
        if a["route"] != b["route"]:
            route_changes.append([key, a["route"], b["route"]])
            continue
        if len(a["cycles"]) != len(b["cycles"]):
            cycle_count_changes.append(key)
            continue
        source = _source(key, units)
        for ca, cb in zip(a["cycles"], b["cycles"], strict=True):
            for field in ca:
                if ca[field] != cb.get(field):
                    changed_fields[field] += 1
                    if field not in CHANGEABLE:
                        unexpected[field] += 1
            if ca["trough_timing_status"] != cb["trough_timing_status"]:
                transitions[f"{source}|{ca['trough_timing_status']}->{cb['trough_timing_status']}"] += 1
                if cb["trough_timing_status"] == "unresolved":
                    status_kept[f"{source}|{cb['status']}|{cb['boundary_status']}"] += 1
            if cb["trough_timing_status"] in DATED and cb["trough_month"] is not None:
                dated[source] += 1
                start, end = cb["trough_interval_start"], cb["trough_interval_end"]
                if start is None or end is None or not start <= cb["trough_month"] <= end:
                    not_covering[source] += 1
        if b["route"] == "per_year_detection" and a["conditions"] and b["conditions"]:
            minimum = b["config"]["min_baseline_cycles"]
            e1_old = sum(bool(e["eligible"]) for e in a["conditions"]["E1"].values())
            now = sum(bool(e["eligible"]) for e in b["conditions"]["E0"].values())
            if e1_old >= minimum > now:
                lost_baseline[source] += 1
    policies = Counter((r.get("policy_id"), r.get("fingerprint")) for r in new.values())
    result = {
        "old_runs_sha256": g1.sha256_file(OLD_RUNS),
        "new_runs_sha256": g1.sha256_file(OUT / "runs.jsonl"),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "records": len(new),
        "policies": [[p, f, n] for (p, f), n in policies.items()],
        "errors": sorted(k for k, r in new.items() if r["error"] is not None),
        "route_changes": route_changes,
        "cycle_count_changes": cycle_count_changes,
        "changed_fields": dict(changed_fields),
        "unexpected_changed_fields": dict(unexpected),
        "trough_label_transitions": dict(sorted(transitions.items())),
        "widened_to_unresolved_status_kept": dict(status_kept),
        "dated_troughs": dict(dated),
        "dated_troughs_not_covering_boundary": dict(not_covering),
        "m2_mismatch_new": rri.mismatch(new, units, rri.series_frames()),
        "e0_mismatches_new": rri.e0_reproduces_library(new),
        "coverage_new": rri.coverage(new, units),
        "units_losing_e1_baseline": dict(lost_baseline),
        "case_study_tables_new": rri.case_study_tables(new, units),
        "simulation": json.loads(SIMULATION.read_text(encoding="utf-8"))["simulation"],
    }
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"analyse: {len(new)} records, route changes {len(route_changes)}, unexpected {dict(unexpected)}, "
        f"not covering {dict(not_covering)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=("run", "analyse"))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    stage_run(args.workers) if args.stage == "run" else stage_analyse()


if __name__ == "__main__":
    main()
