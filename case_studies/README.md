# HydroSeason Case Studies: Reproduction and Provenance

This directory contains the committed, reproducible inputs and checked results for the two HydroSeason v0.1.0 release case studies.

## Case Study Overview

1. **Main HydroSeason Workflow (Case Study 1)**
   - Evaluates the standard HydroSeason analysis pipeline across five representative Australian river catchments covering distinct hydrological regimes (monsoonal/tropical, semi-arid, dryland/intermittent).
   - Analysis window: `2005-01-01` through `2025-12-01` (21 complete years, 252 monthly observations).
   - Inputs: 30 metre surface-water extent series derived from DEA Water Observations.

2. **Resolution Comparison Study (Case Study 2)**
   - Evaluates analytical fidelity and performance across four spatial resolutions (30 m, 60 m, 90 m, and 300 m) across all five publish catchments.
   - Provides evidence-based recommendations for optimal resolution trade-offs.

## Directory Structure

```
case_studies/
├── README.md                          # Reproduction guide and entry point
├── data/
│   ├── extent/                        # Normalized 20-input extent matrix (5 catchments x 4 resolutions)
│   │   ├── daly_river_nt_30m.csv
│   │   ├── fitzroy_river_wa_30m.csv
│   │   └── ... (20 files)
│   ├── manifest.json                  # Hashes, row counts, CRS, bounds, generator commit
│   └── DEA-WATER-OBSERVATIONS-LICENSE.md # CC BY 4.0 data attribution notice
└── results/                           # Checked results produced by case study scripts
    ├── main/                          # Main workflow outputs
    └── resolution/                    # Resolution comparison outputs
```

## Reproduction Instructions

To verify data integrity:

```bash
python scripts/prepare_case_study_data.py --check
```

To run unit tests verifying normalizer and manifest contracts:

```bash
python -m pytest tests/test_prepare_case_study_data.py -q
```

## Data Provenance and Licensing

- Source Data: Geoscience Australia / Digital Earth Australia Water Observations (`ga_ls_wo_3`), DOI: [10.26186/146257](https://doi.org/10.26186/146257).
- Data License: [CC BY 4.0](data/DEA-WATER-OBSERVATIONS-LICENSE.md).
- Code License: MIT License (see repository root `LICENSE`).
- Source Inclusion: Case study input data are committed to the GitHub repository and source distribution archives (Zenodo), but explicitly excluded from PyPI package distributions (`.whl` and `.tar.gz` sdist).
