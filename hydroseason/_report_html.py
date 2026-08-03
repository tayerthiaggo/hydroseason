"""Self-contained light HTML report assembly for manager bundles."""

from __future__ import annotations

import html
import json
from importlib import resources
from typing import Any

import pandas as pd

PLOTLY_ASSET_NAME = "plotly-basic-3.6.0.min.js"


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _json_script(value: Any) -> str:
    raw = json.dumps(value, allow_nan=False, ensure_ascii=False)
    return (
        raw.replace("&", "\\u0026")
        .replace("</", "<\\/")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _plotly_bundle() -> str:
    asset = resources.files("hydroseason").joinpath("_assets", PLOTLY_ASSET_NAME)
    # Disable Plotly's default topojson CDN URL in the rendered offline bundle.
    # The vendored source asset remains byte-for-byte pinned on disk.
    return (
        asset.read_text(encoding="utf-8")
        .replace("https://cdn.plot.ly/un/", "")
        .replace("prefers-color-scheme", "offline-color-scheme-disabled")
    )


def _records(frame: pd.DataFrame, *, max_rows: int = 200) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    limited = frame.head(max_rows).copy()
    for col in limited.columns:
        if pd.api.types.is_datetime64_any_dtype(limited[col]):
            limited[col] = limited[col].dt.strftime("%Y-%m-%d")
    return json.loads(limited.to_json(orient="records", date_format="iso"))


def _table(frame: pd.DataFrame, *, empty_text: str) -> str:
    if frame.empty:
        return f'<p class="empty">{_escape(empty_text)}</p>'
    shown = frame.copy()
    for col in shown.columns:
        if pd.api.types.is_datetime64_any_dtype(shown[col]):
            shown[col] = shown[col].dt.strftime("%Y-%m-%d")
    if "hy_year" in shown.columns:
        shown["hy_year"] = shown["hy_year"].map(
            lambda value: "" if pd.isna(value) else f"HY {int(value)}"
        )
    return shown.to_html(index=False, escape=True, classes="data-table", border=0)


def _kpi_cards(kpis: list[dict[str, str]]) -> str:
    cards = []
    for item in kpis[:6]:
        cards.append(
            "<div class=\"kpi\">"
            f"<span>{_escape(item.get('label', ''))}</span>"
            f"<strong>{_escape(item.get('value', ''))}</strong>"
            f"<small>{_escape(item.get('detail', ''))}</small>"
            "</div>"
        )
    return "".join(cards)


def render_report_html(
    *,
    name: str,
    title: str,
    subtitle: str | None,
    quality_note: str | None,
    verdict: str,
    kpis: list[dict[str, str]],
    monthly: pd.DataFrame,
    hydro_years: pd.DataFrame,
    events: pd.DataFrame,
    low_spells: pd.DataFrame,
    summary: pd.DataFrame,
    timeline_figure: dict[str, Any],
    secondary_figure: dict[str, Any],
    hydro_year_figure: dict[str, Any] | None = None,
) -> str:
    """Render a self-contained light report with inline pinned Plotly."""
    plotly_js = _plotly_bundle()
    data_payload = {
        "name": name,
        "title": title,
        "subtitle": subtitle,
        "quality_note": quality_note,
        "verdict": verdict,
        "figures": {
            "timeline": timeline_figure,
            "hydro_year": hydro_year_figure
            if hydro_year_figure is not None
            else {"data": [], "layout": {}, "config": {"responsive": True, "displaylogo": False}},
            "secondary": secondary_figure,
        },
        "preview_rows": _records(monthly),
    }
    quality = ""
    if quality_note:
        quality = (
            '<div class="quality quality-banner" role="status">'
            f"<strong>Data quality:</strong> {_escape(quality_note)}</div>"
        )
    tables = {
        "hydro_years": _table(
            hydro_years,
            empty_text="No hydrological-year table applies to this route.",
        ),
        "events": _table(events, empty_text="No wet events detected."),
        "low_spells": _table(low_spells, empty_text="No low-extent spells detected."),
        "summary": _table(summary, empty_text="No summary row emitted."),
    }
    return f"""<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #5b6472;
      --line: #d9dee7;
      --blue: #0b78b6;
      --green: #087f5b;
      --amber: #b7791f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--page);
      color: var(--ink);
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 48px; }}
    header {{ padding: 0 0 18px; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0 0 6px; font-size: 2rem; font-weight: 700; }}
    h2 {{ margin: 0 0 12px; font-size: 1.05rem; }}
    p {{ margin: 0; }}
    .subtitle {{ color: var(--muted); font-size: 1rem; }}
    .quality {{
      margin: 16px 0 0;
      padding: 10px 12px;
      border: 1px solid #f2d28a;
      background: #fff8e6;
      color: #704f12;
      border-radius: 6px;
    }}
    .verdict {{
      margin: 18px 0;
      padding: 16px;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      font-size: 1.05rem;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}
    .kpi {{
      min-height: 104px;
      padding: 14px;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
    }}
    .kpi span, .kpi small {{ display: block; color: var(--muted); }}
    .kpi strong {{ display: block; margin: 8px 0 4px; font-size: 1.35rem; }}
    .plot, details {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
    }}
    .plot {{ margin-top: 16px; }}
    .plot > div {{ width: 100%; min-height: 360px; }}
    .plot-primary > div {{ min-height: 480px; }}
    .plot-heading {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .plot-heading h2 {{ margin-bottom: 0; }}
    .scale-controls {{ display: flex; gap: 6px; }}
    .scale-controls button {{
      border: 1px solid var(--line); background: #fff; color: var(--ink); border-radius: 5px;
      padding: 6px 9px; cursor: pointer; font: inherit; font-size: .85rem;
    }}
    .scale-controls button.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
    details {{ margin-top: 14px; }}
    summary {{ cursor: pointer; font-weight: 650; }}
    .data-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: .88rem; }}
    .data-table th, .data-table td {{ padding: 7px 8px; border-bottom: 1px solid var(--line); text-align: left; }}
    .data-table th {{ background: #eef2f7; }}
    .empty {{ color: var(--muted); margin-top: 10px; }}
    @media (max-width: 899px) {{
      main {{ padding: 20px 12px 36px; }}
      .plot-primary > div {{ min-height: 400px; }}
      .plot-heading {{ align-items: flex-start; flex-direction: column; }}
    }}
    @media print {{ body {{ background: #fff; }} .plot, details, .verdict, .kpi {{ box-shadow: none; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>{_escape(title)}</h1>
    <p class="subtitle">{_escape(subtitle or name)}</p>
    {quality}
  </header>
  <section class="verdict">{_escape(verdict)}</section>
  <section class="kpis">{_kpi_cards(kpis)}</section>
  <section class="plot plot-primary">
    <div class="plot-heading">
      <h2>Monthly Surface Water Extent</h2>
      <div class="scale-controls" role="group" aria-label="Extent scale">
        <button id="timeline-scale-linear" type="button" class="active" aria-pressed="true">Linear scale</button>
        <button id="timeline-scale-log" type="button" aria-pressed="false">Log scale</button>
      </div>
    </div>
    <div id="timeline"></div>
  </section>
  <section class="plot plot-primary"><h2>Hydrological Year Extent</h2><div id="hydro-year"></div></section>
  <section class="plot"><h2>Supporting View</h2><div id="secondary"></div></section>
  <details><summary>Hydrological years</summary>{tables["hydro_years"]}</details>
  <details><summary>Wet events</summary>{tables["events"]}</details>
  <details><summary>Low-extent spells</summary>{tables["low_spells"]}</details>
  <details><summary>Method summary</summary>{tables["summary"]}</details>
</main>
<script>
/* {PLOTLY_ASSET_NAME}; vendored pinned offline runtime */
{plotly_js}
</script>
<script>window.HydroSeasonReport = {_json_script(data_payload)};</script>
<script>
(() => {{
  const figures = window.HydroSeasonReport.figures;
  const timeline = document.getElementById("timeline");
  const hydroYear = document.getElementById("hydro-year");
  const secondary = document.getElementById("secondary");
  const linearButton = document.getElementById("timeline-scale-linear");
  const logButton = document.getElementById("timeline-scale-log");
  const originalYByTrace = new WeakMap();

  function originalY(trace) {{
    const saved = originalYByTrace.get(trace);
    if (saved) return saved;
    let values;
    if (Array.isArray(trace.customdata) && Array.isArray(trace.customdata[0])) {{
      values = trace.customdata.map((point, index) =>
        Array.isArray(point) && point.length > 2 ? point[2] : trace.y[index]
      );
    }} else {{
      values = Array.isArray(trace.customdata) ? trace.customdata : trace.y;
    }}
    const immutable = values.slice();
    originalYByTrace.set(trace, immutable);
    return immutable;
  }}

  function logY(trace) {{
    if (trace.meta && Array.isArray(trace.meta.log_safe_y)) return trace.meta.log_safe_y;
    const floor = trace.meta && Number.isFinite(trace.meta.log_floor) ? trace.meta.log_floor : 0.02;
    return originalY(trace).map(value => value == null ? null : Math.max(value, floor));
  }}

  function setScale(type) {{
    [timeline, hydroYear].forEach(chart => {{
      const updates = {{ y: [], indices: [] }};
      chart.data.forEach((trace, index) => {{
        if (!trace.yaxis || trace.yaxis === "y") {{
          updates.y.push(type === "log" ? logY(trace) : originalY(trace));
          updates.indices.push(index);
        }}
      }});
      if (updates.indices.length) Plotly.restyle(chart, {{ y: updates.y }}, updates.indices);
      Plotly.relayout(chart, {{ "yaxis.type": type }});
    }});
    linearButton.classList.toggle("active", type === "linear");
    logButton.classList.toggle("active", type === "log");
    linearButton.setAttribute("aria-pressed", String(type === "linear"));
    logButton.setAttribute("aria-pressed", String(type === "log"));
  }}

  function rangeUpdate(event, source) {{
    if (Array.isArray(event["xaxis.range"])) return {{ "xaxis.range": event["xaxis.range"] }};
    if (event["xaxis.range[0]"] !== undefined || event["xaxis.range[1]"] !== undefined) {{
      const current = source.layout.xaxis.range || [];
      return {{ "xaxis.range": [
        event["xaxis.range[0]"] !== undefined ? event["xaxis.range[0]"] : current[0],
        event["xaxis.range[1]"] !== undefined ? event["xaxis.range[1]"] : current[1],
      ] }};
    }}
    return event["xaxis.autorange"] ? {{ "xaxis.autorange": true }} : null;
  }}

  let syncing = false;
  function synchronize(source, target) {{
    source.on("plotly_relayout", event => {{
      const update = rangeUpdate(event, source);
      if (!update || syncing) return;
      syncing = true;
      Plotly.relayout(target, update).finally(() => {{ syncing = false; }});
    }});
  }}

  Promise.all([
    Plotly.newPlot(timeline, figures.timeline.data, figures.timeline.layout, figures.timeline.config),
    Plotly.newPlot(hydroYear, figures.hydro_year.data, figures.hydro_year.layout, figures.hydro_year.config),
    Plotly.newPlot(secondary, figures.secondary.data, figures.secondary.layout, figures.secondary.config),
  ]).then(() => {{
    linearButton.addEventListener("click", () => setScale("linear"));
    logButton.addEventListener("click", () => setScale("log"));
    synchronize(timeline, hydroYear);
    synchronize(hydroYear, timeline);
  }});
}})();
</script>
</body>
</html>
"""


__all__ = ["PLOTLY_ASSET_NAME", "render_report_html"]
