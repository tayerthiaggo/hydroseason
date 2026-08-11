# HydroSeason Case Studies: Reproduction and Provenance

This directory contains the committed, reproducible inputs and checked results for the HydroSeason v0.1.0 release case studies.

## Case Study Overview

1. **Main HydroSeason Workflow (Case Study 1)**
   - Evaluates the standard HydroSeason analysis pipeline across five representative Australian river catchments covering distinct hydrological regimes (monsoonal/tropical, semi-arid, dryland/intermittent).
   - Analysis window: `2005-01-01` through `2025-12-01` (21 complete years, 252 monthly observations).
   - Inputs: 30 metre surface-water extent series derived from DEA Water Observations.

2. **Resolution Comparison Study (Case Study 2)**
   - Evaluates analytical fidelity and performance across four spatial resolutions (30 m, 60 m, 90 m, and 300 m) across all five publish catchments.
   - Provides evidence-based recommendations for optimal resolution trade-offs.

3. **Rainfall-Augmented Main Workflow (Case Study 1b)**
   - Re-runs Case Study 1's five catchments with monthly SILO gridded rainfall attached as ancillary context (`workflow.run_hydroseason`'s rainfall path), via the same `compare_rainfall_to_extent_regime` comparison used by the public API.
   - Rainfall is strictly additive: it is resolved *after* the water-only `analyze_catchment` call and can never influence regime, route, or hydrological-year boundaries. `summary.csv`'s water-only columns (`regime`, `route`, `amplitude_snr`, `peak_phase_iqr_months`, `n_hydro_years`, ...) are byte-identical to Case Study 1's; only the rainfall-comparison columns (`rainfall_regime`, `rainfall_amplitude_snr`, `rainfall_divergence`, `rainfall_peak_lag_months`) are new.
   - Same analysis window and extent inputs as Case Study 1; rainfall inputs are monthly SILO rainfall (`silo-open-data`, Official archive), pre-fetched and trimmed to `2005-01-01`-`2025-12-01`.

## Directory Structure

```
case_studies/
├── README.md                          # Reproduction guide and entry point
├── data/
│   ├── extent/                        # Normalized 20-input extent matrix (5 catchments x 4 resolutions)
│   │   ├── daly_river_nt_30m.csv
│   │   ├── fitzroy_river_wa_30m.csv
│   │   └── ... (20 files)
│   ├── rainfall/                      # Monthly SILO rainfall, one CSV per catchment (Case Study 1b)
│   │   ├── daly_river_nt_silo_rainfall.csv
│   │   └── ... (5 files)
│   ├── manifest.json                  # Hashes, row counts, CRS, bounds, generator commit
│   └── DEA-WATER-OBSERVATIONS-LICENSE.md # CC BY 4.0 data attribution notice
└── results/                           # Checked results produced by case study scripts
    ├── main/                          # Main workflow outputs (Case Study 1)
    ├── resolution/                    # Resolution comparison outputs (Case Study 2)
    └── main_rainfall/                 # Rainfall-augmented main workflow outputs (Case Study 1b)
```

## Reproduction Instructions

To verify data integrity:

```bash
python scripts/prepare_case_study_data.py --check
```

To rebuild or verify Case Study 1 (main workflow):

```bash
python scripts/_build_study_case_offline.py --check
```

To rebuild or verify Case Study 1b (rainfall-augmented main workflow):

```bash
python scripts/_build_study_case_rainfall.py --check
```

To run unit tests verifying normalizer and manifest contracts:

```bash
python -m pytest tests/test_prepare_case_study_data.py -q
```

## Data Provenance and Licensing

- Source Data: Geoscience Australia / Digital Earth Australia Water Observations (`ga_ls_wo_3`), DOI: [10.26186/146257](https://doi.org/10.26186/146257).
- Rainfall Data: SILO gridded monthly rainfall (Queensland Government / Longpaddock), fetched from the public `silo-open-data` S3 archive.
- Data License: [CC BY 4.0](data/DEA-WATER-OBSERVATIONS-LICENSE.md).
- Code License: MIT License (see repository root `LICENSE`).
- Source Inclusion: Case study input data are committed to the GitHub repository and source distribution archives (Zenodo), but explicitly excluded from PyPI package distributions (`.whl` and `.tar.gz` sdist).
