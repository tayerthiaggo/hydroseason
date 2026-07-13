import pandas as pd
import pytest

from scripts.australia_stress_test import (
    DEFAULT_CACHE,
    DEFAULT_OUTPUT,
    audit_result,
    latitude_band,
    longitude_band,
    run_australia_stress,
)


def test_australia_stress_bands_are_geographic_only():
    assert latitude_band(-20.0) == "tropical_S"
    assert latitude_band(-30.0) == "subtropical_S"
    assert latitude_band(-40.0) == "temperate_S"
    assert longitude_band(119.0) == "west"
    assert longitude_band(130.0) == "central_west"
    assert longitude_band(140.0) == "central_east"
    assert longitude_band(150.0) == "east"


def test_australia_stress_audit_result_counts_anomalies():
    dates = pd.date_range("2020-01-01", periods=8, freq="MS")
    result = pd.DataFrame(
        {
            "Date": dates,
            "SeasonType": [
                "Wet", "Wet", "Wet", "Dry", "Wet", "Wet", "Wet", "Dry",
            ],
            "Hydro_Year": [2020] * 4 + [2021] * 4,
            "Hydro_Year_Boundary_Source": [
                "initial", pd.NA, pd.NA, pd.NA,
                "no_dry_minimum", pd.NA, pd.NA, pd.NA,
            ],
            "Hydro_Year_No_Dry_Season": [
                False, False, False, False,
                True, True, True, True,
            ],
        }
    )

    audit = audit_result(result)

    assert audit["max_hydro_year_months"] == 4
    assert audit["max_wet_run_months"] == 3
    assert audit["one_month_dry_bridges"] == 1
    assert audit["one_month_dry_bridges_strong"] == 1
    assert audit["no_dry_boundary_count"] == 1
    assert audit["no_dry_hydro_year_count"] == 1


@pytest.mark.slow
def test_australia_50_site_saved_or_cached_audit_gate():
    summary_path = DEFAULT_OUTPUT / "australia_silo_stress_summary.csv"
    if summary_path.exists():
        summary = pd.read_csv(summary_path)
    else:
        silo_cache = DEFAULT_CACHE / "silo_netcdf"
        if not silo_cache.exists() or not any(silo_cache.glob("*.monthly_rain.nc")):
            pytest.skip("Australia stress summary/cache not available")
        pytest.importorskip("geopandas")
        summary = run_australia_stress(n_sites=50, show_progress=False, resume=True)

    ok = summary[summary["status"].eq("ok")]
    assert len(ok) == 50
    assert int(ok["max_hydro_year_months"].max()) <= 20
    assert int(ok["one_month_dry_bridges_strong"].max()) == 0
    assert ok["regime"].notna().all()
