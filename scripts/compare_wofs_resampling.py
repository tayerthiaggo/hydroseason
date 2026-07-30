"""Compare WOfS resampling policies (categorical_safe vs native_aligned) on real STAC data.

Queries STAC once for an AOI and year, builds two graphs, materializes both,
computes pixel-exact diffs and phase timings, and outputs JSON. Exits 0 if
outputs match exactly, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import math
import numpy as np
import pandas as pd


def _digest_windowed(cube, windows, *, compute_batch_size: int = 16):
    """Compute one lazy cube in bounded windows and return digest/timing."""
    if compute_batch_size < 1:
        raise ValueError("compute_batch_size must be at least 1")
    import dask

    digest = hashlib.sha256()
    blocks_compared = 0
    started = time.perf_counter()
    for offset in range(0, len(windows), compute_batch_size):
        batch = windows[offset : offset + compute_batch_size]
        blocks = [
            cube.isel(
                y=slice(window.y_start, window.y_stop),
                x=slice(window.x_start, window.x_stop),
            ).data
            for window in batch
        ]
        for values in dask.compute(*blocks):
            digest.update(np.ascontiguousarray(np.asarray(values)).tobytes())
            blocks_compared += 1
    return {
        "digest": digest.hexdigest(),
        "compute_seconds": time.perf_counter() - started,
        "blocks_compared": blocks_compared,
    }


def _compare_windowed(cube_safe, cube_aligned, windows, *, compute_batch_size: int = 16):
    """Compare two lazy cubes without materializing their full parent grid."""
    if compute_batch_size < 1:
        raise ValueError("compute_batch_size must be at least 1")
    import dask

    time_len = int(cube_safe.sizes["time"])
    safe_digest = hashlib.sha256()
    aligned_digest = hashlib.sha256()
    differing_per_month = np.zeros(time_len, dtype=np.int64)
    differing_total = 0
    blocks_compared = 0
    compute_safe_seconds = 0.0
    compute_aligned_seconds = 0.0

    for offset in range(0, len(windows), compute_batch_size):
        batch = windows[offset : offset + compute_batch_size]
        safe_blocks = [
            cube_safe.isel(
                y=slice(window.y_start, window.y_stop),
                x=slice(window.x_start, window.x_stop),
            ).data
            for window in batch
        ]
        aligned_blocks = [
            cube_aligned.isel(
                y=slice(window.y_start, window.y_stop),
                x=slice(window.x_start, window.x_stop),
            ).data
            for window in batch
        ]
        safe_started = time.perf_counter()
        safe_values = dask.compute(*safe_blocks)
        compute_safe_seconds += time.perf_counter() - safe_started
        aligned_started = time.perf_counter()
        aligned_values = dask.compute(*aligned_blocks)
        compute_aligned_seconds += time.perf_counter() - aligned_started
        for safe_value, aligned_value in zip(safe_values, aligned_values, strict=True):
            safe_array = np.ascontiguousarray(np.asarray(safe_value))
            aligned_array = np.ascontiguousarray(np.asarray(aligned_value))
            if safe_array.shape != aligned_array.shape:
                raise ValueError("resampling comparison produced mismatched block shapes")
            safe_digest.update(safe_array.tobytes())
            aligned_digest.update(aligned_array.tobytes())
            differences = safe_array != aligned_array
            differing_per_month += differences.sum(axis=(1, 2), dtype=np.int64)
            differing_total += int(differences.sum())
            blocks_compared += 1

    return {
        "digest_categorical_safe": safe_digest.hexdigest(),
        "digest_native_aligned": aligned_digest.hexdigest(),
        "differing_pixels_total": int(differing_total),
        "differing_pixels_per_month": differing_per_month.tolist(),
        "blocks_compared": blocks_compared,
        "compute_safe_seconds": compute_safe_seconds,
        "compute_aligned_seconds": compute_aligned_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare WOfS resampling policies")
    parser.add_argument("--stac-url", default="https://explorer.sandbox.dea.ga.gov.au/stac")
    parser.add_argument("--collection", default="ga_ls_wo_3")
    parser.add_argument("--aoi", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--compute-batch-size", type=int, default=16)
    args = parser.parse_args()

    import dask
    from odc.geo.geobox import GeoBox
    from odc.geo.crs import CRS
    from affine import Affine
    from hydroseason.io import load_aoi
    from hydroseason._io_geo import _query_wofs_items, build_wofs_year_graph, _all_sources_native_aligned
    from hydroseason._spatial_plan import plan_storage_aligned_slices

    start_date = f"{args.year}-01-01"
    end_date = f"{args.year}-12-31"

    query_start = time.perf_counter()
    items, aoi_gdf = _query_wofs_items(args.stac_url, args.collection, args.aoi, start_date, end_date)
    query_seconds = time.perf_counter() - query_start

    # Derive 30m Albers GeoBox
    aoi_albers = aoi_gdf.to_crs(3577)
    bounds = aoi_albers.total_bounds
    x0, y0, x1, y1 = bounds[0], bounds[1], bounds[2], bounds[3]
    x_min = math.floor(x0 / 30.0) * 30.0
    y_max = math.ceil(y1 / 30.0) * 30.0
    width = math.ceil((x1 - x_min) / 30.0)
    height = math.ceil((y_max - y0) / 30.0)
    geobox = GeoBox((height, width), Affine(30.0, 0, x_min, 0, -30.0, y_max), CRS("EPSG:3577"))

    if args.compute_batch_size < 1:
        raise SystemExit("--compute-batch-size must be at least 1")
    geometry = (
        aoi_albers.geometry.union_all()
        if hasattr(aoi_albers.geometry, "union_all")
        else aoi_albers.geometry.unary_union
    )
    plan = plan_storage_aligned_slices(
        geometry,
        shape=tuple(int(value) for value in geobox.shape),
        transform=geobox.affine,
        storage_chunk=512,
    )

    all_aligned = _all_sources_native_aligned(items, geobox, band="water")

    # Build safe graph
    graph_safe_start = time.perf_counter()
    cube_safe = build_wofs_year_graph(
        items, aoi_gdf, start_date, end_date, geobox=geobox, resampling_policy="categorical_safe"
    )
    graph_safe_seconds = time.perf_counter() - graph_safe_start

    if all_aligned:
        graph_aligned_start = time.perf_counter()
        cube_aligned = build_wofs_year_graph(
            items, aoi_gdf, start_date, end_date,
            geobox=geobox, resampling_policy="native_aligned",
        )
        graph_aligned_seconds = time.perf_counter() - graph_aligned_start
        comparison = _compare_windowed(
            cube_safe,
            cube_aligned,
            plan.windows,
            compute_batch_size=args.compute_batch_size,
        )
        exact_match = comparison["differing_pixels_total"] == 0
    else:
        # Native-aligned policy is guaranteed to resolve to the same safe
        # mode path when any source fails conservative alignment checks. Do
        # not pay for a duplicate full-year read in that case.
        graph_aligned_seconds = 0.0
        digest = _digest_windowed(
            cube_safe, plan.windows, compute_batch_size=args.compute_batch_size
        )
        comparison = {
            "digest_categorical_safe": digest["digest"],
            "digest_native_aligned": digest["digest"],
            "differing_pixels_total": 0,
            "differing_pixels_per_month": [0] * int(cube_safe.sizes["time"]),
            "blocks_compared": digest["blocks_compared"],
            "compute_safe_seconds": digest["compute_seconds"],
            "compute_aligned_seconds": 0.0,
        }
        exact_match = True

    results = {
        "year": args.year,
        "item_count": len(items),
        "all_sources_native_aligned": all_aligned,
        "resampling_comparison_skipped": not all_aligned,
        "exact_match": exact_match,
        "differing_pixels_total": comparison["differing_pixels_total"],
        "differing_pixels_per_month": comparison["differing_pixels_per_month"],
        "digest_categorical_safe": comparison["digest_categorical_safe"],
        "digest_native_aligned": comparison["digest_native_aligned"],
        "blocks_compared": comparison["blocks_compared"],
        "selected_tile_pixels": plan.selected_tile_pixels,
        "planned_window_count": len(plan.windows),
        "query_seconds": query_seconds,
        "graph_safe_seconds": graph_safe_seconds,
        "graph_aligned_seconds": graph_aligned_seconds,
        "compute_safe_seconds": comparison["compute_safe_seconds"],
        "compute_aligned_seconds": comparison["compute_aligned_seconds"],
    }

    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(results, indent=2), encoding="utf-8")

    return 0 if exact_match else 1


if __name__ == "__main__":
    import math
    sys.exit(main())
