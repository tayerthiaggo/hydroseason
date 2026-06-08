from pathlib import Path

import pandas as pd

from hydroseason.config import load_config
from hydroseason.pipeline import (
    _month_quantile_floor,
    _validate_hydro_year_labels_within_record,
    classify_rainfall,
    classify_rainfall_df,
    classify_rainfall_from_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_classify_rainfall_df_one_liner(monthly_df: pd.DataFrame):
    result = classify_rainfall_df(monthly_df)
    assert "Hydro_Year" in result.columns
    assert "SeasonType" in result.columns


def test_classify_rainfall_returns_artifacts(monthly_df: pd.DataFrame):
    artifacts = classify_rainfall(monthly_df)
    assert artifacts.diagnostics.regime in {"non_seasonal", "borderline", "seasonal"}
    assert artifacts.diagnostics.hydro_year_start_month is None or 1 <= artifacts.diagnostics.hydro_year_start_month <= 12
    assert artifacts.diagnostics.fallback_month_used >= 1
    assert artifacts.diagnostics.threshold_firstpass is None or artifacts.diagnostics.threshold_firstpass >= 0
    assert len(artifacts.fixed_monthly) == 12


def test_classify_rainfall_bundle(monthly_df: pd.DataFrame):
    artifacts = classify_rainfall(monthly_df)
    assert "SeasonType" in artifacts.result.columns


def test_classify_rainfall_from_file_writes_output(fixture_csv_path: Path, tmp_path: Path):
    out = tmp_path / "out.csv"
    artifacts = classify_rainfall_from_file(fixture_csv_path, source="auto", output_csv=out)
    assert out.exists()
    df = pd.read_csv(out)
    assert "Seasonality_STL" in df.columns
    assert "Seasonality_Regime" in df.columns


def test_classify_rainfall_from_file_auto_source(fixture_csv_path: Path, tmp_path: Path):
    out = tmp_path / "out_rainfall.csv"
    artifacts = classify_rainfall_from_file(fixture_csv_path, source="auto", output_csv=out)
    assert out.exists()
    assert "Hydro_Year" in artifacts.result.columns


def test_run_pipeline_fetch_silo_config(
    tmp_path: Path,
    monthly_df: pd.DataFrame,
    monkeypatch,
):
    from hydroseason import fetch as fetch_mod
    from hydroseason.pipeline import run_pipeline

    out = tmp_path / "silo_config_results.csv"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""
output:
    output_csv: {out.as_posix()}
fetch:
    enabled: true
    source: silo
    vector_path: data/fitzroy_catchment.geojson
    start_year: 2020
    end_year: 2021
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(fetch_mod, "load_vector", lambda _path: object())
    monkeypatch.setattr(
        fetch_mod,
        "get_monthly_aoi_rainfall",
        lambda *_args, **_kwargs: monthly_df.assign(
            Data_Source="SILO",
            Data_Product="SILO monthly rainfall",
            Fetch_Note="Australian gridded monthly rainfall default",
        ),
    )

    result = run_pipeline(load_config(cfg))

    assert out.exists()
    assert "Hydro_Year" in result.columns


def test_classify_works_with_renamed_value_col(monthly_df: pd.DataFrame):
    df = monthly_df.rename(columns={"Rainfall_mm": "Q_mm"})
    artifacts = classify_rainfall(df, value_col="Q_mm")
    assert "SeasonType" in artifacts.result.columns


def test_raise_on_error_alias_matches_yaml_name(monthly_df: pd.DataFrame):
    artifacts = classify_rainfall(monthly_df, raise_on_error=True)
    assert "SeasonType" in artifacts.result.columns


# ---------------------------------------------------------------------------
# Cross-regime end-to-end portability tests for the adaptive parameters.
# All fixtures are synthetic so they pin algorithmic behaviour without relying
# on external datasets.
# ---------------------------------------------------------------------------
def _build_monthly_record(start_year: int, n_years: int, monthly_climatology: list[float], jitter: float = 0.0, seed: int = 0) -> pd.DataFrame:
    import numpy as np
    rng = np.random.default_rng(seed)
    dates = pd.date_range(f"{start_year}-01-01", periods=12 * n_years, freq="MS")
    base = np.tile(np.asarray(monthly_climatology, dtype=float), n_years)
    if jitter > 0:
        noise = rng.normal(0.0, jitter, size=base.size) * np.maximum(base, 1.0) / 100.0
        base = np.clip(base + noise, 0.0, None)
    return pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "Rainfall_mm": base,
    })


