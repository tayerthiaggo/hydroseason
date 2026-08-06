import dataclasses
import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("dask")
pytest.importorskip("xarray")
pytest.importorskip("affine")

import dask
import xarray as xr
from affine import Affine

from hydroseason._io_wofs_zarr import (
    CONTENT_DIGEST_ALGORITHM,
    WOFS_CACHE_SCHEMA_VERSION,
    WOfSCacheHandle,
    WOfSCacheIdentity,
    WOfSCacheRequest,
    _compute_with_remote_read_retries,
    _content_hasher,
    cache_writer_lock,
    completed_years,
    create_cache_handle,
    open_completed_dual_extent_counts,
    open_completed_extent_counts,
    open_completed_mask_cache,
    preflight_cache_space,
    require_cached_request,
    resolve_cached_request,
    validate_annual_group,
    write_annual_group,
    write_empty_annual_group,
)
from hydroseason._spatial_plan import GridWindow

pytest.importorskip("rioxarray")


def test_content_hasher_is_blake2b_and_is_fresh_each_call():
    assert CONTENT_DIGEST_ALGORITHM == "blake2b"

    first = _content_hasher()
    assert first.name == "blake2b"

    # Each call must return an independent hasher, never a shared module-level
    # object -- write_annual_group runs concurrently under year_workers, and a
    # shared hasher would interleave two years' bytes into one digest.
    first.update(b"year-1986")
    second = _content_hasher()
    assert second.hexdigest() != first.hexdigest()
    assert second.hexdigest() == _content_hasher().hexdigest()


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


def _base_request(**overrides):
    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOFS_CLASSIFIER_VERSION,
        WOFS_PLANNER_VERSION,
        WOfSCacheRequest,
    )

    fields = {
        "stac_url": "https://example.test/stac",
        "collection": "ga_ls_wo_3",
        "aoi_sha256": "a" * 64,
        "start_date": "1986-05-01",
        "end_date": "2026-06-01",
        "crs": "3577",
        "resolution": 30.0,
        "classifier_version": WOFS_CLASSIFIER_VERSION,
        "groupby": "solar_day",
        "majority": True,
        "planner_version": WOFS_PLANNER_VERSION,
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
    }
    fields.update(overrides)
    return WOfSCacheRequest(**fields)


def test_wet_mask_digest_separates_pruned_from_unpruned_stores():
    """A pruned cache must never share a store with an unpruned one: outside
    the mask a pruned year is permanently -2, which is indistinguishable from
    genuinely dry."""
    unpruned = _base_request()
    pruned = _base_request(wet_mask_sha256="b" * 64)
    other_mask = _base_request(wet_mask_sha256="c" * 64)

    assert unpruned.wet_mask_sha256 is None
    assert pruned.request_digest() != unpruned.request_digest()
    assert pruned.request_digest() != other_mask.request_digest()
    # Same mask, same digest -- a second pruned run reuses the first's store.
    assert pruned.request_digest() == _base_request(wet_mask_sha256="b" * 64).request_digest()


def test_absent_wet_mask_preserves_the_legacy_request_digest():
    """Existing full-coverage caches on disk must stay reachable: with no wet
    mask the digest payload must be byte-identical to the pre-field version."""
    request = _base_request()
    payload = request._digest_payload()
    assert "wet_mask_sha256" not in payload


# ---------------------------------------------------------------------------
# W2.1: planning-footprint / composite-bundle cache-identity tests (Step 2)
# ---------------------------------------------------------------------------


def test_absent_footprint_fields_preserve_the_legacy_request_digest():
    """Existing full-coverage/wet_aoi-pruned caches on disk must stay
    reachable: with no planning footprint the digest payload must be
    byte-identical to the pre-footprint-field version (same guarantee as
    test_absent_wet_mask_preserves_the_legacy_request_digest, extended to the
    new footprint fields)."""
    request = _base_request()
    payload = request._digest_payload()
    assert "footprint_digest" not in payload
    assert "footprint_factor" not in payload
    assert "footprint_safety_cells" not in payload
    assert "footprint_covered_years" not in payload


def test_single_mask_composite_bundle_is_the_default_and_preserves_request_digest():
    """composite_bundle="single_mask" is the default and must not perturb
    the digest of a request that never mentions it -- pre-rename "legacy"
    callers' caches stay reachable byte-for-byte via the accepted alias."""
    request = _base_request()
    assert request.composite_bundle == "single_mask"
    assert "composite_bundle" not in request._digest_payload()
    explicit_default = _base_request(composite_bundle="single_mask")
    assert explicit_default.request_digest() == request.request_digest()
    explicit_legacy_alias = _base_request(composite_bundle="legacy")
    assert explicit_legacy_alias.request_digest() == request.request_digest()


def test_footprint_digest_changes_request_digest():
    base = _base_request()
    changed = _base_request(footprint_digest="d" * 64, footprint_factor=4,
                             footprint_safety_cells=1, footprint_covered_years=(2015,))
    other_digest = _base_request(footprint_digest="e" * 64, footprint_factor=4,
                                  footprint_safety_cells=1, footprint_covered_years=(2015,))
    assert changed.request_digest() != base.request_digest()
    assert changed.request_digest() != other_digest.request_digest()


def test_footprint_factor_changes_request_digest():
    common = dict(footprint_digest="d" * 64, footprint_safety_cells=1, footprint_covered_years=(2015,))
    a = _base_request(footprint_factor=4, **common)
    b = _base_request(footprint_factor=8, **common)
    assert a.request_digest() != b.request_digest()


def test_footprint_safety_cells_changes_request_digest():
    common = dict(footprint_digest="d" * 64, footprint_factor=4, footprint_covered_years=(2015,))
    a = _base_request(footprint_safety_cells=1, **common)
    b = _base_request(footprint_safety_cells=2, **common)
    assert a.request_digest() != b.request_digest()


def test_footprint_covered_years_changes_request_digest():
    common = dict(footprint_digest="d" * 64, footprint_factor=4, footprint_safety_cells=1)
    a = _base_request(footprint_covered_years=(2015,), **common)
    b = _base_request(footprint_covered_years=(2015, 2016), **common)
    assert a.request_digest() != b.request_digest()


def test_composite_bundle_changes_request_digest():
    single_mask = _base_request(composite_bundle="single_mask")
    hydrofragments = _base_request(composite_bundle="hydrofragments_v1")
    assert single_mask.request_digest() != hydrofragments.request_digest()


