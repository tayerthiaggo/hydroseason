# DE1: where the dry season ends, against known truth (pre-registration draft)

Status: the project lead confirmed every recommended choice on 2026-11-05 (see the end). Not yet frozen: the freeze follows the checks below. Analysis behind it: [2026-11-05-dry-run-end-analysis.md](2026-11-05-dry-run-end-analysis.md).

## Why

On records whose dry season sits flat at its lowest level, the trough boundary lands near the start of the flat run, not its end. The search window is centred on one calendar month, it cuts the run at its edge, and a tie among equal minima goes to that month. On the Fitzroy tiles the boundary falls before the end of its low run in 54% of cycles, by three months or more in 19%; on small real-record units in 34–50% of cycles. hydropools reads the boundary as the end of the dry season.

The lead chose route A + B (2026-11-05):
- **A. Report the dry run.** Each cycle gets the start and end of its low run, its length and a status for the end.
- **B. Move a tied boundary to the end of its run,** so the hydrological year starts when water returns.

DE1 asks one question: **is the end of the low run a more accurate end of the dry season than today's boundary, without making smooth seasons worse?** A and B use the same dates, so DE1 decides both. Their knock-on effects (year membership, phases, labels, baselines) are checked afterwards, as for 0.3.0.

### History that shapes the design

- **A removed rule.** Before July 2026 the detector had `dry_plateau_rule="last_before_confirmed_recovery"`, a state machine with a fixed rise length (2 months) and rejection window (4 months) that mid-dry rain pulses defeated. It was replaced by the current detector, which lets any month of a tied run be chosen for cycle-length consistency. The field survives but is ignored. DE1's candidate has no rise length or rejection window: the run ends at the first observed month above the boundary's own tolerance.
- **R1** ([results](2026-11-03-l2-r1-results.md)) tested a 20%-amplitude rise. It beat the boundary on `pulse` seasons (0.80 against 0.54 in arm S) and lost on `sine`. DE1's candidate moves a date only when the minimum is a run of tied months, so on a V-shaped trough it changes little or nothing. Rule 2 tests that.

## The candidate

All quantities come from the library's own monthly frame (`prepare_monthly_extent`) and tolerance (`_epsilon_pp` at the boundary month), as in `scripts/dry_run_end_exploratory.py`.

- **Observed month:** extent present and `invalid_pct` at most `max_invalid_pct` (20), the library's usable rule. Other months are unobserved: they neither extend nor end a run.
- **Low run of a boundary t:** starting at t, with level L = extent at t and tolerance ε, the observed months on either side whose extent is at most L + ε, continuing over unobserved months, until the first observed month above L + ε on each side.
- **Run end e** (end of the dry season): the last observed month of the run after t. **Re-wetting month w:** the first observed month above L + ε after e.
- **Run start s:** the first observed month of the run before t.
- **End status:** `point` when w is the month right after e; `interval` when unobserved months lie between e and w (the end is somewhere in e to w − 1); `censored` when the record ends before any w.
- **B's boundary:** t moves to e when e is later than t and no later reported boundary lies at or before e. When a run spans more than one boundary (a year with no wet season), only the last boundary in the run moves; the earlier ones stay, so there is still one boundary per year.

Mid-dry rain pulses end the run: a zero-flow period ends when flow resumes (Snelder et al. 2013; Tramblay et al. 2020). DE1 scores against the wet-season onset, so a pulse before the onset counts against the candidate. That cost is reported.

## Principles

- **Known answer.** Every season's onset is set before any method sees the record.
- **Not referenced to gauges.** The truth is the generator's water extent, not flow.
- **Fresh records.** No seed overlaps G2, L1, L2/R1 or B2.
- **Library untouched.** One run of the current library (`hydroseason-v0.3.0`) per record. The current end of dry is its boundary; the candidate's is computed from the same run. The scorer reproduces the library's within-window `low_run_start_month`/`low_run_end_month` on every cycle before extending them.
- **Default is no change.**

## Records

### Shapes

