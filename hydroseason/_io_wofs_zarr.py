"""Identity, on-disk index, writer lock, and disk preflight for the WOfS Zarr cache.

This module defines what makes one cached WOfS (Water Observations from
Space) Zarr store the *same* as another: a :class:`WOfSCacheRequest` captures
every data-semantic input a caller controls before any STAC/network access
(the STAC endpoint, collection, AOI content hash, date range, CRS,
resolution, and the classifier/planner/schema versions that shift output
semantics), and hashes to a stable ``request_digest()``. Once STAC resolution
and spatial planning (see :mod:`hydroseason._spatial_plan`) determine the
actual raster grid, a :class:`WOfSCacheIdentity` extends the request with
that grid's ``shape``/``transform``/``grid_anchor`` and hashes to a fuller
``digest`` that also pins the grid -- two requests with identical semantics
but different resolved grids get different stores.

On disk, ``cache_root / "index" / f"{request_digest}.json"`` is a small JSON
pointer (written atomically) from a request digest to its store path and
full identity, so a later *offline* run (:func:`resolve_cached_request`,
:func:`require_cached_request`) can look up a completed cache from local
files alone, with zero network access. :func:`cache_writer_lock` is an
exclusive on-disk lock (``cache_root / ".locks" / f"{request_digest}.lock"``)
so two processes never write the same store concurrently.
:func:`preflight_cache_space` and :func:`preflight_request_space` are
conservative disk-space checks callers run *before* any expensive
network/read work, so an undersized disk fails fast rather than mid-write.

This module also implements the annual Zarr group writer/reader that
persists WOfS pixels underneath a :class:`WOfSCacheHandle`'s store
(``handle.path``). :func:`write_annual_group` materialises one calendar
year's canonical water-mask cube into ``handle.path / "years" / "<year>"``
as a resumable, atomically-published Zarr v2 group: it writes to a sibling
temporary directory first, validates the result (:func:`validate_annual_group`),
and only then publishes it in place with a single ``os.replace`` -- so a
crash or interruption mid-write leaves either the previous completed state
or nothing, never a half-written year directory that :func:`completed_years`
would mistake for done. :func:`open_completed_mask_cache` is the read side:
it lazily opens every completed year in a requested date range, concatenates
them in year order, and fills any still-missing months using the same
:func:`hydroseason._io_extent.complete_monthly_axis` convention the rest of
the codebase already uses for gappy monthly cubes (missing months become
``-1`` invalid, matching :data:`CANONICAL_VALUES` semantics).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

# Bumped whenever the on-disk index/manifest layout changes in a way that
# makes an old cache unreadable by new code (or vice versa).
# 3: WOfSCacheRequest gained wet_mask_sha256 (spatial pruning provenance).
# 4: WOfSCacheRequest gained the 8 historical_mask_* fields (the exact
#    scientific-mask provenance/identity), and the store gained the
#    analysis-mask/ Zarr+manifest sidecar (see CacheAnalysisMask).
WOFS_CACHE_SCHEMA_VERSION = 4

# Bumped whenever the water classifier's pixel-value semantics change (e.g.
# a different canonical-value mapping), so old cached pixels are never read
# as if they were classified under the new rule.
WOFS_CLASSIFIER_VERSION = 1

# Bumped whenever the spatial planner's tiling/selection rule changes in a
# way that could shift which windows a cached grid was built from. Mirrors
# hydroseason._spatial_plan's own planner version; kept as a separate
# constant here because a cache identity must remain valid to compare even
# if that module's internal version constant changes independently.
WOFS_PLANNER_VERSION = 1

# The per-year content digest is a cache-invalidation fingerprint over the
# pixels actually loaded, not a security boundary, so it is chosen for speed.
# blake2b is 2-4x faster than sha256 on the multi-hundred-GB byte volume a
# continental 40-year acquisition pushes through it, and because hashing holds
# the GIL, that directly unblocks the year_workers threads in
# _io_wofs_acquire.acquire_wofs_cache.
CONTENT_DIGEST_ALGORITHM = "blake2b"


def _content_hasher():
    """A fresh content-digest hash object. Never share one across years."""
    return hashlib.blake2b()


# Canonical WOfS mask values: -2 outside AOI, -1 invalid/no observation,
# 0 dry, 1 water.
CANONICAL_VALUES = (-2, -1, 0, 1)

# Fixed chunk shape (time, y, x) for the annual Zarr mask arrays written by
# the Task 3 store writer. Defined here because it is part of the cache's
# on-disk identity/contract, not a per-call tuning knob.
MASK_CHUNKS = (1, 512, 512)

_INDEX_DIRNAME = "index"
_LOCKS_DIRNAME = ".locks"
_MANIFEST_FILENAME = "manifest.json"

# Spatial chunk edge (pixels) for the annual Zarr storage grid; matches
# MASK_CHUNKS' y/x extent. Also used to derive the wet_count/clear_count
# local derived-array chunking.
_STORAGE_CHUNK = 512

_YEARS_DIRNAME = "years"
# Written last, inside the temporary annual group, only after validation
# passes -- its presence (post-rename) is what distinguishes a genuinely
# completed annual group from a directory that merely exists.
_COMPLETE_FILENAME = "complete.json"


def _canonical_json_bytes(payload: dict) -> bytes:
    """Order- and whitespace-independent JSON encoding used for all digests."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _sha256_digest(payload: dict) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


@dataclasses.dataclass(frozen=True)
class WOfSCacheRequest:
    """Every data-semantic input that identifies a WOfS cache request.

    Known before any STAC/network access: the source (``stac_url``,
    ``collection``), the AOI (as a content hash, ``aoi_sha256`` -- callers
    hash their own AOI object so this module never needs to know how to
    hash arbitrary AOI types), the requested date range, the target CRS and
    resolution, the compositing knobs (``groupby``, ``majority``), and the
    versions of the classifier/planner/schema that could shift output
    semantics for otherwise-identical inputs.

    ``request_digest()`` is a stable SHA-256 over every field, computed via
    canonical (sorted-key, whitespace-free) JSON -- see the module
    docstring. It does not depend on the resolved raster grid; see
    :class:`WOfSCacheIdentity` for the digest that does.
    """

    stac_url: str
    collection: str
    aoi_sha256: str
    start_date: str
    end_date: str
    crs: str
    resolution: float
    classifier_version: int
    groupby: str
    majority: bool
    planner_version: int
    schema_version: int
    # Digest of the wet mask a pruned acquisition read under, or None for a
    # full-coverage read. Outside the mask a pruned year is permanently -2,
    # which no reader can distinguish from genuinely dry, so pruned and
    # unpruned results must never share a store. Omitted from the digest
    # payload entirely when None, so every cache written before this field
    # existed keeps its original request_digest and stays reachable.
    wet_mask_sha256: str | None = None
    # A prepared hydroseason._io_dea_stats.WetPlanningFootprint's identity,
    # threaded independently of wet_mask_sha256 (a planning_footprint and an
    # explicit wet_aoi are mutually exclusive at the acquire_wofs_cache call
    # site, but the cache identity still needs its own dedicated fields --
    # reusing wet_mask_sha256 would conflate two different provenance
    # stories). All four are None together or set together (see
    # _io_wofs_acquire.acquire_wofs_cache); omitted from the digest payload
    # entirely when None, exactly like wet_mask_sha256, so every cache
    # written before planning-footprint support existed keeps its original
    # request_digest and stays reachable.
    footprint_digest: str | None = None
    footprint_factor: int | None = None
    footprint_safety_cells: int | None = None
    footprint_covered_years: tuple[int, ...] | None = None
    # "legacy" (the default) preserves every existing hydroseason result and
    # cache identity byte-for-byte, so it is omitted from the digest payload
    # like other absent/default provenance fields. "hydrofragments_v1" is new
    # behaviour (task W2.2's dual-composite extent counts, not implemented by
    # this field alone) that must never share a store with a "legacy" run of
    # otherwise-identical parameters, so non-legacy values remain digest
    # inputs.
    composite_bundle: str = "legacy"
    # The exact historical maximum-water mask's identity/provenance (Task 4),
    # threaded independently of wet_mask_sha256/footprint_* -- a scientific
    # analysis mask and a planning-only footprint are two different
    # provenance stories that must never be conflated into one digest input.
    # All eight fields are None together when no historical mask is supplied
    # (the pre-Task-4 shape) and set together when one is (see
    # hydroseason._io_wofs_acquire.acquire_wofs_cache); omitted from the
    # digest payload entirely when None, exactly like wet_mask_sha256/
    # footprint_*, so every cache written before historical-mask support
    # existed keeps its original request_digest and stays reachable.
    historical_mask_sha256: str | None = None
    historical_mask_product: str | None = None
    historical_mask_version: str | None = None
    historical_mask_item_ids: tuple[str, ...] | None = None
    historical_mask_lineage: tuple[str, ...] | None = None
    historical_mask_coverage_start: str | None = None
    historical_mask_coverage_end: str | None = None
    historical_mask_pixel_count: int | None = None

    def _digest_payload(self) -> dict:
        payload = dataclasses.asdict(self)
        if payload.get("wet_mask_sha256") is None:
            # Absent, not null: keeps pre-existing full-coverage caches at
            # their original digest.
            payload.pop("wet_mask_sha256", None)
        for footprint_field in (
            "footprint_digest", "footprint_factor", "footprint_safety_cells",
            "footprint_covered_years",
        ):
            if payload.get(footprint_field) is None:
                payload.pop(footprint_field, None)
        if payload.get("footprint_covered_years") is not None:
            # Tuples survive dataclasses.asdict() as tuples, but canonical
            # JSON encoding needs a list -- keep the payload JSON-serialisable
            # like every other field.
            payload["footprint_covered_years"] = list(payload["footprint_covered_years"])
        if payload.get("composite_bundle") == "legacy":
            payload.pop("composite_bundle", None)
        for historical_mask_field in (
            "historical_mask_sha256", "historical_mask_product", "historical_mask_version",
            "historical_mask_item_ids", "historical_mask_lineage",
            "historical_mask_coverage_start", "historical_mask_coverage_end",
            "historical_mask_pixel_count",
        ):
            if payload.get(historical_mask_field) is None:
                payload.pop(historical_mask_field, None)
        for tuple_field in ("historical_mask_item_ids", "historical_mask_lineage"):
            if payload.get(tuple_field) is not None:
                # Same tuple-to-list normalisation as footprint_covered_years
                # above -- canonical JSON encoding needs a list.
                payload[tuple_field] = list(payload[tuple_field])
        return payload

    def request_digest(self) -> str:
        return _sha256_digest(self._digest_payload())


@dataclasses.dataclass(frozen=True)
class WOfSCacheIdentity:
    """A :class:`WOfSCacheRequest` extended with the resolved raster grid.

    ``shape`` is ``(rows, cols)`` and ``transform`` is a six-value affine
    tuple ``(a, b, c, d, e, f)`` (the same convention as
    ``affine.Affine`` / ``rasterio``'s ``.to_gdal()`` ordering), neither of
    which is known until STAC resolution and spatial planning have run.
    ``grid_anchor`` is a caller-supplied stable label for the grid's origin
    (e.g. a rounded top-left coordinate string) used to keep the identity
    stable across equivalent-but-differently-derived grids; it participates
    in ``digest`` like any other field.

    ``request_digest`` (a property here, not a method -- unlike the
    underlying request) is delegated from the wrapped request and is
    unaffected by ``shape``/``transform``/``grid_anchor``. ``digest`` is the
    full store identity: it changes whenever the grid changes even though
    ``request_digest`` does not, because two requests that agree on every
    semantic field can still resolve to different grids (e.g. a STAC catalog
    update shifts pixel alignment) and must not share a store.
    """

    request: WOfSCacheRequest
    shape: tuple[int, int]
    transform: tuple[float, float, float, float, float, float]
    grid_anchor: str

    @classmethod
    def from_request(
        cls,
        request: WOfSCacheRequest,
        *,
        shape: tuple[int, int],
        transform: tuple[float, float, float, float, float, float],
        grid_anchor: str | None = None,
    ) -> "WOfSCacheIdentity":
        shape = (int(shape[0]), int(shape[1]))
        transform = tuple(float(v) for v in transform)
        if len(transform) != 6:
            raise ValueError(f"transform must have six values, got {transform!r}")
        if grid_anchor is None:
            grid_anchor = f"{transform[2]:.6f},{transform[5]:.6f}"
        return cls(request=request, shape=shape, transform=transform, grid_anchor=grid_anchor)

    @property
    def request_digest(self) -> str:
        return self.request.request_digest()

    @property
    def digest(self) -> str:
        payload = {
            "request": self.request._digest_payload(),
            "shape": list(self.shape),
            "transform": list(self.transform),
            "grid_anchor": self.grid_anchor,
        }
        return _sha256_digest(payload)

    def to_dict(self) -> dict:
        return {
            "request": self.request._digest_payload(),
            "request_digest": self.request_digest,
            "shape": list(self.shape),
            "transform": list(self.transform),
            "grid_anchor": self.grid_anchor,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "WOfSCacheIdentity":
        request = WOfSCacheRequest(**payload["request"])
        return cls(
            request=request,
            shape=(int(payload["shape"][0]), int(payload["shape"][1])),
            transform=tuple(float(v) for v in payload["transform"]),
            grid_anchor=payload["grid_anchor"],
        )


@dataclasses.dataclass(frozen=True)
class WOfSCacheHandle:
    """A resolved pointer to a (possibly complete) on-disk WOfS cache store."""

    path: Path
    identity: str
    request_digest: str


def _index_path(cache_root: Path, request_digest: str) -> Path:
    return Path(cache_root) / _INDEX_DIRNAME / f"{request_digest}.json"


def _lock_path(cache_root: Path, request_digest: str) -> Path:
    return Path(cache_root) / _LOCKS_DIRNAME / f"{request_digest}.lock"


def _store_dir(cache_root: Path, identity_digest: str) -> Path:
    return Path(cache_root) / f"{identity_digest}.zarr"


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write ``payload`` as canonical JSON to ``path`` without ever partial-writing.

    Uses ``tempfile.mkstemp`` in the same directory as ``path`` (so the
    final ``os.replace`` is an atomic rename on the same filesystem), then
    replaces the target in one step. A crash or concurrent read at any point
    before the final ``os.replace`` observes either the old file or nothing
    new -- never a truncated/partial one. Routes through :func:`_long_path`
    so this also works when ``path`` is nested deep enough to exceed
    Windows' legacy ``MAX_PATH`` (e.g. an annual group's ``complete.json``).
    """
    parent = Path(_long_path(path.parent))
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json_bytes(payload))
        os.replace(str(temp_path), _long_path(path))
    finally:
        temp_path.unlink(missing_ok=True)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(Path(_long_path(path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle == 0:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def cache_writer_lock(cache_root: Path, request_digest: str) -> Iterator[None]:
    """Exclusive on-disk lock guarding writes to one request's cache store."""
    lock_path = _lock_path(Path(cache_root), request_digest)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        data = _read_json(lock_path)
        if data and "pid" in data and not _is_pid_alive(data["pid"]):
            lock_path.unlink(missing_ok=True)
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise RuntimeError(
                    f"cache request {request_digest} is already being written "
                    f"(lock file present at {lock_path})"
                ) from exc
        else:
            raise RuntimeError(
                f"cache request {request_digest} is already being written "
                f"(lock file present at {lock_path})"
            ) from exc
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "created": time.time()}))
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _manifest_identity(identity: Any) -> dict:
    if hasattr(identity, "to_dict"):
        return identity.to_dict()
    if hasattr(identity, "as_dict"):
        return identity.as_dict()
    import dataclasses
    if dataclasses.is_dataclass(identity):
        return dataclasses.asdict(identity)
    raise TypeError(f"Cannot serialize identity: {identity!r}")


