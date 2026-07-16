from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from hydroseason import load_aoi, load_wofs_from_stac, monthly_water_extent


def add_provenance(frame: pd.DataFrame, *, source: str, aoi: str) -> pd.DataFrame:
    result = frame.copy()
    result.index = pd.to_datetime(result.index)
    result.index.name = "date"
    result["source"] = source
    result["aoi"] = aoi
    return result


def build(aoi_path: Path, output: Path, start: str, end: str) -> None:
    aoi = load_aoi(aoi_path)
    masks = load_wofs_from_stac(
        "https://explorer.dea.ga.gov.au/stac",
        "ga_ls_wo_3",
        aoi,
        start,
        end,
    )
    extent = add_provenance(
        monthly_water_extent(masks),
        source="DEA Water Observations ga_ls_wo_3",
        aoi=aoi_path.as_posix(),
    )
    expected = pd.date_range(start, end, freq="MS")
    if not extent.index.equals(expected):
        raise RuntimeError("DEA fixture does not contain exactly one row per requested month")
    output.parent.mkdir(parents=True, exist_ok=True)
    extent.to_csv(output, date_format="%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aoi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2025-12-31")
    args = parser.parse_args()
    build(args.aoi, args.output, args.start, args.end)


if __name__ == "__main__":
    main()
