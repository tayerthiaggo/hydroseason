from __future__ import annotations

import numpy as np
import pandas as pd

from ._state_input import prepare_monthly_extent


_JOINT_STATE_MAP: dict[tuple[str, str], str] = {
    ("high", "high"): "wet_persistent",
    ("high", "low"): "recharged_then_contracting",
    ("low", "high"): "buffered_low_recharge",
    ("low", "low"): "dry_low_refuge",
}


def _join_conditions(recharge: str, refuge: str) -> str:
    """Combine recharge/refuge conditions into the joint annual label."""
    return _JOINT_STATE_MAP.get((recharge, refuge), "typical_or_mixed")


def _empirical_percentile(value: float, reference: pd.Series) -> float:
    clean = reference.dropna().to_numpy(float)
    if not len(clean):
        return np.nan
    return 100.0 * (np.sum(clean < value) + 0.5 * np.sum(clean == value)) / len(clean)


def _rolling_baseline_index(order, position, eligible, window_cycles, min_cycles):
    """Return (baseline positional labels, mode, uncertain) for one HY row.

    ``order`` is the chronological positional index array (0..n-1). ``position``
    is the current row's position. ``eligible`` is a boolean array (same length)
    marking rows allowed to anchor the baseline (complete + confirmed). The
    baseline is the eligible rows strictly *before* ``position``; expanding
    below ``window_cycles``, sliding to the most recent ``window_cycles`` at or
    above it.
    """
    prior = [p for p in order[:position] if eligible[p]]
    prior_n = len(prior)
    if prior_n < min_cycles:
        return [], "insufficient", False
    if prior_n < window_cycles:
        return prior, "expanding", True
    return prior[-window_cycles:], "rolling", False


def _condition(percentile: float, low: float, high: float) -> str:
    if pd.isna(percentile):
        return "insufficient_baseline"
    if percentile <= low:
        return "low"
    if percentile >= high:
        return "high"
    return "typical"