def create_cache_handle(cache_root: Path, identity: Any) -> WOfSCacheHandle:
    """Create the root Zarr group for ``identity`` and register it in the index.

    Creates (or opens, idempotently) the store's root Zarr group at
    ``cache_root / "stores" / <request_digest>``, writes that store's root
    manifest (its full identity, so a later reader can validate a hit
    without recomputing anything) and the request index entry pointing to
    it -- both atomically, via :func:`_write_json_atomic` -- and returns the
    resulting :class:`WOfSCacheHandle`.

    Does not acquire :func:`cache_writer_lock` itself; callers that need
    exclusivity across processes must wrap this (and any subsequent writes)
    in that context manager themselves.
    """
    cache_root = Path(cache_root)
    request_digest = identity.request_digest
    store_dir = _store_dir(cache_root, identity.digest)
    store_dir.mkdir(parents=True, exist_ok=True)

    import zarr

    zarr.open_group(_zarr_store(store_dir), mode="a")

    identity_dict = _manifest_identity(identity)
    manifest = {
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
        "request_digest": request_digest,
        "identity": identity_dict,
    }
    _write_json_atomic(store_dir / _MANIFEST_FILENAME, manifest)

    start_date = identity.request.start_date if hasattr(identity, "request") else identity.start_date
    end_date = identity.request.end_date if hasattr(identity, "request") else identity.end_date

    index_entry = {
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
        "request_digest": request_digest,
        "identity": identity_dict,
        "store": str(store_dir.relative_to(cache_root)).replace(os.sep, "/"),
        "start_date": start_date,
        "end_date": end_date,
    }
    _write_json_atomic(_index_path(cache_root, request_digest), index_entry)

    return WOfSCacheHandle(path=store_dir, identity=identity.digest, request_digest=request_digest)


def cache_request_uses_pruning(handle: WOfSCacheHandle) -> bool:
    """True when the store request identity records a pruning source."""
    manifest = _read_json(Path(handle.path) / _MANIFEST_FILENAME)
    identity = manifest.get("identity") if isinstance(manifest, dict) else None
    request = identity.get("request") if isinstance(identity, dict) else None
    if not isinstance(request, dict):
        return False
    return bool(
        request.get("wet_mask_sha256")
        or request.get("footprint_digest")
        or request.get("footprint_factor")
        or request.get("footprint_safety_cells")
        or request.get("footprint_covered_years")
    )


def _validate_hit(cache_root: Path, index_entry: dict, request: WOfSCacheRequest) -> WOfSCacheHandle | None:
    """Confirm an index entry's store manifest still matches both digests.

    A hit requires the index entry's own request digest to match the
    request being looked up (cheap, no filesystem access beyond what the
    caller already did to find the entry), AND the store's own manifest
    file to independently agree on both the request digest and the full
    identity digest. The second check catches a stale or hand-edited index
    entry that points at a store manifest which no longer matches -- such
    an entry is treated as a miss (``None``), never as a hit trusted purely
    from the index.
    """
    if index_entry.get("request_digest") != request.request_digest():
        return None
    store_rel = index_entry.get("store")
    if not store_rel:
        return None
    store_dir = cache_root / Path(store_rel)
    manifest = _read_json(store_dir / _MANIFEST_FILENAME)
    if manifest is None:
        return None
    if manifest.get("request_digest") != request.request_digest():
        return None
    index_identity = index_entry.get("identity") or {}
    manifest_identity = manifest.get("identity") or {}
    if index_identity.get("digest") != manifest_identity.get("digest"):
        return None
    try:
        resolved_identity = WOfSCacheIdentity.from_dict(manifest_identity)
    except (KeyError, TypeError, ValueError):
        return None
    if resolved_identity.digest != manifest_identity.get("digest"):
        return None
    if resolved_identity.request_digest != request.request_digest():
        return None
    if store_dir.resolve() != _store_dir(cache_root, resolved_identity.digest).resolve():
        return None
    return WOfSCacheHandle(
        path=store_dir,
        identity=resolved_identity.digest,
        request_digest=request.request_digest(),
    )


def resolve_cached_request(
    cache_root: Path, request: WOfSCacheRequest, *, offline: bool
) -> WOfSCacheHandle | None:
    """Look up a completed cache for ``request`` using only the local index.

    Reads ``cache_root / "index" / f"{request_digest}.json"`` and, if
    present, validates it against the store's own manifest (see
    :func:`_validate_hit`) before returning a handle. Never touches the
    network regardless of ``offline`` -- the flag is accepted (and required
    ``True`` by every current caller in this module) so that call sites
    stay self-documenting about which lookups are network-free; a future
    ``offline=False`` mode that also checks a remote catalog is out of
    scope for this task.

    Returns ``None`` on any miss: no index entry, an entry that fails
    validation, or a store manifest that cannot be read.
    """
    cache_root = Path(cache_root)
    index_entry = _read_json(_index_path(cache_root, request.request_digest()))
    if index_entry is None:
        return None
    return _validate_hit(cache_root, index_entry, request)


def require_cached_request(
    cache_root: Path, request: WOfSCacheRequest, *, offline: bool
) -> WOfSCacheHandle:
    """Like :func:`resolve_cached_request`, but raise on a miss.

    Raises ``FileNotFoundError`` naming the full requested date range, so an
    offline run that hits a missing/incomplete cache fails with an
    actionable message instead of a bare ``None`` a caller might not check.
    """
    handle = resolve_cached_request(cache_root, request, offline=offline)
    if handle is None:
        raise FileNotFoundError(
            "no cached WOfS store found for request "
            f"{request.request_digest()} covering {request.start_date} to "
            f"{request.end_date} (cache_root={Path(cache_root)!s}, offline={offline})"
        )
    return handle


def preflight_cache_space(
    path: Path, *, shape: tuple[int, int], months: int, headroom: float = 1.5
) -> int:
    """Require enough free disk space at ``path`` for a projected cache write.

    Projects ``height * width * months`` single-byte (``int8``) mask pixels
    -- the on-disk footprint of the canonical WOfS mask array before any
    Zarr compression -- and requires ``ceil(projected_bytes * headroom)``
    bytes free, via ``shutil.disk_usage``. This is deliberately conservative
    (pre-compression, whole-grid) and deliberately cheap (no filesystem scan
    beyond ``disk_usage``): callers run it before any network/read work so
    an undersized disk fails immediately rather than mid-write.

    Raises ``OSError`` if free space is insufficient. Returns the required
    byte count on success.
    """
    height, width = shape
    projected_bytes = int(height) * int(width) * int(months) * np.dtype("int8").itemsize
    required_bytes = math.ceil(projected_bytes * headroom)
    usage = shutil.disk_usage(path)
    if usage.free < required_bytes:
        raise OSError(
            f"insufficient disk space at {Path(path)!s}: cache requires "
            f"{required_bytes:,} bytes ({headroom:g}x headroom over a projected "
            f"{projected_bytes:,} bytes) but only {usage.free:,} bytes are free"
        )
    return required_bytes


def preflight_request_space(
    path: Path,
    aoi,
    *,
    crs: str,
    resolution: float,
    months: int,
    headroom: float = 1.5,
) -> int:
    """Conservative pre-STAC disk-space check from the AOI's bounding box alone.

    Loads/reprojects ``aoi`` locally to ``crs`` (via
    :func:`hydroseason._io_geo.load_aoi`) and estimates a *conservative*
    pixel shape from its bounding box: ``ceil(span / resolution)`` pixels
    per axis, which is always at least as large as whatever exact geometry
    STAC/the planner eventually resolve to (a bbox strictly contains its
    geometry). That shape is then passed to :func:`preflight_cache_space`.

    Purely local geometry math: this function never queries STAC or opens a
    COG, so it can run before :func:`hydroseason._io_geo._query_wofs_items`
    and fail fast on an obviously-undersized disk. A second, exact check
    against the planner's actual de-duplicated windows happens later (after
    STAC resolution), in a subsequent task -- not implemented here.
    """
    from hydroseason._io_geo import load_aoi

    aoi_gdf = load_aoi(aoi, to_crs=crs)
    minx, miny, maxx, maxy = (float(v) for v in aoi_gdf.total_bounds)
    width = math.ceil((maxx - minx) / resolution)
    height = math.ceil((maxy - miny) / resolution)
    return preflight_cache_space(path, shape=(height, width), months=months, headroom=headroom)


@dataclasses.dataclass(frozen=True)
class AnnualWriteStats:
    """What :func:`write_annual_group` actually did for one calendar year.

    ``chunks_considered`` is every de-duplicated ``(time, y_start, x_start)``
    storage-grid cell the planner windows touch for this year;
    ``chunks_written`` is the subset that was not wholly ``-2`` (outside AOI)
    and so was actually assigned into the Zarr array -- Zarr's
    ``write_empty_chunks: False`` encoding then means an unwritten chunk has
    no on-disk chunk file at all. ``loaded_pixels`` sums the pixel count of
    every computed block (considered, not just written), so it reflects real
    Dask compute volume rather than an AOI polygon-area estimate.
    ``item_digest`` is a stable hash over the STAC ``item_ids`` this year's
    write claims to be built from, recorded for later provenance/validation
    (see :func:`validate_annual_group`).
    """

    year: int
    task_count: int
    chunks_considered: int
    chunks_written: int
    loaded_pixels: int
    item_digest: str
    compute_seconds: float = 0.0
    encode_write_seconds: float = 0.0
    validation_seconds: float = 0.0



def _item_digest(item_ids: tuple[str, ...]) -> str:
    return _sha256_digest({"item_ids": list(item_ids)})


def _years_dir(store_path: Path) -> Path:
    return Path(store_path) / _YEARS_DIRNAME


def _year_dir(store_path: Path, year: int) -> Path:
    return _years_dir(store_path) / str(int(year))


_WINDOWS_EXTENDED_PATH_PREFIX = "\\\\?\\"


def _long_path(path: Path) -> str:
    """A Windows path string safe from the legacy 260-character ``MAX_PATH`` limit.

    ``cache_root / "stores" / <64-char sha256 digest> / "years" / ...`` can
    exceed ``MAX_PATH`` on Windows once a caller's own ``cache_root`` is
    itself nested a few directories deep (this is common in tests, whose
    ``tmp_path`` fixtures add their own long, nested prefix) -- and most
    Windows installs do not have the opt-in ``LongPathsEnabled`` registry
    value set, so plain long paths simply fail with ``FileNotFoundError``.
    Prefixing an *absolute* path with ``\\\\?\\`` asks Win32 to bypass
    ``MAX_PATH`` for that call, without requiring any system-level opt-in.
    A no-op on non-Windows platforms and on already-prefixed paths.
    """
    absolute = os.path.abspath(str(path))
    if os.name != "nt" or absolute.startswith(_WINDOWS_EXTENDED_PATH_PREFIX):
        return absolute
    return _WINDOWS_EXTENDED_PATH_PREFIX + absolute


class _LongPathDirectoryStore:
    """A Zarr v2 ``DirectoryStore`` usable past Windows' ``MAX_PATH`` limit.

    Delegates to ``zarr.storage.DirectoryStore`` rooted at a
    :func:`_long_path`-prefixed path, and normalises every storage key
    (Zarr uses ``/``-separated keys like ``"water_mask/.zarray"`` for
    nested arrays) to the native separator before delegating. This second
    part matters specifically because of the first: an ordinary (non
    ``\\\\?\\``-prefixed) Windows path lets the OS silently accept a mixed
    ``\\``/``/`` path, but the ``\\\\?\\`` extended-length form is passed to
    Win32 verbatim and rejects any forward slash with ``WinError 123``.
    """

    def __init__(self, path):
        import zarr

        self._store = zarr.storage.DirectoryStore(_long_path(Path(path)))

    @staticmethod
    def _native_key(key):
        return key.replace("/", os.sep) if key else key

    def __getattr__(self, name):
        return getattr(self._store, name)

    def __getitem__(self, key):
        return self._store[self._native_key(key)]

    def __setitem__(self, key, value):
        self._store[self._native_key(key)] = value

    def __delitem__(self, key):
        del self._store[self._native_key(key)]

    def __contains__(self, key):
        return self._native_key(key) in self._store

    def __iter__(self):
        return iter(self._store)

    def __len__(self):
        return len(self._store)

    def listdir(self, path=None):
        return self._store.listdir(self._native_key(path) if path else path)

    def rmdir(self, path=None):
        return self._store.rmdir(self._native_key(path) if path else path)


def _zarr_store(path: Path):
    """A Zarr store for ``path`` that works past Windows' ``MAX_PATH`` limit.

    Every call site in this module that opens or writes a Zarr *directory*
    (as opposed to JSON sidecar files, which go through
    :func:`_write_json_atomic`/plain ``Path`` I/O) should route through this
    rather than passing a bare path/string to ``zarr``/``xarray`` directly,
    so long cache-root paths keep working uniformly. A no-op wrapper on
    non-Windows platforms (:class:`_LongPathDirectoryStore` degrades to a
    plain, unprefixed ``DirectoryStore`` there).
    """
    return _LongPathDirectoryStore(path)


