# Dynamic Hydrological-Year and Surface-Water Condition Design

Date: 2026-07-15
Status: Approved

## 1. Purpose

`hydroseason` exists primarily to describe annual surface-water dynamics in
intermittent rivers from remote-sensing time series. For every hydrological
year, users need the observed wet peak, two mid-dry measures, the ending dry
minimum, and metrics describing drawdown and persistent-pool resilience.

The new module extends that core workflow to weakly seasonal, bimodal, and
perennial-like rivers and wetlands without weakening the intermittent-river
case. It also places each annual peak and trough in historical context so
sequences of unusually dry or wet years remain visible.

The scientific claim is deliberately narrow:

> The module measures **surface-water extent condition and timing** within a
> supplied AOI or an explicitly aggregated basin. It does not infer discharge,
> storage volume, ecological condition, hydrological drought, or causal
> attribution without external validation.

## 2. Design decisions

1. Hydrological years are **dynamic trough-to-trough cycles**.
2. The full record supplies an initial expected annual phase; each nominal
   cycle then selects its own observed trough and peak.
3. Exactly one nominal trough opportunity exists per year. A missing or
   unusable cycle is reported as unresolved, never silently merged with an
   adjacent cycle.
4. Users may override expected phase and search tolerance, but do not need to
   provide fixed hydrological-year dates.
5. Automatic seasonal-pattern classification is advisory. It suggests the
   starting configuration and never overrides user configuration.
6. Intermittent rivers are the primary case. Other regimes are supported as
   diagnostics and graceful fallbacks.
7. Annual recharge and refuge conditions are separate axes. A low peak and a
   low trough answer different ecological questions.
8. Individual AOIs and basin aggregates use the same analysis, but aggregation
   occurs on pixel counts or explicit area weights before annual metrics are
   calculated.
9. Remote-sensing observation quality is propagated. Unknown quality is never
   treated as fully observed.
10. Existing `hydro_year.py` APIs remain available and unchanged. The new
    dynamic implementation is additive until Fitzroy regression tests show it
    is safe to replace or wrap existing behaviour.

## 3. Non-goals

- No rainfall-derived Walsh-Lawler thresholds.
- No Colwell state-bin indices.
- No fixed wet/dry split imposed by a regime label.
- No automatic claim that a low surface-water observation is drought or
  ecological stress.
- No moving-window WSI, flash-drought detector, or trend significance test in
  this iteration.
- No blind averaging of AOI percentages into a basin percentage.
- No gap filling or fabrication of water extent.
- No requirement that perennial or bimodal systems expose meaningful Wet/Dry
  labels.

These exclusions keep the module practical and remove methods that are not
directly transferable to remotely sensed river and wetland extent.

## 4. Inputs and quality contract

### 4.1 Monthly extent

Accepted input remains compatible with `_coerce_monthly_series`:

- `pd.Series` with monthly timestamps and surface-water extent values; or
- `pd.DataFrame` with `value_col`, optional `date_col`, and optional quality or
  pixel-count fields.

Preferred DataFrame fields are:

| Field | Unit | Meaning |
|---|---:|---|
| `extent_pct` | 0-100 | Water pixels divided by valid in-AOI pixels |
| `n_water` | pixels | Pixels classified as water |
| `n_valid` | pixels | Pixels validly classified as water or dry |
| `n_invalid` | pixels | In-AOI pixels without a valid classification |
| `n_aoi` | pixels | Total in-AOI pixels |
| `invalid_pct` | 0-100 | `100 * n_invalid / n_aoi` |

The conversion to observed fraction is:

```text
observed_fraction = 1 - invalid_pct / 100
```

The old draft's `1 - invalid_pct` conversion was wrong because repository
`invalid_pct` values are percentages, not fractions.

### 4.2 Quality states

- `usable`: extent exists and `invalid_pct <= max_invalid_pct`.
- `low`: extent exists but invalid coverage exceeds the configured limit.
- `missing`: extent is missing.
- `unknown`: extent exists but observation quality was not supplied.

Default `max_invalid_pct=20.0`, matching `detect_hydrological_years`.
`unknown` observations may be analysed only when
`allow_unknown_quality=True`; their outputs remain labelled `unknown`.

Low, missing, and unknown months do not become peak/trough candidates unless
the caller explicitly relaxes the relevant guard. An unresolved year remains
in the annual table with a reason code.

