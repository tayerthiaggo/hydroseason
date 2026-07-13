"""Local rainfall data readers.

Supported formats
-----------------
- **SILO point data** (any fixed format: Standard, Rain Only, Monthly, P51, FAO56, …)
  Space-separated, with a descriptive metadata header where every line starts
  with ``"`` or ``!``.  Daily inputs are automatically aggregated to monthly
  totals; monthly-summary files are returned as-is.
- **SILO custom CSV** (comma-separated, no metadata header; variables chosen by
  the user at export time from longpaddock.qld.gov.au).
- **Bureau of Meteorology (BoM) monthly station CSV** — product code
  ``IDCJAC0001``.  Comma-separated with columns: ``Product code``,
  ``Station number``, ``Year``, ``Month``,
  ``Monthly Precipitation Total (millimetres)``, ``Quality``.

All readers return a tidy DataFrame with at least:

    Date (datetime64[ns], first of month), Year (int), Month (int), Rainfall_mm (float)

ready for :func:`~hydroseason.validate.validate_monthly_input`.
"""

from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_silo(
    path: str | Path,
    *,
    variable: str = "Rain",
    output_col: str = "Rainfall_mm",
    resolution: str = "monthly",
) -> pd.DataFrame:
    """Read a SILO point dataset and return a tidy rainfall DataFrame.

    Handles all SILO fixed formats (Standard, Rain Only, Monthly, P51, FAO56,
    …) as well as SILO custom CSV exports.

    Parameters
    ----------
    path:
        Path to the SILO file.
    variable:
        SILO column name to extract.  Default ``"Rain"`` (daily or monthly
        rainfall in mm).  This is the correct value for all fixed formats and
        for custom CSV exports that include rainfall.
    output_col:
        Name given to the rainfall column in the returned DataFrame.  Default
        ``"Rainfall_mm"`` so the result is directly usable by
        :func:`~hydroseason.validate.validate_monthly_input`.
    resolution:
        Target resolution: ``"monthly"`` or ``"daily"`` or ``"auto"``.

    Returns
    -------
    pd.DataFrame
        Columns: ``Date`` (datetime64[ns]), ``Year`` (int),
        ``Month`` (int), *output_col* (float). Daily inputs
        are summed to monthly totals if resolution is ``"monthly"``.

    Examples
    --------
    >>> df = read_silo("040004.txt")
    >>> from hydroseason import validate_monthly_input
    >>> clean, report = validate_monthly_input(df)
    """
    path = Path(path)

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    # Detect SILO fixed format: any of the first 30 lines starts with " or !
    has_silo_header = any(
        line.strip().startswith(('"', "!")) for line in lines[:30]
    )

    if has_silo_header:
        df = _read_silo_fixed(lines, variable)
    else:
        df = _read_silo_csv(path, variable)

    return _normalise_silo_df(df, variable, output_col, resolution=resolution)


