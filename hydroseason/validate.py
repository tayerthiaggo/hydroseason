"""Input validation and normalisation for monthly rainfall time series.

Expects monthly rainfall totals in mm. Sub-monthly inputs (e.g. daily gauge records)
are automatically aggregated to monthly totals by summing before any other checks.

Validates that the data are suitable for hydrological season delineation:
- Required columns present
- Rainfall values numeric and non-negative (mm)
- No duplicate (Year, Month) entries
- Strict monthly frequency (gaps detected and filled)
- Sufficient record length for STL / climatology

Returns a ValidationReport; the pipeline raises on errors, warns on issues.

Standardisation applied automatically (warnings emitted):
- Sub-monthly input (daily, etc.) → summed to monthly totals
- Year/Month as float or string → coerced to int
- Month out of 1-12 range → error
- Year outside plausible hydrological range → warning
- Value column with locale-formatted strings (e.g. "1,234.5") → stripped and coerced
- Date column already datetime dtype → used as-is (no re-parsing)
- Recoverable duplicate dates (same row, keep-last) → deduped with warning
- Missing months → filled by calendar-month climatological mean (WMO method)
- All-zero or constant value column → warning
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_MONTHS_FOR_STL = 24  # two full cycles for STL with period=12
_YEAR_MIN = 1000
_YEAR_MAX = 2200


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_rows_in: int = 0
    n_rows_out: int = 0
    n_imputed: int = 0
    n_unimputed: int = 0
    max_consecutive_missing: int = 0
    data_confidence: str = "high"
    fraction_missing: float = 0.0
    inferred_freq: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def _coerce_year_month(
    df: pd.DataFrame,
    year_col: str,
    month_col: str,
    report: ValidationReport,
) -> pd.DataFrame:
    """Coerce Year and Month columns to int, handling floats and strings."""
    for col, label in [(year_col, "Year"), (month_col, "Month")]:
        if col not in df.columns:
            continue
        if pd.api.types.is_float_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]):
            original = df[col].copy()
            df[col] = pd.to_numeric(df[col], errors="coerce")
            n_bad = int(df[col].isna().sum())
            if n_bad:
                report.errors.append(
                    f"{n_bad} non-numeric values in '{col}' column."
                )
                return df
            df[col] = df[col].astype(int)
            if not pd.api.types.is_integer_dtype(original):
                report.warnings.append(
                    f"'{col}' coerced from {original.dtype} to int."
                )
        elif not pd.api.types.is_integer_dtype(df[col]):
            df[col] = df[col].astype(int)
    return df


def _validate_year_month_ranges(
    df: pd.DataFrame,
    year_col: str,
    month_col: str,
    report: ValidationReport,
) -> bool:
    """Check Month is 1-12 and Year is plausible. Returns False on blocking error."""
    if month_col in df.columns:
        bad_months = df[month_col][~df[month_col].between(1, 12)]
        if len(bad_months):
            report.errors.append(
                f"{len(bad_months)} rows have Month values outside 1-12: "
                f"{sorted(bad_months.unique().tolist())}."
            )
            return False
    if year_col in df.columns:
        bad_years = df[year_col][~df[year_col].between(_YEAR_MIN, _YEAR_MAX)]
        if len(bad_years):
            report.warnings.append(
                f"{len(bad_years)} rows have Year values outside expected range "
                f"[{_YEAR_MIN}, {_YEAR_MAX}]: {sorted(bad_years.unique().tolist()[:5])}."
            )
    return True


def _coerce_value_column(
    df: pd.DataFrame,
    value_col: str,
    report: ValidationReport,
) -> pd.DataFrame:
    """Standardise value column: strip locale formatting (commas, whitespace), coerce to float."""
    if pd.api.types.is_object_dtype(df[value_col]):
        cleaned = df[value_col].astype(str).str.replace(",", "", regex=False).str.strip()
        df[value_col] = pd.to_numeric(cleaned, errors="coerce")
        report.warnings.append(
            f"Value column '{value_col}' was string-typed; stripped formatting and coerced to numeric."
        )
    else:
        df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    return df


def _ensure_date_column(
    df: pd.DataFrame,
    date_col: str,
    year_col: str,
    month_col: str,
    report: ValidationReport,
) -> pd.DataFrame:
    """Build a canonical datetime Date column.

    Priority:
    1. Year + Month integer columns (unambiguous regardless of locale date format).
    2. Existing Date column (parsed by pandas — ISO format recommended).
    3. If Date already has datetime dtype, use as-is.
    """
    if year_col in df.columns and month_col in df.columns:
        df[date_col] = pd.to_datetime(
            df[[year_col, month_col]].assign(day=1), errors="coerce"
        )
    elif date_col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[date_col]):
            pass  # already datetime, nothing to do
        else:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df


def _aggregate_to_monthly(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    report: ValidationReport,
) -> pd.DataFrame:
    """Detect sub-monthly (e.g. daily) input and aggregate to monthly rainfall totals.

    Only operates when a datetime ``date_col`` is present.  If the median number of
    rows per calendar month is already ≤ 1 the DataFrame is returned unchanged and
    any duplicate-date issues are left for the downstream duplicate check.
    """
    work = df.copy()
    if date_col not in work.columns:
        return work

    # Parse date column to datetime (best effort)
    if pd.api.types.is_datetime64_any_dtype(work[date_col]):
        date_series = work[date_col]
    else:
        date_series = pd.to_datetime(work[date_col], errors="coerce")
        if date_series.isna().mean() > 0.1:
            return work  # too many unparseable dates — let downstream report the error

    # Sub-monthly detection: median rows per calendar month > 1
    periods = date_series.dt.to_period("M")
    rows_per_period = periods.value_counts()
    if rows_per_period.median() <= 1.0:
        return work  # already monthly

    # Aggregate: sum rainfall per calendar month
    work = work.copy()
    work["_period"] = periods
    agg = work.groupby("_period", sort=True)[value_col].sum().reset_index()
    agg[date_col] = agg["_period"].dt.to_timestamp()
    agg = agg[[date_col, value_col]]

    n_in, n_out = len(work), len(agg)
    report.n_rows_in = n_in
    report.warnings.append(
        f"Sub-monthly input detected ({n_in} rows → {n_out} months). "
        f"Aggregated to monthly totals by summing rainfall (mm)."
    )
    return agg


def _impute_climatology_fill(
    work: pd.DataFrame,
    value_col: str,
    month_col: str,
    max_gap_months: int,
    max_consecutive_imputation_gap: int,
    report: ValidationReport,
) -> pd.DataFrame:
    """Fill missing months using the calendar-month climatological mean (WMO method).

    Each missing month is replaced by the mean of all observed values for that calendar
    month across the rest of the record.  This preserves the seasonal amplitude in the
    STL decomposition, unlike linear interpolation which biases peaks and troughs toward
    adjacent months.

    Falls back to linear interpolation only for calendar months that have no observed
    values at all (edge case requiring very large or structured gaps).

    Warns if any consecutive gap exceeds ``max_gap_months`` and refuses to
    impute when a gap exceeds ``max_consecutive_imputation_gap``.
    """
    missing_mask = work[value_col].isna()
    n_missing = int(missing_mask.sum())
    if "Imputed" not in work.columns:
        work["Imputed"] = False
    if n_missing == 0:
        return work

    # Warn about long consecutive gaps (fill still proceeds)
    groups = (missing_mask != missing_mask.shift()).cumsum()
    run_lengths = missing_mask.groupby(groups).transform("sum")
    max_consec = int(run_lengths[missing_mask].max())
    report.max_consecutive_missing = max_consec
    if max_consec > max_gap_months and max_consec > max_consecutive_imputation_gap:
        report.warnings.append(
            f"Longest consecutive gap is {max_consec} months "
            f"(>{max_gap_months}); auto-imputation blocked."
        )
    elif max_consec > max_gap_months:
        report.warnings.append(
            f"Longest consecutive gap is {max_consec} months "
            f"(>{max_gap_months}); climatology fill applied — verify data quality."
        )
    if max_consec > max_consecutive_imputation_gap:
        report.errors.append(
            f"Longest consecutive gap is {max_consec} months, exceeding "
            f"max_consecutive_imputation_gap={max_consecutive_imputation_gap}. "
            "Refusing to impute such a long gap. Reduce the threshold only if this is intentional."
        )
        report.n_unimputed = n_missing
        return work

    before = work[value_col].copy()

    # Step 1: calendar-month climatological mean (ignores NaN by default)
    clim = work.groupby(month_col)[value_col].mean()
    for idx in work.index[missing_mask]:
        m = work.at[idx, month_col]
        if m in clim.index and pd.notna(clim[m]):
            work.at[idx, value_col] = clim[m]

    # Step 2: linear interpolation as fallback for calendar months with no observations
    if work[value_col].isna().any():
        work[value_col] = work[value_col].interpolate(
            method="linear", limit_direction="both"
        )

    imputed_mask = before.isna() & work[value_col].notna()
    work.loc[imputed_mask, "Imputed"] = True
    n_imputed = int(imputed_mask.sum())
    report.n_imputed = n_imputed
    report.n_unimputed = int(work[value_col].isna().sum())
    report.warnings.append(
        f"Imputed {n_imputed} missing month(s) using calendar-month climatological mean "
        f"(WMO gap-fill method)."
    )
    return work


def validate_monthly_input(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    year_col: str = "Year",
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
    max_fraction_missing: float = 0.10,
    max_gap_to_interpolate: int = 2,
    max_consecutive_imputation_gap: int = 12,
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate and normalise a monthly rainfall DataFrame (values in mm).

    Standardises formats automatically before checking:
    - Sub-monthly input (e.g. daily) → aggregated to monthly totals by summing
    - Year/Month float or string → int
    - Value column locale strings (e.g. "1,234.5") → float
    - Date already datetime dtype → used as-is
    - Recoverable duplicate dates → deduplicated (keep last), warning issued
    - Missing months → filled by calendar-month climatological mean (WMO method);
            warns if any consecutive gap exceeds ``max_gap_to_interpolate`` months.
        - Very long missing runs are not auto-imputed when they exceed
            ``max_consecutive_imputation_gap`` months.

    Returns
    -------
    (df_clean, report)
        df_clean has a continuous monthly DatetimeIndex equivalent (Date + Year + Month
        columns, sorted, deduplicated, gap-filled).
        report.ok is False if any blocking issue was found; the caller must raise.
    """
    report = ValidationReport(n_rows_in=len(df))
    work = df.copy()

    # ---- presence of value column
    if value_col not in work.columns:
        available = ", ".join(map(str, work.columns)) or "(none)"
        report.errors.append(
            f"Missing value column: '{value_col}' (expected monthly rainfall in mm). "
            f"Available columns: {available}. "
            f"Pass value_col=... if your rainfall column has a different name."
        )
        return work, report

    # ---- aggregate sub-monthly input to monthly totals
    work = _aggregate_to_monthly(work, date_col, value_col, report)

    # ---- standardise Year / Month to int (float/string → int)
    work = _coerce_year_month(work, year_col, month_col, report)
    if not report.ok:
        return work, report

    # ---- validate Month 1-12 and Year plausibility
    if not _validate_year_month_ranges(work, year_col, month_col, report):
        return work, report

    # ---- standardise value column (locale strings, floats, etc.)
    work = _coerce_value_column(work, value_col, report)
    if work[value_col].isna().all():
        report.errors.append(f"Value column '{value_col}' is not numeric.")
        return work, report

    # ---- date column construction / coercion
    work = _ensure_date_column(work, date_col, year_col, month_col, report)
    if date_col not in work.columns:
        report.errors.append(
            f"Need either '{date_col}' or both '{year_col}' and '{month_col}' columns."
        )
        return work, report
    if work[date_col].isna().any():
        n_bad = int(work[date_col].isna().sum())
        report.errors.append(f"{n_bad} rows have unparseable dates in '{date_col}'.")
        return work, report

    # ---- sort before duplicate check
    work = work.sort_values(date_col).reset_index(drop=True)

    # ---- normalise to first-of-month (before duplicate check so we catch intra-month dupes)
    work[date_col] = work[date_col].values.astype("datetime64[M]").astype("datetime64[ns]")

    # ---- duplicate check — try to recover by keeping last occurrence
    n_dup = int(work.duplicated(subset=[date_col]).sum())
    if n_dup:
        # Check whether the duplicates are identical rows (safe to drop) or conflicting values
        n_full_dup = int(work.duplicated(subset=[date_col, value_col]).sum())
        if n_full_dup == n_dup:
            # Exact duplicates — silently drop
            work = work.drop_duplicates(subset=[date_col], keep="last").reset_index(drop=True)
            report.warnings.append(
                f"Dropped {n_dup} exact duplicate row(s)."
            )
        else:
            # Conflicting values for same date — cannot resolve automatically
            dup_dates = (
                work.loc[work.duplicated(subset=[date_col], keep=False), date_col]
                .dt.strftime("%Y-%m")
                .unique()
            )
            examples = ", ".join(dup_dates[:5])
            more = " ..." if len(dup_dates) > 5 else ""
            report.errors.append(
                f"{n_dup} duplicate dates with differing values in '{date_col}' "
                f"(e.g. {examples}{more}). "
                "Deduplicate the input before calling the pipeline."
            )
            return work, report

    # ---- frequency check via reindex to monthly start
    full_idx = pd.date_range(work[date_col].iloc[0], work[date_col].iloc[-1], freq="MS")
    if len(full_idx) != len(work):
        report.inferred_freq = "irregular"
        n_missing = len(full_idx) - len(work)
        report.warnings.append(
            f"{n_missing} months missing between {full_idx[0].date()} and {full_idx[-1].date()}; "
            f"reindexing to monthly frequency."
        )
        work = (
            work.set_index(date_col)
            .reindex(full_idx)
            .rename_axis(date_col)
            .reset_index()
        )
    else:
        report.inferred_freq = "MS"

    # ---- regenerate Year / Month columns from canonical date
    work[year_col] = work[date_col].dt.year.astype(int)
    work[month_col] = work[date_col].dt.month.astype(int)

    # ---- fill missing months (climatological mean, WMO method)
    if "Imputed" not in work.columns:
        work["Imputed"] = False

    n_missing = int(work[value_col].isna().sum())
    if n_missing:
        report.fraction_missing = n_missing / len(work)
        if report.fraction_missing > max_fraction_missing:
            report.errors.append(
                f"{n_missing} / {len(work)} months missing ({report.fraction_missing:.1%}) "
                f"exceeds max_fraction_missing={max_fraction_missing:.0%}."
            )
            return work, report
        work = _impute_climatology_fill(
            work,
            value_col,
            month_col,
            max_gap_to_interpolate,
            max_consecutive_imputation_gap,
            report,
        )
        if not report.ok:
            return work, report
        remaining = int(work[value_col].isna().sum())
        if remaining:
            report.errors.append(
                f"{remaining} months still missing after climatology fill "
                f"(calendar month has no observed values to average)."
            )
            return work, report

    # ---- non-negative check (rainfall must be ≥ 0 mm)
    if (work[value_col] < 0).any():
        n_neg = int((work[value_col] < 0).sum())
        report.warnings.append(
            f"{n_neg} negative values in '{value_col}'; clipped to 0.0 (rainfall must be non-negative)."
        )
        work[value_col] = work[value_col].clip(lower=0.0)

    # ---- constant / all-zero check (warning only — seasonality analysis will be degenerate)
    if work[value_col].nunique() <= 1:
        report.warnings.append(
            f"Value column '{value_col}' is constant ({work[value_col].iloc[0]}); "
            "seasonality index will be meaningless."
        )

    # ---- length
    if len(work) < MIN_MONTHS_FOR_STL:
        report.errors.append(
            f"Need at least {MIN_MONTHS_FOR_STL} months for seasonality analysis; got {len(work)}."
        )
        return work, report

    # ---- 12-month coverage
    months_present = set(work[month_col].unique().tolist())
    missing_calendar_months = sorted(set(range(1, 13)) - months_present)
    if missing_calendar_months:
        report.warnings.append(
            f"Calendar months not represented in data: {missing_calendar_months}; "
            "climatology will be biased."
        )

    if report.fraction_missing == 0.0:
        report.data_confidence = "high"
    elif report.max_consecutive_missing >= 6 or report.fraction_missing >= 0.08:
        report.data_confidence = "low"
    else:
        report.data_confidence = "medium"

    report.n_rows_out = len(work)
    return work, report


