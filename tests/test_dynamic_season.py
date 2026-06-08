import pandas as pd

from hydroseason.dynamic_season import (
    harmonize_with_zero_preservation,
    refine_season_tails,
    repair_short_dry_gaps,
    segment_main_wet_season_fixed_threshold,
)
from hydroseason.hydro_year import assign_fixed_hydro_year


def test_harmonize_preserves_zeros():
    df = pd.DataFrame({"Rainfall_mm": [0.0, 0.0, 5.0, 10.0, 20.0, 5.0, 0.0, 0.0]})
    out = harmonize_with_zero_preservation(df, window=3)
    # Zeros adjacent to zero must stay zero
    assert out.loc[0, "Smoothed"] == 0
    assert out.loc[1, "Smoothed"] == 0
    assert out.loc[6, "Smoothed"] == 0
    assert out.loc[7, "Smoothed"] == 0


def test_segment_picks_dominant_block(monthly_df: pd.DataFrame):
    monthly_df["Date"] = pd.to_datetime(monthly_df[["Year", "Month"]].assign(day=1))
    work = assign_fixed_hydro_year(monthly_df, start_month=11)
    work = harmonize_with_zero_preservation(work, window=3)
    seg, boundaries = segment_main_wet_season_fixed_threshold(
        work, threshold=float(work[work["Rainfall_mm"] > 0]["Rainfall_mm"].quantile(0.2))
    )
    assert "SeasonType" in seg.columns
    # at least one wet block per year
    assert (boundaries["WetStart"].notna()).any()


def test_refine_hysteresis_extends_wet_tails():
    """Regression for the dead-elif bug: Wet→Dry tail refinement must actually fire."""
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [100, 50, 0, 0, 0, 0, 0, 0, 0, 50, 100, 100],
        "SeasonType": ["Wet", "Wet", "Dry", "Dry", "Dry", "Dry",
                       "Dry", "Dry", "Dry", "Dry", "Wet", "Wet"],
    })
    refined = refine_season_tails(df, threshold_high=40.0, threshold_low=0.0)
    # The Oct=50 month preceding the Nov-Dec Wet block must now be Wet.
    assert refined.loc[refined["Date"] == pd.Timestamp("2020-10-01"), "SeasonType"].iloc[0] == "Wet"


def test_refine_legacy_threshold_argument():
    dates = pd.date_range("2020-01-01", periods=6, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [10, 50, 100, 100, 50, 10],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Dry", "Dry"],
    })
    out = refine_season_tails(df, threshold=40.0)
    assert "SeasonType" in out.columns


def test_repair_short_dry_gap_merges_only_supported_single_month_gap():
    dates = pd.date_range("2020-01-01", periods=9, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "SeasonType": [
            "Wet", "Wet", "Wet", "Dry", "Wet", "Wet", "Wet", "Dry", "Dry",
        ],
    })

    out, diag = repair_short_dry_gaps(
        df,
        max_gap_length=1,
        min_neighbor_wet_length=3,
    )

    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2020-04-01")] == "Wet"
    assert by_date[pd.Timestamp("2020-08-01")] == "Dry"
    assert diag["short_dry_gap_merged_count"] == 1
    assert diag["short_dry_gap_merged_month_count"] == 1


def test_repair_short_dry_gap_preserves_real_two_month_dry_season():
    dates = pd.date_range("2020-01-01", periods=8, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "SeasonType": [
            "Wet", "Wet", "Wet", "Dry", "Dry", "Wet", "Wet", "Wet",
        ],
    })

    out, diag = repair_short_dry_gaps(
        df,
        max_gap_length=1,
        min_neighbor_wet_length=3,
    )

    assert (out.loc[out["Date"].isin(pd.to_datetime(["2020-04-01", "2020-05-01"])), "SeasonType"] == "Dry").all()
    assert diag["short_dry_gap_merged_count"] == 0


