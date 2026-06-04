from pathlib import Path

import pandas as pd
import pytest

from hydroseason.cli import main

FIXTURES = Path(__file__).parent / "fixtures"



def test_cli_run(tmp_path: Path):
    in_csv = FIXTURES / "monthly_rainfall.csv"
    out_csv = tmp_path / "delineated.csv"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""
input:
  csv_path: {in_csv.as_posix()}
output:
  output_csv: {out_csv.as_posix()}
""".strip(),
        encoding="utf-8",
    )
    rc = main(["run", "--config", str(cfg)])
    assert rc == 0
    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    assert "Hydro_Year" in df.columns
    # sidecar diagnostics
    assert (out_csv.with_suffix(".HydroSeason.json")).exists()


def test_cli_demo(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out_csv = tmp_path / "demo.csv"
    rc = main(["demo", "--out", str(out_csv)])
    assert rc == 0
    assert out_csv.exists()


def test_cli_rainfall_csv(tmp_path: Path):
    in_csv = FIXTURES / "monthly_rainfall.csv"
    out_csv = tmp_path / "rainfall_results.csv"

    rc = main(
        [
            "rainfall",
            "--input",
            str(in_csv),
            "--source",
            "csv",
            "--output",
            str(out_csv),
        ]
    )
    assert rc == 0
    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    assert "Hydro_Year" in df.columns


def test_era5_variables_registry():
    from hydroseason import get_monthly_era5_rainfall
    from hydroseason.era5_variables import available, get

    assert callable(get_monthly_era5_rainfall)
    keys = available()
    assert "rainfall" in keys
    assert "temperature" in keys

    rain = get("rainfall")
    assert rain.out_column == "Rainfall_mm"
    assert rain.unit_factor == 1000.0

    temp = get("temperature")
    assert temp.unit_offset == -273.15


def test_cli_fetch_era5_routes_to_aoi_wrapper_with_metadata(tmp_path: Path, monkeypatch):
    from hydroseason import cli as cli_mod

    out_csv = tmp_path / "era5_fetch.csv"

    calls: dict[str, object] = {}

    def fake_load_vector(path):
        calls["vector"] = path
        return object()

    def fake_get_monthly_aoi_rainfall(**kwargs):
        calls["aoi"] = kwargs
        return pd.DataFrame(
            {
                "Date": ["2020-01-01"],
                "Year": [2020],
                "Month": [1],
                "Rainfall_mm": [123.0],
                "Data_Source": ["ERA5"],
                "Data_Product": ["ERA5 hourly ARCO Zarr"],
                "Fetch_Note": ["exact path"],
            }
        )

    monkeypatch.setattr("hydroseason.fetch.load_vector", fake_load_vector)
    monkeypatch.setattr(
        "hydroseason.fetch.get_monthly_aoi_rainfall",
        fake_get_monthly_aoi_rainfall,
    )

    rc = cli_mod.main(
        [
            "fetch",
            "--source",
            "era5",
            "--path",
            "gs://example/store.zarr",
            "--vector",
            "aoi.kml",
            "--start-year",
            "2020",
            "--end-year",
            "2020",
            "--output",
            str(out_csv),
        ]
    )

    assert rc == 0
    assert out_csv.exists()
    assert calls["vector"] == "aoi.kml"
    assert calls["aoi"]["source"] == "era5"
    assert calls["aoi"]["era5_zarr_path"] == "gs://example/store.zarr"
    assert calls["aoi"]["time_chunk"] == "auto"
    assert calls["aoi"]["temporal_batch_years"] == "auto"
    out = pd.read_csv(out_csv)
    assert out.loc[0, "Data_Source"] == "ERA5"


def test_cli_fetch_silo_routes_to_aoi_wrapper_with_metadata(tmp_path: Path, monkeypatch):
    from hydroseason import cli as cli_mod

    out_csv = tmp_path / "silo_fetch.csv"

    calls: dict[str, object] = {}

    def fake_load_vector(path):
        calls["vector"] = path
        return object()

    def fake_get_monthly_aoi_rainfall(**kwargs):
        calls["aoi"] = kwargs
        return pd.DataFrame(
            {
                "Date": ["2020-01-01"],
                "Year": [2020],
                "Month": [1],
                "Rainfall_mm": [100.0],
                "Data_Source": ["SILO"],
                "Data_Product": ["SILO monthly rainfall"],
                "Fetch_Note": ["Australian gridded monthly rainfall default"],
            }
        )

    monkeypatch.setattr("hydroseason.fetch.load_vector", fake_load_vector)
    monkeypatch.setattr(
        "hydroseason.fetch.get_monthly_aoi_rainfall",
        fake_get_monthly_aoi_rainfall,
    )

    rc = cli_mod.main(
        [
            "fetch",
            "--source",
            "silo",
            "--silo-base-url",
            "https://example.test/silo/monthly_rain",
            "--vector",
            "aoi.kmz",
            "--start-year",
            "2020",
            "--end-year",
            "2020",
            "--output",
            str(out_csv),
        ]
    )

    assert rc == 0
    assert out_csv.exists()
    assert calls["vector"] == "aoi.kmz"
    assert calls["aoi"]["source"] == "silo"
    assert (
        calls["aoi"]["silo_base_url"]
        == "https://example.test/silo/monthly_rain"
    )
    out = pd.read_csv(out_csv)
    assert out.loc[0, "Data_Source"] == "SILO"


def test_cli_fetch_auto_routes_to_aoi_fetch(tmp_path: Path, monkeypatch):
    from hydroseason import cli as cli_mod

    out_csv = tmp_path / "auto_fetch.csv"
    calls: dict[str, object] = {}

    def fake_load_vector(path):
        calls["vector"] = path
        return object()

    def fake_get_monthly_aoi_rainfall(**kwargs):
        calls["auto"] = kwargs
        return pd.DataFrame(
            {
                "Date": ["2020-01-01"],
                "Year": [2020],
                "Month": [1],
                "Rainfall_mm": [99.0],
                "Data_Source": ["CHIRPS"],
            }
        )

    monkeypatch.setattr("hydroseason.fetch.load_vector", fake_load_vector)
    monkeypatch.setattr(
        "hydroseason.fetch.get_monthly_aoi_rainfall",
        fake_get_monthly_aoi_rainfall,
    )

    rc = cli_mod.main(
        [
            "fetch",
            "--vector",
            "aoi.geojson",
            "--start-year",
            "2020",
            "--end-year",
            "2020",
            "--output",
            str(out_csv),
        ]
    )

    assert rc == 0
    assert out_csv.exists()
    assert calls["auto"]["source"] == "auto"
    assert calls["auto"]["era5_fallback"] is True


def test_cli_fetch_era5_requires_path():
    with pytest.raises(ValueError, match="--path is required"):
        main(
            [
                "fetch",
                "--source",
                "era5",
                "--vector",
                "aoi.shp",
                "--start-year",
                "2020",
                "--end-year",
                "2020",
                "--output",
                "out.csv",
            ]
        )
