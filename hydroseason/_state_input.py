from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

QualityPolicy = Literal["exclude", "flag"]


def prepare_monthly_extent(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    max_invalid_pct: float = 20.0,
    allow_unknown_quality: bool = False,
    quality_policy: QualityPolicy = "flag",
) -> pd.DataFrame:
    if not 0.0 <= max_invalid_pct <= 100.0:
        raise ValueError("max_invalid_pct must be between 0 and 100.")
    if quality_policy not in {"exclude", "flag"}:
        raise ValueError("quality_policy must be 'exclude' or 'flag'.")
    if isinstance(extent, pd.Series):
        frame = extent.rename(value_col).to_frame()
    else:
        frame = extent.copy()
    if date_col is not None:
        frame.index = pd.to_datetime(frame.pop(date_col))
    elif not isinstance(frame.index, pd.DatetimeIndex) and "date" in frame.columns:
        frame.index = pd.to_datetime(frame.pop("date"))
    else:
        frame.index = pd.to_datetime(frame.index)
    frame.index = frame.index.to_period("M").to_timestamp()
    if frame.index.has_duplicates:
        months = sorted(frame.index[frame.index.duplicated(False)].strftime("%Y-%m").unique())
        raise ValueError(f"duplicate month timestamps: {months}.")
    frame = frame.sort_index()
    if frame.empty:
        return pd.DataFrame(columns=[value_col, "invalid_pct", "observed_fraction", "quality_state", "candidate_usable"])
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq="MS"))

    if "n_invalid" not in frame.columns and "n_aoi" in frame.columns and "n_valid" in frame.columns:
        frame["n_invalid"] = frame["n_aoi"] - frame["n_valid"]

    count_cols = ["n_water", "n_valid", "n_invalid", "n_aoi"]
    present = set(count_cols).intersection(frame.columns)
    if present and present != set(count_cols):
        missing = sorted(set(count_cols) - present)
        raise ValueError(f"pixel-count input requires all count columns; missing {missing}.")
    if present:
        counts = frame[count_cols].apply(pd.to_numeric, errors="coerce")
        if (counts.dropna() < 0).any().any():
            raise ValueError("pixel counts must be non-negative.")
        complete_counts = counts.dropna()
        if ((complete_counts["n_water"] > complete_counts["n_valid"]) | (complete_counts["n_valid"] + complete_counts["n_invalid"] != complete_counts["n_aoi"])).any():
            raise ValueError("pixel counts violate n_water <= n_valid and n_valid + n_invalid == n_aoi.")
        frame[value_col] = np.where(counts["n_valid"] > 0, 100.0 * counts["n_water"] / counts["n_valid"], np.nan)
        frame["invalid_pct"] = np.where(counts["n_aoi"] > 0, 100.0 * counts["n_invalid"] / counts["n_aoi"], np.nan)

    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    if ((frame[value_col] < 0) | (frame[value_col] > 100)).dropna().any():
        raise ValueError("extent_pct must be between 0 and 100.")
    if "invalid_pct" not in frame:
        frame["invalid_pct"] = np.nan
    frame["invalid_pct"] = pd.to_numeric(frame["invalid_pct"], errors="coerce")
    if ((frame["invalid_pct"] < 0) | (frame["invalid_pct"] > 100)).dropna().any():
        raise ValueError("invalid_pct must be between 0 and 100.")

    frame["observed_fraction"] = 1.0 - frame["invalid_pct"] / 100.0
    frame["quality_state"] = np.select(
        [
            frame[value_col].isna(),
            frame["invalid_pct"].isna(),
            frame["invalid_pct"] > max_invalid_pct,
        ],
        ["missing", "unknown", "low"],
        default="usable",
    )
    if quality_policy == "flag":
        # A finite extent with partial invalid coverage remains an observed
        # candidate under ``flag``.  At 100% invalid there are no valid pixels
        # supporting the extent, so it remains unusable even in flag mode.
        frame["candidate_usable"] = frame[value_col].notna() & (
            frame["invalid_pct"].isna() | frame["invalid_pct"].lt(100.0)
        )
    else:
        frame["candidate_usable"] = (frame["quality_state"] == "usable") | (
            allow_unknown_quality & (frame["quality_state"] == "unknown")
        )
    return frame.rename(columns={value_col: "extent_pct"})


# Fitting weight floor. A month observed at 0.5% still carries real signal
# about its own value, so it is down-weighted rather than discarded; without a
# floor its weight underflows to effectively zero and the month is silently
# dropped from every fit.
_MIN_CANDIDATE_WEIGHT = 0.05


def candidate_weights(prepared: pd.DataFrame, *, min_weight: float = _MIN_CANDIDATE_WEIGHT) -> pd.Series:
    """Per-month weight for weighted fits: observed fraction, zero if unusable.

    ``observed_fraction`` is NaN when ``invalid_pct`` is unknown. An unknown
    invalid fraction is not evidence of poor observation, so those months are
    weighted as fully observed; ``candidate_usable`` is what decides whether
    they enter the fit at all.
    """
    if not 0.0 < min_weight <= 1.0:
        raise ValueError("min_weight must be in (0, 1].")
    observed = pd.to_numeric(prepared["observed_fraction"], errors="coerce")
    weights = observed.where(observed.notna(), 1.0).clip(lower=min_weight, upper=1.0)
    return weights.where(prepared["candidate_usable"].to_numpy(dtype=bool), 0.0).astype(float)

