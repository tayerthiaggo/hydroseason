"""Build the combined, multi-catchment interactive HTML report.

Separated from run_multi_catchment_report.py so the report can be
regenerated from checkpointed state without re-querying DEA STAC — run
`python scripts/build_multi_catchment_html.py` directly once
`output/multi_catchment/*_state.pkl` checkpoints exist.
"""

from __future__ import annotations

import html
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output" / "multi_catchment"
REPORT_PATH = REPO_ROOT / "notebooks" / "hydroseason_multi_catchment_report.html"

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

PATTERN_LABELS = {
    "unimodal_annual": "Unimodal annual",
    "bimodal_or_complex": "Bimodal / complex",
    "weak_or_irregular": "Weak / irregular",
    "low_variability": "Low variability",
    "insufficient_record": "Insufficient record",
}

CONDITION_COLORS = {
    "very_low": "#dc2626",
    "low": "#f59e0b",
    "typical_or_mixed": "#64748b",
    "high": "#3b82f6",
    "very_high": "#1d4ed8",
    "insufficient_baseline": "#94a3b8",
    "not_applicable_low_variability": "#94a3b8",
}


def _month_labels(extent: pd.DataFrame, hydro_years: pd.DataFrame) -> pd.DataFrame:
    """Assign Wet/Dry + hy_year to each month from the dynamic engine's hydro_years frame."""
    labels = pd.DataFrame(index=extent.index)
    labels["hy_year"] = np.nan
    labels["season"] = "unassigned"
    complete = hydro_years[hydro_years["status"] == "complete"].sort_values("hy_year")
    for _, row in complete.iterrows():
        start, end, peak = pd.Timestamp(row["hy_start"]), pd.Timestamp(row["hy_end"]), row["peak_month"]
        mask = (labels.index >= start) & (labels.index <= end)
        labels.loc[mask, "hy_year"] = int(row["hy_year"])
        if pd.notna(peak):
            peak = pd.Timestamp(peak)
            labels.loc[mask & (labels.index <= peak), "season"] = "Wet"
            labels.loc[mask & (labels.index > peak), "season"] = "Dry"
        else:
            labels.loc[mask, "season"] = "Dry"
    return labels


