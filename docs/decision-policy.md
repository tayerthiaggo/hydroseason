# Decision policy and scientific baseline

HydroSeason 0.2.0 publishes regime, route, timing-identifiability status, and hydrological years under `established_0_2_0`, using circular timing statistics of annual extrema, circular Kuiper uniformity testing, and calibrated per-year timing-identifiability thresholds. See [the 0.2.0 design](decision-policy-0.2.0.md) and [migration notes](migrations/0.2.0-timing-identifiability.md).

## Protected baseline

Daly, Fitzroy, and Gilbert are protected as seasonal/per-year case studies with their checked annual dates. Lachlan and Moonie are protected as aseasonal/event case studies. Fixtures are evidence of regression, not permission to change the result.

## Promotion gate

A replacement decision policy requires all of the following before implementation:

1. A new versioned decision-policy design.
2. Predeclared metrics and acceptance thresholds.
3. Synthetic calibration and an untouched synthetic validation partition.
4. An independent real-catchment cohort excluded from fitting and threshold selection.
5. Empirical results or published scientific evidence justifying every protected-baseline change.
6. A comparison report covering the established policy, challenger, errors, uncertainty, and known failure modes.
7. Migration notes describing changed public outputs and downstream impact.

Regenerating expected fixtures, tuning to the five protected catchments, or obtaining a better in-sample fit is not sufficient.

The v0.2.0 policy design is frozen in
[`decision-policy-0.2.0.md`](decision-policy-0.2.0.md). It was promoted to
public policy identifier `established_0_2_0` after every gate above passed:
synthetic calibration and untouched validation (false precise-boundary
Wilson upper bound `1.2e-4 <= 0.05`), the five protected catchments'
outcomes unchanged, no confirmed baseline anchor from an unresolved row, the
three motivating records' qualitative checks, and an independently reviewed
21-station real cohort (zero false precise-boundary claims, zero direct
contradictions -- see
`case_studies/results/timing-identifiability/comparison-report.json`).
`established_0_1_1` remains the historical baseline these gates were
measured against; it is no longer the published policy identifier.
