# tests/fixtures/build_dynamic_state_mock.py
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
YEARS = list(range(1990, 2020))
SHIFTS = [-1, 0, 1, 0, -1, 1] * 5


def magnitudes(position):
    if position < 3:
        return 20.0 + position, 1.0 + position, "dry_low_refuge"
    if position < 6:
        return 32.0 + position, 30.0 + position, "buffered_low_recharge"
    if position < 9:
        return 84.0 + position, 1.0 + position - 6, "recharged_then_contracting"
    if position < 12:
        return 84.0 + position, 30.0 + position - 6, "wet_persistent"
    return 55.0 + (position % 12), 10.0 + (position % 10), "typical_or_mixed"


def intermittent_panel():
    index = pd.date_range("1989-08-01", "2020-04-01", freq="MS")
    control = {}
    truth = []
    control[pd.Timestamp("1989-09-01")] = 10.0
    for position, (year, shift) in enumerate(zip(YEARS, SHIFTS)):
        peak_value, trough_value, state = magnitudes(position)
        peak = pd.Timestamp(year, 2 + shift, 1)
        trough = pd.Timestamp(year, 9 + shift, 1)
        control[peak], control[trough] = peak_value, trough_value
        midpoint_target = peak + (trough - peak) / 2
        midpoint = index[int(np.argmin(np.abs(index - midpoint_target)))]
        target = (peak_value + trough_value) / 2
        decline = pd.date_range(peak, trough, freq="MS")
        decline_values = np.linspace(peak_value, trough_value, len(decline))
        half_loss = decline[int(np.flatnonzero(decline_values <= target)[0])]
        truth.append(
            {
                "site": "intermittent", "hy_year": year,
                "peak_month": peak, "peak_extent_pct": peak_value,
                "trough_month": trough, "trough_extent_pct": trough_value,
                "temporal_mid_dry_month": midpoint, "half_loss_month": half_loss,
                "annual_condition": state, "detectable": year != 2008,
            }
        )
    series = pd.Series(control, dtype=float).sort_index().reindex(index).interpolate(method="time")
    frame = pd.DataFrame({"site": "intermittent", "date": index, "extent_pct": series.to_numpy(), "invalid_pct": 0.0})
    pulse_dates = pd.to_datetime(["2003-06-01", "2003-07-01", "2003-08-01"])
    frame.loc[frame["date"].isin(pulse_dates), "extent_pct"] += [2.0, 12.0, 0.0]
    frame.loc[frame["date"].between("2008-06-01", "2008-12-01"), "invalid_pct"] = 100.0
    return frame, pd.DataFrame(truth)


def diagnostic_site(name, formula):
    index = pd.date_range("1990-01-01", periods=30 * 12, freq="MS")
    values = formula(index.month.to_numpy())
    return pd.DataFrame({"site": name, "date": index, "extent_pct": values, "invalid_pct": 0.0})


def basin_sites(intermittent):
    rows = []
    for site, size, scale in (("basin_small", 100, 0.8), ("basin_large", 900, 1.1)):
        extent = np.clip(intermittent["extent_pct"].to_numpy() * scale, 0, 100)
        valid = np.full(len(extent), size, dtype=int)
        water = np.rint(valid * extent / 100).astype(int)
        rows.append(pd.DataFrame({
            "site": site, "date": intermittent["date"], "extent_pct": 100 * water / valid,
            "invalid_pct": 0.0, "n_water": water, "n_valid": valid,
            "n_invalid": 0, "n_aoi": valid,
        }))
    return pd.concat(rows, ignore_index=True)


intermittent, truth = intermittent_panel()
perennial = diagnostic_site("perennial", lambda month: 60.0 + 0.3 * np.cos(2 * np.pi * (month - 2) / 12))
bimodal = diagnostic_site("bimodal", lambda month: 35.0 + 15.0 * np.cos(4 * np.pi * (month - 2) / 12))
panel = pd.concat([intermittent, perennial, bimodal, basin_sites(intermittent)], ignore_index=True)
panel.to_csv(ROOT / "dynamic_state_mock.csv", index=False, date_format="%Y-%m-%d")
truth.to_csv(ROOT / "dynamic_state_truth.csv", index=False, date_format="%Y-%m-%d")
