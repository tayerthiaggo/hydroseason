"""DE2: the year boundary at the end of the low, against known truth.

Plan: docs/handoff/2026-11-08-de2-end-of-low-plan.md. The candidate (R1, search anchor at
the end of the typical low; R2, a boundary at the end of a dry zero-extent low is dated by
where the low ends) is on branch research/refinement-end-of-low; the current library is
method-v0.3.0 at c85d913. Each record is analysed by both libraries, in separate runs:
choose the library with PYTHONPATH and name it with --library.

Records reuse DE1's generators (scripts/known_truth_de1.py, imported, not edited) and G2's
with fresh seeds. Scoring is one score per true dry-season end: a hit is a reported
boundary within one month of it; a record with no boundaries misses all its ends.

Stages:
  check     (per library) noise-free construction records and generator identity
  pilot     (per library) 280 records: run times, routes, counts only
  freeze    write the corpus and the receipt (run under the candidate)
  run       (per library) the main corpus
  evaluate  decision rules and reported breakdowns (run under the candidate)

    PYTHONPATH=<current checkout> python scripts/known_truth_de2.py run --library current
    PYTHONPATH=. python scripts/known_truth_de2.py run --library candidate
"""
from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402
import known_truth_de1 as de1  # noqa: E402
import known_truth_gates as g2  # noqa: E402

HANDOFF = g1.HANDOFF
PLAN = HANDOFF / "2026-11-08-de2-end-of-low-plan.md"
RECEIPT = HANDOFF / "2026-11-08-de2-end-of-low-receipt.json"
RESULTS = HANDOFF / "2026-11-08-de2-end-of-low-results.json"
OUT = g1.DATA / "intermediate" / "hydroseason_known_truth_de2"
REPO = Path(__file__).resolve().parent.parent

CURRENT_FINGERPRINT = "aba922a9eac29cea8498a30794110c80de340b0f6a2fb76d64f60f93855aeb66"
LIBRARIES = ("current", "candidate")
S_EPHEMERAL = range(310000, 311200)
S_PULSE = range(311200, 311600)
S_SINE = range(311600, 312000)
I_SEEDS = range(315000, 316148)
PILOT_S = range(318000, 318200)
PILOT_I = range(319000, 319080)
CHECK_SEEDS_START = 960000
N_BOOT = 2000
K_BANDS = [(0.5, 2), (2, 5), (5, 10), (10, 31)]
DATED = {"point", "interval", "broad"}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "de2.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# ---------------------------------------------------------------- records
def main_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [de1.ephemeral_synthetic(s, sources) for s in S_EPHEMERAL]
    records += [de1.g2_synthetic(s, sources, "pulse") for s in S_PULSE]
    records += [de1.g2_synthetic(s, sources, "sine") for s in S_SINE]
    records += [de1.injection_for(s, I_SEEDS.start, bg) for s in I_SEEDS]
    return records


def pilot_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = []
    for i, s in enumerate(PILOT_S):
        if i < 120:
            records.append(de1.ephemeral_synthetic(s, sources))
        else:
            records.append(de1.g2_synthetic(s, sources, "pulse" if i < 160 else "sine"))
    for i, s in enumerate(PILOT_I):
        background = bg[(i * 3) % len(bg)]
        records.append(de1.ephemeral_injection(s, background) if i % 4 in (0, 1) else de1.g2_injection(s, background))
    return records


def construction_records() -> list[dict]:
    sources = g2.valid_sources()
    return [de1.ephemeral_synthetic(CHECK_SEEDS_START + m, sources, noise_free=True, mean_onset=m) for m in range(1, 13)]


# ---------------------------------------------------------------- one library run
def _library_fingerprint() -> str:
    from hydroseason._method_policy import method_policy_fingerprint

    return method_policy_fingerprint()


def _expected_fingerprint(library: str) -> str:
    if library == "current":
        return CURRENT_FINGERPRINT
    if RECEIPT.exists():
        return json.loads(RECEIPT.read_text(encoding="utf-8"))["candidate_fingerprint"]
    return ""


