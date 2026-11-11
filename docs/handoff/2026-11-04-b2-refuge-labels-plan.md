# B2: refuge (trough) condition labels against known truth (pre-registration draft)

Status: Frozen 2026-11-04. The project lead approved the draft on 2026-11-04 with every open choice as proposed (see "Choices confirmed by the project lead"). The checks and the pilot below ran before the freeze; their outcomes, and the two changes they caused, are recorded in this file. The SHA-256 of this file is in the receipt, written before the main runs. Later edits are reported as deviations. Script: [`scripts/known_truth_b2.py`](../../scripts/known_truth_b2.py).

## Why

Candidate 4 for `hydroseason-v0.3.0` relaxes the condition baseline's timing requirement. Today a cycle can anchor the baseline only if its aggregate `timing_status` is `point` (rule E0). The candidate allows any dated status, `point`, `interval` or `broad` (rule E1).

The evidence so far covers the two condition labels unevenly.

- **Recharge (peak) labels.** B1 ([results](2026-11-03-l1-followups-results.md)) scored them against known truth. On the cycles both rules label, E1 agreed with the truth as often as E0 or slightly more often. On real records ([results](2026-11-03-real-record-impact-results.md)), they repeat between pixel halves as well under E1 as under E0.
- **Refuge (trough) labels.** No test has scored them against a known truth: in B1's corpus the dry level did not vary between seasons, so there was nothing to rank. On real records the pre-registered comparison was inconclusive, and an exploratory measure found lower chance-corrected agreement in the units E1 adds (kappa 0.41 against 0.51).

B2 gives every season a known dry level, so refuge labels can be scored. It asks two questions about relaxing the rule:
1. Where both rules give labels, does E1 make refuge labels less accurate?
2. Do the refuge labels E1 adds carry information about the truth at all?

### What B1 already implies, and why the rules below are not "added minus E0"

The real-record plan compared agreement on the labels E1 adds with agreement on the labels E0 gives. On known truth that comparison mixes two things. It measures the effect of the rule, but also the kind of records each rule reaches. E0 labels only records with at least five `point` cycles, and those have the clearest seasons.

B1's published recharge numbers show the size of this mix ([results JSON](2026-11-03-l1-followups-results.json), recomputed while drafting this plan).

| | Arm S | Arm I |
| --- | ---: | ---: |
| Agreement, cycles E0 labels | 234 of 343 (0.682) | 1,136 of 2,374 (0.479) |
| Agreement, the same cycles under E1 | 248 of 343 (0.723) | 1,194 of 2,374 (0.503) |
| Agreement, cycles only E1 labels | 1,156 of 2,223 (0.520) | 2,018 of 4,842 (0.417) |
| Agreement if labels were independent of truth (E1) | 0.440 | 0.423 |

On the same cycles, E1 is a little more accurate than E0. The labels E1 adds are 0.16 (arm S) and 0.06 (arm I) less accurate than E0's, because they sit in weaker records. In arm I they are no better than chance.

A rule built on "added minus E0" would therefore fail recharge as well as refuge, for a reason the rule does not cause. B2 separates the two questions instead: rule 1 isolates the rule's effect, and rule 2 asks whether the added labels are informative. These numbers were seen before this plan was written, and this section records that.

## Principles

- **Known answer.** Every season's dry level and peak level are set before any method sees the record.
- **Not referenced to gauges.** The truth is the generator's own water extent, not flow. The refuge label ranks the extent at the trough boundary. It is not "the driest month".
- **Fresh records.** No seed overlaps G2's, L1's or L2/R1's.
- **Library untouched.** Labels are recomputed under E0, E1 and E2 exactly as the library calls `classify_annual_surface_water_condition`, using `scripts/l1_followups.py`'s `_conditions`. The recomputation of E0 must reproduce every library label and eligibility flag.
- **Default is no change.** B2 cannot change the library. Its result goes to the project lead with candidate 4.

## Records

### Generators

The generators are G2's `synthetic_record` (arm S) and `injection_record` (arm I) from `scripts/known_truth_gates.py`, with one addition: a dry level that varies between seasons.
- All of G2's draws are made in G2's order from G2's random stream, so every other parameter matches what G2 would give for the same seed. This covers size, peak, low level, k, trough month, shape, year factors, borrowed gaps, noise, spikes and backgrounds.
- The dry levels come from a second stream, seeded `[seed, 0x42320003]`, so they shift no G2 draw.

