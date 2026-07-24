# Usage guide

## Canonical mask shape

Every raster loader converges on the same canonical values before detection
ever sees the data (`time`/`y`/`x`, `int8`):

| Value | Meaning |
|---:|---|
| `1` | water |
| `0` | dry |
| `-1` | invalid (cloud, shadow, no-data, out-of-domain code) |
| `-2` | outside AOI |

`monthly_water_extent` summarises a canonical cube into a monthly
`extent_pct`/`invalid_pct` DataFrame — `n_valid` only counts pixels explicitly
equal to `0` or `1`; anything else (unknown codes, `NaN`, values that bypassed
a classifier) counts as invalid rather than silently inflating the valid
denominator or reading as dry.

## AOI is required for raster/STAC input

`load_monthly_masks` and `load_wofs_from_stac` both require an AOI
(`aoi=`, a vector path or `geopandas.GeoDataFrame`, validated by `load_aoi`).
If AOI clipping or rasterization fails, the loader raises rather than
processing an unclipped raster. `load_monthly_masks_zarr` has no AOI
parameter — it assumes the Zarr cube is already canonical and AOI-clipped.
CSV extent input has no AOI parameter either: extent values are assumed to
already belong to a known AOI computed upstream.

## Gapfill before detecting

Water-mask gaps, cloud/shadow contamination, and missing months can shift the
wet/dry boundaries `detect_hydrological_years` finds. **Strongly run
WaterMask-TSFill gapfilling on raw/incomplete masks before running hydro-year
detection.** `detect_hydrological_years` still rejects (by default) any month
with more than `max_invalid_pct=20.0`% invalid coverage, and duplicate or
missing months raise unless you opt into a permissive policy — but that guard
is a safety net, not a substitute for gapfilling. `load_extent_csv` does not
gapfill or quality-screen; a CSV path is only safe input when the upstream
extent series has already been completed and quality-screened.

## Path 1: extent CSV

The lightweight path — no raster dependencies. Use it if you already have a
completed, quality-screened monthly extent series (e.g. computed elsewhere,
or exported from WaterMask-TSFill).

```python
from hydroseason import load_extent_csv, detect_hydrological_years, label_hydrological_months

extent = load_extent_csv("monthly_extent.csv", date_col="date", value_col="extent_pct")
hydro_years = detect_hydrological_years(extent)
labels = label_hydrological_months(extent.index, hydro_years)
```

The CSV needs a date column and a value column (names configurable via
`date_col`/`value_col`); an optional `invalid_pct` column, if present, is
honoured by `detect_hydrological_years`.

## Path 2: generic water-mask rasters

Requires `pip install hydroseason[raster]`. Loads `water_*.tif`-style files
from a directory (`load_monthly_masks`) or an already-canonical Zarr cube
(`load_monthly_masks_zarr`), clips to the AOI, and returns a lazy,
Dask-backed `xarray.DataArray` — no raster is fully materialized until
`monthly_water_extent` computes its small monthly summaries.

`load_monthly_masks` requires an explicit `encoding` (or a `classifier=`
callable) — it never guesses WOfS-vs-binary from dtype:

```python
from hydroseason import load_monthly_masks, monthly_water_extent, detect_hydrological_years

masks = load_monthly_masks(
    "masks/", "2015-01-01", "2020-12-31",
    aoi="aoi.geojson", encoding="binary",  # or "canonical", or classifier=my_fn
)
extent = monthly_water_extent(masks)
hydro_years = detect_hydrological_years(extent)
```

### Canonical local WOfS cache

The extraction CLI uses the internal canonical mask cache at
`output/wofs_cache` by default. It is not a public Zarr-input mode; use the
loader APIs above for supported inputs. A request's cache identity covers its
AOI content, date range, CRS, resolution, source, and cache schema settings,
so incompatible requests never share a store.

```powershell
python scripts\extract_water_extent_csv.py --aoi data\Gilbert_river_buffer.geojson --resolution 30
python scripts\extract_water_extent_csv.py --aoi data\Gilbert_river_buffer.geojson --resolution 30 --offline
python scripts\extract_water_extent_csv.py --aoi data\Gilbert_river_buffer.geojson --resolution 30 --legacy-remote-path
```

