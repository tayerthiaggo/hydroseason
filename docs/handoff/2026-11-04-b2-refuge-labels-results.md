# B2: refuge (trough) condition labels against known truth, results

Run 2026-11-04 under the frozen plan ([plan](2026-11-04-b2-refuge-labels-plan.md), [receipt](2026-11-04-b2-refuge-labels-receipt.json)). The scorer output is [2026-11-04-b2-refuge-labels-results.json](2026-11-04-b2-refuge-labels-results.json). It cites receipt SHA-256 `8b5f8793f6ca44c279bc72b317151826f2153a43524a4449c261185b1815cdc6`.

## Summary

**Refuge labels pass. Both rules hold in both arms.** Under the reading fixed in advance, B2 supports relaxing the baseline's timing requirement from `point` to any dated status (rule E1, candidate 4 of `hydroseason-v0.3.0`). The project lead decides.

- **Rule 1 holds in both arms.** On the cycles both rules label, E1's refuge labels agree with the truth slightly more often than E0's: +0.029 [+0.008, +0.050] in arm S (940 cycles, 47 records) and +0.067 [+0.046, +0.088] in arm I (4,023 cycles, 106 records). The floor was −0.05. A baseline with more cycles ranks the same troughs a little better, as B1 found for recharge.
- **Rule 2 holds in both arms.** The refuge labels E1 adds carry information: kappa 0.347 [0.326, 0.368] in arm S (7,895 cycles) and 0.382 [0.353, 0.413] in arm I (10,176 cycles). The floor was above 0. Both sit in the "fair" band of Landis and Koch (1977), not "good".
- **Coverage grows about tenfold in arm S.** Records with refuge labels: 47 → 443 of 1,254 (arm S) and 106 → 375 of 569 (arm I).
- **Recharge (reported, not deciding) also passes both rules.** Arm I recharge labels are weak under both rules (kappa 0.196 under E0, 0.158 for the added labels), as B1 found.
- **The library was reproduced exactly.** The recomputed E0 labels and eligibility flags matched the library on every cycle (0 mismatches). No run failed, and every run carried the 0.2.0 method fingerprint `4bcfed63…`.

The documented limit stays: the labels E1 adds are less accurate than E0's own labels (added minus E0 −0.097 [−0.141, −0.051] in arm S, −0.014 [−0.055, +0.026] in arm I). As the plan says, this compares weaker records with stronger ones. It is not an effect of the rule, which rule 1 isolates.

## Decision rules (refuge labels)

Intervals are 95% bootstrap intervals over records (2,000 draws, seed 0). Only seasonal records routed to per-year detection are scored: 1,254 of 2,000 in arm S and 569 of 1,148 in arm I.

| Rule | Arm S | Arm I | Bound | Outcome |
| --- | --- | --- | --- | --- |
| 1. Agreement on cycles both label, E0 → E1 | 0.690 → 0.719 (940 cycles, 47 records) | 0.630 → 0.696 (4,023 cycles, 106 records) | | |
| 1. Difference [95% interval] | +0.029 [+0.008, +0.050] | +0.067 [+0.046, +0.088] | lower ≥ −0.05; ≥ 100 cycles from ≥ 20 records | Holds in both |
| 2. Kappa of the labels E1 adds [95% interval] | 0.347 [0.326, 0.368] (7,895 cycles, 396 records) | 0.382 [0.353, 0.413] (10,176 cycles, 269 records) | lower > 0; ≥ 100 cycles | Holds in both |

**Outcome for refuge labels: pass.**

## Reported, not used to decide

### Refuge labels by group

| Group | Arm S: agree / n (share), kappa | Arm I: agree / n (share), kappa |
| --- | --- | --- |
| E0 | 649 / 940 (0.690), 0.512 | 2,533 / 4,023 (0.630), 0.405 |
| E1 on the cycles E0 labels | 676 / 940 (0.719), 0.548 | 2,802 / 4,023 (0.696), 0.486 |
| Added by E1 | 4,682 / 7,895 (0.593), 0.347 | 6,266 / 10,176 (0.616), 0.382 |
| All E1 | 5,358 / 8,835 (0.606), 0.368 | 9,068 / 14,199 (0.639), 0.410 |
| Chance agreement, all E1 | 0.377 | 0.388 |
| Gross errors (`low` for `high` or the reverse), E0 / all E1 | 3 / 120 | 86 / 288 |
| Labels that change, on cycles both rules label | 97 of 940 (10.3%) | 604 of 4,023 (15.0%) |
| Added minus E0 [95% interval] | −0.097 [−0.141, −0.051] | −0.014 [−0.055, +0.026] |

### Coverage

