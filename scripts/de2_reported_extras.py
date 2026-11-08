"""DE2 extras, reported only and written after the main run was scored.

Reads the frozen DE2 corpus and both libraries' runs through the frozen script's own
functions (scripts/known_truth_de2.py is imported, not edited) and the Fitzroy tile runs
of scripts/refinement_eol_explore.py, and writes
docs/handoff/2026-11-08-de2-end-of-low-extras.json:

- R2 labels on `ephemeral` seasons: how often the true end lies within a month of the
  label's interval, by arm and noise band, and where the truth sits against the boundary;
- the share of true ends hit among records each library routes to per-year detection;
- the Fitzroy tiles, v0.3.0 against the frozen candidate.

    PYTHONPATH=. python scripts/de2_reported_extras.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_de2 as de2  # noqa: E402
import refinement_eol_explore as explore  # noqa: E402

EXTRAS = de2.HANDOFF / "2026-11-08-de2-end-of-low-extras.json"


def main() -> None:
    records = de2._read_corpus()
    runs = {lib: de2.load_runs(de2.OUT / f"main_{lib}.jsonl") for lib in de2.LIBRARIES}
    rows = []
    for key, record in records.items():
        if record["shape"] != "ephemeral":
            continue
        for c in runs["candidate"][key].get("cycles", []):
            if c.get("trough_label_basis") != "end_of_dry_run":
                continue
            b = c["trough"]
            truth = de2._nearest_end(record, b)
            start, end = c["trough_interval_start"], c["trough_interval_end"]
            rows.append({"arm": record["arm"], "k": record["k"], "truth_minus_boundary": None if truth is None else truth - b,
                         "width": None if start is None or end is None else end - start,
                         "covered": truth is not None and start is not None and end is not None
                         and start - 1 <= truth <= end + 1})
    labels = pd.DataFrame(rows)
    r2 = {}
    for arm, g in labels.groupby("arm"):
        r2[arm] = {"labels": len(g), "covered": int(g["covered"].sum()), "covered_share": float(g["covered"].mean()),
                   "width_months": {str(int(k)): int(v) for k, v in Counter(g["width"].dropna()).most_common()},
                   "truth_minus_boundary": {str(int(k)): int(v) for k, v in
                                            Counter(g["truth_minus_boundary"].dropna()).most_common(10)},
                   "by_k": {f"{lo}_{hi}": {"labels": int(len(b)), "covered_share": float(b["covered"].mean()) if len(b) else None}
                            for lo, hi in de2.K_BANDS for b in [g[(g["k"] >= lo) & (g["k"] < hi)]]}}
    per_year = {}
    for lib in de2.LIBRARIES:
        for arm in ("S", "I"):
            ends = hits = 0
            for key, record in records.items():
                run = runs[lib][key]
                if record["arm"] != arm or record["shape"] != "ephemeral" or run["route"] != "per_year_detection":
                    continue
                s = de2.score(record, run)
                ends, hits = ends + s["ends"], hits + s["hits"]
            per_year[f"{lib}|{arm}"] = {"ends": ends, "hits": hits, "share": hits / ends if ends else None}
    tiles = explore.stage_compare()
    out = {"reported_only": True, "results_sha256_lf": de2.g1.sha256_lf(de2.RESULTS),
           "frozen_script_sha256_lf": de2.g1.sha256_lf(Path(de2.__file__)),
           "r2_ephemeral_labels": r2, "per_year_ephemeral_hits": per_year, "fitzroy_tiles": tiles}
    EXTRAS.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "fitzroy_tiles"}, indent=1, default=str))


if __name__ == "__main__":
    main()
