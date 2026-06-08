"""Steps 2-3 — Dynamic wet/dry segmentation and tail refinement.

Step 2: 3-month centred rolling mean (zero-preserving) → percentile threshold →
        dominant contiguous wet block per fixed hydro year.
Step 3: Hysteresis-based tail refinement on raw values (two thresholds).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Step 2a — Smoothing
# ---------------------------------------------------------------------------
def harmonize_with_zero_preservation(
    df: pd.DataFrame,
    *,
    value_col: str = "Rainfall_mm",
    window: int = 3,
    out_col: str = "Smoothed",
) -> pd.DataFrame:
    """Centred rolling mean that preserves runs of zeros (vectorised)."""
    df = df.copy()
    smoothed = df[value_col].rolling(window=window, min_periods=1, center=True).mean()

    values = df[value_col]
    prev_zero = values.shift(1).eq(0)
    next_zero = values.shift(-1).eq(0)
    is_zero = values.eq(0)
    keep_zero = is_zero & (prev_zero | next_zero)
    df[out_col] = smoothed.where(~keep_zero, 0.0)
    return df


# ---------------------------------------------------------------------------
# Step 2b — Dominant wet block per fixed hydro year (vectorised write-back)
# ---------------------------------------------------------------------------
def segment_main_wet_season_fixed_threshold(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    hydro_year_col: str = "Hydro_Year_fixed",
    smoothed_col: str = "Smoothed",
    threshold: float = 10.0,
    threshold_col: str | None = None,
    value_col: str | None = "Rainfall_mm",
    baseline_wet_col: str | None = "_BaselineWetMonth",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    if threshold_col is not None and threshold_col in df.columns:
        local_threshold = pd.to_numeric(df[threshold_col], errors="coerce").fillna(
            threshold
        )
        if (
            value_col is not None
            and value_col in df.columns
            and baseline_wet_col is not None
            and baseline_wet_col in df.columns
        ):
            df["Significant"] = (df[smoothed_col] >= local_threshold) | (
                (df[value_col] >= local_threshold)
                & df[baseline_wet_col].fillna(False).astype(bool)
            )
        else:
            df["Significant"] = df[smoothed_col] >= local_threshold
    else:
        if (
            value_col is not None
            and value_col in df.columns
            and baseline_wet_col is not None
            and baseline_wet_col in df.columns
        ):
            df["Significant"] = (df[smoothed_col] >= threshold) | (
                (df[value_col] >= threshold)
                & df[baseline_wet_col].fillna(False).astype(bool)
            )
        else:
            df["Significant"] = df[smoothed_col] >= threshold

    season = pd.Series("Dry", index=df.index, dtype=object)
    boundaries: list[dict] = []

    # Per fixed hydro year, find the contiguous Significant block with the largest
    # cumulative smoothed sum.
    for hy, group in df.groupby(hydro_year_col, sort=False):
        sig = group["Significant"].to_numpy()
        if not sig.any():
            boundaries.append({"Hydro_Year": hy, "WetStart": None, "WetEnd": None})
            continue

        idx = group.index.to_numpy()
        runs: list[tuple[int, int]] = []
        in_run = False
        run_start = None
        for i, flag in zip(idx, sig):
            if flag and not in_run:
                run_start = int(i)
                in_run = True
            elif not flag and in_run:
                runs.append((run_start, int(i) - 1))
                in_run = False
        if in_run:
            runs.append((run_start, int(idx[-1])))

        # Pick the run with maximum smoothed sum
        best = max(runs, key=lambda r: df.loc[r[0]: r[1], smoothed_col].sum())
        season.loc[best[0]: best[1]] = "Wet"
        wet_start = df.loc[best[0], date_col]
        wet_end = df.loc[best[1], date_col]
        boundaries.append(
            {
                "Hydro_Year": hy,
                "WetStart": wet_start,
                "WetEnd": wet_end,
                "wet_duration_months": int(
                    (wet_end.year - wet_start.year) * 12 + wet_end.month - wet_start.month + 1
                ),
            }
        )

    df["SeasonType"] = season.values
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())
    bounds_df = pd.DataFrame(boundaries)
    for col in ("WetStart", "WetEnd"):
        if col in bounds_df.columns:
            bounds_df[col] = pd.to_datetime(bounds_df[col]).dt.date
    return df, bounds_df


# ---------------------------------------------------------------------------
def refine_season_tails(
    df: pd.DataFrame,
    *,
    rainfall_col: str = "Rainfall_mm",
    season_type_col: str = "SeasonType",
    date_col: str = "Date",
    hydro_year_col: str | None = "Hydro_Year_fixed",
    threshold_high: float | None = None,
    threshold_low: float = 0.0,
    threshold: float | None = None,  # backwards-compat single threshold
    min_core_length: int = 3,
    climatology_floor: float | None = None,
    residual_col: str | None = None,
    residual_threshold: float | None = None,
    per_row_threshold_col: str | None = None,
    extension_threshold_col: str | None = None,
    fragment_keep_col: str | None = None,
    enforce_low_floor_inside_runs: bool = False,
    min_refined_run_length: int | None = None,
    require_low_floor_break_for_pruning: bool = True,
    wet_clim_median: float | None = None,
    hydro_year_start_month: int | None = None,
) -> pd.DataFrame:
    """Refine wet/dry tails using two-threshold hysteresis on raw values.

    For each contiguous Wet run, the operations are applied in this order:
      1. contract the start forward while raw value is below the low floor
         (``threshold_low=0`` keeps legacy exact-zero contraction)
      2. contract the end backward while raw value is below the low floor
      3. extend the (contracted) start backward through preceding Dry months
         while raw value >= threshold_high
      4. extend the (contracted) end forward through following Dry months
         while raw value >= threshold_high

    Rationale (regression fix):
    Contracting **before** extending guarantees that a low/zero month sitting at
    the edge of the dominant wet block (often introduced by the 3-month centred
    smoother) cannot be both dropped from the wet season *and* used as a bridge
    to a sporadic rainfall event in the following dry months. Doing it the other
    way round produced isolated single-month "wet" islands surrounded by dry
    months (e.g. May 1995, 1997, 2012) — a rain event inside the dry season
    must not re-open the wet season.

    Shoulder portability (cross-regime fix):
    ``hydro_year_col`` used to be an absolute wall to prevent adjacent wet
    seasons merging. Replaced with a wet-run-length gate (``min_core_length``):
    a run may cross a fixed-hydro-year boundary only if its current core length
    is at least ``min_core_length``. Orphan single-month events therefore still
    cannot snowball across a boundary, but a real wet core (e.g. Nov-Mar) can
    absorb a genuine October shoulder that sits in the previous fixed-HY. This
    works symmetrically at the recession tail and for both unimodal and bimodal
    regimes (no climatological-anchor assumption).

    ``climatology_floor`` is an optional additive magnitude gate. When provided,
    a candidate shoulder month is only absorbed if its raw value also exceeds
    this site-scaled floor (typically ``alpha * median(wet-month climatology)``).
    This prevents the global ``threshold_high`` from being trivially passed in
    very arid regimes where non-zero rainfall quantiles collapse to a few mm.

    ``residual_col`` + ``residual_threshold`` add an optional STL-residual
    gate: a candidate shoulder month with an extreme positive residual is
    treated as a storm anomaly rather than seasonal shoulder rainfall.

    ``per_row_threshold_col`` can provide row-specific low floors for
    contraction and extension; NaN values fall back to scalar thresholds.
    ``extension_threshold_col`` is stricter and applies only to extension, so
    climatological shoulder gates do not chop real wet cores.
    ``enforce_low_floor_inside_runs`` treats below-floor Wet months as breaks
    before runs are refined; ``min_refined_run_length`` can then dissolve tiny
    fragments left behind by smoothing bleed. ``fragment_keep_col`` can mark
    rows that are allowed to survive this fragment-pruning step, typically
    climatological Wet months in a weak but real wet season.

    A single ``threshold`` argument is accepted for backward compatibility and is
    used as both bounds (high = threshold, low = 0).
    """
    if threshold_high is None:
        threshold_high = float(threshold) if threshold is not None else 5.0
    if threshold is not None and threshold_low == 0.0:
        threshold_low = 0.0  # explicit: keep 0 for zero-extension behaviour

    effective_high = threshold_high
    if climatology_floor is not None and climatology_floor > effective_high:
        effective_high = float(climatology_floor)

    df = df.copy().sort_values(date_col).reset_index(drop=True)
    seasons = df[season_type_col].to_numpy(dtype=object, copy=True)
    values = pd.to_numeric(df[rainfall_col], errors="coerce").to_numpy(dtype=float)
    n = len(df)

    if hydro_year_col is not None and hydro_year_col in df.columns:
        hy = df[hydro_year_col].to_numpy()
    else:
        hy = None

    if (
        residual_col is not None
        and residual_col in df.columns
        and residual_threshold is not None
    ):
        residuals = pd.to_numeric(df[residual_col], errors="coerce").to_numpy()
        residual_limit = float(residual_threshold)
    else:
        residuals = None
        residual_limit = None

    if per_row_threshold_col is not None and per_row_threshold_col in df.columns:
        per_row_floors = pd.to_numeric(df[per_row_threshold_col], errors="coerce").to_numpy()
    else:
        per_row_floors = None

    if extension_threshold_col is not None and extension_threshold_col in df.columns:
        extension_floors = pd.to_numeric(df[extension_threshold_col], errors="coerce").to_numpy()
    else:
        extension_floors = None

    if fragment_keep_col is not None and fragment_keep_col in df.columns:
        fragment_keep = (
            df[fragment_keep_col]
            .astype("boolean")
            .fillna(False)
            .to_numpy(dtype=bool)
        )
    else:
        fragment_keep = None

    def _finite_floor(floors, idx: int, fallback: float) -> float:
        if floors is not None:
            raw = floors[idx]
            if pd.notna(raw):
                value = float(raw)
                if math.isfinite(value):
                    return value
        return float(fallback)

    def _below_low_floor(value: float, floor: float) -> bool:
        if pd.isna(value):
            return False
        if floor <= 0.0:
            return value <= floor
        return value < floor

    def _eligible_for_extension(idx: int) -> bool:
        if pd.isna(values[idx]):
            return False
        gate = float(effective_high)
        if extension_floors is not None:
            gate = max(gate, _finite_floor(extension_floors, idx, gate))
        elif per_row_floors is not None:
            gate = max(gate, _finite_floor(per_row_floors, idx, gate))
        if values[idx] < gate:
            return False
        if residuals is not None and residual_limit is not None:
            residual = residuals[idx]
            if pd.notna(residual) and float(residual) > residual_limit:
                return False
        return True

    low_floor_breaks = [False] * n
    if enforce_low_floor_inside_runs:
        for i in range(n):
            if seasons[i] == "Wet":
                lo = _finite_floor(per_row_floors, i, threshold_low)
                if _below_low_floor(values[i], lo):
                    seasons[i] = "Dry"
                    low_floor_breaks[i] = True

    # Reconstruct wet_clim_median if not passed
    if wet_clim_median is None and fragment_keep_col is not None and fragment_keep_col in df.columns:
        is_wet_month = df[fragment_keep_col].fillna(False).astype(bool)
        if is_wet_month.any():
            m_col = "Month" if "Month" in df.columns else None
            if m_col:
                monthly_medians = df[is_wet_month].groupby(m_col)[rainfall_col].median()
                wet_clim_median = float(monthly_medians.median())

    clim_medians = None
    if "_ClimatologicalMedian" in df.columns:
        clim_medians = df["_ClimatologicalMedian"].to_numpy()

    # identify wet runs
    runs: list[list[int]] = []
    in_run = False
    start = None
    for i in range(n):
        if seasons[i] == "Wet" and not in_run:
            start = i
            in_run = True
        elif seasons[i] != "Wet" and in_run:
            runs.append([start, i - 1])
            in_run = False
    if in_run:
        runs.append([start, n - 1])

    # Count runs per fixed hydro year before pruning
    hy_run_counts = {}
    if hy is not None:
        for r_start, r_end in runs:
            r_hy = hy[r_start]
            hy_run_counts[r_hy] = hy_run_counts.get(r_hy, 0) + 1

    for run in runs:
        s, e = run
        # 1) contract from start (drop leading months below the per-row or scalar floor)
        while s <= e:
            lo = _finite_floor(per_row_floors, s, threshold_low)
            if _below_low_floor(values[s], lo):
                seasons[s] = "Dry"
                s += 1
            else:
                break
        # 2) contract from end (drop trailing months below the per-row or scalar floor)
        while e >= s:
            lo = _finite_floor(per_row_floors, e, threshold_low)
            if _below_low_floor(values[e], lo):
                seasons[e] = "Dry"
                e -= 1
            else:
                break
        if s > e:
            # entire run dissolved by contraction; nothing left to extend from
            continue
        touches_low_floor_break = (
            (s > 0 and low_floor_breaks[s - 1])
            or (e + 1 < n and low_floor_breaks[e + 1])
        )
        keep_fragment = (
            fragment_keep is not None
            and bool(fragment_keep[s:e + 1].any())
        )

        run_length = e - s + 1

        # Check if this is the ONLY wet run in its fixed hydro year
        is_only_run = False
        if hy is not None:
            r_hy = hy[s]
            if hy_run_counts.get(r_hy, 0) == 1:
                is_only_run = True
                keep_fragment = True

        # If it is NOT the only wet run, and has length 1, ignore keep_fragment (prune it if another wet run exists)
        if not is_only_run and run_length == 1 and hy is not None:
            same_hy = (hy == hy[s])
            other_wet_count = np.sum((seasons == "Wet") & same_hy) - run_length
            if other_wet_count > 0:
                keep_fragment = False

            # Protect if the run starts at the hydro year start month (it might be bridged via dry gap)
            if keep_fragment is False and hydro_year_start_month is not None and "Month" in df.columns:
                run_month = int(df.loc[s, "Month"])
                if run_month == int(hydro_year_start_month):
                    keep_fragment = True

        # Protect any run that has a raw rainfall value >= wet_clim_median
        if wet_clim_median is not None and wet_clim_median > 0:
            max_run_rain = np.max(values[s:e + 1])
            if max_run_rain >= wet_clim_median:
                keep_fragment = True

        # Protect baseline wet months only if raw rainfall meets climatological median
        if keep_fragment:
            if clim_medians is not None:
                max_run_rain = np.max(values[s:e + 1])
                run_medians = clim_medians[s:e + 1]
                if max_run_rain < np.min(run_medians):
                    keep_fragment = False
            elif wet_clim_median is not None and wet_clim_median > 0:
                max_run_rain = np.max(values[s:e + 1])
                if max_run_rain < wet_clim_median:
                    keep_fragment = False

        if (
            min_refined_run_length is not None
            and (touches_low_floor_break or not require_low_floor_break_for_pruning)
            and not keep_fragment
            and run_length < min_refined_run_length
        ):
            seasons[s:e + 1] = "Dry"
            continue
        # 3) extend backward from contracted start
        j = s - 1
        while j >= 0 and seasons[j] == "Dry" and _eligible_for_extension(j):
            if hy is not None and hy[j] != hy[s] and (e - s + 1) < min_core_length:
                break
            seasons[j] = "Wet"
            j -= 1
        # 4) extend forward from contracted end
        k = e + 1
        while k < n and seasons[k] == "Dry" and _eligible_for_extension(k):
            if hy is not None and hy[k] != hy[e] and (e - s + 1) < min_core_length:
                break
            seasons[k] = "Wet"
            k += 1

    df[season_type_col] = seasons
    df["SeasonShift"] = df[season_type_col].ne(df[season_type_col].shift())
    return df


def repair_short_dry_gaps(
    df: pd.DataFrame,
    *,
    season_type_col: str = "SeasonType",
    date_col: str = "Date",
    month_col: str = "Month",
    max_gap_length: int = 1,
    min_neighbor_wet_length: int = 3,
    hydro_year_start_month: int | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Merge tiny Dry interruptions inside otherwise continuous Wet periods.

    A one-month Dry label between two substantial Wet runs is usually a local
    trough, not a representative dry season. This post-refinement repair keeps
    real dry seasons intact by requiring Wet runs on both sides and limiting the
    repaired gap length.
    """
    if max_gap_length <= 0:
        out = df.copy()
        return out, {
            "short_dry_gap_merged_count": 0,
            "short_dry_gap_merged_month_count": 0,
        }

    out = df.copy().sort_values(date_col).reset_index(drop=True)
    seasons = out[season_type_col].to_numpy(dtype=object, copy=True)

    runs: list[tuple[str, int, int]] = []
    start = 0
    for i in range(1, len(seasons) + 1):
        if i == len(seasons) or seasons[i] != seasons[start]:
            runs.append((str(seasons[start]), start, i - 1))
            start = i

    merged_count = 0
    merged_months = 0
    for pos, (label, start, end) in enumerate(runs):
        if label != "Dry" or pos == 0 or pos == len(runs) - 1:
            continue
        gap_length = end - start + 1
        if gap_length > int(max_gap_length):
            continue
        prev_label, prev_start, prev_end = runs[pos - 1]
        next_label, next_start, next_end = runs[pos + 1]
        prev_length = prev_end - prev_start + 1
        next_length = next_end - next_start + 1
        
        prev_is_start = False
        if hydro_year_start_month is not None and month_col in out.columns:
            prev_month = int(out.loc[prev_start, month_col])
            prev_is_start = (prev_month == int(hydro_year_start_month))

        if (
            prev_label == "Wet"
            and next_label == "Wet"
            and (
                (prev_length >= int(min_neighbor_wet_length) or prev_is_start)
                and next_length >= int(min_neighbor_wet_length)
            )
        ):
            seasons[start : end + 1] = "Wet"
            merged_count += 1
            merged_months += gap_length

    out[season_type_col] = seasons
    out["SeasonShift"] = out[season_type_col].ne(out[season_type_col].shift())
    return out, {
        "short_dry_gap_merged_count": int(merged_count),
        "short_dry_gap_merged_month_count": int(merged_months),
    }


