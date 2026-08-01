# Manager Report + Full Monthly Export - Design Spec

> **Note:** Implemented through Task 8 of the release readiness plan (`v0.1.0-post-dea-release-readiness.md`).

**Date:** 2026-07-31
**Status:** approved-for-planning (user request: interpretable reports, light theme, Plotly, full CSVs)
**Scope:** reporting UX, CSV exports, study-case builder; not rainfall fetch rewrite

## Problem

Current study-case / package reports are suboptimal for managers:

1. **Information architecture is inverted.** Artifact `automated-catchment-workflow.html` ends with a 10-block inventory of *everything the workflow can compute*. That is an engineer catalogue, not a user story. Users drown in fields (recession dynamics, selection_support, phase_shift_months) before they know the one thing that matters: *does this catchment have a usable hydrological year, and what should I do with the water record?*

2. **HTML charts are static SVG.** Package `generate_html_report` uses `_report_svg` only. Artifact `multi-catchment-transferability-report.html` already shows the desired interaction model: **Plotly** (`cdn.plot.ly`, hover, zoom, legend toggle). Design of that multi report is serviceable but dated (dark gradient hero, dense boxes).

3. **Theme drift.** New package report is light-ish; artifacts mix light tokens with optional dark `prefers-color-scheme`. User wants **forced light theme** for deliverables.

4. **CSVs are thin.** Study-case monthly export is extract-only:
   `date, extent_pct, wet_fill_pct, invalid_pct, n_water, n_valid, n_aoi`
   Missing calculated layer from the workflow inventory:
   - monthly condition (`anomaly_pct`, `reference_median_pct`, `condition_percentile`, `quality_state`)
   - event / low-spell membership flags
   - HY labels where defined (`hy_year`, season/wet-dry assignment, peak/trough markers)
   - optional rainfall columns when present
   HY tables omit many dynamic columns already produced by `detect_dynamic_hydrological_years`.

5. **Route-blind presentation.** Same year-card UI is shown even when regime is aseasonal. Artifact workflow correctly branches (events + low spells when no HY). Package report does not.

## Goals

| Goal | Success look |
|---|---|
| Interpretable, not drowning | First screen answers 3 questions in plain language; detail is progressive |
| All workflow value, structured | Full field inventory available in CSV + collapsible Methods appendix - not front page |
| Dynamic charts | Plotly light theme; pan/zoom/hover; no dark auto-flip |
| Full monthly CSV | One row per month; extract + calculated columns; documented dictionary |
| Route-aware report | Seasonal / marginal / aseasonal layouts differ; never invent HY narrative for aseasonal |
| Rebuild study case | `output/study_case/` uses new report + new CSVs |

## Non-goals

- Redesign of detection science (regime thresholds, event hysteresis) - report consumes existing APIs
- Mandatory rainfall in v1 of new report (optional panel when rainfall frame supplied)
- Multi-catchment comparative HTML as primary deliverable (per-catchment first; multi is stretch)
- Offline-only Plotly (CDN OK for manager HTML; optional later self-host)

## Design principles

1. **Verdict first, metrics second, tables last.**
   Inspired by `water-regime-gate.html` ("Does this catchment have a usable hydrological year?") + workflow route pills.
2. **Progressive disclosure.**
   KPI strip -> 1 plain-language paragraph -> 1-2 Plotly figures -> optional details (events, HY years, methods). No 40-row open tables above the fold.
3. **One story per regime.**

| Regime | Lead story | Primary figure | Secondary |
|---|---|---|---|
| seasonal | Annual wet-dry cycle is real; compare years on hydro-year axis | extent timeline with HY spans + peak/trough markers | year strip / amplitude bars |
| marginal | Cycle weak; window is imposed - treat boundaries as assumption | same timeline, imposed badge | confidence / basis callout |
| aseasonal | No HY - use wet events and dry spells | extent + event/low-spell overlays | event duration hist + spell length |
| insufficient | Not enough clean months/years | quality timeline only | what is missing |

4. **CSV is the complete lab notebook; HTML is the briefing.**
   Never force managers to open CSV to understand the site; never force analysts to scrape HTML for numbers.
5. **Light theme locked.**
   `color-scheme: light`, `data-theme="light"`, Plotly `paper_bgcolor`/`plot_bgcolor` white / `#f8fafc`. No dark media query in shipped reports.
6. **Plain language over code names.**
   Show "Seasonal - per-year hydro years" not only `per_year_detection`. Keep machine keys in CSV and in a Methods appendix.

## Information architecture (single-catchment HTML)

