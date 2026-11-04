"""Simulated effect of the proposed trough-label consistency rule on stored real-record runs.

Exploratory, for the hydroseason-v0.3.0 proposal (docs/handoff/2026-11-04-v0.3.0-proposal.md).
Not a test and not pre-registered. Reads the runs of scripts/real_record_impact.py and writes
docs/handoff/2026-11-04-v0.3.0-label-fix-impact.json.

The rule simulated: when a `point` trough label's one-month interval does not contain the
reported boundary month (`trough_month`), widen the interval to span both months and give it
the status the existing width rule gives that span (`interval` up to 2 months apart, `broad`
up to 5, otherwise `unresolved`). It is applied after boundary detection, so no boundary,
date or peak moves; only the trough label, the aggregate `timing_status` and whatever reads
them change.

    python scripts/v030_label_fix_impact.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_calibration as g1  # noqa: E402
import real_record_impact as rri  # noqa: E402

from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS as GATES  # noqa: E402

TARGET = g1.HANDOFF / "2026-11-04-v0.3.0-label-fix-impact.json"
INFORMATIVE = {"point", "interval", "broad"}
RANK = {"unresolved": 0, "broad": 1, "interval": 2, "point": 3}


def widened_status(span: int) -> str:
    if span <= GATES.max_point_span_months:
        return "point"
    if span <= GATES.max_boundary_interval_months:
        return "interval"
    if span <= GATES.max_broad_interval_months:
        return "broad"
    return "unresolved"


def _mismatched_month(cycle: dict):
    if cycle["trough_timing_status"] != "point" or cycle["trough_month"] is None:
        return None
    start, end, boundary = cycle["trough_interval_start"], cycle["trough_interval_end"], cycle["trough_month"]
    if start == boundary and end == boundary:
        return None
    return start if start != boundary else end


def _eligible(conditions: dict, rule: str, year) -> bool:
    entry = conditions[rule].get(str(year)) or conditions[rule].get(year)
    return bool(entry and entry["eligible"])


def simulate(runs: dict) -> dict:
    out = {}
    for source in ("g1", "su"):
        c = Counter()
        new_status = Counter()
        for key, run in runs.items():
            if not key.startswith(source + "|") or run["route"] != "per_year_detection":
                continue
            c["records"] += 1
            conditions = run["conditions"]
            n_peak = sum(x["peak_timing_status"] in INFORMATIVE for x in run["cycles"])
            n_trough_before = sum(x["trough_timing_status"] in INFORMATIVE for x in run["cycles"])
            n_trough_after = n_trough_before
            lost = {"E0": 0, "E1": 0}
            for cycle in run["cycles"]:
                c["point_troughs"] += cycle["trough_timing_status"] == "point"
                month = _mismatched_month(cycle)
                if month is None:
                    continue
                c["changed_troughs"] += 1
                status = widened_status(abs(cycle["trough_month"] - month))
                new_status[status] += 1
                n_trough_after -= status not in INFORMATIVE
                before = min((cycle["peak_timing_status"], "point"), key=RANK.get)
                after = min((cycle["peak_timing_status"], status), key=RANK.get)
                c["aggregate_changed"] += before != after
                if conditions:
                    # E0 needs an aggregate `point`; E1 needs any dated aggregate status.
                    lost["E0"] += _eligible(conditions, "E0", cycle["hy_year"])
                    lost["E1"] += _eligible(conditions, "E1", cycle["hy_year"]) and after == "unresolved"
            c["records_losing_an_informative_trough"] += n_trough_after < n_trough_before
            minimum = GATES.min_informative_years
            c["records_rerouted"] += min(n_peak, n_trough_before) >= minimum > min(n_peak, n_trough_after)
            for rule in ("E0", "E1"):
                if not conditions:
                    continue
                eligible = sum(bool(v["eligible"]) for v in conditions[rule].values())
                c[f"{rule}_eligible_cycles"] += eligible
                c[f"{rule}_eligible_cycles_lost"] += lost[rule]
                has_baseline = eligible >= 5
                c[f"{rule}_units_with_baseline"] += has_baseline
                c[f"{rule}_units_losing_baseline"] += has_baseline and eligible - lost[rule] < 5
        out[source] = {**dict(c), "new_trough_status": dict(new_status)}
    return out


def main() -> None:
    result = {"results_sha256_lf": g1.sha256_lf(rri.RESULTS), "script_sha256_lf": g1.sha256_lf(Path(__file__)),
              "gates": {"max_point_span_months": GATES.max_point_span_months,
                        "max_boundary_interval_months": GATES.max_boundary_interval_months,
                        "max_broad_interval_months": GATES.max_broad_interval_months,
                        "min_informative_years": GATES.min_informative_years},
              "simulation": simulate(rri.load_runs())}
    TARGET.write_text(json.dumps(g1.clean(result), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(g1.clean(result), indent=1))


if __name__ == "__main__":
    main()
