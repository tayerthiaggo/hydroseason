"""Step 1 — Fixed (baseline) hydrological year.

Two methods are available:
- ``circular_climatology`` (default, transferable): treats months as angles on a unit
  circle, computes the resultant vector and 2nd Fourier harmonic for bimodal detection,
  then labels Wet/Dry by the angular distance from the peak.
- ``identify_fixed_hydro_year`` (legacy): KMeans(k=2) from Tayer (2025).

Both return the same DataFrame shape so downstream code can use either.
Also provides ``hydro_year_start_driest_6_months`` (Bond 2014) and
``hydro_year_start_after_min_month`` (Feng 2013) as additional baselines.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CircularStats:
    peak_month: int            # 1..12 month with maximum climatological value (data-anchored)
    peak_angle_month: float    # circular-mean month in [1, 13)
    concentration_R: float     # resultant vector length in [0, 1]
    second_harmonic_ratio: float   # amp_2 / amp_1
    is_bimodal: bool
    is_uniform: bool


def _build_climatology_frame(
    monthly_df: pd.DataFrame,
    value_col: str,
    month_col: str,
) -> pd.DataFrame:
    work = monthly_df.copy()
    work["_no_rain"] = (work[value_col] == 0).astype(int)
    no_rain = work.groupby(month_col)["_no_rain"].sum().reindex(range(1, 13), fill_value=0)

    agg = (
        work.groupby(month_col)[value_col]
        .agg(mean="mean", median="median")
        .reindex(range(1, 13))
    )
    agg["no_rain_count"] = no_rain.values
    return agg


def circular_stats(climatology_values: np.ndarray) -> CircularStats:
    """Circular statistics over 12 monthly climatology values.

    Months 1..12 are placed on a circle at angles 2π*(m-1)/12.
    The resultant vector R measures concentration; R close to 0 → uniform.
    The 2nd Fourier harmonic detects bimodality (two wet seasons).
    """
    values = np.asarray(climatology_values, dtype=float)
    if values.size != 12:
        raise ValueError("circular_stats requires 12 monthly values.")

    total = values.sum()
    if total <= 0:
        return CircularStats(
            peak_month=1,
            peak_angle_month=1.0,
            concentration_R=0.0,
            second_harmonic_ratio=0.0,
            is_bimodal=False,
            is_uniform=True,
        )

    months = np.arange(1, 13)
    theta = 2.0 * np.pi * (months - 1) / 12.0

    # Resultant vector (concentration)
    x_bar = float((values * np.cos(theta)).sum() / total)
    y_bar = float((values * np.sin(theta)).sum() / total)
    R = float(np.sqrt(x_bar * x_bar + y_bar * y_bar))

    mean_angle = float(np.arctan2(y_bar, x_bar))
    if mean_angle < 0:
        mean_angle += 2.0 * np.pi
    peak_angle_month = mean_angle / (2.0 * np.pi) * 12.0 + 1.0  # [1, 13)

    # First and second Fourier harmonics
    a1 = float((values * np.cos(theta)).sum())
    b1 = float((values * np.sin(theta)).sum())
    a2 = float((values * np.cos(2 * theta)).sum())
    b2 = float((values * np.sin(2 * theta)).sum())
    amp1 = float(np.sqrt(a1 * a1 + b1 * b1))
    amp2 = float(np.sqrt(a2 * a2 + b2 * b2))
    ratio = float(amp2 / amp1) if amp1 > 0 else 0.0

    is_uniform = R < 0.10  # near-zero concentration ≈ perennial regime
    is_bimodal = (not is_uniform) and ratio > 0.50

    peak_month = int(months[int(np.argmax(values))])

    return CircularStats(
        peak_month=peak_month,
        peak_angle_month=peak_angle_month,
        concentration_R=R,
        second_harmonic_ratio=ratio,
        is_bimodal=is_bimodal,
        is_uniform=is_uniform,
    )


def _label_wet_dry_unimodal(values: np.ndarray, peak_month: int) -> np.ndarray:
    """Climatology-aware wet/dry labeling for unimodal regimes.

    Uses circular concentration R to determine the width of the wet season:
    - R >= 0.833 -> 1 (3 wet months: peak +/- 1)
    - 0.50 <= R < 0.833 -> 2 (5 wet months: peak +/- 2)
    - R < 0.50 -> 3 (7 wet months: peak +/- 3)
    """
    stats = circular_stats(values)
    R = stats.concentration_R

    if R >= 0.833:
        max_diff = 1
    elif R >= 0.50:
        max_diff = 2
    else:
        max_diff = 3

    months = np.arange(1, 13)
    diff = np.minimum((months - peak_month) % 12, (peak_month - months) % 12)
    return np.where(diff <= max_diff, "Wet", "Dry")



def _label_wet_dry_bimodal(values: np.ndarray) -> np.ndarray:
    """For bimodal climates, label months above the median climatological value as Wet."""
    threshold = float(np.median(values))
    if threshold <= 0.0 and (values > 0.0).any():
        threshold = float(np.min(values[values > 0.0]))
    return np.where(values >= threshold, "Wet", "Dry")


def _label_wet_dry_uniform() -> np.ndarray:
    return np.array(["Unclassified"] * 12)


def _first_dry_to_wet(seasons: np.ndarray) -> int | None:
    months = np.arange(1, 13)
    for i in range(12):
        prev_idx = (i - 1) % 12
        if seasons[prev_idx] == "Dry" and seasons[i] == "Wet":
            return int(months[i])
    return None


def circular_climatology(
    monthly_df: pd.DataFrame,
    *,
    value_col: str = "Rainfall_mm",
    month_col: str = "Month",
) -> tuple[pd.DataFrame, int | None, CircularStats]:
    """Transferable, climatology-aware fixed-season detection.

    Returns
    -------
    (climatology_df, hydro_year_start_month, stats)
        climatology_df has columns: mean, median, no_rain_count, Season.
        hydro_year_start_month is the first Dry→Wet transition month (1..12), or None
        if the regime is uniform / no transition exists.
    """
    clim = _build_climatology_frame(monthly_df, value_col=value_col, month_col=month_col)
    values = clim["mean"].fillna(0.0).to_numpy()
    stats = circular_stats(values)

    if stats.is_uniform:
        seasons = _label_wet_dry_uniform()
    elif stats.is_bimodal:
        seasons = _label_wet_dry_bimodal(values)
    else:
        seasons = _label_wet_dry_unimodal(values, stats.peak_month)

    clim["Season"] = seasons
    start_month = _first_dry_to_wet(seasons) if not stats.is_uniform else None
    return clim, start_month, stats


# ---------------------------------------------------------------------------
# Legacy KMeans method (kept for parity with the paper)
# ---------------------------------------------------------------------------
def identify_fixed_hydro_year(
    monthly_df: pd.DataFrame,
    *,
    value_col: str = "Rainfall_mm",
    month_col: str = "Month",
) -> tuple[pd.DataFrame, int | None]:
    """KMeans(k=2) over (mean, no_rain_count). Tayer (2025) prototype."""
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        # No sklearn → fall back to circular method
        clim, start, _ = circular_climatology(monthly_df, value_col=value_col, month_col=month_col)
        return clim, start

    clim = _build_climatology_frame(monthly_df, value_col=value_col, month_col=month_col)
    features = pd.DataFrame({"mean": clim["mean"].fillna(0.0), "no_rain": clim["no_rain_count"]})
    x = StandardScaler().fit_transform(features)

    try:
        labels = KMeans(n_clusters=2, n_init="auto", random_state=0).fit_predict(x)
    except Exception as exc:  # noqa: BLE001 — fall back to a median threshold split
        warnings.warn(
            f"KMeans clustering failed ({exc}); falling back to a median rainfall split.",
            RuntimeWarning,
            stacklevel=2,
        )
        thresh = float(features["mean"].median())
        labels = (features["mean"] > thresh).astype(int).to_numpy()

    if features["mean"][labels == 0].mean() > features["mean"][labels == 1].mean():
        season_map = {0: "Wet", 1: "Dry"}
    else:
        season_map = {1: "Wet", 0: "Dry"}
    clim["Season"] = [season_map[l] for l in labels]
    start = _first_dry_to_wet(clim["Season"].values)
    return clim, start


# ---------------------------------------------------------------------------
# Alternative baselines (literature)
# ---------------------------------------------------------------------------
def hydro_year_start_driest_6_months(
    monthly_df: pd.DataFrame,
    *,
    value_col: str = "Rainfall_mm",
    month_col: str = "Month",
) -> tuple[int, list[int]]:
    """Bond (2014): start = first month of the driest 6-month rolling window."""
    monthly_means = monthly_df.groupby(month_col)[value_col].mean().reindex(range(1, 13))
    means_extended = pd.concat([monthly_means, monthly_means.iloc[:5]], ignore_index=True)
    rolling_sums = means_extended.rolling(window=6, min_periods=6).sum().iloc[5:]
    driest_start_idx = int(rolling_sums.idxmin())
    driest_months = [(driest_start_idx + i - 1) % 12 + 1 for i in range(6)]
    return int(driest_months[0]), driest_months


def hydro_year_start_after_min_month(
    monthly_df: pd.DataFrame,
    *,
    value_col: str = "Rainfall_mm",
    month_col: str = "Month",
) -> tuple[int, int]:
    """Feng et al. (2013): start = month after the long-term minimum."""
    monthly_means = monthly_df.groupby(month_col)[value_col].mean().reindex(range(1, 13))
    min_month = int(monthly_means.idxmin())
    return (min_month % 12 + 1), min_month
