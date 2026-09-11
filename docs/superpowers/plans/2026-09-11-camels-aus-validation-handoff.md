# CAMELS-AUS validation and paper: handoff

**Date:** 2026-09-11
**Branch:** `development`, at `aa179b8`
**Suite:** 1633 passed, 1 skipped, 2 xfailed
**Working tree:** clean (two git-ignored scratch dirs were moved out; see Attic)

This is a cold-start handoff. It records what the method now is, which
decisions are settled and must not be relitigated, and what the CAMELS-AUS
run has to do to actually produce evidence rather than another round of
development.

---

## 1. Where the method stands

`direct_profile_combined` is the end-of-dry-season estimator. It is a
**pass-2 challenger**: pass 1 (`robust_extrema`) selects a coherent trough
sequence, pass 2 estimates the equivalence-state endpoint within each
peak-to-peak span and may refine the boundary, may abstain, and never moves a
peak. When it abstains, pass 1's answer stands with a recorded reason.

Frozen policy — **do not retune before the holdout runs**:

```python
TroughRefinementPolicy(
    huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5,
    version="direct_profile_combined_v1",
    candidate="direct_profile_combined",
    delta_rel=0.05, l_uncertainty_k=2.0, scale_mode="combined",
)
```

Behaviour on the seven inspected catchments (84 cycles): refinement applies
to 77, abstains on 7, each abstention carrying a named reason.

Routing on those seven — the prior for what CAMELS-AUS will look like:

| route | n | note |
|---|---|---|
| `per_year_detection` | 4 | Fitzroy, Gilbert, Daly, Kakadu — 21 cycles each |
| `event_characterisation` (aseasonal) | 2 | Lachlan, Moonie — no hydrological years |
| `event_characterisation` (seasonal) | 1 | Roper — seasonal regime, per-cycle timing too diffuse |

**3 of 7 produce no hydrological years at all.** On CAMELS-AUS this will be
a large group and it is a *result*, not a failure: "how often the record
declines to support annualisation, and why" is the direct evidence for the
paper's central claim. Instrument for it from the first pass (§4).

### Settled — do not reopen

- **Equivalence margin is proportional** (`delta_rel`, a fraction of the
  low-state level), not absolute. An absolute margin cannot serve one
  catchment's own cycles: Fitzroy's trough level spans 0.025–0.052 pp.
- **`delta_rel = 0.05`** is bracketed on both sides by the 42-cycle
  Fitzroy/Gilbert review: Gilbert HY2006's genuinely flat Oct–Dec plateau is
  +4.4% and must stay tied; the smallest recovery that must be excluded is
  +10.4%. It sits at the tie-preserving edge, so it is not fitted to the
  value it must reject.
- **The margin is NOT floored by the noise scale.** The endpoint contract
  keeps δ (hydrological choice) separate from σ (measurement property);
  coupling them would make identical hydrology disagree on cloudier records
  and would push boundaries later. σ governs *confidence* instead —
  `recovery_within_noise` downgrades to `provisional` without moving the date.
- **Representative date is the latest month of a genuine tie.** A resolvable
  recovery returns the trough; a real plateau is reported at its end.
- **Untrusted months (`quality_state == "low"`) carry zero weight** in the
  profile solve, and cannot define the reference level, be the departure
  candidate, or anchor the support cluster.
- **Abstention policy stays unanimity** among evaluable scenarios. Majority
  voting was measured (§7) and deliberately rejected for now.
- **`shape_fit` is frozen.** Verified unchanged on all 84 cycles through
  every change this session; only its calibration fingerprint moves.

---

## 2. The thing that must not be spent by accident

Every CAMELS-AUS catchment is currently **uninspected**. That makes them the
blinded holdout this work has never had — the single gap a referee will go
straight for, because `delta_rel` was set from the same cycles it is then
evaluated on.

That status is **single-use**. Once results are looked at, no amount of later
care recovers it.

So: **split before running, not after.** Reserve a sealed partition (suggest
one third) opened only when the method is final. Run the remainder for the
operational, scale and routing checks. If all 561 are opened at once you have
a larger study with exactly the same test-set-fitting objection.

---

## 3. Pre-registration checklist (before any CAMELS result is seen)

Commit these, dated and hashed:

- [ ] The frozen policy tuple above, with the source fingerprint.
- [ ] Metrics and pass/fail gates.
- [ ] Abstention accounting, with **both** denominators — applied/resolvable
      and applied/all — the conflation of these was a prior review finding.
