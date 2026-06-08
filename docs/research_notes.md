# HydroSeason Segmentation — Deep Audit & Improvement Menu

## 0. Root Problem Summary

Neither method works well on Australia 50-site test. Key issues:

| Problem | Heuristic | Liebmann (current impl) |
|---|---|---|
| Lonely months (dry-season storms → Wet) | ✗ Yes | ✗ Partial — block-selection not true Liebmann |
| Arid collapse (quantiles → near-zero) | ✗ Yes | ✓ Handled by `reference_floor` |
| Over-extension via smoothing bleed | ✗ Yes | ✓ No smoothing |
| **Current impl NOT true Liebmann** | N/A | ✗ Critical bug |

---

## 1. Critical Bug: Current `segment_by_cumulative_anomaly` is Not Liebmann

**True Liebmann (Bombardi & Carvalho 2009, Stern & Coe 1982):**
```
C(n) = Σ [R(i) - q]   from t₀ → t_end
Onset  = month after argmin(C)    ← curve turns upward
Demise = month of argmax(C)       ← curve turns downward
```

**Current impl does:**
- Finds positive months where `R(i) > q`
- Groups them into contiguous blocks
- Picks block with max anomaly sum
- ≡ a **greedy block-picker**, not cumulative integral

**Bug consequence:** No inherent rejection of isolated storm bursts. A single 150mm burst in May creates a large-sum block that wins the selection.

### Fix: True Liebmann per year
```python
# Within each hydro year group:
anomalies = rain - q           # shape (n,)
C = np.cumsum(anomalies)       # cumulative from year start
onset_pos  = np.argmin(C)      # last point before upturn
demise_pos = np.argmax(C)      # last point of sustained upturn
if demise_pos > onset_pos:
    wet_indices = range(onset_pos + 1, demise_pos + 1)
```

**User's downturn intuition is exactly right** — the cumulative sum's upward phase (min → max) is the wet season. Isolated storms cause *local* bumps in C but not the global min→max envelope. The key insight: an isolated storm adds a spike then C immediately falls back — `argmax` stays at the true seasonal peak.

---

## 2. Ranked Menu of Improvements

### 2A. Fix True Liebmann (HIGH IMPACT, LOW EFFORT)
Fix the `segment_by_cumulative_anomaly` to use actual cumulative integral with `argmin → argmax` detection.

**Expected benefit:** Automatically rejects isolated dry-season storms because they create a local bump, but the global max of C remains at the true wet season peak.

**Risk:** Cross-year C(n) scope matters. Compute C within each `Hydro_Year_fixed` window starting from a dry-season anchor month (e.g., climatological onset - 3 months).

### 2B. Smoothed Liebmann (MEDIUM IMPACT, LOW EFFORT)
Apply mild smoothing to C(n) before argmin/argmax to suppress noise from interannual variability. Literature uses 41-day (≈ 1.3-month) centered rolling mean. At monthly scale → 3-month smoother on anomalies before cumsum.

```python
smoothed_anomalies = pd.Series(anomalies).rolling(3, center=True, min_periods=1).mean()
C = np.cumsum(smoothed_anomalies)
```

### 2C. Ensemble Consensus (HIGH IMPACT, MEDIUM EFFORT)
Run both methods, take **intersection** or **majority-vote** per month-year.

**Option C1 — Intersection (conservative):**
Month = Wet only if BOTH methods say Wet. Very good at rejecting lonely months. May be too conservative for sparse wet seasons.

**Option C2 — Weighted Union:**
Month = Wet if `w_h * is_wet_h + w_c * is_wet_c >= 0.5`. Start with `w_h=0.4, w_c=0.6`.

**Option C3 — Liebmann gate + Heuristic expansion:**
Liebmann defines the "hard window" [onset, demise]. Heuristic segmentation runs ONLY inside that window. Heuristic tail-refinement cannot escape Liebmann bounds.

> This is probably the best hybrid: Liebmann provides storm-robust hard boundaries, heuristic provides fine-grained month classification inside those bounds.

### 2D. STL Residual Gate on Liebmann (MEDIUM IMPACT, MEDIUM EFFORT)
We already have STL residuals in the pipeline. Before computing anomalies:
- Subtract seasonal component → work on de-seasoned residuals
- Months where residual is an extreme outlier (e.g., > 3σ) → cap rain at clim median before computing anomaly
- Prevents single anomalous months from shifting C(n) peak

