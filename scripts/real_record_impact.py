"""Real-record impact of two hydroseason-v0.3.0 candidates (measurement, not a test).

M1: the condition baseline's timing requirement, today's `point` only (E0) against any dated status (E1).
M2: how often a `point` trough label belongs to a month other than the reported boundary (`trough_date`).

Plan: docs/handoff/2026-11-03-real-record-impact-plan.md. The library is not changed.

Stages:
  run      run the current library on the G1 windows (both pixel halves) and the spatial-unit-study units
  analyse  write docs/handoff/2026-11-03-real-record-impact-results.json
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
import gate_calibration as g1  # noqa: E402
import l1_followups as fu  # noqa: E402

PLAN = g1.HANDOFF / "2026-11-03-real-record-impact-plan.md"
RESULTS = g1.HANDOFF / "2026-11-03-real-record-impact-results.json"
OUT = g1.DATA / "intermediate" / "hydroseason_real_record_impact"
SU = g1.DATA / "intermediate" / "hydroseason_spatial_unit_study"
RULES = ("E0", "E1", "E2")
LABELS = set(fu.LABELS)
KINDS = ("recharge", "refuge")
BOOT, SEED = 2000, 0
CLOUDY = 20.0


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "impact.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# ---------------------------------------------------------------- records


def g1_windows() -> list[str]:
    sites = pd.read_csv(g1.OUT / "sites.csv")
    return sorted(sites.loc[sites["exists"], "window"])


def series_frames() -> dict[str, pd.DataFrame]:
    """Every record's monthly counts, keyed `g1|window|unit|half` or `su|unit_id`."""
    frames = {}
    for window in g1_windows():
        series = pd.read_csv(g1.OUT / "series" / f"{window}.csv.gz")
        for (unit, half), group in series.groupby(["unit", "half"]):
            frames[f"g1|{window}|{unit}|{half}"] = group[["date", "n_water", "n_valid", "n_aoi"]].reset_index(drop=True)
    for path in sorted((SU / "series").glob("*.csv.gz")):
        series = pd.read_csv(path)
        for unit_id, group in series.groupby("unit_id"):
            frames[f"su|{unit_id}"] = group[["date", "n_water", "n_valid", "n_aoi"]].reset_index(drop=True)
    return frames


def g1_series_match_receipt() -> bool:
    receipt = json.loads(g1.RECEIPT.read_text(encoding="utf-8"))
    expected = receipt["series_sha256"]
    return all(g1.sha256_file(g1.OUT / "series" / f"{w}.csv.gz") == expected.get(f"{w}.csv.gz") for w in g1_windows())


