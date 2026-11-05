"""Implementation checks of the reported dry run (DE1 change A) in hydroseason-v0.3.0.

DE1 (docs/handoff/2026-11-05-de1-dry-run-end-results.md) passed rules 1 and 2. Its
change B (move a tied boundary to the end of its run) failed the implementation
checks and was withdrawn (branch research/dry-run-end-b,
docs/handoff/2026-11-06-dry-run-end-b-checks.json). Change A ships: every cycle
reports the dry run of its trough boundary and the boundary does not move.

"Before" is the stored hydroseason-v0.3.0 runs (fingerprint 4d11d348...), made by the
same library code as the commit DE1 ran on; they are read, never rewritten.

Expected, checked here: every existing column of every table identical; the only
differences are the five new columns (dry_run_start, dry_run_end, rewetting,
dry_run_months, dry_end_status); no dry end is `point`.

Stages:
  run-cases   the five case studies, 4 resolutions each (scripts/v030_case_study_comparison.py run)
  run-tiles   the Fitzroy tiles, both input sets (scripts/v030_fitzroy_tiles.py run)
  compare     writes docs/handoff/2026-11-06-dry-run-end-implementation-checks.json

    PYTHONPATH=. python scripts/dry_run_end_checks.py run-cases
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402
import v030_case_study_comparison as cs  # noqa: E402
import v030_fitzroy_tiles as ft  # noqa: E402

INTERMEDIATE = g1.DATA / "intermediate"
OUT = INTERMEDIATE / "hydroseason_dry_run_end_checks"
BEFORE_CASES = INTERMEDIATE / "hydroseason_v030_case_studies" / "v0.3.0"
BEFORE_TILES = INTERMEDIATE / "hydroseason_v030_fitzroy_tiles" / "v0.3.0"
RESULTS = g1.HANDOFF / "2026-11-06-dry-run-end-implementation-checks.json"
BEFORE_FINGERPRINT = "4d11d348a745e980d25b933c3f51fe90e7b5931e856223b597c9d5e3566db578"
NEW_HY = {"dry_run_start_month", "dry_run_end_month", "rewetting_month", "dry_run_months", "dry_end_status"}
NEW_EXPORT = {"dry_run_start_date", "dry_run_end_date", "rewetting_date", "dry_run_months", "dry_end_status"}
SUMMARY_ALLOWED = {"method_policy_fingerprint", "library_file"}


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
        raise SystemExit("the importable HydroSeason is the old 0.3.0; run with the dry-run library")
    return fingerprint


def stage_run_cases() -> None:
    log(f"run-cases with fingerprint {_require_new_library()[:12]}")
    cs.stage_run(OUT / "case_studies")
    log("run-cases done")


def stage_run_tiles(workers: int) -> None:
    log(f"run-tiles with fingerprint {_require_new_library()[:12]}")
    ft.stage_run(OUT / "fitzroy_tiles", workers)
    log("run-tiles done")


def _diff(before: pd.DataFrame, after: pd.DataFrame, new: set[str]) -> dict:
    """Every column of `before` must be identical; `after` may only add the `new` columns."""
    out = {"rows": [len(before), len(after)], "changed": {},
           "added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after))}
    if len(before) == len(after):
        for column in [c for c in before.columns if c in after.columns]:
            same = cs._same(before[column].reset_index(drop=True), after[column].reset_index(drop=True))
            if int((~same).sum()):
                out["changed"][column] = int((~same).sum())
    out["unexpected"] = bool(out["changed"] or out["removed"] or len(before) != len(after)
                             or set(out["added"]) - new)
    return out


def _months(a, b) -> float | None:
    if pd.isna(a) or pd.isna(b) or a == "" or b == "":
        return None
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return float((b.year - a.year) * 12 + b.month - a.month)


def _gap_counts(boundaries, ends) -> dict:
    gaps = pd.Series([_months(a, b) for a, b in zip(boundaries, ends)], dtype=float).dropna()
    return {"cycles": int(len(gaps)), "run_end_after_boundary": int((gaps > 0).sum()),
            "by_3_or_more": int((gaps >= 3).sum()), "by_6_or_more": int((gaps >= 6).sum())}


def compare_cases() -> dict:
    after_dir = OUT / "case_studies"
    series, unexpected = {}, []
    for key in cs.CATCHMENTS:
        for resolution in cs.RESOLUTIONS:
            stem = f"{key}_{resolution}"
            sb = json.loads((BEFORE_CASES / f"{stem}_summary.json").read_text(encoding="utf-8"))
            sa = json.loads((after_dir / f"{stem}_summary.json").read_text(encoding="utf-8"))
            summary_changed = sorted(k for k in sb if sb[k] != sa.get(k) and k not in SUMMARY_ALLOWED)
            hb = cs._read(BEFORE_CASES / f"{stem}_hydro_years.csv")
            ha = cs._read(after_dir / f"{stem}_hydro_years.csv")
            entry = {"route": sa["route"], "summary_changed": summary_changed,
                     "hydro_years": _diff(hb, ha, NEW_HY if len(hb) else set(ha.columns))}
            if len(ha):
                entry["dry_end_status"] = {str(k): int(v) for k, v in ha["dry_end_status"].value_counts().items()}
                entry["run_end_vs_boundary"] = _gap_counts(ha["trough_month"], ha["dry_run_end_month"])
            if (BEFORE_CASES / f"{stem}_monthly_phase.csv").exists():
                entry["monthly_phase"] = _diff(cs._read(BEFORE_CASES / f"{stem}_monthly_phase.csv"),
                                               cs._read(after_dir / f"{stem}_monthly_phase.csv"), set())
            if (summary_changed or entry["hydro_years"]["unexpected"]
                    or entry.get("monthly_phase", {}).get("unexpected")
                    or entry.get("dry_end_status", {}).get("point")):
                unexpected.append(stem)
            series[stem] = entry
    reports = {}
    for path in sorted((BEFORE_CASES / "reports").rglob("*.csv")):
        other = after_dir / "reports" / path.relative_to(BEFORE_CASES / "reports")
        if other.exists():
            new = NEW_EXPORT if path.name.endswith("_hydro_years.csv") else set()
            result = _diff(cs._read(path), cs._read(other), new)
            reports[str(path.relative_to(BEFORE_CASES / "reports"))] = result
            if result["unexpected"]:
                unexpected.append(path.name)
    return {"series": series, "report_tables": reports, "unexpected": unexpected}


def compare_tiles() -> dict:
    after_dir = OUT / "fitzroy_tiles"
    rows, unexpected = [], {}
    for set_name, tile, _src in ft.jobs():
        da, db = BEFORE_TILES / set_name / tile, after_dir / set_name / tile
        tables = {}
        for pattern in ("*_hydro_years.csv", "*_monthly.csv", "*_wet_event.csv", "*_low_spells.csv"):
            fa, fb = ft._one(da, pattern), ft._one(db, pattern)
            if fa is None or fb is None:
                tables[pattern] = {"unexpected": True, "missing": [fa is None, fb is None]}
                continue
            a = pd.read_csv(fa, dtype=str, keep_default_na=False)
            b = pd.read_csv(fb, dtype=str, keep_default_na=False)
            tables[pattern] = _diff(a, b, NEW_EXPORT if pattern == "*_hydro_years.csv" else set())
            if pattern == "*_hydro_years.csv" and len(a) == len(b):
                for (_, ra), (_, rb) in zip(a.iterrows(), b.iterrows()):
                    rows.append({"set": set_name, "tile": tile, "hy_year": rb["hy_year"],
                                 "clock": ft._clock(rb), "boundary": rb["trough_boundary_date"],
                                 "dry_run_end": rb["dry_run_end_date"], "rewetting": rb["rewetting_date"],
                                 "dry_end_status": rb["dry_end_status"], "timing_status": rb["timing_status"]})
        bad = {k: v for k, v in tables.items() if v.get("unexpected")}
        if bad:
            unexpected[f"{set_name}|{tile}"] = bad
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "tile_years.csv", index=False)
    summary = {}
    for set_name, group in table.groupby("set"):
        shift = pd.Series([_months(c, e) for c, e in zip(group["clock"], group["dry_run_end"])], dtype=float).dropna()
        summary[set_name] = {
            "tiles": int(group["tile"].nunique()), "tile_years": len(group),
            "run_end_vs_boundary": _gap_counts(group["boundary"], group["dry_run_end"]),
            "run_end_minus_hydropools_clock_months": {str(int(k)): int(v)
                                                      for k, v in shift.value_counts().sort_index().items()},
            "dry_end_status": {str(k): int(v) for k, v in group["dry_end_status"].value_counts().items()},
        }
    focus = {}
    for tile in ("tile05", "tile13"):
        part = table[(table.set == "production") & (table.tile == tile)]
        focus[tile] = [{"hy_year": r.hy_year, "clock": r.clock, "dry_run_end": r.dry_run_end,
                        "rewetting": r.rewetting, "dry_end_status": r.dry_end_status} for r in part.itertuples()]
    return {"summary": summary, "focus": focus, "unexpected": unexpected}


def stage_compare() -> None:
    from hydroseason._method_policy import CURRENT_METHOD_POLICY, method_policy_fingerprint

    result = {"script_sha256_lf": g1.sha256_lf(Path(__file__)), "before_fingerprint": BEFORE_FINGERPRINT,
              "after_policy": CURRENT_METHOD_POLICY.policy_id, "after_fingerprint": method_policy_fingerprint(),
              "case_studies": compare_cases(), "fitzroy_tiles": compare_tiles()}
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2, default=str) + "\n", encoding="utf-8")
    log(f"compare: case studies unexpected {result['case_studies']['unexpected'] or 'none'}; "
        f"tiles unexpected {sorted(result['fitzroy_tiles']['unexpected']) or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["run-cases", "run-tiles", "compare"])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.stage == "run-cases":
        stage_run_cases()
    elif args.stage == "run-tiles":
        stage_run_tiles(args.workers)
    else:
        stage_compare()


if __name__ == "__main__":
    main()
