import numpy as np
import pandas as pd
import pytest

from hydroseason.dynamic_season import segment_by_cumulative_anomaly
from hydroseason.pipeline import classify_rainfall


def test_cumulative_anomaly_unimodal():
    # 24 months, unimodal wet season (months 4-8 are wet)
    dates = pd.date_range("2020-01-01", periods=24, freq="MS")
    # Wet months have 150mm, dry months have 5mm. median of entire series is 5mm.
    # q will be max(5.0, 10.0) = 10.0.
    rainfall = [
        5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 5, 5,  # Year 1
        5, 5, 5, 160, 190, 170, 150, 140, 5, 5, 5, 5   # Year 2
    ]
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": rainfall,
        "Hydro_Year_fixed": [2020] * 12 + [2021] * 12,
        "Month": dates.month
    })
    
    seg_df, boundaries = segment_by_cumulative_anomaly(
        df,
        is_bimodal=False,
        reference_floor=10.0
    )
    
    assert "SeasonType" in seg_df.columns
    # Check boundaries format
    assert len(boundaries) == 2
    assert boundaries.loc[0, "WetStart"] == pd.Timestamp("2020-04-01").date()
    assert boundaries.loc[0, "WetEnd"] == pd.Timestamp("2020-08-01").date()
    assert boundaries.loc[1, "WetStart"] == pd.Timestamp("2021-04-01").date()
    assert boundaries.loc[1, "WetEnd"] == pd.Timestamp("2021-08-01").date()

    # Verify SeasonType labels
    by_date = dict(zip(seg_df["Date"], seg_df["SeasonType"]))
    assert by_date[pd.Timestamp("2020-01-01")] == "Dry"
    assert by_date[pd.Timestamp("2020-04-01")] == "Wet"
    assert by_date[pd.Timestamp("2020-08-01")] == "Wet"
    assert by_date[pd.Timestamp("2020-09-01")] == "Dry"


def test_cumulative_anomaly_bimodal():
    # 12 months, bimodal wet season (months 3-4 and 9-10 are wet)
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    # median is 5.0, reference_floor is 10.0 -> q = 10.0
    rainfall = [5, 5, 120, 130, 5, 5, 5, 5, 110, 120, 5, 5]
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": rainfall,
        "Hydro_Year_fixed": [2020] * 12,
        "Month": dates.month
    })

    # Under unimodal settings, only the dominant wet season (months 3-4) is captured
    seg_unimodal, _ = segment_by_cumulative_anomaly(df, is_bimodal=False, reference_floor=10.0)
    by_date_uni = dict(zip(seg_unimodal["Date"], seg_unimodal["SeasonType"]))
    assert by_date_uni[pd.Timestamp("2020-03-01")] == "Wet"
    assert by_date_uni[pd.Timestamp("2020-09-01")] == "Dry"

    # Under bimodal settings, both wet seasons (months 3-4 and 9-10) are captured
    seg_bimodal, _ = segment_by_cumulative_anomaly(df, is_bimodal=True, reference_floor=10.0)
    by_date_bi = dict(zip(seg_bimodal["Date"], seg_bimodal["SeasonType"]))
    assert by_date_bi[pd.Timestamp("2020-03-01")] == "Wet"
    assert by_date_bi[pd.Timestamp("2020-04-01")] == "Wet"
    assert by_date_bi[pd.Timestamp("2020-05-01")] == "Dry"
    assert by_date_bi[pd.Timestamp("2020-09-01")] == "Wet"
    assert by_date_bi[pd.Timestamp("2020-10-01")] == "Wet"


def test_cumulative_anomaly_lonely_month_rejection():
    # 12 months with a wet season (months 4-8) and an isolated storm in the dry season (month 11)
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    # Month 11 is an isolated storm (e.g., 25mm), which is positive relative to q=10.0
    # But because Kadane searches for the single maximum subarray, the dominant wet season (months 4-8)
    # has a much larger net anomaly sum and is chosen, while the isolated storm is rejected.
    rainfall = [5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 25, 5]
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": rainfall,
        "Hydro_Year_fixed": [2020] * 12,
        "Month": dates.month
    })

    seg_df, _ = segment_by_cumulative_anomaly(df, is_bimodal=False, reference_floor=10.0)
    by_date = dict(zip(seg_df["Date"], seg_df["SeasonType"]))
    
    # Wet season is correctly identified
    assert by_date[pd.Timestamp("2020-04-01")] == "Wet"
    # Isolated storm remains Dry (not expanded, not labeled Wet)
    assert by_date[pd.Timestamp("2020-11-01")] == "Dry"


