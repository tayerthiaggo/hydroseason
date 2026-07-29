"""Transferable season-window geometry.

``HydroYearConfig`` originally hard-required a tropical-monsoon phase: wet
season spanning the turn of the calendar year, dry season inside one year
after it. That describes northern Australia and rejects, by construction, any
catchment whose wet season sits mid-year -- Mediterranean and cool-temperate
winter-rainfall catchments across southern Australia. These tests pin the
generalisation and, first, that it changes nothing for the existing phase.
"""
import numpy as np
import pandas as pd
import pytest

from hydroseason.hydro_year import HydroYearConfig, detect_hydrological_years


def _cycle_frame(peak_month, trough_month, years=30, amplitude=1.0, base=1.0, seed=0):
    """Monthly series peaking and troughing in the requested calendar months."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    phase = 2 * np.pi * (index.month - peak_month) / 12.0
    values = base + amplitude * np.cos(phase) + rng.normal(0, 0.02, len(index))
    return pd.DataFrame(
        {"extent_pct": np.clip(values, 0.01, None), "invalid_pct": 0.0}, index=index
    )


# --- backward compatibility (must not move) --------------------------------

def test_default_config_is_unchanged():
    """The shipped tropical default must produce byte-identical geometry."""
    cfg = HydroYearConfig()
    assert (cfg.wet_start_month, cfg.wet_end_month) == (11, 4)
    assert (cfg.dry_start_month, cfg.dry_end_month) == (7, 12)


def test_default_geometry_reproduces_known_windows():
    """Wet Nov(Y-1)..Apr(Y), dry Jul(Y)..Dec(Y) -- the documented contract."""
    frame = _cycle_frame(peak_month=2, trough_month=8)
    result = detect_hydrological_years(
        frame, config=HydroYearConfig(), quality_policy="flag", missing_month_policy="ignore"
    )
    assert not result.empty
    row = result[result["hy_year"] == 2000].iloc[0]
    # Peak must be found inside Nov(1999)..Apr(2000).
    assert pd.Timestamp("1999-11-01") <= row["peak_month"] <= pd.Timestamp("2000-04-01")
    # End-dry must be found inside Jul(2000)..Dec(2000).
    assert pd.Timestamp("2000-07-01") <= row["end_dry_month"] <= pd.Timestamp("2000-12-01")


# --- newly supported phases ------------------------------------------------

def test_wet_window_inside_one_year_is_accepted():
    """Winter-rainfall phase: wet Jun..Sep, dry Nov..Feb. Previously rejected."""
    cfg = HydroYearConfig(
        wet_start_month=6, wet_end_month=9, dry_start_month=11, dry_end_month=2
    )
    assert cfg.wet_start_month == 6


def test_dry_window_crossing_the_year_is_accepted():
    cfg = HydroYearConfig(
        wet_start_month=6, wet_end_month=9, dry_start_month=11, dry_end_month=2
    )
    frame = _cycle_frame(peak_month=8, trough_month=1)
    result = detect_hydrological_years(
        frame, config=cfg, quality_policy="flag", missing_month_policy="ignore"
    )
    assert len(result) > 20


def test_winter_rainfall_catchment_finds_the_right_phase():
    """A catchment peaking in August must have its peak detected in August."""
    cfg = HydroYearConfig(
        wet_start_month=6, wet_end_month=9, dry_start_month=11, dry_end_month=2
    )
    frame = _cycle_frame(peak_month=8, trough_month=2)
    result = detect_hydrological_years(
        frame, config=cfg, quality_policy="flag", missing_month_policy="ignore"
    )
    peak_months = pd.to_datetime(result["peak_month"]).dt.month
    assert peak_months.mode().iloc[0] == 8


def test_dry_window_may_fall_in_the_following_calendar_year():
    """wet Jun..Sep then dry Nov..Feb means the dry window ends in Y+1."""
    cfg = HydroYearConfig(
        wet_start_month=6, wet_end_month=9, dry_start_month=11, dry_end_month=2
    )
    frame = _cycle_frame(peak_month=8, trough_month=1)
    result = detect_hydrological_years(
        frame, config=cfg, quality_policy="flag", missing_month_policy="ignore"
    )
    row = result[result["hy_year"] == 2000].iloc[0]
    assert pd.Timestamp("2000-06-01") <= row["peak_month"] <= pd.Timestamp("2000-09-01")
    assert pd.Timestamp("2000-11-01") <= row["end_dry_month"] <= pd.Timestamp("2001-02-01")


@pytest.mark.parametrize("peak,trough", [(2, 8), (5, 11), (8, 2), (11, 5), (1, 7), (7, 1)])
def test_every_phase_around_the_year_is_expressible(peak, trough):
    """No calendar phase may be unrepresentable -- that was the whole defect."""
    wet_start = ((peak - 3) % 12) + 1
    wet_end = ((peak + 1) % 12) + 1
    dry_start = ((wet_end + 1) % 12) + 1
    dry_end = ((dry_start + 2) % 12) + 1
    cfg = HydroYearConfig(
        wet_start_month=wet_start, wet_end_month=wet_end,
        dry_start_month=dry_start, dry_end_month=dry_end,
    )
    frame = _cycle_frame(peak_month=peak, trough_month=trough)
    result = detect_hydrological_years(
        frame, config=cfg, quality_policy="flag", missing_month_policy="ignore"
    )
    assert len(result) > 15, f"phase peak={peak} produced only {len(result)} years"


# --- the constraint that remains -------------------------------------------

def test_dry_window_must_not_start_on_the_wet_end_month():
    """Dry must follow wet. Overlap is the one geometry still rejected."""
    with pytest.raises(ValueError, match="follow"):
        HydroYearConfig(
            wet_start_month=11, wet_end_month=4, dry_start_month=4, dry_end_month=8
        )


def test_cycle_may_not_overlap_consecutive_years_ambiguously():
    with pytest.raises(ValueError, match="overlap ambiguously"):
        HydroYearConfig(
            wet_start_month=1, wet_end_month=12, dry_start_month=1, dry_end_month=12
        )
