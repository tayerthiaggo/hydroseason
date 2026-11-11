"""L1: known-truth test of the trough timing labels.

Plan and decision rules: docs/handoff/2026-11-03-l1-timing-labels-plan.md.

Stages, in order:

    check     G2's noise-free construction records under every setting
    pilot     pilot records under the current setting and k3; run times and counts only
    freeze    build the main corpus and write the receipt before any outcome
    run       main records under every setting kept by the check
    evaluate  decision rules; writes the results JSON

Record generators and scoring helpers are imported unchanged from
scripts/known_truth_gates.py (G2), and through it scripts/gate_calibration.py (G1).
The only change to HydroSeason is made inside worker processes: the trough
tolerance passed to ``equivalent_extremum_dates`` in ``_timing_identifiability``
is multiplied by the setting's factor. The library on disk is not modified.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_gates as g2  # noqa: E402

g1 = g2.g1
REPO_ROOT = g1.REPO_ROOT
HANDOFF = g1.HANDOFF
PLAN = HANDOFF / "2026-11-03-l1-timing-labels-plan.md"
RECEIPT = HANDOFF / "2026-11-03-l1-timing-labels-receipt.json"
RESULTS = HANDOFF / "2026-11-03-l1-timing-labels-results.json"
OUT = g1.DATA / "intermediate" / "hydroseason_known_truth_labels"

SQRT2 = math.sqrt(2.0)
SETTINGS = {
    "current": 1.0,
    "k1": 1.0 * SQRT2,
    "k2": 1.6448536269514722 * SQRT2,
    "k3": 1.959963984540054 * SQRT2,
}
SELFTEST_VALUES = [0.0, 0.5, 1.2, 2.0, 2.5, 4.0]
SELFTEST_EXPECTED = {"current": 2, "k1": 3, "k2": 4, "k3": 5}
SEASONAL_SEEDS = range(200000, 200600)
NULL_SEEDS = range(210000, 210200)
INJECTION_SEEDS = range(220000, 220574)
INJECTIONS_PER_BACKGROUND = 2
PILOT_S_SEEDS = range(230000, 230060)
PILOT_I_SEEDS = range(231000, 231040)
CHECK_SEEDS_START = 900000  # G2's noise-free construction records
DATED = {"point", "interval", "broad"}
MIN_CASES = 100

_FACTOR = 1.0
_SELFTEST: dict = {}


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "l1.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# ---------------------------------------------------------------- worker


def _set_tolerance(factor: float) -> None:
    """Scale the trough (``kind="min"``) tolerance inside this worker process only."""
    global _FACTOR, _SELFTEST
    import hydroseason._timing_identifiability as timing

    original = timing.equivalent_extremum_dates
    if factor != 1.0:
        def scaled(values, *, kind, tolerance):
            return original(values, kind=kind, tolerance=tolerance * factor if kind == "min" else tolerance)

        timing.equivalent_extremum_dates = scaled
    _FACTOR = float(factor)
    probe = pd.Series(SELFTEST_VALUES, index=pd.date_range("2000-01-01", periods=len(SELFTEST_VALUES), freq="MS"))
    _SELFTEST = {
        "min": len(timing.equivalent_extremum_dates(probe, kind="min", tolerance=1.0)),
        "max": len(timing.equivalent_extremum_dates(probe, kind="max", tolerance=1.0)),
    }


def _month(row, column):
    """Month index (year * 12 + month - 1) of a date column, or None."""
    value = row.get(column)
    return None if value is None else g1.month_index(value)


def _run(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    key, rows = payload
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]
    started = time.perf_counter()
    record = {"key": key, "factor": _FACTOR, "selftest": _SELFTEST}
    try:
        analysis = analyze_catchment(frame[["n_water", "n_valid", "n_invalid", "n_aoi"]],
                                     phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    cycles = []
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    for _, row in hy.iterrows():
        cycles.append({
            "trough": _month(row, "trough_month"),
            "status": row.get("trough_timing_status"),
            "start": _month(row, "trough_interval_start"),
            "end": _month(row, "trough_interval_end"),
            "pass1_status": row.get("pass1_trough_timing_status"),
            "refinement": row.get("trough_refinement_status"),
            "ratio": row.get("amplitude_to_floor_ratio"),
            "peak_px": row.get("peak_n_water"),
            "cycle_status": row.get("status"),
            "boundary_status": row.get("boundary_status"),
            "peak_quality": row.get("peak_quality"),
            "timing_status": row.get("timing_status"),
        })
    record.update(route=analysis.route, error=None, cycles=cycles,
                  fingerprint=analysis.method_policy_fingerprint,
                  seconds=round(time.perf_counter() - started, 2))
    return record


def run_records(records: list[dict], setting: str, sink: Path, workers: int) -> None:
    done = set()
    if sink.exists():
        done = {json.loads(line)["key"] for line in sink.read_text(encoding="utf-8").splitlines() if line}
    payloads = [(r["key"], r["rows"]) for r in records if r["key"] not in done]
    log(f"run {sink.name}: {len(payloads)} records, setting {setting} (factor {SETTINGS[setting]:.4f}), {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=_set_tolerance, initargs=(SETTINGS[setting],)) as pool, \
            open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 100 == 0 or n == len(futures):
                log(f"run {sink.name}: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- scoring


def signed_error(trough: int, trough_month: int) -> int:
    after = (trough - (trough_month - 1)) % 12
    return after if after <= 6 else after - 12


def covers_truth(start: int | None, end: int | None, trough_month: int, shape: str) -> bool | None:
    if start is None or end is None:
        return None
    return any(g2.truth_error(t, trough_month, shape) == 0 for t in range(start - 1, end + 2))


def cycle_table(runs: dict[str, dict], meta: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for key, run in runs.items():
        info = meta[key]
        seasonal = info["kind"] == "seasonal"
        for cycle in run["cycles"]:
            has_trough = cycle["trough"] is not None
            correct = (seasonal and has_trough
                       and g2.truth_error(cycle["trough"], info["trough_month"], info["shape"]) <= 1)
            rows.append({
                "key": key, "arm": info["arm"], "kind": info["kind"], "shape": info["shape"],
                "status": cycle["status"] or "none", "has_trough": has_trough,
                "dated": has_trough and cycle["status"] in DATED,
                "correct": bool(correct),
                "exact": bool(seasonal and has_trough and g2.truth_error(cycle["trough"], info["trough_month"], info["shape"]) == 0),
                "signed": signed_error(cycle["trough"], info["trough_month"]) if seasonal and has_trough else None,
                "end_signed": (signed_error(cycle["end"], info["trough_month"])
                               if seasonal and cycle["end"] is not None else None),
                "covers": covers_truth(cycle["start"], cycle["end"], info["trough_month"], info["shape"]) if seasonal else None,
                "refined": cycle["refinement"] in ("confirmed", "provisional"),
                "baseline": (cycle["cycle_status"] == "complete" and cycle["boundary_status"] == "confirmed"
                             and cycle["peak_quality"] != "anomalous" and cycle["timing_status"] == "point"),
                "ratio": cycle["ratio"], "peak_px": cycle["peak_px"],
            })
    frame = pd.DataFrame(rows)
    for column in ("ratio", "peak_px"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def wilson_lower(k: int, n: int, z: float = 1.959964) -> float | None:
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    spread = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return float((centre - spread) / (1 + z * z / n))


def share(frame: pd.DataFrame, column: str) -> dict:
    n = len(frame)
    k = int(frame[column].sum()) if n else 0
    return {"n": n, "k": k, "share": (k / n) if n else None}


def point_safety(frame: pd.DataFrame) -> dict:
    points = frame[frame["dated"] & (frame["status"] == "point")]
    wrong = int((~points["correct"]).sum())
    return {"point_dates": len(points), "not_correct": wrong,
            "share": (wrong / len(points)) if len(points) else None,
            "wilson_lower": wilson_lower(wrong, len(points)), "wilson_upper": g2.wilson_upper(wrong, len(points)),
            "exact": int(points["exact"].sum())}


def reported(frame: pd.DataFrame, runs: dict, keys: list[str]) -> dict:
    """Every reported-only summary for one arm under one setting."""
    out: dict = {"labels": {}, "accuracy_by_label": {}, "point_by_ratio": {}, "interval_covers_truth": {},
                 "baseline": {}, "pulse_signed": {}, "pulse_end_signed": {}, "by_shape": {}}
    with_trough = frame[frame["has_trough"]]
    for shape in ("all", *g2.SHAPES):
        sub = with_trough if shape == "all" else with_trough[with_trough["shape"] == shape]
        out["labels"][shape] = {label: int((sub["status"] == label).sum())
                                for label in ("point", "interval", "broad", "unresolved", "none")}
        out["accuracy_by_label"][shape] = {label: share(sub[sub["status"] == label], "correct")
                                           for label in ("point", "interval", "broad", "unresolved")}
        out["accuracy_by_label"][shape]["all_boundaries"] = share(sub, "correct")
        out["by_shape"][shape] = point_safety(sub)
        widened = sub[sub["status"].isin(["interval", "broad"]) & sub["covers"].notna()]
        out["interval_covers_truth"][shape] = share(widened.assign(covers=widened["covers"].astype(bool)), "covers")
        out["baseline"][shape] = share(sub[sub["baseline"]], "correct")
    points = with_trough[with_trough["status"] == "point"]
    for low, high in [(3, 4), (4, 6), (6, 10), (10, np.inf)]:
        for shape in g2.SHAPES:
            band = points[(points["shape"] == shape) & (points["ratio"] >= low) & (points["ratio"] < high)]
            out["point_by_ratio"][f"{shape} [{low:g},{high:g})"] = {
                "n": len(band), "not_correct": int((~band["correct"]).sum()),
                "share": float((~band["correct"]).mean()) if len(band) else None}
    pulse = with_trough[with_trough["shape"] == "pulse"]
    out["pulse_signed"] = {str(k): int(v) for k, v in sorted(pulse["signed"].dropna().astype(int).value_counts().items())}
    out["pulse_end_signed"] = {str(k): int(v)
                               for k, v in sorted(pulse["end_signed"].dropna().astype(int).value_counts().items())}
    out["routed_per_year_detection"] = float(np.mean([runs[k]["route"] == "per_year_detection" for k in keys]))
    return out


# ---------------------------------------------------------------- records


def main_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [g2.synthetic_record(s, "seasonal", sources) for s in SEASONAL_SEEDS]
    nulls = list(NULL_SEEDS)
    records += [g2.synthetic_record(s, "flat", sources) for s in nulls[:100]]
    records += [g2.synthetic_record(s, "random_pulse", sources) for s in nulls[100:]]
    records += [g2.injection_record(s, bg[(s - INJECTION_SEEDS.start) // INJECTIONS_PER_BACKGROUND])
                for s in INJECTION_SEEDS]
    return records


def check_records() -> list[dict]:
    sources = g2.valid_sources()
    return [g2.synthetic_record(CHECK_SEEDS_START + i, "seasonal", sources, noise_free=True, trough_month=m, shape=shape)
            for i, (m, shape) in enumerate((m, s) for m in range(1, 13) for s in g2.SHAPES)]


def pilot_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [g2.synthetic_record(s, "seasonal", sources) for s in PILOT_S_SEEDS]
    records += [g2.injection_record(s, bg[(i * 7) % len(bg)]) for i, s in enumerate(PILOT_I_SEEDS)]
    return records


# ---------------------------------------------------------------- stages


def stage_check(workers: int) -> None:
    records = check_records()
    meta = {r["key"]: r for r in records}
    summary: dict = {}
    for setting in SETTINGS:
        sink = OUT / f"check_{setting}.jsonl"
        run_records(records, setting, sink, workers)
        runs = g1.load_runs(sink)
        per_shape = {}
        for shape in g2.SHAPES:
            total = at_truth = 0
            for key, run in runs.items():
                if meta[key]["shape"] != shape:
                    continue
                for cycle in run["cycles"][1:-1]:
                    total += 1
                    at_truth += int(cycle["trough"] is not None and g2.truth_error(
                        cycle["trough"], meta[key]["trough_month"], shape) == 0)
            per_shape[shape] = {"cycles": total, "at_truth": at_truth,
                                "share": (at_truth / total) if total else None}
        selftests = {json.dumps(r["selftest"], sort_keys=True) for r in runs.values()}
        kept = all(v["share"] is not None and v["share"] >= 0.95 for v in per_shape.values())
        summary[setting] = {"factor": SETTINGS[setting], "by_shape": per_shape, "kept": kept,
                            "selftests": sorted(selftests)}
        log(f"check {setting}: {per_shape}, kept={kept}, selftests={sorted(selftests)}")
    (OUT / "check.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def stage_pilot(workers: int) -> None:
    """Pilot: run times and counts only, never accuracy."""
    records = pilot_records()
    meta = {r["key"]: r for r in records}
    main_counts = {"S": len(SEASONAL_SEEDS), "I": len(INJECTION_SEEDS)}
    summary: dict = {}
    for setting in ("current", "k3"):
        sink = OUT / f"pilot_{setting}.jsonl"
        run_records(records, setting, sink, workers)
        runs = g1.load_runs(sink)
        frame = cycle_table(runs, meta)
        for arm in ("S", "I"):
            sub = frame[frame["arm"] == arm]
            n_records = sum(1 for k in runs if meta[k]["arm"] == arm)
            points = int((sub["dated"] & (sub["status"] == "point")).sum())
            summary[f"{setting}:{arm}"] = {
                "records": n_records,
                "median_seconds": float(np.median([r["seconds"] for k, r in runs.items() if meta[k]["arm"] == arm])),
                "dated": int(sub["dated"].sum()),
                "point_dates": points,
                "predicted_main_point_dates": points * main_counts[arm] / n_records,
            }
    (OUT / "pilot.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for key, value in summary.items():
        log(f"pilot {key}: {value}")


def stage_freeze() -> None:
    if RECEIPT.exists():
        raise SystemExit("receipt exists; the freeze is written once")
    import hydroseason
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as defaults

    check = json.loads((OUT / "check.json").read_text(encoding="utf-8"))
    records = main_records()
    g2.write_corpus(records, OUT / "corpus.jsonl.gz")
    receipt = {
        "plan": str(PLAN.relative_to(REPO_ROOT)).replace("\\", "/"),
        "plan_sha256_lf": g1.sha256_lf(PLAN),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "g2_script_sha256_lf": g1.sha256_lf(Path(g2.__file__)),
        "g1_script_sha256_lf": g1.sha256_lf(Path(g1.__file__)),
        "git_head": g1.git("rev-parse", "HEAD"),
        "git_branch": g1.git("branch", "--show-current"),
        "git_status_short": g1.git("status", "--short").splitlines(),
        "hydroseason_version": hydroseason.__version__,
        "library_gates": {"ratio": defaults.min_amplitude_to_floor_ratio, "peak_pixels": defaults.min_peak_water_pixels},
        "settings": SETTINGS,
        "settings_kept": [s for s, v in check.items() if v["kept"]],
        "corpus_records": len(records),
        "corpus_sha256": g2.corpus_digest(records),
        "check": check,
        "pilot": json.loads((OUT / "pilot.json").read_text(encoding="utf-8")),
        "frozen_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    RECEIPT.write_text(json.dumps(g1.clean(receipt), indent=2) + "\n", encoding="utf-8")
    log(f"freeze: plan {receipt['plan_sha256_lf']}, script {receipt['script_sha256_lf']}, "
        f"corpus {receipt['corpus_sha256']} ({len(records)} records), settings {receipt['settings_kept']}")


def stage_run(workers: int) -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    records = g2.read_corpus(OUT / "corpus.jsonl.gz")
    if g2.corpus_digest(records) != receipt["corpus_sha256"]:
        raise SystemExit("corpus does not match the receipt")
    for setting in receipt["settings_kept"]:
        run_records(records, setting, OUT / f"main_{setting}.jsonl", workers)


def stage_evaluate() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    records = g2.read_corpus(OUT / "corpus.jsonl.gz")
    meta = {r["key"]: {k: v for k, v in r.items() if k != "rows"} for r in records}
    settings = receipt["settings_kept"]
    if "current" not in settings:
        raise SystemExit("the current setting must be kept")
    runs = {s: g1.load_runs(OUT / f"main_{s}.jsonl") for s in settings}
    for setting, by_key in runs.items():
        if set(by_key) != set(meta):
            raise SystemExit(f"runs for {setting} are incomplete")
    tables = {s: cycle_table(runs[s], meta) for s in settings}
    results: dict = {
        "receipt_sha256_lf": g1.sha256_lf(RECEIPT),
        "errors": {s: sum(r["error"] is not None for r in runs[s].values()) for s in settings},
        "factors_read_back": {s: sorted({r["factor"] for r in runs[s].values()}) for s in settings},
        "selftests_read_back": {s: sorted({json.dumps(r["selftest"], sort_keys=True) for r in runs[s].values()})
                                for s in settings},
        "arms": {}, "settings": {}, "null": {},
    }
    keys = {arm: sorted(k for k, v in meta.items() if v["arm"] == arm and v["kind"] == "seasonal") for arm in ("S", "I")}
    current = {arm: tables["current"][(tables["current"]["arm"] == arm) & (tables["current"]["kind"] == "seasonal")]
               for arm in ("S", "I")}

    # C. Confirmation under the current setting.
    confirm = {}
    for arm in ("S", "I"):
        safety = point_safety(current[arm])
        confirm[arm] = {**safety, "evaluable": safety["point_dates"] >= MIN_CASES,
                        "holds": bool(safety["point_dates"] >= MIN_CASES and safety["wilson_lower"] > 0.05)}
        sub = current[arm][current[arm]["has_trough"]]
        results["arms"][arm] = {
            "label_source_current": {
                source: {label: share(sub[(sub["refined"] == refined) & (sub["status"] == label)], "correct")
                         for label in ("point", "interval", "broad")}
                for source, refined in (("refinement", True), ("pass_1", False))
            },
        }
    results["confirmation"] = {"arms": confirm, "confirmed": all(v["holds"] for v in confirm.values())}

    # Rules 1-3 for every kept setting other than the current one; reported items for all.
    passing = []
    for setting in settings:
        entry: dict = {"factor": SETTINGS[setting], "arms": {}}
        for arm in ("S", "I"):
            table = tables[setting]
            sub = table[(table["arm"] == arm) & (table["kind"] == "seasonal")]
            arm_entry: dict = {"reported": reported(sub, runs[setting], keys[arm])}
            if setting != "current":
                safety = point_safety(sub)
                rule_1 = {**safety, "evaluable": safety["point_dates"] >= MIN_CASES}
                rule_1["holds"] = bool(rule_1["evaluable"] and safety["wilson_upper"] <= 0.05)
                new, old = sub[sub["has_trough"]], current[arm][current[arm]["has_trough"]]
                a_new, a_old = share(new, "correct"), share(old, "correct")
                diff = (a_new["share"] - a_old["share"]) if a_new["n"] and a_old["n"] else None
                interval = (g2.bootstrap_difference(g2.per_key(new, new["has_trough"]),
                                                    g2.per_key(old, old["has_trough"]), keys[arm])
                            if diff is not None else [None, None])
                evaluable_2 = a_new["n"] >= MIN_CASES and a_old["n"] >= MIN_CASES
                rule_2 = {"setting": a_new, "current": a_old, "difference": diff, "ci95": interval,
                          "evaluable": evaluable_2,
                          "holds": bool(evaluable_2 and diff >= -0.02 and interval[0] >= -0.05)}
                routed_new = arm_entry["reported"]["routed_per_year_detection"]
                routed_old = float(np.mean([runs["current"][k]["route"] == "per_year_detection" for k in keys[arm]]))
                rule_3 = {"setting": routed_new, "current": routed_old, "difference": routed_new - routed_old,
                          "evaluable": len(keys[arm]) >= MIN_CASES,
                          "holds": bool(len(keys[arm]) >= MIN_CASES and routed_new - routed_old >= -0.02)}
                arm_entry.update(rule_1=rule_1, rule_2=rule_2, rule_3=rule_3)
            entry["arms"][arm] = arm_entry
        if setting != "current":
            entry["passes"] = all(entry["arms"][arm][f"rule_{n}"]["holds"] for arm in ("S", "I") for n in (1, 2, 3))
            if entry["passes"]:
                passing.append(setting)
        table = tables[setting]
        null = table[table["kind"].isin(["flat", "random_pulse"])]
        null_keys = sorted(k for k, v in meta.items() if v["kind"] in ("flat", "random_pulse"))
        results["null"][setting] = {
            "records": len(null_keys),
            "routed_per_year_detection": float(np.mean([runs[setting][k]["route"] == "per_year_detection"
                                                        for k in null_keys])),
            "point_trough_dates": int((null["dated"] & (null["status"] == "point")).sum()),
            "dated_trough_boundaries": int(null["dated"].sum()),
        }
        results["settings"][setting] = entry
    candidate = min(passing, key=lambda s: SETTINGS[s]) if passing else None
    results["passing_settings"] = passing
    results["candidate"] = candidate
    RESULTS.write_text(json.dumps(g1.clean(results), indent=2) + "\n", encoding="utf-8")
    log(f"evaluate: confirmed={results['confirmation']['confirmed']} passing={passing} candidate={candidate}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["check", "pilot", "freeze", "run", "evaluate"])
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    import hydroseason

    if Path(hydroseason.__file__).resolve().parent != (REPO_ROOT / "hydroseason").resolve():
        raise SystemExit(f"run with the repository's hydroseason, not {hydroseason.__file__}")
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "check":
        stage_check(args.workers)
    elif args.stage == "pilot":
        stage_pilot(args.workers)
    elif args.stage == "freeze":
        stage_freeze()
    elif args.stage == "run":
        stage_run(args.workers)
    else:
        stage_evaluate()


if __name__ == "__main__":
    main()
