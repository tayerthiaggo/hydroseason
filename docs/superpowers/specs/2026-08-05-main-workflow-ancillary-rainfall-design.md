# Main Workflow Orchestrator and Ancillary Rainfall Design

**Date:** 2026-08-05
**Status:** approved design
**Scope:** one public HydroSeason orchestrator, local/DEA water-input dispatch, optional supplied/SILO rainfall context, and rainfall-aware CSV/HTML reporting

## Problem

HydroSeason currently exposes the pieces of its main workflow separately:

1. load or fetch monthly surface-water extent;
2. call `analyze_catchment`;
3. optionally prepare rainfall outside the public package surface; and
4. call `generate_catchment_report`.

The report layer already accepts an optional rainfall frame, aligns it by
month, adds `rainfall_mm` and `rain_anomaly_mm` to the monthly export, and
plots rainfall on the timeline. Internal modules also fetch catchment-mean
monthly SILO rainfall and compare extent and rainfall regimes. However, no
public orchestrator connects these capabilities, rainfall fetching is not a
supported user-facing workflow option, and the current HTML report does not
show the full rainfall-regime comparison.

Users need one call that accepts common local water inputs or fetches DEA
WOfS, performs the existing water-only analysis, optionally adds rainfall as
ancillary context, and writes the complete report bundle.

## Goals

1. Add a public `run_hydroseason` orchestrator that writes the normal report
   bundle and returns reusable in-memory results.
2. Accept precomputed monthly extent from CSV/DataFrame and canonical monthly
   water-mask cubes from NetCDF, Zarr, `xarray.Dataset`, or
   `xarray.DataArray`.
3. Treat `water_source=None` as an explicit request to fetch DEA WOfS using
   the existing cached monthly-extent path.
4. Keep rainfall off by default.
5. Accept a user-supplied monthly rainfall CSV or fetch SILO when
   `fetch_rainfall=True`.
6. Keep every rainfall load, assessment, comparison, and presentation step
   ancillary: it must never alter the water regime, route, hydrological-year
   boundaries, phases, wet events, or low-extent spells.
7. When rainfall is available, enrich the monthly CSV and add a collapsible,
   interpretable rainfall context section to the HTML report.
8. Make rainfall failures non-fatal while retaining explicit status, error,
   and warning information.

## Non-goals

- Rainfall-driven routing, season detection, hydrological-year detection,
  phase labels, event detection, or boundary adjustment.
- Restoring the legacy rainfall-first pipeline or its public APIs.
- Supporting arbitrary climate providers in the first orchestrator version;
  automatic rainfall fetching is SILO-only.
- Supporting GeoTIFF directories in the first orchestrator version. Existing
  lower-level raster loaders remain available.
- Adding a standalone rainfall CSV.
- Adding rainfall-derived fields to hydrological-year, wet-event, or
  low-spell CSVs.
- Treating agreement between rainfall and extent as proof of causality.

## Public API

Add the following top-level API:

```python
def run_hydroseason(
    water_source=None,
    *,
    output_dir: str | Path,
    aoi=None,
    aoi_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    water_mask_variable: str | None = None,
    fetch_rainfall: bool = False,
    rainfall_csv_path: str | Path | None = None,
    stac_url: str = "https://explorer.dea.ga.gov.au/stac",
    stac_collection: str = "ga_ls_wo_3",
    cache_dir: str | Path | None = None,
    analysis_options: Mapping[str, Any] | None = None,
    report_title: str | None = None,
    report_subtitle: str | None = None,
) -> HydroSeasonRunResult:
    ...
```

Parameter meanings:

| Parameter | Meaning |
|---|---|
| `water_source` | Extent CSV/DataFrame, canonical NetCDF/Zarr/Dataset/DataArray mask cube, or `None` for DEA WOfS fetch |
| `output_dir` | Required destination for HTML and CSV artifacts |
| `aoi` | Vector path or GeoDataFrame used by DEA and SILO fetching |
| `aoi_name` | Human-readable AOI/report name; independent of the geometry source |
| `start_date`, `end_date` | Required for DEA fetch; optional local-data bounds |
| `water_mask_variable` | Dataset variable containing the canonical water mask; unused for a DataArray or extent frame |
| `fetch_rainfall` | When true and no rainfall CSV is supplied, fetch SILO rainfall |
| `rainfall_csv_path` | Optional supplied monthly rainfall with `date` and `rainfall_mm`; takes precedence over SILO fetching |
| `stac_url`, `stac_collection` | DEA source overrides with production defaults |
| `cache_dir` | Cache root forwarded to the existing DEA monthly-extent loader |
| `analysis_options` | Options forwarded unchanged to `analyze_catchment`; defaults to `{}` |
| `report_title`, `report_subtitle` | Optional presentation copy passed to the report layer |

