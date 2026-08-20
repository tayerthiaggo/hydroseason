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
    result = compute_monthly_surface_water_condition(frame, quality_policy="exclude")
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
    # By the last year (2024), the trailing-10 window (2014..2023 -> positions
    # 14..23) holds 9 post-shift values (70) and only 1 pre-shift value (30 at
    # position 14), so its median is already 70 -- the baseline has adapted to
    # the new regime despite one straggling pre-shift cycle still in view.
    # 2024's own peak (70) matches that median -> should NOT read as "high".
    assert result.loc[2024, "baseline_mode"] == "rolling"
    # A clean post-shift year whose window is entirely post-shift: position 25 would
    # be needed for a pure window, but with n=25 the last row's window still holds
    # one pre-shift value (pos 14). Assert the softer, still-meaningful claim:
    # the last year is NOT labelled "high" (pre-shift baseline would have made 70 high).
    assert result.loc[2024, "recharge_condition"] != "high"


def test_noise_floor_hedge_downgrades_within_band_only():
    # 12 confirmed years (2000..2011); year 2011 peak (120) is the record high -> "high" unhedged.
    annual = _annual().copy()
    annual["boundary_status"] = "confirmed"
    # Large noise_pp so the peak's departure from baseline median is inside the band.
    big = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5, noise_pp=1000.0
    ).set_index("hy_year")
    assert big.loc[2011, "recharge_condition"] == "high"          # unhedged unchanged
    assert big.loc[2011, "recharge_condition_qualified"] == "typical_uncertain"
    assert big.loc[2011, "noise_floor_pp"] == 1000.0
    # Small noise_pp: real departure survives -> qualified equals unhedged.
    small = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5, noise_pp=0.01
    ).set_index("hy_year")
    assert small.loc[2011, "recharge_condition_qualified"] == "high"
    # None: hedge skipped, qualified mirrors unhedged, noise_floor_pp is NaN.
    none = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5
    ).set_index("hy_year")
    assert none.loc[2011, "recharge_condition_qualified"] == none.loc[2011, "recharge_condition"]
    assert pd.isna(none.loc[2011, "noise_floor_pp"])


def test_timing_confidence_from_amplitude_vs_noise():
    annual = _annual().copy()
    annual["boundary_status"] = "confirmed"
    # amplitudes (peak-trough) for _annual(): 9,8,27,36,45,54,63,72,81,90,108,109
    result = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5, noise_pp=10.0, timing_amplitude_k=2.0
    ).set_index("hy_year")
    # 2000 amplitude 9 < 2*10=20 -> low; 2001 amplitude 8 < 20 -> low
    assert result.loc[2000, "timing_confidence"] == "low"
    assert result.loc[2001, "timing_confidence"] == "low"
    # 2003 amplitude 36 >= 20 -> high
    assert result.loc[2003, "timing_confidence"] == "high"
    # noise_pp None -> unknown
    unknown = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5
    ).set_index("hy_year")
    assert (unknown["timing_confidence"] == "unknown").all()


def test_existing_columns_unchanged_for_full_record_mode():
    # The default (full_record) call must yield the same pre-existing columns
    # it always did; new columns are purely additive.
    annual = _annual().copy()
    annual["boundary_status"] = "confirmed"
    result = classify_annual_surface_water_condition(annual, min_baseline_cycles=5)
    # Pre-existing columns still present and populated.
    for col in ["recharge_condition", "refuge_condition", "annual_condition",
                "peak_percentile", "trough_percentile",
                "consecutive_dry_cycles", "consecutive_wet_cycles"]:
        assert col in result.columns
    # New columns are additive.
    for col in ["baseline_mode", "baseline_n", "baseline_uncertain",
                "noise_floor_pp", "recharge_condition_qualified",
                "refuge_condition_qualified", "annual_condition_qualified",
                "timing_confidence"]:
        assert col in result.columns
    # With noise_pp None (default), all three qualified columns mirror their
    # unhedged counterparts exactly.
    assert (result["recharge_condition_qualified"] == result["recharge_condition"]).all()
    assert (result["refuge_condition_qualified"] == result["refuge_condition"]).all()
    assert (result["annual_condition_qualified"] == result["annual_condition"]).all()
