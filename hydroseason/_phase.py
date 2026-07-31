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

PHASES = ("recovery", "wet", "recession", "dry")
PHASE_COLUMNS = [
    "hy_year", "phase", "phase_status", "phase_confidence", "phase_method",
    "boundary_basis", "p_wet", "p_recession", "p_dry", "p_recovery",
    "extent_pct", "candidate_usable",
]


def empty_monthly_phase(prepared: pd.DataFrame, *, method: str = "none") -> pd.DataFrame:
    """Return the stable monthly-phase schema with phase labelling disabled."""
    frame = pd.DataFrame(index=pd.DatetimeIndex(prepared.index))
    frame["hy_year"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    frame["phase"] = "unspecified"
    frame["phase_status"] = "disabled"
    frame["phase_confidence"] = np.nan
    frame["phase_method"] = method
    frame["boundary_basis"] = "robust_extrema"
    frame["p_wet"] = np.nan
    frame["p_recession"] = np.nan
    frame["p_dry"] = np.nan
    frame["p_recovery"] = np.nan
    frame["extent_pct"] = prepared["extent_pct"].to_numpy(dtype=float)
    frame["candidate_usable"] = prepared["candidate_usable"].to_numpy(dtype=bool)
    return frame.loc[:, PHASE_COLUMNS]


def _as_month(value) -> pd.Timestamp | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).to_period("M").to_timestamp()


def _months_in(prepared: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return prepared.loc[start:end].index


def _confidence(row: pd.Series, *, has_half_loss: bool, unusable: bool) -> float:
    score = 0.55
    if row.get("boundary_status") == "confirmed":
        score += 0.20
    if has_half_loss:
        score += 0.10
    if row.get("peak_selection_status") == "raw":
        score += 0.10
    if unusable:
        score -= 0.25
    return float(np.clip(score, 0.0, 1.0))


def _first_wet_transition(
    prepared: pd.DataFrame,
    *,
    start: pd.Timestamp,
    peak: pd.Timestamp,
    previous_trough: pd.Timestamp,
    peak_extent_pct: float,
    noise_pp: float,
) -> pd.Timestamp:
    pre_peak = prepared.loc[start:peak]
    if pre_peak.empty:
        return peak
    previous_extent = prepared.loc[previous_trough, "extent_pct"] if previous_trough in prepared.index else np.nan
    if pd.isna(previous_extent):
        previous_extent = pre_peak["extent_pct"].dropna().iloc[0]
    mid_level = (float(previous_extent) + float(peak_extent_pct)) / 2.0

    usable = pre_peak.loc[pre_peak["candidate_usable"] & pre_peak["extent_pct"].notna(), "extent_pct"]
    if usable.empty:
        return peak
    slopes = usable.diff()
    slopes.iloc[0] = float(usable.iloc[0]) - float(previous_extent)
    candidates = usable.loc[usable.ge(mid_level - noise_pp) & slopes.ge(0.0)]
    if candidates.empty:
        return peak
    return pd.Timestamp(candidates.index[0])


def _fallback_recession_end(
    prepared: pd.DataFrame,
    *,
    peak: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.Timestamp | None:
    post_peak = prepared.loc[peak + pd.DateOffset(months=1):end].index
    if post_peak.empty:
        return None
    if len(post_peak) == 1:
        return None
    return pd.Timestamp(post_peak[(len(post_peak) - 1) // 2])


def assign_rule_based_phases(
    prepared: pd.DataFrame,
    hydro_years: pd.DataFrame,
    *,
    noise_pp: float,
) -> pd.DataFrame:
    """Assign deterministic descriptive phases anchored to robust annual cycles."""
    out = empty_monthly_phase(prepared, method="rule_based")
    out["phase_status"] = "outside_cycle"

    for _, row in hydro_years.iterrows():
        start = _as_month(row.get("hy_start"))
        end = _as_month(row.get("hy_end"))
        if row.get("status") == "complete" or start is None or end is None:
            continue
        months = _months_in(prepared, start, end)
        out.loc[months, "hy_year"] = int(row["hy_year"])
        out.loc[months, "phase_status"] = "unresolved_cycle"

    for _, row in hydro_years.loc[hydro_years["status"].eq("complete")].iterrows():
        start = _as_month(row.get("hy_start"))
        end = _as_month(row.get("hy_end"))
        peak = _as_month(row.get("peak_month"))
        if start is None or end is None or peak is None:
            continue
        previous_trough = start - pd.DateOffset(months=1)
        wet_start = _first_wet_transition(
            prepared,
            start=start,
            peak=peak,
            previous_trough=previous_trough,
            peak_extent_pct=float(row["peak_extent_pct"]),
            noise_pp=noise_pp,
        )

        half_loss = _as_month(row.get("half_loss_month"))
        has_half_loss = half_loss is not None and peak < half_loss <= end
        recession_end = (
            half_loss
            if has_half_loss
            else _fallback_recession_end(prepared, peak=peak, end=end)
        )

        assignments = [
            (start, wet_start - pd.DateOffset(months=1), "recovery"),
            (wet_start, peak, "wet"),
        ]
        if recession_end is not None:
            assignments.append((peak + pd.DateOffset(months=1), recession_end, "recession"))
            assignments.append((recession_end + pd.DateOffset(months=1), end, "dry"))
        else:
            assignments.append((peak + pd.DateOffset(months=1), end, "dry"))

        for phase_start, phase_end, phase in assignments:
            if phase_start > phase_end:
                continue
            months = _months_in(prepared, phase_start, phase_end)
            out.loc[months, "hy_year"] = int(row["hy_year"])
            out.loc[months, "phase"] = phase

        out.loc[peak, "phase"] = "wet"
        out.loc[end, "phase"] = "dry"
        cycle_months = _months_in(prepared, start, end)
        usable = out.loc[cycle_months, "candidate_usable"].astype(bool)
        status = np.where(usable, "ok", "unusable")
        confidence = [
            _confidence(row, has_half_loss=has_half_loss, unusable=not bool(is_usable))
            for is_usable in usable
        ]
        out.loc[cycle_months, "phase_status"] = status
        out.loc[cycle_months, "phase_confidence"] = confidence

    return out.loc[:, PHASE_COLUMNS]


def assign_monthly_phases(
    prepared: pd.DataFrame,
    hydro_years: pd.DataFrame,
    config: DynamicHydroYearConfig,
    *,
    noise_pp: float,
) -> pd.DataFrame:
    """Dispatch monthly phase labelling without mutating annual products."""
    if config.phase_model == "none":
        return empty_monthly_phase(prepared)
    if config.phase_model == "rule_based":
        return assign_rule_based_phases(prepared, hydro_years, noise_pp=noise_pp)
    raise ValueError(f"unknown phase_model {config.phase_model!r}")
