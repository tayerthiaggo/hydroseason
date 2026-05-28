"""HydroSeason.report — notebook summary cards and HTML report export.

Two public functions:

* :func:`display_summary` — returns an ``IPython.display.HTML`` summary card
  suitable for inline notebook display.  Shows regime badge, key diagnostics,
  and any validation warnings.

* :func:`generate_html_report` — writes a self-contained ``.html`` file with
  all five interactive Plotly charts, a styled diagnostics summary, and a
    per-hydro-year metrics table.  The Plotly JS bundle is embedded so
  the file can be shared and opened in any modern browser without Python.
"""

from __future__ import annotations

import calendar
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import at runtime
    from .pipeline import PipelineArtifacts


# ---------------------------------------------------------------------------
# Colour helpers (shared with plot.py but kept local to avoid import overhead)
# ---------------------------------------------------------------------------
_REGIME_BADGE_STYLE: dict[str, str] = {
    "seasonal": "background:#C8E6C9;color:#1B5E20",
    "borderline": "background:#FFF9C4;color:#F57F17",
    "non_seasonal": "background:#FFCDD2;color:#B71C1C",
}
_DEFAULT_BADGE_STYLE = "background:#ECEFF1;color:#37474F"

_MONTH_ABBR = {i: calendar.month_abbr[i] for i in range(1, 13)}


def _regime_badge(regime: str) -> str:
    style = _REGIME_BADGE_STYLE.get(regime, _DEFAULT_BADGE_STYLE)
    label = regime.replace("_", " ").title()
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:4px;'
        f'font-weight:bold;font-size:13px;{style}">{label}</span>'
    )


def _stat_pill(label: str, value: str) -> str:
    return (
        f'<span style="display:inline-block;margin:3px 6px 3px 0;padding:4px 10px;'
        f'border-radius:4px;background:#ECEFF1;font-size:12px;">'
        f'<b>{label}:</b> {value}</span>'
    )


# ---------------------------------------------------------------------------
# Public: in-notebook summary card
# ---------------------------------------------------------------------------
def display_summary(artifacts: "PipelineArtifacts"):
    """Return an ``IPython.display.HTML`` summary card for inline notebook display.

    The card shows:
    - A coloured regime badge (green / amber / red)
    - Key diagnostics: Walsh-Lawler SI, STL F_S, hydro-year start month,
      date range, record count, imputed rows
    - Any validation warnings
    """
    from IPython.display import HTML

    d = artifacts.diagnostics
    result = artifacts.result

    # Date range
    try:
        dates = artifacts.result["Date"]
        date_min = str(dates.min())[:7]
        date_max = str(dates.max())[:7]
        date_range = f"{date_min} → {date_max}"
    except Exception:
        date_range = "N/A"

    start_month = (
        _MONTH_ABBR.get(d.hydro_year_start_month, str(d.hydro_year_start_month))
        if d.hydro_year_start_month
        else "N/A"
    )

    pills = [
        _stat_pill("Walsh-Lawler SI", f"{d.walsh_lawler_si:.3f}"),
        _stat_pill("STL F<sub>S</sub>", f"{d.stl_strength:.3f}"),
        _stat_pill("Hydro year start", start_month),
        _stat_pill("Date range", date_range),
        _stat_pill("Records", str(d.n_rows_after_validation)),
        _stat_pill("Imputed", str(d.n_imputed)),
    ]

    warnings_html = ""
    if d.validation_warnings:
        items = "".join(f"<li>{w}</li>" for w in d.validation_warnings)
        warnings_html = (
            f'<div style="margin-top:8px;padding:6px 10px;background:#FFF3E0;'
            f'border-left:3px solid #FF9800;border-radius:3px;font-size:11px;">'
            f'<b>Validation warnings:</b><ul style="margin:4px 0 0 16px;">{items}</ul></div>'
        )

    regime_source_note = (
        f'<span style="font-size:11px;color:#757575;margin-left:8px;">'
        f'(via {d.regime_source})</span>'
        if d.regime_source
        else ""
    )

    html = (
        '<div style="font-family:sans-serif;border:1px solid #CFD8DC;border-radius:6px;'
        'padding:14px 18px;max-width:720px;background:#FAFAFA;">'
        '<div style="font-size:16px;font-weight:bold;margin-bottom:10px;">'
        "HydroSeason — Analysis Summary"
        "</div>"
        '<div style="margin-bottom:10px;">'
        + _regime_badge(d.regime)
        + regime_source_note
        + "</div>"
        '<div style="line-height:2.2;">'
        + "".join(pills)
        + "</div>"
        + warnings_html
        + "</div>"
    )
    return HTML(html)


