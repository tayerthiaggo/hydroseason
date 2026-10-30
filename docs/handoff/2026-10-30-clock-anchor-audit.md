# Clock-anchor analysis: independent scientific and workflow audit

Date: 2026-10-30, Australia/Perth. Status: research assessment; no detector, defaults, output contract or external project changed.

Source: `D:/RLH/5.6/repos/hydropools/docs/handoff/2026-10-30-clock-anchor-analysis.md`, SHA-256 `5cbe392fb38af85f31b82a5d47fea0d618bbcde24f2c51bfa3d6847624dea76a`.

Read alongside [current falsification results](../provisional-trough-falsification-2026-10-30.md), [test plan](../superpowers/plans/2026-10-30-trough-falsification-tests.md), and [previous verdict](../provisional-trough-verdict-2026-10-30.md). [Evidence receipt](2026-10-30-clock-anchor-audit-evidence.json) pins inspected files and independently recalculated counts. [Reviewer brief](2026-10-30-clock-anchor-independent-review.md) asks another agent to challenge both source and this audit.

## 1. Verdict

**Good diagnosis of downstream stakes; insufficient evidence for replacing trough with rise. First correct input semantics and audit cohorts. Then compare anchors against explicit scientific targets.**

Source gets several important things right: percentage-only inputs lose pixel support; an unresolved local clock must not become a confident date through fallback; end-dry affects identity and exposure as well as persistence; operational year start is not established wet onset; local minima and catchment hydrology need different interpretation.

But central argument jumps from **synchronous peaks** to **synchronous rises**, from **sensitivity of outcomes** to **accuracy of timing**, and from **observed minimum** to **continuous persistence**. None follows. Two numerical problems and one larger input-contract omission materially weaken that argument:

1. Hydropools supplies `100 * wet / all_pixels`; HydroSeason expects `100 * wet / valid_pixels`. Counts repair denominator as well as pixel detectability.
2. Published `ratio > 10` group silently excludes 92 enormous ratios. Correct full group: 14.4% Jan–Aug ends and 11.2% at least three months from median, versus 6.5% and 3.6% reported.
3. The 26,633-pool-year minimum comparison uses last **observed** month as endpoint for 523 groups whose actual endpoint is missing. Correct observed-endpoint cohort: 26,110; minimum-rule flips remain about 4%, but endpoint estimates change.

Rise is worth testing for **last state before seasonal replenishment**. Trough remains relevant for **minimum water availability**. **Survival through recession** requires a trajectory or drying interval. Choose target before choosing clock.

## 2. Evidence boundary and concurrent work

Inspected HydroSeason implementation and Hydropools `seasons.py`, `pipeline.py`, `persistence.py`, `drying.py`, `extents.py`, `exposure.py`; read original scratch scripts and existing CSVs. Recalculated ratio-bin and endpoint findings directly. Did not rerun raster inference, all original tables, gauge timing, or the full synthetic sweep.

HydroSeason HEAD advanced during audit from `7bd3c20` to `6b3a58e74cb8742674bca40fd35282abb8cee1b4` as existing falsification work completed. Additional edits appeared in its report and runners; this audit leaves those files alone. Receipt hashes specify inspected versions. Hydropools checkout: `ccc4ab070b1eb1e5dd2b97d16fc3ea17fe2c78ba`; output manifest records earlier producer commit `3f54c6cd4562461e98c939fa068eaac778176b63`, version 0.1.0. Current source and historical outputs must not be treated as identical provenance automatically. Sample tile05 HydroSeason manifest records version 0.2.0 and matching published method fingerprint.

Fresh targeted verification:

```text
.venv/Scripts/python.exe -m pytest tests/test_trough_recurrence_contract.py tests/test_catchment_analysis.py::test_catchment_threads_measurement_tolerance_to_the_dynamic_cycle_detector -q -p no:cacheprovider
7 passed in 12.19s
```

These verify inspected behaviour. They do not establish hydrological correctness. External numerical tables not explicitly recalculated below remain source-reported.

## 3. Implementation findings

### 3.1 Missing counts are real; denominator mismatch is bigger than source admits

Hydropools `extent_series` calculates:

```python
n = states.shape[1]
wet = (states == WET).sum(1)
obs = wet + (states == DRY).sum(1)
extent_pct = 100.0 * wet / n
invalid_pct = 100.0 * (n - obs) / n
```

