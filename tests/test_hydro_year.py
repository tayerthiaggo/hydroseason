import importlib
import sys

import numpy as np
import pandas as pd
import pytest


def _monthly_extent(start="2019-01-01", periods=36, value=50.0):
    index = pd.date_range(start, periods=periods, freq="MS")
    return pd.Series(value, index=index, name="extent_pct")


def test_csv_detection_imports_without_raster_dependencies(monkeypatch):
    for name in ("xarray", "dask", "rasterio", "geopandas"):
        monkeypatch.setitem(sys.modules, name, None)

    module = importlib.import_module("hydroseason.hydro_year")

    assert callable(module.detect_hydrological_years)
    assert callable(module.label_hydrological_months)


def test_duplicate_months_raise_by_default():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24)
    duplicate = pd.concat([extent, extent.iloc[[0]]]).sort_index()

    with pytest.raises(ValueError, match="duplicate"):
        detect_hydrological_years(duplicate)


def test_duplicate_months_raise_even_when_one_value_is_missing():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24)
    duplicate = pd.concat([extent, pd.Series([np.nan], index=[extent.index[0]])]).sort_index()

    with pytest.raises(ValueError, match="duplicate"):
        detect_hydrological_years(duplicate)


def test_warn_duplicate_policy_collapses_to_first_month_value():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24)
    duplicate = pd.concat([extent, pd.Series([99.0], index=[pd.Timestamp("2020-02-01")])]).sort_index()

    with pytest.warns(UserWarning, match="Duplicate"):
        result = detect_hydrological_years(duplicate, duplicate_month_policy="warn")

    assert isinstance(result, pd.DataFrame)


def test_missing_months_raise_by_default():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24).drop(pd.Timestamp("2019-06-01"))

    with pytest.raises(ValueError, match="missing"):
        detect_hydrological_years(extent)


def test_unsupported_season_window_geometry_fails_fast():
    from hydroseason.hydro_year import HydroYearConfig

    with pytest.raises(ValueError, match="supported"):
        HydroYearConfig(wet_start_month=4, wet_end_month=6)


def test_dry_window_cross_year_fails_fast():
    from hydroseason.hydro_year import HydroYearConfig

    with pytest.raises(ValueError, match="supported"):
        HydroYearConfig(dry_start_month=10, dry_end_month=3)


def test_dry_window_before_wet_end_fails_fast():
    from hydroseason.hydro_year import HydroYearConfig

    with pytest.raises(ValueError, match="supported"):
        HydroYearConfig(wet_start_month=11, wet_end_month=4, dry_start_month=3, dry_end_month=6)


def test_invalid_coverage_is_rejected_conservatively_by_default():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24).to_frame()
    extent["invalid_pct"] = 0.0
    extent.loc[pd.Timestamp("2019-06-01"), "invalid_pct"] = 100.0

    with pytest.raises(ValueError, match="invalid"):
        detect_hydrological_years(extent)


def test_invalid_coverage_can_be_explicitly_permitted():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24).to_frame()
    extent["invalid_pct"] = 100.0

    result = detect_hydrological_years(extent, max_invalid_pct=100.0)

    assert isinstance(result, pd.DataFrame)


def test_default_max_invalid_pct_permits_typical_wofs_cloud_noise():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24).to_frame()
    extent["invalid_pct"] = 5.0

    result = detect_hydrological_years(extent)

    assert isinstance(result, pd.DataFrame)
    assert not result.empty


def test_default_max_invalid_pct_still_rejects_above_twenty_percent():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=24).to_frame()
    extent["invalid_pct"] = 0.0
    extent.loc[pd.Timestamp("2019-06-01"), "invalid_pct"] = 20.1

    with pytest.raises(ValueError, match="invalid"):
        detect_hydrological_years(extent)


def test_flag_quality_policy_continues_with_high_invalid_observations():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(periods=36).to_frame()
    extent["invalid_pct"] = 0.0
    extent.loc[extent.index[6], "invalid_pct"] = 90.0

    result = detect_hydrological_years(
        extent,
        max_invalid_pct=10.0,
        quality_policy="flag",
    )

    assert not result.empty


def _seasonal_extent(n_years=3):
    index = pd.date_range("2018-01-01", periods=12 * n_years, freq="MS")
    month = index.month
    wet_amplitude = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
    return pd.Series(wet_amplitude, index=index, name="extent_pct")


def test_detect_hydrological_years_golden_path_peak_and_end_dry():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _seasonal_extent(n_years=3)

    result = detect_hydrological_years(extent)

    assert list(result["hy_year"]) == [2018, 2019, 2020]
    for _, row in result.iterrows():
        assert row["peak_month"].month == 2
        assert row["end_dry_month"].month == 8
        assert row["amplitude_pct"] > 0


