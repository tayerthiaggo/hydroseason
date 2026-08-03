# Resolution Fidelity and Acquisition Evidence Study

This study evaluates the scientific impact of spatial resolution coarsening, the performance benefits of conservative wet-mask planning footprints, and the semantic distinction between legacy and dual composite bundles across five Australian catchments.

## Key Findings

1. **Scientific Effect of Resolution Coarsening:** Coarsening resolution from 30 m down to 60 m, 90 m, or 300 m alters surface water extent precision and regime classification. For low-SNR catchments (e.g., Lachlan River), coarsening to 90 m and 300 m distorts seasonal signal detection, causing route classification mismatches (`event_characterisation` vs `per_year_detection`). None of the coarsened candidate resolutions pass all pre-declared scientific fidelity gates. 30 m whole-catchment resolution remains authoritative.
2. **Bounded historical-mask comparison:** The opt-in acquisition benchmark is
   restricted to the 2015 Fitzroy and Gilbert AOIs at 30 m in EPSG:3577. It
   compares a full-AOI reference, a planning-only workflow using a conservative
   footprint derived from the cached historical source, and the fixed
   historical-water-mask workflow. Planning remains performance-only and does
   not set a scientific denominator; only historical-mask mode applies the
   exact mask as that denominator.
3. **Composite Bundle Semantics:** `composite_bundle="legacy"` produces default single-mask outputs. `composite_bundle="hydrofragments_v1"` adds dual sidecar metrics (max-water vs. median-water counts) derived from a single source graph build without modifying the primary mask contract or increasing tile fetch iterations.

## Scientific Resolution Fidelity

<!-- BEGIN GENERATED RESOLUTION RESULTS -->
| Candidate Resolution | Route Agreement | Median Correlation | Median nMAE | Peak Within 1 Month | Trough Within 1 Month | Max Event Delta | Max Low Spell Delta | Recommended |
|---|---|---|---|---|---|---|---|---|
| 60 m | 5/5 | 0.9997 | 0.0030 | 95.2% | 100.0% | 2 | 2 | False |
| 90 m | 4/5 | 0.9991 | 0.0058 | 95.2% | 100.0% | 2 | 3 | False |
| 300 m | 4/5 | 0.9907 | 0.0198 | 90.5% | 100.0% | 5 | 6 | False |
<!-- END GENERATED RESOLUTION RESULTS -->

> [!NOTE]
> **Decision Rationale:** All candidate coarsened resolutions fail one or more pre-declared scientific quality gates (route agreement 5/5, median correlation ≥ 0.995, median nMAE ≤ 0.05, max event delta ≤ 1, max low spell delta ≤ 2 months). Consequently, 30 m spatial resolution is maintained as the single release standard for HydroSeason.

## Acquisition Performance and Pruning

<!-- BEGIN GENERATED ACQUISITION RESULTS -->
| Pruning Mode | Analysis Resolution | Median Speedup | Median Peak RSS (MB) |
|---|---|---|---|
| `full_aoi` | 30 m EPSG:3577 | Pending opt-in measurement | Pending opt-in measurement |
| `planning_only` | 30 m EPSG:3577 | Pending opt-in measurement | Pending opt-in measurement |
| `historical_mask` | 30 m EPSG:3577 | Pending opt-in measurement | Pending opt-in measurement |
<!-- END GENERATED ACQUISITION RESULTS -->

> [!IMPORTANT]
> **External Benchmark Gate:** Live Digital Earth Australia STAC acquisition
> benchmarks are opt-in performance tests that run outside ordinary offline
> CI. No historical-mask timing results have been recorded in this document.
> The harness fails only for exact monthly `n_water` or containment mismatch;
> performance is reported as measured evidence, never as a promised threshold.

## Composite Bundle Validation

| Bundle | Primary Mask Contract | Dual Sidecars | Single Source Graph | Full AOI Denominator | Status |
|---|---|---|---|---|---|
| `legacy` | `wofs_frequency_or_wet` | No | Yes | Yes | Validated |
| `hydrofragments_v1` | `wofs_frequency_or_wet` | Yes (Max / Median) | Yes | Yes | Validated |
