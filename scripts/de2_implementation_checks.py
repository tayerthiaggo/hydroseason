"""Implementation checks of DE2's R1 and revised R2 (boundary at the end of the low).

DE2 (docs/handoff/2026-11-08-de2-end-of-low-results.md) passed; the lead chose R1 with the
revised R2. These checks compare the candidate with the stored hydroseason-v0.3.0 runs on
real records. "Before" is read, never rewritten:

  case studies  data_local/intermediate/hydroseason_dry_run_end_checks/case_studies (c85d913)
  tiles         data_local/intermediate/hydroseason_refinement_eol/cycles_v030.csv (c85d913)
  real records  data_local/intermediate/hydroseason_v030_real_record_check/runs.jsonl
                (fingerprint 4d11d348; boundaries as c85d913, which added reported columns only)

Expected: boundaries move later on flat-bottomed records and rarely elsewhere; routes, cycle
counts and baselines change little; peaks can change where a cycle's window changes; events
and low-extent spells are unchanged.

Stages:
  run-cases   the five case studies, 4 resolutions each
  run-tiles   the Fitzroy tiles (scripts/refinement_eol_explore.py run --tag de2impl)
  run-real    the 4,468 real-record units
  compare     writes docs/handoff/2026-11-08-de2-implementation-checks.json

    PYTHONPATH=. python scripts/de2_implementation_checks.py run-cases
"""
from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402
import real_record_impact as rri  # noqa: E402
import refinement_eol_explore as explore  # noqa: E402
import v030_case_study_comparison as cs  # noqa: E402

INTERMEDIATE = g1.DATA / "intermediate"
OUT = INTERMEDIATE / "hydroseason_de2_implementation"
BEFORE_CASES = INTERMEDIATE / "hydroseason_dry_run_end_checks" / "case_studies"
BEFORE_REAL = INTERMEDIATE / "hydroseason_v030_real_record_check" / "runs.jsonl"
RESULTS = g1.HANDOFF / "2026-11-08-de2-implementation-checks.json"
CURRENT_FINGERPRINT = "aba922a9eac29cea8498a30794110c80de340b0f6a2fb76d64f60f93855aeb66"


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "checks.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _fingerprint() -> str:
    from hydroseason._method_policy import method_policy_fingerprint

    fingerprint = method_policy_fingerprint()
    if fingerprint == CURRENT_FINGERPRINT:
        raise SystemExit("run under the candidate library")
    return fingerprint


def stage_run_cases() -> None:
    log(f"run-cases {_fingerprint()[:12]}")
    cs.stage_run(OUT / "case_studies")


def stage_run_tiles(workers: int) -> None:
    log(f"run-tiles {_fingerprint()[:12]}")
    explore.stage_run(workers, "de2impl")


