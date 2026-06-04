"""HydroSeason.report - notebook summary cards and HTML report export.

Two public functions:

* :func:`display_summary` - returns an HTML summary card suitable for inline
  notebook display.  Shows regime badge, key diagnostics, and any validation
  warnings.

* :func:`generate_html_report` - writes a self-contained ``.html`` file with
  all six interactive Plotly charts, a styled diagnostics summary, and a
    per-hydro-year metrics table.  The Plotly JS bundle is embedded so
  the file can be shared and opened in any modern browser without Python.
"""

from __future__ import annotations

import calendar
from pathlib import Path
from typing import TYPE_CHECKING

from .plot import PLOTLY_CONFIG

if TYPE_CHECKING:  # avoid circular import at runtime
    from .pipeline import PipelineArtifacts


class HTMLSummary:
    """Small fallback HTML wrapper for environments without IPython."""

    def __init__(self, data: str):
        self.data = data

    def _repr_html_(self) -> str:
        return self.data


def _as_html_summary(html: str):
    try:
        from IPython.display import HTML
    except ImportError:
        return HTMLSummary(html)
    return HTML(html)


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
    """Return an HTML summary card for inline notebook display when available.

    The card shows:
    - A coloured regime badge (green / amber / red)
    - Key diagnostics: Walsh-Lawler SI, STL F_S, hydro-year start month,
      date range, record count, imputed rows
    - Any validation warnings
    """
    d = artifacts.diagnostics
    result = artifacts.result

    # Date range
    try:
        dates = artifacts.result["Date"]
        date_min = str(dates.min())[:7]
        date_max = str(dates.max())[:7]
        date_range = f"{date_min} to {date_max}"
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
        _stat_pill("Date range", date_range),
        _stat_pill("Records", str(d.n_rows_after_validation)),
        _stat_pill("Imputed", str(d.n_imputed)),
        _stat_pill("Data confidence", d.data_confidence.title()),
    ]

    warnings_html = ""
    if d.validation_warnings:
        items = "".join(f"<li>{w}</li>" for w in d.validation_warnings)
        warnings_html = (
            f'<div style="margin-top:8px;padding:6px 10px;background:#FFF3E0;'
            f'border-left:3px solid #FF9800;border-radius:3px;font-size:11px;color:#212121;">'
            f'<b>Validation warnings:</b><ul style="margin:4px 0 0 16px;">{items}</ul></div>'
        )

    regime_source_note = (
        f'<span style="font-size:11px;color:#212121;margin-left:8px;">'
        f'(via {d.regime_source})</span>'
        if d.regime_source
        else ""
    )

    # Bullet-point analysis summary (Tayer 2026 style)
    bullets = [
        ("Regime", f"{d.regime} (via {d.regime_source})"),
        ("Walsh-Lawler SI", f"{d.walsh_lawler_si:.3f}"),
        ("STL strength (F_S)", f"{d.stl_strength:.3f}"),
        ("Hydrological year start", start_month),
        ("Date range", date_range),
        ("Records (validated)", str(d.n_rows_after_validation)),
        ("Imputed rows", str(d.n_imputed)),
        ("Max consecutive missing", str(d.max_consecutive_missing)),
        ("Data confidence", d.data_confidence),
    ]
    try:
        n_years = int(result["Hydro_Year"].nunique())
        bullets.append(("Hydrological years covered", str(n_years)))
    except Exception:
        pass
    if "Year_Class_SPI" in result.columns:
        ycs = (
            result[["Hydro_Year", "Year_Class_SPI"]]
            .drop_duplicates(subset=["Hydro_Year"])
        )
        cnt = ycs["Year_Class_SPI"].value_counts().to_dict()
        bullets.append(
            (
                "Year class (SPI +/-1)",
                f"{cnt.get('Wet', 0)} Wet | {cnt.get('Regular', 0)} Regular | {cnt.get('Dry', 0)} Dry",
            )
        )
    if "Drought_Category" in result.columns:
        dc = (
            result[["Hydro_Year", "Drought_Category"]]
            .drop_duplicates(subset=["Hydro_Year"])
        )
        cnt = dc["Drought_Category"].value_counts().to_dict()
        bullets.append(
            (
                "Drought category",
                f"{cnt.get('Prolonged', 0)} Prolonged | {cnt.get('Regular', 0)} Regular | "
                f"{cnt.get('Minimal', 0)} Minimal | {cnt.get('No dry', 0)} No-dry",
            )
        )

    bullets_html = "".join(
        f'<li style="margin:2px 0;"><b>{lbl}:</b> {val}</li>'
        for lbl, val in bullets
    )

    html = (
        '<div style="font-family:sans-serif;border:1px solid #CFD8DC;border-radius:6px;'
        'padding:14px 18px;max-width:720px;background:#FAFAFA;color:#212121;">'
        '<div style="font-size:16px;font-weight:bold;margin-bottom:10px;color:#212121;">'
        "HydroSeason - Analysis Summary"
        "</div>"
        '<div style="margin-bottom:10px;">'
        + _regime_badge(d.regime)
        + regime_source_note
        + "</div>"
        '<ul style="margin:6px 0 6px 18px;padding:0;font-size:12px;line-height:1.6;">'
        + bullets_html
        + "</ul>"
        + warnings_html
        + "</div>"
    )
    return _as_html_summary(html)


