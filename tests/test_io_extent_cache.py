from __future__ import annotations

import warnings
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest


def _aoi():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import box

    return geopandas.GeoDataFrame(geometry=[box(0, 0, 2, 2)], crs="EPSG:4326")


def _mixed_canonical_cube():
    xr = pytest.importorskip("xarray")
    values = np.resize(np.array([-2, -1, 0, 1], dtype=np.int8), (12, 4, 4))
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": pd.date_range("2020-01-01", periods=12, freq="MS")},
    ).chunk({"time": 1, "y": 2, "x": 2})


def _fake_monthly_cube(start: str, end: str):
    xr = pytest.importorskip("xarray")
    dates = pd.date_range(start, end, freq="MS")
    values = np.ones((len(dates), 2, 2), dtype=np.int8)
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": dates, "y": [0, 1], "x": [0, 1]},
    )


def _fake_georeferenced_monthly_cube(start: str, end: str):
    """Like ``_fake_monthly_cube``, but with ``.rio`` metadata matching the
    grid ``_historical_water_mask()`` builds (``EPSG:3577``, the same 2x2
    ``transform``) -- required by ``_clip_to_aoi`` when a historical mask is
    applied on the untiled ``load_wofs_from_stac`` path.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("rioxarray")
    import rioxarray  # noqa: F401  (registers the .rio accessor)
    from affine import Affine

    dates = pd.date_range(start, end, freq="MS")
    values = np.ones((len(dates), 2, 2), dtype=np.int8)
    cube = xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": dates, "y": [45.0, 15.0], "x": [15.0, 45.0]},
    )
    return (
        cube.rio.set_spatial_dims(x_dim="x", y_dim="y")
        .rio.write_crs("EPSG:3577")
        .rio.write_transform(Affine(30.0, 0.0, 0.0, 0.0, -30.0, 60.0))
    )


def _fake_wet_aoi():
    # A minimal real GeoDataFrame (not a bare sentinel) so it can pass through
    # monthly_water_extent's wet_aoi rasterisation unchanged, while identity
    # ("is this the same object that came out of compute_wet_aoi/was passed
    # in explicitly?") is still trackable via `is`/`==` through the pipeline.
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    return gpd.GeoDataFrame({"geometry": [box(-10, -10, 10, 10)]}, geometry="geometry", crs=None)


def _historical_water_mask(*, aoi=None, coverage_end="2021-12-31"):
    from hydroseason._historical_water_mask import HistoricalWaterMask, _aoi_digest, _mask_digest

    if aoi is None:
        aoi_digest = "aoi-digest"
    else:
        import hydroseason.io as hio

        aoi_on_mask_grid = hio.load_aoi(aoi).to_crs("EPSG:3577")
        aoi_digest = _aoi_digest(aoi_on_mask_grid)

    mask = np.array([[True, False], [True, True]])
    transform = (30.0, 0.0, 0.0, 0.0, -30.0, 60.0)
    resolution = (30.0, 30.0)
    return HistoricalWaterMask(
        mask=mask,
        crs="EPSG:3577",
        transform=transform,
        shape=(2, 2),
        resolution=resolution,
        pixel_count=3,
        source_product="ga_ls_wo_fq_myear_3",
        source_version="3",
        source_item_ids=("multi-year-item",),
        source_lineage=("ga_ls_wo_fq_myear_3", "multi-year-item"),
        coverage_start="1987-01-01",
        coverage_end=coverage_end,
        aoi_sha256=aoi_digest,
        mask_sha256=_mask_digest(
            mask,
            crs="EPSG:3577",
            transform=transform,
            shape=(2, 2),
            resolution=resolution,
        ),
    )


def _completed_extent(start: str, end: str):
    index = pd.date_range(start, end, freq="MS")
    return pd.DataFrame(
        {
            "n_water": 1,
            "n_aoi": 3,
            "n_valid": 3,
            "n_invalid": 0,
            "n_wet_aoi": 3,
            "extent_pct": 100.0 / 3.0,
            "invalid_pct": 0.0,
            "wet_fill_pct": 100.0 / 3.0,
        },
        index=index,
    )


def _synthetic_historical_mask_reduction_inputs():
    """A real, georeferenced cube with invalid land beyond the wet mask.

    A regression here catches either a reduction over the planning/full AOI
    instead of the exact historical mask, or a mask application that leaves
    excluded invalid cells in the denominator.
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("geopandas")
    pytest.importorskip("rioxarray")
    import geopandas as gpd
    import rioxarray  # noqa: F401  (registers the .rio accessor)
    from affine import Affine
    from shapely.geometry import box

    from hydroseason._historical_water_mask import HistoricalWaterMask, _mask_digest

    transform = (30.0, 0.0, 0.0, 0.0, -30.0, 90.0)
    values = np.array(
        [
            # Two wet pixels and four dry pixels within the exact mask;
            # invalid land occupies the entire excluded final column.
            [[1, 0, -1], [1, 0, -1], [0, 0, -1]],
            # A source month with no valid observations anywhere.
            [[-1, -1, -1], [-1, -1, -1], [-1, -1, -1]],
        ],
        dtype=np.int8,
    )
    cube = xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={
            "time": pd.to_datetime(["2020-01-01", "2020-02-01"]),
            "y": [75.0, 45.0, 15.0],
            "x": [15.0, 45.0, 75.0],
        },
    )
    cube = (
        cube.rio.set_spatial_dims(x_dim="x", y_dim="y")
        .rio.write_crs("EPSG:3577")
        .rio.write_transform(Affine(*transform))
    )
    mask_values = np.array(
        [[True, True, False], [True, True, False], [True, True, False]]
    )
    historical_mask = HistoricalWaterMask(
        mask=mask_values,
        crs="EPSG:3577",
        transform=transform,
        shape=(3, 3),
        resolution=(30.0, 30.0),
        pixel_count=6,
        source_product="ga_ls_wo_fq_myear_3",
        source_version="3",
        source_item_ids=("synthetic-item",),
        source_lineage=("ga_ls_wo_fq_myear_3", "synthetic-item"),
        coverage_start="1987-01-01",
        coverage_end="2021-12-31",
        aoi_sha256="synthetic-aoi",
        mask_sha256=_mask_digest(
            mask_values,
            crs="EPSG:3577",
            transform=transform,
            shape=(3, 3),
            resolution=(30.0, 30.0),
        ),
    )
    aoi = gpd.GeoDataFrame(
        {"geometry": [box(0, 0, 90, 90)]}, geometry="geometry", crs="EPSG:3577"
    )
    return cube, aoi, historical_mask