def _run_real(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment
    from hydroseason._method_policy import method_policy_fingerprint

    key, rows = payload
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]
    record = {"key": key, "fingerprint": method_policy_fingerprint()}
    try:
        analysis = analyze_catchment(frame[["n_water", "n_valid", "n_invalid", "n_aoi"]],
                                     phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    cycles = [{"hy_year": r.get("hy_year"), "trough_month": g1.month_index(r.get("trough_month")),
               "peak_month": g1.month_index(r.get("peak_month")), "timing_status": r.get("timing_status"),
               "trough_timing_status": r.get("trough_timing_status"), "baseline_eligible": r.get("baseline_eligible"),
               "trough_label_basis": r.get("trough_label_basis")} for _, r in hy.iterrows()]
    config = {"min_baseline_cycles": analysis.state.config.min_baseline_cycles} if analysis.state is not None else {}
    record.update(route=analysis.route, error=None, cycles=cycles, config=config)
    return record


def stage_run_real(workers: int) -> None:
    fingerprint = _fingerprint()
    sink = OUT / "real.jsonl"
    done = set()
    if sink.exists():
        done = {json.loads(x)["key"] for x in sink.read_text(encoding="utf-8").splitlines() if x}
    frames = rri.series_frames()
    payloads = [(k, f.to_dict(orient="list")) for k, f in frames.items() if k not in done]
    log(f"run-real: {len(payloads)} of {len(frames)} records, fingerprint {fingerprint[:12]}")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run_real, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 200 == 0 or n == len(futures):
                log(f"run-real: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- compare
def compare_cases() -> dict:
    after = OUT / "case_studies"
    series = {}
    for key in cs.CATCHMENTS:
        for res in cs.RESOLUTIONS:
            stem = f"{key}_{res}"
            sb = json.loads((BEFORE_CASES / f"{stem}_summary.json").read_text(encoding="utf-8"))
            sa = json.loads((after / f"{stem}_summary.json").read_text(encoding="utf-8"))
            hb, ha = cs._read(BEFORE_CASES / f"{stem}_hydro_years.csv"), cs._read(after / f"{stem}_hydro_years.csv")
            entry = {"route": [sb["route"], sa["route"]], "years": [len(hb), len(ha)]}
            if len(hb) and len(hb) == len(ha):
                def months(frame, column):
                    return pd.to_datetime(frame[column]).dt.strftime("%Y-%m").tolist()
                b0, b1 = months(hb, "trough_month"), months(ha, "trough_month")
                p0, p1 = months(hb, "peak_month"), months(ha, "peak_month")
                shifts = [(pd.Timestamp(y).year - pd.Timestamp(x).year) * 12 + pd.Timestamp(y).month - pd.Timestamp(x).month
                          for x, y in zip(b0, b1) if x != y and x != "NaT" and y != "NaT"]
                entry.update({
                    "boundaries_moved": len(shifts), "shift_months": dict(Counter(shifts)),
                    "peaks_changed": sum(x != y for x, y in zip(p0, p1)),
                    "trough_labels_changed": int((hb["trough_timing_status"].astype(str) != ha["trough_timing_status"].astype(str)).sum()),
                    "timing_changed": int((hb["timing_status"].astype(str) != ha["timing_status"].astype(str)).sum()),
                    "r2_labels": int((ha["trough_label_basis"] == "end_of_dry_run").sum()),
                    "eligible": [int(hb["baseline_eligible"].fillna(False).astype(bool).sum()),
                                 int(ha["baseline_eligible"].fillna(False).astype(bool).sum())],
                    "labelled": [int(hb["recharge_condition"].isin(["low", "typical", "high"]).sum()),
                                 int(ha["recharge_condition"].isin(["low", "typical", "high"]).sum())],
                })
            series[stem] = entry
    tables = {}
    for path in sorted((BEFORE_CASES / "reports").rglob("*.csv")):
        if path.name.endswith(("_wet_event.csv", "_low_spells.csv")):
            other = after / "reports" / path.relative_to(BEFORE_CASES / "reports")
            same = other.exists() and cs._read(path).equals(cs._read(other))
            tables[str(path.relative_to(BEFORE_CASES / "reports"))] = "identical" if same else "changed"
    return {"series": series, "event_and_spell_tables": tables}


def compare_real() -> dict:
    before = {r["key"]: r for r in map(json.loads, BEFORE_REAL.read_text(encoding="utf-8").splitlines()) if r}
    after = {r["key"]: r for r in map(json.loads, (OUT / "real.jsonl").read_text(encoding="utf-8").splitlines()) if r}
    units = pd.read_csv(rri.SU / "units.csv").set_index("unit_id")
    routes, counts, moves, peaks, timing, r2, baseline = Counter(), Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    cycles_by_source: Counter = Counter()
    g1_rows = []
    for key, a in before.items():
        b = after.get(key)
        source = "|".join(map(str, rri.scale_of(key, units)))
        if b is None or a["route"] != b["route"]:
            routes[f"{source}|{a['route']}->{b['route'] if b else 'missing'}"] += 1
            continue
        if len(a["cycles"]) != len(b["cycles"]):
            counts[source] += 1
        # Match by date, not by row: when R1 moves the anchor across January the
        # hydrological-year labels shift by one, so row k before and row k after
        # can be different seasons. Each new boundary is paired with the nearest
        # old boundary within six months.
        old = [c for c in a["cycles"] if c.get("trough_month") is not None]
        old_peaks = {c.get("peak_month") for c in a["cycles"] if c.get("peak_month") is not None}
        for cb in b["cycles"]:
            t1 = cb.get("trough_month")
            if t1 is None:
                continue
            cycles_by_source[source] += 1
            near = min(old, key=lambda c: abs(c["trough_month"] - t1)) if old else None
            if near is None or abs(near["trough_month"] - t1) > 6:
                moves[f"{source}|unmatched"] += 1
                continue
            shift = t1 - near["trough_month"]
            moves[f"{source}|{'same' if shift == 0 else 'later 1-2' if 0 < shift <= 2 else 'later 3+' if shift > 2 else 'earlier 1-2' if shift >= -2 else 'earlier 3+'}"] += 1
            if cb.get("peak_month") is not None and cb.get("peak_month") not in old_peaks:
                peaks[source] += 1
            if near.get("timing_status") != cb.get("timing_status"):
                timing[f"{source}|{near.get('timing_status')}->{cb.get('timing_status')}"] += 1
            r2[source] += cb.get("trough_label_basis") == "end_of_dry_run"
        if key.startswith("g1|"):
            for cb in b["cycles"]:
                t1 = cb.get("trough_month")
                near = min(old, key=lambda c: abs(c["trough_month"] - t1)) if old and t1 is not None else None
                g1_rows.append({"place": key.rsplit("|", 1)[0], "half": key.rsplit("|", 1)[1],
                                "hy_year": cb.get("hy_year"), "after": t1})
            for ca in a["cycles"]:
                g1_rows.append({"place": key.rsplit("|", 1)[0], "half": key.rsplit("|", 1)[1],
                                "hy_year_before": ca.get("hy_year"), "before": ca.get("trough_month")})
        if b["route"] == "per_year_detection" and b.get("config"):
            minimum = b["config"]["min_baseline_cycles"]
            n0 = sum(bool(c.get("baseline_eligible")) for c in a["cycles"])
            n1 = sum(bool(c.get("baseline_eligible")) for c in b["cycles"])
            baseline[f"{source}|{n0 >= minimum}->{n1 >= minimum}"] += 1
    halves = []
    table = pd.DataFrame(g1_rows)
    # Half agreement is within one library: the two pixel halves of a place, same year label.
    for column, year in (("before", "hy_year_before"), ("after", "hy_year")):
        part = table.dropna(subset=[column, year])
        for (_, _), g in part.groupby(["place", year]):
            if set(g["half"]) != {"A", "B"}:
                continue
            x, y = g[g["half"] == "A"].iloc[0], g[g["half"] == "B"].iloc[0]
            halves.append({"library": column, "agree": abs(x[column] - y[column]) <= 1})
    h = pd.DataFrame(halves)
    return {"records": len(after), "fingerprints": dict(Counter(r.get("fingerprint") for r in after.values())),
            "errors": sorted(k for k, r in after.items() if r.get("error")),
            "route_changes": dict(routes), "cycle_count_changes": dict(counts), "cycles": dict(cycles_by_source),
            "boundary_moves": dict(sorted(moves.items())), "peaks_changed": dict(peaks),
            "timing_changes": dict(sorted(timing.items())), "r2_labels": dict(r2),
            "units_with_baseline": dict(sorted(baseline.items())),
            "g1_half_agreement_within_1": {lib: {"pairs": int((h["library"] == lib).sum()),
                                                 "share": float(h.loc[h["library"] == lib, "agree"].mean())}
                                           for lib in ("before", "after")}}


def stage_compare() -> None:
    from hydroseason._method_policy import method_policy_fingerprint

    explore_out = explore.OUT
    a = pd.read_csv(explore_out / "cycles_v030.csv", dtype=str, keep_default_na=False)
    b = pd.read_csv(explore_out / "cycles_de2impl.csv", dtype=str, keep_default_na=False)
    gap = lambda t: pd.Series([explore._months(x, y) if x and y else None for x, y in zip(t.boundary, t.dry_run_end)], dtype=float)
    tiles = {"late3": [int((gap(a) >= 3).sum()), int((gap(b) >= 3).sum())],
             "late": [int((gap(a) > 0).sum()), int((gap(b) > 0).sum())],
             "unresolved_timing": [int((a.status_reason == "unresolved_timing").sum()),
                                   int((b.status_reason == "unresolved_timing").sum())],
             "tiles": [int(a.tile.nunique()), int(b.tile.nunique())]}
    result = {"script_sha256_lf": g1.sha256_lf(Path(__file__)), "fingerprint": method_policy_fingerprint(),
              "case_studies": compare_cases(), "fitzroy_tiles": tiles, "real_records": compare_real()}
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2, default=str) + "\n", encoding="utf-8")
    log("compare written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["run-cases", "run-tiles", "run-real", "compare"])
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    {"run-cases": stage_run_cases, "run-tiles": lambda: stage_run_tiles(args.workers),
     "run-real": lambda: stage_run_real(args.workers), "compare": stage_compare}[args.stage]()


if __name__ == "__main__":
    main()
