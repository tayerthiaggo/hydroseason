"""Geospatial AOI and raster mask loaders.

Raster support is adapted from WaterMask-TSFill commit
90983c1559e7c08951096bbf196c0daedead6b4f.  All geospatial imports
(geopandas, rioxarray, xarray, pystac_client, odc.stac, rasterio, affine,
pyproj) stay inside function bodies so importing this module never requires
those packages -- only calling a function that needs one does.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Collection, Iterator, Literal

import numpy as np
import pandas as pd

from hydroseason._io_extent import complete_monthly_axis


def _configure_cog_read_env() -> None:
    """Set GDAL/rasterio env for fast, concurrent, unsigned S3 COG reads.

    WOfS extraction is latency-bound: a single AOI-year is dozens to hundreds
    of small COG GETs against DEA's public S3, and the wall-clock cost is
    dominated by per-request round-trips, not pixel volume. These settings cut
    that overhead without changing any result:

    * ``AWS_NO_SIGN_REQUEST=YES`` -- DEA's ``dea-public-data`` bucket rejects
      signed reads; without this every lazy dask read fails with
      ``CPLE_AWSInvalidCredentialsError``.
    * ``GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`` -- stop GDAL from listing the
      whole S3 "directory" (a wasteful LIST) every time it opens one COG.
    * ``GDAL_HTTP_MULTIPLEX=YES`` + ``GDAL_HTTP_VERSION=2`` -- reuse one HTTP/2
      connection for many concurrent range requests instead of one per read.
    * ``VSI_CACHE=TRUE`` / ``VSI_CACHE_SIZE`` -- cache COG headers/blocks in
      memory so repeated reads of the same file (e.g. per-month slices of the
      same annual batch) don't re-fetch.
    * ``GDAL_HTTP_MAX_RETRY`` / ``GDAL_HTTP_RETRY_DELAY`` -- ride out transient
      S3 5xx/throttle blips instead of failing the whole load.
    * ``GDAL_HTTP_MAX_TOTAL_CONNECTIONS`` -- raise GDAL's ceiling on
      *simultaneously open* HTTP connections so that widening dask's read-worker
      pool actually yields that many concurrent S3 range requests, rather than
      being throttled back to GDAL's small internal default. This is the lever
      that lets ``read_workers`` translate into real read parallelism for this
      latency-bound workload. NOTE: this option only exists on GDAL >= 3.11; on
      older GDAL it is silently ignored (a no-op, never an error), so the
      connection cap there stays at GDAL's compiled-in default and read
      concurrency stays bounded by it -- upgrading GDAL is what unlocks this.

    Uses ``setdefault`` throughout so a caller who has deliberately set any of
    these in their own environment is never overridden.
    """
    defaults = {
        "AWS_NO_SIGN_REQUEST": "YES",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MULTIPLEX": "YES",
        "GDAL_HTTP_VERSION": "2",
        "VSI_CACHE": "TRUE",
        "VSI_CACHE_SIZE": "67108864",  # 64 MB
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
        "GDAL_HTTP_MAX_RETRY": "5",
        "GDAL_HTTP_RETRY_DELAY": "1",
        # GDAL >= 3.11 only; silently ignored on older GDAL (e.g. 3.10). Sized
        # to comfortably exceed the default read_workers pool so worker count,
        # not GDAL, governs concurrency once GDAL is new enough.
        "GDAL_HTTP_MAX_TOTAL_CONNECTIONS": "64",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)

MaskEncoding = Literal["canonical", "binary", "wofs"]


class AOIRasterizationError(RuntimeError):
    """AOI clipping or rasterization could not be applied safely."""


class GeoreferencingError(ValueError):
    """Raster lacks usable CRS or affine georeferencing."""


class IrregularGridError(GeoreferencingError):
    """Raster x/y coordinates cannot define an affine transform."""


def load_aoi(aoi, *, to_crs: str | int | None = None):
    """Load a non-empty GeoDataFrame from vector path or GeoDataFrame."""
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_aoi requires the raster extra (geopandas).") from exc

    if isinstance(aoi, gpd.GeoDataFrame):
        result = aoi.copy()
    elif isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        if not path.exists():
            raise FileNotFoundError(f"AOI file not found: {path}")
        result = gpd.read_file(path)
    else:
        raise TypeError("aoi must be a vector path or geopandas.GeoDataFrame.")
    if result.empty:
        raise ValueError("AOI GeoDataFrame is empty.")
    result = result[~result.geometry.isna() & ~result.geometry.is_empty].copy()
    if result.empty:
        raise ValueError("AOI has no valid non-empty geometries.")
    if not result.geometry.is_valid.all():
        raise ValueError(
            "AOI contains geometrically invalid (e.g. self-intersecting) "
            "geometry; fix or repair the AOI before use."
        )
    if to_crs is not None:
        result = result.to_crs(_crs_value(to_crs))
    return result


def load_monthly_masks(
    input_dir: str | os.PathLike[str],
    start_date: str,
    end_date: str,
    *,
    aoi=None,
    encoding: MaskEncoding | None = None,
    classifier: Callable | None = None,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_chunk: int = 24,
    majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Load AOI-clipped TIFF masks as lazy canonical time/y/x data.

    Explicit ``encoding`` prevents ambiguous uint8 masks from being mistaken
    for raw WOfS flags. Canonical values: dry 0, water 1, invalid -1, outside -2.
    """
    if aoi is None:
        raise ValueError("AOI is required for raster mask loading.")
    _validate_classifier(encoding, classifier)
    try:
        import rioxarray as rxr
        import xarray as xr
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_monthly_masks requires the raster extra.") from exc

    files = sorted(Path(input_dir).glob("water_*.tif"))
    if not files:
        raise FileNotFoundError(f"No water_*.tif files found in {input_dir}")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    grouped: dict[pd.Timestamp, list] = {}
    for path in files:
        timestamp = _parse_date_from_name(path)
        if start <= timestamp <= end:
            arr = rxr.open_rasterio(path, chunks={"x": chunk_x, "y": chunk_y}).squeeze(drop=True)
            grouped.setdefault(timestamp.to_period("M").to_timestamp(), []).append(_classify(arr, encoding, classifier))
    if not grouped:
        raise FileNotFoundError(f"No mask files fall within {start_date} to {end_date}.")

    aoi_gdf = load_aoi(aoi)
    masks, dates, reference = [], [], None
    for month, observations in sorted(grouped.items()):
        mask = observations[0] if len(observations) == 1 else _combine_observations(xr.concat(observations, dim="time"), majority)
        mask = _clip_to_aoi(mask, aoi_gdf)
        if reference is not None:
            _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
        reference = mask if reference is None else reference
        masks.append(mask)
        dates.append(month)
    return complete_monthly_axis(
        xr.concat(masks, dim="time").assign_coords(time=("time", dates)), start_date, end_date,
        duplicate_month_policy=duplicate_month_policy,
    ).chunk({"time": min(time_chunk, len(dates)), "x": chunk_x, "y": chunk_y})


