"""Build the blinded real-catchment cohort for timing-identifiability review.

Reads HydroSeason stress-bundle monthly CSVs (already-computed output, not
source input), strips every decision column, computes each record's
amplitude-to-floor-ratio stratum under the calibrated v0.2.0 thresholds,
excludes the three motivating stations, and selects a deterministic,
seeded subset per stratum for blinded human review. See
``case_studies/timing-identifiability/cohort-protocol.json`` for the frozen
selection rules this script implements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from hydroseason._calibration import timing_identifiability_fingerprint  # noqa: E402
from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS  # noqa: E402
from hydroseason._timing_identifiability import assess_timing_identifiability  # noqa: E402

# The packet's observation columns: what a blinded reviewer may see.
PACKET_COLUMNS = ("date", "extent_pct", "invalid_pct", "max_invalid_pct", "quality_state")

# HydroSeason decision columns known to appear in stress-bundle monthly CSVs
# (they are output, not source input). Stripped, never passed through.
KNOWN_DECISION_COLUMNS = (
    "regime", "route", "confidence", "phase", "phase_status", "hy_year",
    "usable_month", "is_hy_peak", "is_hy_mid_dry", "is_hy_trough",
    "in_wet_event", "wet_event_id", "in_low_spell", "low_spell_id",
    "baseline_extent_pct",
)

# Optional pixel-count source columns. Not part of the blinded packet (they
# are stripped like decision columns), but recognised so a source that
# happens to carry them is not mistaken for an unrecognised-column error --
# the count-completeness check in build_cohort is the authority on whether a
# partial set is acceptable.
COUNT_COLUMNS = ("n_water", "n_valid", "n_invalid", "n_aoi")

_STRATUM_ORDER = ("below_floor", "mid_ratio", "high_ratio")


class UnrecognisedColumnError(ValueError):
    """A monthly CSV column is neither a packet observation nor a known decision column."""


@dataclass(frozen=True)
class StratumBounds:
    name: str
    lower: float
    upper: float  # may be float("inf")


def _load_protocol(protocol_path: Path) -> dict:
    return json.loads(protocol_path.read_text(encoding="utf-8"))


def _strata_from_protocol(protocol: dict) -> tuple[StratumBounds, ...]:
    strata = protocol["stratification"]["strata"]
    bounds = []
    for entry in strata:
        upper = entry["upper"]
        upper = float("inf") if upper == "inf" else float(upper)
        bounds.append(StratumBounds(name=entry["name"], lower=float(entry["lower"]), upper=upper))
    return tuple(bounds)


def _station_id(bundle_dir: Path) -> str:
    """The station id is the lowercase slug prefix before the first hyphen."""
    return bundle_dir.name.split("-", 1)[0].casefold()


def discover_bundles(stress_root: Path) -> list[Path]:
    return sorted(p for p in stress_root.iterdir() if p.is_dir())


def strip_decision_columns(monthly: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """Reduce a stress-bundle monthly frame to the allowlisted packet columns.

    Any column that is neither a packet observation column nor a known
    HydroSeason decision column raises, rather than silently passing an
    unrecognised (and potentially decision-leaking) column through.
    """
    allowed = set(PACKET_COLUMNS) | set(KNOWN_DECISION_COLUMNS) | set(COUNT_COLUMNS)
    unrecognised = [col for col in monthly.columns if col not in allowed]
    if unrecognised:
        raise UnrecognisedColumnError(
            f"{source}: unrecognised column(s) {unrecognised!r} are neither "
            "packet observation columns nor known decision columns; refusing "
            "to silently pass them into a blinded review packet."
        )
    present = [col for col in PACKET_COLUMNS if col in monthly.columns]
    return monthly.loc[:, present].copy()


def _classify_stratum(ratio: float, strata: tuple[StratumBounds, ...]) -> str | None:
    for bound in strata:
        if bound.lower <= ratio < bound.upper:
            return bound.name
    return None


def _record_amplitude_to_floor_ratio(monthly: pd.DataFrame) -> tuple[float, str]:
    """Median annual amplitude-to-floor ratio and pixel-support status.

    Uses the record's own ``extent_pct``/``invalid_pct`` observations (already
    stripped of decisions) with the frozen calibrated thresholds -- the exact
    quantity and thresholds the challenger policy itself uses.
    """
    evidence = assess_timing_identifiability(
        monthly, thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
    )
    ratios = [year.amplitude_to_floor_ratio for year in evidence.years.values()]
    median_ratio = float(pd.Series(ratios, dtype=float).median()) if ratios else 0.0
    return median_ratio, evidence.pixel_support_status


def _selection_hash(seed: int, station_id: str) -> str:
    return hashlib.sha256(f"{seed}:{station_id}".encode("utf-8")).hexdigest()


def build_cohort(
    *,
    stress_root: Path,
    protocol: dict,
    output_dir: Path,
) -> dict:
    """Build the blinded review packet and manifest; return the manifest summary."""
    seed = int(protocol["seed"])
    exclude_ids = {station_id.casefold() for station_id in protocol["exclude_station_ids"]}
    strata = _strata_from_protocol(protocol)
    quota = 8

    bundles = discover_bundles(stress_root)
    candidates: list[dict] = []
    for bundle_dir in bundles:
        station_id = _station_id(bundle_dir)
        if station_id in exclude_ids:
            continue
        monthly_path = bundle_dir / f"{bundle_dir.name}_monthly.csv"
        if not monthly_path.exists():
            continue
        raw = pd.read_csv(monthly_path, parse_dates=["date"])
        stripped = strip_decision_columns(raw, source=str(monthly_path))

        count_columns = set(COUNT_COLUMNS)
        present_counts = count_columns.intersection(raw.columns)
        if present_counts and present_counts != count_columns:
            raise ValueError(
                f"{monthly_path}: partial pixel-count columns {sorted(present_counts)}; "
                "a source must carry all four count columns or none."
            )

        # Detectability is assessed against the raw source (counts included
        # when present), not the stripped packet: pixel_support_status must
        # reflect the real evidence basis, not an artifact of what a blinded
        # reviewer is shown.
        ratio, pixel_support_status = _record_amplitude_to_floor_ratio(raw)
        stratum = _classify_stratum(ratio, strata)
        if stratum is None:
            continue
        zero_fraction = float((stripped["extent_pct"] == 0.0).mean())
        candidates.append({
            "station_id": station_id,
            "bundle": bundle_dir.name,
            "monthly_path": monthly_path,
            "stratum": stratum,
            "amplitude_to_floor_ratio": ratio,
            "zero_fraction": zero_fraction,
            "pixel_support_status": pixel_support_status,
            "selection_hash": _selection_hash(seed, station_id),
        })

    seen_station_ids = [c["station_id"] for c in candidates]
    assert len(seen_station_ids) == len(set(seen_station_ids)), "duplicate station_id in candidate pool"

    selected: list[dict] = []
    stratum_report: dict[str, dict] = {}
    for stratum_name in _STRATUM_ORDER:
        pool = sorted(
            (c for c in candidates if c["stratum"] == stratum_name),
            key=lambda c: c["selection_hash"],
        )
        available = len(pool)
        take = min(quota, available)
        chosen = pool[:take]
        selected.extend(chosen)
        stratum_report[stratum_name] = {
            "available": available,
            "selected": take,
            "shortfall": max(0, quota - available),
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    packet_dir = output_dir / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    for record in selected:
        raw = pd.read_csv(record["monthly_path"], parse_dates=["date"])
        packet = strip_decision_columns(raw, source=str(record["monthly_path"]))
        packet_path = packet_dir / f"{record['station_id']}_packet.csv"
        packet.to_csv(packet_path, index=False, lineterminator="\n")
        manifest_rows.append({
            "station_id": record["station_id"],
            "stratum": record["stratum"],
            "amplitude_to_floor_ratio": record["amplitude_to_floor_ratio"],
            "zero_fraction": record["zero_fraction"],
            "pixel_support_status": record["pixel_support_status"],
            "packet_file": packet_path.name,
        })

    manifest_df = pd.DataFrame(manifest_rows)
    manifest_path = output_dir / "cohort-manifest.csv"
    manifest_df.to_csv(manifest_path, index=False, lineterminator="\n")

    summary = {
        "protocol_id": protocol["protocol_id"],
        "seed": seed,
        "source_bundles": protocol["source_bundles"],
        "excluded_station_ids": sorted(exclude_ids),
        "quota_policy": protocol["quota_policy"],
        "n_candidates": len(candidates),
        "n_selected": len(selected),
        "per_stratum": stratum_report,
        "threshold_fingerprint": timing_identifiability_fingerprint(),
        "manifest_path": str(manifest_path),
    }
    (output_dir / "cohort-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stress-root", type=Path, required=True)
    parser.add_argument(
        "--protocol", type=Path,
        default=REPO_ROOT / "case_studies" / "timing-identifiability" / "cohort-protocol.json",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=REPO_ROOT / "case_studies" / "results" / "timing-identifiability",
    )
    args = parser.parse_args()

    protocol = _load_protocol(args.protocol)
    summary = build_cohort(
        stress_root=args.stress_root, protocol=protocol, output_dir=args.output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