def test_worker_counts_never_change_request_digest():
    """read_workers/year_workers are execution parallelism knobs, never part
    of a cache's data-semantic identity: two runs that agree on everything
    else but differ only in worker count must resolve to the SAME store,
    and preserve deterministic byte-identical output across worker counts
    (see the global constraint). WOfSCacheRequest simply never has fields
    for worker counts -- assert that stays true."""
    field_names = {f.name for f in dataclasses.fields(WOfSCacheRequest)}
    assert "read_workers" not in field_names
    assert "year_workers" not in field_names


def test_footprint_and_composite_bundle_are_independent_of_each_other():
    """Every listed field -- factor, safety halo, footprint digest, covered
    years, and composite bundle -- must EACH independently change identity,
    not just in combination."""
    base = _base_request(
        footprint_digest="d" * 64, footprint_factor=4,
        footprint_safety_cells=1, footprint_covered_years=(2015,),
        composite_bundle="single_mask",
    )
    only_bundle_changed = dataclasses.replace(base, composite_bundle="hydrofragments_v1")
    only_factor_changed = dataclasses.replace(base, footprint_factor=8)
    only_safety_changed = dataclasses.replace(base, footprint_safety_cells=2)
    only_years_changed = dataclasses.replace(base, footprint_covered_years=(2015, 2016))
    only_digest_changed = dataclasses.replace(base, footprint_digest="e" * 64)

    digests = {
        base.request_digest(),
        only_bundle_changed.request_digest(),
        only_factor_changed.request_digest(),
        only_safety_changed.request_digest(),
        only_years_changed.request_digest(),
        only_digest_changed.request_digest(),
    }
    assert len(digests) == 6


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


def _handle_for_cube(
    tmp_path: Path,
    cube: xr.DataArray,
    *,
    request: WOfSCacheRequest | None = None,
) -> WOfSCacheHandle:
    time_index = pd.DatetimeIndex(np.asarray(cube.time.values))
    base_request = _request() if request is None else request
    request = dataclasses.replace(
        base_request,
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


def test_remote_read_retry_recomputes_transient_tiff_failure(monkeypatch):
    calls = []

    def flaky_compute(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            raise RuntimeError("TIFFReadEncodedTile() failed: got 0 bytes")
        return ("ok",)

    monkeypatch.setattr("hydroseason._io_wofs_zarr.time.sleep", lambda _seconds: None)
    result = _compute_with_remote_read_retries(
        flaky_compute,
        ("lazy-block",),
        {},
    )

    assert result == ("ok",)
    assert len(calls) == 2


def test_annual_writer_leaves_dask_worker_count_unset_by_default(monkeypatch, tmp_path):
    seen = []
    real_compute = dask.compute

    def capture(*args, **kwargs):
        seen.append(kwargs.copy())
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(dask, "compute", capture)
    mask = _canonical_cube(shape=(12, 512, 512), fill=1).chunk(
        {"time": 1, "y": 512, "x": 512}
    )
    write_annual_group(
        _handle_for_cube(tmp_path, mask),
        2015,
        mask,
        windows=(GridWindow("r0c0", 0, 512, 0, 512),),
        item_ids=("a",),
    )

    assert seen
    assert all("num_workers" not in kwargs for kwargs in seen)


def test_annual_writer_honours_explicit_worker_override(monkeypatch, tmp_path):
    seen = []
    real_compute = dask.compute

    def capture(*args, **kwargs):
        seen.append(kwargs.copy())
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(dask, "compute", capture)
    mask = _canonical_cube(shape=(12, 512, 512), fill=1).chunk(
        {"time": 1, "y": 512, "x": 512}
    )
    write_annual_group(
        _handle_for_cube(tmp_path, mask),
        2015,
        mask,
        windows=(GridWindow("r0c0", 0, 512, 0, 512),),
        item_ids=("a",),
        read_workers=3,
    )

    assert any(kwargs.get("num_workers") == 3 for kwargs in seen)


def test_annual_writer_respects_compute_batch_size(monkeypatch, tmp_path):
    seen = []
    real_compute = dask.compute

    def capture(*args, **kwargs):
        seen.append(args)
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(dask, "compute", capture)
    mask = _canonical_cube(shape=(1, 512, 17 * 512), fill=1).chunk(
        {"time": 1, "y": 512, "x": 512}
    )
    windows = tuple(GridWindow(f"r0c{i}", 0, 512, i * 512, (i + 1) * 512) for i in range(17))
    write_annual_group(
        _handle_for_cube(tmp_path, mask),
        2015,
        mask,
        windows=windows,
        item_ids=("a",),
        compute_batch_size=8,
    )

    assert [len(args) for args in seen] == [8, 8, 1]


def test_annual_writer_persists_exact_monthly_extent_counts(tmp_path):
    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )
    extent = open_completed_extent_counts(handle, "2015-01-01", "2015-02-01")

    assert extent is not None
    assert extent["n_aoi"].tolist() == [5, 5]
    assert extent["n_valid"].tolist() == [4, 4]
    assert extent["n_water"].tolist() == [2, 2]
    assert extent["n_invalid"].tolist() == [1, 1]
    assert extent["extent_pct"].tolist() == [50.0, 50.0]
    assert extent["invalid_pct"].tolist() == [20.0, 20.0]


def test_pruned_extent_counts_do_not_infer_full_aoi_denominator_from_footprints(tmp_path):
    """A pruned store cannot reconstruct monthly full-AOI valid/invalid counts
    from fixed geometry footprints, so the fast reader must fail closed."""
    import geopandas as gpd
    from shapely.geometry import box

    from hydroseason._io_wofs_zarr import record_cache_footprints

    mask = _canonical_cube(shape=(2, 2, 4), fill=-2)
    mask.values[:, :, :] = [
        [[1, 0, -2, -2], [1, 0, -2, -2]],
        [[1, 0, -2, -2], [1, 0, -2, -2]],
    ]
    handle = _handle_for_cube(
        tmp_path,
        mask,
        request=dataclasses.replace(_request(), wet_mask_sha256="b" * 64),
    )
    full_aoi = gpd.GeoDataFrame(
        {"geometry": [box(999.0, 1941.0, 1119.0, 1999.0)]}, crs="EPSG:3577"
    )
    analysis_footprint = gpd.GeoDataFrame(
        {"geometry": [box(999.0, 1941.0, 1059.0, 1999.0)]}, crs="EPSG:3577"
    )
    footprints = record_cache_footprints(
        handle,
        full_aoi_gdf=full_aoi,
        analysis_footprint_gdf=analysis_footprint,
        shape=(2, 4),
        transform=(30.0, 0.0, 1000.0, 0.0, -30.0, 2000.0),
        crs="EPSG:3577",
    )
    assert footprints.aoi_pixel_count == 8
    assert footprints.analysis_pixel_count == 4

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 4}),
        windows=(GridWindow("r0c0", 0, 2, 0, 4),),
        item_ids=("a",),
    )

    assert open_completed_extent_counts(handle, "2015-01-01", "2015-01-01") is None


