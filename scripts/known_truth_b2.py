"""B2: known-truth test of the condition labels, with refuge (trough) labels deciding.

Plan and decision rules: docs/handoff/2026-11-04-b2-refuge-labels-plan.md.

Stages, in order:

    identity  with every dry level at 0, B2's generators return G2's records
    check     G2's noise-free construction configurations with dry levels added
    pilot     pilot records; run times and label counts only, never accuracy
    freeze    build the main corpus and write the receipt before any outcome
    run       main records with the current library
    evaluate  decision rules; writes the results JSON

The generators repeat G2's draws (scripts/known_truth_gates.py) in G2's order from
G2's random stream; the only addition is a per-trough dry level drawn from a second
stream. Condition labels under E0, E1 and E2 come from scripts/l1_followups.py's
``_conditions``. The library is not modified.
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
import l1_followups as b1  # noqa: E402

g1 = g2.g1
REPO_ROOT = g1.REPO_ROOT
HANDOFF = g1.HANDOFF
PLAN = HANDOFF / "2026-11-04-b2-refuge-labels-plan.md"
RECEIPT = HANDOFF / "2026-11-04-b2-refuge-labels-receipt.json"
RESULTS = HANDOFF / "2026-11-04-b2-refuge-labels-results.json"
OUT = g1.DATA / "intermediate" / "hydroseason_known_truth_b2"

MONTHS = g2.SYNTH_MONTHS
SHAPES = g2.SHAPES
S_SEEDS = range(280000, 282000)  # 1,400 in the draft; raised to 2,000 after the pilot
I_SEEDS = range(290000, 291148)
INJECTIONS_PER_BACKGROUND = 4
PILOT_S_SEEDS = range(295000, 295200)
PILOT_I_SEEDS = range(296000, 296080)
CHECK_SEEDS_START = 900000  # G2's noise-free construction configurations
IDENTITY_SEEDS = 20
DRY_STREAM = 0x42320003
DRY_MAX = 0.9
N_DRY = {"S": 31, "I": 61}  # one more than G2's year factors: trough j opens cycle j
PEAK_OFFSET = {"sine": 6, "pulse": 2}  # built peak month, in months after the trough
LABELS = ("low", "typical", "high")
DATED = {"point", "interval", "broad"}
RATIO_BANDS = [(3, 4), (4, 6), (6, 10), (10, np.inf)]
N_BOOT = 2000
RULE_1_FLOOR = -0.05
MIN_CYCLES, MIN_RECORDS = 100, 20
PILOT_MIN_RECORDS, PILOT_MIN_CYCLES = 30, 300
_BACKGROUND_CACHE: dict[str, pd.DataFrame] = {}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "b2.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# ---------------------------------------------------------------- generators


def dry_levels(seed: int, arm: str, zero: bool = False) -> np.ndarray:
    """Dry level of each built trough, in season amplitudes, from B2's own stream."""
    if zero:
        return np.zeros(N_DRY[arm])
    return np.random.default_rng([seed, DRY_STREAM]).uniform(0.0, DRY_MAX, size=N_DRY[arm])


def dry_series(months: pd.DatetimeIndex, m: int, shape: str, dry: np.ndarray) -> np.ndarray:
    """Dry level in force each month: trough c's level until the cycle's peak month, then trough c + 1's."""
    month_idx = months.year.to_numpy() * 12 + months.month.to_numpy() - 1
    after = (month_idx - (m - 1)) % 12
    _, cycle = g2.season(months, m, shape)
    return np.where(after < PEAK_OFFSET[shape], dry[cycle], dry[cycle + 1])


def shape_value(shape: str, after: int) -> float:
    return float(0.5 * (1 - np.cos(2 * np.pi * after / 12))) if shape == "sine" else float(g2.PULSE[after])


