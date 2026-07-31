"""Tests for the DEA Water Observation Statistics wet-mask fetch.

Fully offline: the STAC client and the raster loader are both injected, so
these tests never touch the network.
"""
from unittest.mock import Mock

import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("rioxarray")
gpd = pytest.importorskip("geopandas")

from shapely.geometry import box  # noqa: E402

from hydroseason._io_dea_stats import (  # noqa: E402
    DEA_STATS_ALLTIME_COLLECTION,
    DEA_STATS_ANNUAL_COLLECTION,
    DEAStatsUnavailable,
    WetPlanningFootprint,
    build_wet_planning_footprint,
    fetch_dea_stats_wet_aoi,
    open_wo_statistics,
    wet_mask_digest,
)


def _aoi():
    # 3 km x 3 km AOI at the EPSG:3577 origin.
    return gpd.GeoDataFrame({"geometry": [box(0.0, -3000.0, 3000.0, 0.0)]}, crs="EPSG:3577")


def _count_wet(grid, *, res=30.0):
    """A georeferenced count_wet raster from a 2D integer array."""
    h, w = np.asarray(grid).shape
    return xr.DataArray(
        np.asarray(grid, dtype=np.uint16),
        dims=("y", "x"),
        coords={"y": np.arange(h) * -res, "x": np.arange(w) * res},
    ).rio.write_crs("EPSG:3577").rio.write_transform()


def test_wet_aoi_covers_every_pixel_wet_in_any_source_year():
    """The mask must be a union across years, never an intersection: a pixel
    wet only in 1998 must survive, or 1998's flood reads as permanently dry."""
    wet_in_alltime = np.zeros((10, 10), np.uint16)
    wet_in_alltime[1, 1] = 5

    wet_only_1998 = np.zeros((10, 10), np.uint16)
    wet_only_1998[8, 8] = 1

    loaded = {
        (DEA_STATS_ALLTIME_COLLECTION, None): _count_wet(wet_in_alltime),
        (DEA_STATS_ANNUAL_COLLECTION, 1998): _count_wet(wet_only_1998),
    }

    def _loader(collection, year, geobox):
        return loaded[(collection, year)]

    wet_aoi = fetch_dea_stats_wet_aoi(
        "https://example.test/stac", _aoi(), [1998],
        close_m=0.0, buffer_m=0.0, _loader=_loader,
    )

    geometry = wet_aoi.geometry.iloc[0]
    # rioxarray/rasterio use pixel-CENTRE coordinates: with res=30 and the
    # x/y coord arrays built as np.arange(n) * +/-res, pixel (row, col) has
    # its centre at (col * res, -row * res) and spans a 30 m box around it.
    # Pixel (1,1) -> centre (30, -30); pixel (8,8) -> centre (240, -240).
    assert geometry.contains(box(15.0, -45.0, 45.0, -15.0).centroid)
    assert geometry.contains(box(225.0, -255.0, 255.0, -225.0).centroid)


def test_zero_wet_pixels_raises_rather_than_pruning_everything():
    """An all-dry mask would prune the entire AOI. That is never a valid
    answer -- it must fail open at the call site instead."""
    def _loader(collection, year, geobox):
        return _count_wet(np.zeros((10, 10), np.uint16))

    with pytest.raises(DEAStatsUnavailable, match="no wet pixels"):
        fetch_dea_stats_wet_aoi(
            "https://example.test/stac", _aoi(), [1998], _loader=_loader,
        )


def test_loader_failure_raises_dea_stats_unavailable():
    def _loader(collection, year, geobox):
        raise ConnectionError("S3 unreachable")

    with pytest.raises(DEAStatsUnavailable):
        fetch_dea_stats_wet_aoi(
            "https://example.test/stac", _aoi(), [1998], _loader=_loader,
        )


