from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydroseason._catchment import CatchmentAnalysis


LOG_FLOOR = 0.02
PHASE_COLORS = {
    "recovery": "#d3e9d2",
    "wet": "#b9d9ef",
    "recession": "#f3e6c6",
    "dry": "#f1d7d4",
}
MARKERS = {
    "HY Peak": ("peak_month", "#2563eb", "circle"),
    "HY Mid Dry": ("temporal_mid_dry_month", "#f97316", "square"),
    "HY End Dry": ("trough_month", "#dc2626", "circle"),
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
        "margin": {"l": 50, "r": 50, "t": 35, "b": 138},
        "dragmode": "pan",
        "xaxis": {
            "title": "Date",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
            "rangeslider": {"visible": bool(rangeslider)},
        }
        "yaxis": {
            "title": "Water Extent (%)",
            "type": "linear",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
        },
        "legend": {
            "orientation": "h",
            "y": -0.06,
            "yanchor": "top",
            "x": 0.5,
            "xanchor": "center",
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
        },
        "legend2": {
            "orientation": "h",
            "y": -0.27,
            "yanchor": "top",
            "x": 0.5,
            "xanchor": "center",
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
        },
    }


def _config() -> dict[str, Any]:
    return {
        "responsive": True,
        "scrollZoom": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }


def _scale_meta(values: list[Any]) -> dict[str, Any]:
    return {
        "original_y": values,
        "log_floor": LOG_FLOOR,
        "log_safe_y": [
            max(value, LOG_FLOOR) if value is not None else None for value in values
        ],
    }


def _extent_trace(
    dates: list[str | None],
    values: list[Any],
    *,
    name: str,
    customdata: list[Any] | None = None,
    hovertemplate: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "scatter",
        "mode": "lines+markers",
        "name": name,
        "x": dates,
        "y": values,
        "line": {"color": "#0284c7", "width": 2},
        "marker": {"size": 4, "color": "#0284c7"},
        "customdata": values if customdata is None else customdata,
        "hovertemplate": hovertemplate
        or "Date: %{x}<br>Water Extent: %{customdata}%<extra></extra>",
        # Scale restoration is independent of the manager-facing hover payload.
        "meta": _scale_meta(values),
    }


def _marker_status_by_date(analysis: CatchmentAnalysis) -> dict[str, str]:
    rows = analysis.hydro_years if analysis.hydro_years is not None else pd.DataFrame()
    statuses: dict[str, list[str]] = {}
    for name, (column, _, _) in MARKERS.items():
        if column not in rows.columns:
            continue
        for value in rows[column]:
            date = _iso_date(value)
            if date is not None:
                statuses.setdefault(date, []).append(name)
    return {date: ", ".join(names) for date, names in statuses.items()}


def _monthly_hover_data(
    monthly: pd.DataFrame,
    dates: list[str | None],
    extent: list[Any],
    analysis: CatchmentAnalysis,
) -> list[list[Any]]:
    def values(column: str) -> list[Any]:
        if column not in monthly.columns:
            return [None] * len(monthly)
        return _clean_list(monthly[column])

    marker_statuses = _marker_status_by_date(analysis)
    return [
        [extent_value, reference, phase, hy_year, marker_statuses.get(date, "None")]
        for date, extent_value, reference, phase, hy_year in zip(
            dates,
            extent,
            values("reference_median_pct"),
            values("phase"),
            values("hy_year"),
        )
    ]


