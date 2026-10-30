"""Run the released regime assessment on frozen external windows.

Step 2 of docs/provisional-trough-verdict-2026-10-30.md. Reads every ``*.csv``
in ``--fixtures`` as one window. Required columns: ``date`` (any month stamp
pandas can parse), ``extent_pct``, ``invalid_pct``. Optional: ``n_water``,
``n_valid``, ``n_invalid``, ``n_aoi``. An optional ``--rank-troughs`` CSV with
columns ``window_id,rank_trough_month`` supplies the external rank trough for
comparison; it is not treated as truth.

``RULE`` is the illustrative decision rule from the verdict, written before any
real window was read. It is not a method threshold. Do not change it after
seeing data; if it must change, say so in the results document.

Example:

    .venv/Scripts/python.exe scripts/frozen_window_recurrence.py \
        --fixtures dev/fixtures/frozen_windows \
        --rank-troughs dev/fixtures/frozen_windows_rank_troughs.csv \
        --out dev/reports/2026-10-30-frozen-windows.csv \
        --summary dev/reports/2026-10-30-frozen-windows.md
"""

from __future__ import annotations

import argparse
import csv
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hydroseason import (  # noqa: E402
    assess_water_regime,
    classify_seasonal_pattern,
    load_extent_csv,
)

RULE = {
    "alpha": 0.05,
    "majority_fraction": 2.0 / 3.0,
    "minority_fraction": 1.0 / 3.0,
    "max_median_set_width_months": 3.0,
    "max_circular_distance_months": 1,
}
COLUMNS = [
    "window_id",
    "n_months",
    "n_usable_years",
    "n_detectable_years",
    "pixel_support_status",
    "regime",
    "status",
    "reason",
    "peak_p",
    "trough_p",
    "trough_dominant_month",
    "median_trough_set_width",
    "median_peak_set_width",
    "harmonic_pattern",
    "harmonic_order",
    "harmonic_trough",
    "rank_trough_month",
    "circular_distance_to_rank",
    "trough_recurs",
    "compact_and_agrees",
]


def circular_distance(a, b):
    """Shortest distance between two calendar months on the 12-month circle."""
    delta = abs(int(a) - int(b)) % 12
    return min(delta, 12 - delta)


def assess_window(window_id, frame, *, rank_trough=None, n_bootstrap=200):
    assessment = assess_water_regime(frame, n_bootstrap=n_bootstrap)
    test = assessment.seasonality_test
    result = classify_seasonal_pattern(frame)
    widths = [len(months) for months in test.trough_month_sets.values()]
    median_width = float(np.median(widths)) if widths else None
    peak_widths = [len(months) for months in test.peak_month_sets.values()]
    median_peak_width = float(np.median(peak_widths)) if peak_widths else None
    trough_p = test.trough.uniformity_p
    dominant = test.trough.dominant_month
    recurs = test.status == "ok" and trough_p is not None and trough_p < RULE["alpha"]
    distance = None
    if rank_trough is not None and dominant is not None:
        distance = circular_distance(dominant, rank_trough)
    compact = (
        recurs
        and median_width is not None
        and median_width <= RULE["max_median_set_width_months"]
        and (distance is None or distance <= RULE["max_circular_distance_months"])
    )
    return {
        "window_id": window_id,
        "n_months": int(len(frame)),
        "n_usable_years": assessment.n_usable_years,
        "n_detectable_years": test.n_detectable_years,
        "pixel_support_status": assessment.pixel_support_status,
        "regime": assessment.regime,
        "status": test.status,
        "reason": test.reason,
        "peak_p": test.peak.uniformity_p,
        "trough_p": trough_p,
        "trough_dominant_month": dominant,
        "median_trough_set_width": median_width,
        "median_peak_set_width": median_peak_width,
        "harmonic_pattern": result.pattern,
        "harmonic_order": result.selected_harmonic_order,
        "harmonic_trough": result.expected_trough_month,
        "rank_trough_month": rank_trough,
        "circular_distance_to_rank": distance,
        "trough_recurs": bool(recurs),
        "compact_and_agrees": bool(compact),
    }


def decide(rows):
    """Apply ``RULE`` to the per-window rows. Windows without status ok are excluded."""
    ok = [row for row in rows if row["status"] == "ok"]
    n_ok = len(ok)
    n_recurs = sum(bool(row["trough_recurs"]) for row in ok)
    n_compact = sum(bool(row["compact_and_agrees"]) for row in ok)
    if n_ok == 0:
        outcome = "inconclusive"
    elif n_compact >= RULE["majority_fraction"] * n_ok:
        outcome = "A"
    elif n_recurs <= RULE["minority_fraction"] * n_ok:
        outcome = "B"
    else:
        outcome = "inconclusive"
    return {
        "outcome": outcome,
        "n_windows": len(rows),
        "n_ok": n_ok,
        "n_trough_recurs": n_recurs,
        "n_compact_and_agrees": n_compact,
    }


def _load_rank_troughs(path):
    if path is None:
        return {}
    table = pd.read_csv(path)
    return {str(row.window_id): int(row.rank_trough_month) for row in table.itertuples(index=False)}


def to_markdown(rows, decision):
    lines = [
        f"Outcome: **{decision['outcome']}** "
        f"({decision['n_compact_and_agrees']} compact-and-agreeing, "
        f"{decision['n_trough_recurs']} trough-recurring, of {decision['n_ok']} windows "
        f"with status ok; {decision['n_windows']} windows read).",
        "",
        "| window | years | detectable | regime | reason | peak p | trough p | dominant "
        "| trough set width | peak set width | harmonic | rank | dist |",
        "| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in rows:
        harmonic = f"{row['harmonic_pattern']}/{row['harmonic_order']}/{row['harmonic_trough']}"
        lines.append(
            f"| {row['window_id']} | {row['n_usable_years']} | {row['n_detectable_years']} "
            f"| {row['regime']} | {row['reason']} | {row['peak_p']} | {row['trough_p']} "
            f"| {row['trough_dominant_month']} | {row['median_trough_set_width']} "
            f"| {row['median_peak_set_width']} | {harmonic} | {row['rank_trough_month']} "
            f"| {row['circular_distance_to_rank']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--rank-troughs", type=Path, default=None)
    parser.add_argument("--n-bootstrap", type=int, default=200)
    args = parser.parse_args(argv)

    warnings.filterwarnings("ignore")
    ranks = _load_rank_troughs(args.rank_troughs)
    paths = sorted(args.fixtures.glob("*.csv"))
    if not paths:
        parser.error(f"no CSV fixtures in {args.fixtures}")

    rows = []
    for path in paths:
        frame = load_extent_csv(path, date_col="date", value_col="extent_pct")
        rows.append(
            assess_window(
                path.stem, frame, rank_trough=ranks.get(path.stem), n_bootstrap=args.n_bootstrap
            )
        )
    decision = decide(rows)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    markdown = to_markdown(rows, decision)
    if args.summary is not None:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
