# Blinded timing-identifiability review rubric

This rubric is frozen for the independent real-catchment cohort supporting
`established_0_2_0`. Reviewers assess observations, not HydroSeason decisions.

## Allowed labels

Exactly one label is allowed for each record:

- `point_supported` — a defensible single-month extremum exists.
- `interval_supported` — a defensible bounded extremum interval exists, but no point date.
- `event_only` — water occurrence/events are observable but annual timing is not.
- `unobservable` — data quality or spatial support cannot support the water signal.
- `uncertain` — the reviewer cannot distinguish the preceding states.

No synonyms, compound labels, or blank labels are permitted. `uncertain` is an
explicit outcome, not an invitation to guess.

## Blinding and packet contents

The packet may show observation dates, `extent_pct`, pixel counts when
available, invalid coverage, quality flags, and source imagery references. It
must hide HydroSeason `regime`, `route`, timing status, confidence, and
selected thresholds. The packet must not reveal policy identifiers, threshold
fingerprints, or model output alongside the observations.

The reviewer considers whether an extremum is supported across the available
record, whether a bounded set of months is defensible, and whether only water
events can be observed. Invalid or missing coverage and unavailable spatial
support justify `unobservable` when they prevent a water-signal judgment.

## Review and adjudication

Require one reviewer: one independent reviewer labels every packet record and
records a short reason.
Before reporting, adjudicate every `uncertain` label and every model-review
disagreement. Adjudication records the final label, the disagreement reason,
and the adjudicator; it does not change the frozen thresholds.

Uncertain labels remain excluded from rate denominators and are counted
explicitly in the manifest and comparison report. Report label counts,
disagreements, adjudicated cases, and per-stratum shortfalls even when the
cohort is smaller than its requested quota.
