# Scientific Baseline (0.1.1 Established Outcomes)

This directory contains the immutable, protected scientific baseline fixtures for HydroSeason.

## Source & Scope
- **Source:** Checked 2005-2025 raw 30 m case-study run across the 5 reference catchments.
- **Protected fields:** Regime classification, routing, annual hydro year count, climatological peak/trough months, and annual hydrological year date/extent boundaries (`start_date`, `end_date`, `peak_date`, `trough_date`, `peak_extent_pct`, `trough_extent_pct`).
- **Excluded fields:** Phase labels and narrative/prose outputs.

## Governance & Change Control
Any modification to these baseline fixtures is strictly protected:
- Regenerating expected fixtures or altering them to pass tests is forbidden.
- Any scientific baseline change requires a new dated scientific-baseline change note reviewed separately from artifact regeneration.
- Authorizing specification: `docs/superpowers/specs/2026-08-23-baseline-preserving-seasonality-and-phase-schemes-design.md`.