def synthetic_record(seed: int, sources: list[str], *, noise_free: bool = False, trough_month: int | None = None,
                     shape: str | None = None, zero_dry: bool = False) -> dict:
    """Arm S seasonal record: G2's ``synthetic_record`` draw for draw, plus a dry level per trough."""
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
    source, fraction = g2.borrowed_valid_fraction(rng, sources)
    noise = rng.normal(0, sigma, size=len(MONTHS))
    spikes = (rng.random(len(MONTHS)) < 0.04) * rng.uniform(1, 4, size=len(MONTHS)) * sigma
    rng.integers(0, 11, size=30)  # G2 draws its random-pulse starts for every kind
    shape_values, cycle = g2.season(MONTHS, m, shape)
    dry = dry_levels(seed, "S", zero_dry)
    # Written as low + A*w + A*f*shape so that w = 0 reproduces G2's floating-point sum exactly.
    wet = low + amplitude * dry_series(MONTHS, m, shape, dry) + amplitude * year_factor[cycle] * shape_values
    if noise_free:
        n_aoi, fraction = 100_000, np.ones(len(MONTHS))
        n_valid = np.full(len(MONTHS), n_aoi)
        n_water = np.rint(np.clip(wet, 0, 1) * n_aoi).astype(int)
    else:
        n_valid = np.rint(fraction * n_aoi).astype(int)
        n_water = rng.binomial(n_valid, np.clip(wet + noise + spikes, 0, 1))
    return {
        "key": f"S|{seed}" + ("|noise_free" if noise_free else ""),
        "arm": "S", "kind": "seasonal", "seed": seed, "shape": shape, "trough_month": m, "n_aoi": n_aoi, "k": k,
        "source": source,
        "truth": {"dry": dry.tolist(), "year_factor": year_factor.tolist(), "low_pp": 100.0 * low,
                  "amplitude_pp": 100.0 * amplitude},
        "rows": {"date": list(MONTHS.strftime("%Y-%m-%d")), "n_water": n_water.tolist(),
                 "n_valid": n_valid.tolist(), "n_aoi": [n_aoi] * len(MONTHS)},
    }


def _background(window: str) -> pd.DataFrame:
    if window not in _BACKGROUND_CACHE:
        _BACKGROUND_CACHE[window] = pd.read_csv(g1.OUT / "series" / f"{window}.csv.gz")
    return _BACKGROUND_CACHE[window]


def injection_record(seed: int, background: str, *, zero_dry: bool = False) -> dict:
    """Arm I record: G2's ``injection_record`` draw for draw, plus a dry level per trough."""
    rng = np.random.default_rng([seed, 0x47320002])
    window, unit, half = background.split("|")
    series = _background(window)
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
    shape_values, cycle = g2.season(months, m, shape)
    dry = dry_levels(seed, "I", zero_dry)
    expected = np.rint(peak_px * dry_series(months, m, shape, dry)
                       + peak_px * year_factor[cycle] * shape_values).astype(int)
    seen = np.divide(n_valid, n_aoi, out=np.zeros(len(n_valid)), where=n_aoi > 0)
    injected = rng.binomial(expected, np.clip(seen, 0, 1))
    return {
        "key": f"I|{seed}", "arm": "I", "kind": "seasonal", "seed": seed, "shape": shape, "trough_month": m,
        "n_aoi": n_aoi, "k": k, "source": background, "noise_px": noise_px, "peak_px_injected": peak_px,
        "truth": {"dry": dry.tolist(), "year_factor": year_factor.tolist(), "low_pp": None, "amplitude_pp": None},
        "rows": {"date": list(one["date"]), "n_water": np.minimum(n_valid, n_water + injected).tolist(),
                 "n_valid": n_valid.tolist(), "n_aoi": [n_aoi] * len(n_valid)},
    }


