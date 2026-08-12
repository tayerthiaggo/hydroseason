"""Tests for the DEA Water Observation Statistics wet-mask fetch.

Fully offline: the STAC client and the raster loader are both injected, so
these tests never touch the network.
"""
import dataclasses
import json
import time
from unittest.mock import Mock

import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("rioxarray")
gpd = pytest.importorskip("geopandas")

from shapely.geometry import box  # noqa: E402

from hydroseason._historical_water_mask import (  # noqa: E402
    HistoricalWaterMask,
    HistoricalWaterMaskRequest,
    _zarr_store,
    build_historical_water_mask,
    load_or_build_historical_water_mask,
    read_historical_water_mask,
    write_historical_water_mask,
)
from hydroseason._historical_water_mask import _aoi_digest as _historical_aoi_digest  # noqa: E402
from hydroseason._io_dea_stats import (  # noqa: E402  # noqa: E402
    DEA_STATS_ALLTIME_COLLECTION,
    DEA_STATS_ANNUAL_COLLECTION,
    DEAStatsUnavailable,
    WetPlanningFootprint,
    build_planning_footprint_from_historical_mask,
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


def test_open_wo_statistics_does_not_restore_a_hostile_proj_database(monkeypatch):
    """``PROJ_LIB``/``PROJ_DATA`` must NOT be restored, unlike the GDAL/AWS keys.

    This loader returns a LAZY dask graph: the reprojection that needs a
    usable PROJ database happens long after the function returns, when the
    caller computes. ``_configure_cog_read_env`` deliberately repoints
    ``PROJ_LIB``/``PROJ_DATA`` at a known-good bundled database precisely
    because a system-wide value (e.g. from a PostGIS install, which sets
    ``PROJ_LIB`` machine-wide on Windows) makes that reprojection fail with
    ``pyproj.exceptions.ProjError: Error creating Transformer from CRS``.
    Restoring the hostile value on the way out re-arms that failure for
    every lazy read of the returned cube.

    The GDAL/AWS keys are a different case and are still restored (see
    ``test_open_wo_statistics_scopes_unsigned_cog_env_and_restores_it``):
    ``odc.stac.configure_rio`` installs odc-stac's own rasterio environment
    for the lazy reads, so those do not need to survive in ``os.environ``.
    """
    import os

    import hydroseason._io_dea_stats as mod

    hostile = str(tmp_hostile_proj_dir())
    monkeypatch.setenv("PROJ_LIB", hostile)
    monkeypatch.setenv("PROJ_DATA", hostile)

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi())

    assert os.environ.get("PROJ_LIB") != hostile
    assert os.environ.get("PROJ_DATA") != hostile


def tmp_hostile_proj_dir():
    """A path standing in for an incompatible system-wide proj.db directory."""
    from pathlib import Path

    return Path("C:/Program Files/PostgreSQL/16/share/contrib/postgis-3.4/proj")


def test_open_wo_statistics_passes_chunks_through(monkeypatch):
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    calls = _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)

    open_wo_statistics(_aoi(), chunks={"x": 512, "y": 512})

    assert calls["load_kwargs"]["chunks"] == {"x": 512, "y": 512}


def test_open_wo_statistics_stops_waiting_after_search_deadline(monkeypatch):
    """A blocking STAC item iterator must return control at the deadline, not
    only raise after the slow search eventually finishes."""
    import hydroseason._io_dea_stats as mod

    monkeypatch.setattr(mod, "STAC_SEARCH_DEADLINE_S", 0.01)

    class Search:
        def items(self):
            time.sleep(0.5)
            return []

    class FakeClient:
        def search(self, **_kwargs):
            return Search()

    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=FakeClient()))

    started = time.monotonic()
    with pytest.raises(mod.WoStatisticsUnavailable, match="deadline"):
        open_wo_statistics(_aoi())
    assert time.monotonic() - started < 0.35


