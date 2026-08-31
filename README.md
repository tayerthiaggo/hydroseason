# HydroSeason

[![Tests](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml/badge.svg)](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://tayerthiaggo.github.io/hydroseason/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://github.com/tayerthiaggo/hydroseason)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/tayerthiaggo/hydroseason/blob/main/LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21866898.svg)](https://doi.org/10.5281/zenodo.21866898)

**HydroSeason is an open-source Python package for hydrological-year detection and seasonal/aseasonal analysis from monthly satellite-derived surface-water extent.**

HydroSeason turns a monthly surface-water record into a hydrological year report — from a satellite-derived water-mask time series (such as Digital Earth Australia Water Observations), it works out when a catchment floods and dries, where each hydrological year begins and ends, and whether the pattern is even seasonal at all.

> [!NOTE]
> HydroSeason analyzes surface-water extent percentages. It does **not** estimate river discharge, channel depth, total water volume, or groundwater storage.

---

## What you get

[![HydroSeason report preview](https://raw.githubusercontent.com/tayerthiaggo/hydroseason/main/docs/assets/report-preview.png)](https://tayerthiaggo.github.io/hydroseason/examples/fitzroy-river-wa.html)

One function call gives you one self-contained HTML report, an interactive
water-extent timeline with each hydrological year, its wet and dry phases,
and the flood events and low spells found in the record. Plus four CSVs
carrying the same numbers for your own analysis: `_monthly`, `_hydro_years`,
`_wet_event`, and `_low_spells`.

Open a real one (no install needed):

- [Fitzroy River (WA)](https://tayerthiaggo.github.io/hydroseason/examples/fitzroy-river-wa.html) — a strongly seasonal monsoonal catchment
- [Lachlan River (NSW)](https://tayerthiaggo.github.io/hydroseason/examples/lachlan-river-nsw.html) — an aseasonal one, characterized by flood events and dry spells instead of forced hydrological years
- [Fitzroy River, with rainfall context](https://tayerthiaggo.github.io/hydroseason/examples/fitzroy-river-wa-rainfall.html) — the same water analysis, with rainfall added purely as annotation

---

## Installation

```bash
pip install hydroseason              # Core: CSV detection & reports (pandas, numpy)
pip install "hydroseason[raster]"    # + xarray, rioxarray, rasterio, geopandas, dask, zarr
pip install "hydroseason[stac]"      # + pystac-client, odc-stac (DEA STAC acquisition)
pip install "hydroseason[all]"       # Complete raster + STAC dependencies
```

---

## Quickstart

```python
from hydroseason import run_hydroseason

result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/report",
    aoi_name="My AOI",
)

print(f"Regime: {result.analysis.regime.regime}")
print(f"Route: {result.analysis.route}")
print(f"HTML: {result.artifacts.html}")
```

`run_hydroseason` is the one function most people need — see
[the four ways to run it](#the-four-ways-to-run-it) below for rasters,
DEA fetching, and optional rainfall context.

### Many AOIs: one vector row, one report

For independent DEA/STAC analyses from a multi-row vector layer, use
`run_hydroseason_many`. One input row produces one analysis and one report;
each result is isolated under its resolved identifier. This differs from
`run_hydroseason`, which treats a multi-row AOI as one combined analysis over
its union footprint. A one-row `MultiPolygon` is still one AOI.

```python
from hydroseason import run_hydroseason_many

batch = run_hydroseason_many(
    "catchments.gpkg",
    output_dir="results",
    cache_dir="cache",
    start_date="2000-01-01",
    end_date="2025-12-01",
    id_col="catchment_id",
    workers="auto",
)
for outcome in batch.outcomes:
    if outcome.succeeded:
        print(outcome.id, outcome.result.artifacts.html)
    else:
        print(outcome.id, outcome.error_type, outcome.error_message)
batch.raise_for_failures()
```

`workers="auto"` uses a default concurrency cap of 2 and admits work only
within 80% of currently available RAM. See the [Usage Guide](https://tayerthiaggo.github.io/hydroseason/guide/#many-aois-one-row-one-analysis) for memory and scheduling details.

For runs long enough to outlive a notebook session, use the CLI — same
orchestrator, its own process, resumable via `--cache-dir`:

```bash
hydroseason run --aoi data/fitzroy_kimberley_aoi.geojson --aoi-name "Fitzroy River (WA)" \
  --start-date 2005-01-01 --end-date 2025-12-01 \
  --output-dir output/fitzroy --cache-dir cache/fitzroy
```

`hydroseason doctor` reports whether an environment has the optional
dependencies a given path needs. Full recipes:
[CLI Recipes](https://tayerthiaggo.github.io/hydroseason/cli-recipes/).

---

## How it works

1. **You give it monthly water-extent data** — a CSV you already have, a raster/NetCDF/Zarr cube, or nothing at all (it fetches Digital Earth Australia satellite data for you).
2. **On a DEA fetch, it screens the AOI first** — one all-time WOfS Statistics read checks the catchment actually holds recurrent surface water before any monthly data is paid for; an AOI with none raises `HydroSeasonPreflightError` instead of returning an empty analysis. A Statistics outage never becomes a "no water" answer.
3. **It checks whether the catchment has a reliable annual cycle** — a signal-to-noise ratio (SNR): how strong and repeatable the yearly wet/dry swing is compared to noise.
4. **It picks the matching analysis automatically** — a strong, repeatable cycle gets per-year hydrological boundaries; an irregular or dryland catchment gets discrete flood-event and dry-spell characterization instead, rather than forcing a yearly pattern that isn't really there.
5. **Optional rainfall adds context, never changes the answer** — rainfall can be fetched or supplied alongside the water data, but it only annotates the report; it can never alter the regime, route, boundaries, phases, events, or spells that were already decided from water alone.
6. **It writes one self-contained HTML report and four CSVs** — open the HTML anywhere, no server needed; the CSVs are ready for your own analysis.

```
CSV, raster, or DEA fetch  →  run_hydroseason  →  seasonal or aseasonal route  →  HTML report + 4 CSVs
```

---

## The four ways to run it

| You have... | Pass it as `water_source` | Extra required |
|---|---|---|
| A monthly extent CSV or `pandas.DataFrame` | the CSV path or the DataFrame | none (core install) |
| A NetCDF/Zarr file, or an `xarray` object | the file path, or the `Dataset`/`DataArray` | `hydroseason[raster]` |
| Nothing yet — fetch it from DEA | `None`, plus `aoi=`, `start_date=`, `end_date=` | `hydroseason[stac]` |
| Any of the above, plus rainfall context | add `fetch_rainfall=True` or `rainfall_csv_path=` | `hydroseason[raster]` for SILO fetch |

Runnable examples for each: [Usage Guide — The four ways to run it](https://tayerthiaggo.github.io/hydroseason/guide/#the-four-ways-to-run-it),
or the [notebooks](https://github.com/tayerthiaggo/hydroseason/tree/main/notebooks/) — start with
[01_quickstart.ipynb](https://github.com/tayerthiaggo/hydroseason/blob/main/notebooks/01_quickstart.ipynb).
Acquisition internals (the fixed historical water mask, planning
footprints, cache integrity, composite bundles) are documented in
[Advanced: DEA acquisition internals](https://tayerthiaggo.github.io/hydroseason/guide/#advanced-dea-acquisition-internals).

---

## Case Studies

Three fully reproducible offline case studies using 2005–2025 DEA 30 m
whole-catchment extent data across five Australian catchments (Daly,
Fitzroy, Gilbert, Lachlan, Moonie):

1. **[Main Catchment Workflow](https://tayerthiaggo.github.io/hydroseason/case-studies/main-workflow/)** — Route-aware analysis across five catchments: three seasonal/marginal monsoonal basins, two aseasonal dryland basins.
2. **[Resolution and Acquisition Evidence](https://tayerthiaggo.github.io/hydroseason/case-studies/resolution-and-acquisition/)** — Why 30 m resolution is the release standard: 60/90/300 m coarsening fails pre-declared fidelity gates for low-SNR catchments.
3. **[Rainfall Context](https://tayerthiaggo.github.io/hydroseason/case-studies/rainfall-context/)** — Proves rainfall is strictly additive: every water-only column stays byte-identical with rainfall attached.

---

## Scientific Limitations

- **Timing evidence**: Fewer than 30 usable annual timings (not 30 months) can make bootstrap intervals wide; fewer than five usable annual timings is insufficient for regime assessment.
- **Circular timing**: A low mean resultant length can mean diffuse timing or two cancelling preferred seasons; inspect the accompanying Kuiper uniformity result and trough evidence.

- **Extent is not Volume or Discharge**: Surface area percentage (`extent_pct`) dilutes narrow river channels and misses sub-canopy water.
- **Cloud Gaps**: High cloud/shadow invalid coverage (`invalid_pct`) distorts extent statistics if unflagged.
- **Resolution**: Coarsening spatial resolution distorts peak/trough timing and event boundaries. 30 m resolution remains authoritative.

---

## Entry Points

| Symbol | Purpose |
|---|---|
| `run_hydroseason` | One-call orchestrator: resolve water input, analyze, optional rainfall, write report |
| `HydroSeasonRunResult` | Everything a `run_hydroseason` call produced (`.analysis`, `.artifacts`, `.rainfall_status`, ...) |
| `run_hydroseason_many` | DEA/STAC batch orchestrator: preserve each input vector row as one independent run |
| `HydroSeasonBatchResult` | Source-ordered successful and failed per-row outcomes; call `.raise_for_failures()` after inspection |
| `load_extent_csv` | Read a monthly extent CSV directly, for the lower-level building blocks |
| `analyze_catchment` | Assess regime, then run the analysis that regime supports (the routing authority) |
| `generate_catchment_report` | Write the self-contained HTML report plus the 4-CSV bundle |
| `load_wofs_monthly_extent` | Fetch DEA WOfS directly, without the full orchestrator |
| `preflight` | Report what an AOI's record can support, before analysing it ([guide](https://tayerthiaggo.github.io/hydroseason/preflight/)) |
| `HydroSeasonPreflightError` | Raised when the DEA screen finds no recurrent surface water; carries the measured counts |

Full API reference, grouped by task: [Workflow, Loading Data, Analysis, Reporting](https://tayerthiaggo.github.io/hydroseason/api/).

---

## Citation

If you use HydroSeason in your research, please cite the **software release** (see [`CITATION.cff`](https://github.com/tayerthiaggo/hydroseason/blob/main/CITATION.cff)):

```bibtex
@software{tayer_hydroseason,
  author  = {Tayer, Thiaggo C.},
  title   = {HydroSeason: Remote-sensing-first hydrological year and season detection},
  year    = {2026},
  url     = {https://github.com/tayerthiaggo/hydroseason},
  doi     = {10.5281/zenodo.21866898}
}
```

Full citation guidance, including the version-specific DOI policy, is in [docs/citation.md](https://tayerthiaggo.github.io/hydroseason/citation/).

---

## License

MIT License — see [LICENSE](https://github.com/tayerthiaggo/hydroseason/blob/main/LICENSE).