Examples:

```python
# Fetch DEA water extent and SILO rainfall.
result = run_hydroseason(
    output_dir="output/fitzroy",
    aoi="fitzroy.geojson",
    aoi_name="Fitzroy River",
    start_date="2005-01-01",
    end_date="2025-12-01",
    fetch_rainfall=True,
)

# Analyze a local canonical Zarr cube with supplied rainfall.
result = run_hydroseason(
    "water_masks.zarr",
    output_dir="output/local-aoi",
    aoi_name="Local AOI",
    water_mask_variable="water_mask",
    rainfall_csv_path="monthly_rainfall.csv",
)
```

### Return type

```python
@dataclass(frozen=True)
class HydroSeasonRunResult:
    extent: pd.DataFrame
    analysis: CatchmentAnalysis
    rainfall: pd.DataFrame | None
    rainfall_comparison: RegimeComparison | None
    rainfall_status: RainfallStatus
    rainfall_source: Literal["none", "csv", "silo"]
    rainfall_error: str | None
    rainfall_comparison_error: str | None
    source_kind: WaterSourceKind
    warnings: tuple[str, ...]
    artifacts: CatchmentReportPaths
```

`RainfallStatus` is one of:

- `disabled`: no CSV and `fetch_rainfall=False`;
- `provided`: supplied CSV loaded successfully;
- `fetched`: SILO rainfall fetched successfully;
- `provided_failed`: supplied CSV could not be loaded or normalized;
- `fetch_failed`: SILO could not be fetched or normalized.

If rainfall loads successfully but its record is too short for a regime
verdict, load status remains `provided` or `fetched`. The
`RegimeComparison.divergence` value records `rainfall_insufficient`.
If rainfall loads successfully but comparison itself fails, load status also
remains `provided` or `fetched`; `rainfall_comparison_error` records the
failure while the rainfall values remain available to CSV and timeline
output.

## Architecture and module boundaries

### `hydroseason/workflow.py`

Owns the public orchestration contract and `HydroSeasonRunResult`. It composes
existing loading, analysis, rainfall, comparison, and reporting functions. It
does not implement detection science, source-specific parsing, SILO I/O, or
HTML rendering.

### `hydroseason/_workflow_input.py`

Owns water-input type dispatch and normalization into a monthly
`extent_pct`/`invalid_pct` frame. This keeps source inspection and optional
xarray imports out of the orchestrator.

### `hydroseason/_rainfall.py`

Retains SILO fetching and owns strict parsing/normalization of a supplied
monthly rainfall CSV. Its normalized output has a month-start DatetimeIndex
and one numeric `rainfall_mm` column.

### `hydroseason/_regime_compare.py`

Retains comparison interpretation. Add a comparison path that consumes the
already-authoritative `analysis.regime` and assesses only rainfall. The
existing convenience function that assesses both series remains compatible,
but `run_hydroseason` must not use it to recompute the extent assessment.

### Report modules

Existing report/export code receives the normalized rainfall frame plus the
comparison and provenance. The report layer presents those objects but does
not fetch rainfall or run either regime assessment.

## Water-input resolution

The orchestrator resolves `water_source` as follows:

| Input | Resolution path |
|---|---|
| `None` | Call `load_wofs_monthly_extent`; require `aoi`, `start_date`, and `end_date` |
| CSV path | Call `load_extent_csv`; require `date` and `extent_pct` |
| `pandas.DataFrame` | Treat as precomputed extent; require `extent_pct` and a date index or `date` column |
| NetCDF path | Lazily open with xarray, select one canonical mask variable, then summarize |
| Zarr path | Lazily open with xarray, select one canonical mask variable, then summarize |
| `xarray.Dataset` | Select one canonical mask variable, then summarize |
| `xarray.DataArray` | Treat directly as the canonical mask cube, then summarize |

Dataset variable selection is deterministic:

1. use `water_mask_variable` when supplied;
2. otherwise use `water_mask` when present;
3. otherwise use the only data variable when exactly one exists;
4. otherwise raise an actionable ambiguity error listing available variables.

Canonical mask inputs must contain dimensions `time`, `y`, and `x` and use
the package values water `1`, dry `0`, invalid `-1`, and outside AOI `-2`.
The resolver validates dimensions and value-domain compatibility before
summary. It applies optional local start/end bounds, completes the monthly
axis with the package's invalid-month convention, and calls
`monthly_water_extent` exactly once.

When local dates are omitted, the resolver uses the source's first and last
months. If only one local bound is supplied, the other is inferred from the
source. `source_kind` records `dea_wofs`, `extent_csv`, `extent_dataframe`,
`netcdf_mask`, `zarr_mask`, `xarray_dataset`, or `xarray_dataarray`.

