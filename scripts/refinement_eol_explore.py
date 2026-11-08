"""Exploratory: why the trough boundary misses the end of the dry season on ephemeral tiles.

HydroSeason's definition (Methods section 4): the year boundary is the final month of the
supported low state before sustained recovery, i.e. the end of the dry season. On the
Fitzroy tiles hydropools uses, the boundary falls before the end of the dry run
(hydroseason-v0.3.0's `dry_run_end_month`) in 727 of 1,600 production tile-years. The
pass-2 direct-profile refinement exists to place the boundary at the end of the low
state. This script records, for every cycle, what the refinement did and why, so the
causes can be counted before any change is proposed. Reported only; no accuracy against
known truth is computed here.

Outputs (data_local, not committed):
  <OUT>/cycles.csv   one row per tile-year: refinement verdict, both peaks' status,
                     the refinement's month against the boundary and the dry-run end
Prints the breakdown that docs/handoff/2026-11-08-refinement-end-of-low-exploration.md quotes.

    PYTHONPATH=. python scripts/refinement_eol_explore.py run
    PYTHONPATH=. python scripts/refinement_eol_explore.py summarise
"""
from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import warnings  # noqa: E402
from collections import Counter  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402

TILES = Path("D:/RLH/5.6/repos/hydropools/work/fitzroy_v3/hydroseason")
OUT = g1.DATA / "intermediate" / "hydroseason_refinement_eol"


def _months(a, b):
    if pd.isna(a) or pd.isna(b):
        return None
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return (b.year - a.year) * 12 + b.month - a.month


def _one(tile: str) -> list[dict]:
    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    frame = pd.read_csv(TILES / tile / "channel_monthly_extent.csv")
    analysis = analyze_catchment(frame, date_col=[c for c in frame.columns if "date" in c.lower()][0])
    hy = analysis.hydro_years
    rows = []
    for position, (_, r) in enumerate(hy.iterrows()):
        following = hy.iloc[position + 1] if position + 1 < len(hy) else None
        rows.append({
            "tile": tile, "hy_year": int(r["hy_year"]), "status": r["status"], "status_reason": r["status_reason"],
            "boundary": r["trough_month"], "pass1": r["pass1_trough_month"],
            "dry_run_end": r["dry_run_end_month"], "rewetting": r["rewetting_month"],
            "challenger": r["trough_challenger_month"],
            "low_state_start": r["trough_challenger_low_state_start"],
            "low_state_end": r["trough_challenger_low_state_end"],
            "refinement_status": r["trough_refinement_status"], "refinement_reason": r["trough_refinement_reason"],
            "applied": bool(r["trough_refinement_applied"]),
            "left_peak": r["peak_month"], "left_peak_timing": r["peak_timing_status"], "left_peak_quality": r["peak_quality"],
            "right_peak": None if following is None else following["peak_month"],
            "right_peak_timing": None if following is None else following["peak_timing_status"],
            "right_peak_quality": None if following is None else following["peak_quality"],
            "right_status_reason": None if following is None else following["status_reason"],
        })
    return rows


