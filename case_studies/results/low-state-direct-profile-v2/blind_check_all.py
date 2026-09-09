"""Informal real-catchment spot check across all locally available real data.

Not the formal blinded-cohort protocol (scripts/build_trough_refinement_cohort.py)
-- this is a single-reviewer sanity pass per the plan's allowance for "clearly
labelled opt-in engineering evaluation" when full real-cohort evidence isn't
available (Step 5 exit criterion). Covers:

  - The 5 catchments already used for development (Daly, Fitzroy, Gilbert,
    Lachlan, Moonie): individual CYCLES here were never scored by this
    direct-profile candidate before (only the first, rejected prototype was),
    so a disagreement between candidate and baseline on any of these cycles
    is still new information, even though the catchments themselves are
    familiar. Peak/trough context reused from the frozen final-review bundle
    (case_studies/results/final-review-2026-09-08/after/refinement/), not
    re-detected here.
  - Kakadu National Park: real DEA data already fetched for an earlier,
    unrelated stress test (case_studies/results/stress-test-full/), never
    inspected for this endpoint-refinement work at all.

Writes ONE combined blinded review file and ONE decode key, across every
catchment, so cycle order/count give no hint about which catchment (or
algorithm) is which.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from hydroseason._dynamic_year import _row_peak_boundary  # noqa: E402
from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason._trough_refinement import refine_trough_span  # noqa: E402
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY  # noqa: E402

from direct_profile import refine_trough_span_direct_profile_with_sensitivity  # noqa: E402

DELTA_PP = 0.02
DEVELOPED_CATCHMENTS = [
    "daly_river_nt", "fitzroy_river_wa", "gilbert_river_qld",
    "lachlan_river_nsw", "moonie_river_qld_nsw",
]


def _developed_frame_and_annual(name: str):
    frame = prepare_monthly_extent(pd.read_csv(ROOT / f"case_studies/data/extent/{name}_30m.csv"))
    annual = pd.read_csv(
        ROOT / f"case_studies/results/final-review-2026-09-08/after/refinement/{name}/full_hydro_years.csv"
    )
    return frame, annual


def _kakadu_frame_and_annual():
    raw = pd.read_csv(
        ROOT / "case_studies/results/stress-test-full/reports/kakadu-national-park/kakadu-national-park_monthly.csv",
        parse_dates=["date"],
    )
    frame = prepare_monthly_extent(raw[["date", "extent_pct", "invalid_pct"]].rename(columns={"date": "date"}))
    # No pre-computed peak/trough table for this stress-test-only catchment;
    # detect fresh. December is the median-minimum month in this record.
    from hydroseason import DynamicHydroYearConfig, analyze_hydrological_state
    config = DynamicHydroYearConfig(expected_trough_month=12)
    result = analyze_hydrological_state(frame, config=config)
    return frame, result.hydro_years.reset_index(drop=True)


def _spans(name: str, frame: pd.DataFrame, annual: pd.DataFrame):
    for index, row in annual.iterrows():
        left = _row_peak_boundary(row)
        right = _row_peak_boundary(annual.iloc[index + 1]) if index + 1 < len(annual) else None
        yield f"{name}_{int(row.hy_year)}", left, right


def main():
    rng = np.random.default_rng(20260909)
    rows_md: list[tuple[str, str]] = []  # (catchment_label_for_grouping, markdown)
    key = {}
    agree_n = 0
    disagree_n = 0
    chart_records: list[dict] = []

    sources = [(name, *_developed_frame_and_annual(name)) for name in DEVELOPED_CATCHMENTS]
    sources.append(("kakadu_national_park", *_kakadu_frame_and_annual()))

    for name, frame, annual in sources:
        for span_id, left, right in _spans(name, frame, annual):
            if left.selected is None or right is None or right.selected is None:
                continue
            existing = refine_trough_span(frame, left_peak=left, right_peak=right, policy=TROUGH_REFINEMENT_POLICY)
            candidate = refine_trough_span_direct_profile_with_sensitivity(
                frame, left_peak=left, right_peak=right, policy=TROUGH_REFINEMENT_POLICY,
                delta_pp=DELTA_PP, scale_mode="combined",
            )
            existing_applied = existing.status in {"confirmed", "provisional"} and existing.boundary is not None
            candidate_applied = candidate.status in {"confirmed", "provisional"} and candidate.boundary is not None
            if not existing_applied and not candidate_applied:
                continue  # both abstain: nothing to compare or review

            if existing_applied and candidate_applied and existing.boundary == candidate.boundary:
                agree_n += 1
                continue  # identical dates: no adjudication needed, skip from the review file

            disagree_n += 1
            span = frame.loc[left.selected:right.selected, "extent_pct"]
            values_text = ", ".join(f"{d:%Y-%m}={v:.3f}" for d, v in span.items())

            outcomes = [("existing", existing), ("direct_profile_combined", candidate)]
            order = list(rng.permutation(2))
            labelled = [outcomes[i] for i in order]
            key[span_id] = {"A": labelled[0][0], "B": labelled[1][0]}

            def fmt(result_obj):
                date = result_obj.boundary.strftime("%Y-%m") if result_obj.boundary is not None else "—"
                support = ", ".join(d.strftime("%Y-%m") for d in result_obj.boundary_candidates) or "—"
                return date, support, result_obj.status, result_obj.reason

            a_date, a_support, a_status, a_reason = fmt(labelled[0][1])
            b_date, b_support, b_status, b_reason = fmt(labelled[1][1])

            def fmt_chart(result_obj):
                return {
                    "date": result_obj.boundary.strftime("%Y-%m-%d") if result_obj.boundary is not None else None,
                    "support": [d.strftime("%Y-%m-%d") for d in result_obj.boundary_candidates],
                    "status": result_obj.status,
                    "reason": result_obj.reason,
                }

            chart_records.append({
                "span_id": span_id,
                "left_peak": left.selected.strftime("%Y-%m-%d"),
                "right_peak": right.selected.strftime("%Y-%m-%d"),
                "dates": [d.strftime("%Y-%m-%d") for d in span.index],
                "values": [round(float(v), 4) for v in span.to_numpy()],
                "A": fmt_chart(labelled[0][1]),
                "B": fmt_chart(labelled[1][1]),
            })

            rows_md.append((
                name,
                f"### {span_id}  (peak {left.selected:%Y-%m} to peak {right.selected:%Y-%m})\n\n"
                f"Monthly extent_pct: {values_text}\n\n"
                f"| | final low-state month | support set | status | reason |\n"
                f"| --- | --- | --- | --- | --- |\n"
                f"| **Algorithm A** | {a_date} | {a_support} | {a_status} | {a_reason} |\n"
                f"| **Algorithm B** | {b_date} | {b_support} | {b_status} | {b_reason} |\n",
            ))

    (HERE / "blind_check_all_key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    (HERE / "blind_check_all_chart_data.json").write_text(
        json.dumps(chart_records, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "blind_check_all_review.md").write_text(
        "# Real-catchment spot check: where the candidate and baseline disagree\n\n"
        f"{agree_n} cycles where both algorithms produced the identical date are "
        "omitted below (nothing to adjudicate). This file lists only the "
        f"{disagree_n} cycles where they disagree (one applied and the other "
        "abstained, or they chose different months), across the 5 development "
        "catchments plus Kakadu National Park (real DEA data, never inspected "
        "for this endpoint-refinement work). Catchment identity is kept in the "
        "span id -- if that's a source of bias for your review, ignore the "
        "prefix and read the values fresh. Decode key in "
        "`blind_check_all_key.json`.\n\n---\n\n"
        + "\n---\n\n".join(md for _name, md in rows_md),
        encoding="utf-8",
    )
    print(f"agree: {agree_n}, disagree: {disagree_n} (written to blind_check_all_review.md)")


if __name__ == "__main__":
    main()
