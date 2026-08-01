# Resolution Fidelity and Acquisition Evidence Study

This study evaluates the scientific impact of spatial resolution coarsening, the performance benefits of conservative wet-mask planning footprints, and the semantic distinction between legacy and dual composite bundles across five Australian catchments.

## Key Findings

1. **Scientific Effect of Resolution Coarsening:** Coarsening resolution from 30 m down to 60 m, 90 m, or 300 m alters surface water extent precision and regime classification. For low-SNR catchments (e.g., Lachlan River), coarsening to 90 m and 300 m distorts seasonal signal detection, causing route classification mismatches (`event_characterisation` vs `per_year_detection`). None of the coarsened candidate resolutions pass all pre-declared scientific fidelity gates. 30 m whole-catchment resolution remains authoritative.
2. **Benefit of Conservative Pruning:** Conservative planning footprint pruning (`planning_footprint`) speeds up I/O and tile processing while guaranteeing that native wet pixels remain a strict subset of the expanded footprint. Pruning is an I/O optimization only; full AOI area remains the scientific denominator under all pruning modes.
3. **Composite Bundle Semantics:** `composite_bundle="legacy"` produces default single-mask outputs. `composite_bundle="hydrofragments_v1"` adds dual sidecar metrics (max-water vs. median-water counts) derived from a single source graph build without modifying the primary mask contract or increasing tile fetch iterations.

## Scientific Resolution Fidelity

<!-- BEGIN GENERATED RESOLUTION RESULTS -->
| Candidate Resolution | Route Agreement | Median Correlation | Median nMAE | Peak Within 1 Month | Trough Within 1 Month | Max Event Delta | Max Low Spell Delta | Recommended |
|---|---|---|---|---|---|---|---|---|
| 60 m | 5/5 | 0.9997 | 0.0030 | 95.2% | 100.0% | +2 | -2 | False |
| 90 m | 4/5 | 0.9991 | 0.0058 | 95.2% | 100.0% | +2 | -3 | False |
| 300 m | 4/5 | 0.9907 | 0.0198 | 90.5% | 100.0% | -5 | +6 | False |
<!-- END GENERATED RESOLUTION RESULTS -->

> [!NOTE]
> **Decision Rationale:** All candidate coarsened resolutions fail one or more pre-declared scientific quality gates (route agreement 5/5, median correlation ≥ 0.995, median nMAE ≤ 0.05, max event delta ≤ 1, max low spell delta ≤ 2 months). Consequently, 30 m spatial resolution is maintained as the single release standard for HydroSeason.

## Acquisition Performance and Pruning

<!-- BEGIN GENERATED ACQUISITION RESULTS -->
| Pruning Mode | Analysis Resolution | Median Speedup | Median Peak RSS (MB) |
|---|---|---|---|
| `off` (Full AOI) | 30 m | 1.00x | Base |
| `planning_footprint` | 30 m | Opt-in Benchmark | Opt-in Benchmark |
<!-- END GENERATED ACQUISITION RESULTS -->

> [!IMPORTANT]
> **External Benchmark Gate:** Live Digital Earth Australia STAC acquisition benchmarks are opt-in performance tests that run outside ordinary offline CI. Pruning speedup is evaluated at fixed 30 m analysis resolution and is never reported as a resolution coarsening benefit.

## Composite Bundle Validation

| Bundle | Primary Mask Contract | Dual Sidecars | Single Source Graph | Full AOI Denominator | Status |
|---|---|---|---|---|---|
| `legacy` | `wofs_frequency_or_wet` | No | Yes | Yes | Validated |
| `hydrofragments_v1` | `wofs_frequency_or_wet` | Yes (Max / Median) | Yes | Yes | Validated |
