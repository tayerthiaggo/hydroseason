from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
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


SCIENTIFIC_SOURCE_FILES = (
    "hydroseason/_method_policy.py",
    "hydroseason/_events.py",
    "hydroseason/_seasonality_test.py",
    "hydroseason/_trough_refinement.py",
    "hydroseason/_trough_refinement_defaults.py",
    "hydroseason/_regime.py",
    "hydroseason/_catchment.py",
    "hydroseason/_exceptions.py",
    "hydroseason/_fingerprint.py",
)


def _verify_scientific_source_clean(repo_root: Path, *, allow_dirty: bool = False) -> None:
    if allow_dirty:
        return
    res = subprocess.run(
        ["git", "status", "--porcelain", "--", *SCIENTIFIC_SOURCE_FILES],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    dirty_lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if not dirty_lines:
        return

    is_only_method_policy = len(dirty_lines) == 1 and all(
        "hydroseason/_method_policy.py" in line.replace("\\", "/") for line in dirty_lines
    )
    if is_only_method_policy:
        diff_res = subprocess.run(
            ["git", "diff", "HEAD", "--", "hydroseason/_method_policy.py"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        deleted_lines = [
            line.lstrip("-\ufeff\xef\xbb\xbf").strip()
            for line in diff_res.stdout.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        meaningful_deleted = [
            line for line in deleted_lines
            if line and line != "from __future__ import annotations"
        ]
        if not meaningful_deleted:
            return

    raise RuntimeError(
        "Scientific source tree is dirty; refusing to generate canonical method policy manifest"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate canonical method policy manifest and SHA-256 sidecar."
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Target manifest JSON file path (e.g. docs/method-policy-v0.2.0.json).",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow generation when scientific files are dirty (development/testing only).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    _verify_scientific_source_clean(repo_root, allow_dirty=args.allow_dirty)

    manifest = method_policy_manifest()
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    digest = hashlib.sha256(payload).hexdigest()
    sidecar = target.with_name(target.name.replace(".json", "") + ".sha256")
    sidecar.write_bytes(f"{digest}\n".encode("ascii"))
    if sidecar != target.with_suffix(".sha256"):
        target.with_suffix(".sha256").write_bytes(f"{digest}\n".encode("ascii"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