def _marker_traces(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> list[dict[str, Any]]:
    dates = _dates(monthly)
    monthly_values = {
        _iso_date(date): _clean_val(extent)
        for date, extent in zip(
            dates,
            monthly.get("extent_pct", pd.Series(index=monthly.index, dtype=float)),
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
                extent = monthly_values.get(date)
                x.append(date)
                y.append(extent)
                customdata.append([
                    _clean_val(row.get("hy_year")), date, extent,
                    _clean_val(row.get("confidence")), _clean_val(row.get("boundary_status")),
                ])
        traces.append({
            "type": "scatter", "mode": "markers", "name": name, "x": x, "y": y,
            "customdata": customdata,
            "hovertemplate": (
                "HY %{customdata[0]}<br>Date: %{customdata[1]}<br>"
                "Extent: %{customdata[2]}%<br>"
                "Confidence level: %{customdata[3]}<br>Boundary: %{customdata[4]}<extra></extra>"
            ),
            "marker": {
                "size": 8,
                "color": color,
                "symbol": symbol,
                "line": {"color": "#ffffff", "width": 1},
            },
            "meta": _scale_meta(y),
        })
    return traces


def _phase_shapes(
    monthly: pd.DataFrame,
    dates: list[pd.Timestamp],
    analysis: CatchmentAnalysis,
) -> list[dict[str, Any]]:
    phases = monthly.get("phase", pd.Series(index=monthly.index, dtype=object)).tolist()
    rows = getattr(analysis, "hydro_years", pd.DataFrame())
    trough_dates = set()
    if rows is not None and not rows.empty:
        trough_dates = {
            pd.Timestamp(value).to_period("M").to_timestamp()
            for value in rows.get("trough_month", pd.Series(dtype="datetime64[ns]")).dropna()
        }
    shapes: list[dict[str, Any]] = []
    start = 0
    while start < len(dates):
        phase = phases[start] if start < len(phases) else None
        end = start + 1
        while end < len(dates) and phases[end] == phase:
            end += 1
        if phase in PHASE_COLORS and pd.notna(dates[start]):
            boundary = dates[end] if end < len(dates) else dates[-1] + pd.DateOffset(months=1)
            phase_start = dates[start]
            if phase == "dry" and end < len(dates) and phases[end] == "recovery":
                prior_troughs = [value for value in trough_dates if value <= dates[end]]
                if prior_troughs:
                    prior_trough = max(prior_troughs)
                    if prior_trough == dates[end] - pd.DateOffset(months=1):
                        boundary = prior_trough
            if phase == "recovery":
                prior_troughs = [value for value in trough_dates if value <= phase_start]
                if prior_troughs:
                    prior_trough = max(prior_troughs)
                    if prior_trough >= phase_start - pd.DateOffset(months=1):
                        phase_start = prior_trough
            shapes.append({
                "name": f"phase:{phase}", "type": "rect", "xref": "x", "yref": "paper",
                "x0": _iso_date(phase_start), "x1": _iso_date(boundary), "y0": 0, "y1": 1,
                "fillcolor": PHASE_COLORS[phase], "opacity": 0.48, "line": {"width": 0},
                "layer": "below",
            })
        start = end
    return shapes


def _hydro_year_context(analysis: CatchmentAnalysis) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = getattr(analysis, "hydro_years", pd.DataFrame())
    if rows is None or rows.empty:
        return [], []

    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    seen_boundaries: set[str] = set()
    for _, row in rows.iterrows():
        start = _iso_date(row.get("hy_start"))
        end = _iso_date(row.get("hy_end"))
        trough = _iso_date(row.get("trough_month"))
        if trough is not None and trough not in seen_boundaries:
            seen_boundaries.add(trough)
            shapes.append({
                "name": f"HY trough {trough}",
                "type": "line",
                "xref": "x",
                "yref": "paper",
                "x0": trough,
                "x1": trough,
                "y0": 0,
                "y1": 1,
                "line": {"color": "#94a3b8", "dash": "dash", "width": 0.6},
                "layer": "below",
            })

        if start is not None and end is not None:
            midpoint = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
        elif trough is not None:
            midpoint = pd.Timestamp(trough)
        else:
            continue
        hy_year = _clean_val(row.get("hy_year"))
        annotations.append({
            "text": f"HY {hy_year}",
            "xref": "x",
            "yref": "paper",
            "x": _iso_date(midpoint),
            "y": 1.02,
            "showarrow": False,
            "yanchor": "bottom",
            "font": {"size": 10, "color": "#64748b"},
        })
    return shapes, annotations


def _phase_legend_traces() -> list[dict[str, Any]]:
    return [
        {
            "type": "scatter",
            "mode": "lines",
            "name": phase.title(),
            "legend": "legend2",
            "legendgroup": f"phase:{phase}",
            "x": [None],
            "y": [None],
            "line": {"color": color, "width": 10},
            "hoverinfo": "skip",
            "meta": {"phase_legend": phase},
        }
        for phase, color in PHASE_COLORS.items()
    ]


def timeline_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]:
    """Generate the manager timeline as an offline JSON-safe Plotly dict."""
    raw_dates = _dates(monthly)
    dates = [_iso_date(date) for date in raw_dates]
    extent_vals = _clean_list(monthly["extent_pct"])
    data: list[dict[str, Any]] = []

    data.append(
        _extent_trace(
            dates,
            extent_vals,
            name="Water Extent (%)",
            customdata=_monthly_hover_data(monthly, dates, extent_vals, analysis),
            hovertemplate=(
                "Date: %{x}<br>Water Extent: %{customdata[0]}%<br>"
                "Reference Median: %{customdata[1]}%<br>"
                "Phase: %{customdata[2]}<br>"
                "HY Year: %{customdata[3]}<br>Marker Status: %{customdata[4]}<extra></extra>"
            ),
        )
    )

    if "reference_median_pct" in monthly.columns:
        reference = _clean_list(monthly["reference_median_pct"])
        if any(value is not None for value in reference):
            data.append({
                "type": "scatter",
                "mode": "lines",
                "name": "Reference Median",
                "x": dates,
                "y": reference,
                "customdata": reference,
                "hovertemplate": (
                    "Date: %{x}<br>Reference Median: %{customdata}%<extra></extra>"
                ),
                "line": {"color": "#94a3b8", "dash": "dash", "width": 1.5},
                "visible": "legendonly",
                "meta": _scale_meta(reference),
            })
            median_baseline = float(np.nanmedian([value for value in reference if value is not None]))
            data.append({
                "type": "scatter",
                "mode": "lines",
                "name": "Median Baseline",
                "x": [dates[0], dates[-1]],
                "y": [median_baseline, median_baseline],
                "customdata": [median_baseline, median_baseline],
                "hovertemplate": "Median Baseline: %{customdata}<extra></extra>",
                "line": {"color": "#475569", "dash": "dot", "width": 1.5},
                "visible": "legendonly",
                "meta": _scale_meta([median_baseline, median_baseline]),
            })
    data.extend(_marker_traces(monthly, analysis))
    has_rainfall = "rainfall_mm" in monthly.columns and monthly["rainfall_mm"].notna().any()
    if has_rainfall:
        data.append({"type": "bar", "name": "Rainfall", "x": dates, "y": _clean_list(monthly["rainfall_mm"]),
                     "yaxis": "y2", "marker": {"color": "rgba(148, 163, 184, 0.4)"}})
    data.extend(_phase_legend_traces())

    layout = _base_layout(rangeslider=False)
    hydro_shapes, hydro_annotations = _hydro_year_context(analysis)
    layout["shapes"] = (
        _phase_shapes(monthly, raw_dates, analysis)
        + hydro_shapes
    )
    layout["annotations"] = hydro_annotations
    layout["margin"]["t"] = 52
    if has_rainfall:
        layout["yaxis2"] = {"title": "Rainfall (mm)", "type": "linear", "overlaying": "y", "side": "right", "showgrid": False, "zeroline": False}
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
        grouped = monthly.assign(_month=m_indices).groupby("_month")["extent_pct"]
        means = grouped.mean().reindex(months)
        stds = grouped.std().fillna(0.0).reindex(months).fillna(0.0)
        lower = (means - stds).clip(lower=0.0)
        upper = means + stds
        data.extend([
            {
                "type": "scatter", "mode": "lines", "name": "Mean - 1 std",
                "x": month_names, "y": _clean_list(lower), "showlegend": False,
                "line": {"width": 0}, "hoverinfo": "skip",
            },
            {
                "type": "scatter", "mode": "lines", "name": "Mean + 1 std",
                "x": month_names, "y": _clean_list(upper), "showlegend": False,
                "line": {"width": 0}, "fill": "tonexty",
                "fillcolor": "rgba(2, 132, 199, 0.16)", "hoverinfo": "skip",
            },
            {
                "type": "scatter", "mode": "lines+markers",
                "name": "Long-term monthly water extent (+/-1 std)",
                "x": month_names, "y": _clean_list(means),
                "customdata": [[_clean_val(mean), _clean_val(std)] for mean, std in zip(means, stds)],
                "hovertemplate": "Month: %{x}<br>Mean: %{customdata[0]}%<br>Std: %{customdata[1]}%<extra></extra>",
                "line": {"color": "#0284c7", "width": 2},
                "marker": {"size": 6, "color": "#0284c7"},
            },
        ])
        layout = {"paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc", "margin": {"l": 50, "r": 30, "t": 58, "b": 40}, "title": {"text": "Long-term monthly water extent (+/-1 std)", "x": 0.02, "xanchor": "left", "font": {"size": 13, "color": "#334155"}}, "xaxis": {"title": "Month", "showgrid": False}, "yaxis": {"title": "Mean Extent (%)", "showgrid": True, "gridcolor": "#e2e8f0"}}
    else:
        events = analysis.events.events
        if not events.empty and "duration_months" in events.columns:
            data.append({"type": "histogram", "name": "Event Duration (months)", "x": _clean_list(events["duration_months"]), "marker": {"color": "#0ea5e9"}})
            layout = {"paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc", "margin": {"l": 50, "r": 30, "t": 30, "b": 40}, "xaxis": {"title": "Duration (months)", "showgrid": True, "gridcolor": "#e2e8f0"}, "yaxis": {"title": "Count", "showgrid": True, "gridcolor": "#e2e8f0"}}
        else:
            data.append({"type": "bar", "x": [], "y": []})
            layout = {"paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc", "margin": {"l": 50, "r": 30, "t": 30, "b": 40}, "xaxis": {"title": "No Events"}, "yaxis": {"title": "Count"}}
    return {"data": data, "layout": layout, "config": {"responsive": True, "displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}}
