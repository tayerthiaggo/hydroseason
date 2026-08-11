"""The exact historical maximum-water mask: a pure value object and builder.

``historical_max_water_mask = (DEA WO Multi-Year Statistics count_wet > 0)
AND user_AOI``, at the Statistics' native grid resolution. This is a SEPARATE,
scientific artifact from :class:`hydroseason._io_dea_stats.WetPlanningFootprint`
(performance-only, coarsened/dilated). The mask built here is never closed,
buffered, dilated, or round-tripped through polygons -- it is the raw,
grid-aligned boolean raster used exactly as-is as the fixed denominator for
every requested month.

This module does no I/O of its own: :func:`build_historical_water_mask` takes
an already-loaded ``stats`` dataset (whatever
:func:`hydroseason._io_dea_stats.open_wo_statistics` returns) and an AOI, and
is pure computation from there. All geospatial imports stay inside function
bodies, per the package rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    import xarray as xr

# The only DEA WO Statistics product accepted as a historical-mask source.
# The all-time summary is the one whose provenance is pinned as the fixed
# scientific footprint for the entire requested analysis period -- see
# hydroseason._io_dea_stats.DEA_STATS_ALLTIME_COLLECTION, duplicated here as
# a literal rather than imported. This module does import
# hydroseason._io_dea_stats.DEAStatsUnavailable (a leaf exception class with
# no dependency back on this module) for its fail-closed raises, but not the
# collection constants, so the existing one-way dependency direction between
# the two modules is preserved (_io_dea_stats.
# build_planning_footprint_from_historical_mask depends on this module for
# HistoricalWaterMask/build_historical_water_mask, not the reverse).
HISTORICAL_MASK_SOURCE_PRODUCT = "ga_ls_wo_fq_myear_3"

# The monthly WOfS observation collection the historical mask is applied
# against. Both collection ids encode the WOfS algorithm/processing version
# as their trailing "_<n>" token; the historical mask's source lineage is
# only compatible with this monthly collection when that version token
# matches (see _resolve_and_validate_provenance's "incompatible WOfS
# lineage" check).
MONTHLY_WOFS_COLLECTION = "ga_ls_wo_3"


@dataclass(frozen=True)
class HistoricalWaterMask:
    """The exact, immutable `(count_wet > 0) AND AOI` raster and its provenance.

    ``mask`` is a 2D boolean array (row-major, shape ``shape``) at the
    Statistics' native grid -- never a polygon. ``pixel_count`` is the fixed
    number of True cells, which becomes the constant ``n_aoi`` denominator
    for every month in the requested analysis period.

    ``source_item_ids`` and ``source_lineage`` are recorded as sorted tuples
    so two builds over the same underlying STAC items always compare equal
    regardless of search-result ordering. ``aoi_sha256``/``mask_sha256`` are
    stable SHA-256 digests -- see :func:`build_historical_water_mask` for
    exactly what each is computed over.
    """

    mask: Any
    crs: str
    transform: "tuple[float, ...]"
    shape: "tuple[int, int]"
    resolution: "tuple[float, float]"
    pixel_count: int
    source_product: str
    source_version: str
    source_item_ids: "tuple[str, ...]"
    source_lineage: "tuple[str, ...]"
    coverage_start: str
    coverage_end: str
    aoi_sha256: str
    mask_sha256: str


def _resolve_provenance(stats: "xr.Dataset") -> Mapping[str, Any]:
    """The ``stats.attrs["provenance"]`` block written by ``open_wo_statistics``.

    Raises :class:`hydroseason._io_dea_stats.DEAStatsUnavailable` if it is
    absent or missing ``product`` -- the lineage/version/coverage contract
    this builder validates is itself the thing being checked, so an absent
    or malformed block must fail exactly like an incompatible lineage would,
    and via the same fail-closed exception type
    :func:`hydroseason._io_dea_stats.build_wet_planning_footprint` already
    uses for the identical provenance contract.
    """
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    provenance = stats.attrs.get("provenance")
    if not isinstance(provenance, Mapping) or not provenance.get("product"):
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics provenance is absent or "
            "malformed -- incompatible WOfS lineage; refusing to build a "
            "historical water mask without a verifiable source contract"
        )
    return provenance


def _version_token(collection: str) -> str:
    """The trailing ``_<n>`` processing-version token of a DEA collection id.

    Matches the convention ``hydroseason._io_dea_stats._resolve_source_provenance``
    already uses (e.g. ``"ga_ls_wo_fq_myear_3"`` -> ``"3"``). Falls back to the
    full collection id if that convention isn't present.
    """
    tail = collection.rsplit("_", 1)[-1]
    return tail if tail.isdigit() else collection


def _parse_time_span(time_span: str | None) -> "tuple[str, str]":
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    if not time_span or "/" not in time_span:
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics does not cover analysis end: "
            f"source coverage {time_span!r} is unknown or malformed"
        )
    start, _, end = time_span.partition("/")
    if not start or not end:
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics does not cover analysis end: "
            f"source coverage {time_span!r} is unknown or malformed"
        )
    return start, end


def _coverage_covers_analysis_end(coverage_end: str, analysis_end: str) -> bool:
    import pandas as pd

    return pd.Timestamp(coverage_end).tz_localize(None) >= pd.Timestamp(analysis_end).tz_localize(None)


def build_historical_water_mask(
    stats: "xr.Dataset", aoi: Any, *, analysis_end: str,
) -> HistoricalWaterMask:
    """Build the exact `(count_wet > 0) AND AOI` historical water mask.

    ``stats`` is the ``xr.Dataset`` returned by
    :func:`hydroseason._io_dea_stats.open_wo_statistics` (must be the
    all-time Multi-Year product, ``ga_ls_wo_fq_myear_3``). ``aoi`` is a user
    AOI geometry/GeoDataFrame, rasterized onto ``stats``'s native grid via
    :func:`hydroseason._io_geo._inside_aoi_mask_like` (the same
    AOI-onto-grid rasterizer ``_clip_to_aoi`` already uses elsewhere in the
    package). The result is never closed, buffered, dilated, or converted
    through a polygon: it is exactly ``(count_wet > 0) & rasterized_aoi``,
    materialized as a plain boolean ``numpy`` array.

    Raises :class:`hydroseason._io_dea_stats.DEAStatsUnavailable`
    (fail-closed, matching the identical three-category validation
    :func:`hydroseason._io_dea_stats.build_wet_planning_footprint` already
    performs against the same ``stats.attrs["provenance"]`` contract) for:

    * an incompatible source product/lineage (anything other than
      ``ga_ls_wo_fq_myear_3``, or a version token that does not match the
      monthly WOfS collection ``ga_ls_wo_3``) -- message contains
      ``"incompatible WOfS lineage"``;
    * source coverage that does not reach ``analysis_end`` -- message
      contains ``"does not cover analysis end"``;
    * an exact mask with no True cells after the AND-with-AOI step --
      message contains ``"no historically observed water"``.
    """
    import numpy as np
    import rioxarray  # noqa: F401  (registers the .rio accessor used below)

    from hydroseason._io_dea_stats import DEAStatsUnavailable
    from hydroseason._io_geo import _inside_aoi_mask_like, load_aoi

    provenance = _resolve_provenance(stats)
    product = str(provenance["product"])
    if product != HISTORICAL_MASK_SOURCE_PRODUCT:
        raise DEAStatsUnavailable(
            f"incompatible WOfS lineage: historical water mask requires "
            f"product {HISTORICAL_MASK_SOURCE_PRODUCT!r}, got {product!r}"
        )

    version = _version_token(product)
    monthly_version = _version_token(MONTHLY_WOFS_COLLECTION)
    if version != monthly_version:
        # Unreachable in practice today: both collection constants above are
        # hardcoded to agree, so this can only fire if a future edit lets
        # them drift apart. Kept as defense-in-depth for that drift rather
        # than trusting the product-identity check above to catch it alone.
        raise DEAStatsUnavailable(
            f"incompatible WOfS lineage: Multi-Year Statistics version "
            f"{version!r} (from {product!r}) does not match the monthly "
            f"WOfS collection {MONTHLY_WOFS_COLLECTION!r} version "
            f"{monthly_version!r}"
        )

    item_ids = tuple(sorted(str(i) for i in (provenance.get("item_ids") or [])))
    lineage = tuple(sorted({product, *item_ids})) if item_ids else (product,)

    coverage_start, coverage_end = _parse_time_span(provenance.get("time_span"))
    if not _coverage_covers_analysis_end(coverage_end, analysis_end):
        raise DEAStatsUnavailable(
            f"DEA Water Observation Statistics source coverage "
            f"{coverage_start!r}/{coverage_end!r} does not cover analysis "
            f"end {analysis_end!r}"
        )

    count_wet = stats["count_wet"]
    wet = (count_wet > 0).astype(bool)

    aoi_gdf = load_aoi(aoi)
    crs = count_wet.rio.crs
    aoi_on_grid = aoi_gdf.to_crs(crs) if crs is not None else aoi_gdf
    inside_aoi = _inside_aoi_mask_like(wet, aoi_on_grid)

    exact = wet & inside_aoi
    exact_values = np.asarray(exact.values, dtype=bool)

    pixel_count = int(exact_values.sum())
    if pixel_count == 0:
        raise DEAStatsUnavailable(
            "no historically observed water: (count_wet > 0) AND AOI is "
            "empty for this AOI; refusing to build a historical water mask "
            "that would silently become an empty scientific denominator"
        )

    transform = tuple(count_wet.rio.transform())[:6]
    resolution = (abs(float(transform[0])), abs(float(transform[4])))
    shape = (int(exact_values.shape[0]), int(exact_values.shape[1]))

    aoi_sha256 = _aoi_digest(aoi_on_grid)
    mask_sha256 = _mask_digest(
        exact_values, crs=str(crs), transform=transform, shape=shape,
        resolution=resolution,
    )

    return HistoricalWaterMask(
        mask=exact_values,
        crs=str(crs),
        transform=transform,
        shape=shape,
        resolution=resolution,
        pixel_count=pixel_count,
        source_product=product,
        source_version=version,
        source_item_ids=item_ids,
        source_lineage=lineage,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        aoi_sha256=aoi_sha256,
        mask_sha256=mask_sha256,
    )


def _aoi_digest(aoi_gdf) -> str:
    """A stable SHA-256 over an AOI's geometry and CRS.

    Reuses the exact WKB-at-fixed-precision pattern
    :func:`hydroseason._io_dea_stats.wet_mask_digest` already uses, so an
    AOI's digest is computed identically everywhere in the package rather
    than by a second, parallel scheme.
    """
    import shapely
    from shapely import wkb

    geometry = (
        aoi_gdf.geometry.union_all()
        if hasattr(aoi_gdf.geometry, "union_all")
        else aoi_gdf.geometry.unary_union
    )
    geometry = shapely.set_precision(geometry, grid_size=0.001)
    hasher = hashlib.sha256()
    hasher.update(str(aoi_gdf.crs).encode("utf-8"))
    hasher.update(wkb.dumps(geometry))
    return hasher.hexdigest()


def _mask_digest(
    mask_values, *, crs: str, transform: "tuple[float, ...]",
    shape: "tuple[int, int]", resolution: "tuple[float, float]",
) -> str:
    """A stable SHA-256 over canonical grid metadata plus row-major mask bytes.

    Matches the digest style already used by
    :func:`hydroseason._io_dea_stats._wet_planning_footprint_digest`: raw
    boolean bytes plus every grid parameter that could otherwise make two
    different masks collide, hashed in a fixed field order so the result is
    independent of dict/attrs ordering.
    """
    hasher = hashlib.sha256()
    hasher.update(crs.encode("utf-8"))
    hasher.update(str(transform).encode("utf-8"))
    hasher.update(str(shape).encode("utf-8"))
    hasher.update(str(resolution).encode("utf-8"))
    hasher.update(mask_values.tobytes(order="C"))
    return hasher.hexdigest()


# --------------------------------------------------------------------------
# Persistence: a verified Zarr+JSON sidecar cache for HistoricalWaterMask,
# under cache_root / "historical-water-masks" /.
#
#   artifacts/<artifact_digest>/mask.zarr      -- 2D boolean array
#   artifacts/<artifact_digest>/manifest.json  -- every HistoricalWaterMask field
#   index/<request_digest>.json                -- pointer: request -> artifact
#
# Follows the same conventions hydroseason._io_wofs_zarr.py already
# establishes for its own annual-group cache: canonical (sorted-key,
# whitespace-free) JSON digests, atomic writes via a sibling temp
# directory/file plus a single os.replace/os.rename, and an index entry
# published only after the artifact it points to has been verified on disk
# -- so a crash mid-write can never leave a dangling or half-written
# pointer. Zarr itself is opened directly (no xarray/dask template needed
# for a single, eager 2D boolean array), unlike that module's dask-backed
# annual cube writer.
# --------------------------------------------------------------------------

_HISTORICAL_CACHE_DIRNAME = "historical-water-masks"
_ARTIFACTS_DIRNAME = "artifacts"
_INDEX_DIRNAME = "index"
_MASK_ZARR_DIRNAME = "mask.zarr"
_MANIFEST_FILENAME = "manifest.json"

# Bumped whenever the on-disk artifact/index layout or manifest field set
# changes in a way that makes an old cache unreadable (or misread) by new
# code.
HISTORICAL_MASK_CACHE_SCHEMA_VERSION = 1

_WINDOWS_EXTENDED_PATH_PREFIX = "\\\\?\\"


def _long_path(path) -> str:
    """A Windows path string safe from the legacy 260-character ``MAX_PATH`` limit.

    Matches hydroseason._io_wofs_zarr._long_path exactly (duplicated here
    rather than imported, for the same one-way-dependency reason as
    :func:`_canonical_json_bytes`): ``cache_root / "historical-water-masks"
    / "artifacts" / <64-char sha256 digest> / "mask.zarr" / ...`` can exceed
    ``MAX_PATH`` once a caller's own ``cache_root`` is itself nested a few
    directories deep (this is common in tests, whose ``tmp_path`` fixtures
    add their own long, nested prefix), and most Windows installs do not
    have the opt-in ``LongPathsEnabled`` registry value set. A no-op on
    non-Windows platforms and on already-prefixed paths.
    """
    absolute = os.path.abspath(str(path))
    if os.name != "nt" or absolute.startswith(_WINDOWS_EXTENDED_PATH_PREFIX):
        return absolute
    return _WINDOWS_EXTENDED_PATH_PREFIX + absolute


class _LongPathDirectoryStore:
    """A Zarr v2 ``DirectoryStore`` usable past Windows' ``MAX_PATH`` limit.

    Matches hydroseason._io_wofs_zarr._LongPathDirectoryStore exactly:
    delegates to ``zarr.storage.DirectoryStore`` rooted at a
    :func:`_long_path`-prefixed path, and normalises every storage key
    (Zarr uses ``/``-separated keys) to the native separator before
    delegating, since the ``\\\\?\\``-prefixed extended-length form is
    passed to Win32 verbatim and rejects any forward slash.
    """

    def __init__(self, path):
        import zarr

        self._store = zarr.storage.DirectoryStore(_long_path(path))

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


def _zarr_store(path):
    """A Zarr store for ``path`` that works past Windows' ``MAX_PATH`` limit.

    Every call site in this module that opens or writes the ``mask.zarr``
    directory should route through this rather than passing a bare
    path/string to ``zarr`` directly. A no-op wrapper on non-Windows
    platforms.
    """
    return _LongPathDirectoryStore(path)


def _canonical_json_bytes(payload: dict) -> bytes:
    """Order- and whitespace-independent JSON encoding used for all digests.

    Matches hydroseason._io_wofs_zarr._canonical_json_bytes exactly (same
    sorted-key, separator-free convention), duplicated here rather than
    imported to preserve this module's one-way dependency direction (it must
    not depend on the WOfS Zarr cache module).
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _sha256_digest(payload: dict) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class HistoricalWaterMaskRequest:
    """Every data-semantic input that identifies a historical-mask cache request.

    Deliberately excludes anything filesystem- or time-window-specific:
    ``cache_root`` is a caller-supplied mutable path, and analysis
    start/end dates do not change what the cached artifact IS -- only
    whether its recorded ``coverage_end`` is sufficient to serve a given
    request (checked separately at read time against the manifest, not
    baked into the digest). Two requests differing only in analysis window
    must therefore share the same cache entry, which is exactly what lets a
    single artifact serve every requested monthly date without duplication.

    ``aoi_sha256`` is a caller-computed content digest of the AOI geometry
    (the same convention :func:`_aoi_digest` in this module and
    :func:`hydroseason._io_dea_stats.wet_mask_digest` both use) -- this
    module never needs to know how to hash an arbitrary AOI type itself.
    """

    aoi_sha256: str
    product: str
    stac_url: str
    crs: str
    resolution: float

    def request_digest(self) -> str:
        return _sha256_digest(
            {
                "aoi_sha256": self.aoi_sha256,
                "product": self.product,
                "stac_url": self.stac_url,
                "crs": self.crs,
                "resolution": float(self.resolution),
            }
        )


