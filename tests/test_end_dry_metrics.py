import numpy as np
import pandas as pd

from hydroseason.metrics import compute_end_dry_metrics, compute_zero_flow_months


END_DRY_COLS = [
    "wet_area_ha",
    "npools",
    "AWMPA",
    "AWMPL",
    "AWMPW",
    "PF",
    "MPA",
]


def test_compute_end_dry_metrics_synthetic():
    df = pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=6, freq="MS"),
        "Hydro_Year": [2020] * 6,
        "SeasonType": ["Wet", "Wet", "Dry", "Dry", "Dry", "Dry"],
        "wet_area_ha": [100, 80, 20, 10, 4, 2],
        "npools": [50, 40, 12, 10, 6, 4],
    })

    out = compute_end_dry_metrics(df, metric_cols=["wet_area_ha", "npools"])

    assert np.isclose(out["wet_area_ha_endDry"].iloc[0], 3.0)
    assert np.isclose(out["npools_endDry"].iloc[0], 5.0)
    assert out["wet_area_ha_endDry"].nunique() == 1


def test_compute_end_dry_metrics_reproduces_dataset2_reference():
    df = pd.read_csv("tests/fixtures/DATASET2.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

    out = compute_end_dry_metrics(
        df,
        metric_cols=END_DRY_COLS,
        anchor="terminal_minimum",
        anchor_col="wet_area_ha",
    )

    for col in END_DRY_COLS:
        ref_col = f"{col}_endDry"
        diff = (out[ref_col] - df[ref_col]).abs().max()
        assert diff < 1e-6, f"{ref_col} max diff={diff}"


def test_compute_zero_flow_months_threshold():
    df = pd.DataFrame({
        "Hydro_Year": [2020, 2020, 2020, 2021, 2021],
        "Discharge": [0.0, 0.8, 1.2, 0.0, 2.0],
    })

    out = compute_zero_flow_months(df, threshold=1.0)

    assert out.loc[out["Hydro_Year"] == 2020, "zero_flow_months_count"].iloc[0] == 2
    assert out.loc[out["Hydro_Year"] == 2021, "zero_flow_months_count"].iloc[0] == 1
