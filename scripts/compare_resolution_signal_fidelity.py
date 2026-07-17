"""Empirical, real-STAC-data comparison of native 30m vs. a coarsened resolution.

Standalone, one-off empirical artifact -- NOT part of the pytest suite (it
needs live network access to the real DEA STAC endpoint, so wiring it into
CI would make the suite flaky/slow/network-dependent). Run it directly:

    python scripts/compare_resolution_signal_fidelity.py

Purpose
-------
The lazy/bounded multi-catchment extent gate (`plan_resolution` +
`probe_amplitude` in `hydroseason/io.py`) coarsens resolution to fit a memory
budget, subject to a signal-preservation veto. That veto is derived from a
noise-floor *estimate* (`100 / n_pixels`), not from measuring the real
seasonal signal at both resolutions side by side. This script does the real
measurement once, empirically, on a small representative subwindow of a real
catchment, using real DEA STAC data -- to sanity-check that the gate's
estimate-based veto is in the right ballpark versus what actually happens to
the amplitude/pattern signal when you coarsen.

Catchment and subwindow
------------------------
Catchment: `moonie_river_qld_nsw` (data/catchments/moonie_river_qld_nsw_*).
Verified against the boundary file's own `area_km2` field (not assumed from
docs): 14,654.9 km^2, the smallest of the six catchments checked in
`data/catchments/` (Daly 54,670; Fitzroy 97,201; Gilbert 22,016; Lachlan
77,051; Paroo 73,552 km^2) -- see `_verify_smallest_catchment` below for the
exact check performed.

Subwindow: rather than the whole ~14,655 km^2 catchment (too slow/costly for
a quick empirical check), this uses a small bounding box around a real,
verified stretch of the Moonie River's main channel (WOfS/streams data
confirms 6 "MOONIE RIVER" / hierarchy="Major" reaches intersect this bbox --
see `_verify_subwindow_has_stream_reaches` below), buffered out to ~10km x
11km so it also contains surrounding floodplain (dry land), not just the
channel itself. This gives genuine wet/dry heterogeneity in a small area:
representative of real water/land mixing, without paying for a full-basin
load. Bbox (WGS84): (148.6140, -29.2750, 148.7140, -29.1750).

Why this bbox specifically, and not the full catchment gate logic: running
`plan_resolution`/`probe_amplitude`'s full gate on this subwindow's real
bbox+memory-budget was tried first (see `_gate_recommendation_for_reference`
below) -- but the subwindow is so small that even a very tight 0.01 GB
memory budget only coarsens the gate's pick to 60m (peak_gb at native 30m
here is ~0.018 GB, three orders of magnitude under a realistic budget). No
plausible memory budget would make the gate choose 100m or 150m for a
window this size. So, per the deliverable's own guidance, this script picks
a concrete coarser candidate from the default ladder directly: **100m**,
documented here as a deliberate choice representing a resolution the gate
plausibly WOULD choose for a larger catchment (or tighter budget) -- not
what it would choose for this particular small subwindow.

Date range: 2018-01-01 to 2020-12-31 (3 years, 36 months) -- long enough to
span multiple wet/dry cycles for a meaningful amplitude estimate, short
enough to keep STAC query + dask compositing time reasonable for a quick
empirical check (vs. the runner's full 2015-2025 range).

Pipeline mirrored from `probe_amplitude` (hydroseason/io.py): for each
resolution, `load_wofs_from_stac(..., resolution=res)` ->
`monthly_water_extent` (raw pixel counts) -> `prepare_monthly_extent`
(quality screening) -> `_boundary.robust_scale` (10th-90th percentile
spread of extent_pct among usable rows = amplitude_pp; MAD-based
month-to-month noise estimate = noise_pp). This is the exact same
amplitude/noise definition the gate's signal veto is calibrated against.

What gets reported
-------------------
- amplitude_pp and noise_pp at both resolutions, and their deltas.
- Correlation between the two monthly extent_pct series (aligned by month).
- Max and mean absolute difference in extent_pct per month.
- Whether the same wet/dry months (argmax/argmin of extent_pct) are
  identified at both resolutions.
- Results are printed to stdout and also written as JSON to
  `output/resolution_fidelity_comparison.json` for later reference.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason._boundary import robust_scale  # noqa: E402
from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason.hydro_year import monthly_water_extent  # noqa: E402
from hydroseason.io import load_wofs_from_stac, plan_resolution  # noqa: E402

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
OUTPUT_CRS = 3577  # GDA94 / Australian Albers

CATCHMENT_KEY = "moonie_river_qld_nsw"
CATCHMENTS_DIR = REPO_ROOT / "data" / "catchments"

# Small representative subwindow of the Moonie River's main channel, verified
# (see module docstring + _verify_subwindow_has_stream_reaches) to contain a
# real stretch of channel plus surrounding floodplain. WGS84 (minx, miny, maxx, maxy).
SUBWINDOW_BBOX_WGS84 = (148.61402789500005, -29.27499990549997, 148.71402789500007, -29.17499990549997)

# Modest 3-year window: spans multiple wet/dry cycles, keeps STAC query time reasonable.
START_DATE = "2018-01-01"
END_DATE = "2020-12-31"

NATIVE_RES_M = 30.0
COARSE_RES_M = 100.0  # concrete ladder candidate -- see module docstring for why.

OUTPUT_JSON = REPO_ROOT / "output" / "resolution_fidelity_comparison.json"


def _verify_smallest_catchment() -> dict:
    """Check every boundary file's real area_km2 field; confirm Moonie is smallest."""
    import geopandas as gpd

    areas = {}
    for f in sorted(CATCHMENTS_DIR.glob("*_boundary.geojson")):
        gdf = gpd.read_file(f)
        areas[f.stem.removesuffix("_boundary")] = float(gdf.iloc[0]["area_km2"])
    smallest = min(areas, key=areas.get)
    print(f"Catchment areas (km^2), verified from boundary files: {areas}")
    print(f"Smallest: {smallest} ({areas[smallest]:,.1f} km^2)")
    if smallest != CATCHMENT_KEY:
        print(
            f"WARNING: smallest catchment is {smallest}, not {CATCHMENT_KEY} -- "
            f"proceeding with {CATCHMENT_KEY} anyway per script configuration."
        )
    return areas