- [ ] Adjudication procedure: reviewer count, blinding, double-review fraction.
- [ ] The sealed-partition catchment list (IDs only, results unopened).

---

## 4. CAMELS-AUS pipeline

Ordered. Steps 1–3 are safe on the full set; the holdout is only spent at 5.

1. **Extract monthly extent.** Run the standard DEA WOfS acquisition per
   catchment boundary to produce `extent_pct` / `invalid_pct` monthly CSVs —
   the same format as `case_studies/data/extent/*.csv`. This output directory
   becomes the cohort builder's `--source-root`.
   Boundaries: `CAMELS_AUS_v2_Boundaries_adopted.shp` (561 catchments).
   Note `output/wofs_cache` was moved to the Attic (§8); restore it or accept
   a cold cache.

2. **Record routing for every catchment from the start.** Capture `regime`,
   `route`, `route_reason`, cycle count, and per-cycle
   `trough_refinement_status` / `trough_refinement_reason`. This gives the
   annualisation-declined result with no re-run. Do this in the same pass as
   extraction.

3. **Runtime.** Measured: 14–30 s per seasonal catchment with refinement on,
   ~0.5 s off; aseasonal catchments cost nothing (they never reach per-year
   detection). Projected **~112 min single-core for 561**, embarrassingly
   parallel per catchment. Not a blocker — do not optimise pre-emptively.

4. **Freeze the split.** With routing known, draw the sealed partition
   stratified by regime/route so the holdout is not accidentally all
   aseasonal. Commit the ID list.

