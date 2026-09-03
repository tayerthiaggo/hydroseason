# Trough Geometry Re-entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make trough-geometry calibration consume the corrected frozen recurrence policy, remove stale bug-pinning expectations, restart calibration, and return control to Tasks 8-11 of the existing geometry plan.

**Architecture:** Extend the geometry fingerprint across the actual window-timing callees, update the calibration integration test to assert corrected false-precision behavior, then rerun only the already-open geometry calibration partition. Preserve the untouched geometry validation partition and stop at the existing user gate with the newly selected tuple.

**Tech Stack:** Python 3.10+, pandas, NumPy, pytest, JSON, SHA-256.

**Spec:** `docs/superpowers/specs/2026-09-03-recurrence-cluster-identifiability-design.md`

## Global Constraints

- Prerequisite: every task in `docs/superpowers/plans/2026-09-03-recurrence-identifiability-correction.md` is complete and `RECURRENCE_POLICY` is frozen from a calibration run that passed both Wilson safety gates. Recurrence *authority scope* reaching `established_0_2_0` is **not** a prerequisite: the blinded-cohort gate that promotion depends on has no bearing on geometry detection, so geometry re-entry proceeds at `candidate_for_established_0_2_0` scope. See Step 3's fingerprint scope note for why. That plan's Task 6 Step 4 also gives `_write_trough_geometry_defaults()` block markers and replace-or-append behaviour; without it, re-running geometry calibration appends a second `TROUGH_GEOMETRY_DEFAULTS` instead of replacing the first. Confirm the markers exist before Task 3.
- Package remains 0.2.0 during re-entry.
- `TROUGH_GEOMETRY_AUTHORITY_SCOPE` remains exactly `candidate_for_established_0_3_0`.
- Do not change `TROUGH_GEOMETRY_GRID`, any boundary selector, or any corpus truth label.
- Do not weaken false precise-boundary Wilson upper bound `<= 0.05`.
- Geometry calibration seeds are `30000..30239`. Geometry validation seeds `40000..` remain untouched until existing Task 9 receives approval.
- Existing 8/64 result is stale development evidence, not an expectation to preserve.
- The 0/64 expectation is measured, not predicted. On the four
  `missing_outer_months` seeds that carry all eight false points
  (30005/30015/30025/30035, shipped geometry `TroughGeometry(3, 5, 6)`),
  `n_false` is `8.0` of `n_unidentifiable` `16.0` today; with
  `_most_recent_recurrence_cluster` replaced by identity it is `0.0`, and with
  an equal-span `annual_shape_match` stand-in it is also `0.0`. Every false
  point on that family is produced by recurrence narrowing, and neither policy
  that can win calibration reproduces it.
- Keep `tied_low_plateau_wide["published"].sum() == 0`; it protects a separate point-only scoring fix.
- Prior geometry cache/results are stale after recurrence policy and fingerprint changes.
- Preserve unrelated untracked stress-test outputs.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `hydroseason/_calibration.py` | Geometry fingerprint covers direct and transitive timing inputs. | 1 |
| `tests/test_calibration.py` | Pins fingerprint dependency and corrected 0/64 integration behavior. | 1-2 |
| `docs/superpowers/plans/2026-09-02-trough-window-geometry.md` | Existing Tasks 8-11 resumed after this plan. | 3 |
| `.superpowers/sdd/progress.md` | Records recurrence prerequisite and new Task 8 gate state. | 3 |
| `docs/calibration/trough-geometry-calibration.json` | Restarted calibration report from open partition. | 3 |
| `hydroseason/_scientific_defaults.py` | Generated geometry tuple/fingerprint after calibration. | 3 |

---

### Task 1: Extend Geometry Fingerprint Across Timing Dependencies

**Files:**
- Modify: `hydroseason/_calibration.py:2052-2085`
- Modify: `tests/test_calibration.py`

**Interfaces:**
- Consumes: validated `assess_window_timing`, `_window_status`, `narrow_most_recent_recurrence`, and `RECURRENCE_POLICY`. `RECURRENCE_FINGERPRINT` is deliberately **not** consumed; see Step 3.
- Produces: `trough_geometry_fingerprint()` that stales whenever window timing or its selected recurrence policy changes.

- [ ] **Step 1: Write failing source-dependency test**

Append:

```python
def test_trough_geometry_fingerprint_covers_window_timing_and_recurrence_policy():
    import inspect

    from hydroseason import _calibration

    source = inspect.getsource(_calibration.trough_geometry_fingerprint)
    required = {
        "timing_metrics.assess_window_timing",
        "timing_metrics._window_status",
        "recurrence_metrics.narrow_most_recent_recurrence",
        "defaults.RECURRENCE_POLICY",
    }
    missing = sorted(item for item in required if item not in source)
    assert not missing, f"geometry fingerprint misses timing inputs: {missing}"
    # RECURRENCE_FINGERPRINT is deliberately excluded: geometry detection depends
    # on which policy was selected and how narrowing is implemented, both already
    # covered above, not on recurrence's authority scope. The fingerprint adds
    # scope on top of policy, and scope alone moves at recurrence promotion
    # (metrics_changed: False, policy_changed: False), which would otherwise
    # stale every geometry result over a string with no detection effect.
    assert "defaults.RECURRENCE_FINGERPRINT" not in source, (
        "geometry fingerprint must not depend on recurrence authority scope"
    )
```

- [ ] **Step 2: Run test and verify red**

Run: `python -m pytest tests/test_calibration.py -q -k fingerprint_covers_window`

Expected: FAIL listing all four missing inputs (the exclusion assertion passes trivially before the fingerprint function is touched).

- [ ] **Step 3: Add explicit imports and hashes**

Inside `trough_geometry_fingerprint()` import:

```python
        _recurrence_identifiability as recurrence_metrics,
        _timing_identifiability as timing_metrics,
```

Add these objects to the `inspect.getsource()` tuple after dynamic-year functions:

```python
        timing_metrics.assess_window_timing,
        timing_metrics._window_status,
        recurrence_metrics.narrow_most_recent_recurrence,
```

After selected geometry JSON, add:

```python
    if not hasattr(defaults, "RECURRENCE_POLICY"):
        raise ValueError("recurrence defaults have not been generated.")
    hasher.update(defaults.RECURRENCE_POLICY.encode("utf-8"))
```