### The dry level

Each built trough j (at month m of its year) gets its own dry level. In amplitudes of the season:

  w_j ~ Uniform(0, 0.9), independently for each trough.

The spread (standard deviation 0.26 amplitudes) matches the spread of G2's year factor exp(N(0, 0.25)), which sets the peak heights (standard deviation 0.26). So refuge and recharge truth face the same signal-to-noise. The value 0.9 is not fitted.

The dry level of trough j holds from the peak month before it to the month before the peak after it. It changes in a single step at each peak month: month m + 6 for `sine` and m + 2 for `pulse`, in months after the trough. Stepping at the peak, where water is highest, leaves the trough month where G2 built it.

| Arm | Noise-free level in month t of cycle c (trough c to the month before trough c + 1) |
| --- | --- |
| S (fraction of the area) | low + A × (w(t) + f_c × shape(t)), where A = peak − low as in G2 |
| I (pixels, before thinning by the valid fraction and adding to the real background) | rint(P × (w(t) + f_c × shape(t))), where P is G2's injected peak count (k × the background's noise) |

Here w(t) is w_c before the cycle's peak month and w_{c+1} from it on. The noise, spikes, binomial draws and borrowed gaps follow G2 unchanged.

### Sets and seeds

Every record runs once with the current library and `analyze_catchment(..., phase_scheme="two_phase", quality_policy="flag")` on count input. The gates stay at 3.0 and 5 peak pixels, and each run records the method policy fingerprint.