def test_suggest_hydro_year_config_centres_windows_on_climatology():
    from hydroseason.hydro_year import HydroYearConfig, suggest_hydro_year_config

    extent = _seasonal_extent(n_years=3)

    cfg = suggest_hydro_year_config(extent)

    assert isinstance(cfg, HydroYearConfig)
    assert cfg.wet_start_month == 12
    assert cfg.wet_end_month == 4
    assert cfg.dry_start_month == 5
    assert cfg.dry_end_month == 11


def test_suggest_hydro_year_config_roundtrips_into_detection():
    from hydroseason.hydro_year import detect_hydrological_years, suggest_hydro_year_config

    extent = _seasonal_extent(n_years=3)
    cfg = suggest_hydro_year_config(extent)

    result = detect_hydrological_years(extent, config=cfg)

    assert list(result["hy_year"]) == [2018, 2019, 2020]
    for _, row in result.iterrows():
        assert row["peak_month"].month == 2
        assert row["amplitude_pct"] > 0


def test_suggest_hydro_year_config_accepts_overrides():
    from hydroseason.hydro_year import suggest_hydro_year_config

    extent = _seasonal_extent(n_years=3)

    cfg = suggest_hydro_year_config(extent, min_wet_months=5)

    assert cfg.min_wet_months == 5
    assert cfg.wet_start_month == 12 and cfg.wet_end_month == 4


def test_suggest_hydro_year_config_requires_full_year_coverage():
    from hydroseason.hydro_year import suggest_hydro_year_config

    extent = _monthly_extent(periods=6)

    with pytest.raises(ValueError, match="missing calendar months"):
        suggest_hydro_year_config(extent)


def test_label_hydrological_months_splits_wet_dry_and_edges():
    from hydroseason.hydro_year import detect_hydrological_years, label_hydrological_months

    extent = _seasonal_extent(n_years=3)
    hy_df = detect_hydrological_years(extent)

    labels = label_hydrological_months(extent.index, hy_df)

    first_year = hy_df.iloc[0]
    peak = pd.Timestamp(first_year["peak_month"])
    assert labels.loc[peak, "season"] == "Wet"
    assert labels.loc[peak + pd.DateOffset(months=1), "season"] == "Dry"
    assert labels["hy_year"].isna().sum() == 0

    last_year = hy_df.iloc[-1]
    after_last = labels.index > pd.Timestamp(last_year["hy_end"])
    if after_last.any():
        assert (labels.loc[after_last, "season"] == "Dry").all()
        assert (labels.loc[after_last, "hy_year"] == int(last_year["hy_year"])).all()


def test_month_nearest_midpoint_empty_dates_guard():
    from hydroseason.hydro_year import _month_nearest_midpoint

    result = _month_nearest_midpoint(pd.DatetimeIndex([]), pd.Timestamp("2020-02-01"), pd.Timestamp("2020-08-01"))

    assert result == pd.Timestamp("2020-08-01")


def test_monthly_water_extent_excludes_invalid_pixels_from_water_denominator():
    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    import xarray as xr

    from hydroseason.hydro_year import monthly_water_extent

    masks = xr.DataArray(
        np.array([[[1, -1], [0, -2]]], dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(["2020-01-01"])},
    ).chunk({"time": 1, "y": 1, "x": 1})

    summary = monthly_water_extent(masks)

    assert summary.loc[pd.Timestamp("2020-01-01"), "extent_pct"] == pytest.approx(50.0)
    assert summary.loc[pd.Timestamp("2020-01-01"), "invalid_pct"] == pytest.approx(100 / 3)


def test_monthly_water_extent_nan_pixels_are_invalid_not_dry():
    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    import xarray as xr

    from hydroseason.hydro_year import monthly_water_extent

    masks = xr.DataArray(
        np.full((1, 2, 2), np.nan, dtype=float),
        dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(["2020-01-01"])},
    ).chunk({"time": 1, "y": 1, "x": 1})

    summary = monthly_water_extent(masks)
    row = summary.loc[pd.Timestamp("2020-01-01")]

    assert row["n_invalid"] == 4
    assert row["invalid_pct"] == pytest.approx(100.0)
    assert not (row["extent_pct"] == 0.0 and row["invalid_pct"] == 0.0)


