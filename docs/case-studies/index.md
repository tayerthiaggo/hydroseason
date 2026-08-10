# Case Studies Overview

HydroSeason includes three reproducible case studies based on 20-year Digital Earth Australia (DEA) Water Observations (`ga_ls_wo_3`) surface water extent records (2005–2025).

## 1. Main Catchment Workflow
[Main Catchment Workflow](main-workflow.md)

Demonstrates the single route-aware `analyze_catchment` workflow across five Australian catchments representing distinct hydrological regimes:
- **Daly River (NT)** – Monsoonal tropical seasonal
- **Fitzroy River (WA)** – Monsoonal tropical seasonal
- **Gilbert River (QLD)** – Gulf tropical seasonal
- **Lachlan River (NSW)** – Murray-Darling inland dryland aseasonal
- **Moonie River (QLD/NSW)** – Subtropical ephemeral aseasonal

## 2. Resolution Fidelity and Acquisition Evidence
[Resolution Fidelity and Acquisition Evidence](resolution-and-acquisition.md)

Evaluates spatial resolution coarsening (30 m baseline vs. 60 m, 90 m, and 300 m) and acquisition footprint performance:
- **Scientific Resolution Fidelity:** Shows why 30 m whole-catchment resolution remains necessary for route agreement and event accuracy.
- **Acquisition Pruning:** Documents the conservative planning footprint (`planning_footprint` / `WetPlanningFootprint`) I/O optimization.
- **Composite Bundles:** Validates the default `single_mask` bundle vs. `dual_composite_v1` dual-count composite bundles.

## 3. Rainfall Context
[Rainfall Context](rainfall-context.md)

Re-runs the same five catchments with monthly SILO rainfall attached as
ancillary context, proving rainfall is strictly additive: every water-only
column stays byte-identical to Case Study 1, and only the rainfall-
comparison columns are new.
