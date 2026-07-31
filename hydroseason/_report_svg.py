"""SVG chart builders for the HTML report. Pure string generation, no I/O."""

from __future__ import annotations

import html

import numpy as np
import pandas as pd


def generate_svg_chart(extent_df: pd.DataFrame, hy_df: pd.DataFrame, labels_df: pd.DataFrame) -> str:
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


def generate_seasonal_context_svg(extent_df: pd.DataFrame) -> str:
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


__all__ = ["generate_svg_chart", "generate_seasonal_context_svg"]
