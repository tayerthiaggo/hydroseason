"""G1: block split-half calibration of HydroSeason's identifiability gates.

Plan and decision rules: docs/handoff/2026-11-02-g1-gate-calibration-plan.md.

Stages, in order:

    series   build per-window count series (units x halves) for every role
    freeze   write the receipt (plan, script, inputs) before any outcome
    phase-a  run the calibration halves once with the gates open
    choose   reproducibility curves, target and choice; appended to the receipt
    phase-b  exact runs on 40 calibration windows with the chosen gates
    confirm  exact runs on the confirmation windows with current and chosen gates

The library is not modified. Worker processes set the gate values on the
frozen defaults object in-process (and, for the swing alternative, wrap
annual_detectability), and every run records the gate values it used.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
HANDOFF = REPO_ROOT / "docs" / "handoff"
PLAN = HANDOFF / "2026-11-02-g1-gate-calibration-plan.md"
RECEIPT = HANDOFF / "2026-11-02-g1-gate-calibration-receipt.json"
RESULTS = HANDOFF / "2026-11-02-g1-gate-calibration-results.json"

DATA = Path(r"D:\RLH\5.6\data_local")
WINDOWS = DATA / "raw" / "WaterMask-TSFill"
SITES = Path(r"D:\RLH\5.6\repos\WaterMask-TSFill\experiments\gapfill")
OUT = DATA / "intermediate" / "hydroseason_gate_calibration"

DRAWS = {
    "train": ("national_train_sites.json", "national_train_windows", "calibration"),
    "A": ("national_sites.json", "national_windows", "calibration"),
    "B": ("national_sites_b.json", "national_b_windows", "confirmation"),
    "C": ("national_sites_c.json", "national_c_windows", "confirmation"),
    "D": ("national_sites_d.json", "national_d_windows", "confirmation"),
    "E": ("national_sites_e.json", "national_e_windows", "confirmation"),
}
GROUPS = {
    "North": {"Carpentaria Coast", "Tanami-Timor Sea Coast", "North Western Plateau", "North East Coast"},
    "Arid interior": {"Lake Eyre Basin", "Pilbara-Gascoyne", "South Western Plateau"},
    "South-east": {"Murray-Darling Basin", "South East Coast (NSW)", "South East Coast (Victoria)", "Tasmania"},
    "South and west": {"South Australian Gulf", "South West Coast"},
}
START, END = "1988-01-01", "2025-12-01"
HALO, CORE, BLOCK = 10, 512, 67
UNITS = {"core": (0, 512, 0, 512), "q00": (0, 256, 0, 256), "q01": (0, 256, 256, 512),
         "q10": (256, 512, 0, 256), "q11": (256, 512, 256, 512)}
CURRENT = (3.0, 5, 0)
OPEN = (0.0, 0, 0)
GRID_RATIO = [1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 15, 20]
GRID_PEAK = [1, 2, 3, 5, 10, 20, 50, 100, 200]
GRID_SWING = [0, 5, 10, 20, 50, 100, 200]
MATCH_MONTHS, AGREE_MONTHS = 6, 1
DATED = {"point", "interval", "broad"}
N_BOOT, CHECK_WINDOWS = 2000, 40


# ---------------------------------------------------------------- helpers


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "g1.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def month_index(value) -> int | None:
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    return None if pd.isna(stamp) else stamp.year * 12 + stamp.month - 1


def group_of(division: str) -> str:
    return next((name for name, members in GROUPS.items() if division in members), "other")


def load_receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def save_receipt(receipt: dict) -> None:
    RECEIPT.write_text(json.dumps(clean(receipt), indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- series


def sites_table() -> pd.DataFrame:
    rows = []
    for draw, (sites_file, folder, role) in DRAWS.items():
        content = json.loads((SITES / sites_file).read_text(encoding="utf-8"))
        for site in content["sites"] if isinstance(content, dict) else content:
            path = WINDOWS / folder / f"{site['site_id']}.zarr"
            rows.append({
                "window": site["site_id"], "draw": draw, "role": role,
                "division": site["drainage_division"], "water_type": site["water_type"],
                "group": group_of(site["drainage_division"]), "path": str(path), "exists": path.exists(),
            })
    return pd.DataFrame(rows)


def window_series(path: str) -> pd.DataFrame:
    import xarray as xr
    import zarr

    months = pd.date_range(START, END, freq="MS")
    ds = xr.open_zarr(path)
    times = pd.DatetimeIndex(ds["time"].values).to_period("M").to_timestamp()
    t0, t1 = int(times.get_loc(months[0])), int(times.get_loc(months[-1])) + 1
    if not times[t0:t1].equals(months):
        raise ValueError(f"{path}: incomplete study months")
    group = zarr.open_group(path, mode="r")
    core = slice(HALO, HALO + CORE)
    rows_idx, cols_idx = np.meshgrid(np.arange(CORE), np.arange(CORE), indexing="ij")
    half_b = ((rows_idx // BLOCK + cols_idx // BLOCK) % 2).astype(bool)
    masks = {}
    for unit, (r0, r1, c0, c1) in UNITS.items():
        inside = np.zeros((CORE, CORE), bool)
        inside[r0:r1, c0:c1] = True
        masks[(unit, "A")] = (inside & ~half_b).ravel()
        masks[(unit, "B")] = (inside & half_b).ravel()
    totals = {key: [np.zeros(len(months), np.int64), np.zeros(len(months), np.int64)] for key in masks}
    for start in range(t0, t1, 24):
        stop = min(start + 24, t1)
        cw = group["n_clear_water"][start:stop, core, core].reshape(stop - start, -1)
        cd = group["n_clear_dry"][start:stop, core, core].reshape(stop - start, -1)
        water, valid = cw > cd, (cw > 0) | (cd > 0)
        for key, mask in masks.items():
            totals[key][0][start - t0:stop - t0] = water[:, mask].sum(axis=1)
            totals[key][1][start - t0:stop - t0] = valid[:, mask].sum(axis=1)
    frames = []
    for (unit, half), (n_water, n_valid) in totals.items():
        frames.append(pd.DataFrame({"unit": unit, "half": half, "date": months.strftime("%Y-%m-%d"),
                                    "n_water": n_water, "n_valid": n_valid, "n_aoi": int(masks[(unit, half)].sum())}))
    return pd.concat(frames, ignore_index=True)


def stage_series(workers: int) -> None:
    sites = sites_table()
    (OUT / "series").mkdir(parents=True, exist_ok=True)
    sites.to_csv(OUT / "sites.csv", index=False, lineterminator="\n")
    missing = sites[~sites["exists"]]
    if len(missing):
        log(f"series: {len(missing)} windows have no cube: {missing['window'].tolist()[:10]}")
    todo = [r for r in sites[sites["exists"]].itertuples() if not (OUT / "series" / f"{r.window}.csv.gz").exists()]
    log(f"series: {len(todo)} windows to build")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(window_series, r.path): r.window for r in todo}
        for n, future in enumerate(as_completed(futures), start=1):
            window = futures[future]
            future.result().to_csv(OUT / "series" / f"{window}.csv.gz", index=False, lineterminator="\n")
            if n % 25 == 0 or n == len(futures):
                log(f"series: {n}/{len(futures)}")


# ---------------------------------------------------------------- freeze


def stage_freeze() -> None:
    if RECEIPT.exists():
        raise SystemExit("receipt exists; the freeze is written once")
    import hydroseason
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as defaults

    sites = pd.read_csv(OUT / "sites.csv")
    receipt = {
        "plan": str(PLAN.relative_to(REPO_ROOT)).replace("\\", "/"),
        "plan_sha256_lf": sha256_lf(PLAN),
        "script_sha256_lf": sha256_lf(Path(__file__)),
        "git_head": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "git_status_short": git("status", "--short").splitlines(),
        "hydroseason_version": hydroseason.__version__,
        "library_gates": {"ratio": defaults.min_amplitude_to_floor_ratio, "peak_pixels": defaults.min_peak_water_pixels},
        "site_files_sha256": {f: sha256_file(SITES / f) for f, _, _ in DRAWS.values()},
        "windows_by_role": sites.groupby("role")["window"].apply(list).to_dict(),
        "windows_without_cube": sites.loc[~sites["exists"], "window"].tolist(),
        "series_sha256": {p.name: sha256_file(p) for p in sorted((OUT / "series").glob("*.csv.gz"))},
        "frozen_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    save_receipt(receipt)
    log(f"freeze: plan {receipt['plan_sha256_lf']}, script {receipt['script_sha256_lf']}")


# ---------------------------------------------------------------- runs


_SWING = 0


def _set_gates(ratio: float, pixels: int, swing: int) -> None:
    global _SWING
    _SWING = int(swing)
    import hydroseason._seasonality_test as seasonality
    import hydroseason._timing_identifiability as timing
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as defaults

    object.__setattr__(defaults, "min_amplitude_to_floor_ratio", float(ratio))
    object.__setattr__(defaults, "min_peak_water_pixels", int(pixels))
    if swing > 0:
        original = timing.annual_detectability

        def with_swing(values, rows, **kwargs):
            result = original(values, rows, **kwargs)
            if not result.detectable or "n_water" not in rows:
                return result
            trough_rows = rows.loc[values.index[values == values.min()]]
            trough_water = pd.to_numeric(trough_rows["n_water"], errors="coerce").min()
            if result.peak_n_water is None or not np.isfinite(trough_water):
                return result
            if result.peak_n_water - trough_water < swing:
                return dataclasses.replace(result, detectable=False)
            return result

        timing.annual_detectability = with_swing
        seasonality.annual_detectability = with_swing


def _run(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as defaults

    key, rows = payload
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]
    started = time.perf_counter()
    record = {"key": key, "gates": [defaults.min_amplitude_to_floor_ratio, defaults.min_peak_water_pixels, _SWING]}
    try:
        analysis = analyze_catchment(frame[["n_water", "n_valid", "n_invalid", "n_aoi"]],
                                     phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    water = frame["n_water"]
    cycles = []
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    for _, row in hy.iterrows():
        start, end = row.get("hy_start"), row.get("hy_end")
        window = water.loc[start:end] if pd.notna(start) and pd.notna(end) else water.iloc[0:0]
        peak_px = row.get("peak_n_water")
        trough_min = float(window.min()) if len(window) else np.nan
        cycles.append({
            "peak": month_index(row.get("peak_month")), "trough": month_index(row.get("trough_month")),
            "trough_status": row.get("trough_timing_status"), "peak_status": row.get("peak_timing_status"),
            "ratio": row.get("amplitude_to_floor_ratio"), "floor": row.get("detectability_floor_pp"),
            "peak_px": peak_px,
            "swing": (float(peak_px) - trough_min) if pd.notna(peak_px) and np.isfinite(trough_min) else None,
        })
    record.update(route=analysis.route, error=None, cycles=cycles,
                  fingerprint=analysis.method_policy_fingerprint,
                  seconds=round(time.perf_counter() - started, 2))
    return record


def run_halves(windows: list[str], gates: tuple, sink: Path, workers: int, halves=("A", "B")) -> None:
    done = set()
    if sink.exists():
        done = {json.loads(line)["key"] for line in sink.read_text(encoding="utf-8").splitlines() if line}
    payloads = []
    for window in windows:
        series = pd.read_csv(OUT / "series" / f"{window}.csv.gz")
        for (unit, half), g in series.groupby(["unit", "half"]):
            key = f"{window}|{unit}|{half}"
            if half in halves and key not in done:
                payloads.append((key, g[["date", "n_water", "n_valid", "n_aoi"]].to_dict(orient="list")))
    log(f"run {sink.name}: {len(payloads)} series, gates {gates}, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=_set_gates, initargs=gates) as pool, \
            open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(clean(future.result())) + "\n")
            out.flush()
            if n % 100 == 0 or n == len(futures):
                log(f"run {sink.name}: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- scoring


def load_runs(path: Path) -> dict[str, dict]:
    return {r["key"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x)}


def half_cycles(runs: dict[str, dict]) -> pd.DataFrame:
    """One row per half-cycle, with the index of its matched cycle in the other half."""
    by_unit: dict[tuple[str, str], dict[str, list]] = {}
    for key, run in runs.items():
        window, unit, half = key.split("|")
        by_unit.setdefault((window, unit), {})[half] = run["cycles"]
    rows = []
    for (window, unit), halves in by_unit.items():
        a, b = halves.get("A", []), halves.get("B", [])
        candidates = sorted(
            (abs(x["peak"] - y["peak"]), i, j)
            for i, x in enumerate(a) for j, y in enumerate(b)
            if x["peak"] is not None and y["peak"] is not None and abs(x["peak"] - y["peak"]) <= MATCH_MONTHS
        )
        match_a, match_b = {}, {}
        for _, i, j in candidates:
            if i not in match_a and j not in match_b:
                match_a[i], match_b[j] = j, i
        for half, cycles, matches, other in (("A", a, match_a, "B"), ("B", b, match_b, "A")):
            for i, c in enumerate(cycles):
                rows.append({"window": window, "unit": unit, "half": half, "i": i,
                             "match": matches.get(i), "other": other, **c})
    frame = pd.DataFrame(rows)
    for column in ("ratio", "peak_px", "swing"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["dated"] = frame["trough_status"].isin(DATED)
    return frame


def score(frame: pd.DataFrame, gate: tuple | None) -> pd.DataFrame:
    """Per-window pass and reproduced counts. gate=None uses the run's own statuses."""
    if gate is None:
        passes = frame["dated"].to_numpy()
    else:
        r, p, s = gate
        passes = (frame["dated"] & (frame["ratio"].fillna(-1) >= r)
                  & (frame["peak_px"].fillna(-1) >= p) & (frame["swing"].fillna(-1) >= s)).to_numpy()
    lookup = {(w, u, h, i): (ok, t) for w, u, h, i, ok, t in
              zip(frame["window"], frame["unit"], frame["half"], frame["i"], passes, frame["trough"])}
    reproduced = np.zeros(len(frame), bool)
    for n, (w, u, o, m, ok, t) in enumerate(zip(frame["window"], frame["unit"], frame["other"],
                                                frame["match"], passes, frame["trough"])):
        if not ok or m is None or (isinstance(m, float) and math.isnan(m)) or t is None or pd.isna(t):
            continue
        other_ok, other_t = lookup.get((w, u, o, int(m)), (False, None))
        if other_ok and other_t is not None and not pd.isna(other_t) and abs(t - other_t) <= AGREE_MONTHS:
            reproduced[n] = True
    return pd.DataFrame({"window": frame["window"], "passes": passes, "reproduced": reproduced}) \
        .groupby("window", as_index=False).sum()


