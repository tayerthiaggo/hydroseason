# HydroSeason Science, Rationale & Failure Summary

## 0. Project Aims & Rationale

* **Aim**: Robustly delineate hydrological wet/dry seasons and dynamic hydrological years (HY) from monthly rainfall time series across diverse climates.
* **Rationale**: Standard calendar years split wet seasons in half if they cross the calendar boundary (e.g., November–April in the Southern Hemisphere). Dynamically detecting seasonal boundaries ensures that rainfall metrics, trends, and drought indicators (such as SPI) are calculated on cohesive water-cycles rather than artificial calendar slices.
* **Core Challenge**: Handling interannual variability (ENSO, drought) and preventing isolated dry-season storms ("lonely months") from falsely triggering wet season classifications, particularly in arid or semi-arid zones.

---

## 1. Season & Hydrological Year (HY) Delineation Logic

```mermaid
graph TD
    A[Raw Rainfall] --> B[Regime Detection: ANOVA eta² / Circular R / Walsh-Lawler SI]
    B --> C{Regime Type?}
    C -->|non_seasonal| D[Unclassified / Fixed HY Fallback]
    C -->|borderline| E[Fixed Climatological Profile Mapping]
    C -->|seasonal| F{Method Selected?}
    F -->|heuristic| G[Heuristic Method]
    F -->|cumulative_anomaly| K[Cumulative Anomaly Method]
    
    G --> G1[1. Zero-Preserving 3-Month Centered Smooth]
    G1 --> G2[2. Dominant Wet Season Selection per Fixed HY]
    G2 --> G3[3. Tail Refinement: Hysteresis Contraction & Extension]
    G3 --> G4[4. Dynamic HY Assignment: Onset Shift at Wet Transitions]
    
    K --> K1[1. Compute reference floor: q = max(median, floor_cfg)]
    K1 --> K2[2. Compute monthly anomalies: Rain - q]
    K2 --> K3[3. Integrate cumulative anomaly curve within year]
    K3 --> K4[4. Onset at minimum; Demise at maximum]
```

### 1.1 Regime Detection
* **ANOVA $\eta^2$**: Fraction of total variance explained by calendar month. Robust to ENSO interannual scale shifts.
* **Circular $R$**: Resultant vector length of monthly climatology. Immune to interannual noise.
* **SI**: Walsh-Lawler Seasonality Index.
* **Decision**: `seasonal` if high $\eta^2$ or moderate $\eta^2$ confirmed by $R$ or $SI$.

### 1.2 Heuristic Segmentation
1. **Smoothing**: Zero-preserving 3-month rolling mean.
2. **Dominant Block**: Select single contiguous smoothed block per fixed HY with max sum of smoothed rain where value $\ge$ tail floor.
3. **Contraction**: Trim edges of dominant block where raw value < low floor.
4. **Extension**: Grow block edges backward/forward into Dry months where raw value $\ge$ high floor and STL residual is not an extreme storm outlier.
5. **Pruning**: Dissolve runs < `min_refined_run_length` (default 2) to Dry unless protected.
6. **Gap Repair**: Merge 1-month dry gaps between substantial wet runs ($\ge 2$ months).

### 1.3 Cumulative Anomaly Delineation (True Liebmann)
1. **Reference Floor**: Establish floor $q$ as `max(median_rainfall, reference_floor)`.
2. **Anomalies**: Calculate monthly anomalies $A_i = R_i - q$, optionally smoothed (3-month centered mean) or gated by STL residual.
3. **Cumulative Sum**:
   * **Hydrological Year Windowing**: Compute $C_n = \sum A_i$ independently per fixed hydrological year. Onset is the month after the global minimum of $C_n$; demise is the month of the global maximum.
   * **Continuous Multi-Year CUSUM (Peak-Picking)**: Compute $C_{full}$ globally across the whole multi-decade series. Detect significant demises (peaks) and onsets (troughs) using `scipy.signal.find_peaks` with a prominence filter of `min_net_gain`. Scans boundaries to handle edge-year start/end seasons.
4. **Conditional Delineation**:
   * **Unimodal**: Keeps only the single dominant contiguous wet block (highest anomaly sum) within the detected window.
   * **Bimodal**: Keeps all blocks inside the window and searches for secondary wet seasons outside.
* **Benefit**: Smooth, mathematically robust, eliminates year-start anchor boundary artifacts (under multi-year mode), and inherently filters out dry-season storms.

