"""Steps 2-3 — Dynamic wet/dry segmentation and tail refinement.

Step 2: 3-month centred rolling mean (zero-preserving) → percentile threshold →
        dominant contiguous wet block per fixed hydro year.
Step 3: Hysteresis-based tail refinement on raw values (two thresholds).
"""

from __future__ import annotations

import math

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
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    if threshold_col is not None and threshold_col in df.columns:
        local_threshold = pd.to_numeric(df[threshold_col], errors="coerce").fillna(
            threshold
        )
        df["Significant"] = df[smoothed_col] >= local_threshold
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
    seasons = df[season_type_col].to_numpy().copy()
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
        fragment_keep = df[fragment_keep_col].fillna(False).astype(bool).to_numpy()
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
        if (
            min_refined_run_length is not None
            and (touches_low_floor_break or not require_low_floor_break_for_pruning)
            and not keep_fragment
            and (e - s + 1) < min_refined_run_length
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
