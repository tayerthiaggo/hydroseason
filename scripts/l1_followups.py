"""L1 follow-ups B1 and D1: measurements on the L1 corpus, not pre-registered tests.

B1  Does a misdated trough boundary change what the condition baseline reads?
    The baseline ranks each cycle's ``peak_extent_pct`` and ``trough_extent_pct``
    against the baseline-eligible cycles, and eligibility requires aggregate
    ``timing_status == "point"``. B1 measures (a) how far the reported trough level
    sits from the true dry level for correctly and wrongly dated boundaries, and
    (b) how often the peak (recharge) condition label matches the known truth under
    three eligibility rules: today's (E0, ``point`` only), any dated status (E1) and
    no timing requirement (E2).
D1  Why did the boundary step pass over a lower month just after a missed
    ``point`` trough? Each case is matched against the diagnostic columns the
    library already reports.

Stages:

    run      rerun the current library on the L1 seasonal records, keeping every
             cycle column B1 and D1 need, plus condition labels under E0, E1, E2
    analyse  write docs/handoff/2026-11-03-l1-followups-results.json

The L1 corpus, plan and script are read, never changed. The library is not modified.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_gates as g2  # noqa: E402
import known_truth_labels as l1  # noqa: E402

g1 = g2.g1
OUT = g1.DATA / "intermediate" / "hydroseason_l1_followups"
RESULTS = g1.HANDOFF / "2026-11-03-l1-followups-results.json"
DATED = {"point", "interval", "broad"}
LABELS = ("low", "typical", "high")
MONTH_COLUMNS = ("trough_month", "peak_month", "raw_trough_month", "low_run_start_month", "low_run_end_month",
                 "pass1_trough_month", "trough_interval_start", "trough_interval_end")
VALUE_COLUMNS = ("hy_year", "status", "status_reason", "boundary_status", "peak_quality", "timing_status",
                 "trough_timing_status", "peak_timing_status", "trough_extent_pct", "trough_invalid_pct",
                 "peak_extent_pct", "detectability_floor_pp", "amplitude_to_floor_ratio", "raw_trough_extent_pct",
                 "window_status", "selection_status", "trough_search_radius_used", "boundary_at_search_edge",
                 "boundary_search_edge_side", "outside_window_observed", "outside_window_lower", "retry_outcome",
                 "pass1_trough_timing_status", "trough_refinement_status", "trough_refinement_reason",
                 "trough_refinement_applied")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "followups.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _conditions(hy: pd.DataFrame, state) -> dict:
    """Condition labels under E0, E1 and E2, called exactly as the library calls them."""
    from hydroseason._condition import classify_annual_surface_water_condition

    cfg = state.config
    low_variability = False if cfg.expected_trough_month is not None else state.pattern.pattern == "low_variability"
    noise = hy["noise_floor_pp"].iloc[0] if "noise_floor_pp" in hy.columns else None
    noise = None if noise is None or pd.isna(noise) else float(noise)
    variants = {"E0": hy.copy(), "E1": hy.copy(), "E2": hy.drop(columns=["timing_status"])}
    variants["E1"]["timing_status"] = np.where(hy["timing_status"].isin(DATED), "point", hy["timing_status"])
    out = {}
    for name, frame in variants.items():
        result = classify_annual_surface_water_condition(
            frame, reference="full_record", min_baseline_cycles=cfg.min_baseline_cycles,
            low_percentile=cfg.low_percentile, high_percentile=cfg.high_percentile,
            low_variability=low_variability, noise_pp=noise,
        ).set_index("hy_year")
        out[name] = {int(year): {"eligible": bool(row["baseline_eligible"]), "recharge": row["recharge_condition"],
                                 "refuge": row["refuge_condition"]}
                     for year, row in result.iterrows()}
    return out


def _run(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    key, rows = payload
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]
    started = time.perf_counter()
    record = {"key": key}
    try:
        analysis = analyze_catchment(frame[["n_water", "n_valid", "n_invalid", "n_aoi"]],
                                     phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    cycles = []
    for _, row in hy.iterrows():
        cycle = {c: g1.month_index(row.get(c)) for c in MONTH_COLUMNS}
        cycle.update({c: row.get(c) for c in VALUE_COLUMNS})
        cycle.update({"baseline_eligible": row.get("baseline_eligible"), "recharge": row.get("recharge_condition"),
                      "refuge": row.get("refuge_condition")})
        cycles.append(cycle)
    conditions, config = {}, {}
    if analysis.state is not None and len(hy):
        conditions = _conditions(hy, analysis.state)
        cfg = analysis.state.config
        config = {"expected_trough_month": cfg.expected_trough_month, "max_invalid_pct": cfg.max_invalid_pct,
                  "trough_search_radius_months": cfg.trough_search_radius_months,
                  "min_baseline_cycles": cfg.min_baseline_cycles}
    record.update(route=analysis.route, error=None, cycles=cycles, conditions=conditions, config=config,
                  seconds=round(time.perf_counter() - started, 2))
    return record


def stage_run(workers: int) -> None:
    receipt = json.loads(l1.RECEIPT.read_text(encoding="utf-8"))
    records = g2.read_corpus(l1.OUT / "corpus.jsonl.gz")
    if g2.corpus_digest(records) != receipt["corpus_sha256"]:
        raise SystemExit("L1 corpus does not match its receipt")
    seasonal = [r for r in records if r["kind"] == "seasonal"]
    sink = OUT / "runs.jsonl"
    done = set()
    if sink.exists():
        done = {json.loads(x)["key"] for x in sink.read_text(encoding="utf-8").splitlines() if x}
    payloads = [(r["key"], r["rows"]) for r in seasonal if r["key"] not in done]
    log(f"run: {len(payloads)} of {len(seasonal)} seasonal L1 records, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 100 == 0 or n == len(futures):
                log(f"run: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- truth


def truth_parameters(record: dict) -> dict:
    """Redraw the generator's hidden parameters in its own order and check them against the corpus."""
    if record["arm"] == "S":
        rng = np.random.default_rng([record["seed"], 0x47320001])
        n_aoi = int(round(10 ** rng.uniform(2, 5)))
        peak = 10 ** rng.uniform(-2.5, -0.5)
        low = peak * rng.uniform(0, 0.8)
        k = 10 ** rng.uniform(np.log10(0.5), np.log10(30))
        m = int(rng.integers(1, 13))
        year_factor = np.exp(rng.normal(0, 0.25, size=30))
        assert n_aoi == record["n_aoi"] and abs(k - record["k"]) < 1e-9 and m == record["trough_month"]
        return {"low_pp": 100.0 * low, "year_factor": year_factor}
    rng = np.random.default_rng([record["seed"], 0x47320002])
    m = int(rng.integers(1, 13))
    k = 10 ** rng.uniform(np.log10(0.5), np.log10(30))
    year_factor = np.exp(rng.normal(0, 0.25, size=60))
    assert abs(k - record["k"]) < 1e-9 and m == record["trough_month"]
    return {"low_pp": None, "year_factor": year_factor}


