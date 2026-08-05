# Opening Cycle Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a record's very first hydrological-year opportunity has a resolved trough but no preceding trough to anchor its start, bound that cycle using the record's own first observed month instead of reporting it as an empty `no_previous_boundary` row — so a genuine partial first cycle (with peak, drawdown, and monthly phases) is reported instead of a stub with nothing but a trough date.

**Architecture:** `_assemble_dynamic_years` in `hydroseason/_dynamic_year.py` currently special-cases `previous is None` into a blank row. This plan narrows that: when the *first* opportunity in the whole record (`position == 0`) has a resolved trough, synthesize a `previous` trough one month before the record's first observed month, set an explicit `used_record_start` flag, and fall through into the existing cycle-assembly code that already computes peak/mid-dry/drawdown/confidence for every other cycle. A new `status_reason` (`"record_start_boundary"`) distinguishes this case. Mid-record breaks after a data gap (chain reset by `previous = None` inside the loop) are explicitly **not** touched.

**Tech Stack:** Python, pandas, pytest. No new dependencies.

## Verified Facts (checked against the real code before writing this plan)

These were confirmed empirically — do not re-litigate them, but do re-verify if a step's expected output disagrees:

- `select_cycle_peak(cycle, start=previous_trough, end=end, ...)` selects **strictly between** `start` and `end` ([`_boundary.py:215`](../../../hydroseason/_boundary.py)). Because it is passed `previous_trough` (the synthetic pre-record month) and **not** `start`, the record's own first month **is** peak-eligible. Passing `start` instead would silently make the first month ineligible — do not "simplify" this.
- On real Fitzroy data the synthetic cycle is Jan 2005 → Oct 2005: **10 months, 10 usable**, clearing `min_usable_months_per_cycle` (default 8). Peak resolves to **2005-03-01** (0.1193%), trough 2005-10-01 (0.0249%), drawdown **0.0945 pp**.
- `_confidence`'s maximum possible score when `boundary_status == "provisional"` is `1.0 × 1.0 × 0.75 = 0.75`, and `"high"` requires `>= 0.80`. Forcing `provisional` therefore makes `"high"` unreachable arithmetically.
- **`monthly.csv` and the timeline phases change too.** [`_phase.py:188-194`](../../../hydroseason/_phase.py) skips any hydro-year row whose `hy_start`/`hy_end`/`peak_month` is None — which is exactly why Fitzroy's Jan–Oct 2005 is currently `phase="unspecified"`, `phase_status="outside_cycle"`. Populating those fields means **10 monthly rows gain real phases and `hy_year=2005`**. This is intended, but it is a second output surface and gets its own task (Task 3).

## Global Constraints

- `detect_dynamic_hydrological_years` is public/released API — its return schema (`ANNUAL_COLUMNS`) must not change shape (no new columns), only values within existing columns.
- `_assemble_dynamic_years` is shared by both the robust-extrema (released) and semi-Markov (internal-only) detectors — the fix must work for both, since both call it with the same `opportunities` shape.
- `min_usable_months_per_cycle` (default 8) and all other `DynamicHydroYearConfig` thresholds are unchanged — the synthetic first cycle must clear the same bar as any other cycle, not a relaxed one.
- Do not touch the mid-record `no_previous_boundary` path that fires after an `unresolved` cycle resets `previous = None` inside the loop — only the *first* opportunity in the whole table (`position == 0`) is in scope.
- Eligibility must be tracked by an **explicit flag set on the synthetic path**, never inferred positionally from `start == frame.index.min()` — a cycle derived from a real prior trough could coincidentally start at the record's first month, and must not be mislabelled.
- This changes two committed output surfaces: `hydro_years.csv` (Task 1) and `monthly.csv` (Task 3). Committed case-study artifacts under `case_studies/results/` are **not** regenerated without explicit user approval (Task 5).

---

### Task 1: Synthesize the opening boundary in `_assemble_dynamic_years`

**Files:**
- Modify: `hydroseason/_dynamic_year.py:422-515` (`_assemble_dynamic_years`)
- Test: `tests/test_dynamic_year.py`

