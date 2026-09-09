# Endpoint experiment: findings and disposition

**Status: useful prototype, not acceptable for production adoption.**

The initial scale-only experiment showed that a larger noise floor broadens
support but can leave an exact minimum selected. This second experiment tested
a change to the endpoint itself, using the existing robust valley solver and
the existing peak/quality sensitivity machinery.

## What was implemented

`endpoint_experiment.py` is a research-only module, outside the package. In a
single process it temporarily substitutes the selected-span challenger while
reusing the production sensitivity wrapper, then restores the original callable
in `finally`. It must not run concurrently in a shared interpreter. No package
source, production default or historical output was changed.

For each complete selected span, the prototype:

1. Fits the existing Huber valley candidates using a common scale.
2. Retains the existing final profile-support cluster and its supported shapes.
3. Uses the best shape's minimum as a fixed scenario reference level `L`.
4. Defines a low-state ceiling `L + z * scale`.
5. Maps each supported fitted shape to its final month below that ceiling,
   provided a departure and an interior low state exist.
6. Uses the best shape's mapped endpoint operationally and the set of mapped
   endpoints as experimental timing support.

The reference does not drift with successive months or candidate shapes. This
is why a sequence of individually small increases eventually leaves the state.
The gap branch retains the existing conservative gap result; it is not a newly
implemented profile of low-state departure across missing observations.

Two automatic scales were compared: the current residual scale and a second-
difference scale, floored by the current residual/measurement rules. The latter
uses `1.4826 * MAD(second differences) / sqrt(6)` on consecutive usable triples.
Its variance normalization assumes independent errors and a locally linear
signal. Changing curvature, temporal dependence and short records challenge
that assumption. It is a detrended variability estimate, not established EO
measurement accuracy.

An oracle comparator supplies the known simulation noise sigma. It is not
available for real inputs and is not a deployable candidate.

## Verification and experimental scope

- Twelve hand-checked prototype/scoring tests and all thirty existing trough
  tests pass: **42 tests passed**. Four new boundary/state counterexamples were
  first demonstrated to fail against the baseline wrapper. Separate failing
  tests preceded the noise estimator and score implementation.
- The prototype retains the three near-flat months when a tolerance of 0.004 pp
  is explicitly supplied in the fixture; that illustrative value is not a
  selected scientific default.
- An exact plateau has a duration but a single resolved departure endpoint.
- A flat series without departure cannot yield a confirmed experimental
  boundary.
- Quality sensitivity still challenges a low-quality month; scale changes leave
  dates invariant when values and supplied tolerance are scaled together.
- A frozen development matrix contains **384 cases and seven scenarios**:
  **2,688 component evaluations**. Eight shape families cross eight noise
  realizations, three noise scales and two temporal-dependence settings.
- **150 real component evaluations** cover nine Daly years and all 21 Fitzroy
  rows under five non-oracle scenarios.
- Input/package hashes, all output hashes, stored scores and thirty published
  baseline status/reason/scale comparisons were verified.

The experiment configuration was saved before evaluating outcomes. Seeds from
100000 upward remain reserved and were not evaluated. Variants share seeds;
zero-noise variants repeat observations. Counts and rates are descriptive
development results, not independent-sample confidence statements.

## Controlled results

The primary target is the known latent plateau endpoint. Timing-support coverage
counts abstentions as noncoverage among the 288 cases with resolvable truth.

| Scenario | Timing-support coverage | P90 absolute endpoint error, months |
| --- | ---: | ---: |
| Existing candidate | 63.5% | 4.0 |
| Existing candidate with oracle scale | 75.0% | 3.0 |
| Projected endpoint, existing residual scale | 69.1% | 4.0 |
| Projected endpoint, second differences, z=0.5 | 67.4% | 2.0 |
| Projected endpoint, second differences, z=1 | 78.1% | 3.0 |
| Projected endpoint, second differences, z=2 | 64.9% | 4.0 |
| Projected endpoint, oracle scale, z=1 | 80.2% | 2.0 |

No tested scenario reaches the design's 95% support-coverage target. These are
new stress cases with a more specific endpoint target than the previous corpus;
the baseline figures are not a rerun or invalidation of its published validation
metrics. In particular, synthetic flat-series negative controls supply nominal
peaks directly to the component; the full regime/peak pipeline is not evaluated.

The second-difference estimator absorbs some genuine shape curvature into its
scale. In the gradual-recovery family, z=1 places all 48 predictions later than
the latent plateau endpoint, with no support set containing that endpoint.
Increasing z does not resolve that problem.

### Check that the benchmark targets the intended quantity

Ending a latent flat plateau and exiting an operational equivalence band are
different targets. Some delay relative to the first is expected when changes
remain below the declared tolerance.

A separately labelled, post-inspection sensitivity analysis therefore defines
the truth as the last latent month within **one known simulation sigma** of the
latent minimum. This target is computed from the generator, never from a fitted
curve or estimated scale. The same target is used for all scenarios.

Under this target, support coverage is 78.1% for the second-difference z=1
prototype and 80.6% for the oracle-scale z=1 prototype. The conclusion remains:
the current support construction is insufficient. The supplement is development
analysis, not fresh held-out validation or a changed historical score.

## Real-case behavior

With second differences and z=1:

- **Daly 2008:** October becomes November, matching the proposed final low month.
- **Daly 2019:** November becomes December, also matching the proposed endpoint.
- **Daly 2005, 2011, 2018 and 2020:** quality sensitivity remains unresolved in
  the challenger. Existing fallback dates are separate outputs.
- **Daly 2012 and 2014:** the challenger becomes unresolved under quality
  sensitivity rather than forcing the suggested date.
- **Daly 2016:** December remains selected; this prototype does not deliver the
  user's November interpretation.

These are experimental challenger dates and internal statuses, not accepted
two-cycle HY outputs or independently validated labels. Matching two familiar
examples is not a scientific acceptance criterion.

## Decision

Retain the agreed end-of-low-state objective. Do not integrate this prototype or
promote its scale or support rule.

The investigation separates two requirements:

1. The scale must distinguish observational variability from real recession and
   recovery. A local second-difference estimate alone is not sufficient in these
   short, curved spans.
2. Endpoint support must quantify uncertainty in the **new endpoint functional**.
   Mapping a finite set of best trough fits does not automatically transfer the
   previous profile cutoff's calibration. Even the oracle-scale comparator does
   not meet the coverage target.

The next numerical investigation should directly profile the low-state departure
quantity, including uncertainty in its reference level, and recalibrate that
support under declared observation assumptions. Retain the same robust valley,
regime routing and quality/cycle safeguards. Do not attempt to recover coverage
by rounding, choosing the last profile date unconditionally, or tuning to Daly.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m pytest case_studies/results/low-state-refinement-2026-09-09/test_endpoint_experiment.py tests/test_trough_refinement.py -q
.\.venv\Scripts\python.exe case_studies/results/low-state-refinement-2026-09-09/evaluate_endpoint.py
.\.venv\Scripts\python.exe case_studies/results/low-state-refinement-2026-09-09/supplement/assess_estimand.py
.\.venv\Scripts\python.exe case_studies/results/low-state-refinement-2026-09-09/supplement/verify.py
```

The runner refuses a changed frozen configuration or source manifest. A new
numerical experiment needs a separate identity and output location.