def test_cumulative_anomaly_arid_quantile_collapse():
    # Arid region with very low rainfall. Median is 1.0mm.
    # Trace rainfall events (e.g. 5mm) in dry months should not trigger wet seasons.
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    # With reference_floor=10.0, q becomes 10.0.
    # Wet season has months with > 10mm, while dry season has 1mm to 8mm.
    # If q collapsed to median (1.0), dry-season 8mm would look like wet anomalies.
    # By keeping q >= 10.0, dry-season 8mm has anomaly 8 - 10 = -2 < 0 (Dry).
    rainfall = [1, 2, 8, 30, 40, 50, 1, 2, 1, 1, 1, 1]
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": rainfall,
        "Hydro_Year_fixed": [2020] * 12,
        "Month": dates.month
    })

    seg_df, _ = segment_by_cumulative_anomaly(df, is_bimodal=False, reference_floor=10.0)
    by_date = dict(zip(seg_df["Date"], seg_df["SeasonType"]))

    # Wet season correctly identified
    assert by_date[pd.Timestamp("2020-04-01")] == "Wet"
    # 8mm month in month 3 has negative anomaly relative to q=10.0 and stays Dry
    assert by_date[pd.Timestamp("2020-03-01")] == "Dry"


def test_pipeline_integration_cumulative_anomaly():
    # End-to-end run of the pipeline with segmentation_method="cumulative_anomaly"
    dates = pd.date_range("2020-01-01", periods=36, freq="MS")
    rainfall = [
        5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 5, 5,
        5, 5, 5, 160, 190, 170, 150, 140, 5, 5, 5, 5,
        5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 5, 5
    ]
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "Rainfall_mm": rainfall
    })

    artifacts = classify_rainfall(
        df,
        segmentation_method="cumulative_anomaly",
        cumulative_anomaly_reference_floor=10.0
    )

    assert "SeasonType" in artifacts.result.columns
    assert "Hydro_Year" in artifacts.result.columns
    assert artifacts.diagnostics.tail_floor_source == "cumulative_anomaly"
    
    # Check that it successfully resolved Wet and Dry months
    wet_months = artifacts.result[artifacts.result["SeasonType"] == "Wet"]
    assert len(wet_months) > 0
    
    # Check that dry months exist
    dry_months = artifacts.result[artifacts.result["SeasonType"] == "Dry"]
    assert len(dry_months) > 0


def test_pipeline_integration_hybrid():
    # End-to-end run of the pipeline with segmentation_method="hybrid"
    dates = pd.date_range("2020-01-01", periods=24, freq="MS")
    # Wet months (4-8) have high rain (150mm), Month 11 has an isolated storm (25mm)
    rainfall = [
        5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 25, 5,
        5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 25, 5
    ]
    df = pd.DataFrame({
        "Date": dates,
        "Year": dates.year,
        "Month": dates.month,
        "Rainfall_mm": rainfall
    })

    artifacts = classify_rainfall(
        df,
        segmentation_method="hybrid",
        cumulative_anomaly_reference_floor=10.0,
        cumulative_anomaly_absolute_floor=10.0,
        cumulative_anomaly_smooth=False
    )

    assert "SeasonType" in artifacts.result.columns
    assert "Hydro_Year" in artifacts.result.columns
    assert artifacts.diagnostics.tail_floor_source == "hybrid"

    by_date = dict(zip(artifacts.result["Date"], artifacts.result["SeasonType"]))
    # Wet season is correctly identified
    assert by_date[pd.Timestamp("2020-04-01")] == "Wet"
    # Isolated storm remains Dry (clipped by Liebmann window)
    assert by_date[pd.Timestamp("2020-11-01")] == "Dry"


def test_cumulative_anomaly_p2_options():
    # Verify that passing use_stl_residual_gate and use_multi_year_cumsum works without errors
    dates = pd.date_range("2020-01-01", periods=24, freq="MS")
    # Wet months (4-8) have high rain (150mm), Month 11 has a huge storm (1000mm)
    # The storm is a massive outlier and should trigger the STL residual gate.
    rainfall = [
        5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 1000, 5,
        5, 5, 5, 150, 200, 180, 160, 150, 5, 5, 5, 5
    ]
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": rainfall,
        "Hydro_Year_fixed": [2020] * 12 + [2021] * 12,
        "Month": dates.month
    })

    # 1. Without STL gate, the huge storm (1000mm) is so massive it shifts the anomalies and remains Wet.
    seg_df_no_gate, _ = segment_by_cumulative_anomaly(
        df,
        is_bimodal=False,
        reference_floor=10.0,
        use_stl_residual_gate=False
    )
    assert seg_df_no_gate.loc[10, "SeasonType"] == "Wet"

    # 2. With STL gate, the storm is capped to climatological median, so it becomes Dry!
    seg_df_gate, _ = segment_by_cumulative_anomaly(
        df,
        is_bimodal=False,
        reference_floor=10.0,
        use_stl_residual_gate=True
    )
    assert seg_df_gate.loc[10, "SeasonType"] == "Dry"

    # 3. Test multi-year cumulative sum option
    seg_df_my, _ = segment_by_cumulative_anomaly(
        df,
        is_bimodal=False,
        reference_floor=10.0,
        use_multi_year_cumsum=True
    )
    assert (seg_df_my["SeasonType"] == "Wet").any()


