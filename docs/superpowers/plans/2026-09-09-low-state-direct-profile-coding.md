# Low-state direct-profile: coding plan

**Date:** 2026-09-09

**Status:** Stage A, Step 3 deliverable, companion to
[the numerics specification](../specs/2026-09-09-low-state-direct-profile-numerics.md).
Executable failing tests and exact verification commands below. This plan is
not implementation-ready to run until every function signature, test
fixture, and tolerance here is treated as fixed text, not a starting point
for improvisation.

**Prerequisite:** [numerics spec](../specs/2026-09-09-low-state-direct-profile-numerics.md)
exit criterion met; [endpoint contract](../specs/2026-09-09-low-state-endpoint-contract.md)
and [validation protocol](../specs/2026-09-09-low-state-validation-protocol.md)
frozen.

**Scope boundary:** this plan is Stage B, Step 4 work. It does not run until
Stage A is accepted. It touches only
`case_studies/results/low-state-direct-profile-v2/`; no file under
`hydroseason/` is modified by this plan. `_trough_refinement.py`,
`_trough_refinement_defaults.py`, and `trough_refinement_candidate_0_2` are
read-only references, never edited here (Stage C, Step 6 is the only stage
authorized to touch production files, and only after this candidate passes
Step 5).

## File layout

```text
case_studies/results/low-state-direct-profile-v2/
  direct_profile.py            # research module: T/Q solver, refine_trough_span_direct_profile
  evaluate_direct_profile.py   # development harness: FAMILIES, score_records, main()
  test_direct_profile.py       # unit tests for direct_profile.py (this plan's Task 1-4)
  direct-profile-config.json   # frozen before evaluate_direct_profile.py's outcomes are observed
  direct-profile-synthetic-records.json
  direct-profile-synthetic-summary.csv
  direct-profile-output-manifest.json
```

`direct_profile.py` imports `hydroseason._trough_refinement` for
`_fit_valley_huber`, `_fit_valley_convex_cached`, `_robust_location`,
`_support_weights`, `_pulse_dates`, `_separated_clusters_are_pulses`,
`_median_absolute_deviation`, `_measurement_floor`, `_RELATIVE_CONVERGENCE`,
and the `TroughRefinementPolicy`/`TroughRefinementResult`/`PeakBoundary`
dataclasses — by name, read-only. It never reassigns any
`hydroseason._trough_refinement` module attribute (numerics spec §8).

## Task 1: `L`-grid and `T`/`Q` core (`direct_profile.py`)

**Signatures:**

```python
@dataclass(frozen=True)
class DirectProfileFit:
    start_position: int
    end_position: int
    reference_level: float      # the evaluated L, not necessarily L*(start, end)
    fitted: np.ndarray
    loss: float


def l_grid(
    block_level: float, scale: float, *, l_uncertainty_k: float, n_steps_per_scale: int = 4,
) -> np.ndarray:
    """Symmetric grid of admissible L values around block_level.

    Returns block_level + step * j for j in range(-n_L, n_L + 1), where
    step = scale / n_steps_per_scale and n_L = round(l_uncertainty_k * n_steps_per_scale).
    When scale == 0.0, returns array([block_level]) (no L uncertainty without a
    positive scale to bound it).
    """


def fit_with_reference_level(
    values: np.ndarray, weights: np.ndarray, start: int, end: int, level: float,
    *, scale: float, huber_k: float,
) -> DirectProfileFit:
    """Clamp the block to `level` exactly; branches use the existing isotonic fit.

    Mirrors `_fit_valley_convex`'s branch construction, evaluated at the
    supplied `level` instead of a searched regime breakpoint.
    """


def final_departure_index(
    fitted: np.ndarray, level: float, delta_pp: float, *, tolerance: float,
) -> int | None:
    """T(f, L, delta): last interior index with fitted <= level + delta_pp + tolerance,
    provided the contiguous low run touching that index does not reach either
    span edge. Returns None if no interior index qualifies, or the qualifying
    run touches an edge (numerics spec §2.3)."""
```

**Test fixtures (`test_direct_profile.py::TestCore`), literal values:**