def test_pruned_extent_counts_fail_closed_when_footprints_are_missing(tmp_path):
    mask = _canonical_cube(shape=(2, 2, 4), fill=-2)
    mask.values[:, :, :] = [
        [[1, 0, -2, -2], [1, 0, -2, -2]],
        [[1, 0, -2, -2], [1, 0, -2, -2]],
    ]
    handle = _handle_for_cube(
        tmp_path,
        mask,
        request=dataclasses.replace(_request(), wet_mask_sha256="b" * 64),
    )
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 4}),
        windows=(GridWindow("r0c0", 0, 2, 0, 4),),
        item_ids=("a",),
    )

    assert open_completed_extent_counts(handle, "2015-01-01", "2015-01-01") is None


def test_load_wofs_monthly_extent_rejects_pruned_zarr_without_exact_counts(monkeypatch, tmp_path):
    """The legacy extent facade must not fall through to monthly reduction over
    pruned masks after the exact-count fast path fails closed."""
    from hydroseason._io_extent_cache import load_wofs_monthly_extent

    mask = _canonical_cube(shape=(2, 2, 4), fill=-2)
    mask.values[:, :, :] = [
        [[1, 0, -2, -2], [1, 0, -2, -2]],
        [[1, 0, -2, -2], [1, 0, -2, -2]],
    ]
    handle = _handle_for_cube(
        tmp_path,
        mask,
        request=dataclasses.replace(_request(), wet_mask_sha256="b" * 64),
    )
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 4}),
        windows=(GridWindow("r0c0", 0, 2, 0, 4),),
        item_ids=("a",),
    )
    monkeypatch.setattr("hydroseason.io.acquire_wofs_cache", Mock(return_value=handle))

    with pytest.raises(ValueError, match="exact full-AOI monthly extent counts"):
        load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            object(),
            "2015-01-01",
            "2015-01-01",
            mask_cache_dir=tmp_path,
            use_historical_water_mask=False,
        )


def test_load_wofs_monthly_extent_rejects_explicit_wet_aoi_pruned_zarr(monkeypatch, tmp_path):
    """Explicit wet_aoi callers also create pruned stores, so they must hit the
    same fail-closed path before monthly reduction over pruned masks."""
    from hydroseason._io_extent_cache import load_wofs_monthly_extent

    mask = _canonical_cube(shape=(2, 2, 4), fill=-2)
    mask.values[:, :, :] = [
        [[1, 0, -2, -2], [1, 0, -2, -2]],
        [[1, 0, -2, -2], [1, 0, -2, -2]],
    ]
    handle = _handle_for_cube(
        tmp_path,
        mask,
        request=dataclasses.replace(_request(), wet_mask_sha256="b" * 64),
    )
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 4}),
        windows=(GridWindow("r0c0", 0, 2, 0, 4),),
        item_ids=("a",),
    )
    monkeypatch.setattr("hydroseason.io.acquire_wofs_cache", Mock(return_value=handle))

    with pytest.raises(ValueError, match="exact full-AOI monthly extent counts"):
        load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            object(),
            "2015-01-01",
            "2015-01-01",
            mask_cache_dir=tmp_path,
            use_historical_water_mask=False,
            wet_aoi=object(),
        )


def test_write_annual_group_persists_dual_extent_counts_when_given(tmp_path):
    """Step 3 (W2.2): write_annual_group must persist a parallel
    dual_extent_counts.json when handed already-reduced secondary
    (max_water) counts, without touching extent_counts.json (the primary
    composite's own artifact) at all.

    Same 2x3 grid/fixture as
    test_annual_writer_persists_exact_monthly_extent_counts, but with a
    secondary (max_water) composite whose per-pixel counts genuinely
    diverge from the primary at one cell (mirrors the hand-traced pixel in
    test_io.py's test_hydrofragments_v1_dual_counts_diverge_from_majority...):
    the primary (majority) mask marks (0, 0) as dry (0) in month 1, but the
    hand-supplied secondary wet_count at that same cell/month is 1 (some
    day observed it wet) -- proving dual_extent_counts really is a SEPARATE
    reduction, not a relabelling of the primary mask's own counts.
    """
    import geopandas as gpd
    from shapely.geometry import box

    from hydroseason._io_wofs_zarr import _sha256_digest, record_cache_footprints

    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[0, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)

    # A full-AOI/analysis-footprint manifest block must already exist by the
    # time write_annual_group runs (acquire_wofs_cache always calls
    # record_cache_footprints before any year is written -- see
    # _io_wofs_acquire.py); reproduce that ordering here rather than
    # fabricating the fixed denominators.
    full_aoi = gpd.GeoDataFrame(
        {"geometry": [box(1000.0, 1940.0, 1090.0, 2000.0)]}, crs="EPSG:3577"
    )
    footprints = record_cache_footprints(
        handle,
        full_aoi_gdf=full_aoi,
        analysis_footprint_gdf=full_aoi,
        shape=(2, 3),
        transform=(30.0, 0.0, 1000.0, 0.0, -30.0, 2000.0),
        crs="EPSG:3577",
    )

    # Secondary (max_water) per-month wet/clear counts: at (0, 0), month 1,
    # the primary composite says dry (0) but the secondary composite (some
    # day in the month observed water there) says wet -- 1 -- the
    # divergence this test exists to prove is really persisted.
    wet_count = np.zeros((2, 2, 3), dtype=np.uint16)
    wet_count[0] = [[1, 0, 0], [0, 1, 0]]
    wet_count[1] = [[0, 0, 0], [0, 1, 1]]
    clear_count = np.zeros((2, 2, 3), dtype=np.uint16)
    clear_count[0] = [[3, 3, 0], [0, 3, 3]]
    clear_count[1] = [[3, 3, 0], [0, 3, 3]]
    dual_counts = xr.Dataset(
        {
            "wet_count": (("time", "y", "x"), wet_count),
            "clear_count": (("time", "y", "x"), clear_count),
        },
        coords={"time": mask.time.values, "y": mask.y.values, "x": mask.x.values},
    )

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
        dual_counts=dual_counts,
    )

    # extent_counts.json (the PRIMARY composite's artifact) is unaffected.
    primary = open_completed_extent_counts(handle, "2015-01-01", "2015-02-01")
    assert primary["n_water"].tolist() == [1, 2]

    sidecar_path = handle.path / "years" / "2015" / "dual_extent_counts.json"
    assert sidecar_path.exists()
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == WOFS_CACHE_SCHEMA_VERSION
    assert payload["year"] == 2015
    assert payload["dates"] == ["2015-01-01", "2015-02-01"]
    assert payload["aoi_pixel_count"] == footprints.aoi_pixel_count
    assert payload["analysis_mask_pixel_count"] == footprints.analysis_pixel_count
    # n_max_water: sum of wet_count per month = month1: 1+0+0+0+1+0=2, month2: 0+0+0+0+1+1=2
    assert payload["n_max_water"] == [2, 2]
    # n_median_water (primary, for cross-check): matches extent_counts.json's n_water.
    assert payload["n_median_water"] == [1, 2]
    # n_valid_analysis: sum of clear_count per month.
    assert payload["n_valid_analysis"] == [12, 12]

    check_payload = {k: v for k, v in payload.items() if k != "content_digest"}
    assert _sha256_digest(check_payload) == payload["content_digest"]


