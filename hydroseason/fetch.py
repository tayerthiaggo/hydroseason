"""SILO/CHIRPS/ERA5 rainfall fetch helpers returning monthly tidy DataFrames.

Improvements over the prototype:

- Polygon mask applied before temporal resampling.
- Explicit spatial chunking to keep Dask graph sizes manageable.
- Variable adapter registry for ERA5 rainfall conversion.
- Optional Parquet cache keyed by inputs hash.
- Unified fetch progress bar across the full requested year range.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .era5_variables import ERA5Variable, get as get_era5_variable

logger = logging.getLogger(__name__)

SILO_MONTHLY_RAIN_BASE_URL = (
    "https://s3-ap-southeast-2.amazonaws.com/"
    "silo-open-data/Official/annual/monthly_rain"
)
CHIRPS_V3_MONTHLY_COG_BASE_URL = (
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/"
    "monthly/global/cogs"
)
CHIRPS_V3_MONTHLY_TIF_BASE_URL = (
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/"
    "monthly/global/tifs"
)
CHIRPS_START_YEAR = 1981
CHIRPS_LAT_MIN = -60.0
CHIRPS_LAT_MAX = 60.0
_AUSTRALIA_BOUNDS = (112.0, -44.0, 154.0, -9.0)


@dataclass(frozen=True)
class _SystemProfile:
    cpu_count: int
    memory_gib: float


class _FetchProgressBar:
    """Simple single-line progress bar for multi-year fetch workflows."""

    def __init__(
        self,
        total: int,
        *,
        label: str,
        enabled: bool,
        stream=None,
        width: int = 28,
        unit: str = "years",
    ) -> None:
        self.total = max(0, int(total))
        self.label = str(label)
        self.enabled = bool(enabled) and self.total > 0
        self.stream = sys.stderr if stream is None else stream
        self.width = max(10, int(width))
        self.unit = str(unit)
        self.current = 0
        self.stage = "starting"

    def set_stage(self, stage: str) -> None:
        if not self.enabled:
            return
        self.stage = str(stage)
        self._render()

    def advance(self, step: int = 1) -> None:
        if not self.enabled:
            return
        self.current = min(self.total, self.current + max(0, int(step)))
        self._render()

    def close(self) -> None:
        if not self.enabled:
            return
        if self.current < self.total:
            self.current = self.total
            self._render()
        self.stream.write("\n")
        self.stream.flush()

    def _render(self) -> None:
        ratio = 1.0 if self.total == 0 else self.current / self.total
        filled = min(self.width, int(round(self.width * ratio)))
        bar = "#" * filled + "-" * (self.width - filled)
        percent = ratio * 100.0
        message = (
            f"\r{self.label} [{bar}] "
            f"{self.current}/{self.total} {self.unit} "
            f"({percent:5.1f}%) - {self.stage}"
        )
        self.stream.write(message)
        self.stream.flush()


def _system_memory_gib() -> float:
    """Best-effort total system memory in GiB.

    Uses optional dependencies when present, then stdlib fallbacks.
    """
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().total) / (1024**3)
    except Exception:
        pass

    # POSIX fallback
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        phys_pages = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        page_size = 0
        phys_pages = 0
    if page_size > 0 and phys_pages > 0:
        return float(page_size * phys_pages) / (1024**3)

    # Windows fallback
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return float(stat.ullTotalPhys) / (1024**3)
    except Exception:
        pass

    # Conservative fallback when memory cannot be determined.
    return 8.0


def _detect_system_profile() -> _SystemProfile:
    return _SystemProfile(
        cpu_count=max(1, int(os.cpu_count() or 1)),
        memory_gib=max(1.0, float(_system_memory_gib())),
    )


def _is_auto_chunk(value: int | str | None) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() == "auto"
    )


def _auto_spatial_chunk(
    profile: _SystemProfile,
    *,
    grid_shape: tuple[int, int] | None = None,
) -> int:
    # Heuristic tuned for AOI masking + reductions. Goal: avoid OOM on
    # large catchments while keeping chunk/task count reasonable.
    chunk = 32
    if profile.memory_gib >= 16:
        chunk = 48
    if profile.memory_gib >= 32:
        chunk = 64
    if profile.memory_gib >= 64:
        chunk = 96

    if profile.cpu_count >= 16:
        chunk += 16
    elif profile.cpu_count <= 4:
        chunk -= 8

    chunk = max(16, min(128, chunk))

    if grid_shape is not None:
        n_lat, n_lon = grid_shape
        max_dim = max(1, int(max(n_lat, n_lon)))
        total_cells = max(1, int(n_lat) * int(n_lon))
        if total_cells <= 4096:
            chunk = min(32, max_dim)
        else:
            chunk = min(chunk, max_dim)
    return int(max(8, chunk))


def _auto_time_chunk(
    profile: _SystemProfile,
    *,
    total_steps: int | None = None,
) -> int:
    # ERA5 source is hourly. Chunk by a few days to a week depending on
    # machine capacity; this keeps per-task memory bounded.
    chunk = 24
    if profile.memory_gib >= 16:
        chunk = 48
    if profile.memory_gib >= 32:
        chunk = 72
    if profile.memory_gib >= 64:
        chunk = 96

    if profile.cpu_count >= 16:
        chunk += 24
    elif profile.cpu_count <= 4:
        chunk -= 12

    chunk = max(12, min(168, chunk))
    if total_steps is not None:
        chunk = min(chunk, max(1, int(total_steps)))
    return int(chunk)


def _resolve_spatial_chunk(
    value: int | str | None,
    *,
    profile: _SystemProfile,
    grid_shape: tuple[int, int] | None = None,
) -> int:
    if _is_auto_chunk(value):
        return _auto_spatial_chunk(profile, grid_shape=grid_shape)
    if int(value) < 1:
        raise ValueError("spatial_chunk must be a positive integer or 'auto'.")
    return int(value)


def _resolve_time_chunk(
    value: int | str | None,
    *,
    profile: _SystemProfile,
    total_steps: int | None = None,
) -> int:
    if _is_auto_chunk(value):
        return _auto_time_chunk(profile, total_steps=total_steps)
    if int(value) < 1:
        raise ValueError("time_chunk must be a positive integer or 'auto'.")
    return int(value)


def _resolve_temporal_batch_years(
    value: int | str | None,
    *,
    start_year: int,
    end_year: int,
    profile: _SystemProfile,
    grid_shape: tuple[int, int] | None = None,
) -> int:
    n_years = max(1, int(end_year) - int(start_year) + 1)
    if _is_auto_chunk(value):
        total_cells = None
        if grid_shape is not None:
            total_cells = max(1, int(grid_shape[0]) * int(grid_shape[1]))

        if n_years <= 5:
            return n_years
        if profile.memory_gib < 16:
            return 1
        if total_cells is not None and total_cells >= 20000:
            return 1
        if n_years >= 30:
            return 2
        if n_years >= 12:
            return 3
        return n_years

    if int(value) < 1:
        raise ValueError(
            "temporal_batch_years must be a positive integer or 'auto'."
        )
    return min(int(value), n_years)


# ---------------------------------------------------------------------------
# Spatial helpers (CRS-light, lazy imports for optional deps)
# ---------------------------------------------------------------------------


def _wrap_lon_to_ds_range(lon_vals, ds_lon):
    lo, hi = float(ds_lon.min()), float(ds_lon.max())
    if lo >= 0 and hi <= 360:
        return np.mod(lon_vals, 360)
    elif lo >= -180 and hi <= 180:
        lon = np.array(lon_vals)
        return np.where(lon > 180, lon - 360, lon)
    return lon_vals


def _coord_step(coord_vals) -> float | None:
    coord = np.asarray(coord_vals, dtype=float)
    if coord.size < 2:
        return None
    diffs = np.abs(np.diff(coord))
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return None
    return float(np.median(diffs))


def _coord_edges(coord_vals, *, step: float | None = None) -> np.ndarray:
    coord = np.asarray(coord_vals, dtype=float)
    if coord.size == 0:
        raise ValueError(
            "Cannot infer grid edges from an empty coordinate axis."
        )
    if coord.size == 1:
        if step is None:
            raise ValueError(
                "Cannot infer grid spacing from a single coordinate axis "
                "without an explicit step."
            )
        half = abs(float(step)) / 2.0
        return np.array([coord[0] - half, coord[0] + half], dtype=float)

    mids = (coord[:-1] + coord[1:]) / 2.0
    first = coord[0] - (mids[0] - coord[0])
    last = coord[-1] + (coord[-1] - mids[-1])
    return np.concatenate(([first], mids, [last]))


def _bbox_indexer(
    coord_vals,
    lower: float,
    upper: float,
    *,
    step: float | None = None,
    label: str = "coordinate",
) -> slice:
    coord = np.asarray(coord_vals, dtype=float)
    if coord.size == 0:
        raise ValueError(f"Cannot subset an empty {label} coordinate axis.")

    lo, hi = sorted([float(lower), float(upper)])
    edges = _coord_edges(coord, step=step)
    cell_lo = np.minimum(edges[:-1], edges[1:])
    cell_hi = np.maximum(edges[:-1], edges[1:])
    hits = np.flatnonzero((cell_hi > lo) & (cell_lo < hi))

    if hits.size == 0:
        raise ValueError(
            f"AOI bounds [{lo}, {hi}] do not overlap the dataset {label} "
            f"extent [{float(cell_lo.min())}, {float(cell_hi.max())}]."
        )

    return slice(int(hits[0]), int(hits[-1]) + 1)


def rasterize_to_xarray_grid(
    gdf,
    ds,
    lon_name="longitude",
    lat_name="latitude",
    lon_step: float | None = None,
    lat_step: float | None = None,
    all_touched=False,
    dtype="uint8",
):
    import xarray as xr
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
    from shapely.geometry import mapping

    lon = np.asarray(ds[lon_name].values, dtype=float)
    lat = np.asarray(ds[lat_name].values, dtype=float)
    if lon.size == 0 or lat.size == 0:
        raise ValueError(
            "Cannot rasterize AOI onto an empty grid selection "
            f"(latitude={lat.size}, longitude={lon.size})."
        )

    lon_edges = _coord_edges(lon, step=lon_step or _coord_step(lon))
    lat_edges = _coord_edges(lat, step=lat_step or _coord_step(lat))
    transform = from_bounds(
        float(lon_edges.min()),
        float(lat_edges.min()),
        float(lon_edges.max()),
        float(lat_edges.max()),
        len(lon),
        len(lat),
    )
    shapes = [(mapping(geom), 1) for geom in gdf.geometry]
    mask_np = rasterize(
        shapes=shapes,
        out_shape=(len(lat), len(lon)),
        transform=transform,
        fill=0,
        all_touched=all_touched,
        dtype=dtype,
    )
    if not mask_np.any() and not all_touched:
        mask_np = rasterize(
            shapes=shapes,
            out_shape=(len(lat), len(lon)),
            transform=transform,
            fill=0,
            all_touched=True,
            dtype=dtype,
        )
    return xr.DataArray(
        mask_np.astype(bool),
        coords={lat_name: ds[lat_name], lon_name: ds[lon_name]},
        dims=(lat_name, lon_name),
        name="mask",
    )


def load_vector(path: str | Path):
    """Load a polygon vector file (GeoJSON/SHP/KML/KMZ/GPKG/GPCK and others).

    Parameters
    ----------
    path : str | Path
        Input vector path.
    """
    import geopandas as gpd

    path = Path(path)
    suffix = path.suffix.lower()

    # Accept the common typo/variant ".gpck" by reading through a temporary
    # ".gpkg" filename so GDAL/Fiona can resolve the driver reliably.
    if suffix == ".gpck":
        with tempfile.TemporaryDirectory() as tmpdir:
            gpkg_alias = Path(tmpdir) / f"{path.stem}.gpkg"
            gpkg_alias.write_bytes(path.read_bytes())
            gdf = gpd.read_file(gpkg_alias)
        if gdf.empty or gdf.geometry.isna().all():
            raise ValueError(
                f"No valid geometries found in vector file: {path}"
            )
        gdf = gdf[gdf.geometry.notna()].copy()
        gdf = gdf[gdf.geometry.is_valid].copy()
        if gdf.empty:
            raise ValueError(
                f"No valid polygon geometries found in vector file: {path}"
            )
        return gdf

    if suffix == ".kmz":
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(path) as zf:
                kml_names = [
                    n for n in zf.namelist() if n.lower().endswith(".kml")
                ]
                if not kml_names:
                    raise ValueError(f"KMZ has no .kml file: {path}")
                target_name = kml_names[0]
                extracted = Path(tmpdir) / Path(target_name).name
                extracted.write_bytes(zf.read(target_name))
            gdf = gpd.read_file(extracted)
    else:
        gdf = gpd.read_file(path)

    if gdf.empty or gdf.geometry.isna().all():
        raise ValueError(f"No valid geometries found in vector file: {path}")

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[gdf.geometry.is_valid].copy()
    if gdf.empty:
        raise ValueError(
            f"No valid polygon geometries found in vector file: {path}"
        )
    return gdf


def _bounds_4326(gdf) -> tuple[object, tuple[float, float, float, float]]:
    gdf_4326 = gdf.to_crs("EPSG:4326")
    bounds = tuple(float(x) for x in gdf_4326.total_bounds.tolist())
    return gdf_4326, bounds


def _aoi_within_australia(gdf) -> bool:
    _gdf_4326, bounds = _bounds_4326(gdf)
    minx, miny, maxx, maxy = bounds
    aus_minx, aus_miny, aus_maxx, aus_maxy = _AUSTRALIA_BOUNDS
    return (
        minx >= aus_minx
        and maxx <= aus_maxx
        and miny >= aus_miny
        and maxy <= aus_maxy
    )


def _aoi_within_chirps_lat_range(gdf) -> bool:
    _gdf_4326, bounds = _bounds_4326(gdf)
    _minx, miny, _maxx, maxy = bounds
    return miny >= CHIRPS_LAT_MIN and maxy <= CHIRPS_LAT_MAX


def infer_default_fetch_source(gdf) -> str:
    """Infer the practical default rainfall source for an AOI.

    SILO remains the preferred default for Australian AOIs. Elsewhere, use
    CHIRPS because monthly rainfall is the native product HydroSeason needs.
    """
    return "silo" if _aoi_within_australia(gdf) else "chirps"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _cache_key(
    path: str,
    gdf,
    start_year: int,
    end_year: int,
    variable_key: str,
) -> str:
    payload = {
        "path": str(path),
        "start": int(start_year),
        "end": int(end_year),
        "var": variable_key,
        "bbox": [float(x) for x in gdf.total_bounds.tolist()],
        "n_geoms": int(len(gdf)),
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _cache_paths(
    cache_dir: str | Path,
    key: str,
    *,
    prefix: str = "era5_monthly",
) -> tuple[Path, Path]:
    base = Path(cache_dir)
    return base / f"{prefix}_{key}.parquet", base / f"{prefix}_{key}.json"


def _read_cache(
    cache_dir: str | Path | None,
    key: str,
    *,
    prefix: str = "era5_monthly",
) -> pd.DataFrame | None:
    if cache_dir is None:
        return None
    data_path, _ = _cache_paths(cache_dir, key, prefix=prefix)
    if data_path.exists():
        logger.info("Fetch cache hit: %s", data_path)
        return pd.read_parquet(data_path)
    return None


def _write_cache(
    cache_dir: str | Path | None,
    key: str,
    df: pd.DataFrame,
    meta: dict,
    *,
    prefix: str = "era5_monthly",
) -> None:
    if cache_dir is None:
        return
    base = Path(cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    data_path, meta_path = _cache_paths(base, key, prefix=prefix)
    df.to_parquet(data_path, index=False)
    meta_path.write_text(
        json.dumps(meta, default=str, indent=2), encoding="utf-8"
    )
    logger.info("Fetch cache write: %s", data_path)


def _year_stage_label(start_year: int, end_year: int) -> str:
    if int(start_year) == int(end_year):
        return f"processing {int(start_year)}"
    return f"processing {int(start_year)}-{int(end_year)}"


def _source_metadata(
    df: pd.DataFrame,
    *,
    source: str,
    product: str,
    note: str,
) -> pd.DataFrame:
    out = df.copy()
    out["Data_Source"] = source
    out["Data_Product"] = product
    out["Fetch_Note"] = note
    return out


def _chirps_month_url(base_url: str, year: int, month: int) -> str:
    base = str(base_url).rstrip("/")
    if base.endswith("/tifs"):
        ext = "tif"
    else:
        ext = "cog"
    return f"{base}/chirps-v3.0.{int(year)}.{int(month):02d}.{ext}"


def _chirps_tif_url(year: int, month: int) -> str:
    return _chirps_month_url(CHIRPS_V3_MONTHLY_TIF_BASE_URL, year, month)


def _is_recent_chirps_month(year: int, month: int) -> bool:
    # CHIRPS final monthly products lag real time. Missing recent months should
    # shorten the returned record rather than fail a long historical fetch.
    period = pd.Timestamp(year=int(year), month=int(month), day=1, tz="UTC")
    current_month = pd.Timestamp.now(tz="UTC").normalize().replace(day=1)
    cutoff = current_month - pd.DateOffset(months=2)
    return bool(period >= cutoff)


def _read_chirps_month(gdf, url: str) -> float:
    """Read one CHIRPS monthly raster and return the AOI mean rainfall in mm."""
    import rasterio
    from rasterio.mask import mask as raster_mask
    from shapely.geometry import mapping

    with rasterio.open(url) as src:
        target_crs = src.crs or "EPSG:4326"
        gdf_src = gdf.to_crs(target_crs)
        shapes = [mapping(geom) for geom in gdf_src.geometry]
        data, _transform = raster_mask(src, shapes, crop=True, filled=False)

    arr = np.ma.masked_invalid(data[0])
    arr = np.ma.masked_less(arr, 0.0)
    valid = arr.compressed()
    if valid.size == 0:
        return float("nan")
    return float(valid.mean())


def get_monthly_chirps_rainfall(
    gdf,
    start_year: int,
    end_year: int,
    *,
    base_url: str = CHIRPS_V3_MONTHLY_COG_BASE_URL,
    cache_dir: str | Path | None = None,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Fetch CHIRPS v3 monthly AOI-averaged rainfall.

    CHIRPS is a quasi-global, land-only monthly rainfall product. HydroSeason
    uses the monthly rasters directly, avoiding ERA5's hourly-to-monthly
    resampling cost.
    """
    if int(start_year) < CHIRPS_START_YEAR:
        raise ValueError(
            f"CHIRPS starts in {CHIRPS_START_YEAR}; use ERA5 fallback for "
            f"earlier years."
        )
    if not _aoi_within_chirps_lat_range(gdf):
        raise ValueError(
            "CHIRPS v3 global rainfall covers approximately "
            f"{abs(CHIRPS_LAT_MIN):.0f}S-{CHIRPS_LAT_MAX:.0f}N. "
            "Use ERA5 for AOIs outside that latitude range."
        )

    key = _cache_key(
        str(base_url),
        gdf,
        start_year,
        end_year,
        "chirps_v3_monthly",
    )
    cached = _read_cache(cache_dir, key, prefix="chirps_monthly")
    if cached is not None:
        return cached

    gdf_4326, _bounds = _bounds_4326(gdf)
    periods = pd.period_range(
        f"{int(start_year)}-01", f"{int(end_year)}-12", freq="M"
    )
    rows: list[dict[str, object]] = []
    missing_recent: list[str] = []
    progress = _FetchProgressBar(
        len(periods),
        label="CHIRPS",
        enabled=show_progress,
        unit="months",
    )
    try:
        for period in periods:
            year = int(period.year)
            month = int(period.month)
            progress.set_stage(f"processing {year}-{month:02d}")
            url = _chirps_month_url(base_url, year, month)
            product = "CHIRPS v3 monthly COG"
            try:
                value = _read_chirps_month(gdf_4326, url)
            except ImportError:
                raise
            except Exception as first_exc:  # noqa: BLE001 - fallback path
                if str(base_url).rstrip("/") == CHIRPS_V3_MONTHLY_COG_BASE_URL:
                    try:
                        value = _read_chirps_month(
                            gdf_4326, _chirps_tif_url(year, month)
                        )
                        product = "CHIRPS v3 monthly GeoTIFF"
                    except Exception as second_exc:  # noqa: BLE001
                        if _is_recent_chirps_month(year, month):
                            missing_recent.append(f"{year}-{month:02d}")
                            progress.advance()
                            continue
                        raise FileNotFoundError(
                            f"CHIRPS raster unavailable for {year}-{month:02d}: "
                            f"{url}"
                        ) from second_exc
                elif _is_recent_chirps_month(year, month):
                    missing_recent.append(f"{year}-{month:02d}")
                    progress.advance()
                    continue
                else:
                    raise FileNotFoundError(
                        f"CHIRPS raster unavailable for {year}-{month:02d}: {url}"
                    ) from first_exc

            if not np.isfinite(value):
                raise ValueError(
                    f"No valid CHIRPS pixels found inside the AOI for "
                    f"{year}-{month:02d}. CHIRPS is land-only."
                )
            date = period.to_timestamp()
            rows.append(
                {
                    "Date": date.strftime("%Y-%m-%d"),
                    "Year": int(date.year),
                    "Month": int(date.month),
                    "Rainfall_mm": round(max(float(value), 0.0), 2),
                    "Data_Source": "CHIRPS",
                    "Data_Product": product,
                    "Fetch_Note": "CHIRPS v3 monthly rainfall; land-only; 60S-60N",
                }
            )
            progress.advance()
    finally:
        progress.close()

    if not rows:
        raise ValueError("No CHIRPS months were available for the requested range.")

    out = pd.DataFrame(rows)
    if missing_recent:
        missing_note = ", ".join(missing_recent)
        out["Fetch_Note"] = (
            out["Fetch_Note"].astype(str)
            + f"; recent CHIRPS month(s) unavailable: {missing_note}"
        )
    _write_cache(
        cache_dir,
        key,
        out,
        meta={
            "source": "chirps",
            "product": "CHIRPS v3 monthly rainfall",
            "base_url": str(base_url),
            "start_year": int(start_year),
            "end_year": int(end_year),
            "missing_recent_months": missing_recent,
            "unit": "mm",
        },
        prefix="chirps_monthly",
    )
    if missing_recent:
        logger.warning(
            "Skipped recent CHIRPS month(s) not yet available: %s",
            ", ".join(missing_recent),
        )
    return out


