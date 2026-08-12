from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydroseason._aoi_context import AOIContext
from hydroseason.workflow import _in_notebook_kernel, run_hydroseason


def _seasonal_extent(years: int = 8) -> pd.DataFrame:
    dates = pd.date_range("2010-01-01", periods=12 * years, freq="MS")
    phase = 2 * np.pi * (dates.month - 2) / 12
    return pd.DataFrame(
        {
            "extent_pct": np.clip(35 + 25 * np.cos(phase), 0, 100),
            "invalid_pct": 0.0,
        },
        index=dates,
    )


def _rainfall_csv(path: Path, index: pd.DatetimeIndex) -> Path:
    phase = 2 * np.pi * (index.month - 1) / 12
    pd.DataFrame(
        {
            "date": index,
            "rainfall_mm": np.clip(100 + 80 * np.cos(phase), 0, None),
        }
    ).to_csv(path, index=False)
    return path


ANALYSIS_OPTIONS = {
    "phase_model": "rule_based",
    "n_bootstrap": 40,
    "random_state": 7,
}


def test_water_only_workflow_writes_bundle(tmp_path):
    result = run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        aoi_name="Test AOI",
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert result.rainfall_status == "disabled"
    assert result.rainfall_source == "none"
    assert result.rainfall is None
    assert result.rainfall_comparison is None
    assert result.aoi_context is None
    assert result.artifacts.html.exists()
    monthly = pd.read_csv(result.artifacts.monthly_csv)
    assert "rainfall_mm" not in monthly


