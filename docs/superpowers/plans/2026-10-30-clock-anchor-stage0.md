# Clock Anchor Steps 0–2 (Provenance, Target Decision, Stage 0 Rise Test) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute steps 0, 1 and 2 of the [independent verdict](../../handoff/2026-10-30-clock-anchor-independent-verdict.md) entirely from this repository: archive the proposal's provenance, give the lead a target-decision record to fill, and run a pre-registered "stage 0" test of whether a frozen rise rule agrees across Fitzroy tiles better than the end-dry as run.

**Architecture:** One importable script, `scripts/clock_anchor_stage0.py`, holds the frozen rule (`RULE`), the frozen decision margin (`MARGIN`), pure functions for the rise rule and the synchrony metric, and a CLI that reads hydropools' historical HydroSeason outputs read-only and writes a CSV table, a Markdown summary and a JSON receipt under `dev/reports/`. Tests exercise every function on known-truth synthetic series only; real data is read exactly once, after a "freeze" commit. Two handoff documents cover steps 0 and 1.

**Tech Stack:** Python 3.12 in `.venv`, NumPy 2.4, pandas 3.0, pytest, ruff 0.16. Windows paths. Run everything from `D:\RLH\5.6\repos\hydroseason`.

## Global Constraints

- **Never edit anything under `hydroseason/`.** No method, default, threshold or export changes. The 0.2.0 library and `main` stay untouched.
- **Hydropools is read-only.** Inputs: `D:/RLH/5.6/repos/hydropools/work/rerun/fitzroy/hydroseason/<tile>/channel_monthly_extent.csv`, `<tile>/*_hydro_years.csv`, `D:/RLH/5.6/repos/hydropools/outputs/rerun/fitzroy/manifest.json`, and the proposal `D:/RLH/5.6/repos/hydropools/docs/handoff/2026-10-30-clock-anchor-analysis.md`. Never write, move or reformat them. Do not rerun hydropools or HydroSeason on production inputs.
- Work on a new branch `clock-anchor-stage0` created from `development` (Task 1). Commit after each task with the message given. Do not push. Append whatever attribution trailer the harness requires.
- Interpreter: `.venv/Scripts/python.exe`. Pytest: `.venv/Scripts/python.exe -m pytest <paths> -q -p no:cacheprovider --basetemp build/pytest-tmp`. Lint: `.venv/Scripts/python.exe -m ruff check <files>` (line length 100; rules E, F, I; E501 ignored). Fix what ruff reports.
- **Freeze discipline.** `RULE`, `MARGIN` and `VARIANTS` in `scripts/clock_anchor_stage0.py` are written in Tasks 3–6 against synthetic data only and committed in Task 7 before the script reads any real file. After that commit they must not change. If a change becomes unavoidable, record it in the results document as post hoc and label every rerun accordingly.
- **Disclosure.** The results document must state that exploratory rise proxies were run on this same data before the rule was written (verdict §6.1, values 0.82–0.88). Stage 0 is a pre-specified test, not a blind one.
- Tests use `from scripts.clock_anchor_stage0 import ...` (`pyproject.toml` sets `pythonpath = ["."]`). Test docstrings say they pin a frozen rule's arithmetic on known-truth series, not hydrological truth.
- Do not treat the untracked `docs/provisional-trough-*.md` and `RELEASE_PLAN_0.2.1.md` as part of this plan; leave them untracked.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `docs/handoff/2026-10-30-clock-anchor-provenance.md` | Step 0: the three known hashes of the proposal, which one is archived, what is unrecoverable. |
| `docs/handoff/archive/2026-10-30-clock-anchor-analysis-6619c823.md` | Step 0: verbatim copy of the proposal as reviewed. |
| `docs/handoff/2026-10-30-clock-anchor-target-decision.md` | Step 1: decision record for the lead (target, censoring, gates, donor policy). Lead fills it; nothing here waits on it. |
| `scripts/clock_anchor_stage0.py` | Step 2: `RULE`, `MARGIN`, `VARIANTS`; rise rule; end-dry chain; weighted leave-one-out synchrony; decision; loaders; CLI; receipt. |
| `tests/test_clock_anchor_stage0.py` | Known-truth tests for every function and a CLI smoke test on synthetic tiles. |
| `dev/reports/2026-10-30-clock-anchor-stage0.{csv,md,json}` | Step 2 outputs: per tile-year table, summary, receipt with input hashes. |
| `docs/handoff/2026-10-30-clock-anchor-stage0-results.md` | Step 2 results and interpretation, written against pre-stated reading rules. |

---

### Task 1: Branch and provenance archive (step 0)

**Files:**
- Create: `docs/handoff/2026-10-30-clock-anchor-provenance.md`
- Create: `docs/handoff/archive/2026-10-30-clock-anchor-analysis-6619c823.md`

**Interfaces:**
- Produces: a committed `docs/handoff/` directory on branch `clock-anchor-stage0` containing the audit, receipt, review brief, verdict, provenance note and archived proposal.

- [ ] **Step 1: Create the branch**

Run:
```bash
git -C D:/RLH/5.6/repos/hydroseason checkout -b clock-anchor-stage0 development
git -C D:/RLH/5.6/repos/hydroseason status --short
```
Expected: `Switched to a new branch 'clock-anchor-stage0'`; status lists `?? docs/handoff/` and the pre-existing untracked files.

- [ ] **Step 2: Hash the proposal as it is on disk**

Run:
```bash
.venv/Scripts/python.exe -c "import hashlib,pathlib; p=pathlib.Path('D:/RLH/5.6/repos/hydropools/docs/handoff/2026-10-30-clock-anchor-analysis.md'); b=p.read_bytes(); print(hashlib.sha256(b).hexdigest(), len(b))"
```
Expected: `6619c8234a874f17b39c3db36755b4643945612655b70cbdcee2a829040deda7 19223`. If the hash differs, the proposal changed again: record the new hash and size as a fourth version in Step 4, name the archive file after the first eight characters of the new hash, and do not edit the source file.

- [ ] **Step 3: Archive a verbatim copy**

Run:
```bash
mkdir -p docs/handoff/archive
cp D:/RLH/5.6/repos/hydropools/docs/handoff/2026-10-30-clock-anchor-analysis.md docs/handoff/archive/2026-10-30-clock-anchor-analysis-6619c823.md
.venv/Scripts/python.exe -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('docs/handoff/archive/2026-10-30-clock-anchor-analysis-6619c823.md').read_bytes()).hexdigest())"
```
Expected: the same hash as Step 2.

- [ ] **Step 4: Write the provenance note**

Create `docs/handoff/2026-10-30-clock-anchor-provenance.md`:

```markdown
# Clock-anchor proposal: provenance of the reviewed versions

Date: 2026-10-30. Source file: `D:/RLH/5.6/repos/hydropools/docs/handoff/2026-10-30-clock-anchor-analysis.md`. The file is untracked in the hydropools repository, so no version history exists there. Three versions are known from hashes recorded by the reviewers; only the last is recoverable.

| Version | SHA-256 | Bytes | Recorded by | Recoverable |
| --- | --- | ---: | --- | --- |
| 1 | `5cbe392fb38af85f31b82a5d47fea0d618bbcde24f2c51bfa3d6847624dea76a` | unknown | audit text, `2026-10-30-clock-anchor-audit.md` §Source | no |
| 2 | `a57792864766669e87557c52849cd051b99538785a79bffaf6604962472b77c3` | 17,256 | audit receipt, `2026-10-30-clock-anchor-audit-evidence.json` (14:07 local) | no |
| 3 | `6619c8234a874f17b39c3db36755b4643945612655b70cbdcee2a829040deda7` | 19,223 | independent verdict (file modified 14:55 local, after the audit at 14:14) | yes: `archive/2026-10-30-clock-anchor-analysis-6619c823.md` |

What changed between versions 2 and 3, per the author's own note: section 1, section 5 and question 1 of section 6 were rewritten to frame the ask as "the rise edge of the trough band with a departure-size status" instead of "first post-trough month exceeding the trough by the floor, staying above until peak". Audit §5 was written against the earlier wording; the independent verdict judges version 3.

Rule from here: cite the proposal by hash. Any further edit to the source file gets a new row here and a new archive copy. No one edits the archived copies.
```