**Interfaces:**
- Consumes: `frame` (prepared monthly extent, `DatetimeIndex`, columns include `extent_pct`, `invalid_pct`, `candidate_usable`, `observed_fraction`, `quality_state`), `opportunities` (one row per nominal year; columns `hy_year`, `status`, `status_reason`, `trough_month`, `trough_extent_pct`, `trough_invalid_pct`, `boundary_status`, plus `_TROUGH_DIAGNOSTIC_COLUMNS`), `config: DynamicHydroYearConfig`.
- Produces: same `pd.DataFrame(rows, columns=ANNUAL_COLUMNS)` shape as today. Behavioral change: when the first row of `opportunities` has a non-null `trough_month`, its resulting row gets `status_reason="record_start_boundary"` with populated `hy_start`/`hy_end`/`peak_month`/`drawdown_pct`, or falls through to `"insufficient_cycle_coverage"` (with `hy_start` set) if it fails the same coverage checks every other cycle faces.

- [ ] **Step 1: Write the failing test for the happy path**

Add to `tests/test_dynamic_year.py`:

```python
def test_first_opportunity_uses_record_start_as_opening_boundary():
    """The record's own first observed month anchors the opening cycle.

    The very first hydrological-year opportunity has no preceding trough,
    but when enough real data precedes its trough there is a genuine
    partial cycle to report. Before this fix that row was a blank stub
    (status_reason="no_previous_boundary", no hy_start/hy_end/peak at
    all), which rendered as an unbounded "no data" card and left the
    start of the timeline unshaded.
    """
    index = pd.date_range("2005-01-01", periods=36, freq="MS")
    # Descending Jan..Oct 2005 -- the record opens mid-cycle, so its peak
    # is its first month -- then two clean cycles troughing in October.
    # The +30/-20 offset keeps every later month above the opening trough
    # of 8.0, so Oct 2005 stays the first resolved trough.
    opening = [90.0, 78.0, 66.0, 54.0, 42.0, 30.0, 22.0, 16.0, 11.0, 8.0]
    following = list(
        30.0 + 20.0 * np.cos(2 * np.pi * (index[10:].month - 4) / 12)
    )
    raw = pd.DataFrame(
        {"extent_pct": opening + following, "invalid_pct": 0.0}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=10)

    result = detect_dynamic_hydrological_years(raw, config=config)

    first_row = result.iloc[0]
    assert first_row["status_reason"] == "record_start_boundary"
    assert first_row["hy_start"] == pd.Timestamp("2005-01-01")
    assert first_row["hy_end"] == pd.Timestamp("2005-10-01")
    # The record's own first month must be peak-eligible: select_cycle_peak
    # is given the synthetic pre-record trough, not hy_start, precisely so
    # that January is not excluded as a boundary month.
    assert first_row["peak_month"] == pd.Timestamp("2005-01-01")
    assert pd.notna(first_row["drawdown_pct"])
    assert first_row["boundary_status"] == "provisional"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dynamic_year.py::test_first_opportunity_uses_record_start_as_opening_boundary -v`
Expected: FAIL — `status_reason` is `"no_previous_boundary"` and `hy_start`/`peak_month`/`drawdown_pct` are `NaT`/`NaN`.

- [ ] **Step 3: Write the failing test for the too-short fallback**

Add to `tests/test_dynamic_year.py`:

```python
def test_first_opportunity_too_short_still_falls_back_to_insufficient_coverage():
    """A record starting only 3 months before its first trough has no
    cycle to report, even with the record-start boundary. It must fail
    the same min_usable_months_per_cycle check as any other cycle rather
    than being waved through on a synthetic boundary.
    """
    index = pd.date_range("2005-08-01", periods=24, freq="MS")
    opening = [30.0, 20.0, 10.0]  # Aug, Sep, Oct 2005 -- 3 months only
    following = list(
        20.0 + 15.0 * np.cos(2 * np.pi * (index[3:].month - 12) / 12)
    )
    raw = pd.DataFrame(
        {"extent_pct": opening + following, "invalid_pct": 0.0}, index=index
    )
    config = DynamicHydroYearConfig(
        expected_trough_month=10, min_usable_months_per_cycle=8
    )

    result = detect_dynamic_hydrological_years(raw, config=config)

    first_row = result.iloc[0]
    assert first_row["status_reason"] == "insufficient_cycle_coverage"
    assert first_row["hy_start"] == pd.Timestamp("2005-08-01")
    assert pd.isna(first_row["peak_month"])
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_dynamic_year.py::test_first_opportunity_too_short_still_falls_back_to_insufficient_coverage -v`
Expected: FAIL — current code reports `"no_previous_boundary"` with `hy_start` as `NaT`.