```text
Header (light): title, subtitle, period, AOI note
Quality banner (only if needed)
VERDICT CARD
  big pill: Seasonal | Marginal | Aseasonal | Insufficient
  one sentence route_reason (humanised)
  4-6 KPIs max (regime-specific set)
WHAT THIS MEANS (<=80 words, template by regime)
FIGURE 1 - Extent over time (Plotly)
  line extent_pct; optional invalid ribbon
  HY spans / event bars / low spells by route
FIGURE 2 - route-specific
  seasonal: monthly climatology + peak/trough
  aseasonal: event magnitude timeline or duration hist
DETAILS (collapsed by default)
  Hydro years (table) - hidden if n_hy==0
  Wet events (table)
  Low-extent spells (table)
  Data quality notes
METHODS and FIELD GUIDE (collapsed)
  short how-it-works + CSV column dictionary pointer
  NOT a dump of every internal diagnostic on open page
```

### KPI sets (max 6)

**Seasonal / marginal**

1. Regime (+ basis: detected vs imposed)
2. Amplitude SNR
3. Peak / trough climatology months (names, not ints only)
4. Complete hydro-years count
5. Mean peak extent %
6. Mean trough extent % or high-confidence year share

**Aseasonal**

1. Regime
2. Amplitude SNR (show low)
3. Wet events (n)
4. Median event duration (mo)
5. Longest low spell (mo)
6. Years without wet event

### Plain-language templates (examples)

- Seasonal: "This record shows a reproducible annual wet-dry cycle. Compare wet peaks and dry troughs on the hydrological year, not the calendar year."
- Marginal: "Seasonality is weak or unstable year-to-year. Hydro-year windows are imposed from climatology - treat timing as an assumption, not a detection."
- Aseasonal: "No stable annual cycle. Do not use hydrological-year labels. Describe the site with wet-event frequency and dry-spell length."

## Chart design (Plotly, light)

Reuse interaction model from multi-catchment artifact; improve visual system:

| Token | Value |
|---|---|
| Page bg | `#f4f5f6` or `#f8fafc` |
| Card | `#ffffff`, 12px radius, soft shadow |
| Ink | `#14181b` / muted `#565f66` |
| Accent | `#2565c7` |
| Wet / peak | `#0f9f6e` / `#10b981` |
| Dry / trough / low spell | `#d9b26a` / `#f59e0b` |
| Event | `#2565c7` |
| Invalid | `#94a3b8` (ribbon, low opacity) |
| Good/warn/crit pills | same as workflow artifact |

**Figure 1 - timeline**

- Trace: monthly `extent_pct`
- Shapes: HY intervals (seasonal/marginal) or event rectangles + low-spell bands (aseasonal)
- Markers: peak (green), trough (amber) when HY exists
- Hover: date, extent, invalid, hy_year / event_id if any
- Range slider optional for long records

**Figure 2**

- Seasonal: 12-month climatology box or mean+/-IQR; mark peak/trough months
- Aseasonal: horizontal event bars by year or duration histogram + spell length callout

Config: `responsive: true`, `displaylogo: false`, remove lasso/select.

## CSV export design

### A. `*_monthly.csv` - one row per calendar month (complete)

**Extract (always if available)**

| Column | Source |
|---|---|
| date | month start |
| extent_pct | input |
| wet_fill_pct | input optional |
| invalid_pct | input |
| n_water, n_valid, n_aoi | input optional |

**Calculated - condition (always when computable)**

| Column | Source |
|---|---|
| reference_median_pct | `compute_monthly_surface_water_condition` |
| anomaly_pct | same |
| condition_percentile | same |
| reference_n | same |
| quality_state | same |

**Calculated - routing labels**

| Column | Source |
|---|---|
| usable_month | quality screen flag |
| hy_year | label if HY route produced years else null |
| season_label | Wet/Dry from labels if HY else null |
| is_hy_peak | bool |
| is_hy_trough | bool |
| in_wet_event | bool |
| wet_event_id | nullable |
| in_low_spell | bool |
| low_spell_id | nullable |
| regime | constant per series (denormalised for single-file use) |
| route | constant |

**Optional rainfall (if provided)**

| Column | Source |
|---|---|
| rainfall_mm | SILO or user series |
| rain_anomaly_mm | optional |

### B. `*_hydro_years.csv` - full dynamic / fixed table

Export **all columns** returned by detector in use (dynamic state columns already rich: recession, confidence, selection_*, raw_peak/trough, etc.). Do not subset for "pretty". Add:

- `boundary_basis` (detected_per_year / imposed_fixed_window / none)
- `catchment`, `regime`, `route` denormalised