def test_write_annual_group_omits_dual_extent_counts_by_default(tmp_path):
    """composite_bundle='legacy' (dual_counts=None, the default) must write
    no dual_extent_counts.json at all -- a hard requirement (Step 5), not
    merely an empty/zeroed file."""
    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    assert not (handle.path / "years" / "2015" / "dual_extent_counts.json").exists()


def test_open_completed_dual_extent_counts_round_trips_persisted_values(tmp_path):
    """Step 4 (W2.2): open_completed_dual_extent_counts must read back
    exactly what write_annual_group persisted, over a real completed store,
    with the fixed aoi/analysis-mask pixel-count denominators broadcast per
    row (one fixed value per row, not per-month-varying)."""
    import geopandas as gpd
    from shapely.geometry import box

    from hydroseason._io_wofs_zarr import record_cache_footprints

    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[0, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)

    full_aoi = gpd.GeoDataFrame(
        {"geometry": [box(1000.0, 1940.0, 1090.0, 2000.0)]}, crs="EPSG:3577"
    )
    footprints = record_cache_footprints(
        handle,
        full_aoi_gdf=full_aoi,
        analysis_footprint_gdf=full_aoi,
        shape=(2, 3),
        transform=(30.0, 0.0, 1000.0, 0.0, -30.0, 2000.0),
        crs="EPSG:3577",
    )

    wet_count = np.zeros((2, 2, 3), dtype=np.uint16)
    wet_count[0] = [[1, 0, 0], [0, 1, 0]]
    wet_count[1] = [[0, 0, 0], [0, 1, 1]]
    clear_count = np.zeros((2, 2, 3), dtype=np.uint16)
    clear_count[0] = [[3, 3, 0], [0, 3, 3]]
    clear_count[1] = [[3, 3, 0], [0, 3, 3]]
    dual_counts = xr.Dataset(
        {
            "wet_count": (("time", "y", "x"), wet_count),
            "clear_count": (("time", "y", "x"), clear_count),
        },
        coords={"time": mask.time.values, "y": mask.y.values, "x": mask.x.values},
    )

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
        dual_counts=dual_counts,
    )

    result = open_completed_dual_extent_counts(handle, "2015-01-01", "2015-02-01")

    assert result is not None
    assert result["n_max_water"].tolist() == [2, 2]
    assert result["n_median_water"].tolist() == [1, 2]
    assert result["n_valid_analysis"].tolist() == [12, 12]
    assert result["aoi_pixel_count"].tolist() == [footprints.aoi_pixel_count] * 2
    assert result["analysis_mask_pixel_count"].tolist() == [footprints.analysis_pixel_count] * 2


def test_open_completed_dual_extent_counts_returns_none_for_legacy_store(tmp_path):
    """A store acquired with composite_bundle='legacy' (dual_counts=None)
    never writes dual_extent_counts.json, so the reader must fail closed
    (return None), never fabricate/approximate one from the primary mask."""
    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    assert open_completed_dual_extent_counts(handle, "2015-01-01", "2015-12-01") is None


def test_legacy_write_annual_group_output_is_byte_identical_to_pre_w22(tmp_path):
    """Step 5 (W2.2): a REAL regression proof, not just "the code looks
    unchanged" -- these exact digests were captured by running this same
    fixture through write_annual_group on the pre-W2.2 commit (b6816da,
    before dual_counts/composite_bundle threading existed in this module),
    then hand-confirmed identical after this task's changes landed (a
    git-stash A/B diff of the full JSON summary below was byte-for-byte
    equal). Hardcoding them here means any FUTURE change that perturbs
    legacy's compute path, content digest, or extent_counts.json values
    fails this test immediately, rather than relying on a one-time manual
    comparison that itself isn't re-checked by CI.

    ``extent_payload["content_digest"]`` was re-pinned for Task 4's
    WOFS_CACHE_SCHEMA_VERSION 3 -> 4 bump: extent_counts.json embeds
    schema_version in the hashed payload, so bumping it necessarily changes
    this one digest even though the underlying n_aoi/n_valid/n_water values
    (asserted below) are byte-identical to before -- confirmed by hand
    before repinning, exactly like the original pinning process this
    docstring describes.
    """
    rng = np.random.default_rng(1234)
    shape = (12, 64, 96)
    time_len, height, width = shape
    values = rng.choice(
        [1, 0, -1, -2], size=shape, p=[0.4, 0.4, 0.1, 0.1]
    ).astype(np.int8)
    transform = Affine(30, 0, 1000, 0, -30, 2000)
    mask = xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2015-01-01", periods=time_len, freq="MS"),
            "y": transform.f + (np.arange(height) + 0.5) * transform.e,
            "x": transform.c + (np.arange(width) + 0.5) * transform.a,
        },
        name="water_mask",
    ).rio.write_crs(3577).rio.write_transform(transform)
    handle = _handle_for_cube(tmp_path, mask)

    stats = write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 32, "x": 32}),
        windows=(GridWindow("parent", 0, 64, 0, 96),),
        item_ids=("a", "b", "c"),
    )

    complete_payload = json.loads(
        (handle.path / "years" / "2015" / "complete.json").read_text(encoding="utf-8")
    )
    extent_payload = json.loads(
        (handle.path / "years" / "2015" / "extent_counts.json").read_text(encoding="utf-8")
    )

    assert not (handle.path / "years" / "2015" / "dual_extent_counts.json").exists()
    assert stats.task_count == 72
    assert stats.chunks_considered == 12
    assert stats.chunks_written == 12
    assert stats.loaded_pixels == 73728
    assert complete_payload["item_digest"] == (
        "19731455d65161bc54c73f8d1a12737058cf5715b7505453bc036c50a0dcb181"
    )
    assert complete_payload["content_digest"] == (
        "53e92bac984e3b3269a4cb849147eff3ec0c4e877cdbb273bb718704984b6994"
        "707b28f2d85eb4e35bc62b0fef617df92177a8d37ad129549e5ac4c7b0f938eb"
    )
    assert extent_payload["content_digest"] == (
        "ccbcf2d0433aeb66103d86577ee268b1b14f20885b7407a7a3f56f63b36bf23c"
    )
    assert extent_payload["n_aoi"] == [
        5530, 5509, 5576, 5562, 5535, 5516, 5521, 5518, 5540, 5492, 5554, 5541,
    ]
    assert extent_payload["n_valid"] == [
        4963, 4895, 5016, 4956, 4927, 4900, 4904, 4923, 4878, 4882, 4949, 4932,
    ]
    assert extent_payload["n_water"] == [
        2438, 2473, 2516, 2420, 2422, 2478, 2477, 2420, 2421, 2428, 2533, 2478,
    ]
    assert extent_payload["n_invalid"] == [
        567, 614, 560, 606, 608, 616, 617, 595, 662, 610, 605, 609,
    ]


