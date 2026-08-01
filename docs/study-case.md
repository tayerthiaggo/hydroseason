# Study case: five Australian catchments

This page shows how HydroSeason behaves on **whole-catchment** monthly
surface-water extent for five rivers spanning wet–dry tropics to intermittent
Murray–Darling systems. Use it as a reading guide for your own outputs.

**Window:** 2005-01 to 2025-12
**Source:** DEA Water Observations (`ga_ls_wo_3`) monthly composites
**Catchments:** Fitzroy (WA), Daly (NT), Gilbert (QLD), Lachlan (NSW), Moonie (QLD/NSW)

Offline rebuild (no STAC) from cached extent CSVs:

```bash
python scripts/_build_study_case_offline.py
```

Outputs land in `output/study_case/`.

---

## Why these five

| Catchment | Why it is here |
|---|---|
| **Fitzroy River (WA)** | Kimberley monsoonal benchmark; large catchment, clear wet–dry pulse |
| **Daly River (NT)** | Wet–dry tropics with stronger dry-season baseflow / springs |
| **Gilbert River (QLD)** | Flashy Gulf monsoonal system; existing science acceptance case |
| **Lachlan River (NSW)** | Regulated southern MDB river + terminal wetlands |
| **Moonie River (QLD/NSW)** | Dry, low-relief intermittent northern MDB river |

Together they force the package to answer: *when is a hydrological year real,
and when should the workflow refuse to invent one?*

---

## Headline results (2005–2025)

| Catchment | Availability regime | Recommended route | SNR | Peak phase IQR (mo) | Complete dynamic HY | Wet events | Longest low spell (mo) |
|---|---|---:|---:|---:|---:|---:|---:|
| Fitzroy (WA) | **seasonal** | per-year detection | 3.64 | 1.0 | 16 | 19 | 8 |
| Daly (NT) | **seasonal** | per-year detection | 3.80 | 1.0 | 12 | 22 | 6 |
| Gilbert (QLD) | **seasonal** | per-year detection | 3.32 | 1.0 | 17 | 30 | 8 |
| Lachlan (NSW) | **aseasonal** | event characterisation | 0.96 | 4.0 | —* | 12 | 30 |
| Moonie (QLD/NSW) | **aseasonal** | event characterisation | 0.59 | 3.0 | —* | 14 | 21 |

\*Dynamic HY tables can still be produced with an **explicit** trough month for
exploration, but `analyze_catchment` correctly returns **no hydrological
years** for aseasonal records. Trust the regime route over forced HY labels.

Mean peak / trough extent on dynamic complete years (whole-catchment
`extent_pct`, not reach-scale wet-AOI):

| Catchment | Mean peak % | Mean trough % | Mean amplitude (pp) |
|---|---:|---:|---:|
| Fitzroy (WA) | 0.67 | 0.04 | 0.63 |
| Daly (NT) | 0.71 | 0.12 | 0.58 |
| Gilbert (QLD) | 1.54 | 0.11 | 1.44 |
| Lachlan (NSW)* | 0.76 | 0.24 | 0.51 |
| Moonie (QLD/NSW)* | 0.31 | 0.07 | 0.24 |

\*Exploratory dynamic numbers only — route is events, not HY.

---

## How to interpret the routes

```text
assess_water_regime(extent)
        │
        ├─ seasonal  ──────────► per_year_detection
        │                         (detect HY boundaries each year)
        ├─ marginal  ──────────► fixed_climatological_window
        │                         (one window from climatology; labelled imposed)
        └─ aseasonal ──────────► event_characterisation
                                  (wet events + dry spells only; no HY)
```

### Seasonal (Fitzroy, Daly, Gilbert)

- **SNR ≥ ~2** and peaks cluster in calendar time (phase IQR ≤ ~1.5 months).
- Per-year peak and trough are reproducible → hydrological years are meaningful.
- Read:
  - **peak_extent_pct** — wet-season inundation high-water mark
  - **trough_extent_pct** — late dry-season residual water (refuge signal at catchment scale is weak; use reach/pool AOIs for refuge work)
  - **amplitude** — how much the surface-water store breathes each year
  - **confidence / boundary_status** — whether that year's boundary is confirmed

**Manager takeaway:** compare years on a hydro-year axis, not calendar year.
A “dry year” is a low peak and/or low trough on the hydro-year, not “low
January–December mean”.

### Aseasonal (Lachlan, Moonie)

- SNR low and/or peak month jumps around years.
- Forcing a wet/dry HY invents structure the data do not support.
- Read instead:
  - **n_wet_events**, duration, recurrence
  - **longest_low_spell_months**
  - years without a wet event

**Manager takeaway:** report event frequency and dry-spell length. Do **not**
publish “HY 2019 wet season failed” language when no HY exists.

---

## What whole-catchment extent can and cannot say

**Can**

- Show whether an annual surface-water cycle is present
- Compare timing and relative wet/dry extremity across years
- Flag data-quality months (`invalid_pct`) that should not drive trough picks
- Route analysis automatically so operators do not guess the method

**Cannot**

- Measure discharge, depth, volume, or soil moisture
- Prove ecological condition from high trough % alone
- Separate climate from regulation/extraction/farm dams
- Resolve narrow channels or vegetated water that optical classifiers miss
- Replace a pool-scale AOI analysis for persistent-pool management

For refuge / pool questions, clip to a wet-AOI or pool complex first, then
rerun. Catchment `%` dilutes local water to near-zero even when channels hold
water.

---

## Output files (easy CSV layout)

All study-case exports use named columns and rounded values.

### `*_monthly_extent.csv`

| Column | Meaning |
|---|---|
| `date` | Month start (YYYY-MM-DD) |
| `extent_pct` | Water pixels / AOI pixels × 100 |
| `wet_fill_pct` | Water relative to ever-wet mask (if computed) |
| `invalid_pct` | Cloud/shadow/no-data share of AOI (%) |
| `n_water`, `n_valid`, `n_aoi` | Pixel counts for audit |

### `*_hydro_years.csv` (dynamic complete years)

| Column | Meaning |
|---|---|
| `hy_year` | Hydro-year label |
| `hy_start`, `hy_end` | Cycle bounds |
| `peak_month`, `peak_extent_pct` | Wet peak |
| `trough_month`, `trough_extent_pct` | Dry trough |
| `cycle_months` | Length of cycle |
| `confidence` | high / medium / low |
| `boundary_status` | confirmed / provisional |
| `recharge_condition`, `refuge_condition` | Rank labels vs baseline |

### `*_summary.csv` (one row per catchment)

From `CatchmentAnalysis.summary_row`: regime, route, SNR, phase IQR, event
stats, climatological peak/trough months.

### `*_report.html`

Self-contained manager report: KPI cards, extent chart, climatology, expandable
year cards. Quality warnings sit in a **banner**, not the title.

### Cross-catchment table

`study_case_summary.csv` — one row per catchment for slides/tables.

---

## Reproduce

```bash
# 1) If you already have extent CSVs under output/water_extent_csv/
python scripts/_build_study_case_offline.py

# 2) Or rebuild extents from STAC (network, slow)
python scripts/run_multi_catchment_report.py --only fitzroy_river_wa,daly_river_nt,gilbert_river_qld,lachlan_river_nsw,moonie_river_qld_nsw
```

---

## Related reading

- [Dynamic hydrological state](hydrological-state.md) — trough diagnostics and condition labels
- [Usage guide](guide.md) — loaders and detection config
- Tayer et al. (2026) methodological paper — DOI in [Citation](citation.md)
