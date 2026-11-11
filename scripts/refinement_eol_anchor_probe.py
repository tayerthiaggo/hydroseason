"""Exploratory: anchor the trough search at the end of the climatological low (reported only, no truth)."""
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor

for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "1")
import numpy as np
import pandas as pd

REPO = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO)
TILES = "D:/RLH/5.6/repos/hydropools/work/fitzroy_v3/hydroseason"


def load(name):
    if name.startswith("tile"):
        df = pd.read_csv(f"{TILES}/{name}/channel_monthly_extent.csv")
        dc = [c for c in df.columns if "date" in c.lower()][0]
        return df.set_index(pd.to_datetime(df.pop(dc)))
    if name in ("gilbert_fixture", "fitzroy_fixture"):
        path = {"gilbert_fixture": "gilbert_river_monthly.csv", "fitzroy_fixture": "fitzroy_kimberley_monthly.csv"}[name]
        df = pd.read_csv(f"{REPO}/tests/fixtures/{path}", parse_dates=["date"])
        return df.set_index("date")
    from hydroseason import load_extent_csv
    return load_extent_csv(f"{REPO}/case_studies/data/extent/{name}.csv", date_col="date", value_col="extent_pct")


def end_of_climatological_low(prepared: pd.DataFrame) -> tuple[int, dict]:
    usable = prepared.loc[prepared["candidate_usable"], "extent_pct"]
    clim = usable.groupby(usable.index.month).mean().reindex(range(1, 13))
    lo, hi = float(clim.min()), float(clim.max())
    tol = 0.1 * (hi - lo)
    low = (clim <= lo + tol).to_numpy()
    start = int(np.nanargmin(clim.to_numpy()))
    end = start
    for step in range(1, 12):
        i = (start + step) % 12
        if not low[i]:
            break
        end = i
    return end + 1, {int(k): round(float(v), 3) for k, v in clim.items()}


def run(name):
    warnings.simplefilter("ignore")
    import hydroseason._catchment as catchment
    from hydroseason import analyze_catchment
    from hydroseason._state_input import prepare_monthly_extent

    extent = load(name)
    kwargs = {"date_col": None}
    base = analyze_catchment(extent)
    prepared = prepare_monthly_extent(extent, max_invalid_pct=20.0, quality_policy="flag")
    anchor, clim = end_of_climatological_low(prepared)
    current_anchor = base.state.config.expected_trough_month if base.state is not None else None
    real = catchment.DynamicHydroYearConfig
    catchment.DynamicHydroYearConfig = lambda **kw: real(**{**kw, "expected_trough_month": anchor})
    try:
        anchored = analyze_catchment(extent)
    finally:
        catchment.DynamicHydroYearConfig = real
    out = {"name": name, "current_anchor": current_anchor, "proposed_anchor": anchor, "route": [base.route, anchored.route]}
    for label, result in (("current", base), ("anchored", anchored)):
        hy = result.hydro_years
        if hy is None or not len(hy):
            out[label] = {"years": 0}
            continue
        b, e = pd.to_datetime(hy["trough_month"]), pd.to_datetime(hy["dry_run_end_month"])
        gap = ((e.dt.year - b.dt.year) * 12 + e.dt.month - b.dt.month).dropna()
        out[label] = {"years": len(hy), "late": int((gap > 0).sum()), "late3": int((gap >= 3).sum()),
                      "early": int((gap < 0).sum()),
                      "boundary_months": {int(k): int(v) for k, v in pd.Series(b.dt.month).value_counts().head(3).items()},
                      "unresolved_timing": int((hy["timing_status"] == "unresolved").sum()),
                      "rollbacks": int((hy["trough_refinement_reason"] == "atomic_rollback_cycle").sum()),
                      "applied": int(hy["trough_refinement_applied"].sum())}
        if name.endswith("fixture"):
            out[label]["troughs"] = " ".join(d.strftime("%y-%m") for d in b)
    return out


if __name__ == "__main__":
    names = ["tile05", "tile13", "tile54", "tile46", "tile03", "gilbert_fixture", "fitzroy_fixture",
             "daly_river_nt_30m", "fitzroy_river_wa_30m", "gilbert_river_qld_30m"]
    with ProcessPoolExecutor(max_workers=8) as pool:
        for r in pool.map(run, names):
            print(r["name"], "anchor", r["current_anchor"], "->", r["proposed_anchor"], r["route"])
            for k in ("current", "anchored"):
                print("   ", k, {x: y for x, y in r[k].items()})
