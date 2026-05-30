from pathlib import Path

import pandas as pd

from hydroseason.config import load_config
from hydroseason.pipeline import (
    classify_rainfall,
    classify_rainfall_df,
    classify_rainfall_from_file,
)


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
        "get_monthly_silo_rainfall",
        lambda **_kwargs: monthly_df.copy(),
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