```python
import numpy as np

def test_l_grid_symmetric_and_bounded():
    grid = l_grid(0.12, scale=0.01, l_uncertainty_k=2.0, n_steps_per_scale=4)
    assert grid.size == 17  # n_L = round(2.0 * 4) = 8 -> 2*8+1
    np.testing.assert_allclose(grid.min(), 0.12 - 0.02, atol=1e-12)
    np.testing.assert_allclose(grid.max(), 0.12 + 0.02, atol=1e-12)
    np.testing.assert_allclose(np.sort(grid), grid)  # ascending, no duplicates

def test_l_grid_zero_scale_returns_single_point():
    grid = l_grid(0.12, scale=0.0, l_uncertainty_k=2.0)
    np.testing.assert_allclose(grid, [0.12])

def test_final_departure_index_example_1():
    # Step 1 contract Example 1, best-fit block level ~0.12, delta_pp=0.004
    fitted = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
    index = final_departure_index(fitted, level=0.12, delta_pp=0.004, tolerance=1e-9)
    assert index == 4

def test_final_departure_index_flat_series_returns_none():
    fitted = np.full(5, 0.12)
    index = final_departure_index(fitted, level=0.12, delta_pp=0.004, tolerance=1e-9)
    assert index is None  # touches both edges -> undefined departure

def test_final_departure_index_ceiling_equality_included():
    # 0.123 == 0.12 + 0.003 exactly at delta_pp=0.003; must count as "in" per
    # the inclusive (<=) ceiling convention -- the last interior index within
    # the ceiling is 3 (0 and 4 are the span's excluded edges).
    fitted = np.array([0.40, 0.20, 0.120, 0.123, 0.40])
    index = final_departure_index(fitted, level=0.12, delta_pp=0.003, tolerance=1e-9)
    assert index == 3
```

## Task 2: profiled solver and support set (`direct_profile.py`)

**Signature:**

```python
@dataclass(frozen=True)
class DirectProfileSolution:
    support_positions: tuple[int, ...]   # final plausible cluster, sorted
    departure_position: int | None       # representative date position (Step 1 §7 convention)
    best_loss: float
    reference_level_at_best: float
    scale: float
    loss_basis: Literal["standardized_huber", "exact_l1", "unavailable"]


def solve_direct_profile(
    values: np.ndarray, weights: np.ndarray, *, delta_pp: float,
    scale: float, huber_k: float, profile_loss_cutoff: float, l_uncertainty_k: float,
) -> DirectProfileSolution:
    """Grid-search (start, end, L) per numerics spec §2, minimise Q(d) per
    candidate d = T(f, L, delta_pp), cluster plausible d's exactly as
    `_refine_selected_span` clusters `plausible_positions` today, and pick
    the representative date by the latest-exact-optimum-in-final-cluster
    convention (Step 1 §7)."""
```

**Test fixtures (`test_direct_profile.py::TestSolver`):**

```python
def _weights(n):
    return np.ones(n, dtype=float)

def test_solve_direct_profile_example_1_oracle_scale():
    # 0.121 and 0.123 differ by less than delta_pp: index 3 legitimately
    # joins the support cluster under a one-step-shifted shared reference
    # level (real, calibrated timing ambiguity -- numerics spec §5.1, revised
    # after Step 4 implementation surfaced this). The representative date
    # still resolves uniquely to the later member of the cluster.
    values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
    solution = solve_direct_profile(
        values, _weights(7), delta_pp=0.004, scale=0.005, huber_k=1.345,
        profile_loss_cutoff=0.01, l_uncertainty_k=2.0,
    )
    assert solution.departure_position == 4
    assert solution.support_positions == (3, 4)

def test_solve_direct_profile_example_2_gradual_recovery_excludes_change_point():
    values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.125, 0.14, 0.40])
    solution = solve_direct_profile(
        values, _weights(8), delta_pp=0.004, scale=0.003, huber_k=1.345,
        profile_loss_cutoff=0.01, l_uncertainty_k=2.0,
    )
    assert solution.departure_position == 4
    assert 3 not in solution.support_positions  # excludes the latent change point (numerics spec §5.2)
    assert 5 not in solution.support_positions

def test_solve_direct_profile_flat_series_no_departure():
    values = np.full(5, 0.12)
    solution = solve_direct_profile(
        values, _weights(5), delta_pp=0.004, scale=0.005, huber_k=1.345,
        profile_loss_cutoff=0.01, l_uncertainty_k=2.0,
    )
    assert solution.departure_position is None
    assert solution.support_positions == ()

def test_solve_direct_profile_l_uncertainty_widens_support_monotonically():
    values = np.array([0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40])
    widths = []
    for k in (0.0, 1.0, 2.0, 4.0):
        solution = solve_direct_profile(
            values, _weights(7), delta_pp=0.004, scale=0.005, huber_k=1.345,
            profile_loss_cutoff=0.01, l_uncertainty_k=k,
        )
        widths.append(len(solution.support_positions))
    assert widths == sorted(widths)                # non-decreasing
    assert all(w < 5 for w in widths)               # never degenerates to "every interior month" (numerics spec §5.4)
```

