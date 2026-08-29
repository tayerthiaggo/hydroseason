from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from ._preflight_candidate import CandidateEvaluation, _eager_item
from ._preflight_types import (
    Decision,
    MonthlyMetrics,
    MonthlyObservationRecord,
    PreflightThresholds,
)
from ._state_input import QualityPolicy, candidate_weights, prepare_monthly_extent

_STUDY_METADATA_COLUMNS = {
    "rainfall_mm",
    "rain_anomaly_mm",
    "discharge_ml",
    "discharge_cumecs",
    "streamflow_ml",
}
_QUANTILES: tuple[tuple[str, float], ...] = (
    ("q0", 0.0),
    ("q25", 0.25),
    ("q50", 0.50),
    ("q75", 0.75),
    ("q100", 1.0),
)


def _quantile_payload(values: pd.Series | np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {label: None for label, _ in _QUANTILES}
    return {label: float(np.quantile(finite, quantile)) for label, quantile in _QUANTILES}


def _margin_payload(observed: int | float | None, minimum: int | float) -> dict[str, Any]:
    if observed is None:
        return {
            "observed": None,
            "minimum": minimum,
            "signed_margin": None,
            "normalized_margin": None,
        }
    signed_margin = observed - minimum
    normalized_margin = None if minimum == 0 else signed_margin / minimum
    return {
        "observed": observed,
        "minimum": minimum,
        "signed_margin": signed_margin,
        "normalized_margin": normalized_margin,
    }


def _dict_with_all_months(values: pd.Series) -> dict[int, int]:
    counts = values.groupby(values.index.month).sum()
    return {month: int(counts.get(month, 0)) for month in range(1, 13)}


def _year_month_counts(mask: pd.Series) -> dict[int, int]:
    counts = mask.groupby(mask.index.year).sum()
    return {int(year): int(value) for year, value in counts.items()}


def _longest_false_run(mask: pd.Series) -> int:
    longest = 0
    current = 0
    for flag in mask.to_numpy(dtype=bool):
        if flag:
            current = 0
            continue
        current += 1
        longest = max(longest, current)
    return longest


def _pixel_area(grid_identity: dict[str, Any]) -> float | None:
    transform = grid_identity.get("transform")
    if not isinstance(transform, tuple) or len(transform) < 5:
        return None
    try:
        return abs(float(transform[0]) * float(transform[4]))
    except (TypeError, ValueError):
        return None


def _grid_match(record: MonthlyObservationRecord, candidate_evaluation: CandidateEvaluation) -> bool:
    annual = candidate_evaluation.candidate_metrics.evidence
    if annual is None or not record.capabilities.candidate_monthly_overlap:
        return False
    if record.detectable_mask is None:
        return False
    if not all(hasattr(annual, attr) for attr in ("sizes", "coords")):
        return False
    try:
        same_shape = (
            int(annual.sizes["y"]) == int(record.detectable_mask.sizes["y"])
            and int(annual.sizes["x"]) == int(record.detectable_mask.sizes["x"])
        )
        same_y = np.array_equal(np.asarray(annual.coords["y"]), np.asarray(record.detectable_mask.coords["y"]))
        same_x = np.array_equal(np.asarray(annual.coords["x"]), np.asarray(record.detectable_mask.coords["x"]))
    except Exception:
        return False
    return bool(same_shape and same_y and same_x)


def _overlap_metrics(record: MonthlyObservationRecord, candidate_evaluation: CandidateEvaluation) -> dict[str, Any]:
    if not _grid_match(record, candidate_evaluation):
        return {
            "union_detectable_pixels": None,
            "candidate_support_pixels": None,
            "candidate_monthly_overlap_pixels": None,
        }
    annual = candidate_evaluation.candidate_metrics.evidence
    assert annual is not None  # narrow for type-checkers
    monthly_union = record.detectable_mask.any("time")
    candidate_union = annual["count_clear"] > 0
    candidate_union = candidate_union.any("year")
    overlap = monthly_union & candidate_union
    return {
        "union_detectable_pixels": int(_eager_item(monthly_union.sum())),
        "candidate_support_pixels": int(_eager_item(candidate_union.sum())),
        "candidate_monthly_overlap_pixels": int(_eager_item(overlap.sum())),
    }


def _validate_columns(frame: pd.DataFrame) -> None:
    unexpected = _STUDY_METADATA_COLUMNS.intersection(frame.columns)
    if unexpected:
        labels = ", ".join(sorted(unexpected))
        raise ValueError(f"study metadata columns are not accepted by evaluate_monthly: {labels}.")


@dataclass(frozen=True)
class MonthlyEvaluation:
    monthly_metrics: MonthlyMetrics
    run_decision: Decision
    timing_decision: Decision
    run_reasons: tuple[str, ...] = ()
    timing_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def metrics(self) -> SimpleNamespace:
        return SimpleNamespace(**self.monthly_metrics.to_dict()["metrics"])

    @property
    def raw_metrics(self) -> dict[str, Any]:
        return self.monthly_metrics.to_dict()["raw_metrics"]

    @property
    def margins(self) -> dict[str, Any]:
        return self.monthly_metrics.to_dict()["margins"]

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.run_reasons + self.timing_reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_decision": self.run_decision,
            "timing_decision": self.timing_decision,
            "metrics": self.monthly_metrics.to_dict(),
            "reasons": list(self.reasons),
            "run_reasons": list(self.run_reasons),
            "timing_reasons": list(self.timing_reasons),
            "warnings": list(self.warnings),
            "provenance": self.provenance,
        }


