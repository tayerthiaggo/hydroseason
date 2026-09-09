"""Frozen development comparison for the direct-profile candidate.

Predeclared per the Step 2 validation protocol and Step 3 coding plan. No
parameter selection or promotion happens here -- this produces development
evidence only (Stage B, Step 4). Held-out seeds/families remain reserved for
Step 5 and are never accessed by this script.
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

# Same shape families as the frozen first experiment
# (case_studies/results/low-state-refinement-2026-09-09/evaluate_endpoint.py),
# reused for direct comparability. `latent_change_point_index` matches that
# script's `FAMILIES` truth. `declared_endpoint_index` is computed per-record
# below under this protocol's fixed DELTA_PP (validation protocol section 1),
# not from each scenario's own injected noise sigma.
FAMILIES = {
    "plateau": [.4, .3, .2, .12, .12, .12, .12, .2, .3, .4],
    "point": [.4, .3, .2, .12, .2, .3, .4, .45, .5, .6],
    "gradual": [.4, .3, .2, .12, .122, .124, .126, .14, .2, .4],
    "curved_recession": [.4, .24, .18, .14, .13, .125, .12, .2, .3, .4],
    "pulse": [.4, .3, .12, .25, .12, .12, .12, .2, .3, .4],
    "long_plateau": [.4, .2] + [.12] * 9 + [.2, .3, .4],
    "no_recovery": [.12] * 10,
    "gap_at_endpoint": [.4, .3, .2, .12, .12, .12, .12, .2, .3, .4],
}

DELTA_PP = 0.4  # fixed independently of any candidate's own scale (contract §6); percentage points
CONFIG = {
    "purpose": "Stage B Step 4 development falsification; no parameter selection or publication validation",
    "seeds": list(range(8)),
    "noise_sigma_pp": [0.0, 0.1, 0.4],
    "ar1_phi": [0.0, 0.7],
    "delta_pp": DELTA_PP,
    "candidates": [
        "existing", "existing_oracle_scale",
        "direct_profile_residual", "direct_profile_combined", "direct_profile_oracle_scale",
    ],
    "reserved_validation_seeds": "100000 and above; not run by this script",
    "reserved_held_out_families": "two additional families reserved for Step 5; not present here",
    "oracle_scale": "known simulation sigma, unavailable for real EO inputs",
    "scope": "component results only; production peak and quality sensitivity retained",
}


def declared_endpoint_index(latent: list[float], delta_pp: float) -> int | None:
    """Equivalence-state truth under this protocol's fixed delta_pp.

    Last interior index within `delta_pp` of the latent minimum, provided the
    low run does not touch either edge (validation protocol section 1;
    endpoint contract section 5).
    """
    values = np.asarray(latent, dtype=float) * 100.0
    level = float(values.min())
    ceiling = level + delta_pp
    n = values.size
    below = np.flatnonzero(values <= ceiling + 1e-9)
    interior = below[(below > 0) & (below < n - 1)]
    if interior.size == 0:
        return None
    candidate = int(interior[-1])
    run_start, run_end = candidate, candidate
    while run_start - 1 >= 0 and values[run_start - 1] <= ceiling + 1e-9:
        run_start -= 1
    while run_end + 1 < n and values[run_end + 1] <= ceiling + 1e-9:
        run_end += 1
    if run_start == 0 or run_end == n - 1:
        return None
    return candidate


def predictions(frame, left, right, oracle_sigma):
    kwargs = {"left_peak": left, "right_peak": right, "policy": TROUGH_REFINEMENT_POLICY}
    yield "existing", refine_trough_span(frame, **kwargs)
    if oracle_sigma is not None:
        yield "existing_oracle_scale", refine_trough_span(frame, **kwargs, measurement_tolerance_pp=oracle_sigma)
    yield "direct_profile_residual", refine_trough_span_direct_profile(frame, **kwargs, delta_pp=DELTA_PP)
    yield "direct_profile_combined", refine_trough_span_direct_profile(
        frame, **kwargs, delta_pp=DELTA_PP, scale_mode="combined",
    )
    if oracle_sigma is not None:
        yield "direct_profile_oracle_scale", refine_trough_span_direct_profile(
            frame, **kwargs, delta_pp=DELTA_PP, measurement_tolerance_pp=oracle_sigma,
        )


def score_records(records):
    resolvable = [
        row for row in records
        if row["declared_endpoint_index"] is not None and row["resolvable_from_observation"]
    ]
    unresolvable = [row for row in records if row["declared_endpoint_index"] is None]
    applied = [row for row in records if row["predicted_index"] is not None]
    resolved_applied = [row for row in resolvable if row["predicted_index"] is not None]
    point = [row for row in applied if len(row["support_indexes"]) == 1]
    errors = [row["predicted_index"] - row["declared_endpoint_index"] for row in resolved_applied]
    covered = sum(row["declared_endpoint_index"] in row["support_indexes"] for row in resolvable)
    false_precise = sum(row["predicted_index"] is not None and len(row["support_indexes"]) == 1 for row in unresolvable)
    wrong_point = sum(
        row["declared_endpoint_index"] is None or row["support_indexes"][0] != row["declared_endpoint_index"]
        for row in point
    )
    widths = [max(row["support_indexes"]) - min(row["support_indexes"]) for row in applied if row["support_indexes"]]
    return {
        "n": len(records), "resolvable_n": len(resolvable),
        "all_case_application_rate": len(applied) / len(records) if records else None,
        "applied_only_coverage": len(resolved_applied) / len(resolvable) if resolvable else None,
        "unconditional_support_coverage": covered / len(resolvable) if resolvable else None,
        "unresolvable_n": len(unresolvable), "false_precise_unresolvable_n": false_precise,
        "point_predictions_n": len(point), "incorrect_point_predictions_n": wrong_point,
        "median_error_months": float(np.median(np.abs(errors))) if errors else None,
        "p90_error_months": float(np.percentile(np.abs(errors), 90)) if errors else None,
        "early_n": sum(error < 0 for error in errors), "late_n": sum(error > 0 for error in errors),
        "mean_support_width_months": float(np.mean(widths)) if widths else None,
    }


def evaluate_synthetic():
    records = []
    for family_index, (family, latent) in enumerate(FAMILIES.items()):
        truth = declared_endpoint_index(latent, DELTA_PP)
        # gap_at_endpoint masks positions 5-7 (see below); if the declared
        # truth falls inside that masked window it is not resolvable from
        # the observed record at all, regardless of candidate (validation
        # protocol section 2) -- scoring it as a normal resolvable case would
        # penalise every candidate identically for an engineered blind spot.
        resolvable_from_observation = not (family == "gap_at_endpoint" and truth is not None and 5 <= truth < 8)
        for seed in CONFIG["seeds"]:
            for sigma in CONFIG["noise_sigma_pp"]:
                for phi in CONFIG["ar1_phi"]:
                    rng = np.random.default_rng(9500000 + family_index * 1000 + seed)
                    noise = rng.normal(0.0, sigma, len(latent))
                    for index in range(1, len(noise)):
                        noise[index] = phi * noise[index - 1] + np.sqrt(1 - phi**2) * noise[index]
                    dates = pd.date_range("2040-01-01", periods=len(latent), freq="MS")
                    values = np.clip(np.asarray(latent) * 100.0 + noise, 0.0, 100.0)
                    if family == "gap_at_endpoint":
                        values[5:8] = np.nan
                    frame = prepare_monthly_extent(pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates))
                    left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
                    right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
                    for candidate, result in predictions(frame, left, right, sigma):
                        applied = result.status in {"confirmed", "provisional"} and result.boundary is not None
                        records.append({
                            "family": family, "seed": seed, "sigma_pp": sigma, "phi": phi,
                            "candidate": candidate, "evaluation_scope": "component",
                            "declared_endpoint_index": truth,
                            "resolvable_from_observation": resolvable_from_observation,
                            "predicted_index": dates.get_loc(result.boundary) if applied else None,
                            "support_indexes": [dates.get_loc(date) for date in result.boundary_candidates] if applied else [],
                            "local_scale_pp": result.local_scale_pp,
                            "status": result.status, "reason": result.reason,
                        })
        print(f"synthetic {family} complete", flush=True)
    (HERE / "direct-profile-synthetic-records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    summaries = []
    for candidate in CONFIG["candidates"]:
        for family in ("all", *FAMILIES):
            subset = [row for row in records if row["candidate"] == candidate and (family == "all" or row["family"] == family)]
            summaries.append({"candidate": candidate, "family": family, **score_records(subset)})
    frame = pd.DataFrame(summaries)
    frame.to_csv(HERE / "direct-profile-synthetic-summary.csv", index=False)
    print(frame.query("family == 'all'")[[
        "candidate", "unconditional_support_coverage", "median_error_months",
        "p90_error_months", "all_case_application_rate", "mean_support_width_months",
    ]].to_string(index=False))


def main():
    sources = sorted((ROOT / "hydroseason").glob("*.py")) + [HERE / "direct_profile.py", Path(__file__)]
    configuration = {
        **CONFIG, "families": FAMILIES,
        "baseline_policy_version": TROUGH_REFINEMENT_POLICY.version,
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    }
    path = HERE / "direct-profile-config.json"
    payload = json.dumps(configuration, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError("frozen development experiment changed; use a new experiment identity")
    path.write_text(payload, encoding="utf-8")
    evaluate_synthetic()
    names = ["direct-profile-config.json", "direct-profile-synthetic-records.json", "direct-profile-synthetic-summary.csv"]
    hashes = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in names}
    (HERE / "direct-profile-output-manifest.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
