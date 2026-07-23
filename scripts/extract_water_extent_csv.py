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
import os
import sys
import time
from pathlib import Path

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason.io import load_wofs_monthly_extent  # noqa: E402

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
START_DATE = "1986-05-01"
END_DATE = "2026-06-01"
OUTPUT_CRS = 3577
TIME_BLOCK = 12
TILE_PIXELS = 2048

CATCHMENTS_DIR = REPO_ROOT / "data" / "catchments"
OUTPUT_DIR = REPO_ROOT / "output" / "water_extent_csv"

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
    parser.add_argument("--tile-pixels", type=int, default=TILE_PIXELS)
    parser.add_argument("--resolution", type=float, default=None, help="override load resolution (metres)")
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    parser.add_argument("--time-block", type=int, default=TIME_BLOCK)
    parser.add_argument(
        "--read-workers", type=int, default=32,
        help="dask worker count for concurrent S3 COG reads (higher = more parallel "
             "reads for this latency-bound load; 0 leaves dask's default untouched)",
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


def main() -> None:
    args = _build_arg_parser().parse_args()

    if args.profile:
        os.environ["HYDROSEASON_PROFILE"] = "1"

    jobs = _resolve_jobs(args)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tile_kwargs = {}
    if not args.no_tiling:
        tile_kwargs = {"tile_pixels": args.tile_pixels, "precompute_wet_aoi": True}

    overall_start = time.monotonic()
    for name, boundary_path in jobs:
        out_csv = OUTPUT_DIR / f"{name}_water_extent.csv"

        print(f"[{name}] extracting {args.start_date}..{args.end_date} -> {out_csv}", flush=True)
        t0 = time.monotonic()
        extent = load_wofs_monthly_extent(
            STAC_URL, COLLECTION, boundary_path, args.start_date, args.end_date,
            crs=OUTPUT_CRS,
            resolution=args.resolution,
            time_block=args.time_block,
            force=args.force,
            cache_dir=OUTPUT_DIR / "_extent_cache" / name,
            progress=True,
            read_workers=args.read_workers,
            **tile_kwargs,
        )
        elapsed = time.monotonic() - t0
        extent.to_csv(out_csv)
        print(f"[{name}] {len(extent)} months written in {elapsed:.1f}s", flush=True)

    print(f"\nTotal: {time.monotonic() - overall_start:.1f}s for {len(jobs)} AOI(s)")


if __name__ == "__main__":
    main()
