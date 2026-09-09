"""Development-only impact audit of frozen recurrence policy against legacy outputs.

Compares production analysis under the selected recurrence policy against
stored legacy outputs across inspected stress records and protected catchments.
Selection use of this report or any data inside it is strictly forbidden.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from hydroseason import (
    _scientific_defaults as defaults,  # noqa: E402
    analyze_catchment,  # noqa: E402
)
from scripts.build_timing_identifiability_cohort import (  # noqa: E402
    KNOWN_DECISION_COLUMNS,
    discover_bundles,
    strip_decision_columns,
)

ANNUAL_FIELDS = (
    "peak_timing_status",
    "peak_interval_start",
    "peak_interval_end",
    "trough_timing_status",
    "trough_interval_start",
    "trough_interval_end",
    "timing_status",
    "status_reason",
    "boundary_status",
    "confidence",
    "baseline_uncertain",
)
RECORD_FIELDS = ("route", "route_reason", "publication_category")

MOTIVATING_STATION_IDS = ("130413a", "130407a", "130302a")
PROTECTED_CATCHMENT_KEYS = (
    "daly_river_nt",
    "fitzroy_river_wa",
    "gilbert_river_qld",
    "lachlan_river_nsw",
    "moonie_river_qld_nsw",
)


def _field_column(df: pd.DataFrame, field: str) -> str | None:
    if field in df.columns:
        return field
    alias = f"{field}_date"
    if alias in df.columns:
        return alias
    return None


def _normalize_value(val: Any) -> Any:
    if pd.isna(val) or val is None or val is pd.NaT:
        return None
    if isinstance(val, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(val).strftime("%Y-%m-%d")
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.floating, float)):
        return float(val)
    val_str = str(val).strip()
    if val_str == "" or val_str.lower() in ("nan", "nat", "none"):
        return None
    return val_str


def compare_annual_rows(
    station_id: str,
    legacy: pd.DataFrame,
    selected: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Compare annual extrema, status, and baseline fields between legacy and selected."""
    changes: list[dict[str, Any]] = []
    if (
        legacy.empty
        or selected.empty
        or "hy_year" not in legacy.columns
        or "hy_year" not in selected.columns
    ):
        return changes

    legacy_by_year = legacy.set_index("hy_year")
    selected_by_year = selected.set_index("hy_year")
    common_years = sorted(set(legacy_by_year.index).intersection(selected_by_year.index))

    for year in common_years:
        leg_row = legacy_by_year.loc[year]
        sel_row = selected_by_year.loc[year]
        if isinstance(leg_row, pd.DataFrame):
            leg_row = leg_row.iloc[0]
        if isinstance(sel_row, pd.DataFrame):
            sel_row = sel_row.iloc[0]

        for field in ANNUAL_FIELDS:
            leg_col = _field_column(legacy, field)
            sel_col = _field_column(selected, field)
            if leg_col is None or sel_col is None:
                continue
            leg_val = _normalize_value(leg_row[leg_col])
            sel_val = _normalize_value(sel_row[sel_col])
            if leg_val != sel_val:
                changes.append(
                    {
                        "station_id": station_id,
                        "hy_year": int(year),
                        "field": field,
                        "legacy": leg_val,
                        "selected": sel_val,
                    }
                )
    return changes