def load_monthly_masks_zarr(
    zarr_path: str | os.PathLike[str], start_date: str, end_date: str, *, chunk_x: int = 512, chunk_y: int = 512,
    time_chunk: int = 24, duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Open an already-canonical, already-AOI-clipped Zarr mask cube lazily."""
    try:
        import xarray as xr
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_monthly_masks_zarr requires the raster extra.") from exc
    dataset = xr.open_zarr(zarr_path, chunks={"x": chunk_x, "y": chunk_y}, mask_and_scale=False)
    if "water_mask" not in dataset:
        raise ValueError("Zarr store must contain a 'water_mask' variable.")
    masks = dataset["water_mask"].sel(time=slice(pd.Timestamp(start_date), pd.Timestamp(end_date)))
    masks = complete_monthly_axis(masks, start_date, end_date, duplicate_month_policy=duplicate_month_policy)
    return masks.chunk({"time": min(time_chunk, masks.sizes["time"]), "x": chunk_x, "y": chunk_y})


def _query_wofs_items(stac_url, collection, aoi, start_date, end_date):
    """Query STAC for WOfS items in an AOI and date range.

    Returns a tuple of (items, aoi_gdf) where items is a list of STAC items
    and aoi_gdf is the loaded AOI GeoDataFrame.
    """
    import pystac_client

    aoi_gdf = load_aoi(aoi)
    try:
        aoi_4326 = aoi_gdf.to_crs("EPSG:4326")
        client = pystac_client.Client.open(stac_url)
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        items = _collect_stac_items(
            client,
            collections=[collection],
            datetime=f"{start:%Y-%m-%d}/{end:%Y-%m-%d}",
            bbox=list(aoi_4326.total_bounds),
        )
    except Exception as exc:
        raise AOIRasterizationError("STAC AOI query failed; refusing to load an unclipped raster.") from exc
    if not items:
        raise ValueError("No STAC items found for requested AOI and date range.")
    return items, aoi_gdf


def _load_wofs_items(
    items,
    aoi_gdf,
    start_date,
    end_date,
    *,
    crs=3577,
    resolution=None,
    geobox=None,
    chunk_x=512,
    chunk_y=512,
    time_chunk=24,
    majority=True,
    duplicate_month_policy="raise",
    groupby="solar_day",
    resampling=None,
):
    """Load WOfS items, classify, compose monthly, and clip to AOI.

    Items are processed in annual batches with monthly composition,
    returning a lazy xarray.DataArray.

    ``groupby`` controls how ``odc.stac.stac_load`` places items onto pixel
    planes before this function classifies and monthly-composites them:

    * ``"solar_day"`` (default) merges items captured on the same solar day
      into one plane, nodata-aware (a real observation wins over nodata),
      *before* classification. For WOfS this both cuts wall-clock time (fewer,
      already-mosaicked time-slices to read and reduce -- the tile-edge
      duplicate scenes that inflate a year's slice count collapse) and is
      arguably more faithful to the data: same-day overlapping scenes are one
      acquisition split across tile boundaries, so a pixel observed clear in
      one tile-edge scene and nodata in its same-day neighbour is correctly
      read as observed, not as two competing votes.
    * ``"time"`` keeps every item with a distinct timestamp as its own plane
      (the historical behaviour). Same-day tile-edge scenes then each cast a
      separate water/dry/invalid vote in ``_combine_observations``.

    ``resampling`` is passed through to ``odc.stac.stac_load`` verbatim when
    not ``None`` (omitted entirely otherwise, matching ``odc.stac``'s own
    default). Callers with an explicit ``resolution`` (the legacy AOI+CRS
    path) traditionally want ``resampling="mode"`` for a categorical mask;
    callers with a pre-derived ``geobox`` (the cache/tiling path) fix
    CRS/resolution via the geobox and must still pass ``resampling="mode"``
    explicitly through this parameter to get the same categorical-safe
    behaviour -- unlike ``resolution``, ``geobox`` alone does not imply it.

    The per-month selection and majority vote below are agnostic to how many
    slices land in a month, so the only thing ``groupby`` changes is the slice
    granularity feeding the vote (and thus, at same-day overlap boundaries,
    the vote's outcome). Solar-time adjustment can nudge a near-midnight scene
    across a UTC date boundary; such a scene still selects into whichever month
    its solar-day timestamp falls in, and any month loaded that is outside the
    requested year_groups is simply not selected.
    """
    import odc.stac
    import xarray as xr

    import hydroseason.io as _io

    groups: dict[pd.Timestamp, list] = {}
    for item in items:
        date = pd.Timestamp(
            item.properties.get("datetime")
            or item.properties.get("start_datetime")
        )
        if date.tzinfo is not None:
            date = date.tz_convert(None)
        groups.setdefault(date.to_period("M").to_timestamp(), []).append(item)

    annual_groups: dict[int, list[tuple[pd.Timestamp, list]]] = {}
    for month, month_items in sorted(groups.items()):
        annual_groups.setdefault(month.year, []).append((month, month_items))

    target = aoi_gdf.to_crs(_crs_value(crs)) if crs is not None else aoi_gdf
    masks, dates, reference = [], [], None
    for year, year_groups in sorted(annual_groups.items()):
        try:
            year_items = [item for _month, month_items in year_groups for item in month_items]
            spatial = {"geobox": geobox} if geobox is not None else {
                "geopolygon": target.geometry,
                **({"crs": _crs_value(crs)} if crs is not None else {}),
                **({"resolution": resolution} if resolution is not None else {}),
            }
            load_kwargs = {
                "bands": ["water"],
                "chunks": {"x": chunk_x, "y": chunk_y},
                "groupby": groupby,
                **({"resampling": resampling} if resampling is not None else {}),
                **spatial,
            }
            ds = odc.stac.stac_load(year_items, **load_kwargs)
            classified = _classify(ds["water"], "wofs", None)
            loaded_months = pd.DatetimeIndex(classified["time"].values).to_period("M")
        except AOIRasterizationError:
            raise
        except Exception as exc:
            raise AOIRasterizationError(f"STAC load failed for batch year {year}.") from exc

        # Compose each month's observations into a single canonical composite,
        # but do NOT clip per month: the AOI clip is spatial-only and the grid
        # is time-invariant across the whole cube, so clipping every month
        # rasterises the identical AOI geometry 12x/year (and again inside
        # mark_in_aoi_nodata_as_invalid -> 24x). Instead collect the unclipped
        # monthly composites and clip the whole stacked cube exactly once below,
        # after the year loop -- one rasterisation for the entire request.
        for month, _month_items in year_groups:
            try:
                indices = np.flatnonzero(loaded_months == month.to_period("M"))
                if not len(indices):
                    raise ValueError(f"loaded STAC batch has no observations for {month:%Y-%m}")
                observations = classified.isel(time=indices)
                mask = _combine_observations(observations, majority)
            except AOIRasterizationError:
                raise
            except Exception as exc:
                raise AOIRasterizationError(
                    f"AOI composite failed; refusing to process STAC month {month:%Y-%m}."
                ) from exc
            if reference is not None:
                _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
            reference = mask if reference is None else reference
            masks.append(mask)
            dates.append(month)

    try:
        stacked = xr.concat(masks, dim="time").assign_coords(time=("time", dates))
        clipped_cube = _io._clip_to_aoi(stacked, target)
    except AOIRasterizationError:
        raise
    except Exception as exc:
        raise AOIRasterizationError(
            "AOI clip failed; refusing to process an unclipped raster."
        ) from exc

    completed = complete_monthly_axis(
        clipped_cube,
        start_date,
        end_date,
        duplicate_month_policy=duplicate_month_policy,
    )
    return completed.chunk({
        "time": min(time_chunk, completed.sizes["time"]),
        "x": chunk_x,
        "y": chunk_y,
    })


def load_wofs_from_stac(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *, crs: int | str | None = 3577,
    chunk_x: int = 512, chunk_y: int = 512, time_chunk: int = 24, majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise", resolution: float | None = None,
    groupby: str = "solar_day",
):
    """Load WOfS observations in annual batches, compose monthly, and clip to the AOI.

    A calendar year is sent to ``odc.stac.stac_load`` at once.  The returned
    lazy cube is then split into monthly composites, avoiding the substantial
    graph/setup overhead of one loader call per month while retaining the same
    monthly result. ``groupby`` (default ``"solar_day"``) controls same-day
    scene mosaicking before compositing -- see :func:`_load_wofs_items`.
    """
    if aoi is None:
        raise ValueError("AOI is required for WOfS/STAC loading.")
    try:
        import odc.stac
        import pystac_client
        import rioxarray  # noqa: F401  (registers the .rio accessor used by _clip_to_aoi)
        import xarray as xr
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_wofs_from_stac requires the stac extra.") from exc
    # Tune GDAL/rasterio for fast concurrent unsigned S3 COG reads (this also
    # sets AWS_NO_SIGN_REQUEST, without which every lazy dask read of the
    # returned cube fails with CPLE_AWSInvalidCredentialsError on dea-public-data).
    _configure_cog_read_env()

    try:
        items, aoi_gdf = _query_wofs_items(stac_url, collection, aoi, start_date, end_date)
    except Exception as exc:
        raise AOIRasterizationError("STAC AOI query failed; refusing to load an unclipped raster.") from exc

    return _load_wofs_items(
        items,
        aoi_gdf,
        start_date,
        end_date,
        crs=crs,
        resolution=resolution,
        geobox=None,
        chunk_x=chunk_x,
        chunk_y=chunk_y,
        time_chunk=time_chunk,
        majority=majority,
        duplicate_month_policy=duplicate_month_policy,
        groupby=groupby,
        resampling=("mode" if resolution is not None else None),
    )


def _item_year(item) -> int:
    """The calendar year of one STAC item, parsed the same way as :func:`_load_wofs_items`."""
    date = pd.Timestamp(
        item.properties.get("datetime") or item.properties.get("start_datetime")
    )
    if date.tzinfo is not None:
        date = date.tz_convert(None)
    return int(date.year)


def build_wofs_year_graph(
    items,
    aoi_gdf,
    start_date: str,
    end_date: str,
    *,
    geobox,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_chunk: int = 12,
    majority: bool = True,
    groupby: str = "solar_day",
):
    """Build one shared lazy WOfS cube for a single calendar year onto a fixed grid.

    A thin validating wrapper around :func:`_load_wofs_items`, used only by
    the geobox-driven cache acquisition path (never the legacy AOI+resolution
    path, which calls :func:`_load_wofs_items` directly via
    :func:`load_wofs_from_stac`). Two things distinguish this path:

    * A parent ``geobox`` is required (raises ``ValueError`` if missing) --
      it already fixes the output CRS/resolution/alignment, so this function
      delegates to :func:`_load_wofs_items` with ``resolution=None``
      (passing both would be redundant/conflicting).
    * Because ``resolution=None`` here, :func:`_load_wofs_items` would not on
      its own apply ``resampling="mode"`` (that historical behaviour is keyed
      off its ``resolution`` argument, which this path deliberately leaves
      unset). This function passes ``resampling="mode"`` explicitly through
      :func:`_load_wofs_items`'s ``resampling`` keyword so geobox-based loads
      keep the same categorical-safe mode resampling as the legacy path.

    Every supplied item's timestamp must fall within the requested calendar
    year (validated against ``start_date``/``end_date`` -- for this
    function's only caller, :func:`hydroseason._io_wofs_acquire.acquire_wofs_cache`,
    that range is always one calendar year, per
    :func:`hydroseason._io_wofs_acquire.partition_items_by_year`); a
    mismatched item raises ``ValueError`` naming it, so a caller's partition
    bug is caught immediately rather than silently loading the wrong year's
    pixels onto this year's grid.
    """
    if geobox is None:
        raise ValueError("build_wofs_year_graph requires a parent geobox.")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start.year != end.year:
        raise ValueError(
            f"build_wofs_year_graph requires a single-calendar-year range, "
            f"got {start_date} to {end_date}."
        )
    year = start.year
    for item in items:
        item_year = _item_year(item)
        if item_year != year:
            raise ValueError(
                f"item {getattr(item, 'id', item)!r} has timestamp year "
                f"{item_year}, expected {year} (requested range {start_date} "
                f"to {end_date})."
            )

    return _load_wofs_items(
        items,
        aoi_gdf,
        start_date,
        end_date,
        crs=None,
        resolution=None,
        geobox=geobox,
        chunk_x=chunk_x,
        chunk_y=chunk_y,
        time_chunk=time_chunk,
        majority=majority,
        duplicate_month_policy="raise",
        groupby=groupby,
        resampling="mode",
    )


def _tile_slices(shape: tuple[int, int], tile_pixels: int) -> Iterator[tuple[str, slice, slice]]:
    """Yield ``(tile_id, y_slice, x_slice)`` tuples covering ``shape`` exactly once.

    Tiles are laid out on a fixed pixel grid starting at the origin, in
    row-major order, with no overlap. The final row/column of tiles may be
    smaller than ``tile_pixels`` when the shape does not divide evenly.
    """
    if tile_pixels < 1:
        raise ValueError("tile_pixels must be at least 1.")
    height, width = shape
    for row, y0 in enumerate(range(0, height, tile_pixels)):
        for column, x0 in enumerate(range(0, width, tile_pixels)):
            yield (
                f"r{row:04d}_c{column:04d}",
                slice(y0, min(y0 + tile_pixels, height)),
                slice(x0, min(x0 + tile_pixels, width)),
            )


def _output_geobox_for_aoi(items, target, *, crs, resolution):
    """Derive one parent GeoBox spanning the whole AOI from parsed STAC items."""
    import odc.stac

    parsed = list(odc.stac.parse_items(items))
    geobox = odc.stac.output_geobox(
        parsed,
        crs=_crs_value(crs),
        resolution=resolution,
        geopolygon=target.geometry,
    )
    if geobox is None:
        raise AOIRasterizationError("Cannot derive an output GeoBox for the AOI.")
    return geobox


def _tile_intersects_aoi(tile_geobox, target):
    """Cheap bounding-box intersection test to skip tiles with no AOI overlap."""
    from shapely.geometry import box

    bounds = tile_geobox.extent.boundingbox
    tile_polygon = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
    return bool(target.to_crs(tile_geobox.crs).geometry.intersects(tile_polygon).any())


def tile_intersects_wet_aoi(tile_geobox, wet_aoi) -> bool:
    """Module-local indirection to ``hydroseason._wet_aoi.tile_intersects_wet_aoi``.

    ``_wet_aoi`` imports from this module at module scope (for
    ``_preserve_georef``), so this module cannot import ``_wet_aoi`` at
    module scope without a cycle; the import is deferred to call time here
    instead. Kept as a real module-level name (rather than inlining the
    import at the call site in :func:`iter_wofs_tiles_from_stac`) so it can
    be monkeypatched the same way as :func:`_tile_intersects_aoi`.
    """
    from hydroseason._wet_aoi import tile_intersects_wet_aoi as _impl

    return _impl(tile_geobox, wet_aoi)


def iter_wofs_tiles_from_stac(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *, crs: int | str | None = 3577,
    resolution: float, tile_pixels: int, skip_tile_ids: Collection[str] = (),
    chunk_x: int = 512, chunk_y: int = 512, time_chunk: int = 24, majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
    wet_aoi=None,
    groupby: str = "solar_day",
) -> Iterator[tuple[str, "object"]]:
    """Query STAC once, then load WOfS one native-resolution Albers tile at a time.

    A single parent :class:`odc.geo.geobox.GeoBox` is derived for the whole
    AOI, then split into a fixed pixel grid via :func:`_tile_slices`. Each
    tile is loaded independently with :func:`_load_wofs_items`, reusing the
    same STAC item list so the catalog is queried exactly once regardless of
    tile count. Tiles outside the AOI bounding box, or whose id is present in
    ``skip_tile_ids`` (e.g. already cached from a previous run), are skipped
    without loading.

    ``wet_aoi``, if given, is an already-computed wet-AOI GeoDataFrame (see
    :func:`hydroseason._wet_aoi.compute_wet_aoi`) used as a SECOND, independent
    tile-skip gate: a tile is loaded only if it passes both the user-AOI bbox
    test and :func:`hydroseason._wet_aoi.tile_intersects_wet_aoi`. This only
    decides which tiles get loaded at all -- it never changes what the
    per-tile AOI clip inside :func:`_load_wofs_items` clips to (still the
    user's original ``target`` AOI), so extent denominators (``n_aoi``) for
    any tile that does load are unaffected by wet-AOI pruning.
    """
    if aoi is None:
        raise ValueError("AOI is required for WOfS/STAC loading.")
    if resolution is None:
        raise ValueError("resolution is required for tiled WOfS/STAC loading.")
    try:
        import odc.stac  # noqa: F401
        import pystac_client  # noqa: F401
        import rioxarray  # noqa: F401  (registers the .rio accessor used by _clip_to_aoi)
        import xarray as xr  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError("iter_wofs_tiles_from_stac requires the stac extra.") from exc
    # Tune GDAL/rasterio for fast concurrent unsigned S3 COG reads (this also
    # sets AWS_NO_SIGN_REQUEST, without which every lazy dask read of the
    # returned cube fails with CPLE_AWSInvalidCredentialsError on dea-public-data).
    _configure_cog_read_env()

    try:
        items, aoi_gdf = _query_wofs_items(stac_url, collection, aoi, start_date, end_date)
    except Exception as exc:
        raise AOIRasterizationError("STAC AOI query failed; refusing to load an unclipped raster.") from exc

    target = aoi_gdf.to_crs(_crs_value(crs)) if crs is not None else aoi_gdf
    parent_geobox = _output_geobox_for_aoi(items, target, crs=crs, resolution=resolution)

    _profile = os.environ.get("HYDROSEASON_PROFILE", "").strip() not in ("", "0", "false", "False")
    n_total = n_cached = n_outside = n_pruned = n_loaded = 0

    try:
        for tile_id, ys, xs in _tile_slices(parent_geobox.shape, tile_pixels):
            n_total += 1
            if tile_id in skip_tile_ids:
                n_cached += 1
                continue
            tile_geobox = parent_geobox[ys, xs]
            if not _tile_intersects_aoi(tile_geobox, target):
                n_outside += 1
                continue
            # Wet-AOI pruning: skip tiles the full-TS water union never touches.
            # This decides which tiles load; the user-AOI clip below is unchanged,
            # so extent denominators (n_aoi) stay measured against the user AOI.
            if not tile_intersects_wet_aoi(tile_geobox, wet_aoi):
                n_pruned += 1
                continue
            n_loaded += 1
            mask = _load_wofs_items(
                items,
                aoi_gdf,
                start_date,
                end_date,
                crs=crs,
                resolution=resolution,
                geobox=tile_geobox,
                chunk_x=chunk_x,
                chunk_y=chunk_y,
                time_chunk=time_chunk,
                majority=majority,
                duplicate_month_policy=duplicate_month_policy,
                groupby=groupby,
                resampling=("mode" if resolution is not None else None),
            )
            yield tile_id, mask
    finally:
        if _profile:
            import sys

            print(
                f"  [profile] tile grid: {n_total} total = {n_loaded} loaded + "
                f"{n_pruned} pruned (wet-AOI) + {n_outside} outside-AOI + {n_cached} cached",
                file=sys.stderr, flush=True,
            )


def _collect_stac_items(client, *, max_attempts: int = 4, **search_kwargs):
    delay = 2.0
    for attempt in range(1, max_attempts + 1):
        try:
            return list(client.search(**search_kwargs).items())
        except Exception as exc:
            if attempt == max_attempts or not _is_transient_stac_error(exc):
                raise
            time.sleep(delay)
            delay *= 2.0
    raise RuntimeError("unreachable")


def _is_transient_stac_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    if status_code in {500, 502, 503, 504}:
        return True
    text = str(exc).lower()
    return any(token in text for token in ("500", "502", "503", "504", "gateway", "timeout", "temporarily unavailable"))


def _validate_classifier(encoding, classifier):
    if classifier is not None and not callable(classifier):
        raise TypeError("classifier must be callable.")
    if classifier is None and encoding not in {"canonical", "binary", "wofs"}:
        raise ValueError("Specify encoding='canonical', 'binary', or 'wofs', or provide classifier=callable.")
    if classifier is not None and encoding is not None:
        raise ValueError("Pass either encoding or classifier, not both.")


def _classify(arr, encoding, classifier):
    import xarray as xr

    if classifier is not None:
        result = classifier(arr)
        if not hasattr(result, "dims"):
            raise TypeError("classifier must return an xarray.DataArray.")
        in_domain = result.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, result, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "canonical":
        in_domain = arr.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, arr, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "binary":
        return _preserve_georef(xr.where(arr == 1, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1))).astype(np.int8), arr)
    raw = arr.fillna(1).astype(np.uint16)
    invalid = ((raw & np.uint16(1)) != 0) | arr.isnull()
    return _preserve_georef(xr.where(invalid, np.int8(-1), xr.where(arr == 128, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1)))).astype(np.int8), arr)


def _preserve_georef(result, source):
    """Restore rioxarray metadata dropped by xarray classification operations."""
    try:
        result = result.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = source.rio.crs
        if crs is not None:
            result = result.rio.write_crs(crs)
        return result.rio.write_transform(source.rio.transform())
    except Exception:
        return result


def _combine_observations(series, majority):
    water, dry, invalid = (series == 1).sum("time"), (series == 0).sum("time"), (series == -1).sum("time")
    water_wins = (water > 0) & ((water > dry) if majority else True)
    import xarray as xr

    combined = xr.where(water_wins, np.int8(1), xr.where(dry > 0, np.int8(0), xr.where(invalid > 0, np.int8(-1), np.int8(-2)))).astype(np.int8)
    return _preserve_georef(combined, series)


def _clip_to_aoi(mask, aoi_gdf):
    outside_value = np.int8(-2)
    try:
        mask = mask.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = _resolve_raster_crs(mask)
        if crs is None:
            raise GeoreferencingError("raster is missing CRS")
        # Canonical values are already int8, so an unset nodata makes
        # rio.clip's outside-AOI fill land on NaN, which casts straight to
        # 0 (dry) instead of a real sentinel. Write nodata=-2 first so
        # clip's fill value is representable and outside pixels survive as
        # outside (-2), not dry.
        mask = mask.rio.write_nodata(outside_value)
        clipped = mask.rio.clip(aoi_gdf.to_crs(crs).geometry, drop=False, all_touched=True)
    except Exception as exc:
        raise AOIRasterizationError("AOI clip failed; refusing to process an unclipped raster.") from exc
    clipped = clipped.fillna(outside_value).astype(np.int8)
    return mark_in_aoi_nodata_as_invalid(clipped, aoi_gdf)


def mark_in_aoi_nodata_as_invalid(mask, aoi, *, outside_value: int = -2, invalid_value: int = -1):
    aoi_gdf = load_aoi(aoi)
    crs = _resolve_raster_crs(mask)
    if crs is None:
        raise AOIRasterizationError("AOI masking failed: raster is missing CRS.")
    try:
        inside = _inside_aoi_mask_like(mask, aoi_gdf.to_crs(crs))
    except Exception as exc:
        if isinstance(exc, AOIRasterizationError):
            raise
        raise AOIRasterizationError("AOI masking failed; refusing unclipped raster.") from exc
    return mask.where(~((mask == outside_value) & inside), np.int8(invalid_value)).astype(np.int8)


def _inside_aoi_mask_like(template, aoi_gdf):
    try:
        import xarray as xr
        from rasterio.features import geometry_mask

        transform = _resolve_raster_transform(template)
        inside = geometry_mask(list(aoi_gdf.geometry), out_shape=(template.sizes["y"], template.sizes["x"]), transform=transform, invert=True, all_touched=True)
        return xr.DataArray(inside, dims=("y", "x"), coords={"y": template.y, "x": template.x})
    except Exception as exc:
        raise AOIRasterizationError("AOI rasterization failed; refusing unclipped raster.") from exc


def _resolve_raster_crs(da):
    try:
        return da.rio.crs
    except Exception:
        return None


def _resolve_raster_transform(da):
    try:
        transform = da.rio.transform()
    except Exception:
        transform = None
    return _spatial_transform_from_xy(da) if transform is None or _is_identity_transform(transform) else transform


def _spatial_transform_from_xy(da):
    from affine import Affine

    x, y = np.asarray(da.x.values, dtype=float), np.asarray(da.y.values, dtype=float)
    if len(x) < 2 or len(y) < 2:
        raise GeoreferencingError("x/y axes need at least two coordinates.")
    dx, dy = np.diff(x), np.diff(y)
    if not np.allclose(dx, dx[0]) or not np.allclose(dy, dy[0]):
        raise IrregularGridError("x/y coordinate spacing is irregular.")
    return Affine(dx[0], 0, x[0] - dx[0] / 2, 0, dy[0], y[0] - dy[0] / 2)


def _is_identity_transform(transform):
    from affine import Affine

    return tuple(transform)[:6] == tuple(Affine.identity())[:6]


def _assert_compatible_georef(reference, other, *, context):
    try:
        same = _resolve_raster_crs(reference) == _resolve_raster_crs(other) and _resolve_raster_transform(reference) == _resolve_raster_transform(other) and reference.sizes["x"] == other.sizes["x"] and reference.sizes["y"] == other.sizes["y"]
    except Exception as exc:
        raise GeoreferencingError(f"{context}: cannot validate georeferencing.") from exc
    if not same:
        raise GeoreferencingError(f"{context}: raster georeferencing mismatch.")


def _parse_date_from_name(path: Path) -> pd.Timestamp:
    parts = path.stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"Unexpected filename format: {path.name}")
    return pd.Timestamp(f"{parts[-3]}-{parts[-2]}-{parts[-1]}")


def _crs_value(crs):
    return f"EPSG:{crs}" if isinstance(crs, int) else crs


__all__ = [
    "load_aoi", "load_monthly_masks", "load_monthly_masks_zarr", "load_wofs_from_stac",
    "mark_in_aoi_nodata_as_invalid", "AOIRasterizationError", "GeoreferencingError", "IrregularGridError",
]