HydroSeason [`prepare_monthly_extent`](../../hydroseason/_state_input.py) recalculates `extent_pct = 100 * n_water / n_valid` when counts exist. [Documented denominator](../report-columns.md) agrees. Same fixed spatial footprint, different treatment of invalid observations.

Let `v = obs/n`, `p = wet/obs`. Existing export is `100vp`; valid-pixel extent is `100p`. If true observed water fraction stays 20%, halving observation coverage halves exported extent without hydrological change. With `n=100`, `obs=50`, `wet=10`, current export is 10%; counts produce 20%. A direct probe confirmed this normalization.

Across 41 channel input CSVs: 19,434 monthly rows; 18,610 finite usable-by-availability rows; 11,388 of these have positive invalid percentage. Median invalid share among finite rows is only 0.093%, but 95th percentile is 34.53%, 99th 87.92%. Therefore mismatch is not uniformly large, yet potentially important in cloudy transition months. Magnitude of resulting timing error remains unmeasured. Default `quality_policy="flag"` can retain partially invalid candidates; weighting does not undo denominator multiplication.

Minimum input repair: export raw integer `n_water=wet`, `n_valid=obs`, `n_invalid=n-obs`, `n_aoi=n`, with denominator-consistent percentages and footprint/source identity. Do not fabricate counts by multiplying rounded percentages. Existing states may include filled rather than directly observed values: record that provenance; filled support does not become independent measurement evidence.

Important limit: valid-denominator fraction is not automatically true footprint wetness when missing pixels differ systematically from observed pixels. With trustworthy observed classes and arbitrary missing pixels, footprint wetness lies in `[100*wet/n, 100*(wet+n-obs)/n]`. Existing export is the lower bound, which can be useful if explicitly labelled; passing it as ordinary `extent_pct` loses that interpretation. Counts restore compatible measurement semantics, not truth under clouds. An increase whose later lower bound exceeds earlier upper bound is stronger evidence than a quotient increase alone. Classification error and imputed states require further uncertainty beyond these missingness bounds.

For attribution, compare three versions: existing export; valid-denominator percentages without counts; same corrected percentages with counts. First comparison isolates denominator semantics; second isolates count-dependent guards. A separate tolerance sensitivity is useful, but setting everything to 1 pp would be a method choice, not an explanation of current behaviour.

### 3.2 Epsilon floor has an ordinary, traceable explanation

[`run_hydroseason`](../../hydroseason/workflow.py) forwards analysis options into [`analyze_catchment`](../../hydroseason/_catchment.py). Its `measurement_tolerance_pct` default is **0.0**, which it forwards into regime assessment and explicit `DynamicHydroYearConfig`. That overrides dataclass default **1.0**. Hydropools supplies no analysis override. Thus no mystery requires a hidden setter.

[`annual_detectability`](../../hydroseason/_timing_identifiability.py) uses maximum of tolerance, noise, pixel resolution at extrema, epsilon. Missing counts remove resolution and peak wet-pixel checks. Zero tolerance plus zero robust noise then gives epsilon. Direct probe: amplitude 0.1 pp, no counts, zero tolerance/noise gives floor `2.220446049250313e-16`, ratio about `4.5e14`, `detectable=True`.

This is permitted percentage-only behaviour, not evidence of strong physical support. Counts restore quantization and peak-support information; they do not calibrate classification error, spatial dependence, or timing uncertainty. Annual peak-to-trough amplitude also does not establish detectability of a small local onset step. Conversely, exactly flat amplitude remains undetectable even with epsilon: source's 80 zero-ratio records are already rejected on amplitude.

Source's “D8 is mostly this input gap” remains an untested attribution. Need paired corrected-input outputs before assigning fractions of failures to counts, denominator, small samples, broad troughs, or genuine hydrology. Early date or distance from catchment median is a screening flag, not reference error.

### 3.3 `start_date` is month after previous boundary, not previous trough itself

[`_assemble_dynamic_cycle`](../../hydroseason/_dynamic_year.py) sets `hy_start = previous["trough_month"] + DateOffset(months=1)`; [`build_user_hydro_years_export`](../../hydroseason/_report_export.py) maps that to `start_date`.

Source is right that `start_date` does not establish wet onset. Exact “previous trough” claim is one month off. Exposure currently spans month-after-previous-boundary to reading, approximately a trough-bounded cycle, not a demonstrated recharge-to-reading period. Inclusive/exclusive days also matter: Hydropools exposure subtracts cumulative values at onset and target.

