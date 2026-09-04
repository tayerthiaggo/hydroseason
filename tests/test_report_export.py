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
    dates = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (dates.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)


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
    analysis = analyze_catchment(
        seasonal_extent,
        phase_scheme="two_phase",
        n_bootstrap=40,
    )
    years = build_hydro_years_export(analysis, name="Test Catchment")
    assert not years.empty
    assert "catchment" in years.columns
    assert (years["catchment"] == "Test Catchment").all()

    summary = build_summary_export(analysis, name="Test Catchment", verdict="Seasonal regime detected.")
    assert len(summary) == 1
    assert summary.loc[0, "verdict"] == "Seasonal regime detected."
    assert list(summary.columns) == [
        "catchment",
        "decision_policy",
        "regime",
        "route",
        "amplitude_snr",
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
        "n_peak_timing_years",
        "n_trough_timing_years",
        "n_zero_months",
        "zero_month_fraction",
        "n_whole_zero_years",
        "pixel_support_status",
        "timing_evidence",
        "n_usable_years",
        "n_usable_months",
        "n_hydro_years",
        "boundary_basis",
        "climatological_peak_month",
        "climatological_trough_month",
        "n_wet_events",
        "median_event_duration_months",
        "longest_low_spell_months",
        "median_recurrence_months",
        "years_without_wet_event",
        "verdict",
    ]
    assert summary.loc[0].drop("verdict").to_dict() == analysis.summary_row(
        name="Test Catchment"
    )


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


def test_hydro_years_csv_carries_timing_identifiability_columns(seasonal_extent):
    from hydroseason._report_export import build_user_hydro_years_export

    analysis = analyze_catchment(seasonal_extent, phase_scheme="two_phase", n_bootstrap=40)
    user_hy = build_user_hydro_years_export(analysis.hydro_years)
    timing_columns = [
        "timing_status",
        "peak_timing_status",
        "peak_interval_start_date",
        "peak_interval_end_date",
        "trough_timing_status",
        "trough_interval_start_date",
        "trough_interval_end_date",
        "detectability_floor_pp",
        "amplitude_to_floor_ratio",
    ]
    for column in timing_columns:
        assert column in user_hy.columns


def test_public_extremum_date_is_blank_unless_timing_status_is_point():
    from hydroseason._report_export import build_user_hydro_years_export

    hydro_years = pd.DataFrame([
        {
            "hy_year": 2020, "peak_month": pd.Timestamp("2020-02-01"),
            "trough_month": pd.Timestamp("2020-09-01"),
            "peak_timing_status": "point", "trough_timing_status": "interval",
            "trough_interval_start": pd.Timestamp("2020-08-01"),
            "trough_interval_end": pd.Timestamp("2020-10-01"),
        },
        {
            "hy_year": 2021, "peak_month": pd.Timestamp("2021-02-01"),
            "trough_month": pd.Timestamp("2021-09-01"),
            "peak_timing_status": "unresolved", "trough_timing_status": "point",
        },
    ])
    out = build_user_hydro_years_export(hydro_years)
    row_2020 = out.loc[out["hy_year"] == 2020].iloc[0]
    row_2021 = out.loc[out["hy_year"] == 2021].iloc[0]

    assert row_2020["peak_date"] == pd.Timestamp("2020-02-01")
    assert pd.isna(row_2020["trough_date"])
    assert row_2020["trough_interval_start_date"] == pd.Timestamp("2020-08-01")
    assert row_2020["trough_interval_end_date"] == pd.Timestamp("2020-10-01")

    assert pd.isna(row_2021["peak_date"])
    assert row_2021["trough_date"] == pd.Timestamp("2021-09-01")


def test_monthly_and_hydro_years_user_export_fields(seasonal_extent):
    from hydroseason._report_export import build_user_hydro_years_export

    analysis = analyze_catchment(seasonal_extent, phase_scheme="two_phase", n_bootstrap=40)
    monthly = build_monthly_export(seasonal_extent, analysis=analysis)
    user_monthly = build_user_monthly_export(monthly, analysis=analysis, hydro_years=analysis.hydro_years)

    assert "confidence" in user_monthly.columns
    assert user_monthly["confidence"].dropna().isin({"high", "medium", "low"}).all()

    user_hy = build_user_hydro_years_export(analysis.hydro_years)
    assert "mid_dry_invalid_pct" in user_hy.columns
    assert user_hy["mid_dry_invalid_pct"].notna().all()
    assert (user_hy["mid_dry_invalid_pct"] == 0.0).all()
    assert "annual_condition" in user_hy.columns
    assert user_hy["annual_condition"].notna().all()


def _hy_frame():
    """Minimal dynamic-detector frame: one point, one broad, one unresolved."""
    return pd.DataFrame(
        {
            "hy_year": [2020, 2021, 2022],
            "trough_month": pd.to_datetime(["2020-10-01", "2021-11-01", "2022-09-01"]),
            "trough_interval_start": pd.to_datetime(["2020-10-01", "2021-08-01", "2022-01-01"]),
            "trough_interval_end": pd.to_datetime(["2020-10-01", "2021-11-01", "2022-12-01"]),
            "trough_timing_status": ["point", "broad", "unresolved"],
            "peak_timing_status": ["point", "point", "point"],
        }
    )


def test_trough_boundary_date_uses_the_window_end_when_localised():
    from hydroseason._report_export import build_user_hydro_years_export
    out = build_user_hydro_years_export(_hy_frame())
    assert out.loc[0, "trough_boundary_date"] == pd.Timestamp("2020-10-01")
    assert out.loc[1, "trough_boundary_date"] == pd.Timestamp("2021-11-01")


def test_trough_boundary_date_falls_back_to_trough_month_when_unresolved():
    from hydroseason._report_export import build_user_hydro_years_export
    out = build_user_hydro_years_export(_hy_frame())
    assert out.loc[2, "trough_boundary_date"] == pd.Timestamp("2022-09-01")


def test_trough_boundary_date_is_populated_on_every_row():
    from hydroseason._report_export import build_user_hydro_years_export
    out = build_user_hydro_years_export(_hy_frame())
    assert out["trough_boundary_date"].notna().all()


def test_trough_date_keeps_its_point_only_meaning():
    from hydroseason._report_export import build_user_hydro_years_export
    out = build_user_hydro_years_export(_hy_frame())
    assert out.loc[0, "trough_date"] == pd.Timestamp("2020-10-01")
    assert pd.isna(out.loc[1, "trough_date"])
    assert pd.isna(out.loc[2, "trough_date"])

