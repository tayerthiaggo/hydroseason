"""Public report APIs for self-contained HydroSeason manager bundles."""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from ._catchment import CatchmentAnalysis, analyze_catchment
from ._events import _empty_events, _empty_low_spells
from ._regime_compare import RegimeComparison
from ._report_copy import build_rainfall_context, select_kpis, verdict_sentence
from ._report_export import (
    build_events_export,
    build_hydro_years_export,
    build_monthly_export,
    build_summary_export,
    build_user_events_export,
    build_user_hydro_years_export,
    build_user_low_spells_export,
    build_user_monthly_export,
    normalise_report_name,
    safe_stem,
    write_report_csvs,
)
from ._report_html import render_report_html
from ._report_plotly import (
    rainfall_context_figure,
    secondary_figure,
    timeline_figure,
)
from ._state_input import prepare_monthly_extent


@dataclass(frozen=True)
class CatchmentReportPaths:
    """Paths written by :func:`generate_catchment_report`."""

    html: Path
    monthly_csv: Path
    hydro_years_csv: Path
    wet_event_csv: Path
    low_spells_csv: Path

    @property
    def events_csv(self) -> Path:
        """Backward-compatible alias for :attr:`wet_event_csv`."""
        return self.wet_event_csv


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        tmp.write(text)
        tmp_name = tmp.name
    Path(tmp_name).replace(path)


def _validate_analysis_for_extent(extent: Any, analysis: CatchmentAnalysis) -> None:
    prepared = prepare_monthly_extent(
        extent,
        max_invalid_pct=analysis.max_invalid_pct,
        quality_policy=analysis.quality_policy,
    )
    if int(analysis.regime.n_usable_months) != int(prepared["candidate_usable"].sum()):
        raise ValueError("analysis does not match extent usable-month count")

    permits_years = analysis.route not in {"event_characterisation", "insufficient_record"}
    if not permits_years and not analysis.hydro_years.empty:
        raise ValueError("analysis route forbids hydrological-year rows")
    if not permits_years and analysis.state is not None:
        raise ValueError("analysis route forbids hydrological-year state")
    if permits_years and analysis.hydro_years.empty:
        raise ValueError("analysis route requires hydrological-year rows")
    if permits_years and analysis.state is not None:
        if not analysis.state.hydro_years.equals(analysis.hydro_years):
            raise ValueError("analysis state and hydrological-year rows disagree")


def _legacy_years(hydro_years: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "start": "hy_start",
        "end": "hy_end",
        "end_dry_month": "trough_month",
        "end_dry_extent_pct": "trough_extent_pct",
    }
    years = hydro_years.rename(columns={k: v for k, v in aliases.items() if k in hydro_years})
    if "hy_year" not in years.columns:
        years = years.copy()
        years["hy_year"] = range(1, len(years) + 1)
    for col in ("hy_start", "hy_end", "peak_month", "trough_month"):
        if col in years.columns:
            years[col] = pd.to_datetime(years[col])
    return years.reset_index(drop=True)


def _legacy_monthly(extent: Any, hydro_years: pd.DataFrame) -> pd.DataFrame:
    prepared = prepare_monthly_extent(extent)
    out = pd.DataFrame(
        {
            "date": prepared.index,
            "extent_pct": prepared["extent_pct"].to_numpy(),
            "invalid_pct": prepared["invalid_pct"].to_numpy(),
            "hy_year": pd.Series(index=prepared.index, dtype="Int64"),
            "phase": "unspecified",
            "is_hy_peak": False,
            "is_hy_trough": False,
            "key_event": "",
        },
        index=prepared.index,
    )
    for row in hydro_years.itertuples():
        if hasattr(row, "hy_start") and hasattr(row, "hy_end"):
            mask = (out["date"] >= pd.Timestamp(row.hy_start)) & (
                out["date"] <= pd.Timestamp(row.hy_end)
            )
            out.loc[mask, "hy_year"] = int(row.hy_year)
        if hasattr(row, "peak_month") and pd.notna(row.peak_month):
            out.loc[out["date"] == pd.Timestamp(row.peak_month), "is_hy_peak"] = True
            out.loc[out["date"] == pd.Timestamp(row.peak_month), "key_event"] = "Wet Peak"
        if hasattr(row, "trough_month") and pd.notna(row.trough_month):
            out.loc[out["date"] == pd.Timestamp(row.trough_month), "is_hy_trough"] = True
            out.loc[out["date"] == pd.Timestamp(row.trough_month), "key_event"] = "Dry End"
    return out.reset_index(drop=True)


