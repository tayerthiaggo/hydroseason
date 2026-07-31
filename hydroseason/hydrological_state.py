from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ._aggregation import aggregate_basin_monthly_extent
from ._boundary import robust_scale
from ._condition import (
    classify_annual_surface_water_condition,
    compute_monthly_surface_water_condition,
)
from ._dynamic_year import (
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
    suggest_dynamic_hydro_year_config,
)
from ._seasonality import SeasonalPatternResult, classify_seasonal_pattern
from ._state_input import QualityPolicy, prepare_monthly_extent


@dataclass(frozen=True)
class HydrologicalStateResult:
    pattern: SeasonalPatternResult
    config: DynamicHydroYearConfig
    hydro_years: pd.DataFrame
    monthly_condition: pd.DataFrame
    data_quality: dict


def analyze_hydrological_state(
    extent,
    *,
    config: DynamicHydroYearConfig | None = None,
    reference_start=None,
    reference_end=None,
    reference: str = "full_record",
    rolling_window_cycles: int = 10,
    rolling_min_cycles: int = 5,
    n_bootstrap: int = 200,
    random_state: int = 0,
    quality_policy: QualityPolicy = "exclude",
) -> HydrologicalStateResult:
    effective_quality_policy = config.quality_policy if config is not None else quality_policy
    pattern = classify_seasonal_pattern(
        extent, n_bootstrap=n_bootstrap, random_state=random_state, quality_policy=effective_quality_policy
    )
    selected = config or suggest_dynamic_hydro_year_config(
        extent, pattern=pattern, quality_policy=effective_quality_policy
    )
    annual = detect_dynamic_hydrological_years(extent, config=selected, pattern=pattern)
    prepared = prepare_monthly_extent(
        extent, max_invalid_pct=selected.max_invalid_pct,
        allow_unknown_quality=selected.allow_unknown_quality,
        quality_policy=selected.quality_policy,
    )
    _amplitude_pp, noise_pp = robust_scale(prepared)
    annual = classify_annual_surface_water_condition(
        annual,
        reference=reference,
        reference_start=reference_start,
        reference_end=reference_end,
        rolling_window_cycles=rolling_window_cycles,
        rolling_min_cycles=rolling_min_cycles,
        min_baseline_cycles=selected.min_baseline_cycles,
        low_percentile=selected.low_percentile,
        high_percentile=selected.high_percentile,
        low_variability=pattern.pattern == "low_variability",
        noise_pp=noise_pp,
    )
    monthly = compute_monthly_surface_water_condition(
        extent, reference_start=reference_start, reference_end=reference_end,
        max_invalid_pct=selected.max_invalid_pct,
        allow_unknown_quality=selected.allow_unknown_quality,
        quality_policy=selected.quality_policy,
    )
    quality = prepared["quality_state"].value_counts().to_dict()
    quality["n_usable"] = int(prepared["candidate_usable"].sum())
    quality["n_months"] = int(len(prepared))
    return HydrologicalStateResult(pattern, selected, annual, monthly, quality)


__all__ = [
    "DynamicHydroYearConfig", "HydrologicalStateResult", "SeasonalPatternResult",
    "aggregate_basin_monthly_extent", "analyze_hydrological_state",
    "classify_annual_surface_water_condition", "classify_seasonal_pattern",
    "compute_monthly_surface_water_condition", "detect_dynamic_hydrological_years",
    "suggest_dynamic_hydro_year_config",
]
