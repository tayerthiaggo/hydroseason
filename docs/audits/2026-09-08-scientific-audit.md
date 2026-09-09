**HydroSeason scientific, mathematical, and architectural audit — 8 September 2026**

**Verdict.** Preserve the central design: water-only inference, explicit abstention, equivalent-extremum sets, year-level circular summaries, and constrained valley fitting. These are defensible choices. The current evidence does **not** establish statistical optimality, calibrated confidence coverage, or end-to-end superiority of trough refinement. The largest publication risks concern the observation model, interpretation of statistical evidence, and validation design—not the choice of PAVA.

This audit reviews the working tree at commit `aaf231a655a22ad1e4698a6fea25199f373c9784`, including pre-existing uncommitted edits. Package metadata reports 0.2.0. The supplied briefing was found at `docs/superpowers/audit_briefing.md`, rather than `docs/superpowers/audit/_briefing.md`. Library code and existing files were not changed. Recommendations below are proposals, not implemented behavior.

**1. Correct the briefing before using it as a manuscript source**

Several descriptions differ materially from the executable code:

| Briefing claim | Current implementation | Implication |
|---|---|---|
| Extent is `100*n_water/n_aoi` | `_state_input.py:58` computes `100*n_water/n_valid` | This is the wet fraction of observed pixels within a spatial mask. Whole-mask extent requires assumptions about unobserved pixels. |
| Detectability noise has an AR(1) correction | `_boundary.py:150` removes calendar-month medians, then uses MAD of successive residual differences divided by sqrt(2), without AR correction | The briefing combines distinct estimators. `_events.py:78` does apply AR correction to the raw series. |
| Kuiper produces an exact empirical p-value | `_circular_timing.py:117` uses random rotations, at least 999 null draws, and a plus-one Monte Carlo p-value | Correct discrete-null construction is a strength; exhaustive exactness and Monte Carlo estimation are different claims. |
| Fixed climatological windows are an automatic fallback | `decide_established` sets `supports_fixed_window=False`; `_catchment.py` falls back to events on dynamic failure | Describe the authoritative default path separately from legacy or explicitly imposed APIs. |
| `annual_shape_match` compares the typical annual hydrograph | `_recurrence_identifiability.py:57` compares date clusters separated by approximately 12 months | It examines temporal geometry, not amplitude, hydrograph shape, or an independently estimated typical profile. |
| Wider windows require more contiguous cycle months | `_assemble_dynamic_cycle` retains an absolute minimum usable-month count; window support has a separate denominator | Wider search can move shared boundaries and shorten adjacent cycles. The dropout mechanism is not simply a longer required contiguous record. |
| Low spells are below median plus one noise scale | `_events.py` uses median **minus** one scale in noise mode; quantile fallback is separate | Correct the scientific definition. |

There is also a candidate geometry artifact selecting `(base radius, adaptive radius, adaptive minimum) = (4,4,8)`. It contains 240 calibration seeds, not a completed independent validation campaign. The operational `DynamicHydroYearConfig` still defaults to `(3,5,6)`, with base minimum 8. Candidate constants should not be described as promoted defaults.

The `min_timing_years=5` evidence override belongs to the experimental challenger. The established timing-identifiability gate still uses `min_informative_years=7`. These policy families must remain distinct in the paper.

**2. Detectability floor: retain the screening concept; correct its statistical interpretation**

Let observed extent be `y_t`, latent extent be `x_t`, and measurement error be `e_t`. The current rule is approximately

\[
 A=\max_t y_t-\min_t y_t,\qquad
 F=\max\{\tau,\widehat\sigma_\Delta,q_{\rm peak},q_{\rm trough},\epsilon\},
 \qquad A/F\ge3,
\]

with positive-amplitude checks and, where available, at least five observed water pixels at an exact maximum. Here `tau` is in percentage points, even though the argument is named `measurement_tolerance_pct`.

**Keep:** the maximum combines minimum practical requirements transparently; it avoids summing several floors that need not be independent uncertainty components. The ratio and pixel support checks are useful engineering screens. Equivalent-extremum sets are preferable to arbitrary first-occurrence `idxmin` ties.

**Do not claim:** `A/F >= 3` is a three-sigma hypothesis test, that the floor estimates instrument noise alone, or that its equivalence sets are automatically confidence intervals.

The range is selected over many observations. Even for independent Gaussian errors with known standard deviation, a range exceeding three standard deviations is much more common than a single positive three-sigma excursion. Temporal dependence, bounded percentages, zero inflation, classifier errors, and varying spatial support further invalidate that interpretation.

The actual boundary scale is

\[
 r_t=y_t-\operatorname{median}_{j:m(j)=m(t)} y_j,
 \qquad \widehat\sigma_\Delta=
 \frac{1.4826\operatorname{MAD}(r_t-r_{t-1})}{\sqrt2}.
\]

