# Citation

If you use HydroSeason in research, cite the **software release**.

## Software

Prefer the versioned GitHub/Zenodo release.

```bibtex
@software{tayer_hydroseason,
  author  = {Tayer, Thiaggo C.},
  title   = {HydroSeason: Remote-sensing-first hydrological year and season detection},
  version = {0.1.1rc1},
  year    = {2026},
  url     = {https://github.com/tayerthiaggo/hydroseason}
}
```

The README badge links the Zenodo concept DOI for the project; once Zenodo mints
a DOI for 0.1.1, cite that version-specific DOI when referring to HydroSeason 0.1.1.

## Scope note

HydroSeason analyses satellite-derived surface-water extent. Rainfall is
ancillary context only and never sets water routing, boundaries, phases,
events, or low spells.

## Circular-timing precedents and limits

HydroSeason's annual timing statistics are close methodological precedents,
not validation that satellite surface-water extent is interchangeable with
gauge discharge. Mao et al. provide the satellite surface-water precedent:
they describe annual maximum flood-extent timing with circular mean direction
and mean resultant length ([DOI: 10.1029/2019JD031381](https://doi.org/10.1029/2019JD031381)).

The following four are flood-discharge or annual-flood studies, not
satellite-surface-water validation. Hall and Blöschl use circular concentration
and a uniformity assessment for European flood seasonality
([DOI: 10.5194/hess-22-3883-2018](https://doi.org/10.5194/hess-22-3883-2018)).
Cunderlik, Ouarda, and Bobée show why short annual-maximum records need
sampling caution ([DOI: 10.1029/2003WR002295](https://doi.org/10.1029/2003WR002295)).
Matti et al. illustrate flood-season shifts across Scandinavia
([DOI: 10.1002/hyp.11365](https://doi.org/10.1002/hyp.11365)), and Villarini
documents geographic variation in US flood seasonality
([DOI: 10.1016/j.advwatres.2015.11.009](https://doi.org/10.1016/j.advwatres.2015.11.009)).

These papers motivate transparent circular effect sizes and uncertainty
reporting; they do **not** prescribe HydroSeason's package thresholds. The
SNR, bootstrap-CI, and p-value cutoffs are explicit software decisions and
are documented in the [Usage Guide](guide.md#which-route-did-my-catchment-take).

### Interpretation limitations

- Bootstrap intervals resample the usable annual timing observations. They
  quantify sampling variation under that resampling scheme, not sensor error,
  spatial error, autocorrelation, or causal hydrology.
- The Monte Carlo Kuiper p-value tests a discrete 12-month uniform null. It is
  rotation-invariant and complements `R`, but does not identify a physical
  mechanism or make bimodal timing unimodal.
- Calendar months are the available monthly-resolution timing units. A peak
  can move within a month and a monthly water mask can miss short floods;
  results should not be interpreted as daily discharge timing.
- Fewer than 30 usable annual timings (not 30 months) retain the calculated
  classification but may have wide intervals. With 5–9 annual timings, the
  approved 10-year low-power guard prevents a non-significant Kuiper result
  from automatically declaring a strong record aseasonal; it remains marginal.
