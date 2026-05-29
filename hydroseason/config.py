"""Configuration dataclasses and YAML loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class InputConfig:
    csv_path: str | None = None
    date_col: str = "Date"
    year_col: str = "Year"
    month_col: str = "Month"
    value_col: str = "Rainfall_mm"


@dataclass
class OutputConfig:
    output_csv: str


@dataclass
class AlgorithmConfig:
    smooth_window: int | None = None           # None → auto from circular concentration
    firstpass_quantile: float = 0.20
    secondpass_quantile: float = 0.10
    long_period_threshold: int = 16
    fallback_month: int | None = None          # auto-derived from data when None
    method: str = "circular"                    # "circular" | "kmeans"
    onset_window_months: int | str | None = "auto"  # "auto" | None | int
    rainfall_si_override: bool = True
    rainfall_si_threshold: float = 0.80
    min_core_length: int | None = None         # None → auto from circular concentration
    shoulder_climatology_alpha: float = 0.10   # shoulder absorption floor (α * median wet-month clim)
    core_climatology_alpha: float = 0.05       # wet-core detection floor (arid-regime safety)
    shoulder_residual_quantile: float | None = 0.95  # positive STL-residual quantile gate; None disables


@dataclass
class ValidationConfig:
    max_fraction_missing: float = 0.10
    max_gap_to_interpolate: int = 2
    max_consecutive_imputation_gap: int = 12
    raise_on_error: bool = True


@dataclass
class FetchConfig:
    enabled: bool = False
    source: str = "era5"          # "era5" | "silo"
    era5_zarr_path: str | None = None
    silo_base_url: str | None = None
    vector_path: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    variable: str = "rainfall"      # registry key in era5_variables.py
    cache_dir: str | None = None
    spatial_chunk: int = 50


@dataclass
class RunConfig:
    input: InputConfig
    output: OutputConfig
    algorithm: AlgorithmConfig = field(default_factory=AlgorithmConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    fetch: FetchConfig = field(default_factory=FetchConfig)


def _require(d: dict, key: str):
    if key not in d:
        raise KeyError(f"Missing required config section/key: {key}")
    return d[key]


def load_config(path: str | Path) -> RunConfig:
    cfg_path = Path(path)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    output_cfg = OutputConfig(**_require(data, "output"))
    fetch_cfg = FetchConfig(**data.get("fetch", {}))
    input_cfg = InputConfig(**data.get("input", {}))
    if not fetch_cfg.enabled and input_cfg.csv_path is None:
        raise KeyError("Missing required config section/key: input.csv_path")
    algorithm_cfg = AlgorithmConfig(**data.get("algorithm", {}))
    validation_cfg = ValidationConfig(**data.get("validation", {}))

    return RunConfig(
        input=input_cfg,
        output=output_cfg,
        algorithm=algorithm_cfg,
        validation=validation_cfg,
        fetch=fetch_cfg,
    )
