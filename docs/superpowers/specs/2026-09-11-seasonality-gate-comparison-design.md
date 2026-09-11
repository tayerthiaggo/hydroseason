# Seasonality gate comparison: research specification

Date: 11 September 2026. Status: proposed experiment; implementation and results pending. Repository baseline: `ab98bee` (HydroSeason 0.2.0).

## 1. Purpose and decision

Compare HydroSeason's current amplitude/SNR/circular-statistics gate with trend-aware harmonic modelling and robust STL seasonal strength. Include a detrended-SNR ablation to identify whether trend contamination explains disagreements. Produce a reproducible classification table for the reviewed catchments, existing smoke records and constructed records with explicit generative truth.

The experiment asks whether the current first filter rejects observable seasonal structure, admits non-seasonal structure, or expresses uncertainty appropriately. It does not assume that an alternative is better, that agreement with current labels establishes correctness, or that a seasonal record necessarily supports annual boundaries.

Three possible approaches were considered:

| Approach | What it establishes | Limitation |
|---|---|---|
| Catchment comparison only | Where methods disagree on familiar records | No independent truth; vulnerable to choosing the most appealing labels |
| **Catchments plus constructed controls and separate synthetic calibration/test records** | Disagreement, known-truth error, uncertainty and failure modes | Conclusions depend on the simulated processes; recommended here |
| Immediate replacement and end-to-end retuning | Behaviour of a new complete pipeline | Confounds gate changes with boundary changes and pre-empts validation |

This is a research benchmark outside the production decision path. Keep `direct_profile_combined` opt-in, keep its parameters frozen, and leave CAMELS-AUS data, partitions and results untouched. This experiment cannot satisfy or replace its promotion holdout. The manuscript's 2,000-word Methods limit does not apply to this protocol; eventual manuscript reporting should summarise it and put details in supplementary material.

## 2. What the labels mean

Separate three questions in every output:

1. **Seasonal structure:** does the observed process have a reproducible calendar-related component, potentially alongside trend? A repeated twice-yearly pattern is seasonal, although its fundamental period is six months.
2. **Annual-cycle suitability:** is there evidence for one interpretable wet/low cycle per year? Multiple peaks, phase drift and unresolved timing can defeat this even when seasonal structure exists.
3. **Boundary support:** can particular cycle endpoints be identified from observations? This benchmark does not estimate or validate endpoints.

Preserve each method's three class names, `seasonal`, `marginal`, and `aseasonal`, but publish their decision definitions. `marginal` is an evidence category, not a third physical data-generating mechanism. Add a separate status: `ok`, `insufficient_record`, `not_evaluable`, or `error`. Missingness, failed fits and unavailable scores must never be converted to `aseasonal` or hidden inside `marginal`.

Synthetic metadata separately records `calendar_seasonality`, `annual_fundamental`, and `single_cycle_suitable`, each as `yes`, `no`, or `ambiguous`. A weak but nonzero annual component remains a positive physical truth; weak-signal detection curves are reported separately from strong-signal accuracy. Existing real-catchment labels are comparison outputs, not ground truth.

The current aseasonal label also covers unresolved annual timing. Preserve that meaning in the results: an operational negative is not necessarily a claim of statistical certainty. Error tables therefore use the terms **false seasonal classification** and **false aseasonal classification**, with a separate measure of seasonal records rejected by the admission gate. Methods' similarly named classes are not assumed to carry equal confidence.

## 3. Frozen input panels

### 3.1 Reviewed real records

| Record | Source relative to repository root | Primary period |
|---|---|---|
| Daly | `case_studies/data/extent/daly_river_nt_30m.csv` | Jan 2005–Dec 2025 |
| Fitzroy | `case_studies/data/extent/fitzroy_river_wa_30m.csv` | Jan 2005–Dec 2025 |
| Gilbert | `case_studies/data/extent/gilbert_river_qld_30m.csv` | Jan 2005–Dec 2025 |
| Lachlan | `case_studies/data/extent/lachlan_river_nsw_30m.csv` | Jan 2005–Dec 2025 |
| Moonie | `case_studies/data/extent/moonie_river_qld_nsw_30m.csv` | Jan 2005–Dec 2025 |
| Kakadu | `case_studies/results/stress-test-full/reports/kakadu-national-park/kakadu-national-park_monthly.csv` | Jan 2005–Dec 2025 |
| Roper | `output/water_extent_csv/roper_river_nt_30m_water_extent.csv` | Jan 2015–Dec 2025 |