def _verify_subwindow_has_stream_reaches() -> int:
    """Confirm the chosen bbox genuinely intersects real Moonie River channel reaches."""
    import geopandas as gpd
    from shapely.geometry import box

    streams_path = CATCHMENTS_DIR / f"{CATCHMENT_KEY}_streams.geojson"
    streams = gpd.read_file(streams_path).to_crs(4326)
    bb = box(*SUBWINDOW_BBOX_WGS84)
    hits = streams[streams.intersects(bb)]
    n_major_moonie = int(
        ((hits["name"].astype(str).str.contains("Moonie", case=False, na=False)) & (hits["hierarchy"] == "Major")).sum()
    )
    print(f"Subwindow intersects {len(hits)} stream reaches ({n_major_moonie} are 'MOONIE RIVER'/Major).")
    if n_major_moonie == 0:
        raise RuntimeError("Subwindow does not contain a real Moonie River main-channel reach -- bbox is wrong.")
    return n_major_moonie


def _gate_recommendation_for_reference() -> None:
    """Print what plan_resolution would recommend for this subwindow, for context.

    Not used to choose COARSE_RES_M (see module docstring for why) -- purely
    informational, so the report shows the gate's own answer alongside the
    concrete ladder candidate this script actually measures.
    """
    for budget in (12.0, 1.0, 0.1, 0.01, 0.001):
        res, peak_gb, floor_pp, reason = plan_resolution(
            SUBWINDOW_BBOX_WGS84, OUTPUT_CRS, memory_budget_gb=budget,
        )
        print(
            f"  plan_resolution(memory_budget_gb={budget}) -> resolution_m={res}, "
            f"peak_gb={peak_gb:.6f}, floor_pp={floor_pp:.4f}, reason={reason}"
        )


def _subwindow_aoi_gdf():
    import geopandas as gpd
    from shapely.geometry import box

    return gpd.GeoDataFrame(geometry=[box(*SUBWINDOW_BBOX_WGS84)], crs="EPSG:4326")


def _run_pipeline_at_resolution(resolution_m: float) -> dict:
    """Mirror probe_amplitude's exact pipeline at a given resolution: load -> extent -> prepare -> robust_scale."""
    print(f"\n--- Loading real DEA STAC WOfS at {resolution_m:.0f} m resolution ---")
    aoi = _subwindow_aoi_gdf()
    water_mask = load_wofs_from_stac(
        STAC_URL, COLLECTION, aoi, START_DATE, END_DATE, crs=OUTPUT_CRS, resolution=resolution_m,
    )
    print(f"Cube loaded: {dict(water_mask.sizes)}")
    extent = monthly_water_extent(water_mask)
    prepared = prepare_monthly_extent(extent)
    amplitude_pp, noise_pp = robust_scale(prepared)
    n_usable = int(prepared["candidate_usable"].sum())
    print(
        f"resolution_m={resolution_m:.0f} amplitude_pp={amplitude_pp:.4f} "
        f"noise_pp={noise_pp:.4f} n_usable_months={n_usable}/{len(prepared)}"
    )
    return {
        "resolution_m": resolution_m,
        "amplitude_pp": amplitude_pp,
        "noise_pp": noise_pp,
        "n_usable_months": n_usable,
        "n_months_total": len(prepared),
        "prepared": prepared,
    }


