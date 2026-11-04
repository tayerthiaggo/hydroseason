"""Before/after check of hydroseason-v0.3.0 on the five case-study catchments.

Stages:

    run      analyse every committed case-study extent series (5 catchments x 4
             resolutions) with whichever HydroSeason is importable, and write the
             hydro-years, monthly phase and summary tables, plus the full report
             for each 30 m series
    compare  compare two run directories column by column and write compare.json

Run it once per library, choosing the library with PYTHONPATH, for example:

    PYTHONPATH=<0.2.0 checkout> python scripts/v030_case_study_comparison.py run --out <dir>/v0.2.0
    PYTHONPATH=<0.3.0 checkout> python scripts/v030_case_study_comparison.py run --out <dir>/v0.3.0
    python scripts/v030_case_study_comparison.py compare --before <dir>/v0.2.0 --after <dir>/v0.3.0

The 0.3.0 proposal (docs/handoff/2026-11-04-v0.3.0-proposal.md) says which columns may
differ; every other column must be identical.
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "case_studies" / "data" / "extent"
CATCHMENTS = {
    "daly_river_nt": "Daly River (NT)",
    "fitzroy_river_wa": "Fitzroy River (WA)",
    "gilbert_river_qld": "Gilbert River (QLD)",
    "lachlan_river_nsw": "Lachlan River (NSW)",
    "moonie_river_qld_nsw": "Moonie River (QLD/NSW)",
}
RESOLUTIONS = ("30m", "60m", "90m", "300m")

# Columns the proposal allows to differ. B: the trough label; C: the condition baseline.
LABEL_COLUMNS = {"trough_timing_status", "trough_interval_start", "trough_interval_end", "timing_status"}
CONDITION_COLUMNS = {
    "baseline_eligible", "baseline_n", "baseline_mode", "baseline_uncertain", "peak_percentile",
    "trough_percentile", "recharge_condition", "refuge_condition", "annual_condition",
    "recharge_condition_qualified", "refuge_condition_qualified", "annual_condition_qualified",
    "consecutive_dry_cycles", "consecutive_wet_cycles",
}
ALLOWED = LABEL_COLUMNS | CONDITION_COLUMNS
SUMMARY_ALLOWED = {"method_policy_id", "method_policy_fingerprint", "library_file"}


def stage_run(out: Path) -> None:
    import hydroseason
    from hydroseason import analyze_catchment, generate_catchment_report, load_extent_csv

    out.mkdir(parents=True, exist_ok=True)
    for key, name in CATCHMENTS.items():
        for resolution in RESOLUTIONS:
            extent = load_extent_csv(DATA / f"{key}_{resolution}.csv", date_col="date", value_col="extent_pct")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                analysis = analyze_catchment(extent, phase_scheme="two_phase", quality_policy="flag")
            stem = out / f"{key}_{resolution}"
            analysis.hydro_years.to_csv(f"{stem}_hydro_years.csv", index=False)
            if analysis.monthly_phase is not None:
                analysis.monthly_phase.to_csv(f"{stem}_monthly_phase.csv")
            summary = {
                "key": key, "resolution": resolution, "route": analysis.route,
                "route_reason": analysis.route_reason, "regime": analysis.regime.regime,
                "n_hydro_years": int(len(analysis.hydro_years)),
                "method_policy_id": analysis.method_policy_id,
                "method_policy_fingerprint": analysis.method_policy_fingerprint,
                "library_file": hydroseason.__file__,
                "warnings": sorted({str(w.message) for w in caught}),
            }
            Path(f"{stem}_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            if resolution == "30m":
                generate_catchment_report(
                    extent, out / "reports" / key, name=key, analysis=analysis, title=name,
                    subtitle=f"Whole-catchment monthly surface-water extent, 2005-2025 ({analysis.method_policy_id})",
                )
            print(f"{key} {resolution}: {analysis.route}, {len(analysis.hydro_years)} years, "
                  f"{analysis.method_policy_id}", flush=True)


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:  # event-routed records have no hydro-years rows
        return pd.DataFrame()


def _same(a: pd.Series, b: pd.Series) -> pd.Series:
    both_missing = a.isna() & b.isna()
    equal = a.astype(str).eq(b.astype(str))
    numeric_a, numeric_b = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
    close = np.isclose(numeric_a, numeric_b, rtol=0, atol=1e-9, equal_nan=False)
    return both_missing | equal | pd.Series(close, index=a.index)


def _compare_frames(before: pd.DataFrame, after: pd.DataFrame, allowed: set[str]) -> dict:
    out: dict = {"rows": [len(before), len(after)], "columns_only_before": sorted(set(before) - set(after)),
                 "columns_only_after": sorted(set(after) - set(before)), "changed": {}, "unexpected": {}}
    if len(before) != len(after):
        out["unexpected"]["row_count"] = [len(before), len(after)]
        return out
    for column in [c for c in before.columns if c in after.columns]:
        same = _same(before[column].reset_index(drop=True), after[column].reset_index(drop=True))
        n = int((~same).sum())
        if n:
            (out["changed"] if column in allowed else out["unexpected"])[column] = n
    return out


def stage_compare(before: Path, after: Path) -> None:
    result: dict = {"before": str(before), "after": str(after), "series": {}}
    for key in CATCHMENTS:
        for resolution in RESOLUTIONS:
            stem = f"{key}_{resolution}"
            entry: dict = {}
            sb = json.loads((before / f"{stem}_summary.json").read_text(encoding="utf-8"))
            sa = json.loads((after / f"{stem}_summary.json").read_text(encoding="utf-8"))
            entry["summary_changed"] = sorted(k for k in sb if sb[k] != sa.get(k) and k in SUMMARY_ALLOWED)
            entry["summary_unexpected"] = sorted(k for k in sb if sb[k] != sa.get(k) and k not in SUMMARY_ALLOWED)
            entry["policy"] = [sb["method_policy_id"], sa["method_policy_id"]]
            entry["route"] = sa["route"]
            hb = _read(before / f"{stem}_hydro_years.csv")
            ha = _read(after / f"{stem}_hydro_years.csv")
            entry["hydro_years"] = _compare_frames(hb, ha, ALLOWED)
            if (before / f"{stem}_monthly_phase.csv").exists():
                mb = _read(before / f"{stem}_monthly_phase.csv")
                ma = _read(after / f"{stem}_monthly_phase.csv")
                entry["monthly_phase"] = _compare_frames(mb, ma, set())
            for frame, name in ((hb, "before"), (ha, "after")):
                if len(frame) and "baseline_eligible" in frame:
                    entry[f"eligible_{name}"] = int(frame["baseline_eligible"].fillna(False).astype(bool).sum())
                    labelled = frame["recharge_condition"].isin(["low", "typical", "high"])
                    entry[f"labelled_{name}"] = int(labelled.sum())
            result["series"][stem] = entry
    reports_b, reports_a = before / "reports", after / "reports"
    result["report_tables"] = {}
    for path in sorted(reports_b.rglob("*.csv")):
        other = reports_a / path.relative_to(reports_b)
        if other.exists():
            result["report_tables"][str(path.relative_to(reports_b))] = _compare_frames(
                _read(path), _read(other), ALLOWED | {"trough_date", "trough_interval_start_date",
                                                                   "trough_interval_end_date"})
    unexpected = {k: v for k, v in result["series"].items()
                  if v["summary_unexpected"] or v["hydro_years"]["unexpected"]
                  or v.get("monthly_phase", {}).get("unexpected")}
    unexpected.update({k: v for k, v in result["report_tables"].items() if v["unexpected"]})
    result["unexpected_differences"] = sorted(unexpected)
    (after.parent / "compare.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"compare: {len(result['series'])} series; unexpected differences in {sorted(unexpected) or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["run", "compare"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    args = parser.parse_args()
    if args.stage == "run":
        stage_run(args.out)
    else:
        stage_compare(args.before, args.after)


if __name__ == "__main__":
    main()
