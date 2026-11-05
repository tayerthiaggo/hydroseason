"""DE1: where the dry season ends, against known truth.

Plan and decision rules: docs/handoff/2026-11-05-de1-dry-run-end-plan.md.

Stages, in order:

    identity  `pulse` and `sine` records equal G2's generator output
    check     noise-free `ephemeral` construction records, and the run-end unit cases
    pilot     pilot records; run times, pair counts and moved shares only, never accuracy
    freeze    build the main corpus and write the receipt before any outcome
    run       main records with the current library
    evaluate  decision rules; writes the results JSON
    real      reported only: the candidate on the stored v0.3.0 real-record runs

The library is not modified. Each record runs once; the current end of the dry season
is the trough boundary, and the candidate is the end of the boundary's low run
followed past the search window (``low_run``).
"""
from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_gates as g2  # noqa: E402

g1 = g2.g1
HANDOFF = g1.HANDOFF
PLAN = HANDOFF / "2026-11-05-de1-dry-run-end-plan.md"
RECEIPT = HANDOFF / "2026-11-05-de1-dry-run-end-receipt.json"
RESULTS = HANDOFF / "2026-11-05-de1-dry-run-end-results.json"
REAL_RESULTS = HANDOFF / "2026-11-05-de1-dry-run-end-real-records.json"
OUT = g1.DATA / "intermediate" / "hydroseason_known_truth_de1"
V030_RUNS = g1.DATA / "intermediate" / "hydroseason_v030_real_record_check" / "runs.jsonl"

MONTHS = g2.SYNTH_MONTHS
S_EPHEMERAL = range(300000, 301200)
S_PULSE = range(301200, 301600)
S_SINE = range(301600, 302000)
I_SEEDS = range(305000, 306148)
INJECTIONS_PER_BACKGROUND = 4
PILOT_S = range(308000, 308200)
PILOT_I = range(309000, 309080)
CHECK_SEEDS_START = 950000
IDENTITY_SEEDS = 20
S_STREAM, I_STREAM = 0x44450001, 0x44450002
N_YEARS = 64  # per-year draws; more than any record spans
WET_PROFILE = {1: [1.0], 2: [0.6, 1.0], 3: [0.6, 1.0, 0.5]}
TAIL = 0.2
DATED = {"point", "interval", "broad"}
RATIO_BANDS = [(3, 4), (4, 6), (6, 10), (10, np.inf)]
N_BOOT = 2000


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "de1.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def midx(stamp) -> int:
    stamp = pd.Timestamp(stamp)
    return stamp.year * 12 + stamp.month - 1


# ---------------------------------------------------------------- the ephemeral season


def _season_draws(rng) -> dict:
    """Per-record and per-year draws for the `ephemeral` shape, always in this order."""
    return {
        "mean_onset": int(rng.integers(1, 13)),
        "q": float(rng.uniform(0, 0.3)),
        "r": float(rng.uniform(0, 0.15)),
        "jitter": rng.integers(-2, 3, size=N_YEARS),
        "length": rng.integers(1, 4, size=N_YEARS),
        "no_wet": rng.random(N_YEARS),
        "year_factor": np.exp(rng.normal(0, 0.25, size=N_YEARS)),
        "pulse": rng.random(N_YEARS),
        "pulse_size": rng.uniform(0.05, 0.3, size=N_YEARS),
        "pulse_place": rng.random(N_YEARS),
    }


def ephemeral_shape(months: pd.DatetimeIndex, draws: dict) -> tuple[np.ndarray, list[int], list[int]]:
    """Shape in units of the peak (0 when dry), true wet-season onsets and mid-dry pulse months (month indices)."""
    index = np.array([midx(m) for m in months])
    first_year = int(months[0].year) - 1
    onsets, lengths, factors = [], [], []
    for i in range(N_YEARS):
        year = first_year + i
        onset = year * 12 + draws["mean_onset"] - 1 + int(draws["jitter"][i])
        if onset > index[-1] + 2:
            break
        if draws["no_wet"][i] < draws["q"]:
            continue
        onsets.append(onset)
        lengths.append(int(draws["length"][i]))
        factors.append(float(draws["year_factor"][i]))
    values = {}
    for onset, length, factor in zip(onsets, lengths, factors):
        for j, v in enumerate(WET_PROFILE[length]):
            values[onset + j] = v * factor
        values[onset + length] = TAIL * factor
    pulses = []
    for i, (onset, length) in enumerate(zip(onsets, lengths)):
        if i + 1 >= len(onsets) or draws["pulse"][i] >= draws["r"]:
            continue
        candidates = list(range(onset + length + 2, onsets[i + 1] - 1))
        if not candidates:
            continue
        month = candidates[int(draws["pulse_place"][i] * len(candidates))]
        values[month] = max(values.get(month, 0.0), float(draws["pulse_size"][i]))
        pulses.append(month)
    shape = np.array([values.get(int(m), 0.0) for m in index])
    inside = [o for o in onsets if index[0] + 1 <= o <= index[-1]]
    return shape, inside, [p for p in pulses if index[0] <= p <= index[-1]]


