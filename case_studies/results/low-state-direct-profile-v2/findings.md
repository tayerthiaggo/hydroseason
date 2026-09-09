# Direct-profile candidate: Stage B, Step 4 development findings

**Date:** 2026-09-09

**Status:** development evidence only. Frozen development matrix (Step 2
protocol, section 7 budget), **not** independent validation. Reserved seeds
(100000+), reserved held-out families, and the blinded real-cohort workflow
are untouched. Do not describe this as publication-ready or as evidence for
default-policy promotion.

## What was implemented

`direct_profile.py` implements the Step 3 numerical specification: profile
the equivalence-state departure `T(f, L, delta_pp)` over a joint
`(start, end, L)` grid, with `L` anchored once per scenario at the
production-style best-fitting valley's block level (`_natural_reference_level`)
and swept within `±l_uncertainty_k * scale` (default `l_uncertainty_k=2.0`,
`n_steps_per_scale=4`) — see the numerics spec, revised section 2.2, for why
a single shared anchor (not a per-block anchor) is required by the endpoint
contract's common-reference rule.

Two scale hypotheses were compared, per numerics spec section 6:

- `direct_profile_residual`: today's production residual-MAD scale
  (`_local_scale`), deployable on real EO input.
- `direct_profile_combined`: `max(residual_scale, second_difference_scale,
  measurement_floor, measurement_tolerance_pp)`, restricted to spans with at
  least 3 consecutive finite second differences (numerics spec section 6,
  Stage 2), also deployable on real EO input.

`direct_profile_oracle_scale` (known simulation sigma) and `existing`/
`existing_oracle_scale` (production baseline) are retained as non-deployable
or frozen-baseline comparators, exactly as the first prototype's development
matrix did.

16 unit/integration tests in `test_direct_profile.py` pass (Task 1-4 of the
coding plan), plus the full existing `tests/test_trough_refinement.py` and
`tests/test_trough_refinement_calibration.py` suites (46 tests) and the first
prototype's 12 tests (`test_endpoint_experiment.py`) -- 62 tests total, no
regressions in production code (no file under `hydroseason/` was modified).

## Development-matrix result (`direct-profile-synthetic-summary.csv`)

8 families x 8 seeds x 3 noise levels x 2 AR(1) settings = 384 synthetic
cases per candidate, `delta_pp = 0.4` (fixed, independent of any candidate's
scale, per contract section 6). Truth (`declared_endpoint_index`) is the
equivalence-state target computed from each family's latent series under
this fixed `delta_pp` (validation protocol section 1), not the first
prototype's latent-change-point truth. `gap_at_endpoint` cases whose truth
falls inside the engineered gap are excluded from the resolvable population
(`resolvable_from_observation`, validation protocol section 2) rather than
scored as if the record could resolve them.

| Candidate | Unconditional support coverage | Median abs. error (months) | P90 abs. error (months) | All-case application rate | Mean support width (months) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `existing` (frozen baseline) | 53.8% | 0.0 | 4.0 | 91.7% | 0.44 |
| `existing_oracle_scale` | 66.7% | 0.0 | 3.0 | 87.0% | 1.16 |
| `direct_profile_residual` (deployable) | 85.1% | 0.0 | 1.0 | 89.8% | 0.06 |
| `direct_profile_combined` (deployable) | **98.6%** | 0.0 | 1.0 | 90.9% | 1.26 |
| `direct_profile_oracle_scale` | 93.1% | 0.0 | 1.0 | 91.4% | 0.24 |

Frozen gates (Step 2 protocol section 7 / design note): `coverage >= 0.95`,
`median <= 1`, `p90 <= 2` months.

**`direct_profile_combined` is the only candidate in this matrix that clears
all three frozen coverage/error gates** — including against the deployable
(non-oracle) baseline requirement. `direct_profile_residual` substantially
improves over both `existing` baselines but does not clear the 95% coverage
gate on its own.

## False precision (`no_recovery` family; descriptive count, not a gate here)

The synthetic `false_precise_unresolvable_n` denominator (validation
protocol section 8) is distinct from, and not interchangeable with, the
blinded real-cohort's Wilson-bound gate. Out of 48 `no_recovery` cases (flat
series, no true departure):

| Candidate | False-precise count / 48 |
| --- | --- |
| `existing` | 24 (50.0%) |
| `existing_oracle_scale` | 6 (12.5%) |
| `direct_profile_residual` | 8 (16.7%) |
| `direct_profile_combined` | 12 (25.0%) |
| `direct_profile_oracle_scale` | 13 (27.1%) |

`direct_profile_combined` reduces false precision by half relative to the
production baseline, but is worse on this count than `direct_profile_residual`
and both oracle variants are worse than production's own oracle variant.
This is worth attention before any promotion decision, though the design
note and endpoint-findings.md set no fixed synthetic threshold for this
count (only the real-cohort evaluator's Wilson-bound gate is numerically
fixed).

## Known scope limitations of this development pass

- The gap path (`_refine_gap_direct_profile`) always uses the residual scale
  regardless of `scale_mode`; the combined-scale hypothesis was evaluated
  only on complete (non-gapped) spans. `gap_at_endpoint` family results are
  therefore identical in structure across `scale_mode` and are excluded from
  the resolvable population entirely (see above), so this limitation does
  not affect the headline numbers, but combined-scale gap behavior is
  untested.
