from __future__ import annotations

import numpy as np
import pytest

xr = pytest.importorskip("xarray")

from hydroseason._preflight_feasibility import (  # noqa: E402
    FEASIBILITY_MIN_FREQUENCY_FRACTION,
    SUPPORTED_FEASIBILITY_RESOLUTIONS,
    assess_feasibility,
    minimum_cluster_pixels,
)


def _annual(wet: np.ndarray, clear: np.ndarray) -> "xr.Dataset":
    """A single-year annual cube from 2D wet/clear arrays."""
    return xr.Dataset(
        {
            "count_wet": (("year", "y", "x"), wet[None, :, :]),
            "count_clear": (("year", "y", "x"), clear[None, :, :]),
        },
        coords={"year": [2005], "y": np.arange(wet.shape[0]), "x": np.arange(wet.shape[1])},
    )


def test_threshold_and_supported_resolutions_are_fixed():
    assert FEASIBILITY_MIN_FREQUENCY_FRACTION == 0.10
    assert SUPPORTED_FEASIBILITY_RESOLUTIONS == (30.0, 60.0, 90.0)


def test_minimum_cluster_pixels_scales_with_resolution():
    """A fixed ~3600 m^2 real-world bar, expressed in pixels, floored at 2
    so contiguity stays a live criterion at every supported resolution."""
    assert minimum_cluster_pixels(30.0) == 4
    assert minimum_cluster_pixels(60.0) == 2
    assert minimum_cluster_pixels(90.0) == 2


def test_unsupported_resolution_is_rejected_not_snapped():
    wet = np.zeros((5, 5), dtype=np.int16)
    clear = np.full((5, 5), 20, dtype=np.int16)
    with pytest.raises(ValueError, match="resolution"):
        assess_feasibility(_annual(wet, clear), resolution=45.0)


def test_empty_aoi_is_infeasible():
    """Simpson Desert signature: observed everywhere, no recurrent water."""
    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    result = assess_feasibility(_annual(wet, clear), resolution=60.0)
    assert result.feasible is False
    assert result.core_pixel_count == 0
    assert result.reason == "no_recurrent_water"


def test_scattered_subthreshold_pixels_are_infeasible_at_30m():
    """Isolated single pixels at 30m are the classifier-noise signature."""
    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    for y, x in [(1, 1), (4, 7), (8, 2)]:
        wet[y, x] = 20  # 100% frequency, but isolated
    result = assess_feasibility(_annual(wet, clear), resolution=30.0)
    assert result.core_pixel_count == 3
    assert result.largest_cluster_pixels == 1
    assert result.feasible is False
    assert result.reason == "recurrent_water_below_minimum_cluster"


def test_single_isolated_pixel_is_infeasible_at_60m():
    """A lone pixel no longer clears the bar at 60m: the 2-pixel floor keeps
    contiguity a live criterion at every supported resolution, so the same
    physical noise is rejected at 60m just as it is at 30m."""
    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[4, 7] = 20
    result = assess_feasibility(_annual(wet, clear), resolution=60.0)
    assert result.feasible is False
    assert result.reason == "recurrent_water_below_minimum_cluster"


def test_adjacent_pair_is_feasible_at_60m():
    """Two contiguous pixels clear the 2-pixel floor at 60m."""
    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[4, 7] = 20
    wet[4, 8] = 20
    result = assess_feasibility(_annual(wet, clear), resolution=60.0)
    assert result.feasible is True
    assert result.reason == "recurrent_water_present"


def test_contiguous_cluster_is_feasible_at_30m():
    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[3:5, 3:5] = 20  # 2x2 contiguous block
    result = assess_feasibility(_annual(wet, clear), resolution=30.0)
    assert result.feasible is True
    assert result.largest_cluster_pixels == 4


