"""Run HydroSeason across all real-data catchment fixtures and build one
combined, interactive HTML report for manager-facing presentation.

Pulls monthly WOfS (DEA STAC, `ga_ls_wo_3`) for each catchment boundary in
`data/catchments/`, runs the dynamic hydrological-state pipeline
(`analyze_hydrological_state` — auto-detects seasonal pattern: unimodal,
bimodal/complex, weak/irregular, or low-variability), and renders one
self-contained HTML document with per-catchment interactive Plotly charts
plus a cross-catchment comparison section.

Requires network access to the DEA STAC endpoint and the `stac` extra
(pystac_client, odc.stac, rioxarray, xarray). Runtime is dominated by
STAC query + dask compositing per catchment; large basins (Fitzroy WA
~97,000 km², Lachlan ~77,000 km²) take substantially longer than small
ones (Moonie ~14,700 km²). Expect this to run for a while — each
catchment is independent, so a partial failure doesn't lose prior results
(state is checkpointed to `output/multi_catchment/{key}_state.pkl` as it
goes; rerun to resume, already-checkpointed catchments are skipped).

Usage:
    python scripts/run_multi_catchment_report.py
    python scripts/run_multi_catchment_report.py --only gilbert_river_qld,daly_river_nt
    python scripts/run_multi_catchment_report.py --force  # ignore checkpoints
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pickle
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason import analyze_hydrological_state  # noqa: E402

# plan_resolution/probe_amplitude are NOT re-exported from the top-level
# hydroseason package (tests/test_package_surface.py freezes __all__), so
# they're imported directly from hydroseason.io.
from hydroseason.io import (  # noqa: E402
    _DEFAULT_CANDIDATE_RES_M,
    load_wofs_monthly_extent,
    plan_resolution,
    probe_amplitude,
)

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
START_DATE = "2015-01-01"
END_DATE = "2025-12-31"
OUTPUT_CRS = 3577  # GDA94 / Australian Albers
TIME_BLOCK = 12

# Effectively-unlimited budget used to re-derive costs when a gate decision is
# bypassed/overridden -- large enough that peak_gb never exceeds it for any
# realistic AOI/resolution, so plan_resolution's memory constraint stops
# binding and only the (still-checked) signal bound can veto.
_UNLIMITED_MEMORY_BUDGET_GB = 1e12

CATCHMENTS_DIR = REPO_ROOT / "data" / "catchments"
OUTPUT_DIR = REPO_ROOT / "output" / "multi_catchment"
REPORT_PATH = REPO_ROOT / "notebooks" / "hydroseason_multi_catchment_report.html"


@dataclass
class CatchmentSpec:
    key: str
    display_name: str
    river: str
    region: str
    regime_note: str


CATCHMENTS = [
    CatchmentSpec(
        "gilbert_river_qld", "Gilbert River (QLD)", "Gilbert River",
        "QLD, Gulf of Carpentaria",
        "Wet-dry tropics, monsoonal, flashy runoff.",
    ),
    CatchmentSpec(
        "fitzroy_river_wa", "Fitzroy River (WA)", "Fitzroy River",
        "WA, Kimberley",
        "Wet-dry tropics, monsoonal; existing Fitzroy/Kimberley acceptance case.",
    ),
    CatchmentSpec(
        "moonie_river_qld_nsw", "Moonie River (QLD/NSW)", "Moonie River",
        "QLD/NSW border, northern Murray-Darling Basin",
        "Dry, low-relief, intermittent flow.",
    ),
    CatchmentSpec(
        "lachlan_river_nsw", "Lachlan River (NSW)", "Lachlan River",
        "NSW, southern Murray-Darling Basin",
        "Semi-arid, regulated, terminal wetlands (Great Cumbung Swamp).",
    ),
    CatchmentSpec(
        "paroo_river_qld_nsw", "Paroo River (QLD/NSW)", "Paroo River",
        "QLD/NSW, northern Murray-Darling Basin",
        "Extreme boom-bust ephemeral, unregulated, terminal overflow lakes.",
    ),
    CatchmentSpec(
        "daly_river_nt", "Daly River (NT)", "Daly River",
        "NT, wet-dry tropics",
        "Perennial, spring/baseflow-fed (karst) — contrasts Gilbert/Fitzroy's flashiness.",
    ),
]


def _catchment_geo_summary(key: str) -> dict:
    import geopandas as gpd

    boundary = gpd.read_parquet(CATCHMENTS_DIR / f"{key}_boundary.parquet")
    area_km2 = float(boundary["area_km2"].iloc[0])
    streams_path = CATCHMENTS_DIR / f"{key}_streams.parquet"
    n_reaches = None
    if streams_path.exists():
        streams = gpd.read_parquet(streams_path)
        n_reaches = int(len(streams))
    bounds = boundary.to_crs(4326).total_bounds.tolist()
    return {"area_km2": area_km2, "n_stream_reaches": n_reaches, "bounds_wgs84": bounds}


def _choose_resolution(
    spec_key: str,
    geo: dict,
    *,
    resolution_override: float | None,
    allow_large: bool,
    memory_budget_gb: float,
    amplitude_pp: float,
    refuse_coarsen_past: float | None,
    time_chunk: int,
) -> dict:
    """Run the gate, apply precedence rules, and pick the resolution to load at.

    Precedence, highest first:
      1. ``resolution_override`` (``--resolution``): used verbatim. The gate is
         still called first so its pick is available to print for visibility,
         but it is not used to choose the resolution. Cost figures reported are
         re-derived for the override value itself (single-candidate re-plan
         with an unlimited budget), not the gate's own pick, so the printed
         peak_gb/noise_floor/reason are honest for what will actually run.
      2. Guard clamp (``refuse_coarsen_past``): if the gate's pick is coarser
         (a larger metre value) than the guard allows, plan_resolution is
         re-run with its candidate ladder filtered down to candidates no
         coarser than ``refuse_coarsen_past``. This re-derives peak_gb/
         noise_floor_pp/reason for the clamped resolution itself, rather than
         reusing the stale unclamped-pick numbers (which would be wrong for a
         different resolution).
      3. ``--allow-large`` bypass of a pure memory veto (``reason ==
         "native_no_fit"``: even the coarsest candidate exceeds
         memory_budget_gb): re-run plan_resolution with an effectively
         unlimited memory_budget_gb, so the memory constraint stops binding
         and the finest candidate is picked (still subject to the signal
         bound if observed_amplitude_pp was supplied -- a bypassed memory
         veto can still legitimately land on ``signal_veto_no_fit``, which is
         handled independently by the caller via ``pattern_claim_excluded``).
      4. Otherwise: use the gate's pick as-is.

    Returns a dict with ``resolution_m``, ``peak_gb``, ``noise_floor_pp``,
    ``reason``, and ``gate_resolution_m`` (the gate's original, un-overridden
    pick -- kept for the printed cost block even when overridden/clamped/
    bypassed).
    """
    gate_resolution_m, gate_peak_gb, gate_floor_pp, gate_reason = plan_resolution(
        geo["bounds_wgs84"], OUTPUT_CRS,
        memory_budget_gb=memory_budget_gb, observed_amplitude_pp=amplitude_pp,
        time_chunk=time_chunk,
    )

    if resolution_override is not None:
        _, peak_gb, floor_pp, reason = plan_resolution(
            geo["bounds_wgs84"], OUTPUT_CRS,
            memory_budget_gb=_UNLIMITED_MEMORY_BUDGET_GB, observed_amplitude_pp=amplitude_pp,
            candidate_res_m=(resolution_override,), time_chunk=time_chunk,
        )
        return {
            "resolution_m": resolution_override, "peak_gb": peak_gb,
            "noise_floor_pp": floor_pp, "reason": reason,
            "gate_resolution_m": gate_resolution_m,
        }

    if refuse_coarsen_past is not None and gate_resolution_m > refuse_coarsen_past:
        clamped_ladder = tuple(r for r in _DEFAULT_CANDIDATE_RES_M if r <= refuse_coarsen_past)
        resolution_m, peak_gb, floor_pp, reason = plan_resolution(
            geo["bounds_wgs84"], OUTPUT_CRS,
            memory_budget_gb=memory_budget_gb, observed_amplitude_pp=amplitude_pp,
            candidate_res_m=clamped_ladder, time_chunk=time_chunk,
        )
        print(
            f"[{spec_key}] guard clamp: gate wanted {gate_resolution_m:.0f} m, "
            f"refuse_coarsen_past={refuse_coarsen_past:.0f} m -> re-planned to "
            f"{resolution_m:.0f} m",
            flush=True,
        )
        return {
            "resolution_m": resolution_m, "peak_gb": peak_gb,
            "noise_floor_pp": floor_pp, "reason": reason,
            "gate_resolution_m": gate_resolution_m,
        }

    if allow_large and gate_reason == "native_no_fit":
        resolution_m, peak_gb, floor_pp, reason = plan_resolution(
            geo["bounds_wgs84"], OUTPUT_CRS,
            memory_budget_gb=_UNLIMITED_MEMORY_BUDGET_GB, observed_amplitude_pp=amplitude_pp,
            time_chunk=time_chunk,
        )
        print(
            f"[{spec_key}] --allow-large bypass: memory_budget_gb={memory_budget_gb} "
            f"vetoed all candidates (native_no_fit) -> re-planned with an unlimited "
            f"budget, picked {resolution_m:.0f} m",
            flush=True,
        )
        return {
            "resolution_m": resolution_m, "peak_gb": peak_gb,
            "noise_floor_pp": floor_pp, "reason": reason,
            "gate_resolution_m": gate_resolution_m,
        }

    return {
        "resolution_m": gate_resolution_m, "peak_gb": gate_peak_gb,
        "noise_floor_pp": gate_floor_pp, "reason": gate_reason,
        "gate_resolution_m": gate_resolution_m,
    }


def run_one_catchment(
    spec: CatchmentSpec,
    force: bool,
    *,
    resolution_override: float | None = None,
    allow_large: bool = False,
    memory_budget_gb: float = 12.0,
    start_date: str | None = None,
    end_date: str | None = None,
    time_block: int = TIME_BLOCK,
    baseline: str = "rolling",
) -> dict:
    start_date = start_date or START_DATE
    end_date = end_date or END_DATE
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    boundary_path = CATCHMENTS_DIR / f"{spec.key}_boundary.geojson"
    boundary_sha256 = (
        hashlib.sha256(boundary_path.read_bytes()).hexdigest() if boundary_path.exists() else None
    )
    run_config = {
        "start_date": start_date,
        "end_date": end_date,
        "resolution_override": resolution_override,
        "allow_large": allow_large,
        "memory_budget_gb": memory_budget_gb,
        "time_block": time_block,
        "boundary_sha256": boundary_sha256,
        "baseline": baseline,
        "mask_cache_identity": {
            "cache_dir": str(OUTPUT_DIR / "extent_cache" / spec.key),
            "collection": COLLECTION,
            "crs": OUTPUT_CRS,
            "stac_url": STAC_URL,
        },
    }
    checkpoint = OUTPUT_DIR / f"{spec.key}_state.pkl"
    if checkpoint.exists() and not force:
        try:
            with open(checkpoint, "rb") as f:
                cached_result = pickle.load(f)
        except (OSError, EOFError, pickle.UnpicklingError):
            cached_result = None
        if cached_result is not None and cached_result.get("run_config") == run_config:
            print(f"[{spec.key}] checkpoint found, skipping run — use --force to redo", flush=True)
            return cached_result
        print(f"[{spec.key}] checkpoint is stale for current settings; recomputing", flush=True)

    print(f"[{spec.key}] loading boundary + geo summary", flush=True)
    geo = _catchment_geo_summary(spec.key)

    print(f"[{spec.key}] probing seasonal amplitude + thin-channel guard", flush=True)
    guard = probe_amplitude(
        STAC_URL, COLLECTION, boundary_path, start_date, end_date, crs=OUTPUT_CRS,
        cache_dir=OUTPUT_DIR / "extent_cache" / spec.key,
        force=force, time_block=time_block,
    )
    amplitude_pp = guard["amplitude_pp"]
    guard_caveat = guard["guard_caveat"]
    refuse_coarsen_past = guard["refuse_coarsen_past"]

    plan = _choose_resolution(
        spec.key, geo,
        resolution_override=resolution_override, allow_large=allow_large,
        memory_budget_gb=memory_budget_gb, amplitude_pp=amplitude_pp,
        refuse_coarsen_past=refuse_coarsen_past,
        time_chunk=time_block,
    )
    resolution_m = plan["resolution_m"]
    reason = plan["reason"]

    # Print exact cost, no interactive prompt: this MUST stay batch/non-interactive
    # (print-and-proceed, never input() or any blocking prompt).
    print(
        f"[{spec.key}] resolution plan: chosen={resolution_m:.0f} m "
        f"(gate picked {plan['gate_resolution_m']:.0f} m) "
        f"projected_peak_gb={plan['peak_gb']:.3f} "
        f"projected_noise_floor_pp={plan['noise_floor_pp']:.5f} "
        f"reason={reason}",
        flush=True,
    )
    if guard_caveat:
        print(f"[{spec.key}] guard caveat: {guard_caveat}", flush=True)

    pattern_claim_excluded = reason == "signal_veto_no_fit"
    if pattern_claim_excluded:
        print(
            f"[{spec.key}] signal_veto_no_fit: loading anyway, but this catchment "
            f"will be excluded from pattern claims in the report.",
            flush=True,
        )

    print(f"[{spec.key}] loading cached annual extent ({COLLECTION}, {start_date}..{end_date})", flush=True)
    extent = load_wofs_monthly_extent(
        STAC_URL, COLLECTION, boundary_path, start_date, end_date, crs=OUTPUT_CRS,
        resolution=resolution_m, time_block=time_block, force=False,
        cache_dir=OUTPUT_DIR / "extent_cache" / spec.key,
    )
    print(f"[{spec.key}] extent series: {len(extent)} months", flush=True)
    n_valid = int(extent["n_valid"].median())

    print(f"[{spec.key}] running analyze_hydrological_state", flush=True)
    state = analyze_hydrological_state(
        extent,
        reference=baseline,
        rolling_window_cycles=10,
        rolling_min_cycles=5,
    )
    print(
        f"[{spec.key}] pattern={state.pattern.pattern} "
        f"n_hydro_years={len(state.hydro_years)}",
        flush=True,
    )

    result = {
        "spec": spec,
        "geo": geo,
        "extent": extent,
        "pattern": state.pattern,
        "config": state.config,
        "hydro_years": state.hydro_years,
        "monthly_condition": state.monthly_condition,
        "data_quality": state.data_quality,
        "resolution_m": resolution_m,
        "n_valid": n_valid,
        "projected_noise_floor_pp": plan["noise_floor_pp"],
        "reason": reason,
        "guard_caveat": guard_caveat,
        "pattern_claim_excluded": pattern_claim_excluded,
        "run_config": run_config,
    }
    descriptor, temporary_name = tempfile.mkstemp(
        dir=OUTPUT_DIR, prefix=f".{spec.key}-", suffix=".tmp"
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with open(temporary_path, "wb") as f:
            pickle.dump(result, f)
        os.replace(temporary_path, checkpoint)
    finally:
        temporary_path.unlink(missing_ok=True)
    print(f"[{spec.key}] checkpointed -> {checkpoint}", flush=True)
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", type=str, default=None, help="comma-separated catchment keys to run")
    parser.add_argument("--force", action="store_true", help="ignore checkpoints, rerun everything")
    parser.add_argument(
        "--resolution", type=float, default=None,
        help="override the resolution gate entirely and load at this resolution (metres)",
    )
    parser.add_argument(
        "--allow-large", action="store_true",
        help=(
            "bypass the memory veto (plan_resolution reason=native_no_fit): "
            "re-plan with an effectively unlimited memory budget so the "
            "finest candidate is picked, instead of refusing to run"
        ),
    )
    parser.add_argument(
        "--memory-budget-gb", type=float, default=12.0,
        help="total memory budget shared across concurrent workers (default: 12.0)",
    )
    parser.add_argument("--workers", type=int, default=2, help="parallel catchments (default: 2)")
    parser.add_argument(
        "--time-block", type=int, default=TIME_BLOCK,
        help="months per dask compute block (default: 12)",
    )
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    parser.add_argument(
        "--baseline", choices=["rolling", "full_record"], default="rolling",
        help="condition baseline mode: adaptive rolling (default) or single full-record baseline",
    )
    return parser


def _run_catchments(
    specs, *, workers: int, run_kwargs: dict
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Run independent catchments concurrently while preserving report order."""
    ordered_results: list[dict | None] = [None] * len(specs)
    failures: list[tuple[str, str]] = []

    def record(index, spec, *, result=None, error=None):
        if error is None:
            ordered_results[index] = result
        else:
            print(f"[{spec.key}] FAILED: {error!r}", flush=True)
            failures.append((spec.key, repr(error)))

    if workers == 1:
        for index, spec in enumerate(specs):
            try:
                record(index, spec, result=run_one_catchment(spec, **run_kwargs))
            except Exception as exc:  # noqa: BLE001
                record(index, spec, error=exc)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hydroseason") as executor:
            futures = {
                executor.submit(run_one_catchment, spec, **run_kwargs): (index, spec)
                for index, spec in enumerate(specs)
            }
            for future in as_completed(futures):
                index, spec = futures[future]
                try:
                    record(index, spec, result=future.result())
                except Exception as exc:  # noqa: BLE001
                    record(index, spec, error=exc)
    return [result for result in ordered_results if result is not None], failures


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.time_block < 1:
        parser.error("--time-block must be at least 1")

    specs = CATCHMENTS
    if args.only:
        wanted = set(args.only.split(","))
        specs = [s for s in CATCHMENTS if s.key in wanted]
        missing = wanted - {s.key for s in specs}
        if missing:
            raise SystemExit(f"Unknown catchment key(s): {missing}")

    active_workers = min(args.workers, len(specs))
    per_worker_budget_gb = args.memory_budget_gb / active_workers
    print(
        f"Running {len(specs)} catchments with {active_workers} worker(s); "
        f"{per_worker_budget_gb:.2f} GB planning budget per worker",
        flush=True,
    )
    results, failures = _run_catchments(
        specs,
        workers=active_workers,
        run_kwargs={
            "force": args.force,
            "resolution_override": args.resolution,
            "allow_large": args.allow_large,
            "memory_budget_gb": per_worker_budget_gb,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "time_block": args.time_block,
            "baseline": args.baseline,
        },
    )

    if not results:
        raise SystemExit("No catchments produced results; nothing to report.")

    from build_multi_catchment_html import build_report  # noqa: E402  (local module, see scripts/)

    build_report(results, REPORT_PATH)
    print(f"\nReport written to: {REPORT_PATH.resolve()}")

    if failures:
        print("\nFailed catchments (excluded from report):")
        for key, err in failures:
            print(f"  {key}: {err}")


if __name__ == "__main__":
    main()
