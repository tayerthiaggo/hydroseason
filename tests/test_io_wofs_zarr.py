import dataclasses
import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from affine import Affine

from hydroseason._spatial_plan import GridWindow
from hydroseason._io_wofs_zarr import (
    WOFS_CACHE_SCHEMA_VERSION,
    WOfSCacheHandle,
    WOfSCacheIdentity,
    WOfSCacheRequest,
    cache_writer_lock,
    completed_years,
    create_cache_handle,
    open_completed_mask_cache,
    preflight_cache_space,
    require_cached_request,
    resolve_cached_request,
    validate_annual_group,
    write_annual_group,
)

pytest.importorskip("rioxarray")


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
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
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
        "schema_version": WOFS_CACHE_SCHEMA_VERSION + 1,
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


def test_offline_lookup_rejects_store_not_named_for_full_identity(tmp_path):
    identity = WOfSCacheIdentity.from_request(
        _request(), shape=(10, 20), transform=(30, 0, 0, 0, -30, 0)
    )
    handle = create_cache_handle(tmp_path, identity)
    legacy_store = tmp_path / "stores" / identity.request_digest
    legacy_store.parent.mkdir()
    shutil.move(handle.path, legacy_store)
    index_path = tmp_path / "index" / f"{identity.request_digest}.json"
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    index_payload["store"] = f"stores/{identity.request_digest}"
    index_path.write_text(json.dumps(index_payload), encoding="utf-8")

    assert resolve_cached_request(tmp_path, _request(), offline=True) is None


def test_full_grid_identities_use_physically_distinct_stores(tmp_path):
    request = _request()
    old_grid = WOfSCacheIdentity.from_request(
        request, shape=(2, 2), transform=(30, 0, 0, 0, -30, 0)
    )
    new_grid = WOfSCacheIdentity.from_request(
        request, shape=(2, 2), transform=(30, 0, 30, 0, -30, 0)
    )

    old_handle = create_cache_handle(tmp_path, old_grid)
    new_handle = create_cache_handle(tmp_path, new_grid)

    assert old_handle.path != new_handle.path
    assert old_handle.path.name == f"{old_grid.digest}.zarr"
    assert new_handle.path.name == f"{new_grid.digest}.zarr"
    assert completed_years(new_handle) == set()


def test_offline_lookup_lists_missing_dates(tmp_path):
    with pytest.raises(FileNotFoundError, match="2015-01-01.*2025-12-31"):
        require_cached_request(tmp_path, _request(), offline=True)


def test_preflight_fails_before_work_when_free_space_is_too_small(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(OSError, match="requires 1,800 bytes"):
        preflight_cache_space(tmp_path, shape=(10, 10), months=12, headroom=1.5)


def _canonical_cube(*, shape: tuple[int, int, int], fill: int) -> xr.DataArray:
    time, height, width = shape
    transform = Affine(30, 0, 1000, 0, -30, 2000)
    values = np.full(shape, fill, dtype=np.int8)
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2015-01-01", periods=time, freq="MS"),
            "y": transform.f + (np.arange(height) + 0.5) * transform.e,
            "x": transform.c + (np.arange(width) + 0.5) * transform.a,
        },
        name="water_mask",
    ).rio.write_crs(3577).rio.write_transform(transform)


def _handle_for_cube(tmp_path: Path, cube: xr.DataArray) -> WOfSCacheHandle:
    time_index = pd.DatetimeIndex(np.asarray(cube.time.values))
    request = dataclasses.replace(
        _request(),
        start_date=time_index[0].strftime("%Y-%m-%d"),
        end_date=time_index[-1].strftime("%Y-%m-%d"),
    )
    identity = WOfSCacheIdentity.from_request(
        request,
        shape=(cube.sizes["y"], cube.sizes["x"]),
        transform=tuple(cube.rio.transform())[:6],
    )
    return create_cache_handle(tmp_path, identity)


def test_annual_writer_skips_wholly_outside_chunks_and_reads_fill(tmp_path):
    mask = _canonical_cube(shape=(12, 512, 1024), fill=-2)
    mask.loc[{"x": mask.x[:512]}] = 1
    handle = _handle_for_cube(tmp_path, mask)

    stats = write_annual_group(
        handle, 2015, mask.chunk({"time": 1, "y": 512, "x": 512}),
        windows=(GridWindow("parent", 0, 512, 0, 1024),), item_ids=("a", "b"),
    )

    opened = open_completed_mask_cache(handle, "2015-01-01", "2015-12-31")
    assert stats.chunks_considered == 24
    assert stats.chunks_written == 12
    assert (opened.isel(x=slice(512, 1024)).compute().values == -2).all()
    assert set(np.unique(opened.compute())) == {-2, 1}


def test_partial_annual_directory_is_not_a_cache_hit(tmp_path):
    mask = _canonical_cube(shape=(12, 2, 2), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    partial = handle.path / "years" / ".2015.incomplete-test"
    partial.mkdir(parents=True)
    assert completed_years(handle) == set()


def test_completed_years_rejects_marker_only_group(tmp_path):
    mask = _canonical_cube(shape=(12, 2, 2), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    corrupt = handle.path / "years" / "2015"
    corrupt.mkdir(parents=True)
    (corrupt / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (corrupt / "complete.json").write_text(
        json.dumps({"year": 2015, "item_digest": "not-enough"}), encoding="utf-8"
    )

    assert completed_years(handle) == set()


def test_completed_years_rejects_truncated_year_for_full_year_request(tmp_path):
    mask = _canonical_cube(shape=(6, 2, 2), fill=0)
    identity = WOfSCacheIdentity.from_request(
        _request(),
        shape=(mask.sizes["y"], mask.sizes["x"]),
        transform=tuple(mask.rio.transform())[:6],
    )
    handle = create_cache_handle(tmp_path, identity)
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 2}),
        windows=(GridWindow("parent", 0, 2, 0, 2),),
        item_ids=("a",),
    )

    assert completed_years(handle) == set()
    with pytest.raises(ValueError, match="cache request"):
        open_completed_mask_cache(handle, "2015-01-01", "2015-12-31")


