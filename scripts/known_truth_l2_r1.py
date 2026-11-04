"""L2 and R1: a two-sided trough label, and the rise against the trough, on known truth.

Plan and decision rules: docs/handoff/2026-11-03-l2-r1-plan.md.

Stages, in order:

    check     G2's noise-free construction records under both settings, plus the rise rule
    pilot     pilot records under both settings; run times and counts only
    freeze    build the main corpus and write the receipt before any outcome
    run       main records under both settings
    evaluate  decision rules for L2 and R1; writes the results JSON

Record generators come unchanged from scripts/known_truth_gates.py (G2), and the trough
scoring helpers unchanged from scripts/known_truth_labels.py (L1). The only change to
HydroSeason is made inside worker processes under the ``two_sided`` setting: the output
of ``detect_dynamic_hydrological_years`` is relabelled by ``two_sided_years`` before
routing and the condition baseline read it. The library on disk is not modified.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_gates as g2  # noqa: E402
import known_truth_labels as l1  # noqa: E402

g1 = g2.g1
REPO_ROOT = g1.REPO_ROOT
HANDOFF = g1.HANDOFF
PLAN = HANDOFF / "2026-11-03-l2-r1-plan.md"
RECEIPT = HANDOFF / "2026-11-03-l2-r1-receipt.json"
RESULTS = HANDOFF / "2026-11-03-l2-r1-results.json"
OUT = g1.DATA / "intermediate" / "hydroseason_known_truth_l2_r1"

SETTINGS = ("current", "two_sided")
SEASONAL_SEEDS = range(240000, 240600)
NULL_SEEDS = range(250000, 250200)
INJECTION_SEEDS = range(260000, 260574)
INJECTIONS_PER_BACKGROUND = 2
PILOT_S_SEEDS = range(270000, 270060)
PILOT_I_SEEDS = range(271000, 271040)
DATED = l1.DATED
MIN_CASES = 100
RISE_FRACTION = 0.2
RISE_REPORTED = (0.1, 0.5)
RISE_OFFSET = {"pulse": 1, "sine": 2}  # rise truth: months after the trough month m
SELFTEST_EXPECTED = {"tie_after": "interval", "clear_after": "point"}

_SETTING = "current"
_SELFTEST: dict = {}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with open(OUT / "l2r1.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# ---------------------------------------------------------------- L2 rule


def two_sided_years(years: pd.DataFrame, prepared: pd.DataFrame, thresholds) -> pd.DataFrame:
    """Widen each dated trough's equivalent set with the months after its boundary (plan, L2)."""
    from hydroseason._dynamic_year import _aggregate_timing_status
    from hydroseason._timing_identifiability import _window_status

    out = years.copy()
    if out.empty or "trough_timing_status" not in out.columns:
        return out
    extent = prepared["extent_pct"].astype(float)
    usable = prepared["candidate_usable"].astype(bool)
    months = prepared.index
    order = list(out.sort_values("hy_year").index)
    for position, i in enumerate(order):
        if out.at[i, "trough_timing_status"] not in DATED:
            continue
        boundary, floor = out.at[i, "trough_month"], out.at[i, "detectability_floor_pp"]
        if pd.isna(boundary) or pd.isna(floor):
            continue
        start, end = out.at[i, "trough_interval_start"], out.at[i, "trough_interval_end"]
        start = boundary if pd.isna(start) else start
        end = boundary if pd.isna(end) else end
        span = (months >= start) & (months <= max(end, boundary)) & usable.to_numpy()
        if not span.any():
            continue
        level = float(extent[span].min())
        later_peaks = [out.at[j, "peak_month"] for j in order[position + 1:] if pd.notna(out.at[j, "peak_month"])]
        stop = later_peaks[0] if later_peaks else months[-1] + pd.DateOffset(months=1)
        last = None
        for month in months[(months > boundary) & (months < stop)]:
            if not usable.loc[month]:
                continue
            if extent.loc[month] <= level + float(floor):
                last = month
                continue
            break
        if last is None:
            continue
        status = _window_status((pd.Timestamp(start), pd.Timestamp(last)), thresholds, allow_broad=True)
        out.at[i, "trough_timing_status"] = status
        out.at[i, "trough_interval_end"] = last
        peak_status = out.at[i, "peak_timing_status"]
        if isinstance(peak_status, str):
            out.at[i, "timing_status"] = _aggregate_timing_status(peak_status, status)
    return out


