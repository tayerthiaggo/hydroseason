"""CLI for HydroSeason."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_config
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hydroseason", description="Hydrological season and year delineation")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run delineation pipeline from YAML config")
    run_p.add_argument("--config", required=True)

    demo_p = sub.add_parser("demo", help="Run on the bundled fixture")
    demo_p.add_argument("--out", default="output/demo_results.csv")

    fetch_p = sub.add_parser(
        "fetch",
        help="Fetch monthly AOI-averaged climate data (ERA5 or SILO) from GeoJSON/SHP/KML/KMZ/GPKG/GPCK vectors",
    )
    fetch_p.add_argument("--source", default="era5", choices=["era5", "silo"])
    fetch_p.add_argument("--path", default=None)
    fetch_p.add_argument("--silo-base-url", default=None)
    fetch_p.add_argument("--vector", required=True)
    fetch_p.add_argument("--start-year", required=True, type=int)
    fetch_p.add_argument("--end-year", required=True, type=int)
    fetch_p.add_argument("--output", required=True)
    fetch_p.add_argument("--variable", default="rainfall")
    fetch_p.add_argument("--cache-dir", default=None)
    fetch_p.add_argument("--spatial-chunk", type=int, default=50)

    rain_p = sub.add_parser(
        "rainfall",
        help="Read rainfall data (auto/BOM/SILO/CSV) and run delineation",
    )
    rain_p.add_argument("--input", required=True)
    rain_p.add_argument("--output", required=True)
    rain_p.add_argument("--source", default="auto", choices=["auto", "bom", "silo", "csv"])
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
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.command == "run":
        run_pipeline(load_config(args.config))
        return 0

    if args.command == "demo":
        from importlib.resources import as_file, files

        from .pipeline import run_pipeline_from_csv
        fixture = files("hydroseason").joinpath("data/monthly_rainfall.csv")
        with as_file(fixture) as fixture_path:
            artifacts = run_pipeline_from_csv(fixture_path, output_csv=args.out)
        print("Regime:", artifacts.diagnostics.regime)
        print("STL strength:", round(artifacts.diagnostics.stl_strength, 3))
        print("Walsh-Lawler SI:", round(artifacts.diagnostics.walsh_lawler_si, 3))
        print("Hydro-year start month:", artifacts.diagnostics.hydro_year_start_month)
        print(f"Wrote: {args.out}")
        return 0

    if args.command == "fetch":
        from .fetch import get_monthly_silo_rainfall, get_monthly_variable, load_vector

        if args.source == "era5" and not args.path:
            raise ValueError("--path is required when --source era5")

        gdf = load_vector(args.vector)

        if args.source == "era5":
            monthly_df = get_monthly_variable(
                path=args.path,
                gdf=gdf,
                start_year=args.start_year,
                end_year=args.end_year,
                variable=args.variable,
                cache_dir=args.cache_dir,
                spatial_chunk=args.spatial_chunk,
            )
        else:
            kwargs = {
                "gdf": gdf,
                "start_year": args.start_year,
                "end_year": args.end_year,
                "cache_dir": args.cache_dir,
                "spatial_chunk": args.spatial_chunk,
            }
            silo_base_url = args.silo_base_url or args.path
            if silo_base_url:
                kwargs["base_url"] = silo_base_url
            monthly_df = get_monthly_silo_rainfall(**kwargs)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        monthly_df.to_csv(out_path, index=False)
        return 0

    if args.command == "rainfall":
        from .pipeline import run_rainfall

        artifacts = run_rainfall(
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
        print("Walsh-Lawler SI:", round(artifacts.diagnostics.walsh_lawler_si, 3))
        print("Hydro-year start month:", artifacts.diagnostics.hydro_year_start_month)
        print(f"Wrote: {args.output}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