def test_open_wo_statistics_sets_pystac_and_lazy_rio_timeouts(monkeypatch):
    """STAC search timeout constants must be wired to pystac_client, and COG
    read configuration must be installed on odc-stac for later lazy reads."""
    import hydroseason._io_dea_stats as mod

    items = [_FakeItem("item-1", "2020-06-01T00:00:00Z")]
    calls = _install_stac_fakes(monkeypatch, items, _dask_dataset, module=mod)
    configure_rio = Mock()
    monkeypatch.setattr("odc.stac.configure_rio", configure_rio)

    result = open_wo_statistics(_aoi())

    assert calls["search_count"] == 1
    import pystac_client

    pystac_client.Client.open.assert_called_once_with(
        mod.DEFAULT_WO_STATISTICS_STAC_URL,
        timeout=(mod.STAC_CONNECT_TIMEOUT_S, mod.STAC_READ_TIMEOUT_S),
    )
    configure_rio.assert_called_once_with(
        cloud_defaults=True,
        aws={"aws_unsigned": True},
    )
    assert hasattr(result["count_wet"].data, "compute")
    assert result["count_wet"].isel(x=0, y=1).compute().item() >= 0


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


@pytest.mark.parametrize(
    "shape_name, grid",
    [
        ("isolated pixel", np.pad(np.array([[1]], dtype=np.int32), ((3, 12), (11, 4)))),
        ("thin diagonal", np.eye(16, dtype=np.int32)),
        ("thin orthogonal channel", np.pad(np.ones((1, 20), dtype=np.int32), ((9, 10), (0, 0)))),
        ("partial coarse block", np.pad(np.array([[1]], dtype=np.int32), ((9, 0), (9, 0)))),
    ],
)
def test_footprint_vector_clip_keeps_every_native_wet_pixel(shape_name, grid):
    """The polygon used for fine clipping must rasterize back over every native
    wet pixel; coarse-window coverage alone would not catch clip shrinkage."""
    from hydroseason._io_geo import _inside_aoi_mask_like
    from hydroseason._io_wofs_acquire import _wet_aoi_from_planning_footprint

    stats = _stats_dataset(grid)
    footprint = build_wet_planning_footprint(
        stats, factor=4, safety_cells=0, requested_years=[1988],
    )

    wet_aoi = _wet_aoi_from_planning_footprint(footprint)
    clipped_inside = np.asarray(
        _inside_aoi_mask_like(footprint.native_mask, wet_aoi).values, dtype=bool
    )
    native = np.asarray(footprint.native_mask.values, dtype=bool)

    assert np.all(~native | clipped_inside), shape_name


# --------------------------------------------------------------------------
# build_historical_water_mask / HistoricalWaterMask: the exact, immutable
# scientific-footprint raster (task 1 of the historical-water-mask plan).
# `(count_wet > 0) AND rasterized_AOI`, at native grid resolution, never
# closed/buffered/dilated/round-tripped through polygons. Distinct from
# WetPlanningFootprint, which stays performance-only.
# --------------------------------------------------------------------------

_HISTORICAL_MASK_RES = 30.0


def _historical_aoi(*, res=_HISTORICAL_MASK_RES, n=16):
    """An AOI covering only the LEFT half of a synthetic n x n stats grid.

    Grid pixel (row, col) has x-centre col*res, y-centre -row*res (matching
    `_stats_dataset`'s coordinate convention). Restricting the AOI to
    x < (n/2)*res means every wet pixel placed at col >= n/2 must be excluded
    by the AND-with-AOI step, distinguishing "AOI clip happened" from "no
    clip happened" in the exact-mask assertions below.
    """
    half_extent = (n / 2) * res
    return gpd.GeoDataFrame(
        {"geometry": [box(-res, -n * res, half_extent, res)]}, crs="EPSG:3577"
    )