def _artifact_digest(mask: HistoricalWaterMask) -> str:
    """A stable SHA-256 identifying one exact mask's cached artifact.

    Combines ``mask.mask_sha256`` (already a digest over the mask's grid
    metadata and raw boolean bytes -- see :func:`_mask_digest`) with
    normalized source provenance: product, version, sorted item ids,
    lineage, and coverage span. Two builds with byte-identical pixels but
    different source provenance (e.g. a WOfS processing-version bump, or a
    STAC catalog update that changed which items resolved) must never share
    one cached artifact, even though their raw mask bytes agree -- that is
    exactly the "a source-version change never overwrites a pinned
    artifact" requirement.
    """
    return _sha256_digest(
        {
            "mask_sha256": mask.mask_sha256,
            "source_product": mask.source_product,
            "source_version": mask.source_version,
            "source_item_ids": list(mask.source_item_ids),
            "source_lineage": list(mask.source_lineage),
            "coverage_start": mask.coverage_start,
            "coverage_end": mask.coverage_end,
        }
    )


def _historical_cache_root(cache_root) -> Path:
    return Path(cache_root) / _HISTORICAL_CACHE_DIRNAME


def _artifact_dir(cache_root, artifact_digest: str) -> Path:
    return _historical_cache_root(cache_root) / _ARTIFACTS_DIRNAME / artifact_digest