### 2E. Multi-year Cumulative (MEDIUM IMPACT, LOW EFFORT)
Current: compute C(n) independently per hydro year → sensitive to year-start choice.

Better: compute C(n) on **whole series** (like original Liebmann on daily data), then find all local minima that precede a rise of ≥ X mm above local minimum. Each such onset-demise pair = one wet season.

Risk: requires smarter peak-picking across the full-series cumsum. Scipy `find_peaks` with `prominence` parameter handles this.

### 2F. Absolute Precipitation Floor Guard (LOW EFFORT, HIGH BASELINE)
Already known fix: months with `R < abs_floor` (e.g., 10mm) → never Wet, regardless of method.
Both methods should respect this. Trivial to add as post-processing gate.

### 2G. Climatological Onset Window Constraint (MEDIUM EFFORT)
Liebmann can produce "onset" in a wrong month if the year was anomalously dry. Constrain: if computed onset deviates > N months from site's long-run mean onset, use the climatological onset as a fallback.

---

## 3. Proposed Optimal Architecture (Two-Stage)

```
Stage 1 — Hard Boundary (True Liebmann on smoothed anomalies):
  - Scope: whole series, find seasonal onset/demise per year
  - Output: [onset_month, demise_month] for each HY
  - Constraints: bounded by climatological window ± 2 months
  - Absolute floor: R < 10mm → never Wet

Stage 2 — Fine Classification (Heuristic inside Liebmann window):
  - Run heuristic segmentation but only on months within [onset, demise]
  - Shoulder extension CANNOT cross onset-1 or demise+1
  - Pruning still removes sub-minimum runs within window
  - Result: nuanced month classification that respects hard boundary
```

**Why this is better:**
- Liebmann alone: too coarse, treats entire onset→demise as Wet even if some interior months are clearly dry
- Heuristic alone: no hard boundary, bleeds outside true season
- Two-stage: Liebmann sets storm-robust bounds, heuristic does fine-grained interior work

---

## 4. Implementation Priority

| Priority | Action | Files |
|---|---|---|
| 🔴 P0 | Fix `segment_by_cumulative_anomaly` → true argmin/argmax Liebmann | `dynamic_season.py:510` |
| 🔴 P0 | Add absolute floor post-gate to both methods | `dynamic_season.py`, `pipeline.py` |
| 🟡 P1 | Implement ensemble C3 (Liebmann bounds + heuristic interior) | `dynamic_season.py`, `pipeline.py` |
| 🟡 P1 | Smoothed anomalies before cumsum (3-month) | `dynamic_season.py:510` |
| 🟢 P2 | Multi-year cumulative with scipy peak-picking | `dynamic_season.py` |
| 🟢 P2 | STL residual gate on anomaly computation | `dynamic_season.py`, `pipeline.py` |

---

## 5. Quick Win Code Sketch — True Liebmann Fix

```python
# Replace block-selection logic with true cumulative anomaly
for hy, group in df.groupby(hydro_year_col, sort=False):
    idx = group.index.to_numpy()
    rain = group[value_col].to_numpy(dtype=float)
    
    # Apply absolute floor: clamp months < floor to zero contribution
    rain_gated = np.where(rain < abs_floor, 0.0, rain)
    
    # Optionally smooth anomalies to suppress noise
    anomalies = rain_gated - q
    smooth_anom = pd.Series(anomalies).rolling(3, center=True, min_periods=1).mean().to_numpy()
    
    C = np.cumsum(smooth_anom)
    
    onset_pos = int(np.argmin(C))
    demise_pos = int(np.argmax(C))
    
    if demise_pos > onset_pos and (C[demise_pos] - C[onset_pos]) > min_net_gain:
        # Mark months onset_pos+1 through demise_pos as Wet
        for i in range(onset_pos + 1, demise_pos + 1):
            season.loc[idx[i]] = "Wet"
```

`min_net_gain` = e.g., `q * 2` — prevents labeling wet when cumsum barely moves.

---

## 6. References

- Liebmann & Marengo (2001) — original anomalous accumulation onset/demise definition
- Bombardi & Carvalho (2009) — Liebmann applied to SAMS, demise = argmax of C
- Stern & Coe (1982) — probabilistic rainfall onset (pentad-based)
- CUSUM / PELT changepoint literature — for P2 multi-year peak picking
