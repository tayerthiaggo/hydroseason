"""HTML Report Generator for HydroSeason.

Generates a gorgeous, self-contained, responsive, and interactive HTML report
summarizing water-extent seasonal detection results.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
import pandas as pd
import numpy as np


def _generate_svg_chart(extent_df: pd.DataFrame, hy_df: pd.DataFrame, labels_df: pd.DataFrame) -> str:
    """Generate a clean, beautiful, offline-friendly SVG chart for water extent and seasons."""
    if extent_df.empty or len(extent_df) < 2:
        return '<div class="no-chart">Insufficient data points to render time-series chart.</div>'

    # Dimensions (main chart + a smaller HY-boundary subplot below it)
    width = 1200
    main_height = 360
    hy_height = 110
    gap = 30
    height = main_height + gap + hy_height
    pad_left = 60
    pad_right = 40
    pad_top = 30
    pad_bottom = 50

    chart_w = width - pad_left - pad_right
    chart_h = main_height - pad_top - pad_bottom

    df = extent_df.sort_index().copy()
    min_date = df.index.min()
    max_date = df.index.max()
    dt_range = (max_date - min_date).total_seconds()
    if dt_range <= 0:
        dt_range = 1.0

    # Draw shaded seasonal backgrounds
    season_bands = []
    # Identify contiguous blocks of Wet / Dry / Unassigned
    month_width = (30.5 * 24 * 3600) / dt_range * chart_w  # approximate month width
    
    for i, (ts, row) in enumerate(labels_df.sort_index().iterrows()):
        dt = (ts - min_date).total_seconds()
        x_start = pad_left + (dt / dt_range) * chart_w - month_width / 2
        x_end = x_start + month_width
        
        # Clip to chart boundaries
        x_start = max(pad_left, x_start)
        x_end = min(width - pad_right, x_end)
        if x_end <= x_start:
            continue
            
        season = row.get("season", "unassigned")
        if season == "Wet":
            # Blue hue (lighter for white bg)
            fill = "rgba(59, 130, 246, 0.15)"
            title_text = f"{ts.strftime('%b %Y')}: Wet Season"
        elif season == "Dry":
            # Reddish hue (lighter for white bg)
            fill = "rgba(239, 68, 68, 0.12)"
            title_text = f"{ts.strftime('%b %Y')}: Dry Season"
        else:
            fill = "transparent"
            title_text = f"{ts.strftime('%b %Y')}: Unassigned"

        season_bands.append(
            f'<rect x="{x_start:.1f}" y="{pad_top}" width="{(x_end - x_start):.1f}" height="{chart_h}" '
            f'fill="{fill}" stroke="none"><title>{title_text}</title></rect>'
        )

    # Gridlines & Labels
    gridlines = []
    # Y-axis ticks (0%, 25%, 50%, 75%, 100%)
    for pct in [0, 25, 50, 75, 100]:
        y = pad_top + (1.0 - pct / 100.0) * chart_h
        gridlines.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-dasharray="4,4" stroke-width="1" />'
        )
        gridlines.append(
            f'<text x="{pad_left - 10}" y="{(y + 4):.1f}" fill="#64748b" font-size="11" '
            f'text-anchor="end" font-family="sans-serif">{pct}%</text>'
        )

    # X-axis ticks (Annual boundaries)
    years = range(min_date.year, max_date.year + 1)
    for yr in years:
        tick_date = pd.Timestamp(yr, 1, 1)
        if tick_date < min_date:
            tick_date = min_date
        if tick_date > max_date:
            tick_date = max_date
        
        dt = (tick_date - min_date).total_seconds()
        x = pad_left + (dt / dt_range) * chart_w
        gridlines.append(
            f'<line x1="{x:.1f}" y1="{pad_top}" x2="{x:.1f}" y2="{pad_top + chart_h}" '
            f'stroke="#e2e8f0" stroke-width="1" />'
        )
        gridlines.append(
            f'<text x="{x:.1f}" y="{height - pad_bottom + 20}" fill="#64748b" font-size="11" '
            f'text-anchor="middle" font-family="sans-serif">{yr}</text>'
        )

    # Main extent line
    points = []
    invalid_points = []
    for ts, row in df.iterrows():
        val = row.get("extent_pct", np.nan)
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = pad_left + (dt / dt_range) * chart_w
        y = pad_top + (1.0 - val / 100.0) * chart_h
        points.append((x, y, ts, val))
        
        # Track invalid coverage if high
        inv = row.get("invalid_pct", 0.0)
        if inv > 20.0:
            invalid_points.append((x, y, ts, inv))

    path_data = ""
    if points:
        path_data = f"M {points[0][0]:.1f} {points[0][1]:.1f} "
        for p in points[1:]:
            path_data += f"L {p[0]:.1f} {p[1]:.1f} "

    extent_path = (
        f'<path d="{path_data}" fill="none" stroke="#93c5fd" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round" />'
    )

    # 3-month smoothed extent, drawn thicker on top of the raw line
    smoothed = df["extent_pct"].rolling(window=3, min_periods=1, center=True).mean()
    smooth_points = []
    for ts, val in smoothed.items():
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = pad_left + (dt / dt_range) * chart_w
        y = pad_top + (1.0 - val / 100.0) * chart_h
        smooth_points.append((x, y))

    smooth_path_data = ""
    if smooth_points:
        smooth_path_data = f"M {smooth_points[0][0]:.1f} {smooth_points[0][1]:.1f} "
        for p in smooth_points[1:]:
            smooth_path_data += f"L {p[0]:.1f} {p[1]:.1f} "

    smooth_path = (
        f'<path d="{smooth_path_data}" fill="none" stroke="#2563eb" stroke-width="2.5" '
        f'stroke-linecap="round" stroke-linejoin="round" />'
    )

    # Highlight Peak Wet, Mid Dry and End Dry months from hy_df
    markers = []
    for _, row in hy_df.iterrows():
        peak_t = pd.Timestamp(row["peak_month"])
        mid_t = pd.Timestamp(row["mid_dry_month"])
        end_t = pd.Timestamp(row["end_dry_month"])

        peak_val = row["peak_extent_pct"]
        mid_val = row["mid_extent_pct"]
        end_val = row["end_extent_pct"]
        confidence = row.get("confidence", "unassigned")

        # Peak marker: diamond, filled for high confidence, hollow outline for medium/low
        dt_p = (peak_t - min_date).total_seconds()
        x_p = pad_left + (dt_p / dt_range) * chart_w
        y_p = pad_top + (1.0 - peak_val / 100.0) * chart_h
        d = 7
        diamond_pts = f"{x_p:.1f},{y_p - d:.1f} {x_p + d:.1f},{y_p:.1f} {x_p:.1f},{y_p + d:.1f} {x_p - d:.1f},{y_p:.1f}"
        peak_fill = "#3b82f6" if confidence == "high" else "#ffffff"
        peak_label = f"Peak Wet {row['hy_year']} ({confidence} confidence): {peak_t.strftime('%b %Y')} ({peak_val:.1f}%)"
        markers.append(
            f'<polygon points="{diamond_pts}" fill="{peak_fill}" stroke="#3b82f6" stroke-width="2" '
            f'class="chart-marker" data-label="{html.escape(peak_label)}">'
            f'<title>{peak_label}</title>'
            f'</polygon>'
        )

        # Mid Dry marker: square
        dt_m = (mid_t - min_date).total_seconds()
        x_m = pad_left + (dt_m / dt_range) * chart_w
        y_m = pad_top + (1.0 - mid_val / 100.0) * chart_h
        s = 6
        mid_label = f"Mid Dry {row['hy_year']}: {mid_t.strftime('%b %Y')} ({mid_val:.1f}%)"
        markers.append(
            f'<rect x="{x_m - s:.1f}" y="{y_m - s:.1f}" width="{2 * s}" height="{2 * s}" '
            f'fill="#f97316" stroke="#ffffff" stroke-width="1.5" '
            f'class="chart-marker" data-label="{html.escape(mid_label)}">'
            f'<title>{mid_label}</title>'
            f'</rect>'
        )

        # End Dry marker: downward triangle (HY boundary)
        dt_e = (end_t - min_date).total_seconds()
        x_e = pad_left + (dt_e / dt_range) * chart_w
        y_e = pad_top + (1.0 - end_val / 100.0) * chart_h
        t = 7
        tri_pts = f"{x_e - t:.1f},{y_e - t * 0.6:.1f} {x_e + t:.1f},{y_e - t * 0.6:.1f} {x_e:.1f},{y_e + t * 0.8:.1f}"
        end_label = f"End Dry {row['hy_year']}: {end_t.strftime('%b %Y')} ({end_val:.1f}%)"
        markers.append(
            f'<polygon points="{tri_pts}" fill="#ef4444" stroke="#ffffff" stroke-width="1.5" '
            f'class="chart-marker" data-label="{html.escape(end_label)}">'
            f'<title>{end_label}</title>'
            f'</polygon>'
        )

    # Add points for hover/click interaction
    hover_points = []
    for x, y, ts, val in points:
        node_label = f"{ts.strftime('%b %Y')}: {val:.1f}%"
        hover_points.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#334155" opacity="0.0" '
            f'class="chart-node chart-marker" data-label="{html.escape(node_label)}">'
            f'<title>{node_label}</title>'
            f'</circle>'
        )

    # HY-boundary subplot: a step line showing which hydrological year each month belongs to
    hy_top = main_height + gap
    hy_chart_h = hy_height - pad_bottom + 10
    hy_elements = []
    hy_years_sorted = hy_df.dropna(subset=["hy_year"]).sort_values("hy_year") if not hy_df.empty else hy_df
    if not hy_years_sorted.empty:
        hy_min = hy_years_sorted["hy_year"].min()
        hy_max = hy_years_sorted["hy_year"].max()
        hy_span = max(hy_max - hy_min, 1)

        step_points = []
        for _, row in hy_years_sorted.iterrows():
            start_ts = pd.Timestamp(row["hy_start"])
            end_ts = pd.Timestamp(row["hy_end"])
            hy_val = row["hy_year"]
            y_val = hy_top + (1.0 - (hy_val - hy_min) / hy_span) * hy_chart_h
            for ts in (start_ts, end_ts):
                dt = (ts - min_date).total_seconds()
                x = pad_left + (dt / dt_range) * chart_w
                step_points.append((x, y_val))

        if step_points:
            hy_path_data = f"M {step_points[0][0]:.1f} {step_points[0][1]:.1f} "
            for p in step_points[1:]:
                hy_path_data += f"L {p[0]:.1f} {p[1]:.1f} "
            hy_elements.append(
                f'<path d="{hy_path_data}" fill="none" stroke="#334155" stroke-width="1.5" />'
            )

        for pct in (0, 50, 100):
            hy_val = hy_min + hy_span * pct / 100.0
            y = hy_top + (1.0 - pct / 100.0) * hy_chart_h
            hy_elements.append(
                f'<text x="{pad_left - 10}" y="{(y + 4):.1f}" fill="#64748b" font-size="11" '
                f'text-anchor="end" font-family="sans-serif">{int(round(hy_val))}</text>'
            )

    hy_subplot = f"""
  <text x="{pad_left}" y="{hy_top - 8}" fill="#64748b" font-size="12" font-family="sans-serif">Hydrological year labels from month-after-end-dry to end-dry boundaries</text>
  <line x1="{pad_left}" y1="{hy_top}" x2="{width - pad_right}" y2="{hy_top}" stroke="#e2e8f0" stroke-width="1" />
  {"".join(hy_elements)}"""

    svg = f"""<svg viewBox="0 0 {width} {height}" width="100%" height="100%" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
  {"".join(season_bands)}
  {"".join(gridlines)}
  {extent_path}
  {smooth_path}
  {"".join(markers)}
  {"".join(hover_points)}
  {hy_subplot}