For a stationary Gaussian residual process with variance `sigma_r^2` and lag-one correlation `rho`,

\[
 \operatorname{Var}(r_t-r_{t-1})=2\sigma_r^2(1-\rho).
\]

Thus the estimator approaches `sigma_r*sqrt(1-rho)` under its idealized assumptions. Positive residual correlation lowers it. However, dividing by an estimated AR factor is **not automatically the right fix**: residuals contain physical hydrological variability and timing shifts as well as measurement error. Estimating correlation from raw extent confounds seasonal dynamics with error dependence. Clipping a fitted correlation to `[0,0.9]` is a regularization policy, not a statistical identity.

Both relevant difference estimators drop unusable observations before differencing. A January-to-April difference can therefore be treated as one monthly step. For an AR(1) residual and a gap of `h` months, the variance is `2*sigma_r^2*(1-phi^h)`, not the one-month expression. A narrow justified improvement is to use truly adjacent month pairs; a broader model may handle actual lag explicitly.

**Measured example:** for 20 years of noiseless `50+20*sin(2*pi*t/12)`, boundary noise was `4.47e-14` pp, but event noise was `15.401` pp. The estimators are measuring different quantities. The event value is not sensor uncertainty. This does not prove the event detector fails for every seasonal catchment; it disproves a universal measurement-noise interpretation.

