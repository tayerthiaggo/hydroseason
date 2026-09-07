# Blinded Trough Refinement Span Cohort Review Rubric

## Review Unit

The unit of human review is a **single annual cycle span** within an anonymized
catchment. Reviewers inspect a time-series packet containing only allowable
observation columns (`date`, `extent_pct`, `invalid_pct`, `quality_state`, pixel
counts where available, and the span window `span_start` / `span_end`).

Every model output is strictly hidden: both the pass-1 and pass-2 boundaries,
the refinement status and reason, boundary candidates, low-state and recovery
markers, detected pulse months, station identifiers, regime and route
classifications, timing statuses, and all calibration fingerprints.

All cycles in a sampled catchment are labelled. Cycles are never selected
individually, because selecting them on any property visible after the fact
would make the sample outcome-dependent.

## The question the reviewer answers

For this span, **when did the water body reach its annual low point, and how
precisely can that be stated from the observations alone?**

The reviewer is not asked to agree or disagree with any algorithm. They are
asked to state what the data supports.

## Available Labels

1. **`point_supported`** — the span contains a distinct annual low that can
   defensibly be pinned to a single calendar month. Neighbouring months are
   materially higher, so naming one month is honest rather than arbitrary.

2. **`interval_supported`** — the span contains an identifiable annual low, but
   it is spread across two or more adjacent months that are not distinguishable
   from one another. The reviewer records the interval's first and last month.
   The low is real and localised; the exact month within the interval is not
   recoverable.

3. **`no_boundary_supported`** — no defensible annual low exists in this span.
   Typical causes: a flat or near-flat record, a wide diffuse plateau with no
   coherent recession and recovery, or missingness that removes the low itself.
   Abstention is the correct algorithm behaviour here.

4. **`uncertain`** — the reviewer cannot reach a confident determination.
   Reserved for genuine border conditions, not for mild difficulty.

## Interval labels

When labelling `interval_supported`, record `interval_start` and `interval_end`
as month-start dates. A predicted boundary inside that interval scores distance
zero; a predicted boundary outside scores the calendar-month distance to the
nearest edge. This is the only distance rule; it is fixed before unblinding.

## Review Protocol and Quality Control

- **Primary review.** Every packet is labelled independently by a reviewer
  blind to catchment identity and to both algorithms' output.

- **Double review.** At least **20% of labelled spans, and never fewer than
  30 spans**, receive an independent second blind review. The double-reviewed
  subset is drawn before any labelling begins, from the frozen sampling seed.

- **Adjudication.** Every disagreement between the two reviewers is adjudicated
  by a third independent reviewer. Evaluation refuses to run while any
  double-reviewed span remains unadjudicated — a partially adjudicated cohort
  is not a cohort.

- **Freezing.** The completed label file is hashed and frozen **before** any
  algorithm output is revealed. The evaluator refuses to run against a label
  file whose hash has moved.

- **No expansion after unblinding.** If the cohort yields fewer than **73
  algorithm point predictions** with adjudicated truth, the false-precision
  gate is not evaluable and promotion is **unavailable**. The cohort is not
  enlarged after results are seen; a smaller cohort is reported as
  unevaluable, never as passed.

## Rate denominators

- Spans labelled `uncertain` are reported in full but excluded from every
  accuracy and safety rate denominator.
- Coverage and abstention are reported over **all** eligible truth-labelled
  spans, separately from resolved-only accuracy. A method that abstains often
  and is accurate when it does answer must not be able to hide the abstention
  behind the accuracy.
- Catchment-level bootstrap intervals are the headline uncertainty, because
  cycles within one catchment are dependent. Cycle-level Wilson intervals are
  also reported, explicitly labelled as potentially optimistic.

## Direct contradiction rule

An algorithm `point` prediction on a span whose adjudicated truth is
`no_boundary_supported` is a **direct contradiction**. It is counted as a
false-precise boundary and it blocks promotion regardless of aggregate rates.
