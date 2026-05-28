"""HydroSeason.plot — interactive Plotly figures for hydrological season analysis.

All functions return ``plotly.graph_objects.Figure`` and display inline in
Jupyter without any extra call (Plotly auto-renders in notebook cells).

Colour palette is consistent across all figures:
    Wet           → WET_COLOUR  (#1565C0, deep blue)
    Transition    → TRANSITION_COLOUR (#6A1B9A, purple)
    Dry           → DRY_COLOUR  (#EF6C00, amber-orange)
    Unclassified  → UNCLASSIFIED_COLOUR (#9E9E9E, grey)
"""

from __future__ import annotations

import calendar
from typing import Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

WET_COLOUR = "#1565C0"
DRY_COLOUR = "#EF6C00"
TRANSITION_COLOUR = "#6A1B9A"
UNCLASSIFIED_COLOUR = "#9E9E9E"

_SEASON_COLOURS: dict[str, str] = {
    "Wet": WET_COLOUR,
    "Dry": DRY_COLOUR,
    "Transition": TRANSITION_COLOUR,
    "Unclassified": UNCLASSIFIED_COLOUR,
}

_MONTH_ABBR = [calendar.month_abbr[m] for m in range(1, 13)]


def _season_colour(season: str) -> str:
    return _SEASON_COLOURS.get(str(season), UNCLASSIFIED_COLOUR)


def _ordered_seasons(seasons: Sequence[str]) -> list[str]:
    preferred = ["Wet", "Transition", "Dry", "Unclassified"]
    unique = [str(season) for season in pd.Series(seasons).dropna().unique().tolist()]
    ordered = [season for season in preferred if season in unique]
    ordered.extend(season for season in unique if season not in ordered)
    return ordered