def _catchment_extent_figure(spec, extent: pd.DataFrame, hydro_years: pd.DataFrame, pattern) -> str:
    """Return a <div> containing a Plotly time-series chart (extent + hy boundaries)."""
    div_id = f"chart-{spec.key}"
    labels = _month_labels(extent, hydro_years)

    dates = [d.strftime("%Y-%m-%d") for d in extent.index]
    extent_vals = [None if pd.isna(v) else round(float(v), 2) for v in extent["extent_pct"]]
    invalid_vals = [None if pd.isna(v) else round(float(v), 2) for v in extent.get("invalid_pct", pd.Series(index=extent.index, dtype=float))]

    complete = hydro_years[hydro_years["status"] == "complete"]
    peak_x = [pd.Timestamp(v).strftime("%Y-%m-%d") for v in complete["peak_month"] if pd.notna(v)]
    peak_y = [round(float(v), 2) for v, m in zip(complete["peak_extent_pct"], complete["peak_month"]) if pd.notna(m)]
    trough_x = [pd.Timestamp(v).strftime("%Y-%m-%d") for v in complete["trough_month"] if pd.notna(v)]
    trough_y = [round(float(v), 2) for v, m in zip(complete["trough_extent_pct"], complete["trough_month"]) if pd.notna(m)]

    # Wet-season shaded bands (contiguous "Wet" runs)
    shapes = []
    in_band = False
    band_start = None
    for ts, row in labels.iterrows():
        is_wet = row["season"] == "Wet"
        if is_wet and not in_band:
            band_start, in_band = ts, True
        elif not is_wet and in_band:
            shapes.append((band_start, ts))
            in_band = False
    if in_band:
        shapes.append((band_start, labels.index[-1] + pd.DateOffset(months=1)))

    shapes_json = [
        {
            "type": "rect", "xref": "x", "yref": "paper",
            "x0": s.strftime("%Y-%m-%d"), "x1": e.strftime("%Y-%m-%d"),
            "y0": 0, "y1": 1, "fillcolor": "rgba(59,130,246,0.10)", "line": {"width": 0},
        }
        for s, e in shapes
    ]

    traces = [
        {
            "x": dates, "y": extent_vals, "type": "scatter", "mode": "lines",
            "name": "Water extent (%)", "line": {"color": "#0284c7", "width": 1.8},
            "hovertemplate": "%{x|%b %Y}: %{y:.1f}%<extra></extra>",
        },
        {
            "x": dates, "y": invalid_vals, "type": "scatter", "mode": "lines",
            "name": "Invalid / cloud (%)", "line": {"color": "#cbd5e1", "width": 1, "dash": "dot"},
            "yaxis": "y", "visible": "legendonly",
            "hovertemplate": "%{x|%b %Y}: %{y:.1f}% invalid<extra></extra>",
        },
        {
            "x": peak_x, "y": peak_y, "type": "scatter", "mode": "markers",
            "name": "Peak (wet)", "marker": {"color": "#10b981", "size": 9, "symbol": "triangle-up"},
            "hovertemplate": "Peak %{x|%b %Y}: %{y:.1f}%<extra></extra>",
        },
        {
            "x": trough_x, "y": trough_y, "type": "scatter", "mode": "markers",
            "name": "Trough (dry)", "marker": {"color": "#f59e0b", "size": 9, "symbol": "triangle-down"},
            "hovertemplate": "Trough %{x|%b %Y}: %{y:.1f}%<extra></extra>",
        },
    ]

    layout = {
        "title": {"text": f"{spec.display_name} — monthly water extent", "font": {"size": 15}},
        "margin": {"l": 55, "r": 20, "t": 45, "b": 40},
        "height": 380,
        "xaxis": {"title": None, "type": "date", "rangeslider": {"visible": True, "thickness": 0.06}},
        "yaxis": {"title": "Extent (%)", "range": [0, 105]},
        "shapes": shapes_json,
        "legend": {"orientation": "h", "y": 1.18},
        "hovermode": "x unified",
        "plot_bgcolor": "#ffffff",
        "paper_bgcolor": "#ffffff",
    }

    return (
        f'<div id="{div_id}" class="plotly-chart"></div>'
        f"<script>Plotly.newPlot({json.dumps(div_id)}, {json.dumps(traces)}, {json.dumps(layout)}, "
        f'{{responsive: true, displaylogo: false}});</script>'
    )


def _resolution_label(r: dict) -> str:
    """Return the catchment display name with a '(N m)' resolution stamp suffix.

    Falls back to the bare display name if ``resolution_m`` is absent, so
    pre-Task-6 checkpoints (which lack the stamped keys entirely) still
    render without crashing -- see the module-level backward-compatibility
    note near ``_characterization_card``.
    """
    spec = r["spec"]
    resolution_m = r.get("resolution_m")
    if resolution_m is None:
        return spec.display_name
    return f"{spec.display_name} ({resolution_m:.0f}m)"


