"""Regression tests: first-party code must not emit RuntimeWarning."""

from __future__ import annotations

import warnings

import pandas as pd


def test_noise_floor_pp_handles_zero_variance_residual_without_warning():
    from hydroseason.hydro_year import _noise_floor_pp

    index = pd.date_range("2020-01-01", periods=6, freq="MS")
    flat = pd.Series(5.0, index=index)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = _noise_floor_pp(flat)

    assert result == 0.0

