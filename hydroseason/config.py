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
    report_kmeans_silhouette: bool = False      # legacy KMeans diagnostic; opt in for parity
    onset_window_months: int | str | None = "auto"  # "auto" | None | int
    rainfall_si_override: bool = True
    rainfall_si_threshold: float = 0.80
    min_core_length: int | None = None         # None → auto from circular concentration
    shoulder_climatology_alpha: float = 0.10   # shoulder absorption floor (α * median wet-month clim)
    shoulder_month_quantile: float | None = 0.60  # month-aware shoulder extension floor; None disables
    core_climatology_alpha: float = 0.05       # wet-core detection floor (arid-regime safety)
    shoulder_residual_quantile: float | None = 0.95  # positive STL-residual quantile gate; None disables
    climatology_window: str = "rolling"        # "rolling" | "global"
    climatology_window_years: int = 10
    climatology_window_mode: str = "trailing"  # "trailing" | "centered"
    climatology_min_month_observations: int = 5
    climatology_min_wet_year_fraction: float = 0.60
    cap_rolling_tail_at_global: bool = True
    keep_debug_columns: bool = False
    require_low_floor_break_for_pruning: bool = True
    regime_window_years: int = 0
    segmentation_method: str = "heuristic"      # "heuristic" | "cumulative_anomaly" | "hybrid"
    cumulative_anomaly_reference_floor: float = 10.0
    cumulative_anomaly_absolute_floor: float = 10.0
    cumulative_anomaly_smooth: bool = True
    cumulative_anomaly_stl_gate: bool = False
    cumulative_anomaly_multi_year: bool = False

    def __post_init__(self) -> None:
        if self.smooth_window is not None:
            self.smooth_window = int(self.smooth_window)
        self.firstpass_quantile = float(self.firstpass_quantile)
        self.secondpass_quantile = float(self.secondpass_quantile)
        self.long_period_threshold = int(self.long_period_threshold)
        if self.fallback_month is not None:
            self.fallback_month = int(self.fallback_month)
        if isinstance(self.onset_window_months, str) and self.onset_window_months.strip().lower() == "none":
            self.onset_window_months = None
        elif self.onset_window_months is not None and self.onset_window_months != "auto":
            self.onset_window_months = int(self.onset_window_months)
        self.rainfall_si_override = bool(self.rainfall_si_override)
        self.rainfall_si_threshold = float(self.rainfall_si_threshold)
        if self.min_core_length is not None:
            self.min_core_length = int(self.min_core_length)
        self.shoulder_climatology_alpha = float(self.shoulder_climatology_alpha)
        if self.shoulder_month_quantile is not None:
            self.shoulder_month_quantile = float(self.shoulder_month_quantile)
        self.core_climatology_alpha = float(self.core_climatology_alpha)
        if self.shoulder_residual_quantile is not None:
            self.shoulder_residual_quantile = float(self.shoulder_residual_quantile)
        self.climatology_window_years = int(self.climatology_window_years)
        self.climatology_min_month_observations = int(self.climatology_min_month_observations)
        self.climatology_min_wet_year_fraction = float(self.climatology_min_wet_year_fraction)
        self.cap_rolling_tail_at_global = bool(self.cap_rolling_tail_at_global)
        self.keep_debug_columns = bool(self.keep_debug_columns)
        self.require_low_floor_break_for_pruning = bool(self.require_low_floor_break_for_pruning)
        self.regime_window_years = int(self.regime_window_years)
        self.segmentation_method = str(self.segmentation_method).strip().lower()
        if self.segmentation_method not in {"heuristic", "cumulative_anomaly", "hybrid"}:
            raise ValueError("segmentation_method must be one of {'heuristic', 'cumulative_anomaly', 'hybrid'}")
        self.cumulative_anomaly_reference_floor = float(self.cumulative_anomaly_reference_floor)
        self.cumulative_anomaly_absolute_floor = float(self.cumulative_anomaly_absolute_floor)
        self.cumulative_anomaly_smooth = bool(self.cumulative_anomaly_smooth)
        self.cumulative_anomaly_stl_gate = bool(self.cumulative_anomaly_stl_gate)
        self.cumulative_anomaly_multi_year = bool(self.cumulative_anomaly_multi_year)