- **`ephemeral` (new).** No water except a short wet season. Per record:
  - mean onset month uniform over the 12 months;
  - per-year onset jitter uniform over −2 to +2 months;
  - wet length uniform over 1, 2 or 3 months, with profiles [1.0], [0.6, 1.0] and [0.6, 1.0, 0.5] of the year's peak, then one month at 0.2;
  - each year has no wet season with probability q, where q is Uniform(0, 0.3) per record;
  - each wet year has one mid-dry pulse with probability r, where r is Uniform(0, 0.15) per record: one month at Uniform(0.05, 0.3) of the peak, at least two months from the wet months.
- **`pulse` and `sine`:** G2's shapes, unchanged.

### Arm S (synthetic)

G2's synthetic generator, unchanged for `pulse` and `sine`:
- 20 years (2006–2025);
- cloud borrowed from real G1 windows;
- noise σ = amplitude / k with k from 10^Uniform(log 0.5, log 30), plus 4% spikes;
- binomial pixel draws.

For `ephemeral`:
- the dry level is 0;
- the peak is 10^Uniform(−2.5, −0.5);
- the area is 10^Uniform(1.5, 4.5) pixels (31 to about 32,000), so the smallest matches tile13.

### Arm I (injected)

The same seasons injected into G2's 287 real flat half-series. As in G2, the peak is k × the background's noise in pixels. The background's own level and fluctuations stay in the record.

### Sets and seeds

| | Arm S | Arm I |
| --- | --- | --- |
| `ephemeral` | 1,200 (seeds 300000–301199) | 574 (2 per background) |
| `pulse` | 400 (301200–301599) | 287 |
| `sine` | 400 (301600–301999) | 287 |
| Seeds | | 305000–306147 |
| Pilot | 200 (308000–308199) | 80 (309000–309079) |

## Truth and pairing

- **True end of the dry season:**
  - `ephemeral`: the month before each wet season's first wet month;
  - `pulse`: G2's boundary truth, month m, the month before the rise;
  - `sine`: G2's boundary truth, month m or m + 1.
- **Pairs.** A reported boundary t is scored when it is the last reported boundary before a reported peak p.
  - Its truth is the latest true end of the dry season before p.
  - The current date is t; the candidate date is e.
  - Both are scored against the same truth, and p is the same for both, because the candidate moves no peak.
- **Correct:** within one month of the truth.

## Decision rules

Differences are candidate minus current, with 95% bootstrap intervals over records (2,000 draws).

1. **The candidate dates the end of the dry season better on ephemeral seasons.** On `ephemeral`, the lower end of the interval for the difference in share correct is above 0, in each arm.
2. **It does not make smooth seasons worse.** On `sine`, the lower end is at least −0.05, in each arm, as in B2's rule 1.
3. **`point` ends are safe (the 0.2.0 safety rule).** Among candidate ends with status `point`, all shapes pooled, the 95% Wilson upper bound of the share not correct is at most 0.05, in each arm.

## Reading, fixed in advance

- **Rules 1 and 2 hold in both arms:** A and B go to implementation and the implementation checks (below), then to the lead as candidate changes for `hydroseason-v0.4.0`.
- **Rule 1 holds and rule 2 fails:** B is not adopted; the boundary stays. A goes to the lead as a reported column, with the `sine` result stated as its limit.
- **Rule 1 fails in either arm:** neither is adopted. The library is unchanged.
- **Rule 3 fails:** whatever is adopted reports the end status as `interval` or `censored` only, never `point`.
- **Anything else:** inconclusive, and the default is no change.

## Reported, not used to decide

