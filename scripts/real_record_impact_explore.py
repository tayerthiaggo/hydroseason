"""Exploratory (post hoc) checks for the real-record impact measurement.

Not part of docs/handoff/2026-11-03-real-record-impact-plan.md. Reads the stored
runs of scripts/real_record_impact.py and writes
docs/handoff/2026-11-03-real-record-impact-exploratory.json.

1. Chance-corrected agreement (Cohen's kappa) between pixel halves, by group,
   with the plan's window bootstrap (2,000 draws, seed 0).
2. Why a `point` trough label's month differs from the reported boundary month,
   and how far apart they are.

    python scripts/real_record_impact_explore.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402
import real_record_impact as rri  # noqa: E402

TARGET = g1.HANDOFF / "2026-11-03-real-record-impact-exploratory.json"


def _group_kappa(frame: pd.DataFrame, rule: str, kind: str) -> float | None:
    return rri._kappa(frame[f"{rule}|{kind}|A"].to_numpy(), frame[f"{rule}|{kind}|B"].to_numpy())


def kappa_by_group(pairs: pd.DataFrame) -> dict:
    windows = sorted(pairs["window"].unique())
    rng = np.random.default_rng(rri.SEED)
    draws = [rng.choice(len(windows), size=len(windows), replace=True) for _ in range(rri.BOOT)]
    by_window = {w: g for w, g in pairs.groupby("window")}
    out = {}
    for kind in rri.KINDS:
        e0, e1 = rri._labelled(pairs, "E0", kind), rri._labelled(pairs, "E1", kind)
        point = pairs["point_both"]
        groups = {"E0": ("E0", e0), "E1_added": ("E1", e1 & ~e0),
                  "E1_point_both": ("E1", e1 & point), "E1_not_point": ("E1", e1 & ~point),
                  "E0_point_both": ("E0", e0 & point), "E0_not_point": ("E0", e0 & ~point)}
        entry = {}
        for name, (rule, mask) in groups.items():
            sub = pairs[mask]
            entry[name] = {"pairs": len(sub), "windows": int(sub["window"].nunique()),
                           "kappa": _group_kappa(sub, rule, kind),
                           "label_shares_half_a": sub[f"{rule}|{kind}|A"].value_counts(normalize=True).to_dict()}
        for name, base, other in (("added_minus_e0", "E0", "E1_added"),
                                  ("not_point_minus_point", "E1_point_both", "E1_not_point")):
            diffs = []
            for idx in draws:
                chosen = pd.concat([by_window[windows[i]] for i in idx])
                values = []
                for group in (base, other):
                    rule, mask = groups[group]
                    sub = chosen[mask.reindex(chosen.index).to_numpy()]
                    values.append(_group_kappa(sub, rule, kind) if len(sub) else None)
                if None not in values:
                    diffs.append(values[1] - values[0])
            entry[f"kappa_{name}"] = {
                "difference": entry[other]["kappa"] - entry[base]["kappa"],
                "ci95": [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))],
                "valid_draws": len(diffs)}
        out[kind] = entry
    e0_windows = pairs[rri._labelled(pairs, "E0", "recharge")].groupby("window").size()
    out["e0_pairs_by_window"] = {"windows": len(e0_windows), "pairs": int(e0_windows.sum()),
                                 "largest_two": int(e0_windows.nlargest(2).sum())}
    return out


def mismatch_causes(runs: dict) -> dict:
    """Classify each differing `point` trough by what the record says about the label's month."""
    causes: dict[str, Counter] = {"g1": Counter(), "su": Counter()}
    gaps: dict[str, Counter] = {"g1": Counter(), "su": Counter()}
    for key, run in runs.items():
        if run["route"] != "per_year_detection":
            continue
        source = key.split("|")[0]
        for cycle in run["cycles"]:
            if cycle["trough_timing_status"] != "point" or cycle["trough_month"] is None:
                continue
            start, end, boundary = cycle["trough_interval_start"], cycle["trough_interval_end"], cycle["trough_month"]
            if start == boundary and end == boundary:
                continue
            month = start if start != boundary else end
            if month == cycle["raw_trough_month"] and cycle["selection_status"] == "quality_adjusted":
                cause = "cloud_screened_raw_minimum"
            elif cycle.get("outside_window_lower"):
                cause = "lower_month_outside_search_window"
            else:
                cause = "other"
            causes[source][cause] += 1
            gaps[source][boundary - month] += 1
    out = {}
    for source in causes:
        gap = gaps[source]
        total = sum(gap.values())
        ordered = sorted(gap.elements())
        out[source] = {"differs": total, "causes": dict(causes[source]),
                       "gap_months": {str(k): v for k, v in sorted(gap.items())},
                       "gap_one_month": gap.get(1, 0), "gap_median": float(np.median(ordered)) if ordered else None,
                       "gap_max": max(ordered) if ordered else None}
    return out


def main() -> None:
    runs = rri.load_runs()
    result = {"results_sha256_lf": g1.sha256_lf(rri.RESULTS),
              "script_sha256_lf": g1.sha256_lf(Path(__file__)),
              "kappa": kappa_by_group(rri.matched_pairs(runs)),
              "mismatch_causes": mismatch_causes(runs)}
    TARGET.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(g1.clean(result), indent=1))


if __name__ == "__main__":
    main()
