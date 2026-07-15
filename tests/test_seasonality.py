import numpy as np
import pandas as pd

from hydroseason._seasonality import classify_seasonal_pattern


def _signal(values, years=12):
    index = pd.date_range("2000-01-01", periods=12 * years, freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.tile(values, years), "invalid_pct": 0.0},
        index=index,
    )


def test_unimodal_bimodal_low_variability_and_short_records():
    unimodal = 30.0 + 20.0 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    bimodal = 30.0 + 15.0 * np.cos(4 * np.pi * (np.arange(12) - 1) / 12)
    assert classify_seasonal_pattern(_signal(unimodal), n_bootstrap=40).pattern == "unimodal_annual"
    assert classify_seasonal_pattern(_signal(bimodal), n_bootstrap=40).pattern == "bimodal_or_complex"
    assert classify_seasonal_pattern(_signal(np.repeat(20.0, 12)), n_bootstrap=40).pattern == "low_variability"
    assert classify_seasonal_pattern(_signal(unimodal, years=4), n_bootstrap=40).pattern == "insufficient_record"