def selftest() -> dict:
    """The two fixed cases of the plan's wrapper self-test."""
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS

    months = pd.date_range("2000-01-01", periods=14, freq="MS")
    results = {}
    for case, after in (("tie_after", 10.5), ("clear_after", 12.0)):
        values = [5, 20, 50, 40, 30, 20, 10, after, 30, 45, 60, 40, 20, 15]
        prepared = pd.DataFrame({"extent_pct": np.array(values, dtype=float), "candidate_usable": True}, index=months)
        years = pd.DataFrame({
            "hy_year": [2000, 2001], "trough_month": [months[6], months[13]],
            "trough_timing_status": ["point", "unresolved"],
            "trough_interval_start": [months[6], pd.NaT], "trough_interval_end": [months[6], pd.NaT],
            "detectability_floor_pp": [1.0, 1.0], "peak_month": [months[2], months[10]],
            "peak_timing_status": ["point", "point"], "timing_status": ["point", "unresolved"],
        })
        results[case] = two_sided_years(years, prepared, TIMING_IDENTIFIABILITY_DEFAULTS).loc[0, "trough_timing_status"]
    return results


def _install(setting: str) -> None:
    global _SETTING, _SELFTEST
    _SETTING = setting
    import hydroseason.hydrological_state as state
    from hydroseason._state_input import prepare_monthly_extent

    original = state.detect_dynamic_hydrological_years
    if setting == "two_sided":
        def wrapped(extent, *, config, value_col="extent_pct", date_col=None, pattern=None):
            years = original(extent, config=config, value_col=value_col, date_col=date_col, pattern=pattern)
            prepared = prepare_monthly_extent(
                extent, value_col=value_col, date_col=date_col, max_invalid_pct=config.max_invalid_pct,
                allow_unknown_quality=config.allow_unknown_quality, quality_policy=config.quality_policy,
            )
            return two_sided_years(years, prepared, config.timing_identifiability_thresholds)

        state.detect_dynamic_hydrological_years = wrapped
    _SELFTEST = {**selftest(), "wrapped": state.detect_dynamic_hydrological_years is not original}


def _run(payload):
    import warnings

    warnings.simplefilter("ignore")
    from hydroseason import analyze_catchment

    key, rows = payload
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]
    started = time.perf_counter()
    record = {"key": key, "setting": _SETTING, "selftest": _SELFTEST}
    try:
        analysis = analyze_catchment(frame[["n_water", "n_valid", "n_invalid", "n_aoi"]],
                                     phase_scheme="two_phase", quality_policy="flag")
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        record.update(route="error", error=f"{type(exc).__name__}: {exc}"[:400], cycles=[])
        return record
    hy = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    cycles = []
    for _, row in hy.sort_values("hy_year").iterrows() if len(hy) else []:
        cycles.append({
            "hy_year": row.get("hy_year"),
            "trough": l1._month(row, "trough_month"),
            "status": row.get("trough_timing_status"),
            "start": l1._month(row, "trough_interval_start"),
            "end": l1._month(row, "trough_interval_end"),
            "pass1_status": row.get("pass1_trough_timing_status"),
            "refinement": row.get("trough_refinement_status"),
            "ratio": row.get("amplitude_to_floor_ratio"),
            "peak_px": row.get("peak_n_water"),
            "cycle_status": row.get("status"),
            "boundary_status": row.get("boundary_status"),
            "peak_quality": row.get("peak_quality"),
            "timing_status": row.get("timing_status"),
            "peak": l1._month(row, "peak_month"),
            "peak_status": row.get("peak_timing_status"),
            "baseline_eligible": row.get("baseline_eligible"),
        })
    record.update(route=analysis.route, error=None, cycles=cycles,
                  fingerprint=analysis.method_policy_fingerprint,
                  seconds=round(time.perf_counter() - started, 2))
    return record


def run_records(records: list[dict], setting: str, sink: Path, workers: int) -> None:
    done = set()
    if sink.exists():
        done = {json.loads(line)["key"] for line in sink.read_text(encoding="utf-8").splitlines() if line}
    payloads = [(r["key"], r["rows"]) for r in records if r["key"] not in done]
    log(f"run {sink.name}: {len(payloads)} records, setting {setting}, {workers} workers")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=_install, initargs=(setting,)) as pool, \
            open(sink, "a", encoding="utf-8") as out:
        futures = [pool.submit(_run, p) for p in payloads]
        for n, future in enumerate(as_completed(futures), start=1):
            out.write(json.dumps(g1.clean(future.result())) + "\n")
            out.flush()
            if n % 100 == 0 or n == len(futures):
                log(f"run {sink.name}: {n}/{len(futures)}, {time.perf_counter() - started:.0f}s")


