"""Monthly hydrological phase helpers anchored to robust annual cycles.

Phase labels are a separate monthly product. They never rewrite annual
boundaries, peaks, troughs, or condition baselines.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from ._dynamic_year import DynamicHydroYearConfig

PHASE_COLUMNS = [
    "hy_year", "phase", "phase_status", "phase_confidence", "phase_method",
    "boundary_basis", "extent_pct", "candidate_usable",
]


def empty_monthly_phase(prepared: pd.DataFrame, *, method: str = "none", boundary_basis: str = "robust_extrema") -> pd.DataFrame:
    """Return the stable monthly-phase schema with phase labelling disabled.

    ``boundary_basis`` must reflect the detector that actually produced the
    annual boundaries this frame is anchored to; it is never hard-coded here
    so it cannot silently claim ``robust_extrema`` for a different engine.
    """
    frame = pd.DataFrame(index=pd.DatetimeIndex(prepared.index))
    frame["hy_year"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    frame["phase"] = "unspecified"
    frame["phase_status"] = "disabled"
    frame["phase_confidence"] = np.nan
    frame["phase_method"] = method
    frame["boundary_basis"] = boundary_basis
    frame["extent_pct"] = prepared["extent_pct"].to_numpy(dtype=float)
    frame["candidate_usable"] = prepared["candidate_usable"].to_numpy(dtype=bool)
    return frame.loc[:, PHASE_COLUMNS]


def _as_month(value) -> pd.Timestamp | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).to_period("M").to_timestamp()


def _months_in(prepared: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return prepared.loc[start:end].index


def _confidence(row: pd.Series, *, unusable: bool) -> float:
    score = 0.55
    if row.get("boundary_status") == "confirmed":
        score += 0.20
    if row.get("peak_selection_status") == "raw":
        score += 0.10
    if unusable:
        score -= 0.25
    return float(np.clip(score, 0.0, 1.0))


def assign_two_phase_phases(
    prepared: pd.DataFrame,
    hydro_years: pd.DataFrame,
    *,
    boundary_basis: str = "robust_extrema",
) -> pd.DataFrame:
    out = empty_monthly_phase(
        prepared,
        method="two_phase",
        boundary_basis=boundary_basis,
    )
    out["phase_status"] = "outside_cycle"
    for _, row in hydro_years.iterrows():
        start = _as_month(row.get("hy_start"))
        end = _as_month(row.get("hy_end"))
        peak = _as_month(row.get("peak_month"))
        if start is None or end is None or peak is None or not (start <= peak <= end):
            continue
        cycle_months = _months_in(prepared, start, end)
        out.loc[cycle_months, "hy_year"] = int(row["hy_year"])
        timing_status = row.get("timing_status")
        if timing_status == "unresolved":
            out.loc[cycle_months, "phase_status"] = "unresolved_cycle"
            continue
        recovery = _months_in(prepared, start, peak)
        recession = _months_in(prepared, peak + pd.DateOffset(months=1), end)
        out.loc[recovery, "phase"] = "rising"
        out.loc[recession, "phase"] = "receding"
        usable = out.loc[cycle_months, "candidate_usable"].astype(bool)
        if timing_status in {"interval", "broad"}:
            base_status = "interval_boundary"
        else:
            base_status = "ok" if row.get("status") == "complete" else "provisional"
        out.loc[cycle_months, "phase_status"] = np.where(usable, base_status, "unusable")
        out.loc[cycle_months, "phase_confidence"] = [
            _confidence(row, unusable=not bool(value))
            for value in usable
        ]
    return out.loc[:, PHASE_COLUMNS]


def assign_monthly_phases(
    prepared: pd.DataFrame,
    hydro_years: pd.DataFrame,
    config: DynamicHydroYearConfig,
    *,
    boundary_basis: str | None = None,
) -> pd.DataFrame:
    """Dispatch monthly phase labelling without mutating annual products.

    ``boundary_basis`` is always taken from ``boundary_basis`` or
    ``config.detector`` (the engine that actually produced ``hydro_years``),
    never hard-coded, so provenance cannot lie about which detector the
    annual boundaries came from.
    """
    basis = boundary_basis or config.detector
    if config.phase_scheme == "none":
        return empty_monthly_phase(prepared, boundary_basis=basis)
    if config.phase_scheme == "two_phase":
        return assign_two_phase_phases(prepared, hydro_years, boundary_basis=basis)
    raise ValueError(f"unknown phase_scheme {config.phase_scheme!r}")


__all__ = [
    "PHASE_COLUMNS",
    "assign_monthly_phases",
    "assign_two_phase_phases",
    "empty_monthly_phase",
]
