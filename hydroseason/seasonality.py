"""Seasonality detection.

Primary metric: ANOVA eta-squared (eta²) — between-month fraction of total
variance.  Robust to ENSO-driven interannual amplitude modulation because
proportional drought suppression of all months preserves the between-month
ratio.

Confirmation: circular concentration R — computed from the 12-month
climatological mean profile, completely immune to interannual noise.

Supporting: Walsh-Lawler Seasonality Index — a second climatology-based
concentration metric.

Diagnostic: STL seasonality strength (Hyndman) — retained as a data-
consistency indicator (how stable is the seasonal signal across years) but no
longer gates the regime classification.

Backward-compatible API: ``classify_regime_from_stl`` and
``classify_regime_with_rainfall_si`` are kept as public functions for external
callers.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# eta² thresholds — fraction of total variance explained by calendar month
# ---------------------------------------------------------------------------
ETA_SQ_STRONG = 0.35    # clearly seasonal (primary gate)
ETA_SQ_MODERATE = 0.12  # moderately seasonal — confirmed by R or SI
ETA_SQ_WEAK = 0.10      # weak but non-trivial

# Circular concentration R thresholds
R_MODERATE = 0.40       # moderate peak concentration
R_WEAK = 0.25           # weak but non-trivial

# Walsh-Lawler SI thresholds (confirmation)
SI_MODERATE = 0.60
SI_WEAK = 0.40

# Legacy STL thresholds — kept for backward-compatible API
STL_STRONG = 0.60
STL_WEAK = 0.30


@dataclass(frozen=True)
class SeasonalityResult:
    stl_strength: float
    si: float
    regime: str                     # "seasonal" | "borderline" | "non_seasonal"
    eta_squared: float = 0.0        # between-month variance fraction (primary metric)
    circular_R: float = 0.0         # circular concentration from climatology
    silhouette: float | None = None  # legacy KMeans silhouette (opt-in)
    regime_source: str = "eta_squared"
    # regime_source values: "eta_squared" | "eta_squared_confirmed" |
    #                       "concentration" | "all_weak"
    # Legacy values retained only when using the old API functions:
    # "stl" | "rainfall_si_override"


# ---------------------------------------------------------------------------
# Walsh-Lawler SI
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
# eta² — ANOVA between-month fraction of total variance
# ---------------------------------------------------------------------------
def eta_squared_seasonality_score(
    df: pd.DataFrame,
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
) -> float:
    """Between-month fraction of total rainfall variance (ANOVA eta²).

    eta² = SS_between / SS_total, where SS_between measures how much of the
    total variance is attributable to knowing the calendar month.

    Unlike STL, this is robust to ENSO-driven interannual amplitude variation:
    a drought year that suppresses all months proportionally preserves the
    between-month ratio (Jan still averages higher than Aug).  Range [0, 1];
    0 ≈ perfectly uniform, 1 = all variance is between months.

    Typical values:
    - Sharp monsoon:           eta² ≈ 0.40–0.70
    - Clear but noisy season:  eta² ≈ 0.20–0.40
    - Weak / semi-arid:        eta² ≈ 0.10–0.25
    - Near-uniform / perennial: eta² ≈ 0.00–0.08
    """
    values = pd.to_numeric(df[value_col], errors="coerce")
    valid_mask = values.notna()
    valid_values = values[valid_mask]
    valid_months = df.loc[valid_mask, month_col]

    if len(valid_values) < 12:
        return 0.0

    grand_mean = float(valid_values.mean())
    ss_total = float(((valid_values - grand_mean) ** 2).sum())
    if ss_total <= 0:
        return 0.0

    # SS_between: for each calendar month, n_m * (mean_m - grand_mean)²
    group_stats = valid_values.groupby(valid_months).agg(["mean", "count"])
    ss_between = float(
        ((group_stats["mean"] - grand_mean) ** 2 * group_stats["count"]).sum()
    )

    return float(max(0.0, min(1.0, ss_between / ss_total)))


# ---------------------------------------------------------------------------
# Circular concentration R from climatology
# ---------------------------------------------------------------------------
def circular_concentration_R(
    df: pd.DataFrame,
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
) -> float:
    """Mean resultant length R from circular statistics on the 12-month climatology.

    Operates on the mean annual rainfall profile so is completely immune to
    interannual noise.  R in [0, 1]: 0 = perfectly uniform distribution across
    months; 1 = all rainfall in one month.
    """
    clim = (
        df.groupby(month_col)[value_col]
        .mean()
        .reindex(range(1, 13), fill_value=0.0)
        .to_numpy(dtype=float)
    )
    total = clim.sum()
    if total <= 0:
        return 0.0
    months = np.arange(1, 13)
    theta = 2.0 * np.pi * (months - 1) / 12.0
    x_bar = float((clim * np.cos(theta)).sum() / total)
    y_bar = float((clim * np.sin(theta)).sum() / total)
    return float(np.sqrt(x_bar * x_bar + y_bar * y_bar))


# ---------------------------------------------------------------------------
# Composite regime classifier — eta² primary, R + SI confirming
# ---------------------------------------------------------------------------
def classify_regime_composite(
    eta_sq: float,
    circular_R: float,
    si: float,
    *,
    eta_sq_strong: float = ETA_SQ_STRONG,
    eta_sq_moderate: float = ETA_SQ_MODERATE,
    eta_sq_weak: float = ETA_SQ_WEAK,
    r_moderate: float = R_MODERATE,
    r_weak: float = R_WEAK,
    si_moderate: float = SI_MODERATE,
    si_weak: float = SI_WEAK,
) -> tuple[str, str]:
    """Classify seasonality regime from eta², circular R, and SI.

    Returns (regime, regime_source) where:
    - "seasonal"            + "eta_squared"           — high eta²
    - "seasonal"            + "eta_squared_confirmed"  — moderate eta² + R or SI
    - "borderline"          + "concentration"          — weak eta² but R or SI signal
    - "non_seasonal"        + "all_weak"               — all metrics below noise floor

    STL is not used here (kept as a diagnostic field in SeasonalityResult).
    """
    if eta_sq >= eta_sq_strong:
        return "seasonal", "eta_squared"

    if eta_sq >= eta_sq_moderate and (circular_R >= r_moderate or si >= si_moderate):
        return "seasonal", "eta_squared_confirmed"

    if eta_sq >= eta_sq_weak or circular_R >= r_weak or si >= si_weak:
        return "borderline", "concentration"

    return "non_seasonal", "all_weak"


# ---------------------------------------------------------------------------
# Legacy STL functions — kept for backward compatibility and as diagnostic
# ---------------------------------------------------------------------------
_STL_CACHE: dict = {}


def get_stl_fit(df: pd.DataFrame, date_col: str, value_col: str):
    """Return a cached or freshly computed STL fit for diagnostic use."""
    try:
        val_sum = float(df[value_col].sum())
    except Exception:
        val_sum = 0.0
    key = (id(df), len(df), date_col, value_col, val_sum)
    if key in _STL_CACHE:
        return _STL_CACHE[key]

    from statsmodels.tsa.seasonal import STL

    work = df[[date_col, value_col]].copy()
    work[date_col] = pd.to_datetime(work[date_col])
    series = work.set_index(date_col).sort_index().asfreq("MS")

    if series[value_col].isna().any():
        series[value_col] = series[value_col].interpolate(
            method="linear", limit_direction="both"
        )
    if series[value_col].isna().any():
        fit = None
    else:
        try:
            fit = STL(series[value_col], period=12, robust=True).fit()
        except Exception as exc:
            warnings.warn(
                f"STL decomposition failed ({exc}); STL strength set to 0.",
                RuntimeWarning,
                stacklevel=2,
            )
            fit = None

    if len(_STL_CACHE) > 50:
        _STL_CACHE.clear()

    _STL_CACHE[key] = fit
    return fit


def stl_seasonality_strength(
    df: pd.DataFrame,
    date_col: str = "Date",
    value_col: str = "Rainfall_mm",
) -> float:
    """STL seasonal strength F_S (diagnostic use only).

    F_S = max(0, 1 - Var(remainder) / Var(remainder + seasonal))

    Retained as a data-consistency indicator: high F_S means the seasonal
    signal is stable across years.  No longer gates the regime classification.
    """
    fit = get_stl_fit(df, date_col, value_col)
    if fit is None:
        return 0.0
    resid = fit.resid.values
    seasonal = fit.seasonal.values
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
    """STL residuals aligned to the input rows."""
    fit = get_stl_fit(df, date_col, value_col)
    if fit is None:
        return pd.Series(np.nan, index=df.index, dtype=float)

    work = df[[date_col, value_col]].copy()
    work[date_col] = pd.to_datetime(work[date_col])
    residual_by_date = pd.Series(fit.resid, index=fit.resid.index)
    aligned = work[date_col].map(residual_by_date)
    return pd.Series(aligned.to_numpy(dtype=float), index=df.index, dtype=float)


def classify_regime_from_stl(strength: float) -> str:
    """Legacy STL-only regime classifier (backward-compatible API).

    Not used internally — regime is now determined by classify_regime_composite.
    """
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
    """Legacy STL + SI classifier (backward-compatible API).

    Not used internally.  Retained so external code calling this function
    continues to work.
    """
    regime = classify_regime_from_stl(strength)
    if (
        regime != "seasonal"
        and strength >= min_stl_for_override
        and si >= si_strong_threshold
    ):
        return "seasonal", "rainfall_si_override"
    return regime, "stl"


# ---------------------------------------------------------------------------
# Legacy KMeans silhouette diagnostic (opt-in)
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
    no_rain = (
        work.groupby(month_col)["_no_rain"]
        .sum()
        .reindex(range(1, 13), fill_value=0)
    )
    mean_v = (
        work.groupby(month_col)[value_col]
        .mean()
        .reindex(range(1, 13), fill_value=0.0)
    )
    features = pd.DataFrame({"mean": mean_v.values, "no_rain": no_rain.values})
    if features.nunique().min() <= 1:
        return None

    try:
        x = StandardScaler().fit_transform(features)
        labels = KMeans(n_clusters=2, n_init="auto", random_state=0).fit_predict(x)
        if len(np.unique(labels)) < 2:
            return None
        return float(silhouette_score(x, labels))
    except Exception as exc:
        warnings.warn(
            f"KMeans silhouette diagnostic failed ({exc}); returning None.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def detect_seasonality_regime(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
    report_silhouette: bool = False,
    # Parameters below are accepted for backward compatibility but are no
    # longer used to gate the regime — see classify_regime_composite.
    rainfall_si_override: bool = True,
    si_strong_threshold: float = 0.80,
) -> SeasonalityResult:
    """Detect seasonality regime using the eta² + circular R composite.

    Algorithm
    ---------
    1. Compute eta² (between-month ANOVA fraction of total variance).
    2. Compute circular R (concentration of the 12-month climatological mean).
    3. Compute Walsh-Lawler SI (climatology-based concentration).
    4. Classify with classify_regime_composite:
       - eta² >= 0.35                           → seasonal  (eta_squared)
       - eta² >= 0.20 AND (R >= 0.40 OR SI >= 0.60) → seasonal  (eta_squared_confirmed)
       - eta² >= 0.10 OR R >= 0.25 OR SI >= 0.40   → borderline (concentration)
       - all below                              → non_seasonal (all_weak)
    5. STL strength is still computed as a diagnostic consistency indicator
       and stored in SeasonalityResult.stl_strength, but no longer gates the
       regime decision.

    Parameters
    ----------
    rainfall_si_override, si_strong_threshold :
        Accepted for API backward compatibility; not used internally.
    """
    clim = mean_monthly_rainfall(df, month_col=month_col, value_col=value_col)
    si = walsh_lawler_seasonality_index(clim.values)
    eta_sq = eta_squared_seasonality_score(df, month_col=month_col, value_col=value_col)
    circ_R = circular_concentration_R(df, month_col=month_col, value_col=value_col)
    strength = stl_seasonality_strength(df, date_col=date_col, value_col=value_col)

    regime, regime_source = classify_regime_composite(eta_sq, circ_R, si)

    sil = (
        kmeans_silhouette_diagnostic(df, month_col=month_col, value_col=value_col)
        if report_silhouette
        else None
    )

    return SeasonalityResult(
        stl_strength=strength,
        si=si,
        regime=regime,
        eta_squared=eta_sq,
        circular_R=circ_R,
        silhouette=sil,
        regime_source=regime_source,
    )