If route is aseasonal: write **header-only with schema** so pipelines stay stable.

### C. `*_events.csv` / `*_low_spells.csv`

Direct export of `WaterEventResult` frames (always).

### D. `*_summary.csv`

One row: existing `summary_row` + plain `verdict_sentence` + key quality counts.

### E. column dictionary

`docs/report-columns.md` + copy beside study_case outputs.

## API shape

Keep `generate_html_report(extent, hydro_years, ...)` working (compat).

Add higher-level entry (preferred for study case / scripts):

```python
def generate_catchment_report(
    extent: pd.DataFrame,
    output_dir: str | Path,
    *,
    name: str,
    analysis: CatchmentAnalysis | None = None,
    state: HydrologicalStateResult | None = None,
    rainfall: pd.DataFrame | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    quality_note: str | None = None,
    theme: Literal["light"] = "light",
) -> CatchmentReportPaths:
    ...
```

`CatchmentReportPaths`: `html`, `monthly_csv`, `hydro_years_csv`, `events_csv`, `low_spells_csv`, `summary_csv`.

Internals split:

| Module | Role |
|---|---|
| `_report_export.py` | build monthly/hy/events/summary frames |
| `_report_plotly.py` | figure builders -> JSON for Plotly.newPlot |
| `_report_copy.py` | verdict sentences, KPI selection by regime |
| `report.py` / `_report_html.py` | assemble light HTML shell |
| `_report_metrics.py` | keep / extend pure KPIs |
| `_report_svg.py` | retain optional offline/no-JS fallback |

Plotly: embed via CDN script tag. **Prefer dict builders** (stdlib json) so core deps stay pandas/numpy only.

## Mapping inventory -> UX (so nothing is lost)

| Inventory block | Where it lives |
|---|---|
| Regime and routing | Verdict card + summary CSV |
| Wet events | Fig1 overlay + events CSV + collapsed table |
| Low-extent spells | Fig1 overlay + low_spells CSV + collapsed table |
| Rainfall comparison | Optional panel if rainfall present; else omit |
| Monthly condition | monthly CSV + hover on Fig1 |
| HY boundaries / peak-trough / recession / condition / confidence | hydro_years CSV full; HTML shows 5-7 friendly columns in collapsed table; rest in CSV |

Front page never lists the inventory as 10 cards. Methods appendix points to column dictionary / CSVs.

## Study-case builder changes

`scripts/_build_study_case_offline.py`:

1. Build analysis frame (keep `.to_numpy()` fix)
2. `analyze_catchment`
3. Optional `analyze_hydrological_state` with preferred trough
4. `generate_catchment_report(...)` -> `output/study_case/`
5. Aggregate `study_case_summary.csv`

## Visual references (steal / improve)

| Artifact | Steal | Improve |
|---|---|---|
| multi-catchment-transferability | Plotly charts, KPI strip, per-section cards | Drop heavy dark hero; simplify badges; better hierarchy |
| automated-catchment-workflow | Route pills, event timeline metaphor, rainfall panel pattern | Do not ship inventory grid as main content; humanise route_reason |
| water-regime-gate | Verdict-first question | Use as pattern for verdict card |
| package report.py today | Year cards detail | Collapse; fix schema mismatch with dynamic HY cols |

## Risks

| Risk | Mitigation |
|---|---|
| Dynamic HY schema != fixed HY schema in year cards | Normalize column aliases in export/report layer |
| Plotly CDN offline fail | Note in docs; optional local plotly.min.js path later |
| Huge monthly+condition joins slow | Vectorised merge; study case 5 catchments trivial |
| Compat break for `generate_html_report` | Keep function; thin wrapper calling new shell |
| Rainfall on legacy branch only | Gate optional panel; no hard import if missing |

## Acceptance criteria

1. Light-only HTML; no dark `prefers-color-scheme` rules in shipped template.
2. At least one Plotly chart with hover works in browser without Python.
3. Aseasonal catchment report has **zero** primary HY narrative; events/spells lead.
4. Seasonal report shows HY spans on timeline and <=6 KPIs above fold.
5. `*_monthly.csv` includes extract + condition + event/HY flags for all months in series.
6. `*_hydro_years.csv` includes full detector columns when years exist.
7. Study-case rebuild for 5 catchments succeeds; docs match files.
8. Existing `tests/test_report.py` updated/green; new tests for export columns + regime branching.
9. No inventory wall on first screen.

## Out of scope follow-ups

- Multi-catchment compare HTML v2
- Self-contained Plotly bundle
- i18n
- PDF export
