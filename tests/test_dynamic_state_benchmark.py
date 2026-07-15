# tests/test_dynamic_state_benchmark.py
from pathlib import Path

import numpy as np
import pandas as pd

from hydroseason import (
    DynamicHydroYearConfig,
    aggregate_basin_monthly_extent,
    classify_annual_surface_water_condition,
    classify_seasonal_pattern,
    detect_dynamic_hydrological_years,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _month_error(left, right):
    left, right = pd.to_datetime(left), pd.to_datetime(right)
    return np.abs((left.dt.year - right.dt.year) * 12 + left.dt.month - right.dt.month)


def test_mock_benchmark_meets_scientific_acceptance_gates():
    panel = pd.read_csv(FIXTURES / "dynamic_state_mock.csv", parse_dates=["date"])
    truth = pd.read_csv(FIXTURES / "dynamic_state_truth.csv", parse_dates=["peak_month", "trough_month", "temporal_mid_dry_month", "half_loss_month"])
    extent = panel.loc[panel["site"] == "intermittent"].set_index("date")[["extent_pct", "invalid_pct"]]
    config = DynamicHydroYearConfig(expected_trough_month=9)
    annual = detect_dynamic_hydrological_years(extent, config=config)
    assert annual["hy_year"].is_unique
    assert annual.loc[annual["hy_year"] == 2008, "status"].item() == "unresolved"
    assert annual.loc[annual["hy_year"] == 2009, "status_reason"].item() == "no_previous_boundary"
    pulse = annual.loc[annual["hy_year"] == 2003].iloc[0]
    expected_pulse_trough = truth.loc[truth["hy_year"] == 2003, "trough_month"].item()
    assert pulse["trough_month"] == expected_pulse_trough
    assert pulse["n_rewetting_pulses"] >= 1

    joined = annual.merge(truth.loc[truth["detectable"]], on="hy_year", suffixes=("_actual", "_truth"))
    complete = joined.loc[joined["status"] == "complete"]
    assert (_month_error(complete["peak_month_actual"], complete["peak_month_truth"]) <= 1).mean() >= 0.90
    assert (_month_error(complete["trough_month_actual"], complete["trough_month_truth"]) <= 1).mean() >= 0.90
    assert (_month_error(complete["half_loss_month_actual"], complete["half_loss_month_truth"]) <= 1).mean() >= 0.90
    source = extent["extent_pct"]
    assert all(source.loc[date] == value for date, value in zip(complete["peak_month_actual"], complete["peak_extent_pct_actual"]))
    assert all(source.loc[date] == value for date, value in zip(complete["trough_month_actual"], complete["trough_extent_pct_actual"]))

    classified = classify_annual_surface_water_condition(annual)
    state_check = classified.merge(truth[["hy_year", "annual_condition"]], on="hy_year", suffixes=("_actual", "_truth"))
    extremes = state_check["annual_condition_truth"] != "typical_or_mixed"
    assert (state_check.loc[extremes, "annual_condition_actual"] == state_check.loc[extremes, "annual_condition_truth"]).all()


def test_mock_regime_and_basin_cases():
    panel = pd.read_csv(FIXTURES / "dynamic_state_mock.csv", parse_dates=["date"])
    perennial = panel.loc[panel["site"] == "perennial"].set_index("date")[["extent_pct", "invalid_pct"]]
    bimodal = panel.loc[panel["site"] == "bimodal"].set_index("date")[["extent_pct", "invalid_pct"]]
    assert classify_seasonal_pattern(perennial, n_bootstrap=40).pattern == "low_variability"
    assert classify_seasonal_pattern(bimodal, n_bootstrap=40).pattern == "bimodal_or_complex"

    basin = panel.loc[panel["site"].isin(["basin_small", "basin_large"])].rename(columns={"site": "aoi_id"})
    result = aggregate_basin_monthly_extent(basin)
    first = basin.loc[basin["date"] == basin["date"].min()]
    expected = 100 * first["n_water"].sum() / first["n_valid"].sum()
    assert result.iloc[0]["extent_pct"] == expected
