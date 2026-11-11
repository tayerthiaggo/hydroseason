"""hydroseason-v0.2.0 against v0.3.0 on the Fitzroy tiles that hydropools uses.

The tiles are HydroChannel's ~46 km blocks over the whole Fitzroy; each series is the channel-zone
monthly extent inside one tile. Two input sets, both read from the hydropools repo and never written:

  production  work/fitzroy_v3/hydroseason/<tile>/channel_monthly_extent.csv  (40 tiles, percentages
              only; what the hydropools pipeline runs today)
  counts      work/u1/fitzroy/tiles_e/<tile>/series.csv  (41 tiles, with n_water/n_valid/n_invalid/n_aoi
              over intermittent pixels; the honest-floor inputs hydropools tested in U1)

hydropools' clock-anchor analysis (docs/handoff/2026-10-30-clock-anchor-analysis.md) counts a tile-year
as failing when its trough is unresolved or its amplitude-to-floor ratio is below 3.

Expected before running (from the 0.3.0 proposal and the implementation checks), not a decision rule:
  - routes, hydrological-year boundaries, peaks, ratios, monthly phases, events and spells identical;
  - only trough-label and condition-baseline columns differ;
  - B can only remove `point` or widen intervals, so failing tile-years cannot fall, only rise;
  - C adds condition labels where five dated cycles exist.

Stages:
  run      run_hydroseason on every tile of both sets with whichever HydroSeason is importable
  compare  compare two run directories; writes <after>/../compare.json and tile_years.csv

    PYTHONPATH=<checkout> python scripts/v030_fitzroy_tiles.py run --out <dir>/v0.3.0
    python scripts/v030_fitzroy_tiles.py compare --before <dir>/v0.2.0 --after <dir>/v0.3.0
"""
from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

HYDROPOOLS = Path("D:/RLH/5.6/repos/hydropools/work")
SETS = {
    "production": (HYDROPOOLS / "fitzroy_v3" / "hydroseason", "channel_monthly_extent.csv"),
    "counts": (HYDROPOOLS / "u1" / "fitzroy" / "tiles_e", "series.csv"),
}
LABEL = {"trough_timing_status", "trough_interval_start_date", "trough_interval_end_date", "trough_date",
         "timing_status"}
CONDITION_MARKERS = ("condition", "baseline", "percentile", "consecutive_")
UNLABELLED = {"insufficient_baseline", "", "nan", "None"}


def jobs() -> list[tuple[str, str, Path]]:
    out = []
    for name, (root, filename) in SETS.items():
        for tile_dir in sorted(p for p in root.iterdir() if p.is_dir() and (p / filename).exists()):
            out.append((name, tile_dir.name, tile_dir / filename))
    return out


def _run_one(job, out_root: str) -> dict:
    from hydroseason import run_hydroseason
    from hydroseason._method_policy import CURRENT_METHOD_POLICY

    set_name, tile, src = job
    dst = Path(out_root) / set_name / tile
    dst.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            run_hydroseason(str(src), output_dir=str(dst), aoi_name=f"fitzroy_{tile}", show_map=False)
        error = None
    except Exception as exc:  # recorded, not hidden
        error = f"{type(exc).__name__}: {exc}"
    return {"set": set_name, "tile": tile, "policy": CURRENT_METHOD_POLICY.policy_id, "error": error,
            "seconds": round(time.perf_counter() - started, 1)}


