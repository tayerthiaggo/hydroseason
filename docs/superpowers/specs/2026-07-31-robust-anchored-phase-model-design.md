# Robust-Anchored Monthly Phase Model - Design Spec

> **Note:** Rule-based phase model scope implemented through Task 4 of the release readiness plan.

Date: 2026-07-31
Status: Draft for implementation planning
Depends on: `2026-07-15-transferable-hydrological-boundary-design.md`
Related audit: conversation decision to keep robust extrema authoritative and
add phases as a separate product

## 1. Purpose

Users now get accurate trough/peak timing from `detector="robust_extrema"`, but
no monthly hydrological **phase** series (`wet`, `recession`, `dry`,
`recovery`). The existing `semi_markov` engine already models those four states,
yet free HSMM trough selection is not promoted and can disagree with robust
extrema.

This design adds monthly phases **without** letting the phase model rewrite
validated annual boundaries, peaks, drawdowns, or condition baselines.

## 2. Decisions

1. **Boundary authority stays with robust extrema.** Default
   `detector="robust_extrema"` remains the shipped annual-boundary engine.
2. **Phase modelling is a separate axis.** New config field
   `phase_model: Literal["none", "rule_based", "semi_markov"] = "none"`.
3. **No `detector="hybrid"`.** Hybrid behaviour is expressed as
   `detector="robust_extrema"` + `phase_model=...`. This keeps boundary
   promotion gates and phase quality gates independent.
4. **Annual metrics are invariant under phase_model.** For a fixed detector and
   inputs, enabling any phase model must leave `hydro_years` columns
   byte-identical (or exact-float identical) to `phase_model="none"`.
5. **Phases are a new public product**, not a reuse of `monthly_condition`.
   `monthly_condition` remains historical relative anomaly / condition. Phases
   are intra-cycle hydrological stage labels.
6. **Ship `rule_based` first.** It is explainable, tied to robust anchors, and
   becomes the baseline comparator for constrained HSMM.
7. **`phase_model="semi_markov"` is constrained and experimental.** HSMM may
   label months only inside resolved robust trough-to-trough cycles. It may not
   move trough or peak dates used by annual assembly.
8. **Free `detector="semi_markov"` remains opt-in experimental** for people who
   still want HSMM-owned boundaries. It is out of scope for this work except
   documentation clarifying the split.
9. **No new mandatory dependency.** NumPy + pandas only.
10. **Missing/unusable months never become boundaries or confident phase
    anchors.**

## 3. Problem statement

### 3.1 What users want

Accurate:

- peak month / trough month
- and monthly phases: wet → recession → dry → recovery → wet

### 3.2 Why free HSMM is the wrong default for this

`fit_semi_markov_boundaries` selects troughs from `dry → recovery` **transition
posterior**, not from observed minima. On short/noisy records EM can exit dry
too early. Promotion gate in `tests/test_detector_comparison.py` is intentionally
`xfail`. Notebooks already document the disagreement with `robust_extrema`.

### 3.3 Why post-hoc overwrite is also wrong

Replacing HSMM trough dates with robust trough dates while keeping a free
`state_path` makes the path and the reported boundary incoherent (dry may end
before/after the reported trough).

## 4. Architecture

```text
prepared monthly extent
        |
        v
 detector (default robust_extrema)
        |
        +--> trough opportunities
        |
        v
 cycle assembly (unchanged)
        |  peak, half-loss, mid-dry, drawdown, pulses, diagnostics
        v
 hydro_years  -------------------------------\
        |                                     \
        | if phase_model != "none"             \
        v                                       \
 phase classifier (rule_based | semi_markov)     \
        |                                         \
        v                                          \
 monthly_phase                                     |
        |                                          |
        v                                          v
 HydrologicalStateResult(hydro_years, monthly_condition, monthly_phase, ...)
```

### 4.1 Config surface

```python
@dataclass(frozen=True)
class DynamicHydroYearConfig:
    ...
    detector: Literal["robust_extrema", "semi_markov"] = "robust_extrema"
    phase_model: Literal["none", "rule_based", "semi_markov"] = "none"
```

Validation rules:

- `phase_model` must be one of the three literals.
- Recommended / default path: `detector="robust_extrema"` + chosen phase model.
- If `detector="semi_markov"` and `phase_model != "none"`, either:
  - **Option A (preferred for v1):** raise `ValueError` asking callers to use
    robust detector for anchored phases, or
  - **Option B:** allow it but document that phases then use HSMM-owned cycles
    and remain experimental.

This design chooses **Option A** for clarity: robust-anchored phases require
robust boundaries.

### 4.2 Public result surface

```python
@dataclass(frozen=True)
class HydrologicalStateResult:
    pattern: SeasonalPatternResult
    config: DynamicHydroYearConfig
    hydro_years: pd.DataFrame
    monthly_condition: pd.DataFrame
    monthly_phase: pd.DataFrame   # NEW; empty frame when phase_model="none"
    data_quality: dict
```