- [ ] **Step 5: Write a characterization test pinning mid-record resets**

This test **passes before and after** the change — it exists to prove the
new logic does not widen its scope to mid-record chain breaks. It is a
regression guard, not a red-green step.

```python
def test_mid_record_reset_after_gap_still_reports_no_previous_boundary():
    """Only the record's first opportunity may synthesize a boundary.

    A year that resets the chain mid-record (because an earlier year's
    trough was unresolvable) must keep reporting no_previous_boundary --
    synthesizing a start there would invent cycle data spanning a real
    data gap.
    """
    raw = _candidate_frame(start="2017-01-01", periods=84)
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle")

    result = detect_dynamic_hydrological_years(raw, config=config)

    assert result.loc[result["hy_year"] == 2020, "status"].item() == "unresolved"
    assert (
        result.loc[result["hy_year"] == 2021, "status_reason"].item()
        == "no_previous_boundary"
    )
    assert pd.isna(result.loc[result["hy_year"] == 2021, "hy_start"].item())
```

- [ ] **Step 6: Run it to confirm it passes on unmodified code**

Run: `python -m pytest tests/test_dynamic_year.py::test_mid_record_reset_after_gap_still_reports_no_previous_boundary -v`
Expected: PASS (baseline). Re-run after Step 7 — it must still pass.

- [ ] **Step 7: Implement the fix**

Open `hydroseason/_dynamic_year.py`. Replace lines 428-441 (from `rows = []`
through the `start = ...` assignment) with the following. Note
`used_record_start` is defined in the `position == 0` branch and read
further down — it must be reset to `False` at the top of **every**
iteration, and `start` must be computed immediately after it:

```python
    rows = []
    previous = None
    for position, (_, opportunity) in enumerate(opportunities.iterrows()):
        row = _blank_cycle(opportunity)
        used_record_start = False
        if pd.isna(opportunity["trough_month"]):
            previous = None
            rows.append(row)
            continue
        if previous is None:
            if position == 0:
                # Nothing precedes this opportunity at all, so the record's
                # own first observed month is a legitimate stand-in for the
                # previous trough. A mid-record reset (position > 0) is a
                # different situation: a gap broke the chain there, and
                # synthesizing a boundary would invent data across it.
                synthetic_previous = opportunity.copy()
                synthetic_previous["trough_month"] = (
                    frame.index.min() - pd.DateOffset(months=1)
                )
                previous = synthetic_previous
                used_record_start = True
                # Fall through into the normal assembly branch below.
            else:
                row.update(status="partial", status_reason="no_previous_boundary")
                previous = opportunity
                rows.append(row)
                continue
        start = pd.Timestamp(previous["trough_month"]) + pd.DateOffset(months=1)
```

Next, `boundary_status` (currently lines 479-483) must never read
`"confirmed"` for a synthetic start — a boundary taken from the record's
edge has no evidence on its left the way a detected trough does. Replace:

```python
        boundary_status = (
            "provisional"
            if peak_low_quality or opportunity["boundary_status"] != "confirmed"
            else "confirmed"
        )
```

with:

```python
        boundary_status = (
            "provisional"
            if peak_low_quality
            or used_record_start
            or opportunity["boundary_status"] != "confirmed"
            else "confirmed"
        )
```

Finally, `status_reason` (currently lines 484-490) must report the new
case. Replace:

```python
        status_reason = (
            "peak_low_quality"
            if peak_low_quality
            else "ok"
            if boundary_status == "confirmed"
            else "boundary_provisional"
        )
```

with:

```python
        status_reason = (
            "peak_low_quality"
            if peak_low_quality
            else "record_start_boundary"
            if used_record_start
            else "ok"
            if boundary_status == "confirmed"
            else "boundary_provisional"
        )
```

The two `insufficient_cycle_coverage` branches (lines 445-449 and 454-458)
need **no edit**: they already set `hy_start=start`, which is now correctly
`frame.index.min()` on the synthetic path.