def read_bom_monthly(
    path: str | Path,
    *,
    value_col: str | None = None,
    output_col: str = "Rainfall_mm",
    quality_filter: bool = True,
) -> pd.DataFrame:
    """Read a Bureau of Meteorology monthly rainfall CSV (product IDCJAC0001).

    The standard BoM monthly CSV contains the columns::

        Product code, Station number, Year, Month,
        Monthly Precipitation Total (millimetres), Quality

    Missing months appear as absent rows (not zeros).  The returned DataFrame
    contains only the months present in the file; gaps are filled by
    :func:`~hydroseason.validate.validate_monthly_input` using climatological
    infilling.

    Parameters
    ----------
    path:
        Path to the BoM IDCJAC0001 CSV file.
    value_col:
        Override rainfall column name detection.  By default the function
        searches for a column containing ``"precipitation"`` or ``"rainfall"``
        (case-insensitive).
    output_col:
        Name given to the rainfall column in the returned DataFrame.  Default
        ``"Rainfall_mm"``.
    quality_filter:
        When ``True`` (default) rows where ``Quality`` is not ``"Y"`` are
        dropped with a warning.  Pass ``False`` to retain all rows.

    Returns
    -------
    pd.DataFrame
        Columns: ``Date`` (datetime64[ns], first of month), ``Year`` (int),
        ``Month`` (int), *output_col* (float, monthly mm).

    Examples
    --------
    >>> df = read_bom_monthly("IDCJAC0001_003018_Data1.csv")
    >>> from hydroseason import validate_monthly_input
    >>> clean, report = validate_monthly_input(df)
    """
    path = Path(path)
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    # ------------------------------------------------------------------
    # Detect rainfall column
    # ------------------------------------------------------------------
    if value_col is not None:
        if value_col not in df.columns:
            raise ValueError(
                f"Specified value_col '{value_col}' not found. "
                f"Columns: {list(df.columns)}"
            )
        rain_col = value_col
    else:
        candidates = [
            c for c in df.columns
            if "precipitation" in c.lower() or "rainfall" in c.lower()
        ]
        if not candidates:
            raise ValueError(
                "Could not auto-detect the rainfall column. "
                f"Columns found: {list(df.columns)}. "
                "Pass value_col='...' to specify it explicitly."
            )
        rain_col = candidates[0]
        logger.info("BoM reader: using column '%s' as rainfall.", rain_col)

    # ------------------------------------------------------------------
    # Quality filter
    # ------------------------------------------------------------------
    quality_col = next(
        (c for c in df.columns if c.lower() == "quality"), None
    )
    if quality_filter and quality_col:
        n_before = len(df)
        df = df[df[quality_col].str.strip() == "Y"].copy()
        n_dropped = n_before - len(df)
        if n_dropped:
            logger.warning(
                "BoM reader: dropped %d row(s) with Quality != 'Y'. "
                "Pass quality_filter=False to retain them.",
                n_dropped,
            )

    # ------------------------------------------------------------------
    # Coerce Year / Month
    # ------------------------------------------------------------------
    for col in ("Year", "Month"):
        if col not in df.columns:
            raise ValueError(
                f"BoM CSV missing expected column '{col}'. "
                f"Columns found: {list(df.columns)}"
            )
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    n_before = len(df)
    df = df.dropna(subset=["Year", "Month"])
    if len(df) < n_before:
        logger.warning(
            "BoM reader: dropped %d row(s) with missing Year/Month.",
            n_before - len(df),
        )

    df["Year"] = df["Year"].astype(int)
    df["Month"] = df["Month"].astype(int)

    # ------------------------------------------------------------------
    # Rainfall value
    # ------------------------------------------------------------------
    df[rain_col] = pd.to_numeric(df[rain_col], errors="coerce")

    # ------------------------------------------------------------------
    # Build Date + final columns
    # ------------------------------------------------------------------
    df["Date"] = pd.to_datetime(
        df[["Year", "Month"]].assign(day=1), errors="coerce"
    )
    df = df.rename(columns={rain_col: output_col})
    df = (
        df[["Date", "Year", "Month", output_col]]
        .sort_values("Date")
        .reset_index(drop=True)
    )

    logger.info(
        "BoM reader: loaded %d monthly records from %s.", len(df), path.name
    )
    return df