def apply_report(report: ValidationReport, *, raise_on_error: bool = True) -> None:
    """Log warnings and optionally raise on errors."""
    for w in report.warnings:
        logger.warning(w)
    if report.errors and raise_on_error:
        raise ValueError("Input validation failed: " + "; ".join(report.errors))


def validate_daily(
    df: pd.DataFrame,
    *,
    date_col: str = "Date",
    year_col: str = "Year",
    month_col: str = "Month",
    value_col: str = "Rainfall_mm",
    max_fraction_missing: float = 0.10,
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate and normalise a daily rainfall DataFrame (values in mm).

    Validates that the data is suitable for daily hydrological stress analysis:
    - Required columns present
    - Rainfall values numeric and non-negative (mm)
    - No duplicate dates
    - Strict daily frequency (gaps detected and filled with NaN)
    - Sufficient record length (at least 365 days)
    """
    report = ValidationReport(n_rows_in=len(df))
    work = df.copy()

    # ---- presence of value column
    if value_col not in work.columns:
        available = ", ".join(map(str, work.columns)) or "(none)"
        report.errors.append(
            f"Missing value column: '{value_col}' (expected daily rainfall in mm). "
            f"Available columns: {available}. "
            f"Pass value_col=... if your rainfall column has a different name."
        )
        return work, report

    # ---- standardise Year / Month to int (if present)
    work = _coerce_year_month(work, year_col, month_col, report)
    if not report.ok:
        return work, report

    # ---- standardise value column (locale strings, floats, etc.)
    work = _coerce_value_column(work, value_col, report)
    if work[value_col].isna().all():
        report.errors.append(f"Value column '{value_col}' is not numeric.")
        return work, report

    # ---- date column construction / coercion
    if date_col in work.columns:
        if pd.api.types.is_datetime64_any_dtype(work[date_col]):
            pass
        else:
            work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    elif year_col in work.columns and month_col in work.columns and "day" in work.columns:
        work[date_col] = pd.to_datetime(
            work[[year_col, month_col, "day"]], errors="coerce"
        )
    else:
        report.errors.append(
            f"Need either '{date_col}' or '{year_col}', '{month_col}', and 'day' columns."
        )
        return work, report

    if work[date_col].isna().any():
        n_bad = int(work[date_col].isna().sum())
        report.errors.append(f"{n_bad} rows have unparseable dates in '{date_col}'.")
        return work, report

    # ---- sort before duplicate check
    work = work.sort_values(date_col).reset_index(drop=True)

    # ---- duplicate check — try to recover by keeping last occurrence
    n_dup = int(work.duplicated(subset=[date_col]).sum())
    if n_dup:
        n_full_dup = int(work.duplicated(subset=[date_col, value_col]).sum())
        if n_full_dup == n_dup:
            work = work.drop_duplicates(subset=[date_col], keep="last").reset_index(drop=True)
            report.warnings.append(
                f"Dropped {n_dup} exact duplicate daily row(s)."
            )
        else:
            dup_dates = (
                work.loc[work.duplicated(subset=[date_col], keep=False), date_col]
                .dt.strftime("%Y-%m-%d")
                .unique()
            )
            examples = ", ".join(dup_dates[:5])
            more = " ..." if len(dup_dates) > 5 else ""
            report.errors.append(
                f"{n_dup} duplicate dates with differing values in '{date_col}' "
                f"(e.g. {examples}{more})."
            )
            return work, report

    # ---- frequency check via reindex to daily frequency
    full_idx = pd.date_range(work[date_col].iloc[0], work[date_col].iloc[-1], freq="D")
    if len(full_idx) != len(work):
        report.inferred_freq = "irregular"
        n_missing = len(full_idx) - len(work)
        report.warnings.append(
            f"{n_missing} days missing between {full_idx[0].date()} and {full_idx[-1].date()}; "
            f"reindexing to daily frequency."
        )
        work = (
            work.set_index(date_col)
            .reindex(full_idx)
            .rename_axis(date_col)
            .reset_index()
        )
    else:
        report.inferred_freq = "D"

    # ---- regenerate Year / Month columns from canonical date
    work[year_col] = work[date_col].dt.year.astype(int)
    work[month_col] = work[date_col].dt.month.astype(int)

    n_missing = int(work[value_col].isna().sum())
    if n_missing:
        report.fraction_missing = n_missing / len(work)
        if report.fraction_missing > max_fraction_missing:
            report.errors.append(
                f"{n_missing} / {len(work)} days missing ({report.fraction_missing:.1%}) "
                f"exceeds max_fraction_missing={max_fraction_missing:.0%}."
            )
            return work, report

    # ---- non-negative check
    if (work[value_col] < 0).any():
        n_neg = int((work[value_col] < 0).sum())
        report.warnings.append(
            f"{n_neg} negative values in '{value_col}'; clipped to 0.0."
        )
        work[value_col] = work[value_col].clip(lower=0.0)

    # ---- length check
    if len(work) < 365:
        report.errors.append(
            f"Need at least 365 days of data; got {len(work)}."
        )
        return work, report

    if report.fraction_missing == 0.0:
        report.data_confidence = "high"
    elif report.fraction_missing >= 0.08:
        report.data_confidence = "low"
    else:
        report.data_confidence = "medium"

    report.n_rows_out = len(work)
    return work, report