- Real-cohort component evaluation (the `evaluate_real()` counterpart in the
  first prototype's harness) was not run in this pass; only synthetic
  families were evaluated. Daly/Fitzroy development-case dispositions (Step
  6 requirement) are not yet produced for this candidate.
- `l_uncertainty_k` was left at its specification default (2.0) throughout;
  no sweep of this inference constant was run in this pass (numerics spec
  section 7 permits calibrating it against frozen development data, within
  budget; this remains available as a next increment if `direct_profile_combined`
  needs further characterization before Step 5).

## Disposition

`direct_profile_combined` is an **admissible candidate under the Step 2
development gates** (Step 4 exit criterion). It is not integrated,
promoted, or evaluated against reserved/held-out evidence by this document.
Per the plan, the next step is Step 5: freeze this exact candidate and its
constants, then evaluate once against the reserved synthetic seeds (100000+)
and held-out families, and separately pursue the blinded real-cohort
workflow (which requires new human-reviewed labels for this equivalence-state
target — the existing `trough-refinement-span-cohort-v1` labels were frozen
for a different target and are development evidence, not reusable here
without a new blinded round).

## Step 5 addendum: reserved-evidence validation (synthetic leg)

**Status:** frozen candidate (`frozen-candidate.json`: `direct_profile_combined`,
`delta_pp=0.4`, `l_uncertainty_k=2.0`, `scale_mode="combined"`) evaluated
once against reserved synthetic seeds (100000-100007) and two reserved
held-out (shape/noise) families never present in the Step 4 development
matrix (`validate_direct_profile.py`). This satisfies the synthetic half of
Step 5's exit criterion; the real-cohort half (independently reviewed real
spans, existing blinded-cohort workflow) is separate and still pending.

| Candidate | Coverage | Median err. | P90 err. | All 3 gates |
| --- | ---: | ---: | ---: | :---: |
| `existing` (baseline) | 54.3% | 0.0 | 3.0 | fail |
| `direct_profile_combined` (frozen) | **97.75%** | 0.0 | 1.0 | **pass** |

All three frozen gates (coverage>=0.95, median<=1, p90<=2) pass on data this
candidate's development pass never saw, including two reserved held-out
cases (`held_out_asymmetric_recession`, a shape never in the development
family table; `held_out_high_dependence` at AR(1) phi=0.9, beyond
development's {0.0, 0.7}; `held_out_high_noise` at 1.0pp noise, beyond
development's {0.0, 0.1, 0.4}) — coverage on those three held-out cases was
100%, 100%, and 87.5% respectively, versus 66.7%/62.5%/50.0% for the
baseline. False precision on the reserved `no_recovery` cases also improved
(10/48 vs 26/48 for baseline). Full per-family breakdown:
`validation-summary.csv`; raw records: `validation-records.json`; gate
verdicts and source fingerprints: `validation-report.json`,
`validation-source-manifest.json`.

**What this does and does not establish:** this is frozen, held-out
*synthetic* evidence, evaluated once per the plan's discipline (no retuning
after seeing these numbers). It does not constitute the real-cohort
independent validation the design note requires for a publication-grade
claim — that still needs newly blinded, independently reviewed real spans
(existing `trough-refinement-span-cohort-v1` labels were frozen for the old
target and are not reusable here without a fresh blinded round). It also
does not authorize production integration (Stage C) on its own.

## Stage C: integrated into production (opt-in, still not promoted)

Following the informal real-catchment spot check above (13/17 favorable),
this candidate was ported into `hydroseason/_trough_refinement_direct_profile.py`
as a second value of `TroughRefinementPolicy.candidate`
(`"direct_profile_combined"`, alongside the existing default `"shape_fit"`).
This research directory's `direct_profile.py` and its monkeypatch-based
sensitivity wrapper are superseded by that integration — the production
dispatcher (`_refine_selected_span` in `hydroseason/_trough_refinement.py`)
now routes to either candidate through the same real peak/quality
sensitivity ensemble natively. This directory's files remain as the Stage
B/5 research and evidence record; they are not imported by production code.

Full details — wiring, the frozen default policy, the unblinded
five-catchment bundle, and the nine-Daly-example disposition — are in
[`docs/migrations/trough-refinement-candidate.md`](../../../docs/migrations/trough-refinement-candidate.md#direct_profile_combined-a-second-candidate-algorithm).

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m pytest case_studies/results/low-state-direct-profile-v2/test_direct_profile.py tests/test_trough_refinement.py tests/test_trough_refinement_calibration.py -q
.\.venv\Scripts\python.exe case_studies/results/low-state-direct-profile-v2/evaluate_direct_profile.py
.\.venv\Scripts\python.exe case_studies/results/low-state-direct-profile-v2/validate_direct_profile.py
```

The evaluator refuses to run if its frozen `direct-profile-config.json` has
changed since first written; a new numerical experiment needs a new
identity, per the same discipline as the first prototype's harness. The
validator additionally refuses to run at all once `validation-report.json`
exists -- reserved evidence is evaluated once.