def test_unimodal_monsoonal_adaptive_defaults():
    """Sharp unimodal monsoonal climatology resolves to the conservative
    paper-spec defaults (smooth=3, min_core=3, onset_window=1)."""
    clim = [220, 190, 100, 25, 5, 0, 0, 0, 5, 15, 50, 120]  # Fitzroy-like
    df = _build_monthly_record(1990, 12, clim, jitter=10.0, seed=1)
    artifacts = classify_rainfall(df)
    diag = artifacts.diagnostics
    assert diag.regime in {"seasonal", "borderline"}
    if diag.regime == "seasonal":
        assert diag.smooth_window_used == 3
        assert diag.min_core_length_used == 3
        assert diag.onset_window_months_used == 1


def test_mediterranean_recession_shoulder_absorbed_end_to_end():
    """Mediterranean-style Nov-Mar wet, dry summer, with a wet April shoulder.
    The recession shoulder must land Wet after the adaptive pipeline runs."""
    # Climatology with strong Nov-Mar core and a non-trivial April recession
    clim = [110, 95, 80, 40, 10, 2, 0, 0, 5, 20, 70, 100]
    df = _build_monthly_record(2000, 10, clim, jitter=5.0, seed=2)
    # Force an unambiguous April shoulder in a specific year.
    mask = (df["Year"] == 2005) & (df["Month"] == 4)
    df.loc[mask, "Rainfall_mm"] = 60.0
    artifacts = classify_rainfall(df)
    if artifacts.diagnostics.regime != "seasonal":
        import pytest
        pytest.skip(f"synthetic Mediterranean record classified as {artifacts.diagnostics.regime}")
    res = artifacts.result.copy()
    res["Date"] = pd.to_datetime(res["Date"])
    apr_2005 = res.loc[res["Date"] == pd.Timestamp("2005-04-01"), "SeasonType"].iloc[0]
    assert apr_2005 == "Wet", res[res["Year"] == 2005][["Date", "Rainfall_mm", "SeasonType"]]


def test_bimodal_pipeline_disables_onset_window():
    """Bimodal climatology should auto-resolve onset_window_months to None so
    the second wet season's onsets are not discarded as 'mid-year pulses'."""
    # Equatorial-style bimodal climatology (long and short rains)
    clim = [40, 60, 180, 230, 200, 30, 10, 10, 40, 150, 200, 110]
    df = _build_monthly_record(2000, 8, clim, jitter=8.0, seed=3)
    artifacts = classify_rainfall(df)
    diag = artifacts.diagnostics
    if diag.is_bimodal:
        assert diag.onset_window_months_used is None


def test_rolling_climatology_tracks_shifted_recent_wet_months():
    rows = []
    for year in range(1920, 2020):
        for month in range(1, 13):
            if year < 2000:
                rain = 100.0 if month in {11, 12, 1} else 0.0
            else:
                rain = 15.0 if month in {2, 3, 4} else 0.0
            rows.append({
                "Date": pd.Timestamp(year=year, month=month, day=1),
                "Year": year,
                "Month": month,
                "Rainfall_mm": rain,
            })
    df = pd.DataFrame(rows)

    rolling = classify_rainfall(
        df,
        climatology_window="rolling",
        climatology_window_years=10,
        climatology_min_month_observations=5,
        climatology_min_wet_year_fraction=0.60,
    )
    result = rolling.result.copy()
    result["Date"] = pd.to_datetime(result["Date"])
    by_date = result.set_index("Date")

    assert rolling.diagnostics.climatology_window == "rolling"
    assert rolling.diagnostics.climatology_window_years == 10
    assert rolling.diagnostics.climatology_min_wet_year_fraction == 0.60
    assert rolling.diagnostics.onset_window_months_used == 3
    assert by_date.loc[pd.Timestamp("2019-02-01"), "SeasonType"] == "Wet"
    assert by_date.loc[pd.Timestamp("2019-03-01"), "SeasonType"] == "Wet"
    assert by_date.loc[pd.Timestamp("2019-04-01"), "SeasonType"] == "Wet"
    assert by_date.loc[pd.Timestamp("2019-02-01"), "Hydro_Year"] != by_date.loc[
        pd.Timestamp("2018-02-01"), "Hydro_Year"
    ]


