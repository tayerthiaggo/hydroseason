"""Exploratory scale sensitivity; never selects or promotes a policy.

Run from the repository root with .venv/Scripts/python.exe and this file path.
Published peaks are fixed. These are component challenger results, not accepted
HY boundaries: atomic adjacent-cycle acceptance is deliberately not rerun.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from hydroseason._dynamic_year import _row_peak_boundary  # noqa: E402
from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason._trough_refinement import refine_trough_span  # noqa: E402
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY  # noqa: E402

OUT = Path(__file__).resolve().parent
YEARS = {2005, 2008, 2011, 2012, 2014, 2016, 2018, 2019, 2020}
BUNDLE = ROOT / "case_studies/results/final-review-2026-09-08/after/refinement"


def main() -> None:
    rows = []
    sources = {}
    for catchment in ("daly_river_nt", "fitzroy_river_wa"):
        raw_path = ROOT / f"case_studies/data/extent/{catchment}_30m.csv"
        annual_path = BUNDLE / catchment / "full_hydro_years.csv"
        for path in (raw_path, annual_path):
            sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        prepared = prepare_monthly_extent(pd.read_csv(raw_path))
        annual = pd.read_csv(annual_path)
        # Include the user's Daly years and all published Fitzroy cycles.
        for position, row in annual.iterrows():
            if catchment == "daly_river_nt" and int(row.hy_year) not in YEARS:
                continue
            left = _row_peak_boundary(row)
            right = _row_peak_boundary(annual.iloc[position + 1]) if position + 1 < len(annual) else None
            floor = float(row.detectability_floor_pp)
            assert pd.notna(floor) and floor >= 0
            for name, injected_floor in (("existing", 0.0), ("record_floor_sensitivity_only", floor)):
                result = refine_trough_span(
                    prepared, left_peak=left, right_peak=right,
                    policy=TROUGH_REFINEMENT_POLICY,
                    measurement_tolerance_pp=injected_floor,
                )
                rows.append({
                    "catchment": catchment, "hy_year": int(row.hy_year),
                    "scenario": name, "injected_floor_pp": injected_floor,
                    "published_boundary": row.trough_month,
                    "published_refinement_reason": row.trough_refinement_reason,
                    **asdict(result),
                })
                # Preserve partial progress if a later case fails.
                pd.DataFrame(rows).to_csv(OUT / "scale-sensitivity.csv", index=False)
            print(f"{catchment} {int(row.hy_year)} complete", flush=True)
    source_paths = sorted((ROOT / "hydroseason").glob("*.py")) + [Path(__file__).resolve()]
    for path in source_paths:
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "purpose": "Exploratory component scale sensitivity; no policy selection or HY acceptance",
        "policy": asdict(TROUGH_REFINEMENT_POLICY),
        "max_invalid_pct": 20.0, "quality_policy": "flag",
        "sources_sha256": sources, "records": len(rows),
        "output_sha256": hashlib.sha256((OUT / "scale-sensitivity.csv").read_bytes()).hexdigest(),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
