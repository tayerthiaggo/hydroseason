import dataclasses
import json
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


def test_item_cache_invalid_timestamp_fails_closed(tmp_path):
    key = STACItemCacheKey(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="2026-01-01",
        end_date="2026-12-31",
    )
    cache_path = tmp_path / ".stac-items" / f"{key.digest()}.json"
    cache_path.parent.mkdir()
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": "not-a-timestamp",
                "items": {"type": "FeatureCollection", "features": []},
            }
        ),
        encoding="utf-8",
    )

    assert load_cached_items(tmp_path, key, now="2026-07-26T00:00:00Z") is None


def test_cached_empty_year_round_trips_as_empty_not_missing(tmp_path):
    key = STACItemCacheKey(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="1987-01-01",
        end_date="1987-12-31",
    )
    write_cached_items(tmp_path, key, [], fetched_at="2026-07-25T00:00:00Z")
    loaded = load_cached_items(tmp_path, key, now="2026-07-25T01:00:00Z")
    assert loaded == []
    assert loaded is not None


def test_query_caches_per_year_so_a_narrower_rerun_hits(tmp_path, monkeypatch):
    """A second query over a sub-range must reuse the first query's cached years.

    This is the resume path: acquire_wofs_cache derives its query range from
    the years still missing, so after a partial failure the range narrows and
    a whole-range cache key would always miss.
    """
    import geopandas as gpd
    import pystac
    from shapely.geometry import box

    import hydroseason._io_geo as io_geo

    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 1.0, 1.0)]}, crs="EPSG:4326")

    def _dated_item(item_id: str, date: str) -> pystac.Item:
        payload = _item_dict(item_id)
        payload["properties"]["datetime"] = date
        return pystac.Item.from_dict(payload)

    remote_items = [
        _dated_item("i2014", "2014-06-15T00:00:00Z"),
        _dated_item("i2015", "2015-06-15T00:00:00Z"),
    ]

    calls = []

    def _fake_collect(client, **kwargs):
        calls.append(kwargs["datetime"])
        start, end = kwargs["datetime"].split("/")
        return [
            item
            for item in remote_items
            if start <= item.properties["datetime"][:10] <= end
        ]

    monkeypatch.setattr(io_geo, "_collect_stac_items", _fake_collect)

    class _FakeClient:
        @staticmethod
        def open(url):
            return _FakeClient()

    import sys, types
    fake_module = types.ModuleType("pystac_client")
    fake_module.Client = _FakeClient
    monkeypatch.setitem(sys.modules, "pystac_client", fake_module)

    first, _ = io_geo._query_wofs_items(
        "https://example.test/stac", "ga_ls_wo_3", aoi,
        "2014-01-01", "2015-12-31", item_cache_root=tmp_path,
    )
    assert {item.id for item in first} == {"i2014", "i2015"}
    assert len(calls) == 2  # one network query per calendar year

    calls.clear()
    second, _ = io_geo._query_wofs_items(
        "https://example.test/stac", "ga_ls_wo_3", aoi,
        "2015-01-01", "2015-12-31", item_cache_root=tmp_path,
    )
    assert {item.id for item in second} == {"i2015"}
    assert calls == []  # fully served from the per-year cache