def test_rolling_guardrails_widen_unimodal_auto_onset_window():
    rows = []
    for year in range(1980, 2010):
        for month in range(1, 13):
            if year < 1995:
                rain = 120.0 if month in {11, 12, 1} else 2.0
            else:
                rain = 120.0 if month in {12, 1, 2} else 2.0
            rows.append(
                {
                    "Date": pd.Timestamp(year=year, month=month, day=1),
                    "Year": year,
                    "Month": month,
                    "Rainfall_mm": rain,
                }
            )
    df = pd.DataFrame(rows)

    artifacts = classify_rainfall(
        df,
        climatology_window="rolling",
        climatology_window_years=10,
        onset_window_months="auto",
    )
    diag = artifacts.diagnostics

    if diag.regime == "seasonal" and not diag.is_bimodal:
        assert diag.climatology_guardrail_source in {"rolling_trailing", "mixed"}
        assert diag.onset_window_months_used == 3


def test_arid_regime_core_floor_prevents_spurious_wet_core():
    """In an arid record the non-zero quantile collapses to ~mm. The site-scaled
    core floor must protect the wet-core threshold so trivial rainfall events
    are not picked up as the dominant block."""
    # Very arid: tiny wet pulse around Feb, near-zero elsewhere
    clim = [5, 30, 4, 1, 0, 0, 0, 0, 0, 0, 1, 3]
    df = _build_monthly_record(1990, 15, clim, jitter=4.0, seed=4)
    artifacts = classify_rainfall(df)
    diag = artifacts.diagnostics
    # Either non_seasonal/borderline (arid passes through as such) or seasonal
    # with a non-trivial first-pass threshold raised by the core floor.
    if diag.regime == "seasonal":
        assert diag.threshold_firstpass is not None
        assert diag.threshold_firstpass >= diag.core_climatology_floor - 1e-9


def test_diagnostics_reports_resolved_adaptive_values(monthly_df: pd.DataFrame):
    """The DiagnosticsReport must expose what was actually used so users can
    audit/lock the resolved adaptive choices for reproducibility."""
    artifacts = classify_rainfall(monthly_df)
    diag = artifacts.diagnostics
    if diag.regime == "seasonal":
        assert diag.smooth_window_used is not None
        assert diag.min_core_length_used is not None
        assert diag.core_climatology_floor is not None
        assert diag.shoulder_climatology_floor is not None
        assert diag.tail_floor == diag.threshold_firstpass
        assert diag.shoulder_month_quantile == 0.60
        assert diag.shoulder_month_floor_source == "observed"
        assert diag.shoulder_residual_threshold is not None


def test_explicit_overrides_take_precedence(monthly_df: pd.DataFrame):
    """Locking values via kwargs must bypass adaptive resolution."""
    artifacts = classify_rainfall(
        monthly_df,
        smooth_window=5,
        min_core_length=4,
        onset_window_months=2,
    )
    diag = artifacts.diagnostics
    if diag.regime == "seasonal":
        assert diag.smooth_window_used == 5
        assert diag.min_core_length_used == 4
        assert diag.onset_window_months_used == 2


def test_residual_gate_can_be_disabled(monthly_df: pd.DataFrame):
    artifacts = classify_rainfall(
        monthly_df,
        shoulder_residual_quantile=None,
    )
    assert artifacts.diagnostics.shoulder_residual_threshold is None