def _legacy_timeline(monthly: pd.DataFrame) -> dict[str, Any]:
    dates = pd.to_datetime(monthly["date"]).dt.strftime("%Y-%m-%d").tolist()
    y = [
        None
        if value is None or (isinstance(value, float) and math.isnan(value))
        else float(value)
        for value in monthly["extent_pct"].tolist()
    ]
    data: list[dict[str, Any]] = [
        {
            "type": "scatter",
            "mode": "lines+markers",
            "name": "Water Extent (%)",
            "x": dates,
            "y": y,
            "line": {"color": "#0284c7", "width": 2},
            "marker": {"size": 4, "color": "#0284c7"},
        }
    ]
    for flag, name, color, symbol in (
        ("is_hy_peak", "HY Peak", "#059669", "triangle-up"),
        ("is_hy_trough", "HY Trough", "#dc2626", "triangle-down"),
    ):
        mask = monthly[flag].fillna(False).tolist()
        if any(mask):
            data.append(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "name": name,
                    "x": [dates[i] for i, keep in enumerate(mask) if keep],
                    "y": [y[i] for i, keep in enumerate(mask) if keep],
                    "marker": {"size": 8, "color": color, "symbol": symbol},
                }
            )
    return {
        "data": data,
        "layout": {
            "paper_bgcolor": "#ffffff",
            "plot_bgcolor": "#f8fafc",
            "margin": {"l": 50, "r": 30, "t": 30, "b": 40},
            "xaxis": {"title": "Date", "showgrid": True, "gridcolor": "#e2e8f0"},
            "yaxis": {"title": "Water Extent (%)", "showgrid": True, "gridcolor": "#e2e8f0"},
        },
        "config": {"responsive": True, "displaylogo": False},
    }


def _legacy_secondary(monthly: pd.DataFrame) -> dict[str, Any]:
    month_numbers = pd.to_datetime(monthly["date"]).dt.month
    means = [
        (
            None
            if monthly.loc[month_numbers == month, "extent_pct"].dropna().empty
            else float(monthly.loc[month_numbers == month, "extent_pct"].dropna().mean())
        )
        for month in range(1, 13)
    ]
    return {
        "data": [
            {
                "type": "bar",
                "name": "Mean Monthly Extent (%)",
                "x": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                "y": means,
                "marker": {"color": "#0284c7"},
            }
        ],
        "layout": {
            "paper_bgcolor": "#ffffff",
            "plot_bgcolor": "#f8fafc",
            "margin": {"l": 50, "r": 30, "t": 30, "b": 40},
            "xaxis": {"title": "Month", "showgrid": False},
            "yaxis": {"title": "Mean Extent (%)", "showgrid": True, "gridcolor": "#e2e8f0"},
        },
        "config": {"responsive": True, "displaylogo": False},
    }