# ---------------------------------------------------------------------------
# Internal: styled per-hydro-year metrics table (HTML)
# ---------------------------------------------------------------------------
def _metrics_table_html(result, value_col: str = "Rainfall_mm") -> str:
    """Build a styled HTML table of per-hydro-year season metrics."""
    wet_col = "wet_total" if "wet_total" in result.columns else "Rain_wet_season_mm"
    dry_col = "dry_total" if "dry_total" in result.columns else "Rain_dry_season_mm"

    cols_wanted = ["Hydro_Year", wet_col, dry_col, "wet_month_count", "dry_month_count"]
    if "dry_event_count" in result.columns:
        cols_wanted.append("dry_event_count")

    available = [c for c in cols_wanted if c in result.columns]
    annual = (
        result[available]
        .drop_duplicates(subset=["Hydro_Year"])
        .sort_values("Hydro_Year")
        .reset_index(drop=True)
    )

    header_labels = {
        "Hydro_Year": "Hydro Year",
        wet_col: f"Wet total ({value_col})",
        dry_col: f"Dry total ({value_col})",
        "wet_month_count": "Wet months",
        "dry_month_count": "Dry months",
        "dry_event_count": "Rainy dry months",
    }

    th_style = (
        "padding:7px 12px;text-align:left;background:#1565C0;color:white;"
        "font-size:12px;white-space:nowrap;"
    )
    td_style = "padding:6px 12px;font-size:12px;border-bottom:1px solid #ECEFF1;"

    headers = "".join(f'<th style="{th_style}">{header_labels.get(c, c)}</th>' for c in available)
    rows_html = ""
    for i, (_, row) in enumerate(annual.iterrows()):
        bg = "#FAFAFA" if i % 2 == 0 else "white"
        cells = ""
        for c in available:
            val = row[c]
            if c == "Hydro_Year":
                display_val = str(int(val))
            elif c in (wet_col, dry_col):
                display_val = f"{float(val):.1f}"
            else:
                display_val = str(int(val))
            cells += f'<td style="{td_style}background:{bg};">{display_val}</td>'
        rows_html += f"<tr>{cells}</tr>"

    return (
        '<table style="border-collapse:collapse;width:100%;font-family:sans-serif;">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
    )


