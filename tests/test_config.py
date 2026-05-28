from pathlib import Path

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
    assert loaded.algorithm.smooth_window == 3   # paper-spec default
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
validation:
  max_fraction_missing: 0.25
""".strip(),
        encoding="utf-8",
    )
    loaded = load_config(cfg)
    assert loaded.algorithm.smooth_window == 5
    assert loaded.algorithm.method == "kmeans"
    assert loaded.algorithm.fallback_month == 4
    assert loaded.validation.max_fraction_missing == 0.25


def test_example_config_loads():
    loaded = load_config(Path("config/example.yaml"))
    assert loaded.algorithm.smooth_window == 3
    assert loaded.fetch.enabled is False
    assert loaded.fetch.variable == "rainfall"