# ---------------------------------------------------------------------------
# Internal: styled per-hydro-year metrics table (HTML)
# ---------------------------------------------------------------------------
def _metrics_table_html(result, value_col: str = "Rainfall_mm") -> str:
    """Build a styled HTML table of per-hydro-year season metrics."""
    wet_col = "wet_total" if "wet_total" in result.columns else "Rain_wet_season_mm"
    dry_col = "dry_total" if "dry_total" in result.columns else "Rain_dry_season_mm"

    cols_wanted = [
        "Hydro_Year", wet_col, dry_col,
        "wet_month_count", "dry_month_count",
    ]
    if "dry_event_count" in result.columns:
        cols_wanted.append("dry_event_count")
    for extra in ("Annual_SPI", "Year_Class_SPI", "Drought_Category"):
        if extra in result.columns:
            cols_wanted.append(extra)

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
        "Annual_SPI": "Annual SPI",
        "Year_Class_SPI": "Year class (SPI)",
        "Drought_Category": "Drought category",
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
            elif c == "Annual_SPI":
                display_val = f"{float(val):+.2f}"
            elif c in ("Year_Class_SPI", "Drought_Category"):
                display_val = str(val)
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


def _imputed_runs_table_html(result) -> str:
    """Build a styled HTML table of contiguous imputed date ranges."""
    if "Imputed" not in result.columns or not result["Imputed"].fillna(False).any():
        return (
            '<div style="font-family:sans-serif;font-size:12px;color:#546E7A;">'
            "No imputed runs found in this result."
            "</div>"
        )

    work = result.copy()
    work["Date"] = work["Date"].astype("datetime64[ns]")
    work["Imputed"] = work["Imputed"].fillna(False).astype(bool)
    work = work.sort_values("Date").reset_index(drop=True)

    is_imputed = work["Imputed"]
    groups = (is_imputed != is_imputed.shift()).cumsum()
    imputed_rows = work[is_imputed].copy()
    imputed_rows["_grp"] = groups[is_imputed].values

    runs = (
        imputed_rows.groupby("_grp", as_index=False)
        .agg(start=("Date", "min"), end=("Date", "max"), months=("Date", "size"))
        .sort_values("start")
    )
    runs.insert(0, "run", range(1, len(runs) + 1))

    th_style = (
        "padding:7px 12px;text-align:left;background:#1565C0;color:white;"
        "font-size:12px;white-space:nowrap;"
    )
    td_style = "padding:6px 12px;font-size:12px;border-bottom:1px solid #ECEFF1;"

    headers = "".join(
        f'<th style="{th_style}">{h}</th>'
        for h in ["Run", "Start", "End", "Length (months)"]
    )

    rows_html = ""
    for i, (_, row) in enumerate(runs.iterrows()):
        bg = "#FAFAFA" if i % 2 == 0 else "white"
        rows_html += (
            "<tr>"
            f'<td style="{td_style}background:{bg};">{int(row["run"])}</td>'
            f'<td style="{td_style}background:{bg};">{row["start"]:%Y-%m}</td>'
            f'<td style="{td_style}background:{bg};">{row["end"]:%Y-%m}</td>'
            f'<td style="{td_style}background:{bg};">{int(row["months"])}</td>'
            "</tr>"
        )

    return (
        '<table style="border-collapse:collapse;width:100%;font-family:sans-serif;">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
    )