def test_monthly_water_extent_rejects_unknown_canonical_values():
    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    import xarray as xr

    from hydroseason.hydro_year import monthly_water_extent

    masks = xr.DataArray(
        np.full((1, 2, 2), 7, dtype=np.int16),
        dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(["2020-01-01"])},
    ).chunk({"time": 1, "y": 1, "x": 1})

    summary = monthly_water_extent(masks)
    row = summary.loc[pd.Timestamp("2020-01-01")]

    assert row["n_invalid"] == 4
    assert row["invalid_pct"] == pytest.approx(100.0)
    assert not (row["extent_pct"] == 0.0 and row["invalid_pct"] == 0.0)


def test_no_runtime_warning_on_fully_invalid_month(recwarn):
    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    import warnings
    import xarray as xr

    from hydroseason.hydro_year import monthly_water_extent

    masks = xr.DataArray(
        np.full((1, 2, 2), -1, dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(["2020-01-01"])},
    ).chunk({"time": 1, "y": 1, "x": 1})

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        monthly_water_extent(masks)


def test_completed_missing_month_is_rejected_not_dry():
    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    import xarray as xr

    from hydroseason.io import complete_monthly_axis
    from hydroseason.hydro_year import detect_hydrological_years, monthly_water_extent

    masks = xr.DataArray(
        np.array([[[1, 0]] * 2] * 2, dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(["2020-01-01", "2020-03-01"]), "y": [0, 1], "x": [0, 1]},
    ).chunk({"time": 1, "y": 1, "x": 1})

    completed = complete_monthly_axis(masks, "2020-01-01", "2020-03-01")
    summary = monthly_water_extent(completed)
    inserted = summary.loc[pd.Timestamp("2020-02-01")]

    assert inserted["invalid_pct"] == pytest.approx(100.0)
    assert np.isnan(inserted["extent_pct"])

    # NaN extent_pct + invalid_pct=100 on the inserted month is rejected by
    # invalid-coverage validation before it could be silently selected as a
    # dry-window candidate; either failure mode proves it can't leak in as dry.
    with pytest.raises(ValueError, match="invalid"):
        detect_hydrological_years(summary)


def test_leading_fully_invalid_month_is_rejected_not_silently_dropped():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(start="2019-11-01", periods=14).to_frame()
    extent["invalid_pct"] = 5.0
    extent.iloc[0, extent.columns.get_loc("extent_pct")] = np.nan
    extent.iloc[0, extent.columns.get_loc("invalid_pct")] = 100.0

    with pytest.raises(ValueError, match="invalid"):
        detect_hydrological_years(extent)


def test_trailing_fully_invalid_month_is_rejected_not_silently_dropped():
    from hydroseason.hydro_year import detect_hydrological_years

    extent = _monthly_extent(start="2019-01-01", periods=14).to_frame()
    extent["invalid_pct"] = 5.0
    extent.iloc[-1, extent.columns.get_loc("extent_pct")] = np.nan
    extent.iloc[-1, extent.columns.get_loc("invalid_pct")] = 100.0

    with pytest.raises(ValueError, match="invalid"):
        detect_hydrological_years(extent)


def test_wofs_cloud_flags_do_not_create_false_end_dry_boundary():
    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    import xarray as xr

    from hydroseason.hydro_year import detect_hydrological_years, monthly_water_extent

    n_years = 3
    index = pd.date_range("2018-01-01", periods=12 * n_years, freq="MS")
    month = index.month
    wet_amplitude = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
    grid = 10
    frames = []
    for pct in wet_amplitude:
        n_water = int(round(pct / 100.0 * grid * grid))
        flat = np.zeros(grid * grid, dtype=np.int8)
        flat[:n_water] = 1
        frames.append(flat.reshape(grid, grid))
    cube = np.stack(frames, axis=0)

    # Inject light cloud noise (10% of pixels -> invalid) into August months,
    # the expected end-dry boundary, well under the 20% rejection threshold.
    rng = np.random.default_rng(0)
    for i, date in enumerate(index):
        if date.month == 8:
            flat = cube[i].reshape(-1)
            cloud_idx = rng.choice(grid * grid, size=grid * grid // 10, replace=False)
            flat[cloud_idx] = -1

    masks = xr.DataArray(
        cube,
        dims=("time", "y", "x"),
        coords={"time": index},
    ).chunk({"time": 1, "y": grid, "x": grid})

    summary = monthly_water_extent(masks)
    assert (summary["invalid_pct"].dropna() <= 20.0).all()

    result = detect_hydrological_years(summary)

    assert list(result["hy_year"]) == [2018, 2019, 2020]
    for _, row in result.iterrows():
        assert row["peak_month"].month == 2
        assert row["end_dry_month"].month == 8
