# Resolution Fidelity and Acquisition Evidence Study

This study evaluates the scientific impact of spatial resolution coarsening, the performance benefits of conservative wet-mask planning footprints, and the semantic distinction between the default single-mask and dual composite bundles across five Australian catchments.

## Key Findings

1. **Scientific Effect of Resolution Coarsening:** Coarsening resolution from 30 m down to 60 m, 90 m, or 300 m alters surface water extent precision and regime classification. The effect is not uniform across the candidates. **60 m reproduces the 30 m result closely**: it routes all five catchments identically to 30 m (5/5 route agreement), correlates at 0.9997 with median nMAE 0.0030, and places every peak and trough within one month. It misses the pre-declared gate set on one criterion only — a maximum event-count delta of 2 against a declared ceiling of 1. **90 m and 300 m degrade substantively**: for low-SNR catchments (e.g., Lachlan River) both distort seasonal signal detection, causing route classification mismatches (`event_characterisation` vs `per_year_detection`). Strictly, no coarsened candidate clears every pre-declared gate, so 30 m remains the release standard; but 60 m is the only candidate whose disagreement with 30 m is confined to a single discrete count.
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
| 60 m | 5/5 | 0.9997 | 0.0030 | 100.0% | 100.0% | 2 | 2 | False |
| 90 m | 5/5 | 0.9991 | 0.0058 | 100.0% | 100.0% | 2 | 3 | False |
| 300 m | 4/5 | 0.9907 | 0.0198 | 95.2% | 90.5% | 5 | 6 | False |
<!-- END GENERATED RESOLUTION RESULTS -->

> [!NOTE]
> **Decision Rationale:** All candidate coarsened resolutions fail one or more pre-declared scientific quality gates (route agreement 5/5, median correlation ≥ 0.995, median nMAE ≤ 0.05, max event delta ≤ 1, max low spell delta ≤ 2 months). The gates were fixed before the results were computed and have not been revised in light of them, so 30 m spatial resolution is maintained as the single release standard for HydroSeason.
>
> **Practical reading of the 60 m result.** 60 m fails on one criterion, by one event, while agreeing with 30 m on every routing decision and placing all peaks and troughs within a month. For a user who is compute- or bandwidth-constrained on a **large** catchment, 60 m is a defensible working resolution: it will not change which analysis route a catchment takes, and its extent series tracks the 30 m series almost exactly. It is not endorsed as equivalent, and it is not the release default.

> [!WARNING]
> **Coarsening penalty scales inversely with AOI size.** These five catchments are large; every result above is measured on them. The coarser the pixel relative to the catchment, the greater the share of the water signal that a single pixel decides — so on a **small** AOI, or one dominated by narrow channels rather than broad floodplain, 60 m will distort extent considerably more than this table implies, and the 30 m default matters correspondingly more. Do not generalise the 60 m result to a small AOI without re-running this study against it.

## Acquisition Performance and Pruning

<!-- BEGIN GENERATED ACQUISITION RESULTS -->
| Pruning Mode | Analysis Resolution | Median Speedup | Median Peak RSS (MB) |
|---|---|---|---|
| `off` (Full AOI) | 30 m | 1.00x | Base |
| `planning_footprint` | 30 m | Opt-in Benchmark | Opt-in Benchmark |
<!-- END GENERATED ACQUISITION RESULTS -->

> [!IMPORTANT]
> **External Benchmark Gate:** Live Digital Earth Australia STAC acquisition
> benchmarks are opt-in performance tests that run outside ordinary offline
> CI. No historical-mask timing results have been recorded in this document.
> The harness returns nonzero for exact monthly `n_water` or containment
> mismatch, and also for deterministic execution errors. Performance is
> reported as measured evidence, never as a promised threshold.

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
