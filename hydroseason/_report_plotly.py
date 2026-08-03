from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydroseason._catchment import CatchmentAnalysis


LOG_FLOOR = 0.02
PHASE_COLORS = {
    "recovery": "#38bdf8",
    "wet": "#22c55e",
    "recession": "#f59e0b",
    "dry": "#f97316",
}
MARKERS = {
    "HY Peak": ("peak_month", "#059669", "triangle-up"),
    "HY Mid Dry": ("temporal_mid_dry_month", "#7c3aed", "diamond"),
    "HY End Dry": ("trough_month", "#dc2626", "triangle-down"),
}


def _clean_val(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if pd.isna(v):
        return None
    return v


def _clean_list(seq: Any) -> list[Any]:
    return [_clean_val(x) for x in seq]


def _dates(monthly: pd.DataFrame) -> list[pd.Timestamp]:
    source = monthly["date"] if "date" in monthly.columns else monthly.index
    return pd.to_datetime(source, errors="coerce").tolist()


def _iso_date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _base_layout(*, rangeslider: bool) -> dict[str, Any]:
    return {
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#f8fafc",
        "margin": {"l": 50, "r": 50, "t": 30, "b": 40},
        "xaxis": {
            "title": "Date",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
            "rangeslider": {"visible": rangeslider},
        },
        "yaxis": {
            "title": "Water Extent (%)",
            "type": "linear",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
        },
        "legend": {"orientation": "h", "y": -0.2, "x": 0.5, "xanchor": "center"},
    }


def _config() -> dict[str, Any]:
    return {
        "responsive": True,
        "scrollZoom": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }


def _extent_trace(dates: list[str], values: list[Any], *, name: str) -> dict[str, Any]:
    log_safe = [max(value, LOG_FLOOR) if value is not None else None for value in values]
    return {
        "type": "scatter",
        "mode": "lines+markers",
        "name": name,
        "x": dates,
        "y": values,
        "line": {"color": "#0284c7", "width": 2},
        "marker": {"size": 4, "color": "#0284c7"},
        "customdata": values,
        "hovertemplate": "Date: %{x}<br>Water Extent: %{customdata}%<extra></extra>",
        # The HTML mode toggle swaps y with log_safe_y; hover reads original customdata.
        "meta": {"log_floor": LOG_FLOOR, "log_safe_y": log_safe},
    }


def _marker_traces(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> list[dict[str, Any]]:
    dates = _dates(monthly)
    monthly_values = {
        _iso_date(date): (_clean_val(extent), _clean_val(invalid))
        for date, extent, invalid in zip(
            dates,
            monthly.get("extent_pct", pd.Series(index=monthly.index, dtype=float)),
            monthly.get("invalid_pct", pd.Series(index=monthly.index, dtype=float)),
        )
        if _iso_date(date) is not None
    }
    rows = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    traces: list[dict[str, Any]] = []
    for name, (column, color, symbol) in MARKERS.items():
        x: list[str] = []
        y: list[Any] = []
        customdata: list[list[Any]] = []
        if column in rows.columns:
            for _, row in rows.iterrows():
                date = _iso_date(row[column])
                if date is None:
                    continue
                extent, invalid = monthly_values.get(date, (None, None))
                x.append(date)
                y.append(extent)
                customdata.append([
                    _clean_val(row.get("hy_year")), date, extent, invalid,
                    _clean_val(row.get("confidence")), _clean_val(row.get("boundary_status")),
                ])
        traces.append({
            "type": "scatter", "mode": "markers", "name": name, "x": x, "y": y,
            "customdata": customdata,
            "hovertemplate": (
                "HY %{customdata[0]}<br>Date: %{customdata[1]}<br>"
                "Extent: %{customdata[2]}%<br>Invalid: %{customdata[3]}%<br>"
                "Confidence: %{customdata[4]}<br>Boundary: %{customdata[5]}<extra></extra>"
            ),
            "marker": {"size": 10, "color": color, "symbol": symbol},
        })
    return traces


def _phase_shapes(monthly: pd.DataFrame, dates: list[pd.Timestamp]) -> list[dict[str, Any]]:
    phases = monthly.get("phase", pd.Series(index=monthly.index, dtype=object)).tolist()
    shapes: list[dict[str, Any]] = []
    start = 0
    while start < len(dates):
        phase = phases[start] if start < len(phases) else None
        end = start + 1
        while end < len(dates) and phases[end] == phase:
            end += 1
        if phase in PHASE_COLORS and pd.notna(dates[start]):
            boundary = dates[end] if end < len(dates) else dates[-1] + pd.DateOffset(months=1)
            shapes.append({
                "name": f"phase:{phase}", "type": "rect", "xref": "x", "yref": "paper",
                "x0": _iso_date(dates[start]), "x1": _iso_date(boundary), "y0": 0, "y1": 1,
                "fillcolor": PHASE_COLORS[phase], "opacity": 0.12, "line": {"width": 0},
            })
        start = end
    return shapes


def timeline_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]:
    """Generate the manager timeline as an offline JSON-safe Plotly dict."""
    raw_dates = _dates(monthly)
    dates = [_iso_date(date) for date in raw_dates]
    extent_vals = _clean_list(monthly["extent_pct"])
    data: list[dict[str, Any]] = []

    if "reference_median_pct" in monthly.columns:
        reference = _clean_list(monthly["reference_median_pct"])
        if any(value is not None for value in reference):
            data.append({"type": "scatter", "mode": "lines", "name": "Reference Median", "x": dates,
                         "y": reference, "line": {"color": "#94a3b8", "dash": "dash", "width": 1.5}})
    data.append(_extent_trace(dates, extent_vals, name="Water Extent (%)"))

    has_invalid = "invalid_pct" in monthly.columns and any(
        value is not None for value in _clean_list(monthly["invalid_pct"])
    )
    if has_invalid:
        data.append({"type": "scatter", "mode": "lines", "name": "Invalid Coverage (%)", "x": dates,
                     "y": _clean_list(monthly["invalid_pct"]), "yaxis": "y2",
                     "line": {"color": "#d97706", "width": 1.5}})

    has_rainfall = "rainfall_mm" in monthly.columns and monthly["rainfall_mm"].notna().any()
    if has_rainfall:
        data.append({"type": "bar", "name": "Rainfall", "x": dates, "y": _clean_list(monthly["rainfall_mm"]),
                     "yaxis": "y3" if has_invalid else "y2", "marker": {"color": "rgba(148, 163, 184, 0.4)"}})
    data.extend(_marker_traces(monthly, analysis))

    layout = _base_layout(rangeslider=True)
    layout["shapes"] = _phase_shapes(monthly, raw_dates)
    if has_invalid:
        layout["yaxis2"] = {"title": "Invalid Coverage (%)", "type": "linear", "overlaying": "y", "side": "right", "showgrid": False, "zeroline": False}
    if has_rainfall:
        rainfall_axis = "yaxis3" if has_invalid else "yaxis2"
        layout[rainfall_axis] = {"title": "Rainfall (mm)", "type": "linear", "overlaying": "y", "side": "right", "showgrid": False, "zeroline": False}
    return {"data": data, "layout": layout, "config": _config()}


def hydro_year_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]:
    """Generate a hydrological-year interval view on the monthly date domain."""
    raw_dates = _dates(monthly)
    dates = [_iso_date(date) for date in raw_dates]
    data = [_extent_trace(dates, _clean_list(monthly["extent_pct"]), name="Hydrological-year extent")]
    data.extend(_marker_traces(monthly, analysis))
    layout = _base_layout(rangeslider=False)
    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for _, row in analysis.hydro_years.iterrows():
        start, end = _iso_date(row.get("hy_start")), _iso_date(row.get("hy_end"))
        if start is None or end is None:
            continue
        label = f"HY {row.get('hy_year')}"
        shapes.append({"name": label, "type": "rect", "xref": "x", "yref": "paper", "x0": start, "x1": end,
                       "y0": 0, "y1": 1, "fillcolor": "#64748b", "opacity": 0.08, "line": {"width": 0}})
        midpoint = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
        annotations.append({"text": label, "xref": "x", "yref": "paper", "x": _iso_date(midpoint), "y": 1,
                            "showarrow": False, "yanchor": "bottom", "font": {"size": 10, "color": "#475569"}})
    layout["shapes"] = shapes
    layout["annotations"] = annotations
    return {"data": data, "layout": layout, "config": _config()}


