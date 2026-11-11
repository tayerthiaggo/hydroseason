"""Spatial unit study: the same pixels summed into catchments, subbasins and tiles.

Plan and decision rules: docs/handoff/2026-11-02-spatial-unit-study-plan.md.

Stages, run in order (each writes into --out and can be rerun):

    units      build catchment, HydroBASINS subbasin and grid-tile units
    aggregate  sum per-pixel monthly WOfS majority composites into each unit
    validate   compare each catchment series with the committed case-study CSV
    analyze    write the receipt, then run analyze_catchment on every unit
    evaluate   apply the pre-registered comparisons and write the results JSON

Inputs live outside the repository (default D:/RLH/5.6/data_local); see the
plan for sources and hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN = REPO_ROOT / "docs" / "handoff" / "2026-11-02-spatial-unit-study-plan.md"
RECEIPT = REPO_ROOT / "docs" / "handoff" / "2026-11-02-spatial-unit-study-receipt.json"
RESULTS = REPO_ROOT / "docs" / "handoff" / "2026-11-02-spatial-unit-study-results.json"
CASE_EXTENT = REPO_ROOT / "case_studies" / "data" / "extent"
CASE_SUMMARY = REPO_ROOT / "tests" / "fixtures" / "v020" / "case_studies" / "main_summary.csv"

DEFAULT_DATA = Path(r"D:\RLH\5.6\data_local")
DEFAULT_OUT = DEFAULT_DATA / "intermediate" / "hydroseason_spatial_unit_study"

# Case-study key -> cube name in raw/WaterMask-TSFill/cache.
CATCHMENTS = {
    "daly_river_nt": "daly_river_nt",
    "fitzroy_river_wa": "fitzroy_river",
    "gilbert_river_qld": "gilbert",
    "lachlan_river_nsw": "lachlan_river_nsw",
    "moonie_river_qld_nsw": "moonie_river_qld_nsw",
}
LEVELS = (6, 7, 8)
SCHEMES = ("catchment",) + tuple(f"hb{lv}" for lv in LEVELS) + tuple(f"tile{lv}" for lv in LEVELS)
START, END = "2005-01-01", "2025-12-01"
CHUNK = 512
ALBERS = 3577

AREA_BINS = [0, 300, 1000, 3000, 10000, math.inf]
WATER_BINS = [0, 100, 1_000, 10_000, 100_000, math.inf]
MARGIN = 0.10
SIZE_SHARE = 0.80
SIZE_MIN_UNITS = 5
ASYNC_SHARE = 0.25
N_BOOT = 2000


# ---------------------------------------------------------------- helpers


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text_lf(path: Path) -> str:
    """Hash of LF-normalised bytes, stable across core.autocrlf checkouts."""
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def paths(data: Path) -> dict[str, Path]:
    raw = data / "raw"
    return {
        "cubes": raw / "WaterMask-TSFill" / "cache",
        "boundaries": raw / "catchments",
        "dwer": raw / "WaterMask-TSFill" / "shp" / "Fitzroy_catchment_DWER.shp",
        "hydrobasins": raw / "HydroBASINS",
    }


def cube_path(data: Path, key: str) -> Path:
    return paths(data)["cubes"] / f"raw_wofs_flags_{CATCHMENTS[key]}_1986_2026.zarr"


def study_months() -> pd.DatetimeIndex:
    return pd.date_range(START, END, freq="MS")


def log(out: Path, message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(out / "study.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def clean_json(value):
    """Replace NaN and numpy scalars so the output is strict JSON."""
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def circular_month_distance(a: float, b: float) -> float:
    d = abs(a - b) % 12
    return min(d, 12 - d)


# ---------------------------------------------------------------- units


def study_area(data: Path, key: str):
    import geopandas as gpd
    import shapely

    p = paths(data)
    geom = gpd.read_file(p["boundaries"] / f"{key}_boundary.geojson").to_crs(ALBERS).geometry.union_all()
    if key == "fitzroy_river_wa":
        # The Fitzroy cube covers the WA DWER outline only (plan, Data).
        dwer = gpd.read_file(p["dwer"]).to_crs(ALBERS).geometry.union_all()
        geom = geom.intersection(dwer)
    return shapely.make_valid(geom)


def _square_tiles(geom, side_m: float):
    import shapely

    minx, miny, maxx, maxy = geom.bounds
    xs = np.arange(math.floor(minx / side_m) * side_m, maxx, side_m)
    ys = np.arange(math.floor(miny / side_m) * side_m, maxy, side_m)
    boxes, names = [], []
    for x in xs:
        for y in ys:
            boxes.append(shapely.box(x, y, x + side_m, y + side_m))
            names.append(f"{int(x // side_m)}_{int(y // side_m)}")
    boxes = np.array(boxes, dtype=object)
    clipped = shapely.intersection(boxes, geom)
    keep = shapely.area(clipped) >= 0.5 * side_m * side_m
    return [n for n, k in zip(names, keep) if k], list(clipped[keep])


def stage_units(data: Path, out: Path) -> None:
    import geopandas as gpd
    import shapely

    if (out / "series").exists() or (out / "labels").exists():
        raise SystemExit("units already aggregated; delete series/ and labels/ before rebuilding units")
    areas = {key: study_area(data, key) for key in CATCHMENTS}
    union = shapely.union_all(list(areas.values()))
    bbox = tuple(gpd.GeoSeries([union], crs=ALBERS).to_crs(4326).total_bounds)
    rows = [
        {"unit_id": f"{key}:catchment", "key": key, "scheme": "catchment", "level": 0, "geometry": geom}
        for key, geom in areas.items()
    ]
    for level in LEVELS:
        shp = paths(data)["hydrobasins"] / f"hybas_au_lev{level:02d}_v1c.shp"
        hb = gpd.read_file(shp, bbox=bbox).to_crs(ALBERS)
        for key, geom in areas.items():
            cand = hb[hb.intersects(geom)]
            clipped = shapely.intersection(np.array(cand.geometry, dtype=object), geom)
            keep = shapely.area(clipped) >= 0.5 * shapely.area(np.array(cand.geometry, dtype=object))
            for hybas_id, part in zip(cand["HYBAS_ID"][keep], clipped[keep]):
                rows.append({
                    "unit_id": f"{key}:hb{level}:{int(hybas_id)}", "key": key,
                    "scheme": f"hb{level}", "level": level, "geometry": shapely.make_valid(part),
                })
    units = gpd.GeoDataFrame(rows, crs=ALBERS)
    units["area_km2"] = units.area / 1e6

    sides = {}
    tile_rows = []
    for level in LEVELS:
        median_km2 = float(units.loc[units["scheme"] == f"hb{level}", "area_km2"].median())
        side_km = int(round(math.sqrt(median_km2)))
        sides[level] = {"median_subbasin_km2": round(median_km2, 3), "tile_side_km": side_km}
        for key, geom in areas.items():
            names, parts = _square_tiles(geom, side_km * 1000.0)
            for name, part in zip(names, parts):
                tile_rows.append({
                    "unit_id": f"{key}:tile{level}:{name}", "key": key,
                    "scheme": f"tile{level}", "level": level, "geometry": shapely.make_valid(part),
                })
    tiles = gpd.GeoDataFrame(tile_rows, crs=ALBERS)
    tiles["area_km2"] = tiles.area / 1e6
    units = pd.concat([units, tiles], ignore_index=True)
    units = gpd.GeoDataFrame(units, crs=ALBERS)

    out.mkdir(parents=True, exist_ok=True)
    units.to_file(out / "units.gpkg", driver="GPKG")
    units.drop(columns="geometry").to_csv(out / "units.csv", index=False, lineterminator="\n")
    (out / "units_meta.json").write_text(json.dumps({
        "tile_sides": sides,
        "counts": units.groupby(["key", "scheme"]).size().unstack(fill_value=0).to_dict(orient="index"),
    }, indent=2), encoding="utf-8")
    log(out, f"units: {len(units)} units; tile sides {sides}")


# ---------------------------------------------------------------- aggregate


def _grid(cube) -> tuple[tuple[int, int], object]:
    from affine import Affine

    gt = [float(v) for v in str(cube["spatial_ref"].attrs["GeoTransform"]).split()]
    return (cube.sizes["y"], cube.sizes["x"]), Affine(gt[1], gt[2], gt[0], gt[4], gt[5], gt[3])


def _labels(out: Path, key: str, units, shape, transform) -> dict[str, Path]:
    from rasterio.features import rasterize

    label_dir = out / "labels"
    label_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for scheme in SCHEMES:
        path = label_dir / f"{key}_{scheme}.npy"
        files[scheme] = path
        if path.exists():
            continue
        sub = units[(units["key"] == key) & (units["scheme"] == scheme)].reset_index(drop=True)
        if len(sub) >= np.iinfo(np.int16).max:
            raise ValueError(f"too many units for int16 labels: {key} {scheme}")
        shapes = ((geom, i + 1) for i, geom in enumerate(sub.geometry))
        arr = rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="int16", all_touched=False)
        np.save(path, arr)
        del arr
    return files


def _block_sums(args):
    by, bx, shape, label_files, cw_arr, cd_arr, t0, t1 = args
    ys = slice(by * CHUNK, min((by + 1) * CHUNK, shape[0]))
    xs = slice(bx * CHUNK, min((bx + 1) * CHUNK, shape[1]))
    labs = {s: np.load(p, mmap_mode="r")[ys, xs] for s, p in label_files.items()}
    if not (labs["catchment"] > 0).any():
        return None
    cw = cw_arr[t0:t1, ys, xs]
    cd = cd_arr[t0:t1, ys, xs]
    water = cw > cd
    valid = (cw > 0) | (cd > 0)
    result = {}
    for scheme, lab in labs.items():
        mask = lab > 0
        if not mask.any():
            continue
        flat = lab[mask]
        order = np.argsort(flat, kind="stable")
        ordered = flat[order]
        starts = np.flatnonzero(np.r_[True, ordered[1:] != ordered[:-1]])
        ids = ordered[starts].astype(np.int64)
        w = water[:, mask][:, order]
        v = valid[:, mask][:, order]
        result[scheme] = (
            ids,
            np.add.reduceat(w, starts, axis=1, dtype=np.int64),
            np.add.reduceat(v, starts, axis=1, dtype=np.int64),
            np.diff(np.r_[starts, ordered.size]).astype(np.int64),
        )
    return result


def stage_aggregate(data: Path, out: Path, keys: list[str], threads: int) -> None:
    import xarray as xr
    import zarr

    units = _read_units_gpkg(out)
    months = study_months()
    for key in keys:
        target = out / "series" / f"{key}.csv.gz"
        if target.exists():
            log(out, f"aggregate {key}: exists, skipped")
            continue
        path = cube_path(data, key)
        cube = xr.open_zarr(path)
        times = pd.DatetimeIndex(cube["time"].values).to_period("M").to_timestamp()
        t0 = int(times.get_loc(months[0]))
        t1 = int(times.get_loc(months[-1])) + 1
        if not times[t0:t1].equals(months):
            raise ValueError(f"{key}: cube months are not the complete study window")
        shape, transform = _grid(cube)
        started = time.perf_counter()
        label_files = _labels(out, key, units, shape, transform)
        log(out, f"aggregate {key}: labels ready in {time.perf_counter() - started:.0f}s, grid {shape}")
        group = zarr.open_group(str(path), mode="r")
        cw_arr, cd_arr = group["n_clear_water"], group["n_clear_dry"]
        n_units = {s: int(((units["key"] == key) & (units["scheme"] == s)).sum()) for s in SCHEMES}
        water = {s: np.zeros((n_units[s] + 1, len(months)), np.int64) for s in SCHEMES}
        valid = {s: np.zeros((n_units[s] + 1, len(months)), np.int64) for s in SCHEMES}
        aoi = {s: np.zeros(n_units[s] + 1, np.int64) for s in SCHEMES}
        blocks = [
            (by, bx, shape, label_files, cw_arr, cd_arr, t0, t1)
            for by in range(math.ceil(shape[0] / CHUNK))
            for bx in range(math.ceil(shape[1] / CHUNK))
        ]
        done = 0
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = [pool.submit(_block_sums, b) for b in blocks]
            for future in as_completed(futures):
                result = future.result()
                done += 1
                if result:
                    for scheme, (ids, w, v, npx) in result.items():
                        water[scheme][ids] += w.T
                        valid[scheme][ids] += v.T
                        aoi[scheme][ids] += npx
                if done % 100 == 0 or done == len(blocks):
                    log(out, f"aggregate {key}: {done}/{len(blocks)} blocks, {time.perf_counter() - started:.0f}s")
        frames = []
        for scheme in SCHEMES:
            sub = units[(units["key"] == key) & (units["scheme"] == scheme)].reset_index(drop=True)
            for i, unit_id in enumerate(sub["unit_id"], start=1):
                frames.append(pd.DataFrame({
                    "unit_id": unit_id, "date": months.strftime("%Y-%m-%d"),
                    "n_water": water[scheme][i], "n_valid": valid[scheme][i], "n_aoi": aoi[scheme][i],
                }))
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(frames, ignore_index=True).to_csv(target, index=False, lineterminator="\n")
        log(out, f"aggregate {key}: wrote {target.name}")


def _read_units_gpkg(out: Path):
    import geopandas as gpd

    return gpd.read_file(out / "units.gpkg")


# ---------------------------------------------------------------- validate


def unit_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """Monthly extent frame in the shape load_extent_csv returns."""
    frame = rows.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    n_valid = frame["n_valid"].astype(float)
    frame["extent_pct"] = np.where(n_valid > 0, 100.0 * frame["n_water"] / n_valid.where(n_valid > 0), np.nan)
    frame["invalid_pct"] = 100.0 * (frame["n_aoi"] - frame["n_valid"]) / frame["n_aoi"]
    return frame[["extent_pct", "invalid_pct", "n_water", "n_valid", "n_aoi"]].sort_index()


def load_series(out: Path) -> pd.DataFrame:
    return pd.concat(
        [pd.read_csv(p) for p in sorted((out / "series").glob("*.csv.gz"))], ignore_index=True
    )


def stage_validate(out: Path) -> dict:
    series = load_series(out)
    report = {}
    for key in CATCHMENTS:
        rows = series[series["unit_id"] == f"{key}:catchment"].drop(columns="unit_id")
        if rows.empty:
            continue
        cube = unit_frame(rows)
        case = pd.read_csv(CASE_EXTENT / f"{key}_30m.csv", parse_dates=["date"]).set_index("date")
        both = pd.concat([cube["extent_pct"].rename("cube"), case["extent_pct"].rename("case")], axis=1).dropna()
        r = float(np.corrcoef(both["cube"], both["case"])[0, 1])
        aoi_ratio = float(cube["n_aoi"].iloc[0] / case["n_aoi"].iloc[0])
        aoi_ok = True if key == "fitzroy_river_wa" else abs(aoi_ratio - 1) <= 0.01
        report[key] = {
            "pearson_r": round(r, 6), "months_compared": int(len(both)),
            "n_aoi_cube": int(cube["n_aoi"].iloc[0]), "n_aoi_case": int(case["n_aoi"].iloc[0]),
            "n_aoi_ratio": round(aoi_ratio, 6),
            "max_abs_extent_diff_pp": round(float((both["cube"] - both["case"]).abs().max()), 6),
            "pass": bool(r >= 0.995 and aoi_ok),
        }
    (out / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for key, item in report.items():
        log(out, f"validate {key}: {item}")
    return report


# ---------------------------------------------------------------- analyze


def _analyze_unit(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    unit_id, rows = payload
    started = time.perf_counter()
    if max(rows["n_aoi"]) == 0:
        # A sliver smaller than one pixel after rasterising: listed, not analysed.
        return {"unit_id": unit_id, "route": "no_pixels", "n_aoi": 0, "error": None, "seconds": 0.0}
    frame = unit_frame(pd.DataFrame(rows))
    record = {"unit_id": unit_id, "median_n_water": float(frame["n_water"].median()),
              "max_n_water": int(frame["n_water"].max()), "n_aoi": int(frame["n_aoi"].iloc[0])}
    try:
        analysis = analyze_catchment(frame, phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update({"route": "error", "error": f"{type(exc).__name__}: {exc}"[:500],
                       "seconds": round(time.perf_counter() - started, 2)})
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()

    def count(column, value):
        return int((hy[column] == value).sum()) if column in hy.columns else None

    def opt(value):
        return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)

    regime = analysis.regime
    record.update({
        "route": analysis.route,
        "regime": regime.regime,
        "route_reason": str(analysis.route_reason)[:300],
        "n_hydro_years": int(len(hy)),
        "n_confirmed": count("boundary_status", "confirmed"),
        "n_trough_point": count("trough_timing_status", "point"),
        "n_peak_point": count("peak_timing_status", "point"),
        "n_baseline_eligible": int(hy["baseline_eligible"].sum()) if "baseline_eligible" in hy.columns else None,
        "status_reasons": json.dumps(hy["status_reason"].value_counts().to_dict()) if "status_reason" in hy.columns else None,
        "peak_month": opt(analysis.mean_monthly_peak_month),
        "trough_month": opt(analysis.mean_monthly_trough_month),
        "amplitude_snr": opt(getattr(regime, "amplitude_snr", None)),
        "peak_timing_concentration": opt(getattr(regime, "peak_timing_concentration", None)),
        "trough_timing_concentration": opt(getattr(regime, "trough_timing_concentration", None)),
        "error": None,
        "seconds": round(time.perf_counter() - started, 2),
    })
    return record


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def write_receipt(data: Path, out: Path) -> dict:
    import hydroseason

    p = paths(data)
    hb_dir = p["hydrobasins"]
    cubes = {}
    for key in CATCHMENTS:
        path = cube_path(data, key)
        meta = path / ".zmetadata"
        cubes[key] = {
            "path": str(path),
            "zmetadata_sha256": sha256_file(meta) if meta.exists() else None,
            "zattrs_sha256": sha256_file(path / ".zattrs") if (path / ".zattrs").exists() else None,
        }
    receipt = {
        "plan": str(PLAN.relative_to(REPO_ROOT)).replace("\\", "/"),
        "plan_sha256_lf": sha256_text_lf(PLAN),
        "script_sha256_lf": sha256_text_lf(Path(__file__)),
        "git_head": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_status_short": _git("status", "--short").splitlines(),
        "hydroseason_version": hydroseason.__version__,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "analysis_call": 'analyze_catchment(extent, phase_scheme="two_phase", quality_policy="flag")',
        "study_window": [START, END],
        "inputs": {
            "boundaries": {k: sha256_file(p["boundaries"] / f"{k}_boundary.geojson") for k in CATCHMENTS},
            "fitzroy_dwer_shp_sha256": sha256_file(p["dwer"]),
            "hydrobasins_zip_sha256": sha256_file(hb_dir / "hybas_au_lev01-12_v1c.zip"),
            "hydrobasins_shp_sha256": {lv: sha256_file(hb_dir / f"hybas_au_lev{lv:02d}_v1c.shp") for lv in LEVELS},
            "cubes": cubes,
        },
        "units": json.loads((out / "units_meta.json").read_text(encoding="utf-8")),
        "units_csv_sha256": sha256_file(out / "units.csv"),
        "series_sha256": {f.name: sha256_file(f) for f in sorted((out / "series").glob("*.csv.gz"))},
        "validation": json.loads((out / "validation.json").read_text(encoding="utf-8")),
        "receipt_written_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def stage_analyze(data: Path, out: Path, workers: int, keys: list[str]) -> None:
    receipt_path = out / "receipt_written.flag"
    if not receipt_path.exists():
        receipt = write_receipt(data, out)
        receipt_path.write_text(receipt["receipt_written_utc"], encoding="utf-8")
        log(out, f"analyze: receipt written, plan sha256 {receipt['plan_sha256_lf']}")
    validation = json.loads((out / "validation.json").read_text(encoding="utf-8"))
    # Only catchments that have been aggregated and passed V1 are analysed;
    # catchments aggregated later are analysed by rerunning this stage.
    ready = [k for k in keys if k in validation and validation[k]["pass"]]
    excluded = sorted(k for k in keys if k in validation and not validation[k]["pass"])
    pending = sorted(k for k in keys if k not in validation)
    log(out, f"analyze: ready {ready}; excluded after V1 {excluded}; not yet validated {pending}")
    series = load_series(out)
    units = pd.read_csv(out / "units.csv")
    units = units[units["key"].isin(ready)]
    results_path = out / "outcomes.jsonl"
    done = set()
    if results_path.exists():
        done = {json.loads(line)["unit_id"] for line in results_path.read_text(encoding="utf-8").splitlines() if line}
    todo = units[~units["unit_id"].isin(done)].sort_values("area_km2", ascending=False)
    grouped = {uid: g.drop(columns="unit_id").to_dict(orient="list") for uid, g in series.groupby("unit_id")}
    log(out, f"analyze: {len(todo)} units to run, {len(done)} already done, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool, open(results_path, "a", encoding="utf-8") as sink:
        futures = {pool.submit(_analyze_unit, (uid, grouped[uid])): uid for uid in todo["unit_id"]}
        for n, future in enumerate(as_completed(futures), start=1):
            sink.write(json.dumps(future.result()) + "\n")
            sink.flush()
            if n % 25 == 0 or n == len(futures):
                log(out, f"analyze: {n}/{len(futures)} units, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- evaluate


def _bin(values, edges):
    return pd.cut(values, edges, right=False, labels=[f"[{a},{b})" for a, b in zip(edges[:-1], edges[1:])])


def outcome_table(out: Path) -> pd.DataFrame:
    units = pd.read_csv(out / "units.csv")
    rows = [json.loads(line) for line in (out / "outcomes.jsonl").read_text(encoding="utf-8").splitlines() if line]
    outcomes = pd.DataFrame(rows).drop_duplicates("unit_id", keep="last")
    table = units.merge(outcomes, on="unit_id", how="inner")
    table = table[table["route"] != "no_pixels"].copy()
    table["type"] = np.where(table["scheme"].str.startswith("hb"), "subbasin",
                             np.where(table["scheme"].str.startswith("tile"), "tile", "catchment"))
    table["routed_seasonal"] = (table["route"] == "per_year_detection").astype(float)
    n = table["n_hydro_years"].where(table["n_hydro_years"] > 0)
    table["confirmed_share"] = table["n_confirmed"] / n
    table["trough_point_share"] = table["n_trough_point"] / n
    table["baseline_eligible_share"] = table["n_baseline_eligible"] / n
    table["area_bin"] = _bin(table["area_km2"], AREA_BINS).astype(str)
    table["water_bin"] = _bin(table["median_n_water"], WATER_BINS).astype(str)
    return table


def _mh_difference(frame: pd.DataFrame, outcome: str) -> tuple[float | None, dict[str, float]]:
    """Mantel-Haenszel weighted difference, subbasin minus tile, over catchment x area-bin strata."""
    pooled_num = pooled_den = 0.0
    per_key: dict[str, list[float]] = {}
    for (key, _), stratum in frame.groupby(["key", "area_bin"], observed=True):
        s = stratum.loc[stratum["type"] == "subbasin", outcome].dropna()
        t = stratum.loc[stratum["type"] == "tile", outcome].dropna()
        if s.empty or t.empty:
            continue
        w = len(s) * len(t) / (len(s) + len(t))
        diff = float(s.mean() - t.mean())
        pooled_num += w * diff
        pooled_den += w
        num, den = per_key.get(key, [0.0, 0.0])
        per_key[key] = [num + w * diff, den + w]
    pooled = pooled_num / pooled_den if pooled_den else None
    return pooled, {k: v[0] / v[1] for k, v in per_key.items()}


def _bootstrap(frame: pd.DataFrame, outcome: str, rng: np.random.Generator) -> list[float]:
    groups = [g for _, g in frame.groupby("key")]
    values = []
    for _ in range(N_BOOT):
        sample = pd.concat([g.iloc[rng.integers(0, len(g), len(g))] for g in groups], ignore_index=True)
        pooled, _ = _mh_difference(sample, outcome)
        if pooled is not None:
            values.append(pooled)
    return values


def _c1(table: pd.DataFrame) -> dict:
    sub = table[table["type"].isin(["subbasin", "tile"])]
    seasonal = sub[sub["routed_seasonal"] == 1]
    rng = np.random.default_rng(0)
    outcomes = {}
    for name, frame in (
        ("routed_seasonal", sub),
        ("confirmed_share", seasonal),
        ("trough_point_share", seasonal),
        ("baseline_eligible_share", seasonal),
    ):
        pooled, per_key = _mh_difference(frame, name)
        draws = _bootstrap(frame, name, rng)
        lo, hi = (float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))) if draws else (None, None)
        outcomes[name] = {
            "difference": pooled, "ci95": [lo, hi], "per_catchment": per_key,
            "n_positive_catchments": sum(v > 0 for v in per_key.values()),
            "n_negative_catchments": sum(v < 0 for v in per_key.values()),
            "n_catchments": len(per_key), "n_draws": len(draws),
        }
    primary = [outcomes["routed_seasonal"], outcomes["confirmed_share"]]

    def supported(o, sign):
        if o["difference"] is None or o["ci95"][0] is None:
            return False
        if sign > 0:
            return o["difference"] >= MARGIN and o["ci95"][0] > 0 and o["n_positive_catchments"] >= 3
        return o["difference"] <= -MARGIN and o["ci95"][1] < 0 and o["n_negative_catchments"] >= 3

    if any(supported(o, +1) for o in primary):
        decision = "supported"
    elif any(supported(o, -1) for o in primary):
        decision = "reversed"
    elif all(o["ci95"][0] is not None and o["ci95"][0] > -MARGIN and o["ci95"][1] < MARGIN for o in primary):
        decision = "equivalent"
    else:
        decision = "inconclusive"
    return {"decision": decision, "outcomes": outcomes}


def _size_rule(frame: pd.DataFrame, bin_column: str, edges: list[float]) -> dict:
    labels = [f"[{a},{b})" for a, b in zip(edges[:-1], edges[1:])]
    shares = {}
    for label in labels:
        units = frame[frame[bin_column] == label]
        shares[label] = {"n": int(len(units)),
                         "seasonal_share": float(units["routed_seasonal"].mean()) if len(units) else None}
    minimum = None
    for i, label in enumerate(labels):
        rest = [shares[lb] for lb in labels[i:] if shares[lb]["n"] >= SIZE_MIN_UNITS]
        if shares[label]["n"] >= SIZE_MIN_UNITS and rest and all(r["seasonal_share"] >= SIZE_SHARE for r in rest):
            minimum = edges[i]
            break
    return {"bins": shares, "minimum_lower_edge": minimum}


def stage_evaluate(out: Path) -> dict:
    table = outcome_table(out)
    table.to_csv(out / "outcomes_table.csv", index=False, lineterminator="\n")
    catch = table[table["type"] == "catchment"].set_index("key")
    seasonal_keys = sorted(catch.index[catch["routed_seasonal"] == 1])
    aseasonal_keys = sorted(catch.index[catch["routed_seasonal"] != 1])

    fixture = pd.read_csv(CASE_SUMMARY).set_index("key")
    v2 = {}
    for key, row in catch.iterrows():
        ref = fixture.loc[key]
        v2[key] = {
            "route": [row["route"], ref["route"]],
            "regime": [row["regime"], ref["regime"]],
            "n_hydro_years": [int(row["n_hydro_years"]), int(ref["n_hydro_years"])],
            "peak_month": [row["peak_month"], None if pd.isna(ref["water_extent_peak_month"]) else float(ref["water_extent_peak_month"])],
            "trough_month": [row["trough_month"], None if pd.isna(ref["climatological_trough_month"]) else float(ref["climatological_trough_month"])],
        }

    c1 = _c1(table)
    c2 = {}
    in_seasonal = table[table["key"].isin(seasonal_keys)]
    for unit_type in ("subbasin", "tile"):
        frame = in_seasonal[in_seasonal["type"] == unit_type]
        c2[unit_type] = {
            "by_water_pixels": _size_rule(frame, "water_bin", WATER_BINS),
            "by_area_km2": _size_rule(frame, "area_bin", AREA_BINS),
        }

    def async_share(column):
        rows = []
        for key in seasonal_keys:
            ref = catch.loc[key, column]
            if ref is None or pd.isna(ref):
                continue
            units = table[(table["key"] == key) & (table["scheme"] == "hb7") & (table["routed_seasonal"] == 1)]
            rows.extend(circular_month_distance(v, ref) > 1 for v in units[column].dropna())
        return {"n": len(rows), "share_more_than_1_month": float(np.mean(rows)) if rows else None}

    c3 = {"trough": async_share("trough_month"), "peak": async_share("peak_month")}
    c3["material"] = any((c3[k]["share_more_than_1_month"] or 0) >= ASYNC_SHARE for k in ("trough", "peak"))
    c3["catchment_vs_hb7_trough_point_share"] = {
        key: {
            "catchment": None if pd.isna(catch.loc[key, "trough_point_share"]) else float(catch.loc[key, "trough_point_share"]),
            "hb7_seasonal_median": float(table[(table["key"] == key) & (table["scheme"] == "hb7") & (table["routed_seasonal"] == 1)]["trough_point_share"].median())
            if ((table["key"] == key) & (table["scheme"] == "hb7") & (table["routed_seasonal"] == 1)).any() else None,
        }
        for key in seasonal_keys
    }
    hb7_aseasonal = table[table["key"].isin(aseasonal_keys) & (table["scheme"] == "hb7")]
    c4 = {
        "n": int(len(hb7_aseasonal)),
        "share_routed_seasonal": float(hb7_aseasonal["routed_seasonal"].mean()) if len(hb7_aseasonal) else None,
        "per_catchment": hb7_aseasonal.groupby("key")["routed_seasonal"].agg(["size", "mean"]).to_dict(orient="index"),
    }
    c4["material"] = (c4["share_routed_seasonal"] or 0) >= ASYNC_SHARE

    errors = table[table["route"] == "error"]
    all_rows = [json.loads(line) for line in (out / "outcomes.jsonl").read_text(encoding="utf-8").splitlines() if line]
    no_pixels = sorted({r["unit_id"] for r in all_rows if r.get("route") == "no_pixels"})
    results = {
        "receipt_sha256_lf": sha256_text_lf(RECEIPT) if RECEIPT.exists() else None,
        "series_sha256_at_evaluate": {f.name: sha256_file(f) for f in sorted((out / "series").glob("*.csv.gz"))},
        "validation_at_evaluate": json.loads((out / "validation.json").read_text(encoding="utf-8")),
        "excluded_no_pixels": no_pixels,
        "n_units": int(len(table)),
        "units_by_scheme": table.groupby("scheme").size().to_dict(),
        "error_share": float(len(errors) / len(table)) if len(table) else None,
        "errors": errors[["unit_id", "error"]].to_dict(orient="records")[:50],
        "seasonal_catchments": seasonal_keys,
        "aseasonal_catchments": aseasonal_keys,
        "v2_catchment_vs_case_study": v2,
        "c1_unit_type": c1,
        "c2_size": c2,
        "c3_asynchrony": c3,
        "c4_hidden_seasonality": c4,
        "routed_seasonal_by_scheme": table.groupby(["key", "scheme"])["routed_seasonal"].mean().unstack().round(3).to_dict(orient="index"),
    }
    RESULTS.write_text(json.dumps(clean_json(results), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    log(out, f"evaluate: C1 {c1['decision']}; wrote {RESULTS.name}")
    return results


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["units", "aggregate", "validate", "analyze", "evaluate"])
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--keys", nargs="*", default=list(CATCHMENTS))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage == "units":
        stage_units(args.data, args.out)
    elif args.stage == "aggregate":
        stage_aggregate(args.data, args.out, args.keys, args.threads)
    elif args.stage == "validate":
        stage_validate(args.out)
    elif args.stage == "analyze":
        stage_analyze(args.data, args.out, args.workers, args.keys)
    else:
        stage_evaluate(args.out)


if __name__ == "__main__":
    main()
