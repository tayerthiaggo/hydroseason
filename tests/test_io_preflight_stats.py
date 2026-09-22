"""Tests for the preflight annual DEA Water Observation Statistics loader."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("rioxarray")
gpd = pytest.importorskip("geopandas")

import odc.stac  # noqa: E402
from shapely.geometry import box  # noqa: E402


def _aoi():
    return gpd.GeoDataFrame({"geometry": [box(0.0, -3000.0, 3000.0, 0.0)]}, crs="EPSG:3577")


class _FakeItem:
    def __init__(
        self,
        item_id: str,
        date: str,
        *,
        product: str = "ga_ls_wo_fq_cyear_3",
        processing_version: str | None = "3",
    ) -> None:
        self.id = item_id
        self.collection_id = product
        self.properties = {
            "datetime": date,
            "odc:product": product,
            "odc:processing_version": processing_version,
        }


def _annual_dataset(count_wet: int, *, count_clear: int = 10, time_len: int = 1):
    wet = np.full((time_len, 1, 1), count_wet, dtype=np.int16)
    clear = np.full((time_len, 1, 1), count_clear, dtype=np.int16)
    ds = xr.Dataset(
        {
            "count_wet": (("time", "y", "x"), wet),
            "count_clear": (("time", "y", "x"), clear),
        },
        coords={"time": np.arange(time_len), "y": [0.0], "x": [0.0]},
    )
    return ds.rio.write_crs("EPSG:3577").rio.write_transform()


def test_complete_years_never_use_partial_edges():
    from hydroseason._io_preflight_stats import resolve_complete_year_window

    window = resolve_complete_year_window("2005-03-14", "2010-10-02")

    assert window.complete_years == (2006, 2007, 2008, 2009)
    assert window.partial_start == ("2005-03-14", "2005-12-31")
    assert window.partial_end == ("2010-01-01", "2010-10-02")


def test_resolve_complete_year_window_can_return_no_complete_years():
    from hydroseason._io_preflight_stats import resolve_complete_year_window

    window = resolve_complete_year_window("2005-03-14", "2005-10-02")

    assert window.complete_years == ()
    assert window.partial_start == ("2005-03-14", "2005-12-31")
    assert window.partial_end is None


def test_complete_years_require_exact_timestamp_boundaries():
    from hydroseason._io_preflight_stats import resolve_complete_year_window

    window = resolve_complete_year_window(
        "2005-01-01T12:00:00",
        "2005-12-31T23:59:59",
    )

    assert window.complete_years == ()
    assert window.partial_start == ("2005-01-01T12:00:00", "2005-12-31")
    assert window.partial_end is None


def test_open_annual_wo_statistics_rejects_requests_without_a_complete_year():
    from hydroseason._io_preflight_stats import (
        AnnualStatisticsUnavailable,
        open_annual_wo_statistics,
    )

    with pytest.raises(AnnualStatisticsUnavailable, match="complete calendar year"):
        open_annual_wo_statistics(_aoi(), "2005-03-14", "2005-10-02")


def test_distinct_years_survive_spatial_tile_reduction(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [
        _FakeItem("tile-a-2005", "2005-12-31T00:00:00Z"),
        _FakeItem("tile-b-2005", "2005-12-31T00:00:00Z"),
        _FakeItem("tile-a-2006", "2006-12-31T00:00:00Z"),
    ]

    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr(
        "hydroseason._io_geo._query_wofs_items",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("monthly ga_ls_wo_3 acquisition must not be used")
        ),
    )

    def fake_load(loaded_items, **_kwargs):
        year = loaded_items[0].properties["datetime"][:4]
        return _annual_dataset(3 if year == "2005" else 7)

    monkeypatch.setattr("odc.stac.load", Mock(side_effect=fake_load))

    result = mod.open_annual_wo_statistics(
        _aoi(),
        "2005-01-01",
        "2006-12-31",
        chunks={"x": 2, "y": 2},
    )

    assert result.year.values.tolist() == [2005, 2006]
    assert result.count_wet.sel(year=2005).item() == 3
    assert result.count_wet.sel(year=2006).item() == 7
    assert result.attrs["provenance"]["missing_requested_years"] == []


def test_missing_requested_years_are_recorded_in_provenance(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [
        _FakeItem("tile-a-2005", "2005-12-31T00:00:00Z"),
        _FakeItem("tile-a-2007", "2007-12-31T00:00:00Z"),
    ]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(side_effect=lambda loaded_items, **_kwargs: _annual_dataset(5)))

    result = mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2007-12-31")

    assert result.year.values.tolist() == [2005, 2007]
    assert result.attrs["provenance"]["missing_requested_years"] == [2006]


def test_malformed_item_datetime_raises(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    bad_item = SimpleNamespace(id="bad-item", collection_id="ga_ls_wo_fq_cyear_3", properties={"datetime": "not-a-date"})
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: [bad_item])
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    with pytest.raises(mod.AnnualStatisticsUnavailable, match="datetime"):
        mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")


def test_missing_item_id_raises(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    bad_item = SimpleNamespace(
        id=None,
        collection_id="ga_ls_wo_fq_cyear_3",
        properties={"datetime": "2005-12-31T00:00:00Z"},
    )
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: [bad_item])
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    with pytest.raises(mod.AnnualStatisticsUnavailable, match="item id"):
        mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")


def test_ambiguous_year_summary_raises(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5, time_len=2)))

    with pytest.raises(mod.AnnualStatisticsUnavailable, match="ambiguous annual summary for 2005"):
        mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")


def test_stac_search_failure_is_wrapped(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    def explode(**_kwargs):
        raise RuntimeError("STAC unavailable")

    monkeypatch.setattr(mod, "_search_complete_year_items", explode)
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    with pytest.raises(mod.AnnualStatisticsUnavailable, match="STAC unavailable"):
        mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")


def test_wet_aoi_pruning_shrinks_the_load_extent(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    pruned_aoi = gpd.GeoDataFrame(
        {"geometry": [box(500.0, -1500.0, 1500.0, -500.0)]}, crs="EPSG:3577"
    )
    fake_fetch = Mock(return_value=pruned_aoi)
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", fake_fetch)

    result = mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")

    assert fake_fetch.call_count == 1
    _, kwargs = fake_fetch.call_args
    assert kwargs["years"] == [2005]

    load_kwargs = odc.stac.load.call_args.kwargs
    loaded_geometry = load_kwargs["geopolygon"]
    assert loaded_geometry.total_bounds.tolist() == pruned_aoi.total_bounds.tolist()

    pruning_provenance = result.attrs["provenance"]["wet_aoi_pruning"]
    assert pruning_provenance == {
        "requested": True,
        "applied": True,
        "fallback_reason": None,
        "min_frequency_fraction": None,
        "require_year_union": False,
    }


def test_wet_aoi_pruning_falls_back_to_full_aoi_on_failure(monkeypatch):
    import hydroseason._io_preflight_stats as mod
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    def explode(*_args, **_kwargs):
        raise DEAStatsUnavailable("no wet pixels found")

    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", explode)

    full_aoi = _aoi()
    result = mod.open_annual_wo_statistics(full_aoi, "2005-01-01", "2005-12-31")

    assert result.count_wet.sel(year=2005).item() == 5
    load_kwargs = odc.stac.load.call_args.kwargs
    loaded_geometry = load_kwargs["geopolygon"]
    assert loaded_geometry.total_bounds.tolist() == pytest.approx(
        full_aoi.to_crs("EPSG:3577").total_bounds.tolist()
    )

    pruning_provenance = result.attrs["provenance"]["wet_aoi_pruning"]
    assert pruning_provenance == {
        "requested": True,
        "applied": False,
        "fallback_reason": "no wet pixels found",
        "min_frequency_fraction": None,
        "require_year_union": False,
    }


def test_wet_aoi_pruning_falls_back_to_full_aoi_on_other_failures(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", explode)

    full_aoi = _aoi()
    result = mod.open_annual_wo_statistics(full_aoi, "2005-01-01", "2005-12-31")

    assert result.count_wet.sel(year=2005).item() == 5
    load_kwargs = odc.stac.load.call_args.kwargs
    loaded_geometry = load_kwargs["geopolygon"]
    assert loaded_geometry.total_bounds.tolist() == pytest.approx(
        full_aoi.to_crs("EPSG:3577").total_bounds.tolist()
    )

    pruning_provenance = result.attrs["provenance"]["wet_aoi_pruning"]
    assert pruning_provenance == {
        "requested": True,
        "applied": False,
        "fallback_reason": "boom",
        "min_frequency_fraction": None,
        "require_year_union": False,
    }


def test_invalid_frequency_fraction_propagates_as_value_error_not_fallback(monkeypatch):
    """A bad wet_aoi_min_frequency_fraction (operator error) must surface as
    a hard ValueError out of open_annual_wo_statistics itself, not be
    silently absorbed into the wet-AOI fallback-to-full-AOI path the way a
    genuine DEAStatsUnavailable (network/geometry/timeout) is.

    Deliberately does NOT mock fetch_dea_stats_wet_aoi: the real function
    must be the one raising, so this proves the ValueError actually escapes
    open_annual_wo_statistics's try/except around that call, rather than
    only proving fetch_dea_stats_wet_aoi raises in isolation.
    """
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(
        "odc.stac.load",
        Mock(side_effect=AssertionError("must not reach odc.stac.load after a bad parameter")),
    )

    with pytest.raises(ValueError, match="between 0 and 1"):
        mod.open_annual_wo_statistics(
            _aoi(),
            "2005-01-01",
            "2005-12-31",
            prune_to_wet_aoi=True,
            wet_aoi_min_frequency_fraction=10,
        )


def test_wet_aoi_pruning_can_be_disabled(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))
    fake_fetch = Mock(side_effect=AssertionError("must not be called when disabled"))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", fake_fetch)

    mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", prune_to_wet_aoi=False
    )

    assert fake_fetch.call_count == 0


def test_wet_aoi_frequency_threshold_is_forwarded(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    fake_fetch = Mock(return_value=_aoi())
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", fake_fetch)

    mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", wet_aoi_min_frequency_fraction=0.1
    )

    _, kwargs = fake_fetch.call_args
    assert kwargs["min_frequency_fraction"] == 0.1


def test_wet_aoi_frequency_threshold_recorded_in_provenance(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    result = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", wet_aoi_min_frequency_fraction=0.1
    )

    assert result.attrs["provenance"]["wet_aoi_pruning"]["min_frequency_fraction"] == 0.1


def test_wet_aoi_require_year_union_defaults_to_false(monkeypatch):
    """The preflight-facing default must be False (skip the per-year
    union) -- this is the new, deliberate default, opposite of the shared
    _io_dea_stats.py function's own default."""
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    fake_fetch = Mock(return_value=_aoi())
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", fake_fetch)

    mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")

    _, kwargs = fake_fetch.call_args
    assert kwargs["require_year_union"] is False