Roper is an additional previously reviewed development record. The five main records each have 252 months and no missing extent; Kakadu has 252 months with one missing extent; Roper has 132 months with no missing extent. Validate these assertions during ingestion rather than silently accepting a changed file. Verify the five files against `case_studies/data/manifest.json`; record SHA-256 for every source and the normalised inputs.

For primary historical-input parity, follow the input selection in `case_studies/results/low-state-direct-profile-v2/build_catchment_reports.py`: preserve the five catchments' count columns; select only date, extent and invalid fraction for Kakadu; select extent and invalid fraction with the source date index for Roper. Kakadu's report-derived regime, route, phase and other algorithm outputs are forbidden inputs.

The five count-bearing files lack `n_invalid`, which `prepare_monthly_extent` derives as `n_aoi - n_valid`; it then derives extent and invalid fraction from counts. Reuse that behaviour. Validate count consistency and report discrepancies between stored and derived percentages without changing the scientific defaults. A secondary metadata sensitivity uses extent/invalid-only for all seven and, separately, Roper's complete native counts. These views must have distinct identifiers.

Publish the full-record table first. A secondary Jan 2015–Dec 2025 table gives all seven the same period. Existing 60 m, 90 m and 300 m versions of the five main catchments are resolution sensitivities, not additional independent catchments.

### 3.2 Existing smoke records

Reuse only the deterministic `make_smoke_frames()` generator in `scripts/build_final_review.py`: `clean-seasonal`, `all-zero`, `constant-water`, `two-pulses`, `long-plateau`, `gap-at-low`, `gap-at-recovery`, `low-quality`, and `late-trough-short-following`.

Archive the resulting 180-month frames and hashes. The `two-pulses` fixture changes part of one year; it is not a record with two peaks in every year. The perturbed fixtures generally retain an underlying annual signal. Annotate their construction before scoring; do not treat their names or old report labels as scientific truth. The two flat records are deterministic negative controls. All nine belong in a separate table and must not inflate Monte Carlo sample sizes.

### 3.3 Shared preparation

Use monthly timestamps, extent in percent, the existing preparation function and `quality_policy="flag"`, `max_invalid_pct=20`, `measurement_tolerance_pct=0`. A qualifying calendar year has at least nine candidate-usable months; fewer than five qualifying years gives `insufficient_record` for every method. C0 retains all its native calculations; alternative score calculations use the same qualifying-year observations. Preserve the full monthly grid for decomposition, marking other positions unavailable.

Under `flag`, finite partially invalid observations remain candidates; fully invalid observations do not. Record unknown quality explicitly. C1 and C3 use the existing candidate weights (observed fraction, minimum 0.05, unknown quality weight 1, unusable weight 0). C0 retains its native unweighted climatological score. STL has robust residual weighting but no equivalent input-quality weighting in the selected interface. Declare this difference; do not describe the fits as identically weighted.

Run the existing `exclude` policy as a labelled sensitivity. Never add imputed observations to timing evidence, sample-size counts, or boundary processing.

## 4. Four comparison methods

### C0 — current joint gate, unchanged

Call `assess_water_regime` directly, with 200 whole-year timing bootstrap replicates and random state 0; preserve the current circular null procedure and defaults. Save the raw result as the parity oracle.

The climatological amplitude is the range of monthly means. Its SNR denominator is the mean available within-calendar-month standard deviation across years, not an independently measured observation error. The current decision order is:

1. Fewer than five qualifying years: insufficient record.
2. SNR ≥ 2 and peak resultant-length lower 95% bound ≥ 0.70: seasonal.
3. Otherwise SNR < 0.70: aseasonal.
4. Otherwise peak circular-uniformity p ≥ 0.10 with at least ten informative peak years: aseasonal.
5. Otherwise: marginal.

Preserve the native gate route: seasonal or marginal can enter per-year detection when both peak and trough evidence have at least seven informative years. This is permission to attempt detection; downstream cycle checks may still decline. SNR ≥ 2 is not a mandatory routing threshold. Report all evidence and the decisive branch, including insufficient timing and unavailable pixel support.

These cutoffs and their joint use are implementation policy. Non-rejection of circular uniformity is not proof of aseasonality.

### C1 — trend-aware harmonic predictive skill

Fit weighted least-squares models on original observed extent:

\[
M_0(t)=a+bt,\qquad
M_K(t)=a+bt+\sum_{k=1}^{K}\{c_k\cos(2\pi kt/12)+d_k\sin(2\pi kt/12)\},\quad K\in\{1,2,3\}.
\]

Use the same linear trend in both competing models. Scale/centre time using training data only. Use five contiguous outer blocks of qualifying calendar years, split as evenly as possible in chronological order. For each outer training set, select K by inner leave-one-calendar-year-out weighted prediction error; choose the smallest K within one standard error of the minimum mean inner-fold error. Compute that standard error across inner held-out years, not months. Exclude the three months immediately adjacent to each held-out block from its training set in both inner and outer evaluation. Fit only full-rank models with at least 36 positive-weight training observations; if any required fold fails, return `not_evaluable` with a reason. Do not silently reduce the period or model set.

Pool errors over outer held-out observations:

\[
H=1-\frac{\sum w_t(E_t-\widehat M_K^{(-fold)}(t))^2}
{\sum w_t(E_t-\widehat M_0^{(-fold)}(t))^2}.
\]

Retain negative skill; do not clip it. This measures recovery of held-out calendar structure beyond a linear trend, not forecast skill or a p-value. Zero baseline error with both models exact gives score 0 and `no_variation_beyond_trend`; zero baseline error with nonzero seasonal-model error gives `not_evaluable`. Define numerical zero as mean squared error ≤ `1e-20 * max(1, mean(E²))` on the same scored observations.

Map H to classes using Section 6. Save selected K by fold, both errors, predictions, first-harmonic amplitude and the fitted seasonal profile. For diagnostic full-record coefficients and C3, select K by the same year-wise rule using the full eligible record, then refit. The existing `_harmonic.py` provides related machinery but currently compares with an intercept-only baseline; it is not already this candidate.

### C2 — robust STL seasonal strength

Decompose monthly extent as `E = trend + seasonal + remainder`, with period 12, seasonal window 13, trend window 21, low-pass window 13, all LOESS degrees 1, all jumps 1, robust fitting enabled, two inner iterations and 15 outer iterations. Pin and record the implementation/package version. These are prespecified benchmark settings, not universal optimal values. The parameterisation follows the [statsmodels STL interface](https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.html) and [fit interface](https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.fit.html).

For this adapter, fill only internal unavailable runs of at most two months by linear interpolation between their nearest available neighbours, and only if unavailable months are ≤ 10% of the full grid. Any unavailable endpoint, longer run or excess fraction gives `not_evaluable: stl_gap_policy`. This is an explicit benchmark input contract, not a claim that the original STL method universally prohibits missing data. Record every interpolated position.

On original eligible observed months only, calculate

\[
F_S=\max\{0,1-\operatorname{Var}(remainder)/\operatorname{Var}(seasonal+remainder)\}.
\]