def nearest(index: int, months: set[int]) -> int:
    return min((index + o for o in range(-6, 7) if (index + o) % 12 + 1 in months), key=lambda i: (abs(i - index), i))


def truth_months(record: dict) -> set[int]:
    m = record["trough_month"]
    return {m, m % 12 + 1} if record["shape"] == "sine" else {m}


def series(record: dict) -> tuple[dict, dict]:
    rows = record["rows"]
    idx = [g1.month_index(d) for d in rows["date"]]
    ext = {i: (100.0 * w / v if v else np.nan) for i, w, v in zip(idx, rows["n_water"], rows["n_valid"])}
    invalid = {i: 100.0 * (a - v) / a for i, v, a in zip(idx, rows["n_valid"], rows["n_aoi"])}
    return ext, invalid


def truth_label(value: float, reference: np.ndarray, low: float = 20.0, high: float = 80.0) -> str:
    pct = 100.0 * (np.sum(reference < value) + 0.5 * np.sum(reference == value)) / len(reference)
    return "low" if pct <= low else "high" if pct >= high else "typical"


# ---------------------------------------------------------------- analysis


def _share(k: int, n: int) -> dict:
    return {"n": int(n), "k": int(k), "share": (k / n) if n else None}


def b1(records: dict, runs: dict) -> dict:
    level_rows, label_rows, record_rows = [], [], []
    for key, run in runs.items():
        rec = records[key]
        if run["route"] != "per_year_detection" or not run["cycles"]:
            continue
        truth = truth_parameters(rec)
        ext, _ = series(rec)
        months = truth_months(rec)
        idx = sorted(ext)
        m = rec["trough_month"]
        first_cycle = (idx[0] - (m - 1)) // 12
        n_cycles = (idx[-1] - (m - 1)) // 12 - first_cycle + 1
        offset = 6 if rec["shape"] == "sine" else 2  # true peak month after the trough
        inside = [c for c in range(n_cycles) if idx[0] <= (first_cycle + c) * 12 + m - 1 + offset <= idx[-1]]
        reference = truth["year_factor"][inside]
        for variant, years in run["conditions"].items():
            record_rows.append({"key": key, "arm": rec["arm"], "variant": variant,
                                "eligible": sum(v["eligible"] for v in years.values()),
                                "labelled": any(v["recharge"] in LABELS for v in years.values())})
        for cycle in run["cycles"]:
            t = cycle["trough_month"]
            if t is not None and cycle["trough_extent_pct"] is not None and cycle["detectability_floor_pp"]:
                star = nearest(t, months)
                floor = cycle["detectability_floor_pp"]
                level_rows.append({
                    "arm": rec["arm"], "shape": rec["shape"], "correct": abs(t - star) <= 1,
                    "eligible_e0": bool(cycle["baseline_eligible"]),
                    "vs_true_month": (cycle["trough_extent_pct"] - ext.get(star, np.nan)) / floor,
                    "vs_true_level": ((cycle["trough_extent_pct"] - truth["low_pp"]) / floor
                                      if truth["low_pp"] is not None else np.nan),
                })
            p = cycle["peak_month"]
            if p is None:
                continue
            c = (p - (m - 1)) // 12 - first_cycle
            if c not in inside:
                continue
            want = truth_label(truth["year_factor"][c], reference)
            got = {variant: years.get(str(cycle["hy_year"]), {}).get("recharge")
                   for variant, years in run["conditions"].items()}
            for variant, label in got.items():
                label_rows.append({"arm": rec["arm"], "shape": rec["shape"], "variant": variant,
                                   "labelled": label in LABELS, "agree": label == want, "want": want,
                                   "gross": {label, want} == {"low", "high"},
                                   "paired": got.get("E0") in LABELS and got.get("E1") in LABELS})
    level, labels, recs = pd.DataFrame(level_rows), pd.DataFrame(label_rows), pd.DataFrame(record_rows)
    out: dict = {"level": {}, "recharge": {}, "records_with_labels": {}}
    for arm in ("S", "I"):
        for shape in ("sine", "pulse", "all"):
            sub = level[(level["arm"] == arm) & ((level["shape"] == shape) | (shape == "all"))]
            for group, rows in (("correct", sub[sub["correct"]]), ("miss", sub[~sub["correct"]]),
                                ("miss_eligible_e0", sub[~sub["correct"] & sub["eligible_e0"]]),
                                ("correct_eligible_e0", sub[sub["correct"] & sub["eligible_e0"]])):
                entry = {"n": int(len(rows))}
                for col in ("vs_true_month", "vs_true_level"):
                    vals = rows[col].dropna().to_numpy(float)
                    if len(vals):
                        entry[col] = {"median": float(np.median(vals)), "median_abs": float(np.median(np.abs(vals))),
                                      "share_abs_over_1": float(np.mean(np.abs(vals) > 1))}
                out["level"][f"{arm}|{shape}|{group}"] = entry
        for variant in ("E0", "E1", "E2"):
            sub = labels[(labels["arm"] == arm) & (labels["variant"] == variant)]
            lab = sub[sub["labelled"]]
            out["recharge"][f"{arm}|{variant}"] = {
                "cycles_with_true_peak": int(len(sub)),
                "labelled": _share(int(sub["labelled"].sum()), len(sub)),
                "agree_among_labelled": _share(int(lab["agree"].sum()), len(lab)),
                "gross_among_labelled": _share(int(lab["gross"].sum()), len(lab)),
            }
            paired = sub[sub["paired"]]
            out["recharge"][f"{arm}|{variant}"]["agree_on_cycles_labelled_under_e0_and_e1"] = _share(
                int(paired["agree"].sum()), len(paired))
            if variant == "E1":
                mix = lab["want"].value_counts(normalize=True)
                out["recharge"][f"{arm}|chance_agreement_e1"] = float((mix ** 2).sum())
            r = recs[(recs["arm"] == arm) & (recs["variant"] == variant)]
            out["records_with_labels"][f"{arm}|{variant}"] = {
                "records": int(len(r)), "with_labels": _share(int(r["labelled"].sum()), len(r)),
                "median_eligible_cycles": float(r["eligible"].median()) if len(r) else None,
            }
    return out


