from pathlib import Path

import pytest

from hydroseason.config import load_config


def test_load_config_defaults(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
input:
  csv_path: tests/fixtures/monthly_rainfall.csv
output:
  output_csv: out/results.csv
""".strip(),
        encoding="utf-8",
    )
    loaded = load_config(cfg)
    assert loaded.algorithm.smooth_window is None  # None → auto from regime
    assert loaded.algorithm.min_core_length is None  # None → auto from regime
    assert loaded.algorithm.onset_window_months == "auto"
    assert loaded.algorithm.shoulder_residual_quantile == 0.95
    assert loaded.algorithm.fallback_month is None  # auto-derived
    assert loaded.algorithm.method == "circular"
    assert loaded.validation.raise_on_error is True


def test_load_config_overrides(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
input:
  csv_path: x.csv
output:
  output_csv: y.csv
algorithm:
  smooth_window: 5
  method: kmeans
  fallback_month: 4
  shoulder_residual_quantile: null
validation:
  max_fraction_missing: 0.25
""".strip(),
        encoding="utf-8",
    )
    loaded = load_config(cfg)
    assert loaded.algorithm.smooth_window == 5
    assert loaded.algorithm.method == "kmeans"
    assert loaded.algorithm.fallback_month == 4
    assert loaded.algorithm.shoulder_residual_quantile is None
    assert loaded.validation.max_fraction_missing == 0.25


def test_example_config_loads():
    loaded = load_config(Path("config/example.yaml"))
    assert loaded.algorithm.smooth_window is None
    assert loaded.fetch.enabled is False
    assert loaded.fetch.variable == "rainfall"


def test_load_config_missing_output_points_to_example(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("input:\n  csv_path: x.csv\n", encoding="utf-8")
    with pytest.raises(KeyError) as exc:
        load_config(cfg)
    assert "output" in str(exc.value)
    assert "config/example.yaml" in str(exc.value)


def test_load_config_missing_input_csv_path(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("output:\n  output_csv: out.csv\n", encoding="utf-8")
    with pytest.raises(KeyError) as exc:
        load_config(cfg)
    assert "input.csv_path" in str(exc.value)


def test_load_fetch_only_config_without_input_csv(tmp_path: Path):
    cfg = tmp_path / "fetch_config.yaml"
    cfg.write_text(
        """
output:
  output_csv: out/results.csv
fetch:
  enabled: true
  source: silo
  vector_path: data/fitzroy_catchment.geojson
  start_year: 2020
  end_year: 2021
""".strip(),
        encoding="utf-8",
    )

    loaded = load_config(cfg)

    assert loaded.input.csv_path is None
    assert loaded.fetch.enabled is True
    assert loaded.fetch.source == "silo"


def test_load_config_requires_csv_when_fetch_disabled(tmp_path: Path):
    cfg = tmp_path / "bad_config.yaml"
    cfg.write_text(
        """
output:
  output_csv: out/results.csv
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(KeyError, match="input.csv_path"):
        load_config(cfg)