def get_monthly_aoi_rainfall(
    gdf,
    start_year: int,
    end_year: int,
    *,
    source: str = "auto",
    era5_zarr_path: str | None = None,
    silo_base_url: str | None = None,
    chirps_base_url: str = CHIRPS_V3_MONTHLY_COG_BASE_URL,
    variable: str = "rainfall",
    cache_dir: str | Path | None = None,
    spatial_chunk: int | str | None = "auto",
    time_chunk: int | str | None = "auto",
    era5_fallback: bool = True,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Fetch monthly AOI rainfall using the package default source policy.

    ``source="auto"`` uses SILO for Australian AOIs and CHIRPS elsewhere.
    ERA5 is used only when explicitly selected, or as a fallback for ranges or
    AOIs outside CHIRPS coverage when ``era5_zarr_path`` is provided.
    """
    resolved_source = str(source).lower().strip()
    if resolved_source == "auto":
        resolved_source = infer_default_fetch_source(gdf)

    if resolved_source == "silo":
        df = get_monthly_silo_rainfall(
            gdf=gdf,
            start_year=start_year,
            end_year=end_year,
            base_url=silo_base_url or SILO_MONTHLY_RAIN_BASE_URL,
            cache_dir=cache_dir,
            spatial_chunk=spatial_chunk,
            show_progress=show_progress,
        )
        return _source_metadata(
            df,
            source="SILO",
            product="SILO monthly rainfall",
            note="Australian gridded monthly rainfall default",
        )

    if resolved_source == "era5":
        if not era5_zarr_path:
            raise ValueError("era5_zarr_path is required when source='era5'.")
        df = get_monthly_era5_rainfall(
            path=era5_zarr_path,
            gdf=gdf,
            start_year=start_year,
            end_year=end_year,
            variable=variable,
            cache_dir=cache_dir,
            spatial_chunk=spatial_chunk,
            time_chunk=time_chunk,
            show_progress=show_progress,
        )
        return _source_metadata(
            df,
            source="ERA5",
            product="ERA5 hourly ARCO Zarr",
            note="ERA5 fallback/exact path; hourly data aggregated to monthly",
        )

    if resolved_source != "chirps":
        raise ValueError("source must be one of {'auto', 'silo', 'chirps', 'era5'}")

    frames: list[pd.DataFrame] = []
    if int(start_year) < CHIRPS_START_YEAR:
        if not (era5_fallback and era5_zarr_path):
            raise ValueError(
                f"Requested start_year={start_year}, but CHIRPS starts in "
                f"{CHIRPS_START_YEAR}. Provide era5_zarr_path or set "
                "source='era5' for longer historical ranges."
            )
        era5_end = min(int(end_year), CHIRPS_START_YEAR - 1)
        frames.append(
            get_monthly_aoi_rainfall(
                gdf,
                int(start_year),
                era5_end,
                source="era5",
                era5_zarr_path=era5_zarr_path,
                variable=variable,
                cache_dir=cache_dir,
                spatial_chunk=spatial_chunk,
                time_chunk=time_chunk,
                show_progress=show_progress,
            )
        )

    chirps_start = max(int(start_year), CHIRPS_START_YEAR)
    if chirps_start <= int(end_year):
        if _aoi_within_chirps_lat_range(gdf):
            try:
                chirps_df = get_monthly_chirps_rainfall(
                    gdf,
                    chirps_start,
                    int(end_year),
                    base_url=chirps_base_url,
                    cache_dir=cache_dir,
                    show_progress=show_progress,
                )
            except ValueError:
                if not (era5_fallback and era5_zarr_path):
                    raise
                logger.warning(
                    "CHIRPS could not cover %s-%s; using ERA5 fallback.",
                    chirps_start,
                    int(end_year),
                )
                frames.append(
                    get_monthly_aoi_rainfall(
                        gdf,
                        chirps_start,
                        int(end_year),
                        source="era5",
                        era5_zarr_path=era5_zarr_path,
                        variable=variable,
                        cache_dir=cache_dir,
                        spatial_chunk=spatial_chunk,
                        time_chunk=time_chunk,
                        show_progress=show_progress,
                    )
                )
            else:
                frames.append(chirps_df)

                expected_dates = pd.date_range(
                    f"{chirps_start}-01-01",
                    f"{int(end_year)}-12-01",
                    freq="MS",
                ).strftime("%Y-%m-%d")
                observed_dates = set(
                    pd.to_datetime(chirps_df["Date"]).dt.strftime("%Y-%m-%d")
                )
                missing_dates = [
                    str(date)
                    for date in expected_dates
                    if str(date) not in observed_dates
                ]
                if missing_dates and era5_fallback and era5_zarr_path:
                    missing_periods = pd.to_datetime(pd.Series(missing_dates))
                    fallback_df = get_monthly_aoi_rainfall(
                        gdf,
                        int(missing_periods.dt.year.min()),
                        int(missing_periods.dt.year.max()),
                        source="era5",
                        era5_zarr_path=era5_zarr_path,
                        variable=variable,
                        cache_dir=cache_dir,
                        spatial_chunk=spatial_chunk,
                        time_chunk=time_chunk,
                        show_progress=show_progress,
                    )
                    fallback_df = fallback_df[
                        pd.to_datetime(fallback_df["Date"])
                        .dt.strftime("%Y-%m-%d")
                        .isin(missing_dates)
                    ].copy()
                    if not fallback_df.empty:
                        fallback_df["Fetch_Note"] = (
                            fallback_df["Fetch_Note"].astype(str)
                            + "; filled CHIRPS-unavailable month"
                        )
                        frames.append(fallback_df)
                elif missing_dates:
                    logger.warning(
                        "CHIRPS returned an incomplete recent range and no "
                        "ERA5 fallback is configured. Missing month(s): %s",
                        ", ".join(missing_dates),
                    )
        elif era5_fallback and era5_zarr_path:
            frames.append(
                get_monthly_aoi_rainfall(
                    gdf,
                    chirps_start,
                    int(end_year),
                    source="era5",
                    era5_zarr_path=era5_zarr_path,
                    variable=variable,
                    cache_dir=cache_dir,
                    spatial_chunk=spatial_chunk,
                    time_chunk=time_chunk,
                    show_progress=show_progress,
                )
            )
        else:
            raise ValueError(
                "AOI falls outside CHIRPS latitude coverage. Provide "
                "era5_zarr_path or set source='era5'."
            )

    if not frames:
        raise ValueError("No rainfall source covered the requested range.")

    out = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["Date"], keep="last")
        .sort_values("Date")
        .reset_index(drop=True)
    )
    if out["Data_Source"].nunique() > 1:
        out["Fetch_Note"] = out["Fetch_Note"].astype(str) + "; mixed-source series"
    return out


# ---------------------------------------------------------------------------
# Main fetch
# ---------------------------------------------------------------------------
def get_monthly_era5_rainfall(
    path: str,
    gdf,
    start_year: int,
    end_year: int,
    *,
    variable: str | ERA5Variable = "rainfall",
    cache_dir: str | Path | None = None,
    spatial_chunk: int | str | None = "auto",
    time_chunk: int | str | None = "auto",
    temporal_batch_years: int | str | None = "auto",
    show_progress: bool = True,
) -> pd.DataFrame:
    """Fetch monthly catchment-averaged values for one ERA5 variable.

    Parameters
    ----------
    path : str
        Zarr store URI (e.g. ``gs://gcp-public-data-arco-era5/...``).
    gdf : GeoDataFrame
        Polygon(s) defining the catchment.
    start_year, end_year : int
        Inclusive temporal range.
    variable : str | ERA5Variable
        Registry key or an ``ERA5Variable``.
    cache_dir : str | Path | None
        If given, results are cached locally as parquet keyed by inputs hash.
    spatial_chunk : int | str | None
        Dask chunk size along latitude/longitude. Use ``"auto"`` (default)
        to tune from available CPU and RAM.
    time_chunk : int | str | None
        Dask chunk size along the native hourly time dimension. Smaller values
        reduce peak memory for large AOIs. Use ``"auto"`` (default) to tune
        from available CPU and RAM.
    temporal_batch_years : int | str | None
        Number of years per compute batch. ``"auto"`` (default) splits long
        spans into smaller exact batches to reduce Dask graph size.
    """
    import xarray as xr

    profile = _detect_system_profile()

    var = (
        variable
        if isinstance(variable, ERA5Variable)
        else get_era5_variable(variable)
    )

    # ---- cache lookup
    key = _cache_key(path, gdf, start_year, end_year, var.key)
    cached = _read_cache(cache_dir, key, prefix="era5_monthly")
    if cached is not None:
        return cached

    # ---- open lazily
    if (
        str(path).startswith("gs://")
        and importlib.util.find_spec("gcsfs") is None
    ):
        raise ImportError(
            "gcsfs is required to read Google Cloud Storage ERA5 Zarr stores. "
            "Install the fetch extra with: pip install \"hydroseason[fetch]\""
        )
    total_hours = max(1, (int(end_year) - int(start_year) + 1) * 366 * 24)
    resolved_time_chunk = _resolve_time_chunk(
        time_chunk,
        profile=profile,
        total_steps=total_hours,
    )
    ds = xr.open_zarr(
        path,
        chunks={"time": resolved_time_chunk},
        storage_options={"token": "anon"},
    )
    ds = ds.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))

    # Resolve variable name in the store
    var_name = var.era5_name
    if var_name not in ds.data_vars:
        # try common short alias
        if "tp" in ds.data_vars and var.key == "rainfall":
            var_name = "tp"
        elif "t2m" in ds.data_vars and var.key == "temperature":
            var_name = "t2m"
        else:
            raise KeyError(
                f"Variable '{var.era5_name}' not found; "
                f"available: {list(ds.data_vars)}"
            )
    ds = ds[[var_name]]

    # ---- spatial subset on bbox of polygons (CRS = EPSG:4326)
    gdf = gdf.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = gdf.total_bounds
    lon_vals = ds.longitude.values
    lat_vals = ds.latitude.values
    lon_step = _coord_step(lon_vals)
    lat_step = _coord_step(lat_vals)
    lon_pair = _wrap_lon_to_ds_range([minx, maxx], lon_vals)
    lon_sel = _bbox_indexer(
        lon_vals,
        lon_pair[0],
        lon_pair[1],
        step=lon_step,
        label="longitude",
    )
    lat_sel = _bbox_indexer(
        lat_vals,
        miny,
        maxy,
        step=lat_step,
        label="latitude",
    )
    grid_shape = (
        int(ds.isel(latitude=lat_sel).sizes["latitude"]),
        int(ds.isel(longitude=lon_sel).sizes["longitude"]),
    )
    resolved_spatial_chunk = _resolve_spatial_chunk(
        spatial_chunk,
        profile=profile,
        grid_shape=grid_shape,
    )
    ds_small = ds.isel(longitude=lon_sel, latitude=lat_sel).chunk(
        {
            "time": resolved_time_chunk,
            "latitude": resolved_spatial_chunk,
            "longitude": resolved_spatial_chunk,
        }
    )
    resolved_batch_years = _resolve_temporal_batch_years(
        temporal_batch_years,
        start_year=start_year,
        end_year=end_year,
        profile=profile,
        grid_shape=grid_shape,
    )

    # ---- rasterized polygon mask on the small grid
    mask = rasterize_to_xarray_grid(
        gdf,
        ds_small,
        lon_name="longitude",
        lat_name="latitude",
        lon_step=lon_step,
        lat_step=lat_step,
    )

    # ---- MASK, THEN COLLAPSE SPACE BEFORE RESAMPLE (correctness + memory)
    da = ds_small[var_name].where(mask)
    catchment_hourly = da.mean(("latitude", "longitude"), skipna=True)
    monthly_frames: list[pd.DataFrame] = []
    progress = _FetchProgressBar(
        int(end_year) - int(start_year) + 1,
        label="ERA5",
        enabled=show_progress,
    )
    try:
        for batch_start in range(
            start_year, end_year + 1, resolved_batch_years
        ):
            batch_end = min(end_year, batch_start + resolved_batch_years - 1)
            progress.set_stage(_year_stage_label(batch_start, batch_end))
            batch_hourly = catchment_hourly.sel(
                time=slice(f"{batch_start}-01-01", f"{batch_end}-12-31")
            )
            if var.aggregation == "sum":
                batch_series = batch_hourly.resample(time="MS").sum("time")
            elif var.aggregation == "mean":
                batch_series = batch_hourly.resample(time="MS").mean("time")
            else:
                raise ValueError(
                    f"Unsupported aggregation '{var.aggregation}'."
                )

            values = batch_series.compute()
            progress.advance(batch_end - batch_start + 1)

            batch_df = (
                values.to_pandas()
                .rename(var.out_column)
                .to_frame()
                .reset_index()
            )
            monthly_frames.append(batch_df)
    finally:
        progress.close()

    df = (
        pd.concat(monthly_frames, ignore_index=True)
        .sort_values("time")
        .reset_index(drop=True)
    )
    df["Date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["Year"] = df["time"].dt.year.astype(int)
    df["Month"] = df["time"].dt.month.astype(int)
    df.drop(columns=["time"], inplace=True)

    # unit conversion
    df[var.out_column] = (
        df[var.out_column] * var.unit_factor + var.unit_offset
    ).round(2)

    # zero-clip for accumulation variables only (avoid clipping temperatures!)
    if var.aggregation == "sum":
        df.loc[df[var.out_column] < 1, var.out_column] = 0.0

    out = df[["Date", "Year", "Month", var.out_column]]

    _write_cache(
        cache_dir,
        key,
        out,
        meta={
            "path": str(path),
            "start_year": start_year,
            "end_year": end_year,
            "variable": var.key,
            "unit": var.unit_label,
            "spatial_chunk": resolved_spatial_chunk,
            "time_chunk": resolved_time_chunk,
            "temporal_batch_years": resolved_batch_years,
            "chunk_strategy": {
                "spatial": (
                    "auto" if _is_auto_chunk(spatial_chunk) else "manual"
                ),
                "time": "auto" if _is_auto_chunk(time_chunk) else "manual",
                "temporal_batch_years": (
                    "auto"
                    if _is_auto_chunk(temporal_batch_years)
                    else "manual"
                ),
            },
            "system_profile": {
                "cpu_count": profile.cpu_count,
                "memory_gib": round(profile.memory_gib, 2),
            },
        },
        prefix="era5_monthly",
    )
    return out


def _coord_name(ds, candidates: tuple[str, ...], label: str) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(
        f"Could not locate {label} coordinate. Checked: {candidates}"
    )


def _silo_rain_var_name(ds) -> str:
    preferred = ("monthly_rain", "Rainfall_mm", "rain", "rainfall")
    for name in preferred:
        if name in ds.data_vars:
            return name
    if len(ds.data_vars) == 1:
        return list(ds.data_vars)[0]
    raise KeyError(
        "Could not infer SILO rainfall variable; "
        f"available: {list(ds.data_vars)}"
    )


def _silo_year_dataset_path(
    year: int,
    base_url: str,
    cache_dir: str | Path | None,
) -> tuple[Path, bool]:
    """Return a local NetCDF path for a SILO annual monthly-rain file.

    Returns ``(path, is_temporary)``. HTTP/S sources are downloaded because
    raw NetCDF-over-HTTPS support varies by xarray backend.
    """
    filename = f"{year}.monthly_rain.nc"
    source = str(base_url).rstrip("/")

    if source.startswith(("http://", "https://")):
        if cache_dir is not None:
            base = Path(cache_dir) / "silo_netcdf"
            base.mkdir(parents=True, exist_ok=True)
            target = base / filename
            if not target.exists():
                urllib.request.urlretrieve(f"{source}/{filename}", target)
            return target, False

        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".monthly_rain.nc"
        )
        tmp_path = Path(tmp.name)
        tmp.close()
        urllib.request.urlretrieve(f"{source}/{filename}", tmp_path)
        return tmp_path, True

    return Path(source) / filename, False


def get_monthly_silo_rainfall(
    gdf,
    start_year: int,
    end_year: int,
    *,
    base_url: str = SILO_MONTHLY_RAIN_BASE_URL,
    cache_dir: str | Path | None = None,
    spatial_chunk: int | str | None = "auto",
    show_progress: bool = True,
) -> pd.DataFrame:
    """Fetch SILO gridded monthly rainfall averaged over an AOI polygon.

    Downloads SILO annual monthly-rain NetCDF files hosted on AWS,
    masks each to the polygon, and returns the spatial mean per month.

    Parameters
    ----------
    gdf:
        A GeoDataFrame defining the area of interest (any CRS; reprojected to
        EPSG:4326 internally). Use :func:`load_vector` to load one from a file.
    start_year, end_year:
        Inclusive range of calendar years to fetch.
    base_url:
        Base URL of the SILO monthly-rain NetCDF store.
    cache_dir:
        Optional directory for caching the assembled monthly series as Parquet.
    spatial_chunk:
        Dask chunk size (grid cells) along each spatial dimension. Use
        ``"auto"`` (default) to tune from available CPU and RAM.
    show_progress:
        Show a dask progress bar during compute when available.

    Returns
    -------
    pandas.DataFrame
        Tidy monthly frame with columns ``Date``, ``Year``, ``Month`` and
        ``Rainfall_mm``, ready to pass to :func:`classify_rainfall`.
    """
    import xarray as xr

    key = _cache_key(base_url, gdf, start_year, end_year, "silo_monthly_rain")
    cached = _read_cache(cache_dir, key, prefix="silo_monthly")
    if cached is not None:
        return cached

    profile = _detect_system_profile()

    gdf = gdf.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = gdf.total_bounds

    monthly_frames: list[pd.DataFrame] = []
    years = range(int(start_year), int(end_year) + 1)
    progress = _FetchProgressBar(
        int(end_year) - int(start_year) + 1,
        label="SILO",
        enabled=show_progress,
    )
    try:
        for year in years:
            progress.set_stage(_year_stage_label(year, year))
            nc_path, is_temporary = _silo_year_dataset_path(
                year, base_url, cache_dir
            )
            ds = xr.open_dataset(nc_path)

            try:
                lon_name = _coord_name(
                    ds, ("longitude", "lon", "x"), "longitude"
                )
                lat_name = _coord_name(ds, ("latitude", "lat", "y"), "latitude")
                time_name = _coord_name(ds, ("time",), "time")
                var_name = _silo_rain_var_name(ds)

                lon_vals = ds[lon_name].values
                lat_vals = ds[lat_name].values
                lon_step = _coord_step(lon_vals)
                lat_step = _coord_step(lat_vals)
                lon_pair = _wrap_lon_to_ds_range([minx, maxx], lon_vals)
                lon_sel = _bbox_indexer(
                    lon_vals,
                    lon_pair[0],
                    lon_pair[1],
                    step=lon_step,
                    label=lon_name,
                )
                lat_sel = _bbox_indexer(
                    lat_vals,
                    miny,
                    maxy,
                    step=lat_step,
                    label=lat_name,
                )
                grid_shape = (
                    int(ds.isel({lat_name: lat_sel}).sizes[lat_name]),
                    int(ds.isel({lon_name: lon_sel}).sizes[lon_name]),
                )
                resolved_spatial_chunk = _resolve_spatial_chunk(
                    spatial_chunk,
                    profile=profile,
                    grid_shape=grid_shape,
                )
                ds_small = ds.isel(
                    {lon_name: lon_sel, lat_name: lat_sel}
                ).chunk(
                    {
                        time_name: 12,
                        lat_name: resolved_spatial_chunk,
                        lon_name: resolved_spatial_chunk,
                    }
                )

                mask = rasterize_to_xarray_grid(
                    gdf,
                    ds_small,
                    lon_name=lon_name,
                    lat_name=lat_name,
                    lon_step=lon_step,
                    lat_step=lat_step,
                )
                da = ds_small[var_name].where(mask)
                catchment_series = da.mean((lat_name, lon_name), skipna=True)
                values = catchment_series.compute()

                df = (
                    values.to_pandas()
                    .rename("Rainfall_mm")
                    .to_frame()
                    .reset_index()
                )
                df["Date"] = pd.to_datetime(df[time_name]).dt.strftime(
                    "%Y-%m-%d"
                )
                df["Year"] = pd.to_datetime(df[time_name]).dt.year.astype(int)
                df["Month"] = pd.to_datetime(df[time_name]).dt.month.astype(int)
                df = df[["Date", "Year", "Month", "Rainfall_mm"]]
                monthly_frames.append(df)
                progress.advance()
            finally:
                ds.close()
                if is_temporary:
                    nc_path.unlink(missing_ok=True)
    finally:
        progress.close()

    out = (
        pd.concat(monthly_frames, ignore_index=True)
        .sort_values("Date")
        .reset_index(drop=True)
    )

    _write_cache(
        cache_dir,
        key,
        out,
        meta={
            "base_url": base_url,
            "start_year": int(start_year),
            "end_year": int(end_year),
            "variable": "monthly_rain",
            "unit": "mm",
            "spatial_chunk": (
                "auto" if _is_auto_chunk(spatial_chunk) else int(spatial_chunk)
            ),
            "system_profile": {
                "cpu_count": profile.cpu_count,
                "memory_gib": round(profile.memory_gib, 2),
            },
        },
        prefix="silo_monthly",
    )
    return out