def test_wet_aoi_require_year_union_can_be_enabled(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    fake_fetch = Mock(return_value=_aoi())
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", fake_fetch)

    mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", wet_aoi_require_year_union=True
    )

    _, kwargs = fake_fetch.call_args
    assert kwargs["require_year_union"] is True


def test_wet_aoi_require_year_union_recorded_in_provenance(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    result = mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")

    assert result.attrs["provenance"]["wet_aoi_pruning"]["require_year_union"] is False


def test_cache_hit_reuses_cached_counts_without_reloading(monkeypatch, tmp_path):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    first_load = Mock(return_value=_annual_dataset(5))
    monkeypatch.setattr("odc.stac.load", first_load)
    first = mod.open_annual_wo_statistics(
        _aoi(),
        "2005-01-01",
        "2005-12-31",
        cache_dir=tmp_path,
    )
    assert first.count_wet.sel(year=2005).item() == 5
    assert first_load.call_count == 1

    monkeypatch.setattr(
        "odc.stac.load",
        Mock(side_effect=AssertionError("cache hit must not re-run odc.stac.load")),
    )
    second = mod.open_annual_wo_statistics(
        _aoi(),
        "2005-01-01",
        "2005-12-31",
        cache_dir=tmp_path,
    )

    assert second.count_wet.sel(year=2005).item() == 5


def test_write_band_streamed_preserves_values_dtype_and_shape(tmp_path):
    """Cache writing must not materialise the full multi-year cube at once.

    Large catchments blow the process memory budget if every year is pulled
    into a single float64 NumPy array before saving. Writing year-by-year
    into a pre-allocated on-disk array must round-trip identically.
    """
    dask_array = pytest.importorskip("dask.array")
    from hydroseason._io_preflight_stats import _write_band_streamed

    raw = np.arange(3 * 2 * 2, dtype=np.int16).reshape(3, 2, 2)
    band = xr.DataArray(
        dask_array.from_array(raw, chunks=(1, 1, 1)),
        dims=("year", "y", "x"),
        coords={"year": [2001, 2002, 2003], "y": [0.0, 1.0], "x": [0.0, 1.0]},
    )

    path = tmp_path / "band.npy"
    _write_band_streamed(path, band)

    written = np.load(path)
    np.testing.assert_array_equal(written, raw)
    assert written.dtype == raw.dtype
    assert written.shape == raw.shape


def test_write_band_streamed_rejects_year_not_leading_dim(tmp_path):
    from hydroseason._io_preflight_stats import _write_band_streamed

    band = xr.DataArray(
        np.zeros((2, 3), dtype=np.int16),
        dims=("y", "year"),
        coords={"y": [0.0, 1.0], "year": [2001, 2002, 2003]},
    )

    with pytest.raises(ValueError, match="year"):
        _write_band_streamed(tmp_path / "band.npy", band)


def test_cache_rejects_changed_item_identity(monkeypatch, tmp_path):
    import hydroseason._io_preflight_stats as mod

    original_items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(original_items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))
    mod.open_annual_wo_statistics(
        _aoi(),
        "2005-01-01",
        "2005-12-31",
        cache_dir=tmp_path,
    )

    changed_items = [_FakeItem("tile-b-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(changed_items))
    changed_load = Mock(return_value=_annual_dataset(9))
    monkeypatch.setattr("odc.stac.load", changed_load)

    refreshed = mod.open_annual_wo_statistics(
        _aoi(),
        "2005-01-01",
        "2005-12-31",
        cache_dir=tmp_path,
    )

    assert changed_load.call_count == 1
    assert refreshed.count_wet.sel(year=2005).item() == 9
    assert refreshed.attrs["provenance"]["item_ids_by_year"] == {"2005": ["tile-b-2005"]}


def test_cache_verification_rejects_tampered_item_identity(monkeypatch, tmp_path):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    mod.open_annual_wo_statistics(
        _aoi(),
        "2005-01-01",
        "2005-12-31",
        cache_dir=tmp_path,
    )

    cache_root = tmp_path / "preflight-annual-statistics"
    manifest_path = next(cache_root.iterdir()) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cache_identity"]["item_ids_by_year"] = {"2005": [""]}
    manifest["provenance"]["item_ids_by_year"] = {"2005": [""]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="item identity"):
        mod.open_annual_wo_statistics(
            _aoi(),
            "2005-01-01",
            "2005-12-31",
            cache_dir=tmp_path,
        )


def test_provenance_includes_grid_and_metric_identity(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    result = mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")

    provenance = result.attrs["provenance"]
    assert provenance["crs"] == "EPSG:3577"
    assert provenance["resolution"] == 30.0
    assert provenance["pixel_area"] == pytest.approx(900.0)
    assert provenance["metric_implementation_version"] == "preflight_annual_statistics_v1"


def test_io_facade_exports_open_annual_wo_statistics():
    from hydroseason import io

    assert callable(io.open_annual_wo_statistics)


def test_open_annual_wo_statistics_materializes_by_default(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    fake_dataset = _annual_dataset(5)
    original_compute = type(fake_dataset).compute
    compute_calls = []

    def spying_compute(self, *args, **kwargs):
        compute_calls.append(True)
        return original_compute(self, *args, **kwargs)

    # xarray's Dataset uses __slots__ in this environment, so instance-level
    # monkeypatching of a method (monkeypatch.setattr(fake_dataset, ...))
    # raises "attribute is read-only" -- patch the class instead, which is
    # equivalent here since fake_dataset is the only Dataset instance
    # exercised by this test's odc.stac.load stub.
    monkeypatch.setattr(type(fake_dataset), "compute", spying_compute)
    monkeypatch.setattr("odc.stac.load", Mock(return_value=fake_dataset))

    result = mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31")

    assert compute_calls, ".compute() must be called when materialize is left at its default"
    assert result.count_wet.sel(year=2005).item() == 5


def test_open_annual_wo_statistics_materialize_false_skips_compute(monkeypatch):
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())

    fake_dataset = _annual_dataset(5)

    def exploding_compute(*_args, **_kwargs):
        raise AssertionError("materialize=False must not call .compute()")

    # See the class-level-patch note in the "materializes_by_default" test
    # above: xarray's Dataset uses __slots__ in this environment, so
    # instance-level monkeypatching of a method is rejected as read-only.
    monkeypatch.setattr(type(fake_dataset), "compute", exploding_compute)
    monkeypatch.setattr("odc.stac.load", Mock(return_value=fake_dataset))

    result = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", materialize=False
    )

    assert result.count_wet.sel(year=2005).item() == 5


def test_open_annual_wo_statistics_materialize_produces_identical_values(monkeypatch):
    """The whole point of this parameter is a performance change, not a
    behaviour change -- prove the two paths agree on actual values."""
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(7)))

    lazy_result = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", materialize=False
    )
    eager_result = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", materialize=True
    )

    assert lazy_result.count_wet.sel(year=2005).item() == eager_result.count_wet.sel(year=2005).item()


