"""G2: known-truth test of the looser identifiability gates.

Plan and decision rules: docs/handoff/2026-11-02-g2-known-truth-gates-plan.md.

Stages, in order:

    check     noise-free construction check (trough boundary at the built month)
    pilot     pilot records with both gates; run times and band counts only
    freeze    build the main corpus and write the receipt before any outcome
    run       main records with the current and the chosen gates
    evaluate  decision rules; writes the results JSON

The analysis call and the in-process gate override are imported unchanged from
scripts/gate_calibration.py (G1), so both studies run HydroSeason identically.
The library is not modified.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402

REPO_ROOT = g1.REPO_ROOT
HANDOFF = g1.HANDOFF
PLAN = HANDOFF / "2026-11-02-g2-known-truth-gates-plan.md"
RECEIPT = HANDOFF / "2026-11-02-g2-known-truth-gates-receipt.json"
RESULTS = HANDOFF / "2026-11-02-g2-known-truth-gates-results.json"
OUT = g1.DATA / "intermediate" / "hydroseason_known_truth_gates"

CURRENT, CHOSEN = (3.0, 5, 0), (1.5, 2, 0)
SYNTH_MONTHS = pd.date_range("2006-01-01", "2025-12-01", freq="MS")
SHAPES = ("sine", "pulse")
# Months after the trough month m: wet pulse, then a recession down to m.
PULSE = np.array([0.0, 0.6, 1.0, 0.8, 0.5, 0.35, 0.25, 0.18, 0.12, 0.08, 0.05, 0.02])
SEASONAL_SEEDS = range(100000, 101000)
NULL_SEEDS = range(110000, 110400)
N_BACKGROUNDS, INJECTIONS_PER_BACKGROUND = 287, 4  # even, so each background gets both shapes equally
INJECTION_SEEDS = range(120000, 120000 + N_BACKGROUNDS * INJECTIONS_PER_BACKGROUND)
PILOT_SEEDS = range(190000, 190100)
PILOT_I_SEEDS = range(191000, 191100)
N_BOOT = 2000
DATED = g1.DATED


# ---------------------------------------------------------------- helpers


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "g2.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def season(months: pd.DatetimeIndex, trough_month: int, shape: str) -> tuple[np.ndarray, np.ndarray]:
    """Seasonal shape in [0, 1] with its minimum at trough_month, and each month's cycle number."""
    month_idx = months.year.to_numpy() * 12 + months.month.to_numpy() - 1
    after = (month_idx - (trough_month - 1)) % 12
    shape_values = 0.5 * (1 - np.cos(2 * np.pi * after / 12)) if shape == "sine" else PULSE[after]
    cycle = (month_idx - (trough_month - 1)) // 12
    return shape_values, cycle - cycle.min()


def valid_sources() -> list[str]:
    return sorted(p.name for p in (g1.OUT / "series").glob("*.csv.gz"))


def borrowed_valid_fraction(rng, sources: list[str]) -> tuple[str, np.ndarray]:
    window = sources[int(rng.integers(len(sources)))]
    series = pd.read_csv(g1.OUT / "series" / window)
    keys = sorted(series.groupby(["unit", "half"]).groups)
    unit, half = keys[int(rng.integers(len(keys)))]
    one = series[(series["unit"] == unit) & (series["half"] == half)].set_index("date")
    one = one.loc[SYNTH_MONTHS.strftime("%Y-%m-%d")]
    return f"{window.removesuffix('.csv.gz')}|{unit}|{half}", (one["n_valid"] / one["n_aoi"]).to_numpy(float)