def read_rainfall(
    path: str | Path,
    *,
    source: str = "auto",
    value_col: str = "Rainfall_mm",
    silo_variable: str = "Rain",
    bom_value_col: str | None = None,
    bom_quality_filter: bool = True,
    resolution: str = "monthly",
    **read_csv_kwargs,
) -> pd.DataFrame:
    """Read rainfall data from common sources with one entry point.

    Parameters
    ----------
    path:
        Input file path.
    source:
        One of ``"auto"``, ``"silo"``, ``"bom"``, ``"csv"``.
        ``"auto"`` detects BoM/SILO using file content and falls back to
        ``pandas.read_csv`` for other sources.
    value_col:
        Canonical rainfall column name expected by the pipeline.
    silo_variable:
        SILO variable to extract (default ``"Rain"``).
    bom_value_col:
        Optional explicit BoM rainfall column override.
    bom_quality_filter:
        When reading BoM, keep only rows with ``Quality == "Y"`` by default.
    resolution:
        Target resolution: ``"monthly"``, ``"daily"``, or ``"auto"``.
    **read_csv_kwargs:
        Forwarded to ``pandas.read_csv`` when using generic CSV mode.
    """
    path = Path(path)
    source_norm = source.lower().strip()

    if source_norm not in {"auto", "silo", "bom", "csv"}:
        raise ValueError(
            "source must be one of {'auto', 'silo', 'bom', 'csv'}."
        )

    if source_norm == "silo":
        if resolution == "auto":
            df = read_silo(path, variable=silo_variable, output_col=value_col, resolution="daily")
            if len(df) > 1 and df["Date"].diff().dropna().median() <= pd.Timedelta(days=1):
                return df
            resolution = "monthly"
        return read_silo(path, variable=silo_variable, output_col=value_col, resolution=resolution)

    if source_norm == "bom":
        return read_bom_monthly(
            path,
            value_col=bom_value_col,
            output_col=value_col,
            quality_filter=bom_quality_filter,
        )

    if source_norm == "csv":
        df = pd.read_csv(path, **read_csv_kwargs)
        df = _normalise_generic_csv(df, value_col=value_col)
        if resolution == "monthly" and len(df) > 1 and df["Date"].diff().dropna().median() <= pd.Timedelta(days=1):
            periods = df["Date"].dt.to_period("M")
            df["_period"] = periods
            agg = df.groupby("_period", sort=True)[value_col].sum().reset_index()
            agg["Date"] = agg["_period"].dt.to_timestamp()
            df = agg[["Date", value_col]].copy()
            df["Year"] = df["Date"].dt.year.astype(int)
            df["Month"] = df["Date"].dt.month.astype(int)
            df = df[["Date", "Year", "Month", value_col]].sort_values("Date").reset_index(drop=True)
        return df

    # auto detect: BoM has an explicit product code / monthly precipitation column.
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        head = [fh.readline() for _ in range(30)]
    head_joined = "\n".join(head)

    if "IDCJAC0001" in head_joined or "Monthly Precipitation Total" in head_joined:
        logger.info("read_rainfall(auto): detected BoM monthly format.")
        return read_bom_monthly(
            path,
            value_col=bom_value_col,
            output_col=value_col,
            quality_filter=bom_quality_filter,
        )

    if any(line.strip().startswith(('"', "!")) for line in head if line):
        logger.info("read_rainfall(auto): detected SILO fixed format.")
        if resolution == "auto":
            df = read_silo(path, variable=silo_variable, output_col=value_col, resolution="daily")
            if len(df) > 1 and df["Date"].diff().dropna().median() <= pd.Timedelta(days=1):
                return df
            resolution = "monthly"
        return read_silo(path, variable=silo_variable, output_col=value_col, resolution=resolution)

    logger.info("read_rainfall(auto): falling back to pandas.read_csv.")
    df = pd.read_csv(path, **read_csv_kwargs)
    df = _normalise_generic_csv(df, value_col=value_col)
    if resolution == "monthly" and len(df) > 1 and df["Date"].diff().dropna().median() <= pd.Timedelta(days=1):
        periods = df["Date"].dt.to_period("M")
        df["_period"] = periods
        agg = df.groupby("_period", sort=True)[value_col].sum().reset_index()
        agg["Date"] = agg["_period"].dt.to_timestamp()
        df = agg[["Date", value_col]].copy()
        df["Year"] = df["Date"].dt.year.astype(int)
        df["Month"] = df["Date"].dt.month.astype(int)
        df = df[["Date", "Year", "Month", value_col]].sort_values("Date").reset_index(drop=True)
    return df


