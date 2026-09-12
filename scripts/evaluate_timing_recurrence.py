"""Score the seasonality candidate against known-truth synthetic records.

Nothing here selects a parameter. Alpha and every rule were fixed in the
design before any record was drawn, so this script only measures and reports:
a failed acceptance criterion is a finding, never a reason to retune.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import hydroseason  # noqa: E402
from hydroseason._regime import assess_water_regime  # noqa: E402
from hydroseason._seasonality_synthetic import (  # noqa: E402
    SEASONALITY_FAMILIES,
    SeasonalityRecord,
    iter_seasonality_records,
)

Z_ONE_SIDED_95 = 1.6448536269514722
FALSE_SEASONAL_BOUND = 0.05
DETECTION_FLOOR = 0.80
DETECTION_LENGTHS = (15, 30)
SENSITIVITY_ALPHA = 0.10


def wilson_upper(successes: int, trials: int, z: float = Z_ONE_SIDED_95) -> float:
    """One-sided Wilson upper bound for a proportion."""
    if trials <= 0:
        return 1.0
    proportion = successes / trials
    denominator = 1.0 + z**2 / trials
    centre = proportion + z**2 / (2 * trials)
    spread = z * np.sqrt(
        proportion * (1.0 - proportion) / trials + z**2 / (4 * trials**2)
    )
    return float(min(1.0, (centre + spread) / denominator))


def score_record(record: SeasonalityRecord) -> dict:
    """Score one record under the established policy and the candidate."""
    established = assess_water_regime(record.frame, n_bootstrap=200, random_state=0)
    candidate = assess_water_regime(
        record.frame,
        n_bootstrap=200,
        random_state=0,
        seasonality_policy="timing_recurrence",
    )
    test = candidate.seasonality_test
    return {
        "family": record.truth.family,
        "family_id": record.truth.family_id,
        "truth_seasonal": record.truth.truth_seasonal,
        "n_years": record.truth.n_years,
        "replicate": record.truth.replicate,
        "variant": record.truth.variant,
        "n_redraws": record.truth.n_redraws,
        "established_regime": established.regime,
        "established_route": established.public_route,
        "established_snr": round(float(established.amplitude_snr), 4),
        "candidate_class": test.classification if test else None,
        "candidate_status": test.status if test else None,
        "candidate_reason": test.reason if test else None,
        "candidate_regime": candidate.regime,
        "candidate_route": candidate.public_route,
        "candidate_peak_p": test.peak.uniformity_p if test else None,
        "candidate_trough_p": test.trough.uniformity_p if test else None,
        "candidate_peak_r": test.peak.concentration if test else None,
        "candidate_trough_r": test.trough.concentration if test else None,
        "n_detectable_years": test.n_detectable_years if test else 0,
        "n_timing_eligible_years": test.n_timing_eligible_years if test else 0,
    }


PROTECTED_RECORDS = ("daly_river_nt", "fitzroy_river_wa", "gilbert_river_qld",
                     "lachlan_river_nsw", "moonie_river_qld_nsw")


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render markdown without `DataFrame.to_markdown`, which needs tabulate.

    tabulate is neither installed nor declared in this project, so calling
    `to_markdown` would fail at the end of an hour-long run.
    """
    header = "| " + " | ".join(str(column) for column in frame.columns) + " |"
    rule = "| " + " | ".join("---" for _ in frame.columns) + " |"
    rows = [
        "| " + " | ".join("" if pd.isna(value) else str(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, rule, *rows]) + "\n"


def real_record_rows(paths: dict[str, Path]) -> pd.DataFrame:
    """Score named real records under both policies, protected ones included."""
    from hydroseason import load_extent_csv

    rows = []
    for name, path in paths.items():
        frame = load_extent_csv(path, date_col="date", value_col="extent_pct")
        established = assess_water_regime(frame, n_bootstrap=200, random_state=0)
        candidate = assess_water_regime(
            frame, n_bootstrap=200, random_state=0, seasonality_policy="timing_recurrence"
        )
        test = candidate.seasonality_test
        rows.append(
            {
                "record": name,
                "protected": name in PROTECTED_RECORDS,
                "established_regime": established.regime,
                "established_route": established.public_route,
                "established_snr": round(float(established.amplitude_snr), 3),
                "candidate_class": test.classification if test else None,
                "candidate_status": test.status if test else None,
                "candidate_reason": test.reason if test else None,
                "candidate_route": candidate.public_route,
                "candidate_peak_p": test.peak.uniformity_p if test else None,
                "candidate_trough_p": test.trough.uniformity_p if test else None,
                "n_detectable_years": test.n_detectable_years if test else 0,
                "agrees": (
                    (established.regime in {"seasonal", "marginal"})
                    == (candidate.regime == "seasonal")
                ),
            }
        )
    return pd.DataFrame(rows)


def _seasonal_at(rows: pd.DataFrame, alpha: float) -> pd.Series:
    """Recompute the candidate class at another alpha from saved p-values."""
    peak = rows["candidate_peak_p"]
    trough = rows["candidate_trough_p"]
    return (peak.notna() & trough.notna() & (peak < alpha) & (trough < alpha))


def summarise(records: pd.DataFrame, *, alpha: float) -> pd.DataFrame:
    """Rates by family, length and variant, with Wilson bounds."""
    seasonal = _seasonal_at(records, alpha)
    frame = records.assign(seasonal_call=seasonal)
    grouped = frame.groupby(
        ["family", "truth_seasonal", "variant", "n_years"], dropna=False
    )
    rows = []
    for (family, truth, variant, n_years), group in grouped:
        successes = int(group["seasonal_call"].sum())
        trials = int(len(group))
        rows.append(
            {
                "family": family,
                "truth_seasonal": truth,
                "variant": variant,
                "n_years": int(n_years),
                "seasonal": successes,
                "n": trials,
                "rate": successes / trials if trials else float("nan"),
                "wilson_upper": wilson_upper(successes, trials),
                "insufficient": int((group["candidate_status"] != "ok").sum()),
            }
        )
    return pd.DataFrame(rows)


def acceptance(metrics: pd.DataFrame) -> dict:
    """Apply the design's predeclared criteria to the metrics table."""
    # Ensure variant column exists for groupby operations
    work_metrics = metrics.copy()
    if "variant" not in work_metrics.columns:
        work_metrics["variant"] = "base"

    negatives = work_metrics.loc[
        work_metrics["truth_seasonal"] == False  # noqa: E712
    ]
    pooled = (
        negatives.groupby(["family", "variant"], dropna=False)[["seasonal", "n"]]
        .sum()
        .reset_index()
    )
    false_failures = []
    for row in pooled.itertuples():
        bound = wilson_upper(int(row.seasonal), int(row.n))
        if bound > FALSE_SEASONAL_BOUND:
            false_failures.append(
                {
                    "family": row.family,
                    "variant": row.variant,
                    "seasonal": int(row.seasonal),
                    "n": int(row.n),
                    "wilson_upper": bound,
                }
            )

    positives = work_metrics.loc[
        (work_metrics["truth_seasonal"] == True)  # noqa: E712
        & (work_metrics["n_years"].isin(DETECTION_LENGTHS))
        & (work_metrics["variant"] == "base")
    ]
    detection_failures = []
    if "rate" in positives.columns:
        detection_failures = [
            {
                "family": row.family,
                "n_years": int(row.n_years),
                "rate": float(row.rate),
                "n": int(row.n),
            }
            for row in positives.itertuples()
            if float(row.rate) < DETECTION_FLOOR
        ]

    return {
        "false_seasonal": {
            "bound": FALSE_SEASONAL_BOUND,
            "passed": not false_failures,
            "failures": false_failures,
        },
        "detection": {
            "floor": DETECTION_FLOOR,
            "lengths": list(DETECTION_LENGTHS),
            "passed": not detection_failures,
            "failures": detection_failures,
        },
        "status_accounting": {
            "insufficient_records": (
                int(work_metrics["insufficient"].sum())
                if "insufficient" in work_metrics.columns
                else 0
            ),
            "note": (
                "insufficient records are counted separately and never as aseasonal"
            ),
        },
    }


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=200)
    parser.add_argument("--lengths", type=int, nargs="+", default=[7, 15, 30])
    parser.add_argument(
        "--variants",
        nargs="+",
        default=[
            "base",
            "missing_10",
            "missing_25",
            "low_state_gap",
            "pixel_rounded",
        ],
    )
    parser.add_argument("--real-root", type=Path, default=None)
    args = parser.parse_args(argv)

    out_dir = args.out_dir
    if out_dir.exists() and any(out_dir.iterdir()):
        parser.error(
            f"{out_dir} exists and is not empty; run directories are immutable"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        score_record(record)
        for record in iter_seasonality_records(
            lengths=tuple(args.lengths),
            replicates=args.replicates,
            variants=tuple(args.variants),
        )
    ]
    records = pd.DataFrame(rows)
    records.to_csv(out_dir / "synthetic_records.csv", index=False)

    metrics = summarise(records, alpha=0.05)
    metrics.to_csv(out_dir / "synthetic_metrics.csv", index=False)
    summarise(records, alpha=SENSITIVITY_ALPHA).to_csv(
        out_dir / "sensitivity_alpha_0_10.csv", index=False
    )

    verdict = acceptance(metrics)
    (out_dir / "acceptance.json").write_text(
        json.dumps(verdict, indent=2), encoding="utf-8"
    )

    protocol = {
        "commit": _git_commit(),
        "hydroseason_version": hydroseason.__version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "alpha": 0.05,
        "sensitivity_alpha": SENSITIVITY_ALPHA,
        "replicates": args.replicates,
        "lengths": args.lengths,
        "variants": args.variants,
        "families": [family.name for family in SEASONALITY_FAMILIES],
        "seed_range": "90000-95000",
        "n_records": int(len(records)),
    }
    (out_dir / "protocol.json").write_text(
        json.dumps(protocol, indent=2), encoding="utf-8"
    )

    if args.real_root is not None:
        paths = {
            path.stem.replace("_30m", ""): path
            for path in sorted(args.real_root.glob("*_30m.csv"))
        }
        table = real_record_rows(paths)
        table.to_csv(out_dir / "real_records.csv", index=False)
        (out_dir / "real_records.md").write_text(_markdown_table(table), encoding="utf-8")

    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