def _storage_chunk_starts(start: int, stop: int, chunk: int = _STORAGE_CHUNK) -> list[int]:
    """Storage-grid chunk starts (multiples of ``chunk``) covering ``[start, stop)``."""
    first = (start // chunk) * chunk
    return list(range(first, stop, chunk))


def _handle_request_dict(handle: "WOfSCacheHandle") -> dict:
    """The raw ``request`` dict recorded in ``handle``'s store manifest.

    Used to look up ``historical_mask_pixel_count`` (and, in principle, any
    other request field) without requiring callers to thread the original
    :class:`WOfSCacheRequest` through every writer call -- the manifest
    written by :func:`create_cache_handle` already carries it. Returns an
    empty dict if the manifest or its ``identity``/``request`` block is
    missing/malformed, matching :func:`_store_year_time_axis`'s existing
    tolerant read of the same manifest path.
    """
    manifest = _read_json(Path(handle.path) / _MANIFEST_FILENAME) or {}
    identity = manifest.get("identity") or {}
    request = identity.get("request") or {}
    return request if isinstance(request, dict) else {}


def _check_historical_mask_count_invariants(
    handle: "WOfSCacheHandle",
    *,
    year: int,
    n_aoi_cnt,
    n_valid_cnt,
    n_water_cnt,
    n_invalid_cnt,
) -> None:
    """Enforce, for every month in ``year``, the three count invariants:

    ``n_water <= n_valid``, ``n_valid + n_invalid == n_aoi`` always; and
    ``n_aoi == historical_mask_pixel_count`` ONLY when the store's own
    request pins a historical mask (``historical_mask_pixel_count is not
    None`` in the manifest's recorded request) -- a request with no
    historical mask (the pre-Task-4, still-supported shape) has no pinned
    scientific denominator to compare against, so that third check is
    skipped entirely for it, exactly as it always behaved before this task.

    Raises ``ValueError`` naming the year and the first violated invariant
    on any mismatch -- a store whose actually-written pixels disagree with
    its own pinned denominator is corrupt and must fail loudly rather than
    silently cache a wrong count.
    """
    n_aoi_cnt = np.asarray(n_aoi_cnt)
    n_valid_cnt = np.asarray(n_valid_cnt)
    n_water_cnt = np.asarray(n_water_cnt)
    n_invalid_cnt = np.asarray(n_invalid_cnt)

    if bool((n_water_cnt > n_valid_cnt).any()):
        raise ValueError(
            f"annual group for year {year} violates n_water <= n_valid for at "
            "least one month (corrupt write)"
        )
    if bool((n_valid_cnt + n_invalid_cnt != n_aoi_cnt).any()):
        raise ValueError(
            f"annual group for year {year} violates n_valid + n_invalid == n_aoi "
            "for at least one month (corrupt write)"
        )

    request = _handle_request_dict(handle)
    historical_mask_pixel_count = request.get("historical_mask_pixel_count")
    if historical_mask_pixel_count is None:
        return
    expected = int(historical_mask_pixel_count)
    if bool((n_aoi_cnt != expected).any()):
        bad_values = sorted({int(v) for v in n_aoi_cnt[n_aoi_cnt != expected]})
        raise ValueError(
            f"annual group for year {year} violates n_aoi == historical_mask_pixel_count "
            f"({expected}) for at least one month: observed n_aoi value(s) {bad_values}"
        )


def _mask_template(mask, year: int) -> "object":
    """An eager-coords, lazy-data ``xr.Dataset`` describing one year's annual group.

    ``mask`` already carries the full (possibly multi-year) time axis; this
    template narrows to ``year`` only, keeps ``time``/``y``/``x`` coordinates
    eager (so ``to_zarr(..., compute=False)`` can write real metadata without
    computing any pixels), and replaces the data variable with a Dask
    ``empty`` array of the same shape/dtype/chunking so the call only
    initialises the store layout.
    """
    import dask.array as da
    import xarray as xr

    year_mask = mask.sel(time=slice(f"{year}-01-01", f"{year}-12-31"))
    height = year_mask.sizes["y"]
    width = year_mask.sizes["x"]
    time_len = year_mask.sizes["time"]
    empty = da.empty((time_len, height, width), dtype=np.int8, chunks=MASK_CHUNKS)
    template = xr.DataArray(
        empty,
        dims=("time", "y", "x"),
        coords={
            "time": year_mask.time.values,
            "y": year_mask.y.values,
            "x": year_mask.x.values,
        },
        name="water_mask",
    )
    crs = year_mask.rio.crs
    if crs is not None:
        template = template.rio.write_crs(crs)
    template = template.rio.write_transform(year_mask.rio.transform())
    return xr.Dataset({"water_mask": template}), year_mask


def _compute_with_remote_read_retries(
    compute_fn, *args, retries: int = 3, retry_delay: float = 1.0, **kwargs
):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return compute_fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(retry_delay)
            else:
                raise last_exc


def write_annual_group(
    handle: WOfSCacheHandle,
    year: int,
    mask,
    *,
    windows: tuple,
    item_ids: tuple[str, ...],
    overwrite: bool = False,
    compute_batch_size: int = 16,
    read_workers: int | None = None,
    dual_counts=None,
) -> AnnualWriteStats:
    """Materialise one calendar year of ``mask`` into a completed annual Zarr group.

    ``dual_counts``, when given (only ever passed for
    ``composite_bundle="hydrofragments_v1"`` -- see
    :func:`hydroseason._io_geo._load_wofs_items`'s
    ``hydrofragments_dual_counts`` attribute), is an already-reduced lazy
    ``(time, y, x)`` ``xr.Dataset`` with ``wet_count``/``clear_count``
    ``uint16`` variables for the SECONDARY (any-day-wet ``max_water``)
    composite, one plane per month, aligned to ``mask``'s own time axis.
    This function performs NO further spatial reduction of its own beyond
    summing each already-reduced count plane over ``(y, x)`` into one
    per-month scalar (mirroring exactly how ``n_water``/``n_valid``/etc. are
    already derived from the PRIMARY composite's written blocks below) --
    the caller (:mod:`hydroseason._io_geo`) already did the pixel-level
    reduction. When given, the per-month scalars are written to a parallel
    ``years/<year>/dual_extent_counts.json`` sidecar (see
    :data:`WOFS_CACHE_SCHEMA_VERSION`/:func:`_sha256_digest`, same
    conventions as ``extent_counts.json``). ``dual_counts=None`` (the
    default, and the ONLY value ever passed for
    ``composite_bundle="legacy"``) performs zero extra computation and
    writes no such file -- this function's every other output stays
    byte-for-byte identical to before ``dual_counts`` existed.
    """
    if compute_batch_size < 1:
        raise ValueError("compute_batch_size must be at least 1")
    if read_workers is not None and read_workers < 1:
        raise ValueError("read_workers must be positive or None")

    import shutil as _shutil

    import zarr
    from numcodecs import Blosc

    store_path = Path(handle.path)
    years_dir = _years_dir(store_path)
    Path(_long_path(years_dir)).mkdir(parents=True, exist_ok=True)
    final_year_path = _year_dir(store_path, year)
    if Path(_long_path(final_year_path)).exists() and not overwrite:
        raise FileExistsError(
            f"annual group for year {year} already exists at {final_year_path} "
            "(pass overwrite=True to replace it)"
        )

    temp_path = years_dir / f".{int(year)}.incomplete-{uuid.uuid4().hex}"
    Path(_long_path(temp_path)).mkdir(parents=True, exist_ok=True)

    try:
        dataset, year_mask = _mask_template(mask, year)

        compressor = Blosc(cname="zstd", clevel=1, shuffle=Blosc.BITSHUFFLE)
        encoding = {
            "water_mask": {
                "dtype": "int8",
                "chunks": MASK_CHUNKS,
                "compressor": compressor,
                "_FillValue": -2,
                "write_empty_chunks": False,
            }
        }
        dataset.to_zarr(
            _zarr_store(temp_path), mode="w", compute=False, consolidated=False, encoding=encoding
        )

        height = year_mask.sizes["y"]
        width = year_mask.sizes["x"]
        time_len = year_mask.sizes["time"]

        group = zarr.open_group(_zarr_store(temp_path), mode="r+")
        mask_array = group["water_mask"]

        # wet_count/clear_count are local derived arrays (not public source
        # data). Keep them chunked in Zarr, not full-grid in memory.
        derived_arrays = {}
        for derived_name in ("wet_count", "clear_count"):
            derived_array = group.create_dataset(
                derived_name,
                shape=(height, width),
                dtype=np.uint16,
                chunks=(_STORAGE_CHUNK, _STORAGE_CHUNK),
                fill_value=0,
                overwrite=True,
            )
            derived_array.attrs["_ARRAY_DIMENSIONS"] = ["y", "x"]
            derived_arrays[derived_name] = derived_array

        spatial_keys: set[tuple[int, int]] = set()
        for window in windows:
            y_start = max(0, window.y_start)
            y_stop = min(height, window.y_stop)
            x_start = max(0, window.x_start)
            x_stop = min(width, window.x_stop)
            if y_start >= y_stop or x_start >= x_stop:
                continue
            y_starts = _storage_chunk_starts(y_start, y_stop)
            x_starts = _storage_chunk_starts(x_start, x_stop)
            for cy in y_starts:
                for cx in x_starts:
                    spatial_keys.add((cy, cx))

        task_count = 0
        chunks_considered = len(spatial_keys) * time_len
        chunks_written = 0
        loaded_pixels = 0
        compute_seconds = 0.0
        encode_write_seconds = 0.0
        validation_seconds = 0.0
        n_aoi_cnt = np.zeros(time_len, dtype=np.int64)
        n_valid_cnt = np.zeros(time_len, dtype=np.int64)
        n_water_cnt = np.zeros(time_len, dtype=np.int64)
        n_invalid_cnt = np.zeros(time_len, dtype=np.int64)
        written_chunk_keys_set: set[tuple[int, int, int]] = set()

        dual_year_counts = None
        if dual_counts is not None:
            dual_year_counts = dual_counts.sel(time=slice(f"{year}-01-01", f"{year}-12-31"))
            n_max_water_cnt = np.zeros(time_len, dtype=np.int64)
            n_max_clear_cnt = np.zeros(time_len, dtype=np.int64)

        content_hasher = _content_hasher()
        content_hasher.update(
            _canonical_json_bytes(
                {
                    "dtype": "int8",
                    "shape": [time_len, height, width],
                    "spatial_chunks": [list(key) for key in sorted(spatial_keys)],
                }
            )
        )

        import dask

        keys_list = sorted(spatial_keys)
        compute_kwargs = {}
        if read_workers is not None:
            compute_kwargs = {"scheduler": "threads", "num_workers": read_workers}

        for i in range(0, len(keys_list), compute_batch_size):
            batch_keys = keys_list[i : i + compute_batch_size]
            blocks_to_compute = []
            block_metadata = []
            dual_blocks_to_compute = []
            for cy, cx in batch_keys:
                cy_stop = min(cy + _STORAGE_CHUNK, height)
                cx_stop = min(cx + _STORAGE_CHUNK, width)
                block = year_mask.isel(
                    time=slice(0, time_len), y=slice(cy, cy_stop), x=slice(cx, cx_stop)
                ).data
                if hasattr(block, "__dask_graph__"):
                    task_count += len(block.__dask_graph__())
                blocks_to_compute.append(block)
                block_metadata.append((cy, cx, cy_stop, cx_stop))
                if dual_year_counts is not None:
                    # Ride the secondary composite's counts through the SAME
                    # dask.compute call as the primary blocks below, rather
                    # than triggering a second, independent Dask execution.
                    dual_slice = dual_year_counts.isel(
                        time=slice(0, time_len), y=slice(cy, cy_stop), x=slice(cx, cx_stop)
                    )
                    dual_blocks_to_compute.append(dual_slice["wet_count"].data)
                    dual_blocks_to_compute.append(dual_slice["clear_count"].data)

            compute_started = time.perf_counter()
            computed_all = _compute_with_remote_read_retries(
                dask.compute,
                *blocks_to_compute,
                *dual_blocks_to_compute,
                **compute_kwargs,
            )
            compute_seconds += time.perf_counter() - compute_started
            computed_blocks = computed_all[: len(blocks_to_compute)]
            computed_dual_blocks = computed_all[len(blocks_to_compute):]

            write_started = time.perf_counter()
            for block_idx, ((cy, cx, cy_stop, cx_stop), raw_val) in enumerate(
                zip(block_metadata, computed_blocks)
            ):
                values = np.asarray(raw_val)
                loaded_pixels += int(values.size)
                content_hasher.update(
                    _canonical_json_bytes(
                        {"y_start": cy, "x_start": cx, "shape": list(values.shape)}
                    )
                )
                # dask.compute already returns C-contiguous arrays here, so
                # ascontiguousarray was allocating a full second copy of every
                # block. Assert-and-use instead of copy-always; the fallback
                # covers any future non-contiguous producer.
                content_hasher.update(
                    values.tobytes() if values.flags["C_CONTIGUOUS"]
                    else np.ascontiguousarray(values).tobytes()
                )

                invalid_domain = ~np.isin(values, CANONICAL_VALUES)
                if invalid_domain.any():
                    bad = sorted({int(v) for v in np.unique(values[invalid_domain])})
                    raise ValueError(
                        f"mask contains values outside the canonical domain {CANONICAL_VALUES}: {bad}"
                    )

                block_water = (values == 1).sum(axis=(1, 2), dtype=np.int64)
                block_dry = (values == 0).sum(axis=(1, 2), dtype=np.int64)
                block_aoi = (values != -2).sum(axis=(1, 2), dtype=np.int64)
                n_water_cnt += block_water
                n_valid_cnt += block_water + block_dry
                n_aoi_cnt += block_aoi
                n_invalid_cnt += block_aoi - block_water - block_dry

                if dual_year_counts is not None:
                    dual_wet_raw = np.asarray(computed_dual_blocks[2 * block_idx])
                    dual_clear_raw = np.asarray(computed_dual_blocks[2 * block_idx + 1])
                    n_max_water_cnt += dual_wet_raw.sum(axis=(1, 2), dtype=np.int64)
                    n_max_clear_cnt += dual_clear_raw.sum(axis=(1, 2), dtype=np.int64)

                if bool((values == -2).all()):
                    continue

                for t in range(time_len):
                    plane = values[t]
                    if bool((plane == -2).all()):
                        continue
                    mask_array[t, cy:cy_stop, cx:cx_stop] = plane
                    chunks_written += 1
                    written_chunk_keys_set.add((t, cy // _STORAGE_CHUNK, cx // _STORAGE_CHUNK))

                wet_values = (values == 1).sum(axis=0).astype(np.uint16)
                clear_values = ((values == 0) | (values == 1)).sum(axis=0).astype(np.uint16)
                if bool(wet_values.any()):
                    derived_arrays["wet_count"][cy:cy_stop, cx:cx_stop] = wet_values
                if bool(clear_values.any()):
                    derived_arrays["clear_count"][cy:cy_stop, cx:cx_stop] = clear_values
            encode_write_seconds += time.perf_counter() - write_started

        digest = _item_digest(tuple(item_ids))
        time_values = pd.DatetimeIndex(np.asarray(year_mask.time.values))
        written_chunk_keys = [list(k) for k in sorted(written_chunk_keys_set)]

        _check_historical_mask_count_invariants(
            handle,
            year=year,
            n_aoi_cnt=n_aoi_cnt,
            n_valid_cnt=n_valid_cnt,
            n_water_cnt=n_water_cnt,
            n_invalid_cnt=n_invalid_cnt,
        )

        extent_counts_payload = {
            "schema_version": WOFS_CACHE_SCHEMA_VERSION,
            "year": int(year),
            "dates": [d.strftime("%Y-%m-%d") for d in time_values],
            "n_aoi": n_aoi_cnt.tolist(),
            "n_valid": n_valid_cnt.tolist(),
            "n_water": n_water_cnt.tolist(),
            "n_invalid": n_invalid_cnt.tolist(),
        }
        extent_counts_payload["content_digest"] = _sha256_digest(extent_counts_payload)
        _write_json_atomic(temp_path / "extent_counts.json", extent_counts_payload)

        if dual_year_counts is not None:
            # Fixed, per-store reference-area denominators (task W2.3):
            # full-AOI pixel count is the entire requested catchment,
            # constant regardless of pruning; analysis-mask pixel count is
            # the (possibly pruned) footprint that actually gated reads for
            # THIS store. Both are already persisted in the store's root
            # manifest by record_cache_footprints (called by
            # acquire_wofs_cache before any year is written), so they are
            # read back here rather than re-derived -- never conflated with
            # the per-month n_aoi count above, which is a *content* count
            # over the actually-written pixels, not this fixed geometry
            # denominator.
            footprints = read_cache_footprints(handle)
            dual_extent_counts_payload = {
                "schema_version": WOFS_CACHE_SCHEMA_VERSION,
                "year": int(year),
                "dates": [d.strftime("%Y-%m-%d") for d in time_values],
                "aoi_pixel_count": int(footprints.aoi_pixel_count),
                "analysis_mask_pixel_count": int(footprints.analysis_pixel_count),
                "n_max_water": n_max_water_cnt.tolist(),
                "n_median_water": n_water_cnt.tolist(),
                "n_valid_analysis": n_max_clear_cnt.tolist(),
            }
            dual_extent_counts_payload["content_digest"] = _sha256_digest(dual_extent_counts_payload)
            _write_json_atomic(temp_path / "dual_extent_counts.json", dual_extent_counts_payload)

        complete_payload = {
            "schema_version": WOFS_CACHE_SCHEMA_VERSION,
            "year": int(year),
            "start_date": time_values[0].strftime("%Y-%m-%d"),
            "end_date": time_values[-1].strftime("%Y-%m-%d"),
            "month_count": int(len(time_values)),
            "item_ids": list(item_ids),
            "item_digest": digest,
            "content_digest": content_hasher.hexdigest(),
            "chunks_considered": chunks_considered,
            "chunks_written": chunks_written,
            "loaded_pixels": loaded_pixels,
            "written_chunk_keys": written_chunk_keys,
        }
        _write_json_atomic(temp_path / _COMPLETE_FILENAME, complete_payload)

        expected_shape = (time_len, height, width)
        expected_transform = tuple(year_mask.rio.transform())[:6]
        validation_started = time.perf_counter()
        validate_annual_group(
            temp_path,
            expected_year=year,
            expected_shape=expected_shape,
            expected_transform=expected_transform,
        )
        validation_seconds = time.perf_counter() - validation_started

        del mask_array, group, derived_arrays
        import gc

        gc.collect()
        if Path(_long_path(final_year_path)).exists():
            _shutil.rmtree(_long_path(final_year_path))
        os.rename(_long_path(temp_path), _long_path(final_year_path))
    except BaseException:
        _shutil.rmtree(_long_path(temp_path), ignore_errors=True)
        raise

    _record_completed_year(store_path, year)

    return AnnualWriteStats(
        year=int(year),
        task_count=task_count,
        chunks_considered=chunks_considered,
        chunks_written=chunks_written,
        loaded_pixels=loaded_pixels,
        item_digest=digest,
        compute_seconds=compute_seconds,
        encode_write_seconds=encode_write_seconds,
        validation_seconds=validation_seconds,
    )


def write_empty_annual_group(
    handle: WOfSCacheHandle,
    year: int,
    mask,
    *,
    overwrite: bool = False,
    dual_extent_counts: bool = False,
) -> AnnualWriteStats:
    """Write a completed annual group for a year with no source observations.

    When STAC returned no items for ``year`` and the store's request pins NO
    historical mask, every pixel of every month is ``-2`` (outside/no-data)
    by construction. ``write_annual_group`` would still compute and hash
    every 512px block to discover that, then write none of them -- pure
    waste proportional to AOI area. This produces the identical on-disk
    group directly: the same Zarr layout, the same all-zero
    ``wet_count``/``clear_count``, the same zeroed ``extent_counts.json``,
    and a ``complete.json`` carrying an empty ``item_ids``.
    ``validate_annual_group`` accepts the result unchanged.

    When the store's request DOES pin a historical mask
    (``historical_mask_pixel_count`` set -- see
    :func:`hydroseason._io_wofs_acquire.acquire_wofs_cache`), a missing
    year's pixels are NOT uniformly ``-2``: every cell inside the exact
    historical mask is ``-1`` (invalid -- inside the fixed AOI, but no
    source observation this month), matching
    :func:`hydroseason._io_wofs_acquire._empty_year_mask`'s own contract, so
    the constant ``n_aoi == historical_mask_pixel_count`` denominator holds
    for a missing year exactly like it does for a normal one. This reads the
    verified analysis-mask sidecar (:func:`read_cache_analysis_mask`, which
    :func:`hydroseason._io_wofs_acquire.acquire_wofs_cache` always records
    before calling this function whenever a historical mask is pinned) and
    writes its ``-1``-inside/``-2``-outside pattern into every month's
    ``water_mask`` plane directly (still zero STAC/network access -- this is
    pure in-memory raster writing, not a monthly composite), with
    ``n_aoi``/``n_invalid`` set to ``historical_mask_pixel_count`` and
    ``n_valid``/``n_water`` left at ``0`` (no source observation exists this
    month, so nothing can be classified wet or dry).

    ``dual_extent_counts=True`` (only ever passed for
    ``composite_bundle="hydrofragments_v1"``) additionally writes a zeroed
    ``years/<year>/dual_extent_counts.json`` sidecar -- an empty year has no
    observations for EITHER composite, so both are legitimately all-zero,
    keeping the artifact's presence consistent whether or not a given year
    actually had source items. ``dual_extent_counts=False`` (the default,
    and the only value ever passed for ``composite_bundle="legacy"``) writes
    no such file.
    """
    import shutil as _shutil

    import zarr
    from numcodecs import Blosc

    store_path = Path(handle.path)
    years_dir = _years_dir(store_path)
    Path(_long_path(years_dir)).mkdir(parents=True, exist_ok=True)
    final_year_path = _year_dir(store_path, year)
    if Path(_long_path(final_year_path)).exists() and not overwrite:
        raise FileExistsError(
            f"annual group for year {year} already exists at {final_year_path} "
            "(pass overwrite=True to replace it)"
        )

    temp_path = years_dir / f".{int(year)}.incomplete-{uuid.uuid4().hex}"
    Path(_long_path(temp_path)).mkdir(parents=True, exist_ok=True)

    try:
        dataset, year_mask = _mask_template(mask, year)

        compressor = Blosc(cname="zstd", clevel=1, shuffle=Blosc.BITSHUFFLE)
        encoding = {
            "water_mask": {
                "dtype": "int8",
                "chunks": MASK_CHUNKS,
                "compressor": compressor,
                "_FillValue": -2,
                "write_empty_chunks": False,
            }
        }
        dataset.to_zarr(
            _zarr_store(temp_path), mode="w", compute=False, consolidated=False, encoding=encoding
        )

        height = year_mask.sizes["y"]
        width = year_mask.sizes["x"]
        time_len = year_mask.sizes["time"]

        group = zarr.open_group(_zarr_store(temp_path), mode="r+")
        # No data to write into water_mask: every chunk stays unwritten, which
        # with write_empty_chunks=False and _FillValue=-2 reads back as -2
        # everywhere -- exactly what the general path would have produced.
        for derived_name in ("wet_count", "clear_count"):
            derived_array = group.create_dataset(
                derived_name,
                shape=(height, width),
                dtype=np.uint16,
                chunks=(_STORAGE_CHUNK, _STORAGE_CHUNK),
                fill_value=0,
                overwrite=True,
            )
            derived_array.attrs["_ARRAY_DIMENSIONS"] = ["y", "x"]

        digest = _item_digest(())
        time_values = pd.DatetimeIndex(np.asarray(year_mask.time.values))
        zeros = [0] * time_len

        # A pinned historical mask means a missing year's pixels are NOT
        # uniformly -2: every cell inside the exact mask is -1 (invalid, no
        # source data this month -- see _empty_year_mask), so the fixed
        # n_aoi == historical_mask_pixel_count denominator must hold here
        # exactly like it does for a normal (item-bearing) year. Read the
        # verified on-disk copy of the exact mask (record_cache_analysis_mask
        # is always called before this function whenever a historical mask
        # is pinned -- see acquire_wofs_cache) rather than trusting `mask`'s
        # own (possibly mocked, in tests) values, so this stays correct even
        # when a caller substitutes a stand-in `mask` object.
        historical_mask_pixel_count = _handle_request_dict(handle).get(
            "historical_mask_pixel_count"
        )
        analysis_mask = (
            read_cache_analysis_mask(handle) if historical_mask_pixel_count is not None else None
        )

        mask_array = group["water_mask"]
        chunks_written = 0
        written_chunk_keys: list[list[int]] = []

        if analysis_mask is not None:
            inside = np.asarray(analysis_mask.mask, dtype=bool)
            if inside.shape != (height, width):
                raise ValueError(
                    f"annual group for year {year}: analysis-mask shape "
                    f"{inside.shape!r} does not match this store's grid "
                    f"{(height, width)!r}"
                )
            plane = np.full((height, width), -2, dtype=np.int8)
            plane[inside] = -1
            pixel_count = int(inside.sum())
            n_aoi_cnt = [pixel_count] * time_len
            n_invalid_cnt = [pixel_count] * time_len
            n_valid_cnt = list(zeros)
            n_water_cnt = list(zeros)

            content_hasher = _content_hasher()
            content_hasher.update(
                _canonical_json_bytes(
                    {
                        "dtype": "int8",
                        "shape": [time_len, height, width],
                        "spatial_chunks": [],
                    }
                )
            )
            for t in range(time_len):
                mask_array[t, :, :] = plane
                content_hasher.update(
                    _canonical_json_bytes({"y_start": 0, "x_start": 0, "shape": [1, height, width]})
                )
                content_hasher.update(
                    plane.tobytes() if plane.flags["C_CONTIGUOUS"]
                    else np.ascontiguousarray(plane).tobytes()
                )
                for cy in _storage_chunk_starts(0, height):
                    for cx in _storage_chunk_starts(0, width):
                        written_chunk_keys.append(
                            [t, cy // _STORAGE_CHUNK, cx // _STORAGE_CHUNK]
                        )
            chunks_written = len(written_chunk_keys)
        else:
            n_aoi_cnt = zeros
            n_valid_cnt = zeros
            n_water_cnt = zeros
            n_invalid_cnt = zeros

            content_hasher = _content_hasher()
            content_hasher.update(
                _canonical_json_bytes(
                    {
                        "dtype": "int8",
                        "shape": [time_len, height, width],
                        "spatial_chunks": [],
                    }
                )
            )

        _check_historical_mask_count_invariants(
            handle,
            year=year,
            n_aoi_cnt=n_aoi_cnt,
            n_valid_cnt=n_valid_cnt,
            n_water_cnt=n_water_cnt,
            n_invalid_cnt=n_invalid_cnt,
        )

        extent_counts_payload = {
            "schema_version": WOFS_CACHE_SCHEMA_VERSION,
            "year": int(year),
            "dates": [d.strftime("%Y-%m-%d") for d in time_values],
            "n_aoi": list(n_aoi_cnt),
            "n_valid": list(n_valid_cnt),
            "n_water": list(n_water_cnt),
            "n_invalid": list(n_invalid_cnt),
        }
        extent_counts_payload["content_digest"] = _sha256_digest(extent_counts_payload)
        _write_json_atomic(temp_path / "extent_counts.json", extent_counts_payload)

        if dual_extent_counts:
            footprints = read_cache_footprints(handle)
            dual_extent_counts_payload = {
                "schema_version": WOFS_CACHE_SCHEMA_VERSION,
                "year": int(year),
                "dates": [d.strftime("%Y-%m-%d") for d in time_values],
                "aoi_pixel_count": int(footprints.aoi_pixel_count),
                "analysis_mask_pixel_count": int(footprints.analysis_pixel_count),
                "n_max_water": list(zeros),
                "n_median_water": list(zeros),
                "n_valid_analysis": list(zeros),
            }
            dual_extent_counts_payload["content_digest"] = _sha256_digest(dual_extent_counts_payload)
            _write_json_atomic(temp_path / "dual_extent_counts.json", dual_extent_counts_payload)

        complete_payload = {
            "schema_version": WOFS_CACHE_SCHEMA_VERSION,
            "year": int(year),
            "start_date": time_values[0].strftime("%Y-%m-%d"),
            "end_date": time_values[-1].strftime("%Y-%m-%d"),
            "month_count": int(len(time_values)),
            "item_ids": [],
            "item_digest": digest,
            "content_digest": content_hasher.hexdigest(),
            "chunks_considered": chunks_written,
            "chunks_written": chunks_written,
            "loaded_pixels": 0,
            "written_chunk_keys": written_chunk_keys,
        }
        _write_json_atomic(temp_path / _COMPLETE_FILENAME, complete_payload)

        validate_annual_group(
            temp_path,
            expected_year=year,
            expected_shape=(time_len, height, width),
            expected_transform=tuple(year_mask.rio.transform())[:6],
        )

        del group
        import gc

        gc.collect()
        if Path(_long_path(final_year_path)).exists():
            _shutil.rmtree(_long_path(final_year_path))
        os.rename(_long_path(temp_path), _long_path(final_year_path))
    except BaseException:
        _shutil.rmtree(_long_path(temp_path), ignore_errors=True)
        raise

    _record_completed_year(store_path, year)

    return AnnualWriteStats(
        year=int(year),
        task_count=0,
        chunks_considered=chunks_written,
        chunks_written=chunks_written,
        loaded_pixels=0,
        item_digest=digest,
        compute_seconds=0.0,
        encode_write_seconds=0.0,
        validation_seconds=0.0,
    )


def _record_completed_year(store_path: Path, year: int) -> None:
    """Add ``year`` to the store's root manifest, preserving every other key.

    Read-modify-write via :func:`_write_json_atomic`: the manifest written
    by :func:`create_cache_handle` already exists (identity/request_digest),
    so this only appends to (or creates) its ``completed_years`` list --
    never touches the fields :func:`_validate_hit` depends on.
    """
    manifest_path = store_path / _MANIFEST_FILENAME
    manifest = _read_json(manifest_path) or {}
    completed = sorted(set(manifest.get("completed_years", [])) | {int(year)})
    manifest["completed_years"] = completed
    _write_json_atomic(manifest_path, manifest)


_FOOTPRINTS_KEY = "footprints"
_FOOTPRINTS_SCHEMA_VERSION = 1
# Fixed precision grid for canonical WKB serialisation, matching
# hydroseason._io_dea_stats.wet_mask_digest's convention exactly, so a
# geometry that round-trips through this module and through that one digests
# identically.
_GEOMETRY_PRECISION_GRID_SIZE = 0.001


@dataclasses.dataclass(frozen=True)
class CacheFootprints:
    """Persisted full-AOI and analysis-footprint geometry/counts/digests.

    ``aoi_geometry_wkb_hex``/``analysis_geometry_wkb_hex`` are canonical WKB
    (fixed 1e-3 precision, matching
    :func:`hydroseason._io_dea_stats.wet_mask_digest`'s convention) for the
    full user AOI and the (possibly identical, when no pruning applied)
    analysis footprint actually used to gate reads/writes. ``shape``/
    ``transform``/``crs`` describe the cache's grid these geometries were
    rasterized against. ``aoi_pixel_count``/``analysis_pixel_count`` are the
    exact pixel counts of each geometry rasterized onto that grid.
    ``aoi_digest``/``analysis_digest`` are SHA-256 digests over
    ``(crs, wkb)``, independent of anything else in the manifest, so a
    consumer (e.g. HydroFragments) can re-rasterize from the persisted WKB
    and cross-check both the digest and the pixel count without trusting
    either alone.

    ``aoi_pixel_count`` is the fixed reference-area denominator (APSEC/LPI
    per the plan's global constraints) and must be identical between a
    pruned and an unpruned cache covering the same catchment.
    ``analysis_pixel_count`` is the conservative potential-water footprint
    denominator (monthly coverage) and MAY legitimately differ between them.
    """

    aoi_geometry_wkb_hex: str
    analysis_geometry_wkb_hex: str
    crs: str
    shape: tuple[int, int]
    transform: tuple[float, float, float, float, float, float]
    aoi_pixel_count: int
    analysis_pixel_count: int
    aoi_digest: str
    analysis_digest: str

    def to_dict(self) -> dict:
        return {
            "schema_version": _FOOTPRINTS_SCHEMA_VERSION,
            "aoi_geometry_wkb_hex": self.aoi_geometry_wkb_hex,
            "analysis_geometry_wkb_hex": self.analysis_geometry_wkb_hex,
            "crs": self.crs,
            "shape": list(self.shape),
            "transform": list(self.transform),
            "aoi_pixel_count": int(self.aoi_pixel_count),
            "analysis_pixel_count": int(self.analysis_pixel_count),
            "aoi_digest": self.aoi_digest,
            "analysis_digest": self.analysis_digest,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "CacheFootprints":
        return cls(
            aoi_geometry_wkb_hex=payload["aoi_geometry_wkb_hex"],
            analysis_geometry_wkb_hex=payload["analysis_geometry_wkb_hex"],
            crs=payload["crs"],
            shape=(int(payload["shape"][0]), int(payload["shape"][1])),
            transform=tuple(float(v) for v in payload["transform"]),
            aoi_pixel_count=int(payload["aoi_pixel_count"]),
            analysis_pixel_count=int(payload["analysis_pixel_count"]),
            aoi_digest=payload["aoi_digest"],
            analysis_digest=payload["analysis_digest"],
        )


def _canonical_geometry_wkb_hex(gdf) -> str:
    """Canonical (fixed-precision, dissolved) WKB hex for one geometry column.

    Mirrors :func:`hydroseason._io_dea_stats.wet_mask_digest`'s geometry
    handling exactly (union to a single geometry, snap to a fixed 1e-3
    precision grid before serialising) so the same geometry always produces
    the same bytes regardless of shapely/geopandas version or how many rows
    the caller's GeoDataFrame happens to have.
    """
    import shapely
    from shapely import wkb

    geometry = (
        gdf.geometry.union_all()
        if hasattr(gdf.geometry, "union_all")
        else gdf.geometry.unary_union
    )
    geometry = shapely.set_precision(geometry, grid_size=_GEOMETRY_PRECISION_GRID_SIZE)
    return wkb.dumps(geometry).hex()


def _geometry_digest(crs: str, wkb_hex: str) -> str:
    """A stable SHA-256 over ``(crs, wkb_hex)``, independent of pixel counts.

    Kept separate from :data:`_sha256_digest`'s canonical-JSON convention
    (which is fine for plain JSON payloads) because the digest here must
    stay stable however the caller chooses to name/order surrounding
    manifest keys -- it only ever covers the geometry identity itself.
    """
    hasher = hashlib.sha256()
    hasher.update(str(crs).encode("utf-8"))
    hasher.update(bytes.fromhex(wkb_hex))
    return hasher.hexdigest()


def _rasterize_pixel_count(
    wkb_hex: str, *, shape: tuple[int, int], transform: tuple[float, ...]
) -> int:
    """Re-rasterize a canonical WKB geometry onto ``shape``/``transform`` and count True pixels.

    Uses ``rasterio.features.geometry_mask`` with ``invert=True`` (True
    inside the geometry) and ``all_touched=True`` -- the same rasterization
    primitive and touch convention :mod:`hydroseason._io_geo`'s own
    ``_inside_aoi_mask_like`` uses for AOI clipping, so a geometry
    round-tripped through this module counts pixels exactly the same way
    the acquisition path itself would have clipped them.
    """
    from affine import Affine
    from rasterio.features import geometry_mask
    from shapely import wkb

    geometry = wkb.loads(bytes.fromhex(wkb_hex))
    height, width = int(shape[0]), int(shape[1])
    affine_transform = Affine(*transform)
    inside = geometry_mask(
        [geometry],
        out_shape=(height, width),
        transform=affine_transform,
        invert=True,
        all_touched=True,
    )
    return int(np.count_nonzero(inside))


def record_cache_footprints(
    handle: WOfSCacheHandle,
    *,
    full_aoi_gdf,
    analysis_footprint_gdf,
    shape: tuple[int, int],
    transform: tuple[float, float, float, float, float, float],
    crs: str,
) -> CacheFootprints:
    """Persist full-AOI and analysis-footprint geometry/counts/digests atomically.

    ``full_aoi_gdf`` is the caller's full requested catchment (the fixed
    reference area APSEC/LPI denominators use per the plan's global
    constraints). ``analysis_footprint_gdf`` is the (possibly pruned, or --
    when no pruning was applied -- identical to ``full_aoi_gdf``) footprint
    actually used to gate which storage windows were read/written; it feeds
    the conservative potential-water ``analysis_mask`` denominator.

    Both geometries are canonicalised to fixed-precision WKB (see
    :func:`_canonical_geometry_wkb_hex`), rasterized onto ``shape``/
    ``transform`` to derive exact pixel counts (see
    :func:`_rasterize_pixel_count`), and digested independently of those
    counts (see :func:`_geometry_digest`) -- so a later reader
    (:func:`verify_cache_footprints`) can re-rasterize from the persisted
    WKB and cross-check both the digest and the pixel count, never trusting
    either alone.

    Written into the store's root ``manifest.json`` under a ``footprints``
    key via read-modify-write + :func:`_write_json_atomic`, mirroring
    :func:`_record_completed_year`'s pattern exactly: every other manifest
    key (``identity``/``request_digest``/``completed_years``/...) is
    preserved untouched.

    Because ``full_aoi_gdf`` is the SAME requested catchment for a pruned
    and an unpruned acquisition of that catchment, ``aoi_pixel_count`` is
    identical between the two regardless of pruning; ``analysis_pixel_count``
    reflects whichever footprint was actually used and so may legitimately
    differ.
    """
    aoi_wkb_hex = _canonical_geometry_wkb_hex(full_aoi_gdf)
    analysis_wkb_hex = _canonical_geometry_wkb_hex(analysis_footprint_gdf)
    crs_text = str(crs)
    shape_tuple = (int(shape[0]), int(shape[1]))
    transform_tuple = tuple(float(v) for v in transform)

    footprints = CacheFootprints(
        aoi_geometry_wkb_hex=aoi_wkb_hex,
        analysis_geometry_wkb_hex=analysis_wkb_hex,
        crs=crs_text,
        shape=shape_tuple,
        transform=transform_tuple,
        aoi_pixel_count=_rasterize_pixel_count(
            aoi_wkb_hex, shape=shape_tuple, transform=transform_tuple
        ),
        analysis_pixel_count=_rasterize_pixel_count(
            analysis_wkb_hex, shape=shape_tuple, transform=transform_tuple
        ),
        aoi_digest=_geometry_digest(crs_text, aoi_wkb_hex),
        analysis_digest=_geometry_digest(crs_text, analysis_wkb_hex),
    )

    manifest_path = Path(handle.path) / _MANIFEST_FILENAME
    manifest = _read_json(manifest_path) or {}
    manifest[_FOOTPRINTS_KEY] = footprints.to_dict()
    _write_json_atomic(manifest_path, manifest)

    return footprints


def read_cache_footprints(handle: WOfSCacheHandle) -> CacheFootprints:
    """Read back the :class:`CacheFootprints` persisted by :func:`record_cache_footprints`.

    Raises ``FileNotFoundError`` if the store has no manifest, or ``ValueError``
    if the manifest exists but carries no ``footprints`` block (e.g. a cache
    written before this task existed) or the block is malformed.
    """
    manifest_path = Path(handle.path) / _MANIFEST_FILENAME
    manifest = _read_json(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"no manifest found at {manifest_path}")
    payload = manifest.get(_FOOTPRINTS_KEY)
    if payload is None:
        raise ValueError(
            f"manifest at {manifest_path} has no '{_FOOTPRINTS_KEY}' metadata "
            "(cache was written before task W2.3, or record_cache_footprints "
            "was never called for it)"
        )
    try:
        return CacheFootprints.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"manifest at {manifest_path} has malformed '{_FOOTPRINTS_KEY}' metadata: {exc}"
        ) from exc


def verify_cache_footprints(handle: WOfSCacheHandle) -> CacheFootprints:
    """Read, independently re-rasterize, and verify persisted cache footprints.

    This is the tamper-detection entry point: it reads the persisted
    :class:`CacheFootprints` (:func:`read_cache_footprints`), then
    independently:

    1. Recomputes each geometry's digest from its persisted WKB and
       compares it against the persisted digest.
    2. Re-rasterizes each geometry from its persisted WKB onto the
       persisted ``shape``/``transform`` and compares the resulting pixel
       count against the persisted pixel count.

    Raises ``ValueError`` describing the first mismatch found -- a
    corrupted/hand-edited WKB string, a digest that no longer matches its
    geometry, or a pixel count that no longer matches what re-rasterizing
    the (otherwise valid) geometry actually produces. Never silently
    accepts a mismatch: this is what makes persisted geometry tamper-evident
    rather than merely informative.
    """
    footprints = read_cache_footprints(handle)

    for label, wkb_hex, expected_digest, expected_count in (
        ("aoi", footprints.aoi_geometry_wkb_hex, footprints.aoi_digest, footprints.aoi_pixel_count),
        (
            "analysis",
            footprints.analysis_geometry_wkb_hex,
            footprints.analysis_digest,
            footprints.analysis_pixel_count,
        ),
    ):
        try:
            recomputed_digest = _geometry_digest(footprints.crs, wkb_hex)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"cache footprint '{label}' geometry at {handle.path} is not valid WKB hex "
                f"(tampered or corrupted): {exc}"
            ) from exc
        if recomputed_digest != expected_digest:
            raise ValueError(
                f"cache footprint '{label}' digest mismatch at {handle.path}: "
                f"persisted digest {expected_digest!r} does not match the digest "
                f"recomputed from its persisted geometry {recomputed_digest!r} "
                "(tampered or corrupted manifest)"
            )
        recomputed_count = _rasterize_pixel_count(
            wkb_hex, shape=footprints.shape, transform=footprints.transform
        )
        if recomputed_count != expected_count:
            raise ValueError(
                f"cache footprint '{label}' pixel count mismatch at {handle.path}: "
                f"persisted count {expected_count} does not match the count "
                f"{recomputed_count} obtained by re-rasterizing its persisted "
                "geometry (tampered or corrupted manifest)"
            )

    return footprints


# --------------------------------------------------------------------------
# CacheAnalysisMask: a verified copy of the exact HistoricalWaterMask boolean
# raster, persisted under the WOfS store itself as
# ``analysis-mask/mask.zarr`` + ``analysis-mask/manifest.json``.
#
# This is deliberately a SEPARATE artifact from
# hydroseason._historical_water_mask's own ``historical-water-masks/``
# cache: that cache is keyed by AOI/product/stac_url/crs/resolution and can
# serve many different WOfS stores; this sidecar is a content-addressed COPY
# pinned to the one WOfS store it gates counts for, so a reader here never
# needs to know how to resolve/locate the other cache to verify a store's own
# scientific denominator. It also never serializes the mask to a polygon --
# only the exact grid-aligned boolean raster and its provenance -- mirroring
# CacheFootprints' analysis_geometry_wkb_hex/aoi_geometry_wkb_hex fields but
# for the raster case (a historical mask is never round-tripped through
# vector geometry, per hydroseason._historical_water_mask's own contract).
#
# Reuses hydroseason._historical_water_mask's already-established atomic-
# write, canonical-JSON-digest, mask-digest, and Windows-long-path Zarr
# helpers directly (via import) rather than reimplementing them a third
# time: _historical_water_mask.py never imports this module (see its own
# module docstring: "_io_dea_stats.build_planning_footprint_from_historical_mask
# depends on this module for HistoricalWaterMask/build_historical_water_mask,
# not the reverse"), so this module importing FROM it introduces no import
# cycle.
# --------------------------------------------------------------------------

_ANALYSIS_MASK_DIRNAME = "analysis-mask"
_ANALYSIS_MASK_ZARR_DIRNAME = "mask.zarr"
_ANALYSIS_MASK_MANIFEST_FILENAME = "manifest.json"


@dataclasses.dataclass(frozen=True)
class CacheAnalysisMask:
    """The exact historical water mask raster, as persisted under this WOfS store.

    Fields mirror :class:`hydroseason._historical_water_mask.HistoricalWaterMask`
    (minus ``aoi_sha256``, which belongs to that mask's own cache identity,
    not to this store-local copy). ``mask`` is the same 2D boolean array;
    everything else is the provenance :func:`verify_cache_analysis_mask`
    cross-checks against re-hashed/re-read on-disk bytes.
    """

    mask: Any
    crs: str
    transform: tuple[float, ...]
    shape: tuple[int, int]
    pixel_count: int
    source_product: str
    source_version: str
    source_item_ids: tuple[str, ...]
    source_lineage: tuple[str, ...]
    coverage_start: str
    coverage_end: str
    mask_sha256: str


def _analysis_mask_dir(store_path: Path) -> Path:
    return Path(store_path) / _ANALYSIS_MASK_DIRNAME


def _analysis_mask_manifest_payload(historical_mask) -> dict:
    payload = {
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
        "crs": str(historical_mask.crs),
        "transform": [float(v) for v in historical_mask.transform],
        "shape": [int(historical_mask.shape[0]), int(historical_mask.shape[1])],
        "pixel_count": int(historical_mask.pixel_count),
        "source_product": str(historical_mask.source_product),
        "source_version": str(historical_mask.source_version),
        "source_item_ids": list(historical_mask.source_item_ids),
        "source_lineage": list(historical_mask.source_lineage),
        "coverage_start": str(historical_mask.coverage_start),
        "coverage_end": str(historical_mask.coverage_end),
        "mask_sha256": str(historical_mask.mask_sha256),
    }
    # A digest over the FULL provenance record (product/version/item_ids/
    # lineage/coverage), not just the mask bytes -- _mask_digest (reused
    # below in _verify_analysis_mask_dir) only ever covers
    # crs/transform/shape/resolution/pixel-bytes, so a hand-edited
    # source_lineage/coverage_start/coverage_end/source_product/
    # source_version/source_item_ids field would otherwise pass mask-digest
    # verification untouched. content_digest closes that gap.
    payload["content_digest"] = _sha256_digest(payload)
    return payload


def record_cache_analysis_mask(handle: WOfSCacheHandle, historical_mask) -> CacheAnalysisMask:
    """Persist a verified copy of ``historical_mask`` under this WOfS store.

    ``historical_mask`` is a
    :class:`hydroseason._historical_water_mask.HistoricalWaterMask`. Writes
    ``analysis-mask/mask.zarr`` (a plain 2D boolean Zarr array, via
    :func:`hydroseason._historical_water_mask._zarr_store`, same long-path-safe
    convention as that module's own ``mask.zarr``) and
    ``analysis-mask/manifest.json`` to a sibling temporary directory first,
    verifies the freshly-written artifact against the in-memory mask (so a
    write-time bug can never publish a corrupt sidecar), then renames it into
    place atomically -- the same publish-only-after-verify pattern
    :func:`hydroseason._historical_water_mask.write_historical_water_mask`
    already established for its own artifact.

    Idempotent: calling this again with a byte-identical mask overwrites the
    sidecar with an identical result. Never serializes ``mask`` to a polygon
    -- only the exact grid-aligned boolean raster and its provenance.
    """
    import shutil as _shutil

    import numpy as _np
    import zarr

    from hydroseason._historical_water_mask import _long_path as _hwm_long_path
    from hydroseason._historical_water_mask import _write_json_atomic as _hwm_write_json_atomic
    from hydroseason._historical_water_mask import _zarr_store as _hwm_zarr_store

    store_path = Path(handle.path)
    final_dir = _analysis_mask_dir(store_path)
    temp_dir = _analysis_mask_dir(store_path).parent / (
        f".{_ANALYSIS_MASK_DIRNAME}.incomplete-{uuid.uuid4().hex}"
    )
    if Path(_hwm_long_path(temp_dir)).exists():
        _shutil.rmtree(_hwm_long_path(temp_dir))
    Path(_hwm_long_path(temp_dir)).mkdir(parents=True)
    try:
        mask_values = _np.ascontiguousarray(_np.asarray(historical_mask.mask, dtype=bool))
        zarr_path = temp_dir / _ANALYSIS_MASK_ZARR_DIRNAME
        array = zarr.open_array(
            _hwm_zarr_store(zarr_path), mode="w", shape=mask_values.shape, chunks=True, dtype=bool,
        )
        array[:] = mask_values

        manifest = _analysis_mask_manifest_payload(historical_mask)
        _hwm_write_json_atomic(temp_dir / _ANALYSIS_MASK_MANIFEST_FILENAME, manifest)

        _verify_analysis_mask_dir(temp_dir, expected_manifest=manifest, mask_values=mask_values)

        if Path(_hwm_long_path(final_dir)).exists():
            _shutil.rmtree(_hwm_long_path(final_dir))
        os.rename(_hwm_long_path(temp_dir), _hwm_long_path(final_dir))
    except BaseException:
        _shutil.rmtree(_hwm_long_path(temp_dir), ignore_errors=True)
        raise

    return CacheAnalysisMask(
        mask=mask_values,
        crs=str(historical_mask.crs),
        transform=tuple(float(v) for v in historical_mask.transform),
        shape=(int(historical_mask.shape[0]), int(historical_mask.shape[1])),
        pixel_count=int(historical_mask.pixel_count),
        source_product=str(historical_mask.source_product),
        source_version=str(historical_mask.source_version),
        source_item_ids=tuple(str(v) for v in historical_mask.source_item_ids),
        source_lineage=tuple(str(v) for v in historical_mask.source_lineage),
        coverage_start=str(historical_mask.coverage_start),
        coverage_end=str(historical_mask.coverage_end),
        mask_sha256=str(historical_mask.mask_sha256),
    )


def _verify_analysis_mask_dir(artifact_dir: Path, *, expected_manifest: dict, mask_values) -> None:
    """Recompute the mask digest/grid/pixel count from ``artifact_dir`` on disk
    and compare against ``expected_manifest``/``mask_values``.

    Raises ``ValueError("analysis mask cache verification failed")`` on any
    mismatch -- tampered raster bytes, a hand-edited manifest field
    (crs/transform/shape/source lineage/coverage/pixel count), or a
    manifest/array shape disagreement. Reuses
    :func:`hydroseason._historical_water_mask._mask_digest` exactly, so a
    mask digested here and one digested by that module's own cache agree
    byte-for-byte whenever the underlying raster and grid metadata agree.
    """
    import numpy as _np
    import zarr

    from hydroseason._historical_water_mask import _mask_digest as _hwm_mask_digest
    from hydroseason._historical_water_mask import _zarr_store as _hwm_zarr_store

    expected_content_digest = expected_manifest.get("content_digest")
    if expected_content_digest is not None:
        check_payload = {k: v for k, v in expected_manifest.items() if k != "content_digest"}
        if _sha256_digest(check_payload) != expected_content_digest:
            raise ValueError(
                "analysis mask cache verification failed: manifest content_digest "
                "does not match its own recorded fields (tampered or corrupted "
                "manifest -- product/version/item_ids/lineage/coverage/pixel_count "
                "no longer agree with the digest recorded alongside them)"
            )

    zarr_path = artifact_dir / _ANALYSIS_MASK_ZARR_DIRNAME
    try:
        array = zarr.open_array(_hwm_zarr_store(zarr_path), mode="r")
        on_disk = _np.asarray(array[:], dtype=bool)
    except Exception as exc:
        raise ValueError(
            "analysis mask cache verification failed: could not read "
            f"mask.zarr at {zarr_path}: {type(exc).__name__}: {exc}"
        ) from exc

    expected_shape = tuple(int(v) for v in expected_manifest["shape"])
    if tuple(on_disk.shape) != expected_shape:
        raise ValueError(
            "analysis mask cache verification failed: on-disk shape "
            f"{tuple(on_disk.shape)!r} does not match manifest shape {expected_shape!r}"
        )

    recomputed_pixel_count = int(on_disk.sum())
    if recomputed_pixel_count != int(expected_manifest["pixel_count"]):
        raise ValueError(
            "analysis mask cache verification failed: recomputed pixel_count "
            f"{recomputed_pixel_count} does not match manifest pixel_count "
            f"{expected_manifest['pixel_count']}"
        )

    recomputed_digest = _hwm_mask_digest(
        on_disk,
        crs=str(expected_manifest["crs"]),
        transform=tuple(expected_manifest["transform"]),
        shape=expected_shape,
        resolution=(
            abs(float(expected_manifest["transform"][0])),
            abs(float(expected_manifest["transform"][4])),
        ),
    )
    if recomputed_digest != expected_manifest["mask_sha256"]:
        raise ValueError(
            "analysis mask cache verification failed: recomputed mask digest "
            f"{recomputed_digest} does not match manifest mask_sha256 "
            f"{expected_manifest['mask_sha256']}"
        )

    if mask_values is not None and not _np.array_equal(on_disk, mask_values):
        raise ValueError(
            "analysis mask cache verification failed: on-disk mask bytes do "
            "not match the mask being persisted"
        )


def read_cache_analysis_mask(handle: WOfSCacheHandle) -> "CacheAnalysisMask | None":
    """Read back (WITHOUT verifying) the :class:`CacheAnalysisMask` persisted
    by :func:`record_cache_analysis_mask`, or ``None`` if none was ever
    recorded for this store.

    A miss (no ``analysis-mask/`` directory, or an unreadable/malformed
    manifest) returns ``None`` rather than raising -- this mirrors
    :func:`hydroseason._historical_water_mask.read_historical_water_mask`'s
    own miss-is-not-an-error convention. Callers that need tamper-evidence
    should use :func:`verify_cache_analysis_mask` instead (or in addition).
    """
    from hydroseason._historical_water_mask import _long_path as _hwm_long_path

    manifest_path = _analysis_mask_dir(Path(handle.path)) / _ANALYSIS_MASK_MANIFEST_FILENAME
    manifest = _read_json(manifest_path)
    if manifest is None:
        return None

    required_fields = (
        "crs", "transform", "shape", "pixel_count", "source_product", "source_version",
        "source_item_ids", "source_lineage", "coverage_start", "coverage_end", "mask_sha256",
    )
    if any(field not in manifest for field in required_fields):
        return None

    zarr_path = _analysis_mask_dir(Path(handle.path)) / _ANALYSIS_MASK_ZARR_DIRNAME
    if not Path(_hwm_long_path(zarr_path)).exists():
        return None

    try:
        import numpy as _np
        import zarr

        from hydroseason._historical_water_mask import _zarr_store as _hwm_zarr_store

        array = zarr.open_array(_hwm_zarr_store(zarr_path), mode="r")
        mask_values = _np.asarray(array[:], dtype=bool)
    except Exception:
        return None

    return CacheAnalysisMask(
        mask=mask_values,
        crs=str(manifest["crs"]),
        transform=tuple(float(v) for v in manifest["transform"]),
        shape=(int(manifest["shape"][0]), int(manifest["shape"][1])),
        pixel_count=int(manifest["pixel_count"]),
        source_product=str(manifest["source_product"]),
        source_version=str(manifest["source_version"]),
        source_item_ids=tuple(str(v) for v in manifest["source_item_ids"]),
        source_lineage=tuple(str(v) for v in manifest["source_lineage"]),
        coverage_start=str(manifest["coverage_start"]),
        coverage_end=str(manifest["coverage_end"]),
        mask_sha256=str(manifest["mask_sha256"]),
    )


def verify_cache_analysis_mask(handle: WOfSCacheHandle) -> CacheAnalysisMask:
    """Read, independently re-hash, and verify the persisted analysis mask.

    Raises ``FileNotFoundError`` if no ``analysis-mask/`` sidecar was ever
    recorded for this store (see :func:`record_cache_analysis_mask`), or
    ``ValueError("analysis mask cache verification failed: ...")`` describing
    the first mismatch found -- tampered raster bytes, a hand-edited
    manifest field, or a manifest/array shape disagreement (see
    :func:`_verify_analysis_mask_dir`). Never silently accepts a mismatch:
    this is what :func:`open_completed_extent_counts` relies on before
    trusting a scientifically pruned store's fixed denominator.
    """
    manifest_path = _analysis_mask_dir(Path(handle.path)) / _ANALYSIS_MASK_MANIFEST_FILENAME
    manifest = _read_json(manifest_path)
    if manifest is None:
        raise FileNotFoundError(
            f"no analysis-mask sidecar found for store at {handle.path} "
            "(record_cache_analysis_mask was never called for it)"
        )

    required_fields = (
        "crs", "transform", "shape", "pixel_count", "source_product", "source_version",
        "source_item_ids", "source_lineage", "coverage_start", "coverage_end", "mask_sha256",
    )
    missing = [field for field in required_fields if field not in manifest]
    if missing:
        raise ValueError(
            "analysis mask cache verification failed: manifest at "
            f"{manifest_path} is missing required fields {missing}"
        )

    artifact_dir = _analysis_mask_dir(Path(handle.path))
    _verify_analysis_mask_dir(artifact_dir, expected_manifest=manifest, mask_values=None)

    import numpy as _np
    import zarr

    from hydroseason._historical_water_mask import _zarr_store as _hwm_zarr_store

    array = zarr.open_array(_hwm_zarr_store(artifact_dir / _ANALYSIS_MASK_ZARR_DIRNAME), mode="r")
    mask_values = _np.asarray(array[:], dtype=bool)

    return CacheAnalysisMask(
        mask=mask_values,
        crs=str(manifest["crs"]),
        transform=tuple(float(v) for v in manifest["transform"]),
        shape=(int(manifest["shape"][0]), int(manifest["shape"][1])),
        pixel_count=int(manifest["pixel_count"]),
        source_product=str(manifest["source_product"]),
        source_version=str(manifest["source_version"]),
        source_item_ids=tuple(str(v) for v in manifest["source_item_ids"]),
        source_lineage=tuple(str(v) for v in manifest["source_lineage"]),
        coverage_start=str(manifest["coverage_start"]),
        coverage_end=str(manifest["coverage_end"]),
        mask_sha256=str(manifest["mask_sha256"]),
    )


def _read_georef(dataset) -> tuple["object", object, tuple[float, ...]]:
    """Recover ``water_mask``'s CRS/transform from a freshly-``xr.open_zarr``'d dataset.

    ``rio.write_crs`` records the CRS/transform link (``grid_mapping`` ->
    the ``spatial_ref`` scalar variable, plus that variable's
    ``GeoTransform`` attribute) on the in-memory ``.encoding``, which is not
    guaranteed to round-trip back onto the ``water_mask`` array's on-disk
    *attrs* through a bare ``to_zarr``/``open_zarr`` cycle (unlike
    ``rioxarray.open_rasterio``, plain ``xr.open_zarr`` does not run
    rioxarray's own CRS-detection machinery). The ``spatial_ref`` sibling
    variable's ``crs_wkt`` attribute is written by
    :func:`_mask_template`/``rio.write_crs`` regardless and is always
    present on a group this module wrote, so re-attaching it explicitly
    here is what makes CRS validation possible at all after a real
    Zarr round-trip.
    """
    import rioxarray  # noqa: F401

    mask_da = dataset["water_mask"]
    crs = mask_da.rio.crs
    if crs is None and "spatial_ref" in dataset:
        crs_wkt = dataset["spatial_ref"].attrs.get("crs_wkt")
        if crs_wkt:
            mask_da = mask_da.rio.write_crs(crs_wkt)
            crs = mask_da.rio.crs
    transform = tuple(mask_da.rio.transform())[:6]
    return mask_da, crs, transform


def _stored_chunk_count(array_path: Path) -> int:
    """Count physical Zarr v2 chunk files below an array directory."""
    root = Path(_long_path(array_path))
    if not root.exists():
        return 0
    count = 0
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        name = entry.name
        if name.startswith("."):
            continue
        try:
            tuple(int(part) for part in name.split("."))
        except ValueError:
            continue
        count += 1
    return count


def validate_annual_group(
    path: Path,
    *,
    expected_year: int,
    expected_shape: tuple[int, int, int],
    expected_transform: tuple[float, float, float, float, float, float],
) -> dict:
    """Validate a (possibly still-temporary) annual Zarr group before publishing it.

    Checks, in order: the path is a real Zarr group (``.zgroup`` present);
    the ``water_mask`` variable exists with ``int8`` dtype; every stored
    chunk's values lie in the canonical domain ``{-2, -1, 0, 1}``; the time
    axis has exactly 12 (or the year's requested partial-year count of)
    calendar-month timestamps, all within ``expected_year``, strictly
    increasing and unique; ``water_mask.shape == expected_shape`` and its
    chunk shape matches :data:`MASK_CHUNKS`; the group's CRS and affine
    transform match ``expected_transform``; and a ``complete.json`` item
    digest is present. Raises ``ValueError`` (or ``FileNotFoundError`` for a
    genuinely missing/corrupt group) describing the first failure found;
    returns the parsed ``complete.json`` payload on success.
    """
    import zarr

    path = Path(path)
    if not Path(_long_path(path / ".zgroup")).exists():
        raise FileNotFoundError(f"{path} is not a Zarr group (missing .zgroup)")

    try:
        group = zarr.open_group(_zarr_store(path), mode="r")
    except Exception as exc:
        raise ValueError(f"{path} could not be opened as a Zarr group: {exc}") from exc

    if "water_mask" not in group:
        raise ValueError(f"{path} is missing the 'water_mask' variable")
    mask_array = group["water_mask"]

    if mask_array.dtype != np.dtype("int8"):
        raise ValueError(
            f"water_mask dtype must be int8, got {mask_array.dtype} at {path}"
        )

    expected_time, expected_height, expected_width = expected_shape
    if tuple(mask_array.shape) != (expected_time, expected_height, expected_width):
        raise ValueError(
            f"water_mask shape {tuple(mask_array.shape)} does not match "
            f"expected {(expected_time, expected_height, expected_width)} at {path}"
        )
    if tuple(mask_array.chunks) != tuple(MASK_CHUNKS):
        raise ValueError(
            f"water_mask chunks {tuple(mask_array.chunks)} do not match "
            f"expected {tuple(MASK_CHUNKS)} at {path}"
        )

    complete_path = path / _COMPLETE_FILENAME
    complete_payload = _read_json(complete_path)
    if complete_payload is None:
        raise ValueError(f"{path} is missing a valid {_COMPLETE_FILENAME}")
    if not complete_payload.get("item_digest"):
        raise ValueError(f"{path} {_COMPLETE_FILENAME} is missing an item_digest")
    if int(complete_payload.get("year", -1)) != int(expected_year):
        raise ValueError(
            f"{path} {_COMPLETE_FILENAME} year {complete_payload.get('year')} "
            f"does not match expected {expected_year}"
        )
    expected_chunks_written = complete_payload.get("chunks_written")
    if expected_chunks_written is not None:
        actual_chunks_written = _stored_chunk_count(path / "water_mask")
        if actual_chunks_written != int(expected_chunks_written):
            raise ValueError(
                f"water_mask has {actual_chunks_written} stored chunks, expected "
                f"{expected_chunks_written} at {path}"
            )

    written_chunk_keys = complete_payload.get("written_chunk_keys")
    if written_chunk_keys is not None:
        for key in written_chunk_keys:
            t, cy_idx, cx_idx = key
            t0 = t * mask_array.chunks[0]
            y0 = cy_idx * mask_array.chunks[1]
            x0 = cx_idx * mask_array.chunks[2]
            values = mask_array[
                t0 : min(t0 + mask_array.chunks[0], expected_time),
                y0 : min(y0 + mask_array.chunks[1], expected_height),
                x0 : min(x0 + mask_array.chunks[2], expected_width),
            ]
            invalid_domain = ~np.isin(values, CANONICAL_VALUES)
            if invalid_domain.any():
                bad = sorted({int(v) for v in np.unique(values[invalid_domain])})
                raise ValueError(
                    f"water_mask contains values outside {CANONICAL_VALUES}: {bad} at {path}"
                )
    else:
        for t0 in range(0, expected_time, mask_array.chunks[0]):
            for y0 in range(0, expected_height, mask_array.chunks[1]):
                for x0 in range(0, expected_width, mask_array.chunks[2]):
                    values = mask_array[
                        t0 : min(t0 + mask_array.chunks[0], expected_time),
                        y0 : min(y0 + mask_array.chunks[1], expected_height),
                        x0 : min(x0 + mask_array.chunks[2], expected_width),
                    ]
                    invalid_domain = ~np.isin(values, CANONICAL_VALUES)
                    if invalid_domain.any():
                        bad = sorted({int(v) for v in np.unique(values[invalid_domain])})
                        raise ValueError(
                            f"water_mask contains values outside {CANONICAL_VALUES}: {bad} at {path}"
                        )

    if "time" not in group:
        raise ValueError(f"{path} is missing the 'time' coordinate")
    import pandas as pd

    opened = None
    try:
        import xarray as xr

        # Zarr stores time CF-encoded (e.g. "days since ..."); only xarray's
        # decoder (not a raw zarr array read) recovers real timestamps.
        opened = xr.open_zarr(_zarr_store(path), consolidated=False, mask_and_scale=False)
        mask_da, actual_crs, actual_transform = _read_georef(opened)
        time_values = pd.DatetimeIndex(np.asarray(mask_da.time.values))
    except Exception as exc:
        raise ValueError(f"{path} georeferencing could not be read: {exc}") from exc
    finally:
        if opened is not None:
            opened.close()

    if len(time_values) == 0:
        raise ValueError(f"{path} has an empty time axis")
    if not time_values.is_unique:
        raise ValueError(f"{path} time axis contains duplicate timestamps")
    if not time_values.is_monotonic_increasing:
        raise ValueError(f"{path} time axis is not in strict monthly order")
    if any(ts.year != int(expected_year) for ts in time_values):
        raise ValueError(
            f"{path} time axis contains timestamps outside year {expected_year}"
        )
    if any((ts.day != 1) for ts in time_values):
        raise ValueError(f"{path} time axis contains non-month-start timestamps")
    max_months = 12
    if len(time_values) > max_months:
        raise ValueError(
            f"{path} time axis has {len(time_values)} entries, more than {max_months} months"
        )
    expected_axis = pd.date_range(time_values[0], periods=len(time_values), freq="MS")
    if not time_values.equals(expected_axis):
        raise ValueError(f"{path} time axis is not a contiguous run of calendar months")

    if actual_crs is None:
        raise ValueError(f"{path} water_mask is missing a CRS")
    if any(
        not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
        for a, b in zip(actual_transform, expected_transform)
    ):
        raise ValueError(
            f"{path} transform {actual_transform} does not match expected {expected_transform}"
        )

    return complete_payload


def _completed_group_metadata(
    path: Path,
    *,
    expected_year: int,
    expected_grid_shape: tuple[int, int],
    expected_time_axis: "object",
) -> dict:
    """Validate completion and array metadata without reading raster chunks."""
    import pandas as pd
    import zarr
    from xarray.coding.times import decode_cf_datetime

    path = Path(path)
    if not Path(_long_path(path / ".zgroup")).exists():
        raise FileNotFoundError(f"{path} is not a Zarr group (missing .zgroup)")
    complete = _read_json(path / _COMPLETE_FILENAME)
    if complete is None:
        raise ValueError(f"{path} is missing a valid {_COMPLETE_FILENAME}")
    if int(complete.get("schema_version", -1)) != WOFS_CACHE_SCHEMA_VERSION:
        raise ValueError(f"{path} has an incompatible annual schema version")
    if int(complete.get("year", -1)) != int(expected_year):
        raise ValueError(f"{path} completion year does not match {expected_year}")
    if not complete.get("item_digest") or not complete.get("content_digest"):
        raise ValueError(f"{path} completion metadata is missing provenance digests")

    group = zarr.open_group(_zarr_store(path), mode="r")
    required = {"water_mask", "wet_count", "clear_count", "time", "y", "x", "spatial_ref"}
    missing = sorted(required - set(group.array_keys()))
    if missing:
        raise ValueError(f"{path} is missing required arrays: {missing}")

    height, width = (int(expected_grid_shape[0]), int(expected_grid_shape[1]))
    mask_array = group["water_mask"]
    if mask_array.dtype != np.dtype("int8"):
        raise ValueError(f"{path} water_mask dtype is not int8")
    if tuple(mask_array.shape[1:]) != (height, width) or not 1 <= int(mask_array.shape[0]) <= 12:
        raise ValueError(f"{path} water_mask shape is incompatible with the store grid")
    if tuple(mask_array.chunks) != tuple(MASK_CHUNKS):
        raise ValueError(f"{path} water_mask chunks do not match {MASK_CHUNKS}")

    for name in ("wet_count", "clear_count"):
        array = group[name]
        if array.dtype != np.dtype("uint16") or tuple(array.shape) != (height, width):
            raise ValueError(f"{path} {name} metadata is incompatible with the store grid")
        if tuple(array.chunks) != (_STORAGE_CHUNK, _STORAGE_CHUNK):
            raise ValueError(f"{path} {name} chunks are invalid")

    if tuple(group["y"].shape) != (height,) or tuple(group["x"].shape) != (width,):
        raise ValueError(f"{path} coordinate shapes are incompatible with the store grid")
    time_array = group["time"]
    units = time_array.attrs.get("units")
    if not units:
        raise ValueError(f"{path} time coordinate is missing CF units")
    decoded = decode_cf_datetime(
        np.asarray(time_array[:]), units, time_array.attrs.get("calendar", "standard")
    )
    time_values = pd.DatetimeIndex(np.asarray(decoded))
    expected_time_axis = pd.DatetimeIndex(expected_time_axis)
    if not time_values.is_unique:
        raise ValueError(f"{path} time axis contains duplicate timestamps")
    if not time_values.is_monotonic_increasing:
        raise ValueError(f"{path} time axis is not in strict monthly order")
    if any(ts.year != int(expected_year) or ts.day != 1 for ts in time_values):
        raise ValueError(f"{path} time axis is outside year {expected_year} or not month-start")
    expected_axis = pd.date_range(time_values[0], periods=len(time_values), freq="MS")
    if not time_values.equals(expected_axis):
        raise ValueError(f"{path} time axis is not a contiguous run of calendar months")
    if not time_values.equals(expected_time_axis):
        raise ValueError(f"{path} time axis does not match the cache request for {expected_year}")
    if complete.get("start_date") != expected_time_axis[0].strftime("%Y-%m-%d"):
        raise ValueError(f"{path} completion start_date does not match the cache request")
    if complete.get("end_date") != expected_time_axis[-1].strftime("%Y-%m-%d"):
        raise ValueError(f"{path} completion end_date does not match the cache request")
    if int(complete.get("month_count", -1)) != len(expected_time_axis):
        raise ValueError(f"{path} completion month_count does not match the cache request")

    expected_chunks = int(complete.get("chunks_written", -1))
    if expected_chunks < 0 or _stored_chunk_count(path / "water_mask") != expected_chunks:
        raise ValueError(f"{path} stored chunk count does not match completion metadata")
    return complete


def _store_grid_shape(handle: WOfSCacheHandle) -> tuple[int, int]:
    manifest = _read_json(Path(handle.path) / _MANIFEST_FILENAME) or {}
    identity = manifest.get("identity") or {}
    if identity.get("digest") != handle.identity:
        raise ValueError(f"cache manifest identity does not match handle at {handle.path}")
    shape = tuple(identity.get("shape") or ())
    if len(shape) != 2:
        raise ValueError(f"cache manifest is missing a two-dimensional grid shape at {handle.path}")
    return int(shape[0]), int(shape[1])


def _store_year_time_axis(handle: WOfSCacheHandle, year: int):
    manifest = _read_json(Path(handle.path) / _MANIFEST_FILENAME) or {}
    identity = manifest.get("identity") or {}
    request = identity.get("request") or {}
    start = pd.Timestamp(request.get("start_date")).to_period("M").to_timestamp()
    end = pd.Timestamp(request.get("end_date")).to_period("M").to_timestamp()
    year_start = max(pd.Timestamp(f"{int(year)}-01-01"), start)
    year_end = min(pd.Timestamp(f"{int(year)}-12-01"), end)
    if year_end < year_start:
        raise ValueError(f"year {year} is outside cache request range at {handle.path}")
    return pd.date_range(year_start, year_end, freq="MS")


def completed_years(handle: WOfSCacheHandle) -> set[int]:
    """Every calendar year with a genuinely completed annual group.

    A year counts as completed only if ``years/<year>`` exists, is a real
    Zarr group, and contains a readable ``complete.json`` -- a directory
    that merely exists (e.g. a stale/interrupted
    ``years/.<year>.incomplete-<uuid>`` temp directory, or a corrupt
    ``years/<year>``) is silently excluded rather than raising, so callers
    can use this to decide what still needs (re)building. Directory names
    starting with ``.`` (the temp-write naming convention) are always
    ignored without even checking their contents.
    """
    store_path = Path(handle.path)
    years_dir = _years_dir(store_path)
    if not Path(_long_path(years_dir)).is_dir():
        return set()
    try:
        expected_grid_shape = _store_grid_shape(handle)
    except ValueError:
        return set()
    result: set[int] = set()
    for entry in Path(_long_path(years_dir)).iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        try:
            year = int(entry.name)
        except ValueError:
            continue
        try:
            _completed_group_metadata(
                entry,
                expected_year=year,
                expected_grid_shape=expected_grid_shape,
                expected_time_axis=_store_year_time_axis(handle, year),
            )
        except Exception:
            continue
        result.add(year)
    return result


def open_completed_mask_cache(
    handle: WOfSCacheHandle,
    start_date: str,
    end_date: str,
    *,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_chunk: int = 12,
):
    """Lazily open the canonical water-mask cube for ``[start_date, end_date]``.

    Opens every completed annual group (:func:`completed_years`) that
    overlaps the requested range with ``xr.open_zarr(...,
    mask_and_scale=False)``, concatenates them in year order, slices to the
    exact requested dates, and fills any still-missing months via
    :func:`hydroseason._io_extent.complete_monthly_axis` (the same
    missing-month policy ``_io_geo.load_monthly_masks_zarr`` already uses:
    gaps become ``-1`` invalid, not ``-2`` outside).

    Raises ``ValueError`` if a completed year's stored time axis is not
    strictly increasing and duplicate-free (a corrupted store -- see
    :func:`validate_annual_group`, which every *newly written* group
    already passed, but an on-disk group can still be hand-edited or
    corrupted after the fact), or if any requested calendar month falls in
    a year that has no completed annual group.
    """
    import pandas as pd
    import xarray as xr

    store_path = Path(handle.path)
    start = pd.Timestamp(start_date).to_period("M").to_timestamp()
    end = pd.Timestamp(end_date).to_period("M").to_timestamp()
    requested_years = set(range(start.year, end.year + 1))

    available = completed_years(handle)
    missing = sorted(requested_years - available)
    if missing:
        try:
            expected_grid_shape = _store_grid_shape(handle)
        except ValueError:
            expected_grid_shape = None
        if expected_grid_shape is not None:
            for year in missing:
                year_path = _year_dir(store_path, year)
                if Path(_long_path(year_path)).is_dir():
                    _completed_group_metadata(
                        year_path,
                        expected_year=year,
                        expected_grid_shape=expected_grid_shape,
                        expected_time_axis=_store_year_time_axis(handle, year),
                    )
        raise FileNotFoundError(
            f"no completed WOfS annual group for year(s) {missing} at {store_path} "
            f"(requested range {start_date} to {end_date})"
        )

    arrays = []
    for year in sorted(requested_years):
        year_path = _year_dir(store_path, year)
        opened_ds = xr.open_zarr(
            _zarr_store(year_path),
            consolidated=False,
            mask_and_scale=False,
            chunks={"time": time_chunk, "y": chunk_y, "x": chunk_x},
        )
        mask_da, _crs, _transform = _read_georef(opened_ds)
        time_index = pd.DatetimeIndex(np.asarray(mask_da.time.values))
        if not time_index.is_unique or not time_index.is_monotonic_increasing:
            raise ValueError(
                f"annual group for year {year} at {year_path} does not have a "
                "strict monthly order time axis"
            )
        arrays.append(mask_da)

    combined = xr.concat(arrays, dim="time") if len(arrays) > 1 else arrays[0]
    combined = combined.sel(time=slice(start, end))

    from hydroseason._io_extent import complete_monthly_axis

    return complete_monthly_axis(combined, start_date, end_date)


def _backfill_extent_counts_json(year_path: Path, year: int) -> dict | None:
    try:
        import xarray as xr
        opened_ds = xr.open_zarr(_zarr_store(year_path), consolidated=False, mask_and_scale=False)
        try:
            mask_da, _crs, _transform = _read_georef(opened_ds)
            values = np.asarray(mask_da.values)
            time_index = pd.DatetimeIndex(np.asarray(mask_da.time.values))
            dates = [d.strftime("%Y-%m-%d") for d in time_index]

            water = (values == 1).sum(axis=(1, 2), dtype=np.int64)
            dry = (values == 0).sum(axis=(1, 2), dtype=np.int64)
            aoi = (values != -2).sum(axis=(1, 2), dtype=np.int64)
            valid = water + dry
            invalid = aoi - valid

            payload = {
                "schema_version": WOFS_CACHE_SCHEMA_VERSION,
                "year": int(year),
                "dates": dates,
                "n_aoi": aoi.tolist(),
                "n_valid": valid.tolist(),
                "n_water": water.tolist(),
                "n_invalid": invalid.tolist(),
            }
            payload["content_digest"] = _sha256_digest(payload)
            _write_json_atomic(year_path / "extent_counts.json", payload)
            return payload
        finally:
            opened_ds.close()
    except Exception:
        return None


def open_completed_extent_counts(
    handle: WOfSCacheHandle,
    start_date: str,
    end_date: str,
    *,
    read_workers: int | None = None,
) -> pd.DataFrame | None:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    requested_years = list(range(start.year, end.year + 1))
    done = completed_years(handle)
    if not set(requested_years).issubset(done):
        return None

    request = _handle_request_dict(handle)
    historical_mask_pixel_count = request.get("historical_mask_pixel_count")
    historical_mask_sha256 = request.get("historical_mask_sha256")

    if historical_mask_pixel_count is not None:
        # The request pins an exact scientific (historical-mask) denominator
        # -- accept the pruned counts ONLY when a CacheAnalysisMask sidecar
        # is actually on disk, independently verifies (tamper-evidence, not
        # just presence), and agrees with the request's own pinned identity.
        # This is a strictly higher bar than the legacy wet_aoi/planning-only
        # footprint check below: an unverified or absent sidecar, or one
        # that disagrees with the request, still lacks a valid scientific
        # denominator and must fail closed exactly like a planning-only
        # footprint always has.
        try:
            analysis_mask = verify_cache_analysis_mask(handle)
        except (FileNotFoundError, ValueError):
            return None
        if analysis_mask.pixel_count != int(historical_mask_pixel_count):
            return None
        if historical_mask_sha256 is not None and analysis_mask.mask_sha256 != str(
            historical_mask_sha256
        ):
            return None
    else:
        # No historical (scientific) mask on this request -- fall back to
        # the pre-Task-4 behaviour unchanged: a wet_aoi/planning-only
        # footprint still lacks a valid scientific denominator and must be
        # refused, regardless of how tightly it was pruned.
        request_uses_pruning = cache_request_uses_pruning(handle)
        if request_uses_pruning:
            try:
                footprints = verify_cache_footprints(handle)
            except (FileNotFoundError, ValueError):
                return None
            if footprints.analysis_pixel_count < footprints.aoi_pixel_count:
                # The per-year sidecar only contains counts over pixels that
                # were actually loaded. Fixed geometry metadata cannot
                # reconstruct the omitted pixels' monthly valid/invalid
                # state, so returning extent_pct here would be an inferred
                # scientific denominator.
                return None

    all_dates = []
    all_n_aoi = []
    all_n_valid = []
    all_n_water = []
    all_n_invalid = []

    for year in requested_years:
        year_path = Path(handle.path) / "years" / str(int(year))
        path = year_path / "extent_counts.json"
        payload = _read_json(path)
        if payload is None:
            payload = _backfill_extent_counts_json(year_path, year)
        if payload is None:
            return None
        content_digest = payload.get("content_digest")
        check_payload = {k: v for k, v in payload.items() if k != "content_digest"}
        if _sha256_digest(check_payload) != content_digest:
            return None

        dates = payload.get("dates", [])
        n_aoi = payload.get("n_aoi", [])
        n_valid = payload.get("n_valid", [])
        n_water = payload.get("n_water", [])
        n_invalid = payload.get("n_invalid", [])
        if not (len(dates) == len(n_aoi) == len(n_valid) == len(n_water) == len(n_invalid)):
            return None

        for aoi, val, wat, inv in zip(n_aoi, n_valid, n_water, n_invalid):
            if aoi < 0 or val < 0 or wat < 0 or inv < 0:
                return None
            if not (wat <= val <= aoi):
                return None
            if inv != aoi - val:
                return None

        all_dates.extend(dates)
        all_n_aoi.extend(n_aoi)
        all_n_valid.extend(n_valid)
        all_n_water.extend(n_water)
        all_n_invalid.extend(n_invalid)

    df = pd.DataFrame(
        {
            "n_water": np.array(all_n_water, dtype=np.int64),
            "n_aoi": np.array(all_n_aoi, dtype=np.int64),
            "n_valid": np.array(all_n_valid, dtype=np.int64),
            "n_invalid": np.array(all_n_invalid, dtype=np.int64),
        },
        index=pd.DatetimeIndex(all_dates),
    )
    mask_in_range = (df.index >= start) & (df.index <= end)
    df = df.loc[mask_in_range].copy()
    if df.empty:
        return None

    n_valid = df["n_valid"].to_numpy(dtype=np.float64)
    n_water = df["n_water"].to_numpy(dtype=np.float64)
    n_aoi = df["n_aoi"].to_numpy(dtype=np.float64)
    n_invalid = df["n_invalid"].to_numpy(dtype=np.float64)

    extent_pct = np.full_like(n_valid, np.nan)
    np.divide(n_water * 100.0, n_valid, out=extent_pct, where=n_valid > 0)

    invalid_pct = np.full_like(n_aoi, np.nan)
    np.divide(n_invalid * 100.0, n_aoi, out=invalid_pct, where=n_aoi > 0)

    df["extent_pct"] = extent_pct
    df["invalid_pct"] = invalid_pct
    df["n_wet_aoi"] = df["n_valid"]
    df["wet_fill_pct"] = extent_pct

    return df[["n_water", "n_aoi", "n_valid", "n_invalid", "n_wet_aoi", "extent_pct", "invalid_pct", "wet_fill_pct"]]


def open_completed_dual_extent_counts(
    handle: WOfSCacheHandle,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """Read back the ``years/<year>/dual_extent_counts.json`` sidecars task
    W2.2's ``composite_bundle="hydrofragments_v1"`` acquisition writes.

    Public reader counterpart to :func:`open_completed_extent_counts`, but
    for the SECOND (any-day-wet ``max_water``) composite's per-month pixel
    counts alongside the fixed full-AOI/analysis-mask pixel-count
    denominators (see :class:`CacheFootprints`) -- never conflating a
    per-month content count with those fixed geometry denominators.

    Unlike :func:`open_completed_extent_counts`, there is no backfill path:
    the secondary composite only ever exists as this sidecar (task W2.2
    deliberately never persists a second full-resolution raster to
    reconstruct it from), so a missing or tampered ``dual_extent_counts.json``
    for any requested year returns ``None`` rather than approximating one.
    Returns ``None`` if any requested year is not completed, the sidecar is
    missing/malformed for any requested year (e.g. the cache was acquired
    with ``composite_bundle="legacy"``, which never writes this file), the
    per-year ``content_digest`` does not match, or the resulting range has
    no rows.
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    requested_years = list(range(start.year, end.year + 1))
    done = completed_years(handle)
    if not set(requested_years).issubset(done):
        return None

    all_dates: list[str] = []
    all_aoi_pixel_count: list[int] = []
    all_analysis_mask_pixel_count: list[int] = []
    all_n_max_water: list[int] = []
    all_n_median_water: list[int] = []
    all_n_valid_analysis: list[int] = []

    for year in requested_years:
        year_path = Path(handle.path) / "years" / str(int(year))
        payload = _read_json(year_path / "dual_extent_counts.json")
        if payload is None:
            return None
        content_digest = payload.get("content_digest")
        check_payload = {k: v for k, v in payload.items() if k != "content_digest"}
        if _sha256_digest(check_payload) != content_digest:
            return None

        dates = payload.get("dates", [])
        n_max_water = payload.get("n_max_water", [])
        n_median_water = payload.get("n_median_water", [])
        n_valid_analysis = payload.get("n_valid_analysis", [])
        if not (len(dates) == len(n_max_water) == len(n_median_water) == len(n_valid_analysis)):
            return None
        if any(v < 0 for v in n_max_water) or any(v < 0 for v in n_median_water) or any(
            v < 0 for v in n_valid_analysis
        ):
            return None

        aoi_pixel_count = payload.get("aoi_pixel_count")
        analysis_mask_pixel_count = payload.get("analysis_mask_pixel_count")
        if aoi_pixel_count is None or analysis_mask_pixel_count is None:
            return None

        all_dates.extend(dates)
        all_aoi_pixel_count.extend([int(aoi_pixel_count)] * len(dates))
        all_analysis_mask_pixel_count.extend([int(analysis_mask_pixel_count)] * len(dates))
        all_n_max_water.extend(n_max_water)
        all_n_median_water.extend(n_median_water)
        all_n_valid_analysis.extend(n_valid_analysis)

    df = pd.DataFrame(
        {
            "aoi_pixel_count": np.array(all_aoi_pixel_count, dtype=np.int64),
            "analysis_mask_pixel_count": np.array(all_analysis_mask_pixel_count, dtype=np.int64),
            "n_max_water": np.array(all_n_max_water, dtype=np.int64),
            "n_median_water": np.array(all_n_median_water, dtype=np.int64),
            "n_valid_analysis": np.array(all_n_valid_analysis, dtype=np.int64),
        },
        index=pd.DatetimeIndex(all_dates),
    )
    mask_in_range = (df.index >= start) & (df.index <= end)
    df = df.loc[mask_in_range].copy()
    if df.empty:
        return None

    return df[[
        "aoi_pixel_count", "analysis_mask_pixel_count",
        "n_max_water", "n_median_water", "n_valid_analysis",
    ]]


__all__ = [
    "WOFS_CACHE_SCHEMA_VERSION",
    "WOFS_CLASSIFIER_VERSION",
    "WOFS_PLANNER_VERSION",
    "CANONICAL_VALUES",
    "MASK_CHUNKS",
    "WOfSCacheRequest",
    "WOfSCacheIdentity",
    "WOfSCacheHandle",
    "cache_request_uses_pruning",
    "cache_writer_lock",
    "create_cache_handle",
    "resolve_cached_request",
    "require_cached_request",
    "preflight_cache_space",
    "preflight_request_space",
    "AnnualWriteStats",
    "write_annual_group",
    "write_empty_annual_group",
    "validate_annual_group",
    "completed_years",
    "open_completed_mask_cache",
    "open_completed_extent_counts",
    "open_completed_dual_extent_counts",
    "CacheFootprints",
    "record_cache_footprints",
    "read_cache_footprints",
    "verify_cache_footprints",
    "CacheAnalysisMask",
    "record_cache_analysis_mask",
    "read_cache_analysis_mask",
    "verify_cache_analysis_mask",
]

