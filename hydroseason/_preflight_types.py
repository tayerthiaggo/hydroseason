from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

Decision = Literal["pass", "fail", "indeterminate", "not_assessed"]
ThresholdMode = Literal["default", "diagnostic"]
ReasonCode: TypeAlias = str

_DECISIONS: tuple[Decision, ...] = ("pass", "fail", "indeterminate", "not_assessed")
_PROFILE_STATUSES = {"testing", "provisional", "frozen"}
_NON_NEGATIVE_THRESHOLD_FIELDS = (
    "min_clear_count",
    "min_reliable_pixels",
    "min_reliable_years",
    "min_episodic_wet_count",
    "min_episodic_pixels",
    "min_episodic_years",
    "min_candidate_years",
    "min_pooled_usable_months",
    "min_effective_usable_months",
    "min_months_per_supported_year",
    "min_supported_years",
    "min_calendar_month_supported_years",
    "min_monthly_detectable_pixels",
)
_SUMMARY_REASON_TEXT = {
    "candidate_ready": "candidate metrics satisfy thresholds",
    "monthly_supported": "monthly support meets downstream defaults",
    "timing_borderline": "timing support is near threshold",
    "near_threshold_support": "support sits close to one or more thresholds",
}


def eligibility_from_decision(decision: Decision) -> bool | None:
    if decision == "pass":
        return True
    if decision == "fail":
        return False
    return None


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def _profile_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sort_key(value: Any) -> tuple[str, str]:
    return (type(value).__name__, repr(value))


def _freeze_mapping(mapping: Any) -> tuple[tuple[Any, Any], ...]:
    if isinstance(mapping, tuple) and all(isinstance(item, tuple) and len(item) == 2 for item in mapping):
        return tuple((key, _freeze_value(value)) for key, value in mapping)
    if not isinstance(mapping, dict):
        raise TypeError("expected a mapping payload")
    return tuple(
        (key, _freeze_value(value))
        for key, value in sorted(mapping.items(), key=lambda item: _sort_key(item[0]))
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


def _thaw_value(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(isinstance(item, tuple) and len(item) == 2 for item in value):
            return {key: _thaw_value(item_value) for key, item_value in value}
        return [_thaw_value(item) for item in value]
    return value


def _validate_decision(field_name: str, decision: Decision) -> None:
    if decision not in _DECISIONS:
        raise ValueError(f"{field_name} must be one of {_DECISIONS}.")


def _reason_text(code: str) -> str:
    return _SUMMARY_REASON_TEXT.get(code, code.replace("_", " "))


@dataclass(frozen=True)
class PreflightThresholds:
    profile_name: str
    profile_version: str
    profile_status: Literal["testing", "provisional", "frozen"]
    min_clear_count: int
    min_frequency_fraction: float
    min_reliable_pixels: int
    min_reliable_years: int
    min_episodic_wet_count: int
    min_episodic_pixels: int
    min_episodic_years: int
    min_candidate_years: int
    min_pooled_usable_months: int
    min_effective_usable_months: float
    min_months_per_supported_year: int
    min_supported_years: int
    min_calendar_month_supported_years: int
    calendar_month_warning_support_fraction: float
    min_monthly_detectable_pixels: int
    near_threshold_margin_fraction: float

    def __post_init__(self) -> None:
        if self.profile_status not in _PROFILE_STATUSES:
            raise ValueError("profile_status must be testing, provisional, or frozen.")
        for field_name in _NON_NEGATIVE_THRESHOLD_FIELDS:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative.")
        if not 0.0 <= self.min_frequency_fraction <= 1.0:
            raise ValueError("min_frequency_fraction must be between 0 and 1.")
        if not 0.0 <= self.calendar_month_warning_support_fraction <= 1.0:
            raise ValueError(
                "calendar_month_warning_support_fraction must be between 0 and 1."
            )
        if not 0.0 <= self.near_threshold_margin_fraction <= 1.0:
            raise ValueError("near_threshold_margin_fraction must be between 0 and 1.")
        if self.min_months_per_supported_year < 1 or self.min_months_per_supported_year > 12:
            raise ValueError("min_months_per_supported_year must be between 1 and 12.")

    @classmethod
    def testing(cls) -> "PreflightThresholds":
        return cls(
            "testing",
            "1",
            "testing",
            2,
            0.25,
            2,
            2,
            1,
            2,
            2,
            2,
            45,
            40.0,
            9,
            5,
            2,
            0.75,
            2,
            0.10,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "profile_version": self.profile_version,
            "profile_status": self.profile_status,
            "min_clear_count": self.min_clear_count,
            "min_frequency_fraction": self.min_frequency_fraction,
            "min_reliable_pixels": self.min_reliable_pixels,
            "min_reliable_years": self.min_reliable_years,
            "min_episodic_wet_count": self.min_episodic_wet_count,
            "min_episodic_pixels": self.min_episodic_pixels,
            "min_episodic_years": self.min_episodic_years,
            "min_candidate_years": self.min_candidate_years,
            "min_pooled_usable_months": self.min_pooled_usable_months,
            "min_effective_usable_months": self.min_effective_usable_months,
            "min_months_per_supported_year": self.min_months_per_supported_year,
            "min_supported_years": self.min_supported_years,
            "min_calendar_month_supported_years": self.min_calendar_month_supported_years,
            "calendar_month_warning_support_fraction": (
                self.calendar_month_warning_support_fraction
            ),
            "min_monthly_detectable_pixels": self.min_monthly_detectable_pixels,
            "near_threshold_margin_fraction": self.near_threshold_margin_fraction,
        }

    @property
    def profile_hash(self) -> str:
        return _profile_digest(self.to_dict())


@dataclass(frozen=True)
class PreflightCapabilities:
    annual_recurrence: bool
    per_year_detection: bool
    fixed_climatological_window: bool
    event_characterisation: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "annual_recurrence": self.annual_recurrence,
            "per_year_detection": self.per_year_detection,
            "fixed_climatological_window": self.fixed_climatological_window,
            "event_characterisation": self.event_characterisation,
        }


@dataclass(frozen=True)
class MonthlyObservationCapabilities:
    per_month_pixel_counts: bool
    unique_monthly_pixels: bool
    candidate_monthly_overlap: bool
    exact_geometry: bool
    exact_time_window: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "per_month_pixel_counts": self.per_month_pixel_counts,
            "unique_monthly_pixels": self.unique_monthly_pixels,
            "candidate_monthly_overlap": self.candidate_monthly_overlap,
            "exact_geometry": self.exact_geometry,
            "exact_time_window": self.exact_time_window,
        }


