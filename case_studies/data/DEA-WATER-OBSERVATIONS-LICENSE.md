# Geoscience Australia Data Attribution and License Notice

The surface-water extent time-series data contained in `case_studies/data/extent/*.csv` are derived from **Digital Earth Australia (DEA) Water Observations** (product: `ga_ls_wo_3`), produced by Geoscience Australia.

## Upstream Dataset Details

- **Dataset Name:** Digital Earth Australia Water Observations (Landsat, Collection 3)
- **Product ID:** `ga_ls_wo_3`
- **Publisher:** Geoscience Australia / Digital Earth Australia
- **DOI:** [10.26186/146257](https://doi.org/10.26186/146257)
- **License:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
- **STAC Catalog:** `https://explorer.dea.ga.gov.au/stac`

## Attribution Statement

> Incorporates data from Digital Earth Australia Water Observations (`ga_ls_wo_3`), © Commonwealth of Australia (Geoscience Australia) 2026. Licensed under Creative Commons Attribution 4.0 International.

## Derivative Nature

The `.csv` files in this repository are derived monthly summary statistics (water pixel count `n_water`, valid pixel count `n_valid`, area of interest pixel count `n_aoi`, percentage surface water extent `extent_pct`, and invalid observation percentage `invalid_pct`) extracted over five Australian river catchment boundaries for the period `2005-01-01` through `2025-12-01`.

## License Separation

- The **data files** in `case_studies/data/` are provided under the terms of the **CC BY 4.0** license.
- The **HydroSeason software source code** and scripts in this repository are licensed separately under the **MIT License** (see `LICENSE` at root).
