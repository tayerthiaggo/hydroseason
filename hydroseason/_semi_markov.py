"""Opt-in four-state hidden semi-Markov model (HSMM) boundary challenger.

This module is a probabilistic alternative to the shipped-default robust
extrema detector (``hydroseason._boundary``). It models a hydrological year
as a strict cycle through four states -- ``wet -> recession -> dry ->
recovery -> wet`` -- each with an explicit (non-geometric) duration
distribution, and estimates state occupancy via an explicit-duration
Viterbi / forward-backward recursion in log space, with an outer EM loop
that re-estimates the per-state Gaussian emission parameters.

Nothing else in the codebase imports this module yet; it is exercised only
by ``tests/test_semi_markov.py`` until a later task wires it into the public
dispatch configuration.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

STATES = ("wet", "recession", "dry", "recovery")
_N_STATES = len(STATES)
_DRY_INDEX = STATES.index("dry")
_WET_INDEX = STATES.index("wet")

# Seed values only: EM re-estimates means/variances from data each iteration,
# so these merely need the right relative order (wet high, dry low, the two
# transitional states in between with opposite slope signs) to steer the
# duration-constrained dynamic program towards the correct cyclic labelling.
_LEVEL_MEAN_INIT = np.array([0.9, 0.5, 0.1, 0.5])
_SLOPE_MEAN_INIT = np.array([0.0, -0.2, 0.0, 0.2])
_INITIAL_VARIANCE = 1.0
_MIN_OBSERVED_FRACTION = 0.05
_USABLE_FRACTION_EPS = 1e-9
_TROUGH_WINDOW_MONTHS = 3


@dataclass(frozen=True)
class SemiMarkovConfig:
    min_duration: tuple[int, int, int, int] = (1, 1, 1, 1)
    max_duration: tuple[int, int, int, int] = (8, 10, 8, 8)
    max_iterations: int = 25
    convergence_tol: float = 1e-5
    variance_floor: float = 0.05


@dataclass(frozen=True)
class SemiMarkovResult:
    trough_months: tuple[pd.Timestamp, ...]
    peak_months: tuple[pd.Timestamp, ...]
    state_path: tuple[str, ...]
    state_posterior: np.ndarray
    trough_support: tuple[float, ...]
    log_likelihood: float


def _logsumexp(values: np.ndarray) -> float:
    maximum = float(np.max(values))
    return maximum + float(np.log(np.exp(values - maximum).sum()))


def _usable_mask(frame: pd.DataFrame) -> np.ndarray:
    """Months that may carry emission evidence and be selected as boundaries."""
    usable = frame["candidate_usable"].to_numpy(dtype=bool)
    fraction = frame["observed_fraction"].to_numpy(dtype=float)
    return usable & (fraction > _USABLE_FRACTION_EPS)


def _normalize_observations(
    frame: pd.DataFrame, config: SemiMarkovConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build the two per-month observation dimensions: level and slope.

    ``extent_pct`` is centred on the median of usable observations and scaled
    by a robust spread (``Q90 - Q10``, floored by ``variance_floor`` so a
    near-constant series never produces a degenerate/zero scale). Slope is
    the one-month difference of the normalized level. A month's slope is only
    usable when both it and the preceding month are usable -- a single
    missing month must not corrupt the slope of its usable neighbour.
    """
    usable = _usable_mask(frame)
    extent = frame["extent_pct"].to_numpy(dtype=float)
    reference = extent[usable]
    if reference.size:
        median = float(np.median(reference))
        q10, q90 = (float(v) for v in np.quantile(reference, [0.10, 0.90]))
    else:
        median, q10, q90 = 0.0, 0.0, 0.0
    scale = max(q90 - q10, config.variance_floor)
    level = (extent - median) / scale

    slope = np.zeros_like(level)
    slope[1:] = level[1:] - level[:-1]
    slope_usable = usable.copy()
    slope_usable[0] = False
    slope_usable[1:] &= usable[:-1]
    return level, slope, usable, slope_usable