@dataclass(frozen=True)
class CandidateMetrics:
    metrics: dict[str, Any] | tuple[tuple[Any, Any], ...] = field(default_factory=dict)
    margins: dict[str, Any] | tuple[tuple[Any, Any], ...] = field(default_factory=dict)
    raw_metrics: dict[str, Any] | tuple[tuple[Any, Any], ...] = field(
        default_factory=dict,
        kw_only=True,
    )
    evidence: Any = field(default=None, repr=False, compare=False, kw_only=True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_metrics", _freeze_mapping(self.raw_metrics))
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics))
        object.__setattr__(self, "margins", _freeze_mapping(self.margins))

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_metrics": _thaw_value(self.raw_metrics),
            "metrics": _thaw_value(self.metrics),
            "margins": _thaw_value(self.margins),
        }


@dataclass(frozen=True)
class MonthlyMetrics:
    metrics: dict[str, Any] | tuple[tuple[Any, Any], ...]
    margins: dict[str, Any] | tuple[tuple[Any, Any], ...] = field(default_factory=dict)
    raw_metrics: dict[str, Any] | tuple[tuple[Any, Any], ...] = field(
        default_factory=dict,
        kw_only=True,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_metrics", _freeze_mapping(self.raw_metrics))
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics))
        object.__setattr__(self, "margins", _freeze_mapping(self.margins))

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_metrics": _thaw_value(self.raw_metrics),
            "metrics": _thaw_value(self.metrics),
            "margins": _thaw_value(self.margins),
        }