If Step 2 showed a different hash, add a row 4 with that hash and size, mark row 3 "no" under Recoverable, and point row 4 at the archive file you created.

- [ ] **Step 5: Commit the handoff directory**

Run:
```bash
git add docs/handoff/ docs/superpowers/plans/2026-10-30-clock-anchor-stage0.md
git status --short docs/handoff/ docs/superpowers/plans/
git commit -m "docs: archive clock-anchor proposal provenance and review documents"
```
Expected: the commit contains `docs/handoff/2026-10-30-clock-anchor-audit-evidence.json`, `2026-10-30-clock-anchor-audit.md`, `2026-10-30-clock-anchor-independent-review.md`, `2026-10-30-clock-anchor-independent-verdict.md`, `2026-10-30-clock-anchor-provenance.md`, `archive/2026-10-30-clock-anchor-analysis-6619c823.md`, and this plan file. Nothing else.

---

### Task 2: Target decision record (step 1)

**Files:**
- Create: `docs/handoff/2026-10-30-clock-anchor-target-decision.md`

**Interfaces:**
- Produces: a decision record the lead fills in. No later task in this plan reads it; stage 0 is target-agnostic. Stages A–C (not in this plan) require it filled.

- [ ] **Step 1: Write the record**

Create `docs/handoff/2026-10-30-clock-anchor-target-decision.md`:

```markdown
# Clock-anchor target decision record

Status: **awaiting lead**. Date opened: 2026-10-30. Decided: ____ (date, name).

Basis: [independent verdict](2026-10-30-clock-anchor-independent-verdict.md) §9 and §10. Stage 0 (frozen rise-rule synchrony test) runs without this record. Stages A, B and C do not start until every field below is filled.

## 1. Scientific target of the end-of-dry reading

Choose one, or name several products explicitly.

| Option | Definition | What the end-dry date means | Consequence |
| --- | --- | --- | --- |
| T1 minimum availability | Lowest supported extent in the post-peak window; may be an interval | Aggregate only; circular per pool | y is read at the band end as today; `start_date` and X unchanged |
| T2 pre-replenishment state | Occupancy in the last month of the supported low state (month before `rise_date`) | Needs a rise rule with status and interval; uncertainty `[L-1, U-1]` | HydroSeason additive fields (§9 contract); hydropools endpoint policy; refit |
| T3 continuous survival | No supported drying between recession start and replenishment | Interval-censored trajectory, not a date | New product; `pool_years.csv` drying fields are the starting point |

Decision: ____

## 2. Years without a sustained rise (failed wet season)

| Option | Effect |
| --- | --- |
| Censor into the next rise | One window spanning two years; one reading in the far tail of X; `refuge_2yr` and carry-over A partly redundant |
| One row per year, interim reading at the last observed low month, flagged `season_not_ended` | Keeps one reading per year; flag must propagate to identity, X, refuges |

Decision: ____

## 3. Hydropools and HydroSeason's own gates

Today hydropools consumes every cycle regardless of `boundary_status` (provisional in 1,257 of 1,558 tile-years), `status` (partial in 1,269) and `confidence` (low in 840); only `trough_timing_status` and date presence are consulted.

| Option | Effect |
| --- | --- |
| Keep ignoring the gates | No change; quality discarded before the anchor question |
| Honour `boundary_status == confirmed` | 301 tile-years keep a local clock; the rest need the donor policy below |
| Honour a named subset (state which columns and values) | ____ |

Decision: ____

## 4. Donor policy for tile-years without a local clock (rule (c))

Needed whatever the anchor: pixel counts will route tiles 05, 13, 18 and probably 46 out of per-year detection (verdict finding 10; 151 tile-years), and 135 windows already fall to `hy_boundary`.

Required fields in any implementation: `endpoint_source ∈ {local, donor_median, catchment}`, donor tile IDs, donor spread in months, year alignment, `endpoint_status`. No silent replacement of an unknown local date by a neighbour's.

Decision on donor set (network neighbours via AHGF up/downstream, then catchment; or other): ____
Decision on minimum donors and maximum spread before abstaining: ____

## 5. Referee for the chosen target

| Target | Admissible referee |
| --- | --- |
| T2 on gauge-connected reaches | First flow after a zero-flow spell at 802003, 802006, 802007, 802008, 802055, under a protocol written and hashed before any discharge file is opened for this purpose |
| Extent change anywhere | Independent imagery or field observation, blinded labels, "not identifiable" allowed |
| T3 | Drying and rewetting evidence per pool |

Decision: ____

## 6. Holdout

Jul–Dec 2026 counts as a holdout only with (a) a statement of what 2026 imagery has been viewed through any channel (DEA services, TSFill, Planet) and by whom, and (b) a hashed, frozen rule. The local WOfS cache ends 2026-06.

Statement: ____
```

- [ ] **Step 2: Commit**

Run:
```bash
git add docs/handoff/2026-10-30-clock-anchor-target-decision.md
git commit -m "docs: add clock-anchor target decision record for the lead"
```

---

### Task 3: Stage 0 script skeleton — frozen rule, margin, pure helpers

**Files:**
- Create: `scripts/clock_anchor_stage0.py`
- Create: `tests/test_clock_anchor_stage0.py`

**Interfaces:**
- Produces (used by Tasks 4–6 and the tests):
  - `RULE: dict`, `MARGIN: dict`, `HY_DATE_COLUMNS: list[str]`
  - `valid_denominator_extent(monthly: pd.DataFrame) -> pd.Series` — index month-start `Timestamp`, float, NaN where unobserved
  - `exported_extent(monthly: pd.DataFrame) -> pd.Series` — same index, the exported `extent_pct`
  - `month_index(stamp) -> int` — `year*12 + month-1`
  - `month_from_index(k: int) -> pd.Timestamp`
  - `end_dry_as_run(row: pd.Series) -> pd.Timestamp | None` — hydropools `dry_windows` chain without the re-wet guard
  - `weighted_median(values, weights) -> float`
  - `leave_one_out_deviations(values, weights, *, min_other: int) -> np.ndarray`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_clock_anchor_stage0.py`:

```python
"""Pin the arithmetic of the frozen stage-0 rise rule on known-truth synthetic series.

Nothing here is hydrological truth. The tests record what the rule in
scripts/clock_anchor_stage0.py computes, so that the real-data run in the plan
is a pre-specified test and not an exploration.
"""

import numpy as np
import pandas as pd
import pytest

from scripts.clock_anchor_stage0 import (
    HY_DATE_COLUMNS,
    MARGIN,
    RULE,
    end_dry_as_run,
    exported_extent,
    leave_one_out_deviations,
    month_from_index,
    month_index,
    valid_denominator_extent,
    weighted_median,
)


def test_rule_and_margin_are_the_frozen_values():
    assert RULE["version"] == "stage0_rise_v1"
    assert RULE["floor_pp_min"] == 1.0
    assert RULE["confirm_max_gap_months"] == 2
    assert RULE["scored_statuses"] == ["point", "interval"]
    assert MARGIN["min_within_1"] == 0.90
    assert MARGIN["min_gain_over_end_dry"] == 0.05
    assert MARGIN["min_coverage"] == 0.90
    assert MARGIN["big_tile_min_px"] == 3000
    assert MARGIN["min_other_tiles"] == 3
    assert MARGIN["min_scored_tile_years"] == 500
    assert (MARGIN["hy_first"], MARGIN["hy_last"]) == (1988, 2025)
    assert "trough_boundary_date" in HY_DATE_COLUMNS


def test_valid_denominator_extent_divides_by_observed_share():
    monthly = pd.DataFrame(
        {
            "date": ["2000-01-01", "2000-02-01", "2000-03-01"],
            "extent_pct": [10.0, 10.0, np.nan],
            "invalid_pct": [50.0, 0.0, 100.0],
        }
    )
    values = valid_denominator_extent(monthly)
    assert values.loc["2000-01-01"] == pytest.approx(20.0)
    assert values.loc["2000-02-01"] == pytest.approx(10.0)
    assert np.isnan(values.loc["2000-03-01"])
    assert exported_extent(monthly).loc["2000-01-01"] == pytest.approx(10.0)
    assert isinstance(values.index, pd.DatetimeIndex)