def test_supplied_csv_takes_precedence_and_enriches_monthly_csv(
    monkeypatch, tmp_path
):
    extent = _seasonal_extent()
    rain_path = _rainfall_csv(tmp_path / "rain.csv", extent.index)

    def forbid_fetch(*args, **kwargs):
        raise AssertionError("SILO must not run when rainfall_csv_path is supplied")

    monkeypatch.setattr("hydroseason.workflow.get_monthly_silo_rainfall", forbid_fetch)
    result = run_hydroseason(
        extent,
        output_dir=tmp_path / "report",
        rainfall_csv_path=rain_path,
        fetch_rainfall=True,
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert result.rainfall_status == "provided"
    assert result.rainfall_source == "csv"
    assert result.rainfall_comparison.extent is result.analysis.regime
    monthly = pd.read_csv(result.artifacts.monthly_csv)
    assert {"rainfall_mm", "rain_anomaly_mm"} <= set(monthly.columns)
    for path in (
        result.artifacts.hydro_years_csv,
        result.artifacts.wet_event_csv,
        result.artifacts.low_spells_csv,
    ):
        assert "rainfall_mm" not in pd.read_csv(path).columns
    assert not list((tmp_path / "report").glob("*rainfall*.csv"))


def test_fetch_rainfall_uses_extent_years_and_loaded_aoi(monkeypatch, tmp_path):
    extent = _seasonal_extent()
    sentinel_aoi = object()
    calls = {}
    loaded = []

    def fake_load(value):
        loaded.append(value)
        return sentinel_aoi

    monkeypatch.setattr("hydroseason.workflow.load_aoi", fake_load)

    def fake_silo(gdf, start_year, end_year):
        calls.update(gdf=gdf, start_year=start_year, end_year=end_year)
        return pd.DataFrame(
            {"date": extent.index, "rainfall_mm": np.linspace(1, 100, len(extent))}
        )

    monkeypatch.setattr("hydroseason.workflow.get_monthly_silo_rainfall", fake_silo)
    result = run_hydroseason(
        extent,
        output_dir=tmp_path,
        aoi="aoi.geojson",
        fetch_rainfall=True,
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert result.rainfall_status == "fetched"
    assert result.rainfall_source == "silo"
    assert calls == {"gdf": sentinel_aoi, "start_year": 2010, "end_year": 2017}
    assert loaded == ["aoi.geojson"]
    assert "Rainfall context (SILO)" in result.artifacts.html.read_text(encoding="utf-8")


def test_aoi_load_preview_precedes_acquisition_and_context_is_reused(
    monkeypatch, tmp_path
):
    """Loading twice or acquiring before the preview would break the single-AOI flow."""
    from hydroseason._workflow_input import ResolvedWaterInput

    events = []
    loaded_aoi = object()
    context = AOIContext("{}", (115.0, -32.0, 116.0, -31.0), "AOI", 0)
    captured = {}
    monkeypatch.setattr(
        "hydroseason.workflow.load_aoi",
        lambda value: events.append("load") or loaded_aoi,
    )
    monkeypatch.setattr(
        "hydroseason.workflow.build_aoi_context",
        lambda value, **kwargs: events.append("context") or context,
    )
    monkeypatch.setattr(
        "hydroseason.workflow.display_aoi_map",
        lambda value: events.append("display"),
    )

    def fake_resolve(water_source, **kwargs):
        assert kwargs["aoi"] is loaded_aoi
        events.append("acquire")
        return ResolvedWaterInput(_seasonal_extent(), "extent_dataframe")

    monkeypatch.setattr("hydroseason.workflow.resolve_water_input", fake_resolve)

    def fake_report(*args, **kwargs):
        captured["context"] = kwargs["aoi_context"]
        events.append("report")
        return _report_paths(tmp_path)

    monkeypatch.setattr("hydroseason.workflow.generate_catchment_report", fake_report)
    result = run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        aoi="aoi.geojson",
        show_map=True,
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert events == ["load", "context", "display", "acquire", "report"]
    assert result.aoi_context is context
    assert captured["context"] is context


@pytest.mark.parametrize(
    ("show_map", "in_notebook", "expected_displays"),
    [(False, True, 0), (True, False, 1), ("auto", False, 0), ("auto", True, 1)],
)
def test_show_map_modes_control_preview(
    monkeypatch, tmp_path, show_map, in_notebook, expected_displays
):
    displays = []
    context = AOIContext("{}", (115.0, -32.0, 116.0, -31.0), "AOI", 0)
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())
    monkeypatch.setattr("hydroseason.workflow.build_aoi_context", lambda value, **kwargs: context)
    monkeypatch.setattr("hydroseason.workflow._in_notebook_kernel", lambda: in_notebook)
    monkeypatch.setattr("hydroseason.workflow.display_aoi_map", lambda value: displays.append(value))

    run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        aoi="aoi.geojson",
        show_map=show_map,
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert displays == [context] * expected_displays


def test_show_map_rejects_invalid_values(tmp_path):
    with pytest.raises(ValueError, match="show_map must be 'auto', True, or False\\."):
        run_hydroseason(
            _seasonal_extent(), output_dir=tmp_path, show_map="yes"
        )


def test_context_and_display_failures_warn_without_blocking_a_run(monkeypatch, tmp_path):
    """AOI display helpers are optional even though loading the supplied AOI is not."""
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())
    monkeypatch.setattr(
        "hydroseason.workflow.build_aoi_context",
        lambda value, **kwargs: (_ for _ in ()).throw(RuntimeError("bad context")),
    )
    with pytest.warns(UserWarning, match="bad context"):
        result = run_hydroseason(
            _seasonal_extent(), output_dir=tmp_path, aoi="aoi.geojson"
        )
    assert result.aoi_context is None

    context = AOIContext("{}", (115.0, -32.0, 116.0, -31.0), "AOI", 0)
    monkeypatch.setattr("hydroseason.workflow.build_aoi_context", lambda value, **kwargs: context)
    monkeypatch.setattr(
        "hydroseason.workflow.display_aoi_map",
        lambda value: (_ for _ in ()).throw(RuntimeError("display unavailable")),
    )
    with pytest.warns(UserWarning, match="display unavailable"):
        result = run_hydroseason(
            _seasonal_extent(), output_dir=tmp_path / "display", aoi="aoi.geojson", show_map=True
        )
    assert result.aoi_context is context


def test_supplied_unloadable_aoi_is_fatal_for_precomputed_water(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "hydroseason.workflow.load_aoi",
        lambda value: (_ for _ in ()).throw(ValueError("invalid AOI")),
    )
    with pytest.raises(ValueError, match="invalid AOI"):
        run_hydroseason(
            _seasonal_extent(), output_dir=tmp_path, aoi="broken.geojson"
        )