def ephemeral_synthetic(seed: int, sources: list[str], *, noise_free: bool = False,
                        mean_onset: int | None = None) -> dict:
    rng = np.random.default_rng([seed, S_STREAM])
    n_aoi = int(round(10 ** rng.uniform(1.5, 4.5)))
    peak = 10 ** rng.uniform(-2.5, -0.5)
    k = 10 ** rng.uniform(np.log10(0.5), np.log10(30))
    sigma = peak / k
    draws = _season_draws(rng)
    if mean_onset is not None:
        draws["mean_onset"] = mean_onset
    source, fraction = g2.borrowed_valid_fraction(rng, sources)
    noise = rng.normal(0, sigma, size=len(MONTHS))
    spikes = (rng.random(len(MONTHS)) < 0.04) * rng.uniform(1, 4, size=len(MONTHS)) * sigma
    shape, onsets, pulses = ephemeral_shape(MONTHS, draws)
    wet = peak * shape
    if noise_free:
        n_aoi = 100_000
        n_valid = np.full(len(MONTHS), n_aoi)
        n_water = np.rint(np.clip(wet, 0, 1) * n_aoi).astype(int)
    else:
        n_valid = np.rint(fraction * n_aoi).astype(int)
        n_water = rng.binomial(n_valid, np.clip(wet + noise + spikes, 0, 1))
    return {
        "key": f"S|ephemeral|{seed}" + ("|noise_free" if noise_free else ""), "arm": "S", "shape": "ephemeral",
        "seed": seed, "trough_month": None, "n_aoi": n_aoi, "k": k, "source": source,
        "truth": {"onsets": onsets, "pulses": pulses, "mean_onset": draws["mean_onset"], "q": draws["q"],
                  "r": draws["r"]},
        "rows": {"date": list(MONTHS.strftime("%Y-%m-%d")), "n_water": n_water.tolist(),
                 "n_valid": n_valid.tolist(), "n_aoi": [n_aoi] * len(MONTHS)},
    }


_BACKGROUND_CACHE: dict[str, pd.DataFrame] = {}


def _background(window: str) -> pd.DataFrame:
    if window not in _BACKGROUND_CACHE:
        _BACKGROUND_CACHE[window] = pd.read_csv(g1.OUT / "series" / f"{window}.csv.gz")
    return _BACKGROUND_CACHE[window]


def ephemeral_injection(seed: int, background: str) -> dict:
    rng = np.random.default_rng([seed, I_STREAM])
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
    k = 10 ** rng.uniform(np.log10(0.5), np.log10(30))
    peak_px = k * noise_px
    draws = _season_draws(rng)
    shape, onsets, pulses = ephemeral_shape(months, draws)
    expected = np.rint(peak_px * shape).astype(int)
    seen = np.divide(n_valid, n_aoi, out=np.zeros(len(n_valid)), where=n_aoi > 0)
    injected = rng.binomial(expected, np.clip(seen, 0, 1))
    return {
        "key": f"I|{seed}", "arm": "I", "shape": "ephemeral", "seed": seed, "trough_month": None,
        "n_aoi": n_aoi, "k": k, "source": background, "noise_px": noise_px,
        "truth": {"onsets": onsets, "pulses": pulses, "mean_onset": draws["mean_onset"], "q": draws["q"],
                  "r": draws["r"]},
        "rows": {"date": list(one["date"]), "n_water": np.minimum(n_valid, n_water + injected).tolist(),
                 "n_valid": n_valid.tolist(), "n_aoi": [n_aoi] * len(n_valid)},
    }


def g2_synthetic(seed: int, sources: list[str], shape: str) -> dict:
    record = g2.synthetic_record(seed, "seasonal", sources, shape=shape)
    record["truth"] = None
    return record


def g2_injection(seed: int, background: str) -> dict:
    record = g2.injection_record(seed, background)
    record["truth"] = None
    return record


