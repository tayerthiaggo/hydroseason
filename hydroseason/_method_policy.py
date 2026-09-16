from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ._events import _DEFAULT_ENTER_K, _DEFAULT_EXIT_K, _DEFAULT_LOW_K
from ._seasonality_test import TIMING_RECURRENCE_ALPHA
from ._trough_refinement import TroughRefinementPolicy
from ._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY


@dataclass(frozen=True)
class HydroSeasonMethodPolicy:
    policy_id: str
    min_detectable_years: int
    trough_refinement: TroughRefinementPolicy


CURRENT_METHOD_POLICY = HydroSeasonMethodPolicy(
    policy_id="hydroseason-v0.2.0",
    min_detectable_years=5,
    trough_refinement=TROUGH_REFINEMENT_POLICY,
)


def method_policy_manifest() -> dict[str, Any]:
    return {
        "event_thresholds": {
            "enter_sigma": _DEFAULT_ENTER_K,
            "exit_sigma": _DEFAULT_EXIT_K,
            "low_sigma": _DEFAULT_LOW_K,
        },
        "policy_id": CURRENT_METHOD_POLICY.policy_id,
        "seasonality": {
            "alpha": TIMING_RECURRENCE_ALPHA,
            "method": "timing_recurrence",
            "min_detectable_years": CURRENT_METHOD_POLICY.min_detectable_years,
        },
        "trough_refinement": {
            "delta_rel": CURRENT_METHOD_POLICY.trough_refinement.delta_rel,
            "huber_k": CURRENT_METHOD_POLICY.trough_refinement.huber_k,
            "l_uncertainty_k": CURRENT_METHOD_POLICY.trough_refinement.l_uncertainty_k,
            "method": "direct_profile_combined",
            "profile_loss_cutoff": CURRENT_METHOD_POLICY.trough_refinement.profile_loss_cutoff,
            "pulse_z": CURRENT_METHOD_POLICY.trough_refinement.pulse_z,
            "scale_mode": CURRENT_METHOD_POLICY.trough_refinement.scale_mode,
            "version": CURRENT_METHOD_POLICY.trough_refinement.version,
        },
    }


def canonical_method_policy_json() -> str:
    manifest = method_policy_manifest()
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)


def method_policy_fingerprint() -> str:
    canonical = canonical_method_policy_json().encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
