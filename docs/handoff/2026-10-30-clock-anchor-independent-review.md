# Independent review request: clock, trough, rise and pool science

Date: 2026-10-30. Prepared for another agent; not yet independently reviewed.

## Assignment

Audit both original clock-anchor proposal and [new audit](2026-10-30-clock-anchor-audit.md). Do not treat either as authority. Deliver independent judgement, factual corrections, and smallest experiment capable of changing decision. Do not implement detector changes, alter thresholds, rerun entire production pipeline, or amend ongoing tests to make them pass.

Original: `D:/RLH/5.6/repos/hydropools/docs/handoff/2026-10-30-clock-anchor-analysis.md`.

Working repository: `D:/RLH/5.6/repos/hydroseason`. Preserve unrelated concurrent edits. Read repository instructions. [Receipt](2026-10-30-clock-anchor-audit-evidence.json) pins source/input hashes and newly recalculated numbers. If checkout differs, state differences before judging implementation claims.

Suggested output: `docs/handoff/2026-10-30-clock-anchor-independent-verdict.md`. Return **agree / partly agree / disagree / not verifiable** for each material claim, with source location or reproducible evidence. Separate source inspection, rerun behaviour, historical artifact, scientific inference and proposed policy.

## Required reading

1. Original proposal, new audit, evidence receipt.
2. `docs/provisional-trough-{analysis,judgement,verdict}-2026-10-30.md`.
3. `docs/superpowers/plans/2026-10-30-trough-falsification-tests.md`, `docs/provisional-trough-falsification-2026-10-30.md`, and current `dev/reports/2026-10-30-*` artifacts. Tests completed while audit ran; prefer pinned artifacts over stale “still running” descriptions.
4. HydroSeason: `workflow.py`, `_catchment.py`, `_state_input.py`, `_timing_identifiability.py`, `_seasonality_test.py`, `_circular_timing.py`, `_dynamic_year.py`, `_report_export.py`, `_scientific_defaults.py`.
5. Hydropools: `src/hydropools/{seasons,pipeline,persistence,drying,extents,exposure}.py`; output manifest; channel monthly inputs; hydro-year tables; `pool_months.csv`; `pool_years.csv`. These external files are read-only for this task.

## First: try to falsify audit's new findings

- Does `extent_series` use all pixels while HydroSeason expects valid pixels? Does adding counts normalize values automatically? Quantify distinction between input semantic defect and measured hydrological error. Does historical producer source differ materially from current checkout?
- Does high-level default tolerance 0 override dataclass default 1? Confirm propagation into annual cycles, not only regime assessment. Distinguish this floor from harmonic fitted-amplitude floor.
- Does `pd.cut` upper edge `1e9` drop 92 records? Recalculate all `ratio >10` and check 145/1,005 early dates, 113/1,005 large deviations; distinguish zero from missing ratios.
- Does filtering unobserved months cause last-row endpoint error for 523 groups? Require `pos_to_end==0`. Confirm 26,110 actual observed endpoints, 10,914 wet, 9,876 without observed dry, 1,038 changes; reconcile 534 missing endpoints among 26,644 `pool_years` rows.
- Is `start_date` month after previous boundary? Verify export mapping and first/partial-cycle exceptions.

If audit got any of these wrong, correct them before broader scientific discussion.

## Then: challenge scientific conclusion

1. Can observed peak synchrony establish onset synchrony under any stated assumptions here? Construct minimal counterexample, or supply evidence those assumptions hold. Does point-only selection or target-included weighted median distort comparison?
2. Which actual target is justified: minimum water, state before replenishment, survival through recession, or another? Is shared aggregate clock appropriate for that target? Where does clock/identity/persistence selection create dependence?
3. Does 4% minimum-rule disagreement justify “trough month barely matters” given 19.4% minus-one-month disagreement? Can similar era summaries exclude observation-density bias?
4. Can sustained rise be defined without resolving trough date first? Specify persistence horizon, gaps, pulses, local change uncertainty, no-peak years, timestamp support and confirmation lag. Is frozen annual-extrema calibration transferable to onset?
5. Is “refuges fall” guaranteed? Distinguish minimum on fixed complete cohort from shifted endpoint and rebuilt identity. Derive counterexample if direction is not guaranteed.
6. Is first flow a fair referee for chosen target? Specify gauge-connected reach, uncertainty, spatial mismatch, quality codes and clustering. Does proposed 70% ±1-month benchmark hide dangerous late estimates? What baseline must challenger beat?
7. Does recommendation preserve existing seasonal conjunction and annual-condition safeguards while allowing separate consumer target? Is proposed product boundary unnecessarily broad or too restrictive?
8. Which decisions must transfer between channel, floodplain and TSFill, and which should remain target-specific?

## Integrate tests without overstating them

Existing checks report 4/100 drifting-trough rejections, 99/100 stable-trough power, 7/200 uniform-null trough, 17/200 peak; follow-up 51/1,000 trough and 62/1,000 peak. Full sweep has 21/30 peak rejections in stable broad-peak 30-year construction versus 1/30 sharp-peak variant.

Check underlying estimand before calling nonuniform equivalent peak sets false positives. Distinguish recurrence from annual endpoint accuracy. Counts variant rounds pixels, changing series; synthetic amplitude and complete-or-missing observations do not model tiny/cloudy channels. Frozen 24-window real-data check remains separate; rank agreement is not independent truth.

Identify any current test that genuinely adjudicates rise proposal. If none, say so. Do not discard trough recurrence results because a different target has been proposed.

## Required deliverable

- Ranked factual/scientific findings, severity and effect on decision.
- Judgement on original recommendation and audit recommendation separately.
- Precise target definition plus minimum output/uncertainty contract, without implementation.
- Smallest staged experiment: input repair attribution first; independent timing comparison second; fixed-core and rebuilt-system consequences separately. Specify what outcome supports adoption, rejection or continued uncertainty. Freeze numerical margins before new confirmatory reference inspection.
- Evidence/provenance gaps, including Fitzroy calibration partition membership and whether any 2026 imagery genuinely remains unexamined. Do not assert holdout cleanliness from calendar date or data cutoff alone.

Preserve old results as evidence for old product. Record reused validation as development evidence. No silent change to `start_date`, no automatic replacement of unknown local timing with confident neighbour date, and no threshold tuning to obtain desired refuge count.
