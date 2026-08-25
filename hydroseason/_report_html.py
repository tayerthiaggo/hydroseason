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


def _kpi_cards(kpis: list[dict[str, str]]) -> str:
    cards = []
    for item in kpis:
        cards.append(
            "<div class=\"kpi\">"
            f"<strong class=\"kpi-value\">{_escape(item.get('value', ''))}</strong>"
            f"<div class=\"kpi-label\">{_escape(item.get('label', ''))}<br>"
            f"<small>{_escape(item.get('detail', ''))}</small></div>"
            "</div>"
        )
    return "".join(cards)


def _format_metric(value: object, *, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, (float, int)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _rainfall_details(context: dict[str, Any] | None) -> str:
    if context is None:
        return ""
    lag = context.get("peak_lag_months")
    lag_text = "N/A" if lag is None else f"{int(lag)} month(s)"
    warning = (
        f'<p class="rain-warning">{_escape(context["warning"])}</p>'
        if context.get("warning")
        else ""
    )
    return (
        '<details class="rainfall-context">'
        f'<summary>{_escape(context["title"])}</summary>'
        f'<div class="rain-badge">{_escape(context["comparison_label"])}</div>'
        '<div class="rain-grid">'
        '<div id="rainfall-context-figure"></div>'
        '<dl class="rain-stats">'
        f'<dt>Rainfall regime</dt><dd>{_escape(context.get("rainfall_regime") or "N/A")}</dd>'
        f'<dt>Comparison</dt><dd>{_escape(context["comparison_label"])}</dd>'
        f'<dt>Extent SNR</dt><dd>{_escape(_format_metric(context.get("extent_snr")))}</dd>'
        f'<dt>Rain SNR</dt><dd>{_escape(_format_metric(context.get("rainfall_snr")))}</dd>'
        f'<dt>Extent peak / trough</dt><dd>{_escape(context["extent_peak_month"])} / {_escape(context["extent_trough_month"])}</dd>'
        f'<dt>Rain peak / trough</dt><dd>{_escape(context["rainfall_peak_month"])} / {_escape(context["rainfall_trough_month"])}</dd>'
        f'<dt>Peak lag</dt><dd>{_escape(lag_text)}</dd>'
        '</dl></div>'
        f'<p class="rain-interpretation">{_escape(context["interpretation"])}</p>'
        f'{warning}</details>'
    )


def _safe_date(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _row_value(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return None


def _fmt_extent(value: Any) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.2f}%"


def _fmt_date(value: Any, *, year: bool = True) -> str:
    parsed = _safe_date(value)
    if parsed is None:
        return "N/A"
    return parsed.strftime("%B %Y" if year else "%b %Y")


def _interval_match(date: pd.Timestamp | None, rows: list[dict[str, Any]]) -> bool:
    if date is None:
        return False
    for row in rows:
        start = _safe_date(row.get("start") or row.get("start_date"))
        end = _safe_date(row.get("end") or row.get("end_date"))
        if start is not None and end is not None and start <= date <= end:
            return True
    return False


def _browser_rows(
    monthly: pd.DataFrame,
    events: pd.DataFrame,
    low_spells: pd.DataFrame,
    *,
    quality_threshold: float = 20.0,
) -> list[dict[str, Any]]:
    rows = _records(monthly, max_rows=10000)
    event_rows = _records(events, max_rows=10000)
    low_rows = _records(low_spells, max_rows=10000)
    for row in rows:
        date = _safe_date(row.get("date"))
        if date is not None:
            row.setdefault("year", int(date.year))
            row.setdefault("display_date", date.strftime("%b %Y"))
        invalid = row.get("invalid_pct")
        try:
            invalid_value = float(invalid)
        except (TypeError, ValueError):
            invalid_value = None
        state = str(row.get("quality_state") or "").lower()
        if invalid_value is None or state in {"missing", "unknown"}:
            row["quality_filter"] = "missing"
            row["quality_label"] = "Missing/unknown"
        elif state == "usable" and invalid_value <= quality_threshold:
            row["quality_filter"] = "good"
            row["quality_label"] = "Good"
        else:
            row["quality_filter"] = "flagged"
            row["quality_label"] = "Flagged"
        row["wet_event"] = "Yes" if _interval_match(date, event_rows) else "No"
        row["low_extent_spell"] = "Yes" if _interval_match(date, low_rows) else "No"
    return rows


_STATUS_REASON_TEXT = {
    "no_previous_boundary": (
        "No preceding hydrological-year boundary exists, so this cycle has no "
        "resolved start and end."
    ),
    "insufficient_trough_candidates": (
        "Too few usable trough candidates to place a cycle boundary."
    ),
    "boundary_low_quality": "Boundary months failed the data-quality threshold.",
    "boundary_provisional": "Boundary is provisional and was not confirmed.",
    "peak_low_quality": "The peak month failed the data-quality threshold.",
    "insufficient_cycle_coverage": (
        "The record's start didn't have enough usable months before the "
        "first trough to assemble a full cycle, so this year's detail "
        "metrics could not be computed."
    ),
}


_CONDITION_DISPLAY_MAP = {
    "wet_persistent": "Wet Persistent",
    "recharged_then_contracting": "Recharged, Contracting",
    "buffered_low_recharge": "Buffered Low Recharge",
    "dry_low_refuge": "Dry Low Refuge",
    "typical_or_mixed": "Typical / Mixed",
    "typical_uncertain": "Typical / Mixed",
    "high": "High",
    "low": "Low",
    "typical": "Typical",
    "insufficient_baseline": "Insufficient Baseline",
    "not_applicable_low_variability": "Low Variability",
}


def _unbounded_year_card(row: pd.Series, year: Any) -> str:
    """Render a hydrological year that has no resolved start/end boundary.

    These years are reported rather than skipped so the number of cards always
    matches the hydrological-year count shown in the summary cards.
    """
    confidence = str(_row_value(row, "confidence") or "unassigned").lower()
    status = str(_row_value(row, "status") or "incomplete").lower()
    condition_val = _row_value(row, "annual_condition", "annual_condition_qualified")
    cond_item = ""
    if condition_val and str(condition_val).lower() not in ("none", "nan", "unassigned", "<na>", "", "insufficient_baseline"):
        c_str = str(condition_val).lower()
        c_label = _CONDITION_DISPLAY_MAP.get(c_str, c_str.replace("_", " ").title())
        cond_item = f'<span class="summary-stat">Condition: <strong>{_escape(c_label)}</strong></span>'
    reason_key = str(_row_value(row, "status_reason") or "").lower()
    reason = _STATUS_REASON_TEXT.get(
        reason_key,
        reason_key.replace("_", " ").capitalize() if reason_key else "",
    )
    if reason and confidence and confidence != "unassigned":
        reason = f"{confidence.title()} confidence: {reason}"
    trough_date = _row_value(row, "trough_month", "end_dry_month", "trough_date")
    trough_extent = _row_value(row, "trough_extent_pct", "end_extent_pct")
    observed = ""
    if trough_date is not None:
        observed = (
            '<div class="detail-kpis">'
            '<div class="detail-kpi-card">'
            '<span class="detail-kpi-label">End Dry Month</span>'
            f'<span class="detail-kpi-value value-dry">{_escape(_fmt_date(trough_date))}</span>'
            f'<span class="detail-kpi-sub">{_escape(_fmt_extent(trough_extent))} extent</span>'
            "</div></div>"
        )
    return (
        '<details class="year-card year-card-unbounded">'
        '<summary class="year-header">'
        '<div class="year-title-group">'
        '<span class="expand-icon">▶</span>'
        f'<span class="year-number">HY {_escape(year)}</span>'
        '<span class="year-dates">Cycle boundaries not resolved</span>'
        "</div>"
        '<div class="year-meta-group">'
        f'{cond_item}'
        f'<span class="summary-stat">Status: <strong>{_escape(status.title())}</strong></span>'
        f'<span class="confidence-badge badge-{_escape(confidence)}" title="Hydrological year data quality and boundary confidence: {_escape(confidence.upper())}">{_escape(confidence.upper())} CONFIDENCE</span>'
        "</div>"
        "</summary>"
        '<div class="year-detail-content">'
        f'<p class="year-card-note">{_escape(reason)}</p>'
        f"{observed}"
        "</div></details>"
    )


def _year_cards(monthly: pd.DataFrame, hydro_years: pd.DataFrame) -> str:
    if hydro_years.empty:
        return '<p class="empty">No hydrological-year cycles available.</p>'

    monthly_frame = monthly.copy()
    monthly_frame.index = pd.to_datetime(
        monthly_frame["date"] if "date" in monthly_frame.columns else monthly_frame.index,
        errors="coerce",
    )
    cards: list[str] = []
    for _, row in hydro_years.sort_values("hy_year", ascending=False).iterrows():
        start = _safe_date(_row_value(row, "hy_start", "start_date", "start"))
        end = _safe_date(_row_value(row, "hy_end", "end_date", "end"))
        year = _row_value(row, "hy_year")
        if start is None or end is None:
            # A year without resolved boundaries still has to appear, or the
            # card count silently disagrees with the reported year total.
            cards.append(_unbounded_year_card(row, year))
            continue
        peak_date = _row_value(row, "peak_month", "peak_date")
        mid_date = _row_value(row, "temporal_mid_dry_month", "mid_dry_month", "mid_dry_date")
        trough_date = _row_value(row, "trough_month", "end_dry_month", "trough_date")
        cycle = _row_value(row, "cycle_months", "n_months_cycle")
        amplitude = _row_value(row, "amplitude_pct", "drawdown_pct", "seasonal_amplitude_pp")
        confidence = str(_row_value(row, "confidence") or "unassigned").lower()
        status_reason = str(_row_value(row, "status_reason") or "").lower()
        if status_reason == "record_start_boundary":
            note_text = (
                "This year&#39;s start is inferred from the record&#39;s first "
                "observed month, not a detected trough — there is no data before "
                "it to confirm where the previous dry season ended."
            )
        elif status_reason in _STATUS_REASON_TEXT:
            note_text = _escape(_STATUS_REASON_TEXT[status_reason])
        else:
            note_text = ""
        if note_text and confidence and confidence != "unassigned":
            note_text = f"{confidence.title()} confidence: {note_text}"
        inferred_start_note = (
            f'<p class="year-card-note">{note_text}</p>' if note_text else ""
        )
        condition_val = _row_value(row, "annual_condition", "annual_condition_qualified")
        condition_item = ""
        if condition_val and str(condition_val).lower() not in ("none", "nan", "unassigned", "<na>", ""):
            c_str = str(condition_val).lower()
            c_label = _CONDITION_DISPLAY_MAP.get(c_str, c_str.replace("_", " ").title())
            condition_item = f'<span class="summary-stat">Condition: <strong>{_escape(c_label)}</strong></span>'

        meta_items = []
        if condition_item:
            meta_items.append(condition_item)
        meta_items.extend([
            f'<span class="summary-stat">Cycle: <strong>{_escape("N/A" if cycle is None or pd.isna(cycle) else f"{float(cycle):.1f} mos")}</strong></span>',
            f'<span class="summary-stat">Amplitude: <strong>{_escape(_fmt_extent(amplitude))}</strong></span>',
            f'<span class="confidence-badge badge-{_escape(confidence)}" title="Hydrological year data quality and boundary confidence: {_escape(confidence.upper())}">{_escape(confidence.upper())} CONFIDENCE</span>',
        ])
        meta_html = "".join(meta_items)
        segment = monthly_frame.loc[(monthly_frame.index >= start) & (monthly_frame.index <= end)]
        detail_rows: list[str] = []
        phase_display_map = {
            "recovery": "Rising",
            "rising": "Rising",
            "recession": "Receding",
            "receding": "Receding",
            "wet": "Wet",
            "dry": "Dry",
        }
        for date, month in segment.iterrows():
            phase = str(month.get("phase", "unspecified") or "unspecified").lower()
            phase_label = phase_display_map.get(phase, "Unassigned" if phase == "unspecified" else phase.title())
            phase_class = phase if phase in {"recovery", "rising", "wet", "recession", "receding", "dry"} else "unassigned"
            event = ""
            if _safe_date(peak_date) == date:
                event = '<span class="cell-marker marker-wet">Wet Peak</span>'
            elif _safe_date(mid_date) == date:
                event = '<span class="cell-marker marker-mid">Mid Dry</span>'
            elif _safe_date(trough_date) == date:
                event = '<span class="cell-marker marker-dry">Dry End</span>'
            extent_value = month.get("extent_pct")
            invalid_value = month.get("invalid_pct")
            invalid_text = "N/A" if pd.isna(invalid_value) else f"{float(invalid_value):.2f}%"
            detail_rows.append(
                "<tr>"
                f"<td>{_escape(date.strftime('%b %Y'))}</td>"
                f"<td><span class=\"phase-badge phase-{phase_class}\">{_escape(phase_label)}</span></td>"
                f"<td><strong>{_escape(_fmt_extent(extent_value))}</strong></td>"
                f"<td>{_escape(invalid_text)}</td>"
                f"<td>{event}</td>"
                "</tr>"
            )
        cards.append(
            '<details class="year-card">'
            '<summary class="year-header">'
            '<div class="year-title-group">'
            '<span class="expand-icon">▶</span>'
            f'<span class="year-number">HY {_escape(year)}</span>'
            f'<span class="year-dates">{_escape(start.strftime("%b %Y"))} – {_escape(end.strftime("%b %Y"))}</span>'
            '</div>'
            '<div class="year-meta-group">'
            f'{meta_html}'
            '</div>'
            '</summary>'
            '<div class="year-detail-content">'
            '<div class="detail-kpis">'
            f'<div class="detail-kpi-card"><span class="detail-kpi-label">Peak Wet Month</span><span class="detail-kpi-value value-wet">{_escape(_fmt_date(peak_date))}</span><span class="detail-kpi-sub">{_escape(_fmt_extent(_row_value(row, "peak_extent_pct")))} extent</span></div>'
            f'<div class="detail-kpi-card"><span class="detail-kpi-label">Mid-Dry Target</span><span class="detail-kpi-value value-mid">{_escape(_fmt_date(mid_date))}</span><span class="detail-kpi-sub">{_escape(_fmt_extent(_row_value(row, "temporal_mid_dry_extent_pct", "mid_extent_pct")))} extent</span></div>'
            f'<div class="detail-kpi-card"><span class="detail-kpi-label">End Dry Month</span><span class="detail-kpi-value value-dry">{_escape(_fmt_date(trough_date))}</span><span class="detail-kpi-sub">{_escape(_fmt_extent(_row_value(row, "trough_extent_pct", "end_extent_pct")))} extent</span></div>'
            '</div>'
            f'{inferred_start_note}'
            '<table class="nested-table"><thead><tr><th>Month</th><th>Phase</th><th>Water Extent</th><th>Invalid/Cloud Cover</th><th>Key Event</th></tr></thead>'
            f'<tbody>{"".join(detail_rows)}</tbody></table>'
            '</div></details>'
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
    event_figure: dict[str, Any] | None = None,
    event_explainer: str | None = None,
    low_spell_figure: dict[str, Any] | None = None,
    low_spell_explainer: str | None = None,
    quality_threshold: float | None = None,
    rainfall_context: dict[str, Any] | None = None,
    rainfall_figure: dict[str, Any] | None = None,
    rainfall_warning: str | None = None,
    aoi_map_html: str | None = None,
) -> str:
    """Render a self-contained light report with inline pinned Plotly."""
    quality_threshold = 20.0 if quality_threshold is None else float(quality_threshold)
    plotly_js = _plotly_bundle()
    data_payload = {
        "name": name,
        "title": title,
        "subtitle": subtitle,
        "quality_note": quality_note,
        "verdict": verdict,
        "figures": {
            "timeline": timeline_figure,
            "secondary": secondary_figure,
        },
        "quality_threshold": quality_threshold,
        "raw_rows": _browser_rows(
            monthly,
            events,
            low_spells,
            quality_threshold=quality_threshold,
        ),
    }
    if rainfall_figure is not None:
        data_payload["figures"]["rainfall"] = rainfall_figure
    if event_figure is not None:
        data_payload["figures"]["events"] = event_figure
    if low_spell_figure is not None:
        data_payload["figures"]["low_spells"] = low_spell_figure
    event_section = (
        '<details class="report-section">'
        "<summary>Wet Event Characterisation</summary>"
        '<div class="report-section-content">'
        f"<p>{_escape(event_explainer)}</p>"
        '<div class="plot"><div id="events" class="plot-canvas"></div></div>'
        "</div></details>"
        if event_figure is not None
        else ""
    )
    low_spell_section = (
        '<details class="report-section">'
        "<summary>Low-Extent Spells</summary>"
        '<div class="report-section-content">'
        f"<p>{_escape(low_spell_explainer)}</p>"
        '<div class="plot"><div id="low-spells" class="plot-canvas"></div></div>'
        "</div></details>"
        if low_spell_figure is not None
        else ""
    )
    aoi_context_section = (
        f'<section id="aoi-context">{aoi_map_html}</section>'
        if aoi_map_html is not None
        else ""
    )
    quality = ""
    if quality_note:
        quality = (
            '<div class="quality quality-banner" role="status">'
            f"<strong>Data quality:</strong> {_escape(quality_note)}</div>"
        )
    rainfall_failure = (
        '<div class="quality rainfall-warning" role="status">'
        f'<strong>Rainfall context unavailable:</strong> {_escape(rainfall_warning)}'
        '</div>'
        if rainfall_warning
        else ""
    )
    rainfall_details = _rainfall_details(rainfall_context)
    rainfall_block = f"  {rainfall_details}" if rainfall_details else ""
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
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 16px;
      margin: 18px 0 24px;
    }}
    .kpi {{
      min-height: 126px;
      padding: 20px;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,.05);
    }}
    /* KPI values are mostly short numbers but some are multi-word labels
       ("Fixed Window", "Event-Based"). Without wrapping, a long value runs
       past the card edge instead of breaking; the clamp lets the type shrink
       on narrow cards before it has to wrap at all. */
    .kpi-value {{
      display: block;
      margin: 0 0 4px;
      font-size: clamp(1.1rem, 1rem + 1.1vw, 1.65rem);
      line-height: 1.15;
      overflow-wrap: anywhere;
      hyphens: auto;
    }}
    .kpi-label {{ display: block; color: var(--muted); font-size: .78rem; line-height: 1.3; }}
    .kpi-label small {{ font-size: .72rem; }}
    .plot, details {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
    }}
    .plot {{ margin-top: 16px; }}
    .plot > .plot-canvas {{ width: 100%; min-height: 360px; }}
    .plot-primary > .plot-canvas {{ min-height: 480px; }}
    .plot-heading {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .plot-heading h2 {{ margin-bottom: 0; }}
    .scale-controls {{ display: flex; gap: 6px; }}
    .scale-controls button {{
      border: 1px solid var(--line); background: #fff; color: var(--ink); border-radius: 5px;
      padding: 6px 9px; cursor: pointer; font: inherit; font-size: .85rem;
    }}
    .scale-controls button.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
    details {{ margin-top: 14px; }}
    .report-section {{ margin-top: 16px; }}
    .report-section-content {{ padding-top: 12px; }}
    summary {{ cursor: pointer; font-weight: 650; }}
    .rain-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(220px, .6fr);
      gap: 16px;
      margin-top: 12px;
    }}
    .rain-grid > div {{ width: 100%; min-height: 320px; }}
    .rain-stats {{
      display: grid;
      grid-template-columns: minmax(110px, auto) 1fr;
      gap: 7px 10px;
      align-content: start;
      margin: 0;
    }}
    .rain-stats dt {{ color: var(--muted); font-weight: 650; }}
    .rain-stats dd {{ margin: 0; }}
    .rain-badge {{
      display: inline-block;
      margin-top: 10px;
      padding: 4px 8px;
      border-radius: 999px;
      background: #e8f5ef;
      color: #086445;
      font-weight: 650;
    }}
    .rain-warning {{ color: #704f12; }}
    .rain-interpretation {{ margin-top: 12px; color: var(--muted); }}
    @media (max-width: 760px) {{
      .rain-grid {{ grid-template-columns: 1fr; }}
    }}
    .data-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: .88rem; }}
    .data-table th, .data-table td {{ padding: 7px 8px; border-bottom: 1px solid var(--line); text-align: left; }}
    .data-table th {{ background: #eef2f7; }}
    .empty {{ color: var(--muted); margin-top: 10px; }}
    .year-cards-container {{ display: flex; flex-direction: column; gap: 12px; margin: 16px 0 28px; }}
    .year-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
    .year-card[open] {{ border-color: var(--blue); }}
    .year-header {{ padding: 14px 18px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; gap: 16px; list-style: none; }}
    .year-header::-webkit-details-marker {{ display: none; }}
    .year-title-group, .year-meta-group {{ display: flex; align-items: center; gap: 10px; }}
    .expand-icon {{ color: var(--muted); font-size: .75rem; transition: transform .2s ease; }}
    .year-card[open] .expand-icon {{ transform: rotate(90deg); }}
    .year-number {{ font-size: 1.1rem; font-weight: 700; }}
    .year-dates, .summary-stat {{ color: var(--muted); font-size: .82rem; }}
    .confidence-badge {{ font-size: .68rem; font-weight: 700; padding: 3px 7px; border-radius: 4px; letter-spacing: .04em; }}
    .badge-high {{ background: #dcfce7; color: #166534; }}
    .badge-medium {{ background: #fef3c7; color: #92400e; }}
    .badge-low {{ background: #fee2e2; color: #991b1b; }}
    .badge-unassigned, .badge-nan {{ background: #e2e8f0; color: #475569; }}
    .year-detail-content {{ padding: 0 18px 18px; border-top: 1px solid var(--line); background: #fafafa; }}
    .year-card-unbounded {{ border-style: dashed; }}
    .year-card-unbounded .year-number {{ color: var(--muted); }}
    .year-card-note {{ margin: 14px 0 0; color: var(--muted); }}
    .detail-kpis {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 14px 0 18px; }}
    .detail-kpi-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; }}
    .detail-kpi-label {{ display: block; color: var(--muted); font-size: .7rem; text-transform: uppercase; margin-bottom: 3px; }}
    .detail-kpi-value {{ display: block; font-size: 1rem; font-weight: 650; }}
    .value-wet {{ color: #087f5b; }} .value-mid {{ color: #c2410c; }} .value-dry {{ color: #dc2626; }}
    .detail-kpi-sub {{ display: block; color: var(--muted); font-size: .75rem; margin-top: 2px; }}
    .nested-table, .main-table {{ width: 100%; border-collapse: collapse; font-size: .82rem; background: var(--panel); }}
    .nested-table th, .nested-table td, .main-table th, .main-table td {{ padding: 7px 9px; border-bottom: 1px solid var(--line); text-align: left; }}
    .nested-table th, .main-table th {{ background: #eef2f7; font-size: .75rem; }}
    .phase-badge, .cell-marker {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: .7rem; font-weight: 650; }}
    .phase-recovery, .phase-rising {{ background: #d3e9d2; color: #166534; }} .phase-wet {{ background: #b9d9ef; color: #075985; }}
    .phase-recession, .phase-receding {{ background: #f3e6c6; color: #92400e; }} .phase-dry {{ background: #f1d7d4; color: #991b1b; }}
    .phase-unassigned {{ background: #e2e8f0; color: #475569; }}
    .marker-wet {{ background: #2563eb; color: #fff; }} .marker-mid {{ background: #f97316; color: #fff; }} .marker-dry {{ background: #dc2626; color: #fff; }}
    .filters-row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: end; padding: 14px; margin: 16px 0; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }}
    .filter-item {{ display: flex; flex-direction: column; gap: 4px; min-width: 150px; }}
    .filter-item label {{ color: var(--muted); font-size: .75rem; }}
    .filter-item select {{ border: 1px solid var(--line); border-radius: 5px; padding: 6px 8px; background: #fff; color: var(--ink); font: inherit; font-size: .82rem; }}
    .main-table-container {{ overflow-x: auto; }}
    @media (max-width: 899px) {{
      main {{ padding: 20px 12px 36px; }}
      .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
      .year-header {{ align-items: flex-start; flex-direction: column; }}
      .year-meta-group {{ flex-wrap: wrap; }}
      .detail-kpis {{ grid-template-columns: 1fr; }}
      .plot-primary > .plot-canvas {{ min-height: 400px; }}
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
    {rainfall_failure}
  </header>
  <section class="verdict">{_escape(verdict)}</section>
  <section class="kpis">{_kpi_cards(kpis)}</section>
  {aoi_context_section}
  <section class="plot plot-primary">
    <div class="plot-heading">
      <h2>Monthly Surface Water Extent</h2>
      <div class="scale-controls" role="group" aria-label="Extent scale">
        <button id="timeline-scale-linear" type="button" class="active" aria-pressed="true">Linear scale</button>
        <button id="timeline-scale-log" type="button" aria-pressed="false">Log scale</button>
      </div>
    </div>
    <div id="timeline" class="plot-canvas"></div>
  </section>
  <details class="report-section">
    <summary>Seasonal Context</summary>
    <div class="report-section-content">
      <div class="plot"><div id="secondary" class="plot-canvas"></div></div>
    </div>
  </details>
  {event_section}
  {low_spell_section}
  <details class="report-section">
    <summary>Yearly Cycle Details</summary>
    <div class="report-section-content">
      <p>Expand individual hydrological years to view monthly breakdowns and detailed statistics.</p>
      <div class="year-cards-container">{_year_cards(monthly, hydro_years)}</div>
    </div>
  </details>
  <details class="report-section">
    <summary>Raw Data Browser</summary>
    <div class="report-section-content">
      <p>Filter and explore the monthly extent data directly.</p>
      <div class="filters-row">
        <div class="filter-item"><label for="raw-year-filter">Filter by Year</label><select id="raw-year-filter"><option value="all">All Years</option></select></div>
        <div class="filter-item"><label for="raw-phase-filter">Filter by Phase</label><select id="raw-phase-filter"><option value="all">All Phases</option><option value="recovery">Rising</option><option value="recession">Receding</option></select></div>
        <div class="filter-item"><label for="raw-quality-filter">Data quality (threshold {quality_threshold:.1f}% invalid)</label><select id="raw-quality-filter"><option value="all">All Records</option><option value="good">Good</option><option value="flagged">Flagged</option><option value="missing">Missing/unknown</option></select></div>
        <div class="filter-item"><label for="raw-event-filter">Wet events</label><select id="raw-event-filter"><option value="all">All Records</option><option value="yes">In wet event</option><option value="no">Outside wet event</option></select></div>
        <div class="filter-item"><label for="raw-spell-filter">Low-extent spells</label><select id="raw-spell-filter"><option value="all">All Records</option><option value="yes">In low-extent spell</option><option value="no">Outside low-extent spell</option></select></div>
      </div>
      <div class="main-table-container">
        <table class="main-table" id="raw-data-table">
          <thead><tr><th>Date</th><th>Phase</th><th>Hydro Year</th><th>Extent (%)</th><th>Invalid (%)</th><th>Data quality</th><th>Wet event</th><th>Low-extent spell</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </details>
{rainfall_block}
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
  const secondary = document.getElementById("secondary");
  const eventsPlot = document.getElementById("events");
  const lowSpellsPlot = document.getElementById("low-spells");
  const linearButton = document.getElementById("timeline-scale-linear");
  const logButton = document.getElementById("timeline-scale-log");
  const rawRows = window.HydroSeasonReport.raw_rows || [];
  const originalYByTrace = new WeakMap();

  function escapeHtml(value) {{
    const escapes = {{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }};
    return String(value ?? "").replace(/[&<>"']/g, character => escapes[character]);
  }}

  function formatPercent(value) {{
    return value == null || value === "" || Number.isNaN(Number(value)) ? "N/A" : Number(value).toFixed(2) + "%";
  }}

  function populateRawBrowser() {{
    const yearFilter = document.getElementById("raw-year-filter");
    const phaseFilter = document.getElementById("raw-phase-filter");
    const qualityFilter = document.getElementById("raw-quality-filter");
    const eventFilter = document.getElementById("raw-event-filter");
    const spellFilter = document.getElementById("raw-spell-filter");
    if (!document.querySelector) return;
    const body = document.querySelector("#raw-data-table tbody");
    if (!yearFilter || !body) return;
    [...new Set(rawRows.map(row => row.year).filter(year => year != null))]
      .sort((left, right) => right - left)
      .forEach(year => {{
        const option = document.createElement("option");
        option.value = String(year);
        option.textContent = String(year);
        yearFilter.appendChild(option);
      }});
    function render() {{
      const rows = rawRows.filter(row =>
        (yearFilter.value === "all" || String(row.year) === yearFilter.value) &&
        (phaseFilter.value === "all" || String(row.phase || "unspecified") === phaseFilter.value) &&
        (qualityFilter.value === "all" || String(row.quality_filter || "missing") === qualityFilter.value) &&
        (eventFilter.value === "all" || String(row.wet_event || "No").toLowerCase() === eventFilter.value) &&
        (spellFilter.value === "all" || String(row.low_extent_spell || "No").toLowerCase() === spellFilter.value)
      );
      const phaseMap = {{ recovery: "Rising", rising: "Rising", recession: "Receding", receding: "Receding", wet: "Wet", dry: "Dry" }};
      body.innerHTML = rows.map(row => {{
        const phase = String(row.phase || "unspecified");
        const phaseLabel = phaseMap[phase] || (phase === "unspecified" ? "Unassigned" : phase.charAt(0).toUpperCase() + phase.slice(1));
        const hydroYear = row.hy_year == null ? "" : "HY " + row.hy_year;
        return "<tr><td>" + escapeHtml(row.display_date || row.date) + "</td><td>" + escapeHtml(phaseLabel) +
          "</td><td>" + escapeHtml(hydroYear) + "</td><td>" + formatPercent(row.extent_pct) +
          "</td><td>" + formatPercent(row.invalid_pct) + "</td><td>" + escapeHtml(row.quality_label || "Missing/unknown") +
          "</td><td>" + escapeHtml(row.wet_event || "No") +
          "</td><td>" + escapeHtml(row.low_extent_spell || "No") + "</td></tr>";
      }}).join("");
    }}
    [yearFilter, phaseFilter, qualityFilter, eventFilter, spellFilter].forEach(control => control && control.addEventListener("change", render));
    render();
  }}

  function originalY(trace) {{
    if (trace.meta && Array.isArray(trace.meta.original_y)) return trace.meta.original_y;
    const saved = originalYByTrace.get(trace);
    if (saved) return saved;
    const values = Array.isArray(trace.y) ? trace.y : [];
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
    const updates = {{ y: [], indices: [] }};
    timeline.data.forEach((trace, index) => {{
      if (!trace.yaxis || trace.yaxis === "y") {{
        updates.y.push(type === "log" ? logY(trace) : originalY(trace));
        updates.indices.push(index);
      }}
    }});
    if (updates.indices.length) Plotly.restyle(timeline, {{ y: updates.y }}, updates.indices);
    Plotly.relayout(timeline, {{ "yaxis.type": type }});
    linearButton.classList.toggle("active", type === "linear");
    logButton.classList.toggle("active", type === "log");
    linearButton.setAttribute("aria-pressed", String(type === "linear"));
    logButton.setAttribute("aria-pressed", String(type === "log"));
  }}

  function togglePhaseLegend(event) {{
    const trace = timeline.data[event.curveNumber];
    const phase = trace.meta && trace.meta.phase_legend;
    if (!phase) return;
    const hidden = trace.visible !== "legendonly";
    const nextVisible = hidden ? "legendonly" : true;
    const phaseName = "phase:" + phase;
    const shapes = (timeline.layout.shapes || []).map(shape =>
      shape.name === phaseName ? Object.assign({{}}, shape, {{visible: !hidden}}) : shape
    );
    Plotly.restyle(timeline, {{visible: nextVisible}}, [event.curveNumber]);
    Plotly.relayout(timeline, {{shapes}});
    return false;
  }}

  Promise.all([
    Plotly.newPlot(timeline, figures.timeline.data, figures.timeline.layout, figures.timeline.config),
    Plotly.newPlot(secondary, figures.secondary.data, figures.secondary.layout, figures.secondary.config),
  ]).then(() => {{
    linearButton.addEventListener("click", () => setScale("linear"));
    logButton.addEventListener("click", () => setScale("log"));
    timeline.on("plotly_legendclick", togglePhaseLegend);
    if (document.querySelectorAll) document.querySelectorAll("details.report-section").forEach(section => {{
      section.addEventListener("toggle", () => {{
        if (!section.open) return;
        // Plotly sizes a chart to its container at draw time; inside a closed
        // <details> that container is zero-height, so every collapsed panel
        // needs a resize when it first opens or it renders as a sliver.
        [secondary, eventsPlot, lowSpellsPlot].forEach(node => {{
          if (node && section.contains(node)) Plotly.Plots.resize(node);
        }});
      }});
    }});
    populateRawBrowser();
    if (figures.events && eventsPlot) {{
      Plotly.newPlot(
        eventsPlot,
        figures.events.data,
        figures.events.layout,
        figures.events.config
      );
    }}
    if (figures.low_spells && lowSpellsPlot) {{
      Plotly.newPlot(
        lowSpellsPlot,
        figures.low_spells.data,
        figures.low_spells.layout,
        figures.low_spells.config
      );
    }}
    if (figures.rainfall) {{
      Plotly.newPlot(
        "rainfall-context-figure",
        figures.rainfall.data,
        figures.rainfall.layout,
        figures.rainfall.config
      );
    }}
  }});
}})();
</script>
</body>
</html>
"""


__all__ = ["PLOTLY_ASSET_NAME", "render_report_html"]