def test_in_notebook_kernel_requires_the_zmq_shell(monkeypatch):
    import sys
    from types import SimpleNamespace

    zmq = type("ZMQInteractiveShell", (), {})()
    terminal = type("TerminalInteractiveShell", (), {})()
    monkeypatch.setitem(sys.modules, "IPython", SimpleNamespace(get_ipython=lambda: zmq))
    assert _in_notebook_kernel() is True
    monkeypatch.setitem(sys.modules, "IPython", SimpleNamespace(get_ipython=lambda: terminal))
    assert _in_notebook_kernel() is False
    monkeypatch.setitem(sys.modules, "IPython", SimpleNamespace(get_ipython=lambda: None))
    assert _in_notebook_kernel() is False


def _report_paths(tmp_path):
    from hydroseason.report import CatchmentReportPaths

    return CatchmentReportPaths(
        html=tmp_path / "report.html",
        monthly_csv=tmp_path / "monthly.csv",
        hydro_years_csv=tmp_path / "years.csv",
        wet_event_csv=tmp_path / "events.csv",
        low_spells_csv=tmp_path / "spells.csv",
    )


def test_silo_failure_is_nonfatal_and_writes_water_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())

    def fail_silo(*args, **kwargs):
        raise OSError("SILO unavailable")

    monkeypatch.setattr("hydroseason.workflow.get_monthly_silo_rainfall", fail_silo)
    with pytest.warns(UserWarning, match="SILO unavailable"):
        result = run_hydroseason(
            _seasonal_extent(),
            output_dir=tmp_path,
            aoi="aoi.geojson",
            fetch_rainfall=True,
            analysis_options=ANALYSIS_OPTIONS,
        )

    assert result.rainfall_status == "fetch_failed"
    assert result.rainfall_error == "SILO unavailable"
    assert result.artifacts.html.exists()
    assert "rainfall_mm" not in pd.read_csv(result.artifacts.monthly_csv)
    failure_html = result.artifacts.html.read_text(encoding="utf-8")
    assert "Ancillary SILO rainfall unavailable" in failure_html
    assert 'id="rainfall-context-figure"' not in failure_html


def test_missing_aoi_is_a_nonfatal_fetch_failure(tmp_path):
    with pytest.warns(UserWarning, match="requires aoi"):
        result = run_hydroseason(
            _seasonal_extent(),
            output_dir=tmp_path,
            fetch_rainfall=True,
            analysis_options=ANALYSIS_OPTIONS,
        )

    assert result.rainfall_status == "fetch_failed"
    assert result.rainfall_source == "silo"
    assert result.rainfall is None
    assert result.artifacts.html.exists()


def test_malformed_supplied_rainfall_is_nonfatal(tmp_path):
    rain_path = tmp_path / "rain.csv"
    pd.DataFrame({"date": ["2020-01-01"], "rain": [10.0]}).to_csv(
        rain_path, index=False
    )

    with pytest.warns(UserWarning, match="rainfall CSV"):
        result = run_hydroseason(
            _seasonal_extent(),
            output_dir=tmp_path / "report",
            rainfall_csv_path=rain_path,
            analysis_options=ANALYSIS_OPTIONS,
        )

    assert result.rainfall_status == "provided_failed"
    assert result.rainfall_source == "csv"
    assert result.rainfall is None
    assert result.rainfall_error is not None
    assert result.artifacts.html.exists()
    provided_failure_html = result.artifacts.html.read_text(encoding="utf-8")
    assert "Ancillary rainfall CSV unavailable" in provided_failure_html
    assert 'id="rainfall-context-figure"' not in provided_failure_html


def test_disjoint_supplied_rainfall_is_a_nonfatal_provided_failure(tmp_path):
    extent = _seasonal_extent()
    disjoint_index = pd.date_range("1990-01-01", periods=12, freq="MS")
    rain_path = _rainfall_csv(tmp_path / "rain.csv", disjoint_index)

    with pytest.warns(UserWarning, match="no months overlapping"):
        result = run_hydroseason(
            extent,
            output_dir=tmp_path / "report",
            rainfall_csv_path=rain_path,
            analysis_options=ANALYSIS_OPTIONS,
        )

    assert result.rainfall_status == "provided_failed"
    assert result.rainfall is None
    assert result.rainfall_comparison is None
    monthly = pd.read_csv(result.artifacts.monthly_csv)
    assert "rainfall_mm" not in monthly.columns