Empty-frame contract when `phase_model="none"`:

- columns present (stable schema)
- zero rows **or** full monthly index with `phase="unspecified"` and
  `phase_status="disabled"`

Prefer **full monthly index + disabled status** so downstream joins on date
never break. Decision for implementation: full monthly index with
`phase_status="disabled"` when phase model off.

### 4.3 `monthly_phase` schema

One row per prepared month:

| Column | Type | Meaning |
|---|---|---|
| `date` | Timestamp (index or column) | Month start |
| `hy_year` | int or NA | Owning dynamic HY if inside a resolved cycle |
| `phase` | category/str | `wet` / `recession` / `dry` / `recovery` / `unspecified` |
| `phase_status` | str | `ok` / `provisional` / `unresolved_cycle` / `outside_cycle` / `disabled` / `unusable` |
| `phase_confidence` | float 0–1 or NA | Rule score or max state posterior |
| `phase_method` | str | `none` / `rule_based` / `semi_markov` |
| `boundary_basis` | str | `robust_extrema` (v1 always when phases enabled) |
| `p_wet` | float or NA | Posterior / soft score (rule_based may leave NA) |
| `p_recession` | float or NA | |
| `p_dry` | float or NA | |
| `p_recovery` | float or NA | |
| `extent_pct` | float | Pass-through for plotting |
| `candidate_usable` | bool | Pass-through |

Hard labels always come from argmax of available soft scores when present;
rule-based may set only hard `phase` + heuristic confidence.

## 5. Phase models

### 5.1 Rule-based (v1 ship target)

Operate only inside complete/partial cycles that have both:

- previous trough boundary
- current trough boundary
- selected peak

For cycle spanning `(previous_trough, current_trough]`:

```text
months after previous_trough up to and including peak:
    early rising limb -> recovery until first month that is:
        - at/above recovery_level, or
        - in a contiguous high-equivalent run containing the peak
    remaining pre-peak / at-peak high months -> wet

months after peak up to and including current trough:
    peak -> half_loss_month (inclusive of first half-loss month) -> recession
    after half_loss through trough -> dry
```

More precise algorithm:

1. **Split cycle** at `peak_month` into pre-peak (`start .. peak`) and
   post-peak (`peak+1m .. end`).
2. **Post-peak**
   - If `half_loss_month` is valid:
     - `peak+1 .. half_loss` → `recession` (include half-loss month)
     - `half_loss+1 .. trough` → `dry`
   - Else fallback: midpoint of post-peak span splits recession/dry.
3. **Pre-peak**
   - Compute `mid_level = (peak_extent + trough_extent) / 2` using the
     **starting** trough extent (previous trough) and peak extent.
   - From cycle start forward, label `recovery` while extent is rising or
     still below `mid_level` (with noise tolerance from `robust_scale`).
   - First month that reaches the contiguous high-run containing the peak
     (or first month ≥ mid_level with non-negative slope) starts `wet`
     through peak.
4. **Peak month** is always `wet` if usable; if unusable, `phase_status="unusable"`.
5. **Trough month** is always `dry` if usable (ending dry anchor).
6. **Unusable months** keep positional phase label only if neighbours force
   continuity; else `phase="unspecified"`, `phase_status="unusable"`.
   Prefer: still assign phase by calendar position in the cycle, but mark
   `phase_status="unusable"` and lower confidence. Implementation chooses
   positional assignment + unusable status so phase timelines stay continuous.

Confidence heuristic (rule-based):

```text
base = 0.55
+0.20 if cycle boundary_status == "confirmed"
+0.10 if half_loss_month is not NA
+0.10 if peak_selection_status == "raw"
-0.25 if month unusable
clip to [0, 1]
```

Not a calibrated probability; document as quality grade.

### 5.2 Constrained semi-Markov (v1 experimental)

Goal: use HSMM emission/duration machinery for phases while **forcing**
robust trough anchors.

#### Required API change

Extend `hydroseason/_semi_markov.py` (or add a sibling function) with:

```python
def fit_semi_markov_phases(
    frame: pd.DataFrame,
    *,
    cycle_bounds: Sequence[tuple[pd.Timestamp, pd.Timestamp]],
    # each tuple is (previous_trough, current_trough)
    config: SemiMarkovConfig = SemiMarkovConfig(),
) -> PhaseModelResult:
    ...
```

Constraints:

1. Fit only on months inside resolved cycles (concatenate with hard breaks, or
   fit per cycle if record is long enough — per-cycle preferred when cycle has
   ≥ `min_usable_months_per_cycle` usable months).
2. Force path structure so that:
   - month `current_trough` is labelled `dry` (or is the final month of a dry
     segment)
   - month immediately after `previous_trough` may begin `recovery`
   - no transition is allowed that would place `recovery` before the starting
     trough anchor or extend `wet` past the ending trough
3. Do **not** call free `_select_troughs` for annual products.
4. Return monthly hard path + posterior; ignore free peak selection for annual
   metrics (annual peaks remain robust).