def _emission_loglik(
    level: np.ndarray,
    slope: np.ndarray,
    usable: np.ndarray,
    slope_usable: np.ndarray,
    observed_fraction: np.ndarray,
    means_level: np.ndarray,
    means_slope: np.ndarray,
    var_level: np.ndarray,
    var_slope: np.ndarray,
) -> np.ndarray:
    """Per-month, per-state diagonal-Gaussian log density over (level, slope).

    Variance is divided by ``clip(observed_fraction, 0.05, 1.0)`` so a
    partially-observed month is treated as less informative (wider,
    lower-confidence emission) rather than more informative. Months that are
    unusable (``candidate_usable=False`` or ``observed_fraction`` near zero)
    contribute exactly zero emission evidence -- they neither favour nor
    penalize any state -- and likewise a usable month whose *predecessor* is
    missing contributes zero slope evidence.
    """
    n_months = level.shape[0]
    fraction_scale = np.clip(observed_fraction, _MIN_OBSERVED_FRACTION, 1.0)
    emit = np.zeros((n_months, _N_STATES))
    for state in range(_N_STATES):
        eff_var_level = var_level[state] / fraction_scale
        eff_var_slope = var_slope[state] / fraction_scale
        level_term = -0.5 * np.log(2 * np.pi * eff_var_level) - 0.5 * (
            level - means_level[state]
        ) ** 2 / eff_var_level
        slope_term = -0.5 * np.log(2 * np.pi * eff_var_slope) - 0.5 * (
            slope - means_slope[state]
        ) ** 2 / eff_var_slope
        emit[:, state] = np.where(usable, level_term, 0.0) + np.where(
            slope_usable, slope_term, 0.0
        )
    return emit


def _duration_logprobs(config: SemiMarkovConfig) -> list[dict[int, float]]:
    """Discrete-uniform log duration probability per state, keyed by duration."""
    logprobs: list[dict[int, float]] = []
    for state in range(_N_STATES):
        lo, hi = config.min_duration[state], config.max_duration[state]
        n_durations = hi - lo + 1
        log_p = -np.log(n_durations)
        logprobs.append({duration: log_p for duration in range(lo, hi + 1)})
    return logprobs


def _cumsum_with_zero(values: np.ndarray) -> np.ndarray:
    out = np.empty(len(values) + 1)
    out[0] = 0.0
    np.cumsum(values, out=out[1:])
    return out


def _segment_sum(cumulative: np.ndarray, start: int, end: int) -> float:
    """Sum of the underlying series over inclusive month indices [start, end]."""
    return float(cumulative[end + 1] - cumulative[start])


