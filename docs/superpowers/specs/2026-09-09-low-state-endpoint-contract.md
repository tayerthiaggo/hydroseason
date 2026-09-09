# Low-state endpoint contract

**Date:** 2026-09-09

**Status:** Stage A, Step 1 deliverable. Defines the estimand only. No numerical
solver, automatic margin, or production behavior change is authorized here.

**Owner:** analyst/implementer draft. Hydrological interpretation choices
already agreed (see
[design](../../../docs/superpowers/specs/2026-09-09-end-of-low-state-refinement-design.md))
are recorded, not re-litigated.

## 1. Operational target

The operational target is: **the final interior month of the supported
seasonal low state before sustained surface-water recovery, within an
eligible closed peak-to-peak span.**

"Interior" excludes the span's bounding peaks themselves. "Sustained" means
the departure is not reversed by a later observed or supported return to the
low state (a pulse). "Supported" means the month is inside the low-state
equivalence band defined in §3, not merely below some arbitrary rank.

This is the same objective already approved in the design note; this
document only makes it identifiable and separates it from quantities it is
routinely confused with.

## 2. Quantities that must stay distinct

| Quantity | Definition | Existing/contract name |
| --- | --- | --- |
| Observed minimum | The minimum `extent_pct` under the stated observation-quality rule and search domain, whatever its quality. It may be a poor-quality observation and is never itself the endpoint. | `raw_trough_month` / `raw_trough_extent_pct` |
| Latent low-water level `L` | The unobserved seasonal floor implied by the fitted valley shape for one scenario — a model quantity, not a directly measured one. | fitted valley's low-state block level |
| Low-state occupancy | The full contiguous span (start through end month) that the fitted/selected low state actually covers, independent of how confidently its endpoint is pinned down. A long occupancy can still have a well-resolved endpoint; a short one can have an uncertain endpoint because of missing data. | `low_state_start` / `low_state_end` |
| Endpoint support | The set of interior months that remain statistically plausible final-departure months under the declared loss and cutoff — timing uncertainty, not occupancy. | `boundary_candidates` (final cluster) |
| Operational representative date | The single date used for temporal partitioning when the endpoint is not uniquely resolved; a convention (§7), not a claim of unique physical identification. | `boundary` |
| Observed recovery evidence | Departure supported by subsequent observed values remaining outside the low-state band, not merely the calendar month after a numerical minimum. | `recovery_start` and downstream quality/pulse checks |

The equivalence margin (§3) and the timing-support machinery (§3, §6) are
what make "endpoint support" a defensible confidence-like object rather than
an artifact of which exact loss value happens to be smallest — see the
verified mismatch in the design note (`_local_scale`/`_refine_selected_span`
interaction).

## 3. `sigma_pp` and `delta_pp` are not the same object

- `sigma_pp`: an **observation/variability scale**, in extent-percentage
  points, used inside the robust fit (Huber loss, profile-support cutoff).
  It answers "how much residual scatter is consistent with a single fitted
  level, given known measurement resolution and unmodeled variability."
  Today's production `_local_scale` is one such estimator (residual MAD,
  floored by one-pixel resolution and an explicit measurement tolerance);
  the endpoint-experiment second-difference estimator is a candidate
  alternative, not yet validated.
- `delta_pp`: the **margin defining low-state equivalence** — how far above
  the latent low-water level `L` a month can sit and still count as "in the
  low state" rather than "departed." It is a scientific/operational choice
  about what counts as a materially different water level, not a statistical
  estimate of measurement noise.
- A rule of the form `delta_pp = k * sigma_pp` (for some dimensionless `k`)
  is a **model assumption**, and only that: it says the equivalence margin
  should scale with observation uncertainty. It requires its own
  justification and calibration (Step 3/Stage B) and must never be written
  into this contract, or into truth generation (Step 2), as though it were a
  definitional identity. A contract or truth definition that silently
  assumes a specific `k` has smuggled a numerical-research decision into the
  scientific target.
- Consequence for Step 2: synthetic truth must be able to express `delta_pp`
  independently of whatever `sigma_pp` a candidate solver estimates from the
  same data, so an evaluator can tell a bad `sigma_pp` estimator apart from a
  bad endpoint rule (see design note §"Compare these bounded alternatives").

## 4. What the supplied EO inputs can and cannot support

From `hydroseason/_state_input.py` and `docs/hydrological-state.md`:

- **Temporal compositing:** one value per calendar month
  (`prepare_monthly_extent` reindexes to a strict `MS` monthly index; no
  sub-monthly information is available downstream).
