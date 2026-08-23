import json
from dataclasses import replace

import numpy as np
import pandas as pd

from hydroseason._boundary_recoverability import RecoverabilityThresholds
from hydroseason._catchment import analyze_catchment
from hydroseason._evidence import EvidenceThresholds
from hydroseason._regime import assess_water_regime
from hydroseason.hydrological_state import HydrologicalStateResult

EVIDENCE = EvidenceThresholds(
    seasonal_cv_skill=0.3,
    periodicity_alpha=0.05,
    amplitude_noise_ratio=1.0,
    mode_min_frequency=0.60,
    mode_min_separation_months=2,
    strong_timing_concentration=0.70,
    weak_timing_concentration=0.40,
    min_timing_years=10,
)
RECOVERABILITY = RecoverabilityThresholds(
    min_years=5,
    min_coverage=0.80,
    min_within_1_month=0.80,
    within_1_month_wilson_floor=0.50,
    max_p90_error_months=2.0,
    admit_insufficient_drift=False,
)


def _calibrated(extent, **kwargs):
    kwargs.setdefault("evidence_thresholds", EVIDENCE)
    kwargs.setdefault("recoverability_thresholds", RECOVERABILITY)
    return analyze_catchment(extent, **kwargs)


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
    percentage_cycle = np.array([1, 2, 3, 4, 5, 10, 15, 20, 40, 80, 100, 10])
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
    full_result = _calibrated(full_aoi, phase_scheme="four_phase", n_bootstrap=40)
    historical_result = _calibrated(historical, phase_scheme="four_phase", n_bootstrap=40)

    assert full_result.regime.regime == historical_result.regime.regime
    assert full_result.route == historical_result.route
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
    assert not full_result.hydro_years.empty
    assert not historical_result.hydro_years.empty
    selection_cols = [
        "hy_year",
        "status",
        "hy_start",
        "hy_end",
        "peak_month",
        "trough_month",
        "peak_extent_pct",
        "trough_extent_pct",
        "boundary_basis",
    ]
    pd.testing.assert_frame_equal(
        full_result.hydro_years[selection_cols], historical_result.hydro_years[selection_cols]
    )
    assert not full_result.events.events.empty
    assert not full_result.events.low_spells.empty
    pd.testing.assert_frame_equal(full_result.events.events, historical_result.events.events)
    pd.testing.assert_frame_equal(full_result.events.low_spells, historical_result.events.low_spells)