def _forward(
    emit: np.ndarray, durations: list[dict[int, float]]
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Segmental (explicit-duration) forward recursion in log space.

    ``alpha[t, j]`` is the log-probability mass of all segmentations of
    months ``0..t`` in which a segment of state ``j`` ends exactly at ``t``.
    Because transitions are strictly cyclic, state ``j`` has exactly one
    permitted predecessor, so the usual sum-over-predecessors collapses to a
    single term.
    """
    n_months = emit.shape[0]
    cumulative = [_cumsum_with_zero(emit[:, state]) for state in range(_N_STATES)]
    initial_logprob = -np.log(_N_STATES)
    alpha = np.full((n_months, _N_STATES), -np.inf)
    for t in range(n_months):
        for state in range(_N_STATES):
            prev_state = (state - 1) % _N_STATES
            best = -np.inf
            for duration, duration_logp in durations[state].items():
                start = t - duration + 1
                if start < 0:
                    continue
                segment = _segment_sum(cumulative[state], start, t)
                if start == 0:
                    prior_score = initial_logprob
                else:
                    prior_score = alpha[start - 1, prev_state]
                    if prior_score == -np.inf:
                        continue
                best = np.logaddexp(best, duration_logp + segment + prior_score)
            alpha[t, state] = best
    return alpha, cumulative


def _backward(
    emit: np.ndarray,
    durations: list[dict[int, float]],
    cumulative: list[np.ndarray],
) -> np.ndarray:
    """Segmental backward recursion.

    ``beta[t, j]`` is the log-probability of all observations strictly after
    ``t`` given that a segment of state ``j`` ends exactly at ``t`` (so the
    next segment, of the cyclic successor state, begins at ``t + 1``).
    """
    n_months = emit.shape[0]
    beta = np.zeros((n_months, _N_STATES))
    for t in range(n_months - 2, -1, -1):
        for state in range(_N_STATES):
            next_state = (state + 1) % _N_STATES
            best = -np.inf
            for duration, duration_logp in durations[next_state].items():
                end = t + duration
                if end > n_months - 1:
                    continue
                segment = _segment_sum(cumulative[next_state], t + 1, end)
                best = np.logaddexp(best, duration_logp + segment + beta[end, next_state])
            beta[t, state] = best
    return beta


def _state_posterior(
    emit: np.ndarray,
    alpha: np.ndarray,
    beta: np.ndarray,
    durations: list[dict[int, float]],
    cumulative: list[np.ndarray],
) -> tuple[np.ndarray, float]:
    """Monthly state-occupancy posterior and total log-likelihood.

    Every complete segmentation assigns exactly one segment (hence exactly
    one state) to a given month. Summing, over every candidate segment that
    covers month ``t``, the probability mass of segmentations containing that
    exact segment (``alpha`` of the prefix times duration times segment
    emission times ``beta`` of the suffix) and dividing by the total
    likelihood therefore yields a properly normalized per-month posterior
    that sums to one across states.
    """
    n_months = emit.shape[0]
    initial_logprob = -np.log(_N_STATES)
    log_likelihood = _logsumexp(alpha[n_months - 1, :])
    gamma = np.full((n_months, _N_STATES), -np.inf)
    for state in range(_N_STATES):
        prev_state = (state - 1) % _N_STATES
        for duration, duration_logp in durations[state].items():
            for end in range(duration - 1, n_months):
                start = end - duration + 1
                if start == 0:
                    prior_score = initial_logprob
                else:
                    prior_score = alpha[start - 1, prev_state]
                    if prior_score == -np.inf:
                        continue
                segment = _segment_sum(cumulative[state], start, end)
                segment_score = prior_score + duration_logp + segment + beta[end, state]
                if segment_score == -np.inf:
                    continue
                for t in range(start, end + 1):
                    gamma[t, state] = np.logaddexp(gamma[t, state], segment_score)
    posterior = np.exp(gamma - log_likelihood)
    row_sums = posterior.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0.0] = 1.0
    posterior = posterior / row_sums
    return posterior, log_likelihood


def _viterbi(emit: np.ndarray, durations: list[dict[int, float]]) -> list[str]:
    """Best single segmentation (hard state path) via explicit-duration Viterbi."""
    n_months = emit.shape[0]
    cumulative = [_cumsum_with_zero(emit[:, state]) for state in range(_N_STATES)]
    initial_logprob = -np.log(_N_STATES)
    best_score = np.full((n_months, _N_STATES), -np.inf)
    # parent[t, j] holds the end index of the preceding segment, or -1 when
    # the segment ending at t is the very first segment of the sequence.
    parent = np.full((n_months, _N_STATES), -2, dtype=int)
    for t in range(n_months):
        for state in range(_N_STATES):
            prev_state = (state - 1) % _N_STATES
            top_score, top_parent = -np.inf, -2
            for duration, duration_logp in durations[state].items():
                start = t - duration + 1
                if start < 0:
                    continue
                segment = _segment_sum(cumulative[state], start, t)
                if start == 0:
                    prior_score, candidate_parent = initial_logprob, -1
                else:
                    prior_score = best_score[start - 1, prev_state]
                    if prior_score == -np.inf:
                        continue
                    candidate_parent = start - 1
                candidate = duration_logp + segment + prior_score
                if candidate > top_score:
                    top_score, top_parent = candidate, candidate_parent
            best_score[t, state] = top_score
            parent[t, state] = top_parent

    path = [-1] * n_months
    t = n_months - 1
    state = int(np.argmax(best_score[n_months - 1, :]))
    while t >= 0:
        segment_start = parent[t, state] + 1
        for k in range(segment_start, t + 1):
            path[k] = state
        if parent[t, state] == -1:
            break
        t = parent[t, state]
        state = (state - 1) % _N_STATES
    return [STATES[index] for index in path]


def _select_troughs(
    frame: pd.DataFrame,
    posterior: np.ndarray,
    usable: np.ndarray,
    expected_trough_month: int,
) -> tuple[tuple[pd.Timestamp, ...], tuple[float, ...]]:
    """Pick, per calendar-year window, the usable dry->recovery transition anchor.

    The trough month is the point of maximum "dry" occupancy posterior within
    a window around the expected phase; restricting candidates to usable
    months means an unusable observation can never be selected, satisfying
    the "never treat a missing observation as a boundary" invariant directly
    rather than relying on the dynamic program to avoid it incidentally.
    """
    index = frame.index
    trough_months: list[pd.Timestamp] = []
    trough_support: list[float] = []
    for year in sorted(set(index.year)):
        target = pd.Timestamp(year=year, month=expected_trough_month, day=1)
        window_start = target - pd.DateOffset(months=_TROUGH_WINDOW_MONTHS)
        window_end = target + pd.DateOffset(months=_TROUGH_WINDOW_MONTHS)
        positions = np.where((index >= window_start) & (index <= window_end))[0]
        best_position, best_score = None, -np.inf
        for position in positions:
            if not usable[position]:
                continue
            score = float(posterior[position, _DRY_INDEX])
            if score > best_score:
                best_score, best_position = score, position
        if best_position is None:
            continue
        date = pd.Timestamp(index[best_position])
        if date in trough_months:
            continue
        support = sum(
            float(posterior[best_position + offset, _DRY_INDEX])
            for offset in (-1, 0, 1)
            if 0 <= best_position + offset < len(index)
        )
        trough_months.append(date)
        trough_support.append(support)
    return tuple(trough_months), tuple(trough_support)


def _select_peaks(
    frame: pd.DataFrame,
    state_path: list[str],
    usable: np.ndarray,
    trough_months: tuple[pd.Timestamp, ...],
) -> tuple[pd.Timestamp, ...]:
    """Maximum usable raw observation assigned to ``wet`` between consecutive troughs."""
    if len(trough_months) < 2:
        return tuple()
    extent = frame["extent_pct"].to_numpy(dtype=float)
    index = frame.index
    ordered = sorted(trough_months)
    peaks: list[pd.Timestamp] = []
    for start, end in zip(ordered[:-1], ordered[1:]):
        positions = np.where((index > start) & (index < end))[0]
        best_position, best_value = None, -np.inf
        for position in positions:
            if not usable[position] or state_path[position] != "wet":
                continue
            value = extent[position]
            if value > best_value:
                best_value, best_position = value, position
        if best_position is not None:
            peaks.append(pd.Timestamp(index[best_position]))
    return tuple(peaks)


def fit_semi_markov_boundaries(
    frame: pd.DataFrame,
    expected_trough_month: int,
    config: SemiMarkovConfig = SemiMarkovConfig(),
) -> SemiMarkovResult:
    """Fit the four-state HSMM challenger and extract trough/peak boundaries.

    ``frame`` must be indexed by a sorted, monthly ``DatetimeIndex`` and carry
    ``extent_pct``, ``observed_fraction``, and ``candidate_usable`` columns
    (the same contract used by the robust extrema detector). Unusable months
    contribute no emission evidence and are never eligible as boundaries.
    """
    frame = frame.sort_index()
    level, slope, usable, slope_usable = _normalize_observations(frame, config)
    observed_fraction = frame["observed_fraction"].to_numpy(dtype=float)
    durations = _duration_logprobs(config)

    means_level = _LEVEL_MEAN_INIT.copy()
    means_slope = _SLOPE_MEAN_INIT.copy()
    var_level = np.full(_N_STATES, _INITIAL_VARIANCE)
    var_slope = np.full(_N_STATES, _INITIAL_VARIANCE)

    log_likelihood = -np.inf
    posterior = np.full((level.shape[0], _N_STATES), 1.0 / _N_STATES)
    for _ in range(max(1, config.max_iterations)):
        emit = _emission_loglik(
            level, slope, usable, slope_usable, observed_fraction,
            means_level, means_slope, var_level, var_slope,
        )
        alpha, cumulative = _forward(emit, durations)
        beta = _backward(emit, durations, cumulative)
        posterior, new_log_likelihood = _state_posterior(emit, alpha, beta, durations, cumulative)

        weight_level = posterior * usable[:, None]
        weight_slope = posterior * slope_usable[:, None]
        denom_level = weight_level.sum(axis=0)
        denom_slope = weight_slope.sum(axis=0)
        for state in range(_N_STATES):
            if denom_level[state] > _USABLE_FRACTION_EPS:
                means_level[state] = float((weight_level[:, state] * level).sum() / denom_level[state])
                var_level[state] = max(
                    float((weight_level[:, state] * (level - means_level[state]) ** 2).sum() / denom_level[state]),
                    config.variance_floor,
                )
            if denom_slope[state] > _USABLE_FRACTION_EPS:
                means_slope[state] = float((weight_slope[:, state] * slope).sum() / denom_slope[state])
                var_slope[state] = max(
                    float((weight_slope[:, state] * (slope - means_slope[state]) ** 2).sum() / denom_slope[state]),
                    config.variance_floor,
                )

        converged = np.isfinite(log_likelihood) and abs(new_log_likelihood - log_likelihood) < config.convergence_tol
        log_likelihood = new_log_likelihood
        if converged:
            break

    emit = _emission_loglik(
        level, slope, usable, slope_usable, observed_fraction,
        means_level, means_slope, var_level, var_slope,
    )
    state_path = _viterbi(emit, durations)
    alpha, cumulative = _forward(emit, durations)
    beta = _backward(emit, durations, cumulative)
    posterior, log_likelihood = _state_posterior(emit, alpha, beta, durations, cumulative)

    trough_months, trough_support = _select_troughs(frame, posterior, usable, expected_trough_month)
    peak_months = _select_peaks(frame, state_path, usable, trough_months)

    return SemiMarkovResult(
        trough_months=trough_months,
        peak_months=peak_months,
        state_path=tuple(state_path),
        state_posterior=posterior,
        trough_support=trough_support,
        log_likelihood=float(log_likelihood),
    )