def _index_path(cache_root, request_digest: str) -> Path:
    return _historical_cache_root(cache_root) / _INDEX_DIRNAME / f"{request_digest}.json"


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write ``payload`` as canonical JSON to ``path`` without ever partial-writing.

    Same pattern as hydroseason._io_wofs_zarr._write_json_atomic: a
    ``tempfile.mkstemp`` sibling in the same directory (so the final
    ``os.replace`` is an atomic same-filesystem rename), written then
    replaced in one step -- a crash or concurrent read at any point before
    that final step observes either the old file or nothing new, never a
    truncated one.
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


def _mask_manifest_payload(mask: HistoricalWaterMask) -> dict:
    return {
        "schema_version": HISTORICAL_MASK_CACHE_SCHEMA_VERSION,
        "crs": mask.crs,
        "transform": list(mask.transform),
        "shape": list(mask.shape),
        "resolution": list(mask.resolution),
        "pixel_count": int(mask.pixel_count),
        "source_product": mask.source_product,
        "source_version": mask.source_version,
        "source_item_ids": list(mask.source_item_ids),
        "source_lineage": list(mask.source_lineage),
        "coverage_start": mask.coverage_start,
        "coverage_end": mask.coverage_end,
        "aoi_sha256": mask.aoi_sha256,
        "mask_sha256": mask.mask_sha256,
    }


