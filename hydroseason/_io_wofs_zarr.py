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

This module implements identity/lock/lookup/preflight only. The annual Zarr
group writer/reader that actually persists WOfS pixels is a later task.
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
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import numpy as np

# Bumped whenever the on-disk index/manifest layout changes in a way that
# makes an old cache unreadable by new code (or vice versa).
WOFS_CACHE_SCHEMA_VERSION = 1

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

    def _digest_payload(self) -> dict:
        return dataclasses.asdict(self)

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


def _store_dir(cache_root: Path, request_digest: str) -> Path:
    return Path(cache_root) / "stores" / request_digest


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write ``payload`` as canonical JSON to ``path`` without ever partial-writing.

    Uses ``tempfile.mkstemp`` in the same directory as ``path`` (so the
    final ``os.replace`` is an atomic rename on the same filesystem), then
    replaces the target in one step. A crash or concurrent read at any point
    before the final ``os.replace`` observes either the old file or nothing
    new -- never a truncated/partial one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}-", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json_bytes(payload))
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextmanager
def cache_writer_lock(cache_root: Path, request_digest: str) -> Iterator[None]:
    """Exclusive on-disk lock guarding writes to one request's cache store.

    Acquires ``cache_root / ".locks" / f"{request_digest}.lock"`` via
    ``os.open`` with ``O_CREAT | O_EXCL`` -- an atomic create-if-absent that
    the OS refuses if the file already exists, so two processes racing to
    acquire the same lock can never both succeed. A losing process gets
    ``FileExistsError`` from the OS, which is re-raised here as a
    ``RuntimeError`` naming the request as already being written, rather
    than silently proceeding or auto-deleting the other process's lock file
    (that file might belong to a writer that is still very much alive; only
    the process that created a lock file ever removes it, in its own
    ``finally`` block on exit -- releasing on exception too).

    The lock file's contents (PID and creation timestamp) are informational
    only, useful for a human diagnosing a stuck lock; this module never
    reads them back to decide anything.
    """
    lock_path = _lock_path(Path(cache_root), request_digest)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
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


def create_cache_handle(cache_root: Path, identity: WOfSCacheIdentity) -> WOfSCacheHandle:
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
    store_dir = _store_dir(cache_root, request_digest)
    store_dir.mkdir(parents=True, exist_ok=True)

    import zarr

    zarr.open_group(store=str(store_dir), mode="a")

    manifest = {
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
        "request_digest": request_digest,
        "identity": identity.to_dict(),
    }
    _write_json_atomic(store_dir / _MANIFEST_FILENAME, manifest)

    index_entry = {
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
        "request_digest": request_digest,
        "identity": identity.to_dict(),
        "store": str(store_dir.relative_to(cache_root)).replace(os.sep, "/"),
        "start_date": identity.request.start_date,
        "end_date": identity.request.end_date,
    }
    _write_json_atomic(_index_path(cache_root, request_digest), index_entry)

    return WOfSCacheHandle(path=store_dir, identity=identity.digest, request_digest=request_digest)


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
    if not manifest_identity.get("digest"):
        return None
    return WOfSCacheHandle(
        path=store_dir,
        identity=manifest_identity["digest"],
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


__all__ = [
    "WOFS_CACHE_SCHEMA_VERSION",
    "WOFS_CLASSIFIER_VERSION",
    "WOFS_PLANNER_VERSION",
    "CANONICAL_VALUES",
    "MASK_CHUNKS",
    "WOfSCacheRequest",
    "WOfSCacheIdentity",
    "WOfSCacheHandle",
    "cache_writer_lock",
    "create_cache_handle",
    "resolve_cached_request",
    "require_cached_request",
    "preflight_cache_space",
    "preflight_request_space",
]
