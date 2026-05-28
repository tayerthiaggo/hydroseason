"""Season-level summary metrics per hydrological year."""

from __future__ import annotations

import pandas as pd


def compute_season_metrics(
    df: pd.DataFrame,
    *,
    value_col: str = "Rainfall_mm",
    hydro_year_col: str = "Hydro_Year",
    season_col: str = "SeasonType",
    nonzero_threshold: float = 1.0,
) -> pd.DataFrame:
    """Append per-hydro-year aggregates of the value column for Wet vs Dry seasons.

    Output columns (names prefixed with the value column when non-default):
      - <value>_dry_total, <value>_wet_total
      - dry_event_count (months > nonzero_threshold in dry season)
      - dry_month_count, wet_month_count
    """
    df = df.copy()
    suffix = "" if value_col == "Rainfall_mm" else f"_{value_col}"

    dry = df[df[season_col] == "Dry"]
    wet = df[df[season_col] == "Wet"]

    dry_event_counts = (
        dry[dry[value_col] > nonzero_threshold].groupby(hydro_year_col)[value_col].count()
    )
    dry_totals = dry.groupby(hydro_year_col)[value_col].sum().round(2)
    wet_totals = wet.groupby(hydro_year_col)[value_col].sum().round(2)

    df[f"dry_event_count{suffix}"] = (
        df[hydro_year_col].map(dry_event_counts).fillna(0).astype(int)
    )
    df[f"dry_total{suffix}"] = df[hydro_year_col].map(dry_totals).fillna(0)
    df[f"wet_total{suffix}"] = df[hydro_year_col].map(wet_totals).fillna(0)

    df["dry_month_count"] = (
        df[hydro_year_col].map(dry.groupby(hydro_year_col).size()).fillna(0).astype(int)
    )
    df["wet_month_count"] = (
        df[hydro_year_col].map(wet.groupby(hydro_year_col).size()).fillna(0).astype(int)
    )

    # Backwards-compat aliases for rainfall workflows
    if value_col == "Rainfall_mm":
        df["Dry_season_rain_count"] = df["dry_event_count"]
        df["Rain_dry_season_mm"] = df["dry_total"]
        df["Rain_wet_season_mm"] = df["wet_total"]
        df["Dry_month_count"] = df["dry_month_count"]

    return df


def compute_end_dry_metrics(
    df: pd.DataFrame,
    *,
    metric_cols: list[str] | tuple[str, ...],
    hydro_year_col: str = "Hydro_Year",
    season_col: str = "SeasonType",
    date_col: str = "Date",
    last_n: int = 2,
    anchor: str = "tail",
    anchor_col: str | None = None,
    suffix: str = "_endDry",
    min_periods: int = 1,
) -> pd.DataFrame:
    """Append end-of-dry-season state metrics for each hydrological year.

    For every hydrological year, this computes the mean of the requested
    ``metric_cols`` over a dry-season window and maps the result back to every
    row in that hydrological year using ``<metric>_endDry`` output columns.

    ``anchor="tail"`` averages the final ``last_n`` rows labelled Dry.
    ``anchor="terminal_minimum"`` first finds the driest terminal point by
    walking backward from the final Dry row while ``anchor_col`` is increasing
    (for example wetted area rebounding after the minimum). It then averages
    the ``last_n`` rows ending at that local minimum. This reproduces the
    Tayer et al. end-of-dry river-state metrics, where a final dry-labelled
    month can be excluded if wetted area has already rebounded.
    """
    if last_n <= 0:
        raise ValueError("last_n must be a positive integer.")
    if min_periods <= 0:
        raise ValueError("min_periods must be a positive integer.")

    if anchor not in {"tail", "terminal_minimum"}:
        raise ValueError("anchor must be either 'tail' or 'terminal_minimum'.")

    missing = [c for c in metric_cols if c not in df.columns]
    required = [hydro_year_col, season_col, date_col]
    missing += [c for c in required if c not in df.columns]
    if anchor == "terminal_minimum":
        if anchor_col is None:
            raise ValueError("anchor_col is required when anchor='terminal_minimum'.")
        if anchor_col not in df.columns:
            missing.append(anchor_col)
    if missing:
        raise KeyError(f"Missing required columns: {missing}")

    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    out = out.sort_values([hydro_year_col, date_col]).reset_index(drop=True)

    records: list[dict[str, float | int]] = []
    for hydro_year, group in out.groupby(hydro_year_col, sort=True):
        dry = group[group[season_col] == "Dry"].copy()
        if anchor == "terminal_minimum" and not dry.empty:
            values = pd.to_numeric(dry[anchor_col], errors="coerce").to_numpy()
            anchor_pos = len(dry) - 1
            while anchor_pos > 0 and values[anchor_pos] > values[anchor_pos - 1]:
                anchor_pos -= 1
            start = max(0, anchor_pos - last_n + 1)
            dry_tail = dry.iloc[start:anchor_pos + 1]
        else:
            dry_tail = dry.tail(last_n)
        record: dict[str, float | int] = {hydro_year_col: hydro_year}
        for col in metric_cols:
            out_col = f"{col}{suffix}"
            if len(dry_tail) >= min_periods:
                record[out_col] = float(pd.to_numeric(dry_tail[col], errors="coerce").mean())
            else:
                record[out_col] = float("nan")
        records.append(record)

    annual = pd.DataFrame(records).set_index(hydro_year_col)
    for col in annual.columns:
        out[col] = out[hydro_year_col].map(annual[col])
    return out


def compute_zero_flow_months(
    df: pd.DataFrame,
    *,
    discharge_col: str = "Discharge",
    hydro_year_col: str = "Hydro_Year",
    threshold: float = 1.0,
    out_col: str = "zero_flow_months_count",
) -> pd.DataFrame:
    """Append months per hydrological year with discharge at or below a threshold."""
    missing = [c for c in [discharge_col, hydro_year_col] if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")

    out = df.copy()
    counts = (
        out[pd.to_numeric(out[discharge_col], errors="coerce") <= threshold]
        .groupby(hydro_year_col)[discharge_col]
        .size()
    )
    out[out_col] = out[hydro_year_col].map(counts).fillna(0).astype(int)
    return out