def quality_screen(records: dict, runs: dict) -> dict:
    """Where the trough selection moved off the raw minimum: is the selected or the raw month right?"""
    rows = []
    for key, run in runs.items():
        rec = records[key]
        if run["route"] != "per_year_detection":
            continue
        months = truth_months(rec)
        for cycle in run["cycles"]:
            t, raw = cycle["trough_month"], cycle["raw_trough_month"]
            if t is None or raw is None or raw == t:
                continue
            rows.append({"arm": rec["arm"], "status": cycle["selection_status"],
                         "selected_ok": abs(t - nearest(t, months)) <= 1,
                         "raw_ok": abs(raw - nearest(raw, months)) <= 1})
    frame = pd.DataFrame(rows)
    out = {}
    for (arm, status), g in frame.groupby(["arm", "status"]):
        out[f"{arm}|{status}"] = {"cycles": int(len(g)), "selected_correct": int(g["selected_ok"].sum()),
                                  "raw_correct": int(g["raw_ok"].sum())}
    return out


def d1(records: dict, runs: dict) -> dict:
    cases = []
    for key, run in runs.items():
        rec = records[key]
        if run["route"] != "per_year_detection":
            continue
        ext, invalid = series(rec)
        months = truth_months(rec)
        cfg = run["config"]
        for cycle in run["cycles"]:
            t = cycle["trough_month"]
            if t is None or cycle["trough_timing_status"] != "point" or abs(t - nearest(t, months)) <= 1:
                continue
            lower = [t + j for j in (1, 2, 3) if not np.isnan(ext.get(t + j, np.nan)) and ext[t + j] < ext[t]]
            if not lower:
                continue
            first = lower[0]
            expected = nearest(t, {cfg["expected_trough_month"]}) if cfg.get("expected_trough_month") else None
            radius = cycle["trough_search_radius_used"]
            flags = {
                "outside_search_window": (expected is not None and radius is not None and first > expected + radius),
                "boundary_at_search_edge": bool(cycle["boundary_at_search_edge"]),
                "outside_window_lower_flag": bool(cycle["outside_window_lower"]),
                "lower_month_invalid_over_max": invalid.get(first, 0.0) > cfg["max_invalid_pct"],
                "refinement_moved_earlier": (cycle["pass1_trough_month"] is not None
                                             and cycle["pass1_trough_month"] > t),
                "raw_minimum_not_selected": (cycle["raw_trough_month"] is not None and cycle["raw_trough_month"] != t),
            }
            cases.append({"arm": rec["arm"], "shape": rec["shape"], **flags,
                          "lower_by_floors": (ext[t] - ext[first]) / cycle["detectability_floor_pp"]})
    frame = pd.DataFrame(cases)
    if frame.empty:
        return {}
    order = ["outside_search_window", "refinement_moved_earlier", "raw_minimum_not_selected",
             "lower_month_invalid_over_max"]
    out: dict = {}
    for arm in ("S", "I"):
        for shape in ("sine", "pulse", "all"):
            sub = frame[(frame["arm"] == arm) & ((frame["shape"] == shape) | (shape == "all"))]
            entry = {"cases": int(len(sub))}
            for flag in [*order, "boundary_at_search_edge", "outside_window_lower_flag"]:
                entry[flag] = int(sub[flag].sum())
            first_reason = sub[order].idxmax(axis=1).where(sub[order].any(axis=1), "none_of_these")
            entry["first_reason"] = {k: int(v) for k, v in first_reason.value_counts().items()}
            entry["lower_by_floors_median"] = float(sub["lower_by_floors"].median()) if len(sub) else None
            out[f"{arm}|{shape}"] = entry
    return out


