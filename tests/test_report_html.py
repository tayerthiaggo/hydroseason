import pandas as pd

from hydroseason._report_html import _year_cards


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
