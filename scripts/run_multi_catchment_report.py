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
import os
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason import (  # noqa: E402
    analyze_hydrological_state,
    load_wofs_from_stac,
    monthly_water_extent,
)

# plan_resolution/probe_amplitude are NOT re-exported from the top-level
# hydroseason package (tests/test_package_surface.py freezes __all__), so
# they're imported directly from hydroseason.io.
from hydroseason.io import _DEFAULT_CANDIDATE_RES_M, plan_resolution, probe_amplitude  # noqa: E402

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
START_DATE = "2015-01-01"
END_DATE = "2025-12-31"
OUTPUT_CRS = 3577  # GDA94 / Australian Albers

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
    )

    if resolution_override is not None:
        _, peak_gb, floor_pp, reason = plan_resolution(
            geo["bounds_wgs84"], OUTPUT_CRS,
            memory_budget_gb=_UNLIMITED_MEMORY_BUDGET_GB, observed_amplitude_pp=amplitude_pp,
            candidate_res_m=(resolution_override,),
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
            candidate_res_m=clamped_ladder,
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
) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint = OUTPUT_DIR / f"{spec.key}_state.pkl"
    if checkpoint.exists() and not force:
        print(f"[{spec.key}] checkpoint found, skipping run — use --force to redo", flush=True)
        with open(checkpoint, "rb") as f:
            return pickle.load(f)

    print(f"[{spec.key}] loading boundary + geo summary", flush=True)
    geo = _catchment_geo_summary(spec.key)
    boundary_path = CATCHMENTS_DIR / f"{spec.key}_boundary.geojson"

    print(f"[{spec.key}] probing seasonal amplitude + thin-channel guard", flush=True)
    guard = probe_amplitude(
        STAC_URL, COLLECTION, boundary_path, START_DATE, END_DATE, crs=OUTPUT_CRS,
    )
    amplitude_pp = guard["amplitude_pp"]
    guard_caveat = guard["guard_caveat"]
    refuse_coarsen_past = guard["refuse_coarsen_past"]

    plan = _choose_resolution(
        spec.key, geo,
        resolution_override=resolution_override, allow_large=allow_large,
        memory_budget_gb=memory_budget_gb, amplitude_pp=amplitude_pp,
        refuse_coarsen_past=refuse_coarsen_past,
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

    print(f"[{spec.key}] querying DEA STAC ({COLLECTION}, {START_DATE}..{END_DATE})", flush=True)
    water_mask = load_wofs_from_stac(
        STAC_URL, COLLECTION, boundary_path, START_DATE, END_DATE, crs=OUTPUT_CRS,
        resolution=resolution_m,
    )
    print(f"[{spec.key}] cube loaded: {dict(water_mask.sizes)}", flush=True)

    print(f"[{spec.key}] computing monthly extent (this triggers the dask graph)", flush=True)
    extent = monthly_water_extent(water_mask)
    print(f"[{spec.key}] extent series: {len(extent)} months", flush=True)
    n_valid = int(extent["n_valid"].median())

    print(f"[{spec.key}] running analyze_hydrological_state", flush=True)
    state = analyze_hydrological_state(extent)
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
    }
    with open(checkpoint, "wb") as f:
        pickle.dump(result, f)
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
        help="memory budget passed to plan_resolution (default: 12.0)",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    specs = CATCHMENTS
    if args.only:
        wanted = set(args.only.split(","))
        specs = [s for s in CATCHMENTS if s.key in wanted]
        missing = wanted - {s.key for s in specs}
        if missing:
            raise SystemExit(f"Unknown catchment key(s): {missing}")

    results = []
    failures = []
    for spec in specs:
        try:
            results.append(run_one_catchment(
                spec, args.force,
                resolution_override=args.resolution,
                allow_large=args.allow_large,
                memory_budget_gb=args.memory_budget_gb,
            ))
        except Exception as exc:  # noqa: BLE001 - report and continue to next catchment
            print(f"[{spec.key}] FAILED: {exc!r}", flush=True)
            failures.append((spec.key, repr(exc)))

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