def _imputed_runs_note_html(diagnostics) -> str:
    """Build a plain-language note to help interpret imputation confidence."""
    confidence = str(getattr(diagnostics, "data_confidence", "unknown")).lower()
    n_imputed = int(getattr(diagnostics, "n_imputed", 0) or 0)
    max_gap = int(getattr(diagnostics, "max_consecutive_missing", 0) or 0)

    if n_imputed == 0:
        msg = (
            "No missing months were gap-filled in this run. Confidence in the "
            "season labels is higher because all months come from observed data."
        )
    elif confidence == "high":
        msg = (
            "Only a small amount of rainfall was gap-filled. Confidence is high, "
            "but still review the listed periods where values were imputed."
        )
    elif confidence == "medium":
        msg = (
            "Some rainfall values were gap-filled. Treat season boundaries around "
            "these periods with moderate caution."
        )
    else:
        msg = (
            "A substantial amount of rainfall was gap-filled, including long gaps. "
            "Interpret season boundaries near these periods with low confidence."
        )

    return (
        '<div style="font-family:sans-serif;font-size:12px;color:#37474F;'
        'background:#FFF8E1;border-left:4px solid #F9A825;border-radius:3px;'
        'padding:8px 12px;margin-bottom:10px;line-height:1.5;">'
        f"<b>Confidence note:</b> {msg} "
        f"<span style='color:#607D8B'>(imputed months: {n_imputed}, longest missing run: {max_gap} months)</span>"
        "</div>"
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
    3. Imputation and data quality (interactive Plotly)
    4. Imputed runs table (styled HTML)
    5. Aggregated monthly rainfall (interactive Plotly)
    6. Annual wet/dry totals (interactive Plotly)
    7. STL decomposition (interactive Plotly)
    8. Per-hydro-year metrics table (styled HTML)
    9. Diagnostics table (interactive Plotly)

    Plotly JS is embedded in the file, so no internet connection or Python
    environment is needed to view the report after it is created.
    """
    from .plot import (
        plot_agg_monthly_rainfall,
        plot_annual_metrics,
        plot_imputation_overview,
        plot_diagnostics_table,
        plot_season_timeline,
        plot_stl_decomposition,
    )

    output_path = Path(output_path)
    d = artifacts.diagnostics

    # Build each figure as an HTML div (full_html=False, include_plotlyjs only once)
    fig_timeline = plot_season_timeline(artifacts.result, value_col=value_col, height=450)
    fig_quality = plot_imputation_overview(artifacts.result, value_col=value_col, title="", height=320)
    fig_clim = plot_agg_monthly_rainfall(artifacts.result, artifacts.fixed_monthly, value_col=value_col, height=420)
    fig_annual = plot_annual_metrics(artifacts.result, height=480)
    fig_stl = plot_stl_decomposition(artifacts.result, value_col=value_col, title="", height=680)
    fig_diag = plot_diagnostics_table(d, title="", height=560)

    # First figure gets the full Plotly JS bundle embedded once.
    html_timeline = fig_timeline.to_html(full_html=False, include_plotlyjs=True, config=PLOTLY_CONFIG)
    html_quality = fig_quality.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_clim = fig_clim.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_annual = fig_annual.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_stl = fig_stl.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_diag = fig_diag.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)

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
        date_range = f"{str(dates.min())[:7]} to {str(dates.max())[:7]}"
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
    imputed_runs_note = _imputed_runs_note_html(d)
    imputed_runs_table = _imputed_runs_table_html(artifacts.result)

    def _section(heading: str, content: str) -> str:
        return (
            f'<section style="margin-bottom:40px;">'
            f'<h2 style="font-family:sans-serif;font-size:18px;color:#1565C0;'
            f'border-bottom:2px solid #BBDEFB;padding-bottom:6px;">{heading}</h2>'
            f"{content}"
            f"</section>"
        )

    def _section_chart(heading: str, html_content: str, initial_height: int = 450) -> str:
        """Section wrapper with a vertically-resizable chart container."""
        return (
            f'<section style="margin-bottom:40px;">'
            f'<h2 style="font-family:sans-serif;font-size:18px;color:#1565C0;'
            f'border-bottom:2px solid #BBDEFB;padding-bottom:6px;">{heading}</h2>'
            f'<p style="font-size:10px;color:#90A4AE;text-align:right;margin:0 0 3px;">'
            f'drag bottom edge to resize</p>'
            f'<div class="chart-container" style="height:{initial_height}px;">'
            f'{html_content}'
            f'</div>'
            f'</section>'
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
                <b>Imputed:</b> {d.n_imputed} &nbsp;|&nbsp;
                <b>Confidence:</b> {d.data_confidence}
      </div>
      {warnings_html}
    </header>
    """ + _section_chart("Season Timeline", html_timeline, 450) \
            + _section_chart("Imputation and Data Quality", html_quality, 320) \
        + _section("Imputed Runs", imputed_runs_note + imputed_runs_table) \
      + _section_chart("Aggregated Monthly Rainfall", html_clim, 420) \
      + _section_chart("Annual Wet / Dry Totals", html_annual, 480) \
      + _section_chart("STL Decomposition", html_stl, 680) \
      + _section("Per-Hydro-Year Metrics", metrics_table) \
      + _section_chart("Algorithm Diagnostics", html_diag, 480)

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
    .chart-container {{
      resize: vertical;
      overflow: hidden;
      margin-bottom: 4px;
      min-height: 200px;
    }}
  </style>
</head>
<body>
{body}
<footer style="margin-top:40px;font-size:11px;color:#9E9E9E;text-align:center;">
  Generated by HydroSeason
</footer>
<script>
(function () {{
  function init() {{
    document.querySelectorAll('.chart-container').forEach(function (c) {{
      var d = c.querySelector('.plotly-graph-div');
      if (!d) return;
      new ResizeObserver(function () {{
        Plotly.relayout(d, {{height: c.clientHeight}});
      }}).observe(c);
    }});
  }}
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}})();
</script>
</body>
</html>"""

    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Public: full export bundle
# ---------------------------------------------------------------------------
def export_bundle(
    artifacts: "PipelineArtifacts",
    output_dir: str | Path = "hydroseason_export",
    *,
    title: str = "HydroSeason Report",
    value_col: str = "Rainfall_mm",
) -> Path:
    """Export a complete analysis bundle to a folder and return its path.

    Contents
    --------
    ::

        output_dir/
          report.html              - self-contained interactive HTML (offline)
          data/
            results_monthly.csv    - full labelled monthly result
            metrics_annual.csv     - per-hydro-year season metrics
            diagnostics.json       - full DiagnosticsReport as JSON

    Parameters
    ----------
    artifacts:
        ``PipelineArtifacts`` from :func:`~hydroseason.pipeline.classify_rainfall`.
    output_dir:
        Destination folder.  Created (including parents) if it does not exist.
    title:
        Title string used in the HTML report header.
    value_col:
        Column name for the primary measurement variable.

    Returns
    -------
    Path
        Resolved absolute path to *output_dir*.
    """
    import json
    from dataclasses import asdict

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = artifacts.result

    # 1. HTML report (offline, fully embedded)
    generate_html_report(artifacts, output_dir / "report.html", title=title, value_col=value_col)

    # 2. Tabular data
    data_dir = output_dir / "data"
    data_dir.mkdir(exist_ok=True)

    wet_col = "wet_total" if "wet_total" in result.columns else "Rain_wet_season_mm"
    dry_col = "dry_total" if "dry_total" in result.columns else "Rain_dry_season_mm"
    metric_cols = ["Hydro_Year", wet_col, dry_col, "wet_month_count", "dry_month_count"]
    if "dry_event_count" in result.columns:
        metric_cols.append("dry_event_count")
    for extra in ("Annual_SPI", "Year_Class_SPI", "Drought_Category"):
        if extra in result.columns:
            metric_cols.append(extra)
    available_cols = [c for c in metric_cols if c in result.columns]
    annual = (
        result[available_cols]
        .drop_duplicates(subset=["Hydro_Year"])
        .sort_values("Hydro_Year")
        .reset_index(drop=True)
    )
    annual.to_csv(data_dir / "metrics_annual.csv", index=False)

    # Monthly result: preserve all output columns, sorted by Date
    monthly_sort_col = "Date" if "Date" in result.columns else result.columns[0]
    result.sort_values(monthly_sort_col).reset_index(drop=True).to_csv(
        data_dir / "results_monthly.csv", index=False
    )

    diag_dict = asdict(artifacts.diagnostics)
    with open(data_dir / "diagnostics.json", "w", encoding="utf-8") as fh:
        json.dump(diag_dict, fh, indent=2, default=str)

    return output_dir.resolve()
