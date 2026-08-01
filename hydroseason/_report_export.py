"""Complete route-aware report export frames and CSV writing.

Preserves every source month, stable empty schemas, explicit closed-interval
membership, nullable identifiers, route authority, and optional rainfall month alignment.
Do not infer membership by row position.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from ._condition import compute_monthly_surface_water_condition
from ._events import _empty_events, _empty_low_spells
from ._phase import empty_monthly_phase
from ._state_input import prepare_monthly_extent

if TYPE_CHECKING:
    from ._catchment import CatchmentAnalysis


STABLE_HY_COLUMNS = [
    "hy_year",
    "hy_start",
    "hy_end",
    "trough_month",
    "peak_month",
    "trough_extent_pct",
    "peak_extent_pct",
    "duration_months",
    "status",
    "peak_selection_status",
    "half_loss_month",
    "boundary_basis",
    "catchment",
    "regime",
    "route",
]


def safe_stem(name: str) -> str:
    """Sanitize catchment name into safe filename stem."""
    stem = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return stem or "catchment"


def build_monthly_export(
    extent: Any,
    *,
    analysis: CatchmentAnalysis,
    rainfall: Any | None = None,
) -> pd.DataFrame:
    """Build a complete, monthly timeline export matching source length and alignment."""
    prepared = prepare_monthly_extent(extent)

    if analysis.state is not None:
        cond_df = analysis.state.monthly_condition
        phase_df = analysis.state.monthly_phase
    else:
        cond_df = compute_monthly_surface_water_condition(extent)
        phase_df = empty_monthly_phase(prepared)

    out = pd.DataFrame(index=prepared.index)
    out["date"] = prepared.index
    out["extent_pct"] = prepared["extent_pct"]
    out["invalid_pct"] = prepared["invalid_pct"]
    out["usable_month"] = prepared["candidate_usable"]

    for col in ["reference_median_pct", "anomaly_pct", "condition_percentile"]:
        out[col] = cond_df[col] if col in cond_df.columns else np.nan

    out["quality_state"] = prepared["quality_state"]

    out["hy_year"] = pd.Series(index=prepared.index, dtype="Int64")
    out["phase"] = phase_df["phase"].to_numpy() if "phase" in phase_df.columns else "unspecified"
    out["is_hy_peak"] = False
    out["is_hy_trough"] = False

    permits_years = analysis.route not in {"event_characterisation", "insufficient_record"}
    if permits_years and not analysis.hydro_years.empty:
        for row in analysis.hydro_years.itertuples():
            start_dt = pd.Timestamp(row.hy_start)
            end_dt = pd.Timestamp(row.hy_end)
            mask = (out["date"] >= start_dt) & (out["date"] <= end_dt)
            out.loc[mask, "hy_year"] = int(row.hy_year)

            if hasattr(row, "peak_month") and pd.notna(row.peak_month):
                p_dt = pd.Timestamp(row.peak_month)
                out.loc[out["date"] == p_dt, "is_hy_peak"] = True

            if hasattr(row, "trough_month") and pd.notna(row.trough_month):
                t_dt = pd.Timestamp(row.trough_month)
                out.loc[out["date"] == t_dt, "is_hy_trough"] = True
    else:
        out["hy_year"] = pd.Series(index=prepared.index, dtype="Int64")
        out["phase"] = "unspecified"
        out["is_hy_peak"] = False
        out["is_hy_trough"] = False

    out["in_wet_event"] = False
    out["wet_event_id"] = pd.Series(index=prepared.index, dtype="Int64")
    out["in_low_spell"] = False
    out["low_spell_id"] = pd.Series(index=prepared.index, dtype="Int64")

    if analysis.events is not None:
        if not analysis.events.events.empty:
            for row in analysis.events.events.itertuples():
                e_start = pd.Timestamp(row.start)
                e_end = pd.Timestamp(row.end)
                mask = (out["date"] >= e_start) & (out["date"] <= e_end)
                out.loc[mask, "in_wet_event"] = True
                out.loc[mask, "wet_event_id"] = int(row.event_id)

        if not analysis.events.low_spells.empty:
            for row in analysis.events.low_spells.itertuples():
                s_start = pd.Timestamp(row.start)
                s_end = pd.Timestamp(row.end)
                mask = (out["date"] >= s_start) & (out["date"] <= s_end)
                out.loc[mask, "in_low_spell"] = True
                out.loc[mask, "low_spell_id"] = int(row.spell_id)

    out["regime"] = analysis.regime.regime
    out["route"] = analysis.route

    if rainfall is not None:
        if isinstance(rainfall, (str, Path)):
            rf_df = pd.read_csv(rainfall)
        elif isinstance(rainfall, pd.Series):
            rf_df = rainfall.to_frame(name="rainfall_mm")
        else:
            rf_df = rainfall.copy()

        if "date" in rf_df.columns:
            rf_df.index = pd.to_datetime(rf_df.pop("date"))
        else:
            rf_df.index = pd.to_datetime(rf_df.index)

        rf_df.index = rf_df.index.to_period("M").to_timestamp()

        val_col = "rainfall_mm" if "rainfall_mm" in rf_df.columns else rf_df.columns[0]
        rain_series = pd.to_numeric(rf_df[val_col], errors="coerce")
        out["rainfall_mm"] = out["date"].map(rain_series)

        monthly_medians = out.groupby(out["date"].dt.month)["rainfall_mm"].transform("median")
        out["rain_anomaly_mm"] = out["rainfall_mm"] - monthly_medians

    return out.reset_index(drop=True)


def build_hydro_years_export(
    analysis: CatchmentAnalysis,
    *,
    name: str,
) -> pd.DataFrame:
    """Build hydrological year export table with catchment metadata."""
    permits_years = analysis.route not in {"event_characterisation", "insufficient_record"}
    if not permits_years or analysis.hydro_years.empty:
        return pd.DataFrame(columns=STABLE_HY_COLUMNS)

    df = analysis.hydro_years.copy()
    df["catchment"] = name
    df["regime"] = analysis.regime.regime
    df["route"] = analysis.route
    if "boundary_basis" not in df.columns:
        df["boundary_basis"] = (
            "detected_per_year"
            if analysis.route == "per_year_detection"
            else "imposed_fixed_window"
        )
    return df.reset_index(drop=True)


def build_events_export(
    analysis: CatchmentAnalysis,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build wet event and dry spell export tables."""
    if analysis.events is None:
        return _empty_events(), _empty_low_spells()

    events_df = (
        analysis.events.events.copy()
        if not analysis.events.events.empty
        else _empty_events()
    )
    low_spells_df = (
        analysis.events.low_spells.copy()
        if not analysis.events.low_spells.empty
        else _empty_low_spells()
    )
    return events_df.reset_index(drop=True), low_spells_df.reset_index(drop=True)