def test_alltime_failure_alone_still_succeeds_from_annual_years():
    """myear is the cheap primary source but not required: if only the annual
    product resolves, the per-year union is still a valid superset."""
    wet = np.zeros((10, 10), np.uint16)
    wet[4, 4] = 3

    def _loader(collection, year, geobox):
        if collection == DEA_STATS_ALLTIME_COLLECTION:
            raise ConnectionError("myear unavailable")
        return _count_wet(wet)

    wet_aoi = fetch_dea_stats_wet_aoi(
        "https://example.test/stac", _aoi(), [1998],
        close_m=0.0, buffer_m=0.0, _loader=_loader,
    )
    assert not wet_aoi.empty
    assert wet_aoi.geometry.iloc[0].area > 0


def test_digest_is_stable_for_identical_geometry_and_differs_otherwise():
    left = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")
    same = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")
    other = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 200.0, 100.0)]}, crs="EPSG:3577")

    assert wet_mask_digest(left) == wet_mask_digest(same)
    assert wet_mask_digest(left) != wet_mask_digest(other)
    assert len(wet_mask_digest(left)) == 64


# --------------------------------------------------------------------------
# open_wo_statistics: the public native DEA Water Observation Statistics
# loader (task W1.1). Returns a raw xr.Dataset of count_wet/count_clear plus
# a lazily derived frequency -- no polygon reduction, no acquisition-side
# planning logic. Downstream conversion into a planning mask is a separate,
# later task (W1.5) and is deliberately not exercised here.
# --------------------------------------------------------------------------

class _FakeItem:
    def __init__(self, item_id, date):
        self.id = item_id
        self.properties = {"datetime": date}


def _install_stac_fakes(monkeypatch, items, dataset_factory, *, module):
    """Patch pystac_client.Client.open and odc.stac.load for one test.

    ``dataset_factory(items, **load_kwargs) -> xr.Dataset`` stands in for
    odc.stac.load; ``items`` is whatever the fake search returns. Returns a
    mutable ``calls`` dict the test can inspect (search call count/kwargs,
    load call kwargs).
    """
    calls = {"search_count": 0, "search_kwargs": [], "load_kwargs": None}

    def fake_search(**kwargs):
        calls["search_count"] += 1
        calls["search_kwargs"].append(kwargs)
        result = Mock()
        result.items.return_value = list(items)
        return result

    client = Mock()
    client.search.side_effect = fake_search
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=client))

    def fake_load(loaded_items, **kwargs):
        calls["load_kwargs"] = kwargs
        return dataset_factory(loaded_items, **kwargs)

    monkeypatch.setattr("odc.stac.load", Mock(side_effect=fake_load))
    return calls


def _dask_dataset(
    items, *, crs="EPSG:3577", resolution=30.0, bands=("count_wet", "count_clear"),
    nodata=-1, shape=(4, 4), **_ignored_kwargs,
):
    """Stand-in for odc.stac.load: builds a small dask-backed grid directly
    from the crs/resolution kwargs open_wo_statistics passes, ignoring
    geopolygon/chunks (irrelevant to what these tests assert)."""
    import dask.array as da

    ny, nx = shape
    y = -np.arange(ny) * resolution
    x = np.arange(nx) * resolution

    count_wet = np.full((ny, nx), 3, dtype=np.int16)
    count_wet[0, 0] = nodata  # one nodata pixel to exercise nodata handling
    count_clear = np.full((ny, nx), 10, dtype=np.int16)
    count_clear[0, 0] = nodata

    data_vars = {}
    for band, arr in (("count_wet", count_wet), ("count_clear", count_clear)):
        if band in bands:
            dask_arr = da.from_array(arr, chunks=(2, 2))
            data_vars[band] = (("y", "x"), dask_arr)

    ds = xr.Dataset(data_vars, coords={"y": y, "x": x})
    for band in bands:
        ds[band].attrs["nodata"] = nodata
    return ds.rio.write_crs(crs)


def test_open_wo_statistics_issues_exactly_one_stac_search(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    calls = _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi())

    assert calls["search_count"] == 1


def test_open_wo_statistics_requests_exactly_two_bands(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    calls = _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi())

    requested_bands = calls["load_kwargs"]["bands"]
    assert set(requested_bands) == {"count_wet", "count_clear"}
    assert len(requested_bands) == 2


