"""Read-only reproductions for codex-final.md; run from the repository root."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import (
    PeakBoundary, TroughRefinementPolicy, refine_trough_span,
)
from scripts import evaluate_final_pipeline as evaluator


def main():
    policy = TroughRefinementPolicy(1.345, 0.05, 1.5)
    index = pd.date_range("2020-01-01", periods=9, freq="MS")

    def peak(date):
        return PeakBoundary(date, (date,), "point", "normal")

    print("C1: observed-count input, frozen policy, default measurement tolerance")
    for missing in (False, True):
        water = np.array([90, 60, 30, 10, 10, 11, 10, 30, 80])
        valid = np.full(9, 100)
        if missing:
            valid[4] = 0
        raw = pd.DataFrame({
            "extent_pct": water,
            "n_water": np.where(valid > 0, water, 0),
            "n_valid": valid,
            "n_invalid": 100 - valid,
            "n_aoi": 100,
        }, index=index)
        result = refine_trough_span(
            prepare_monthly_extent(raw),
            left_peak=peak(index[0]), right_peak=peak(index[-1]), policy=policy,
        )
        print({
            "missing_may": missing, "status": result.status,
            "reason": result.reason, "boundary": str(result.boundary),
            "support": [str(date.date()) for date in result.boundary_candidates],
            "scale_pp": result.local_scale_pp,
        })

    print("C2: real recovery changes omitted from cycle diff")
    bundle = Path(__file__).resolve().parents[1]
    for catchment in ("daly_river_nt", "fitzroy_river_wa", "gilbert_river_qld"):
        before = pd.read_csv(bundle / "before/refinement" / catchment / "full_hydro_years.csv")
        after = pd.read_csv(bundle / "after/refinement" / catchment / "full_hydro_years.csv")
        diff, _ = evaluator.compare_cycle_tables(before, after)
        emitted = set(diff.hy_year)
        before = before.set_index("hy_year")
        after = after.set_index("hy_year")
        for year in before.index:
            left = before.at[year, "recovery_start_month"]
            right = after.at[year, "recovery_start_month"]
            equal = (pd.isna(left) and pd.isna(right)) or left == right
            if not equal and year not in emitted:
                print(catchment, year, "recovery:", left, "->", right)

    print("C3: in-memory scoring mutation is invisible to pipeline fingerprint")
    original = evaluator._GEOMETRY_MAX_MATCH_MONTHS
    fingerprint = evaluator._pipeline_manifest_hash(policy)
    print("before:", evaluator._split_wrong_cycle([(2020, 1.0)]))
    try:
        evaluator._GEOMETRY_MAX_MATCH_MONTHS = 0
        print("after:", evaluator._split_wrong_cycle([(2020, 1.0)]))
        print("same fingerprint:", evaluator._pipeline_manifest_hash(policy) == fingerprint)
    finally:
        evaluator._GEOMETRY_MAX_MATCH_MONTHS = original


if __name__ == "__main__":
    main()