## 5. Advisory seasonal-pattern model

### 5.1 Why the previous classifier is removed

Walsh-Lawler SI and its published thresholds describe rainfall concentration.
Circular concentration applied to absolute water extent is strongly affected
by perennial baseline area and cancels opposing bimodal peaks. Colwell indices
depend materially on arbitrary state bins and record length. Raw eta-squared
thresholds also cannot be retained unchanged after switching estimators.

Those methods are removed rather than ported under a new variable name.

### 5.2 Replacement: small harmonic model

`classify_seasonal_pattern` fits three models to usable monthly extent:

1. intercept only;
2. intercept plus annual sine/cosine terms;
3. intercept plus annual and semi-annual sine/cosine terms.

Model selection uses AICc. The selected 12-month fitted curve is inspected for
one or two distinct local maxima. Whole-year bootstrap resampling reports
support for the selected shape and uncertainty in expected peak/trough month.
Fewer than five complete years returns `insufficient_record`. A fitted annual
range no greater than `measurement_tolerance_pct` (default 1.0 percentage
point) returns `low_variability`. An intercept-only winner or bootstrap support
below 0.80 returns `weak_or_irregular`; otherwise the number of fitted local
maxima separates `unimodal_annual` from `bimodal_or_complex`.

```python
@dataclass(frozen=True)
class SeasonalPatternResult:
    pattern: Literal[
        "unimodal_annual",
        "bimodal_or_complex",
        "weak_or_irregular",
        "low_variability",
        "insufficient_record",
    ]
    expected_peak_month: int | None
    expected_trough_month: int | None
    secondary_peak_month: int | None
    secondary_trough_month: int | None
    seasonal_strength: float
    bootstrap_support: float
    peak_phase_iqr_months: float | None
    trough_phase_iqr_months: float | None
    n_complete_years: int
```

The classifier is advisory:

- it seeds an expected primary trough and peak;
- it warns when phase is unstable or the record is insufficient;
- it never suppresses annual metrics;
- it never changes an explicit user configuration;
- a bimodal record still uses one caller-selected primary trough for annual
  accounting, while retaining secondary phase metadata.

## 6. Dynamic trough-to-trough hydrological years

### 6.1 Configuration

```python
@dataclass(frozen=True)
class DynamicHydroYearConfig:
    expected_trough_month: int
    expected_peak_month: int | None = None
    trough_search_radius_months: int = 3
    dry_plateau_rule: Literal["last_before_confirmed_recovery", "middle", "first"] = "last_before_confirmed_recovery"
    sustained_rise_months: int = 2
    pulse_rejection_window_months: int = 4
    max_invalid_pct: float = 20.0
    allow_unknown_quality: bool = False
    min_usable_months_per_cycle: int = 8
    min_usable_trough_candidates: int = 2
    min_baseline_cycles: int = 10
    low_percentile: float = 20.0
    high_percentile: float = 80.0
    measurement_tolerance_pct: float = 1.0
```

`suggest_dynamic_hydro_year_config` creates this configuration from the
advisory model. The returned object is a starting point for inspection and
optional user refinement, not fixed annual dates. When the advisory model has
no stable trough phase, suggestion fails clearly and asks the caller to supply
`expected_trough_month`; it never invents a boundary from an unstable fit.

### 6.2 Nominal trough opportunities

For each calendar year, construct one candidate window centred on that year's
`expected_trough_month`, extending `trough_search_radius_months` in each
direction. Default windows may shift an observed trough three months early or
late.

Within each window:

1. retain usable observations;
2. choose the minimum extent;
3. resolve equal or near-equal minima with `dry_plateau_rule`;
4. record phase shift from the expected trough;
5. report the opportunity as unresolved when candidate coverage is
   insufficient.

`last_before_confirmed_recovery` is default. It selects the last usable month in
a low plateau before a recovery is confirmed. Confirmation requires
`sustained_rise_months` consecutive usable months above the plateau by
`measurement_tolerance_pct`, followed by no return to that low plateau during
`pulse_rejection_window_months`. Thus a mid-dry rainfall pulse which rises for
two months then recedes is not allowed to end a hydrological year: the detector
continues to the later low-water opportunity and records the reversal as a
rewetting pulse. This represents the end of dry-refuge conditions better than
the arbitrary middle of a long zero-water plateau.