def _compare_series(native: dict, coarse: dict) -> dict:
    """Quantify month-by-month agreement between the two resolutions' extent_pct series."""
    native_s = native["prepared"]["extent_pct"]
    coarse_s = coarse["prepared"]["extent_pct"]
    aligned = native_s.to_frame("native").join(coarse_s.to_frame("coarse"), how="inner").dropna()

    correlation = float(aligned["native"].corr(aligned["coarse"])) if len(aligned) >= 2 else float("nan")
    abs_diff = (aligned["native"] - aligned["coarse"]).abs()
    max_abs_diff = float(abs_diff.max()) if len(abs_diff) else float("nan")
    mean_abs_diff = float(abs_diff.mean()) if len(abs_diff) else float("nan")

    native_wet_month = aligned["native"].idxmax() if len(aligned) else None
    coarse_wet_month = aligned["coarse"].idxmax() if len(aligned) else None
    native_dry_month = aligned["native"].idxmin() if len(aligned) else None
    coarse_dry_month = aligned["coarse"].idxmin() if len(aligned) else None

    same_wet_month = native_wet_month == coarse_wet_month
    same_dry_month = native_dry_month == coarse_dry_month

    return {
        "n_months_compared": len(aligned),
        "correlation": correlation,
        "max_abs_diff_extent_pct": max_abs_diff,
        "mean_abs_diff_extent_pct": mean_abs_diff,
        "native_wet_month": str(native_wet_month) if native_wet_month is not None else None,
        "coarse_wet_month": str(coarse_wet_month) if coarse_wet_month is not None else None,
        "native_dry_month": str(native_dry_month) if native_dry_month is not None else None,
        "coarse_dry_month": str(coarse_dry_month) if coarse_dry_month is not None else None,
        "same_wet_month": same_wet_month,
        "same_dry_month": same_dry_month,
    }


def main() -> None:
    print("=" * 78)
    print("Empirical 30m-vs-coarsened signal fidelity comparison (real DEA STAC data)")
    print("=" * 78)

    _verify_smallest_catchment()
    _verify_subwindow_has_stream_reaches()

    print(f"\nSubwindow bbox (WGS84): {SUBWINDOW_BBOX_WGS84}")
    print(f"Date range: {START_DATE} .. {END_DATE}")
    print("\nFor reference, plan_resolution's own recommendation at this subwindow's real bbox:")
    _gate_recommendation_for_reference()
    print(
        f"\n(Subwindow is too small for any realistic budget to land on {COARSE_RES_M:.0f}m -- "
        f"this script measures {COARSE_RES_M:.0f}m directly as a concrete ladder candidate, "
        f"per the deliverable's documented fallback. See module docstring.)"
    )

    native = _run_pipeline_at_resolution(NATIVE_RES_M)
    coarse = _run_pipeline_at_resolution(COARSE_RES_M)

    comparison = _compare_series(native, coarse)

    amplitude_delta_pp = coarse["amplitude_pp"] - native["amplitude_pp"]
    noise_delta_pp = coarse["noise_pp"] - native["noise_pp"]

    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)
    print(f"Native  {NATIVE_RES_M:.0f}m: amplitude_pp={native['amplitude_pp']:.4f}  noise_pp={native['noise_pp']:.4f}")
    print(f"Coarse  {COARSE_RES_M:.0f}m: amplitude_pp={coarse['amplitude_pp']:.4f}  noise_pp={coarse['noise_pp']:.4f}")
    print(f"Delta (coarse - native): amplitude_pp={amplitude_delta_pp:+.4f}  noise_pp={noise_delta_pp:+.4f}")
    print(f"Monthly series correlation: {comparison['correlation']:.4f}")
    print(f"Max |extent_pct diff| across months: {comparison['max_abs_diff_extent_pct']:.4f} pp")
    print(f"Mean |extent_pct diff| across months: {comparison['mean_abs_diff_extent_pct']:.4f} pp")
    print(f"Same wettest month identified: {comparison['same_wet_month']} (native={comparison['native_wet_month']}, coarse={comparison['coarse_wet_month']})")
    print(f"Same driest month identified: {comparison['same_dry_month']} (native={comparison['native_dry_month']}, coarse={comparison['coarse_dry_month']})")

    results = {
        "catchment": CATCHMENT_KEY,
        "subwindow_bbox_wgs84": list(SUBWINDOW_BBOX_WGS84),
        "date_range": [START_DATE, END_DATE],
        "native_res_m": NATIVE_RES_M,
        "coarse_res_m": COARSE_RES_M,
        "native": {k: v for k, v in native.items() if k != "prepared"},
        "coarse": {k: v for k, v in coarse.items() if k != "prepared"},
        "amplitude_delta_pp": amplitude_delta_pp,
        "noise_delta_pp": noise_delta_pp,
        "comparison": comparison,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results written to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