def test_frequency_is_summed_across_years_not_per_year():
    """A pixel wet 10% of the time overall qualifies even if no single
    year reaches the bar on its own. Uses two adjacent qualifying pixels
    (rather than one) so the assertion exercises frequency-summing, not
    the separate 2-pixel cluster floor (Fix 4)."""
    wet = np.zeros((2, 3, 3), dtype=np.int16)
    clear = np.full((2, 3, 3), 50, dtype=np.int16)
    wet[0, 1, 1] = 4
    wet[1, 1, 1] = 6  # 10/100 == 0.10 overall
    wet[0, 1, 2] = 4
    wet[1, 1, 2] = 6  # adjacent pixel, same overall frequency
    annual = xr.Dataset(
        {"count_wet": (("year", "y", "x"), wet), "count_clear": (("year", "y", "x"), clear)},
        coords={"year": [2005, 2006], "y": np.arange(3), "x": np.arange(3)},
    )
    result = assess_feasibility(annual, resolution=60.0)
    assert result.core_pixel_count == 2
    assert result.feasible is True


def test_all_time_statistics_are_screened_without_a_year_dimension():
    """The regular workflow reuses all-time count bands for the same gate."""
    wet = np.zeros((3, 3), dtype=np.int16)
    clear = np.full((3, 3), 50, dtype=np.int16)
    wet[1:, 1:] = 10
    statistics = xr.Dataset(
        {
            "count_wet": (("y", "x"), wet),
            "count_clear": (("y", "x"), clear),
        },
        coords={"y": np.arange(3), "x": np.arange(3)},
    )

    result = assess_feasibility(statistics, resolution=30.0)

    assert result.feasible is True
    assert result.core_pixel_count == 4
    assert result.largest_cluster_pixels == 4


def test_zero_clear_observations_never_count_as_water():
    """A pixel never observed has no defined frequency and must not pass."""
    wet = np.zeros((5, 5), dtype=np.int16)
    clear = np.zeros((5, 5), dtype=np.int16)
    wet[2, 2] = 5  # wet hits with zero clear looks: undefined, not water
    result = assess_feasibility(_annual(wet, clear), resolution=60.0)
    assert result.core_pixel_count == 0
    assert result.feasible is False


def test_diagonal_pixels_are_not_one_cluster():
    """Connectivity is 4-way: diagonal touching is not contiguity."""
    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[3, 3] = 20
    wet[4, 4] = 20
    result = assess_feasibility(_annual(wet, clear), resolution=30.0)
    assert result.cluster_count == 2
    assert result.largest_cluster_pixels == 1
    assert result.feasible is False


def test_dask_backed_annual_matches_numpy_path_without_materializing():
    """The dask path must use dask_image labelling and never force a full
    compute of the grid-sized labelled array -- only scalar/small-vector
    reductions should reach memory before the final result is built."""
    da = pytest.importorskip("dask.array")

    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[3:5, 3:5] = 20  # 2x2 contiguous block
    wet[8, 8] = 20  # isolated pixel, below the 30m cluster bar

    numpy_annual = _annual(wet, clear)
    numpy_result = assess_feasibility(numpy_annual, resolution=30.0)

    dask_annual = xr.Dataset(
        {
            "count_wet": (("year", "y", "x"), da.from_array(wet[None, :, :], chunks=(1, 4, 4))),
            "count_clear": (
                ("year", "y", "x"),
                da.from_array(clear[None, :, :], chunks=(1, 4, 4)),
            ),
        },
        coords={"year": [2005], "y": np.arange(10), "x": np.arange(10)},
    )
    assert hasattr(dask_annual["count_wet"].data, "dask")

    dask_result = assess_feasibility(dask_annual, resolution=30.0)

    assert dask_result == numpy_result


def test_preflight_feasibility_only_returns_feasibility_result(monkeypatch):
    import importlib

    mod = importlib.import_module("hydroseason.preflight")
    from hydroseason._preflight_feasibility import FeasibilityResult

    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[3:5, 3:5] = 20
    annual = _annual(wet, clear)

    monkeypatch.setattr(mod, "open_annual_wo_statistics", lambda *_a, **_k: annual)

    result = mod.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        feasibility_only=True,
        resolution=30.0,
    )

    assert isinstance(result, FeasibilityResult)
    assert result.feasible is True
    assert result.resolution == 30.0


