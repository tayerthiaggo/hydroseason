"""Render case study documentation tables from checked CSV results.

Updates markdown files between marker comments or checks that documentation matches checked results.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent


def render_main_results_table(summary_csv: Path) -> str:
    """Render main study Markdown table from summary.csv."""
    df = pd.read_csv(summary_csv)
    peak_column = (
        "water_extent_peak_month"
        if "water_extent_peak_month" in df.columns
        else "climatological_peak_month"
    )
    lines = [
        "| Catchment | Regime | Route | SNR | Peak R | Trough R | Trough R CI low | Peak-month IQR (months) | Hydro Years | Events | Longest Low Spell (months) | Peak Month | Trough Month |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, row in df.iterrows():
        snr_str = f"{row['amplitude_snr']:.2f}"
        peak_r_str = (
            f"{row['peak_timing_concentration']:.3f}"
            if pd.notna(row.get("peak_timing_concentration"))
            else "N/A"
        )
        trough_r_str = (
            f"{row['trough_timing_concentration']:.3f}"
            if pd.notna(row.get("trough_timing_concentration"))
            else "N/A"
        )
        trough_ci_str = (
            f"{row['trough_timing_concentration_ci_low']:.3f}"
            if pd.notna(row.get("trough_timing_concentration_ci_low"))
            else "N/A"
        )
        peak_iqr_str = (
            f"{row['peak_phase_iqr_months']:.1f}"
            if pd.notna(row["peak_phase_iqr_months"])
            else "N/A"
        )
        peak_str = (
            pd.to_datetime(f"2020-{int(row[peak_column]):02d}-01").strftime("%b")
            if pd.notna(row[peak_column])
            else "N/A"
        )
        trough_str = (
            pd.to_datetime(f"2020-{int(row['climatological_trough_month']):02d}-01").strftime("%b")
            if pd.notna(row["climatological_trough_month"])
            else "N/A"
        )
        lines.append(
            f"| {row['name']} | {row['regime']} | {row['route']} | {snr_str} | "
            f"{peak_r_str} | {trough_r_str} | {trough_ci_str} | {peak_iqr_str} | "
            f"{row['n_hydro_years']} | {row['n_events']} | {row['longest_low_spell_months']} | "
            f"{peak_str} | {trough_str} |"
        )
    return "\n".join(lines)


def render_rainfall_results_table(summary_csv: Path) -> str:
    """Render rainfall-augmented main study Markdown table from summary.csv."""
    df = pd.read_csv(summary_csv)
    lines = [
        "| Catchment | Water Regime | Rainfall Regime | Water SNR | Rainfall SNR | Water Peak R | Rainfall Peak R | Divergence | Peak Lag (months) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, row in df.iterrows():
        lag_str = (
            f"{row['rainfall_peak_lag_months']:.0f}"
            if pd.notna(row["rainfall_peak_lag_months"])
            else "N/A"
        )
        water_r_str = (
            f"{row['peak_timing_concentration']:.3f}"
            if pd.notna(row.get("peak_timing_concentration"))
            else "N/A"
        )
        rain_r_str = (
            f"{row['rainfall_peak_timing_concentration']:.3f}"
            if pd.notna(row.get("rainfall_peak_timing_concentration"))
            else "N/A"
        )
        lines.append(
            f"| {row['name']} | {row['regime']} | {row['rainfall_regime']} | "
            f"{row['amplitude_snr']:.2f} | {row['rainfall_amplitude_snr']:.2f} | "
            f"{water_r_str} | {rain_r_str} | "
            f"{row['rainfall_divergence']} | {lag_str} |"
        )
    return "\n".join(lines)


def render_resolution_results_table(decision_csv: Path) -> str:
    """Render resolution decision Markdown table from decision.csv."""
    df = pd.read_csv(decision_csv)
    lines = [
        "| Candidate Resolution | Route Agreement | Median Correlation | Median nMAE | Peak Within 1 Month | Trough Within 1 Month | Max Event Delta | Max Low Spell Delta | Recommended |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, row in df.iterrows():
        corr_str = f"{row['median_correlation']:.4f}" if pd.notna(row['median_correlation']) else "N/A"
        nmae_str = f"{row['median_normalized_mae']:.4f}"
        peak_str = f"{row['median_peak_within_one_month'] * 100:.1f}%"
        trough_str = f"{row['median_trough_within_one_month'] * 100:.1f}%"
        rec_str = str(row['recommended'])
        lines.append(
            f"| {row['candidate_resolution_m']} m | {row['route_agreement_count']} | {corr_str} | {nmae_str} | "
            f"{peak_str} | {trough_str} | {row['max_abs_event_count_delta']} | {row['max_abs_longest_low_spell_delta']} | {rec_str} |"
        )
    return "\n".join(lines)


def render_acquisition_results_table(acquisition_summary_csv: Path) -> str:
    """Render acquisition Markdown table from acquisition-summary.csv."""
    if not acquisition_summary_csv.exists() or acquisition_summary_csv.stat().st_size == 0:
        return (
            "| Pruning Mode | Analysis Resolution | Median Speedup | Median Peak RSS (MB) |\n"
            "|---|---|---|---|\n"
            "| `off` (Full AOI) | 30 m | 1.00x | Base |\n"
            "| `planning_footprint` | 30 m | Opt-in Benchmark | Opt-in Benchmark |"
        )

    df = pd.read_csv(acquisition_summary_csv)
    if df.empty:
        return (
            "| Pruning Mode | Analysis Resolution | Median Speedup | Median Peak RSS (MB) |\n"
            "|---|---|---|---|\n"
            "| `off` (Full AOI) | 30 m | 1.00x | Base |\n"
            "| `planning_footprint` | 30 m | Opt-in Benchmark | Opt-in Benchmark |"
        )

    lines = [
        "| Pruning Mode | Analysis Resolution | Median Speedup | Median Peak RSS (MB) |",
        "|---|---|---|---|",
    ]
    for _, row in df.iterrows():
        p_mode = f"`{row['pruning']}`"
        res_str = f"{row['resolution_m']} m"
        speedup_str = f"{row['median_speedup']:.2f}x"
        rss_str = f"{row['median_peak_rss_mb']:.1f}" if pd.notna(row.get('median_peak_rss_mb')) else "N/A"
        lines.append(f"| {p_mode} | {res_str} | {speedup_str} | {rss_str} |")
    return "\n".join(lines)


def replace_marker_content(text: str, marker_name: str, new_content: str) -> str:
    pattern = rf"(<!-- BEGIN {marker_name} -->\n)(.*?)(<!-- END {marker_name} -->)"
    replacement = rf"\g<1>{new_content}\n\g<3>"
    return re.sub(pattern, replacement, text, flags=re.DOTALL)


def render_case_study_docs(root: Path = REPO_ROOT, *, check: bool = False) -> int:
    """Render or check case study documentation tables against checked CSV results."""
    root = Path(root)
    main_doc = root / "docs" / "case-studies" / "main-workflow.md"
    resolution_doc = root / "docs" / "case-studies" / "resolution-and-acquisition.md"
    rainfall_doc = root / "docs" / "case-studies" / "rainfall-context.md"

    main_summary_csv = root / "case_studies" / "results" / "main" / "summary.csv"
    decision_csv = root / "case_studies" / "results" / "resolution" / "decision.csv"
    acquisition_csv = root / "case_studies" / "results" / "resolution" / "acquisition-summary.csv"
    rainfall_summary_csv = root / "case_studies" / "results" / "main_rainfall" / "summary.csv"

    if not main_doc.exists() or not resolution_doc.exists() or not rainfall_doc.exists():
        print("ERROR: Case study documentation files missing.", file=sys.stderr)
        return 1

    if not main_summary_csv.exists() or not decision_csv.exists() or not rainfall_summary_csv.exists():
        print("ERROR: Result CSV files missing.", file=sys.stderr)
        return 1

    main_text = main_doc.read_text(encoding="utf-8")
    main_table = render_main_results_table(main_summary_csv)
    new_main_text = replace_marker_content(main_text, "GENERATED MAIN RESULTS", main_table)

    res_text = resolution_doc.read_text(encoding="utf-8")
    res_table = render_resolution_results_table(decision_csv)
    acq_table = render_acquisition_results_table(acquisition_csv)

    new_res_text = replace_marker_content(res_text, "GENERATED RESOLUTION RESULTS", res_table)
    new_res_text = replace_marker_content(new_res_text, "GENERATED ACQUISITION RESULTS", acq_table)

    rainfall_text = rainfall_doc.read_text(encoding="utf-8")
    rainfall_table = render_rainfall_results_table(rainfall_summary_csv)
    new_rainfall_text = replace_marker_content(rainfall_text, "GENERATED RAINFALL RESULTS", rainfall_table)

    if check:
        drift = False
        if new_main_text != main_text:
            print(f"DRIFT DETECTED: {main_doc} differs from checked CSV results.", file=sys.stderr)
            drift = True
        if new_res_text != res_text:
            print(f"DRIFT DETECTED: {resolution_doc} differs from checked CSV results.", file=sys.stderr)
            drift = True
        if new_rainfall_text != rainfall_text:
            print(f"DRIFT DETECTED: {rainfall_doc} differs from checked CSV results.", file=sys.stderr)
            drift = True
        if drift:
            return 1
        print("CHECK PASS: All case study documentation tables match checked results.")
        return 0

    main_doc.write_text(new_main_text, encoding="utf-8")
    resolution_doc.write_text(new_res_text, encoding="utf-8")
    rainfall_doc.write_text(new_rainfall_text, encoding="utf-8")
    print("Rendered case study documentation tables successfully.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check documentation tables against CSV results without modifying files",
    )
    args = parser.parse_args()
    ret = render_case_study_docs(REPO_ROOT, check=args.check)
    sys.exit(ret)


if __name__ == "__main__":
    main()