def test_disjoint_fetched_rainfall_is_a_nonfatal_fetch_failure(monkeypatch, tmp_path):
    extent = _seasonal_extent()
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())

    def fake_silo(gdf, start_year, end_year):
        disjoint_index = pd.date_range("1990-01-01", periods=12, freq="MS")
        return pd.DataFrame(
            {
                "date": disjoint_index,
                "rainfall_mm": np.linspace(1, 100, len(disjoint_index)),
            }
        )

    monkeypatch.setattr("hydroseason.workflow.get_monthly_silo_rainfall", fake_silo)

    with pytest.warns(UserWarning, match="no months overlapping"):
        result = run_hydroseason(
            extent,
            output_dir=tmp_path,
            aoi="aoi.geojson",
            fetch_rainfall=True,
            analysis_options=ANALYSIS_OPTIONS,
        )

    assert result.rainfall_status == "fetch_failed"
    assert result.rainfall is None
    assert result.rainfall_comparison is None
    monthly = pd.read_csv(result.artifacts.monthly_csv)
    assert "rainfall_mm" not in monthly.columns


def test_comparison_failure_retains_loaded_rainfall(monkeypatch, tmp_path):
    extent = _seasonal_extent()
    rain_path = _rainfall_csv(tmp_path / "rain.csv", extent.index)

    def fail_comparison(*args, **kwargs):
        raise RuntimeError("comparison unavailable")

    monkeypatch.setattr(
        "hydroseason.workflow.compare_rainfall_to_extent_regime", fail_comparison
    )
    with pytest.warns(UserWarning, match="comparison unavailable"):
        result = run_hydroseason(
            extent,
            output_dir=tmp_path / "report",
            rainfall_csv_path=rain_path,
            analysis_options=ANALYSIS_OPTIONS,
        )

    assert result.rainfall_status == "provided"
    assert result.rainfall is not None
    assert result.rainfall_comparison is None
    assert result.rainfall_comparison_error == "comparison unavailable"
    assert "rainfall_mm" in pd.read_csv(result.artifacts.monthly_csv)
    comparison_html = result.artifacts.html.read_text(encoding="utf-8")
    assert "Rainfall context (supplied CSV)" in comparison_html
    assert "comparison unavailable" in comparison_html