def test_month_index_is_absolute_and_invertible():
    assert month_index("2000-01-01") == 2000 * 12
    assert month_index("2000-12-01") - month_index("2000-01-01") == 11
    assert month_index("2001-01-01") - month_index("2000-12-01") == 1
    assert month_from_index(month_index("1999-11-01")) == pd.Timestamp("1999-11-01")


def test_end_dry_as_run_follows_the_hydropools_chain():
    point = pd.Series(
        {
            "trough_timing_status": "point",
            "trough_date": pd.Timestamp("2000-09-01"),
            "trough_interval_end_date": pd.Timestamp("2000-10-01"),
            "trough_boundary_date": pd.Timestamp("2000-09-01"),
        }
    )
    broad = pd.Series(
        {
            "trough_timing_status": "broad",
            "trough_date": pd.NaT,
            "trough_interval_end_date": pd.Timestamp("2000-10-01"),
            "trough_boundary_date": pd.Timestamp("2000-10-01"),
        }
    )
    unresolved = pd.Series(
        {
            "trough_timing_status": "unresolved",
            "trough_date": pd.NaT,
            "trough_interval_end_date": pd.NaT,
            "trough_boundary_date": pd.Timestamp("2000-08-01"),
        }
    )
    blank = pd.Series(
        {
            "trough_timing_status": None,
            "trough_date": pd.NaT,
            "trough_interval_end_date": pd.NaT,
            "trough_boundary_date": pd.NaT,
        }
    )
    assert end_dry_as_run(point) == pd.Timestamp("2000-09-01")
    assert end_dry_as_run(broad) == pd.Timestamp("2000-10-01")
    assert end_dry_as_run(unresolved) == pd.Timestamp("2000-08-01")
    assert end_dry_as_run(blank) is None


def test_weighted_median_matches_the_proposal_definition():
    assert weighted_median([1, 2, 10], [1, 1, 1]) == 2.0
    assert weighted_median([1, 2, 10], [5, 1, 1]) == 1.0
    assert weighted_median([3], [7]) == 3.0


def test_leave_one_out_deviations_exclude_the_target():
    devs = leave_one_out_deviations([5, 5, 5, 9], [1, 1, 1, 1], min_other=3)
    assert list(devs) == [0.0, 0.0, 0.0, 4.0]
    assert np.isnan(leave_one_out_deviations([5, 9], [1, 1], min_other=3)).all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `ModuleNotFoundError: No module named 'scripts.clock_anchor_stage0'` (collection error).

- [ ] **Step 3: Create the script with the frozen constants and helpers**

Create `scripts/clock_anchor_stage0.py`:

```python
"""Stage 0 of the clock-anchor thread: does a frozen rise rule agree across tiles?

Reads hydropools' historical HydroSeason outputs read-only (per tile:
``channel_monthly_extent.csv`` and ``*_hydro_years.csv``) and the hydropools
output manifest (channel pixel counts). For every tile-year it locates the
first sustained departure from the trough band under ``RULE`` and scores how
well tiles agree on that month, against the end-dry hydropools uses today.

``RULE``, ``MARGIN`` and ``VARIANTS`` are frozen before any real data is read
(see docs/superpowers/plans/2026-10-30-clock-anchor-stage0.md, Task 7). They
are not method thresholds and nothing in ``hydroseason/`` uses them.

Example:

    .venv/Scripts/python.exe scripts/clock_anchor_stage0.py \
        --hydroseason-dir D:/RLH/5.6/repos/hydropools/work/rerun/fitzroy/hydroseason \
        --manifest D:/RLH/5.6/repos/hydropools/outputs/rerun/fitzroy/manifest.json \
        --out dev/reports/2026-10-30-clock-anchor-stage0.csv \
        --summary dev/reports/2026-10-30-clock-anchor-stage0.md \
        --receipt dev/reports/2026-10-30-clock-anchor-stage0.json
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RULE = {
    "version": "stage0_rise_v1",
    "extent": "valid_denominator: extent_pct / (1 - invalid_pct / 100)",
    "level": "median of the valid-denominator extent over the trough band "
    "(trough_interval_start_date..trough_interval_end_date, else the boundary month)",
    "floor_pp_min": 1.0,
    "threshold": "level + max(detectability_floor_pp, floor_pp_min)",
    "search": "months after trough_boundary_date up to and including the window end",
    "window_end": "next cycle's peak_date, else its peak_interval_start_date, "
    "else its trough_boundary_date",
    "confirm_max_gap_months": 2,
    "confirmation": "the next observed month, at most confirm_max_gap_months later and "
    "inside the window, must also exceed the threshold; a single exceedance followed by a "
    "return below it is a pulse and the search continues",
    "status": {
        "point": "confirmed, and the calendar month before the rise month was observed below "
        "the threshold",
        "interval": "confirmed, but the last observed low month is more than one month "
        "earlier (or the boundary month itself was unobserved); interval = "
        "[last low month + 1, rise month]",
        "unconfirmed": "an exceedance with no following observation inside the window within "
        "confirm_max_gap_months",
        "no_rise": "nothing exceeds the threshold before the window end",
        "no_observed_months": "no observed month between the boundary and the window end",
        "no_band_level": "no observed month inside the trough band",
        "no_window": "no boundary, no following cycle, or a window end at or before the boundary",
    },
    "scored_month": "the rise month (first observed exceedance; the interval's end)",
    "scored_statuses": ["point", "interval"],
}

MARGIN = {
    "min_within_1": 0.90,
    "min_gain_over_end_dry": 0.05,
    "min_coverage": 0.90,
    "big_tile_min_px": 3000,
    "min_other_tiles": 3,
    "min_scored_tile_years": 500,
    "hy_first": 1988,
    "hy_last": 2025,
    "primary_metric": "pooled share of big-tile tile-years within +-1 month of the "
    "leave-target-out channel-pixel-weighted median of the same year",
    "coverage": "point + interval over all statuses except no_window, big tiles",
}

HY_DATE_COLUMNS = [
    "trough_boundary_date",
    "trough_interval_start_date",
    "trough_interval_end_date",
    "trough_date",
    "peak_date",
    "peak_interval_start_date",
    "mid_dry_date",
]


def _month_axis(monthly: pd.DataFrame) -> pd.DatetimeIndex:
    stamps = pd.to_datetime(monthly["date"]).dt.to_period("M").dt.to_timestamp()
    return pd.DatetimeIndex(stamps)


def valid_denominator_extent(monthly: pd.DataFrame) -> pd.Series:
    """Hydropools exports 100*wet/n_aoi and 100*(n_aoi-obs)/n_aoi; their quotient is the valid-pixel extent."""
    extent = pd.to_numeric(monthly["extent_pct"], errors="coerce").to_numpy(dtype=float)
    invalid = pd.to_numeric(monthly["invalid_pct"], errors="coerce").to_numpy(dtype=float)
    observed = 1.0 - invalid / 100.0
    with np.errstate(divide="ignore", invalid="ignore"):
        values = np.where(
            np.isfinite(extent) & np.isfinite(observed) & (observed > 0.0),
            extent / observed,
            np.nan,
        )
    return pd.Series(values, index=_month_axis(monthly), name="valid_denominator_extent").sort_index()


def exported_extent(monthly: pd.DataFrame) -> pd.Series:
    """The exported ``extent_pct`` as is (denominator = all footprint pixels)."""
    extent = pd.to_numeric(monthly["extent_pct"], errors="coerce").to_numpy(dtype=float)
    return pd.Series(extent, index=_month_axis(monthly), name="exported_extent").sort_index()


def month_index(stamp) -> int:
    ts = pd.Timestamp(stamp)
    return ts.year * 12 + ts.month - 1


def month_from_index(k: int) -> pd.Timestamp:
    return pd.Timestamp(year=k // 12, month=k % 12 + 1, day=1)


def end_dry_as_run(row: pd.Series) -> pd.Timestamp | None:
    """hydropools ``seasons.dry_windows`` chain: point -> interval end -> boundary. No re-wet guard."""
    if row.get("trough_timing_status") == "point" and pd.notna(row.get("trough_date")):
        return pd.Timestamp(row["trough_date"])
    if pd.notna(row.get("trough_interval_end_date")):
        return pd.Timestamp(row["trough_interval_end_date"])
    if pd.notna(row.get("trough_boundary_date")):
        return pd.Timestamp(row["trough_boundary_date"])
    return None


def weighted_median(values, weights) -> float:
    """First value whose cumulative weight reaches half the total (the proposal's ``sync.py`` rule)."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cumulative, cumulative[-1] / 2.0)])


def leave_one_out_deviations(values, weights, *, min_other: int) -> np.ndarray:
    """Absolute distance of each value from the weighted median of the others; NaN if too few others."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) - 1 < min_other:
        return out
    for i in range(len(values)):
        out[i] = abs(values[i] - weighted_median(np.delete(values, i), np.delete(weights, i)))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `6 passed`.

- [ ] **Step 5: Lint**

Run: `.venv/Scripts/python.exe -m ruff check scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py
git commit -m "chore: add stage-0 clock-anchor script skeleton with frozen rule and margin"
```

---

### Task 4: The rise rule

**Files:**
- Modify: `scripts/clock_anchor_stage0.py` (append)
- Modify: `tests/test_clock_anchor_stage0.py` (append)

**Interfaces:**
- Consumes: `month_index`, `month_from_index` from Task 3.
- Produces: `rise_month(values: pd.Series, row: pd.Series, next_row: pd.Series | None, *, floor_pp_min: float, confirm_max_gap_months: int) -> dict` with keys `status, rise_month, interval_start, interval_end, level_pp, threshold_pp, window_end, band_start, band_end, n_pulses`. Dates are `pd.Timestamp` or `pd.NaT`; floats are `float` or `nan`.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_clock_anchor_stage0.py` (add `rise_month` to the import list at the top):

