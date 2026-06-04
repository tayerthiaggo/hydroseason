"""Seasonality detection.

Primary metric: STL seasonality strength (Hyndman) — transferable across any monthly variable.
Reported diagnostic: Walsh-Lawler Seasonality Index (rainfall-specific but free to compute).
Legacy opt-in diagnostic: silhouette of 2-cluster KMeans on (mean, no-rain).

Regime is decided by STL strength thresholds, not SI.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

# STL thresholds for monthly series. STL strength is in [0, 1]; Hyndman et al.
# generally treat >= 0.6 as strongly seasonal; below 0.3 as weak.
STL_STRONG = 0.60
STL_WEAK = 0.30


@dataclass(frozen=True)
class SeasonalityResult:
    stl_strength: float
    si: float
    regime: str  # "seasonal" | "borderline" | "non_seasonal"
    silhouette: float | None = None
    regime_source: str = "stl"


# ---------------------------------------------------------------------------
# Walsh-Lawler SI (diagnostic)
# ---------------------------------------------------------------------------
def walsh_lawler_seasonality_index(monthly_climatology_values: pd.Series | np.ndarray) -> float:
    values = np.asarray(monthly_climatology_values, dtype=float)
    if values.size != 12:
        raise ValueError("Walsh-Lawler SI requires exactly 12 monthly climatology values.")
    annual_total = values.sum()
    if annual_total <= 0:
        return 0.0
    return float((1.0 / annual_total) * np.abs(values - annual_total / 12.0).sum())


def mean_monthly_rainfall(
    df: pd.DataFrame,
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
) -> pd.Series:
    return df.groupby(month_col)[value_col].mean().reindex(range(1, 13), fill_value=0.0)


# ---------------------------------------------------------------------------
# STL seasonality strength (primary, transferable)
# ---------------------------------------------------------------------------
def stl_seasonality_strength(
    df: pd.DataFrame,
    date_col: str = "Date",
    value_col: str = "Rainfall_mm",
) -> float:
    """Seasonality strength from STL decomposition.

    F_S = max(0, 1 - Var(remainder) / Var(remainder + seasonal))

    Unit-free in [0, 1]; works for any monthly variable.
    Reference: Wang, Smith, Hyndman (2006); Hyndman feasts/tsfeatures.
    """
    from statsmodels.tsa.seasonal import STL  # local import keeps base import light

    series = df[[date_col, value_col]].copy()
    series[date_col] = pd.to_datetime(series[date_col])
    series = series.set_index(date_col).asfreq("MS")

    # STL fails on NaN; we expect validate.py to have interpolated already.
    if series[value_col].isna().any():
        series[value_col] = series[value_col].interpolate(method="linear", limit_direction="both")
    if series[value_col].isna().any():
        return 0.0

    try:
        stl = STL(series[value_col], period=12, robust=True).fit()
    except Exception as exc:  # noqa: BLE001 — STL can fail on degenerate series
        warnings.warn(
            f"STL decomposition failed ({exc}); seasonality strength set to 0.0.",
            RuntimeWarning,
            stacklevel=2,
        )
        return 0.0

    resid = stl.resid.values
    seasonal = stl.seasonal.values
    denom = np.var(resid + seasonal)
    if denom <= 0:
        return 0.0
    return float(max(0.0, 1.0 - np.var(resid) / denom))


def stl_residuals(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    value_col: str = "Rainfall_mm",
) -> pd.Series:
    """Return STL residuals aligned to the input rows.

    The residual is the part of the monthly value not explained by the STL
    trend + seasonal components. Positive outliers are useful for distinguishing
    isolated storm events from climatologically plausible shoulder months.
    """
    from statsmodels.tsa.seasonal import STL  # local import keeps base import light

    work = df[[date_col, value_col]].copy()
    work[date_col] = pd.to_datetime(work[date_col])
    series = work.set_index(date_col).sort_index().asfreq("MS")

    if series[value_col].isna().any():
        series[value_col] = series[value_col].interpolate(method="linear", limit_direction="both")
    if series[value_col].isna().any():
        return pd.Series(np.nan, index=df.index, dtype=float)

    try:
        fit = STL(series[value_col], period=12, robust=True).fit()
    except Exception as exc:  # noqa: BLE001 — STL can fail on degenerate series
        warnings.warn(
            f"STL decomposition failed ({exc}); residuals set to NaN.",
            RuntimeWarning,
            stacklevel=2,
        )
        return pd.Series(np.nan, index=df.index, dtype=float)

    residual_by_date = pd.Series(fit.resid, index=series.index)
    aligned = pd.to_datetime(df[date_col]).map(residual_by_date)
    return pd.Series(aligned.to_numpy(dtype=float), index=df.index, dtype=float)


def classify_regime_from_stl(strength: float) -> str:
    if strength < STL_WEAK:
        return "non_seasonal"
    if strength < STL_STRONG:
        return "borderline"
    return "seasonal"


def classify_regime_with_rainfall_si(
    strength: float,
    si: float,
    *,
    si_strong_threshold: float = 0.80,
    min_stl_for_override: float = STL_WEAK,
) -> tuple[str, str]:
    """Classify rainfall seasonality with STL as base and SI as a strong-rainfall override.

    STL is unit-free and transferable, but raw monthly rainfall is highly skewed:
    extreme wet months inflate the STL remainder variance and can make strongly
    seasonal monsoonal catchments land just below the generic ``STL_STRONG`` cutoff.

    If STL finds at least borderline seasonality and Walsh-Lawler SI is strongly
    seasonal, this promotes the regime to ``seasonal`` and records the source as
    ``rainfall_si_override``. Non-seasonal STL results are not promoted.
    """
    regime = classify_regime_from_stl(strength)
    if regime != "seasonal" and strength >= min_stl_for_override and si >= si_strong_threshold:
        return "seasonal", "rainfall_si_override"
    return regime, "stl"


# ---------------------------------------------------------------------------
# Legacy KMeans silhouette diagnostic (opt-in; kept for backward-compatible reporting)
# ---------------------------------------------------------------------------
def kmeans_silhouette_diagnostic(
    df: pd.DataFrame,
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
) -> float | None:
    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return None

    work = df.copy()
    work["_no_rain"] = (work[value_col] == 0).astype(int)
    no_rain = work.groupby(month_col)["_no_rain"].sum().reindex(range(1, 13), fill_value=0)
    mean_v = work.groupby(month_col)[value_col].mean().reindex(range(1, 13), fill_value=0.0)
    features = pd.DataFrame({"mean": mean_v.values, "no_rain": no_rain.values})
    if features.nunique().min() <= 1:
        return None

    try:
        x = StandardScaler().fit_transform(features)
        labels = KMeans(n_clusters=2, n_init="auto", random_state=0).fit_predict(x)
        if len(np.unique(labels)) < 2:
            return None
        return float(silhouette_score(x, labels))
    except Exception as exc:  # noqa: BLE001 — diagnostic only, never fatal
        warnings.warn(
            f"KMeans silhouette diagnostic failed ({exc}); returning None.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


# ---------------------------------------------------------------------------
# Public regime detection
# ---------------------------------------------------------------------------
def detect_seasonality_regime(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
    report_silhouette: bool = False,
    rainfall_si_override: bool = True,
    si_strong_threshold: float = 0.80,
) -> SeasonalityResult:
    clim = mean_monthly_rainfall(df, month_col=month_col, value_col=value_col)
    si = walsh_lawler_seasonality_index(clim.values)
    strength = stl_seasonality_strength(df, date_col=date_col, value_col=value_col)
    if rainfall_si_override:
        regime, regime_source = classify_regime_with_rainfall_si(
            strength, si, si_strong_threshold=si_strong_threshold
        )
    else:
        regime = classify_regime_from_stl(strength)
        regime_source = "stl"
    sil = kmeans_silhouette_diagnostic(df, month_col=month_col, value_col=value_col) if report_silhouette else None
    return SeasonalityResult(
        stl_strength=strength,
        si=si,
        regime=regime,
        silhouette=sil,
        regime_source=regime_source,
    )
