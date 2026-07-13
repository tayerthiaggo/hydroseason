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
import html
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from .plot import PLOTLY_CONFIG

if TYPE_CHECKING:  # avoid circular import at runtime
    from .pipeline import PipelineArtifacts


class HTMLSummary:
    """Small fallback HTML wrapper for environments without IPython."""

    def __init__(self, data: str):
        self.data = data

    def _repr_html_(self) -> str:
        return self.data


def _normalize_input(artifacts):
    """Normalize PipelineArtifacts or HydroSeasonResult to unified references."""
    if hasattr(artifacts, "monthly") and artifacts.monthly is not None:
        # HydroSeasonResult (daily or monthly routing result)
        return (
            artifacts.monthly,
            None,
            artifacts.diagnostics,
            artifacts.stress,
            artifacts.daily,
        )
    else:
        # PipelineArtifacts (monthly dynamic season pipeline output)
        return (
            artifacts.result,
            getattr(artifacts, "fixed_monthly", None),
            artifacts.diagnostics,
            getattr(artifacts, "stress", None),
            None,
        )


def _stress_table_html(stress_df) -> str:
    """Build a styled HTML table of annual hydrological stress metrics."""
    if stress_df is None or stress_df.empty:
        return (
            '<div style="font-family:sans-serif;font-size:12px;color:#546E7A;">'
            "No stress metrics available."
            "</div>"
        )

    cols_wanted = [
        "hydro_year",
        "stress_date",
        "stress_window_start",
        "stress_window_end",
        "dry_season_length_days",
        "antecedent_rainfall_deficit",
        "rainfall_since_wet_season_end",
        "stress_confidence",
    ]
    available = [c for c in cols_wanted if c in stress_df.columns]

    header_labels = {
        "hydro_year": "Hydro Year",
        "stress_date": "Stress Date",
        "stress_window_start": "Stress Window Start",
        "stress_window_end": "Stress Window End",
        "dry_season_length_days": "Dry Season Length (days)",
        "antecedent_rainfall_deficit": "Antecedent Deficit (mm)",
        "rainfall_since_wet_season_end": "Dry Season Rain (mm)",
        "stress_confidence": "Confidence Score",
    }

    th_style = (
        "padding:7px 12px;text-align:left;background:#D32F2F;color:white;"
        "font-size:12px;white-space:nowrap;"
    )
    td_style = "padding:6px 12px;font-size:12px;border-bottom:1px solid #ECEFF1;"

    headers = "".join(f'<th style="{th_style}">{header_labels.get(c, c)}</th>' for c in available)
    rows_html = ""
    for i, (_, row) in enumerate(stress_df.iterrows()):
        bg = "#FAFAFA" if i % 2 == 0 else "white"
        cells = ""
        for c in available:
            val = row[c]
            if pd.isna(val) or val is None:
                display_val = "N/A"
            elif c == "hydro_year":
                display_val = str(int(val))
            elif c in ("stress_date", "stress_window_start", "stress_window_end"):
                if hasattr(val, "strftime"):
                    display_val = val.strftime("%Y-%m-%d")
                else:
                    display_val = str(val)
            elif c == "stress_confidence":
                display_val = f"{float(val):.2f}"
            elif c in ("antecedent_rainfall_deficit", "rainfall_since_wet_season_end"):
                display_val = f"{float(val):.1f}"
            else:
                display_val = str(val)
            cells += f'<td style="{td_style}background:{bg};">{display_val}</td>'
        rows_html += f"<tr>{cells}</tr>"

    return (
        '<table style="border-collapse:collapse;width:100%;font-family:sans-serif;">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
    )


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


