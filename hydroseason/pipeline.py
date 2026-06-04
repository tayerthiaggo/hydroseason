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
    tail_floor: float | None = None
    smooth_window_used: int | None = None
    min_core_length_used: int | None = None
    onset_window_months_used: int | None = None
    core_climatology_floor: float | None = None
    shoulder_climatology_floor: float | None = None
    shoulder_month_quantile: float | None = None
    shoulder_month_floor_source: str | None = None
    climatology_window: str | None = None
    climatology_window_years: int | None = None
    climatology_window_mode: str | None = None
    climatology_min_month_observations: int | None = None
    climatology_min_wet_year_fraction: float | None = None
    climatology_guardrail_source: str | None = None
    climatology_guardrail_fallback_count: int = 0
    climatology_unstable_month_count: int = 0
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


def _month_quantile_floor(
    df: pd.DataFrame,
    *,
    month_col: str,
    value_col: str,
    quantile: float,
    imputed_col: str = "Imputed",
    min_observed_per_month: int = 3,
) -> tuple[pd.Series, str]:
    """Calendar-month quantile floors, preferring observed rows over imputes."""
    all_floor = (
        df.groupby(month_col)[value_col]
        .quantile(quantile)
        .reindex(range(1, 13))
    )
    if imputed_col not in df.columns:
        return all_floor, "all"

    observed = df[~df[imputed_col].fillna(False).astype(bool)]
    observed_counts = (
        observed.groupby(month_col)[value_col]
        .count()
        .reindex(range(1, 13), fill_value=0)
    )
    observed_floor = (
        observed.groupby(month_col)[value_col]
        .quantile(quantile)
        .reindex(range(1, 13))
    )
    enough_observed = observed_counts >= min_observed_per_month
    floor = observed_floor.where(enough_observed, all_floor)
    source = "observed" if bool(enough_observed.all()) else "observed_with_fallback"
    return floor, source


def _observed_rows(df: pd.DataFrame, imputed_col: str = "Imputed") -> pd.DataFrame:
    if imputed_col not in df.columns:
        return df
    return df[~df[imputed_col].fillna(False).astype(bool)]


def _has_month_coverage(
    df: pd.DataFrame,
    *,
    month_col: str,
    value_col: str,
    min_observed_per_month: int,
) -> bool:
    observed = _observed_rows(df)
    counts = (
        observed.groupby(month_col)[value_col]
        .count()
        .reindex(range(1, 13), fill_value=0)
    )
    return bool((counts >= int(min_observed_per_month)).all())


def _fixed_monthly_for_method(
    df: pd.DataFrame,
    *,
    method: str,
    month_col: str,
    value_col: str,
) -> pd.DataFrame:
    if method == "kmeans":
        fixed, _start = identify_fixed_hydro_year(
            df, value_col=value_col, month_col=month_col
        )
    else:
        fixed, _start, _stats = circular_climatology(
            df, value_col=value_col, month_col=month_col
        )
    return fixed


def _window_subset(
    df: pd.DataFrame,
    *,
    hydro_year_col: str,
    hydro_year: int,
    years: int,
    mode: str,
) -> pd.DataFrame:
    if mode == "trailing":
        start = hydro_year - years + 1
        end = hydro_year
    elif mode == "centered":
        before = (years - 1) // 2
        after = years - 1 - before
        start = hydro_year - before
        end = hydro_year + after
    else:
        raise ValueError('climatology_window_mode must be "trailing" or "centered".')
    return df[(df[hydro_year_col] >= start) & (df[hydro_year_col] <= end)]


def _guardrail_values(
    df: pd.DataFrame,
    fixed_monthly: pd.DataFrame,
    *,
    month_col: str,
    value_col: str,
    firstpass_quantile: float,
    core_climatology_alpha: float,
    shoulder_climatology_alpha: float,
    shoulder_month_quantile: float | None,
) -> tuple[float, float, pd.Series, pd.Series | None, str | None]:
    wet_clim = fixed_monthly.loc[fixed_monthly["Season"] == "Wet", "median"].dropna()
    wet_median = float(wet_clim.median()) if len(wet_clim) else 0.0
    core_floor = float(wet_median * core_climatology_alpha)
    shoulder_floor = float(wet_median * shoulder_climatology_alpha)

    observed = _observed_rows(df)
    values_for_threshold = observed if len(observed) else df
    nonzero = values_for_threshold.loc[values_for_threshold[value_col] > 0, value_col]
    quantile_value = float(nonzero.quantile(firstpass_quantile)) if len(nonzero) else 0.0
    tail_floor = max(quantile_value, core_floor)

    baseline_wet = fixed_monthly["Season"].eq("Wet").reindex(range(1, 13), fill_value=False)
    month_floor = None
    month_source = None
    if shoulder_month_quantile is not None:
        month_floor, month_source = _month_quantile_floor(
            df,
            month_col=month_col,
            value_col=value_col,
            quantile=shoulder_month_quantile,
        )
    return tail_floor, shoulder_floor, baseline_wet, month_floor, month_source


