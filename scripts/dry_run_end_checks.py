"""Implementation checks of the dry-season-end rule (DE1, A + B) in hydroseason-v0.3.0.

DE1 (docs/handoff/2026-11-05-de1-dry-run-end-results.md) passed rules 1 and 2, so A
(report each boundary's dry run) and B (move a tied boundary to the end of its run)
were implemented. The plan's implementation checks compare the library before and
after on the five case studies, the Fitzroy tiles hydropools uses and the real-record
units. "Before" is the stored hydroseason-v0.3.0 runs (fingerprint 4d11d348...),
made by the same library code as the commit DE1 ran on; they are read, never rewritten.

Expected (from the plan), checked here:
  - routes, record lengths and peak months identical; no peak moves;
  - pass-1 and trough-refinement evidence identical (B runs after both);
  - everything else that differs follows from a moved boundary: year start and end,
    trough fields, trough labels, timing, status, mid-dry, monthly phases, baselines;
  - every dated trough label covers its boundary; no dry end is `point`.

Stages:
  run-cases   the five case studies, 4 resolutions each (scripts/v030_case_study_comparison.py run)
  run-tiles   the Fitzroy tiles, both input sets (scripts/v030_fitzroy_tiles.py run)
  run-real    the 4,468 real-record units (G1 windows, spatial-unit study)
  compare     writes docs/handoff/2026-11-05-dry-run-end-implementation-checks.json

    PYTHONPATH=. python scripts/dry_run_end_checks.py run-cases
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402
import l1_followups as fu  # noqa: E402
import real_record_impact as rri  # noqa: E402
import v030_case_study_comparison as cs  # noqa: E402
import v030_fitzroy_tiles as ft  # noqa: E402

INTERMEDIATE = g1.DATA / "intermediate"
OUT = INTERMEDIATE / "hydroseason_dry_run_end_checks"
BEFORE_CASES = INTERMEDIATE / "hydroseason_v030_case_studies" / "v0.3.0"
BEFORE_TILES = INTERMEDIATE / "hydroseason_v030_fitzroy_tiles" / "v0.3.0"
BEFORE_REAL = INTERMEDIATE / "hydroseason_v030_real_record_check" / "runs.jsonl"
RESULTS = g1.HANDOFF / "2026-11-05-dry-run-end-implementation-checks.json"
BEFORE_FINGERPRINT = "4d11d348a745e980d25b933c3f51fe90e7b5931e856223b597c9d5e3566db578"
DATED = {"point", "interval", "broad"}

# Year columns B may not touch: peaks, the pass-1 window search and the trough refinement.
FIXED_HY = {
    "hy_year", "peak_month", "peak_extent_pct", "peak_invalid_pct", "raw_peak_month", "raw_peak_extent_pct",
    "peak_quality", "raw_trough_month", "raw_trough_extent_pct", "low_run_start_month", "low_run_end_month",
    "window_status", "selection_status", "selection_support", "selection_quality", "window_n_expected",
    "window_n_usable", "trough_search_radius_used", "boundary_at_search_edge", "boundary_search_edge_side",
    "outside_window_observed", "outside_window_lower", "retry_outcome", "pass1_trough_month",
    "pass1_trough_interval_start", "pass1_trough_interval_end", "pass1_trough_timing_status",
    "trough_challenger_month", "trough_challenger_interval_start", "trough_challenger_interval_end",
    "trough_challenger_timing_status", "trough_challenger_low_state_start", "trough_challenger_low_state_end",
    "trough_refinement_status", "trough_refinement_reason", "trough_refinement_applied", "recovery_start_month",
    "trough_local_scale_pp", "trough_profile_best_loss", "trough_profile_cutoff", "trough_effective_support",
    "trough_pulse_months", "trough_refinement_policy_version", "trough_loss_basis",
}
# Monthly columns B may not touch: the record itself, events and low-extent spells.
FIXED_MONTHLY = {"date", "extent_pct", "invalid_pct", "max_invalid_pct", "usable_month", "quality_state",
                 "candidate_usable", "in_wet_event", "wet_event_id", "in_low_spell", "low_spell_id",
                 "is_hy_peak", "regime", "route", "Unnamed: 0"}
FIXED_EXPORT = {"catchment", "hy_year", "peak_date", "peak_extent_pct", "peak_invalid_pct", "peak_quality",
                "regime", "route", "trough_refinement_status", "trough_refinement_reason"}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "checks.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _require_new_library() -> str:
    from hydroseason._method_policy import method_policy_fingerprint

    fingerprint = method_policy_fingerprint()
    if fingerprint == BEFORE_FINGERPRINT:
        raise SystemExit("the importable HydroSeason is the old 0.3.0; run with the dry-season-end library")
    return fingerprint


# ---------------------------------------------------------------- runs
def stage_run_cases() -> None:
    log(f"run-cases with fingerprint {_require_new_library()[:12]}")
    cs.stage_run(OUT / "case_studies")
    log("run-cases done")


def stage_run_tiles(workers: int) -> None:
    log(f"run-tiles with fingerprint {_require_new_library()[:12]}")
    ft.stage_run(OUT / "fitzroy_tiles", workers)
    log("run-tiles done")


DRY_FIELDS = ("dry_run_start_month", "dry_run_end_month", "rewetting_month")
DRY_VALUES = ("dry_run_months", "dry_end_status", "dry_run_boundary_status", "boundary_shift_months", "hy_start",
              "hy_end")


def _run_real(payload):
    """fu._run (the stored 0.3.0 record format) plus the dry-run columns, from one analysis."""
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment
    from hydroseason._method_policy import method_policy_fingerprint

    key, rows = payload
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]
    started = time.perf_counter()
    record = {"key": key, "fingerprint": method_policy_fingerprint()}
    try:
        analysis = analyze_catchment(frame[["n_water", "n_valid", "n_invalid", "n_aoi"]],
                                     phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    cycles = []
    for _, row in hy.iterrows():
        cycle = {c: g1.month_index(row.get(c)) for c in (*fu.MONTH_COLUMNS, *DRY_FIELDS, "hy_start", "hy_end")}
        cycle.update({c: row.get(c) for c in fu.VALUE_COLUMNS})
        cycle.update({c: row.get(c) for c in DRY_VALUES if c not in ("hy_start", "hy_end")})
        cycle.update({"baseline_eligible": row.get("baseline_eligible"), "recharge": row.get("recharge_condition"),
                      "refuge": row.get("refuge_condition")})
        cycles.append(cycle)
    config = {}
    if analysis.state is not None and len(hy):
        config = {"min_baseline_cycles": analysis.state.config.min_baseline_cycles}
    record.update(route=analysis.route, error=None, cycles=cycles, config=config,
                  seconds=round(time.perf_counter() - started, 2))
    return record


def stage_run_real(workers: int) -> None:
    fingerprint = _require_new_library()
    sink = OUT / "real_records.jsonl"
    done = set()
    if sink.exists():
        done = {json.loads(x)["key"] for x in sink.read_text(encoding="utf-8").splitlines() if x}
    frames = rri.series_frames()
    payloads = [(key, frame.to_dict(orient="list")) for key, frame in frames.items() if key not in done]
    log(f"run-real: {len(payloads)} of {len(frames)} records, {workers} workers, fingerprint {fingerprint[:12]}")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run_real, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 200 == 0 or n == len(futures):
                log(f"run-real: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- compare
def _changed(before: pd.DataFrame, after: pd.DataFrame, fixed: set[str]) -> dict:
    out = {"rows": [len(before), len(after)], "changed": {}, "unexpected": {},
           "columns_only_after": sorted(set(after) - set(before)),
           "columns_only_before": sorted(set(before) - set(after))}
    if len(before) != len(after):
        out["unexpected"]["<rows>"] = [len(before), len(after)]
        return out
    for column in [c for c in before.columns if c in after.columns]:
        same = cs._same(before[column].reset_index(drop=True), after[column].reset_index(drop=True))
        n = int((~same).sum())
        if n:
            (out["unexpected"] if column in fixed else out["changed"])[column] = n
    if out["columns_only_before"]:
        out["unexpected"]["<columns removed>"] = out["columns_only_before"]
    return out


def _dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _labels_cover(frame: pd.DataFrame) -> int:
    """Dated trough labels that miss their boundary (must be 0)."""
    if not len(frame) or "trough_timing_status" not in frame:
        return 0
    dated = frame[frame["trough_timing_status"].isin(DATED)]
    start, end, boundary = (_dates(dated[c]) for c in ("trough_interval_start", "trough_interval_end", "trough_month"))
    return int((~((start <= boundary) & (boundary <= end))).sum())


def _outcomes(frame: pd.DataFrame) -> dict:
    if not len(frame) or "dry_run_boundary_status" not in frame:
        return {}
    return {str(k): int(v) for k, v in frame["dry_run_boundary_status"].value_counts().items()}


def compare_cases() -> dict:
    after_dir = OUT / "case_studies"
    series, unexpected = {}, []
    for key in cs.CATCHMENTS:
        for resolution in cs.RESOLUTIONS:
            stem = f"{key}_{resolution}"
            sb = json.loads((BEFORE_CASES / f"{stem}_summary.json").read_text(encoding="utf-8"))
            sa = json.loads((after_dir / f"{stem}_summary.json").read_text(encoding="utf-8"))
            hb, ha = cs._read(BEFORE_CASES / f"{stem}_hydro_years.csv"), cs._read(after_dir / f"{stem}_hydro_years.csv")
            entry = {"route": [sb["route"], sa["route"]], "fingerprint": [sb["method_policy_fingerprint"][:12],
                                                                          sa["method_policy_fingerprint"][:12]],
                     "hydro_years": _changed(hb, ha, FIXED_HY), "outcomes": _outcomes(ha),
                     "labels_not_covering": _labels_cover(ha),
                     "point_dry_ends": int((ha.get("dry_end_status", pd.Series(dtype=str)) == "point").sum())}
            if len(ha) and "boundary_shift_months" in ha:
                moved = ha[ha["dry_run_boundary_status"] == "moved"]
                entry["moved_months"] = {str(int(k)): int(v) for k, v in moved["boundary_shift_months"].value_counts()
                                         .sort_index().items()}
                for frame, name in ((hb, "before"), (ha, "after")):
                    entry[f"timing_{name}"] = {str(k): int(v) for k, v in frame["timing_status"].value_counts().items()}
                    entry[f"eligible_{name}"] = int(frame["baseline_eligible"].fillna(False).astype(bool).sum())
                    entry[f"labelled_{name}"] = int(frame["recharge_condition"].isin(["low", "typical", "high"]).sum())
                peak_label = (hb["peak_timing_status"].astype(str) != ha["peak_timing_status"].astype(str))
                entry["peak_label_changes"] = int(peak_label.sum())
            if (BEFORE_CASES / f"{stem}_monthly_phase.csv").exists() and (after_dir / f"{stem}_monthly_phase.csv").exists():
                mb = cs._read(BEFORE_CASES / f"{stem}_monthly_phase.csv")
                ma = cs._read(after_dir / f"{stem}_monthly_phase.csv")
                monthly = _changed(mb, ma, FIXED_MONTHLY)
                if len(mb) == len(ma):
                    moved_rows = ~pd.concat([cs._same(mb[c], ma[c]) for c in mb.columns if c in ma.columns],
                                            axis=1).all(axis=1)
                    monthly["months_changed"] = int(moved_rows.sum())
                entry["monthly_phase"] = monthly
            if (entry["route"][0] != entry["route"][1] or entry["hydro_years"]["unexpected"]
                    or entry.get("monthly_phase", {}).get("unexpected") or entry["labels_not_covering"]
                    or entry["point_dry_ends"]):
                unexpected.append(stem)
            series[stem] = entry
    reports = {}
    for path in sorted((BEFORE_CASES / "reports").rglob("*.csv")):
        other = after_dir / "reports" / path.relative_to(BEFORE_CASES / "reports")
        if other.exists():
            fixed = FIXED_EXPORT if path.name.endswith("_hydro_years.csv") else FIXED_MONTHLY
            if path.name.endswith(("_wet_event.csv", "_low_spells.csv")):
                fixed = set(cs._read(path).columns)
            result = _changed(cs._read(path), cs._read(other), fixed)
            reports[str(path.relative_to(BEFORE_CASES / "reports"))] = result
            if result["unexpected"]:
                unexpected.append(str(path.name))
    return {"series": series, "report_tables": reports, "unexpected": unexpected}


def compare_tiles() -> dict:
    after_dir = OUT / "fitzroy_tiles"
    rows, tiles, unexpected = [], {}, {}
    for set_name, tile, _src in ft.jobs():
        da, db = BEFORE_TILES / set_name / tile, after_dir / set_name / tile
        ha, hb = ft._one(da, "*_hydro_years.csv"), ft._one(db, "*_hydro_years.csv")
        if ha is None or hb is None:
            unexpected[f"{set_name}|{tile}"] = "missing"
            continue
        a = pd.read_csv(ha, dtype=str, keep_default_na=False)
        b = pd.read_csv(hb, dtype=str, keep_default_na=False)
        if len(a) != len(b):
            unexpected[f"{set_name}|{tile}"] = "row count"
            continue
        fixed_changed = sorted(c for c in FIXED_EXPORT if c in a and (a[c] != b[c]).any())
        others = {}
        for pattern in ("*_wet_event.csv", "*_low_spells.csv"):
            fa, fb = ft._one(da, pattern), ft._one(db, pattern)
            if fa is not None and fb is not None:
                changed = ft._frame_diff(pd.read_csv(fa, dtype=str, keep_default_na=False),
                                         pd.read_csv(fb, dtype=str, keep_default_na=False))["changed"]
                if changed:
                    others[pattern[2:-4]] = changed
        if fixed_changed or others:
            unexpected[f"{set_name}|{tile}"] = {"fixed_columns": fixed_changed, "tables": others}
        tiles[f"{set_name}|{tile}"] = {"years": len(b), "outcomes": _outcomes(b)}
        for (_, ra), (_, rb) in zip(a.iterrows(), b.iterrows()):
            rows.append({
                "set": set_name, "tile": tile, "hy_year": ra["hy_year"],
                "boundary_before": ra.get("trough_boundary_date", ""), "boundary_after": rb.get("trough_boundary_date", ""),
                "clock_before": ft._clock(ra), "clock_after": ft._clock(rb),
                "dry_run_end": rb.get("dry_run_end_date", ""), "rewetting": rb.get("rewetting_date", ""),
                "dry_end_status": rb.get("dry_end_status", ""),
                "trough_before": ra.get("trough_timing_status", ""), "trough_after": rb.get("trough_timing_status", ""),
                "timing_before": ra.get("timing_status", ""), "timing_after": rb.get("timing_status", ""),
                "fails_before": ft._fails(ra), "fails_after": ft._fails(rb),
                "eligible_before": ra.get("baseline_eligible", ""), "eligible_after": rb.get("baseline_eligible", ""),
                "annual_before": ra.get("annual_condition", ""), "annual_after": rb.get("annual_condition", ""),
            })
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "tile_years.csv", index=False)

    def months_between(x: str, y: str) -> float:
        if not x or not y:
            return np.nan
        a, b = pd.Timestamp(x), pd.Timestamp(y)
        return float((b.year - a.year) * 12 + b.month - a.month)

    table["clock_shift"] = [months_between(x, y) for x, y in zip(table.clock_before, table.clock_after)]
    summary = {}
    for set_name, group in table.groupby("set"):
        shift = group["clock_shift"].dropna()
        summary[set_name] = {
            "tiles": int(group["tile"].nunique()), "tile_years": len(group),
            "boundaries_moved": int((group.boundary_before != group.boundary_after).sum()),
            "clock_changes": int((group.clock_before != group.clock_after).sum()),
            "clock_shift_months": {str(int(k)): int(v) for k, v in shift.value_counts().sort_index().items()},
            "fails_before": int(group["fails_before"].sum()), "fails_after": int(group["fails_after"].sum()),
            "timing_unresolved_before": int((group.timing_before == "unresolved").sum()),
            "timing_unresolved_after": int((group.timing_after == "unresolved").sum()),
            "eligible_before": int((group.eligible_before == "True").sum()),
            "eligible_after": int((group.eligible_after == "True").sum()),
            "labelled_years_before": int(group.annual_before.map(ft._labelled).sum()),
            "labelled_years_after": int(group.annual_after.map(ft._labelled).sum()),
            "dry_end_status": {str(k): int(v) for k, v in group.dry_end_status.value_counts().items()},
        }
    focus = {}
    for tile in ("tile05", "tile13"):
        part = table[(table.set == "production") & (table.tile == tile)]
        focus[tile] = [{"hy_year": r.hy_year, "clock_before": r.clock_before, "clock_after": r.clock_after,
                        "rewetting": r.rewetting, "dry_end_status": r.dry_end_status, "timing_after": r.timing_after}
                       for r in part.itertuples()]
    return {"summary": summary, "tiles": tiles, "focus": focus, "unexpected": unexpected}


def compare_real() -> dict:
    old = {r["key"]: r for r in (json.loads(x) for x in BEFORE_REAL.read_text(encoding="utf-8").splitlines() if x)}
    new = {r["key"]: r for r in (json.loads(x) for x in (OUT / "real_records.jsonl").read_text(encoding="utf-8")
                                 .splitlines() if x)}
    units = pd.read_csv(rri.SU / "units.csv").set_index("unit_id")
    fixed = {"peak_month", "peak_extent_pct", "peak_quality", "raw_trough_month", "raw_trough_extent_pct",
             "low_run_start_month", "low_run_end_month", "pass1_trough_month", "pass1_trough_timing_status",
             "window_status", "selection_status", "trough_search_radius_used", "boundary_at_search_edge",
             "boundary_search_edge_side", "outside_window_observed", "outside_window_lower", "retry_outcome",
             "trough_refinement_status", "trough_refinement_reason", "trough_refinement_applied", "hy_year"}
    route_changes, count_changes = [], []
    unexpected, changed, outcomes, shifts = Counter(), Counter(), Counter(), Counter()
    timing, eligible, not_covering, point_ends = Counter(), Counter(), Counter(), Counter()
    baseline_units = Counter()
    for key in sorted(old):
        a, b = old[key], new.get(key)
        if b is None:
            route_changes.append([key, a["route"], "missing"])
            continue
        if a["route"] != b["route"]:
            route_changes.append([key, a["route"], b["route"]])
            continue
        if len(a["cycles"]) != len(b["cycles"]):
            count_changes.append(key)
            continue
        source, scale = rri.scale_of(key, units)
        source = f"{source}|{scale}"
        for ca, cb in zip(a["cycles"], b["cycles"], strict=True):
            for field in ca:
                if ca[field] != cb.get(field):
                    changed[field] += 1
                    if field in fixed:
                        unexpected[field] += 1
            outcome = cb.get("dry_run_boundary_status")
            outcomes[f"{source}|{outcome}"] += 1
            if outcome == "moved":
                shifts[f"{source}|{int(cb['boundary_shift_months'])}"] += 1
            timing[f"{source}|{ca['timing_status']}->{cb['timing_status']}"] += ca["timing_status"] != cb["timing_status"]
            eligible[f"{source}|{bool(ca['baseline_eligible'])}->{bool(cb['baseline_eligible'])}"] += 1
            point_ends[source] += cb.get("dry_end_status") == "point"
            if cb["trough_timing_status"] in DATED and cb["trough_month"] is not None:
                start, end = cb["trough_interval_start"], cb["trough_interval_end"]
                if start is None or end is None or not start <= cb["trough_month"] <= end:
                    not_covering[source] += 1
        if b["route"] == "per_year_detection" and b.get("config"):
            minimum = b["config"]["min_baseline_cycles"]
            before_n = sum(bool(c["baseline_eligible"]) for c in a["cycles"])
            after_n = sum(bool(c["baseline_eligible"]) for c in b["cycles"])
            baseline_units[f"{source}|{before_n >= minimum}->{after_n >= minimum}"] += 1
    fingerprints = Counter(r.get("fingerprint") for r in new.values())
    return {
        "records": len(new), "fingerprints": dict(fingerprints),
        "errors": sorted(k for k, r in new.items() if r.get("error")),
        "route_changes": route_changes, "cycle_count_changes": count_changes,
        "changed_fields": dict(changed), "unexpected_changed_fields": dict(unexpected),
        "outcomes": dict(sorted(outcomes.items())), "moved_months": dict(sorted(shifts.items())),
        "timing_changes": {k: v for k, v in sorted(timing.items()) if v},
        "baseline_eligible_transitions": dict(sorted(eligible.items())),
        "units_with_baseline": dict(sorted(baseline_units.items())),
        "dated_troughs_not_covering_boundary": dict(not_covering),
        "point_dry_ends": sum(point_ends.values()),
    }


def stage_compare(parts: list[str]) -> None:
    from hydroseason._method_policy import CURRENT_METHOD_POLICY, method_policy_fingerprint

    result = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    result.update({"script_sha256_lf": g1.sha256_lf(Path(__file__)), "before_fingerprint": BEFORE_FINGERPRINT,
                   "after_policy": CURRENT_METHOD_POLICY.policy_id, "after_fingerprint": method_policy_fingerprint()})
    if "cases" in parts:
        result["case_studies"] = compare_cases()
    if "tiles" in parts:
        result["fitzroy_tiles"] = compare_tiles()
    if "real" in parts:
        result["real_records"] = compare_real()
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2, default=str) + "\n", encoding="utf-8")
    for part in ("case_studies", "fitzroy_tiles"):
        if part in result:
            log(f"compare {part}: unexpected {result[part]['unexpected'] or 'none'}")
    if "real_records" in result:
        real = result["real_records"]
        log(f"compare real: routes {len(real['route_changes'])}, counts {len(real['cycle_count_changes'])}, "
            f"unexpected {real['unexpected_changed_fields'] or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["run-cases", "run-tiles", "run-real", "compare"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--parts", nargs="*", default=["cases", "tiles", "real"])
    args = parser.parse_args()
    if args.stage == "run-cases":
        stage_run_cases()
    elif args.stage == "run-tiles":
        stage_run_tiles(args.workers)
    elif args.stage == "run-real":
        stage_run_real(args.workers)
    else:
        stage_compare(args.parts)


if __name__ == "__main__":
    main()