If recovery cannot yet be confirmed because the record ends inside the
rejection window, retain the best trough but set `boundary_status=provisional`
and lower confidence. A return to the plateau rejects the putative recovery; a
coverage gap makes the transition partial rather than assumed. `middle` and
`first` remain explicit alternatives for studies needing those conventions.

One nominal opportunity per year prevents adjacent hydrological years from
being merged. An unresolved opportunity breaks the sequence; detection does
not connect the previous trough directly to the following year's trough.

### 6.3 Dynamic cycles

A resolved cycle starts one month after the previous resolved trough and ends
at the current trough. Its length changes when wet or dry phases arrive early
or late.

Within that trough-to-trough span:

- `peak_month`: greatest usable extent;
- `peak_extent_pct`: extent at peak;
- `temporal_mid_dry_month`: observed month nearest the temporal midpoint from
  peak to ending trough;
- `temporal_mid_dry_extent_pct`: extent in that month;
- `half_loss_target_pct`: `(peak_extent_pct + trough_extent_pct) / 2`;
- `half_loss_month`: first usable post-peak month at or below the target;
- `half_loss_extent_pct`: observed extent in that month;
- `trough_month`: ending minimum;
- `trough_extent_pct`: extent at ending minimum;
- `drawdown_pct`: peak minus trough;
- `persistence_ratio`: trough divided by peak, with an explicit zero-peak
  guard;
- `recession_months`: peak-to-trough duration;
- `half_loss_months`: peak-to-half-loss duration;
- `cycle_months`: trough-to-trough duration.

If a late within-cycle flow pulse raises extent after the half-loss threshold
was crossed, the first crossing remains the half-loss timing metric and
`n_rewetting_pulses` records subsequent material reversals. A material pulse is
an increase greater than `measurement_tolerance_pct`.

For `bimodal_or_complex` patterns, output also records highest secondary peak
and lowest secondary trough when separated from primary extrema by at least two
months. They are descriptive only; configured primary trough defines boundary.

### 6.4 Annual output contract

`detect_dynamic_hydrological_years` returns one row per nominal cycle,
including unresolved rows. Core columns are:

```text
hy_year, status, status_reason,
hy_start, hy_end, cycle_months,
peak_month, peak_extent_pct, peak_invalid_pct,
temporal_mid_dry_month, temporal_mid_dry_extent_pct,
half_loss_month, half_loss_extent_pct, half_loss_target_pct,
trough_month, trough_extent_pct, trough_invalid_pct,
boundary_status,
drawdown_pct, persistence_ratio, recession_months, half_loss_months,
n_rewetting_pulses, n_usable_months, confidence,
secondary_peak_month, secondary_peak_extent_pct,
secondary_trough_month, secondary_trough_extent_pct
```

Cycle status values are `complete`, `partial`, and `unresolved`.
`boundary_status` is `confirmed` or `provisional`. Confidence reflects
candidate coverage, quality, and boundary status; it is not inferred solely
from drawdown size.

## 7. Historical recharge and refuge condition

Annual magnitude is evaluated independently of annual timing.

- **Recharge condition** compares each cycle's peak with historical peaks.
- **Refuge condition** compares each cycle's ending trough with historical
  troughs.

The reference is fixed and explicit:

- `reference="full_record"` for retrospective description; or
- caller-supplied `reference_start` and `reference_end` for monitoring without
  future leakage.

Reference-year percentiles use leave-one-out ranking. Fewer than
`min_baseline_cycles` complete cycles produces continuous values but no public
condition label. A `low_variability` pattern also returns continuous annual
metrics but sets recharge/refuge labels, combined condition, and sequence
counts to `not_applicable_low_variability` unless caller explicitly opts in.
This prevents measurement-scale perennial variation being called extreme.

Each axis is `low` at or below P20, `high` at or above P80, and `typical`
between them. Public combined states are:

| Recharge | Refuge | `annual_condition` | Interpretation |
|---|---|---|---|
| high | high | `wet_persistent` | Strong recharge and strong retention |
| high | low | `recharged_then_contracting` | Strong recharge followed by large loss |
| low | high | `buffered_low_recharge` | Weak recharge but retained refuge water |
| low | low | `dry_low_refuge` | Weak recharge and poor ending refuge extent |
| otherwise | otherwise | `typical_or_mixed` | Neither axis is jointly extreme |

Annual public output adds:

```text
peak_percentile, trough_percentile,
recharge_condition, refuge_condition, annual_condition,
peak_change_from_previous_pct, trough_change_from_previous_pct,
consecutive_dry_cycles, consecutive_wet_cycles
```

Consecutive dry/wet counts apply only to `dry_low_refuge` and
`wet_persistent`. Continuous percentile columns remain the primary scientific
values; labels are concise interpretation aids.

## 8. Monthly surface-water condition

`compute_monthly_surface_water_condition` compares each usable observation
with the same calendar month in the fixed reference period. It reports an
empirical percentile and robust median anomaly:

```text
extent_pct, reference_median_pct, anomaly_pct,
condition_percentile, reference_n, quality_state
```

No moving reference is included in this iteration. A fixed reference preserves
multi-year dry/wet sequences and keeps retrospective and operational meanings
clear.

Low-condition runs may be summarized as descriptive runs below a configured
percentile. They are called `low_surface_water_runs`, not drought or stress
episodes.

## 9. AOI and basin scales

### 9.1 AOI/reach analysis

Each fixed reach, pool complex, or wetland AOI receives its own monthly series,
advisory pattern, dynamic hydrological years, and annual condition table.

AOI boundaries and pixel area are provenance, not incidental metadata. A
boundary change creates a new series identity.

### 9.2 Basin aggregation

Preferred aggregation sums counts by month:

```text
basin_n_water = sum(aoi_n_water)
basin_n_valid = sum(aoi_n_valid)
basin_extent_pct = 100 * basin_n_water / basin_n_valid
```

It also reports AOI coverage and invalid pixel counts. If pixel counts are not
available, aggregation requires an explicit AOI area weight. Unweighted means
of percentages are rejected.

The basin monthly series then passes through the same dynamic detector. Basin
hydrological years are not made by averaging AOI annual tables; different AOIs
may peak and contract at different times.

## 10. Public API

```python
pattern = classify_seasonal_pattern(extent)
config = suggest_dynamic_hydro_year_config(extent, pattern=pattern)
annual = detect_dynamic_hydrological_years(extent, config=config)
annual = classify_annual_surface_water_condition(annual)
monthly = compute_monthly_surface_water_condition(extent)

result = analyze_hydrological_state(extent, config=config)
result.pattern
result.config
result.hydro_years
result.monthly_condition
result.data_quality
```

```python
@dataclass(frozen=True)
class HydrologicalStateResult:
    pattern: SeasonalPatternResult
    config: DynamicHydroYearConfig
    hydro_years: pd.DataFrame
    monthly_condition: pd.DataFrame
    data_quality: dict
```

Existing `detect_hydrological_years`, `HydroYearConfig`, reports, and notebooks
continue to work. New report integration occurs only after Fitzroy parity is
reviewed.

## 11. Validation

### 11.1 Deterministic mock benchmark

A fixed-seed monthly panel covers at least 30 years and contains:

1. a primary intermittent unimodal reach with year-to-year phase jitter;
2. deliberately early and late troughs;
3. multi-year low-peak/low-trough and high-peak/high-trough sequences;
4. high-peak/low-trough and low-peak/high-trough mixed cases;
5. dry-season rewetting pulses which must not create an early boundary;
6. a low-variability perennial-like wetland;
7. a bimodal floodplain series;
8. cloud gaps correlated with the wet season;
9. one unresolved nominal year that must not merge adjacent cycles; and
10. several AOIs with unequal sizes for basin aggregation.

Ground-truth peak, trough, temporal midpoint, half-loss, annual condition, and
sequence membership are stored independently of detector output.

Acceptance gates:

- no resolved nominal cycles are merged or duplicated;
- the deliberately unresolved year stays unresolved;
- at least 90% of detectable mock peaks and troughs are within one month of
  ground truth;
- selected extents exactly equal source observations at selected dates;
- at least 90% of detectable half-loss dates are within one month;
- all four extreme recharge/refuge combinations are classified correctly;
- low/unknown-quality observations never receive high confidence; and
- basin count-weighting matches direct summed-pixel arithmetic.

### 11.2 Fitzroy regression gate

Create a small frozen monthly CSV from the existing Fitzroy/Kimberley notebook
output, with provenance and no network dependency. Run old and new detectors
side by side.

Required comparison table:

