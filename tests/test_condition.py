import numpy as np
import pandas as pd

from hydroseason._condition import (
    classify_annual_surface_water_condition,
    compute_monthly_surface_water_condition,
)


def _annual():
    years = np.arange(2000, 2012)
    return pd.DataFrame(
        {
            "hy_year": years,
            "status": "complete",
            "hy_end": pd.to_datetime([f"{year}-09-01" for year in years]),
            "peak_extent_pct": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120],
            "trough_extent_pct": [1, 12, 3, 4, 5, 6, 7, 8, 9, 10, 2, 11],
        }
    )


def test_recharge_and_refuge_axes_produce_all_four_joint_states():
    result = classify_annual_surface_water_condition(_annual())
    by_year = result.set_index("hy_year")["annual_condition"]
    assert by_year[2000] == "dry_low_refuge"
    assert by_year[2001] == "buffered_low_recharge"
    assert by_year[2010] == "recharged_then_contracting"
    assert by_year[2011] == "wet_persistent"
    assert result.loc[result["hy_year"] == 2000, "peak_percentile"].item() == 0.0
    assert result.loc[result["hy_year"] == 2011, "peak_percentile"].item() == 100.0


def test_consecutive_counts_only_follow_joint_extremes():
    annual = _annual()
    annual.loc[annual["hy_year"].isin([2002, 2003]), ["peak_extent_pct", "trough_extent_pct"]] = [5, 0]
    result = classify_annual_surface_water_condition(annual)
    assert result.loc[result["hy_year"] == 2003, "consecutive_dry_cycles"].item() >= 2


def test_provisional_boundary_excluded_from_baseline_blocks_activation():
    # Ten otherwise-complete cycles, but one carries a provisional trough
    # boundary. Because a provisional boundary may not anchor the baseline, only
    # nine cycles remain eligible -- below min_baseline_cycles (10) -- so the
    # public condition must stay insufficient_baseline rather than activating.
    annual = _annual().iloc[:10].copy()
    annual["boundary_status"] = "confirmed"
    annual.loc[annual["hy_year"] == 2005, "boundary_status"] = "provisional"
    result = classify_annual_surface_water_condition(annual)
    assert set(result["annual_condition"]) == {"insufficient_baseline"}
    assert set(result["recharge_condition"]) == {"insufficient_baseline"}
    assert set(result["refuge_condition"]) == {"insufficient_baseline"}


def test_all_confirmed_boundaries_activate_baseline():
    # Sanity counterpart: the same ten cycles with every boundary confirmed do
    # reach the baseline threshold and produce real (non-insufficient) labels,
    # proving the gate above blocks specifically on the provisional boundary.
    annual = _annual().iloc[:10].copy()
    annual["boundary_status"] = "confirmed"
    result = classify_annual_surface_water_condition(annual)
    assert (result["annual_condition"] != "insufficient_baseline").any()


def test_low_variability_suppresses_public_labels_but_keeps_percentiles():
    result = classify_annual_surface_water_condition(_annual(), low_variability=True)
    assert result["peak_percentile"].notna().all()
    assert set(result["annual_condition"]) == {"not_applicable_low_variability"}


def test_monthly_condition_uses_same_calendar_month_and_fixed_reference():
    index = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    frame = pd.DataFrame(
        {"extent_pct": index.year - 1999 + index.month / 100, "invalid_pct": 0.0},
        index=index,
    )
    result = compute_monthly_surface_water_condition(
        frame, reference_start="2000-01-01", reference_end="2009-12-01"
    )
    row = result.loc["2011-01-01"]
    assert row["reference_n"] == 10
    assert row["reference_median_pct"] == 5.51
    assert row["anomaly_pct"] == 6.5
    assert row["condition_percentile"] == 100.0


def test_low_quality_month_has_no_condition_rank():
    frame = pd.DataFrame(
        {"extent_pct": [10.0, 20.0], "invalid_pct": [0.0, 50.0]},
        index=pd.to_datetime(["2000-01-01", "2001-01-01"]),
    )
    result = compute_monthly_surface_water_condition(frame)
    assert pd.isna(result.loc["2001-01-01", "condition_percentile"])


def _annual_n(n_years, peak, trough, start=2000):
    years = np.arange(start, start + n_years)
    return pd.DataFrame(
        {
            "hy_year": years,
            "status": "complete",
            "boundary_status": "confirmed",
            "hy_end": pd.to_datetime([f"{year}-09-01" for year in years]),
            "peak_extent_pct": peak,
            "trough_extent_pct": trough,
        }
    )


def test_rolling_baseline_phases_label_every_year_past_floor():
    n = 21
    rng = np.random.default_rng(0)
    peak = 50 + rng.normal(0, 5, n)
    trough = 10 + rng.normal(0, 2, n)
    annual = _annual_n(n, peak, trough)
    result = classify_annual_surface_water_condition(
        annual, reference="rolling", rolling_window_cycles=10, rolling_min_cycles=5
    ).set_index("hy_year")
    # First 5 rows (0..4 prior cycles) are below the floor.
    assert (result["baseline_mode"].iloc[:5] == "insufficient").all()
    # Rows with 5..9 prior cycles are the expanding phase.
    assert (result["baseline_mode"].iloc[5:10] == "expanding").all()
    assert result["baseline_uncertain"].iloc[5:10].all()
    # Rows with >=10 prior cycles are the rolling phase, window pinned to 10.
    assert (result["baseline_mode"].iloc[10:] == "rolling").all()
    assert (result["baseline_n"].iloc[10:] == 10).all()
    assert not result["baseline_uncertain"].iloc[10:].any()
    # Every row past the floor has a real (non-insufficient) label.
    assert (result["annual_condition"].iloc[5:] != "insufficient_baseline").all()


def test_rolling_baseline_forgets_pre_shift_regime():
    # 25 years: peak ~30 for years 0..14, steps up to ~70 for years 15..24.
    n = 25
    peak = np.concatenate([np.full(15, 30.0), np.full(10, 70.0)])
    trough = np.full(n, 5.0)
    annual = _annual_n(n, peak, trough)
    result = classify_annual_surface_water_condition(
        annual, reference="rolling", rolling_window_cycles=10, rolling_min_cycles=5
    ).set_index("hy_year")
    # By the last year (2024), all 10 prior cycles (2014..2023 -> positions 14..23)
    # are post-shift-valued (position 14 is still 30, positions 15..23 are 70), and
    # 2024's own peak (70) matches the new regime -> should NOT read as "high".
    # Use a fully-past-shift year: 2024 has prior positions 14..23; test the median.
    assert result.loc[2024, "baseline_mode"] == "rolling"
    # A clean post-shift year whose window is entirely post-shift: position 25 would
    # be needed for a pure window, but with n=25 the last row's window still holds
    # one pre-shift value (pos 14). Assert the softer, still-meaningful claim:
    # the last year is NOT labelled "high" (pre-shift baseline would have made 70 high).
    assert result.loc[2024, "recharge_condition"] != "high"