- [ ] **Step 8: Run the three tests from this task**

Run: `python -m pytest tests/test_dynamic_year.py -k "record_start_as_opening_boundary or too_short_still_falls_back or mid_record_reset" -v`
Expected: 3 passed.

- [ ] **Step 9: Run the full module for regressions**

Run: `python -m pytest tests/test_dynamic_year.py -v`
Expected: all pass. Pay attention to `test_unresolved_nominal_year_breaks_cycles_instead_of_merging` and `test_dynamic_cycle_reports_observed_peak_two_mid_dry_metrics_and_trough` — if either fails, `used_record_start` is leaking into cycles it should not touch (check it is reset at the top of every loop iteration).

- [ ] **Step 10: Commit**

```bash
git add hydroseason/_dynamic_year.py tests/test_dynamic_year.py
git commit -m "feat: bound the record's opening hydrological year from its own start date"
```

---

### Task 2: Pin the confidence ceiling for synthetic-start cycles

**Files:**
- Test: `tests/test_dynamic_year.py`
- Modify: `hydroseason/_dynamic_year.py:351-358` (`_confidence`) — **only if Step 2 fails**

**Interfaces:**
- Consumes: `_confidence(cycle: pd.DataFrame, boundary_status: str) -> str`.
- Produces: `"high" | "medium" | "low"`. No signature change expected.

- [ ] **Step 1: Write the test**

```python
def test_record_start_boundary_cycle_is_never_high_confidence():
    """A cycle opened at the record's edge is an assumption, not a
    detection, and must never be scored "high". Task 1 forces
    boundary_status="provisional" for these, which caps _confidence's
    score at 0.75 -- below the 0.80 "high" threshold.
    """
    index = pd.date_range("2005-01-01", periods=36, freq="MS")
    opening = [90.0, 78.0, 66.0, 54.0, 42.0, 30.0, 22.0, 16.0, 11.0, 8.0]
    following = list(
        30.0 + 20.0 * np.cos(2 * np.pi * (index[10:].month - 4) / 12)
    )
    raw = pd.DataFrame(
        {"extent_pct": opening + following, "invalid_pct": 0.0}, index=index
    )
    config = DynamicHydroYearConfig(expected_trough_month=10)

    result = detect_dynamic_hydrological_years(raw, config=config)

    first_row = result.iloc[0]
    assert first_row["status_reason"] == "record_start_boundary"
    assert first_row["confidence"] in {"medium", "low"}
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_dynamic_year.py::test_record_start_boundary_cycle_is_never_high_confidence -v`
Expected: PASS with no production change — Task 1's `used_record_start` already forces `provisional`, capping the score at `0.75 < 0.80`.

If it unexpectedly FAILS, add an explicit cap rather than relying on the
arithmetic (and only then):

```python
def _confidence(cycle: pd.DataFrame, boundary_status: str, *, capped_medium: bool = False) -> str:
    usable_fraction = float(cycle["candidate_usable"].mean())
    observed = cycle.loc[cycle["candidate_usable"], "observed_fraction"]
    quality = float(observed.mean()) if observed.notna().any() else 0.5
    score = usable_fraction * quality * (0.75 if boundary_status == "provisional" else 1.0)
    if (cycle["quality_state"] == "unknown").any():
        score = min(score, 0.59)
    tier = "high" if score >= 0.80 else "medium" if score >= 0.60 else "low"
    return "medium" if capped_medium and tier == "high" else tier
```