## Task 3: gap, pulse, and quality integration (`direct_profile.py`)

**Signature:**

```python
def refine_trough_span_direct_profile(
    frame: pd.DataFrame, *, left_peak: PeakBoundary, right_peak: PeakBoundary | None,
    policy: TroughRefinementPolicy, delta_pp: float, l_uncertainty_k: float = 2.0,
    scale_mode: Literal["residual", "combined"] = "residual",
    measurement_tolerance_pp: float = 0.0,
) -> TroughRefinementResult:
    """Per numerics spec §9. Full entry point: builds the span, dispatches to
    the pre-gap path (Task 3a) or the complete-span path (Task 1-2 solver),
    applies quality/pulse gating (reusing `_pulse_dates`,
    `_separated_clusters_are_pulses` unmodified), and returns the existing
    `TroughRefinementResult` shape."""
```

**Test fixtures (`test_direct_profile.py::TestIntegration`):**

```python
def _frame(values, dates):
    return prepare_monthly_extent(pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates))

def test_pulse_return_does_not_reset_low_state():
    # Step 1 contract Example 4
    dates = pd.date_range("2040-01-01", periods=9, freq="MS")
    values = [0.40, 0.20, 0.120, 0.121, 0.30, 0.122, 0.123, 0.20, 0.40]
    frame = _frame(values, dates)
    left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
    right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
    result = refine_trough_span_direct_profile(
        frame, left_peak=left, right_peak=right,
        policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.004,
    )
    assert result.boundary == dates[6]
    assert dates[4] in result.pulse_months

def test_gap_adjacent_to_low_state_is_unresolved():
    # Step 1 contract Example 5. Post-gap value (0.122) is itself within the
    # equivalence band, unlike a decisive post-gap recovery (e.g. 0.40),
    # which existing gap handling already resolves provisionally.
    dates = pd.date_range("2040-01-01", periods=8, freq="MS")
    values = [0.40, 0.20, 0.120, 0.121, 0.123, np.nan, np.nan, 0.122]
    frame = _frame(values, dates)
    left = PeakBoundary(dates[0], (dates[0],), "point", "normal")
    right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
    result = refine_trough_span_direct_profile(
        frame, left_peak=left, right_peak=right,
        policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.004,
    )
    assert result.status == "unresolved"
    assert result.boundary is None

def test_low_quality_peak_forces_provisional():
    dates = pd.date_range("2040-01-01", periods=7, freq="MS")
    values = [0.40, 0.20, 0.120, 0.121, 0.123, 0.20, 0.40]
    frame = _frame(values, dates)
    left = PeakBoundary(dates[0], (dates[0],), "point", "low")
    right = PeakBoundary(dates[-1], (dates[-1],), "point", "normal")
    result = refine_trough_span_direct_profile(
        frame, left_peak=left, right_peak=right,
        policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.004,
    )
    assert result.status == "provisional"
    assert result.reason == "low_quality_peak"
```

## Task 4: scale-invariance and normalization checks

**Test fixtures (`test_direct_profile.py::TestInvariance`):**