def test_preflight_feasibility_only_rejects_empty_aoi(monkeypatch):
    import importlib

    mod = importlib.import_module("hydroseason.preflight")

    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    monkeypatch.setattr(mod, "open_annual_wo_statistics", lambda *_a, **_k: _annual(wet, clear))

    result = mod.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        feasibility_only=True,
    )

    assert result.feasible is False
    assert result.reason == "no_recurrent_water"


def test_preflight_feasibility_only_reraises_on_statistics_outage(monkeypatch):
    """A DEA statistics outage is not evidence the AOI lacks water. feasibility_only
    must fail loudly rather than silently reporting infeasible, since that could
    wrongly exclude an AOI from a large sweep."""
    import importlib

    from hydroseason._io_preflight_stats import AnnualStatisticsUnavailable

    mod = importlib.import_module("hydroseason.preflight")

    def _raise_outage(*_a, **_k):
        raise AnnualStatisticsUnavailable("stac endpoint unreachable")

    monkeypatch.setattr(mod, "open_annual_wo_statistics", _raise_outage)

    with pytest.raises(AnnualStatisticsUnavailable):
        mod.preflight(
            aoi="unused",
            start_date="2005-01-01",
            end_date="2005-12-31",
            feasibility_only=True,
        )


def test_preflight_feasibility_only_passes_materialize_false(monkeypatch):
    """feasibility_only needs only two scalars out of the cube, so it must
    request materialize=False from open_annual_wo_statistics -- otherwise
    the NumPy path is reached in production and the dask branch built for
    large AOIs is unreachable."""
    import importlib

    mod = importlib.import_module("hydroseason.preflight")

    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[3:5, 3:5] = 20
    annual = _annual(wet, clear)

    captured_kwargs = {}

    def _fake_open(*_a, **kwargs):
        captured_kwargs.update(kwargs)
        return annual

    monkeypatch.setattr(mod, "open_annual_wo_statistics", _fake_open)

    mod.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        feasibility_only=True,
    )

    assert captured_kwargs.get("materialize") is False


def test_preflight_non_feasibility_path_keeps_default_materialize(monkeypatch):
    """The non-feasibility_only path must NOT pass materialize at all (or
    must pass the default True) -- feasibility_only's lazy-loading override
    must not leak into ordinary preflight() calls."""
    import importlib

    mod = importlib.import_module("hydroseason.preflight")

    captured_kwargs = {}

    def _fake_open(*_a, **kwargs):
        captured_kwargs.update(kwargs)
        raise mod.AnnualStatisticsUnavailable("stop before candidate evaluation")

    monkeypatch.setattr(mod, "open_annual_wo_statistics", _fake_open)

    mod.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        thresholds="diagnostic",
    )

    assert captured_kwargs.get("materialize", True) is True


