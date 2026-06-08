# HydroSeason Science & Failure Summary

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

### 1.3 Cumulative Anomaly Segmentation (Liebmann Method)
1. **Reference Floor**: Establish floor $q$ as `max(median_rainfall, reference_floor)`.
2. **Anomalies**: Calculate monthly anomalies $A_i = R_i - q$.
3. **Cumulative Sum**: Compute $C_n = \sum_{i=1}^n A_i$ for each hydrological year.
4. **Wet Season Bounds**:
   * **Onset**: Month following the global minimum of $C_n$ (where anomalies turn positive).
   * **Demise**: Month of the global maximum of $C_n$ (where positive anomalies peak).
* **Benefit**: Smooth, mathematically rigorous, no arbitrary hysteresis thresholds, inherently rejects isolated dry-season storms.

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

## 3. Potential Mitigation Vectors

1. **Use Cumulative Anomaly (Recommended)**: Use the Liebmann method to dynamically segment seasons, avoiding threshold-based heuristic tail refinement altogether.
2. **Tighten Pruning Gating**: Disable or lower the priority of the "only wet run" protection if the absolute rainfall volume is below a threshold.
3. **Disable `require_low_floor_break_for_pruning`**: Set this config parameter to `False` to prune all sub-minimum runs unconditionally.
4. **Absolute Minimum Floor**: Impose an absolute precipitation floor (e.g., 10mm or 15mm) below which a month can never be classified as Wet, regardless of quantiles.
5. **Adaptive Smoothers**: Tighter rolling windows to prevent single-month pulses from smearing into multiple months.

