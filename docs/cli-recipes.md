# CLI Recipes

`hydroseason run` calls the same `run_hydroseason` orchestrator the Python
examples use, in its own process. Nothing is reimplemented: the CLI
translates path and scalar arguments and calls it once.

Run it instead of a notebook cell when the run is long. A 21-year DEA fetch
spends hours inside native GDAL, PROJ, and NumPy code; if that aborts the
interpreter, a Jupyter kernel loses every variable you had, while a CLI
process loses only itself — and `--cache-dir` lets the next invocation
resume from the last completed calendar year.

In-memory DataFrames and xarray objects stay kernel-only, as do advanced
`analysis_options`. Everything else has a flag.

## 1. Install

```bash
pip install hydroseason                    # core: CSV/DataFrame input
pip install "hydroseason[raster]"          # NetCDF/Zarr/xarray + SILO rainfall
pip install "hydroseason[stac]"            # + DEA WOfS fetching
pip install "hydroseason[all]"             # raster + stac
pip install "hydroseason[case-study,docs]" # reproducibility + docs builds
```

Check what an environment can actually do:

```bash
hydroseason doctor
```

It probes the interpreter (supported: 3.10–3.13) and every optional
dependency, including the netCDF4/NumPy binary-compatibility check, and
exits nonzero if anything failed.

## 2. Run an existing extent CSV

Kernel:

```python
from hydroseason import run_hydroseason

result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/isaac",
    aoi_name="Isaac River",
)
```

CLI:

```bash
hydroseason run \
  --water-source monthly_extent.csv \
  --output-dir output/isaac \
  --aoi-name "Isaac River"
```

```bash
python -m hydroseason run \
  --water-source monthly_extent.csv \
  --output-dir output/isaac \
  --aoi-name "Isaac River"
```

## 3. Run rasters, NetCDF, or Zarr

Kernel:

```python
result = run_hydroseason(
    "monthly_masks.nc",
    output_dir="output/local",
    water_mask_variable="water_mask",
    aoi_name="Local AOI",
)
```

CLI:

```bash
hydroseason run \
  --water-source monthly_masks.nc \
  --water-mask-variable water_mask \
  --output-dir output/local \
  --aoi-name "Local AOI"
```

## 4. Fetch DEA WOfS

Omit `--water-source`; `--aoi`, `--start-date`, and `--end-date` become
required.

Kernel:

```python
result = run_hydroseason(
    output_dir="output/isaac",
    aoi="isaac.geojson",
    aoi_name="Isaac River",
    start_date="2005-01-01",
    end_date="2025-12-01",
    cache_dir="cache/isaac",
)
```

CLI:

```bash
hydroseason run \
  --aoi isaac.geojson \
  --aoi-name "Isaac River" \
  --start-date 2005-01-01 \
  --end-date 2025-12-01 \
  --output-dir output/isaac \
  --cache-dir cache/isaac
```

`--stac-url` configures **both** DEA searches this path performs: the
monthly `ga_ls_wo_3` search and the `ga_ls_wo_fq_myear_3` historical-
statistics search that fixes the run's spatial denominator. Pass
`--statistics-stac-url` only when the two must point at different services.

## 5. Add rainfall context

Rainfall is optional and always ancillary: it enriches the monthly CSV and
the HTML report and never changes water regime, route, boundaries, phases,
events, or low spells. A rainfall failure is reported, not fatal — the
water-only bundle is still written and the command still exits 0.

```bash
hydroseason run \
  --water-source monthly_extent.csv \
  --output-dir output/isaac \
  --rainfall-csv monthly_rainfall.csv
```

```bash
hydroseason run \
  --aoi isaac.geojson --aoi-name "Isaac River" \
  --start-date 2005-01-01 --end-date 2025-12-01 \
  --output-dir output/isaac \
  --fetch-rainfall
```

`--rainfall-csv` takes precedence over `--fetch-rainfall`: SILO is never
called when a CSV is given. `--fetch-rainfall` needs the `raster` extra
(`s3fs`, `h5netcdf`, `h5py`); when those are missing, the command warns
before the water step rather than after it. `hydroseason doctor` tells you
in advance.

## 6. Long-running runs

**Progress.** On by default: five numbered step lines on standard error,
plus a bar ticking once per calendar year during a DEA fetch. `--no-progress`
turns it off.

```text
[1/5] resolve water input ... fetching DEA WOfS
[1/5] resolve water input: 47%|████▋     | 10/21 [08:12<09:01, 49.2s/yr]
[1/5] resolve water input done (252 months, dea_wofs) in 1032.4s
[2/5] analyze catchment ...
[2/5] analyze catchment done (per_year_detection route) in 3.1s
[3/5] rainfall ...
[3/5] rainfall done (skipped) in 0.0s
[4/5] rainfall comparison ...
[4/5] rainfall comparison done (skipped) in 0.0s
[5/5] write report ...
[5/5] write report done (isaac-river-report.html) in 1.8s
```

**Log redirection.** Progress and warnings go to standard error, the result
summary to standard output, so both can be captured:

```powershell
hydroseason run --aoi isaac.geojson --aoi-name "Isaac River" `
  --start-date 2005-01-01 --end-date 2025-12-01 `
  --output-dir output/isaac --cache-dir cache/isaac *> hydroseason.log
```

```bash
hydroseason run --aoi isaac.geojson --aoi-name "Isaac River" \
  --start-date 2005-01-01 --end-date 2025-12-01 \
  --output-dir output/isaac --cache-dir cache/isaac > hydroseason.log 2>&1
```

**Interruption and retry.** Ctrl-C is safe. Re-run the identical command
with the same `--cache-dir`: completed calendar years are read from cache
and only the missing ones are re-fetched. There is no separate checkpoint
protocol — cache identity includes every data-affecting input, so a changed
AOI, date range, resolution, or STAC URL never silently reuses stale work.

**Exit status.** `0` success, including an ancillary rainfall failure. `1` a
fatal water-input, analysis, or report-writing failure. `2` a usage error.

**Machine-readable output.** `--json` prints the summary as JSON on standard
output for scripting. The payload includes `output_dir` (resolved absolute
path) and paths to every artifact (`html`, `monthly_csv`, `hydro_years_csv`,
`wet_event_csv`, `low_spells_csv`):

```bash
hydroseason run --water-source monthly_extent.csv --output-dir out --json
```

**Historical mask refresh.** By default a DEA run refreshes a compatible
cached historical mask to the current vintage. Pin the existing cache with
`--no-refresh-historical-mask` when you want a reproducible re-run against the
same denominator:

```bash
hydroseason run \
  --aoi isaac.geojson --aoi-name "Isaac River" \
  --start-date 2005-01-01 --end-date 2025-12-01 \
  --output-dir output/isaac --cache-dir cache/isaac \
  --no-refresh-historical-mask
```

## 7. Repository checks

Maintainer and reproducibility commands, for a source checkout rather than
an installed package:

```text
python scripts/prepare_case_study_data.py --check
python scripts/_build_study_case_offline.py --check
python scripts/_build_study_case_rainfall.py --check
python scripts/run_resolution_case_study.py --check --output-dir case_studies/results/resolution
python scripts/render_case_study_docs.py --check
python -m mkdocs serve
python -m mkdocs build --strict
```