```python
def test_scale_and_unit_invariance():
    dates = pd.date_range("2040-01-01", periods=7, freq="MS")
    values = np.array([4.0, 2.0, 1.20, 1.21, 1.23, 2.0, 4.0])
    peaks = dict(
        left_peak=PeakBoundary(dates[0], (dates[0],), "point", "normal"),
        right_peak=PeakBoundary(dates[-1], (dates[-1],), "point", "normal"),
    )
    result = refine_trough_span_direct_profile(
        _frame(values, dates), **peaks, policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.04,
    )
    assert result.boundary == dates[4]

    # A tenfold rescale of values AND delta_pp together must not change the
    # selected date -- only loss magnitude changes, since huber_k and the
    # profile cutoff are dimensionless and scale is re-estimated from the
    # rescaled data.
    result_scaled = refine_trough_span_direct_profile(
        _frame(values * 10.0, dates), **peaks, policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.4,
    )
    assert result_scaled.boundary == dates[4]

def test_exact_zero_scale_uses_exact_l1_loss_basis():
    dates = pd.date_range("2040-01-01", periods=5, freq="MS")
    values = [0.40, 0.20, 0.12, 0.12, 0.40]
    frame = _frame(values, dates)
    result = refine_trough_span_direct_profile(
        frame, left_peak=PeakBoundary(dates[0], (dates[0],), "point", "normal"),
        right_peak=PeakBoundary(dates[-1], (dates[-1],), "point", "normal"),
        policy=TROUGH_REFINEMENT_POLICY, delta_pp=0.0,
    )
    assert result.loss_basis == "exact_l1"
```

## Numerical tolerances (fixed, not tuned per test)

- Loss-equality comparisons: `max(np.finfo(float).eps, _RELATIVE_CONVERGENCE
  * max(1.0, abs(best_loss)))`, identical to `_trough_refinement.py`'s
  existing convention — no new tolerance constant is introduced for loss
  comparisons.
- Ceiling-equality comparisons (`fitted[i] <= level + delta_pp`): tolerance
  `64 * np.finfo(float).eps * max(abs(level) + delta_pp, 1.0)`, matching the
  numerical-tolerance style already used in `endpoint_experiment.py`'s
  `_project_selected`.
- `l_grid` step size: `scale / n_steps_per_scale` with `n_steps_per_scale =
  4` as the specification default (numerics spec §7); this is a solver
  resolution constant, tuned only in Step 4's development comparison, never
  in unit tests.

## Independent numerical reference (required by numerics spec exit check)

Task 2's `test_solve_direct_profile_example_1_oracle_scale` and
`test_solve_direct_profile_example_2_gradual_recovery_excludes_change_point`
must each also be checked against a brute-force reference implementation
(a direct nested Python loop over every `(start, end, L)` triple with no
caching or PAVA optimization) on the same small fixed arrays, asserting the
optimized solver's `best_loss` and `departure_position` match the brute-force
result within the loss-equality tolerance above. This brute-force reference
lives in `test_direct_profile.py` itself (not in `direct_profile.py`) and is
never used at evaluation scale.

## Exact verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest case_studies/results/low-state-direct-profile-v2/test_direct_profile.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_trough_refinement.py tests/test_trough_refinement_calibration.py -q
.\.venv\Scripts\python.exe -m pytest case_studies/results/low-state-refinement-2026-09-09/test_endpoint_experiment.py -q
.\.venv\Scripts\python.exe case_studies/results/low-state-direct-profile-v2/evaluate_direct_profile.py
```

The fourth command must refuse to overwrite a changed frozen
`direct-profile-config.json`, exactly as
`evaluate_endpoint.py::main`'s existing `RuntimeError` guard does — this
plan's `evaluate_direct_profile.py` reuses that guard pattern rather than
inventing a new one.

## Task completion gate

A task in this plan is done only when:

1. Every literal test fixture above exists verbatim (the equality-boundary
   placeholder in Task 1 resolved to one literal value, not left as an
   `or`).
2. The exact verification commands run and are reported, per
   `superpowers:verification-before-completion` — pytest output pasted or
   summarized with pass/fail counts, not asserted from memory.
3. No file under `hydroseason/` differs from its Stage-A state (`git diff
   --stat hydroseason/` is empty for this plan's commits).

## Exit criterion (matches numerics spec Step 3 exit criterion)

This coding plan can be followed without inventing a margin, changing truth
labels, or deciding the uncertainty rule during implementation: `delta_pp`
is always caller-supplied (never defaulted), `l_uncertainty_k`'s grid
construction is pinned in Task 1, and every test fixture's expected value is
either a literal or an explicitly flagged placeholder resolved before the
task is marked done.
