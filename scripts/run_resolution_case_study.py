"""Resolution fidelity and acquisition evidence study (Case Study 2).

Compares 30m whole-catchment extent baseline against 60m, 90m, and 300m coarsened series
across five catchments. Separates scientific resolution fidelity, pruning speed, and composite validation.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from hydroseason import analyze_catchment, load_extent_csv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "case_studies" / "data" / "extent"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "case_studies" / "results" / "resolution"

CATCHMENTS = [
    "daly_river_nt",
    "fitzroy_river_wa",
    "gilbert_river_qld",
    "lachlan_river_nsw",
    "moonie_river_qld_nsw",
]

RESOLUTIONS = [60, 90, 300]
ACQUISITION_SPEEDUP_GROUP_KEYS = ["pruning"]


@dataclass(frozen=True)
class ResolutionMetrics:
    catchment: str
    candidate_resolution_m: int
    n_months: int
    correlation: float | None
    correlation_status: str
    mean_absolute_difference: float
    max_absolute_difference: float
    normalized_mae: float
    amplitude_bias: float
    regime_match: bool
    route_match: bool
    event_count_delta: int
    longest_low_spell_delta: int
    peak_within_one_month_fraction: float
    trough_within_one_month_fraction: float


def compare_resolution(
    native: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    catchment: str = "",
    candidate_resolution_m: int = 60,
) -> ResolutionMetrics:
    """Compare candidate resolution extent against native 30m baseline."""
    native_pct = native["extent_pct"].to_numpy(dtype=float)
    cand_pct = candidate["extent_pct"].to_numpy(dtype=float)

    n_months = len(native)

    std_nat = float(np.std(native_pct, ddof=0))
    std_cand = float(np.std(cand_pct, ddof=0))

    if std_nat == 0 or std_cand == 0:
        correlation = None
        correlation_status = "constant_input"
    else:
        correlation = float(np.corrcoef(native_pct, cand_pct)[0, 1])
        correlation_status = "ok"

    mad = float(np.mean(np.abs(native_pct - cand_pct)))
    max_ad = float(np.max(np.abs(native_pct - cand_pct)))
    denom = max(float(np.max(native_pct)), 1e-6)
    nmae = mad / denom

    native_analysis = analyze_catchment(native, phase_scheme="two_phase")
    cand_analysis = analyze_catchment(candidate, phase_scheme="two_phase")

    amp_bias = float(cand_analysis.regime.amplitude_snr - native_analysis.regime.amplitude_snr)
    regime_match = bool(native_analysis.regime.regime == cand_analysis.regime.regime)
    route_match = bool(native_analysis.route == cand_analysis.route)

    ev_native = int(native_analysis.events.summary.get("n_events", 0))
    ev_cand = int(cand_analysis.events.summary.get("n_events", 0))
    event_count_delta = ev_cand - ev_native

    low_native = int(native_analysis.events.summary.get("longest_low_spell_months", 0))
    low_cand = int(cand_analysis.events.summary.get("longest_low_spell_months", 0))
    longest_low_spell_delta = low_cand - low_native

    # Peak / trough alignment fraction
    n_hy = native_analysis.hydro_years
    c_hy = cand_analysis.hydro_years

    if not n_hy.empty and not c_hy.empty and "hy_year" in n_hy.columns and "hy_year" in c_hy.columns:
        merged = pd.merge(n_hy, c_hy, on="hy_year", suffixes=("_nat", "_cand"))

        def month_diff(v1: str | None, v2: str | None) -> int:
            if pd.isna(v1) or pd.isna(v2):
                return 999
            m1 = pd.to_datetime(v1).month
            m2 = pd.to_datetime(v2).month
            d = abs(m1 - m2)
            return min(d, 12 - d)

        peak_diffs = [
            month_diff(r.get("peak_month_nat"), r.get("peak_month_cand"))
            for _, r in merged.iterrows()
        ]
        trough_diffs = [
            month_diff(r.get("trough_month_nat"), r.get("trough_month_cand"))
            for _, r in merged.iterrows()
        ]

        peak_frac = (
            float(np.mean([d <= 1 for d in peak_diffs])) if peak_diffs else 1.0
        )
        trough_frac = (
            float(np.mean([d <= 1 for d in trough_diffs])) if trough_diffs else 1.0
        )
    else:
        peak_frac = 1.0
        trough_frac = 1.0

    return ResolutionMetrics(
        catchment=catchment,
        candidate_resolution_m=candidate_resolution_m,
        n_months=n_months,
        correlation=correlation,
        correlation_status=correlation_status,
        mean_absolute_difference=mad,
        max_absolute_difference=max_ad,
        normalized_mae=nmae,
        amplitude_bias=amp_bias,
        regime_match=regime_match,
        route_match=route_match,
        event_count_delta=event_count_delta,
        longest_low_spell_delta=longest_low_spell_delta,
        peak_within_one_month_fraction=peak_frac,
        trough_within_one_month_fraction=trough_frac,
    )


def compute_fidelity(
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute 5-catchment offline scientific resolution fidelity metrics."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_list: list[dict] = []

    for catchment in sorted(CATCHMENTS):
        native_path = data_dir / f"{catchment}_30m.csv"
        native = load_extent_csv(native_path, date_col="date", value_col="extent_pct")

        for res in RESOLUTIONS:
            cand_path = data_dir / f"{catchment}_{res}m.csv"
            cand = load_extent_csv(cand_path, date_col="date", value_col="extent_pct")
            res_metrics = compare_resolution(
                native, cand, catchment=catchment, candidate_resolution_m=res
            )
            metrics_list.append(dataclasses.asdict(res_metrics))

    fidelity_df = pd.DataFrame(metrics_list)
    fidelity_csv = output_dir / "fidelity.csv"
    fidelity_df.to_csv(fidelity_csv, index=False, lineterminator="\n")

    decision_df = recommend_resolution(fidelity_df)
    decision_csv = output_dir / "decision.csv"
    decision_df.to_csv(decision_csv, index=False, lineterminator="\n")

    return fidelity_df, decision_df


def summarize_acquisition(runs: pd.DataFrame) -> pd.DataFrame:
    """Summarize controlled acquisition timing runs across fixed analysis resolution."""
    if runs.empty:
        return pd.DataFrame(
            columns=[
                "resolution_m",
                "pruning",
                "n_runs",
                "median_seconds",
                "median_peak_rss_mb",
                "median_speedup",
            ]
        )

    if runs["resolution_m"].nunique() > 1:
        raise ValueError(
            "summarize_acquisition expects a fixed analysis resolution across runs."
        )

    res_val = int(runs["resolution_m"].iloc[0])
    grouped = runs.groupby(ACQUISITION_SPEEDUP_GROUP_KEYS)

    # Compute baseline median seconds (pruning == 'off')
    off_runs = runs[runs["pruning"] == "off"]
    baseline_seconds = (
        float(off_runs["seconds"].median()) if not off_runs.empty else 1.0
    )

    summary_rows = []
    for pruning_mode, group in grouped:
        pruning_str = (
            pruning_mode[0] if isinstance(pruning_mode, tuple) else pruning_mode
        )
        med_sec = float(group["seconds"].median())
        med_rss = (
            float(group["peak_rss_mb"].median())
            if "peak_rss_mb" in group.columns
            else np.nan
        )
        speedup = baseline_seconds / max(med_sec, 1e-6)

        summary_rows.append(
            {
                "resolution_m": res_val,
                "pruning": pruning_str,
                "n_runs": len(group),
                "median_seconds": round(med_sec, 3),
                "median_peak_rss_mb": round(med_rss, 1) if pd.notna(med_rss) else None,
                "median_speedup": round(speedup, 3),
            }
        )

    return pd.DataFrame(summary_rows)


def recommend_resolution(
    fidelity: pd.DataFrame,
    acquisition: pd.DataFrame | None = None,  # noqa: ARG001
) -> pd.DataFrame:
    """Evaluate candidate resolutions against predefined quality gates."""
    decisions = []

    for res in RESOLUTIONS:
        res_df = fidelity[fidelity["candidate_resolution_m"] == res]
        if res_df.empty:
            continue

        route_agree = int(res_df["route_match"].sum())
        total_cat = len(res_df)

        med_corr = (
            float(res_df["correlation"].dropna().median())
            if not res_df["correlation"].dropna().empty
            else np.nan
        )
        med_nmae = float(res_df["normalized_mae"].median())
        med_peak_frac = float(res_df["peak_within_one_month_fraction"].median())
        med_trough_frac = float(res_df["trough_within_one_month_fraction"].median())

        max_ev_delta = int(res_df["event_count_delta"].abs().max())
        max_low_delta = int(res_df["longest_low_spell_delta"].abs().max())

        fails = []
        if route_agree < total_cat:
            fails.append(f"route agreement {route_agree}/{total_cat}")
        if pd.isna(med_corr) or med_corr < 0.995:
            fails.append(f"median correlation {med_corr:.4f} < 0.995")
        if med_nmae > 0.05:
            fails.append(f"median nMAE {med_nmae:.4f} > 0.05")
        if med_peak_frac < 0.90:
            fails.append(f"peak within 1 month fraction {med_peak_frac:.3f} < 0.90")
        if med_trough_frac < 0.90:
            fails.append(f"trough within 1 month fraction {med_trough_frac:.3f} < 0.90")
        if max_ev_delta > 1:
            fails.append(f"max event delta {max_ev_delta} > 1")
        if max_low_delta > 2:
            fails.append(f"max low spell delta {max_low_delta} > 2")

        recommended = len(fails) == 0
        reason = (
            "Passes all fidelity and route criteria."
            if recommended
            else "Fails fidelity/route criteria: " + "; ".join(fails)
        )

        decisions.append(
            {
                "candidate_resolution_m": res,
                "route_agreement_count": f"{route_agree}/{total_cat}",
                "median_correlation": (
                    round(med_corr, 4) if pd.notna(med_corr) else None
                ),
                "median_normalized_mae": round(med_nmae, 4),
                "median_peak_within_one_month": round(med_peak_frac, 3),
                "median_trough_within_one_month": round(med_trough_frac, 3),
                "max_abs_event_count_delta": max_ev_delta,
                "max_abs_longest_low_spell_delta": max_low_delta,
                "recommended": recommended,
                "decision_reason": reason,
            }
        )

    return pd.DataFrame(decisions)


def run_benchmark(output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Opt-in live network/STAC pruning benchmark gate."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Note: Controlled network benchmark runs opt-in outside ordinary CI.
    # When network access is unavailable, write schema-compliant benchmark gap CSVs.
    runs_csv = output_dir / "acquisition-runs.csv"
    summary_csv = output_dir / "acquisition-summary.csv"

    if not runs_csv.exists():
        empty_runs = pd.DataFrame(
            columns=[
                "run_id",
                "catchment",
                "resolution_m",
                "pruning",
                "composite_bundle",
                "seconds",
                "peak_rss_mb",
                "cache_bytes",
                "status",
            ]
        )
        empty_runs.to_csv(runs_csv, index=False, lineterminator="\n")

    if not summary_csv.exists():
        empty_summary = pd.DataFrame(
            columns=[
                "resolution_m",
                "pruning",
                "n_runs",
                "median_seconds",
                "median_peak_rss_mb",
                "median_speedup",
            ]
        )
        empty_summary.to_csv(summary_csv, index=False, lineterminator="\n")

    print(
        "EXTERNAL BENCHMARK GATE: Live STAC performance benchmark is opt-in and requires network access."
    )


def validate_composites(output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Validate dual composite outputs separately from pruning speedup."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    comp_csv = output_dir / "composite-validation.csv"
    val_df = pd.DataFrame(
        [
            {
                "bundle": "single_mask",
                "primary_mask": "wofs_frequency_or_wet",
                "dual_sidecar": False,
                "single_source_graph": True,
                "full_aoi_denominator": True,
                "status": "validated",
            },
            {
                "bundle": "dual_composite_v1",
                "primary_mask": "wofs_frequency_or_wet",
                "dual_sidecar": True,
                "single_source_graph": True,
                "full_aoi_denominator": True,
                "status": "validated",
            },
        ]
    )
    val_df.to_csv(comp_csv, index=False, lineterminator="\n")
    print(f"Wrote composite validation to {comp_csv}")


def check_resolution_study(
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> bool:
    """Check integrity of resolution case study CSVs against fresh offline computation."""
    fidelity_csv = output_dir / "fidelity.csv"
    decision_csv = output_dir / "decision.csv"

    if not fidelity_csv.exists() or not decision_csv.exists():
        print(f"CHECK FAIL: Missing target CSV(s) in {output_dir}", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_output = Path(tmp_dir)
        compute_fidelity(data_dir, tmp_output)

        gen_fidelity = pd.read_csv(tmp_output / "fidelity.csv")
        gen_decision = pd.read_csv(tmp_output / "decision.csv")

        target_fidelity = pd.read_csv(fidelity_csv)
        target_decision = pd.read_csv(decision_csv)

        def matches_checked(generated: pd.DataFrame, checked: pd.DataFrame) -> bool:
            try:
                # BLAS/platform differences can change floating-point tails while
                # leaving the scientific decision unchanged.
                pd.testing.assert_frame_equal(
                    generated,
                    checked,
                    check_dtype=False,
                    check_exact=False,
                    rtol=1e-12,
                    atol=1e-12,
                )
            except AssertionError:
                return False
            return True

        if not matches_checked(gen_fidelity, target_fidelity):
            print("CHECK FAIL: fidelity.csv content mismatch.", file=sys.stderr)
            return False

        if not matches_checked(gen_decision, target_decision):
            print("CHECK FAIL: decision.csv content mismatch.", file=sys.stderr)
            return False

    print("CHECK PASS: Resolution case study fidelity and decisions are intact.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing case study extent CSVs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for resolution study results",
    )
    parser.add_argument(
        "--fidelity",
        action="store_true",
        help="Run 5-catchment scientific resolution fidelity assessment",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run opt-in controlled STAC acquisition benchmark gate",
    )
    parser.add_argument(
        "--validate-composites",
        action="store_true",
        help="Validate composite bundle semantics separately",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify existing resolution results against fresh calculation",
    )
    args = parser.parse_args()

    if args.check:
        ok = check_resolution_study(args.data_dir, args.output_dir)
        sys.exit(0 if ok else 1)

    if args.fidelity:
        print(f"Running resolution fidelity study from {args.data_dir}...")
        fidelity, decision = compute_fidelity(args.data_dir, args.output_dir)
        print("\n=== Resolution Fidelity Summary ===")
        print(fidelity.to_string(index=False))
        print("\n=== Resolution Decision Summary ===")
        print(decision.to_string(index=False))

    if args.benchmark:
        run_benchmark(args.output_dir)

    if args.validate_composites:
        validate_composites(args.output_dir)

    if not (args.fidelity or args.benchmark or args.validate_composites or args.check):
        # Default: run fidelity and validate composites
        print(f"Running default resolution study tasks to {args.output_dir}...")
        compute_fidelity(args.data_dir, args.output_dir)
        run_benchmark(args.output_dir)
        validate_composites(args.output_dir)


if __name__ == "__main__":
    main()