def _normalise_generic_csv(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    df = df.copy()
    
    date_cols = [c for c in df.columns if str(c).lower() in {"date", "timestamp", "time", "dt"}]
    year_cols = [c for c in df.columns if str(c).lower() == "year"]
    month_cols = [c for c in df.columns if str(c).lower() == "month"]
    
    if date_cols:
        date_col = date_cols[0]
        # try parsing. If integers (like 20100101), converting to string first helps
        if pd.api.types.is_numeric_dtype(df[date_col]):
            df["Date"] = pd.to_datetime(df[date_col].astype(str), errors="coerce")
        else:
            df["Date"] = pd.to_datetime(df[date_col], errors="coerce")
    elif year_cols and month_cols:
        y_col = year_cols[0]
        m_col = month_cols[0]
        df["Date"] = pd.to_datetime(
            pd.DataFrame({
                "year": df[y_col].astype(int),
                "month": df[m_col].astype(int),
                "day": 1
            }),
            errors="coerce"
        )
    else:
        first_col = df.columns[0]
        df["Date"] = pd.to_datetime(df[first_col].astype(str), errors="coerce")
        
    df["Year"] = df["Date"].dt.year
    df["Month"] = df["Date"].dt.month
    
    if value_col not in df.columns:
        exact_ci = [c for c in df.columns if str(c).lower() == value_col.lower()]
        if exact_ci:
            df = df.rename(columns={exact_ci[0]: value_col})
        else:
            exact_rain_names = {
                "rain",
                "rain_mm",
                "rainfall",
                "rainfall_mm",
                "precip",
                "precip_mm",
                "precipitation",
                "ppt",
                "pr",
                "val",
                "value",
                "q",
            }
            rain_tokens = ("rain", "rainfall", "precip", "precipitation", "ppt")
            protected_names = {"date", "year", "month", "timestamp", "time", "dt"}

            def _normalised_name(col) -> str:
                return str(col).strip().lower().replace(" ", "_")

            matched_cols = [
                c for c in df.columns
                if (
                    _normalised_name(c) in exact_rain_names
                    or any(token in _normalised_name(c) for token in rain_tokens)
                )
            ]
            candidate_cols = [
                c for c in matched_cols
                if _normalised_name(c) not in protected_names
            ]
            
            if candidate_cols:
                df = df.rename(columns={candidate_cols[0]: value_col})
            else:
                other_cols = [
                    c for c in df.columns
                    if str(c) not in {"Date", "Year", "Month"}
                    and _normalised_name(c) not in protected_names
                ]
                if other_cols:
                    df = df.rename(columns={other_cols[0]: value_col})
                    
    if value_col in df.columns:
        df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
        
    keep_cols = ["Date", "Year", "Month"]
    if value_col in df.columns:
        keep_cols.append(value_col)
    
    df = df[keep_cols].dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    df["Year"] = df["Year"].astype(int)
    df["Month"] = df["Month"].astype(int)
    return df


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_silo_fixed(lines: list[str], variable: str) -> pd.DataFrame:
    """Parse a SILO fixed (space-separated) file with a ``"`` / ``!`` header."""
    # Collect non-header, non-empty lines in order
    non_header = [
        line for line in lines
        if line.strip() and not line.strip().startswith(('"', "!"))
    ]

    if len(non_header) < 2:
        raise ValueError(
            "SILO file appears to have no data block — only header lines found."
        )

    col_names = non_header[0].split()

    # The second non-header line is the units row if it starts with '('
    if non_header[1].strip().startswith("("):
        data_lines = non_header[2:]
    else:
        data_lines = non_header[1:]

    if not data_lines:
        raise ValueError("SILO file has a column header but no data rows.")

    content = "\n".join(line.rstrip() for line in data_lines)
    df = pd.read_csv(
        StringIO(content),
        sep=r"\s+",
        header=None,
        names=col_names,
        dtype=str,
    )
    return df


def _read_silo_csv(path: Path, variable: str) -> pd.DataFrame:
    """Parse a SILO custom CSV (comma-separated, no metadata header)."""
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    # Locate the requested variable column (case-insensitive exact, then prefix)
    var_lower = variable.lower()
    match = next((c for c in df.columns if c.lower() == var_lower), None)
    if match is None:
        match = next(
            (c for c in df.columns if c.lower().startswith(var_lower)), None
        )
    if match is None:
        if variable == "Rain":
            # Fallback: any column with 'rain' in its name
            match = next(
                (c for c in df.columns if "rain" in c.lower()), None
            )
    if match is None:
        raise ValueError(
            f"Variable '{variable}' not found in SILO CSV columns: "
            f"{list(df.columns)}. "
            "Use the `variable` parameter to specify the correct column name."
        )

    # Rename to the canonical variable name so _normalise_silo_df can find it
    if match != variable:
        df = df.rename(columns={match: variable})

    return df


def _normalise_silo_df(
    df: pd.DataFrame, variable: str, output_col: str, resolution: str = "monthly"
) -> pd.DataFrame:
    """Common normalisation: parse Date, locate rainfall column, aggregate daily→monthly."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # ------------------------------------------------------------------
    # Date column
    # ------------------------------------------------------------------
    date_col = next((c for c in df.columns if c.lower() == "date"), None)
    if date_col is None:
        raise ValueError(
            "No 'Date' column found in SILO data. "
            "SILO files should have a 'Date' column in yyyymmdd format."
        )

    raw_dates = df[date_col].astype(str).str.strip()
    # Try yyyymmdd first; fall back to pandas generic parser
    if raw_dates.str.match(r"^\d{8}$").all():
        df[date_col] = pd.to_datetime(raw_dates, format="%Y%m%d", errors="coerce")
    else:
        df[date_col] = pd.to_datetime(raw_dates, errors="coerce")

    n_bad = int(df[date_col].isna().sum())
    if n_bad:
        df = df.dropna(subset=[date_col])
        logger.warning("SILO reader: dropped %d rows with unparseable dates.", n_bad)

    # ------------------------------------------------------------------
    # Rainfall column
    # ------------------------------------------------------------------
    var_lower = variable.lower()
    var_col = next((c for c in df.columns if c.lower() == var_lower), None)
    if var_col is None:
        var_col = next(
            (c for c in df.columns if c.lower().startswith(var_lower[:4])), None
        )
    if var_col is None:
        raise ValueError(
            f"Column '{variable}' not found in SILO data. "
            f"Available columns: {list(df.columns)}"
        )

    df[var_col] = pd.to_numeric(df[var_col], errors="coerce")

    n_nan = int(df[var_col].isna().sum())
    if n_nan:
        logger.warning(
            "SILO reader: dropped %d rows with missing '%s' values.", n_nan, var_col
        )
        df = df.dropna(subset=[var_col])

    # ------------------------------------------------------------------
    # Daily → monthly aggregation (if needed)
    # ------------------------------------------------------------------
    periods = df[date_col].dt.to_period("M")
    if resolution == "monthly" and periods.value_counts().max() > 1:
        # Daily (or sub-monthly) data — aggregate by summing
        df["_period"] = periods
        agg = df.groupby("_period", sort=True)[var_col].sum().reset_index()
        agg["Date"] = agg["_period"].dt.to_timestamp()
        df = agg[["Date", var_col]].copy()
        logger.info(
            "SILO reader: aggregated daily data to %d monthly totals.", len(df)
        )
    else:
        df = df[[date_col, var_col]].copy()
        df = df.rename(columns={date_col: "Date"})

    # ------------------------------------------------------------------
    # Final columns
    # ------------------------------------------------------------------
    df = df.rename(columns={var_col: output_col})
    df["Year"] = df["Date"].dt.year.astype(int)
    df["Month"] = df["Date"].dt.month.astype(int)
    df = (
        df[["Date", "Year", "Month", output_col]]
        .sort_values("Date")
        .reset_index(drop=True)
    )
    return df
