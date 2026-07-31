"""Tests for task W2.3: persisting/verifying full-AOI vs analysis-footprint
cache metadata (:mod:`hydroseason._io_wofs_zarr`'s ``record_cache_footprints``/
``read_cache_footprints``/``verify_cache_footprints``).

Two properties are load-bearing for this task (see the plan's global
constraints and the W2.3 brief):

1. A pruned (wet-footprint-restricted) cache and an unpruned (full-AOI) cache
   covering the SAME catchment must report the SAME ``aoi_pixel_count`` --
   the fixed reference-area denominator never shrinks due to pruning -- while
   ``analysis_pixel_count`` (the conservative potential-water footprint) MAY
   differ, because it legitimately reflects whatever was actually pruned to.
2. Persisted geometry/digests must be tamper-evident: corrupting the stored
   WKB or mismatching a digest must be detected and rejected, never silently
   accepted.
"""
from __future__ import annotations

import pytest

gpd = pytest.importorskip("geopandas")
pytest.importorskip("rioxarray")
pytest.importorskip("shapely")

from shapely.geometry import box

from hydroseason._io_wofs_zarr import (
    WOfSCacheIdentity,
    WOfSCacheRequest,
    _read_json,
    _write_json_atomic,
    create_cache_handle,
    read_cache_footprints,
    record_cache_footprints,
    verify_cache_footprints,
)


def _request(**overrides) -> WOfSCacheRequest:
    payload = dict(
        stac_url="https://example.invalid/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="2015-01-01",
        end_date="2015-12-31",
        crs="EPSG:3577",
        resolution=30.0,
        classifier_version=1,
        groupby="solar_day",
        majority=True,
        planner_version=1,
        schema_version=3,
    )
    payload.update(overrides)
    return WOfSCacheRequest(**payload)


# A 300 m x 300 m AOI (10x10 pixels @ 30 m) at the EPSG:3577 origin.
_GRID_SHAPE = (10, 10)
_GRID_TRANSFORM = (30.0, 0.0, 0.0, 0.0, -30.0, 0.0)


def _full_aoi_gdf():
    return gpd.GeoDataFrame({"geometry": [box(0.0, -300.0, 300.0, 0.0)]}, crs="EPSG:3577")


def _analysis_footprint_gdf_full():
    """An unpruned run's analysis footprint: identical to the full AOI."""
    return _full_aoi_gdf()


def _analysis_footprint_gdf_pruned():
    """A pruned run's analysis footprint: a strict, smaller subset of the AOI.

    Half of the full 300x300 m AOI (10x10 px @ 30 m) -> 300x150 m -> 10x5 px
    = 50 pixels, vs. the full AOI's 100 pixels.
    """
    return gpd.GeoDataFrame({"geometry": [box(0.0, -150.0, 300.0, 0.0)]}, crs="EPSG:3577")


def _make_handle(tmp_path, *, wet_mask_sha256=None):
    identity = WOfSCacheIdentity.from_request(
        _request(wet_mask_sha256=wet_mask_sha256), shape=_GRID_SHAPE, transform=_GRID_TRANSFORM
    )
    return create_cache_handle(tmp_path, identity)


# ---------------------------------------------------------------------------
# Step 1: identical aoi_pixel_count, differing analysis_pixel_count.
# ---------------------------------------------------------------------------