def test_extent_counts_backfills_legacy_group_from_stored_chunks(tmp_path):
    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    sidecar = handle.path / "years" / "2015" / "extent_counts.json"
    sidecar.unlink()

    extent = open_completed_extent_counts(
        handle, "2015-01-01", "2015-02-01", read_workers=2
    )

    assert extent is not None
    assert extent["n_aoi"].tolist() == [5, 5]
    assert extent["n_valid"].tolist() == [4, 4]
    assert extent["n_water"].tolist() == [2, 2]
    assert extent["n_invalid"].tolist() == [1, 1]
    assert sidecar.exists()
    assert completed_years(handle) == {2015}

    # Backfill must release its Zarr handle so an atomic annual rewrite can
    # remove/rename the group on Windows.
    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
        overwrite=True,
    )


def test_extent_counts_equal_raster_reduction(tmp_path):
    from hydroseason.hydro_year import monthly_water_extent

    mask = _canonical_cube(shape=(12, 512, 512), fill=-2)
    mask.values[:6, 100:200, 100:200] = 1
    mask.values[6:, 200:300, 200:300] = 0
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 512, "x": 512}),
        windows=(GridWindow("r0c0", 0, 512, 0, 512),),
        item_ids=("a",),
    )

    counts_extent = open_completed_extent_counts(handle, "2015-01-01", "2015-12-31")
    mask_extent = monthly_water_extent(open_completed_mask_cache(handle, "2015-01-01", "2015-12-31"), time_block=12)

    pd.testing.assert_frame_equal(counts_extent, mask_extent, check_exact=True)


def test_validation_uses_written_chunk_keys_when_present(tmp_path):
    mask = _canonical_cube(shape=(2, 512, 1024), fill=-2)
    mask.loc[{"x": mask.x[:512]}] = 1
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 512, "x": 512}),
        windows=(GridWindow("r0c0", 0, 512, 0, 512), GridWindow("r0c1", 0, 512, 512, 1024)),
        item_ids=("a",),
    )

    path = handle.path / "years" / "2015"
    payload = json.loads((path / "complete.json").read_text(encoding="utf-8"))

    assert len(payload.get("written_chunk_keys", [])) == 2
    assert all(k[2] == 0 for k in payload["written_chunk_keys"])


def test_write_empty_annual_group_matches_full_path_output(tmp_path):
    """The no-items fast path must produce a group indistinguishable from the
    general path, so a year written either way validates and reads back the
    same."""
    import numpy as np
    import xarray as xr

    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOFS_CLASSIFIER_VERSION,
        WOFS_PLANNER_VERSION,
        WOfSCacheIdentity,
        WOfSCacheRequest,
        completed_years,
        create_cache_handle,
        validate_annual_group,
        write_empty_annual_group,
    )

    times = pd.date_range("1987-01-01", "1987-12-01", freq="MS")
    empty = xr.DataArray(
        np.full((len(times), 64, 64), -2, dtype=np.int8),
        dims=("time", "y", "x"),
        coords={
            "time": times,
            "y": np.arange(64) * -30.0,
            "x": np.arange(64) * 30.0,
        },
    ).rio.write_crs("EPSG:3577").rio.write_transform()

    request = WOfSCacheRequest(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="1987-01-01",
        end_date="1987-12-31",
        crs="3577",
        resolution=30.0,
        classifier_version=WOFS_CLASSIFIER_VERSION,
        groupby="solar_day",
        majority=True,
        planner_version=WOFS_PLANNER_VERSION,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )
    identity = WOfSCacheIdentity.from_request(
        request, shape=(64, 64), transform=tuple(empty.rio.transform())[:6]
    )
    handle = create_cache_handle(tmp_path, identity)

    stats = write_empty_annual_group(handle, 1987, empty)

    assert stats.year == 1987
    assert stats.chunks_written == 0
    assert stats.loaded_pixels == 0
    assert 1987 in completed_years(handle)
    validate_annual_group(
        Path(handle.path) / "years" / "1987",
        expected_year=1987,
        expected_shape=(len(times), 64, 64),
        expected_transform=tuple(empty.rio.transform())[:6],
    )

    counts = json.loads(
        (Path(handle.path) / "years" / "1987" / "extent_counts.json").read_text(encoding="utf-8")
    )
    assert counts["n_water"] == [0] * len(times)
    assert counts["n_valid"] == [0] * len(times)
    assert counts["n_aoi"] == [0] * len(times)


# ---------------------------------------------------------------------------
# Task 4: scientific-mask semantics pinned in the WOfS cache
# ---------------------------------------------------------------------------


def _historical_mask_request(**overrides):
    common = dict(
        historical_mask_sha256="f" * 64,
        historical_mask_product="ga_ls_wo_fq_myear_3",
        historical_mask_version="3",
        historical_mask_item_ids=("item-a", "item-b"),
        historical_mask_lineage=("ga_ls_wo_fq_myear_3", "item-a", "item-b"),
        historical_mask_coverage_start="1986-01-01",
        historical_mask_coverage_end="2026-01-01",
        historical_mask_pixel_count=5,
    )
    common.update(overrides)
    return _base_request(**common)