| | Arm S, E0 | Arm S, E1 | Arm I, E0 | Arm I, E1 |
| --- | ---: | ---: | ---: | ---: |
| Records with refuge labels | 47 | 443 | 106 | 375 |
| Refuge cycles labelled | 940 | 8,835 | 4,023 | 14,199 |
| Median eligible cycles per record | 1 | 4 | 2 | 6 |

E2 gave the same labels as E1 in arm S, and almost the same in arm I (9,080 against 9,068 refuge agreements).

### By shape and by ratio band (refuge, kappa)

| | Arm S, E0 | Arm S, added | Arm I, E0 | Arm I, added |
| --- | ---: | ---: | ---: | ---: |
| `sine` | 0.491 (240) | 0.341 (4,329) | 0.297 (1,292) | 0.360 (5,537) |
| `pulse` | 0.520 (700) | 0.354 (3,566) | 0.457 (2,731) | 0.408 (4,639) |
| Ratio 3–4 | 0.120 (18) | 0.221 (1,404) | 0.219 (60) | 0.239 (479) |
| Ratio 4–6 | 0.324 (96) | 0.320 (2,948) | 0.269 (209) | 0.312 (1,217) |
| Ratio 6–10 | 0.540 (252) | 0.415 (1,799) | 0.361 (779) | 0.338 (2,256) |
| Ratio 10 and up | 0.545 (526) | 0.576 (750) | 0.444 (2,642) | 0.433 (5,065) |

Within a ratio band, the added labels are about as informative as E0's, except arm S at ratio 6–10 (0.415 against 0.540). In arm S the gap in the summary comes mostly from where the added labels sit: 4,352 of 7,895 (55%) are in cycles with a ratio below 6, against 114 of 940 (12%) of E0's. In arm I most added labels sit at ratio 10 and up, and the gap is small.

### Qualified labels (refuge)

`typical_uncertain` replaces `low` or `high` in 75 of 552 E0 labels and 2,074 of 4,920 E1 labels (arm S), and in 178 of 2,193 and 973 of 7,367 (arm I). The rest agree with the truth in 0.721 (E0) and 0.683 (E1) of cycles in arm S, and 0.645 and 0.657 in arm I. With fewer eligible cycles per record, the qualified label withholds more of the added labels, as it should.

### Recharge labels under the same rules

| Rule | Arm S | Arm I |
| --- | --- | --- |
| 1. Difference [95% interval] | +0.026 [−0.005, +0.058] (898 cycles, 47 records) | +0.040 [+0.024, +0.057] (3,890 cycles, 106 records) |
| 2. Kappa of the labels E1 adds | 0.275 [0.254, 0.296] (7,569 cycles) | 0.158 [0.134, 0.182] (9,816 cycles) |
| E0 kappa | 0.464 | 0.196 |
| Added minus E0 | −0.126 [−0.171, −0.076] | −0.014 [−0.052, +0.022] |

Both rules hold for recharge too. B1's concern, that rule 2 might fail for recharge in arm I, did not happen, but arm I's recharge labels are weak under both rules: E0 kappa 0.196 and added kappa 0.158. Arm I's truth leaves out the real background's own wet and dry years, so it understates accuracy (a limit stated in advance).

### The trough level read (arm S)

The reported `trough_extent_pct` minus the true dry level, in floors: median −0.56 (absolute 0.61) for correctly dated boundaries (17,445) and −0.66 (absolute 0.69) for missed ones (6,604). A quarter of correct boundaries and 30% of missed ones read more than a floor away. A missed boundary reads the dry level almost as well as a correct one. This fits a baseline that ranks levels, not dates.

### Not scored

141 refuge rows and 156 recharge rows had their true trough or cycle outside the reference set and were not scored, as the plan specifies.

## Deviations

- **Run time.** The plan estimated about 35 minutes on 12 workers from the pilot's per-record times. The main run took 3 h 6 min (11,151 s). Other jobs shared the machine; the cause was not investigated further. Nothing else changed.
- No other deviations. The plan, script and receipt are unchanged since the freeze; their SHA-256 values are in the receipt and checked by `tests/test_b2_results.py`.

## What this means for 0.3.0

Under the plan's reading, the pass supports candidate 4 (change C of the [proposal](2026-11-04-v0.3.0-proposal.md)) for both labels: let `point`, `interval` and `broad` cycles anchor the condition baseline. The limits that stay documented:
- the labels added by relaxing are fair, not good (kappa about 0.35 for refuge, 0.16–0.28 for recharge);
- on real records, added units repeat less well between pixel halves (kappa 0.41 against 0.51);
- the truth is the generator's, with a dry level that steps once a season and never reaches zero;
- not accuracy for real places, and not referenced to gauges.
