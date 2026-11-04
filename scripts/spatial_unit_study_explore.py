"""Exploratory (post hoc) tables for the spatial unit study.

Not part of the pre-registered decisions in
docs/handoff/2026-11-02-spatial-unit-study-plan.md. Reads the study's
outcomes table and units and writes
docs/handoff/2026-11-02-spatial-unit-study-exploratory.json.

    python scripts/spatial_unit_study_explore.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spatial_unit_study import DEFAULT_OUT, REPO_ROOT, clean_json  # noqa: E402

TARGET = REPO_ROOT / "docs" / "handoff" / "2026-11-02-spatial-unit-study-exploratory.json"
WATER_ORDER = ["[0,100)", "[100,1000)", "[1000,10000)", "[10000,100000)"]


def circular(a: pd.Series, b: pd.Series) -> pd.Series:
    d = (a - b).abs() % 12
    return np.minimum(d, 12 - d)


def build(out: Path) -> dict:
    import geopandas as gpd

    table = pd.read_csv(out / "outcomes_table.csv")
    catch = table[table["type"] == "catchment"].set_index("key")
    seasonal = sorted(catch.index[catch["routed_seasonal"] == 1])

    # 1. Cycle quality and agreement with the catchment's climatological
    #    timing, by water-pixel size, in the seasonal catchments.
    units = table[table["key"].isin(seasonal) & (table["type"] != "catchment")].copy()
    units["peak_within_1_month"] = circular(units["peak_month"], units["key"].map(catch["peak_month"])) <= 1
    units["trough_within_1_month"] = circular(units["trough_month"], units["key"].map(catch["trough_month"])) <= 1
    routed = units[units["routed_seasonal"] == 1]
    quality = {}
    for (unit_type, water_bin), group in routed.groupby(["type", "water_bin"]):
        if water_bin not in WATER_ORDER:
            continue
        quality.setdefault(unit_type, {})[water_bin] = {
            "n": int(len(group)),
            "confirmed_share_mean": float(group["confirmed_share"].mean()),
            "trough_point_share_mean": float(group["trough_point_share"].mean()),
            "baseline_eligible_share_mean": float(group["baseline_eligible_share"].mean()),
            "peak_within_1_month_of_catchment": float(group["peak_within_1_month"].mean()),
            "trough_within_1_month_of_catchment": float(group["trough_within_1_month"].mean()),
        }

    # 2. Catchment versus subbasin trough timing resolution.
    resolution = {
        key: {
            "catchment_trough_point_share": float(catch.loc[key, "trough_point_share"]),
            "hb7_seasonal_median_trough_point_share": float(
                table[(table["key"] == key) & (table["scheme"] == "hb7") & (table["routed_seasonal"] == 1)]["trough_point_share"].median()
            ),
        }
        for key in seasonal
    }

    # 3. Where the seasonal subbasins of the aseasonal catchments are.
    geoms = gpd.read_file(out / "units.gpkg")[["unit_id", "geometry"]]
    hidden = {}
    for key in sorted(catch.index[catch["routed_seasonal"] != 1]):
        hidden[key] = {}
        for scheme in ("hb7", "hb8", "tile7", "tile8"):
            frame = geoms.merge(table[(table["key"] == key) & (table["scheme"] == scheme)], on="unit_id")
            if frame.empty:
                continue
            frame["easting_km"] = frame.geometry.centroid.x / 1000
            thirds = pd.qcut(frame["easting_km"], 3, labels=["west", "middle", "east"])
            seasonal_units = frame[frame["routed_seasonal"] == 1]
            hidden[key][scheme] = {
                "n": int(len(frame)),
                "routed_seasonal_share": float(frame["routed_seasonal"].mean()),
                "routed_seasonal_share_by_easting_third": {
                    str(k): float(v) for k, v in frame.groupby(thirds, observed=True)["routed_seasonal"].mean().items()
                },
                "median_monthly_water_pixels": {
                    "seasonal": float(frame.loc[frame["routed_seasonal"] == 1, "median_n_water"].median()) if len(seasonal_units) else None,
                    "not_seasonal": float(frame.loc[frame["routed_seasonal"] != 1, "median_n_water"].median()),
                },
                "seasonal_peak_months": {str(int(k)): int(v) for k, v in seasonal_units["peak_month"].value_counts().sort_index().items()},
                "seasonal_trough_months": {str(int(k)): int(v) for k, v in seasonal_units["trough_month"].value_counts().sort_index().items()},
            }

    water = table.groupby("scheme")["median_n_water"].quantile([0.1, 0.5, 0.9]).unstack()
    return {
        "note": "Exploratory, post hoc; not part of the pre-registered decisions.",
        "seasonal_catchments": seasonal,
        "quality_and_timing_by_water_pixels": quality,
        "catchment_vs_hb7_trough_resolution": resolution,
        "seasonal_units_inside_aseasonal_catchments": hidden,
        "median_monthly_water_pixels_by_scheme": {
            scheme: {"p10": float(row[0.1]), "p50": float(row[0.5]), "p90": float(row[0.9])} for scheme, row in water.iterrows()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = build(args.out)
    TARGET.write_text(json.dumps(clean_json(result), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
