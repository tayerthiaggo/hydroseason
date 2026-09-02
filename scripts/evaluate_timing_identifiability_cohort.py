"""One-pass evaluation of the blinded real-catchment timing-identifiability cohort.

Loads the frozen manifest and reviewer labels, runs the frozen v0.2.0
challenger policy on each cohort record's raw source (never on the blinded
packet -- the reviewer labels the packet; the evaluator re-attaches the
station identity only after labels are frozen), and reports confusion tables,
Wilson intervals, per-stratum outcomes, and every disagreement. It never
searches thresholds and never writes ``_scientific_defaults.py`` or any
threshold file.

"Old" below means the pre-v0.2.0 published rule exactly as it existed before
this plan's timing-identifiability gate was added: route is
``per_year_detection`` whenever regime is seasonal or marginal, with no
timing-evidence gate at all. That rule is reconstructed from the current
regime label rather than re-executing retired code, since the regime
classifier itself is unchanged by this plan (only the routing decision that
consumes it changed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from hydroseason._calibration import wilson_interval  # noqa: E402
from hydroseason._catchment import analyze_catchment  # noqa: E402
from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS  # noqa: E402

VALID_LABELS = (
    "point_supported", "interval_supported", "event_only", "unobservable", "uncertain",
)


class LabelFileChangedError(ValueError):
    """The review-labels file's SHA-256 no longer matches the one recorded in the manifest."""


def _sha256_of_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_hash_path(labels_path: Path) -> Path:
    return labels_path.with_suffix(labels_path.suffix + ".sha256")


def freeze_labels_hash(labels_path: Path) -> str:
    """Record the review-labels file's SHA-256 the first time it is evaluated.

    A later evaluation of the same ``labels_path`` whose content no longer
    matches this recorded hash raises: once labels are frozen for review,
    they must not be silently edited after the fact.
    """
    digest = _sha256_of_file(labels_path)
    hash_path = _frozen_hash_path(labels_path)
    if hash_path.exists():
        recorded = hash_path.read_text(encoding="utf-8").strip()
        if recorded != digest:
            raise LabelFileChangedError(
                f"{labels_path} has changed since its SHA-256 was frozen "
                f"(recorded {recorded}, now {digest}); review labels are "
                "immutable once frozen."
            )
    else:
        hash_path.write_text(digest, encoding="utf-8")
    return digest


def load_manifest(manifest_path: Path) -> pd.DataFrame:
    return pd.read_csv(manifest_path)


def load_labels(labels_path: Path) -> pd.DataFrame:
    labels = pd.read_csv(labels_path)
    invalid = set(labels["label"].astype(str)) - set(VALID_LABELS)
    if invalid:
        raise ValueError(f"invalid label(s) in {labels_path}: {sorted(invalid)}")
    if labels["station_id"].duplicated().any():
        dupes = labels.loc[labels["station_id"].duplicated(), "station_id"].tolist()
        raise ValueError(f"duplicate station_id in {labels_path}: {dupes}")
    return labels


def _old_route(regime: str) -> str:
    """Reconstruct the pre-v0.2.0 route rule: no timing-evidence gate."""
    return "per_year_detection" if regime in {"seasonal", "marginal"} else "event_characterisation"


def _new_publication_category(analysis) -> str:
    """Map the challenger's actual record-level claim onto the rubric's space.

    A reviewer judges the whole record, not one lucky year, so the mapping
    must not either: a record where only a handful of 21 years happen to
    resolve to "point" while most are "unresolved" is not a record whose
    *timing is supported* -- it is exactly the "route on identifiable annual
    timing" gate's job to withhold that claim, and ``timing_evidence``
    already encodes it. "supported" is required before a record is even
    routed to ``per_year_detection`` with a point/interval claim at all
    (``timing_evidence`` gates ``supports_per_year_boundaries``), so it is
    the correct record-level signal here: "insufficient"/"unsupported" both
    mean no timing claim survives to publication, i.e. "event_only" (or
    "unobservable" when there is no usable record whatsoever).
    """
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


def _load_source_frame(station_id: str, stress_root: Path | None) -> pd.DataFrame | None:
    """Re-locate a cohort record's full raw source by station id, for evaluation only.

    Only called after labels are frozen. Returns ``None`` if the source
    cannot be found (the manifest's own diagnostics still allow reporting).
    """
    if stress_root is None or not stress_root.exists():
        return None
    matches = [p for p in stress_root.iterdir() if p.is_dir() and p.name.casefold().startswith(station_id)]
    if not matches:
        return None
    monthly_path = matches[0] / f"{matches[0].name}_monthly.csv"
    if not monthly_path.exists():
        return None
    raw = pd.read_csv(monthly_path, parse_dates=["date"])
    known_decision_columns = {
        "regime", "route", "confidence", "phase", "phase_status", "hy_year",
        "usable_month", "is_hy_peak", "is_hy_mid_dry", "is_hy_trough",
        "in_wet_event", "wet_event_id", "in_low_spell", "low_spell_id",
        "baseline_extent_pct",
    }
    observation_columns = [c for c in raw.columns if c not in known_decision_columns]
    return raw.loc[:, observation_columns].set_index("date")


