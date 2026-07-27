#!/usr/bin/env python3
"""Materialise native 30m WOfS categorical Zarr caches from STAC."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

import pandas as pd
import xarray as xr

from hydroseason.io import load_wofs_from_stac
from hydroseason._io_wofs_zarr import (
    WOfSCacheIdentity,
    WOfSCacheRequest,
    create_cache_handle,
    WOFS_CACHE_SCHEMA_VERSION,
    WOFS_CLASSIFIER_VERSION,
    WOFS_PLANNER_VERSION,
)
from hydroseason._io_geo import _resolve_raster_transform


def extract_native_zarr(
    aoi_path: str | Path,
    start_date: str,
    end_date: str,
    cache_dir: str | Path,
    stac_url: str = "https://explorer.sandbox.dea.ga.gov.au/stac",
    collection: str = "ga_ls_wo_3",
) -> Path:
    aoi_path = Path(aoi_path)
    cache_dir = Path(cache_dir)
    
    # Compute deterministic hash of the AOI vector file for the request identity
    aoi_hash = hashlib.sha256(aoi_path.read_bytes()).hexdigest()
    
    resolution = 30.0
    crs_str = "EPSG:3577"
    
    req = WOfSCacheRequest(
        stac_url=stac_url,
        collection=collection,
        aoi_sha256=aoi_hash,
        start_date=start_date,
        end_date=end_date,
        crs=crs_str,
        resolution=resolution,
        classifier_version=WOFS_CLASSIFIER_VERSION,
        groupby="solar_day",
        majority=True,
        planner_version=WOFS_PLANNER_VERSION,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    
    # Load from STAC (this performs clipping and temporal reduction)
    print(f"Loading native WOfS data from STAC for {start_date} to {end_date}...")
    da = load_wofs_from_stac(
        stac_url=stac_url,
        collection=collection,
        aoi=aoi_path,
        start_date=start_date,
        end_date=end_date,
        crs=3577,
        resolution=resolution,
    )
    
    transform_obj = _resolve_raster_transform(da)
    transform = (
        transform_obj.c, transform_obj.a, transform_obj.b,
        transform_obj.f, transform_obj.d, transform_obj.e,
    )
    shape = (da.sizes["y"], da.sizes["x"])
    
    identity = WOfSCacheIdentity.from_request(req, shape=shape, transform=transform)
    handle = create_cache_handle(cache_dir, identity)
    
    print(f"Materialising cache to {handle.path}...")
    years = pd.DatetimeIndex(da.time.values).year.unique()
    for year in years:
        da_year = da.sel(time=str(year))
        # Ensure we write a Dataset with a well-known variable name
        ds_year = xr.Dataset({"water": da_year})
        
        # We append/overwrite the specific year group
        import zarr
        group = zarr.open_group(handle.path, mode="a")
        if str(year) in group:
            import shutil
            shutil.rmtree(handle.path / str(year), ignore_errors=True)
            
        ds_year.to_zarr(handle.path, group=str(year), mode="a")
        print(f" - Wrote year {year}")
        
    print(f"Extraction complete.")
    return handle.path


def main():
    parser = argparse.ArgumentParser(description="Extract native WOfS Zarr caches.")
    parser.add_argument("--aoi", required=True, help="Path to AOI vector file")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--cache-dir", required=True, help="Cache directory root")
    parser.add_argument("--stac-url", default="https://explorer.sandbox.dea.ga.gov.au/stac", help="STAC API URL")
    parser.add_argument("--collection", default="ga_ls_wo_3", help="STAC Collection ID")
    
    args = parser.parse_args()
    
    try:
        extract_native_zarr(
            aoi_path=args.aoi,
            start_date=args.start,
            end_date=args.end,
            cache_dir=args.cache_dir,
            stac_url=args.stac_url,
            collection=args.collection,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
