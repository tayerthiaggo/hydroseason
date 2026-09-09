"""Verify frozen development provenance, stored scores and baseline results."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
sys.path.insert(0, str(OUT))

from evaluate_endpoint import score_records  # noqa: E402

config = json.loads((OUT / "endpoint-experiment-config.json").read_text(encoding="utf-8"))
for path, digest in config["source_sha256"].items():
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
hashes = json.loads((OUT / "endpoint-output-manifest.json").read_text(encoding="utf-8"))
for path, digest in hashes.items():
    assert hashlib.sha256((OUT / path).read_bytes()).hexdigest() == digest, path
records = json.loads((OUT / "endpoint-synthetic-records.json").read_text(encoding="utf-8"))
assert len(records) == 2688
summary = pd.read_csv(OUT / "endpoint-synthetic-summary.csv")
for candidate in config["candidates"]:
    subset = [row for row in records if row["candidate"] == candidate]
    assert len(subset) == 384
    calculated = score_records(subset)
    stored = summary[(summary.candidate == candidate) & (summary.family == "all")].iloc[0]
    for field, value in calculated.items():
        assert value is None and pd.isna(stored[field]) or value is not None and np.isclose(value, stored[field]), (candidate, field)
real = pd.read_csv(OUT / "endpoint-real-development.csv").fillna("")
assert len(real) == 150
assert not real.duplicated(["catchment", "hy_year", "candidate"]).any()
for catchment, group in real[real.candidate == "existing"].groupby("catchment"):
    published = pd.read_csv(ROOT / "case_studies/results/final-review-2026-09-08/after/refinement" / catchment / "full_hydro_years.csv").fillna("").set_index("hy_year")
    for row in group.itertuples():
        expected = published.loc[row.hy_year]
        assert row.status == expected.trough_refinement_status
        assert row.reason == expected.trough_refinement_reason
        assert np.isclose(row.local_scale_pp, expected.trough_local_scale_pp, atol=1e-12, rtol=0)
print("PASS: frozen source/output hashes, 2688 synthetic results, all-candidate scores, 150 real results, 30 published baseline checks")
