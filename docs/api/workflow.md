# Workflow

The one-call orchestrator. Start here — see [Usage Guide: Start here, one call](../guide.md#start-here-one-call).

::: hydroseason.workflow
    options:
      members:
        - HydroSeasonRunResult
        - run_hydroseason
      show_root_heading: true
      show_source: false
      heading_level: 2

## AOI and map parameters

`run_hydroseason` accepts one AOI analysis. If its supplied AOI contains
multiple rows, they are analysed together as one union footprint; use
`run_hydroseason_many` when rows must remain separate. Its `show_map` parameter
accepts `"auto"` (default: preview only in a notebook), `True` (request a
preview), or `False` (no preview). `HydroSeasonRunResult` returns
`aoi_context: AOIContext | None`: compact display geometry and bounds when an
AOI was supplied, otherwise `None`. It is display metadata, not a replacement
for the analysed footprint.

For DEA acquisition, `run_hydroseason(..., refresh_historical_mask=True)`
adopts a wider historical-mask vintage when available. Pass `False` to pin a
compatible cached vintage. Any `HistoricalMaskRefreshedWarning` notice is
copied once into `HydroSeasonRunResult.warnings`.

## Row-preserving DEA/STAC batches

`run_hydroseason_many(aois, *, output_dir, start_date, end_date, ...)` has no
`water_source` parameter: in 0.1.1 it is DEA/STAC-only. It loads the vector
once, splits it into one single-row AOI per input row, and invokes the
single-AOI workflow for each. A `MultiPolygon` in one row remains one AOI.
The result tuple is always in source order, even when scheduling begins larger
items first.

| Parameter / result | Contract |
|---|---|
| `id_col` | Optional source identifier column. Values must be non-null, nonblank, and unique before and after safe filename conversion; defaults are `aoi-0001`, `aoi-0002`, ... |
| `workers` | `"auto"` or a positive integer. Auto uses `min(2, logical CPU count)`; `1` is sequential; a larger integer is honoured subject to memory admission. |
| `memory_budget_gb` | Optional positive finite decimal-GB budget. `None` uses 80% of currently available RAM. |
| `show_map` | `"auto"`, `True`, or `False`; batch preview is best-effort and never changes child analyses. |
| `refresh_historical_mask` | Defaults to `True` for every child workflow; `False` pins each compatible cached historical-mask vintage. |
| `HydroSeasonAOIOutcome` | Immutable `id`, zero-based `source_position`, successful `result` or complete `error_type`/`error_message`; exactly one form is populated. |
| `HydroSeasonBatchResult` | Immutable `outcomes` tuple plus source-ordered `.succeeded`, `.failed`, and `.raise_for_failures()`. |
| `HydroSeasonBatchError` | Raised by `.raise_for_failures()` with every failed outcome in `.failures`. |

Each row receives `output_dir/<safe-id>/` and, when provided,
`cache_dir/<safe-id>/`. Runtime exceptions are captured per row, while invalid
input, identifiers, dates, worker counts, or budgets fail before any child
run. The scheduler estimates a 30 m native-resolution peak from the AOI's
bounding box, admitting concurrent jobs only while the summed estimate fits.
Before work starts, one global oversized-AOI warning lists every affected
source position; each oversized item then runs alone. Threads provide I/O
overlap only; this outer scheduler does not set Dask worker counts or promise
linear throughput.

::: hydroseason.batch
    options:
      members:
        - HydroSeasonAOIOutcome
        - HydroSeasonBatchError
        - HydroSeasonBatchResult
        - run_hydroseason_many
      show_root_heading: true
      show_source: false
      heading_level: 2
