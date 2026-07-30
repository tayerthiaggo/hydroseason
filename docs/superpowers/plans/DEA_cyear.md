# WOfS Spatial Pruning via DEA Water Observation Statistics (Annual Mask > 0%)

Accelerate `hydroseason` WOfS raster extraction by pre-fetching pre-computed annual water frequency statistics (`ga_ls_wo_fq_cyear_3` / `ga_ls_wo_fq_myear_3`) from DEA STAC to build a spatial wet mask (`water summary > 0%`) before fetching daily observation scenes. This prunes dry tiles prior to Dask graph generation, reducing downloaded spatial area and processing time.

## User Review Required

> [!IMPORTANT]
> - Uses DEA Water Observation Statistics annual product (`ga_ls_wo_fq_cyear_3`) to discover everywhere water occurred (`frequency > 0` or `count_wet > 0`).
> - Prunes dry spatial tiles *before* building daily observation Dask graphs (`ga_ls_wo_3`), eliminating reads over dry land.
> - Falls back gracefully to standard full-AOI tile plan if DEA statistics STAC collection is unavailable or unreachable.

## Proposed Changes

### `hydroseason` Core Package

---

#### [MODIFY] `hydroseason/_io_geo.py`
- Add `fetch_dea_stats_wet_aoi(...)` function to query `ga_ls_wo_fq_cyear_3` (or `ga_ls_wo_fq_myear_3`) via STAC for target years and AOI.
- Load `frequency` or `count_wet` band, identify pixels with `water summary > 0%` (`count_wet > 0`), and convert to buffered wet AOI polygon via `wet_aoi_polygon`.

---

#### [MODIFY] `hydroseason/_io_wofs_acquire.py`
- Update `acquire_wofs_cache(...)` to attempt pre-fetching wet AOI from DEA Water Observation Statistics if `wet_aoi` parameter is not explicitly passed.
- Pass pre-computed `wet_aoi` into `build_wofs_year_graph(...)` and spatial tile planner to prune dry tiles across all annual Dask graphs before data loading.

---

#### [MODIFY] `hydroseason/_wet_aoi.py`
- Add helper `wet_aoi_from_summary_raster(...)` to construct vector wet AOI directly from 2D summary raster (`frequency > 0` / `count_wet > 0`).

---

#### [MODIFY] `scripts/extract_water_extent_csv.py`
- Add `--use-dea-stats-mask` flag (default True) to enable pre-masking wet AOI from DEA statistics in batch extraction script.

## Verification Plan

### Automated Tests
- Unit test in `tests/test_io_geo.py` mocking DEA STAC response for `ga_ls_wo_fq_cyear_3` and confirming wet AOI polygon generation.
- Integration test in `tests/test_io_wofs_acquire.py` verifying spatial tile planner prunes dry tiles when pre-computed `wet_aoi` is supplied.
- Run `pytest tests/` to ensure no regressions.

### Manual Verification
- Test `scripts/extract_water_extent_csv.py` on test catchments (e.g. `lachlan_river_nsw`) to compare tile count and execution speed before vs after stats pre-masking.