```text
hy_year,
old_peak_month, new_peak_month, peak_shift_months,
old_end_dry_month, new_trough_month, trough_shift_months,
old_peak_extent_pct, new_peak_extent_pct,
old_end_extent_pct, new_trough_extent_pct,
old_confidence, new_confidence
```

Acceptance gates:

- identical set of nominal hydrological-year labels for years with adequate
  data;
- no merged or duplicated hydrological years;
- median absolute peak and trough timing shift no greater than one month;
- larger differences are listed for scientific review, not hidden by relaxing
  tests; and
- legacy outputs remain unchanged because the existing API is additive.

### 11.3 Australian real-case direction

Recommended validation sequence:

1. **Fitzroy/Kimberley**: immediate regression against existing repository
   results.
2. **Gilbert River, Queensland**: best open intermittent-river science case.
   Tayer et al. provide 1986-2023 remote-sensing, rainfall, discharge, dynamic
   hydrological-year results, open data (`10.26182/866c-5c36`), and code
   (`tayerthiaggo/irivermetrics`). Use this as an external replication target.
3. **Warrego-Darling/Toorale Western Floodplain**: event validation using DEA
   Water Observations, BoM/WaterNSW gauges, and published CEWH Flow-MER reports.
   The documented 2017-2019 dry sequence and 2019/2024 reconnection events
   provide interpretable low/high cases.
4. **Macquarie Marshes**: deliberate hard case using Flow-MER inundation maps,
   gauges, and depth loggers. Treat as a limitation test because emergent
   vegetation causes optical water classifiers to underestimate inundation.
5. **BoM Hydrologic Reference Stations**: select nearby high-quality,
   minimally regulated gauges for timing comparison where a mapped reach and a
   gauge represent comparable spatial processes.

Real-case comparisons evaluate timing agreement, rank correlation at plausible
lags, event direction, and failure modes. Gauge discharge is supporting
evidence, not assumed ground truth for spatial extent after flow ceases.

## 12. Literature grounding

- Tayer et al. (2026), *Mapping resilience: A framework for analysing
  surface-water dynamics and persistent pools in non-perennial rivers using
  remote sensing, rainfall and river discharge data*, Journal of Hydrology,
  DOI `10.1016/j.jhydrol.2025.134750`. Direct grounding for dynamic
  hydrological years and persistent-pool resilience.
- Tayer et al. (2023), *Ecohydrological metrics derived from multispectral
  images to characterize surface water in an intermittent river*, Journal of
  Hydrology, DOI `10.1016/j.jhydrol.2023.129087`.
- Tayer et al. (2023), *Identifying intermittent river sections with similar
  hydrology using remotely sensed metrics*, Journal of Hydrology, DOI
  `10.1016/j.jhydrol.2023.130266`.
- Mueller et al. (2016), *Water observations from space: Mapping surface water
  from 25 years of Landsat imagery across Australia*, Remote Sensing of
  Environment, DOI `10.1016/j.rse.2015.11.003`.
- Krause et al. (2021), *Mapping and Monitoring the Multi-Decadal Dynamics of
  Australia's Open Waterbodies using Landsat*, Remote Sensing, DOI
  `10.3390/rs13081437`.
- McJannet et al. (2014), *Persistence of in-stream waterholes in ephemeral
  rivers of tropical northern Australia and potential impacts of climate
  change*, Marine and Freshwater Research, 65, 1131-1144.
- Yu et al. (2022), *Water-level recession characteristics in isolated pools
  within non-perennial streams*, Advances in Water Resources, DOI
  `10.1016/j.advwatres.2022.104267`.
- NSW DCCEEW remote-sensing work on remnant-pool contraction and connectivity
  in the Barwon-Darling during the 2017-2019 drought.

## 13. Known limits and interpretation

- Surface extent is not water volume or depth.
- Extent-discharge relationships can be lagged, hysteretic, or absent after
  flow ceases.
- Optical classifiers under-detect narrow, shaded, turbid, or vegetated water.
- Monthly composites can miss short floods and short drying events.
- AOI definition changes percentages and persistence interpretation.
- Managed releases, barriers, and groundwater inputs can decouple local extent
  from basin rainfall or upstream discharge.
- A high trough means more observed surface extent than other troughs; it does
  not alone prove ecological resilience.
- Basin aggregation can hide asynchronous local refuge failure. Basin results
  must accompany, not replace, AOI results.

These limitations must appear in API documentation and user-facing reports.