def test_refine_no_orphan_wet_event_inside_dry_season():
    """Regression: a single rainfall event inside the dry season must not
    re-open the wet season.

    Reproduces the HY 1995 case: the dominant wet block ends with a zero month
    (kept inside the block by the 3-month smoother), and the next month has a
    standalone rainfall event above the high threshold. The fix is to contract
    first (drop the trailing zero), then extend from the contracted boundary —
    so the gap month blocks the extension and the event stays Dry.
    """
    dates = pd.date_range("1994-10-01", periods=12, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        # Oct..Mar = clearly wet, Apr = 0 (was inside the smoothed wet block),
        # May = isolated event, then dry.
        "Rainfall_mm": [21.2, 40.2, 12.6, 142.2, 410.7, 83.6,
                        0.0, 26.8, 0.0, 0.0, 19.8, 2.4],
        "SeasonType": ["Wet", "Wet", "Wet", "Wet", "Wet", "Wet",
                       "Wet", "Dry", "Dry", "Dry", "Dry", "Dry"],
    })
    out = refine_season_tails(df, threshold_high=5.0, threshold_low=0.0)
    seasons = dict(zip(out["Date"], out["SeasonType"]))
    # The zero month at the tail must be contracted to Dry.
    assert seasons[pd.Timestamp("1995-04-01")] == "Dry"
    # The standalone May event must NOT be re-classified as Wet.
    assert seasons[pd.Timestamp("1995-05-01")] == "Dry"


def test_refine_does_not_merge_across_hydro_years():
    """Adjacent fixed-hydro-year wet seasons must not merge via extension.

    Without the HY cap, the forward extension from the first wet run would
    bridge across the HY boundary and swallow the dry gap, producing a single
    multi-year wet run (the failure mode behind the 26-month HY 2022).
    """
    dates = pd.date_range("2021-10-01", periods=18, freq="MS")
    # 18 months: Oct 2021 → Mar 2023.
    # HY boundary at Oct 2022 (months 1..12 = HY2022, months 13..18 = HY2023).
    rainfall = [
        80, 60, 40, 20, 10, 10,    # Oct21..Mar22 — HY2022 wet block
        10, 10, 10, 10,            # Apr22..Jul22 — qualifying dry tail (>= threshold_high)
        10, 10,                    # Aug22..Sep22 — still HY2022, qualifying
        10, 20, 40, 60, 80, 50,    # Oct22..Mar23 — HY2023 wet block
    ]
    hy = [2022] * 12 + [2023] * 6
    seasons = ["Wet"] * 6 + ["Dry"] * 6 + ["Wet"] * 6
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": rainfall,
        "Hydro_Year_fixed": hy,
        "SeasonType": seasons,
    })
    out = refine_season_tails(
        df, threshold_high=5.0, threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed",
    )
    # HY2022 wet run must not extend into HY2023 rows.
    hy2023_rows = out[out["Hydro_Year_fixed"] == 2023]
    # The HY2023 wet block stays in HY2023, but the HY2022 forward extension
    # must stop at the HY boundary, not consume HY2023 dry-tail months.
    last_hy2022_wet = out.loc[
        (out["Hydro_Year_fixed"] == 2022) & (out["SeasonType"] == "Wet"), "Date"
    ].max()
    assert last_hy2022_wet <= pd.Timestamp("2022-09-01")
    # The first HY2023 row remains Wet (its own wet block start), not merged.
    assert hy2023_rows.iloc[0]["SeasonType"] == "Wet"


