import numpy as np
import pandas as pd

from hydroseason._catchment import analyze_catchment
from hydroseason._regime import assess_water_regime
from hydroseason.hydrological_state import HydrologicalStateResult


def _seasonal(years=30, noise=0.02, seed=0):
    rng = np.random.default_rng(seed)
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    values = np.tile(cycle, years) + rng.normal(0, noise, 12 * years)
    return pd.DataFrame(
        {"extent_pct": np.clip(values, 0, None), "invalid_pct": 0.0}, index=index
    )


def _aseasonal(years=30, seed=3):
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    values = np.abs(rng.normal(0.15, 0.12, 12 * years))
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def _percentage_equivalent_varying_coverage_series(years=30):
    """Return full-AOI and exact-mask count series with identical percentages.

    Both populations vary by month (and differ from each other) while
    retaining the same percentage signal. Any selector using absolute
    water/area counts rather than the documented percentages will therefore
    diverge.
    """
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    percentage_cycle = np.array([1, 1, 1, 1, 5, 10, 15, 20, 40, 80, 100, 10])
    extent_pct = np.tile(percentage_cycle, years)
    invalid_land = np.resize(np.array([0, 10, 20, 40, 60, 80, 100]), len(index))
    historical_valid = np.resize(
        np.array([100, 900, 200, 1200, 300, 1100, 400, 1000, 500, 900, 600, 800]),
        len(index),
    )
    full_valid = np.resize(
        np.array([3000, 2100, 3400, 2000, 3500, 2100, 3600, 2000, 3700, 2100, 3800, 2000]),
        len(index),
    )

    historical = pd.DataFrame(
        {
            "n_water": extent_pct * historical_valid // 100,
            "n_valid": historical_valid,
            "n_invalid": 0,
            "n_aoi": historical_valid,
        },
        index=index,
    )
    full_aoi = pd.DataFrame(
        {
            "n_water": extent_pct * full_valid // 100,
            "n_valid": full_valid,
            "n_invalid": invalid_land,
            "n_aoi": full_valid + invalid_land,
        },
        index=index,
    )
    return full_aoi, historical


def test_analysis_selections_are_unchanged_for_percentage_equivalent_mask_population():
    """Regime, cycles, phases, events and low spells use percentages, not area."""
    from hydroseason._state_input import prepare_monthly_extent

    full_aoi, historical = _percentage_equivalent_varying_coverage_series()
    full_prepared = prepare_monthly_extent(full_aoi)
    historical_prepared = prepare_monthly_extent(historical)
    full_result = analyze_catchment(full_aoi, phase_model="rule_based", n_bootstrap=40)
    historical_result = analyze_catchment(historical, phase_model="rule_based", n_bootstrap=40)

    assert full_result.regime.regime == historical_result.regime.regime == "seasonal"
    assert (full_aoi["n_water"] > historical["n_water"]).all()
    assert (full_aoi["n_aoi"] > historical["n_aoi"]).all()
    assert full_aoi["n_valid"].nunique() > 1
    assert historical["n_valid"].nunique() > 1
    assert historical.loc["1990-06-01", "n_water"] > historical.loc["1990-07-01", "n_water"]
    assert full_aoi.loc["1990-06-01", "n_water"] < full_aoi.loc["1990-07-01", "n_water"]
    assert not np.array_equal(
        np.argsort(full_aoi["n_water"].to_numpy()),
        np.argsort(historical["n_water"].to_numpy()),
    )
    np.testing.assert_array_equal(
        full_prepared["extent_pct"].to_numpy(), historical_prepared["extent_pct"].to_numpy()
    )
    assert full_prepared["invalid_pct"].nunique() > 1
    assert historical_prepared["invalid_pct"].eq(0.0).all()
    assert full_result.regime.n_usable_months == historical_result.regime.n_usable_months

    annual_columns = [
        "hy_start",
        "hy_end",
        "peak_month",
        "temporal_mid_dry_month",
        "trough_month",
    ]
    pd.testing.assert_frame_equal(
        full_result.hydro_years.loc[:, annual_columns],
        historical_result.hydro_years.loc[:, annual_columns],
    )
    pd.testing.assert_frame_equal(
        full_result.state.monthly_phase.loc[:, ["hy_year", "phase", "phase_status"]],
        historical_result.state.monthly_phase.loc[:, ["hy_year", "phase", "phase_status"]],
    )
    assert not full_result.events.events.empty
    assert not full_result.events.low_spells.empty
    pd.testing.assert_frame_equal(full_result.events.events, historical_result.events.events)
    pd.testing.assert_frame_equal(full_result.events.low_spells, historical_result.events.low_spells)


