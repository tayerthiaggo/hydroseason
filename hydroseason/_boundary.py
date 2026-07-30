from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

__all__ = ["SIGNAL_FLOOR_FRACTION", "RobustBoundaryConfig", "BoundarySelection",
           "robust_scale", "select_window_minimum", "select_cycle_peak",
           "select_boundary_sequence"]

WindowStatus = Literal["full", "left_truncated", "right_truncated", "internal_gap"]
SelectionStatus = Literal["raw", "ambiguous", "quality_adjusted", "unresolved"]

SIGNAL_FLOOR_FRACTION = 0.10


@dataclass(frozen=True)
class RobustBoundaryConfig:
    min_usable_candidates: int = 2
    min_window_coverage: float = 0.70
    support_threshold: float = 0.80
    anomaly_noise_scales: float = 3.0

    def __post_init__(self) -> None:
        if self.min_usable_candidates < 1:
            raise ValueError("min_usable_candidates must be positive")
        if not 0 < self.min_window_coverage <= 1:
            raise ValueError("min_window_coverage must be in (0, 1]")
        if not 0 <= self.support_threshold <= 1:
            raise ValueError("support_threshold must be in [0, 1]")
        if self.anomaly_noise_scales <= 0:
            raise ValueError("anomaly_noise_scales must be positive")


@dataclass(frozen=True)
class BoundarySelection:
    raw_month: pd.Timestamp | None
    raw_extent_pct: float
    selected_month: pd.Timestamp | None
    selected_extent_pct: float
    run_start: pd.Timestamp | None
    run_end: pd.Timestamp | None
    window_status: WindowStatus
    selection_status: SelectionStatus
    support: float
    n_expected: int
    n_usable: int
    phase_shift_months: int | None


def robust_scale(frame: pd.DataFrame) -> tuple[float, float]:
    """Estimate amplitude and noise scale (percentage points) from usable candidates.

    Amplitude is the 10th-90th percentile spread of extent_pct among usable rows.
    Noise is a robust (MAD-based) estimate of month-to-month variability after
    removing each observation's month-of-year median (a crude seasonal baseline).
    """
    usable = frame.loc[frame["candidate_usable"], "extent_pct"].astype(float)
    if not len(usable):
        return 0.0, 0.0
    amplitude = float(usable.quantile(0.90) - usable.quantile(0.10))
    month_median = usable.groupby(usable.index.month).transform("median")
    delta = (usable - month_median).diff().dropna().to_numpy(float)
    if not len(delta):
        return amplitude, 0.0
    centre = float(np.median(delta))
    noise = 1.4826 * float(np.median(np.abs(delta - centre))) / np.sqrt(2.0)
    return amplitude, noise


def _epsilon_pp(row: pd.Series, *, noise_pp: float, amplitude_pp: float) -> float:
    """Tolerance band (percentage points) for treating nearby values as equivalent minima.

    Bounded above by 10% of the amplitude so the tolerance never swallows the
    whole seasonal range; bounded below by measurement resolution (100 / n_valid)
    when available, otherwise by the noise estimate.
    """
    resolution = 100.0 / float(row["n_valid"]) if "n_valid" in row and row["n_valid"] > 0 else 0.0
    return min(SIGNAL_FLOOR_FRACTION * amplitude_pp, max(resolution, noise_pp)) if amplitude_pp > 0 else 0.0