def write_historical_water_mask(
    cache_root, request: HistoricalWaterMaskRequest, mask: HistoricalWaterMask,
) -> str:
    """Atomically persist ``mask`` under ``cache_root``, then publish the index.

    Writes ``mask.zarr`` (a plain 2D boolean Zarr array, chunked, no time
    axis and no canonical -2/-1/0/1 value domain -- unlike the WOfS annual
    cache, this is a single already-exact boolean raster) and
    ``manifest.json`` (every :class:`HistoricalWaterMask` field) to a
    sibling temporary directory under ``artifacts/``, then renames it into
    place in one step so a crash mid-write can never leave a half-written
    artifact directory that a reader could mistake for complete.

    The artifact is content-addressed by :func:`_artifact_digest`, derived
    from the exact-mask digest plus normalized source provenance -- so
    writing the identical mask twice (e.g. once per requested monthly
    analysis date) is idempotent and never creates a duplicate artifact,
    and a source-version change always lands at a different artifact path
    rather than overwriting a pinned one.

    The request-index pointer (``index/<request_digest>.json``) is written
    LAST, only after the artifact directory has been fully published and
    independently re-verified via :func:`read_historical_water_mask`-style
    checks -- so an index entry is never observable pointing at an
    unverified or partially-written artifact.

    Returns the artifact digest.
    """
    import shutil

    import numpy as np
    import zarr

    cache_root = Path(cache_root)
    artifact_digest = _artifact_digest(mask)
    final_dir = _artifact_dir(cache_root, artifact_digest)

    # Idempotent skip: trusts manifest.json presence at the content-addressed
    # path without re-verifying its bytes, relying on artifact_digest being
    # derived from the mask content itself (see _artifact_digest) to make a
    # stale or foreign manifest at this path a contradiction, not a risk.
    if not Path(_long_path(final_dir / _MANIFEST_FILENAME)).exists():
        artifacts_root = _historical_cache_root(cache_root) / _ARTIFACTS_DIRNAME
        Path(_long_path(artifacts_root)).mkdir(parents=True, exist_ok=True)
        temp_dir = artifacts_root / f".{artifact_digest}.incomplete-{os.getpid()}-{id(mask)}"
        if Path(_long_path(temp_dir)).exists():
            shutil.rmtree(_long_path(temp_dir))
        Path(_long_path(temp_dir)).mkdir(parents=True)
        try:
            mask_values = np.ascontiguousarray(np.asarray(mask.mask, dtype=bool))
            zarr_path = temp_dir / _MASK_ZARR_DIRNAME
            array = zarr.open_array(
                _zarr_store(zarr_path),
                mode="w",
                shape=mask_values.shape,
                chunks=True,
                dtype=bool,
            )
            array[:] = mask_values

            manifest = _mask_manifest_payload(mask)
            manifest["artifact_digest"] = artifact_digest
            _write_json_atomic(temp_dir / _MANIFEST_FILENAME, manifest)

            # Verify the freshly-written artifact against the in-memory
            # mask BEFORE it becomes visible at its final path, so a
            # write-time bug can never publish a corrupt artifact.
            _verify_artifact_dir(temp_dir, expected_manifest=manifest, mask_values=mask_values)

            if Path(_long_path(final_dir)).exists():
                shutil.rmtree(_long_path(final_dir))
            os.rename(_long_path(temp_dir), _long_path(final_dir))
        except BaseException:
            shutil.rmtree(_long_path(temp_dir), ignore_errors=True)
            raise

    index_entry = {
        "schema_version": HISTORICAL_MASK_CACHE_SCHEMA_VERSION,
        "request_digest": request.request_digest(),
        "artifact_digest": artifact_digest,
        "aoi_sha256": request.aoi_sha256,
        "product": request.product,
        "stac_url": request.stac_url,
        "crs": request.crs,
        "resolution": float(request.resolution),
    }
    _write_json_atomic(_index_path(cache_root, request.request_digest()), index_entry)

    return artifact_digest


