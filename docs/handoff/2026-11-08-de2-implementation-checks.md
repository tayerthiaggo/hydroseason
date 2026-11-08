# DE2 implementation checks: the year boundary at the end of the low

Date: 2026-11-08. Branch `research/refinement-end-of-low`. Candidate: R1 (search anchor at the end of the typical low) and the revised R2 (a boundary at the end of a dry low dated from the run end to the month before the next peak), fingerprint `59756dfe895ffbe5213b558229eb36f1a0452e86e7c1d95e334bab31fd6bfb65`. Evidence: [DE2 results](2026-11-08-de2-end-of-low-results.md), including the post-hoc check of the revised R2. Script [`scripts/de2_implementation_checks.py`](../../scripts/de2_implementation_checks.py); output [2026-11-08-de2-implementation-checks.json](2026-11-08-de2-implementation-checks.json).

"Before" is the stored `hydroseason-v0.3.0` runs: the case studies and tiles from `c85d913` and the real-record units from the 0.3.0 real-record check (same boundaries; `c85d913` only added reported columns).

## Outcome

| Check | Result |
| --- | --- |
| Five case studies, 4 resolutions | 19 of 20 series unchanged in every boundary, peak, label and baseline. Fitzroy at 300 m: 4 of 21 boundaries move later (3 months, 4 months, 6 months), 1 peak changes, baseline-anchoring cycles 8 → 7. Wet-event and low-spell tables identical |
| Fitzroy tiles (40, production inputs) | Tile-years ending three or more months before the dry season 251 → 104; any months 727 → 602; no tile loses per-year detection; years with unresolved timing 408 → 533 |
| Real-record units (4,468) | No errors, one fingerprint. 38 change route (30 gain per-year detection). Boundaries below |
| G1 pixel halves agreeing on the boundary within a month | 0.734 → 0.767 (33,459 pairs) |
| Reviewed Gilbert and Fitzroy trough tests, full suite | Pass (see the commit) |

## Boundaries on real records

Each new boundary is matched to the nearest old boundary within six months. (Matching by row would compare different seasons when R1 moves the anchor across January, because the year labels shift by one.)

| Source | Boundaries | Unchanged | Later | Later by 3+ months | Earlier | Units with a condition baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| G1 core windows | 16,941 | 14,136 (83.4%) | 2,607 (15.4%) | 977 (5.8%) | 73 (0.4%) | 274 → 262 |
| G1 quadrants | 58,902 | 40,869 (69.4%) | 16,386 (27.8%) | 7,208 (12.2%) | 1,108 (1.9%) | 690 → 642 |
| Whole catchments | 63 | 63 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 1 → 1 |
| HydroBASINS 6 | 483 | 479 (99.2%) | 4 (0.8%) | 3 (0.6%) | 0 (0.0%) | 14 → 14 |
| HydroBASINS 7 | 2,100 | 1,975 (94.0%) | 121 (5.8%) | 44 (2.1%) | 1 (0.0%) | 51 → 51 |
| HydroBASINS 8 | 6,090 | 4,933 (81.0%) | 1,077 (17.7%) | 472 (7.8%) | 57 (0.9%) | 92 → 93 |
| Tiles 6 | 924 | 857 (92.7%) | 58 (6.3%) | 29 (3.1%) | 4 (0.4%) | 16 → 18 |
| Tiles 7 | 2,541 | 2,341 (92.1%) | 174 (6.8%) | 84 (3.3%) | 12 (0.5%) | 53 → 48 |
| Tiles 8 | 8,904 | 7,151 (80.3%) | 1,611 (18.1%) | 740 (8.3%) | 84 (0.9%) | 127 → 115 |

- **Where boundaries move.** Whole catchments do not move; subbasins and tiles at levels 6 and 7 barely move; the smallest units and the G1 windows move most, as expected where flat, dry lows are common. Moves are almost all later.
- **Reproducibility improves.** The two pixel halves of a G1 window agree on the boundary within a month more often after the change.
- **Baselines shrink a little.** About 5% fewer units have a condition baseline (G1 quadrants 690 → 642), because cycles whose window changes can lose their dated label or confirmed boundary.
- **Peaks.** Peaks change where a cycle's window changes; the counts are in the JSON (`peaks_changed`).

## Deviations

- R2 is the revised version the lead chose after DE2 (post-hoc check, not pre-registered); R1 is as frozen.
- The first comparison matched real-record years by row and counted spurious earlier moves where the anchor crossed January; the script now matches by date. The library runs were not repeated.

## For the lead

With these checks the change is ready to join `hydroseason-v0.3.0`: merge `research/refinement-end-of-low` into `method-v0.3.0`. The docs, CHANGELOG, manifest, validation receipt and fingerprint pins are already updated on the branch.
