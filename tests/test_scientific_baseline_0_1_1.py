from pathlib import Path

import pandas as pd
import pytest

from hydroseason import analyze_catchment

ROOT = Path(__file__).parents[1]
EXTENT = ROOT / "case_studies" / "data" / "extent"
BASELINE = Path(__file__).parent / "fixtures" / "scientific_baseline_0_1_1"

CASES = {
    "daly_river_nt": ("daly-river-nt", "seasonal", "per_year_detection", 3, 11, 21),
    "fitzroy_river_wa": ("fitzroy-river-wa", "seasonal", "per_year_detection", 2, 11, 21),
    "gilbert_river_qld": ("gilbert-river-qld", "seasonal", "per_year_detection", 2, 11, 21),
    "lachlan_river_nsw": ("lachlan-river-nsw", "aseasonal", "event_characterisation", None, None, 0),
    "moonie_river_qld_nsw": ("moonie-river-qld-nsw", "aseasonal", "event_characterisation", None, None, 0),
}

ANNUAL_COLUMNS = [
    "hy_year",
    "start_date",
    "end_date",
    "peak_date",
    "trough_date",
    "peak_extent_pct",
    "trough_extent_pct",
]


def _read_extent(case_key: str) -> pd.DataFrame:
    return pd.read_csv(EXTENT / f"{case_key}_30m.csv", parse_dates=["date"])


def test_frozen_summary_encodes_the_approved_five_case_contract():
    summary = pd.read_csv(BASELINE / "summary.csv").set_index("key")
    assert set(summary.index) == set(CASES)
    for case_key, (_, regime, route, peak, trough, n_years) in CASES.items():
        row = summary.loc[case_key]
        assert row["regime"] == regime
        assert row["route"] == route
        assert row["n_hydro_years"] == n_years
        if peak is not None:
            assert row["water_extent_peak_month"] == peak
            assert row["climatological_trough_month"] == trough


@pytest.mark.parametrize("case_key", CASES)
def test_raw_30m_record_matches_established_public_baseline(case_key: str):
    slug, regime, route, peak_month, trough_month, n_years = CASES[case_key]
    analysis = analyze_catchment(
        _read_extent(case_key),
        date_col="date",
        phase_scheme="none",
        n_bootstrap=200,
        random_state=0,
    )

    assert analysis.regime.decision_policy == "established_0_1_1"
    assert analysis.regime.regime == regime
    assert analysis.route == route
    assert analysis.climatological_peak_month == peak_month
    assert analysis.climatological_trough_month == trough_month
    assert len(analysis.hydro_years) == n_years

    if n_years == 0:
        assert analysis.hydro_years.empty
        return

    expected = pd.read_csv(
        BASELINE / f"{slug}_hydro_years.csv",
        usecols=ANNUAL_COLUMNS,
        parse_dates=["start_date", "end_date", "peak_date", "trough_date"],
    )
    actual = analysis.hydro_years.rename(
        columns={
            "hy_start": "start_date",
            "hy_end": "end_date",
            "peak_month": "peak_date",
            "trough_month": "trough_date",
        }
    ).loc[:, ANNUAL_COLUMNS].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )
