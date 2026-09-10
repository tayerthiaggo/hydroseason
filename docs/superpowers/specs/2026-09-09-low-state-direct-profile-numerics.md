# Low-state direct-profile numerical specification

**Date:** 2026-09-09

**Status:** Stage A, Step 3 deliverable. Specifies one bounded numerical
candidate for Stage B. Not implementation-ready until its companion coding
plan (`2026-09-09-low-state-direct-profile-coding.md`) is written; not a
production change.

> **Amendment, 2026-09-10.** The equivalence margin named `delta_pp`
> throughout this document is now proportional to the low-state level:
> `delta_rel * L`, floored by the observation's physical resolution, with
> `TroughRefinementPolicy.delta_rel` replacing `delta_pp`. The solver
> recomputes the margin for each candidate `L` on the reference-level grid
> rather than holding one value fixed across the grid. Everything else in
> this specification — the profile, the common-reference rule, the global-
> optimum comparison, the support-cluster and representative-date rules —
> is unchanged. See the endpoint contract's §3 amendment and
> `docs/migrations/trough-refinement-candidate.md` for the 42-cycle review
> that motivated it.

**Depends on:** the endpoint contract (Step 1) for `sigma_pp`/`delta_pp`,
the equivalence-state target, and the representative-date convention; the
validation protocol (Step 2) for the truth fields and evaluation gates this
candidate is scored against.

**Prior evidence this specification must answer:** `endpoint-findings.md`'s
verdict that the first prototype's endpoint mapping "does not automatically
transfer the previous profile cutoff's calibration" and that a fixed
single-shape reference `L` (see `endpoint_experiment.py::_project_selected`,
`level = float(np.min(best.fitted))`) is one candidate cause, separate from
the noise-scale question.

## 1. Primary hypothesis, restated precisely

```text
T(f, L, delta) = final interior low-state month under the Step 1 §5
                 equivalence-state definition: the last interior month i
                 such that fitted[i] <= L + delta and no interior month
                 after i also satisfies that ceiling (the low run touching
                 i does not extend to either span edge).

Q(d) = min over admissible (f, L) with T(f, L, delta) = d
       of sum_t w_t * Huber((y_t - f_t) / scale)
```

The hypothesis under test: allowing `L` to vary within a **bounded,
data-justified region** around its single best-fit value, rather than fixing
it at one shape's minimum, produces better-calibrated endpoint support for
the equivalence-state target than the first prototype's fixed-`L` projection
(`endpoint_experiment.py`).

## 2. Admissibility constraints

### 2.1 Shape family `f`

Unchanged from production: `f` is a fixed-block valley — an isotonic
decreasing branch before `start`, a constant low-state block on
`[start, end]`, and an isotonic increasing branch after `end` — fitted under
weighted Huber loss with shared `scale` and `huber_k` exactly as
`_fit_valley_huber`/`_fit_valley_convex` already compute for a given
`(start, end)`. No new shape family is introduced. `start` and `end` range
over the same finite grid as today: `1 <= start <= end <= len(span) - 2`
(interior positions only, both span edges excluded, matching
`_refine_selected_span`'s existing loop bounds).

### 2.2 Reference level `L` and its relationship to the fitted valley

- **Single shared reference, per the endpoint contract's common-reference
  rule (Step 1 §8):** `L` is anchored **once per scenario**, not
  re-estimated for each candidate `(start, end)` block. The anchor `L0` is
  the block level of the single best-fitting unconstrained valley shape
  found by today's production search (`_fit_valley_huber` minimized over
  every `(start, end)`) — i.e. what production would already report as the
  low-state level absent any uncertainty. Re-deriving a separate
  `L*(start, end)` per candidate block was an earlier draft of this
  specification and was found, during Step 4 implementation, to violate the
  common-reference rule: two blocks differing only in which points they
  include could otherwise imply two different reference levels for what is
  supposed to be one physical low-water level in one scenario.
- `L` ranges over a finite, bounded grid built **once**, from `L0`, and
  reused for every `(start, end)` candidate:

  ```text
  L_grid = { L0 + j * step : j = -n_L, ..., -1, 0, 1, ..., n_L }
  step = scale / n_steps_per_scale
  ```

  with `n_L` and `n_steps_per_scale` declared numerical-research constants
  (§6), not scientific constants. `L` is never allowed outside
  `[L0 - l_uncertainty_k * scale, L0 + l_uncertainty_k * scale]`
  where `l_uncertainty_k = n_L / n_steps_per_scale`.
- **Why bounded:** an unbounded `L` lets the ceiling `L + delta` chase any
  month by moving `L` arbitrarily far from the data, making every candidate
  `d` equally "achievable" and destroying identifiability (design note:
  "check that a free reference level cannot make every endpoint fit equally
  well by moving the ceiling"). Anchoring the grid to `L*(start, end) ±
  l_uncertainty_k * scale` ties the admissible range to the same scale used
  everywhere else in the fit, so a larger noise floor widens `L`'s
  uncertainty by exactly as much as it widens everything else — no separate,
  unscaled slack is introduced.
- For each grid point, the **evaluated fit** `f` clamps the block to that
  `L` value exactly (not `L*`): `fitted = np.where(np.isfinite(branch),
  np.maximum(branch, L), L)`, mirroring `_fit_valley_convex`'s existing
  `level` substitution step, but evaluated at the swept `L` instead of only
  at the regime breakpoints `_fit_valley_convex` currently searches.
- **Equality handling at the low-state ceiling:** a month with
  `fitted[i] == L + delta` exactly counts as inside the low state (`<=`, not
  `<`), matching Step 1's worked examples (`0.123 <= 0.12 + 0.004` should be
  "in", never excluded by strict inequality); floating-point equality uses
  the same `_RELATIVE_CONVERGENCE`-scaled tolerance already used elsewhere
  in `_trough_refinement.py` (never a bare `==`).

### 2.3 Candidate dates and interior-only rule

A candidate `d` for `T(f, L, delta)` must be an interior span position
(`0 < d < len(span) - 1`), matching Step 1 §1's exclusion of the bounding
peaks. `T` returns `None` (no departure) when every interior month is
`<= L + delta`, or when the low run under the ceiling touches either edge of
the block's own admissible domain in a way that makes "final departure"
undefined (mirrors `_project_selected`'s existing `low[0] == 0 or low[-1] ==
len(span) - 1` guard, generalized to the swept-`L` grid).

### 2.4 Shared scale, objective units, and profile normalization

- `scale` is the same shared Huber scale used for the shape fit itself
  (§6 for its candidate estimators) — never a second, independently chosen
  scale for the `L`-uncertainty grid.
- The objective `Q(d)` is total weighted Huber loss in the same units as
  today's `best_loss`/`candidate.loss` (percentage-point-squared-equivalent
  Huber units), not divided by `effective_support` inside `Q` itself.
- **Profile normalization**: exactly as today, the *support* decision
  divides the loss difference by `effective_support` before comparing to
  `policy.profile_loss_cutoff`:

  ```text
  plausible(d) <=> (Q(d) - Q_global_min) / effective_support <= profile_loss_cutoff + tolerance
  ```

  where `Q_global_min` is the minimum loss across **every** `(start, end, L)`
  combination evaluated, including combinations whose `T` is undefined (a
  "no departure" / flat-band explanation) — not merely the minimum among
  combinations that happen to produce a defined `d`. Comparing only against
  the best *departure-labelled* loss lets a flat series with no real
  departure spuriously "support" a departure whose fit is only slightly
  worse than a same-loss departure-labelled alternative, while actually
  being far worse than the true (undefined-`T`) global optimum; this was
  found and fixed during Step 4 implementation (see the flat-series negative
  control, §5.3).

  (When `scale == 0.0`, use the existing exact-optimum tolerance rule
  instead, exactly as `_refine_selected_span` already branches on
  `scale == 0.0`.)

## 3. Why profile over the new target, not reuse the old constant-bottom profile

The existing `_refine_selected_span` profile already computes a support
cluster, but that cluster is a profile over **exact loss-optimal endpoint
position** at a *fixed* implicit `L` (whatever each `(start, end)`
candidate's own block level happens to be) — it never asks "how would this
support change if the low-state reference itself were uncertain." The first
prototype (`endpoint_experiment.py`) partially addressed this by mapping
each of those already-selected shapes through a *fixed* `level =
min(best.fitted)`, but that fixed level is a single point estimate from one
shape, not a profiled quantity — exactly the gap `endpoint-findings.md`
identifies ("mapping a finite set of best trough fits does not automatically
transfer the previous profile cutoff's calibration").

Profiling directly over the **new** target `T(f, L, delta)` means the
reported support set for `d` already reflects both position uncertainty
*and* reference-level uncertainty in one coherent loss surface, rather than
inheriting a support set calibrated for a different functional (the raw
endpoint position) and hoping it transfers.

## 4. Missing observations, pulse returns, uncertain peaks, and poor-quality observations

- **Missing observations (gaps):** the pre-gap-only segment logic in
  `_refine_gap_after_low_state` is reused **unmodified** as the entry point
  when `not observed.all()`. Compatibility argument: that function's
  contract is "assume the low state is fully contained before the gap, and
  verify that assumption before trusting the pre-gap boundary" — it never
  depends on which endpoint functional is being computed, only on whether
  the *pre-gap segment* admits a defensible low state and whether *post-gap*
  values are compatible with it. The new target changes what counts as
  "compatible" (equivalence-band membership under `L`/`delta` rather than
  raw Huber-loss membership under `profile_loss_cutoff`), so the one
  required change is: the post-gap comparisons in
  `_refine_gap_after_low_state` (`low_state_continues_past_gap`,
  `at_low_level`) are re-expressed in terms of the swept-`L` ceiling
  (`value <= L + delta` for the pre-gap segment's admissible `L` range)
  instead of the raw Huber-loss cutoff, and every other line — including the
  `gap_overlaps_low_state` / `gap_before_low_state` / `post_gap_return_to_low_state`
  outcome logic — is unchanged. Do not mix the new equivalence-band gap
  compatibility check with the old raw-loss gap check in the same result;
  a candidate implementation must use one or the other, never both, for a
  single span.
- **Pulse returns:** `_pulse_dates` and `_separated_clusters_are_pulses` are
  reused unmodified in their tolerance construction
  (`policy.pulse_z * scale`), but their `low_level` comparison point is the
  swept-`L`-consistent block level for the winning `(start, end, L)` triple,
  not a re-derived quantity. A pulse month is never itself an admissible
  candidate `d` (matches Step 1 Example 4).
- **Uncertain peaks:** unchanged — `left_peak.timing_status` /
  `right_peak.quality` continue to gate `status`/`reason`
  (`interval_peak`, `low_quality_peak`) exactly as `_refine_selected_span`
  already does, applied after `T`/`Q` resolve `d`, not before.
- **Poor-quality observations:** unchanged — `essential_low_quality_recovery`
  and `unknown_quality` gating apply to the resolved `d` exactly as today.
  Quality does not affect the `L`-grid construction itself; a low-quality
  month still contributes to the fit through its existing weight
  (`_support_weights`), and its quality state is judged only after `d` is
  resolved.

## 5. Identifiability demonstration (required before Step 4 implementation)

Using Step 1's worked examples (contract §8) and one flat-series negative
control, this specification requires the coding plan's test suite to
demonstrate, by direct computation (not by inspection):

1. **Example 1** (`latent = [0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40]`,
   `delta_pp = 0.004`): `T(f*, L*, delta) = 4` for the loss-minimizing
   `(start, end, L)` triple. Because 0.121 and 0.123 differ by less than
   `delta_pp` itself, index 3 also enters the support set at this scale
   under a one-grid-step-shifted `L` (its added loss is within
   `profile_loss_cutoff` of the global optimum) — this is the model
   correctly reporting genuine timing ambiguity between two values already
   within noise of each other, not a defect; the **representative date**
   (Step 1 §7) still resolves uniquely to `d = 4`, the later member of the
   cluster.
2. **Example 2** (gradual recovery): `T = 4`, and `d = 5` (the latent
   change-point-adjacent month, Step 1's contrasted diagnostic) is **not**
   in the support set — this is the specific failure mode the first
   prototype needs to avoid repeating for gradual recoveries
   (`endpoint-findings.md`: "z=1 places all 48 predictions later than the
   latent plateau endpoint").
3. **Example 3** (`latent = [0.12, 0.12, 0.12, 0.12, 0.12]`): `T(f, L,
   delta) = None` for every admissible `(f, L)` — no interior month ever
   exceeds the ceiling, so no departure is ever identified. This is the
   required flat-series negative control (design note: "failure to identify
   a departure in a flat series").
4. **Bounded-`L` check:** for Example 1, re-run with `l_uncertainty_k`
   swept from `0` up to at least `4` (§6 grid). Confirm that the resulting
   support set's width grows monotonically (or stays constant) with
   `l_uncertainty_k` but never becomes "every interior month," for any
   `l_uncertainty_k` up to the value tested. A candidate `l_uncertainty_k`
   for which the support set degenerates to the full span on this example
   fails this specification's bound requirement and must not proceed to
   Step 4's development comparison as a default.

## 6. Scale hypotheses: separating solver/support failure from scale failure

Per `endpoint-findings.md`'s explicit sequencing requirement ("use
known-noise simulation first to separate solver/support failures from
automatic-scale failures"):

1. **Stage 1 — known-noise simulation.** Run the full `T`/`Q` solver with
   `scale` supplied directly from the generator (`oracle_scale`, exactly as
   `evaluate_endpoint.py::predictions()` already threads
   `measurement_tolerance_pp=sigma`). This isolates whether the *profiling
   mechanism itself* (not scale estimation) achieves the Step 2 §7
   coverage/error gates. If Stage 1 fails on oracle scale, the profiling
   mechanism itself is rejected regardless of any automatic-scale proposal,
   per the design note's requirement not to search additional constants
   outside the predeclared budget.
2. **Stage 2 — one justified automatic-scale hypothesis**, run only if
   Stage 1 passes:

   ```text
   combined_scale = max(
       residual_scale,          # today's _local_scale residual-MAD estimator
       second_difference_scale, # endpoint_experiment.py's existing estimator
       _measurement_floor(frame),
       measurement_tolerance_pp,
   )
   ```

   **Domain of applicability, stated in advance:** `second_difference_scale`
   is included in the max only when the span has at least 4 usable months
   with at least 3 consecutive usable triples (matching its own
   finite-difference requirement); otherwise `combined_scale` reduces to
   `max(residual_scale, _measurement_floor(frame), measurement_tolerance_pp)`
   — i.e., today's existing `_local_scale`. This is a bounded, single
   named hypothesis (not a search over estimator combinations); it is
   compared once against the residual-only baseline in Step 4's development
   matrix (§7 of the validation protocol's candidate budget) and is
   rejected, not silently dropped, if it fails the frozen gates.
3. The **failed second-difference-alone estimator** (`z in {0.5, 1, 2}`,
   `endpoint-findings.md`) is retained in the development comparison as a
   labelled prior-failed control, never re-promoted as a default by this
   specification.

## 7. Constants: target-defining vs. inference-tuning

| Constant | Role | Fixed by | Calibrated against truth? |
| --- | --- | --- | --- |
| `delta_pp` | Defines the scientific target (Step 1 §3, §6) | Step 1 contract / declared value | No — target sensitivity only (Step 1 §6) |
| `huber_k` | Shape-fit robustness tuning (production default, unchanged) | Existing `TroughRefinementPolicy.huber_k` | Not by this specification |
| `profile_loss_cutoff` | Support-cluster threshold (production default, unchanged) | Existing `TroughRefinementPolicy.profile_loss_cutoff` | Not by this specification |
| `l_uncertainty_k` (`n_L`, `n_steps_per_scale`) | Numerical bound on `L`'s admissible grid — a solver/inference constant, not a scientific one | This specification | Yes, in Step 4, against frozen development data only |
| `combined_scale`'s component weights (implicit `max`) | Automatic-scale hypothesis (§6 Stage 2) | This specification | Yes, in Step 4, against frozen development data only |

`delta_pp` is never calibrated against synthetic or real truth by this
candidate; doing so would fit the target to the data used to score it,
exactly the confound Step 1 §6 exists to prevent. `l_uncertainty_k` and the
scale hypothesis are calibrated only against the Step 2 §7 frozen
development matrix, never against the reserved validation seeds/families
(Step 2 §7, §9) or the nine Daly examples (design note, "do not select them
from agreement with the nine Daly interpretations").

## 8. Source fingerprint coverage and dependency injection

- The Step 4 harness fingerprints three independent source groups, each
  hashed and frozen before outcomes are observed (extending
  `evaluate_endpoint.py::main`'s existing `source_sha256` pattern):
  1. the experimental solver module(s) named in the coding plan;
  2. the truth generator (the frozen `FAMILIES` table plus any new held-out
     families from Step 2 §9, stored in a location separate from the
     solver module so a solver change cannot silently also change truth);
  3. the scorer (`score_records`-equivalent implementation covering Step 2's
     full taxonomy in §1-§4 of the validation protocol).
- **Dependency injection, not monkeypatching:** the first prototype
  temporarily replaced `hydroseason._trough_refinement._refine_selected_span`
  in-process and required "must not run concurrently in a shared
  interpreter" (`endpoint-findings.md`). The Step 4 harness instead accepts
  the challenger function as an explicit parameter:

  ```python
  def evaluate_component(
      frame: pd.DataFrame,
      *,
      left_peak: PeakBoundary,
      right_peak: PeakBoundary | None,
      policy: TroughRefinementPolicy,
      challenger: Callable[..., TroughRefinementResult],
      measurement_tolerance_pp: float = 0.0,
  ) -> TroughRefinementResult:
      return challenger(
          frame, left_peak=left_peak, right_peak=right_peak,
          policy=policy, measurement_tolerance_pp=measurement_tolerance_pp,
      )
  ```

  `challenger` is `hydroseason._trough_refinement.refine_trough_span` for
  the `existing` candidate and the new direct-profile solver's public entry
  point (§9) for every `project_*` candidate — no global module attribute is
  reassigned, so candidates may be evaluated in any order or in parallel.

## 9. Public entry point (fixed for the coding plan)

```python
def refine_trough_span_direct_profile(
    frame: pd.DataFrame,
    *,
    left_peak: PeakBoundary,
    right_peak: PeakBoundary | None,
    policy: TroughRefinementPolicy,
    delta_pp: float,
    l_uncertainty_k: float = 2.0,
    scale_mode: Literal["residual", "combined"] = "residual",
    measurement_tolerance_pp: float = 0.0,
) -> TroughRefinementResult:
    """Direct-profile low-state-departure challenger (research candidate).

    Returns the existing ``TroughRefinementResult`` shape unchanged, so it is
    a drop-in ``challenger`` for ``evaluate_component`` (see §8) and for the
    Step 2 validation protocol's ``predictions()``-style harness. Never
    called from production ``analyze_hydrological_state``/
    ``detect_dynamic_hydrological_years`` paths.
    """
```

`delta_pp` has no default — callers must supply the Step 1-fixed value
explicitly, so it can never silently take on an implementation default.
`l_uncertainty_k` and `scale_mode` are the two numerical-research constants
from §7's table; both are keyword-only and both default to the values named
in §6/§7 so a bare call reproduces the specification's Stage-2 hypothesis.

## Exit check

- §2 defines every admissibility constraint (shape family, `L`'s relation to
  the fitted valley, candidate dates, shared scale, objective units, profile
  normalization, ceiling equality) without inventing a new scientific rule.
- §2.2 explicitly bounds `L` and explains why the bound prevents the ceiling
  from chasing an arbitrary candidate date.
- §4 states how gaps, pulses, uncertain peaks, and poor-quality observations
  enter, and gives the explicit compatibility argument required before
  mixing the new target with the old gap logic.
- §5 lists the exact identifiability demonstrations the coding plan's tests
  must reproduce, including the flat-series negative control.
- §6 sequences known-noise-first, then exactly one named automatic-scale
  hypothesis with a stated domain of applicability, retaining the failed
  second-difference-alone estimator as a labelled control, not a default.
- §7's table fixes which constants define the target (never calibrated
  against truth) versus which tune inference (calibrated only against
  frozen development data).
- §8-§9 give literal function signatures, dependency-injection contract, and
  fingerprint coverage sufficient for the coding plan to proceed without
  deciding the uncertainty rule during implementation.

If Stage 1 (§6, known-noise oracle scale) fails to identify the Step 1
worked examples correctly, or the bounded-`L` check in §5 fails, this
specification's candidate is itself falsified before Step 4's automatic-scale
comparison is run, and that finding is recorded per the design note's
falsification-first sequencing rather than patched by changing `delta_pp`.
