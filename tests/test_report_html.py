import pandas as pd

from hydroseason._report_html import _year_cards, render_report_html


def _monthly(start="2005-01-01", periods=24):
    index = pd.date_range(start, periods=periods, freq="MS")
    return pd.DataFrame(
        {
            "date": index,
            "extent_pct": 1.0,
            "invalid_pct": 0.0,
            "phase": "wet",
        }
    )


def test_report_places_optional_aoi_map_after_the_summary_region():
    """Removing the AOI context section would hide a supplied report map."""
    html = render_report_html(
        name="Test AOI",
        title="Test AOI",
        subtitle=None,
        quality_note=None,
        verdict="Seasonal",
        kpis=[{"value": "1", "label": "KPI", "detail": "detail"}],
        monthly=pd.DataFrame(),
        hydro_years=pd.DataFrame(),
        events=pd.DataFrame(),
        low_spells=pd.DataFrame(),
        summary=pd.DataFrame(),
        timeline_figure={"data": [], "layout": {}, "config": {}},
        secondary_figure={"data": [], "layout": {}, "config": {}},
        aoi_map_html='<div id="aoi-map-report">AOI map</div>',
    )

    assert '<section id="aoi-context">' in html
    assert html.index('class="kpis"') < html.index('id="aoi-context"')
    assert html.index('id="aoi-context"') < html.index('id="timeline"')
    assert 'id="aoi-map-report"' in html


def test_report_omits_aoi_context_section_without_a_map():
    """An absent AOI context must not leave an empty report section behind."""
    html = render_report_html(
        name="Test AOI",
        title="Test AOI",
        subtitle=None,
        quality_note=None,
        verdict="Seasonal",
        kpis=[],
        monthly=pd.DataFrame(),
        hydro_years=pd.DataFrame(),
        events=pd.DataFrame(),
        low_spells=pd.DataFrame(),
        summary=pd.DataFrame(),
        timeline_figure={"data": [], "layout": {}, "config": {}},
        secondary_figure={"data": [], "layout": {}, "config": {}},
    )

    assert 'id="aoi-context"' not in html


def test_year_cards_render_one_card_per_hydrological_year():
    monthly = _monthly()
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2006,
                "hy_start": pd.Timestamp("2005-11-01"),
                "hy_end": pd.Timestamp("2006-10-01"),
                "peak_month": pd.Timestamp("2006-01-01"),
                "trough_month": pd.Timestamp("2006-10-01"),
                "cycle_months": 12.0,
                "drawdown_pct": 0.68,
                "confidence": "medium",
                "status": "partial",
                "status_reason": "peak_low_quality",
            }
        ]
    )

    html = _year_cards(monthly, hydro_years)

    assert html.count("<details class=") == 1
    assert "HY 2006" in html


def test_year_cards_report_years_without_resolved_boundaries():
    """A year with no start/end must still appear, not vanish silently.

    Dropping it makes the rendered card count disagree with the
    hydrological-year total reported in the summary cards.
    """
    monthly = _monthly()
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2006,
                "hy_start": pd.Timestamp("2005-11-01"),
                "hy_end": pd.Timestamp("2006-10-01"),
                "peak_month": pd.Timestamp("2006-01-01"),
                "trough_month": pd.Timestamp("2006-10-01"),
                "cycle_months": 12.0,
                "drawdown_pct": 0.68,
                "confidence": "medium",
                "status": "complete",
                "status_reason": "ok",
            },
            {
                "hy_year": 2005,
                "hy_start": pd.NaT,
                "hy_end": pd.NaT,
                "peak_month": pd.NaT,
                "trough_month": pd.Timestamp("2005-10-01"),
                "trough_extent_pct": 0.024872,
                "cycle_months": float("nan"),
                "drawdown_pct": float("nan"),
                "confidence": "low",
                "status": "partial",
                "status_reason": "no_previous_boundary",
            },
        ]
    )

    html = _year_cards(monthly, hydro_years)

    assert html.count("<details class=") == 2
    assert "HY 2005" in html
    assert "Cycle boundaries not resolved" in html
    assert "No preceding hydrological-year boundary" in html
    # The observed trough is still worth showing even without a full cycle.
    assert "0.02%" in html


def test_year_cards_unbounded_year_reports_unmapped_reason_verbatim():
    monthly = _monthly()
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2005,
                "hy_start": pd.NaT,
                "hy_end": pd.NaT,
                "confidence": "low",
                "status": "partial",
                "status_reason": "some_new_reason",
            }
        ]
    )

    html = _year_cards(monthly, hydro_years)

    assert "Some new reason" in html


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


def test_year_cards_explain_insufficient_cycle_coverage_on_bounded_card():
    """A too-short opening cycle (e.g. only 3 months of data before the first
    trough) now gets non-null hy_start/hy_end, so it takes the bounded-card
    path instead of _unbounded_year_card. It must not silently lose its
    explanatory text just because it has real dates -- the card shows a LOW
    confidence badge and N/A metrics, and a manager needs to know why.
    """
    monthly = _monthly()
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2005,
                "hy_start": pd.Timestamp("2005-08-01"),
                "hy_end": pd.Timestamp("2005-10-01"),
                "peak_month": pd.NaT,
                "trough_month": pd.Timestamp("2005-10-01"),
                "cycle_months": float("nan"),
                "drawdown_pct": float("nan"),
                "confidence": "low",
                "status": "partial",
                "status_reason": "insufficient_cycle_coverage",
            }
        ]
    )

    html = _year_cards(monthly, hydro_years)

    assert html.count("<details class=") == 1
    assert "HY 2005" in html
    assert "year-card-unbounded" not in html
    assert "enough usable months" in html.lower()


def test_year_cards_render_confidence_title_in_note_and_drawdown_stat():
    monthly = _monthly()
    hydro_years = pd.DataFrame(
        [
            {
                "hy_year": 2025,
                "hy_start": pd.Timestamp("2024-10-01"),
                "hy_end": pd.Timestamp("2025-12-01"),
                "peak_month": pd.Timestamp("2025-02-01"),
                "trough_month": pd.Timestamp("2025-12-01"),
                "cycle_months": 15.0,
                "drawdown_pct": 0.32559,
                "amplitude_pct": 0.45,
                "annual_condition": "typical_or_mixed",
                "confidence": "medium",
                "status": "partial",
                "status_reason": "boundary_provisional",
            }
        ]
    )

    html = _year_cards(monthly, hydro_years)

    assert "Condition: <strong>Typical / Mixed</strong>" in html
    assert "Medium confidence: Boundary is provisional and was not confirmed." in html
    assert "Cycle: <strong>15.0 mos</strong>" in html
    assert "Amplitude: <strong>0.45%</strong>" in html
    assert "Drawdown" not in html
    assert "MEDIUM CONFIDENCE" in html

