"""Stage C, Step 6: full five-catchment comparison bundle (unblinded).

Compares the shape_fit baseline (production TROUGH_REFINEMENT_POLICY) against
the newly integrated direct_profile_combined candidate
(TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY) across every trough-refinement-
eligible cycle in the five development catchments (Daly, Fitzroy, Gilbert,
Lachlan, Moonie), using each catchment's frozen pass-1 peaks/troughs
(case_studies/results/final-review-2026-09-08/after/refinement/<name>/full_hydro_years.csv)
so this is purely a pass-2 (trough refinement) comparison -- pass-1 peaks and
chronology are the fixed baseline, unaffected by candidate choice (matches the
atomic adjacent-cycle acceptance the plan requires unchanged).

This is the *unblinded* companion to blind_review.html / blind_check_all.py:
those tools drove the human review; this one produces the permanent, fully
labelled comparison record and the nine-Daly-example disposition.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from hydroseason._dynamic_year import _row_peak_boundary  # noqa: E402
from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason._trough_refinement import refine_trough_span  # noqa: E402
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY  # noqa: E402
from hydroseason._trough_refinement_direct_profile_defaults import (  # noqa: E402
    TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY,
)

CATCHMENTS = ["daly_river_nt", "fitzroy_river_wa", "gilbert_river_qld", "lachlan_river_nsw", "moonie_river_qld_nsw"]
NINE_DALY_YEARS = {2005, 2008, 2011, 2012, 2014, 2016, 2018, 2019, 2020}


def _fmt(result):
    return {
        "boundary": result.boundary.strftime("%Y-%m") if result.boundary is not None else None,
        "support": ",".join(d.strftime("%Y-%m") for d in result.boundary_candidates),
        "support_width_months": (
            len(result.boundary_candidates) - 1 if len(result.boundary_candidates) > 1 else 0
        ),
        "status": result.status,
        "reason": result.reason,
    }


def main():
    rows = []
    for name in CATCHMENTS:
        frame = prepare_monthly_extent(pd.read_csv(ROOT / f"case_studies/data/extent/{name}_30m.csv"))
        annual = pd.read_csv(
            ROOT / f"case_studies/results/final-review-2026-09-08/after/refinement/{name}/full_hydro_years.csv"
        )
        for index, row in annual.iterrows():
            left = _row_peak_boundary(row)
            right = _row_peak_boundary(annual.iloc[index + 1]) if index + 1 < len(annual) else None
            if left.selected is None or right is None or right.selected is None:
                continue
            baseline = refine_trough_span(frame, left_peak=left, right_peak=right, policy=TROUGH_REFINEMENT_POLICY)
            candidate = refine_trough_span(
                frame, left_peak=left, right_peak=right, policy=TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY,
            )
            record = {
                "catchment": name, "hy_year": int(row.hy_year),
                "left_peak": left.selected.strftime("%Y-%m"), "right_peak": right.selected.strftime("%Y-%m"),
                "is_nine_daly_example": name == "daly_river_nt" and int(row.hy_year) in NINE_DALY_YEARS,
            }
            for prefix, result in (("baseline", baseline), ("candidate", candidate)):
                for key, value in _fmt(result).items():
                    record[f"{prefix}_{key}"] = value
            record["dates_agree"] = record["baseline_boundary"] == record["candidate_boundary"]
            rows.append(record)

    frame = pd.DataFrame(rows)
    frame.to_csv(HERE / "five_catchment_bundle.csv", index=False)

    n = len(frame)
    n_agree = int(frame["dates_agree"].sum())
    print(f"{n} cycles compared across {len(CATCHMENTS)} catchments; {n_agree} identical, {n - n_agree} differ")

    daly = frame[frame["is_nine_daly_example"]].sort_values("hy_year")
    daly.to_csv(HERE / "daly_nine_example_disposition.csv", index=False)
    print("\nNine Daly examples:")
    print(daly[[
        "hy_year", "baseline_boundary", "baseline_status", "candidate_boundary", "candidate_status", "dates_agree",
    ]].to_string(index=False))


if __name__ == "__main__":
    main()
