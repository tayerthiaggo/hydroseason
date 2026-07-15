from __future__ import annotations

import numpy as np
import pandas as pd

from ._state_input import prepare_monthly_extent


def _empirical_percentile(value: float, reference: pd.Series) -> float:
    clean = reference.dropna().to_numpy(float)
    if not len(clean):
        return np.nan
    return 100.0 * (np.sum(clean < value) + 0.5 * np.sum(clean == value)) / len(clean)


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
    min_baseline_cycles: int = 10,
    low_percentile: float = 20.0,
    high_percentile: float = 80.0,
    low_variability: bool = False,
    allow_low_variability_labels: bool = False,
) -> pd.DataFrame:
    if reference != "full_record" and (reference_start is None or reference_end is None):
        raise ValueError("reference must be 'full_record' or include reference_start and reference_end.")
    if not 0 <= low_percentile < high_percentile <= 100:
        raise ValueError("condition percentiles must satisfy 0 <= low < high <= 100.")
    out = annual.copy().sort_values("hy_year").reset_index(drop=True)
    complete = out["status"].eq("complete")
    reference_mask = complete.copy()
    if reference_start is not None:
        dates = pd.to_datetime(out["hy_end"])
        reference_mask &= dates.between(pd.Timestamp(reference_start), pd.Timestamp(reference_end))

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
    mapping = {
        ("high", "high"): "wet_persistent",
        ("high", "low"): "recharged_then_contracting",
        ("low", "high"): "buffered_low_recharge",
        ("low", "low"): "dry_low_refuge",
    }
    out["annual_condition"] = [mapping.get(pair, "typical_or_mixed") for pair in zip(out["recharge_condition"], out["refuge_condition"])]
    if not enough:
        out["annual_condition"] = "insufficient_baseline"
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