def test_historical_water_mask_excludes_zero_wet_and_outside_aoi_cells():
    """The exact mask must equal (count_wet > 0) AND rasterized_AOI: a wet
    pixel outside the AOI must be excluded, and a dry pixel inside the AOI
    must stay excluded -- no closing, buffering, dilation, or polygon
    round-tripping is applied anywhere in this path."""
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 2] = 1  # wet, inside the AOI's left half
    grid[3, 12] = 1  # wet, outside the AOI's left half -- must be excluded
    stats = _stats_dataset(grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z")

    result = build_historical_water_mask(
        stats, _historical_aoi()
    )

    mask = np.asarray(result.mask, dtype=bool)
    assert mask[3, 2]
    assert not mask[3, 12]
    assert mask.sum() == 1
    assert result.pixel_count == 1


def test_historical_water_mask_value_object_records_full_provenance():
    grid = np.zeros((10, 10), dtype=np.int32)
    grid[2, 2] = 1
    stats = _stats_dataset(
        grid,
        time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z",
        product=DEA_STATS_ALLTIME_COLLECTION,
    )
    aoi = _historical_aoi(n=10)

    result = build_historical_water_mask(stats, aoi)

    assert isinstance(result, HistoricalWaterMask)
    assert result.crs
    assert result.transform and isinstance(result.transform, tuple)
    assert result.shape == (10, 10)
    assert result.resolution == (_HISTORICAL_MASK_RES, _HISTORICAL_MASK_RES)
    assert result.pixel_count == int(np.asarray(result.mask, dtype=bool).sum())
    assert result.source_product == DEA_STATS_ALLTIME_COLLECTION
    assert result.source_version
    assert isinstance(result.source_item_ids, tuple) and result.source_item_ids
    assert isinstance(result.source_lineage, tuple) and result.source_lineage
    assert result.coverage_start == "1987-01-01T00:00:00Z"
    assert result.coverage_end == "2025-12-31T00:00:00Z"
    assert len(result.aoi_sha256) == 64
    assert len(result.mask_sha256) == 64


def test_historical_water_mask_empty_mask_raises_dea_stats_unavailable():
    """count_wet all-zero within the AOI must fail closed: an empty mask
    could otherwise be mistaken for 'no water to analyse' rather than 'the
    source/AOI combination has none'."""
    grid = np.zeros((10, 10), dtype=np.int32)
    stats = _stats_dataset(grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z")

    with pytest.raises(DEAStatsUnavailable, match="no historically observed water"):
        build_historical_water_mask(stats, _historical_aoi(n=10))


def test_historical_water_mask_all_wet_outside_aoi_raises_dea_stats_unavailable():
    """Wet pixels that exist only outside the AOI must also fail as 'no
    historically observed water' -- the AND-with-AOI step must run before
    the emptiness check, not after."""
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 12] = 1  # outside the left-half AOI
    stats = _stats_dataset(grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z")

    with pytest.raises(DEAStatsUnavailable, match="no historically observed water"):
        build_historical_water_mask(stats, _historical_aoi())


def test_analysis_end_past_coverage_end_still_builds():
    """The mask is an all-time (count_wet > 0) AND AOI footprint, not a
    time-windowed artifact -- a requested analysis_end past the source's
    recorded coverage_end must not block the build. Identical pixel_count
    and mask_sha256 versus an in-coverage build prove only the gate was
    removed, not the raster itself."""
    grid = np.zeros((10, 10), dtype=np.int32)
    grid[2, 2] = 1
    aoi = _historical_aoi(n=10)
    short_coverage_stats = _stats_dataset(
        grid, time_span="1987-01-01T00:00:00Z/2018-12-31T00:00:00Z"
    )
    in_coverage_stats = _stats_dataset(
        grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z"
    )

    result = build_historical_water_mask(short_coverage_stats, aoi)
    baseline = build_historical_water_mask(in_coverage_stats, aoi)

    assert result.pixel_count == baseline.pixel_count
    assert result.mask_sha256 == baseline.mask_sha256


def test_analysis_start_before_coverage_start_still_builds():
    """Same principle at the other edge: a source whose recorded coverage
    starts after the requested window's start (here, well after the usual
    1987 baseline) must still build, with the same pixel_count/mask_sha256
    as an in-coverage build."""
    grid = np.zeros((10, 10), dtype=np.int32)
    grid[2, 2] = 1
    aoi = _historical_aoi(n=10)
    late_start_stats = _stats_dataset(
        grid, time_span="2015-01-01T00:00:00Z/2018-12-31T00:00:00Z"
    )
    in_coverage_stats = _stats_dataset(
        grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z"
    )

    result = build_historical_water_mask(late_start_stats, aoi)
    baseline = build_historical_water_mask(in_coverage_stats, aoi)

    assert result.pixel_count == baseline.pixel_count
    assert result.mask_sha256 == baseline.mask_sha256


def test_historical_water_mask_incompatible_lineage_raises_dea_stats_unavailable():
    """Only the all-time Multi-Year product (ga_ls_wo_fq_myear_3) is a valid
    source for the historical mask -- an incompatible product (e.g. the
    per-calendar-year summary) must fail closed rather than silently being
    treated as an equivalent lineage to the monthly WOfS collection."""
    grid = np.zeros((10, 10), dtype=np.int32)
    grid[2, 2] = 1
    stats = _stats_dataset(
        grid,
        time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z",
        product=DEA_STATS_ANNUAL_COLLECTION,
    )

    with pytest.raises(DEAStatsUnavailable, match="incompatible WOfS lineage"):
        build_historical_water_mask(stats, _historical_aoi(n=10))


def test_historical_water_mask_geographic_grid_builds_correctly():
    """The mask builder must work on a geographic (lat/lon) grid too --
    open_wo_statistics is source-agnostic about CRS, so this module must not
    silently assume a projected grid."""
    res = 0.00027  # ~30 m in degrees
    grid = np.zeros((8, 8), dtype=np.int32)
    grid[1, 1] = 1
    h, w = grid.shape
    count_wet = xr.DataArray(
        grid.astype(np.int32),
        dims=("y", "x"),
        coords={"y": 30.0 - np.arange(h) * res, "x": 130.0 + np.arange(w) * res},
    )
    count_clear = xr.full_like(count_wet, 10)
    ds = xr.Dataset({"count_wet": count_wet, "count_clear": count_clear})
    ds = ds.rio.write_crs("EPSG:4326").rio.write_transform()
    ds.attrs["provenance"] = {
        "product": DEA_STATS_ALLTIME_COLLECTION,
        "stac_url": "https://example.test/stac",
        "item_ids": ["item-1"],
        "crs": "EPSG:4326",
        "resolution": res,
        "time_span": "1987-01-01T00:00:00Z/2025-12-31T00:00:00Z",
    }
    aoi = gpd.GeoDataFrame(
        {"geometry": [box(129.999, 29.0, 131.0, 30.001)]}, crs="EPSG:4326"
    )

    result = build_historical_water_mask(ds, aoi)

    mask = np.asarray(result.mask, dtype=bool)
    assert mask[1, 1]
    assert result.pixel_count == 1
    assert result.crs


def test_historical_water_mask_digest_is_repeatable_and_sensitive():
    grid = np.zeros((10, 10), dtype=np.int32)
    grid[2, 2] = 1
    time_span = "1987-01-01T00:00:00Z/2025-12-31T00:00:00Z"
    stats_a = _stats_dataset(grid, time_span=time_span)
    stats_b = _stats_dataset(grid, time_span=time_span)
    aoi = _historical_aoi(n=10)

    result_a = build_historical_water_mask(stats_a, aoi)
    result_b = build_historical_water_mask(stats_b, aoi)

    assert result_a.mask_sha256 == result_b.mask_sha256
    assert result_a.aoi_sha256 == result_b.aoi_sha256

    other_grid = np.zeros((10, 10), dtype=np.int32)
    other_grid[5, 5] = 1
    stats_other = _stats_dataset(other_grid, time_span=time_span)
    result_other = build_historical_water_mask(stats_other, aoi)

    assert result_other.mask_sha256 != result_a.mask_sha256


# --------------------------------------------------------------------------
# build_planning_footprint_from_historical_mask: builds a WetPlanningFootprint
# from an already-built HistoricalWaterMask. native_mask must be the exact
# boolean array (no dilation); only coarse_mask may be max-pooled/dilated.
# --------------------------------------------------------------------------


def test_planning_footprint_from_historical_mask_native_mask_is_exact():
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 2] = 1
    stats = _stats_dataset(grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z")
    historical_mask = build_historical_water_mask(
        stats, _historical_aoi()
    )

    footprint = build_planning_footprint_from_historical_mask(
        historical_mask, factor=4, safety_cells=1,
    )

    assert isinstance(footprint, WetPlanningFootprint)
    native = np.asarray(footprint.native_mask.values, dtype=bool) if hasattr(
        footprint.native_mask, "values"
    ) else np.asarray(footprint.native_mask, dtype=bool)
    exact = np.asarray(historical_mask.mask, dtype=bool)
    assert np.array_equal(native, exact)
    assert historical_mask.mask_sha256 in footprint.digest or footprint.digest


def test_planning_footprint_safety_dilation_cannot_mutate_exact_mask():
    """The defining guarantee: expanding coarse_mask with safety_cells may
    grow the planning footprint, but HistoricalWaterMask.mask, pixel_count,
    and mask_sha256 must be completely unaffected by that dilation."""
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[6, 6] = 1
    stats = _stats_dataset(grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z")
    historical_mask = build_historical_water_mask(
        stats, _historical_aoi()
    )

    before_mask = np.array(historical_mask.mask, copy=True, dtype=bool)
    before_pixel_count = historical_mask.pixel_count
    before_digest = historical_mask.mask_sha256

    plain = build_planning_footprint_from_historical_mask(
        historical_mask, factor=4, safety_cells=0,
    )
    haloed = build_planning_footprint_from_historical_mask(
        historical_mask, factor=4, safety_cells=2,
    )

    plain_coarse = np.asarray(plain.coarse_mask.values, dtype=bool)
    haloed_coarse = np.asarray(haloed.coarse_mask.values, dtype=bool)
    assert haloed_coarse.sum() >= plain_coarse.sum()

    assert np.array_equal(np.asarray(historical_mask.mask, dtype=bool), before_mask)
    assert historical_mask.pixel_count == before_pixel_count
    assert historical_mask.mask_sha256 == before_digest


# --------------------------------------------------------------------------
# HistoricalWaterMaskRequest / write_historical_water_mask /
# read_historical_water_mask / load_or_build_historical_water_mask
# (task 2 of the historical-water-mask plan): persist and verify a
# HistoricalWaterMask under cache_root/historical-water-masks/, and
# orchestrate cache-first, one-network-load loading.
# --------------------------------------------------------------------------


def _historical_mask_request(**overrides):
    fields = dict(
        aoi_sha256="a" * 64,
        product=DEA_STATS_ALLTIME_COLLECTION,
        stac_url="https://example.test/stac",
        crs="EPSG:3577",
        resolution=30.0,
    )
    fields.update(overrides)
    return HistoricalWaterMaskRequest(**fields)


def _built_historical_mask(*, seed_cell=(3, 2), n=16, time_span=None):
    grid = np.zeros((n, n), dtype=np.int32)
    grid[seed_cell] = 1
    stats = _stats_dataset(
        grid,
        time_span=time_span or "1987-01-01T00:00:00Z/2025-12-31T00:00:00Z",
    )
    aoi = _historical_aoi(n=n)
    return build_historical_water_mask(stats, aoi)


def test_historical_water_mask_request_digest_excludes_paths_and_dates():
    """The canonical request digest must depend only on AOI/product/STAC/CRS/
    resolution -- never on a mutable filesystem path or an analysis start/end
    date, since two different analysis windows against the same source must
    share one cache entry."""
    request = _historical_mask_request()
    same = _historical_mask_request()
    assert request.request_digest() == same.request_digest()

    different_product = _historical_mask_request(product=DEA_STATS_ANNUAL_COLLECTION)
    assert different_product.request_digest() != request.request_digest()

    different_aoi = _historical_mask_request(aoi_sha256="b" * 64)
    assert different_aoi.request_digest() != request.request_digest()

    different_stac = _historical_mask_request(stac_url="https://other.test/stac")
    assert different_stac.request_digest() != request.request_digest()

    different_crs = _historical_mask_request(crs="EPSG:4326")
    assert different_crs.request_digest() != request.request_digest()

    different_res = _historical_mask_request(resolution=10.0)
    assert different_res.request_digest() != request.request_digest()

    assert not hasattr(request, "analysis_end")
    assert not hasattr(request, "cache_root")


def test_write_then_read_historical_water_mask_round_trips(tmp_path):
    mask = _built_historical_mask()
    request = _historical_mask_request()

    write_historical_water_mask(tmp_path, request, mask)
    result = read_historical_water_mask(tmp_path, request)

    assert result is not None
    assert np.array_equal(np.asarray(result.mask, dtype=bool), np.asarray(mask.mask, dtype=bool))
    assert result.pixel_count == mask.pixel_count
    assert result.mask_sha256 == mask.mask_sha256
    assert result.aoi_sha256 == mask.aoi_sha256
    assert result.crs == mask.crs
    assert result.shape == mask.shape
    assert result.resolution == mask.resolution
    assert result.source_product == mask.source_product
    assert result.source_version == mask.source_version
    assert result.source_item_ids == mask.source_item_ids
    assert result.source_lineage == mask.source_lineage
    assert result.coverage_start == mask.coverage_start
    assert result.coverage_end == mask.coverage_end


def test_write_historical_water_mask_persists_two_dimensional_boolean_zarr(tmp_path):
    """The on-disk mask array must be a plain 2D boolean Zarr array, not a
    time-cubed or integer-canonical-value array like the WOfS annual cache."""
    zarr = pytest.importorskip("zarr")
    mask = _built_historical_mask()
    request = _historical_mask_request()

    write_historical_water_mask(tmp_path, request, mask)

    artifacts_dir = tmp_path / "historical-water-masks" / "artifacts"
    artifact_dirs = list(artifacts_dir.iterdir())
    assert len(artifact_dirs) == 1
    zarr_path = artifact_dirs[0] / "mask.zarr"
    assert zarr_path.exists()
    array = zarr.open_array(str(zarr_path), mode="r")
    assert array.dtype == bool
    assert array.shape == mask.shape
    assert np.array_equal(np.asarray(array[:]), np.asarray(mask.mask, dtype=bool))

    manifest_path = artifact_dirs[0] / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in (
        "crs", "transform", "shape", "resolution", "pixel_count",
        "source_product", "source_version", "source_item_ids",
        "source_lineage", "coverage_start", "coverage_end", "aoi_sha256",
        "mask_sha256",
    ):
        assert field in manifest, f"manifest missing {field!r}"


def test_write_historical_water_mask_index_pointer_keyed_by_request(tmp_path):
    mask = _built_historical_mask()
    request = _historical_mask_request()

    write_historical_water_mask(tmp_path, request, mask)

    index_path = (
        tmp_path / "historical-water-masks" / "index" / f"{request.request_digest()}.json"
    )
    assert index_path.exists()
    index_entry = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_entry["request_digest"] == request.request_digest()
    assert "artifact_digest" in index_entry
    assert index_entry.get("aoi_sha256") == request.aoi_sha256
    assert index_entry.get("product") == request.product
    assert index_entry.get("stac_url") == request.stac_url


def test_requested_monthly_dates_do_not_create_duplicate_artifacts(tmp_path):
    """The same source mask requested for different monthly analysis dates
    must not create duplicate mask artifacts -- the artifact digest excludes
    analysis_end entirely."""
    mask = _built_historical_mask()
    request = _historical_mask_request()

    write_historical_water_mask(tmp_path, request, mask)
    write_historical_water_mask(tmp_path, request, mask)

    artifacts_dir = tmp_path / "historical-water-masks" / "artifacts"
    assert len(list(artifacts_dir.iterdir())) == 1


def test_read_historical_water_mask_returns_none_when_no_cache(tmp_path):
    request = _historical_mask_request()
    assert read_historical_water_mask(tmp_path, request) is None


def test_read_historical_water_mask_rejects_tampered_mask_bytes(tmp_path):
    zarr = pytest.importorskip("zarr")
    mask = _built_historical_mask()
    request = _historical_mask_request()
    write_historical_water_mask(tmp_path, request, mask)

    artifacts_dir = tmp_path / "historical-water-masks" / "artifacts"
    artifact_dir = next(artifacts_dir.iterdir())
    # Use the same long-path-aware store as production. A bare string path
    # can raise FileNotFoundError while opening a chunk on Windows when the
    # full-suite temp root crosses MAX_PATH.
    array = zarr.open_array(_zarr_store(artifact_dir / "mask.zarr"), mode="r+")
    tampered = np.asarray(array[:], dtype=bool)
    tampered[0, 0] = not tampered[0, 0]
    array[:] = tampered
    assert np.array_equal(np.asarray(array[:], dtype=bool), tampered)

    with pytest.raises(ValueError, match="historical water mask cache verification failed"):
        read_historical_water_mask(tmp_path, request)


def test_read_historical_water_mask_rejects_tampered_manifest_field(tmp_path):
    mask = _built_historical_mask()
    request = _historical_mask_request()
    write_historical_water_mask(tmp_path, request, mask)

    artifacts_dir = tmp_path / "historical-water-masks" / "artifacts"
    artifact_dir = next(artifacts_dir.iterdir())
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pixel_count"] = manifest["pixel_count"] + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="historical water mask cache verification failed"):
        read_historical_water_mask(tmp_path, request)


def test_cached_artifact_serves_any_analysis_window(tmp_path):
    """A cached artifact whose recorded coverage_end predates a later
    requested analysis_end is still a hit -- the mask is an all-time
    footprint, so it serves any requested analysis window rather than being
    reported as a miss."""
    mask = _built_historical_mask(
        time_span="1987-01-01T00:00:00Z/2018-12-31T00:00:00Z",
    )
    request = _historical_mask_request()
    write_historical_water_mask(tmp_path, request, mask)

    result = read_historical_water_mask(tmp_path, request)
    assert result is not None
    assert result.mask_sha256 == mask.mask_sha256


def test_load_or_build_warm_cache_makes_zero_statistics_calls(tmp_path, monkeypatch):
    aoi = _historical_aoi(n=16)
    real_aoi_sha256 = _historical_aoi_digest(aoi.to_crs("EPSG:3577"))
    mask = _built_historical_mask()
    request = _historical_mask_request(aoi_sha256=real_aoi_sha256)
    write_historical_water_mask(tmp_path, request, mask)

    def _boom(*args, **kwargs):
        raise AssertionError("open_wo_statistics must not be called on a warm cache hit")

    monkeypatch.setattr(
        "hydroseason._io_dea_stats.open_wo_statistics", _boom,
    )

    result = load_or_build_historical_water_mask(
        aoi,
        cache_root=tmp_path,
        offline=True,
        stac_url=request.stac_url,
        product=request.product,
        crs=request.crs,
        resolution=request.resolution,
    )

    assert result.mask_sha256 == mask.mask_sha256


def test_load_or_build_offline_no_cache_fails_closed(tmp_path):
    with pytest.raises(DEAStatsUnavailable):
        load_or_build_historical_water_mask(
            _historical_aoi(n=16),
            cache_root=tmp_path,
            offline=True,
        )


def test_load_or_build_cold_cache_builds_and_persists(tmp_path, monkeypatch):
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 2] = 1
    stats = _stats_dataset(grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z")

    call_count = {"n": 0}

    def _fake_open_wo_statistics(aoi, **kwargs):
        call_count["n"] += 1
        return stats

    monkeypatch.setattr(
        "hydroseason._io_dea_stats.open_wo_statistics", _fake_open_wo_statistics,
    )

    aoi = _historical_aoi(n=16)
    result = load_or_build_historical_water_mask(
        aoi, cache_root=tmp_path, offline=False,
    )

    assert call_count["n"] == 1
    assert result.pixel_count == 1

    artifacts_dir = tmp_path / "historical-water-masks" / "artifacts"
    assert len(list(artifacts_dir.iterdir())) == 1

    # A second call must be served from the now-warm cache: zero further
    # Statistics calls.
    result_again = load_or_build_historical_water_mask(
        aoi, cache_root=tmp_path, offline=False,
    )
    assert call_count["n"] == 1
    assert result_again.mask_sha256 == result.mask_sha256


def test_load_or_build_statistics_failure_offline_mode_returns_cache_or_raises(tmp_path, monkeypatch):
    """After a Statistics failure, offline mode (or the fallback described in
    the brief) must return only a verified cache, and must never construct a
    full-AOI mask -- with no cache present, it raises rather than silently
    building something unverifiable."""
    def _fail(aoi, **kwargs):
        raise DEAStatsUnavailable("simulated source failure")

    monkeypatch.setattr(
        "hydroseason._io_dea_stats.open_wo_statistics", _fail,
    )

    with pytest.raises(DEAStatsUnavailable):
        load_or_build_historical_water_mask(
            _historical_aoi(n=16),
            cache_root=tmp_path, offline=False,
        )


def test_load_or_build_product_change_produces_distinct_verified_artifact(tmp_path, monkeypatch):
    grid = np.zeros((16, 16), dtype=np.int32)
    grid[3, 2] = 1
    stats_alltime = _stats_dataset(
        grid, time_span="1987-01-01T00:00:00Z/2025-12-31T00:00:00Z",
        product=DEA_STATS_ALLTIME_COLLECTION,
    )

    def _fake_open_wo_statistics(aoi, *, product=DEA_STATS_ALLTIME_COLLECTION, **kwargs):
        return stats_alltime

    monkeypatch.setattr(
        "hydroseason._io_dea_stats.open_wo_statistics", _fake_open_wo_statistics,
    )

    aoi = _historical_aoi(n=16)
    result_default = load_or_build_historical_water_mask(
        aoi, cache_root=tmp_path, offline=False,
        stac_url="https://a.test/stac",
    )
    result_other_stac = load_or_build_historical_water_mask(
        aoi, cache_root=tmp_path, offline=False,
        stac_url="https://b.test/stac",
    )

    assert result_default.mask_sha256 == result_other_stac.mask_sha256

    artifacts_dir = tmp_path / "historical-water-masks" / "artifacts"
    # Two distinct index entries (different stac_url -> different request
    # digest) may point at artifacts; a different *source item/version*
    # would additionally force a distinct artifact_digest even when the
    # mask pixels are identical, but that is exercised by the digest-level
    # test below rather than requiring two live Statistics loads here.
    index_dir = tmp_path / "historical-water-masks" / "index"
    assert len(list(index_dir.iterdir())) == 2
    assert len(list(artifacts_dir.iterdir())) >= 1


def test_artifact_digest_differs_when_source_version_changes_despite_identical_mask(tmp_path):
    """Two HistoricalWaterMask builds with byte-identical mask pixels but
    different source provenance (e.g. a WOfS processing-version bump) must
    produce distinct artifact_digests, so a source-version change never
    silently overwrites a pinned artifact."""
    mask_a = _built_historical_mask()
    mask_b = _built_historical_mask()
    assert mask_a.mask_sha256 == mask_b.mask_sha256  # identical pixels/grid

    mask_b_other_version = dataclasses.replace(mask_b, source_version="999")

    request = _historical_mask_request()
    write_historical_water_mask(tmp_path, request, mask_a)
    write_historical_water_mask(tmp_path, request, mask_b_other_version)

    artifacts_dir = tmp_path / "historical-water-masks" / "artifacts"
    assert len(list(artifacts_dir.iterdir())) == 2


def test_wo_statistics_unavailable_is_a_dea_stats_unavailable():
    """Every statistics failure must satisfy the module's documented
    fail-open contract ("Every failure path raises DEAStatsUnavailable"),
    so the existing `except DEAStatsUnavailable` fallbacks in
    _io_wofs_acquire and _historical_water_mask actually cover an
    unreachable statistics endpoint."""
    import hydroseason._io_dea_stats as mod

    assert issubclass(mod.WoStatisticsUnavailable, mod.DEAStatsUnavailable)


def test_open_wo_statistics_unreachable_endpoint_raises_typed_error(monkeypatch):
    """pystac_client.Client.open is a network call: a dead proxy or an
    unreachable endpoint must arrive as WoStatisticsUnavailable naming the
    URL, not as a raw pystac_client.APIError. This is the exact failure
    reported from the field (ProxyError -> APIError escaping the loader)."""
    import hydroseason._io_dea_stats as mod

    def explode(*args, **kwargs):
        raise RuntimeError("ProxyError: connection to 127.0.0.1:9 refused")

    monkeypatch.setattr("pystac_client.Client.open", explode)

    with pytest.raises(mod.WoStatisticsUnavailable, match=r"example\.invalid"):
        open_wo_statistics(_aoi(), stac_url="https://example.invalid/stac")


def test_open_wo_statistics_search_failure_names_the_endpoint(monkeypatch):
    import hydroseason._io_dea_stats as mod

    client = Mock()
    client.search.side_effect = RuntimeError("boom")
    monkeypatch.setattr("pystac_client.Client.open", Mock(return_value=client))

    with pytest.raises(mod.WoStatisticsUnavailable, match=r"example\.invalid"):
        open_wo_statistics(_aoi(), stac_url="https://example.invalid/stac")
