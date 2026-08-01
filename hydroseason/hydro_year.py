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
QualityPolicy = Literal["exclude", "flag"]

# Cycle spans beyond this make consecutive years' search windows overlap by
# more than six months; see HydroYearConfig.__post_init__.
_MAX_CYCLE_SPAN_MONTHS = 18


def _cyclic_span(start_month: int, end_month: int) -> int:
    """Inclusive month count walking forward from ``start_month`` to ``end_month``."""
    return ((end_month - start_month) % 12) + 1


def _cyclic_gap(from_month: int, to_month: int) -> int:
    """Months stepped forward from ``from_month`` to reach ``to_month``."""
    return (to_month - from_month) % 12


@dataclass(frozen=True)
class HydroYearConfig:
    """Wet then dry search windows, at any phase of the calendar year.

    Windows are **cyclic month ranges**, not calendar-anchored spans: each is
    read by walking forward from its start month to its end month, wrapping
    through December where needed. The cycle for the record labelled ``Y`` is
    anchored so the wet window *ends* in year ``Y``; the wet window's start and
    the whole dry window then fall wherever that anchoring puts them, which may
    be the previous or the following calendar year.

    The shipped default is unchanged and describes a tropical monsoon: wet
    Nov(Y-1)..Apr(Y), then dry Jul(Y)..Dec(Y).

    Because the geometry is cyclic, phases the earlier fixed geometry could not
    express are now valid -- notably southern-Australian winter-rainfall
    catchments, e.g. ``wet_start_month=6, wet_end_month=9,
    dry_start_month=11, dry_end_month=2``, whose dry window ends in ``Y+1``.
    The only ordering rule left is that the dry window must begin after the wet
    window ends.
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
        if _cyclic_gap(self.wet_end_month, self.dry_start_month) == 0:
            raise ValueError(
                "Unsupported season-window geometry: the dry window must follow the "
                "wet window, so dry_start_month cannot equal wet_end_month."
            )
        # Consecutive years' search windows overlap by (cycle_span - 12) months.
        # The shipped default spans 14, so a 2-month overlap is normal and fine.
        # Past 18 the overlap exceeds half a year and the same observation can
        # be the peak of two different records, which makes the assignment
        # ambiguous rather than merely generous.
        if self.cycle_span_months > _MAX_CYCLE_SPAN_MONTHS:
            raise ValueError(
                "Unsupported season-window geometry: wet window, gap and dry window "
                f"span {self.cycle_span_months} months (max {_MAX_CYCLE_SPAN_MONTHS}); "
                "consecutive hydrological years would overlap ambiguously."
            )
        if self.min_wet_months < 1 or self.min_dry_months < 1:
            raise ValueError("Minimum wet and dry month counts must be positive.")
        if not 0 <= self.low_confidence_ratio <= self.medium_confidence_ratio <= 1:
            raise ValueError("Confidence ratios must satisfy 0 <= low <= medium <= 1.")

    @property
    def wet_span_months(self) -> int:
        return _cyclic_span(self.wet_start_month, self.wet_end_month)

    @property
    def dry_span_months(self) -> int:
        return _cyclic_span(self.dry_start_month, self.dry_end_month)

    @property
    def wet_to_dry_gap_months(self) -> int:
        return _cyclic_gap(self.wet_end_month, self.dry_start_month)

    @property
    def cycle_span_months(self) -> int:
        """Total months from wet-window start to dry-window end."""
        return self.wet_span_months + self.wet_to_dry_gap_months + self.dry_span_months - 1

    def windows_for_year(self, year: int) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
        """Absolute (wet_start, wet_end, dry_start, dry_end) for record ``year``.

        Anchored on the wet window ending in ``year``, then walked outward by
        the cyclic spans, so every other bound lands in whichever calendar year
        the phase implies without the caller specifying offsets.
        """
        wet_end = pd.Timestamp(year, self.wet_end_month, 1)
        wet_start = wet_end - pd.DateOffset(months=self.wet_span_months - 1)
        dry_start = wet_end + pd.DateOffset(months=self.wet_to_dry_gap_months)
        dry_end = dry_start + pd.DateOffset(months=self.dry_span_months - 1)
        return wet_start, wet_end, dry_start, dry_end


def suggest_hydro_year_config(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    **overrides,
) -> HydroYearConfig:
    """Propose a ``HydroYearConfig`` from a monthly-mean climatology of ``extent``.

    Averages ``extent`` by calendar month, then takes the contiguous
    above-mean run around the climatological peak as the wet window and the
    below-mean run around the trough as the dry window. Because
    ``HydroYearConfig`` windows are cyclic, the suggestion keeps whatever phase
    the climatology shows rather than reshaping it toward a cross-year wet
    season -- a winter-rainfall catchment gets a mid-year wet window.

    This remains a first guess for review, not a substitute for it: bimodal,
    flat, or noisy climatologies can produce a split that doesn't match
    physical wet/dry seasons. Screen the record with ``assess_water_regime``
    first; a catchment it calls aseasonal has no phase worth suggesting. Pass explicit ``HydroYearConfig`` fields as ``overrides`` (e.g.
    ``min_wet_months=3``) to keep the suggested months but override other
    settings.
    """
    series, _, _ = _coerce_monthly_series(
        extent, value_col=value_col, date_col=date_col, duplicate_month_policy="warn"
    )
    if series.empty:
        raise ValueError("suggest_hydro_year_config requires at least one non-missing monthly value.")
    climatology = series.groupby(series.index.month).mean().reindex(range(1, 13))
    if climatology.isna().any():
        missing = sorted(climatology[climatology.isna()].index)
        raise ValueError(
            f"climatology is missing calendar months {missing}; need coverage of all 12 months."
        )

    peak_month = int(climatology.idxmax())
    trough_month = int(climatology.idxmin())

    # Classify each calendar month as "wet" (above the climatological mean)
    # by walking outward from the peak month, and "dry" by walking outward
    # from the trough month, so the split follows the shape of the annual
    # cycle rather than a fixed threshold.
    overall_mean = float(climatology.mean())
    is_wet = climatology > overall_mean

    def _contiguous_run(center: int, keep: pd.Series) -> list[int]:
        run = [center]
        month = center % 12 + 1
        while keep.loc[month] and month not in run:
            run.append(month)
            month = month % 12 + 1
        month = (center - 2) % 12 + 1
        while keep.loc[month] and month not in run:
            run.insert(0, month)
            month = (month - 2) % 12 + 1
        return run

    wet_months = _contiguous_run(peak_month, is_wet)
    dry_months = _contiguous_run(trough_month, ~is_wet)

    wet_start_month, wet_end_month = wet_months[0], wet_months[-1]
    dry_start_month, dry_end_month = dry_months[0], dry_months[-1]

    # Windows are cyclic, so the runs above are kept at whatever phase the
    # climatology actually shows -- no reshaping toward a cross-year wet
    # season. The single remaining rule is that the dry window must begin
    # after the wet window ends; nudge it by one month only if they collide.
    if _cyclic_gap(wet_end_month, dry_start_month) == 0:
        dry_start_month = (wet_end_month % 12) + 1
        if _cyclic_span(dry_start_month, dry_end_month) > 12:
            dry_end_month = dry_start_month

    fields = {
        "wet_start_month": wet_start_month,
        "wet_end_month": wet_end_month,
        "dry_start_month": dry_start_month,
        "dry_end_month": dry_end_month,
    }
    fields.update(overrides)
    return HydroYearConfig(**fields)


def monthly_water_extent(
    water_mask: "xr.DataArray",
    *,
    water_value: int = 1,
    dry_value: int = 0,
    outside_value: int = -2,
    invalid_value: int = -1,
    spatial_dims: tuple[str, str] = ("y", "x"),
    time_block: int = 1,
    wet_aoi=None,
    read_workers: int | None = None,
) -> pd.DataFrame:
    """Summarise monthly canonical masks without treating invalid pixels as dry.

    ``n_valid`` counts only pixels explicitly equal to ``water_value`` or
    ``dry_value``; any other code (unknown values, NaN, out-of-domain codes
    that bypassed a classifier) counts as invalid rather than silently
    inflating the valid denominator. Raster dependencies are imported only at
    this computation boundary. The four scalar summaries are computed in
    streamed blocks of ``time_block`` steps along ``time`` rather than in one
    all-at-once ``dask.compute`` call, so peak memory stays bounded by
    ``time_block`` (times the spatial chunk footprint) instead of scaling
    with the full length of ``time``. Raising ``time_block`` trades scheduler
    overhead (more, smaller ``dask.compute`` calls) for locality (fewer calls,
    more spatial chunks held concurrently); lower it to bound memory more
    tightly, raise it to reduce per-call scheduling overhead.

    ``wet_aoi``, if given, is a polygon or GeoDataFrame (in any CRS) describing
    the historical wet-AOI extent. It is rasterised against ``water_mask``'s
    spatial grid exactly once (the grid is time-invariant across the whole
    cube), then used to compute ``n_wet_aoi`` -- the per-month count of pixels
    inside the wet AOI that are also not ``outside_value`` -- and the derived
    ``wet_fill_pct = 100 * n_water / n_wet_aoi`` drought-signal ratio (NaN when
    ``n_wet_aoi`` is 0). When ``wet_aoi`` is ``None`` (the default), no
    rasterisation happens at all and ``n_wet_aoi`` is set equal to
    ``n_valid``, so existing callers adding no wet AOI see no change to any
    pre-existing column, and get a well-defined ``wet_fill_pct`` computed
    with the same ``100 * n_water / n_wet_aoi`` formula used in the
    ``wet_aoi``-given case (this keeps ``wet_fill_pct`` an exact
    sum-then-percentage tiled aggregation of ``n_water``/``n_wet_aoi``,
    matching how ``extent_pct`` and ``invalid_pct`` already aggregate).
    ``wet_fill_pct`` therefore equals ``extent_pct`` exactly and
    unconditionally when ``wet_aoi`` is ``None``, regardless of whether
    invalid pixels are present, because both ratios reduce to the same
    ``100 * n_water / n_valid`` formula in that case (they can legitimately
    differ only when a real ``wet_aoi`` is supplied).

    ``read_workers``, if given (and > 0), overrides dask's threaded-scheduler
    worker count for the ``dask.compute`` reductions below, where the lazy
    STAC/COG graph is actually materialised. Profiling on real WOfS data found
    this workload is decode/warp-CPU-bound rather than I/O-latency-bound as
    might be assumed for remote reads: dask's own default worker count
    outperformed every explicit override tried (4 through 64), and forcing a
    higher count made it monotonically worse. Leave this at ``None`` (the
    default, which leaves dask's configuration untouched) unless you have
    profiled your own workload and confirmed a specific value helps -- see
    ``hydroseason._io_extent_cache.load_wofs_monthly_extent``'s ``read_workers``
    docstring for the measurements. The override, if used, is scoped via
    ``dask.config.set`` and restored on exit.
    """
    try:
        import dask
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError("monthly_water_extent requires the raster extra (dask and xarray).") from exc

    from contextlib import nullcontext

    concurrency = (
        dask.config.set(scheduler="threads", num_workers=read_workers)
        if read_workers is not None and read_workers > 0
        else nullcontext()
    )

    dims = list(spatial_dims)
    n_time = water_mask.sizes["time"]

    first_slice = water_mask.isel(time=0)

    inside_wet = None
    if wet_aoi is not None:
        import geopandas as gpd
        import rioxarray  # noqa: F401  (registers the .rio accessor used below)

        from hydroseason._io_geo import _inside_aoi_mask_like, _resolve_raster_crs

        mask_crs = _resolve_raster_crs(water_mask)
        gdf = (
            wet_aoi
            if isinstance(wet_aoi, gpd.GeoDataFrame)
            else gpd.GeoDataFrame({"geometry": [wet_aoi]}, geometry="geometry", crs=mask_crs)
        )
        if gdf.crs is not None and mask_crs is not None:
            gdf = gdf.to_crs(mask_crs)
        inside_wet = _inside_aoi_mask_like(first_slice, gdf)

    n_aoi_parts: list[np.ndarray] = []
    n_valid_parts: list[np.ndarray] = []
    n_water_parts: list[np.ndarray] = []
    n_invalid_parts: list[np.ndarray] = []
    n_wet_aoi_parts: list[np.ndarray] = []
    with concurrency:
        for start in range(0, n_time, time_block):
            block = water_mask.isel(time=slice(start, start + time_block))
            n_water_block = (block == water_value).sum(dim=dims, dtype=np.int32)
            n_dry_block = (block == dry_value).sum(dim=dims, dtype=np.int32)
            n_valid_block = n_water_block + n_dry_block
            n_aoi_block = (block != outside_value).sum(dim=dims, dtype=np.int32)
            n_invalid_block = n_aoi_block - n_valid_block
            if inside_wet is not None:
                n_wet_aoi_block = ((block != outside_value) & inside_wet).sum(dim=dims, dtype=np.int32)
                (
                    n_aoi_block,
                    n_valid_block,
                    n_water_block,
                    n_invalid_block,
                    n_wet_aoi_block,
                ) = dask.compute(
                    n_aoi_block, n_valid_block, n_water_block, n_invalid_block, n_wet_aoi_block
                )
                n_wet_aoi_parts.append(np.asarray(n_wet_aoi_block.values, dtype=float))
            else:
                n_aoi_block, n_valid_block, n_water_block, n_invalid_block = dask.compute(
                    n_aoi_block, n_valid_block, n_water_block, n_invalid_block
                )
            n_aoi_parts.append(np.asarray(n_aoi_block.values, dtype=float))
            n_valid_parts.append(np.asarray(n_valid_block.values, dtype=float))
            n_water_parts.append(np.asarray(n_water_block.values, dtype=float))
            n_invalid_parts.append(np.asarray(n_invalid_block.values, dtype=float))

    n_aoi_arr = np.concatenate(n_aoi_parts)
    n_valid_arr = np.concatenate(n_valid_parts)
    n_water_arr = np.concatenate(n_water_parts)
    n_invalid_arr = np.concatenate(n_invalid_parts)
    extent_pct = np.full_like(n_valid_arr, np.nan)
    np.divide(n_water_arr * 100.0, n_valid_arr, out=extent_pct, where=n_valid_arr > 0)
    invalid_pct = np.full_like(n_aoi_arr, np.nan)
    np.divide(n_invalid_arr * 100.0, n_aoi_arr, out=invalid_pct, where=n_aoi_arr > 0)

    if inside_wet is not None:
        n_wet_aoi_arr = np.concatenate(n_wet_aoi_parts)
    else:
        # No wet AOI given: fall back to n_valid (not n_aoi) so wet_fill_pct
        # is an EXACT alias of extent_pct in this case (same formula and
        # denominator), not merely equal when there happen to be zero
        # invalid pixels -- while remaining tiling-exact, since n_valid is
        # itself already a tiling-exact summed count.
        n_wet_aoi_arr = n_valid_arr
    wet_fill_pct = np.full_like(n_wet_aoi_arr, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        np.divide(n_water_arr * 100.0, n_wet_aoi_arr, out=wet_fill_pct, where=n_wet_aoi_arr > 0)

    return pd.DataFrame(
        {
            "n_water": n_water_arr.astype(np.int64),
            "n_aoi": n_aoi_arr.astype(np.int64),
            "n_valid": n_valid_arr.astype(np.int64),
            "n_invalid": n_invalid_arr.astype(np.int64),
            "n_wet_aoi": n_wet_aoi_arr.astype(np.int64),
            "extent_pct": extent_pct,
            "invalid_pct": invalid_pct,
            "wet_fill_pct": wet_fill_pct,
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
    quality_policy: QualityPolicy = "exclude",
) -> pd.DataFrame:
    """Detect hydrological years from a complete, quality-screened monthly series.

    ``invalid_pct`` is honoured when supplied in a DataFrame. The conservative
    default rejects months with more than 20% invalid coverage. Set
    ``quality_policy="flag"`` to retain those observations and continue while
    leaving quality interpretation to the caller.
    """
    if not 0 <= max_invalid_pct <= 100:
        raise ValueError("max_invalid_pct must be between 0 and 100.")
    if quality_policy not in {"exclude", "flag"}:
        raise ValueError("quality_policy must be 'exclude' or 'flag'.")
    cfg = config or HydroYearConfig()
    series, invalid_pct, full_index = _coerce_monthly_series(
        extent,
        value_col=value_col,
        date_col=date_col,
        duplicate_month_policy=duplicate_month_policy,
    )
    if invalid_pct is not None and quality_policy == "exclude":
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
        wet_start, wet_end, dry_start, dry_end = cfg.windows_for_year(year)
        wet = _window(series, wet_start, wet_end)
        dry = _window(series, dry_start, dry_end)
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
    return _assign_confidence(_assign_end_dry_spans(result, series.index), cfg, series)


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


def _noise_floor_pp(series: pd.Series) -> float:
    """Robust month-to-month noise scale, in percentage points.

    Month-of-year medians are removed first so a genuine seasonal cycle is not
    counted as noise; the MAD of successive differences of the residual then
    estimates the scale of variation that carries no annual information.
    """
    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if len(values) < 3:
        return 0.0
    residual = values - values.groupby(values.index.month).transform("median")
    delta = residual.diff().dropna().to_numpy(float)
    if not len(delta):
        return 0.0
    centre = float(np.median(delta))
    scale = 1.4826 * float(np.median(np.abs(delta - centre))) / np.sqrt(2.0)
    # Successive differences of an AR(1) series recover sigma*sqrt(1-phi), not
    # sigma, so on a persistent record (multi-year wet and dry spells are the
    # norm in dryland catchments) this under-reads the true spread -- and it
    # under-reads most on exactly the records whose apparent amplitude is
    # persistence rather than season. Rescale to the iid-equivalent spread.
    if residual.std(ddof=0) == 0:
        phi = 0.0
    else:
        phi = float(pd.Series(residual.to_numpy(float)).autocorr(1) or 0.0)
    phi = min(max(phi, 0.0), 0.9)
    return scale / np.sqrt(1.0 - phi)


def _assign_confidence(result, cfg, series=None):
    out = result.copy()
    positive = out.loc[out["amplitude_pct"] > 0, "amplitude_pct"]
    typical = float(positive.median()) if len(positive) else 0.0
    out["confidence"] = np.select(
        [out["amplitude_pct"] <= max(0.0, typical * cfg.low_confidence_ratio), out["amplitude_pct"] <= max(0.0, typical * cfg.medium_confidence_ratio)],
        ["low", "medium"], default="high",
    )
    # The grade above is purely relative to this record's own median amplitude,
    # so a record containing nothing but noise still rates most of its years
    # "high" -- precisely where a caller most needs a warning. Cap the grade
    # against an absolute noise floor so a year must clear month-to-month
    # variability to earn confidence. This can only lower a grade, never raise
    # one, so records carrying real signal are unaffected.
    if series is not None:
        noise = _noise_floor_pp(series)
        if noise > 0:
            # amplitude_pct is a max-minus-min, whose expected value grows with
            # window length even for pure noise (the range of n iid draws is
            # ~2*sqrt(ln n) standard deviations). Comparing against a flat
            # multiple of noise would therefore keep passing longer windows;
            # compare against the range noise alone would produce over this
            # year's own span instead.
            months = out["n_months_cycle"].clip(lower=3).astype(float)
            expected_noise_range = noise * 2.0 * np.sqrt(np.log(months))
            ratio = out["amplitude_pct"] / expected_noise_range
            out.loc[(ratio <= 1.5) & (out["confidence"] == "high"), "confidence"] = "medium"
            out.loc[ratio <= 1.0, "confidence"] = "low"
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


__all__ = [
    "HydroYearConfig",
    "detect_hydrological_years",
    "label_hydrological_months",
    "monthly_water_extent",
    "suggest_hydro_year_config",
]