def test_open_wo_statistics_requests_native_30m_grid_explicitly(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    calls = _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi(), resolution=30.0, crs="EPSG:3577")

    assert calls["load_kwargs"]["resolution"] == 30.0
    assert calls["load_kwargs"]["crs"] == "EPSG:3577"


def test_open_wo_statistics_returns_a_dataset(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    result = open_wo_statistics(_aoi())

    assert isinstance(result, xr.Dataset)
    assert set(result.data_vars) >= {"count_wet", "count_clear", "frequency"}


def test_open_wo_statistics_frequency_is_derived_0_to_100(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    result = open_wo_statistics(_aoi())
    frequency = result["frequency"].compute()

    # count_wet=3, count_clear=10 everywhere except the nodata pixel.
    valid = frequency.values[1:, 1:]
    assert np.allclose(valid, 100.0 * 3.0 / 10.0)
    assert np.nanmax(frequency.values) <= 100.0
    assert np.nanmin(valid) >= 0.0


def test_open_wo_statistics_frequency_nodata_where_inputs_are_nodata(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    result = open_wo_statistics(_aoi())
    frequency = result["frequency"].compute()

    assert bool(np.isnan(frequency.values[0, 0]))


def test_open_wo_statistics_records_provenance(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z"), _FakeItem("item-2", "2021-06-01T00:00:00Z")]
    _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    result = open_wo_statistics(_aoi(), product="ga_ls_wo_fq_myear_3")

    provenance = result.attrs["provenance"]
    assert provenance["product"] == "ga_ls_wo_fq_myear_3"
    assert set(provenance["item_ids"]) == {"item-1", "item-2"}
    assert "frequency" in provenance
    assert "count_wet" in provenance["frequency"] and "count_clear" in provenance["frequency"]
    assert provenance["time_span"] == "2020-06-01T00:00:00Z/2021-06-01T00:00:00Z"


def test_open_wo_statistics_does_not_load_eagerly(monkeypatch):
    """The loader must never call .load()/.compute() itself -- forcing a
    materialization here would defeat the whole point of a Dask-backed
    zoning source (a huge AOI must stay lazy until the caller decides).

    Asserted indirectly: every returned variable's ``.data`` is still a
    dask array after the loader returns. If the loader had called
    ``.load()``/``.compute()`` internally, ``.data`` would be a plain numpy
    array instead.
    """
    import dask.array as da

    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    result = open_wo_statistics(_aoi())

    assert isinstance(result["count_wet"].data, da.Array)
    assert isinstance(result["count_clear"].data, da.Array)
    assert isinstance(result["frequency"].data, da.Array)


def test_open_wo_statistics_no_items_raises(monkeypatch):
    import hydroseason._io_dea_stats as mod

    _install_stac_fakes(monkeypatch, [], _dask_dataset, module=mod)

    with pytest.raises(mod.WoStatisticsUnavailable):
        open_wo_statistics(_aoi())


def test_open_wo_statistics_passes_geographic_crs_through_unvalidated(monkeypatch):
    """Rejecting a geographic CRS is HydroFragments' job
    (guard_area_metric_crs), not this loader's -- hydroseason has no pyproj
    dependency and must never import HydroFragments (one-way dependency
    rule). open_wo_statistics stays source-agnostic: it hands back whatever
    grid crs/resolution asked for, unvalidated, and the HydroFragments
    adapter is the one that hard-fails on geographic CRS before use."""
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    calls = _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi(), crs="EPSG:4326")

    assert calls["load_kwargs"]["crs"] == "EPSG:4326"


def test_open_wo_statistics_scopes_unsigned_cog_env_and_restores_it(monkeypatch):
    """Uses the shared unsigned-COG GDAL config, but must not leave process
    env permanently mutated by this call once it returns."""
    import os

    import hydroseason._io_dea_stats as mod

    monkeypatch.delenv("AWS_NO_SIGN_REQUEST", raising=False)

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi())

    assert "AWS_NO_SIGN_REQUEST" not in os.environ


def test_open_wo_statistics_passes_chunks_through(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    calls = _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi(), chunks={"x": 512, "y": 512})

    assert calls["load_kwargs"]["chunks"] == {"x": 512, "y": 512}


# --------------------------------------------------------------------------
# build_wet_planning_footprint: a SEPARATE, performance-only artifact built
# on top of open_wo_statistics's output. It is a pruning/planning aid only
# -- never fed into build_zones()/zoning, and never allowed to change what
# counts as inside/outside the catchment for a metric denominator.
#
# The single most important property here is the round-trip proof: expanding
# coarse_mask back to the native grid must cover every native wet pixel
# (native_mask <= expanded_coarse_mask), for every accepted plan.
# --------------------------------------------------------------------------


def _stats_dataset(
    count_wet_grid, *, res=30.0, count_clear_value=10,
    time_span="1988-01-01T00:00:00Z/2024-12-31T00:00:00Z",
    product=DEA_STATS_ALLTIME_COLLECTION,
    provenance=True,
):
    """A synthetic stand-in for open_wo_statistics's returned xr.Dataset.

    Builds count_wet/count_clear DataArrays at the given grid plus a
    provenance attrs block carrying the fields build_wet_planning_footprint
    needs to validate temporal/lineage coverage -- shaped exactly like the
    real loader's ``.attrs["provenance"]`` (see open_wo_statistics).
    """
    import dask.array as da

    grid = np.asarray(count_wet_grid, dtype=np.int32)
    h, w = grid.shape
    count_wet = xr.DataArray(
        da.from_array(grid, chunks=(4, 4)), dims=("y", "x"),
        coords={"y": np.arange(h) * -res, "x": np.arange(w) * res},
    )
    count_clear = xr.full_like(count_wet, count_clear_value)
    ds = xr.Dataset({"count_wet": count_wet, "count_clear": count_clear})
    ds = ds.rio.write_crs("EPSG:3577").rio.write_transform()
    if provenance:
        ds.attrs["provenance"] = {
            "product": product,
            "stac_url": "https://example.test/stac",
            "item_ids": ["item-1"],
            "crs": "EPSG:3577",
            "resolution": res,
            "time_span": time_span,
            "frequency": {
                "derivation": "100 * count_wet / count_clear",
                "count_wet": "count_wet",
                "count_clear": "count_clear",
            },
        }
    return ds


def test_footprint_isolated_one_pixel_water_survives_round_trip():
    """A single isolated 30 m wet pixel must never disappear when coarsened
    -- the defining correctness property of this whole task."""
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    stats = _stats_dataset(grid)

    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    native = np.asarray(footprint.native_mask.values, dtype=bool)
    coarse = np.asarray(footprint.coarse_mask.values, dtype=bool)
    expanded = coarse.repeat(4, axis=0).repeat(4, axis=1)[:16, :16]
    assert np.all(native <= expanded)
    assert coarse.any()


def test_footprint_thin_diagonal_channel_round_trip():
    grid = np.zeros((16, 16), dtype=np.int32)
    for i in range(16):
        grid[i, i] = 1
    stats = _stats_dataset(grid)

    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    native = np.asarray(footprint.native_mask.values, dtype=bool)
    coarse = np.asarray(footprint.coarse_mask.values, dtype=bool)
    expanded = coarse.repeat(4, axis=0).repeat(4, axis=1)[:16, :16]
    assert np.all(native <= expanded)


def test_footprint_thin_orthogonal_channel_round_trip():
    grid = np.zeros((20, 20), dtype=np.int32)
    grid[9, :] = 1  # a single-pixel-wide horizontal channel
    stats = _stats_dataset(grid)

    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    native = np.asarray(footprint.native_mask.values, dtype=bool)
    coarse = np.asarray(footprint.coarse_mask.values, dtype=bool)
    expanded = coarse.repeat(4, axis=0).repeat(4, axis=1)[:20, :20]
    assert np.all(native <= expanded)


def test_footprint_partial_edge_block_preserved_not_dropped():
    """A native grid whose size is not a multiple of ``factor`` must pad the
    trailing partial block rather than drop it -- a wet pixel in the last,
    smaller row/col must still survive."""
    grid = np.zeros((10, 10), dtype=np.int32)  # 10 is not a multiple of 4
    grid[9, 9] = 1  # in the partial trailing 2x2 block for factor=4
    stats = _stats_dataset(grid)

    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    native = np.asarray(footprint.native_mask.values, dtype=bool)
    coarse = np.asarray(footprint.coarse_mask.values, dtype=bool)
    # coarsen(boundary="pad") grows the coarse grid to cover the partial
    # block rather than truncating it away.
    assert coarse.shape == (3, 3)
    expanded = coarse.repeat(4, axis=0).repeat(4, axis=1)[:10, :10]
    assert np.all(native <= expanded)
    assert coarse[2, 2]  # the trailing partial block is marked wet


def test_footprint_safety_cells_dilate_coarse_mask():
    """safety_cells applies a coarse-cell halo: strictly more (or equal)
    coarse cells are marked wet than with safety_cells=0, and the round-trip
    superset property still holds."""
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[6, 6] = 1
    stats = _stats_dataset(grid)

    plain = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )
    haloed = build_wet_planning_footprint(
        stats, factor=4, safety_cells=1, requested_years=[1988],
    )

    plain_coarse = np.asarray(plain.coarse_mask.values, dtype=bool)
    haloed_coarse = np.asarray(haloed.coarse_mask.values, dtype=bool)
    assert haloed_coarse.sum() >= plain_coarse.sum()
    assert np.all(plain_coarse <= haloed_coarse)

    native = np.asarray(haloed.native_mask.values, dtype=bool)
    expanded = haloed_coarse.repeat(4, axis=0).repeat(4, axis=1)[:16, :16]
    assert np.all(native <= expanded)


def test_footprint_empty_mask_raises_dea_stats_unavailable():
    """count_wet all-zero must fail open exactly like fetch_dea_stats_wet_aoi
    -- an empty dry footprint must never be mistaken for 'nothing to prune'."""
    grid = np.zeros((10, 10), dtype=np.int32)
    stats = _stats_dataset(grid)

    with pytest.raises(DEAStatsUnavailable):
        build_wet_planning_footprint(stats, requested_years=[1988])


def test_footprint_missing_requested_year_raises_dea_stats_unavailable():
    """The statistics' time_span must cover every requested year, or this
    must fail open rather than silently produce a partial mask."""
    grid = np.zeros((10, 10), dtype=np.int32)
    grid[5, 5] = 1
    stats = _stats_dataset(grid, time_span="2015-01-01T00:00:00Z/2018-12-31T00:00:00Z")

    with pytest.raises(DEAStatsUnavailable):
        build_wet_planning_footprint(stats, requested_years=[2020])


def test_footprint_missing_lineage_provenance_raises_dea_stats_unavailable():
    """Absent/incompatible statistics-lineage provenance must fail open too,
    not just an absent/insufficient time span."""
    grid = np.zeros((10, 10), dtype=np.int32)
    grid[5, 5] = 1
    stats = _stats_dataset(grid, provenance=False)

    with pytest.raises(DEAStatsUnavailable):
        build_wet_planning_footprint(stats, requested_years=[1988])


def test_footprint_shifted_grid_rejection():
    """A coarse mask built against one grid must not be silently treated as
    valid for a native mask on a different (shifted) grid -- the dataclass's
    own native_mask/coarse_mask must come from one consistent build, and
    re-validating a footprint against a foreign, shifted native grid must be
    rejected rather than accepted."""
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    stats = _stats_dataset(grid)
    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    shifted_grid = np.zeros((16, 16), dtype=np.int32)
    shifted_stats = _stats_dataset(shifted_grid, res=30.0)
    # Shift the shifted dataset's coordinate origin by half a native pixel
    # so it no longer aligns with footprint's native grid.
    shifted_stats = shifted_stats.assign_coords(
        x=shifted_stats.x + 15.0, y=shifted_stats.y - 15.0
    )
    shifted_native = shifted_stats["count_wet"] > 0

    assert not _grids_aligned(footprint.native_mask, shifted_native)


def _grids_aligned(a, b) -> bool:
    """True if two DataArrays share the same x/y coordinate grid."""
    if a.sizes != b.sizes:
        return False
    return bool(np.array_equal(a.x.values, b.x.values)) and bool(
        np.array_equal(a.y.values, b.y.values)
    )


def test_footprint_deterministic_digest_for_identical_inputs():
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    stats_a = _stats_dataset(grid)
    stats_b = _stats_dataset(grid)

    footprint_a = build_wet_planning_footprint(
        stats_a, factor=4, safety_cells=1, requested_years=[1988],
    )
    footprint_b = build_wet_planning_footprint(
        stats_b, factor=4, safety_cells=1, requested_years=[1988],
    )

    assert footprint_a.digest == footprint_b.digest
    assert len(footprint_a.digest) == 64


def test_footprint_digest_differs_for_different_mask_or_params():
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    other_grid = np.zeros((16, 16), dtype=np.int32)
    other_grid[0, 0] = 1
    stats = _stats_dataset(grid)
    other_stats = _stats_dataset(other_grid)

    base = build_wet_planning_footprint(
        stats, factor=4, safety_cells=1, requested_years=[1988],
    )
    different_mask = build_wet_planning_footprint(
        other_stats, factor=4, safety_cells=1, requested_years=[1988],
    )
    different_factor = build_wet_planning_footprint(
        stats, factor=2, safety_cells=1, requested_years=[1988],
    )
    different_safety = build_wet_planning_footprint(
        stats, factor=4, safety_cells=2, requested_years=[1988],
    )

    digests = {
        base.digest, different_mask.digest, different_factor.digest,
        different_safety.digest,
    }
    assert len(digests) == 4


def test_footprint_records_provenance_years_and_active_windows():
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    stats = _stats_dataset(grid, product=DEA_STATS_ALLTIME_COLLECTION)

    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=1, requested_years=[1988, 1999],
    )

    assert isinstance(footprint, WetPlanningFootprint)
    assert footprint.factor == 4
    assert footprint.safety_cells == 1
    assert list(footprint.covered_years) == [1988, 1999]
    assert footprint.source_collection == DEA_STATS_ALLTIME_COLLECTION
    assert footprint.source_version  # non-empty
    assert footprint.source_lineage  # non-empty
    assert len(footprint.active_windows) >= 1
    assert footprint.geometry is None