def test_exact_historical_mask_changes_only_the_intended_reduction_population():
    """Excluded invalid land must not change in-mask water or extent percent."""
    from hydroseason.hydro_year import monthly_water_extent
    from hydroseason.io import _clip_to_aoi

    cube, aoi, historical_mask = _synthetic_historical_mask_reduction_inputs()
    full_aoi = monthly_water_extent(cube, time_block=2)
    historical = monthly_water_extent(
        _clip_to_aoi(cube, aoi, historical_water_mask=historical_mask), time_block=2
    )

    january = pd.Timestamp("2020-01-01")
    assert full_aoi.loc[january, "n_water"] == historical.loc[january, "n_water"] == 2
    assert full_aoi.loc[january, "n_valid"] == historical.loc[january, "n_valid"] == 6
    assert full_aoi.loc[january, "n_aoi"] == 9
    assert historical.loc[january, "n_aoi"] == historical_mask.pixel_count == 6
    assert full_aoi.loc[january, "extent_pct"] == historical.loc[january, "extent_pct"] == pytest.approx(100.0 / 3.0)
    assert full_aoi.loc[january, "invalid_pct"] == pytest.approx(100.0 * 3.0 / 9.0)
    assert historical.loc[january, "invalid_pct"] == 0.0


def test_historical_mask_denominator_is_fixed_for_normal_invalid_and_no_source_months():
    """A pinned historical pixel count survives every source-availability state."""
    from hydroseason._io_extent_cache import _missing_year_extent
    from hydroseason.hydro_year import monthly_water_extent
    from hydroseason.io import _clip_to_aoi

    cube, aoi, historical_mask = _synthetic_historical_mask_reduction_inputs()
    observed = monthly_water_extent(
        _clip_to_aoi(cube, aoi, historical_water_mask=historical_mask), time_block=2
    )
    no_source = _missing_year_extent(
        pd.Timestamp("2020-03-01"),
        pd.Timestamp("2020-03-31"),
        historical_water_mask=historical_mask,
    )
    result = pd.concat([observed, no_source])

    assert (result["n_aoi"] == historical_mask.pixel_count).all()
    assert result.loc["2020-01-01", "n_valid"] == 6  # normal source month
    assert result.loc["2020-02-01", "n_invalid"] == 6  # all-invalid source month
    assert result.loc["2020-03-01", "n_invalid"] == 6  # no source month
    assert result.loc["2020-02-01", "invalid_pct"] == 100.0
    assert result.loc["2020-03-01", "invalid_pct"] == 100.0


def test_cache_path_passes_exact_mask_and_dilated_planning_footprint_without_changing_counts(
    monkeypatch, tmp_path,
):
    """Planning dilation is passed to acquisition, never used as analysis area."""
    import hydroseason.io as hio
    from hydroseason._io_dea_stats import build_planning_footprint_from_historical_mask

    aoi = _aoi()
    historical_mask = _historical_water_mask(aoi=aoi)
    footprints = []

    def build_dilated_footprint(mask):
        footprint = build_planning_footprint_from_historical_mask(
            mask, factor=1, safety_cells=1
        )
        footprints.append(footprint)
        return footprint

    acquire = Mock(return_value=SimpleNamespace(path=tmp_path / "store.zarr"))
    expected = _completed_extent("2020-01-01", "2020-12-31")
    monkeypatch.setattr(hio, "build_planning_footprint_from_historical_mask", build_dilated_footprint)
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(hio, "open_completed_extent_counts", Mock(return_value=expected))

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac",
        "ga_ls_wo_3",
        aoi,
        "2020-01-01",
        "2020-12-31",
        resolution=30,
        mask_cache_dir=tmp_path / "cache",
        historical_water_mask=historical_mask,
    )

    footprint = footprints[0]
    native = np.asarray(getattr(footprint.native_mask, "values", footprint.native_mask), dtype=bool)
    coarse = np.asarray(getattr(footprint.coarse_mask, "values", footprint.coarse_mask), dtype=bool)
    assert np.array_equal(native, historical_mask.mask)
    assert coarse.sum() > native.sum()  # the planning halo is a true superset
    assert acquire.call_args.kwargs["historical_water_mask"] is historical_mask
    assert acquire.call_args.kwargs["planning_footprint"] is footprint
    pd.testing.assert_frame_equal(result, expected)
    assert (result["n_aoi"] == historical_mask.pixel_count).all()
    assert (result["n_valid"] == historical_mask.pixel_count).all()
    assert (result["n_water"] == 1).all()
    assert (result["n_invalid"] == 0).all()


def test_default_historical_mask_keeps_fixed_denominator_for_no_source_year(monkeypatch):
    import hydroseason.io as hio

    aoi = _aoi()
    monkeypatch.setattr(
        hio,
        "load_wofs_from_stac",
        Mock(side_effect=ValueError("No STAC items found for the requested AOI")),
    )

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac",
        "ga_ls_wo_3",
        aoi,
        "2020-01-01",
        "2020-12-31",
        resolution=30,
        historical_water_mask=_historical_water_mask(aoi=aoi),
    )

    assert (result["n_aoi"] == 3).all()
    assert (result["n_valid"] == 0).all()
    assert (result["n_invalid"] == 3).all()
    assert result["extent_pct"].isna().all()
    assert (result["invalid_pct"] == 100.0).all()


def test_uncached_load_pins_resolution_to_historical_mask_grid(monkeypatch):
    """A caller-omitted ``resolution`` must not let the monthly WOfS load
    drift onto odc.stac's native/auto-detected item grid while the exact
    historical water mask is always built at an explicit, EDGE-anchored
    resolution -- see ``_load_wofs_items``'s ``spatial`` dict, which omits
    ``"resolution"`` from the ``odc.stac.stac_load`` call entirely whenever
    ``resolution is None``, silently switching that call onto
    ``odc.stac``'s ``_auto_load_params`` native-item-alignment path. That
    grid is not guaranteed to agree with the historical mask's fixed
    EDGE-anchored grid, and previously produced a real
    ``GeoreferencingError`` on ``run_hydroseason(aoi=...)`` (no explicit
    ``resolution``, no ``cache_dir`` -- the documented, uncached DEA-fetch
    path) once ``_clip_to_aoi`` compared the two grids.

    Regression: ``load_wofs_monthly_extent`` must resolve the historical
    mask's own grid resolution and use it for every subsequent WOfS load,
    instead of forwarding a caller-omitted ``None`` straight through.
    """
    import hydroseason.io as hio

    aoi = _aoi()
    mask = _historical_water_mask(aoi=aoi)
    load = Mock(side_effect=ValueError("No STAC items found for the requested AOI"))
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac",
        "ga_ls_wo_3",
        aoi,
        "2020-01-01",
        "2020-12-31",
        historical_water_mask=mask,
    )

    assert load.call_args.kwargs["resolution"] == pytest.approx(mask.resolution[0])


def test_invalid_supplied_historical_mask_fails_before_acquisition(monkeypatch, tmp_path):
    import hydroseason.io as hio

    aoi = _aoi()
    invalid_mask = replace(_historical_water_mask(aoi=aoi), pixel_count=4)
    acquire = Mock()
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)

    with pytest.raises(ValueError, match="pixel_count"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            "2020-12-31",
            resolution=30,
            mask_cache_dir=tmp_path,
            historical_water_mask=invalid_mask,
        )

    acquire.assert_not_called()


