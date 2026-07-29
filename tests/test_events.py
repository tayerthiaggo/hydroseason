import numpy as np
import pandas as pd

from hydroseason._events import extract_water_events


def _frame(values, start="1990-01-01"):
    index = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.asarray(values, dtype=float), "invalid_pct": 0.0},
        index=index,
    )


def test_isolated_pulse_is_one_event_with_correct_span():
    values = [0.1] * 12 + [2.0, 3.0, 2.0] + [0.1] * 12
    result = extract_water_events(_frame(values))
    assert len(result.events) == 1
    event = result.events.iloc[0]
    assert event["duration_months"] == 3
    assert event["peak_extent_pct"] == 3.0
    assert event["start"] == pd.Timestamp("1991-01-01")
    assert event["end"] == pd.Timestamp("1991-03-01")


def test_two_separated_pulses_are_two_events():
    values = [0.1] * 8 + [3.0, 3.0] + [0.1] * 10 + [3.0, 3.0] + [0.1] * 8
    result = extract_water_events(_frame(values))
    assert len(result.events) == 2


def test_hysteresis_keeps_a_dipping_pulse_as_one_event():
    """A single mid-event dip below the start threshold must not split one
    flood into two. Entry and exit thresholds differ for exactly this reason.
    """
    values = [0.1] * 10 + [3.0, 3.0, 1.2, 3.0, 3.0] + [0.1] * 10
    result = extract_water_events(_frame(values))
    assert len(result.events) == 1
    assert result.events.iloc[0]["duration_months"] == 5


def test_low_spells_are_reported_with_duration():
    """Dry spells are runs below the dry threshold, not merely gaps between
    events, so they are counted wherever the record sits low."""
    values = [0.5] * 30 + [0.05] * 20 + [0.5] * 10 + [3.0, 3.0]
    result = extract_water_events(_frame(values))
    assert len(result.low_spells) >= 1
    assert int(result.low_spells["duration_months"].max()) == 20


def test_longest_dry_spell_matches_the_spell_table():
    values = [0.5] * 30 + [0.05] * 20 + [0.5] * 10 + [3.0, 3.0]
    result = extract_water_events(_frame(values))
    assert result.summary["longest_low_spell_months"] == int(
        result.low_spells["duration_months"].max()
    )


def test_flat_record_yields_no_events():
    result = extract_water_events(_frame([0.5] * 60))
    assert len(result.events) == 0
    assert result.summary["n_events"] == 0


def test_event_magnitude_scales_with_size_and_duration():
    small = extract_water_events(_frame([0.1] * 12 + [2.0] + [0.1] * 12))
    big = extract_water_events(_frame([0.1] * 12 + [2.0, 2.0, 2.0] + [0.1] * 12))
    assert big.events.iloc[0]["magnitude_pp_months"] > small.events.iloc[0]["magnitude_pp_months"]


def test_gaps_do_not_bridge_two_events():
    """A missing month must break an event rather than silently joining the
    months either side of it into one long episode."""
    values = [0.1] * 8 + [3.0, np.nan, 3.0] + [0.1] * 8
    result = extract_water_events(_frame(values))
    assert len(result.events) == 2


def test_recurrence_interval_reported_when_multiple_events():
    values = ([0.1] * 10 + [3.0, 3.0]) * 4
    result = extract_water_events(_frame(values))
    assert result.summary["median_recurrence_months"] > 0


def test_thresholds_are_recorded_for_audit():
    result = extract_water_events(_frame([0.1] * 12 + [3.0] + [0.1] * 12))
    assert "enter_threshold_pct" in result.summary
    assert "exit_threshold_pct" in result.summary
    assert result.summary["exit_threshold_pct"] <= result.summary["enter_threshold_pct"]