Use ordinary sample variances, without robust reweighting or counting interpolated months. A denominator below the C1 numerical tolerance gives score 0 and `no_detrended_variation`. Save all components and score denominators. Map the score using Section 6. STL decomposition alone does not establish statistical significance or a unique annual cycle. Seasonal strength is motivated by [Wang, Smith and Hyndman (2006)](https://doi.org/10.1007/s10618-005-0039-x); the exact score thresholds remain study policy.

### C3 — detrended-SNR ablation

Subtract only C1's full-record fitted linear trend, centred at the eligible-observation mean time, from the observed series. Retain the fitted seasonal component in the adjusted observations. Recompute C0's monthly amplitude and within-month variability on these adjusted values. Use a benchmark-local numerical helper; signed intermediate residuals must not be passed off as physical extent or clipped to 0–100.

Replace only the SNR argument to the existing decision policy. Hold original-data timing month sets, R, confidence intervals, p-values, informative-year counts and pixel/measurement support fixed. Retain C0's exact thresholds, including the low-SNR veto. Save both raw and adjusted SNR. If the trend fit is unavailable, the ablation is unavailable.

C3 isolates one computational change; it is not a complete validated replacement. It will not repair problems in raw-data timing identifiability or nonlinear trend handling.

### Common timing and admission diagnostic

For every method, show the same original-data peak/trough evidence alongside its classification. For C1–C3, compute a labelled **gate-admission proxy**: class is seasonal or marginal and both original timing-year counts are ≥ 7. C0 uses its returned native gate route. Do not call the proxy a newly validated routing policy, and do not run endpoint refinement in this experiment.

Use the truth columns for bimodal and drifting records to expose cases where seasonal detection and annual suitability diverge. Strong timing evidence alone does not prove one cycle per year.

## 5. Constructed records

### 5.1 Deterministic controls

Include all-zero, constant-positive, pure linear trend, an exact annual sinusoid, and the previously identified trend pair:

\[
E_t=10+5\cos(2\pi t/12),\qquad
E'_t=10+0.2t+5\cos(2\pi t/12),\quad t=0,\ldots,359.
\]

Both pair members contain the same annual component; trend alone and flat records do not. Their expected physical truth is fixed before execution. Reproduce the observed C0 diagnostic (seasonal versus aseasonal; second SNR approximately 0.488926) without using that result as truth for the alternatives. Run all 12 calendar phase shifts as symmetry checks. A method's scientifically incorrect classification is an experimental finding, not grounds to remove the case or stop the benchmark.

### 5.2 Independent simulation partitions

Use eight core families, three record lengths (7, 15, 30 years), and 100 independent records per family/length in each partition: **2,400 calibration records and 2,400 synthetic test records**. These are separate from the deterministic smoke panel.

| Family | Construction | Seasonal truth |
|---|---|---|
| White noise | Constant level plus independent noise | No |
| Persistent noise | Constant level plus AR(1), coefficient 0.8 | No |
| Trend plus persistent noise | Linear trend plus AR(1), coefficient 0.5 | No |
| Non-calendar events | Independent monthly event starts, exponentially decaying pulses | No |
| Smooth annual | Fixed annual sinusoid plus noise | Yes |
| Narrow annual peak | Fixed circular triangular pulse, two-month half-width, plus noise | Yes |
| Asymmetric annual | Repeated rise over three months and decline over nine months, plus noise | Yes |
| Annual plus trend | Same annual sinusoid plus linear trend and noise | Yes |

Generate monthly series from January 1990. Let A = 5 percentage points and centre at 50%. Normalise each deterministic annual shape to range 2A and zero mean. Draw integer calendar phase uniformly from 0–11. Alternate Gaussian noise standard deviation between 0.25A and 0.5A across replicates. Noise is independent unless the family explicitly specifies AR(1). AR innovations have variance giving this stationary marginal variance; initialise from the stationary distribution. Centre linear trends and balance end-to-end excursions of −8A, −2A, +2A and +8A across replicates. Balance the eight noise-SD/trend-excursion combinations as evenly as 100 replicates permits, instead of correlating noise level with trend sign. Event starts have probability 0.08 per month, amplitude uniform on [A, 2A], exponential decay time 1.5 months and a 120-month burn-in. Add independent Gaussian noise to that family too. Centre the event process by its generating expectation, not the realised record mean.

Reject and redraw a complete generated record if it falls outside 0–100%; log redraw counts and attempt identifiers. Do not clip, which could manufacture a seasonal plateau. All primary core records have known quality, no gaps and no pixel quantisation. This intentionally measures identifiable structure first; it does not reproduce the full EO observation process.

Use independent deterministic random streams keyed by `SeedSequence([base, family_id, length_years, replicate, attempt])`, with bases 61001 for calibration, 62001 for test and 63001 for challenges. Assign core family IDs 1–8 in table order; challenge IDs start at 101 in table order. Freeze the generator algorithm/version and configuration before fitting. Challenge levels share one base random draw per replicate and apply deterministic perturbations to it. The test stream is inaccessible to threshold selection. Paired method comparisons use the exact same generated frames. Shared-family synthetic testing measures generalisation to new draws, not new real catchments or entirely new process families.

### 5.3 Prespecified challenge panel

Use 15-year records and 100 base replicates per listed level, with pairing across methods and perturbation levels. Keep these out of threshold calibration and pooled core accuracy:

| Challenge | Fixed levels / construction | Interpretation |
|---|---|---|
| Weak annual signal | Sinusoid/noise amplitude ratios 0, 0.25, 0.5, 1, 2, 4; noise SD 2.5% | Detection and marginal-rate curves; only zero is physically non-seasonal |
| Two cycles per year | Pure six-month sinusoid; annual + second harmonic at amplitude ratios 1:1 and 1:2 | Seasonal structure can pass while one-cycle suitability fails or is ambiguous |
| Timing instability | Independent yearly phase jitter SD 0.5, 1.5, 3 months; separately monotone phase drift totalling 3 or 6 months | Distinguish periodic structure, fixed-calendar repeatability and boundary suitability |
| Changing annual amplitude | Sinusoidal amplitude grows linearly from A to 3A; separately annual component absent in middle third | Seasonal process changes; do not assign a universal three-class truth |
| Nonlinear baseline | Annual and non-annual pairs with a midpoint level step of 4A; separately a centred quadratic baseline of range 4A | Challenge the linear-trend assumption independently of annual truth |
| Missing observations | Random 10% and 25%; separately a three-month gap centred on the annual low state in every third year | Truth unchanged; score availability and lost timing evidence separately |
| Quality flags | Invalid fraction 60% at low-state months versus at peak months; separately 100%; unchanged latent series | Exercise flag/exclude policy and method weighting differences |
| Low extent and pixel support | Scale strong seasonal extent by 0.01 and 0.001; round water counts for n_valid = n_aoi = 1,000 and 100,000, n_invalid = 0 | Separate latent periodicity from observable amplitude and timing support |
| Short record | Complete 3, 4, 5 and 6-year strong annual/noise pairs | Check common insufficiency rule and distinct seven-year timing requirement |

For paired noise use the smooth annual core recipe; non-annual pairs remove only its annual component. Record the latent and observed series separately. Challenge expectations are dimensions or acceptable outcomes, not post-hoc hard labels. Phase drift is explicitly not fixed-calendar stationarity; pixel rounding may erase an otherwise present latent component.

## 6. Calibrating class boundaries without label leakage

C0 and C3 retain existing thresholds. C1 and C2 each receive their own lower and upper scalar-score cutoffs; never reuse SNR cutoffs or choose thresholds to reproduce real-catchment labels.

On the calibration core only, search pairs of ordered cutoffs drawn from midpoints between distinct finite scores, plus endpoints outside the observed range. Set the endpoint offset to `max(1, maximum_score - minimum_score)`. Scores below the lower cutoff are aseasonal; scores above the upper cutoff are seasonal; all others are marginal. Equality belongs to marginal. Also permit the explicit all-marginal rule. If there are no finite scores, calibration fails.

Choose the pair maximising the average of (i) the fraction of positive records correctly called seasonal and (ii) the fraction of negative records correctly called aseasonal, subject to both of these one-sided 95% Wilson upper bounds being ≤ 5%:

- Negative records called seasonal / all negative records.
- Strong positive records called aseasonal / all strong positive records.

Use z = 1.6448536269514722. In both the objective and error denominators retain unavailable records; separately require ≥ 95% evaluability within each truth class so unavailability cannot create a successful candidate. Break equal-objective ties by lower summed classification-error rates, then a wider marginal interval, then ascending lower cutoff. Save the score grid, search counts, selected cutoffs and achieved rates so the search can be reproduced without storing millions of candidate-pair rows. If evaluability fails, return `not_evaluable` with reason `calibration_failed` for calibrated outputs; retain raw scores but do not issue classes. If only all-marginal is selected, retain that result and its zero decisive coverage. An all-marginal rule applies only to evaluable records; unavailable status remains unavailable.

The 5% error budget, confidence convention, grid and 95% evaluability requirement are experimental policy, not literature-derived laws. Search makes these calibration bounds selection-dependent: they are selection criteria, not a guarantee. Freeze and hash cutoffs before scoring synthetic test records, challenges or real catchments. Inferential performance comes from the independent synthetic test set, conditional on the frozen simulator and selection procedure. Any later tuning creates a new experiment version and needs a fresh synthetic test stream.

## 7. Outputs and analysis

Write a new immutable run directory under `case_studies/results/seasonality-gate-comparison/<run_id>/`. Do not overwrite existing reviewed reports. Expected artifacts:

- `protocol.json`: source/spec/config hashes, baseline and benchmark commits, environment versions, seeds, method settings, input views, cutoffs and execution stage.
- `input_manifest.csv` and constructed-record metadata/frames: source provenance, periods, quality, truth dimensions, partition and hashes.
- `classifications_long.csv`: one row per record × view × method; class, status, reason, score, raw/detrended amplitude and SNR where applicable, R intervals, p-values, usable/timing years, pixel status, imputation fraction, native route or proxy and runtime.
- `classification_table.md` and `.csv`: separate real, smoke, deterministic and constructed-summary panels, with columns `record | expected truth / unlabelled | C0 | C1 | C2 | C3 | timing years | admission disagreement`. Each method cell includes class and unavailable status as necessary; link to numeric evidence. Never fill the spec's table with unexecuted predictions.
- `synthetic_metrics.csv`: error, marginal, evaluability and coverage metrics by family, length and method, plus uncertainty intervals.
- `findings.md` and figures: disagreement explanations, score distributions, weak-signal detection curves, and observed/seasonal/trend/remainder plots for each real record. Predictions and decomposition arrays are saved separately for reproducibility.

For independent synthetic test records report false seasonal and false aseasonal classification rates using all records of the relevant truth, correct decisive coverage, marginal fraction, unavailable fraction, and accuracy conditional on a decisive classification. Here decisive means an operational seasonal/aseasonal label, not an inferred confidence level. Also report admission of known unsuitable records and rejection of known suitable records, separating aseasonal classification, insufficient timing and method unavailability as reasons. Score annual suitability only where generative truth is unambiguous; this is a gate diagnostic, not endpoint accuracy.

Show both micro-averages and equal-family macro-averages. Do not advertise conditional accuracy without its coverage. Produce 95% two-sided Wilson intervals for per-stratum proportions and paired differences with 2,000 bootstrap replicates resampling whole records within family/length strata (seed 64001). Challenge variants of one base record are a cluster, not independent replicates. For the prespecified 5% acceptance targets use one-sided 95% bounds, matching calibration; do not substitute the reporting table's two-sided bounds.

For real records report pairwise disagreement counts and reasons; seven reviewed catchments cannot establish population accuracy. Inspect disagreements using raw series, quality, fitted components and timing evidence; any expert interpretation after viewing labels is exploratory. Do not score agreement with old classifications, rainfall, discharge or visual expectations as objective truth.

Secondary sensitivities are: matched record period; metadata/count view; the existing exclude-quality policy; 60/90/300 m inputs; and STL seasonal windows 7 and 25 (trend 21 and low-pass 13 unchanged). Apply frozen primary cutoffs and label these as sensitivity results. Do not choose the best sensitivity for the main table. STLs with different windows are not separately calibrated competitors in this first experiment.

## 8. Implementation boundaries and verification

The later implementation should provide a benchmark entry point in `scripts/` with separate ingestion/generation, method adapters, calibration and reporting modules. Existing production functions are called through thin adapters; exploratory harmonic/STL fitting and class mappings stay outside the public package. Add optional benchmark dependencies without changing production defaults or introducing runtime imports into the production API.

Execution order is: input/parity validation; nine smoke records and deterministic controls; a disposable small runtime pilot; core calibration; cutoff/config freeze; synthetic test and challenge evaluation; real-catchment tables; sensitivity/report generation. Pilot records use base 60001, are excluded from calibration/test metrics, and only inform batching/runtime. Changes motivated by pilot scientific outcomes must be recorded before freezing the protocol.

Focused verification must establish:

1. C0 adapter outputs match direct `assess_water_regime` outputs on identical inputs, including flat data, unknown quality and the trend pair.
2. All methods use the intended observation masks; count reconstruction, Kakadu input allowlisting and imputation provenance are checked.
3. Harmonic model selection and scaling cannot see outer held-out observations; threshold selection cannot read test/challenge/real labels or scores.
4. Synthetic truth comes from generation metadata; phase shifts preserve intended structure; non-calendar events have no imposed annual schedule.
5. Short records, unavailable fits, constant-series denominators and numerical failures receive explicit stable statuses.
6. Every table cell traces to a machine-readable result, source hash, configuration and method version; rerunning reproduces results within recorded numerical tolerances.
7. Production defaults and public classifications remain unchanged; no CAMELS source is loaded; no existing report or endpoint-refinement policy is mutated.

A completed experiment may find that every candidate has limitations. Completion requires complete, auditable tables and error accounting, not a predetermined winner or every method passing every constructed case. A candidate is eligible for further validation only if independent synthetic test upper error bounds meet the prespecified 5% targets, evaluability meets 95%, and correct decisive coverage improves over C0 without concealing serious family-specific failures. Report paired uncertainty; an interval spanning zero does not establish improvement. No result from this experiment automatically changes the paper's implemented method or promotes a default. Any proposed replacement requires an explicit subsequent decision and an independent real-data validation protocol.

## 9. Scientific basis and limits of citation support

Annual amplitude and phase have hydrological precedent in [Gnann, Howden and Woods (2020)](https://doi.org/10.5194/hess-24-561-2020). Circular statistics and their limitations for multimodal timing are discussed by [Hall and Blöschl (2018)](https://doi.org/10.5194/hess-22-3883-2018). These support descriptors, not HydroSeason's joint gate or exact thresholds.

STL originates with Cleveland et al. (1990), *STL: A Seasonal-Trend Decomposition Procedure Based on Loess*, *Journal of Official Statistics*, 6(1), 3–73 ([original-paper copy](https://yairmau.com/time-series/seasonality/cleveland-1990-STL.pdf)). Decomposition-based seasonal strength is described by [Wang, Smith and Hyndman (2006)](https://doi.org/10.1007/s10618-005-0039-x). [Papacharalampous et al. (2023)](https://doi.org/10.1186/s40645-023-00574-y) provides hydroclimatic use of such features; this is not validation for monthly EO water extent or annual boundary detection.

Separating seasonal and baseline change in Earth-observation records also has precedent in [Verbesselt et al. (2010)](https://doi.org/10.1016/j.rse.2009.08.014). BFAST, wavelets and additional decomposition families are deferred to keep the first comparison interpretable; the nonlinear and nonstationary challenges will show whether a second experiment is justified.

Literature discovery used Consensus in the preceding methodological review, with original/author/publisher checks. This specification's folds, simulation distributions, missing-data rules, window choices and calibration targets are explicit research design choices. None is presented as a cited consensus standard. The evidence supports testing the alternatives, not preselecting their superiority.