def injection_for(seed: int, start: int, bg: list[str]) -> dict:
    index = seed - start
    background = bg[(index // INJECTIONS_PER_BACKGROUND) % len(bg)]
    if index % INJECTIONS_PER_BACKGROUND in (0, 1):
        return ephemeral_injection(seed, background)
    return g2_injection(seed, background)  # G2 picks the shape from the seed: even `sine`, odd `pulse`


def main_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [ephemeral_synthetic(s, sources) for s in S_EPHEMERAL]
    records += [g2_synthetic(s, sources, "pulse") for s in S_PULSE]
    records += [g2_synthetic(s, sources, "sine") for s in S_SINE]
    records += [injection_for(s, I_SEEDS.start, bg) for s in I_SEEDS]
    return records


def pilot_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = []
    for i, s in enumerate(PILOT_S):
        if i < 120:
            records.append(ephemeral_synthetic(s, sources))
        else:
            records.append(g2_synthetic(s, sources, "pulse" if i < 160 else "sine"))
    for i, s in enumerate(PILOT_I):
        background = bg[(i * 3) % len(bg)]
        records.append(ephemeral_injection(s, background) if i % 4 in (0, 1) else g2_injection(s, background))
    return records


# ---------------------------------------------------------------- the candidate


def low_run(frame: pd.DataFrame, boundary: pd.Timestamp, noise_pp: float, amplitude_pp: float) -> dict:
    """The boundary's low run, followed past the search window over unobserved months."""
    from hydroseason._boundary import _epsilon_pp

    if boundary not in frame.index or pd.isna(frame.at[boundary, "extent_pct"]):
        return {"run_start": None, "run_end": None, "rewet": None, "end_status": None, "level": None, "eps": None}
    level = float(frame.at[boundary, "extent_pct"])
    eps = float(_epsilon_pp(frame.loc[boundary], noise_pp=noise_pp, amplitude_pp=amplitude_pp))
    observed = (frame["quality_state"] == "usable").to_numpy()
    values = frame["extent_pct"].to_numpy(float)
    months = list(frame.index)
    pos = months.index(boundary)
    end, rewet = pos, None
    for i in range(pos + 1, len(months)):
        if not observed[i]:
            continue
        if values[i] <= level + eps:
            end = i
        else:
            rewet = i
            break
    start = pos
    for i in range(pos - 1, -1, -1):
        if not observed[i]:
            continue
        if values[i] <= level + eps:
            start = i
        else:
            break
    if rewet is None:
        status = "censored"
    elif midx(months[rewet]) == midx(months[end]) + 1:
        status = "point"
    else:
        status = "interval"
    return {"run_start": midx(months[start]), "run_end": midx(months[end]),
            "rewet": None if rewet is None else midx(months[rewet]), "end_status": status,
            "level": level, "eps": eps}


def annotate(frame_counts: pd.DataFrame, analysis) -> list[dict]:
    from hydroseason._boundary import robust_scale
    from hydroseason._state_input import prepare_monthly_extent

    frame = prepare_monthly_extent(frame_counts, max_invalid_pct=analysis.max_invalid_pct, quality_policy="flag")
    amplitude, noise = robust_scale(frame)
    out = []
    for _, row in analysis.hydro_years.iterrows():
        t = row.get("trough_month")
        run = low_run(frame, pd.Timestamp(t), noise, amplitude) if pd.notna(t) else low_run(frame, None, 0, 0)
        out.append(run)
    return out


def _counts_frame(rows: dict) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]
    return frame[["n_water", "n_valid", "n_invalid", "n_aoi"]]


def _run(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    key, rows = payload
    counts = _counts_frame(rows)
    started = time.perf_counter()
    record = {"key": key}
    try:
        analysis = analyze_catchment(counts, phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    runs = annotate(counts, analysis) if len(hy) else []
    cycles = []
    for (_, row), run in zip(hy.iterrows(), runs):
        cycle = {
            "hy_year": row.get("hy_year"),
            "trough": g1.month_index(row.get("trough_month")), "peak": g1.month_index(row.get("peak_month")),
            "low_run_start": g1.month_index(row.get("low_run_start_month")),
            "low_run_end": g1.month_index(row.get("low_run_end_month")),
            "trough_interval_start": g1.month_index(row.get("trough_interval_start")),
            "trough_timing_status": row.get("trough_timing_status"),
            "peak_timing_status": row.get("peak_timing_status"), "timing_status": row.get("timing_status"),
            "status": row.get("status"), "boundary_status": row.get("boundary_status"),
            "ratio": row.get("amplitude_to_floor_ratio"), "baseline_eligible": row.get("baseline_eligible"),
            "radius": row.get("trough_search_radius_used"),
        }
        cycle.update(run)
        cycles.append(cycle)
    config = {}
    if analysis.state is not None:
        config = {"expected_trough_month": analysis.state.config.expected_trough_month}
    record.update(route=analysis.route, error=None, cycles=cycles, config=config,
                  fingerprint=analysis.method_policy_fingerprint, seconds=round(time.perf_counter() - started, 2))
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


def _keyed(series: pd.Series) -> dict:
    return {"|".join(map(str, k)) if isinstance(k, tuple) else str(k): (v.item() if hasattr(v, "item") else v)
            for k, v in series.items()}


def load_runs(path: Path) -> dict[str, dict]:
    return {r["key"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x)}


# ---------------------------------------------------------------- pairs and truth


def grade(width: int) -> str:
    """0.3.0's width grading of a trough label (covers_trough_boundary)."""
    return "point" if width <= 1 else "interval" if width <= 3 else "broad" if width <= 6 else "unresolved"


RANK = {"point": 3, "interval": 2, "broad": 1, "unresolved": 0}


def weaker(a, b) -> str:
    if a not in RANK or b not in RANK:
        return "unresolved"
    return a if RANK[a] <= RANK[b] else b


def pairs(record: dict, run: dict) -> list[dict]:
    """One pair per reported dated peak: the last boundary before it, scored current against candidate."""
    if run.get("route") != "per_year_detection":
        return []
    cycles = [c for c in run["cycles"] if c.get("trough") is not None]
    boundaries = sorted(c["trough"] for c in cycles)
    by_trough = {c["trough"]: c for c in cycles}
    out = []
    for c in run["cycles"]:
        p = c.get("peak")
        if p is None or c.get("peak_timing_status") not in DATED:
            continue
        before = [t for t in boundaries if t < p]
        if not before:
            continue
        t = before[-1]
        owner = by_trough[t]
        e = owner.get("run_end")
        if e is None:
            continue
        truth_end, pulse_before, in_wet = None, False, True
        if record["shape"] == "ephemeral":
            ends = [o - 1 for o in record["truth"]["onsets"] if o - 1 < p]
            if not ends:
                continue
            # A wet season spans its onset to its tail, at most 4 months; a pulse or noise read
            # as the peak is outside every wet season and is reported, not scored.
            in_wet = any(o <= p <= o + 3 for o in record["truth"]["onsets"])
            truth_end = max(ends)
            previous = [o for o in record["truth"]["onsets"] if o - 1 < truth_end]
            pulse_before = any((not previous or p_ > previous[-1]) and p_ <= truth_end
                               for p_ in record["truth"]["pulses"])
            err_current, err_candidate = t - truth_end, e - truth_end
            abs_current, abs_candidate = abs(err_current), abs(err_candidate)
        else:
            abs_current = g2.truth_error(t, record["trough_month"], record["shape"])
            abs_candidate = g2.truth_error(e, record["trough_month"], record["shape"])
            err_current = err_candidate = None
        span_start = owner.get("trough_interval_start")
        span_grade = owner.get("trough_timing_status")
        if e > t and owner.get("trough_timing_status") in DATED and span_start is not None:
            span_grade = grade(e - span_start + 1)
        end_grade = {"point": "point", "interval": "interval"}.get(owner.get("end_status"), "unresolved")
        out.append({
            "key": record["key"], "arm": record["arm"], "shape": record["shape"], "n_aoi": record["n_aoi"],
            "t": t, "e": e, "p": p, "moved": e > t, "move": e - t, "end_status": owner.get("end_status"),
            "err_current": err_current, "err_candidate": err_candidate,
            "correct_current": abs_current <= 1, "correct_candidate": abs_candidate <= 1,
            "ratio": c.get("ratio"), "pulse_before": pulse_before, "peak_in_wet": in_wet,
            "no_wet_before": truth_end is not None and (t <= truth_end - 12),
            "timing_now": owner.get("timing_status"),
            "timing_if_span": weaker(owner.get("peak_timing_status"), span_grade) if e > t else owner.get("timing_status"),
            "timing_if_end": weaker(owner.get("peak_timing_status"), end_grade) if e > t else owner.get("timing_status"),
        })
    return out


def wet_seasons(record: dict) -> int:
    if record["shape"] != "ephemeral":
        return 0
    return len(record["truth"]["onsets"])


# ---------------------------------------------------------------- statistics


def wilson_upper(k: int, n: int) -> float | None:
    return g2.wilson_upper(k, n)


def bootstrap_difference(table: pd.DataFrame, seed: int) -> dict:
    """Candidate minus current share correct, pooled over pairs, with a record bootstrap."""
    if table.empty:
        return {"pairs": 0, "records": 0, "evaluable": False}
    per = table.groupby("key").agg(n=("correct_current", "size"), cur=("correct_current", "sum"),
                                   cand=("correct_candidate", "sum"))
    n, cur, cand = per["n"].to_numpy(float), per["cur"].to_numpy(float), per["cand"].to_numpy(float)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(N_BOOT):
        pick = rng.integers(0, len(per), len(per))
        total = n[pick].sum()
        draws.append((cand[pick].sum() - cur[pick].sum()) / total)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"pairs": int(n.sum()), "records": int(len(per)), "evaluable": True,
            "current": float(cur.sum() / n.sum()), "candidate": float(cand.sum() / n.sum()),
            "difference": float((cand.sum() - cur.sum()) / n.sum()), "ci95": [float(lo), float(hi)]}


# ---------------------------------------------------------------- stages


def stage_identity() -> None:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    failures = []
    for i in range(IDENTITY_SEEDS):
        for shape in ("pulse", "sine"):
            ours = g2_synthetic(S_PULSE.start + i, sources, shape)
            theirs = g2.synthetic_record(S_PULSE.start + i, "seasonal", sources, shape=shape)
            if ours["rows"] != theirs["rows"]:
                failures.append(f"S|{shape}|{i}")
        seed = I_SEEDS.start + 4 * i + 2 + (i % 2)
        ours = injection_for(seed, I_SEEDS.start, bg)
        theirs = g2.injection_record(seed, bg[(seed - I_SEEDS.start) // INJECTIONS_PER_BACKGROUND])
        if ours["rows"] != theirs["rows"] or ours["shape"] != theirs["shape"]:
            failures.append(f"I|{seed}")
    shapes = Counter(injection_for(s, I_SEEDS.start, bg)["shape"] for s in I_SEEDS)
    result = {"pairs": 3 * IDENTITY_SEEDS, "failures": failures, "arm_i_shapes": dict(shapes)}
    (OUT / "identity.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    log(f"identity: {result}")


def _unit_cases() -> list[str]:
    """Hand-built series for low_run: expected run end, rewet and status."""
    months = pd.date_range("2000-01-01", periods=12, freq="MS")

    def frame(values, invalid):
        f = pd.DataFrame({"extent_pct": values, "invalid_pct": invalid}, index=months)
        f["quality_state"] = np.where(f["extent_pct"].isna(), "missing", np.where(f["invalid_pct"] > 20, "low", "usable"))
        return f

    failures = []
    zero = [0.0] * 12
    # Flat zero run to month 9, water at 10: end 9, point.
    v = zero.copy(); v[0] = 5.0; v[10] = 4.0; v[11] = 6.0
    r = low_run(frame(v, [0.0] * 12), months[3], 0.0, 6.0)
    if (r["run_end"], r["end_status"]) != (midx(months[9]), "point"):
        failures.append(f"flat {r}")
    # Cloudy month 9 (reads 0 under cloud), water at 10: end 8, interval.
    inv = [0.0] * 12; inv[9] = 60.0
    r = low_run(frame(v, inv), months[3], 0.0, 6.0)
    if (r["run_end"], r["end_status"]) != (midx(months[8]), "interval"):
        failures.append(f"cloud {r}")
    # Mid-dry pulse at 6 ends the run at 5.
    w = v.copy(); w[6] = 2.0
    r = low_run(frame(w, [0.0] * 12), months[3], 0.0, 6.0)
    if (r["run_end"], r["rewet"], r["end_status"]) != (midx(months[5]), midx(months[6]), "point"):
        failures.append(f"pulse {r}")
    # Dry to the end of the record: censored.
    r = low_run(frame([5.0] + [0.0] * 11, [0.0] * 12), months[3], 0.0, 6.0)
    if (r["run_end"], r["end_status"]) != (midx(months[11]), "censored"):
        failures.append(f"censored {r}")
    return failures


def stage_check(workers: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    unit = _unit_cases()
    sources = g2.valid_sources()
    records = [ephemeral_synthetic(CHECK_SEEDS_START + m, sources, noise_free=True, mean_onset=m) for m in range(1, 13)]
    sink = OUT / "check.jsonl"
    if sink.exists():
        sink.unlink()
    run_records(records, sink, workers)
    runs = load_runs(sink)
    rows, mismatches = [], []
    for record in records:
        for pair in pairs(record, runs[record["key"]]):
            rows.append(pair)
            if pair["peak_in_wet"] and not pair["pulse_before"] and pair["err_candidate"] != 0:
                mismatches.append({k: pair[k] for k in ("key", "t", "e", "p", "err_candidate", "err_current")})
    table = pd.DataFrame(rows)
    result = {
        "unit_case_failures": unit,
        "records": len(records), "routes": dict(Counter(r["route"] for r in runs.values())),
        "pairs": len(table), "pairs_without_pulse": int((~table["pulse_before"]).sum()) if len(table) else 0,
        "candidate_mismatches_without_pulse": mismatches,
        "current_error_months": dict(Counter(int(x) for x in table["err_current"])) if len(table) else {},
        "current_boundary_calendar_months": dict(Counter(int(t % 12 + 1) for t in table["t"])) if len(table) else {},
    }
    (OUT / "check.json").write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"check: unit failures {unit}; pairs {result['pairs']}; candidate mismatches without pulse {len(mismatches)}")


def stage_pilot(workers: int) -> None:
    records = pilot_records()
    sink = OUT / "pilot.jsonl"
    run_records(records, sink, workers)
    runs = load_runs(sink)
    meta = {r["key"]: r for r in records}
    rows = [p for k, run in runs.items() for p in pairs(meta[k], run)]
    table = pd.DataFrame(rows)
    within = []
    for k, run in runs.items():
        for c in run.get("cycles", []):
            if c.get("low_run_end") is not None and c.get("run_end") is not None and c.get("trough") is not None:
                within.append(c["run_end"] >= c["low_run_end"])
    result = {
        "records": len(records), "errors": sorted(k for k, r in runs.items() if r.get("error")),
        "routes": dict(Counter(f"{meta[k]['arm']}|{meta[k]['shape']}|{r['route']}" for k, r in runs.items())),
        "seconds_median": float(np.median([r.get("seconds", 0) for r in runs.values()])),
        "pairs_by_arm_shape": _keyed(table.groupby(["arm", "shape"]).size()) if len(table) else {},
        "pairs_with_peak_outside_wet": int((~table["peak_in_wet"]).sum()) if len(table) else 0,
        "moved_share_by_arm_shape": _keyed(table.groupby(["arm", "shape"])["moved"].mean().round(3)) if len(table) else {},
        "moved_3plus_share_by_arm_shape": _keyed(table.assign(m3=table["move"] >= 3).groupby(["arm", "shape"])["m3"]
                                                 .mean().round(3)) if len(table) else {},
        "run_end_not_before_library_run_end": f"{sum(within)} of {len(within)}",
    }
    (OUT / "pilot.json").write_text(json.dumps(g1.clean(result), indent=2, default=str) + "\n", encoding="utf-8")
    log(f"pilot: {json.dumps(g1.clean(result), default=str)[:1500]}")


def stage_freeze() -> None:
    records = main_records()
    corpus = OUT / "corpus.jsonl.gz"
    with gzip.open(corpus, "wt", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(g1.clean(record)) + "\n")
    from hydroseason._method_policy import method_policy_fingerprint

    here = Path(__file__)
    receipt = {
        "plan_sha256_lf": g1.sha256_lf(PLAN),
        "script_sha256_lf": g1.sha256_lf(here),
        "g2_script_sha256_lf": g1.sha256_lf(here.with_name("known_truth_gates.py")),
        "g1_script_sha256_lf": g1.sha256_lf(here.with_name("gate_calibration.py")),
        "seeds": {"S_ephemeral": [S_EPHEMERAL.start, S_EPHEMERAL.stop], "S_pulse": [S_PULSE.start, S_PULSE.stop],
                  "S_sine": [S_SINE.start, S_SINE.stop], "I": [I_SEEDS.start, I_SEEDS.stop]},
        "corpus_records": len(records),
        "corpus_digest": g2.corpus_digest(records),
        "library_fingerprint": method_policy_fingerprint(),
        "identity": json.loads((OUT / "identity.json").read_text(encoding="utf-8")),
        "check": json.loads((OUT / "check.json").read_text(encoding="utf-8")),
    }
    RECEIPT.write_text(json.dumps(g1.clean(receipt), indent=2) + "\n", encoding="utf-8")
    log(f"freeze: {len(records)} records, digest {receipt['corpus_digest'][:12]}")


def stage_run(workers: int) -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if receipt["plan_sha256_lf"] != g1.sha256_lf(PLAN) or receipt["script_sha256_lf"] != g1.sha256_lf(Path(__file__)):
        raise SystemExit("plan or script changed since the freeze")
    with gzip.open(OUT / "corpus.jsonl.gz", "rt", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    run_records(records, OUT / "main.jsonl", workers)


def _summary(table: pd.DataFrame, seed: int) -> dict:
    return bootstrap_difference(table, seed)


def stage_evaluate() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    with gzip.open(OUT / "corpus.jsonl.gz", "rt", encoding="utf-8") as handle:
        records = {r["key"]: r for r in (json.loads(line) for line in handle if line.strip())}
    runs = load_runs(OUT / "main.jsonl")
    every = pd.DataFrame([p for k, run in runs.items() for p in pairs(records[k], run)])
    every["ratio"] = pd.to_numeric(every["ratio"], errors="coerce")
    outside = every[~every["peak_in_wet"]]
    table = every[every["peak_in_wet"]]
    decision_rules, reported = {}, {}
    for arm in ("S", "I"):
        a = table[table["arm"] == arm]
        eph, sine, pulse = a[a["shape"] == "ephemeral"], a[a["shape"] == "sine"], a[a["shape"] == "pulse"]
        r1 = _summary(eph, 101 if arm == "S" else 102)
        r2 = _summary(sine, 201 if arm == "S" else 202)
        point = a[a["end_status"] == "point"]
        k = int((~point["correct_candidate"]).sum())
        upper = wilson_upper(k, len(point))
        decision_rules[arm] = {
            "rule_1": {**r1, "outcome": "holds" if r1.get("evaluable") and r1["ci95"][0] > 0 else "fails"},
            "rule_2": {**r2, "outcome": "holds" if r2.get("evaluable") and r2["ci95"][0] >= -0.05 else "fails"},
            "rule_3": {"point_ends": len(point), "not_correct": k, "share": k / len(point) if len(point) else None,
                       "wilson_upper": upper,
                       "outcome": "holds" if upper is not None and upper <= 0.05 else "fails"},
        }
        rep = {"pulse": _summary(pulse, 301 if arm == "S" else 302)}
        for lo, hi in RATIO_BANDS:
            band = eph[(eph["ratio"] >= lo) & (eph["ratio"] < hi)]
            rep[f"ephemeral_ratio_{lo}_{hi}"] = _summary(band, 400 + lo)
        for name, mask in (("area_lt_100", eph["n_aoi"] < 100), ("area_100_1000", (eph["n_aoi"] >= 100) & (eph["n_aoi"] < 1000)),
                           ("area_ge_1000", eph["n_aoi"] >= 1000), ("no_wet_before", eph["no_wet_before"]),
                           ("pulse_before", eph["pulse_before"]), ("neither", ~eph["no_wet_before"] & ~eph["pulse_before"])):
            rep[f"ephemeral_{name}"] = _summary(eph[mask], 500 + len(name))
        rep["moved_share"] = a.groupby("shape")["moved"].mean().round(4).to_dict()
        rep["move_months"] = {s: dict(Counter(int(x) for x in g["move"])) for s, g in a.groupby("shape")}
        rep["signed_errors_ephemeral"] = {
            "current": dict(Counter(int(x) for x in eph["err_current"].dropna())),
            "candidate": dict(Counter(int(x) for x in eph["err_candidate"].dropna()))}
        rep["end_status"] = {s: {"pairs": int(len(g)), "correct": float(g["correct_candidate"].mean())}
                             for s, g in a.groupby("end_status")}
        seasons = sum(wet_seasons(r) for r in records.values() if r["arm"] == arm)
        rep["coverage_ephemeral"] = {"wet_seasons": seasons, "pairs": int(len(eph)),
                                     "peaks_outside_wet_seasons": _summary(outside[outside["arm"] == arm], 600)}
        moved = a[a["moved"]]
        rep["timing_of_moved_pairs"] = {
            "now": dict(Counter(moved["timing_now"].fillna("none"))),
            "if_graded_by_span": dict(Counter(moved["timing_if_span"].fillna("none"))),
            "if_graded_by_end_status": dict(Counter(moved["timing_if_end"].fillna("none")))}
        reported[arm] = rep
    holds = {arm: all(decision_rules[arm][r]["outcome"] == "holds" for r in ("rule_1", "rule_2")) for arm in ("S", "I")}
    r1_fails = any(decision_rules[arm]["rule_1"]["outcome"] == "fails" for arm in ("S", "I"))
    r2_fails = any(decision_rules[arm]["rule_2"]["outcome"] == "fails" for arm in ("S", "I"))
    if all(holds.values()):
        decision = "A and B go to implementation"
    elif not r1_fails and r2_fails:
        decision = "A only, as a reported column; B not adopted"
    elif r1_fails:
        decision = "neither; no change"
    else:
        decision = "inconclusive; no change"
    rule_3 = all(decision_rules[arm]["rule_3"]["outcome"] == "holds" for arm in ("S", "I"))
    result = {
        "receipt_sha256_lf": g1.sha256_lf(RECEIPT), "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "records": len(runs), "errors": sorted(k for k, r in runs.items() if r.get("error")),
        "fingerprints": sorted({r.get("fingerprint") for r in runs.values() if r.get("fingerprint")}),
        "pairs": int(len(table)), "decision": decision, "point_status_allowed": rule_3,
        "rules": decision_rules, "reported": reported,
    }
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2, default=str) + "\n", encoding="utf-8")
    log(f"evaluate: {decision}; point allowed {rule_3}")


def stage_real(workers: int) -> None:
    """Reported only: the candidate on the stored v0.3.0 real-record runs (G1 windows, spatial-unit units)."""
    import real_record_impact as rri

    stored = load_runs(V030_RUNS)
    frames = rri.series_frames()
    jobs = [(k, frames[k].to_dict(orient="list"), r["cycles"]) for k, r in stored.items()
            if r["route"] == "per_year_detection" and r["cycles"] and k in frames]
    log(f"real: {len(jobs)} records")
    out = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for key, ends in pool.map(_real_one, jobs, chunksize=8):
            out[key] = ends
    units = pd.read_csv(rri.SU / "units.csv").set_index("unit_id")
    rows = []
    for key, ends in out.items():
        source = "|".join(map(str, rri.scale_of(key, units)))
        for c in ends:
            rows.append({"key": key, "source": source, **c})
    table = pd.DataFrame(rows)
    table = table[table["t"].notna() & table["e"].notna()]
    table["move"] = table["e"] - table["t"]
    summary = {}
    for source, g in table.groupby("source"):
        summary[source] = {"cycles": int(len(g)), "moved": float((g["move"] > 0).mean()),
                           "moved_3plus": float((g["move"] >= 3).mean()), "moved_6plus": float((g["move"] >= 6).mean()),
                           "end_status": dict(Counter(g["end_status"].fillna("none")))}
    halves = []
    g1_rows = table[table["key"].str.startswith("g1|")].copy()
    g1_rows["place"] = g1_rows["key"].str.rsplit("|", n=1).str[0]
    g1_rows["half"] = g1_rows["key"].str.rsplit("|", n=1).str[1]
    for (place, year), g in g1_rows.groupby(["place", "hy_year"]):
        if set(g["half"]) != {"A", "B"}:
            continue
        a, b = g[g["half"] == "A"].iloc[0], g[g["half"] == "B"].iloc[0]
        halves.append({"current": abs(a["t"] - b["t"]) <= 1, "candidate": abs(a["e"] - b["e"]) <= 1})
    h = pd.DataFrame(halves)
    result = {"script_sha256_lf": g1.sha256_lf(Path(__file__)), "records": len(out), "by_source": summary,
              "g1_half_agreement_within_1": {"pairs": int(len(h)), "current": float(h["current"].mean()),
                                             "candidate": float(h["candidate"].mean())}}
    REAL_RESULTS.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"real: {json.dumps(g1.clean(result))[:800]}")


def _real_one(job):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason._boundary import robust_scale
    from hydroseason._state_input import prepare_monthly_extent

    key, rows, cycles = job
    counts = _counts_frame(rows)
    frame = prepare_monthly_extent(counts, max_invalid_pct=20.0, quality_policy="flag")
    amplitude, noise = robust_scale(frame)
    out = []
    for c in cycles:
        t = c.get("trough_month")
        if t is None:
            continue
        stamp = pd.Timestamp(year=t // 12, month=t % 12 + 1, day=1)
        run = low_run(frame, stamp, noise, amplitude)
        out.append({"hy_year": c.get("hy_year"), "t": t, "e": run["run_end"], "end_status": run["end_status"]})
    return key, out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=("identity", "check", "pilot", "freeze", "run", "evaluate", "real"))
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    {"identity": lambda: stage_identity(), "check": lambda: stage_check(args.workers),
     "pilot": lambda: stage_pilot(args.workers), "freeze": lambda: stage_freeze(),
     "run": lambda: stage_run(args.workers), "evaluate": lambda: stage_evaluate(),
     "real": lambda: stage_real(args.workers)}[args.stage]()


if __name__ == "__main__":
    main()
