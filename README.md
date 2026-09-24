# HydroSeason

[![Tests](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml/badge.svg)](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://tayerthiaggo.github.io/hydroseason/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://github.com/tayerthiaggo/hydroseason)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/tayerthiaggo/hydroseason/blob/main/LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21866898.svg)](https://doi.org/10.5281/zenodo.21866898)

**Find the hydrological year in satellite surface-water data — or learn that there isn't one.**

HydroSeason reads a monthly surface-water extent record (for example, from
Digital Earth Australia Water Observations) and tells you whether the
catchment floods and dries on a reliable annual cycle. If it does, you get
per-year boundaries and wet/dry phases. If it doesn't, you get flood events
and low-water spells instead of a forced calendar.

> **Scope:** HydroSeason measures surface-water **extent**. It does not
> estimate discharge, depth, volume, or groundwater.

## What you get

[![HydroSeason report preview](https://raw.githubusercontent.com/tayerthiaggo/hydroseason/main/docs/assets/report-preview.png)](https://tayerthiaggo.github.io/hydroseason/examples/fitzroy-river-wa.html)

One call writes a self-contained HTML report, four CSVs (`_monthly`,
`_hydro_years`, `_wet_event`, `_low_spells`), and a run manifest that
records the method version and input checksums.

Open a real report (no install needed):

- [Fitzroy River (WA)](https://tayerthiaggo.github.io/hydroseason/examples/fitzroy-river-wa.html) — seasonal: per-year boundaries
- [Lachlan River (NSW)](https://tayerthiaggo.github.io/hydroseason/examples/lachlan-river-nsw.html) — aseasonal: events and dry spells
- [Fitzroy River + rainfall](https://tayerthiaggo.github.io/hydroseason/examples/fitzroy-river-wa-rainfall.html) — rainfall shown as context only

## Install

```bash
pip install hydroseason              # CSV input (pandas + numpy only)
pip install "hydroseason[raster]"    # + NetCDF/Zarr/xarray input and SILO rainfall
pip install "hydroseason[stac]"      # + fetch DEA Water Observations directly
```

Python 3.10–3.13. Run `hydroseason doctor` to check which inputs your
environment supports.

## Quickstart

From a monthly extent CSV (`date`, `extent_pct`, optional `invalid_pct`):

```python
from hydroseason import run_hydroseason

result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/report",
    aoi_name="My AOI",
)
print(result.analysis.regime.regime)  # "seasonal", "aseasonal", or "insufficient_record"
print(result.analysis.route)          # "per_year_detection", "event_characterisation", ...
print(result.artifacts.html)
```

Or fetch DEA data for a polygon, from the command line:

```bash
hydroseason run --aoi catchment.geojson --aoi-name "My catchment" \
  --start-date 2005-01-01 --end-date 2025-12-01 \
  --output-dir output/report --cache-dir cache
```

The same function also takes NetCDF/Zarr rasters, optional rainfall, and —
through `run_hydroseason_many` — many AOIs at once. See the
[Usage Guide](https://tayerthiaggo.github.io/hydroseason/guide/) and the
[notebooks](https://github.com/tayerthiaggo/hydroseason/tree/main/notebooks/).

## How it works

1. **Screen** — on a DEA fetch, one read of the all-time WOfS statistics
   checks the AOI holds recurrent water before any monthly data is downloaded.
2. **Test seasonality** — circular Kuiper tests ask whether annual peaks
   *and* troughs recur in the same calendar months (at least five detectable
   years required).
3. **Route** — a seasonal record with at least seven resolved cycles gets
   per-year boundaries, refined with a robust (Huber) profile fit. Anything
   else gets flood-event and low-spell analysis.
4. **Report** — rainfall, if added, annotates the report but never changes
   the answer, which is decided from water alone.

Every run uses one frozen method, `hydroseason-v0.2.0`, recorded in the run
manifest. Details: [Methods Reference](https://tayerthiaggo.github.io/hydroseason/methods/).

## Case studies

Three reproducible studies on five Australian catchments (DEA 30 m,
2005–2025): the [main workflow](https://tayerthiaggo.github.io/hydroseason/case-studies/main-workflow/),
[resolution sensitivity](https://tayerthiaggo.github.io/hydroseason/case-studies/resolution-and-acquisition/),
and [rainfall context](https://tayerthiaggo.github.io/hydroseason/case-studies/rainfall-context/).

## Citation

Please cite the software release ([`CITATION.cff`](https://github.com/tayerthiaggo/hydroseason/blob/main/CITATION.cff)):

```bibtex
@software{tayer_hydroseason,
  author  = {Tayer, Thiaggo C.},
  title   = {HydroSeason: Remote-sensing-first hydrological year and season detection},
  year    = {2026},
  url     = {https://github.com/tayerthiaggo/hydroseason},
  doi     = {10.5281/zenodo.21866898}
}
```

See [Citation](https://tayerthiaggo.github.io/hydroseason/citation/) for version-specific DOIs.

## License

MIT — see [LICENSE](https://github.com/tayerthiaggo/hydroseason/blob/main/LICENSE).