def _marginal(years=30, seed=7, peak_month=11, *, phase_wander=False):
    """Marginal-amplitude cycle peaking at ``peak_month`` (1..12).

    Default peak_month=11 preserves the original Nov-centred fixture used by
    the existing fixed-window routing tests. Set ``phase_wander=True`` when the
    test must stay inside the marginal band for every calendar peak: mild
    per-year peak shifts keep phase IQR above the seasonal ceiling without
    reaching aseasonal.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    if not phase_wander:
        # cos peaks when (month_index - (peak_month-1)) == 0.
        cycle = 0.45 + 0.16 * np.cos(
            2 * np.pi * (np.arange(12) - (peak_month - 1)) / 12
        )
        values = np.tile(cycle, years) + rng.normal(0, 0.16, 12 * years)
    else:
        # Deterministic mild wander: IQR lands in (1.5, 3.5), clim peak stays
        # near the requested month for every phase.
        base = [-2, -1, 0, 0, 1, 2, -1, 0, 1, -2, 1, 0]
        shifts = np.array(base * ((years // len(base)) + 1))[:years]
        chunks = []
        for shift in shifts:
            pm = (peak_month - 1 + int(shift)) % 12
            cycle = 0.50 + 0.20 * np.cos(2 * np.pi * (np.arange(12) - pm) / 12)
            chunks.append(cycle + rng.normal(0, 0.12, 12))
        values = np.concatenate(chunks)
    return pd.DataFrame(
        {"extent_pct": np.clip(values, 0, None), "invalid_pct": 0.0}, index=index
    )


def _timing_route_record(kind: str, *, years: int = 30):
    """Construct high-SNR records with controlled peak and trough timing."""
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    chunks = []
    for year in range(years):
        values = np.full(12, 5.0)
        if kind == "unstable_trough":
            peak_month, trough_month = 3, (0 if year % 2 == 0 else 6)
        elif kind == "concentrated_nonuniform":
            peak_month, trough_month = (3, 0) if year % 3 else (9, 6)
        elif kind == "diffuse_uniform":
            peak_month, trough_month = year % 12, (year + 6) % 12
        else:
            raise ValueError(f"unknown timing route fixture: {kind}")
        values[peak_month] = 10.0
        values[trough_month] = 0.0
        chunks.append(values)
    return pd.DataFrame(
        {"extent_pct": np.concatenate(chunks), "invalid_pct": 0.0}, index=index
    )


def _diffuse_uniform_marginal_record():
    """Seven broad-peak years: high SNR but uniform timing has little power."""
    index = pd.date_range("1990-01-01", periods=12 * 7, freq="MS")
    values = np.tile(np.array([8.0] * 11 + [0.0]), 7)
    for year, month in enumerate([1, 3, 5, 7, 9, 11, 1]):
        values[12 * year + month - 1] = 8.1
    return pd.DataFrame(
        {"extent_pct": values, "invalid_pct": 0.0}, index=index
    )


# --- routing runs without prompting ---------------------------------------

def test_seasonal_routes_to_per_year_detection():
    result = analyze_catchment(_seasonal())
    assert result.regime.regime == "seasonal"
    assert result.route == "per_year_detection"
    assert not result.hydro_years.empty
    assert "trough timing" in result.route_reason.lower()


def test_seasonal_record_with_unstable_trough_uses_fixed_window():
    result = analyze_catchment(_timing_route_record("unstable_trough"), n_bootstrap=40)

    assert result.regime.regime == "seasonal"
    assert result.regime.supports_per_year_boundaries is False
    assert result.route == "fixed_climatological_window"
    assert "fixed climatological window" in result.route_reason.lower()


def test_concentrated_nonuniform_marginal_uses_fixed_window():
    result = analyze_catchment(_timing_route_record("concentrated_nonuniform"), n_bootstrap=40)

    assert result.regime.regime == "marginal"
    assert result.regime.peak_timing_uniformity_p < 0.1
    assert result.regime.trough_timing_uniformity_p < 0.1
    assert result.regime.supports_fixed_window is True
    assert result.route == "fixed_climatological_window"


def test_diffuse_uniform_marginal_uses_event_characterisation():
    result = analyze_catchment(_diffuse_uniform_marginal_record(), n_bootstrap=40)

    assert result.regime.regime == "marginal"
    assert result.regime.peak_timing_uniformity_p >= 0.1
    assert result.regime.supports_fixed_window is False
    assert result.route == "event_characterisation"
    assert "complex or diffuse timing" in result.route_reason.lower()


def test_per_year_boundary_failure_falls_back_to_event_characterisation(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("dynamic detector rejected the record")

    monkeypatch.setattr("hydroseason._catchment.analyze_hydrological_state", fail)

    result = analyze_catchment(_seasonal(), n_bootstrap=40)

    assert result.route == "event_characterisation"
    assert result.hydro_years.empty
    assert "trough timing" in result.route_reason.lower()


def test_catchment_threads_existing_bootstrap_controls_to_regime_assessment():
    extent = _marginal()
    direct = assess_water_regime(extent, n_bootstrap=40, random_state=11)
    routed = analyze_catchment(extent, n_bootstrap=40, random_state=11)

    assert routed.regime.peak_timing_concentration_ci_low == direct.peak_timing_concentration_ci_low
    assert routed.regime.peak_timing_concentration_ci_high == direct.peak_timing_concentration_ci_high
    assert routed.regime.peak_timing_uniformity_p == direct.peak_timing_uniformity_p


def test_marginal_routes_to_fixed_window():
    result = analyze_catchment(_marginal())
    assert result.regime.regime == "marginal"
    assert result.route == "fixed_climatological_window"
    assert not result.hydro_years.empty


def test_aseasonal_routes_to_events_only_and_emits_no_hydro_years():
    result = analyze_catchment(_aseasonal())
    assert result.regime.regime == "aseasonal"
    assert result.route == "event_characterisation"
    assert result.hydro_years.empty


def test_every_route_returns_events():
    """Event descriptors are always available, whatever the regime -- they are
    the one view that never depends on a cycle existing."""
    for frame in (_seasonal(), _marginal(), _aseasonal()):
        assert analyze_catchment(frame).events is not None


def test_route_is_recorded_with_a_reason_for_audit():
    result = analyze_catchment(_aseasonal())
    assert result.route_reason
    assert "aseasonal" in result.route_reason.lower()


def test_analysis_never_raises_on_a_record_with_no_detectable_cycle():
    """The whole point of routing: a record the detector cannot handle must
    return a usable result rather than propagate an exception."""
    result = analyze_catchment(_aseasonal())
    assert result.route == "event_characterisation"
    assert result.events.summary["n_events"] >= 0


def test_short_record_is_routed_without_error():
    short = _seasonal(years=3)
    result = analyze_catchment(short)
    assert result.regime.regime == "insufficient_record"
    assert result.route == "insufficient_record"
    assert result.hydro_years.empty


def test_fixed_window_years_are_marked_as_imposed_not_detected():
    """A marginal catchment's boundaries come from an assumption the workflow
    imposed. That must be visible in the output, not inferred by the reader.
    """
    result = analyze_catchment(_marginal())
    assert (result.hydro_years["boundary_basis"] == "imposed_fixed_window").all()


def test_seasonal_years_are_marked_as_detected():
    result = analyze_catchment(_seasonal())
    assert (result.hydro_years["boundary_basis"] == "detected_per_year").all()


def test_seasonal_route_uses_robust_dynamic_state():
    result = analyze_catchment(_seasonal(), phase_model="rule_based", n_bootstrap=40)

    assert result.route == "per_year_detection"
    assert isinstance(result.state, HydrologicalStateResult)
    assert result.state.config.detector == "robust_extrema"
    pd.testing.assert_frame_equal(result.hydro_years, result.state.hydro_years)
    assert result.hydro_years["boundary_basis"].eq("detected_per_year").all()
    assert result.state.monthly_phase["phase_method"].eq("rule_based").any()


def test_analyze_catchment_phase_toggle_never_changes_public_annual_frame():
    # Permanent regression for the stage-06 review's focused probe: toggling
    # only phase_model through the public analyze_catchment entry point must
    # leave the full public annual frame exactly equal, not just the
    # lower-level detect_dynamic_hydrological_years output.
    extent = _seasonal()
    none_result = analyze_catchment(extent, phase_model="none", n_bootstrap=40)
    rule_based_result = analyze_catchment(extent, phase_model="rule_based", n_bootstrap=40)
    assert not none_result.hydro_years.empty
    pd.testing.assert_frame_equal(none_result.hydro_years, rule_based_result.hydro_years)


def test_aseasonal_route_never_constructs_state_or_years():
    result = analyze_catchment(_aseasonal(), phase_model="rule_based", n_bootstrap=40)

    assert result.route == "event_characterisation"
    assert result.state is None
    assert result.hydro_years.empty


def test_marginal_route_keeps_imposed_windows_separate_from_robust_state():
    result = analyze_catchment(_marginal(), phase_model="rule_based", n_bootstrap=40)

    assert result.route == "fixed_climatological_window"
    assert result.state is None
    assert result.hydro_years["boundary_basis"].eq("imposed_fixed_window").all()


def test_marginal_fixed_window_covers_every_climatological_peak_phase():
    """Task 5 contract: every marginal peak phase gets an imposed fixed window.

    Earlier tropical-only geometry dropped Mar-Sep peaks to events-only. Cyclic
    HydroYearConfig windows must cover all twelve calendar peaks, including
    mid-year (e.g. June).
    """
    for peak_month in range(1, 13):
        # phase_wander keeps every calendar peak inside the marginal band;
        # re-seed per phase so residual noise does not correlate across cases.
        result = analyze_catchment(
            _marginal(
                peak_month=peak_month, seed=300 + peak_month, phase_wander=True
            ),
            phase_model="rule_based",
            n_bootstrap=40,
        )
        assert result.regime.regime == "marginal", (
            f"peak={peak_month}: expected marginal, got {result.regime.regime} "
            f"(SNR={result.regime.amplitude_snr}, "
            f"IQR={result.regime.peak_phase_iqr_months})"
        )
        assert result.route == "fixed_climatological_window", peak_month
        assert result.state is None, peak_month
        assert not result.hydro_years.empty, peak_month
        assert result.hydro_years["boundary_basis"].eq("imposed_fixed_window").all(), (
            peak_month
        )
        # Climatological peak should land near the requested phase (wrap-aware
        # circular distance <= 1 month tolerates discrete-month noise).
        observed = int(result.climatological_peak_month)
        delta = min((observed - peak_month) % 12, (peak_month - observed) % 12)
        assert delta <= 1, (peak_month, observed)


def test_peak_and_trough_withheld_for_aseasonal():
    result = analyze_catchment(_aseasonal())
    assert result.climatological_peak_month is None
    assert result.climatological_trough_month is None


def test_summary_row_is_flat_and_serialisable():
    """One row per catchment, for the cross-catchment summary table."""
    row = analyze_catchment(_seasonal()).summary_row(name="test_catchment")
    assert row["catchment"] == "test_catchment"
    assert row["regime"] == "seasonal"
    assert row["route"] == "per_year_detection"
    assert isinstance(row["n_hydro_years"], int)
    assert {
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
    } <= set(row)
    assert row["peak_timing_concentration"] == round(
        analyze_catchment(_seasonal()).regime.peak_timing_concentration, 3
    )
    assert row["peak_phase_iqr_months"] == round(
        analyze_catchment(_seasonal()).regime.peak_phase_iqr_months, 2
    )
    for value in row.values():
        assert not isinstance(value, (list, dict, tuple, pd.DataFrame))
