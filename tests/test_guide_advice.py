"""The guide's advice on dates, counts, process pools and gates stays tied to the code."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS

GUIDE = Path("docs/guide.md")
EXAMPLE = Path("docs/examples/fitzroy-river-wa/fitzroy-river-wa_hydro_years.csv")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_guide_explains_dates_counts_and_process_pools():
    guide = GUIDE.read_text(encoding="utf-8")
    dates = " ".join(_section(guide, "## Dates around the dry-season low").split())
    assert "the cycle boundary that the trough method places at the end of the dry-season low" in dates
    assert "always `trough_boundary_date` plus one month" in dates
    assert "gauge" not in dates.lower()

    csv = _section(guide, "### 1. From a CSV you already have")
    assert "`extent_pct = 100 * n_water / n_valid`" in csv
    assert "Pass counts whenever you have them." in csv

    batch = _section(guide, "### Batch memory and threads")
    for variable in ("OMP_NUM_THREADS=1", "OPENBLAS_NUM_THREADS=1", "MKL_NUM_THREADS=1"):
        assert variable in batch


def test_start_date_is_the_month_after_the_previous_boundary():
    years = pd.read_csv(EXAMPLE, parse_dates=["start_date", "trough_boundary_date"])
    following_start = years["start_date"].shift(-1)
    expected = years["trough_boundary_date"] + pd.offsets.MonthBegin(1)
    anchored = following_start.notna() & expected.notna()
    assert anchored.sum() >= 20
    assert (following_start[anchored] == expected[anchored]).all()


def test_docs_state_the_default_gates_and_what_they_were_checked_on():
    text = " ".join(Path("docs/hydrological-state.md").read_text(encoding="utf-8").split())
    ratio = TIMING_IDENTIFIABILITY_DEFAULTS.min_amplitude_to_floor_ratio
    pixels = TIMING_IDENTIFIABILITY_DEFAULTS.min_peak_water_pixels
    assert f"at least {ratio:.1f} times its floor" in text
    assert f"at least {pixels} water pixels" in text
    assert "less accurate in a known-truth test (G2), so the defaults stay" in text
    assert "They are tested values, not values fitted to lowland channels, floodplains or wetlands." in text
    assert "calibrated detectability floor" not in text


def test_docs_do_not_promise_an_exact_month_for_point_timing():
    for path in ("docs/report-columns.md", "docs/hydrological-state.md", "docs/guide.md"):
        text = " ".join(Path(path).read_text(encoding="utf-8").split())
        assert "resolves to an exact month" not in text, path
    columns = " ".join(Path("docs/report-columns.md").read_text(encoding="utf-8").split())
    assert "not how close the reported month is to the true one" in columns
    assert "`broad` (troughs only)" in columns
    state = " ".join(Path("docs/hydrological-state.md").read_text(encoding="utf-8").split())
    assert "(`unresolved` < `broad` < `interval` < `point`)" in state
    guide = GUIDE.read_text(encoding="utf-8")
    dates = " ".join(_section(guide, "## Dates around the dry-season low").split())
    assert "the low is distinct, but the month is not necessarily exact" in dates
    assert "between 1 in 3 and just over 4 in 10 `point` troughs were more than a month from the true month" in dates
    assert "Three November 2026 known-truth tests (G2, L1 and L2, each on fresh records)" in dates
    assert "A `point` trough was not right more often than an `interval` one" in dates


def test_docs_say_the_trough_label_only_looks_back_to_the_peak():
    """The trough window ends at the boundary (trough_search="post_peak"), so later months are never compared."""
    import inspect

    from hydroseason import _dynamic_year

    assert 'trough_search="post_peak"' in inspect.getsource(_dynamic_year._cycle_timing_evidence)
    for path in ("docs/report-columns.md", "docs/hydrological-state.md"):
        text = " ".join(Path(path).read_text(encoding="utf-8").split())
        assert "months after the boundary are not" in text, path
    guide = GUIDE.read_text(encoding="utf-8")
    dates = " ".join(_section(guide, "## Dates around the dry-season low").split())
    assert "The months after the trough are not compared." in dates
