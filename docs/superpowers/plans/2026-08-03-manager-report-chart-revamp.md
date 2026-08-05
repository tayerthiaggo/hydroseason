# Manager Report Chart Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the offline manager report's monthly extent chart full width and interactive, add phase/quality/HY context, and add a synchronized hydrological-year extent chart below it.

**Architecture:** Keep Plotly figure construction as pure Python dict builders in `_report_plotly.py`. Pass a new HY figure through the existing report renderer, which will add scale controls and narrowly scoped JavaScript for scale switching and two-chart x-range synchronization. Preserve the public report API and user CSV projections.

**Tech Stack:** Python 3, pandas, NumPy, pytest, vendored offline Plotly 3.6.0, HTML/CSS/JavaScript emitted by `_report_html.py`.

## Global Constraints

- Monthly Surface Water Extent is the most important chart and spans the page.
- Supporting View moves below the two primary charts and is unchanged in this pass.
- Linear scale is the default; users can switch to log scale.
- Monthly phase context uses `recovery`, `wet`, `recession`, and `dry`.
- Monthly chart includes reference median and invalid percentage on a secondary axis.
- Peak, mid-dry, and end-dry markers come from hydrological-year exports.
- HY chart uses the same chronological x-axis and synchronized navigation.
- HY intervals run from month-after-end-dry through end-dry and display `HY ####` labels.
- Keep all reports self-contained with pinned Plotly and no CDN/script tags.
- Keep public report APIs, CSV filenames, and CSV schemas unchanged.

## File Map

- Modify `hydroseason/_report_plotly.py`: phase styling, marker helpers, richer timeline figure, and new `hydro_year_figure`.
- Modify `hydroseason/report.py`: import and pass the new HY figure for bundle reports; preserve legacy renderer compatibility.
- Modify `hydroseason/_report_html.py`: render full-width chart cards, scale controls, new serialized figure, and x-range synchronization.
- Modify `tests/test_report_plotly.py`: figure contracts and regression tests.
- Modify `tests/test_generate_catchment_report.py`: HTML shell and interaction-hook contracts.
- Modify `tests/test_report.py` only if legacy compatibility coverage exposes a concrete regression; otherwise leave it unchanged.
- Regenerate `case_studies/results/main/fitzroy_river_wa/fitzroy-river-wa.html` as the manual inspection artifact; do not add generated HTML to the implementation commit unless explicitly requested.

---

### Task 1: Add failing Plotly figure contracts

**Files:**
- Modify: `tests/test_report_plotly.py`
- Test: `tests/test_report_plotly.py`

**Interfaces:**
- Consumes existing `monthly` and `analysis` fixtures from `build_monthly_export` and `analyze_catchment`.
- Produces required contracts for `timeline_figure(monthly, analysis)` and the new `hydro_year_figure(monthly, analysis)`.

- [ ] **Step 1: Add timeline behavior tests**

Add assertions covering the requested public figure shape:

```python
def test_timeline_contains_phase_context_quality_and_scale_controls(seasonal_data):
    monthly, analysis = seasonal_data
    figure = timeline_figure(monthly, analysis)
    names = {trace.get("name") for trace in figure["data"]}
    phase_shapes = [shape for shape in figure["layout"]["shapes"] if shape.get("name", "").startswith("phase:")]

    assert "Water Extent (%)" in names
    assert "Reference Median" in names
    assert "Invalid Coverage (%)" in names
    assert {"HY Peak", "HY Mid Dry", "HY End Dry"} <= names
    assert {"phase:recovery", "phase:wet", "phase:recession", "phase:dry"} <= {
        shape["name"] for shape in phase_shapes
    }
    assert figure["layout"]["yaxis"]["type"] == "linear"
    assert figure["layout"]["yaxis2"]["title"] == "Invalid Coverage (%)"
    assert figure["layout"]["xaxis"]["rangeslider"]["visible"] is True
    assert figure["config"]["scrollZoom"] is True
```

Add a marker-data assertion that the mid-dry date comes from
`temporal_mid_dry_month` in the analysis HY rows, not from row position.

- [ ] **Step 2: Add HY figure behavior test**

Add a test with the existing seasonal fixture:

```python
def test_hydro_year_figure_contains_intervals_labels_and_boundary_markers(seasonal_data):
    monthly, analysis = seasonal_data
    figure = hydro_year_figure(monthly, analysis)

    assert any(trace.get("name") == "Hydrological-year extent" for trace in figure["data"])
    assert {"HY Peak", "HY Mid Dry", "HY End Dry"} <= {
        trace.get("name") for trace in figure["data"]
    }
    assert any(annotation.get("text", "").startswith("HY ") for annotation in figure["layout"]["annotations"])
    assert any(shape.get("name", "").startswith("HY ") for shape in figure["layout"]["shapes"])
    assert figure["layout"]["xaxis"]["rangeslider"]["visible"] is False
```

