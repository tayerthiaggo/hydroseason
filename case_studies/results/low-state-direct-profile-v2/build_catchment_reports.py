"""Standard per-catchment HTML reports, shape_fit vs direct_profile_combined.

Unlike blind_review.html (a custom side-by-side review tool) or
five_catchment_bundle.csv (raw comparison data), these are the real
`generate_catchment_report` output -- the same report format every other
HydroSeason catchment gets -- run once per candidate so the new candidate's
dates/diagnostics can be inspected in their normal report context, not just
in an isolated diff table.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from hydroseason import analyze_catchment, generate_catchment_report  # noqa: E402
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY  # noqa: E402
from hydroseason._trough_refinement_direct_profile_defaults import (  # noqa: E402
    TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY,
)

DEVELOPMENT_CATCHMENTS = [
    "daly_river_nt", "fitzroy_river_wa", "gilbert_river_qld", "lachlan_river_nsw", "moonie_river_qld_nsw",
]
OUT_DIR = HERE / "html_reports"

CANDIDATES = {
    "shape_fit": TROUGH_REFINEMENT_POLICY,
    "direct_profile_combined": TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY,
}


def _sources():
    for name in DEVELOPMENT_CATCHMENTS:
        yield name, pd.read_csv(ROOT / f"case_studies/data/extent/{name}_30m.csv")
    # Real, previously untouched-by-this-work catchments used in the
    # informal spot check (findings.md) -- included here so their reports
    # exist in the normal format too, not just as blind-review rows.
    kakadu_raw = pd.read_csv(
        ROOT / "case_studies/results/stress-test-full/reports/kakadu-national-park/kakadu-national-park_monthly.csv"
    )
    yield "kakadu_national_park", kakadu_raw[["date", "extent_pct", "invalid_pct"]]
    roper = pd.read_csv(
        ROOT / "output/water_extent_csv/roper_river_nt_30m_water_extent.csv", index_col=0, parse_dates=True,
    )
    yield "roper_river_nt", roper[["extent_pct", "invalid_pct"]]


def main():
    for name, extent in _sources():
        date_col = "date" if "date" in extent.columns else None
        for label, policy in CANDIDATES.items():
            analysis = analyze_catchment(extent, date_col=date_col, trough_refinement_policy=policy)
            out_dir = OUT_DIR / label
            paths = generate_catchment_report(
                extent, out_dir, name=name, analysis=analysis,
                title=f"{name.replace('_', ' ').title()} -- {label}",
                subtitle=f"Trough-refinement candidate: {policy.version} (opt-in, not promoted)",
            )
            print(f"[{label}] {name} -> {paths.html}")


if __name__ == "__main__":
    main()