**Pixel resolution is not measurement accuracy.** `100/n_valid` is one-pixel quantization of observed fraction. It does not capture spatially correlated misclassification, geolocation error, subpixel mixing, or missing-water bias. Five water pixels may include adjacent classification errors; the gate is a minimum support heuristic, not a probability guarantee. The DEA product explicitly distinguishes water from pixels obscured by cloud, shadow, and sensor problems. [DEA Water Observations](https://knowledge.dea.ga.gov.au/data/product/dea-water-observations-landsat/)

The distinction between observed and whole-mask fractions supplies a useful mathematical foundation. Let `f_t=n_valid/n_aoi`, and temporarily assume valid-pixel water classifications are correct. Without assumptions about missing pixels,

\[
 x_t\in[\ell_t,u_t]=[f_t y_t,\ f_t y_t+100(1-f_t)].
\]

These are deterministic missing-support bounds, **not** confidence bounds for classifier error. With `f=0.5` and observed extent `y=20%`, whole-mask extent can lie anywhere from 10% to 60%. A one-pixel floor cannot account for this ambiguity.

Recommended hierarchy:

1. Retain the current floor as a named, calibrated practical screen. Publish each component and whether pixel support is available.
2. Separate residual variability, pixel resolution, missing-support sensitivity, and classification uncertainty. Do not collapse their meanings into one `sigma_noise` label.
3. For CSVs, accept physical metadata or user-supplied measurement tolerance when available. Otherwise report that physical detectability is unverified. Do not reject all count-free CSVs or invent pixel counts.
4. Where calibrated simultaneous measurement intervals `[L_t,U_t]` are available, derive possible extrema by

\[
 \mathcal M_{\min}=\{t:L_t\le\min_s U_s\},\qquad
 \mathcal M_{\max}=\{t:U_t\ge\max_s L_s\}.
\]

On the event that every latent value lies in its interval, these sets contain its true extrema. A conservative amplitude lower bound is

\[
 A_{\rm lower}=\max\{0,\max_t L_t-\min_t U_t\}.
\]

An entirely missing month has `[0,100]` support and can remain an extremum candidate. Removing that ambiguity requires explicit physical or shape assumptions. This is a useful partial-identification extension, not a requirement to replace the working detector immediately.

For the existing floor-equivalence rule, calibrate false detection and timing-set coverage against latent truth under dependent, heteroscedastic, zero-inflated observation models. Independent Gaussian noise alone is inadequate.

**3. Circular timing: sound representation, conditional evidence**

The correct record summary for `N` informative years is

\[
 z_y=\frac1{|M_y|}\sum_{m\in M_y}e^{i2\pi(m-1)/12},\qquad
 \bar z=\frac1N\sum_y z_y,\qquad R=|\bar z|.
\]

Each year has total weight one. Retain this: a year with three equivalent months should not count as three independent annual observations. Also retain year-level bootstrap resampling and a discrete 12-month null.

Equal weighting within a candidate set is a transparent uncertainty convention, not a posterior probability derived from the observation process. Accordingly, `R` combines interannual concentration with within-year ambiguity. If every year has the same three-month interval, `R=(1+2*cos(pi/6))/3 ≈ 0.911`, despite identical interval centers. This behavior is useful, but thresholds must be interpreted accordingly.

Only resolved annual sets enter the regime summary. The result estimates concentration **conditional on detectability and identifiability**. Seasonal clouds or low-amplitude years can make that subset systematically unrepresentative. Bootstrap intervals conditional on selected sets do not propagate uncertainty from estimating the floor, building the sets, narrowing recurrence, or selecting years.

The annual Kuiper implementation rotates each year's full month set independently, preserving its internal spacing. Its null is random calendar orientation conditional on those shapes. This is appropriate when calendar rotations are exchangeable under the observation process. It is not automatically valid when some months are much more likely to be observable. For publication, simulate or randomize through the complete observation-and-selection pipeline while preserving the actual seasonal observation opportunity and relevant serial structure.

The plus-one Monte Carlo calculation is good practice. At 999 draws and a true tail probability near 0.10, Monte Carlo standard error is approximately `sqrt(0.1*0.9/999)=0.0095`. This matters when the route changes at 0.10. Use more draws for decisions close to a threshold or report a Monte Carlo uncertainty band and an indeterminate result when it straddles the threshold. More draws reduce numerical uncertainty, not uncertainty from a short record.

Two hundred bootstrap replicates leave roughly five draws in each 2.5% tail. Increase the publication analysis to a predeclared larger count and check interval stability. Use blocks of consecutive years where interannual dependence is material; do not assume that resampling years independently resolves ENSO-scale dependence. Refit the relevant stages within resamples if claiming unconditional timing uncertainty. Drift estimates need extra care when timing crosses the selected angular branch cut or changes mode; a single linear slope around one dominant month is not universally valid.

**Bimodality:** add a descriptive second circular moment before introducing mixture machinery:

\[
 R_k=\left|\frac1N\sum_y\frac1{|M_y|}
 \sum_{m\in M_y}e^{ik\theta_m}\right|,\quad k=1,2.
\]

Equal antipodal modes have `R_1=0`, `R_2=1`. This identifies an axis, not which mode occurred first, whether both occurred in every year, or whether they represent two independent hydrological years. Compare within-year pulse occurrence, annual and semiannual harmonics, and separated-mode timing. A dual von Mises mixture is optional when sample size supports it and the components are stable under resampling. Two wet seasons should normally remain two episodes within one annual regime, rather than two objects misleadingly called years. Circular hydrological seasonality and its bimodal limitations already have direct precedent. [Berghuijs, Hale and Beria, 2025](https://hess.copernicus.org/articles/29/2851/2025/)

**4. Decision policy: abstention is defensible; non-rejection is not evidence of aseasonality**

The established rule combines climatological amplitude SNR, peak concentration, and a Kuiper threshold. Its strongest route safeguard is the second timing gate on the cycles actually produced. Keep it.

The key inferential flaw is labeling a record `aseasonal` because Kuiper `p >= 0.10`. A large p-value means the selected test did not detect departure from its null; it does not establish uniform timing. Insufficient power, missingness, diffuse annual timing, and an inappropriate null can all produce that result. The distinction is consistent with the ASA's guidance on p-value interpretation. [ASA statement](https://doi.org/10.1080/00031305.2016.1154108)

A conservative decision to withhold annual boundaries may still be reasonable. The **scientific label and explanation** must say whether annual structure was contradicted or merely not established.

The policy also has a record-length discontinuity. Holding summary evidence fixed at SNR 1, concentration 0.2, interval `[0,0.5]`, and p=0.5, the decision function allows `per_year_detection` at 9 informative years, but switches to `event_characterisation` at 10. This is a demonstrated decision-function property, not an observed frequency of false annualisation in real data. The downstream gate may further reject a particular record.

The trough timing summary is passed to `decide_established` but is not used for concentration-based classification; trough information enters through counts. Also, `min(n_peak,n_trough)>=7` need not mean seven **jointly** informative cycles. Disjoint peak-resolved and trough-resolved subsets can satisfy separate counts. Report their intersection and justify which denominator matches the claim being made.

A scientifically cleaner conceptual policy separates:

- **Annual structure:** supported, weak/unsupported, or uncertain.
- **Per-cycle boundary recoverability:** point, interval, broad, or unresolved.
- **Operational action:** dynamic segmentation, descriptive events, or explicitly imposed calendar summaries.

For positive annual evidence, compare an annual or multimodal seasonal predictor against an appropriate nonseasonal baseline using blocked out-of-sample evaluation. A skill quantity could be

\[
 S=1-\frac{\sum_{t\in\mathrm{test}}\ell(y_t,\hat y_{\rm seasonal,t})}
 {\sum_{t\in\mathrm{test}}\ell(y_t,\hat y_{\rm baseline,t})}.
\]

Define the baseline to include justified persistence or trend; comparison only with a constant mean can exaggerate seasonal skill. Require an uncertainty bound above a scientifically meaningful skill margin for strong claims, alongside detectable amplitude and recoverable timing. To claim practically absent annual structure, use an upper bound below a predeclared minimum meaningful effect. Otherwise retain uncertainty. No new numerical thresholds are recommended without calibration.

The repository already contains challenger machinery for predictive skill. Evaluate it against this requirement before writing another subsystem. Preserve established behavior until a versioned challenger wins independent validation.

SNR itself is a useful descriptive contrast but conflates measurement error, year-to-year amplitude variation, trends, and timing shifts. A physically seasonal system with changing amplitude can have low SNR. Conversely, seven informative years within a much longer episodic record do not establish recurrence in the intervening years. Publish informative-year fractions and zero-water-year counts alongside absolute thresholds.

**5. Resolution of the trough geometry trade-off**

The briefing's edge-hit percentages are development evidence, not truth-based boundary errors. A lower observed value beyond an edge challenges the boundary; it does not prove that value belongs to the intended cycle. Left-only retries also alter the apparent left/right asymmetry, so the residual histogram cannot directly justify `[-2,+4]`.

Current retry logic has three leftward restrictions: `_adaptive_edge_retry_years`, `not_later_than`, and acceptance only when a candidate is earlier than its original boundary. Mirroring the trigger alone will not enable a right-moving correction.

The candidate `(4,4,8)` artifact should finish its declared evaluation before adding a competing mechanism. Reported calibration metrics include median absolute error 0, mean signed bias +0.292 months, coverage-drop rate 0.139, and abstention 0.276. The key named `boundary_mae` is actually a **median**, not a mean. Zero median error can coexist with a substantial error tail. Neither those numbers nor reduced edge hits establish optimal geometry.

**Proposed mathematical resolution: local candidate expansion with invariant evidence requirements and paired cycle validation.** This is a bounded follow-up design, consistent with the existing 0.3.0 document's bidirectional-retry re-entry condition. Do not silently expand the current calibration grid after seeing validation outcomes.

Let boundaries be `b_(i-1), b_i, b_(i+1)`, and `u_t` indicate usable observation. Define

\[
 C(a,b)=\sum_{a<t\le b}u_t.
\]

Keep the original search opportunity `W_i^0=[a_i-3,a_i+3]`. When edge evidence challenges `b_i`, inspect an extension on the relevant side, capped by predeclared limits and neighboring cycle structure. The extension provides optional candidate evidence. It does not retroactively replace the original window's quality denominator with the number of all newly searched months.

For a proposed boundary `b`, require

\[
 b_{i-1}<p_i<b<p_{i+1}<b_{i+1},
 \qquad C(b_{i-1},b)\ge q_i,
 \qquad C(b,b_{i+1})\ge q_{i+1},
\]

where peaks are identifiable anchors and `q_i,q_(i+1)` are the existing cycle-specific minimum counts. For interval peaks, require ordering for all retained plausible peak dates or downgrade unresolved overlap. Require local observation support around the challenged boundary and evidence of continuing recession or eventual recovery appropriate to the chosen boundary definition. A search-edge hit alone is insufficient. Missing outer months contribute uncertainty; they are not evidence of a lower trough.

For a rightward move, let

\[
 G(b)=\sum_{b_i<t\le b}u_t.
\]

Then exactly

\[
 C(b_{i-1},b)=C(b_{i-1},b_i)+G(b),\qquad
 C(b,b_{i+1})=C(b_i,b_{i+1})-G(b).
\]

Thus a necessary usable-count condition is

\[
 G(b)\le C(b_i,b_{i+1})-q_{i+1}.
\]

This explicitly exposes the following cycle's available observation budget. Example: moving a boundary two usable months later preserves both cycles if the following cycle has 10 usable months and requires 8. It fails that condition if the following cycle has only 9. A global radius change does not express this local dependency.

Reassemble **both** affected cycles before accepting the proposal. Require unchanged peak evidence where that is the declared pass-2 contract, valid timing, unique ordered boundaries, and no newly uncomputable cycle. Commit or roll back both together. `_apply_trough_refinement` already contains much of this transaction pattern; reuse it rather than building another assembly engine. Keep non-target boundaries fixed during an isolated proposal. If multiple proposals interact, validate against the current accepted sequence and record any order dependence; use joint candidate optimization only if that interaction proves consequential.

This guarantees no loss of the chosen usable-count admissibility among accepted local moves. It **does not guarantee** every clipped trough is recoverable, all quality labels remain unchanged, or statistical coverage of timing intervals. A corrected boundary can reveal that a previously reported cycle was unsupported. Retaining its old date solely to maintain output counts would be scientifically wrong: preserve it as provisional evidence or abstain, with the challenge recorded.

There is a fundamental information limit. Two latent series can agree on every observed month while having different true minima inside a missing interval. No algorithm can distinguish them without additional assumptions or observations. Therefore zero clipping error, zero abstention, and unchanged information requirements cannot all be guaranteed for arbitrary missingness.

**Boundary target must be explicit.** The observed absolute minimum and the last low-state month before recovery are different estimands. An exact plateau admits many equivalent minimum dates; selecting its right endpoint is an operational convention. Preserve `raw_trough_month`, the low-state interval, selected boundary, and recovery onset separately. Never present a refinement that deliberately shifts off the raw minimum as an improvement in raw-minimum accuracy.

**What not to add now:** a universal asymmetric window, a new rainfall prior, or wholesale Bayesian segmentation. Rainfall-conditioned inference changes the water-only estimand and violates the current ancillary-context invariant. If later justified, water-only trend or recession information can define a prior, but estimate and validate it independently of the boundary being judged. A principled symmetric radius winner remains preferable if it passes the predeclared safety and accuracy criteria.

**6. PAVA audit: retain the optimization core; repair uncertainty and validation**

For fixed low-state interval `[a,b]`, the fitted valley solves

\[
 \min_{\mu}\sum_t w_t\rho_k((y_t-\mu_t)/s)
 \quad\text{subject to}\quad
 \mu_1\ge\cdots\ge\mu_a=\cdots=\mu_b\le\cdots\le\mu_n.
\]

With positive weights and fixed positive scale, this is a convex optimization problem. Generalized PAVA is an appropriate solver for the monotone branches; pooling uses the minimizer of the summed block loss. The shared low level can be profiled over branch breakpoints. This is established optimization methodology, not a new general PAVA algorithm. [de Leeuw, Hornik and Mair, 2009](https://www.jstatsoft.org/article/view/v032i05)

The implementation uses generalized L1/Huber PAVA, rather than merely running ordinary squared-loss PAVA once and calling it robust. It handles zero scale through L1, avoiding division by zero. These are good choices at the optimization level.

**Independent check:** 35 random fixed-block problems, each under L1 and two Huber scales, were compared with independent linear-programming/SLSQP solutions. All 105 oracle solves succeeded. Maximum absolute objective disagreement was `5.05e-11`. This supports numerical correctness on bounded cases; it is not a proof of correctness for every input or a scientific validation of boundary selection.

Huber limits the influence of amplitude outliers. It does not know whether a short positive pulse is rainfall, a flood, regulation, or classifier error. A broad genuine rewetting episode can violate the one-valley model. Preserve pulse diagnostics and abstention for competing modes. A persistent alternative mode should not be dismissed as noise merely because a robust fit can absorb it.

Six changes or clarifications are justified before promotion:

**6.1 Scale units and the measurement floor.** `_convex_loss` is dimensionless for `s>0`, but returns `sum(w*abs(y-fit))` in percentage points when `s=0`. The same `profile_loss_cutoff=0.05` therefore changes units across the branch. `_local_scale` uses the pixel floor only if both residual estimators vanish; a small positive residual estimate can remain below one-pixel resolution.

Reproduction: `[90,60,30,10,10.2,45,80]` with no count metadata and perfect quality gives zero local scale and candidate set `{April}`. Multiplying values by 0.01, leaving the profile policy unchanged, gives `{March,April}`. This illustrates the cutoff's amplitude dependence in L1 mode. Physical detectability can legitimately depend on amplitude; the problem is an undocumented change in the loss unit.

Choose a coherent interpretation: use a positive, independently justified scale in every profile calculation, with `s=max(s_residual,s_measurement)` where both are meaningful; or define and calibrate a separate L1 cutoff explicitly in pp. If no positive measurement scale is available, deterministic exact-minimizer sets are defensible, but their confidence level is unknown. Do not insert arbitrary machine epsilon and call it measurement precision.

**6.2 Fit tolerance is not a confidence interval.** Endpoint plausibility uses

\[
 [L(b)-L_{\min}]/\sum_t w_t\le c.
\]

This is an average-loss equivalence threshold. `sum(w)` is an information proxy, not a statistically derived effective sample size. Normalized Huber loss with heuristic coverage weights is not automatically a correctly specified log-likelihood. No Wilks chi-square cutoff or confidence interpretation follows, particularly after searching the low-state block and selecting peaks.

Calibrate boundary-set inclusion against independently generated latent truth, with interval width, abstention, and conditional error reported together. A refitted block/bootstrap procedure is a candidate, but extrema and change locations are nonregular: its coverage must itself be checked. Calling the output a support set is appropriate until that validation exists.

**6.3 Do not truncate uncertainty to the exact optimum.** `_trough_refinement.py:828` caps the final plausible endpoint cluster at its latest exact optimum, even if later endpoints pass the declared profile tolerance. That can be an operational rule for assigning rising months to the next cycle. It is not a valid reason to delete statistically plausible later boundaries from an uncertainty set. Return the full calibrated support set separately from the chosen operational date. Test sensitivity to tiny perturbations around the optimum; floating-point equality is not physical identifiability.

**6.4 Preserve calendar gaps during quality sensitivity.** `_quality_sensitivity` removes rows with `frame.drop`; `_refine_selected_span` then treats neighboring retained positions as consecutive evidence. Reproduction using `[90,60,30,10,20,45,80]` with May removed yields `confirmed` and `recovery_start=May`, although May is absent. This is an internal scenario-path finding; normal input preparation initially creates a regular month grid. Preserve the missing row as unobserved, or explicitly carry elapsed calendar time and forbid recovery claims across it.

Perturbing one low-quality month at a time also does not explore all joint combinations of missing-pixel outcomes. Describe it as sensitivity screening, not a worst-case robustness certificate.

**6.5 Enumerated blocks need identifiable semantics.** Multiple `[a,b]` constraints can yield the same flat fitted bottom. Optimization may be nonunique even when fitted values agree. State the tie rule and distinguish a fitted low plateau from a confidence interval on departure. A singleton valley can also have many isotonic steps on either branch, so shape constraints do not eliminate every form of overfitting. Assess shape violations out of sample before adding smoothness penalties. For 7–20 month spans, no solver rewrite is justified solely for speed; profile longer spans and sensitivity combinations first.

**6.6 The existing validation report is too narrow for its integration claims.** In `_trough_refinement_calibration.py:95`, `_cache_row` evaluates `refine_trough_span` directly and sets `peak_changed=False`, `duplicate_or_nonmonotonic=False`, and `new_uncomputable=False` as constants. These gates are structural/not exercised in this harness. Their zeros are not empirical validation of full-cycle recomputation.

The synthetic `pass1_boundary` is generated at `_synthetic.py:1200` by selecting the truth interval start, sometimes shifted one month earlier. It is not produced by running the actual pass-1 detector. Therefore the published pass-1 versus pass-2 median/p90 comparison measures improvement over that synthetic comparator, not measured superiority over HydroSeason's first pass.

The synthetic challenge distribution is also unusually favorable: most families use 0.03 pp noise over an approximately 80 pp swing, and noise is explicitly zeroed at the peaks and designated trough. The low-variability family supplies an already-unresolved peak, short-circuiting refinement. Distinct seeds do not remove these shared structural assumptions.

Finally, `boundary_set_inclusion` tests whether predicted and truth intervals **overlap**. It does not require the entire truth set to be covered. For plateau truth, overlap can be a useful compatibility score, but it cannot be described as full set inclusion. False precision is counted only for singleton predictions on unresolvable truth; it does not count every erroneous singleton on otherwise resolvable cases, or narrow misleading intervals. Overall abstention is also different from the reported abstention restricted to resolvable truth.

Retain this harness as component validation. Add a separate full-pipeline comparison that runs actual pass 1 and pass 2 on identical complete records; measures all recomputed quantities; and reports singleton correctness, operational-date error, set overlap, full-set containment where appropriate, width, and abstention with explicit denominators. Existing integration tests remain valuable, but cannot convert hard-coded report fields into measured cohort results.

**7. Architecture: preserve separation; remove ambiguity at scientific interfaces**

The strongest choices are pure numerical functions, optional geospatial dependencies, frozen policy objects, deterministic random streams, transactional adjacent-cycle recomputation, and rainfall supplied after water inference. Keep all of them. No wholesale refactor is warranted.

Targeted improvements:

- **One authoritative decision object.** `_regime.public_route(regime)` maps seasonal/marginal labels directly to per-year detection without timing evidence. It cannot represent the full authoritative policy. Document/deprecate the shortcut or require the decision object, preventing future callers from bypassing the timing gate.
- **Explicit evidence contracts.** Represent scientific regime, observation quality, boundary uncertainty, operational date, and confidence status separately. A refinement marked `confirmed` may still carry an interval; downstream users must not infer point precision from that word alone.
- **Named estimators.** Keep event variability and deseasonalized boundary variability separate if their purposes differ. Share calendar-aware input handling, not an accidentally misleading generic noise label.
- **Policy provenance.** Record the actual active geometry, recurrence policy, refinement policy, measurement tolerance, input/mask identity, seed, package version, and source revision. `candidate_for_established` describes provenance and approval status; it does not itself prevent code from using a constant.
- **Fingerprint scope.** Hashing selected source functions does not recursively hash their callees. For example, the geometry fingerprint lists detector entry points but omits `_assemble_dynamic_cycle` and core `_boundary` implementations from its direct source list. The briefing's claim that any relevant logic change necessarily trips staleness checks is too broad. Cover scientific dependency closures or include a source-tree/revision manifest, while retaining finer fingerprints to identify what changed.
- **Expected abstention versus software failure.** `_catchment.py` catches a broad `ValueError` from dynamic analysis and routes to events. The warning is useful, but malformed input or an internal invariant failure is not evidence for an event-based hydrological regime. Use typed expected nonrecoverability outcomes; surface unexpected failures clearly.
- **Preflight scope.** A 10% recurrent-water screen can reject a valid rare-flood system with no persistent refuge. Treat acquisition feasibility as a documented domain restriction and test false exclusions separately. An efficiency screen cannot demonstrate absence of scientifically useful ephemeral water. Existing override paths, if used, should be reported.

Quality climatology should remain a useful anomaly diagnostic. Its p90 measures unusual cloudiness for a month, not reliable extent. Leaving out the target year reduces self-influence but does not repair a persistently cloudy decade. Use an independent/frozen reference or robust temporal comparison, while retaining absolute missing-support sensitivity and explicit unknown quality.

Strict condition baselines prevent dubious boundaries from defining historical percentiles; retain that protection. However, resulting percentiles are conditional on accepted clear, identifiable cycles. If wettest years are cloudiest, they are not automatically an unbiased baseline for all years. Report eligible counts and exclusion patterns, use a frozen reference period for comparisons, and evaluate rank sensitivity. Terms such as “recharge” and “refuge” should be defined as extent-based proxies; recharge flux, accessible water supply, and habitat quality are not observed directly.

**8. Publication: strongest contribution and required evidence**

The defensible novelty is a **validated, observation-aware framework deciding when satellite surface-water records support dynamic annual segmentation, when only timing intervals are identifiable, and when event descriptions are more defensible**. Its strength is the integration and demonstrated consequences, not a claim that circular statistics, adaptive seasonal timing, or PAVA are new.

Avoid “first rigorous framework” until a systematic prior-art review supports a narrow claim. Australia's Bureau of Meteorology already defines catchment water years using the minimum mean monthly flow, so a universal comparison only against July–June is insufficient. [BOM Hydrologic Reference Stations glossary](https://www.bom.gov.au/water/hrs/glossary.shtml)

Satellite seasonal-parameter extraction also has a long methodological history. TIMESAT extracts seasonal dates and amplitudes from smoothed satellite records; its vegetation application differs from HydroSeason, but the general idea of data-derived seasonal boundaries is prior art. [Jönsson and Eklundh, 2004](https://www.sciencedirect.com/science/article/pii/S0098300404000974)

A strong evaluation should include:

1. **Real, blinded boundary references.** Reserve previously uninspected catchments stratified by climate, regulation, waterbody type, spatial support, and cloud regime. Use independent image interpretation, finer temporal observations where available, and multiple annotators allowed to assign intervals or “unresolvable.” Keep motivating/protected catchments in development evidence.
2. **Observation realism.** Simulate latent extent separately from observation: nonlinear recession, variable pulse timing/amplitude/duration, zero inflation, persistent errors, seasonal and flood-dependent clouds, spatially clustered misclassification, changing valid footprint, trends, and sensor-era changes. Perturb true extrema too. Hold out entire process families as well as seeds.
3. **Actual baselines.** Compare calendar/administrative years, locally optimized fixed water years, actual shipped dynamic detection, and the candidate refinement on the same observations. Add one credible harmonic/smoothing or change-point comparator when it answers a distinct question. Do not demand sophisticated baselines merely to increase their count.
4. **Risk versus coverage.** Report probability of a materially wrong boundary conditional on publishing one, fraction published, error quantiles, signed error, interval width, and abstention. Also report false annualisation on aseasonal truth and false abstention on seasonal truth. A policy that abstains on everything can have zero false precise outputs.
5. **Dependence-aware uncertainty.** Bootstrap catchments across real cohorts and preserve temporal blocks within long records. Report family-level synthetic results. Wilson bounds require a defensible Bernoulli sampling unit; thousands of dependent cycles are not thousands of independent replications. A zero-error upper bound describes the evaluated population, not a universal safety guarantee.
6. **Downstream scientific effect.** Measure event splitting, changes in persistence/drawdown, condition rankings, trend estimates, and ecological interpretation. Test whether adaptive segmentation creates duration or selection artifacts. Since `T_i=b_i-b_(i-1)` varies, compare integrated metrics together with duration-normalized metrics. Do not compare a 9-month and a 15-month integral as if both covered 12 months.
7. **Spatial and temporal transfer.** Treat 30 m as the native reference for this DEA product, not truth. Hold footprint and temporal compositing constant when evaluating 60/90/300 m. Report resolution failures by waterbody size and geometry, and validate against independent imagery where possible. Monthly sampling cannot establish submonthly flood peaks or exact recovery dates.
8. **Reproducibility and analysis discipline.** Archive the full pipeline, manifests, observed and latent synthetic data, labels, frozen configurations, and all exclusions. Separate parameter selection from final evaluation. If validation informs redesign, it becomes development evidence and a new held-out evaluation is needed. Deterministic seeds and hashes make this auditable; they do not eliminate researcher selection bias.

For HESS/WRR, the paper needs a hydrological result—for example, where dynamic boundaries materially alter inference and where abstention prevents unsupported conclusions. For RSE, prioritize the observation model, cloud/missingness effects, and transfer across sensors/resolutions. This is an editorial assessment of the contribution, not a prediction of acceptance. A software-centered paper can instead emphasize reproducible implementation and validated workflow reliability.

Keep the narrative proportional: fixed water years are useful for accounting, storage budgets, and comparability. They are not inherently scientifically invalid in aseasonal catchments. The error is interpreting a fixed reporting boundary as an observed seasonal transition. Test the consequences rather than asserting that fixed dates universally corrupt trend analysis.

**9. Rainfall lag and hydrological inertia: useful extension, separate estimand**

Retain rainfall as external context. A circular peak-month lag is descriptive phase difference; it does not identify catchment residence or retention time. Extent can respond nonlinearly to storage and is not discharge. Seasonal translation already has a hydrological-signature literature that should frame this extension. [Gnann et al., 2020](https://hess.copernicus.org/articles/24/561/2020/)

Under the explicitly assumed linear reservoir model

\[
 \frac{dS}{dt}=I(t)-S/\tau,\qquad Q=S/\tau,
\]

the input-to-output transfer is `H(i*omega)=1/(1+i*omega*tau)`. If extent were approximately linear in storage over the analyzed range and inputs were suitable effective inflow, an annual phase lag `Delta` would satisfy

\[
 \phi=\omega\Delta=\arctan(\omega\tau),\qquad
 \tau=\tan(\omega\Delta)/\omega,
 \quad \omega=2\pi/12\ \mathrm{month}^{-1}.
\]

This only supports positive lags below a quarter period in this simple model; estimates become unstable near three months. Raw catchment rainfall is not effective inflow, and translation delays, evaporation, regulation, groundwater exchange, and extent–storage geometry violate the assumptions. Do not transform the current integer month lag directly into a residence-time claim.

A safer extension is an empirical response kernel `x_t=alpha+sum_(k=0)^K h_k P_(t-k)+e_t`, constrained and regularized only where justified. Its centroid `sum(k*h_k)/sum(h_k)` is a response timescale under that model, not water-particle age. Require blocked predictive validation and assess seasonality confounding; cross-correlating two seasonal climatologies alone is insufficient. Keep all such modeling downstream from water-only boundaries.

**10. Priority decisions**

**Do now for the scientific record:** correct briefing equations and policy descriptions; distinguish uncertainty from non-rejection; relabel validation metrics with their actual denominators and scope; state the raw-minimum versus recovery-boundary estimands.

**Before refinement promotion:** resolve profile-loss units and the gap-preservation issue; separate the operational endpoint from its support set; run a full detector comparison using real pass-1 outputs and measured integration invariants; expand independent noise/missingness challenges.

**Before changing trough geometry:** finish evaluation of the frozen `(4,4,8)` candidate. If the declared failure conditions remain, test bounded bidirectional proposals with paired cycle checks. Change the active policy only if it earns better error–coverage performance on held-out data.

**Keep unless evidence says otherwise:** generalized PAVA, water-only authority, explicit abstention, one weight per informative year, discrete Kuiper rotations, conservative baseline eligibility, and the lightweight core dependency structure. Bayesian priors, mixture models, smoothing penalties, and architectural rewrites are optional research directions, not prerequisites.

**11. Verification and audit limits**

Reproducible numerical probes are in [2026-09-08-audit-probes.py](2026-09-08-audit-probes.py). They require SciPy only as an independent audit oracle. Run from the repository root:

```powershell
.\.venv\Scripts\python.exe docs\audits\2026-09-08-audit-probes.py
```

Verified environment: Python 3.12.13, NumPy 2.4.6, pandas 3.0.3, SciPy 1.18.1. The initial shell Python was 3.14, outside the package's declared range; verification was repeated using the repository's supported Python 3.12 environment.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_circular_timing.py tests/test_timing_identifiability.py tests/test_decision_policy.py tests/test_trough_refinement.py tests/test_trough_geometry_corpus.py tests/test_release_metadata.py tests/test_dynamic_year.py -q --disable-warnings
```

Result: **176 passed, 1 failed, 2 warnings** in 31.63 seconds. The failure is `test_no_gitignored_or_process_files_are_tracked_in_git`: two already-tracked files match `.gitignore`:

- `docs/superpowers/plans/2026-09-06-two-pass-trough-refinement.md`
- `docs/superpowers/specs/2026-09-06-two-pass-trough-refinement-design.md`

This metadata failure was present before audit artifacts were added. It does not establish a numerical defect. All selected scientific/dynamic test cases passed. Passing existing tests does not resolve the inferential or validation-design findings above.

This is an in-depth audit of the requested numerical and routing paths, their synthetic validation, and connected scientific interfaces. It is not an exhaustive raster-acquisition/security review, systematic global novelty search, rerun of every calibration campaign, or blinded annotation of the reported real-catchment cohort. The briefing's 420-cycle statistics are treated as reported development evidence; no new empirical claim is made about their true boundary accuracy.
