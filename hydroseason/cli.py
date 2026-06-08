"""CLI for HydroSeason."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_config
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydroseason",
        description="Rainfall-based hydrological season and year delineation",
    )
    from . import __version__
    parser.add_argument(
        "--version", action="version", version=f"hydroseason {__version__}"
    )
    parser.add_argument("--verbose", "-v", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser(
        "run",
        help="Run delineation pipeline from YAML config",
    )
    run_p.add_argument("--config", required=True)

    demo_p = sub.add_parser("demo", help="Run on the bundled fixture")
    demo_p.add_argument(
        "--out",
        default="output/demo_results.csv",
        help="Output CSV path. Parent folder is created automatically.",
    )

    fetch_p = sub.add_parser(
        "fetch",
        help=(
            "Fetch monthly AOI-averaged rainfall (auto/SILO/CHIRPS/ERA5) from "
            "GeoJSON/SHP/KML/KMZ/GPKG/GPCK vectors"
        ),
    )
    fetch_p.add_argument(
        "--source",
        default="auto",
        choices=["auto", "silo", "chirps", "era5"],
    )
    fetch_p.add_argument(
        "--path",
        default=None,
        help="Optional source path/base URL override.",
    )
    fetch_p.add_argument("--silo-base-url", default=None)
    fetch_p.add_argument("--chirps-base-url", default=None)
    fetch_p.add_argument("--vector", required=True)
    fetch_p.add_argument("--start-year", required=True, type=int)
    fetch_p.add_argument("--end-year", required=True, type=int)
    fetch_p.add_argument(
        "--output",
        required=True,
        help="Output CSV path. Parent folder is created automatically.",
    )
    fetch_p.add_argument(
        "--variable",
        default="rainfall",
        help="ERA5 rainfall selector. Only 'rainfall' is supported.",
    )
    fetch_p.add_argument("--cache-dir", default=None)
    fetch_p.add_argument("--spatial-chunk", default="auto")
    fetch_p.add_argument("--time-chunk", default="auto")
    fetch_p.add_argument("--temporal-batch-years", default="auto")
    fetch_p.add_argument(
        "--era5-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    fetch_p.add_argument(
        "--large-era5-fallback",
        default="ask",
        choices=["ask", "allow", "error"],
        help=(
            "What to do before an implicit large ERA5 fallback (>60 months): "
            "'ask' prompts for up to 5 minutes, 'allow' proceeds, "
            "'error' fails fast."
        ),
    )

    rain_p = sub.add_parser(
        "rainfall",
        help="Read rainfall data (auto/BOM/SILO/CSV) and run delineation",
    )
    rain_p.add_argument("--input", required=True)
    rain_p.add_argument(
        "--output",
        required=True,
        help="Output CSV path. Parent folder is created automatically.",
    )
    rain_p.add_argument(
        "--source",
        default="auto",
        choices=["auto", "bom", "silo", "csv"],
    )
    rain_p.add_argument("--value-col", default="Rainfall_mm")
    rain_p.add_argument("--silo-variable", default="Rain")
    rain_p.add_argument("--bom-value-col", default=None)
    rain_p.add_argument("--keep-bom-non-y", action="store_true")
    return parser


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.command == "run":
        run_pipeline(load_config(args.config))
        return 0

    if args.command == "demo":
        from importlib.resources import as_file, files

        from .pipeline import classify_rainfall_from_file
        fixture = files("hydroseason").joinpath("data/monthly_rainfall.csv")
        with as_file(fixture) as fixture_path:
            artifacts = classify_rainfall_from_file(
                fixture_path,
                output_csv=args.out,
            )
        print("Regime:", artifacts.diagnostics.regime)
        print("STL strength:", round(artifacts.diagnostics.stl_strength, 3))
        print(
            "Walsh-Lawler SI:",
            round(artifacts.diagnostics.walsh_lawler_si, 3),
        )
        print(
            "Hydro-year start month:",
            artifacts.diagnostics.hydro_year_start_month,
        )
        print(f"Wrote: {args.out}")
        return 0

    if args.command == "fetch":
        from .fetch import (
            get_monthly_aoi_rainfall,
            load_vector,
        )

        gdf = load_vector(args.vector)

        kwargs = {
            "gdf": gdf,
            "start_year": args.start_year,
            "end_year": args.end_year,
            "source": args.source,
            "era5_zarr_path": args.path,
            "silo_base_url": args.silo_base_url or (args.path if args.source == "silo" else None),
            "variable": args.variable,
            "cache_dir": args.cache_dir,
            "spatial_chunk": args.spatial_chunk,
            "time_chunk": args.time_chunk,
            "temporal_batch_years": args.temporal_batch_years,
            "era5_fallback": args.era5_fallback,
            "large_era5_fallback": args.large_era5_fallback,
        }
        if args.chirps_base_url:
            kwargs["chirps_base_url"] = args.chirps_base_url
        monthly_df = get_monthly_aoi_rainfall(**kwargs)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        monthly_df.to_csv(out_path, index=False)
        return 0

    if args.command == "rainfall":
        from .pipeline import classify_rainfall_from_file

        artifacts = classify_rainfall_from_file(
            args.input,
            source=args.source,
            value_col=args.value_col,
            output_csv=args.output,
            silo_variable=args.silo_variable,
            bom_value_col=args.bom_value_col,
            bom_quality_filter=not args.keep_bom_non_y,
        )
        print("Regime:", artifacts.diagnostics.regime)
        print("STL strength:", round(artifacts.diagnostics.stl_strength, 3))
        print(
            "Walsh-Lawler SI:",
            round(artifacts.diagnostics.walsh_lawler_si, 3),
        )
        print(
            "Hydro-year start month:",
            artifacts.diagnostics.hydro_year_start_month,
        )
        print(f"Wrote: {args.output}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
