"""DE1 extras, reported only and written after the main run was scored.

Nothing here feeds a decision rule. It reads the frozen DE1 corpus and runs through the
frozen script's own functions (`scripts/known_truth_de1.py` is imported, not edited) and
answers four questions the results raised:

1. routing: how many records of each arm and shape reach per-year detection at all;
2. early ends: on `ephemeral` pairs the candidate still dates two or more months early,
   what kind of month ended the run (a true mid-dry pulse, the wet season, or a dry month
   above the tolerance, i.e. noise, a spike or, in arm I, the background);
3. overshoots: pairs whose candidate end lies at or after the peak it precedes;
4. rule 3 by shape: where the `point` ends that are not correct come from, for all
   pairs (as rule 3 pooled them) and for pairs whose boundary moved.

Run: PYTHONPATH=. python scripts/de1_reported_extras.py
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_de1 as de1  # noqa: E402

EXTRAS = de1.HANDOFF / "2026-11-05-de1-dry-run-end-extras.json"


def _frame(record: dict) -> pd.DataFrame:
    from hydroseason._state_input import prepare_monthly_extent

    return prepare_monthly_extent(de1._counts_frame(record["rows"]), max_invalid_pct=20.0, quality_policy="flag")


def _month_kind(month: int, truth: dict) -> str:
    if month in truth["pulses"]:
        return "mid_dry_pulse"
    if any(o <= month <= o + 3 for o in truth["onsets"]):
        return "wet_season"
    return "dry_month_above_tolerance"


def main() -> None:
    with gzip.open(de1.OUT / "corpus.jsonl.gz", "rt", encoding="utf-8") as handle:
        records = {r["key"]: r for r in (json.loads(line) for line in handle if line.strip())}
    runs = de1.load_runs(de1.OUT / "main.jsonl")

    routing = Counter((records[k]["arm"], records[k]["shape"], run.get("route")) for k, run in runs.items())

    early, overshoot, point_wrong, point_all = Counter(), Counter(), Counter(), Counter()
    moved_point_wrong, moved_point_all = Counter(), Counter()
    early_margin, overshoot_peak_unobserved = [], Counter()
    frames: dict[str, pd.DataFrame] = {}
    for key, run in runs.items():
        record = records[key]
        by_trough = {c["trough"]: c for c in run.get("cycles", []) if c.get("trough") is not None}
        for pair in de1.pairs(record, run):
            if not pair["peak_in_wet"]:
                continue
            arm, shape = pair["arm"], pair["shape"]
            if pair["end_status"] == "point":
                point_all[(arm, shape)] += 1
                point_wrong[(arm, shape)] += not pair["correct_candidate"]
                if pair["moved"]:
                    moved_point_all[(arm, shape)] += 1
                    moved_point_wrong[(arm, shape)] += not pair["correct_candidate"]
            if pair["e"] >= pair["p"]:
                overshoot[(arm, shape)] += 1
                frame = frames.setdefault(key, _frame(record))
                peak = next((m for m in frame.index if de1.midx(m) == pair["p"]), None)
                usable = peak is not None and frame.at[peak, "quality_state"] == "usable"
                overshoot_peak_unobserved[(arm, shape, "peak_usable" if usable else "peak_not_usable")] += 1
            if shape != "ephemeral" or pair["err_candidate"] > -2:
                continue
            owner = by_trough[pair["t"]]
            rewet = owner.get("rewet")
            if rewet is None:
                early[(arm, "no_rewet_month")] += 1
                continue
            kind = _month_kind(rewet, record["truth"])
            early[(arm, kind)] += 1
            if kind == "dry_month_above_tolerance" and owner.get("eps"):
                frame = frames.setdefault(key, _frame(record))
                month = next(m for m in frame.index if de1.midx(m) == rewet)
                early_margin.append({"arm": arm, "over_eps": (float(frame.at[month, "extent_pct"]) - owner["level"]) / owner["eps"]})

    margin = pd.DataFrame(early_margin)
    margins = {arm: {q: round(float(g["over_eps"].quantile(q)), 2) for q in (0.25, 0.5, 0.75)}
               for arm, g in margin.groupby("arm")} if len(margin) else {}

    def keyed(counter: Counter) -> dict:
        return {"|".join(map(str, k)): v for k, v in sorted(counter.items())}

    out = {
        "reported_only": True,
        "results_sha256_lf": de1.g1.sha256_lf(de1.RESULTS),
        "frozen_script_sha256_lf": de1.g1.sha256_lf(Path(de1.__file__)),
        "routing": keyed(routing),
        "ephemeral_early_ends_by_rewet_month": keyed(early),
        "ephemeral_early_dry_month_rise_in_eps_quantiles": margins,
        "overshoot_pairs": keyed(overshoot),
        "overshoot_pairs_by_peak_quality": keyed(overshoot_peak_unobserved),
        "point_ends_by_shape": keyed(point_all),
        "point_ends_not_correct_by_shape": keyed(point_wrong),
        "moved_point_ends_by_shape": keyed(moved_point_all),
        "moved_point_ends_not_correct_by_shape": keyed(moved_point_wrong),
    }
    EXTRAS.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