def test_historical_mask_sha256_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(historical_mask_sha256="e" * 64)
    assert base.request_digest() != changed.request_digest()


def test_historical_mask_product_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(historical_mask_product="other_product")
    assert base.request_digest() != changed.request_digest()


def test_historical_mask_version_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(historical_mask_version="4")
    assert base.request_digest() != changed.request_digest()


def test_historical_mask_item_ids_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(historical_mask_item_ids=("item-a", "item-c"))
    assert base.request_digest() != changed.request_digest()


def test_historical_mask_lineage_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(
        historical_mask_lineage=("ga_ls_wo_fq_myear_3", "item-a", "item-c")
    )
    assert base.request_digest() != changed.request_digest()


def test_historical_mask_coverage_start_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(historical_mask_coverage_start="1987-01-01")
    assert base.request_digest() != changed.request_digest()


def test_historical_mask_coverage_end_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(historical_mask_coverage_end="2027-01-01")
    assert base.request_digest() != changed.request_digest()


def test_historical_mask_pixel_count_changes_request_digest():
    base = _historical_mask_request()
    changed = _historical_mask_request(historical_mask_pixel_count=6)
    assert base.request_digest() != changed.request_digest()


def test_planning_factor_changes_request_digest_independent_of_historical_mask():
    """footprint_factor already changes identity (see
    test_footprint_factor_changes_request_digest above); re-assert it here
    alongside a populated historical mask, to prove the two provenance
    stories (scientific mask vs. planning-only footprint) are genuinely
    independent digest inputs rather than aliasing one another."""
    common = dict(
        footprint_digest="d" * 64, footprint_safety_cells=1, footprint_covered_years=(2015,),
    )
    a = _historical_mask_request(footprint_factor=4, **common)
    b = _historical_mask_request(footprint_factor=8, **common)
    assert a.request_digest() != b.request_digest()


def test_planning_safety_cells_changes_request_digest_independent_of_historical_mask():
    common = dict(footprint_digest="d" * 64, footprint_factor=4, footprint_covered_years=(2015,))
    a = _historical_mask_request(footprint_safety_cells=1, **common)
    b = _historical_mask_request(footprint_safety_cells=2, **common)
    assert a.request_digest() != b.request_digest()


def test_absent_historical_mask_fields_preserve_the_legacy_request_digest():
    """Existing (pre-Task-4) caches on disk must stay reachable: with no
    historical mask supplied, the digest payload must be byte-identical to
    the pre-historical-mask-field version (same guarantee as
    test_absent_footprint_fields_preserve_the_legacy_request_digest)."""
    request = _base_request()
    payload = request._digest_payload()
    for field in (
        "historical_mask_sha256", "historical_mask_product", "historical_mask_version",
        "historical_mask_item_ids", "historical_mask_lineage",
        "historical_mask_coverage_start", "historical_mask_coverage_end",
        "historical_mask_pixel_count",
    ):
        assert field not in payload
    assert request.request_digest() == _base_request().request_digest()


def test_wofs_cache_schema_version_is_4():
    assert WOFS_CACHE_SCHEMA_VERSION == 4


# --- CacheAnalysisMask: persistence and tamper detection ---


def _historical_mask_fixture(*, shape=(2, 3), transform=(30.0, 0.0, 1000.0, 0.0, -30.0, 2000.0)):
    """A minimal in-memory HistoricalWaterMask for CacheAnalysisMask tests.

    ``mask_sha256`` is computed with the real
    :func:`hydroseason._historical_water_mask._mask_digest` (not a
    placeholder) so verification against re-hashed on-disk bytes genuinely
    passes for an untampered artifact -- required for the tamper tests
    below to actually distinguish "tampered" from "the fixture's own digest
    was never real to begin with"."""
    from hydroseason._historical_water_mask import HistoricalWaterMask, _mask_digest

    values = np.zeros(shape, dtype=bool)
    values[0, 0] = True
    values[1, 1] = True
    pixel_count = int(values.sum())
    resolution = (abs(float(transform[0])), abs(float(transform[4])))
    mask_sha256 = _mask_digest(
        values, crs="EPSG:3577", transform=transform, shape=shape, resolution=resolution,
    )
    return HistoricalWaterMask(
        mask=values,
        crs="EPSG:3577",
        transform=transform,
        shape=shape,
        resolution=resolution,
        pixel_count=pixel_count,
        source_product="ga_ls_wo_fq_myear_3",
        source_version="3",
        source_item_ids=("item-a", "item-b"),
        source_lineage=("ga_ls_wo_fq_myear_3", "item-a", "item-b"),
        coverage_start="1986-01-01",
        coverage_end="2026-01-01",
        aoi_sha256="a" * 64,
        mask_sha256=mask_sha256,
    )


def _historical_mask_fixture_with_values(values, *, transform=(30.0, 0.0, 1000.0, 0.0, -30.0, 2000.0)):
    """Like :func:`_historical_mask_fixture`, but for an explicit boolean
    array (used where a test needs the mask's exact footprint to match a
    specific written cube's n_aoi) -- still with a genuinely recomputed
    mask_sha256, never a stale/placeholder one."""
    from hydroseason._historical_water_mask import HistoricalWaterMask, _mask_digest

    values = np.asarray(values, dtype=bool)
    shape = (int(values.shape[0]), int(values.shape[1]))
    resolution = (abs(float(transform[0])), abs(float(transform[4])))
    mask_sha256 = _mask_digest(
        values, crs="EPSG:3577", transform=transform, shape=shape, resolution=resolution,
    )
    return HistoricalWaterMask(
        mask=values,
        crs="EPSG:3577",
        transform=transform,
        shape=shape,
        resolution=resolution,
        pixel_count=int(values.sum()),
        source_product="ga_ls_wo_fq_myear_3",
        source_version="3",
        source_item_ids=("item-a", "item-b"),
        source_lineage=("ga_ls_wo_fq_myear_3", "item-a", "item-b"),
        coverage_start="1986-01-01",
        coverage_end="2026-01-01",
        aoi_sha256="a" * 64,
        mask_sha256=mask_sha256,
    )


