"""Informal real-catchment spot check: Roper River NT, blinded for manual review.

Not the formal blinded-cohort protocol (scripts/build_trough_refinement_cohort.py) --
that needs a much larger sample, double review, and a Wilson-bound gate. This is
a single-catchment, single-reviewer sanity check per the plan's allowance for
"clearly labelled opt-in engineering evaluation" when full real-cohort evidence
isn't available (Step 5 exit criterion).

Writes two files:
  roper_blind_review.md   -- for the human reviewer: monthly values per cycle,
                              plus two unlabelled candidate dates/support sets.
  roper_blind_key.json    -- decode key (which label is which algorithm).
                              Do not open until after the review.
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

from hydroseason import DynamicHydroYearConfig, analyze_hydrological_state  # noqa: E402
from hydroseason._dynamic_year import _row_peak_boundary  # noqa: E402
from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason._trough_refinement import refine_trough_span  # noqa: E402
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY  # noqa: E402

from direct_profile import refine_trough_span_direct_profile  # noqa: E402

CSV = ROOT / "output/water_extent_csv/roper_river_nt_30m_water_extent.csv"
DELTA_PP = 0.4


def main():
    raw = pd.read_csv(CSV, index_col=0, parse_dates=True)
    frame = prepare_monthly_extent(raw)
    config = DynamicHydroYearConfig(expected_trough_month=11)
    result = analyze_hydrological_state(frame, config=config)
    annual = result.hydro_years.reset_index(drop=True)

    rng = np.random.default_rng(20260909)
    rows_md = []
    key = {}

    for index, row in annual.iterrows():
        left = _row_peak_boundary(row)
        right = _row_peak_boundary(annual.iloc[index + 1]) if index + 1 < len(annual) else None
        existing = refine_trough_span(frame, left_peak=left, right_peak=right, policy=TROUGH_REFINEMENT_POLICY)
        candidate = refine_trough_span_direct_profile(
            frame, left_peak=left, right_peak=right, policy=TROUGH_REFINEMENT_POLICY,
            delta_pp=DELTA_PP, scale_mode="combined",
        )
        if existing.status == "awaiting_next_peak" or left.selected is None or right is None or right.selected is None:
            continue

        span = frame.loc[left.selected:right.selected, "extent_pct"]
        values_text = ", ".join(f"{d:%Y-%m}={v:.3f}" for d, v in span.items())

        outcomes = [("existing", existing), ("direct_profile_combined", candidate)]
        order = list(rng.permutation(2))
        labelled = [outcomes[i] for i in order]
        span_id = f"span_{int(row.hy_year)}"
        key[span_id] = {"A": labelled[0][0], "B": labelled[1][0]}

        def fmt(result_obj):
            date = result_obj.boundary.strftime("%Y-%m") if result_obj.boundary is not None else "—"
            support = ", ".join(d.strftime("%Y-%m") for d in result_obj.boundary_candidates) or "—"
            return date, support, result_obj.status, result_obj.reason

        a_date, a_support, a_status, a_reason = fmt(labelled[0][1])
        b_date, b_support, b_status, b_reason = fmt(labelled[1][1])

        rows_md.append(
            f"### {span_id}  (peak {left.selected:%Y-%m} to peak {right.selected:%Y-%m})\n\n"
            f"Monthly extent_pct: {values_text}\n\n"
            f"| | final low-state month | support set | status | reason |\n"
            f"| --- | --- | --- | --- | --- |\n"
            f"| **Algorithm A** | {a_date} | {a_support} | {a_status} | {a_reason} |\n"
            f"| **Algorithm B** | {b_date} | {b_support} | {b_status} | {b_reason} |\n"
        )

    (HERE / "roper_blind_key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    (HERE / "roper_blind_review.md").write_text(
        "# Roper River NT: blinded low-state-endpoint spot check\n\n"
        "For each annual cycle: the observed monthly extent_pct series, then "
        "each algorithm's proposed final low-state month (the operational "
        "hydrological-year boundary), its support set (timing uncertainty), "
        "status, and reason. A and B are consistently which-is-which within "
        "this file but not revealed -- decode key is in `roper_blind_key.json`, "
        "which is deliberately separate so it isn't visible while reading.\n\n"
        "Read each cycle and note which column (A or B) looks like the more "
        "defensible final low-state month given the observed values -- or if "
        "both look wrong, or equally reasonable.\n\n---\n\n"
        + "\n---\n\n".join(rows_md),
        encoding="utf-8",
    )
    print(f"{len(rows_md)} spans written to roper_blind_review.md")


if __name__ == "__main__":
    main()