def test_rainfall_never_changes_water_analysis(tmp_path):
    extent = _seasonal_extent()
    rain_path = _rainfall_csv(tmp_path / "rain.csv", extent.index)
    without = run_hydroseason(
        extent,
        output_dir=tmp_path / "without",
        analysis_options=ANALYSIS_OPTIONS,
    )
    with_rain = run_hydroseason(
        extent,
        output_dir=tmp_path / "with",
        rainfall_csv_path=rain_path,
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert without.analysis.regime == with_rain.analysis.regime
    assert without.analysis.route == with_rain.analysis.route
    assert without.analysis.route_reason == with_rain.analysis.route_reason
    pd.testing.assert_frame_equal(
        without.analysis.hydro_years, with_rain.analysis.hydro_years
    )
    pd.testing.assert_frame_equal(
        without.analysis.events.events, with_rain.analysis.events.events
    )
    pd.testing.assert_frame_equal(
        without.analysis.events.low_spells, with_rain.analysis.events.low_spells
    )
    pd.testing.assert_series_equal(
        pd.Series(without.analysis.events.summary),
        pd.Series(with_rain.analysis.events.summary),
        check_names=False,
    )
    pd.testing.assert_frame_equal(
        without.analysis.monthly, with_rain.analysis.monthly
    )
    assert (without.analysis.state is None) == (with_rain.analysis.state is None)
    if without.analysis.state is not None:
        pd.testing.assert_frame_equal(
            without.analysis.state.monthly_phase,
            with_rain.analysis.state.monthly_phase,
        )


def test_run_hydroseason_propagates_one_stac_url_through_the_full_input_seam(
    monkeypatch, tmp_path
):
    """Exercise run_hydroseason -> resolve_water_input -> DEA loader without
    replacing the middle seam. This is the regression boundary requested by
    the diagnosis handoff."""
    calls = {}

    def fake_loader(
        stac_url, collection, aoi, start_date, end_date, *,
        cache_dir, statistics_stac_url, progress, progress_desc, on_warning,
    ):
        calls.update(stac_url=stac_url, statistics_stac_url=statistics_stac_url)
        return _seasonal_extent()

    monkeypatch.setattr(
        "hydroseason._workflow_input.load_wofs_monthly_extent", fake_loader
    )
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())
    run_hydroseason(
        None,
        output_dir=tmp_path,
        aoi="aoi.geojson",
        start_date="2010-01-01",
        end_date="2017-12-01",
        stac_url="https://example.test/stac",
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert calls["stac_url"] == "https://example.test/stac"
    assert calls["statistics_stac_url"] == "https://example.test/stac"


def _fake_wo_statistics_dataset(*, time_span: str, size: int = 4, resolution: float = 30.0):
    """A minimal, real ``xr.Dataset`` shaped like ``open_wo_statistics``'s
    return value: a ``count_wet``/``count_clear`` pair plus the
    ``provenance`` attrs block ``build_historical_water_mask`` reads for
    product/lineage/coverage. One cell is wet so the built mask is
    non-empty. Mirrors ``_refresh_stats_dataset`` in
    tests/test_io_extent_cache.py (kept local here rather than imported,
    per that module's own convention of small per-test fixture builders).
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("rioxarray")
    da = pytest.importorskip("dask.array")
    import rioxarray  # noqa: F401  (registers the .rio accessor)

    from hydroseason._historical_water_mask import HISTORICAL_MASK_SOURCE_PRODUCT

    grid = np.zeros((size, size), dtype=np.int32)
    grid[0, 0] = 1
    count_wet = xr.DataArray(
        da.from_array(grid, chunks=(size, size)), dims=("y", "x"),
        coords={
            "y": np.arange(size) * -resolution,
            "x": np.arange(size) * resolution,
        },
    )
    count_clear = xr.full_like(count_wet, 10)
    dataset = xr.Dataset({"count_wet": count_wet, "count_clear": count_clear})
    dataset = dataset.rio.write_crs("EPSG:3577").rio.write_transform()
    dataset.attrs["provenance"] = {
        "product": HISTORICAL_MASK_SOURCE_PRODUCT,
        "stac_url": "https://example.test/stac",
        "item_ids": ["stats-item"],
        "crs": "EPSG:3577",
        "resolution": resolution,
        "time_span": time_span,
        "frequency": {
            "derivation": "100 * count_wet / count_clear",
            "count_wet": "count_wet",
            "count_clear": "count_clear",
        },
    }
    return dataset


def _fake_monthly_wofs_cube(start: str, end: str, *, size: int = 4, resolution: float = 30.0):
    """A real, georeferenced monthly cube on the SAME grid
    ``_fake_wo_statistics_dataset`` builds its mask on -- required by
    ``_clip_to_aoi``'s exact-grid check (``_assert_historical_mask_grid_matches``).
    """
    xr = pytest.importorskip("xarray")
    pytest.importorskip("rioxarray")
    from affine import Affine

    dates = pd.date_range(start, end, freq="MS")
    values = np.ones((len(dates), size, size), dtype=np.int8)
    cube = xr.DataArray(
        values, dims=("time", "y", "x"),
        coords={
            "time": dates,
            "y": np.arange(size) * -resolution,
            "x": np.arange(size) * resolution,
        },
    )
    return (
        cube.rio.set_spatial_dims(x_dim="x", y_dim="y")
        .rio.write_crs("EPSG:3577")
        .rio.write_transform(Affine(resolution, 0.0, -resolution / 2, 0.0, -resolution, resolution / 2))
    )


def test_run_hydroseason_succeeds_past_mask_coverage(monkeypatch, tmp_path):
    """A requested end_date past the historical mask's recorded coverage_end
    must not abort the run (the fatal coverage gate this plan removes), and
    the resulting HistoricalMaskCoverageWarning notice must reach both
    warnings.warn and HydroSeasonRunResult.warnings -- the full stack proof
    that Tasks 2-7's plumbing actually connects end to end through the real
    public entry point, not just at the unit level of each task's own tests.

    Only the two genuine external-service boundaries are mocked
    (``open_wo_statistics``, the Multi-Year Statistics STAC search, and
    ``load_wofs_from_stac``, the monthly WOfS STAC search); everything
    between them -- ``build_historical_water_mask``,
    ``_resolve_historical_water_mask``'s coverage-gate/warning logic, and
    the AOI-clipped reduction -- runs for real.
    """
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    import hydroseason.io as hio

    coverage_start = "1987-01-01"
    coverage_end = "2021-12-31"
    requested_start = "2010-01-01"
    requested_end = "2023-12-01"

    aoi = gpd.GeoDataFrame({"geometry": [box(-15, -60, 105, 15)]}, crs="EPSG:3577")
    stats_dataset = _fake_wo_statistics_dataset(
        time_span=f"{coverage_start}/{coverage_end}"
    )

    def fake_open_statistics(aoi_arg, *, stac_url, crs, resolution, **kwargs):
        return stats_dataset

    def fake_load_from_stac(stac_url, collection, aoi_arg, start, end, **kwargs):
        return _fake_monthly_wofs_cube(start, end)

    monkeypatch.setattr(hio, "open_wo_statistics", fake_open_statistics)
    monkeypatch.setattr(hio, "load_wofs_from_stac", fake_load_from_stac)

    with pytest.warns(UserWarning, match="not fully inside"):
        result = run_hydroseason(
            None,
            output_dir=tmp_path,
            aoi=aoi,
            start_date=requested_start,
            end_date=requested_end,
            stac_url="https://example.test/stac",
            analysis_options=ANALYSIS_OPTIONS,
        )

    assert result.artifacts.html.exists()
    assert result.source_kind == "dea_wofs"
    matches = [
        message
        for message in result.warnings
        if requested_end in message and coverage_end in message
    ]
    assert matches, result.warnings


def test_progress_reports_all_five_steps_in_order(tmp_path):
    seen = []

    run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        analysis_options=ANALYSIS_OPTIONS,
        progress=seen.append,
    )

    starts = [(e.step, e.label) for e in seen if e.phase == "start"]
    finishes = [(e.step, e.label) for e in seen if e.phase == "finish"]
    assert starts == [
        (1, "resolve water input"),
        (2, "analyze catchment"),
        (3, "rainfall"),
        (4, "rainfall comparison"),
        (5, "write report"),
    ]
    assert finishes == starts
    assert all(e.total_steps == 5 for e in seen)


def test_progress_marks_disabled_rainfall_steps_as_skipped(tmp_path):
    seen = []

    run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        analysis_options=ANALYSIS_OPTIONS,
        progress=seen.append,
    )

    details = {
        e.step: e.detail for e in seen if e.phase == "finish"
    }
    assert details[3] == "skipped"
    assert details[4] == "skipped"


def test_progress_finish_details_carry_the_run_facts(tmp_path):
    seen = []
    extent = _seasonal_extent()

    result = run_hydroseason(
        extent,
        output_dir=tmp_path,
        analysis_options=ANALYSIS_OPTIONS,
        progress=seen.append,
    )

    finishes = {e.step: e.detail for e in seen if e.phase == "finish"}
    assert f"{len(extent)} months" in finishes[1]
    assert result.analysis.route in finishes[2]
    assert str(result.artifacts.html.name) in finishes[5]


def test_progress_default_is_silent(tmp_path, capsys):
    run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        analysis_options=ANALYSIS_OPTIONS,
    )

    captured = capsys.readouterr()
    assert "[1/5]" not in captured.err
    assert "[1/5]" not in captured.out


def test_progress_true_writes_step_lines_to_stderr(tmp_path, capsys):
    run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        analysis_options=ANALYSIS_OPTIONS,
        progress=True,
    )

    err = capsys.readouterr().err
    assert "[1/5] resolve water input" in err
    assert "[5/5] write report done" in err


def test_progress_enables_the_per_year_bar_only_for_the_builtin_renderer(
    monkeypatch, tmp_path
):
    calls = []

    def fake_resolve(water_source, **kwargs):
        calls.append(kwargs)
        from hydroseason._workflow_input import ResolvedWaterInput

        return ResolvedWaterInput(_seasonal_extent(), "dea_wofs")

    monkeypatch.setattr("hydroseason.workflow.resolve_water_input", fake_resolve)
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())

    run_hydroseason(
        None, output_dir=tmp_path / "a", aoi="aoi.geojson",
        start_date="2010-01-01", end_date="2017-12-01",
        analysis_options=ANALYSIS_OPTIONS, progress=True,
    )
    run_hydroseason(
        None, output_dir=tmp_path / "b", aoi="aoi.geojson",
        start_date="2010-01-01", end_date="2017-12-01",
        analysis_options=ANALYSIS_OPTIONS, progress=lambda event: None,
    )

    assert calls[0]["progress"] is True
    assert calls[0]["progress_desc"] == "[1/5] resolve water input"
    assert calls[1]["progress"] is False


def test_fetch_rainfall_warns_upfront_when_silo_dependencies_are_missing(
    monkeypatch, tmp_path
):
    """A missing s3fs turned into rainfall_status='fetch_failed' only AFTER
    the water acquisition -- hours later on a DEA run. Warn before the water
    step instead, while the run is still cheap to abort."""
    monkeypatch.setattr(
        "hydroseason.workflow.missing_rainfall_dependencies",
        lambda: ("h5netcdf", "s3fs"),
    )
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())
    seen = []

    with pytest.warns(UserWarning, match=r"s3fs"):
        result = run_hydroseason(
            _seasonal_extent(),
            output_dir=tmp_path,
            aoi="aoi.geojson",
            fetch_rainfall=True,
            analysis_options=ANALYSIS_OPTIONS,
            progress=seen.append,
        )

    assert any("s3fs" in message for message in result.warnings)
    assert result.rainfall_status == "fetch_failed"


def test_no_dependency_warning_when_rainfall_is_not_requested(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "hydroseason.workflow.missing_rainfall_dependencies",
        lambda: ("h5netcdf", "s3fs"),
    )

    result = run_hydroseason(
        _seasonal_extent(),
        output_dir=tmp_path,
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert not any("s3fs" in message for message in result.warnings)


def test_run_hydroseason_surfaces_resolved_water_warnings(monkeypatch, tmp_path):
    """resolve_water_input can now carry non-fatal provenance notices on
    ResolvedWaterInput.warnings; run_hydroseason must fold them into the
    result's aggregated warnings alongside analysis and rainfall messages."""
    def fake_resolve(water_source, **kwargs):
        from hydroseason._workflow_input import ResolvedWaterInput

        return ResolvedWaterInput(
            _seasonal_extent(), "dea_wofs", ("probe warning",)
        )

    monkeypatch.setattr("hydroseason.workflow.resolve_water_input", fake_resolve)
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: object())

    result = run_hydroseason(
        None,
        output_dir=tmp_path,
        aoi="aoi.geojson",
        start_date="2010-01-01",
        end_date="2017-12-01",
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert "probe warning" in result.warnings


def test_supplied_rainfall_csv_does_not_probe_silo_dependencies(monkeypatch, tmp_path):
    extent = _seasonal_extent()
    rain_path = _rainfall_csv(tmp_path / "rain.csv", extent.index)

    def forbid_probe():
        raise AssertionError("a supplied CSV never touches SILO")

    monkeypatch.setattr(
        "hydroseason.workflow.missing_rainfall_dependencies", forbid_probe
    )

    result = run_hydroseason(
        extent,
        output_dir=tmp_path / "report",
        rainfall_csv_path=rain_path,
        fetch_rainfall=True,
        analysis_options=ANALYSIS_OPTIONS,
    )

    assert result.rainfall_status == "provided"
