"""Route-aware report frames, user-facing CSV projections, and CSV writing.

The internal ``build_*_export`` functions preserve every source month and
diagnostic field.  ``build_user_*_export`` functions project those frames into
the compact default CSV schemas. Both layers use stable empty schemas,
explicit closed-interval membership, nullable identifiers, route authority,
and optional rainfall month alignment. Do not infer membership by row position.
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

# The generated CSV bundle is deliberately smaller and more literal than the
# internal diagnostic frames used to render HTML.  These are the stable,
# user-facing schemas; the full frames remain available through the build_*
# helpers for analysts and for the HTML layer.
DEFAULT_REPORT_NAME = "HydroSeason results"

MONTHLY_CSV_COLUMNS = [
    "date",
    "extent_pct",
    "invalid_pct",
    "max_invalid_pct",
    "baseline_extent_pct",
    "usable_month",
    "quality_state",
    "hy_year",
    "phase",
    "phase_status",
    "is_hy_peak",
    "is_hy_mid_dry",
    "is_hy_trough",
    "in_wet_event",
    "wet_event_id",
    "in_low_spell",
    "low_spell_id",
    "regime",
    "route",
]

HY_CSV_COLUMNS = [
    "catchment",
    "hy_year",
    "start_date",
    "end_date",
    "peak_date",
    "mid_dry_date",
    "trough_date",
    "peak_extent_pct",
    "mid_dry_extent_pct",
    "trough_extent_pct",
    "peak_invalid_pct",
    "mid_dry_invalid_pct",
    "trough_invalid_pct",
    "drawdown_pct",
    "confidence",
    "status",
    "boundary_status",
    "boundary_basis",
    "regime",
    "route",
]

EVENT_CSV_COLUMNS = [
    "event_id",
    "start_date",
    "end_date",
    "duration_months",
    "baseline_extent_pct",
    "peak_date",
    "peak_extent_pct",
    "mean_extent_pct",
    "magnitude_pp_months",
]

LOW_SPELL_CSV_COLUMNS = [
    "low_spell_id",
    "start_date",
    "end_date",
    "duration_months",
    "baseline_extent_pct",
    "min_extent_pct",
]


def safe_stem(name: str) -> str:
    """Sanitize catchment name into safe filename stem."""
    stem = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return stem or "catchment"


def normalise_report_name(name: str | None) -> str:
    """Return the display name used in reports and metadata columns."""
    if name is None:
        return DEFAULT_REPORT_NAME
    value = str(name).strip()
    return value or DEFAULT_REPORT_NAME


def build_monthly_export(
    extent: Any,
    *,
    analysis: CatchmentAnalysis,
    rainfall: Any | None = None,
) -> pd.DataFrame:
    """Build a complete, monthly timeline export matching source length and alignment."""
    prepared = prepare_monthly_extent(
        extent,
        max_invalid_pct=analysis.max_invalid_pct,
        quality_policy=analysis.quality_policy,
    )

    if analysis.state is not None:
        cond_df = analysis.state.monthly_condition
        phase_df = analysis.state.monthly_phase
    else:
        cond_df = compute_monthly_surface_water_condition(
            extent,
            max_invalid_pct=analysis.max_invalid_pct,
            quality_policy=analysis.quality_policy,
        )
        # Routes without a state object may still carry phases (the imposed
        # fixed window does). Reindex onto the export's own month grid so a
        # phase frame built from a differently-trimmed record cannot shift
        # labels by a row.
        if analysis.monthly_phase is not None:
            phase_df = analysis.monthly_phase.reindex(prepared.index)
            phase_df["phase"] = phase_df["phase"].fillna("unspecified")
        else:
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


def _first_column(frame: pd.DataFrame, *names: str) -> pd.Series:
    """Return the first available column, or a correctly-sized NA series."""
    for name in names:
        if name in frame.columns:
            return frame[name]
    return pd.Series(pd.NA, index=frame.index)


def _mark_monthly_mid_dry(
    monthly: pd.DataFrame,
    hydro_years: pd.DataFrame | None,
) -> pd.Series:
    """Mark the observed mid-dry month without adding it to the HTML frame."""
    marker = pd.Series(False, index=monthly.index, dtype="boolean")
    if hydro_years is None or hydro_years.empty or "date" not in monthly.columns:
        return marker
    dates = pd.to_datetime(monthly["date"], errors="coerce")
    mid_dates = _first_column(
        hydro_years,
        "temporal_mid_dry_month",
        "mid_dry_month",
    )
    for value in pd.to_datetime(mid_dates, errors="coerce").dropna():
        marker |= dates.eq(value)
    return marker


def build_user_monthly_export(
    monthly: pd.DataFrame,
    *,
    hydro_years: pd.DataFrame | None = None,
    analysis: CatchmentAnalysis | None = None,
) -> pd.DataFrame:
    """Project the complete monthly frame into the stable user CSV schema."""
    out = monthly.copy()
    out["is_hy_mid_dry"] = _mark_monthly_mid_dry(out, hydro_years)

    if analysis is not None:
        out["max_invalid_pct"] = float(analysis.max_invalid_pct)
        event_summary = analysis.events.summary if analysis.events is not None else {}
        out["baseline_extent_pct"] = float(
            event_summary.get("baseline_pct", np.nan)
        )
        if analysis.state is not None and "phase_status" in analysis.state.monthly_phase:
            out["phase_status"] = analysis.state.monthly_phase["phase_status"].to_numpy()
        else:
            out["phase_status"] = "disabled"

    # Keep optional rainfall context, but do not expose condition-model
    # intermediates in the default bundle.
    for col in MONTHLY_CSV_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    columns = MONTHLY_CSV_COLUMNS + [
        col for col in ("rainfall_mm", "rain_anomaly_mm") if col in out.columns
    ]
    return out.loc[:, columns].reset_index(drop=True)


def build_user_hydro_years_export(hydro_years: pd.DataFrame) -> pd.DataFrame:
    """Project dynamic and fixed HY detector rows into one readable schema."""
    out = pd.DataFrame(index=hydro_years.index)
    aliases = {
        "catchment": ("catchment",),
        "hy_year": ("hy_year",),
        "start_date": ("hy_start", "start"),
        "end_date": ("hy_end", "end"),
        "peak_date": ("peak_month",),
        "mid_dry_date": ("temporal_mid_dry_month", "mid_dry_month"),
        "trough_date": ("trough_month", "end_dry_month"),
        "peak_extent_pct": ("peak_extent_pct",),
        "mid_dry_extent_pct": (
            "temporal_mid_dry_extent_pct",
            "mid_extent_pct",
        ),
        "trough_extent_pct": ("trough_extent_pct", "end_dry_extent_pct"),
        "peak_invalid_pct": ("peak_invalid_pct",),
        "mid_dry_invalid_pct": ("mid_dry_invalid_pct",),
        "trough_invalid_pct": ("trough_invalid_pct",),
        "drawdown_pct": ("drawdown_pct", "amplitude_pct"),
        "confidence": ("confidence",),
        "status": ("status",),
        "boundary_status": ("boundary_status",),
        "boundary_basis": ("boundary_basis",),
        "regime": ("regime",),
        "route": ("route",),
    }
    for target, source_names in aliases.items():
        out[target] = _first_column(hydro_years, *source_names).to_numpy()

    # Stable empty files still have the same header as populated files.
    return out.reindex(columns=HY_CSV_COLUMNS).reset_index(drop=True)


def build_user_events_export(
    events: pd.DataFrame,
    *,
    baseline_extent_pct: float | None = None,
) -> pd.DataFrame:
    """Use explicit date names in the wet-event CSV."""
    out = events.rename(
        columns={"start": "start_date", "end": "end_date", "peak_month": "peak_date"}
    ).copy()
    out["baseline_extent_pct"] = baseline_extent_pct
    for col in EVENT_CSV_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    return out.loc[:, EVENT_CSV_COLUMNS].reset_index(drop=True)


def build_user_low_spells_export(
    low_spells: pd.DataFrame,
    *,
    baseline_extent_pct: float | None = None,
) -> pd.DataFrame:
    """Use explicit date names in the low-extent-spell CSV."""
    out = low_spells.rename(
        columns={
            "spell_id": "low_spell_id",
            "start": "start_date",
            "end": "end_date",
        }
    ).copy()
    out["baseline_extent_pct"] = baseline_extent_pct
    for col in LOW_SPELL_CSV_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    return out.loc[:, LOW_SPELL_CSV_COLUMNS].reset_index(drop=True)


def write_report_csvs(
    output_dir: str | Path,
    *,
    stem: str,
    monthly: pd.DataFrame,
    hydro_years: pd.DataFrame,
    events: pd.DataFrame,
    low_spells: pd.DataFrame,
) -> dict[str, Path]:
    """Atomically write CSV report files to output_dir."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    clean_stem = safe_stem(stem)

    targets = {
        "monthly": out_path / f"{clean_stem}_monthly.csv",
        "hydro_years": out_path / f"{clean_stem}_hydro_years.csv",
        "wet_event": out_path / f"{clean_stem}_wet_event.csv",
        "low_spells": out_path / f"{clean_stem}_low_spells.csv",
    }
    frames = {
        "monthly": monthly,
        "hydro_years": hydro_years,
        "wet_event": events,
        "low_spells": low_spells,
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
    "DEFAULT_REPORT_NAME",
    "EVENT_CSV_COLUMNS",
    "HY_CSV_COLUMNS",
    "LOW_SPELL_CSV_COLUMNS",
    "MONTHLY_CSV_COLUMNS",
    "STABLE_HY_COLUMNS",
    "build_events_export",
    "build_hydro_years_export",
    "build_monthly_export",
    "build_summary_export",
    "build_user_events_export",
    "build_user_hydro_years_export",
    "build_user_low_spells_export",
    "build_user_monthly_export",
    "normalise_report_name",
    "safe_stem",
    "write_report_csvs",
]
