# Local-Extrema Trough/Peak Detection — Redesign Plan

Date: 2026-07-15
Status: Superseded by `2026-07-15-transferable-hydrological-boundary-detection.md`
Related: `docs/superpowers/specs/2026-07-15-hydrological-state-design.md`,
`docs/superpowers/plans/2026-07-15-hydrological-state-module.md` (Tasks 1-8,
implemented and merged), `.superpowers/sdd/task-8-report.md` (the Fitzroy
regression finding that motivates this plan)

## 1. Problem

Task 8 of the hydrological-state module plan validated the dynamic detector
against real Fitzroy River (Kimberley) DEA Water Observations data (132
months, 2015-2025). The result: only **2 of 11** hydrological years reached
`status="complete"` under the plan's default configuration
(`sustained_rise_months=2`, `pulse_rejection_window_months=4`). The other 9
sat at `unresolved` (`recovery_not_confirmed`) or `partial`
(`no_previous_boundary`) — not wrong, but refusing to commit to an answer for
82% of the record.

The two years that *did* resolve were accurate: trough dates matched the
legacy detector exactly, peak dates matched within 1 month. So the underlying
per-year cycle metrics (Task 4's `detect_dynamic_hydrological_years`) are
sound. The failure is narrower and localized to one mechanism: the
recovery-confirmation state machine in `_find_trough_opportunities` /
`_recovery_status` (Task 3), which requires *global* proof — two rising
months followed by four months with no return to the plateau — before it
will commit to any trough at all. On a real monsoonal river where the wet
season is often a brief, sharp spike against a long, noisy dry-season floor,
that confirmation sequence frequently never completes inside the search
window, so the whole year is discarded rather than resolved.

### 1.1 What we tried first, and why it's not enough

An initial response was to auto-tune the two confirmation parameters
(`sustained_rise_months`, `pulse_rejection_window_months`) per input series —
grid-search a small set of values, pick whichever resolves the most years,
warn if the winner is looser than the plan's stated defaults. A manual sweep
of this idea against the real Fitzroy fixture
(`tests/fixtures/fitzroy_kimberley_monthly.csv`) found:

| sustained | rejection | radius | n_complete |
|---|---|---|---|
| 2 (default) | 4 (default) | 3 (default) | 2 |
| 1 | 2 | 3 | **7** |
| 1 | 2 | 5 | 4 |
| 2/3 | 4 | 3-5 | 0-1 |

The best single (sustained, rejection) pair found by the sweep resolved 7/11
years — better, but still short, and the underlying mechanism is unchanged:
it is still a strict multi-month state machine that either fully confirms or
discards an entire year. No single global parameter pair reaches the
remaining 4 years without over-loosening the rule to the point it would
start accepting noise elsewhere. This caps the achievable improvement and
does not address the root cause: **the recovery-confirmation rule is
answering the wrong question.** It tries to prove "the river definitely
recovered" before it will name a trough, when the scientific data need is
simpler: "which month was this year's low point."

### 1.2 The alternative validated in this plan

A **local-minimum trough detector** — pick the observed minimum inside each
year's search window, full stop, no confirmation state machine — was tested
against the same real Fitzroy data:

| Metric | Global recovery-confirmation (default) | Local-minimum |
|---|---|---|
| Troughs resolved | 2/11 | **11/11** |
| Median trough shift vs. legacy | n/a (too few to measure) | **0 months** |
| Peaks resolved (dependent on trough) | 2/11 | **10/11** |
| Median peak shift vs. legacy (calendar-month only, i.e. ignoring the label-year skew documented in `task-8-report.md`) | n/a | **1 month** (within the plan's ≤1.0 gate) |

This is not a tradeoff against the recovery-confirmation approach — it
strictly dominates it on every year the confirmation rule *did* resolve, and
resolves the other 9 as well, all within the plan's own accuracy gates.

It was also checked against the two adversarial cases the
recovery-confirmation rule exists to guard against:

1. **A temporary rain pulse mid-decline, followed by a real, lower trough
   later in the window.** (This is what the Task 7 synthetic benchmark's
   2003 rewetting-pulse fixture exercises.) Result: local-minimum correctly
   ignores the pulse and finds the true lower trough, because by
   construction it can never select a value that is not the window's global
   minimum. Verified against all 30 years of the frozen Task 7 benchmark
   fixture (`tests/fixtures/dynamic_state_mock.csv` /
   `dynamic_state_truth.csv`): 30/30 troughs within 1 month of truth,
   including the pulse year (exact match) and the deliberately-unresolvable
   year 2008 (correctly still needs a missing-data guard — see §3.3).
2. **A single-month data glitch that dips below a real, sustained dry
   plateau.** (Constructed adversarial case, not present in either existing
   fixture.) Result: **local-minimum fails this case** — it selects the
   glitch month over the 4-month plateau, because it has no concept of
   "sustained" at all. This is the one real capability the
   recovery-confirmation rule had that pure local-minimum does not, and this
   plan's design must not regress it silently.

### 1.3 What this plan is

Replace the global recovery-confirmation gate in `_find_trough_opportunities`
with a **local-extrema trough/peak detector**, keeping a lightweight
plateau/tolerance check so a single-month glitch cannot masquerade as the
year's trough. This is a change to the core trough-selection mechanism
introduced in Task 3 of the hydrological-state module plan, not a parameter
change — `_recovery_status`, `_select_low_candidate`, and the
`sustained_rise_months` / `pulse_rejection_window_months` fields on
`DynamicHydroYearConfig` are all superseded by this plan for trough
*selection*, though the rewetting-pulse *counting* metric in Task 4
(`n_rewetting_pulses`) is a separate, already-correct concern (see §3.4) and
is not touched.

## 2. Non-goals

- This plan does not change `detect_dynamic_hydrological_years`'s output
  contract (`ANNUAL_COLUMNS`), `HydrologicalStateResult`, or any public
  function signature. Same inputs in, same shape out.
- This plan does not touch the legacy fixed-calendar path
  (`hydro_year.py`, `HydroYearConfig`, `detect_hydrological_years`,
  `suggest_hydro_year_config`) at all.
- This plan does not re-run or re-tune the seasonality classifier
  (`_seasonality.py`, Task 2) or the condition-percentile logic
  (`_condition.py`, Task 5). Those consume the annual table's columns, which
  are unchanged in shape.
- This plan does not resolve the HY2016-style year-labelling skew between
  the legacy and dynamic detectors' `hy_year` conventions
  (`task-8-report.md` §"Concerns"). That is a separate, smaller
  documentation/test-formula fix (see §6) and is out of scope for the
  detection-algorithm change itself.
- The auto-tuning idea from §1.1 is superseded, not merged alongside this
  plan. Do not implement both.

## 3. Design

### 3.1 Trough selection: local minimum with a plateau-tolerance guard

For each calendar year's search window (`expected_trough_month ±
trough_search_radius_months`, unchanged from the existing contract), among
usable (`candidate_usable`) months:

1. Find the window minimum value, `m`.
2. Find all months within `measurement_tolerance_pct` of `m` — the existing
   `DynamicHydroYearConfig.measurement_tolerance_pct` field, already present,
   reused rather than duplicated.
3. **Plateau check:** if the count of within-tolerance months is `< 2`
   *and* removing the single lowest month would raise the window minimum by
   more than a configurable `glitch_rejection_pct` (new field, default
   `5.0`), treat the lowest month as a candidate glitch: exclude it and
   recompute the minimum from the remaining usable months in the window.
   Repeat at most once (a second single-month exclusion is not attempted —
   see §3.1.1 for why).
4. Resolve the (possibly glitch-corrected) tolerance band to one month using
   the existing `dry_plateau_rule` (`last_before_confirmed_recovery` /
   `middle` / `first`) — but with "confirmed recovery" no longer meaning
   "the state machine completed"; instead, for
   `last_before_confirmed_recovery`, it means "the last month in the
   tolerance band," since there is no longer a recovery state machine to
   confirm against. **Rename this enum value** as part of this plan (see
   §3.1.2) since "confirmed_recovery" no longer describes what happens.
5. If the window has fewer than `min_usable_trough_candidates` usable
   months (existing field, unchanged), the year is `unresolved` /
   `insufficient_trough_candidates` — this status path is unchanged from
   Task 3.

No `boundary_status` of `provisional` is produced by this mechanism anymore
(that concept existed only because the recovery-confirmation window could
run past the end of the record). `boundary_status` becomes `confirmed`
whenever a trough is selected at all, since local-minimum selection does not
depend on future months. **Open question for review:** is a always-confirmed
boundary status acceptable, or should a new, more specific caveat replace it
(e.g. flagging when the record ends before the window's search radius is
fully covered)? See §7.

#### 3.1.1 Why glitch-rejection is bounded to one exclusion, not recursive

Recursive glitch-rejection ("keep excluding the lowest point until the
remaining minimum looks plausible") has no natural stopping rule and risks
excluding a real, if unusual, trough. Bounding it to one exclusion pass keeps
the mechanism auditable (a caller can always see whether the reported
`trough_month` was the raw window minimum or a glitch-corrected one — see
`status_reason` values below) and matches the one adversarial case this plan
was validated against. If real data surfaces a case needing more, that is a
new, separately-justified change, not something to pre-build here.

#### 3.1.2 Naming

`dry_plateau_rule`'s `last_before_confirmed_recovery` literal is renamed to
`last_of_tolerance_band` (or reviewer's preferred name) to stop implying a
recovery confirmation that no longer exists. This is a breaking rename of a
`Literal` value on a dataclass field that shipped in the already-merged
Task 2/3 work. Given the whole `hydrological_state` module is unreleased
(no version tag, no external consumers yet per `git log`), this plan treats
it as a pre-release rename, not a deprecation-cycle change. **Confirm this
assumption with the human before implementing** — if the module has already
been consumed by downstream code outside this repository, a compatibility
shim is needed instead.

### 3.2 Peak selection: local maximum between consecutive troughs

Once trough months for consecutive years are fixed (§3.1), the peak for the
year's cycle is the maximum usable `extent_pct` strictly between the
previous trough and the current trough — this is **unchanged** from Task 4's
existing `detect_dynamic_hydrological_years` logic (`_middle_tie(usable,
"max")`), which already operates this way and does not depend on the
recovery-confirmation machinery. No change needed here beyond the fact that
troughs are now resolved for more years, so more peaks get computed as a
downstream consequence.

### 3.3 Interaction with `status_reason` and the Task 7 benchmark's 2008 case

The Task 7 synthetic benchmark deliberately makes 2008 undetectable by
setting `invalid_pct=100.0` for `2008-06-01` through `2008-12-01` — i.e. the
search window has too few *usable* months, not a shape problem. This plan's
change does not touch the `min_usable_trough_candidates` gate (§3.1 step 5),
so 2008 must remain `unresolved` / `insufficient_trough_candidates` after
this change, exactly as today. This is a required regression check, not
optional — the benchmark's existing assertion
(`annual.loc[annual["hy_year"] == 2008, "status"].item() == "unresolved"`)
must continue to pass unmodified.

### 3.4 `n_rewetting_pulses` is unaffected

Task 4's rewetting-pulse count (`_dynamic_year.py`, computed from
`post_peak.diff() > measurement_tolerance_pct` after the half-loss point) is
a *descriptive* metric about the shape of the decline, computed after peak
and trough are already fixed. It does not participate in trough selection
today and will not after this change. The Task 7 benchmark's assertion that
the 2003 pulse year has `n_rewetting_pulses >= 1` is expected to keep passing
unmodified, since peak/trough dates for that year do not change under
local-minimum selection (verified in §1.2, point 1).

### 3.5 Fields added/changed on `DynamicHydroYearConfig`

| Field | Change |
|---|---|
| `sustained_rise_months` | **Removed.** No longer consumed by trough selection. Removing (not just ignoring) surfaces a clear `TypeError` for any caller who was setting it, rather than silently no-op-ing — reviewer should confirm this is preferred over deprecation-warn-and-ignore. |
| `pulse_rejection_window_months` | **Removed**, same rationale. |
| `glitch_rejection_pct` | **New**, default `5.0`. Documented in §3.1 step 3. |
| `dry_plateau_rule` | Literal value renamed per §3.1.2; default behavior (take the last month of the tolerance band) unchanged in spirit. |
| `measurement_tolerance_pct` | Unchanged, now doing double duty (tolerance-band width AND glitch-check threshold via `glitch_rejection_pct`) — reviewer should sanity-check these two roles don't need separating into two fields. |
| `trough_search_radius_months`, `min_usable_trough_candidates`, everything else | Unchanged. |

This is a **breaking change** to `DynamicHydroYearConfig`'s field set. Given
the module is unreleased (§3.1.2), this plan treats that as acceptable, but
flags it for explicit reviewer sign-off.

## 4. Files touched

- Modify `hydroseason/_dynamic_year.py`: replace `_recovery_status` and
  `_select_low_candidate` with the local-extrema + glitch-guard logic from
  §3.1; remove the two superseded config fields and add
  `glitch_rejection_pct`; rename the `dry_plateau_rule` literal value.
  `_find_trough_opportunities`'s signature and return-row shape are
  unchanged (`hy_year`, `status`, `status_reason`, `trough_month`,
  `trough_extent_pct`, `trough_invalid_pct`, `boundary_status`,
  `phase_shift_months`) — only how `trough_month` is chosen changes.
- Modify `tests/test_dynamic_year.py`: the existing tests written against
  the recovery-confirmation state machine (`test_mid_dry_two_month_rise_is_rejected_when_water_returns_low`,
  `test_final_low_is_retained_as_provisional_when_recovery_window_is_incomplete`,
  and any test asserting `boundary_status == "provisional"`) test behavior
  this plan removes. They must be **rewritten**, not deleted silently —
  each old test's intent (pulse is not mistaken for trough; behavior when
  data runs out) needs a new assertion against the new mechanism, or an
  explicit note in the plan's implementation task explaining why the
  scenario no longer applies.
- New tests: glitch-rejection (§3.1 step 3, both branches — glitch excluded,
  and legitimate low-tolerance-band-of-one NOT excluded), the renamed
  `dry_plateau_rule` literal, and the removed-fields `TypeError` check if
  that's the chosen removal style (§3.5).
- Re-run unmodified: `tests/test_dynamic_state_benchmark.py` (Task 7 gate,
  §3.3 — must stay green with zero threshold changes) and
  `tests/test_fitzroy_regression.py` (Task 8 gate — expected to newly
  **pass** the previously-failing
  `test_dynamic_fitzroy_years_do_not_merge_and_remain_close_to_reviewed_results`
  test; if it does not, that is a plan-blocking finding, not something to
  paper over by loosening that test's threshold).
- Modify `docs/hydrological-state.md`: the existing "Mid-dry rainfall
  pulses" section describes the recovery-confirmation rule this plan
  removes (`docs/hydrological-state.md`, per Task 8's frozen content) — must
  be rewritten to describe local-extrema selection and the glitch guard
  instead.
- Modify `docs/superpowers/specs/2026-07-15-hydrological-state-design.md`
  §6.2 ("Nominal trough opportunities"): describes the mechanism this plan
  replaces; needs a design-doc update alongside (or instead of, per
  reviewer preference) this standalone plan file.

## 5. Testing strategy

Follow the existing project convention (test-first, per-module unit tests,
then the two full-record gates):

1. Unit-level: rewritten `tests/test_dynamic_year.py` cases for local-min
   selection, the glitch guard (both directions), and the renamed literal.
2. Full-suite regression: `python -m pytest -q` must stay green except for
   the Task 8 Fitzroy test flipping from fail to pass.
3. Synthetic benchmark (Task 7, `tests/test_dynamic_state_benchmark.py`):
   must continue to pass with its existing ≥90% thresholds **unmodified**.
4. Real-data benchmark (Task 8, `tests/test_fitzroy_regression.py`): both
   tests must pass, including the previously-failing
   `test_dynamic_fitzroy_years_do_not_merge_and_remain_close_to_reviewed_results`.
   No threshold in that test may be loosened to achieve this — if it still
   fails after implementation, that is a signal the design needs more work,
   not that the gate needs relaxing.
5. New adversarial regression test: the single-month-glitch-vs-plateau case
   from §1.2 point 2, constructed the same way as this plan's validation
   script, added as a permanent test so a future change cannot silently
   reintroduce the glitch vulnerability.

## 6. Follow-up, explicitly out of scope here

- The HY-labelling skew between legacy (`hy_year` can start in December of
  the prior calendar year) and dynamic (`hy_year` is anchored to its own
  trough-to-trough cycle) conventions makes raw `hy_year`-matched month-shift
  comparisons noisy (`task-8-report.md`). `tests/test_fitzroy_regression.py`
  currently compares raw month labels; whether to fix the *comparison
  formula* (calendar-month-only distance, as used for validation in §1.2) or
  leave it as a known caveat is a separate, small follow-up.
- Whether `boundary_status` should carry any signal at all post this change
  (§3.1, "Open question") may want its own short discussion before
  implementation, not resolved unilaterally by whoever picks up this plan.

## 7. Open questions for the reviewing agent

1. Is the one-exclusion-only glitch guard (§3.1.1) sufficiently justified by
   the single adversarial test case in §1.2, or does it need broader
   synthetic-data validation (e.g. added to the Task 7 fixture family)
   before this is trusted as a general mitigation?
2. Is removing `sustained_rise_months` / `pulse_rejection_window_months`
   outright (raising `TypeError` for old callers) the right compatibility
   posture, or should they be accepted-but-ignored with a `DeprecationWarning`
   for one release cycle, given the module is unreleased but may already be
   in use in this repo's own notebooks?
3. Does collapsing `boundary_status` to always-`confirmed` lose information
   that a caller might currently depend on (e.g. `_confidence()` in Task 4
   reads `boundary_status` to apply a confidence penalty) — trace that
   consumer and confirm the confidence-scoring behavior is still sensible
   once `provisional` never occurs.
4. `glitch_rejection_pct` default of `5.0` was not tuned against real data
   the way the trough-selection approach itself was (§1.2) — it is a
   reasonable-sounding placeholder, not an evidence-backed value. Flag this
   explicitly; consider whether the implementation task should validate it
   against the Fitzroy and synthetic-benchmark fixtures before finalizing
   the default.