The test must also assert that a HY interval starts at `hy_start` and ends at
`hy_end`, which are already defined as month-after-end-dry through end-dry by
`analysis.hydro_years`.

- [ ] **Step 3: Update existing exact-config assertions for the new interaction contract**

Replace the current exact `figure["config"]` equality with assertions for
`responsive`, `displaylogo`, `scrollZoom`, and the retained removed selection
`modeBarButtonsToRemove` entries. This prevents unrelated future Plotly config
keys from making the test brittle.

- [ ] **Step 4: Run tests to verify RED**

Run:

```text
python -m pytest tests/test_report_plotly.py -q
```

Expected: FAIL because `hydro_year_figure` is not defined and the current
`timeline_figure` lacks phase shapes, mid-dry markers, invalid coverage, range
slider, and the requested config fields.

---

### Task 2: Implement figure builders and timeline visuals

**Files:**
- Modify: `hydroseason/_report_plotly.py`
- Test: `tests/test_report_plotly.py`

**Interfaces:**
- `timeline_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]` remains the existing interface.
- Add `hydro_year_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]`.

- [ ] **Step 1: Add shared constants and safe helpers**

Define stable phase colors for exactly `recovery`, `wet`, `recession`, and
`dry`; define marker colors/symbols for peak, mid dry, and end dry; and add a
`LOG_FLOOR = 0.02` constant. Reuse `_clean_val`/`_clean_list` and convert all
`hy_start`, `hy_end`, and marker dates to ISO date strings before returning
figure dicts.

- [ ] **Step 2: Implement timeline phase bands and HY markers**

Build contiguous phase shapes from adjacent monthly dates. Each shape must
include `name="phase:<phase>"`, `type="rect"`, `xref="x"`, `yref="paper"`,
`y0=0`, `y1=1`, low opacity fill, and no border. Ignore null/unknown phases.

Build marker traces from HY rows using these source columns:

```python
marker_columns = {
    "HY Peak": "peak_month",
    "HY Mid Dry": "temporal_mid_dry_month",
    "HY End Dry": "trough_month",
}
```

For each marker, look up the matching monthly extent and invalid value by date.
Use hover text that includes HY year, date, extent, invalid percentage,
`confidence`, and `boundary_status` when available.

- [ ] **Step 3: Add reference median and invalid coverage traces**

Keep reference median as a dashed slate line when its column has finite values.
Add `Invalid Coverage (%)` as an amber line assigned to `yaxis="y2"` when
`invalid_pct` exists and has finite values. Keep the extent trace visually
primary and do not put invalid coverage on the left scale.

- [ ] **Step 4: Add timeline navigation and scale metadata**

Set left `yaxis.type` to `linear`, right `yaxis2.type` to `linear`, add a
visible `xaxis.rangeslider`, and set `config.scrollZoom=True` while retaining
responsive behavior and the existing modebar removals. Add trace metadata or
`customdata` sufficient for the HTML script to clamp non-positive extent values
to `LOG_FLOOR` when switching to log mode while leaving hover values unchanged.

- [ ] **Step 5: Implement `hydro_year_figure`**

Render the monthly extent line on the same date domain. For each complete HY
row, add a low-opacity rectangle from `hy_start` to `hy_end`, named `HY ####`,
plus a centered annotation with text `HY ####`. Add the same three marker traces
using the HY row dates. Use linear y-axis, no second range slider, and the same
responsive/scroll zoom config.

- [ ] **Step 6: Run focused tests to verify GREEN**

Run:

```text
python -m pytest tests/test_report_plotly.py -q
```

Expected: PASS with no serialization warnings or NaN/Infinity errors.

---

### Task 3: Add failing HTML shell and interaction tests

**Files:**
- Modify: `tests/test_generate_catchment_report.py`

**Interfaces:**
- Consumes `generate_catchment_report` and its returned HTML path.
- Produces stable HTML contracts for the new chart layout and script behavior.

- [ ] **Step 1: Add bundle HTML assertions**

Extend the offline bundle test with assertions for:

```python
assert 'id="timeline-scale-linear"' in html
assert 'id="timeline-scale-log"' in html
assert 'id="timeline"' in html
assert 'id="hydro-year"' in html
assert html.index("Monthly Surface Water Extent") < html.index("Hydrological Year Extent")
assert html.index("Hydrological Year Extent") < html.index("Supporting View")
assert "plotly_relayout" in html
assert "Invalid Coverage (%)" in html
assert '"hydro_year"' in html
```

Keep existing assertions for offline Plotly, escaping, strict JSON, CSV names,
and no per-study summary CSV.

- [ ] **Step 2: Add legacy compatibility assertion**

Assert that `generate_html_report` still renders `id="timeline"` and
`id="hydro-year"` without creating CSV files. Its HY chart may be empty, but
its shell and Plotly runtime must remain valid.

- [ ] **Step 3: Run tests to verify RED**

Run:

```text
python -m pytest tests/test_generate_catchment_report.py -q
```

