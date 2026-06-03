"""High-level validation, season detection, and labelling pipeline.

DataFrame-first and config-driven entry points share the same orchestrator. All
algorithm decisions are recorded in ``DiagnosticsReport``.
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
from .metrics import compute_annual_spi_categories, compute_season_metrics
from .seasonality import SeasonalityResult, detect_seasonality_regime
from .seasonality import stl_residuals
from .validate import apply_report, validate_monthly_input

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticsReport:
    """Record of every algorithm decision made during a pipeline run.

    Serialised to the ``<output>.HydroSeason.json`` sidecar file. Fields that are
    ``None`` indicate the corresponding step was skipped (for example,
    ``circular_R`` is ``None`` when ``method="kmeans"``).

    Key fields
    ----------
    regime:
        Detected seasonality regime: ``"seasonal"``, ``"borderline"`` or
        ``"non_seasonal"``.
    regime_source:
        How ``regime`` was decided: ``"stl"`` or ``"rainfall_si_override"``.
    stl_strength:
        STL seasonality strength F_S in [0, 1] (Wang/Hyndman).
    walsh_lawler_si:
        Walsh-Lawler Seasonality Index (rainfall-specific diagnostic).
    hydro_year_start_month:
        Resolved hydrological-year start month (1..12), or ``None`` if uniform.
    smooth_window_used, min_core_length_used, onset_window_months_used:
        Adaptive parameter values resolved from the circular concentration when
        the user left them at their sentinel defaults.
    data_confidence:
        Qualitative data-quality flag: ``"high"``, ``"medium"`` or ``"low"``.
    """

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
    smooth_window_used: int | None = None
    min_core_length_used: int | None = None
    onset_window_months_used: int | None = None
    core_climatology_floor: float | None = None
    shoulder_climatology_floor: float | None = None
    shoulder_residual_threshold: float | None = None
    validation_warnings: list[str] = field(default_factory=list)
    n_input_rows: int = 0
    n_rows_after_validation: int = 0
    n_imputed: int = 0
    n_unimputed: int = 0
    max_consecutive_missing: int = 0
    data_confidence: str = "high"


def _resolve_adaptive_smooth_window(circ_stats: CircularStats | None) -> int:
    """Pick smoothing width from circular concentration. Clamped to [3, 5] so
    concentrated regimes preserve the paper-spec 3-month default, while diffuse
    (low-R) regimes get up to a 5-month window. No upper override for monsoonal
    sharpness — tighter smoothing adds noise without improving onset detection.
    """
    if circ_stats is None or circ_stats.is_uniform:
        return 3
    R = float(circ_stats.concentration_R)
    raw = 2 + 3 * (1 - R)
    return int(max(3, min(5, round(raw))))


def _resolve_adaptive_min_core_length(circ_stats: CircularStats | None) -> int:
    """Minimum wet-run length required to cross a fixed-HY boundary. Scales
    inversely with circular concentration: concentrated regimes can use a
    shorter core (sharp monsoon onsets), diffuse regimes need a longer core
    before allowing boundary crossing. Clamped to [2, 5]; Fitzroy (R≈0.72) → 3.
    """
    if circ_stats is None or circ_stats.is_uniform:
        return 3
    R = float(circ_stats.concentration_R)
    raw = 2 + 4 * (1 - R)
    return int(max(2, min(5, round(raw))))


def _resolve_adaptive_onset_window(
    circ_stats: CircularStats | None,
) -> int | None:
    """Onset acceptance window around the climatological start month.

    Bimodal regimes have two onsets per year so a single anchor + narrow window
    discards real onsets — disable the filter (return None). Unimodal regimes
    keep the conservative ±1 month default that prevents mid-year wet pulses
    from incrementing the hydro-year label.
    """
    if circ_stats is None:
        return 1
    if circ_stats.is_uniform:
        return None
    if circ_stats.is_bimodal:
        return None
    return 1


@dataclass(frozen=True)
class PipelineArtifacts:
    """Bundle returned by every pipeline entry point.

    Attributes
    ----------
    result:
        The main output: the input rows with added ``SeasonType``,
        ``Hydro_Year`` and metric columns. This is what most users want.
    fixed_monthly:
        The 12-row monthly climatology table (mean/median/no-rain counts and the
        fixed Wet/Dry label per calendar month) used as the baseline season.
    wet_boundaries:
        Per-hydro-year wet-season start/end boundaries, or ``None`` for
        non-seasonal regimes where no wet season is delineated.
    seasonality:
        The :class:`~hydroseason.seasonality.SeasonalityResult` with STL
        strength, SI and the chosen regime.
    diagnostics:
        The :class:`DiagnosticsReport` recording every algorithm decision.
    """

    result: pd.DataFrame
    fixed_monthly: pd.DataFrame
    wet_boundaries: pd.DataFrame | None
    seasonality: SeasonalityResult
    diagnostics: DiagnosticsReport


def classify_rainfall(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    year_col: str = "Year",
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
    smooth_window: int | None = None,
    firstpass_quantile: float = 0.20,
    secondpass_quantile: float = 0.10,
    long_period_threshold: int = 16,
    fallback_month: int | None = None,
    method: str = "circular",
    onset_window_months: int | str | None = "auto",
    rainfall_si_override: bool = True,
    rainfall_si_threshold: float = 0.80,
    min_core_length: int | None = None,
    shoulder_climatology_alpha: float = 0.10,
    core_climatology_alpha: float = 0.05,
    shoulder_residual_quantile: float | None = 0.95,
    max_fraction_missing: float = 0.10,
    max_gap_to_interpolate: int = 2,
    max_consecutive_imputation_gap: int = 12,
    raise_on_validation_error: bool = True,
    raise_on_error: bool | None = None,
    output_csv: str | Path | None = None,
) -> PipelineArtifacts:
    """Delineate Wet/Dry seasons and hydrological years from monthly rainfall.

    This is the primary entry point. It validates the input, detects the
    seasonality regime, derives a climatology-based fixed season and
    hydrological-year start, refines the dynamic wet season, and computes
    per-year rainfall metrics. Every decision is recorded in the returned
    :class:`DiagnosticsReport`.

    Parameters
    ----------
    df:
        Monthly rainfall table. Must contain the date, year, month and value
        columns named by ``date_col``, ``year_col``, ``month_col`` and
        ``value_col`` (defaults ``Date``, ``Year``, ``Month``, ``Rainfall_mm``).
    date_col, year_col, month_col, value_col:
        Column names in ``df``.
    smooth_window:
        Centred rolling-mean window (months) applied before segmentation.
        ``None`` (default) resolves adaptively from the circular concentration
        (3-5 months); pass an int to override.
    firstpass_quantile, secondpass_quantile:
        Quantiles of the smoothed series used for the first/second wet-season
        thresholds.
    long_period_threshold:
        Maximum accepted interval between wet-season onsets before trying to
        recover a filtered real Wet onset.
    fallback_month:
        Target month for choosing a recovered Wet onset when an accepted onset
        is absent for too long. ``None`` derives it from the data.
    method:
        Fixed-season method: ``"circular"`` (default, transferable) or
        ``"kmeans"`` (legacy).
    onset_window_months:
        Acceptance window (months) around the climatological start for counting
        a wet onset. ``"auto"`` (default) disables it for bimodal/uniform
        regimes and uses +/-1 month otherwise; ``None`` disables it; an int sets
        it explicitly.
    rainfall_si_override, rainfall_si_threshold:
        When the Walsh-Lawler SI is at least ``rainfall_si_threshold`` and STL is
        at least borderline, promote the regime to ``seasonal``.
    min_core_length:
        Minimum consecutive wet-run length to cross a fixed-HY boundary.
        ``None`` resolves adaptively.
    shoulder_climatology_alpha, core_climatology_alpha:
        Site-scaling factors applied to the wet-month climatology median to set
        the shoulder/core absorption floors.
    shoulder_residual_quantile:
        Quantile of positive STL residuals above which a candidate shoulder is
        rejected as an isolated storm. ``None`` disables the gate.
    max_fraction_missing, max_gap_to_interpolate, max_consecutive_imputation_gap:
        Validation/imputation controls. Gaps longer than
        ``max_consecutive_imputation_gap`` months raise instead of being filled.
    raise_on_validation_error:
        If ``True`` (default) a validation failure raises; otherwise it is
        recorded as a warning and the run continues. ``raise_on_error`` is a
        deprecated alias.
    output_csv:
        Optional path to write ``artifacts.result`` as a CSV file. The parent
        directory is created if it does not exist. ``None`` (default) skips
        writing.

    Returns
    -------
    PipelineArtifacts
        Bundle of ``result``, ``fixed_monthly``, ``wet_boundaries``,
        ``seasonality`` and ``diagnostics``.

    Examples
    --------
    >>> import pandas as pd
    >>> from hydroseason import classify_rainfall
    >>> df = pd.read_csv("data/monthly_rainfall.csv")
    >>> artifacts = classify_rainfall(df)
    >>> artifacts.result[["Date", "SeasonType", "Hydro_Year"]].head()
    >>> artifacts.diagnostics.regime
    'seasonal'
    """
    if raise_on_error is not None:
        raise_on_validation_error = raise_on_error

    # ---- Step 0 — validate & normalise
    cleaned, report = validate_monthly_input(
        df,
        date_col=date_col,
        year_col=year_col,
        month_col=month_col,
        value_col=value_col,
        max_fraction_missing=max_fraction_missing,
        max_gap_to_interpolate=max_gap_to_interpolate,
        max_consecutive_imputation_gap=max_consecutive_imputation_gap,
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
        (
            fixed_monthly,
            hydro_year_start_month,
            circ_stats,
        ) = circular_climatology(
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

    # ---- Step 1.5 — resolve adaptive algorithm parameters from regime
    smooth_window_used = (
        int(smooth_window) if smooth_window is not None
        else _resolve_adaptive_smooth_window(circ_stats)
    )
    min_core_length_used = (
        int(min_core_length) if min_core_length is not None
        else _resolve_adaptive_min_core_length(circ_stats)
    )
    if onset_window_months == "auto":
        onset_window_resolved: int | None = _resolve_adaptive_onset_window(
            circ_stats
        )
    elif onset_window_months is None:
        onset_window_resolved = None
    else:
        onset_window_resolved = int(onset_window_months)

    # Site-scaled rainfall floors derived from the climatological wet months.
    # When no wet months exist in the climatology the floors collapse to 0.
    wet_clim = fixed_monthly.loc[
        fixed_monthly["Season"] == "Wet", "median"
    ].dropna()
    wet_clim_median = float(wet_clim.median()) if len(wet_clim) else 0.0
    core_clim_floor = float(wet_clim_median * core_climatology_alpha)
    shoulder_clim_floor = float(wet_clim_median * shoulder_climatology_alpha)

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
    shoulder_residual_threshold: float | None = None

    if shoulder_residual_quantile is not None:
        shoulder_residual_quantile = float(shoulder_residual_quantile)
        if not 0.0 <= shoulder_residual_quantile <= 1.0:
            raise ValueError(
                "shoulder_residual_quantile must be between 0 and 1, "
                "or None to disable."
            )

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
        if len(nonzero):
            quantile_value = float(nonzero.quantile(firstpass_quantile))
        else:
            quantile_value = 0.0
        # Climatology floor protects the wet-core detection in arid regimes
        # where non-zero quantiles can collapse to a few mm.
        threshold_first = max(quantile_value, core_clim_floor)
        work = harmonize_with_zero_preservation(
            work, value_col=value_col, window=smooth_window_used
        )
        segmented_df, wet_boundaries = segment_main_wet_season_fixed_threshold(
            work,
            date_col=date_col,
            hydro_year_col="Hydro_Year_fixed",
            smoothed_col="Smoothed",
            threshold=threshold_first,
        )
        threshold_second = (
            float(
                segmented_df[segmented_df[value_col] > 0][value_col].quantile(
                    secondpass_quantile
                )
            )
            if (segmented_df[value_col] > 0).any() else 0.0
        )
        residual_col = None
        if shoulder_residual_quantile is not None:
            residual_col = "_STL_Residual"
            segmented_df[residual_col] = stl_residuals(
                segmented_df,
                date_col=date_col,
                value_col=value_col,
            )
            positive_residuals = segmented_df.loc[
                segmented_df[residual_col] > 0,
                residual_col,
            ].dropna()
            if len(positive_residuals):
                shoulder_residual_threshold = float(
                    positive_residuals.quantile(shoulder_residual_quantile)
                )
        segmented_df = refine_season_tails(
            segmented_df,
            rainfall_col=value_col,
            date_col=date_col,
            threshold_high=threshold_second,
            threshold_low=0.0,
            min_core_length=min_core_length_used,
            climatology_floor=shoulder_clim_floor,
            residual_col=residual_col,
            residual_threshold=shoulder_residual_threshold,
        )
        if residual_col is not None and residual_col in segmented_df.columns:
            segmented_df = segmented_df.drop(columns=[residual_col])
        out = assign_hydro_years(
            segmented_df,
            long_period_threshold=long_period_threshold,
            fallback_month=fallback_month_used,
            hydro_year_start_month=hydro_year_start_month,
            onset_window_months=onset_window_resolved,
            date_col=date_col,
            year_col=year_col,
            month_col=month_col,
        )

    out["Seasonality_SI"] = seasonality.si
    out["Seasonality_STL"] = seasonality.stl_strength
    out["Seasonality_Regime"] = seasonality.regime

    if "Hydro_Year" in out.columns and "SeasonType" in out.columns:
        out = compute_season_metrics(out, value_col=value_col)
        if value_col == "Rainfall_mm":
            out = compute_annual_spi_categories(out, value_col=value_col)

    diagnostics = DiagnosticsReport(
        regime=seasonality.regime,
        regime_source=seasonality.regime_source,
        stl_strength=seasonality.stl_strength,
        walsh_lawler_si=seasonality.si,
        kmeans_silhouette=seasonality.silhouette,
        circular_R=(circ_stats.concentration_R if circ_stats else None),
        is_bimodal=(circ_stats.is_bimodal if circ_stats else None),
        is_uniform=(circ_stats.is_uniform if circ_stats else None),
        hydro_year_start_month=(
            int(hydro_year_start_month) if hydro_year_start_month else None
        ),
        fallback_month_used=fallback_month_used,
        threshold_firstpass=threshold_first,
        threshold_secondpass=threshold_second,
        rainfall_si_override=rainfall_si_override,
        smooth_window_used=smooth_window_used,
        min_core_length_used=min_core_length_used,
        onset_window_months_used=onset_window_resolved,
        core_climatology_floor=core_clim_floor,
        shoulder_climatology_floor=shoulder_clim_floor,
        shoulder_residual_threshold=shoulder_residual_threshold,
        validation_warnings=list(report.warnings),
        n_input_rows=report.n_rows_in,
        n_rows_after_validation=report.n_rows_out,
        n_imputed=report.n_imputed,
        n_unimputed=report.n_unimputed,
        max_consecutive_missing=report.max_consecutive_missing,
        data_confidence=report.data_confidence,
    )

    artifacts = PipelineArtifacts(
        result=out,
        fixed_monthly=fixed_monthly,
        wet_boundaries=wet_boundaries,
        seasonality=seasonality,
        diagnostics=diagnostics,
    )
    if output_csv is not None:
        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        artifacts.result.to_csv(out_path, index=False)
    return artifacts


def run_pipeline(config: RunConfig) -> pd.DataFrame:
    if config.fetch.enabled:
        from .fetch import (
            get_monthly_silo_rainfall,
            get_monthly_era5_rainfall,
            load_vector,
        )

        if not config.fetch.vector_path:
            raise ValueError(
                "fetch.vector_path is required when fetch.enabled=true"
            )
        if config.fetch.start_year is None or config.fetch.end_year is None:
            raise ValueError(
                "fetch.start_year and fetch.end_year are required when "
                "fetch.enabled=true"
            )

        gdf = load_vector(config.fetch.vector_path)
        source = config.fetch.source.lower().strip()
        if source == "era5":
            if not config.fetch.era5_zarr_path:
                raise ValueError(
                    "fetch.era5_zarr_path is required when fetch.source='era5'"
                )
            in_df = get_monthly_era5_rainfall(
                path=config.fetch.era5_zarr_path,
                gdf=gdf,
                start_year=config.fetch.start_year,
                end_year=config.fetch.end_year,
                variable=config.fetch.variable,
                cache_dir=config.fetch.cache_dir,
                spatial_chunk=config.fetch.spatial_chunk,
            )
        elif source == "silo":
            kwargs = {
                "gdf": gdf,
                "start_year": config.fetch.start_year,
                "end_year": config.fetch.end_year,
                "cache_dir": config.fetch.cache_dir,
                "spatial_chunk": config.fetch.spatial_chunk,
            }
            if config.fetch.silo_base_url:
                kwargs["base_url"] = config.fetch.silo_base_url
            in_df = get_monthly_silo_rainfall(**kwargs)
        else:
            raise ValueError("fetch.source must be one of {'era5', 'silo'}")
    else:
        if config.input.csv_path is None:
            raise ValueError(
                "input.csv_path is required when fetch.enabled=false"
            )
        in_df = pd.read_csv(config.input.csv_path)
    artifacts = classify_rainfall(
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
        min_core_length=config.algorithm.min_core_length,
        shoulder_climatology_alpha=config.algorithm.shoulder_climatology_alpha,
        core_climatology_alpha=config.algorithm.core_climatology_alpha,
        shoulder_residual_quantile=config.algorithm.shoulder_residual_quantile,
        max_fraction_missing=config.validation.max_fraction_missing,
        max_gap_to_interpolate=config.validation.max_gap_to_interpolate,
        max_consecutive_imputation_gap=(
            config.validation.max_consecutive_imputation_gap
        ),
        raise_on_validation_error=config.validation.raise_on_error,
    )

    output_path = Path(config.output.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.result.to_csv(output_path, index=False)

    diag_path = output_path.with_suffix(".HydroSeason.json")
    import json
    diag_path.write_text(
        json.dumps(asdict(artifacts.diagnostics), default=str, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote results: %s", output_path)
    logger.info("Wrote diagnostics: %s", diag_path)
    return artifacts.result


def classify_rainfall_from_file(
    path: str | Path,
    *,
    source: str = "auto",
    value_col: str = "Rainfall_mm",
    silo_variable: str = "Rain",
    bom_value_col: str | None = None,
    bom_quality_filter: bool = True,
    output_csv: str | Path | None = None,
    **kwargs,
) -> PipelineArtifacts:
    """Read a rainfall file and run the full classification pipeline in one call.

    Uses ``hydroseason.io.read_rainfall`` for ingestion (auto-detects BoM,
    SILO, and generic CSV), then calls :func:`classify_rainfall`.
    """
    from .io import read_rainfall

    df = read_rainfall(
        path,
        source=source,
        value_col=value_col,
        silo_variable=silo_variable,
        bom_value_col=bom_value_col,
        bom_quality_filter=bom_quality_filter,
    )
    if "value_col" not in kwargs:
        kwargs["value_col"] = value_col
    return classify_rainfall(df, output_csv=output_csv, **kwargs)


# Convenience one-liner — best for quick notebook exploration.
def classify_rainfall_df(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Run the full classification pipeline and return just the result DataFrame.

    This is the simplest entry point: pass in your monthly rainfall DataFrame
    and get back the labelled result with ``SeasonType`` and ``Hydro_Year``
    columns.  If you also need diagnostics, wet boundaries, or the fixed
    climatology, use :func:`classify_rainfall` instead (it returns the full
    :class:`PipelineArtifacts` bundle).
    """
    return classify_rainfall(df, **kwargs).result