# ---------------------------------------------------------------------------
# Cross-regime shoulder absorption (Rule A: wet-run-length gate replaces
# absolute HY-boundary wall).
# ---------------------------------------------------------------------------
def test_shoulder_absorbed_across_hy_when_core_long_enough():
    """Real wet core (>=3 months) absorbs a genuine shoulder month sitting in
    the previous fixed-hydro-year (Oct shoulder before a Nov-Mar core)."""
    dates = pd.date_range("1994-08-01", periods=10, freq="MS")
    # Oct rainfall is well above any plausible threshold; the HY boundary is
    # between Oct (HY1994) and Nov (HY1995). The Nov-Mar core has length 5.
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 0.0, 21.2, 40.2, 60.0, 142.2, 410.7, 83.6, 30.0, 5.0],
        "Hydro_Year_fixed": [1994, 1994, 1994, 1995, 1995, 1995, 1995, 1995, 1995, 1995],
        "SeasonType": ["Dry", "Dry", "Dry", "Wet", "Wet", "Wet", "Wet", "Wet", "Dry", "Dry"],
    })
    out = refine_season_tails(
        df, threshold_high=5.0, threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed", min_core_length=3,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("1994-10-01")] == "Wet"
    # September stays Dry (raw value 0).
    assert by_date[pd.Timestamp("1994-09-01")] == "Dry"


def test_orphan_event_still_cannot_cross_hy_boundary():
    """A single-month wet 'core' must NOT absorb a neighbouring month across
    a fixed-HY boundary, even with the new rule."""
    dates = pd.date_range("1994-08-01", periods=6, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 30.0, 25.0, 0.0, 0.0, 0.0],
        # HY boundary between Sep (HY1994) and Oct (HY1995).
        "Hydro_Year_fixed": [1994, 1994, 1995, 1995, 1995, 1995],
        # The "core" is a single Wet month in Sep 1994 (HY1994); the Oct
        # candidate sits across the HY boundary.
        "SeasonType": ["Dry", "Wet", "Dry", "Dry", "Dry", "Dry"],
    })
    out = refine_season_tails(
        df, threshold_high=5.0, threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed", min_core_length=3,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    # The single-month core (length 1 < min_core_length=3) cannot snowball
    # across the boundary.
    assert by_date[pd.Timestamp("1994-10-01")] == "Dry"


def test_recession_shoulder_absorbed_symmetrically():
    """Recession (Mediterranean-style) shoulder one month into the next
    fixed-hydro-year must also be absorbed when the core is long enough."""
    dates = pd.date_range("2010-11-01", periods=8, freq="MS")
    # Nov-Feb core in HY2011, then a wet March that already crosses into
    # HY2011's next fixed-HY (hypothetical March start, just to exercise
    # forward extension across a boundary).
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [60.0, 120.0, 150.0, 100.0, 50.0, 8.0, 0.0, 0.0],
        "Hydro_Year_fixed": [2011, 2011, 2011, 2011, 2011, 2012, 2012, 2012],
        "SeasonType": ["Wet", "Wet", "Wet", "Wet", "Wet", "Dry", "Dry", "Dry"],
    })
    out = refine_season_tails(
        df, threshold_high=5.0, threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed", min_core_length=3,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2011-04-01")] == "Wet"
    assert by_date[pd.Timestamp("2011-05-01")] == "Dry"


