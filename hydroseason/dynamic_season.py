"""Steps 2-3 — Dynamic wet/dry segmentation and tail refinement.

Step 2: 3-month centred rolling mean (zero-preserving) → percentile threshold →
        dominant contiguous wet block per fixed hydro year.
Step 3: Hysteresis-based tail refinement on raw values (two thresholds).
"""

from __future__ import annotations

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
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

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

        # Run-length encoding of True runs
        idx = group.index.to_numpy()
        change = (sig != pd.Series(sig).shift(fill_value=False).to_numpy())
        run_starts = idx[change & sig]
        run_ends = idx[
            pd.Series(sig).shift(-1, fill_value=False).to_numpy() != sig
        ]
        run_ends = run_ends[(sig if len(run_ends) == len(sig) else sig[: len(run_ends)])]
        # Recompute robustly using a simple loop over local index — clearer and safe
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
# Step 3 — Hysteresis tail refinement
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
) -> pd.DataFrame:
    """Refine wet/dry tails using two-threshold hysteresis on raw values.

    For each contiguous Wet run, the operations are applied in this order:
      1. contract the start forward while raw value <= threshold_low
      2. contract the end backward while raw value <= threshold_low
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
    values = df[rainfall_col].to_numpy()
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

    def _eligible_for_extension(idx: int) -> bool:
        if values[idx] < effective_high:
            return False
        if residuals is not None and residual_limit is not None:
            residual = residuals[idx]
            if pd.notna(residual) and float(residual) > residual_limit:
                return False
        return True

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
        # 1) contract from start (drop leading low/zero months)
        while s <= e and values[s] <= threshold_low:
            seasons[s] = "Dry"
            s += 1
        # 2) contract from end (drop trailing low/zero months)
        while e >= s and values[e] <= threshold_low:
            seasons[e] = "Dry"
            e -= 1
        if s > e:
            # entire run dissolved by contraction; nothing left to extend from
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