def stage_run(workers: int, limit: int | None = None) -> None:
    sink = OUT / "runs.jsonl"
    done = set()
    if sink.exists():
        done = {json.loads(x)["key"] for x in sink.read_text(encoding="utf-8").splitlines() if x}
    frames = series_frames()
    payloads = [(key, frame.to_dict(orient="list")) for key, frame in frames.items() if key not in done][:limit]
    log(f"run: {len(payloads)} of {len(frames)} records, {workers} workers, plan {g1.sha256_lf(PLAN)}")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(fu._run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 200 == 0 or n == len(futures):
                log(f"run: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- helpers


def load_runs() -> dict[str, dict]:
    return {r["key"]: r for r in (json.loads(x) for x in (OUT / "runs.jsonl").read_text(encoding="utf-8").splitlines() if x)}


def scale_of(key: str, units: pd.DataFrame) -> tuple[str, str]:
    parts = key.split("|")
    if parts[0] == "g1":
        return "g1", "core" if parts[2] == "core" else "quadrant"
    return "su", str(units.loc[parts[1], "scheme"])


def label_of(run: dict, rule: str, year, kind: str):
    entry = run["conditions"].get(rule, {}).get(str(int(year))) if year is not None and not pd.isna(year) else None
    value = entry.get(kind) if entry else None
    return value if value in LABELS else None


def share(k: int, n: int) -> dict:
    return {"n": n, "k": k, "share": (k / n) if n else None}


# ---------------------------------------------------------------- M1


def coverage(runs: dict, units: pd.DataFrame) -> dict:
    rows = []
    for key, run in runs.items():
        if run["route"] != "per_year_detection" or not run["conditions"]:
            continue
        source, scale = scale_of(key, units)
        min_cycles = run["config"]["min_baseline_cycles"]
        for rule in RULES:
            entries = run["conditions"][rule].values()
            eligible = sum(bool(e["eligible"]) for e in entries)
            rows.append({"source": source, "scale": scale, "rule": rule, "key": key, "cycles": len(run["cycles"]),
                         "eligible": eligible, "has_baseline": eligible >= min_cycles,
                         "recharge": sum(e["recharge"] in LABELS for e in entries),
                         "refuge": sum(e["refuge"] in LABELS for e in entries)})
    frame = pd.DataFrame(rows)
    out = {}
    for (source, scale, rule), g in frame.groupby(["source", "scale", "rule"]):
        out[f"{source}|{scale}|{rule}"] = {
            "units": len(g), "units_with_baseline": share(int(g["has_baseline"].sum()), len(g)),
            "cycles": int(g["cycles"].sum()),
            "recharge_labelled": share(int(g["recharge"].sum()), int(g["cycles"].sum())),
            "refuge_labelled": share(int(g["refuge"].sum()), int(g["cycles"].sum())),
            "median_eligible_per_unit": float(g["eligible"].median()),
        }
    return out


def matched_pairs(runs: dict) -> pd.DataFrame:
    """Matched cycle pairs between the two pixel halves of a G1 unit, with each rule's labels."""
    by_unit: dict[tuple[str, str], dict[str, dict]] = {}
    for key, run in runs.items():
        parts = key.split("|")
        if parts[0] == "g1" and run["route"] == "per_year_detection" and run["conditions"]:
            by_unit.setdefault((parts[1], parts[2]), {})[parts[3]] = run
    rows = []
    for (window, unit), halves in by_unit.items():
        if set(halves) != {"A", "B"}:
            continue
        a, b = halves["A"], halves["B"]
        candidates = sorted(
            (abs(x["peak_month"] - y["peak_month"]), i, j)
            for i, x in enumerate(a["cycles"]) for j, y in enumerate(b["cycles"])
            if x["peak_month"] is not None and y["peak_month"] is not None
            and abs(x["peak_month"] - y["peak_month"]) <= g1.MATCH_MONTHS)
        used_a, used_b = set(), set()
        for _, i, j in candidates:
            if i in used_a or j in used_b:
                continue
            used_a.add(i)
            used_b.add(j)
            ca, cb = a["cycles"][i], b["cycles"][j]
            row = {"window": window, "unit": unit,
                   "point_both": ca["timing_status"] == "point" and cb["timing_status"] == "point"}
            for rule in RULES:
                for kind in KINDS:
                    row[f"{rule}|{kind}|A"] = label_of(a, rule, ca["hy_year"], kind)
                    row[f"{rule}|{kind}|B"] = label_of(b, rule, cb["hy_year"], kind)
            rows.append(row)
    return pd.DataFrame(rows)


def _agreement(frame: pd.DataFrame, rule: str, kind: str, mask: pd.Series) -> tuple[int, int]:
    sub = frame[mask]
    return int((sub[f"{rule}|{kind}|A"] == sub[f"{rule}|{kind}|B"]).sum()), len(sub)


def _labelled(frame: pd.DataFrame, rule: str, kind: str) -> pd.Series:
    return frame[f"{rule}|{kind}|A"].notna() & frame[f"{rule}|{kind}|B"].notna()


def _chance(frame: pd.DataFrame, rule: str, kind: str, mask: pd.Series) -> float | None:
    sub = frame[mask]
    if not len(sub):
        return None
    pa = sub[f"{rule}|{kind}|A"].value_counts(normalize=True)
    pb = sub[f"{rule}|{kind}|B"].value_counts(normalize=True)
    return float(sum(pa.get(label, 0.0) * pb.get(label, 0.0) for label in LABELS))


def _reading(ci: list | None) -> str:
    if ci is None:
        return "inconclusive"
    if ci[1] < -0.05:
        return "evidence_of_a_cost"
    if ci[0] >= -0.05:
        return "no_evidence_of_a_cost"
    return "inconclusive"


def _difference(pairs: pd.DataFrame, windows: list, draws: list, kind: str,
                base: tuple[str, pd.Series], other: tuple[str, pd.Series]) -> dict:
    """Agreement on `other` pairs minus agreement on `base` pairs, with a bootstrap over windows."""
    (base_rule, base_mask), (other_rule, other_mask) = base, other
    per_window = {}
    for window, g in pairs.groupby("window"):
        kb, nb = _agreement(g, base_rule, kind, base_mask.loc[g.index])
        ko, no = _agreement(g, other_rule, kind, other_mask.loc[g.index])
        per_window[window] = (kb, nb, ko, no)
    table = np.array([per_window[w] for w in windows], dtype=float)
    diffs = []
    for idx in draws:
        s = table[idx].sum(axis=0)
        if s[1] and s[3]:
            diffs.append(s[2] / s[3] - s[0] / s[1])
    total = table.sum(axis=0)
    point = (total[2] / total[3] - total[0] / total[1]) if total[1] and total[3] else None
    ci = [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))] if diffs else None
    return {"base_pairs": int(total[1]), "other_pairs": int(total[3]), "difference": point, "ci95": ci,
            "valid_draws": len(diffs), "reading": _reading(ci)}