Do **not** add `defaults.RECURRENCE_FINGERPRINT`. Geometry behaviour depends on
exactly two things: which recurrence policy was selected, and how narrowing is
implemented. Both are already hashed above (`RECURRENCE_POLICY` and
`narrow_most_recent_recurrence`'s source). `RECURRENCE_FINGERPRINT` layers
corpus/scoring/seeds/metrics/*scope* on top of the same policy value; scope is
its only contribution that policy does not already carry, and scope is exactly
what changes at recurrence promotion with `metrics_changed: False,
policy_changed: False`. Hashing it would stale every geometry result on a
promotion that changes no detection behaviour, forcing geometry re-entry to
wait on the blinded-cohort gate for no reason tied to geometry itself.

Keep the attribute access literal: the Step 1 test greps
`trough_geometry_fingerprint`'s source for `defaults.RECURRENCE_POLICY`, so a
`getattr()` rewrite would pass the hash and fail the test. The guard is what
turns a skipped prerequisite into a named error instead of an `AttributeError`
from inside a fingerprint call. The same test also asserts
`defaults.RECURRENCE_FINGERPRINT` is absent from the source, so re-adding it
later fails loudly rather than silently reintroducing the coupling.

Do not add recurrence validation results; geometry fingerprint tracks selected calibration inputs, not downstream validation.

- [ ] **Step 4: Run fingerprint and calibration tests**

Run:

```powershell
python -m pytest tests/test_calibration.py tests/test_scientific_defaults.py -q -k "trough_geometry_fingerprint or fingerprint_covers_window or recurrence"
```

Expected: PASS. Any previously generated geometry fingerprint is now stale by design.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_calibration.py tests/test_calibration.py
git commit -m "fix: fingerprint recurrence inputs in geometry calibration"
```

---

### Task 2: Replace Bug-Pinning Geometry Integration Expectations

**Files:**
- Modify: `tests/test_calibration.py:757-846`

**Interfaces:**
- Consumes: corrected production recurrence default and real 40-seed geometry cache.
- Produces: integration proof that `missing_outer_months` no longer creates the documented 8 false point rows and selector gate is not weakened.

- [ ] **Step 1: Rewrite stale test narrative before assertions**

Keep the test name `test_selector_composes_with_a_real_cache_from_the_calibration_partition`. Replace its 8/64 paragraphs with:

```python
    The recurrence-identifiability correction removes the geometry-invariant
    false points formerly contributed by the first year of each two-year
    ``missing_outer_months`` gap.  This test keeps the original 40-seed
    integration scale and now requires zero false point publications across
    the 64 truth-unidentifiable rows.  The Wilson admission gate remains
    unchanged; the selector must succeed rather than being wrapped in an
    expected RuntimeError.
```

In `test_geometry_runner_writes_defaults_and_a_report`, remove the paragraph calling 8/64 accepted/documented. State that real calibration is now independently covered by the integration test and this test isolates writer plumbing with a hand-built cache.

- [ ] **Step 2: Replace failing assertions exactly**

Keep cache construction and `tied_low_plateau_wide` assertion. Replace:

```python
    assert metrics["n_false"] == 8.0
    assert metrics["n_unidentifiable"] == 64.0

    with pytest.raises(RuntimeError, match="false precise-boundary"):
        select_trough_geometry_defaults(cache)
```

with:

```python
    assert metrics["n_false"] == 0.0
    assert metrics["n_unidentifiable"] == 64.0
    geometry, score = select_trough_geometry_defaults(cache)
    assert geometry in set(iter_trough_geometry_points())
    assert score.false_precise_boundary_n == 64
    assert score.false_precise_boundary_rate == 0.0
    assert score.false_precise_boundary_wilson[1] <= 0.05
```

This is the frozen prediction, and it has been measured on the family that
carries all eight rows: disabling recurrence narrowing takes that family from
`n_false == 8.0` to `0.0` (see Global Constraints). A nonzero result here
therefore means a *different* family started contributing, not that the
diagnosis was wrong. If `n_false` is nonzero, stop and report family/seed/year
residuals; do not loosen the assertion or the gate.

- [ ] **Step 3: Run the real-cache integration test**

Run:

```powershell
python -m pytest tests/test_calibration.py -q -k "selector_composes_with_a_real_cache or geometry_runner"
```

Expected: PASS. The cache evaluates four seeds from each ten-family geometry corpus across all 24 tuples.

- [ ] **Step 4: Run geometry-focused suite**

Run:

```powershell
python -m pytest tests/test_trough_geometry_corpus.py tests/test_boundary_geometry.py tests/test_calibration.py tests/test_dynamic_year.py -q -k "geometry or missing_outer_months or tied_low_plateau"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_calibration.py
git commit -m "test: replace stale recurrence false-point expectation"
```

---

### Task 3: Restart Geometry Calibration and Return to Existing User Gate

**Gate:** calibration partition only. Stop after reporting result; existing geometry Task 9 validation still requires user approval.

**Files:**
- Modify (generated): `hydroseason/_scientific_defaults.py`
- Create: `docs/calibration/trough-geometry-calibration.json`
- Modify: `.superpowers/sdd/progress.md`

**Interfaces:**
- Consumes: Tasks 1-2 and corrected recurrence evidence.
- Produces: fresh geometry tuple/fingerprint and a precise continuation point at existing geometry Task 8.

- [ ] **Step 1: Confirm validation partition remains unopened**

Run:

```powershell
Test-Path docs\calibration\trough-geometry-validation.json
git status --short
```

Expected: validation report absent. If present from an earlier unauthorized run, stop and report contamination before continuing.

- [ ] **Step 2: Run geometry calibration from scratch**

Run:

```powershell
python scripts\run_calibration.py --trough-geometry --partition calibration --num-geometry-seeds 240 --out-report docs\calibration\trough-geometry-calibration.json
```

Expected: exit 0; 5,760 detections evaluated (240 seeds x 24 grid points),
report written, generated defaults gain or replace exactly one geometry block.
Confirm the last part rather than assuming it:

```powershell
python -c "import pathlib; text=pathlib.Path('hydroseason/_scientific_defaults.py').read_text(encoding='utf-8'); print(text.count('TROUGH_GEOMETRY_DEFAULTS'), text.count('RECURRENCE_POLICY'), text.count('TIMING_IDENTIFIABILITY_DEFAULTS'))"
```

Expected: `1 1 1`. Each constant is named exactly once, on its assignment
line; the block markers spell the names with spaces, so they do not add to the
counts. A `2` in the first column means the geometry block was appended twice.
`TIMING_IDENTIFIABILITY_DEFAULTS` reads `1` today, before any geometry or
recurrence block exists.

If the false-precision gate still raises, stop and record residual rows as an
open corpus-label question; do not proceed to validation.

- [ ] **Step 3: Print exact result and selector path**

Run:

```powershell
python -c "import json; p=json.load(open('docs/calibration/trough-geometry-calibration.json')); print(json.dumps(p['geometry'], indent=2)); print(p['fingerprint']); print(json.dumps(p['metrics'], indent=2)); print(json.dumps(p['selection_counts'], indent=2)); print(json.dumps(p['tie_breaks'], indent=2))"
```

Record exact tuple, fingerprint, false-precision interval, every metric, survivor counts, and deciding stage. Do not call a tie-break result a metric win.

- [ ] **Step 4: Verify generated artifact linkage**

Run:

```powershell
python -c "import json; from dataclasses import asdict; from hydroseason._scientific_defaults import TROUGH_GEOMETRY_DEFAULTS,TROUGH_GEOMETRY_FINGERPRINT; from hydroseason._calibration import trough_geometry_fingerprint; p=json.load(open('docs/calibration/trough-geometry-calibration.json')); assert asdict(TROUGH_GEOMETRY_DEFAULTS)==p['geometry']; assert TROUGH_GEOMETRY_FINGERPRINT==p['fingerprint']; assert trough_geometry_fingerprint(TROUGH_GEOMETRY_DEFAULTS)==TROUGH_GEOMETRY_FINGERPRINT"
python -m pytest tests/test_scientific_defaults.py tests/test_calibration.py -q -k "geometry or recurrence"
```

Expected: PASS.

- [ ] **Step 5: Update progress ledger**

Append under the paused Task 8 section:

```markdown
## RECURRENCE CORRECTION COMPLETE; TASK 8 RE-ENTERED

The recurrence-identifiability correction plan completed under 0.2.0. Geometry
fingerprinting now includes window timing and the frozen recurrence policy.
The stale 8/64 false-point expectation was removed without weakening the gate.
Task 8 calibration was restarted from seeds 30000..30239; exact tuple,
fingerprint, metrics, and selector path are in
`docs/calibration/trough-geometry-calibration.json`.

Next action: report Task 8 outcome to user. Do not run Task 9 validation until
user selects the branch and explicitly approves opening the untouched partition.
```

- [ ] **Step 6: Stop and hand back to existing plan**

Report Task 8 result. Continue from `docs/superpowers/plans/2026-09-02-trough-window-geometry.md` Task 8 Step 3, using actual report values for its literal freeze test. Then follow its user branch gate, Task 9 untouched validation, conditional Task 10 cohort, and Task 11 decision. Do not duplicate or bypass those gates here.

Do not commit generated geometry defaults/report until existing Task 8's freeze test is completed and the user approves the recorded result.

---

## Self-Review Notes

- Fingerprint transitive gap: Task 1 explicitly hashes all three missing functions and the one selected recurrence value that affects detection (`RECURRENCE_POLICY`); `RECURRENCE_FINGERPRINT` is deliberately excluded and the exclusion is itself asserted (see Audit Fixes).
- Stale 8/64 assertions and narratives: Task 2 removes both named locations while preserving `tied_low_plateau_wide` protection.
- Falsifiable 0/64 prediction: Task 2; failure stops rather than weakening gate.
- Cache restart: Task 3 uses all 240 calibration seeds after fingerprint correction.
- Untouched validation: Task 3 checks absence and stops before Task 9.
- Version/policy scope: Global Constraints preserve 0.2.0 and candidate 0.3.0 geometry authority.
- Existing plan continuity: Task 3 hands back at exact Task 8 Step 3, then Tasks 9-11.
- Placeholder scan: runtime tuple/fingerprint are read from generated report; plan contains no fake literals.
- Type consistency: `trough_geometry_fingerprint(TroughGeometry | None) -> str` remains unchanged.

## Audit Fixes (2026-09-03)

- 0/64 is now measured rather than predicted; the four `missing_outer_months`
  seeds go from `n_false == 8.0` to `0.0` once recurrence narrowing is removed,
  under both policies that can win calibration.
- The geometry defaults writer is append-only with no markers, so "gain or
  replace one geometry block" was not achievable as written. The correction
  plan's Task 6 now fixes that writer, and Task 3 verifies single occurrence
  instead of assuming it.
- `defaults.RECURRENCE_POLICY` is guarded so a skipped prerequisite reports
  itself, while staying literal for the Step 1 source-dependency test.
- **`RECURRENCE_FINGERPRINT` decoupled from the geometry hash (2026-09-04).** The correction plan's Task 11 blinded-cohort gate has no eligible uninspected source root, so promotion to `established_0_2_0` is withheld indefinitely and recurrence ships at `candidate_for_established_0_2_0` scope. Hashing `RECURRENCE_FINGERPRINT` would have forced geometry re-entry to wait behind that unresolved gate even though authority scope has no effect on geometry detection, and would stale every geometry result the moment promotion eventually lands on `metrics_changed: False, policy_changed: False` alone. Geometry now hashes `RECURRENCE_POLICY` and `narrow_most_recent_recurrence`'s source directly instead, which is what actually determines geometry behaviour. The prerequisite in Global Constraints was updated to match: frozen policy, not established scope.