def test_record_and_read_cache_analysis_mask_round_trips(tmp_path):
    from hydroseason._io_wofs_zarr import (
        CacheAnalysisMask,
        read_cache_analysis_mask,
        record_cache_analysis_mask,
    )

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()

    recorded = record_cache_analysis_mask(handle, historical_mask)
    assert isinstance(recorded, CacheAnalysisMask)
    assert recorded.pixel_count == 2

    read_back = read_cache_analysis_mask(handle)
    assert read_back is not None
    assert read_back.pixel_count == 2
    assert read_back.mask_sha256 == historical_mask.mask_sha256
    assert np.array_equal(np.asarray(read_back.mask, dtype=bool), historical_mask.mask)

    assert (handle.path / "analysis-mask" / "mask.zarr").exists()
    assert (handle.path / "analysis-mask" / "manifest.json").exists()


def test_analysis_mask_manifest_never_serializes_a_polygon(tmp_path):
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    manifest = json.loads(
        (handle.path / "analysis-mask" / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_text = json.dumps(manifest)
    assert "POLYGON" not in manifest_text.upper()
    assert "wkb" not in manifest_text.lower()


def test_verify_cache_analysis_mask_passes_for_untampered_artifact(tmp_path):
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask, verify_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    verified = verify_cache_analysis_mask(handle)
    assert verified.pixel_count == 2


def test_verify_cache_analysis_mask_detects_tampered_raster_bytes(tmp_path):
    import zarr

    from hydroseason._io_wofs_zarr import (
        _zarr_store,
        record_cache_analysis_mask,
        verify_cache_analysis_mask,
    )

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    zarr_path = handle.path / "analysis-mask" / "mask.zarr"
    array = zarr.open_array(_zarr_store(zarr_path), mode="r+")
    array[0, 0] = False  # flip a True cell to False -- tamper the raster bytes

    with pytest.raises(ValueError, match="verification failed"):
        verify_cache_analysis_mask(handle)


def test_verify_cache_analysis_mask_detects_tampered_digest(tmp_path):
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask, verify_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    manifest_path = handle.path / "analysis-mask" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mask_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="verification failed"):
        verify_cache_analysis_mask(handle)


@pytest.mark.parametrize("field", ["crs", "transform", "shape"])
def test_verify_cache_analysis_mask_detects_tampered_grid_metadata(tmp_path, field):
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask, verify_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    manifest_path = handle.path / "analysis-mask" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if field == "crs":
        manifest["crs"] = "EPSG:4326"
    elif field == "transform":
        manifest["transform"] = [60.0, 0.0, 1000.0, 0.0, -60.0, 2000.0]
    else:
        manifest["shape"] = [3, 2]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="verification failed"):
        verify_cache_analysis_mask(handle)


def test_verify_cache_analysis_mask_detects_tampered_source_lineage(tmp_path):
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask, verify_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    manifest_path = handle.path / "analysis-mask" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_lineage"] = ["tampered_lineage"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="verification failed"):
        verify_cache_analysis_mask(handle)


def test_verify_cache_analysis_mask_detects_tampered_coverage(tmp_path):
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask, verify_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    manifest_path = handle.path / "analysis-mask" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["coverage_end"] = "2099-01-01"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="verification failed"):
        verify_cache_analysis_mask(handle)


def test_verify_cache_analysis_mask_detects_tampered_pixel_count(tmp_path):
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask, verify_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)
    historical_mask = _historical_mask_fixture()
    record_cache_analysis_mask(handle, historical_mask)

    manifest_path = handle.path / "analysis-mask" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pixel_count"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="verification failed"):
        verify_cache_analysis_mask(handle)


def test_read_cache_analysis_mask_returns_none_when_absent(tmp_path):
    from hydroseason._io_wofs_zarr import read_cache_analysis_mask

    request = _historical_mask_request()
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    handle = _handle_for_cube(tmp_path, mask, request=request)

    assert read_cache_analysis_mask(handle) is None


# --- write_annual_group / write_empty_annual_group: count invariants ---


def test_write_annual_group_enforces_n_aoi_equals_historical_mask_pixel_count(tmp_path):
    """When the request carries a historical mask, every month's n_aoi must
    equal the pinned historical_mask_pixel_count -- a store whose actually
    written pixels disagree with the request's own pinned denominator is
    corrupt and must fail loudly rather than silently cache a wrong count."""
    # 2x3 grid, historical_mask_pixel_count pinned to 5, but the written mask
    # has n_aoi == 4 (one more -2 cell than the pinned mask allows for), so
    # the invariant n_aoi == historical_mask_pixel_count must reject this.
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, -2, -2]]
    request = _historical_mask_request(historical_mask_pixel_count=5)
    handle = _handle_for_cube(tmp_path, mask, request=request)

    with pytest.raises(ValueError, match="n_aoi"):
        write_annual_group(
            handle,
            2015,
            mask.chunk({"time": 1, "y": 2, "x": 3}),
            windows=(GridWindow("r0c0", 0, 2, 0, 3),),
            item_ids=("a",),
        )


def test_write_annual_group_passes_invariants_when_n_aoi_matches_historical_mask(tmp_path):
    """The positive case: n_aoi over the actually-written pixels equals the
    pinned historical_mask_pixel_count, so write_annual_group must succeed
    and persist counts as normal."""
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, -2]]  # n_aoi = 4 (all but the two -2 cells)
    request = _historical_mask_request(historical_mask_pixel_count=4)
    handle = _handle_for_cube(tmp_path, mask, request=request)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    extent = open_completed_extent_counts(handle, "2015-01-01", "2015-01-01")
    assert extent is None or extent["n_aoi"].tolist() == [4]


def test_write_annual_group_skips_historical_mask_invariant_for_legacy_requests(tmp_path):
    """A request with no historical mask (the pre-Task-4, still-supported
    shape) must behave exactly as before: no n_aoi == historical_mask_pixel_count
    check is even attempted, since there is no pinned denominator to compare
    against."""
    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    extent = open_completed_extent_counts(handle, "2015-01-01", "2015-02-01")
    assert extent["n_aoi"].tolist() == [5, 5]


def test_write_empty_annual_group_enforces_historical_mask_pixel_count_invariant(tmp_path):
    """An empty year (no STAC items) is entirely -2 (n_aoi=0), so if the
    request pins a nonzero historical_mask_pixel_count the invariant must
    reject it -- a genuinely no-source year covering historically-observed
    water is a contradiction, not a valid empty group."""
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    request = _historical_mask_request(historical_mask_pixel_count=5)
    handle = _handle_for_cube(tmp_path, mask, request=request)

    with pytest.raises(ValueError, match="n_aoi"):
        write_empty_annual_group(handle, 2015, mask)


