"""Filesystem and canonical-JSON helpers shared by the on-disk caches.

A leaf module: it imports nothing from ``hydroseason``, so the WOfS Zarr
cache, the historical-water-mask cache and the preflight statistics cache can
all share one copy without depending on each other. ``_canonical_json_bytes``
feeds every cache digest, so its encoding must never change.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


def _canonical_json_bytes(payload: dict) -> bytes:
    """Order- and whitespace-independent JSON encoding used for all digests."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _sha256_digest(payload: dict) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


_WINDOWS_EXTENDED_PATH_PREFIX = "\\\\?\\"


def _long_path(path: Path) -> str:
    """A Windows path string safe from the legacy 260-character ``MAX_PATH`` limit.

    Cache paths such as ``cache_root / "stores" / <64-char sha256 digest> /
    "years" / ...`` can exceed ``MAX_PATH`` on Windows once a caller's own
    ``cache_root`` is itself nested a few directories deep (this is common in
    tests, whose ``tmp_path`` fixtures add their own long, nested prefix) --
    and most Windows installs do not have the opt-in ``LongPathsEnabled``
    registry value set, so plain long paths simply fail with
    ``FileNotFoundError``. Prefixing an *absolute* path with ``\\\\?\\`` asks
    Win32 to bypass ``MAX_PATH`` for that call, without requiring any
    system-level opt-in. Network shares (``\\\\server\\share``) take the
    ``\\\\?\\UNC\\`` form instead. A no-op on non-Windows platforms and on
    already-prefixed paths.
    """
    absolute = os.path.abspath(str(path))
    if os.name != "nt" or absolute.startswith(_WINDOWS_EXTENDED_PATH_PREFIX):
        return absolute
    if absolute.startswith("\\\\"):
        return _WINDOWS_EXTENDED_PATH_PREFIX + "UNC" + absolute[1:]
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

    Every call site that opens or writes a Zarr *directory* (as opposed to
    JSON sidecar files, which go through :func:`_write_json_atomic`/plain
    ``Path`` I/O) should route through this rather than passing a bare
    path/string to ``zarr``/``xarray`` directly, so long cache-root paths
    keep working uniformly. A no-op wrapper on non-Windows platforms
    (:class:`_LongPathDirectoryStore` degrades to a plain, unprefixed
    ``DirectoryStore`` there).
    """
    return _LongPathDirectoryStore(path)


def _write_atomic(path: Path, write: Callable[[Path], object]) -> None:
    """Create ``path`` via ``write(temp_path)`` without ever leaving a partial file.

    ``write`` fills a temporary file in the same directory as ``path`` (so the
    final ``os.replace`` is an atomic rename on the same filesystem); a crash
    or concurrent read before that replace sees the old file or nothing new.
    Routes through :func:`_long_path` so this also works when ``path`` is
    nested deep enough to exceed Windows' legacy ``MAX_PATH``.
    """
    parent = Path(_long_path(path.parent))
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        write(temp_path)
        _retry_while_held(lambda: os.replace(str(temp_path), _long_path(path)))
    finally:
        temp_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write ``payload`` as canonical JSON to ``path`` (see :func:`_write_atomic`)."""
    _write_atomic(path, lambda temp: temp.write_bytes(_canonical_json_bytes(payload)))


# shortcut: a fixed lag after 31 December, because DEA keeps ingesting late
# scenes for a closed year for weeks; upgrade if the catalog ever publishes a
# per-year completeness flag.
_YEAR_SETTLE_LAG = timedelta(days=60)


def _now() -> datetime:
    """The current UTC time; the one clock cache freshness reads (tests patch it)."""
    return datetime.now(timezone.utc)


def _year_settled(year: int, written_at: float) -> bool:
    """True when a cache of ``year`` written at ``written_at`` (POSIX seconds) is final.

    Anything written earlier may lack scenes the catalog had not ingested
    yet, so callers rebuild it instead of trusting it for good.
    """
    settled_from = datetime(int(year), 12, 31, tzinfo=timezone.utc) + _YEAR_SETTLE_LAG
    return written_at >= settled_from.timestamp()


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(Path(_long_path(path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _retry_while_held(operation: Callable[[], object]) -> None:
    """Run a rename/replace, retrying briefly while Windows (antivirus, a lingering handle) holds a file."""
    for attempt in range(5):
        try:
            operation()
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
            import gc

            gc.collect()


def _rename_dir(source: Path | str, target: Path | str) -> None:
    _retry_while_held(lambda: os.rename(str(source), str(target)))