def test_supplied_historical_mask_rejects_nat_coverage_before_acquisition(monkeypatch, tmp_path):
    import hydroseason.io as hio

    aoi = _aoi()
    invalid_mask = replace(_historical_water_mask(aoi=aoi), coverage_start=None)
    acquire = Mock(side_effect=AssertionError("acquisition"))
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)

    with pytest.raises(ValueError, match="invalid coverage provenance"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            "2020-12-31",
            resolution=30,
            mask_cache_dir=tmp_path,
            historical_water_mask=invalid_mask,
        )

    acquire.assert_not_called()


def test_default_historical_mask_is_resolved_once_and_reused_across_start_dates(monkeypatch, tmp_path):
    import hydroseason.io as hio

    mask = _historical_water_mask()
    resolve = Mock(return_value=mask)
    acquire = Mock(side_effect=lambda *_args, **_kwargs: SimpleNamespace(path=tmp_path / "store.zarr"))
    monkeypatch.setattr(hio, "load_or_build_historical_water_mask", resolve)
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(
        hio,
        "open_completed_extent_counts",
        lambda _handle, start, end, **_kwargs: _completed_extent(start, end),
    )

    common = dict(
        stac_url="https://example.invalid/monthly",
        collection="ga_ls_wo_3",
        aoi=_aoi(),
        end_date="2021-12-31",
        resolution=30,
        mask_cache_dir=tmp_path / "wofs-cache",
        historical_mask_cache_dir=tmp_path / "historical-cache",
        statistics_stac_url="https://example.invalid/statistics",
    )
    hio.load_wofs_monthly_extent(start_date="2020-01-01", **common)
    hio.load_wofs_monthly_extent(start_date="2021-01-01", **common)

    assert resolve.call_count == 2
    assert {call.kwargs["cache_root"] for call in resolve.call_args_list} == {
        tmp_path / "historical-cache"
    }
    assert all(call.kwargs["historical_water_mask"] is mask for call in acquire.call_args_list)
    assert all(call.kwargs["planning_footprint"] is not None for call in acquire.call_args_list)


def test_supplied_mask_past_coverage_warns_but_succeeds(monkeypatch, tmp_path):
    import hydroseason.io as hio
    from hydroseason._historical_water_mask import HistoricalMaskCoverageWarning

    aoi = _aoi()
    mask = _historical_water_mask(aoi=aoi, coverage_end="2021-12-31")
    acquire = Mock(return_value=SimpleNamespace(path=tmp_path / "store.zarr"))
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(
        hio,
        "open_completed_extent_counts",
        lambda _handle, start, end, **_kwargs: _completed_extent(start, end),
    )

    for end_date in ("2020-12-31", "2021-12-31"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            end_date,
            resolution=30,
            mask_cache_dir=tmp_path,
            historical_water_mask=mask,
        )

    with pytest.warns(HistoricalMaskCoverageWarning) as record:
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            "2022-01-01",
            resolution=30,
            mask_cache_dir=tmp_path,
            historical_water_mask=mask,
        )

    message = str(record[0].message)
    assert "2020-01-01" in message
    assert "2022-01-01" in message
    assert "1987-01-01" in message
    assert "2021-12-31" in message
    assert "1 month" in message

    assert acquire.call_count == 3
    assert all(call.kwargs["historical_water_mask"] is mask for call in acquire.call_args_list)


def test_built_mask_past_coverage_warns(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason._historical_water_mask import HistoricalMaskCoverageWarning

    aoi = _aoi()
    mask = _historical_water_mask(aoi=aoi, coverage_end="2021-12-31")
    monkeypatch.setattr(hio, "open_wo_statistics", Mock(return_value=SimpleNamespace()))
    monkeypatch.setattr(hio, "build_historical_water_mask", Mock(return_value=mask))
    load = Mock(
        side_effect=lambda _u, _c, _a, start, end, **kw: _fake_georeferenced_monthly_cube(
            start, end
        )
    )
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        # No cache_dir/mask_cache_dir/historical_mask_cache_dir at all -- this
        # is the no-cache-root, in-memory `build_historical_water_mask`
        # branch of `_resolve_historical_water_mask`, not the cache_root
        # branch already exercised above.
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            "2022-01-01",
            resolution=30,
        )

    coverage_warnings = [
        w for w in record if issubclass(w.category, HistoricalMaskCoverageWarning)
    ]
    assert len(coverage_warnings) == 1
    message = str(coverage_warnings[0].message)
    assert "2020-01-01" in message
    assert "2022-01-01" in message
    assert "1987-01-01" in message
    assert "2021-12-31" in message


def test_cached_mask_past_coverage_warns(monkeypatch, tmp_path):
    import hydroseason.io as hio
    from hydroseason._historical_water_mask import HistoricalMaskCoverageWarning

    aoi = _aoi()
    mask = _historical_water_mask(aoi=aoi, coverage_end="2021-12-31")
    monkeypatch.setattr(hio, "load_or_build_historical_water_mask", Mock(return_value=mask))
    acquire = Mock(return_value=SimpleNamespace(path=tmp_path / "store.zarr"))
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(
        hio,
        "open_completed_extent_counts",
        lambda _handle, start, end, **_kwargs: _completed_extent(start, end),
    )

    with pytest.warns(HistoricalMaskCoverageWarning) as record:
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            "2022-01-01",
            resolution=30,
            mask_cache_dir=tmp_path / "wofs-cache",
            historical_mask_cache_dir=tmp_path / "historical-cache",
        )

    message = str(record[0].message)
    assert "2020-01-01" in message
    assert "2022-01-01" in message
    assert "1987-01-01" in message
    assert "2021-12-31" in message


def test_window_inside_coverage_does_not_warn(monkeypatch, tmp_path):
    import hydroseason.io as hio
    from hydroseason._historical_water_mask import HistoricalMaskCoverageWarning

    aoi = _aoi()
    mask = _historical_water_mask(aoi=aoi, coverage_end="2021-12-31")
    acquire = Mock(return_value=SimpleNamespace(path=tmp_path / "store.zarr"))
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(
        hio,
        "open_completed_extent_counts",
        lambda _handle, start, end, **_kwargs: _completed_extent(start, end),
    )

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            "2020-12-31",
            resolution=30,
            mask_cache_dir=tmp_path,
            historical_water_mask=mask,
        )

    coverage_warnings = [
        w for w in record if issubclass(w.category, HistoricalMaskCoverageWarning)
    ]
    assert coverage_warnings == []