passing `capped_medium=used_record_start` at the call site. Do not add
this parameter speculatively if Step 2 passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_dynamic_year.py hydroseason/_dynamic_year.py
git commit -m "test: pin confidence ceiling for record-start-boundary cycles"
```

---

### Task 3: Cover the monthly phase-labelling consequence

Populating `hy_start`/`hy_end`/`peak_month` makes the opening cycle
**phaseable**: [`_phase.py:188-194`](../../../hydroseason/_phase.py) skips rows
where any of those is None, which is why Fitzroy's Jan–Oct 2005 is
currently `phase="unspecified"`, `phase_status="outside_cycle"`. After
Task 1 those months get real phases and `hy_year`. This is the intended
user-visible outcome (the timeline stops being blank there) — this task
pins it with a test so it cannot regress silently.

**Files:**
- Test: `tests/test_phase.py` (add to the existing module)
- Modify: none expected — this task verifies an emergent consequence of Task 1.

**Interfaces:**
- Consumes: `hydroseason._phase.assign_rule_based_phases(prepared, hydro_years, *, noise_pp, boundary_basis="robust_extrema") -> pd.DataFrame`, and `hydroseason._state_input.prepare_monthly_extent` to build `prepared` (the raw frame alone lacks the `candidate_usable`/`observed_fraction` columns the phase code reads).
- Produces: no new interface.

- [ ] **Step 1: Add the import**

`tests/test_phase.py` currently imports `assign_monthly_phases` and
`empty_monthly_phase` from `hydroseason._phase`. Add
`assign_rule_based_phases` to that same import list (it is the function
the rule-based path actually runs).

- [ ] **Step 2: Write the test**

Add to `tests/test_phase.py`. This body was executed against the real
module while writing this plan and passes verbatim:

```python
def test_record_start_boundary_cycle_receives_monthly_phases():
    """An opening cycle bounded from the record start must be phaseable.

    assign_rule_based_phases skips rows whose hy_start/hy_end/peak_month
    is None, so before the opening-boundary fix the record's first months
    stayed "unspecified"/"outside_cycle" and left the timeline unshaded
    there. Once those fields are populated the months must get real
    phases like any other partial cycle.
    """
    index = pd.date_range("2005-01-01", periods=10, freq="MS")
    raw = pd.DataFrame(
        {
            "extent_pct": [90.0, 78.0, 66.0, 54.0, 42.0, 30.0, 22.0, 16.0, 11.0, 8.0],
            "invalid_pct": 0.0,
        },
        index=index,
    )
    prepared = prepare_monthly_extent(raw)
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2005,
                "status": "partial",
                "status_reason": "record_start_boundary",
                "hy_start": pd.Timestamp("2005-01-01"),
                "hy_end": pd.Timestamp("2005-10-01"),
                "peak_month": pd.Timestamp("2005-01-01"),
                "peak_extent_pct": 90.0,
                "trough_extent_pct": 8.0,
            }
        ]
    )

    out = assign_rule_based_phases(prepared, hydro_years, noise_pp=1.0)

    assert (out["phase_status"] != "outside_cycle").any()
    assert (out["hy_year"] == 2005).any()
    assert set(out["phase"].unique()) - {"unspecified"}
```

- [ ] **Step 3: Run it**

Run: `python -m pytest tests/test_phase.py::test_record_start_boundary_cycle_receives_monthly_phases -v`
Expected: PASS. This is a characterization test guarding an emergent
consequence, not a red-green cycle — it passes as soon as the row carries
`hy_start`/`hy_end`/`peak_month`. Verified output for this fixture:
Jan 2005 = `wet`, Feb = `recession`, Mar–Oct = `dry`, all
`phase_status="provisional"`, all `hy_year=2005`.

- [ ] **Step 4: Run the full phase module**

Run: `python -m pytest tests/test_phase.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase.py
git commit -m "test: pin monthly phase labelling for record-start-boundary cycles"
```

---

### Task 4: Flag inferred starts in the report year card

**Files:**
- Modify: `hydroseason/_report_html.py` (`_year_cards`)
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: `hydro_years` rows may now carry `status_reason == "record_start_boundary"` **with** `hy_start`/`hy_end` populated.
- Produces: no interface change. `_year_cards` already branches on `start is None or end is None`, so these rows automatically take the normal bounded-card path (not `_unbounded_year_card`). This task only adds explanatory copy.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_report_html.py`:

```python
def test_year_cards_flag_record_start_boundary_years_as_inferred():
    """A year starting at the record's edge renders as a normal bounded
    card, but must say its start is inferred -- a manager comparing it
    against other years needs to know its left edge is not independently
    verified.
    """
    monthly = _monthly()
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2005,
                "hy_start": pd.Timestamp("2005-01-01"),
                "hy_end": pd.Timestamp("2005-10-01"),
                "peak_month": pd.Timestamp("2005-03-01"),
                "trough_month": pd.Timestamp("2005-10-01"),
                "cycle_months": 10.0,
                "drawdown_pct": 0.0945,
                "confidence": "medium",
                "status": "partial",
                "status_reason": "record_start_boundary",
            }
        ]
    )

    html = _year_cards(monthly, hydro_years)

    assert html.count("<details class=") == 1
    assert "HY 2005" in html
    assert "year-card-unbounded" not in html
    assert "inferred from the record" in html.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_html.py::test_year_cards_flag_record_start_boundary_years_as_inferred -v`
