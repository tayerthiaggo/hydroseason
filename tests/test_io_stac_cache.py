import dataclasses
import pystac
import pytest

from hydroseason._io_stac_cache import (
    STACItemCacheKey,
    load_cached_items,
    write_cached_items,
)


def _item_dict(item_id: str) -> dict:
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        "bbox": [0, 0, 1, 1],
        "properties": {"datetime": "2015-01-15T00:00:00Z"},
        "assets": {},
        "links": [],
    }


def test_item_cache_key_excludes_output_resolution():
    left = STACItemCacheKey(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="1986-05-01",
        end_date="2026-06-01",
    )
    assert left.digest() == dataclasses.replace(left).digest()


def test_item_cache_round_trip_preserves_item_dicts(tmp_path):
    key = STACItemCacheKey(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="2015-01-01",
        end_date="2015-12-31",
    )
    items = [pystac.Item.from_dict(_item_dict("a")), pystac.Item.from_dict(_item_dict("b"))]
    write_cached_items(tmp_path, key, items, fetched_at="2026-07-25T00:00:00Z")
    loaded = load_cached_items(tmp_path, key, now="2026-07-25T01:00:00Z")
    assert loaded is not None
    assert [item.to_dict() for item in loaded] == [item.to_dict() for item in items]
