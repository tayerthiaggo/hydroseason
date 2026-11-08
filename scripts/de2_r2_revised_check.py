"""DE2 follow-up, post hoc and reported: R1 with the revised R2 label, on DE2's frozen records.

After DE2 the lead chose (2026-11-08) to revise R2 before the implementation checks: DE2's
R2 labelled the end of a dry low as a one-month `interval` and the true end lay within a
month of it in only 28% (arm S) and 61% (arm I) of ephemeral cases. Revised R2: the label
runs from the run end to the month before the next peak, graded by width (`interval`,
`broad`, never `point`; no relabel if wider). R1 is unchanged.

This check is not a pre-registered test. It reruns DE2's frozen corpus under the revised
candidate, scores it with DE2's frozen functions (imported, not edited) against DE2's
current-library runs, and reports DE2's four rules and the R2 label accuracy.

    PYTHONPATH=. python scripts/de2_r2_revised_check.py run
    PYTHONPATH=. python scripts/de2_r2_revised_check.py score
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_de2 as de2  # noqa: E402
import known_truth_de2_evaluate  # noqa: E402,F401  (integer-seed fix for the noise bands)

RESULT = de2.HANDOFF / "2026-11-08-de2-r2-revised-check.json"
SINK = de2.OUT / "main_candidate_r2rev.jsonl"


def stage_run(workers: int) -> None:
    fingerprint = de2._library_fingerprint()
    frozen = json.loads(de2.RECEIPT.read_text(encoding="utf-8"))["candidate_fingerprint"]
    if fingerprint in (de2.CURRENT_FINGERPRINT, frozen):
        raise SystemExit("run under the revised candidate")
    de2.run_records(list(de2._read_corpus().values()), SINK, workers)


def stage_score() -> None:
    records = de2._read_corpus()
    current = de2.load_runs(de2.OUT / "main_current.jsonl")
    revised = de2.load_runs(SINK)
    rows, labels = [], []
    for key, record in records.items():
        a, b = de2.score(record, current[key]), de2.score(record, revised[key])
        rows.append({"arm": record["arm"], "shape": record["shape"], "k": record.get("k"), "ends": a["ends"],
                     "hits_current": a["hits"], "hits_candidate": b["hits"],
                     "per_year_current": a["per_year"], "per_year_candidate": b["per_year"],
                     "cycles_current": a["cycles"], "cycles_candidate": b["cycles"],
                     "dated_current": a["dated"], "dated_candidate": b["dated"]})
        if record["shape"] == "ephemeral":
            for c in revised[key].get("cycles", []):
                if c.get("trough_label_basis") != "end_of_dry_run":
                    continue
                truth = de2._nearest_end(record, c["trough"])
                start, end = c["trough_interval_start"], c["trough_interval_end"]
                labels.append({"arm": record["arm"], "status": c["trough_timing_status"],
                               "covered": truth is not None and start - 1 <= truth <= end + 1})
    table, labels = pd.DataFrame(rows), pd.DataFrame(labels)
    seeds = {("S", "ephemeral"): 101, ("I", "ephemeral"): 102, ("S", "sine"): 201, ("I", "sine"): 202,
             ("S", "pulse"): 301, ("I", "pulse"): 302}
    rules, reported = {}, {}
    for arm in ("S", "I"):
        a = table[table["arm"] == arm]
        out = {}
        for name, shape, bound in (("rule_1", "ephemeral", 0.0), ("rule_2", "sine", -0.05), ("rule_3", "pulse", -0.05)):
            r = de2.bootstrap_difference(a[a["shape"] == shape], seeds[(arm, shape)])
            ok = r.get("evaluable") and (r["ci95"][0] > bound if name == "rule_1" else r["ci95"][0] >= bound)
            out[name] = {**r, "outcome": "holds" if ok else "fails"}
        rules[arm] = out
        lab = labels[labels["arm"] == arm]
        reported[arm] = {
            "r2_labels": int(len(lab)), "r2_covered": int(lab["covered"].sum()),
            "r2_covered_share": float(lab["covered"].mean()) if len(lab) else None,
            "r2_status": dict(Counter(lab["status"])),
            "routing": {shape: [int(g["per_year_current"].sum()), int(g["per_year_candidate"].sum()), len(g)]
                        for shape, g in a.groupby("shape")},
            "dated_share": {shape: [float(g["dated_current"].sum() / max(g["cycles_current"].sum(), 1)),
                                    float(g["dated_candidate"].sum() / max(g["cycles_candidate"].sum(), 1))]
                            for shape, g in a.groupby("shape")},
        }
    gates = de2._reviewed_gates()
    result = {"post_hoc": True, "fingerprint": sorted({r.get("fingerprint") for r in revised.values()}),
              "errors": sorted(k for k, r in revised.items() if r.get("error")),
              "frozen_script_sha256_lf": de2.g1.sha256_lf(Path(de2.__file__)),
              "rules": rules, "reviewed_gates": gates, "reported": reported}
    RESULT.write_text(json.dumps(de2.g1.clean(result), indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(de2.g1.clean(result), indent=1, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["run", "score"])
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    stage_run(args.workers) if args.stage == "run" else stage_score()


if __name__ == "__main__":
    main()