Acquisition records completion one calendar year at a time. An interrupted
run resumes completed annual groups, while a concurrent writer for the same
store is rejected. `--offline` makes no STAC request: a missing matching cache
is reported explicitly. `--legacy-remote-path` opts out of the canonical cache
for direct STAC loading.

### Opt-in WOfS cache benchmark

The real DEA/STAC cache benchmark is intentionally excluded from normal test
runs because it is network and wall-clock dependent. It compares the current
tiled remote path against a cold canonical cache for the Gilbert and Fitzroy
2015 AOIs, then verifies Gilbert offline cache reads. It writes raw runs,
medians, output digests, cache/read diagnostics, memory when available, and
GDAL `VSI_CACHE` A/B results to JSON.

```powershell
$env:HYDROSEASON_RUN_WOFS_PERF = "1"
python -m pytest tests\test_wofs_cache_performance.py -m "network and performance" -v
```

For an investigation without pytest, run
`python scripts\benchmark_wofs_cache.py --output output\wofs_cache_benchmark.json --runs 3`.
The 20% Gilbert cold-cache, 10% Fitzroy cold-cache-regression, 80% Gilbert
offline-cache, exact-output, and zero-offline-STAC-call checks are hard gates;
the 35% target and 40% stretch results are recorded but do not fail a passing
hard gate.

For a pre-built canonical Zarr cube (already AOI-clipped):

```python
from hydroseason import load_monthly_masks_zarr, monthly_water_extent

masks = load_monthly_masks_zarr("masks.zarr", "2015-01-01", "2020-12-31")
extent = monthly_water_extent(masks)
```

## Path 3: WOfS / STAC

Requires `pip install hydroseason[stac]`. Queries a STAC catalog, groups
items by month, classifies WOfS pixel flags, and clips to the AOI — lazy and
Dask-backed end to end.

For long-running analyses, use the resumable loader below. It batches STAC
reads by calendar year, aligns Dask computation to 12-month chunks, and caches
the small extent table so reruns resume from completed years.

```python
from hydroseason import load_wofs_monthly_extent, detect_hydrological_years

extent = load_wofs_monthly_extent(
    stac_url="<your-stac-catalog-url>",
    collection="<wofs-collection-id>",
    aoi="aoi.geojson",
    start_date="2015-01-01",
    end_date="2020-12-31",
    cache_dir="output/extent_cache/my_aoi",
    time_block=12,
)
hydro_years = detect_hydrological_years(extent)
```

## Detection configuration

`HydroYearConfig` controls the wet/dry search windows and confidence
thresholds. The default assumes a cross-year wet season and a same-year dry
season (`wet_start_month=11`, `wet_end_month=4`, `dry_start_month=7`,
`dry_end_month=12`); unsupported window geometry (non-cross-year wet season,
cross-year dry season, or a dry season that doesn't follow the wet season)
fails fast at config construction, rather than producing a wrong answer.

```python
from hydroseason import HydroYearConfig, detect_hydrological_years

config = HydroYearConfig(wet_start_month=10, wet_end_month=3, dry_start_month=6, dry_end_month=9)
hydro_years = detect_hydrological_years(extent, config=config)
```

Duplicate and missing months raise by default
(`duplicate_month_policy="raise"`, `missing_month_policy="raise"`); pass
`"warn"` (duplicates) or `"ignore"` (missing months) only if you have
deliberately chosen a permissive policy.

## Not in this release

The detection core and loaders above are the whole current public surface.
Not yet built (tracked as follow-up work, not silently missing):

- a config-driven pipeline/orchestration layer connecting a source straight
  through to a validated, reported output;
- an HTML report for the new water-extent data model (the previous
  rainfall-based report lives, unmodified, on `legacy/rainfall`, as a design
  reference for a future rebuild);
- a water-mask-equivalent validation module.

## Legacy rainfall implementation

The rainfall-based season/hydro-year detection that shipped in `0.1.0`
(fetchers for CHIRPS/SILO/ERA5/BoM, the rainfall pipeline, CLI, and HTML
report) is preserved, unmodified, on the `legacy/rainfall` branch (tag
`v0-rainfall-legacy`). It is not maintained on `main` going forward.
