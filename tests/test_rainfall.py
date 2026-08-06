"""SILO rainfall as ancillary context, and the extent-vs-rainfall comparison.

Rainfall never enters regime classification or boundary detection for the
water-extent record: it is compared against them. Contaminating the primary
analysis would forfeit the ability to say "this is what the satellite saw".
"""
import numpy as np
import pandas as pd
import pytest

from hydroseason import assess_water_regime
from hydroseason._rainfall import (
    align_monthly_rainfall,
    load_monthly_rainfall_csv,
    monthly_rainfall_to_frame,
    normalise_monthly_rainfall,
)
from hydroseason._regime_compare import (
    compare_extent_and_rainfall_regimes,
    compare_rainfall_to_extent_regime,
)


def _monthly(values, start="1990-01-01", col="rainfall_mm"):
    index = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({col: np.asarray(values, dtype=float)}, index=index)


def _seasonal_rain(years=30, peak_month=2, seed=0, noise=6.0):
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    phase = 2 * np.pi * (index.month - peak_month) / 12.0
    return pd.DataFrame(
        {"rainfall_mm": np.clip(90 + 80 * np.cos(phase) + rng.normal(0, noise, len(index)), 0, None)},
        index=index,
    )


def _flat_rain(years=30, seed=1):
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    return pd.DataFrame(
        {"rainfall_mm": np.clip(rng.normal(45, 30, len(index)), 0, None)}, index=index
    )


def _seasonal_extent(years=30, peak_month=2, seed=2, noise=0.02):
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    phase = 2 * np.pi * (index.month - peak_month) / 12.0
    return pd.DataFrame(
        {"extent_pct": np.clip(1.0 + 0.8 * np.cos(phase) + rng.normal(0, noise, len(index)), 0.01, None),
         "invalid_pct": 0.0},
        index=index,
    )


def _flat_extent(years=30, seed=3):
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.abs(rng.normal(0.15, 0.12, len(index))), "invalid_pct": 0.0},
        index=index,
    )


# --- rainfall frame adaptation --------------------------------------------

def test_rainfall_frame_is_adapted_to_the_shared_regime_input():
    """Regime assessment reads extent_pct in [0, 100]; rainfall mm routinely
    exceeds 100 in the wet season, so it is rescaled to a percent-of-peak
    index rather than passed through raw -- a monotonic rescale that changes
    no regime verdict (assess_water_regime's diagnostics are ratios)."""
    frame = monthly_rainfall_to_frame(_monthly([10.0, 20.0, 30.0]))
    assert "extent_pct" in frame.columns
    assert "invalid_pct" in frame.columns
    assert frame["extent_pct"].tolist() == pytest.approx([100 / 3, 200 / 3, 100.0])
    assert frame["extent_pct"].max() == pytest.approx(100.0)


def test_rainfall_frame_accepts_a_tidy_date_column():
    tidy = pd.DataFrame({
        "Date": pd.date_range("1990-01-01", periods=6, freq="MS"),
        "Rainfall_mm": [1.0, 2, 3, 4, 5, 6],
    })
    frame = monthly_rainfall_to_frame(tidy, value_col="Rainfall_mm", date_col="Date")
    assert len(frame) == 6
    assert frame["extent_pct"].iloc[-1] == pytest.approx(100.0)


def test_rainfall_frame_stays_in_bounds_for_the_shared_regime_input():
    """The whole point of the rescale: real SILO magnitudes (0-300mm/month)
    must clear assess_water_regime's [0, 100] domain check without error."""
    from hydroseason import assess_water_regime

    heavy = _monthly([0.0, 5.0, 300.0, 250.0, 10.0, 0.0] * 20)
    frame = monthly_rainfall_to_frame(heavy)
    assert frame["extent_pct"].between(0, 100).all()
    assess_water_regime(frame)  # must not raise


def test_rainfall_frame_rejects_an_unknown_value_column():
    with pytest.raises(KeyError, match="not_a_column"):
        monthly_rainfall_to_frame(_monthly([1.0, 2.0]), value_col="not_a_column")


# --- the comparison --------------------------------------------------------

def test_matching_seasonal_regimes_report_agreement():
    result = compare_extent_and_rainfall_regimes(
        _seasonal_extent(peak_month=2), _seasonal_rain(peak_month=1)
    )
    assert result.extent_regime == "seasonal"
    assert result.rainfall_regime == "seasonal"
    assert result.divergence == "agree"


def test_seasonal_rainfall_with_aseasonal_extent_flags_damping():
    """The diagnostic that matters: rainfall has a cycle, water extent does
    not. Something between the two is removing the signal."""
    result = compare_extent_and_rainfall_regimes(_flat_extent(), _seasonal_rain())
    assert result.extent_regime == "aseasonal"
    assert result.rainfall_regime == "seasonal"
    assert result.divergence == "extent_damped"
    assert "regulation" in result.interpretation.lower()