def _verify_artifact_dir(artifact_dir: Path, *, expected_manifest: dict, mask_values) -> None:
    """Recompute the mask digest/grid/pixel count from ``artifact_dir`` on disk
    and compare against ``expected_manifest``/``mask_values``.

    Raises ``ValueError("historical water mask cache verification failed")``
    on any mismatch -- tampered mask bytes, a hand-edited manifest field, or
    a manifest/array shape disagreement. This is a LOCAL STORAGE INTEGRITY
    check, deliberately a different exception family from
    :class:`hydroseason._io_dea_stats.DEAStatsUnavailable` (reserved for the
    remote DEA source itself being unusable/unavailable/incompatible): a
    corrupted on-disk artifact is not a statement about DEA's availability,
    and the existing WOfS Zarr cache (``_io_wofs_zarr._validate_hit``,
    ``WOfSCacheIdentity.from_dict``) already uses plain ``ValueError`` for
    the identical class of problem, so this follows that established
    convention rather than introducing a third failure vocabulary.
    """
    import numpy as np
    import zarr

    zarr_path = artifact_dir / _MASK_ZARR_DIRNAME
    try:
        array = zarr.open_array(_zarr_store(zarr_path), mode="r")
        on_disk = np.asarray(array[:], dtype=bool)
    except Exception as exc:
        raise ValueError(
            "historical water mask cache verification failed: could not read "
            f"mask.zarr at {zarr_path}: {type(exc).__name__}: {exc}"
        ) from exc

    expected_shape = tuple(int(v) for v in expected_manifest["shape"])
    if tuple(on_disk.shape) != expected_shape:
        raise ValueError(
            "historical water mask cache verification failed: on-disk shape "
            f"{tuple(on_disk.shape)!r} does not match manifest shape {expected_shape!r}"
        )

    recomputed_pixel_count = int(on_disk.sum())
    if recomputed_pixel_count != int(expected_manifest["pixel_count"]):
        raise ValueError(
            "historical water mask cache verification failed: recomputed "
            f"pixel_count {recomputed_pixel_count} does not match manifest "
            f"pixel_count {expected_manifest['pixel_count']}"
        )

    recomputed_digest = _mask_digest(
        on_disk,
        crs=str(expected_manifest["crs"]),
        transform=tuple(expected_manifest["transform"]),
        shape=expected_shape,
        resolution=tuple(expected_manifest["resolution"]),
    )
    if recomputed_digest != expected_manifest["mask_sha256"]:
        raise ValueError(
            "historical water mask cache verification failed: recomputed "
            f"mask digest {recomputed_digest} does not match manifest "
            f"mask_sha256 {expected_manifest['mask_sha256']}"
        )

    if mask_values is not None and not np.array_equal(on_disk, mask_values):
        raise ValueError(
            "historical water mask cache verification failed: on-disk mask "
            "bytes do not match the mask being persisted"
        )