Keep `start_date` semantics stable. Any onset product needs distinct fields and explicit association with previous/current rise. For endpoint just before rise `R_(y+1)`, exposure would normally start at `R_y`, not `R_(y+1)`. Re-key cycle IDs explicitly; calendar-year equality is unsafe when anchors move across December.

### 3.4 Ratio table drops precisely its most pathological cases

Original `clock_quality.py` uses:

```python
pd.cut(ratio.fillna(-1), [-2, 0, 1, 2, 5, 10, 1e9], ...)
```

Ratios above `1e9` become missing categories; grouped table omits them. Independently recalculated from its 1,545-row CSV:

| Actual group | n | Jan–Aug end | At least 3 months off median |
| --- | ---: | ---: | ---: |
| `10 < ratio <= 1e9`, published `>10` row | 913 | 59 / 913 = 6.46% | 33 / 913 = 3.61% |
| `ratio > 1e9`, excluded | 92 | 86 / 92 = 93.48% | 80 / 92 = 86.96% |
| All `ratio > 10` | 1,005 | 145 / 1,005 = 14.43% | 113 / 1,005 = 11.24% |

Excluded records: tile05 28, tile13 17, tile18 15, tile46 32. Also, “no amplitude (ratio NaN)” actually contains **80 zero ratios and zero NaN ratios** in this CSV. Zero can indicate amplitude at/below floor, not missing input. These corrections strengthen input-support concern, weaken the claim that ratio stratification isolates “real early troughs.”

### 3.5 Minimum comparison confuses last observed month with endpoint

Hydropools removes `state == "unobserved"` before writing `pool_months.csv`. Original `ymin.py` then takes each group's `state.iloc[-1]`; that need not have `pos_to_end == 0`.

Recalculation:

- 132,815 retained month rows; 26,633 pool-year groups.
- 523 groups lack actual observed endpoint; their latest observed positions are 1, 2 or 4 months before it.
- Source calculation reproduces exactly: last-observed wet share 0.421770; no-observed-dry share 0.382157; 1,055 wet-to-dry changes.
- Restrict to actual observed endpoint (`pos_to_end == 0`): **26,110** pool-years; **10,914** wet at endpoint (0.418001); **9,876** with no observed dry month (0.378246); **1,038 / 26,110 = 3.98%** changes.
- `pool_years.csv` contains 26,644 rows, with **534 unobserved actual endpoints**. The 523 above are groups with some retained observation; 11 further groups are absent from `pool_months.csv`. Known endpoint states agree exactly between both tables.

So ~4% descriptive result survives corrected cohort. Its interpretation does not: no observed dry month is weaker than continuous survival; within-window minimum is not a one-month perturbation of trough timing. Source's own minus-one-month comparison changes 19.4%, already contradicting “exact trough month barely matters.”

## 4. Scientific reasoning: what follows, what does not

### Peak synchrony does not establish rise synchrony

Identical March peaks can follow November onset in one reach and February onset in another. Different runoff thresholds, storage, connectivity and tributary inputs can produce that pattern. Source measures peak synchrony, **never rise synchrony**. Replace “rise agrees in 93%” with “93% peak agreement motivates measuring rise agreement.”

Point-only selection also matters: peak and trough statistics use different eligible subsets and different numbers of tiles. Report coverage alongside accuracy, compare matched tile-years, and do not infer whole-catchment accuracy from identifiable survivors. Pixel-weighted median can be influenced heavily by the very tile being evaluated; use leave-target-out donor benchmarks when assessing borrowing.

Tile flaw versus anchor flaw remains open. A processing box can mix tributaries, perennial pools and floodplain storage. A rise anchor might reduce or amplify that mixture. Test a bounded set of matched aggregations after input repair, including seam/gauge cases; do not begin a wholesale network repartition on this evidence.

### Sensitivity of `y` is not validation of onset

Source's saved `clock_check.json` compares different paired cohorts: minus one month **25,209**, plus one **23,056**, catchment median **25,067**. These are not all 26,644 pool-years. Plus-one-month result is 7,523 changes, including 6,764 dry-to-wet: strong evidence of nearby rewetting in observed cases. It does not locate first flow, sustained onset, or explain the omitted cases. It also uses reconstructed unguarded end dates, matching actual run ends in 99.29% of compared region-years, not exactly all.

An endpoint chosen near a low state naturally has a wetter following month. Shared pixels help choose aggregate endpoint and score pool outcome, so this is not independent evidence. Evaluate timing with a separate reference; evaluate downstream consequences separately.

### Observation-density bias was not excluded

