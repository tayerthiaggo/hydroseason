import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from hydroseason._io_wofs_zarr import (
    WOfSCacheHandle,
    WOfSCacheIdentity,
    WOfSCacheRequest,
    cache_writer_lock,
    create_cache_handle,
    preflight_cache_space,
    require_cached_request,
    resolve_cached_request,
)


def _request() -> WOfSCacheRequest:
    return WOfSCacheRequest(
        stac_url="https://example.invalid/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="2015-01-01",
        end_date="2025-12-31",
        crs="EPSG:3577",
        resolution=30.0,
        classifier_version=1,
        groupby="solar_day",
        majority=True,
        planner_version=1,
        schema_version=1,
    )


def test_every_data_semantic_changes_request_digest():
    base = _request()
    for field, changed in {
        "stac_url": "https://other.invalid/stac",
        "collection": "other",
        "aoi_sha256": "b" * 64,
        "start_date": "2016-01-01",
        "end_date": "2024-12-31",
        "crs": "EPSG:4326",
        "resolution": 60.0,
        "classifier_version": 2,
        "groupby": "time",
        "majority": False,
        "planner_version": 2,
        "schema_version": 2,
    }.items():
        assert dataclasses.replace(base, **{field: changed}).request_digest() != base.request_digest()


def test_transform_changes_full_identity_not_request_digest():
    request = _request()
    left = WOfSCacheIdentity.from_request(request, shape=(10, 20), transform=(30, 0, 0, 0, -30, 0))
    right = WOfSCacheIdentity.from_request(request, shape=(10, 20), transform=(30, 0, 30, 0, -30, 0))
    assert left.request_digest == right.request_digest
    assert left.digest != right.digest


def test_same_request_writer_is_rejected(tmp_path):
    with cache_writer_lock(tmp_path, "abc"):
        with pytest.raises(RuntimeError, match="already being written"):
            with cache_writer_lock(tmp_path, "abc"):
                pass


def test_offline_lookup_uses_local_index_without_network(tmp_path):
    identity = WOfSCacheIdentity.from_request(
        _request(), shape=(10, 20), transform=(30, 0, 0, 0, -30, 0)
    )
    handle = create_cache_handle(tmp_path, identity)
    assert resolve_cached_request(tmp_path, _request(), offline=True) == handle


def test_offline_lookup_lists_missing_dates(tmp_path):
    with pytest.raises(FileNotFoundError, match="2015-01-01.*2025-12-31"):
        require_cached_request(tmp_path, _request(), offline=True)


def test_preflight_fails_before_work_when_free_space_is_too_small(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(OSError, match="requires 1,800 bytes"):
        preflight_cache_space(tmp_path, shape=(10, 10), months=12, headroom=1.5)