def _format_month_year(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    ts = pd.Timestamp(value)
    return f"{_MONTH_ABBR.get(ts.month, ts.month)} {ts.year}"


def _season_onsets_frame(result) -> pd.DataFrame:
    """Return per-hydro-year Wet/Dry onset month-year labels."""
    required = {"Date", "Hydro_Year", "SeasonType"}
    if not required.issubset(result.columns):
        return pd.DataFrame(columns=["Hydro_Year", "Wet start", "Dry start"])

    work = result[list(required)].copy()
    work["Date"] = pd.to_datetime(work["Date"])
    work = work.sort_values("Date").reset_index(drop=True)

    rows = []
    for hydro_year, group in work.groupby("Hydro_Year", sort=True):
        wet_rows = group[group["SeasonType"].eq("Wet")]
        wet_start = wet_rows["Date"].min() if not wet_rows.empty else None

        dry_rows = group[group["SeasonType"].eq("Dry")]
        if wet_start is not None and not pd.isna(wet_start):
            dry_rows = dry_rows[dry_rows["Date"] > wet_start]
        dry_start = dry_rows["Date"].min() if not dry_rows.empty else None

        rows.append(
            {
                "Hydro_Year": hydro_year,
                "Wet start": _format_month_year(wet_start),
                "Dry start": _format_month_year(dry_start),
            }
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Public: in-notebook summary card
# ---------------------------------------------------------------------------
def display_summary(artifacts: PipelineArtifacts | HydroSeasonResult):
    """Return an HTML summary card for inline notebook display when available.

    The card shows:
    - A coloured regime badge (green / amber / red)
    - Key diagnostics: Walsh-Lawler SI, STL F_S, hydro-year start month,
      date range, record count, imputed rows
    - Any validation warnings
    """
    result_df, fixed_monthly, d, stress_df, daily_df = _normalize_input(artifacts)
    result = result_df

    # Date range
    try:
        dates = result_df["Date"]
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
    onsets = _season_onsets_frame(result)
    if not onsets.empty:
        first_wet = onsets.loc[onsets["Wet start"].ne("N/A"), "Wet start"]
        first_dry = onsets.loc[onsets["Dry start"].ne("N/A"), "Dry start"]
        if not first_wet.empty:
            bullets.append(("First Wet start", first_wet.iloc[0]))
        if not first_dry.empty:
            bullets.append(("First Dry start", first_dry.iloc[0]))

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
    for extra in ("Annual_SPI", "Year_Class_SPI"):
        if extra in result.columns:
            cols_wanted.append(extra)

    available = [c for c in cols_wanted if c in result.columns]
    annual = (
        result[available]
        .drop_duplicates(subset=["Hydro_Year"])
        .sort_values("Hydro_Year")
        .reset_index(drop=True)
    )
    onsets = _season_onsets_frame(result)
    if not onsets.empty:
        annual = annual.merge(onsets, on="Hydro_Year", how="left")
        for col in ("Wet start", "Dry start"):
            if col not in available:
                available.append(col)

    header_labels = {
        "Hydro_Year": "Hydro Year",
        "Wet start": "Wet start",
        "Dry start": "Dry start",
        wet_col: f"Wet total ({value_col})",
        dry_col: f"Dry total ({value_col})",
        "wet_month_count": "Wet months",
        "dry_month_count": "Dry months",
        "dry_event_count": "Rainy dry months",
        "Annual_SPI": "Annual SPI",
        "Year_Class_SPI": "Year class (SPI)",
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
            elif c in ("Wet start", "Dry start", "Year_Class_SPI"):
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
    artifacts: PipelineArtifacts | HydroSeasonResult,
    output_path: str | Path = "hydroseason_report.html",
    *,
    title: str = "HydroSeason Report",
    value_col: str = "Rainfall_mm",
) -> Path:
    """Write a self-contained interactive HTML report and return its path.

    The report includes:
    1. Header / summary card (regime badge + key diagnostics)
    2. Season timeline (interactive Plotly)
    3. Hydrological stress timeline and metrics (interactive Plotly + HTML)
    4. Imputation and data quality (interactive Plotly)
    5. Imputed runs table (styled HTML)
    6. Aggregated monthly rainfall (interactive Plotly)
    7. Annual wet/dry totals (interactive Plotly)
    8. STL decomposition (interactive Plotly)
    9. Per-hydro-year metrics table (styled HTML)
    10. Diagnostics table (interactive Plotly)

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
        plot_stress_timeline,
    )

    output_path = Path(output_path)
    result_df, fixed_monthly, d, stress_df, daily_df = _normalize_input(artifacts)

    # Build each figure as an HTML div (full_html=False, include_plotlyjs only once)
    fig_timeline = plot_season_timeline(result_df, value_col=value_col, height=450)
    fig_quality = plot_imputation_overview(result_df, value_col=value_col, title="", height=320)
    fig_clim = plot_agg_monthly_rainfall(result_df, fixed_monthly, value_col=value_col, height=420)
    fig_annual = plot_annual_metrics(result_df, height=480)
    fig_stl = plot_stl_decomposition(result_df, value_col=value_col, title="", height=680)
    fig_diag = plot_diagnostics_table(d, title="", height=560)
    fig_stress = plot_stress_timeline(artifacts, value_col=value_col, height=450)

    # First figure gets the full Plotly JS bundle embedded once.
    html_timeline = fig_timeline.to_html(full_html=False, include_plotlyjs=True, config=PLOTLY_CONFIG)
    html_quality = fig_quality.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_clim = fig_clim.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_annual = fig_annual.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_stl = fig_stl.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_diag = fig_diag.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    html_stress = fig_stress.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)

    # Summary card
    start_month_name = (
        _MONTH_ABBR.get(d.hydro_year_start_month, str(d.hydro_year_start_month))
        if d.hydro_year_start_month
        else "N/A"
    )
    badge_style = _REGIME_BADGE_STYLE.get(d.regime, _DEFAULT_BADGE_STYLE)
    regime_label = d.regime.replace("_", " ").title()

    try:
        dates = result_df["Date"]
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

    metrics_table = _metrics_table_html(result_df, value_col=value_col)
    imputed_runs_note = _imputed_runs_note_html(d)
    imputed_runs_table = _imputed_runs_table_html(result_df)

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
            + _section_chart("Hydrological Stress Timeline", html_stress, 450) \
            + _section("Hydrological Stress Metrics", _stress_table_html(stress_df)) \
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


def generate_multisite_timeline_report(
    output_dir: str | Path,
    output_path: str | Path | None = None,
    *,
    summary_path: str | Path | None = None,
    title: str = "HydroSeason Multi-Site Timeline Report",
    value_col: str = "Rainfall_mm",
) -> Path:
    """Write a self-contained HTML gallery of per-site season timelines.

    The report is designed for the global fetch/classify stress-test outputs:
    a summary CSV plus per-site folders containing ``*_hydroseason_result.csv``.
    Sites without a classified result are still listed with their failure status.
    """
    from .plot import plot_season_timeline, plot_stress_timeline

    output_dir = Path(output_dir)
    if output_path is None:
        output_path = output_dir / "multisite_timeline_report.html"
    output_path = Path(output_path)

    if summary_path is None:
        summary_path = output_dir / "global_chirps_era5_stress_summary.csv"
    summary_path = Path(summary_path)
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")

    summary = pd.read_csv(summary_path)
    if "site_id" not in summary.columns:
        raise ValueError(f"Summary CSV must include 'site_id': {summary_path}")
    summary = summary.sort_values("site_id").reset_index(drop=True)

    ok_count = int(summary["status"].eq("ok").sum()) if "status" in summary.columns else 0
    failed_count = int((~summary["status"].eq("ok")).sum()) if "status" in summary.columns else 0

    plotly_embedded = False
    sections: list[str] = []
    for _, row in summary.iterrows():
        site_id = str(row["site_id"])
        country = str(row.get("country", "Unknown"))
        status = str(row.get("status", "unknown"))
        site_dir = output_dir / site_id
        result_path = site_dir / f"{site_id}_hydroseason_result.csv"
        monthly_path = site_dir / f"{site_id}_monthly_rainfall.csv"
        error_path = site_dir / f"{site_id}_error.txt"

        regime = str(row.get("regime", "")) or "n/a"
        lat_band = str(row.get("lat_band", "")) or "n/a"
        data_sources = str(row.get("data_sources", "")) or "n/a"
        continent = str(row.get("continent", "")) or "n/a"
        lat = row.get("lat", "")
        lon = row.get("lon", "")
        error_text = str(row.get("error", "") or "").strip()
        if not error_text and error_path.exists():
            error_text = error_path.read_text(encoding="utf-8").strip()

        title_bits = [site_id, country]
        if pd.notna(lat) and pd.notna(lon):
            title_bits.append(f"({float(lat):.3f}, {float(lon):.3f})")
        card_title = " ".join(title_bits)

        status_class = "ok" if status == "ok" else "failed"
        timeline_html = ""
        stress_html = ""
        if result_path.exists():
            result = pd.read_csv(result_path)
            fig = plot_season_timeline(
                result,
                value_col=value_col,
                title=f"{site_id} | {country}",
                height=340,
            )
            timeline_html = fig.to_html(
                full_html=False,
                include_plotlyjs=not plotly_embedded,
                config=PLOTLY_CONFIG,
            )
            plotly_embedded = True
            
            stress_path = site_dir / f"{site_id}_stress.csv"
            if stress_path.exists():
                stress_df = pd.read_csv(stress_path)
                from .pipeline import PipelineArtifacts
                dummy_artifacts = PipelineArtifacts(
                    result=result,
                    fixed_monthly=pd.DataFrame(),
                    wet_boundaries=None,
                    seasonality=None,
                    diagnostics=None,
                    stress=stress_df,
                )
                fig_stress = plot_stress_timeline(
                    dummy_artifacts,
                    value_col=value_col,
                    title=f"{site_id} | Hydrological Stress Timeline",
                    height=340,
                )
                stress_plot_html = fig_stress.to_html(
                    full_html=False,
                    include_plotlyjs=not plotly_embedded,
                    config=PLOTLY_CONFIG,
                )
                plotly_embedded = True
                
                stress_table_html = _stress_table_html(stress_df)
                stress_html = f"""
    <div style="margin-top:20px; border-top:1px solid #e7decd; padding-top:20px;">
      <h3 style="font-family:sans-serif;font-size:15px;color:#D32F2F;margin-top:0;">Hydrological Stress Timeline & Cumulative Anomaly</h3>
      <div class="chart-shell">{stress_plot_html}</div>
      <h3 style="font-family:sans-serif;font-size:15px;color:#D32F2F;margin-top:20px;margin-bottom:10px;">Hydrological Stress Metrics</h3>
      <div style="overflow-x:auto;">{stress_table_html}</div>
    </div>
"""
        else:
            detail = (
        f"Classified result not available. Monthly rainfall file exists: {monthly_path.exists()}."
            )
            if error_text:
                detail += f" Error: {error_text}"
            timeline_html = (
                '<div class="missing-plot">'
                f"{html.escape(detail)}"
                "</div>"
            )

        error_block = ""
        if error_text:
            error_block = (
                '<div class="error-block">'
                f"<strong>Error</strong><pre>{html.escape(error_text)}</pre>"
                "</div>"
            )

        stl_strength = row.get("stl_strength", None)
        walsh_lawler_si = row.get("walsh_lawler_si", None)
        circular_r = row.get("circular_R", None)
        contrast_class = str(row.get("season_contrast_class", "n/a"))
        contrast_ratio = row.get("season_contrast_ratio", None)
        hy_start_month = row.get("hydro_year_start_month", None)
        
        def fmt_val(v, fmt="{:.3f}"):
            return fmt.format(v) if pd.notna(v) and isinstance(v, (int, float)) else "n/a"

        diagnostics_html = (
            '<div class="meta-grid diagnostics-grid" style="margin-top: 10px; border-top: 1px dashed #cabda7; padding-top: 10px;">'
            f'<div><span class="meta-label">STL Strength (F_S)</span><span class="meta-value">{fmt_val(stl_strength)}</span></div>'
            f'<div><span class="meta-label">Walsh-Lawler SI</span><span class="meta-value">{fmt_val(walsh_lawler_si)}</span></div>'
            f'<div><span class="meta-label">Circular R</span><span class="meta-value">{fmt_val(circular_r)}</span></div>'
            f'<div><span class="meta-label">Contrast Class</span><span class="meta-value">{html.escape(contrast_class)}</span></div>'
            f'<div><span class="meta-label">Contrast Ratio</span><span class="meta-value">{fmt_val(contrast_ratio, "{:.2f}")}</span></div>'
            f'<div><span class="meta-label">HY Start Month</span><span class="meta-value">{fmt_val(hy_start_month, "{:.0f}")}</span></div>'
            "</div>"
        )

        metadata_html = (
            '<div class="meta-grid">'
            f'<div><span class="meta-label">regime</span><span class="meta-value">{html.escape(regime)}</span></div>'
            f'<div><span class="meta-label">lat_band</span><span class="meta-value">{html.escape(lat_band)}</span></div>'
            f'<div><span class="meta-label">data_sources</span><span class="meta-value">{html.escape(data_sources)}</span></div>'
            f'<div><span class="meta-label">continent</span><span class="meta-value">{html.escape(continent)}</span></div>'
            f'<div><span class="meta-label">status</span><span class="meta-value">{html.escape(status)}</span></div>'
            f'<div><span class="meta-label">coords</span><span class="meta-value">{html.escape(str(lat))}, {html.escape(str(lon))}</span></div>'
            "</div>"
        )

        sections.append(
            f"""
<details class="site-card {status_class}" data-site="{html.escape(site_id.lower())}" data-country="{html.escape(country.lower())}" data-status="{html.escape(status.lower())}" data-regime="{html.escape(regime.lower())}" data-lat-band="{html.escape(lat_band.lower())}" data-data-sources="{html.escape(data_sources.lower())}">
  <summary>
    <span class="site-name">{html.escape(card_title)}</span>
    <span class="pill status-pill {status_class}">{html.escape(status)}</span>
    <span class="pill">{html.escape(regime)}</span>
    <span class="pill">{html.escape(lat_band)}</span>
    <span class="pill">{html.escape(data_sources)}</span>
  </summary>
  <div class="site-body">
    {metadata_html}
    {diagnostics_html}
    <div class="chart-shell" style="margin-top:14px;">{timeline_html}</div>
    {stress_html}
    {error_block}
  </div>
</details>"""
        )

    summary_json = html.escape(
        json.dumps(
            {
                "n_sites": int(len(summary)),
                "n_ok": ok_count,
                "n_failed": failed_count,
                "summary_csv": str(summary_path),
            },
            indent=2,
        )
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
  <style>
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0;
      background: #f7f6f2;
      color: #1a2a36;
      line-height: 1.5;
    }}
    .page {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 32px 24px;
    }}
    .hero {{
      background: linear-gradient(135deg, #112a36 0%, #1e4559 50%, #cca560 100%);
      color: white;
      padding: 40px;
      border-radius: 20px;
      box-shadow: 0 20px 40px rgba(17, 42, 54, 0.15);
      margin-bottom: 28px;
    }}
    .hero h1 {{
      font-family: 'Outfit', sans-serif;
      font-weight: 800;
      font-size: 36px;
      margin: 0 0 12px;
      letter-spacing: -0.02em;
    }}
    .hero p {{
      margin: 0;
      max-width: 900px;
      font-size: 15px;
      line-height: 1.6;
      opacity: 0.9;
    }}
    .summary-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 20px;
    }}
    .summary-pill {{
      display: inline-flex;
      align-items: center;
      padding: 8px 16px;
      border-radius: 99px;
      font-size: 13px;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(4px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: white;
    }}
    .summary-pill.light {{
      background: #ffffff;
      color: #112a36;
      border: 0;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      align-items: center;
      margin-bottom: 24px;
      padding: 20px;
      background: #ffffff;
      border: 1px solid rgba(17, 42, 54, 0.06);
      border-radius: 16px;
      box-shadow: 0 4px 12px rgba(17, 42, 54, 0.02);
    }}
    .search-box {{
      flex: 1 1 300px;
      min-width: 200px;
    }}
    .search-box input {{
      width: 100%;
      box-sizing: border-box;
      padding: 12px 16px;
      border-radius: 10px;
      border: 1px solid #dcdad5;
      font-size: 14px;
      font-family: inherit;
      background: #fcfcfb;
      transition: all 0.2s ease;
    }}
    .search-box input:focus {{
      outline: none;
      border-color: #cca560;
      background: #ffffff;
      box-shadow: 0 0 0 3px rgba(202, 165, 96, 0.15);
    }}
    .filter-group {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .filter-group-label {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #61737e;
      margin-right: 4px;
    }}
    .filter-pill {{
      padding: 8px 14px;
      border: 1px solid #dcdad5;
      border-radius: 99px;
      background: #ffffff;
      color: #2b3e4a;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      font-family: inherit;
      transition: all 0.2s ease;
    }}
    .filter-pill:hover {{
      background: #f7f6f2;
      border-color: #cca560;
    }}
    .filter-pill.active {{
      background: #112a36;
      color: #ffffff;
      border-color: #112a36;
      font-weight: 600;
    }}
    .action-buttons {{
      display: flex;
      gap: 8px;
      margin-left: auto;
    }}
    .action-buttons button {{
      padding: 10px 16px;
      border: 0;
      border-radius: 10px;
      background: #112a36;
      color: white;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      font-family: inherit;
      transition: all 0.2s ease;
    }}
    .action-buttons button:hover {{
      background: #1e4559;
      transform: translateY(-1px);
    }}
    .site-card {{
      margin-bottom: 16px;
      border: 1px solid rgba(17, 42, 54, 0.08);
      border-radius: 16px;
      background: #ffffff;
      box-shadow: 0 6px 16px rgba(17, 42, 54, 0.03);
      overflow: hidden;
      transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }}
    .site-card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 12px 24px rgba(17, 42, 54, 0.06);
      border-color: rgba(202, 165, 96, 0.3);
    }}
    .site-card summary {{
      list-style: none;
      cursor: pointer;
      padding: 18px 24px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      background: #fbfbf9;
      border-bottom: 1px solid rgba(17, 42, 54, 0.04);
      user-select: none;
    }}
    .site-card summary::-webkit-details-marker {{
      display: none;
    }}
    .site-card[open] summary {{
      background: #f9f8f4;
    }}
    .site-name {{
      font-family: 'Outfit', sans-serif;
      font-weight: 700;
      font-size: 18px;
      color: #112a36;
      margin-right: auto;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 99px;
      font-size: 12px;
      font-weight: 600;
      background: #e8ecee;
      color: #1e4559;
    }}
    .pill.status-pill.ok {{
      background: #e6f6eb;
      color: #137333;
    }}
    .pill.status-pill.failed {{
      background: #fdf2f2;
      color: #c53030;
    }}
    .site-body {{
      padding: 24px;
      background: #ffffff;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .meta-grid > div {{
      background: #fcfbf9;
      border: 1px solid rgba(17, 42, 54, 0.04);
      border-radius: 12px;
      padding: 12px 14px;
      transition: all 0.2s ease;
    }}
    .meta-grid > div:hover {{
      background: #f7f6f2;
      border-color: rgba(202, 165, 96, 0.15);
    }}
    .meta-label {{
      display: block;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #71828a;
      margin-bottom: 4px;
      font-weight: 700;
    }}
    .meta-value {{
      font-size: 14px;
      font-weight: 600;
      color: #112a36;
    }}
    .chart-shell {{
      border-radius: 12px;
      border: 1px solid rgba(17, 42, 54, 0.05);
      overflow: hidden;
      background: white;
      box-shadow: inset 0 2px 8px rgba(17, 42, 54, 0.01);
    }}
    .missing-plot {{
      padding: 20px;
      border-radius: 12px;
      background: #fffafa;
      color: #c53030;
      border: 1px solid #fde8e8;
      font-size: 14px;
    }}
    .error-block {{
      margin-top: 16px;
      padding: 16px;
      border-radius: 12px;
      background: #fffafa;
      border: 1px solid #fde8e8;
    }}
    .error-block strong {{
      color: #c53030;
      font-size: 14px;
    }}
    .error-block pre, .summary-json {{
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.45;
      margin: 8px 0 0;
    }}
    .summary-json {{
      margin-bottom: 24px;
      background: #ffffff;
      padding: 16px 20px;
      border-radius: 16px;
      border: 1px solid rgba(17, 42, 54, 0.06);
      font-size: 12px;
      line-height: 1.5;
      color: #4a5568;
    }}
    .hidden {{
      display: none !important;
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{html.escape(title)}</h1>
      <p>Manual inspection gallery for cached HydroSeason site outputs. Each site section shows its season timeline and hydrological stress metrics when available, along with diagnostics. Failed sites stay in the report so gaps are visible during review.</p>
      <div class="summary-strip">
        <span class="summary-pill light">sites: {len(summary)}</span>
        <span class="summary-pill light">ok: {ok_count}</span>
        <span class="summary-pill light">not ok: {failed_count}</span>
        <span class="summary-pill light">summary: {html.escape(str(summary_path))}</span>
      </div>
    </section>

    <section class="toolbar">
      <div class="search-box">
        <input id="site-filter" type="search" placeholder="Filter by site, country, lat_band, etc...">
      </div>
      <div class="filter-group">
        <span class="filter-group-label">Regime:</span>
        <button type="button" class="filter-pill active" data-filter-type="regime" data-filter-value="all">All</button>
        <button type="button" class="filter-pill" data-filter-type="regime" data-filter-value="seasonal">Seasonal</button>
        <button type="button" class="filter-pill" data-filter-type="regime" data-filter-value="borderline">Borderline</button>
        <button type="button" class="filter-pill" data-filter-type="regime" data-filter-value="non_seasonal">Non-Seasonal</button>
      </div>
      <div class="filter-group">
        <span class="filter-group-label">Status:</span>
        <button type="button" class="filter-pill active" data-filter-type="status" data-filter-value="all">All</button>
        <button type="button" class="filter-pill" data-filter-type="status" data-filter-value="ok">OK</button>
        <button type="button" class="filter-pill" data-filter-type="status" data-filter-value="failed">Failed</button>
      </div>
      <div class="action-buttons">
        <button type="button" id="expand-all">Expand all</button>
        <button type="button" id="collapse-all">Collapse all</button>
      </div>
    </section>

    <pre class="summary-json">{summary_json}</pre>

    {''.join(sections)}
  </div>

  <script>
    (function () {{
      var filterInput = document.getElementById('site-filter');
      var cards = Array.prototype.slice.call(document.querySelectorAll('.site-card'));
      var expandAll = document.getElementById('expand-all');
      var collapseAll = document.getElementById('collapse-all');
      var filterPills = Array.prototype.slice.call(document.querySelectorAll('.filter-pill'));

      var activeFilters = {{
        regime: 'all',
        status: 'all'
      }};

      function haystack(card) {{
        return [
          card.dataset.site,
          card.dataset.country,
          card.dataset.status,
          card.dataset.regime,
          card.dataset.latBand,
          card.dataset.dataSources
        ].join(' ');
      }}

      function applyFilters() {{
        var q = (filterInput.value || '').toLowerCase().trim();
        cards.forEach(function (card) {{
          var textMatch = !q || haystack(card).indexOf(q) >= 0;
          var regimeMatch = activeFilters.regime === 'all' || card.dataset.regime === activeFilters.regime;
          var statusMatch = activeFilters.status === 'all' || card.dataset.status === activeFilters.status;
          
          card.classList.toggle('hidden', !(textMatch && regimeMatch && statusMatch));
        }});
      }}

      filterInput.addEventListener('input', applyFilters);

      filterPills.forEach(function (pill) {{
        pill.addEventListener('click', function () {{
          var type = pill.dataset.filterType;
          var val = pill.dataset.filterValue;
          
          // Deactivate siblings
          filterPills.forEach(function (sibling) {{
            if (sibling.dataset.filterType === type) {{
              sibling.classList.remove('active');
            }}
          }});
          
          pill.classList.add('active');
          activeFilters[type] = val;
          applyFilters();
        }});
      }});

      expandAll.addEventListener('click', function () {{
        cards.forEach(function (card) {{
          if (!card.classList.contains('hidden')) {{
            card.open = true;
          }}
        }});
      }});
      collapseAll.addEventListener('click', function () {{
        cards.forEach(function (card) {{
          card.open = false;
        }});
      }});
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
    artifacts: PipelineArtifacts | HydroSeasonResult,
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
        ``PipelineArtifacts`` or ``HydroSeasonResult`` from the pipeline run.
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
    result_df, fixed_monthly, d, stress_df, daily_df = _normalize_input(artifacts)
    result = result_df

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
    for extra in ("Annual_SPI", "Year_Class_SPI"):
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

    diag_dict = asdict(d)
    with open(data_dir / "diagnostics.json", "w", encoding="utf-8") as fh:
        json.dump(diag_dict, fh, indent=2, default=str)

    return output_dir.resolve()