def test_open_annual_wo_statistics_materializes_cache_hit_too(monkeypatch, tmp_path):
    """The cache-hit path (_open_cached_dataset, memmap-backed) must also be
    materialized by default -- this is the path the pilot's profile replay
    actually exercises after the first catchment load."""
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    first = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", cache_dir=tmp_path
    )
    assert first.count_wet.sel(year=2005).item() == 5

    monkeypatch.setattr(
        "odc.stac.load", Mock(side_effect=AssertionError("cache hit must not re-fetch"))
    )
    second = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", cache_dir=tmp_path
    )

    # np.memmap is itself a subclass of np.ndarray with no .compute
    # attribute either way, so hasattr(..., "compute") cannot distinguish
    # "materialized" from "still memmap" here -- isinstance is the correct
    # check. Note np.asarray(memmap) returns a view sharing the same
    # underlying buffer, not a detached RAM copy (the memmap stays
    # disk-page-mapped); what this proves is that the array no longer
    # carries memmap's lazy/disk-paged *interface*, which is what matters
    # for correctness here -- not that the bytes were physically copied.
    assert not isinstance(second.count_wet.data, np.memmap), (
        "cache-hit dataset must be materialized (real, non-memmap NumPy "
        "array) when materialize=True (the default)"
    )
    assert second.attrs["provenance"] == first.attrs["provenance"]


