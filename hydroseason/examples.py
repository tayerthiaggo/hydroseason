"""Small helpers for runnable HydroSeason examples.

These keep notebooks focused on workflow decisions while reusing the public
loaders that real applications should call directly.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hydroseason.io import load_extent_csv, load_wofs_monthly_extent


def create_mock_extent_data(start_date: str = "2006-01-01", periods: int = 240) -> pd.DataFrame:
    """Create deterministic monthly extent data for offline examples."""
    dates = pd.date_range(start_date, periods=periods, freq="MS")
    months = dates.month

    seasonal = 45.0 + 35.0 * np.cos(2 * np.pi * (months - 2) / 12)
    year_shift = {
        2011: 8.0,
        2015: -12.0,
        2016: -9.0,
        2019: -14.0,
        2022: 11.0,
        2023: 7.0,
    }
    shifts = np.array([year_shift.get(int(year), 0.0) for year in dates.year])

    rng = np.random.default_rng(42)
    noise = rng.normal(0, 2.2, size=len(dates))
    extent_pct = np.clip(seasonal + shifts + noise, 0, 100)

    invalid_pct = np.clip(rng.exponential(scale=2.0, size=len(dates)), 0, 100)
    for index, value in ((20, 18.0), (117, 16.0)):
        if index < len(invalid_pct):
            invalid_pct[index] = value

    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "extent_pct": np.round(extent_pct, 2),
            "invalid_pct": np.round(invalid_pct, 2),
        }
    )


def load_example_csv_extent(
    output_path: str | Path,
    *,
    start_date: str = "2006-01-01",
    periods: int = 240,
) -> pd.DataFrame:
    """Write deterministic example CSV data and load it through the CSV loader.

    Warns loudly: the returned frame is SYNTHETIC. It is shaped to look like a
    plausible monsoonal catchment, so nothing downstream -- plots, detected
    hydrological years, an HTML report -- betrays that the numbers are
    invented. A caller who reaches this because a real CSV was missing must be
    told, or they will read fabricated output as a measurement.
    """
    import warnings

    output_path = Path(output_path)
    warnings.warn(
        f"Generating SYNTHETIC example water-extent data at {output_path}. "
        "These numbers are invented, not measured, and any analysis or report "
        "derived from them is illustrative only.",
        UserWarning,
        stacklevel=2,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    create_mock_extent_data(start_date=start_date, periods=periods).to_csv(output_path, index=False)
    return load_extent_csv(output_path, date_col="date", value_col="extent_pct")


def load_csv_extent_option(path: str | Path) -> pd.DataFrame:
    """Load an existing monthly extent CSV without generating example data."""
    return load_extent_csv(path, date_col="date", value_col="extent_pct")


def flag_extent_quality(
    extent: pd.DataFrame,
    *,
    max_invalid_pct: float = 10.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the observed extent unchanged plus an auditable quality table."""
    if not 0.0 <= max_invalid_pct <= 100.0:
        raise ValueError("max_invalid_pct must be between 0 and 100.")
    frame = extent.copy()
    frame.index = pd.to_datetime(frame.index).to_period("M").to_timestamp()
    if frame.index.has_duplicates:
        raise ValueError("extent contains duplicate month timestamps.")
    frame = frame.sort_index().reindex(
        pd.date_range(frame.index.min(), frame.index.max(), freq="MS")
    )
    values = pd.to_numeric(frame["extent_pct"], errors="coerce")
    invalid = pd.to_numeric(
        frame["invalid_pct"] if "invalid_pct" in frame else pd.Series(np.nan, index=frame.index),
        errors="coerce",
    )
    quality = pd.DataFrame(
        {
            "extent_pct_raw": values,
            "invalid_pct": invalid,
        },
        index=frame.index,
    )
    quality["quality_flag"] = np.select(
        [values.isna(), invalid.isna(), invalid.gt(max_invalid_pct)],
        ["missing_extent", "unknown_invalid_pct", "high_invalid_pct"],
        default="usable",
    )
    quality["bias_warning"] = np.where(
        quality["quality_flag"].isin(["high_invalid_pct", "missing_extent"]),
        "Potential bias: invalid coverage exceeded MAX_INVALID_PCT or extent was missing; no fill applied.",
        "",
    )
    return frame, quality