def test_pruned_and_unpruned_caches_retain_identical_aoi_pixel_count(tmp_path):
    unpruned_handle = _make_handle(tmp_path / "unpruned")
    pruned_handle = _make_handle(tmp_path / "pruned", wet_mask_sha256="deadbeef")

    unpruned_footprints = record_cache_footprints(
        unpruned_handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_full(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )
    pruned_footprints = record_cache_footprints(
        pruned_handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )

    assert unpruned_footprints.aoi_pixel_count == pruned_footprints.aoi_pixel_count
    assert unpruned_footprints.aoi_pixel_count == 100  # 10x10 grid, fully inside AOI


def test_analysis_pixel_count_differs_when_pruning_applied(tmp_path):
    unpruned_handle = _make_handle(tmp_path / "unpruned")
    pruned_handle = _make_handle(tmp_path / "pruned", wet_mask_sha256="deadbeef")

    unpruned_footprints = record_cache_footprints(
        unpruned_handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_full(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )
    pruned_footprints = record_cache_footprints(
        pruned_handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )

    assert unpruned_footprints.analysis_pixel_count == 100
    assert pruned_footprints.analysis_pixel_count == 50
    assert pruned_footprints.analysis_pixel_count != unpruned_footprints.analysis_pixel_count
    # aoi_pixel_count is unaffected by pruning.
    assert pruned_footprints.aoi_pixel_count == unpruned_footprints.aoi_pixel_count


def test_read_cache_footprints_round_trips_persisted_metadata(tmp_path):
    handle = _make_handle(tmp_path)
    written = record_cache_footprints(
        handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )
    read_back = read_cache_footprints(handle)

    assert read_back.aoi_pixel_count == written.aoi_pixel_count
    assert read_back.analysis_pixel_count == written.analysis_pixel_count
    assert read_back.aoi_geometry_wkb_hex == written.aoi_geometry_wkb_hex
    assert read_back.analysis_geometry_wkb_hex == written.analysis_geometry_wkb_hex
    assert read_back.aoi_digest == written.aoi_digest
    assert read_back.analysis_digest == written.analysis_digest
    assert read_back.crs == written.crs
    assert tuple(read_back.transform) == tuple(written.transform)
    assert tuple(read_back.shape) == tuple(written.shape)


# ---------------------------------------------------------------------------
# Step 2: tampered geometry/digest rejection.
# ---------------------------------------------------------------------------


def test_verify_cache_footprints_accepts_untampered_metadata(tmp_path):
    handle = _make_handle(tmp_path)
    record_cache_footprints(
        handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )

    verified = verify_cache_footprints(handle)
    assert verified.aoi_pixel_count == 100
    assert verified.analysis_pixel_count == 50


def test_verify_cache_footprints_rejects_tampered_geometry(tmp_path):
    handle = _make_handle(tmp_path)
    record_cache_footprints(
        handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )

    manifest_path = handle.path / "manifest.json"
    manifest = _read_json(manifest_path)
    # Corrupt the persisted AOI WKB directly -- simulating a hand-edited or
    # bit-rotted manifest -- without touching its digest.
    tampered_wkb_hex = manifest["footprints"]["aoi_geometry_wkb_hex"]
    manifest["footprints"]["aoi_geometry_wkb_hex"] = tampered_wkb_hex[:-4] + "ffff"
    _write_json_atomic(manifest_path, manifest)

    with pytest.raises(ValueError, match="(?i)digest|tamper|mismatch"):
        verify_cache_footprints(handle)


def test_verify_cache_footprints_rejects_mismatched_digest(tmp_path):
    handle = _make_handle(tmp_path)
    record_cache_footprints(
        handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )

    manifest_path = handle.path / "manifest.json"
    manifest = _read_json(manifest_path)
    # Mismatch the analysis digest against its (untouched) geometry.
    manifest["footprints"]["analysis_digest"] = "0" * 64
    _write_json_atomic(manifest_path, manifest)

    with pytest.raises(ValueError, match="(?i)digest|tamper|mismatch"):
        verify_cache_footprints(handle)


def test_verify_cache_footprints_rejects_tampered_pixel_count(tmp_path):
    """A pixel count that no longer matches the persisted geometry, even
    though the geometry's own digest still checks out, must also be
    rejected -- re-rasterizing the geometry is the independent proof, not
    merely trusting whatever count was written alongside it."""
    handle = _make_handle(tmp_path)
    record_cache_footprints(
        handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )

    manifest_path = handle.path / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["footprints"]["analysis_pixel_count"] = 9999
    _write_json_atomic(manifest_path, manifest)

    with pytest.raises(ValueError, match="(?i)pixel|mismatch|count"):
        verify_cache_footprints(handle)


def test_verify_cache_footprints_raises_when_metadata_absent(tmp_path):
    handle = _make_handle(tmp_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_cache_footprints(handle)


def test_record_cache_footprints_is_atomic_write(tmp_path, monkeypatch):
    """A crash mid-write must never leave a torn manifest.json -- this test
    doesn't simulate a literal crash, but asserts record_cache_footprints
    routes through the same _write_json_atomic temp-then-replace helper
    every other piece of root metadata in this module uses."""
    import hydroseason._io_wofs_zarr as mod

    calls = []
    original = mod._write_json_atomic

    def _spy(path, payload):
        calls.append(path)
        return original(path, payload)

    monkeypatch.setattr(mod, "_write_json_atomic", _spy)

    handle = _make_handle(tmp_path)
    record_cache_footprints(
        handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )
    assert any(path.name == "manifest.json" for path in calls)


def test_record_cache_footprints_preserves_existing_manifest_keys(tmp_path):
    """Read-modify-write must never clobber identity/request_digest, matching
    _record_completed_year's contract."""
    handle = _make_handle(tmp_path)
    manifest_before = _read_json(handle.path / "manifest.json")

    record_cache_footprints(
        handle,
        full_aoi_gdf=_full_aoi_gdf(),
        analysis_footprint_gdf=_analysis_footprint_gdf_pruned(),
        shape=_GRID_SHAPE,
        transform=_GRID_TRANSFORM,
        crs="EPSG:3577",
    )

    manifest_after = _read_json(handle.path / "manifest.json")
    assert manifest_after["request_digest"] == manifest_before["request_digest"]
    assert manifest_after["identity"] == manifest_before["identity"]
    assert "footprints" in manifest_after
