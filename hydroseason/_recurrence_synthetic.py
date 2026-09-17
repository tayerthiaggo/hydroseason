"""Independent truth-labelled recurrence corpus."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._timing_identifiability import (
    PixelSupportStatus,
    TimingIdentifiabilityThresholds,
    TimingStatus,
)

RECURRENCE_CALIBRATION_SEEDS = range(50000, 55000)
RECURRENCE_VALIDATION_SEEDS = range(60000, 65000)

RECURRENCE_FAMILIES = (
    "annual_point_recurrence",
    "annual_interval_recurrence",
    "annual_phase_drift",
    "ordinary_gap_fragmented_plateau",
    "long_gap_fragmented_plateau",
    "annual_aligned_fragment_trap",
    "scattered_equivalent_ties",
    "single_diffuse_cluster",
)

_RECIPES = {
    "annual_point_recurrence": ((3,), (15,), "point"),
    "annual_interval_recurrence": ((2, 3), (14, 15), "interval"),
    "annual_phase_drift": ((3,), (14,), "point"),
    "ordinary_gap_fragmented_plateau": ((0, 1, 2, 3, 4, 8, 11), (), "unresolved"),
    "long_gap_fragmented_plateau": ((0, 1, 2, 6, 9, 13, 17), (), "unresolved"),
    "annual_aligned_fragment_trap": ((1, 2, 3, 13), (), "unresolved"),
    "scattered_equivalent_ties": ((1, 5, 9, 16), (), "unresolved"),
    "single_diffuse_cluster": ((4, 5, 6, 7, 8), (), "unresolved"),
}


@dataclass(frozen=True)
class RecurrenceTruth:
    kind: Literal["peak", "trough"]
    status: TimingStatus
    latest_dates: tuple[pd.Timestamp, ...]


@dataclass(frozen=True)
class RecurrenceSyntheticRecord:
    seed: int
    family: str
    values: pd.Series
    rows: pd.DataFrame
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    thresholds: TimingIdentifiabilityThresholds
    measurement_tolerance_pct: float
    noise_pp: float
    pixel_support_status: PixelSupportStatus
    truth: RecurrenceTruth


def generate_recurrence_record(
    seed: int,
    *,
    partition: Literal["calibration", "validation"] | str,
) -> RecurrenceSyntheticRecord:
    if partition == "calibration":
        if seed not in RECURRENCE_CALIBRATION_SEEDS:
            raise ValueError(
                f"seed {seed} is not in RECURRENCE_CALIBRATION_SEEDS ({RECURRENCE_CALIBRATION_SEEDS})"
            )
    elif partition == "validation":
        if seed not in RECURRENCE_VALIDATION_SEEDS:
            raise ValueError(
                f"seed {seed} is not in RECURRENCE_VALIDATION_SEEDS ({RECURRENCE_VALIDATION_SEEDS})"
            )
    else:
        raise ValueError(f"unknown partition: {partition!r}")

    family = RECURRENCE_FAMILIES[seed % len(RECURRENCE_FAMILIES)]
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x52454355]))
    kind: Literal["peak", "trough"] = (
        "peak" if (seed // len(RECURRENCE_FAMILIES)) % 2 == 0 else "trough"
    )
    pixel_support_status: PixelSupportStatus = (
        "available" if (seed // 16) % 2 == 0 else "unavailable"
    )
    max_interval = 2 + int((seed // 32) % 2)
    window_positions = (
        12 if family == "ordinary_gap_fragmented_plateau" else 13 + int(rng.integers(0, 8))
    )

    prior_offsets, latest_offsets, status = _RECIPES[family]
    recipe_offsets = prior_offsets + latest_offsets
    max_recipe_offset = max(recipe_offsets) if recipe_offsets else 0
    if window_positions <= max_recipe_offset:
        window_positions = max_recipe_offset + 1

    window_start = pd.Timestamp("1990-01-01")
    all_dates = pd.date_range(window_start, periods=window_positions, freq="MS")
    window_end = all_dates[-1]

    values = np.full(window_positions, 40.0, dtype=float)
    values[list(recipe_offsets)] = 70.0 if kind == "peak" else 10.0

    opposite_offset = None
    for ref in recipe_offsets:
        if ref + 6 < window_positions and (ref + 6) not in recipe_offsets:
            opposite_offset = ref + 6
            break
        if ref - 6 >= 0 and (ref - 6) not in recipe_offsets:
            opposite_offset = ref - 6
            break
    if opposite_offset is not None:
        values[opposite_offset] = 10.0 if kind == "peak" else 70.0

    keep_mask = np.ones(window_positions, dtype=bool)
    if seed % 3 == 0:
        interior = [
            i
            for i in range(1, window_positions - 1)
            if i not in recipe_offsets and i != opposite_offset
        ]
        keep_mask[interior[:2]] = False

    series = pd.Series(values[keep_mask], index=all_dates[keep_mask], dtype=float)
    if pixel_support_status == "available":
        rows = pd.DataFrame(
            {
                "n_valid": 100,
                "n_aoi": 100,
                "n_invalid": 0,
                "n_water": series.round().astype(int),
            },
            index=series.index,
        )
    else:
        rows = pd.DataFrame(
            {
                "n_valid": 100,
            },
            index=series.index,
        )

    truth = RecurrenceTruth(
        kind=kind,
        status=status,
        latest_dates=tuple(all_dates[m] for m in latest_offsets),
    )
    thresholds = TimingIdentifiabilityThresholds(1.5, 1, 0, max_interval, 2)

    return RecurrenceSyntheticRecord(
        seed=seed,
        family=family,
        values=series,
        rows=rows,
        window_start=window_start,
        window_end=window_end,
        thresholds=thresholds,
        measurement_tolerance_pct=1.0,
        noise_pp=0.0,
        pixel_support_status=pixel_support_status,
        truth=truth,
    )


__all__ = [
    "RECURRENCE_CALIBRATION_SEEDS",
    "RECURRENCE_FAMILIES",
    "RECURRENCE_VALIDATION_SEEDS",
    "RecurrenceSyntheticRecord",
    "RecurrenceTruth",
    "generate_recurrence_record",
]
