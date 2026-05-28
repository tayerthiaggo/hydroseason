"""High-level pipeline: validate → detect regime → fixed season → dynamic season → metrics.

DataFrame-first (Jupyter friendly) and config-driven (CLI) entry points share the
same orchestrator. All algorithm decisions (regime, fallback month, thresholds) are
recorded in a ``DiagnosticsReport`` returned alongside the result.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from .config import RunConfig
from .dynamic_season import (
    harmonize_with_zero_preservation,
    refine_season_tails,
    segment_main_wet_season_fixed_threshold,
)
from .fixed_season import (
    CircularStats,
    circular_climatology,
    hydro_year_start_after_min_month,
    identify_fixed_hydro_year,
)
from .hydro_year import assign_fixed_hydro_year, assign_hydro_years
from .metrics import compute_season_metrics
from .seasonality import SeasonalityResult, detect_seasonality_regime
from .validate import ValidationReport, apply_report, validate_monthly_input

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticsReport:
    regime: str
    regime_source: str
    stl_strength: float
    walsh_lawler_si: float
    kmeans_silhouette: float | None
    circular_R: float | None
    is_bimodal: bool | None
    is_uniform: bool | None
    hydro_year_start_month: int | None
    fallback_month_used: int
    threshold_firstpass: float | None
    threshold_secondpass: float | None
    rainfall_si_override: bool
    validation_warnings: list[str] = field(default_factory=list)
    n_input_rows: int = 0
    n_rows_after_validation: int = 0
    n_imputed: int = 0


@dataclass(frozen=True)
class PipelineArtifacts:
    result: pd.DataFrame
    fixed_monthly: pd.DataFrame
    wet_boundaries: pd.DataFrame | None
    seasonality: SeasonalityResult
    diagnostics: DiagnosticsReport


def delineate_monthly_dataframe(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    year_col: str = "Year",
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
    smooth_window: int = 3,
    firstpass_quantile: float = 0.20,
    secondpass_quantile: float = 0.10,
    long_period_threshold: int = 16,
    fallback_month: int | None = None,
    method: str = "circular",
    onset_window_months: int | None = 1,
    rainfall_si_override: bool = True,
    rainfall_si_threshold: float = 0.80,
    max_fraction_missing: float = 0.10,
    max_gap_to_interpolate: int = 2,
    raise_on_validation_error: bool = True,
) -> PipelineArtifacts:
    # ---- Step 0 — validate & normalise
    cleaned, report = validate_monthly_input(
        df,
        date_col=date_col,
        year_col=year_col,
        month_col=month_col,
        value_col=value_col,
        max_fraction_missing=max_fraction_missing,
        max_gap_to_interpolate=max_gap_to_interpolate,
    )
    apply_report(report, raise_on_error=raise_on_validation_error)

    # ---- Step 0.5 — regime detection
    seasonality = detect_seasonality_regime(
        cleaned,
        date_col=date_col,
        month_col=month_col,
        value_col=value_col,
        rainfall_si_override=rainfall_si_override,
        si_strong_threshold=rainfall_si_threshold,
    )

    # ---- Step 1 — fixed (baseline) season + start month
    if method == "kmeans":
        fixed_monthly, hydro_year_start_month = identify_fixed_hydro_year(
            cleaned, value_col=value_col, month_col=month_col
        )
        circ_stats: CircularStats | None = None
    else:
        fixed_monthly, hydro_year_start_month, circ_stats = circular_climatology(
            cleaned, value_col=value_col, month_col=month_col
        )

    # Auto-derive fallback month from data if user did not specify one.
    if fallback_month is None:
        fb_month, _min_month = hydro_year_start_after_min_month(
            cleaned, value_col=value_col, month_col=month_col
        )
        fallback_month_used = int(fb_month)
    else:
        fallback_month_used = int(fallback_month)

    if hydro_year_start_month is None:
        hydro_year_start_month = fallback_month_used

    work = assign_fixed_hydro_year(
        cleaned,
        start_month=hydro_year_start_month,
        year_col=year_col,
        month_col=month_col,
        date_col=date_col,
        out_col="Hydro_Year_fixed",
    )

    wet_boundaries: pd.DataFrame | None = None
    threshold_first: float | None = None
    threshold_second: float | None = None

    if seasonality.regime == "non_seasonal":
        out = work.copy()
        out["SeasonType"] = "Unclassified"
        out["SeasonShift"] = out["SeasonType"].ne(out["SeasonType"].shift())
        out["Hydro_Year"] = out[year_col].astype(int)

    elif seasonality.regime == "borderline":
        month_to_season = fixed_monthly["Season"].to_dict()
        out = work.copy()
        out["SeasonType"] = out[month_col].map(month_to_season).fillna("Dry")
        out["SeasonShift"] = out["SeasonType"].ne(out["SeasonType"].shift())
        out["Hydro_Year"] = out["Hydro_Year_fixed"]

    else:
        nonzero = work[work[value_col] > 0][value_col]
        threshold_first = float(nonzero.quantile(firstpass_quantile)) if len(nonzero) else 0.0
        work = harmonize_with_zero_preservation(work, value_col=value_col, window=smooth_window)
        segmented_df, wet_boundaries = segment_main_wet_season_fixed_threshold(
            work,
            date_col=date_col,
            hydro_year_col="Hydro_Year_fixed",
            smoothed_col="Smoothed",
            threshold=threshold_first,
        )
        threshold_second = (
            float(segmented_df[segmented_df[value_col] > 0][value_col].quantile(secondpass_quantile))
            if (segmented_df[value_col] > 0).any() else 0.0
        )
        segmented_df = refine_season_tails(
            segmented_df,
            rainfall_col=value_col,
            date_col=date_col,
            threshold_high=threshold_second,
            threshold_low=0.0,
        )
        out = assign_hydro_years(
            segmented_df,
            long_period_threshold=long_period_threshold,
            fallback_month=fallback_month_used,
            hydro_year_start_month=hydro_year_start_month,
            onset_window_months=onset_window_months,
            date_col=date_col,
            year_col=year_col,
            month_col=month_col,
        )

    out["Seasonality_SI"] = seasonality.si
    out["Seasonality_STL"] = seasonality.stl_strength
    out["Seasonality_Regime"] = seasonality.regime

    if "Hydro_Year" in out.columns and "SeasonType" in out.columns:
        out = compute_season_metrics(out, value_col=value_col)

    diagnostics = DiagnosticsReport(
        regime=seasonality.regime,
        regime_source=seasonality.regime_source,
        stl_strength=seasonality.stl_strength,
        walsh_lawler_si=seasonality.si,
        kmeans_silhouette=seasonality.silhouette,
        circular_R=(circ_stats.concentration_R if circ_stats else None),
        is_bimodal=(circ_stats.is_bimodal if circ_stats else None),
        is_uniform=(circ_stats.is_uniform if circ_stats else None),
        hydro_year_start_month=int(hydro_year_start_month) if hydro_year_start_month else None,
        fallback_month_used=fallback_month_used,
        threshold_firstpass=threshold_first,
        threshold_secondpass=threshold_second,
        rainfall_si_override=rainfall_si_override,
        validation_warnings=list(report.warnings),
        n_input_rows=report.n_rows_in,
        n_rows_after_validation=report.n_rows_out,
        n_imputed=report.n_imputed,
    )

    return PipelineArtifacts(
        result=out,
        fixed_monthly=fixed_monthly,
        wet_boundaries=wet_boundaries,
        seasonality=seasonality,
        diagnostics=diagnostics,
    )


def run_pipeline(config: RunConfig) -> pd.DataFrame:
    in_df = pd.read_csv(config.input.csv_path)
    artifacts = delineate_monthly_dataframe(
        in_df,
        date_col=config.input.date_col,
        year_col=config.input.year_col,
        month_col=config.input.month_col,
        value_col=config.input.value_col,
        smooth_window=config.algorithm.smooth_window,
        firstpass_quantile=config.algorithm.firstpass_quantile,
        secondpass_quantile=config.algorithm.secondpass_quantile,
        long_period_threshold=config.algorithm.long_period_threshold,
        fallback_month=config.algorithm.fallback_month,
        method=config.algorithm.method,
        onset_window_months=config.algorithm.onset_window_months,
        rainfall_si_override=config.algorithm.rainfall_si_override,
        rainfall_si_threshold=config.algorithm.rainfall_si_threshold,
        max_fraction_missing=config.validation.max_fraction_missing,
        max_gap_to_interpolate=config.validation.max_gap_to_interpolate,
        raise_on_validation_error=config.validation.raise_on_error,
    )

    output_path = Path(config.output.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.result.to_csv(output_path, index=False)

    diag_path = output_path.with_suffix(".HydroSeason.json")
    import json
    diag_path.write_text(json.dumps(asdict(artifacts.diagnostics), default=str, indent=2), encoding="utf-8")
    logger.info("Wrote results: %s", output_path)
    logger.info("Wrote diagnostics: %s", diag_path)
    return artifacts.result


def run_pipeline_from_csv(
    csv_path: str | Path,
    *,
    output_csv: str | Path | None = None,
    **kwargs,
) -> PipelineArtifacts:
    df = pd.read_csv(csv_path)
    artifacts = delineate_monthly_dataframe(df, **kwargs)
    if output_csv is not None:
        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        artifacts.result.to_csv(out_path, index=False)
    return artifacts


# Convenience one-liner — best for quick notebook exploration.
def classify(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Run the pipeline with defaults and return just the result DataFrame."""
    return delineate_monthly_dataframe(df, **kwargs).result