Expected: FAIL — no "inferred" copy exists in the bounded card.

- [ ] **Step 3: Add the note**

In `hydroseason/_report_html.py`, inside `_year_cards`'s loop (the normal
bounded-card path, after `confidence` is read and before `cards.append`),
add:

```python
        status_reason = str(_row_value(row, "status_reason") or "").lower()
        inferred_start_note = (
            '<p class="year-card-note">'
            "This year&#39;s start is inferred from the record&#39;s first "
            "observed month, not a detected trough — there is no data before "
            "it to confirm where the previous dry season ended."
            "</p>"
            if status_reason == "record_start_boundary"
            else ""
        )
```

Then insert `{inferred_start_note}` into the card f-string immediately
before the `<table class="nested-table">` fragment, inside
`year-detail-content`. The `.year-card-note` CSS class already exists
(added with `_unbounded_year_card`), so no stylesheet change is needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_html.py::test_year_cards_flag_record_start_boundary_years_as_inferred -v`
Expected: PASS

- [ ] **Step 5: Run the full report-html module**

Run: `python -m pytest tests/test_report_html.py -v`
Expected: all pass, including the three earlier year-card tests, none of
which use `record_start_boundary`.

- [ ] **Step 6: Commit**

```bash
git add hydroseason/_report_html.py tests/test_report_html.py
git commit -m "feat: flag record-start-boundary years as inferred in the year card"
```

---

### Task 5: Verify end-to-end on Fitzroy, then stop

**Files:**
- No source changes — verification gate only.

**Interfaces:**
- Consumes: `hydroseason.report.generate_catchment_report` (unchanged signature).

- [ ] **Step 1: Regenerate Fitzroy to the scratch preview directory**

```bash
python - <<'EOF'
import pandas as pd
from hydroseason.report import generate_catchment_report