def stage_run(workers: int, tag: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tiles = sorted(p.name for p in TILES.iterdir() if (p / "channel_monthly_extent.csv").exists())
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = [row for result in pool.map(_one, tiles) for row in result]
    pd.DataFrame(rows).to_csv(OUT / f"cycles_{tag}.csv", index=False)
    print(f"{len(rows)} cycles from {len(tiles)} tiles")


def _peak_state(month, timing) -> str:
    if month is None or (isinstance(month, float) and pd.isna(month)) or month == "":
        return "missing"
    return "unresolved" if timing == "unresolved" else "dated"


def stage_summarise(tag: str) -> dict:
    t = pd.read_csv(OUT / f"cycles_{tag}.csv", dtype=str, keep_default_na=False)
    t["gap"] = [_months(a, b) if a and b else None for a, b in zip(t.boundary, t.dry_run_end)]
    t["challenger_gap"] = [_months(a, b) if a and b else None for a, b in zip(t.challenger, t.dry_run_end)]
    late = t[t["gap"].fillna(0).astype(float) > 0]
    out: dict = {"cycles": len(t), "late": len(late), "late_3plus": int((late["gap"].astype(float) >= 3).sum())}

    def bucket(r) -> str:
        if r.refinement_reason == "missing_or_unresolved_peak":
            left = _peak_state(r.left_peak, r.left_peak_timing)
            right = _peak_state(r.right_peak, r.right_peak_timing)
            return f"no refinement: left peak {left}, right peak {right}"
        if r.refinement_reason == "atomic_rollback_cycle":
            return "refinement rolled back (one boundary at a time)"
        if r.refinement_reason == "open_span":
            return "last boundary of the record (open span)"
        if r.applied == "True":
            g = r.challenger_gap
            return "refinement applied, ends at the run end" if g in (0, 0.0) else "refinement applied, ends before the run end"
        if r.challenger:
            return f"refinement found a month but abstained ({r.refinement_reason})"
        return f"refinement abstained, no month ({r.refinement_reason})"

    late = late.assign(bucket=late.apply(bucket, axis=1))
    out["late_by_cause"] = dict(Counter(late["bucket"]).most_common())
    late3 = late[late["gap"].astype(float) >= 3]
    out["late_3plus_by_cause"] = dict(Counter(late3["bucket"]).most_common())
    applied_early = late[late["bucket"] == "refinement applied, ends before the run end"]
    out["applied_early_gap_months"] = dict(Counter(int(x) for x in applied_early["gap"].astype(float)).most_common())
    abstained = late[late["bucket"].str.startswith("refinement found a month")]
    out["abstained_challenger_vs_run_end"] = dict(Counter(
        "at run end" if g in (0, 0.0) else "before run end" if g is not None and float(g) > 0 else "after run end"
        for g in abstained["challenger_gap"]).most_common())
    rolled = late[late["bucket"] == "refinement rolled back (one boundary at a time)"]
    out["rolled_back_challenger_vs_run_end"] = dict(Counter(
        "at run end" if g in (0, 0.0) else f"{int(float(g))} months before" if g is not None and float(g) > 0 else "after"
        for g in rolled["challenger_gap"]).most_common())
    by_tile = late.groupby("tile").size().sort_values(ascending=False)
    out["late_by_tile_top"] = {k: int(v) for k, v in by_tile.head(8).items()}
    print(json.dumps(out, indent=1))
    return out


def stage_compare() -> dict:
    """The candidate library against v0.3.0 on the same tile-years."""
    a = pd.read_csv(OUT / "cycles_v030.csv", dtype=str, keep_default_na=False)
    b = pd.read_csv(OUT / "cycles_candidate.csv", dtype=str, keep_default_na=False)
    lost = sorted(set(a.tile) - set(b.tile))
    a = a[a.tile.isin(set(b.tile))].reset_index(drop=True)
    keys = list(zip(a.tile, a.hy_year))
    b = b.set_index(["tile", "hy_year"]).reindex(keys).reset_index()
    b = b.fillna("")
    gap_a = pd.Series([_months(x, y) if x and y else None for x, y in zip(a.boundary, a.dry_run_end)], dtype=float)
    gap_b = pd.Series([_months(x, y) if x and y else None for x, y in zip(b.boundary, b.dry_run_end)], dtype=float)
    moved = a.boundary != b.boundary
    out = {
        "tiles_routed_to_events": lost,
        "unresolved_timing_before_after": [int((a.status_reason == "unresolved_timing").sum()),
                                           int((b.status_reason == "unresolved_timing").sum())],
        "cycles": len(a),
        "peaks_changed": int((a.left_peak != b.left_peak).sum()),
        "boundaries_moved": int(moved.sum()),
        "moved_later": int(sum(1 for x, y in zip(a.boundary[moved], b.boundary[moved]) if x and y and y > x)),
        "moved_to_run_end": int(((b.boundary == b.dry_run_end) & moved).sum()),
        "late_before": int((gap_a > 0).sum()), "late_after": int((gap_b > 0).sum()),
        "late3_before": int((gap_a >= 3).sum()), "late3_after": int((gap_b >= 3).sum()),
        "boundary_after_run_end": int((gap_b < 0).sum()),
        "reason_after_for_moved": dict(Counter(b.refinement_reason[moved]).most_common()),
        "status_reason_changes": dict(Counter(f"{x}->{y}" for x, y in zip(a.status_reason, b.status_reason) if x != y).most_common(8)),
        "late3_after_by_tile_top": {k: int(v) for k, v in b[gap_b >= 3].groupby("tile").size().sort_values(ascending=False).head(8).items()},
    }
    for tile in ("tile05", "tile13", "tile54", "tile46"):
        sel = (a.tile == tile).to_numpy()
        if not sel.any():
            out[f"{tile}_late3"] = "routed to events"
            continue
        out[f"{tile}_late3"] = [int((gap_a[sel] >= 3).sum()), int((gap_b[sel] >= 3).sum())]
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["run", "summarise", "compare"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--tag", default="v030", help="v030 (the library as released) or candidate")
    args = parser.parse_args()
    if args.stage == "run":
        stage_run(args.workers, args.tag)
    elif args.stage == "summarise":
        stage_summarise(args.tag)
    else:
        stage_compare()


if __name__ == "__main__":
    main()
