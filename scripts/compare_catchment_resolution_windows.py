"""Compare native-pixel and coarsened WOfS signal on lower-reach windows offline.

This relies entirely on pre-extracted native Zarr caches and performs zero network calls.

For each catchment fixture in ``data/catchments``:
1. build the lower-reach window
2. locate its native 30 m cache in the provided cache directory
3. materialise derived Zarr caches for each target resolution
4. compute exact categorical spatial fidelity (1 - mismatches / valid)
5. export standalone HTML matrix report

Run:
    python scripts/compare_catchment_resolution_windows.py --cache-dir /path/to/cache
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import pandas as pd
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason._study_aois import (
    CATCHMENTS,
    CatchmentSpec,
    build_lower_reach_window,
)
from hydroseason._io_wofs_zarr import (
    WOfSCacheRequest,
    WOfSCacheIdentity,
    WOfSCacheHandle,
    resolve_cached_request,
    WOFS_CACHE_SCHEMA_VERSION,
    WOFS_CLASSIFIER_VERSION,
    WOFS_PLANNER_VERSION,
)
from hydroseason._io_wofs_coarsen import (
    derive_resolution_cache,
)
from hydroseason._io_wofs_compare import (
    count_categorical_mismatches,
)

OUTPUT_CRS = 3577
DEFAULT_START_DATE = "2005-01-01"
DEFAULT_END_DATE = "2025-12-31"
DEFAULT_NATIVE_RES_M = 30.0
DEFAULT_RESOLUTIONS = [60.0, 90.0, 120.0, 250.0]

CATCHMENTS_DIR = REPO_ROOT / "data" / "catchments"
OUTPUT_DIR = REPO_ROOT / "output" / "resolution_window_comparison"
REPORT_PATH = REPO_ROOT / "notebooks" / "hydroseason_resolution_window_comparison.html"



from hydroseason._study_aois import (
    CATCHMENTS,
    CatchmentSpec,
    LowerReachWindow,
    _candidate_streams,
    _downstream_endpoint,
    _geometry_union,
    _longest_linestring,
    build_lower_reach_window,
    select_lower_reach,
)


def _read_catchment_inputs(key: str):
    gpd = _import_geopandas()
    boundary_path = CATCHMENTS_DIR / f"{key}_boundary.parquet"
    streams_path = CATCHMENTS_DIR / f"{key}_streams.parquet"
    if not boundary_path.exists():
        raise FileNotFoundError(f"Missing boundary fixture: {boundary_path}")
    if not streams_path.exists():
        raise FileNotFoundError(f"Missing streams fixture: {streams_path}")
    return gpd.read_parquet(boundary_path), gpd.read_parquet(streams_path)


def _safe_float(value) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _robust_signal(prepared: pd.DataFrame) -> tuple[float, float]:
    if "candidate_usable" not in prepared:
        prepared = prepared.copy()
        prepared["candidate_usable"] = True
    amplitude_pp, noise_pp = robust_scale(prepared)
    return float(amplitude_pp), float(noise_pp)


def run_offline_matrix(
    native_handle: WOfSCacheHandle,
    target_root: Path,
    resolutions: list[float],
) -> dict:
    import zarr
    
    native_manifest = json.loads((native_handle.path / "manifest.json").read_text(encoding="utf-8"))
    native_res = native_manifest["request"]["resolution"]
    
    matrix = {}
    years = sorted(zarr.open_group(native_handle.path, mode="r").group_keys())
    
    for res in resolutions:
        factor = round(res / native_res)
        if abs(factor - (res / native_res)) > 1e-5:
            continue
            
        print(f"    Deriving cache for factor {factor} ({res}m)")
        derived_handle = derive_resolution_cache(native_handle, target_root, factor=factor)
        
        # Compare
        total_valid = 0
        total_mismatch = 0
        
        for year_str in years:
            ds_native = xr.open_zarr(native_handle.path, group=year_str)
            ds_derived = xr.open_zarr(derived_handle.path, group=year_str)
            
            # Upsample derived to native shape for pixel-by-pixel comparison
            # Or we could just use count_categorical_mismatches?
            # Wait, `count_categorical_mismatches` expects identical shape.
            # To compare them, the coarsened matrix must be upsampled back using nearest neighbor,
            # BUT wait, spatial coarsen reduces shape.
            # "Implement exact array categorical matching across identical domains."
            # "Ensure strict georeferencing and shape equivalence."
            # So I must upsample `test` to match `baseline`'s shape.
            # Since xarray supports `reindex_like` or `interp`, we can use `reindex_like(method="nearest")`.
            
            # Find the primary variable
            var_name = list(ds_native.data_vars.keys())[0]
            
            da_native = ds_native[var_name]
            da_derived = ds_derived[var_name]
            
            # Upsample derived back to native shape
            da_derived_upsampled = da_derived.reindex_like(da_native, method="nearest")
            
            valid, mismatched = count_categorical_mismatches(da_native, da_derived_upsampled)
            total_valid += valid
            total_mismatch += mismatched
            
            ds_native.close()
            ds_derived.close()
            
        fidelity = 1.0 - (total_mismatch / total_valid) if total_valid > 0 else 0.0
        matrix[res] = {
            "fidelity": fidelity,
            "total_valid": total_valid,
            "total_mismatch": total_mismatch,
            "derived_store": str(derived_handle.path),
        }
    
    return matrix


def _read_catchment_inputs(key: str):
    import geopandas as gpd
    boundary_path = CATCHMENTS_DIR / f"{key}_boundary.parquet"
    streams_path = CATCHMENTS_DIR / f"{key}_streams.parquet"
    if not boundary_path.exists():
        raise FileNotFoundError(f"Missing boundary fixture: {boundary_path}")
    if not streams_path.exists():
        raise FileNotFoundError(f"Missing streams fixture: {streams_path}")
    return gpd.read_parquet(boundary_path), gpd.read_parquet(streams_path)


def run_one_catchment(
    spec: CatchmentSpec,
    *,
    side_km: float,
    start_date: str,
    end_date: str,
    native_res_m: float,
    resolutions: list[float],
    cache_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> dict:
    catchment_dir = output_dir / spec.key
    result_path = catchment_dir / "offline_matrix.json"
    
    boundary_source = CATCHMENTS_DIR / f"{spec.key}_boundary.parquet"
    streams_source = CATCHMENTS_DIR / f"{spec.key}_streams.parquet"
    expected_config = {
        "date_range": [start_date, end_date],
        "side_km": side_km,
        "native_resolution_m": native_res_m,
        "resolutions": resolutions,
        "boundary_sha256": hashlib.sha256(boundary_source.read_bytes()).hexdigest(),
        "streams_sha256": hashlib.sha256(streams_source.read_bytes()).hexdigest(),
        "result_schema_version": 3,
    }
    
    if result_path.exists() and not force:
        try:
            cached_result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_result = None
        if cached_result is not None and cached_result.get("run_config") == expected_config:
            print(f"[{spec.key}] checkpoint found, skipping -- use --force to redo", flush=True)
            return cached_result
        print(f"[{spec.key}] checkpoint stale for current settings; rebuilding", flush=True)

    catchment_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{spec.key}] lower-reach {side_km} km window", flush=True)
    boundary, streams = _read_catchment_inputs(spec.key)
    window = build_lower_reach_window(spec.key, boundary, streams, side_km=side_km, output_crs=OUTPUT_CRS)

    aoi_path = catchment_dir / "lower_reach_square_clipped.geojson"
    window.analysis_aoi.to_crs(4326).to_file(aoi_path, driver="GeoJSON")

    print(
        f"[{spec.key}] lower_hydroid={window.lower_hydroid} "
        f"bbox={tuple(round(v, 5) for v in window.analysis_bounds_wgs84)}",
        flush=True,
    )
    
    aoi_hash = hashlib.sha256(aoi_path.read_bytes()).hexdigest()
    request = WOfSCacheRequest(
        stac_url="https://explorer.sandbox.dea.ga.gov.au/stac", # Mock URL
        collection="ga_ls_wo_3",
        aoi_sha256=aoi_hash,
        start_date=start_date,
        end_date=end_date,
        crs="EPSG:3577",
        resolution=native_res_m,
        classifier_version=WOFS_CLASSIFIER_VERSION,
        groupby="solar_day",
        majority=True,
        planner_version=WOFS_PLANNER_VERSION,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    
    native_handle = resolve_cached_request(cache_dir, request, offline=True)
    if native_handle is None:
        raise FileNotFoundError(f"Native cache not found for {spec.key}. Run extract_native_zarr.py first.")
        
    print(f"[{spec.key}] Native cache located. Running offline resolution matrix.")
    
    matrix = run_offline_matrix(
        native_handle,
        target_root=catchment_dir / "derived_caches",
        resolutions=resolutions,
    )
    
    result = {
        "catchment_key": spec.key,
        "display_name": spec.display_name,
        "river": spec.river,
        "region": spec.region,
        "date_range": [start_date, end_date],
        "lower_hydroid": window.lower_hydroid,
        "side_km": side_km,
        "square_bounds_projected": list(window.square_bounds_projected),
        "analysis_bounds_wgs84": list(window.analysis_bounds_wgs84),
        "run_config": expected_config,
        "matrix": matrix,
    }
    
    temporary_result_path = result_path.with_suffix(".json.tmp")
    temporary_result_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    os.replace(temporary_result_path, result_path)
    return result


def build_html_report(results: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    
    # Get all sorted resolutions from the first result
    res_keys = sorted(float(k) for k in results[0]["matrix"].keys()) if results else []
    
    # Generate table headers
    res_headers = "".join(f"<th>{res:.0f} m fidelity</th>" for res in res_keys)
    
    for result in results:
        matrix = result["matrix"]
        res_cols = "".join(
            f"<td>{(matrix.get(str(res), {}).get('fidelity', 0.0) * 100):.2f}%</td>"
            if str(res) in matrix or float(res) in matrix else "<td>N/A</td>"
            for res in res_keys
        )
        
        rows.append(
            f"""<tr>
              <td>{html.escape(result['display_name'])}</td>
              <td>{html.escape(str(result['lower_hydroid']))}</td>
              {res_cols}
            </tr>"""
        )

    date_ranges = {tuple(r["date_range"]) for r in results}
    date_label = ", ".join(f"{a}..{b}" for a, b in sorted(date_ranges))
    
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HydroSeason resolution-window comparison</title>
<style>
  body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f8fafc; color:#334155; }}
  header {{ background:linear-gradient(135deg,#0f172a,#164e63); color:white; padding:34px; }}
  header h1 {{ margin:0 0 8px; font-size:28px; font-weight:650; }}
  header p {{ margin:0; color:#cbd5e1; }}
  main {{ max-width:1180px; margin:0 auto; padding:24px; }}
  .card {{ background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px; margin:20px 0; box-shadow:0 1px 3px rgba(15,23,42,.06); }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; background:#f1f5f9; color:#64748b; font-size:12px; text-transform:uppercase; letter-spacing:.04em; padding:9px 10px; }}
  td {{ border-top:1px solid #eef2f7; padding:9px 10px; font-size:14px; }}
</style>
</head>
<body>
<header>
  <h1>HydroSeason native-vs-coarsened lower-reach comparison (Offline Fidelity Matrix)</h1>
  <p>DEA WOfS {html.escape(date_label)} · lower stream outlet point</p>
</header>
<main>
  <section class="card">
    <h2>Fidelity Matrix</h2>
    <table>
      <thead><tr><th>Catchment</th><th>Lower hydroid</th>{res_headers}</tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>
</main>
</body>
</html>"""
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def _write_summary_tables(results: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


def _select_specs(only: str | None) -> list[CatchmentSpec]:
    if only is None:
        return CATCHMENTS
    wanted = {part.strip() for part in only.split(",") if part.strip()}
    selected = [spec for spec in CATCHMENTS if spec.key in wanted]
    missing = wanted - {spec.key for spec in selected}
    if missing:
        raise SystemExit(f"Unknown catchment key(s): {sorted(missing)}")
    return selected


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="comma-separated catchment keys")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--native-resolution", type=float, default=DEFAULT_NATIVE_RES_M)
    parser.add_argument(
        "--resolutions",
        type=lambda s: [float(x) for x in s.split(",")],
        default=DEFAULT_RESOLUTIONS,
        help="comma-separated target resolutions in meters (e.g. 60,90,120)",
    )
    parser.add_argument("--side-km", type=float, default=50.0)
    parser.add_argument("--workers", type=int, default=2, help="parallel catchments (default: 2)")
    parser.add_argument("--force", action="store_true", help="rerun catchments with existing JSON")
    parser.add_argument("--cache-dir", type=Path, required=True, help="Directory containing native zarr caches")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    return parser