def _comparison_figure(results: list[dict]) -> str:
    """Cross-catchment comparison: peak/trough extent distribution per catchment.

    Per spec §guiding principle, catchments may run at different resolutions
    (the lazy/bounded gate can coarsen some and not others). Rather than
    silently excluding resolution-flagged catchments from this comparison
    (the brief's own wording -- "framed regime-shape, resolution stamp
    visible per catchment" -- calls for labelling, not exclusion), every
    catchment's y-axis label is stamped with its resolution in metres, e.g.
    "Gilbert River (QLD) (100m)". This keeps mixed-resolution comparisons
    visible/legible rather than hiding the caveat, while still surfacing
    the underlying difference so a reader isn't comparing apples to oranges
    unknowingly.
    """
    div_id = "chart-comparison"
    traces = []
    for r in results:
        spec = r["spec"]
        hy = r["hydro_years"]
        complete = hy[hy["status"] == "complete"]
        if complete.empty:
            continue
        label = _resolution_label(r)
        traces.append({
            "y": [label] * len(complete),
            "x": [round(float(v), 1) for v in complete["peak_extent_pct"]],
            "type": "box", "name": "Peak (wet)", "orientation": "h",
            "marker": {"color": "#10b981"}, "legendgroup": "peak",
            "showlegend": spec is results[0]["spec"],
            "offsetgroup": "peak", "alignmentgroup": "a",
        })
        traces.append({
            "y": [label] * len(complete),
            "x": [round(float(v), 1) for v in complete["trough_extent_pct"]],
            "type": "box", "name": "Trough (dry)", "orientation": "h",
            "marker": {"color": "#f59e0b"}, "legendgroup": "trough",
            "showlegend": spec is results[0]["spec"],
            "offsetgroup": "trough", "alignmentgroup": "a",
        })

    layout = {
        "title": {"text": "Peak vs. trough extent distribution, per catchment (all detected hydro-years)", "font": {"size": 15}},
        "margin": {"l": 180, "r": 20, "t": 50, "b": 40},
        "height": 110 + 70 * len(results),
        "xaxis": {"title": "Water extent (%)", "range": [0, 105]},
        "boxmode": "group",
        "plot_bgcolor": "#ffffff",
        "paper_bgcolor": "#ffffff",
    }
    return (
        f'<div id="{div_id}" class="plotly-chart"></div>'
        f"<script>Plotly.newPlot({json.dumps(div_id)}, {json.dumps(traces)}, {json.dumps(layout)}, "
        f'{{responsive: true, displaylogo: false}});</script>'
    )


def _area_pattern_figure(results: list[dict]) -> str:
    """Bubble chart: catchment area vs. seasonal amplitude, sized by area, colored by pattern.

    Per-point resolution stamp and flagged styling: each bubble's peak/trough
    amplitude is only a trustworthy quantitative figure when the catchment's
    ``pattern_claim_excluded`` is falsy (see ``plan_resolution``'s
    ``signal_veto_no_fit`` reason and ``_characterization_card``'s
    "resolution-flagged" framing). This chart previously plotted every
    catchment identically regardless of that flag. It now follows the same
    convention as ``_comparison_figure``: the resolution is folded into the
    hover text (via ``_resolution_label``) and flagged points get a visually
    distinct marker outline (thicker, red-tinted ring) so a reader can spot
    at a glance which bubbles' amplitude numbers are not meant for
    quantitative pattern comparison. Uses ``.get(..., default)`` for
    ``pattern_claim_excluded``/``resolution_m`` for the same backward
    compatibility reason documented on ``_characterization_card``.
    """
    div_id = "chart-area-pattern"
    pattern_colors = {
        "unimodal_annual": "#0284c7", "bimodal_or_complex": "#7c3aed",
        "weak_or_irregular": "#dc2626", "low_variability": "#64748b",
        "insufficient_record": "#cbd5e1",
    }
    xs, ys, sizes, colors, texts = [], [], [], [], []
    marker_line_colors, marker_line_widths = [], []
    for r in results:
        geo, hy = r["geo"], r["hydro_years"]
        complete = hy[hy["status"] == "complete"]
        amp = float((complete["peak_extent_pct"] - complete["trough_extent_pct"]).mean()) if not complete.empty else 0.0
        flagged = bool(r.get("pattern_claim_excluded", False))
        xs.append(geo["area_km2"])
        ys.append(round(amp, 1))
        sizes.append(max(18, min(70, (geo["area_km2"] ** 0.5) / 4)))
        colors.append(pattern_colors.get(r["pattern"].pattern, "#94a3b8"))
        label = _resolution_label(r)
        flag_note = "<br><b>Resolution-flagged: excluded from pattern claims</b>" if flagged else ""
        texts.append(f"{label}<br>{PATTERN_LABELS.get(r['pattern'].pattern, r['pattern'].pattern)}<br>{geo['area_km2']:,.0f} km²{flag_note}")
        marker_line_colors.append("#dc2626" if flagged else "#1e293b")
        marker_line_widths.append(3 if flagged else 1)

    trace = {
        "x": xs, "y": ys, "mode": "markers+text", "type": "scatter",
        "text": [r["spec"].display_name for r in results], "textposition": "top center",
        "marker": {
            "size": sizes, "color": colors,
            "line": {"width": marker_line_widths, "color": marker_line_colors},
        },
        "hovertext": texts, "hoverinfo": "text",
    }
    layout = {
        "title": {"text": "Catchment area vs. mean seasonal amplitude (bubble = area, color = seasonal pattern, red outline = resolution-flagged)", "font": {"size": 15}},
        "margin": {"l": 60, "r": 20, "t": 50, "b": 50},
        "height": 420,
        "xaxis": {"title": "Catchment area (km²)", "type": "log"},
        "yaxis": {"title": "Mean peak − trough extent (percentage points)"},
        "plot_bgcolor": "#ffffff",
        "paper_bgcolor": "#ffffff",
    }
    return (
        f'<div id="{div_id}" class="plotly-chart"></div>'
        f"<script>Plotly.newPlot({json.dumps(div_id)}, [{json.dumps(trace)}], {json.dumps(layout)}, "
        f'{{responsive: true, displaylogo: false}});</script>'
    )