def synthetic_record(seed: int, kind: str, sources: list[str], *, noise_free: bool = False,
                     trough_month: int | None = None, shape: str | None = None) -> dict:
    """Arm S record. Every draw happens in a fixed order whatever the kind."""
    rng = np.random.default_rng([seed, 0x47320001])
    n_aoi = int(round(10 ** rng.uniform(2, 5)))
    peak = 10 ** rng.uniform(-2.5, -0.5)
    low = peak * rng.uniform(0, 0.8)
    amplitude = peak - low
    k = 10 ** rng.uniform(np.log10(0.5), np.log10(30))
    sigma = amplitude / k
    shape = shape or SHAPES[seed % 2]
    m = int(trough_month or rng.integers(1, 13))
    if trough_month:
        rng.integers(1, 13)
    year_factor = np.exp(rng.normal(0, 0.25, size=30))
    source, fraction = borrowed_valid_fraction(rng, sources)
    noise = rng.normal(0, sigma, size=len(SYNTH_MONTHS))
    spikes = (rng.random(len(SYNTH_MONTHS)) < 0.04) * rng.uniform(1, 4, size=len(SYNTH_MONTHS)) * sigma
    pulse_starts = rng.integers(0, 11, size=30)
    shape_values, cycle = season(SYNTH_MONTHS, m, shape)
    if kind == "seasonal":
        wet = low + amplitude * year_factor[cycle] * shape_values
    elif kind == "flat":
        wet = np.full(len(SYNTH_MONTHS), low + amplitude / 2)
    elif kind == "random_pulse":
        wet = np.full(len(SYNTH_MONTHS), low)
        years = SYNTH_MONTHS.year.to_numpy() - SYNTH_MONTHS.year.min()
        in_year = SYNTH_MONTHS.month.to_numpy() - 1
        flood = (in_year == pulse_starts[years]) | (in_year == pulse_starts[years] + 1)
        wet = wet + flood * amplitude * year_factor[years]
    else:
        raise ValueError(kind)
    if noise_free:
        n_aoi, fraction = 100_000, np.ones(len(SYNTH_MONTHS))
        n_valid = np.full(len(SYNTH_MONTHS), n_aoi)
        n_water = np.rint(np.clip(wet, 0, 1) * n_aoi).astype(int)
    else:
        n_valid = np.rint(fraction * n_aoi).astype(int)
        n_water = rng.binomial(n_valid, np.clip(wet + noise + spikes, 0, 1))
    return {
        "key": f"S|{kind}|{seed}" + ("|noise_free" if noise_free else ""),
        "arm": "S", "kind": kind, "seed": seed, "shape": shape if kind == "seasonal" else None,
        "trough_month": m if kind == "seasonal" else None, "n_aoi": n_aoi, "k": k, "source": source,
        "rows": {"date": list(SYNTH_MONTHS.strftime("%Y-%m-%d")), "n_water": n_water.tolist(),
                 "n_valid": n_valid.tolist(), "n_aoi": [n_aoi] * len(SYNTH_MONTHS)},
    }


def backgrounds() -> list[str]:
    runs = g1.load_runs(g1.OUT / "phase_a.jsonl")
    return sorted(k for k, r in runs.items() if r["route"] == "event_characterisation" and k.endswith("|A"))


def injection_record(seed: int, background: str) -> dict:
    """Arm I record: a known season injected into a real flat half-series."""
    rng = np.random.default_rng([seed, 0x47320002])
    window, unit, half = background.split("|")
    series = pd.read_csv(g1.OUT / "series" / f"{window}.csv.gz")
    one = series[(series["unit"] == unit) & (series["half"] == half)]
    months = pd.DatetimeIndex(pd.to_datetime(one["date"]))
    n_water = one["n_water"].to_numpy(int)
    n_valid = one["n_valid"].to_numpy(int)
    n_aoi = int(one["n_aoi"].iloc[0])
    observed = n_water[n_valid > 0]
    change = np.abs(np.diff(observed)) if len(observed) > 1 else np.array([0.0])
    noise_px = max(1.0, 1.4826 * float(np.median(change)) / np.sqrt(2))
    shape = SHAPES[seed % 2]
    m = int(rng.integers(1, 13))
    k = 10 ** rng.uniform(np.log10(0.5), np.log10(30))
    peak_px = k * noise_px
    year_factor = np.exp(rng.normal(0, 0.25, size=60))
    shape_values, cycle = season(months, m, shape)
    expected = np.rint(peak_px * year_factor[cycle] * shape_values).astype(int)
    seen = np.divide(n_valid, n_aoi, out=np.zeros(len(n_valid)), where=n_aoi > 0)
    injected = rng.binomial(expected, np.clip(seen, 0, 1))
    return {
        "key": f"I|{seed}", "arm": "I", "kind": "seasonal", "seed": seed, "shape": shape, "trough_month": m,
        "n_aoi": n_aoi, "k": k, "source": background, "noise_px": noise_px, "peak_px_injected": peak_px,
        "rows": {"date": list(one["date"]), "n_water": np.minimum(n_valid, n_water + injected).tolist(),
                 "n_valid": n_valid.tolist(), "n_aoi": [n_aoi] * len(n_valid)},
    }