def _kappa(a: np.ndarray, b: np.ndarray) -> float | None:
    if not len(a):
        return None
    observed = float(np.mean(a == b))
    expected = float(sum(np.mean(a == label) * np.mean(b == label) for label in LABELS))
    return (observed - expected) / (1 - expected) if expected < 1 else None


def reproducibility(pairs: pd.DataFrame) -> dict:
    out = {"matched_pairs": len(pairs), "windows": int(pairs["window"].nunique()) if len(pairs) else 0}
    windows = sorted(pairs["window"].unique())
    rng = np.random.default_rng(SEED)
    draws = [rng.choice(len(windows), size=len(windows), replace=True) for _ in range(BOOT)]
    for kind in KINDS:
        e0, e1 = _labelled(pairs, "E0", kind), _labelled(pairs, "E1", kind)
        added = e1 & ~e0
        point, other = e1 & pairs["point_both"], e1 & ~pairs["point_both"]
        entry = {}
        for name, rule, mask in (("E0", "E0", e0), ("E1", "E1", e1), ("E1_added", "E1", added),
                                 ("E1_point_both", "E1", point), ("E1_not_point", "E1", other),
                                 ("E2", "E2", _labelled(pairs, "E2", kind))):
            k, n = _agreement(pairs, rule, kind, mask)
            entry[name] = {**share(k, n), "chance": _chance(pairs, rule, kind, mask)}
        entry["added_minus_e0"] = _difference(pairs, windows, draws, kind, ("E0", e0), ("E1", added))
        entry["not_point_minus_point"] = _difference(pairs, windows, draws, kind, ("E1", point), ("E1", other))
        entry["primary"] = "added_minus_e0" if entry["E0"]["n"] >= 100 else "not_point_minus_point"
        sub = pairs[e1]
        groups = {w: g for w, g in sub.groupby("window")}
        kappas = []
        for idx in draws:
            chosen = [groups[windows[i]] for i in idx if windows[i] in groups]
            if chosen:
                c = pd.concat(chosen)
                value = _kappa(c[f"E1|{kind}|A"].to_numpy(), c[f"E1|{kind}|B"].to_numpy())
                if value is not None:
                    kappas.append(value)
        entry["E1_kappa"] = {"kappa": _kappa(sub[f"E1|{kind}|A"].to_numpy(), sub[f"E1|{kind}|B"].to_numpy()),
                             "ci95": [float(np.quantile(kappas, 0.025)), float(np.quantile(kappas, 0.975))]
                             if kappas else None}
        out[kind] = entry
    return out


def case_study_tables(runs: dict, units: pd.DataFrame) -> dict:
    out = {}
    for unit_id, row in units[units["scheme"] == "catchment"].iterrows():
        run = runs.get(f"su|{unit_id}")
        if run is None:
            continue
        entry = {"route": run["route"], "cycles": len(run["cycles"])}
        if run["conditions"]:
            for rule in ("E0", "E1"):
                years = run["conditions"][rule]
                entry[rule] = {
                    "eligible": sum(bool(e["eligible"]) for e in years.values()),
                    "labelled_years": sum(e["recharge"] in LABELS for e in years.values()),
                    "labels": {year: f"{e['recharge']}/{e['refuge']}" for year, e in sorted(years.items())},
                }
        out[row["key"]] = entry
    return out