### 1.4 Dynamic HY Labeling
* `Hydro_Year` increments at Wet onset.
* Filtered by `onset_window_months` (default $\pm 1$ month around climatological anchor) to prevent off-season shifts.
* Recovers boundaries in long gaps ($\ge 16$ months) using fallback month or lowest-rain months.

---

## 2. Why "Lonely Months" (Dry-Season Rain) Leak into Wet Labels

Four main algorithmic root causes preserve single-month rain events inside the Dry season as "Wet" in the **Heuristic** method:

### Cause 1: "Only Wet Run" Protection Gating
* **Logic**: `refine_season_tails` protects a wet run from pruning if it is the only wet run in its fixed HY.
* **Failure**: If a severe drought completely zeroes out the actual wet season, a single heavy dry-season storm is selected as the dominant block. Since it is the only wet run, it cannot be pruned.

### Cause 2: Climatological Median Rain Protection
* **Logic**: A wet run is protected from pruning if its maximum raw rain $\ge$ `wet_clim_median`.
* **Failure**: High-intensity convective storms in the dry season easily exceed the climatological wet-season median, bypassing fragment pruning.

### Cause 3: Pruning Restricted by `require_low_floor_break_for_pruning`
* **Logic**: `require_low_floor_break_for_pruning=True` (default) permits pruning of short runs (<2 months) *only* if they were split from a larger block by a low-floor break (e.g., zero rain).
* **Failure**: Isolated dry-season rain runs that were never part of the dominant block did not touch a low-floor break, preventing their deletion.

### Cause 4: Rolling Climatology & Quantile Collapsing
* **Logic**: Tail floors scale dynamically via rolling windows.
* **Failure**: In dry/semi-arid regions, the 10th percentile positive rainfall (`secondpass_quantile`) collapses to low values (e.g., < 5mm). This extremely low high-threshold floor makes extension over-sensitive, expanding tiny showers.

---

## 3. Implemented Mitigations & Advanced Settings

1. **True Cumulative Anomaly (Implemented & Default for CA)**: Uses the fixed Liebmann mathematical definition ($onset = argmin + 1$, $demise = argmax$), preventing greedy block-picking storm leaks.
2. **Absolute Precipitation Floor (Implemented)**: Enforces `absolute_wet_floor` (default 10mm). Months below this limit are strictly `Dry`, preventing arid collapse artifacts.
3. **Continuous Multi-Year CUSUM (Implemented & Configurable)**: Runs peak-picking (`use_multi_year_cumsum=True`) via `scipy.signal.find_peaks` with prominence filtering, solving year-start boundary sensitivities.
4. **Hybrid Mode (Implemented)**: Uses Liebmann for the storm-robust seasonal envelope bounds, and Heuristic for fine-grained interior month classification.
5. **STL Residual Gate (Implemented)**: Clips anomalies during high-intensity dry-season convective storms.
6. **Disable `require_low_floor_break_for_pruning` (Configurable)**: Can be set to `False` to prune all sub-minimum heuristic runs unconditionally.

---

## 4. Alternative Optics (Design Candidates for Future Agents)

To refine classification and simplify complexity, other agents should consider the following math/domain perspectives:

### 4.1 Hidden Markov Models (HMM) [Computer Science / Stats]
* **Optic**: Frame season delineation as state transitions under hidden parameters.
* **Concept**: Two hidden states (Wet / Dry). Emissions are monthly rainfall modeled via a Gamma distribution (or Zero-Inflated Tweedie distribution to handle dry months).
* **Benefit**: Probabilistic, transition matrices model season persistence (avoids isolated storm jumps without manual pruning rules), and Viterbi algorithm handles optimal multi-decade sequence decoding.

### 4.2 Changepoint Detection (PELT / Ruptures) [Computer Science / Stats]
* **Optic**: Segment time series by identifying abrupt shifts in distribution properties.
* **Concept**: Apply PELT (Pruned Exact Linear Time) or Binary Segmentation to discover changes in mean/variance of rainfall. Wet seasons represent contiguous high-mean segments.
* **Benefit**: Non-parametric, avoids hand-crafted threshold tuning, and naturally bounds season segments globally.

### 4.3 Double-Logistic Phenology Curves [Biology / Ecology]
* **Optic**: Treat the cumulative anomaly curve like vegetation greenness growth curves.
* **Concept**: Fit double-logistic models (e.g., Beck's or Zhang's vegetation onset methods) to cumulative rainfall anomalies per cycle to isolate the start-of-season (SOS) and end-of-season (EOS) curvature inflection points.
* **Benefit**: Extremely smooth, noise-tolerant, and aligns perfectly with how natural ecosystems respond to rainfall.