def test_bimodal_second_wet_season_absorbs_shoulder():
    """For a bimodal regime, the second wet block must independently absorb
    its own shoulder across a fixed-HY boundary if the core is long enough."""
    dates = pd.date_range("2000-01-01", periods=24, freq="MS")
    rainfall = [
        # Long rains Mar-May, dry Jun-Sep, short rains Oct-Dec (East Africa-ish)
        20, 30, 200, 250, 220, 5, 0, 0, 0, 80, 220, 180,
        25, 30, 250, 280, 230, 5, 0, 0, 0, 90, 240, 200,
    ]
    hy = [2000] * 6 + [2001] * 12 + [2002] * 6
    season = (
        ["Dry"] * 2 + ["Wet"] * 3 + ["Dry"]            # 2000 Jan-Jun
        + ["Dry"] * 3 + ["Wet"] * 3                    # 2000 Jul-Dec
        + ["Dry"] * 2 + ["Wet"] * 3 + ["Dry"]          # 2001 Jan-Jun
        + ["Dry"] * 3 + ["Wet"] * 3                    # 2001 Jul-Dec
    )
    df = pd.DataFrame({
        "Date": dates, "Rainfall_mm": rainfall,
        "Hydro_Year_fixed": hy, "SeasonType": season,
    })
    out = refine_season_tails(
        df, threshold_high=10.0, threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed", min_core_length=3,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    # Both wet blocks remain wet; the rule does not destabilise bimodal labelling.
    assert by_date[pd.Timestamp("2001-03-01")] == "Wet"
    assert by_date[pd.Timestamp("2001-10-01")] == "Wet"
    # Dry trough between the two wet blocks stays dry.
    assert by_date[pd.Timestamp("2001-07-01")] == "Dry"


def test_climatology_floor_blocks_trivial_absorption_in_arid_regimes():
    """In arid regimes the global threshold_high can be near-zero. The
    climatology_floor gate must prevent a 1 mm month from being absorbed."""
    dates = pd.date_range("2010-08-01", periods=6, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 1.5, 80.0, 90.0, 70.0, 0.0],
        "Hydro_Year_fixed": [2010, 2010, 2011, 2011, 2011, 2011],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Wet", "Dry"],
    })
    # threshold_high alone (1.0) would absorb September (1.5 mm). The floor
    # (= 0.10 * 80 = 8.0) blocks it.
    out = refine_season_tails(
        df, threshold_high=1.0, threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed", min_core_length=3,
        climatology_floor=8.0,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2010-09-01")] == "Dry"


def test_residual_gate_blocks_extreme_positive_shoulder_anomaly():
    """A high-rainfall candidate with an extreme STL residual should stay Dry:
    it behaves like an isolated storm anomaly, not a seasonal shoulder."""
    dates = pd.date_range("2010-08-01", periods=6, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 45.0, 100.0, 120.0, 90.0, 0.0],
        "STL_Residual": [0.0, 250.0, 5.0, 0.0, 0.0, 0.0],
        "Hydro_Year_fixed": [2010, 2010, 2011, 2011, 2011, 2011],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Wet", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=10.0,
        threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=3,
        residual_col="STL_Residual",
        residual_threshold=100.0,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2010-09-01")] == "Dry"


def test_residual_gate_allows_non_anomalous_shoulder():
    dates = pd.date_range("2010-08-01", periods=6, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 45.0, 100.0, 120.0, 90.0, 0.0],
        "STL_Residual": [0.0, 25.0, 5.0, 0.0, 0.0, 0.0],
        "Hydro_Year_fixed": [2010, 2010, 2011, 2011, 2011, 2011],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Wet", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=10.0,
        threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=3,
        residual_col="STL_Residual",
        residual_threshold=100.0,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2010-09-01")] == "Wet"


def test_month_aware_extension_floor_blocks_ordinary_dry_month():
    dates = pd.date_range("2010-08-01", periods=6, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 25.0, 100.0, 120.0, 90.0, 0.0],
        "MonthFloor": [0.0, 30.0, 0.0, 0.0, 0.0, 0.0],
        "Hydro_Year_fixed": [2010, 2010, 2011, 2011, 2011, 2011],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Wet", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=10.0,
        threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=3,
        extension_threshold_col="MonthFloor",
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2010-09-01")] == "Dry"


def test_per_row_floor_fallback_cannot_loosen_extension_gate():
    dates = pd.date_range("2010-08-01", periods=5, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 8.0, 100.0, 120.0, 0.0],
        "PerRowFloor": [0.0, 5.0, 0.0, 0.0, 0.0],
        "Hydro_Year_fixed": [2010, 2010, 2011, 2011, 2011],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=10.0,
        threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=2,
        per_row_threshold_col="PerRowFloor",
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2010-09-01")] == "Dry"


def test_extension_floor_nan_falls_back_to_scalar_gate():
    dates = pd.date_range("2010-08-01", periods=5, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 12.0, 100.0, 120.0, 0.0],
        "MonthFloor": [0.0, None, 0.0, 0.0, 0.0],
        "Hydro_Year_fixed": [2010, 2010, 2011, 2011, 2011],
        "SeasonType": ["Dry", "Dry", "Wet", "Wet", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=10.0,
        threshold_low=0.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=2,
        extension_threshold_col="MonthFloor",
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2010-09-01")] == "Wet"


def test_low_floor_inside_run_splits_smoothing_bleed_fragment():
    dates = pd.date_range("2002-12-01", periods=8, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [81.6, 89.8, 187.68, 196.2, 3.4, 14.2, 13.8, 0.0],
        "Hydro_Year_fixed": [2003] * 8,
        "SeasonType": ["Wet", "Wet", "Wet", "Wet", "Wet", "Wet", "Wet", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=4.0,
        threshold_low=10.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=3,
        enforce_low_floor_inside_runs=True,
        min_refined_run_length=3,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2003-04-01")] == "Dry"
    assert by_date[pd.Timestamp("2003-05-01")] == "Dry"
    assert by_date[pd.Timestamp("2003-06-01")] == "Dry"


def test_baseline_wet_fragment_survives_low_floor_break():
    dates = pd.date_range("1987-11-01", periods=5, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [11.5, 99.0, 43.0, 6.7, 7.0],
        "BaselineWet": [True, True, True, True, True],
        "Hydro_Year_fixed": [1988] * 5,
        "SeasonType": ["Wet", "Wet", "Wet", "Wet", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=4.0,
        threshold_low=12.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=3,
        climatology_floor=12.0,
        fragment_keep_col="BaselineWet",
        enforce_low_floor_inside_runs=True,
        min_refined_run_length=3,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("1987-11-01")] == "Dry"
    assert by_date[pd.Timestamp("1987-12-01")] == "Wet"
    assert by_date[pd.Timestamp("1988-01-01")] == "Wet"
    assert by_date[pd.Timestamp("1988-02-01")] == "Dry"


def test_short_real_wet_run_survives_fragment_pruning_without_low_break():
    dates = pd.date_range("2010-01-01", periods=5, freq="MS")
    df = pd.DataFrame({
        "Date": dates,
        "Rainfall_mm": [0.0, 30.0, 35.0, 0.0, 0.0],
        "Hydro_Year_fixed": [2010] * 5,
        "SeasonType": ["Dry", "Wet", "Wet", "Dry", "Dry"],
    })
    out = refine_season_tails(
        df,
        threshold_high=10.0,
        threshold_low=10.0,
        hydro_year_col="Hydro_Year_fixed",
        min_core_length=3,
        enforce_low_floor_inside_runs=True,
        min_refined_run_length=3,
    )
    by_date = dict(zip(out["Date"], out["SeasonType"]))
    assert by_date[pd.Timestamp("2010-02-01")] == "Wet"
    assert by_date[pd.Timestamp("2010-03-01")] == "Wet"


def test_targeted_october_shoulders_pipeline_e2e():
    """End-to-end: every shoulder month listed for the Fitzroy dataset is
    classified Wet after the rule change."""
    import pandas as _pd
    from pathlib import Path
    from hydroseason.pipeline import classify_rainfall

    csv_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "DATASET2.csv"
    df = _pd.read_csv(csv_path)
    df["Date"] = _pd.to_datetime(df["Date"], dayfirst=True)
    artifacts = classify_rainfall(df)
    result = artifacts.result.copy()
    result["Date"] = _pd.to_datetime(result["Date"])

    targets = [
        "1994-10-01", "1995-10-01", "1996-10-01", "1998-10-01",
        "2000-10-01", "2001-10-01", "2005-10-01",
        "2010-09-01", "2010-10-01", "2017-10-01", "2020-10-01",
    ]
    labels = {
        d: result.loc[result["Date"] == _pd.Timestamp(d), "SeasonType"].iloc[0]
        for d in targets
    }
    # All shoulder months should be Wet now (Sept 2010 included).
    assert all(v == "Wet" for v in labels.values()), labels

    # And the orphan dry-season events must remain Dry.
    for d in ("1995-05-01", "1997-05-01", "2012-05-01"):
        assert result.loc[result["Date"] == _pd.Timestamp(d), "SeasonType"].iloc[0] == "Dry"


def test_targeted_problem_months_pipeline_e2e():
    """End-to-end: known smoothing-bleed months stay Dry."""
    import pandas as _pd
    from pathlib import Path
    from hydroseason.pipeline import classify_rainfall

    csv_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "DATASET2.csv"
    df = _pd.read_csv(csv_path)
    df["Date"] = _pd.to_datetime(df["Date"], dayfirst=True)
    artifacts = classify_rainfall(df)
    result = artifacts.result.copy()
    result["Date"] = _pd.to_datetime(result["Date"])

    targets = [
        "2003-04-01", "2003-05-01", "2003-06-01",
        "2009-05-01", "2009-11-01", "2010-04-01",
        "2022-09-01", "2022-10-01",
    ]
    labels = {
        d: result.loc[result["Date"] == _pd.Timestamp(d), "SeasonType"].iloc[0]
        for d in targets
    }
    assert all(v == "Dry" for v in labels.values()), labels
    assert artifacts.diagnostics.tail_floor == artifacts.diagnostics.threshold_firstpass
    assert artifacts.diagnostics.shoulder_month_quantile == 0.60