def stability(runs: dict) -> dict:
    counts = {kind: [0, 0] for kind in KINDS}
    for run in runs.values():
        if run["route"] != "per_year_detection" or not run["conditions"]:
            continue
        for year, e0 in run["conditions"]["E0"].items():
            e1 = run["conditions"]["E1"].get(year, {})
            for kind in KINDS:
                if e0.get(kind) in LABELS and e1.get(kind) in LABELS:
                    counts[kind][1] += 1
                    counts[kind][0] += e0[kind] != e1[kind]
    return {kind: {"labelled_under_both": n, "changed": share(k, n)} for kind, (k, n) in counts.items()}


def e0_reproduces_library(runs: dict) -> int:
    mismatches = 0
    for run in runs.values():
        if run["route"] != "per_year_detection" or not run["conditions"]:
            continue
        for cycle in run["cycles"]:
            e0 = run["conditions"]["E0"].get(str(int(cycle["hy_year"])))
            if e0 is None or bool(e0["eligible"]) != bool(cycle["baseline_eligible"]) \
                    or e0["recharge"] != cycle["recharge"] or e0["refuge"] != cycle["refuge"]:
                mismatches += 1
    return mismatches


# ---------------------------------------------------------------- M2


def mismatch(runs: dict, units: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> dict:
    rows = []
    for key, run in runs.items():
        if run["route"] != "per_year_detection":
            continue
        source, scale = scale_of(key, units)
        invalid = None
        for cycle in run["cycles"]:
            if cycle["trough_timing_status"] != "point" or cycle["trough_month"] is None:
                continue
            start, end, boundary = cycle["trough_interval_start"], cycle["trough_interval_end"], cycle["trough_month"]
            differs = start != boundary or end != boundary
            row = {"source": source, "scale": scale, "differs": differs, "cloudy": None, "side": None,
                   "selection_status": cycle["selection_status"]}
            if differs:
                if invalid is None:
                    f = frames[key]
                    invalid = {g1.month_index(d): 100.0 * (a - v) / a if a else None
                               for d, v, a in zip(f["date"], f["n_valid"], f["n_aoi"])}
                month = start if start != boundary else end
                row["side"] = "before" if month is not None and month < boundary else "after"
                row["cloudy"] = bool(month is not None and invalid.get(month) is not None and invalid[month] > CLOUDY)
            rows.append(row)
    frame = pd.DataFrame(rows)
    out = {}
    for (source, scale), g in frame.groupby(["source", "scale"]):
        d = g[g["differs"]]
        out[f"{source}|{scale}"] = {
            "point_troughs": len(g), "differs": share(len(d), len(g)),
            "differs_cloudy": share(int(d["cloudy"].sum()), len(d)),
            "differs_side": {k: int(v) for k, v in d["side"].value_counts().items()},
            "differs_selection_status": {str(k): int(v) for k, v in d["selection_status"].value_counts().items()},
        }
    return out


# ---------------------------------------------------------------- analyse


def stage_analyse() -> None:
    runs = load_runs()
    frames = series_frames()
    if set(runs) != set(frames):
        raise SystemExit(f"run keys do not match the records: {len(set(frames) - set(runs))} missing")
    units = pd.read_csv(SU / "units.csv").set_index("unit_id")
    routes = pd.Series({k: (k.split("|")[0], r["route"]) for k, r in runs.items()}).value_counts()
    pairs = matched_pairs(runs)
    result = {
        "plan_sha256_lf": g1.sha256_lf(PLAN),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "l1_followups_sha256_lf": g1.sha256_lf(Path(fu.__file__)),
        "g1_series_match_receipt": g1_series_match_receipt(),
        "records": len(runs),
        "errors": sorted(k for k, r in runs.items() if r["error"] is not None),
        "routes": {f"{s}|{route}": int(n) for (s, route), n in routes.items()},
        "e0_mismatches": e0_reproduces_library(runs),
        "m1": {"coverage": coverage(runs, units), "reproducibility": reproducibility(pairs),
               "case_study_tables": case_study_tables(runs, units), "stability": stability(runs)},
        "m2": mismatch(runs, units, frames),
    }
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"analyse: {len(runs)} records, errors {len(result['errors'])}, E0 mismatches {result['e0_mismatches']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("run", "analyse"))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N pending records (smoke test)")
    args = parser.parse_args()
    if args.stage == "run":
        stage_run(args.workers, args.limit)
    else:
        stage_analyse()


if __name__ == "__main__":
    main()
