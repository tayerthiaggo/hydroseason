# G2: are the looser gates' extra dates right? A known-truth test (pre-registration)

Status: **frozen before any outcome**, 2026-11-02. The project lead asked for the test after G1 and agreed that the known answer can be synthetic. The SHA-256 of this file goes into the receipt before the main runs. Later edits are reported as deviations.

Background: G1 ([results](2026-11-02-g1-gate-calibration-results.md)) found that looser gates pass the pre-registered reproducibility rules: an amplitude-to-floor ratio of 1.5 instead of 3.0, and 2 peak water pixels instead of 5. Split-half reproducibility cannot see errors both halves share, and the 0.2.0 synthetic suite has no records with a ratio between 0 and 3. G2 asks whether the cycles the looser gates admit are dated correctly when the answer is known.

## Principles

- **Known answer.** Every record is built so that its trough month is set before any method sees it.
- **Not referenced to gauges.**
- **Library untouched.** Gate values are set inside worker processes exactly as in G1 (`scripts/gate_calibration.py`, `_set_gates` and `_run`, imported unchanged). Every run records the gate values it read back.
- **Default is no change.** Unless every rule below holds, the recommendation is to keep the current gates.

## Two arms

### Arm S: synthetic records

Each record is a monthly count series, 2006-01 to 2025-12 (240 months). All draws come from one seeded generator per record.

- **Area:** `n_aoi` = 10^U(2, 5) pixels, from 100 to 100,000.
- **Water:** a peak fraction P = 10^U(−2.5, −0.5) of the area and a low fraction L = P × U(0, 0.8). The seasonal amplitude is A = P − L, scaled each year by exp(N(0, 0.25)).
- **Season shape,** alternating by seed:
  - `sine`: a cosine with its minimum at the trough month m;
  - `pulse`: a four-month wet pulse after m, then a recession that falls to its lowest value at m. So m is the end of the dry-season low.

  m is drawn uniformly from the 12 months and is the same every year.
- **Shared monthly noise:** N(0, σ) on the wet fraction, with σ = A / k and k = 10^U(log10 0.5, log10 30). Each month also has a 4% chance of a false-water spike of U(1, 4) × σ. The wet fraction is clipped to [0, 1].
- **Observation:** valid-pixel fractions are borrowed month by month from a real G1 half-series (2006–2025), chosen by seed from all 319 windows. That gives real cloud and gap patterns, including months with nothing observed. `n_valid` = round(fraction × `n_aoi`), and `n_water` ~ Binomial(`n_valid`, wet fraction).
- **Truth:** the trough boundary falls at month m in every year.

**Null records** use the same draws for area, water, noise and observation, with no fixed season:
- `flat`: constant wet fraction L + A/2;
- `random_pulse`: each year, one two-month flood of amplitude A starting in a random month.

A null record has no true annual cycle.

### Arm I: known seasons injected into real flat records

- **Backgrounds:** the 287 G1 calibration half-series (half A only) that route to event characterisation with the gates open. Their own noise, gaps, false water and floods stay in place.
- **Injection:** each background gets four injections with different seeds, two of each shape. Each injection is a `sine` or `pulse` season with trough month m and a peak of W water pixels over the full area, scaled each year by exp(N(0, 0.25)).
  - W = k × the background's noise in pixels, with k = 10^U(log10 0.5, log10 30).
  - The background's noise is 1.4826 × the median absolute month-to-month change of `n_water` / √2, and at least 1 pixel.
  - Injected water in a month is Binomial(round(expected water), `n_valid` / `n_aoi`), and `n_water` is capped at `n_valid`.
- **Truth:** the trough boundary falls at month m in every year.

## Runs

Every record runs twice with `analyze_catchment(..., phase_scheme="two_phase", quality_policy="flag")` on count input: once with the current gates (3.0, 5 pixels) and once with the chosen gates (1.5, 2 pixels).

Seeds:

| Set | Seeds | Records |
| --- | --- | ---: |
| Arm S, seasonal | 100000–100999 | 1,000 |
| Arm S, null | 110000–110399 | 400 (200 `flat`, 200 `random_pulse`) |
| Arm I | 120000–121147 | 1,148 (4 per background) |
| Pilots (never scored for accuracy) | 190000–190099; 191000–191099 (arm I) | 200 |

## Checks before the freeze (no accuracy is computed)