Expected: FAIL because the current renderer has no scale controls, HY chart,
new figure payload, or synchronization script.

---

### Task 4: Implement report layout, scale controls, and synchronized zoom

**Files:**
- Modify: `hydroseason/_report_html.py`
- Modify: `hydroseason/report.py`
- Test: `tests/test_generate_catchment_report.py`

**Interfaces:**
- `render_report_html(..., hydro_year_figure: dict[str, Any] | None = None) -> str`; the new argument is optional for legacy callers.
- `generate_catchment_report` passes `hydro_year_figure(monthly, analysis)`.
- `generate_html_report` omits the new argument and receives a safe empty HY figure.

- [ ] **Step 1: Extend renderer payload and signature**

Add optional `hydro_year_figure` to `render_report_html`. Serialize it under
`window.HydroSeasonReport.figures.hydro_year`; use an empty valid Plotly figure
when omitted. Keep `_json_script(... allow_nan=False)` as the only payload path.

- [ ] **Step 2: Replace primary chart grid with full-width cards**

Render, in order:

```html
<section class="plot plot-primary">
  <div class="plot-heading">
    <h2>Monthly Surface Water Extent</h2>
    <div class="scale-controls" role="group" aria-label="Extent scale">
      <button id="timeline-scale-linear" type="button" class="active">Linear scale</button>
      <button id="timeline-scale-log" type="button">Log scale</button>
    </div>
  </div>
  <div id="timeline"></div>
</section>
<section class="plot plot-primary"><h2>Hydrological Year Extent</h2><div id="hydro-year"></div></section>
<section class="plot"><h2>Supporting View</h2><div id="secondary"></div></section>
```

Use responsive CSS so each primary plot has a minimum height around 480px on
wide screens and remains usable below 900px. Preserve table sections below.

- [ ] **Step 3: Implement Plotly initialization and scale switching**

Initialize `timeline`, `hydro-year`, and `secondary` from the serialized
figures. Keep the modebar and responsive behavior. On linear/log button click,
update only the left y-axis type and restyle extent/reference/marker traces with
the log floor for non-positive values; update active button classes and
`aria-pressed` state. Keep `yaxis2.type` linear.

- [ ] **Step 4: Implement bidirectional x-range synchronization**

Attach `plotly_relayout` listeners to timeline and HY chart. Handle both
`xaxis.range` arrays and `xaxis.range[0]`/`xaxis.range[1]` event forms, plus
`xaxis.autorange`. Use a reentrancy guard so syncing one chart does not trigger
an endless loop. Do not synchronize y-axis changes.

- [ ] **Step 5: Run focused HTML tests to verify GREEN**

Run:

```text
python -m pytest tests/test_generate_catchment_report.py tests/test_report.py -q
```

Expected: PASS, including legacy compatibility and HTML escaping tests.

---

### Task 5: Full verification and Fitzroy artifact regeneration

**Files:**
- Modify: `case_studies/results/main/fitzroy_river_wa/fitzroy-river-wa.html` (generated manual-inspection artifact only)

- [ ] **Step 1: Run all report-focused tests**

Run:

```text
python -m pytest tests/test_report.py tests/test_report_plotly.py tests/test_generate_catchment_report.py tests/test_report_export.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 2: Run the full test suite**

Run:

```text
python -m pytest -q
```

Expected: PASS. If an unrelated pre-existing failure appears, record its
exact test and error without weakening the new report assertions.

- [ ] **Step 3: Regenerate Fitzroy report**

Run the existing targeted export command:

```text
python -c "from pathlib import Path; from hydroseason import analyze_catchment, generate_catchment_report, load_extent_csv; extent=load_extent_csv(Path('case_studies/data/extent/fitzroy_river_wa_30m.csv'), date_col='date', value_col='extent_pct'); analysis=analyze_catchment(extent, phase_model='rule_based', quality_policy='flag'); print(generate_catchment_report(extent, Path('case_studies/results/main/fitzroy_river_wa'), name='fitzroy_river_wa', analysis=analysis, title='Fitzroy River (WA)', subtitle='Whole-catchment monthly surface-water extent, 2005-2025', quality_note='Finite monthly observations are retained for boundary mapping; invalid coverage is reported and low-quality boundaries are marked provisional/low confidence.'))"
```

Verify the HTML contains the four phase names, the three marker names, the
linear/log controls, `Reference Median`, `Invalid Coverage (%)`, and both chart
containers. Open the HTML locally and manually check full-width layout, mouse
zoom, range slider, scale toggle, phase bands, HY labels, and synchronized x
navigation.

- [ ] **Step 4: Check repository diff**

Run:

```text
git status --short
git diff -- hydroseason/_report_plotly.py hydroseason/_report_html.py hydroseason/report.py tests/test_report_plotly.py tests/test_generate_catchment_report.py
```

Confirm only intended source/tests/spec/plan changes are staged; keep the
generated Fitzroy HTML untracked unless the user explicitly asks to commit it.