def build_summary_export(
    analysis: CatchmentAnalysis,
    *,
    name: str,
    verdict: str,
) -> pd.DataFrame:
    """Build single-row summary export DataFrame."""
    row = analysis.summary_row(name=name)
    row["verdict"] = verdict
    return pd.DataFrame([row])


def write_report_csvs(
    output_dir: str | Path,
    *,
    stem: str,
    monthly: pd.DataFrame,
    hydro_years: pd.DataFrame,
    events: pd.DataFrame,
    low_spells: pd.DataFrame,
    summary: pd.DataFrame,
) -> dict[str, Path]:
    """Atomically write CSV report files to output_dir."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    clean_stem = safe_stem(stem)

    targets = {
        "monthly": out_path / f"{clean_stem}_monthly.csv",
        "hydro_years": out_path / f"{clean_stem}_hydro_years.csv",
        "events": out_path / f"{clean_stem}_events.csv",
        "low_spells": out_path / f"{clean_stem}_low_spells.csv",
        "summary": out_path / f"{clean_stem}_summary.csv",
    }
    frames = {
        "monthly": monthly,
        "hydro_years": hydro_years,
        "events": events,
        "low_spells": low_spells,
        "summary": summary,
    }

    for key, target in targets.items():
        df = frames[key]
        with tempfile.NamedTemporaryFile(
            mode="w", dir=out_path, delete=False, suffix=".tmp", encoding="utf-8"
        ) as tmp:
            df.to_csv(tmp.name, index=False)
            tmp_name = tmp.name
        Path(tmp_name).replace(target)

    return targets


__all__ = [
    "STABLE_HY_COLUMNS",
    "build_events_export",
    "build_hydro_years_export",
    "build_monthly_export",
    "build_summary_export",
    "safe_stem",
    "write_report_csvs",
]
