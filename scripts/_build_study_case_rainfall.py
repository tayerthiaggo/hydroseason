"""Build the rainfall-augmented main case study (Case Study 1b) offline.

Same five catchments, same 30 m extent inputs, and the same route-aware water
analysis as Case Study 1 (``_build_study_case_offline.py``) -- rainfall is
purely additive context laid alongside it, never a second opinion that can
change a regime, route, or hydrological-year boundary
(see ``_catchment.CatchmentAnalysis`` and the ``workflow.run_hydroseason``
invariant that rainfall is resolved strictly after the water-only analysis).

Rainfall is monthly SILO gridded rainfall (silo-open-data, Official archive),
pre-fetched to ``case_studies/data/rainfall/{key}_silo_rainfall.csv`` and
trimmed to the analysis window so this script -- like the main study -- runs
fully offline from committed inputs.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

from hydroseason import analyze_catchment, generate_catchment_report, load_extent_csv
from hydroseason._rainfall import align_monthly_rainfall, load_monthly_rainfall_csv
from hydroseason._regime_compare import compare_rainfall_to_extent_regime

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXTENT_DIR = REPO_ROOT / "case_studies" / "data" / "extent"
DEFAULT_RAINFALL_DIR = REPO_ROOT / "case_studies" / "data" / "rainfall"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "case_studies" / "results" / "main_rainfall"

CATCHMENT_NAMES = {
    "daly_river_nt": "Daly River (NT)",
    "fitzroy_river_wa": "Fitzroy River (WA)",
    "gilbert_river_qld": "Gilbert River (QLD)",
    "lachlan_river_nsw": "Lachlan River (NSW)",
    "moonie_river_qld_nsw": "Moonie River (QLD/NSW)",
}


def build_rainfall_study(
    extent_dir: Path, rainfall_dir: Path, output_dir: Path
) -> pd.DataFrame:
    """Build the rainfall-augmented report bundle and summary dataframe."""
    extent_dir = Path(extent_dir)
    rainfall_dir = Path(rainfall_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    errors: list[str] = []

    for key in sorted(CATCHMENT_NAMES.keys()):
        name = CATCHMENT_NAMES[key]
        extent_csv = extent_dir / f"{key}_30m.csv"
        rainfall_csv = rainfall_dir / f"{key}_silo_rainfall.csv"
        if not extent_csv.exists():
            errors.append(f"Missing required input extent file: {extent_csv}")
            continue
        if not rainfall_csv.exists():
            errors.append(f"Missing required input rainfall file: {rainfall_csv}")
            continue

        try:
            extent = load_extent_csv(extent_csv, date_col="date", value_col="extent_pct")
            # Water-only analysis first and unconditionally: rainfall must
            # never be able to change the regime, route, or HY boundaries it
            # is laid alongside.
            analysis = analyze_catchment(
                extent,
                phase_model="rule_based",
                quality_policy="flag",
            )
            rainfall = load_monthly_rainfall_csv(rainfall_csv)
            rainfall = align_monthly_rainfall(rainfall, extent.index)
            comparison = compare_rainfall_to_extent_regime(analysis.regime, rainfall)
            aoi_path = REPO_ROOT / "data" / "catchments" / f"{key}_boundary.geojson"
            aoi_context = None
            if aoi_path.exists():
                try:
                    from hydroseason._aoi_context import build_aoi_context
                    from hydroseason._boundary import load_aoi

                    aoi_context = build_aoi_context(load_aoi(aoi_path), display_name=name)
                except Exception:
                    pass

            generate_catchment_report(
                extent,
                output_dir / key,
                name=key,
                analysis=analysis,
                title=name,
                subtitle="Whole-catchment monthly surface-water extent with SILO rainfall context, 2005-2025",
                quality_note=(
                    "Finite monthly observations are retained for boundary mapping; "
                    "invalid coverage is reported and low-quality boundaries are "
                    "marked provisional/low confidence."
                ),
                rainfall=rainfall,
                rainfall_comparison=comparison,
                rainfall_source="silo",
                aoi_context=aoi_context,
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
                    "peak_phase_iqr_months": (
                        round(float(analysis.regime.peak_phase_iqr_months), 3)
                        if analysis.regime.peak_phase_iqr_months is not None
                        else None
                    ),
                    "water_extent_peak_month": (
                        float(analysis.climatological_peak_month)
                        if analysis.climatological_peak_month is not None
                        else None
                    ),
                    "climatological_trough_month": (
                        float(analysis.climatological_trough_month)
                        if analysis.climatological_trough_month is not None
                        else None
                    ),
                    "rainfall_regime": (
                        comparison.rainfall.regime if comparison.rainfall is not None else None
                    ),
                    "rainfall_amplitude_snr": (
                        round(float(comparison.rainfall.amplitude_snr), 3)
                        if comparison.rainfall is not None
                        else None
                    ),
                    "rainfall_divergence": comparison.divergence,
                    "rainfall_peak_lag_months": comparison.peak_lag_months,
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed building rainfall case study for {key}: {exc}")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    summary_df = pd.DataFrame(rows)
    summary_csv = output_dir / "summary.csv"
    summary_df.to_csv(summary_csv, index=False, lineterminator="\n")
    return summary_df


def check_rainfall_study(
    extent_dir: Path = DEFAULT_EXTENT_DIR,
    rainfall_dir: Path = DEFAULT_RAINFALL_DIR,
    target_summary_csv: Path = DEFAULT_OUTPUT_DIR / "summary.csv",
) -> bool:
    """Verify built rainfall study summary matches target summary CSV."""
    if not target_summary_csv.exists():
        print(f"CHECK FAIL: Target summary CSV missing: {target_summary_csv}", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_output = Path(tmp_dir)
        summary_df = build_rainfall_study(extent_dir, rainfall_dir, tmp_output)
        gen_csv = tmp_output / "summary.csv"

        target_bytes = target_summary_csv.read_bytes().replace(b"\r\n", b"\n")
        gen_bytes = gen_csv.read_bytes().replace(b"\r\n", b"\n")

        if gen_bytes != target_bytes:
            print("CHECK FAIL: Generated summary CSV differs from target CSV.", file=sys.stderr)
            target_df = pd.read_csv(target_summary_csv)
            if not summary_df.equals(target_df):
                print("DataFrame differences detected.", file=sys.stderr)
            return False

    print("CHECK PASS: Rainfall study summary matches checked results.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extent-dir",
        type=Path,
        default=DEFAULT_EXTENT_DIR,
        help="Directory containing 30m extent CSVs",
    )
    parser.add_argument(
        "--rainfall-dir",
        type=Path,
        default=DEFAULT_RAINFALL_DIR,
        help="Directory containing per-catchment SILO rainfall CSVs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for rainfall case study results",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify built rainfall study summary against committed results without modifying files",
    )
    args = parser.parse_args()

    if args.check:
        ok = check_rainfall_study(args.extent_dir, args.rainfall_dir, args.output_dir / "summary.csv")
        sys.exit(0 if ok else 1)

    print(
        f"Building rainfall case study from {args.extent_dir} + {args.rainfall_dir} "
        f"to {args.output_dir}..."
    )
    summary = build_rainfall_study(args.extent_dir, args.rainfall_dir, args.output_dir)
    print(f"Successfully generated rainfall case study for {len(summary)} catchments.")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