def run_records(records: list[dict], gates: tuple, sink: Path, workers: int) -> None:
    done = set()
    if sink.exists():
        done = {json.loads(line)["key"] for line in sink.read_text(encoding="utf-8").splitlines() if line}
    payloads = [(r["key"], r["rows"]) for r in records if r["key"] not in done]
    log(f"run {sink.name}: {len(payloads)} records, gates {gates}, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=g1._set_gates, initargs=gates) as pool, \
            open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(g1._run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 100 == 0 or n == len(futures):
                log(f"run {sink.name}: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


def write_corpus(records: list[dict], path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(g1.clean(record)) + "\n")


def read_corpus(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def corpus_digest(records: list[dict]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for record in records:
        digest.update(json.dumps(g1.clean(record), sort_keys=True).encode())
    return digest.hexdigest()


# ---------------------------------------------------------------- scoring


def circular_error(trough: int, trough_month: int) -> int:
    after = (trough - (trough_month - 1)) % 12
    return int(min(after, 12 - after))


def truth_error(trough: int, trough_month: int, shape: str) -> int:
    """Months to the true boundary: m for `pulse`; m or m + 1 for `sine` (construction check)."""
    error = circular_error(trough, trough_month)
    if shape == "sine":
        error = min(error, circular_error(trough, trough_month % 12 + 1))
    return error


def cycle_table(runs: dict[str, dict], meta: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for key, run in runs.items():
        info = meta[key]
        for cycle in run["cycles"]:
            dated = cycle["trough_status"] in DATED and cycle["trough"] is not None
            correct = None
            if dated:
                correct = (info["trough_month"] is not None
                           and truth_error(cycle["trough"], info["trough_month"], info["shape"]) <= 1)
            rows.append({"key": key, "arm": info["arm"], "kind": info["kind"], "shape": info["shape"],
                         "status": cycle["trough_status"], "dated": dated, "correct": correct,
                         "ratio": cycle["ratio"], "peak_px": cycle["peak_px"]})
    frame = pd.DataFrame(rows)
    for column in ("ratio", "peak_px"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def admitted(frame: pd.DataFrame) -> pd.Series:
    return frame["dated"] & ((frame["ratio"] < 3.0) | (frame["peak_px"] < 5))


def margin(frame: pd.DataFrame) -> pd.Series:
    return frame["dated"] & (frame["ratio"] >= 3.0) & (frame["ratio"] < 6.0) & (frame["peak_px"] >= 5)


def wilson_upper(k: int, n: int, z: float = 1.959964) -> float | None:
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    spread = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return float((centre + spread) / (1 + z * z / n))


def per_key(frame: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    sub = frame[mask]
    return sub.groupby("key").agg(n=("correct", "size"), ok=("correct", "sum"))


def bootstrap_difference(a: pd.DataFrame, b: pd.DataFrame, keys: list[str]) -> list[float]:
    """95% interval of accuracy(a) - accuracy(b), resampling records."""
    rng = np.random.default_rng(0)
    keys = np.array(sorted(keys))
    a = a.reindex(keys, fill_value=0)
    b = b.reindex(keys, fill_value=0)
    an, ak, bn, bk = (a["n"].to_numpy(float), a["ok"].to_numpy(float), b["n"].to_numpy(float), b["ok"].to_numpy(float))
    values = []
    for _ in range(N_BOOT):
        w = np.bincount(rng.integers(0, len(keys), len(keys)), minlength=len(keys))
        if (w * an).sum() and (w * bn).sum():
            values.append((w * ak).sum() / (w * an).sum() - (w * bk).sum() / (w * bn).sum())
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def accuracy(frame: pd.DataFrame, mask: pd.Series) -> dict:
    sub = frame[mask]
    n, k = len(sub), int(sub["correct"].sum())
    return {"n": n, "correct": k, "accuracy": (k / n) if n else None}


def bands(frame: pd.DataFrame) -> dict:
    out = {}
    dated = frame[frame["dated"]]
    for low, high in [(1.5, 2), (2, 2.5), (2.5, 3), (3, 4), (4, 6), (6, 10), (10, np.inf)]:
        mask = (dated["ratio"] >= low) & (dated["ratio"] < high)
        out[f"ratio [{low:g},{high:g})"] = accuracy(dated, mask)
    for low, high in [(2, 5), (5, 20), (20, np.inf)]:
        mask = (dated["peak_px"] >= low) & (dated["peak_px"] < high)
        out[f"peak_px [{low:g},{high:g})"] = accuracy(dated, mask)
    return out


# ---------------------------------------------------------------- stages


def stage_check(workers: int) -> None:
    sources = valid_sources()
    records = [synthetic_record(900000 + i, "seasonal", sources, noise_free=True, trough_month=m, shape=shape)
               for i, (m, shape) in enumerate((m, s) for m in range(1, 13) for s in SHAPES)]
    sink = OUT / "check.jsonl"
    run_records(records, CURRENT, sink, workers)
    runs = g1.load_runs(sink)
    summary = {}
    for record in records:
        cycles = runs[record["key"]]["cycles"][1:-1]
        at = [c["trough"] is not None and circular_error(c["trough"], record["trough_month"]) == 0 for c in cycles]
        at_truth = [c["trough"] is not None and truth_error(c["trough"], record["trough_month"], record["shape"]) == 0
                    for c in cycles]
        summary[record["key"]] = {"shape": record["shape"], "trough_month": record["trough_month"],
                                  "route": runs[record["key"]]["route"], "cycles": len(cycles),
                                  "at_m": sum(at), "at_truth": sum(at_truth)}
    for shape in SHAPES:
        rows = [v for v in summary.values() if v["shape"] == shape]
        total = sum(v["cycles"] for v in rows)
        at_m, at_truth = sum(v["at_m"] for v in rows), sum(v["at_truth"] for v in rows)
        log(f"check {shape}: {at_m}/{total} interior trough boundaries at m, {at_truth}/{total} at the truth; "
            f"routes {sorted({v['route'] for v in rows})}")
    (OUT / "check.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def stage_pilot(workers: int, second: bool = False) -> None:
    """Pilot runs: only run times and band counts are summarised, never accuracy."""
    sources, bg = valid_sources(), backgrounds()
    if second:  # arm I only, to size the injections per background
        records = [injection_record(s, bg[(i * 3) % len(bg)]) for i, s in enumerate(PILOT_I_SEEDS)]
        names, summary_file = ("pilot_i_current.jsonl", "pilot_i_chosen.jsonl"), "pilot_i.json"
    else:
        seeds = list(PILOT_SEEDS)
        records = [synthetic_record(s, "seasonal", sources) for s in seeds[:60]]
        records += [injection_record(s, bg[(i * 7) % len(bg)]) for i, s in enumerate(seeds[60:])]
        names, summary_file = ("pilot_current.jsonl", "pilot_chosen.jsonl"), "pilot.json"
    for gates, name in zip((CURRENT, CHOSEN), names, strict=True):
        run_records(records, gates, OUT / name, workers)
    meta = {r["key"]: r for r in records}
    summary = {}
    for name in names:
        runs = g1.load_runs(OUT / name)
        frame = cycle_table(runs, meta)
        for arm in sorted(set(frame["arm"])):
            sub = frame[frame["arm"] == arm]
            summary[f"{name}:{arm}"] = {
                "records": int(sum(1 for k in runs if meta[k]["arm"] == arm)),
                "median_seconds": float(np.median([r["seconds"] for k, r in runs.items() if meta[k]["arm"] == arm])),
                "dated": int(sub["dated"].sum()),
                "admitted_band": int(admitted(sub).sum()),
                "admitted_band_point": int((admitted(sub) & (sub["status"] == "point")).sum()),
                "current_margin": int(margin(sub).sum()),
            }
    (OUT / summary_file).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for key, value in summary.items():
        log(f"pilot {key}: {value}")


def main_records() -> list[dict]:
    sources, bg = valid_sources(), backgrounds()
    records = [synthetic_record(s, "seasonal", sources) for s in SEASONAL_SEEDS]
    nulls = list(NULL_SEEDS)
    records += [synthetic_record(s, "flat", sources) for s in nulls[:200]]
    records += [synthetic_record(s, "random_pulse", sources) for s in nulls[200:]]
    records += [injection_record(s, bg[(s - INJECTION_SEEDS.start) // INJECTIONS_PER_BACKGROUND])
                for s in INJECTION_SEEDS]
    return records


def stage_freeze() -> None:
    if RECEIPT.exists():
        raise SystemExit("receipt exists; the freeze is written once")
    import hydroseason
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as defaults

    if len(backgrounds()) != N_BACKGROUNDS:
        raise SystemExit("background count does not match the injection seeds")
    records = main_records()
    write_corpus(records, OUT / "corpus.jsonl.gz")
    receipt = {
        "plan": str(PLAN.relative_to(REPO_ROOT)).replace("\\", "/"),
        "plan_sha256_lf": g1.sha256_lf(PLAN),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "g1_script_sha256_lf": g1.sha256_lf(Path(g1.__file__)),
        "git_head": g1.git("rev-parse", "HEAD"),
        "git_branch": g1.git("branch", "--show-current"),
        "git_status_short": g1.git("status", "--short").splitlines(),
        "hydroseason_version": hydroseason.__version__,
        "library_gates": {"ratio": defaults.min_amplitude_to_floor_ratio, "peak_pixels": defaults.min_peak_water_pixels},
        "corpus_records": len(records),
        "corpus_sha256": corpus_digest(records),
        "check": json.loads((OUT / "check.json").read_text(encoding="utf-8")),
        "pilot": json.loads((OUT / "pilot.json").read_text(encoding="utf-8")),
        "pilot_i": json.loads((OUT / "pilot_i.json").read_text(encoding="utf-8")),
        "frozen_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    RECEIPT.write_text(json.dumps(g1.clean(receipt), indent=2) + "\n", encoding="utf-8")
    log(f"freeze: plan {receipt['plan_sha256_lf']}, script {receipt['script_sha256_lf']}, "
        f"corpus {receipt['corpus_sha256']} ({len(records)} records)")


def stage_run(workers: int) -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    records = read_corpus(OUT / "corpus.jsonl.gz")
    if corpus_digest(records) != receipt["corpus_sha256"]:
        raise SystemExit("corpus does not match the receipt")
    run_records(records, CURRENT, OUT / "main_current.jsonl", workers)
    run_records(records, CHOSEN, OUT / "main_chosen.jsonl", workers)


def stage_evaluate() -> None:
    receipt_hash = g1.sha256_lf(RECEIPT)
    records = read_corpus(OUT / "corpus.jsonl.gz")
    meta = {r["key"]: {k: v for k, v in r.items() if k != "rows"} for r in records}
    current_runs, chosen_runs = g1.load_runs(OUT / "main_current.jsonl"), g1.load_runs(OUT / "main_chosen.jsonl")
    if set(current_runs) != set(meta) or set(chosen_runs) != set(meta):
        raise SystemExit("runs are incomplete")
    errors = sum(r["error"] is not None for r in [*current_runs.values(), *chosen_runs.values()])
    gates_read = sorted({tuple(r["gates"]) for r in current_runs.values()} | {tuple(r["gates"]) for r in chosen_runs.values()})
    current, chosen = cycle_table(current_runs, meta), cycle_table(chosen_runs, meta)
    results: dict = {"receipt_sha256_lf": receipt_hash, "errors": errors, "gates_read_back": gates_read, "arms": {}}
    checks = {}
    for arm in ("S", "I"):
        cur = current[(current["arm"] == arm) & (current["kind"] == "seasonal")]
        new = chosen[(chosen["arm"] == arm) & (chosen["kind"] == "seasonal")]
        band, edge = admitted(new), margin(cur)
        points = new[band & (new["status"] == "point")]
        edge_points = cur[edge & (cur["status"] == "point")]
        wrong = int((~points["correct"].astype(bool)).sum())
        edge_wrong = int((~edge_points["correct"].astype(bool)).sum())
        upper = wilson_upper(wrong, len(points))
        a_band, a_edge = accuracy(new, band), accuracy(cur, edge)
        keys = [k for k, v in meta.items() if v["arm"] == arm and v["kind"] == "seasonal"]
        diff = (a_band["accuracy"] - a_edge["accuracy"]) if a_band["n"] and a_edge["n"] else None
        interval = bootstrap_difference(per_key(new, band), per_key(cur, edge), keys) if diff is not None else [None, None]
        evaluable_1, evaluable_2 = len(points) >= 100, a_band["n"] >= 100 and a_edge["n"] >= 100
        checks[f"1_precise_safe_{arm}"] = bool(evaluable_1 and upper <= 0.05)
        checks[f"2_band_vs_margin_{arm}"] = bool(evaluable_2 and diff >= -0.05 and interval[0] >= -0.10)
        routed = lambda runs: np.mean([runs[k]["route"] == "per_year_detection" for k in keys])  # noqa: E731
        results["arms"][arm] = {
            "seasonal_records": len(keys),
            "rule_1": {"point_in_band": len(points), "not_correct": wrong, "wilson_upper": upper,
                       "evaluable": evaluable_1},
            "rule_1_current_margin": {"point_in_margin": len(edge_points), "not_correct": edge_wrong,
                                      "wilson_upper": wilson_upper(edge_wrong, len(edge_points))},
            "rule_2": {"admitted_band": a_band, "current_margin": a_edge, "difference": diff,
                       "ci95": interval, "evaluable": evaluable_2},
            "all_dated": {"current": accuracy(cur, cur["dated"]), "chosen": accuracy(new, new["dated"])},
            "routed_per_year_detection": {"current": float(routed(current_runs)), "chosen": float(routed(chosen_runs))},
            "bands": {"current": bands(cur), "chosen": bands(new)},
            "by_shape": {shape: {"admitted_band": accuracy(new[new["shape"] == shape], band[new["shape"] == shape]),
                                 "current_margin": accuracy(cur[cur["shape"] == shape], edge[cur["shape"] == shape])}
                         for shape in SHAPES},
        }
    # Arm I by the background's water type.
    sites = pd.read_csv(g1.OUT / "sites.csv").set_index("window")["water_type"].to_dict()
    new = chosen[chosen["arm"] == "I"].copy()
    cur = current[current["arm"] == "I"].copy()
    for frame in (new, cur):
        frame["water_type"] = [sites.get(meta[k]["source"].split("|")[0]) for k in frame["key"]]
    results["arms"]["I"]["by_water_type"] = {
        wt: {"admitted_band": accuracy(new[new["water_type"] == wt], admitted(new)[new["water_type"] == wt]),
             "current_margin": accuracy(cur[cur["water_type"] == wt], margin(cur)[cur["water_type"] == wt])}
        for wt in sorted(set(new["water_type"].dropna()))
    }
    null_keys = sorted(k for k, v in meta.items() if v["kind"] in ("flat", "random_pulse"))
    seasonal_cur = np.array([current_runs[k]["route"] == "per_year_detection" for k in null_keys], float)
    seasonal_new = np.array([chosen_runs[k]["route"] == "per_year_detection" for k in null_keys], float)
    rng = np.random.default_rng(0)
    draws = [np.mean((seasonal_new - seasonal_cur)[rng.integers(0, len(null_keys), len(null_keys))]) for _ in range(N_BOOT)]
    null_interval = [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))]
    null_dated = {name: int(frame[frame["kind"].isin(["flat", "random_pulse"])]["dated"].sum())
                  for name, frame in (("current", current), ("chosen", chosen))}
    checks["3_null_records"] = bool(null_interval[1] <= 0.02)
    results["null"] = {
        "records": len(null_keys),
        "routed_per_year_detection": {"current": float(seasonal_cur.mean()), "chosen": float(seasonal_new.mean())},
        "by_kind": {kind: {name: float(np.mean([runs[k]["route"] == "per_year_detection"
                                                for k in null_keys if meta[k]["kind"] == kind]))
                           for name, runs in (("current", current_runs), ("chosen", chosen_runs))}
                    for kind in ("flat", "random_pulse")},
        "difference": float((seasonal_new - seasonal_cur).mean()), "ci95": null_interval,
        "dated_trough_boundaries": null_dated,
    }
    results["checks"] = checks
    results["passes"] = all(checks.values())
    RESULTS.write_text(json.dumps(g1.clean(results), indent=2) + "\n", encoding="utf-8")
    log(f"evaluate: passes={results['passes']} checks={checks}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["check", "pilot", "pilot-i", "freeze", "run", "evaluate"])
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
    elif args.stage == "pilot-i":
        stage_pilot(args.workers, second=True)
    elif args.stage == "freeze":
        stage_freeze()
    elif args.stage == "run":
        stage_run(args.workers)
    else:
        stage_evaluate()


if __name__ == "__main__":
    main()