def rate(per_window: pd.DataFrame, weights: pd.Series | None = None) -> tuple[float | None, float]:
    w = 1.0 if weights is None else per_window["window"].map(weights).fillna(0.0)
    passes = float((per_window["passes"] * w).sum())
    return ((float((per_window["reproduced"] * w).sum()) / passes) if passes else None), passes


def boot_weights(windows: list[str], rng) -> list[pd.Series]:
    windows = np.array(sorted(windows))
    return [pd.Series(rng.choice(windows, size=len(windows), replace=True)).value_counts().astype(float)
            for _ in range(N_BOOT)]


def ci(values) -> list:
    values = [v for v in values if v is not None]
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))] if values else [None, None]


# ---------------------------------------------------------------- choose


def stage_choose() -> None:
    receipt = load_receipt()
    if "choice" in receipt:
        raise SystemExit("choice already written")
    frame = half_cycles(load_runs(OUT / "phase_a.jsonl"))
    dated = frame[frame["dated"]]
    q_ratio, q_peak = float(dated["ratio"].quantile(0.75)), float(dated["peak_px"].quantile(0.75))
    ceiling, _ = rate(score(frame, (q_ratio, q_peak, 0)))
    target = 0.95 * ceiling
    grid = [(r, p, 0, "shape1") for r in GRID_RATIO for p in GRID_PEAK]
    grid += [(r, 0, s, "shape2") for r in GRID_RATIO for s in GRID_SWING]
    curves = []
    for r, p, s, shape in grid:
        value, passes = rate(score(frame, (r, p, s)))
        curves.append({"ratio": r, "peak_px": p, "swing": s, "shape": shape, "reproducibility": value, "passes": passes})
    curves = pd.DataFrame(curves)
    curves.to_csv(OUT / "curves.csv", index=False, lineterminator="\n")
    ok = curves[curves["reproducibility"].fillna(-1) >= target]
    best = {}
    for shape in ("shape1", "shape2"):
        candidates = ok[ok["shape"] == shape].sort_values(["passes", "ratio", "peak_px", "swing"], ascending=False)
        best[shape] = candidates.iloc[0].to_dict() if len(candidates) else None
    choice = best["shape1"]
    if best["shape2"] is not None and (choice is None or best["shape2"]["passes"] >= 1.05 * choice["passes"]):
        choice = best["shape2"]
    current_value, current_passes = rate(score(frame, CURRENT))
    receipt["choice"] = {
        "top_quartile_gate": {"ratio": q_ratio, "peak_px": q_peak}, "ceiling": ceiling, "target": target,
        "best": best, "chosen": choice,
        "current": {"reproducibility": current_value, "passes": current_passes},
        "curves_sha256": sha256_file(OUT / "curves.csv"),
        "n_half_cycles": int(len(frame)), "n_dated": int(len(dated)),
        "written_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    save_receipt(receipt)
    log(f"choose: target {target:.3f}, chosen {choice}")


def chosen_gates(receipt: dict) -> tuple | None:
    chosen = receipt["choice"]["chosen"]
    if chosen is None:
        return None
    return (float(chosen["ratio"]), int(chosen["peak_px"]), int(chosen["swing"]))


# ---------------------------------------------------------------- phase B and confirmation


def stage_phase_b(workers: int) -> None:
    receipt = load_receipt()
    gates = chosen_gates(receipt)
    if gates is None:
        raise SystemExit("no gates were chosen; nothing to check")
    sites = pd.read_csv(OUT / "sites.csv")
    calib = sites[(sites["role"] == "calibration") & sites["exists"]]
    rng = np.random.default_rng(0)
    shares = calib["water_type"].value_counts(normalize=True)
    quota = (shares * CHECK_WINDOWS).round().astype(int)
    while quota.sum() > CHECK_WINDOWS:
        quota[quota.idxmax()] -= 1
    while quota.sum() < CHECK_WINDOWS:
        quota[quota.idxmin()] += 1
    picked = []
    for water_type, n in quota.items():
        pool = sorted(calib.loc[calib["water_type"] == water_type, "window"])
        picked += list(rng.choice(pool, size=min(n, len(pool)), replace=False))
    run_halves(picked, gates, OUT / "phase_b.jsonl", workers)
    exact, _ = rate(score(half_cycles(load_runs(OUT / "phase_b.jsonl")), None))
    phase_a = half_cycles(load_runs(OUT / "phase_a.jsonl"))
    post_hoc, _ = rate(score(phase_a[phase_a["window"].isin(picked)], gates))
    receipt["phase_b"] = {"windows": picked, "exact": exact, "post_hoc": post_hoc,
                          "holds": bool(exact is not None and post_hoc is not None and abs(exact - post_hoc) <= 0.03),
                          "written_utc": pd.Timestamp.now(tz="UTC").isoformat()}
    save_receipt(receipt)
    log(f"phase-b: exact {exact}, post hoc {post_hoc}")


def routes_agree(runs: dict[str, dict]) -> pd.DataFrame:
    by_unit: dict[tuple[str, str], dict[str, str]] = {}
    for key, run in runs.items():
        window, unit, half = key.split("|")
        by_unit.setdefault((window, unit), {})[half] = run["route"]
    rows = [{"window": w, "agree": float(h.get("A") == h.get("B"))} for (w, _), h in by_unit.items() if len(h) == 2]
    return pd.DataFrame(rows).groupby("window", as_index=False).agg(agree=("agree", "sum"), units=("agree", "size"))


def stage_confirm(workers: int) -> None:
    receipt = load_receipt()
    gates = chosen_gates(receipt)
    if gates is None or not receipt.get("phase_b", {}).get("holds", False):
        raise SystemExit("no confirmable choice: see the receipt")
    sites = pd.read_csv(OUT / "sites.csv")
    conf = sites[(sites["role"] == "confirmation") & sites["exists"]]
    windows = sorted(conf["window"])
    run_halves(windows, CURRENT, OUT / "confirm_current.jsonl", workers)
    run_halves(windows, gates, OUT / "confirm_chosen.jsonl", workers)
    current_runs, chosen_runs = load_runs(OUT / "confirm_current.jsonl"), load_runs(OUT / "confirm_chosen.jsonl")
    current, chosen = score(half_cycles(current_runs), None), score(half_cycles(chosen_runs), None)
    target = receipt["choice"]["target"]
    draws = boot_weights(windows, np.random.default_rng(0))

    r_cur, n_cur = rate(current)
    r_new, n_new = rate(chosen)
    gain = [None if rate(chosen, w)[0] is None or rate(current, w)[0] is None
            else rate(chosen, w)[0] - rate(current, w)[0] for w in draws]
    growth = [rate(chosen, w)[1] / rate(current, w)[1] - 1 if rate(current, w)[1] else None for w in draws]
    tightening = r_new - r_cur >= 0.05 and ci(gain)[0] is not None and ci(gain)[0] > 0
    loosening = (n_new / n_cur - 1 >= 0.10 and ci(growth)[0] is not None and ci(growth)[0] > 0
                 and r_cur - r_new <= 0.02)

    hc = half_cycles(chosen_runs).merge(conf[["window", "water_type", "group"]], on="window")
    strata = {}
    for column in ("water_type", "group"):
        for name, sub in hc.groupby(column):
            value, passes = rate(score(sub, None))
            strata[f"{column}:{name}"] = {"reproducibility": value, "passes": passes,
                                          "fails": bool(passes >= 30 and value is not None and value < target - 0.10)}
    route_cur, route_new = routes_agree(current_runs), routes_agree(chosen_runs)
    agree_cur = route_cur["agree"].sum() / route_cur["units"].sum()
    agree_new = route_new["agree"].sum() / route_new["units"].sum()

    checks = {
        "1_reproducibility_at_target": bool(r_new is not None and r_new >= target - 0.03),
        "2_gain_over_current": bool(tightening or loosening),
        "3_no_stratum_fails": not any(s["fails"] for s in strata.values()),
        "4_route_agreement": bool(agree_new >= agree_cur - 0.02),
    }
    results = {
        "receipt_sha256_lf": sha256_lf(RECEIPT), "gates_current": CURRENT, "gates_chosen": gates,
        "target": target,
        "current": {"reproducibility": r_cur, "passes": n_cur, "route_agreement": agree_cur},
        "chosen": {"reproducibility": r_new, "passes": n_new, "route_agreement": agree_new},
        "gain_ci95": ci(gain), "pass_growth_ci95": ci(growth),
        "tightening_rule": bool(tightening), "loosening_rule": bool(loosening),
        "strata": strata, "checks": checks, "adopt": all(checks.values()),
        "fingerprints": sorted({r.get("fingerprint") for r in chosen_runs.values()} - {None}),
    }
    RESULTS.write_text(json.dumps(clean(results), indent=2) + "\n", encoding="utf-8")
    log(f"confirm: adopt={results['adopt']} checks={checks}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["series", "freeze", "phase-a", "choose", "phase-b", "confirm"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="phase-a pilot: first N calibration windows only")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "series":
        stage_series(args.workers)
    elif args.stage == "freeze":
        stage_freeze()
    elif args.stage == "phase-a":
        if not RECEIPT.exists():
            raise SystemExit("freeze first")
        sites = pd.read_csv(OUT / "sites.csv")
        calib = sorted(sites.loc[(sites["role"] == "calibration") & sites["exists"], "window"])
        run_halves(calib[: args.limit] if args.limit else calib, OPEN, OUT / "phase_a.jsonl", args.workers)
    elif args.stage == "choose":
        stage_choose()
    elif args.stage == "phase-b":
        stage_phase_b(args.workers)
    else:
        stage_confirm(args.workers)


if __name__ == "__main__":
    main()
