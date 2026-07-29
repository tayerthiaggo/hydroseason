import numpy as np
import pandas as pd

from hydroseason._regime import assess_water_regime


def _series(monthly_values, years=30, noise=0.0, seed=0):
    """Monthly extent series repeating ``monthly_values`` with optional noise."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    values = np.tile(monthly_values, years)
    if noise:
        values = values + rng.normal(0.0, noise, size=len(values))
    return pd.DataFrame(
        {"extent_pct": np.clip(values, 0.0, None), "invalid_pct": 0.0},
        index=index,
    )


def _drop_months(frame, months):
    """Blank out given calendar months, mimicking wet-season cloud loss."""
    out = frame.copy()
    out.loc[out.index.month.isin(months), "extent_pct"] = np.nan
    out.loc[out.index.month.isin(months), "invalid_pct"] = 100.0
    return out


# --- regime classification -------------------------------------------------

def test_strong_annual_cycle_is_seasonal():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    result = assess_water_regime(_series(cycle, noise=0.02))
    assert result.regime == "seasonal"
    assert result.amplitude_snr > 2.0
    assert result.climatological_peak_month == 2


def test_flat_noise_only_series_is_aseasonal():
    flat = np.repeat(0.15, 12)
    result = assess_water_regime(_series(flat, noise=0.12, seed=3))
    assert result.regime == "aseasonal"
    assert result.climatological_peak_month is None
    assert result.climatological_trough_month is None


def test_weak_cycle_under_heavy_noise_is_marginal():
    cycle = 0.45 + 0.16 * np.cos(2 * np.pi * (np.arange(12) - 10) / 12)
    result = assess_water_regime(_series(cycle, noise=0.16, seed=7))
    assert result.regime == "marginal"


def test_short_record_is_insufficient():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    result = assess_water_regime(_series(cycle, years=3))
    assert result.regime == "insufficient_record"
    assert result.climatological_peak_month is None


# --- the tropical cloud-gap regression ------------------------------------

def test_partial_years_still_classify_when_wet_months_are_cloud_lost():
    """A monsoonal catchment losing 2 wet months/yr to cloud must not be
    reported as having no usable record: the 12/12 completeness rule this
    replaces discarded exactly the strongly-seasonal catchments."""
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    gappy = _drop_months(_series(cycle, noise=0.02), months=[1, 2])
    result = assess_water_regime(gappy)
    assert result.regime == "seasonal"
    assert result.n_usable_years >= 20


def test_completeness_threshold_is_configurable():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    gappy = _drop_months(_series(cycle, noise=0.02), months=[1, 2, 3, 4])
    lenient = assess_water_regime(gappy, min_months_per_year=8)
    strict = assess_water_regime(gappy, min_months_per_year=11)
    assert lenient.n_usable_years > strict.n_usable_years


# --- scale invariance ------------------------------------------------------

def test_regime_is_invariant_to_absolute_extent_scale():
    """A catchment whose whole signal sits under 1% must classify the same as
    one an order of magnitude larger. An absolute pp tolerance breaks this."""
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    big = assess_water_regime(_series(cycle, noise=0.02))
    small = assess_water_regime(_series(cycle * 0.05, noise=0.001))
    assert big.regime == small.regime == "seasonal"
    assert small.climatological_peak_month == big.climatological_peak_month


# --- guidance payload ------------------------------------------------------

def test_seasonal_regime_permits_per_year_boundaries():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    result = assess_water_regime(_series(cycle, noise=0.02))
    assert result.supports_per_year_boundaries is True
    assert result.supports_fixed_window is True


def test_marginal_regime_permits_fixed_window_but_not_per_year():
    cycle = 0.45 + 0.16 * np.cos(2 * np.pi * (np.arange(12) - 10) / 12)
    result = assess_water_regime(_series(cycle, noise=0.16, seed=7))
    assert result.supports_fixed_window is True
    assert result.supports_per_year_boundaries is False


def test_aseasonal_regime_permits_neither():
    result = assess_water_regime(_series(np.repeat(0.15, 12), noise=0.12, seed=3))
    assert result.supports_fixed_window is False
    assert result.supports_per_year_boundaries is False


def test_assessment_reports_event_descriptors():
    result = assess_water_regime(_series(np.repeat(0.15, 12), noise=0.12, seed=3))
    assert result.longest_low_spell_months > 0
    assert result.n_wet_events > 0


def test_persistent_noise_is_downgraded_not_rated_high():
    """Multi-year wet/dry persistence inflates a window's max-minus-min without
    any seasonal cycle being present. Confidence must not read that as signal.
    """
    from hydroseason.hydro_year import HydroYearConfig, detect_hydrological_years

    rng = np.random.default_rng(5)
    index = pd.date_range("1990-01-01", periods=12 * 30, freq="MS")
    walk = np.zeros(len(index))
    for i in range(1, len(index)):  # AR(1), no seasonal term whatsoever
        walk[i] = 0.8 * walk[i - 1] + rng.normal(0.0, 0.1)
    frame = pd.DataFrame(
        {"extent_pct": np.abs(walk + 0.5), "invalid_pct": 0.0}, index=index
    )
    cfg = HydroYearConfig(
        wet_start_month=12, wet_end_month=4, dry_start_month=5, dry_end_month=10
    )
    result = detect_hydrological_years(
        frame, config=cfg, quality_policy="flag", missing_month_policy="ignore"
    )
    high_fraction = (result["confidence"] == "high").mean()
    assert high_fraction < 0.5, f"persistent noise rated {high_fraction:.0%} high"


def test_caveats_never_claim_climate_and_flag_non_rainfall_drivers():
    """Surface-water extent is water availability as observed, not a climate
    signal: regulated or extracted catchments can look aseasonal for reasons
    that have nothing to do with rainfall."""
    result = assess_water_regime(_series(np.repeat(0.15, 12), noise=0.12, seed=3))
    joined = " ".join(result.caveats).lower()
    # Climate may only appear as an explicit disclaimer, never as a claim.
    assert "not a climate variable" in joined
    assert "water availability" in joined
    assert "regulation" in joined or "extraction" in joined


def test_event_descriptors_match_the_shared_event_definition():
    """Regime must not carry its own private notion of an event.

    A second definition drifts from the first: the regime module previously
    counted episodes on a bare p75 quantile while ``extract_water_events``
    used noise-relative thresholds with hysteresis and duration filters, so
    the same record reported two different event counts depending on which
    entry point the caller used.
    """
    from hydroseason._events import extract_water_events

    frame = _series(np.repeat(0.15, 12), noise=0.12, seed=3)
    regime = assess_water_regime(frame)
    events = extract_water_events(frame)
    assert regime.n_wet_events == events.summary["n_events"]
    assert regime.longest_low_spell_months == events.summary["longest_low_spell_months"]