5. **Build the blinded cohort** from the non-sealed partition:
   ```
   scripts/build_trough_refinement_cohort.py \
       --source-root <camels extent dir> --protocol <new protocol> --output-dir <out>
   ```
   The builder already enforces the two properties that make this evidence:
   packets carry only `packet_allowlist` columns (the reviewer never sees
   either algorithm's answer), and catchments are the sampling unit with the
   double-review subset drawn from a frozen seed before labelling.

6. **Label, then score** with `scripts/evaluate_trough_refinement_cohort.py`.

### Two gaps that block step 5

- **A new protocol version is required.** The existing
  `case_studies/trough-refinement/cohort-protocol.json` is
  `trough-refinement-span-cohort-v1`, frozen for `shape_fit`'s target. Its
  labels were collected for a different question; reusing them for the
  equivalence-state target would be scoring one candidate against another's
  labels. Write `v2` with labels matching the equivalence-state endpoint
  (point / interval / no-boundary), keeping `min_algorithm_point_predictions:
  73` — that is the Wilson bound requirement for the zero-error
  false-precision gate, and the cohort **must not be enlarged after results
  are seen**.
- **`excluded_sources` needs extending.** It currently matches by substring
  on path and token, and already lists `daly`, `fitzroy`, `gilbert`,
  `lachlan`, `moonie` plus gauge IDs `130413a`, `130407a`, `130302a`.
  CAMELS-AUS contains those same rivers as gauged catchments — **verify their
  CAMELS gauge IDs and exclude them explicitly**, and add Kakadu and Roper,
  which were inspected this session and are not yet listed.

---

## 5. Immediate work not needing CAMELS data

- **Rebuild the synthetic matrix multi-scale.** Agreed, not started. Every
  family in the Stage B corpus currently sits at the same low-state level
  (0.12 × 100 = 12.0 pp), so the corpus is structurally incapable of
  distinguishing an absolute margin from a proportional one — it neither
  validates nor refutes the central design decision. Varying the low-state
  level across families turns a dead corpus into real evidence. Files:
  `case_studies/results/low-state-direct-profile-v2/evaluate_direct_profile.py`
  (`FAMILIES`, `DELTA_PP`) and `validate_direct_profile.py`. Note the truth
  function `declared_endpoint_index` is defined in terms of the margin, so it
  must move to the proportional definition too — this is a Stage A protocol
  revision, not a knob change.
- **Optional performance.** `_robust_location` is called 632k times per
  catchment via the isotonic branch fit in `fit_with_reference_level` (171k
  calls). Those branches depend only on `start` and `end`, **not on `L`**,
  yet are recomputed for all 17 grid levels. Hoisting them out of the L loop
  is behaviour-preserving and worth ~an order of magnitude on the inner loop.
  Unnecessary at current runtime; verify outputs byte-identical if done.

---

## 6. Paper

Target: WRR / Journal of Hydrology / an environmental-software venue.
Scope: the whole HydroSeason pipeline. Methods capped at **2000 words**.

Draft lives outside the repo (`current_methods.md`). State:

- **Blocker: the seasonality material is duplicated four times** — the
  climatology/amplitude/SNR block and the circular-statistics/classification
  block each appear in four near-identical versions. Cutting to one recovers
  ~500–600 words, which is close to what the missing section needs.
- **Missing: the boundary-refinement section.** A ~430-word draft at journal
  register was produced this session and belongs immediately after
  "Annual-cycle gate and routes", which currently describes pass 1 only. It
  is in the session transcript; regenerate from the endpoint contract and
  numerics spec if lost.
- **Citations.** The circular-statistics references (Hall & Blöschl, Mao,
  Villarini) are genuine and correctly used. The SNR ≥ 2.0, R ≥ 0.70,
  p = 0.10, 20% invalid, 3/1/1 noise multipliers and `delta_rel` are
  **implementation policy with no literature source** — the draft already
  says this and it should stay prominent. Do not let a reviewer think
  otherwise, and do not fabricate a citation for them.
- **Abstention belongs in the abstract.** 7 of 84 cycles declined with a
  named reason each. Most methods in this space report a number for every
  cycle and never say which ones the data could not support.

### Sequencing point

`direct_profile_combined` is approved as *the paper's method*, but it is
still marked opt-in and not promoted in code. Promotion is gated on exactly
the holdout CAMELS-AUS will provide. **Do not flip it to the default before
that holdout runs** — otherwise the promotion pre-dates its own evidence,
which is the first thing a referee would notice.

---

## 7. Measured but rejected

Recorded so it is not re-derived. Abstention policy options, measured across
63 dev cycles:

| option | applied | fixes Daly 2005 | fixes Daly 2011 |
|---|---|---|---|
| unanimity (**kept**) | 54 | no | no |
| majority vote | 60 | no | yes |
| skip per-month masking (**adopted**, see `aa179b8`) | 61 | yes | no |
| both | 62 | yes | yes |

Majority voting was rejected: it needs an underived threshold and silently
outvotes genuine minority information (one Daly 2011 scenario answers
`2012-02`, a real signal that an 84.6%-invalid December could hide a much
later end). **Daly HY2011 therefore still publishes pass 1's September** —
a defensible abstention about a badly-clouded record, and only one month
from the tie. Revisit only with new evidence, not new preference.

---

## 8. Attic

Moved out of the repo during cleanup, all git-ignored, nothing tracked:

`D:\RLH\5.6\repos\_hydroseason_attic_20260910\`

| item | size | note |
|---|---|---|
| `data/catchments/` | 363 MB | boundary/stream inputs for the multi-catchment scripts |
| `output/wofs_cache/` | 99 MB | **restore before the CAMELS run** or accept a cold cache |
| `.tmp-audit-full-20260906/` | 96 MB | earlier session scratch |
| `.tmp-codex-fix-review-20260909/` | 1 MB | earlier session scratch |

`output/water_extent_csv/` was deliberately **kept** in the repo —
`build_catchment_reports.py` reads the Roper CSV from it.

---

## 9. File map

| what | where |
|---|---|
| estimator | `hydroseason/_trough_refinement_direct_profile.py` |
| ensemble, policy, dispatcher | `hydroseason/_trough_refinement.py` |
| frozen policy | `hydroseason/_trough_refinement_direct_profile_defaults.py` |
| tests | `tests/test_trough_refinement_direct_profile.py` (28) |
| formal target, σ/δ separation | `docs/superpowers/specs/2026-09-09-low-state-endpoint-contract.md` |
| estimator spec | `docs/superpowers/specs/2026-09-09-low-state-direct-profile-numerics.md` |
| validation protocol | `docs/superpowers/specs/2026-09-09-low-state-validation-protocol.md` |
| defect analyses, evidence, limits | `docs/migrations/trough-refinement-candidate.md` |
| reason codes | `docs/report-columns.md` |
| reports for review | `case_studies/results/low-state-direct-profile-v2/html_reports/` |
| cohort builder / evaluator | `scripts/build_trough_refinement_cohort.py`, `scripts/evaluate_trough_refinement_cohort.py` |

Two staleness guards hash `_trough_refinement.py`'s source and will fail
after any edit to it. Regenerate with:

```
scripts/run_calibration.py --trough-refinement --fixed-trough-policy
scripts/evaluate_final_pipeline.py --output-dir case_studies/results/final-review-2026-09-08/validation
```

`shape_fit`'s policy values must come back byte-identical — only the
fingerprint should change. If anything else moves, stop.