@dataclass
class ValidationConfig:
    max_fraction_missing: float = 0.10
    max_gap_to_interpolate: int = 2
    max_consecutive_imputation_gap: int = 12
    raise_on_error: bool = True

    def __post_init__(self) -> None:
        self.max_fraction_missing = float(self.max_fraction_missing)
        self.max_gap_to_interpolate = int(self.max_gap_to_interpolate)
        self.max_consecutive_imputation_gap = int(self.max_consecutive_imputation_gap)
        self.raise_on_error = bool(self.raise_on_error)


@dataclass
class FetchConfig:
    enabled: bool = False
    source: str = "auto"          # "auto" | "silo" | "chirps" | "era5"
    era5_zarr_path: str | None = None
    silo_base_url: str | None = None
    chirps_base_url: str | None = None
    vector_path: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    variable: str = "rainfall"      # legacy selector; only rainfall is supported
    cache_dir: str | None = None
    spatial_chunk: int | str | None = "auto"
    time_chunk: int | str | None = "auto"
    temporal_batch_years: int | str | None = "auto"
    era5_fallback: bool = True
    large_era5_fallback: str = "ask"

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        if self.start_year is not None:
            self.start_year = int(self.start_year)
        if self.end_year is not None:
            self.end_year = int(self.end_year)
        if self.spatial_chunk is not None and self.spatial_chunk != "auto":
            self.spatial_chunk = int(self.spatial_chunk)
        if self.time_chunk is not None and self.time_chunk != "auto":
            self.time_chunk = int(self.time_chunk)
        if (
            self.temporal_batch_years is not None
            and self.temporal_batch_years != "auto"
        ):
            self.temporal_batch_years = int(self.temporal_batch_years)
        self.era5_fallback = bool(self.era5_fallback)
        self.large_era5_fallback = str(self.large_era5_fallback).strip().lower()
        if self.large_era5_fallback not in {"ask", "allow", "error"}:
            raise ValueError(
                "fetch.large_era5_fallback must be one of "
                "{'ask', 'allow', 'error'}."
            )


@dataclass
class DailyDetectionConfig:
    onset_persistence_days: int = 21
    cessation_persistence_days: int = 21
    baseline_roll_window_days: int = 30

    def __post_init__(self) -> None:
        self.onset_persistence_days = int(self.onset_persistence_days)
        self.cessation_persistence_days = int(self.cessation_persistence_days)
        self.baseline_roll_window_days = int(self.baseline_roll_window_days)


@dataclass
class DailyValidationConfig:
    max_fraction_missing: float = 0.10
    raise_on_error: bool = True

    def __post_init__(self) -> None:
        self.max_fraction_missing = float(self.max_fraction_missing)
        self.raise_on_error = bool(self.raise_on_error)


@dataclass
class RunConfig:
    input: InputConfig
    output: OutputConfig
    algorithm: AlgorithmConfig = field(default_factory=AlgorithmConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    fetch: FetchConfig = field(default_factory=FetchConfig)
    daily_detection: DailyDetectionConfig = field(default_factory=DailyDetectionConfig)
    daily_validation: DailyValidationConfig = field(default_factory=DailyValidationConfig)


def _require(d: dict, key: str) -> object:
    if key not in d:
        raise KeyError(
            f"Missing required config section/key: '{key}'. "
            "See config/example.yaml for the expected structure."
        )
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
    daily_detection_cfg = DailyDetectionConfig(**data.get("daily_detection", {}))
    daily_validation_cfg = DailyValidationConfig(**data.get("daily_validation", {}))

    return RunConfig(
        input=input_cfg,
        output=output_cfg,
        algorithm=algorithm_cfg,
        validation=validation_cfg,
        fetch=fetch_cfg,
        daily_detection=daily_detection_cfg,
        daily_validation=daily_validation_cfg,
    )