```python
def _series(overrides=None, missing=(), base=2.0, start="2000-01-01", months=48):
    index = pd.date_range(start, periods=months, freq="MS")
    values = pd.Series(base, index=index, dtype=float)
    for stamp, value in (overrides or {}).items():
        values.loc[pd.Timestamp(stamp)] = value
    for stamp in missing:
        values.loc[pd.Timestamp(stamp)] = np.nan
    return values


def _cycle(year, floor=0.5):
    return dict(
        hy_year=year,
        trough_boundary_date=f"{year}-09-01",
        trough_interval_start_date=f"{year}-08-01",
        trough_interval_end_date=f"{year}-09-01",
        trough_date=f"{year}-09-01",
        trough_timing_status="point",
        peak_date=f"{year}-02-01",
        peak_interval_start_date=None,
        mid_dry_date=f"{year}-06-01",
        detectability_floor_pp=floor,
    )


def _rows(*years):
    frame = pd.DataFrame([_cycle(year) for year in years])
    for col in HY_DATE_COLUMNS:
        frame[col] = pd.to_datetime(frame[col])
    return frame


def _rise(values, rows, **kwargs):
    kwargs.setdefault("floor_pp_min", 1.0)
    kwargs.setdefault("confirm_max_gap_months", 2)
    return rise_month(values, rows.iloc[0], rows.iloc[1], **kwargs)


def test_rise_month_point_when_the_departure_is_bracketed_and_confirmed():
    values = _series({"2000-12-01": 6.0, "2001-01-01": 12.0, "2001-02-01": 20.0})
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2000-12-01")
    assert result["interval_start"] == pd.Timestamp("2000-12-01")
    assert result["interval_end"] == pd.Timestamp("2000-12-01")
    assert result["level_pp"] == pytest.approx(2.0)
    assert result["threshold_pp"] == pytest.approx(3.0)  # band median 2.0 + max(0.5, 1.0)
    assert result["window_end"] == pd.Timestamp("2001-02-01")
    assert result["band_start"] == pd.Timestamp("2000-08-01")
    assert result["n_pulses"] == 0


def test_rise_month_skips_a_one_month_pulse():
    values = _series({"2000-10-01": 5.0, "2001-01-01": 7.0, "2001-02-01": 12.0})
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2001-01-01")
    assert result["n_pulses"] == 1


def test_rise_month_reports_an_interval_across_a_gap():
    values = _series({"2000-12-01": 6.0, "2001-01-01": 12.0}, missing=["2000-11-01"])
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "interval"
    assert result["rise_month"] == pd.Timestamp("2000-12-01")
    assert result["interval_start"] == pd.Timestamp("2000-11-01")
    assert result["interval_end"] == pd.Timestamp("2000-12-01")


def test_rise_month_is_unconfirmed_without_a_following_observation():
    values = _series({"2001-02-01": 6.0})  # the exceedance is the window's last month
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "unconfirmed"
    assert result["rise_month"] == pd.Timestamp("2001-02-01")


def test_rise_month_is_unconfirmed_when_the_next_observation_is_too_far():
    values = _series(
        {"2000-11-01": 6.0, "2001-02-01": 12.0}, missing=["2000-12-01", "2001-01-01"]
    )
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "unconfirmed"
    assert result["rise_month"] == pd.Timestamp("2000-11-01")


def test_rise_month_confirms_across_a_single_missing_month():
    values = _series({"2000-11-01": 6.0, "2001-01-01": 12.0}, missing=["2000-12-01"])
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2000-11-01")
    assert _rise(values, _rows(2000, 2001), confirm_max_gap_months=1)["status"] == "unconfirmed"


def test_rise_month_no_rise_when_nothing_leaves_the_band():
    assert _rise(_series(), _rows(2000, 2001))["status"] == "no_rise"


def test_rise_month_abstention_statuses():
    rows = _rows(2000, 2001)
    no_band = _series(missing=["2000-08-01", "2000-09-01"])
    assert _rise(no_band, rows)["status"] == "no_band_level"
    unobserved = _series(missing=[f"2000-{m:02d}-01" for m in (10, 11, 12)] + ["2001-01-01", "2001-02-01"])
    assert _rise(unobserved, rows)["status"] == "no_observed_months"
    assert rise_month(_series(), rows.iloc[0], None, floor_pp_min=1.0, confirm_max_gap_months=2)["status"] == "no_window"


def test_rise_month_uses_the_detectability_floor_when_it_exceeds_the_minimum():
    values = _series({"2000-12-01": 4.5, "2001-01-01": 4.6, "2001-02-01": 20.0})
    rows = _rows(2000, 2001)
    rows.loc[0, "detectability_floor_pp"] = 3.0  # threshold 2.0 + 3.0 = 5.0
    result = _rise(values, rows)
    assert result["threshold_pp"] == pytest.approx(5.0)
    assert result["status"] == "unconfirmed"  # only February exceeds, and it is the last month


def test_rise_month_falls_back_to_the_next_boundary_when_the_next_peak_is_missing():
    rows = _rows(2000, 2001)
    rows.loc[1, "peak_date"] = pd.NaT
    values = _series({"2001-03-01": 6.0, "2001-04-01": 12.0})
    result = _rise(values, rows)
    assert result["window_end"] == pd.Timestamp("2001-09-01")
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2001-03-01")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `ImportError: cannot import name 'rise_month'`.

- [ ] **Step 3: Append the implementation**

Append to `scripts/clock_anchor_stage0.py`:

```python
def _first_present(row: pd.Series, columns: tuple[str, ...]) -> pd.Timestamp | None:
    for col in columns:
        if pd.notna(row.get(col)):
            return pd.Timestamp(row[col])
    return None