def _characterization_card(r: dict) -> str:
    """Render one catchment's detail card.

    Backward compatibility: ``resolution_m``, ``n_valid``,
    ``projected_noise_floor_pp``, ``guard_caveat``, and
    ``pattern_claim_excluded`` were only stamped onto ``result`` starting
    with Task 6 (runner wiring, commit d14c173). Older/pre-Task-6
    checkpoints on disk -- or any ``result`` dict from before this plan's
    work -- will not have these keys. Every access below goes through
    ``r.get(...)`` with an explicit fallback (``None``/omit the stamp)
    rather than ``r[...]`` direct indexing, specifically so this function
    never crashes when handed such a dict; it just renders the affected
    block as "unknown" or omits it.
    """
    spec, geo, pattern, hy = r["spec"], r["geo"], r["pattern"], r["hydro_years"]
    complete = hy[hy["status"] == "complete"]
    n_complete = len(complete)
    n_total = len(hy)
    mean_peak = complete["peak_extent_pct"].mean() if n_complete else float("nan")
    mean_trough = complete["trough_extent_pct"].mean() if n_complete else float("nan")

    condition_counts = complete["annual_condition"].value_counts().to_dict() if "annual_condition" in complete.columns else {}
    condition_html = "".join(
        f'<span class="cond-chip" style="background:{CONDITION_COLORS.get(c, "#94a3b8")}22;'
        f'color:{CONDITION_COLORS.get(c, "#94a3b8")};border:1px solid {CONDITION_COLORS.get(c, "#94a3b8")}55">'
        f"{html.escape(c.replace('_', ' '))}: {n}</span>"
        for c, n in sorted(condition_counts.items())
    )

    # Noise-hedged view of annual_condition (stress-trust layer, Tasks 1-6):
    # collapses condition labels judged indistinguishable from the median
    # under the catchment's projected noise floor into "typical_uncertain".
    # Same completeness scoping as the plain condition chips above -- an
    # incomplete hydro-year's condition/timing isn't a settled observation
    # either, so it's excluded from both chip strips for consistency.
    qualified_counts = (
        complete["annual_condition_qualified"].value_counts().to_dict()
        if "annual_condition_qualified" in complete.columns else {}
    )
    qualified_condition_html = "".join(
        f'<span class="cond-chip" style="background:{CONDITION_COLORS.get(c, "#94a3b8")}22;'
        f'color:{CONDITION_COLORS.get(c, "#94a3b8")};border:1px solid {CONDITION_COLORS.get(c, "#94a3b8")}55">'
        f"{html.escape(c.replace('_', ' '))}: {n}</span>"
        for c, n in sorted(qualified_counts.items())
    )

    # timing_confidence has no purpose-built color map (only three values:
    # low/high/unknown) -- reuse CONDITION_COLORS.get(..., fallback) for a
    # consistent muted-grey default rather than inventing a new palette.
    timing_counts = (
        complete["timing_confidence"].value_counts().to_dict()
        if "timing_confidence" in complete.columns else {}
    )
    timing_confidence_html = "".join(
        f'<span class="cond-chip" style="background:{CONDITION_COLORS.get(c, "#94a3b8")}22;'
        f'color:{CONDITION_COLORS.get(c, "#94a3b8")};border:1px solid {CONDITION_COLORS.get(c, "#94a3b8")}55">'
        f"{html.escape(c.replace('_', ' '))}: {n}</span>"
        for c, n in sorted(timing_counts.items())
    )
    stress_trust_row_html = (
        f'<div class="cond-row"><span class="kpi-label">Qualified</span> {qualified_condition_html}'
        f'<span class="kpi-label">Timing confidence</span> {timing_confidence_html}</div>'
        if qualified_condition_html or timing_confidence_html else ""
    )

    resolution_m = r.get("resolution_m")
    n_valid = r.get("n_valid")
    noise_floor_pp = r.get("projected_noise_floor_pp")
    guard_caveat = r.get("guard_caveat")
    pattern_claim_excluded = bool(r.get("pattern_claim_excluded", False))

    resolution_html = f"{resolution_m:.0f} m" if resolution_m is not None else "—"
    n_valid_html = f"{n_valid:,}" if n_valid is not None else "—"
    noise_floor_html = f"{noise_floor_pp:.2f} pp" if noise_floor_pp is not None else "—"

    flagged_badge_html = (
        '<span class="pattern-badge pattern-flagged">Resolution-flagged &mdash; regime-shape only</span>'
        if pattern_claim_excluded else ""
    )
    flagged_note_html = (
        '<p class="flagged-note">This catchment\'s resolution was judged inadequate to support '
        "quantitative pattern/peak-trough comparisons against other catchments. Only its general "
        "wet/dry regime <strong>shape</strong> should be read from the chart below &mdash; exclude "
        "it from cross-catchment pattern claims.</p>"
        if pattern_claim_excluded else ""
    )
    caveat_html = (
        f'<div class="caveat-block"><span class="caveat-label">Guard caveat</span>'
        f"<p>{html.escape(str(guard_caveat))}</p></div>"
        if guard_caveat else ""
    )

    return f"""
    <section class="catchment-section" id="section-{spec.key}">
      <div class="catchment-header">
        <h2>{html.escape(spec.display_name)}</h2>
        <span class="pattern-badge pattern-{pattern.pattern}">{PATTERN_LABELS.get(pattern.pattern, pattern.pattern)}</span>
        {flagged_badge_html}
      </div>
      <p class="regime-note">{html.escape(spec.region)} &middot; {html.escape(spec.regime_note)}</p>
      {flagged_note_html}
      <div class="kpi-row">
        <div class="kpi"><span class="kpi-label">Catchment area</span><span class="kpi-value">{geo['area_km2']:,.0f} km²</span></div>
        <div class="kpi"><span class="kpi-label">Stream reaches</span><span class="kpi-value">{geo['n_stream_reaches'] if geo['n_stream_reaches'] is not None else '—'}</span></div>
        <div class="kpi"><span class="kpi-label">Hydro-years detected</span><span class="kpi-value">{n_total} <span class="kpi-sub">({n_complete} complete)</span></span></div>
        <div class="kpi"><span class="kpi-label">Mean peak / trough</span><span class="kpi-value">{mean_peak:.1f}% / {mean_trough:.1f}%</span></div>
        <div class="kpi"><span class="kpi-label">Seasonal strength</span><span class="kpi-value">{pattern.seasonal_strength:.2f}</span></div>
        <div class="kpi"><span class="kpi-label">Bootstrap support</span><span class="kpi-value">{pattern.bootstrap_support:.0%}</span></div>
        <div class="kpi"><span class="kpi-label">Resolution</span><span class="kpi-value">{resolution_html}</span></div>
        <div class="kpi"><span class="kpi-label">Valid pixels (median)</span><span class="kpi-value">{n_valid_html}</span></div>
        <div class="kpi"><span class="kpi-label">Projected noise floor</span><span class="kpi-value">{noise_floor_html}</span></div>
      </div>
      <div class="cond-row">{condition_html or '<span class="cond-chip">no complete cycles</span>'}</div>
      {stress_trust_row_html}
      {caveat_html}
      {_catchment_extent_figure(spec, r['extent'], hy, pattern)}
    </section>
    """


