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


def _monthly_baseline(prepared: pd.DataFrame) -> pd.Series:
    usable = prepared.loc[
        prepared["candidate_usable"] & prepared["extent_pct"].notna(),
        "extent_pct",
    ]
    if usable.empty:
        return pd.Series(dtype=float)
    return usable.groupby(usable.index.month).median()


def _first_baseline_crossing(
    prepared: pd.DataFrame,
    *,
    start: pd.Timestamp,
    peak: pd.Timestamp,
    baseline: pd.Series,
    noise_pp: float,
) -> pd.Timestamp:
    window = prepared.loc[start:peak]
    if window.empty:
        return peak
    values = window["extent_pct"]
    levels = pd.Series(
        [baseline.get(date.month, np.nan) for date in window.index],
        index=window.index,
        dtype=float,
    )
    usable = window["candidate_usable"] & values.notna() & levels.notna()
    if not usable.any():
        return peak
    slopes = values.diff()
    previous = start - pd.DateOffset(months=1)
    previous_value = prepared.loc[previous, "extent_pct"] if previous in prepared.index else values.iloc[0]
    slopes.iloc[0] = values.iloc[0] - previous_value
    candidates = window.index[usable & values.ge(levels) & slopes.ge(-float(noise_pp))]
    if len(candidates) == 0:
        return peak
    return pd.Timestamp(candidates[0])


def _first_baseline_downcrossing(
    prepared: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    baseline: pd.Series,
) -> pd.Timestamp | None:
    window = prepared.loc[start:end]
    if window.empty:
        return None
    values = window["extent_pct"]
    levels = pd.Series(
        [baseline.get(date.month, np.nan) for date in window.index],
        index=window.index,
        dtype=float,
    )
    usable = window["candidate_usable"] & values.notna() & levels.notna()
    candidates = window.index[usable & values.le(levels)]
    if len(candidates) == 0:
        return None
    return pd.Timestamp(candidates[0])


def _first_relative_threshold_crossing(
    prepared: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    baseline: pd.Series,
    amplitude: float,
    fraction: float,
) -> pd.Timestamp | None:
    window = prepared.loc[start:end]
    if window.empty:
        return None
    values = window["extent_pct"]
    levels = pd.Series(
        [baseline.get(date.month, np.nan) + fraction * amplitude for date in window.index],
        index=window.index,
        dtype=float,
    )
    usable = window["candidate_usable"] & values.notna() & levels.notna()
    candidates = window.index[usable & values.le(levels)]
    if len(candidates) == 0:
        return None
    return pd.Timestamp(candidates[0])


def assign_rule_based_phases(
    prepared: pd.DataFrame,
    hydro_years: pd.DataFrame,
    *,
    noise_pp: float,
    boundary_basis: str = "robust_extrema",
) -> pd.DataFrame:
    """Assign baseline-relative descriptive phases to robust annual cycles.

    The month-specific reference median is the baseline. Recovery ends when
    extent crosses that baseline while rising; wet/high-water continues through
    the peak until half the peak anomaly is lost; recession continues until the
    extent falls back through baseline; and dry continues to the trough.
    """
    out = empty_monthly_phase(prepared, method="rule_based", boundary_basis=boundary_basis)
    out["phase_status"] = "outside_cycle"
    baseline = _monthly_baseline(prepared)

    for _, row in hydro_years.iterrows():
        start = _as_month(row.get("hy_start"))
        end = _as_month(row.get("hy_end"))
        if row.get("status") == "complete" or start is None or end is None:
            continue
        months = _months_in(prepared, start, end)
        out.loc[months, "hy_year"] = int(row["hy_year"])
        out.loc[months, "phase_status"] = "unresolved_cycle"

    # Partial cycles still contain useful observed structure.  Label them
    # provisionally instead of discarding every phase and emitting a large
    # ``unspecified`` block; the annual row's status remains the authority on
    # boundary quality.
    phaseable = hydro_years.loc[hydro_years["status"].isin(["complete", "partial"])]
    for _, row in phaseable.iterrows():
        start = _as_month(row.get("hy_start"))
        end = _as_month(row.get("hy_end"))
        peak = _as_month(row.get("peak_month"))
        if start is None or end is None or peak is None:
            continue
        wet_start = _first_baseline_crossing(
            prepared,
            start=start,
            peak=peak,
            baseline=baseline,
            noise_pp=noise_pp,
        )

        peak_extent = float(row["peak_extent_pct"])
        peak_baseline = baseline.get(peak.month, np.nan)
        trough_extent = float(row.get("trough_extent_pct", np.nan))
        amplitude = peak_extent - float(peak_baseline) if pd.notna(peak_baseline) else np.nan
        if not np.isfinite(amplitude) or amplitude <= 0:
            amplitude = peak_extent - trough_extent
        if not np.isfinite(amplitude) or amplitude <= 0:
            amplitude = max(float(noise_pp), 1e-6)

        half_crossing = _first_relative_threshold_crossing(
            prepared,
            start=peak + pd.DateOffset(months=1),
            end=end,
            baseline=baseline,
            amplitude=amplitude,
            fraction=0.5,
        )
        half_start = half_crossing or peak + pd.DateOffset(months=1)
        recession_end = _first_baseline_downcrossing(
            prepared,
            start=half_start + pd.DateOffset(months=1),
            end=end,
            baseline=baseline,
        )
        dry_start = recession_end or end
        has_half_loss = half_crossing is not None

        assignments = [
            (start, wet_start - pd.DateOffset(months=1), "recovery"),
            (wet_start, half_start - pd.DateOffset(months=1), "wet"),
            (half_start, dry_start - pd.DateOffset(months=1), "recession"),
            (dry_start, end, "dry"),
        ]

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
        phase_status = "ok" if row.get("status") == "complete" else "provisional"
        status = np.where(usable, phase_status, "unusable")
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
    """Dispatch monthly phase labelling without mutating annual products.

    ``boundary_basis`` is always taken from ``config.detector`` (the engine
    that actually produced ``hydro_years``), never hard-coded, so provenance
    cannot lie about which detector the annual boundaries came from.
    """
    if config.phase_model == "none":
        return empty_monthly_phase(prepared, boundary_basis=config.detector)
    if config.phase_model == "rule_based":
        return assign_rule_based_phases(prepared, hydro_years, noise_pp=noise_pp, boundary_basis=config.detector)
    raise ValueError(f"unknown phase_model {config.phase_model!r}")