def rise_month(
    values: pd.Series,
    row: pd.Series,
    next_row: pd.Series | None,
    *,
    floor_pp_min: float,
    confirm_max_gap_months: int,
) -> dict:
    """Apply ``RULE`` to one cycle. ``values`` is a month-start-indexed extent series."""
    out = dict(
        status=None,
        rise_month=pd.NaT,
        interval_start=pd.NaT,
        interval_end=pd.NaT,
        level_pp=np.nan,
        threshold_pp=np.nan,
        window_end=pd.NaT,
        band_start=pd.NaT,
        band_end=pd.NaT,
        n_pulses=0,
    )
    boundary = row.get("trough_boundary_date")
    if pd.isna(boundary) or next_row is None:
        out["status"] = "no_window"
        return out
    boundary = pd.Timestamp(boundary)
    window_end = _first_present(
        next_row, ("peak_date", "peak_interval_start_date", "trough_boundary_date")
    )
    if window_end is None or window_end <= boundary:
        out["status"] = "no_window"
        return out
    out["window_end"] = window_end

    band_start = row.get("trough_interval_start_date")
    band_end = row.get("trough_interval_end_date")
    if pd.isna(band_start) or pd.isna(band_end):
        band_start = band_end = boundary
    band_start, band_end = pd.Timestamp(band_start), pd.Timestamp(band_end)
    out["band_start"], out["band_end"] = band_start, band_end
    band = values.loc[band_start:band_end].dropna()
    if band.empty:
        out["status"] = "no_band_level"
        return out
    level = float(band.median())
    floor = row.get("detectability_floor_pp")
    floor = float(floor) if pd.notna(floor) else 0.0
    threshold = level + max(floor, float(floor_pp_min))
    out.update(level_pp=level, threshold_pp=threshold)

    span = values.loc[boundary + pd.DateOffset(months=1) : window_end].dropna()
    if span.empty:
        out["status"] = "no_observed_months"
        return out
    k = np.array([month_index(stamp) for stamp in span.index])
    exceed = span.to_numpy(dtype=float) > threshold
    boundary_value = float(values.get(boundary, np.nan))
    last_low_k = (
        month_index(boundary)
        if np.isfinite(boundary_value) and boundary_value <= threshold
        else None
    )

    def _interval_start(rise_k: int) -> pd.Timestamp:
        start_k = last_low_k + 1 if last_low_k is not None else month_index(boundary) + 1
        return month_from_index(min(start_k, rise_k))

    pulses = 0
    i = 0
    while i < len(k):
        if not exceed[i]:
            last_low_k = int(k[i])
            i += 1
            continue
        j = i + 1
        if j >= len(k) or k[j] - k[i] > confirm_max_gap_months:
            out.update(
                status="unconfirmed",
                rise_month=span.index[i],
                interval_start=_interval_start(int(k[i])),
                interval_end=span.index[i],
                n_pulses=pulses,
            )
            return out
        if exceed[j]:
            bracketed = last_low_k is not None and last_low_k + 1 == int(k[i])
            out.update(
                status="point" if bracketed else "interval",
                rise_month=span.index[i],
                interval_start=_interval_start(int(k[i])),
                interval_end=span.index[i],
                n_pulses=pulses,
            )
            return out
        pulses += 1
        last_low_k = int(k[j])
        i = j + 1
    out.update(status="no_rise", n_pulses=pulses)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `16 passed`.

- [ ] **Step 5: Lint and commit**

Run: `.venv/Scripts/python.exe -m ruff check scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py`
Expected: `All checks passed!`

```bash
git add scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py
git commit -m "chore: add frozen stage-0 rise rule with known-truth tests"
```

---

### Task 5: Synchrony metric and decision

**Files:**
- Modify: `scripts/clock_anchor_stage0.py` (append)
- Modify: `tests/test_clock_anchor_stage0.py` (append)

**Interfaces:**
- Consumes: `month_index`, `leave_one_out_deviations`, `MARGIN`.
- Produces:
  - `synchrony(table: pd.DataFrame, month_col: str, *, big_tile_min_px: int, min_other_tiles: int) -> dict` with keys `n_tile_years, n_years, pooled_within_1, mean_within_1, share_ge3`. `table` needs columns `hy_year`, `px`, and `month_col` (datetime, NaT allowed).
  - `decide(rise: dict, end_dry: dict, coverage: float) -> str` returning `"PASS"`, `"FAIL"` or `"INCONCLUSIVE"`.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_clock_anchor_stage0.py` (add `decide`, `synchrony` to the import list):

```python
def test_synchrony_scores_leave_target_out_agreement_on_big_tiles():
    table = pd.DataFrame(
        {
            "tile": ["a", "b", "c", "d", "small"] * 2,
            "hy_year": [2000] * 5 + [2001] * 5,
            "px": [5000, 5000, 5000, 5000, 100] * 2,
            "month": pd.to_datetime(
                [
                    "2000-12-01", "2000-12-01", "2001-01-01", "2001-04-01", "2000-06-01",
                    "2001-12-01", "2001-12-01", "2001-12-01", None, "2001-06-01",
                ]
            ),
        }
    )
    result = synchrony(table, "month", big_tile_min_px=3000, min_other_tiles=3)
    assert result["n_years"] == 1  # 2001 leaves each big tile with only two others
    assert result["n_tile_years"] == 4
    assert result["pooled_within_1"] == pytest.approx(0.75)
    assert result["mean_within_1"] == pytest.approx(0.75)
    assert result["share_ge3"] == pytest.approx(0.25)


def test_synchrony_is_empty_without_enough_tiles():
    table = pd.DataFrame({"hy_year": [2000, 2000], "px": [5000, 5000], "month": pd.to_datetime(["2000-12-01", "2001-01-01"])})
    result = synchrony(table, "month", big_tile_min_px=3000, min_other_tiles=3)
    assert result["n_tile_years"] == 0
    assert np.isnan(result["pooled_within_1"])


def test_decide_applies_the_frozen_margin():
    end_dry = {"n_tile_years": 1000, "pooled_within_1": 0.83}
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.91}, end_dry, coverage=0.95) == "PASS"
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.91}, end_dry, coverage=0.85) == "FAIL"
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.87}, end_dry, coverage=0.95) == "FAIL"
    strong_baseline = {"n_tile_years": 1000, "pooled_within_1": 0.92}
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.95}, strong_baseline, coverage=0.95) == "FAIL"
    assert decide({"n_tile_years": 100, "pooled_within_1": 0.95}, end_dry, coverage=0.95) == "INCONCLUSIVE"
    assert decide({"n_tile_years": 1000, "pooled_within_1": np.nan}, end_dry, coverage=0.95) == "INCONCLUSIVE"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `ImportError: cannot import name 'decide'`.

- [ ] **Step 3: Append the implementation**

Append to `scripts/clock_anchor_stage0.py`:

```python
def synchrony(
    table: pd.DataFrame, month_col: str, *, big_tile_min_px: int, min_other_tiles: int
) -> dict:
    """Leave-target-out, channel-pixel-weighted agreement of big tiles on ``month_col`` per year."""
    rows = table.dropna(subset=[month_col])
    rows = rows[rows["px"] >= big_tile_min_px]
    deviations, per_year = [], []
    for _, group in rows.groupby("hy_year"):
        k = np.array([month_index(stamp) for stamp in group[month_col]])
        d = leave_one_out_deviations(k, group["px"].to_numpy(dtype=float), min_other=min_other_tiles)
        d = d[np.isfinite(d)]
        if d.size == 0:
            continue
        deviations.append(d)
        per_year.append(float((d <= 1).mean()))
    if not deviations:
        return dict(n_tile_years=0, n_years=0, pooled_within_1=np.nan, mean_within_1=np.nan, share_ge3=np.nan)
    d = np.concatenate(deviations)
    return dict(
        n_tile_years=int(d.size),
        n_years=len(per_year),
        pooled_within_1=float((d <= 1).mean()),
        mean_within_1=float(np.mean(per_year)),
        share_ge3=float((d >= 3).mean()),
    )


def decide(rise: dict, end_dry: dict, coverage: float) -> str:
    """Apply ``MARGIN``. PASS only if the rise rule is synchronous, better than today, and covers enough."""
    enough = (
        rise["n_tile_years"] >= MARGIN["min_scored_tile_years"]
        and end_dry["n_tile_years"] >= MARGIN["min_scored_tile_years"]
        and np.isfinite(rise["pooled_within_1"])
        and np.isfinite(end_dry["pooled_within_1"])
    )
    if not enough:
        return "INCONCLUSIVE"
    passed = (
        rise["pooled_within_1"] >= MARGIN["min_within_1"]
        and rise["pooled_within_1"] - end_dry["pooled_within_1"] >= MARGIN["min_gain_over_end_dry"]
        and coverage >= MARGIN["min_coverage"]
    )
    return "PASS" if passed else "FAIL"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `19 passed`.

- [ ] **Step 5: Lint and commit**

Run: `.venv/Scripts/python.exe -m ruff check scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py`
Expected: `All checks passed!`

```bash
git add scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py
git commit -m "chore: add leave-target-out synchrony metric and frozen decision for stage 0"
```

---

### Task 6: Loaders, variants, receipt and CLI

**Files:**
- Modify: `scripts/clock_anchor_stage0.py` (replace the import block; append)
- Modify: `tests/test_clock_anchor_stage0.py` (append)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `VARIANTS: tuple[dict, ...]` — five named variants; `"primary"` decides.
  - `channel_pixels(manifest_path: Path) -> dict[str, int]`
  - `load_tile(tile_dir: Path) -> tuple[str, pd.DataFrame, pd.DataFrame]` — `(tile_name, monthly, hydro_years)`
  - `evaluate_tile(tile, monthly, hy, px, *, extent, floor_pp_min, confirm_max_gap_months) -> list[dict]`
  - `run(hydroseason_dir: Path, manifest_path: Path) -> tuple[pd.DataFrame, dict]`
  - `receipt(hydroseason_dir, manifest_path, summary) -> dict`
  - `to_markdown(summary) -> str`
  - `main(argv=None) -> int`

- [ ] **Step 1: Append the failing smoke test**

Append to `tests/test_clock_anchor_stage0.py` (add `VARIANTS`, `main` to the import list, and `import json` plus `from pathlib import Path` at the top of the file, keeping stdlib imports before third-party ones):

```python
def _write_tile(root: Path, tile: str, rise_month_of_year: int):
    tile_dir = root / tile
    tile_dir.mkdir(parents=True)
    index = pd.date_range("1987-01-01", periods=12 * 40, freq="MS")
    extent = pd.Series(2.0, index=index)
    for year in range(1987, 2027):
        for offset, value in ((0, 6.0), (1, 12.0), (2, 20.0)):
            stamp = pd.Timestamp(year=year, month=rise_month_of_year, day=1) + pd.DateOffset(months=offset)
            if stamp in extent.index:
                extent.loc[stamp] = value
    pd.DataFrame({"date": index.strftime("%Y-%m-%d"), "extent_pct": extent.to_numpy(), "invalid_pct": 0.0}).to_csv(
        tile_dir / "channel_monthly_extent.csv", index=False
    )
    rows = []
    for year in range(1988, 2027):
        rows.append(
            dict(
                hy_year=year,
                trough_boundary_date=f"{year}-09-01",
                trough_interval_start_date=f"{year}-08-01",
                trough_interval_end_date=f"{year}-09-01",
                trough_date=f"{year}-09-01",
                trough_timing_status="point",
                peak_date=f"{year}-02-01",
                peak_interval_start_date="",
                mid_dry_date=f"{year}-06-01",
                detectability_floor_pp=0.5,
            )
        )
    pd.DataFrame(rows).to_csv(tile_dir / f"fitzroy-{tile}_hydro_years.csv", index=False)


def test_main_writes_table_summary_and_receipt(tmp_path):
    hydroseason_dir = tmp_path / "hydroseason"
    _write_tile(hydroseason_dir, "tile01", rise_month_of_year=12)
    _write_tile(hydroseason_dir, "tile02", rise_month_of_year=11)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"summary": {"regions": [{"name": "tile01", "channel_px": 5000}, {"name": "tile02", "channel_px": 4000}]}})
    )
    out = tmp_path / "stage0.csv"
    summary = tmp_path / "stage0.md"
    receipt = tmp_path / "stage0.json"
    code = main(
        [
            "--hydroseason-dir", str(hydroseason_dir),
            "--manifest", str(manifest),
            "--out", str(out),
            "--summary", str(summary),
            "--receipt", str(receipt),
        ]
    )
    assert code == 0
    table = pd.read_csv(out)
    assert set(table["variant"]) == {variant["name"] for variant in VARIANTS}
    primary = table[(table["variant"] == "primary") & (table["tile"] == "tile01")]
    assert len(primary) == 38  # hy 1988..2025
    assert (primary["status"] == "point").all()
    assert (pd.to_datetime(primary["rise_month"]).dt.month == 12).all()
    assert (pd.to_datetime(primary["end_dry_as_run"]).dt.month == 9).all()
    report = json.loads(receipt.read_text())
    assert report["decision"] == "INCONCLUSIVE"  # two tiles: fewer than three others per year
    assert report["rule"]["version"] == "stage0_rise_v1"
    assert set(report["inputs"]) == {
        "tile01/channel_monthly_extent.csv", "tile01/fitzroy-tile01_hydro_years.csv",
        "tile02/channel_monthly_extent.csv", "tile02/fitzroy-tile02_hydro_years.csv",
    }
    assert "primary" in summary.read_text()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `ImportError: cannot import name 'VARIANTS'`.

- [ ] **Step 3: Replace the import block and append the implementation**

Replace the import block at the top of `scripts/clock_anchor_stage0.py` with:

```python
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
```

Append to the end of `scripts/clock_anchor_stage0.py`:

```python
VARIANTS = (
    dict(name="primary", extent="valid_denominator", floor_pp_min=1.0, confirm_max_gap_months=2),
    dict(name="floor_2pp", extent="valid_denominator", floor_pp_min=2.0, confirm_max_gap_months=2),
    dict(name="floor_only", extent="valid_denominator", floor_pp_min=0.0, confirm_max_gap_months=2),
    dict(name="exported_extent", extent="exported", floor_pp_min=1.0, confirm_max_gap_months=2),
    dict(name="confirm_1", extent="valid_denominator", floor_pp_min=1.0, confirm_max_gap_months=1),
)


def channel_pixels(manifest_path: Path) -> dict[str, int]:
    manifest = json.loads(Path(manifest_path).read_text())
    return {region["name"]: int(region["channel_px"]) for region in manifest["summary"]["regions"]}


def load_tile(tile_dir: Path) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    monthly = pd.read_csv(tile_dir / "channel_monthly_extent.csv")
    hy_paths = sorted(tile_dir.glob("*_hydro_years.csv"))
    if len(hy_paths) != 1:
        raise FileNotFoundError(f"{tile_dir}: expected one *_hydro_years.csv, found {len(hy_paths)}")
    hy = pd.read_csv(hy_paths[0])
    for col in HY_DATE_COLUMNS:
        hy[col] = pd.to_datetime(hy[col], errors="coerce")
    hy = hy.sort_values("hy_year").reset_index(drop=True)
    return tile_dir.name, monthly, hy


def evaluate_tile(
    tile: str,
    monthly: pd.DataFrame,
    hy: pd.DataFrame,
    px: int,
    *,
    extent: str,
    floor_pp_min: float,
    confirm_max_gap_months: int,
) -> list[dict]:
    values = valid_denominator_extent(monthly) if extent == "valid_denominator" else exported_extent(monthly)
    out = []
    for i in range(len(hy)):
        row = hy.iloc[i]
        year = int(row["hy_year"])
        if year < MARGIN["hy_first"] or year > MARGIN["hy_last"]:
            continue
        next_row = hy.iloc[i + 1] if i + 1 < len(hy) else None
        result = rise_month(
            values, row, next_row,
            floor_pp_min=floor_pp_min, confirm_max_gap_months=confirm_max_gap_months,
        )
        pre_rise = (
            result["rise_month"] - pd.DateOffset(months=1) if pd.notna(result["rise_month"]) else pd.NaT
        )
        out.append(
            dict(
                tile=tile,
                hy_year=year,
                px=px,
                boundary=row["trough_boundary_date"],
                trough_timing_status=row.get("trough_timing_status"),
                floor_pp=row.get("detectability_floor_pp"),
                end_dry_as_run=end_dry_as_run(row),
                pre_rise_month=pre_rise,
                **result,
            )
        )
    return out


def _variant_summary(sub: pd.DataFrame) -> dict:
    covered = sub["status"].isin(RULE["scored_statuses"])
    eligible = sub["status"].ne("no_window")
    big = sub["px"] >= MARGIN["big_tile_min_px"]
    scored = sub.assign(scored_month=sub["rise_month"].where(covered))
    widths = (
        scored.loc[covered, "interval_end"].map(month_index) - scored.loc[covered, "interval_start"].map(month_index)
    )
    return dict(
        rise=synchrony(
            scored, "scored_month",
            big_tile_min_px=MARGIN["big_tile_min_px"], min_other_tiles=MARGIN["min_other_tiles"],
        ),
        coverage_big=float((covered & big).sum() / max(int((eligible & big).sum()), 1)),
        coverage_all=float(covered.sum() / max(int(eligible.sum()), 1)),
        status_counts={str(k): int(v) for k, v in sub["status"].value_counts().items()},
        median_interval_width_months=float(widths.median()) if len(widths) else float("nan"),
        median_months_boundary_to_rise=float(
            (scored.loc[covered, "rise_month"].map(month_index) - scored.loc[covered, "boundary"].map(month_index)).median()
        ) if covered.any() else float("nan"),
    )


def run(hydroseason_dir: Path, manifest_path: Path) -> tuple[pd.DataFrame, dict]:
    px = channel_pixels(manifest_path)
    tile_dirs = sorted(path for path in Path(hydroseason_dir).iterdir() if path.is_dir())
    tiles = [load_tile(path) for path in tile_dirs]
    frames = []
    for variant in VARIANTS:
        options = {key: value for key, value in variant.items() if key != "name"}
        for tile, monthly, hy in tiles:
            if tile not in px:
                raise KeyError(f"{tile} is not a region in {manifest_path}")
            frame = pd.DataFrame(evaluate_tile(tile, monthly, hy, px[tile], **options))
            frame["variant"] = variant["name"]
            frames.append(frame)
    table = pd.concat(frames, ignore_index=True)
    primary = table[table["variant"] == "primary"]
    end_dry = synchrony(
        primary[primary["status"].ne("no_window")], "end_dry_as_run",
        big_tile_min_px=MARGIN["big_tile_min_px"], min_other_tiles=MARGIN["min_other_tiles"],
    )
    summary = {
        "n_tiles": len(tiles),
        "n_big_tiles": int(sum(px[tile] >= MARGIN["big_tile_min_px"] for tile, _, _ in tiles)),
        "end_dry_as_run": end_dry,
        "variants": {
            variant["name"]: _variant_summary(table[table["variant"] == variant["name"]])
            for variant in VARIANTS
        },
    }
    summary["decision"] = decide(
        summary["variants"]["primary"]["rise"], end_dry, summary["variants"]["primary"]["coverage_big"]
    )
    return table, summary


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=Path(__file__).resolve().parent.parent, check=False,
        )
        return result.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def receipt(hydroseason_dir: Path, manifest_path: Path, summary: dict) -> dict:
    hydroseason_dir = Path(hydroseason_dir)
    inputs = {
        path.relative_to(hydroseason_dir).as_posix(): _sha256(path)
        for path in sorted(hydroseason_dir.rglob("*.csv"))
        if path.name == "channel_monthly_extent.csv" or path.name.endswith("_hydro_years.csv")
    }
    return dict(
        rule=RULE,
        margin=MARGIN,
        variants=list(VARIANTS),
        script_sha256=_sha256(Path(__file__)),
        git_head=_git_head(),
        manifest_sha256=_sha256(manifest_path),
        inputs=inputs,
        numpy=np.__version__,
        pandas=pd.__version__,
        decision=summary["decision"],
        summary=summary,
    )


def _fmt(value, digits=3) -> str:
    try:
        return f"{float(value):.{digits}f}" if np.isfinite(float(value)) else "n/a"
    except (TypeError, ValueError):
        return "n/a"


def to_markdown(summary: dict) -> str:
    end_dry = summary["end_dry_as_run"]
    lines = [
        f"Decision (primary variant, frozen margin): **{summary['decision']}**",
        "",
        f"Tiles read: {summary['n_tiles']} ({summary['n_big_tiles']} with channel_px >= "
        f"{MARGIN['big_tile_min_px']}). Scored years {MARGIN['hy_first']}-{MARGIN['hy_last']}.",
        "",
        "End-dry as run (hydropools chain, no re-wet guard): "
        f"pooled within +-1 = {_fmt(end_dry['pooled_within_1'])}, mean of years = "
        f"{_fmt(end_dry['mean_within_1'])}, >=3 off = {_fmt(end_dry['share_ge3'])}, "
        f"n = {end_dry['n_tile_years']} tile-years over {end_dry['n_years']} years.",
        "",
        "| variant | within +-1 (pooled) | within +-1 (mean of years) | >=3 off | n tile-years "
        "| coverage big | coverage all | median interval width | median boundary->rise | statuses |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, item in summary["variants"].items():
        rise = item["rise"]
        statuses = ", ".join(f"{key} {value}" for key, value in sorted(item["status_counts"].items()))
        lines.append(
            f"| {name} | {_fmt(rise['pooled_within_1'])} | {_fmt(rise['mean_within_1'])} "
            f"| {_fmt(rise['share_ge3'])} | {rise['n_tile_years']} | {_fmt(item['coverage_big'])} "
            f"| {_fmt(item['coverage_all'])} | {_fmt(item['median_interval_width_months'], 1)} "
            f"| {_fmt(item['median_months_boundary_to_rise'], 1)} | {statuses} |"
        )
    lines += [
        "",
        f"Margin: within +-1 >= {MARGIN['min_within_1']}, gain over end-dry >= "
        f"{MARGIN['min_gain_over_end_dry']}, coverage (big tiles) >= {MARGIN['min_coverage']}, "
        f"at least {MARGIN['min_scored_tile_years']} scored tile-years. Only the primary variant decides.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--hydroseason-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)

    table, summary = run(args.hydroseason_dir, args.manifest)
    for path in (args.out, args.summary, args.receipt):
        path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    args.summary.write_text(to_markdown(summary), encoding="utf-8")
    args.receipt.write_text(
        json.dumps(receipt(args.hydroseason_dir, args.manifest, summary), indent=1, default=str),
        encoding="utf-8",
    )
    print(f"decision={summary['decision']} rows={len(table)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_clock_anchor_stage0.py -q -p no:cacheprovider --basetemp build/pytest-tmp`
Expected: `20 passed`.

- [ ] **Step 5: Lint and commit**

