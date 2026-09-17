"""Decide whether an AOI's satellite record can support the analysis at all.

Two questions live here, deliberately kept apart because they have different
answer shapes and different maturity:

**Is there any recurrent surface water?** :func:`run_regular_preflight` (and
:func:`preflight` with ``feasibility_only=True``) answers this from one
all-time DEA WOfS Statistics read using fixed constants -- recurrent water at
``>=10%`` frequency, subject to a contiguous-cluster rule -- and returns a
:class:`~hydroseason._preflight_feasibility.FeasibilityResult`. This is the
screen ``run_hydroseason`` applies automatically before monthly acquisition;
a rejection surfaces as :class:`~hydroseason.workflow.HydroSeasonPreflightError`.
A Statistics outage never converts into a "no water" answer: the workflow
warns and continues, and the standalone feasibility path re-raises.

**Is the record dense and long enough for per-year detection?**
:func:`preflight` answers this and returns a
:class:`~hydroseason._preflight_types.PreflightResult` carrying separate
candidate, monthly, and timing decisions. Its threshold profile is *not yet
calibrated*: ``thresholds="default"`` raises
:class:`PreflightProfileUnavailable` rather than guessing. Until that profile
is frozen, use ``thresholds="diagnostic"`` to obtain the measured metrics
without any pass/fail gating, or supply your own
:class:`~hydroseason._preflight_types.PreflightThresholds`.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Mapping

from ._historical_water_mask import HistoricalWaterMask
from ._io_dea_stats import (
    COUNT_CLEAR_BAND,
    COUNT_WET_BAND,
    DEA_STATS_ANNUAL_COLLECTION,
    DEFAULT_WO_STATISTICS_PRODUCT,
    DEFAULT_WO_STATISTICS_STAC_URL,
)
from ._io_preflight_stats import AnnualStatisticsUnavailable, open_annual_wo_statistics
from ._preflight_candidate import compute_candidate_raw_metrics, evaluate_candidate
from ._preflight_feasibility import FeasibilityResult, assess_feasibility
from ._preflight_monthly import evaluate_monthly
from ._preflight_monthly_input import normalize_monthly_observations
from ._preflight_types import (
    CandidateMetrics,
    MonthlyMetrics,
    PreflightCapabilities,
    PreflightResult,
    PreflightThresholds,
    ThresholdMode,
)
from ._state_input import QualityPolicy

try:
    from ._io_dea_stats import DEAStatsUnavailable, WoStatisticsUnavailable
except ImportError:  # pragma: no cover
    DEAStatsUnavailable = RuntimeError
    WoStatisticsUnavailable = RuntimeError


_CAPABILITIES = PreflightCapabilities(
    annual_recurrence=True,
    per_year_detection=True,
    fixed_climatological_window=True,
    event_characterisation=True,
)
_DIAGNOSTIC_THRESHOLDS = PreflightThresholds(
    profile_name="diagnostic",
    profile_version="0",
    profile_status="provisional",
    min_clear_count=0,
    min_frequency_fraction=0.0,
    min_reliable_pixels=0,
    min_reliable_years=0,
    min_episodic_wet_count=0,
    min_episodic_pixels=0,
    min_episodic_years=0,
    min_candidate_years=0,
    min_pooled_usable_months=0,
    min_effective_usable_months=0.0,
    min_months_per_supported_year=1,
    min_supported_years=0,
    min_calendar_month_supported_years=0,
    calendar_month_warning_support_fraction=0.0,
    min_monthly_detectable_pixels=0,
    near_threshold_margin_fraction=0.0,
)
_ANNUAL_CACHE_ERROR_PREFIX = "annual statistics cache verification failed:"
_MONTHLY_DECLARED_ERROR_SNIPPETS = (
    "duplicate month timestamps",
    "start_date must not be after end_date",
    "Canonical water mask",
    "extent counts cross-check failed against cached mask cube.",
    "Raw-count monthly input requires variables",
    "Raw-count cube contains duplicate month timestamps.",
    "Monthly observation paths must currently point to a .zarr store.",
    "water_mask_variable=",
    "Dataset monthly input must either expose raw-count variables or name a water_mask_variable.",
    "Monthly observations must be a DataFrame, DataArray, Dataset, WOfSCacheHandle, or .zarr path.",
    "analysis mask cache verification failed:",
)


class PreflightProfileUnavailable(RuntimeError):
    """The reviewed preflight profile has not been installed yet."""


@dataclasses.dataclass(frozen=True)
class RegularWorkflowPreflight:
    """The single Statistics read shared by regular DEA acquisition."""

    feasibility: FeasibilityResult
    historical_water_mask: HistoricalWaterMask | None = None


def run_regular_preflight(
    aoi: Any,
    start_date: Any,
    end_date: Any,
    *,
    stac_url: str = DEFAULT_WO_STATISTICS_STAC_URL,
    resolution: float = 30.0,
    crs: str = "EPSG:3577",
    chunks: Mapping[str, int] | None = None,
) -> RegularWorkflowPreflight:
    """Screen an AOI and build its reusable maximum-water mask.

    Regular DEA order is: one all-time WOfS Statistics read, the ``>10%``
    recurrent-water/contiguity screen, then ``count_wet > 0 AND AOI`` mask
    derivation. The loaded raw count bands are handed to both computations,
    so monthly acquisition can reuse the resulting exact mask without a
    second Statistics query.

    ``start_date`` and ``end_date`` remain part of this workflow seam even
    though the fixed maximum-water footprint is intentionally all-time.
    """
    import hydroseason.io as io

    statistics = io.open_wo_statistics(
        aoi,
        product=DEFAULT_WO_STATISTICS_PRODUCT,
        stac_url=stac_url,
        resolution=resolution,
        crs=crs,
        chunks=chunks,
    )
    # Keep provenance/georeferencing attrs, discard only derived frequency,
    # and materialize the two source bands once for the shared handoff.
    statistics = statistics[[COUNT_WET_BAND, COUNT_CLEAR_BAND]].load()
    feasibility = assess_feasibility(statistics, resolution=resolution)
    if not feasibility.feasible:
        return RegularWorkflowPreflight(feasibility)

    try:
        historical_water_mask = io.build_historical_water_mask(statistics, aoi)
    except Exception as exc:
        # Do not let a successful read fall through to the monthly loader,
        # which would query Statistics again and could change the denominator.
        raise RuntimeError(
            "DEA WOfS Statistics loaded successfully but the reusable "
            "historical maximum-water mask could not be built"
        ) from exc
    return RegularWorkflowPreflight(feasibility, historical_water_mask)


def _empty_monthly_metrics() -> MonthlyMetrics:
    return MonthlyMetrics(metrics={})


def _warning_text(code: str, detail: str | None = None) -> str:
    return code if not detail else f"{code}: {detail}"


def _result(
    *,
    thresholds: PreflightThresholds,
    candidate_metrics: CandidateMetrics | None = None,
    monthly_metrics: MonthlyMetrics | None = None,
    candidate_decision: str,
    monthly_decision: str,
    timing_decision: str,
    candidate_reasons: tuple[str, ...] = (),
    monthly_reasons: tuple[str, ...] = (),
    timing_reasons: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    provenance: dict[str, Any] | None = None,
) -> PreflightResult:
    return PreflightResult(
        thresholds=thresholds,
        capabilities=_CAPABILITIES,
        candidate_metrics=CandidateMetrics() if candidate_metrics is None else candidate_metrics,
        monthly_metrics=_empty_monthly_metrics() if monthly_metrics is None else monthly_metrics,
        candidate_decision=candidate_decision,
        monthly_decision=monthly_decision,
        timing_decision=timing_decision,
        candidate_reasons=candidate_reasons,
        monthly_reasons=monthly_reasons,
        timing_reasons=timing_reasons,
        warnings=warnings,
        provenance={} if provenance is None else provenance,
    )


def _resolve_thresholds(
    thresholds: ThresholdMode | PreflightThresholds,
) -> tuple[PreflightThresholds, bool]:
    if thresholds == "diagnostic":
        return _DIAGNOSTIC_THRESHOLDS, True
    if thresholds == "default":
        raise PreflightProfileUnavailable(
            "Default preflight thresholds are unavailable; finish the calibration/freeze checkpoint before using thresholds='default'."
        )
    if isinstance(thresholds, PreflightThresholds):
        return thresholds, False
    raise TypeError("thresholds must be 'default', 'diagnostic', or a PreflightThresholds instance.")


def _monthly_error_is_declared(exc: Exception) -> bool:
    if not isinstance(exc, ValueError):
        return False
    text = str(exc)
    return any(snippet in text for snippet in _MONTHLY_DECLARED_ERROR_SNIPPETS)


def _annual_error_to_warning(exc: Exception) -> tuple[str, str]:
    text = str(exc)
    if text.startswith(_ANNUAL_CACHE_ERROR_PREFIX):
        return "statistics_provenance_invalid", text
    return "statistics_unavailable", text


def _monthly_source_provenance(record) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    source = record.source_identity
    if not isinstance(source, dict):
        warnings.append("monthly_provenance_invalid")
        source = {}
    return source, warnings


def preflight(
    aoi: Any,
    start_date: Any,
    end_date: Any,
    *,
    monthly_observations: Any | None = None,
    thresholds: ThresholdMode | PreflightThresholds = "default",
    stac_url: str = DEFAULT_WO_STATISTICS_STAC_URL,
    statistics_product: str = DEA_STATS_ANNUAL_COLLECTION,
    resolution: float = 30.0,
    # When True, run ONLY the cheap recurrent-water feasibility filter and
    # return a FeasibilityResult, not a PreflightResult. Different question,
    # different answer shape: forcing it into PreflightResult's
    # decision/reason/threshold structure would drag back the multi-profile
    # machinery the filter deliberately replaces.
    feasibility_only: bool = False,
    crs: str = "EPSG:3577",
    chunks: Mapping[str, int] | None = None,
    cache_dir: str | Path | None = None,
    prune_to_wet_aoi: bool = True,
    wet_aoi_min_frequency_fraction: float | None = None,
    # False here, deliberately the opposite of fetch_dea_stats_wet_aoi's own
    # True default: preflight is a detection-sufficiency gate, not a
    # forensic record, so it skips the per-year mask-union safety net by
    # default (measured ~92% of a large catchment's preflight runtime).
    # The monthly acquisition pipeline, the same function's other caller,
    # keeps the safe default since a pixel outside its mask is written as
    # permanently dry -- higher stakes than a preflight decision.
    wet_aoi_require_year_union: bool = False,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "flag",
    allow_unknown_quality: bool = False,
) -> PreflightResult | FeasibilityResult:
    """Report what an AOI's satellite record can support, before analysing it.

    Reads DEA WOfS Statistics for ``aoi`` over ``start_date``..``end_date`` and
    reports whether the record can support annual detection -- without running
    the analysis and without ever answering "no water" from a data outage.

    Parameters
    ----------
    aoi : str, pathlib.Path or geopandas.GeoDataFrame
        Area of interest, in any CRS; reprojected to ``crs`` internally.
    start_date, end_date : str
        Inclusive analysis window, ``"YYYY-MM-DD"``.
    monthly_observations : optional
        An already-resolved monthly record -- DataFrame, ``xarray``
        DataArray/Dataset, ``WOfSCacheHandle``, or a ``.zarr`` path -- used for
        the monthly and timing decisions. Without it those decisions are
        ``"not_assessed"``; the candidate decision still runs.
    thresholds : {"default", "diagnostic"} or PreflightThresholds, default "default"
        Cut-off profile. ``"default"`` raises
        :class:`PreflightProfileUnavailable` because the reviewed profile is
        not installed yet; ``"diagnostic"`` measures every metric with all
        cut-offs at zero, so nothing is gated and the numbers can be inspected
        on their own; a :class:`~hydroseason._preflight_types.PreflightThresholds`
        instance applies your own declared cut-offs.
    feasibility_only : bool, default False
        Run only the fixed-constant recurrent-water screen and return a
        :class:`~hydroseason._preflight_feasibility.FeasibilityResult`. This
        path ignores ``thresholds`` entirely, so it works today, and it
        re-raises a Statistics outage rather than reporting no water.
    stac_url, statistics_product, resolution, crs, chunks, cache_dir
        DEA Statistics access: endpoint, collection, target resolution in
        metres, working CRS, dask chunking, and an optional cache directory.
    prune_to_wet_aoi, wet_aoi_min_frequency_fraction, wet_aoi_require_year_union
        Restrict the read to the wet footprint. ``wet_aoi_require_year_union``
        defaults to ``False`` here -- unlike monthly acquisition, which keeps
        the per-year mask-union safety net -- because it costs the bulk of a
        large catchment's preflight runtime and a preflight decision is not a
        forensic record.
    max_invalid_pct, quality_policy, allow_unknown_quality
        How the monthly record's per-month quality is screened before the
        monthly and timing decisions are taken.

    Returns
    -------
    PreflightResult or FeasibilityResult
        A :class:`~hydroseason._preflight_feasibility.FeasibilityResult` when
        ``feasibility_only=True``, otherwise a
        :class:`~hydroseason._preflight_types.PreflightResult`.

    Raises
    ------
    PreflightProfileUnavailable
        ``thresholds="default"`` was requested before the reviewed profile
        was installed.
    TypeError
        ``thresholds`` was neither a recognised mode nor a
        :class:`~hydroseason._preflight_types.PreflightThresholds`.

    Notes
    -----
    Outside ``feasibility_only``, an unreachable or unusable Statistics source
    never becomes a negative answer: the affected decisions become
    ``"not_assessed"`` and the cause is recorded in ``result.warnings``.

    Examples
    --------
    Screen an AOI for recurrent water before committing to acquisition::

        from hydroseason import preflight

        feasibility = preflight(
            "catchment.geojson", "2005-01-01", "2025-12-01",
            feasibility_only=True,
        )
        print(feasibility.feasible, feasibility.reason)

    Measure detection support without gating it::

        result = preflight(
            "catchment.geojson", "2005-01-01", "2025-12-01",
            thresholds="diagnostic",
        )
        print(result.summary())
    """
    # feasibility_only never reads resolved_thresholds/diagnostic_mode: it runs
    # only the fixed-constant recurrent-water filter and skips candidate/
    # monthly evaluation entirely, so resolving (and possibly rejecting) a
    # threshold profile here would block a cheap pre-filter behind the same
    # calibration/freeze checkpoint the filter exists to not depend on.
    if feasibility_only:
        resolved_thresholds, diagnostic_mode = None, False
    else:
        resolved_thresholds, diagnostic_mode = _resolve_thresholds(thresholds)
    warnings: list[str] = []
    provenance: dict[str, Any] = {
        "annual": {
            "request": {
                "start_date": start_date,
                "end_date": end_date,
                "product": statistics_product,
                "stac_url": stac_url,
                "resolution": resolution,
                "crs": crs,
            }
        },
        "monthly": {
            "supplied": monthly_observations is not None,
        },
    }

    try:
        annual = open_annual_wo_statistics(
            aoi,
            start_date=start_date,
            end_date=end_date,
            product=statistics_product,
            stac_url=stac_url,
            resolution=resolution,
            crs=crs,
            chunks=chunks,
            cache_dir=cache_dir,
            prune_to_wet_aoi=prune_to_wet_aoi,
            wet_aoi_min_frequency_fraction=wet_aoi_min_frequency_fraction,
            wet_aoi_require_year_union=wet_aoi_require_year_union,
            # feasibility_only needs only two scalars out of the cube (a
            # frequency threshold and a cluster-size check), both of which
            # reduce lazily. Materializing the whole grid first (the default
            # for every other preflight path) is pure waste here, and for a
            # Fitzroy-scale AOI it is exactly the multi-GB allocation this
            # mode exists to avoid -- so keep it lazy and let
            # assess_feasibility's dask branch do the reduction.
            **({"materialize": False} if feasibility_only else {}),
        )
    except (AnnualStatisticsUnavailable, WoStatisticsUnavailable, DEAStatsUnavailable) as exc:
        if feasibility_only:
            # A statistics outage is not evidence the AOI lacks water --
            # silently reporting infeasible would be scientifically wrong
            # and could wrongly exclude an AOI from a large sweep. Fail
            # loudly instead of returning any result.
            raise
        code, detail = _annual_error_to_warning(exc)
        warnings.append(_warning_text(code, detail))
        return _result(
            thresholds=resolved_thresholds,
            candidate_decision="indeterminate",
            monthly_decision="not_assessed",
            timing_decision="not_assessed",
            candidate_reasons=(code,),
            monthly_reasons=("monthly_not_supplied",) if monthly_observations is None else (),
            warnings=tuple(warnings),
            provenance=provenance,
        )
    except ValueError as exc:
        if not str(exc).startswith(_ANNUAL_CACHE_ERROR_PREFIX):
            raise
        if feasibility_only:
            # Same rationale as above: an outage must never be reported as
            # infeasible, so re-raise rather than returning a result.
            raise
        code, detail = _annual_error_to_warning(exc)
        warnings.append(_warning_text(code, detail))
        return _result(
            thresholds=resolved_thresholds,
            candidate_decision="indeterminate",
            monthly_decision="not_assessed",
            timing_decision="not_assessed",
            candidate_reasons=(code,),
            monthly_reasons=("monthly_not_supplied",) if monthly_observations is None else (),
            warnings=tuple(warnings),
            provenance=provenance,
        )

    annual_provenance = annual.attrs.get("provenance", {})
    if not isinstance(annual_provenance, dict):
        warnings.append("annual_provenance_invalid")
        annual_provenance = {}

    if feasibility_only:
        # Provenance was already computed by open_annual_wo_statistics (per-
        # year item IDs, processing versions, missing_requested_years, the
        # wet_aoi_pruning applied/fallback block) -- carry it through rather
        # than discarding it. missing_requested_years never raises; without
        # this a sweep rejection based on a degraded (e.g. partial-years)
        # read would be indistinguishable from a clean one.
        feasibility_result = assess_feasibility(annual, resolution=resolution)
        return dataclasses.replace(feasibility_result, provenance=annual_provenance)

    provenance["annual"]["source"] = annual_provenance

    candidate_metrics = compute_candidate_raw_metrics(annual)
    if diagnostic_mode:
        candidate_decision = "not_assessed"
        candidate_reasons = ("diagnostic_mode",)
    else:
        candidate_evaluation = evaluate_candidate(candidate_metrics, resolved_thresholds)
        candidate_metrics = candidate_evaluation.candidate_metrics
        candidate_decision = candidate_evaluation.decision
        candidate_reasons = candidate_evaluation.reasons
        warnings.extend(candidate_evaluation.warnings)

    if monthly_observations is None:
        return _result(
            thresholds=resolved_thresholds,
            candidate_metrics=candidate_metrics,
            candidate_decision=candidate_decision,
            monthly_decision="not_assessed",
            timing_decision="not_assessed",
            candidate_reasons=candidate_reasons,
            monthly_reasons=("monthly_not_supplied",),
            warnings=tuple(warnings),
            provenance=provenance,
        )

    try:
        monthly_record = normalize_monthly_observations(
            monthly_observations,
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        if not _monthly_error_is_declared(exc):
            raise
        warnings.append(_warning_text("invalid_input", str(exc)))
        return _result(
            thresholds=resolved_thresholds,
            candidate_metrics=candidate_metrics,
            candidate_decision=candidate_decision,
            monthly_decision="not_assessed",
            timing_decision="not_assessed",
            candidate_reasons=candidate_reasons,
            monthly_reasons=("invalid_input",),
            timing_reasons=("invalid_input",),
            warnings=tuple(warnings),
            provenance=provenance,
        )

    monthly_source, monthly_source_warnings = _monthly_source_provenance(monthly_record)
    warnings.extend(monthly_source_warnings)
    provenance["monthly"]["source"] = monthly_source

    if diagnostic_mode:
        return _result(
            thresholds=resolved_thresholds,
            candidate_metrics=candidate_metrics,
            candidate_decision="not_assessed",
            monthly_decision="not_assessed",
            timing_decision="not_assessed",
            candidate_reasons=("diagnostic_mode",),
            monthly_reasons=("diagnostic_mode",),
            timing_reasons=("diagnostic_mode",),
            warnings=tuple(warnings),
            provenance=provenance,
        )

    monthly_evaluation = evaluate_monthly(
        monthly_record,
        candidate_evaluation,
        resolved_thresholds,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
        allow_unknown_quality=allow_unknown_quality,
    )
    warnings.extend(monthly_evaluation.warnings)
    return _result(
        thresholds=resolved_thresholds,
        candidate_metrics=candidate_metrics,
        monthly_metrics=monthly_evaluation.monthly_metrics,
        candidate_decision=candidate_decision,
        monthly_decision=monthly_evaluation.run_decision,
        timing_decision=monthly_evaluation.timing_decision,
        candidate_reasons=candidate_reasons,
        monthly_reasons=monthly_evaluation.run_reasons,
        timing_reasons=monthly_evaluation.timing_reasons,
        warnings=tuple(dict.fromkeys(warnings)),
        provenance=provenance,
    )


__all__ = [
    "preflight",
    "run_regular_preflight",
    "RegularWorkflowPreflight",
    "PreflightProfileUnavailable",
]