def test_completed_years_uses_metadata_checks_without_full_validation(monkeypatch, tmp_path):
    mask = _canonical_cube(shape=(2, 2, 2), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 2}),
        windows=(GridWindow("parent", 0, 2, 0, 2),),
        item_ids=("a",),
    )
    monkeypatch.setattr(
        "hydroseason._io_wofs_zarr.validate_annual_group",
        Mock(side_effect=AssertionError("completed_years must not scan annual pixels")),
    )

    assert completed_years(handle) == {2015}


def test_writer_does_not_allocate_full_grid_count_arrays(monkeypatch, tmp_path):
    import hydroseason._io_wofs_zarr as zarr_io

    mask = _canonical_cube(shape=(2, 513, 513), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    real_zeros = np.zeros

    def reject_full_grid_zeros(shape, *args, **kwargs):
        if isinstance(shape, tuple) and shape == (513, 513):
            raise AssertionError("full-grid count allocation")
        return real_zeros(shape, *args, **kwargs)

    monkeypatch.setattr(zarr_io.np, "zeros", reject_full_grid_zeros)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 512, "x": 512}),
        windows=(GridWindow("parent", 0, 513, 0, 513),),
        item_ids=("a",),
    )


def test_validation_reads_water_mask_in_storage_chunks(monkeypatch, tmp_path):
    import zarr

    mask = _canonical_cube(shape=(2, 513, 513), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 512, "x": 512}),
        windows=(GridWindow("parent", 0, 513, 0, 513),),
        item_ids=("a",),
    )
    path = handle.path / "years" / "2015"
    array_type = type(zarr.open_group(path, mode="r")["water_mask"])
    original_getitem = array_type.__getitem__
    reads = []

    def reject_full_mask_read(array, key):
        if getattr(array, "path", "") == "water_mask":
            reads.append(key)
            if key == slice(None):
                raise AssertionError("full water_mask read")
        return original_getitem(array, key)

    monkeypatch.setattr(array_type, "__getitem__", reject_full_mask_read)

    validate_annual_group(
        path,
        expected_year=2015,
        expected_shape=(2, 513, 513),
        expected_transform=tuple(mask.rio.transform())[:6],
    )
    assert len(reads) >= 8


def test_annual_content_digest_changes_when_rewritten_pixels_change(tmp_path):
    first = _canonical_cube(shape=(2, 2, 2), fill=0)
    first.values[:, 0, 0] = 1
    second = _canonical_cube(shape=(2, 2, 2), fill=0)
    second.values[:, 0, 1] = 1
    handle = _handle_for_cube(tmp_path, first)
    window = (GridWindow("parent", 0, 2, 0, 2),)

    write_annual_group(handle, 2015, first.chunk({"time": 1}), windows=window, item_ids=("a",))
    first_complete = json.loads(
        (handle.path / "years" / "2015" / "complete.json").read_text(encoding="utf-8")
    )
    write_annual_group(
        handle, 2015, second.chunk({"time": 1}), windows=window, item_ids=("a",), overwrite=True
    )
    second_complete = json.loads(
        (handle.path / "years" / "2015" / "complete.json").read_text(encoding="utf-8")
    )

    assert first_complete["content_digest"] != second_complete["content_digest"]


def test_writer_renames_only_after_validation(monkeypatch, tmp_path):
    mask = _canonical_cube(shape=(12, 2, 2), fill=0).chunk({"time": 1, "y": 2, "x": 2})
    handle = _handle_for_cube(tmp_path, mask)
    monkeypatch.setattr("hydroseason._io_wofs_zarr.validate_annual_group", Mock(side_effect=ValueError("bad domain")))
    with pytest.raises(ValueError, match="bad domain"):
        write_annual_group(handle, 2015, mask, windows=(GridWindow("parent", 0, 2, 0, 2),), item_ids=("a",))
    assert not (handle.path / "years" / "2015").exists()


def test_reader_rejects_duplicate_or_out_of_order_months(tmp_path):
    import zarr

    mask = _canonical_cube(shape=(12, 2, 2), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    write_annual_group(
        handle, 2015, mask.chunk({"time": 1, "y": 2, "x": 2}),
        windows=(GridWindow("parent", 0, 2, 0, 2),), item_ids=("a",),
    )
    group = zarr.open_group(handle.path / "years" / "2015", mode="r+")
    encoded = group["time"][:]
    group["time"][:] = encoded[::-1]
    with pytest.raises(ValueError, match="strict monthly order"):
        open_completed_mask_cache(handle, "2015-01-01", "2015-12-31")


def test_annual_writer_reports_non_negative_phase_timings(tmp_path):
    mask = _canonical_cube(shape=(12, 512, 512), fill=1).chunk(
        {"time": 1, "y": 512, "x": 512}
    )
    handle = _handle_for_cube(tmp_path, mask)

    stats = write_annual_group(
        handle,
        2015,
        mask,
        windows=(GridWindow("r0c0", 0, 512, 0, 512),),
        item_ids=("a",),
    )

    assert stats.compute_seconds >= 0.0
    assert stats.encode_write_seconds >= 0.0
    assert stats.validation_seconds >= 0.0