def generate_catchment_report(
    extent: Any,
    output_dir: str | Path,
    *,
    name: str | None = None,
    analysis: CatchmentAnalysis | None = None,
    rainfall: Any | None = None,
    rainfall_comparison: RegimeComparison | None = None,
    rainfall_source: Literal["csv", "silo"] | None = None,
    rainfall_warning: str | None = None,
    rainfall_comparison_warning: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    quality_note: str | None = None,
) -> CatchmentReportPaths:
    """Write HTML plus a compact, route-aware CSV bundle.

    ``name`` is optional because an AOI may not correspond to a named
    catchment.  Blank names are rendered as ``HydroSeason results`` and use a
    safe ``hydroseason-results`` filename stem.

    Rainfall context is presentation-only and additive: ``rainfall_comparison``,
    ``rainfall_source``, ``rainfall_warning``, and ``rainfall_comparison_warning``
    never alter the route-aware KPIs or primary figures -- they only render an
    optional collapsible rainfall section below them. Direct ``rainfall=``
    callers that do not specify ``rainfall_source`` are labelled "supplied CSV".
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    display_name = normalise_report_name(name)
    clean_stem = safe_stem(display_name)

    if analysis is None:
        analysis = analyze_catchment(extent, phase_model="rule_based")
    else:
        _validate_analysis_for_extent(extent, analysis)

    monthly = build_monthly_export(extent, analysis=analysis, rainfall=rainfall)
    hydro_years = build_hydro_years_export(analysis, name=display_name)
    events, low_spells = build_events_export(analysis)
    verdict = verdict_sentence(analysis)
    summary = build_summary_export(analysis, name=display_name, verdict=verdict)

    has_rainfall = "rainfall_mm" in monthly and monthly["rainfall_mm"].notna().any()
    effective_rainfall_source = rainfall_source or ("csv" if has_rainfall else None)
    rain_context = (
        build_rainfall_context(
            source=effective_rainfall_source,
            comparison=rainfall_comparison,
            comparison_warning=rainfall_comparison_warning,
        )
        if has_rainfall and effective_rainfall_source is not None
        else None
    )
    rain_figure = rainfall_context_figure(monthly) if has_rainfall else None

    # Keep the rich frames for HTML.  The CSV bundle is intentionally a
    # smaller, stable interface with explicit date names and only the fields a
    # manager normally needs to interpret the result.
    csv_paths = write_report_csvs(
        output,
        stem=clean_stem,
        monthly=build_user_monthly_export(
            monthly,
            hydro_years=hydro_years,
            analysis=analysis,
        ),
        hydro_years=build_user_hydro_years_export(hydro_years),
        events=build_user_events_export(
            events,
            baseline_extent_pct=analysis.events.summary.get("baseline_pct"),
        ),
        low_spells=build_user_low_spells_export(
            low_spells,
            baseline_extent_pct=analysis.events.summary.get("baseline_pct"),
        ),
    )

    html_path = output / f"{clean_stem}.html"
    html_text = render_report_html(
        name=display_name,
        title=title or display_name,
        subtitle=subtitle,
        quality_note=quality_note,
        verdict=verdict,
        kpis=select_kpis(analysis, extent=monthly),
        monthly=monthly,
        hydro_years=hydro_years,
        events=events,
        low_spells=low_spells,
        summary=summary,
        timeline_figure=timeline_figure(monthly, analysis),
        secondary_figure=secondary_figure(monthly, analysis),
        quality_threshold=analysis.max_invalid_pct,
        rainfall_context=rain_context,
        rainfall_figure=rain_figure,
        rainfall_warning=rainfall_warning,
    )
    _write_text_atomic(html_path, html_text)

    return CatchmentReportPaths(
        html=html_path.resolve(),
        monthly_csv=csv_paths["monthly"].resolve(),
        hydro_years_csv=csv_paths["hydro_years"].resolve(),
        wet_event_csv=csv_paths["wet_event"].resolve(),
        low_spells_csv=csv_paths["low_spells"].resolve(),
    )


def generate_html_report(
    extent: pd.DataFrame,
    hydro_years: pd.DataFrame,
    output_path: str | Path,
    title: str = "HydroSeason Seasonal Analysis",
    *,
    subtitle: str | None = None,
    quality_note: str | None = None,
) -> Path:
    """Render the legacy supplied-year HTML report without creating CSV files."""
    output = Path(output_path)
    years = _legacy_years(hydro_years)
    monthly = _legacy_monthly(extent, years)
    summary = pd.DataFrame(
        [
            {
                "title": title,
                "n_months": len(monthly),
                "n_hydro_years": len(years),
                "compatibility_api": True,
            }
        ]
    )
    verdict = (
        f"Legacy compatibility report rendered from {len(years)} supplied "
        "hydrological-year rows."
    )
    html_text = render_report_html(
        name=title,
        title=title,
        subtitle=subtitle,
        quality_note=quality_note,
        verdict=verdict,
        kpis=[
            {"label": "Hydrological years", "value": str(len(years)), "detail": "Supplied by caller"},
            {"label": "Months", "value": str(len(monthly)), "detail": "Source records"},
        ],
        monthly=monthly,
        hydro_years=years,
        events=_empty_events(),
        low_spells=_empty_low_spells(),
        summary=summary,
        timeline_figure=_legacy_timeline(monthly),
        secondary_figure=_legacy_secondary(monthly),
    )
    _write_text_atomic(output, html_text)
    return output.resolve()


__all__ = ["CatchmentReportPaths", "generate_catchment_report", "generate_html_report"]
