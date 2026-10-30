"""Sweep known-truth records through the harmonic and recurrence paths.

Writes one CSV row per (construction, years, flood_rate, gap, counts, seed) and
a markdown summary per cell. Records behaviour; asserts nothing. This is step 3
of docs/provisional-trough-verdict-2026-10-30.md. "Wrong month" means outside
the union of strict annual minima; on a near-flat plateau this can include
months within the plateau that were never the strict minimum.

Example (default grid of 90 cells, 30 seeds, 15 to 25 minutes single-threaded):

    .venv/Scripts/python.exe scripts/trough_falsification_sweep.py --seeds 30 \
        --out dev/reports/2026-10-30-trough-falsification-matrix.csv \
        --summary dev/reports/2026-10-30-trough-falsification-summary.md
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

from hydroseason import assess_water_regime, classify_seasonal_pattern  # noqa: E402
from scripts.trough_synthetic import (  # noqa: E402
    CONSTRUCTIONS,
    build_record,
    truth_trough_months,
)

ALPHA = 0.05
REFUSAL_LABELS = {"low_variability", "weak_or_irregular", "insufficient_record"}
CELL_KEYS = ["construction", "years", "flood_rate", "gap", "counts"]
COLUMNS = CELL_KEYS + [
    "seed",
    "truth_months",
    "harmonic_pattern",
    "harmonic_order",
    "harmonic_trough",
    "harmonic_accepted",
    "harmonic_trough_in_truth",
    "regime",
    "status",
    "reason",
    "peak_p",
    "trough_p",
    "trough_dominant_month",
    "trough_dominant_in_truth",
    "n_detectable_years",
    "median_trough_set_width",
]


def run_cell(kind, *, years, flood_rate, gap, counts, seeds, n_bootstrap):
    """One row per seed for a single cell of the grid."""
    rows = []
    for seed in range(seeds):
        values, frame = build_record(
            kind, seed=seed, years=years, flood_rate=flood_rate, gap=gap, counts=counts
        )
        truth = set(truth_trough_months(values))
        result = classify_seasonal_pattern(frame, n_null=49)
        assessment = assess_water_regime(frame, n_bootstrap=n_bootstrap)
        test = assessment.seasonality_test
        accepted = result.pattern not in REFUSAL_LABELS
        widths = [len(months) for months in test.trough_month_sets.values()]
        dominant = test.trough.dominant_month
        rows.append(
            {
                "construction": kind,
                "years": years,
                "flood_rate": flood_rate,
                "gap": gap or "none",
                "counts": counts,
                "seed": seed,
                "truth_months": "|".join(str(month) for month in sorted(truth)),
                "harmonic_pattern": result.pattern,
                "harmonic_order": result.selected_harmonic_order,
                "harmonic_trough": result.expected_trough_month,
                "harmonic_accepted": accepted,
                "harmonic_trough_in_truth": bool(
                    accepted and result.expected_trough_month in truth
                ),
                "regime": assessment.regime,
                "status": test.status,
                "reason": test.reason,
                "peak_p": test.peak.uniformity_p,
                "trough_p": test.trough.uniformity_p,
                "trough_dominant_month": dominant,
                "trough_dominant_in_truth": None if dominant is None else dominant in truth,
                "n_detectable_years": test.n_detectable_years,
                "median_trough_set_width": float(np.median(widths)) if widths else None,
            }
        )
    return rows


def summarise(rows):
    """Per-cell counts. Rates are counts over ``n``; no thresholds are applied."""
    frame = pd.DataFrame(rows, columns=COLUMNS)
    trough_p = pd.to_numeric(frame["trough_p"], errors="coerce")
    peak_p = pd.to_numeric(frame["peak_p"], errors="coerce")
    frame = frame.assign(_trough_rej=trough_p < ALPHA, _peak_rej=peak_p < ALPHA)
    summary = []
    for keys, cell in frame.groupby(CELL_KEYS, sort=True):
        accepted = cell["harmonic_accepted"].astype(bool)
        in_truth = cell["harmonic_trough_in_truth"].astype(bool)
        widths = pd.to_numeric(cell["median_trough_set_width"], errors="coerce")
        summary.append(
            {
                "cell": "/".join(str(key) for key in keys),
                "n": int(len(cell)),
                "harmonic_accept": int(accepted.sum()),
                "harmonic_wrong_month": int((accepted & ~in_truth).sum()),
                "trough_rej": int(cell["_trough_rej"].sum()),
                "peak_rej": int(cell["_peak_rej"].sum()),
                "seasonal": int((cell["regime"] == "seasonal").sum()),
                "median_set_width": float(widths.median()),
            }
        )
    return summary


def to_markdown(summary):
    lines = [
        "| cell | n | harmonic accept | harmonic wrong month | trough p<0.05 "
        "| peak p<0.05 | seasonal | median set width |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary:
        lines.append(
            f"| {row['cell']} | {row['n']} | {row['harmonic_accept']} "
            f"| {row['harmonic_wrong_month']} | {row['trough_rej']} | {row['peak_rej']} "
            f"| {row['seasonal']} | {row['median_set_width']:.1f} |"
        )
    return "\n".join(lines) + "\n"


def _parse_gap(text):
    return None if text == "none" else text


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument(
        "--constructions",
        nargs="+",
        default=["stable", "stable_sharp", "drift", "plateau", "uniform"],
        choices=CONSTRUCTIONS,
    )
    parser.add_argument("--years", nargs="+", type=int, default=[7, 12, 30])
    parser.add_argument("--floods", nargs="+", type=float, default=[0.0, 0.3])
    parser.add_argument(
        "--gaps",
        nargs="+",
        default=["none", "dry20", "wet20"],
        choices=["none", "random20", "dry20", "wet20"],
    )
    parser.add_argument(
        "--counts", action="store_true", help="attach consistent pixel counts to every record"
    )
    parser.add_argument("--n-bootstrap", type=int, default=50)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    args = parser.parse_args(argv)

    warnings.filterwarnings("ignore")
    rows = []
    for kind in args.constructions:
        for years in args.years:
            for flood_rate in args.floods:
                for gap in args.gaps:
                    rows.extend(
                        run_cell(
                            kind,
                            years=years,
                            flood_rate=flood_rate,
                            gap=_parse_gap(gap),
                            counts=args.counts,
                            seeds=args.seeds,
                            n_bootstrap=args.n_bootstrap,
                        )
                    )
                    print(f"done {kind}/{years}/{flood_rate}/{gap}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    markdown = to_markdown(summarise(rows))
    if args.summary is not None:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