def classify_annual_surface_water_condition(
    annual: pd.DataFrame,
    *,
    reference: str = "full_record",
    reference_start: str | pd.Timestamp | None = None,
    reference_end: str | pd.Timestamp | None = None,
    rolling_window_cycles: int = 10,
    rolling_min_cycles: int = 5,
    min_baseline_cycles: int = 10,
    low_percentile: float = 20.0,
    high_percentile: float = 80.0,
    low_variability: bool = False,
    allow_low_variability_labels: bool = False,
    noise_pp: float | None = None,
) -> pd.DataFrame:
    if reference not in ("full_record", "rolling") and (reference_start is None or reference_end is None):
        raise ValueError("reference must be 'full_record', 'rolling', or include reference_start and reference_end.")
    if reference == "rolling" and not 1 <= rolling_min_cycles <= rolling_window_cycles:
        raise ValueError("rolling params must satisfy 1 <= rolling_min_cycles <= rolling_window_cycles.")
    if not 0 <= low_percentile < high_percentile <= 100:
        raise ValueError("condition percentiles must satisfy 0 <= low < high <= 100.")
    out = annual.copy().sort_values("hy_year").reset_index(drop=True)
    complete = out["status"].eq("complete")
    reference_mask = complete.copy()
    # A cycle may only anchor the baseline if its trough boundary is trustworthy.
    # ``status == "complete"`` already implies a confirmed boundary for frames
    # produced by the robust detector, but we add this defensive second gate for
    # any caller whose frame carries an explicit ``boundary_status`` column
    # (provisional boundaries must never enter the baseline). The check is
    # conditional: callers that never ran the robust detector have no such column
    # and keep the original ``status``-only behaviour.
    if "boundary_status" in out.columns:
        reference_mask &= out["boundary_status"].eq("confirmed")
    if reference_start is not None:
        dates = pd.to_datetime(out["hy_end"])
        reference_mask &= dates.between(pd.Timestamp(reference_start), pd.Timestamp(reference_end))

    out["baseline_mode"] = "full" if reference == "full_record" else ("fixed" if reference != "rolling" else "")
    out["baseline_n"] = 0
    out["baseline_uncertain"] = False

    if reference == "rolling":
        order = list(range(len(out)))
        eligible = reference_mask.to_numpy()
        for source, target in (("peak_extent_pct", "peak_percentile"), ("trough_extent_pct", "trough_percentile")):
            values = []
            for position in order:
                labels, mode, uncertain = _rolling_baseline_index(
                    order, position, eligible, rolling_window_cycles, rolling_min_cycles
                )
                if source == "peak_extent_pct":  # record mode once, on the first axis pass
                    out.iloc[position, out.columns.get_loc("baseline_mode")] = mode
                    out.iloc[position, out.columns.get_loc("baseline_n")] = len(labels)
                    out.iloc[position, out.columns.get_loc("baseline_uncertain")] = uncertain
                baseline = out.iloc[labels][source] if labels else out[source].iloc[0:0]
                cell = out.iloc[position][source]
                values.append(_empirical_percentile(float(cell), baseline) if pd.notna(cell) and len(baseline) else np.nan)
            out[target] = values
        enough = True  # per-row insufficiency already encoded in baseline_mode
    else:
        for source, target in (("peak_extent_pct", "peak_percentile"), ("trough_extent_pct", "trough_percentile")):
            values = []
            for index, row in out.iterrows():
                baseline = out.loc[reference_mask, source]
                if reference_mask.loc[index]:
                    baseline = baseline.drop(index=index)
                values.append(_empirical_percentile(float(row[source]), baseline) if pd.notna(row[source]) else np.nan)
            out[target] = values
        enough = int(reference_mask.sum()) >= min_baseline_cycles

    if enough:
        out["recharge_condition"] = out["peak_percentile"].map(lambda value: _condition(value, low_percentile, high_percentile))
        out["refuge_condition"] = out["trough_percentile"].map(lambda value: _condition(value, low_percentile, high_percentile))
    else:
        out["recharge_condition"] = "insufficient_baseline"
        out["refuge_condition"] = "insufficient_baseline"
    out["annual_condition"] = [
        _join_conditions(recharge, refuge)
        for recharge, refuge in zip(out["recharge_condition"], out["refuge_condition"])
    ]
    if not enough:
        out["annual_condition"] = "insufficient_baseline"
    if reference == "rolling":
        insufficient_rows = out["baseline_mode"] == "insufficient"
        out.loc[insufficient_rows, ["recharge_condition", "refuge_condition"]] = "insufficient_baseline"
        out.loc[insufficient_rows, "annual_condition"] = "insufficient_baseline"
    if low_variability and not allow_low_variability_labels:
        out[["recharge_condition", "refuge_condition", "annual_condition"]] = "not_applicable_low_variability"

    out["peak_change_from_previous_pct"] = out["peak_extent_pct"].diff()
    out["trough_change_from_previous_pct"] = out["trough_extent_pct"].diff()
    dry_count = wet_count = 0
    dry_counts, wet_counts = [], []
    for state in out["annual_condition"]:
        dry_count = dry_count + 1 if state == "dry_low_refuge" else 0
        wet_count = wet_count + 1 if state == "wet_persistent" else 0
        dry_counts.append(dry_count)
        wet_counts.append(wet_count)
    out["consecutive_dry_cycles"] = dry_counts
    out["consecutive_wet_cycles"] = wet_counts

    # Baseline median per row, per axis, matching the reference mode used above.
    def _baseline_median(source):
        medians = []
        if reference == "rolling":
            order = list(range(len(out)))
            eligible = reference_mask.to_numpy()
            for position in order:
                labels, _mode, _unc = _rolling_baseline_index(
                    order, position, eligible, rolling_window_cycles, rolling_min_cycles
                )
                base = out.iloc[labels][source] if labels else out[source].iloc[0:0]
                medians.append(float(base.median()) if len(base) else np.nan)
        else:
            for index, _row in out.iterrows():
                base = out.loc[reference_mask, source]
                if reference_mask.loc[index]:
                    base = base.drop(index=index)
                medians.append(float(base.median()) if len(base) else np.nan)
        return medians

    peak_median = _baseline_median("peak_extent_pct")
    trough_median = _baseline_median("trough_extent_pct")

    out["noise_floor_pp"] = float(noise_pp) if noise_pp is not None else np.nan

    def _qualify(condition_col, extent_col, medians):
        qualified = []
        for position, (_index, row) in enumerate(out.iterrows()):
            label = row[condition_col]
            if noise_pp is None or label not in ("low", "high"):
                qualified.append(label)
                continue
            median = medians[position]
            departure = abs(float(row[extent_col]) - median) if pd.notna(median) else np.inf
            qualified.append("typical_uncertain" if departure < float(noise_pp) else label)
        return qualified

    out["recharge_condition_qualified"] = _qualify("recharge_condition", "peak_extent_pct", peak_median)
    out["refuge_condition_qualified"] = _qualify("refuge_condition", "trough_extent_pct", trough_median)
    out["annual_condition_qualified"] = [
        _join_conditions(recharge, refuge)
        for recharge, refuge in zip(out["recharge_condition_qualified"], out["refuge_condition_qualified"])
    ]
    # Preserve the special-case labels the unhedged annual_condition uses.
    special = out["annual_condition"].isin(["insufficient_baseline", "not_applicable_low_variability"])
    out.loc[special, "annual_condition_qualified"] = out.loc[special, "annual_condition"]

    return out


def compute_monthly_surface_water_condition(
    extent,
    *,
    reference_start=None,
    reference_end=None,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    max_invalid_pct: float = 20.0,
    allow_unknown_quality: bool = False,
) -> pd.DataFrame:
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=max_invalid_pct, allow_unknown_quality=allow_unknown_quality,
    )
    reference_mask = frame["candidate_usable"].copy()
    if reference_start is not None or reference_end is not None:
        if reference_start is None or reference_end is None:
            raise ValueError("reference_start and reference_end must be supplied together.")
        reference_mask &= frame.index.to_series().between(pd.Timestamp(reference_start), pd.Timestamp(reference_end)).to_numpy()
    rows = []
    for date, row in frame.iterrows():
        baseline = frame.loc[reference_mask & (frame.index.month == date.month), "extent_pct"]
        if date in baseline.index:
            baseline = baseline.drop(index=date)
        usable = bool(row["candidate_usable"])
        median = float(baseline.median()) if len(baseline) else np.nan
        rows.append(
            {
                "extent_pct": row["extent_pct"],
                "reference_median_pct": median,
                "anomaly_pct": float(row["extent_pct"] - median) if usable and pd.notna(median) else np.nan,
                "condition_percentile": _empirical_percentile(float(row["extent_pct"]), baseline) if usable else np.nan,
                "reference_n": int(len(baseline)),
                "quality_state": row["quality_state"],
            }
        )
    return pd.DataFrame(rows, index=frame.index)
