"""Rescore the stored L1 and L2 known-truth runs under the hydroseason-v0.3.0 trough-label rule.

Step 5 of the 0.3.0 implementation checks (docs/handoff/2026-11-04-v0.3.0-proposal.md).
Reported, not used to decide. The stored runs of the current setting are read; each dated
trough label whose interval misses the boundary is widened to cover it and graded by width,
as `_reconcile_trough_labels` does in the library. Then the share of `point` troughs more
than a month from the truth is computed before and after, with L1's own scoring.

    python scripts/v030_rescore_known_truth.py

Writes docs/handoff/2026-11-04-v0.3.0-known-truth-rescore.json.
"""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_gates as g2  # noqa: E402
import known_truth_l2_r1 as l2  # noqa: E402
import known_truth_labels as l1  # noqa: E402

g1 = g2.g1
TARGET = g1.HANDOFF / "2026-11-04-v0.3.0-known-truth-rescore.json"
DATED = {"point", "interval", "broad"}


def graded(span: int) -> str:
    from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as gates

    if span <= gates.max_point_span_months:
        return "point"
    if span <= gates.max_boundary_interval_months:
        return "interval"
    if span <= gates.max_broad_interval_months:
        return "broad"
    return "unresolved"


def widen(runs: dict) -> tuple[dict, Counter]:
    out, moves = copy.deepcopy(runs), Counter()
    for run in out.values():
        for cycle in run["cycles"]:
            trough, start, end = cycle["trough"], cycle["start"], cycle["end"]
            if cycle["status"] not in DATED or None in (trough, start, end) or start <= trough <= end:
                continue
            new = graded(max(end, trough) - min(start, trough))
            moves[f"{cycle['status']}->{new}"] += 1
            cycle.update(status=new, start=min(start, trough), end=max(end, trough))
    return out, moves


def score(study: str, out_dir: Path, receipt: Path) -> dict:
    records = g2.read_corpus(out_dir / "corpus.jsonl.gz")
    if g2.corpus_digest(records) != json.loads(receipt.read_text(encoding="utf-8"))["corpus_sha256"]:
        raise SystemExit(f"{study} corpus does not match its receipt")
    meta = {r["key"]: {k: v for k, v in r.items() if k != "rows"} for r in records}
    before = g1.load_runs(out_dir / "main_current.jsonl")
    after, moves = widen(before)
    result: dict = {"runs_sha256": g1.sha256_file(out_dir / "main_current.jsonl"), "label_moves": dict(moves),
                    "arms": {}}
    for name, runs in (("before", before), ("after", after)):
        table = l1.cycle_table(runs, meta)
        for arm in ("S", "I"):
            sub = table[(table["arm"] == arm) & (table["kind"] == "seasonal")]
            entry = result["arms"].setdefault(arm, {})
            entry[name] = {"point": l1.point_safety(sub),
                           "labels": {s: int(((sub["status"] == s) & sub["has_trough"]).sum())
                                      for s in ("point", "interval", "broad", "unresolved")},
                           "dated_correct": l1.share(sub[sub["dated"]], "correct")}
    return result


def main() -> None:
    result = {
        "script_sha256_lf": g1.sha256_lf(Path(__file__)),
        "l1": score("L1", l1.OUT, l1.RECEIPT),
        "l2": score("L2", l2.OUT, l2.RECEIPT),
    }
    TARGET.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    for study in ("l1", "l2"):
        for arm, entry in result[study]["arms"].items():
            b, a = entry["before"]["point"], entry["after"]["point"]
            print(f"{study} {arm}: point miss {b['not_correct']}/{b['point_dates']} -> {a['not_correct']}/{a['point_dates']}")


if __name__ == "__main__":
    main()
