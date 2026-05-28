from pathlib import Path

import pandas as pd

from hydroseason.pipeline import classify, delineate_monthly_dataframe, run_pipeline_from_csv


def test_classify_one_liner(monthly_df: pd.DataFrame):
    result = classify(monthly_df)
    assert "Hydro_Year" in result.columns
    assert "SeasonType" in result.columns


def test_delineate_returns_artifacts(monthly_df: pd.DataFrame):
    artifacts = delineate_monthly_dataframe(monthly_df)
    assert artifacts.diagnostics.regime in {"non_seasonal", "borderline", "seasonal"}
    assert artifacts.diagnostics.hydro_year_start_month is None or 1 <= artifacts.diagnostics.hydro_year_start_month <= 12
    assert artifacts.diagnostics.fallback_month_used >= 1
    assert artifacts.diagnostics.threshold_firstpass is None or artifacts.diagnostics.threshold_firstpass >= 0
    assert len(artifacts.fixed_monthly) == 12


def test_run_pipeline_from_csv_writes_output(fixture_csv_path: Path, tmp_path: Path):
    out = tmp_path / "out.csv"
    artifacts = run_pipeline_from_csv(fixture_csv_path, output_csv=out)
    assert out.exists()
    df = pd.read_csv(out)
    assert "Seasonality_STL" in df.columns
    assert "Seasonality_Regime" in df.columns


def test_delineate_works_with_renamed_value_col(monthly_df: pd.DataFrame):
    df = monthly_df.rename(columns={"Rainfall_mm": "Q_mm"})
    artifacts = delineate_monthly_dataframe(df, value_col="Q_mm")
    assert "SeasonType" in artifacts.result.columns