def test_window_before_coverage_start_warns_without_truncation_language(monkeypatch, tmp_path):
    import hydroseason.io as hio
    from hydroseason._historical_water_mask import HistoricalMaskCoverageWarning

    aoi = _aoi()
    mask = _historical_water_mask(aoi=aoi, coverage_end="2021-12-31")
    acquire = Mock(return_value=SimpleNamespace(path=tmp_path / "store.zarr"))
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(
        hio,
        "open_completed_extent_counts",
        lambda _handle, start, end, **_kwargs: _completed_extent(start, end),
    )

    with pytest.warns(HistoricalMaskCoverageWarning) as record:
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "1985-01-01",
            "2020-12-31",
            resolution=30,
            mask_cache_dir=tmp_path,
            historical_water_mask=mask,
        )

    message = str(record[0].message)
    assert "1985-01-01" in message
    assert "1987-01-01" in message
    assert "begins" in message
    assert "not counted in extent_pct" not in message
    assert "first inundated" not in message


def test_describe_coverage_gap_both_directions_attaches_caveat_once():
    from hydroseason._historical_water_mask import describe_coverage_gap

    message = describe_coverage_gap(
        coverage_start="1987-01-01",
        coverage_end="2021-12-31",
        start_date="1985-01-01",
        end_date="2022-06-01",
    )

    assert message is not None
    assert "begins" in message and "month(s) before" in message
    assert "extends" in message and "month(s) past" in message
    assert message.count("not counted in extent_pct") == 1
    assert message.index("not counted in extent_pct") > message.index("extends")


def test_on_warning_callback_receives_the_message(monkeypatch, tmp_path):
    import hydroseason.io as hio
    from hydroseason._historical_water_mask import HistoricalMaskCoverageWarning

    aoi = _aoi()
    mask = _historical_water_mask(aoi=aoi, coverage_end="2021-12-31")
    acquire = Mock(return_value=SimpleNamespace(path=tmp_path / "store.zarr"))
    monkeypatch.setattr(hio, "acquire_wofs_cache", acquire)
    monkeypatch.setattr(
        hio,
        "open_completed_extent_counts",
        lambda _handle, start, end, **_kwargs: _completed_extent(start, end),
    )

    received: list[str] = []

    with pytest.warns(HistoricalMaskCoverageWarning) as record:
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            aoi,
            "2020-01-01",
            "2022-01-01",
            resolution=30,
            mask_cache_dir=tmp_path,
            historical_water_mask=mask,
            on_warning=received.append,
        )

    assert len(received) == 1
    assert received[0] == str(record[0].message)


def test_offline_historical_mask_replay_never_calls_statistics_stac(monkeypatch, tmp_path):
    import hydroseason.io as hio

    mask = _historical_water_mask()
    resolve = Mock(return_value=mask)
    monkeypatch.setattr(hio, "load_or_build_historical_water_mask", resolve)
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=SimpleNamespace(path=tmp_path / "store.zarr")))
    monkeypatch.setattr(
        hio,
        "open_completed_extent_counts",
        lambda _handle, start, end, **_kwargs: _completed_extent(start, end),
    )
    monkeypatch.setattr(hio, "open_wo_statistics", Mock(side_effect=AssertionError("statistics STAC")))

    hio.load_wofs_monthly_extent(
        "https://example.invalid/monthly",
        "ga_ls_wo_3",
        _aoi(),
        "2020-01-01",
        "2020-12-31",
        resolution=30,
        mask_cache_dir=tmp_path / "wofs-cache",
        offline=True,
    )

    assert resolve.call_args.kwargs["offline"] is True
    assert resolve.call_args.kwargs["cache_root"] == tmp_path / "wofs-cache"


def test_offline_historical_mask_without_cache_root_never_calls_statistics_stac(monkeypatch):
    import hydroseason.io as hio
    from hydroseason._io_dea_stats import HistoricalWaterMaskUnavailable

    statistics = Mock(side_effect=AssertionError("statistics STAC"))
    monkeypatch.setattr(hio, "open_wo_statistics", statistics)

    with pytest.raises(
        HistoricalWaterMaskUnavailable, match="fixed multiyear water mask"
    ):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/monthly",
            "ga_ls_wo_3",
            _aoi(),
            "2020-01-01",
            "2020-12-31",
            resolution=30,
            offline=True,
        )

    statistics.assert_not_called()


def test_explicit_full_aoi_mode_preserves_legacy_loading_and_rejects_mask(monkeypatch):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.hydro_year import monthly_water_extent

    cube = _fake_monthly_cube("2020-01-01", "2020-12-01")
    load = Mock(return_value=cube)
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    actual = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2020-01-01", "2020-12-31", resolution=30,
        use_historical_water_mask=False,
    )

    pd.testing.assert_frame_equal(actual, monthly_water_extent(cube, time_block=12))
    with pytest.raises(ValueError, match="use_historical_water_mask=False"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2020-01-01", "2020-12-31", resolution=30,
            use_historical_water_mask=False,
            historical_water_mask=_historical_water_mask(),
        )


def test_offline_cache_hit_performs_zero_stac_calls(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio

    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    cube = _mixed_canonical_cube()
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=handle))
    monkeypatch.setattr(hio, "open_completed_mask_cache", Mock(return_value=cube))
    monkeypatch.setattr(hio, "_query_wofs_items", Mock(side_effect=AssertionError("network")), raising=False)

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2020-01-01", "2020-12-31", resolution=30,
        mask_cache_dir=tmp_path, offline=True, use_historical_water_mask=False,
    )

    assert len(result) == 12


def test_offline_cache_miss_is_explicit(tmp_path):
    import hydroseason.io as hio

    with pytest.raises(FileNotFoundError, match="offline WOfS cache miss"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2020-01-01", "2020-12-31", resolution=30,
            mask_cache_dir=tmp_path, offline=True, use_historical_water_mask=False,
        )


def test_offline_without_mask_cache_dir_is_explicit():
    import hydroseason.io as hio

    with pytest.raises(FileNotFoundError, match="offline WOfS cache miss"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2020-01-01", "2020-12-31", resolution=30, offline=True,
            use_historical_water_mask=False,
        )


def test_offline_without_mask_cache_dir_still_uses_complete_csv_cache(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    load = Mock(return_value=_fake_monthly_cube("2020-01-01", "2020-12-01"))
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-01-01",
        end_date="2020-12-31",
        resolution=30,
        cache_dir=tmp_path / "extent_cache",
        use_historical_water_mask=False,
    )
    expected = hio.load_wofs_monthly_extent(**kwargs)

    monkeypatch.setattr(
        hio,
        "acquire_wofs_cache",
        Mock(side_effect=AssertionError("canonical acquisition must not run")),
    )
    actual = hio.load_wofs_monthly_extent(**kwargs, offline=True)

    assert load.call_count == 1
    pd.testing.assert_frame_equal(actual, expected, check_freq=False, check_dtype=False)


def test_canonical_cache_extent_is_exactly_equal_to_legacy(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.hydro_year import monthly_water_extent

    cube = _mixed_canonical_cube()
    expected = monthly_water_extent(cube, time_block=3)
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=handle))
    monkeypatch.setattr(hio, "open_completed_mask_cache", Mock(return_value=cube))

    actual = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2020-01-01", "2020-12-31", resolution=30,
        mask_cache_dir=tmp_path, use_historical_water_mask=False,
    )

    pd.testing.assert_frame_equal(actual, expected)


