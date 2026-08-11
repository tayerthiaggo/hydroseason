import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._report_export import (
    build_events_export,
    build_hydro_years_export,
    build_monthly_export,
    build_summary_export,
    build_user_events_export,
    build_user_low_spells_export,
    build_user_monthly_export,
    safe_stem,
    write_report_csvs,
)


@pytest.fixture
def seasonal_extent():
    dates = pd.date_range("2010-01-01", "2015-12-01", freq="MS")
    records = []
    for date in dates:
        month = date.month
        val = 10.0 + 30.0 * np.sin(2 * np.pi * (month - 1) / 12) + np.random.normal(0, 1)
        records.append({"extent_pct": max(0.0, min(100.0, val)), "invalid_pct": 0.0})
    return pd.DataFrame(records, index=dates)


@pytest.fixture
def aseasonal_extent():
    years = 10
    rng = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=12 * years, freq="MS")
    values = np.abs(rng.normal(0.15, 0.12, 12 * years))
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)


@pytest.fixture
def rainfall_df():
    dates = pd.date_range("2010-01-01", "2015-12-01", freq="MS")
    records = []
    for date in dates:
        records.append({"rainfall_mm": 50.0 + 20.0 * np.sin(2 * np.pi * date.month / 12)})
    return pd.DataFrame(records, index=dates)


def test_safe_stem():
    assert safe_stem("Fitzroy / Station 1 (QLD)") == "fitzroy-station-1-qld"
    assert safe_stem("!!!") == "catchment"


def test_monthly_export_preserves_every_source_month(seasonal_extent):
    analysis = analyze_catchment(seasonal_extent, phase_model="rule_based", n_bootstrap=40)
    out = build_monthly_export(seasonal_extent, analysis=analysis)
    assert len(out) == len(seasonal_extent)
    assert out["date"].is_monotonic_increasing
    assert {
        "extent_pct",
        "invalid_pct",
        "usable_month",
        "reference_median_pct",
        "anomaly_pct",
        "condition_percentile",
        "quality_state",
        "hy_year",
        "phase",
        "is_hy_peak",
        "is_hy_trough",
        "in_wet_event",
        "wet_event_id",
        "in_low_spell",
        "low_spell_id",
        "regime",
        "route",
    } <= set(out.columns)


def test_flagged_analysis_exports_partial_quality_months_as_usable():
    dates = pd.date_range("2010-01-01", periods=24, freq="MS")
    extent = pd.DataFrame(
        {
            "extent_pct": np.linspace(1.0, 12.0, len(dates)),
            "invalid_pct": [0.0, 90.0] * (len(dates) // 2),
        },
        index=dates,
    )
    analysis = analyze_catchment(extent, quality_policy="flag")
    out = build_monthly_export(extent, analysis=analysis)

    assert out["usable_month"].all()
    assert out.loc[out["invalid_pct"] == 90.0, "quality_state"].eq("low").all()


def test_aseasonal_export_has_no_hy_or_phase_claims(aseasonal_extent):
    analysis = analyze_catchment(aseasonal_extent, phase_model="rule_based", n_bootstrap=40)
    monthly = build_monthly_export(aseasonal_extent, analysis=analysis)
    years = build_hydro_years_export(analysis, name="Dryland")
    assert years.empty
    assert monthly["hy_year"].isna().all()
    assert monthly["phase"].eq("unspecified").all()
    assert not monthly["is_hy_peak"].any()
    assert not monthly["is_hy_trough"].any()


def test_monthly_export_aligns_optional_rainfall_by_month(seasonal_extent, rainfall_df):
    analysis = analyze_catchment(seasonal_extent, n_bootstrap=40)
    out = build_monthly_export(seasonal_extent, analysis=analysis, rainfall=rainfall_df)
    assert {"rainfall_mm", "rain_anomaly_mm"} <= set(out.columns)
    assert out["date"].is_unique


def test_build_hydro_years_export_and_summary(seasonal_extent):
    analysis = analyze_catchment(seasonal_extent, phase_model="rule_based", n_bootstrap=40)
    years = build_hydro_years_export(analysis, name="Test Catchment")
    assert not years.empty
    assert "catchment" in years.columns
    assert (years["catchment"] == "Test Catchment").all()

    summary = build_summary_export(analysis, name="Test Catchment", verdict="Seasonal regime detected.")
    assert len(summary) == 1
    assert summary.loc[0, "verdict"] == "Seasonal regime detected."
    assert {
        "peak_timing_concentration",
        "peak_timing_concentration_ci_low",
        "peak_timing_concentration_ci_high",
        "peak_timing_uniformity_p",
        "peak_phase_iqr_months",
        "trough_timing_concentration",
        "trough_timing_concentration_ci_low",
        "trough_timing_concentration_ci_high",
        "trough_timing_uniformity_p",
        "trough_phase_iqr_months",
        "n_timing_years",
    } <= set(summary.columns)


def test_build_events_export(seasonal_extent):
    analysis = analyze_catchment(seasonal_extent, n_bootstrap=40)
    events_df, low_spells_df = build_events_export(analysis)
    assert isinstance(events_df, pd.DataFrame)
    assert isinstance(low_spells_df, pd.DataFrame)


def test_user_csv_exports_include_quality_threshold_and_event_baseline(seasonal_extent):
    analysis = analyze_catchment(seasonal_extent, phase_model="rule_based", n_bootstrap=40)
    monthly = build_monthly_export(seasonal_extent, analysis=analysis)
    events, low_spells = build_events_export(analysis)
    baseline = analysis.events.summary["baseline_pct"]

    user_monthly = build_user_monthly_export(monthly, analysis=analysis)
    user_events = build_user_events_export(events, baseline_extent_pct=baseline)
    user_low_spells = build_user_low_spells_export(
        low_spells, baseline_extent_pct=baseline
    )

    assert user_monthly["max_invalid_pct"].eq(analysis.max_invalid_pct).all()
    assert user_monthly["baseline_extent_pct"].eq(baseline).all()
    assert user_events["baseline_extent_pct"].eq(baseline).all()
    assert user_low_spells["baseline_extent_pct"].eq(baseline).all()


def test_write_report_csvs(tmp_path, seasonal_extent):
    analysis = analyze_catchment(seasonal_extent, phase_model="rule_based", n_bootstrap=40)
    monthly = build_monthly_export(seasonal_extent, analysis=analysis)
    years = build_hydro_years_export(analysis, name="Test Catchment")
    events, low_spells = build_events_export(analysis)
    paths = write_report_csvs(
        tmp_path,
        stem="test-catchment",
        monthly=monthly,
        hydro_years=years,
        events=events,
        low_spells=low_spells,
    )

    assert set(paths.keys()) == {"monthly", "hydro_years", "wet_event", "low_spells"}
    assert paths["wet_event"].name == "test-catchment_wet_event.csv"
    for p in paths.values():
        assert p.exists()
