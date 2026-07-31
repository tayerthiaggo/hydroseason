"""Tests for the DEA Water Observation Statistics wet-mask fetch.

Fully offline: the STAC client and the raster loader are both injected, so
these tests never touch the network.
"""
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
    fetch_dea_stats_wet_aoi,
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
