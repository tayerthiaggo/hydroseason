# Resolution Fidelity and Acquisition Evidence Study

This study evaluates the scientific impact of spatial resolution coarsening, the performance benefits of conservative wet-mask planning footprints, and the semantic distinction between the default single-mask and dual composite bundles across five Australian catchments.

## Key Findings

1. **Resolution coarsening:** All three coarser resolutions (60, 90, 300 m)
   route every catchment the same way as 30 m (5/5). What changes is the
   detail. **60 m tracks 30 m closely** (median correlation 0.9997, median
   nMAE 0.0030, every peak and trough within one month, at most one event
   different) but misses the pre-declared gate on one criterion: its longest
   low spell differs by up to 3 months against a ceiling of 2. **90 m** fails
   the same criterion by more (4 months). **300 m** also fails on correlation
   (0.9907 < 0.995) and event count (up to 3 events different), and places
   only 95.2% of peaks and troughs within a month. No coarsened resolution
   clears every gate, so 30 m remains the release standard.
2. **Bounded historical-mask comparison:** The opt-in acquisition benchmark is
   restricted to the 2015 Fitzroy and Gilbert AOIs at 30 m in EPSG:3577. It
   compares a full-AOI reference, a planning-only workflow using a conservative
   footprint derived from the cached historical source, and the fixed
   historical-water-mask workflow. Planning remains performance-only and does
   not set a scientific denominator; only historical-mask mode applies the
   exact mask as that denominator.
3. **Composite Bundle Semantics:** `composite_bundle="single_mask"` (the default) produces single-mask outputs. `composite_bundle="dual_composite_v1"` adds dual sidecar metrics (max-water vs. median-water counts) derived from a single source graph build without modifying the primary mask contract or increasing tile fetch iterations.

## Scientific Resolution Fidelity

<!-- BEGIN GENERATED RESOLUTION RESULTS -->
| Candidate Resolution | Route Agreement | Median Correlation | Median nMAE | Peak Within 1 Month | Trough Within 1 Month | Max Event Delta | Max Low Spell Delta | Recommended |
|---|---|---|---|---|---|---|---|---|
| 60 m | 5/5 | 0.9997 | 0.0030 | 100.0% | 100.0% | 1 | 3 | False |
| 90 m | 5/5 | 0.9991 | 0.0058 | 100.0% | 100.0% | 1 | 4 | False |
| 300 m | 5/5 | 0.9907 | 0.0198 | 95.2% | 95.2% | 3 | 6 | False |
<!-- END GENERATED RESOLUTION RESULTS -->

!!! note "Decision rationale"
    Every coarsened resolution fails at least one pre-declared gate (route
    agreement 5/5, median correlation ≥ 0.995, median nMAE ≤ 0.05, max event
    delta ≤ 1, max low-spell delta ≤ 2 months). The gates were fixed before the
    results were computed and have not been revised, so 30 m stays the single
    release standard.

    **Practical reading of the 60 m result.** 60 m fails one criterion, by one
    month of low-spell duration, while agreeing with 30 m on every route and
    placing all peaks and troughs within a month. For a compute- or
    bandwidth-constrained run on a **large** catchment, 60 m is a defensible
    working resolution. It is not endorsed as equivalent and is not the
    default.

!!! warning "Coarsening penalty grows as the AOI shrinks"
    These five catchments are large. On a **small** AOI, or one dominated by
    narrow channels rather than broad floodplain, each coarse pixel decides a
    bigger share of the water signal, so 60 m will distort extent much more
    than this table implies. Do not generalise the 60 m result to a small AOI
    without re-running this study on it.

## Acquisition Performance and Pruning

<!-- BEGIN GENERATED ACQUISITION RESULTS -->
| Pruning Mode | Analysis Resolution | Median Speedup | Median Peak RSS (MB) |
|---|---|---|---|
| `off` (Full AOI) | 30 m | 1.00x | Base |
| `planning_footprint` | 30 m | Opt-in Benchmark | Opt-in Benchmark |
<!-- END GENERATED ACQUISITION RESULTS -->

!!! note "Opt-in benchmark"
    Live DEA STAC acquisition benchmarks run outside offline CI, and no timing
    results are recorded here yet. The harness
    (`scripts/benchmark_wofs_cache.py`) fails on any monthly `n_water` or
    containment mismatch; performance numbers are reported as measurements,
    never as promised thresholds.

## Composite Bundle Validation

A *composite bundle* selects how many composites one acquisition derives from
the same daily WOfS observations. The default, `single_mask`, derives one: the
primary majority-vote (median-water) mask that every hydroseason result is
computed from. `dual_composite_v1` additionally derives a second, any-day-wet
(max-water) composite from the *same* already-resident daily observations —
no second STAC query, no second classification pass — and persists it as
per-month pixel counts in a parallel `years/<year>/dual_extent_counts.json`
sidecar, read back via `open_completed_dual_extent_counts`. The max-water
counts exist for downstream fragment/connectivity analysis; hydroseason itself
never reads them.

This table records what that validation asserts: enabling the second composite
is **purely additive**. It does not alter the primary mask contract, does not
change the denominator any metric is computed against, and does not cost an
extra source graph build or extra tile fetches.

| Bundle | Primary Mask Contract | Dual Sidecars | Single Source Graph | Full AOI Denominator | Status |
|---|---|---|---|---|---|
| `single_mask` | `wofs_frequency_or_wet` | No | Yes | Yes | Validated |
| `dual_composite_v1` | `wofs_frequency_or_wet` | Yes (Max / Median) | Yes | Yes | Validated |