def test_derived_wet_aoi_identity_reaches_extent_csv_cache(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason._io_extent_cache as extent_cache
    import hydroseason.io as hio

    cube = _mixed_canonical_cube()
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="grid-id", request_digest="request")
    wet_aoi = _fake_wet_aoi()
    wet_aoi.attrs["hydroseason_wet_aoi_identity"] = "derived-content-and-params"
    writes = []
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=handle))
    monkeypatch.setattr(hio, "open_completed_mask_cache", Mock(return_value=cube))
    monkeypatch.setattr(hio, "load_or_build_cached_wet_aoi", Mock(return_value=wet_aoi))
    monkeypatch.setattr(
        extent_cache,
        "_write_requested_annual_extent_parts",
        lambda frame, **kwargs: writes.append(kwargs),
    )

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac",
        "ga_ls_wo_3",
        _aoi(),
        "2020-01-01",
        "2020-12-31",
        resolution=30,
        cache_dir=tmp_path / "extent",
        mask_cache_dir=tmp_path / "masks",
        tile_pixels=512,
        precompute_wet_aoi=True,
        use_historical_water_mask=False,
    )

    assert writes[0]["wet_aoi_hash"] == "derived-content-and-params"


def test_cached_extent_reuses_completed_calendar_years(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    def fake_load(_url, _collection, _aoi, start, end, **kwargs):
        return _fake_monthly_cube(start, end)

    load = Mock(side_effect=fake_load)
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-11-01",
        end_date="2021-02-28",
        cache_dir=tmp_path / "cache",
        resolution=100,
        use_historical_water_mask=False,
    )
    first = load_wofs_monthly_extent(**kwargs)
    second = load_wofs_monthly_extent(**kwargs)
    forced = load_wofs_monthly_extent(**kwargs, force=True)

    assert load.call_count == 4
    assert list(first.index) == list(pd.date_range("2020-11-01", "2021-02-01", freq="MS"))
    pd.testing.assert_frame_equal(first, second, check_freq=False, check_dtype=False)
    pd.testing.assert_frame_equal(first, forced, check_freq=False)


def test_cached_extent_is_invalidated_when_resolution_changes(monkeypatch, tmp_path):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    load = Mock(side_effect=lambda _u, _c, _a, start, end, **kw: _fake_monthly_cube(start, end))
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    common = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
        use_historical_water_mask=False,
    )
    load_wofs_monthly_extent(**common, resolution=100)
    load_wofs_monthly_extent(**common, resolution=30)

    assert load.call_count == 2


def test_year_without_stac_items_becomes_unusable_months(monkeypatch):
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    def fake_load(_url, _collection, _aoi, start, end, **kwargs):
        if start.startswith("2020"):
            raise ValueError("No STAC items found for requested AOI and date range.")
        return _fake_monthly_cube(start, end)

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load)

    extent = load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", object(),
        "2020-01-01", "2021-12-31", resolution=100,
        use_historical_water_mask=False,
    )

    assert len(extent) == 24
    assert (extent.loc["2020", "n_valid"] == 0).all()
    assert extent.loc["2020", "extent_pct"].isna().all()
    assert (extent.loc["2021", "n_valid"] == 4).all()


def test_tile_extent_aggregation_sums_counts_then_recomputes_percentages():
    from hydroseason._io_extent_cache import _aggregate_extent_parts

    index = pd.DatetimeIndex(["2020-01-01"])
    left = pd.DataFrame({
        "n_water": [3], "n_aoi": [8], "n_valid": [6], "n_invalid": [2],
        "n_wet_aoi": [8], "extent_pct": [50.0], "invalid_pct": [25.0],
        "wet_fill_pct": [37.5],
    }, index=index)
    right = pd.DataFrame({
        "n_water": [1], "n_aoi": [2], "n_valid": [2], "n_invalid": [0],
        "n_wet_aoi": [2], "extent_pct": [50.0], "invalid_pct": [0.0],
        "wet_fill_pct": [50.0],
    }, index=index)

    result = _aggregate_extent_parts([left, right], index)

    assert result.loc[index[0], "n_water"] == 4
    assert result.loc[index[0], "n_valid"] == 8
    assert result.loc[index[0], "n_invalid"] == 2
    assert result.loc[index[0], "n_aoi"] == 10
    assert result.loc[index[0], "n_wet_aoi"] == 10
    assert result.loc[index[0], "extent_pct"] == 50.0
    assert result.loc[index[0], "invalid_pct"] == 20.0
    assert result.loc[index[0], "wet_fill_pct"] == 40.0
    assert result.loc[index[0], "n_aoi"] == (
        result.loc[index[0], "n_valid"] + result.loc[index[0], "n_invalid"]
    )


def test_tile_extent_aggregation_keeps_empty_month_percentages_nan():
    from hydroseason._io_extent_cache import _aggregate_extent_parts

    index = pd.DatetimeIndex(["2020-01-01"])
    result = _aggregate_extent_parts([], index)

    assert (result[["n_water", "n_aoi", "n_valid", "n_invalid", "n_wet_aoi"]] == 0).all().all()
    assert result[["extent_pct", "invalid_pct", "wet_fill_pct"]].isna().all().all()


def test_tiled_extent_resume_skips_completed_tiles(monkeypatch, tmp_path):
    import hydroseason.io as hio

    calls = []
    fail_once = {"value": True}

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        calls.append(set(skip_tile_ids))
        for tile_id in ["r0000_c0000", "r0000_c0001", "r0001_c0000"]:
            if tile_id in skip_tile_ids:
                continue
            if tile_id == "r0001_c0000" and fail_once["value"]:
                fail_once["value"] = False
                raise RuntimeError("interrupted")
            yield tile_id, _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        use_historical_water_mask=False,
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        hio.load_wofs_monthly_extent(**kwargs)
    result = hio.load_wofs_monthly_extent(**kwargs)

    assert calls[0] == set()
    assert calls[1] == {"r0000_c0000", "r0000_c0001"}
    assert (result["n_water"] == 12).all()