# ---------------------------------------------------------------- R1 rule


def record_series(record: dict) -> tuple[dict, dict]:
    """Monthly extent (percent of valid pixels) and usability, as the library reads count input."""
    rows = record["rows"]
    extent, usable = {}, {}
    for date, water, valid in zip(rows["date"], rows["n_water"], rows["n_valid"]):
        index = g1.month_index(date)
        usable[index] = valid > 0
        extent[index] = 100.0 * water / valid if valid > 0 else np.nan
    return extent, usable


def rise_month(cycles: list[dict], j: int, extent: dict, usable: dict, fraction: float) -> int | None:
    """Amplitude-threshold rise of cycle j (plan, R1)."""
    peak = cycles[j]["peak"]
    if peak is None:
        return None
    if j > 0 and cycles[j - 1]["peak"] is not None:
        after = cycles[j - 1]["peak"]
    elif j > 0 and cycles[j - 1]["trough"] is not None:
        after = cycles[j - 1]["trough"] - 1  # the window starts at the previous trough boundary
    else:
        after = min(extent) - 1
    window = [t for t in range(after + 1, peak + 1) if usable.get(t)]
    if not window or not usable.get(peak):
        return None
    low, high = min(extent[t] for t in window), extent[peak]
    if high <= low:
        return None
    threshold = low + fraction * (high - low)
    for t in range(peak - 1, after, -1):
        if usable.get(t) and extent[t] <= threshold:
            return t + 1
    return None


def nearest_error(month: int, true_month: int) -> int:
    after = (month - (true_month - 1)) % 12
    return min(after, 12 - after)


def rise_offset(shape: str, fraction: float) -> int:
    """Months after the trough at which the noise-free shape's rise falls, under the same rule."""
    after = np.arange(12)
    values = 0.5 * (1 - np.cos(2 * np.pi * after / 12)) if shape == "sine" else g2.PULSE
    peak = int(np.argmax(values))
    return next(k + 1 for k in range(peak - 1, -1, -1) if values[k] <= fraction)


def rise_truth_month(record: dict, fraction: float = RISE_FRACTION) -> int:
    return (record["trough_month"] - 1 + rise_offset(record["shape"], fraction)) % 12 + 1


def pair_table(runs: dict, meta: dict, fraction: float = RISE_FRACTION) -> pd.DataFrame:
    rows = []
    for key, run in runs.items():
        info = meta[key]
        if info["kind"] != "seasonal" or run["route"] != "per_year_detection":
            continue
        extent, usable = record_series(info)
        cycles = run["cycles"]
        rise_true = rise_truth_month(info, fraction)
        for j in range(1, len(cycles)):
            trough, peak = cycles[j - 1]["trough"], cycles[j]["peak"]
            if trough is None or peak is None:
                continue
            rise = rise_month(cycles, j, extent, usable, fraction)
            rise_error = nearest_error(rise, rise_true) if rise is not None else None
            trough_error = g2.truth_error(trough, info["trough_month"], info["shape"])
            library_rise_error = nearest_error(trough + 1, rise_true)
            rows.append({
                "key": key, "arm": info["arm"], "shape": info["shape"], "has_rise": rise is not None,
                "rise_correct": rise_error is not None and rise_error <= 1, "rise_exact": rise_error == 0,
                "rise_signed": (l1.signed_error(rise, rise_true) if rise is not None else None),
                "trough_correct": trough_error <= 1, "trough_exact": trough_error == 0,
                "library_rise_correct": library_rise_error <= 1,
                "ratio": cycles[j]["ratio"], "peak_status": cycles[j]["peak_status"],
            })
    frame = pd.DataFrame(rows)
    if len(frame):
        frame["ratio"] = pd.to_numeric(frame["ratio"], errors="coerce")
    return frame


# ---------------------------------------------------------------- records


