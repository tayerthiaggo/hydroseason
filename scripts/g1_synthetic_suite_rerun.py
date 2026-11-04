"""Rerun the 0.2.0 timing-identifiability synthetic suite at the G1 gates.

G1 (docs/handoff/2026-11-02-g1-gate-calibration-plan.md) asks for the existing
synthetic validation suite to be rerun with the chosen gates before any change.
That suite was removed from the library before 0.2.0 (commit 88b78cd), so this
script runs it from the last commit that still had it, a6e5a41, extracted into a
separate directory. The library in this repository is not imported.

Usage::

    git archive a6e5a41 hydroseason | tar -x -C <dir>
    python scripts/g1_synthetic_suite_rerun.py <dir> <out.json>

The record reports, for the calibration and validation partitions:
- how the corpus's amplitude-to-floor ratios and peak water pixels are spread,
  so a reader can see whether any record falls between the gate values tested;
- the frozen 0.2.0 selection rerun from scratch, with its survivor counts;
- the four selection metrics at the current, chosen and fully open gates.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SOURCE_COMMIT = "a6e5a41"
GATES = {"current": (3.0, 5), "chosen": (1.5, 2), "open": (0.0, 0)}
RATIO_BANDS = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.5), (1.5, 3.0), (3.0, 25.0), (25.0, float("inf"))]


def main(source: Path, out: Path) -> None:
    sys.path.insert(0, str(source))
    import hydroseason  # noqa: PLC0415

    if Path(hydroseason.__file__).resolve().parent != (source / "hydroseason").resolve():
        raise SystemExit(f"imported the wrong hydroseason: {hydroseason.__file__}")
    from hydroseason._calibration import (  # noqa: PLC0415
        build_timing_identifiability_cache,
        score_timing_identifiability_thresholds,
        select_timing_identifiability_defaults,
    )
    from hydroseason._synthetic import CALIBRATION_SEEDS, VALIDATION_SEEDS  # noqa: PLC0415

    from hydroseason._timing_identifiability import TimingIdentifiabilityThresholds  # noqa: PLC0415

    record: dict = {
        "source_commit": SOURCE_COMMIT,
        "source_commit_resolved": subprocess.run(
            ["git", "rev-parse", SOURCE_COMMIT], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "partitions": {},
    }
    for partition, seeds in (("calibration", CALIBRATION_SEEDS), ("validation", VALIDATION_SEEDS)):
        cache = build_timing_identifiability_cache(seeds, partition=partition)
        ratio = cache["amplitude_to_floor_ratio"].astype(float)
        pixels = cache["peak_n_water"]
        bands = {}
        for low, high in RATIO_BANDS:
            mask = (ratio == 0.0) if high == 0.0 else ((ratio > low) if low == 0.0 else (ratio >= low)) & (ratio < high)
            label = "0" if high == 0.0 else f"[{low:g},{high:g})"
            bands[label] = int(mask.sum())
        entry: dict = {
            "rows": len(cache),
            "records": int(cache["seed"].nunique()),
            "families": sorted(cache["family"].unique().tolist()),
            "rows_by_ratio": bands,
            "rows_with_ratio_above_0_and_peak_pixels_below_5": int(((ratio > 0) & (pixels < 5)).sum()),
            "gates": {},
        }
        if partition == "calibration":
            selected, score = select_timing_identifiability_defaults(cache)
            entry["reselection"] = {
                "ratio": selected.min_amplitude_to_floor_ratio,
                "peak_pixels": selected.min_peak_water_pixels,
                "survivors": score.selection_counts,
            }
        for name, (gate_ratio, gate_pixels) in GATES.items():
            thresholds = TimingIdentifiabilityThresholds(gate_ratio, gate_pixels, 0, 2, 7)
            score = score_timing_identifiability_thresholds(cache, thresholds)
            entry["gates"][name] = {
                "ratio": gate_ratio,
                "peak_pixels": gate_pixels,
                "false_precise_boundary_rate": score.false_precise_boundary_rate,
                "false_precise_boundary_wilson": list(score.false_precise_boundary_wilson),
                "precise_boundaries": score.false_precise_boundary_n,
                "correct_abstention": score.correct_abstention,
                "annualisation_recall": score.annualisation_recall,
                "median_absolute_boundary_error_months": score.boundary_mae,
            }
        record["partitions"][partition] = entry
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