def test_tiled_extent_no_data_year_continues_to_next_year(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(_url, _collection, _aoi, start, _end, **kwargs):
        if start.startswith("2020"):
            raise ValueError("No STAC items found for requested AOI and date range.")
        yield "r0000_c0000", _fake_monthly_cube("2021-01-01", "2021-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac",
        "wofs",
        object(),
        "2020-01-01",
        "2021-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        use_historical_water_mask=False,
    )

    assert len(result) == 24
    assert (result.loc["2020", "n_valid"] == 0).all()
    assert result.loc["2020", "extent_pct"].isna().all()
    assert (result.loc["2021", "n_valid"] == 4).all()
    assert (result.loc["2021", "n_water"] == 4).all()


def test_tiled_extent_zero_tiles_yielded_raises_and_does_not_cache(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        return
        yield  # pragma: no cover - makes this a generator function that yields nothing

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    cache_dir = tmp_path / "cache"
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=cache_dir,
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        use_historical_water_mask=False,
    )

    with pytest.raises(ValueError, match="no tiles were produced"):
        hio.load_wofs_monthly_extent(**kwargs)

    assert not cache_dir.exists() or list(cache_dir.glob("*.csv")) == []


def test_tiled_extent_per_tile_value_error_propagates_uncached(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        # A tile whose reduced monthly index doesn't match the expected year
        # window -- this triggers the "unexpected monthly index" ValueError
        # inside the reduction loop, not from the generator/STAC query itself.
        yield "r0000_c0000", _fake_monthly_cube("2020-06-01", "2020-08-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    cache_dir = tmp_path / "cache"
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=cache_dir,
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        use_historical_water_mask=False,
    )

    with pytest.raises(ValueError, match="unexpected monthly index"):
        hio.load_wofs_monthly_extent(**kwargs)

    assert not cache_dir.exists() or list(cache_dir.glob("*.csv")) == []


def test_tiled_extent_force_ignores_annual_and_tile_caches(monkeypatch, tmp_path):
    import hydroseason.io as hio

    calls = []

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        calls.append(set(skip_tile_ids))
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        use_historical_water_mask=False,
    )

    hio.load_wofs_monthly_extent(**kwargs)
    hio.load_wofs_monthly_extent(**kwargs)
    hio.load_wofs_monthly_extent(**kwargs, force=True)

    assert len(calls) == 2
    assert calls[0] == set()
    assert calls[1] == set()


def test_cache_path_depends_on_wet_aoi_hash(tmp_path):
    from hydroseason._io_extent_cache import _cache_path

    common = dict(
        cache_dir=tmp_path, stac_url="s", collection="c", aoi_hash="a",
        start=pd.Timestamp("2020-01-01"), end=pd.Timestamp("2020-12-31"),
        crs=3577, resolution=30.0, majority=True,
    )
    p_none = _cache_path(**common, wet_aoi_hash="")
    p_wet = _cache_path(**common, wet_aoi_hash="deadbeef")
    assert p_none != p_wet  # wet AOI is data-affecting -> distinct cache file


def test_cache_path_wet_aoi_hash_defaults_to_empty(tmp_path):
    # Default (no wet_aoi_hash kwarg) must match explicitly passing "" so that
    # pre-Task-5 callers of _cache_path (no wet AOI involved) are unaffected.
    from hydroseason._io_extent_cache import _cache_path

    common = dict(
        cache_dir=tmp_path, stac_url="s", collection="c", aoi_hash="a",
        start=pd.Timestamp("2020-01-01"), end=pd.Timestamp("2020-12-31"),
        crs=3577, resolution=30.0, majority=True,
    )
    assert _cache_path(**common) == _cache_path(**common, wet_aoi_hash="")


def test_cache_path_depends_on_wet_mask(tmp_path):
    # A dea_stats-pruned run and an off (unpruned) run of the same AOI/dates/
    # params must not collide on the annual CSV cache key -- otherwise
    # whichever ran first "poisons" the cache for the other (the bug this
    # test exists to catch).
    from hydroseason._io_extent_cache import _cache_path

    common = dict(
        cache_dir=tmp_path, stac_url="s", collection="c", aoi_hash="a",
        start=pd.Timestamp("2020-01-01"), end=pd.Timestamp("2020-12-31"),
        crs=3577, resolution=30.0, majority=True,
    )
    p_off = _cache_path(**common, wet_mask="off")
    p_dea_stats = _cache_path(**common, wet_mask="dea_stats")
    assert p_off != p_dea_stats


def test_cache_path_wet_mask_default_matches_pre_fix_signature(tmp_path):
    # wet_mask="off" with no explicit wet_aoi (the default) must reproduce
    # the EXACT pre-fix cache key, so every already-written CSV cache file
    # on disk stays reachable. Prove it by construction: the identity dict's
    # serialized JSON must be byte-identical whether wet_mask is omitted,
    # passed explicitly as "off", or wet_aoi_hash is passed/omitted -- all
    # of these describe the pre-fix "no wet AOI in play" case.
    from hydroseason._io_extent_cache import _cache_path

    common = dict(
        cache_dir=tmp_path, stac_url="s", collection="c", aoi_hash="a",
        start=pd.Timestamp("2020-01-01"), end=pd.Timestamp("2020-12-31"),
        crs=3577, resolution=30.0, majority=True,
    )
    pre_fix_default = _cache_path(**common)
    assert _cache_path(**common, wet_mask="off") == pre_fix_default
    assert _cache_path(**common, wet_aoi_hash="", wet_mask="off") == pre_fix_default
    assert _cache_path(**common, wet_aoi_hash="") == pre_fix_default


def test_load_wofs_monthly_extent_does_not_share_csv_cache_across_wet_mask(monkeypatch, tmp_path):
    # End-to-end regression test for the live bug: two calls to
    # load_wofs_monthly_extent with identical AOI/dates but different
    # wet_mask values must not silently share a CSV cache entry. Uses the
    # untiled legacy path (no mask_cache_dir) via a mocked load_wofs_from_stac,
    # following the pattern in test_cached_extent_is_invalidated_when_resolution_changes.
    pytest.importorskip("dask")
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    load = Mock(side_effect=lambda _u, _c, _a, start, end, **kw: _fake_monthly_cube(start, end))
    monkeypatch.setattr(hio, "load_wofs_from_stac", load)

    common = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=aoi,
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
        resolution=100,
    )
    load_wofs_monthly_extent(**common, wet_mask="off", use_historical_water_mask=False)
    load_wofs_monthly_extent(**common, wet_mask="dea_stats", use_historical_water_mask=False)

    # If the two wet_mask values shared a cache key, the second call would
    # hit the first call's cached CSV and load_wofs_from_stac would only be
    # invoked once in total instead of once per wet_mask value.
    assert load.call_count == 2


def test_precompute_requires_tile_pixels(tmp_path):
    from hydroseason._io_extent_cache import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="precompute_wet_aoi requires tile_pixels"):
        load_wofs_monthly_extent(
            "https://example.invalid/stac", "wofs", aoi, "2020-01-01", "2020-12-31",
            cache_dir=tmp_path / "cache", resolution=30.0,
            precompute_wet_aoi=True,  # no tile_pixels -> error
            use_historical_water_mask=False,
        )