| Set | Seeds | Records |
| --- | --- | ---: |
| Arm S, seasonal | 280000–281999 | 2,000 (`sine` for even seeds, `pulse` for odd); scaled up from 1,400 after the pilot |
| Arm I | 290000–291147 | 1,148 (4 per background, G2's 287 backgrounds: two `sine`, two `pulse`) |
| Pilot (never scored for accuracy) | 295000–295199 (S); 296000–296079 (I, injection i into background 3i mod 287) | 280 |
| Construction (noise-free) | G2's 24 check configurations (seeds 900000–900023), with dry levels added | 24 |

There are no null records. Refuge labels exist only on seasonal records routed to per-year detection.

**Why these sizes.** Rule 1 needs records that E0 labels. In B1, 18 of 600 arm S records and 65 of 574 arm I records had an E0 baseline. Arm S is raised to 1,400 and arm I to 1,148 to aim for at least 40 such records in each arm. The pilot checks this before the freeze. After the pilot, arm S was raised to 2,000 (see "Pilot outcome"). Run time, from the pilot's median per-record times (10.6 s in arm S, 2.0 s in arm I), is about 35 minutes on 12 workers.

## Truth

The truth for each label is the quantity the label ranks, read from the noise-free series at the true month. It is ranked within the record, independent of any eligibility rule.

- **Refuge truth of trough j:** its dry level, d_j = low + A × w_j in arm S, and w_j × P pixels in arm I. The real background's own level is not part of arm I's truth.
- **Recharge truth of cycle c:** the noise-free maximum within the cycle, over all twelve of its months. With a constant dry level this is B1's year-factor truth; here it also carries the dry level, as the observed peak does. Because the dry level steps at the built peak month, the maximum falls in the month before it when the next dry level is much lower. The truth uses whichever month is highest (clarified before the freeze).
- **Reference set:**
  - refuge: every built trough whose month lies inside the record;
  - recharge: every cycle whose noise-free peak month lies inside the record, as B1 used.
- **True label:** B1's `truth_label`. It applies the library's percentile formula, 100 × (number below + half the number equal) / n over the reference set including the season itself, and cuts at 20 (low, at or below) and 80 (high, at or above), as the library does.
  - The library leaves the row itself out of its baseline; the truth keeps it in, as in B1.
  - Continuous draws give no ties.
  - Truth is defined over all seasons rather than the eligible ones, so that both rules are scored against the same answer.

**Matching library rows to the truth.**
- A row's refuge label is scored against the true trough nearest its `trough_month`. That is m for `pulse`, and the nearer of m and m + 1 for `sine`, as in G2, L1 and B1.
- A row's recharge label is scored against the cycle holding its `peak_month`, as in B1.
- Rows whose true trough or cycle lies outside the reference set are not scored, and are counted.

**Labels scored:** the unqualified `refuge_condition` and `recharge_condition`, as in B1 and the real-record study. The qualified labels (`typical_uncertain`) are reported.

## Decision rules (refuge labels)

Both rules are evaluated in each arm, on seasonal records routed to per-year detection. Intervals come from a 2,000-draw bootstrap over records (seed 0).

1. **The rule does not make labels worse where both give labels.**
   - The measure: on cycles labelled under both E0 and E1, agreement with the truth under E1 minus agreement under E0.
   - Holds if the lower end of its 95% interval is at least −0.05.
   - Fails if the whole interval lies below −0.05.
   - Otherwise it is inconclusive.
   - It can be evaluated only with at least 100 such cycles from at least 20 records in the arm. Otherwise it is inconclusive.
2. **The labels E1 adds carry information.**
   - The measure: Cohen's kappa between E1's refuge labels and the truth, on cycles labelled under E1 but not under E0.
   - Holds if the lower end of its 95% interval is above 0.
   - Fails otherwise.
   - It can be evaluated only with at least 100 such cycles. Otherwise it is inconclusive.

**Outcome for refuge labels:**
- **Pass:** both rules hold in both arms.
- **Fail:** either rule fails in either arm.
- **Inconclusive:** anything else.

## Reading, fixed in advance

- **Pass.** On known truth, relaxing does not make refuge labels worse where both rules give them, and the refuge labels it adds are informative. With B1, this supports relaxing for both labels. The real-record finding of lower repeatability in added units stays as a documented limit. The project lead decides.
- **Fail on rule 1.** The larger baseline makes refuge labels less accurate in records both rules reach. This is evidence against relaxing for refuge labels.
- **Fail on rule 2.** In that arm, the refuge labels E1 adds are no better than chance. Relaxing would publish uninformative refuge labels in the records it adds. This is evidence against relaxing for refuge labels.
- **Inconclusive.** B2 does not settle it, and the default for refuge labels is no change. The lead decides on the existing evidence.

The library uses one eligibility rule for both labels. B2 does not test a split rule (relaxed for recharge only), and proposing one would need its own case.

## Reported, not used to decide

- **Recharge labels under the same two rules,** as a replication of B1 on fresh records with a varying dry level, read the same way. From B1's numbers, rule 2 may fail for recharge in arm I. If it does, the lead should weigh that against candidate 4 as a whole.
- **Agreement on added labels minus agreement on E0 labels,** for both labels: the real-record study's comparison, with the caveat above.
- **Coverage under E0, E1 and E2:** cycles with a label, records with a baseline, and median eligible cycles per record.
- **Agreement, chance agreement and kappa** for each group: E0, E1, added, and E1 on cycles E0 also labels. Also gross errors (`low` given for `high`, or the reverse).
- **Qualified labels:** how often `typical_uncertain` replaces `low` or `high`, and the agreement of what remains.
- **Label stability:** on cycles labelled under both rules, the share whose label changes.
- **By shape and by ratio band** (3–4, 4–6, 6–10, 10 and up, as in L1).
- **The trough level read,** as in B1: the reported `trough_extent_pct` minus the true dry level, in floors, for correctly and wrongly dated boundaries.

## Checks before the freeze (no accuracy computed on the main corpus)

1. **Generator identity.** With every w_j set to 0, B2's generators return, for 20 seeds per arm, exactly the records G2's generators return. This checks that the dry level is the only change.
2. **Construction.** G2's 24 noise-free configurations, with dry levels added:
   - Interior trough boundaries must fall at the truth in at least 95% of cycles, as in L1 and L2. This checks that the dry-level steps did not move the troughs.
   - In at least 95% of interior cycles, the reported `trough_extent_pct` must equal the noise-free level of its own month within 0.01 percentage points, and the reported `peak_extent_pct` the noise-free maximum within 0.01. That level is the built dry level when the boundary sits at m. (Amended before the freeze: the draft compared with the dry level itself, which a `sine` boundary at m + 1, accepted as truth since G2, cannot meet; see "Construction check outcome".)
   - Agreement of E1 and E2 labels with the truth is recorded, not required. The library ranks against eligible cycles only, so labels near the 20th and 80th percentiles can differ.
3. **Pilot.** The 280 pilot records run once. Only run times and counts are looked at: records with an E0 baseline, cycles labelled under both rules, and cycles E1 adds, for each label and arm.
   - If the pilot predicts fewer than 30 E0-labelled records or fewer than 300 cycles labelled under both rules in an arm of the main corpus, that arm is scaled up before the freeze. Arm I can grow to 8 injections per background.

**Identity check outcome (2026-11-04):** with every dry level at 0, all 64 records returned by B2's generators were identical to G2's: 20 seeds per arm plus the 24 noise-free configurations.

**Construction check outcome (2026-11-04):** passed after one amendment. Both shapes routed to per-year detection. Of 216 interior cycles per shape, the boundary fell at the truth in 215 (`sine`) and 212 (`pulse`). The trough extent equalled the noise-free level of its month in 216 and 216, and the peak extent the noise-free maximum in 216 and 212.

As first written, the check compared the trough extent with the built dry level. It failed for `sine`: 116 of 216 matched. The library placed 102 `sine` boundaries at m + 1, the end of the flat dry stretch, which G2, L1 and L2 accept as truth. There the level also holds 0.067 of that season's amplitude. In `pulse`, 212 of 216 matched. The criterion was amended to the noise-free level at the reported month, before any accuracy was computed on the main corpus.

The refuge truth is unchanged: a `sine` boundary at m + 1 reads a level slightly above the dry level, and that is part of what B2 measures. On the construction records, E1 refuge labels agreed with the truth in 434 of 480 cycles (kappa 0.84), and E0 labels in 396 of 460 (0.76). This was recorded, not required.

**Pilot outcome (2026-11-04):** no errors. Per-year detection: 115 of 200 (arm S) and 39 of 80 (arm I). Records with E0 refuge labels: 4 (S) and 7 (I). Refuge cycles labelled under both rules: 80 and 266. Refuge cycles E1 adds: 740 and 836.

Scaled to the main corpus, arm S predicted 28 records with E0 labels, below the floor of 30. So arm S was raised from 1,400 to 2,000 records (seeds 280000–281999), which aims at the 40 records this plan targets. Arm I predicted 100 records and 3,817 cycles labelled under both, and is unchanged.

## Limits stated in advance

- **The truth is the generator's.**
  - The dry level steps once a season, at the peak.
  - Its spread is uniform and matched to the peak spread.
  - It never falls to zero. Ephemeral refuges that dry out completely in some years, and the ties that would bring, are not modelled.
  - Real dry levels may drift or trend.
- **Arm I's truth leaves out the real background's own wet and dry years.** Labels that respond to them count as errors, so arm I understates accuracy, as B1 noted for recharge.
- **Rule 1 speaks only for records both rules reach,** which are the clearest seasons. Rule 2 speaks for the rest, with a minimal bar: better than chance, not "good".
- **One dry-level spread is tested,** not fitted.
- **The rules were chosen after B1's recharge numbers and the real-record results were seen.** The section above records how they shaped the design.
- **Not accuracy for real places,** and not referenced to gauges.

## Choices confirmed by the project lead (2026-11-04)

The lead approved the draft with each choice as proposed:

1. **The decision rules: confirmed.** Rule 1 (the rule's effect on cycles both rules label) plus rule 2 (added labels beat chance) replace the added-minus-E0 comparison of the real-record plan, for the reason given above. Added-minus-E0 is reported, not used to decide.
2. **The floor in rule 2: kappa above 0, confirmed.** A stricter floor, such as 0.20, the lower bound of "fair" agreement in Landis and Koch (1977), would on B1's numbers likely fail even today's E0 recharge labels in arm I.
3. **Recharge: reported, not deciding, confirmed.** It is scored under the same rules.
4. **The dry-level spread: Uniform(0, 0.9) amplitudes, confirmed.** It is matched to the peak spread. Smaller spreads would make refuge labels harder to get right.
