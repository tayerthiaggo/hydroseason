from pathlib import Path

import pandas as pd
import pytest

from hydroseason import DynamicHydroYearConfig, detect_dynamic_hydrological_years


ROOT = Path(__file__).parents[1]
CASES = {
    "fitzroy_river_wa": ("fitzroy_river_wa_30m.csv", 11),
    "gilbert_river_qld": ("gilbert_river_qld_30m.csv", 10),
}


def test_flagged_daly_2011_keeps_observed_cycle_and_marks_low_confidence():
    monthly = pd.read_csv(
        ROOT / "case_studies" / "data" / "extent" / "daly_river_nt_30m.csv",
        parse_dates=["date"],
    ).set_index("date")
    actual = detect_dynamic_hydrological_years(
        monthly,
        config=DynamicHydroYearConfig(
            expected_trough_month=11,
            max_invalid_pct=20.0,
            quality_policy="flag",
        ),
    ).set_index("hy_year")

    row = actual.loc[2011]
    assert row["peak_month"] == pd.Timestamp("2011-03-01")
    assert row["peak_invalid_pct"] > 80.0
    assert row["n_usable_months"] == 14
    assert row["peak_selection_status"] == "low_quality"
    assert row["boundary_status"] == "provisional"
    assert row["status"] == "partial"
    assert row["confidence"] == "low"


def _review_date(value: str) -> pd.Timestamp:
    return pd.to_datetime(value, dayfirst=True)


@pytest.mark.parametrize("catchment", sorted(CASES))
def test_manual_review_troughs_are_authoritative(catchment):
    data_name, expected_trough_month = CASES[catchment]
    monthly = pd.read_csv(ROOT / "case_studies" / "data" / "extent" / data_name,
                          parse_dates=["date"]).set_index("date")
    review = pd.read_csv(ROOT / "tests" / "fixtures" / f"{catchment}_manual_review.csv")
    actual = detect_dynamic_hydrological_years(
        monthly,
        config=DynamicHydroYearConfig(
            expected_trough_month=expected_trough_month,
            max_invalid_pct=20.0,
        ),
    ).set_index("hy_year")
    for row in review.itertuples(index=False):
        accepted = {_review_date(row.correct_trough_month)}
        notes = "" if pd.isna(row.notes) else str(row.notes)
        if "can also be" in notes:
            accepted.add(_review_date(notes.split("can also be", 1)[1].split()[0]))
        assert actual.loc[row.hy_year, "trough_month"] in accepted


@pytest.mark.parametrize("catchment", sorted(CASES))
def test_manual_review_peaks_match_observed_maxima(catchment):
    data_name, expected_trough_month = CASES[catchment]
    monthly = pd.read_csv(ROOT / "case_studies" / "data" / "extent" / data_name,
                          parse_dates=["date"]).set_index("date")
    review = pd.read_csv(ROOT / "tests" / "fixtures" / f"{catchment}_manual_review.csv")
    actual = detect_dynamic_hydrological_years(
        monthly,
        config=DynamicHydroYearConfig(
            expected_trough_month=expected_trough_month,
            max_invalid_pct=20.0,
        ),
    ).set_index("hy_year")
    for row in review.itertuples(index=False):
        peak = actual.loc[row.hy_year, "peak_month"]
        if pd.isna(peak):
            continue  # First partial year has no preceding trough anchor.
        assert peak == _review_date(row.correct_peak_month)


@pytest.mark.parametrize("catchment", sorted(CASES))
def test_manual_review_high_invalid_peaks_are_explicitly_provisional(catchment):
    data_name, expected_trough_month = CASES[catchment]
    monthly = pd.read_csv(ROOT / "case_studies" / "data" / "extent" / data_name,
                          parse_dates=["date"]).set_index("date")
    actual = detect_dynamic_hydrological_years(
        monthly,
        config=DynamicHydroYearConfig(
            expected_trough_month=expected_trough_month,
            max_invalid_pct=20.0,
        ),
    )
    selected = actual.loc[actual["peak_invalid_pct"].gt(20.0)]
    assert not selected.empty
    assert selected["peak_selection_status"].eq("low_quality").all()
    assert selected["boundary_status"].eq("provisional").all()
    assert selected["status"].eq("partial").all()
