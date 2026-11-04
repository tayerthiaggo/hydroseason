"""X1: year-by-year agreement of HydroSeason dates across nested areas.

Plan and decision rules: docs/handoff/2026-11-02-x1-cross-scale-agreement-plan.md.
Uses the series of the spatial unit study (scripts/spatial_unit_study.py).

    python scripts/cross_scale_agreement.py analyze [--workers N]
    python scripts/cross_scale_agreement.py evaluate
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spatial_unit_study import (  # noqa: E402
    DEFAULT_DATA,
    DEFAULT_OUT,
    REPO_ROOT,
    WATER_BINS,
    _bin,
    _git,
    clean_json,
    load_series,
    sha256_file,
    sha256_text_lf,
    unit_frame,
)

HANDOFF = REPO_ROOT / "docs" / "handoff"
PLAN = HANDOFF / "2026-11-02-x1-cross-scale-agreement-plan.md"
RECEIPT = HANDOFF / "2026-11-02-x1-cross-scale-agreement-receipt.json"
RESULTS = HANDOFF / "2026-11-02-x1-cross-scale-agreement-results.json"
STUDY_RECEIPT = HANDOFF / "2026-11-02-spatial-unit-study-receipt.json"
SCHEMES = ("catchment", "hb6", "hb7", "hb8")
MATCH_WINDOW_MONTHS = 6
AGREE_MONTHS = 1
SHARE = 0.80
MIN_CYCLES = 30
MARGIN = 0.10
N_BOOT = 2000


def log(out: Path, message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(out / "x1.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def month_index(value) -> int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    return stamp.year * 12 + stamp.month - 1


# ---------------------------------------------------------------- analyze


def _cycles(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    unit_id, rows = payload
    started = time.perf_counter()
    try:
        analysis = analyze_catchment(unit_frame(pd.DataFrame(rows)), phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        return {"unit_id": unit_id, "route": "error", "error": f"{type(exc).__name__}: {exc}"[:500], "cycles": []}
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    cycles = []
    for _, row in hy.iterrows():
        cycles.append({
            "hy_year": int(row["hy_year"]),
            "peak": month_index(row.get("peak_month")),
            "trough": month_index(row.get("trough_month")),
            "peak_status": row.get("peak_timing_status"),
            "trough_status": row.get("trough_timing_status"),
        })
    return {"unit_id": unit_id, "route": analysis.route, "error": None, "cycles": cycles,
            "seconds": round(time.perf_counter() - started, 2)}


def write_receipt(out: Path) -> dict:
    import hydroseason

    receipt = {
        "plan": str(PLAN.relative_to(REPO_ROOT)).replace("\\", "/"),
        "plan_sha256_lf": sha256_text_lf(PLAN),
        "script_sha256_lf": sha256_text_lf(Path(__file__)),
        "study_receipt_sha256_lf": sha256_text_lf(STUDY_RECEIPT),
        "study_script_sha256_lf": sha256_text_lf(Path(__file__).resolve().parent / "spatial_unit_study.py"),
        "git_head": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_status_short": _git("status", "--short").splitlines(),
        "hydroseason_version": hydroseason.__version__,
        "analysis_call": 'analyze_catchment(extent, phase_scheme="two_phase", quality_policy="flag")',
        "units_csv_sha256": sha256_file(out / "units.csv"),
        "series_sha256": {f.name: sha256_file(f) for f in sorted((out / "series").glob("*.csv.gz"))},
        "receipt_written_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def stage_analyze(out: Path, workers: int) -> None:
    x1 = out / "x1"
    x1.mkdir(parents=True, exist_ok=True)
    if not (x1 / "receipt_written.flag").exists():
        receipt = write_receipt(out)
        (x1 / "receipt_written.flag").write_text(receipt["receipt_written_utc"], encoding="utf-8")
        log(x1, f"analyze: receipt written, plan sha256 {receipt['plan_sha256_lf']}")
    units = pd.read_csv(out / "units.csv")
    units = units[units["scheme"].isin(SCHEMES)]
    sink_path = x1 / "cycles.jsonl"
    done = set()
    if sink_path.exists():
        done = {json.loads(line)["unit_id"] for line in sink_path.read_text(encoding="utf-8").splitlines() if line}
    todo = units[~units["unit_id"].isin(done)].sort_values("area_km2", ascending=False)
    series = load_series(out)
    grouped = {uid: g.drop(columns="unit_id").to_dict(orient="list") for uid, g in series.groupby("unit_id")}
    log(x1, f"analyze: {len(todo)} units to run, {len(done)} done, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(sink_path, "a", encoding="utf-8") as sink:
        futures = {pool.submit(_cycles, (uid, grouped[uid])): uid for uid in todo["unit_id"]}
        for n, future in enumerate(as_completed(futures), start=1):
            sink.write(json.dumps(clean_json(future.result())) + "\n")
            sink.flush()
            if n % 50 == 0 or n == len(futures):
                log(x1, f"analyze: {n}/{len(futures)} units, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- evaluate


def parent_map(data: Path, units: pd.DataFrame) -> dict[str, str]:
    """Inner subbasin unit -> containing unit one level up (or the catchment)."""
    import geopandas as gpd

    hb = units[units["scheme"].str.startswith("hb")].copy()
    hb["hybas"] = hb["unit_id"].str.split(":").str[2].astype("int64")
    pfaf: dict[int, str] = {}
    for level in (6, 7, 8):
        shp = data / "raw" / "HydroBASINS" / f"hybas_au_lev{level:02d}_v1c.shp"
        table = gpd.read_file(shp, columns=["HYBAS_ID", "PFAF_ID"], ignore_geometry=True)
        pfaf.update(dict(zip(table["HYBAS_ID"].astype("int64"), table["PFAF_ID"].astype(str))))
    hb["pfaf"] = hb["hybas"].map(pfaf)
    by_code = {(r.key, int(r.level), r.pfaf): r.unit_id for r in hb.itertuples()}
    parents = {}
    for r in hb.itertuples():
        if int(r.level) == 6:
            parents[r.unit_id] = f"{r.key}:catchment"
        else:
            parents[r.unit_id] = by_code.get((r.key, int(r.level) - 1, r.pfaf[:-1]))
    return parents


def match_cycles(inner: list[dict], outer: list[dict]) -> list[tuple[dict, dict]]:
    candidates = []
    for i, a in enumerate(inner):
        for j, b in enumerate(outer):
            if a["peak"] is None or b["peak"] is None:
                continue
            distance = abs(a["peak"] - b["peak"])
            if distance <= MATCH_WINDOW_MONTHS:
                candidates.append((distance, i, j))
    used_i, used_j, pairs = set(), set(), []
    for _, i, j in sorted(candidates):
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        pairs.append((inner[i], outer[j]))
    return pairs


def pair_rows(cycles: dict[str, dict], parents: dict[str, str], water: dict[str, float]) -> pd.DataFrame:
    rows = []
    for inner_id, parent_id in parents.items():
        key, scheme = inner_id.split(":")[0], inner_id.split(":")[1]
        relations = {"catchment": f"{key}:catchment"}
        if parent_id is not None:
            relations["parent"] = parent_id
        for relation, outer_id in relations.items():
            inner, outer = cycles.get(inner_id), cycles.get(outer_id)
            if inner is None or outer is None:
                continue
            if inner["route"] != "per_year_detection" or outer["route"] != "per_year_detection":
                continue
            n_inner = sum(c["peak"] is not None for c in inner["cycles"])
            for a, b in match_cycles(inner["cycles"], outer["cycles"]):
                trough_diff = None if a["trough"] is None or b["trough"] is None else a["trough"] - b["trough"]
                rows.append({
                    "inner": inner_id, "outer": outer_id, "relation": relation, "key": key, "level": scheme,
                    "water": water.get(inner_id, np.nan), "n_inner_cycles": n_inner,
                    "peak_agree": float(abs(a["peak"] - b["peak"]) <= AGREE_MONTHS),
                    "trough_agree": np.nan if trough_diff is None else float(abs(trough_diff) <= AGREE_MONTHS),
                    "both_peak_point": a["peak_status"] == "point" and b["peak_status"] == "point",
                    "both_trough_point": a["trough_status"] == "point" and b["trough_status"] == "point",
                })
    frame = pd.DataFrame(rows)
    frame["water_bin"] = _bin(frame["water"], WATER_BINS).astype(str)
    return frame


def unit_sums(pairs: pd.DataFrame) -> pd.DataFrame:
    """Agreement counts per inner unit and relation, the resampling unit of the bootstrap."""
    table = pairs.assign(
        pa=pairs["peak_agree"], pn=1.0,
        ta=pairs["trough_agree"].fillna(0.0), tn=pairs["trough_agree"].notna().astype(float),
    )
    keys = ["key", "inner", "relation", "level", "water_bin"]
    return table.groupby(keys, as_index=False)[["pa", "pn", "ta", "tn"]].sum()


def share(sums: pd.DataFrame, date: str, weights: pd.Series | None = None) -> float | None:
    a, n = ("pa", "pn") if date == "peak" else ("ta", "tn")
    w = 1.0 if weights is None else sums["inner"].map(weights).fillna(0.0)
    denominator = float((sums[n] * w).sum())
    return float((sums[a] * w).sum()) / denominator if denominator > 0 else None


def bootstrap_weights(sums: pd.DataFrame, rng) -> list[pd.Series]:
    units = {k: np.sort(g["inner"].unique()) for k, g in sums.groupby("key")}
    draws = []
    for _ in range(N_BOOT):
        picks = np.concatenate([rng.choice(u, size=len(u), replace=True) for u in units.values()])
        draws.append(pd.Series(picks).value_counts().astype(float))
    return draws


def _ci(values: list) -> list:
    values = [v for v in values if v is not None]
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))] if values else [None, None]


def stage_evaluate(data: Path, out: Path) -> dict:
    x1 = out / "x1"
    units = pd.read_csv(out / "units.csv")
    records = [json.loads(line) for line in (x1 / "cycles.jsonl").read_text(encoding="utf-8").splitlines() if line]
    cycles = {r["unit_id"]: r for r in records}
    series = load_series(out)
    water = series.groupby("unit_id")["n_water"].median().to_dict()
    parents = parent_map(data, units)
    pairs = pair_rows(cycles, parents, water)
    pairs.to_csv(x1 / "pairs.csv", index=False, lineterminator="\n")
    sums = unit_sums(pairs)
    point_sums = {date: unit_sums(pairs[pairs[f"both_{date}_point"]]) for date in ("peak", "trough")}
    draws = bootstrap_weights(sums, np.random.default_rng(0))
    labels = [f"[{a},{b})" for a, b in zip(WATER_BINS[:-1], WATER_BINS[1:])]

    tables, r1 = {}, {}
    for relation in ("parent", "catchment"):
        rel = sums[sums["relation"] == relation]
        for date in ("peak", "trough"):
            n_col = "pn" if date == "peak" else "tn"
            bins = {
                lb: {"share": share(rel[rel["water_bin"] == lb], date), "n": int(rel.loc[rel["water_bin"] == lb, n_col].sum())}
                for lb in labels
            }
            levels = {
                lv: {"share": share(rel[rel["level"] == lv], date), "n": int(rel.loc[rel["level"] == lv, n_col].sum())}
                for lv in ("hb6", "hb7", "hb8")
            }
            point_rel = point_sums[date][point_sums[date]["relation"] == relation]
            tables[f"{relation}_{date}"] = {
                "pooled": share(rel, date), "n": int(rel[n_col].sum()),
                "ci95": _ci([share(rel, date, w) for w in draws]),
                "by_water_pixels": bins, "by_level": levels,
                "point_only": {"share": share(point_rel, date), "n": int(point_rel[n_col].sum())},
                "by_catchment": {k: {"share": share(g, date), "n": int(g[n_col].sum())} for k, g in rel.groupby("key")},
            }
            minimum = None
            for i, label in enumerate(labels):
                rest = [bins[lb] for lb in labels[i:] if bins[lb]["n"] >= MIN_CYCLES]
                if bins[label]["n"] >= MIN_CYCLES and rest and all(b["share"] >= SHARE for b in rest):
                    minimum = WATER_BINS[i]
                    break
            r1[f"{relation}_{date}"] = minimum

    catch = sums[sums["relation"] == "catchment"]

    def peak_minus_trough(frame, weights=None):
        p, t = share(frame, "peak", weights), share(frame, "trough", weights)
        return None if p is None or t is None else p - t

    diff = peak_minus_trough(catch)
    ci = _ci([peak_minus_trough(catch, w) for w in draws])
    per_key = {k: peak_minus_trough(g) for k, g in catch.groupby("key")}
    pos = sum(v > 0 for v in per_key.values() if v is not None)
    neg = sum(v < 0 for v in per_key.values() if v is not None)
    if diff is not None and ci[0] is not None and diff >= MARGIN and ci[0] > 0 and pos >= 3:
        r2 = "peaks_more_widely_shared"
    elif diff is not None and ci[1] is not None and diff <= -MARGIN and ci[1] < 0 and neg >= 3:
        r2 = "troughs_more_widely_shared"
    elif ci[0] is not None and ci[0] > -MARGIN and ci[1] < MARGIN:
        r2 = "similar"
    else:
        r2 = "inconclusive"

    nested = sums[sums["level"].isin(["hb7", "hb8"])]
    nested = nested[nested.groupby("inner")["relation"].transform("nunique") == 2]
    r3 = {}
    for date in ("peak", "trough"):
        def parent_minus_catchment(frame, weights=None, d=date):
            p = share(frame[frame["relation"] == "parent"], d, weights)
            q = share(frame[frame["relation"] == "catchment"], d, weights)
            return None if p is None or q is None else p - q

        value = parent_minus_catchment(nested)
        interval = _ci([parent_minus_catchment(nested, w) for w in draws])
        r3[date] = {
            "difference": value, "ci95": interval,
            "parent_closer": bool(interval[0] is not None and interval[0] > 0),
            "catchment_closer": bool(interval[1] is not None and interval[1] < 0),
            "n_inner_units": int(nested["inner"].nunique()),
        }

    match_rate = {}
    for relation in ("parent", "catchment"):
        rel = pairs[pairs["relation"] == relation]
        inner_cycles = int(rel.drop_duplicates("inner")["n_inner_cycles"].sum())
        match_rate[relation] = {
            "matched_cycles": int(len(rel)), "inner_cycles": inner_cycles,
            "rate": float(len(rel) / inner_cycles) if inner_cycles else None,
        }

    results = {
        "receipt_sha256_lf": sha256_text_lf(RECEIPT),
        "n_units_analysed": len(records),
        "routes": pd.Series([r["route"] for r in records]).value_counts().to_dict(),
        "errors": [r["unit_id"] for r in records if r["route"] == "error"],
        "units_without_kept_parent": sorted(k for k, v in parents.items() if v is None),
        "match_rate": match_rate,
        "agreement": tables,
        "r1_minimum_water_pixels": r1,
        "r2_peak_vs_trough": {"decision": r2, "difference": diff, "ci95": ci, "per_catchment": per_key},
        "r3_parent_vs_catchment": r3,
    }
    RESULTS.write_text(json.dumps(clean_json(results), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    log(x1, f"evaluate: R2 {r2}; R1 {r1}; wrote {RESULTS.name}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["analyze", "evaluate"])
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.stage == "analyze":
        stage_analyze(args.out, args.workers)
    else:
        stage_evaluate(args.data, args.out)


if __name__ == "__main__":
    main()
