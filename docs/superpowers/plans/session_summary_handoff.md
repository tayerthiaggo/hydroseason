# Session Handoff Summary

## 1. Issue Diagnosed & Resolved

### Root Cause
During execution of `python scripts/extract_water_extent_csv.py --profile`, processing failed at year 2016 for `fitzroy_river_wa` after 4 hours 40 minutes:
```
rasterio._err.CPLE_AppDefinedError: TIFFFillTile:Read error at row 4294967295, col 4294967295, tile 119; got 0 bytes, expected 1185
rasterio.errors.WarpOperationError: Chunk and warp failed
```
- **Cause**: Transient HTTP/S3 network read failure while fetching Geoscience Australia (DEA) Landsat COGs (`ga_ls_wo_3`) from AWS S3. GDAL's default retry parameters were insufficient for long-running batch extractions.

### Modifications Made

1. **`hydroseason/_io_geo.py`** ([_io_geo.py](file:///d:/RLH/5.6/repos/hydroseason/hydroseason/_io_geo.py#L56-L71))
   - Enhanced `_configure_cog_read_env()` defaults for GDAL S3 HTTP resilience:
     - `GDAL_HTTP_MAX_RETRY`: `5` -> `10`
     - `GDAL_HTTP_RETRY_DELAY`: `1` -> `3`
     - `GDAL_HTTP_RETRY_CODES`: `"429,500,502,503,504,520,522,524"`
     - `GDAL_HTTP_TIMEOUT`: `"30"`
     - `GDAL_HTTP_CONNECTTIMEOUT`: `"15"`

2. **`hydroseason/_io_wofs_acquire.py`** ([_io_wofs_acquire.py](file:///d:/RLH/5.6/repos/hydroseason/hydroseason/_io_wofs_acquire.py#L400-L425))
   - Added a 3-attempt exponential backoff retry loop around `write_annual_group()` in `_process_one_year()`.
   - Prevents transient S3 drops from failing multi-hour catchment extraction jobs.

### Verification
- Ran full test suite for I/O modules:
  ```powershell
  pytest tests/test_io.py tests/test_io_extent_cache.py
  ```
  **Result**: 79 passed, 0 failed.

---

## 2. Extraction Resume & Cache Status

- **Completed Years**: Years 1993 through 2015 (23 years) for `fitzroy_river_wa` were already successfully computed and committed to the local Zarr store (`output/wofs_cache/...`).
- **Resume Behavior**: Re-running the script will detect the `complete.json` markers for years 1993–2015 and automatically resume acquisition from year 2016.

### Next Command to Run
```powershell
python scripts/extract_water_extent_csv.py --profile
```

---

## 3. Performance Architecture Insights (Q&A Summary)

1. **Network Latency (70–80% of total runtime)**:
   - S3 HTTP Range GET round-trips for 18,634 scenes dominate wall-clock time (~50–150ms per request).
   - *Mitigation*: Local Zarr cache (0.6s extraction on 2nd run), `read_workers` parallel requests, spatial STAC item pruning.

2. **Client-Side Reprojection / GDAL Warp (15–20% of runtime)**:
   - DEA S3 COGs are stored in native UTM projections.
   - `odc.stac.load` reprojects raw UTM COGs to EPSG:3577 (Australian Albers) on the local CPU (`rasterio.warp.reproject`).
   - *Necessity*: Required so overlapping satellite scenes across UTM boundaries align on a unified equal-area grid.

3. **Spatial Overlap Fusing (5–10% of runtime)**:
   - In-memory numpy array compositing per solar day across overlapping path boundaries.

4. **Storage-Aligned Spatial Windows (`n_windows`)**:
   - Catchments are chunked into 512x512 pixel windows to cap peak RAM usage.