def _marginal(years=30, seed=7, peak_month=11, *, phase_wander=False):
    """Marginal-amplitude cycle peaking at ``peak_month`` (1..12)."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    if not phase_wander:
        cycle = 0.45 + 0.16 * np.cos(
            2 * np.pi * (np.arange(12) - (peak_month - 1)) / 12
        )
        values = np.tile(cycle, years) + rng.normal(0, 0.16, 12 * years)
    else:
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
    result = _calibrated(_seasonal())
    assert result.regime.regime == "seasonal"
    assert result.route == "per_year_detection"
    assert not result.hydro_years.empty
    assert "reproducible" in result.route_reason.lower()


def test_seasonal_record_with_unstable_trough_routes_to_fixed_window():
    result = _calibrated(_timing_route_record("unstable_trough"), n_bootstrap=40)

    assert result.regime.supports_per_year_boundaries is False
    assert result.regime.supports_fixed_window is True
    assert result.route == "fixed_climatological_window"
    assert (result.hydro_years["boundary_basis"] == "imposed_fixed_window").all()


def test_concentrated_nonuniform_marginal_routes_to_fixed_window():
    result = _calibrated(_timing_route_record("concentrated_nonuniform"), n_bootstrap=40)

    assert result.route == "fixed_climatological_window"
    assert (result.hydro_years["boundary_basis"] == "imposed_fixed_window").all()


def test_diffuse_uniform_marginal_uses_event_characterisation():
    result = _calibrated(_diffuse_uniform_marginal_record(), n_bootstrap=40)

    assert result.route == "event_characterisation"


def test_per_year_boundary_failure_falls_back_to_event_characterisation(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("dynamic detector rejected the record")

    monkeypatch.setattr("hydroseason._catchment.analyze_hydrological_state", fail)

    result = _calibrated(_seasonal(), n_bootstrap=40)

    assert result.route == "event_characterisation"
    assert result.hydro_years.empty
    assert "detection failed" in result.route_reason.lower()


def test_empty_per_year_result_falls_back_to_event_characterisation(monkeypatch):
    baseline = _calibrated(_seasonal(), n_bootstrap=40)
    empty_state = replace(baseline.state, hydro_years=pd.DataFrame())
    monkeypatch.setattr(
        "hydroseason._catchment.analyze_hydrological_state",
        lambda *args, **kwargs: empty_state,
    )

    result = _calibrated(_seasonal(), n_bootstrap=40)

    assert result.route == "event_characterisation"
    assert result.hydro_years.empty
    assert "returned no hydrological years" in result.route_reason.lower()


def test_catchment_threads_existing_bootstrap_controls_to_regime_assessment():
    extent = _marginal()
    direct = assess_water_regime(extent, n_bootstrap=40, random_state=11)
    routed = analyze_catchment(extent, n_bootstrap=40, random_state=11)

    assert routed.regime.peak_timing_concentration_ci_low == direct.peak_timing_concentration_ci_low
    assert routed.regime.peak_timing_concentration_ci_high == direct.peak_timing_concentration_ci_high
    assert routed.regime.peak_timing_uniformity_p == direct.peak_timing_uniformity_p


def test_marginal_routes_to_events_without_recoverable_boundaries():
    result = _calibrated(_diffuse_uniform_marginal_record())
    assert result.route == "event_characterisation"
    assert result.hydro_years.empty


def test_aseasonal_routes_to_events_only_and_emits_no_hydro_years():
    result = _calibrated(_aseasonal())
    assert result.regime.regime == "aseasonal"
    assert result.route == "event_characterisation"
    assert result.hydro_years.empty


def test_every_route_returns_events():
    """Event descriptors are always available, whatever the regime -- they are
    the one view that never depends on a cycle existing."""
    for frame in (_seasonal(), _marginal(), _aseasonal()):
        assert _calibrated(frame).events is not None


def test_route_is_recorded_with_a_reason_for_audit():
    result = _calibrated(_aseasonal())
    assert result.route_reason
    assert "aseasonal" in result.route_reason.lower()


def test_analysis_never_raises_on_a_record_with_no_detectable_cycle():
    """The whole point of routing: a record the detector cannot handle must
    return a usable result rather than propagate an exception."""
    result = _calibrated(_aseasonal())
    assert result.route == "event_characterisation"
    assert result.events.summary["n_events"] >= 0


def test_short_record_is_routed_without_error():
    short = _seasonal(years=3)
    result = _calibrated(short)
    assert result.regime.regime == "insufficient_record"
    assert result.route == "insufficient_record"
    assert result.hydro_years.empty


def test_seasonal_years_are_marked_as_detected():
    result = _calibrated(_seasonal())
    assert (result.hydro_years["boundary_basis"] == "detected_per_year").all()


def test_seasonal_route_uses_robust_dynamic_state():
    result = _calibrated(_seasonal(), phase_scheme="four_phase", n_bootstrap=40)

    assert result.route == "per_year_detection"
    assert isinstance(result.state, HydrologicalStateResult)
    assert result.state.config.detector == "robust_extrema"
    pd.testing.assert_frame_equal(result.hydro_years, result.state.hydro_years)
    assert result.hydro_years["boundary_basis"].eq("detected_per_year").all()
    assert result.state.monthly_phase["phase_method"].eq("four_phase").any()


def test_analyze_catchment_phase_toggle_never_changes_public_annual_frame():
    extent = _seasonal()
    none_result = _calibrated(extent, phase_scheme="none", n_bootstrap=40)
    two_phase_result = _calibrated(extent, phase_scheme="two_phase", n_bootstrap=40)
    four_phase_result = _calibrated(extent, phase_scheme="four_phase", n_bootstrap=40)
    assert not none_result.hydro_years.empty
    pd.testing.assert_frame_equal(none_result.hydro_years, two_phase_result.hydro_years)
    pd.testing.assert_frame_equal(none_result.hydro_years, four_phase_result.hydro_years)


def test_aseasonal_route_never_constructs_state_or_years():
    result = _calibrated(_aseasonal(), phase_scheme="two_phase", n_bootstrap=40)

    assert result.route == "event_characterisation"
    assert result.state is None
    assert result.hydro_years.empty


def test_peak_and_trough_withheld_for_aseasonal():
    result = _calibrated(_aseasonal())
    assert result.climatological_peak_month is None
    assert result.climatological_trough_month is None


def test_summary_row_has_canonical_schema_and_rounds_timing_diagnostics():
    """One row has a stable flat schema with precise, JSON-safe timing evidence."""
    analysis = _calibrated(_seasonal())
    timing_regime = replace(
        analysis.regime,
        peak_timing_concentration=0.1236,
        peak_timing_concentration_ci_low=0.2346,
        peak_timing_concentration_ci_high=0.3456,
        peak_timing_uniformity_p=0.4566,
        peak_phase_iqr_months=1.236,
        trough_timing_concentration=0.5676,
        trough_timing_concentration_ci_low=0.6786,
        trough_timing_concentration_ci_high=0.7896,
        trough_timing_uniformity_p=0.8916,
        trough_phase_iqr_months=2.344,
        n_timing_years=17,
    )
    row = replace(analysis, regime=timing_regime).summary_row(name="test_catchment")

    assert list(row) == [
        "catchment",
        "decision_policy",
        "regime",
        "route",
        "amplitude_snr",
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
        "n_usable_years",
        "n_usable_months",
        "n_hydro_years",
        "boundary_basis",
        "climatological_peak_month",
        "climatological_trough_month",
        "n_wet_events",
        "median_event_duration_months",
        "longest_low_spell_months",
        "median_recurrence_months",
        "years_without_wet_event",
        "challenger_route",
        "challenger_regime",
        "challenger_annual_cycle_evidence",
        "challenger_boundary_recoverability",
        "challenger_seasonal_cv_skill",
    ]
    assert {
        "peak_timing_concentration": 0.124,
        "peak_timing_concentration_ci_low": 0.235,
        "peak_timing_concentration_ci_high": 0.346,
        "peak_timing_uniformity_p": 0.457,
        "peak_phase_iqr_months": 1.24,
        "trough_timing_concentration": 0.568,
        "trough_timing_concentration_ci_low": 0.679,
        "trough_timing_concentration_ci_high": 0.79,
        "trough_timing_uniformity_p": 0.892,
        "trough_phase_iqr_months": 2.34,
        "n_timing_years": 17,
    }.items() <= row.items()
    assert json.dumps(row)
    for value in row.values():
        assert not isinstance(value, (list, dict, tuple, pd.DataFrame))


def test_catchment_analysis_exposes_decision_policy_and_isolated_challenger():
    result = _calibrated(_seasonal(), n_bootstrap=40)
    assert result.decision_policy == "established_0_1_1"
    assert result.public_route == "per_year_detection"
    assert result.challenger is not None
    assert result.challenger.proposed_route in {"per_year_detection", "event_characterisation"}


def test_catchment_analysis_routes_independently_of_challenger_failure(monkeypatch):
    def fail_challenger(*args, **kwargs):
        raise RuntimeError("challenger crashed")

    monkeypatch.setattr("hydroseason._regime.assess_challenger", fail_challenger)
    result = analyze_catchment(_seasonal(), n_bootstrap=40)
    assert result.route == "per_year_detection"
    assert result.decision_policy == "established_0_1_1"
    assert result.challenger.status == "failed"