def evaluate(
    *,
    manifest: pd.DataFrame,
    labels: pd.DataFrame,
    stress_root: Path | None,
) -> dict:
    joined = manifest.merge(labels, on="station_id", how="left", validate="one_to_one")
    missing_labels = joined.loc[joined["label"].isna(), "station_id"].tolist()

    rows = []
    for record in joined.itertuples():
        source = _load_source_frame(record.station_id, stress_root)
        if source is None:
            rows.append({
                "station_id": record.station_id,
                "stratum": record.stratum,
                "reviewer_label": record.label if pd.notna(record.label) else None,
                "new_category": None,
                "old_route": None,
                "new_route": None,
                "regime": None,
                "evaluated": False,
            })
            continue
        analysis = analyze_catchment(source)
        rows.append({
            "station_id": record.station_id,
            "stratum": record.stratum,
            "reviewer_label": record.label if pd.notna(record.label) else None,
            "new_category": _new_publication_category(analysis),
            "old_route": _old_route(analysis.regime.regime),
            "new_route": analysis.route,
            "regime": analysis.regime.regime,
            "evaluated": True,
        })

    results = pd.DataFrame(rows)
    evaluated = results.loc[results["evaluated"]]
    rated = evaluated.loc[evaluated["reviewer_label"].notna() & (evaluated["reviewer_label"] != "uncertain")]

    confusion = (
        rated.groupby(["reviewer_label", "new_category"]).size().reset_index(name="count")
        if not rated.empty else pd.DataFrame(columns=["reviewer_label", "new_category", "count"])
    )

    def _rate(mask_agree: pd.Series, n: int) -> dict:
        k = int(mask_agree.sum())
        low, high = wilson_interval(k, n) if n else (0.0, 1.0)
        return {"k": k, "n": n, "rate": (k / n if n else None), "wilson_low": low, "wilson_high": high}

    n_rated = len(rated)
    agreement = (
        (rated["reviewer_label"] == rated["new_category"]) if not rated.empty
        else pd.Series(dtype=bool)
    )

    # False precise-boundary: reviewer said the record does NOT support a point
    # date, but the challenger published one anyway.
    false_point_mask = (
        (rated["reviewer_label"] != "point_supported") & (rated["new_category"] == "point_supported")
        if not rated.empty else pd.Series(dtype=bool)
    )

    quota = 8
    per_stratum = {
        stratum: {
            "n": int((results["stratum"] == stratum).sum()),
            "n_rated": int((rated["stratum"] == stratum).sum()) if not rated.empty else 0,
            "shortfall": max(0, quota - int((results["stratum"] == stratum).sum())),
        }
        for stratum in sorted(results["stratum"].dropna().unique())
    }

    disagreements = (
        rated.loc[rated["reviewer_label"] != rated["new_category"]]
        [["station_id", "stratum", "reviewer_label", "new_category", "old_route", "new_route", "regime"]]
        .to_dict("records")
        if not rated.empty else []
    )

    n_uncertain = int((evaluated["reviewer_label"] == "uncertain").sum())
    n_missing_labels = len(missing_labels)

    route_changes = evaluated.loc[
        evaluated["old_route"].notna() & (evaluated["old_route"] != evaluated["new_route"])
    ][["station_id", "stratum", "old_route", "new_route", "regime"]].to_dict("records")

    report = {
        "threshold_fingerprint_source": "TIMING_IDENTIFIABILITY_DEFAULTS (loaded, never reselected)",
        "thresholds": {
            "min_amplitude_to_floor_ratio": TIMING_IDENTIFIABILITY_DEFAULTS.min_amplitude_to_floor_ratio,
            "min_peak_water_pixels": TIMING_IDENTIFIABILITY_DEFAULTS.min_peak_water_pixels,
            "max_point_span_months": TIMING_IDENTIFIABILITY_DEFAULTS.max_point_span_months,
            "max_boundary_interval_months": TIMING_IDENTIFIABILITY_DEFAULTS.max_boundary_interval_months,
            "min_informative_years": TIMING_IDENTIFIABILITY_DEFAULTS.min_informative_years,
        },
        "n_cohort_records": int(len(manifest)),
        "n_evaluated": int(evaluated.shape[0]),
        "n_missing_source": int((~results["evaluated"]).sum()),
        "n_missing_labels": n_missing_labels,
        "missing_label_station_ids": missing_labels,
        "n_uncertain_excluded": n_uncertain,
        "n_rated": n_rated,
        "overall_agreement": _rate(agreement, n_rated),
        "false_precise_boundary": _rate(false_point_mask, n_rated),
        "confusion_table": confusion.to_dict("records"),
        "per_stratum": per_stratum,
        "old_vs_new_route_changes": route_changes,
        "n_route_changes": len(route_changes),
        "disagreements": disagreements,
        "n_disagreements": len(disagreements),
        "known_limitations": {
            "per_stratum_shortfall": {
                stratum: report["shortfall"] for stratum, report in per_stratum.items()
            },
            "pixel_support_status": (
                sorted(set(manifest["pixel_support_status"]))
                if "pixel_support_status" in manifest.columns else []
            ),
            "min_peak_water_pixels_evidence_basis": (
                "synthetic-only: every cohort record reports "
                "pixel_support_status=\"unavailable\", so this threshold's "
                "detectability condition is never exercised on real data"
                if "pixel_support_status" in manifest.columns
                and set(manifest["pixel_support_status"]) == {"unavailable"}
                else "mixed: some cohort records carry pixel counts"
            ),
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--stress-root", type=Path, default=None,
        help="Root directory to re-locate each cohort record's raw source for evaluation.",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    labels = load_labels(args.labels)
    report = evaluate(manifest=manifest, labels=labels, stress_root=args.stress_root)
    report["labels_sha256"] = freeze_labels_hash(args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
