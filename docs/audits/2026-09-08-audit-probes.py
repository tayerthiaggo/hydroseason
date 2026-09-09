"""Reproduce bounded numerical checks from the scientific audit; no library edits.

Run from the repository root with a supported Python environment containing
NumPy, pandas, and SciPy. SciPy is an independent audit oracle, not a new core
dependency. Output is JSON on stdout.
"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import scipy
from scipy.optimize import LinearConstraint, linprog, minimize

from hydroseason._boundary import robust_scale
from hydroseason._circular_timing import AnnualTimingSummary
from hydroseason._decision_policy import decide_established
from hydroseason._events import _noise_scale
from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import (
    PeakBoundary,
    TroughRefinementPolicy,
    _convex_loss,
    _fit_valley_convex,
    _refine_selected_span,
    refine_trough_span,
)


def main():
    rng = np.random.default_rng(20260908)
    worst = 0.0
    comparisons = failures = 0
    for _ in range(35):
        n = int(rng.integers(4, 10))
        values = rng.normal(10, 5, n)
        weights = rng.uniform(0.1, 1, n)
        start = int(rng.integers(1, n - 1))
        end = int(rng.integers(start, n - 1))
        matrix = np.zeros((n - 1, n))
        equality = np.zeros(n - 1, dtype=bool)
        for i in range(n - 1):
            if i < start:
                matrix[i, i], matrix[i, i + 1] = 1, -1
            else:
                matrix[i, i], matrix[i, i + 1] = -1, 1
            equality[i] = start <= i < end
        for scale in (0.0, 0.2, 2.0):
            _, loss = _fit_valley_convex(
                values, weights, start, end, scale=scale, huber_k=1.345
            )
            if scale == 0:
                inequalities = np.block([
                    [np.eye(n), -np.eye(n)],
                    [-np.eye(n), -np.eye(n)],
                    [-matrix, np.zeros((n - 1, n))],
                ])
                eq = matrix[equality]
                oracle = linprog(
                    np.r_[np.zeros(n), weights],
                    A_ub=inequalities,
                    b_ub=np.r_[values, -values, np.zeros(n - 1)],
                    A_eq=np.c_[eq, np.zeros_like(eq)] if len(eq) else None,
                    b_eq=np.zeros(len(eq)) if len(eq) else None,
                    bounds=[(None, None)] * n + [(0, None)] * n,
                    method="highs",
                )
            else:
                constraints = [LinearConstraint(matrix[~equality], 0, np.inf)]
                if equality.any():
                    constraints.append(LinearConstraint(matrix[equality], 0, 0))
                oracle = minimize(
                    lambda fit: _convex_loss(
                        values, fit, weights, scale=scale, huber_k=1.345
                    ),
                    np.full(n, np.average(values, weights=weights)),
                    jac=lambda fit: weights * np.clip(
                        (fit - values) / scale, -1.345, 1.345
                    ) / scale,
                    constraints=constraints,
                    method="SLSQP",
                    options={"ftol": 1e-10, "maxiter": 1000},
                )
            failures += int(not oracle.success)
            if oracle.success:
                worst = max(worst, abs(loss - oracle.fun))
                comparisons += 1

    index = pd.date_range("2000-01-01", periods=240, freq="MS")
    sine = pd.Series(50 + 20 * np.sin(2 * np.pi * np.arange(240) / 12), index=index)
    index = pd.date_range("2020-01-01", periods=7, freq="MS")
    left = PeakBoundary(index[0], (index[0],), "point", "normal")
    right = PeakBoundary(index[-1], (index[-1],), "point", "normal")
    policy = TroughRefinementPolicy(1.345, 0.05, 1.5)
    scaled_results = []
    for factor in (1.0, 0.01):
        frame = prepare_monthly_extent(pd.DataFrame({
            "extent_pct": factor * np.array([90, 60, 30, 10, 10.2, 45, 80]),
            "invalid_pct": 0.0,
        }, index=index))
        result = refine_trough_span(frame, left_peak=left, right_peak=right, policy=policy)
        scaled_results.append({
            "factor": factor,
            "local_scale_pp": result.local_scale_pp,
            "status": result.status,
            "boundary_candidates": [str(t.date()) for t in result.boundary_candidates],
        })

    gap_frame = prepare_monthly_extent(pd.DataFrame({
        "extent_pct": [90, 60, 30, 10, 20, 45, 80], "invalid_pct": 0.0,
    }, index=index)).drop(index=index[4])
    gap_result = _refine_selected_span(
        gap_frame, left_peak=left, right_peak=right, policy=policy,
        measurement_tolerance_pp=0.0,
    )
    decisions = []
    for n in (9, 10):
        timing = AnnualTimingSummary(0.2, 0.0, 0.5, 6.0, 0.5, n, 1)
        decision = decide_established(
            n_usable_years=n, amplitude_snr=1.0,
            peak_timing=timing, trough_timing=timing,
            n_peak_timing_years=n, n_trough_timing_years=n,
            min_informative_years=7,
        )
        decisions.append({"n": n, "regime": decision.regime, "route": decision.route})
    output = {
        "environment": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scipy": scipy.__version__,
        },
        "convex_oracle": {
            "successful": comparisons, "oracle_failures": failures,
            "max_absolute_objective_difference": worst,
        },
        "noiseless_sine": {
            "boundary_noise": float(robust_scale(prepare_monthly_extent(sine))[1]),
            "event_noise": float(_noise_scale(sine)),
        },
        "zero_scale_profile": scaled_results,
        "dropped_month_scenario": {
            "status": gap_result.status,
            "recovery_start": str(gap_result.recovery_start),
            "recovery_start_present": gap_result.recovery_start in gap_frame.index,
        },
        "decision_summary_probe": decisions,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