def read_historical_water_mask(
    cache_root, request: HistoricalWaterMaskRequest, *, analysis_end: str,
) -> "HistoricalWaterMask | None":
    """Look up and verify a cached :class:`HistoricalWaterMask` for ``request``.

    Reads ``index/<request_digest>.json``; on a miss (no index entry, or an
    index entry whose ``request_digest``/``artifact_digest`` disagree with
    the manifest it names) returns ``None`` rather than raising -- a miss is
    an ordinary, expected outcome (cold cache, or a stale/foreign index
    entry), not a corruption.

    On a hit, recomputes and compares the boolean mask digest, grid
    metadata (crs/transform/shape/resolution), and pixel count against the
    on-disk ``mask.zarr``/``manifest.json``; any mismatch is treated as
    tampering and raises ``ValueError("historical water mask cache
    verification failed")`` (see :func:`_verify_artifact_dir`) rather than
    silently returning corrupted data.

    A verified artifact whose recorded ``coverage_end`` does not reach
    ``analysis_end`` cannot satisfy this request -- it is reported as a
    miss (``None``), the same as no cache at all, since the resolved source
    coverage recorded in the manifest (not the request digest) is what
    determines whether an artifact can serve a given analysis window.
    """
    cache_root = Path(cache_root)
    index_entry = _read_json(_index_path(cache_root, request.request_digest()))
    if index_entry is None:
        return None
    if index_entry.get("request_digest") != request.request_digest():
        return None

    artifact_digest = index_entry.get("artifact_digest")
    if not artifact_digest:
        return None
    artifact_dir = _artifact_dir(cache_root, artifact_digest)
    manifest = _read_json(artifact_dir / _MANIFEST_FILENAME)
    if manifest is None:
        return None
    if manifest.get("artifact_digest") != artifact_digest:
        return None

    required_fields = (
        "crs", "transform", "shape", "resolution", "pixel_count",
        "source_product", "source_version", "source_item_ids",
        "source_lineage", "coverage_start", "coverage_end", "aoi_sha256",
        "mask_sha256",
    )
    if any(field not in manifest for field in required_fields):
        return None

    # Verify on-disk contents against the manifest's OWN recorded fields
    # (not against any in-memory mask -- there is none on a read path) --
    # any mismatch is tampering, not a miss, and must raise.
    _verify_artifact_dir(artifact_dir, expected_manifest=manifest, mask_values=None)

    if not _coverage_covers_analysis_end(manifest["coverage_end"], analysis_end):
        return None

    import numpy as np
    import zarr

    array = zarr.open_array(_zarr_store(artifact_dir / _MASK_ZARR_DIRNAME), mode="r")
    mask_values = np.asarray(array[:], dtype=bool)

    return HistoricalWaterMask(
        mask=mask_values,
        crs=str(manifest["crs"]),
        transform=tuple(float(v) for v in manifest["transform"]),
        shape=(int(manifest["shape"][0]), int(manifest["shape"][1])),
        resolution=(float(manifest["resolution"][0]), float(manifest["resolution"][1])),
        pixel_count=int(manifest["pixel_count"]),
        source_product=str(manifest["source_product"]),
        source_version=str(manifest["source_version"]),
        source_item_ids=tuple(str(v) for v in manifest["source_item_ids"]),
        source_lineage=tuple(str(v) for v in manifest["source_lineage"]),
        coverage_start=str(manifest["coverage_start"]),
        coverage_end=str(manifest["coverage_end"]),
        aoi_sha256=str(manifest["aoi_sha256"]),
        mask_sha256=str(manifest["mask_sha256"]),
    )


