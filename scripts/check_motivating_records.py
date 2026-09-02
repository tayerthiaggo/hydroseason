"""Read-only qualitative acceptance check for the three motivating records.

130413A Denison Creek at Braeside, 130407A Nebo Creek at Nebo, and 130302A
Dawson River at Taroom are diagnostic examples this plan exists to protect
(see the plan's Global Constraints) -- never threshold-selection or
untouched-validation records. This script re-runs ``analyze_catchment()`` on
each record's stripped observation columns and asserts qualitative behavior
only, never threshold-fitted exact numbers, and never a station-specific
code path.
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

from hydroseason._catchment import analyze_catchment  # noqa: E402

KNOWN_DECISION_COLUMNS = (
    "regime", "route", "confidence", "phase", "phase_status", "hy_year",
    "usable_month", "is_hy_peak", "is_hy_mid_dry", "is_hy_trough",
    "in_wet_event", "wet_event_id", "in_low_spell", "low_spell_id",
    "baseline_extent_pct",
)
COUNT_COLUMNS = ("n_water", "n_valid", "n_invalid", "n_aoi")

STATIONS = {
    "130413a": "Denison Creek at Braeside",
    "130407a": "Nebo Creek at Nebo",
    "130302a": "Dawson River at Taroom",
}


class MotivatingRecordCheckFailure(AssertionError):
    """A named qualitative assertion failed for a motivating record."""


def _station_slug(bundle_dir: Path) -> str:
    return bundle_dir.name.split("-", 1)[0].casefold()


def find_bundle(stress_root: Path, station_id: str) -> Path:
    station_id = station_id.casefold()
    matches = [
        p for p in stress_root.iterdir()
        if p.is_dir() and _station_slug(p) == station_id
    ]
    if not matches:
        raise FileNotFoundError(f"no bundle directory found for station {station_id!r} under {stress_root}")
    return matches[0]


def load_observation_frame(bundle_dir: Path) -> pd.DataFrame:
    """Strip decision columns from a stress bundle's monthly CSV.

    Any column that is neither a recognised observation column nor a known
    decision column raises, so an unrecognised field cannot silently reach
    ``analyze_catchment()`` disguised as an observation.
    """
    monthly_path = bundle_dir / f"{bundle_dir.name}_monthly.csv"
    raw = pd.read_csv(monthly_path, parse_dates=["date"])
    known = set(KNOWN_DECISION_COLUMNS) | set(COUNT_COLUMNS)
    observation_columns = [c for c in raw.columns if c not in known]
    unrecognised = [
        c for c in raw.columns
        if c not in known and c not in observation_columns
    ]
    if unrecognised:
        raise ValueError(f"{monthly_path}: unrecognised column(s) {unrecognised!r}")
    return raw.loc[:, observation_columns].set_index("date")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise MotivatingRecordCheckFailure(message)


def check_denison(analysis) -> dict:
    """130413A Denison Creek at Braeside: zero-dominated, whole-zero years."""
    regime = analysis.regime
    results = {}

    _assert(regime.n_zero_months > 0, "expected zero diagnostics to be visible (n_zero_months > 0)")
    results["n_zero_months"] = regime.n_zero_months
    results["zero_month_fraction"] = regime.zero_month_fraction
    results["n_whole_zero_years"] = regime.n_whole_zero_years

    _assert(regime.pixel_support_status == "unavailable", "expected percentage-only pixel_support_status")
    results["pixel_support_status"] = regime.pixel_support_status

    hy = analysis.hydro_years
    if hy is not None and not hy.empty and "timing_status" in hy.columns:
        unresolved = hy.loc[hy["timing_status"] == "unresolved"]
        if "peak_date" in hy.columns:
            _assert(
                unresolved["peak_date"].isna().all() if "peak_date" in unresolved.columns else True,
                "an unresolved year must not carry a public exact peak date",
            )
        if "trough_date" in hy.columns:
            _assert(
                unresolved["trough_date"].isna().all() if "trough_date" in unresolved.columns else True,
                "an unresolved year must not carry a public exact trough date",
            )
        if "boundary_status" in unresolved.columns:
            _assert(
                (unresolved["boundary_status"] != "confirmed").all(),
                "an unresolved year must never carry a confirmed boundary status",
            )
        results["n_hydro_years"] = int(len(hy))
        results["n_unresolved_cycles"] = int(len(unresolved))
    else:
        results["n_hydro_years"] = 0

    return results


def check_nebo(analysis) -> dict:
    """130407A Nebo Creek at Nebo: insufficient timing evidence, event-routed."""
    regime = analysis.regime
    results = {
        "n_zero_months": regime.n_zero_months,
        "zero_month_fraction": regime.zero_month_fraction,
        "pixel_support_status": regime.pixel_support_status,
        "timing_evidence": regime.timing_evidence,
        "route": analysis.route,
    }
    _assert(regime.n_zero_months > 0, "expected zero diagnostics to be visible (n_zero_months > 0)")
    _assert(regime.pixel_support_status == "unavailable", "expected percentage-only pixel_support_status")
    _assert(
        regime.timing_evidence == "insufficient",
        f"expected timing_evidence='insufficient', got {regime.timing_evidence!r}",
    )
    _assert(
        analysis.route == "event_characterisation",
        f"expected route='event_characterisation', got {analysis.route!r}",
    )
    _assert(analysis.hydro_years.empty, "expected the public hydrological-year table to be empty")
    return results


def check_taroom(analysis) -> dict:
    """130302A Dawson River at Taroom: detectable floods, unresolved flat years."""
    regime = analysis.regime
    results = {
        "pixel_support_status": regime.pixel_support_status,
        "timing_evidence": regime.timing_evidence,
        "route": analysis.route,
        "n_events": analysis.events.summary.get("n_events", 0) if analysis.events is not None else 0,
    }
    _assert(regime.pixel_support_status == "unavailable", "expected percentage-only pixel_support_status")
    _assert(
        results["n_events"] > 0 or not analysis.hydro_years.empty,
        "expected detectable flood peaks to remain available via events or resolved cycles",
    )

    hy = analysis.hydro_years
    if hy is not None and not hy.empty and "timing_status" in hy.columns:
        results["n_hydro_years"] = int(len(hy))
        results["n_unresolved_cycles"] = int((hy["timing_status"] == "unresolved").sum())
        results["n_point_cycles"] = int((hy["timing_status"] == "point").sum())
        unresolved = hy.loc[hy["timing_status"] == "unresolved"]
        if "confidence" in unresolved.columns:
            _assert(
                (unresolved["confidence"] != "high").all(),
                "a flat/unresolved year must never carry high confidence",
            )
    else:
        results["n_hydro_years"] = 0

    _assert(
        results["n_events"] > 0,
        "expected event output to remain populated for this record",
    )
    return results


CHECKS = {
    "130413a": ("Denison Creek at Braeside", check_denison),
    "130407a": ("Nebo Creek at Nebo", check_nebo),
    "130302a": ("Dawson River at Taroom", check_taroom),
}


def run_check(stress_root: Path, station_id: str) -> dict:
    station_id = station_id.casefold()
    if station_id not in CHECKS:
        raise ValueError(f"no motivating-record check registered for {station_id!r}")
    name, check_fn = CHECKS[station_id]
    bundle_dir = find_bundle(stress_root, station_id)
    observations = load_observation_frame(bundle_dir)
    analysis = analyze_catchment(observations)
    results = check_fn(analysis)
    return {
        "station_id": station_id,
        "name": name,
        "bundle": bundle_dir.name,
        "regime": analysis.regime.regime,
        "route": analysis.route,
        "results": results,
        "passed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stress-root", type=Path, required=True)
    parser.add_argument(
        "--stations", type=str, default="130413a,130407a,130302a",
        help="Comma-separated station ids to check.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    station_ids = [s.strip() for s in args.stations.split(",") if s.strip()]
    reports = []
    failed = False
    for station_id in station_ids:
        try:
            report = run_check(args.stress_root, station_id)
        except (MotivatingRecordCheckFailure, AssertionError) as exc:
            failed = True
            report = {"station_id": station_id.casefold(), "passed": False, "error": str(exc)}
        reports.append(report)

    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "motivating-records-check.json").write_text(
            json.dumps(reports, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )

    print(json.dumps(reports, indent=2, sort_keys=True, default=str))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