Run: `.venv/Scripts/python.exe -m ruff check scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py`
Expected: `All checks passed!` (if ruff asks to sort the test module's imports, apply `--fix` to the test file only and rerun the tests).

```bash
git add scripts/clock_anchor_stage0.py tests/test_clock_anchor_stage0.py
git commit -m "chore: add stage-0 loaders, variants, receipt and CLI with synthetic smoke test"
```

---

### Task 7: Freeze, then run on the historical outputs

**Files:**
- Create: `docs/handoff/2026-10-30-clock-anchor-stage0-results.md` (freeze header only in this task)
- Create: `dev/reports/2026-10-30-clock-anchor-stage0.csv`, `.md`, `.json`

**Interfaces:**
- Consumes: the committed script from Task 6.
- Produces: the three report files and a results document whose freeze header was committed before the run.

- [ ] **Step 1: Record the freeze**

Run:
```bash
git rev-parse HEAD
.venv/Scripts/python.exe -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('scripts/clock_anchor_stage0.py').read_bytes()).hexdigest())"
```
Create `docs/handoff/2026-10-30-clock-anchor-stage0-results.md` with exactly this content, substituting the two values printed:

```markdown
# Clock anchor stage 0: frozen rise rule versus end-dry as run

Date: 2026-10-30. Branch `clock-anchor-stage0`. Plan: [2026-10-30-clock-anchor-stage0.md](../superpowers/plans/2026-10-30-clock-anchor-stage0.md). Question: does a frozen rise rule agree across Fitzroy tiles better than the end-dry hydropools uses today?

## Freeze

- Script `scripts/clock_anchor_stage0.py`, SHA-256 `<printed hash>`, committed at `<printed HEAD>` before any real file was read by it.
- `RULE["version"] = "stage0_rise_v1"`; `MARGIN`: within ±1 ≥ 0.90, gain over end-dry ≥ 0.05, big-tile coverage ≥ 0.90, ≥ 500 scored tile-years; only the `primary` variant decides.
- Disclosure: before this rule was written, exploratory rise proxies were computed on the same series (independent verdict §6.1: first departure > 1 pp 0.82, doubling 0.88, half-amplitude 0.93 which coincides with the peak month). This test is pre-specified, not blind. The rule differs from those proxies (band-median level, two-observation confirmation, pulse rejection, interval statuses) and was fixed with its margin before this run.

## Reading rules (written before the run)

- **PASS**: the rise premise survives on this data; stage B (gauge referee) becomes worth its cost if the lead chooses target T2.
- **FAIL with rise within ±1 below end-dry + 0.05**: the proposal's synchrony motivation is falsified on its own data. The thread reduces to the floor on four tiles, departure-size status semantics, handling of `hy_boundary` and `unresolved` cases, and the censoring policy. No HydroSeason contract change is motivated by synchrony.
- **FAIL on coverage alone** (rise synchronous but covers < 0.90): report where the abstentions sit (cloud months, `no_rise` years, four epsilon tiles); a rise anchor would trade coverage for agreement, which is the lead's call under target T2.
- **INCONCLUSIVE**: data problem; fix the loader, do not touch the rule.
- Sensitivity variants are reported, never used to decide. If any variant passes while the primary fails, say so and say that it would be post hoc to adopt it.

## Results

(filled in Task 8)
```

Commit:
```bash
git add docs/handoff/2026-10-30-clock-anchor-stage0-results.md
git commit -m "docs: freeze stage-0 rule hash and reading rules before the real-data run"
```

- [ ] **Step 2: Run on the historical outputs (read-only inputs)**

Run:
```bash
.venv/Scripts/python.exe scripts/clock_anchor_stage0.py --hydroseason-dir D:/RLH/5.6/repos/hydropools/work/rerun/fitzroy/hydroseason --manifest D:/RLH/5.6/repos/hydropools/outputs/rerun/fitzroy/manifest.json --out dev/reports/2026-10-30-clock-anchor-stage0.csv --summary dev/reports/2026-10-30-clock-anchor-stage0.md --receipt dev/reports/2026-10-30-clock-anchor-stage0.json
```
Expected: one line `decision=<PASS|FAIL|INCONCLUSIVE> rows=<n> -> dev/reports/2026-10-30-clock-anchor-stage0.csv`, where `rows` is 5 variants × the number of scored tile-years (41 tiles × up to 38 years, so about 7,790). Runtime under one minute. If it raises, fix the loader against the real column names, rerun the test suite, commit the fix as `fix: stage-0 loader ...`, and record in the results document that the loader (not the rule) changed after the freeze.

- [ ] **Step 3: Sanity-check the receipt against the pinned inputs**

Run:
```bash
.venv/Scripts/python.exe -c "import json; r=json.load(open('dev/reports/2026-10-30-clock-anchor-stage0.json')); print(r['decision'], r['git_head'], len(r['inputs']), r['summary']['n_tiles'], r['summary']['n_big_tiles']); print(r['summary']['end_dry_as_run']); print(r['summary']['variants']['primary']['rise'], r['summary']['variants']['primary']['coverage_big'], r['summary']['variants']['primary']['status_counts'])"
```
Expected: 82 input files, 41 tiles, 31 big tiles; `git_head` equal to the freeze commit from Step 1; end-dry pooled within ±1 close to 0.83 (the verdict measured 0.826 leave-target-out with the same weights and tile set). If the end-dry figure differs from 0.826 by more than 0.02, the eligible-row filter differs from the verdict's; record the difference in the results document rather than adjusting anything.

- [ ] **Step 4: Commit the reports**

```bash
git add dev/reports/2026-10-30-clock-anchor-stage0.csv dev/reports/2026-10-30-clock-anchor-stage0.md dev/reports/2026-10-30-clock-anchor-stage0.json
git commit -m "chore: record stage-0 clock-anchor run on historical Fitzroy outputs"
```

---

### Task 8: Results document

**Files:**
- Modify: `docs/handoff/2026-10-30-clock-anchor-stage0-results.md` (replace the `## Results` placeholder)

**Interfaces:**
- Consumes: `dev/reports/2026-10-30-clock-anchor-stage0.md` and `.json`.
- Produces: the finished results document; the input to the lead's go/no-go on stages A–C.

- [ ] **Step 1: Fill the results section**

Replace `## Results\n\n(filled in Task 8)` with the following, copying every number from `dev/reports/2026-10-30-clock-anchor-stage0.json` (paths given in angle brackets name the JSON keys to copy; do not round beyond three decimals; do not omit a row):

```markdown
## Results

Decision: **<decision>**. Receipt: `dev/reports/2026-10-30-clock-anchor-stage0.json` (`git_head` <summary.git_head>, 82 input files hashed, manifest `<manifest_sha256>`).

| Method | within ±1 (pooled) | within ±1 (mean of years) | ≥ 3 off | scored tile-years | coverage, big tiles |
| --- | ---: | ---: | ---: | ---: | ---: |
| End-dry as run (chain, no re-wet guard) | <end_dry_as_run.pooled_within_1> | <end_dry_as_run.mean_within_1> | <end_dry_as_run.share_ge3> | <end_dry_as_run.n_tile_years> | n/a |
| Rise, primary | <variants.primary.rise.pooled_within_1> | <…mean_within_1> | <…share_ge3> | <…n_tile_years> | <variants.primary.coverage_big> |
| Rise, floor_2pp | … | … | … | … | … |
| Rise, floor_only | … | … | … | … | … |
| Rise, exported_extent | … | … | … | … | … |
| Rise, confirm_1 | … | … | … | … | … |

Primary status counts (all tiles, 1988–2025): <variants.primary.status_counts as "point n, interval n, unconfirmed n, no_rise n, no_observed_months n, no_band_level n, no_window n">. Median interval width <…median_interval_width_months> months; median months from boundary to rise month <…median_months_boundary_to_rise>.

Margin check (primary): within ±1 <value> against 0.90; gain over end-dry <rise − end_dry> against 0.05; coverage <value> against 0.90; scored tile-years <value> against 500.

## Interpretation

<Apply the reading rule that matches the decision, verbatim from the "Reading rules" section above, then add at most five sentences of what the status counts say about where the rule abstained. State which tiles carry most no_band_level / no_observed_months rows by reading the CSV: `.venv/Scripts/python.exe -c "import pandas as pd; t=pd.read_csv('dev/reports/2026-10-30-clock-anchor-stage0.csv'); t=t[t.variant=='primary']; print(t[t.status.isin(['no_band_level','no_observed_months','unconfirmed'])].tile.value_counts().head(8))"`. If any sensitivity variant passes the margin while the primary fails, write one sentence saying so and that adopting it would be post hoc.>

## Limits

- Inputs are the unrepaired hydropools exports: the valid-denominator correction is exact for percentages but restores no pixel counts, so the detectability floor is still machine epsilon on tiles 05, 13, 18 and 46; those tiles fall under `floor_pp_min = 1.0` in every variant except `floor_only`.
- The band level is the median of the exported trough band, which the proposal itself calls the trough estimator. A rise rule that does not depend on the trough band at all was not tested.
- Agreement with a pixel-weighted median of other tiles is a synchrony measurement, not a timing accuracy measurement. Stage B is the only place accuracy against an independent referee is assessed.
- Rows for 2025 use the 2026 cycle row as the following cycle; HydroSeason inputs end 2026-06, so those windows can be truncated and are more likely `unconfirmed`.
- The end-dry comparator omits the re-wet guard, which moved 8 of 1,544 windows.

## What this does not decide

The target (T1/T2/T3), the censoring policy, the donor policy and whether hydropools honours HydroSeason's gates remain the lead's decisions in [2026-10-30-clock-anchor-target-decision.md](2026-10-30-clock-anchor-target-decision.md). Stage A (input repair attribution) is motivated independently of this result and is the next step whatever the decision here.
```

- [ ] **Step 2: Check the document renders and commit**

Run: `.venv/Scripts/python.exe -m mkdocs build --strict 2>&1 | tail -3` (expected: build completes; an advisory about MkDocs 2.0 is acceptable, errors are not).

```bash
git add docs/handoff/2026-10-30-clock-anchor-stage0-results.md
git commit -m "docs: record stage-0 clock-anchor results and interpretation"
```

- [ ] **Step 3: Final state**

Run: `git log --oneline development..clock-anchor-stage0` — expected eight commits (Tasks 1–8, plus any loader fix). Run `git status --short` — expected only the pre-existing untracked files (`RELEASE_PLAN_0.2.1.md`, the three `docs/provisional-trough-*.md`). Do not merge or push; the lead reads the results document and decides on stages A–C.