def test_open_annual_wo_statistics_does_not_retain_a_frequency_fraction_band(
    monkeypatch, tmp_path
):
    """frequency_fraction was a derived variable nothing downstream reads --
    _preflight_candidate.py computes its own frequency locally from
    count_wet/count_clear and never touches dataset["frequency_fraction"].
    Materializing it cost 336MB of 672MB on a 21x2000x2000 grid (measured
    empirically). Confirm the returned Dataset no longer carries it, on both
    the fresh-fetch path and the cache-hit (_open_cached_dataset) path."""
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    fresh = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", cache_dir=tmp_path
    )

    assert "frequency_fraction" not in fresh.data_vars
    assert set(fresh.data_vars) == {"count_wet", "count_clear"}

    monkeypatch.setattr(
        "odc.stac.load",
        Mock(side_effect=AssertionError("cache hit must not re-run odc.stac.load")),
    )
    cache_hit = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", cache_dir=tmp_path
    )

    assert "frequency_fraction" not in cache_hit.data_vars
    assert set(cache_hit.data_vars) == {"count_wet", "count_clear"}


def test_open_annual_wo_statistics_materialize_false_preserves_cache_hit_memmap(
    monkeypatch, tmp_path
):
    """materialize=False must genuinely preserve the memmap on the cache-hit
    path too, not just the fresh-fetch path -- this is the path with the
    subtle semantics (np.asarray() is what converts it; .compute()/.load()
    silently no-op on memmap either way), so it needs its own proof."""
    import hydroseason._io_preflight_stats as mod

    items = [_FakeItem("tile-a-2005", "2005-12-31T00:00:00Z")]
    monkeypatch.setattr(mod, "_search_complete_year_items", lambda **_kwargs: list(items))
    monkeypatch.setattr(mod, "fetch_dea_stats_wet_aoi", lambda *_a, **_k: _aoi())
    monkeypatch.setattr("odc.stac.load", Mock(return_value=_annual_dataset(5)))

    mod.open_annual_wo_statistics(_aoi(), "2005-01-01", "2005-12-31", cache_dir=tmp_path)

    monkeypatch.setattr(
        "odc.stac.load", Mock(side_effect=AssertionError("cache hit must not re-fetch"))
    )
    cached = mod.open_annual_wo_statistics(
        _aoi(), "2005-01-01", "2005-12-31", cache_dir=tmp_path, materialize=False
    )

    assert isinstance(cached.count_wet.data, np.memmap)


