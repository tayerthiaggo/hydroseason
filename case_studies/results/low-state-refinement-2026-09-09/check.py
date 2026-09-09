"""Verify this exploratory bundle against its recorded sources and baseline."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
for relative, expected in manifest["sources_sha256"].items():
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
assert hashlib.sha256((OUT / "scale-sensitivity.csv").read_bytes()).hexdigest() == manifest["output_sha256"]
results = pd.read_csv(OUT / "scale-sensitivity.csv").fillna("")
assert len(results) == manifest["records"] == 60
assert not results.duplicated(["catchment", "hy_year", "scenario"]).any()
assert set(results.scenario) == {"existing", "record_floor_sensitivity_only"}
for catchment, group in results.groupby("catchment"):
    baseline = pd.read_csv(
        ROOT / "case_studies/results/final-review-2026-09-08/after/refinement"
        / catchment / "full_hydro_years.csv"
    ).fillna("").set_index("hy_year")
    existing = group[group.scenario == "existing"].set_index("hy_year")
    altered = group[group.scenario != "existing"].set_index("hy_year")
    assert existing.index.equals(altered.index)
    for year, row in existing.iterrows():
        expected = baseline.loc[year]
        assert row.status == expected.trough_refinement_status, (catchment, year, "status")
        assert row.reason == expected.trough_refinement_reason, (catchment, year, "reason")
        assert abs(float(row.local_scale_pp) - float(expected.trough_local_scale_pp)) < 1e-12, (catchment, year, "scale")
    changes = {
        field: int((existing[field] != altered[field]).sum())
        for field in ("boundary", "status", "reason", "low_state_start", "low_state_end", "boundary_candidates")
    }
    print(f"{catchment}: {len(existing)} baseline checks passed; changes={changes}")
print("PASS: source hashes, output hash, scenario pairs and 30 baseline status/reason/scale checks")