extent = pd.read_csv(
    "case_studies/data/extent/fitzroy_river_wa_30m.csv",
    parse_dates=["date"], index_col="date",
)
paths = generate_catchment_report(
    extent, "preview_report", name="Fitzroy River (WA)",
    title="Fitzroy River (WA)",
    subtitle="Whole-catchment monthly surface-water extent, 2005-2025",
)
hy = pd.read_csv(paths.hydro_years_csv)
row = hy.loc[hy["hy_year"] == 2005].iloc[0]
print(row[["hy_year", "start_date", "end_date", "peak_date", "trough_date", "status", "confidence"]])
assert row["start_date"] == "2005-01-01", row["start_date"]
assert row["end_date"] == "2005-10-01", row["end_date"]
assert row["peak_date"] == "2005-03-01", row["peak_date"]
print("OK: HY 2005 bounded Jan 2005 -> Oct 2005, peak Mar 2005")
EOF
```

Expected: assertions pass. Peak is **2005-03-01** and drawdown ≈ **0.0945 pp**
(verified against the real data while writing this plan). A different peak
month means peak selection is receiving `hy_start` instead of the synthetic
pre-record trough — re-check Task 1 Step 7.

- [ ] **Step 2: Confirm the monthly phases filled in**

```bash
python - <<'EOF'
import pandas as pd
monthly = pd.read_csv("preview_report/fitzroy-river-wa_monthly.csv", parse_dates=["date"])
opening = monthly[monthly["date"] < "2005-11-01"]
print(opening[["date", "extent_pct", "hy_year", "phase", "phase_status"]].to_string(index=False))
assert (opening["phase"] != "unspecified").any(), "opening months still unphased"
assert (opening["hy_year"] == 2005).any(), "opening months not assigned to HY 2005"
print("OK: opening months now phased and assigned to HY 2005")
EOF
```

Expected: the 10 opening months show real phases and `hy_year=2005`
instead of `unspecified`/`outside_cycle`.

- [ ] **Step 3: Confirm the HTML card and timeline**

```bash
python - <<'EOF'
html = open("preview_report/fitzroy-river-wa.html", encoding="utf-8").read()
print("year cards:", html.count('<details class="year-card'))
print("unbounded cards:", html.count("year-card-unbounded"))
print("HY 2005 present:", "HY 2005" in html)
print("inferred note:", "inferred from the record" in html.lower())
EOF
```

Expected: `year cards: 21`; `unbounded cards: 0` (HY 2005 is now a normal
bounded card — note the CSS rules for `.year-card-unbounded` remain in the
stylesheet, so count the `<details class=` occurrences, not the raw class
name, if this reads unexpectedly); `HY 2005 present: True`; `inferred note: True`.

- [ ] **Step 4: Full suite and lint**

Run: `python -m pytest tests/ -q`
Expected: **750 passed**, 1 skipped, 1 deselected — 744 before this plan
plus 6 new tests: 3 in Task 1 (Steps 1, 3, 5), 1 in Task 2, 1 in Task 3,
1 in Task 4. Two of those (Task 1's mid-record test and Task 3's phase
test) are characterization tests that also pass before the change. If
`tests/test_io_wofs_zarr.py` fails, re-run that file alone 2-3 times: it
has documented pre-existing flakiness (~1 in 6-8 runs) unrelated to this
work.

Run: `python -m ruff check hydroseason/ tests/`
Expected: `All checks passed!`

- [ ] **Step 5: Report to the user and stop**

Do **not** regenerate `case_studies/results/main/*` in place, and do not
`git add` anything under `case_studies/results/`. Those are committed
reference outputs, and this change alters both `hydro_years.csv` and
`monthly.csv` for every catchment whose record opens mid-cycle — a
deliberate data change that is the user's call. Report the Step 1-3
findings and ask whether to regenerate the committed bundle.

---

## Self-Review Notes

**Spec coverage:** The user's request — "we can clearly see a peak and the
first trough... indicate the HY as Jan 2005-Oct 2005... flagged as
incomplete but there's enough to point what we can" — maps to Task 1
(bounding + real peak/drawdown), Task 3 (the monthly phases that make the
timeline stop being blank there), and Task 4 (flagging it as inferred
rather than passing it off as a normally-detected year). Task 2 stops the
new path from claiming unwarranted confidence. Task 5 verifies on the real
data without unilaterally rewriting committed artifacts.

**Revisions from the first draft**, after checking each claim against the code:
1. Added Task 3 — the first draft silently omitted that `monthly.csv` and the timeline phases change, which is arguably the user-visible point of the fix.
2. Replaced positional `opened_at_record_start = start == frame.index.min()` with an explicit `used_record_start` flag set only on the synthetic path, and stated the reset-per-iteration requirement.
3. Step 7 now gives each edit once, in dependency order, instead of contradicting itself about where to define the flag.
4. Corrected the test-count arithmetic (750 = 744 + 6) and the "3 PASS / 4th" confusion.
5. Fixtures widened to 36 months and **executed against the real detector** while revising. The first draft's `following` formula was wrong twice over: its phase put later troughs in July rather than October, and a naive phase correction pushed the *first* trough to Nov 2005, breaking the `hy_end == 2005-10-01` assertion. The committed `30.0 + 20.0 * cos(2π(month−4)/12)` keeps every later month above the opening trough of 8.0, so Oct 2005 stays first. Verified: `hy_start=2005-01-01`, `hy_end=2005-10-01`, `peak_month=2005-01-01`, 10/10 usable months.
6. Task 3's test body was executed verbatim against `_phase.py` — it needs `prepare_monthly_extent` (a hand-built frame lacks `candidate_usable`), and `assign_rule_based_phases` must be added to `tests/test_phase.py`'s import list. Expected phases recorded.
7. Added the Verified Facts section recording what was empirically checked, including the `select_cycle_peak(start=previous_trough)` subtlety that a well-meaning simplification would break.

**Type consistency:** `_assemble_dynamic_years` still returns
`pd.DataFrame(rows, columns=ANNUAL_COLUMNS)`. `status_reason` gains one new
literal (`"record_start_boundary"`), consumed by `_report_html.py`'s existing
string branching. No signatures change unless Task 2 Step 2 fails.
