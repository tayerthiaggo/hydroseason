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

from shapely.geometry import box

from hydroseason._io_dea_stats import (
    DEA_STATS_ALLTIME_COLLECTION,
    DEA_STATS_ANNUAL_COLLECTION,
    DEAStatsUnavailable,
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