def _require(library: str) -> str:
    fingerprint = _library_fingerprint()
    expected = _expected_fingerprint(library)
    if library == "current" and fingerprint != expected:
        raise SystemExit(f"--library current needs fingerprint {expected[:12]}, got {fingerprint[:12]}")
    if library == "candidate" and (fingerprint == CURRENT_FINGERPRINT or (expected and fingerprint != expected)):
        raise SystemExit(f"--library candidate needs the candidate fingerprint, got {fingerprint[:12]}")
    return fingerprint


def _run(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    key, rows = payload
    counts = de1._counts_frame(rows)
    started = time.perf_counter()
    record = {"key": key, "fingerprint": _library_fingerprint()}
    try:
        analysis = analyze_catchment(counts, phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    cycles = []
    for _, row in hy.iterrows():
        cycles.append({
            "hy_year": row.get("hy_year"),
            "trough": g1.month_index(row.get("trough_month")), "peak": g1.month_index(row.get("peak_month")),
            "trough_timing_status": row.get("trough_timing_status"),
            "trough_interval_start": g1.month_index(row.get("trough_interval_start")),
            "trough_interval_end": g1.month_index(row.get("trough_interval_end")),
            "peak_timing_status": row.get("peak_timing_status"), "timing_status": row.get("timing_status"),
            "status_reason": row.get("status_reason"),
            "trough_label_basis": row.get("trough_label_basis"),
            "dry_run_end": g1.month_index(row.get("dry_run_end_month")),
        })
    anchor = analysis.state.config.expected_trough_month if analysis.state is not None else None
    record.update(route=analysis.route, error=None, cycles=cycles, anchor=anchor,
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


def load_runs(path: Path) -> dict[str, dict]:
    return {r["key"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x)}


# ---------------------------------------------------------------- scoring
def true_ends(record: dict) -> list[int]:
    """Month indices of the true ends of the dry season inside the record."""
    months = [g1.month_index(d) for d in record["rows"]["date"]]
    first, last = months[0], months[-1]
    if record["shape"] == "ephemeral":
        return [o - 1 for o in record["truth"]["onsets"] if first + 1 <= o - 1 <= last - 1]
    m = int(record["trough_month"])
    years = range(first // 12, last // 12 + 1)
    return [y * 12 + m - 1 for y in years if first + 1 <= y * 12 + m - 1 <= last - 1]


def hit(record: dict, end: int, boundaries: list[int]) -> bool:
    if record["shape"] == "ephemeral":
        return any(abs(b - end) <= 1 for b in boundaries)
    return any(abs(b - end) <= 6 and g2.truth_error(b, int(record["trough_month"]), record["shape"]) <= 1
               for b in boundaries)


def score(record: dict, run: dict) -> dict:
    ends = true_ends(record)
    boundaries = [c["trough"] for c in run.get("cycles", []) if c.get("trough") is not None]
    hits = sum(hit(record, e, boundaries) for e in ends)
    cycles = run.get("cycles", [])
    dated = sum(c.get("timing_status") in DATED for c in cycles)
    return {"ends": len(ends), "hits": hits, "per_year": run.get("route") == "per_year_detection",
            "cycles": len(cycles), "dated": dated}


def _nearest_end(record: dict, b: int) -> int | None:
    ends = true_ends(record)
    return min(ends, key=lambda e: abs(e - b)) if ends else None


def label_rows(record: dict, run: dict) -> list[dict]:
    """Point labels and R2 labels against the truth (reported)."""
    out = []
    for c in run.get("cycles", []):
        b = c.get("trough")
        if b is None:
            continue
        if record["shape"] == "ephemeral":
            truth = _nearest_end(record, b)
            if truth is None:
                continue
            error = abs(b - truth)
        else:
            truth = None
            error = g2.truth_error(b, int(record["trough_month"]), record["shape"])
        row = {"status": c.get("trough_timing_status"), "basis": c.get("trough_label_basis"), "error": error,
               "covered": None}
        if c.get("trough_label_basis") == "end_of_dry_run" and truth is not None:
            start, end = c.get("trough_interval_start"), c.get("trough_interval_end")
            row["covered"] = start is not None and end is not None and start - 1 <= truth <= end + 1
        out.append(row)
    return out


def bootstrap_difference(table: pd.DataFrame, seed: int) -> dict:
    """Share of true ends hit, candidate minus current, with a bootstrap over records."""
    table = table[table["ends"] > 0]
    if len(table) < 20:
        return {"records": int(len(table)), "evaluable": False}
    ends = table["ends"].to_numpy(float)
    cur, cand = table["hits_current"].to_numpy(float), table["hits_candidate"].to_numpy(float)
    rng = np.random.default_rng(seed)
    draws = []
    n = len(table)
    for _ in range(N_BOOT):
        i = rng.integers(0, n, n)
        draws.append(cand[i].sum() / ends[i].sum() - cur[i].sum() / ends[i].sum())
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"records": int(n), "ends": int(ends.sum()), "evaluable": True,
            "current": float(cur.sum() / ends.sum()), "candidate": float(cand.sum() / ends.sum()),
            "difference": float((cand.sum() - cur.sum()) / ends.sum()), "ci95": [float(lo), float(hi)]}


def wilson_upper(k: int, n: int) -> float | None:
    if n == 0:
        return None
    z = 1.959963984540054
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return float((centre + margin) / (1 + z * z / n))


# ---------------------------------------------------------------- stages
def stage_check(library: str, workers: int) -> None:
    fingerprint = _require(library)
    OUT.mkdir(parents=True, exist_ok=True)
    records = construction_records()
    sink = OUT / f"check_{library}.jsonl"
    if sink.exists():
        sink.unlink()
    run_records(records, sink, workers)
    runs = load_runs(sink)
    total = exact = within = 0
    for record in records:
        run = runs[record["key"]]
        boundaries = [c["trough"] for c in run["cycles"] if c.get("trough") is not None]
        for end in true_ends(record):
            total += 1
            exact += any(b == end for b in boundaries)
            within += any(abs(b - end) <= 1 for b in boundaries)
    sources, bg = g2.valid_sources(), g2.backgrounds()
    identity = []
    for i in range(20):
        for shape in ("pulse", "sine"):
            if de1.g2_synthetic(S_PULSE.start + i, sources, shape)["rows"] != g2.synthetic_record(
                    S_PULSE.start + i, "seasonal", sources, shape=shape)["rows"]:
                identity.append(f"{shape}|{i}")
    result = {"library": library, "fingerprint": fingerprint, "construction_true_ends": total,
              "construction_exact": exact, "construction_within_1": within,
              "routes": dict(Counter(r["route"] for r in runs.values())), "identity_failures": identity,
              "arm_i_shapes": dict(Counter(de1.injection_for(s, I_SEEDS.start, bg)["shape"] for s in I_SEEDS))}
    (OUT / f"check_{library}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    log(f"check {library}: {result}")


def stage_pilot(library: str, workers: int) -> None:
    _require(library)
    sink = OUT / f"pilot_{library}.jsonl"
    run_records(pilot_records(), sink, workers)
    runs = load_runs(sink)
    seconds = [r.get("seconds", 0) for r in runs.values()]
    result = {"library": library, "records": len(runs), "routes": dict(Counter(r["route"] for r in runs.values())),
              "errors": sum(1 for r in runs.values() if r.get("error")), "seconds_median": float(np.median(seconds)),
              "seconds_total": float(np.sum(seconds)), "cycles": sum(len(r["cycles"]) for r in runs.values())}
    (OUT / f"pilot_{library}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    log(f"pilot {library}: {result}")


def stage_freeze() -> None:
    fingerprint = _library_fingerprint()
    if fingerprint == CURRENT_FINGERPRINT:
        raise SystemExit("freeze under the candidate library")
    records = main_records()
    with gzip.open(OUT / "corpus.jsonl.gz", "wt", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(g1.clean(record)) + "\n")
    digest = g2.corpus_digest(records)
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    receipt = {
        "plan_sha256_lf": g1.sha256_lf(PLAN), "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "de1_script_sha256_lf": g1.sha256_lf(Path(de1.__file__)), "g2_script_sha256_lf": g1.sha256_lf(Path(g2.__file__)),
        "current_fingerprint": CURRENT_FINGERPRINT, "current_commit": "c85d913",
        "candidate_fingerprint": fingerprint, "candidate_commit": head,
        "candidate_sources_sha256_lf": {p: g1.sha256_lf(REPO / p) for p in (
            "hydroseason/_catchment.py", "hydroseason/_dynamic_year.py", "hydroseason/_dry_run.py",
            "hydroseason/_trough_refinement.py", "hydroseason/_method_policy.py")},
        "seeds": {"S_ephemeral": [S_EPHEMERAL.start, S_EPHEMERAL.stop], "S_pulse": [S_PULSE.start, S_PULSE.stop],
                  "S_sine": [S_SINE.start, S_SINE.stop], "I": [I_SEEDS.start, I_SEEDS.stop]},
        "corpus_records": len(records), "corpus_digest": digest,
        "checks": {lib: json.loads((OUT / f"check_{lib}.json").read_text(encoding="utf-8")) for lib in LIBRARIES},
        "pilot": {lib: json.loads((OUT / f"pilot_{lib}.json").read_text(encoding="utf-8")) for lib in LIBRARIES},
    }
    RECEIPT.write_text(json.dumps(g1.clean(receipt), indent=2) + "\n", encoding="utf-8")
    log(f"freeze: {len(records)} records, digest {digest[:12]}, candidate {fingerprint[:12]} at {head[:7]}")


def _read_corpus() -> dict[str, dict]:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    with gzip.open(OUT / "corpus.jsonl.gz", "rt", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    if g2.corpus_digest(records) != receipt["corpus_digest"]:
        raise SystemExit("corpus does not match the receipt")
    return {r["key"]: r for r in records}


def stage_run(library: str, workers: int) -> None:
    _require(library)
    records = list(_read_corpus().values())
    run_records(records, OUT / f"main_{library}.jsonl", workers)


def _reviewed_gates() -> dict:
    tests = ["tests/test_gilbert_regression.py", "tests/test_fitzroy_regression.py"]
    result = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"],
                            cwd=REPO, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO)})
    return {"passed": result.returncode == 0, "summary": result.stdout.strip().splitlines()[-1:]}


def stage_evaluate() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if _library_fingerprint() != receipt["candidate_fingerprint"]:
        raise SystemExit("evaluate under the frozen candidate")
    records = _read_corpus()
    runs = {lib: load_runs(OUT / f"main_{lib}.jsonl") for lib in LIBRARIES}
    fingerprints = {lib: sorted({r.get("fingerprint") for r in runs[lib].values()}) for lib in LIBRARIES}
    rows, labels = [], []
    for key, record in records.items():
        s_cur, s_cand = score(record, runs["current"][key]), score(record, runs["candidate"][key])
        peaks_cur = {c["peak"] for c in runs["current"][key].get("cycles", []) if c.get("peak") is not None}
        peaks_cand = {c["peak"] for c in runs["candidate"][key].get("cycles", []) if c.get("peak") is not None}
        rows.append({"key": key, "arm": record["arm"], "shape": record["shape"], "k": record.get("k"),
                     "ends": s_cur["ends"], "hits_current": s_cur["hits"], "hits_candidate": s_cand["hits"],
                     "per_year_current": s_cur["per_year"], "per_year_candidate": s_cand["per_year"],
                     "cycles_current": s_cur["cycles"], "cycles_candidate": s_cand["cycles"],
                     "dated_current": s_cur["dated"], "dated_candidate": s_cand["dated"],
                     "peaks_changed": len(peaks_cur ^ peaks_cand),
                     "anchor_moved": runs["current"][key].get("anchor") != runs["candidate"][key].get("anchor")})
        for lib in LIBRARIES:
            for row in label_rows(record, runs[lib][key]):
                labels.append({**row, "library": lib, "arm": record["arm"], "shape": record["shape"]})
    table, labels = pd.DataFrame(rows), pd.DataFrame(labels)
    seeds = {("S", "ephemeral"): 101, ("I", "ephemeral"): 102, ("S", "sine"): 201, ("I", "sine"): 202,
             ("S", "pulse"): 301, ("I", "pulse"): 302}
    rules, reported = {}, {}
    for arm in ("S", "I"):
        a = table[table["arm"] == arm]
        r1 = bootstrap_difference(a[a["shape"] == "ephemeral"], seeds[(arm, "ephemeral")])
        r2 = bootstrap_difference(a[a["shape"] == "sine"], seeds[(arm, "sine")])
        r3 = bootstrap_difference(a[a["shape"] == "pulse"], seeds[(arm, "pulse")])
        rules[arm] = {
            "rule_1": {**r1, "outcome": "holds" if r1.get("evaluable") and r1["ci95"][0] > 0 else "fails"},
            "rule_2": {**r2, "outcome": "holds" if r2.get("evaluable") and r2["ci95"][0] >= -0.05 else "fails"},
            "rule_3": {**r3, "outcome": "holds" if r3.get("evaluable") and r3["ci95"][0] >= -0.05 else "fails"},
        }
        rep = {}
        eph = a[a["shape"] == "ephemeral"]
        for lo, hi in K_BANDS:
            band = eph[(eph["k"] >= lo) & (eph["k"] < hi)]
            rep[f"ephemeral_k_{lo}_{hi}"] = bootstrap_difference(band, 400 + lo)
        for shape, g in a.groupby("shape"):
            rep[f"{shape}_routing"] = {"per_year_current": int(g["per_year_current"].sum()),
                                       "per_year_candidate": int(g["per_year_candidate"].sum()), "records": len(g)}
            rep[f"{shape}_dated_share"] = {
                "current": float(g["dated_current"].sum() / max(g["cycles_current"].sum(), 1)),
                "candidate": float(g["dated_candidate"].sum() / max(g["cycles_candidate"].sum(), 1))}
            rep[f"{shape}_records_with_peak_changes"] = int((g["peaks_changed"] > 0).sum())
            rep[f"{shape}_anchor_moved"] = int(g["anchor_moved"].sum())
        al = labels[labels["arm"] == arm]
        for lib in LIBRARIES:
            point = al[(al["library"] == lib) & (al["status"] == "point")]
            k = int((point["error"] > 1).sum())
            rep[f"point_labels_{lib}"] = {"labels": len(point), "not_correct": k,
                                          "share": k / len(point) if len(point) else None,
                                          "wilson_upper": wilson_upper(k, len(point))}
        r2rows = al[(al["library"] == "candidate") & (al["basis"] == "end_of_dry_run")]
        rep["r2_labels"] = {"labels": len(r2rows), "truth_outside_interval_by_more_than_1":
                            int((r2rows["covered"] == False).sum())}  # noqa: E712
        reported[arm] = rep
    gates = _reviewed_gates()
    holds = all(rules[arm][r]["outcome"] == "holds" for arm in ("S", "I") for r in ("rule_1", "rule_2", "rule_3"))
    r1_fails = any(rules[arm]["rule_1"]["outcome"] == "fails" for arm in ("S", "I"))
    if holds and gates["passed"]:
        decision = "R1 and R2 go to the implementation checks"
    elif r1_fails or not gates["passed"] or any(rules[arm][r]["outcome"] == "fails"
                                                 for arm in ("S", "I") for r in ("rule_2", "rule_3")):
        decision = "no change"
    else:
        decision = "inconclusive; no change"
    result = {"receipt_sha256_lf": g1.sha256_lf(RECEIPT), "script_sha256_lf": g1.sha256_lf(Path(__file__)),
              "records": len(records), "fingerprints": fingerprints,
              "errors": {lib: sorted(k for k, r in runs[lib].items() if r.get("error")) for lib in LIBRARIES},
              "decision": decision, "rules": rules, "rule_4_reviewed_gates": gates, "reported": reported}
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2, default=str) + "\n", encoding="utf-8")
    log(f"evaluate: {decision}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["check", "pilot", "freeze", "run", "evaluate"])
    parser.add_argument("--library", choices=LIBRARIES)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    if args.stage in ("check", "pilot", "run") and args.library is None:
        parser.error("--library is required for this stage")
    {"check": lambda: stage_check(args.library, args.workers),
     "pilot": lambda: stage_pilot(args.library, args.workers),
     "freeze": stage_freeze, "run": lambda: stage_run(args.library, args.workers),
     "evaluate": stage_evaluate}[args.stage]()


if __name__ == "__main__":
    main()