1. **Construction:** 24 noise-free arm S records (12 trough months × 2 shapes, 100,000 pixels, every pixel observed, no noise) run with the current gates. Their trough boundaries must fall at m in at least 95% of cycles, the first and last cycle excluded. If one shape fails, its truth is redefined from the noise-free run before the freeze, and the change is recorded.
2. **Pilot:** 100 pilot records (60 arm S, 40 arm I) run with both gates. Only run times and the number of dated trough boundaries in each band are looked at. The main sample sizes above stand unless the pilot predicts fewer than 300 dated boundaries in the admitted band of either arm. In that case they are scaled up before the freeze.

**Construction check outcome (recorded before the freeze).** The `pulse` shape put 216 of 216 interior trough boundaries at m. The `sine` shape put 158 of 216 at m and the other 58 at m + 1, all in years where the method found a two-month low (m and m + 1, status `interval`). The boundary then falls at the end of that low, as the method defines it. So, for `sine` records, the true boundary is m or m + 1, and errors are measured to the nearer of the two. Under that truth, the check finds 216 of 216 for both shapes. `pulse` truth is unchanged. Results are also reported by shape.

**Pilot outcome (recorded before the freeze).** The first pilot predicted enough admitted-band dates in both arms: about 1,300 in arm S and about 370 in arm I. But it predicted only about 57 `point` dates in arm I's admitted band, below the 100 that rule 1 needs. A second pilot of 100 arm I records (seeds 191000–191099) put the rate at 35 `point` dates per 140 records across both pilots. Arm I was therefore raised from two injections per background to four, for about 290 expected. Only counts and run times were looked at.

## Definitions

- **Dated trough boundary:** `trough_timing_status` is `point`, `interval` or `broad`, as in G1.
- **Error:** the distance in months from a dated trough boundary to the nearest true trough month (for `sine`, the nearer of m and m + 1). **Correct** means within 1 month, as in G1. A dated boundary in a null record is always false.
- **Admitted band:** dated trough boundaries in the chosen-gate run whose cycle has a ratio below 3.0 or fewer than 5 peak water pixels. These are the dates the looser gates add.
- **Current margin:** dated trough boundaries in the current-gate run whose cycle has a ratio from 3.0 to below 6.0, with at least 5 peak water pixels. These are the weakest dates the current gates already accept.

## Decision rules

The looser gates pass G2 only if all of the following hold.

1. **Precise dates stay safe (the 0.2.0 safety rule).** In each arm, among `point` trough boundaries in the admitted band, the 95% Wilson upper bound of the share that are not correct is at most 0.05.
2. **Admitted dates are about as good as the current margin.** In each arm, the accuracy of the admitted band minus the accuracy of the current margin is:
   - at least −0.05 as a point estimate;
   - and at least −0.10 at the lower end of its 95% interval, from a 2,000-draw bootstrap over records (seed 0).
3. **Null records do not turn seasonal (arm S).** The share of null records routed to per-year detection, chosen minus current, has a 95% interval whose upper end is at most 0.02. The interval comes from a paired bootstrap over null records, with 2,000 draws and seed 0.

A rule whose band holds fewer than 100 cases in an arm cannot be evaluated, and then G2 does not pass.

If G2 passes, the remaining pre-release checks from G1 follow: X1 under the chosen gates, the impact tables, then a `hydroseason-v0.3.0` policy. If it fails, the current gates stay and the results are published.

## Reported, not used to decide

- Accuracy by ratio band (1.5–2, 2–2.5, 2.5–3, 3–4, 4–6, 6–10, 10 and up) and by peak water pixels (2–4, 5–19, 20 and up), under each gate.
- Accuracy of all dated trough boundaries, and the share of seasonal records routed to per-year detection, under each gate.
- Rules 1 and 2 for the current margin itself, so the current gates are held to the same standard.
- Both arms split by season shape, and arm I by the background's water type.

## Limits stated in advance

- **Synthetic noise is a model.** Arm S uses real gaps but modelled noise. Arm I keeps real noise but adds a modelled season.
- **One trough month per record.** Real seasons shift from year to year; here only the amplitude does.
- **Backgrounds that are not quite flat.** An arm I background may carry a weak season of its own that pulls dates away from the injected one. That affects both gates alike.
- **Not accuracy for real places.** The test says whether the gates' extra dates are right on records like these, not that any real record's date is right.
