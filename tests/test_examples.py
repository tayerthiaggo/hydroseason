from __future__ import annotations

import pandas as pd

from hydroseason.examples import (
    create_mock_extent_data,
    dynamic_hydro_years_for_report,
    flag_extent_quality,
    load_workflow_extent,
)


def test_load_workflow_extent_uses_csv_fallback_for_offline_stac_default(tmp_path):
    extent, source = load_workflow_extent(
        input_source="stac",
        run_remote_stac=False,
        csv_fallback_when_stac_disabled=True,
        csv_path=tmp_path / "mock_extent.csv",
        stac_url="https://example.invalid/stac",
        collection="ga_ls_wo_3",
        aoi_path=tmp_path / "aoi.geojson",
        start_date="2006-01-01",
        end_date="2006-12-31",
        periods=24,
    )

    assert source == "csv_fallback"
    assert isinstance(extent.index, pd.DatetimeIndex)
    assert list(extent.columns) == ["extent_pct", "invalid_pct"]
    assert len(extent) == 24


def test_load_workflow_extent_rejects_unknown_source(tmp_path):
    try:
        load_workflow_extent(
            input_source="spreadsheet",
            run_remote_stac=False,
            csv_fallback_when_stac_disabled=True,
            csv_path=tmp_path / "mock_extent.csv",
            stac_url="https://example.invalid/stac",
            collection="ga_ls_wo_3",
            aoi_path=tmp_path / "aoi.geojson",
            start_date="2006-01-01",
            end_date="2006-12-31",
            periods=24,
        )
    except ValueError as exc:
        assert "input_source" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("Expected ValueError for unknown input_source.")


def test_load_workflow_extent_reads_existing_csv_option(tmp_path):
    path = tmp_path / "existing_extent.csv"
    create_mock_extent_data(periods=12).to_csv(path, index=False)

    extent, source = load_workflow_extent(
        input_source="csv",
        run_remote_stac=False,
        csv_fallback_when_stac_disabled=False,
        csv_path=path,
        stac_url="https://example.invalid/stac",
        collection="ga_ls_wo_3",
        aoi_path=tmp_path / "aoi.geojson",
        start_date="2006-01-01",
        end_date="2006-12-31",
        periods=24,
    )

    assert source == "csv"
    assert len(extent) == 12
    assert extent.index.min() == pd.Timestamp("2006-01-01")


def test_flag_extent_quality_preserves_observations_and_flags_bias():
    raw = pd.DataFrame(
        {
            "extent_pct": [10.0, 20.0, float("nan"), 40.0],
            "invalid_pct": [0.0, 25.0, 100.0, 0.0],
        },
        index=pd.date_range("2020-01-01", periods=4, freq="MS"),
    )

    observed, quality = flag_extent_quality(raw, max_invalid_pct=10.0)

    pd.testing.assert_frame_equal(observed, raw)
    assert quality["quality_flag"].tolist() == ["usable", "high_invalid_pct", "missing_extent", "usable"]
    assert quality.loc["2020-02-01", "invalid_pct"] == 25.0
    assert quality["bias_warning"].str.contains("Potential bias").sum() == 2


def test_dynamic_hydro_years_for_report_uses_resolved_dynamic_cycles():
    dynamic = pd.DataFrame(
        {
            "hy_year": [2020, 2021],
            "status": ["partial", "complete"],
            "hy_start": [pd.NaT, pd.Timestamp("2020-09-01")],
            "hy_end": [pd.NaT, pd.Timestamp("2021-08-01")],
            "peak_month": [pd.NaT, pd.Timestamp("2021-02-01")],
            "peak_extent_pct": [float("nan"), 80.0],
            "temporal_mid_dry_month": [pd.NaT, pd.Timestamp("2021-05-01")],
            "temporal_mid_dry_extent_pct": [float("nan"), 40.0],
            "trough_month": [pd.Timestamp("2020-08-01"), pd.Timestamp("2021-08-01")],
            "trough_extent_pct": [10.0, 8.0],
            "cycle_months": [float("nan"), 12],
            "confidence": ["low", "high"],
        }
    )

    report_years = dynamic_hydro_years_for_report(dynamic)

    assert report_years["hy_year"].tolist() == [2021]
    assert report_years.loc[0, "end_dry_month"] == pd.Timestamp("2021-08-01")