def _select_window_extreme(
    window: pd.DataFrame,
    *,
    expected: pd.Timestamp,
    expected_count: int,
    noise_pp: float,
    amplitude_pp: float,
    config: RobustBoundaryConfig,
    kind: Literal["min", "max"],
) -> BoundarySelection:
    """Select an extremum (minimum or maximum) within a window.

    For maxima the extent sign is inverted for comparisons only; the returned
    ``raw_*``/``selected_*`` extents are always the original observed values, so
    a raw observed extremum is never silently replaced. Passing ``kind="min"``
    reproduces the historical minimum-selection behaviour exactly.
    """
    sign = 1.0 if kind == "min" else -1.0
    usable = window.loc[window["candidate_usable"]].copy()
    n_usable = len(usable)
    if n_usable < config.min_usable_candidates:
        return BoundarySelection(None, np.nan, None, np.nan, None, None,
                                 "internal_gap", "unresolved", 0.0,
                                 expected_count, n_usable, None)
    comparison = usable["extent_pct"] * sign
    raw_month = pd.Timestamp(comparison.idxmin())
    raw_extent = float(usable.loc[raw_month, "extent_pct"])
    raw_comparison = float(comparison.loc[raw_month])
    epsilon = _epsilon_pp(usable.loc[raw_month], noise_pp=noise_pp, amplitude_pp=amplitude_pp)
    equivalent = (
        window["candidate_usable"]
        & (window["extent_pct"] * sign).le(raw_comparison + epsilon)
    )
    groups = equivalent.ne(equivalent.shift(fill_value=False)).cumsum()
    raw_group = groups.loc[raw_month]
    run = window.loc[equivalent & groups.eq(raw_group)]
    local = comparison.rolling(3, center=True, min_periods=2).median()
    residual = float(local.loc[raw_month] - raw_comparison)
    ambiguous = noise_pp > 0 and residual > config.anomaly_noise_scales * noise_pp
    full_start = expected - pd.DateOffset(months=(expected_count - 1) // 2)
    full_end = expected + pd.DateOffset(months=(expected_count - 1) // 2)
    if window.index.min() > full_start:
        window_status = "left_truncated"
    elif window.index.max() < full_end:
        window_status = "right_truncated"
    elif n_usable / expected_count < config.min_window_coverage:
        window_status = "internal_gap"
    else:
        window_status = "full"
    support = min(1.0, n_usable / expected_count)
    if ambiguous:
        support *= 0.60
    if window_status != "full":
        support *= 0.75
    return BoundarySelection(
        raw_month, raw_extent, raw_month, raw_extent,
        pd.Timestamp(run.index[0]), pd.Timestamp(run.index[-1]),
        window_status, "ambiguous" if ambiguous else "raw", support,
        expected_count, n_usable,
        (raw_month.year - expected.year) * 12 + raw_month.month - expected.month,
    )


def select_window_minimum(
    window: pd.DataFrame,
    *,
    expected: pd.Timestamp,
    expected_count: int,
    noise_pp: float,
    amplitude_pp: float,
    config: RobustBoundaryConfig = RobustBoundaryConfig(),
) -> BoundarySelection:
    """Select the boundary month within a window around an expected date.

    Always reports the true observed minimum (``raw_month``/``raw_extent_pct``)
    even when the selection is flagged ambiguous or the window is truncated —
    the raw extremum is never silently replaced or dropped.
    """
    return _select_window_extreme(
        window, expected=expected, expected_count=expected_count,
        noise_pp=noise_pp, amplitude_pp=amplitude_pp, config=config, kind="min",
    )


def select_cycle_peak(
    cycle: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    noise_pp: float,
    amplitude_pp: float,
    config: RobustBoundaryConfig = RobustBoundaryConfig(),
) -> BoundarySelection:
    """Select the seasonal peak (maximum) strictly between two trough boundaries.

    The two enclosing troughs (``start`` and ``end``) are never eligible as the
    peak -- only strictly-interior months are candidates. Selection reuses the
    minimum selector's machinery via ``_select_window_extreme(kind="max")``, so
    the true observed maximum (``raw_month``/``raw_extent_pct``) is always
    reported even when the selection is flagged ambiguous.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    interior = cycle.loc[(cycle.index > start) & (cycle.index < end)]
    n_interior = len(interior)
    if n_interior == 0:
        return BoundarySelection(None, np.nan, None, np.nan, None, None,
                                 "internal_gap", "unresolved", 0.0, 0, 0, None)
    expected = pd.Timestamp(interior.index[n_interior // 2])
    return _select_window_extreme(
        interior, expected=expected, expected_count=n_interior,
        noise_pp=noise_pp, amplitude_pp=amplitude_pp, config=config, kind="max",
    )


# Default: how much higher (as a fraction of the year's own observed minimum) a
# rival candidate may be while still counting as the *same* physical trough that
# the cross-year coherence pass is free to move onto. Candidates above this
# relative band are "materially higher" observations, not measurement noise, and
# the coherence pass may not substitute them for the raw minimum. The value is
# bracketed by the human-reviewed ground truth itself, independently on two
# sides: an already-approved synthetic case treats a ~5% relative gap as
# equivalent (coherence should win), while a real river shows a 7.1% gap is
# material (coherence must lose). 0.05 sits at the equivalent-side edge of that
# bracket, so it honours "≤5% is noise" without being tuned to the material
# value it must exclude.
_RAW_MINIMUM_REL_TOLERANCE = 0.05


def select_boundary_sequence(
    opportunities: list[dict],
    *,
    raw_minimum_rel_tolerance: float | None = None,
) -> list[pd.Timestamp | None]:
    """Pick a globally consistent boundary date per year via dynamic programming.

    Each opportunity contributes a phase cost (distance in months from its
    expected date) and, for consecutive opportunities within an unbroken run
    of non-empty candidate lists, a cycle cost (deviation of the inter-year
    gap from 12 months). Years with an empty candidate list are unresolved
    (``None``) and break cycle continuity: the DP never links a candidate
    across such a gap, so each contiguous block of resolved years is
    optimized independently.

    ``raw_minimum_rel_tolerance`` gates a *fidelity* guard so the coherence pass
    cannot silently override a materially lower observed minimum. It defaults to
    ``None``, which reproduces the historical value-blind behaviour exactly
    (callers that pass only raw candidate tuples, such as the approved synthetic
    optimizer tests, are unaffected). When a fraction is supplied, any candidate
    whose extent exceeds its own year's observed minimum ``m_i`` by more than
    ``raw_minimum_rel_tolerance * m_i`` is treated as ineligible: it is a
    materially higher observation, not measurement noise around the same physical
    trough, so coherence is not allowed to substitute it for the raw minimum.
    Candidates within the band keep zero value-cost, so among relative-equivalents
    the coherence pass still operates exactly as before. A *relative* reference is
    used deliberately -- "materially higher" only makes physical sense as a
    fraction of that year's own water level (the same 0.01pp gap is noise on a
    1.0pp trough but a 50% jump on a 0.02pp trough), which is precisely why the
    absolute noise band already in ``select_window_minimum`` proved too loose.
    Each year's observed minimum always has excess 0 and so is always eligible.
    """
    selected: list[pd.Timestamp | None] = [None] * len(opportunities)
    # A cost large enough to make an over-tolerance candidate never win against
    # any in-tolerance candidate, yet finite so the DP stays well defined even in
    # the (impossible) event that a whole year were over tolerance -- the year's
    # own minimum has excess 0 and is always in tolerance, so one always remains.
    ineligible_cost = float("inf") if raw_minimum_rel_tolerance is not None else 0.0

    def fidelity_cost(opportunity: dict) -> list[float]:
        values = [float(value) for _, value in opportunity["candidates"]]
        if not values or raw_minimum_rel_tolerance is None:
            return [0.0] * len(values)
        minimum = min(values)
        threshold = minimum * (1.0 + raw_minimum_rel_tolerance)
        return [0.0 if value <= threshold else ineligible_cost for value in values]

    def optimize_block(block: list[dict]) -> list[pd.Timestamp]:
        costs: list[list[float]] = []
        parents: list[list[int | None]] = []
        fidelities = [fidelity_cost(opportunity) for opportunity in block]
        for index, opportunity in enumerate(block):
            row_costs, row_parents = [], []
            for candidate_index, (date, _) in enumerate(opportunity["candidates"]):
                phase = abs(
                    (date.year - opportunity["expected"].year) * 12
                    + date.month - opportunity["expected"].month
                )
                fidelity = fidelities[index][candidate_index]
                if index == 0:
                    row_costs.append(float(phase) + fidelity)
                    row_parents.append(None)
                    continue
                best_cost, best_parent = float("inf"), None
                for parent_index, (previous_date, _) in enumerate(
                    block[index - 1]["candidates"]
                ):
                    cycle = (
                        (date.year - previous_date.year) * 12
                        + date.month - previous_date.month
                    )
                    candidate_cost = (
                        costs[index - 1][parent_index] + phase + fidelity + abs(cycle - 12)
                    )
                    if candidate_cost < best_cost:
                        best_cost, best_parent = candidate_cost, parent_index
                row_costs.append(best_cost)
                row_parents.append(best_parent)
            costs.append(row_costs)
            parents.append(row_parents)
        cursor = int(np.argmin(costs[-1]))
        chosen = []
        for index in range(len(block) - 1, -1, -1):
            chosen.append(pd.Timestamp(block[index]["candidates"][cursor][0]))
            parent = parents[index][cursor]
            if parent is not None:
                cursor = parent
        return list(reversed(chosen))

    block_start = 0
    while block_start < len(opportunities):
        while (
            block_start < len(opportunities)
            and not opportunities[block_start]["candidates"]
        ):
            block_start += 1
        if block_start == len(opportunities):
            break
        block_end = block_start
        while (
            block_end < len(opportunities)
            and opportunities[block_end]["candidates"]
        ):
            block_end += 1
        selected[block_start:block_end] = optimize_block(
            opportunities[block_start:block_end]
        )
        block_start = block_end
    return selected