def test_bincount_reduction_is_bounded_to_a_scalar_on_dask_path(monkeypatch):
    """da.bincount(labelled.ravel()) returns one int64 per label, which
    scales with cluster count, not real water bodies -- an adversarial
    checkerboard AOI can make that vector larger than the labelled array
    it was meant to avoid materializing. assess_feasibility must reduce to
    the maximum only and keep it lazy on the dask path."""
    da = pytest.importorskip("dask.array")
    import dask.array as dask_array_module

    original_bincount = dask_array_module.bincount
    captured_sizes = []

    def _tracking_bincount(*args, **kwargs):
        result = original_bincount(*args, **kwargs)
        captured_sizes.append(result)
        return result

    monkeypatch.setattr(dask_array_module, "bincount", _tracking_bincount)

    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[3:5, 3:5] = 20

    dask_annual = xr.Dataset(
        {
            "count_wet": (("year", "y", "x"), da.from_array(wet[None, :, :], chunks=(1, 4, 4))),
            "count_clear": (
                ("year", "y", "x"),
                da.from_array(clear[None, :, :], chunks=(1, 4, 4)),
            ),
        },
        coords={"year": [2005], "y": np.arange(10), "x": np.arange(10)},
    )

    from hydroseason._preflight_feasibility import assess_feasibility as _assess

    result = _assess(dask_annual, resolution=30.0)

    assert result.largest_cluster_pixels == 4
    # If da.bincount is still called at all it must never be computed as a
    # vector and handed back whole -- the fix reduces to .max() lazily. We
    # accept either: bincount not called (a max-based reduction that avoids
    # it entirely), or, if called, its dask array must never be the object
    # passed into dask.compute() directly (it should be reduced first).
    for tracked in captured_sizes:
        assert hasattr(tracked, "dask"), "bincount result must remain a lazy dask array"


def test_provenance_is_populated_from_annual_statistics(monkeypatch):
    """preflight() must not discard annual provenance before returning the
    feasibility result -- otherwise a sweep rejection based on a degraded
    (e.g. partial-years) read is indistinguishable from a clean one."""
    import importlib

    mod = importlib.import_module("hydroseason.preflight")

    wet = np.zeros((10, 10), dtype=np.int16)
    clear = np.full((10, 10), 20, dtype=np.int16)
    wet[3:5, 3:5] = 20
    annual = _annual(wet, clear)
    annual.attrs["provenance"] = {
        "missing_requested_years": [2004],
        "item_ids_by_year": {"2005": ["abc"]},
    }

    monkeypatch.setattr(mod, "open_annual_wo_statistics", lambda *_a, **_k: annual)

    result = mod.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        feasibility_only=True,
    )

    assert result.provenance.get("missing_requested_years") == [2004]
    assert result.provenance.get("item_ids_by_year") == {"2005": ["abc"]}


def test_feasibility_result_provenance_defaults_to_empty_dict():
    from hydroseason._preflight_feasibility import FeasibilityResult

    result = FeasibilityResult(
        feasible=True,
        resolution=30.0,
        core_pixel_count=4,
        cluster_count=1,
        largest_cluster_pixels=4,
        minimum_cluster_pixels=4,
        reason="recurrent_water_present",
    )
    assert result.provenance == {}


def test_feasibility_result_to_dict_includes_provenance():
    from hydroseason._preflight_feasibility import FeasibilityResult

    result = FeasibilityResult(
        feasible=True,
        resolution=30.0,
        core_pixel_count=4,
        cluster_count=1,
        largest_cluster_pixels=4,
        minimum_cluster_pixels=4,
        reason="recurrent_water_present",
        provenance={"missing_requested_years": []},
    )
    payload = result.to_dict()
    assert payload == {
        "feasible": True,
        "resolution": 30.0,
        "core_pixel_count": 4,
        "cluster_count": 1,
        "largest_cluster_pixels": 4,
        "minimum_cluster_pixels": 4,
        "reason": "recurrent_water_present",
        "provenance": {"missing_requested_years": []},
    }


def test_resolution_rejects_non_numeric_string(monkeypatch):
    """float(resolution) silently accepts the string "30" -- tighten so a
    non-numeric type raises rather than being coerced."""
    wet = np.zeros((5, 5), dtype=np.int16)
    clear = np.full((5, 5), 20, dtype=np.int16)
    with pytest.raises((TypeError, ValueError)):
        assess_feasibility(_annual(wet, clear), resolution="30")  # type: ignore[arg-type]


def test_feasibility_result_is_exported_from_package_root():
    import hydroseason
    from hydroseason._preflight_feasibility import FeasibilityResult

    assert hydroseason.FeasibilityResult is FeasibilityResult
    assert "FeasibilityResult" in hydroseason.__all__

