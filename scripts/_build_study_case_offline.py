"""Build main HydroSeason case study (Case Study 1) offline.

Consumes committed 30 m whole-catchment extent inputs and public route-aware APIs
(analyze_catchment, generate_catchment_report).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

from hydroseason import analyze_catchment, generate_catchment_report, load_extent_csv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "case_studies" / "data" / "extent"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "case_studies" / "results" / "main"

CATCHMENT_NAMES = {
    "daly_river_nt": "Daly River (NT)",
    "fitzroy_river_wa": "Fitzroy River (WA)",
    "gilbert_river_qld": "Gilbert River (QLD)",
    "lachlan_river_nsw": "Lachlan River (NSW)",
    "moonie_river_qld_nsw": "Moonie River (QLD/NSW)",
}


def build_main_study(data_dir: Path, output_dir: Path) -> pd.DataFrame:
    """Build complete main study report bundle and summary dataframe from 30m inputs."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    errors: list[str] = []

    for key in sorted(CATCHMENT_NAMES.keys()):
        name = CATCHMENT_NAMES[key]
        csv_path = data_dir / f"{key}_30m.csv"
        if not csv_path.exists():
            errors.append(f"Missing required input extent file: {csv_path}")
            continue

        try:
            extent = load_extent_csv(csv_path, date_col="date", value_col="extent_pct")
            analysis = analyze_catchment(extent, phase_model="rule_based")
            generate_catchment_report(
                extent,
                output_dir / key,
                name=key,
                analysis=analysis,
                title=name,
                subtitle="Whole-catchment monthly surface-water extent, 2005-2025",
            )
            rows.append(
                {
                    "key": key,
                    "name": name,
                    "series_used": "extent_pct",
                    "regime": analysis.regime.regime,
                    "route": analysis.route,
                    "route_reason": analysis.route_reason,
                    "n_months": len(extent),
                    "n_hydro_years": len(analysis.hydro_years),
                    "n_events": analysis.events.summary.get("n_events", 0),
                    "longest_low_spell_months": analysis.events.summary.get(
                        "longest_low_spell_months", 0
                    ),
                    "amplitude_snr": round(float(analysis.regime.amplitude_snr), 3),
                    "climatological_peak_month": (
                        float(analysis.climatological_peak_month)
                        if analysis.climatological_peak_month is not None
                        else None
                    ),
                    "climatological_trough_month": (
                        float(analysis.climatological_trough_month)
                        if analysis.climatological_trough_month is not None
                        else None
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed building case study for {key}: {exc}")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    summary_df = pd.DataFrame(rows)
    summary_csv = output_dir / "summary.csv"
    summary_df.to_csv(summary_csv, index=False, lineterminator="\n")
    return summary_df


def check_main_study(
    data_dir: Path = DEFAULT_DATA_DIR,
    target_summary_csv: Path = DEFAULT_OUTPUT_DIR / "summary.csv",
) -> bool:
    """Verify built main study summary matches target summary CSV."""
    if not target_summary_csv.exists():
        print(f"CHECK FAIL: Target summary CSV missing: {target_summary_csv}", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_output = Path(tmp_dir)
        summary_df = build_main_study(data_dir, tmp_output)
        gen_csv = tmp_output / "summary.csv"
        
        target_bytes = target_summary_csv.read_bytes().replace(b"\r\n", b"\n")
        gen_bytes = gen_csv.read_bytes().replace(b"\r\n", b"\n")

        if gen_bytes != target_bytes:
            print("CHECK FAIL: Generated summary CSV differs from target CSV.", file=sys.stderr)

            target_df = pd.read_csv(target_summary_csv)
            if not summary_df.equals(target_df):
                print("DataFrame differences detected.", file=sys.stderr)
            return False

    print("CHECK PASS: Main study summary matches checked results.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing 30m extent CSVs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for main case study results",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify built main study summary against committed results without modifying files",
    )
    args = parser.parse_args()

    if args.check:
        ok = check_main_study(args.data_dir, args.output_dir / "summary.csv")
        sys.exit(0 if ok else 1)

    print(f"Building main case study from {args.data_dir} to {args.output_dir}...")
    summary = build_main_study(args.data_dir, args.output_dir)
    print(f"Successfully generated main case study for {len(summary)} catchments.")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