def stage_run(out: Path, workers: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    log = out / "run.jsonl"
    done = set()
    if log.exists():
        done = {(r["set"], r["tile"]) for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())
                if r["error"] is None}
    todo = [j for j in jobs() if (j[0], j[1]) not in done]
    print(f"{len(todo)} series to run, {workers} workers", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool, open(log, "a", encoding="utf-8") as sink:
        futures = [pool.submit(_run_one, j, str(out)) for j in todo]
        for n, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            sink.write(json.dumps(record) + "\n")
            sink.flush()
            print(f"{n}/{len(todo)} {record['set']} {record['tile']} {record['seconds']}s "
                  f"{record['error'] or 'ok'}", flush=True)


# ---------------------------------------------------------------- compare
def _one(directory: Path, pattern: str) -> Path | None:
    found = sorted(directory.glob(pattern))
    return found[0] if found else None


def _payload(html: Path) -> dict:
    text = html.read_text(encoding="utf-8")
    marker = "window.HydroSeasonReport = "
    return json.JSONDecoder().raw_decode(text, text.index(marker) + len(marker))[0]


def _clock(row) -> str:
    """hydropools' end-dry clock (a): trough_date if point, else the interval end, else the boundary."""
    if row.get("trough_timing_status") == "point" and isinstance(row.get("trough_date"), str):
        return row["trough_date"]
    for column in ("trough_interval_end_date", "trough_boundary_date"):
        if isinstance(row.get(column), str) and row[column]:
            return row[column]
    return ""


def _fails(row) -> bool:
    ratio = pd.to_numeric(row.get("amplitude_to_floor_ratio"), errors="coerce")
    return row.get("trough_timing_status") in ("unresolved", None) or pd.isna(ratio) or ratio < 3.0


def _labelled(value) -> bool:
    return str(value) not in UNLABELLED


def _allowed(column: str) -> bool:
    return column in LABEL or any(m in column for m in CONDITION_MARKERS)


def _frame_diff(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return {"shape": [list(a.shape), list(b.shape)], "changed": {"<shape>": 1}}
    changed = {}
    for column in a.columns:
        x, y = a[column].astype(str), b[column].astype(str)
        n = int((x != y).sum())
        if n:
            changed[column] = n
    return {"changed": changed}


def stage_compare(before: Path, after: Path) -> None:
    rows, tiles = [], {}
    for set_name, tile, _src in jobs():
        da, db = before / set_name / tile, after / set_name / tile
        ha, hb = _one(da, "*_hydro_years.csv"), _one(db, "*_hydro_years.csv")
        if ha is None or hb is None:
            tiles[f"{set_name}|{tile}"] = {"missing": [ha is None, hb is None]}
            continue
        a, b = pd.read_csv(ha, dtype=str, keep_default_na=False), pd.read_csv(hb, dtype=str, keep_default_na=False)
        hy = _frame_diff(a, b)
        # A cycle whose aggregate timing becomes unresolved loses its monthly phases (existing phase rule);
        # monthly changes are expected only inside such years.
        timing_changed = set(a.loc[a["timing_status"] != b["timing_status"], "hy_year"]) if len(a) == len(b) else set()
        others, phase_years = {}, set()
        for pattern in ("*_monthly.csv", "*_wet_event.csv", "*_low_spells.csv"):
            fa, fb = _one(da, pattern), _one(db, pattern)
            if fa is not None and fb is not None:
                ta = pd.read_csv(fa, dtype=str, keep_default_na=False)
                tb = pd.read_csv(fb, dtype=str, keep_default_na=False)
                changed = _frame_diff(ta, tb)["changed"]
                if pattern == "*_monthly.csv" and changed and "<shape>" not in changed:
                    moved = (ta != tb).any(axis=1)
                    phase_years = set(ta.loc[moved, "hy_year"])
                    if set(changed) <= {"phase", "phase_status"} and phase_years <= timing_changed:
                        changed = {}
                others[pattern[2:-4]] = changed
        pa, pb = _payload(_one(da, "*.html")), _payload(_one(db, "*.html"))
        pa.pop("subtitle", None), pb.pop("subtitle", None)
        traces = []
        for figure in ("timeline", "secondary", "events", "low_spells"):
            fa, fb = pa["figures"].get(figure, {}), pb["figures"].get(figure, {})
            names_a = {t.get("name"): t for t in fa.get("data", [])}
            names_b = {t.get("name"): t for t in fb.get("data", [])}
            for name in sorted(set(names_a) | set(names_b), key=str):
                if names_a.get(name) != names_b.get(name):
                    traces.append(f"{figure}:{name}")
        record = {
            "route": [a["route"].iloc[0] if len(a) else "", b["route"].iloc[0] if len(b) else ""],
            "years": len(b),
            "hydro_years_changed": hy["changed"],
            "unexpected": sorted(c for c in hy["changed"] if not _allowed(c)),
            "other_tables_changed": {k: v for k, v in others.items() if v},
            "graph_traces_changed": traces,
            "payload_identical": pa == pb,
            "timing_changed_years": sorted(timing_changed),
            "monthly_phase_changed_years": sorted(phase_years),
        }
        if len(a) == len(b):
            for (_, ra), (_, rb) in zip(a.iterrows(), b.iterrows()):
                rows.append({
                    "set": set_name, "tile": tile, "hy_year": ra["hy_year"],
                    "ratio": ra.get("amplitude_to_floor_ratio", ""),
                    "trough_before": ra.get("trough_timing_status", ""),
                    "trough_after": rb.get("trough_timing_status", ""),
                    "clock_before": _clock(ra), "clock_after": _clock(rb),
                    "fails_before": _fails(ra), "fails_after": _fails(rb),
                    "status": ra.get("status", ""), "boundary_status": ra.get("boundary_status", ""),
                    "baseline_eligible_before": ra.get("baseline_eligible", ""),
                    "baseline_eligible_after": rb.get("baseline_eligible", ""),
                    "baseline_n_before": ra.get("baseline_n", ""), "baseline_n_after": rb.get("baseline_n", ""),
                    "annual_before": ra.get("annual_condition", ""), "annual_after": rb.get("annual_condition", ""),
                    "phase_months_changed": ra["hy_year"] in phase_years,
                })
        tiles[f"{set_name}|{tile}"] = record
    table = pd.DataFrame(rows)
    table.to_csv(after.parent / "tile_years.csv", index=False)

    summary = {}
    for set_name, group in table.groupby("set"):
        per_tile = group.groupby("tile")
        summary[set_name] = {
            "tiles": int(group["tile"].nunique()),
            "tile_years": len(group),
            "fails_before": int(group["fails_before"].sum()),
            "fails_after": int(group["fails_after"].sum()),
            "trough_label_changes": {f"{x}->{y}": int(n) for (x, y), n in
                                     group[group.trough_before != group.trough_after]
                                     .groupby(["trough_before", "trough_after"]).size().items()},
            "clock_changes": int((group.clock_before != group.clock_after).sum()),
            "years_with_monthly_phase_changes": int(group.phase_months_changed.sum()),
            "baseline_eligible_before": int((group.baseline_eligible_before == "True").sum()),
            "baseline_eligible_after": int((group.baseline_eligible_after == "True").sum()),
            "tiles_with_labels_before": int(per_tile.apply(lambda g: g.annual_before.map(_labelled).any()).sum()),
            "tiles_with_labels_after": int(per_tile.apply(lambda g: g.annual_after.map(_labelled).any()).sum()),
            "labelled_years_before": int(group.annual_before.map(_labelled).sum()),
            "labelled_years_after": int(group.annual_after.map(_labelled).sum()),
            "labelled_both": int((group.annual_before.map(_labelled) & group.annual_after.map(_labelled)).sum()),
            "label_changed_where_both": int((group.annual_before.map(_labelled) & group.annual_after.map(_labelled)
                                             & (group.annual_before != group.annual_after)).sum()),
            "labels_removed": int((group.annual_before.map(_labelled) & ~group.annual_after.map(_labelled)).sum()),
        }
    unexpected = {k: v["unexpected"] for k, v in tiles.items() if v.get("unexpected")}
    unexpected.update({k: v["other_tables_changed"] for k, v in tiles.items() if v.get("other_tables_changed")})
    unexpected.update({k: "route" for k, v in tiles.items() if "route" in v and v["route"][0] != v["route"][1]})
    result = {"before": str(before), "after": str(after), "summary": summary, "unexpected": unexpected,
              "tiles": tiles}
    (after.parent / "compare.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("unexpected:", unexpected or "none")


def stage_identity(before: Path) -> None:
    """Does the 0.2.0 rerun reproduce hydropools' stored production hydro-years?"""
    out = {}
    root, _ = SETS["production"]
    for tile_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        stored = _one(tile_dir, "*_hydro_years.csv")
        rerun = _one(before / "production" / tile_dir.name, "*_hydro_years.csv")
        if stored is None or rerun is None:
            out[tile_dir.name] = "missing"
            continue
        a = pd.read_csv(stored, dtype=str, keep_default_na=False)
        b = pd.read_csv(rerun, dtype=str, keep_default_na=False)
        # Later 0.2.0 commits added export columns; compare the columns both runs have.
        common = [c for c in a.columns if c in b.columns]
        diff = _frame_diff(a[common], b[common])
        out[tile_dir.name] = diff["changed"]
        out.setdefault("_columns_only_in_rerun", sorted(c for c in b.columns if c not in a.columns))
    (before.parent / "identity_v020_vs_hydropools.json").write_text(json.dumps(out, indent=2) + "\n",
                                                                     encoding="utf-8")
    same = sum(1 for k, v in out.items() if not k.startswith("_") and v == {})
    print(f"identical to hydropools stored run on shared columns: {same} of {len(out) - 1}")
    for k, v in out.items():
        if v and not k.startswith("_"):
            print(" ", k, v)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=("run", "compare", "identity"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    if args.stage == "run":
        stage_run(args.out, args.workers)
    elif args.stage == "compare":
        stage_compare(args.before, args.after)
    else:
        stage_identity(args.before)


if __name__ == "__main__":
    main()
