"""Tests for the direct-profile low-state-departure research candidate.

Research-only, outside the package. See ``direct_profile.py`` module docstring
and the Step 3 numerics spec / coding plan for the contract these tests pin.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason._trough_refinement import PeakBoundary  # noqa: E402
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY  # noqa: E402

import direct_profile  # noqa: E402
from direct_profile import (  # noqa: E402
    _natural_reference_level,
    final_departure_index,
    fit_with_reference_level,
    l_grid,
    refine_trough_span_direct_profile,
    refine_trough_span_direct_profile_with_sensitivity,
    solve_direct_profile,
)


class TestCore:
    def test_l_grid_symmetric_and_bounded(self):
        grid = l_grid(0.12, scale=0.01, l_uncertainty_k=2.0, n_steps_per_scale=4)
        assert grid.size == 17  # n_L = round(2.0 * 4) = 8 -> 2*8+1
        np.testing.assert_allclose(grid.min(), 0.12 - 0.02, atol=1e-12)
        np.testing.assert_allclose(grid.max(), 0.12 + 0.02, atol=1e-12)
        np.testing.assert_allclose(np.sort(grid), grid)

    def test_l_grid_zero_scale_returns_single_point(self):
        grid = l_grid(0.12, scale=0.0, l_uncertainty_k=2.0)
        np.testing.assert_allclose(grid, [0.12])

    def test_final_departure_index_example_1(self):
        fitted = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
        index = final_departure_index(fitted, level=0.12, delta_pp=0.004, tolerance=1e-9)
        assert index == 4

    def test_final_departure_index_flat_series_returns_none(self):
        fitted = np.full(5, 0.12)
        index = final_departure_index(fitted, level=0.12, delta_pp=0.004, tolerance=1e-9)
        assert index is None

    def test_final_departure_index_ceiling_equality_included(self):
        fitted = np.array([0.40, 0.20, 0.120, 0.123, 0.40])
        index = final_departure_index(fitted, level=0.12, delta_pp=0.003, tolerance=1e-9)
        assert index == 3

    def test_fit_with_reference_level_clamps_block_exactly(self):
        values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
        weights = np.ones(7)
        fit = fit_with_reference_level(values, weights, 2, 4, level=0.15, scale=0.01, huber_k=1.345)
        np.testing.assert_allclose(fit.fitted[2:5], [0.15, 0.15, 0.15])
        assert fit.reference_level == 0.15
        assert fit.start_position == 2
        assert fit.end_position == 4


class TestSolver:
    @staticmethod
    def _weights(n):
        return np.ones(n, dtype=float)

    def test_solve_direct_profile_example_1_oracle_scale(self):
        # index 3 (0.121) and index 4 (0.123) genuinely tie within
        # profile_loss_cutoff at this scale: the three low-state values
        # (0.120/0.121/0.123) differ by less than delta_pp itself, so a
        # shared reference level shifted by roughly one grid step legitimately
        # excludes 0.123 while keeping 0.121 -- this is real, calibrated
        # timing uncertainty (the whole point of profiling L), not a defect.
        # The representative date (Step 1 contract section 7) still resolves
        # to the unique, later value.
        values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
        solution = solve_direct_profile(
            values, self._weights(7), delta_pp=0.004, scale=0.005, huber_k=1.345,
            profile_loss_cutoff=0.01, l_uncertainty_k=2.0,
        )
        assert solution.departure_position == 4
        assert solution.support_positions == (3, 4)

    def test_solve_direct_profile_example_2_gradual_recovery_excludes_change_point(self):
        values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.125, 0.14, 0.40])
        solution = solve_direct_profile(
            values, self._weights(8), delta_pp=0.004, scale=0.003, huber_k=1.345,
            profile_loss_cutoff=0.01, l_uncertainty_k=2.0,
        )
        assert solution.departure_position == 4
        assert 3 not in solution.support_positions
        assert 5 not in solution.support_positions

    def test_solve_direct_profile_flat_series_no_departure(self):
        values = np.full(5, 0.12)
        solution = solve_direct_profile(
            values, self._weights(5), delta_pp=0.004, scale=0.005, huber_k=1.345,
            profile_loss_cutoff=0.01, l_uncertainty_k=2.0,
        )
        assert solution.departure_position is None
        assert solution.support_positions == ()

    def test_solve_direct_profile_l_uncertainty_widens_support_monotonically(self):
        values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
        widths = []
        for k in (0.0, 1.0, 2.0, 4.0):
            solution = solve_direct_profile(
                values, self._weights(7), delta_pp=0.004, scale=0.005, huber_k=1.345,
                profile_loss_cutoff=0.01, l_uncertainty_k=k,
            )
            widths.append(len(solution.support_positions))
        assert widths == sorted(widths)
        assert all(w < 5 for w in widths)

    def test_solve_direct_profile_matches_brute_force_reference(self):
        """Independent numerical reference: nested-loop brute force, no PAVA/caching."""
        values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
        weights = self._weights(7)
        delta_pp, scale, huber_k = 0.004, 0.005, 1.345

        def huber(residual, scale, k):
            if scale == 0.0:
                return abs(residual)
            magnitude = abs(residual / scale)
            if magnitude <= k:
                return 0.5 * magnitude**2
            return k * magnitude - 0.5 * k**2

        reference_level = _natural_reference_level(values, weights, scale=scale, huber_k=huber_k)
        best_loss = np.inf
        for start in range(1, len(values) - 1):
            for end in range(start, len(values) - 1):
                for level in l_grid(reference_level, scale, l_uncertainty_k=2.0):
                    fit = fit_with_reference_level(values, weights, start, end, level=level, scale=scale, huber_k=huber_k)
                    loss = sum(w * huber(v - f, scale, huber_k) for v, f, w in zip(values, fit.fitted, weights))
                    if loss < best_loss:
                        best_loss = loss

        solution = solve_direct_profile(
            values, weights, delta_pp=delta_pp, scale=scale, huber_k=huber_k,
            profile_loss_cutoff=0.01, l_uncertainty_k=2.0,
        )
        tolerance = max(np.finfo(float).eps, 1e-9 * max(1.0, abs(best_loss)))
        assert abs(solution.best_loss - best_loss) <= tolerance


def _frame(values, dates):
    return prepare_monthly_extent(pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates))


class TestIntegration:
    def test_pulse_return_does_not_reset_low_state(self):
        dates = pd.date_range("2040-01-01", periods=9, freq="MS")
        values = [0.40, 0.20, 0.120, 0.121, 0.30, 0.122, 0.123, 0.20, 0.40]
        frame = _frame([v * 100 for v in values], dates)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        result = refine_trough_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.4,
        )
        assert result.boundary == dates[6]
        assert dates[4] in result.pulse_months

    def test_gap_adjacent_to_low_state_is_unresolved(self):
        # Post-gap value (12.2) is itself within the equivalence band of the
        # pre-gap low state, so a genuine return-to-low-state cannot be ruled
        # out from the observed record -- unlike a decisive post-gap
        # recovery (e.g. to 40.0), which existing gap handling already
        # resolves provisionally at the last pre-gap month.
        dates = pd.date_range("2040-01-01", periods=8, freq="MS")
        values = [40.0, 20.0, 12.0, 12.1, 12.3, np.nan, np.nan, 12.2]
        frame = _frame(values, dates)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        result = refine_trough_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.4,
        )
        assert result.status == "unresolved"
        assert result.boundary is None

    def test_low_quality_peak_forces_provisional(self):
        dates = pd.date_range("2040-01-01", periods=7, freq="MS")
        values = [40.0, 20.0, 12.0, 12.1, 12.3, 20.0, 40.0]
        frame = _frame(values, dates)
        left = PeakBoundary(dates[0], (dates[0],), "point", "low")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        result = refine_trough_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.4,
        )
        assert result.status == "provisional"
        assert result.reason == "low_quality_peak"


class TestInvariance:
    def test_exact_zero_scale_uses_exact_l1_loss_basis(self):
        dates = pd.date_range("2040-01-01", periods=5, freq="MS")
        values = [40.0, 20.0, 12.0, 12.0, 40.0]
        frame = _frame(values, dates)
        result = refine_trough_span_direct_profile(
            frame, left_peak=PeakBoundary(dates[0], (dates[0],), "point", "normal"),
            right_peak=PeakBoundary(dates[-1], (dates[-1],), "point", "normal"),
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.0,
        )
        assert result.loss_basis == "exact_l1"

    def test_scale_and_unit_invariance(self):
        dates = pd.date_range("2040-01-01", periods=7, freq="MS")
        values = np.array([4.0, 2.0, 1.20, 1.21, 1.23, 2.0, 4.0])
        frame = _frame(values, dates)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        result = refine_trough_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.04,
        )
        assert result.boundary == dates[4]

        frame_scaled = _frame(values * 10.0, dates)
        result_scaled = refine_trough_span_direct_profile(
            frame_scaled, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.4,
        )
        assert result_scaled.boundary == dates[4]


class TestSensitivityWrapper:
    """refine_trough_span_direct_profile_with_sensitivity reuses production's
    real peak/quality sensitivity ensemble (hydroseason._trough_refinement.
    refine_trough_span's outer loop) around the direct-profile core -- see
    module docstring. These tests pin the monkeypatch's safety contract, not
    the ensemble's own decision logic (already covered by
    tests/test_trough_refinement.py)."""

    def test_restores_original_after_call(self):
        dates = pd.date_range("2040-01-01", periods=7, freq="MS")
        values = [4.0, 2.0, 1.20, 1.21, 1.23, 2.0, 4.0]
        frame = _frame(values, dates)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        refine_trough_span_direct_profile_with_sensitivity(
            frame, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.04, scale_mode="combined",
        )
        assert direct_profile._core._refine_selected_span is direct_profile._ORIGINAL_REFINE_SELECTED_SPAN

    def test_raises_when_called_reentrantly(self):
        direct_profile._core._refine_selected_span = lambda *a, **k: None
        try:
            dates = pd.date_range("2040-01-01", periods=7, freq="MS")
            frame = _frame([4.0, 2.0, 1.2, 1.21, 1.23, 2.0, 4.0], dates)
            left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
            right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
            with pytest.raises(RuntimeError):
                refine_trough_span_direct_profile_with_sensitivity(
                    frame, left_peak=left, right_peak=right,
                    policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.04,
                )
        finally:
            direct_profile._core._refine_selected_span = direct_profile._ORIGINAL_REFINE_SELECTED_SPAN

    def test_matches_bare_candidate_on_clean_point_peak_case(self):
        dates = pd.date_range("2040-01-01", periods=7, freq="MS")
        values = [4.0, 2.0, 1.20, 1.21, 1.23, 2.0, 4.0]
        frame = _frame(values, dates)
        left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
        right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
        bare = refine_trough_span_direct_profile(
            frame, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.04, scale_mode="combined",
        )
        wrapped = refine_trough_span_direct_profile_with_sensitivity(
            frame, left_peak=left, right_peak=right,
            policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.04, scale_mode="combined",
        )
        assert wrapped.boundary == bare.boundary
