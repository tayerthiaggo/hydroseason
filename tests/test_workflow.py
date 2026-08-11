from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydroseason.workflow import run_hydroseason


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
    monkeypatch.setattr("hydroseason.workflow.load_aoi", lambda value: sentinel_aoi)

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
    assert "Rainfall context (SILO)" in result.artifacts.html.read_text(encoding="utf-8")


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
        cache_dir, statistics_stac_url,
    ):
        calls.update(stac_url=stac_url, statistics_stac_url=statistics_stac_url)
        return _seasonal_extent()

    monkeypatch.setattr(
        "hydroseason._workflow_input.load_wofs_monthly_extent", fake_loader
    )
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