def main_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [synthetic_record(s, sources) for s in S_SEEDS]
    records += [injection_record(s, bg[(s - I_SEEDS.start) // INJECTIONS_PER_BACKGROUND]) for s in I_SEEDS]
    return records


def pilot_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [synthetic_record(s, sources) for s in PILOT_S_SEEDS]
    records += [injection_record(s, bg[(i * 3) % len(bg)]) for i, s in enumerate(PILOT_I_SEEDS)]
    return records


def check_records() -> list[dict]:
    sources = g2.valid_sources()
    configs = [(m, s) for m in range(1, 13) for s in SHAPES]
    return [synthetic_record(CHECK_SEEDS_START + i, sources, noise_free=True, trough_month=m, shape=shape)
            for i, (m, shape) in enumerate(configs)]


# ---------------------------------------------------------------- worker


def _conditions(hy: pd.DataFrame, state) -> dict:
    """Labels under E0, E1, E2: B1's ``_conditions`` for the plain labels, plus the qualified labels."""
    from hydroseason._condition import classify_annual_surface_water_condition

    plain = b1._conditions(hy, state)
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
        out[name] = {}
        for year, row in result.iterrows():
            entry = {"eligible": bool(row["baseline_eligible"]), "recharge": row["recharge_condition"],
                     "refuge": row["refuge_condition"], "recharge_q": row["recharge_condition_qualified"],
                     "refuge_q": row["refuge_condition_qualified"]}
            if {k: entry[k] for k in ("eligible", "recharge", "refuge")} != plain[name][int(year)]:
                raise AssertionError(f"qualified pass disagrees with B1's _conditions at {name} {year}")
            out[name][int(year)] = entry
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
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[], conditions={})
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    cycles = []
    for _, row in hy.iterrows():
        cycles.append({
            "hy_year": row.get("hy_year"),
            "trough_month": g1.month_index(row.get("trough_month")),
            "peak_month": g1.month_index(row.get("peak_month")),
            "trough_extent_pct": row.get("trough_extent_pct"),
            "peak_extent_pct": row.get("peak_extent_pct"),
            "status": row.get("status"), "boundary_status": row.get("boundary_status"),
            "peak_quality": row.get("peak_quality"), "timing_status": row.get("timing_status"),
            "trough_timing_status": row.get("trough_timing_status"),
            "peak_timing_status": row.get("peak_timing_status"),
            "ratio": row.get("amplitude_to_floor_ratio"), "floor": row.get("detectability_floor_pp"),
            "baseline_eligible": row.get("baseline_eligible"),
            "recharge": row.get("recharge_condition"), "refuge": row.get("refuge_condition"),
            "recharge_q": row.get("recharge_condition_qualified"), "refuge_q": row.get("refuge_condition_qualified"),
        })
    conditions = _conditions(hy, analysis.state) if analysis.state is not None and len(hy) else {}
    record.update(route=analysis.route, error=None, cycles=cycles, conditions=conditions,
                  fingerprint=analysis.method_policy_fingerprint,
                  seconds=round(time.perf_counter() - started, 2))
    return record


def run_records(records: list[dict], sink: Path, workers: int) -> None:
    done = set()
    if sink.exists():
        done = {json.loads(line)["key"] for line in sink.read_text(encoding="utf-8").splitlines() if line}
    payloads = [(r["key"], r["rows"]) for r in records if r["key"] not in done]
    log(f"run {sink.name}: {len(payloads)} of {len(records)} records, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 100 == 0 or n == len(futures):
                log(f"run {sink.name}: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- truth


def truth_tables(record: dict) -> dict:
    """Built troughs and cycles inside the record, with their true values in season amplitudes.

    A cycle's true value is its noise-free maximum over all twelve of its months. Because the
    dry level steps at the built peak month, the maximum can fall in the month before it.
    """
    m, shape = record["trough_month"], record["shape"]
    dry = np.asarray(record["truth"]["dry"])
    factor = np.asarray(record["truth"]["year_factor"])
    idx = [g1.month_index(d) for d in record["rows"]["date"]]
    first, last = idx[0], idx[-1]
    first_cycle = (first - (m - 1)) // 12
    n_cycles = (last - (m - 1)) // 12 - first_cycle + 1
    trough_at = {j: (first_cycle + j) * 12 + m - 1 for j in range(n_cycles + 1)}
    troughs = {j: float(dry[j]) for j, t in trough_at.items() if first <= t <= last}
    cycles = {}
    offset = PEAK_OFFSET[shape]
    for c in range(n_cycles):
        values = [(dry[c] if a < offset else dry[c + 1]) + factor[c] * shape_value(shape, a) for a in range(12)]
        top = int(np.argmax(values))
        if first <= trough_at[c] + top <= last:
            cycles[c] = float(values[top])
    return {"first_cycle": first_cycle, "troughs": troughs, "cycles": cycles}


def trough_index(month: int, record: dict, first_cycle: int) -> int:
    star = b1.nearest(month, b1.truth_months(record))
    return (star - (record["trough_month"] - 1)) // 12 - first_cycle


def cycle_index(month: int, record: dict, first_cycle: int) -> int:
    return (month - (record["trough_month"] - 1)) // 12 - first_cycle


def label_table(records: dict, runs: dict) -> tuple[pd.DataFrame, dict]:
    """One row per scored (record, cycle, label kind), with the labels under E0, E1 and E2."""
    rows, unscored = [], {"refuge": 0, "recharge": 0}
    for key, run in runs.items():
        if run["route"] != "per_year_detection" or not run["cycles"]:
            continue
        rec = records[key]
        truth = truth_tables(rec)
        fc = truth["first_cycle"]
        ref = {"refuge": np.array(list(truth["troughs"].values())),
               "recharge": np.array(list(truth["cycles"].values()))}
        for cycle in run["cycles"]:
            for kind, month_col, table, locate in (("refuge", "trough_month", truth["troughs"], trough_index),
                                                   ("recharge", "peak_month", truth["cycles"], cycle_index)):
                month = cycle[month_col]
                if month is None:
                    continue
                j = locate(month, rec, fc)
                if j not in table:
                    unscored[kind] += 1
                    continue
                got = {v: run["conditions"].get(v, {}).get(str(cycle["hy_year"]), {}) for v in ("E0", "E1", "E2")}
                rows.append({
                    "key": key, "arm": rec["arm"], "shape": rec["shape"], "kind": kind, "hy_year": cycle["hy_year"],
                    "want": b1.truth_label(table[j], ref[kind]), "ratio": cycle["ratio"],
                    **{v: got[v].get(kind) for v in got}, **{f"{v}_q": got[v].get(f"{kind}_q") for v in got},
                })
    return pd.DataFrame(rows), unscored


# ---------------------------------------------------------------- statistics


def confusion(got: pd.Series, want: pd.Series) -> np.ndarray:
    """3 x 3 counts: rows are the library's label, columns the true label."""
    mat = np.zeros((3, 3))
    for g, w in zip(got, want):
        mat[LABELS.index(g), LABELS.index(w)] += 1
    return mat


def kappa(mat: np.ndarray) -> float | None:
    n = mat.sum()
    if n == 0:
        return None
    po = np.trace(mat) / n
    pe = float((mat.sum(axis=1) * mat.sum(axis=0)).sum() / n ** 2)
    return None if pe >= 1 else float((po - pe) / (1 - pe))


def chance(mat: np.ndarray) -> float | None:
    n = mat.sum()
    return float((mat.sum(axis=1) * mat.sum(axis=0)).sum() / n ** 2) if n else None


def bootstrap(per_key: dict[str, np.ndarray], keys: list[str], statistic, width: int) -> list[float | None]:
    """95% interval of a statistic of summed per-record vectors, resampling records (seed 0)."""
    if not keys:
        return [None, None]
    rng = np.random.default_rng(0)
    stack = np.stack([per_key.get(k, np.zeros(width)) for k in sorted(keys)])
    values = []
    for _ in range(N_BOOT):
        w = np.bincount(rng.integers(0, len(keys), len(keys)), minlength=len(keys))
        value = statistic((w[:, None] * stack).sum(axis=0))
        if value is not None and np.isfinite(value):
            values.append(value)
    if not values:
        return [None, None]
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def summary(sub: pd.DataFrame, column: str) -> dict:
    """Agreement, chance agreement, kappa and gross errors of one label column against the truth."""
    lab = sub[sub[column].isin(LABELS)]
    mat = confusion(lab[column], lab["want"]) if len(lab) else np.zeros((3, 3))
    n = int(len(lab))
    agree = int((lab[column] == lab["want"]).sum())
    gross = int(sum({g, w} == {"low", "high"} for g, w in zip(lab[column], lab["want"])))
    return {"n": n, "agree": agree, "share": (agree / n) if n else None, "chance": chance(mat),
            "kappa": kappa(mat), "gross": gross, "records": int(lab["key"].nunique()) if n else 0}


def rule_1(sub: pd.DataFrame, keys: list[str]) -> dict:
    """E1 minus E0 agreement on cycles both rules label."""
    both = sub[sub["E0"].isin(LABELS) & sub["E1"].isin(LABELS)]
    per_key = {k: np.array([len(g), (g["E0"] == g["want"]).sum(), (g["E1"] == g["want"]).sum()], float)
               for k, g in both.groupby("key")}
    n = len(both)
    diff = (((both["E1"] == both["want"]).sum() - (both["E0"] == both["want"]).sum()) / n) if n else None
    interval = bootstrap(per_key, keys, lambda v: (v[2] - v[1]) / v[0] if v[0] else None, 3)
    evaluable = n >= MIN_CYCLES and both["key"].nunique() >= MIN_RECORDS
    if not evaluable or interval[0] is None:
        outcome = "inconclusive"
    elif interval[0] >= RULE_1_FLOOR:
        outcome = "holds"
    elif interval[1] < RULE_1_FLOOR:
        outcome = "fails"
    else:
        outcome = "inconclusive"
    return {"cycles": int(n), "records": int(both["key"].nunique()), "difference": diff, "ci95": interval,
            "floor": RULE_1_FLOOR, "evaluable": bool(evaluable), "outcome": outcome}


def rule_2(sub: pd.DataFrame, keys: list[str]) -> dict:
    """Cohen's kappa of the labels E1 adds (labelled under E1, not under E0) with the truth."""
    added = sub[sub["E1"].isin(LABELS) & ~sub["E0"].isin(LABELS)]
    per_key = {k: confusion(g["E1"], g["want"]).ravel() for k, g in added.groupby("key")}
    mat = confusion(added["E1"], added["want"]) if len(added) else np.zeros((3, 3))
    interval = bootstrap(per_key, keys, lambda v: kappa(v.reshape(3, 3)), 9)
    evaluable = len(added) >= MIN_CYCLES
    if not evaluable or interval[0] is None:
        outcome = "inconclusive"
    else:
        outcome = "holds" if interval[0] > 0 else "fails"
    return {"cycles": int(len(added)), "records": int(added["key"].nunique()), "kappa": kappa(mat),
            "ci95": interval, "floor": 0.0, "evaluable": bool(evaluable), "outcome": outcome}


def added_minus_e0(sub: pd.DataFrame, keys: list[str]) -> dict:
    """The real-record study's comparison; reported, not used to decide."""
    e0 = sub[sub["E0"].isin(LABELS)]
    added = sub[sub["E1"].isin(LABELS) & ~sub["E0"].isin(LABELS)]
    per_key = {}
    for k in set(e0["key"]) | set(added["key"]):
        a, e = added[added["key"] == k], e0[e0["key"] == k]
        per_key[k] = np.array([len(a), (a["E1"] == a["want"]).sum(), len(e), (e["E0"] == e["want"]).sum()], float)
    diff = None
    if len(e0) and len(added):
        diff = float((added["E1"] == added["want"]).mean() - (e0["E0"] == e0["want"]).mean())
    stat = lambda v: (v[1] / v[0] - v[3] / v[2]) if v[0] and v[2] else None  # noqa: E731
    return {"difference": diff, "ci95": bootstrap(per_key, keys, stat, 4)}


def qualified(sub: pd.DataFrame, variant: str, mask: pd.Series) -> dict:
    rows = sub[mask & sub[variant].isin(["low", "high"])]
    replaced = int((rows[f"{variant}_q"] == "typical_uncertain").sum())
    kept = sub[mask & sub[f"{variant}_q"].isin(LABELS)]
    agree = int((kept[f"{variant}_q"] == kept["want"]).sum())
    return {"low_or_high": int(len(rows)), "replaced_by_typical_uncertain": replaced,
            "remaining_labelled": int(len(kept)), "remaining_agree": agree,
            "remaining_share": (agree / len(kept)) if len(kept) else None}


def groups(sub: pd.DataFrame) -> dict:
    e0, e1 = sub["E0"].isin(LABELS), sub["E1"].isin(LABELS)
    both = sub[e0 & e1]
    return {
        "E0": summary(sub, "E0"), "E1": summary(sub, "E1"), "E2": summary(sub, "E2"),
        "E0_on_cycles_both_label": summary(both, "E0"), "E1_on_cycles_both_label": summary(both, "E1"),
        "added": summary(sub[e1 & ~e0], "E1"),
    }


# ---------------------------------------------------------------- stages


def stage_identity() -> None:
    """With every dry level at 0, B2's generators must return G2's records exactly."""
    sources, bg = g2.valid_sources(), g2.backgrounds()
    fields = ("arm", "kind", "seed", "shape", "trough_month", "n_aoi", "k", "source", "rows")
    pairs = []
    for s in list(S_SEEDS)[:IDENTITY_SEEDS]:
        pairs.append((synthetic_record(s, sources, zero_dry=True), g2.synthetic_record(s, "seasonal", sources)))
    for s in list(I_SEEDS)[:IDENTITY_SEEDS]:
        b = bg[(s - I_SEEDS.start) // INJECTIONS_PER_BACKGROUND]
        pairs.append((injection_record(s, b, zero_dry=True), g2.injection_record(s, b)))
    for i, (m, shape) in enumerate((m, s) for m in range(1, 13) for s in SHAPES):
        seed = CHECK_SEEDS_START + i
        pairs.append((synthetic_record(seed, sources, noise_free=True, trough_month=m, shape=shape, zero_dry=True),
                      g2.synthetic_record(seed, "seasonal", sources, noise_free=True, trough_month=m, shape=shape)))
    failures = []
    for ours, theirs in pairs:
        bad = [f for f in fields if json.dumps(g1.clean(ours.get(f))) != json.dumps(g1.clean(theirs.get(f)))]
        if bad:
            failures.append({"seed": ours["seed"], "arm": ours["arm"], "fields": bad})
    result = {"pairs": len(pairs), "identical": len(pairs) - len(failures), "failures": failures}
    (OUT / "identity.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    log(f"identity: {result['identical']}/{result['pairs']} identical")


def stage_check(workers: int) -> None:
    records = check_records()
    sink = OUT / "check.jsonl"
    run_records(records, sink, workers)
    runs = g1.load_runs(sink)
    meta = {r["key"]: r for r in records}
    per_shape: dict = {}
    for shape in SHAPES:
        total = at_truth = at_m = trough_ok = at_dry = peak_ok = 0
        routes = set()
        for key, run in runs.items():
            rec = meta[key]
            if rec["shape"] != shape:
                continue
            routes.add(run["route"])
            truth = truth_tables(rec)
            low, amp = rec["truth"]["low_pp"], rec["truth"]["amplitude_pp"]
            rows = rec["rows"]
            level = {g1.month_index(d): 100.0 * w / v for d, w, v in zip(rows["date"], rows["n_water"], rows["n_valid"])}
            for cycle in run["cycles"][1:-1]:
                total += 1
                t, p = cycle["trough_month"], cycle["peak_month"]
                at_truth += int(t is not None and g2.truth_error(t, rec["trough_month"], shape) == 0)
                at_m += int(t is not None and g2.circular_error(t, rec["trough_month"]) == 0)
                if t is not None and cycle["trough_extent_pct"] is not None:
                    # The noise-free level at the reported month: the built dry level at m; for `sine`
                    # boundaries at m + 1 (accepted as truth since G2) it also holds 0.067 of the season.
                    trough_ok += int(abs(cycle["trough_extent_pct"] - level[t]) <= 0.01)
                    j = trough_index(t, rec, truth["first_cycle"])
                    at_dry += int(abs(cycle["trough_extent_pct"] - (low + amp * rec["truth"]["dry"][j])) <= 0.01)
                if p is not None and cycle["peak_extent_pct"] is not None:
                    c = cycle_index(p, rec, truth["first_cycle"])
                    if c in truth["cycles"]:
                        peak_ok += int(abs(cycle["peak_extent_pct"] - (low + amp * truth["cycles"][c])) <= 0.01)
        per_shape[shape] = {"interior_cycles": total, "boundary_at_truth": at_truth, "boundary_at_m": at_m,
                            "trough_extent_at_noise_free_level_of_its_month": trough_ok,
                            "trough_extent_at_built_dry_level_reported": at_dry,
                            "peak_extent_at_noise_free_maximum": peak_ok, "routes": sorted(routes)}
    passes = all(
        v["interior_cycles"] and min(v["boundary_at_truth"], v["trough_extent_at_noise_free_level_of_its_month"],
                                     v["peak_extent_at_noise_free_maximum"]) / v["interior_cycles"] >= 0.95
        for v in per_shape.values())
    frame, unscored = label_table(meta, runs)
    recorded = {kind: {v: summary(frame[frame["kind"] == kind], v) for v in ("E0", "E1", "E2")}
                for kind in ("refuge", "recharge")} if len(frame) else {}
    result = {"by_shape": per_shape, "passes": bool(passes), "labels_recorded_not_required": recorded,
              "unscored": unscored}
    (OUT / "check.json").write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"check: passes={passes} {per_shape}")


def _label_counts(runs: dict, meta: dict) -> dict:
    out = {}
    for arm in ("S", "I"):
        keys = [k for k in runs if meta[k]["arm"] == arm]
        seconds = [runs[k]["seconds"] for k in keys if runs[k].get("seconds")]
        entry = {"records": len(keys), "median_seconds": float(np.median(seconds)) if seconds else None,
                 "per_year_detection": sum(runs[k]["route"] == "per_year_detection" for k in keys),
                 "errors": sum(runs[k]["error"] is not None for k in keys)}
        for kind in ("refuge", "recharge"):
            with_e0 = both = added = 0
            for k in keys:
                cond = runs[k].get("conditions") or {}
                e0, e1 = cond.get("E0", {}), cond.get("E1", {})
                with_e0 += int(any(v[kind] in LABELS for v in e0.values()))
                for y, v in e1.items():
                    if v[kind] in LABELS:
                        if e0.get(y, {}).get(kind) in LABELS:
                            both += 1
                        else:
                            added += 1
            entry[kind] = {"records_with_e0_labels": with_e0, "cycles_labelled_under_both": both,
                           "cycles_e1_adds": added}
        out[arm] = entry
    return out


def stage_pilot(workers: int) -> None:
    """Pilot: run times and label counts only, never accuracy."""
    records = pilot_records()
    sink = OUT / "pilot.jsonl"
    run_records(records, sink, workers)
    runs = g1.load_runs(sink)
    meta = {r["key"]: {k: v for k, v in r.items() if k not in ("rows", "truth")} for r in records}
    counts = _label_counts(runs, meta)
    scale = {"S": len(S_SEEDS) / len(PILOT_S_SEEDS), "I": len(I_SEEDS) / len(PILOT_I_SEEDS)}
    predicted = {}
    for arm in ("S", "I"):
        refuge = counts[arm]["refuge"]
        predicted[arm] = {
            "records_with_e0_refuge_labels": refuge["records_with_e0_labels"] * scale[arm],
            "refuge_cycles_labelled_under_both": refuge["cycles_labelled_under_both"] * scale[arm],
            "refuge_cycles_e1_adds": refuge["cycles_e1_adds"] * scale[arm],
            "cpu_seconds": (counts[arm]["median_seconds"] or 0) * (len(S_SEEDS) if arm == "S" else len(I_SEEDS)),
        }
        predicted[arm]["large_enough"] = bool(
            predicted[arm]["records_with_e0_refuge_labels"] >= PILOT_MIN_RECORDS
            and predicted[arm]["refuge_cycles_labelled_under_both"] >= PILOT_MIN_CYCLES)
    result = {"counts": counts, "scale": scale, "predicted_main": predicted}
    (OUT / "pilot.json").write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"pilot: {json.dumps(g1.clean(result))}")


def stage_freeze() -> None:
    if RECEIPT.exists():
        raise SystemExit("receipt exists; the freeze is written once")
    import hydroseason
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as defaults

    plan = PLAN.read_text(encoding="utf-8")
    if "to be recorded here before the freeze" in plan or "Status: Frozen" not in plan:
        raise SystemExit("record the check and pilot outcomes in the plan and mark it frozen first")
    identity = json.loads((OUT / "identity.json").read_text(encoding="utf-8"))
    check = json.loads((OUT / "check.json").read_text(encoding="utf-8"))
    if identity["failures"] or not check["passes"]:
        raise SystemExit("identity or construction check failed")
    if len(g2.backgrounds()) * INJECTIONS_PER_BACKGROUND != len(I_SEEDS):
        raise SystemExit("background count does not match the injection seeds")
    pilot_runs = g1.load_runs(OUT / "pilot.jsonl")
    records = main_records()
    g2.write_corpus(records, OUT / "corpus.jsonl.gz")
    receipt = {
        "plan": str(PLAN.relative_to(REPO_ROOT)).replace("\\", "/"),
        "plan_sha256_lf": g1.sha256_lf(PLAN),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "b1_script_sha256_lf": g1.sha256_lf(Path(b1.__file__)),
        "g2_script_sha256_lf": g1.sha256_lf(Path(g2.__file__)),
        "g1_script_sha256_lf": g1.sha256_lf(Path(g1.__file__)),
        "git_head": g1.git("rev-parse", "HEAD"),
        "git_branch": g1.git("branch", "--show-current"),
        "git_status_short": g1.git("status", "--short").splitlines(),
        "hydroseason_version": hydroseason.__version__,
        "method_policy_fingerprints_in_pilot": sorted({r.get("fingerprint") for r in pilot_runs.values()
                                                       if r.get("fingerprint")}),
        "library_gates": {"ratio": defaults.min_amplitude_to_floor_ratio, "peak_pixels": defaults.min_peak_water_pixels},
        "corpus_records": len(records),
        "corpus_sha256": g2.corpus_digest(records),
        "identity": identity,
        "check": check,
        "pilot": json.loads((OUT / "pilot.json").read_text(encoding="utf-8")),
        "frozen_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    RECEIPT.write_text(json.dumps(g1.clean(receipt), indent=2) + "\n", encoding="utf-8")
    log(f"freeze: plan {receipt['plan_sha256_lf']}, script {receipt['script_sha256_lf']}, "
        f"corpus {receipt['corpus_sha256']} ({len(records)} records)")


def stage_run(workers: int) -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    records = g2.read_corpus(OUT / "corpus.jsonl.gz")
    if g2.corpus_digest(records) != receipt["corpus_sha256"]:
        raise SystemExit("corpus does not match the receipt")
    run_records(records, OUT / "main.jsonl", workers)


def trough_level_read(records: dict, runs: dict) -> dict:
    """Reported trough_extent_pct minus the true dry level, in detectability floors (arm S)."""
    rows = []
    for key, run in runs.items():
        rec = records[key]
        if rec["arm"] != "S" or run["route"] != "per_year_detection":
            continue
        truth = truth_tables(rec)
        for cycle in run["cycles"]:
            t, level, floor = cycle["trough_month"], cycle["trough_extent_pct"], cycle["floor"]
            if t is None or level is None or not floor:
                continue
            j = trough_index(t, rec, truth["first_cycle"])
            if not 0 <= j < len(rec["truth"]["dry"]):
                continue
            star = b1.nearest(t, b1.truth_months(rec))
            built = rec["truth"]["low_pp"] + rec["truth"]["amplitude_pp"] * rec["truth"]["dry"][j]
            rows.append({"correct": abs(t - star) <= 1, "floors": (level - built) / floor})
    frame = pd.DataFrame(rows)
    out = {}
    for name, sub in (("correct", frame[frame["correct"]]), ("miss", frame[~frame["correct"]])):
        vals = sub["floors"].to_numpy(float)
        out[name] = {"n": int(len(vals)), "median": float(np.median(vals)) if len(vals) else None,
                     "median_abs": float(np.median(np.abs(vals))) if len(vals) else None,
                     "share_abs_over_1": float(np.mean(np.abs(vals) > 1)) if len(vals) else None}
    return out


def stage_evaluate() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    corpus = g2.read_corpus(OUT / "corpus.jsonl.gz")
    if g2.corpus_digest(corpus) != receipt["corpus_sha256"]:
        raise SystemExit("corpus does not match the receipt")
    records = {r["key"]: r for r in corpus}
    runs = g1.load_runs(OUT / "main.jsonl")
    if set(runs) != set(records):
        raise SystemExit("runs are incomplete")
    e0_mismatch = 0
    for run in runs.values():
        for cycle in run["cycles"]:
            got = run["conditions"].get("E0", {}).get(str(cycle["hy_year"]), {})
            if got and (got["recharge"], got["refuge"], got["recharge_q"], got["refuge_q"], got["eligible"]) != (
                    cycle["recharge"], cycle["refuge"], cycle["recharge_q"], cycle["refuge_q"],
                    bool(cycle["baseline_eligible"])):
                e0_mismatch += 1
    frame, unscored = label_table(records, runs)
    results: dict = {
        "receipt_sha256_lf": g1.sha256_lf(RECEIPT),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "records": len(runs),
        "errors": sum(r["error"] is not None for r in runs.values()),
        "fingerprints": sorted({r.get("fingerprint") for r in runs.values() if r.get("fingerprint")}),
        "routes": {arm: pd.Series([r["route"] for k, r in runs.items() if records[k]["arm"] == arm])
                   .value_counts().to_dict() for arm in ("S", "I")},
        "e0_reproduces_library_labels": e0_mismatch == 0,
        "e0_mismatched_cycles": e0_mismatch,
        "unscored_rows": unscored,
        "labels": {},
    }
    for kind in ("refuge", "recharge"):
        out: dict = {}
        for arm in ("S", "I"):
            keys = sorted(k for k, r in runs.items() if records[k]["arm"] == arm and r["route"] == "per_year_detection")
            sub = frame[(frame["kind"] == kind) & (frame["arm"] == arm)]
            e0, e1 = sub["E0"].isin(LABELS), sub["E1"].isin(LABELS)
            both = sub[e0 & e1]
            entry = {
                "records_per_year_detection": len(keys),
                "scored_cycles": int(len(sub)),
                "rule_1": rule_1(sub, keys),
                "rule_2": rule_2(sub, keys),
                "groups": groups(sub),
                "added_minus_e0_reported": added_minus_e0(sub, keys),
                "coverage": {},
                "label_changed_on_cycles_both_label": {"n": int(len(both)),
                                                       "changed": int((both["E0"] != both["E1"]).sum())},
                "qualified": {"E0": qualified(sub, "E0", e0), "E1": qualified(sub, "E1", e1),
                              "added": qualified(sub, "E1", e1 & ~e0)},
                "by_shape": {s: groups(sub[sub["shape"] == s]) for s in SHAPES},
                "by_ratio_band": {},
            }
            ratio = pd.to_numeric(sub["ratio"], errors="coerce")
            for lo, hi in RATIO_BANDS:
                entry["by_ratio_band"][f"[{lo:g},{hi:g})"] = groups(sub[(ratio >= lo) & (ratio < hi)])
            for v in ("E0", "E1", "E2"):
                labelled = sub[sub[v].isin(LABELS)]
                eligible = [sum(c["eligible"] for c in runs[k]["conditions"].get(v, {}).values()) for k in keys]
                entry["coverage"][v] = {"cycles_labelled": int(len(labelled)),
                                        "records_with_labels": int(labelled["key"].nunique()),
                                        "median_eligible_cycles": float(np.median(eligible)) if eligible else None}
            out[arm] = entry
        outcomes = [out[a][r]["outcome"] for a in ("S", "I") for r in ("rule_1", "rule_2")]
        out["outcome"] = ("fail" if "fails" in outcomes
                          else "pass" if all(o == "holds" for o in outcomes) else "inconclusive")
        results["labels"][kind] = out
    results["decision"] = {"refuge": results["labels"]["refuge"]["outcome"],
                           "recharge_reported": results["labels"]["recharge"]["outcome"]}
    results["trough_level_read_S"] = trough_level_read(records, runs)
    RESULTS.write_text(json.dumps(g1.clean(results), indent=2) + "\n", encoding="utf-8")
    log(f"evaluate: refuge {results['decision']['refuge']}, recharge (reported) "
        f"{results['decision']['recharge_reported']}, E0 mismatches {e0_mismatch}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["identity", "check", "pilot", "freeze", "run", "evaluate"])
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    import hydroseason

    if Path(hydroseason.__file__).resolve().parent != (REPO_ROOT / "hydroseason").resolve():
        raise SystemExit(f"run with the repository's hydroseason, not {hydroseason.__file__}")
    OUT.mkdir(parents=True, exist_ok=True)
    stages = {"identity": stage_identity, "check": lambda: stage_check(args.workers),
              "pilot": lambda: stage_pilot(args.workers), "freeze": stage_freeze,
              "run": lambda: stage_run(args.workers), "evaluate": stage_evaluate}
    stages[args.stage]()


if __name__ == "__main__":
    main()
