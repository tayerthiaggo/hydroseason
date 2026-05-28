from pathlib import Path

import pandas as pd

from hydroseason.cli import main


def test_cli_run(tmp_path: Path):
    in_csv = Path("tests/fixtures/monthly_rainfall.csv")
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


def test_era5_variables_registry():
    from hydroseason import get_monthly_total_precip, get_monthly_variable
    from hydroseason.era5_variables import available, get
    assert callable(get_monthly_variable)
    assert callable(get_monthly_total_precip)
    keys = available()
    assert "rainfall" in keys
    assert "temperature" in keys
    rain = get("rainfall")
    assert rain.out_column == "Rainfall_mm"
    assert rain.unit_factor == 1000.0
    temp = get("temperature")
    assert temp.unit_offset == -273.15
