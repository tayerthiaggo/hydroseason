"""Bounded, resumable STAC-to-monthly-extent loading."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from hydroseason.hydro_year import monthly_water_extent


def _profile_enabled() -> bool:
    """Read the profiling flag at call time, not import time.

    Callers (e.g. the extract script's ``--profile``) may set the env var
    after this module is imported, so it must be re-read per use rather than
    frozen at module load.
    """
    return os.environ.get("HYDROSEASON_PROFILE", "").strip() not in ("", "0", "false", "False")


@contextmanager
def _phase(label: str):
    """Print wall-clock time for a named phase when HYDROSEASON_PROFILE is set.

    Zero overhead (a bare yield) when profiling is off, so normal runs are
    unaffected. Timings go to stderr so they never pollute CSV/stdout capture.
    """
    if not _profile_enabled():
        yield
        return
    import sys

    t0 = time.monotonic()
    try:
        yield
    finally:
        print(f"  [profile] {label}: {time.monotonic() - t0:.1f}s", file=sys.stderr, flush=True)


@contextmanager
def _read_concurrency(read_workers: int | None):
    """Widen dask's threaded-scheduler worker count for the enclosed reads.

    Used around the precompute whole-cube pass, where the lazy STAC/COG graph
    is materialised by ``compute_wet_aoi``'s ``.any("time")`` reduction. The
    per-year reductions get the same treatment inside
    :func:`hydroseason.hydro_year.monthly_water_extent` via its own
    ``read_workers`` argument; this context covers the one read site that does
    not route through that function. See ``monthly_water_extent`` for why more
    workers than ``cpu_count`` help this latency-bound S3 workload. A ``None``
    or non-positive ``read_workers`` is a no-op; the override is scoped to the
    ``with`` block and restored on exit.
    """
    if read_workers is None or read_workers <= 0:
        yield
        return
    try:
        import dask
    except ImportError:  # pragma: no cover - dask is a raster-extra dependency
        yield
        return
    with dask.config.set(scheduler="threads", num_workers=read_workers):
        yield

# Bumped 2 -> 3 when the STAC loader default changed to groupby="solar_day"
# (same-day scenes are now nodata-mosaicked before compositing), which shifts
# extent values at same-day overlap boundaries versus the old groupby="time"
# path. Old cache CSVs hold pre-change values, so the version bump invalidates
# them rather than silently mixing the two compositing semantics.
_CACHE_SCHEMA_VERSION = 3
_EXTENT_COLUMNS = (
    "n_water",
    "n_aoi",
    "n_valid",
    "n_invalid",
    "n_wet_aoi",
    "extent_pct",
    "invalid_pct",
    "wet_fill_pct",
)


def _aoi_digest(aoi) -> str:
    if isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if hasattr(aoi, "to_json"):
        payload = f"{getattr(aoi, 'crs', None)}\n{aoi.to_json()}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    return hashlib.sha256(repr(aoi).encode("utf-8")).hexdigest()


def _aoi_spans_multiple_tiles(aoi, *, crs, resolution, tile_pixels) -> bool | None:
    """Would this AOI's bounding box cover more than one load tile?

    A tile is ``tile_pixels`` pixels square at ``resolution`` metres, so it
    spans ``tile_pixels * resolution`` metres per side. When the AOI's bounding
    box (measured in the target ``crs``) fits inside a single tile on both
    axes, tiling can only ever produce one tile -- making the tiled+precompute
    path a strict no-op that still pays for a whole-cube precompute read (see
    the performance note in :func:`load_wofs_monthly_extent`). Returns True if
    the bbox spans >1 tile on either axis, False if it fits in one, and None
    when the span cannot be determined without a STAC query (e.g. geopandas
    unavailable, or the AOI type is not introspectable) -- in which case the
    caller must not assume single-tile and should keep the requested path.

    This is a bounding-box test, deliberately conservative: it can only ever
    *confirm* a single tile (bbox strictly inside one tile), never wrongly
    claim multi-tile, so degrading to the untiled path on a False result is
    always output-identical to a 1-tile tiled run.
    """
    if resolution is None or resolution <= 0 or tile_pixels is None or tile_pixels < 1:
        return None
    try:
        import hydroseason.io as _io

        aoi_gdf = _io.load_aoi(aoi)
        target = aoi_gdf.to_crs(_crs_value_local(crs)) if crs is not None else aoi_gdf
        minx, miny, maxx, maxy = (float(v) for v in target.total_bounds)
    except Exception:
        return None
    tile_span_m = float(tile_pixels) * float(resolution)
    return (maxx - minx) > tile_span_m or (maxy - miny) > tile_span_m


def _crs_value_local(crs):
    """Local mirror of ``_io_geo._crs_value`` to avoid importing the STAC module
    just to normalise a CRS int/str for the bbox pre-check."""
    return f"EPSG:{crs}" if isinstance(crs, int) else crs


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
    wet_aoi_hash: str = "",
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
        "wet_aoi_sha256": wet_aoi_hash,
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


def _write_requested_annual_extent_parts(
    extent: pd.DataFrame,
    *,
    cache_root: Path | None,
    stac_url: str,
    collection: str,
    aoi_hash: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    crs: int | str | None,
    resolution: float | None,
    majority: bool,
    wet_aoi_hash: str,
    force: bool,
) -> None:
    """Persist only missing (or forced) annual CSV extent cache parts."""
    if cache_root is None:
        return
    for year_start, year_end in _year_windows(start, end):
        expected_index = pd.date_range(
            year_start.to_period("M").to_timestamp(),
            year_end.to_period("M").to_timestamp(),
            freq="MS",
        )
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
            wet_aoi_hash=wet_aoi_hash,
        )
        cached = None if force or not cache_path.exists() else _read_cached_extent(cache_path)
        if cached is None or not cached.index.equals(expected_index):
            _write_extent_atomic(extent.loc[expected_index, _EXTENT_COLUMNS], cache_path)


def _read_requested_annual_extent_parts(
    *,
    cache_root: Path,
    stac_url: str,
    collection: str,
    aoi_hash: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    crs: int | str | None,
    resolution: float | None,
    majority: bool,
    wet_aoi_hash: str,
) -> pd.DataFrame | None:
    """Return the complete requested legacy CSV cache, if every part is valid."""
    parts = []
    for year_start, year_end in _year_windows(start, end):
        expected_index = pd.date_range(
            year_start.to_period("M").to_timestamp(),
            year_end.to_period("M").to_timestamp(),
            freq="MS",
        )
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
            wet_aoi_hash=wet_aoi_hash,
        )
        cached = _read_cached_extent(cache_path) if cache_path.exists() else None
        if cached is None or not cached.index.equals(expected_index):
            return None
        parts.append(cached)
    return pd.concat(parts).sort_index()


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
            "n_wet_aoi": 0,
            "extent_pct": float("nan"),
            "invalid_pct": float("nan"),
            "wet_fill_pct": float("nan"),
        },
        index=index,
    )


def _aggregate_extent_parts(parts, index):
    """Aggregate per-tile monthly extent counts into annual totals.

    Sums raw integer pixel counts across tiles (n_water, n_aoi, n_valid,
    n_invalid, n_wet_aoi), then recomputes percentages from the summed
    counts. Enforces the invariant n_aoi == n_valid + n_invalid, and produces
    NaN percentages when denominators are zero.
    """
    count_columns = ["n_water", "n_aoi", "n_valid", "n_invalid", "n_wet_aoi"]
    totals = pd.DataFrame(0, index=index, columns=count_columns, dtype="int64")
    for part in parts:
        aligned = part.reindex(index)
        totals = totals.add(aligned[count_columns].fillna(0).astype("int64"), fill_value=0)

    if not (totals["n_aoi"] == totals["n_valid"] + totals["n_invalid"]).all():
        raise ValueError("tile counts violate n_aoi == n_valid + n_invalid")

    extent_pct = np.full(len(totals), np.nan, dtype=float)
    invalid_pct = np.full(len(totals), np.nan, dtype=float)
    wet_fill_pct = np.full(len(totals), np.nan, dtype=float)
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
    np.divide(
        totals["n_water"].to_numpy(dtype=float) * 100.0,
        totals["n_wet_aoi"].to_numpy(dtype=float),
        out=wet_fill_pct,
        where=totals["n_wet_aoi"].to_numpy() > 0,
    )
    totals["extent_pct"] = extent_pct
    totals["invalid_pct"] = invalid_pct
    totals["wet_fill_pct"] = wet_fill_pct
    return totals.loc[:, _EXTENT_COLUMNS]


def _reconcile_pruned_tile_denominator(tiled_extent, full_ts, year_start, year_end, expected_index, time_block, read_workers=None):
    """Replace a tiled/pruned year's denominator columns with the full-TS ground truth.

    Wet-AOI pruning skips loading tiles the ever-wet union never touches, so
    those tiles' n_aoi/n_valid/n_invalid pixel counts (which can genuinely
    vary month to month, e.g. cloud-affected pixels, and cannot be inferred
    from geometry alone) are simply absent from ``tiled_extent`` -- not zero,
    just missing, which silently shrinks the denominator and corrupts
    extent_pct/invalid_pct relative to an unpruned run over the identical
    data. ``full_ts`` is the whole-AOI cube already loaded (at no extra STAC
    cost) to derive the wet AOI in the first place, so slicing it to this
    year and reducing it once with monthly_water_extent (no wet_aoi -- this
    is the plain, untiled ground truth) gives the exact n_water/n_aoi/
    n_valid/n_invalid/extent_pct/invalid_pct an unpruned tiled run would have
    produced (the tiled sum-then-percentage aggregation is bit-exact versus
    a whole-cube reduction; see
    test_tiled_reduction_matches_whole_cube_reduction_with_boundary_canonical_values).
    Only n_wet_aoi/wet_fill_pct are left untouched, since pruning is allowed
    to change those two.
    """
    year_slice = full_ts.sel(time=slice(year_start, year_end))
    ground_truth = monthly_water_extent(
        year_slice, time_block=time_block, read_workers=read_workers
    )
    if not ground_truth.index.equals(expected_index):
        raise ValueError(
            f"full-TS cube has an unexpected monthly index for "
            f"{year_start:%Y-%m} - {year_end:%Y-%m}"
        )
    reconciled = tiled_extent.copy()
    for column in ("n_water", "n_aoi", "n_valid", "n_invalid", "extent_pct", "invalid_pct"):
        reconciled[column] = ground_truth[column]
    return reconciled


def load_wofs_monthly_extent(
    stac_url: str,
    collection: str,
    aoi,
    start_date: str,
    end_date: str,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    mask_cache_dir: str | os.PathLike[str] | None = None,
    offline: bool = False,
    crs: int | str | None = 3577,
    resolution: float | None = None,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_block: int = 12,
    majority: bool = True,
    force: bool = False,
    tile_pixels: int | None = None,
    wet_aoi=None,
    precompute_wet_aoi: bool = False,
    persistence_min: float = 0.0,
    close_m: float = 150.0,
    buffer_m: float = 300.0,
    progress: bool = False,
    progress_desc: str | None = None,
    progress_position: int | None = None,
    auto_tiling: bool = True,
    read_workers: int | None = None,
    diagnostics_callback: Callable[[dict[str, int]], None] | None = None,
    resampling_policy: Literal["categorical_safe", "native_aligned"] = "categorical_safe",
    year_workers: int = 1,
    wet_mask: Literal["off", "dea_stats"] = "off",
) -> pd.DataFrame:
    """Compute monthly WOfS extent in resumable calendar-year pieces.

    Each year is loaded and reduced independently, bounding graph size and
    allowing a stopped run to resume from its last completed year.  When
    ``cache_dir`` is supplied, CSV cache identity includes all data-affecting
    inputs, the AOI content hash, and (when a wet AOI is in play) its content
    hash too -- a different wet AOI never silently reads a stale cache.

    ``progress=True`` shows a tqdm bar ticking once per calendar year
    processed (cache hits included), so long tiled STAC pulls give visible
    feedback instead of blocking silently.

    ``read_workers``, if given (and > 0), overrides dask's threaded-scheduler
    worker count while the lazy STAC/COG graph is materialised -- both the
    precompute whole-cube pass and every per-year reduction.

    PROFILING RESULT (see git history for the investigation): forcing a
    worker count here does NOT help and usually HURTS. Measured on a 133-scene
    AOI-year, dask's own default (unset) decoded in ~18-23s; explicit worker
    counts of 4, 8, 16, 32, and 64 were all slower than unset, and got
    monotonically worse above ~8 workers (64 workers: ~30s, nearly 2x unset).
    The workload is decode/warp-CPU-bound, not I/O-latency-bound as originally
    assumed -- a raw concurrent-HTTP probe fetching the same 133 scenes'
    headers took ~6s, so the wall is GDAL's per-scene GeoTIFF decode and
    reprojection, which dask's own worker-count heuristic already sizes
    close to this machine's real parallel-decode capacity. Forcing a
    higher number adds thread-scheduling/lock contention on top of an
    already-saturated decode step. The default is therefore ``None`` (leave
    dask's scheduler untouched); only pass an explicit value if you have
    profiled your own machine and confirmed it helps there -- it very
    likely will not.

    ``auto_tiling=True`` (the default) degrades a requested tiled load to the
    plain untiled path when the AOI's bounding box provably fits inside one
    load tile (``tile_pixels * resolution`` metres per side). In that case
    tiling can only ever yield a single tile, so its output is bit-identical
    to the untiled reduction, but ``precompute_wet_aoi`` would still pay for a
    full extra whole-cube read to prune a one-cell grid. Degrading skips that
    dead cost. It is suppressed when a ``wet_aoi`` is caller-supplied (that
    genuinely changes ``n_wet_aoi``/``wet_fill_pct``), and can be turned off
    with ``auto_tiling=False`` to force the tiled path regardless of AOI size.

    When ``tile_pixels`` is set, each annual window is loaded tile-by-tile via
    :func:`hydroseason.io.iter_wofs_tiles_from_stac` instead of as one whole-AOI
    load. Already-cached tile CSVs (under a per-year tile-cache directory
    derived from the annual cache path) are read and their ids passed as
    ``skip_tile_ids``, so an interrupted year resumes at tile granularity on
    the next call. This has no effect on the annual cache's identity: a
    complete annual result is tile-shape-independent, so it is written to and
    read from the same cache file as the untiled path.

    ``wet_aoi``, if given, is an already-computed wet-AOI GeoDataFrame (see
    :func:`hydroseason.io.compute_wet_aoi`) threaded into every tiled per-year
    load's ``n_wet_aoi``/``wet_fill_pct`` computation, and -- only when a
    ``full_ts`` cube is also available to reconcile against (see below) -- as
    a second, independent tile-skip gate too. If ``precompute_wet_aoi`` is
    True and ``wet_aoi`` is not supplied, one full-time-series
    ``load_wofs_from_stac`` pass over the whole requested window is used to
    derive it via :func:`hydroseason.io.compute_wet_aoi` (using
    ``persistence_min``, ``close_m``, ``buffer_m``), before any per-year tiled
    loads happen. ``precompute_wet_aoi`` requires ``tile_pixels`` -- pruning
    only exists on the tiled path, so precomputing a wet AOI without tiling
    would be a no-op the caller almost certainly didn't intend.

    KNOWN LIMITATION: this full-time-series precompute pass runs
    unconditionally, even when every year in the requested range is already
    cached from a prior run -- it is not skipped on a fully-cached resume.
    This is because the per-year cache key includes a hash of the derived
    ``wet_aoi`` itself (see ``wet_aoi_hash`` below), which cannot be known
    before ``wet_aoi`` is actually derived; there is no cheaper way to check
    "is this already cached" without first paying the cost being checked
    for. A fully correct fix would persist the derived wet-AOI geometry as
    its own cache artifact (keyed on the non-wet-AOI-hash-dependent inputs)
    so it can be reloaded cheaply on a later call instead of re-derived --
    tracked as follow-up work, not implemented here. This is a performance
    regression on repeat calls, not a correctness issue: results are still
    correct, just not resumed cheaply.

    Pruning tiles that the wet AOI excludes guarantees those tiles contribute
    no water -- but ``iter_wofs_tiles_from_stac`` never loads them, so their
    ``n_aoi``/``n_valid``/``n_invalid`` pixel counts (which genuinely can
    differ per month, e.g. cloud-affected pixels, and cannot be inferred from
    geometry alone) would otherwise silently vanish from the tiled
    aggregate's denominator instead of being counted as unseen-but-real AOI
    pixels -- corrupting ``extent_pct`` even though pruning never touches
    which pixels contribute *water*. When ``wet_aoi`` was derived internally
    here (not supplied by the caller), the already-loaded ``full_ts`` cube
    covers the exact same AOI/CRS/resolution as the tiled path and was fetched
    regardless of pruning, so it is reduced once per year with
    :func:`hydroseason.hydro_year.monthly_water_extent` and its
    ``n_water``/``n_aoi``/``n_valid``/``n_invalid``/``extent_pct``/
    ``invalid_pct`` replace the (potentially pruning-truncated) tiled
    aggregate's for that year -- an exact, no-extra-STAC-cost source of
    truth, computed from data already resident rather than reconstructed.
    Only ``n_wet_aoi``/``wet_fill_pct`` are left to the tiled aggregate,
    since those two are legitimately allowed to differ under pruning.

    This reconciliation only applies when ``precompute_wet_aoi`` derived
    ``wet_aoi`` here, because only then is a ``full_ts`` cube available to
    reconcile against. A caller-supplied ``wet_aoi`` has no accompanying
    full-time-series cube, so there is no ground truth to correct the tiled
    aggregate's denominator against if pruning were allowed to run -- and
    running it anyway would silently corrupt ``extent_pct``/``invalid_pct``.
    To guarantee correctness, pruning is therefore automatically disabled
    (falling back to loading every tile, unpruned) whenever there is no
    ``full_ts`` to reconcile against -- i.e., only a ``precompute_wet_aoi``-
    derived ``wet_aoi`` currently benefits from tile-skip pruning; an
    externally-supplied ``wet_aoi`` does not, today. This is a real,
    documented capability boundary, not a bug: an externally-supplied
    ``wet_aoi`` still gets its ``n_wet_aoi``/``wet_fill_pct`` computed
    correctly against the real wet-AOI geometry (that calculation only reads
    pixels from tiles actually loaded, and every tile is loaded when pruning
    is disabled, so it has no missing-tile denominator problem of its own)
    -- it just does not skip loading any tiles.
    """
    if time_block < 1:
        raise ValueError("time_block must be at least 1.")
    if tile_pixels is not None:
        if tile_pixels < 1:
            raise ValueError("tile_pixels must be at least 1.")
        if resolution is None or resolution <= 0:
            raise ValueError("tiled loading requires a positive resolution.")
    if precompute_wet_aoi and tile_pixels is None:
        raise ValueError("precompute_wet_aoi requires tile_pixels (pruning is tiled-only).")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date.")

    # Auto-degrade to the untiled path when the AOI's bounding box provably
    # fits inside a single load tile. Tiling then produces exactly one tile,
    # so the tiled aggregate is bit-identical to a plain whole-AOI reduction
    # -- but the tiled+precompute path would still pay for a full whole-cube
    # precompute read to prune a one-cell grid (see the perf note below). We
    # only degrade when no caller-supplied wet_aoi is in play: a supplied
    # wet_aoi changes n_wet_aoi/wet_fill_pct output, so dropping the tiled
    # path (which is where a supplied wet_aoi is consumed) would silently
    # alter results. precompute_wet_aoi-derived wet AOIs are safe to drop
    # because a single-tile run reconciles to the same whole-cube ground truth.
    if auto_tiling and tile_pixels is not None and wet_aoi is None:
        spans = _aoi_spans_multiple_tiles(
            aoi, crs=crs, resolution=resolution, tile_pixels=tile_pixels,
        )
        if spans is False:
            if _profile_enabled():
                import sys
                print(
                    "  [profile] auto-tiling: AOI fits in one tile -> "
                    "using untiled path (skipping precompute double-read)",
                    file=sys.stderr, flush=True,
                )
            tile_pixels = None
            precompute_wet_aoi = False

    cache_root = Path(cache_dir) if cache_dir is not None else None
    aoi_hash = _aoi_digest(aoi) if cache_root is not None else ""
    parts: list[pd.DataFrame] = []

    # Resolve through the facade at call time to preserve the existing loader
    # monkeypatch seam and keep this module independent of optional STAC deps.
    import hydroseason.io as _io

    if mask_cache_dir is not None or offline:
        wet_aoi_hash = _aoi_digest(wet_aoi) if (cache_root is not None and wet_aoi is not None) else ""
        if cache_root is not None and not force and (wet_aoi is not None or not precompute_wet_aoi):
            cached_extent = _read_requested_annual_extent_parts(
                cache_root=cache_root,
                stac_url=stac_url,
                collection=collection,
                aoi_hash=aoi_hash,
                start=start,
                end=end,
                crs=crs,
                resolution=resolution,
                majority=majority,
                wet_aoi_hash=wet_aoi_hash,
            )
            if cached_extent is not None:
                return cached_extent
        if offline and mask_cache_dir is None:
            raise FileNotFoundError(
                "offline WOfS cache miss: mask_cache_dir is required for offline mode"
            )
        try:
            handle = _io.acquire_wofs_cache(
                stac_url, collection, aoi, start_date, end_date,
                cache_root=mask_cache_dir,
                crs=crs,
                resolution=resolution,
                chunk_x=chunk_x,
                chunk_y=chunk_y,
                time_chunk=time_block,
                majority=majority,
                offline=offline,
                force=force,
                progress=progress,
                progress_desc=progress_desc,
                progress_position=progress_position,
                diagnostics_callback=diagnostics_callback,
                wet_aoi=wet_aoi,
                compute_batch_size=16,
                read_workers=read_workers,
                resampling_policy=resampling_policy,
                year_workers=year_workers,
                wet_mask=wet_mask,
            )
        except FileNotFoundError as exc:
            if offline:
                raise FileNotFoundError(f"offline WOfS cache miss: {exc}") from exc
            raise
        if wet_aoi is None and not precompute_wet_aoi:
            fast_extent = _io.open_completed_extent_counts(
                handle, start_date, end_date, read_workers=read_workers
            )
            if fast_extent is not None:
                _write_requested_annual_extent_parts(
                    fast_extent,
                    cache_root=cache_root,
                    stac_url=stac_url,
                    collection=collection,
                    aoi_hash=aoi_hash,
                    start=start,
                    end=end,
                    crs=crs,
                    resolution=resolution,
                    majority=majority,
                    wet_aoi_hash=wet_aoi_hash,
                    force=force,
                )
                return fast_extent
        masks = _io.open_completed_mask_cache(
            handle, start_date, end_date,
            chunk_x=chunk_x, chunk_y=chunk_y, time_chunk=time_block,
        )
        effective_wet_aoi = wet_aoi
        if precompute_wet_aoi and effective_wet_aoi is None:
            effective_wet_aoi = _io.load_or_build_cached_wet_aoi(
                handle, persistence_min=persistence_min, close_m=close_m, buffer_m=buffer_m,
            )
        if effective_wet_aoi is not None:
            wet_aoi_hash = effective_wet_aoi.attrs.get(
                "hydroseason_wet_aoi_identity", _aoi_digest(effective_wet_aoi)
            )
        extent = monthly_water_extent(
            masks, time_block=time_block, wet_aoi=effective_wet_aoi, read_workers=read_workers,
        )
        _write_requested_annual_extent_parts(
            extent,
            cache_root=cache_root,
            stac_url=stac_url,
            collection=collection,
            aoi_hash=aoi_hash,
            start=start,
            end=end,
            crs=crs,
            resolution=resolution,
            majority=majority,
            wet_aoi_hash=wet_aoi_hash,
            force=force,
        )
        return extent

    full_ts = None
    if precompute_wet_aoi and wet_aoi is None:
        with _phase("precompute wet-AOI (whole-cube read)"), _read_concurrency(read_workers):
            full_ts = _io.load_wofs_from_stac(
                stac_url, collection, aoi,
                start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                crs=crs, resolution=resolution,
                chunk_x=chunk_x, chunk_y=chunk_y, time_chunk=time_block, majority=majority,
            )
            wet_aoi = _io.compute_wet_aoi(
                full_ts, persistence_min=persistence_min, close_m=close_m, buffer_m=buffer_m,
            )

    wet_aoi_hash = _aoi_digest(wet_aoi) if (cache_root is not None and wet_aoi is not None) else ""

    # Pruning (iter_wofs_tiles_from_stac's tile-skip gate) is only safe when
    # full_ts is available to reconcile the tiled aggregate's denominator
    # against afterwards (see _reconcile_pruned_tile_denominator) -- that
    # covers both "no wet_aoi at all" and "an externally-supplied wet_aoi
    # with no accompanying full_ts". Falling back to None here disables
    # pruning entirely for the externally-supplied case, trading away the
    # tile-skip speedup for correctness. n_wet_aoi/wet_fill_pct are a
    # separate concern -- they are computed per loaded tile from whichever
    # tiles genuinely get read, with no missing-tile denominator problem,
    # so they must keep using the real, caller-supplied wet_aoi (not this
    # pruning-gated fallback) to reflect the true wet-AOI geometry.
    effective_wet_aoi = wet_aoi if full_ts is not None else None

    year_iter = _year_windows(start, end)
    if progress:
        from tqdm.auto import tqdm

        tqdm_kwargs = {
            "total": end.year - start.year + 1,
            "desc": progress_desc if progress_desc else "years",
            "unit": "yr",
        }
        if progress_position is not None:
            tqdm_kwargs["position"] = progress_position
            tqdm_kwargs["leave"] = True

        year_iter = tqdm(year_iter, **tqdm_kwargs)

    for year_start, year_end in year_iter:
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
                wet_aoi_hash=wet_aoi_hash,
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

            tiles = iter(
                _io.iter_wofs_tiles_from_stac(
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
                    wet_aoi=effective_wet_aoi,
                )
            )
            # The STAC query fires lazily, on the generator's first advancement.
            # Isolate that single `next()` in a narrow try/except so only the
            # intentional "No STAC items found" ValueError it can raise is ever
            # caught here -- ValueErrors raised later, while reducing tiles in
            # the loop body below, must never be misrouted into this branch.
            try:
                first_tile = next(tiles)
            except StopIteration:
                first_tile = None
            except ValueError as exc:
                if "No STAC items found" not in str(exc):
                    raise
                extent = _missing_year_extent(year_start, year_end)
                if cache_path is not None:
                    _write_extent_atomic(extent, cache_path)
                parts.append(extent)
                continue

            remaining_tiles = tiles if first_tile is None else itertools.chain([first_tile], tiles)
            n_loaded = 0
            with _phase(f"tiled load {year_start:%Y} (loading tiles)"):
                for tile_id, water_mask in remaining_tiles:
                    tile_extent = monthly_water_extent(
                        water_mask, time_block=time_block, wet_aoi=wet_aoi,
                        read_workers=read_workers,
                    )
                    if not tile_extent.index.equals(expected_index):
                        raise ValueError(f"tile {tile_id} has an unexpected monthly index")
                    if tile_cache_dir is not None:
                        _write_extent_atomic(tile_extent, tile_cache_dir / f"{tile_id}.csv")
                    tile_parts[tile_id] = tile_extent
                    n_loaded += 1
            if _profile_enabled():
                import sys
                print(
                    f"  [profile] {year_start:%Y}: {n_loaded} tiles loaded, "
                    f"{len(tile_parts) - n_loaded} from cache",
                    file=sys.stderr, flush=True,
                )

            if not tile_parts:
                raise ValueError(
                    f"no tiles were produced for {year_start:%Y-%m} - {year_end:%Y-%m} "
                    "despite STAC items being found"
                )
            extent = _aggregate_extent_parts(tile_parts.values(), expected_index)
            if full_ts is not None:
                extent = _reconcile_pruned_tile_denominator(
                    extent, full_ts, year_start, year_end, expected_index, time_block,
                    read_workers=read_workers,
                )
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
            extent = monthly_water_extent(
                water_mask, time_block=time_block, wet_aoi=wet_aoi,
                read_workers=read_workers,
            )
        if cache_path is not None:
            _write_extent_atomic(extent, cache_path)
        parts.append(extent)

    combined = pd.concat(parts).sort_index()
    if combined.index.has_duplicates:
        duplicates = combined.index[combined.index.duplicated()].unique()
        raise ValueError(f"duplicate cached extent months: {list(duplicates)}")
    return combined


__all__ = ["load_wofs_monthly_extent"]