def compare_record_fields(
    station_id: str,
    legacy: dict[str, Any],
    selected: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare record-level fields (route, route_reason, publication_category)."""
    changes: list[dict[str, Any]] = []
    for field in RECORD_FIELDS:
        if field not in legacy or field not in selected:
            continue
        leg_val = _normalize_value(legacy[field])
        sel_val = _normalize_value(selected[field])
        if leg_val is not None and sel_val is not None and leg_val != sel_val:
            changes.append(
                {
                    "station_id": station_id,
                    "field": field,
                    "legacy": leg_val,
                    "selected": sel_val,
                }
            )
    return changes


def compute_publication_category(analysis: Any) -> str:
    """Map the analysis record-level claim onto the publication category."""
    if analysis.regime.regime == "insufficient_record":
        return "unobservable"
    if analysis.regime.timing_evidence != "supported":
        return "event_only"
    hydro_years = analysis.hydro_years
    if hydro_years is not None and not hydro_years.empty and "timing_status" in hydro_years.columns:
        statuses = hydro_years["timing_status"].dropna()
        if not statuses.empty:
            dominant = statuses.value_counts().idxmax()
            if dominant == "point":
                return "point_supported"
            if dominant == "interval":
                return "interval_supported"
    return "event_only"


def _legacy_publication_category(regime: str | None, timing_evidence: str | None, hydro_years: pd.DataFrame | None) -> str | None:
    if regime is None:
        return None
    if regime == "insufficient_record":
        return "unobservable"
    if timing_evidence is not None and timing_evidence != "supported":
        return "event_only"
    if hydro_years is not None and not hydro_years.empty and "timing_status" in hydro_years.columns:
        statuses = hydro_years["timing_status"].dropna()
        if not statuses.empty:
            dominant = statuses.value_counts().idxmax()
            if dominant == "point":
                return "point_supported"
            if dominant == "interval":
                return "interval_supported"
    return "event_only"


def _station_id_from_bundle(bundle_dir: Path) -> str:
    return bundle_dir.name.split("-", 1)[0].casefold()


def audit_impact(
    *,
    stress_root: Path,
    protected_root: Path,
    legacy_results_root: Path,
    cohort_manifest: Path,
) -> dict[str, Any]:
    # 1. Load cohort manifest
    manifest_df = pd.read_csv(cohort_manifest)
    cohort_ids = set(manifest_df["station_id"].astype(str).str.casefold())

    # Try loading stress summary if present in legacy root or parent
    legacy_summary_lookup: dict[str, dict[str, Any]] = {}
    for candidate_summary in (
        legacy_results_root / "stress-test-full-results.csv",
        legacy_results_root.parent / "stress-test-full-results.csv",
    ):
        if candidate_summary.exists():
            sum_df = pd.read_csv(candidate_summary)
            if "station_id" in sum_df.columns:
                for _, r in sum_df.iterrows():
                    legacy_summary_lookup[str(r["station_id"]).casefold()] = dict(r)
            break

    # Discover stress records
    stress_bundles = discover_bundles(stress_root) if stress_root.exists() else []

    all_annual_changes: list[dict[str, Any]] = []
    all_record_changes: list[dict[str, Any]] = []

    missing_sources = 0
    missing_legacy_artifacts = 0

    record_catalog: list[dict[str, Any]] = []

    # Process Stress Records
    for bundle in stress_bundles:
        sid = _station_id_from_bundle(bundle)
        is_motivating = sid in MOTIVATING_STATION_IDS
        in_cohort = sid in cohort_ids
        is_protected = False

        monthly_path = bundle / f"{bundle.name}_monthly.csv"
        if not monthly_path.exists():
            missing_sources += 1
            record_catalog.append({
                "station_id": sid,
                "bundle": bundle.name,
                "group": "stress",
                "source_exists": False,
                "legacy_artifact_exists": False,
                "in_cohort": in_cohort,
                "is_motivating": is_motivating,
                "is_protected": is_protected,
            })
            continue

        raw_df = pd.read_csv(monthly_path)
        stripped = strip_decision_columns(raw_df, source=str(monthly_path))
        selected_analysis = analyze_catchment(stripped)

        selected_record_dict = {
            "route": selected_analysis.route,
            "route_reason": selected_analysis.route_reason,
            "publication_category": compute_publication_category(selected_analysis),
        }

        # Find matching legacy artifact
        legacy_artifact_candidates = [
            legacy_results_root / bundle.name / f"{bundle.name}_hydro_years.csv",
            legacy_results_root / f"{bundle.name}_hydro_years.csv",
            legacy_results_root / f"{sid}_hydro_years.csv",
        ]
        legacy_hy_path = next((p for p in legacy_artifact_candidates if p.exists()), None)
        legacy_artifact_exists = legacy_hy_path is not None

        ann_diffs: list[dict[str, Any]] = []
        rec_diffs: list[dict[str, Any]] = []

        if not legacy_artifact_exists:
            missing_legacy_artifacts += 1
        else:
            legacy_hy = pd.read_csv(legacy_hy_path)
            ann_diffs = compare_annual_rows(sid, legacy_hy, selected_analysis.hydro_years)
            all_annual_changes.extend(ann_diffs)

            legacy_sum = legacy_summary_lookup.get(sid, {})
            legacy_route = (
                legacy_hy["route"].iloc[0]
                if "route" in legacy_hy.columns and not legacy_hy.empty
                else legacy_sum.get("route")
            )
            legacy_regime = (
                legacy_hy["regime"].iloc[0]
                if "regime" in legacy_hy.columns and not legacy_hy.empty
                else legacy_sum.get("regime")
            )
            legacy_timing_ev = legacy_sum.get("timing_evidence")
            legacy_pub_cat = _legacy_publication_category(legacy_regime, legacy_timing_ev, legacy_hy)

            legacy_record_dict = {
                "route": legacy_route,
                "route_reason": None,  # Not recorded in legacy stress artifact
                "publication_category": legacy_pub_cat,
            }
            rec_diffs = compare_record_fields(sid, legacy_record_dict, selected_record_dict)
            all_record_changes.extend(rec_diffs)

        record_catalog.append({
            "station_id": sid,
            "bundle": bundle.name,
            "group": "stress",
            "source_exists": True,
            "legacy_artifact_exists": legacy_artifact_exists,
            "in_cohort": in_cohort,
            "is_motivating": is_motivating,
            "is_protected": is_protected,
            "annual_changes_count": len(ann_diffs),
            "record_changes_count": len(rec_diffs),
        })

    # Process Protected Catchments
    for p_key in PROTECTED_CATCHMENT_KEYS:
        sid = p_key
        is_motivating = False
        in_cohort = False
        is_protected = True

        # Candidate source files
        source_candidates = [
            protected_root / f"{p_key}_30m.csv",
            protected_root / f"{p_key}.csv",
            protected_root / f"{p_key}_300m.csv",
        ]
        source_path = next((p for p in source_candidates if p.exists()), None)
        source_exists = source_path is not None

        if not source_exists:
            missing_sources += 1
            record_catalog.append({
                "station_id": sid,
                "bundle": p_key,
                "group": "protected",
                "source_exists": False,
                "legacy_artifact_exists": False,
                "in_cohort": in_cohort,
                "is_motivating": is_motivating,
                "is_protected": is_protected,
            })
            continue

        raw_df = pd.read_csv(source_path)
        # Check if decision columns present
        decision_cols_present = [c for c in raw_df.columns if c in KNOWN_DECISION_COLUMNS]
        if decision_cols_present:
            stripped = strip_decision_columns(raw_df, source=str(source_path))
        else:
            stripped = raw_df
        selected_analysis = analyze_catchment(stripped)

        # Check for legacy artifact
        legacy_artifact_candidates = [
            legacy_results_root / p_key / f"{p_key}_hydro_years.csv",
            legacy_results_root / f"{p_key}_hydro_years.csv",
        ]
        legacy_hy_path = next((p for p in legacy_artifact_candidates if p.exists()), None)
        legacy_artifact_exists = legacy_hy_path is not None

        ann_diffs = []
        rec_diffs = []
        if not legacy_artifact_exists:
            missing_legacy_artifacts += 1
        else:
            legacy_hy = pd.read_csv(legacy_hy_path)
            ann_diffs = compare_annual_rows(sid, legacy_hy, selected_analysis.hydro_years)
            all_annual_changes.extend(ann_diffs)

        record_catalog.append({
            "station_id": sid,
            "bundle": p_key,
            "group": "protected",
            "source_exists": True,
            "legacy_artifact_exists": legacy_artifact_exists,
            "in_cohort": in_cohort,
            "is_motivating": is_motivating,
            "is_protected": is_protected,
            "annual_changes_count": len(ann_diffs),
            "record_changes_count": len(rec_diffs),
        })

    # Breakdown counts
    field_counts = Counter(c["field"] for c in all_annual_changes)
    station_counts = Counter(c["station_id"] for c in all_annual_changes)
    year_counts = Counter(str(c["hy_year"]) for c in all_annual_changes)

    def _cohort_membership(station_id: str) -> str:
        return "in_cohort" if station_id in cohort_ids else "not_in_cohort"

    def _motivating_status(station_id: str) -> str:
        return "motivating" if station_id in MOTIVATING_STATION_IDS else "non_motivating"

    def _protected_status(station_id: str) -> str:
        return "protected" if station_id in PROTECTED_CATCHMENT_KEYS else "non_protected"

    cohort_changes = Counter(_cohort_membership(c["station_id"]) for c in all_annual_changes)
    motivating_changes = Counter(_motivating_status(c["station_id"]) for c in all_annual_changes)
    protected_changes = Counter(_protected_status(c["station_id"]) for c in all_annual_changes)

    report = {
        "selection_use": "forbidden",
        "timing_identifiability_fingerprint": defaults.TIMING_IDENTIFIABILITY_FINGERPRINT,
        "recurrence_fingerprint": defaults.RECURRENCE_FINGERPRINT,
        "selected_policy": defaults.RECURRENCE_POLICY,
        "counts": {
            "stress_records": len(stress_bundles),
            "protected_catchments": len(PROTECTED_CATCHMENT_KEYS),
            "motivating_ids": len(MOTIVATING_STATION_IDS),
            "cohort_ids": len(cohort_ids),
            "missing_sources": missing_sources,
            "missing_legacy_artifacts": missing_legacy_artifacts,
            "total_annual_changes": len(all_annual_changes),
            "total_record_changes": len(all_record_changes),
        },
        "counts_by_source_group": {
            "stress": {
                "records": len(stress_bundles),
                "annual_changes": sum(
                    r["annual_changes_count"] for r in record_catalog if r["group"] == "stress"
                ),
                "record_changes": sum(
                    r["record_changes_count"] for r in record_catalog if r["group"] == "stress"
                ),
                "missing_artifacts": sum(
                    1 for r in record_catalog if r["group"] == "stress" and not r["legacy_artifact_exists"]
                ),
            },
            "protected": {
                "records": len(PROTECTED_CATCHMENT_KEYS),
                "annual_changes": sum(
                    r["annual_changes_count"] for r in record_catalog if r["group"] == "protected"
                ),
                "record_changes": sum(
                    r["record_changes_count"] for r in record_catalog if r["group"] == "protected"
                ),
                "missing_artifacts": sum(
                    1 for r in record_catalog if r["group"] == "protected" and not r["legacy_artifact_exists"]
                ),
            },
        },
        "counts_by_field": dict(field_counts),
        "counts_by_station": dict(station_counts),
        "counts_by_year": dict(year_counts),
        "counts_by_cohort_membership": {
            "in_cohort": {
                "records": len(cohort_ids),
                "annual_changes": cohort_changes["in_cohort"],
            },
            "not_in_cohort": {
                "records": (len(stress_bundles) + len(PROTECTED_CATCHMENT_KEYS)) - len(cohort_ids),
                "annual_changes": cohort_changes["not_in_cohort"],
            },
        },
        "counts_by_motivating_status": {
            "motivating": {
                "records": len(MOTIVATING_STATION_IDS),
                "annual_changes": motivating_changes["motivating"],
            },
            "non_motivating": {
                "records": (len(stress_bundles) + len(PROTECTED_CATCHMENT_KEYS)) - len(MOTIVATING_STATION_IDS),
                "annual_changes": motivating_changes["non_motivating"],
            },
        },
        "counts_by_protected_status": {
            "protected": {
                "records": len(PROTECTED_CATCHMENT_KEYS),
                "annual_changes": protected_changes["protected"],
            },
            "non_protected": {
                "records": len(stress_bundles),
                "annual_changes": protected_changes["non_protected"],
            },
        },
        "records": record_catalog,
        "annual_changes": all_annual_changes,
        "record_changes": all_record_changes,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stress-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, required=True)
    parser.add_argument("--legacy-results-root", type=Path, required=True)
    parser.add_argument("--cohort-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = audit_impact(
        stress_root=args.stress_root,
        protected_root=args.protected_root,
        legacy_results_root=args.legacy_results_root,
        cohort_manifest=args.cohort_manifest,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote recurrence impact report to {args.output}")


if __name__ == "__main__":
    main()
