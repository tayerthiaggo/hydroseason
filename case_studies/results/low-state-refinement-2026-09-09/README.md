# End-of-low-state diagnostic, 2026-09-09

**Exploratory component experiment; no production policy changed.**

**Continuation:** the subsequent [endpoint experiment](endpoint-findings.md)
includes 2,688 synthetic and 150 real evaluations. It demonstrates why both
endpoint selection and uncertainty require refinement; the prototype is not
accepted for production integration.

The agreed objective is an HY boundary at the final supported low-state month
before sustained recovery. This experiment asks whether increasing the current
refinement's scale alone can achieve that objective.

## Reproduction

From the repository root:

```powershell
.\.venv\Scripts\python.exe case_studies/results/low-state-refinement-2026-09-09/probe.py
```

Inputs: raw Daly and Fitzroy 30 m monthly counts and published full annual tables
from `final-review-2026-09-08/after/refinement`. Preparation uses the existing
20% invalid threshold and `flag` policy. Published peak dates, interval evidence
and quality are fixed. The existing candidate tuple is unchanged:
`huber_k=1.345`, `profile_loss_cutoff=0.05`, `pulse_z=1.5`.

`scale-sensitivity.csv` contains 60 evaluations: nine selected Daly years and
all 21 Fitzroy annual rows, each under two scenarios. Rows with unavailable or
open-span evidence are retained. `manifest.json` records policy, input/source
hashes and output hash. `probe.py` is an exploratory analysis artifact.

Scenarios:

- `existing`: zero explicit measurement tolerance, as in the published run.
- `record_floor_sensitivity_only`: inject each catchment's published
  `detectability_floor_pp` through the existing tolerance argument. Daly's value
  is approximately 0.022260104 pp; Fitzroy's is 0.014825342 pp.

The record floor may contain genuine hydrological variability. It is not an
independently validated measurement-error estimate. This scenario is a
sensitivity experiment, not calibrated policy selection.

## Findings

| Case | Existing challenger | Injected-floor challenger | Interpretation |
| --- | --- | --- | --- |
| Daly 2008 | October; October support | October; October-November support | Broader support does not move the exact optimum. |
| Daly 2019 | November; November support | November; August-December support | December is supported, but not selected. |
| Daly 2018 | Unresolved, unstable quality sensitivity | Provisional January 2019, interval-peak reason | Scale changes can change status and shift a boundary undesirably. |
| Fitzroy 2019 | Provisional December | Unresolved, boundary set too broad | Increased tolerance can remove a previously available answer. |

Across Daly's nine rows, the endpoint-support set changes in six and the
operational challenger changes in one. Across Fitzroy's 21 rows, support changes
in 19 and the operational challenger changes in one. A null-to-date or
date-to-null change counts as an operational change.

The baseline reproduces the published refinement status, reason and local scale
for all 30 rows (scale absolute difference below 1e-12 pp). This is a bounded
reproduction check, not proof that every published field was reproduced.

These are challenger outputs. The production integration's atomic adjacent-cycle
acceptance was not rerun. A changed challenger is not necessarily an accepted
HY boundary, and no historical report has been regenerated or overwritten.

**Conclusion:** examine both the scale assumption and the endpoint decision.
Neither increasing the scale alone nor blindly selecting the last profile
endpoint supplies a validated end-of-low-state rule.

See the [method refinement design](../../../docs/superpowers/specs/2026-09-09-end-of-low-state-refinement-design.md).
