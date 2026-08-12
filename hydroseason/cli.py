"""Command-line entry point: one `run_hydroseason` call in its own process.

Exists for process isolation, not for extra features. A 21-year DEA fetch
runs for hours inside native GDAL/PROJ/NumPy code; when that aborts the
interpreter, a notebook kernel loses every variable the user had, while a
CLI process loses nothing but itself, and its cache directory lets the next
invocation resume. This is also why the parser is deliberately thin: it
translates path and scalar arguments and calls the orchestrator exactly
once. It never reimplements input resolution, analysis, rainfall, or
reporting, so it cannot drift from the notebook path.

In-memory DataFrames and xarray objects stay kernel-only, and
``analysis_options`` stays Python-only until a serialization contract for it
is designed -- exposing a half-serialized subset would be a second, subtly
different API.

Exit status: 0 on success (including an ancillary rainfall failure, which
``run_hydroseason`` treats as non-fatal by design), 1 on a fatal water-input,
analysis, or report-writing failure, 2 on a usage error from argparse.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from ._diagnostics import check_environment
from .workflow import run_hydroseason

_STATUS_MARK = {"ok": "ok  ", "warning": "warn", "error": "FAIL"}


def _build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="hydroseason",
        description=(
            "Hydro-year and season detection from monthly surface-water "
            "extent."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run",
        help="Resolve water input, analyze it, and write the report bundle.",
        description=(
            "Runs hydroseason.run_hydroseason once in this process. Omit "
            "--water-source to fetch DEA WOfS, which then requires --aoi, "
            "--start-date, and --end-date."
        ),
    )
    run.add_argument(
        "--water-source",
        help=(
            "Extent CSV, canonical NetCDF/Zarr water mask, or omitted to "
            "fetch DEA WOfS."
        ),
    )
    run.add_argument("--output-dir", required=True, help="Report bundle directory.")
    run.add_argument("--aoi", help="AOI vector path (GeoJSON, GeoPackage, shapefile).")
    run.add_argument("--aoi-name", help="Display name used in the report.")
    run.add_argument("--start-date", help="First month, YYYY-MM-DD.")
    run.add_argument("--end-date", help="Last month, YYYY-MM-DD.")
    run.add_argument(
        "--water-mask-variable",
        help="Variable to read from a NetCDF/Zarr source with several.",
    )
    run.add_argument(
        "--rainfall-csv",
        help=(
            "Monthly rainfall CSV. Takes precedence over --fetch-rainfall: "
            "SILO is never called when this is given."
        ),
    )
    run.add_argument(
        "--fetch-rainfall",
        action="store_true",
        help="Fetch SILO rainfall over the resolved water-extent years.",
    )
    run.add_argument("--stac-url", help="STAC endpoint for both DEA searches.")
    run.add_argument(
        "--statistics-stac-url",
        help=(
            "Override the historical-statistics STAC endpoint. Defaults to "
            "--stac-url; pass this only to use two different services."
        ),
    )
    run.add_argument("--stac-collection", help="Monthly WOfS collection id.")
    run.add_argument(
        "--cache-dir",
        help=(
            "Reusable cache root. An interrupted DEA run resumes from its "
            "last completed calendar year on the next invocation."
        ),
    )
    run.add_argument("--report-title", help="HTML report title.")
    run.add_argument("--report-subtitle", help="HTML report subtitle.")
    run.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write step progress to standard error (default: on).",
    )
    run.add_argument(
        "--json",
        action="store_true",
        help="Print the result summary as JSON on standard output.",
    )

    subparsers.add_parser(
        "doctor",
        help="Report the interpreter and optional-dependency status.",
        description=(
            "Probes the interpreter and every raster/stac dependency, "
            "including the netCDF4/NumPy ABI check. Exit status is nonzero "
            "if any check failed."
        ),
    )
    return parser


def _summary(result) -> dict:
    return {
        "source_kind": result.source_kind,
        "regime": result.analysis.regime.regime,
        "route": result.analysis.route,
        "rainfall_status": result.rainfall_status,
        "rainfall_source": result.rainfall_source,
        "rainfall_error": result.rainfall_error,
        "html": str(result.artifacts.html),
        "monthly_csv": str(result.artifacts.monthly_csv),
        "hydro_years_csv": str(result.artifacts.hydro_years_csv),
        "wet_event_csv": str(result.artifacts.wet_event_csv),
        "low_spells_csv": str(result.artifacts.low_spells_csv),
        "warnings": list(result.warnings),
    }


def _run(args: argparse.Namespace) -> int:
    kwargs = {
        "output_dir": args.output_dir,
        "aoi": args.aoi,
        "aoi_name": args.aoi_name,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "water_mask_variable": args.water_mask_variable,
        "rainfall_csv_path": args.rainfall_csv,
        "fetch_rainfall": args.fetch_rainfall,
        "statistics_stac_url": args.statistics_stac_url,
        "cache_dir": args.cache_dir,
        "report_title": args.report_title,
        "report_subtitle": args.report_subtitle,
        "progress": args.progress,
        "show_map": False,
    }
    # Left out entirely when unset so run_hydroseason's own documented
    # defaults apply, rather than this parser owning a second copy of them.
    if args.stac_url is not None:
        kwargs["stac_url"] = args.stac_url
    if args.stac_collection is not None:
        kwargs["stac_collection"] = args.stac_collection

    try:
        result = run_hydroseason(args.water_source, **kwargs)
    except Exception as exc:
        print(f"hydroseason run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    summary = _summary(result)
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"source kind      : {summary['source_kind']}")
    print(f"regime           : {summary['regime']}")
    print(f"route            : {summary['route']}")
    print(f"rainfall         : {summary['rainfall_status']} ({summary['rainfall_source']})")
    if summary["rainfall_error"]:
        print(f"rainfall error   : {summary['rainfall_error']}", file=sys.stderr)
    print(f"html report      : {summary['html']}")
    print(f"monthly csv      : {summary['monthly_csv']}")
    print(f"hydro years csv  : {summary['hydro_years_csv']}")
    print(f"wet events csv   : {summary['wet_event_csv']}")
    print(f"low spells csv   : {summary['low_spells_csv']}")
    for message in summary["warnings"]:
        print(f"warning: {message}", file=sys.stderr)
    return 0


def _doctor() -> int:
    checks = check_environment()
    failed = 0
    for check in checks:
        if check.status == "error":
            failed += 1
        print(f"{_STATUS_MARK[check.status]}  {check.name:<14} {check.detail}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    return _run(args)


__all__ = ["main"]