CSV/DataFrame input is available from the core install. NetCDF, Zarr,
Dataset, DataArray, and SILO paths require the `raster` extra. DEA fetching
requires the `stac` extra. Missing dependencies on the selected water path
are fatal; missing dependencies on the rainfall path are non-fatal.

## Authoritative data flow

```text
water_source
    |
    v
resolve monthly water extent
    |
    v
analyze_catchment(extent, **analysis_options)  <-- sole routing authority
    |
    +------------------------------+
    |                              |
    v                              v
resolve ancillary rainfall     water-only analysis remains frozen
    |
    v
assess rainfall regime only
    |
    v
compare against analysis.regime
    |
    v
generate CSV/HTML with optional context
    |
    v
HydroSeasonRunResult
```

`analyze_catchment` receives no rainfall parameter and requires no code
change. Once it returns, its regime, route, hydrological years, state, phases,
events, and low spells are never mutated or recomputed.

## Rainfall resolution and alignment

Rainfall source precedence is exact:

1. If `rainfall_csv_path` is supplied, load it and do not fetch SILO, even
   when `fetch_rainfall=True`.
2. Else if `fetch_rainfall=True`, fetch SILO for the AOI and calendar years
   covered by the resolved extent frame.
3. Else rainfall is disabled.

A supplied rainfall CSV must contain:

- `date`, parseable as a calendar date; and
- `rainfall_mm`, numeric monthly rainfall.

Dates normalize to month starts. Duplicate months are invalid rather than
silently aggregated. Rainfall is clipped to the resolved extent period and
left-aligned onto extent months. Missing rainfall months remain `NaN`; they
do not remove water observations. Rain anomaly is defined as:

```text
rain_anomaly_mm = rainfall_mm - median(rainfall_mm for the same calendar month)
```

SILO fetching uses the existing lazy catchment-mean monthly fetcher. For a
local water source, `aoi` is optional unless SILO fetching is requested. If
SILO is requested without an AOI, water analysis proceeds and rainfall ends
with `fetch_failed` plus an actionable warning.

## Rainfall regime comparison

When normalized rainfall is present, assess it independently using the same
regime diagnostic algorithm and compatible record-length settings used for
water. The extent side of `RegimeComparison` is the exact
`analysis.regime` object returned by the authoritative water analysis.

Comparison outputs include:

- rainfall regime;
- rainfall amplitude SNR;
- extent amplitude SNR from `analysis.regime`;
- rainfall and extent climatological peak/trough months when supported;
- circular signed peak lag from rainfall peak to extent peak;
- divergence key (`agree`, `extent_damped`, `extent_more_seasonal`,
  `partial`, or an insufficient-record state); and
- cautious plain-language interpretation.

Comparison text may state that a pattern is consistent with a hypothesis. It
must not claim rainfall causation, regulation, extraction, or storage without
external evidence.

## CSV output

The existing report CSV bundle remains stable. When normalized rainfall is
present, append these columns to `*_monthly.csv`:

| Column | Definition |
|---|---|
| `rainfall_mm` | Supplied or SILO monthly rainfall aligned by month |
| `rain_anomaly_mm` | Deviation from that calendar month's record median |

When rainfall is absent or fails, omit both columns. Do not add a standalone
rainfall file. Do not add rainfall columns to hydrological-year, wet-event,
or low-spell CSVs; doing so could imply those outputs used rainfall.

Comparison-level values remain available in `HydroSeasonRunResult` and the
HTML report rather than being denormalized onto every monthly CSV row.

## HTML rainfall context

When rainfall is present, retain the existing raw monthly rainfall trace on
the timeline's secondary axis and add a collapsed `<details>` section titled
according to provenance:

- `Rainfall context (SILO)`; or
- `Rainfall context (supplied CSV)`.

The section follows the presentation pattern in
`docs/artifacts/automated-catchment-workflow.html` and contains:

1. a comparison/divergence badge;
2. a paired 12-month climatology figure with rainfall bars and an extent
   line;
3. rainfall regime;
4. comparison label and cautious interpretation;
5. extent SNR;
6. rainfall SNR;
7. rainfall and extent peak/trough months where defined; and
8. circular peak lag where defined.

The rainfall panel is contextual and appears below the primary route-aware
water story. It never replaces the report verdict, KPIs, timeline, or
route-specific supporting view.

When rainfall is disabled, omit rainfall columns, traces, and the entire
context section. When rainfall loading fails, omit the context visualization
and add a concise report warning that rainfall context was unavailable while
the water analysis completed successfully. When rainfall loads but comparison
fails, retain its CSV columns, timeline trace, and climatology; show comparison
statistics as unavailable and include a concise comparison warning.

