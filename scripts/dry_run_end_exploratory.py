"""Exploratory: where does the dry-season low run really end on the Fitzroy tiles?

For every per-year cycle, follow the boundary's low run (months within HydroSeason's own
tolerance of the boundary extent) forward past the search window, using the library's
frame and tolerance, and compare its end with the boundary and the window edge.
Run with the 0.3.0 checkout on PYTHONPATH. Writes dry_run_tiles.csv next to this script.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

HP = Path("D:/RLH/5.6/repos/hydropools/work")
SETS = {"production": (HP / "fitzroy_v3" / "hydroseason", "channel_monthly_extent.csv"),
        "counts": (HP / "u1" / "fitzroy" / "tiles_e", "series.csv")}
OUT = Path(__file__).with_name("dry_run_tiles.csv")


def one(job):
    set_name, tile, path = job
    warnings.simplefilter("ignore")
    from hydroseason._boundary import _epsilon_pp, robust_scale
    from hydroseason._catchment import analyze_catchment
    from hydroseason._state_input import prepare_monthly_extent
    from hydroseason._workflow_input import resolve_water_input

    extent = resolve_water_input(str(path)).extent
    analysis = analyze_catchment(extent)
    rows = []
    if analysis.route != "per_year_detection":
        return rows
    frame = prepare_monthly_extent(extent, max_invalid_pct=analysis.max_invalid_pct)
    amplitude, noise = robust_scale(frame)
    hy = analysis.hydro_years.reset_index(drop=True)
    present = frame["extent_pct"].notna() & frame["invalid_pct"].lt(100.0)
    months = list(frame.index)
    for i, c in hy.iterrows():
        t = c.get("trough_month")
        if pd.isna(t) or pd.Timestamp(t) not in frame.index:
            continue
        t = pd.Timestamp(t)
        level = float(frame.loc[t, "extent_pct"])
        eps = _epsilon_pp(frame.loc[t], noise_pp=noise, amplitude_pp=amplitude)
        pos = months.index(t)
        end, rise = t, None
        for m in months[pos + 1:]:
            if not present.loc[m]:
                continue  # unobserved month: neither extends nor ends the run
            if float(frame.loc[m, "extent_pct"]) <= level + eps:
                end = m
            else:
                rise = m
                break
        nxt = hy.iloc[i + 1] if i + 1 < len(hy) else None
        rows.append({
            "set": set_name, "tile": tile, "hy_year": int(c["hy_year"]),
            "status": c["status"], "trough_timing_status": c.get("trough_timing_status"),
            "boundary": t, "low_run_end_window": c.get("low_run_end_month"),
            "low_run_end_true": end, "rise_month": rise,
            "next_peak": None if nxt is None else nxt.get("peak_month"),
            "level": level, "eps": eps,
        })
    return rows


def main():
    jobs = []
    for set_name, (root, filename) in SETS.items():
        for d in sorted(p for p in root.iterdir() if (p / filename).exists()):
            jobs.append((set_name, d.name, d / filename))
    rows = []
    with ProcessPoolExecutor(max_workers=int(sys.argv[1]) if len(sys.argv) > 1 else 10) as pool:
        for n, r in enumerate(pool.map(one, jobs), start=1):
            rows.extend(r)
            print(f"{n}/{len(jobs)}", flush=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print("written", OUT, len(rows))


if __name__ == "__main__":
    main()