</svg>"""
    return svg


def _generate_seasonal_context_svg(extent_df: pd.DataFrame) -> str:
    """Two-panel SVG: monthly climatology (mean +/- 1 std) and raw-vs-smoothed time series."""
    if extent_df.empty:
        return '<div class="no-chart">Insufficient data points to render seasonal context chart.</div>'

    df = extent_df.sort_index().copy()

    width = 1200
    height = 320
    gap = 50
    panel_w = (width - gap) / 2
    pad_left = 55
    pad_right = 20
    pad_top = 30
    pad_bottom = 45
    panel_chart_w = panel_w - pad_left - pad_right
    panel_chart_h = height - pad_top - pad_bottom

    # --- Left panel: monthly climatology (mean +/- 1 std) ---
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly = df.groupby(df.index.month)["extent_pct"].agg(["mean", "std"]).reindex(range(1, 13))
    monthly["std"] = monthly["std"].fillna(0.0)
    max_val = max((monthly["mean"] + monthly["std"]).max(), 1.0)

    bars = []
    bar_w = panel_chart_w / 12 * 0.65
    slot_w = panel_chart_w / 12
    for i, month_num in enumerate(range(1, 13)):
        mean_val = monthly.loc[month_num, "mean"]
        std_val = monthly.loc[month_num, "std"]
        if pd.isna(mean_val):
            continue
        x_center = pad_left + slot_w * (i + 0.5)
        bar_h = (mean_val / max_val) * panel_chart_h
        y_top = pad_top + panel_chart_h - bar_h
        bars.append(
            f'<rect x="{x_center - bar_w / 2:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="#60a5fa" stroke="#2563eb" stroke-width="1">'
            f'<title>{month_names[i]}: {mean_val:.2f}% +/- {std_val:.2f}%</title></rect>'
        )
        err_top = pad_top + panel_chart_h - min((mean_val + std_val) / max_val * panel_chart_h, panel_chart_h)
        err_bottom = pad_top + panel_chart_h - max((mean_val - std_val) / max_val * panel_chart_h, 0)
        bars.append(
            f'<line x1="{x_center:.1f}" y1="{err_top:.1f}" x2="{x_center:.1f}" y2="{err_bottom:.1f}" '
            f'stroke="#1e293b" stroke-width="1.5" />'
        )
        bars.append(
            f'<text x="{x_center:.1f}" y="{height - pad_bottom + 16:.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="middle" font-family="sans-serif">{month_names[i]}</text>'
        )

    left_gridlines = []
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        val = max_val * frac
        y = pad_top + panel_chart_h - frac * panel_chart_h
        left_gridlines.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + panel_chart_w}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-dasharray="4,4" stroke-width="1" />'
        )
        left_gridlines.append(
            f'<text x="{pad_left - 8}" y="{(y + 4):.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="end" font-family="sans-serif">{val:.1f}%</text>'
        )

    left_panel = f"""
  <text x="{pad_left}" y="16" fill="#334155" font-size="13" font-weight="600" font-family="sans-serif">Long-term monthly climatology (+/-1 std)</text>
  {"".join(left_gridlines)}
  {"".join(bars)}"""

    # --- Right panel: raw vs 3-month smoothed time series ---
    right_x0 = panel_w + gap
    min_date = df.index.min()
    max_date = df.index.max()
    dt_range = (max_date - min_date).total_seconds() or 1.0
    right_chart_w = panel_chart_w
    series_max = max(df["extent_pct"].max(), 1.0)

    raw_pts = []
    for ts, val in df["extent_pct"].items():
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = right_x0 + pad_left + (dt / dt_range) * right_chart_w
        y = pad_top + (1.0 - val / series_max) * panel_chart_h
        raw_pts.append((x, y))

    smoothed = df["extent_pct"].rolling(window=3, min_periods=1, center=True).mean()
    smooth_pts = []
    for ts, val in smoothed.items():
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = right_x0 + pad_left + (dt / dt_range) * right_chart_w
        y = pad_top + (1.0 - val / series_max) * panel_chart_h
        smooth_pts.append((x, y))

    def _path(pts):
        if not pts:
            return ""
        d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f} "
        for p in pts[1:]:
            d += f"L {p[0]:.1f} {p[1]:.1f} "
        return d

    raw_path = f'<path d="{_path(raw_pts)}" fill="none" stroke="#93c5fd" stroke-width="1.2" />'
    smooth_path_r = f'<path d="{_path(smooth_pts)}" fill="none" stroke="#2563eb" stroke-width="2.2" />'

    right_gridlines = []
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        val = series_max * frac
        y = pad_top + panel_chart_h - frac * panel_chart_h
        right_gridlines.append(
            f'<line x1="{right_x0 + pad_left}" y1="{y:.1f}" x2="{right_x0 + pad_left + right_chart_w}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-dasharray="4,4" stroke-width="1" />'
        )
        right_gridlines.append(
            f'<text x="{right_x0 + pad_left - 8}" y="{(y + 4):.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="end" font-family="sans-serif">{val:.1f}%</text>'
        )

    years = range(min_date.year, max_date.year + 1, max(1, (max_date.year - min_date.year) // 6 or 1))
    for yr in years:
        tick_date = pd.Timestamp(yr, 1, 1)
        tick_date = min(max(tick_date, min_date), max_date)
        dt = (tick_date - min_date).total_seconds()
        x = right_x0 + pad_left + (dt / dt_range) * right_chart_w
        right_gridlines.append(
            f'<text x="{x:.1f}" y="{height - pad_bottom + 16:.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="middle" font-family="sans-serif">{yr}</text>'
        )

    right_panel = f"""
  <text x="{right_x0 + pad_left}" y="16" fill="#334155" font-size="13" font-weight="600" font-family="sans-serif">Extent time series - raw vs smoothed</text>
  {"".join(right_gridlines)}
  {raw_path}
  {smooth_path_r}"""

    svg = f"""<svg viewBox="0 0 {width} {height}" width="100%" height="100%" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
  {left_panel}
  {right_panel}
