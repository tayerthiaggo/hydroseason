from __future__ import annotations

from typing import Any, Literal, Mapping, cast

PhaseScheme = Literal["two_phase", "none"]


class UnsetPhaseScheme:
    pass


PHASE_SCHEME_UNSET = UnsetPhaseScheme()


def resolve_phase_scheme(
    *,
    phase_scheme: PhaseScheme | UnsetPhaseScheme = PHASE_SCHEME_UNSET,
) -> PhaseScheme:
    selected = "two_phase" if phase_scheme is PHASE_SCHEME_UNSET else phase_scheme
    if selected not in {"two_phase", "none"}:
        raise ValueError("phase_scheme must be 'two_phase' or 'none'")
    return cast(PhaseScheme, selected)


def inject_phase_options(
    options: Mapping[str, Any] | None,
    *,
    phase_scheme: PhaseScheme | UnsetPhaseScheme = PHASE_SCHEME_UNSET,
) -> dict[str, Any]:
    merged = dict(options or {})
    if phase_scheme is not PHASE_SCHEME_UNSET:
        if "phase_scheme" in merged:
            raise ValueError("phase_scheme cannot be supplied both directly and in analysis_options")
        merged["phase_scheme"] = phase_scheme
    return merged