# ---------------------------------------------------------------------------
# Public: full HTML report
# ---------------------------------------------------------------------------
def generate_html_report(
    artifacts: "PipelineArtifacts",
    output_path: str | Path = "hydroseason_report.html",
    *,
    title: str = "HydroSeason Report",
    value_col: str = "Rainfall_mm",
) -> Path:
    """Write a self-contained interactive HTML report and return its path.

    The report includes:
    1. Header / summary card (regime badge + key diagnostics)
    2. Season timeline (interactive Plotly)
    3. Monthly climatology (interactive Plotly)
    4. Annual wet/dry totals (interactive Plotly)
    5. STL decomposition (interactive Plotly)
    6. Diagnostics table (interactive Plotly)
    7. Per-hydro-year metrics table (styled HTML)

    Plotly JS is embedded in the file, so no internet connection or Python
    environment is needed to view the report after it is created.
    """
    from .plot import (
        plot_annual_metrics,
        plot_diagnostics_table,
        plot_monthly_climatology,
        plot_season_timeline,
        plot_stl_decomposition,
    )

    output_path = Path(output_path)
    d = artifacts.diagnostics

    # Build each figure as an HTML div (full_html=False, include_plotlyjs only once)
    fig_timeline = plot_season_timeline(artifacts.result, value_col=value_col, height=450)
    fig_clim = plot_monthly_climatology(artifacts.result, artifacts.fixed_monthly, value_col=value_col, height=420)
    fig_annual = plot_annual_metrics(artifacts.result, height=480)
    fig_stl = plot_stl_decomposition(artifacts.result, value_col=value_col, height=680)
    fig_diag = plot_diagnostics_table(d, height=480)

    # First figure gets the full Plotly JS bundle embedded once.
    html_timeline = fig_timeline.to_html(full_html=False, include_plotlyjs=True)
    html_clim = fig_clim.to_html(full_html=False, include_plotlyjs=False)
    html_annual = fig_annual.to_html(full_html=False, include_plotlyjs=False)
    html_stl = fig_stl.to_html(full_html=False, include_plotlyjs=False)
    html_diag = fig_diag.to_html(full_html=False, include_plotlyjs=False)

    # Summary card
    start_month_name = (
        _MONTH_ABBR.get(d.hydro_year_start_month, str(d.hydro_year_start_month))
        if d.hydro_year_start_month
        else "N/A"
    )
    badge_style = _REGIME_BADGE_STYLE.get(d.regime, _DEFAULT_BADGE_STYLE)
    regime_label = d.regime.replace("_", " ").title()

    try:
        dates = artifacts.result["Date"]
        date_range = f"{str(dates.min())[:7]} → {str(dates.max())[:7]}"
    except Exception:
        date_range = "N/A"

    warnings_html = ""
    if d.validation_warnings:
        items = "".join(f"<li>{w}</li>" for w in d.validation_warnings)
        warnings_html = (
            f'<div style="margin:8px 0;padding:8px 14px;background:#FFF3E0;'
            f'border-left:4px solid #FF9800;border-radius:3px;">'
            f"<b>Validation warnings:</b><ul>{items}</ul></div>"
        )

    metrics_table = _metrics_table_html(artifacts.result, value_col=value_col)

    def _section(heading: str, content: str) -> str:
        return (
            f'<section style="margin-bottom:40px;">'
            f'<h2 style="font-family:sans-serif;font-size:18px;color:#1565C0;'
            f'border-bottom:2px solid #BBDEFB;padding-bottom:6px;">{heading}</h2>'
            f"{content}"
            f"</section>"
        )

    body = f"""
    <header style="margin-bottom:32px;">
      <h1 style="font-family:sans-serif;font-size:26px;color:#0D47A1;margin-bottom:6px;">{title}</h1>
      <div style="font-family:sans-serif;display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:10px;">
        <span style="padding:4px 14px;border-radius:4px;font-weight:bold;font-size:14px;{badge_style}">{regime_label}</span>
        <span style="font-size:13px;color:#546E7A;">via {d.regime_source}</span>
      </div>
      <div style="font-family:sans-serif;font-size:13px;color:#37474F;line-height:2;">
        <b>Walsh-Lawler SI:</b> {d.walsh_lawler_si:.3f} &nbsp;|&nbsp;
        <b>STL F<sub>S</sub>:</b> {d.stl_strength:.3f} &nbsp;|&nbsp;
        <b>Hydro year start:</b> {start_month_name} &nbsp;|&nbsp;
        <b>Date range:</b> {date_range} &nbsp;|&nbsp;
        <b>Records:</b> {d.n_rows_after_validation} &nbsp;|&nbsp;
        <b>Imputed:</b> {d.n_imputed}
      </div>
      {warnings_html}
    </header>
    """ + _section("Season Timeline", html_timeline) \
      + _section("Monthly Climatology", html_clim) \
      + _section("Annual Wet / Dry Totals", html_annual) \
      + _section("STL Decomposition", html_stl) \
      + _section("Algorithm Diagnostics", html_diag) \
      + _section("Per-Hydro-Year Metrics", metrics_table)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      font-family: sans-serif;
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 24px;
      background: #FAFAFA;
      color: #212121;
    }}
    section {{ background: white; padding: 20px 24px; border-radius: 6px;
               box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    h2 {{ margin-top: 0; }}
    ul {{ margin: 4px 0; padding-left: 20px; }}
    table {{ margin-top: 8px; }}
  </style>
</head>
<body>
{body}
<footer style="margin-top:40px;font-size:11px;color:#9E9E9E;text-align:center;">
  Generated by HydroSeason
</footer>
</body>
</html>"""

    output_path.write_text(html_doc, encoding="utf-8")
    return output_path