def evaluate_monthly(
    record: MonthlyObservationRecord,
    candidate_evaluation: CandidateEvaluation,
    thresholds: PreflightThresholds,
    *,
    max_invalid_pct: float = 20.0,
    allow_unknown_quality: bool = False,
    quality_policy: QualityPolicy = "flag",
) -> MonthlyEvaluation:
    frame = record.frame if isinstance(record.frame, pd.DataFrame) else pd.DataFrame(record.frame)
    _validate_columns(frame)
    prepared = prepare_monthly_extent(
        frame,
        max_invalid_pct=max_invalid_pct,
        allow_unknown_quality=allow_unknown_quality,
        quality_policy=quality_policy,
    )
    usable_mask = prepared["candidate_usable"].fillna(False).astype(bool)
    weights = candidate_weights(prepared)
    candidate_month_count = int(usable_mask.sum())
    effective_candidate_months = float(weights.sum())
    months_per_candidate_year = _year_month_counts(usable_mask.astype(int))
    candidate_regime_years = sum(
        1
        for count in months_per_candidate_year.values()
        if count >= thresholds.min_months_per_supported_year
    )
    calendar_month_candidate_years = _dict_with_all_months(usable_mask.astype(int))
    largest_unusable_gap_months = _longest_false_run(usable_mask)
    observed_fraction_overall = (
        None if candidate_month_count == 0 else effective_candidate_months / candidate_month_count
    )

    detectable_water_mask: pd.Series | None = None
    supported_mask: pd.Series | None = None
    supported_month_count: int | None = None
    effective_supported_months: float | None = None
    months_per_supported_year: dict[int, int] = {}
    n_regime_usable_years: int | None = None
    calendar_month_supported_years: dict[int, int] | None = None
    detectable_quantiles: dict[str, float | None] | None = None
    if record.capabilities.per_month_pixel_counts:
        detectable = pd.to_numeric(prepared["n_water"], errors="coerce")
        detectable_quantiles = _quantile_payload(detectable.to_numpy(dtype=float))
        detectable_water_mask = usable_mask & detectable.gt(0).fillna(False)
        supported_mask = usable_mask & detectable.ge(thresholds.min_monthly_detectable_pixels).fillna(False)
        supported_month_count = int(supported_mask.sum())
        effective_supported_months = float(weights.where(supported_mask, 0.0).sum())
        months_per_supported_year = _year_month_counts(supported_mask.astype(int))
        n_regime_usable_years = sum(
            1
            for count in months_per_supported_year.values()
            if count >= thresholds.min_months_per_supported_year
        )
        calendar_month_supported_years = _dict_with_all_months(supported_mask.astype(int))

    overlap_metrics = _overlap_metrics(record, candidate_evaluation)
    raw_metrics = {
        "candidate_month_count": candidate_month_count,
        "effective_candidate_months": effective_candidate_months,
        "observed_fraction_overall": observed_fraction_overall,
        "largest_unusable_gap_months": largest_unusable_gap_months,
        "calendar_month_candidate_years": calendar_month_candidate_years,
        "months_per_candidate_year": months_per_candidate_year,
        "detectable_pixel_count_quantiles": detectable_quantiles,
        "months_with_detectable_water": (
            None if detectable_water_mask is None else int(detectable_water_mask.sum())
        ),
        "pixel_area": _pixel_area(record.grid_identity),
        **overlap_metrics,
    }
    metrics = {
        "candidate_month_count": candidate_month_count,
        "effective_candidate_months": effective_candidate_months,
        "supported_month_count": supported_month_count,
        "effective_supported_months": effective_supported_months,
        "months_per_supported_year": months_per_supported_year,
        "calendar_month_supported_years": calendar_month_supported_years,
        "n_regime_usable_years": n_regime_usable_years,
        "largest_unusable_gap_months": largest_unusable_gap_months,
    }
    margins = {
        "supported_months": _margin_payload(supported_month_count, thresholds.min_pooled_usable_months),
        "effective_supported_months": _margin_payload(
            effective_supported_months,
            thresholds.min_effective_usable_months,
        ),
        "supported_years": _margin_payload(n_regime_usable_years, thresholds.min_supported_years),
    }

    run_reasons: list[str] = []
    timing_reasons: list[str] = []
    warnings: list[str] = []

    if not record.capabilities.per_month_pixel_counts:
        run_decision: Decision = "not_assessed"
        run_reasons.append("monthly_spatial_support_not_assessed")
    else:
        assert supported_month_count is not None
        assert effective_supported_months is not None
        if supported_month_count < thresholds.min_pooled_usable_months:
            run_reasons.append("monthly_pooled_support_insufficient")
        if effective_supported_months < thresholds.min_effective_usable_months:
            run_reasons.append("monthly_effective_support_insufficient")
        if supported_month_count == 0 and candidate_month_count > 0:
            run_reasons.append("monthly_detectable_pixels_insufficient")
        run_decision = "fail" if run_reasons else "pass"
        if run_decision == "pass":
            run_reasons.append("monthly_supported")

    timing_counts = (
        calendar_month_supported_years
        if record.capabilities.per_month_pixel_counts
        else calendar_month_candidate_years
    )
    timing_years = n_regime_usable_years if record.capabilities.per_month_pixel_counts else candidate_regime_years
    if timing_years < thresholds.min_supported_years:
        timing_reasons.append("monthly_supported_years_insufficient")
    if any(count == 0 for count in timing_counts.values()):
        timing_reasons.append("calendar_month_unobserved")
    elif any(count < thresholds.min_calendar_month_supported_years for count in timing_counts.values()):
        timing_reasons.append("calendar_month_repeat_below_minimum")
    if timing_years > 0 and any(
        count >= thresholds.min_calendar_month_supported_years
        and (count / timing_years) < thresholds.calendar_month_warning_support_fraction
        for count in timing_counts.values()
    ):
        warnings.append("calendar_month_support_weak")

    if run_decision == "pass":
        timing_decision: Decision = "fail" if timing_reasons else "pass"
        if timing_decision == "pass":
            timing_reasons.append("monthly_supported")
    elif run_decision == "fail":
        timing_decision = "fail"
        timing_reasons = ["run_ineligible", *timing_reasons]
    elif timing_reasons:
        timing_decision = "fail"
    else:
        timing_decision = run_decision

    return MonthlyEvaluation(
        monthly_metrics=MonthlyMetrics(raw_metrics=raw_metrics, metrics=metrics, margins=margins),
        run_decision=run_decision,
        timing_decision=timing_decision,
        run_reasons=tuple(dict.fromkeys(run_reasons)),
        timing_reasons=tuple(dict.fromkeys(timing_reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
        provenance={
            "quality_policy": quality_policy,
            "allow_unknown_quality": allow_unknown_quality,
            "effective_support_rule": (
                "candidate_weights semantics; unknown observed_fraction contributes 1.0 "
                "only when the month is candidate-usable"
            ),
        },
    )


__all__ = ["MonthlyEvaluation", "evaluate_monthly"]