def secondary_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]:
    """Generate secondary light-theme plain-dict Plotly figure (climatology or event durations)."""
    data: list[dict[str, Any]] = []

    if analysis.route in ("per_year_detection", "climatological_fixed"):
        months = range(1, 13)
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        m_indices = pd.to_datetime(monthly["date"]).dt.month if "date" in monthly.columns else monthly.index.month
        means = [_clean_val(monthly.loc[m_indices == month, "extent_pct"].dropna().mean()) if not monthly.loc[m_indices == month, "extent_pct"].dropna().empty else None for month in months]
        data.append({"type": "bar", "name": "Mean Monthly Extent (%)", "x": month_names, "y": means, "marker": {"color": "#0284c7"}})
        layout = {"paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc", "margin": {"l": 50, "r": 30, "t": 30, "b": 40}, "xaxis": {"title": "Month", "showgrid": False}, "yaxis": {"title": "Mean Extent (%)", "showgrid": True, "gridcolor": "#e2e8f0"}}
    else:
        events = analysis.events.events
        if not events.empty and "duration_months" in events.columns:
            data.append({"type": "histogram", "name": "Event Duration (months)", "x": _clean_list(events["duration_months"]), "marker": {"color": "#0ea5e9"}})
            layout = {"paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc", "margin": {"l": 50, "r": 30, "t": 30, "b": 40}, "xaxis": {"title": "Duration (months)", "showgrid": True, "gridcolor": "#e2e8f0"}, "yaxis": {"title": "Count", "showgrid": True, "gridcolor": "#e2e8f0"}}
        else:
            data.append({"type": "bar", "x": [], "y": []})
            layout = {"paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc", "margin": {"l": 50, "r": 30, "t": 30, "b": 40}, "xaxis": {"title": "No Events"}, "yaxis": {"title": "Count"}}
    return {"data": data, "layout": layout, "config": {"responsive": True, "displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}}