@dataclass(frozen=True)
class PreflightResult:
    thresholds: PreflightThresholds
    capabilities: PreflightCapabilities
    candidate_metrics: CandidateMetrics
    monthly_metrics: MonthlyMetrics
    candidate_decision: Decision
    monthly_decision: Decision
    timing_decision: Decision
    candidate_reasons: tuple[ReasonCode, ...] = ()
    monthly_reasons: tuple[ReasonCode, ...] = ()
    timing_reasons: tuple[ReasonCode, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: dict[str, Any] | tuple[tuple[Any, Any], ...] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_decision("candidate_decision", self.candidate_decision)
        _validate_decision("monthly_decision", self.monthly_decision)
        _validate_decision("timing_decision", self.timing_decision)
        object.__setattr__(self, "candidate_reasons", tuple(self.candidate_reasons))
        object.__setattr__(self, "monthly_reasons", tuple(self.monthly_reasons))
        object.__setattr__(self, "timing_reasons", tuple(self.timing_reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))

    @property
    def candidate_eligible(self) -> bool | None:
        return eligibility_from_decision(self.candidate_decision)

    @property
    def monthly_eligible(self) -> bool | None:
        return eligibility_from_decision(self.monthly_decision)

    @property
    def timing_eligible(self) -> bool | None:
        return eligibility_from_decision(self.timing_decision)

    @property
    def reasons(self) -> tuple[ReasonCode, ...]:
        return tuple(
            dict.fromkeys(
                self.candidate_reasons + self.monthly_reasons + self.timing_reasons
            )
        )

    def summary(self) -> str:
        parts = [
            f"Candidate {self.candidate_decision}: {', '.join(_reason_text(code) for code in self.candidate_reasons) or 'no reasons recorded'}",
            f"Monthly {self.monthly_decision}: {', '.join(_reason_text(code) for code in self.monthly_reasons) or 'no reasons recorded'}",
            f"Timing {self.timing_decision}: {', '.join(_reason_text(code) for code in self.timing_reasons) or 'no reasons recorded'}",
        ]
        return ". ".join(parts)

    def to_dict(self, *, flat: bool = True) -> dict[str, Any]:
        candidate_payload = self.candidate_metrics.to_dict()
        monthly_payload = self.monthly_metrics.to_dict()
        reasons_payload = {
            "candidate": list(self.candidate_reasons),
            "monthly": list(self.monthly_reasons),
            "timing": list(self.timing_reasons),
        }
        margins_payload = {
            "candidate": candidate_payload["margins"],
            "monthly": monthly_payload["margins"],
        }
        metrics_payload = {
            "candidate": candidate_payload["metrics"],
            "candidate_raw": candidate_payload["raw_metrics"],
            "monthly": monthly_payload["metrics"],
            "monthly_raw": monthly_payload["raw_metrics"],
        }
        provenance_payload = _thaw_value(self.provenance)
        nested = {
            "candidate_decision": self.candidate_decision,
            "candidate_eligible": self.candidate_eligible,
            "monthly_decision": self.monthly_decision,
            "monthly_eligible": self.monthly_eligible,
            "timing_decision": self.timing_decision,
            "timing_eligible": self.timing_eligible,
            "summary": self.summary(),
            "profile_hash": self.thresholds.profile_hash,
            "thresholds": self.thresholds.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "candidate_metrics": candidate_payload,
            "monthly_metrics": monthly_payload,
            "reasons": reasons_payload,
            "warnings": list(self.warnings),
            "provenance": provenance_payload,
        }
        if not flat:
            return nested
        return {
            "candidate_decision": self.candidate_decision,
            "candidate_eligible": self.candidate_eligible,
            "monthly_decision": self.monthly_decision,
            "monthly_eligible": self.monthly_eligible,
            "timing_decision": self.timing_decision,
            "timing_eligible": self.timing_eligible,
            "summary": self.summary(),
            "profile_hash": self.thresholds.profile_hash,
            "capabilities_json": _canonical_json(self.capabilities.to_dict()),
            "metrics_json": _canonical_json(metrics_payload),
            "margins_json": _canonical_json(margins_payload),
            "thresholds_json": _canonical_json(self.thresholds.to_dict()),
            "warnings_json": _canonical_json(list(self.warnings)),
            "reasons_json": _canonical_json(reasons_payload),
            "provenance_json": _canonical_json(provenance_payload),
        }


@dataclass(frozen=True)
class MonthlyObservationRecord:
    frame: Any
    capabilities: MonthlyObservationCapabilities
    detectable_mask: Any = None
    grid_identity: dict[str, Any] = field(default_factory=dict)
    source_identity: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": self.capabilities.to_dict(),
            "grid_identity": dict(self.grid_identity),
            "source_identity": dict(self.source_identity),
        }


__all__ = [
    "CandidateMetrics",
    "Decision",
    "MonthlyObservationCapabilities",
    "MonthlyObservationRecord",
    "MonthlyMetrics",
    "PreflightCapabilities",
    "PreflightResult",
    "PreflightThresholds",
    "ReasonCode",
    "ThresholdMode",
    "eligibility_from_decision",
]