def dynamic_hydro_years_for_report(dynamic_years: pd.DataFrame) -> pd.DataFrame:
    """Adapt dynamic HY output to the fixed-window report schema."""
    required = {
        "hy_year", "status", "hy_start", "hy_end", "peak_month", "peak_extent_pct",
        "temporal_mid_dry_month", "temporal_mid_dry_extent_pct", "trough_month",
        "trough_extent_pct", "cycle_months", "confidence",
    }
    missing = sorted(required.difference(dynamic_years.columns))
    if missing:
        raise ValueError(f"Dynamic HY output is missing report columns: {missing}.")
    resolved = dynamic_years.loc[
        dynamic_years["status"].isin(["complete", "partial"])
        & dynamic_years[["hy_start", "hy_end", "peak_month", "trough_month"]].notna().all(axis=1)
    ].copy()
    return pd.DataFrame(
        {
            "hy_year": resolved["hy_year"].astype(int),
            "hy_start": resolved["hy_start"],
            "hy_end": resolved["hy_end"],
            "peak_month": resolved["peak_month"],
            "peak_extent_pct": resolved["peak_extent_pct"],
            "mid_dry_month": resolved["temporal_mid_dry_month"],
            "mid_extent_pct": resolved["temporal_mid_dry_extent_pct"],
            "end_dry_month": resolved["trough_month"],
            "end_extent_pct": resolved["trough_extent_pct"],
            "amplitude_pct": resolved["peak_extent_pct"] - resolved["trough_extent_pct"],
            "n_months_cycle": resolved["cycle_months"],
            "confidence": resolved["confidence"],
            "boundary_source": "dynamic_trough",
        },
        index=resolved.index,
    ).reset_index(drop=True)


def load_example_stac_extent(
    *,
    stac_url: str,
    collection: str,
    aoi_path: str | Path,
    start_date: str,
    end_date: str,
    crs: int | str | None = 3577,
    cache_dir: str | Path | None = None,
    resolution: float | None = None,
    time_block: int = 12,
    force: bool = False,
    tile_pixels: int | None = None,
    precompute_wet_aoi: bool = False,
) -> pd.DataFrame:
    """Load WOfS monthly extent from STAC using the bounded cached path.

    ``tile_pixels``/``precompute_wet_aoi`` opt into the tiled, wet-AOI-pruned
    fast path (see :func:`hydroseason.io.load_wofs_monthly_extent`); left at
    their defaults this is the plain whole-AOI load.
    """
    return load_wofs_monthly_extent(
        stac_url,
        collection,
        aoi_path,
        start_date,
        end_date,
        crs=crs,
        cache_dir=cache_dir,
        resolution=resolution,
        time_block=time_block,
        force=force,
        tile_pixels=tile_pixels,
        precompute_wet_aoi=precompute_wet_aoi,
    )


def load_workflow_extent(
    *,
    input_source: str,
    run_remote_stac: bool,
    csv_fallback_when_stac_disabled: bool,
    csv_path: str | Path,
    stac_url: str,
    collection: str,
    aoi_path: str | Path,
    start_date: str,
    end_date: str,
    periods: int,
    crs: int | str | None = 3577,
    cache_dir: str | Path | None = None,
    time_block: int = 12,
    resolution: float | None = None,
    tile_pixels: int | None = None,
    precompute_wet_aoi: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Load monthly extent for examples, preferring STAC with CSV fallback.

    ``resolution``/``tile_pixels``/``precompute_wet_aoi`` are forwarded to
    :func:`load_example_stac_extent` and only take effect on the real STAC
    path (``input_source="stac"`` and ``run_remote_stac=True``); the CSV and
    CSV-fallback paths ignore them, since there is no STAC load to tile or
    prune there.
    """
    if input_source == "stac" and run_remote_stac:
        extent = load_example_stac_extent(
            stac_url=stac_url,
            collection=collection,
            aoi_path=aoi_path,
            start_date=start_date,
            end_date=end_date,
            crs=crs,
            cache_dir=cache_dir,
            time_block=time_block,
            resolution=resolution,
            tile_pixels=tile_pixels,
            precompute_wet_aoi=precompute_wet_aoi,
        )
        return extent, "stac"
    if input_source == "stac" and csv_fallback_when_stac_disabled:
        extent = load_csv_extent_option(csv_path) if Path(csv_path).exists() else load_example_csv_extent(
            csv_path, start_date=start_date, periods=periods
        )
        return extent, "csv_fallback"
    if input_source == "csv":
        extent = load_csv_extent_option(csv_path) if Path(csv_path).exists() else load_example_csv_extent(
            csv_path, start_date=start_date, periods=periods
        )
        return extent, "csv"
    raise ValueError("Set input_source to 'stac' or 'csv'.")


__all__ = [
    "create_mock_extent_data",
    "dynamic_hydro_years_for_report",
    "flag_extent_quality",
    "load_csv_extent_option",
    "load_example_csv_extent",
    "load_example_stac_extent",
    "load_workflow_extent",
]
