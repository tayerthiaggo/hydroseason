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
    assert row["n_usable_months"] == 10
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
def test_manual_review_high_invalid_peaks_are_provisional_only_when_anomalous(catchment):
    """The flat ">20% invalid is always provisional" rule was retired deliberately.

    A cycle is cut trough-to-trough, so its peak is interior, and in a
    monsoonal catchment the annual maximum lands in the cloudiest month by
    construction. A flat 20% cap flagged a third of all cycles for having
    their peak where peaks belong. See
    .superpowers/sdd/task-2-brief.md for the plan that retires this rule:
    only peaks anomalous for their own month-of-year now downgrade the cycle.
    Released cycles' complete/confirmed status is verified against the full
    analyze_catchment pipeline, because this test's bare detector call leaves
    timing unresolved for nearly every cycle.
    """
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
    # The raw selector still flags these against the flat screen...
    assert selected["peak_selection_status"].eq("low_quality").all()
    # ...but a peak that is merely cloudy for its season no longer marks the
    # cycle unsound. The annual maximum occurs during the monsoon, so a flat
    # 20% cap flags the median wet-season month rather than an anomaly. Only
    # peaks anomalous for their own month-of-year are provisional now.
    anomalous = selected.loc[selected["peak_quality"].eq("anomalous")]
    normal = selected.loc[selected["peak_quality"].eq("normal")]
    assert not normal.empty, "expected some >20% peaks to be seasonally normal"
    assert not anomalous.empty, "expected some >20% peaks to be anomalous"
    # boundary_status is a conjunction of four independent conditions, so a
    # seasonally-normal peak does not by itself make a cycle confirmed --
    # unresolved timing keeps most cycles provisional under this test's bare
    # detector call, for reasons this change does not touch. What this change
    # governs is the REASON: a merely-cloudy peak must no longer be the thing
    # that downgrades a cycle.
    assert normal["status_reason"].ne("peak_quality_anomalous").all()
    assert anomalous["status_reason"].eq("peak_quality_anomalous").all()
    assert anomalous["boundary_status"].eq("provisional").all()
