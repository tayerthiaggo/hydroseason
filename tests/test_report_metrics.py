import numpy as np
import pandas as pd
import pytest

from hydroseason import detect_hydrological_years, label_hydrological_months
from hydroseason._report_metrics import build_monthly_records, build_year_cards_data, compute_report_kpis


def _seasonal_extent(n_years=3):
    index = pd.date_range("2018-01-01", periods=12 * n_years, freq="MS")
    month = index.month
    wet_amplitude = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
    return pd.DataFrame({"extent_pct": wet_amplitude, "invalid_pct": 0.0}, index=index)


def test_compute_report_kpis_matches_manual_calc():
    extent = _seasonal_extent(n_years=3)
    hy_df = detect_hydrological_years(extent)

    kpis = compute_report_kpis(extent, hy_df)

    assert kpis["total_months"] == len(extent)
    assert kpis["n_years"] == len(hy_df)
    assert kpis["mean_peak"] == pytest.approx(hy_df["peak_extent_pct"].mean())
    assert kpis["mean_end"] == pytest.approx(hy_df["end_extent_pct"].mean())
    assert kpis["mean_amp"] == pytest.approx(hy_df["amplitude_pct"].mean())
    assert kpis["mean_len"] == pytest.approx(hy_df["n_months_cycle"].mean())
    assert kpis["high_conf"] == len(hy_df[hy_df["confidence"] == "high"])
    assert kpis["med_conf"] == len(hy_df[hy_df["confidence"] == "medium"])
    assert kpis["low_conf"] == len(hy_df[hy_df["confidence"] == "low"])
    assert kpis["min_end"] == pytest.approx(hy_df["end_extent_pct"].min())
    assert kpis["max_peak"] == pytest.approx(hy_df["peak_extent_pct"].max())
    assert kpis["avg_invalid"] == pytest.approx(extent["invalid_pct"].mean())
    assert kpis["start_date"] == extent.index.min().strftime("%b %Y")
    assert kpis["end_date_label"] == extent.index.max().strftime("%b %Y")


def test_compute_report_kpis_empty_hydro_years():
    extent = _seasonal_extent(n_years=1)
    empty_hy = pd.DataFrame(columns=[
        "hy_year", "peak_extent_pct", "end_extent_pct", "amplitude_pct",
        "n_months_cycle", "confidence",
    ])

    kpis = compute_report_kpis(extent, empty_hy)

    assert kpis["n_years"] == 0
    assert kpis["mean_peak"] == 0.0
    assert kpis["high_conf"] == 0
    assert kpis["min_end"] == 0.0
    assert kpis["max_peak"] == 0.0


def test_build_year_cards_data_shape():
    extent = _seasonal_extent(n_years=2)
    hy_df = detect_hydrological_years(extent)
    labels = label_hydrological_months(extent.index, hy_df)

    cards = build_year_cards_data(extent, hy_df, labels)

    assert len(cards) == len(hy_df)
    for card in cards:
        assert set(["hy_val", "conf", "start_ts", "end_ts", "n_months_cycle", "amplitude_pct", "peak_month", "peak_extent_pct", "mid_dry_month", "mid_extent_pct", "end_dry_month", "end_extent_pct", "month_rows"]).issubset(card.keys())
        for month_row in card["month_rows"]:
            assert set(["ts", "season", "extent_pct", "invalid_pct", "is_peak", "is_mid", "is_end"]).issubset(month_row.keys())


def test_build_monthly_records_shape_and_values():
    extent = _seasonal_extent(n_years=1)
    hy_df = detect_hydrological_years(extent)
    labels = label_hydrological_months(extent.index, hy_df)

    records = build_monthly_records(extent, labels)

    assert len(records) == len(labels)
    first = records[0]
    assert set(["date", "display_date", "year", "season", "hy_year", "extent_pct", "invalid_pct"]) == set(first.keys())
    assert first["extent_pct"] == round(float(extent.iloc[0]["extent_pct"]), 2)
