# Manager Report + Full Monthly Export - Implementation Plan

> **Note:** Implemented through Task 8 of the release readiness plan (`v0.1.0-post-dea-release-readiness.md`).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship route-aware, light-theme, Plotly manager reports and complete monthly/HY/event CSV exports so users get a clear verdict without drowning in fields, while analysts retain every calculated variable.

**Architecture:** New export + Plotly + copy layers behind `generate_catchment_report`; keep `generate_html_report` as compatibility wrapper. Study-case builder calls the new API. Design source: `docs/superpowers/specs/2026-07-31-manager-report-full-export-design.md`.

**Tech stack:** Python 3.10+, pandas, numpy, stdlib json/html; Plotly.js via CDN in HTML (no new required pip dep). pytest.

**Design ref:** [2026-07-31-manager-report-full-export-design.md](../specs/2026-07-31-manager-report-full-export-design.md)

**Artifact refs:**
- `docs/artifacts/automated-catchment-workflow.html` (inventory + route UX)
- `docs/artifacts/multi-catchment-transferability-report.html` (Plotly light-ish)
- `docs/artifacts/water-regime-gate.html` (verdict-first)

---

## Task graph

```text
T0  fixtures + schema map          (no dep)
T1  _report_export.py monthly/HY   (dep T0)
T2  _report_copy.py verdict/KPIs   (dep T0)
T3  _report_plotly.py figures      (dep T0)
T4  HTML shell + generate_catchment_report  (dep T1,T2,T3)
T5  generate_html_report wrapper   (dep T4)
T6  tests                          (dep T4,T5)
T7  study-case builder + rebuild   (dep T4,T6)
T8  docs (study-case, guide, dictionary) (dep T7)
T9  acceptance checklist           (dep T7,T8)
```

Parallel-safe after T0: T1 || T2 || T3.

---

## T0 - Fixtures and schema map

**Files:**
- Create: `docs/superpowers/specs/_schema_map_report_export.md`
- Tests may build synthetic frames in-file

- [ ] **Step 1: Document column aliases**

Cover:
- fixed HY: `end_extent_pct`, `n_months_cycle`, `peak_extent_pct`, ...
- dynamic HY: `trough_extent_pct`, `cycle_months`, recession/confidence cols
- monthly condition cols from `compute_monthly_surface_water_condition`
- events / low_spells cols from `WaterEventResult`
- alias function: `normalize_hydro_years(df) -> df`

- [ ] **Step 2: Tiny synthetic fixtures in tests**

Seasonal (~15y monsoonal), aseasonal (noise), marginal optional - helpers in `tests/test_report_export.py`.

---

## T1 - Full CSV export module

**Files:**
- Create: `hydroseason/_report_export.py`
- Test: `tests/test_report_export.py`

**API:**

```python
def build_monthly_export(
    extent,
    *,
    analysis=None,
    monthly_condition=None,
    hydro_years=None,
    rainfall=None,
    name=None,
): ...

def build_hydro_years_export(hydro_years, *, analysis, name): ...
def build_events_export(events): ...
def build_summary_export(analysis, *, name, extra=None): ...
def write_catchment_csvs(out_dir, **frames): ...
```

- [ ] **Step 1: Implement `build_monthly_export`**

Rules:
- Index -> `date` column (month start)
- Preserve all original extent columns
- Left-join condition on date
- Flags: `in_wet_event`, `wet_event_id`, `in_low_spell`, `low_spell_id`
- If hydro_years non-empty: `hy_year`, `season_label`, peak/trough bools
- `usable_month` from invalid_pct / quality_state
- Include **all** months in extent (no drop)

- [ ] **Step 2: Implement HY / events / summary writers**

- HY: all detector columns + denormalised meta; empty -> header-only stable schema
- Events/spells: as-is
- Summary: `summary_row` + `verdict_code` + `verdict_sentence`

- [ ] **Step 3: Tests**

```bash
python -m pytest tests/test_report_export.py -q
```

Assert monthly rows == len(extent); condition cols present; event flags; aseasonal hy_year NA; seasonal hy_year non-null.

- [ ] **Step 4: Commit** `feat(report): full monthly and event CSV export builders`

---

## T2 - Verdict copy and KPI selection

**Files:**
- Create: `hydroseason/_report_copy.py`
- Test: `tests/test_report_copy.py`

```python
def verdict_sentence(analysis): ...
def select_kpis(analysis, hydro_years=None): ...  # list[dict] len <= 6
def human_route(route): ...
def month_name(m): ...
```

- [ ] **Step 1: Templates** for seasonal/marginal/aseasonal/insufficient
- [ ] **Step 2: KPI unit tests** (no HY metrics on aseasonal)
- [ ] **Step 3: Commit** `feat(report): regime-aware verdict copy and KPIs`

---

## T3 - Plotly figure builders (dict-only)

**Files:**
- Create: `hydroseason/_report_plotly.py`
- Test: `tests/test_report_plotly.py`

```python
def extent_timeline_figure(monthly, analysis, hydro_years) -> dict: ...
def secondary_figure(monthly, analysis, hydro_years) -> dict: ...
```

Return `{data, layout, config}` for `Plotly.newPlot`.

- [ ] **Step 1: Timeline** - extent line; HY or events/spells shapes; light layout
- [ ] **Step 2: Secondary** - climatology vs event hist by regime
- [ ] **Step 3: Tests** - data+layout; white paper_bgcolor
- [ ] **Step 4: Commit** `feat(report): Plotly light-theme figure dicts`

---

## T4 - HTML shell + generate_catchment_report

**Files:**
- Modify/create: `hydroseason/report.py` (optional `_report_html.py`)
- Modify: `hydroseason/__init__.py`
- Modify: `tests/test_package_surface.py` if needed

```python
@dataclass(frozen=True)
class CatchmentReportPaths:
    html: Path
    monthly_csv: Path
    hydro_years_csv: Path
    events_csv: Path
    low_spells_csv: Path
    summary_csv: Path

def generate_catchment_report(...) -> CatchmentReportPaths: ...
```

HTML requirements:
- `data-theme="light"`; no dark media queries
- Plotly CDN 2.35.2
- Verdict card, KPIs, what-this-means, 2 charts, collapsed details
- Methods appendix collapsed - no 10-card inventory
- Escape user strings

- [ ] **Step 1: Assembler**
- [ ] **Step 2: Default `analyze_catchment`; optional state for condition + rich HY**
- [ ] **Step 3: Open one HTML in browser**
- [ ] **Step 4: Commit** `feat(report): generate_catchment_report light Plotly shell`

---

## T5 - Compat wrapper for generate_html_report

**Files:**
- Modify: `hydroseason/report.py`
- Modify: `tests/test_report.py`

- [ ] **Step 1: Wrapper** - extent+hydro_years still works; light + Plotly default
- [ ] **Step 2: Tests** - title/subtitle/quality; Plotly.newPlot; light theme; no dark CSS; HY labels on seasonal
- [ ] **Step 3: Commit** `feat(report): light Plotly generate_html_report compat`

---

## T6 - Broader tests + metrics alias fix

**Files:**
- Modify: `hydroseason/_report_metrics.py`
- Create: `tests/test_generate_catchment_report.py`

- [ ] **Step 1: normalize_hydro_years aliases** (trough/end, cycle_months)
- [ ] **Step 2: E2E tmp_path bundle test**
- [ ] **Step 3: Run full report test set**

```bash
python -m pytest tests/test_report.py tests/test_report_export.py tests/test_report_copy.py tests/test_report_plotly.py tests/test_generate_catchment_report.py tests/test_package_surface.py -q
```

- [ ] **Step 4: Commit** `test(report): catchment report bundle and HY aliases`

---

## T7 - Study-case builder rebuild

**Files:**
- Modify: `scripts/_build_study_case_offline.py`

- [ ] **Step 1: Call `generate_catchment_report` per catchment**
- [ ] **Step 2: Summary rollup under `output/study_case/`**
- [ ] **Step 3: Run**

```powershell
$env:PYTHONPATH = "D:\RLH\5.6\repos\hydroseason"
python scripts/_build_study_case_offline.py
```

Expect: 5 light+Plotly HTML; monthly CSVs with condition+flags; events CSVs; aseasonal HY header-only; seasonal HY rich cols.

- [ ] **Step 4: Spot-check** Fitzroy H1, Moonie aseasonal verdict
- [ ] **Step 5: Commit** `feat(study-case): rebuild with manager report and full CSVs`

---

## T8 - Docs

**Files:**
- Modify: `docs/study-case.md`, `docs/guide.md`, `docs/api.md`, `README.md`
- Create: `docs/report-columns.md`
- Update `mkdocs.yml` nav if new page

- [ ] **Step 1: Progressive disclosure UX + regime reading rules**
- [ ] **Step 2: Full monthly column dictionary**
- [ ] **Step 3: `mkdocs build --strict`**
- [ ] **Step 4: Commit** `docs: manager report UX and full CSV dictionary`

---

## T9 - Acceptance

- [ ] Light theme only
- [ ] Plotly hover works
- [ ] Aseasonal: no primary HY story
- [ ] Seasonal: HY on timeline, <=6 KPIs
- [ ] Monthly CSV complete
- [ ] HY CSV full columns when present
- [ ] Tests green
- [ ] Docs match files
- [ ] No inventory wall on first screen

Record residual gaps in CHANGELOG Unreleased.

---

## Implementation notes for agents

1. PowerShell: no bash heredoc; no bare `&` inside `python -c` - use files for patches.
2. Always `.to_numpy()` when building DataFrame values with a new index.
3. Prefer `CatchmentAnalysis` before `analyze_hydrological_state`; pass `climatological_trough_month`.
4. Do not reintroduce fake Zenodo DOI.
5. Keep public `__all__` intentional; update package_surface if exporting new names.
6. Plotly builders return plain dicts (no plotly Python package required).

---

## Estimated effort

| Task | Size |
|---|---|
| T0-T1 | M |
| T2 | S |
| T3 | M |
| T4 | L |
| T5-T6 | M |
| T7 | S |
| T8-T9 | S |