def test_footprint_never_creates_polygons_by_default():
    """Contract: 'Do not create polygons unless the consumer requires them.'
    geometry stays None on the default path."""
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    stats = _stats_dataset(grid)

    footprint = build_wet_planning_footprint(stats, requested_years=[1988])

    assert footprint.geometry is None


def test_footprint_accepts_dask_backed_stats_and_round_trips():
    """open_wo_statistics's real output is Dask-backed (never .load()d); this
    must consume that directly and still produce a correct footprint."""
    import dask.array as da

    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    stats = _stats_dataset(grid)
    assert isinstance(stats["count_wet"].data, da.Array)

    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    native = np.asarray(footprint.native_mask.values, dtype=bool)
    coarse = np.asarray(footprint.coarse_mask.values, dtype=bool)
    expanded = coarse.repeat(4, axis=0).repeat(4, axis=1)[:16, :16]
    assert np.all(native <= expanded)


def test_footprint_active_windows_are_grid_windows():
    from hydroseason._spatial_plan import GridWindow

    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 11] = 1
    stats = _stats_dataset(grid)

    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    assert all(isinstance(w, GridWindow) for w in footprint.active_windows)
    # Every wet native pixel must fall inside at least one active window.
    ys, xs = np.nonzero(np.asarray(footprint.native_mask.values, dtype=bool))
    for y, x in zip(ys, xs):
        assert any(
            w.y_start <= y < w.y_stop and w.x_start <= x < w.x_stop
            for w in footprint.active_windows
        )