def segment_by_cumulative_anomaly(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    hydro_year_col: str = "Hydro_Year_fixed",
    value_col: str = "Rainfall_mm",
    is_bimodal: bool = False,
    reference_floor: float = 10.0,
    absolute_wet_floor: float = 10.0,
    smooth_anomalies: bool = True,
    smooth_window: int = 3,
    min_net_gain: float | None = None,
    use_stl_residual_gate: bool = False,
    use_multi_year_cumsum: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Segment Wet/Dry seasons using true Liebmann cumulative anomaly method.

    Implements the canonical Liebmann & Marengo (2001) / Bombardi & Carvalho
    (2009) definition:
      - Onset  = month following argmin(C)   [cumsum turns upward]
      - Demise = month of argmax(C)          [cumsum peaks before decline]

    where C(n) = Σ [R(i) - q] integrated over each hydrological year.

    This correctly rejects isolated dry-season storms: a single anomalous burst
    creates only a local spike in C, but the *global* argmax remains anchored
    at the true seasonal peak. The block-selection approach used previously was
    not true Liebmann and did not have this property.

    Parameters
    ----------
    df : DataFrame
        Monthly rainfall table.
    reference_floor : float
        Minimum value for the reference q = max(median, reference_floor).
        Prevents collapse to near-zero in arid regions.
    absolute_wet_floor : float
        Hard pre-gate: months with R < absolute_wet_floor contribute zero
        positive anomaly. They cannot be classified Wet regardless of cumsum.
    smooth_anomalies : bool
        If True, apply a centred rolling mean to anomalies before cumsum
        to suppress interannual noise (41-day equivalent at monthly scale).
    smooth_window : int
        Window for anomaly smoothing (default 3 months).
    min_net_gain : float | None
        Minimum required rise in C (argmax - argmin) to label any Wet months.
        If None, defaults to q (one month's reference amount).
    use_stl_residual_gate : bool
        If True, cap extreme outliers in rainfall (residual > 3 sigma) to monthly
        climatological medians before anomaly computation.
    use_multi_year_cumsum : bool
        If True, compute cumulative sum continuously across years instead of resetting.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)
    df[value_col] = df[value_col].astype(float)

    # Compute reference level q from observed data only
    observed_mask = (
        ~df["Imputed"].fillna(False).astype(bool)
        if "Imputed" in df.columns
        else pd.Series(True, index=df.index)
    )
    observed_rain = df.loc[observed_mask, value_col]
    q = max(
        float(observed_rain.median()) if len(observed_rain) > 0 else float(df[value_col].median()),
        float(reference_floor),
    )

    if min_net_gain is None:
        min_net_gain = q  # must accumulate at least one reference month's worth

    # --- STL residual gate: cap extreme rainfall outliers ---
    if use_stl_residual_gate:
        from .seasonality import get_stl_fit
        fit = get_stl_fit(df, date_col, value_col)
        if fit is not None:
            resid = fit.resid.to_numpy()
            std_resid = np.nanstd(resid)
            if std_resid > 0:
                limit = 3.0 * std_resid
                if "_ClimatologicalMedian" in df.columns:
                    clim_medians = df["_ClimatologicalMedian"].to_numpy()
                else:
                    clim_medians = df.groupby(df[date_col].dt.month)[value_col].transform("median").to_numpy()
                
                outlier_mask = resid > limit
                df.loc[outlier_mask, value_col] = np.minimum(df.loc[outlier_mask, value_col], clim_medians[outlier_mask])

    rain_full = df[value_col].to_numpy(dtype=float)
    rain_gated_full = np.where(rain_full < absolute_wet_floor, 0.0, rain_full)
    anomalies_full = rain_gated_full - q

    if smooth_anomalies and len(df) >= smooth_window:
        anomalies_full = (
            pd.Series(anomalies_full)
            .rolling(smooth_window, center=True, min_periods=1)
            .mean()
            .to_numpy()
        )

    C_full = np.cumsum(anomalies_full) if use_multi_year_cumsum else None

    season = pd.Series("Dry", index=df.index, dtype=object)
    boundaries = []

    for hy, group in df.groupby(hydro_year_col, sort=False):
        idx = group.index.to_numpy()
        rain = group[value_col].to_numpy(dtype=float)
        n = len(idx)
        if n == 0:
            boundaries.append({"Hydro_Year": hy, "WetStart": None, "WetEnd": None, "wet_duration_months": 0})
            continue

        rain_gated = rain_gated_full[idx]
        anomalies = anomalies_full[idx]

        # --- True Liebmann: cumulative sum ---
        if use_multi_year_cumsum:
            C = C_full[idx]
        else:
            C = np.cumsum(anomalies)

        # --- Find onset (after global min) and demise (global max) ---
        onset_pos = int(np.argmin(C))
        demise_pos = int(np.argmax(C))

        net_gain = C[demise_pos] - C[onset_pos]

        if demise_pos > onset_pos and net_gain >= min_net_gain:
            # Candidate indices are within the wet slice (onset_pos + 1 to demise_pos)
            # and must satisfy the absolute floor constraint
            candidate_idx_in_group = [
                i for i in range(onset_pos + 1, demise_pos + 1)
                if rain[i] >= absolute_wet_floor
            ]
            
            if candidate_idx_in_group:
                # Group candidate indices into contiguous blocks
                blocks = []
                current_block = [candidate_idx_in_group[0]]
                for idx_val in candidate_idx_in_group[1:]:
                    if idx_val == current_block[-1] + 1:
                        current_block.append(idx_val)
                    else:
                        blocks.append(current_block)
                        current_block = [idx_val]
                blocks.append(current_block)
                
                # Calculate anomaly sums for each block
                block_sums = []
                for block in blocks:
                    block_anom = float(np.sum(rain[block] - q))
                    block_sums.append((block_anom, block))
                
                # Sort blocks by anomaly sum descending
                block_sums.sort(key=lambda x: x[0], reverse=True)
                
                selected_blocks = []
                if is_bimodal:
                    # Keep all blocks with positive anomaly sums inside the window
                    selected_blocks = [block for anom, block in block_sums if anom > 0]
                    # If nothing is positive, keep the top one
                    if not selected_blocks and block_sums:
                        selected_blocks.append(block_sums[0][1])
                else:
                    # Keep only the single dominant block
                    if block_sums:
                        selected_blocks.append(block_sums[0][1])
                
                # Label selected blocks as Wet
                for block in selected_blocks:
                    for i in block:
                        season.loc[idx[i]] = "Wet"
                
                # Define boundaries based on the actual labeled Wet months
                # within this hydro year (if any were labeled Wet)
                hy_wet_indices = [idx[i] for block in selected_blocks for i in block]
                if hy_wet_indices:
                    # Sort globally to find start and end
                    hy_wet_indices.sort()
                    wet_start = pd.Timestamp(df.loc[hy_wet_indices[0], date_col])
                    wet_end = pd.Timestamp(df.loc[hy_wet_indices[-1], date_col])
                    duration = int(
                        (wet_end.year - wet_start.year) * 12
                        + wet_end.month - wet_start.month + 1
                    )
                    
                    if is_bimodal:
                        # Find secondary wet season outside the primary window
                        secondary = _find_secondary_liebmann(
                            rain, rain_gated, q, idx, onset_pos, demise_pos,
                            n, min_net_gain, absolute_wet_floor, group, date_col, season
                        )
                        boundaries.append({
                            "Hydro_Year": hy,
                            "WetStart": wet_start.date(),
                            "WetEnd": wet_end.date(),
                            "wet_duration_months": duration,
                            "secondary_wet_start": secondary.get("start"),
                            "secondary_wet_end": secondary.get("end"),
                        })
                    else:
                        boundaries.append({
                            "Hydro_Year": hy,
                            "WetStart": wet_start.date(),
                            "WetEnd": wet_end.date(),
                            "wet_duration_months": duration,
                        })
                else:
                    boundaries.append({
                        "Hydro_Year": hy,
                        "WetStart": None,
                        "WetEnd": None,
                        "wet_duration_months": 0,
                    })
            else:
                boundaries.append({
                    "Hydro_Year": hy,
                    "WetStart": None,
                    "WetEnd": None,
                    "wet_duration_months": 0,
                })
        else:
            boundaries.append({
                "Hydro_Year": hy,
                "WetStart": None,
                "WetEnd": None,
                "wet_duration_months": 0,
            })

    df["SeasonType"] = season.values
    df["SeasonShift"] = df["SeasonType"].ne(df["SeasonType"].shift())
    bounds_df = pd.DataFrame(boundaries)
    return df, bounds_df


def _find_secondary_liebmann(
    rain: np.ndarray,
    rain_gated: np.ndarray,
    q: float,
    idx: np.ndarray,
    onset_pos: int,
    demise_pos: int,
    n: int,
    min_net_gain: float,
    absolute_wet_floor: float,
    group: pd.DataFrame,
    date_col: str,
    season: pd.Series,
) -> dict:
    """Find a secondary wet season for bimodal sites outside the primary window."""
    # Build index set of residual months (outside primary wet window)
    primary = set(range(onset_pos + 1, demise_pos + 1))
    residual_idx = [i for i in range(n) if i not in primary]
    if len(residual_idx) < 2:
        return {}

    res_rain = rain_gated[residual_idx]
    res_anom = res_rain - q
    C_res = np.cumsum(res_anom)

    res_onset = int(np.argmin(C_res))
    res_demise = int(np.argmax(C_res))
    net = C_res[res_demise] - C_res[res_onset]

    if res_demise > res_onset and net >= min_net_gain:
        for k in range(res_onset + 1, res_demise + 1):
            gi = residual_idx[k]
            if rain[gi] >= absolute_wet_floor:
                season.loc[idx[gi]] = "Wet"
        return {
            "start": group.iloc[residual_idx[res_onset + 1]][date_col].date()
            if hasattr(group.iloc[residual_idx[res_onset + 1]][date_col], "date")
            else None,
            "end": group.iloc[residual_idx[res_demise]][date_col].date()
            if hasattr(group.iloc[residual_idx[res_demise]][date_col], "date")
            else None,
        }
    return {}

