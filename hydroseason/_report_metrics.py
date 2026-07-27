"""Pure data-shaping for the HTML report: KPIs, year-card rows, monthly records.

No HTML or string templating happens here -- every function returns plain
dicts/lists of primitives (str, int, float, Timestamp, None) that
``_report_svg.py`` and ``report.py`` turn into markup.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_report_kpis(extent: pd.DataFrame, hydro_years: pd.DataFrame) -> dict:
    """Summary KPI values for the report header cards and executive summary."""
    total_months = len(extent)
    start_date = extent.index.min().strftime("%b %Y") if not extent.empty else "N/A"
    end_date_label = extent.index.max().strftime("%b %Y") if not extent.empty else "N/A"

    n_years = len(hydro_years)

    if n_years > 0:
        mean_peak = hydro_years["peak_extent_pct"].mean()
        mean_end = hydro_years["end_extent_pct"].mean()
        mean_amp = hydro_years["amplitude_pct"].mean()
        mean_len = hydro_years["n_months_cycle"].mean()
        high_conf = len(hydro_years[hydro_years["confidence"] == "high"])
        med_conf = len(hydro_years[hydro_years["confidence"] == "medium"])
        low_conf = len(hydro_years[hydro_years["confidence"] == "low"])
        min_end = hydro_years["end_extent_pct"].min()
        max_peak = hydro_years["peak_extent_pct"].max()
    else:
        mean_peak = mean_end = mean_amp = mean_len = 0.0
        high_conf = med_conf = low_conf = 0
        min_end = max_peak = 0.0

    avg_invalid = extent["invalid_pct"].mean() if "invalid_pct" in extent.columns else 0.0

    return {
        "total_months": total_months,
        "start_date": start_date,
        "end_date_label": end_date_label,
        "n_years": n_years,
        "mean_peak": mean_peak,
        "mean_end": mean_end,
        "mean_amp": mean_amp,
        "mean_len": mean_len,
        "high_conf": high_conf,
        "med_conf": med_conf,
        "low_conf": low_conf,
        "min_end": min_end,
        "max_peak": max_peak,
        "avg_invalid": avg_invalid,
    }


def build_year_cards_data(extent: pd.DataFrame, hydro_years: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    """Per-hydrological-year data for the expandable year-card sections, newest first."""
    cards = []
    for _, row in hydro_years.sort_values("hy_year", ascending=False).iterrows():
        hy_val = int(row["hy_year"])
        conf = row.get("confidence", "unassigned")

        start_ts = pd.Timestamp(row["hy_start"])
        end_ts = pd.Timestamp(row["hy_end"])
        year_months = labels[(labels.index >= start_ts) & (labels.index <= end_ts)].copy()

        peak_month = pd.Timestamp(row["peak_month"])
        mid_dry_month = pd.Timestamp(row["mid_dry_month"])
        end_dry_month = pd.Timestamp(row["end_dry_month"])

        month_rows = []
        for ts, m_row in year_months.iterrows():
            ext_val = extent.loc[ts, "extent_pct"] if ts in extent.index else np.nan
            inv_val = extent.loc[ts, "invalid_pct"] if (ts in extent.index and "invalid_pct" in extent.columns) else 0.0
            month_rows.append({
                "ts": ts,
                "season": m_row["season"],
                "extent_pct": ext_val,
                "invalid_pct": inv_val,
                "is_peak": ts == peak_month,
                "is_mid": ts == mid_dry_month,
                "is_end": ts == end_dry_month,
            })

        cards.append({
            "hy_val": hy_val,
            "conf": conf,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "n_months_cycle": row["n_months_cycle"],
            "amplitude_pct": row["amplitude_pct"],
            "peak_month": peak_month,
            "peak_extent_pct": row["peak_extent_pct"],
            "mid_dry_month": mid_dry_month,
            "mid_extent_pct": row["mid_extent_pct"],
            "end_dry_month": end_dry_month,
            "end_extent_pct": row["end_extent_pct"],
            "month_rows": month_rows,
        })
    return cards


def build_monthly_records(extent: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    """Flat per-month records for the report's JS-driven filterable data table."""
    records = []
    for ts, row in labels.iterrows():
        ext_val = extent.loc[ts, "extent_pct"] if ts in extent.index else None
        inv_val = extent.loc[ts, "invalid_pct"] if (ts in extent.index and "invalid_pct" in extent.columns) else 0.0

        records.append({
            "date": ts.strftime("%Y-%m-%d"),
            "display_date": ts.strftime("%b %Y"),
            "year": ts.year,
            "season": row["season"],
            "hy_year": int(row["hy_year"]) if not pd.isna(row["hy_year"]) else None,
            "extent_pct": round(float(ext_val), 2) if ext_val is not None else None,
            "invalid_pct": round(float(inv_val), 2),
        })
    return records


__all__ = ["compute_report_kpis", "build_year_cards_data", "build_monthly_records"]
