"""Extract monthly WOfS water-extent time series from STAC and dump one CSV
per catchment to output/water_extent_csv/.

Uses the fast path: tiled STAC load (``tile_pixels``) with a precomputed
wet-AOI prune (``precompute_wet_aoi``) so tiles the AOI never gets wet in are
skipped entirely. This is the same loader `run_multi_catchment_report.py`
uses, minus the hydrological-state analysis and HTML report -- just the raw
extent series, for timing/benchmarking the STAC extraction step in
isolation.

Usage:
    python scripts/extract_water_extent_csv.py
    python scripts/extract_water_extent_csv.py --only gilbert_river_qld,daly_river_nt
    python scripts/extract_water_extent_csv.py --no-tiling   # legacy whole-AOI path, for comparison

    # arbitrary AOI file (not a fixture catchment), with phase timing:
    python scripts/extract_water_extent_csv.py --aoi data/Gilbert_river_buffer.geojson \
        --resolution 30 --profile
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason._io_geo import _crs_value  # noqa: E402
from hydroseason._io_wofs_acquire import (  # noqa: E402
    _aoi_digest,
    _probe_local_wet_aoi_handle,
    _resolve_wet_aoi,
)
from hydroseason._io_wofs_zarr import (  # noqa: E402
    WOFS_CACHE_SCHEMA_VERSION,
    WOFS_CLASSIFIER_VERSION,
    WOFS_PLANNER_VERSION,
)
from hydroseason.io import acquire_wofs_cache, load_aoi, load_wofs_monthly_extent  # noqa: E402

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
START_DATE = "1986-05-01"
END_DATE = "2026-06-01"
OUTPUT_CRS = 3577
TIME_BLOCK = 12
TILE_PIXELS = 2048

CATCHMENTS_DIR = REPO_ROOT / "data" / "catchments"
OUTPUT_DIR = REPO_ROOT / "output" / "water_extent_csv"
DEFAULT_MASK_CACHE_DIR = REPO_ROOT / "output" / "wofs_cache"

CATCHMENT_KEYS = [
    "gilbert_river_qld",
    "fitzroy_river_wa",
    "moonie_river_qld_nsw",
    "lachlan_river_nsw",
    "paroo_river_qld_nsw",
    "daly_river_nt",
]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", type=str, default=None, help="comma-separated catchment keys to run")
    parser.add_argument(
        "--aoi", type=str, default=None,
        help="path to an arbitrary AOI vector file, run instead of the fixture catchments "
             "(e.g. data/Gilbert_river_buffer.geojson). Repeatable via comma-separated paths.",
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="output/cache basename for --aoi (defaults to the AOI file stem)",
    )
    parser.add_argument("--force", action="store_true", help="ignore extent cache, refetch from STAC")
    parser.add_argument(
        "--no-tiling", action="store_true",
        help="use the legacy whole-AOI load instead of tiled+wet-AOI-pruned (for A/B timing)",
    )
    parser.add_argument(
        "--tile-pixels",
        type=int,
        default=TILE_PIXELS,
        help="tile size in pixels for legacy direct path (default: 1024; canonical cache uses 512-aligned execution grid)",
    )
    parser.add_argument("--resolution", type=float, default=30.0, help="load resolution (metres; default: 30)")
    parser.add_argument(
        "--mask-cache-dir",
        type=Path,
        default=DEFAULT_MASK_CACHE_DIR,
        help="internal canonical WOfS mask cache directory (default: output/wofs_cache)",
    )
    cache_mode = parser.add_mutually_exclusive_group()
    cache_mode.add_argument(
        "--offline",
        action="store_true",
        help="read only from the canonical local WOfS mask cache; fail explicitly on a cache miss",
    )
    cache_mode.add_argument(
        "--legacy-remote-path",
        action="store_true",
        help="bypass the canonical mask cache and use the legacy direct STAC path",
    )
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    parser.add_argument("--time-block", type=int, default=TIME_BLOCK)
    parser.add_argument(
        "--compute-batch-size",
        type=int,
        default=16,
        help="spatial 512px blocks per bounded Dask compute call (default: 16)",
    )
    parser.add_argument(
        "--read-workers", type=int, default=0,
        help="override dask's threaded-scheduler worker count for both canonical acquisition and local reduction "
             "(0 = leave dask's own default alone; only set if confirmed to help)",
    )
    parser.add_argument(
        "--resampling-policy",
        choices=("categorical_safe", "native_aligned"),
        default="categorical_safe",
        help="resampling policy for WOfS loading (default: categorical_safe)",
    )
    parser.add_argument(
        "--year-workers", type=int, default=1,
        help="number of concurrent worker threads for parallel multi-year acquisition (default: 1)",
    )
    parser.add_argument(
        "--wet-mask",
        choices=("off", "dea_stats"),
        default="off",
        help="prune reads to an ever-wet mask. 'dea_stats' derives it from DEA Water "
             "Observation Statistics (ga_ls_wo_fq_myear_3 + ga_ls_wo_fq_cyear_3). "
             "NOTE: a pruned run writes to a DIFFERENT cache store than a full-coverage "
             "run, so it will not reuse years already acquired without the mask "
             "(default: off)",
    )
    parser.add_argument(
        "--output-csv", type=str, default=None,
        help="explicit path for output CSV (default: output/water_extent_csv/{name}_{res}m_water_extent.csv)",
    )
    parser.add_argument(
        "--profile", action="store_true",
        help="print per-phase timing (precompute vs tiled, per-year, tile-skip counts) to stderr",
    )
    return parser


def _resolve_jobs(args) -> list[tuple[str, Path]]:
    """Build a list of (name, aoi_path) jobs from --aoi or the fixture keys."""
    if args.aoi:
        paths = [Path(p.strip()) for p in args.aoi.split(",") if p.strip()]
        if args.name and len(paths) > 1:
            raise SystemExit("--name is only valid with a single --aoi path.")
        jobs = []
        for path in paths:
            if not path.exists():
                raise SystemExit(f"AOI file not found: {path}")
            name = args.name if args.name else path.stem
            jobs.append((name, path))
        return jobs

    keys = CATCHMENT_KEYS
    if args.only:
        wanted = set(args.only.split(","))
        keys = [k for k in CATCHMENT_KEYS if k in wanted]
        missing = wanted - set(keys)
        if missing:
            raise SystemExit(f"Unknown catchment key(s): {missing}")
    return [(key, CATCHMENTS_DIR / f"{key}_boundary.geojson") for key in keys]


def _process_job(job: tuple[str, Path], args, tile_kwargs: dict, position: int = 0) -> dict:
    name, boundary_path = job
    res_val = args.resolution if args.resolution is not None else 30.0
    res_suffix = f"_{int(res_val)}m" if args.resolution is not None else ""
    out_csv = Path(args.output_csv) if getattr(args, "output_csv", None) else OUTPUT_DIR / f"{name}{res_suffix}_water_extent.csv"

    t0 = time.monotonic()
    extent = load_wofs_monthly_extent(
        STAC_URL, COLLECTION, boundary_path, args.start_date, args.end_date,
        crs=OUTPUT_CRS,
        resolution=args.resolution,
        time_block=args.time_block,
        force=args.force,
        cache_dir=OUTPUT_DIR / "_extent_cache" / name,
        mask_cache_dir=None if args.legacy_remote_path else args.mask_cache_dir,
        offline=args.offline,
        progress=True,
        progress_desc=f"[{name}]",
        progress_position=position,
        read_workers=args.read_workers if args.read_workers > 0 else None,
        resampling_policy=args.resampling_policy,
        year_workers=args.year_workers,
        wet_mask=args.wet_mask,
        **tile_kwargs,
    )
    elapsed = time.monotonic() - t0
    extent.to_csv(out_csv)
    print(f"[{name}] {len(extent)} months written in {elapsed:.1f}s -> {out_csv}", flush=True)

    if args.profile and not args.legacy_remote_path:
        # offline=True never touches the network, so it can only derive
        # wet_mask_sha256 from an explicit wet_aoi (see
        # hydroseason._io_wofs_acquire.acquire_wofs_cache's `if offline:`
        # branch). Passing wet_mask straight through here would silently
        # resolve to the unpruned store identity and 404 against the pruned
        # store the main call above just wrote. Resolve the mask ourselves
        # first (same preference order the main call uses) and pass the
        # resolved wet_aoi instead.
        aoi_gdf = load_aoi(boundary_path)
        profile_years = list(range(pd.Timestamp(args.start_date).year, pd.Timestamp(args.end_date).year + 1))
        # Every field of WOfSCacheRequest except wet_mask_sha256, built the
        # same way hydroseason._io_wofs_acquire.acquire_wofs_cache builds its
        # own base_request_kwargs -- must match the main (non-profile) call
        # above exactly, or the local-store probe below looks up the wrong
        # request and always misses.
        base_request_kwargs = dict(
            stac_url=STAC_URL,
            collection=COLLECTION,
            aoi_sha256=_aoi_digest(aoi_gdf),
            start_date=pd.Timestamp(args.start_date).strftime("%Y-%m-%d"),
            end_date=pd.Timestamp(args.end_date).strftime("%Y-%m-%d"),
            crs=str(_crs_value(OUTPUT_CRS)),
            resolution=float(args.resolution),
            classifier_version=WOFS_CLASSIFIER_VERSION,
            groupby="solar_day",
            majority=True,
            planner_version=WOFS_PLANNER_VERSION,
            schema_version=WOFS_CACHE_SCHEMA_VERSION,
        )
        local_wet_aoi_handle = _probe_local_wet_aoi_handle(
            args.mask_cache_dir,
            base_request_kwargs,
            wet_aoi=None,
            wet_mask=args.wet_mask,
        )
        resolved_wet_aoi, _resolved_digest = _resolve_wet_aoi(
            STAC_URL,
            aoi_gdf,
            profile_years,
            wet_aoi=None,
            wet_mask=args.wet_mask,
            crs=OUTPUT_CRS,
            resolution=args.resolution,
            progress=False,
            aoi_name=name,
            local_wet_aoi_handle=local_wet_aoi_handle,
        )
        handle = acquire_wofs_cache(
            STAC_URL,
            COLLECTION,
            boundary_path,
            args.start_date,
            args.end_date,
            cache_root=args.mask_cache_dir,
            crs=OUTPUT_CRS,
            resolution=args.resolution,
            offline=True,
            resampling_policy=args.resampling_policy,
            year_workers=args.year_workers,
            wet_aoi=resolved_wet_aoi,
        )
        manifest_path = Path(handle.path) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        diagnostics = manifest.get("acquisition", {}).get("plan_diagnostics", [])
        print(
            f"[{name}] canonical cache: identity={handle.identity} store={handle.path}",
            file=sys.stderr,
            flush=True,
        )
        print(
            f"[{name}] planner diagnostics: {json.dumps(diagnostics, sort_keys=True)}",
            file=sys.stderr,
            flush=True,
        )

    return {
        "catchment": name,
        "resolution_m": res_val,
        "n_months": len(extent),
        "elapsed_seconds": round(elapsed, 2),
        "start_date": args.start_date,
        "end_date": args.end_date,
    }


def main() -> None:
    args = _build_arg_parser().parse_args()

    if args.profile:
        os.environ["HYDROSEASON_PROFILE"] = "1"

    jobs = _resolve_jobs(args)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tile_kwargs = {}
    if not args.no_tiling and args.tile_pixels:
        tile_kwargs = {"tile_pixels": args.tile_pixels, "precompute_wet_aoi": False}

    overall_start = time.monotonic()
    timing_records = []

    res_display = args.resolution or 30.0
    print(f"Starting extraction across {len(jobs)} catchment(s) (res={res_display:.0f}m)...\n", flush=True)

    for idx, job in enumerate(jobs):
        record = _process_job(job, args, tile_kwargs, position=0)
        timing_records.append(record)

    total_time = time.monotonic() - overall_start
    print(f"\nTotal: {total_time:.1f}s for {len(jobs)} AOI(s)")

    if timing_records:
        timing_df = pd.DataFrame(timing_records)
        timing_csv_path = OUTPUT_DIR / "execution_timing.csv"

        if timing_csv_path.exists():
            existing_df = pd.read_csv(timing_csv_path)
            combined_df = pd.concat([existing_df, timing_df], ignore_index=True)
        else:
            combined_df = timing_df

        combined_df.to_csv(timing_csv_path, index=False)
        print(f"\nExecution timing updated in: {timing_csv_path}")
        try:
            print(combined_df.to_markdown(index=False))
        except Exception:
            print(combined_df.to_string(index=False))


if __name__ == "__main__":
    main()
