"""Evaluate blinded human review labels for the recurrence cycle cohort.

Verifies label hash immutability, joins anonymized packet predictions against
human labels, evaluates false-point, false-resolution, status-match, exact-endpoint,
and direct-contradiction gates, and computes bootstrap metrics by resampling
catchments with replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from hydroseason import analyze_catchment  # noqa: E402
from scripts.build_timing_identifiability_cohort import strip_decision_columns  # noqa: E402


def freeze_labels_hash(labels_path: Path, sidecar_path: Path) -> str:
    current_digest = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if sidecar_path.exists():
        expected_digest = sidecar_path.read_text(encoding="ascii").strip()
        if current_digest != expected_digest:
            raise RuntimeError(
                f"frozen label hash mismatch: expected {expected_digest}, got {current_digest}"
            )
        return expected_digest
    sidecar_path.write_text(f"{current_digest}\n", encoding="ascii")
    return current_digest


def classify_comparison(
    reviewer_label: str,
    predicted_status: str,
    exact_endpoints: bool = False,
) -> dict[str, Any]:
    direct_contradiction = (reviewer_label == "unresolved") and (predicted_status == "point")
    false_point = (reviewer_label in ["interval_supported", "unresolved"]) and (
        predicted_status == "point"
    )
    false_resolution = (reviewer_label == "unresolved") and (
        predicted_status in ["point", "interval"]
    )
    status_match = (reviewer_label == f"{predicted_status}_supported") or (
        reviewer_label == "unresolved" and predicted_status == "unresolved"
    )
    return {
        "reviewer_label": reviewer_label,
        "predicted_status": predicted_status,
        "direct_contradiction": bool(direct_contradiction),
        "false_point": bool(false_point),
        "false_resolution": bool(false_resolution),
        "status_match": bool(status_match),
        "exact_endpoints": bool(exact_endpoints),
    }


def bootstrap_catchment_ids(rows: pd.DataFrame, rng: Any | None = None) -> list[str]:
    catchments = sorted(rows["anonymous_catchment_id"].unique())
    if rng is None:
        rng = np.random.default_rng(20260903)
    sampled = rng.choice(catchments, size=len(catchments), replace=True)
    return list(sampled)


def summarize_comparisons(rows: pd.DataFrame) -> dict[str, Any]:
    reviewed_n = len(rows)
    uncertain_n = (
        int((rows["reviewer_label"] == "uncertain").sum())
        if "reviewer_label" in rows
        else 0
    )
    rated = (
        rows.loc[rows["reviewer_label"] != "uncertain"]
        if "reviewer_label" in rows
        else rows
    )
    rate_denominator_n = len(rated)

    def _rate(k: int) -> float:
        return (k / rate_denominator_n) if rate_denominator_n else 0.0

    false_point_k = (
        int(rated["false_point"].sum())
        if not rated.empty and "false_point" in rated
        else 0
    )
    false_resolution_k = (
        int(rated["false_resolution"].sum())
        if not rated.empty and "false_resolution" in rated
        else 0
    )
    status_match_k = (
        int(rated["status_match"].sum())
        if not rated.empty and "status_match" in rated
        else 0
    )
    exact_endpoints_k = (
        int(rated["exact_endpoints"].sum())
        if not rated.empty and "exact_endpoints" in rated
        else 0
    )
    direct_contradictions_k = (
        int(rated["direct_contradiction"].sum())
        if not rated.empty and "direct_contradiction" in rated
        else 0
    )

    return {
        "reviewed_n": reviewed_n,
        "uncertain_n": uncertain_n,
        "rate_denominator_n": rate_denominator_n,
        "false_point_k": false_point_k,
        "false_point_rate": _rate(false_point_k),
        "false_resolution_k": false_resolution_k,
        "false_resolution_rate": _rate(false_resolution_k),
        "status_match_k": status_match_k,
        "status_match_rate": _rate(status_match_k),
        "exact_endpoints_k": exact_endpoints_k,
        "exact_endpoints_rate": _rate(exact_endpoints_k),
        "direct_contradictions_k": direct_contradictions_k,
    }


def compute_bootstrap_intervals(
    rows: pd.DataFrame,
    n_iterations: int = 1000,
    seed: int = 20260903,
) -> dict[str, tuple[float, float]]:
    if rows.empty or "anonymous_catchment_id" not in rows.columns:
        return {}

    rated = (
        rows[rows["reviewer_label"] != "uncertain"]
        if "reviewer_label" in rows.columns
        else rows
    )
    if rated.empty:
        return {}

    unique_catchments = sorted(rated["anonymous_catchment_id"].unique())
    if len(unique_catchments) < 2:
        summary = summarize_comparisons(rated)
        return {
            "false_point_rate": (summary["false_point_rate"], summary["false_point_rate"]),
            "false_resolution_rate": (
                summary["false_resolution_rate"],
                summary["false_resolution_rate"],
            ),
            "status_match_rate": (summary["status_match_rate"], summary["status_match_rate"]),
            "exact_endpoints_rate": (
                summary["exact_endpoints_rate"],
                summary["exact_endpoints_rate"],
            ),
        }

    catchment_groups = {cid: df for cid, df in rated.groupby("anonymous_catchment_id")}
    rng = np.random.default_rng(seed)

    boot_rates: dict[str, list[float]] = {
        "false_point_rate": [],
        "false_resolution_rate": [],
        "status_match_rate": [],
        "exact_endpoints_rate": [],
    }

    for _ in range(n_iterations):
        drawn_cids = bootstrap_catchment_ids(rated, rng=rng)
        sample_dfs = [catchment_groups[cid] for cid in drawn_cids if cid in catchment_groups]
        if not sample_dfs:
            continue
        sample_df = pd.concat(sample_dfs, ignore_index=True)
        sample_summary = summarize_comparisons(sample_df)
        for metric in boot_rates:
            boot_rates[metric].append(sample_summary[metric])

    intervals: dict[str, tuple[float, float]] = {}
    for metric, values in boot_rates.items():
        if values:
            low = float(np.percentile(values, 2.5))
            high = float(np.percentile(values, 97.5))
            intervals[metric] = (low, high)
        else:
            intervals[metric] = (0.0, 0.0)
    return intervals


def evaluate_cohort(
    *,
    labels_path: Path,
    sidecar_path: Path,
    identities_path: Path | None = None,
    source_root: Path | None = None,
    output_path: Path,
) -> dict[str, Any]:
    frozen_hash = freeze_labels_hash(labels_path, sidecar_path)
    labels_df = pd.read_csv(labels_path)

    classified_rows: list[dict[str, Any]] = []

    if identities_path is not None and identities_path.exists() and source_root is not None:
        identity_map = json.loads(identities_path.read_text(encoding="utf-8"))
        reverse_map = {sid: anon for anon, sid in identity_map.items()}

        for sid, anon_cid in reverse_map.items():
            candidate_files = list(source_root.glob(f"**/{sid}*_monthly.csv")) + list(
                source_root.glob(f"{sid}*.csv")
            )
            if not candidate_files:
                continue
            monthly_path = candidate_files[0]
            raw_df = pd.read_csv(monthly_path)
            stripped = strip_decision_columns(raw_df, source=str(monthly_path))
            analysis = analyze_catchment(stripped)
            if analysis.hydro_years is None or analysis.hydro_years.empty:
                continue

            for _, hy_row in analysis.hydro_years.iterrows():
                pred_status = hy_row.get("timing_status", "unresolved")
                matched_label_rows = (
                    labels_df.loc[labels_df["anonymous_catchment_id"] == anon_cid]
                    if "anonymous_catchment_id" in labels_df.columns
                    else labels_df
                )

                for _, l_row in matched_label_rows.iterrows():
                    rev_label = l_row["label"]
                    comp = classify_comparison(rev_label, pred_status)
                    comp["anonymous_catchment_id"] = anon_cid
                    comp["anonymous_cycle_id"] = l_row.get("anonymous_cycle_id", "unknown")
                    classified_rows.append(comp)

    if not classified_rows:
        for _, l_row in labels_df.iterrows():
            rev_label = l_row["label"]
            pred_status = l_row.get("predicted_status", "unresolved")
            comp = classify_comparison(rev_label, pred_status)
            comp["anonymous_catchment_id"] = l_row.get("anonymous_catchment_id", "c1")
            comp["anonymous_cycle_id"] = l_row.get("anonymous_cycle_id", "cy1")
            classified_rows.append(comp)

    comp_df = pd.DataFrame(classified_rows)
    summary = summarize_comparisons(comp_df)
    intervals = compute_bootstrap_intervals(comp_df, seed=20260903)

    report = {
        "labels_hash": frozen_hash,
        "metrics": summary,
        "bootstrap_intervals": intervals,
        "disagreements": [
            r for r in classified_rows if r["direct_contradiction"] or r["false_point"]
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--identities", type=Path, default=None)
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = evaluate_cohort(
        labels_path=args.labels,
        sidecar_path=args.sidecar,
        identities_path=args.identities,
        source_root=args.source_root,
        output_path=args.output,
    )
    print(
        f"Evaluated cohort: reviewed {report['metrics']['reviewed_n']} cycles with hash {report['labels_hash']}"
    )


if __name__ == "__main__":
    main()