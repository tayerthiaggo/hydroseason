# HydroSeason Case Studies: Reproduction and Provenance

This directory holds the committed inputs for the three HydroSeason case
studies. The write-ups are in the documentation:
[main workflow](https://tayerthiaggo.github.io/hydroseason/case-studies/main-workflow/),
[resolution](https://tayerthiaggo.github.io/hydroseason/case-studies/resolution-and-acquisition/),
and [rainfall context](https://tayerthiaggo.github.io/hydroseason/case-studies/rainfall-context/).

All three use five Australian catchments (Daly, Fitzroy, Gilbert, Lachlan,
Moonie) over `2005-01-01` to `2025-12-01` (252 months).

1. **Main workflow** — the standard `run_hydroseason` analysis on the 30 m
   whole-catchment extent series.
2. **Resolution** — the same analysis on 60, 90, and 300 m versions of each
   series, compared against 30 m.
3. **Rainfall context** — the main workflow with monthly SILO rainfall
   attached. Every water-only column matches the main workflow exactly; only
   the rainfall-comparison columns are new.

## Layout

```
case_studies/
├── README.md
└── data/
    ├── extent/      # 20 monthly extent CSVs: 5 catchments x 4 resolutions
    ├── rainfall/    # 5 monthly SILO rainfall CSVs
    ├── manifest.json                      # hashes, row counts, CRS, bounds
    └── DEA-WATER-OBSERVATIONS-LICENSE.md  # CC BY 4.0 attribution
```

The checked results the documentation tables are rendered from live in
`tests/fixtures/v020/case_studies/`.

## Reproduce

From the repository root, with `pip install -e ".[all,docs]"`:

```bash
python scripts/prepare_case_study_data.py --check    # input integrity
python scripts/_build_study_case_offline.py --check  # main workflow
python scripts/_build_study_case_rainfall.py --check # rainfall context
python scripts/run_resolution_case_study.py --check  # resolution
python scripts/render_case_study_docs.py --check     # docs tables
```

Each check rebuilds the results offline and compares them with the checked
results. Drop `--check` to regenerate.

## Provenance and licensing

- Extent: Geoscience Australia / Digital Earth Australia Water Observations
  (`ga_ls_wo_3`), DOI [10.26186/146257](https://doi.org/10.26186/146257).
- Rainfall: SILO gridded monthly rainfall (Queensland Government), from the
  public `silo-open-data` archive.
- Data license: [CC BY 4.0](data/DEA-WATER-OBSERVATIONS-LICENSE.md). Code
  license: MIT (repository `LICENSE`).
- These files are in the GitHub repository and Zenodo archive but not in the
  PyPI wheel or sdist.