Minimal viable constraint for v1 (if full constrained DP is too large):

- Run free HSMM emissions/Viterbi **per robust cycle segment only**
- Relabel the last month of each segment to `dry` if needed and repair
  illegal transitions with a deterministic cleanup pass that preserves cyclic
  order

Prefer true constrained DP if effort allows; cleanup-pass is acceptable only
with explicit tests that cleanup never moves annual trough/peak fields
(those fields are not produced here anyway).

`phase_confidence = max_k posterior[t, k]`.

### 5.3 Months outside resolved cycles

Leading months before first resolved previous-boundary, gaps after unresolved
years, and trailing incomplete spans:

- `phase="unspecified"`
- `phase_status="outside_cycle"` or `"unresolved_cycle"`
- posteriors NA

## 6. Invariants (must hold in tests)

1. **Annual invariance:**  
   `detect_dynamic_hydrological_years(... phase_model=X)` annual frame equals
   `phase_model="none"` for all existing `ANNUAL_COLUMNS`.
2. **Orchestrator invariance:**  
   `analyze_hydrological_state` annual condition columns unchanged when only
   `phase_model` changes.
3. **Phase alphabet:** hard labels ⊆
   `{wet, recession, dry, recovery, unspecified}`.
4. **Cycle-internal cyclic order:** within each resolved cycle, ignoring
   unusable months, hard labels follow subsequence of the cyclic order
   `recovery → wet → recession → dry` (wrap only across cycle boundary, not
   inside).
5. **Anchor consistency (rule_based and constrained semi_markov):**
   - trough month → `dry` when usable
   - peak month → `wet` when usable
6. **No network I/O in tests.**
7. **Internals stay unexported** unless deliberately added to public API:
   phase helpers remain submodule-private; public access is via
   `analyze_hydrological_state` / optional thin wrapper.

## 7. Non-goals

- Promoting free `detector="semi_markov"` to default.
- Using phase labels as condition baseline inputs.
- Depth/volume/discharge inference.
- Multi-peak bimodal secondary-phase decomposition beyond primary cycle
  (secondary extrema remain descriptive annual fields only in v1).
- Calibrated probabilistic scoring for rule-based confidence.
- Plotly/report UI polish beyond a minimal optional strip (can be follow-up).

## 8. Validation

### 8.1 Synthetic unit fixtures

- Clean monsoonal sinusoid: phases occupy expected quadrants.
- Flat dry plateau: long terminal `dry`, trough at robust minimum.
- Mid-dry rewetting pulse: pulse months stay inside same cycle; may briefly
  rise within `dry`/`recession` without spawning a new HY (boundary authority
  still robust).
- Missing month in trough window: no phase/boundary invented on unusable date.
- Half-loss missing: recession/dry fallback still returns full coverage inside
  cycle.

### 8.2 Real fixtures

Use existing Fitzroy + Gilbert monthly fixtures:

- Annual trough/peak regression gates remain green under all phase models.
- Spot-check phase strips in notebook or SVG smoke (non-blocking visual).

### 8.3 Experimental HSMM phase gate (non-blocking)

Optional `@pytest.mark.experimental` comparison:

- rule_based vs constrained semi_markov disagreement rate
- fraction of cycles violating anchor consistency before cleanup
- runtime budget ≤ 5× rule_based

Does not block release.

## 9. Documentation / changelog

- Update `docs/hydrological-state.md`: phase_model section, schema, examples.
- Update boundary design note: phases are additive product; HSMM challenger
  remains boundary-optional and phase-optional separately.
- `CHANGELOG.md` under Unreleased: additive feature.

## 10. Rollout

| Stage | What | Default |
|---|---|---|
| v1a | config + empty/disabled monthly_phase plumbing | `phase_model="none"` |
| v1b | `rule_based` implementation + tests + docs | still `"none"` |
| v1c | constrained `semi_markov` experimental | still `"none"` |
| later | consider default `rule_based` only after user feedback | decision gate |

## 11. Open implementation choices (resolve during plan execution)

1. Index vs `date` column for `monthly_phase` — match `monthly_condition`
   convention.
2. Whether `detect_dynamic_hydrological_years` returns phases or only
   `analyze_hydrological_state` attaches them. Prefer a dedicated
   `assign_monthly_phases(prepared, hydro_years, config)` called from the
   orchestrator so cycle assembly stays pure.
3. Per-cycle vs whole-record constrained HSMM fit.
4. Exact recovery/wet threshold constants for rule_based (noise-relative).

## 12. Success criteria

- User can run:

```python
cfg = DynamicHydroYearConfig(
    expected_trough_month=9,
    detector="robust_extrema",
    phase_model="rule_based",
)
result = analyze_hydrological_state(monthly, config=cfg)
result.hydro_years   # same boundaries/metrics as before
result.monthly_phase # wet/recession/dry/recovery timeline
```

- Robust extrema accuracy preserved.
- Phases available without promoting free HSMM boundaries.
- Constrained HSMM available experimentally for comparison.
