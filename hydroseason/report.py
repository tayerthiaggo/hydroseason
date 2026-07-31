"""HTML Report Generator for HydroSeason.

Generates a gorgeous, self-contained, responsive, and interactive HTML report
summarizing water-extent seasonal detection results.

Orchestrates ``_report_metrics`` (KPI/year-card/monthly-record data) and
``_report_svg`` (chart markup) into the final HTML document.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from hydroseason._report_metrics import (
    build_monthly_records,
    build_year_cards_data,
    compute_report_kpis,
)
from hydroseason._report_svg import generate_seasonal_context_svg, generate_svg_chart


def _render_year_card(card: dict) -> str:
    conf_cls = f"badge-{card['conf']}"

    month_rows_html = []
    for m_row in card["month_rows"]:
        ts = m_row["ts"]
        ext_val = m_row["extent_pct"]
        inv_val = m_row["invalid_pct"]

        ext_str = f"{ext_val:.1f}%" if not pd.isna(ext_val) else "N/A"
        inv_str = f"{inv_val:.1f}%" if inv_val > 0 else "0%"

        label_style = "season-wet" if m_row["season"] == "Wet" else "season-dry"
        label_text = m_row["season"]

        marker_html = ""
        if m_row["is_peak"]:
            marker_html = '<span class="cell-marker marker-wet">Wet Peak</span>'
        elif m_row["is_end"]:
            marker_html = '<span class="cell-marker marker-dry">Dry End</span>'
        elif m_row["is_mid"]:
            marker_html = '<span class="cell-marker marker-mid">Mid Dry</span>'

        month_rows_html.append(f"""
            <tr>
              <td>{ts.strftime("%b %Y")}</td>
              <td><span class="season-badge {label_style}">{label_text}</span></td>
              <td><strong>{ext_str}</strong></td>
              <td>{inv_str}</td>
              <td>{marker_html}</td>
            </tr>""")

    month_table = f"""
        <table class="nested-table">
          <thead>
            <tr>
              <th>Month</th>
              <th>Season Assignment</th>
              <th>Water Extent</th>
              <th>Invalid/Cloud Cover</th>
              <th>Key Event</th>
            </tr>
          </thead>
          <tbody>
            {"".join(month_rows_html)}
          </tbody>
        </table>"""

    return f"""
        <details class="year-card" id="hy-card-{card['hy_val']}">
          <summary class="year-header">
            <div class="year-title-group">
              <span class="expand-icon">▶</span>
              <span class="year-number">HY {card['hy_val']}</span>
              <span class="year-dates">{card['start_ts'].strftime("%b %Y")} – {card['end_ts'].strftime("%b %Y")}</span>
            </div>
            <div class="year-meta-group">
              <span class="summary-stat">Cycle: <strong>{card['n_months_cycle']} mos</strong></span>
              <span class="summary-stat">Amplitude: <strong>{card['amplitude_pct']:.1f}%</strong></span>
              <span class="confidence-badge {conf_cls}">{card['conf'].upper()}</span>
            </div>
          </summary>
          <div class="year-detail-content">
            <div class="detail-kpis">
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">Peak Wet Month</span>
                <span class="detail-kpi-value value-wet">{card['peak_month'].strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{card['peak_extent_pct']:.1f}% extent</span>
              </div>
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">Mid-Dry Target</span>
                <span class="detail-kpi-value value-mid">{card['mid_dry_month'].strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{card['mid_extent_pct']:.1f}% extent</span>
              </div>
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">End Dry Month</span>
                <span class="detail-kpi-value value-dry">{card['end_dry_month'].strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{card['end_extent_pct']:.1f}% extent</span>
              </div>
            </div>
            {month_table}
          </div>
        </details>"""


def generate_html_report(
    extent: pd.DataFrame,
    hydro_years: pd.DataFrame,
    output_path: str | Path,
    title: str = "HydroSeason Seasonal Analysis",
) -> Path:
    """Generate a self-contained interactive HTML report of the hydrological season detection.

    Parameters
    ----------
    extent : pd.DataFrame
        Monthly water extent DataFrame (must contain 'extent_pct' index should be DatetimeIndex).
    hydro_years : pd.DataFrame
        Hydrological years DataFrame returned by `detect_hydrological_years`.
    output_path : str | Path
        Path to save the generated HTML file.
    title : str, default "HydroSeason Seasonal Analysis"
        Title shown in the report header.

    Returns
    -------
    Path
        Absolute path to the written HTML file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from hydroseason.hydro_year import label_hydrological_months
    labels = label_hydrological_months(extent.index, hydro_years)

    kpis = compute_report_kpis(extent, hydro_years)
    year_cards_data = build_year_cards_data(extent, hydro_years, labels)
    monthly_records = build_monthly_records(extent, labels)

    total_months = kpis["total_months"]
    start_date = kpis["start_date"]
    end_date = kpis["end_date_label"]
    n_years = kpis["n_years"]
    mean_end = kpis["mean_end"]
    mean_amp = kpis["mean_amp"]
    mean_len = kpis["mean_len"]
    high_conf = kpis["high_conf"]
    min_end = kpis["min_end"]
    max_peak = kpis["max_peak"]
    avg_invalid = kpis["avg_invalid"]

    year_cards = [_render_year_card(card) for card in year_cards_data]

    svg_chart = generate_svg_chart(extent, hydro_years, labels)
    seasonal_context_svg = generate_seasonal_context_svg(extent)

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
    
    :root {{
      --bg-main: #f8fafc;
      --bg-card: #ffffff;
      --border: #e2e8f0;
      --text-main: #334155;
      --text-muted: #64748b;
      
      --wet: #10b981;
      --wet-bg: rgba(16, 185, 129, 0.15);
      --dry: #f59e0b;
      --dry-bg: rgba(245, 158, 11, 0.15);
      --danger: #ef4444;
      --mid: #3b82f6;
      
      --accent: #2563eb;
    }}
    
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    
    body {{
      font-family: 'Roboto', sans-serif;
      background-color: var(--bg-main);
      color: var(--text-main);
      line-height: 1.5;
      padding: 24px;
    }}
    
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    
    header {{
      margin-bottom: 32px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 20px;
    }}
    
    h1 {{
      font-size: 2.2rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 8px;
    }}
    
    .subtitle {{
      color: var(--text-muted);
      font-size: 1.05rem;
      font-weight: 400;
    }}
    
    .grid {{
      display: grid;
      gap: 16px;
      margin-bottom: 32px;
    }}
    
    .grid.cards {{
      grid-template-columns: repeat(4, 1fr);
    }}
    
    .grid.two {{
      grid-template-columns: repeat(2, 1fr);
    }}
    
    .card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .card .value {{
      font-size: 2rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 4px;
    }}
    
    .card .label {{
      font-size: 0.85rem;
      color: var(--text-muted);
      line-height: 1.3;
    }}
    
    .report-text {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .report-text h2 {{
      margin-bottom: 16px;
      font-size: 1.2rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
    }}
    
    .report-text p {{
      margin-bottom: 12px;
    }}
    
    .report-text ul, .report-text ol {{
      margin-left: 20px;
      margin-bottom: 12px;
    }}
    
    .report-text li {{
      margin-bottom: 6px;
    }}
    
    .chart-container {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      position: relative;
      margin-top: 16px;
    }}
    
    .chart-svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    
    .chart-node {{
      transition: r 0.15s ease, opacity 0.15s ease;
      cursor: pointer;
    }}

    .chart-node:hover {{
      r: 8;
      opacity: 0.8;
    }}

    .chart-marker {{
      cursor: pointer;
    }}

    .chart-tooltip {{
      position: absolute;
      display: none;
      background-color: #172033;
      color: #ffffff;
      font-size: 0.8rem;
      padding: 6px 10px;
      border-radius: 6px;
      pointer-events: none;
      white-space: nowrap;
      transform: translate(-50%, -100%);
      z-index: 10;
      box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }}

    .legend-container {{
      display: flex;
      gap: 16px;
      justify-content: center;
      margin-top: 16px;
      font-size: 0.85rem;
    }}
    
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--text-muted);
    }}
    
    .legend-color {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
    }}
    
    .legend-circle {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}

    .legend-shape {{
      width: 14px;
      height: 14px;
      flex-shrink: 0;
    }}

    .year-cards-container {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 40px;
    }}
    
    .year-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      transition: border-color 0.2s ease;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .year-card[open] {{
      border-color: var(--accent);
    }}
    
    .year-header {{
      padding: 16px 20px;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      user-select: none;
      list-style: none;
    }}
    
    .year-header::-webkit-details-marker {{
      display: none;
    }}
    
    .year-title-group {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    
    .expand-icon {{
      font-size: 0.8rem;
      color: var(--text-muted);
      transition: transform 0.2s ease;
    }}
    
    .year-card[open] .expand-icon {{
      transform: rotate(90deg);
    }}
    
    .year-number {{
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-main);
    }}
    
    .year-dates {{
      font-size: 0.9rem;
      color: var(--text-muted);
      font-weight: 400;
    }}
    
    .year-meta-group {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    
    .summary-stat {{
      font-size: 0.9rem;
      color: var(--text-muted);
    }}
    
    .confidence-badge {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 4px;
      letter-spacing: 0.05em;
    }}
    
    .badge-high {{
      background-color: var(--wet-bg);
      color: var(--wet);
    }}
    
    .badge-medium {{
      background-color: var(--dry-bg);
      color: #b45309;
    }}
    
    .badge-low {{
      background-color: rgba(239, 68, 68, 0.15);
      color: var(--danger);
    }}
    
    .year-detail-content {{
      padding: 0 20px 20px 20px;
      border-top: 1px solid var(--border);
      background-color: #fafafa;
    }}
    
    .detail-kpis {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 16px;
      margin-bottom: 20px;
    }}
    
    .detail-kpi-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px;
    }}
    
    .detail-kpi-label {{
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      margin-bottom: 4px;
      display: block;
    }}
    
    .detail-kpi-value {{
      font-size: 1.15rem;
      font-weight: 600;
    }}
    
    .value-wet {{ color: var(--wet); }}
    .value-dry {{ color: var(--danger); }}
    .value-mid {{ color: var(--mid); }}
    
    .detail-kpi-sub {{
      font-size: 0.8rem;
      color: var(--text-muted);
      display: block;
      margin-top: 2px;
    }}
    
    .nested-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }}
    
    .nested-table th, .nested-table td {{
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    
    .nested-table th {{
      background-color: #f1f5f9;
      color: var(--text-main);
      font-weight: 600;
      font-size: 0.8rem;
    }}
    
    .season-badge {{
      font-size: 0.8rem;
      font-weight: 500;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    
    .season-wet {{
      background-color: var(--wet-bg);
      color: #047857;
    }}
    
    .season-dry {{
      background-color: var(--dry-bg);
      color: #b45309;
    }}
    
    .cell-marker {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    
    .marker-wet {{
      background-color: var(--wet);
      color: #ffffff;
    }}
    
    .marker-mid {{
      background-color: var(--mid);
      color: #ffffff;
    }}
    
    .marker-dry {{
      background-color: var(--danger);
      color: #ffffff;
    }}
    
    .filters-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
      align-items: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .filter-item {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    
    .filter-item label {{
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
    }}
    
    .filter-item select, .filter-item input {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 6px 12px;
      border-radius: 4px;
      font-family: inherit;
      outline: none;
    }}
    
    .filter-item select:focus, .filter-item input:focus {{
      border-color: var(--accent);
    }}
    
    .main-table-container {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .main-table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }}
    
    .main-table th, .main-table td {{
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }}
    
    .main-table th {{
      background-color: #f1f5f9;
      color: var(--text-main);
      font-weight: 600;
      font-size: 0.85rem;
    }}
    
    .main-table tbody tr:hover {{
      background-color: #f8fafc;
    }}
    
    @media (max-width: 900px) {{
      .grid.cards, .grid.two {{ grid-template-columns: 1fr; }}
      .detail-kpis {{ grid-template-columns: 1fr; }}
    }}
    
    @media print {{
      body {{ background: white; }}
      .filters-row {{ display: none; }}
      .card, .report-text, .year-card, .main-table-container {{ box-shadow: none; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{html.escape(title)}</h1>
      <p class="subtitle">Manager-ready summary of hydrological-year workflow based on remote-sensing water extent series.</p>
    </header>
    
    <main>
      <section class="grid cards">
        <div class="card"><div class="value">{n_years}</div><div class="label">hydrological years<br><small>{start_date} to {end_date}</small></div></div>
        <div class="card"><div class="value">{mean_amp:.1f}%</div><div class="label">mean annual amplitude<br><small>diff between peak and end dry</small></div></div>
        <div class="card"><div class="value">{mean_len:.1f}</div><div class="label">mean cycle length<br><small>months per hydro-year</small></div></div>
        <div class="card"><div class="value">{high_conf}</div><div class="label">high confidence years<br><small>out of {n_years} total years</small></div></div>
        <div class="card"><div class="value">{min_end:.1f}%</div><div class="label">lower water extent at end of dry season<br><small>minimum across all hydro-years</small></div></div>
        <div class="card"><div class="value">{max_peak:.1f}%</div><div class="label">higher water extent in wet season<br><small>maximum across all hydro-years</small></div></div>
        <div class="card"><div class="value">{mean_end:.1f}%</div><div class="label">average water extent at end of dry season<br><small>mean across all hydro-years</small></div></div>
        <div class="card"><div class="value">{avg_invalid:.1f}%</div><div class="label">average invalid/cloud cover<br><small>mean across {total_months} months of observations</small></div></div>
      </section>
      
      <section class="grid two">
        <div class="report-text">
          <h2>Executive Summary</h2>
          <p>This report details the seasonal dynamics of surface water extent derived from satellite observations. The timeseries has been analyzed to detect continuous hydrological years, isolating the natural wet and dry phases of the landscape.</p>
          <ul>
            <li><b>{n_years} total hydrological years</b> were successfully detected across {total_months} months of observations.</li>
            <li>The average cycle length is <b>{mean_len:.1f} months</b>.</li>
            <li><b>{high_conf} years ({round(high_conf/n_years*100) if n_years else 0}%)</b> are classified as high-confidence based on data availability and clear amplitude signals.</li>
          </ul>
        </div>
        <div class="report-text">
          <h2>Workflow</h2>
          <ol>
            <li>Load and quality-flag remote sensing water extent observations over the target period.</li>
            <li>Detect hydrological years by identifying localized peaks (Wet season) and subsequent minima (End Dry season).</li>
            <li>Calculate the Mid-Dry target month for each year to represent the transition period.</li>
            <li>Label all intermediate months based on their position within the defined hydrological years.</li>
            <li>Export visual summaries and underlying statistics.</li>
          </ol>
        </div>
      </section>

      <section class="report-text">
        <h2>Hydrological-Year Signal</h2>
        <p>The chart below displays the continuous water extent percentage over time. The background is shaded to indicate the assigned seasonal context (blue for Wet, red for Dry). Key points in each cycle are highlighted: Peak Wet (blue diamond, filled for high confidence), Mid-Dry (orange square), and End-Dry (red triangle, hydrological-year boundary). Click any marker or line point to see its exact value. The lower panel shows which hydrological year each month belongs to.</p>

        <div class="chart-container">
          {svg_chart}
          <div class="chart-tooltip" data-tooltip-for="hy-signal"></div>
          <div class="legend-container">
            <div class="legend-item"><div class="legend-color" style="background-color: var(--wet-bg);"></div> Wet Season</div>
            <div class="legend-item"><div class="legend-color" style="background-color: var(--dry-bg);"></div> Dry Season</div>
            <div class="legend-item"><div class="legend-color" style="background-color: #93c5fd; height: 2px;"></div> Monthly extent (raw)</div>
            <div class="legend-item"><div class="legend-color" style="background-color: var(--accent); height: 2px;"></div> 3-mo smoothed</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><polygon points="8,1 15,8 8,15 1,8" fill="#3b82f6" stroke="#3b82f6"/></svg> Peak Wet (high confidence)</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" fill="#f97316"/></svg> Mid Dry</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><polygon points="2,3 14,3 8,14" fill="#ef4444"/></svg> End Dry (HY boundary)</div>
          </div>
        </div>
      </section>

      <section class="report-text">
        <h2>Seasonal Context</h2>
        <p>Wet-season peaks and dry-season stress months vary by year, so the analysis avoids fixed calendar-month assumptions. This matters for persistent pools, where antecedent catchment response can shift the timing of water retention.</p>
        <div class="chart-container">
          {seasonal_context_svg}
        </div>
      </section>

      <div class="report-text" style="margin-bottom: 32px;">
        <h2>Yearly Cycle Details</h2>
        <p>Expand individual hydrological years to view monthly breakdowns and detailed statistics.</p>
        <div class="year-cards-container" style="margin-top: 16px;">
          {"".join(year_cards)}
        </div>
      </div>
      
      <div class="report-text">
        <h2>Raw Data Browser</h2>
        <p>Filter and explore the monthly extent data directly.</p>
        
        <div class="filters-row" style="margin-top: 16px;">
          <div class="filter-item">
            <label for="yearFilter">Filter by Year</label>
            <select id="yearFilter">
              <option value="all">All Years</option>
            </select>
          </div>
          <div class="filter-item">
            <label for="seasonFilter">Filter by Season</label>
            <select id="seasonFilter">
              <option value="all">All Seasons</option>
              <option value="Wet">Wet</option>
              <option value="Dry">Dry</option>
            </select>
          </div>
          <div class="filter-item">
            <label for="invalidFilter">Data Quality</label>
            <select id="invalidFilter">
              <option value="all">All Records</option>
              <option value="clean">Clean (≤ 10% Invalid)</option>
              <option value="warn">Warning (> 10% Invalid)</option>
            </select>
          </div>
        </div>
        
        <div class="main-table-container">
          <table class="main-table" id="dataTable">
            <thead>
              <tr>
                <th>Date</th>
                <th>Season</th>
                <th>Hydro Year</th>
                <th>Extent (%)</th>
                <th>Invalid (%)</th>
              </tr>
            </thead>
            <tbody>
              <!-- Populated by JS -->
            </tbody>
          </table>
        </div>
      </div>
    </main>
  </div>

  <script>
    // Data Injected from Python
    const chartData = {json.dumps(monthly_records)};
    
    document.addEventListener('DOMContentLoaded', () => {{
      // Click-to-reveal tooltips for chart markers/points
      document.querySelectorAll('.chart-container').forEach((container) => {{
        const tooltip = container.querySelector('.chart-tooltip');
        if (!tooltip) return;

        container.addEventListener('click', (evt) => {{
          const marker = evt.target.closest('.chart-marker');
          if (!marker) {{
            tooltip.style.display = 'none';
            return;
          }}
          const label = marker.getAttribute('data-label');
          if (!label) return;

          const containerRect = container.getBoundingClientRect();
          const markerRect = marker.getBoundingClientRect();
          tooltip.textContent = label;
          tooltip.style.left = (markerRect.left - containerRect.left + markerRect.width / 2) + 'px';
          tooltip.style.top = (markerRect.top - containerRect.top) + 'px';
          tooltip.style.display = 'block';
          evt.stopPropagation();
        }});
      }});

      document.addEventListener('click', (evt) => {{
        if (!evt.target.closest('.chart-container')) {{
          document.querySelectorAll('.chart-tooltip').forEach((t) => {{ t.style.display = 'none'; }});
        }}
      }});

      // Populate Year Dropdown
      const yearSelect = document.getElementById('yearFilter');
      const years = [...new Set(chartData.map(d => d.year))].sort((a,b) => b-a);
      years.forEach(y => {{
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        yearSelect.appendChild(opt);
      }});
      
      // Filtering Logic
      const tbody = document.querySelector('#dataTable tbody');
      
      function renderTable() {{
        const yFilter = yearSelect.value;
        const sFilter = document.getElementById('seasonFilter').value;
        const iFilter = document.getElementById('invalidFilter').value;
        
        let filtered = chartData;
        
        if (yFilter !== 'all') {{
          filtered = filtered.filter(d => d.year.toString() === yFilter);
        }}
        
        if (sFilter !== 'all') {{
          filtered = filtered.filter(d => d.season === sFilter);
        }}
        
        if (iFilter === 'clean') {{
          filtered = filtered.filter(d => d.invalid_pct <= 10.0);
        }} else if (iFilter === 'warn') {{
          filtered = filtered.filter(d => d.invalid_pct > 10.0);
        }}
        
        tbody.innerHTML = '';
        
        filtered.forEach(row => {{
          const tr = document.createElement('tr');
          
          let extDisplay = row.extent_pct !== null ? row.extent_pct.toFixed(2) + '%' : 'N/A';
          let invDisplay = row.invalid_pct.toFixed(2) + '%';
          
          let seasonBadge = '';
          if (row.season === 'Wet') {{
            seasonBadge = '<span class="season-badge season-wet">Wet</span>';
          }} else if (row.season === 'Dry') {{
            seasonBadge = '<span class="season-badge season-dry">Dry</span>';
          }} else {{
            seasonBadge = '<span class="season-badge" style="background:#e2e8f0; color:#475569;">Unassigned</span>';
          }}
          
          let hyDisplay = row.hy_year !== null ? 'HY ' + row.hy_year : '-';
          
          tr.innerHTML = `
            <td><strong>${{row.display_date}}</strong></td>
            <td>${{seasonBadge}}</td>
            <td>${{hyDisplay}}</td>
            <td>${{extDisplay}}</td>
            <td>${{invDisplay}}</td>
          `;
          tbody.appendChild(tr);
        }});
        
        if (filtered.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px; color:#64748b;">No records match the current filters.</td></tr>';
        }}
      }}
      
      // Bind Events
      document.getElementById('yearFilter').addEventListener('change', renderTable);
      document.getElementById('seasonFilter').addEventListener('change', renderTable);
      document.getElementById('invalidFilter').addEventListener('change', renderTable);
      
      // Initial Render
      renderTable();
    }});
  </script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_template)

    return output_path
