"""Predeclared development comparison. No policy selection or promotion."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from endpoint_experiment import ROOT, refine_experimental, second_difference_scale
from hydroseason._dynamic_year import _row_peak_boundary
from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import PeakBoundary, refine_trough_span
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY

OUT = Path(__file__).resolve().parent
CONFIG = {
    "purpose": "development falsification; no parameter selection or publication validation",
    "seeds": list(range(8)),
    "noise_sigma_pp": [0.0, 0.001, 0.004],
    "ar1_phi": [0.0, 0.7],
    "candidates": ["existing", "existing_oracle_scale", "project_residual_z1",
                   "project_second_difference_z05", "project_second_difference_z1",
                   "project_second_difference_z2", "project_oracle_scale_z1"],
    "reserved_validation_seeds": "100000 and above; not run by this script",
    "oracle_scale": "known simulation sigma, unavailable for real EO inputs",
    "scope": "component results only; production peak and quality sensitivity retained",
}

FAMILIES = {
    "plateau": ([.4, .3, .2, .12, .12, .12, .12, .2, .3, .4], 6),
    "point": ([.4, .3, .2, .12, .2, .3, .4, .45, .5, .6], 3),
    "gradual": ([.4, .3, .2, .12, .122, .124, .126, .14, .2, .4], 3),
    "curved_recession": ([.4, .24, .18, .14, .13, .125, .12, .2, .3, .4], 6),
    "pulse": ([.4, .3, .12, .25, .12, .12, .12, .2, .3, .4], 6),
    "long_plateau": ([.4, .2] + [.12] * 9 + [.2, .3, .4], 10),
    "no_recovery": ([.12] * 10, None),
    "gap_at_endpoint": ([.4, .3, .2, .12, .12, .12, .12, .2, .3, .4], None),
}


def score_records(records):
    resolvable = [row for row in records if row["truth_index"] is not None]
    unresolvable = [row for row in records if row["truth_index"] is None]
    applied = [row for row in records if row["predicted_index"] is not None]
    resolved_applied = [row for row in resolvable if row["predicted_index"] is not None]
    point = [row for row in applied if len(row["support_indexes"]) == 1]
    errors = [row["predicted_index"] - row["truth_index"] for row in resolved_applied]
    covered = sum(row["truth_index"] in row["support_indexes"] for row in resolvable)
    false_precise = sum(row["predicted_index"] is not None and len(row["support_indexes"]) == 1 for row in unresolvable)
    wrong_point = sum(row["truth_index"] is None or row["support_indexes"][0] != row["truth_index"] for row in point)
    widths = [max(row["support_indexes"]) - min(row["support_indexes"]) for row in applied if row["support_indexes"]]
    return {
        "n": len(records), "resolvable_n": len(resolvable),
        "all_case_applied_n": len(applied), "resolvable_applied_n": len(resolved_applied),
        "resolvable_coverage": len(resolved_applied) / len(resolvable) if resolvable else None,
        "all_case_coverage": len(applied) / len(records) if records else None,
        "truth_support_coverage": covered / len(resolvable) if resolvable else None,
        "unresolvable_n": len(unresolvable), "false_precise_unresolvable_n": false_precise,
        "point_predictions_n": len(point), "wrong_point_predictions_n": wrong_point,
        "median_error_months": float(np.median(np.abs(errors))) if errors else None,
        "p90_error_months": float(np.percentile(np.abs(errors), 90)) if errors else None,
        "early_n": sum(error < 0 for error in errors), "late_n": sum(error > 0 for error in errors),
        "mean_support_width_months": float(np.mean(widths)) if widths else None,
    }


def predictions(frame, left, right, oracle_sigma):
    kwargs = {"left_peak": left, "right_peak": right, "policy": TROUGH_REFINEMENT_POLICY}
    yield "existing", refine_trough_span(frame, **kwargs)
    if oracle_sigma is not None:
        yield "existing_oracle_scale", refine_trough_span(frame, **kwargs, measurement_tolerance_pp=oracle_sigma)
    yield "project_residual_z1", refine_experimental(frame, **kwargs)
    for z, suffix in ((.5, "05"), (1., "1"), (2., "2")):
        yield f"project_second_difference_z{suffix}", refine_experimental(
            frame, **kwargs, low_state_z=z, scale_mode="second_difference",
        )
    if oracle_sigma is not None:
        yield "project_oracle_scale_z1", refine_experimental(
            frame, **kwargs, measurement_tolerance_pp=oracle_sigma,
        )


def evaluate_synthetic():
    records = []
    for family_index, (family, (latent, truth)) in enumerate(FAMILIES.items()):
        for seed in CONFIG["seeds"]:
            for sigma in CONFIG["noise_sigma_pp"]:
                for phi in CONFIG["ar1_phi"]:
                    rng = np.random.default_rng(9000000 + family_index * 1000 + seed)
                    noise = rng.normal(0., sigma, len(latent))
                    for index in range(1, len(noise)):
                        noise[index] = phi * noise[index - 1] + np.sqrt(1 - phi**2) * noise[index]
                    dates = pd.date_range("2040-01-01", periods=len(latent), freq="MS")
                    values = np.maximum(0., np.asarray(latent) + noise)
                    if family == "gap_at_endpoint":
                        values[5:8] = np.nan
                    frame = prepare_monthly_extent(pd.DataFrame(
                        {"extent_pct": values, "invalid_pct": 0.0}, index=dates,
                    ))
                    left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
                    right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
                    for candidate, result in predictions(frame, left, right, sigma):
                        applied = result.status in {"confirmed", "provisional"} and result.boundary is not None
                        records.append({
                            "family": family, "seed": seed, "sigma_pp": sigma, "phi": phi,
                            "candidate": candidate, "truth_index": truth,
                            "predicted_index": dates.get_loc(result.boundary) if applied else None,
                            "support_indexes": [dates.get_loc(date) for date in result.boundary_candidates] if applied else [],
                            "estimated_second_difference_pp": second_difference_scale(values),
                            "local_scale_pp": result.local_scale_pp,
                            "status": result.status, "reason": result.reason,
                        })
        print(f"synthetic {family} complete", flush=True)
    (OUT / "endpoint-synthetic-records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    summaries = []
    for candidate in CONFIG["candidates"]:
        for family in ("all", *FAMILIES):
            subset = [row for row in records if row["candidate"] == candidate and (family == "all" or row["family"] == family)]
            summaries.append({"candidate": candidate, "family": family, **score_records(subset)})
    pd.DataFrame(summaries).to_csv(OUT / "endpoint-synthetic-summary.csv", index=False)


def evaluate_real():
    records = []
    bundle = ROOT / "case_studies/results/final-review-2026-09-08/after/refinement"
    for catchment in ("daly_river_nt", "fitzroy_river_wa"):
        frame = prepare_monthly_extent(pd.read_csv(ROOT / f"case_studies/data/extent/{catchment}_30m.csv"))
        annual = pd.read_csv(bundle / catchment / "full_hydro_years.csv")
        for index, row in annual.iterrows():
            if catchment == "daly_river_nt" and int(row.hy_year) not in {2005, 2008, 2011, 2012, 2014, 2016, 2018, 2019, 2020}:
                continue
            left = _row_peak_boundary(row)
            right = _row_peak_boundary(annual.iloc[index + 1]) if index + 1 < len(annual) else None
            for candidate, result in predictions(frame, left, right, None):
                records.append({"catchment": catchment, "hy_year": int(row.hy_year), "candidate": candidate, **asdict(result)})
            print(f"real {catchment} {int(row.hy_year)} complete", flush=True)
    pd.DataFrame(records).to_csv(OUT / "endpoint-real-development.csv", index=False)


def main():
    sources = sorted((ROOT / "hydroseason").glob("*.py")) + sorted(OUT.glob("*.py"))
    configuration = {
        **CONFIG, "families": FAMILIES, "baseline_policy": asdict(TROUGH_REFINEMENT_POLICY),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    }
    # Write the exact experiment before observing outcomes. Changes require an
    # explicit new experiment identity; this script does not search a policy.
    path = OUT / "endpoint-experiment-config.json"
    payload = json.dumps(configuration, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError("frozen development experiment changed; use a new experiment identity")
    path.write_text(payload, encoding="utf-8")
    evaluate_synthetic()
    evaluate_real()
    names = ["endpoint-experiment-config.json", "endpoint-synthetic-records.json", "endpoint-synthetic-summary.csv", "endpoint-real-development.csv"]
    hashes = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in names}
    (OUT / "endpoint-output-manifest.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
