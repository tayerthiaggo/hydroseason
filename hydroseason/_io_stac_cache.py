"""STAC item metadata caching for repeated resolution and workflow probes.

Caches STAC item search metadata under ``cache_root / ".stac-items" / f"{digest}.json"``.
Identified by STAC URL, collection, AOI hash, start_date, and end_date.
Independent of output CRS or resolution, allowing repeated queries with different
grid parameters to reuse cached STAC items without hitting the remote API.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pystac

from hydroseason._io_wofs_zarr import _canonical_json_bytes, _read_json, _write_json_atomic


@dataclasses.dataclass(frozen=True)
class STACItemCacheKey:
    stac_url: str
    collection: str
    aoi_sha256: str
    start_date: str
    end_date: str

    def digest(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(dataclasses.asdict(self))).hexdigest()


def _stac_items_dir(cache_root: Path) -> Path:
    return Path(cache_root) / ".stac-items"


def load_cached_items(
    cache_root: str | Path | None,
    key: STACItemCacheKey,
    *,
    now: str | None = None,
) -> list[pystac.Item] | None:
    if cache_root is None:
        return None
    cache_path = _stac_items_dir(Path(cache_root)) / f"{key.digest()}.json"
    payload = _read_json(cache_path)
    if payload is None or not isinstance(payload, dict):
        return None

    fetched_at_str = payload.get("fetched_at")
    items_dict = payload.get("items")
    if not fetched_at_str or not items_dict:
        return None

    # Expiration logic
    end_year = int(key.end_date.split("-")[0])
    current_utc_year = (
        datetime.fromisoformat(now.replace("Z", "+00:00")).year
        if now
        else datetime.now(timezone.utc).year
    )
    if end_year >= current_utc_year:
        fetched_at = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
        now_dt = (
            datetime.fromisoformat(now.replace("Z", "+00:00"))
            if now
            else datetime.now(timezone.utc)
        )
        if (now_dt - fetched_at).total_seconds() > 86400:
            return None

    try:
        item_collection = pystac.ItemCollection.from_dict(items_dict)
        return list(item_collection.items)
    except Exception:
        return None


def write_cached_items(
    cache_root: str | Path | None,
    key: STACItemCacheKey,
    items: list[pystac.Item],
    *,
    fetched_at: str | None = None,
) -> None:
    if cache_root is None:
        return
    items_dir = _stac_items_dir(Path(cache_root))
    items_dir.mkdir(parents=True, exist_ok=True)
    cache_path = items_dir / f"{key.digest()}.json"

    now_iso = (
        fetched_at
        if fetched_at
        else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    item_collection = pystac.ItemCollection(items)
    payload = {
        "key": dataclasses.asdict(key),
        "fetched_at": now_iso,
        "items": item_collection.to_dict(),
    }
    _write_json_atomic(cache_path, payload)


__all__ = [
    "STACItemCacheKey",
    "load_cached_items",
    "write_cached_items",
]