def test_precompute_wet_aoi_runs_full_ts_pass_and_threads_into_tiles(monkeypatch, tmp_path):
    import hydroseason.io as hio

    full_ts_calls = []
    compute_wet_aoi_calls = []
    tile_calls = []

    sentinel_wet_aoi = _fake_wet_aoi()

    def fake_load_full_ts(_url, _collection, _aoi, start, end, **kwargs):
        full_ts_calls.append((start, end))
        return _fake_monthly_cube(start, end)

    def fake_compute_wet_aoi(mask, **kwargs):
        compute_wet_aoi_calls.append(kwargs)
        return sentinel_wet_aoi

    def fake_tiles(*args, wet_aoi=None, skip_tile_ids=(), **kwargs):
        tile_calls.append(wet_aoi)
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load_full_ts)
    monkeypatch.setattr(hio, "compute_wet_aoi", fake_compute_wet_aoi)
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)

    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", object(),
        "2020-01-01", "2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        precompute_wet_aoi=True,
        persistence_min=0.25,
        close_m=100.0,
        buffer_m=200.0,
        use_historical_water_mask=False,
    )

    # One full-time-series pass over the whole requested window.
    assert full_ts_calls == [("2020-01-01", "2020-12-31")]
    # compute_wet_aoi received the precompute knobs.
    assert compute_wet_aoi_calls == [
        {"persistence_min": 0.25, "close_m": 100.0, "buffer_m": 200.0}
    ]
    # The computed wet AOI is threaded into the tiled per-year load.
    assert tile_calls == [sentinel_wet_aoi]
    assert (result["n_water"] == 4).all()
    assert "wet_fill_pct" in result.columns


def test_wet_aoi_passed_explicitly_skips_precompute_pass_but_does_not_prune_tiles(
    monkeypatch, tmp_path
):
    """An externally-supplied ``wet_aoi`` (no ``precompute_wet_aoi``) still
    skips the internal precompute pass (no redundant full-TS STAC call), but
    -- per Task 8's fix -- must NOT be threaded into
    ``iter_wofs_tiles_from_stac`` as a pruning gate, because there is no
    ``full_ts`` cube here to reconcile the tiled aggregate's denominator
    against if a tile were skipped. This replaces a prior version of this
    test that asserted ``tile_calls == [explicit_wet_aoi]`` -- that assertion
    was exercising exactly the denominator-shrinkage bug Task 8 fixes, not a
    correct contract worth preserving.

    ``n_wet_aoi``/``wet_fill_pct`` are a separate concern with no such
    problem (they only ever read pixels from tiles actually loaded), so the
    real ``wet_aoi`` must still reach ``monthly_water_extent`` for that
    calculation -- verified via ``monthly_water_extent_calls`` below.
    """
    import hydroseason._io_extent_cache as extent_cache
    import hydroseason.io as hio

    full_ts_calls = []
    tile_calls = []
    monthly_water_extent_calls = []
    explicit_wet_aoi = _fake_wet_aoi()

    def fake_load_full_ts(*args, **kwargs):
        full_ts_calls.append(args)
        raise AssertionError("full-TS pass must not run when wet_aoi is already given")

    def fake_tiles(*args, wet_aoi=None, skip_tile_ids=(), **kwargs):
        tile_calls.append(wet_aoi)
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    real_monthly_water_extent = extent_cache.monthly_water_extent

    def spying_monthly_water_extent(*args, **kwargs):
        monthly_water_extent_calls.append(kwargs.get("wet_aoi"))
        return real_monthly_water_extent(*args, **kwargs)

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load_full_ts)
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    monkeypatch.setattr(extent_cache, "monthly_water_extent", spying_monthly_water_extent)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", object(),
        "2020-01-01", "2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
        wet_aoi=explicit_wet_aoi,
        use_historical_water_mask=False,
    )

    assert full_ts_calls == []
    # Pruning gate: disabled (falls back to None) since there is no full_ts.
    assert tile_calls == [None]
    # n_wet_aoi/wet_fill_pct calculation: still uses the real, caller-supplied
    # wet_aoi, since that computation has no missing-tile denominator problem.
    assert monthly_water_extent_calls == [explicit_wet_aoi]


def test_untiled_path_threads_caller_supplied_wet_aoi_into_wet_fill_pct(monkeypatch, tmp_path):
    """Finding 2 regression: wet_aoi given without tile_pixels must still flow
    into monthly_water_extent on the untiled branch, so wet_fill_pct reflects
    the real wet AOI instead of silently falling back to n_valid/extent_pct.
    """
    pytest.importorskip("dask")
    xr = pytest.importorskip("xarray")
    pytest.importorskip("rasterio")
    pytest.importorskip("rioxarray")
    gpd = pytest.importorskip("geopandas")
    import rioxarray  # noqa: F401  (registers the .rio accessor)
    from shapely.geometry import box

    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    # 4x4 grid, one wet pixel; wet AOI covers only the top-left quadrant, so
    # n_wet_aoi (4) differs from n_valid (16) and wet_fill_pct != extent_pct.
    def fake_load(_url, _collection, _aoi, start, end, **kwargs):
        dates = pd.date_range(start, end, freq="MS")
        cube = np.zeros((len(dates), 4, 4), dtype=np.int8)
        cube[:, 0, 0] = 1
        masks = xr.DataArray(
            cube,
            dims=("time", "y", "x"),
            coords={
                "time": dates,
                "y": np.arange(4) * -30.0,
                "x": np.arange(4) * 30.0,
            },
        ).chunk({"time": 1, "y": 4, "x": 4})
        return masks.rio.write_crs("EPSG:3577")

    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load)

    wet_aoi = gpd.GeoDataFrame(
        {"geometry": [box(-15, -75, 45, 15)]}, geometry="geometry", crs="EPSG:3577"
    )

    result = load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-01-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        wet_aoi=wet_aoi,
        use_historical_water_mask=False,
    )

    row = result.loc[pd.Timestamp("2020-01-01")]
    assert row["n_valid"] == 16
    # The wet AOI covers only part of the grid, so n_wet_aoi must differ from
    # n_valid/n_aoi -- proving the untiled branch actually rasterised the
    # real, caller-supplied wet_aoi rather than silently aliasing n_wet_aoi
    # to n_valid (the pre-fix, no-wet-AOI fallback behaviour).
    assert 0 < row["n_wet_aoi"] < 16
    assert row["wet_fill_pct"] == pytest.approx(100.0 * row["n_water"] / row["n_wet_aoi"])
    assert row["extent_pct"] == pytest.approx(6.25)
    assert row["wet_fill_pct"] != row["extent_pct"]


def test_different_wet_aoi_produces_different_cache_file(monkeypatch, tmp_path):
    import hydroseason.io as hio

    def fake_tiles(*args, wet_aoi=None, skip_tile_ids=(), **kwargs):
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    cache_dir = tmp_path / "cache"
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=cache_dir,
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    hio.load_wofs_monthly_extent(**kwargs, wet_aoi=None, use_historical_water_mask=False)
    files_without_wet_aoi = set(cache_dir.glob("extent_*.csv"))

    hio.load_wofs_monthly_extent(**kwargs, wet_aoi=_fake_wet_aoi(), use_historical_water_mask=False)
    files_with_wet_aoi = set(cache_dir.glob("extent_*.csv")) - files_without_wet_aoi

    assert files_with_wet_aoi  # a new, distinct annual cache file was written


