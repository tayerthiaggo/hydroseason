"""Source-agnostic hydrological-year detection from monthly water extent.

Ported from WaterMask-TSFill commit
90983c1559e7c08951096bbf196c0daedead6b4f. Raster masks, WOfS, and extent
CSVs converge on this module's monthly ``extent_pct`` input.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import xarray as xr


DuplicateMonthPolicy = Literal["raise", "warn"]
MissingMonthPolicy = Literal["raise", "ignore"]


@dataclass(frozen=True)
class HydroYearConfig:
    """Supported cross-year wet and same-year dry search windows.

    A record labelled ``Y`` uses wet months Nov(Y-1)..Apr(Y), then dry
    months Jul(Y)..Dec(Y). Other shapes must retain that geometry.
    """

    wet_start_month: int = 11
    wet_end_month: int = 4
    dry_start_month: int = 7
    dry_end_month: int = 12
    min_wet_months: int = 2
    min_dry_months: int = 2
    low_confidence_ratio: float = 0.25
    medium_confidence_ratio: float = 0.50

    def __post_init__(self) -> None:
        months = (
            self.wet_start_month,
            self.wet_end_month,
            self.dry_start_month,
            self.dry_end_month,
        )
        if any(month < 1 or month > 12 for month in months):
            raise ValueError("Season months must be in 1..12.")
        if self.wet_start_month <= self.wet_end_month:
            raise ValueError(
                "Unsupported season-window geometry: wet season must cross the year boundary."
            )
        if self.dry_start_month > self.dry_end_month:
            raise ValueError(
                "Unsupported season-window geometry: dry season must stay within one year."
            )
        if self.dry_start_month <= self.wet_end_month:
            raise ValueError(
                "Unsupported season-window geometry: dry season must follow wet-season end."
            )
        if self.min_wet_months < 1 or self.min_dry_months < 1:
            raise ValueError("Minimum wet and dry month counts must be positive.")
        if not 0 <= self.low_confidence_ratio <= self.medium_confidence_ratio <= 1:
            raise ValueError("Confidence ratios must satisfy 0 <= low <= medium <= 1.")


def monthly_water_extent(
    water_mask: "xr.DataArray",
    *,
    water_value: int = 1,
    dry_value: int = 0,
    outside_value: int = -2,
    invalid_value: int = -1,
    spatial_dims: tuple[str, str] = ("y", "x"),
) -> pd.DataFrame:
    """Summarise monthly canonical masks without treating invalid pixels as dry.

    ``n_valid`` counts only pixels explicitly equal to ``water_value`` or
    ``dry_value``; any other code (unknown values, NaN, out-of-domain codes
    that bypassed a classifier) counts as invalid rather than silently
    inflating the valid denominator. Raster dependencies are imported only at
    this computation boundary. The four scalar summaries share one
    ``dask.compute`` call.
    """
    try:
        import dask
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError("monthly_water_extent requires the raster extra (dask and xarray).") from exc

    dims = list(spatial_dims)
    n_aoi = (water_mask != outside_value).sum(dim=dims)
    n_water = (water_mask == water_value).sum(dim=dims)
    n_dry = (water_mask == dry_value).sum(dim=dims)
    n_valid = n_water + n_dry
    n_invalid = n_aoi - n_valid
    n_aoi, n_valid, n_water, n_invalid = dask.compute(n_aoi, n_valid, n_water, n_invalid)

    n_aoi_arr = np.asarray(n_aoi.values, dtype=float)
    n_valid_arr = np.asarray(n_valid.values, dtype=float)
    n_water_arr = np.asarray(n_water.values, dtype=float)
    n_invalid_arr = np.asarray(n_invalid.values, dtype=float)
    extent_pct = np.full_like(n_valid_arr, np.nan)
    np.divide(n_water_arr * 100.0, n_valid_arr, out=extent_pct, where=n_valid_arr > 0)
    invalid_pct = np.full_like(n_aoi_arr, np.nan)
    np.divide(n_invalid_arr * 100.0, n_aoi_arr, out=invalid_pct, where=n_aoi_arr > 0)

    return pd.DataFrame(
        {
            "n_water": n_water_arr.astype(int),
            "n_aoi": n_aoi_arr.astype(int),
            "n_valid": n_valid_arr.astype(int),
            "n_invalid": n_invalid_arr.astype(int),
            "extent_pct": extent_pct,
            "invalid_pct": invalid_pct,
        },
        index=pd.DatetimeIndex(np.asarray(water_mask.time.values)),
    )


def detect_hydrological_years(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    config: HydroYearConfig | None = None,
    duplicate_month_policy: DuplicateMonthPolicy = "raise",
    missing_month_policy: MissingMonthPolicy = "raise",
    max_invalid_pct: float = 20.0,
) -> pd.DataFrame:
    """Detect hydrological years from a complete, quality-screened monthly series.

    ``invalid_pct`` is honoured when supplied in a DataFrame. The conservative
    default rejects months with more than 20% invalid coverage (see migration
    plan §6.2); callers may explicitly raise ``max_invalid_pct`` after
    assessing data quality.
    """
    if not 0 <= max_invalid_pct <= 100:
        raise ValueError("max_invalid_pct must be between 0 and 100.")
    cfg = config or HydroYearConfig()
    series, invalid_pct, full_index = _coerce_monthly_series(
        extent,
        value_col=value_col,
        date_col=date_col,
        duplicate_month_policy=duplicate_month_policy,
    )
    if invalid_pct is not None:
        invalid = invalid_pct.reindex(full_index)
        if invalid.isna().any() or (invalid > max_invalid_pct).any():
            raise ValueError(
                "Invalid coverage exceeds max_invalid_pct or is unknown; "
                "use completed masks, quality-screen the series, or explicitly raise the threshold."
            )
    if series.empty:
        return _empty_result()
    _handle_missing_months(series.index, policy=missing_month_policy)

    rows: list[dict] = []
    for year in range(int(series.index.min().year), int(series.index.max().year) + 1):
        wet = _window(series, pd.Timestamp(year - 1, cfg.wet_start_month, 1), pd.Timestamp(year, cfg.wet_end_month, 1))
        dry = _window(series, pd.Timestamp(year, cfg.dry_start_month, 1), pd.Timestamp(year, cfg.dry_end_month, 1))
        if len(wet) < cfg.min_wet_months or len(dry) < cfg.min_dry_months:
            continue
        peak_month = _idxmax_with_middle_tie_break(wet)
        end_dry_month = _idxmin_with_middle_tie_break(dry)
        span = _window(series, peak_month, end_dry_month)
        mid_dry_month = _month_nearest_midpoint(span.index, peak_month, end_dry_month)
        peak_extent, end_extent, mid_extent = (
            float(series.loc[peak_month]),
            float(series.loc[end_dry_month]),
            float(series.loc[mid_dry_month]),
        )
        rows.append({
            "hy_year": year, "hy_start": wet.index.min(), "hy_end": dry.index.max(),
            "peak_month": peak_month, "peak_extent_pct": round(peak_extent, 6),
            "mid_dry_month": mid_dry_month, "mid_extent_pct": round(mid_extent, 6),
            "end_dry_month": end_dry_month, "end_extent_pct": round(end_extent, 6),
            "amplitude_pct": round(peak_extent - end_extent, 6), "n_months_cycle": int(len(span)),
            "confidence": "unassigned", "boundary_source": "annual_window",
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return _empty_result()
    return _assign_confidence(_assign_end_dry_spans(result, series.index), cfg)


def label_hydrological_months(dates: pd.Index | pd.Series | pd.DatetimeIndex, hy_df: pd.DataFrame) -> pd.DataFrame:
    """Assign Wet/Dry and hydrological-year labels from detected boundaries."""
    times = pd.DatetimeIndex(pd.to_datetime(dates)).to_period("M").to_timestamp()
    labels = pd.DataFrame(index=times)
    labels["hy_year"], labels["season"] = np.nan, "unassigned"
    if hy_df.empty:
        return labels
    ordered = hy_df.sort_values("hy_year").reset_index(drop=True)
    for _, row in ordered.iterrows():
        mask = (labels.index >= pd.Timestamp(row["hy_start"])) & (labels.index <= pd.Timestamp(row["hy_end"]))
        labels.loc[mask, "hy_year"] = int(row["hy_year"])
        labels.loc[mask & (labels.index <= pd.Timestamp(row["peak_month"])), "season"] = "Wet"
        labels.loc[mask & (labels.index > pd.Timestamp(row["peak_month"])), "season"] = "Dry"
    first, last = ordered.iloc[0], ordered.iloc[-1]
    before = labels.index <= pd.Timestamp(first["hy_end"])
    labels.loc[before & labels["hy_year"].isna(), ["hy_year", "season"]] = (int(first["hy_year"]), "Wet")
    after = labels.index > pd.Timestamp(last["hy_end"])
    labels.loc[after, ["hy_year", "season"]] = (int(last["hy_year"]), "Dry")
    return labels


def _coerce_monthly_series(extent, *, value_col, date_col, duplicate_month_policy):
    if isinstance(extent, pd.Series):
        series, invalid = extent.copy(), None
    else:
        frame = extent.copy()
        frame.index = pd.to_datetime(frame[date_col] if date_col is not None else frame.index)
        series = frame[value_col].copy()
        invalid = frame["invalid_pct"].copy() if "invalid_pct" in frame else None
    series.index = pd.to_datetime(series.index).to_period("M").to_timestamp()
    _handle_duplicate_months(pd.DatetimeIndex(series.index), policy=duplicate_month_policy)
    if series.index.has_duplicates:
        series = series[~series.index.duplicated(keep="first")]
    series = pd.to_numeric(series, errors="coerce").sort_index()
    full_index = series.index
    series = series.dropna()
    if invalid is not None:
        invalid.index = pd.to_datetime(invalid.index).to_period("M").to_timestamp()
        invalid = invalid[~invalid.index.duplicated(keep="first")]
        invalid = pd.to_numeric(invalid, errors="coerce").sort_index()
    return series, invalid, full_index


def _handle_duplicate_months(months: pd.DatetimeIndex, *, policy: DuplicateMonthPolicy) -> None:
    if months.is_unique:
        return
    duplicates = sorted({timestamp.strftime("%Y-%m") for timestamp in months[months.duplicated(keep=False)]})
    if policy == "raise":
        raise ValueError(f"duplicate month timestamps: {duplicates}.")
    if policy != "warn":
        raise ValueError("duplicate_month_policy must be 'raise' or 'warn'.")
    import warnings
    warnings.warn(f"Duplicate month timestamps: {duplicates}; keeping first occurrence.", UserWarning, stacklevel=3)


def _handle_missing_months(months: pd.DatetimeIndex, *, policy: MissingMonthPolicy) -> None:
    if policy not in ("raise", "ignore"):
        raise ValueError("missing_month_policy must be 'raise' or 'ignore'.")
    expected = pd.date_range(months.min(), months.max(), freq="MS")
    missing = expected.difference(months)
    if len(missing) and policy == "raise":
        raise ValueError(f"missing month timestamps: {[time.strftime('%Y-%m') for time in missing]}.")


def _window(series, start, end):
    return series.loc[(series.index >= start) & (series.index <= end)]


def _idxmax_with_middle_tie_break(series):
    candidates = series[series == series.max()]
    return pd.Timestamp(candidates.index[len(candidates) // 2])


def _idxmin_with_middle_tie_break(series):
    candidates = series[series == series.min()]
    return pd.Timestamp(candidates.index[len(candidates) // 2])


def _month_nearest_midpoint(dates, start, end):
    if len(dates) == 0:
        return pd.Timestamp(end)
    midpoint = (start.toordinal() + end.toordinal()) / 2.0
    return pd.Timestamp(dates[int(np.argmin(np.abs(np.array([date.toordinal() for date in dates]) - midpoint)))])


def _assign_confidence(result, cfg):
    out = result.copy()
    positive = out.loc[out["amplitude_pct"] > 0, "amplitude_pct"]
    typical = float(positive.median()) if len(positive) else 0.0
    out["confidence"] = np.select(
        [out["amplitude_pct"] <= max(0.0, typical * cfg.low_confidence_ratio), out["amplitude_pct"] <= max(0.0, typical * cfg.medium_confidence_ratio)],
        ["low", "medium"], default="high",
    )
    out.loc[out["confidence"] == "low", "boundary_source"] = "annual_window_low_amplitude"
    out.loc[out["amplitude_pct"] <= 0, "boundary_source"] = "flat_window"
    return out


def _assign_end_dry_spans(result, dates):
    out = result.sort_values("hy_year").reset_index(drop=True).copy()
    out["hy_start"] = [pd.Timestamp(dates.min()) if i == 0 else pd.Timestamp(out.loc[i - 1, "end_dry_month"]) + pd.DateOffset(months=1) for i in range(len(out))]
    out["hy_end"] = pd.to_datetime(out["end_dry_month"])
    out["n_months_cycle"] = [len(pd.date_range(start, end, freq="MS")) for start, end in zip(out["hy_start"], out["hy_end"])]
    return out


def _empty_result():
    return pd.DataFrame(columns=["hy_year", "hy_start", "hy_end", "peak_month", "peak_extent_pct", "mid_dry_month", "mid_extent_pct", "end_dry_month", "end_extent_pct", "amplitude_pct", "n_months_cycle", "confidence", "boundary_source"])


__all__ = ["HydroYearConfig", "detect_hydrological_years", "label_hydrological_months", "monthly_water_extent"]