def load_or_build_historical_water_mask(
    aoi: Any,
    *,
    analysis_end: str,
    cache_root,
    offline: bool = False,
    stac_url: str | None = None,
    product: str | None = None,
    crs: str = "EPSG:3577",
    resolution: float = 30,
) -> HistoricalWaterMask:
    """Resolve a verified :class:`HistoricalWaterMask` for ``aoi``, cache-first.

    Resolution order: (1) a verified cache hit via
    :func:`read_historical_water_mask` -- zero network access; (2) exactly
    one :func:`hydroseason._io_dea_stats.open_wo_statistics` load plus
    :func:`build_historical_water_mask`, persisted via
    :func:`write_historical_water_mask` before being returned.

    In ``offline=True`` mode, or after a Statistics load/build failure,
    returns ONLY a verified cache -- never falls through to constructing a
    full-AOI mask by any other means. If no verified cache exists in either
    case, raises :class:`hydroseason._io_dea_stats.DEAStatsUnavailable`
    (offline with no cache: "no cached historical water mask"; online with
    a Statistics failure: the underlying failure, re-raised).

    ``stac_url``/``product`` default to
    :data:`hydroseason._io_dea_stats.DEFAULT_WO_STATISTICS_STAC_URL` /
    :data:`hydroseason._io_dea_stats.DEFAULT_WO_STATISTICS_PRODUCT` when not
    given. ``cache_root`` is required and has no default -- this function
    caches to disk, and picking a directory on the caller's behalf (e.g.
    relative to the current working directory) is not a decision this
    module makes silently. This mirrors every other cache-bearing entry
    point in the package (:mod:`hydroseason._io_wofs_zarr`,
    :mod:`hydroseason._io_wofs_acquire`, :mod:`hydroseason._io_stac_cache`),
    none of which default ``cache_root`` either. A shared default cache root
    across the high-level API is expected to be wired through by a later
    task, not invented here.
    """
    from hydroseason._io_dea_stats import (
        DEFAULT_WO_STATISTICS_PRODUCT,
        DEFAULT_WO_STATISTICS_STAC_URL,
        DEAStatsUnavailable,
    )
    from hydroseason._io_geo import load_aoi

    resolved_stac_url = stac_url or DEFAULT_WO_STATISTICS_STAC_URL
    resolved_product = product or DEFAULT_WO_STATISTICS_PRODUCT

    aoi_gdf = load_aoi(aoi)
    crs_normalized = str(crs)
    aoi_on_crs = aoi_gdf.to_crs(crs_normalized) if crs_normalized else aoi_gdf
    aoi_sha256 = _aoi_digest(aoi_on_crs)

    request = HistoricalWaterMaskRequest(
        aoi_sha256=aoi_sha256,
        product=resolved_product,
        stac_url=resolved_stac_url,
        crs=crs_normalized,
        resolution=float(resolution),
    )

    cached = read_historical_water_mask(cache_root, request, analysis_end=analysis_end)
    if cached is not None:
        return cached

    if offline:
        raise DEAStatsUnavailable(
            "no cached historical water mask satisfies this request while "
            "offline=True; refusing to build one over the network"
        )

    import hydroseason._io_dea_stats as _io_dea_stats

    # DEAStatsUnavailable now covers WoStatisticsUnavailable (subclass), so
    # an unreachable statistics endpoint reaches the cache-after-failure
    # fallback below instead of propagating past it.
    try:
        stats = _io_dea_stats.open_wo_statistics(
            aoi_on_crs,
            product=resolved_product,
            stac_url=resolved_stac_url,
            resolution=float(resolution),
            crs=crs_normalized,
        )
        mask = build_historical_water_mask(stats, aoi_on_crs, analysis_end=analysis_end)
    except DEAStatsUnavailable:
        cached_after_failure = read_historical_water_mask(
            cache_root, request, analysis_end=analysis_end
        )
        if cached_after_failure is not None:
            return cached_after_failure
        raise

    write_historical_water_mask(cache_root, request, mask)
    return mask


__all__ = [
    "HISTORICAL_MASK_SOURCE_PRODUCT",
    "HISTORICAL_MASK_CACHE_SCHEMA_VERSION",
    "MONTHLY_WOFS_COLLECTION",
    "HistoricalWaterMask",
    "HistoricalWaterMaskRequest",
    "build_historical_water_mask",
    "load_or_build_historical_water_mask",
    "read_historical_water_mask",
    "write_historical_water_mask",
]
