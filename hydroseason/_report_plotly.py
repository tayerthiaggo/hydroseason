from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydroseason._catchment import CatchmentAnalysis


LOG_FLOOR = 0.02
PHASE_COLORS = {
    "rising": "#d3e9d2",
    "receding": "#f3e6c6",
}
MARKERS = {
    "HY Peak": ("peak_month", "#2563eb", "circle"),
    "HY Mid Dry": ("temporal_mid_dry_month", "#f97316", "square"),
    "HY End Dry": ("trough_month", "#dc2626", "circle"),
}
HOVER_TEMPLATE = (
    "HY %{customdata[0]}<br>Date: %{customdata[1]}<br>"
    "Extent: %{customdata[2]:.2f}%<br>Invalid: %{customdata[3]:.2f}%<br>"
    "Confidence: %{customdata[4]}<br>Status: %{customdata[5]}<extra></extra>"
)


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
    # Axis titles are {"text": ...} objects, not bare strings, throughout this
    # module: the vendored Plotly.js build silently drops a bare-string axis
    # title (no error, no fallback -- the axis just renders untitled), so
    # every axis dict below follows this form even where it looks verbose.
    return {
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#f8fafc",
        "margin": {"l": 50, "r": 50, "t": 35, "b": 138},
        "dragmode": "pan",
        "xaxis": {
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
            "rangeslider": {"visible": bool(rangeslider)},
        },
        "yaxis": {
            "title": {"text": "Water Extent (%)"},
            "type": "linear",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
            "rangemode": "tozero",
        },
        "legend": {
            "orientation": "h",
            "y": -0.05,
            "yanchor": "top",
            "x": 0.5,
            "xanchor": "center",
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
        },
        "legend2": {
            "orientation": "h",
            "y": -0.15,
            "yanchor": "top",
            "x": 0.5,
            "xanchor": "center",
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
        },
        "legend3": {
            "orientation": "h",
            "y": -0.25,
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
    legend: str = "legend2",
) -> dict[str, Any]:
    return {
        "type": "scatter",
        "mode": "lines+markers",
        "name": name,
        "legend": legend,
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
    marker_status = {
        "HY Peak": "peak",
        "HY Mid Dry": "mid-dry",
        "HY End Dry": "end-dry",
    }
    for name, (column, _, _) in MARKERS.items():
        if column not in rows.columns:
            continue
        for value in rows[column]:
            date = _iso_date(value)
            if date is not None:
                statuses.setdefault(date, []).append(marker_status[name])
    return {date: names[0] for date, names in statuses.items()}


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
    phase_aliases = {
        "recovery": "rising",
        "wet": "rising",
        "rising": "rising",
        "recession": "receding",
        "dry": "receding",
        "receding": "receding",
    }
    invalid = values("invalid_pct")
    confidence = values("confidence")
    return [
        [
            hy_year,
            date,
            extent_value,
            invalid_value,
            confidence_value,
            marker_statuses.get(date, phase_aliases.get(str(phase).lower(), "N/A")),
        ]
        for date, extent_value, invalid_value, confidence_value, phase, hy_year in zip(
            dates,
            extent,
            invalid,
            confidence,
            values("phase"),
            values("hy_year"),
        )
    ]


def _is_imposed(analysis: CatchmentAnalysis) -> bool:
    """Whether annual boundaries were imposed from climatology, not detected.

    Imposed and detected boundaries are drawn on the same axes so catchments
    stay comparable, but they are not the same kind of claim: an imposed window
    is one average phase applied to every year, and rendering it identically to
    a per-year detection would erase the distinction the regime gate exists to
    make. Read from ``boundary_basis`` on the rows themselves rather than from
    the route name, so the provenance travels with the data.
    """
    rows = getattr(analysis, "hydro_years", pd.DataFrame())
    if rows is None or rows.empty or "boundary_basis" not in rows.columns:
        return False
    return bool((rows["boundary_basis"] == "imposed_fixed_window").any())


def _marker_traces(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> list[dict[str, Any]]:
    dates = [_iso_date(date) for date in _dates(monthly)]
    imposed = _is_imposed(analysis)
    monthly_hover = _monthly_hover_data(
        monthly,
        dates,
        _clean_list(monthly.get("extent_pct", pd.Series(index=monthly.index, dtype=float))),
        analysis,
    )
    monthly_points = {
        payload[1]: payload for payload in monthly_hover if payload[1] is not None
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
                point = monthly_points.get(date)
                extent = point[2] if point is not None else None
                x.append(date)
                y.append(extent)
                customdata.append([
                    _clean_val(row.get("hy_year")), date, extent,
                    point[3] if point is not None else None,
                    point[4] if point is not None else _clean_val(row.get("confidence")),
                    {"HY Peak": "peak", "HY Mid Dry": "mid-dry", "HY End Dry": "end-dry"}[name],
                ])
        marker = {
            "size": 8,
            "color": color,
            "symbol": symbol,
            "line": {"color": "#ffffff", "width": 1},
        }
        traces.append({
            "type": "scatter", "mode": "markers",
            "name": f"{name} (imposed)" if imposed else name,
            "legend": "legend",
            "x": x, "y": y,
            "customdata": customdata,
            "hovertemplate": HOVER_TEMPLATE,
            "marker": marker,
            "meta": _scale_meta(y),
        })
    return traces


PHASE_LABELS = {
    "recovery": "Rising",
    "rising": "Rising",
    "recession": "Receding",
    "receding": "Receding",
}


def _phase_shapes(
    monthly: pd.DataFrame,
    dates: list[pd.Timestamp],
    analysis: CatchmentAnalysis,
) -> list[dict[str, Any]]:
    active = _active_phases(monthly, analysis)
    if not active:
        return []

    opacity = 0.28 if _is_imposed(analysis) else 0.48
    shapes: list[dict[str, Any]] = []

    hydro_years = getattr(analysis, "hydro_years", pd.DataFrame())
    if hydro_years is not None and not hydro_years.empty:
        prev_trough: pd.Timestamp | None = None
        for _, row in hydro_years.sort_values("hy_year").iterrows():
            start_val = row.get("hy_start")
            peak_val = row.get("peak_month")
            trough_val = row.get("trough_month") or row.get("hy_end")

            start_ts = pd.Timestamp(start_val) if pd.notna(start_val) else None
            peak_ts = pd.Timestamp(peak_val) if pd.notna(peak_val) else None
            trough_ts = pd.Timestamp(trough_val) if pd.notna(trough_val) else None

            rising_start = prev_trough if prev_trough is not None else start_ts

            if rising_start is not None and peak_ts is not None and rising_start < peak_ts:
                shapes.append({
                    "name": "phase:rising",
                    "type": "rect",
                    "xref": "x",
                    "yref": "paper",
                    "x0": _iso_date(rising_start),
                    "x1": _iso_date(peak_ts),
                    "y0": 0,
                    "y1": 1,
                    "fillcolor": PHASE_COLORS["rising"],
                    "opacity": opacity,
                    "line": {"width": 0},
                    "layer": "below",
                })

            if peak_ts is not None and trough_ts is not None and peak_ts < trough_ts:
                shapes.append({
                    "name": "phase:receding",
                    "type": "rect",
                    "xref": "x",
                    "yref": "paper",
                    "x0": _iso_date(peak_ts),
                    "x1": _iso_date(trough_ts),
                    "y0": 0,
                    "y1": 1,
                    "fillcolor": PHASE_COLORS["receding"],
                    "opacity": opacity,
                    "line": {"width": 0},
                    "layer": "below",
                })

            if trough_ts is not None:
                prev_trough = trough_ts
        return shapes

    return []


def _hydro_year_context(analysis: CatchmentAnalysis) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = getattr(analysis, "hydro_years", pd.DataFrame())
    if rows is None or rows.empty:
        return [], []

    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    seen_boundaries: set[str] = set()

    def add_boundary(date: str | None, label: str) -> None:
        # A cycle boundary is only drawn once, whichever year references it
        # first: consecutive years share a boundary, and on a dashed grey line
        # a duplicate is invisible but doubles the rendered opacity.
        if date is None or date in seen_boundaries:
            return
        seen_boundaries.add(date)
        shapes.append({
            "name": f"HY {label} {date}",
            "type": "line",
            "xref": "x",
            "yref": "paper",
            "x0": date,
            "x1": date,
            "y0": 0,
            "y1": 1,
            "line": {"color": "#94a3b8", "dash": "dash", "width": 0.6},
            "layer": "below",
        })

    prev_trough: pd.Timestamp | None = None
    for _, row in rows.iterrows():
        start = _iso_date(row.get("hy_start"))
        end = _iso_date(row.get("hy_end"))
        trough = _iso_date(row.get("trough_month"))
        # A year's start is one month after the previous year's trough, so
        # both lines mark the same real-world boundary -- draw only the
        # trough line there. Draw the start line only when there is no
        # previous trough to anchor it (record-start or post-gap year),
        # otherwise it renders with no left-hand edge at all.
        start_ts = pd.Timestamp(start) if start is not None else None
        anchored = (
            prev_trough is not None
            and start_ts is not None
            and start_ts == prev_trough + pd.DateOffset(months=1)
        )
        if not anchored:
            add_boundary(start, "start")
        add_boundary(trough, "trough")
        if trough is not None:
            prev_trough = pd.Timestamp(trough)

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


def _active_phases(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> list[str]:
    hydro_years = getattr(analysis, "hydro_years", pd.DataFrame())
    if hydro_years is not None and not hydro_years.empty:
        return ["rising", "receding"]
    if "phase" in monthly.columns:
        present = set(monthly["phase"].dropna().unique()) - {"unspecified"}
        if {"recovery", "wet", "rising"} & present or {"recession", "dry", "receding"} & present:
            return ["rising", "receding"]
    return []


def _phase_legend_traces(phases: list[str] | None = None) -> list[dict[str, Any]]:
    if phases is None:
        phases = list(PHASE_COLORS.keys())
    return [
        {
            "type": "scatter",
            "mode": "lines",
            "name": PHASE_LABELS.get(phase, phase.title()),
            "legend": "legend3",
            "x": [None],
            "y": [None],
            "line": {"color": PHASE_COLORS.get(phase, "#94a3b8"), "width": 10},
            "showlegend": True,
            "hoverinfo": "none",
            "meta": {"phase_legend": phase},
        }
        for phase in phases
        if phase in PHASE_COLORS
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
            legend="legend2",
            customdata=_monthly_hover_data(monthly, dates, extent_vals, analysis),
            hovertemplate=HOVER_TEMPLATE,
        )
    )

    extent_series = pd.Series(
        monthly["extent_pct"].to_numpy(dtype=float) if "extent_pct" in monthly.columns else [],
        dtype=float,
    )
    if not extent_series.empty:
        rolling_3m = extent_series.rolling(window=3, min_periods=1, center=True).mean()
        rolling_3m_vals = _clean_list(rolling_3m)
        data.append({
            "type": "scatter",
            "mode": "lines",
            "name": "3-Month Rolling Avg",
            "legend": "legend2",
            "x": dates,
            "y": rolling_3m_vals,
            "customdata": rolling_3m_vals,
            "line": {"color": "#0f766e", "width": 2, "dash": "dash"},
            "visible": "legendonly",
            "hovertemplate": "Date: %{x}<br>3-Month Avg Extent: %{customdata:.2f}%<extra></extra>",
            "meta": _scale_meta(rolling_3m_vals),
        })

    if "reference_median_pct" in monthly.columns:
        reference = _clean_list(monthly["reference_median_pct"])
        if any(value is not None for value in reference):
            data.append({
                "type": "scatter",
                "mode": "lines",
                "name": "Reference Median",
                "legend": "legend2",
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
                "legend": "legend2",
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
        data.append({"type": "bar", "name": "Rainfall", "legend": "legend2", "x": dates, "y": _clean_list(monthly["rainfall_mm"]),
                     "yaxis": "y2", "marker": {"color": "rgba(148, 163, 184, 0.4)"}})
    data.extend(_phase_legend_traces(_active_phases(monthly, analysis)))

    layout = _base_layout(rangeslider=False)
    hydro_shapes, hydro_annotations = _hydro_year_context(analysis)
    layout["shapes"] = (
        _phase_shapes(monthly, raw_dates, analysis)
        + hydro_shapes
    )
    layout["annotations"] = hydro_annotations
    layout["margin"]["t"] = 52
    if has_rainfall:
        layout["yaxis2"] = {
            "title": {"text": "Rainfall (mm)"},
            "type": "linear",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "zeroline": False,
            "rangemode": "tozero",
        }
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


def _secondary_config() -> dict[str, Any]:
    return {
        "responsive": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }


def secondary_figure(monthly: pd.DataFrame, analysis: CatchmentAnalysis) -> dict[str, Any]:
    """Generate the long-term monthly water-extent climatology.

    Rendered for every catchment regardless of route. Averaging each calendar
    month over the record is a description of the observations, not a claim
    that a reproducible annual cycle exists -- and where none does, a flat or
    ragged profile with wide bands *is* the evidence for that, which a reader
    can only weigh if it is drawn. Routing this panel on ``analysis.route``
    previously withheld it from exactly the catchments whose seasonality was
    most in question, and substituted an event histogram whose axes answer an
    unrelated question under a "Seasonal Context" heading.
    """
    months = range(1, 13)
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    m_indices = pd.to_datetime(monthly["date"]).dt.month if "date" in monthly.columns else monthly.index.month
    grouped = monthly.assign(_month=m_indices).groupby("_month")["extent_pct"]
    means = grouped.mean().reindex(months)
    stds = grouped.std().fillna(0.0).reindex(months).fillna(0.0)
    lower = (means - stds).clip(lower=0.0)
    upper = means + stds
    data: list[dict[str, Any]] = [
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
    ]
    layout = {"paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc", "margin": {"l": 50, "r": 30, "t": 58, "b": 40}, "title": {"text": "Long-term monthly water extent (+/-1 std)", "x": 0.02, "xanchor": "left", "font": {"size": 13, "color": "#334155"}}, "xaxis": {"title": {"text": "Month"}, "showgrid": False}, "yaxis": {"title": {"text": "Mean Extent (%)"}, "showgrid": True, "gridcolor": "#e2e8f0", "rangemode": "tozero"}}
    return {"data": data, "layout": layout, "config": _secondary_config()}


def event_duration_figure(analysis: CatchmentAnalysis) -> dict[str, Any] | None:
    """Generate a one-bar-per-event duration chart, or None when there are none.

    A histogram bins values as though they were samples from a continuous
    distribution. Wet events are not that: a record can hold as few as five of
    them, unevenly spaced across twenty years (Lachlan: 2010, 2011, 2012, 2016,
    2021), so auto-binning scatters them across mostly-empty bins that read as
    noise rather than a shape. Charting one bar per actual event instead, in
    the order it occurred, shows what is actually there: how long each event
    lasted and how the events are spaced through the record -- the thing a
    duration histogram cannot show at all.

    This is its own panel rather than an alternative to the climatology: the
    two answer different questions and a catchment may need both. Returning
    None (instead of an empty-axes placeholder) lets the caller omit the
    section entirely rather than render a chart with nothing in it.
    """
    events = analysis.events.events
    if events.empty or "duration_months" not in events.columns:
        return None
    starts = pd.to_datetime(events["start"])
    ends = pd.to_datetime(events["end"])
    peak_extent = events.get("peak_extent_pct", pd.Series(index=events.index, dtype=float))
    magnitude = events.get("magnitude_pp_months", pd.Series(index=events.index, dtype=float))
    customdata = [
        [start.strftime("%b %Y"), end.strftime("%b %Y"), _clean_val(peak), _clean_val(mag)]
        for start, end, peak, mag in zip(starts, ends, peak_extent, magnitude)
    ]
    return {
        "data": [{
            "type": "bar",
            "name": "Wet event duration",
            "x": [start.strftime("%b %Y") for start in starts],
            "y": _clean_list(events["duration_months"]),
            "customdata": customdata,
            "hovertemplate": (
                "Event: %{customdata[0]} to %{customdata[1]}<br>"
                "Duration: %{y} months<br>"
                "Peak extent: %{customdata[2]}%<br>"
                "Magnitude: %{customdata[3]} pp-months<extra></extra>"
            ),
            "marker": {"color": "#0ea5e9"},
        }],
        "layout": {
            "paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc",
            "margin": {"l": 50, "r": 30, "t": 30, "b": 60},
            "xaxis": {"title": {"text": "Event start"}, "type": "category", "showgrid": False},
            "yaxis": {"title": {"text": "Duration (months)"}, "showgrid": True, "gridcolor": "#e2e8f0"},
        },
        "config": _secondary_config(),
    }


def low_spell_duration_figure(analysis: CatchmentAnalysis) -> dict[str, Any] | None:
    """Generate a one-bar-per-spell duration chart, or None when there are none.

    Mirrors ``event_duration_figure`` for the same reason: a low-extent spell
    count can be small and unevenly spaced, so one bar per actual spell (in
    the order it occurred) is legible where a histogram would not be.
    """
    low_spells = analysis.events.low_spells
    if low_spells.empty or "duration_months" not in low_spells.columns:
        return None
    starts = pd.to_datetime(low_spells["start"])
    ends = pd.to_datetime(low_spells["end"])
    min_extent = low_spells.get("min_extent_pct", pd.Series(index=low_spells.index, dtype=float))
    customdata = [
        [start.strftime("%b %Y"), end.strftime("%b %Y"), _clean_val(minimum)]
        for start, end, minimum in zip(starts, ends, min_extent)
    ]
    return {
        "data": [{
            "type": "bar",
            "name": "Low-extent spell duration",
            "x": [start.strftime("%b %Y") for start in starts],
            "y": _clean_list(low_spells["duration_months"]),
            "customdata": customdata,
            "hovertemplate": (
                "Spell: %{customdata[0]} to %{customdata[1]}<br>"
                "Duration: %{y} months<br>"
                "Lowest extent: %{customdata[2]}%<extra></extra>"
            ),
            "marker": {"color": "#f97316"},
        }],
        "layout": {
            "paper_bgcolor": "#ffffff", "plot_bgcolor": "#f8fafc",
            "margin": {"l": 50, "r": 30, "t": 30, "b": 60},
            "xaxis": {"title": {"text": "Spell start"}, "type": "category", "showgrid": False},
            "yaxis": {"title": {"text": "Duration (months)"}, "showgrid": True, "gridcolor": "#e2e8f0"},
        },
        "config": _secondary_config(),
    }


def rainfall_context_figure(monthly: pd.DataFrame) -> dict[str, Any] | None:
    """Generate paired monthly climatology figure for rainfall and extent.

    Returns None if rainfall data is not present; otherwise returns a strict-JSON
    serializable Plotly figure dict with rainfall (bar) and extent (scatter) traces.
    """
    if "rainfall_mm" not in monthly or not monthly["rainfall_mm"].notna().any():
        return None

    month_number = pd.to_datetime(monthly["date"]).dt.month
    labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    rain_means = [
        _clean_val(monthly.loc[month_number == month, "rainfall_mm"].mean())
        for month in range(1, 13)
    ]
    extent_means = [
        _clean_val(monthly.loc[month_number == month, "extent_pct"].mean())
        for month in range(1, 13)
    ]

    return {
        "data": [
            {
                "type": "bar",
                "name": "Mean Monthly Rainfall (mm)",
                "x": labels,
                "y": rain_means,
                "yaxis": "y2",
                "marker": {"color": "rgba(16, 185, 129, 0.42)"},
            },
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": "Mean Monthly Extent (%)",
                "x": labels,
                "y": extent_means,
                "line": {"color": "#0284c7", "width": 2},
                "marker": {"color": "#0284c7", "size": 6},
            },
        ],
        "layout": {
            "paper_bgcolor": "#ffffff",
            "plot_bgcolor": "#f8fafc",
            "margin": {"l": 50, "r": 50, "t": 20, "b": 40},
            "xaxis": {"title": {"text": "Calendar month"}, "showgrid": False},
            "yaxis": {
                "title": {"text": "Water Extent (%)"},
                "gridcolor": "#e2e8f0",
                "rangemode": "tozero",
            },
            "yaxis2": {
                "title": {"text": "Rainfall (mm)"},
                "overlaying": "y",
                "side": "right",
                "showgrid": False,
                "rangemode": "tozero",
            },
            "legend": {"orientation": "h", "y": -0.22, "x": 0.5, "xanchor": "center"},
        },
        "config": {
            "responsive": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    }
