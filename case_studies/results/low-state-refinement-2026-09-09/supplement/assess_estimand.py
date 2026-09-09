"""Separate latent plateau-end error from a declared low-state functional.

This is a supplemental development analysis, written after the first experiment
was inspected. It neither overwrites that experiment nor counts as held-out
validation. The target uses the noise sigma known to the generator, never an
estimated scale or a model prediction. The fixed margin is one sigma for every
candidate; candidate-specific margins would silently change the target.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OUT))

from evaluate_endpoint import score_records  # noqa: E402


def main():
    config = json.loads((OUT / "endpoint-experiment-config.json").read_text(encoding="utf-8"))
    records = json.loads((OUT / "endpoint-synthetic-records.json").read_text(encoding="utf-8"))
    for row in records:
        row["latent_truth_index"] = row["truth_index"]
        if row["truth_index"] is not None:
            latent = np.asarray(config["families"][row["family"]][0])
            ceiling = float(latent.min()) + row["sigma_pp"]
            indexes = np.flatnonzero(latent <= ceiling + 1e-14)
            row["truth_index"] = int(indexes[-1])
    summaries = []
    for candidate in config["candidates"]:
        for family in ("all", *config["families"]):
            subset = [row for row in records if row["candidate"] == candidate and (family == "all" or row["family"] == family)]
            summaries.append({"candidate": candidate, "family": family, **score_records(subset)})
    pd.DataFrame(summaries).to_csv(OUT / "endpoint-equivalence-target-summary.csv", index=False)
    print(pd.DataFrame(summaries).query("family == 'all'")[[
        "candidate", "truth_support_coverage", "p90_error_months", "early_n", "late_n",
    ]].to_string(index=False))


if __name__ == "__main__":
    main()