For an actually wet pool with independent false-dry probability `q` per observed month, probability of at least one false dry is `1 - (1-q)^m`. More observations increase minimum-rule failures even without hydrological change. Independence is only a counterexample, not assumed true of WOfS.

Similar era-level gaps between endpoint and minimum rules cannot distinguish that mechanism from changing hydrology, sensors, clouds, interval length, or pool selection. The published CSV already excludes unobserved months. Use fixed-length/calendar-matched windows and deliberate thinning of higher-density observations to earlier availability patterns; report missing endpoint and internal gap rates. “No observed dry” must retain an uncertainty state when gaps prevent a survival claim.

### A rise changes target; a refuge decline is not guaranteed

Three defensible targets need different summaries:

- **Minimum availability:** lowest supported water level/extent, potentially an interval.
- **State immediately before replenishment:** occupancy at `R_(y+1)-1 month`, with interval/gap uncertainty.
- **Continuous survival from recession:** no supported drying before replenishment, with interval censoring and separate rewetting events.

“Wet at endpoint” can include a pool that dried and rewetted. A refuge interpretation must decide whether such interruption disqualifies it. Aggregate minimum and pool survival are different: an aggregate clock is a reasonable shared exposure convention, but it does not remove selection dependence when same pools contribute to clock and identity.

Taking a within-window minimum weakly lowers `y` on a fixed, fully observed cohort by construction. Moving to a pre-rise date does **not** have that guarantee. Rewetting, later sampling, censoring and rebuilt cores can move wet share or refuge count either way. Predicted “refuges fall” is a hypothesis, not a known direction.

### Gauge flow and mapped water are distinct observables