def test_write_empty_annual_group_passes_when_historical_mask_pixel_count_is_zero(tmp_path):
    """Degenerate but internally consistent: a request pinning
    historical_mask_pixel_count=0 combined with an empty (all -2) year
    satisfies n_aoi == historical_mask_pixel_count trivially."""
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    request = _historical_mask_request(historical_mask_pixel_count=0)
    handle = _handle_for_cube(tmp_path, mask, request=request)

    write_empty_annual_group(handle, 2015, mask)
    assert 2015 in completed_years(handle)


def test_write_annual_group_enforces_n_water_le_n_valid(tmp_path):
    """n_water <= n_valid must hold for every month; this is already
    structurally guaranteed by how n_water/n_valid are derived from the same
    canonical-domain values (n_valid = water + dry, n_water = water), so this
    test documents/pins that invariant explicitly rather than leaving it
    merely implicit in the arithmetic."""
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )
    extent = open_completed_extent_counts(handle, "2015-01-01", "2015-01-01")
    assert (extent["n_water"] <= extent["n_valid"]).all()


def test_write_annual_group_enforces_n_valid_plus_n_invalid_equals_n_aoi(tmp_path):
    """n_valid + n_invalid == n_aoi must hold for every month; again already
    structurally guaranteed (n_invalid = n_aoi - n_valid) -- pin it
    explicitly as a regression guard."""
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )
    extent = open_completed_extent_counts(handle, "2015-01-01", "2015-01-01")
    assert (extent["n_valid"] + extent["n_invalid"] == extent["n_aoi"]).all()


# --- open_completed_extent_counts: scientific-mask pruning acceptance/refusal ---


def test_open_completed_extent_counts_accepts_scientific_pruning_when_verified(tmp_path):
    """A store pruned to the exact historical (scientific) mask -- not merely
    a smaller planning-only footprint -- must be accepted by the fast-count
    reader when the request and a verified CacheAnalysisMask agree."""
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask

    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, -2]]  # n_aoi = 4
    # A mask whose footprint genuinely matches the written cube's n_aoi=4,
    # so record+verify reflects a real, internally consistent scientific
    # mask rather than an arbitrary fixture.
    values = np.array([[True, True, True], [False, True, False]], dtype=bool)
    historical_mask = _historical_mask_fixture_with_values(values)
    assert historical_mask.pixel_count == 4

    # The request's historical_mask_sha256 must genuinely agree with the
    # recorded mask's own digest -- open_completed_extent_counts refuses
    # when they disagree (see
    # test_open_completed_extent_counts_refuses_when_analysis_mask_is_tampered),
    # so this positive test must set it to the mask's real digest, not the
    # arbitrary "f" * 64 placeholder _historical_mask_request defaults to.
    request = _historical_mask_request(
        historical_mask_pixel_count=4, historical_mask_sha256=historical_mask.mask_sha256,
    )
    handle = _handle_for_cube(tmp_path, mask, request=request)

    record_cache_analysis_mask(handle, historical_mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    extent = open_completed_extent_counts(handle, "2015-01-01", "2015-01-01")
    assert extent is not None
    assert extent["n_aoi"].tolist() == [4]


def test_open_completed_extent_counts_refuses_when_no_analysis_mask_recorded(tmp_path):
    """A request that pins a historical_mask_pixel_count but has no verified
    CacheAnalysisMask on disk (e.g. record_cache_analysis_mask was never
    called) cannot be trusted as a scientific denominator -- fail closed."""
    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, -2]]
    request = _historical_mask_request(historical_mask_pixel_count=4)
    handle = _handle_for_cube(tmp_path, mask, request=request)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    assert open_completed_extent_counts(handle, "2015-01-01", "2015-01-01") is None


def test_open_completed_extent_counts_refuses_when_analysis_mask_is_tampered(tmp_path):
    """A recorded CacheAnalysisMask that fails verification (tampered on
    disk) must not be trusted as a scientific denominator either."""
    from hydroseason._io_wofs_zarr import record_cache_analysis_mask

    mask = _canonical_cube(shape=(1, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, -2]]
    request = _historical_mask_request(historical_mask_pixel_count=4)
    handle = _handle_for_cube(tmp_path, mask, request=request)

    values = np.array([[True, True, True], [False, True, False]], dtype=bool)
    historical_mask = _historical_mask_fixture_with_values(values)
    record_cache_analysis_mask(handle, historical_mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )

    manifest_path = handle.path / "analysis-mask" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pixel_count"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert open_completed_extent_counts(handle, "2015-01-01", "2015-01-01") is None


def test_open_completed_extent_counts_still_refuses_planning_only_footprint(tmp_path):
    """Pre-existing behaviour (see
    test_pruned_extent_counts_do_not_infer_full_aoi_denominator_from_footprints
    above) must be unchanged: a store pruned only via wet_mask_sha256/
    footprint_* (planning-only, no historical mask) is still refused,
    because it still lacks a valid scientific denominator regardless of
    Task 4's new acceptance path."""
    import geopandas as gpd
    from shapely.geometry import box

    from hydroseason._io_wofs_zarr import record_cache_footprints

    mask = _canonical_cube(shape=(2, 2, 4), fill=-2)
    mask.values[:, :, :] = [
        [[1, 0, -2, -2], [1, 0, -2, -2]],
        [[1, 0, -2, -2], [1, 0, -2, -2]],
    ]
    handle = _handle_for_cube(
        tmp_path,
        mask,
        request=dataclasses.replace(_request(), wet_mask_sha256="b" * 64),
    )
    full_aoi = gpd.GeoDataFrame(
        {"geometry": [box(999.0, 1941.0, 1119.0, 1999.0)]}, crs="EPSG:3577"
    )
    analysis_footprint = gpd.GeoDataFrame(
        {"geometry": [box(999.0, 1941.0, 1059.0, 1999.0)]}, crs="EPSG:3577"
    )
    record_cache_footprints(
        handle,
        full_aoi_gdf=full_aoi,
        analysis_footprint_gdf=analysis_footprint,
        shape=(2, 4),
        transform=(30.0, 0.0, 1000.0, 0.0, -30.0, 2000.0),
        crs="EPSG:3577",
    )

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 4}),
        windows=(GridWindow("r0c0", 0, 2, 0, 4),),
        item_ids=("a",),
    )

    assert open_completed_extent_counts(handle, "2015-01-01", "2015-01-01") is None