def _stable_wet_months(
    df: pd.DataFrame,
    baseline_wet: pd.Series,
    *,
    month_col: str,
    value_col: str,
    floor: float,
    min_wet_year_fraction: float,
) -> tuple[pd.Series, int]:
    """Filter local Wet months to those repeatedly wet in the window."""
    wet = baseline_wet.reindex(range(1, 13), fill_value=False).astype(bool)
    if min_wet_year_fraction <= 0.0:
        return wet, 0

    observed = _observed_rows(df)
    values_for_support = observed if len(observed) else df
    support = (
        values_for_support.assign(_WetSupport=values_for_support[value_col] >= floor)
        .groupby(month_col)["_WetSupport"]
        .mean()
        .reindex(range(1, 13), fill_value=0.0)
    )
    stable = wet & support.ge(float(min_wet_year_fraction))
    unstable_count = int((wet & ~stable).sum())
    return stable, unstable_count


def _build_guardrail_columns(
    df: pd.DataFrame,
    *,
    fixed_monthly: pd.DataFrame,
    method: str,
    hydro_year_col: str,
    month_col: str,
    value_col: str,
    firstpass_quantile: float,
    core_climatology_alpha: float,
    shoulder_climatology_alpha: float,
    shoulder_month_quantile: float | None,
    climatology_window: str,
    climatology_window_years: int,
    climatology_window_mode: str,
    climatology_min_month_observations: int,
    climatology_min_wet_year_fraction: float,
    low_confidence_missing: bool,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if climatology_window not in {"global", "rolling"}:
        raise ValueError('climatology_window must be "global" or "rolling".')
    if climatology_window_years <= 0:
        raise ValueError("climatology_window_years must be positive.")
    if climatology_min_month_observations <= 0:
        raise ValueError("climatology_min_month_observations must be positive.")
    if not 0.0 <= float(climatology_min_wet_year_fraction) <= 1.0:
        raise ValueError("climatology_min_wet_year_fraction must be between 0 and 1.")
    hydro_years = sorted(df[hydro_year_col].dropna().astype(int).unique())
    short_record = (
        climatology_window == "rolling"
        and len(hydro_years) < int(climatology_window_years) * 2
    )

    out = pd.DataFrame(index=df.index)
    global_tail, global_shoulder, global_wet, global_month_floor, global_month_source = (
        _guardrail_values(
            df,
            fixed_monthly,
            month_col=month_col,
            value_col=value_col,
            firstpass_quantile=firstpass_quantile,
            core_climatology_alpha=core_climatology_alpha,
            shoulder_climatology_alpha=shoulder_climatology_alpha,
            shoulder_month_quantile=(
                None if low_confidence_missing else shoulder_month_quantile
            ),
        )
    )

    fallback_count = 0
    unstable_month_count = 0
    sources: set[str] = set()
    month_sources: set[str] = set()
    if low_confidence_missing and shoulder_month_quantile is not None:
        month_sources.add("disabled_low_confidence")

    for hy in hydro_years:
        idx = df.index[df[hydro_year_col].astype(int) == hy]
        use_global = (
            climatology_window == "global"
            or low_confidence_missing
            or short_record
        )
        source = "global_short_record" if short_record and climatology_window == "rolling" else "global"
        local = df
        fixed = fixed_monthly

        if not use_global:
            local = _window_subset(
                df,
                hydro_year_col=hydro_year_col,
                hydro_year=int(hy),
                years=int(climatology_window_years),
                mode=climatology_window_mode,
            )
            if _has_month_coverage(
                local,
                month_col=month_col,
                value_col=value_col,
                min_observed_per_month=climatology_min_month_observations,
            ):
                fixed = _fixed_monthly_for_method(
                    local,
                    method=method,
                    month_col=month_col,
                    value_col=value_col,
                )
                source = f"rolling_{climatology_window_mode}"
            else:
                local = df
                fallback_count += 1
                source = "global_fallback"

        if source in {"global", "global_short_record"}:
            tail = global_tail
            shoulder = global_shoulder
            wet = global_wet
            month_floor = global_month_floor
            month_source = global_month_source
            tail_by_month = None
        elif source == "global_fallback":
            tail = global_tail
            shoulder = global_shoulder
            wet = global_wet
            month_floor = global_month_floor
            month_source = global_month_source
            tail_by_month = None
        else:
            tail, shoulder, wet, month_floor, month_source = _guardrail_values(
                local,
                fixed,
                month_col=month_col,
                value_col=value_col,
                firstpass_quantile=firstpass_quantile,
                core_climatology_alpha=core_climatology_alpha,
                shoulder_climatology_alpha=shoulder_climatology_alpha,
                shoulder_month_quantile=shoulder_month_quantile,
            )
            tail = min(float(tail), float(global_tail))
            wet, unstable_count = _stable_wet_months(
                local,
                wet,
                month_col=month_col,
                value_col=value_col,
                floor=tail,
                min_wet_year_fraction=climatology_min_wet_year_fraction,
            )
            unstable_month_count += unstable_count
            base_tail = pd.Series(tail, index=range(1, 13))
            strict_tail = pd.Series(max(tail, global_tail), index=range(1, 13))
            tail_by_month = base_tail.where(wet, strict_tail)

        row_months = df.loc[idx, month_col]
        if tail_by_month is None:
            out.loc[idx, "_TailFloor"] = float(tail)
        else:
            out.loc[idx, "_TailFloor"] = row_months.map(tail_by_month).astype(float)
        out.loc[idx, "_BaselineWetMonth"] = row_months.map(wet).fillna(False).astype(bool)
        extension = pd.Series(float(max(tail, shoulder)), index=idx)
        if month_floor is not None:
            extension = pd.concat(
                [extension, row_months.map(month_floor).rename("_MonthFloor")],
                axis=1,
            ).max(axis=1)
        out.loc[idx, "_ExtensionFloor"] = extension.astype(float)
        sources.add(source)
        if month_source is not None:
            prefix = "rolling_" if source.startswith("rolling_") else ""
            month_sources.add(prefix + month_source)

    if not month_sources and shoulder_month_quantile is None:
        month_floor_source: str | None = None
    elif not month_sources:
        month_floor_source = "disabled"
    elif len(month_sources) == 1:
        month_floor_source = next(iter(month_sources))
    else:
        month_floor_source = "mixed"

    if len(sources) == 1:
        guardrail_source = next(iter(sources))
    elif sources:
        guardrail_source = "mixed"
    else:
        guardrail_source = None

    rolling_active = any(source.startswith("rolling_") for source in sources)

    return out, {
        "guardrail_source": guardrail_source,
        "fallback_count": fallback_count,
        "rolling_active": rolling_active,
        "unstable_month_count": unstable_month_count,
        "month_floor_source": month_floor_source,
        "global_tail_floor": global_tail,
        "global_shoulder_floor": global_shoulder,
    }


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
    report_kmeans_silhouette: bool = False,
    onset_window_months: int | str | None = "auto",
    rainfall_si_override: bool = True,
    rainfall_si_threshold: float = 0.80,
    min_core_length: int | None = None,
    shoulder_climatology_alpha: float = 0.10,
    shoulder_month_quantile: float | None = 0.60,
    core_climatology_alpha: float = 0.05,
    shoulder_residual_quantile: float | None = 0.95,
    climatology_window: str = "rolling",
    climatology_window_years: int = 10,
    climatology_window_mode: str = "trailing",
    climatology_min_month_observations: int = 5,
    climatology_min_wet_year_fraction: float = 0.60,
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
    report_kmeans_silhouette:
        If ``True``, compute the legacy KMeans silhouette diagnostic for
        backward-compatible reports. Defaults to ``False`` so normal runs avoid
        KMeans and the Windows MKL warning.
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
    shoulder_month_quantile:
        Optional calendar-month rainfall quantile used as a month-aware
        shoulder extension floor. The default (0.60) lets above-normal
        build-up/recession months join the wet season while blocking more
        ordinary dry-season rain pulses. ``None`` disables this gate.
    shoulder_residual_quantile:
        Quantile of positive STL residuals above which a candidate shoulder is
        rejected as an isolated storm. ``None`` disables the gate.
    climatology_window, climatology_window_years, climatology_window_mode:
        Climatology source for local guardrails. ``"rolling"`` (default) uses
        recent local normal by fixed hydrological year; ``"global"`` uses the
        full record. The rolling window can be ``"trailing"`` or ``"centered"``.
    climatology_min_month_observations:
        Minimum observed values per calendar month required before a rolling
        local window is trusted; otherwise the guardrail falls back to global.
    climatology_min_wet_year_fraction:
        Fraction of observed years in a rolling window that must exceed the
        local tail floor before a locally labelled Wet month is treated as a
        stable recent Wet month. This guards short windows against one-off wet
        shoulders and decadal noise.
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
        report_silhouette=report_kmeans_silhouette,
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
    if climatology_window not in {"global", "rolling"}:
        raise ValueError('climatology_window must be "global" or "rolling".')
    if int(climatology_window_years) <= 0:
        raise ValueError("climatology_window_years must be positive.")
    if climatology_window_mode not in {"trailing", "centered"}:
        raise ValueError(
            'climatology_window_mode must be "trailing" or "centered".'
        )
    if int(climatology_min_month_observations) <= 0:
        raise ValueError("climatology_min_month_observations must be positive.")
    climatology_min_wet_year_fraction = float(climatology_min_wet_year_fraction)
    if not 0.0 <= climatology_min_wet_year_fraction <= 1.0:
        raise ValueError("climatology_min_wet_year_fraction must be between 0 and 1.")

    smooth_window_used = (
        int(smooth_window) if smooth_window is not None
        else _resolve_adaptive_smooth_window(circ_stats)
    )
    min_core_length_used = (
        int(min_core_length) if min_core_length is not None
        else _resolve_adaptive_min_core_length(circ_stats)
    )
    if onset_window_months == "auto":
        onset_window_resolved = _resolve_adaptive_onset_window(circ_stats)
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
    tail_floor: float | None = None
    shoulder_residual_threshold: float | None = None
    shoulder_month_floor_source: str | None = None
    climatology_guardrail_source: str | None = None
    climatology_guardrail_fallback_count = 0
    climatology_unstable_month_count = 0

    if shoulder_month_quantile is not None:
        shoulder_month_quantile = float(shoulder_month_quantile)
        if not 0.0 <= shoulder_month_quantile <= 1.0:
            raise ValueError(
                "shoulder_month_quantile must be between 0 and 1, "
                "or None to disable."
            )

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
        low_confidence_missing = (
            report.data_confidence == "low"
            and (report.n_imputed > 0 or report.n_unimputed > 0)
        )
        guardrail_cols, guardrail_diag = _build_guardrail_columns(
            work,
            fixed_monthly=fixed_monthly,
            method=method,
            hydro_year_col="Hydro_Year_fixed",
            month_col=month_col,
            value_col=value_col,
            firstpass_quantile=firstpass_quantile,
            core_climatology_alpha=core_climatology_alpha,
            shoulder_climatology_alpha=shoulder_climatology_alpha,
            shoulder_month_quantile=shoulder_month_quantile,
            climatology_window=climatology_window,
            climatology_window_years=int(climatology_window_years),
            climatology_window_mode=climatology_window_mode,
            climatology_min_month_observations=int(
                climatology_min_month_observations
            ),
            climatology_min_wet_year_fraction=climatology_min_wet_year_fraction,
            low_confidence_missing=low_confidence_missing,
        )
        for col in guardrail_cols.columns:
            work[col] = guardrail_cols[col]
        climatology_guardrail_source = str(guardrail_diag["guardrail_source"])
        climatology_guardrail_fallback_count = int(
            guardrail_diag["fallback_count"]
        )
        climatology_unstable_month_count = int(
            guardrail_diag["unstable_month_count"]
        )
        shoulder_month_floor_source = (
            str(guardrail_diag["month_floor_source"])
            if guardrail_diag["month_floor_source"] is not None else None
        )
        if onset_window_months == "auto" and bool(guardrail_diag["rolling_active"]):
            onset_window_resolved = None

        segmented_df, wet_boundaries = segment_main_wet_season_fixed_threshold(
            work,
            date_col=date_col,
            hydro_year_col="Hydro_Year_fixed",
            smoothed_col="Smoothed",
            threshold=threshold_first,
            threshold_col="_TailFloor",
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

        tail_floor_col = "_TailFloor"
        extension_threshold_col = "_ExtensionFloor"
        fragment_keep_col = "_BaselineWetMonth"

        # ``tail_floor`` remains the global fallback value for diagnostics.
        # Actual seasonal runs use per-row guardrails when rolling climatology is
        # active.
        tail_floor = float(threshold_first)
        segmented_df = refine_season_tails(
            segmented_df,
            rainfall_col=value_col,
            date_col=date_col,
            threshold_high=threshold_second,
            threshold_low=0.0,
            min_core_length=min_core_length_used,
            climatology_floor=None,
            residual_col=residual_col,
            residual_threshold=shoulder_residual_threshold,
            per_row_threshold_col=tail_floor_col,
            extension_threshold_col=extension_threshold_col,
            fragment_keep_col=fragment_keep_col,
            enforce_low_floor_inside_runs=True,
            min_refined_run_length=min_core_length_used,
        )
        if residual_col is not None and residual_col in segmented_df.columns:
            segmented_df = segmented_df.drop(columns=[residual_col])
        for col in (tail_floor_col, extension_threshold_col, fragment_keep_col):
            if col in segmented_df.columns:
                segmented_df = segmented_df.drop(columns=[col])
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
        tail_floor=tail_floor,
        rainfall_si_override=rainfall_si_override,
        smooth_window_used=smooth_window_used,
        min_core_length_used=min_core_length_used,
        onset_window_months_used=onset_window_resolved,
        core_climatology_floor=core_clim_floor,
        shoulder_climatology_floor=shoulder_clim_floor,
        shoulder_month_quantile=shoulder_month_quantile,
        shoulder_month_floor_source=shoulder_month_floor_source,
        climatology_window=climatology_window,
        climatology_window_years=int(climatology_window_years),
        climatology_window_mode=climatology_window_mode,
        climatology_min_month_observations=int(climatology_min_month_observations),
        climatology_min_wet_year_fraction=climatology_min_wet_year_fraction,
        climatology_guardrail_source=climatology_guardrail_source,
        climatology_guardrail_fallback_count=climatology_guardrail_fallback_count,
        climatology_unstable_month_count=climatology_unstable_month_count,
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
            get_monthly_aoi_rainfall,
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
        if source in {"auto", "chirps"}:
            kwargs = {
                "source": source,
                "era5_zarr_path": config.fetch.era5_zarr_path,
                "silo_base_url": config.fetch.silo_base_url,
                "variable": config.fetch.variable,
                "cache_dir": config.fetch.cache_dir,
                "spatial_chunk": config.fetch.spatial_chunk,
                "time_chunk": config.fetch.time_chunk,
                "era5_fallback": config.fetch.era5_fallback,
            }
            if config.fetch.chirps_base_url:
                kwargs["chirps_base_url"] = config.fetch.chirps_base_url
            in_df = get_monthly_aoi_rainfall(
                gdf,
                start_year=config.fetch.start_year,
                end_year=config.fetch.end_year,
                **kwargs,
            )
        elif source == "era5":
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
                time_chunk=config.fetch.time_chunk,
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
            raise ValueError(
                "fetch.source must be one of {'auto', 'silo', 'chirps', 'era5'}"
            )
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
        report_kmeans_silhouette=config.algorithm.report_kmeans_silhouette,
        onset_window_months=config.algorithm.onset_window_months,
        rainfall_si_override=config.algorithm.rainfall_si_override,
        rainfall_si_threshold=config.algorithm.rainfall_si_threshold,
        min_core_length=config.algorithm.min_core_length,
        shoulder_climatology_alpha=config.algorithm.shoulder_climatology_alpha,
        shoulder_month_quantile=config.algorithm.shoulder_month_quantile,
        core_climatology_alpha=config.algorithm.core_climatology_alpha,
        shoulder_residual_quantile=config.algorithm.shoulder_residual_quantile,
        climatology_window=config.algorithm.climatology_window,
        climatology_window_years=config.algorithm.climatology_window_years,
        climatology_window_mode=config.algorithm.climatology_window_mode,
        climatology_min_month_observations=(
            config.algorithm.climatology_min_month_observations
        ),
        climatology_min_wet_year_fraction=(
            config.algorithm.climatology_min_wet_year_fraction
        ),
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