</svg>"""
    return svg


def generate_html_report(
    extent: pd.DataFrame,
    hydro_years: pd.DataFrame,
    output_path: str | Path,
    title: str = "HydroSeason Seasonal Analysis",
) -> Path:
    """Generate a self-contained interactive HTML report of the hydrological season detection.

    Parameters
    ----------
    extent : pd.DataFrame
        Monthly water extent DataFrame (must contain 'extent_pct' index should be DatetimeIndex).
    hydro_years : pd.DataFrame
        Hydrological years DataFrame returned by `detect_hydrological_years`.
    output_path : str | Path
        Path to save the generated HTML file.
    title : str, default "HydroSeason Seasonal Analysis"
        Title shown in the report header.

    Returns
    -------
    Path
        Absolute path to the written HTML file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Calculate labels
    from hydroseason.hydro_year import label_hydrological_months
    labels = label_hydrological_months(extent.index, hydro_years)

    # 1. Summary KPIs
    total_months = len(extent)
    start_date = extent.index.min().strftime("%b %Y") if not extent.empty else "N/A"
    end_date = extent.index.max().strftime("%b %Y") if not extent.empty else "N/A"
    
    n_years = len(hydro_years)
    
    if n_years > 0:
        mean_peak = hydro_years["peak_extent_pct"].mean()
        mean_end = hydro_years["end_extent_pct"].mean()
        mean_amp = hydro_years["amplitude_pct"].mean()
        mean_len = hydro_years["n_months_cycle"].mean()
        high_conf = len(hydro_years[hydro_years["confidence"] == "high"])
        med_conf = len(hydro_years[hydro_years["confidence"] == "medium"])
        low_conf = len(hydro_years[hydro_years["confidence"] == "low"])
        min_end = hydro_years["end_extent_pct"].min()
        max_peak = hydro_years["peak_extent_pct"].max()
    else:
        mean_peak = mean_end = mean_amp = mean_len = 0.0
        high_conf = med_conf = low_conf = 0
        min_end = max_peak = 0.0

    avg_invalid = extent["invalid_pct"].mean() if "invalid_pct" in extent.columns else 0.0

    # 2. Year Details Sections
    year_cards = []
    for _, row in hydro_years.sort_values("hy_year", ascending=False).iterrows():
        hy_val = int(row["hy_year"])
        conf = row.get("confidence", "unassigned")
        conf_cls = f"badge-{conf}"
        
        # Extract monthly timeline for this hydro year
        start_ts = pd.Timestamp(row["hy_start"])
        end_ts = pd.Timestamp(row["hy_end"])
        year_months = labels[(labels.index >= start_ts) & (labels.index <= end_ts)].copy()
        
        # Build month status rows
        month_rows = []
        for ts, m_row in year_months.iterrows():
            ext_val = extent.loc[ts, "extent_pct"] if ts in extent.index else np.nan
            inv_val = extent.loc[ts, "invalid_pct"] if (ts in extent.index and "invalid_pct" in extent.columns) else 0.0
            
            ext_str = f"{ext_val:.1f}%" if not pd.isna(ext_val) else "N/A"
            inv_str = f"{inv_val:.1f}%" if inv_val > 0 else "0%"
            
            is_peak = (ts == pd.Timestamp(row["peak_month"]))
            is_mid = (ts == pd.Timestamp(row["mid_dry_month"]))
            is_end = (ts == pd.Timestamp(row["end_dry_month"]))
            
            label_style = "season-wet" if m_row["season"] == "Wet" else "season-dry"
            label_text = m_row["season"]
            
            marker_html = ""
            if is_peak:
                marker_html = '<span class="cell-marker marker-wet">Wet Peak</span>'
            elif is_end:
                marker_html = '<span class="cell-marker marker-dry">Dry End</span>'
            elif is_mid:
                marker_html = '<span class="cell-marker marker-mid">Mid Dry</span>'
                
            month_rows.append(f"""
            <tr>
              <td>{ts.strftime("%b %Y")}</td>
              <td><span class="season-badge {label_style}">{label_text}</span></td>
              <td><strong>{ext_str}</strong></td>
              <td>{inv_str}</td>
              <td>{marker_html}</td>
            </tr>""")

        month_table = f"""
        <table class="nested-table">
          <thead>
            <tr>
              <th>Month</th>
              <th>Season Assignment</th>
              <th>Water Extent</th>
              <th>Invalid/Cloud Cover</th>
              <th>Key Event</th>
            </tr>
          </thead>
          <tbody>
            {"".join(month_rows)}
          </tbody>
        </table>"""

        year_cards.append(f"""
        <details class="year-card" id="hy-card-{hy_val}">
          <summary class="year-header">
            <div class="year-title-group">
              <span class="expand-icon">▶</span>
              <span class="year-number">HY {hy_val}</span>
              <span class="year-dates">{start_ts.strftime("%b %Y")} – {end_ts.strftime("%b %Y")}</span>
            </div>
            <div class="year-meta-group">
              <span class="summary-stat">Cycle: <strong>{row["n_months_cycle"]} mos</strong></span>
              <span class="summary-stat">Amplitude: <strong>{row["amplitude_pct"]:.1f}%</strong></span>
              <span class="confidence-badge {conf_cls}">{conf.upper()}</span>
            </div>
          </summary>
          <div class="year-detail-content">
            <div class="detail-kpis">
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">Peak Wet Month</span>
                <span class="detail-kpi-value value-wet">{pd.Timestamp(row["peak_month"]).strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{row["peak_extent_pct"]:.1f}% extent</span>
              </div>
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">Mid-Dry Target</span>
                <span class="detail-kpi-value value-mid">{pd.Timestamp(row["mid_dry_month"]).strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{row["mid_extent_pct"]:.1f}% extent</span>
              </div>
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">End Dry Month</span>
                <span class="detail-kpi-value value-dry">{pd.Timestamp(row["end_dry_month"]).strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{row["end_extent_pct"]:.1f}% extent</span>
              </div>
            </div>
            {month_table}
          </div>
        </details>""")

    # 3. Monthly Breakdown data (for JSON-based filtering in JS)
    monthly_records = []
    for ts, row in labels.iterrows():
        ext_val = extent.loc[ts, "extent_pct"] if ts in extent.index else None
        inv_val = extent.loc[ts, "invalid_pct"] if (ts in extent.index and "invalid_pct" in extent.columns) else 0.0
        
        monthly_records.append({
            "date": ts.strftime("%Y-%m-%d"),
            "display_date": ts.strftime("%b %Y"),
            "year": ts.year,
            "season": row["season"],
            "hy_year": int(row["hy_year"]) if not pd.isna(row["hy_year"]) else None,
            "extent_pct": round(float(ext_val), 2) if ext_val is not None else None,
            "invalid_pct": round(float(inv_val), 2)
        })

    svg_chart = _generate_svg_chart(extent, hydro_years, labels)
    seasonal_context_svg = _generate_seasonal_context_svg(extent)

    # 4. Generate HTML File
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
    
    :root {{
      --bg-main: #f8fafc;
      --bg-card: #ffffff;
      --border: #e2e8f0;
      --text-main: #334155;
      --text-muted: #64748b;
      
      --wet: #10b981;
      --wet-bg: rgba(16, 185, 129, 0.15);
      --dry: #f59e0b;
      --dry-bg: rgba(245, 158, 11, 0.15);
      --danger: #ef4444;
      --mid: #3b82f6;
      
      --accent: #2563eb;
    }}
    
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    
    body {{
      font-family: 'Roboto', sans-serif;
      background-color: var(--bg-main);
      color: var(--text-main);
      line-height: 1.5;
      padding: 24px;
    }}
    
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    
    header {{
      margin-bottom: 32px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 20px;
    }}
    
    h1 {{
      font-size: 2.2rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 8px;
    }}
    
    .subtitle {{
      color: var(--text-muted);
      font-size: 1.05rem;
      font-weight: 400;
    }}
    
    .grid {{
      display: grid;
      gap: 16px;
      margin-bottom: 32px;
    }}
    
    .grid.cards {{
      grid-template-columns: repeat(4, 1fr);
    }}
    
    .grid.two {{
      grid-template-columns: repeat(2, 1fr);
    }}
    
    .card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .card .value {{
      font-size: 2rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 4px;
    }}
    
    .card .label {{
      font-size: 0.85rem;
      color: var(--text-muted);
      line-height: 1.3;
    }}
    
    .report-text {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .report-text h2 {{
      margin-bottom: 16px;
      font-size: 1.2rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
    }}
    
    .report-text p {{
      margin-bottom: 12px;
    }}
    
    .report-text ul, .report-text ol {{
      margin-left: 20px;
      margin-bottom: 12px;
    }}
    
    .report-text li {{
      margin-bottom: 6px;
    }}
    
    .chart-container {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      position: relative;
      margin-top: 16px;
    }}
    
    .chart-svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    
    .chart-node {{
      transition: r 0.15s ease, opacity 0.15s ease;
      cursor: pointer;
    }}

    .chart-node:hover {{
      r: 8;
      opacity: 0.8;
    }}

    .chart-marker {{
      cursor: pointer;
    }}

    .chart-tooltip {{
      position: absolute;
      display: none;
      background-color: #172033;
      color: #ffffff;
      font-size: 0.8rem;
      padding: 6px 10px;
      border-radius: 6px;
      pointer-events: none;
      white-space: nowrap;
      transform: translate(-50%, -100%);
      z-index: 10;
      box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }}

    .legend-container {{
      display: flex;
      gap: 16px;
      justify-content: center;
      margin-top: 16px;
      font-size: 0.85rem;
    }}
    
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--text-muted);
    }}
    
    .legend-color {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
    }}
    
    .legend-circle {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}

    .legend-shape {{
      width: 14px;
      height: 14px;
      flex-shrink: 0;
    }}

    .year-cards-container {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 40px;
    }}
    
    .year-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      transition: border-color 0.2s ease;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .year-card[open] {{
      border-color: var(--accent);
    }}
    
    .year-header {{
      padding: 16px 20px;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      user-select: none;
      list-style: none;
    }}
    
    .year-header::-webkit-details-marker {{
      display: none;
    }}
    
    .year-title-group {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    
    .expand-icon {{
      font-size: 0.8rem;
      color: var(--text-muted);
      transition: transform 0.2s ease;
    }}
    
    .year-card[open] .expand-icon {{
      transform: rotate(90deg);
    }}
    
    .year-number {{
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-main);
    }}
    
    .year-dates {{
      font-size: 0.9rem;
      color: var(--text-muted);
      font-weight: 400;
    }}
    
    .year-meta-group {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    
    .summary-stat {{
      font-size: 0.9rem;
      color: var(--text-muted);
    }}
    
    .confidence-badge {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 4px;
      letter-spacing: 0.05em;
    }}
    
    .badge-high {{
      background-color: var(--wet-bg);
      color: var(--wet);
    }}
    
    .badge-medium {{
      background-color: var(--dry-bg);
      color: #b45309;
    }}
    
    .badge-low {{
      background-color: rgba(239, 68, 68, 0.15);
      color: var(--danger);
    }}
    
    .year-detail-content {{
      padding: 0 20px 20px 20px;
      border-top: 1px solid var(--border);
      background-color: #fafafa;
    }}
    
    .detail-kpis {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 16px;
      margin-bottom: 20px;
    }}
    
    .detail-kpi-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px;
    }}
    
    .detail-kpi-label {{
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      margin-bottom: 4px;
      display: block;
    }}
    
    .detail-kpi-value {{
      font-size: 1.15rem;
      font-weight: 600;
    }}
    
    .value-wet {{ color: var(--wet); }}
    .value-dry {{ color: var(--danger); }}
    .value-mid {{ color: var(--mid); }}
    
    .detail-kpi-sub {{
      font-size: 0.8rem;
      color: var(--text-muted);
      display: block;
      margin-top: 2px;
    }}
    
    .nested-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }}
    
    .nested-table th, .nested-table td {{
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    
    .nested-table th {{
      background-color: #f1f5f9;
      color: var(--text-main);
      font-weight: 600;
      font-size: 0.8rem;
    }}
    
    .season-badge {{
      font-size: 0.8rem;
      font-weight: 500;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    
    .season-wet {{
      background-color: var(--wet-bg);
      color: #047857;
    }}
    
    .season-dry {{
      background-color: var(--dry-bg);
      color: #b45309;
    }}
    
    .cell-marker {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    
    .marker-wet {{
      background-color: var(--wet);
      color: #ffffff;
    }}
    
    .marker-mid {{
      background-color: var(--mid);
      color: #ffffff;
    }}
    
    .marker-dry {{
      background-color: var(--danger);
      color: #ffffff;
    }}
    
    .filters-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
      align-items: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .filter-item {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    
    .filter-item label {{
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
    }}
    
    .filter-item select, .filter-item input {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 6px 12px;
      border-radius: 4px;
      font-family: inherit;
      outline: none;
    }}
    
    .filter-item select:focus, .filter-item input:focus {{
      border-color: var(--accent);
    }}
    
    .main-table-container {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .main-table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }}
    
    .main-table th, .main-table td {{
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }}
    
    .main-table th {{
      background-color: #f1f5f9;
      color: var(--text-main);
      font-weight: 600;
      font-size: 0.85rem;
    }}
    
    .main-table tbody tr:hover {{
      background-color: #f8fafc;
    }}
    
    @media (max-width: 900px) {{
      .grid.cards, .grid.two {{ grid-template-columns: 1fr; }}
      .detail-kpis {{ grid-template-columns: 1fr; }}
    }}
    
    @media print {{
      body {{ background: white; }}
      .filters-row {{ display: none; }}
      .card, .report-text, .year-card, .main-table-container {{ box-shadow: none; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{html.escape(title)}</h1>
      <p class="subtitle">Manager-ready summary of hydrological-year workflow based on remote-sensing water extent series.</p>
    </header>
    
    <main>
      <section class="grid cards">
        <div class="card"><div class="value">{n_years}</div><div class="label">hydrological years<br><small>{start_date} to {end_date}</small></div></div>
        <div class="card"><div class="value">{mean_amp:.1f}%</div><div class="label">mean annual amplitude<br><small>diff between peak and end dry</small></div></div>
        <div class="card"><div class="value">{mean_len:.1f}</div><div class="label">mean cycle length<br><small>months per hydro-year</small></div></div>
        <div class="card"><div class="value">{high_conf}</div><div class="label">high confidence years<br><small>out of {n_years} total years</small></div></div>
        <div class="card"><div class="value">{min_end:.1f}%</div><div class="label">lower water extent at end of dry season<br><small>minimum across all hydro-years</small></div></div>
        <div class="card"><div class="value">{max_peak:.1f}%</div><div class="label">higher water extent in wet season<br><small>maximum across all hydro-years</small></div></div>
        <div class="card"><div class="value">{mean_end:.1f}%</div><div class="label">average water extent at end of dry season<br><small>mean across all hydro-years</small></div></div>
        <div class="card"><div class="value">{avg_invalid:.1f}%</div><div class="label">average invalid/cloud cover<br><small>mean across {total_months} months of observations</small></div></div>
      </section>
      
      <section class="grid two">
        <div class="report-text">
          <h2>Executive Summary</h2>
          <p>This report details the seasonal dynamics of surface water extent derived from satellite observations. The timeseries has been analyzed to detect continuous hydrological years, isolating the natural wet and dry phases of the landscape.</p>
          <ul>
            <li><b>{n_years} total hydrological years</b> were successfully detected across {total_months} months of observations.</li>
            <li>The average cycle length is <b>{mean_len:.1f} months</b>.</li>
            <li><b>{high_conf} years ({round(high_conf/n_years*100) if n_years else 0}%)</b> are classified as high-confidence based on data availability and clear amplitude signals.</li>
          </ul>
        </div>
        <div class="report-text">
          <h2>Workflow</h2>
          <ol>
            <li>Load and gap-fill remote sensing water extent observations over the target period.</li>
            <li>Detect hydrological years by identifying localized peaks (Wet season) and subsequent minima (End Dry season).</li>
            <li>Calculate the Mid-Dry target month for each year to represent the transition period.</li>
            <li>Label all intermediate months based on their position within the defined hydrological years.</li>
            <li>Export visual summaries and underlying statistics.</li>
          </ol>
        </div>
      </section>

      <section class="report-text">
        <h2>Hydrological-Year Signal</h2>
        <p>The chart below displays the continuous water extent percentage over time. The background is shaded to indicate the assigned seasonal context (blue for Wet, red for Dry). Key points in each cycle are highlighted: Peak Wet (blue diamond, filled for high confidence), Mid-Dry (orange square), and End-Dry (red triangle, hydrological-year boundary). Click any marker or line point to see its exact value. The lower panel shows which hydrological year each month belongs to.</p>

        <div class="chart-container">
          {svg_chart}
          <div class="chart-tooltip" data-tooltip-for="hy-signal"></div>
          <div class="legend-container">
            <div class="legend-item"><div class="legend-color" style="background-color: var(--wet-bg);"></div> Wet Season</div>
            <div class="legend-item"><div class="legend-color" style="background-color: var(--dry-bg);"></div> Dry Season</div>
            <div class="legend-item"><div class="legend-color" style="background-color: #93c5fd; height: 2px;"></div> Monthly extent (raw)</div>
            <div class="legend-item"><div class="legend-color" style="background-color: var(--accent); height: 2px;"></div> 3-mo smoothed</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><polygon points="8,1 15,8 8,15 1,8" fill="#3b82f6" stroke="#3b82f6"/></svg> Peak Wet (high confidence)</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" fill="#f97316"/></svg> Mid Dry</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><polygon points="2,3 14,3 8,14" fill="#ef4444"/></svg> End Dry (HY boundary)</div>
          </div>
        </div>
      </section>

      <section class="report-text">
        <h2>Seasonal Context</h2>
        <p>Wet-season peaks and dry-season stress months vary by year, so the analysis avoids fixed calendar-month assumptions. This matters for persistent pools, where antecedent catchment response can shift the timing of water retention.</p>
        <div class="chart-container">
          {seasonal_context_svg}
        </div>
      </section>

      <div class="report-text" style="margin-bottom: 32px;">
        <h2>Yearly Cycle Details</h2>
        <p>Expand individual hydrological years to view monthly breakdowns and detailed statistics.</p>
        <div class="year-cards-container" style="margin-top: 16px;">
          {"".join(year_cards)}
        </div>
      </div>
      
      <div class="report-text">
        <h2>Raw Data Browser</h2>
        <p>Filter and explore the monthly extent data directly.</p>
        
        <div class="filters-row" style="margin-top: 16px;">
          <div class="filter-item">
            <label for="yearFilter">Filter by Year</label>
            <select id="yearFilter">
              <option value="all">All Years</option>
            </select>
          </div>
          <div class="filter-item">
            <label for="seasonFilter">Filter by Season</label>
            <select id="seasonFilter">
              <option value="all">All Seasons</option>
              <option value="Wet">Wet</option>
              <option value="Dry">Dry</option>
            </select>
          </div>
          <div class="filter-item">
            <label for="invalidFilter">Data Quality</label>
            <select id="invalidFilter">
              <option value="all">All Records</option>
              <option value="clean">Clean (≤ 10% Invalid)</option>
              <option value="warn">Warning (> 10% Invalid)</option>
            </select>
          </div>
        </div>
        
        <div class="main-table-container">
          <table class="main-table" id="dataTable">
            <thead>
              <tr>
                <th>Date</th>
                <th>Season</th>
                <th>Hydro Year</th>
                <th>Extent (%)</th>
                <th>Invalid (%)</th>
              </tr>
            </thead>
            <tbody>
              <!-- Populated by JS -->
            </tbody>
          </table>
        </div>
      </div>
    </main>
  </div>

  <script>
    // Data Injected from Python
    const chartData = {json.dumps(monthly_records)};
    
    document.addEventListener('DOMContentLoaded', () => {{
      // Click-to-reveal tooltips for chart markers/points
      document.querySelectorAll('.chart-container').forEach((container) => {{
        const tooltip = container.querySelector('.chart-tooltip');
        if (!tooltip) return;

        container.addEventListener('click', (evt) => {{
          const marker = evt.target.closest('.chart-marker');
          if (!marker) {{
            tooltip.style.display = 'none';
            return;
          }}
          const label = marker.getAttribute('data-label');
          if (!label) return;

          const containerRect = container.getBoundingClientRect();
          const markerRect = marker.getBoundingClientRect();
          tooltip.textContent = label;
          tooltip.style.left = (markerRect.left - containerRect.left + markerRect.width / 2) + 'px';
          tooltip.style.top = (markerRect.top - containerRect.top) + 'px';
          tooltip.style.display = 'block';
          evt.stopPropagation();
        }});
      }});

      document.addEventListener('click', (evt) => {{
        if (!evt.target.closest('.chart-container')) {{
          document.querySelectorAll('.chart-tooltip').forEach((t) => {{ t.style.display = 'none'; }});
        }}
      }});

      // Populate Year Dropdown
      const yearSelect = document.getElementById('yearFilter');
      const years = [...new Set(chartData.map(d => d.year))].sort((a,b) => b-a);
      years.forEach(y => {{
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        yearSelect.appendChild(opt);
      }});
      
      // Filtering Logic
      const tbody = document.querySelector('#dataTable tbody');
      
      function renderTable() {{
        const yFilter = yearSelect.value;
        const sFilter = document.getElementById('seasonFilter').value;
        const iFilter = document.getElementById('invalidFilter').value;
        
        let filtered = chartData;
        
        if (yFilter !== 'all') {{
          filtered = filtered.filter(d => d.year.toString() === yFilter);
        }}
        
        if (sFilter !== 'all') {{
          filtered = filtered.filter(d => d.season === sFilter);
        }}
        
        if (iFilter === 'clean') {{
          filtered = filtered.filter(d => d.invalid_pct <= 10.0);
        }} else if (iFilter === 'warn') {{
          filtered = filtered.filter(d => d.invalid_pct > 10.0);
        }}
        
        tbody.innerHTML = '';
        
        filtered.forEach(row => {{
          const tr = document.createElement('tr');
          
          let extDisplay = row.extent_pct !== null ? row.extent_pct.toFixed(2) + '%' : 'N/A';
          let invDisplay = row.invalid_pct.toFixed(2) + '%';
          
          let seasonBadge = '';
          if (row.season === 'Wet') {{
            seasonBadge = '<span class="season-badge season-wet">Wet</span>';
          }} else if (row.season === 'Dry') {{
            seasonBadge = '<span class="season-badge season-dry">Dry</span>';
          }} else {{
            seasonBadge = '<span class="season-badge" style="background:#e2e8f0; color:#475569;">Unassigned</span>';
          }}
          
          let hyDisplay = row.hy_year !== null ? 'HY ' + row.hy_year : '-';
          
          tr.innerHTML = `
            <td><strong>${{row.display_date}}</strong></td>
            <td>${{seasonBadge}}</td>
            <td>${{hyDisplay}}</td>
            <td>${{extDisplay}}</td>
            <td>${{invDisplay}}</td>
          `;
          tbody.appendChild(tr);
        }});
        
        if (filtered.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px; color:#64748b;">No records match the current filters.</td></tr>';
        }}
      }}
      
      // Bind Events
      document.getElementById('yearFilter').addEventListener('change', renderTable);
      document.getElementById('seasonFilter').addEventListener('change', renderTable);
      document.getElementById('invalidFilter').addEventListener('change', renderTable);
      
      // Initial Render
      renderTable();
    }});
  </script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_template)
        
    return output_path
