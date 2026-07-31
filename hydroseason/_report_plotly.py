from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydroseason._catchment import CatchmentAnalysis


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


def timeline_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]:
    """Generate light-theme plain-dict Plotly figure for monthly timeline."""
    dates = [d.strftime("%Y-%m-%d") if isinstance(d, (pd.Timestamp, pd.DatetimeIndex)) else str(d) for d in monthly.index]
    if "date" in monthly.columns:
        dates = [pd.to_datetime(d).strftime("%Y-%m-%d") for d in monthly["date"]]

    data: list[dict[str, Any]] = []

    # Reference median if available
    if "reference_median_pct" in monthly.columns:
        data.append({
            "type": "scatter",
            "mode": "lines",
            "name": "Reference Median",
            "x": dates,
            "y": _clean_list(monthly["reference_median_pct"]),
            "line": {"color": "#94a3b8", "dash": "dash", "width": 1.5},
        })

    # Main extent line
    extent_vals = _clean_list(monthly["extent_pct"])
    data.append({
        "type": "scatter",
        "mode": "lines+markers",
        "name": "Water Extent (%)",
        "x": dates,
        "y": extent_vals,
        "line": {"color": "#0284c7", "width": 2},
        "marker": {"size": 4, "color": "#0284c7"},
    })

    # Optional rainfall on secondary axis
    has_rainfall = "rainfall_mm" in monthly.columns and monthly["rainfall_mm"].notna().any()
    if has_rainfall:
        rain_vals = _clean_list(monthly["rainfall_mm"])
        data.append({
            "type": "bar",
            "name": "Rainfall",
            "x": dates,
            "y": rain_vals,
            "yaxis": "y2",
            "marker": {"color": "rgba(148, 163, 184, 0.4)"},
        })

    # Markers for Peak and Trough if route is seasonal/marginal
    if "is_hy_peak" in monthly.columns and monthly["is_hy_peak"].any():
        peak_mask = monthly["is_hy_peak"].fillna(False)
        peak_dates = [dates[i] for i, m in enumerate(peak_mask) if m]
        peak_y = [extent_vals[i] for i, m in enumerate(peak_mask) if m]
        data.append({
            "type": "scatter",
            "mode": "markers",
            "name": "HY Peak",
            "x": peak_dates,
            "y": peak_y,
            "marker": {"size": 10, "color": "#059669", "symbol": "triangle-up"},
        })

    if "is_hy_trough" in monthly.columns and monthly["is_hy_trough"].any():
        trough_mask = monthly["is_hy_trough"].fillna(False)
        trough_dates = [dates[i] for i, m in enumerate(trough_mask) if m]
        trough_y = [extent_vals[i] for i, m in enumerate(trough_mask) if m]
        data.append({
            "type": "scatter",
            "mode": "markers",
            "name": "HY Trough",
            "x": trough_dates,
            "y": trough_y,
            "marker": {"size": 10, "color": "#dc2626", "symbol": "triangle-down"},
        })

    layout: dict[str, Any] = {
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#f8fafc",
        "margin": {"l": 50, "r": 50, "t": 30, "b": 40},
        "xaxis": {
            "title": "Date",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
        },
        "yaxis": {
            "title": "Water Extent (%)",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
        },
        "legend": {
            "orientation": "h",
            "y": -0.2,
            "x": 0.5,
            "xanchor": "center",
        },
    }

    if has_rainfall:
        layout["yaxis2"] = {
            "title": "Rainfall (mm)",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "zeroline": False,
        }

    config = {
        "responsive": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }

    return {"data": data, "layout": layout, "config": config}


def secondary_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]:
    """Generate secondary light-theme plain-dict Plotly figure (climatology or event durations)."""
    data: list[dict[str, Any]] = []

    if analysis.route in ("per_year_detection", "climatological_fixed"):
        # Monthly extent climatology box/summary
        months = range(1, 13)
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        # Calculate monthly medians/means
        if "date" in monthly.columns:
            m_indices = pd.to_datetime(monthly["date"]).dt.month
        else:
            m_indices = monthly.index.month

        means = []
        for m in months:
            vals = monthly.loc[m_indices == m, "extent_pct"].dropna()
            means.append(_clean_val(vals.mean()) if len(vals) > 0 else None)

        data.append({
            "type": "bar",
            "name": "Mean Monthly Extent (%)",
            "x": month_names,
            "y": means,
            "marker": {"color": "#0284c7"},
        })

        layout = {
            "paper_bgcolor": "#ffffff",
            "plot_bgcolor": "#f8fafc",
            "margin": {"l": 50, "r": 30, "t": 30, "b": 40},
            "xaxis": {"title": "Month", "showgrid": False},
            "yaxis": {"title": "Mean Extent (%)", "showgrid": True, "gridcolor": "#e2e8f0"},
        }
    else:
        # Aseasonal: Event duration histogram / summary
        events = analysis.events.events
        if not events.empty and "duration_months" in events.columns:
            durations = _clean_list(events["duration_months"])
            data.append({
                "type": "histogram",
                "name": "Event Duration (months)",
                "x": durations,
                "marker": {"color": "#0ea5e9"},
            })
            layout = {
                "paper_bgcolor": "#ffffff",
                "plot_bgcolor": "#f8fafc",
                "margin": {"l": 50, "r": 30, "t": 30, "b": 40},
                "xaxis": {"title": "Duration (months)", "showgrid": True, "gridcolor": "#e2e8f0"},
                "yaxis": {"title": "Count", "showgrid": True, "gridcolor": "#e2e8f0"},
            }
        else:
            # Fallback empty
            data.append({
                "type": "bar",
                "x": [],
                "y": [],
            })
            layout = {
                "paper_bgcolor": "#ffffff",
                "plot_bgcolor": "#f8fafc",
                "margin": {"l": 50, "r": 30, "t": 30, "b": 40},
                "xaxis": {"title": "No Events"},
                "yaxis": {"title": "Count"},
            }

    config = {
        "responsive": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }

    return {"data": data, "layout": layout, "config": config}