Gauge first flow is valuable independent evidence about reconnection at that gauge. It is not universal truth for tile-wide extent rise or every pool. A primary study explicitly separates flowing, ponding and dry conditions and discusses limitations of point gauges for spatial water presence: [Cavallo et al., 2025, Journal of Hydrology](https://iris.polito.it/retrieve/82a0c475-8768-47c5-98b5-daffdaed7f23/Cavallo_et_al_2025_compressed.pdf), pp. 1–2 of article. This supports target distinction, not a Fitzroy timing-lag estimate.

Audit inference: validate gauge-connected channel rise against first flow; validate extent change with independent imagery/field observations; validate refuge survival with drying/rewetting evidence. Do not force one referee to answer all three.

## 5. Rise definition still contains scientific choices

Source proposes first post-trough month exceeding trough level by floor, staying above until peak. Worth evaluating, but neither “no new constant” nor self-contained:

1. **Reference low state.** Which trough when trough is unresolved or broad? Estimated low level may be usable without point date, but target bracket and uncertainty must be explicit. Requiring a resolved trough first would inherit failures it aims to avoid.
2. **Persistence.** “Until peak” is itself a persistence rule and uses future observations. A brief first-flow pulse followed by drying is not sustained seasonal onset. Specify which event serves science.
3. **Missing months.** Remaining observed months above threshold do not establish continuous persistence through cloudy gaps. Missing is not a below-threshold failure either. Return interval/unresolved evidence.
4. **Threshold scale.** Floor for annual extrema is not calibrated local change uncertainty. Trough and new month have uncertainty, changing valid coverage and potentially correlated errors. Existing amplitude ratio and five-peak-pixel defaults were calibrated for another task; borrowing numbers does not validate onset.
5. **Peak dependence.** Multiple peaks, no clear next peak, aseasonal years and all-year flow need explicit outcomes. A new field only inside current seasonal route could leave exactly the rejected records unsupported.
6. **Monthly support.** Month stamps represent composites, not instantaneous events. Within-month rise can contaminate a monthly state. Inspect composite definition and observation dates before treating “month before” as guaranteed pre-event.
7. **Operational latency.** Confirmation through peak requires waiting for that peak; final record year can remain provisional. Retrospective confirmation is legitimate, but cannot be reported as a forecast available before onset.

For an onset interval `[L,U]`, admissible pre-rise months span `[L-1,U-1]`. Subtracting one month from one selected date does not remove interval uncertainty. Define endpoint status, observation support and downstream eligibility rather than collapsing interval to its end.

## 6. What current trough tests establish

Tests running when request arrived have since produced a results document. These are **existing-run results inspected here**, not a newly rerun full suite:

- Pre-registered checks: drifting-trough rejection **4/100** (bound ≤10); stable-trough power **99/100** (bound ≥90); uniform-null trough **7/200**, peak **17/200** (both bounds ≤17).
- Follow-up uniform null: **51/1,000** trough and **62/1,000** peak rejections. No pre-registered pass threshold for this follow-up. Counts do not justify declaring universal calibration or a general defect.
- 30-year stable trough, no floods, no gaps: trough rejects **30/30**, peak **21/30**, seasonal **21/30**. Sharp random-peak variant: peak **1/30**, seasonal **1/30**. Broad tied evidence and a calendar hole remain important investigation targets. “No recurring point peak” is not identical to a uniform distribution of equivalent peak sets; inspect the null's estimand before calling every rejection false.
- 12-year stable trough, flood probability 0.3, no gaps: harmonic accepts **12/30**, wrong month **5/30**; trough rejects **29/30**. Existing trough recurrence can retain information that harmonic magnitude prediction loses.
- Short records with concentrated dry gaps lose power: stable/7 years/floods0.3/dry20 gives trough rejection **15/30**, versus **28/30** without gaps. Synthetic missingness is therefore material even before realistic cloud structure.

Counts variant rounds water pixels on a 1,000-pixel footprint; it is not a pure metadata switch. It has neither tiny zero-heavy channels nor partial cloud sampling of heterogeneous water. Therefore its modest differences do not refute count/denominator concerns in Hydropools.

These tests assess **recurrence across years**, not accuracy of a particular year's late-dry date, spatial transfer, or onset. The existing joint peak-and-trough rule defines seasonal regime; a trough-only or rise-only consumer product need not redefine that regime. Keep both workstreams: finish frozen-window recurrence evaluation; separately evaluate late-dry endpoint hypothesis. Rank recovery remains exploratory and changes units; do not use rank amplitude against physical percentage-point floors.

Frozen external 24-window evaluation is still a distinct requirement. Acceptance against rank trough alone would be agreement between estimators, not independent truth. Calibration membership of Fitzroy remains **unverified**: defaults header points to calibration maintained outside repository, while local receipts pin aggregate stages/hashes but do not identify partition members. Request partition manifest from calibration owner before claiming transfer validation.

## 7. Workflow changes if rise earns adoption

**No automatic implementation recommendation yet.** A supported rise product would require these changes:

- **HydroSeason:** separate low state, wetting event and administrative year boundary; additive, versioned outputs with provenance, interval/status, observation support, confirmation time and method identity. Preserve existing `start_date` meaning and current regime/baseline gates unless separately validated.
- **Hydropools:** one explicit consumer endpoint policy. Choosing local/donor/catchment event still needs source, donor IDs, spread, year alignment and failure status. Removing old fallback chain does not remove missing evidence; it replaces a hidden chain with a documented policy. A donor median is an imputation, not a detected local event.
- **Severity:** define `X = (C(endpoint)-C(previous_rise))/scale` and antecedent span separately if that is desired target. Record calendar support and offsets. Rise-to-rise is a complete-cycle quantity; reading-before-rise stops before next rise. E−P remains an exposure index, not a physical pool water balance without inflow, groundwater, storage and connectivity.
- **Drying and extents:** retain wet peak as normal start of recession walk. Source says start walks from month before rise; acceptable only as the backward walk's **endpoint/origin**. Current drying/export code already spans peak to end-dry. Replacing peak-side start with pre-rise month would discard recession history.
- **Identity and registry:** first score alternatives on fixed 709 cores to isolate timing; then rebuild cores/era-dry selection and compare births, losses, splits, merges and inherited IDs. Fixed-core performance is not whole-system performance. Clock-dependent identity learned from all years must be considered when claiming held-out predictions.
- **Statistics:** refit severity quantiles, coefficients, year-block uncertainty and refuge classifications. Propagate endpoint/donor alternatives through whole affected workflow, not only final logistic fit. Calendar years and connected gauges are dependent; do not bootstrap pool-years independently.
- **Floodplain/TSFill:** separate estimands. Floodplain last-water, local onset and channel reconnection may differ. Zero troughs can form identifiable dry intervals; zero alone does not prove trough useless. TSFill's climatological accuracy strata need not share an annual persistence clock. Share event semantics and provenance where appropriate, not necessarily identical dates.

Previous validation is still evidence about previous product. Once used to choose a new policy, same imagery is development evidence rather than fresh confirmation. Keep old results, label reuse, obtain held-out evaluation. No need to call every historical label scientifically worthless.

## 8. Smallest decisive research sequence

### A. Resolve input and audit integrity first

Freeze raw counts, masks, state provenance, code and output hashes. Correct denominators and retain counts; compare stages from section 3.1 on same tile-years. Report route changes, floor changes, resolved/unresolved coverage, endpoint shifts, cloud association and affected pool-years. Rebuild ratio bins with infinite upper endpoint; separate zero, missing, epsilon-floor and ordinary-floor cases. Retain unobserved months in audit tables.

**Decision:** if most anomalies disappear, rise becomes an optional target change rather than a necessary detector rescue. If anomalies remain, diagnose them against independent evidence. Do not tune a replacement from suspect CSVs first.

### B. Define target and freeze a bounded challenger

Choose minimum availability, pre-replenishment state, continuous survival, or multiple clearly named products. Write handling of pulses, missing intervals, no rise and nonseasonal years. Freeze one operational rise rule before final reference evaluation. Use adversarial examples: flat/zero, constant high water, sharp onset after long plateau, false early pulse, two wet seasons, cloud gap across onset, changing valid subset, asynchronous reaches with same peak.

**Decision:** if proposed rule cannot answer these without arbitrary silent choices, design is incomplete. This does not invalidate rise as a target.

### C. Independent timing comparison on corrected inputs

Gauge study should define timezone/day boundary, quality-code eligibility, usable record, zero-spell detection, multiple spells, sustained versus first flow, missing-data interruption, gauge-to-reach mapping, and allowable physical lag before scoring. Inspect local semicolon-delimited BOM format and timestamps carrying `+10:00`; never interpret missing discharge as zero.

Compare corrected trough endpoint plus one month, fixed climatological onset, and frozen rise challenger on paired cases. Report abstention/coverage, signed lag, interval width/coverage, false early detection and false late detection. **Late onset estimate is especially costly:** its preceding month may already contain rewetting. ±1-month symmetric accuracy alone hides this error.

The source's 70% within ±1 month can remain an explicitly borrowed benchmark, but cannot establish superiority without baseline improvement and uncertainty. Report per-gauge and per-year results plus pooled counts; use hydrological-year blocks across connected gauges and leave-gauge/reach-out evaluation where sample permits. Keep all-year-flow and no-observed-rise cases visible, not dropped successes.

On 2026-10-30, July–September and most of October 2026 have already elapsed. Jul–Dec 2026 is a clean holdout only if access logs substantiate non-use and rule is frozen before inspection. Source outputs ending June help but do not establish analyst blinding. Otherwise choose demonstrably unused periods/reaches or future observations, and distinguish retrospective analysis from prediction.

### D. Evaluate scientific consequences separately

On fixed cores and common observable pool-years: compare current endpoint, corrected-input trough endpoint, pre-rise endpoint and trajectory survival. Then report full available cohorts and missingness separately; common-cohort comparisons alone can conceal cloud-driven selection. Include actual endpoint state, drying intervals, `X` changes, refuge flips and within-era effects.

Only then rebuild identity/registry and rerun whole pipeline. Compare against independent state/drying labels for the chosen target. Do not select clock for producing driest outcomes, most refuges, highest coverage, or best fit on reused labels.

**Adoption requires** declared target, corrected input contract, supported timing improvement or stronger target validity, explicit uncertainty/abstention, bounded downstream damage and reproducible transfer evidence. No numerical adoption margin is chosen post-hoc in this audit.

## 9. Reproduction of new numerical findings

Run from HydroSeason root with `.venv/Scripts/python.exe`; external inputs stay read-only. This minimal endpoint check needs no raster stack:

```python
from pathlib import Path
import pandas as pd

p = Path('D:/RLH/5.6/repos/hydropools/outputs/rerun/fitzroy')
pm = pd.read_csv(p / 'pool_months.csv').sort_values(['core', 'hy', 't'])
g = pm.groupby(['core', 'hy'])
print(g.ngroups, g.tail(1).pos_to_end.ne(0).sum())  # 26633, 523
dry = g.state.apply(lambda s: s.eq('dry').any()).rename('any_dry')
a = pm[pm.pos_to_end.eq(0)].join(dry, on=['core', 'hy'])
print(len(a), a.state.eq('wet').sum(), (~a.any_dry).sum())
# 26110, 10914, 9876
print((a.state.eq('wet') & a.any_dry).sum())  # 1038
```

Ratio audit uses `clock_quality.csv` path pinned in evidence receipt. Count `ratio > 1e9` directly before grouping; rerun from primary hydro-year CSVs if scratch CSV is unavailable. Original scratch scripts are evidence of computations, not permanent scientific provenance. Archive inputs/scripts with hashes before relying on their tables externally.