def test_both_aseasonal_reports_climate_consistent():
    result = compare_extent_and_rainfall_regimes(_flat_extent(), _flat_rain())
    assert result.divergence == "agree"
    assert "rainfall" in result.interpretation.lower()


def test_seasonal_extent_with_aseasonal_rainfall_is_flagged_as_unexpected():
    result = compare_extent_and_rainfall_regimes(_seasonal_extent(), _flat_rain())
    assert result.divergence == "extent_more_seasonal"


def test_phase_lag_is_reported_in_months():
    result = compare_extent_and_rainfall_regimes(
        _seasonal_extent(peak_month=4), _seasonal_rain(peak_month=1)
    )
    assert result.peak_lag_months is not None
    assert 2 <= result.peak_lag_months <= 4


def test_phase_lag_wraps_across_the_year_boundary():
    """A December rainfall peak and a January extent peak are one month apart,
    not eleven."""
    result = compare_extent_and_rainfall_regimes(
        _seasonal_extent(peak_month=1), _seasonal_rain(peak_month=12)
    )
    assert result.peak_lag_months == 1


def test_comparison_never_alters_the_extent_verdict():
    """Rainfall is ancillary. The extent regime must be identical to what
    assess_water_regime returns on its own."""
    from hydroseason import assess_water_regime

    extent = _flat_extent()
    standalone = assess_water_regime(extent)
    compared = compare_extent_and_rainfall_regimes(extent, _seasonal_rain())
    assert compared.extent_regime == standalone.regime
    assert compared.extent.amplitude_snr == standalone.amplitude_snr


def test_missing_rainfall_yields_an_extent_only_result():
    result = compare_extent_and_rainfall_regimes(_seasonal_extent(), None)
    assert result.rainfall_regime is None
    assert result.divergence == "no_rainfall"
    assert result.extent_regime == "seasonal"


# --- rainfall CSV normalization/alignment -----------------------------------

def test_load_monthly_rainfall_csv_normalises_dates_and_values(tmp_path):
    path = tmp_path / "rain.csv"
    pd.DataFrame(
        {"date": ["2020-01-18", "2020-03-22"], "rainfall_mm": ["10", "30"]}
    ).to_csv(path, index=False)

    rainfall = load_monthly_rainfall_csv(path)

    assert rainfall.index.tolist() == [
        pd.Timestamp("2020-01-01"),
        pd.Timestamp("2020-03-01"),
    ]
    assert rainfall["rainfall_mm"].tolist() == [10, 30]


def test_rainfall_rejects_duplicate_months_and_missing_columns():
    duplicate = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-20"],
            "rainfall_mm": [1.0, 2.0],
        }
    )
    with pytest.raises(ValueError, match="duplicate months"):
        normalise_monthly_rainfall(duplicate)
    with pytest.raises(ValueError, match="date.*rainfall_mm"):
        normalise_monthly_rainfall(pd.DataFrame({"rain": [1.0]}))


def test_align_rainfall_preserves_extent_axis_and_missing_months():
    rainfall = normalise_monthly_rainfall(
        pd.DataFrame(
            {"date": ["2020-01-01", "2020-03-01"], "rainfall_mm": [10.0, 30.0]}
        )
    )
    axis = pd.date_range("2020-01-01", "2020-03-01", freq="MS")
    aligned = align_monthly_rainfall(rainfall, axis)

    assert aligned.index.equals(axis)
    assert pd.isna(aligned.loc["2020-02-01", "rainfall_mm"])


# --- authoritative comparison ------------------------------------------------

def test_comparison_reuses_authoritative_extent_assessment():
    extent = _seasonal_extent(peak_month=2)
    authoritative = assess_water_regime(extent)
    result = compare_rainfall_to_extent_regime(
        authoritative,
        _seasonal_rain(peak_month=1),
    )

    assert result.extent is authoritative
    assert result.rainfall_regime == "seasonal"
    assert result.peak_lag_months == 1


def test_existing_comparison_wrapper_remains_compatible():
    extent = _seasonal_extent(peak_month=2)
    rainfall = _seasonal_rain(peak_month=1)
    wrapped = compare_extent_and_rainfall_regimes(extent, rainfall)
    direct = compare_rainfall_to_extent_regime(
        assess_water_regime(extent), rainfall
    )

    assert wrapped.divergence == direct.divergence
    assert wrapped.peak_lag_months == direct.peak_lag_months
    assert wrapped.interpretation == direct.interpretation