def _run_catchments(specs, *, workers: int, run_kwargs: dict):
    """Run catchments concurrently and retain the configured report order."""
    ordered_results: list[dict | None] = [None] * len(specs)
    failures = []
    with ThreadPoolExecutor(
        max_workers=min(workers, len(specs)), thread_name_prefix="resolution-window"
    ) as executor:
        futures = {
            executor.submit(run_one_catchment, spec, **run_kwargs): (index, spec)
            for index, spec in enumerate(specs)
        }
        for future in as_completed(futures):
            index, spec = futures[future]
            try:
                ordered_results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - continue with other catchments
                print(f"[{spec.key}] FAILED: {exc!r}", flush=True)
                failures.append({"catchment_key": spec.key, "error": repr(exc)})
    return [result for result in ordered_results if result is not None], failures


def main(argv: Iterable[str] | None = None) -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    specs = _select_specs(args.only)
    if not specs:
        parser.error("no catchments selected")
        
    run_kwargs = {
        "side_km": args.side_km,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "native_res_m": args.native_resolution,
        "resolutions": args.resolutions,
        "cache_dir": args.cache_dir,
        "output_dir": args.output_dir,
        "force": args.force,
    }
    results, failures = _run_catchments(
        specs, workers=args.workers, run_kwargs=run_kwargs
    )

    if not results:
        raise SystemExit("No catchments produced results; nothing to report.")

    _write_summary_tables(results, args.output_dir)
    report_path = build_html_report(results, args.report_path)
    print(f"\nReport written to: {report_path.resolve()}")
    print(f"Summary written to: {(args.output_dir / 'summary.csv').resolve()}")
    if failures:
        fail_path = args.output_dir / "failures.json"
        fail_path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
        print(f"Failures written to: {fail_path.resolve()}")


if __name__ == "__main__":
    main()