def main_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [g2.synthetic_record(s, "seasonal", sources) for s in SEASONAL_SEEDS]
    nulls = list(NULL_SEEDS)
    records += [g2.synthetic_record(s, "flat", sources) for s in nulls[:100]]
    records += [g2.synthetic_record(s, "random_pulse", sources) for s in nulls[100:]]
    records += [g2.injection_record(s, bg[(s - INJECTION_SEEDS.start) // INJECTIONS_PER_BACKGROUND])
                for s in INJECTION_SEEDS]
    return records


def pilot_records() -> list[dict]:
    sources, bg = g2.valid_sources(), g2.backgrounds()
    records = [g2.synthetic_record(s, "seasonal", sources) for s in PILOT_S_SEEDS]
    records += [g2.injection_record(s, bg[(i * 7) % len(bg)]) for i, s in enumerate(PILOT_I_SEEDS)]
    return records


# ---------------------------------------------------------------- stages


def stage_check(workers: int) -> None:
    records = l1.check_records()
    meta = {r["key"]: r for r in records}
    summary: dict = {}
    labels: dict = {}
    for setting in SETTINGS:
        sink = OUT / f"check_{setting}.jsonl"
        run_records(records, setting, sink, workers)
        runs = g1.load_runs(sink)
        labels[setting] = {key: [c["status"] for c in run["cycles"]] for key, run in runs.items()}
        per_shape = {}
        for shape in g2.SHAPES:
            total = at_truth = rise_total = rise_at_truth = 0
            for key, run in runs.items():
                if meta[key]["shape"] != shape:
                    continue
                cycles = run["cycles"]
                extent, usable = record_series(meta[key])
                for j in range(1, len(cycles) - 1):
                    total += 1
                    at_truth += int(cycles[j]["trough"] is not None and g2.truth_error(
                        cycles[j]["trough"], meta[key]["trough_month"], shape) == 0)
                    rise = rise_month(cycles, j, extent, usable, RISE_FRACTION)
                    rise_total += 1
                    rise_at_truth += int(rise is not None and nearest_error(rise, rise_truth_month(meta[key])) == 0)
            per_shape[shape] = {"cycles": total, "at_truth": at_truth, "share": (at_truth / total) if total else None,
                                "rise_cycles": rise_total, "rise_at_truth": rise_at_truth,
                                "rise_share": (rise_at_truth / rise_total) if rise_total else None}
        selftests = sorted({json.dumps(r["selftest"], sort_keys=True) for r in runs.values()})
        summary[setting] = {"by_shape": per_shape, "selftests": selftests,
                            "troughs_ok": all(v["share"] is not None and v["share"] >= 0.95 for v in per_shape.values())}
        log(f"check {setting}: {per_shape}, selftests={selftests}")
    changes = {shape: 0 for shape in g2.SHAPES}
    for key, statuses in labels["current"].items():
        changes[meta[key]["shape"]] += sum(a != b for a, b in zip(statuses, labels["two_sided"][key]))
    rise_ok = all(v["rise_share"] is not None and v["rise_share"] >= 0.95
                  for v in summary["current"]["by_shape"].values())
    summary["two_sided_label_changes"] = changes
    summary["pulse_labels_unchanged"] = changes["pulse"] == 0
    summary["r1_kept"] = rise_ok
    log(f"check: label changes {changes}, R1 kept={rise_ok}")
    (OUT / "check.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def stage_pilot(workers: int) -> None:
    """Pilot: run times and counts only, never accuracy."""
    records = pilot_records()
    meta = {r["key"]: r for r in records}
    scale = {"S": len(SEASONAL_SEEDS) / len(PILOT_S_SEEDS), "I": len(INJECTION_SEEDS) / len(PILOT_I_SEEDS)}
    summary: dict = {}
    for setting in SETTINGS:
        sink = OUT / f"pilot_{setting}.jsonl"
        run_records(records, setting, sink, workers)
        runs = g1.load_runs(sink)
        frame = l1.cycle_table(runs, meta)
        pairs = pair_table(runs, meta)
        for arm in ("S", "I"):
            sub = frame[frame["arm"] == arm]
            entry = {
                "records": sum(1 for k in runs if meta[k]["arm"] == arm),
                "median_seconds": float(np.median([r["seconds"] for k, r in runs.items() if meta[k]["arm"] == arm])),
                "predicted_point_dates": int((sub["dated"] & (sub["status"] == "point")).sum()) * scale[arm],
                "predicted_interval_dates": int((sub["dated"] & (sub["status"] == "interval")).sum()) * scale[arm],
            }
            for shape in g2.SHAPES:
                n = int(((pairs["arm"] == arm) & (pairs["shape"] == shape)).sum()) if len(pairs) else 0
                entry[f"predicted_{shape}_pairs"] = n * scale[arm]
            summary[f"{setting}:{arm}"] = entry
    (OUT / "pilot.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for key, value in summary.items():
        log(f"pilot {key}: {value}")


def stage_freeze() -> None:
    if RECEIPT.exists():
        raise SystemExit("receipt exists; the freeze is written once")
    import hydroseason
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as defaults

    check = json.loads((OUT / "check.json").read_text(encoding="utf-8"))
    records = main_records()
    g2.write_corpus(records, OUT / "corpus.jsonl.gz")
    receipt = {
        "plan": str(PLAN.relative_to(REPO_ROOT)).replace("\\", "/"),
        "plan_sha256_lf": g1.sha256_lf(PLAN),
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "l1_script_sha256_lf": g1.sha256_lf(Path(l1.__file__)),
        "g2_script_sha256_lf": g1.sha256_lf(Path(g2.__file__)),
        "g1_script_sha256_lf": g1.sha256_lf(Path(g1.__file__)),
        "git_head": g1.git("rev-parse", "HEAD"),
        "git_branch": g1.git("branch", "--show-current"),
        "git_status_short": g1.git("status", "--short").splitlines(),
        "hydroseason_version": hydroseason.__version__,
        "library_gates": {"ratio": defaults.min_amplitude_to_floor_ratio, "peak_pixels": defaults.min_peak_water_pixels},
        "settings": list(SETTINGS),
        "rise_fraction": RISE_FRACTION,
        "r1_kept": check["r1_kept"],
        "corpus_records": len(records),
        "corpus_sha256": g2.corpus_digest(records),
        "check": check,
        "pilot": json.loads((OUT / "pilot.json").read_text(encoding="utf-8")),
        "frozen_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    RECEIPT.write_text(json.dumps(g1.clean(receipt), indent=2) + "\n", encoding="utf-8")
    log(f"freeze: plan {receipt['plan_sha256_lf']}, script {receipt['script_sha256_lf']}, "
        f"corpus {receipt['corpus_sha256']} ({len(records)} records), R1 kept {receipt['r1_kept']}")


def stage_run(workers: int) -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    records = g2.read_corpus(OUT / "corpus.jsonl.gz")
    if g2.corpus_digest(records) != receipt["corpus_sha256"]:
        raise SystemExit("corpus does not match the receipt")
    for setting in SETTINGS:
        run_records(records, setting, OUT / f"main_{setting}.jsonl", workers)


# ---------------------------------------------------------------- evaluation


def _bootstrap(keys: list[str], per_key: dict[str, tuple], statistic, draws: int = 2000) -> list[float]:
    """Percentile 95% interval of statistic(sums) over records resampled with replacement (seed 0)."""
    rng = np.random.default_rng(0)
    table = np.array([per_key.get(k, (0,) * len(next(iter(per_key.values())))) for k in keys], dtype=float)
    values = []
    for _ in range(draws):
        sums = table[rng.integers(0, len(keys), len(keys))].sum(axis=0)
        value = statistic(sums)
        if value is not None and np.isfinite(value):
            values.append(value)
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def _ratio(k: float, n: float) -> float | None:
    return k / n if n else None


def evaluate_l2(runs: dict, meta: dict) -> dict:
    tables = {s: l1.cycle_table(runs[s], meta) for s in SETTINGS}
    out: dict = {"arms": {}}
    passes = True
    for arm in ("S", "I"):
        keys = sorted(k for k, v in meta.items() if v["arm"] == arm and v["kind"] == "seasonal")
        cur = tables["current"][(tables["current"]["arm"] == arm) & (tables["current"]["kind"] == "seasonal")]
        two = tables["two_sided"][(tables["two_sided"]["arm"] == arm) & (tables["two_sided"]["kind"] == "seasonal")]
        cur_safety, two_safety = l1.point_safety(cur), l1.point_safety(two)

        def counts(frame):
            points = frame[frame["dated"] & (frame["status"] == "point")]
            return {k: (len(g), int((~g["correct"]).sum())) for k, g in points.groupby("key")}

        c_counts, t_counts = counts(cur), counts(two)
        per_key = {k: (*c_counts.get(k, (0, 0)), *t_counts.get(k, (0, 0))) for k in keys}
        difference = (two_safety["share"] - cur_safety["share"]
                      if two_safety["share"] is not None and cur_safety["share"] is not None else None)
        interval = _bootstrap(keys, per_key, lambda s: (s[3] / s[2] - s[1] / s[0]) if s[0] and s[2] else None)
        rule_1 = {"current": cur_safety, "two_sided": two_safety, "difference": difference, "ci95": interval,
                  "evaluable": min(cur_safety["point_dates"], two_safety["point_dates"]) >= MIN_CASES}
        rule_1["holds"] = bool(rule_1["evaluable"] and difference <= -0.05 and interval[1] < 0)

        intervals = two[two["dated"] & (two["status"] == "interval")]
        interval_wrong = _ratio(int((~intervals["correct"]).sum()), len(intervals))
        rule_2 = {"point_not_correct": two_safety["share"], "interval_not_correct": interval_wrong,
                  "interval_dates": len(intervals),
                  "evaluable": min(two_safety["point_dates"], len(intervals)) >= MIN_CASES}
        rule_2["holds"] = bool(rule_2["evaluable"] and two_safety["share"] <= interval_wrong)

        route = {s: float(np.mean([runs[s][k]["route"] == "per_year_detection" for k in keys])) for s in SETTINGS}
        rule_3 = {"current": route["current"], "two_sided": route["two_sided"],
                  "difference": route["two_sided"] - route["current"], "evaluable": len(keys) >= MIN_CASES}
        rule_3["holds"] = bool(rule_3["evaluable"] and rule_3["difference"] >= -0.02)

        both = [k for k in keys if all(runs[s][k]["route"] == "per_year_detection" for s in SETTINGS)]
        moved = sum([c["trough"] for c in runs["current"][k]["cycles"]] != [c["trough"] for c in runs["two_sided"][k]["cycles"]]
                    for k in both)
        rule_4 = {"records_compared": len(both), "records_with_changed_dates": moved, "holds": moved == 0}

        out["arms"][arm] = {
            "rule_1": rule_1, "rule_2": rule_2, "rule_3": rule_3, "rule_4": rule_4,
            "reported": {s: l1.reported(tables[s][(tables[s]["arm"] == arm) & (tables[s]["kind"] == "seasonal")],
                                        runs[s], keys) for s in SETTINGS},
        }
        passes &= all(out["arms"][arm][r]["holds"] for r in ("rule_1", "rule_2", "rule_3", "rule_4"))
    nulls = [k for k, v in meta.items() if v["kind"] != "seasonal"]
    out["null"] = {s: {"records": len(nulls),
                       "routed_per_year_detection": float(np.mean([runs[s][k]["route"] == "per_year_detection" for k in nulls])),
                       "point_trough_dates": int(sum(c["status"] == "point" for k in nulls for c in runs[s][k]["cycles"]))}
                   for s in SETTINGS}
    out["passes"] = bool(passes)
    return out


def evaluate_r1(runs: dict, meta: dict) -> dict:
    out: dict = {"arms": {}, "reported_fractions": {}}
    passes = True
    pairs = pair_table(runs, meta)
    for arm in ("S", "I"):
        keys = sorted(k for k, v in meta.items() if v["arm"] == arm and v["kind"] == "seasonal")
        entry: dict = {}
        for shape, rule in (("pulse", "rule_1"), ("sine", "rule_2")):
            sub = pairs[(pairs["arm"] == arm) & (pairs["shape"] == shape)]
            per_key = {k: (len(g), int(g["rise_correct"].sum()), int(g["trough_correct"].sum()))
                       for k, g in sub.groupby("key")}
            per_key = {k: per_key.get(k, (0, 0, 0)) for k in keys}
            n = len(sub)
            rise_acc, trough_acc = _ratio(int(sub["rise_correct"].sum()), n), _ratio(int(sub["trough_correct"].sum()), n)
            difference = (rise_acc - trough_acc) if n else None
            interval = _bootstrap(keys, per_key, lambda s: (s[1] - s[2]) / s[0] if s[0] else None)
            result = {"pairs": n, "rise_accuracy": rise_acc, "trough_accuracy": trough_acc,
                      "difference": difference, "ci95": interval, "evaluable": n >= MIN_CASES,
                      "rise_exact": _ratio(int(sub["rise_exact"].sum()), n),
                      "trough_exact": _ratio(int(sub["trough_exact"].sum()), n),
                      "library_rise_accuracy": _ratio(int(sub["library_rise_correct"].sum()), n)}
            if shape == "pulse":
                result["holds"] = bool(result["evaluable"] and difference >= 0.05 and interval[0] > 0)
            else:
                result["holds"] = bool(result["evaluable"] and difference >= -0.02 and interval[0] >= -0.05)
            entry[rule] = result
        arm_pairs = pairs[pairs["arm"] == arm]
        coverage = _ratio(int(arm_pairs["has_rise"].sum()), len(arm_pairs))
        entry["rule_3"] = {"pairs": len(arm_pairs), "coverage": coverage,
                           "evaluable": len(arm_pairs) >= MIN_CASES}
        entry["rule_3"]["holds"] = bool(entry["rule_3"]["evaluable"] and coverage >= 0.90)
        reported: dict = {"by_ratio": {}, "rise_signed": {}, "by_peak_status": {}}
        bands = pd.cut(arm_pairs["ratio"], [3, 4, 6, 10, np.inf], right=False, labels=["3-4", "4-6", "6-10", "10+"])
        for (shape, band), g in arm_pairs.groupby([arm_pairs["shape"], bands], observed=True):
            reported["by_ratio"][f"{shape} {band}"] = {"pairs": len(g), "rise": float(g["rise_correct"].mean()),
                                                       "trough": float(g["trough_correct"].mean())}
        for shape, g in arm_pairs.groupby("shape"):
            reported["rise_signed"][shape] = {str(int(k)): int(v) for k, v in g["rise_signed"].dropna().value_counts().sort_index().items()}
        for (shape, status), g in arm_pairs.groupby(["shape", "peak_status"]):
            reported["by_peak_status"][f"{shape} {status}"] = {"pairs": len(g), "rise": float(g["rise_correct"].mean()),
                                                               "trough": float(g["trough_correct"].mean())}
        entry["reported"] = reported
        out["arms"][arm] = entry
        passes &= all(entry[r]["holds"] for r in ("rule_1", "rule_2", "rule_3"))
    for fraction in RISE_REPORTED:
        alt = pair_table(runs, meta, fraction)
        out["reported_fractions"][str(fraction)] = {
            f"{arm} {shape}": {"pairs": len(g), "rise": float(g["rise_correct"].mean()),
                               "trough": float(g["trough_correct"].mean()), "coverage": float(g["has_rise"].mean())}
            for (arm, shape), g in alt.groupby(["arm", "shape"])}
    out["passes"] = bool(passes)
    return out


def stage_evaluate() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    records = g2.read_corpus(OUT / "corpus.jsonl.gz")
    if g2.corpus_digest(records) != receipt["corpus_sha256"]:
        raise SystemExit("corpus does not match the receipt")
    meta = {r["key"]: r for r in records}
    runs = {s: g1.load_runs(OUT / f"main_{s}.jsonl") for s in SETTINGS}
    for s in SETTINGS:
        if set(runs[s]) != set(meta):
            raise SystemExit(f"{s}: run keys do not match the corpus")
    result = {
        "receipt_sha256_lf": g1.sha256_lf(RECEIPT),
        "errors": {s: sum(r["error"] is not None for r in runs[s].values()) for s in SETTINGS},
        "selftests_read_back": {s: sorted({json.dumps(r["selftest"], sort_keys=True) for r in runs[s].values()})
                                for s in SETTINGS},
        "fingerprints": {s: sorted({r.get("fingerprint") for r in runs[s].values() if r.get("fingerprint")})
                         for s in SETTINGS},
        "l2": evaluate_l2(runs, meta),
        "r1": evaluate_r1(runs["current"], meta) if receipt["r1_kept"] else {"dropped": True, "passes": False},
    }
    RESULTS.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    log(f"evaluate: L2 passes={result['l2']['passes']}, R1 passes={result['r1']['passes']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["check", "pilot", "freeze", "run", "evaluate"])
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    if args.stage in ("check", "pilot", "run"):
        {"check": stage_check, "pilot": stage_pilot, "run": stage_run}[args.stage](args.workers)
    else:
        {"freeze": stage_freeze, "evaluate": stage_evaluate}[args.stage]()


if __name__ == "__main__":
    main()
