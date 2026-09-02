"""Record- and cohort-level trough search geometry diagnostics.

These summarise *where* boundaries were found relative to the window that was
allowed to find them.  Nothing here participates in choosing a boundary, and
nothing here is an error rate: without per-cycle truth, an outside-window
challenge is a challenge, not a correction.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ._calibration import wilson_interval


@dataclass(frozen=True)
class BoundaryGeometrySummary:
    """Neutral geometry diagnostics for one catchment.

    The two rates have different denominators and must not be compared.
    ``boundary_search_edge_rate`` is over published boundaries;
    ``outside_window_lower_rate`` is over boundaries whose audit span was fully
    observed.
    """

    n_boundaries: int
    n_at_search_edge: int
    boundary_search_edge_rate: float
    boundary_search_edge_interval: tuple[float, float]
    interval_method: str
    n_outside_window_observed: int
    n_outside_window_lower: int
    outside_window_lower_rate: float
    radius_used_counts: dict[int, int]
    retry_outcome_counts: dict[str, int]
    edge_side_counts: dict[str, int]


# The Task 2 diagnostic columns this module reads.  A frame missing any of
# these (e.g. one loaded from the compact CSV export bundle, which omits them)
# cannot be summarised and must hit the "no data" branch instead of raising a
# bare KeyError partway through.
_REQUIRED_COLUMNS = (
    "trough_month",
    "boundary_at_search_edge",
    "boundary_search_edge_side",
    "outside_window_observed",
    "outside_window_lower",
    "trough_search_radius_used",
    "retry_outcome",
)

# (0.0, 1.0) -- not (0.0, 0.0) -- because "no data" is not the same claim as "a
# confidently estimated rate of zero".  This matches wilson_interval's own
# convention for n <= 0.
_NO_DATA = BoundaryGeometrySummary(
    n_boundaries=0,
    n_at_search_edge=0,
    boundary_search_edge_rate=0.0,
    boundary_search_edge_interval=(0.0, 1.0),
    interval_method="wilson_within_catchment",
    n_outside_window_observed=0,
    n_outside_window_lower=0,
    outside_window_lower_rate=0.0,
    radius_used_counts={},
    retry_outcome_counts={},
    edge_side_counts={},
)


def summarise_boundary_geometry(annual: pd.DataFrame) -> BoundaryGeometrySummary:
    """Summarise one catchment's published boundaries.

    The interval is Wilson and is labelled ``wilson_within_catchment`` because
    cycles inside one catchment are serially dependent: it understates the true
    uncertainty and is reported honestly as such.  Use
    :func:`bootstrap_catchment_rate` across catchments instead.
    """
    if annual.empty or not set(_REQUIRED_COLUMNS).issubset(annual.columns):
        return _NO_DATA  # no annual frame at all, or missing required columns

    published = annual.loc[annual["trough_month"].notna()]
    n_boundaries = int(len(published))
    if n_boundaries == 0:
        return _NO_DATA  # frame present but nothing published yet

    at_edge = published["boundary_at_search_edge"].fillna(False).astype(bool)
    observed = published["outside_window_observed"].fillna(False).astype(bool)
    lower = published["outside_window_lower"].fillna(False).astype(bool) & observed

    n_at_edge = int(at_edge.sum())
    n_observed = int(observed.sum())
    n_lower = int(lower.sum())

    radius_counts = {
        int(value): int(count)
        for value, count in published["trough_search_radius_used"].dropna().value_counts().items()
    }
    retry_counts = {
        str(value): int(count)
        for value, count in published["retry_outcome"].dropna().value_counts().items()
    }
    edge_side_counts = {
        str(value): int(count)
        for value, count in published["boundary_search_edge_side"].dropna().value_counts().items()
    }

    return BoundaryGeometrySummary(
        n_boundaries=n_boundaries,
        n_at_search_edge=n_at_edge,
        boundary_search_edge_rate=n_at_edge / n_boundaries,
        boundary_search_edge_interval=wilson_interval(n_at_edge, n_boundaries),
        interval_method="wilson_within_catchment",
        n_outside_window_observed=n_observed,
        n_outside_window_lower=n_lower,
        outside_window_lower_rate=(n_lower / n_observed) if n_observed else 0.0,
        radius_used_counts=dict(sorted(radius_counts.items())),
        retry_outcome_counts=dict(sorted(retry_counts.items())),
        edge_side_counts=dict(sorted(edge_side_counts.items())),
    )


def bootstrap_catchment_rate(
    per_catchment: Sequence[tuple[int, int]],
    *,
    seed: int = 0,
    n_resamples: int = 2000,
) -> tuple[float, float]:
    """Percentile bootstrap interval that resamples catchments, not cycles.

    ``per_catchment`` is one ``(successes, trials)`` pair per catchment.  Cycles
    within a catchment are serially dependent, so a cycle-level interval on the
    pooled counts understates uncertainty by roughly the cluster size.  The
    resampling unit is therefore the catchment.  Returns a 95% percentile
    bootstrap interval (the 2.5th and 97.5th percentiles of the resampled
    rates).
    """
    if not len(per_catchment):
        raise ValueError("bootstrap_catchment_rate needs at least one catchment.")
    if n_resamples <= 0:
        raise ValueError("bootstrap_catchment_rate needs n_resamples > 0.")
    successes = np.asarray([int(item[0]) for item in per_catchment], dtype=float)
    trials = np.asarray([int(item[1]) for item in per_catchment], dtype=float)
    if (trials < 0).any() or (successes < 0).any() or (successes > trials).any():
        raise ValueError("each catchment needs 0 <= successes <= trials.")

    rng = np.random.default_rng(seed)
    n = len(per_catchment)
    draws = rng.integers(0, n, size=(int(n_resamples), n))
    resampled_trials = trials[draws].sum(axis=1)
    resampled_successes = successes[draws].sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        rates = np.where(resampled_trials > 0, resampled_successes / resampled_trials, np.nan)
    rates = rates[np.isfinite(rates)]
    if not rates.size:
        raise ValueError(
            "bootstrap_catchment_rate: every catchment has trials == 0; "
            "no resampled rate is defined."
        )
    return (float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5)))
