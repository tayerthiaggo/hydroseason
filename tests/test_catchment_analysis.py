import numpy as np
import pandas as pd

from hydroseason._catchment import analyze_catchment
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


def _marginal(years=30, seed=7):
    rng = np.random.default_rng(seed)
    cycle = 0.45 + 0.16 * np.cos(2 * np.pi * (np.arange(12) - 10) / 12)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    values = np.tile(cycle, years) + rng.normal(0, 0.16, 12 * years)
    return pd.DataFrame(
        {"extent_pct": np.clip(values, 0, None), "invalid_pct": 0.0}, index=index
    )


# --- routing runs without prompting ---------------------------------------

def test_seasonal_routes_to_per_year_detection():
    result = analyze_catchment(_seasonal())
    assert result.regime.regime == "seasonal"
    assert result.route == "per_year_detection"
    assert not result.hydro_years.empty


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
    for value in row.values():
        assert not isinstance(value, (list, dict, tuple, pd.DataFrame))