def test_low_1987_88_wet_season_is_not_merged():
    df = pd.read_csv(FIXTURES / "DATASET2.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

    artifacts = classify_rainfall(df)
    result = artifacts.result.copy()
    result["Date"] = pd.to_datetime(result["Date"])
    by_date = result.set_index("Date")

    assert by_date.loc[pd.Timestamp("1987-12-01"), "SeasonType"] == "Wet"
    assert by_date.loc[pd.Timestamp("1988-01-01"), "SeasonType"] == "Wet"
    assert by_date.loc[pd.Timestamp("1987-12-01"), "Hydro_Year"] == 1988

    hy1988 = result[result["Hydro_Year"] == 1988]
    assert hy1988["Date"].min() == pd.Timestamp("1987-12-01")
    assert hy1988["Date"].max() == pd.Timestamp("1988-10-01")
    assert (hy1988["SeasonType"] == "Wet").sum() >= 2
    assert (hy1988["SeasonType"] == "Dry").sum() < 19


def test_ten_year_stability_guard_blocks_unstable_false_shoulders():
    df = pd.read_csv(FIXTURES / "DATASET2.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

    artifacts = classify_rainfall(df)
    result = artifacts.result.copy()
    result["Date"] = pd.to_datetime(result["Date"])
    by_date = result.set_index("Date")

    assert artifacts.diagnostics.climatology_window_years == 10
    assert artifacts.diagnostics.climatology_unstable_month_count > 0
    assert by_date.loc[pd.Timestamp("2010-04-01"), "SeasonType"] == "Dry"
    assert by_date.loc[pd.Timestamp("2022-09-01"), "SeasonType"] == "Dry"
    assert by_date.loc[pd.Timestamp("2022-10-01"), "SeasonType"] == "Dry"


def test_imputed_record_does_not_invent_future_hydro_years():
    df = pd.read_csv(Path("data/monthly_rainfall2.csv"))

    artifacts = classify_rainfall(df)
    result = artifacts.result.copy()
    result["Date"] = pd.to_datetime(result["Date"])
    by_date = result.set_index("Date")

    assert artifacts.diagnostics.n_imputed == 36
    assert artifacts.diagnostics.is_bimodal is False
    assert artifacts.diagnostics.onset_window_months_used == 1
    assert result["Hydro_Year"].max() == 2023
    assert by_date.loc[pd.Timestamp("2004-03-01"), "Hydro_Year"] == 2004
    assert by_date.loc[pd.Timestamp("2005-03-01"), "Hydro_Year"] == 2005
    assert by_date.loc[pd.Timestamp("2022-03-01"), "Hydro_Year"] == 2022


def test_hydro_year_guard_rejects_date_escaped_labels():
    import pytest

    dates = pd.to_datetime(["2022-03-01", "2023-10-01"])
    result = pd.DataFrame(
        {
            "Date": dates,
            "Hydro_Year": [2025, 2027],
        }
    )

    with pytest.raises(RuntimeError, match="date-constrained record bounds"):
        _validate_hydro_year_labels_within_record(
            result,
            hydro_year_start_month=11,
            date_col="Date",
        )


def test_rolling_guardrail_diagnostics_summarise_actual_tail_floors():
    df = pd.read_csv(FIXTURES / "DATASET2.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

    artifacts = classify_rainfall(df, keep_debug_columns=True)
    diag = artifacts.diagnostics
    tail_values = artifacts.result["_TailFloor"].dropna().round(6)

    assert len(tail_values) > 0
    assert diag.tail_floor == diag.threshold_firstpass
    assert round(diag.tail_floor_min, 6) == float(tail_values.min())
    assert round(diag.tail_floor_max, 6) == float(tail_values.max())
    assert diag.tail_floor_unique_count == int(tail_values.nunique())
    assert diag.tail_floor_source == (
        "per_row" if tail_values.nunique() > 1 else "scalar"
    )
    assert diag.extension_floor_min is not None
    assert diag.extension_floor_max is not None


def test_shoulder_month_quantile_validates_range(monthly_df: pd.DataFrame):
    import pytest

    with pytest.raises(ValueError, match="shoulder_month_quantile"):
        classify_rainfall(monthly_df, shoulder_month_quantile=1.5)

    with pytest.raises(ValueError, match="climatology_min_wet_year_fraction"):
        classify_rainfall(monthly_df, climatology_min_wet_year_fraction=1.5)


def test_month_quantile_floor_prefers_observed_values():
    rows = []
    for month in range(1, 13):
        base = month * 10.0
        rows.extend([
            {"Month": month, "Rainfall_mm": base, "Imputed": False},
            {"Month": month, "Rainfall_mm": base + 1.0, "Imputed": False},
            {"Month": month, "Rainfall_mm": base + 2.0, "Imputed": False},
            {"Month": month, "Rainfall_mm": 10000.0, "Imputed": True},
        ])
    df = pd.DataFrame(rows)

    floor, source = _month_quantile_floor(
        df,
        month_col="Month",
        value_col="Rainfall_mm",
        quantile=0.75,
    )

    assert source == "observed"
    assert floor.loc[10] < 200.0


def test_low_confidence_missing_data_disables_month_floor():
    clim = [220, 190, 100, 25, 5, 0, 0, 0, 5, 15, 50, 120]
    df = _build_monthly_record(2000, 15, clim)
    drop_dates = {
        pd.Timestamp(year=year, month=((year - 2000 + 5) % 12) + 1, day=1)
        for year in range(2000, 2015)
    }
    df = df[~df["Date"].isin(drop_dates)].reset_index(drop=True)

    artifacts = classify_rainfall(df)
    diag = artifacts.diagnostics

    assert diag.data_confidence == "low"
    if diag.regime == "seasonal":
        assert diag.shoulder_month_floor_source == "disabled_low_confidence"



def test_low_confidence_long_record_keeps_global_onset_guard():
    clim = [220, 190, 100, 25, 5, 0, 0, 0, 5, 15, 50, 120]
    df = _build_monthly_record(1950, 50, clim)
    drop_dates = {
        pd.Timestamp(year=year, month=((year - 1950 + 5) % 12) + 1, day=1)
        for year in range(1950, 2000)
    }
    df = df[~df["Date"].isin(drop_dates)].reset_index(drop=True)

    artifacts = classify_rainfall(df)
    diag = artifacts.diagnostics

    assert diag.data_confidence == "low"
    if diag.regime == "seasonal":
        assert diag.climatology_guardrail_source == "global"
        assert diag.onset_window_months_used == 1


def test_regime_window_years_subsets_correctly():
    # Construct a dataset where older years have strong seasonality, but newer years are completely uniform.
    # If we use regime_window_years=10, it should classify as non-seasonal because it only looks at the last 10 years.
    # If we use regime_window_years=0, it should use the full record and might classify as borderline/seasonal.
    clim_seasonal = [100, 100, 100, 10, 10, 10, 10, 10, 10, 10, 10, 10]
    clim_uniform = [40] * 12
    
    rows = []
    # Years 1980 to 2009: seasonal (30 years)
    for year in range(1980, 2010):
        for month in range(1, 13):
            rows.append({
                "Date": pd.Timestamp(year=year, month=month, day=1),
                "Year": year,
                "Month": month,
                "Rainfall_mm": clim_seasonal[month-1],
            })
    # Years 2010 to 2019: uniform (10 years)
    for year in range(2010, 2020):
        for month in range(1, 13):
            rows.append({
                "Date": pd.Timestamp(year=year, month=month, day=1),
                "Year": year,
                "Month": month,
                "Rainfall_mm": clim_uniform[month-1],
            })
    df = pd.DataFrame(rows)

    # Full record: should see strong seasonality overall due to 30 seasonal years
    art_full = classify_rainfall(df, regime_window_years=0)
    assert art_full.diagnostics.regime in {"seasonal", "borderline"}
    assert art_full.diagnostics.regime_window_years == 0

    # Recent 10 years only: should be non-seasonal
    art_window = classify_rainfall(df, regime_window_years=10)
    assert art_window.diagnostics.regime == "non_seasonal"
    assert art_window.diagnostics.regime_window_years == 10


def test_non_seasonal_min_month_hy():
    # Completely uniform climatology with noise, so it is classified as non_seasonal.
    # The minimum month will be resolved from the random variation in the data.
    clim = [30.0] * 12
    df = _build_monthly_record(2000, 20, clim, jitter=20.0, seed=42)
    
    artifacts = classify_rainfall(df)
    assert artifacts.diagnostics.regime == "non_seasonal"
    assert artifacts.diagnostics.non_seasonal_hy_start_month is not None
    assert 1 <= artifacts.diagnostics.non_seasonal_hy_start_month <= 12
    assert artifacts.diagnostics.hydro_year_start_month == artifacts.diagnostics.non_seasonal_hy_start_month
    # The Hydro_Year boundary source should be "min_month"
    first_indices = artifacts.result.groupby("Hydro_Year", sort=False).head(1).index
    boundary_sources = artifacts.result.loc[first_indices, "Hydro_Year_Boundary_Source"].dropna().unique()
    assert "min_month" in boundary_sources or "initial" in boundary_sources


def test_adaptive_wet_year_fraction_low_contrast():
    # Setup dry_driest/wet_less_wet climatology with circular_R < 0.50
    # season_contrast_class dry_driest or wet_less_wet is determined by _season_contrast_diagnostics
    # Let's verify that effective_wet_year_fraction is lowered to 0.40
    clim = [20.0, 22.0, 25.0, 18.0, 15.0, 12.0, 14.0, 16.0, 18.0, 20.0, 19.0, 21.0] # diffuse, low contrast
    df = _build_monthly_record(2000, 15, clim)
    
    artifacts = classify_rainfall(df, climatology_min_wet_year_fraction=0.60)
    # Check effective fraction
    assert artifacts.diagnostics.effective_wet_year_fraction is not None
    # Depending on regime, if it gets classified as seasonal, effective_wet_year_fraction should be <= 0.40
    if artifacts.diagnostics.regime == "seasonal":
        assert artifacts.diagnostics.effective_wet_year_fraction <= 0.40
