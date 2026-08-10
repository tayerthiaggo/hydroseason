# Citation

If you use HydroSeason in research, cite the **software release** and the
associated **methodological paper**.

## Software

Prefer the versioned GitHub/Zenodo release once a DOI is minted. Until then,
cite the repository and version from `CITATION.cff` / `pyproject.toml`.

```bibtex
@software{tayer_hydroseason,
  author  = {Tayer, Thiaggo C.},
  title   = {HydroSeason: Remote-sensing-first hydrological year and season detection},
  version = {0.1.0},
  year    = {2026},
  url     = {https://github.com/tayerthiaggo/hydroseason},
  note    = {Replace with Zenodo DOI after first archived release}
}
```

`CITATION.cff` intentionally has **no software DOI** until the first public
release is archived on Zenodo. Do not invent a placeholder DOI in papers.
After minting, add `doi:` back to `CITATION.cff` and enable the README DOI badge.

## Method paper

Tayer, T. C., Beesley, L. S., Stewart-Koster, B., Bond, N., Douglas, M. M.,
Rossi, M. J., McGregor, G. B., & Marshall, J. C. (2026). Mapping resilience:
A framework for analysing surface-water dynamics and persistent pools in
non-perennial rivers using remote sensing, rainfall and river discharge data.
*Journal of Hydrology*, *666*, 134750.
https://doi.org/10.1016/j.jhydrol.2025.134750

```bibtex
@article{tayer2026mapping,
  author  = {Tayer, Thiaggo C. and Beesley, Leah S. and Stewart-Koster, Ben
             and Bond, Nick and Douglas, Michael M. and Rossi, Maria J.
             and McGregor, Glenn B. and Marshall, Jonathan C.},
  title   = {Mapping resilience: A framework for analysing surface-water
             dynamics and persistent pools in non-perennial rivers using
             remote sensing, rainfall and river discharge data},
  journal = {Journal of Hydrology},
  volume  = {666},
  pages   = {134750},
  year    = {2026},
  doi     = {10.1016/j.jhydrol.2025.134750}
}
```

## Scope note

HydroSeason analyses satellite-derived surface-water extent. Rainfall is
ancillary context only and never sets water routing, boundaries, phases,
events, or low spells.