# ---------------------------------------------------------------------------
# Figure 1 — Season timeline
# ---------------------------------------------------------------------------
def plot_season_timeline(
    df: pd.DataFrame,
    *,
    value_col: str = "Rainfall_mm",
    date_col: str = "Date",
    season_col: str = "SeasonType",
    hydro_year_col: str = "Hydro_Year",
    smoothed_col: str | None = "Smoothed",
    title: str = "Monthly rainfall with season classification",
    width: int | None = None,
    height: int = 450,
) -> go.Figure:
    """Interactive bar chart of monthly values coloured by season type.

    Hydrological year boundaries are drawn as vertical dashed lines.
    If *smoothed_col* is present its smoothed curve is overlaid.
    Hover shows Date, value, SeasonType, and Hydro_Year.
    A range-slider is included beneath the x-axis for easy time navigation.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])

    seasons = df[season_col].fillna("Unclassified")
    unique_seasons = seasons.unique().tolist()

    # Build one bar trace per season so the legend is clean
    fig = go.Figure()
    for season in _ordered_seasons(unique_seasons):
        if season not in unique_seasons:
            continue
        mask = seasons == season
        sub = df[mask]
        fig.add_trace(go.Bar(
            x=sub[date_col],
            y=sub[value_col],
            name=season,
            marker_color=_season_colour(season),
            hovertemplate=(
                "<b>%{x|%b %Y}</b><br>"
                f"{value_col}: %{{y:.1f}}<br>"
                f"Season: {season}<br>"
                + (f"Hydro Year: %{{customdata}}<br>" if hydro_year_col in df.columns else "")
                + "<extra></extra>"
            ),
            customdata=sub[hydro_year_col].values if hydro_year_col in df.columns else None,
        ))

    # Smoothed overlay
    if smoothed_col and smoothed_col in df.columns:
        fig.add_trace(go.Scatter(
            x=df[date_col],
            y=df[smoothed_col],
            mode="lines",
            name="Smoothed",
            line=dict(color="#212121", width=1.5, dash="dash"),
            hovertemplate="<b>%{x|%b %Y}</b><br>Smoothed: %{y:.1f}<extra></extra>",
        ))

    # Hydro-year boundary lines
    shapes = []
    if hydro_year_col in df.columns:
        shifts = df[df[hydro_year_col] != df[hydro_year_col].shift()]
        for d in shifts[date_col].iloc[1:]:
            shapes.append(dict(
                type="line",
                x0=d, x1=d, y0=0, y1=1,
                xref="x", yref="paper",
                line=dict(color="#757575", width=0.8, dash="dot"),
            ))

    fig.update_layout(
        title=title,
        xaxis=dict(
            title="Date",
            rangeslider=dict(visible=True, thickness=0.05),
            type="date",
        ),
        yaxis=dict(title=value_col),
        barmode="overlay",
        shapes=shapes,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=height,
        width=width,
        plot_bgcolor="white",
        paper_bgcolor="white",
        hoverlabel=dict(bgcolor="white"),
        margin=dict(t=80, b=60),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEEEEE")
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE")
    return fig


# ---------------------------------------------------------------------------
# Figure 2 — Monthly climatology
# ---------------------------------------------------------------------------
def plot_monthly_climatology(
    monthly_df: pd.DataFrame,
    fixed_monthly: pd.DataFrame | None = None,
    *,
    value_col: str = "Rainfall_mm",
    month_col: str = "Month",
    title: str = "Monthly climatology",
    width: int | None = None,
    height: int = 420,
) -> go.Figure:
    """Interactive mean monthly climatology bar chart coloured by baseline season assignment.

    Parameters
    ----------
    monthly_df:
        The validated (or result) DataFrame — used to compute mean monthly values and std.
    fixed_monthly:
        The ``fixed_monthly`` artefact from the pipeline with a ``Season`` column.
        If None, all bars are rendered without season colouring.
    """
    clim = (
        monthly_df.groupby(month_col)[value_col]
        .mean()
        .reindex(range(1, 13), fill_value=0.0)
    )
    std = (
        monthly_df.groupby(month_col)[value_col]
        .std()
        .reindex(range(1, 13), fill_value=0.0)
    )

    if fixed_monthly is not None and "Season" in fixed_monthly.columns:
        season_by_month = list(fixed_monthly["Season"].values)
    else:
        season_by_month = ["Dry"] * 12

    bar_colours = [_season_colour(s) for s in season_by_month]

    fig = go.Figure()
    for season in _ordered_seasons(season_by_month):
        month_indices = [i for i, s in enumerate(season_by_month) if s == season]
        if not month_indices:
            continue
        fig.add_trace(go.Bar(
            x=[_MONTH_ABBR[i] for i in month_indices],
            y=[float(clim.iloc[i]) for i in month_indices],
            name=f"{season} (baseline)",
            marker_color=_season_colour(season),
            error_y=dict(
                type="data",
                array=[float(std.iloc[i]) for i in month_indices],
                visible=True,
                color="#263238",
                thickness=1.2,
                width=4,
            ),
            hovertemplate=(
                "<b>%{x}</b><br>"
                f"Mean {value_col}: %{{y:.1f}} mm<br>"
                "Std: %{error_y.array:.1f} mm<br>"
                f"Season: {season}<br>"
                "<extra></extra>"
            ),
        ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="Month", categoryorder="array", categoryarray=_MONTH_ABBR),
        yaxis=dict(title=f"Mean {value_col} (mm)"),
        barmode="overlay",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=height,
        width=width,
        plot_bgcolor="white",
        paper_bgcolor="white",
        hoverlabel=dict(bgcolor="white"),
        margin=dict(t=80, b=60),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE")
    return fig


# ---------------------------------------------------------------------------
# Figure 3 — STL decomposition
# ---------------------------------------------------------------------------
def plot_stl_decomposition(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    value_col: str = "Rainfall_mm",
    title: str = "STL decomposition",
    width: int | None = None,
    height: int = 700,
) -> go.Figure:
    """Interactive four-panel STL decomposition: original, trend, seasonal, remainder.

    Annotates the seasonality strength (F_S) in the seasonal panel subtitle.
    """
    from statsmodels.tsa.seasonal import STL

    series = df[[date_col, value_col]].copy()
    series[date_col] = pd.to_datetime(series[date_col])
    series = series.set_index(date_col).asfreq("MS")[value_col]
    series = series.interpolate(method="linear", limit_direction="both")

    stl = STL(series, period=12, robust=True).fit()

    var_r = float(np.var(stl.resid))
    var_rs = float(np.var(stl.resid + stl.seasonal))
    fs = round(max(0.0, 1.0 - var_r / var_rs) if var_rs > 0 else 0.0, 3)

    dates = series.index

    panels = [
        ("Observed", series.values, WET_COLOUR, False, "solid"),
        ("Trend", stl.trend.values, "#37474F", False, "solid"),
        (f"Seasonal  (F_S = {fs})", stl.seasonal.values, "#6A1B9A", True, "solid"),
        ("Remainder", stl.resid.values, "#B71C1C", True, "solid"),
    ]

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        subplot_titles=[p[0] for p in panels],
        vertical_spacing=0.06,
    )

    for row, (label, values, colour, zeroline, dash) in enumerate(panels, start=1):
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=values,
                mode="lines",
                name=label,
                line=dict(color=colour, width=1.2),
                hovertemplate="<b>%{x|%b %Y}</b><br>%{y:.2f}<extra></extra>",
                showlegend=False,
            ),
            row=row, col=1,
        )
        if zeroline:
            fig.add_hline(y=0, line=dict(color="#90A4AE", width=0.7, dash="dash"), row=row, col=1)

    fig.update_layout(
        title=title,
        height=height,
        width=width,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(t=80, b=60),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEEEEE")
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE")
    return fig


# ---------------------------------------------------------------------------
# Figure 4 — Annual metrics
# ---------------------------------------------------------------------------
def plot_annual_metrics(
    df: pd.DataFrame,
    *,
    hydro_year_col: str = "Hydro_Year",
    wet_col: str = "wet_total",
    dry_col: str = "dry_total",
    wet_months_col: str = "wet_month_count",
    fallback_wet_col: str = "Rain_wet_season_mm",
    fallback_dry_col: str = "Rain_dry_season_mm",
    title: str = "Annual wet / dry season totals",
    width: int | None = None,
    height: int = 500,
) -> go.Figure:
    """Interactive stacked bar of wet and dry season totals per hydrological year.

    Wet month count is shown as a line on a secondary y-axis.
    Falls back to legacy column names if ``wet_total`` is not present.
    """
    if wet_col not in df.columns:
        wet_col = fallback_wet_col
    if dry_col not in df.columns:
        dry_col = fallback_dry_col

    annual = (
        df[[hydro_year_col, wet_col, dry_col, wet_months_col]]
        .drop_duplicates(subset=[hydro_year_col])
        .sort_values(hydro_year_col)
        .reset_index(drop=True)
    )
    years = annual[hydro_year_col].astype(int).astype(str).tolist()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=["Wet & dry totals (mm)", "Wet months per year"],
        vertical_spacing=0.12,
        row_heights=[0.65, 0.35],
    )

    fig.add_trace(go.Bar(
        x=years,
        y=annual[wet_col],
        name="Wet total",
        marker_color=WET_COLOUR,
        hovertemplate="<b>Hydro Year %{x}</b><br>Wet total: %{y:.0f} mm<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=years,
        y=annual[dry_col],
        name="Dry total",
        marker_color=DRY_COLOUR,
        hovertemplate="<b>Hydro Year %{x}</b><br>Dry total: %{y:.0f} mm<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=years,
        y=annual[wet_months_col],
        name="Wet months",
        marker_color="#0288D1",
        opacity=0.85,
        hovertemplate="<b>Hydro Year %{x}</b><br>Wet months: %{y}<extra></extra>",
    ), row=2, col=1)

    fig.update_layout(
        title=title,
        barmode="stack",
        height=height,
        width=width,
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="white"),
        margin=dict(t=80, b=60),
    )
    fig.update_xaxes(showgrid=False, tickangle=45)
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE")
    fig.update_yaxes(title_text="mm", row=1, col=1)
    fig.update_yaxes(title_text="count", row=2, col=1)
    return fig


# ---------------------------------------------------------------------------
# Figure 5 — Diagnostics table
# ---------------------------------------------------------------------------
def plot_diagnostics_table(
    diagnostics,  # DiagnosticsReport (avoid circular import)
    *,
    title: str = "Algorithm diagnostics",
    width: int | None = None,
    height: int = 480,
) -> go.Figure:
    """Interactive table of DiagnosticsReport fields.

    The 'regime' cell is colour-coded:
      seasonal      → light green (#C8E6C9)
      borderline    → light amber (#FFF9C4)
      non_seasonal  → light red  (#FFCDD2)
    """
    _regime_colours = {
        "seasonal": "#C8E6C9",
        "borderline": "#FFF9C4",
        "non_seasonal": "#FFCDD2",
    }

    regime = str(getattr(diagnostics, "regime", "unknown"))
    header_bg = _regime_colours.get(regime, "#F5F5F5")

    fields = [
        ("Regime", diagnostics.regime),
        ("Regime source", diagnostics.regime_source),
        ("STL strength (F_S)", f"{diagnostics.stl_strength:.3f}"),
        ("Walsh-Lawler SI", f"{diagnostics.walsh_lawler_si:.3f}"),
        ("Hydro year start (month)", diagnostics.hydro_year_start_month),
        ("Fallback month used", diagnostics.fallback_month_used),
        ("Rainfall SI override", diagnostics.rainfall_si_override),
        ("Circular R", f"{diagnostics.circular_R:.3f}" if diagnostics.circular_R is not None else "N/A"),
        ("Is bimodal", diagnostics.is_bimodal),
        ("Is uniform", diagnostics.is_uniform),
        ("KMeans silhouette", f"{diagnostics.kmeans_silhouette:.3f}" if diagnostics.kmeans_silhouette is not None else "N/A"),
        ("Threshold (1st pass)", f"{diagnostics.threshold_firstpass:.1f}" if diagnostics.threshold_firstpass is not None else "N/A"),
        ("Threshold (2nd pass)", f"{diagnostics.threshold_secondpass:.1f}" if diagnostics.threshold_secondpass is not None else "N/A"),
        ("Input rows", diagnostics.n_input_rows),
        ("Rows after validation", diagnostics.n_rows_after_validation),
        ("Imputed rows", diagnostics.n_imputed),
    ]
    if diagnostics.validation_warnings:
        fields.append(("Validation warnings", "; ".join(diagnostics.validation_warnings)))

    labels = [f[0] for f in fields]
    values = [str(f[1]) for f in fields]

    # Highlight the regime row
    cell_colours = ["white"] * len(labels)
    if "Regime" in labels:
        cell_colours[labels.index("Regime")] = header_bg

    fig = go.Figure(go.Table(
        header=dict(
            values=["<b>Field</b>", "<b>Value</b>"],
            fill_color="#ECEFF1",
            align="left",
            font=dict(size=12),
            height=30,
        ),
        cells=dict(
            values=[labels, values],
            fill_color=[cell_colours, cell_colours],
            align="left",
            font=dict(size=11),
            height=26,
        ),
    ))

    fig.update_layout(
        title=title,
        height=height,
        width=width,
        margin=dict(t=60, b=20, l=10, r=10),
        paper_bgcolor="white",
    )
    return fig


# ---------------------------------------------------------------------------
# Figure 6 — Dashboard (composite)
# ---------------------------------------------------------------------------
def plot_dashboard(
    artifacts,  # PipelineArtifacts (avoid circular import — typed as Any)
    *,
    value_col: str = "Rainfall_mm",
    title: str = "HydroSeason dashboard",
    width: int | None = None,
    height: int = 900,
) -> go.Figure:
    """Composite interactive dashboard with three panels.

    Layout:
      Row 1 (full width): Season timeline
      Row 2 col 1: Monthly climatology
      Row 2 col 2: Annual wet/dry metrics
    """
    result = artifacts.result
    fixed_monthly = artifacts.fixed_monthly
    d = artifacts.diagnostics

    # Resolve column names (fallback for backwards compat)
    wet_col = "wet_total" if "wet_total" in result.columns else "Rain_wet_season_mm"
    dry_col = "dry_total" if "dry_total" in result.columns else "Rain_dry_season_mm"
    wet_months_col = "wet_month_count"

    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"colspan": 2}, None], [{}, {}]],
        subplot_titles=[
            f"Season timeline  |  regime: {d.regime}  |  SI: {d.walsh_lawler_si:.3f}",
            "Monthly climatology",
            "Annual totals",
        ],
        vertical_spacing=0.14,
        horizontal_spacing=0.1,
        row_heights=[0.55, 0.45],
    )

    # ── Row 1: Timeline ──────────────────────────────────────────────────────
    df_t = result.copy()
    df_t["Date"] = pd.to_datetime(df_t["Date"])
    seasons = df_t["SeasonType"].fillna("Unclassified")

    for season in _ordered_seasons(seasons):
        mask = seasons == season
        if not mask.any():
            continue
        sub = df_t[mask]
        fig.add_trace(go.Bar(
            x=sub["Date"],
            y=sub[value_col],
            name=season,
            marker_color=_season_colour(season),
            legendgroup=season,
            showlegend=True,
            hovertemplate=(
                f"<b>%{{x|%b %Y}}</b><br>{value_col}: %{{y:.1f}}<br>Season: {season}<extra></extra>"
            ),
        ), row=1, col=1)

    smoothed_col = "Smoothed"
    if smoothed_col in df_t.columns:
        fig.add_trace(go.Scatter(
            x=df_t["Date"], y=df_t[smoothed_col],
            mode="lines", name="Smoothed",
            line=dict(color="#212121", width=1.5, dash="dash"),
            legendgroup="Smoothed",
            hovertemplate="<b>%{x|%b %Y}</b><br>Smoothed: %{y:.1f}<extra></extra>",
        ), row=1, col=1)

    # Hydro-year boundaries on timeline
    if "Hydro_Year" in df_t.columns:
        shifts = df_t[df_t["Hydro_Year"] != df_t["Hydro_Year"].shift()]
        for d_date in shifts["Date"].iloc[1:]:
            fig.add_shape(
                type="line",
                x0=d_date, x1=d_date, y0=0, y1=1,
                xref="x", yref="paper",
                line=dict(color="#757575", width=0.8, dash="dot"),
                row=1, col=1,
            )

    # ── Row 2 col 1: Monthly climatology ─────────────────────────────────────
    clim = result.groupby("Month")[value_col].mean().reindex(range(1, 13), fill_value=0.0)
    std_v = result.groupby("Month")[value_col].std().reindex(range(1, 13), fill_value=0.0)

    if fixed_monthly is not None and "Season" in fixed_monthly.columns:
        season_by_month = list(fixed_monthly["Season"].values)
    else:
        season_by_month = ["Dry"] * 12

    for season in _ordered_seasons(season_by_month):
        month_indices = [i for i, s in enumerate(season_by_month) if s == season]
        if not month_indices:
            continue
        fig.add_trace(go.Bar(
            x=[_MONTH_ABBR[i] for i in month_indices],
            y=[float(clim.iloc[i]) for i in month_indices],
            name=f"{season} (baseline)",
            marker_color=_season_colour(season),
            legendgroup=f"{season}-clim",
            showlegend=False,
            error_y=dict(
                type="data",
                array=[float(std_v.iloc[i]) for i in month_indices],
                visible=True,
                color="#263238",
                thickness=1.0,
                width=3,
            ),
            hovertemplate=f"<b>%{{x}}</b><br>Mean: %{{y:.1f}} mm<br>Std: %{{error_y.array:.1f}} mm<br>Season: {season}<extra></extra>",
        ), row=2, col=1)

    # ── Row 2 col 2: Annual metrics ───────────────────────────────────────────
    annual = (
        result[[("Hydro_Year"), wet_col, dry_col]]
        .drop_duplicates(subset=["Hydro_Year"])
        .sort_values("Hydro_Year")
        .reset_index(drop=True)
    )
    years = annual["Hydro_Year"].astype(int).astype(str).tolist()

    fig.add_trace(go.Bar(
        x=years, y=annual[wet_col],
        name="Wet total",
        marker_color=WET_COLOUR,
        legendgroup="ann-wet",
        showlegend=False,
        hovertemplate="<b>%{x}</b><br>Wet: %{y:.0f} mm<extra></extra>",
    ), row=2, col=2)

    fig.add_trace(go.Bar(
        x=years, y=annual[dry_col],
        name="Dry total",
        marker_color=DRY_COLOUR,
        legendgroup="ann-dry",
        showlegend=False,
        hovertemplate="<b>%{x}</b><br>Dry: %{y:.0f} mm<extra></extra>",
    ), row=2, col=2)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        barmode="stack",
        height=height,
        width=width,
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="white"),
        margin=dict(t=100, b=60),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEEEEE")
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE")
    # Month category order for climatology
    fig.update_xaxes(categoryorder="array", categoryarray=_MONTH_ABBR, row=2, col=1)
    fig.update_xaxes(tickangle=45, row=2, col=2)
    fig.update_yaxes(title_text=value_col, row=1, col=1)
    fig.update_yaxes(title_text="mm", row=2, col=1)
    fig.update_yaxes(title_text="mm", row=2, col=2)
    return fig
