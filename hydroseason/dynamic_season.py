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
    threshold_high: float | None = None,
    threshold_low: float = 0.0,
    threshold: float | None = None,  # backwards-compat single threshold
) -> pd.DataFrame:
    """Refine wet/dry tails using two-threshold hysteresis on raw values.

    For each contiguous Wet run:
      - extend the start backward through preceding Dry months while raw value >= threshold_high
      - extend the end forward through following Dry months while raw value >= threshold_high
      - contract the start forward while raw value <= threshold_low
      - contract the end backward while raw value <= threshold_low

    A single ``threshold`` argument is accepted for backward compatibility and is
    used as both bounds (high = threshold, low = 0).
    """
    if threshold_high is None:
        threshold_high = float(threshold) if threshold is not None else 5.0
    if threshold is not None and threshold_low == 0.0:
        threshold_low = 0.0  # explicit: keep 0 for zero-extension behaviour

    df = df.copy().sort_values(date_col).reset_index(drop=True)
    seasons = df[season_type_col].to_numpy().copy()
    values = df[rainfall_col].to_numpy()
    n = len(df)

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
        # extend backward
        j = s - 1
        while j >= 0 and seasons[j] == "Dry" and values[j] >= threshold_high:
            seasons[j] = "Wet"
            j -= 1
        # extend forward
        k = e + 1
        while k < n and seasons[k] == "Dry" and values[k] >= threshold_high:
            seasons[k] = "Wet"
            k += 1
        # contract from start
        j = s
        while j <= e and values[j] <= threshold_low:
            seasons[j] = "Dry"
            j += 1
        # contract from end
        k = e
        while k >= s and values[k] <= threshold_low:
            seasons[k] = "Dry"
            k -= 1

    df[season_type_col] = seasons
    df["SeasonShift"] = df[season_type_col].ne(df[season_type_col].shift())
    return df
