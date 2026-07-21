from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from hydroseason import load_aoi
from hydroseason.io import load_wofs_monthly_extent

# Default output CRS: Australian Albers (EPSG:3577)
DEA_ALBERS_CRS = 3577


def add_provenance(frame: pd.DataFrame, *, source: str, aoi: str) -> pd.DataFrame:
    result = frame.copy()
    result.index = pd.to_datetime(result.index)
    result.index.name = "date"
    result["source"] = source
    result["aoi"] = aoi
    return result


def build(
    aoi_path: Path,
    output: Path,
    start: str,
    end: str,
    cache_dir: Path,
    *,
    resolution: float = 30.0,
    tile_pixels: int = 1024,
) -> None:
    aoi = load_aoi(aoi_path)
    extent = load_wofs_monthly_extent(
        "https://explorer.dea.ga.gov.au/stac",
        "ga_ls_wo_3",
        aoi,
        start,
        end,
        crs=DEA_ALBERS_CRS,
        resolution=resolution,
        tile_pixels=tile_pixels,
        cache_dir=cache_dir,
        time_block=12,
    )
    extent = add_provenance(
        extent,
        source="DEA Water Observations ga_ls_wo_3",
        aoi=aoi_path.as_posix(),
    )
    expected = pd.date_range(start, end, freq="MS")
    if not extent.index.equals(expected):
        raise RuntimeError("DEA fixture does not contain exactly one row per requested month")
    output.parent.mkdir(parents=True, exist_ok=True)
    extent.to_csv(output, date_format="%Y-%m-%d")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aoi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--resolution", type=float, default=30.0)
    parser.add_argument(
        "--tile-pixels",
        type=int,
        default=1024,
        help="non-overlapping Albers tile edge in pixels (default: 1024)",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("output/real_extent_cache")
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    build(
        args.aoi,
        args.output,
        args.start,
        args.end,
        args.cache_dir,
        resolution=args.resolution,
        tile_pixels=args.tile_pixels,
    )


if __name__ == "__main__":
    main()