- `pulse` seasons under rules 1 and 2.
- By ratio band (3–4, 4–6, 6–10, 10 and up), area, years with no wet season, and years with a mid-dry pulse.
- Signed errors of both dates, run lengths, and the share of pairs where the candidate moves the date.
- End status counts and the accuracy of each status.
- The aggregate timing of paired cycles if their boundary moved, graded two ways: by the span of the widened trough label (0.3.0's rule) and by the end status (the proposal in the next section).
- Coverage: the share of true wet seasons with a scored pair.
- **Real records,** from the stored v0.3.0 real-record runs and the Fitzroy tile runs, extended past the window with the same code:
  - how many boundaries would move, and by how much;
  - for G1 windows, end-of-dry agreement between the two pixel halves of the same place (within one month), current against candidate.

## Checks before the freeze (no accuracy computed on the main corpus)

1. **Generator identity.** For 20 seeds, `pulse` and `sine` records equal G2's generator output exactly.
2. **Construction.** Noise-free, cloud-free `ephemeral` records:
   - the candidate's end equals the truth in every wet year without a mid-dry pulse;
   - the current boundary's months are recorded, to show the tie-break in the generator.
3. **Scorer identity.** On the pilot, the scorer's within-window runs equal the library's `low_run_start_month`/`low_run_end_month` on every cycle.
4. **Pilot.** 280 records, once. Only run times, pair counts and the share of cycles whose boundary lies before its run end are looked at; the last confirms the generator reproduces the behaviour seen on the Fitzroy tiles.
5. **Freeze.** A receipt records the SHA-256 of this plan, the DE1 script and the G2, L1 and L2/R1 scripts it imports, the seed ranges and the library fingerprint.

The run is about 3,150 records, one library run each, comparable to B2 (3 h on a shared machine).

## Interaction with hydroseason-v0.3.0

0.3.0 does not change where the dry season ends: on tiles 05 and 13 no trough label changed and neither tile has condition labels under either version ([tile results](2026-11-05-v0.3.0-fitzroy-tiles.md)). Its rules bear on A + B as follows:

- **The trough label covers the boundary** (rule `covers_trough_boundary`). If B moves a boundary to the end of a long run, the label widens over the whole run and is graded by its width. On the Fitzroy tiles (exploratory, from the dry-run measurement) the boundary would move in 50% of cycles, and about 210 cycles (13%) would become `unresolved`. In 0.3.0 an `unresolved` year has no monthly phases and cannot anchor the condition baseline.
- **Proposed resolution, for the implementation stage:** a moved boundary takes its timing from its end status (`point` or `interval`; `censored` reads `unresolved`), because its date is the re-wetting transition, not a single lowest month. The trough label keeps reporting the run's span in `trough_interval_start`/`_end`. On the tiles this would grade about 520 moved cycles `point`, against 107 `point` today, so it stands only if rule 3 holds; if rule 3 fails, a moved boundary is `interval` at best. The lead decides at implementation; DE1's rules do not depend on it.
- **Any dated cycle anchors the baseline.** With the proposal above, moved cycles graded `point` or `interval` can anchor condition baselines, so near-ephemeral tiles could gain them. Refuge labels there rank a trough extent that is zero in most years, which carries little information; this is reported at implementation.
- **The fingerprint covers the rules.** The run rule and the moved-boundary rule join the manifest, so any change gets a new policy id.

## After a pass: implementation checks

1. Implement A and B in the library under a new policy id, with unit tests for each rule, including multi-year runs and unobserved months.
2. Five case studies and the Fitzroy tiles, before against after. Only the columns A and B name may differ: the new run columns, boundaries and what follows from them (year start and end, monthly phases, mid-dry, trough labels, baselines). Peaks must not move.
3. The real-record rerun: route and cycle-count changes, baseline coverage, and the hydropools end-of-dry clock on the tiles.
4. Docs, CHANGELOG, manifest, full suite, and the lead's approval.

## Limits stated in advance

- **The truth is the generator's.** The `ephemeral` shape was designed after seeing Fitzroy tiles 05 and 13; its parameters are set here, not fitted.
- **One candidate.** The alternative end, the last low month before the next peak (which spans mid-dry pulses), is not tested. Its cost and benefit show in the pulse breakdown.
- **Monthly resolution.** A wet season that starts and ends within one month's composite is invisible.
- **Arm I's truth leaves out the background's own wet and dry years.**
- **Not accuracy for real places,** and not referenced to gauges.

## Choices confirmed by the project lead (2026-11-05)

The lead confirmed every recommended option.

1. **Cloudy months:** months above 20% invalid are unobserved, so a cloud-hidden wet month cannot extend the dry run.
2. **Mid-dry pulses end the run,** the zero-flow-period convention. The last low month before the next peak is not tested.
3. **Years with no wet season:** only the last boundary in a run moves, keeping one boundary per year.
4. **Margins:** rule 2 at −0.05 (as B2) and rule 3 at 0.05 (the 0.2.0 safety rule).
5. **The `ephemeral` generator and the set sizes** as above.

Added after confirmation, before the freeze: the section on the interaction with `hydroseason-v0.3.0` and the matching reported measure. Neither changes a decision rule.
