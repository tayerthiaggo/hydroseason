"""Step 5: reserved-evidence validation for the frozen direct-profile candidate.

Runs exactly once against evidence untouched by Step 4 development:
- synthetic seeds 100000-100007 (reserved; never accessed by
  evaluate_direct_profile.py) on the same 8 development families, and
- two reserved held-out (shape/noise) families never present in the
  development matrix (validation protocol section 9; numerics spec
  section 9): a strong-AR(1)-dependence case and a high-noise-amplitude
  case, both beyond the ranges swept in development.

The frozen candidate and its constants are declared in
``frozen-candidate.json``, written before this script's first run. This
script refuses to run if that file is missing, and refuses to silently
re-run with different frozen parameters once its own output exists.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason._trough_refinement import PeakBoundary, refine_trough_span  # noqa: E402
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY  # noqa: E402

from direct_profile import refine_trough_span_direct_profile  # noqa: E402
from evaluate_direct_profile import FAMILIES, declared_endpoint_index, score_records  # noqa: E402

FROZEN = json.loads((HERE / "frozen-candidate.json").read_text(encoding="utf-8"))
PARAMS = FROZEN["frozen_parameters"]
DELTA_PP = PARAMS["delta_pp"]

RESERVED_SEEDS = list(range(100000, 100008))

# Reserved held-out families (validation protocol section 9): never present
# in evaluate_direct_profile.py's development FAMILIES table, and evaluated
# only here, once.
HELD_OUT_FAMILIES = {
    # New shape: slow multi-step recession then an abrupt, brief low state,
    # not present in any development family (development shapes either
    # recede in one smooth step or hold a long plateau).
    "held_out_asymmetric_recession": [.40, .35, .28, .20, .14, .12, .12, .30, .40],
}
HELD_OUT_NOISE_CASES = [
    # Beyond development's ar1_phi in {0.0, 0.7}: strong temporal dependence.
    {"label": "held_out_high_dependence", "family": "plateau", "sigma_pp": 0.4, "phi": 0.9},
    # Beyond development's noise_sigma_pp in {0.0, 0.1, 0.4}: high amplitude.
    {"label": "held_out_high_noise", "family": "curved_recession", "sigma_pp": 1.0, "phi": 0.0},
]


def predictions(frame, left, right):
    kwargs = {"left_peak": left, "right_peak": right, "policy": TROUGH_REFINEMENT_POLICY}
    yield "existing", refine_trough_span(frame, **kwargs)
    yield "direct_profile_combined", refine_trough_span_direct_profile(
        frame, **kwargs, delta_pp=DELTA_PP,
        l_uncertainty_k=PARAMS["l_uncertainty_k"], scale_mode=PARAMS["scale_mode"],
    )


def _run_case(latent, truth, seed_offset, sigma, phi, family_label):
    rng = np.random.default_rng(seed_offset)
    noise = rng.normal(0.0, sigma, len(latent))
    for index in range(1, len(noise)):
        noise[index] = phi * noise[index - 1] + np.sqrt(1 - phi**2) * noise[index]
    dates = pd.date_range("2040-01-01", periods=len(latent), freq="MS")
    values = np.clip(np.asarray(latent) * 100.0 + noise, 0.0, 100.0)
    frame = prepare_monthly_extent(pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates))
    left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
    right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
    rows = []
    for candidate, result in predictions(frame, left, right):
        applied = result.status in {"confirmed", "provisional"} and result.boundary is not None
        rows.append({
            "family": family_label, "candidate": candidate,
            "declared_endpoint_index": truth, "resolvable_from_observation": True,
            "predicted_index": dates.get_loc(result.boundary) if applied else None,
            "support_indexes": [dates.get_loc(d) for d in result.boundary_candidates] if applied else [],
            "status": result.status, "reason": result.reason,
        })
    return rows


def main():
    if (HERE / "validation-report.json").exists():
        raise RuntimeError(
            "validation-report.json already exists: reserved evidence has already been "
            "evaluated once for this frozen candidate. A changed result requires a new "
            "candidate identity, not a rerun of this script."
        )
    records = []

    # Reserved seeds on the 8 development families, same noise grid as
    # development, at seeds this candidate's development pass never touched.
    for family_index, (family, latent) in enumerate(FAMILIES.items()):
        truth = declared_endpoint_index(latent, DELTA_PP)
        for seed in RESERVED_SEEDS:
            for sigma in (0.0, 0.1, 0.4):
                for phi in (0.0, 0.7):
                    seed_offset = 9500000 + family_index * 1000 + seed
                    records.extend(_run_case(latent, truth, seed_offset, sigma, phi, family))

    # Reserved held-out shape family.
    for family, latent in HELD_OUT_FAMILIES.items():
        truth = declared_endpoint_index(latent, DELTA_PP)
        for seed in RESERVED_SEEDS:
            for sigma in (0.0, 0.1, 0.4):
                for phi in (0.0, 0.7):
                    seed_offset = 9800000 + seed
                    records.extend(_run_case(latent, truth, seed_offset, sigma, phi, family))

    # Reserved held-out noise/dependence settings on existing shapes.
    for case in HELD_OUT_NOISE_CASES:
        latent = FAMILIES[case["family"]]
        truth = declared_endpoint_index(latent, DELTA_PP)
        for seed in RESERVED_SEEDS:
            seed_offset = 9900000 + seed
            records.extend(_run_case(latent, truth, seed_offset, case["sigma_pp"], case["phi"], case["label"]))

    (HERE / "validation-records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    summaries = []
    for candidate in ("existing", "direct_profile_combined"):
        for family in ("all", *FAMILIES, *HELD_OUT_FAMILIES, *{c["label"] for c in HELD_OUT_NOISE_CASES}):
            subset = [r for r in records if r["candidate"] == candidate and (family == "all" or r["family"] == family)]
            if not subset:
                continue
            summaries.append({"candidate": candidate, "family": family, **score_records(subset)})
    frame = pd.DataFrame(summaries)
    frame.to_csv(HERE / "validation-summary.csv", index=False)

    gates = {}
    for candidate in ("existing", "direct_profile_combined"):
        overall = frame[(frame.candidate == candidate) & (frame.family == "all")].iloc[0]
        gates[candidate] = {
            "coverage_at_least_0_95": bool(overall.unconditional_support_coverage >= 0.95),
            "median_at_most_1": bool(overall.median_error_months is None or overall.median_error_months <= 1.0),
            "p90_at_most_2": bool(overall.p90_error_months is None or overall.p90_error_months <= 2.0),
        }
    report = {
        "frozen_candidate": FROZEN,
        "reserved_seeds": RESERVED_SEEDS,
        "held_out_families": list(HELD_OUT_FAMILIES) + [c["label"] for c in HELD_OUT_NOISE_CASES],
        "gates": gates,
    }
    (HERE / "validation-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    sources = sorted((ROOT / "hydroseason").glob("*.py")) + [HERE / "direct_profile.py", Path(__file__)]
    manifest = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    (HERE / "validation-source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(frame[frame.family == "all"][[
        "candidate", "unconditional_support_coverage", "median_error_months", "p90_error_months",
    ]].to_string(index=False))
    print(json.dumps(gates, indent=2))


if __name__ == "__main__":
    main()
