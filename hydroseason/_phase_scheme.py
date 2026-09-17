from __future__ import annotations

import warnings
from typing import Any, Literal, Mapping, cast

PhaseScheme = Literal["two_phase", "four_phase", "none"]
LegacyPhaseModel = Literal["cycle_relative", "rule_based", "none"]


class UnsetPhaseScheme:
    pass


PHASE_SCHEME_UNSET = UnsetPhaseScheme()


def resolve_phase_scheme(
    *,
    phase_scheme: PhaseScheme | UnsetPhaseScheme = PHASE_SCHEME_UNSET,
    phase_model: LegacyPhaseModel | None = None,
) -> PhaseScheme:
    if phase_scheme is not PHASE_SCHEME_UNSET and phase_model is not None:
        raise ValueError("phase_scheme and phase_model cannot both be supplied")
    if phase_model is not None:
        if phase_model not in {"cycle_relative", "rule_based", "none"}:
            raise ValueError("phase_model must be 'cycle_relative', 'rule_based', or 'none'")
        warnings.warn(
            "phase_model is deprecated; use phase_scheme='two_phase' or 'none'",
            DeprecationWarning,
            stacklevel=3,
        )
        return "none" if phase_model == "none" else "two_phase"
    selected = "two_phase" if phase_scheme is PHASE_SCHEME_UNSET else phase_scheme
    if selected == "four_phase":
        warnings.warn(
            "phase_scheme='four_phase' is deprecated; using two rising/receding phases",
            DeprecationWarning,
            stacklevel=3,
        )
        return "two_phase"
    if selected not in {"two_phase", "none"}:
        raise ValueError("phase_scheme must be 'two_phase' or 'none'")
    return cast(PhaseScheme, selected)


def inject_phase_options(
    options: Mapping[str, Any] | None,
    *,
    phase_scheme: PhaseScheme | UnsetPhaseScheme = PHASE_SCHEME_UNSET,
    phase_model: LegacyPhaseModel | None = None,
) -> dict[str, Any]:
    merged = dict(options or {})
    direct = phase_scheme is not PHASE_SCHEME_UNSET or phase_model is not None
    mapped = "phase_scheme" in merged or "phase_model" in merged
    if direct and mapped:
        raise ValueError("phase selection cannot be supplied both directly and in analysis_options")
    if direct:
        if phase_scheme is not PHASE_SCHEME_UNSET:
            merged["phase_scheme"] = phase_scheme
        if phase_model is not None:
            merged["phase_model"] = phase_model
    return merged