- **Valid-pixel denominator:** `extent_pct = 100 * n_water / n_valid` among
  valid observations inside the fixed historical-mask AOI;
  `invalid_pct = 100 * n_invalid / n_aoi` with a constant `n_aoi`. The
  resolution of one valid pixel is `100 / n_valid` percentage points for that
  month (`_measurement_floor` computes the record's median).
- **Missingness:** a month is `quality_state="missing"` when `extent_pct` is
  absent, `"unknown"` when `invalid_pct` is absent, `"low"` when
  `invalid_pct` exceeds `max_invalid_pct`, else `"usable"`. Under
  `quality_policy="flag"`, a finite value with partial invalid coverage
  still counts as `candidate_usable`; under `100%` invalid it never does.
  There is no reconstructed value for a missing month — the record has a
  true calendar gap.
- **Known observation error:** no independently supplied per-month
  measurement-error estimate exists in the input. The only directly known
  physical quantity is per-month pixel-count quantization
  (`_measurement_floor`); anything beyond that (residual scale, explicit
  user tolerance) is an assumption or a policy choice, not a measured
  instrument accuracy.
- **Available variability proxies:** residual scatter around a preliminary
  robust fit (current production `_local_scale`), local second-difference
  scatter (endpoint-experiment candidate), and a user-supplied
  `measurement_tolerance_pp` floor. None of these is validated observation
  error; each is recorded here as a proxy with a stated construction, not
  inferred sensor accuracy.

This contract records these properties as **known and unknown** inputs. It
does not infer an observation-error value from pixel counts or residual fit
sizes; that inference, if attempted, is Step 3's numerical-research question.

## 5. Target definition: equivalence-state endpoint vs. latent change point

Two distinct targets exist and must not be silently merged:

1. **Equivalence-state endpoint (working recommendation):** the final
   interior month whose value lies within `delta_pp` of the low-state
   reference level `L` for that fitted scenario. Consistent with the user's
   near-flat Daly examples, where several months are materially
   indistinguishable and only a later, larger change should count as
   recovery.
2. **Latent change-point endpoint (secondary diagnostic):** the month at
   which the underlying process last departs its shape (e.g. the last month
   of the fitted flat/valley segment before the fitted recession/recovery
   branch begins), independent of any equivalence margin. Retained only as a
   diagnostic alongside the primary target, never substituted for it.

The equivalence-state endpoint is the operational target for this
refinement. The latent change point may still be reported (e.g. for
comparison in Step 2's evaluator) but is not the quantity that endpoint
support, `boundary`, or `recovery_start` describe.

## 6. Fixing the margin independently of the scored prediction

- `delta_pp` (or the model assumption `delta_pp = k * sigma_pp` from §3) is
  fixed **before** a candidate is scored against it, from a source
  independent of that candidate's own output: a declared constant, a
  synthetic generator parameter, or a value calibrated against
  frozen development data. It is never derived from the same fitted `L` or
  loss surface being evaluated against it.
- If `delta_pp` (or `k`) is changed between experiments, the result is a
  **different scientific target**, reported as such (target sensitivity),
  never as a second, competing "estimator" of the same one true endpoint.
  Step 2's evaluator must keep target identity and candidate identity in
  separate fields so this distinction survives aggregation.
- A margin that can be moved after seeing which date a candidate would
  otherwise report is not a fixed target; this rule exists specifically to
  block that failure mode.

## 7. Representative-date convention under uncertainty

When endpoint support (§2) contains more than one month, or a calendar gap
prevents unique resolution, an **operational representative date** may still
be required for downstream partitioning (mirroring current
`boundary_candidates` → `boundary` behavior). The convention:

- The representative date is the **latest exact-optimum month within the
  final plausible cluster** (consistent with current `_refine_selected_span`
  behavior, carried forward as a convention rather than re-derived from
  scratch) — never an average, median, or earliest date, and never invented
  from a fixed calendar rule.
- Choosing this date is a **tie-breaking convention for partitioning**, not
  a claim that it is the uniquely established physical transition. Every
  output that reports a single representative date must be paired with (a)
  the full support set and (b) a status field distinguishing `confirmed`
  from `provisional`/`unresolved`, so a reader cannot mistake convention for
  certainty.
- When no interior month is supported at all (flat series, no departure), or
  the support set spans more than the allowed number of months, there is
  **no** representative date: the result must abstain (`unresolved` /
  `no_defensible_low_state` / `boundary_set_too_broad` or equivalent), not
  fall back to an arbitrary date.
- A calendar gap adjacent to the low state does not, by itself, supply
  representative-date evidence; existing gap handling
  (`_refine_gap_after_low_state`) already treats gap-adjacency as requiring
  extra evidence rather than as positive recovery signal, and this
  convention preserves that behavior for the new target.

## 8. Worked examples

All examples use the design note's illustrative `delta_pp = 0.004` (as a
fixed, externally supplied margin per §6) and, where relevant, a known
latent minimum `L = 0.12`. These are **definition checks only** — they fix
what the contract means, not a selected production margin, noise estimator,
or an instruction to treat observed EO values as noiseless truth.

**Example 1 — clean equivalence-state departure**

```text
latent = [0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40]
equivalence-state end = index 4      (0.123 is within delta_pp of L; 0.20 is not)
```

**Example 2 — gradual recovery distinguishes the two targets**

```text
latent = [0.40, 0.20, 0.120, 0.121, 0.123, 0.125, 0.14, 0.40]
equivalence-state end = index 4      (index 5's 0.125 is still within delta_pp of L)
first upward latent change = index 3 (the shape's departure begins one month earlier)
```

This is the canonical case for §5: an evaluator that only checks the latent
change point would flag index 4 as a "late" error against index 3, when both
are correct answers to *different* targets. Report against the
equivalence-state target unless the diagnostic is explicitly requested.

**Example 3 — no supported departure**

```text
latent = [0.12, 0.12, 0.12, 0.12, 0.12]
no supported seasonal departure
```

No interior month ever leaves the equivalence band. The correct result is
abstention (no endpoint, no representative date), not a forced pick of the
first or last month.

**Example 4 — pulse return (does not reset the low state)**

```text
latent = [0.40, 0.20, 0.120, 0.121, 0.30, 0.122, 0.123, 0.20, 0.40]
equivalence-state end = index 6      (0.30 at index 4 is a pulse: it returns to
                                       the equivalence band at index 5-6 before
                                       sustained recovery at index 7)
```

The reference level `L` established from the pre-pulse low-state months is
retained across the pulse (§ "common reference" rule below); the pulse month
itself is diagnostic (comparable to `pulse_months`/`n_rewetting_pulses`) and
is not itself a candidate endpoint, and does not advance or reset the
low-state reference.

**Example 5 — missing-departure example (gap prevents resolution)**

```text
latent  = [0.40, 0.20, 0.120, 0.121, 0.123,  ??? ,  ??? , 0.122]
observed = [0.40, 0.20, 0.120, 0.121, 0.123, missing, missing, 0.122]
result: unresolved (the post-gap value is itself within the equivalence band
        of the pre-gap low state, so a genuine return to the low state
        cannot be ruled out from the observed record -- calendar gaps do not
        count as positive recovery evidence)
```

A post-gap value that is a **decisive** departure (e.g. `0.40`, clearly
outside the equivalence band by a wide margin) is a different case: existing
gap handling (`_refine_gap_after_low_state`) already resolves that
provisionally at the last pre-gap month rather than abstaining outright,
because sustained recovery *is* evidenced there — only its exact month
within the gap is uncertain. Abstention (this example) is reserved for gaps
where the post-gap evidence itself cannot rule out a continued low state.
Consistent with §7's abstention rule: the boundary is not guessed by
interpolating across the gap, and the gap is not treated as if it were
recovery.

**Common-reference rule used above:** within one fitted scenario, `L` is
fixed once from the low-state block and does not drift month-by-month.
Consecutive small increments relative to the *previous* month cannot chain
into an indefinite low-state extension or an indefinite departure by
comparing each month only to its immediate neighbor; every month is compared
to the same scenario-level `L`. This directly rules out the design note's
concern about chained pairwise comparisons producing a drifting low state.

## Exit check

- §1 states one operational target sentence.
- §2's table gives six distinct quantities with non-overlapping definitions
  and their existing/contract field names.
- §3 keeps `sigma_pp` and `delta_pp` conceptually and notationally separate,
  and flags any `delta_pp = k * sigma_pp` rule as an assumption requiring
  justification.
- §4 records EO input properties as known/unknown; no sensor accuracy is
  inferred from pixel counts.
- §5 names the working target (equivalence-state endpoint) and retains the
  latent change point only as a diagnostic.
- §6 fixes the margin independently of the scored prediction and requires
  target-sensitivity reporting on any margin change.
- §7 defines the representative-date convention, including gaps, without
  claiming unique physical identification.
- §8 gives explicit results, including uncertain/absent cases, a pulse-return
  example, and a missing-departure example, all sharing one fixed reference
  per scenario.

Any automatic derivation of `delta_pp` or `sigma_pp` beyond what is written
here is explicitly deferred to Step 3 as a numerical-research question, not
a hidden default of this contract.