def build_report(results: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results = sorted(results, key=lambda r: r["geo"]["area_km2"])

    def _summary_row(r: dict) -> str:
        resolution_m = r.get("resolution_m")
        resolution_html = f"{resolution_m:.0f} m" if resolution_m is not None else "—"
        flagged_html = (
            ' <span class="pattern-badge pattern-flagged">flagged</span>'
            if r.get("pattern_claim_excluded") else ""
        )
        return f"""<tr>
          <td><a href="#section-{r['spec'].key}">{html.escape(r['spec'].display_name)}</a></td>
          <td>{html.escape(r['spec'].region)}</td>
          <td>{r['geo']['area_km2']:,.0f}</td>
          <td>{r['geo']['n_stream_reaches'] if r['geo']['n_stream_reaches'] is not None else '—'}</td>
          <td>{resolution_html}{flagged_html}</td>
          <td><span class="pattern-badge pattern-{r['pattern'].pattern}">{PATTERN_LABELS.get(r['pattern'].pattern, r['pattern'].pattern)}</span></td>
          <td>{len(r['hydro_years'][r['hydro_years']['status'] == 'complete'])}</td>
        </tr>"""

    summary_rows = "".join(_summary_row(r) for r in results)

    sections = "".join(_characterization_card(r) for r in results)
    comparison_chart = _comparison_figure(results)
    bubble_chart = _area_pattern_figure(results)

    n_catchments = len(results)
    total_area = sum(r["geo"]["area_km2"] for r in results)
    date_min = min(r["extent"].index.min() for r in results)
    date_max = max(r["extent"].index.max() for r in results)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HydroSeason — Multi-Catchment Transferability Report</title>
<script src="{PLOTLY_CDN}"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Roboto', -apple-system, sans-serif; margin: 0; background: #f8fafc; color: #334155;
  }}
  header.top {{
    background: linear-gradient(135deg, #0f172a, #1e3a5f); color: #fff; padding: 40px 32px;
  }}
  header.top h1 {{ margin: 0 0 6px 0; font-weight: 500; font-size: 28px; }}
  header.top p {{ margin: 0; color: #cbd5e1; font-size: 14px; }}
  .container {{ max-width: 1180px; margin: 0 auto; padding: 28px 24px 60px; }}
  .kpi-strip {{ display: flex; gap: 16px; flex-wrap: wrap; margin: -20px 24px 28px; position: relative; z-index: 2; }}
  .kpi-strip .kpi-card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); flex: 1; min-width: 160px;
  }}
  .kpi-strip .kpi-card .num {{ font-size: 22px; font-weight: 700; color: #0f172a; }}
  .kpi-strip .kpi-card .lbl {{ font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: .03em; }}
  h2 {{ font-weight: 500; color: #0f172a; }}
  table.summary {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  table.summary th {{ text-align: left; background: #f1f5f9; padding: 10px 14px; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: .03em; }}
  table.summary td {{ padding: 10px 14px; border-top: 1px solid #f1f5f9; font-size: 14px; }}
  table.summary a {{ color: #0284c7; text-decoration: none; font-weight: 500; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 20px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .catchment-section {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; margin: 24px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .catchment-header {{ display: flex; align-items: center; gap: 12px; }}
  .catchment-header h2 {{ margin: 0; }}
  .regime-note {{ color: #64748b; font-size: 13.5px; margin: 4px 0 18px; }}
  .pattern-badge {{ font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 999px; text-transform: uppercase; letter-spacing: .03em; }}
  .pattern-unimodal_annual {{ background: #e0f2fe; color: #0369a1; }}
  .pattern-bimodal_or_complex {{ background: #ede9fe; color: #6d28d9; }}
  .pattern-weak_or_irregular {{ background: #fee2e2; color: #b91c1c; }}
  .pattern-low_variability {{ background: #f1f5f9; color: #475569; }}
  .pattern-insufficient_record {{ background: #f1f5f9; color: #94a3b8; }}
  .pattern-flagged {{ background: #fef3c7; color: #b45309; }}
  .flagged-note {{
    background: #fffbeb; border: 1px solid #fde68a; color: #92400e; border-radius: 8px;
    padding: 10px 14px; font-size: 13px; margin: 10px 0 16px;
  }}
  .caveat-block {{
    background: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #dc2626;
    border-radius: 8px; padding: 10px 14px; margin: 0 0 16px; color: #991b1b; font-size: 13px;
  }}
  .caveat-block .caveat-label {{
    display: block; font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .03em; margin-bottom: 3px; color: #b91c1c;
  }}
  .caveat-block p {{ margin: 0; }}
  .kpi-row {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }}
  .kpi {{ background: #f8fafc; border: 1px solid #f1f5f9; border-radius: 8px; padding: 8px 14px; min-width: 130px; }}
  .kpi-label {{ display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: .03em; }}
  .kpi-value {{ display: block; font-size: 16px; font-weight: 700; color: #0f172a; }}
  .kpi-sub {{ font-size: 11px; font-weight: 400; color: #94a3b8; }}
  .cond-row {{ margin-bottom: 14px; }}
  .cond-chip {{ display: inline-block; font-size: 11px; padding: 3px 9px; border-radius: 999px; margin: 0 6px 6px 0; }}
  .plotly-chart {{ width: 100%; }}
  .toc {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0 0; }}
  .toc a {{ font-size: 12.5px; color: #0284c7; background: #e0f2fe; padding: 5px 12px; border-radius: 999px; text-decoration: none; }}
  footer {{ text-align: center; color: #94a3b8; font-size: 12px; padding: 30px; }}
</style>
</head>
<body>
<header class="top">
  <h1>HydroSeason — Multi-Catchment Transferability Report</h1>
  <p>Real-data AHGF/BoM catchment boundaries &middot; DEA STAC WOfS ({date_min.strftime('%b %Y')}&ndash;{date_max.strftime('%b %Y')})
     &middot; dynamic hydrological-state engine (auto-detected seasonal pattern per catchment)</p>
  <div class="toc">{"".join(f'<a href="#section-{r["spec"].key}">{html.escape(r["spec"].display_name)}</a>' for r in results)}</div>
</header>
<div class="container">
  <div class="kpi-strip">
    <div class="kpi-card"><div class="num">{n_catchments}</div><div class="lbl">Catchments</div></div>
    <div class="kpi-card"><div class="num">{total_area:,.0f}</div><div class="lbl">Total area (km²)</div></div>
    <div class="kpi-card"><div class="num">{date_min.strftime('%Y')}–{date_max.strftime('%Y')}</div><div class="lbl">Record span</div></div>
  </div>

  <h2>Summary</h2>
  <table class="summary">
    <thead><tr><th>Catchment</th><th>Region</th><th>Area (km²)</th><th>Stream reaches</th><th>Resolution</th><th>Seasonal pattern</th><th>Complete hydro-years</th></tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>

  <div class="card">{bubble_chart}</div>
  <div class="card">{comparison_chart}</div>

  <h2>Per-catchment detail</h2>
  {sections}
</div>
<footer>Generated by scripts/run_multi_catchment_report.py — HydroSeason dynamic hydrological-state engine (robust_extrema detector)</footer>
</body>
</html>"""

    html_doc = html_doc.replace("{START_DATE_PLACEHOLDER}", "")
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def main() -> None:
    checkpoints = sorted(OUTPUT_DIR.glob("*_state.pkl"))
    if not checkpoints:
        raise SystemExit(f"No checkpoints found in {OUTPUT_DIR}. Run run_multi_catchment_report.py first.")
    results = []
    for cp in checkpoints:
        with open(cp, "rb") as f:
            results.append(pickle.load(f))
    build_report(results, REPORT_PATH)
    print(f"Report written to: {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    main()
