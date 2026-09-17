# Decision policy and scientific baseline

HydroSeason freezes a single authoritative runtime method: `hydroseason-v0.2.0` (payload SHA-256 fingerprint: `ac32ad6bcce4c30f6406bb5b4f2e205a02d56a045448706fe7d9e5f086aa4080`).

There are no competing, alternate, or unversioned runtime method policies. Earlier experimental flags, candidate selectors (including unpromoted shape-fit trough refinement, SNR routing, and opt-in seasonality selectors), and selectable policy flags have been removed. Trough refinement is frozen to direct-profile refinement (`direct_profile_combined_v1`), and seasonality classification is frozen to mandatory circular timing recurrence with the five-detectable-year guard. See [Methods Reference](methods.md) and [the 0.2.0 design](decision-policy-0.2.0.md).

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

The v0.2.0 policy design is frozen in [`decision-policy-0.2.0.md`](decision-policy-0.2.0.md). It was promoted to public policy identifier `established_0_2_0` after every gate above passed across both timing identifiability and recurrence identifiability:
synthetic calibration and untouched validation for timing identifiability (`docs/calibration/2026-09-01-timing-identifiability-calibration.json` and `docs/calibration/2026-09-01-timing-identifiability-validation.json`, false precise-boundary Wilson upper bound `1.2e-4 <= 0.05`); synthetic calibration, untouched validation, and the promotion decision record for recurrence identifiability (`docs/calibration/2026-09-03-recurrence-identifiability-calibration.json`, `docs/calibration/2026-09-03-recurrence-identifiability-validation.json`, and `docs/calibration/2026-09-03-recurrence-identifiability-promotion.json`); the five protected catchments' outcomes unchanged; no confirmed baseline anchor from an unresolved row; the three motivating records' qualitative checks; and the timing cohort review (`case_studies/results/timing-identifiability/comparison-report.json`).
In the frozen release, this established policy is shipped as the sole runtime method `hydroseason-v0.2.0`.
`established_0_1_1` remains the historical baseline these gates were measured against; it is no longer the published policy identifier.
