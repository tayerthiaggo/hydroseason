"""Bounded, resumable STAC-to-monthly-extent loading."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from hydroseason.hydro_year import monthly_water_extent

_CACHE_SCHEMA_VERSION = 1
_EXTENT_COLUMNS = (
    "n_water",
    "n_aoi",
    "n_valid",
    "n_invalid",
    "extent_pct",
    "invalid_pct",
)


def _aoi_digest(aoi) -> str:
    if isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if hasattr(aoi, "to_json"):
        payload = f"{getattr(aoi, 'crs', None)}\n{aoi.to_json()}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    return hashlib.sha256(repr(aoi).encode("utf-8")).hexdigest()


def _year_windows(start: pd.Timestamp, end: pd.Timestamp):
    for year in range(start.year, end.year + 1):
        yield max(start, pd.Timestamp(year, 1, 1)), min(end, pd.Timestamp(year, 12, 31))


def _cache_path(
    cache_dir: Path,
    *,
    stac_url: str,
    collection: str,
    aoi_hash: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    crs,
    resolution,
    majority: bool,
) -> Path:
    identity = {
        "schema": _CACHE_SCHEMA_VERSION,
        "stac_url": stac_url,
        "collection": collection,
        "aoi_sha256": aoi_hash,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "crs": crs,
        "resolution": resolution,
        "majority": majority,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"extent_{start:%Y%m%d}_{end:%Y%m%d}_{digest}.csv"


def _read_cached_extent(path: Path) -> pd.DataFrame | None:
    try:
        frame = pd.read_csv(path, index_col="time", parse_dates=["time"])
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    if tuple(frame.columns) != _EXTENT_COLUMNS or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    frame.index.name = None
    return frame


def _write_extent_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp"
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        frame.to_csv(temporary_path, index_label="time")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _missing_year_extent(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    index = pd.date_range(
        start.to_period("M").to_timestamp(), end.to_period("M").to_timestamp(), freq="MS"
    )
    return pd.DataFrame(
        {
            "n_water": 0,
            "n_aoi": 0,
            "n_valid": 0,
            "n_invalid": 0,
            "extent_pct": float("nan"),
            "invalid_pct": float("nan"),
        },
        index=index,
    )


def _aggregate_extent_parts(parts, index):
    """Aggregate per-tile monthly extent counts into annual totals.

    Sums raw integer pixel counts across tiles (n_water, n_aoi, n_valid, n_invalid),
    then recomputes percentages from the summed counts. Enforces the invariant
    n_aoi == n_valid + n_invalid, and produces NaN percentages when denominators are zero.
    """
    count_columns = ["n_water", "n_aoi", "n_valid", "n_invalid"]
    totals = pd.DataFrame(0, index=index, columns=count_columns, dtype="int64")
    for part in parts:
        aligned = part.reindex(index)
        totals = totals.add(aligned[count_columns].fillna(0).astype("int64"), fill_value=0)

    if not (totals["n_aoi"] == totals["n_valid"] + totals["n_invalid"]).all():
        raise ValueError("tile counts violate n_aoi == n_valid + n_invalid")

    extent_pct = np.full(len(totals), np.nan, dtype=float)
    invalid_pct = np.full(len(totals), np.nan, dtype=float)
    np.divide(
        totals["n_water"].to_numpy(dtype=float) * 100.0,
        totals["n_valid"].to_numpy(dtype=float),
        out=extent_pct,
        where=totals["n_valid"].to_numpy() > 0,
    )
    np.divide(
        totals["n_invalid"].to_numpy(dtype=float) * 100.0,
        totals["n_aoi"].to_numpy(dtype=float),
        out=invalid_pct,
        where=totals["n_aoi"].to_numpy() > 0,
    )
    totals["extent_pct"] = extent_pct
    totals["invalid_pct"] = invalid_pct
    return totals.loc[:, _EXTENT_COLUMNS]


def load_wofs_monthly_extent(
    stac_url: str,
    collection: str,
    aoi,
    start_date: str,
    end_date: str,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    crs: int | str | None = 3577,
    resolution: float | None = None,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_block: int = 12,
    majority: bool = True,
    force: bool = False,
    tile_pixels: int | None = None,
) -> pd.DataFrame:
    """Compute monthly WOfS extent in resumable calendar-year pieces.

    Each year is loaded and reduced independently, bounding graph size and
    allowing a stopped run to resume from its last completed year.  When
    ``cache_dir`` is supplied, CSV cache identity includes all data-affecting
    inputs and the AOI content hash.

    When ``tile_pixels`` is set, each annual window is loaded tile-by-tile via
    :func:`hydroseason.io.iter_wofs_tiles_from_stac` instead of as one whole-AOI
    load. Already-cached tile CSVs (under a per-year tile-cache directory
    derived from the annual cache path) are read and their ids passed as
    ``skip_tile_ids``, so an interrupted year resumes at tile granularity on
    the next call. This has no effect on the annual cache's identity: a
    complete annual result is tile-shape-independent, so it is written to and
    read from the same cache file as the untiled path.
    """
    if time_block < 1:
        raise ValueError("time_block must be at least 1.")
    if tile_pixels is not None:
        if tile_pixels < 1:
            raise ValueError("tile_pixels must be at least 1.")
        if resolution is None or resolution <= 0:
            raise ValueError("tiled loading requires a positive resolution.")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date.")

    cache_root = Path(cache_dir) if cache_dir is not None else None
    aoi_hash = _aoi_digest(aoi) if cache_root is not None else ""
    parts: list[pd.DataFrame] = []

    # Resolve through the facade at call time to preserve the existing loader
    # monkeypatch seam and keep this module independent of optional STAC deps.
    import hydroseason.io as _io

    for year_start, year_end in _year_windows(start, end):
        expected_index = pd.date_range(
            year_start.to_period("M").to_timestamp(),
            year_end.to_period("M").to_timestamp(),
            freq="MS",
        )
        cache_path = None
        if cache_root is not None:
            cache_path = _cache_path(
                cache_root,
                stac_url=stac_url,
                collection=collection,
                aoi_hash=aoi_hash,
                start=year_start,
                end=year_end,
                crs=crs,
                resolution=resolution,
                majority=majority,
            )
            cached = None if force or not cache_path.exists() else _read_cached_extent(cache_path)
            if cached is not None and not cached.index.equals(expected_index):
                cached = None
            if cached is not None:
                parts.append(cached)
                continue

        if tile_pixels is not None:
            tile_cache_dir = None
            if cache_path is not None:
                tile_cache_dir = cache_path.parent / f"{cache_path.stem}_tiles_{tile_pixels}"

            tile_parts: dict[str, pd.DataFrame] = {}
            if tile_cache_dir is not None and not force:
                for path in sorted(tile_cache_dir.glob("*.csv")):
                    cached_tile = _read_cached_extent(path)
                    if cached_tile is not None and cached_tile.index.equals(expected_index):
                        tile_parts[path.stem] = cached_tile

            try:
                tiles = _io.iter_wofs_tiles_from_stac(
                    stac_url,
                    collection,
                    aoi,
                    year_start.strftime("%Y-%m-%d"),
                    year_end.strftime("%Y-%m-%d"),
                    crs=crs,
                    resolution=resolution,
                    tile_pixels=tile_pixels,
                    chunk_x=chunk_x,
                    chunk_y=chunk_y,
                    time_chunk=time_block,
                    majority=majority,
                    skip_tile_ids=set(tile_parts),
                )
                for tile_id, water_mask in tiles:
                    tile_extent = monthly_water_extent(water_mask, time_block=time_block)
                    if not tile_extent.index.equals(expected_index):
                        raise ValueError(f"tile {tile_id} has an unexpected monthly index")
                    if tile_cache_dir is not None:
                        _write_extent_atomic(tile_extent, tile_cache_dir / f"{tile_id}.csv")
                    tile_parts[tile_id] = tile_extent
            except ValueError as exc:
                if "No STAC items found" not in str(exc):
                    raise
                extent = _missing_year_extent(year_start, year_end)
            else:
                extent = _aggregate_extent_parts(tile_parts.values(), expected_index)
            if cache_path is not None:
                _write_extent_atomic(extent, cache_path)
            parts.append(extent)
            continue

        try:
            water_mask = _io.load_wofs_from_stac(
                stac_url,
                collection,
                aoi,
                year_start.strftime("%Y-%m-%d"),
                year_end.strftime("%Y-%m-%d"),
                crs=crs,
                resolution=resolution,
                chunk_x=chunk_x,
                chunk_y=chunk_y,
                time_chunk=time_block,
                majority=majority,
            )
        except ValueError as exc:
            if "No STAC items found" not in str(exc):
                raise
            extent = _missing_year_extent(year_start, year_end)
        else:
            extent = monthly_water_extent(water_mask, time_block=time_block)
        if cache_path is not None:
            _write_extent_atomic(extent, cache_path)
        parts.append(extent)

    combined = pd.concat(parts).sort_index()
    if combined.index.has_duplicates:
        duplicates = combined.index[combined.index.duplicated()].unique()
        raise ValueError(f"duplicate cached extent months: {list(duplicates)}")
    return combined


__all__ = ["load_wofs_monthly_extent"]
