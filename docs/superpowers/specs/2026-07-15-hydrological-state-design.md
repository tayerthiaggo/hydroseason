# Hydrological State Module — Design Spec

Date: 2026-07-15
Status: Approved for planning

## 1. Problem

`hydro_year.py` assumes every basin has a clearly bimodal wet/dry cycle
(`HydroYearConfig` hard-requires a wet window that crosses the year boundary
and a dry window that doesn't). This models monsoonal catchments like
Fitzroy/Kimberley well, but breaks down — or at best produces a meaningless
split — for perennial or weakly-seasonal/bimodal systems, where there is no
sharply defined wet or dry season, only a smaller amplitude of variation
around a mostly-wet baseline.

The goal is a **source-agnostic hydrological-stress framework** that works
identically on monsoonal and perennial systems: instead of asking "when is
the wet/dry season?", ask "how much water does this system have right now,
relative to its own normal, and when is it under stress?" Wet/dry season
labelling becomes a special case that only applies when the underlying
regime actually supports it.

## 2. Non-goals

- Does not replace or modify `hydro_year.py` / `HydroYearConfig` /
  `detect_hydrological_years`. Existing monsoonal-site consumers (Fitzroy,
  Kimberley notebooks) are unaffected.
- Does not pick a final "winner" between the two regime-classification
  methods (eta²/R/SI composite vs. Colwell indices) — both are computed and
  exposed; choosing a default is deferred to empirical validation on real
  AOIs after this module ships.
- Does not source or validate against a real perennial-basin dataset. Tests
  use synthetic series (perennial-with-noise, bimodal, flat) plus the
  existing Fitzroy monsoonal data as the seasonal contrast case.

## 3. Prior art in this codebase

A pre-strip module (`hydroseason/seasonality.py`, removed in commit
`cc13a89`, recoverable via `git show cc13a89~1:hydroseason/seasonality.py`)
already implemented a composite, non-hardcoded regime classifier for
rainfall series:

- **eta² (ANOVA between-month variance fraction)** — primary metric, robust
  to ENSO-driven amplitude modulation. Thresholds: strong ≥0.35, moderate
  ≥0.12, weak ≥0.10.
- **Circular concentration R** — from circular statistics on the 12-month
  climatology, immune to interannual noise. Thresholds: moderate ≥0.40, weak
  ≥0.25.
- **Walsh-Lawler Seasonality Index (SI)** — second concentration metric,
  confirmatory. Thresholds: moderate ≥0.60, weak ≥0.40.
- `classify_regime_composite()` combines these hierarchically (strong eta²
  alone decides; moderate eta² needs R or SI confirmation; everything weak →
  `non_seasonal`) rather than gating on one fixed threshold.

This logic is variable-agnostic (operates on a monthly value column, labelled
`Rainfall_mm` in the legacy code) and ports directly to `extent_pct`.

The same removed codebase also had a true Liebmann & Marengo (2001) /
Bombardi & Carvalho (2009) cumulative-anomaly implementation
(`segment_by_cumulative_anomaly` in `dynamic_season.py`,
`C(n) = cumsum(R - q)`, onset = argmin, demise = argmax) documented in
`docs/research_notes.md` (also recoverable at `cc13a89~1`). This is the same
mathematical family as the percentile-based stress-episode method chosen
below (§6) and is noted here as related prior art, not reused directly.

## 4. External literature grounding

- **Unified streamflow drought index** (Tijdeman et al., *Hydrological
  Sciences Journal*, 2024, DOI 10.1080/02626667.2024.2390925) — extends the
  threshold method to perennial and intermittent rivers with one consistent
  metric, avoiding regime-specific statistical treatment. Confirms the
  "one metric, any regime" framing is an established approach, not a novel
  risk.
- **Variable/day-of-year threshold methods (Q95 via Flow Duration Curve)** —
  baseline computed per calendar position with a rolling reference period,
  rather than one fixed global threshold.
- **Non-stationary baseline literature (SPI/SPEI)** — Lisonbee et al. 2024
  ("A Review of Climate Normals for Drought Indices") and related 2026 work
  confirm that a fixed reference climatology is a known, citable problem
  under trend/non-stationarity, and that moving-window reference periods are
  the standard mitigation.
- **Flash drought via satellite Land Surface Water Index** (ScienceDirect,
  2022, S2352938522000787) — percentile-based onset/intensification
  (decline from above P40 to below P20, minimum decline rate per interval)
  applied directly to a satellite-derived water index. This is the closest
  published precedent to the exact input variable used here (water extent,
  not streamflow or precipitation).
- **Colwell (1974) predictability/constancy/seasonality indices** — an
  established, data-driven alternative for classifying flow regimes
  (perennial/intermittent/ephemeral) without a hardcoded amplitude
  threshold, used as the second regime-classification method for empirical
  comparison against the ported eta²/R/SI composite.

## 5. Architecture

New standalone module `hydroseason/hydrological_state.py`, alongside
`hydro_year.py` (unmodified). Top-level entry point:

```python
result = analyze_hydrological_state(extent, window_years=12)
result.regime            # SeasonalityResult — diagnostic, both methods
result.hydro_years        # DataFrame — anchor always; wet/dry iff seasonal
result.wsi                 # Series — Wetness State Index, always computed
result.stress_episodes     # DataFrame — always computed
```

Every basin gets a `hydro_years` table (the anchored 12-month cycle is
required scaffolding for all downstream metrics — occurrence, refuge area,
etc. — regardless of regime) and always gets `wsi` + `stress_episodes`. Only
`regime` and whether `hydro_years` carries wet/dry season labels depend on
the detected regime. Nothing here blocks or short-circuits on regime — it
is informative metadata attached to the result, per the approved design
turn.

## 6. Components

### 6.1 `classify_seasonality_regime(extent, *, value_col="extent_pct", method="both")`

Ports the legacy composite classifier (§3), renaming the rainfall-specific
column default to `extent_pct` and updating docstring "typical values"
guidance to reference water-extent seasonality rather than rainfall. Adds
a second, independently-computed method:

- **Colwell indices**: predictability (P), constancy (C), contingency (M)
  computed from the monthly extent matrix (years × months). High
  constancy relative to contingency indicates a perennial/non-seasonal
  regime; high contingency indicates a predictable seasonal cycle.

`method="both"` (default) computes and returns both; `method="eta_r_si"` or
`method="colwell"` restrict to one for callers who have already validated
which method suits their data.

```python
@dataclass(frozen=True)
class SeasonalityResult:
    regime: Literal["seasonal", "borderline", "non_seasonal"]
    regime_source: str                  # e.g. "eta_squared", "colwell_predictability"
    eta_squared: float
    circular_R: float
    walsh_lawler_si: float
    colwell_predictability: float | None
    colwell_constancy: float | None
    colwell_contingency: float | None
```

The composite `regime` field is derived from the eta²/R/SI hierarchy (ported
as-is, thresholds unchanged from legacy since they are dimensionless ratios
independent of the input variable). Colwell values are always reported
alongside for comparison; no fusion between the two methods is attempted in
this iteration.

### 6.2 Hydro year anchor (always) + season labels (conditional)

Generalises `suggest_hydro_year_config`. New function
`suggest_hydrological_state_config(extent, *, regime=None, **overrides)`:

1. Computes monthly climatology, finds `trough_month` (climatological
   minimum) — always, regardless of regime.
2. Hydro year is anchored as `[trough_month + 1, ..., trough_month]`
   (start = month after the historical driest month, end = the historical
   driest month itself) — this is the same convention already used
   implicitly by `suggest_hydro_year_config`'s wet/dry geometry, now made
   the explicit, regime-independent rule.
3. If `regime` (from §6.1, or passed explicitly) is `"seasonal"`: also
   computes `wet_start/end`, `dry_start/end` via the existing contiguous-run
   logic from `suggest_hydro_year_config`, and downstream
   `label_hydrological_months`-equivalent output carries `season` values of
   `"Wet"` / `"Dry"`.
4. If `regime` is `"borderline"` or `"non_seasonal"`: only the anchor
   (`trough_month`, `peak_month` as `historically_driest_month` /
   `historically_wettest_month` metadata) is returned. No `Wet`/`Dry` season
   is asserted; a new `season_mode` field on the config/result is set to
   `"anchor_only"` (vs. `"labeled"`), and month labelling returns
   `season="unassigned"` rather than forcing a Wet/Dry split onto a flat or
   bimodal climatology.

This requires a new config shape distinct from `HydroYearConfig` (which
hard-validates wet-window-crosses-year-boundary geometry unconditionally) —
`HydrologicalYearAnchor` or similar, detailed in the implementation plan.

### 6.3 `compute_wetness_state_index(extent, *, window_years=12, spread="both")`

- Moving-window baseline, calendar-month-aware: for each month `t`, the
  reference window is the trailing `window_years` of *that same calendar
  month* (e.g. Wetness for July 2020 compares against July values from the
  preceding `window_years` years), not a flat trailing window across all
  months. This avoids conflating seasonal cycle with anomaly, and directly
  addresses the trend concern raised in brainstorming: a basin drying out
  since the 2000s gets a baseline that tracks the recent normal rather than
  diluting the signal against a multi-decade historical average.
- `center` = rolling median of that calendar-month window.
- `spread`: `"mad"` (median absolute deviation, default per approved
  config), `"iqr"`, or `"both"` (both computed, exposed as separate
  columns — no forced single choice, per brainstorming decision).
- `WSI_t = (extent_t - center_t) / spread_t` (one column per spread metric
  if `spread="both"`).
- Requires at least `window_years` of prior same-calendar-month data before
  producing a non-NaN value for a given month — early series years are
  NaN by construction, not silently zero-filled.

### 6.4 `detect_stress_episodes(wsi, *, onset_pctile=40, trough_pctile=20, min_decline_rate=None)`

Percentile-based, adapted from the satellite LSWI flash-drought method
(§4) to monthly cadence:

- Percentiles are computed on the WSI distribution itself (already
  standardized), not on raw extent.
- Episode **onset**: first month WSI crosses from ≥ P40 to < P40 with a
  sustained decline (guards against single-month noise the same way the
  legacy Liebmann audit flagged "lonely storm months" as a failure mode —
  here, "lonely wet-month noise").
- Episode **intensification**: continues while WSI keeps falling toward
  P20; **trough** = local minimum WSI within the episode.
- Episode **recovery**: first month WSI returns to ≥ P40.
- **Severity**: cumulative WSI deficit below the P40 threshold across the
  episode (run-theory / Yevjevich-style integrated deficit, computed within
  episodes already delimited by the percentile method — not used as the
  primary detection method, only as the within-episode severity summary).

Output: one row per detected episode with `onset`, `trough_month`,
`trough_wsi`, `recovery`, `duration_months`, `severity` (cumulative deficit).
Runs identically regardless of regime — this is the universal metric that
replaces "is it dry season" with "is this basin under stress right now,
relative to its own normal."

## 7. Data contracts

- Input: same `extent` shape as `hydro_year.py` accepts today (`pd.Series`
  or `pd.DataFrame` with `value_col`/`date_col`), monthly cadence, reuses
  `_coerce_monthly_series` from `hydro_year.py` rather than duplicating
  coercion logic (import, don't fork).
- Output dataclasses/DataFrames are new to `hydrological_state.py`; no
  existing `hydro_year.py` return shapes change.
- `hydroseason/__init__.py` exports the new public surface:
  `analyze_hydrological_state`, `classify_seasonality_regime`,
  `compute_wetness_state_index`, `detect_stress_episodes`,
  `suggest_hydrological_state_config`, `SeasonalityResult`.

## 8. Testing strategy

- **Synthetic perennial series**: flat climatology + Gaussian noise, no
  seasonal cycle. Assert `classify_seasonality_regime` returns
  `non_seasonal` (or `borderline` at the noise boundary) from both methods;
  assert `hydro_years` is `anchor_only`; assert `wsi`/`stress_episodes`
  compute without error and produce sane values (no NaN explosion, no
  spurious Wet/Dry labels).
- **Synthetic bimodal series**: two peaks/troughs per year. Assert regime
  classifier does not force a single wet/dry split; assert anchor still
  resolves to a single trough month (documented as an accepted degenerate
  case, consistent with existing `suggest_hydro_year_config` behaviour on
  bimodal climatologies).
- **Synthetic monsoonal series** (sharp single peak/trough, low noise):
  assert `regime == "seasonal"` from both methods, and that resulting
  `wet_start/end`/`dry_start/end` match what `suggest_hydro_year_config`
  would already produce on the same series (regression-style parity check
  against existing behaviour).
- **Fitzroy/Kimberley real data** (already in the repo via the STAC
  notebook / example data): regression check that `classify_seasonality_regime`
  labels it `seasonal`, as a real-world sanity check alongside the
  synthetic cases.
- **Injected trend**: synthetic series with a step or linear drying trend
  partway through. Assert moving-window WSI baseline tracks the trend
  (post-trend months are not all flagged as extreme stress relative to a
  now-stale pre-trend baseline) — this is the direct regression test for
  the non-stationarity concern raised in brainstorming.
- **Stress episode edge cases**: no episodes (always-wet series), one long
  episode, multiple short episodes, episode active at series end
  (no recovery yet — must not crash, should report `recovery=NaT`/open).

## 9. Open items deferred past this plan

- Choosing a default regime-classification method (eta²/R/SI vs. Colwell)
  once validated against a real perennial/weakly-seasonal AOI.
- Any integration between `hydrological_state.py` outputs and
  `hydro_year.py` consumers (deliberately out of scope — new module is
  additive only, per approved design).
