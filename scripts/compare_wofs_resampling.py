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

import numpy as np
import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare WOfS resampling policies")
    parser.add_argument("--stac-url", default="https://explorer.sandbox.dea.ga.gov.au/stac")
    parser.add_argument("--collection", default="ga_ls_wo_3")
    parser.add_argument("--aoi", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    import dask
    from odc.geo.geobox import GeoBox
    from odc.geo.crs import CRS
    from affine import Affine
    from hydroseason.io import load_aoi
    from hydroseason._io_geo import _query_wofs_items, build_wofs_year_graph, _all_sources_native_aligned

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
    geobox = GeoBox((height, width), Affine(30.0, 0, x_min, 0, -30.0, y_max), CRS.from_epsg(3577))

    all_aligned = _all_sources_native_aligned(items, geobox, band="water")

    # Build safe graph
    graph_safe_start = time.perf_counter()
    cube_safe = build_wofs_year_graph(
        items, aoi_gdf, start_date, end_date, geobox=geobox, resampling_policy="categorical_safe"
    )
    graph_safe_seconds = time.perf_counter() - graph_safe_start

    # Build aligned graph
    graph_aligned_start = time.perf_counter()
    cube_aligned = build_wofs_year_graph(
        items, aoi_gdf, start_date, end_date, geobox=geobox, resampling_policy="native_aligned"
    )
    graph_aligned_seconds = time.perf_counter() - graph_aligned_start

    # Compute safe
    compute_safe_start = time.perf_counter()
    arr_safe = np.asarray(cube_safe.values)
    compute_safe_seconds = time.perf_counter() - compute_safe_start

    # Compute aligned
    compute_aligned_start = time.perf_counter()
    arr_aligned = np.asarray(cube_aligned.values)
    compute_aligned_seconds = time.perf_counter() - compute_aligned_start

    exact_match = bool(np.array_equal(arr_safe, arr_aligned))
    diff_mask = arr_safe != arr_aligned
    differing_pixels_total = int(diff_mask.sum())
    differing_pixels_per_month = diff_mask.sum(axis=(1, 2)).tolist()

    digest_safe = hashlib.sha256(np.ascontiguousarray(arr_safe).tobytes()).hexdigest()
    digest_aligned = hashlib.sha256(np.ascontiguousarray(arr_aligned).tobytes()).hexdigest()

    results = {
        "year": args.year,
        "item_count": len(items),
        "all_sources_native_aligned": all_aligned,
        "exact_match": exact_match,
        "differing_pixels_total": differing_pixels_total,
        "differing_pixels_per_month": differing_pixels_per_month,
        "digest_categorical_safe": digest_safe,
        "digest_native_aligned": digest_aligned,
        "query_seconds": query_seconds,
        "graph_safe_seconds": graph_safe_seconds,
        "graph_aligned_seconds": graph_aligned_seconds,
        "compute_safe_seconds": compute_safe_seconds,
        "compute_aligned_seconds": compute_aligned_seconds,
    }

    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(results, indent=2), encoding="utf-8")

    return 0 if exact_match else 1


if __name__ == "__main__":
    import math
    sys.exit(main())