## Error handling

Fatal water/workflow errors:

- unsupported `water_source` type or path;
- missing `aoi`, `start_date`, or `end_date` for DEA fetching;
- ambiguous or missing Dataset variable;
- invalid canonical mask dimensions or values;
- malformed extent CSV/DataFrame;
- selected water-path dependency failure;
- water loading, analysis, CSV writing, or HTML writing failure.

Non-fatal ancillary errors:

- missing AOI for SILO with a local water source;
- missing rainfall-path dependency;
- missing, malformed, duplicate-month, or nonnumeric rainfall CSV;
- SILO network, object-store, NetCDF, geometry, or coverage failure;
- rainfall regime assessment or comparison failure.

Ancillary exceptions are caught after water analysis. For load/fetch failures,
the orchestrator emits a Python warning, appends the message to
`HydroSeasonRunResult.warnings`, sets the specific failure status and
`rainfall_error`, and generates a valid water-only artifact bundle. For a
comparison-only failure, it retains normalized rainfall, sets
`rainfall_comparison_error`, warns, and generates rainfall-enriched artifacts
without comparison metrics. It does not catch `KeyboardInterrupt` or
`SystemExit`.

## Testing strategy

### Water resolver unit tests

- CSV path and in-memory DataFrame resolve to equivalent monthly extent.
- NetCDF, Zarr, Dataset, and DataArray fixtures resolve to equivalent monthly
  extent.
- Dataset variable selection follows the documented priority.
- Ambiguous variables, missing dimensions, invalid codes, and missing DEA
  arguments fail with actionable messages.
- Local date bounds subset and complete the monthly axis correctly.

### Rainfall unit tests

- CSV parsing normalizes month starts and numeric values.
- Duplicate months and malformed columns fail inside the ancillary boundary.
- Supplied CSV takes precedence over `fetch_rainfall=True`.
- SILO fetch uses extent years and the supplied AOI.
- Missing months remain `NaN` after alignment.
- Rain anomaly uses the same-calendar-month median.
- Comparison uses the exact `analysis.regime` object and computes circular
  peak lag correctly.

### Orchestrator tests

- Default invocation with local extent writes a water-only bundle.
- Supplied rainfall enriches monthly CSV and HTML without network access.
- Mocked SILO fetching enriches the same outputs.
- Mocked SILO failure is non-fatal and still writes every water artifact.
- Before/after equality checks prove rainfall on versus off leaves route,
  hydrological-year rows, state/phase frames, event rows, low-spell rows, and
  water-regime diagnostics unchanged.
- `HydroSeasonRunResult` records source, status, warnings, errors, comparison,
  and artifact paths accurately.

### Report tests

- Rainfall columns appear only when rainfall is present.
- Timeline rainfall trace appears only when rainfall is present.
- Collapsible context contains source label, comparison badge, paired
  climatology, extent SNR, rainfall SNR, and peak lag.
- Rainfall absence omits the whole section.
- Rainfall failure shows a concise non-fatal warning without an empty chart.
- Generated figure dictionaries remain strict-JSON serializable.

### Integration and documentation checks

- Unit tests mock SILO and DEA; no default test requires network access.
- Optional real-source smoke tests retain the `network` marker.
- Update README quickstart, usage guide, API reference, report-column
  dictionary, and package-surface tests.
- Re-export `run_hydroseason` and `HydroSeasonRunResult` from
  `hydroseason.__init__`.
- Run focused workflow/rainfall/report tests, then the full suite and strict
  MkDocs build.

## Acceptance criteria

1. One public `run_hydroseason` call accepts every agreed water source,
   writes HTML and CSV artifacts, and returns `HydroSeasonRunResult`.
2. `water_source=None` fetches DEA WOfS only when AOI and date bounds are
   supplied.
3. Rainfall is absent by default.
4. A supplied rainfall CSV is used regardless of `fetch_rainfall`; otherwise
   `fetch_rainfall=True` fetches SILO.
5. Any ancillary rainfall failure is non-fatal, visible, and auditable.
6. With rainfall available, `*_monthly.csv` contains `rainfall_mm` and
   `rain_anomaly_mm`; without rainfall, it contains neither.
7. With rainfall available, HTML contains the raw timeline trace and a
   collapsible context section with rainfall regime, comparison, extent SNR,
   rain SNR, peak/trough timing, peak lag, paired climatology, and cautious
   interpretation.
8. Rainfall on/off invariance tests prove byte/equality-equivalent water
   regime diagnostics, route, boundaries, phases, events, and low spells.
9. Existing lower-level loading, `analyze_catchment`, and report APIs remain
   compatible.
10. Focused tests, full test suite, lint, and strict documentation build pass.