def _write_box_aoi(tmp_path, name, *, crs, span_m):
    """Write a square AOI GeoJSON `span_m` metres per side in the given CRS."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        {"geometry": [box(0, 0, span_m, span_m)]}, geometry="geometry", crs=crs
    )
    path = tmp_path / name
    gdf.to_file(path, driver="GeoJSON")
    return path


def test_auto_tiling_degrades_single_tile_aoi_to_untiled_path(monkeypatch, tmp_path):
    """An AOI smaller than one tile skips precompute and the tiled iterator,
    taking the plain untiled read instead (bit-identical, no double-read)."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    # 5 km AOI at 30 m with tile_pixels=2048 => one tile spans ~61 km >> 5 km.
    aoi = _write_box_aoi(tmp_path, "small.geojson", crs="EPSG:3577", span_m=5_000)

    untiled = Mock(side_effect=lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end))
    tiles = Mock(side_effect=lambda *a, **k: iter(()))
    monkeypatch.setattr(hio, "load_wofs_from_stac", untiled)
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", tiles)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
        use_historical_water_mask=False,
    )

    assert untiled.called  # took the untiled whole-AOI read
    assert not tiles.called  # never touched the tiled iterator


def test_auto_tiling_keeps_tiled_path_for_multi_tile_aoi(monkeypatch, tmp_path):
    """An AOI larger than one tile keeps the tiled+precompute path."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    # 200 km AOI at 30 m with tile_pixels=2048 => spans many ~61 km tiles.
    aoi = _write_box_aoi(tmp_path, "big.geojson", crs="EPSG:3577", span_m=200_000)

    monkeypatch.setattr(
        hio, "load_wofs_from_stac",
        lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end),
    )
    monkeypatch.setattr(hio, "compute_wet_aoi", lambda mask, **k: _fake_wet_aoi())
    tiles = Mock(side_effect=lambda *a, **k: iter(
        [("r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01"))]
    ))
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", tiles)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
        use_historical_water_mask=False,
    )

    assert tiles.called  # kept the tiled path for a genuinely multi-tile AOI


def test_auto_tiling_false_forces_tiled_path_even_for_small_aoi(monkeypatch, tmp_path):
    """auto_tiling=False keeps the requested tiled path regardless of AOI size."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    aoi = _write_box_aoi(tmp_path, "small2.geojson", crs="EPSG:3577", span_m=5_000)

    monkeypatch.setattr(
        hio, "load_wofs_from_stac",
        lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end),
    )
    monkeypatch.setattr(hio, "compute_wet_aoi", lambda mask, **k: _fake_wet_aoi())
    tiles = Mock(side_effect=lambda *a, **k: iter(
        [("r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01"))]
    ))
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", tiles)

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
        auto_tiling=False,
        use_historical_water_mask=False,
    )

    assert tiles.called  # opt-out respected: tiled path forced


def test_read_workers_threads_into_reduction_and_leaves_result_unchanged(monkeypatch, tmp_path):
    """read_workers reaches monthly_water_extent and does not alter output."""
    pytest.importorskip("dask")
    import hydroseason.hydro_year as hy
    import hydroseason.io as hio
    from hydroseason.io import load_wofs_monthly_extent

    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    monkeypatch.setattr(
        hio, "load_wofs_from_stac",
        lambda _u, _c, _a, start, end, **k: _fake_monthly_cube(start, end),
    )

    seen_workers = []
    real_reduce = hy.monthly_water_extent

    def spy_reduce(*args, read_workers=None, **kwargs):
        seen_workers.append(read_workers)
        return real_reduce(*args, read_workers=read_workers, **kwargs)

    # The cache module imported the name directly, so patch it there.
    monkeypatch.setattr("hydroseason._io_extent_cache.monthly_water_extent", spy_reduce)

    kwargs = dict(
        stac_url="https://example.invalid/stac", collection="wofs", aoi=aoi,
        start_date="2020-11-01", end_date="2021-02-28", resolution=100,
        use_historical_water_mask=False,
    )
    default_run = load_wofs_monthly_extent(**kwargs)
    tuned_run = load_wofs_monthly_extent(**kwargs, read_workers=8)

    # Default is None (profiling found forcing a worker count hurts this
    # workload -- see load_wofs_monthly_extent's read_workers docstring);
    # an explicit override still threads through when the caller opts in.
    assert None in seen_workers
    assert 8 in seen_workers
    # Concurrency is a scheduler detail only: identical numbers out.
    pd.testing.assert_frame_equal(default_run, tuned_run, check_freq=False)


def test_wet_aoi_disk_cache_sidecar_persistence(tmp_path):
    pytest.importorskip("geopandas")
    pytest.importorskip("shapely")
    import geopandas as gpd
    from shapely.geometry import box

    from hydroseason._io_extent_cache import _aoi_digest

    wet_gdf = gpd.GeoDataFrame({"geometry": [box(0, 0, 10, 10)]}, crs="EPSG:3577")
    digest = _aoi_digest(wet_gdf)

    sidecar_path = tmp_path / f"wet_aoi_{digest}.geojson"
    wet_gdf.to_file(sidecar_path, driver="GeoJSON")

    loaded_gdf = gpd.read_file(sidecar_path)
    assert len(loaded_gdf) == 1
    assert loaded_gdf.crs.to_epsg() == 3577


def test_historical_mask_failure_reports_endpoint_product_and_remedy(monkeypatch, tmp_path):
    """The multiyear mask is this run's spatial denominator, so its failure
    must stay fatal -- but the message must name the endpoint that failed,
    the product requested, the underlying error, and the argument that
    redirects it. A bare ProxyError traceback is undiagnosable in a
    notebook."""
    from hydroseason._io_dea_stats import (
        DEAStatsUnavailable,
        HistoricalWaterMaskUnavailable,
        WoStatisticsUnavailable,
    )
    from hydroseason._io_extent_cache import load_wofs_monthly_extent

    def explode(*args, **kwargs):
        raise WoStatisticsUnavailable(
            "DEA Water Observation Statistics STAC search failed for product "
            "'ga_ls_wo_fq_myear_3' at https://statistics.invalid/stac: "
            "APIError: ProxyError"
        )

    monkeypatch.setattr(
        "hydroseason._io_extent_cache._resolve_historical_water_mask", explode
    )

    with pytest.raises(HistoricalWaterMaskUnavailable) as excinfo:
        load_wofs_monthly_extent(
            "https://example.invalid/stac",
            "ga_ls_wo_3",
            _aoi(),
            "2020-01-01",
            "2020-12-01",
            cache_dir=tmp_path,
            statistics_stac_url="https://statistics.invalid/stac",
        )

    message = str(excinfo.value)
    assert "https://statistics.invalid/stac" in message
    assert "ga_ls_wo_fq_myear_3" in message
    assert "statistics_stac_url" in message
    assert "ProxyError" in message
    # Stays fatal, and stays catchable as the module's documented base type.
    assert isinstance(excinfo.value, DEAStatsUnavailable)