def stage_analyse() -> None:
    records = {r["key"]: r for r in g2.read_corpus(l1.OUT / "corpus.jsonl.gz") if r["kind"] == "seasonal"}
    runs = {r["key"]: r for r in (json.loads(x) for x in (OUT / "runs.jsonl").read_text(encoding="utf-8").splitlines() if x)}
    e0_mismatch = 0
    for run in runs.values():
        for cycle in run["cycles"]:
            got = run["conditions"].get("E0", {}).get(str(cycle["hy_year"]), {})
            if got and (got["recharge"], got["refuge"], got["eligible"]) != (
                    cycle["recharge"], cycle["refuge"], bool(cycle["baseline_eligible"])):
                e0_mismatch += 1
    result = {
        "l1_receipt_sha256_lf": g1.sha256_lf(l1.RECEIPT),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "records": len(runs),
        "errors": sum(r["error"] is not None for r in runs.values()),
        "routes": pd.Series([r["route"] for r in runs.values()]).value_counts().to_dict(),
        "e0_reproduces_library_labels": e0_mismatch == 0,
        "e0_mismatched_cycles": e0_mismatch,
        "b1": b1(records, runs),
        "d1": d1(records, runs),
        "d1_quality_screen": quality_screen(records, runs),
    }
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"analyse: {len(runs)} records, E0 mismatches {e0_mismatch}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["run", "analyse"])
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    stage_run(args.workers) if args.stage == "run" else stage_analyse()


if __name__ == "__main__":
    main()
